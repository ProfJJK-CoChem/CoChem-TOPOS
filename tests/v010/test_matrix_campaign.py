"""Campaign proof guards; only an actual xTB full row supplies a passing case."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from topos.campaign_authority import base_authority_evidence, retained_registries
from topos.config import SystemConfig
from topos.matrix_campaign import (
    CampaignPlan,
    _native_evidence,
    _predeclaration_evidence,
    assess,
    create_plan,
    main,
    verify_report,
)
from topos.method_matrix import MATRIX_REVISION
from topos.models import Artifact, Attempt, Molecule, RunRecord, RunRequest
from topos.release import source_inventory
from topos.storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest
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
    assert report["release_eligible"] is False and report["release_eligible_rows"] == 0
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


@pytest.fixture
def authority_guard_contract(tmp_path):
    """Control-plane contracts only; these contain no scientific native output."""
    schema = pytest.importorskip("cochem_base.cochem_core_registry_schema")
    phase_reports = [{"phase_number": i, "status": "PASSED", "success": True,
                      "report": {"phase_id": f"authority-guard-only-{i}", "status": "PASSED", "errors": []}}
                     for i in range(1, 12)]
    registry = schema.CoChemSystemConfig.model_validate({
        "status": "ACTIVE", "hardware": {"ram_gb": 4, "allocatable_compute_cores": 2, "maxcore_mb": 1024},
        "engines": {"xtb": {"status": "found", "path": "/authority-guard-only/xtb", "hash": "a" * 64}},
        "stage0": {"completed_at": "2026-10-07T12:00:00+00:00", "phases": [
            {"phase_number": entry["phase_number"], "status": "PASSED",
             "sha256": hashlib.sha256(json.dumps(entry["report"], sort_keys=True).encode()).hexdigest()}
            for entry in phase_reports]},
    })
    # BASE fills legacy hardware aliases on round-trip; checksum the canonical
    # persisted schema rather than the initial compact constructor arguments.
    registry = schema.CoChemSystemConfig.model_validate(registry.model_dump(mode="json"))
    registry.update_checksum()
    path = tmp_path / "registry.json"
    atomic_json(path, registry.model_dump(mode="json"))
    atomic_json(tmp_path / "setup_summary.json", {"dry_run": False, "registry_path": str(path),
                                                 "artifact_dir": str(path.parent.parent), "phases_executed": phase_reports})
    registries, _ = retained_registries(tmp_path, [path])
    authority = {"backend": "cochem-base", "registry_sha256": file_digest(path),
                 "registry_path": str(path),
                 "registry_checksum": registry.registry_checksum,
                 "ecosystem": {"available": True, "problems": [], "components": {
                     name: {"available": True} for name in ("CoChem-BASE", "CoChem-TOPOS", "CoChem-TORQ")}}}
    record = RunRecord(request=request(), metadata={"execution_provider": "CoChem-BASE", "execution_authority": authority,
                                                   "matrix_execution": {"children": []}})
    # A native identity contract, not calculation output or a campaign receipt.
    record.attempts.append(Attempt(run_id=record.run_id, engine="xtb", method="GFN2-xTB", status="completed",
                                  command=["/authority-guard-only/xtb"], metadata={"executable_sha256": "a" * 64}))
    store = RunStore(tmp_path / "contract-only")
    store.commit(record)
    return tmp_path, path, registries, record, store


@pytest.mark.parametrize("change", ["development", "missing-registry", "checksum", "binary", "path", "allocation"])
def test_base_authority_guard_rejects_backend_labels_without_exact_audit(authority_guard_contract, change):
    _, _, registries, record, store = authority_guard_contract
    raw = record.model_dump(mode="json")
    if change == "development":
        raw["metadata"]["execution_authority"]["backend"] = "development"
    elif change == "missing-registry":
        registries = {}
    elif change == "checksum":
        raw["metadata"]["execution_authority"]["registry_checksum"] = "c" * 64
    elif change == "binary":
        raw["attempts"][0]["metadata"]["executable_sha256"] = "c" * 64
    elif change == "path":
        raw["attempts"][0]["command"][0] = "/authority-guard-only/unaudited-wrapper"
    else:
        raw["request"]["threads"] = 3
    with pytest.raises(IntegrityError):
        base_authority_evidence(raw, store, registries)


def test_retained_base_audit_is_portable_and_checksum_tampering_fails(authority_guard_contract, tmp_path):
    root, path, registries, record, store = authority_guard_contract
    proof = base_authority_evidence(record.model_dump(mode="json"), store, registries)
    assert proof["native_attempts"][0]["executable_sha256"] == "a" * 64
    relocated = tmp_path / "relocated"
    relocated.mkdir()
    copied = relocated / path.name
    shutil.copyfile(path, copied)
    shutil.copyfile(root / "setup_summary.json", relocated / "setup_summary.json")
    assert retained_registries(relocated, [copied])[0] == registries
    wrong = json.loads(copied.read_text())
    wrong["hardware"]["ram_gb"] = 8
    atomic_json(copied, wrong)
    with pytest.raises(IntegrityError, match="checksum"):
        retained_registries(relocated, [copied])
    with pytest.raises(IntegrityError, match="inside the campaign bundle"):
        retained_registries(relocated, [root / path.name])


@pytest.mark.parametrize("change", ["missing", "report-bytes", "unexecuted", "audit-errors", "dry-run"])
def test_registry_checksum_cannot_replace_actual_eleven_phase_reports(authority_guard_contract, change):
    root, path, _, _, _ = authority_guard_contract
    summary_path = root / "setup_summary.json"
    summary = json.loads(summary_path.read_text())
    if change == "missing":
        summary_path.unlink()
    else:
        if change == "report-bytes":
            summary["phases_executed"][0]["report"]["unreviewed_field"] = "changed actual report bytes"
        elif change == "unexecuted":
            summary["phases_executed"].pop()
        elif change == "audit-errors":
            summary["phases_executed"][0]["report"]["errors"] = ["unresolved audit error"]
        else:
            summary["dry_run"] = True
        atomic_json(summary_path, summary)
    with pytest.raises(IntegrityError):
        retained_registries(root, [path])


@pytest.mark.parametrize("status,success", [("FAILED", False), ("FAILED", True), ("SKIPPED", False),
                                           ("SKIPPED", True), ("PASSED", False), ("DEGRADED", True)])
def test_consistent_rechecksummed_phase_outcomes_require_successful_execution(authority_guard_contract, status, success):
    """All recorded digests/statuses agree; unsuccessful audit still rejects."""
    root, path, _, _, _ = authority_guard_contract
    schema = pytest.importorskip("cochem_base.cochem_core_registry_schema")
    registry = schema.CoChemSystemConfig.model_validate(json.loads(path.read_text()))
    summary_path = root / "setup_summary.json"
    summary = json.loads(summary_path.read_text())
    entry = summary["phases_executed"][0]
    entry.update(status=status, success=success)
    entry["report"]["status"] = status
    assert entry["report"]["errors"] == []
    phase = registry.stage0.phases[0]
    phase.status = status
    phase.sha256 = hashlib.sha256(json.dumps(entry["report"], sort_keys=True).encode()).hexdigest()
    registry.update_checksum()
    assert registry.verify_checksum()
    assert entry["status"] == phase.status == entry["report"]["status"]
    assert phase.sha256 == hashlib.sha256(json.dumps(entry["report"], sort_keys=True).encode()).hexdigest()
    atomic_json(path, registry.model_dump(mode="json"))
    atomic_json(summary_path, summary)
    if status == "DEGRADED" and success:
        _, receipts = retained_registries(root, [path])
        assert receipts[0]["verified_phase_reports"][0]["status"] == "DEGRADED"
    else:
        with pytest.raises(IntegrityError):
            retained_registries(root, [path])


@pytest.mark.parametrize("change", [None, "scan-gradient-child", "development-child", "changed-copy", "missing-child"])
def test_copied_child_requires_its_exact_independent_base_authority(authority_guard_contract, change):
    _, _, registries, record, store = authority_guard_contract
    from topos.matrix_workflow import _append_child

    child = record.model_copy(deep=True)
    child.run_id = "run_authority_child_guard"
    child.attempts[0].run_id = child.run_id
    child.attempts[0].attempt_id = "attempt_authority_child_guard"
    if change == "development-child":
        child.metadata["execution_authority"]["backend"] = "development"
    child_dir = store.run_dir / "children" / child.run_id
    _append_child(record, child, store.run_dir, child_dir, "authority-guard", include_candidates=False)
    record.metadata["matrix_execution"]["children"] = [{"task_id": "authority-guard", "run_id": child.run_id,
                                                        "record_sha256": digest_json(child.model_dump(mode="json"))}]
    store.commit(record)
    raw = store.load()
    if change == "scan-gradient-child":
        raw["metadata"]["matrix_execution"]["children"] = []
    elif change == "changed-copy":
        raw["attempts"][-1]["command"].append("--unreviewed-option")
    elif change == "missing-child":
        raw["artifacts"] = []
    if change in (None, "scan-gradient-child"):
        assert base_authority_evidence(raw, store, registries)["child_run_ids"] == [child.run_id]
    else:
        with pytest.raises(IntegrityError):
            base_authority_evidence(raw, store, registries)


def test_campaign_cannot_promote_missing_42_base_rows_by_editing_release_boolean(tmp_path):
    plan_path, report_path = tmp_path / "declared.json", tmp_path / "report.json"
    atomic_json(plan_path, create_plan(ROOT))
    report = assess(plan_path, [], ROOT)
    report["release_eligible"] = True
    report["release_eligible_rows"] = 42
    report["status"] = "passed"
    atomic_json(report_path, report)
    with pytest.raises(IntegrityError, match="differs"):
        verify_report(report_path, ROOT)


@pytest.mark.parametrize("change", [None, "manifest", "zero", "partial", "boolean", "missing-session", "missing-binary"])
def test_extopt_callback_contract_cannot_be_bypassed_by_present_native_hash(tmp_path, change):
    """Consumer metadata guard only; no ExtOpt process/model result is claimed.

    The normal-termination bytes are an unmodified historical native HF-3c
    parser fixture. Callback fields below are explicitly control-plane inputs,
    not an actual callback receipt or a complete matrix/scientific calculation.
    """
    fixture = ROOT / "tests/v010/fixtures/orca611"
    provenance = json.loads((fixture / "provenance.json").read_text())
    native = fixture / "hf3c-water-native.stdout"
    assert file_digest(native) == provenance["files"][native.name]
    store = RunStore(tmp_path / "extopt-metadata-guard-only")
    output = store.run_dir / "native-fixture.stdout"
    shutil.copyfile(native, output)
    metadata = {"execution_kind": "real", "executable_sha256": "d" * 64, "manifest_sha256": "e" * 64,
                "server_summary": {"manifest_sha256": "e" * 64, "requests": 2, "successful_requests": 2}}
    if change == "manifest":
        metadata["server_summary"]["manifest_sha256"] = "f" * 64
    elif change == "zero":
        metadata["server_summary"].update(requests=0, successful_requests=0)
    elif change == "partial":
        metadata["server_summary"]["successful_requests"] = 1
    elif change == "boolean":
        metadata["server_summary"].update(requests=True, successful_requests=True)
    elif change == "missing-session":
        metadata["server_summary"] = None
    elif change == "missing-binary":
        metadata.pop("executable_sha256")
    record = RunRecord(request=request())
    record.attempts.append(Attempt(run_id=record.run_id, engine="orca", method="HF-3c",
        command=["/nonexecuted-metadata-guard-only/orca", "original-hf3c-input.inp"], status="completed", converged=True,
        engine_version="6.1.1", validation_status="validated-for-protocol", metadata=metadata,
        artifacts=[Artifact(path=output.name, sha256=file_digest(output), size_bytes=output.stat().st_size, role="raw-output")]))
    store.commit(record)
    if change is None:
        assert _native_evidence(store.load(), store)[0]["identity_sha256"] == metadata["executable_sha256"]
    else:
        with pytest.raises(IntegrityError, match="hashed executable" if change == "missing-binary" else "callback session"):
            _native_evidence(store.load(), store)


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
    assert report["status"] == "pending"
    assert report["release_eligible"] is False and report["release_eligible_rows"] == 0
    assert row["release_eligible"] is False
    assert "BASE execution authority" in row["results"][0]["evidence"]["release_blocker"]
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
