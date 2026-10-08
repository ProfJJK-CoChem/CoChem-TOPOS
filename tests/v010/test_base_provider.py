"""Actual BASE producer-to-TOPOS receiver interoperability, with genuine xTB."""
import json
import os
from importlib.metadata import entry_points
from pathlib import Path

import pytest

from topos.base_provider import (
    execute_handoff,
    hosted_budget_context,
    metadata,
    request_from_handoff,
)
from topos.config import SystemConfig
from topos.models import Molecule, RunRequest
from topos.storage import RunStore, digest_json, file_digest


def base_api():
    try:
        from cochem_base.interfaces.artifact_handoff import prepare_module_handoff
    except ImportError:
        if os.environ.get("TOPOS_REQUIRE_BASE") == "1":
            pytest.fail("Mandatory BASE provider acceptance requires the actual BASE package")
        pytest.skip("Actual BASE package required; no producer handoff substitute")
    return prepare_module_handoff


def prepare(tmp_path, *, operation="energy", request=None):
    producer = base_api()
    molecule = Molecule(symbols=["O", "H", "H"],
                        coordinates=[[0, 0, 0], [.9572, 0, 0], [-.23999, .9273, 0]])
    payload = request or RunRequest(molecule=molecule, purpose="energy", n_candidates=1,
                                   budget_seconds=30).model_dump(mode="json")
    source = tmp_path / "source.xyz"
    source.write_text("3\nOriginal BASE input\nO 0 0 0\nH .9572 0 0\nH -.23999 .9273 0\n")
    target = tmp_path / "handoff"
    producer("topos", source, target, operation=operation, options={"topos_request": payload})
    return target / "handoff.json"


def test_provider_metadata_never_claims_executed_science():
    assert metadata()["integration_contract"] == "cochem.module-handoff/1"
    assert metadata()["execution_verified"] is False


def test_installed_base_discovers_topos_provider_without_claiming_execution():
    base_api()
    from cochem_base.interfaces.module_registry import get_module_capability

    capability = get_module_capability("topos")
    assert capability.status.value == "installed_pending_integration"
    assert capability.execution_verified is False
    providers = [entry for entry in entry_points(group="cochem.modules") if entry.name == "topos"]
    assert len(providers) == 1
    assert providers[0].load().metadata()["integration_contract"] == "cochem.module-handoff/1"


def test_real_base_handoff_preserves_explicit_request_and_original_artifact(tmp_path):
    manifest = prepare(tmp_path)
    request, provenance = request_from_handoff(manifest)
    assert request.purpose == "energy" and request.engine == "xtb"
    assert provenance["manifest_file_sha256"] == file_digest(manifest)
    assert provenance["artifact_sha256"] == file_digest(manifest.parent / "artifact.xyz")
    assert provenance["producer_scientific_execution_performed"] is False


def test_base_handoff_tampering_does_not_launch_a_consumer(tmp_path):
    manifest = prepare(tmp_path)
    (manifest.parent / "artifact.xyz").write_text("3\nchanged\nO 0 0 0\nH 1 0 0\nH 0 1 0\n")
    with pytest.raises(ValueError, match="integrity"):
        request_from_handoff(manifest)


@pytest.mark.parametrize("change", ["state", "coordinates", "operation"])
def test_receiver_requires_explicit_state_geometry_and_operation_agreement(tmp_path, change):
    manifest = prepare(tmp_path)
    value = json.loads(manifest.read_text())
    if change == "state":
        del value["options"]["topos_request"]["molecule"]["charge"]
    elif change == "coordinates":
        value["options"]["topos_request"]["molecule"]["coordinates"][1][0] = 1
    else:
        value["operation"] = "gradient"
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        request_from_handoff(manifest)


