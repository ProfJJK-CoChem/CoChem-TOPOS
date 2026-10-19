"""Receipt boundary tests; protocol fixtures make no scientific execution claim."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from packaging.requirements import Requirement

from topos import base_integration


@pytest.fixture
def sidecar(tmp_path):
    root = tmp_path / "modules"
    receipt = root / "torq" / "installation.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"identity_fixture_only":true}\n')
    value = {"schema_version": "cochem.module-sidecar/1", "module_id": "torq",
             "root": str(root), "spec": {},
             "installation_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}
    path = tmp_path / "sidecar.json"
    path.write_text(json.dumps(value))
    return path, value, receipt


def test_managed_dependencies_accept_base_1_1_without_coinstalling_torq():
    import tomllib

    project = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())["project"]
    requirements = [Requirement(item) for item in project["dependencies"]]
    base = [item for item in requirements if item.name.lower() == "cochem-base"]
    assert len(base) == 1 and "1.1.0" in base[0].specifier
    assert "1.2.0" not in base[0].specifier
    assert not any(item.name.lower() == "cochem-torq" for item in requirements)


@pytest.mark.parametrize("field,value", [
    ("schema_version", "unknown/1"), ("module_id", "topos"),
    ("root", 1), ("root", "relative/modules"), ("spec", []),
    ("installation_receipt_sha256", "not-a-sha256"),
])
def test_sidecar_rejects_malformed_identity_before_verification(sidecar, field, value):
    path, payload, _receipt = sidecar
    payload[field] = value
    path.write_text(json.dumps(payload))
    with pytest.raises(base_integration.BaseIntegrationError, match="sidecar"):
        base_integration._verified_torq_sidecar(path)


def test_sidecar_rejects_duplicate_contract_fields(sidecar):
    path, payload, _receipt = sidecar
    path.write_text(json.dumps(payload)[:-1] + ',"module_id":"torq"}')
    with pytest.raises(base_integration.BaseIntegrationError, match="duplicate"):
        base_integration._verified_torq_sidecar(path)


def test_sidecar_rejects_redirected_or_oversized_receipt(sidecar, tmp_path):
    path, _payload, _receipt = sidecar
    link = tmp_path / "redirect.json"
    link.symlink_to(path)
    with pytest.raises(base_integration.BaseIntegrationError, match="regular"):
        base_integration._verified_torq_sidecar(link)
    path.write_bytes(b" " * 100_001)
    with pytest.raises(base_integration.BaseIntegrationError, match="bounded"):
        base_integration._verified_torq_sidecar(path)


def test_sidecar_rejects_receipt_changed_since_base_verification(sidecar):
    path, _payload, receipt = sidecar
    receipt.write_text('{"changed":true}\n')
    with pytest.raises(base_integration.BaseIntegrationError, match="receipt changed"):
        base_integration._verified_torq_sidecar(path)


def test_sidecar_rejects_redirected_installation_receipt(sidecar, tmp_path):
    path, _payload, receipt = sidecar
    retained = tmp_path / "otherwise-identical-installation.json"
    receipt.rename(retained)
    receipt.symlink_to(retained)
    with pytest.raises(base_integration.BaseIntegrationError, match="regular file"):
        base_integration._verified_torq_sidecar(path)


def test_invalid_configured_sidecar_cannot_fall_back_to_source(sidecar, tmp_path, monkeypatch):
    path, _payload, receipt = sidecar
    receipt.write_text('{"changed":true}\n')
    source = tmp_path / "otherwise-discoverable-torq"
    (source / "src/cochem_torq").mkdir(parents=True)
    (source / "pyproject.toml").write_text('[project]\nname="CoChem-TORQ"\n')
    monkeypatch.setenv("COCHEM_TORQ_ROOT", str(source))
    monkeypatch.setenv("COCHEM_TORQ_SIDECAR", str(path))
    status = base_integration.inspect_ecosystem()
    assert not status.available
    assert not status.components["CoChem-TORQ"]["available"]
    assert any("receipt changed" in problem for problem in status.problems)
