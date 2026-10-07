"""Remote transport/recovery regressions; no fixture is scientific evidence."""
from __future__ import annotations

import json
from threading import Event

import pytest
from test_remote_dispatch import GitHubFixture, make_evidence

from topos import remote_workflow
from topos.actions.dispatch import ActionDispatchClient, DispatchResult, RemoteExecutionError
from topos.config import SystemConfig
from topos.models import Molecule, RunRecord, RunRequest
from topos.storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest
from topos.workflow import Workflow


@pytest.fixture
def owned_remote(tmp_path, monkeypatch):
    transport = GitHubFixture()
    client = ActionDispatchClient(target_repo="owner/controller", transport=transport)
    monkeypatch.setattr(remote_workflow, "ActionDispatchClient", lambda **kwargs: client)
    request = RunRequest(molecule=Molecule(symbols=["He"], coordinates=[[0, 0, 0]]),
                         calculation_environment="github-actions", purpose="energy")
    workflow = Workflow(tmp_path / "reviews", config=SystemConfig(remote_repository="owner/controller"))
    monkeypatch.setattr(workflow, "_execute", lambda *args, **kwargs: pytest.fail("remote recovery executed locally"))
    return workflow, request, client, transport


def interrupted_submission(workflow, request, client, monkeypatch):
    original = client.wait_for_result

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt("explicit client interruption after durable dispatch commit")

    monkeypatch.setattr(client, "wait_for_result", interrupted)
    with pytest.raises(KeyboardInterrupt):
        workflow.run(request)
    folder, = workflow.output_root.iterdir()
    record = RunStore(folder).load()
    receipt = DispatchResult(**record["metadata"]["remote_dispatch"], inputs=record["request"])
    monkeypatch.setattr(client, "wait_for_result", original)
    return folder, receipt


def test_interrupted_remote_resume_retrieves_same_job_without_dispatch(owned_remote, tmp_path, monkeypatch):
    workflow, request, client, transport = owned_remote
    folder, receipt = interrupted_submission(workflow, request, client, monkeypatch)
    stored = RunStore(folder).load()
    assert stored["metadata"]["request_sha256"] == digest_json(request.model_dump(mode="json"))
    assert stored["metadata"]["input_sha256"] == digest_json(request.molecule.model_dump(mode="json"))
    original = make_evidence(tmp_path / "native-transport-fixture", transport, receipt)
    # Mutable convenience files never authorize recovery. The verified RunStore
    # receipt is authoritative, even if the client receipt file was edited.
    atomic_json(folder / "dispatch-receipt.json", {"dispatch_id": "unowned"})
    transport.calls.clear()
    result = workflow.resume(folder, invocation_budget_seconds=20)
    assert result.status == "failed"  # actual fixture worker status, never fabricated success
    assert result.request == request
    assert result.metadata["remote_completion_confirmed"] is True
    assert result.metadata["remote_dispatch"]["dispatch_id"] == receipt.dispatch_id
    assert result.metadata["remote_dispatch"]["remote_job_id"] == "123"
    assert result.metadata["remote_worker_identity"]["request_sha256"] == digest_json(original.request.model_dump(mode="json"))
    assert result.metadata["remote_worker_identity"]["request_sha256"] != result.metadata["request_sha256"]
    assert not any(path.endswith("/dispatches") for _, path, _ in transport.calls)
    assert json.loads((folder / "remote-request.json").read_text()) == request.model_dump(mode="json")
    assert RunStore(folder).load() == result.model_dump(mode="json")
    continuation = result.metadata["continuations"][-1]
    assert continuation["kind"] == "remote-owned-job-poll-and-retrieve"
    assert continuation["polling_budget_seconds"] == 20
    assert continuation["scientific_budget_seconds"] == request.budget_seconds


def test_queue_budget_import_preserves_distinct_caller_and_worker_identities(owned_remote, tmp_path, monkeypatch):
    workflow, request, client, transport = owned_remote
    request = request.model_copy(update={"include_queue_in_budget": True, "budget_seconds": 120})
    folder, receipt = interrupted_submission(workflow, request, client, monkeypatch)
    original = make_evidence(tmp_path / "queue-transport-fixture", transport, receipt)
    result = workflow.resume(folder)
    assert original.request.budget_seconds == 90
    assert result.request.budget_seconds == 120
    assert result.metadata["request_sha256"] == receipt.request_sha256
    assert result.metadata["remote_worker_identity"]["request_sha256"] == digest_json(original.request.model_dump(mode="json"))
    before = digest_json(RunStore(folder).load())
    transport.calls.clear()
    # A verified failed worker result is immutable final history, not a retry.
    assert workflow.resume(folder).model_dump(mode="json") == result.model_dump(mode="json")
    assert transport.calls == []
    assert digest_json(RunStore(folder).load()) == before


