"""Real CLI subprocess metadata fixtures; no remote or chemical success claims."""
from __future__ import annotations

import json
import os
import sys

import pytest

from topos.actions.dispatch import (
    ActionDispatchClient,
    RemoteExecutionError,
    _controller_environment,
    _GitHubCLITransport,
    _GitHubTransport,
)
from topos.config import DEFAULT_REMOTE_BASE_COMMIT, SystemConfig, load_config


@pytest.fixture
def native_cli(tmp_path, monkeypatch):
    executable = tmp_path / "gh"
    log = tmp_path / "cli-calls.jsonl"
    script = """import json, os, sys, time
arguments = sys.argv[1:]
with open(os.environ['CLI_FIXTURE_LOG'], 'a') as output:
 output.write(json.dumps({'arguments': arguments, 'credential_names': [name for name in ('GH_TOKEN', 'GITHUB_TOKEN') if name in os.environ]}) + '\\n')
if os.environ.get('CLI_FIXTURE_FAILURE'):
 print('Sensitive fixture stderr must never enter the exception', file=sys.stderr)
 raise SystemExit(1)
if arguments[:2] == ['auth', 'status']:
 raise SystemExit(0)
if os.environ.get('CLI_FIXTURE_DELAY'):
 time.sleep(5)
if os.environ.get('CLI_FIXTURE_LARGE'):
 sys.stdout.buffer.write(b'x' * 10000)
elif '--input' in arguments:
 print(json.dumps({'received': json.load(sys.stdin)}))
else:
 print(json.dumps({'private': True, 'default_branch': 'main'}))
"""
    executable.write_text("#!" + sys.executable + "\n" + script)
    executable.chmod(0o700)
    monkeypatch.setenv("CLI_FIXTURE_LOG", str(log))
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CODESPACES", raising=False)
    monkeypatch.delenv("COCHEM_PRIVATE_GH_AUTH", raising=False)
    return log


def test_codespaces_uses_stored_cli_without_exposing_the_injected_token(native_cli, monkeypatch):
    monkeypatch.setenv("CODESPACES", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "injected-infrastructure-fixture")
    client = ActionDispatchClient(target_repo="owner/controller")
    transport = client._connection()
    assert isinstance(transport, _GitHubCLITransport)
    assert transport.request("GET", "/repos/owner/controller")["private"] is True
    calls = [json.loads(line) for line in native_cli.read_text().splitlines()]
    assert len(calls) == 2
    assert all(call["credential_names"] == [] for call in calls)
    assert calls[1]["arguments"][:5] == ["api", "--hostname", "github.com", "--method", "GET"]
    assert os.environ["GITHUB_TOKEN"] == "injected-infrastructure-fixture"
    assert "injected-infrastructure-fixture" not in repr(transport)


def test_native_cli_preserves_structured_json_and_real_newlines(native_cli):
    transport = _GitHubCLITransport(_controller_environment())
    payload = {"ref": "main", "inputs": {"description": "First line\nSecond line $() `literal`"}}
    assert transport.request("POST", "/repos/owner/controller/actions/workflows/topos_compute.yml/dispatches",
                             payload) == {"received": payload}
    call = json.loads(native_cli.read_text().splitlines()[-1])
    assert call["arguments"][-2:] == ["--input", "-"]
    assert not any("First line" in argument for argument in call["arguments"])


def test_actions_and_explicit_environment_modes_keep_the_owning_token(native_cli, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "owning-project-infrastructure-fixture")
    monkeypatch.setenv("CODESPACES", "true")
    monkeypatch.setenv("COCHEM_PRIVATE_GH_AUTH", "stored-cli")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert isinstance(ActionDispatchClient(target_repo="owner/controller")._connection(), _GitHubTransport)
    monkeypatch.delenv("GITHUB_ACTIONS")
    monkeypatch.setenv("COCHEM_PRIVATE_GH_AUTH", "environment")
    assert isinstance(ActionDispatchClient(target_repo="owner/controller")._connection(), _GitHubTransport)
    assert not native_cli.exists()


@pytest.mark.parametrize("path", ["https://evil.invalid/data", "/user", "/repos/owner/controller\nHeader: value"])
def test_native_cli_rejects_nonrepository_api_endpoints(native_cli, path):
    transport = _GitHubCLITransport(_controller_environment())
    before = native_cli.read_bytes()
    with pytest.raises(RemoteExecutionError, match="REST path"):
        transport.request("GET", path)
    assert native_cli.read_bytes() == before


@pytest.mark.parametrize("path", ["https://evil.invalid/data", "/repos/owner/controller/actions/artifacts/1",
                                  "/repos/owner/controller/actions/artifacts/../zip"])
def test_native_cli_artifact_download_requires_the_fixed_github_endpoint(native_cli, path):
    transport = _GitHubCLITransport(_controller_environment())
    before = native_cli.read_bytes()
    with pytest.raises(RemoteExecutionError, match="artifact download"):
        transport.download(path)
    assert native_cli.read_bytes() == before


def test_native_cli_failure_is_redacted_and_never_claims_authentication(native_cli, monkeypatch):
    monkeypatch.setenv("CLI_FIXTURE_FAILURE", "true")
    with pytest.raises(RemoteExecutionError) as error:
        _GitHubCLITransport(_controller_environment())
    assert "Sensitive fixture" not in str(error.value)


def test_native_cli_enforces_actual_subprocess_output_and_time_limits(native_cli, monkeypatch):
    transport = _GitHubCLITransport(_controller_environment())
    transport._environment["CLI_FIXTURE_LARGE"] = "true"
    with pytest.raises(RemoteExecutionError, match="size limit"):
        transport._run(["api"], limit=100, timeout=1)
    transport._environment.pop("CLI_FIXTURE_LARGE")
    transport._environment["CLI_FIXTURE_DELAY"] = "true"
    with pytest.raises(RemoteExecutionError, match="could not be completed"):
        transport._run(["api"], limit=1000, timeout=.05)


def test_remote_source_pin_is_explicit_configuration_with_a_documented_foundation_default(tmp_path, monkeypatch):
    monkeypatch.delenv("TOPOS_REMOTE_BASE_COMMIT", raising=False)
    monkeypatch.delenv("TOPOS_CONFIG", raising=False)
    assert SystemConfig().remote_base_commit == DEFAULT_REMOTE_BASE_COMMIT
    assert SystemConfig().remote_controller_profile == "free"
    config = tmp_path / "topos.json"
    config.write_text(json.dumps({"remote_base_commit": "b" * 40}))
    assert load_config(config).remote_base_commit == "b" * 40
    monkeypatch.setenv("TOPOS_REMOTE_BASE_COMMIT", "c" * 40)
    assert load_config(config).remote_base_commit == "c" * 40
    monkeypatch.setenv("TOPOS_REMOTE_BASE_COMMIT", "main")
    with pytest.raises(ValueError, match="remote_base_commit"):
        load_config(config)
    monkeypatch.delenv("TOPOS_REMOTE_BASE_COMMIT")
    monkeypatch.setenv("TOPOS_REMOTE_CONTROLLER_PROFILE", "legacy-topos-orca")
    assert load_config(config).remote_controller_profile == "legacy-topos-orca"
    monkeypatch.setenv("TOPOS_REMOTE_CONTROLLER_PROFILE", "unverified")
    with pytest.raises(ValueError, match="remote_controller_profile"):
        load_config(config)
