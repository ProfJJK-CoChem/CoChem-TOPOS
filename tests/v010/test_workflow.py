"""Workflow regressions; integration cases execute genuine external xTB."""

from __future__ import annotations

import csv
import json
import os
import shutil
from threading import Event

import pytest

from topos.config import SystemConfig
from topos.models import Molecule, RunRequest
from topos.publication import export_bundle, verify_bundle
from topos.review import acknowledge_torq, append_decision, create_ensemble_manifest
from topos.storage import IntegrityError, RunStore, digest_json
from topos.workflow import Workflow


def water():
    return Molecule(
        symbols=["O", "H", "H"],
        coordinates=[[0, 0, 0], [0.9572, 0, 0], [-0.23999, 0.9273, 0]],
        isotopes=[16, 1, 1],
    )


def executable():
    binary = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if not binary:
        pytest.skip("real xTB executable unavailable; no chemical result simulated")
    return binary


def request(**changes):
    return RunRequest(molecule=water(), budget_seconds=60, profile_id="xtb-vtight-v1", **changes)


@pytest.mark.parametrize("allocation", [-1, True, float("inf"), float("nan"), "5", 61])
def test_initial_invocation_budget_cannot_be_malformed_or_increase_request(tmp_path, allocation):
    selected = request()
    original = selected.model_dump(mode="json")
    with pytest.raises(ValueError):
        Workflow(tmp_path).run(selected, invocation_budget_seconds=allocation)
    assert selected.model_dump(mode="json") == original
    assert not list(tmp_path.glob("run_*"))


def test_initial_budget_allocation_preserves_request_and_bounds_cancelled_invocation(tmp_path):
    cancelled = Event()
    cancelled.set()
    selected = request(n_candidates=1)
    original = selected.model_dump(mode="json")
    record = Workflow(tmp_path, config=SystemConfig(execution_backend="development")).run(
        selected, cancel_event=cancelled, invocation_budget_seconds=20,
    )
    assert record.status == "cancelled" and not record.attempts
    assert record.request.model_dump(mode="json") == original
    assert record.metadata["request_sha256"] == digest_json(original)
    assert 0 < record.metadata["invocation_budget_allocated_seconds"] <= 20
    assert record.metadata["budget_accounting"]["budget_seconds"] <= 20
    assert RunStore(tmp_path / record.run_id).load()["request"] == original


def test_expired_initial_allocation_never_reaches_execution_and_keeps_original_budget(tmp_path, monkeypatch):
    selected = request()
    original = selected.model_dump(mode="json")
    monkeypatch.setattr(Workflow, "_execute", lambda *args, **kwargs: pytest.fail("Expired invocation cannot launch"))
    record = Workflow(tmp_path).run(selected, invocation_budget_seconds=0)
    assert record.status == "timed-out" and not record.attempts and not record.candidates
    assert record.request.model_dump(mode="json") == original
    assert record.metadata["request_sha256"] == digest_json(original)
    assert record.metadata["invocation_budget_allocated_seconds"] == 0
    assert record.metadata["budget_accounting"]["execution_seconds"] == 0
    assert record.metadata["budget_accounting"]["budget_seconds"] == 0


def test_initial_invocation_override_cannot_be_silently_forwarded_to_remote_submission(tmp_path):
    with pytest.raises(ValueError, match="assigned local worker"):
        Workflow(tmp_path).run(request(calculation_environment="github-actions"), invocation_budget_seconds=10)
    assert not list(tmp_path.glob("run_*"))


def test_missing_engine_has_no_energy_or_substitution_and_saved_attempt(tmp_path):
    workflow = Workflow(
        tmp_path, config=SystemConfig(executables={"xtb": str(tmp_path / "absent-xtb")})
    )
    result = workflow.run(request(n_candidates=1))
    assert result.status == "unavailable"
    assert len(result.attempts) == 1
    assert result.attempts[0].method == "GFN2-xTB"
    assert result.attempts[0].engine == "xtb"
    assert not result.attempts[0].quantities
    assert result.candidates[0].energy_hartree is None
    assert RunStore(tmp_path / result.run_id).load()["status"] == "unavailable"


def test_capability_errors_prevent_engine_launch(tmp_path):
    result = Workflow(tmp_path).run(request(device="cuda"))
    assert result.status == "unsupported" and not result.attempts
    result = Workflow(tmp_path).run(
        request(calculation_environment="github-actions", presentation_environment="codespaces")
    )
    assert result.status == "unavailable" and not result.attempts
    assert result.request.presentation_environment == "codespaces"
    assert result.request.calculation_environment == "github-actions"
    result = Workflow(tmp_path).run(request(matrix_revision="unverified-new-matrix"))
    assert result.status == "unsupported" and not result.attempts


def test_collision_and_unknown_constraints_stop_before_execution(tmp_path):
    result = Workflow(tmp_path).run(
        RunRequest(molecule=Molecule(symbols=["He", "He"], coordinates=[[0, 0, 0], [0, 0, 0]]))
    )
    assert result.status == "failed" and not result.attempts
    result = Workflow(tmp_path).run(request(constraints={"invented": True}))
    assert result.status == "unsupported" and not result.attempts


def test_cancellation_before_launch_keeps_input_and_honest_state(tmp_path):
    event = Event()
    event.set()
    result = Workflow(tmp_path).run(request(), cancel_event=event)
    assert result.status == "cancelled" and not result.attempts
    stored = RunStore(tmp_path / result.run_id).load()
    assert stored["request"]["molecule"]["isotopes"] == [16, 1, 1]
    assert stored["metadata"]["input_sha256"]


