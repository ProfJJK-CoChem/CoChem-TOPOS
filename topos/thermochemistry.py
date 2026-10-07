"""Physical finite-difference Hessians and explicitly declared ideal-gas RRHO.

Gradients are engine derivatives in Eh/bohr, not optimization Hessian guesses.
All displaced evaluations and raw artifacts remain available for inspection.
Finite-difference convergence and harmonic/ideal-gas assumptions are reported;
the presence of a number never certifies an exhaustive conformer ensemble.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable

import numpy as np
from scipy import constants

from .chemistry import resolved_masses
from .engines import EngineResult, run_engine
from .models import Candidate, MethodSpec, Molecule, ResourceLimits
from .science import (
    BOHR_ANGSTROM,
    HARTREE_J,
    KB_HARTREE_K,
    constants_provenance,
    ensemble_populations,
    geometry_digest,
    harmonic_analysis,
    rotational_constants,
    validate_derivatives,
)
from .storage import IntegrityError, atomic_json, digest_json, file_digest

GradientEvaluator = Callable[[Molecule, Path, ResourceLimits], EngineResult]


def finite_difference_hessian(
    molecule: Molecule,
    method: MethodSpec,
    resources: ResourceLimits,
    workdir: str | Path,
    *,
    step_bohr: float = 0.005,
    cancel_event: Event | None = None,
    executable: str | Path | None = None,
    evaluator: GradientEvaluator | None = None,
    process_runner: Callable[..., Any] | None = None,
    artifact_root: str | Path | None = None,
    asymmetry_tolerance: float = 5e-5,
    derivative_tolerance: float = 2e-5,
) -> dict[str, Any]:
    """Central Cartesian differences, with verified per-displacement restart.

    The first evaluation is at the reference geometry; the following 6N
    evaluations supply paired displaced gradients. A budget/cancellation or
    failed derivative returns no Hessian. Supplied callbacks are explicitly
    labelled as caller-provided and must return actual gradient evidence when
    used scientifically. They are useful for durable workflow integration.

    Constraints are not applied to the displaced Cartesian engine jobs. The
    result records them and cannot by itself establish constrained stability.
    """
    if not np.isfinite([step_bohr, asymmetry_tolerance, derivative_tolerance]).all() or min(
        step_bohr, asymmetry_tolerance, derivative_tolerance
    ) <= 0:
        raise ValueError("finite-difference step and consistency tolerances must be positive")
    started = time.monotonic()
    deadline = started + resources.budget_seconds
    folder = Path(workdir).resolve()
    evidence_root = Path(artifact_root).resolve() if artifact_root is not None else folder
    folder.mkdir(parents=True, exist_ok=True)
    requested = str(executable) if executable is not None else os.environ.get(
        f"TOPOS_{method.engine.upper()}_EXECUTABLE", method.engine
    )
    binary = shutil.which(requested)
    protocol = {
        "schema": "topos-finite-difference-hessian/0.1.0",
        "geometry": molecule.model_dump(mode="json"),
        "method": method.model_dump(mode="json"),
        "step_bohr": step_bohr,
        "resources": {k: v for k, v in resources.model_dump().items() if k != "budget_seconds"},
        "executable_sha256": file_digest(Path(binary)) if binary and evaluator is None else None,
        "evaluator": "caller-provided" if evaluator else "topos.engines.run_engine",
    }
    manifest_path = folder / "hessian-protocol.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != protocol:
            raise IntegrityError("Hessian restart protocol differs from the original calculation")
    elif any(folder.iterdir()):
        raise IntegrityError("Hessian directory contains unverified previous output")
    else:
        atomic_json(manifest_path, protocol)
    result: dict[str, Any] = {
        "status": "running", "energy_hartree": None,
        "gradient_hartree_per_bohr": None, "hessian_hartree_per_bohr2": None,
        "evaluations": [], "artifacts": [],
        "metadata": {"protocol": protocol, "geometry_sha256": geometry_digest(molecule),
                     "derivative_kind": "physical-central-finite-difference-of-gradients",
                     "formula": "H[:,j]=(g(x+h*e_j)-g(x-h*e_j))/(2*h)",
                     "units": "hartree/bohr^2", "finite_difference_order": 2,
                     "step_convergence": "not-established-by-one-displacement-size",
                     "constraints": method.constraints,
                     "dimension": 3 * len(molecule.symbols),
                     "expected_evaluations": 1 + 6 * len(molecule.symbols),
                     "asymmetry_tolerance_hartree_per_bohr2": asymmetry_tolerance,
                     "energy_gradient_tolerance_hartree_per_bohr": derivative_tolerance},
    }
    raw_method = method.model_copy(update={"constraints": {}})

    def finish(status: str, reason: str | None = None) -> dict[str, Any]:
        result["status"] = status
        result["metadata"]["elapsed_seconds"] = time.monotonic() - started
        if reason:
            result["reason"] = reason
        atomic_json(folder / "hessian-result.json", result)
        return result

    def evaluate(geometry: Molecule, label: str) -> EngineResult | None:
        if cancel_event is not None and cancel_event.is_set():
            result.update(status="cancelled", reason="Hessian cancelled before derivative evaluation")
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result.update(status="timed-out", reason="Hessian evaluation budget exhausted")
            return None
        receipt = folder / f"{label}.json"
        cached = False
        if receipt.exists():
            saved = json.loads(receipt.read_text())
            if (saved["geometry_sha256"] != geometry_digest(geometry)
                    or saved["result_sha256"] != digest_json(saved["result"])):
                raise IntegrityError("Hessian derivative receipt failed integrity verification")
            calculation = EngineResult.model_validate(saved["result"])
            for artifact in calculation.artifacts:
                path = Path(artifact.path).resolve()
                if (not path.is_relative_to(evidence_root) or not path.is_file()
                        or path.stat().st_size != artifact.size_bytes
                        or file_digest(path) != artifact.sha256):
                    raise IntegrityError("Hessian derivative raw artifact failed integrity verification")
            cached = calculation.status == "completed"
        if not cached:
            # Failed/interrupted scratch is retained, and a fresh directory is
            # always supplied to the next attempt. No stale engine outputs read.
            attempts = folder / label
            attempts.mkdir(exist_ok=True)
            count = 0
            while (attempts / str(count)).exists():
                count += 1
            scratch = attempts / str(count)
            limits = resources.model_copy(update={"budget_seconds": remaining})
            calculation = (evaluator(geometry, scratch, limits) if evaluator else run_engine(
                geometry, raw_method, limits, scratch, operation="gradient",
                cancel_event=cancel_event, executable=executable,
                **({"process_runner": process_runner} if process_runner is not None else {}),
            ))
            data = calculation.model_dump(mode="json")
            atomic_json(receipt, {"geometry_sha256": geometry_digest(geometry),
                                  "result_sha256": digest_json(data), "result": data})
        result["evaluations"].append({"label": label, "resumed": cached,
                                      "geometry_sha256": geometry_digest(geometry),
                                      "result": calculation.model_dump(mode="json")})
        result["artifacts"].extend(a.model_dump(mode="json") for a in calculation.artifacts)
        if (calculation.status != "completed" or calculation.energy_hartree is None
                or calculation.gradient_hartree_per_bohr is None):
            result.update(status=calculation.status if calculation.status != "completed" else "failed",
                          reason=calculation.diagnostics.get("reason", "Complete physical derivative unavailable"))
            return None
        validate_derivatives(calculation.gradient_hartree_per_bohr, natoms=len(molecule.symbols))
        if calculation.molecule is not None and geometry_digest(calculation.molecule) != geometry_digest(geometry):
            raise IntegrityError("Hessian derivative geometry differs from requested displacement")
        return calculation

    central = evaluate(molecule, "reference")
    if central is None:
        return finish(result["status"], result.get("reason"))
    result["energy_hartree"] = central.energy_hartree
    result["gradient_hartree_per_bohr"] = central.gradient_hartree_per_bohr
    n = 3 * len(molecule.symbols)
    hessian = np.empty((n, n), dtype=float)
    energy_gradient = np.empty(n, dtype=float)
    for column in range(n):
        pair = []
        for sign, suffix in ((1, "plus"), (-1, "minus")):
            xyz = np.array(molecule.coordinates, dtype=float)
            xyz.flat[column] += sign * step_bohr * BOHR_ANGSTROM
            displaced = Molecule.model_validate({**molecule.model_dump(), "coordinates": xyz.tolist()})
            calculation = evaluate(displaced, f"coordinate-{column:05d}-{suffix}")
            if calculation is None:
                return finish(result["status"], result.get("reason"))
            if (calculation.engine, calculation.method, calculation.engine_version,
                calculation.metadata.get("executable_sha256")) != (
                    central.engine, central.method, central.engine_version,
                    central.metadata.get("executable_sha256")):
                return finish("failed", "Derivative engine/method/version identity changed across Hessian evaluations")
            pair.append(calculation)
        plus, minus = pair
        hessian[:, column] = (
            np.asarray(plus.gradient_hartree_per_bohr).ravel()
            - np.asarray(minus.gradient_hartree_per_bohr).ravel()
        ) / (2 * step_bohr)
        energy_gradient[column] = (plus.energy_hartree - minus.energy_hartree) / (2 * step_bohr)
    asymmetry = float(np.max(np.abs(hessian - hessian.T)))
    gradient_error = float(np.max(np.abs(energy_gradient - np.asarray(central.gradient_hartree_per_bohr).ravel())))
    result["metadata"].update(max_antisymmetry_hartree_per_bohr2=asymmetry,
                              max_energy_gradient_difference_hartree_per_bohr=gradient_error,
                              symmetrization="(H+H.T)/2 after raw asymmetry check")
    if asymmetry > asymmetry_tolerance or gradient_error > derivative_tolerance:
        return finish("failed", "Finite-difference derivative consistency exceeds declared tolerance")
    result["hessian_hartree_per_bohr2"] = ((hessian + hessian.T) / 2).tolist()
    validate_derivatives(hessian=result["hessian_hartree_per_bohr2"], natoms=len(molecule.symbols))
    return finish("completed")


def standard_state_correction(
    *, temperature_k: float, pressure_pa: float = 101325.0, concentration_mol_l: float = 1.0,
    delta_n: float = 1.0,
) -> dict[str, Any]:
    """Ideal-gas chemical-potential conversion Δν RT ln(c°RT/p°).

    This is a reference-state conversion, not a solvation free energy. For
    A+B→AB, Δν=-1, hence the 1 atm→1 M reaction correction is negative.
    """
    if not np.isfinite([temperature_k, pressure_pa, concentration_mol_l, delta_n]).all() or min(
        temperature_k, pressure_pa, concentration_mol_l
    ) <= 0:
        raise ValueError("temperature, pressure and concentration must be finite and positive")
    ratio = concentration_mol_l * 1000 * constants.R * temperature_k / pressure_pa
    value = delta_n * KB_HARTREE_K * temperature_k * math.log(ratio)
    return {"correction_hartree": value, "delta_n": delta_n,
            "temperature_k": temperature_k, "pressure_pa": pressure_pa,
            "concentration_mol_l": concentration_mol_l,
            "definition": "delta_n*k_B*T*ln(c_standard*R*T/p_standard)",
            "solvation_included": False}


def rrho_thermochemistry(
    molecule: Molecule,
    electronic_energy_hartree: float,
    analysis: dict[str, Any],
    *,
    temperature_k: float = 298.15,
    pressure_pa: float = 101325.0,
    concentration_mol_l: float | None = None,
    symmetry_number: int = 1,
    frequency_scale: float = 1.0,
    low_frequency_policy: str = "reject",
    cutoff_cm1: float = 10.0,
) -> dict[str, Any]:
    """Ideal-gas rigid-rotor/harmonic-oscillator single-conformer quantities.

    Ground electronic degeneracy equals explicit spin multiplicity. Rotational
    symmetry is supplied explicitly, never inferred from hit counts. Optional
    frequency-floor regularization affects thermal oscillator terms only, with
    unmodified scaled frequencies retained for ZPE; it is labelled modified-HO,
    not a hindered rotor or a Grimme interpolation. Near-zero or imaginary modes
    never silently disappear. Constrained-subspace analyses are rejected.
    """
    values = [electronic_energy_hartree, temperature_k, pressure_pa, frequency_scale, cutoff_cm1]
    if not np.isfinite(values).all() or min(values[1:]) <= 0:
        raise ValueError("energy must be finite; thermal settings must be positive")
    if (not isinstance(symmetry_number, int) or isinstance(symmetry_number, bool)
            or symmetry_number < 1):
        raise ValueError("rotational symmetry number must be an explicit positive integer")
    if low_frequency_policy not in {"reject", "frequency-floor"}:
        raise ValueError("low frequency policy must be reject or frequency-floor")
    if (analysis.get("validity") != "harmonic-minimum-within-thresholds"
            or analysis.get("stationary") is not True
            or analysis.get("constraints") or analysis.get("subspace", "full-cartesian") != "full-cartesian"):
        raise ValueError("RRHO requires a validated full-dimensional stationary minimum")
    frequencies = np.asarray(analysis.get("frequencies_cm1"), dtype=float)
    rotation = rotational_constants(molecule)
    expected = 0 if len(molecule.symbols) == 1 else 3 * len(molecule.symbols) - (
        5 if rotation["geometry_class"] == "linear" else 6
    )
    if frequencies.shape != (expected,) or not np.isfinite(frequencies).all():
        raise ValueError("frequency count differs from the complete internal vibrational subspace")
    if np.any(frequencies <= 0):
        raise ValueError("imaginary or zero internal modes require explicit additional physical treatment")
    scaled = frequencies * frequency_scale
    if low_frequency_policy == "reject" and np.any(scaled < cutoff_cm1):
        raise ValueError("near-zero internal modes require an explicit low-frequency thermal model")
    thermal_frequencies = np.maximum(scaled, cutoff_cm1) if low_frequency_policy == "frequency-floor" else scaled
    k_t = KB_HARTREE_K * temperature_k
    masses, mass_provenance = resolved_masses(molecule)
    mass_kg = float(masses.sum()) * constants.atomic_mass
    log_q_trans = 1.5 * math.log(2 * math.pi * mass_kg * constants.k * temperature_k / constants.h**2)
    log_q_trans += math.log(constants.k * temperature_k / pressure_pa)
    translation_entropy = KB_HARTREE_K * (log_q_trans + 2.5)
    translation_enthalpy = 2.5 * k_t
    geometry_class = rotation["geometry_class"]
    moments = np.asarray(rotation["moments_amu_angstrom2"]) * constants.atomic_mass * constants.angstrom**2
    rotor_factor = 8 * math.pi**2 * constants.k * temperature_k / constants.h**2
    if geometry_class == "monatomic":
        if symmetry_number != 1:
            raise ValueError("a monatomic species has rotational symmetry number one")
        rotation_entropy, rotation_energy = 0.0, 0.0
    elif geometry_class == "linear":
        log_q_rot = math.log(rotor_factor * float(moments[-1]) / symmetry_number)
        rotation_entropy, rotation_energy = KB_HARTREE_K * (log_q_rot + 1), k_t
    else:
        log_q_rot = 0.5 * math.log(math.pi) - math.log(symmetry_number)
        log_q_rot += 1.5 * math.log(rotor_factor) + 0.5 * float(np.log(moments).sum())
        rotation_entropy, rotation_energy = KB_HARTREE_K * (log_q_rot + 1.5), 1.5 * k_t
    quanta = constants.h * constants.c * 100 * thermal_frequencies / HARTREE_J
    x = quanta / k_t
    # exp(-x)/(1-exp(-x)) avoids overflow for high-frequency/low-T modes.
    occupancy = np.exp(-x) / (-np.expm1(-x))
    vibrational_energy = float(np.sum(quanta * occupancy))
    vibrational_entropy = float(KB_HARTREE_K * np.sum(x * occupancy - np.log(-np.expm1(-x))))
    electronic_entropy = KB_HARTREE_K * math.log(molecule.multiplicity)
    zpe = float(0.5 * constants.h * constants.c * 100 * scaled.sum() / HARTREE_J)
    entropy = translation_entropy + rotation_entropy + vibrational_entropy + electronic_entropy
    thermal_enthalpy = translation_enthalpy + rotation_energy + vibrational_energy
    enthalpy = electronic_energy_hartree + zpe + thermal_enthalpy
    correction = 0.0
    standard_state: dict[str, Any] = {"kind": "ideal-gas", "pressure_pa": pressure_pa,
                                       "temperature_k": temperature_k}
    if concentration_mol_l is not None:
        standard_state = standard_state_correction(temperature_k=temperature_k, pressure_pa=pressure_pa,
                                                   concentration_mol_l=concentration_mol_l)
        standard_state["kind"] = "ideal-concentration-reference"
        correction = standard_state["correction_hartree"]
    gibbs = enthalpy - temperature_k * entropy + correction
    return {
        "status": "completed", "model": "ideal-gas-RRHO" if low_frequency_policy == "reject" else "ideal-gas-modified-HO-frequency-floor",
        "geometry_sha256": geometry_digest(molecule), "temperature_k": temperature_k,
        "molecular_state": {"symbols": molecule.symbols, "isotopes": molecule.isotopes,
                            "charge": molecule.charge, "multiplicity": molecule.multiplicity,
                            "atom_ids": molecule.atom_ids, "environment": molecule.environment},
        "electronic_energy_hartree": electronic_energy_hartree, "zpe_hartree": zpe,
        "thermal_enthalpy_correction_hartree": thermal_enthalpy,
        "enthalpy_hartree": enthalpy, "entropy_hartree_per_k": entropy,
        "standard_state_correction_hartree": correction,
        "solvation_correction_hartree": None, "gibbs_hartree": gibbs,
        "thermal_gibbs_correction_hartree": gibbs - electronic_energy_hartree,
        "components": {
            "translation_enthalpy_hartree": translation_enthalpy,
            "rotation_energy_hartree": rotation_energy,
            "vibration_thermal_energy_hartree": vibrational_energy,
            "translation_entropy_hartree_per_k": translation_entropy,
            "rotation_entropy_hartree_per_k": rotation_entropy,
            "vibration_entropy_hartree_per_k": vibrational_entropy,
            "electronic_entropy_hartree_per_k": electronic_entropy,
        },
        "standard_state": standard_state, "symmetry_number": symmetry_number,
        "electronic_degeneracy": molecule.multiplicity,
        "frequency_scale": frequency_scale, "low_frequency_policy": low_frequency_policy,
        "cutoff_cm1": cutoff_cm1, "scaled_frequencies_cm1": scaled.tolist(),
        "thermal_frequencies_cm1": thermal_frequencies.tolist(), "rotation": rotation,
        "isotope_provenance": mass_provenance, "constants": constants_provenance(),
        "scope": "single conformer; no configurational mixing, excited electronic states or solvation",
        "entropy_reference": "ideal gas at pressure_pa; concentration correction added separately to G",
        "uncertainty": "harmonic/rigid-rotor/ideal-gas approximations; accuracy not certified",
    }


def calculate_thermochemistry(
    molecule: Molecule, method: MethodSpec, resources: ResourceLimits, workdir: str | Path,
    *, step_bohr: float = 0.005, cancel_event: Event | None = None,
    executable: str | Path | None = None, evaluator: GradientEvaluator | None = None,
    process_runner: Callable[..., Any] | None = None, thermal: bool = True,
    artifact_root: str | Path | None = None,
    gradient_threshold: float = 1e-5, imaginary_tolerance_cm1: float = 10.0,
    **thermal_options: Any,
) -> dict[str, Any]:
    """Obtain real gradients → Hessian → frequency validation → separated RRHO."""
    hessian = finite_difference_hessian(molecule, method, resources, workdir, step_bohr=step_bohr,
                                        cancel_event=cancel_event, executable=executable, evaluator=evaluator,
                                        process_runner=process_runner, artifact_root=artifact_root)
    result: dict[str, Any] = {"status": hessian["status"], "hessian": hessian,
                              "analysis": None, "thermochemistry": None}
    if hessian["status"] != "completed":
        result["reason"] = hessian.get("reason", "physical Hessian unavailable")
        return result
    if method.constraints:
        result.update(status="unsupported", reason="A constrained geometry requires an explicit constrained thermal model; whole-molecule RRHO is not applied")
        result["analysis"] = {"subspace": "full-cartesian-at-constrained-geometry",
                              "constraints": method.constraints,
                              "validity": "constrained-stability-not-established"}
        return result
    analysis = harmonic_analysis(molecule, hessian["hessian_hartree_per_bohr2"],
                                 gradient_hartree_per_bohr=hessian["gradient_hartree_per_bohr"],
                                 gradient_threshold=gradient_threshold,
                                 imaginary_tolerance_cm1=imaginary_tolerance_cm1)
    analysis.update(subspace="full-cartesian", geometry_sha256=geometry_digest(molecule))
    result["analysis"] = analysis
    if thermal:
        try:
            result["thermochemistry"] = rrho_thermochemistry(molecule, hessian["energy_hartree"], analysis, **thermal_options)
            reference = hessian["evaluations"][0]["result"]
            result["thermochemistry"]["comparison_protocol"] = {
                "method": method.model_dump(mode="json"), "engine_version": reference["engine_version"],
                "executable_sha256": reference["metadata"].get("executable_sha256"),
            }
        except ValueError as exc:
            result.update(status="partial", reason=str(exc))
    atomic_json(Path(workdir) / "thermochemistry-result.json", result)
    return result


def derivative_coordinate_frame(molecule: Molecule) -> tuple[Molecule, dict[str, Any]]:
    """Choose an explicit proper frame away from exact Cartesian coordinate planes.

    Genuine xTB 6.7.1 derivatives for exactly axis-planar water exhibited a
    nonconservative out-of-plane gradient component in regression testing. A
    fixed proper rotation/translation before optimization avoids that special
    frame. Every native evaluation uses and records the transformed geometry;
    no gradient or Hessian is silently patched after computation. Numerical
    derivative consistency checks still apply in the chosen frame.
    """
    from scipy.spatial.transform import Rotation

    rotation = Rotation.from_rotvec([0.7, 0.4, 0.5]).as_matrix()
    translation = np.array([0.123, 0.567, 0.932])
    coordinates = np.asarray(molecule.coordinates) @ rotation + translation
    transformed = Molecule.model_validate({**molecule.model_dump(), "coordinates": coordinates.tolist()})
    return transformed, {"kind": "proper-rigid-coordinate-transformation",
                         "formula": "new_coordinates = original_coordinates @ rotation + translation",
                         "rotation": rotation.tolist(), "translation_angstrom": translation.tolist(),
                         "original_geometry_sha256": geometry_digest(molecule),
                         "transformed_geometry_sha256": geometry_digest(transformed),
                         "reason": "avoid exact Cartesian coordinate planes in numerical derivative evaluation"}


def mixed_level_gibbs(high_energy_hartree: float, low_thermochemistry: dict[str, Any], *,
                      high_method: dict[str, Any], rationale: str) -> dict[str, Any]:
    """E_high + (G_low - E_low), preserving the low-level thermal assumptions."""
    if not high_method or not rationale.strip() or low_thermochemistry.get("status") != "completed":
        raise ValueError("mixed-level Gibbs requires valid lower-level thermochemistry and justified high-level method")
    low_energy = low_thermochemistry["electronic_energy_hartree"]
    low_gibbs = low_thermochemistry["gibbs_hartree"]
    if not np.isfinite([high_energy_hartree, low_energy, low_gibbs]).all():
        raise ValueError("mixed-level energies must be finite")
    return {"gibbs_hartree": high_energy_hartree + (low_gibbs - low_energy),
            "formula": "E_high + (G_low - E_low)", "high_energy_hartree": high_energy_hartree,
            "high_method": high_method, "thermal_source": low_thermochemistry, "rationale": rationale,
            "geometry_sha256": low_thermochemistry.get("geometry_sha256")}


def ensemble_sensitivity(candidates: list[Candidate], *, temperature_k: float = 298.15,
                         quantity: str = "gibbs", windows_kcal_mol: tuple[float, ...] = (1, 3, 6),
                         missing_states: int = 0, missing_gap_kcal_mol: float | None = None) -> dict[str, Any]:
    """Report truncation sensitivity and an explicitly conditional missing-state bound."""
    from .science import HARTREE_KCAL_MOL

    complete = ensemble_populations(candidates, temperature_k=temperature_k, quantity=quantity)
    if (not windows_kcal_mol or not np.isfinite(windows_kcal_mol).all()
            or min(windows_kcal_mol) <= 0 or not isinstance(missing_states, int)
            or isinstance(missing_states, bool) or missing_states < 0):
        raise ValueError("positive energy windows and a nonnegative missing-state count are required")
    if missing_states and (missing_gap_kcal_mol is None or not np.isfinite(missing_gap_kcal_mol)):
        raise ValueError("a missing-state energy-gap assumption must accompany its count")
    field = "gibbs_hartree" if quantity == "gibbs" else "energy_hartree"
    minimum = min(getattr(c, field) for c in candidates)
    windows = []
    for window in windows_kcal_mol:
        retained = [c for c in candidates if (getattr(c, field) - minimum) * HARTREE_KCAL_MOL <= window]
        subset = ensemble_populations(retained, temperature_k=temperature_k, quantity=quantity)
        windows.append({"window_kcal_mol": window, "retained_count": len(retained),
                        "retained_probability": sum(complete["populations"][c.candidate_id] for c in retained),
                        "ensemble_energy_shift_hartree": subset["ensemble_energy_hartree"] - complete["ensemble_energy_hartree"]})
    bound = None
    if missing_states:
        from scipy.special import expit, logsumexp

        k_t = KB_HARTREE_K * temperature_k
        observed_log_z = logsumexp([math.log(c.degeneracy) - (getattr(c, field) - minimum) / k_t for c in candidates])
        missing_log_z = math.log(missing_states) - missing_gap_kcal_mol / HARTREE_KCAL_MOL / k_t
        bound = float(expit(missing_log_z - observed_log_z))
    return {"ensemble": complete, "windows": windows, "missing_population_upper_bound": bound,
            "missing_states_assumption": missing_states, "minimum_missing_gap_kcal_mol": missing_gap_kcal_mol,
            "missing_degeneracy_assumption": "each absent state has degeneracy one",
            "completeness": "not-certified; missing-state bound depends on user assumptions"}
