"""Explicit scalar-relativistic geometry increments; no implied DBOC closure.

The conditional native profile is all-electron RHF with one exact uncontracted
basis, paired between nonrelativistic and spin-free X2C-1e Hamiltonians. Native
CFOUR 2.1 energies drive checked numerical derivatives. This is not an
analytic relativistic gradient, a DPT2 implementation or a DBOC calculation.
"""
from __future__ import annotations

import math
import re
import shutil
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable, Literal

import numpy as np

from .base_integration import BaseRuntime
from .cfour_artifacts import finalize_artifacts, native_text
from .cfour_controls import native_control_value
from .cfour_dependencies import require_cfour_parsers
from .composites import _geometry_parameters, _increment, _wrap_degrees
from .engines import EngineParseError, EngineResult
from .external_engines import (
    ExternalProtocol,
    _native_completion,
    _native_genbas,
    _physical_input,
    cfour_input,
    parse_cfour_output,
)
from .higher_composite import HigherCoordinateSet, NumericalGeometryOptions, checked_energy_gradient
from .matrix_components import run_component
from .models import Molecule, ResourceLimits
from .scans import constraint_system, project_scan_geometry
from .science import BOHR_ANGSTROM, geometry_digest, validate_stereochemical_preservation
from .storage import IntegrityError, atomic_json, digest_json, file_digest

SOURCES = [
    "https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/psi4/src/read_options.cc#L4687-L4698",
    "https://github.com/HPQC-LABS/AI_ENERGIES/blob/3098f558135589f5acf52474428ba020a561d58d/Ne/x2c-unc/2z/ccsd.txt",
]


class ScalarRelativisticProtocol(ExternalProtocol):
    """An explicit small-correction model, without a default increment basis."""

    engine: Literal["cfour"] = "cfour"
    engine_version: Literal["2.1"] = "2.1"
    operation: Literal["energy"] = "energy"
    method: Literal["HF"] = "HF"
    frozen_core: Literal[False] = False
    contraction: Literal["UNCONTRACTED"] = "UNCONTRACTED"
    relativistic: Literal["OFF", "X2C1E"]

    def electronic_protocol(self) -> ExternalProtocol:
        return ExternalProtocol.model_validate(self.model_dump(exclude={"contraction", "relativistic"}))


def scalar_input(molecule: Molecule, protocol: ScalarRelativisticProtocol, resources: ResourceLimits) -> str:
    protocol = ScalarRelativisticProtocol.model_validate(protocol.model_dump())
    raw = cfour_input(molecule, protocol.electronic_protocol(), resources)
    before, after = raw.rsplit(")", 1)
    return before + f"\nRELATIVISTIC={protocol.relativistic}\nCONTRACTION=UNCONTRACTED\nDBOC=OFF)" + after


def scalar_controls(raw: str, relativistic: Literal["OFF", "X2C1E"]) -> dict[str, str]:
    """Parse actual native echoed settings; these checks alone certify no energy."""
    controls = {}
    for label, wanted in (("RELATIVIST(?:IC)?", relativistic), ("CONTRACTION", "UNCONTRACTED"), ("DBOC", "OFF")):
        if native_control_value(raw, label) != wanted:
            raise EngineParseError(f"Scalar correction requires one native {label}={wanted} setting")
        controls[label] = wanted
    if re.search(r"SIGSEGV|segmentation fault|forrtl:\s*severe|fatal error", raw, re.I):
        raise EngineParseError("Native scalar correction reports a fatal error")
    if relativistic == "X2C1E" and not re.search(r"--executable\s+xvpropx2c\s+finished with status\s+0\b", raw):
        raise EngineParseError("X2C-1e lacks its native xvpropx2c completion evidence")
    return controls


def parse_scalar_output(raw: str, molecule: Molecule, protocol: ScalarRelativisticProtocol) -> dict[str, Any]:
    protocol = ScalarRelativisticProtocol.model_validate(protocol.model_dump())
    controls = scalar_controls(raw, protocol.relativistic)
    _native_completion(raw, protocol.electronic_protocol())
    parsed = parse_cfour_output(raw, molecule, protocol.electronic_protocol())
    parsed.update(scalar_controls=controls, hamiltonian="nonrelativistic" if protocol.relativistic == "OFF" else "spin-free X2C-1e",
                  contraction="UNCONTRACTED", dboc_included=False,
                  energy_definition="all-electron RHF electronic energy under the specified one-electron Hamiltonian")
    return parsed