@pytest.mark.integration
def test_real_search_review_handoff_export_and_resume(tmp_path):
    binary = executable()
    root = tmp_path / "runs"
    workflow = Workflow(root, config=SystemConfig(executables={"xtb": binary}))
    result = workflow.run(request(n_candidates=3, seed=2026))
    assert result.status == "completed"
    assert len(result.attempts) == 3
    eligible = [c for c in result.candidates if c.status == "eligible"]
    assert len(eligible) == 1
    assert sum(c.status == "duplicate" for c in result.candidates) == 2
    assert eligible[0].energy_hartree == pytest.approx(-5.070544447, abs=2e-8)
    assert eligible[0].gibbs_hartree is None
    assert all(
        a.engine_version == "6.7.1" and a.metadata["execution_kind"] == "real"
        for a in result.attempts
    )
    assert all(a.command and a.artifacts for a in result.attempts)
    run_dir = root / result.run_id
    store = RunStore(run_dir)
    snapshot = store.verify()["snapshot_id"]
    assert workflow.resume(run_dir).model_dump() == result.model_dump()
    assert store.verify()["snapshot_id"] == snapshot
    # Test actor explicitly exercises review mechanics, not author publication.
    candidate = eligible[0]
    append_decision(
        run_dir,
        subject_id=candidate.candidate_id,
        action="accept",
        actor="integration-test",
        reason="Protocol integration fixture, not an experimental accuracy claim",
    )
    manifest = create_ensemble_manifest(
        run_dir, [candidate.candidate_id], actor="integration-test", reason="Test handoff"
    )
    acknowledgment = acknowledge_torq(
        run_dir,
        manifest["manifest_sha256"],
        actor="test-torq",
        schema_version="topos-ensemble/0.1.0",
    )
    assert acknowledgment["manifest_sha256"] == manifest["manifest_sha256"]
    bundle = tmp_path / "bundle"
    exported = export_bundle(run_dir, bundle)
    assert verify_bundle(bundle) == exported
    assert exported["publication_status"] == "not-published"
    rows = list(csv.DictReader((bundle / "selected.csv").open()))
    assert len(rows) == 1 and rows[0]["gibbs_energy_hartree"] == ""
    assert float(rows[0]["electronic_energy_hartree"]) == candidate.energy_hartree
    assert len(json.loads((bundle / "candidate-ledger.json").read_text())) == 3
    assert not any("TOKEN" in item["path"] for item in exported["files"])
    with pytest.raises(IntegrityError):
        acknowledge_torq(
            run_dir, "0" * 64, actor="test-torq", schema_version="topos-ensemble/0.1.0"
        )


@pytest.mark.integration
def test_unavailable_resume_creates_new_linked_real_attempt(tmp_path):
    binary = executable()
    config = SystemConfig(executables={"xtb": str(tmp_path / "absent")})
    workflow = Workflow(tmp_path, config=config)
    missing = workflow.run(request(n_candidates=1))
    old = missing.attempts[0].model_dump()
    config.executables["xtb"] = binary
    resumed = workflow.resume(tmp_path / missing.run_id)
    assert resumed.status == "completed"
    assert len(resumed.attempts) == 2
    assert resumed.attempts[0].model_dump() == old
    assert resumed.attempts[1].parent_attempt_id == old["attempt_id"]
    assert resumed.metadata["continuations"]
    assert sum(c.status == "eligible" for c in resumed.candidates) == 1
    assert resumed.candidates[0].energy_hartree is None


@pytest.mark.integration
def test_real_crest_union_is_refined_and_all_sources_preserved(tmp_path):
    binary = executable()
    crest = shutil.which(os.environ.get('TOPOS_CREST_EXECUTABLE', 'crest'))
    if not crest:
        pytest.skip('real CREST executable unavailable; no ensemble simulated')
    # CREST MD isotope inputs are unvalidated, so this fixture declares natural defaults.
    molecule = water().model_copy(update={'isotopes': [None, None, None]})
    config = SystemConfig(executables={'xtb': binary, 'crest': crest})
    result = Workflow(tmp_path, config=config).run(RunRequest(molecule=molecule, search_algorithm='union', sampler_profile='crest-mquick-v1', n_candidates=2, seed=73, budget_seconds=90, profile_id='xtb-vtight-v1'))
    assert result.status == 'completed'
    samplers = [a for a in result.attempts if a.engine == 'crest']
    assert len(samplers) == 1 and samplers[0].engine_version == '3.0.2'
    assert samplers[0].metadata['effective_seed'] is None
    assert samplers[0].metadata['raw_ensemble']
    assert samplers[0].metadata['potential_engine_version'] == '6.7.1'
    assert all(c.attempt_id != samplers[0].attempt_id for c in result.candidates)
    eligible = [c for c in result.candidates if c.status == 'eligible']
    assert len(eligible) == 1
    assert set(eligible[0].sources) == {'INITIAL_SEED', 'JIGGLE_QUENCH', 'CREST'}
    assert result.metadata['search_summary']['exhaustive'] is False
    assert any(c['doi'] == '10.1063/5.0197592' for c in result.metadata['citations'] if 'doi' in c)
    assert all(a.engine == 'xtb' for a in result.attempts if a.attempt_id in {c.attempt_id for c in result.candidates})
