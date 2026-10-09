"""Local-controller refusal and evidence boundaries; no native chemistry simulated."""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from threading import Event

import pytest

from topos.matrix_workflow import MatrixInputs
from topos.method_matrix import MATRIX_REVISION
from topos.models import Molecule, RunRecord, RunRequest
from topos.storage import RunStore, atomic_json

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "accept_cfour_topos.py"
spec = importlib.util.spec_from_file_location("topos_test_local_cfour_acceptance", SCRIPT)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


def request(**changes):
    molecule = Molecule(symbols=["O", "H", "H"],
        coordinates=[[.1, -.1, .2], [1.06, -.1, .2], [-.14, .83, .2]])
    values = dict(molecule=molecule, purpose="matrix", engine="cfour", method="MP2",
        matrix_row_id="T3C-30min", matrix_revision=MATRIX_REVISION,
        matrix_inputs={"external_resolution": "cfour-topos-cartesian-optimizer-v1",
            "external_protocol": {"engine": "cfour", "engine_version": "2.1", "method": "MP2",
                "operation": "optimize", "orbital_basis": "PVDZ", "frozen_core": True,
                "genbas_path": "/CONTROL-ONLY/GENBAS", "genbas_sha256": "0" * 64}})
    values.update(changes)
    return RunRequest(**values)


def test_local_request_keeps_exact_protocol_and_no_invented_nuclear_inputs():
    supplied = request()
    parsed, inputs = acceptance.validate_request(supplied.model_dump(mode="json"))
    assert parsed == supplied
    assert inputs.external_protocol.method == "MP2"
    assert inputs.external_protocol.orbital_basis == "PVDZ"
    assert inputs.external_protocol.gradient_max_hartree_per_bohr == 1e-5
    assert inputs.external_protocol.gradient_rms_hartree_per_bohr == 3e-6
    assert not inputs.cfour_quadrupole_moments
    assert inputs.external_protocol.efg_convention is None


@pytest.mark.parametrize("changes,reason", [
    ({"matrix_row_id": "T3C-1w"}, "six ordinary"),
    ({"matrix_revision": "unreviewed"}, "archived matrix"),
    ({"calculation_environment": "github-actions"}, "local CPU"),
    ({"device": "gpu"}, "local CPU"),
    ({"matrix_inputs": {}}, "external_protocol"),
])
def test_unsupported_or_incomplete_requests_refuse_before_native_work(changes, reason):
    with pytest.raises((ValueError, RuntimeError), match=reason):
        acceptance.validate_request(request(**changes).model_dump(mode="json"))


def test_wrong_method_and_missing_geometry_resolution_are_not_substituted():
    value = request().model_dump(mode="json")
    value["matrix_inputs"]["external_protocol"]["method"] = "CCSD(T)"
    with pytest.raises(ValueError, match="no method/operation substitution"):
        acceptance.validate_request(value)
    value = request().model_dump(mode="json")
    value["matrix_inputs"].pop("external_resolution")
    with pytest.raises(acceptance.AcceptanceFailure, match="Cartesian optimizer"):
        acceptance.validate_request(value)


