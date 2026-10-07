"""Persist TOPOS remote requests and import verified worker evidence for review."""
from __future__ import annotations

import shutil
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

from .actions.dispatch import ActionDispatchClient, DispatchResult, RemoteExecutionError
from .models import Artifact, RunRecord, RunRequest, utc_now
from .storage import RunStore, artifact_inventory, atomic_json, confined_file, file_digest

if TYPE_CHECKING:
    from .workflow import Workflow


def _transport_metadata(receipt: DispatchResult) -> dict:
    return {key: value for key, value in receipt.to_dict().items() if key not in {"inputs", "record"}}


def run_remote(workflow: Workflow, request: RunRequest, *, cancel_event: Event | None = None) -> RunRecord:
    """Submit through the BASE-provisioned worker; never fall back to local QM.

    The worker's unmodified snapshot remains under remote-evidence. The local
    review record identifies its source run and keeps the user's original remote
    request; copied native evidence is independently included in its RunStore.
    """
    record = RunRecord(request=request)
    folder = workflow.output_root / record.run_id
    folder.mkdir(parents=True, exist_ok=False)
    record.metadata.update(run_dir=str(folder), execution_kind="remote-request",
                           capability_scope="CoChem-BASE provisioned GitHub Actions worker")
    store = RunStore(folder)
    store.commit(record)
    if cancel_event is not None and cancel_event.is_set():
        record.status = "cancelled"
        record.metadata["termination_reason"] = "cancelled before remote submission"
        store.commit(record)
        return record
    client = ActionDispatchClient(target_repo=workflow.config.remote_repository)
    try:
        receipt = client.dispatch_request(request, ref=workflow.config.remote_ref)
        record.metadata["remote_dispatch"] = _transport_metadata(receipt)
        if receipt.status == "unavailable":
            record.status = "unavailable"
            record.metadata["termination_reason"] = receipt.details
            store.commit(record)
            return record
        record.status = "queued"
        store.commit(record)
        atomic_json(folder / "dispatch-receipt.json", receipt.to_dict())
        receipt = client.wait_for_result(receipt, folder / "remote-evidence",
                                         timeout_seconds=5400 + request.budget_seconds,
                                         cancel_event=cancel_event)
        record.metadata["remote_dispatch"] = _transport_metadata(receipt)
        atomic_json(folder / "dispatch-receipt.json", receipt.to_dict())
        if receipt.record is None:
            record.status = "timed-out" if receipt.status == "polling-timed-out" else "running"
            record.metadata["termination_reason"] = receipt.details
            record.metadata["remote_completion_confirmed"] = False
            store.commit(record)
            return record
        source = RunRecord.model_validate(receipt.record)
        evidence = Path(receipt.artifact_path)
        source_store = RunStore(evidence / "run")
        snapshot = source_store.snapshot_path()
        for entry in artifact_inventory(receipt.record):
            origin = confined_file(snapshot / "artifacts", entry["path"])
            target = folder / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            with origin.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
        source_record = folder / "remote-worker-record.json"
        atomic_json(source_record, receipt.record)
        worker_receipt = folder / "remote-worker-receipt.json"
        shutil.copyfile(evidence / "worker-receipt.json", worker_receipt)
        # Keep original worker identifiers and the transformation explicit.
        source.metadata.update(record.metadata)
        source.metadata.update(remote_source_run_id=source.run_id, remote_completion_confirmed=True,
                               execution_kind="verified-github-actions-result")
        source.run_id = record.run_id
        source.request = request
        source.created_at = record.created_at
        source.updated_at = utc_now()
        for attempt in source.attempts:
            attempt.run_id = record.run_id
        for path, role in ((source_record, "remote-worker-record"), (worker_receipt, "remote-worker-receipt")):
            source.artifacts.append(Artifact(path=path.name, sha256=file_digest(path),
                                             size_bytes=path.stat().st_size, role=role))
        store.commit(source)
        return source
    except (RemoteExecutionError, OSError, ValueError) as exc:
        record.status = "failed"
        record.updated_at = utc_now()
        record.metadata["termination_reason"] = str(exc)
        record.metadata["remote_completion_confirmed"] = False
        store.commit(record)
        return record
