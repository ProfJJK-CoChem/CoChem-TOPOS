"""Persist TOPOS remote requests and recover the same owned Actions job."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from filelock import FileLock

from .actions.dispatch import ActionDispatchClient, DispatchResult, RemoteExecutionError
from .models import Artifact, RunRecord, RunRequest, utc_now
from .storage import (
    IntegrityError,
    RunStore,
    artifact_inventory,
    atomic_json,
    confined_file,
    digest_json,
    file_digest,
    read_json,
)

if TYPE_CHECKING:
    from .workflow import Workflow


def _transport_metadata(receipt: DispatchResult) -> dict[str, Any]:
    return {key: value for key, value in receipt.to_dict().items() if key not in {"inputs", "record"}}


def _check_binding(workflow: Workflow, record: RunRecord, receipt: DispatchResult,
                   *, original_request: dict[str, Any] | None = None) -> None:
    request = original_request if original_request is not None else record.request.model_dump(mode="json")
    if (receipt.target_repo != workflow.config.remote_repository
            or receipt.ref != workflow.config.remote_ref):
        raise IntegrityError("Saved dispatch belongs to a different configured controller or ref")
    if receipt.inputs != request or receipt.request_sha256 != record.metadata["request_sha256"]:
        raise IntegrityError("Saved dispatch differs from the immutable user request")


def _copy_verified_file(origin: Path, target: Path, *, root: Path) -> None:
    """Recover an interrupted import without replacing an existing native file."""
    if (not target.is_relative_to(root) or not target.resolve().is_relative_to(root)
            or any(parent.is_symlink() for parent in (target, *target.parents) if parent.is_relative_to(root))):
        raise IntegrityError("Remote import paths must remain inside this run without symbolic links")
    target.parent.mkdir(parents=True, exist_ok=True)
    expected_size, expected_digest = origin.stat().st_size, file_digest(origin)
    if target.exists() or target.is_symlink():
        if (target.is_symlink() or not target.is_file() or target.stat().st_size != expected_size
                or file_digest(target) != expected_digest):
            raise IntegrityError("Existing remote import artifact differs from verified worker evidence")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".remote-import-", dir=target.parent)
    staged = Path(temporary)
    try:
        with origin.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        if staged.stat().st_size != expected_size or file_digest(staged) != expected_digest:
            raise IntegrityError("Worker artifact changed during remote import")
        os.replace(staged, target)
    finally:
        staged.unlink(missing_ok=True)


def _import_result(record: RunRecord, store: RunStore, receipt: DispatchResult) -> RunRecord:
    """Retain both worker-local and caller-remote identities explicitly."""
    folder = store.run_dir
    source = RunRecord.model_validate(receipt.record)
    evidence = Path(receipt.artifact_path or "")
    if not evidence.is_absolute() or evidence.parent != folder:
        raise IntegrityError("Verified worker evidence must belong to this local run directory")
    source_store = RunStore(evidence / "run")
    if source_store.load() != receipt.record:
        raise IntegrityError("Retrieved worker record differs from its immutable snapshot")
    snapshot = source_store.snapshot_path()
    for entry in artifact_inventory(receipt.record):
        origin = confined_file(snapshot / "artifacts", entry["path"])
        target = folder / entry["path"]
        if Path(entry["path"]).parts[0] in {"snapshots", "CURRENT.json", ".execution.lock", ".writer.lock"}:
            raise IntegrityError("Worker artifact conflicts with local persistence or execution ownership")
        _copy_verified_file(origin, target, root=folder)
    source_record = folder / "remote-worker-record.json"
    if source_record.exists() or source_record.is_symlink():
        if source_record.is_symlink() or read_json(source_record) != receipt.record:
            raise IntegrityError("Existing worker record differs from the retrieved immutable snapshot")
    else:
        atomic_json(source_record, receipt.record)
    worker_receipt = folder / "remote-worker-receipt.json"
    _copy_verified_file(evidence / "worker-receipt.json", worker_receipt, root=folder)
    worker_identity = {
        "run_id": source.run_id,
        "request_sha256": digest_json(receipt.record["request"]),
        "input_sha256": digest_json(receipt.record["request"]["molecule"]),
        "record_sha256": digest_json(receipt.record),
        "github_run_id": receipt.remote_job_id,
        "controller_commit_sha": receipt.commit_sha,
    }
    source.metadata.update({key: value for key, value in record.metadata.items() if key != "termination_reason"})
    source.metadata.update(remote_source_run_id=source.run_id, remote_worker_identity=worker_identity,
                           remote_completion_confirmed=True, execution_kind="verified-github-actions-result")
    source.run_id = record.run_id
    source.request = record.request
    source.created_at = record.created_at
    source.updated_at = utc_now()
    for attempt in source.attempts:
        attempt.run_id = record.run_id
    # The worker's request.json describes its deliberate local execution. The
    # original caller request is independently retained as remote-request.json.
    source.artifacts.extend(record.artifacts)
    for path, role in ((source_record, "remote-worker-record"), (worker_receipt, "remote-worker-receipt")):
        source.artifacts.append(Artifact(path=path.name, sha256=file_digest(path),
                                         size_bytes=path.stat().st_size, role=role))
    store.commit(source)
    return source


def _wait_for_owned_result(workflow: Workflow, record: RunRecord, store: RunStore,
                           receipt: DispatchResult, *, cancel_event: Event | None,
                           timeout_seconds: float, original_request: dict[str, Any] | None = None) -> RunRecord:
    client = ActionDispatchClient(target_repo=workflow.config.remote_repository)
    try:
        _check_binding(workflow, record, receipt, original_request=original_request)
        destination = store.run_dir / "remote-evidence"
        if destination.exists() or destination.is_symlink():
            # A process can stop after retrieval but before committing the local
            # review record. Reauthenticate the same job into a fresh location;
            # existing native files must still match exactly before reuse.
            destination = store.run_dir / f"remote-evidence-recovery-{uuid4().hex}"
        receipt = client.wait_for_result(receipt, destination, timeout_seconds=timeout_seconds,
                                         cancel_event=cancel_event)
        _check_binding(workflow, record, receipt, original_request=original_request)
        record.metadata["remote_dispatch"] = _transport_metadata(receipt)
        atomic_json(store.run_dir / "dispatch-receipt.json", receipt.to_dict())
        if receipt.record is None:
            record.status = "timed-out" if receipt.status == "polling-timed-out" else "running"
            record.metadata["termination_reason"] = receipt.details
            record.metadata["remote_completion_confirmed"] = False
            record.updated_at = utc_now()
            store.commit(record)
            return record
        return _import_result(record, store, receipt)
    except (RemoteExecutionError, OSError, ValueError) as exc:
        record.status = "failed"
        record.updated_at = utc_now()
        record.metadata["termination_reason"] = str(exc)
        record.metadata["remote_completion_confirmed"] = False
        store.commit(record)
        return record


def run_remote(workflow: Workflow, request: RunRequest, *, cancel_event: Event | None = None) -> RunRecord:
    """Submit once through the BASE worker and import its unchanged evidence."""
    record = RunRecord(request=request)
    folder = workflow.output_root / record.run_id
    folder.mkdir(parents=True, exist_ok=False)
    record.metadata.update(run_dir=str(folder), execution_kind="remote-request",
                           input_sha256=digest_json(request.molecule.model_dump(mode="json")),
                           request_sha256=digest_json(request.model_dump(mode="json")),
                           capability_scope="CoChem-BASE provisioned GitHub Actions worker",
                           remote_completion_confirmed=False)
    request_path = folder / "remote-request.json"
    atomic_json(request_path, request.model_dump(mode="json"))
    record.artifacts.append(Artifact(path=request_path.name, sha256=file_digest(request_path),
                                     size_bytes=request_path.stat().st_size, role="remote-user-request"))
    store = RunStore(folder)
    store.commit(record)
    with FileLock(str(folder / ".execution.lock"), timeout=0):
        if cancel_event is not None and cancel_event.is_set():
            record.status = "cancelled"
            record.metadata["termination_reason"] = "cancelled before remote submission"
            store.commit(record)
            return record
        client = ActionDispatchClient(target_repo=workflow.config.remote_repository)
        try:
            receipt = client.dispatch_request(request, ref=workflow.config.remote_ref)
            _check_binding(workflow, record, receipt)
            record.metadata["remote_dispatch"] = _transport_metadata(receipt)
            if receipt.status == "unavailable":
                record.status = "unavailable"
                record.metadata["termination_reason"] = receipt.details
                store.commit(record)
                return record
            record.status = "queued"
            # The committed metadata is authoritative recovery state. A crash
            # after this commit needs only the same correlation ID, never a new
            # workflow dispatch or a local scientific retry.
            store.commit(record)
            atomic_json(folder / "dispatch-receipt.json", receipt.to_dict())
        except (RemoteExecutionError, OSError, ValueError) as exc:
            record.status = "failed"
            record.metadata["termination_reason"] = str(exc)
            store.commit(record)
            return record
        return _wait_for_owned_result(workflow, record, store, receipt, cancel_event=cancel_event,
                                      timeout_seconds=5400 + request.budget_seconds)


def _verify_completed_import(record: RunRecord, store: RunStore, receipt: DispatchResult) -> None:
    """A terminal remote wrapper must retain the bound original worker proof."""
    from .actions.queue_budget import verify_queue_record

    snapshot = store.snapshot_path() / "artifacts"
    source = read_json(confined_file(snapshot, "remote-worker-record.json"))
    worker = read_json(confined_file(snapshot, "remote-worker-receipt.json"))
    if worker.get("schema_version") != "topos-compute-worker/0.1.0" or worker.get("context_verified") is not True:
        raise IntegrityError("Saved remote completion lacks a verified worker execution context")
    for key, expected in (("dispatch_id", receipt.dispatch_id), ("request_sha256", receipt.request_sha256),
                          ("request", receipt.inputs), ("github_run_id", receipt.remote_job_id),
                          ("github_sha", receipt.commit_sha), ("run_path", "run"), ("status", source["status"])):
        if worker.get(key) != expected:
            raise IntegrityError(f"Saved worker receipt differs from its dispatch ownership: {key}")
    identity = {
        "run_id": source["run_id"], "request_sha256": digest_json(source["request"]),
        "input_sha256": digest_json(source["request"]["molecule"]), "record_sha256": digest_json(source),
        "github_run_id": receipt.remote_job_id, "controller_commit_sha": receipt.commit_sha,
    }
    if (source["request"] != verify_queue_record(receipt.inputs, source, worker.get("budget_accounting"),
                                                receipt.github_created_at)
            or worker.get("local_request_sha256") != digest_json(source["request"])
            or worker.get("run", {}).get("run_id") != source["run_id"]
            or worker.get("run", {}).get("record_sha256") != digest_json(source)
            or record.status != source["status"]
            or record.metadata.get("remote_source_run_id") != source["run_id"]
            or record.metadata.get("remote_worker_identity") != identity):
        raise IntegrityError("Saved remote completion differs from the immutable worker scientific record")


def resume_remote(workflow: Workflow, record: RunRecord, store: RunStore, *,
                  cancel_event: Event | None = None,
                  invocation_budget_seconds: float | None = None,
                  original_request: dict[str, Any] | None = None) -> RunRecord:
    """Poll/retrieve the existing owned job; never dispatch or execute locally."""
    current_request = record.request.model_dump(mode="json")
    request = original_request if original_request is not None else current_request
    if (record.metadata.get("request_sha256") != digest_json(request)
            or record.metadata.get("input_sha256") != digest_json(request["molecule"])):
        raise IntegrityError("Saved remote run lacks its verified immutable user request identity")
    saved = record.metadata.get("remote_dispatch")
    if not isinstance(saved, dict):
        if record.status in {"unavailable", "failed", "cancelled"}:
            return record
        raise IntegrityError("Remote run has no committed dispatch ownership receipt; resubmission is prohibited")
    if saved.get("status") == "unavailable":
        return record
    try:
        receipt = DispatchResult(**saved, inputs=request)
    except TypeError as exc:
        raise IntegrityError("Saved remote dispatch receipt has an invalid structure") from exc
    _check_binding(workflow, record, receipt, original_request=request)
    # Validate the exact workflow, correlation identifier, request hash and
    # pinned controller revision before committing continuation history.
    client = ActionDispatchClient(target_repo=workflow.config.remote_repository)
    client._check_receipt(receipt)
    if record.metadata.get("remote_completion_confirmed") is True:
        # Failed/partial/cancelled worker results are final scientific history
        # too. Starting another calculation requires an explicit new request.
        _verify_completed_import(record, store, receipt)
        return record
    if current_request != request:
        record.metadata["request_default_expansion"] = {
            "original_sha256": digest_json(request), "view_sha256": digest_json(current_request),
            "added_fields": sorted(set(current_request) - set(request)),
            "policy": "validate original request with current optional defaults; preserve stored original",
        }
    timeout = 5400 + record.request.budget_seconds if invocation_budget_seconds is None else invocation_budget_seconds
    record.metadata.setdefault("continuations", []).append({
        "requested_at": utc_now(), "previous_status": record.status,
        "previous_termination_reason": record.metadata.get("termination_reason"),
        "kind": "remote-owned-job-poll-and-retrieve", "polling_budget_seconds": timeout,
        "dispatch_id": receipt.dispatch_id, "remote_job_id": receipt.remote_job_id,
        "scientific_budget_seconds": record.request.budget_seconds,
    })
    record.status = "queued"
    record.updated_at = utc_now()
    store.commit(record)
    return _wait_for_owned_result(workflow, record, store, receipt, cancel_event=cancel_event,
                                  timeout_seconds=timeout, original_request=request)
