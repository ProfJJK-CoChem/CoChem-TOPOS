"""Hosted request/receipt guards; runner metadata fixtures are not remote evidence."""
import base64
import json
import os
from pathlib import Path

import pytest
from test_hosted_worker import setup_context, smoke_payload

from topos.actions.compute_worker import decode_request, run_compute_worker
from topos.actions.hosted_requirements import main as preflight_main
from topos.actions.hosted_requirements import required_native_engines, validate_submission
from topos.actions.hosted_worker import verify_evidence
from topos.models import RunRequest
from topos.storage import digest_json, json_bytes


def encoded_request(**changes):
    data = RunRequest.model_validate({**smoke_payload(), "calculation_environment": "github-actions", **changes}).model_dump(mode="json")
    return data, base64.b64encode(json_bytes(data)).decode(), digest_json(data)


def test_worker_preserves_original_and_explicitly_localizes_only_execution():
    original, encoded, digest = encoded_request()
    restored, local = decode_request(encoded, digest)
    assert restored == original
    assert local.model_dump(mode="json") == {**original, "calculation_environment": "local"}
    assert digest_json(local.model_dump(mode="json")) != digest


@pytest.mark.parametrize("changes", [{"budget_seconds": 14401}, {"threads": 5}, {"memory_mb": 13000},
                                     {"calculation_environment": "local"}])
def test_worker_rejects_out_of_contract_requests(changes):
    _, encoded, digest = encoded_request(**changes)
    with pytest.raises(ValueError):
        decode_request(encoded, digest)


def test_worker_rejects_changed_hash_omitted_defaults_and_oversize():
    _, encoded, digest = encoded_request()
    for raw, sha in ((encoded, "0" * 64), ("A" * 50001, digest),
                     (base64.b64encode(json_bytes(smoke_payload())).decode(), digest_json(smoke_payload()))):
        with pytest.raises(ValueError):
            decode_request(raw, sha)


def test_event_mismatch_leaves_verified_failure_without_engine_execution(tmp_path, monkeypatch):
    _, temporary, _ = setup_context(tmp_path, monkeypatch)
    _, encoded, digest = encoded_request()
    receipt, code = run_compute_worker(encoded, digest, "topos_" + "a" * 32,
                                      temporary / "runs", temporary / "evidence")
    assert code != 0 and receipt["status"] == "failed" and receipt["run_path"] is None
    assert "differs from" in receipt["failure"]["message"]
    assert not (temporary / "runs").exists()
    verify_evidence(temporary / "evidence")


def test_free_request_has_no_orca_license_gate_but_still_requires_base(tmp_path, monkeypatch):
    _, temporary, _ = setup_context(tmp_path, monkeypatch)
    monkeypatch.delenv("ORCA_CLOUD_LICENSE_CONFIRMED")
    monkeypatch.delenv("COCHEM_CONFIG", raising=False)
    _, encoded, digest = encoded_request(engine="xtb", engine_version="6.7.1", method="GFN2-xTB", profile_id="screening-v1")
    dispatch_id = "topos_" + "b" * 32
    event = Path(os.environ["GITHUB_EVENT_PATH"])
    data = json.loads(event.read_text())
    data["inputs"] = {"dispatch_id": dispatch_id, "request_b64": encoded, "request_sha256": digest}
    event.write_text(json.dumps(data))
    receipt, code = run_compute_worker(encoded, digest, dispatch_id, temporary / "runs", temporary / "evidence")
    assert code != 0 and receipt["context_verified"]
    assert "BASE setup registry" in receipt["failure"]["message"]
    assert not (temporary / "runs").exists()
    verify_evidence(temporary / "evidence")


@pytest.mark.parametrize("row", ["T1-10s", "T1-1h", "T2-10s", "T3O-10s", "T5-10s"])
def test_free_matrix_recipe_derives_requirements_from_actual_plan(row):
    # The matrix resolves its own engines, independently of the primitive default.
    original, encoded, digest = encoded_request(purpose="matrix", matrix_row_id=row)
    assert "orca" not in required_native_engines(original)
    assert validate_submission(encoded, digest, "topos_" + "c" * 32)["requires_orca"] is False
    assert decode_request(encoded, digest)[0] == original


@pytest.mark.parametrize("row", ["T1-1min", "T1-3h", "T1-12h", "T1-3d", "T2-30min", "T3O-3h", "T5-1h"])
def test_licensed_matrix_recipe_derives_orca_from_native_plan(row):
    original, encoded, digest = encoded_request(engine="xtb", purpose="matrix", matrix_row_id=row)
    assert "orca" in required_native_engines(original)
    assert validate_submission(encoded, digest, "topos_" + "c" * 32)["requires_orca"] is True
    assert decode_request(encoded, digest)[0] == original


@pytest.mark.parametrize("row", ["T1-30min", "T4O-1h", "T999-10s", None])
def test_unknown_or_unsupported_hosted_matrix_row_cannot_reach_provisioning(row):
    # Registered ML recipes still need an installer the hosted worker supports;
    # TORQ-owned and unknown rows cannot use the TOPOS native-engine provisioner.
    _, encoded, digest = encoded_request(purpose="matrix", matrix_row_id=row)
    with pytest.raises(ValueError):
        validate_submission(encoded, digest, "topos_" + "c" * 32)
    with pytest.raises(ValueError):
        decode_request(encoded, digest)


