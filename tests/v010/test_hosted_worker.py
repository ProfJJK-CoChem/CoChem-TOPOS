"""Hosted-worker infrastructure gates; none of these tests execute or simulate ORCA chemistry."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from topos.actions.hosted_worker import (
    WorkerError,
    _scientific_success,
    run_worker,
    solver_environment,
    stage_committed_run,
    validate_hosted_context,
    validate_smoke_request,
    verified_installation,
    verify_evidence,
)
from topos.models import Artifact, RunRecord
from topos.storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest


@contextlib.contextmanager
def _scoped_env(**updates: str | None):
    previous = {key: os.environ.get(key) for key in updates}
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextlib.contextmanager
def _scoped_attr(target, name: str, value):
    previous = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, previous)


def smoke_payload():
    return {
        "molecule": {"symbols": ["O", "H", "H"], "coordinates": [[0, 0, 0], [0.9572, 0, 0], [-0.23999, 0.9273, 0]],
                     "isotopes": [16, 1, 1], "charge": 0, "multiplicity": 1},
        "engine": "orca", "engine_version": "6.1.1", "method": "HF-3c", "purpose": "energy",
        "profile_id": "orca-mapping-v4.2", "calculation_environment": "local",
        "budget_seconds": 120, "n_candidates": 1, "threads": 1, "memory_mb": 2048, "device": "cpu",
    }


@contextlib.contextmanager
def setup_context(tmp_path, *, raw_request=None):
    """Fabricate runner metadata only to test guard logic; never a remote execution receipt."""
    workspace = tmp_path / "checkout"
    temporary = tmp_path / "runner-temp"
    workspace.mkdir()
    temporary.mkdir()
    raw = json.dumps(smoke_payload()).encode() if raw_request is None else raw_request
    request = workspace / "request.json"
    request.write_bytes(raw)
    commands = [
        ["init", "-q"], ["config", "user.name", "Worker infrastructure test"],
        ["config", "user.email", "infrastructure-test@example.invalid"],
        ["add", "request.json"], ["commit", "-q", "-m", "Infrastructure request fixture"],
    ]
    for command in commands:
        subprocess.run(["git", "-C", str(workspace), *command], check=True, capture_output=True)
    head = subprocess.check_output(["git", "-C", str(workspace), "rev-parse", "HEAD"], text=True).strip()
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"repository": {"private": True, "full_name": "example/private-science", "default_branch": "main"}}))
    values = {
        "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch", "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64", "ORCA_CLOUD_LICENSE_CONFIRMED": "true",
        "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "example/private-science",
        "GITHUB_RUN_ID": "1234", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_SHA": head, "GITHUB_WORKFLOW_SHA": head,
        "GITHUB_JOB": "orca_smoke", "GITHUB_WORKSPACE": str(workspace), "GITHUB_EVENT_PATH": str(event),
        "GITHUB_REF": "refs/heads/main", "RUNNER_TEMP": str(temporary), "ORCA_611_SHA256": "a" * 64,
        "TOPOS_ORCA_EXECUTABLE": str(temporary / "orca-6.1.1" / "orca"),
    }
    with _scoped_env(**values):
        yield workspace, temporary, request


def install_receipt(temporary):
    installation = temporary / "orca-6.1.1"
    installation.mkdir()
    atomic_json(installation / "topos-orca-installation.json", {"archive_sha256": "a" * 64, "expected_version": "6.1.1"})
    return installation


def test_missing_hosted_gate_writes_failure_receipt_without_calculation(tmp_path):
    with setup_context(tmp_path) as (_, temporary, request):
        with _scoped_env(
            GITHUB_ACTIONS=None,
            ORCA_611_ARCHIVE_URL="https://example.invalid/?signed=DO-NOT-PRINT",
        ):
            receipt, code = run_worker(request, temporary / "runs", temporary / "evidence")
    assert code != 0
    assert receipt["context_verified"] is False
    assert receipt["scientific_success"] is False
    assert receipt["run"] is None
    assert "DO-NOT-PRINT" not in json.dumps(receipt)
    assert not (temporary / "runs").exists()
    inventory = verify_evidence(temporary / "evidence")
    assert [entry["path"] for entry in inventory["files"]] == ["worker-receipt.json"]


@pytest.mark.parametrize("variable,value", [
    ("GITHUB_EVENT_NAME", "pull_request"), ("RUNNER_ENVIRONMENT", "self-hosted"),
    ("GITHUB_REF", "refs/heads/unreviewed"), ("ORCA_CLOUD_LICENSE_CONFIRMED", "false"),
    ("GITHUB_WORKFLOW_SHA", "b" * 40), ("GITHUB_SHA", "c" * 40),
])
def test_context_rejects_wrong_event_host_license_or_source(tmp_path, variable, value):
    with setup_context(tmp_path), _scoped_env(**{variable: value}):
        with pytest.raises(WorkerError):
            validate_hosted_context()


def test_context_attestation_distinguishes_licensed_and_free_requests(tmp_path):
    with setup_context(tmp_path):
        licensed, _ = validate_hosted_context(require_orca_license=True)
        assert licensed["license_attestation"] == "operator confirmed; worker does not determine legal eligibility"
        with _scoped_env(ORCA_CLOUD_LICENSE_CONFIRMED=None):
            free, _ = validate_hosted_context(require_orca_license=False)
            assert free["license_attestation"] == "not required; this request does not use ORCA and no ORCA attestation was checked"
            with pytest.raises(WorkerError, match="ORCA_CLOUD_LICENSE_CONFIRMED"):
                validate_hosted_context(require_orca_license=True)


def test_public_repository_and_changed_checkout_are_rejected(tmp_path):
    with setup_context(tmp_path) as (_, _, request):
        event = Path(os.environ["GITHUB_EVENT_PATH"])
        payload = json.loads(event.read_text())
        payload["repository"]["private"] = False
        event.write_text(json.dumps(payload))
        with pytest.raises(WorkerError, match="private repository"):
            validate_hosted_context()
        payload["repository"]["private"] = True
        event.write_text(json.dumps(payload))
        request.write_text("changed after reviewed commit")
        with pytest.raises(WorkerError, match="Tracked source"):
            validate_hosted_context()


def test_malformed_reviewed_request_hashes_input_but_never_claims_engine_success(tmp_path):
    malformed = b'{"method":"DO-NOT-PRINT", broken-json}'
    with setup_context(tmp_path, raw_request=malformed) as (_, temporary, request):
        receipt, code = run_worker(request, temporary / "runs", temporary / "evidence")
    assert code != 0 and receipt["scientific_success"] is False
    assert receipt["request_file_sha256"] == hashlib.sha256(malformed).hexdigest()
    assert receipt["failure"]["code"] == "invalid-request"
    assert "DO-NOT-PRINT" not in json.dumps(receipt)
    assert receipt["installation"] is None and receipt["run"] is None
    assert not (temporary / "evidence" / "reviewed-request.json").exists()
    verify_evidence(temporary / "evidence")


@pytest.mark.parametrize("changes", [
    {"engine_version": "6.0.1"}, {"method": "r2SCAN-3c"}, {"threads": 2},
    {"budget_seconds": 121}, {"memory_mb": 2049}, {"purpose": "optimize"},
    {"calculation_environment": "github-actions"}, {"device": "cuda"}, {"n_candidates": 2},
])
def test_smoke_request_requires_exact_scientific_and_resource_profile(changes):
    payload = {**smoke_payload(), **changes}
    with pytest.raises(WorkerError, match="hosted smoke"):
        validate_smoke_request(json.dumps(payload).encode())


def test_missing_binary_has_verified_failure_receipt_and_no_fake_run(tmp_path):
    with setup_context(tmp_path) as (_, temporary, request):
        install_receipt(temporary)
        receipt, code = run_worker(request, temporary / "runs", temporary / "evidence")
    assert code != 0 and receipt["scientific_success"] is False
    assert receipt["status"] == "unavailable"
    assert receipt["failure"]["code"] == "binary-unavailable"
    assert receipt["run"] is None
    assert receipt["request_sha256"] is not None
    assert not (temporary / "runs").exists()
    verify_evidence(temporary / "evidence")


def test_archive_receipt_mismatch_rejects_before_any_binary_execution(tmp_path):
    with setup_context(tmp_path) as (_, temporary, _):
        install_receipt(temporary)
        with _scoped_env(ORCA_611_SHA256="b" * 64):
            with pytest.raises(WorkerError, match="reviewed ORCA archive"):
                verified_installation(temporary)


def test_worker_roots_must_be_fresh_confined_and_outside_checkout(tmp_path):
    with setup_context(tmp_path) as (workspace, temporary, request):
        for output in (workspace / "outputs", tmp_path / "escaped", temporary):
            receipt, code = run_worker(request, output, temporary / "evidence")
            assert code != 0 and receipt["failure"]["code"] == "unsafe-path"
        existing = temporary / "existing"
        existing.mkdir()
        receipt, code = run_worker(request, existing, temporary / "evidence")
        assert code != 0 and receipt["failure"]["code"] == "existing-output"
        link = temporary / "link"
        link.symlink_to(workspace, target_is_directory=True)
        receipt, code = run_worker(request, link / "outputs", temporary / "evidence")
        assert code != 0 and receipt["failure"]["code"] == "unsafe-path"


def committed_failure(tmp_path):
    request = validate_smoke_request(json.dumps(smoke_payload()).encode())
    record = RunRecord(request=request, status="unavailable", metadata={"failure": "Infrastructure fixture; no chemistry executed"})
    root = tmp_path / record.run_id
    root.mkdir()
    input_path = root / "input.json"
    input_path.write_text(json.dumps(request.model_dump(mode="json")))
    record.artifacts = [Artifact(path="input.json", size_bytes=input_path.stat().st_size,
                                 sha256=file_digest(input_path), role="request")]
    RunStore(root).commit(record)
    return root, record


def test_staging_preserves_committed_identity_and_excludes_unlisted_files(tmp_path):
    run_dir, record = committed_failure(tmp_path)
    (run_dir / "orca-binary-unlisted").write_bytes(b"\x7fELFnot-scientific-evidence")
    (run_dir / "unlisted-secret.txt").write_text("DO-NOT-COPY")
    destination = tmp_path / "evidence"
    destination.mkdir()
    staged = stage_committed_run(run_dir, destination, digest_json(record.request.model_dump(mode="json")))
    assert staged["run_id"] == record.run_id
    assert RunStore(destination / "run").load() == record.model_dump(mode="json")
    assert set(staged["relative_paths"]) == {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
    assert not list(destination.rglob("unlisted-secret.txt"))
    assert not list(destination.rglob("orca-binary-unlisted"))
    assert _scientific_success(record, {}) is False


def test_staging_rejects_request_identity_mismatch_and_snapshot_tampering(tmp_path):
    run_dir, record = committed_failure(tmp_path)
    destination = tmp_path / "evidence"
    destination.mkdir()
    with pytest.raises(IntegrityError, match="reviewed request"):
        stage_committed_run(run_dir, destination, "b" * 64)
    assert not list(destination.iterdir())
    snapshot = RunStore(run_dir).snapshot_path()
    (snapshot / "artifacts/input.json").write_text("tampered")
    with pytest.raises(IntegrityError, match="checksum"):
        stage_committed_run(run_dir, destination, digest_json(record.request.model_dump(mode="json")))
    assert not list(destination.iterdir())


def test_evidence_inventory_detects_later_corruption(tmp_path):
    with setup_context(tmp_path) as (_, temporary, request), _scoped_env(GITHUB_ACTIONS=None):
        run_worker(request, temporary / "runs", temporary / "evidence")
    receipt_path = temporary / "evidence/worker-receipt.json"
    receipt_path.write_text("{}")
    with pytest.raises(IntegrityError, match="inventory"):
        verify_evidence(temporary / "evidence")


def test_solver_environment_excludes_worker_credentials_and_restores_after_error():
    with _scoped_env(
        GITHUB_TOKEN="TEST-TOKEN-FIXTURE",
        ACTIONS_RUNTIME_TOKEN="TEST-RUNTIME-FIXTURE",
        ORCA_611_ARCHIVE_URL="https://example.invalid/signed-secret",
        CUSTOM_PASSWORD="TEST-PASSWORD-FIXTURE",
    ):
        path = os.environ["PATH"]
        with pytest.raises(RuntimeError, match="test interruption"):
            with solver_environment():
                assert os.environ["PATH"] == path
                assert "GITHUB_TOKEN" not in os.environ
                assert "ACTIONS_RUNTIME_TOKEN" not in os.environ
                assert "ORCA_611_ARCHIVE_URL" not in os.environ
                assert "CUSTOM_PASSWORD" not in os.environ
                raise RuntimeError("test interruption")
        assert os.environ["GITHUB_TOKEN"] == "TEST-TOKEN-FIXTURE"
        assert os.environ["ACTIONS_RUNTIME_TOKEN"] == "TEST-RUNTIME-FIXTURE"


def test_solver_environment_prepends_verified_installation_helpers(tmp_path):
    directory = tmp_path / "verified-orca"
    directory.mkdir()
    with _scoped_env(PATH="/usr/bin", LD_LIBRARY_PATH="/approved/runtime/lib"):
        with solver_environment({"executable": str(directory / "orca")}):
            assert os.environ["PATH"] == f"{directory}:/usr/bin"
            assert os.environ["LD_LIBRARY_PATH"] == f"{directory}:/approved/runtime/lib"
        assert os.environ["PATH"] == "/usr/bin"
        assert os.environ["LD_LIBRARY_PATH"] == "/approved/runtime/lib"


def test_evidence_finalization_failure_cannot_leave_success_claim_in_receipt(tmp_path):
    import topos.actions.hosted_worker as worker

    def reject_inventory(root):
        raise IntegrityError("forced infrastructure finalization failure")

    with setup_context(tmp_path) as (_, temporary, request), _scoped_env(
        GITHUB_ACTIONS=None
    ), _scoped_attr(worker, "verify_evidence", reject_inventory):
        receipt, code = run_worker(request, temporary / "runs", temporary / "evidence")
    assert code != 0
    saved = json.loads((temporary / "evidence/worker-receipt.json").read_text())
    assert saved == receipt
    assert saved["scientific_success"] is False and saved["status"] == "failed"
    assert saved["failure"]["code"] == "evidence-finalization-failed"
