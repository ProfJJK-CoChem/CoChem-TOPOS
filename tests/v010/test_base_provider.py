"""Actual BASE producer-to-TOPOS receiver interoperability, with genuine xTB."""
import json
import os
from importlib.metadata import entry_points
from pathlib import Path

import pytest

from topos.base_provider import execute_handoff, metadata, request_from_handoff
from topos.config import SystemConfig
from topos.models import Molecule, RunRequest
from topos.storage import RunStore, file_digest


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
