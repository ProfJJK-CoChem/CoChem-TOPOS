"""Durable ML publication tests using actual explicitly supplied checkpoints.

The local bounded runtime is development execution, not BASE attestation.
Mutated copies of genuine results are rejection tests, never new predictions.
"""
from __future__ import annotations

import copy
import os
import shutil
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from topos import ml_workflow
from topos.ml import ModelManifest
from topos.ml_workflow import RigidMLGrid, execute_ml_matrix
from topos.models import Molecule, RunRecord, RunRequest
from topos.runtime import run_process
from topos.storage import IntegrityError, RunStore, atomic_json, file_digest, read_json


class GenuineDevelopmentRuntime:
    def __init__(self, python):
        self.python, self.calls = python, 0

    def resolve_executable(self, engine):
        return self.python

    def run_ml_process(self, command, workdir, resources, *, engine, request_sha256, worker_sha256,
                       model_files, gpu_index=None, gpu_memory_mb=None, **kwargs):
        from topos import ml_worker

        assert gpu_index is gpu_memory_mb is None and engine in {"mace", "aimnet2"}
        assert file_digest(Path(command[-1])) == request_sha256
        assert file_digest(Path(ml_worker.__file__)) == worker_sha256
        assert all(file_digest(Path(path)) == expected for path, expected in model_files.items())
        self.calls += 1
        return run_process(command, workdir, resources, **kwargs)


def real_request(backend):
    variable = "TOPOS_AIMNET_TEST_REQUEST" if backend == "aimnet2" else "TOPOS_ML_TEST_REQUEST"
    path, python = os.environ.get(variable), os.environ.get("TOPOS_ML_TEST_PYTHON")
    if not path or not python:
        pytest.skip("Explicit actual ML interpreter/checkpoint request required")
    request = read_json(Path(path))
    manifest = ModelManifest.model_validate(request["manifest"])
    assert manifest.backend == backend
    reference = Molecule.model_validate(request["molecules"][0])
    coordinates = reference.coordinates + [[row[0] + 5, row[1], row[2]] for row in reference.coordinates]
    count = len(reference.symbols)
    fragments = [list(range(count)), list(range(count, 2 * count))]
    dimer = Molecule(symbols=reference.symbols * 2, coordinates=coordinates, fragments=fragments,
                    fragment_states=[{"atom_indices": group, "charge": 0, "multiplicity": 1} for group in fragments])
    return manifest, dimer, GenuineDevelopmentRuntime(python)


def context(folder, backend="aimnet2"):
    manifest, molecule, runtime = real_request(backend)
    row = "T5-1min" if backend == "aimnet2" else "T2-1min"
    record = RunRecord(request=RunRequest(molecule=molecule, engine=backend, method=manifest.family,
        matrix_row_id=row, threads=1, memory_mb=8192, budget_seconds=180))
    store = RunStore(folder / record.run_id)
    store.commit(record)
    grid = None if backend == "aimnet2" else RigidMLGrid(moving_fragment=1,
        translation_x_angstrom=[i * .005 for i in range(10)],
        translation_y_angstrom=[i * .005 for i in range(10)],
        translation_z_angstrom=[i * .005 for i in range(10)],
        isolated_fragment_geometry_sources=["explicit supplied first frozen monomer geometry",
                                             "explicit supplied second frozen monomer geometry"])
    inputs = SimpleNamespace(ml_model=manifest, ml_grid=grid, ml_gpu_index=None, ml_gpu_memory_mb=None)
    return SimpleNamespace(base_runtime=runtime), record, store, inputs


@pytest.fixture(scope="module")
def actual_campaign(tmp_path_factory):
    workflow, record, store, inputs = context(tmp_path_factory.mktemp("genuine-ml-campaign"))
    assert execute_ml_matrix(workflow, record, store, time.monotonic() + 180, None, inputs)
    assert record.status == "completed", record.attempts[-1].diagnostics
    assert workflow.base_runtime.calls == 1
    assert store.verify()
    return workflow, record, store, inputs


def test_actual_committee_campaign_resumes_only_after_complete_evidence(actual_campaign):
    workflow, record, store, inputs = actual_campaign
    original = copy.deepcopy(record.model_dump(mode="json"))
    recovered = RunRecord.model_validate(store.recover())
    assert execute_ml_matrix(workflow, recovered, store, time.monotonic() + 180, None, inputs)
    assert workflow.base_runtime.calls == 1, "verified resume must not rerun inference"
    assert recovered.status == "completed" and len(recovered.attempts) == 1
    assert recovered.attempts[0].quantities[0].value == original["attempts"][0]["quantities"][0]["value"]


