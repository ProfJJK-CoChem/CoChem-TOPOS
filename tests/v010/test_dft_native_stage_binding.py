"""Artifact/identity contracts only; no artificial output certifies DFT chemistry.

The hosted native-hessian case exercises the complete importer using its actual
optimization and independent final gradient, without another engine calculation.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from topos.engines import EngineResult
from topos.ml_training import (
    _final_gradient_contract,
    _optimization_refinement_contract,
    _optimization_stage_receipt,
    _reference_artifact,
    _validate_final_stationarity,
)
from topos.models import Artifact, Attempt, MethodSpec, Molecule, ResourceLimits
from topos.storage import IntegrityError, atomic_json, digest_json, file_digest


def identity_contract():
    """An unexecuted bookkeeping fixture, never a completed scientific attempt."""
    molecule = Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.96, 0, 0], [-.24, .93, 0]])
    method = MethodSpec(engine="orca", method="r2SCAN-3c", purpose="optimize", engine_version="6.1.1",
                        profile_id="orca-mapping-v4.1")
    resources = ResourceLimits(threads=1, memory_mb=2048, budget_seconds=100)
    attempt = Attempt(run_id="contract-run", attempt_id="contract-attempt", engine="orca", method=method.method,
        status="queued", engine_version="6.1.1", command=["/contract-only/orca", "job.inp"],
        metadata={"fixture_kind": "identity contract only, not executed", "executable_sha256": "a" * 64})
    stage = {"directory": "final-gradient", "execution_kind": "real", "engine": "orca", "engine_version": "6.1.1",
        "executable_sha256": "a" * 64, "method": method.model_dump(mode="json"),
        "input_molecule_sha256": digest_json(molecule.model_dump(mode="json")),
        "command": list(attempt.command), "resources": resources.model_copy(update={"budget_seconds": 50}).model_dump(mode="json"),
        "native_files_sha256": {name: "b" * 64 for name in ("job.inp", "engine.stdout", "job.engrad")}}
    attempt.metadata["final_gradient_verification"] = stage
    return attempt, molecule, method, resources


def test_final_stage_identity_preserves_geometry_hamiltonian_authority_and_allocation():
    attempt, molecule, method, resources = identity_contract()
    assert _final_gradient_contract(attempt, molecule, method, resources) == attempt.metadata["final_gradient_verification"]
    assert attempt.status == "queued" and attempt.converged is None


@pytest.mark.parametrize("damage", ["absent", "directory", "method", "version", "binary", "geometry", "command",
                                  "memory", "device", "budget", "missing-hash", "extra-hash", "invalid-hash"])
def test_final_stage_cannot_mix_identity_or_use_ambiguous_native_evidence(damage):
    attempt, molecule, method, resources = identity_contract()
    stage = attempt.metadata["final_gradient_verification"]
    if damage == "absent":
        del attempt.metadata["final_gradient_verification"]
    elif damage == "directory":
        stage["directory"] = "arbitrary-alternate"
    elif damage == "method":
        stage["method"]["method"] = "HF"
    elif damage == "version":
        stage["engine_version"] = "6.0.1"
    elif damage == "binary":
        stage["executable_sha256"] = "c" * 64
    elif damage == "geometry":
        stage["input_molecule_sha256"] = "c" * 64
    elif damage == "command":
        stage["command"] = ["/different/orca", "job.inp"]
    elif damage in {"memory", "device", "budget"}:
        field, value = {"memory": ("memory_mb", 1024), "device": ("device", "gpu"), "budget": ("budget_seconds", 101)}[damage]
        stage["resources"][field] = value
    elif damage == "missing-hash":
        del stage["native_files_sha256"]["job.engrad"]
    elif damage == "extra-hash":
        stage["native_files_sha256"]["alternate.engrad"] = "b" * 64
    else:
        stage["native_files_sha256"]["job.engrad"] = "invalid hash"
    with pytest.raises(ValueError):
        _final_gradient_contract(attempt, molecule, method, resources)


def stage_files(tmp_path):
    attempt, _, _, _ = identity_contract()
    for stage in ("", "final-gradient"):
        for name in ("job.inp", "engine.stdout", "job.engrad"):
            relative = (Path("attempts") / attempt.attempt_id / stage / name).as_posix()
            path = tmp_path / "artifacts" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"Bookkeeping fixture for {stage or 'optimizer'}/{name}; not ORCA output.\n")
            attempt.artifacts.append(Artifact(path=relative, sha256=file_digest(path), size_bytes=path.stat().st_size))
    return attempt


def test_exact_stage_selection_handles_repeated_native_basenames_without_guessing(tmp_path):
    attempt = stage_files(tmp_path)
    optimizer = _reference_artifact(tmp_path, attempt, "engine.stdout", stage="")
    final = _reference_artifact(tmp_path, attempt, "engine.stdout", stage="final-gradient")
    assert optimizer != final
    assert "optimizer/engine.stdout" in optimizer.read_text()
    assert "final-gradient/engine.stdout" in final.read_text()
    # Existing gradient-only imports still reject ambiguous basename membership.
    with pytest.raises(IntegrityError, match="exactly one"):
        _reference_artifact(tmp_path, attempt, "engine.stdout")


@pytest.mark.parametrize("damage", ["duplicate", "missing-stage", "changed-bytes", "symlink"])
def test_final_stage_artifacts_reject_duplicates_substitution_and_tampering(tmp_path, damage):
    attempt = stage_files(tmp_path)
    final = next(a for a in attempt.artifacts if a.path.endswith("final-gradient/job.engrad"))
    path = tmp_path / "artifacts" / final.path
    if damage == "duplicate":
        attempt.artifacts.append(copy.deepcopy(final))
    elif damage == "missing-stage":
        attempt.artifacts.remove(final)  # Optimizer's same basename may not substitute.
    elif damage == "changed-bytes":
        path.write_text("Changed stage evidence")
    else:
        path.unlink()
        path.symlink_to(tmp_path / "artifacts" / "attempts" / attempt.attempt_id / "job.engrad")
    with pytest.raises(IntegrityError):
        _reference_artifact(tmp_path, attempt, "job.engrad", stage="final-gradient")


def test_hosted_dft_import_helper_requires_actual_success_without_writing_evidence(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/orca_dft_import_acceptance.py"
    spec = importlib.util.spec_from_file_location("orca_dft_import_acceptance_guard", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _, molecule, _, _ = identity_contract()
    missing = EngineResult(status="unavailable", engine="orca", method="r2SCAN-3c", operation="optimize")
    with pytest.raises(ValueError, match="actual completed"):
        module.verify_optimized_dft_import(missing, molecule, tmp_path / "no-result")
    assert not (tmp_path / "no-result").exists()


def test_gradient_stationarity_is_recomputed_at_the_exact_profile_thresholds():
    _, _, method, _ = identity_contract()
    # Analytical Cartesian vectors only; these are not native engine results.
    diagnostics = {"passed": True, "max_gradient_threshold": 1e-5, "rms_gradient_threshold": 3e-6,
                   "max_gradient_hartree_per_bohr": 2e-6, "rms_gradient_hartree_per_bohr": 2e-6}
    _validate_final_stationarity([[2e-6, 2e-6, 2e-6]], method, diagnostics)
    for gradient in ([[1e-4, 1e-4, 1e-4]], [[float("nan"), 0., 0.]], [[0., 0.]], []):
        with pytest.raises(IntegrityError):
            _validate_final_stationarity(gradient, method, diagnostics)
    with pytest.raises(IntegrityError, match="stationarity"):
        _validate_final_stationarity([[2e-6, 2e-6, 2e-6]], method, {**diagnostics, "passed": False})
    with pytest.raises(IntegrityError, match="stationarity"):
        _validate_final_stationarity([[2e-6, 2e-6, 2e-6]], method,
                                     {**diagnostics, "max_gradient_hartree_per_bohr": 0.})
    with pytest.raises(IntegrityError, match="stationarity"):
        _validate_final_stationarity([[2e-6, 2e-6, 2e-6]],
                                     method.model_copy(update={"profile_id": "orca-vpt2-reference-v1"}), diagnostics)


def refinement_contract():
    """Unexecuted history identity fixture; never supplied as native evidence."""
    attempt, initial, method, resources = identity_contract()
    middle = initial.model_copy(update={"coordinates": [[0., 0., 0.], [.97, 0., 0.], [-.24, .94, 0.]]})
    output = initial.model_copy(update={"coordinates": [[0., 0., 0.], [.98, 0., 0.], [-.24, .95, 0.]]})
    final_resources = resources.model_copy(update={"budget_seconds": 60.})
    stages = []
    for index, (start, end, allocation) in enumerate(((initial, middle, resources), (middle, output, final_resources))):
        stages.append({"stage_directory": "." if index == 0 else "optimization-refinement-1",
            "input_molecule": start.model_dump(mode="json"), "output_molecule": end.model_dump(mode="json"),
            "method": method.model_dump(mode="json"), "resources": allocation.model_dump(mode="json"),
            "engine_version": attempt.engine_version, "executable_sha256": attempt.metadata["executable_sha256"],
            "command": list(attempt.command), "process": {"status": "completed", "returncode": 0},
            "status": "completed" if index else "partial", "converged": bool(index),
            "native_optimizer_reported_converged": True})
    attempt.metadata["optimization_refinement"] = {
        "schema": "topos-orca-optimization-refinement/1", "maximum_restarts": 3,
        "initial_molecule": initial.model_dump(mode="json"), "original_resources": resources.model_dump(mode="json"),
        "stages": stages, "accepted_stage_directory": "optimization-refinement-1",
        "final_stage_directory": "optimization-refinement-1"}
    final = attempt.metadata["final_gradient_verification"]
    final["directory"] = "optimization-refinement-1/final-gradient"
    final["input_molecule_sha256"] = digest_json(output.model_dump(mode="json"))
    stages[-1]["final_gradient_verification"] = copy.deepcopy(final)
    attempt.diagnostics.update({"process": stages[-1]["process"], "native_optimizer_reported_converged": True})
    return attempt, initial, output, method, final_resources


def test_explicit_refinement_contract_binds_original_chain_and_exact_accepted_stage():
    attempt, initial, output, method, resources = refinement_contract()
    stages = _optimization_refinement_contract(attempt, initial, output, method, resources)
    assert len(stages) == 2 and stages[-1]["input_molecule"] == stages[0]["output_molecule"]
    assert _final_gradient_contract(attempt, output, method, resources,
        optimization_stage=stages[-1]["stage_directory"])["directory"] == "optimization-refinement-1/final-gradient"
    assert attempt.status == "queued"  # The identity fixture never becomes a scientific result.


@pytest.mark.parametrize("damage", ["schema", "limit", "omitted-stage", "duplicate-stage", "reorder",
    "original-geometry", "broken-chain", "method", "version", "binary", "command", "failed-process",
    "returncode", "failed-stage", "already-accepted", "memory", "reset-deadline", "isotope", "accepted-stage",
    "wrong-final-geometry", "final-resources", "final-stage", "native-endpoint", "final-gradient", "final-diagnostics"])
def test_refinement_history_cannot_hide_changed_protocol_failed_stages_or_budget_reset(damage):
    attempt, initial, output, method, resources = refinement_contract()
    history = attempt.metadata["optimization_refinement"]
    stages = history["stages"]
    if damage == "schema":
        history["schema"] = "unrecognized"
    elif damage == "limit":
        history["maximum_restarts"] = 30
    elif damage == "omitted-stage":
        history["stages"] = stages[1:]
    elif damage == "duplicate-stage":
        stages.append(copy.deepcopy(stages[1]))
    elif damage == "reorder":
        stages.reverse()
    elif damage == "original-geometry":
        history["initial_molecule"] = output.model_dump(mode="json")
    elif damage == "broken-chain":
        stages[1]["input_molecule"] = initial.model_dump(mode="json")
    elif damage == "method":
        stages[1]["method"]["method"] = "HF-3c"
    elif damage == "version":
        stages[1]["engine_version"] = "6.0.1"
    elif damage == "binary":
        stages[1]["executable_sha256"] = "c" * 64
    elif damage == "command":
        stages[1]["command"][0] = "/different/orca"
    elif damage == "failed-process":
        stages[0]["process"]["status"] = "timed-out"
    elif damage == "returncode":
        stages[0]["process"]["returncode"] = 1
    elif damage == "failed-stage":
        stages[0]["status"] = "failed"
    elif damage == "already-accepted":
        stages[0]["converged"] = True
    elif damage == "memory":
        stages[1]["resources"]["memory_mb"] = 1024
    elif damage == "reset-deadline":
        stages[1]["resources"]["budget_seconds"] = 101.
    elif damage == "isotope":
        stages[1]["output_molecule"]["isotopes"] = [18, 1, 1]
    elif damage == "accepted-stage":
        history["accepted_stage_directory"] = "."
    elif damage == "wrong-final-geometry":
        output = initial
    elif damage == "final-stage":
        history["final_stage_directory"] = "."
    elif damage == "native-endpoint":
        stages[0]["native_optimizer_reported_converged"] = False
    elif damage == "final-gradient":
        stages[-1]["final_gradient_verification"]["energy_hartree"] = -100.
    elif damage == "final-diagnostics":
        attempt.diagnostics["convergence"] = {"max_gradient": True}
    else:
        resources = resources.model_copy(update={"budget_seconds": 61.})
    with pytest.raises(ValueError):
        _optimization_refinement_contract(attempt, initial, output, method, resources)


def test_nested_native_files_preserve_stage_names_and_cannot_replace_root_or_final(tmp_path):
    attempt = stage_files(tmp_path)
    for stage in ("optimization-refinement-1", "optimization-refinement-1/final-gradient"):
        relative = (Path("attempts") / attempt.attempt_id / stage / "job.inp").as_posix()
        path = tmp_path / "artifacts" / relative
        path.parent.mkdir(parents=True)
        path.write_text(f"Unexecuted file-identity fixture: {stage}\n")
        attempt.artifacts.append(Artifact(path=relative, sha256=file_digest(path), size_bytes=path.stat().st_size))
        assert _reference_artifact(tmp_path, attempt, "job.inp", stage=stage) == path
    for stage in ("../optimization-refinement-1", "optimization-refinement-0", "optimization-refinement-4",
                  "optimization-refinement-1/../final-gradient", "/optimization-refinement-1"):
        with pytest.raises(ValueError):
            _reference_artifact(tmp_path, attempt, "job.inp", stage=stage)


def retained_partial_receipt(tmp_path):
    """Retain an actual rejected hosted result; never assert a scientific pass."""
    fixtures = Path(__file__).parent / "fixtures/orca_fifth_hosted"
    native = EngineResult.model_validate(json.loads((fixtures / "incomplete-r2scan-result.json").read_text()))
    native.diagnostics["native_optimizer_reported_converged"] = (
        "THE OPTIMIZATION HAS CONVERGED" in (fixtures / "incomplete-r2scan-optimization.stdout").read_text())
    attempt = Attempt(run_id="receipt-review", attempt_id="rejected-native-stage", engine=native.engine,
                      engine_version=native.engine_version, method=native.method, status="partial")
    path = tmp_path / "artifacts/attempts" / attempt.attempt_id / "optimization-stage-0.json"
    atomic_json(path, native.model_dump(mode="json"))
    attempt.artifacts.append(Artifact(path=path.relative_to(tmp_path / "artifacts").as_posix(),
        sha256=file_digest(path), size_bytes=path.stat().st_size))
    stage = {"stage_directory": ".", "output_molecule": native.molecule.model_dump(mode="json"),
        "engine_version": native.engine_version, "method": native.metadata["requested_method"],
        "resources": native.metadata["resources"], "executable_sha256": native.metadata["executable_sha256"],
        "command": native.command, "status": native.status, "converged": native.converged,
        **{key: native.diagnostics.get(key) for key in (
            "process", "convergence", "native_optimizer_reported_converged", "independent_stationarity")},
        "final_gradient_verification": native.metadata.get("final_gradient_verification"),
        "receipt": {"path": path.name, "sha256": file_digest(path), "size_bytes": path.stat().st_size}}
    return attempt, stage, path


def test_genuine_partial_stage_receipt_remains_bound_and_partial(tmp_path):
    attempt, stage, original = retained_partial_receipt(tmp_path)
    path, native = _optimization_stage_receipt(tmp_path, attempt, 0, stage)
    assert path == original and native.status == "partial" and native.converged is False


@pytest.mark.parametrize("damage", ["changed-bytes", "renamed", "missing-artifact", "duplicate", "receipt-hash",
                                  "process", "geometry", "convergence", "energy-change", "method", "gradient", "elapsed-budget"])
def test_stage_receipt_cannot_disagree_with_history_or_immutable_inventory(tmp_path, damage):
    attempt, stage, path = retained_partial_receipt(tmp_path)
    if damage == "changed-bytes":
        path.write_text("{}")
    elif damage == "renamed":
        stage["receipt"]["path"] = "optimization-stage-1.json"
    elif damage == "missing-artifact":
        attempt.artifacts.clear()
    elif damage == "duplicate":
        attempt.artifacts.append(attempt.artifacts[0].model_copy())
    elif damage == "receipt-hash":
        stage["receipt"]["sha256"] = "a" * 64
    elif damage == "process":
        stage["process"] = {"status": "completed", "returncode": 0}
    elif damage == "geometry":
        stage["output_molecule"]["coordinates"][0][0] += .1
    elif damage == "convergence":
        stage["convergence"] = {"rms_gradient": True}
    elif damage == "energy-change":
        stage["energy_change_evidence"] = {"source": "unbound invented energy difference", "passed": True}
    elif damage == "method":
        stage["method"]["method"] = "B3LYP"
    elif damage == "elapsed-budget":
        raw = json.loads(path.read_text())
        raw["elapsed_seconds"] = stage["resources"]["budget_seconds"] + 1
        atomic_json(path, raw)
        stage["receipt"].update(sha256=file_digest(path), size_bytes=path.stat().st_size)
        attempt.artifacts[0] = attempt.artifacts[0].model_copy(update={
            "sha256": file_digest(path), "size_bytes": path.stat().st_size})
    else:
        stage["final_gradient_verification"] = {"directory": "final-gradient"}
    with pytest.raises(IntegrityError):
        _optimization_stage_receipt(tmp_path, attempt, 0, stage)
