"""Lab-workstation calculation environment: submit, poll, verified import.

The worker side is a real ``python -m topos run`` on the exact submitted
request (its outcome in this environment is whatever TOPOS genuinely records).
Only the job runner's protocol files - status.json and the results archive
summary - are written here, as the workstation runner would write them.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from topos.config import SystemConfig
from topos.models import RunRequest
from topos.storage import IntegrityError, RunStore
from topos.workflow import Workflow

REQUEST = {"molecule": {"symbols": ["O", "H", "H"], "coordinates": [[0, 0, 0], [0.7586, 0, 0.5043],
                                                                      [-0.7586, 0, 0.5043]],
                        "charge": 0, "multiplicity": 1},
           "purpose": "energy", "engine": "xtb", "method": "GFN2-xTB", "budget_seconds": 60,
           "threads": 4, "memory_mb": 2048, "calculation_environment": "workstation"}


def _workflow(tmp_path: Path, **settings) -> Workflow:
    (tmp_path / "Drive").mkdir(exist_ok=True)
    config = SystemConfig(output_root=tmp_path / "runs", workstation_folder=str(tmp_path / "Drive" / "alice"),
                          workstation_student_id="alice", **settings)
    return Workflow(config.output_root, config=config)


def _pick_up(folder: Path, dispatch: dict) -> tuple[Path, Path]:
    """What the runner does on intake: move the submission into jobs/<label>/ and copy it to scratch."""
    label = dispatch["job_name"] + "__0123abcd"
    job = folder / "jobs" / label
    job.mkdir(parents=True)
    (folder / "inbox" / dispatch["job_name"]).rename(job / "input")
    work = folder.parent.parent / "scratch" / label
    shutil.copytree(job / "input", work)
    return job, work


def _status(job: Path, dispatch: dict, state: str, archive: bytes | None = None, **extra) -> None:
    label = job.name
    doc = {"schema": "cochem.workstation-job-status/1", "label": label, "client_job_id": dispatch["client_job_id"],
           "state": state, "message": f"workstation reports {state.lower()}", "attempts": 1, "workstation": "lab-ws",
           "result_file": f"{label}_results.zip" if archive is not None else None,
           "result_sha256": hashlib.sha256(archive).hexdigest() if archive is not None else None,
           "progress": {}, "output_tail": ["line 1", "line 2"], **extra}
    if archive is not None:
        (job / doc["result_file"]).write_bytes(archive)
    (job / "status.json").write_text(json.dumps(doc))


def _archive(work: Path, dispatch: dict, *, request_hash: str | None = None, tamper: bool = False) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        for path in sorted(work.rglob("*")):
            relative = path.relative_to(work).as_posix()
            # The runner leaves out unchanged top-level inputs and lock files.
            if path.is_file() and relative not in {"request.json", "job.json"} and not path.name.endswith(".lock"):
                data = path.read_bytes()
                if tamper and path.parent.name == "artifacts" and path.name == "input.xyz":
                    data = data.replace(b"O", b"S", 1)
                bundle.writestr(relative, data)
        bundle.writestr("_runner/job_summary.json", json.dumps({
            "schema": "cochem.workstation-job-summary/1", "client_job_id": dispatch["client_job_id"],
            "input_hashes": {"request.json": request_hash or hashlib.sha256((work / "request.json").read_bytes()).hexdigest()}}))
    return stream.getvalue()


def _run_worker(work: Path) -> None:
    subprocess.run([sys.executable, "-m", "topos", "run", "--request", "request.json", "--output-root", "runs"],
                   cwd=work, capture_output=True, text=True, timeout=600, check=False)
    assert len(list((work / "runs").glob("*/CURRENT.json"))) == 1


def test_unassigned_folder_is_unavailable_not_failed(tmp_path, monkeypatch):
    for variable in ("TOPOS_WORKSTATION_FOLDER", "COCHEM_WORKSTATION_FOLDER", "TOPOS_WORKSTATION_STUDENT",
                     "COCHEM_WORKSTATION_STUDENT", "COCHEM_ARTIFACTS", "COCHEM_ARTIFACT_DIR"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("COCHEM_ARTIFACTS", str(tmp_path / "base-artifacts"))
    workflow = Workflow(tmp_path / "runs", config=SystemConfig(output_root=tmp_path / "runs"))
    record = workflow.run(RunRequest.model_validate(REQUEST))
    assert record.status == "unavailable" and "Assign the lab workstation" in record.metadata["termination_reason"]


def test_submit_poll_and_import_verified_worker_record(tmp_path):
    workflow = _workflow(tmp_path)
    folder = tmp_path / "Drive" / "alice"
    record = workflow.run(RunRequest.model_validate(REQUEST))
    assert record.status == "queued" and record.metadata["execution_kind"] == "workstation-request"
    dispatch = record.metadata["workstation_dispatch"]
    submitted = folder / "inbox" / dispatch["job_name"]
    manifest = json.loads((submitted / "job.json").read_text())
    worker_request = json.loads((submitted / "request.json").read_text())
    assert manifest["engine"] == "topos_run" and manifest["input"] == "request.json"
    assert manifest["resources"] == {"cores": 4, "memory_gb": 2.0, "max_hours": 2}
    assert manifest["files"]["request.json"] == hashlib.sha256((submitted / "request.json").read_bytes()).hexdigest()
    assert worker_request["calculation_environment"] == "local"
    assert json.loads((folder / "cochem_workstation_folder.json").read_text())["student_id"] == "alice"

    run_dir = Path(record.metadata["run_dir"])
    assert workflow.resume(run_dir).metadata["workstation_dispatch"]["state"] == "SUBMITTED"

    job, work = _pick_up(folder, dispatch)
    _status(job, dispatch, "PAUSED", queue_position=1)
    paused = workflow.resume(run_dir)
    assert paused.status == "queued" and paused.metadata["workstation_dispatch"]["state"] == "PAUSED"
    _status(job, dispatch, "RUNNING", progress={"step": 2})
    assert workflow.resume(run_dir).status == "running"

    _run_worker(work)
    _status(job, dispatch, "FAILED")  # terminal, archive not yet published
    assert workflow.resume(run_dir).status == "running"
    _status(job, dispatch, "FAILED", _archive(work, dispatch))
    imported = workflow.resume(run_dir)
    worker_store = RunStore(next((work / "runs").glob("*/CURRENT.json")).parent)
    worker = worker_store.load()
    assert imported.status == worker["status"]
    assert imported.metadata["execution_kind"] == "verified-workstation-result"
    assert imported.metadata["workstation_completion_confirmed"] is True
    assert imported.metadata["workstation_worker_identity"]["run_id"] == worker["run_id"]
    assert imported.run_id == record.run_id and imported.request == record.request
    RunStore(run_dir).verify()
    assert (run_dir / "workstation-worker-record.json").is_file()
    assert workflow.resume(run_dir) == imported  # final: never resubmitted or re-imported


@pytest.mark.parametrize("problem", ["tampered-artifact", "other-request"])
def test_mismatched_or_tampered_results_are_refused(tmp_path, problem):
    workflow = _workflow(tmp_path)
    folder = tmp_path / "Drive" / "alice"
    record = workflow.run(RunRequest.model_validate(REQUEST))
    dispatch = record.metadata["workstation_dispatch"]
    job, work = _pick_up(folder, dispatch)
    _run_worker(work)
    archive = _archive(work, dispatch, tamper=problem == "tampered-artifact",
                       request_hash="0" * 64 if problem == "other-request" else None)
    _status(job, dispatch, "COMPLETED", archive)
    with pytest.raises(IntegrityError):
        workflow.resume(Path(record.metadata["run_dir"]))
    assert RunStore(Path(record.metadata["run_dir"])).load()["metadata"].get("workstation_completion_confirmed") is False


def test_cancel_request_reaches_the_workstation(tmp_path):
    import threading
    workflow = _workflow(tmp_path)
    folder = tmp_path / "Drive" / "alice"
    record = workflow.run(RunRequest.model_validate(REQUEST))
    dispatch = record.metadata["workstation_dispatch"]
    job, _work = _pick_up(folder, dispatch)
    _status(job, dispatch, "RUNNING")
    cancel = threading.Event()
    cancel.set()
    workflow.resume(Path(record.metadata["run_dir"]), cancel_event=cancel)
    assert (job / "CANCEL").exists()


def test_rejected_submission_is_final(tmp_path):
    workflow = _workflow(tmp_path)
    folder = tmp_path / "Drive" / "alice"
    record = workflow.run(RunRequest.model_validate(REQUEST))
    dispatch = record.metadata["workstation_dispatch"]
    job, _work = _pick_up(folder, dispatch)
    _status(job, dispatch, "FAILED", attempts=0, message="Rejected: Unknown engine 'topos_run'")
    final = workflow.resume(Path(record.metadata["run_dir"]))
    assert final.status == "failed" and "Unknown engine" in final.metadata["termination_reason"]
    assert final.metadata["workstation_completion_confirmed"] is True


def test_streamlit_offers_the_workstation_and_its_folder_setting(tmp_path, monkeypatch):
    testing = pytest.importorskip("streamlit.testing.v1")
    monkeypatch.setenv("TOPOS_OUTPUT_ROOT", str(tmp_path / "runs"))
    (tmp_path / "Drive").mkdir()
    application = testing.AppTest.from_file(str(Path(__file__).resolve().parents[1] / "topos/streamlit_app.py"))
    application.run(timeout=30)
    assert not application.exception
    environment = next(item for item in application.selectbox if item.label == "Calculation environment")
    assert "workstation" in environment.options
    next(item for item in application.text_input if item.label == "Workstation Drive folder").input(
        str(tmp_path / "Drive" / "alice"))
    next(item for item in application.text_input if item.label == "Student ID").input("alice")
    next(item for item in application.button if item.label == "Use this workstation folder").click()
    application.run(timeout=30)
    assert not application.exception
    assert application.session_state["topos_execution_config"]["workstation_folder"] == str(tmp_path / "Drive" / "alice")
    assert (tmp_path / "Drive" / "alice" / "inbox").is_dir()


def test_queued_workstation_record_explains_itself(tmp_path):
    from topos.ui import _show_workstation_status

    class Recorder:
        def __init__(self):
            self.lines, self.session_state = [], {}

        def info(self, text):
            self.lines.append(text)

        write = caption = code = info

        def expander(self, *_args, **_kwargs):
            import contextlib
            return contextlib.nullcontext()

        def button(self, *_args, **_kwargs):
            return False

    workflow = _workflow(tmp_path)
    record = workflow.run(RunRequest.model_validate(REQUEST)).model_dump(mode="json")
    recorder = Recorder()
    _show_workstation_status(recorder, record)
    assert "Queued to the lab workstation" in recorder.lines[0] and "check back later" in recorder.lines[0]
    assert any("SUBMITTED" in line for line in recorder.lines)
