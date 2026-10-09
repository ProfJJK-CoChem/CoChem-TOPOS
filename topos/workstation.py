"""Queue TOPOS requests to a lab workstation through a Drive folder the user assigns.

The workstation runs the CoChem workstation job runner
(https://github.com/ProfJJK-CoChem/cochem_workstation_job_runner) with its
``topos_run`` template: ``python -m topos run --request request.json
--output-root runs``. Submitting returns at once with a ``queued`` record:
the job may legitimately wait for hours while the workstation owner uses the
machine. Resuming the run polls ``jobs/<label>/status.json`` in the folder and,
once results are published, imports them only after the worker's own
RunStore snapshot verifies and its request matches this submission exactly.

Nothing hard-codes a folder. It comes from ``SystemConfig.workstation_folder``
(or ``TOPOS_WORKSTATION_FOLDER`` / ``COCHEM_WORKSTATION_FOLDER``), or from the
folder assigned in CoChem-BASE. Google Drive folder links work through
CoChem-BASE's Drive API transport when BASE provides it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from threading import Event
from typing import TYPE_CHECKING, Any

from filelock import FileLock

from .models import Artifact, RunRecord, RunRequest, utc_now
from .storage import (
    IntegrityError,
    RunStore,
    artifact_inventory,
    atomic_json,
    confined_file,
    digest_json,
    file_digest,
)

if TYPE_CHECKING:
    from .workflow import Workflow

EXECUTION_KIND = "workstation-request"
JOB_SCHEMA = "cochem.workstation-job/1"
STATUS_SCHEMA = "cochem.workstation-job-status/1"
SUMMARY_SCHEMA = "cochem.workstation-job-summary/1"
FOLDER_SCHEMA = "cochem.workstation-folder/1"
FOLDER_MARKER = "cochem_workstation_folder.json"
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
DRIVE_LINK = re.compile(r"^(?:https://drive\.google\.com/|drive:)")
MAX_RESULT_BYTES = 4 * 1024 * 1024 * 1024
STUDENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


class WorkstationUnavailable(RuntimeError):
    """No workstation folder is assigned or reachable."""


# ---------------------------------------------------------------------------
# Settings and transport
# ---------------------------------------------------------------------------
def workstation_settings(config: Any) -> tuple[str, str, str]:
    """Return (folder, student_id, template) from TOPOS settings, the environment or BASE."""
    folder = getattr(config, "workstation_folder", None) or os.environ.get("TOPOS_WORKSTATION_FOLDER") \
        or os.environ.get("COCHEM_WORKSTATION_FOLDER")
    student = getattr(config, "workstation_student_id", None) or os.environ.get("TOPOS_WORKSTATION_STUDENT") \
        or os.environ.get("COCHEM_WORKSTATION_STUDENT")
    template = getattr(config, "workstation_template", None) or "topos_run"
    if not folder or not student:
        try:  # the folder assigned once in CoChem-BASE's Lab workstation panel
            from cochem_base.interfaces.workstation_queue import load_settings
            saved = load_settings()
        except Exception:
            saved = None
        if saved is not None:
            folder, student = folder or saved.folder, student or saved.student_id
    if not folder or not student:
        raise WorkstationUnavailable("Assign the lab workstation Drive folder and your student ID "
                                     "(Lab workstation settings) before choosing the workstation")
    if not STUDENT_ID.fullmatch(str(student)):
        raise WorkstationUnavailable("The workstation student ID may use letters, digits, '.', '_' and '-'")
    return str(folder), str(student), str(template)


class LocalFolder:
    """A folder synced by Google Drive for desktop (standard library only)."""

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder).expanduser()

    def ensure(self, student_id: str) -> None:
        if not self.folder.parent.is_dir():
            raise WorkstationUnavailable(f"{self.folder.parent} does not exist; is Google Drive for desktop running?")
        (self.folder / "inbox").mkdir(parents=True, exist_ok=True)
        (self.folder / "jobs").mkdir(parents=True, exist_ok=True)
        marker = self.folder / FOLDER_MARKER
        if not marker.is_file():
            marker.write_text(json.dumps({"schema": FOLDER_SCHEMA, "student_id": student_id,
                                          "created_by": "CoChem-TOPOS"}, indent=2) + "\n", encoding="utf-8")

    def submit(self, job_name: str, files: dict[str, bytes]) -> None:
        inbox = self.folder / "inbox"
        if not inbox.is_dir():
            raise WorkstationUnavailable(f"{self.folder} is not an assigned workstation folder (missing inbox/)")
        staging = inbox / f".cochem-upload-{uuid.uuid4().hex[:12]}"
        staging.mkdir()
        try:
            for name, contents in files.items():
                (staging / name).write_bytes(contents)
            os.replace(staging, inbox / job_name)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def pending(self, job_name: str) -> bool:
        return (self.folder / "inbox" / job_name).is_dir()

    def status(self, job_name: str, client_job_id: str) -> dict | None:
        for path in sorted((self.folder / "jobs").glob(job_name + "__*/status.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if doc.get("schema") == STATUS_SCHEMA and doc.get("client_job_id") == client_job_id:
                return doc
        return None

    def download_result(self, status: dict, destination: Path) -> None:
        name = str(status.get("result_file") or "")
        source = self.folder / "jobs" / str(status["label"]) / name
        if not name or "/" in name or "\\" in name or source.is_symlink() or not source.is_file():
            raise WorkstationUnavailable("The results archive has not finished syncing yet")
        shutil.copyfile(source, destination)

    def cancel(self, job_name: str, status: dict | None) -> None:
        if status is None and self.pending(job_name):
            shutil.rmtree(self.folder / "inbox" / job_name)
        elif status is not None:
            (self.folder / "jobs" / str(status["label"]) / "CANCEL").write_text("cancel requested\n", encoding="utf-8")


def open_transport(folder: str, student_id: str) -> Any:
    if DRIVE_LINK.match(folder.strip()):
        try:
            from cochem_base.interfaces.workstation_queue import WorkstationSettings
            from cochem_base.interfaces.workstation_queue import open_transport as base_transport
        except ImportError as exc:
            raise WorkstationUnavailable("Google Drive folder links need CoChem-BASE's workstation support; "
                                         "use a folder synced by Google Drive for desktop instead") from exc
        return base_transport(WorkstationSettings(folder=folder.strip(), student_id=student_id))
    return LocalFolder(folder)


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------
def _job_files(worker_request: bytes, *, job_name: str, client_job_id: str, student_id: str, template: str,
               request: RunRequest) -> dict[str, bytes]:
    hours = max(1, min(168, int(request.budget_seconds // 3600) + 2))
    manifest = {"schema": JOB_SCHEMA, "engine": template, "name": job_name, "input": "request.json",
                "resources": {"cores": request.threads, "memory_gb": round(request.memory_mb / 1024, 3),
                              "max_hours": hours},
                "job_id": client_job_id, "student_id": student_id,
                "files": {"request.json": hashlib.sha256(worker_request).hexdigest()}}
    return {"request.json": worker_request, "job.json": json.dumps(manifest, indent=2, sort_keys=True).encode()}


def run_workstation(workflow: Workflow, request: RunRequest, *, cancel_event: Event | None = None,
                    staged_record: RunRecord | None = None) -> RunRecord:
    """Deposit the request in the assigned folder and return the queued record at once."""
    record = staged_record if staged_record is not None else RunRecord(request=request)
    folder = workflow.output_root / record.run_id
    if staged_record is None:
        folder.mkdir(parents=True, exist_ok=False)
        record.metadata["run_dir"] = str(folder)
        RunStore(folder).commit(record)
    elif Path(record.metadata.get("run_dir", "")).resolve() != folder:
        raise IntegrityError("The staged external run does not belong to this output root")
    store = RunStore(folder)
    with FileLock(str(folder / ".execution.lock"), timeout=0):
        if staged_record is not None:
            from .remote_workflow import _verify_pristine_external
            _verify_pristine_external(record, store, workflow, request)
        record.metadata.update(run_dir=str(folder), execution_kind=EXECUTION_KIND,
                               input_sha256=digest_json(request.molecule.model_dump(mode="json")),
                               request_sha256=digest_json(request.model_dump(mode="json")),
                               capability_scope="CoChem workstation job runner (assigned Drive folder queue)",
                               workstation_completion_confirmed=False)
        request_path = folder / "workstation-request.json"
        atomic_json(request_path, request.model_dump(mode="json"))
        record.artifacts.append(Artifact(path=request_path.name, sha256=file_digest(request_path),
                                         size_bytes=request_path.stat().st_size, role="workstation-user-request"))
        store.commit(record)
        if cancel_event is not None and cancel_event.is_set():
            record.status = "cancelled"
            record.metadata["termination_reason"] = "cancelled before workstation submission"
            store.commit(record)
            return record
        try:
            folder_setting, student, template = workstation_settings(workflow.config)
            transport = open_transport(folder_setting, student)
            transport.ensure(student)
            worker = RunRequest.model_validate({**request.model_dump(mode="json"),
                                                "calculation_environment": "local"})
            worker_bytes = json.dumps(worker.model_dump(mode="json"), indent=2, sort_keys=True).encode()
            job_name = "topos-" + record.run_id.removeprefix("run_")[:12]
            client_job_id = "cochem-topos:" + record.run_id
            transport.submit(job_name, _job_files(worker_bytes, job_name=job_name, client_job_id=client_job_id,
                                                  student_id=student, template=template, request=request))
        except WorkstationUnavailable as exc:
            record.status = "unavailable"
            record.metadata["termination_reason"] = str(exc)
            store.commit(record)
            return record
        except (OSError, ValueError, RuntimeError) as exc:
            record.status = "failed"
            record.metadata["termination_reason"] = f"workstation submission failed: {exc}"
            store.commit(record)
            return record
        record.metadata["workstation_dispatch"] = {
            "client_job_id": client_job_id, "job_name": job_name, "folder": folder_setting, "student_id": student,
            "template": template, "worker_request_sha256": hashlib.sha256(worker_bytes).hexdigest(),
            "worker_request_identity": digest_json(worker.model_dump(mode="json")), "submitted_at": utc_now(),
            "state": "SUBMITTED", "message": "Waiting for the workstation to pick the job up from the folder",
        }
        record.status = "queued"
        record.updated_at = utc_now()
        store.commit(record)
        return record


# ---------------------------------------------------------------------------
# Polling and verified import
# ---------------------------------------------------------------------------
def _safe_extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if sum(m.file_size for m in members) > MAX_RESULT_BYTES or len(members) > 50000:
            raise IntegrityError("The workstation results archive is larger than TOPOS imports")
        for member in members:
            if member.is_dir():
                continue
            path = PurePosixPath(member.filename.replace("\\", "/"))
            if (path.is_absolute() or ".." in path.parts or not path.parts or ":" in path.parts[0]
                    or (member.external_attr >> 16) & 0o170000 == 0o120000):
                raise IntegrityError("The workstation results archive contains an unsafe entry")
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink, 1024 * 1024)


def _worker_run(evidence: Path, dispatch: dict) -> tuple[RunStore, dict]:
    summary = json.loads((evidence / "_runner" / "job_summary.json").read_text(encoding="utf-8"))
    if (summary.get("schema") != SUMMARY_SCHEMA or summary.get("client_job_id") != dispatch["client_job_id"]
            or (summary.get("input_hashes") or {}).get("request.json") != dispatch["worker_request_sha256"]):
        raise IntegrityError("The returned workstation results belong to a different TOPOS request")
    runs = [path.parent for path in (evidence / "runs").glob("*/CURRENT.json")]
    if len(runs) != 1:
        raise IntegrityError("The workstation results must contain exactly one TOPOS run record")
    worker_store = RunStore(runs[0])
    worker_store.verify()
    source = worker_store.load()
    if digest_json(source["request"]) != dispatch["worker_request_identity"]:
        raise IntegrityError("The workstation's TOPOS record ran a different request")
    return worker_store, source


def _import(record: RunRecord, store: RunStore, worker_store: RunStore, source_doc: dict,
            dispatch: dict, status: dict) -> RunRecord:
    """Bring the verified worker artifacts into this run, keeping both identities."""
    from .remote_workflow import _copy_verified_file

    folder = store.run_dir
    source = RunRecord.model_validate(source_doc)
    snapshot = worker_store.snapshot_path()
    original_paths = {artifact.path for artifact in record.artifacts}
    rebound = {}
    for entry in artifact_inventory(source_doc):
        relative = entry["path"]
        if Path(relative).parts[0] in {"snapshots", "CURRENT.json", ".execution.lock", ".writer.lock"}:
            raise IntegrityError("Worker artifact conflicts with local persistence or execution ownership")
        if relative in original_paths:
            if relative not in {"request.json", "input.xyz"}:
                raise IntegrityError("Worker artifact conflicts with retained caller evidence")
            rebound[relative] = "workstation-worker-inputs/" + relative
        _copy_verified_file(confined_file(snapshot / "artifacts", relative), folder / rebound.get(relative, relative),
                            root=folder)
    source.artifacts = [a.model_copy(update={"path": rebound.get(a.path, a.path)}) for a in source.artifacts]
    worker_record = folder / "workstation-worker-record.json"
    if worker_record.exists():
        if json.loads(worker_record.read_text(encoding="utf-8")) != source_doc:
            raise IntegrityError("Existing workstation worker record differs from the verified snapshot")
    else:
        atomic_json(worker_record, source_doc)
    identity = {"run_id": source.run_id, "request_sha256": digest_json(source_doc["request"]),
                "record_sha256": digest_json(source_doc), "workstation": status.get("workstation"),
                "workstation_job_label": status.get("label"), "client_job_id": dispatch["client_job_id"]}
    source.metadata.update({key: value for key, value in record.metadata.items() if key != "termination_reason"})
    source.metadata.update(workstation_source_run_id=source.run_id, workstation_worker_identity=identity,
                           workstation_completion_confirmed=True, execution_kind="verified-workstation-result")
    source.run_id = record.run_id
    source.request = record.request
    source.created_at = record.created_at
    source.updated_at = utc_now()
    for attempt in source.attempts:
        attempt.run_id = record.run_id
    source.artifacts.extend(record.artifacts)
    source.artifacts.append(Artifact(path=worker_record.name, sha256=file_digest(worker_record),
                                     size_bytes=worker_record.stat().st_size, role="workstation-worker-record"))
    store.commit(source)
    return source


def resume_workstation(workflow: Workflow, record: RunRecord, store: RunStore, *,
                       cancel_event: Event | None = None,
                       original_request: dict[str, Any] | None = None) -> RunRecord:
    """Poll the owned workstation job; import verified results once published. Never re-submits."""
    request = original_request if original_request is not None else record.request.model_dump(mode="json")
    if record.metadata.get("request_sha256") != digest_json(request) \
            or record.metadata.get("input_sha256") != digest_json(request["molecule"]):
        raise IntegrityError("Saved workstation run lacks its verified immutable user request identity")
    dispatch = record.metadata.get("workstation_dispatch")
    if not isinstance(dispatch, dict):
        if record.status in {"unavailable", "failed", "cancelled"}:
            return record
        raise IntegrityError("Workstation run has no committed submission; resubmission is prohibited")
    if record.metadata.get("workstation_completion_confirmed") is True:
        return record
    transport = open_transport(dispatch["folder"], dispatch["student_id"])
    status = transport.status(dispatch["job_name"], dispatch["client_job_id"])
    if cancel_event is not None and cancel_event.is_set():
        transport.cancel(dispatch["job_name"], status)
        dispatch.update(state="CANCEL_REQUESTED", message="Cancellation requested from TOPOS")
        record.metadata["workstation_dispatch"] = dispatch
        store.commit(record)
        return record
    if status is None:
        waiting = transport.pending(dispatch["job_name"])
        state = "SUBMITTED" if waiting else "SYNCING"
        message = ("Waiting for the workstation to pick the job up from the folder" if waiting
                   else "The job is between the inbox and jobs/ folders (Drive may still be syncing)")
        if dispatch.get("state") != state:
            dispatch.update(state=state, message=message, updated_at=utc_now())
            record.metadata["workstation_dispatch"] = dispatch
            store.commit(record)
        return record
    state = str(status.get("state"))
    live = {"state": state, "message": status.get("message") or status.get("explanation") or "",
            "workstation": status.get("workstation"), "label": status.get("label"),
            "queue_position": status.get("queue_position"), "resources": status.get("resources") or {},
            "repairs": status.get("repairs") or [], "progress": status.get("progress") or {},
            "output_tail": (status.get("output_tail") or [])[-20:]}
    changed = any(dispatch.get(key) != value for key, value in live.items())
    dispatch.update(live)
    record.metadata["workstation_dispatch"] = dispatch
    if state not in TERMINAL or (not status.get("result_file") and status.get("attempts", 0) > 0):
        new_status = "running" if state in {"RUNNING", "SUSPENDED"} or state in TERMINAL else "queued"
        if changed or record.status != new_status:
            dispatch["updated_at"] = utc_now()
            record.status = new_status
            record.updated_at = utc_now()
            store.commit(record)
        return record
    if not status.get("result_file"):  # rejected or cancelled before it ever ran
        record.status = "cancelled" if state == "CANCELLED" else "failed"
        record.metadata.update(termination_reason=live["message"], workstation_completion_confirmed=True)
        store.commit(record)
        return record
    evidence = store.run_dir / "workstation-evidence"
    if evidence.exists():
        evidence = store.run_dir / f"workstation-evidence-recovery-{uuid.uuid4().hex}"
    staging = Path(tempfile.mkdtemp(prefix=".workstation-", dir=store.run_dir))
    try:
        archive = staging / "results.zip"
        transport.download_result(status, archive)
        if status.get("result_sha256") and file_digest(archive) != status["result_sha256"]:
            raise WorkstationUnavailable("The results archive is still syncing (checksum differs)")
        _safe_extract(archive, staging / "evidence")
        shutil.move(str(staging / "evidence"), str(evidence))
    except (WorkstationUnavailable, OSError, zipfile.BadZipFile) as exc:
        dispatch["message"] = f"Results not imported yet: {exc}"
        store.commit(record)
        return record
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    worker_store, source = _worker_run(evidence, dispatch)
    return _import(record, store, worker_store, source, dispatch, status)