def run_scalar_relativistic(molecule: Molecule, protocol: ScalarRelativisticProtocol,
                            resources: ResourceLimits, workdir: str | Path, *,
                            executable: str | Path | None = None,
                            process_runner: Callable[..., Any] | None = None,
                            cancel_event: Event | None = None) -> EngineResult:
    """One BASE-mediated native scalar-Hamiltonian energy, retaining raw evidence."""
    started, folder = time.monotonic(), Path(workdir)
    result = EngineResult(status="unsupported", engine="cfour", method="HF", operation="energy",
        metadata={"execution_kind": "not-executed", "adapter_validation": "conditional-not-live-validated",
                  "sources": SOURCES, "requested_protocol": protocol.model_dump(mode="json")})
    try:
        protocol = ScalarRelativisticProtocol.model_validate(protocol.model_dump())
        require_cfour_parsers()
        _physical_input(molecule, resources)
        if folder.is_symlink():
            raise IntegrityError("Scalar correction work directory cannot be a symlink")
        folder = folder.resolve()
        if folder.exists() and any(folder.iterdir()):
            raise ValueError("Scalar energy attempts require a fresh directory")
        if cancel_event is not None and cancel_event.is_set():
            result.status = "cancelled"
            return result
        if process_runner is None:
            runtime = BaseRuntime()
            runtime.validate_resources(resources)
            executable = runtime.resolve_executable("cfour", executable)
            process_runner = runtime.run_process
        resolved = shutil.which(str(executable or "xcfour"))
        if resolved is None:
            result.status, result.diagnostics["reason"] = "unavailable", "Audited CFOUR 2.1 executable is unavailable"
            return result
        binary = Path(resolved).resolve()
        genbas = _native_genbas(binary, protocol.electronic_protocol(), molecule)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "ZMAT").write_text(scalar_input(molecule, protocol, resources))
        shutil.copyfile(genbas, folder / "GENBAS")
        if file_digest(folder / "GENBAS") != protocol.genbas_sha256:
            raise IntegrityError("Native GENBAS changed during staging")
        atomic_json(folder / "protocol.json", protocol.model_dump(mode="json"))
        immutable = {str(path): file_digest(path) for path in (folder / "ZMAT", folder / "GENBAS", folder / "protocol.json", binary, genbas)}
        result.metadata.update(executable_sha256=file_digest(binary), executable=str(binary),
            protocol_sha256=digest_json(protocol.model_dump(mode="json")),
            basis_library={"path": str(genbas), "sha256": protocol.genbas_sha256, "contraction": "UNCONTRACTED"})
        remaining = resources.budget_seconds - (time.monotonic() - started)
        if remaining <= 0:
            result.status = "timed-out"
            return result
        result.command = [str(binary)]
        process = process_runner(result.command, folder, resources.model_copy(update={"budget_seconds": remaining}),
                                 cancel_event=cancel_event, log_prefix="engine")
        result.metadata["execution_kind"] = "real"
        result.status, result.diagnostics["process"] = process.status, process.to_dict()
        if process.status != "completed" or process.returncode != 0:
            if process.status == "completed":
                result.status = "failed"
            result.diagnostics["reason"] = process.reason or f"CFOUR process returned {process.returncode}"
            return result
        if any(Path(path).is_symlink() or file_digest(Path(path)) != wanted for path, wanted in immutable.items()):
            raise IntegrityError("Immutable scalar correction inputs changed during native execution")
        native = parse_scalar_output(native_text(folder, "engine.stdout", required=True, process_path=process.stdout_path), molecule, protocol)
        atomic_json(folder / "native-result.json", native)
        result.metadata.update(native_result=native, adapter_validation="native-output-validated-for-this-execution")
        result.energy_hartree, result.molecule = native["energy_hartree"], molecule
        result.engine_version, result.converged = native["engine_version"], True
        return result
    except (ValueError, RuntimeError, OSError) as exc:
        result.status = "failed" if result.metadata["execution_kind"] == "real" else "unsupported" if isinstance(exc, ValueError) else "unavailable"
        result.converged = False
        result.diagnostics["reason"] = str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - started
        if folder.is_dir() and not folder.is_symlink():
            finalize_artifacts(result, folder)


class ScalarCampaignStopped(RuntimeError):
    """The durable native component ledger already records the stop reason."""


