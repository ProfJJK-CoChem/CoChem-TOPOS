"""Receipt boundary tests; protocol fixtures make no scientific execution claim."""
from __future__ import annotations

import hashlib
import json
import os
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


def test_invalid_configured_sidecar_cannot_fall_back_to_source(sidecar, tmp_path):
    path, _payload, receipt = sidecar
    receipt.write_text('{"changed":true}\n')
    source = tmp_path / "otherwise-discoverable-torq"
    (source / "src/cochem_torq").mkdir(parents=True)
    (source / "pyproject.toml").write_text('[project]\nname="CoChem-TORQ"\n')
    overrides = {
        "COCHEM_TORQ_ROOT": str(source),
        "COCHEM_TORQ_SIDECAR": str(path),
    }
    previous = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)
    try:
        status = base_integration.inspect_ecosystem()
    finally:
        for k, val in previous.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val
    assert not status.available
    assert not status.components["CoChem-TORQ"]["available"]
    assert any("receipt changed" in problem for problem in status.problems)


def _create_isolated_torq_venv(root: Path, *, version: str = "0.1.0") -> tuple[Path, Path]:
    """Create a minimal isolated sibling venv layout with a cochem-torq CLI and dist-info."""
    venv_root = root / "Modules" / "torq-env"
    bin_dir = venv_root / "bin"
    bin_dir.mkdir(parents=True)
    (venv_root / "pyvenv.cfg").write_text("include-system-site-packages = false\n", encoding="utf-8")
    py_exe = bin_dir / "python"
    py_exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    py_exe.chmod(0o755)
    torq_bin = bin_dir / "cochem-torq"
    torq_bin.write_text(f"#!{py_exe}\n# Isolated TORQ CLI marker\n", encoding="utf-8")
    torq_bin.chmod(0o755)
    dist_info = venv_root / "lib" / "python3.12" / "site-packages" / f"cochem_torq-{version}.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: CoChem-TORQ\nVersion: {version}\n",
        encoding="utf-8",
    )
    return venv_root, torq_bin


def test_external_torq_binary_env_is_discovered_without_importing_torq(tmp_path):
    venv_root, torq_bin = _create_isolated_torq_venv(tmp_path, version="0.1.0")
    overrides = {
        "COCHEM_TORQ_SIDECAR": None,
        "COCHEM_TORQ_ROOT": None,
        "COCHEM_TORQ_BIN": str(torq_bin),
    }
    previous = {k: os.environ.get(k) for k in overrides}
    for k, val in overrides.items():
        if val is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = val
    try:
        status = base_integration.inspect_ecosystem()
    finally:
        for k, val in previous.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val
    torq = status.components["CoChem-TORQ"]
    assert torq["available"] is True
    assert torq["kind"] == "external-isolated-binary"
    assert torq["version"] == "0.1.0"
    assert torq["discovery_source"] == "COCHEM_TORQ_BIN"
    assert torq["isolated_env_root"] == str(venv_root.resolve())
    assert torq["consumer_ready"] is False


def test_invalid_external_torq_binary_env_fails_closed(tmp_path):
    missing = tmp_path / "does-not-exist" / "cochem-torq"
    overrides = {
        "COCHEM_TORQ_SIDECAR": None,
        "COCHEM_TORQ_ROOT": None,
        "COCHEM_TORQ_BIN": str(missing),
    }
    previous = {k: os.environ.get(k) for k in overrides}
    for k, val in overrides.items():
        if val is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = val
    try:
        status = base_integration.inspect_ecosystem()
    finally:
        for k, val in previous.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val
    assert not status.available
    assert status.components["CoChem-TORQ"]["available"] is False
    assert any("COCHEM_TORQ_BIN" in problem for problem in status.problems)


def test_doctor_autodiscovers_isolated_torq_binary_on_path_when_not_in_python_env(tmp_path, capsys):
    import importlib.metadata

    from topos.cli import main as cli_main

    venv_root, torq_bin = _create_isolated_torq_venv(tmp_path, version="0.1.0")
    original_dist = importlib.metadata.distribution

    def _no_torq_dist(name: str):
        if name.lower().replace("_", "-") == "cochem-torq":
            raise importlib.metadata.PackageNotFoundError(name)
        return original_dist(name)

    overrides = {
        "COCHEM_TORQ_SIDECAR": None,
        "COCHEM_TORQ_ROOT": None,
        "COCHEM_TORQ_BIN": None,
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "PATH": str(torq_bin.parent) + os.pathsep + os.environ.get("PATH", ""),
    }
    previous = {k: os.environ.get(k) for k in overrides}
    for k, val in overrides.items():
        if val is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = val
    importlib.metadata.distribution = _no_torq_dist
    try:
        # Strict default inspect_ecosystem remains False without explicit env var or autodiscovery.
        strict_status = base_integration.inspect_ecosystem()
        assert strict_status.components["CoChem-TORQ"]["available"] is False

        # Autodiscovery enabled (used by `topos doctor`) detects the isolated sibling binary via PATH.
        doctor_status = base_integration.inspect_ecosystem(allow_external_torq_binary=True)
        torq = doctor_status.components["CoChem-TORQ"]
        assert torq["available"] is True
        assert torq["kind"] == "external-isolated-binary"
        assert torq["version"] == "0.1.0"
        assert torq["isolated_env_root"] == str(venv_root.resolve())
        assert torq["discovery_source"] == "PATH"

        # Also verify workstation_direct_bin discovery when ~/CoChem_Workstation_Direct/bin/cochem-torq exists.
        ws_bin = tmp_path / "CoChem_Workstation_Direct" / "bin" / "cochem-torq"
        ws_bin.parent.mkdir(parents=True, exist_ok=True)
        ws_bin.symlink_to(torq_bin)
        ws_status = base_integration.inspect_ecosystem(allow_external_torq_binary=True)
        assert ws_status.components["CoChem-TORQ"]["discovery_source"] == "workstation_direct_bin"
        assert ws_status.components["CoChem-TORQ"]["isolated_env_root"] == str(venv_root.resolve())

        rc = cli_main(["doctor"])
        out = json.loads(capsys.readouterr().out)
        assert out["components"]["CoChem-TORQ"]["available"] is True
        assert out["components"]["CoChem-TORQ"]["kind"] == "external-isolated-binary"
        assert rc == (0 if out["available"] else 3)
    finally:
        importlib.metadata.distribution = original_dist
        for k, val in previous.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val


def test_invalid_sidecar_still_cannot_fall_back_to_external_torq_binary(sidecar, tmp_path):
    path, _payload, receipt = sidecar
    receipt.write_text('{"changed":true}\n', encoding="utf-8")
    _, torq_bin = _create_isolated_torq_venv(tmp_path)
    overrides = {
        "COCHEM_TORQ_SIDECAR": str(path),
        "COCHEM_TORQ_BIN": str(torq_bin),
    }
    previous = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)
    try:
        status = base_integration.inspect_ecosystem(allow_external_torq_binary=True)
    finally:
        for k, val in previous.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val
    assert not status.available
    assert status.components["CoChem-TORQ"]["available"] is False
    assert any("receipt changed" in problem for problem in status.problems)