@pytest.mark.integration
def test_actual_base_handoff_executes_real_xtb_and_retains_consumption_receipt(tmp_path):
    manifest = prepare(tmp_path)
    registry = os.environ.get("COCHEM_CONFIG")
    if not registry or not Path(registry).is_file():
        if os.environ.get("TOPOS_REQUIRE_BASE") == "1":
            pytest.fail("A genuine eleven-phase BASE registry is required")
        pytest.skip("Actual BASE setup registry is unavailable")
    before = file_digest(manifest)
    outcome = execute_handoff(manifest, tmp_path / "runs",
                              config=SystemConfig(execution_backend="base", base_registry_path=Path(registry)))
    record, receipt = outcome["record"], outcome["receipt"]
    assert record["status"] == "completed", record["metadata"].get("termination_reason")
    assert receipt["status"] == "completed" and receipt["execution_provider"] == "CoChem-BASE"
    assert record["attempts"][0]["engine_version"] == "6.7.1"
    assert record["attempts"][0]["metadata"]["execution_kind"] == "real"
    assert record["candidates"][0]["energy_hartree"] < 0
    RunStore(record["metadata"]["run_dir"]).verify()
    assert file_digest(manifest) == before
    assert json.loads(manifest.read_text())["scientific_execution_performed"] is False


def test_base_receiver_refuses_development_execution(tmp_path):
    with pytest.raises(ValueError, match="mandatory BASE"):
        execute_handoff(tmp_path / "missing.json", tmp_path / "runs",
                        config=SystemConfig(execution_backend="development"))
    assert not (tmp_path / "runs").exists()


def hosted_control(monkeypatch, request, *, created="2026-10-08T00:00:00Z"):
    """Infrastructure context only; it neither authenticates GitHub nor creates science."""
    control = {"schema_version": "cochem.topos-hosted-budget/1", "request_sha256": digest_json(request),
               "repository": "student/project", "repository_id": 17, "owner_id": 18,
               "source_sha": "1" * 40, "ref": "refs/heads/main",
               "workflow_path": ".github/workflows/topos_calculation.yml", "run_id": 19, "run_attempt": 1,
               "workflow_created_at": created}
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    for name, value in {"GITHUB_REPOSITORY": control["repository"], "GITHUB_REPOSITORY_ID": "17",
                        "GITHUB_REPOSITORY_OWNER_ID": "18", "GITHUB_SHA": control["source_sha"],
                        "GITHUB_REF": control["ref"], "GITHUB_RUN_ID": "19", "GITHUB_RUN_ATTEMPT": "1",
                        "GITHUB_WORKFLOW_REF": "student/project/.github/workflows/topos_calculation.yml@refs/heads/main"}.items():
        monkeypatch.setenv(name, value)
    return control


def test_hosted_budget_recomputes_at_final_boundary_without_rewriting_scientific_request(monkeypatch):
    molecule = Molecule(symbols=["He"], coordinates=[[0, 0, 0]])
    request = RunRequest(molecule=molecule, purpose="energy", include_queue_in_budget=True, budget_seconds=30)
    original = request.model_dump(mode="json")
    control = hosted_control(monkeypatch, original)
    monkeypatch.setattr("topos.base_provider.utc_now", lambda: "2026-10-08T00:00:10+00:00")
    first, _ = hosted_budget_context(control, request, digest_json(original))
    monkeypatch.setattr("topos.base_provider.utc_now", lambda: "2026-10-08T00:00:25+00:00")
    second, context = hosted_budget_context(control, request, digest_json(original))
    assert first == 20 and second == 5
    assert context["budget_accounting"]["pre_execution_elapsed_seconds"] == 25
    assert request.model_dump(mode="json") == original


@pytest.mark.parametrize("changed", ["extra", "request", "repository", "source", "workflow", "run", "attempt",
                                     "bool-id", "future", "no-actions"])
