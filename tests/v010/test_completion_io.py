"""TOPOS producer/publication contracts; these are not a live TORQ calculation.

ENOSPC tests use the Linux kernel's /dev/full device at an isolated file-write
boundary: actual errno handling, not a claim of full-filesystem/power-loss testing.
"""
from __future__ import annotations

import errno
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_storage_publication import make_record, reviewed

from topos.publication import _license_metadata, export_bundle, verify_bundle
from topos.references import executed_references, method_references
from topos.review import (
    CONSUMER_RECEIPT_SCHEMA,
    ENSEMBLE_SCHEMA,
    accept_torq_receipt,
    append_decision,
    export_torq_handoff,
    review_basket,
    verify_torq_handoff,
)
from topos.storage import IntegrityError, RunStore, atomic_json, digest_json


def test_handoff_preserves_complete_state_and_does_not_acknowledge_consumer(tmp_path):
    run_dir = tmp_path / "run"
    record, ensemble = reviewed(run_dir)
    target = tmp_path / "handoff.json"
    handoff = export_torq_handoff(run_dir, target)
    assert verify_torq_handoff(target) == handoff
    assert handoff["consumer_status"] == "awaiting-external-consumption"
    assert handoff["ensemble_sha256"] == ensemble["manifest_sha256"]
    assert handoff["members"][0]["molecule"] == record.candidates[0].molecule.model_dump(mode="json")
    assert handoff["request"] == record.request.model_dump(mode="json")
    assert not (run_dir / "consumer-receipts").exists()
    with pytest.raises(FileExistsError, match="Immutable"):
        export_torq_handoff(run_dir, target)


@pytest.mark.parametrize("change", ["schema", "checksum", "geometry", "review", "missing", "request"])
def test_handoff_rejects_stale_corrupt_and_incomplete_content(tmp_path, change):
    run_dir = tmp_path / "run"
    reviewed(run_dir)
    path = tmp_path / "handoff.json"
    handoff = export_torq_handoff(run_dir, path)
    if change == "schema":
        handoff["schema_version"] = "future"
    elif change == "checksum":
        handoff["handoff_sha256"] = "0" * 64
    elif change == "geometry":
        handoff["members"][0]["geometry_sha256"] = "0" * 64
    elif change == "review":
        handoff["review"][0]["action"] = "reject"
    elif change == "request":
        handoff["request"]["seed"] = 829
    else:
        del handoff["members"]
    if change != "checksum":
        handoff["handoff_sha256"] = digest_json({k: v for k, v in handoff.items() if k != "handoff_sha256"})
    atomic_json(path, handoff)
    with pytest.raises(IntegrityError):
        verify_torq_handoff(path)


def receipt_fixture(handoff):
    """External declaration fixture, expressly not an actual TORQ acknowledgment."""
    body = {
        "schema_version": CONSUMER_RECEIPT_SCHEMA,
        "run_id": handoff["run_id"], "ensemble_schema": ENSEMBLE_SCHEMA,
        "ensemble_sha256": handoff["ensemble_sha256"], "handoff_sha256": handoff["handoff_sha256"],
        "members": [{"member_id": m["member_id"], "geometry_sha256": m["geometry_sha256"]}
                    for m in handoff["members"]],
        "consumer": {"name": "CoChem-TORQ", "version": "contract-test-fixture"},
        "consumed_at": "2026-10-07T00:00:00+00:00", "status": "consumed",
    }
    return {**body, "receipt_sha256": digest_json(body)}


def test_external_receipt_binds_current_ensemble_and_member_geometry(tmp_path):
    run_dir = tmp_path / "run"
    reviewed(run_dir)
    handoff = export_torq_handoff(run_dir, tmp_path / "handoff.json")
    receipt = receipt_fixture(handoff)
    path = tmp_path / "external-receipt.json"
    atomic_json(path, receipt)
    assert accept_torq_receipt(run_dir, path) == receipt
    assert accept_torq_receipt(run_dir, path) == receipt
    assert len(list((run_dir / "consumer-receipts").iterdir())) == 1
    record = RunStore(run_dir).load()
    record["metadata"]["revision"] = "changed after consumption"
    RunStore(run_dir).commit(record)
    with pytest.raises(IntegrityError, match="stale"):
        accept_torq_receipt(run_dir, path)


