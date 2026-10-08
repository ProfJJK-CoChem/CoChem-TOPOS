"""Campaign persistence contracts; these tests do not simulate native chemistry."""
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from topos.matrix_ml_training import (
    _durable_stage,
    _verified_cached,
    _verified_checkpoint,
    execute_ml_training,
)
from topos.models import Artifact, Attempt, Molecule, RunRecord, RunRequest
from topos.storage import IntegrityError, RunStore, digest_json, file_digest


def context(tmp_path):
    molecule = Molecule(symbols=["O", "H", "H"],
                        coordinates=[[0, 0, 0], [.96, 0, 0], [-.24, .93, 0]])
    record = RunRecord(request=RunRequest(molecule=molecule))
    store = RunStore(tmp_path / record.run_id)
    store.commit(record)
    return record, store


def cache_fixture(tmp_path):
    # A record-format fixture, never submitted to an engine or accepted as a calculation.
    record, store = context(tmp_path)
    path = store.run_dir / "fixture-evidence.txt"
    path.write_text("Storage fixture, not a native calculation")
    payload = {"status": "completed", "fixture_only": True}
    attempt = Attempt(run_id=record.run_id, engine="fixture", method="fixture",
        status="completed", converged=True, validation_status="validated-for-protocol",
        metadata={"compound_stage_sha256": "identity", "role": "role", "execution_kind": "real",
                  "stage_result": payload, "stage_result_sha256": digest_json(payload)},
        artifacts=[Artifact(path=path.name, sha256=file_digest(path), size_bytes=path.stat().st_size)])
    record.attempts.append(attempt)
    return record, store, attempt, path


def test_campaign_cache_checks_identity_and_digest(tmp_path):
    record, store, attempt, _ = cache_fixture(tmp_path)
    assert _verified_cached(record, store, "another", "role") is None
    assert _verified_cached(record, store, "identity", "another") is None
    assert _verified_cached(record, store, "identity", "role")["fixture_only"]
    attempt.metadata["stage_result"]["fixture_only"] = False
    with pytest.raises(IntegrityError, match="result changed"):
        _verified_cached(record, store, "identity", "role")


@pytest.mark.parametrize("mutation", ["bytes", "missing", "symlink", "parent-symlink", "no-artifacts", "not-real"])
def test_campaign_cache_rejects_missing_or_changed_evidence(tmp_path, mutation):
    record, store, attempt, path = cache_fixture(tmp_path)
    if mutation == "bytes":
        path.write_text("changed")
    elif mutation == "missing":
        path.unlink()
    elif mutation == "symlink":
        target = tmp_path / "external"
        path.rename(target)
        path.symlink_to(target)
    elif mutation == "parent-symlink":
        target = store.run_dir / "real-folder"
        target.mkdir()
        path.rename(target / path.name)
        (store.run_dir / "alias").symlink_to(target, target_is_directory=True)
        attempt.artifacts[0].path = "alias/" + path.name
    elif mutation == "no-artifacts":
        attempt.artifacts.clear()
    else:
        attempt.metadata["execution_kind"] = "not-executed"
    with pytest.raises(IntegrityError):
        _verified_cached(record, store, "identity", "role")


def test_unexpected_failure_is_committed_with_retained_raw_bytes(tmp_path):
    record, store = context(tmp_path)
    attempt = Attempt(run_id=record.run_id, engine="fixture", method="fixture", status="running")
    record.attempts.append(attempt)
    folder = store.run_dir / "attempts" / attempt.attempt_id
    folder.mkdir(parents=True)
    (folder / "partial.stdout").write_text("partial process output")
    with pytest.raises(RuntimeError, match="interrupted parser"):
        with _durable_stage(record, store, attempt, folder):
            raise RuntimeError("interrupted parser")
    recovered = RunRecord.model_validate(store.recover())
    assert recovered.status == "failed"
    failed = recovered.attempts[-1]
    assert failed.status == "failed" and failed.finished_at and failed.converged is False
    assert failed.validation_status == "rejected"
    assert len(failed.artifacts) == 1
    assert Path(failed.artifacts[0].path).name == "partial.stdout"
    assert store.verify()