@pytest.mark.parametrize("configuration", [
    {"remote_repository": "another/controller"}, {"remote_ref": "another-ref"},
])
def test_recovery_rejects_changed_controller_configuration_before_network(owned_remote, configuration, monkeypatch):
    workflow, request, client, transport = owned_remote
    folder, _ = interrupted_submission(workflow, request, client, monkeypatch)
    for key, value in configuration.items():
        setattr(workflow.config, key, value)
    transport.calls.clear()
    with pytest.raises(IntegrityError, match="different configured controller or ref"):
        workflow.resume(folder)
    assert transport.calls == []


@pytest.mark.parametrize("key,value", [
    ("request_sha256", "b" * 64), ("commit_sha", None),
    ("dispatch_id", "topos_unowned"), ("workflow_name", "other.yml"),
])
def test_recovery_rejects_inconsistent_saved_ownership_before_network(owned_remote, monkeypatch, key, value):
    workflow, request, client, transport = owned_remote
    folder, _ = interrupted_submission(workflow, request, client, monkeypatch)
    record = RunRecord.model_validate(RunStore(folder).load())
    record.metadata["remote_dispatch"][key] = value
    RunStore(folder).commit(record)
    transport.calls.clear()
    with pytest.raises((IntegrityError, RemoteExecutionError)):
        workflow.resume(folder)
    assert transport.calls == []


def test_remote_missing_identity_never_falls_back_to_local_or_redispatch(owned_remote, monkeypatch):
    workflow, request, client, transport = owned_remote
    folder, _ = interrupted_submission(workflow, request, client, monkeypatch)
    record = RunRecord.model_validate(RunStore(folder).load())
    record.metadata.pop("request_sha256")
    RunStore(folder).commit(record)
    transport.calls.clear()
    with pytest.raises(IntegrityError, match="immutable user request identity"):
        workflow.resume(folder)
    assert transport.calls == []


def test_unavailable_or_precancelled_remote_resume_never_submits(owned_remote, monkeypatch):
    workflow, request, client, transport = owned_remote
    monkeypatch.setattr(client, "dispatch_request", lambda *args, **kwargs: DispatchResult(
        "topos_" + "a" * 32, "topos_compute.yml", "owner/controller", request.model_dump(mode="json"),
        "main", request_sha256=digest_json(request.model_dump(mode="json")), details="credential absent"))
    unavailable = workflow.run(request)
    assert unavailable.status == "unavailable"
    cancelled_event = Event()
    cancelled_event.set()
    cancelled = workflow.run(request, cancel_event=cancelled_event)
    assert cancelled.status == "cancelled"
    transport.calls.clear()
    for record in (unavailable, cancelled):
        before = digest_json(RunStore(record.metadata["run_dir"]).load())
        assert workflow.resume(record.metadata["run_dir"]).model_dump(mode="json") == record.model_dump(mode="json")
        assert digest_json(RunStore(record.metadata["run_dir"]).load()) == before
    assert transport.calls == []


def test_resume_cancellation_only_requests_owned_job_and_can_later_retrieve(owned_remote, tmp_path, monkeypatch):
    workflow, request, client, transport = owned_remote
    folder, receipt = interrupted_submission(workflow, request, client, monkeypatch)
    event = Event()
    event.set()
    transport.calls.clear()
    pending = workflow.resume(folder, cancel_event=event)
    assert pending.status == "running"
    assert pending.metadata["remote_completion_confirmed"] is False
    assert pending.metadata["remote_dispatch"]["status"] == "cancellation-requested"
    assert transport.calls[-1][:2] == ("POST", "/repos/owner/controller/actions/runs/123/cancel")
    assert not any(path.endswith("/dispatches") for _, path, _ in transport.calls)
    make_evidence(tmp_path / "cancel-result-fixture", transport, receipt)
    terminal = workflow.resume(folder)
    assert terminal.status == "failed"
    assert terminal.metadata["remote_completion_confirmed"] is True