@pytest.mark.parametrize("defect", ["changed", "unexpected", "missing"])
def test_imported_source_mismatch_rejects_even_when_version_is_unchanged(tmp_path, defect):
    source, package = tmp_path / "reviewed", tmp_path / "installed" / "topos"
    (source / "topos").mkdir(parents=True)
    package.mkdir(parents=True)
    (source / "topos" / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (package / "__init__.py").write_text('__version__ = "0.1.0"\n')
    assert acceptance.executing_sources(source, package)["imported_package_matches_source"]
    if defect == "changed":
        (package / "__init__.py").write_text('__version__ = "0.1.0"\nchanged = True\n')
    elif defect == "unexpected":
        (package / "unexpected.py").write_text("# unexpected installed execution path\n")
    else:
        (package / "__init__.py").unlink()
    with pytest.raises(acceptance.AcceptanceFailure, match="differs from the declared source"):
        acceptance.executing_sources(source, package)


def test_missing_actual_authority_retains_failure_and_never_calls_workflow(tmp_path, monkeypatch):
    declaration = tmp_path / "request.json"
    atomic_json(declaration, request().model_dump(mode="json"))
    registry = tmp_path / "absent-registry.json"
    # Source-content checking is independently exercised above. This failure
    # cannot yield native/scientific success or an authority receipt.
    monkeypatch.setattr(acceptance, "executing_sources", lambda root: {"test_only": "Failure-path bookkeeping"})
    monkeypatch.setattr(acceptance.Workflow, "run", lambda *a, **k: pytest.fail("No native run before actual audit authority"))
    report, code = acceptance.run_acceptance(registry, declaration, tmp_path / "evidence", tmp_path / "controlled")
    assert code == 3 and report["status"] == "failed"
    assert report["predeclaration"] is None and report["run"] is None
    assert report["release_eligible"] is False and report["full_matrix_campaign_certified"] is False
    assert report["scientific_accuracy_certified"] is False
    assert report["replay"]["status"] == "not-run"
    saved = json.loads((tmp_path / "evidence" / "acceptance.json").read_text())
    assert saved == report and saved["failure"]
    assert not (tmp_path / "evidence" / "run").exists()


@pytest.mark.parametrize("budget", [float("inf"), float("nan"), 0, -1, 301, True])
def test_invalid_or_extended_shared_budget_fails_before_authority_or_launch(tmp_path, monkeypatch, budget):
    declaration = tmp_path / "request.json"
    atomic_json(declaration, request(budget_seconds=300).model_dump(mode="json"))
    monkeypatch.setattr(acceptance, "executing_sources", lambda root: {"test_only": "Failure-path bookkeeping"})
    monkeypatch.setattr(acceptance.BaseRuntime, "__init__", lambda *a, **k: pytest.fail("Budget preflight must precede runtime"))
    report, code = acceptance.run_acceptance(tmp_path / "unused", declaration,
        tmp_path / "evidence", tmp_path / "controlled", budget_seconds=budget)
    assert code == 3 and report["predeclaration"] is None
    assert "shared diagnostic budget" in report["failure"]["message"]


def test_existing_evidence_and_overlapping_scratch_are_refused_without_overwrite(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    marker = evidence / "original.txt"
    marker.write_text("Original diagnostic evidence")
    with pytest.raises(acceptance.AcceptanceFailure, match="fresh"):
        acceptance.run_acceptance(tmp_path / "unused", tmp_path / "unused", evidence, tmp_path / "scratch")
    assert marker.read_text() == "Original diagnostic evidence"
    assert not (tmp_path / "scratch").exists()
    with pytest.raises(acceptance.AcceptanceFailure, match="separate"):
        acceptance.run_acceptance(tmp_path / "unused", tmp_path / "unused", tmp_path / "fresh", tmp_path / "fresh" / "scratch")
    assert not (tmp_path / "fresh").exists()


def test_replay_cannot_commit_a_cache_miss_or_launch_native_code(tmp_path):
    class RefusalRuntime:
        def cfour_runtime_identity(self):
            # Bookkeeping-only identity for an intentionally absent cache.
            return {"test_only": "No runtime or native calculation claimed"}

        def resolve_executable(self, *args):
            return "/CONTROL-ONLY/no-native-program"

        def run_process(self, *args, **kwargs):
            pytest.fail("A read-only cache miss must never launch native code")

    class RefusalWorkflow:
        base_runtime = RefusalRuntime()
        config = type("Config", (), {"executables": {}})()

    supplied = request()
    record = RunRecord(request=supplied, status="running")
    store = RunStore(tmp_path / "run")
    store.commit(record)
    before = store.verify()
    with pytest.raises(acceptance.AcceptanceFailure, match="Read-only replay"):
        acceptance.replay_components(RefusalWorkflow(), record, store,
            MatrixInputs.model_validate(supplied.matrix_inputs), time.monotonic() + 60, Event())
    assert store.verify() == before
    assert not store.load()["attempts"]
    assert not (tmp_path / "run" / "attempts").exists()


def test_expired_replay_stays_explicitly_not_run_without_authorizing_runtime(tmp_path):
    supplied = request()
    record = RunRecord(request=supplied)
    result = acceptance.replay_components(None, record, None,
        MatrixInputs.model_validate(supplied.matrix_inputs), time.monotonic() - 1, Event())
    assert result["status"] == "not-run" and result["additional_native_launches"] == 0


def test_read_only_store_forbids_every_replay_checkpoint(tmp_path):
    store = RunStore(tmp_path / "run")
    guarded = acceptance._ReadOnlyReplayStore(store)
    assert guarded.run_dir == store.run_dir
    with pytest.raises(acceptance.AcceptanceFailure, match="Read-only replay"):
        guarded.commit(RunRecord(request=request()))
    assert not store.current.exists()
