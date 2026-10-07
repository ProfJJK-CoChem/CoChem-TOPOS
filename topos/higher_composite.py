"""Explicit CFOUR CBS/CV/full-triples/full-quadruples geometry composites.

The numerical optimizer calls actual native single-point energies through the
durable component ledger. It does not fabricate analytic CCSDTQ derivatives,
claim a native CFOUR optimizer, or attach a family benchmark to chosen bases.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from threading import Event
from typing import Any, Literal

import numpy as np
from pydantic import Field, model_validator

from .composites import CompositeCoordinate, _geometry_parameters, _increment, _wrap_degrees
from .energy_composite import _BASIS_CARDINALS
from .external_engines import ExternalProtocol, run_external
from .matrix_components import run_component
from .models import Contract, Molecule
from .scans import constraint_system, project_scan_geometry
from .science import (
    BOHR_ANGSTROM,
    geometry_digest,
    rotational_constants,
    validate_stereochemical_preservation,
)
from .storage import IntegrityError, digest_json


class HigherCoordinateSet(Contract):
    """Independent internal chart, without a silently assumed CV basis."""

    coordinates: list[CompositeCoordinate]
    projection_tolerance_native: float = Field(default=1e-10, gt=0, le=1e-8)


class NumericalGeometryOptions(Contract):
    """Central energy differences at h and h/2; use the finer derivative."""

    step_bohr: float = Field(gt=1e-5, le=.02)
    maximum_step_disagreement_hartree_per_bohr: float = Field(gt=0, le=1e-5)
    gradient_max_hartree_per_bohr: float = Field(gt=0, le=1e-4)
    gradient_rms_hartree_per_bohr: float = Field(gt=0, le=1e-4)
    maximum_iterations: int = Field(default=200, ge=1, le=2000)

    @model_validator(mode="after")
    def error_below_convergence(self):
        if self.maximum_step_disagreement_hartree_per_bohr > min(
                self.gradient_max_hartree_per_bohr, self.gradient_rms_hartree_per_bohr) / 4:
            raise ValueError("Two-step derivative disagreement must be at most one quarter of both gradient convergence thresholds")
        return self


class HigherGeometryProtocol(Contract):
    """Every physical component and approximation is an explicit caller choice.

    R_inf is an inverse-power extrapolation of optimized internal parameters,
    not an energy extrapolation. fQ is CCSDTQ minus CCSDT in the same basis.
    """

    template: ExternalProtocol
    low_basis: str
    high_basis: str
    geometry_inverse_power: float = Field(gt=0, le=10)
    core_valence_basis: str
    full_triples_basis: str
    full_quadruples_basis: str
    coordinates: HigherCoordinateSet
    numerical_quadruples: NumericalGeometryOptions
    convention: Literal["explicit-geometry-CBS-CV-fT-fQ-v1"]

    @model_validator(mode="after")
    def exact_variant(self):
        template = self.template
        if (template.engine, template.engine_version, template.method, template.operation, template.frozen_core) != (
                "cfour", "2.1", "CCSD(T)", "optimize", True):
            raise ValueError("The higher geometry template is public CFOUR 2.1 frozen-core CCSD(T) optimization")
        if not template.genbas_path or not template.genbas_sha256:
            raise ValueError("Higher composites require one pinned native GENBAS path and SHA-256")
        if (self.low_basis not in _BASIS_CARDINALS or self.high_basis not in _BASIS_CARDINALS
                or _BASIS_CARDINALS[self.high_basis] != _BASIS_CARDINALS[self.low_basis] + 1):
            raise ValueError("Geometry CBS requires consecutive explicit cc-pVXZ bases or native PVXZ aliases")
        if self.cbs_denominator() < 1e-6:
            raise ValueError("Geometry extrapolation is numerically ill-conditioned")
        if not self.core_valence_basis.startswith(("cc-pCV", "cc-pwCV", "PCV", "PWCV")):
            raise ValueError("The same-basis ae-minus-fc increment requires an explicit core-valence basis")
        # Validate literal basis names and each actual native method/operation.
        self.protocols()
        return self

    def cbs_denominator(self) -> float:
        low, high = _BASIS_CARDINALS[self.low_basis], _BASIS_CARDINALS[self.high_basis]
        return -math.expm1(self.geometry_inverse_power * math.log(low / high))

    def protocols(self) -> dict[str, ExternalProtocol]:
        specifications = {
            "cc_low": ("CCSD(T)", self.low_basis, True),
            "cc_high": ("CCSD(T)", self.high_basis, True),
            "cv_ae": ("CCSD(T)", self.core_valence_basis, False),
            "cv_fc": ("CCSD(T)", self.core_valence_basis, True),
            "triples_full": ("CCSDT", self.full_triples_basis, True),
            "triples_parent": ("CCSD(T)", self.full_triples_basis, True),
            "quadruples_full": ("CCSDTQ", self.full_quadruples_basis, True),
            "quadruples_parent": ("CCSDT", self.full_quadruples_basis, True),
        }
        return {role: ExternalProtocol.model_validate({**self.template.model_dump(), "method": method,
                    "orbital_basis": basis, "frozen_core": core,
                    "operation": "energy" if role == "quadruples_full" else "optimize"})
                for role, (method, basis, core) in specifications.items()}


def checked_energy_gradient(energy: Callable[[np.ndarray], float], coordinates_bohr: np.ndarray,
                            options: NumericalGeometryOptions) -> tuple[float, np.ndarray, dict[str, Any]]:
    """Actual central energy derivatives with an explicit step-sensitivity test.

    This utility has no engine semantics. Its caller must provide independently
    verified energies at each displaced geometry. The h/h2 difference is a
    sensitivity diagnostic, not a rigorous uncertainty or Richardson claim.
    """
    options = NumericalGeometryOptions.model_validate(options.model_dump())
    x = np.asarray(coordinates_bohr, dtype=float)
    if x.ndim != 1 or not len(x) or len(x) % 3 or not np.all(np.isfinite(x)):
        raise ValueError("Numerical geometry derivatives require finite Cartesian coordinates in bohr")

    def actual(point: np.ndarray) -> float:
        value = energy(point.copy())
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)) or not math.isfinite(value):
            raise ValueError("Every numerical derivative displacement requires a finite actual energy")
        return float(value)

    center = actual(x)
    derivatives = []
    for step in (options.step_bohr, options.step_bohr / 2):
        gradient = np.empty_like(x)
        for index in range(len(x)):
            delta = np.zeros_like(x)
            delta[index] = step
            gradient[index] = (actual(x + delta) - actual(x - delta)) / (2 * step)
        derivatives.append(gradient)
    if not all(np.all(np.isfinite(value)) for value in derivatives):
        raise ValueError("Numerical energy differentiation produced a nonfinite derivative")
    spread = float(np.max(np.abs(derivatives[1] - derivatives[0])))
    if spread > options.maximum_step_disagreement_hartree_per_bohr:
        raise ValueError("Numerical energy derivative failed its two-step displacement sensitivity check")
    return center, derivatives[1], {
        "definition": "central differences of actual electronic energies at h and h/2; finer derivative retained",
        "steps_bohr": [options.step_bohr, options.step_bohr / 2],
        "coarse_gradient_hartree_per_bohr": derivatives[0].reshape(-1, 3).tolist(),
        "maximum_step_disagreement_hartree_per_bohr": spread,
        "rigorous_uncertainty_estimate": False, "analytic_derivative": False,
    }


def combine_higher_geometry(components: dict[str, Molecule], protocol: HigherGeometryProtocol) -> dict[str, Any]:
    """Parameter-wise CBS + CV + fT + fQ; never arithmetic on Cartesian frames."""
    from .workflow import _topology_preserved

    protocol = HigherGeometryProtocol.model_validate(protocol.model_dump())
    if set(components) != set(protocol.protocols()):
        raise ValueError("All eight optimized geometry components are required exactly once")
    components = {role: Molecule.model_validate(molecule.model_dump()) for role, molecule in components.items()}
    base = components["cc_low"]
    identity = base.model_dump(exclude={"coordinates", "name"})
    stereo = {}
    for role, molecule in components.items():
        if molecule.model_dump(exclude={"coordinates", "name"}) != identity:
            raise ValueError("Higher geometry components change molecular, isotope, bond or state identity")
        stereo[role] = validate_stereochemical_preservation(base, molecule)
        if stereo[role]["status"] != "preserved":
            raise ValueError("Higher geometry component changes or ambiguously defines stereochemistry")
        if not _topology_preserved(base, molecule):
            raise ValueError("Higher geometry component changes the inferred bond topology")
    n = len(base.symbols)
    count = 0 if n == 1 else 1 if n == 2 else 3 * n - 6
    chart = protocol.coordinates
    if len(chart.coordinates) != count or any(max(c.atoms) >= n for c in chart.coordinates):
        raise ValueError("Higher geometry needs a complete independent internal-coordinate chart with valid atom indices")
    if n == 2 and chart.coordinates[0].kind != "distance":
        raise ValueError("A diatomic geometry chart requires its single distance coordinate")
    scans = [c.scan_coordinate() for c in chart.coordinates]
    parameters, ranks = {}, {}
    for role, molecule in components.items():
        parameters[role], ranks[role] = _geometry_parameters(molecule, chart, scans)
        if ranks[role] is not None and ranks[role] < 1e-8:
            raise ValueError("Higher geometry chart is rank deficient or ill-conditioned")
    increments = {key: [] for key in ("cbs", "core_valence", "full_triples", "full_quadruples")}
    targets = []
    for i, coordinate in enumerate(chart.coordinates):
        cbs = _increment(parameters["cc_high"][i], parameters["cc_low"][i], coordinate) / protocol.cbs_denominator()
        cv = _increment(parameters["cv_ae"][i], parameters["cv_fc"][i], coordinate)
        triples = _increment(parameters["triples_full"][i], parameters["triples_parent"][i], coordinate)
        quadruples = _increment(parameters["quadruples_full"][i], parameters["quadruples_parent"][i], coordinate)
        for key, value in zip(increments, (cbs, cv, triples, quadruples), strict=True):
            increments[key].append(value)
        target = math.fsum([parameters["cc_low"][i], cbs, cv, triples, quadruples])
        if not math.isfinite(target):
            raise ValueError("Composite internal-coordinate arithmetic is nonfinite")
        if coordinate.kind == "distance" and target <= 0 or coordinate.kind == "angle" and not 0 < target < 180:
            raise ValueError("Composite internal-coordinate target lies outside its physical domain")
        targets.append(_wrap_degrees(target) if coordinate.kind == "dihedral" else target)
    xyz = np.asarray(base.coordinates) / BOHR_ANGSTROM
    projected = project_scan_geometry(xyz, scans, tuple(targets), tolerance=chart.projection_tolerance_native) if scans else xyz
    molecule = Molecule.model_validate({**base.model_dump(), "coordinates": (projected * BOHR_ANGSTROM).tolist()})
    stereo["composite"] = validate_stereochemical_preservation(base, molecule)
    if stereo["composite"]["status"] != "preserved":
        raise ValueError("Reconstructed composite changes or ambiguously defines stereochemistry")
    if not _topology_preserved(base, molecule):
        raise ValueError("Reconstructed composite changes the inferred bond topology")
    realized, ranks["composite"] = _geometry_parameters(molecule, chart, scans)
    residual = constraint_system(projected, scans, tuple(targets))[0] if scans else np.array([])
    if len(residual) and float(np.max(np.abs(residual))) > chart.projection_tolerance_native:
        raise ValueError("Composite reconstruction exceeds its coordinate residual tolerance")
    if ranks["composite"] is not None and ranks["composite"] < 1e-8:
        raise ValueError("Composite reconstruction has an ill-conditioned coordinate chart")
    return {
        "schema_version": "topos-higher-geometry/1", "molecule": molecule.model_dump(mode="json"),
        "formula": "R_low+(R_high-R_low)/(1-(X_low/X_high)^p)+(R_ae-R_fc)CCSD(T)+(R_CCSDT-R_CCSD(T))fc+(R_CCSDTQ-R_CCSDT)fc",
        "coordinate_specification": chart.model_dump(mode="json"), "geometry_inverse_power": protocol.geometry_inverse_power,
        "component_parameters": parameters, "increments": increments, "target_parameters": targets,
        "realized_parameters": realized, "residual_native": residual.tolist(),
        "component_geometry_sha256": {role: geometry_digest(value) for role, value in components.items()},
        "jacobian_smallest_to_largest_singular_value": ranks, "stereochemistry_checks": stereo,
        "inferred_topology_preserved": True,
        "assumptions": ["Component optimizations describe the same local conformer; common input, bond topology and stereochemistry do not establish membership of one torsional potential well"],
        "claims": {"energy_computed": False, "stationary_point_verified": False, "minimum_verified": False,
                   "same_conformational_basin_verified": False,
                   "vibrational_correction_computed": False, "counterpoise_bracket_computed": False,
                   "relativistic_correction_computed": False, "dboc_computed": False, "accuracy_claim": None},
    }


class _ComponentStop(Exception):
    """The durable native ledger already recorded an unsuccessful component."""


def _numerical_optimize(workflow, record, store, native: ExternalProtocol, options: NumericalGeometryOptions,
                        deadline: float, cancel_event: Event | None) -> tuple[Molecule, dict[str, Any], set[tuple]]:
    from scipy.optimize import minimize

    from .workflow import _topology_preserved

    initial = record.request.molecule
    evaluated, derivatives, identities = {}, {}, set()

    def check_deadline():
        if cancel_event is not None and cancel_event.is_set():
            record.status, record.metadata["termination_reason"] = "cancelled", "Higher geometry derivative campaign cancelled"
            store.commit(record)
            raise _ComponentStop()
        if time.monotonic() >= deadline:
            record.status, record.metadata["termination_reason"] = "timed-out", "Higher geometry derivative campaign deadline reached"
            store.commit(record)
            raise _ComponentStop()

    def energy(x: np.ndarray) -> float:
        check_deadline()
        current = Molecule.model_validate({**initial.model_dump(), "coordinates": (x.reshape(-1, 3) * BOHR_ANGSTROM).tolist()})
        key = digest_json(current.coordinates)
        if key not in evaluated:
            result = run_component(workflow, record, store, "higher-quadruples-energy-" + key, current,
                                   native, run_external, deadline, cancel_event)
            if result is None:
                raise _ComponentStop()
            if result.energy_hartree is None:
                raise IntegrityError("Numerical quadruples derivative lacks actual native electronic energy")
            identities.add((result.engine_version, result.metadata.get("executable_sha256"),
                            result.metadata.get("basis_library", {}).get("sha256")))
            evaluated[key] = result.energy_hartree
        return evaluated[key]

    def evaluate(x: np.ndarray) -> tuple[float, np.ndarray]:
        check_deadline()
        key = digest_json(x.tolist())
        if key not in derivatives:
            derivatives[key] = checked_energy_gradient(energy, x, options)
        value, gradient, _ = derivatives[key]
        return value, gradient

    x = np.asarray(initial.coordinates).ravel() / BOHR_ANGSTROM
    optimized = minimize(evaluate, x, jac=True, method="L-BFGS-B",
                         options={"maxiter": options.maximum_iterations, "maxls": 30, "ftol": 1e-15,
                                  "gtol": min(options.gradient_max_hartree_per_bohr, options.gradient_rms_hartree_per_bohr) / 2})
    value, gradient = evaluate(optimized.x)
    max_g, rms_g = float(np.max(np.abs(gradient))), float(np.sqrt(np.mean(gradient**2)))
    sensitivity = derivatives[digest_json(optimized.x.tolist())][2]
    margin = sensitivity["maximum_step_disagreement_hartree_per_bohr"]
    if max_g + margin > options.gradient_max_hartree_per_bohr or rms_g + margin > options.gradient_rms_hartree_per_bohr:
        record.status, record.metadata["termination_reason"] = "partial", "Numerical full-quadruples optimization did not satisfy both gradient criteria including step sensitivity"
        store.commit(record)
        raise _ComponentStop()
    molecule = Molecule.model_validate({**initial.model_dump(), "coordinates": (optimized.x.reshape(-1, 3) * BOHR_ANGSTROM).tolist()})
    if not _topology_preserved(initial, molecule) or validate_stereochemical_preservation(initial, molecule)["status"] != "preserved":
        raise ValueError("Numerical full-quadruples optimization changed topology or stereochemistry")
    check_deadline()
    return molecule, {
        "driver": "TOPOS/scipy-L-BFGS-B; actual native energies; central h/h2 differences",
        "native_cfour_optimizer": False, "analytic_gradient": False, "iterations": int(optimized.nit),
        "message": str(optimized.message), "electronic_energy_hartree": value,
        "gradient_hartree_per_bohr": gradient.reshape(-1, 3).tolist(),
        "max_gradient_hartree_per_bohr": max_g, "rms_gradient_hartree_per_bohr": rms_g,
        "derivative_sensitivity": sensitivity, "energy_geometries": len(evaluated),
        "gradient_evaluations": len(derivatives), "minimum_hessian_verified": False,
        "options": options.model_dump(mode="json"),
    }, identities


def calculate_higher_geometry(workflow, record, store, inputs, deadline: float, cancel_event: Event | None,
                              *, include_rotor_constants: bool = True) -> dict | None:
    """Calculate the eight-component geometry without certifying a containing row."""

    def within_budget() -> bool:
        cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled or time.monotonic() >= deadline:
            record.status = "cancelled" if cancelled else "timed-out"
            record.metadata["termination_reason"] = "Higher composite campaign cancelled" if cancelled else "Higher composite shared deadline reached"
            store.commit(record)
            return False
        return True

    try:
        if record.request.matrix_row_id not in {"T3C-1w", "T3C-1mo"}:
            raise ValueError("This uncorrected higher-geometry component is only for the explicit CFOUR geometry family; it cannot substitute for a CP bracket")
        if inputs.higher_geometry is None:
            raise ValueError("T3C-1w requires an explicit higher_geometry protocol with every basis, coordinate and derivative choice")
        if inputs.external_resolution != "cfour-topos-cartesian-optimizer-v1":
            raise ValueError("Explicit CFOUR/TOPOS Cartesian optimizer source resolution is required")
        protocol = HigherGeometryProtocol.model_validate(inputs.higher_geometry.model_dump())
        protocols = protocol.protocols()
        combine_higher_geometry({role: record.request.molecule for role in protocols}, protocol)
        # One shared geometry deadline covers all eight optimizations, not a
        # fresh wall budget for each displaced energy or component.
        cap = record.request.per_geometry_budget_seconds
        if cap is not None:
            deadline = min(deadline, time.monotonic() + cap)
        if not within_budget():
            return None
        geometries, native_optimizations, identities = {}, {}, set()
        for role, component in protocols.items():
            if role == "quadruples_full":
                molecule, diagnostic, observed = _numerical_optimize(
                    workflow, record, store, component, protocol.numerical_quadruples, deadline, cancel_event)
                geometries[role], native_optimizations[role] = molecule, diagnostic
                identities.update(observed)
                continue
            result = run_component(workflow, record, store, "higher-geometry-" + role, record.request.molecule,
                                   component, run_external, deadline, cancel_event)
            if result is None:
                return None
            if result.molecule is None or result.gradient_hartree_per_bohr is None:
                raise IntegrityError("Higher composite optimization lacks an actual geometry and analytic gradient")
            geometries[role] = result.molecule
            native_optimizations[role] = result.diagnostics.get("optimization")
            identities.add((result.engine_version, result.metadata.get("executable_sha256"),
                            result.metadata.get("basis_library", {}).get("sha256")))
        if len(identities) != 1 or not all(next(iter(identities))):
            raise IntegrityError("Higher composite mixed native versions, executable bytes or GENBAS libraries")
        if not within_budget():
            return None
        combined = combine_higher_geometry(geometries, protocol)
        molecule = Molecule.model_validate(combined["molecule"])
        identity = next(iter(identities))
        output = {
            "row_id": "T3C-1w", "output_kind": "composite-equilibrium-geometry",
            "containing_matrix_row_id": record.request.matrix_row_id,
            "definition": combined["formula"], "protocol": protocol.model_dump(mode="json"),
            "component_protocols": {role: p.model_dump(mode="json") for role, p in protocols.items()},
            "component_attempt_ids": [a.attempt_id for a in record.attempts if a.status == "completed"
                                      and str(a.metadata.get("component_key", "")).startswith("higher-")],
            "engine_version": identity[0], "executable_sha256": identity[1], "genbas_sha256": identity[2],
            "source_resolution": inputs.external_resolution, "geometry_composite": combined,
            "molecule": molecule.model_dump(mode="json"), "component_optimization_evidence": native_optimizations,
            "equilibrium_rotational_constants_mhz": [value * 1000 if value is not None else None
                                                     for value in rotational_constants(molecule)["constants_ghz"]] if include_rotor_constants else None,
            "composite_electronic_energy_hartree": None, "minimum_hessian_verified": False,
            "vibrational_correction_applied": False, "native_cfour_optimizer": False, "accuracy_claim": None,
            "restart_scope": "completed native energy/optimization components only; interrupted native CC amplitudes restart from scratch",
        }
        if not within_budget():
            return None
        return output
    except IntegrityError:
        raise
    except _ComponentStop:
        return None
    except (ValueError, RuntimeError, OSError) as exc:
        record.status, record.metadata["termination_reason"] = "unsupported" if not record.attempts else "partial", str(exc)
        store.commit(record)
        return None


def execute_higher_recipe(workflow, record, store, inputs, deadline: float, cancel_event: Event | None) -> bool:
    """Complete T3C-1w only; corrections never borrow this row's completion."""
    from .external_matrix_workflow import _publish

    if record.request.matrix_row_id != "T3C-1w":
        record.status = "unsupported"
        record.metadata["termination_reason"] = "Only T3C-1w is complete here; CP and mass-dependent correction rows need their explicit containing recipes"
        store.commit(record)
        return False
    output = calculate_higher_geometry(workflow, record, store, inputs, deadline, cancel_event)
    if not output:
        return False
    _publish(record, store, output)
    return True