def test_resume_after_import_commit_interruption_reauthenticates_same_job(owned_remote, tmp_path, monkeypatch):
    workflow, request, client, transport = owned_remote
    folder, receipt = interrupted_submission(workflow, request, client, monkeypatch)
    make_evidence(tmp_path / "import-result-fixture", transport, receipt)
    original_commit = RunStore.commit

    def interrupted_commit(self, record):
        if isinstance(record, RunRecord) and record.metadata.get("remote_completion_confirmed") is True:
            raise KeyboardInterrupt("interrupted before local result publication")
        return original_commit(self, record)

    monkeypatch.setattr(RunStore, "commit", interrupted_commit)
    with pytest.raises(KeyboardInterrupt):
        workflow.resume(folder)
    assert RunStore(folder).load()["metadata"]["remote_completion_confirmed"] is False
    assert (folder / "remote-evidence").is_dir()
    worker_record_digest = file_digest(folder / "remote-worker-record.json")
    monkeypatch.setattr(RunStore, "commit", original_commit)
    transport.calls.clear()
    result = workflow.resume(folder)
    assert result.metadata["remote_completion_confirmed"] is True
    assert len(list(folder.glob("remote-evidence-recovery-*"))) == 1
    assert file_digest(folder / "remote-worker-record.json") == worker_record_digest
    assert not any(path.endswith("/dispatches") for _, path, _ in transport.calls)


def test_terminal_claim_without_frozen_worker_proof_is_rejected(owned_remote, monkeypatch):
    workflow, request, client, transport = owned_remote
    folder, _ = interrupted_submission(workflow, request, client, monkeypatch)
    record = RunRecord.model_validate(RunStore(folder).load())
    record.metadata["remote_completion_confirmed"] = True
    RunStore(folder).commit(record)
    transport.calls.clear()
    with pytest.raises(IntegrityError):
        workflow.resume(folder)
    assert transport.calls == []


def test_interrupted_import_never_replaces_different_existing_proof(owned_remote, tmp_path, monkeypatch):
    workflow, request, client, transport = owned_remote
    folder, receipt = interrupted_submission(workflow, request, client, monkeypatch)
    make_evidence(tmp_path / "conflict-result-fixture", transport, receipt)
    atomic_json(folder / "remote-worker-record.json", {"source": "different"})
    result = workflow.resume(folder)
    assert result.status == "failed"
    assert result.metadata["remote_completion_confirmed"] is False
    assert "differs" in result.metadata["termination_reason"]
    assert json.loads((folder / "remote-worker-record.json").read_text()) == {"source": "different"}


def test_remote_import_copy_rejects_symlink_parent(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"fixture artifact, not molecular output")
    root = tmp_path / "run"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(IntegrityError, match="symbolic links"):
        remote_workflow._copy_verified_file(source, root / "link" / "artifact", root=root)
    assert not (outside / "artifact").exists()


def test_accepted_dispatch_with_lost_response_keeps_pinned_owned_receipt(owned_remote, tmp_path, monkeypatch):
    workflow, request, client, transport = owned_remote
    original_request = transport.request

    def lost_post_response(method, path, payload=None):
        result = original_request(method, path, payload)
        if path.endswith("/dispatches"):
            raise RemoteExecutionError("transport response timed out")
        return result

    monkeypatch.setattr(transport, "request", lost_post_response)
    folder, receipt = interrupted_submission(workflow, request, client, monkeypatch)
    assert receipt.status == "submission-unconfirmed"
    assert receipt.commit_sha == transport.run["head_sha"]
    assert receipt.dispatch_id == transport.run["display_title"]
    assert "no acceptance or calculation completion is claimed" in receipt.details
    make_evidence(tmp_path / "lost-response-result-fixture", transport, receipt)
    transport.calls.clear()
    recovered = workflow.resume(folder)
    assert recovered.metadata["remote_completion_confirmed"] is True
    assert recovered.metadata["remote_dispatch"]["dispatch_id"] == receipt.dispatch_id
    assert not any(path.endswith("/dispatches") for _, path, _ in transport.calls)


def test_submission_unconfirmed_does_not_claim_job_exists(owned_remote, monkeypatch):
    _, request, client, transport = owned_remote
    original_request = transport.request

    def failed_post(method, path, payload=None):
        if path.endswith("/dispatches"):
            raise RemoteExecutionError("request delivery failed")
        return original_request(method, path, payload)

    monkeypatch.setattr(transport, "request", failed_post)
    receipt = client.dispatch_request(request)
    assert receipt.status == "submission-unconfirmed"
    assert receipt.remote_job_id is None and receipt.record is None
    assert receipt.commit_sha is not None
    polled = client.poll(receipt)
    assert polled.remote_job_id is None
    assert polled.status == "submitted"
    assert polled.record is None