def test_shared_preflight_cli_allows_free_matrix_without_license_and_gates_orca(tmp_path, monkeypatch):
    _, encoded, digest = encoded_request(purpose="matrix", matrix_row_id="T3O-10s")
    monkeypatch.setenv("TOPOS_REQUEST_B64", encoded)
    monkeypatch.setenv("TOPOS_REQUEST_SHA256", digest)
    monkeypatch.setenv("TOPOS_DISPATCH_ID", "topos_" + "d" * 32)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    monkeypatch.delenv("ORCA_CLOUD_LICENSE_CONFIRMED", raising=False)
    preflight_main()
    assert (tmp_path / "outputs").read_text() == "licensed=false\n"
    _, encoded, digest = encoded_request(purpose="matrix", matrix_row_id="T5-1h")
    monkeypatch.setenv("TOPOS_REQUEST_B64", encoded)
    monkeypatch.setenv("TOPOS_REQUEST_SHA256", digest)
    with pytest.raises(ValueError, match="ORCA cloud"):
        preflight_main()
    assert (tmp_path / "outputs").read_text() == "licensed=false\n"


def test_free_matrix_worker_does_not_require_orca_license(tmp_path, monkeypatch):
    _, temporary, _ = setup_context(tmp_path, monkeypatch)
    monkeypatch.delenv("ORCA_CLOUD_LICENSE_CONFIRMED")
    monkeypatch.delenv("COCHEM_CONFIG", raising=False)
    _, encoded, digest = encoded_request(purpose="matrix", matrix_row_id="T3O-10s")
    dispatch_id = "topos_" + "e" * 32
    event = Path(os.environ["GITHUB_EVENT_PATH"])
    payload = json.loads(event.read_text())
    payload["inputs"] = {"dispatch_id": dispatch_id, "request_b64": encoded, "request_sha256": digest}
    event.write_text(json.dumps(payload))
    receipt, code = run_compute_worker(encoded, digest, dispatch_id, temporary / "runs", temporary / "evidence")
    assert code != 0 and receipt["context_verified"]
    assert "BASE setup registry" in receipt["failure"]["message"]


def test_expired_queue_budget_commits_no_attempt_without_constructing_workflow(tmp_path, monkeypatch):
    from topos.actions.dispatch import _GitHubTransport
    from topos.storage import RunStore

    _, temporary, _ = setup_context(tmp_path, monkeypatch)
    _, encoded, digest = encoded_request(include_queue_in_budget=True, budget_seconds=1,
                                         engine="xtb", engine_version="6.7.1", method="GFN2-xTB", profile_id="screening-v1")
    dispatch_id = "topos_" + "f" * 32
    event_path = Path(os.environ["GITHUB_EVENT_PATH"])
    event = json.loads(event_path.read_text())
    event["inputs"] = {"dispatch_id": dispatch_id, "request_b64": encoded, "request_sha256": digest}
    event_path.write_text(json.dumps(event))
    registry = temporary / "unread-registry.json"
    registry.write_text("{}")
    monkeypatch.setenv("COCHEM_CONFIG", str(registry))
    monkeypatch.setenv("GITHUB_TOKEN", "infrastructure-test-only")
    server_run = {"id": 1234, "head_sha": os.environ["GITHUB_SHA"], "event": "workflow_dispatch",
                  "display_title": dispatch_id, "path": ".github/workflows/topos_compute.yml",
                  "created_at": "2000-01-01T00:00:00Z"}
    monkeypatch.setattr(_GitHubTransport, "request", lambda self, method, path: server_run)
    def no_workflow(*args, **kwargs):
        pytest.fail("Expired queue budget must not instantiate a scientific workflow")
    monkeypatch.setattr("topos.actions.compute_worker.Workflow", no_workflow)
    receipt, code = run_compute_worker(encoded, digest, dispatch_id, temporary / "runs", temporary / "evidence")
    assert code == 3 and receipt["status"] == "timed-out"
    assert receipt["budget_accounting"]["remaining_execution_seconds"] == 0
    record = RunStore(temporary / "evidence/run").load()
    assert record["attempts"] == [] and record["candidates"] == []
    assert record["metadata"]["execution_kind"] == "no-execution"
    assert record["metadata"]["budget_accounting"] == receipt["budget_accounting"]
    verify_evidence(temporary / "evidence")


def test_explicit_reference_energy_branch_requires_orca_without_claiming_geometry():
    request, _, _ = encoded_request(purpose="matrix", matrix_row_id="T3O-1mo",
                                    matrix_inputs={"source_resolution": "orca-f12-reference-singlepoint-v1"})
    assert required_native_engines(request) == {"orca"}
    request["matrix_inputs"] = {}
    with pytest.raises(ValueError, match="explicit compiled source resolution"):
        required_native_engines(request)
