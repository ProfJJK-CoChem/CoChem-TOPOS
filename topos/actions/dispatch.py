"""Correlated GitHub Actions execution and verified TOPOS result retrieval.

An accepted HTTP submission is never scientific completion: completion requires
an authenticated, correlated worker receipt and verified RunStore snapshot.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Timer
from typing import Any
from uuid import uuid4

from ..config import DEFAULT_REMOTE_BASE_COMMIT

REMOTE_UNAVAILABLE = (
    "Remote calculation requires an explicit private controller repository, "
    "its TOPOS compute workflow, and a credential with Actions access. "
    "No local calculation was substituted."
)
WORKFLOW = "topos_compute.yml"
MAX_REQUEST_BYTES = 37_500
MAX_ARCHIVE_BYTES = 512 * 1024**2
MAX_EXPANDED_BYTES = 2 * 1024**3


class RemoteExecutionError(RuntimeError):
    """Submission, correlation, or retrieved evidence could not be established."""


@dataclass(frozen=True)
class DispatchResult:
    dispatch_id: str
    workflow_name: str
    target_repo: str | None
    inputs: dict[str, Any]
    ref: str
    status: str = "unavailable"
    validation_status: str = "not-evaluated"
    auth_source: str = "not-requested"
    payload_path: str | None = None
    remote_job_id: str | None = None
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: str = REMOTE_UNAVAILABLE
    request_sha256: str | None = None
    commit_sha: str | None = None
    base_commit: str | None = None
    controller_profile: str = "free"
    github_created_at: str | None = None
    artifact_path: str | None = None
    record: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _without_credentials(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if re.search(
            r"token|password|secret|credential|authorization", str(key), re.I,
        ) else _without_credentials(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_without_credentials(item) for item in value]
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _GitHubTransport:
    """Fixed-origin transport; errors never include credentials or signed URLs."""

    def __init__(self, token: str):
        if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise RemoteExecutionError("Invalid GitHub credential")
        self._token = token

    def __repr__(self):
        return "<GitHubTransport credential redacted>"

    def request(self, method: str, path: str, payload: Any = None) -> Any:
        if not path.startswith("/repos/") or "\n" in path or "\r" in path:
            raise RemoteExecutionError("Invalid GitHub REST path")
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "CoChem-TOPOS/0.1.0"}
        data = None if payload is None else _canonical(payload)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request("https://api.github.com" + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=30) as response:
                content = response.read(4 * 1024**2 + 1)
                if len(content) > 4 * 1024**2:
                    raise RemoteExecutionError("GitHub REST response exceeds its size limit")
                value = json.loads(content) if content else {}
                if not isinstance(value, dict):
                    raise RemoteExecutionError("GitHub REST endpoint returned an unexpected response structure")
                return value
        except urllib.error.HTTPError as exc:
            raise RemoteExecutionError(f"GitHub REST request failed (HTTP {exc.code})") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise RemoteExecutionError("GitHub REST endpoint is unavailable or returned invalid JSON") from None

    def download(self, path: str) -> bytes:
        if not re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/artifacts/[1-9][0-9]*/zip", path):
            raise RemoteExecutionError("Invalid artifact download endpoint")
        request = urllib.request.Request("https://api.github.com" + path, headers={
            "Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "CoChem-TOPOS/0.1.0",
        })
        try:
            try:
                response = urllib.request.build_opener(_NoRedirect()).open(request, timeout=30)
            except urllib.error.HTTPError as exc:
                if exc.code != 302:
                    raise RemoteExecutionError(f"Artifact download failed (HTTP {exc.code})") from None
                locations = exc.headers.get_all("Location", [])
                exc.close()
                if len(locations) != 1:
                    raise RemoteExecutionError("Artifact response has ambiguous redirect location") from None
                target = urllib.parse.urlsplit(locations[0])
                hostname = target.hostname or ""
                allowed = hostname.endswith(".blob.core.windows.net") or hostname == "pipelines.actions.githubusercontent.com"
                if (target.scheme != "https" or not allowed or target.port not in (None, 443)
                        or target.username or target.password or target.fragment
                        or any(ord(char) < 33 or ord(char) > 126 for char in locations[0])):
                    raise RemoteExecutionError("Artifact response redirected outside GitHub artifact storage") from None
                response = urllib.request.build_opener(_NoRedirect()).open(
                    urllib.request.Request(locations[0], headers={"User-Agent": "CoChem-TOPOS/0.1.0"}), timeout=30,
                )
            with response:
                chunks, size = [], 0
                started = time.monotonic()
                while True:
                    block = response.read(min(1024**2, MAX_ARCHIVE_BYTES + 1 - size))
                    if not block:
                        break
                    size += len(block)
                    if size > MAX_ARCHIVE_BYTES or time.monotonic() - started > 300:
                        raise RemoteExecutionError("Artifact download exceeds size or time limit")
                    chunks.append(block)
                return b"".join(chunks)
        except RemoteExecutionError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise RemoteExecutionError("Artifact download could not be completed") from None


def _controller_environment() -> dict[str, str]:
    """Select account authentication without reading stored CLI credentials.

    Match BASE's private lifecycle policy: Actions retains its owning-project
    token; Codespaces uses the user's native browser-authenticated gh account
    unless environment authentication was explicitly selected.
    """
    selected = os.environ.copy()
    if selected.get("GITHUB_ACTIONS", "").lower() == "true":
        return selected
    mode = selected.get("COCHEM_PRIVATE_GH_AUTH", "auto")
    if mode not in {"auto", "stored-cli", "environment"}:
        raise RemoteExecutionError("COCHEM_PRIVATE_GH_AUTH must select auto, stored-cli, or environment")
    if mode == "stored-cli" or (mode == "auto" and selected.get("CODESPACES", "").lower() == "true"):
        selected.pop("GH_TOKEN", None)
        selected.pop("GITHUB_TOKEN", None)
    return selected


class _GitHubCLITransport:
    """Bounded fixed-origin gh API transport using native stored account auth.

    Native gh owns its credential store and authenticated redirect behavior. No
    credential is extracted, printed, written to a request file, or forwarded
    to a calculation engine. Artifact endpoints remain fixed to the correlated
    GitHub run and the existing digest/archive verification still applies.
    """

    def __init__(self, environment: dict[str, str]):
        self._environment = dict(environment)
        self._executable = shutil.which("gh", path=environment.get("PATH"))
        if not self._executable:
            raise RemoteExecutionError("No GitHub Actions credential or authenticated native GitHub CLI is configured")
        self._run(["auth", "status", "--hostname", "github.com"], limit=64 * 1024, timeout=10)

    def __repr__(self):
        return "<GitHubCLITransport native stored authentication; credentials not extracted>"

    def _run(self, arguments: list[str], *, data: bytes | None = None,
             limit: int, timeout: float) -> bytes:
        process = None
        timer = None
        try:
            process = subprocess.Popen([self._executable, *arguments],
                                       stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       env=self._environment)
            def expire() -> None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass

            timer = Timer(timeout, expire)
            timer.daemon = True
            timer.start()
            if data is not None:
                if len(data) > 64 * 1024:
                    raise RemoteExecutionError("GitHub CLI request exceeds its bounded input size")
                process.stdin.write(data)
                process.stdin.close()
            chunks, size = [], 0
            while True:
                block = process.stdout.read(min(1024 * 1024, limit + 1 - size))
                if not block:
                    break
                chunks.append(block)
                size += len(block)
                if size > limit:
                    raise RemoteExecutionError("GitHub CLI response exceeds its size limit")
            if process.wait(timeout=1) != 0:
                raise RemoteExecutionError("Native GitHub CLI authentication or API request could not be completed")
            return b"".join(chunks)
        except RemoteExecutionError:
            raise
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise RemoteExecutionError("Native GitHub CLI authentication or API request is unavailable") from None
        finally:
            if timer is not None:
                timer.cancel()
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if process.stdout is not None:
                    process.stdout.close()
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()

    def request(self, method: str, path: str, payload: Any = None) -> Any:
        if (method not in {"GET", "POST"} or not path.startswith("/repos/")
                or any(character in path for character in ("\n", "\r"))):
            raise RemoteExecutionError("Invalid GitHub REST path or method")
        arguments = ["api", "--hostname", "github.com", "--method", method, path,
                     "--header", "Accept: application/vnd.github+json",
                     "--header", "X-GitHub-Api-Version: 2022-11-28"]
        data = None if payload is None else _canonical(payload)
        if data is not None:
            arguments.extend(["--input", "-"])
        raw = self._run(arguments, data=data, limit=4 * 1024**2, timeout=30)
        try:
            value = json.loads(raw) if raw else {}
            if not isinstance(value, dict):
                raise ValueError
            return value
        except ValueError:
            raise RemoteExecutionError("GitHub CLI endpoint returned invalid JSON") from None

    def download(self, path: str) -> bytes:
        if not re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/artifacts/[1-9][0-9]*/zip", path):
            raise RemoteExecutionError("Invalid artifact download endpoint")
        return self._run(["api", "--hostname", "github.com", "--method", "GET", path],
                         limit=MAX_ARCHIVE_BYTES, timeout=300)


def _extract_archive(content: bytes, destination: Path) -> None:
    """Extract regular files only, before publishing any retrieved evidence."""
    from ..storage import safe_relative

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 100_000 or sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES:
                raise RemoteExecutionError("Artifact archive exceeds extraction limits")
            names: set[str] = set()
            for entry in entries:
                name = safe_relative(entry.filename.rstrip("/") if entry.is_dir() else entry.filename)
                if name in names or entry.flag_bits & 1:
                    raise RemoteExecutionError("Duplicate or encrypted artifact archive entry")
                names.add(name)
                mode = (entry.external_attr >> 16) & 0xFFFF
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG):
                    raise RemoteExecutionError("Artifact archive contains a nonregular file")
                target = destination / name
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer, 1024**2)
                if target.stat().st_size != entry.file_size:
                    raise RemoteExecutionError("Artifact archive member has an inconsistent size")
    except RemoteExecutionError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        raise RemoteExecutionError("Artifact archive is invalid or unsafe") from None


class ActionDispatchClient:
    """Private-controller workflow submission, polling, retrieval and cancel."""

    def __init__(self, repo_root: Path | str | None = None, token: str | None = None,
                 target_repo: str | None = None, *, transport: Any = None,
                 base_commit: str | None = None, controller_profile: str | None = None):
        if target_repo is not None and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", target_repo):
            raise ValueError("target_repo must be an explicit GitHub owner/repository")
        self.target_repo = target_repo
        self.base_commit = (base_commit if base_commit is not None else
                            os.environ.get("TOPOS_REMOTE_BASE_COMMIT", DEFAULT_REMOTE_BASE_COMMIT))
        if not isinstance(self.base_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", self.base_commit):
            raise ValueError("base_commit must be an explicit lowercase 40-character BASE Git commit")
        self.controller_profile = (controller_profile if controller_profile is not None else
                                   os.environ.get("TOPOS_REMOTE_CONTROLLER_PROFILE", "free"))
        if self.controller_profile not in {"free", "legacy-topos-orca"}:
            raise ValueError("controller_profile must select free or legacy-topos-orca")
        self._transport = transport or (_GitHubTransport(token) if token else None)

    def _connection(self):
        if self.target_repo is None:
            raise RemoteExecutionError("An explicit private controller repository is required")
        if self._transport is None:
            environment = _controller_environment()
            token = environment.get("GH_TOKEN") or environment.get("GITHUB_TOKEN")
            self._transport = _GitHubTransport(token) if token else _GitHubCLITransport(environment)
        return self._transport

    def dispatch_workflow(self, workflow_name: str = WORKFLOW, inputs: dict[str, Any] | None = None,
                          ref: str = "main") -> DispatchResult:
        if not workflow_name or not ref:
            raise ValueError("workflow_name and ref must not be empty")
        if workflow_name == WORKFLOW and inputs and "molecule" in inputs:
            return self.dispatch_request(inputs, ref=ref)
        return DispatchResult(f"unavailable_{uuid4().hex}", workflow_name, self.target_repo,
                              _without_credentials(inputs or {}), ref)

    def dispatch_request(self, request: Any, *, ref: str = "main") -> DispatchResult:
        from ..models import RunRequest
        from .hosted_requirements import required_native_engines

        validated = RunRequest.model_validate(request).model_dump(mode="json")
        if validated["calculation_environment"] != "github-actions":
            raise ValueError("Remote dispatch requires calculation_environment='github-actions'")
        engines = required_native_engines(validated)
        data = _canonical(validated)
        if len(data) > MAX_REQUEST_BYTES:
            raise ValueError("Request exceeds GitHub Actions input size limit")
        receipt = DispatchResult(f"topos_{uuid4().hex}", WORKFLOW, self.target_repo, validated, ref,
                                 request_sha256=hashlib.sha256(data).hexdigest(), base_commit=self.base_commit,
                                 controller_profile=self.controller_profile)
        if "orca" in engines:
            if self.controller_profile != "legacy-topos-orca":
                return replace(receipt, details="This generic controller is configured for xTB and CREST. "
                               "Export the canonical request and use CoChem-BASE's private TOPOS calculation "
                               "workflow for licensed engines. No calculation was submitted.")
            if self.base_commit != DEFAULT_REMOTE_BASE_COMMIT:
                return replace(receipt, details="The explicit legacy TOPOS ORCA controller requires its "
                               "validated foundation BASE revision. New BASE staged-asset jobs use the "
                               "separate private TOPOS calculation workflow. No calculation was submitted.")
        try:
            connection = self._connection()
            repository = connection.request("GET", f"/repos/{self.target_repo}")
            if repository.get("private") is not True or repository.get("default_branch") != ref:
                raise RemoteExecutionError("Calculation controller must be private and use its default branch")
            commit = connection.request("GET", f"/repos/{self.target_repo}/commits/{urllib.parse.quote(ref, safe='')}")
            sha = commit.get("sha", "")
            if not re.fullmatch(r"[a-f0-9]{40}", sha):
                raise RemoteExecutionError("Controller commit identity is invalid")
            # Persistable ownership must survive an ambiguous POST response:
            # GitHub may have accepted the uniquely correlated job before the
            # transport timed out. Poll this receipt rather than dispatching a
            # second scientific calculation.
            receipt = replace(receipt, commit_sha=sha, auth_source="configured-github-credential")
            try:
                connection.request("POST", f"/repos/{self.target_repo}/actions/workflows/{WORKFLOW}/dispatches", {
                    "ref": ref, "inputs": {"dispatch_id": receipt.dispatch_id,
                        "request_b64": base64.b64encode(data).decode("ascii"), "request_sha256": receipt.request_sha256,
                        "base_commit": receipt.base_commit},
                })
            except RemoteExecutionError as exc:
                return replace(receipt, status="submission-unconfirmed",
                               details="Workflow submission response could not be confirmed; no acceptance or calculation completion is claimed. "
                               "Recover only the same correlation identifier. " + str(exc))
            return replace(receipt, status="submitted", auth_source="configured-github-credential",
                           commit_sha=sha, details="Workflow accepted; calculation completion is not yet established")
        except RemoteExecutionError as exc:
            return replace(receipt, details=str(exc))

    def _check_receipt(self, receipt: DispatchResult) -> None:
        if receipt.target_repo != self.target_repo or receipt.workflow_name != WORKFLOW:
            raise RemoteExecutionError("Dispatch receipt belongs to a different controller or workflow")
        if not re.fullmatch(r"topos_[a-f0-9]{32}", receipt.dispatch_id):
            raise RemoteExecutionError("Invalid dispatch correlation identifier")
        if hashlib.sha256(_canonical(receipt.inputs)).hexdigest() != receipt.request_sha256:
            raise RemoteExecutionError("Dispatch request checksum mismatch")
        if not re.fullmatch(r"[a-f0-9]{40}", receipt.commit_sha or ""):
            raise RemoteExecutionError("Dispatch receipt lacks a pinned controller revision")
        if receipt.base_commit != self.base_commit:
            raise RemoteExecutionError("Dispatch receipt differs from the configured BASE source revision")
        if receipt.controller_profile != self.controller_profile:
            raise RemoteExecutionError("Dispatch receipt differs from the configured controller profile")

    def _same_dispatch(self, run: dict[str, Any], receipt: DispatchResult) -> bool:
        return (isinstance(run, dict) and isinstance(run.get("path"), str)
                and run.get("display_title") == receipt.dispatch_id
                and run.get("event") == "workflow_dispatch"
                and run.get("path", "").split("@", 1)[0] == f".github/workflows/{WORKFLOW}")

    def poll(self, receipt: DispatchResult) -> DispatchResult:
        self._check_receipt(receipt)
        connection = self._connection()
        if receipt.remote_job_id:
            if not re.fullmatch(r"[1-9][0-9]*", receipt.remote_job_id):
                raise RemoteExecutionError("Invalid GitHub run ID")
            run = connection.request("GET", f"/repos/{self.target_repo}/actions/runs/{receipt.remote_job_id}")
            if not self._same_dispatch(run, receipt):
                raise RemoteExecutionError("GitHub run no longer matches the dispatched request")
        else:
            matches = []
            for page in range(1, 11):
                payload = connection.request("GET", f"/repos/{self.target_repo}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&per_page=100&page={page}")
                runs = payload.get("workflow_runs", [])
                matches.extend(run for run in runs if self._same_dispatch(run, receipt))
                if len(runs) < 100:
                    break
            if not matches:
                return replace(receipt, status="submitted", details="Awaiting a run matching request and controller revision")
            if len(matches) != 1:
                raise RemoteExecutionError("Multiple GitHub runs match the same dispatch identifier")
            run = matches[0]
        run_id = str(run.get("id", ""))
        if not re.fullmatch(r"[1-9][0-9]*", run_id):
            raise RemoteExecutionError("GitHub returned an invalid run identity")
        if run.get("head_sha") != receipt.commit_sha:
            # workflow_dispatch accepts a mutable branch. A push between the
            # HEAD lookup and dispatch must not hide our uniquely identified
            # job from cancellation or authorize results from its new revision.
            detail = "The owned workflow already ended; its results are rejected"
            if run.get("status") != "completed":
                try:
                    connection.request("POST", f"/repos/{self.target_repo}/actions/runs/{run_id}/cancel")
                    detail = "Cancellation requested; termination is not yet confirmed"
                except RemoteExecutionError as exc:
                    detail = f"Cancellation could not be submitted: {exc}"
            raise RemoteExecutionError(f"Owned GitHub run {run_id} used an unexpected controller revision. {detail}")
        created_at = run.get("created_at")
        if receipt.inputs.get("include_queue_in_budget"):
            from .queue_budget import utc_timestamp
            try:
                utc_timestamp(created_at)
            except ValueError as exc:
                raise RemoteExecutionError("GitHub run lacks a valid server creation timestamp") from exc
            if receipt.github_created_at is not None and receipt.github_created_at != created_at:
                raise RemoteExecutionError("GitHub workflow creation timestamp changed")
        status = "awaiting-retrieval" if run.get("status") == "completed" else "running"
        return replace(receipt, remote_job_id=run_id, github_created_at=created_at, status=status,
                       details=f"GitHub workflow {run.get('status')}; conclusion {run.get('conclusion')}; result not yet verified")

    def cancel(self, receipt: DispatchResult) -> DispatchResult:
        updated = self.poll(receipt)
        if updated.remote_job_id is None:
            return replace(updated, details="Run has not appeared yet; cancellation is not confirmed")
        if updated.status == "awaiting-retrieval":
            return replace(updated, details="Workflow already ended; retrieve its actual result")
        self._connection().request("POST", f"/repos/{self.target_repo}/actions/runs/{updated.remote_job_id}/cancel")
        return replace(updated, status="cancellation-requested", details="Cancellation submitted; process termination is not yet confirmed")

    def retrieve_result(self, receipt: DispatchResult, destination: str | Path) -> DispatchResult:
        updated = self.poll(receipt)
        if updated.status != "awaiting-retrieval" or updated.remote_job_id is None:
            raise RemoteExecutionError("Workflow has not completed; evidence cannot be retrieved")
        connection = self._connection()
        matches = []
        for page in range(1, 11):
            payload = connection.request("GET", f"/repos/{self.target_repo}/actions/runs/{updated.remote_job_id}/artifacts?per_page=100&page={page}")
            artifacts = payload.get("artifacts", [])
            matches.extend(item for item in artifacts if item.get("name") == f"topos-evidence-{updated.dispatch_id}")
            if len(artifacts) < 100:
                break
        if len(matches) != 1 or matches[0].get("expired") is not False:
            raise RemoteExecutionError("Exactly one unexpired correlated evidence artifact is required")
        artifact = matches[0]
        run = artifact.get("workflow_run", {})
        if str(run.get("id")) != updated.remote_job_id or run.get("head_sha") != updated.commit_sha:
            raise RemoteExecutionError("Artifact belongs to a different GitHub run or controller revision")
        artifact_id = str(artifact.get("id", ""))
        if not re.fullmatch(r"[1-9][0-9]*", artifact_id):
            raise RemoteExecutionError("Invalid evidence artifact identity")
        if not isinstance(artifact.get("size_in_bytes"), int) or not 0 < artifact["size_in_bytes"] <= MAX_ARCHIVE_BYTES:
            raise RemoteExecutionError("Evidence artifact exceeds download size limit")
        content = connection.download(f"/repos/{self.target_repo}/actions/artifacts/{artifact_id}/zip")
        if len(content) > MAX_ARCHIVE_BYTES:
            raise RemoteExecutionError("Evidence artifact exceeds download size limit")
        digest = artifact.get("digest")
        if digest is not None and digest != "sha256:" + hashlib.sha256(content).hexdigest():
            raise RemoteExecutionError("Downloaded evidence differs from the GitHub artifact digest")
        target = Path(destination).expanduser().absolute()
        if target.exists() or target.is_symlink():
            raise FileExistsError("Evidence destination already exists; choose a fresh location")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".topos-download-", dir=target.parent))
        try:
            _extract_archive(content, staging)
            from ..storage import RunStore, read_json
            from .hosted_worker import verify_evidence

            if {path.name for path in staging.iterdir()} != {"run", "worker-receipt.json", "evidence-inventory.json"}:
                raise RemoteExecutionError("Unexpected worker evidence root membership")
            verify_evidence(staging)
            worker = read_json(staging / "worker-receipt.json")
            if worker.get("schema_version") != "topos-compute-worker/0.1.0" or worker.get("context_verified") is not True:
                raise RemoteExecutionError("Worker execution context has not been verified")
            for key, expected in (("dispatch_id", updated.dispatch_id), ("request_sha256", updated.request_sha256),
                                  ("request", updated.inputs), ("github_run_id", updated.remote_job_id),
                                  ("github_sha", updated.commit_sha), ("base_commit", updated.base_commit),
                                  ("run_path", "run")):
                if worker.get(key) != expected:
                    raise RemoteExecutionError(f"Worker receipt mismatch: {key}")
            store = RunStore(staging / "run")
            manifest = store.verify()
            record = store.load()
            base_source = worker.get("base_source")
            if (not isinstance(base_source, dict) or base_source.get("commit_sha") != updated.base_commit
                    or base_source.get("checked_out_source_verified") is not True
                    or record.get("metadata", {}).get("hosted_base_source") != base_source):
                raise RemoteExecutionError("Worker BASE source identity lacks its bound checkout and run evidence")
            if worker.get("status") != record.get("status"):
                raise RemoteExecutionError("Worker receipt and immutable run status disagree")
            actual_request = dict(record["request"])
            from .queue_budget import verify_queue_record
            expected_request = verify_queue_record(updated.inputs, record, worker.get("budget_accounting"),
                                                   updated.github_created_at)
            if actual_request != expected_request:
                raise RemoteExecutionError("Retrieved scientific run used a different request")
            if worker.get("local_request_sha256") != hashlib.sha256(_canonical(actual_request)).hexdigest():
                raise RemoteExecutionError("Worker local request digest mismatch")
            for key in ("run_id", "snapshot_id", "record_sha256"):
                if worker.get("run", {}).get(key) != manifest[key]:
                    raise RemoteExecutionError("Worker receipt does not identify the retrieved snapshot")
            staging.rename(target)
            return replace(updated, status=record["status"], validation_status=record["validation_status"],
                           artifact_path=str(target), record=record,
                           details="Retrieved correlated, checksum-verified worker evidence")
        except RemoteExecutionError:
            raise
        except (OSError, ValueError, KeyError) as exc:
            raise RemoteExecutionError("Retrieved worker evidence failed structural or checksum validation") from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def wait_for_result(self, receipt: DispatchResult, destination: str | Path, *,
                        timeout_seconds: float = 3600, poll_interval: float = 5,
                        cancel_event: Event | None = None) -> DispatchResult:
        if not all(math.isfinite(value) and value > 0 for value in (timeout_seconds, poll_interval)):
            raise ValueError("Polling budget and interval must be finite and positive")
        deadline = time.monotonic() + timeout_seconds
        current = receipt
        while time.monotonic() < deadline:
            current = self.poll(current)
            if current.status == "awaiting-retrieval":
                return self.retrieve_result(current, destination)
            if cancel_event is not None and cancel_event.is_set():
                current = self.cancel(current)
                if current.remote_job_id is not None:
                    return current
                # Dispatch can be accepted before the run-list index catches
                # up. Keep looking for the owned run so a cancellation request
                # is not silently abandoned during this propagation window.
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        if current.remote_job_id:
            current = self.cancel(current)
        return replace(current, status="polling-timed-out", details="Client polling budget expired; no completed calculation is claimed. " + current.details)