def test_missing_training_inputs_cannot_start_or_publish_a_campaign(tmp_path):
    record, store = context(tmp_path)
    with pytest.raises(ValueError, match="authentic DFT dataset"):
        execute_ml_training(None, record, store, SimpleNamespace(
            ml_model=None, ml_training_dataset=None, ml_training_options=None),
            None, 0, None)
    assert not record.attempts and not record.candidates


def test_retained_checkpoint_does_not_pretend_heldout_completion(tmp_path):
    record, store, attempt, path = cache_fixture(tmp_path)
    attempt.status = "partial"
    attempt.converged = False
    attempt.validation_status = "not-evaluated"
    attempt.metadata["role"] = "experimental-fine-tuning"
    payload = {"status": "partial", "checkpoint": {"fixture_only": True},
               "process": {"status": "completed"}, "heldout_errors": None}
    attempt.metadata.update(stage_result=payload, stage_result_sha256=digest_json(payload))
    assert _verified_cached(record, store, "identity", "experimental-fine-tuning") is None
    assert _verified_checkpoint(record, store, "identity") == payload
    # The low-level training recovery independently requires real model/native evidence.
    # This storage fixture validates only eligibility and tamper rejection.
    path.write_text("changed evidence")
    with pytest.raises(IntegrityError, match="checkpoint evidence"):
        _verified_checkpoint(record, store, "identity")


@pytest.mark.parametrize("stop", ["cancel-before", "deadline-before", "cancel-during-verification"])
def test_compound_stop_never_restores_cached_success_or_launches_training(tmp_path, monkeypatch, stop):
    """Control-flow fixture only; no native process or successful science result exists."""
    import time

    from topos import matrix_ml_training, ml_crest

    record, _ = context(tmp_path)
    record = RunRecord(request=record.request.model_copy(update={"device": "gpu", "threads": 2}))
    store = RunStore(tmp_path / record.run_id)
    store.commit(record)
    event = Event()
    if stop == "cancel-before":
        event.set()
    empty_spec = SimpleNamespace(model_dump=lambda **kwargs: {})
    options = SimpleNamespace(gpu_index=0, gpu_memory_mb=512, model_dump=lambda **kwargs: {})
    inputs = SimpleNamespace(ml_model=empty_spec, ml_training_dataset=empty_spec, ml_training_options=options,
        ml_search_allocation=SimpleNamespace(model_dump=lambda: dict(ml_threads=1, orca_threads=1,
                                                                    ml_memory_mb=256, orca_memory_mb=256)),
        ml_gpu_index=0, ml_gpu_memory_mb=512, ml_search_seeds=[])
    # Only the unrelated installation preflight is replaced. No executor or native
    # output is simulated; the test must stop before cached-result acceptance.
    monkeypatch.setattr(ml_crest, "validate_crest_ml_distribution", lambda path: None)
    workflow = SimpleNamespace(base_runtime=SimpleNamespace(resolve_executable=lambda engine: "/not-executed/"+engine))
    visited = []

    def cache_boundary(*args):
        assert stop == "cancel-during-verification"
        visited.append(True)
        event.set()
        return None

    monkeypatch.setattr(matrix_ml_training, "_verified_cached", cache_boundary)
    monkeypatch.setattr(matrix_ml_training, "_verified_checkpoint", lambda *args: pytest.fail("Stopped invocation cannot restore a checkpoint"))
    monkeypatch.setattr(matrix_ml_training, "run_mace_finetuning", lambda *args, **kwargs: pytest.fail("Stopped invocation cannot train"))
    assert execute_ml_training(workflow, record, store, inputs, None,
        0 if stop == "deadline-before" else time.monotonic()+30, event) is False
    assert record.status == ("timed-out" if stop == "deadline-before" else "cancelled")
    assert bool(visited) == (stop == "cancel-during-verification")
    assert not record.attempts and "experimental_trained_model" not in record.metadata
    assert RunRecord.model_validate(store.recover()).status == record.status
