"""Artifact/identity contracts only; no artificial output certifies DFT chemistry.

The hosted native-hessian case exercises the complete importer using its actual
optimization and independent final gradient, without another engine calculation.
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

from topos.engines import EngineResult
from topos.ml_training import (
    _final_gradient_contract,
    _reference_artifact,
    _validate_final_stationarity,
)
from topos.models import Artifact, Attempt, MethodSpec, Molecule, ResourceLimits
from topos.storage import IntegrityError, digest_json, file_digest


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