@pytest.mark.parametrize("cancelled", [True, False])
def test_completed_actual_ml_cache_cannot_override_cancellation_or_deadline(tmp_path, actual_campaign, cancelled):
    workflow, original, original_store, inputs = actual_campaign
    folder = tmp_path / original.run_id
    shutil.copytree(original_store.run_dir, folder)
    store = RunStore(folder)
    record = RunRecord.model_validate(store.recover())
    calls = workflow.base_runtime.calls
    event = Event()
    if cancelled:
        event.set()
    assert execute_ml_matrix(workflow, record, store, 0 if not cancelled else time.monotonic()+180, event, inputs)
    assert record.status == ("cancelled" if cancelled else "timed-out")
    assert workflow.base_runtime.calls == calls
    assert len(record.attempts) == 1 and record.attempts[0].status == "completed"
    assert RunRecord.model_validate(store.recover()).status == record.status


@pytest.mark.parametrize("damage", ["empty-artifacts", "not-converged", "not-validated", "not-real",
    "missing-receipt", "missing-native", "artifact-size", "escape", "parent-symlink", "receipt-hash",
    "published-quantity", "forged-derived", "forged-frame", "incomplete-frames", "culling-claim", "gradient-shape"])
def test_completed_cache_cannot_accept_damaged_genuine_campaign(tmp_path, actual_campaign, damage):
    workflow, original, original_store, inputs = actual_campaign
    copied = tmp_path / original.run_id
    shutil.copytree(original_store.run_dir, copied)
    store = RunStore(copied)
    record = RunRecord.model_validate(store.recover())
    attempt = record.attempts[-1]
    folder = store.run_dir / "attempts" / attempt.attempt_id
    receipt = folder / "ml-campaign.json"
    if damage == "empty-artifacts":
        attempt.artifacts = []
    elif damage == "not-converged":
        attempt.converged = False
    elif damage == "not-validated":
        attempt.validation_status = "not-evaluated"
    elif damage == "not-real":
        attempt.metadata["execution_kind"] = "not-executed"
    elif damage == "culling-claim":
        attempt.metadata["energy_culling_authorized"] = True
    elif damage == "missing-receipt":
        receipt.unlink()
    elif damage == "missing-native":
        (folder / "ml-result.json").unlink()
    elif damage == "artifact-size":
        attempt.artifacts[0].size_bytes += 1
    elif damage == "escape":
        attempt.artifacts[0].path = "../outside"
    elif damage == "parent-symlink":
        destination = tmp_path / "moved-real-attempt"
        folder.rename(destination)
        folder.symlink_to(destination, target_is_directory=True)
    elif damage == "receipt-hash":
        attempt.metadata["derived_result_sha256"] = "0" * 64
    elif damage == "published-quantity":
        attempt.quantities[0].value += 1
    else:
        payload = read_json(receipt)
        if damage == "forged-derived":
            payload["derived"]["electronic_interaction_hartree"] += 1
            attempt.metadata["derived"] = payload["derived"]
            attempt.quantities[0].value = payload["derived"]["electronic_interaction_hartree"]
        elif damage == "forged-frame":
            payload["frame_results"][0]["energy_hartree"] += 1
        elif damage == "gradient-shape":
            payload["frame_results"][0]["gradient_hartree_per_bohr"] = payload["frame_results"][0]["gradient_hartree_per_bohr"][:1]
        else:
            payload["frame_results"].pop()
        atomic_json(receipt, payload)
        # Even internally consistent new hashes cannot turn altered chemistry
        # into an accepted result; the original native member data is retained.
        attempt.metadata["derived_result_sha256"] = file_digest(receipt)
        entry = next(a for a in attempt.artifacts if Path(a.path).name == receipt.name)
        entry.sha256, entry.size_bytes = file_digest(receipt), receipt.stat().st_size
    calls = workflow.base_runtime.calls
    with pytest.raises(IntegrityError):
        execute_ml_matrix(workflow, record, store, time.monotonic() + 180, None, inputs)
    assert workflow.base_runtime.calls == calls


