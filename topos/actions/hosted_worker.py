"""Bounded ORCA smoke calculation inside an explicitly approved hosted Actions job.

This is a worker, not a dispatch client. Environment guards are not a substitute
for inspecting the matching GitHub run and its retrieved artifact. It never
creates a publication export or approves the resulting candidate for a human.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import signal
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

import psutil

from topos.config import SystemConfig
from topos.models import RunRecord, RunRequest, utc_now
from topos.storage import (
    IntegrityError,
    RunStore,
    atomic_json,
    confined_file,
    digest_json,
    file_digest,
    read_json,
    safe_relative,
)
from topos.ui import parse_request_json
from topos.workflow import Workflow

RECEIPT_SCHEMA = "topos-hosted-worker/0.1.0"
INVENTORY_SCHEMA = "topos-hosted-evidence/0.1.0"
INSTALLATION_NAME = "orca-6.1.1"
EXPECTED_VERSION = "6.1.1"


class WorkerError(ValueError):
    """A controlled, credential-free failure explanation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _required(name: str, pattern: str) -> str:
    value = os.environ.get(name, "")
    if not re.fullmatch(pattern, value):
        raise WorkerError("invalid-runner-context", f"Missing or invalid required runner field: {name}")
    return value


def _no_symlink(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise WorkerError("unsafe-path", "Worker paths may not traverse symbolic links")


def _absolute_directory(value: str | Path, field: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.is_dir():
        raise WorkerError("unsafe-path", f"{field} must be an existing absolute directory")
    _no_symlink(path)
    return path.resolve()


def _fresh_roots(output_root: Path, evidence_root: Path) -> tuple[Path, Path, Path]:
    temporary = _absolute_directory(os.environ.get("RUNNER_TEMP", ""), "RUNNER_TEMP")
    # Even invalid runner context must not direct an error receipt into source files.
    source_roots = [Path(__file__).resolve().parents[2]]
    if os.environ.get("GITHUB_WORKSPACE"):
        source_roots.append(Path(os.environ["GITHUB_WORKSPACE"]).resolve())
    resolved = []
    for path in (output_root, evidence_root):
        if not path.is_absolute():
            raise WorkerError("unsafe-path", "Output and evidence directories must be absolute")
        _no_symlink(path)
        target = path.resolve()
        if target == temporary or not target.is_relative_to(temporary):
            raise WorkerError("unsafe-path", "Worker directories must be strictly inside RUNNER_TEMP")
        if any(target.is_relative_to(root) for root in source_roots):
            raise WorkerError("unsafe-path", "Worker directories must remain outside the source checkout")
        if path.exists():
            raise WorkerError("existing-output", "Worker output and evidence directories must be fresh")
        resolved.append(target)
    output, evidence = resolved
    if output.is_relative_to(evidence) or evidence.is_relative_to(output):
        raise WorkerError("unsafe-path", "Output and evidence directories must be independent")
    evidence.mkdir(parents=True, exist_ok=False)
    # Keep the receipt directory available if creation of the separate run root fails.
    return output, evidence, temporary


def _git(workspace: Path, arguments: list[str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(workspace), *arguments], capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkerError("checkout-unverified", "The checked-out source revision could not be verified") from exc
    if completed.returncode:
        raise WorkerError("checkout-unverified", "The checked-out source revision could not be verified")
    return completed.stdout


def validate_hosted_context(*, require_orca_license: bool = True) -> tuple[dict[str, Any], Path]:
    """Validate only the specifically supported private, default-branch dispatch."""
    required = {
        "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64",
        "GITHUB_SERVER_URL": "https://github.com",
    }
    if require_orca_license:
        required["ORCA_CLOUD_LICENSE_CONFIRMED"] = "true"
    for name, expected in required.items():
        if os.environ.get(name) != expected:
            raise WorkerError("unsupported-runner-context", f"Required hosted execution gate is not satisfied: {name}")
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise WorkerError("unsupported-platform", "The worker requires Linux x86-64")
    repository = _required("GITHUB_REPOSITORY", r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
    run_id = _required("GITHUB_RUN_ID", r"[1-9][0-9]*")
    run_attempt = _required("GITHUB_RUN_ATTEMPT", r"[1-9][0-9]*")
    source_sha = _required("GITHUB_SHA", r"[0-9a-f]{40}")
    workflow_sha = _required("GITHUB_WORKFLOW_SHA", r"[0-9a-f]{40}")
    job = _required("GITHUB_JOB", r"[A-Za-z_][A-Za-z0-9_-]*")
    workspace = _absolute_directory(os.environ.get("GITHUB_WORKSPACE", ""), "GITHUB_WORKSPACE")
    event_path = Path(os.environ.get("GITHUB_EVENT_PATH", ""))
    if not event_path.is_absolute() or not event_path.is_file() or event_path.stat().st_size > 2_000_000:
        raise WorkerError("invalid-event", "A bounded GitHub workflow event file is required")
    _no_symlink(event_path)
    try:
        event = json.loads(event_path.read_text(encoding="utf-8"))
        event_repository = event["repository"]
        branch = event_repository["default_branch"]
        if event_repository["private"] is not True or event_repository["full_name"] != repository:
            raise ValueError
        if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9_.\-/]+", branch):
            raise ValueError
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise WorkerError("invalid-event", "The event must identify the same private repository and its default branch") from exc
    expected_ref = f"refs/heads/{branch}"
    if os.environ.get("GITHUB_REF") != expected_ref or source_sha != workflow_sha:
        raise WorkerError("revision-mismatch", "Dispatch must use the reviewed default branch and matching workflow/source revisions")
    head = _git(workspace, ["rev-parse", "HEAD"]).decode("ascii", errors="replace").strip()
    if head != source_sha:
        raise WorkerError("revision-mismatch", "Checkout HEAD does not match the dispatched source revision")
    if _git(workspace, ["status", "--porcelain", "--untracked-files=no"]).strip():
        raise WorkerError("dirty-checkout", "Tracked source files differ from the reviewed checkout")
    return {
        "provider": "github-actions", "runner_environment": "github-hosted",
        "event_name": "workflow_dispatch", "repository": repository, "repository_private": True,
        "ref": expected_ref, "run_id": run_id, "run_attempt": int(run_attempt), "job": job,
        "source_sha": source_sha, "workflow_sha": workflow_sha, "checkout_sha": head,
        "server_url": "https://github.com",
        "run_url": f"https://github.com/{repository}/actions/runs/{run_id}",
        "runner_os": "Linux", "runner_arch": "X64", "actual_platform": platform.platform(),
        "context_scope": "runner-supplied context; verify against the actual hosted job and retrieved artifact",
        "license_attestation": ("operator confirmed; worker does not determine legal eligibility" if require_orca_license
                                else "not required; this request does not use ORCA and no ORCA attestation was checked"),
    }, workspace


def reviewed_request_bytes(path: Path, workspace: Path) -> bytes:
    source = path if path.is_absolute() else workspace / path
    _no_symlink(source)
    source = source.resolve()
    if not source.is_relative_to(workspace) or not source.is_file():
        raise WorkerError("unreviewed-request", "The request must be a tracked file in the reviewed checkout")
    if source.stat().st_size > 1_000_000:
        raise WorkerError("invalid-request", "The reviewed request exceeds the input size limit")
    raw = source.read_bytes()
    relative = source.relative_to(workspace).as_posix()
    committed = _git(workspace, ["show", f"HEAD:{relative}"])
    if raw != committed:
        raise WorkerError("unreviewed-request", "The request bytes differ from the reviewed commit")
    return raw


def validate_smoke_request(raw: bytes) -> RunRequest:
    try:
        request = parse_request_json(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise WorkerError("invalid-request", "The reviewed file is not a valid finite TOPOS request") from exc
    expected = {
        "engine": "orca", "engine_version": EXPECTED_VERSION, "method": "HF-3c", "purpose": "energy",
        "profile_id": "orca-mapping-v4.2", "matrix_revision": "topos-0.1.0-supported-profile-v1",
        "calculation_environment": "local", "device": "cpu", "threads": 1, "n_candidates": 1,
        "search_algorithm": "jiggle-quench",
    }
    if any(getattr(request, name) != value for name, value in expected.items()):
        raise WorkerError("unsupported-request", "The hosted smoke profile requires serial local ORCA 6.1.1 HF-3c energy with the explicit mapping profile")
    if request.budget_seconds > 120 or request.memory_mb > 2048:
        raise WorkerError("unsupported-request", "The hosted smoke request exceeds 120 seconds or 2048 MiB")
    if request.constraints or any(getattr(request, key) is not None for key in ("basis", "auxiliary_basis", "dispersion", "solvent")):
        raise WorkerError("unsupported-request", "The hosted smoke profile requires the unmodified gas-phase native HF-3c recipe")
    molecule = request.molecule
    if (molecule.symbols != ["O", "H", "H"] or molecule.charge != 0 or molecule.multiplicity != 1
            or molecule.isotopes not in ([None, None, None], [16, 1, 1]) or molecule.environment
            or molecule.stereochemistry or len(molecule.fragments) > 1):
        raise WorkerError("unsupported-request", "The initial hosted smoke profile is restricted to neutral singlet water")
    return request


def verified_installation(temporary: Path) -> dict[str, Any]:
    expected_hash = _required("ORCA_611_SHA256", r"[0-9a-fA-F]{64}").lower()
    installation = temporary / INSTALLATION_NAME
    _no_symlink(installation)
    manifest_path = installation / "topos-orca-installation.json"
    try:
        manifest = read_json(confined_file(installation, manifest_path.name))
    except (OSError, ValueError) as exc:
        raise WorkerError("installation-unverified", "The pinned ORCA installation receipt is unavailable") from exc
    if manifest != {"archive_sha256": expected_hash, "expected_version": EXPECTED_VERSION}:
        raise WorkerError("installation-unverified", "The installation receipt does not match the reviewed ORCA archive and version")
    binary = Path(os.environ.get("TOPOS_ORCA_EXECUTABLE", ""))
    if not binary.is_absolute():
        raise WorkerError("binary-unavailable", "TOPOS_ORCA_EXECUTABLE must name an absolute installed ORCA executable")
    _no_symlink(binary)
    if (not binary.is_file() or not stat.S_ISREG(binary.stat().st_mode)
            or not binary.resolve().is_relative_to(installation.resolve())
            or binary.name != "orca" or not os.access(binary, os.X_OK)):
        raise WorkerError("binary-unavailable", "The requested ORCA executable is missing, non-executable, or outside the verified installation")
    return {
        "archive_sha256": expected_hash, "expected_version": EXPECTED_VERSION,
        "executable": str(binary.resolve()), "executable_sha256": file_digest(binary),
        "installation_receipt_sha256": file_digest(manifest_path),
        "observed_version": None,
    }


@contextmanager
def solver_environment(installation: dict[str, Any] | None = None):
    """Avoid handing worker credentials to the licensed solver; not an OS sandbox."""
    previous = dict(os.environ)
    allowed = {
        "PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
        "LD_LIBRARY_PATH", "LIBRARY_PATH", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS", "TOPOS_ORCA_EXECUTABLE",
    }
    try:
        os.environ.clear()
        os.environ.update({name: value for name, value in previous.items() if name in allowed})
        if installation is not None:
            directory = str(Path(installation["executable"]).parent)
            for name in ("PATH", "LD_LIBRARY_PATH"):
                inherited = os.environ.get(name)
                os.environ[name] = directory + (os.pathsep + inherited if inherited else "")
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


@contextmanager
def cancellation_signals(event: Event):
    previous = {}

    def cancel(signum: int, frame: Any) -> None:
        event.set()

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, cancel)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def stage_committed_run(run_dir: Path, evidence_root: Path, request_sha256: str) -> dict[str, Any]:
    """Copy only one verified committed generation and its explicit membership."""
    _no_symlink(run_dir)
    _no_symlink(evidence_root)
    source = RunStore(run_dir)
    target = evidence_root / "run"
    if target.exists():
        raise IntegrityError("Staged evidence already exists")
    temporary = evidence_root / f".pending-{uuid4().hex}"
    temporary.mkdir(exist_ok=False)
    try:
        with source.lock:
            manifest = source.verify()
            record = source.load()
            from topos.cfour_artifacts import validate_scientific_export_membership

            scientific_membership = validate_scientific_export_membership(record, manifest)
            if digest_json(record["request"]) != request_sha256:
                raise IntegrityError("Committed run does not match the reviewed request")
            snapshot_prefix = f"snapshots/{manifest['snapshot_id']}"
            relative_paths = ["CURRENT.json", f"{snapshot_prefix}/manifest.json", f"{snapshot_prefix}/record.h5"]
            relative_paths.extend(f"{snapshot_prefix}/artifacts/{entry['path']}" for entry in manifest["artifacts"])
            for relative in relative_paths:
                original = confined_file(run_dir, relative)
                # Scientific binary data (HDF5/wavefunctions) are valid evidence;
                # installed native executables and archives are not members.
                with original.open("rb") as stream:
                    if stream.read(4) == b"\x7fELF":
                        raise IntegrityError("Native executable cannot be staged as scientific evidence")
                destination = temporary / safe_relative(relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with original.open("rb") as reader, destination.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
            staged = RunStore(temporary)
            if staged.verify() != manifest or staged.load() != record:
                raise IntegrityError("Copied run failed independent membership verification")
            if read_json(source.current) != read_json(staged.current):
                raise IntegrityError("Commit pointer changed while staging evidence")
        temporary.rename(target)
        # Verify the public staging location after the atomic directory rename.
        if RunStore(target).verify() != manifest:
            raise IntegrityError("Published evidence snapshot differs from its verified source")
        return {
            "run_id": record["run_id"], "status": record["status"],
            "validation_status": record["validation_status"],
            "snapshot_id": manifest["snapshot_id"], "record_sha256": manifest["record_sha256"],
            "relative_paths": ["run/" + value for value in relative_paths],
            "scientific_export_membership": scientific_membership,
        }
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def verify_evidence(evidence_root: Path) -> dict[str, Any]:
    inventory = read_json(confined_file(evidence_root, "evidence-inventory.json"))
    if inventory.get("schema_version") != INVENTORY_SCHEMA or not isinstance(inventory.get("files"), list):
        raise IntegrityError("Invalid hosted evidence inventory schema")
    paths = set()
    for entry in inventory["files"]:
        relative = safe_relative(entry["path"])
        if relative in paths or relative == "evidence-inventory.json":
            raise IntegrityError("Duplicate or recursive hosted evidence membership")
        paths.add(relative)
        path = confined_file(evidence_root, relative)
        if path.stat().st_size != entry["size_bytes"] or file_digest(path) != entry["sha256"]:
            raise IntegrityError("Hosted evidence file does not match its inventory")
    actual = {p.relative_to(evidence_root).as_posix() for p in evidence_root.rglob("*") if p.is_file()}
    if actual != paths | {"evidence-inventory.json"}:
        raise IntegrityError("Unexpected or missing hosted evidence files")
    if "worker-receipt.json" not in paths:
        raise IntegrityError("Hosted evidence is missing its worker receipt")
    if "run/CURRENT.json" in paths:
        RunStore(evidence_root / "run").verify()
    return inventory


def _scientific_success(record: RunRecord, installation: dict[str, Any]) -> bool:
    if record.status != "completed" or len(record.attempts) != 1:
        return False
    attempt = record.attempts[0]
    if (attempt.engine != "orca" or attempt.method != "HF-3c" or attempt.engine_version != EXPECTED_VERSION
            or attempt.status != "completed" or attempt.validation_status != "validated-for-protocol"
            or attempt.converged is not True or attempt.metadata.get("execution_kind") != "real"
            or attempt.metadata.get("executable_sha256") != installation["executable_sha256"]
            or not attempt.command or attempt.command[0] != installation["executable"]):
        return False
    energies = [q for q in attempt.quantities if q.name == "electronic_energy"]
    return (len(energies) == 1 and energies[0].units == "hartree"
            and energies[0].validity == "validated-for-protocol" and energies[0].attempt_id == attempt.attempt_id
            and isinstance(energies[0].value, (int, float)) and not isinstance(energies[0].value, bool)
            and math.isfinite(energies[0].value)
            and energies[0].method == "HF-3c" and bool(energies[0].parser)
            and attempt.metadata.get("operation") == "energy"
            and any(a.role == "raw-output" for a in attempt.artifacts) and len(record.candidates) == 1
            and record.candidates[0].status == "eligible"
            and record.candidates[0].attempt_id == attempt.attempt_id
            and record.candidates[0].energy_hartree == energies[0].value)


def run_worker(request_path: Path, output_root: Path, evidence_root: Path) -> tuple[dict[str, Any], int]:
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA, "started_at": utc_now(), "finished_at": None,
        "requested_execution_environment": "github-actions-hosted", "context_verified": False,
        "status": "failed", "validation_status": "not-evaluated", "scientific_success": False,
        "queue_seconds": None, "review_status": "not-performed", "publication_status": "not-performed",
        "request_file_sha256": None, "request_sha256": None, "run": None, "installation": None,
    }
    evidence = None
    output = None
    staged_paths: list[str] = []
    exit_code = 2
    try:
        output, evidence, temporary = _fresh_roots(output_root, evidence_root)
        context, workspace = validate_hosted_context()
        receipt.update(context=context, context_verified=True)
        raw = reviewed_request_bytes(request_path, workspace)
        receipt["request_file_sha256"] = hashlib.sha256(raw).hexdigest()
        request = validate_smoke_request(raw)
        receipt["request_sha256"] = digest_json(request.model_dump(mode="json"))
        (evidence / "reviewed-request.json").write_bytes(raw)
        staged_paths.append("reviewed-request.json")
        installation = verified_installation(temporary)
        receipt["installation"] = installation
        available_mb = psutil.virtual_memory().available // (1024 * 1024)
        if (os.cpu_count() or 0) < 1 or available_mb < request.memory_mb:
            raise WorkerError("resources-unavailable", "The hosted runner lacks the requested serial CPU or available memory")
        receipt["resources"] = {"threads": 1, "memory_mb": request.memory_mb, "budget_seconds": request.budget_seconds,
                                "available_memory_mb": available_mb, "cpu_count": os.cpu_count()}
        output.mkdir(parents=True, exist_ok=False)
        config = SystemConfig(output_root=output, executables={"orca": installation["executable"]},
                              max_threads=1, max_memory_mb=2048)
        event = Event()
        with cancellation_signals(event), solver_environment(installation):
            record = Workflow(output, config=config).run(request, cancel_event=event)
        run_dir = Path(record.metadata["run_dir"])
        if run_dir.parent != output or run_dir.name != record.run_id:
            raise WorkerError("run-identity-mismatch", "Workflow result does not belong to this isolated worker run")
        staged = stage_committed_run(run_dir, evidence, receipt["request_sha256"])
        staged_paths.extend(staged.pop("relative_paths"))
        receipt["run"] = staged
        receipt["status"] = record.status
        receipt["validation_status"] = record.validation_status
        observed = sorted({a.engine_version for a in record.attempts if a.engine_version is not None})
        installation["observed_version"] = observed[0] if len(observed) == 1 else None
        receipt["attempts"] = [{"attempt_id": a.attempt_id, "engine": a.engine, "method": a.method,
                                "engine_version": a.engine_version, "status": a.status,
                                "validation_status": a.validation_status,
                                "execution_kind": a.metadata.get("execution_kind"),
                                "executable_sha256": a.metadata.get("executable_sha256")} for a in record.attempts]
        receipt["scientific_success"] = _scientific_success(record, installation)
        if not receipt["scientific_success"]:
            if receipt["status"] == "completed":
                receipt["status"] = "failed"
            receipt["failure"] = {"code": "scientific-result-incomplete", "message": "The exact requested ORCA calculation lacks completed, converged, verified energy evidence"}
        exit_code = 0 if receipt["scientific_success"] else 3
    except WorkerError as exc:
        receipt["failure"] = {"code": exc.code, "message": str(exc)}
        if exc.code in {"binary-unavailable", "installation-unverified", "resources-unavailable"}:
            receipt["status"] = "unavailable"
        elif exc.code in {"unsupported-request", "unsupported-platform", "unsupported-runner-context"}:
            receipt["status"] = "unsupported"
    except Exception as exc:
        # Never echo a raw engine, URL, request validation, or environment exception.
        receipt["failure"] = {"code": "worker-failure", "message": "Worker execution or evidence verification failed",
                              "exception_type": type(exc).__name__}
        # A fresh output root belongs exclusively to this invocation. Recover only
        # the single explicitly committed child with the same request identity.
        if output is not None and output.exists() and evidence is not None and receipt["request_sha256"]:
            try:
                children = [p for p in output.iterdir() if p.is_dir() and not p.is_symlink()]
                if len(children) == 1 and re.fullmatch(r"run_[0-9a-f]{32}", children[0].name):
                    staged = stage_committed_run(children[0], evidence, receipt["request_sha256"])
                    staged_paths.extend(staged.pop("relative_paths"))
                    receipt["run"] = staged
                    receipt["recovery"] = "last verified committed snapshot; not promoted to scientific success"
            except Exception:
                receipt["recovery"] = "no independently verifiable committed snapshot was staged"
    finally:
        receipt["finished_at"] = utc_now()
        if evidence is not None:
            try:
                atomic_json(evidence / "worker-receipt.json", receipt)
                staged_paths.append("worker-receipt.json")
                entries = []
                for relative in sorted(set(staged_paths)):
                    path = confined_file(evidence, relative)
                    entries.append({"path": relative, "size_bytes": path.stat().st_size, "sha256": file_digest(path)})
                atomic_json(evidence / "evidence-inventory.json", {"schema_version": INVENTORY_SCHEMA, "files": entries})
                verify_evidence(evidence)
            except Exception as exc:
                receipt["scientific_success"] = False
                receipt["status"] = "failed"
                receipt["failure"] = {"code": "evidence-finalization-failed", "message": "The worker receipt or evidence inventory could not be verified",
                                      "exception_type": type(exc).__name__}
                exit_code = 3
                try:
                    atomic_json(evidence / "worker-receipt.json", receipt)
                except Exception:
                    pass
                # A sanitized stdout receipt remains available even on full disk.
    return receipt, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute the reviewed private GitHub-hosted ORCA smoke profile")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    args = parser.parse_args(argv)
    receipt, code = run_worker(args.request, args.output_root, args.evidence_root)
    print(json.dumps(receipt, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