@pytest.mark.parametrize("change", ["member", "consumer", "version", "status", "timestamp", "schema", "extra"])
def test_external_receipt_rejects_partial_or_mismatched_declarations(tmp_path, change):
    run_dir = tmp_path / "run"
    reviewed(run_dir)
    handoff = export_torq_handoff(run_dir, tmp_path / "handoff.json")
    receipt = receipt_fixture(handoff)
    if change == "member":
        receipt["members"][0]["geometry_sha256"] = "0" * 64
    elif change == "consumer":
        receipt["consumer"]["name"] = "TOPOS inventing a receipt"
    elif change == "version":
        receipt["consumer"]["version"] = ""
    elif change == "status":
        receipt["status"] = "queued"
    elif change == "timestamp":
        receipt["consumed_at"] = "2026-10-07T00:00:00"
    elif change == "schema":
        receipt["ensemble_schema"] = "future"
    else:
        receipt["unrecognized"] = True
    receipt["receipt_sha256"] = digest_json({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    path = tmp_path / "external-receipt.json"
    atomic_json(path, receipt)
    with pytest.raises(IntegrityError):
        accept_torq_receipt(run_dir, path)
    assert not (run_dir / "consumer-receipts").exists()


def test_review_annotations_preserve_original_observation_and_supersession(tmp_path):
    record, _ = reviewed(tmp_path)
    basket = review_basket(tmp_path)
    original = basket["items"][0]["candidate"]
    previous = basket["items"][0]["decision"]
    append_decision(tmp_path, subject_id=record.candidates[0].candidate_id, action="annotate",
                    actor="chemist", reason="Manual grouping only", scope="symmetry annotation",
                    annotations={"suggested_point_group": "Dinfh", "is_measured": False},
                    supersedes=previous["decision_id"])
    result = review_basket(tmp_path)
    assert result["items"][0]["candidate"] == original
    assert result["items"][0]["decision"]["annotations"]["suggested_point_group"] == "Dinfh"
    assert len(result["items"][0]["history"]) == 2


def test_export_table_and_figure_regenerate_without_topos_import(tmp_path):
    run_dir = tmp_path / "run"
    reviewed(run_dir)
    bundle = tmp_path / "bundle"
    manifest = export_bundle(run_dir, bundle, license_identifier="CC-BY-4.0")
    output = tmp_path / "reproduced"
    # Isolated interpreter cannot import local site-packages or project modules.
    result = subprocess.run([sys.executable, "-I", str(bundle / "regenerate.py"), str(output)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    for name in ("selected.csv", "relative-energy.svg"):
        assert (bundle / name).read_bytes() == (output / name).read_bytes()
    assert verify_bundle(bundle) == manifest
    assert manifest["publication_status"] == "not-published"
    assert manifest["version_doi"] is None and manifest["concept_doi"] is None
    assert manifest["publication_ready"] is False


def test_reproduction_fails_on_changed_source_data(tmp_path):
    reviewed(tmp_path / "run")
    bundle = tmp_path / "bundle"
    export_bundle(tmp_path / "run", bundle)
    (bundle / "run.json").write_text("{}")
    output = tmp_path / "reproduced"
    result = subprocess.run([sys.executable, "-I", str(bundle / "regenerate.py"), str(output)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert not output.exists()


def test_figure_never_invents_missing_energy(tmp_path):
    record = make_record(tmp_path / "run")
    record.candidates[0].energy_hartree = None
    reviewed(tmp_path / "run", record)
    export_bundle(tmp_path / "run", tmp_path / "bundle")
    figure = (tmp_path / "bundle/relative-energy.svg").read_text()
    assert "No electronic energies reported" in figure
    assert "<circle" not in figure


@pytest.mark.parametrize("license_id", ["whatever", "CC BY", "<script>", "LicenseRef-", "CC-BY-4.0 OR anything"])
def test_unrecognized_license_identifiers_are_rejected(license_id):
    with pytest.raises(IntegrityError, match="SPDX"):
        _license_metadata(license_id, {"attempts": []})


def test_orca_data_restrictions_and_required_citation_are_execution_aware():
    record = {"attempts": [{"attempt_id": "actual-attempt", "engine": "orca", "method": "HF-3c",
                           "engine_version": "6.1.1", "status": "failed", "command": ["orca", "input.inp"],
                           "metadata": {"execution_kind": "real"}}]}
    references, _ = executed_references(record)
    assert any(c.get("doi") == "10.1002/wcms.70019" for c in references)
    assert any(c.get("doi") == "10.1002/jcc.23317" for c in references)
    metadata, issues = _license_metadata("CC-BY-4.0", record)
    assert metadata["orca_data_attempt_ids"] == ["actual-attempt"]
    assert any("blanket" in issue for issue in issues)
    record["attempts"][0]["command"] = []
    references, _ = executed_references(record)
    assert not any(c.get("doi") == "10.1002/wcms.70019" for c in references)
    assert _license_metadata(None, record)[0]["orca_data_attempt_ids"] == []
    assert any(c["kind"] == "preprint-method" for c in method_references("xtb", "GFN0-xTB"))


def _redirect_one_staging_write_to_kernel_full(monkeypatch, predicate):
    if not Path("/dev/full").exists():
        pytest.skip("Actual ENOSPC errno device is available only on supported Unix hosts")
    original = Path.open
    redirected = []
    def open_file(path, mode="r", *args, **kwargs):
        if mode == "xb" and predicate(path):
            redirected.append(str(path))
            return original(Path("/dev/full"), "wb", buffering=0)
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", open_file)
    return redirected


def test_actual_kernel_enospc_during_snapshot_write_preserves_committed_evidence(tmp_path, monkeypatch):
    record = make_record(tmp_path)
    store = RunStore(tmp_path)
    before = store.commit(record)
    pointer = store.current.read_bytes()
    record.metadata["next"] = True
    redirected = _redirect_one_staging_write_to_kernel_full(
        monkeypatch, lambda path: ".pending-" in str(path) and "/artifacts/" in str(path))
    with pytest.raises(OSError) as error:
        store.commit(record)
    assert error.value.errno == errno.ENOSPC
    assert redirected
    assert store.current.read_bytes() == pointer
    assert store.verify() == before
    assert not list(store.snapshots.glob(".pending-*"))


def test_actual_kernel_enospc_during_export_never_publishes_partial_bundle(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    reviewed(run_dir)
    before = RunStore(run_dir).verify()
    redirected = _redirect_one_staging_write_to_kernel_full(
        monkeypatch, lambda path: ".bundle.pending-" in str(path) and path.name == "run.json")
    with pytest.raises(OSError) as error:
        export_bundle(run_dir, tmp_path / "bundle")
    assert error.value.errno == errno.ENOSPC
    assert redirected
    assert not (tmp_path / "bundle").exists()
    assert not list(tmp_path.glob(".bundle.pending-*"))
    assert RunStore(run_dir).verify() == before


def test_cli_handoff_and_external_receipt_round_trip(tmp_path, capsys):
    from topos.cli import main

    run_dir = tmp_path / "run"
    reviewed(run_dir)
    handoff_file = tmp_path / "handoff.json"
    assert main(["export-handoff", str(run_dir), "--destination", str(handoff_file)]) == 0
    handoff = json.loads(capsys.readouterr().out)
    assert main(["verify-handoff", str(handoff_file)]) == 0
    assert json.loads(capsys.readouterr().out) == handoff
    receipt = receipt_fixture(handoff)
    receipt_file = tmp_path / "consumer.json"
    atomic_json(receipt_file, receipt)
    assert main(["receive-torq", str(run_dir), "--receipt", str(receipt_file)]) == 0
    assert json.loads(capsys.readouterr().out) == receipt
    assert main(["basket", str(run_dir)]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["eligibility"]["eligible"]


def test_cli_matrix_uses_source_rows_and_explicit_hardware_capability_gates(tmp_path, capsys):
    from topos.cli import main

    assert main(["matrix", "list", "--owner", "TOPOS"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert catalog["rows"] and all(row["owner"] == "TOPOS" for row in catalog["rows"])
    assert len(catalog["source_sha256"]) == 64
    assert main(["matrix", "show", "T3O-30min"]) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["row_id"] == "T3O-30min"
    assert row["source"]["line"] > 0
    hardware = tmp_path / "hardware.json"
    atomic_json(hardware, {"cpu_threads": 2, "memory_mb": 2048, "fingerprint": "contract-fixture-cpu"})
    assert main(["matrix", "plan", "T3O-30min", "--hardware", str(hardware)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert not plan["runnable"] and plan["blockers"]
    assert plan["estimated_wall_seconds"] is None
    assert main(["matrix", "show", "imaginary-row"]) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "error"


@pytest.mark.parametrize("status,expected", [("completed", 0), ("failed", 3), ("cancelled", 3)])
def test_base_receiver_cli_preserves_execution_status_and_passes_cancellation(tmp_path, capsys, monkeypatch, status, expected):
    from topos.cli import main

    def receiver(path, output_root, *, cancel_event):
        assert path == tmp_path / "handoff.json" and output_root == tmp_path / "runs"
        assert not cancel_event.is_set()
        return {"receipt": {"status": status}, "record": {"status": status}}
    monkeypatch.setattr("topos.base_provider.execute_handoff", receiver)
    assert main(["receive-base", str(tmp_path / "handoff.json"), "--output-root", str(tmp_path / "runs")]) == expected
    assert json.loads(capsys.readouterr().out)["record"]["status"] == status


def test_browser_exposes_advanced_protocols_and_matrix_without_engine_claims():
    testing = pytest.importorskip("streamlit.testing.v1", reason="optional browser adapter")
    app = testing.AppTest.from_file(str(Path(__file__).resolve().parents[2] / "cochem_topos_web.py")).run(timeout=20)
    assert not app.exception
    purposes = next(widget for widget in app.selectbox if widget.label == "Purpose")
    assert {"frequency", "thermochemistry", "association"}.issubset(purposes.options)
    purposes.select("thermochemistry")
    app.run(timeout=20)
    assert not app.exception
    assert {"Temperature (K)", "Hessian displacement (bohr)", "Gas standard pressure (Pa)",
            "Frequency scale factor", "Low-frequency cutoff (cm⁻¹)"}.issubset({w.label for w in app.number_input})
    assert "Search algorithm" not in {w.label for w in app.selectbox}
    assert "Matrix row" in {w.label for w in app.selectbox}
    with pytest.raises(KeyError):
        app.session_state["topos_job"]


def test_rehashed_outer_bundle_cannot_replace_original_scientific_evidence(tmp_path):
    from topos.storage import file_digest

    reviewed(tmp_path / "run")
    bundle = tmp_path / "bundle"
    manifest = export_bundle(tmp_path / "run", bundle)
    entry = next(item for item in manifest["files"] if item["path"].endswith("stdout.json"))
    artifact = bundle / entry["path"]
    artifact.write_text('{"energy": 12345}\n')
    entry["sha256"], entry["size_bytes"] = file_digest(artifact), artifact.stat().st_size
    manifest["manifest_sha256"] = digest_json({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    atomic_json(bundle / "manifest.json", manifest)
    with pytest.raises(IntegrityError, match="original committed scientific evidence"):
        verify_bundle(bundle)


def test_publication_sampling_sensitivity_uses_only_reviewed_members_and_unknown_missing_states(tmp_path):
    run_dir = tmp_path / 'run'
    record = make_record(run_dir)
    # An unselected observation cannot contribute to the reported ensemble.
    excluded = record.candidates[0].model_copy(deep=True)
    excluded.candidate_id = 'unreviewed_observation'
    excluded.energy_hartree = -100.0
    record.candidates.append(excluded)
    reviewed(run_dir, record)
    bundle = tmp_path / 'bundle'
    export_bundle(run_dir, bundle)
    report = json.loads((bundle / 'sampling-sensitivity.json').read_text())
    assert report['observed_member_ids'] == ['candidate_selected']
    assert report['ensemble']['populations'] == {'candidate_selected': 1.0}
    assert report['ensemble']['weight_kind'] == 'electronic-energy-weights-not-Gibbs-populations'
    assert report['missing_states_assumption'] is None
    assert report['missing_population_upper_bound'] is None
    assert not report['missing_state_assumptions_declared']
    assert [window['window_kcal_mol'] for window in report['windows']] == [1.0, 3.0, 6.0]
    destination = tmp_path / 'recomputed.json'
    process = subprocess.run([sys.executable, str(bundle / 'recompute-sensitivity.py'), str(destination)],
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    assert json.loads(destination.read_text()) == report
    verify_bundle(bundle)


def test_publication_sampling_sensitivity_missing_state_bound_requires_explicit_assumptions(tmp_path):
    run_dir = tmp_path / 'run'
    reviewed(run_dir)
    bundle = tmp_path / 'bundle'
    export_bundle(run_dir, bundle, sensitivity_options={
        'windows_kcal_mol': [2.0, 4.0], 'missing_states': 3, 'missing_gap_kcal_mol': 0.0,
    })
    report = json.loads((bundle / 'sampling-sensitivity.json').read_text())
    # One observed state of degeneracy one, three declared absent states at or above E_min.
    assert report['missing_population_upper_bound'] == pytest.approx(0.75)
    assert report['missing_state_assumptions_declared']
    assert report['temperature_k'] == 298.15
    with pytest.raises(IntegrityError, match='explicitly declared'):
        export_bundle(run_dir, tmp_path / 'invalid', sensitivity_options={'missing_gap_kcal_mol': 1.0})
    export_bundle(run_dir, tmp_path / 'missing-gibbs', sensitivity_options={'quantity': 'gibbs'})
    missing = json.loads((tmp_path / 'missing-gibbs' / 'sampling-sensitivity.json').read_text())
    assert missing['status'] == 'unavailable'
    assert missing['ensemble'] is None
    assert missing['missing_population_upper_bound'] is None
    assert 'valid gibbs_hartree' in missing['reason']


def test_model_credit_requires_execution_and_preserves_checkpoint_identity():
    manifest = {'backend': 'aimnet2', 'family': 'AIMNet2', 'training_method': 'declared-training-level',
                'license_name': 'model-specific', 'license_url': 'https://example.org/model-license',
                'domain_reference': 'https://example.org/domain',
                'members': [{'sha256': 'a' * 64, 'training_run_id': 'training-1', 'source': 'https://example.org/checkpoint'}]}
    attempt = {'attempt_id': 'model-execution', 'engine': 'aimnet2', 'method': 'AIMNet2',
               'engine_version': 'test-contract', 'status': 'completed', 'command': ['model-worker'],
               'metadata': {'execution_kind': 'real', 'manifest': manifest, 'manifest_sha256': 'b' * 64}}
    references, _ = executed_references({'attempts': [attempt], 'request': {}})
    assert any(reference.get('doi') == '10.1039/D4SC08572H' for reference in references)
    checkpoint = next(reference for reference in references if reference['kind'] == 'model-artifact')
    assert checkpoint['members'][0]['sha256'] == 'a' * 64
    assert checkpoint['training_hamiltonian'] == 'declared-training-level'
    attempt['metadata']['execution_kind'] = 'not-executed'
    references, _ = executed_references({'attempts': [attempt], 'request': {'metadata': {'manifest': manifest}}})
    assert not any(reference.get('doi') == '10.1039/D4SC08572H' for reference in references)
    assert not any(reference['kind'] == 'model-artifact' for reference in references)


def test_correlated_credit_uses_actual_native_protocol_basis_not_request_default():
    attempt = {'attempt_id': 'correlated', 'engine': 'orca', 'method': 'DLPNO-CCSD(T1)',
               'engine_version': '6.1.1', 'status': 'completed', 'command': ['orca', 'job.inp'],
               'metadata': {'execution_kind': 'real', 'requested_protocol': {'orbital_basis': 'def2-QZVPP'}}}
    references, _ = executed_references({'attempts': [attempt], 'request': {'basis': 'jun-cc-pVTZ'}})
    assert any(reference.get('doi') == '10.1063/1.5011798' for reference in references)
    basis = next(reference for reference in references if reference.get('doi') == '10.1039/b508541a')
    assert basis['bases'] == ['def2-QZVPP']
    assert not any(reference.get('doi') == '10.1021/ct1005533' for reference in references)
