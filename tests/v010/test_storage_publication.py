"""Real filesystem and process tests for commit/review/export integrity.

The tiny numerical child process is explicitly an analytical unit-test engine,
not evidence that xTB, ORCA or a research chemistry calculation succeeded.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import h5py
import pytest
from filelock import Timeout

from topos.models import Artifact, Attempt, Candidate, Molecule, Quantity, RunRecord, RunRequest
from topos.publication import export_bundle, verify_bundle
from topos.review import (
    acknowledge_torq,
    append_decision,
    create_ensemble_manifest,
    get_ensemble_manifest,
    list_decisions,
)
from topos.storage import IntegrityError, RunStore


def make_record(directory: Path, run_id: str = "run_test") -> RunRecord:
    directory.mkdir(parents=True, exist_ok=True)
    molecule = Molecule(symbols=["H", "H"], coordinates=[[0, 0, 0], [0, 0, 0.74]])
    attempt_directory = directory / "attempts" / "numerical"
    attempt_directory.mkdir(parents=True)
    # Real analytical evaluation in a child process, with captured stdout/stderr.
    command = [sys.executable, "-c", "import json; r=0.74; print(json.dumps({'energy': 0.5*(r-0.74)**2}))"]
    process = subprocess.run(command, capture_output=True, check=True, timeout=10)
    (attempt_directory / "stdout.json").write_bytes(process.stdout)
    (attempt_directory / "input.xyz").write_text("2\nanalytical fixture\nH 0 0 0\nH 0 0 0.74\n")
    (attempt_directory / "stderr.txt").write_bytes(process.stderr)
    artifacts = []
    for name, role in (("stdout.json", "raw-output"), ("input.xyz", "input"), ("stderr.txt", "stderr")):
        path = attempt_directory / name
        artifacts.append(Artifact(
            path=path.relative_to(directory).as_posix(),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size_bytes=path.stat().st_size,
            role=role,
        ))
    attempt = Attempt(
        attempt_id="attempt_analytic", run_id=run_id, engine="analytical-test",
        method="harmonic-unit-test", status="completed", converged=True,
        validation_status="validated-for-protocol", command=command,
        engine_version=sys.version.split()[0], artifacts=artifacts,
        metadata={"execution_kind": "real", "scope": "analytical unit-test fixture",
                  "output_molecule": molecule.model_dump(mode="json"),
                  "comparison_protocol": "analytical-unit-test-v1"},
    )
    candidate = Candidate(
        candidate_id="candidate_selected", molecule=molecule, attempt_id=attempt.attempt_id,
        energy_hartree=json.loads(process.stdout)["energy"],
        comparison_protocol="analytical-unit-test-v1",
    )
    attempt.quantities.append(Quantity(
        name="electronic_energy", value=candidate.energy_hartree, units="hartree",
        definition="Analytical unit-test harmonic energy", attempt_id=attempt.attempt_id,
        geometry_id=candidate.candidate_id, method=attempt.method, validity="validated-for-protocol",
    ))
    return RunRecord(
        run_id=run_id, request=RunRequest(molecule=molecule), status="completed",
        validation_status="validated-for-protocol", attempts=[attempt], candidates=[candidate],
    )


def reviewed(directory: Path, record: RunRecord | None = None) -> tuple[RunRecord, dict]:
    record = record or make_record(directory)
    RunStore(directory).commit(record)
    append_decision(directory, subject_id=record.candidates[0].candidate_id,
                    action="accept", actor="unit-test reviewer", reason="Analytical fixture checked")
    ensemble = create_ensemble_manifest(directory, [record.candidates[0].candidate_id], actor="reviewer")
    return record, ensemble


def test_hdf5_roundtrip_explicit_artifacts_and_closed_handles(tmp_path):
    record = make_record(tmp_path)
    store = RunStore(tmp_path)
    manifest = store.commit(record)
    assert store.load() == record.model_dump(mode="json")
    assert store.commit(record) == manifest
    assert len(list(store.snapshots.iterdir())) == 1
    snapshot = store.snapshot_path()
    with h5py.File(snapshot / "record.h5", "r") as handle:
        assert handle.attrs["run_id"] == record.run_id
        assert len(handle["candidates"]) == 1
        assert len(handle["deduplicated_isomers"]) == 0
        group = next(iter(handle["candidates"].values()))
        assert group["coordinates_angstrom"].dtype.name == "float64"
        assert group["coordinates_angstrom"].shape == (2, 3)
    # A source log changing later does not mutate the committed evidence.
    (tmp_path / record.attempts[0].artifacts[0].path).write_text("changed live scratch")
    assert store.verify() == manifest
    # Reader handles are closed, including on Windows.
    original = (snapshot / "record.h5").read_bytes()
    (snapshot / "record.h5").unlink()
    (snapshot / "record.h5").write_bytes(original)
    assert store.load()["run_id"] == record.run_id


def test_failed_next_commit_preserves_previous_snapshot(tmp_path):
    record = make_record(tmp_path)
    store = RunStore(tmp_path)
    before = store.commit(record)
    (tmp_path / record.attempts[0].artifacts[0].path).write_text("truncated output")
    changed = record.model_copy(deep=True)
    changed.metadata["new_attempt_requested"] = True
    with pytest.raises(IntegrityError, match="checksum mismatch"):
        store.commit(changed)
    assert store.verify() == before
    assert not list(store.snapshots.glob(".pending-*"))


def test_corruption_missing_artifact_and_membership_are_detected(tmp_path):
    record = make_record(tmp_path)
    store = RunStore(tmp_path)
    store.commit(record)
    snapshot = store.snapshot_path()
    artifact = snapshot / "artifacts" / record.attempts[0].artifacts[0].path
    original = artifact.read_bytes()
    artifact.write_bytes(b"corrupt")
    with pytest.raises(IntegrityError, match="checksum mismatch"):
        store.load()
    artifact.unlink()
    with pytest.raises(IntegrityError, match="Missing artifact"):
        store.load()
    artifact.write_bytes(original)
    (snapshot / "unlisted.txt").write_text("not a member")
    with pytest.raises(IntegrityError, match="payload files"):
        store.load()


def test_schema_dimensions_and_run_identity_are_rejected(tmp_path):
    record = make_record(tmp_path)
    store = RunStore(tmp_path)
    store.commit(record)
    invalid = record.model_dump(mode="json")
    invalid["candidates"][0]["molecule"]["coordinates"] = [[0, 0, 0]]
    with pytest.raises(IntegrityError, match="coordinates"):
        store.commit(invalid)
    invalid = record.model_dump(mode="json")
    invalid["schema_version"] = "future/7"
    with pytest.raises(IntegrityError):
        store.commit(invalid)
    changed = record.model_copy(deep=True)
    changed.request.seed = 82
    with pytest.raises(IntegrityError, match="Immutable input"):
        store.commit(changed)
    changed = record.model_copy(deep=True)
    changed.run_id = "other_run"
    changed.attempts[0].run_id = "other_run"
    with pytest.raises(IntegrityError, match="another run"):
        store.commit(changed)


def test_interrupted_stages_are_not_promoted_on_recovery(tmp_path):
    record = make_record(tmp_path)
    store = RunStore(tmp_path)
    expected = store.commit(record)
    abandoned = store.snapshots / ".pending-interrupted"
    abandoned.mkdir()
    (abandoned / "record.h5").write_bytes(b"incomplete write")
    assert store.recover() == record.model_dump(mode="json")
    assert store.verify() == expected
    store.current.unlink()
    with pytest.raises(FileNotFoundError, match="No committed"):
        store.recover()
    # Explicitly retrying the same record can finish pointer publication after
    # verifying the complete orphan; no partial pending directory is adopted.
    assert store.commit(record) == expected
    assert store.recover() == record.model_dump(mode="json")


def test_quota_failure_keeps_commit_unchanged(tmp_path):
    record = make_record(tmp_path)
    store = RunStore(tmp_path)
    manifest = store.commit(record)
    changed = record.model_copy(deep=True)
    changed.metadata["addition"] = "new"
    with pytest.raises(IntegrityError, match="quota"):
        RunStore(tmp_path, max_snapshot_bytes=1).commit(changed)
    assert store.verify() == manifest


def test_unavailable_initial_record_can_be_committed(tmp_path):
    record = make_record(tmp_path)
    record.attempts = []
    record.candidates = []
    record.status = "unavailable"
    record.validation_status = "not-evaluated"
    RunStore(tmp_path).commit(record)
    assert RunStore(tmp_path).recover()["status"] == "unavailable"


def test_independent_runs_and_concurrent_snapshot_readers(tmp_path):
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first, second = make_record(first_dir, "first"), make_record(second_dir, "second")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: RunStore(pair[0]).commit(pair[1]),
                                [(first_dir, first), (second_dir, second)]))
    assert {result["run_id"] for result in results} == {"first", "second"}
    def writer():
        for i in range(6):
            changed = first.model_copy(deep=True)
            changed.metadata["iteration"] = i
            RunStore(first_dir).commit(changed)
    def reader():
        for _ in range(12):
            assert RunStore(first_dir).load()["run_id"] == "first"
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(writer), pool.submit(reader), pool.submit(reader)]
        for future in futures:
            future.result(timeout=20)
    assert RunStore(second_dir).load()["run_id"] == "second"


def test_writer_lock_timeout_is_explicit(tmp_path):
    record = make_record(tmp_path)
    store = RunStore(tmp_path)
    with store.lock:
        with pytest.raises(Timeout):
            RunStore(tmp_path, lock_timeout=0.05).commit(record)


def test_path_escape_and_symlink_artifacts_are_rejected(tmp_path):
    record = make_record(tmp_path)
    record.attempts[0].artifacts[0].path = "../outside.log"
    with pytest.raises(IntegrityError, match="Unsafe"):
        RunStore(tmp_path).commit(record)
    record.attempts[0].artifacts[0].path = "linked.log"
    (tmp_path / "linked.log").symlink_to(tmp_path / "attempts/numerical/stdout.json")
    with pytest.raises(IntegrityError, match="Symlink"):
        RunStore(tmp_path).commit(record)


def test_review_requires_explicit_supersession_and_preserves_audit(tmp_path):
    record, ensemble = reviewed(tmp_path)
    first = list_decisions(tmp_path)[0]
    with pytest.raises(IntegrityError, match="supersede"):
        append_decision(tmp_path, subject_id="candidate_selected", action="reject",
                        actor="chemist", reason="Changed interpretation")
    rejection = append_decision(tmp_path, subject_id="candidate_selected", action="reject",
                                actor="chemist", reason="Changed interpretation", supersedes=first["decision_id"])
    assert list_decisions(tmp_path) == [first, rejection]
    with pytest.raises(IntegrityError, match="superseded"):
        get_ensemble_manifest(tmp_path)
    with pytest.raises(IntegrityError, match="superseded"):
        acknowledge_torq(tmp_path, ensemble["manifest_sha256"], actor="TORQ")
    assert RunStore(tmp_path).load() == record.model_dump(mode="json")


def test_torq_requires_current_digest_and_compatible_schema(tmp_path):
    _, ensemble = reviewed(tmp_path)
    ack = acknowledge_torq(tmp_path, ensemble["manifest_sha256"], actor="TORQ user")
    assert ack["scope"] == "manifest-receipt-only"
    with pytest.raises(IntegrityError, match="stale"):
        acknowledge_torq(tmp_path, "0" * 64, actor="TORQ")
    with pytest.raises(IntegrityError, match="incompatible"):
        acknowledge_torq(tmp_path, ensemble["manifest_sha256"], actor="TORQ", schema_version="future")


def test_new_run_commit_invalidates_old_review(tmp_path):
    record, ensemble = reviewed(tmp_path)
    record.metadata["analysis_revision"] = 2
    RunStore(tmp_path).commit(record)
    with pytest.raises(IntegrityError, match="stale"):
        get_ensemble_manifest(tmp_path)
    with pytest.raises(IntegrityError, match="stale"):
        create_ensemble_manifest(tmp_path, ensemble["member_ids"], actor="reviewer")


def test_review_chain_corruption_detected(tmp_path):
    reviewed(tmp_path)
    event = next((tmp_path / "review/events").glob("*.json"))
    payload = json.loads(event.read_text())
    payload["reason"] = "unrecorded edit"
    event.write_text(json.dumps(payload))
    with pytest.raises(IntegrityError, match="checksum"):
        list_decisions(tmp_path)


def test_bundle_reproducibility_nulls_failures_and_exact_membership(tmp_path):
    run_dir = tmp_path / "run"
    record = make_record(run_dir)
    record.candidates[0].energy_hartree = None
    failed = record.attempts[0].model_copy(deep=True)
    failed.attempt_id = "attempt_failed"
    failed.status = "failed"
    failed.converged = False
    failed.validation_status = "rejected"
    failed.diagnostics["reason"] = "Analytical fixture failure path"
    record.attempts.append(failed)
    excluded = record.candidates[0].model_copy(deep=True)
    excluded.candidate_id = "candidate_failed"
    excluded.attempt_id = failed.attempt_id
    excluded.status = "rejected"
    excluded.metadata["exclusion_reason"] = "Calculation failed"
    record.candidates.append(excluded)
    reviewed(run_dir, record)
    # An unlisted scratch file must not leak into publication.
    (run_dir / "unrelated.txt").write_text("outside explicit membership")
    first = export_bundle(run_dir, tmp_path / "bundle1")
    second = export_bundle(run_dir, tmp_path / "bundle2")
    assert first == second
    assert first["publication_ready"] is False
    assert first["version_doi"] is None
    assert first["unresolved"]
    assert verify_bundle(tmp_path / "bundle1") == first
    with (tmp_path / "bundle1/selected.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["electronic_energy_hartree"] == ""
    assert rows[0]["gibbs_energy_hartree"] == ""
    assert "not reported" in rows[0]["missing_values"]
    ledger = json.loads((tmp_path / "bundle1/candidate-ledger.json").read_text())
    assert ledger[1]["candidate"]["molecule"] == excluded.molecule.model_dump(mode="json")
    assert ledger[1]["exclusion_reason"] == "Calculation failed"
    assert not any("unrelated" in a["path"] for a in first["files"])
    with pytest.raises(FileExistsError):
        export_bundle(run_dir, tmp_path / "bundle1")


@pytest.mark.parametrize("change", ["status", "validation", "execution", "version", "output"])
def test_review_cannot_promote_noneligible_calculation(tmp_path, change):
    record = make_record(tmp_path)
    attempt = record.attempts[0]
    if change == "status":
        attempt.status = "partial"
    elif change == "validation":
        attempt.validation_status = "not-evaluated"
    elif change == "execution":
        attempt.metadata["execution_kind"] = "demonstration"
    elif change == "version":
        attempt.engine_version = None
    else:
        attempt.artifacts = []
    RunStore(tmp_path).commit(record)
    append_decision(tmp_path, subject_id="candidate_selected", action="accept", actor="reviewer", reason="review")
    with pytest.raises(IntegrityError):
        create_ensemble_manifest(tmp_path, ["candidate_selected"], actor="reviewer")


def test_bundle_corruption_and_unlisted_files_are_rejected(tmp_path):
    reviewed(tmp_path / "run")
    export_bundle(tmp_path / "run", tmp_path / "bundle")
    table = tmp_path / "bundle/selected.csv"
    original = table.read_bytes()
    table.write_bytes(original.replace(b"0.0", b"9.9"))
    with pytest.raises(IntegrityError, match="checksum"):
        verify_bundle(tmp_path / "bundle")
    table.write_bytes(original)
    (tmp_path / "bundle/extra.txt").write_text("unlisted")
    with pytest.raises(IntegrityError, match="membership"):
        verify_bundle(tmp_path / "bundle")


@pytest.mark.parametrize("field", ["energy", "geometry", "protocol", "rejected", "duplicate"])
def test_human_acceptance_cannot_certify_changed_scientific_payload(tmp_path, field):
    record = make_record(tmp_path)
    candidate = record.candidates[0]
    if field == "energy":
        candidate.energy_hartree = 0.25
    elif field == "geometry":
        candidate.molecule.coordinates[1][2] = 0.85
    elif field == "protocol":
        candidate.comparison_protocol = "unrelated-method"
    else:
        candidate.status = field
    RunStore(tmp_path).commit(record)
    append_decision(tmp_path, subject_id=candidate.candidate_id, action="accept", actor="reviewer", reason="review")
    with pytest.raises(IntegrityError):
        create_ensemble_manifest(tmp_path, [candidate.candidate_id], actor="reviewer")


def test_committed_attempts_and_candidate_science_are_immutable(tmp_path):
    record = make_record(tmp_path)
    store = RunStore(tmp_path)
    before = store.commit(record)
    changed = record.model_copy(deep=True)
    changed.attempts[0].command = ["different-engine"]
    with pytest.raises(IntegrityError, match="finished attempt is immutable"):
        store.commit(changed)
    changed = record.model_copy(deep=True)
    changed.candidates[0].energy_hartree = 42
    with pytest.raises(IntegrityError, match="scientific payload is immutable"):
        store.commit(changed)
    assert store.verify() == before


def test_explicit_derived_optimizer_uses_accepted_real_derivative(tmp_path):
    record = make_record(tmp_path)
    source = record.attempts[0]
    derived = source.model_copy(deep=True)
    derived.attempt_id = "attempt_derived"
    derived.parent_attempt_id = source.attempt_id
    derived.command = ["topos-internal", "rigid-body-optimize"]
    derived.metadata.update({
        "result_kind": "derived-optimization", "algorithm": "TOPOS rigid-body optimizer",
        "accepted_derivative_attempt_id": source.attempt_id,
        "derivative_attempt_ids": [source.attempt_id],
    })
    for quantity in derived.quantities:
        quantity.attempt_id = derived.attempt_id
    record.attempts.append(derived)
    record.candidates[0].attempt_id = derived.attempt_id
    reviewed(tmp_path, record)
    exported = export_bundle(tmp_path, tmp_path.parent / (tmp_path.name + "-derived-bundle"))
    assert exported["selected_member_ids"] == ["candidate_selected"]
    methods = (tmp_path.parent / (tmp_path.name + "-derived-bundle") / "methods.md").read_text()
    assert "Geometry optimization was performed by TOPOS" in methods


def test_invalid_accepted_derivative_cannot_support_derived_result(tmp_path):
    record = make_record(tmp_path)
    source = record.attempts[0]
    derived = source.model_copy(deep=True)
    derived.attempt_id = "attempt_derived"
    derived.parent_attempt_id = source.attempt_id
    derived.command = ["topos-internal", "rigid-body-optimize"]
    derived.metadata.update({
        "result_kind": "derived-optimization", "accepted_derivative_attempt_id": source.attempt_id,
        "derivative_attempt_ids": [source.attempt_id],
    })
    for quantity in derived.quantities:
        quantity.attempt_id = derived.attempt_id
    source.quantities[0].value = 0.75
    record.attempts.append(derived)
    record.candidates[0].attempt_id = derived.attempt_id
    RunStore(tmp_path).commit(record)
    append_decision(tmp_path, subject_id="candidate_selected", action="accept", actor="reviewer", reason="review")
    with pytest.raises(IntegrityError, match="accepted derivative"):
        create_ensemble_manifest(tmp_path, ["candidate_selected"], actor="reviewer")