@pytest.mark.parametrize("failure", ["derived", "receipt", "final-commit"])
def test_failure_after_actual_inference_never_persists_completed_attempt(tmp_path, monkeypatch, failure):
    workflow, record, store, inputs = context(tmp_path)
    if failure == "derived":
        def fail_derivation(*args, **kwargs):
            assert record.attempts[-1].status == "running"
            raise OSError("injected derived publication failure")

        monkeypatch.setattr(ml_workflow, "_derived_campaign", fail_derivation)
    elif failure == "receipt":
        def fail_receipt(path, payload):
            assert path.name == "ml-campaign.json" and record.attempts[-1].status == "running"
            raise OSError("injected receipt publication failure")

        monkeypatch.setattr(ml_workflow, "atomic_json", fail_receipt)
    else:
        original_commit = store.commit

        def fail_one_completion(value):
            if value.attempts and value.attempts[-1].status == "completed":
                raise OSError("injected final commit failure")
            return original_commit(value)

        monkeypatch.setattr(store, "commit", fail_one_completion)
    assert execute_ml_matrix(workflow, record, store, time.monotonic() + 180, None, inputs)
    assert workflow.base_runtime.calls == 1
    persisted = RunRecord.model_validate(store.recover())
    attempt = persisted.attempts[-1]
    assert persisted.status == attempt.status == "failed"
    assert attempt.converged is False and attempt.validation_status == "rejected"
    assert not attempt.quantities and "ml_campaign" not in persisted.metadata
    assert "injected" in attempt.diagnostics["reason"]
    assert {Path(a.path).name for a in attempt.artifacts} >= {"ml-request.json", "ml-result.json"}
    assert store.verify()


def test_hdf5_failure_after_1000_actual_mace_points_is_not_completed(tmp_path, monkeypatch):
    workflow, record, store, inputs = context(tmp_path, backend="mace")
    original_file = ml_workflow.h5py.File

    def fail_surface_only(path, *args, **kwargs):
        if Path(path).name == "ml-surface.h5":
            assert record.attempts[-1].status == "running"
            raise OSError("injected HDF5 publication failure")
        return original_file(path, *args, **kwargs)

    monkeypatch.setattr(ml_workflow.h5py, "File", fail_surface_only)
    assert execute_ml_matrix(workflow, record, store, time.monotonic() + 180, None, inputs)
    persisted = RunRecord.model_validate(store.recover())
    attempt = persisted.attempts[-1]
    assert workflow.base_runtime.calls == 1 and persisted.status == attempt.status == "failed"
    assert "injected HDF5" in attempt.diagnostics["reason"]
    output = read_json(store.run_dir / "attempts" / attempt.attempt_id / "ml-result.json")
    assert len(output["frames"]) == 1000, "the crash point follows authentic complete native inference"
    assert not attempt.quantities and "ml_campaign" not in persisted.metadata
    assert attempt.converged is False and store.verify()


def test_commit_acknowledgement_loss_recovers_the_verified_publication(tmp_path, monkeypatch):
    workflow, record, store, inputs = context(tmp_path)
    original_commit = store.commit

    def lose_acknowledgement(value):
        result = original_commit(value)
        if value.attempts and value.attempts[-1].status == "completed":
            raise OSError("injected failure after complete commit pointer publication")
        return result

    monkeypatch.setattr(store, "commit", lose_acknowledgement)
    assert execute_ml_matrix(workflow, record, store, time.monotonic() + 180, None, inputs)
    persisted = RunRecord.model_validate(store.recover())
    assert persisted.status == record.status == "completed"
    assert persisted.attempts == record.attempts and workflow.base_runtime.calls == 1
    assert persisted.attempts[-1].validation_status == "validated-for-protocol" and store.verify()


def test_actual_surface_publication_and_semantic_hdf5_resume_validation(tmp_path):
    workflow, record, store, inputs = context(tmp_path, backend="mace")
    assert execute_ml_matrix(workflow, record, store, time.monotonic() + 180, None, inputs)
    assert record.status == "completed", record.attempts[-1].diagnostics
    assert execute_ml_matrix(workflow, record, store, time.monotonic() + 180, None, inputs)
    assert workflow.base_runtime.calls == 1
    attempt = record.attempts[-1]
    shard = store.run_dir / "attempts" / attempt.attempt_id / "ml-surface.h5"
    with ml_workflow.h5py.File(shard, "r+") as handle:
        assert handle["energies"].shape == (1000,)
        handle["energies"][0] += 1
    entry = next(a for a in attempt.artifacts if Path(a.path).name == shard.name)
    entry.sha256, entry.size_bytes = file_digest(shard), shard.stat().st_size
    with pytest.raises(IntegrityError, match="surface shard"):
        execute_ml_matrix(workflow, record, store, time.monotonic() + 180, None, inputs)
    assert workflow.base_runtime.calls == 1