def optimize_scalar_geometry(workflow, record, store, protocol: ScalarRelativisticProtocol,
                             options: NumericalGeometryOptions, deadline: float,
                             cancel_event: Event | None = None) -> tuple[Molecule, dict, set[tuple]]:
    """Optimize with checked h/h2 gradients of independently verified HF energies."""
    from scipy.optimize import minimize

    from .workflow import _topology_preserved

    protocol = ScalarRelativisticProtocol.model_validate(protocol.model_dump())
    options = NumericalGeometryOptions.model_validate(options.model_dump())
    initial = record.request.molecule
    values, derivatives, identities = {}, {}, set()

    def check():
        stopped = cancel_event is not None and cancel_event.is_set()
        if stopped or time.monotonic() >= deadline:
            record.status = "cancelled" if stopped else "timed-out"
            record.metadata["termination_reason"] = "Scalar relativistic geometry campaign stopped; native energy components retained"
            store.commit(record)
            raise ScalarCampaignStopped(record.metadata["termination_reason"])

    def energy(x):
        check()
        current = Molecule.model_validate({**initial.model_dump(), "coordinates": (x.reshape(-1, 3) * BOHR_ANGSTROM).tolist()})
        key = digest_json(current.coordinates)
        if key not in values:
            result = run_component(workflow, record, store, "scalar-" + protocol.relativistic + "-" + key,
                current, protocol, run_scalar_relativistic, deadline, cancel_event)
            if result is None:
                raise ScalarCampaignStopped("A native scalar energy component did not complete")
            if result.energy_hartree is None:
                raise IntegrityError("Scalar derivative lacks its actual native electronic energy")
            values[key] = result.energy_hartree
            identities.add((result.engine_version, result.metadata.get("executable_sha256"),
                            result.metadata.get("basis_library", {}).get("sha256")))
        return values[key]

    def evaluate(x):
        check()
        key = digest_json(x.tolist())
        if key not in derivatives:
            derivatives[key] = checked_energy_gradient(energy, x, options)
        return derivatives[key][:2]

    x = np.asarray(initial.coordinates).ravel() / BOHR_ANGSTROM
    optimized = minimize(evaluate, x, jac=True, method="L-BFGS-B", options={"maxiter": options.maximum_iterations,
        "maxls": 30, "ftol": 1e-15, "gtol": min(options.gradient_max_hartree_per_bohr, options.gradient_rms_hartree_per_bohr) / 2})
    value, gradient = evaluate(optimized.x)
    sensitivity = derivatives[digest_json(optimized.x.tolist())][2]
    error = sensitivity["maximum_step_disagreement_hartree_per_bohr"]
    maximum, rms = float(np.max(np.abs(gradient))), float(np.sqrt(np.mean(gradient**2)))
    if maximum + error > options.gradient_max_hartree_per_bohr or rms + error > options.gradient_rms_hartree_per_bohr:
        record.status, record.metadata["termination_reason"] = "partial", "Scalar geometry did not meet both gradient thresholds including step sensitivity"
        store.commit(record)
        raise ScalarCampaignStopped(record.metadata["termination_reason"])
    molecule = Molecule.model_validate({**initial.model_dump(), "coordinates": (optimized.x.reshape(-1, 3) * BOHR_ANGSTROM).tolist()})
    if not _topology_preserved(initial, molecule) or validate_stereochemical_preservation(initial, molecule)["status"] != "preserved":
        raise ValueError("Scalar geometry optimization changed topology or stereochemistry")
    check()
    return molecule, {"protocol": protocol.model_dump(mode="json"), "options": options.model_dump(mode="json"),
        "energy_hartree": value, "gradient_hartree_per_bohr": gradient.reshape(-1, 3).tolist(),
        "gradient_max_hartree_per_bohr": maximum, "gradient_rms_hartree_per_bohr": rms,
        "derivative_sensitivity": sensitivity, "energy_geometries": len(values),
        "iterations": int(optimized.nit), "native_analytic_gradient": False,
        "minimum_hessian_verified": False, "driver": "TOPOS L-BFGS-B; native HF energies; central h/h2 derivatives"}, identities


