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