def test_hosted_budget_rejects_unbound_or_malformed_controls_before_calculation(monkeypatch, changed):
    request = RunRequest(molecule=Molecule(symbols=["He"], coordinates=[[0, 0, 0]]), purpose="energy",
                         include_queue_in_budget=True)
    control = hosted_control(monkeypatch, request.model_dump(mode="json"))
    monkeypatch.setattr("topos.base_provider.utc_now", lambda: "2026-10-08T00:00:10+00:00")
    if changed == "extra":
        control["elapsed_override"] = 0
    elif changed == "request":
        control["request_sha256"] = "2" * 64
    elif changed == "repository":
        control["repository"] = "student/other"
    elif changed == "source":
        control["source_sha"] = "2" * 40
    elif changed == "workflow":
        control["workflow_path"] = ".github/workflows/unreviewed.yml"
    elif changed == "run":
        control["run_id"] = 20
    elif changed == "attempt":
        control["run_attempt"] = 2
    elif changed == "bool-id":
        control["owner_id"] = True
    elif changed == "future":
        control["workflow_created_at"] = "2026-10-08T00:00:20Z"
    else:
        monkeypatch.setenv("GITHUB_ACTIONS", "false")
    with pytest.raises(ValueError):
        hosted_budget_context(control, request, digest_json(request.model_dump(mode="json")))


def test_expired_server_budget_retains_real_base_handoff_and_zero_native_attempts(tmp_path, monkeypatch):
    from topos.workflow import Workflow

    molecule = Molecule(symbols=["O", "H", "H"],
                        coordinates=[[0, 0, 0], [.9572, 0, 0], [-.23999, .9273, 0]])
    payload = RunRequest(molecule=molecule, purpose="energy", budget_seconds=30,
                         include_queue_in_budget=True).model_dump(mode="json")
    manifest = prepare(tmp_path, request=payload)
    before = file_digest(manifest)
    control = hosted_control(monkeypatch, payload)
    monkeypatch.setattr("topos.base_provider.utc_now", lambda: "2026-10-08T00:01:00+00:00")
    monkeypatch.setattr(Workflow, "_execute", lambda *args, **kwargs: pytest.fail("An expired allocation cannot execute"))
    result = execute_handoff(manifest, tmp_path / "runs", hosted_budget=control,
                             config=SystemConfig(execution_backend="base"))
    record, receipt = result["record"], result["receipt"]
    assert record["status"] == receipt["status"] == "timed-out"
    assert record["attempts"] == record["candidates"] == []
    assert record["metadata"]["execution_kind"] == "no-execution"
    assert record["metadata"]["invocation_budget_allocated_seconds"] == 0
    assert record["request"]["budget_seconds"] == payload["budget_seconds"]
    assert record["metadata"]["request_sha256"] == digest_json(record["request"])
    assert receipt["declared_request_sha256"] == digest_json(payload)
    assert receipt["budget_accounting"]["expired_before_execution"] is True
    assert receipt["hosted_budget_control_sha256"] == digest_json(control)
    assert file_digest(manifest) == before
    store = RunStore(record["metadata"]["run_dir"])
    assert store.load() == record
    store.verify()


def test_hosted_queue_budget_requires_separate_control_not_caller_metadata(tmp_path, monkeypatch):
    manifest = prepare(tmp_path, request=RunRequest(
        molecule=Molecule(symbols=["O", "H", "H"],
                          coordinates=[[0, 0, 0], [.9572, 0, 0], [-.23999, .9273, 0]]),
        purpose="energy", include_queue_in_budget=True,
        metadata={"hosted_budget": {"claimed_elapsed": 0}},
    ).model_dump(mode="json"))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(ValueError, match="separate authenticated budget control"):
        execute_handoff(manifest, tmp_path / "runs", config=SystemConfig(execution_backend="base"))
    assert not (tmp_path / "runs").exists()


def test_execution_only_hosted_request_retains_identity_without_charging_setup(monkeypatch):
    request = RunRequest(molecule=Molecule(symbols=["He"], coordinates=[[0, 0, 0]]), purpose="energy")
    original = request.model_dump(mode="json")
    control = hosted_control(monkeypatch, original)
    monkeypatch.setattr("topos.base_provider.utc_now", lambda: "2026-10-08T01:00:00+00:00")
    allocation, context = hosted_budget_context(control, request, digest_json(original))
    assert allocation is None and context["budget_accounting"] is None
    assert context["hosted_budget_control"] == control
    assert request.model_dump(mode="json") == original