def apply_scalar_geometry_increment(base: Molecule, relativistic: Molecule, nonrelativistic: Molecule,
                                    chart: HigherCoordinateSet) -> dict[str, Any]:
    """Pure internal-coordinate assembly, with no native-execution attestation."""
    from .workflow import _topology_preserved

    molecules = {"base": base, "relativistic": relativistic, "nonrelativistic": nonrelativistic}
    identity = base.model_dump(exclude={"coordinates", "name"})
    for molecule in molecules.values():
        if molecule.model_dump(exclude={"coordinates", "name"}) != identity:
            raise ValueError("Scalar geometry increment changed mapped molecular/isotope/state identity")
        if not _topology_preserved(base, molecule) or validate_stereochemical_preservation(base, molecule)["status"] != "preserved":
            raise ValueError("Scalar geometry increment changed topology or stereochemistry")
    n = len(base.symbols)
    if n < 2 or len(chart.coordinates) != (1 if n == 2 else 3 * n - 6):
        raise ValueError("Scalar geometry assembly requires a complete independent internal-coordinate chart")
    if any(max(c.atoms) >= n for c in chart.coordinates) or n == 2 and chart.coordinates[0].kind != "distance":
        raise ValueError("Scalar geometry chart has invalid atom indices or a non-distance diatomic coordinate")
    scans = [coordinate.scan_coordinate() for coordinate in chart.coordinates]
    parameters, ranks = {}, {}
    for role, molecule in molecules.items():
        parameters[role], ranks[role] = _geometry_parameters(molecule, chart, scans)
        if ranks[role] is not None and ranks[role] < 1e-8:
            raise ValueError("Scalar geometry chart is ill-conditioned")
    increments = [_increment(a, b, c) for a, b, c in zip(parameters["relativistic"], parameters["nonrelativistic"], chart.coordinates, strict=True)]
    targets = [math.fsum([a, delta]) for a, delta in zip(parameters["base"], increments, strict=True)]
    for i, coordinate in enumerate(chart.coordinates):
        target = targets[i]
        if not math.isfinite(target) or coordinate.kind == "distance" and target <= 0 or coordinate.kind == "angle" and not 0 < target < 180:
            raise ValueError("Corrected geometry parameter lies outside its physical domain")
        if coordinate.kind == "dihedral":
            targets[i] = _wrap_degrees(target)
    xyz = project_scan_geometry(np.asarray(base.coordinates) / BOHR_ANGSTROM, scans, tuple(targets),
                                tolerance=chart.projection_tolerance_native)
    corrected = Molecule.model_validate({**base.model_dump(), "coordinates": (xyz * BOHR_ANGSTROM).tolist()})
    if not _topology_preserved(base, corrected) or validate_stereochemical_preservation(base, corrected)["status"] != "preserved":
        raise ValueError("Reconstructed scalar-corrected geometry changed topology or stereochemistry")
    residual = constraint_system(xyz, scans, tuple(targets))[0]
    realized, ratio = _geometry_parameters(corrected, chart, scans)
    if np.max(np.abs(residual)) > chart.projection_tolerance_native or ratio is not None and ratio < 1e-8:
        raise ValueError("Scalar geometry reconstruction failed the coordinate residual/rank gate")
    return {"schema_version": "topos-scalar-geometry-increment/1", "molecule": corrected.model_dump(mode="json"),
        "formula": "R_corrected=R_base+(R_HF_X2C1E-R_HF_nonrelativistic), parameter-wise in the declared chart",
        "coordinates": chart.model_dump(mode="json"), "component_parameters": parameters,
        "increment_parameters": increments, "realized_parameters": realized, "residual_native": residual.tolist(),
        "component_geometry_sha256": {role: geometry_digest(molecule) for role, molecule in molecules.items()},
        "claims": {"native_execution_verified": False, "dboc_computed": False, "matrix_row_complete": False,
                   "stationary_point_verified": False, "minimum_verified": False, "accuracy_claim": None},
        "assumptions": ["Additive HF scalar increment; correlated relativistic response is not included",
                        "Common topology and stereochemistry do not verify the same torsional basin"]}


def calculate_scalar_geometry_correction(workflow, record, store, base: Molecule,
                                         protocol: ScalarRelativisticProtocol, chart: HigherCoordinateSet,
                                         options: NumericalGeometryOptions, deadline: float,
                                         cancel_event: Event | None = None) -> dict[str, Any]:
    """Run both actual HF geometry surfaces and add their coordinate difference.

    Native energy components use the existing immutable ledger, including on
    recovery. The numerical outer optimization restarts from the common input;
    it reuses matching completed energy evaluations, not interrupted amplitudes.
    This returns only the scalar leg; the full month-tier DBOC closure is absent.
    """
    protocol = ScalarRelativisticProtocol.model_validate(protocol.model_dump())
    if protocol.relativistic != "X2C1E":
        raise ValueError("The paired scalar correction must explicitly select X2C1E")
    geometries, evaluations, identities = {}, {}, set()
    for role, choice in (("nonrelativistic", "OFF"), ("relativistic", "X2C1E")):
        leg = ScalarRelativisticProtocol.model_validate({**protocol.model_dump(), "relativistic": choice})
        geometries[role], evaluations[role], observed = optimize_scalar_geometry(
            workflow, record, store, leg, options, deadline, cancel_event)
        identities.update(observed)
    if len(identities) != 1 or any(value is None for value in next(iter(identities))):
        raise IntegrityError("Scalar paired geometries mixed native versions, executables or basis libraries")
    report = apply_scalar_geometry_increment(base, geometries["relativistic"], geometries["nonrelativistic"], chart)
    report.update(native_optimizations=evaluations, native_engine_identity=list(next(iter(identities))),
                  recovery="restart outer optimizer; reuse verified native energy components at matching geometries")
    report["claims"]["native_execution_verified"] = True
    return report
