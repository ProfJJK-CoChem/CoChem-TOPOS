"""Historical real ORCA bytes test the importer, never a physical release gate.

The wrapper RunStores below are test-created around unchanged scientific data
from the cited Actions artifact. They are not current-source TOPOS calculations,
independent literature references or matrix campaign acceptance evidence.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from topos.models import Artifact, Attempt, Molecule, Quantity, RunRecord, RunRequest
from topos.reference_interaction import CP_DEFINITION, extract_reference_value
from topos.storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest

FIXTURE = Path(__file__).parents[1] / "fixtures" / "orca61-native-cp-he2"
ORIGINAL_ROOT = Path("/home/runner/work/_temp/topos-orca-evidence/counterpoise-native")


def fixture_store(tmp_path, *, change_payload=None, change_request=None, change_raw=None):
    provenance = json.loads((FIXTURE / "provenance.json").read_text())
    assert file_digest(FIXTURE / "counterpoise-result.json") == provenance["original_counterpoise_result_sha256"]
    payload = json.loads((FIXTURE / "counterpoise-result.json").read_text())
    members = deepcopy(provenance["members"])
    folder = tmp_path / "test-created-historical-fixture-wrapper"
    folder.mkdir(parents=True)
    for original, description in members.items():
        source = FIXTURE / description["stored_path"]
        assert file_digest(source) == description["sha256"]
        assert source.stat().st_size == description["size_bytes"]
        relative = "native/" + Path(original).relative_to(ORIGINAL_ROOT).as_posix()
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        if change_raw:
            change_raw(original, target)
        description.update(path=relative, sha256=file_digest(target), size_bytes=target.stat().st_size)
        # Tampering tests deliberately rehash the forged raw member and receipt;
        # scientific re-parsing must catch it even with a consistent snapshot.
        for job in payload["jobs"]:
            for artifact in job["result"]["artifacts"]:
                if artifact["path"] == original:
                    artifact.update(sha256=description["sha256"], size_bytes=description["size_bytes"])
        for artifact in payload["artifacts"]:
            if artifact["path"] == original:
                artifact.update(sha256=description["sha256"], size_bytes=description["size_bytes"])
    if change_payload:
        change_payload(payload)
    for job in payload["jobs"]:
        job["result_sha256"] = digest_json(job["result"])
    request = RunRequest(molecule=Molecule.model_validate(payload["plan"][0]["molecule"]),
                         purpose="energy", engine="orca", method="wB97M-V", basis="def2-TZVPP",
                         auxiliary_basis="def2/J", engine_version="6.1.1", profile_id="orca-mapping-v4.1")
    if change_request:
        request = change_request(request)
    record = RunRecord(request=request, status="completed", validation_status="validated-for-protocol",
                       metadata={"test_fixture_wrapper": provenance["scope"]})
    for job in payload["jobs"]:
        native = job["result"]
        directory = Path(native["diagnostics"]["process"]["stdout_path"]).parent
        artifacts = [Artifact(**{k: v for k, v in description.items() if k != "stored_path"})
                     for original, description in members.items() if Path(original).parent == directory]
        identifier = "attempt_cp_" + job["result_sha256"][:24]
        record.attempts.append(Attempt(attempt_id=identifier, run_id=record.run_id, engine="orca",
                              method=native["method"], status=native["status"], converged=native["converged"],
                              validation_status="validated-for-protocol", command=native["command"],
                              engine_version=native["engine_version"], diagnostics=native["diagnostics"],
                              metadata={**native["metadata"], "counterpoise_role": job["role"]}, artifacts=artifacts,
                              quantities=[Quantity(name="electronic_energy", value=native["energy_hartree"],
                                                   units="hartree", definition="Retained historical native CP component",
                                                   validity="validated-for-protocol", attempt_id=identifier)]))
    for _original, description in members.items():
        if description["role"] in {"basis-export-receipt", "basis-export-output"}:
            record.artifacts.append(Artifact(**{k: v for k, v in description.items() if k != "stored_path"}))
    result_path = "counterpoise-results/" + digest_json(payload) + ".json"
    target = folder / result_path
    atomic_json(target, payload)
    record.artifacts.append(Artifact(path=result_path, role="counterpoise-result", sha256=file_digest(target),
                                     size_bytes=target.stat().st_size))
    record.metadata["matrix_counterpoise"] = {k: payload[k] for k in ("status", "validation_status", "basis_identity", "energies")}
    record.metadata["matrix_counterpoise"]["result_path"] = result_path
    store = RunStore(folder)
    store.commit(record)
    case = SimpleNamespace(request=request, observable="cp_interaction_energy", units="hartree",
                           definition=CP_DEFINITION, geometry_role="frozen-complex-geometry", engine_version="6.1.1")
    return case, record, store


def test_importer_recomputes_five_genuine_historical_cp_legs_without_executable(tmp_path):
    case, record, store = fixture_store(tmp_path)
    value, proof = extract_reference_value(case, record, store)
    assert value == pytest.approx(-3.0934611999544614e-5, abs=1e-14)
    assert value != proof["recomputed_energies_hartree"]["half_cp_interaction_hartree"]
    assert len(proof["native_legs"]) == 5
    assert len(proof["basis_exports"]) == 2
    assert proof["snapshot_id"] == store.verify()["snapshot_id"]
    assert all(not Path(leg["stdout_path"]).is_absolute() for leg in proof["native_legs"].values())
    assert str(tmp_path) not in json.dumps(proof)
    # The original native executable is absent; no licensed program is installed
    # or emulated by this offline text importer.
    assert not Path(record.attempts[0].command[0]).exists()


def test_importer_evidence_reverifies_after_bundle_relocation(tmp_path):
    import shutil

    case, record, store = fixture_store(tmp_path / "original")
    expected = extract_reference_value(case, record, store)
    moved = tmp_path / "relocated" / "wrapper"
    shutil.copytree(store.run_dir, moved)
    moved_store = RunStore(moved)
    assert extract_reference_value(case, moved_store.load(), moved_store) == expected


def test_identical_export_streams_from_other_history_do_not_replace_owned_evidence(tmp_path):
    case, record, store = fixture_store(tmp_path)
    expected, _ = extract_reference_value(case, record, store)
    original = next(a for a in record.artifacts if a.role == "basis-export-output" and a.size_bytes > 0)
    unrelated = "unrelated-export-history/" + Path(original.path).name
    target = store.run_dir / unrelated
    target.parent.mkdir()
    target.write_bytes((store.run_dir / original.path).read_bytes())
    record.artifacts.append(original.model_copy(update={"path": unrelated}))
    store.commit(record)
    actual, proof = extract_reference_value(case, record, store)
    assert actual == expected
    assert unrelated not in json.dumps(proof)


def missing_leg(payload):
    payload["jobs"].pop()


def substituted_half_cp(payload):
    payload["energies"]["cp_interaction_hartree"] = payload["energies"]["half_cp_interaction_hartree"]


def fake_execution(payload):
    payload["jobs"][0]["result"]["metadata"]["execution_kind"] = "mock"


def failed_process(payload):
    payload["jobs"][0]["result"]["diagnostics"]["process"]["returncode"] = 1


def changed_export_identity(payload):
    payload["basis_export_receipts"]["orbital"]["orca_sha256"] = "a" * 64
    payload["basis_identity"]["receipt_sha256"] = digest_json(payload["basis_export_receipts"])


@pytest.mark.parametrize("change,error", [
    (missing_leg, "five distinct"), (substituted_half_cp, "recomputed five"),
    (fake_execution, "genuine native"), (failed_process, "process did not complete"),
    (changed_export_identity, "native retained artifacts|export disagrees"),
])
def test_forged_consistent_receipts_cannot_replace_actual_native_cp_proof(tmp_path, change, error):
    case, record, store = fixture_store(tmp_path, change_payload=change)
    with pytest.raises(IntegrityError, match=error):
        extract_reference_value(case, record, store)


@pytest.mark.parametrize("kind,error", [("energy", "structured energy"), ("ghost", "raw deck changed")])
def test_rehashed_native_tampering_is_caught_by_independent_scientific_reparsing(tmp_path, kind, error):
    def change(original, path):
        if kind == "energy" and original.endswith("leg-0-attempt-0/engine.stdout"):
            path.write_text(path.read_text().replace("-5.793260048012", "-5.893260048012"))
        if kind == "ghost" and original.endswith("leg-2-attempt-0/job.inp"):
            path.write_text(path.read_text().replace("He:", "He"))
    case, record, store = fixture_store(tmp_path, change_raw=change)
    with pytest.raises(IntegrityError, match=error):
        extract_reference_value(case, record, store)


def test_reference_scope_state_method_and_record_are_exact(tmp_path):
    case, record, store = fixture_store(tmp_path)
    forged = record.model_copy(deep=True)
    forged.metadata["matrix_counterpoise"]["energies"]["cp_interaction_hartree"] = 0
    with pytest.raises(IntegrityError, match="exact immutable"):
        extract_reference_value(case, forged, store)
    case.definition = "thermal binding energy"
    with pytest.raises(IntegrityError, match="exact frozen electronic"):
        extract_reference_value(case, record, store)
    case.definition = CP_DEFINITION
    case.geometry_role = "optimized-stationary-geometry"
    with pytest.raises(IntegrityError, match="exact frozen electronic"):
        extract_reference_value(case, record, store)


def test_reference_cannot_change_tested_hamiltonian_or_frozen_geometry(tmp_path):
    case, record, store = fixture_store(tmp_path / "method", change_request=lambda request: request.model_copy(update={"method": "HF"}))
    with pytest.raises(IntegrityError, match="predeclared tested protocol"):
        extract_reference_value(case, record, store)
    def move(request):
        molecule = request.molecule.model_copy(deep=True)
        molecule.coordinates[1][2] = 3.1
        return request.model_copy(update={"molecule": molecule})
    case, record, store = fixture_store(tmp_path / "geometry", change_request=move)
    with pytest.raises(IntegrityError, match="frozen geometry"):
        extract_reference_value(case, record, store)
