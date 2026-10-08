"""Setup input/plan contracts. No mocked installation is reported as success."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "setup_ecosystem.py"
spec = importlib.util.spec_from_file_location("topos_setup_ecosystem_test", MODULE_PATH)
setup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = setup
spec.loader.exec_module(setup)


@pytest.fixture
def roots(tmp_path):
    result = {}
    for name in setup.REPOSITORIES:
        directory = tmp_path / name
        directory.mkdir()
        (directory / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "0.1.0"\n')
        result[name] = directory
    (result["CoChem-BASE"] / "scripts").mkdir()
    # Merely validate entry-point presence. These files are never executed.
    (result["CoChem-BASE"] / "scripts" / "hosted_dashboard.py").write_text("# Path-validation fixture only\n")
    (result["CoChem-BASE"] / "cli.py").write_text("# Path-validation fixture only\n")
    return result


def layout(roots, artifacts, **kwargs):
    return setup.validate_layout(roots["CoChem-BASE"], roots["CoChem-TORQ"], artifacts,
                                 topos_root=roots["CoChem-TOPOS"], **kwargs)


def test_layout_checks_expected_projects_without_creating_artifacts(roots, tmp_path):
    artifacts = tmp_path / "runtime"
    result = layout(roots, artifacts)
    assert result.artifacts == artifacts
    assert result.python == artifacts / "ui-env" / "bin" / "python"
    assert not artifacts.exists()


@pytest.mark.parametrize("project", setup.REPOSITORIES)
def test_missing_repository_is_rejected_before_any_provisioning(roots, tmp_path, project):
    (roots[project] / "pyproject.toml").unlink()
    with pytest.raises(ValueError, match="source checkout"):
        layout(roots, tmp_path / "runtime")
    assert not (tmp_path / "runtime").exists()


@pytest.mark.parametrize("project", setup.REPOSITORIES)
def test_misnamed_checkout_cannot_supply_another_mandatory_component(roots, tmp_path, project):
    (roots[project] / "pyproject.toml").write_text('[project]\nname="Unrelated-Project"\n')
    with pytest.raises(ValueError, match="does not identify"):
        layout(roots, tmp_path / "runtime")


@pytest.mark.parametrize("project", setup.REPOSITORIES)
@pytest.mark.parametrize("inside", [False, True])
def test_artifacts_cannot_pollute_any_source_checkout(roots, project, inside):
    artifacts = roots[project] / "runtime" if inside else roots[project]
    with pytest.raises(ValueError, match="outside and disjoint"):
        layout(roots, artifacts)


def test_artifacts_cannot_enclose_source_repositories(roots, tmp_path):
    with pytest.raises(ValueError, match="outside and disjoint"):
        layout(roots, tmp_path)


def test_symlink_does_not_bypass_source_tree_separation(roots, tmp_path):
    link = tmp_path / "runtime-alias"
    link.symlink_to(roots["CoChem-TOPOS"], target_is_directory=True)
    with pytest.raises(ValueError, match="outside and disjoint"):
        layout(roots, link / "artifacts")


def test_setup_entrypoints_must_exist(roots, tmp_path):
    (roots["CoChem-BASE"] / "scripts" / "hosted_dashboard.py").unlink()
    with pytest.raises(ValueError, match="entry point"):
        layout(roots, tmp_path / "runtime")


@pytest.mark.parametrize("minimum", [0, -1, float("nan"), float("inf")])
def test_storage_floor_must_be_positive_finite(roots, tmp_path, minimum):
    with pytest.raises(ValueError, match="finite and positive"):
        layout(roots, tmp_path / "runtime", min_disk_space_gb=minimum)


def test_python_version_floor_is_explicit():
    with pytest.raises(ValueError, match="3.11"):
        setup.require_python((3, 10, 99))
    setup.require_python((3, 11, 0))


def test_mandatory_manifest_lists_all_three_installations():
    assert setup.deployment_manifest() == {"selected_repositories": ["CoChem-BASE", "CoChem-TOPOS", "CoChem-TORQ"]}


def test_command_plan_refreshes_dependencies_and_complete_setup(roots, tmp_path):
    resolved = layout(roots, tmp_path / "runtime", min_disk_space_gb=2.5)
    commands = setup.setup_commands(resolved, bootstrap_python="/explicit/python")
    assert commands["bootstrap"][0] == "/explicit/python"
    assert commands["bootstrap"][1] == str(roots["CoChem-BASE"] / "scripts" / "hosted_dashboard.py")
    assert commands["bootstrap"][2] == "setup"
    assert str(roots["CoChem-TOPOS"]) + "[dev,ui]" in commands["install_modules"]
    assert str(roots["CoChem-TORQ"]) in commands["install_modules"]
    assert "--no-deps" not in commands["install_modules"]
    assert {"setup", "--all", "--skip-heavy", "--json"} <= set(commands["mandatory_setup"])
    assert commands["mandatory_setup"][commands["mandatory_setup"].index("--min-disk-space-gb") + 1] == "2.5"
    assert commands["pip_check"][-2:] == ["pip", "check"]


def test_environment_binds_manifest_registry_and_actual_base_xtb_path(roots, tmp_path, monkeypatch):
    resolved = layout(roots, tmp_path / "runtime")
    xtb = resolved.artifacts / "free-engines" / "xtb" / "xtb-dist" / "bin" / "xtb"
    xtb.parent.mkdir(parents=True)
    xtb.write_text("path fixture; not executed")
    crest = tmp_path / "explicit-crest"
    monkeypatch.setenv("COCHEM_MANIFEST_PATH", "/stale/manifest.json")
    monkeypatch.setenv("COCHEM_CONFIG", "/stale/registry.json")
    monkeypatch.setenv("COCHEM_TORQ_ROOT", "/stale/torq")
    env = setup.runtime_environment(resolved, crest)
    assert env["COCHEM_MANIFEST_PATH"] == str(resolved.manifest)
    assert env["COCHEM_CONFIG"] == str(resolved.artifacts / "Registry" / "cochem_system_config.json")
    assert env["COCHEM_CREST_BIN"] == str(crest)
    assert env["COCHEM_XTB_BIN"] == str(xtb)
    assert env["TOPOS_EXECUTION_BACKEND"] == "base"
    assert "COCHEM_TORQ_ROOT" not in env
    assert env["COCHEM_CORE_SILO"].startswith(str(resolved.artifacts))


def test_probes_require_actual_authority_both_engine_versions_and_all_phases():
    # Syntax/reference checks supplement genuine setup evidence; they do not
    # represent an executed BASE setup or executable verification.
    compile(setup.EXISTING_BASE_PROBE, "existing-base-probe", "exec")
    compile(setup.VALIDATION_PROBE, "mandatory-validation-probe", "exec")
    assert "verify_integrity=True" in setup.EXISTING_BASE_PROBE
    assert "BaseRuntime" in setup.VALIDATION_PROBE
    assert "range(1, 12)" in setup.VALIDATION_PROBE
    assert "('xtb', '6.7.1'), ('crest', '3.0.2')" in setup.VALIDATION_PROBE
    assert "subprocess.run([executable, '--version']" in setup.VALIDATION_PROBE
    assert "not certified by installation" in setup.VALIDATION_PROBE


def test_atomic_manifest_write_contains_no_credentials(tmp_path):
    target = tmp_path / "mandatory-deployment.json"
    setup._write_json(target, setup.deployment_manifest())
    assert json.loads(target.read_text()) == setup.deployment_manifest()
    assert not target.with_name(target.name + ".tmp").exists()


def test_cli_rejects_missing_roots_without_network_or_artifacts(tmp_path, capsys):
    status = setup.main(["--base-root", str(tmp_path / "missing-base"), "--torq-root", str(tmp_path / "missing-torq"),
                         "--artifacts", str(tmp_path / "runtime")])
    assert status == 1
    assert "source checkout" in capsys.readouterr().err
    assert not (tmp_path / "runtime").exists()
