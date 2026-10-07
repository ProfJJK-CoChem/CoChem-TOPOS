"""Campaign proof guards; only an actual xTB full row supplies a passing case."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from topos.config import SystemConfig
from topos.matrix_campaign import (
    CampaignPlan,
    _predeclaration_evidence,
    assess,
    create_plan,
    main,
    verify_report,
)
from topos.method_matrix import MATRIX_REVISION
from topos.models import Attempt, Molecule, RunRecord, RunRequest
from topos.release import source_inventory
from topos.storage import IntegrityError, RunStore, atomic_json
from topos.workflow import Workflow

ROOT = Path(__file__).resolve().parents[2]


def request(row="T3O-10s", **changes):
    return RunRequest(molecule=Molecule(symbols=["O", "H", "H"],
                      coordinates=[[0, 0, 0], [.9572, 0, 0], [-.23999, .9273, 0]]),
                      purpose="matrix", matrix_revision=MATRIX_REVISION, matrix_row_id=row,
                      budget_seconds=30, threads=1, memory_mb=256, n_candidates=1, **changes)


def frozen_sources(destination):
    for relative in source_inventory(ROOT):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return destination


def test_inventory_preserves_exact_owner_scope_and_two_unavailable_rows(tmp_path):
    plan = create_plan(ROOT)
    assert len(plan["available_rows"]) == 42
    assert plan["torq_owned_rows_excluded"] == 96
    assert [entry["row_id"] for entry in plan["unavailable_by_design"]] == ["T3C-10s", "T3C-1min"]
    assert all(entry["source_excerpt"] == "CFOUR has no 10 s or 1 min entry" for entry in plan["unavailable_by_design"])
    path = tmp_path / "declared.json"
    atomic_json(path, plan)
    report = assess(path, [], ROOT)
    assert report["status"] == "blocked"
    assert report["counts"] == {"passed": 0, "failed": 0, "pending": 42}
    assert not plan["cases"]


@pytest.mark.parametrize("row", ["T3C-10s", "T3C-1min", "T4O-1h"])
def test_unavailable_and_torq_rows_cannot_be_declared_as_topos_cases(row):
    with pytest.raises(ValueError, match="42 available TOPOS"):
        create_plan(ROOT, [request(row).model_dump(mode="json")])


def test_case_definition_binds_molecule_state_resources_and_compiled_protocol():
    plan = create_plan(ROOT, [request().model_dump(mode="json")])
    assert plan["cases"][0]["recipe"]["row"]["row_id"] == "T3O-10s"
    corrupt = copy.deepcopy(plan)
    corrupt["cases"][0]["request"]["memory_mb"] = 512
    with pytest.raises(ValueError, match="exact typed scientific definition"):
        CampaignPlan.model_validate(corrupt)
    with pytest.raises(ValueError, match="at most one"):
        create_plan(ROOT, [request().model_dump(mode="json")] * 2)
    with pytest.raises(ValueError, match="Predeclare all scientific inputs"):
        create_plan(ROOT, [request("T1-10s").model_dump(mode="json")])
    with pytest.raises(ValueError, match="compatibility branch"):
        create_plan(ROOT, [request("T3O-1mo", matrix_inputs={"source_resolution": "orca-f12-reference-singlepoint-v1"}).model_dump(mode="json")])


def test_cli_plan_and_assess_do_not_execute_or_claim_coverage(tmp_path):
    sources = frozen_sources(tmp_path / "frozen-source")
    path = tmp_path / "campaign.json"
    report = tmp_path / "report.json"
    planned = subprocess.run([sys.executable, "-m", "topos.matrix_campaign", "plan", "--source-root", str(sources),
                              "--output", str(path)], capture_output=True, text=True)
    assert planned.returncode == 0, planned.stderr
    assessed = subprocess.run([sys.executable, "-m", "topos.matrix_campaign", "assess", "--source-root", str(sources),
                               "--plan", str(path), "--output", str(report)], capture_output=True, text=True)
    assert assessed.returncode == 3, assessed.stderr
    assert verify_report(report, sources)["counts"]["pending"] == 42
    assert not (tmp_path / "runs").exists()


def test_main_accepts_delegated_arguments_and_reports_require_owned_bundle(tmp_path):
    path = tmp_path / "declared.json"
    assert main(["plan", "--source-root", str(ROOT), "--output", str(path)]) == 0
    with pytest.raises(IntegrityError, match="campaign plan bundle"):
        assess(path, [tmp_path.parent / "foreign-run"], ROOT)
    with pytest.raises(SystemExit):
        main(["assess", "--source-root", str(ROOT), "--plan", str(path),
              "--output", str(tmp_path / "another-root" / "report.json")])


@pytest.mark.parametrize("started_at", [None, "2026-10-07T11:59:59+00:00"])
def test_predeclared_plan_rejects_missing_or_cached_native_launch_time(tmp_path, started_at):
    # Timestamp guard regression only: a failed attempt with no scientific
    # artifact is deliberately not executable/campaign acceptance evidence.
    declared = "2026-10-07T12:00:00+00:00"
    record = RunRecord(request=request(), created_at="2026-10-07T12:00:01+00:00",
                       updated_at="2026-10-07T12:00:02+00:00")
    record.attempts.append(Attempt(run_id=record.run_id, engine="xtb", method="GFN2-xTB",
                                  status="failed", command=["/missing-test-executable"],
                                  metadata={"execution_kind": "real"}, started_at=started_at))
    store = RunStore(tmp_path / "timestamp-guard-only")
    store.commit(record)
    with pytest.raises(IntegrityError, match="launch timestamp"):
        _predeclaration_evidence(store.load(), store, declared)


def test_predeclaration_verifies_earlier_snapshots_not_only_repackaged_current_record(tmp_path):
    declared = "2026-10-07T12:00:00+00:00"
    record = RunRecord(request=request(), created_at="2026-10-07T11:59:59+00:00",
                       updated_at="2026-10-07T11:59:59+00:00")
    store = RunStore(tmp_path / "historical-guard-only")
    store.commit(record)
    record.created_at = "2026-10-07T12:00:01+00:00"
    record.updated_at = "2026-10-07T12:00:02+00:00"
    store.commit(record)
    with pytest.raises(IntegrityError, match="history predates"):
        _predeclaration_evidence(store.load(), store, declared)


def test_postdeclaration_history_is_verified_and_missing_history_members_fail(tmp_path):
    declared = "2026-10-07T12:00:00+00:00"
    record = RunRecord(request=request(), created_at="2026-10-07T12:00:01+00:00",
                       updated_at="2026-10-07T12:00:02+00:00")
    store = RunStore(tmp_path / "history-guard-only")
    first = store.commit(record)
    record.metadata["timestamp_test_only"] = True
    second = store.commit(record)
    assert _predeclaration_evidence(store.load(), store, declared) == sorted([first["snapshot_id"], second["snapshot_id"]])
    (store.snapshots / first["snapshot_id"] / "record.h5").unlink()
    with pytest.raises(IntegrityError):
        _predeclaration_evidence(store.load(), store, declared)


@pytest.fixture(scope="module")
def actual_row(tmp_path_factory):
    choices = [os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"),
               "/workspace/.cochem-base-runtime/free-engines/xtb/xtb-dist/bin/xtb"]
    executable = next((found for choice in choices if (found := shutil.which(choice))), None)
    if not executable:
        pytest.skip("Actual xTB is required; no native matrix success is simulated")
    root = tmp_path_factory.mktemp("actual-matrix-campaign")
    sources = frozen_sources(root / "source")
    plan_path = root / "predeclared.json"
    atomic_json(plan_path, create_plan(sources, [request().model_dump(mode="json")]))
    record = Workflow(root / "runs", config=SystemConfig(execution_backend="development",
                      executables={"xtb": executable})).run(request())
    assert record.status == "completed", record.metadata.get("termination_reason")
    store = RunStore(record.metadata["run_dir"])
    report = assess(plan_path, [store.run_dir], sources)
    assert report["counts"] == {"passed": 1, "failed": 0, "pending": 41}, report
    return root, sources, plan_path, store, record


def clone_store(store, destination):
    shutil.copytree(store.run_dir, destination)
    return RunStore(destination)


@pytest.mark.integration
def test_genuine_current_source_matrix_row_is_counted_once_and_report_reverifies(actual_row, tmp_path):
    root, sources, plan_path, store, _ = actual_row
    report = assess(plan_path, [store.run_dir], sources)
    path = root / "receipt.json"
    atomic_json(path, report)
    assert verify_report(path, sources) == report
    relocated = tmp_path / "relocated-campaign"
    shutil.copytree(root, relocated)
    assert verify_report(relocated / path.name, relocated / "source") == report
    assert not Path(report["plan_path"]).is_absolute()
    assert all(not Path(path).is_absolute() for path in report["candidate_runs"])
    row = next(item for item in report["rows"] if item["row_id"] == "T3O-10s")
    assert row["status"] == "passed"
    assert row["results"][0]["evidence"]["native_attempts"]
    assert report["status"] == "blocked"
    with pytest.raises(IntegrityError, match="Duplicate"):
        assess(plan_path, [store.run_dir, store.run_dir], sources)
    forged = copy.deepcopy(report)
    forged["status"] = "passed"
    forged["counts"]["passed"] = 42
    atomic_json(path, forged)
    with pytest.raises(IntegrityError, match="differs"):
        verify_report(path, sources)


@pytest.mark.integration
@pytest.mark.parametrize("change,reason", [
    ("partial", "complete full-row"), ("compatibility", "complete full-row"),
    ("wrong-request", "identity differs"), ("stale-source", "source identity"),
    ("wrong-row", "no matching predeclared"), ("wrong-protocol", "compiler protocol"),
    ("fake-kind", "actual converged execution"), ("zero-native", "without actual native attempts"),
])
def test_failed_partial_stale_or_faked_receipts_cannot_supply_matrix_coverage(actual_row, tmp_path, change, reason):
    _, sources, plan_path, original_store, _ = actual_row
    local_plan = tmp_path / plan_path.name
    shutil.copyfile(plan_path, local_plan)
    store = clone_store(original_store, tmp_path / "candidate")
    record = RunRecord.model_validate(store.load())
    if change == "partial":
        record.status = "partial"
    elif change == "compatibility":
        record.metadata["matrix_execution"]["full_row_completed"] = False
    elif change == "wrong-request":
        record.metadata["request_sha256"] = "a" * 64
    elif change == "stale-source":
        record.metadata["software"]["source_files"]["topos/matrix_workflow.py"] = "a" * 64
    elif change == "wrong-row":
        record.metadata["matrix_execution"]["row_id"] = "T3O-30min"
    elif change == "wrong-protocol":
        record.metadata["matrix_plan"]["steps"][0]["method"] = "fabricated substitute"
    else:
        # Create a distinct initial record for deliberately invalid proof: a
        # finished attempt may never be rewritten inside its original history.
        raw = record.model_dump(mode="json")
        if change == "zero-native":
            raw["attempts"] = []
            raw["candidates"] = []
        else:
            raw["attempts"][0]["metadata"]["execution_kind"] = "mock"
        other = RunStore(tmp_path / "invalid-initial-proof")
        for artifact in original_store.verify()["artifacts"]:
            target = other.run_dir / artifact["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original_store.snapshot_path() / "artifacts" / artifact["path"], target)
        other.commit(raw)
        store = other
    if change not in {"fake-kind", "zero-native"}:
        store.commit(record)
    report = assess(local_plan, [store.run_dir], sources)
    assert report["counts"]["passed"] == 0
    failures = report["invalid_candidates"] + [result for row in report["rows"] for result in row["results"] if result["status"] == "failed"]
    assert any(reason in failure["reason"] for failure in failures), failures


@pytest.mark.integration
def test_changed_source_or_plan_and_corrupt_snapshot_fail_closed(actual_row, tmp_path):
    _, sources, plan_path, original_store, _ = actual_row
    changed = tmp_path / "changed-source"
    shutil.copytree(sources, changed)
    with (changed / "topos/matrix_workflow.py").open("a") as writer:
        writer.write("\n# source drift\n")
    with pytest.raises(IntegrityError, match="current source"):
        assess(plan_path, [original_store.run_dir], changed)
    altered_plan = json.loads(plan_path.read_text())
    altered_plan["declared_at"] = "2099-01-01T00:00:00+00:00"
    altered_path = tmp_path / "post-hoc.json"
    atomic_json(altered_path, altered_plan)
    copied = clone_store(original_store, tmp_path / "known-run")
    report = assess(altered_path, [copied.run_dir], sources)
    assert report["counts"]["passed"] == 0
    assert "post-hoc" in next(row for row in report["rows"] if row["results"])["results"][0]["reason"]
    corrupted = clone_store(original_store, tmp_path / "corrupt-run")
    local_plan = tmp_path / plan_path.name
    shutil.copyfile(plan_path, local_plan)
    raw = next((corrupted.snapshot_path() / "artifacts").rglob("engine.stdout"))
    raw.write_text("fabricated output replacement")
    assert assess(local_plan, [corrupted.run_dir], sources)["invalid_candidates"]
