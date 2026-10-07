"""Hash-bound DFT data and explicit MACE multihead fine-tuning preparation.

The matrix's 100–500 points are a recipe constraint, not an accuracy guarantee.
Training is experimental and cannot by itself complete the subsequent GOAT and
CREST searches. Native DFT imports and held-out numerical errors are separate
from availability of an audited GPU training runner.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import time
from pathlib import Path
from threading import Event
from typing import Any, Literal

import numpy as np
from pydantic import Field, model_validator

from .engines import (
    EngineResult,
    _engine_version,
    _number,
    _orca_convergence,
    _orca_input,
    artifact_inventory,
    parse_orca_engrad,
    read_xyz,
)
from .ml import BOHR_ANGSTROM, HARTREE_EV, MLRunner, ModelManifest, molecule_system_identity
from .models import Artifact, Attempt, Contract, MethodSpec, Molecule, ResourceLimits, RunRecord
from .storage import IntegrityError, RunStore, atomic_json, confined_file, digest_json, file_digest

MACE_VERSION = "0.3.16"
MACE_SOURCE = "https://github.com/ACEsuit/mace/blob/v0.3.16/mace/cli/run_train.py"
DFT_METHODS = frozenset({"B3LYP", "wB97X-V", "wB97M-V", "r2SCAN-3c", "r²SCAN-3c"})
_SHA = r"^[a-f0-9]{64}$"


class DFTSourcePoint(Contract):
    run_dir: str
    record_sha256: str = Field(pattern=_SHA)
    attempt_id: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    partition: Literal["train", "validation", "test"]


class TrainingDatasetSpec(Contract):
    points: list[DFTSourcePoint] = Field(min_length=100, max_length=500)
    partition_rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_partition(self):
        if not self.partition_rationale.strip():
            raise ValueError("Partition rationale must explain the configuration grouping")
        groups: dict[str, str] = {}
        identities = set()
        for point in self.points:
            if not point.group_id.strip():
                raise ValueError("Configuration group identifiers must be nonempty")
            identity = (point.record_sha256, point.attempt_id)
            if identity in identities:
                raise ValueError("A source DFT attempt cannot occur more than once")
            identities.add(identity)
            if point.group_id in groups and groups[point.group_id] != point.partition:
                raise ValueError("Related configuration groups must not cross training/validation/test partitions")
            groups[point.group_id] = point.partition
        if set(groups.values()) != {"train", "validation", "test"}:
            raise ValueError("Explicit group-disjoint training, validation and held-out test data are required")
        return self


class ReferenceFrame(Contract):
    """Canonical numerical reference; native provenance is verified on import."""

    source: DFTSourcePoint
    molecule: Molecule
    method: MethodSpec
    energy_hartree: float
    gradient_hartree_per_bohr: list[list[float]]
    energy_units: Literal["hartree"] = "hartree"
    gradient_units: Literal["hartree/bohr"] = "hartree/bohr"

    @model_validator(mode="after")
    def validate_gradient(self):
        gradient = np.asarray(self.gradient_hartree_per_bohr, dtype=float)
        if gradient.shape != (len(self.molecule.symbols), 3) or not np.isfinite(gradient).all():
            raise ValueError("A reference requires a finite Cartesian energy gradient for every atom")
        return self


def _reference_artifact(snapshot: Path, attempt: Attempt, name: str, *, stage: str | None = None) -> Path:
    """Bind a retained native file to its exact stage, never an arbitrary basename."""
    receipt = stage == "" and re.fullmatch(r"optimization-stage-[0-3]\.json", name)
    if (name not in {"job.inp", "engine.stdout", "job.engrad", "job.xyz"} and not receipt
            or stage is not None and not re.fullmatch(r"(?:optimization-refinement-[1-3](?:/final-gradient)?|final-gradient)?", stage)):
        raise ValueError("Unknown DFT native evidence stage or filename")
    if stage is None:
        matches = [artifact for artifact in attempt.artifacts if Path(artifact.path).name == name]
    else:
        expected = (Path("attempts") / attempt.attempt_id / stage / name).as_posix()
        matches = [artifact for artifact in attempt.artifacts if artifact.path == expected]
    if len(matches) != 1:
        raise IntegrityError(f"DFT reference requires exactly one retained {stage or 'native'}/{name}")
    artifact = matches[0]
    path = confined_file(snapshot, "artifacts/" + artifact.path)
    if path.stat().st_size != artifact.size_bytes or file_digest(path) != artifact.sha256:
        raise IntegrityError("Immutable DFT source artifact changed during import")
    return path


def _dft_output_energy(path: Path) -> tuple[str, float]:
    stdout = path.read_text(errors="replace")
    if (_engine_version(stdout, "orca") != "6.1.1" or "ORCA TERMINATED NORMALLY" not in stdout
            or "SCF CONVERGED AFTER" not in stdout
            or re.search(r"SCF NOT CONVERGED|SCF CONVERGENCE FAILURE", stdout, re.I)):
        raise IntegrityError("DFT native output does not establish version and electronic convergence")
    totals = re.findall(r"FINAL SINGLE POINT ENERGY\s+(\S+)", stdout)
    if not totals:
        raise IntegrityError("DFT native total energy is absent")
    return stdout, _number(totals[-1])


def _final_gradient_contract(attempt: Attempt, molecule: Molecule, method: MethodSpec,
                             resources: ResourceLimits, *, optimization_stage: str = "") -> dict:
    """Reject an unbound final stage before reading any of its scientific data."""
    stage = attempt.metadata.get("final_gradient_verification")
    expected_directory = (Path(optimization_stage) / "final-gradient").as_posix()
    if (optimization_stage and not re.fullmatch(r"optimization-refinement-[1-3]", optimization_stage)
            or not isinstance(stage, dict) or stage.get("directory") != expected_directory
            or stage.get("execution_kind") != "real" or stage.get("engine") != "orca"
            or stage.get("engine_version") != attempt.engine_version
            or stage.get("executable_sha256") != attempt.metadata.get("executable_sha256")
            or not re.fullmatch(_SHA, str(stage.get("executable_sha256", "")))
            or stage.get("method") != method.model_dump(mode="json")
            or stage.get("input_molecule_sha256") != digest_json(molecule.model_dump(mode="json"))
            or not attempt.command or stage.get("command") != [attempt.command[0], "job.inp"]):
        raise IntegrityError("Optimized DFT reference lacks its exact independent final-gradient identity")
    final_resources = ResourceLimits.model_validate(stage.get("resources"))
    if (final_resources.model_dump(exclude={"budget_seconds"}) != resources.model_dump(exclude={"budget_seconds"})
            or final_resources.budget_seconds > resources.budget_seconds):
        raise IntegrityError("Final DFT gradient changed its native allocation/input resource convention")
    hashes = stage.get("native_files_sha256")
    if (not isinstance(hashes, dict) or set(hashes) != {"job.inp", "engine.stdout", "job.engrad"}
            or any(not re.fullmatch(_SHA, str(value)) for value in hashes.values())):
        raise IntegrityError("Final DFT gradient lacks exact native input/output/gradient hashes")
    return stage


def _optimization_refinement_contract(attempt: Attempt, initial: Molecule, molecule: Molecule,
                                      method: MethodSpec, resources: ResourceLimits) -> list[dict]:
    """Validate the bounded native restart chain before selecting any raw stage."""
    history = attempt.metadata.get("optimization_refinement")
    if history is None:
        return []
    if (not isinstance(history, dict) or history.get("schema") != "topos-orca-optimization-refinement/1"
            or history.get("maximum_restarts") != 3
            or not attempt.command
            or history.get("initial_molecule") != initial.model_dump(mode="json")):
        raise IntegrityError("DFT optimization refinement lacks its original geometry and bounded protocol")
    stages = history.get("stages")
    if not isinstance(stages, list) or not 2 <= len(stages) <= 4:
        raise IntegrityError("DFT optimization refinement must retain every bounded native stage")
    original = ResourceLimits.model_validate(history.get("original_resources"))
    expected_input = initial.model_dump(mode="json")
    previous_budget = original.budget_seconds
    for index, stage in enumerate(stages):
        directory = "." if index == 0 else f"optimization-refinement-{index}"
        if (not isinstance(stage, dict) or stage.get("stage_directory") != directory
                or stage.get("input_molecule") != expected_input
                or stage.get("method") != method.model_dump(mode="json")
                or stage.get("engine_version") != attempt.engine_version
                or stage.get("executable_sha256") != attempt.metadata.get("executable_sha256")
                or stage.get("command") != [attempt.command[0], "job.inp"]
                or stage.get("process", {}).get("status") != "completed"
                or stage.get("process", {}).get("returncode") != 0
                or stage.get("status") != ("completed" if index == len(stages) - 1 else "partial")
                or stage.get("native_optimizer_reported_converged") is not True
                or stage.get("converged") is not (index == len(stages) - 1)):
            raise IntegrityError("DFT optimization refinement changed identity or skipped a native stage")
        allocation = ResourceLimits.model_validate(stage.get("resources"))
        if (allocation.model_dump(exclude={"budget_seconds"}) != original.model_dump(exclude={"budget_seconds"})
                or allocation.budget_seconds > previous_budget
                or index == 0 and allocation != original):
            raise IntegrityError("DFT optimization refinement changed allocation or reset its deadline")
        output = Molecule.model_validate(stage.get("output_molecule"))
        if output.model_dump(exclude={"coordinates", "name"}) != initial.model_dump(exclude={"coordinates", "name"}):
            raise IntegrityError("DFT optimization refinement changed molecular identity")
        previous_budget = allocation.budget_seconds
        expected_input = output.model_dump(mode="json")
    if (history.get("accepted_stage_directory") != stages[-1]["stage_directory"]
            or history.get("final_stage_directory") != stages[-1]["stage_directory"]
            or expected_input != molecule.model_dump(mode="json")
            or stages[-1]["resources"] != resources.model_dump(mode="json")
            or stages[-1].get("final_gradient_verification") != attempt.metadata.get("final_gradient_verification")
            or any(stages[-1].get(key) != attempt.diagnostics.get(key) for key in (
                "process", "convergence", "native_optimizer_reported_converged", "independent_stationarity"))):
        raise IntegrityError("DFT optimized result does not identify the final accepted native stage")
    return stages


def _optimization_stage_receipt(snapshot: Path, attempt: Attempt, index: int,
                                stage: dict) -> tuple[Path, EngineResult]:
    """Bind history to the unchanged per-stage result before reparsing raw files."""
    name = f"optimization-stage-{index}.json"
    path = _reference_artifact(snapshot, attempt, name, stage="")
    receipt = stage.get("receipt")
    if receipt != {"path": name, "sha256": file_digest(path), "size_bytes": path.stat().st_size}:
        raise IntegrityError("DFT refinement stage receipt changed or identifies another stage")
    native = EngineResult.model_validate_json(path.read_text())
    if (not math.isfinite(native.elapsed_seconds) or native.elapsed_seconds <= 0
            or native.elapsed_seconds > ResourceLimits.model_validate(stage["resources"]).budget_seconds):
        raise IntegrityError("DFT refinement receipt exceeds its remaining wall budget")
    gradient = native.metadata.get("final_gradient_verification")
    if gradient is not None:
        gradient = dict(gradient)
        if gradient.get("directory") != "final-gradient":
            raise IntegrityError("DFT refinement receipt has an unexpected native gradient directory")
        gradient["directory"] = (Path(stage["stage_directory"]) / "final-gradient").as_posix()
    if (native.engine != "orca" or native.operation != "optimize"
            or native.metadata.get("execution_kind") != "real"
            or native.method != attempt.method or native.engine_version != stage["engine_version"]
            or native.metadata.get("executable_sha256") != stage["executable_sha256"]
            or native.metadata.get("requested_method") != stage["method"]
            or native.metadata.get("resources") != stage["resources"]
            or native.command != stage["command"] or native.status != stage["status"]
            or native.converged is not stage["converged"] or native.molecule is None
            or native.molecule.model_dump(mode="json") != stage["output_molecule"]
            or any(native.diagnostics.get(key) != stage.get(key) for key in (
                "process", "convergence", "native_optimizer_reported_converged", "independent_stationarity"))
            or gradient != stage.get("final_gradient_verification")):
        raise IntegrityError("DFT refinement history differs from its retained native stage receipt")
    return path, native


def _optimization_refinement_evidence(snapshot: Path, attempt: Attempt, stages: list[dict],
                                      method: MethodSpec) -> dict[str, Path]:
    """Reparse each unchanged optimizer stage; no metadata pass flag is enough."""
    retained = {}
    remaining_ceiling = None
    for index, stage in enumerate(stages):
        receipt, native = _optimization_stage_receipt(snapshot, attempt, index, stage)
        retained[receipt.name] = receipt
        directory = "" if index == 0 else stage["stage_directory"]
        files = {name: _reference_artifact(snapshot, attempt, name, stage=directory)
                 for name in ("job.inp", "engine.stdout", "job.xyz")}
        initial = Molecule.model_validate(stage["input_molecule"])
        output = Molecule.model_validate(stage["output_molecule"])
        allocation = ResourceLimits.model_validate(stage["resources"])
        if remaining_ceiling is not None and allocation.budget_seconds > remaining_ceiling + 1e-9:
            raise IntegrityError("DFT refinement restarted without charging the preceding native stage")
        remaining_ceiling = allocation.budget_seconds - native.elapsed_seconds
        if files["job.inp"].read_text() != _orca_input(initial, method, allocation, "optimize"):
            raise IntegrityError("DFT refinement native input changed its recorded method or geometry")
        stdout, optimizer_energy = _dft_output_energy(files["engine.stdout"])
        criteria = _orca_convergence(stdout)
        if ("THE OPTIMIZATION HAS CONVERGED" not in stdout or len(criteria) != 5
                or criteria != stage.get("convergence")
                or native.energy_hartree != optimizer_energy
                or read_xyz(files["job.xyz"], initial) != output):
            raise IntegrityError("DFT refinement lacks a genuine native optimizer endpoint")
        if index == len(stages) - 1 and not all(criteria.values()):
            raise IntegrityError("Final DFT refinement did not meet all five geometry gates")
        if index < len(stages) - 1 and all(criteria.values()):
            # A restart after all native gates passed is justified only by the
            # independently evaluated final gradient, at these same tolerances.
            final_directory = (Path(directory) / "final-gradient").as_posix()
            gradient_files = {name: _reference_artifact(snapshot, attempt, name, stage=final_directory)
                              for name in ("job.inp", "engine.stdout", "job.engrad")}
            verified = stage.get("final_gradient_verification")
            temporary = attempt.model_copy(deep=True)
            temporary.metadata["final_gradient_verification"] = verified
            contract = _final_gradient_contract(temporary, output, method, allocation,
                                                optimization_stage=directory)
            if (any(file_digest(path) != contract["native_files_sha256"][name]
                    for name, path in gradient_files.items())
                    or gradient_files["job.inp"].read_text() != _orca_input(
                        output, method, ResourceLimits.model_validate(contract["resources"]), "gradient")):
                raise IntegrityError("DFT refinement restart gradient changed its bound native evidence")
            _, native_energy = _dft_output_energy(gradient_files["engine.stdout"])
            derivative_energy, gradient = parse_orca_engrad(gradient_files["job.engrad"], output)
            if (abs(derivative_energy - native_energy) > 2e-7 or abs(native_energy - optimizer_energy) > 2e-7
                    or contract.get("energy_hartree") != native_energy
                    or contract.get("energy_difference_hartree") != native_energy - optimizer_energy):
                raise IntegrityError("DFT refinement restart gradient has inconsistent energies")
            if native.gradient_hartree_per_bohr != gradient:
                raise IntegrityError("DFT refinement receipt changed its independently evaluated native gradient")
            _validate_final_stationarity(gradient, method, stage.get("independent_stationarity"), expected_passed=False)
            retained.update({(Path(final_directory) / name).as_posix(): path for name, path in gradient_files.items()})
        elif index < len(stages) - 1 and (stage.get("final_gradient_verification") is not None
                                        or stage.get("independent_stationarity") is not None
                                        or native.gradient_hartree_per_bohr is not None):
            raise IntegrityError("DFT refinement claims a final gradient before all native geometry gates passed")
        retained.update({(Path(directory) / name).as_posix(): path for name, path in files.items()})
    return retained


def _validate_final_stationarity(gradient: list[list[float]], method: MethodSpec, stationarity: dict,
                                 *, expected_passed: bool = True) -> None:
    """Recompute Cartesian stationarity; a stored pass flag is insufficient."""
    values = np.asarray(gradient, dtype=float)
    if values.ndim != 2 or not len(values) or values.shape[1] != 3 or not np.isfinite(values).all():
        raise IntegrityError("Final DFT gradient has invalid Cartesian components")
    strict = method.profile_id == "orca-vpt2-reference-v1"
    max_limit, rms_limit = (1e-7, 3e-8) if strict else (1e-5, 3e-6)
    maximum, rms = float(np.max(np.abs(values))), float(np.sqrt(np.mean(values ** 2)))
    passed = maximum <= max_limit and rms <= rms_limit
    if (not isinstance(stationarity, dict) or passed is not expected_passed or stationarity.get("passed") is not passed
            or stationarity.get("max_gradient_threshold") != max_limit
            or stationarity.get("rms_gradient_threshold") != rms_limit
            or any(isinstance(stationarity.get(key), bool) or not isinstance(stationarity.get(key), (float, int))
                   or not math.isfinite(stationarity[key]) or abs(stationarity[key] - actual) > 1e-15
                   for key, actual in (("max_gradient_hartree_per_bohr", maximum), ("rms_gradient_hartree_per_bohr", rms)))):
        raise IntegrityError("Optimized DFT reference lacks independently verified final-gradient stationarity")


def import_dft_point(source: DFTSourcePoint, destination: str | Path) -> ReferenceFrame:
    """Reparse an explicitly selected immutable ORCA DFT energy/gradient run."""
    raw_root = Path(source.run_dir).expanduser()
    if "://" in source.run_dir or not raw_root.is_absolute() or raw_root.is_symlink():
        raise ValueError("DFT provenance requires an explicit absolute nonsymlink local RunStore")
    root = raw_root.resolve(strict=True)
    if not root.is_dir() or not (root / "CURRENT.json").is_file():
        raise ValueError("DFT provenance does not identify a committed local RunStore")
    store = RunStore(root)
    raw, manifest = store.load(), store.verify()
    if digest_json(raw) != source.record_sha256 or manifest["record_sha256"] != source.record_sha256:
        raise IntegrityError("DFT source differs from the explicitly selected immutable record")
    snapshot = store.snapshots / manifest["snapshot_id"]
    record = RunRecord.model_validate(raw)
    matches = [attempt for attempt in record.attempts if attempt.attempt_id == source.attempt_id]
    if len(matches) != 1:
        raise ValueError("Select exactly one retained DFT attempt")
    attempt = matches[0]
    if (attempt.status != "completed" or not attempt.converged
            or attempt.validation_status != "validated-for-protocol" or attempt.engine != "orca"
            or attempt.engine_version != "6.1.1" or attempt.method not in DFT_METHODS
            or attempt.metadata.get("execution_kind") != "real" or not attempt.command
            or not re.fullmatch(_SHA, str(attempt.metadata.get("executable_sha256", "")))):
        raise ValueError("Reference data require a real completed ORCA 6.1.1 DFT gradient attempt")
    method = MethodSpec.model_validate(attempt.metadata.get("requested_method"))
    if (method.engine != "orca" or method.method != attempt.method or method.method not in DFT_METHODS
            or method.solvent or method.constraints or attempt.metadata.get("external_basis")):
        raise ValueError("DFT labels require an explicit supported common gas-phase method/basis protocol")
    molecule = Molecule.model_validate(attempt.metadata.get("output_molecule"))
    initial = Molecule.model_validate(attempt.metadata.get("input_molecule"))
    if molecule.model_dump(exclude={"coordinates", "name"}) != initial.model_dump(exclude={"coordinates", "name"}):
        raise IntegrityError("DFT reference changed molecular identity")
    if molecule.charge != 0 or molecule.multiplicity != 1 or molecule.environment:
        raise ValueError("This MACE molecular fine-tuning adapter requires neutral closed-shell gas-phase data")
    operation = attempt.metadata.get("operation", attempt.metadata.get("native_result", {}).get("operation"))
    if operation not in {"gradient", "optimize"}:
        raise ValueError("DFT training data require an actual analytic-gradient calculation")
    resources = ResourceLimits.model_validate(attempt.metadata.get("resources"))

    stages = (_optimization_refinement_contract(attempt, initial, molecule, method, resources)
              if operation == "optimize" else [])
    selected_stage = stages[-1]["stage_directory"] if stages else ("" if operation == "optimize" else None)
    stage_initial = Molecule.model_validate(stages[-1]["input_molecule"]) if stages else initial
    retained = _optimization_refinement_evidence(snapshot, attempt, stages, method)

    def native_file(name: str, stage: str | None = selected_stage) -> Path:
        return _reference_artifact(snapshot, attempt, name, stage=stage)

    deck = native_file("job.inp").read_text()
    if deck != _orca_input(stage_initial, method, resources, operation):
        raise IntegrityError("DFT native input differs from the recorded typed Hamiltonian and geometry")
    stdout, optimizer_energy = _dft_output_energy(native_file("engine.stdout"))
    retained.update({(Path(selected_stage or "") / name).as_posix(): native_file(name)
                     for name in ("job.inp", "engine.stdout")})
    if operation == "optimize":
        criteria = _orca_convergence(stdout)
        if "THE OPTIMIZATION HAS CONVERGED" not in stdout or len(criteria) != 5 or not all(criteria.values()):
            raise IntegrityError("DFT optimization raw output does not establish all five geometry gates")
        if read_xyz(native_file("job.xyz"), stage_initial).coordinates != molecule.coordinates:
            raise IntegrityError("DFT stored output geometry differs from its native XYZ")
        retained[(Path(selected_stage) / "job.xyz").as_posix()] = native_file("job.xyz")
        stage = _final_gradient_contract(attempt, molecule, method, resources,
                                         optimization_stage=selected_stage)
        final_files = {name: native_file(name, stage["directory"]) for name in stage["native_files_sha256"]}
        if any(file_digest(path) != stage["native_files_sha256"][name] for name, path in final_files.items()):
            raise IntegrityError("Final DFT gradient native file differs from its bound stage identity")
        final_resources = ResourceLimits.model_validate(stage["resources"])
        if final_files["job.inp"].read_text() != _orca_input(molecule, method, final_resources, "gradient"):
            raise IntegrityError("Final DFT gradient input differs from its exact optimized geometry and Hamiltonian")
        _, final_energy = _dft_output_energy(final_files["engine.stdout"])
        energy, gradient = parse_orca_engrad(final_files["job.engrad"], molecule)
        if (abs(energy - final_energy) > 2e-7 or abs(energy - optimizer_energy) > 2e-7
                or stage.get("energy_hartree") != final_energy
                or stage.get("energy_difference_hartree") != final_energy - optimizer_energy):
            raise IntegrityError("DFT optimization, final-gradient output and derivative energies disagree")
        _validate_final_stationarity(gradient, method, attempt.diagnostics.get("independent_stationarity", {}))
        if stages:
            final_receipt = EngineResult.model_validate_json(retained[f"optimization-stage-{len(stages)-1}.json"].read_text())
            if final_receipt.gradient_hartree_per_bohr != gradient:
                raise IntegrityError("Final DFT refinement receipt changed its native gradient")
        retained.update({stage["directory"] + "/" + name: path for name, path in final_files.items()})
    elif initial.coordinates != molecule.coordinates:
        raise IntegrityError("A DFT single-point gradient changed its geometry")
    else:
        energy, gradient = parse_orca_engrad(native_file("job.engrad"), molecule)
        if abs(energy - optimizer_energy) > 2e-7:
            raise IntegrityError("DFT gradient and output energies disagree")
        retained["job.engrad"] = native_file("job.engrad")
    for name, units, actual in (("electronic_energy", "hartree", energy),
                                ("cartesian_gradient", "hartree/bohr", gradient)):
        quantities = [quantity for quantity in attempt.quantities
                      if quantity.name == name and quantity.units == units
                      and quantity.validity == "validated-for-protocol"]
        if len(quantities) != 1 or np.shape(quantities[0].value) != np.shape(actual) or not np.allclose(
                quantities[0].value, actual, rtol=0, atol=2e-7 if name == "electronic_energy" else 1e-12):
            raise IntegrityError("DFT structured quantities differ from native energy/gradient observations")
    target = Path(destination)
    if target.is_symlink():
        raise IntegrityError("DFT evidence destination must not be a symlink")
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise ValueError("DFT evidence import requires a fresh directory")
    for name, original in retained.items():
        copied = target / name
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, copied)
    atomic_json(target / "source-record.json", raw)
    atomic_json(target / "source-manifest.json", manifest)
    frame = ReferenceFrame(source=source, molecule=molecule, method=method,
                           energy_hartree=energy, gradient_hartree_per_bohr=gradient)
    atomic_json(target / "reference.json", frame.model_dump(mode="json"))
    return frame


def _configuration_key(molecule: Molecule) -> str:
    """Conservative isotope/species distance fingerprint, not an identity proof.

    Atom IDs/order cannot hide a duplicate from permutation-invariant models.
    Sorted per-center distance profiles also ignore rigid motion and reflection;
    homometric configurations can collide and are conservatively kept out of
    separate partitions. Exact target atom mapping is checked independently.
    """
    xyz = np.asarray(molecule.coordinates)
    distances = np.round(np.linalg.norm(xyz[:, None] - xyz[None, :], axis=2), 8)
    labels = list(zip(molecule.symbols, [isotope or 0 for isotope in molecule.isotopes], strict=True))
    centers = sorted((labels[i], sorted((labels[j], float(distances[i, j]))
                                       for j in range(len(labels)) if i != j)) for i in range(len(labels)))
    return digest_json({"fingerprint": "species-isotope-distance-profiles-v1",
                        "charge": molecule.charge, "multiplicity": molecule.multiplicity,
                        "environment": molecule.environment, "centers": centers})


def validate_reference_partition(frames: list[ReferenceFrame]) -> dict[str, Any]:
    """Check numerical compatibility and duplicate leakage, without native attestation."""
    TrainingDatasetSpec(points=[frame.source for frame in frames],
                        partition_rationale="Validation of supplied explicit partitions")
    identity = frames[0].molecule.model_dump(exclude={"coordinates", "name"})
    protocol = frames[0].method.model_dump(exclude={"purpose"})
    seen = set()
    counts = dict.fromkeys(("train", "validation", "test"), 0)
    for frame in frames:
        if frame.molecule.model_dump(exclude={"coordinates", "name"}) != identity:
            raise ValueError("System-specific training points must share atom mapping and molecular state")
        if frame.method.model_dump(exclude={"purpose"}) != protocol:
            raise ValueError("All system-specific labels require the same explicit DFT Hamiltonian")
        key = _configuration_key(frame.molecule)
        if key in seen:
            raise ValueError("Duplicate configurations, including rigidly rotated/translated copies, leak or reweight data")
        seen.add(key)
        counts[frame.source.partition] += 1
    return {"counts": counts, "reference_protocol": protocol,
            "configuration_keys": sorted(seen),
            "split_scope": "explicit related-configuration groups; no group crosses partitions; conservative species/isotope-labelled permutation/rigid-invariant distance fingerprint at 1e-8 angstrom, not molecular identity proof",
            "native_provenance_verified": False}


def validate_training_target(frames: list[ReferenceFrame], expected_molecule: Molecule | None = None) -> dict[str, Any]:
    """Bind system-specific labels to one exact chemical identity, not a shape.

    Distorted DFT configurations are legitimate training points. Distances are
    therefore not used to invent or replace their declared graph; atom IDs,
    declared bonds, fragments, isotopes, state and stereochemistry must agree.
    """
    if not frames:
        raise ValueError("System-specific training requires reference configurations")
    target = expected_molecule or frames[0].molecule
    target = Molecule.model_validate(target.model_dump(mode="json"))
    identity = target.model_dump(mode="json", exclude={"coordinates", "name"})
    for frame in frames:
        if frame.molecule.model_dump(mode="json", exclude={"coordinates", "name"}) != identity:
            raise ValueError("System-specific DFT dataset identity differs from the requested target molecule")
    return {"molecule_identity": identity, "molecule_identity_sha256": molecule_system_identity(target),
            "bound_to_requested_target": expected_molecule is not None,
            "geometry_scope": "supplied system-specific configurations; coordinates may differ",
            "graph_policy": "preserve declared graph; no distance-threshold reassignment on distorted points",
            "transferability_outside_target_assessed": False}


def _trained_manifest(manifest: ModelManifest, checkpoint: Path, request: dict,
                      prepared: dict, domain: dict, folder: Path) -> ModelManifest:
    trained = manifest.model_dump(mode="json")
    trained.update(head="Default", precision="float64",
        family=manifest.family + "/system-finetuned",
        training_method=json.dumps(prepared["reference_protocol"], sort_keys=True),
        supported_elements=sorted(set(domain["molecule_identity"]["symbols"])),
        system_identity_sha256=domain["molecule_identity_sha256"],
        domain_reference=("System-specific Default head; target_identity_sha256=" + domain["molecule_identity_sha256"]
            + "; dataset_specification_sha256=" + prepared["specification_sha256"]
            + "; transferability outside this target is unassessed. Foundation provenance: " + manifest.domain_reference),
        members=[{"path": str(checkpoint), "sha256": file_digest(checkpoint),
                  "training_run_id": digest_json(request), "source": str(folder / "training-request.json")}])
    return ModelManifest.model_validate(trained)


def reference_extxyz(frames: list[ReferenceFrame]) -> str:
    """MACE/ASE extended XYZ: absolute eV energies and forces = -dE/dx, eV/Å."""
    rows = []
    for frame in frames:
        forces = -np.asarray(frame.gradient_hartree_per_bohr) * HARTREE_EV / BOHR_ANGSTROM
        rows.extend([str(len(frame.molecule.symbols)),
                     'Properties=species:S:1:pos:R:3:REF_forces:R:3 pbc="F F F" '
                     f'REF_energy={frame.energy_hartree * HARTREE_EV:.17g} '
                     f'config_type="system" source_id="{digest_json(frame.source.model_dump())}"'])
        for symbol, xyz, force in zip(frame.molecule.symbols, frame.molecule.coordinates, forces, strict=True):
            rows.append(symbol + " " + " ".join(format(float(value), ".17g") for value in [*xyz, *force]))
    return "\n".join(rows) + "\n"


def prepare_training_dataset(specification: TrainingDatasetSpec, destination: str | Path, *,
                             deadline: float | None = None,
                             cancel_event: Event | None = None) -> dict[str, Any]:
    specification = TrainingDatasetSpec.model_validate(specification.model_dump())
    raw_target = Path(destination)
    if raw_target.is_symlink():
        raise IntegrityError("Training dataset destination cannot be a symlink")
    target = raw_target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise ValueError("Training dataset preparation requires a fresh directory")
    frames = []
    for index, source in enumerate(specification.points):
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("DFT dataset verification cancelled")
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("DFT dataset verification deadline reached")
        frames.append(import_dft_point(source, target / "sources" / f"point-{index:04d}"))
    report = validate_reference_partition(frames)
    files = {}
    for partition in ("train", "validation", "test"):
        path = target / f"{partition}.extxyz"
        path.write_text(reference_extxyz([frame for frame in frames if frame.source.partition == partition]))
        files[partition] = {"path": str(path), "sha256": file_digest(path)}
    report.update(schema_version="topos-dft-training-data/1", native_provenance_verified=True,
                  specification=specification.model_dump(mode="json"),
                  specification_sha256=digest_json(specification.model_dump(mode="json")),
                  frames=[frame.model_dump(mode="json") for frame in frames], files=files,
                  units={"energy": "eV", "force": "eV/angstrom", "geometry": "angstrom"},
                  heldout_policy="Test points are excluded from fitting, epoch selection and CLI training input")
    atomic_json(target / "dataset.json", report)
    return report


def numerical_error_metrics(reference_energies, predicted_energies, reference_gradients,
                            predicted_gradients) -> dict[str, float]:
    """Pure error arithmetic; the caller establishes independent native/model provenance."""
    reference = np.asarray(reference_energies, dtype=float)
    predicted = np.asarray(predicted_energies, dtype=float)
    if (reference.ndim != 1 or not len(reference) or predicted.shape != reference.shape
            or not np.isfinite(reference).all() or not np.isfinite(predicted).all()
            or len(reference_gradients) != len(reference) or len(predicted_gradients) != len(reference)):
        raise ValueError("Finite paired energies and gradients are required for every held-out frame")
    atom_counts, force_errors = [], []
    for wanted, actual in zip(reference_gradients, predicted_gradients, strict=True):
        wanted, actual = np.asarray(wanted, dtype=float), np.asarray(actual, dtype=float)
        if (wanted.ndim != 2 or wanted.shape[1] != 3 or not len(wanted) or actual.shape != wanted.shape
                or not np.isfinite(wanted).all() or not np.isfinite(actual).all()):
            raise ValueError("Held-out gradients must have matching finite atom-by-three shapes")
        atom_counts.append(len(wanted))
        force_errors.extend(((actual - wanted) * HARTREE_EV / BOHR_ANGSTROM).ravel())
    energy_error = (predicted - reference) * HARTREE_EV
    per_atom = energy_error / atom_counts
    force_error = np.asarray(force_errors)
    with np.errstate(over="ignore", invalid="ignore"):
        result = {"energy_mae_ev": float(np.mean(np.abs(energy_error))),
                  "energy_rmse_ev": float(np.sqrt(np.mean(energy_error**2))),
                  "energy_per_atom_mae_ev": float(np.mean(np.abs(per_atom))),
                  "energy_per_atom_rmse_ev": float(np.sqrt(np.mean(per_atom**2))),
                  "force_component_mae_ev_per_angstrom": float(np.mean(np.abs(force_error))),
                  "force_component_rmse_ev_per_angstrom": float(np.sqrt(np.mean(force_error**2)))}
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError("Held-out error arithmetic overflowed")
    return result


def heldout_errors(frames: list[ReferenceFrame], predictions: list[EngineResult], *,
                   manifest_sha256: str) -> dict[str, Any]:
    if not frames or len(frames) != len(predictions) or any(frame.source.partition != "test" for frame in frames):
        raise ValueError("Held-out reporting requires every explicitly selected test frame exactly once")
    if len({_configuration_key(frame.molecule) for frame in frames}) != len(frames):
        raise ValueError("Held-out configurations must be distinct")
    for frame, prediction in zip(frames, predictions, strict=True):
        if (prediction.status != "completed" or prediction.metadata.get("execution_kind") != "real"
                or prediction.engine != "mace" or prediction.metadata.get("manifest_sha256") != manifest_sha256
                or prediction.molecule != frame.molecule or prediction.energy_hartree is None
                or prediction.gradient_hartree_per_bohr is None):
            raise ValueError("Held-out comparison requires genuine matching MACE predictions from one exact checkpoint manifest")
    return {"count": len(frames), "manifest_sha256": manifest_sha256,
            "metrics": numerical_error_metrics([frame.energy_hartree for frame in frames],
                [prediction.energy_hartree for prediction in predictions],
                [frame.gradient_hartree_per_bohr for frame in frames],
                [prediction.gradient_hartree_per_bohr for prediction in predictions]),
            "accuracy_guarantee": None, "culling_authorized": False,
            "interpretation": "Errors on the explicitly held-out configurations only; no global surface-accuracy or basin-completeness claim"}


class ReplayFile(Contract):
    """Explicit prior training data, never a model name that triggers a download."""

    path: str
    sha256: str = Field(pattern=_SHA)
    source: str = Field(min_length=1)
    reference_method: str = Field(min_length=1)
    license_name: str = Field(min_length=1)
    energy_units: Literal["eV"] = "eV"
    force_units: Literal["eV/angstrom"] = "eV/angstrom"

    def verify(self) -> Path:
        path = Path(self.path)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError("Replay data must be explicit absolute regular files")
        if path.stat().st_size > 128 * 1024 * 1024 or file_digest(path) != self.sha256:
            raise IntegrityError("Replay data exceed the bounded file size or differ from their hash")
        return path


class MACETrainingOptions(Contract):
    package_version: Literal["0.3.16"] = "0.3.16"
    name: str = Field(default="topos_finetune", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    seed: int = Field(ge=0, strict=True)
    max_epochs: int = Field(ge=1, le=100000, strict=True)
    batch_size: int = Field(default=5, ge=1, le=128, strict=True)
    atomic_energy_baseline: Literal["foundation"]
    replay_train: ReplayFile
    replay_validation: ReplayFile
    energy_weight: float = Field(default=1.0, gt=0)
    forces_weight: float = Field(default=100.0, gt=0)
    gpu_index: int = Field(ge=0, strict=True)
    gpu_memory_mb: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def distinct_replay(self):
        if self.replay_train.sha256 == self.replay_validation.sha256:
            raise ValueError("Replay training and validation files must be distinct")
        if self.replay_train.reference_method != self.replay_validation.reference_method:
            raise ValueError("Replay training and validation labels require the same reference method")
        return self


def compile_mace_training_command(interpreter: str, foundation: Path, train: Path,
                                  validation: Path, replay_train: Path, replay_validation: Path,
                                  output: Path, options: MACETrainingOptions,
                                  *, foundation_head: str | None = None) -> list[str]:
    """Official v0.3.16 CLI; test data are intentionally absent from its inputs.

    Local checkpoints require explicit replay files to prevent upstream silently
    disabling multihead fine-tuning. Foundation E0s are a declared model baseline,
    not newly calculated isolated-atom DFT reference energies.
    """
    paths = [Path(interpreter), foundation, train, validation, replay_train, replay_validation, output]
    if any(not path.is_absolute() for path in paths):
        raise ValueError("Training command paths must be explicit absolute paths")
    options = MACETrainingOptions.model_validate(options.model_dump())
    arguments = {
        "name": options.name, "seed": options.seed, "device": "cuda", "default_dtype": "float64",
        "foundation_model": str(foundation), "multiheads_finetuning": "True",
        "train_file": str(train), "valid_file": str(validation),
        "pt_train_file": str(replay_train), "pt_valid_file": str(replay_validation),
        "E0s": options.atomic_energy_baseline, "energy_key": "REF_energy", "forces_key": "REF_forces",
        "max_num_epochs": options.max_epochs, "batch_size": options.batch_size,
        "valid_batch_size": options.batch_size, "num_workers": 0,
        "energy_weight": options.energy_weight, "forces_weight": options.forces_weight,
        "plot": "False", "error_table": "PerAtomRMSE", "launcher": "none",
        "work_dir": str(output), "model_dir": str(output / "models"),
        "checkpoints_dir": str(output / "checkpoints"), "results_dir": str(output / "results"),
        "log_dir": str(output / "logs"), "downloads_dir": str(output / "downloads"),
    }
    if foundation_head is not None:
        arguments["foundation_head"] = foundation_head
    return [interpreter, "-m", "mace.cli.run_train", *[f"--{key}={value}" for key, value in arguments.items()],
            "--save_cpu", "--keep_checkpoints"]


def _validate_replay(options: MACETrainingOptions, frames: list[ReferenceFrame]) -> None:
    try:
        from ase.io import read
    except ImportError as exc:
        raise ValueError("Replay validation requires the official ASE extended-XYZ reader") from exc
    reference_keys = {_configuration_key(frame.molecule) for frame in frames}
    replay_keys = set()
    for source in (options.replay_train, options.replay_validation):
        path = source.verify()
        atoms_list = read(path, index=":", format="extxyz")
        if not atoms_list:
            raise ValueError("Replay files must contain actual prior energy/force configurations")
        for atoms in atoms_list:
            energy, forces = atoms.info.get("REF_energy"), atoms.arrays.get("REF_forces")
            if (energy is None or forces is None or not math.isfinite(float(energy))
                    or np.shape(forces) != (len(atoms), 3) or not np.isfinite(forces).all()
                    or np.any(atoms.pbc)):
                raise ValueError("Replay labels must be finite nonperiodic REF_energy/REF_forces in eV and eV/angstrom")
            molecule = Molecule(symbols=atoms.get_chemical_symbols(), coordinates=atoms.positions.tolist())
            # The reference system may carry explicit bond/isotope labels absent
            # from the replay format; compare its geometry under those labels too.
            for frame in frames[:1]:
                if molecule.symbols == frame.molecule.symbols:
                    molecule = frame.molecule.model_copy(update={"coordinates": molecule.coordinates})
            key = _configuration_key(molecule)
            if key in reference_keys or key in replay_keys:
                raise ValueError("Replay partitions must be disjoint and exclude all system-specific configurations")
            replay_keys.add(key)


def _verified_fitted_checkpoint(resume_report: dict[str, Any], manifest: ModelManifest,
                                dataset: TrainingDatasetSpec, options: MACETrainingOptions,
                                expected_molecule: Molecule | None, *, deadline: float,
                                cancel_event: Event | None) -> tuple[dict, dict, ModelManifest, dict]:
    """Verify retained fitting evidence before reusing its checkpoint for heldout.

    A retry may itself have failed during heldout inference. Its immutable source
    report always identifies the original fit, avoiding recursive retraining or
    a claim that the original native training command executed again.
    """
    source = resume_report.get("fitted_checkpoint_source", resume_report)
    if not isinstance(source, dict):
        raise IntegrityError("Checkpoint recovery requires its original fitting report")
    for previous in [resume_report, source] if source is not resume_report else [source]:
        artifacts = previous.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise IntegrityError("Checkpoint recovery requires retained immutable native artifacts")
        seen = set()
        for artifact in artifacts:
            artifact = Artifact.model_validate(artifact)
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Checkpoint verification cancelled")
            if time.monotonic() >= deadline:
                raise TimeoutError("Checkpoint verification deadline reached")
            path = Path(artifact.path)
            if not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
                raise IntegrityError("Checkpoint evidence must use absolute regular paths without symlinks")
            if path.resolve() in seen:
                raise IntegrityError("Checkpoint artifact inventory contains duplicate paths")
            seen.add(path.resolve())
            if not path.is_file() or path.stat().st_size != artifact.size_bytes or file_digest(path) != artifact.sha256:
                raise IntegrityError("Retained checkpoint/training evidence changed")
    process = source.get("process", {})
    if (source.get("schema_version") != "topos-mace-finetuning/1"
            or source.get("execution_kind") != "real" or source.get("checkpoint") is None
            or process.get("status") != "completed" or process.get("returncode") != 0
            or source.get("training_performed") is not True):
        raise IntegrityError("Recovery requires a completed actual native fit with its archived checkpoint")
    paths = {Path(item["path"]).resolve() for item in source["artifacts"]}
    requests = [path for path in paths if path.name == "training-request.json"]
    if len(requests) != 1:
        raise IntegrityError("Recovery requires exactly one original immutable training request")
    request_path = requests[0]
    original = request_path.parent
    if any(not path.is_relative_to(original) for path in paths):
        raise IntegrityError("Original fitting artifacts escape their recorded work directory")
    source_report = original / "training-report.json"
    if (source_report not in paths
            or json.loads(source_report.read_text()) != {k: v for k, v in source.items() if k != "artifacts"}):
        raise IntegrityError("Original fitting report differs from its retained native receipt")
    request = json.loads(request_path.read_text())
    if (digest_json(request) != source.get("request_sha256")
            or request.get("manifest") != manifest.model_dump(mode="json")
            or request.get("dataset") != dataset.model_dump(mode="json")
            or request.get("options") != options.model_dump(mode="json")
            or request.get("command") != process.get("command")):
        raise IntegrityError("Checkpoint recovery model/data/training protocol changed")
    dataset_path = original / "dataset/dataset.json"
    trained_path = original / "trained-model.json"
    if dataset_path not in paths or trained_path not in paths:
        raise IntegrityError("Checkpoint recovery lacks its native dataset or checkpoint manifest receipt")
    if file_digest(dataset_path) != request.get("dataset_sha256"):
        raise IntegrityError("Checkpoint source dataset differs from its training request")
    prepared = json.loads(dataset_path.read_text())
    if (prepared.get("native_provenance_verified") is not True
            or prepared.get("specification_sha256") != digest_json(dataset.model_dump(mode="json"))
            or prepared.get("specification") != dataset.model_dump(mode="json")):
        raise IntegrityError("Checkpoint source data are not the requested verified DFT dataset")
    frames = [ReferenceFrame.model_validate(frame) for frame in prepared["frames"]]
    validated_partition = validate_reference_partition(frames)
    if any(prepared.get(key) != validated_partition[key]
           for key in ("counts", "reference_protocol", "configuration_keys")):
        raise IntegrityError("Checkpoint dataset summary differs from its reference configurations")
    if [frame.source.model_dump(mode="json") for frame in frames] != dataset.model_dump(mode="json")["points"]:
        raise IntegrityError("Checkpoint dataset frames differ from the selected DFT attempts")
    domain = validate_training_target(frames, expected_molecule)
    if request.get("training_domain") != domain or source.get("training_domain") != domain:
        raise IntegrityError("Checkpoint target identity differs from the requested training system")
    checkpoint = original / "native/models" / (options.name + ".model")
    if checkpoint not in paths:
        raise IntegrityError("Checkpoint itself is missing from the immutable fitting evidence")
    if checkpoint.stat().st_size == 0 or file_digest(checkpoint) == manifest.members[0].sha256:
        raise IntegrityError("Retained checkpoint is empty or identical to the unfitted foundation")
    trained = _trained_manifest(manifest, checkpoint, request, prepared, domain, original)
    if (trained.model_dump(mode="json") != source["checkpoint"]
            or json.loads(trained_path.read_text()) != source["checkpoint"]):
        raise IntegrityError("Trained checkpoint manifest differs from the verified fitting protocol")
    stdout_path = Path(process.get("stdout_path", ""))
    if stdout_path not in paths:
        raise IntegrityError("Native fitting stdout is not part of the verified evidence")
    native_evidence = stdout_path.read_text(errors="replace") + "\n" + "\n".join(
        path.read_text(errors="replace") for path in paths if path.parent == original / "native/logs" and path.suffix == ".log")
    if (f"MACE version: {MACE_VERSION}" not in native_evidence
            or "Using multiheads finetuning mode" not in native_evidence
            or "Error-table on TRAIN and VALID:" not in native_evidence
            or not re.search(r"(?m)\bDone\s*$", native_evidence)):
        raise IntegrityError("Retained source lacks actual completed native multihead fitting evidence")
    return source, prepared, trained, domain


def _evaluate_heldout(prepared: dict, trained: ModelManifest, resources: ResourceLimits,
                       options: MACETrainingOptions, folder: Path, runtime, report: dict,
                       *, deadline: float, cancel_event: Event | None) -> dict:
    remaining = deadline - time.monotonic()
    if remaining <= 0 or cancel_event is not None and cancel_event.is_set():
        report.update(status="cancelled" if cancel_event is not None and cancel_event.is_set() else "partial",
                      reason="Checkpoint archived; independent held-out evaluation awaits another invocation")
        return report
    heldout = [ReferenceFrame.model_validate(frame) for frame in prepared["frames"] if frame["source"]["partition"] == "test"]
    predictions = MLRunner(trained, runtime, gpu_index=options.gpu_index,
        gpu_memory_mb=options.gpu_memory_mb).evaluate_frames([frame.molecule for frame in heldout],
            folder / "heldout", resources.model_copy(update={"budget_seconds": remaining}), cancel_event=cancel_event)
    report["execution_kind"] = "real"
    if predictions:
        report["heldout_command"] = predictions[0].command
        report["heldout_process"] = predictions[0].diagnostics.get("process")
        report["heldout_execution_kind"] = predictions[0].metadata.get("execution_kind", "not-executed")
        if report.get("resumed_checkpoint"):
            report["command"] = predictions[0].command
    if len(predictions) != len(heldout) or any(item.status != "completed" for item in predictions):
        report.update(status="partial", reason="Checkpoint archived; actual held-out model evaluation did not complete")
        return report
    report["heldout_errors"] = heldout_errors(heldout, predictions,
        manifest_sha256=digest_json(trained.model_dump(mode="json")))
    report["heldout_errors"]["foundation_pretraining_overlap_assessed"] = False
    report.update(status="completed", reason="Fine-tuned checkpoint and held-out observations archived; GOAT and CREST searches remain separate required stages")
    return report


def run_mace_finetuning(manifest: ModelManifest, dataset: TrainingDatasetSpec,
                        options: MACETrainingOptions, resources: ResourceLimits,
                        workdir: str | Path, *, runtime=None,
                        cancel_event: Event | None = None, expected_molecule: Molecule | None = None,
                        resume_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the official MACE CLI only through the dedicated audited BASE boundary.

    A successful result archives the checkpoint and independently evaluates the
    test partition using the exact target head. Validation data select the model;
    the test partition never enters the training command. There is no CPU fallback.
    """
    started = time.monotonic()
    raw_folder = Path(workdir)
    if raw_folder.is_symlink():
        raise IntegrityError("Fine-tuning work directory cannot be a symlink")
    folder = raw_folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()):
        raise ValueError("Fine-tuning requires a fresh attempt directory")
    report: dict[str, Any] = {"schema_version": "topos-mace-finetuning/1", "status": "unavailable",
                             "execution_kind": "not-executed", "experimental": True,
                             "matrix_row_complete": False, "search_reexecuted": False,
                             "accuracy_guarantee": None, "checkpoint": None, "heldout_errors": None,
                             "training_performed": False, "resumed_checkpoint": False,
                             "heldout_execution_kind": "not-executed",
        "official_source": MACE_SOURCE}
    try:
        manifest = ModelManifest.model_validate(manifest.model_dump())
        dataset = TrainingDatasetSpec.model_validate(dataset.model_dump())
        options = MACETrainingOptions.model_validate(options.model_dump())
        resources = ResourceLimits.model_validate(resources.model_dump())
        if cancel_event is not None and cancel_event.is_set():
            report.update(status="cancelled", reason="Fine-tuning cancelled before dataset import and execution")
            return report
        if resources.device != "gpu":
            report.update(status="unsupported", reason="The matrix fine-tuning stage requires an explicit GPU allocation; no CPU substitution")
            return report
        if manifest.backend != "mace" or len(manifest.members) != 1 or manifest.package_version != MACE_VERSION:
            raise ValueError("Fine-tuning requires one explicit MACE 0.3.16 foundation checkpoint")
        if runtime is None or not callable(getattr(runtime, "run_mace_training_process", None)):
            report["reason"] = "Mandatory CoChem-BASE audited GPU training boundary run_mace_training_process is unavailable"
            return report
        if resume_report is not None:
            source, prepared, trained, domain = _verified_fitted_checkpoint(
                resume_report, manifest, dataset, options, expected_molecule,
                deadline=started + resources.budget_seconds, cancel_event=cancel_event)
            report.update(status="partial", execution_kind="real", resumed_checkpoint=True, fitted_checkpoint_source=source,
                original_training_process=source["process"], process=source["process"],
                checkpoint=trained.model_dump(mode="json"), training_domain=domain,
                request_sha256=source["request_sha256"], dataset_sha256=source["dataset_sha256"],
                partition_counts=prepared["counts"])
            atomic_json(folder / "fitted-checkpoint-source.json", source)
            return _evaluate_heldout(prepared, trained, resources, options, folder, runtime, report,
                                    deadline=started + resources.budget_seconds, cancel_event=cancel_event)
        if options.replay_train.reference_method != manifest.training_method:
            raise ValueError("Replay labels must explicitly match the foundation model's declared training method")
        foundation_path = manifest.members[0].verify()
        prepared = prepare_training_dataset(dataset, folder / "dataset",
            deadline=started + resources.budget_seconds, cancel_event=cancel_event)
        frames = [ReferenceFrame.model_validate(frame) for frame in prepared["frames"]]
        domain = validate_training_target(frames, expected_molecule)
        report["training_domain"] = domain
        for frame in frames:
            manifest.validate_molecule(frame.molecule)
        _validate_replay(options, frames)
        staged = folder / "inputs"
        staged.mkdir()
        foundation = staged / "foundation.model"
        replay_train, replay_validation = staged / "replay-train.extxyz", staged / "replay-validation.extxyz"
        for original, target in ((foundation_path, foundation), (options.replay_train.verify(), replay_train),
                                 (options.replay_validation.verify(), replay_validation)):
            shutil.copyfile(original, target)
        if (file_digest(foundation) != manifest.members[0].sha256
                or file_digest(replay_train) != options.replay_train.sha256
                or file_digest(replay_validation) != options.replay_validation.sha256):
            raise IntegrityError("Training inputs changed during staging")
        executable = runtime.resolve_executable("mace")
        native_folder = folder / "native"
        native_folder.mkdir()
        command = compile_mace_training_command(executable, foundation,
            Path(prepared["files"]["train"]["path"]), Path(prepared["files"]["validation"]["path"]),
            replay_train, replay_validation, native_folder, options, foundation_head=manifest.head)
        request = {"manifest": manifest.model_dump(mode="json"), "dataset": dataset.model_dump(mode="json"),
                   "dataset_sha256": file_digest(folder / "dataset" / "dataset.json"),
                   "options": options.model_dump(mode="json"), "resources": resources.model_dump(mode="json"),
                   "command": command, "output_head": "Default", "training_domain": domain}
        atomic_json(folder / "training-request.json", request)
        inputs = {str(path): file_digest(path) for path in
                  [foundation, replay_train, replay_validation, folder / "training-request.json",
                   folder / "dataset" / "dataset.json", *[Path(item["path"]) for item in prepared["files"].values()]]}
        remaining = resources.budget_seconds - (time.monotonic() - started)
        if remaining <= 0:
            report.update(status="timed-out", reason="Fine-tuning budget exhausted during reference verification")
            return report
        report.update(command=command, request_sha256=digest_json(request),
                      dataset_sha256=request["dataset_sha256"], partition_counts=prepared["counts"])
        process = runtime.run_mace_training_process(command, native_folder,
            resources.model_copy(update={"budget_seconds": remaining}), package_version=MACE_VERSION,
            input_files=inputs, gpu_index=options.gpu_index, gpu_memory_mb=options.gpu_memory_mb,
            cancel_event=cancel_event)
        report.update(execution_kind="real", training_performed=True, process=process.to_dict(), status=process.status)
        for path, expected in inputs.items():
            if Path(path).is_symlink() or file_digest(Path(path)) != expected:
                raise IntegrityError("An immutable fine-tuning input changed during execution")
        if process.status != "completed":
            report["reason"] = "Native GPU training did not complete; no fitted model is certified"
            return report
        native_stdout = Path(process.stdout_path).read_text(errors="replace")
        logs = "\n".join(path.read_text(errors="replace") for path in (native_folder / "logs").glob("*.log") if not path.is_symlink())
        native_evidence = native_stdout + "\n" + logs
        if (f"MACE version: {MACE_VERSION}" not in native_evidence
                or "Using multiheads finetuning mode" not in native_evidence
                or "Error-table on TRAIN and VALID:" not in native_evidence
                or not re.search(r"(?m)\bDone\s*$", native_evidence)):
            raise IntegrityError("Native output does not establish versioned multihead training completion")
        checkpoint = native_folder / "models" / (options.name + ".model")
        if checkpoint.is_symlink() or not checkpoint.is_file() or checkpoint.stat().st_size == 0:
            raise IntegrityError("Completed fine-tuning did not retain its model checkpoint")
        if file_digest(checkpoint) == manifest.members[0].sha256:
            raise IntegrityError("Fine-tuned checkpoint is byte-identical to the unfitted foundation")
        trained_manifest = _trained_manifest(manifest, checkpoint, request, prepared, domain, folder)
        atomic_json(folder / "trained-model.json", trained_manifest.model_dump(mode="json"))
        report["checkpoint"] = trained_manifest.model_dump(mode="json")
        return _evaluate_heldout(prepared, trained_manifest, resources, options, folder, runtime, report,
                                deadline=started + resources.budget_seconds, cancel_event=cancel_event)
    except InterruptedError as exc:
        report.update(status="cancelled", reason=str(exc))
        return report
    except TimeoutError as exc:
        report.update(status="timed-out", reason=str(exc))
        return report
    except (ValueError, OSError, RuntimeError) as exc:
        report.update(status="failed" if report["execution_kind"] == "real" else "unsupported", reason=str(exc))
        return report
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        atomic_json(folder / "training-report.json", report)
        report["artifacts"] = [artifact.model_dump(mode="json") for artifact in artifact_inventory(folder)]
