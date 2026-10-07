"""Import harmonic/RRHO references by recomputing immutable native derivatives.

The importer does not determine literature accuracy. It establishes that the
compared quantity follows from the selected native files and the predeclared
isotope, state, temperature, symmetry and standard-state model. A single finite
difference displacement does not establish step-size convergence.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .engines import _engine_version, _number, _orca_input, parse_orca_engrad, parse_xtb_gradient
from .models import MethodSpec, Molecule, ResourceLimits, RunRecord
from .native_hessian import orca_frequency_input, parse_orca_hessian
from .review import validate_scientific_candidate
from .science import (
    BOHR_ANGSTROM,
    geometry_digest,
    harmonic_analysis,
    rotational_constants,
    validate_derivatives,
)
from .storage import IntegrityError, RunStore, confined_file, digest_json, file_digest
from .thermochemistry import rrho_thermochemistry

FREQUENCY_DEFINITION = (
    "positive mass-weighted harmonic vibrational frequencies at a validated full-dimensional "
    "minimum; rigid translations and rotations removed"
)
ROTOR_DEFINITION = (
    "rigid-rotor constants from the recorded geometry and declared isotope masses; no vibrational correction"
)
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrityError(message)


def _close(actual: Any, expected: Any, *, label: str, atol: float = 1e-12) -> None:
    """Check all recomputed fields; stored supplemental provenance may remain."""
    if isinstance(expected, Mapping):
        _require(isinstance(actual, Mapping), f"{label} is missing its declared model")
        for key, value in expected.items():
            _require(key in actual, f"{label} is missing {key}")
            _close(actual[key], value, label=f"{label}.{key}", atol=atol)
    elif isinstance(expected, (float, int)) and not isinstance(expected, bool):
        _require(isinstance(actual, (float, int)) and not isinstance(actual, bool)
                 and bool(np.isfinite(actual)) and bool(np.isclose(actual, expected, rtol=1e-10, atol=atol)),
                 f"{label} differs from its immutable native derivation")
    elif isinstance(expected, list):
        _require(isinstance(actual, list) and len(actual) == len(expected), f"{label} has an incompatible dimension")
        for index, value in enumerate(expected):
            _close(actual[index], value, label=f"{label}[{index}]", atol=atol)
    else:
        _require(actual == expected, f"{label} differs from its declared scientific context")


def _artifact(snapshot: Path, inventory: list[dict], name: str) -> tuple[Path, dict]:
    matches = [entry for entry in inventory if Path(entry["path"]).name == name]
    _require(len(matches) == 1, f"Native artifact {name} must have unique immutable membership")
    entry = matches[0]
    path = confined_file(snapshot, "artifacts/" + entry["path"])
    _require(path.stat().st_size == entry["size_bytes"] and file_digest(path) == entry["sha256"],
             f"Native artifact {name} checksum changed")
    return path, dict(entry)


def _mapped_artifacts(embedded: list[dict], inventory: list[dict]) -> list[dict]:
    """Relocate original EngineResult paths by native identity, never live paths."""
    mapped = []
    for entry in embedded:
        matches = [item for item in inventory
                   if Path(item["path"]).name == Path(entry["path"]).name
                   and all(item.get(key) == entry.get(key) for key in ("sha256", "size_bytes", "role"))]
        _require(len(matches) == 1, "Embedded native result artifact has missing or ambiguous snapshot membership")
        mapped.append(matches[0])
    _require(bool(mapped) and len({item["path"] for item in mapped}) == len(mapped),
             "Embedded native result requires distinct actual artifacts")
    return mapped


def _quantity(attempt: dict, name: str, units: str) -> dict:
    entries = [quantity for quantity in attempt["quantities"] if quantity["name"] == name]
    _require(len(entries) == 1, f"Native derivative requires exactly one {name} quantity")
    quantity = entries[0]
    _require(quantity["units"] == units and quantity["attempt_id"] == attempt["attempt_id"]
             and quantity["method"] == attempt["method"] and quantity["validity"] == "validated-for-protocol",
             f"Native {name} lacks exact units and source attribution")
    return quantity


def _native_gradient(attempt: dict, molecule: Molecule, method: MethodSpec, snapshot: Path,
                     engine_version: str, *, embedded: bool = False) -> tuple[float, np.ndarray, dict]:
    metadata = attempt["metadata"]
    _require(attempt["status"] == "completed" and attempt.get("converged") is True
             and metadata.get("execution_kind") == "real"
             and attempt["engine"] == method.engine and attempt["method"] == method.method
             and attempt["engine_version"] == engine_version,
             "Harmonic reference requires completed matching actual native gradients")
    if not embedded:
        _require(attempt["validation_status"] == "validated-for-protocol"
                 and metadata.get("operation") == "gradient"
                 and metadata.get("input_molecule") == molecule.model_dump(mode="json")
                 and metadata.get("output_molecule") == molecule.model_dump(mode="json"),
                 "Native gradient input/output geometry differs from its declared displacement")
    else:
        _require(attempt.get("operation") == "gradient" and attempt.get("molecule") == molecule.model_dump(mode="json"),
                 "Embedded native reference is not an actual gradient at the selected geometry")
    _require(metadata.get("requested_method") == method.model_dump(mode="json"),
             "Native gradient Hamiltonian/numerical profile differs from the declared derivative protocol")
    executable_hash = metadata.get("executable_sha256")
    _require(isinstance(executable_hash, str) and re.fullmatch(r"[0-9a-f]{64}", executable_hash) is not None,
             "Native gradient executable checksum is absent")
    process = attempt["diagnostics"].get("process", {})
    _require(process.get("status") == "completed" and process.get("returncode") == 0
             and process.get("command") == attempt.get("command"), "Native gradient process was not completed successfully")
    inventory = attempt["artifacts"]
    stdout, output_entry = _artifact(snapshot, inventory, Path(process.get("stdout_path", "")).name)
    stderr, error_entry = _artifact(snapshot, inventory, Path(process.get("stderr_path", "")).name)
    raw, errors = stdout.read_text(errors="replace"), stderr.read_text(errors="replace")
    version_stdout, version_entry = _artifact(snapshot, inventory, "version.stdout")
    version_stderr, version_error_entry = _artifact(snapshot, inventory, "version.stderr")
    _require(_engine_version(version_stdout.read_text(errors="replace") + version_stderr.read_text(errors="replace"),
                             method.engine) == engine_version, "Independent native engine version differs from the reference")
    selected = [output_entry, error_entry, version_entry, version_error_entry]
    command = attempt["command"]
    _require(isinstance(command, list) and bool(command) and Path(command[0]).is_absolute(),
             "Native executable command identity is absent")
    if method.engine == "xtb":
        _require(method.method == "GFN2-xTB" and engine_version == "6.7.1",
                 "Native xTB derivatives require the supported exact GFN2-xTB/version protocol")
        expected_command = ["input.xyz", "--gfn", "2", "--chrg", str(molecule.charge),
                            "--uhf", str(molecule.multiplicity - 1), "--json", "--grad"]
        _require(command[1:] == expected_command, "Native xTB command changed the Hamiltonian/state or derivative operation")
        input_path, input_entry = _artifact(snapshot, inventory, "input.xyz")
        rows = [str(len(molecule.symbols)), "TOPOS input; angstrom; atom order preserved"]
        rows.extend(f"{symbol} {xyz[0]:.16g} {xyz[1]:.16g} {xyz[2]:.16g}"
                    for symbol, xyz in zip(molecule.symbols, molecule.coordinates, strict=True))
        _require(input_path.read_text() == "\n".join(rows) + "\n", "Native xTB input geometry changed")
        _require("normal termination of xtb" in raw + errors and "convergence criteria satisfied" in raw,
                 "Native xTB termination/electronic convergence is absent")
        gradient_path, gradient_entry = _artifact(snapshot, inventory, "gradient")
        energy, gradient = parse_xtb_gradient(gradient_path, molecule)
        literals = re.findall(r"TOTAL ENERGY\s+(" + _FLOAT + r")\s+Eh", raw)
        tolerance = 2e-9
    elif method.engine == "orca":
        _require(engine_version == "6.1.1", "Native ORCA derivatives require the exact supported engine version")
        resources = ResourceLimits.model_validate(metadata["resources"])
        input_path, input_entry = _artifact(snapshot, inventory, "job.inp")
        _require(command[1:] == ["job.inp"]
                 and input_path.read_text() == _orca_input(molecule, method, resources, "gradient"),
                 "Native ORCA input differs from its declared Hamiltonian, state or resources")
        _require(_engine_version(raw, "orca") == engine_version and "ORCA TERMINATED NORMALLY" in raw
                 and "SCF CONVERGED AFTER" in raw
                 and re.search(r"SCF NOT CONVERGED|SCF CONVERGENCE FAILURE", raw, re.I) is None,
                 "Native ORCA version/termination/electronic convergence is absent")
        gradient_path, gradient_entry = _artifact(snapshot, inventory, "job.engrad")
        energy, gradient = parse_orca_engrad(gradient_path, molecule)
        literals = re.findall(r"FINAL SINGLE POINT ENERGY\s+(" + _FLOAT + ")", raw)
        tolerance = 2e-7
    else:
        raise LookupError("This engine requires a dedicated native harmonic-reference importer")
    _require(bool(literals) and abs(_number(literals[-1]) - energy) <= tolerance,
             "Native stdout energy differs from its actual gradient artifact")
    validate_derivatives(gradient=gradient, natoms=len(molecule.symbols))
    if embedded:
        _close(attempt.get("energy_hartree"), energy, label="embedded native energy")
        _close(attempt.get("gradient_hartree_per_bohr"), gradient, label="embedded native gradient")
    else:
        _close(_quantity(attempt, "electronic_energy", "hartree")["value"], energy, label="native energy")
        _close(_quantity(attempt, "cartesian_gradient", "hartree/bohr")["value"], gradient, label="native gradient")
    selected.extend([input_entry, gradient_entry])
    return energy, np.asarray(gradient), {
        "attempt_id": attempt.get("attempt_id"), "engine_version": engine_version,
        "executable_sha256": executable_hash, "command_arguments": command[1:],
        "executable_basename": Path(command[0]).name,
        "geometry_sha256": digest_json(molecule.model_dump(mode="json")),
        "method": method.model_dump(mode="json"), "native_artifacts": selected,
        "parser": f"topos.engines/parse_{method.engine}_gradient" if method.engine == "xtb" else "topos.engines/parse_orca_engrad",
    }


def _reconstruct_hessian(gradients: list[np.ndarray], energies: list[float], step: float) -> tuple[np.ndarray, dict]:
    """Central-difference identity and conservation gates, independently testable as mathematics."""
    _require(np.isfinite(step) and 0 < step <= 0.1 and bool(gradients), "Physical derivative displacement is invalid")
    dimension = gradients[0].size
    _require(len(gradients) == len(energies) == 1 + 2 * dimension
             and all(gradient.shape == gradients[0].shape and np.isfinite(gradient).all() for gradient in gradients)
             and np.isfinite(energies).all(), "Physical Hessian requires all complete paired native evaluations")
    raw = np.column_stack([(gradients[1 + 2*j].ravel() - gradients[2 + 2*j].ravel()) / (2 * step)
                           for j in range(dimension)])
    asymmetry = float(np.max(np.abs(raw - raw.T)))
    energy_gradient = np.asarray([(energies[1 + 2*j] - energies[2 + 2*j]) / (2 * step)
                                  for j in range(dimension)])
    error = float(np.max(np.abs(energy_gradient - gradients[0].ravel())))
    _require(asymmetry <= 5e-5 and error <= 2e-5,
             "Native paired gradients/energies fail physical Hessian conservation thresholds")
    return (raw + raw.T) / 2, {"max_antisymmetry_hartree_per_bohr2": asymmetry,
                               "max_energy_gradient_difference_hartree_per_bohr": error,
                               "step_bohr": step, "finite_difference_order": 2,
                               "step_convergence": "not-established-by-one-displacement-size"}


def _physical_derivatives(record: dict, candidate: dict, attempt: dict, snapshot: Path,
                          engine_version: str) -> tuple[np.ndarray, np.ndarray, float, dict, dict]:
    metadata = attempt["metadata"]
    evidence = [entry for entry in attempt["artifacts"]
                if entry["role"] == "derived-output" and entry["sha256"] == metadata.get("derived_result_sha256")]
    _require(len(evidence) == 1 and record["metadata"].get("advanced_result") == evidence[0]["path"],
             "Harmonic reference must retain its exact advanced derived-result artifact")
    result_path = confined_file(snapshot, "artifacts/" + evidence[0]["path"])
    result = json.loads(result_path.read_text())
    _require(result.get("status") == "completed" and result.get("hessian", {}).get("status") == "completed",
             "Advanced harmonic result was not completed")
    hessian_record = result["hessian"]
    molecule = Molecule.model_validate(candidate["molecule"])
    method = RunRecord.model_validate(record).request.method_spec
    step = record["request"]["thermochemistry_options"]["step_bohr"]
    protocol = hessian_record["metadata"]["protocol"]
    _require(protocol.get("geometry") == candidate["molecule"] and protocol.get("method") == method.model_dump(mode="json")
             and protocol.get("step_bohr") == step, "Physical Hessian protocol differs from the predeclared reference")
    _require(hessian_record["metadata"].get("derivative_kind") == "physical-central-finite-difference-of-gradients"
             and hessian_record["metadata"].get("units") == "hartree/bohr^2",
             "Reference Hessian is not the declared physical central difference of gradients")
    identifiers = metadata["derivative_attempt_ids"]
    evaluations = hessian_record["evaluations"]
    _require(len(identifiers) == len(evaluations) == 1 + 6 * len(molecule.symbols),
             "Harmonic reference lacks all native derivative evaluations")
    attempts = {item["attempt_id"]: item for item in record["attempts"]}
    gradients, energies, proofs = [], [], []
    for index, (identifier, evaluation) in enumerate(zip(identifiers, evaluations, strict=True)):
        displaced = molecule.model_dump(mode="json")
        label = "reference"
        if index:
            column, sign = (index - 1) // 2, (1 if index % 2 else -1)
            coordinates = np.asarray(displaced["coordinates"])
            coordinates.flat[column] += sign * step * BOHR_ANGSTROM
            displaced["coordinates"] = coordinates.tolist()
            label = f"coordinate-{column:05d}-{'plus' if sign == 1 else 'minus'}"
        _require(evaluation.get("label") == label
                 and evaluation.get("geometry_sha256") == geometry_digest(Molecule.model_validate(displaced))
                 and evaluation.get("result", {}).get("metadata", {}).get("attempt_id") == identifier,
                 "Derived-result native derivative order/geometry/source identity changed")
        source = attempts[identifier]
        energy, gradient, proof = _native_gradient(source, Molecule.model_validate(displaced), method, snapshot, engine_version)
        embedded = evaluation["result"]
        _require(embedded.get("molecule") == displaced and embedded.get("status") == source["status"]
                 and embedded.get("converged") is True and embedded.get("command") == source["command"]
                 and embedded.get("engine_version") == source["engine_version"]
                 and embedded.get("metadata", {}).get("executable_sha256") == proof["executable_sha256"],
                 "Derived-result evaluation differs from its authentic persisted derivative")
        _close(embedded.get("energy_hartree"), energy, label="derived native energy")
        _close(embedded.get("gradient_hartree_per_bohr"), gradient.tolist(), label="derived native gradient")
        mapped = _mapped_artifacts(embedded["artifacts"], source["artifacts"])
        _require({item["path"] for item in mapped} == {item["path"] for item in source["artifacts"]},
                 "Derived-result native artifact inventory differs from its persisted derivative")
        gradients.append(gradient)
        energies.append(energy)
        proofs.append(proof)
    _require(len({item["executable_sha256"] for item in proofs}) == 1
             and proofs[0]["executable_sha256"] == metadata.get("executable_sha256"),
             "All native Hessian evaluations must use the exact same executable")
    hessian, checks = _reconstruct_hessian(gradients, energies, step)
    _close(hessian_record["hessian_hartree_per_bohr2"], hessian.tolist(), label="derived Cartesian Hessian")
    _close(hessian_record["energy_hartree"], energies[0], label="central reference energy")
    _close(_quantity(attempt, "cartesian_hessian", "hartree/bohr^2")["value"], hessian.tolist(), label="reported Hessian")
    return hessian, gradients[0], energies[0], result, {
        "derivative_attempt_ids": identifiers, "native_derivatives": proofs,
        "derived_result_artifact": evidence[0], "derivation": "symmetric central finite differences of actual Cartesian gradients",
        "numerical_derivative_checks": checks, "gradient_threshold_hartree_per_bohr": 1e-5,
    }


def _analytic_derivatives(record: dict, candidate: dict, attempt: dict, snapshot: Path, requested_method: MethodSpec,
                          engine_version: str) -> tuple[np.ndarray, np.ndarray, float, dict, dict]:
    metadata = attempt["metadata"]
    native = attempt
    source_id = metadata.get("native_hessian_attempt_id")
    if source_id is not None:
        sources = [source for source in record["attempts"] if source["attempt_id"] == source_id]
        _require(len(sources) == 1 and source_id != attempt["attempt_id"]
                 and attempt.get("parent_attempt_id") == source_id and metadata.get("attribution_only") is True
                 and attempt.get("command") == ["topos-internal", "native-hessian-candidate-attribution"],
                 "Derived harmonic attribution must bind exactly one actual immutable native component")
        native = sources[0]
        _require(native.get("status") == "completed" and native.get("converged") is True
                 and native.get("validation_status") == "validated-for-protocol"
                 and native.get("metadata", {}).get("execution_kind") == "real"
                 and all(native.get(key) == attempt.get(key) for key in ("engine", "method", "engine_version")),
                 "Derived harmonic attribution lacks a matching completed actual native component")
        native_metadata = native["metadata"]
        _require(metadata.get("native_hessian_result_sha256") == native_metadata.get("native_result_sha256")
                 == digest_json(native_metadata.get("native_result")),
                 "Derived harmonic attribution differs from its immutable native result identity")
        for key in ("protocol", "analysis", "reference_gradient_result", "hessian_hartree_per_bohr2",
                    "derivative_kind", "executable_sha256", "requested_method"):
            _require(metadata.get(key) == native_metadata.get(key),
                     f"Derived harmonic attribution changed its actual native {key}")
    else:
        _require(bool(native["command"]) and native["command"][0] != "topos-internal",
                 "Internal harmonic attribution cannot be presented as an additional native execution")
    molecule = Molecule.model_validate(candidate["molecule"])
    protocol = metadata["protocol"]
    method = MethodSpec.model_validate(protocol["method"])
    # A derivative child names its frequency role independently; the actual
    # Hamiltonian, numerical profile, basis, solvent and constraints remain exact.
    scientific_fields = {"engine", "method", "basis", "auxiliary_basis", "dispersion", "solvent", "constraints", "profile_id"}
    _require(method.model_dump(include=scientific_fields) == requested_method.model_dump(include=scientific_fields),
             "Native analytic Hessian Hamiltonian/basis differs from the predeclared reference")
    reference = dict(metadata["reference_gradient_result"])
    reference["artifacts"] = _mapped_artifacts(reference["artifacts"], native["artifacts"])
    energy, gradient, gradient_proof = _native_gradient(reference, molecule, method, snapshot, engine_version, embedded=True)
    gradient_proof.update(attempt_id=native["attempt_id"], native_stage="separate embedded reference gradient")
    resources = ResourceLimits.model_validate(protocol["resources"])
    native_input, input_entry = _artifact(snapshot, native["artifacts"], "frequency.inp")
    _require(native["command"][1:] == ["frequency.inp"]
             and native_input.read_text() == orca_frequency_input(molecule, method, resources, check_cpu_affinity=False),
             "Native analytic Hessian input differs from its recorded Hamiltonian/state")
    process = native["diagnostics"]["process"]
    _require(process.get("status") == "completed" and process.get("returncode") == 0
             and process.get("command") == native["command"], "Native analytic frequency process did not complete")
    stdout, output_entry = _artifact(snapshot, native["artifacts"], Path(process["stdout_path"]).name)
    raw = stdout.read_text(errors="replace")
    literals = re.findall(r"FINAL SINGLE POINT ENERGY\s+(" + _FLOAT + ")", raw)
    _require(_engine_version(raw, "orca") == engine_version and "ORCA TERMINATED NORMALLY" in raw
             and re.search(r"SCF NOT CONVERGED|SCF CONVERGENCE FAILURE", raw, re.I) is None
             and bool(literals) and abs(_number(literals[-1]) - energy) <= 1e-7,
             "Native analytic Hessian completion/version/reference energy is inconsistent")
    path, hessian_entry = _artifact(snapshot, native["artifacts"], "frequency.hess")
    parsed = parse_orca_hessian(path, molecule)
    hessian = np.asarray(parsed["hessian_hartree_per_bohr2"])
    _close(metadata["hessian_hartree_per_bohr2"], hessian.tolist(), label="native analytic Hessian")
    _close(_quantity(attempt, "cartesian_hessian", "hartree/bohr^2")["value"], hessian.tolist(), label="reported native Hessian")
    result = {"analysis": metadata["analysis"], "thermochemistry": metadata.get("thermochemistry")}
    return hessian, gradient, energy, result, {
        "derivative_attempt_ids": [native["attempt_id"]], "native_derivatives": [gradient_proof],
        "native_hessian_attempt_id": native["attempt_id"], "candidate_attribution_attempt_id": attempt["attempt_id"],
        "native_hessian_artifacts": [input_entry, output_entry, hessian_entry],
        "native_frame": parsed["native_to_requested_frame"], "native_masses_amu": parsed["native_masses_amu"],
        "derivation": "native ORCA analytic Cartesian Hessian with separately parsed actual reference gradient",
        "gradient_threshold_hartree_per_bohr": protocol["gradient_threshold"],
    }


def _thermal(record: dict, candidate: dict, attempt: dict, analysis: dict, energy: float,
             result: dict) -> tuple[dict, dict | None]:
    from .symmetry import point_group_analysis

    request = RunRecord.model_validate(record).request
    options = request.thermochemistry_options
    molecule = Molecule.model_validate(candidate["molecule"])
    symmetry = options.symmetry_number
    symmetry_proof = None
    if symmetry is None:
        symmetry_proof = point_group_analysis(molecule, tolerance_angstrom=request.symmetry_tolerance_angstrom)
        _require(symmetry_proof.get("status") == "stable" and symmetry_proof.get("rotational_symmetry_number") is not None,
                 "Predeclared RRHO symmetry is unresolved or tolerance-sensitive")
        symmetry = symmetry_proof["rotational_symmetry_number"]
        if "symmetry_evidence" in result:
            _close(result["symmetry_evidence"], symmetry_proof, label="rotational symmetry evidence")
    recalculated = rrho_thermochemistry(
        molecule, energy, analysis, temperature_k=request.temperature_k,
        pressure_pa=options.pressure_pa, concentration_mol_l=options.concentration_mol_l,
        symmetry_number=symmetry, frequency_scale=options.frequency_scale,
        low_frequency_policy=options.low_frequency_policy, cutoff_cm1=options.cutoff_cm1,
    )
    _close(result.get("thermochemistry"), recalculated, label="derived RRHO model")
    _close(attempt["metadata"].get("thermochemistry"), recalculated, label="reported RRHO model")
    _close(candidate["metadata"].get("thermochemistry"), recalculated, label="candidate RRHO model")
    _close(candidate.get("gibbs_hartree"), recalculated["gibbs_hartree"], label="candidate Gibbs energy")
    quantity = _quantity(attempt, "gibbs_energy", "hartree")
    _require(quantity.get("geometry_id") == candidate["candidate_id"], "Gibbs quantity belongs to a different geometry")
    _close(quantity["value"], recalculated["gibbs_hartree"], label="reported Gibbs energy")
    _require(quantity["definition"] == recalculated["model"] + "; explicit reference state and symmetry",
             "Gibbs quantity definition differs from the exact declared thermal model")
    return recalculated, symmetry_proof


def extract_reference_value(case: Any, record: RunRecord, store: RunStore) -> tuple[Any, dict]:
    """Recompute a unique eligible harmonic observable from its native snapshot.

    ``case`` is structurally typed to avoid importing the reference-plan module.
    Unsupported quantity families raise LookupError; missing/corrupt evidence
    in a supported pathway raises IntegrityError and cannot produce a value.
    """
    if case.observable not in {"gibbs_energy", "harmonic_frequencies", "equilibrium_rotational_constants"}:
        raise LookupError("This quantity is outside the harmonic/RRHO reference importer")
    _require(case.geometry_role == "harmonic-minimum", "Harmonic references require a predeclared harmonic-minimum geometry")
    expected_units = {"gibbs_energy": "hartree", "harmonic_frequencies": "cm^-1", "equilibrium_rotational_constants": "GHz"}
    _require(case.units == expected_units[case.observable], "Harmonic reference units differ from the exact observable")
    _require(record.request == case.request, "Measured request differs from its exact predeclaration")
    _require(not record.request.constraints, "A constrained reference cannot establish full-dimensional harmonic RRHO")
    manifest = store.verify()
    saved = store.load()
    _require(RunRecord.model_validate(saved) == record and digest_json(saved) == manifest["record_sha256"],
             "Measured record differs from the verified current native snapshot")
    snapshot = store.snapshots / manifest["snapshot_id"]
    candidates = [item for item in saved["candidates"] if item["status"] == "eligible"]
    _require(len(candidates) == 1, "Harmonic reference requires one predeclared eligible candidate, without post hoc selection")
    candidate = candidates[0]
    attempt = validate_scientific_candidate(saved, candidate)
    _require(attempt["engine_version"] == case.engine_version and attempt["engine"] == case.request.engine
             and attempt["method"] == case.request.method, "Harmonic native engine/version/method differs from predeclaration")
    kind = attempt["metadata"].get("result_kind")
    if kind == "physical-hessian-thermochemistry":
        hessian, gradient, energy, result, proof = _physical_derivatives(saved, candidate, attempt, snapshot, case.engine_version)
    elif kind == "native-analytic-hessian":
        hessian, gradient, energy, result, proof = _analytic_derivatives(
            saved, candidate, attempt, snapshot, record.request.method_spec, case.engine_version)
    else:
        if record.request.purpose in {"frequency", "thermochemistry"}:
            raise IntegrityError("Ordinary harmonic request lacks its completed physical derivative protocol")
        raise LookupError("This calculation has no implemented physical harmonic derivative protocol")
    molecule = Molecule.model_validate(candidate["molecule"])
    analysis = harmonic_analysis(molecule, hessian, gradient_hartree_per_bohr=gradient,
                                 gradient_threshold=proof["gradient_threshold_hartree_per_bohr"])
    analysis["subspace"] = "full-cartesian"
    analysis["geometry_sha256"] = geometry_digest(molecule)
    _require(analysis["stationary"] is True and analysis["validity"] == "harmonic-minimum-within-thresholds"
             and all(frequency > 0 for frequency in analysis["frequencies_cm1"]),
             "Native reference is not a free full-dimensional positive-frequency harmonic minimum")
    for stored in (result["analysis"], attempt["metadata"]["analysis"], candidate["metadata"].get("frequency_analysis")):
        # Analytic matrix candidates do not store the optional two ordinary
        # analysis annotations; the physical values/context are still required.
        core = {key: value for key, value in analysis.items() if key not in {"subspace", "geometry_sha256"}}
        _close(stored, core, label="native harmonic analysis", atol=1e-7)
    _close(candidate["energy_hartree"], energy, label="native central electronic energy")
    proof.update(candidate_id=candidate["candidate_id"], attempt_id=attempt["attempt_id"],
                 snapshot_id=manifest["snapshot_id"], record_sha256=manifest["record_sha256"],
                 geometry_sha256=digest_json(candidate["molecule"]), engine_version=case.engine_version,
                 observable=case.observable, units=case.units, definition=case.definition,
                 parser="topos.reference_thermal/immutable-native-harmonic-rrho-v1",
                 harmonic_analysis=analysis, isotope_provenance=analysis["isotope_provenance"],
                 scientific_accuracy_certified=False)
    if case.observable == "gibbs_energy":
        _require(record.request.purpose == "thermochemistry", "Gibbs comparison requires an explicit thermochemistry request")
        thermal, symmetry = _thermal(saved, candidate, attempt, analysis, energy, result)
        _require(case.definition == thermal["model"] + "; explicit reference state and symmetry",
                 "Predeclared Gibbs definition differs from its recomputed RRHO model")
        proof.update(thermochemistry=thermal, symmetry_evidence=symmetry)
        value = thermal["gibbs_hartree"]
    elif case.observable == "harmonic_frequencies":
        _require(case.definition == FREQUENCY_DEFINITION, "Harmonic reference definition differs from its exact quantity")
        value = analysis["frequencies_cm1"]
    else:
        _require(case.definition == ROTOR_DEFINITION, "Equilibrium rotor comparison cannot represent ground-state averaging")
        rotors = rotational_constants(molecule)
        _close(candidate["metadata"].get("rotational_constants"), rotors, label="equilibrium rotor arithmetic")
        _require(all(value is not None for value in rotors["constants_ghz"]),
                 "Three finite equilibrium rotational constants require a nonlinear molecule")
        proof["rotational_constants"] = rotors
        value = rotors["constants_ghz"]
    _require(store.verify()["snapshot_id"] == manifest["snapshot_id"], "Native snapshot changed during reference extraction")
    return value, proof
