"""GitHub transport/receipt fixtures: none of these fixtures are chemistry evidence."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import stat
import zipfile
from dataclasses import replace
from email.message import Message
from pathlib import Path
from threading import Event

import pytest

from topos.actions.dispatch import (
    ActionDispatchClient,
    RemoteExecutionError,
    _canonical,
    _extract_archive,
    _GitHubTransport,
)
from topos.models import Molecule, RunRecord, RunRequest
from topos.storage import RunStore, atomic_json

SHA = "a" * 40


class GitHubFixture:
    """Explicit API fixture, never an executable scientific engine."""

    def __init__(self):
        self.calls = []
        self.run = None
        self.artifacts = []
        self.content = b""
        self.private = True
        self.extra_runs = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path == "/repos/owner/controller":
            return {"private": self.private, "default_branch": "main"}
        if "/commits/" in path:
            return {"sha": SHA}
        if path.endswith("/dispatches"):
            self.run = {"id": 123, "head_sha": SHA, "display_title": payload["inputs"]["dispatch_id"],
                        "event": "workflow_dispatch", "status": "in_progress", "conclusion": None,
                        "path": ".github/workflows/topos_compute.yml", "created_at": "2026-10-07T12:00:00Z"}
            return {}
        if "/runs?" in path:
            return {"workflow_runs": ([self.run] if self.run else []) + self.extra_runs}
        if path.endswith("/cancel"):
            return {}
        if "/artifacts?" in path:
            return {"artifacts": self.artifacts}
        if path.endswith("/runs/123"):
            return self.run
        raise AssertionError((method, path))

    def download(self, path):
        self.calls.append(("DOWNLOAD", path, None))
        return self.content


@pytest.fixture
def submitted():
    transport = GitHubFixture()
    client = ActionDispatchClient(target_repo="owner/controller", transport=transport)
    request = RunRequest(molecule=Molecule(symbols=["He"], coordinates=[[0, 0, 0]]),
                         calculation_environment="github-actions", purpose="energy")
    receipt = client.dispatch_request(request)
    return client, transport, receipt


def make_evidence(root: Path, transport: GitHubFixture, receipt, *, receipt_patch=None, mutate=None):
    root.mkdir()
    request = dict(receipt.inputs)
    request["calculation_environment"] = "local"
    accounting = None
    if receipt.inputs.get("include_queue_in_budget"):
        from topos.actions.queue_budget import local_request_with_budget, queue_accounting
        accounting = queue_accounting(receipt.inputs, transport.run["created_at"], "2026-10-07T12:00:30+00:00")
        request = local_request_with_budget(receipt.inputs, accounting)
    # A failed record deliberately contains no simulated molecular result.
    record = RunRecord(request=RunRequest.model_validate(request), status="failed",
                       metadata={"budget_accounting": accounting} if accounting else {})
    manifest = RunStore(root / "run").commit(record)
    worker = {"schema_version": "topos-compute-worker/0.1.0", "context_verified": True,
              "local_request_sha256": hashlib.sha256(_canonical(request)).hexdigest(),
              "run": {key: manifest[key] for key in ("run_id", "snapshot_id", "record_sha256")},
              "dispatch_id": receipt.dispatch_id, "request_sha256": receipt.request_sha256,
              "request": receipt.inputs, "github_run_id": "123", "github_sha": SHA,
              "run_path": "run", "status": "failed"}
    if accounting is not None:
        worker["budget_accounting"] = accounting
    worker.update(receipt_patch or {})
    atomic_json(root / "worker-receipt.json", worker)
    if mutate:
        mutate(root)
    from topos.actions.hosted_worker import INVENTORY_SCHEMA

    members = [{"path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size}
               for path in sorted(root.rglob("*")) if path.is_file() and path.name != ".writer.lock"]
    atomic_json(root / "evidence-inventory.json", {"schema_version": INVENTORY_SCHEMA, "files": members})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name != ".writer.lock":
                archive.write(path, path.relative_to(root).as_posix())
    transport.content = buffer.getvalue()
    transport.run["status"] = "completed"
    transport.run["conclusion"] = "failure"
    transport.artifacts = [{"id": 999, "name": f"topos-evidence-{receipt.dispatch_id}",
                            "expired": False, "size_in_bytes": len(transport.content),
                            "digest": "sha256:" + hashlib.sha256(transport.content).hexdigest(),
                            "workflow_run": {"id": 123, "head_sha": SHA}}]
    return record


def test_dispatch_preserves_exact_normalized_request_and_pins_commit(submitted):
    _, transport, receipt = submitted
    assert receipt.status == "submitted"
    assert receipt.remote_job_id is None
    assert receipt.record is None
    assert receipt.commit_sha == SHA
    payload = transport.calls[-1][2]["inputs"]
    raw = base64.b64decode(payload["request_b64"], validate=True)
    assert raw == _canonical(receipt.inputs)
    assert hashlib.sha256(raw).hexdigest() == payload["request_sha256"]
    assert receipt.dispatch_id == payload["dispatch_id"]


def test_missing_repository_credentials_are_honest_without_local_fallback(submitted, monkeypatch):
    _, _, receipt = submitted
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = ActionDispatchClient(target_repo="owner/controller").dispatch_request(receipt.inputs)
    assert result.status == "unavailable"
    assert "credential" in result.details
    assert result.remote_job_id is None


def test_queue_inclusive_budget_preserves_original_submitted_request(submitted):
    client, transport, receipt = submitted
    transport.calls.clear()
    result = client.dispatch_request({**receipt.inputs, "include_queue_in_budget": True})
    assert result.status == "submitted"
    assert result.inputs["include_queue_in_budget"] is True
    assert result.inputs["budget_seconds"] == receipt.inputs["budget_seconds"]


@pytest.mark.parametrize("private, ref", [(False, "main"), (True, "unreviewed")])
def test_controller_requires_private_default_branch(submitted, private, ref):
    client, transport, previous = submitted
    transport.calls.clear()
    transport.private = private
    result = client.dispatch_request(previous.inputs, ref=ref)
    assert result.status == "unavailable"
    assert not any(call[0] == "POST" for call in transport.calls)


def test_poll_requires_title_revision_event_and_workflow(submitted):
    client, transport, receipt = submitted
    original = dict(transport.run)
    for key, replacement in (("display_title", "unrelated"),
                              ("event", "push"), ("path", ".github/workflows/unrelated.yml")):
        transport.run = {**original, key: replacement}
        result = client.poll(receipt)
        assert result.status == "submitted" and result.remote_job_id is None
    transport.run = original
    result = client.poll(receipt)
    assert result.status == "running" and result.remote_job_id == "123"
    assert result.record is None


def test_changed_branch_head_is_detected_and_owned_run_cancelled(submitted):
    client, transport, receipt = submitted
    transport.run["head_sha"] = "b" * 40
    with pytest.raises(RemoteExecutionError, match="run 123.*unexpected controller revision.*Cancellation requested"):
        client.poll(receipt)
    assert transport.calls[-1][:2] == ("POST", "/repos/owner/controller/actions/runs/123/cancel")


def test_completed_unexpected_revision_is_rejected_without_artifact_retrieval(submitted, tmp_path):
    client, transport, receipt = submitted
    transport.run.update(head_sha="b" * 40, status="completed")
    with pytest.raises(RemoteExecutionError, match="already ended; its results are rejected"):
        client.retrieve_result(receipt, tmp_path / "evidence")
    assert not any(call[0] == "DOWNLOAD" or call[1].endswith("/cancel") for call in transport.calls)


def test_ambiguous_owned_revision_race_never_cancels_an_arbitrary_run(submitted):
    client, transport, receipt = submitted
    transport.extra_runs = [{**transport.run, "id": 124, "head_sha": "b" * 40}]
    with pytest.raises(RemoteExecutionError, match="Multiple"):
        client.poll(receipt)
    assert not any(call[1].endswith("/cancel") for call in transport.calls)


def test_unregistered_matrix_route_is_rejected_before_any_network_call(submitted):
    client, transport, receipt = submitted
    transport.calls.clear()
    with pytest.raises(ValueError, match="registered"):
        client.dispatch_request({**receipt.inputs, "purpose": "matrix", "matrix_row_id": "T1-30min"})
    assert transport.calls == []


def test_ambiguous_correlation_and_changed_receipt_are_rejected(submitted):
    client, transport, receipt = submitted
    transport.extra_runs = [{**transport.run, "id": 124}]
    with pytest.raises(RemoteExecutionError, match="Multiple"):
        client.poll(receipt)
    with pytest.raises(RemoteExecutionError, match="checksum"):
        client.poll(replace(receipt, inputs={**receipt.inputs, "budget_seconds": 42}))


def test_cancel_only_owned_correlated_run_and_never_claims_termination(submitted):
    client, transport, receipt = submitted
    result = client.cancel(receipt)
    assert result.status == "cancellation-requested"
    assert transport.calls[-1][:2] == ("POST", "/repos/owner/controller/actions/runs/123/cancel")
    assert result.record is None


def test_completed_github_run_is_not_itself_completed_science(submitted):
    client, transport, receipt = submitted
    transport.run.update(status="completed", conclusion="success")
    result = client.poll(receipt)
    assert result.status == "awaiting-retrieval"
    assert result.validation_status == "not-evaluated"
    assert result.record is None


def test_retrieved_failed_worker_record_is_verified_and_remains_failed(submitted, tmp_path):
    client, transport, receipt = submitted
    original = make_evidence(tmp_path / "source", transport, receipt)
    result = client.retrieve_result(receipt, tmp_path / "verified")
    assert result.status == "failed"
    assert result.record == original.model_dump(mode="json")
    assert RunStore(tmp_path / "verified/run").load() == result.record
    assert result.artifact_path == str(tmp_path / "verified")


@pytest.mark.parametrize("key,value", [("request_sha256", "b" * 64), ("github_sha", "b" * 40),
                                      ("github_run_id", "124"), ("dispatch_id", "another"),
                                      ("request", {}), ("run_path", "elsewhere"), ("status", "completed")])
def test_worker_receipt_identity_is_required(submitted, tmp_path, key, value):
    client, transport, receipt = submitted
    make_evidence(tmp_path / "source", transport, receipt, receipt_patch={key: value})
    with pytest.raises(RemoteExecutionError):
        client.retrieve_result(receipt, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


def test_artifact_association_digest_and_expiry_are_enforced(submitted, tmp_path):
    client, transport, receipt = submitted
    make_evidence(tmp_path / "source", transport, receipt)
    original = dict(transport.artifacts[0])
    for key, value in (("workflow_run", {"id": 124, "head_sha": SHA}),
                       ("digest", "sha256:" + "b" * 64), ("expired", True)):
        transport.artifacts[0] = {**original, key: value}
        with pytest.raises(RemoteExecutionError):
            client.retrieve_result(receipt, tmp_path / "rejected")
        assert not (tmp_path / "rejected").exists()


def test_snapshot_corruption_prevents_publication(submitted, tmp_path):
    client, transport, receipt = submitted

    def corrupt(root):
        next(root.rglob("record.h5")).write_bytes(b"not the original record")

    make_evidence(tmp_path / "source", transport, receipt, mutate=corrupt)
    with pytest.raises(RemoteExecutionError, match="checksum validation"):
        client.retrieve_result(receipt, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "run/../escape", "run\\escape", "C:/escape"])
def test_archive_paths_are_confined(tmp_path, name):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, b"forbidden")
    with pytest.raises(RemoteExecutionError, match="unsafe"):
        _extract_archive(buffer.getvalue(), tmp_path)


def test_symlink_zip_entry_is_rejected(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        entry = zipfile.ZipInfo("link")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(entry, "../target")
    with pytest.raises(RemoteExecutionError, match="nonregular"):
        _extract_archive(buffer.getvalue(), tmp_path)


def test_wait_cancellation_requests_only_its_owned_job(submitted, tmp_path):
    client, _, receipt = submitted
    cancelled = Event()
    cancelled.set()
    result = client.wait_for_result(receipt, tmp_path / "result", cancel_event=cancelled)
    assert result.status == "cancellation-requested"


def test_cancel_during_run_index_delay_is_not_abandoned(submitted, tmp_path, monkeypatch):
    client, transport, receipt = submitted
    original = transport.request
    counter = {"lists": 0}

    def delayed(method, path, payload=None):
        if "/runs?" in path:
            counter["lists"] += 1
            if counter["lists"] <= 2:
                return {"workflow_runs": []}
        return original(method, path, payload)

    monkeypatch.setattr(transport, "request", delayed)
    cancelled = Event()
    cancelled.set()
    result = client.wait_for_result(receipt, tmp_path / "result", cancel_event=cancelled,
                                     timeout_seconds=1, poll_interval=.001)
    assert counter["lists"] >= 3
    assert result.status == "cancellation-requested"
    assert transport.calls[-1][:2] == ("POST", "/repos/owner/controller/actions/runs/123/cancel")


def test_remote_workflow_records_missing_configuration_without_execution(tmp_path, monkeypatch):
    from topos.config import SystemConfig
    from topos.remote_workflow import run_remote
    from topos.workflow import Workflow

    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    workflow = Workflow(output_root=tmp_path / "runs", config=SystemConfig())
    request = RunRequest(molecule=Molecule(symbols=["He"], coordinates=[[0, 0, 0]]),
                         calculation_environment="github-actions", purpose="energy")
    result = run_remote(workflow, request)
    assert result.status == "unavailable"
    assert result.request == request
    assert not result.attempts and not result.candidates
    assert RunStore(result.metadata["run_dir"]).load()["status"] == "unavailable"


def test_remote_workflow_imports_verified_record_and_preserves_user_request(submitted, tmp_path, monkeypatch):
    from topos import remote_workflow
    from topos.config import SystemConfig
    from topos.workflow import Workflow

    client, transport, receipt = submitted
    original = make_evidence(tmp_path / "source", transport, receipt)
    monkeypatch.setattr(client, "dispatch_request", lambda request, ref: receipt)
    monkeypatch.setattr(remote_workflow, "ActionDispatchClient", lambda **kwargs: client)
    request = RunRequest.model_validate(receipt.inputs)
    workflow = Workflow(tmp_path / "reviews", config=SystemConfig(remote_repository="owner/controller"))
    result = remote_workflow.run_remote(workflow, request)
    assert result.status == "failed"
    assert result.request == request
    assert result.metadata["remote_completion_confirmed"] is True
    assert result.metadata["remote_source_run_id"] == original.run_id
    folder = Path(result.metadata["run_dir"])
    assert json.loads((folder / "remote-worker-record.json").read_text()) == original.model_dump(mode="json")
    assert RunStore(folder).load() == result.model_dump(mode="json")


def test_artifact_redirect_never_forwards_github_authorization(monkeypatch):
    import urllib.request

    requests = []
    headers = Message()
    headers["Location"] = "https://productionresultssa0.blob.core.windows.net/data/archive.zip?sig=private"

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            if len(requests) == 1:
                raise urllib.error.HTTPError(request.full_url, 302, "redirect", headers, io.BytesIO())
            return io.BytesIO(b"artifact bytes")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    result = _GitHubTransport("explicit-credential").download("/repos/owner/controller/actions/artifacts/123/zip")
    assert result == b"artifact bytes"
    assert requests[0].get_header("Authorization") == "Bearer explicit-credential"
    assert requests[1].get_header("Authorization") is None
    assert requests[1].get_header("Cookie") is None


@pytest.mark.parametrize("location", ["https://evil.example/secret", "http://productionresultssa0.blob.core.windows.net/archive",
                                     "https://user:password@productionresultssa0.blob.core.windows.net/archive",
                                     "https://productionresultssa0.blob.core.windows.net:8443/archive"])
def test_artifact_redirect_rejects_unexpected_destinations(monkeypatch, location):
    import urllib.request

    headers = Message()
    headers["Location"] = location

    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, 302, "redirect", headers, io.BytesIO())

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(RemoteExecutionError, match="outside GitHub") as error:
        _GitHubTransport("explicit-credential").download("/repos/owner/controller/actions/artifacts/123/zip")
    assert "explicit-credential" not in str(error.value)
    assert location not in str(error.value)


def test_queue_accounting_is_independently_bound_to_server_timestamp(submitted, tmp_path):
    client, transport, receipt = submitted
    receipt = client.dispatch_request({**receipt.inputs, "include_queue_in_budget": True, "budget_seconds": 120})
    expected = make_evidence(tmp_path / "worker", transport, receipt)
    result = client.retrieve_result(receipt, tmp_path / "retrieved")
    assert result.github_created_at == transport.run["created_at"]
    assert result.record == expected.model_dump(mode="json")
    assert result.record["request"]["budget_seconds"] == 90
    assert result.inputs["budget_seconds"] == 120


def test_forged_queue_origin_cannot_extend_execution_budget(submitted, tmp_path):
    client, transport, receipt = submitted
    receipt = client.dispatch_request({**receipt.inputs, "include_queue_in_budget": True, "budget_seconds": 120})
    make_evidence(tmp_path / "worker", transport, receipt)
    transport.run["created_at"] = "2026-10-07T11:59:30Z"
    with pytest.raises(RemoteExecutionError, match="checksum validation"):
        client.retrieve_result(receipt, tmp_path / "retrieved")
    assert not (tmp_path / "retrieved").exists()


def test_queue_request_requires_valid_server_creation_time(submitted):
    client, transport, receipt = submitted
    receipt = client.dispatch_request({**receipt.inputs, "include_queue_in_budget": True})
    transport.run.pop("created_at")
    with pytest.raises(RemoteExecutionError, match="server creation timestamp"):
        client.poll(receipt)
