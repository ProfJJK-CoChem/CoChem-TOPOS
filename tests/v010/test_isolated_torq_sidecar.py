"""Mandatory TORQ identity is verified without replacing BASE namespaces."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from topos.base_integration import BaseIntegrationError, _verified_torq_sidecar


def test_sidecar_requires_the_exact_typed_receipt(tmp_path):
    path = tmp_path / "sidecar.json"
    path.write_text(json.dumps({"schema_version": "cochem.module-sidecar/1", "module_id": "torq",
                                "source_path": "/arbitrary/unverified/source"}))
    with pytest.raises(BaseIntegrationError, match="contract"):
        _verified_torq_sidecar(path)


def test_sidecar_receipt_tampering_rejected_before_provider_import(tmp_path):
    root = tmp_path / "modules"
    (root / "torq").mkdir(parents=True)
    (root / "torq/installation.json").write_text('{"status":"unverified"}')
    path = tmp_path / "sidecar.json"
    path.write_text(json.dumps({"schema_version": "cochem.module-sidecar/1", "module_id": "torq",
        "root": str(root), "spec": {}, "installation_receipt_sha256": "0" * 64}))
    with pytest.raises(BaseIntegrationError, match="changed"):
        _verified_torq_sidecar(path)


def test_matching_hash_does_not_replace_real_installation_verification(tmp_path):
    root = tmp_path / "modules"
    (root / "torq").mkdir(parents=True)
    receipt = root / "torq/installation.json"
    receipt.write_text('{"status":"unverified"}')
    path = tmp_path / "sidecar.json"
    path.write_text(json.dumps({"schema_version": "cochem.module-sidecar/1", "module_id": "torq",
        "root": str(root), "spec": {}, "installation_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}))
    with pytest.raises(BaseIntegrationError, match="failed verification"):
        _verified_torq_sidecar(path)


def test_topos_dependency_boundary_keeps_torq_outside_base_authority_environment():
    import tomllib

    project = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())["project"]
    assert "CoChem-BASE>=1.0.1,<2" in project["dependencies"]
    assert not any(requirement.lower().startswith("cochem-torq") for requirement in project["dependencies"])


def matching_sidecar(tmp_path, **changes):
    """Matching hashes alone are deliberately unverified policy bookkeeping."""
    root = tmp_path / "modules"
    (root / "torq").mkdir(parents=True)
    receipt = root / "torq/installation.json"
    receipt.write_text('{"status":"unverified"}')
    value = {"schema_version": "cochem.module-sidecar/1", "module_id": "torq",
             "root": str(root), "spec": {},
             "installation_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}
    path = tmp_path / "sidecar.json"
    path.write_text(json.dumps(value | changes))
    return path


@pytest.mark.parametrize("root", [None, [], {}, 1, False, "", "   "])
def test_malformed_root_types_are_contract_errors_before_verifier_import(tmp_path, root):
    with pytest.raises(BaseIntegrationError, match="contract"):
        _verified_torq_sidecar(matching_sidecar(tmp_path, root=root))


@pytest.mark.parametrize("content", ["{", "null", "[]", '"receipt"', "42"])
def test_invalid_json_or_nonobject_sidecars_are_integration_errors(tmp_path, content):
    path = tmp_path / "sidecar.json"
    path.write_text(content)
    with pytest.raises(BaseIntegrationError):
        _verified_torq_sidecar(path)


def test_absent_sidecar_is_an_integration_error(tmp_path):
    with pytest.raises(BaseIntegrationError):
        _verified_torq_sidecar(tmp_path / "missing.json")


@pytest.mark.parametrize("exception", [KeyError("revision"), TypeError("invalid spec field")])
def test_supported_base_verifier_contract_exceptions_are_normalized(tmp_path, monkeypatch, exception):
    from scripts import manage_modules

    def reject(module_id, spec, root):
        assert module_id == "torq" and spec == {} and root.is_dir()
        raise exception

    monkeypatch.setattr(manage_modules, "verify_installation", reject)
    with pytest.raises(BaseIntegrationError, match="failed verification") as error:
        _verified_torq_sidecar(matching_sidecar(tmp_path))
    assert error.value.__cause__ is exception


@pytest.mark.parametrize("receipt", [None, {}, {"distribution_metadata": None},
    {"distribution_metadata": {"name": 1}}])
def test_malformed_verifier_results_are_integration_errors_without_availability(tmp_path, monkeypatch, receipt):
    from scripts import manage_modules

    monkeypatch.setattr(manage_modules, "verify_installation", lambda *args: receipt)
    with pytest.raises(BaseIntegrationError):
        _verified_torq_sidecar(matching_sidecar(tmp_path))


def test_ecosystem_marks_malformed_sidecar_unavailable_without_raw_type_error(tmp_path, monkeypatch):
    from topos.base_integration import inspect_ecosystem

    monkeypatch.setenv("COCHEM_TORQ_SIDECAR", str(matching_sidecar(tmp_path, root=[])))
    status = inspect_ecosystem()
    assert status.available is False
    assert status.components["CoChem-TORQ"] == {"available": False}
    assert any("TORQ sidecar contract" in problem for problem in status.problems)
