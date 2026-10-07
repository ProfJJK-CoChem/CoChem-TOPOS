"""Counterpoise input/provenance contracts, not licensed ORCA execution evidence."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Event

import pytest

from topos.counterpoise import (
    EXECUTION_TIMING_SCOPE,
    _leg_execution_timing,
    _validate_basis_export_receipts,
    counterpoise_plan,
    execute_counterpoise,
)
from topos.engines import EngineResult, _orca_input, run_engine
from topos.models import FragmentState, MethodSpec, Molecule, ResourceLimits, utc_now
from topos.science import counterpoise_interaction
from topos.storage import IntegrityError, digest_json, file_digest


def hydrogen_pair():
    return Molecule(symbols=["H", "H"], coordinates=[[0, 0, 0], [0, 0, 3]],
                    atom_ids=["a", "b"], fragments=[[0], [1]],
                    fragment_states=[FragmentState(atom_indices=[0], charge=0, multiplicity=2),
                                     FragmentState(atom_indices=[1], charge=0, multiplicity=2)])


def method():
    return MethodSpec(engine="orca", method="wB97M-V", basis="def2-TZVPP",
                      auxiliary_basis="def2/J", profile_id="orca-mapping-v4.1")


def basis_files(tmp_path):
    # Deliberately not a real basis: these tests never invoke ORCA.
    orbital, auxiliary = tmp_path / "orbital.bas", tmp_path / "auxiliary.bas"
    orbital.write_text("UNIT TEST INPUT PLACEHOLDER: never used for scientific calculation\n")
    auxiliary.write_text("UNIT TEST INPUT PLACEHOLDER: never used for scientific calculation\n")
    return {"orbital_basis_file": orbital, "auxiliary_basis_file": auxiliary}


def test_cp_plan_keeps_physical_doublet_fragments_separate_from_singlet_basis_centers():
    molecule = hydrogen_pair()
    plan = counterpoise_plan(molecule, method())
    assert len(plan) == 5
    first_ghost = plan[2]
    assert first_ghost["ghost_atom_indices"] == [1]
    assert first_ghost["ghost_electronic_state"] == [0, 2]
    assert first_ghost["molecule"]["multiplicity"] == 1
    assert first_ghost["physical_molecule"]["multiplicity"] == 2
    assert first_ghost["physical_molecule"]["atom_ids"] == ["a"]
    assert plan[4]["ghost_atom_indices"] == [0]
    assert plan[4]["physical_molecule"]["atom_ids"] == ["b"]


def test_native_orca_ghost_deck_uses_shared_files_and_documented_colon_syntax():
    text = _orca_input(hydrogen_pair(), method(), ResourceLimits(), "energy",
                       ghost_atom_indices=[1], ghost_electronic_state=(0, 2),
                       basis_files={"orbital": "orbital.bas", "auxiliary": "auxiliary.bas"})
    assert '* xyz 0 2\nH 0 0 0\nH: 0 0 3\n*' in text
    assert 'GTOName "orbital.bas"' in text and 'GTOAuxJName "auxiliary.bas"' in text
    assert "RIJCOSX" in text
    assert "MORead" not in text and "D4" not in text and "Opt" not in text
    assert "def2-TZVPP" not in text  # explicit archived basis bytes are authoritative


@pytest.mark.parametrize("update", [
    {"method": "HF-3c", "basis": None}, {"method": "r2SCAN-3c", "basis": None},
    {"dispersion": "D4"}, {"solvent": "water"}, {"constraints": {"frozen_atoms": [0]}},
    {"engine": "xtb", "method": "GFN2-xTB", "basis": None},
])
def test_cp_rejects_double_gcp_and_incompatible_hamiltonians(update):
    with pytest.raises(ValueError, match="Counterpoise requires"):
        counterpoise_plan(hydrogen_pair(), method().model_copy(update=update))


def test_cp_rejects_missing_fragment_states_and_ecp_scope():
    molecule = hydrogen_pair()
    molecule.fragment_states = []
    with pytest.raises(ValueError, match="fragment charge/spin"):
        counterpoise_plan(molecule, method())
    heavy = Molecule(symbols=["Xe", "Xe"], coordinates=[[0, 0, 0], [0, 0, 5]], fragments=[[0], [1]],
                     fragment_states=[FragmentState(atom_indices=[0], charge=0, multiplicity=1),
                                      FragmentState(atom_indices=[1], charge=0, multiplicity=1)])
    with pytest.raises(ValueError, match="ECP"):
        counterpoise_plan(heavy, method())


def test_missing_engine_never_produces_counterpoise_energy(tmp_path):
    basis = basis_files(tmp_path)
    def should_not_run(*args, **kwargs):
        pytest.fail("Missing ORCA must not execute another binary")
    result = execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp",
                                  **basis, executable=tmp_path / "missing-orca", process_runner=should_not_run)
    assert result["status"] == "unavailable"
    assert result["energies"] is None and result["validation_status"] == "not-evaluated"
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["result"]["energy_hartree"] is None


def test_cp_requires_both_shared_basis_files_for_hybrid_recipe(tmp_path):
    basis = basis_files(tmp_path)
    with pytest.raises(ValueError, match="Coulomb-fitting"):
        execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp",
                              orbital_basis_file=basis["orbital_basis_file"])


def test_ghost_electron_parity_is_checked_on_actual_fragment_not_all_basis_centers(tmp_path):
    basis = basis_files(tmp_path)
    result = run_engine(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp",
                         operation="energy", executable=tmp_path / "missing",
                         ghost_atom_indices=[1], ghost_electronic_state=(0, 2), **basis)
    assert result.status == "unavailable"  # accepted physical state, missing actual engine
    assert result.metadata["physical_molecule"]["symbols"] == ["H"]
    assert result.metadata["physical_molecule"]["multiplicity"] == 2
    assert result.metadata["basis_center_molecule"]["symbols"] == ["H", "H"]
    assert result.metadata["basis_center_molecule"]["multiplicity"] == 1
    invalid = run_engine(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "invalid",
                          operation="energy", executable=tmp_path / "missing",
                          ghost_atom_indices=[1], ghost_electronic_state=(0, 1), **basis)
    assert invalid.status == "unsupported"
    assert "physical ghost-fragment state" in invalid.diagnostics["reason"]


@pytest.mark.parametrize("ghosts,state,operation", [([0, 1], (0, 1), "energy"), ([9], (0, 2), "energy"),
                                                     ([0, 0], (0, 2), "energy"), ([1], None, "energy"),
                                                     ([1], (0, 2), "gradient")])
def test_invalid_ghost_index_state_or_derivative_request_is_rejected(tmp_path, ghosts, state, operation):
    result = run_engine(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "run", operation=operation,
                         ghost_atom_indices=ghosts, ghost_electronic_state=state, executable=tmp_path / "missing")
    assert result.status == "unsupported" and result.energy_hartree is None


def test_cp_cancellation_does_not_produce_partial_sum(tmp_path):
    cancel = Event()
    cancel.set()
    result = execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp",
                                  **basis_files(tmp_path), cancel_event=cancel,
                                  process_runner=lambda *a, **kw: pytest.fail("Cancelled job must not execute"))
    assert result["status"] == "cancelled" and not result["jobs"] and result["energies"] is None


def test_test_fixture_cannot_be_misreported_as_executed_counterpoise(tmp_path, monkeypatch):
    """A parser fixture result is deliberately refused as chemical evidence."""
    import topos.counterpoise as module

    def fixture(*args, **kwargs):
        return EngineResult(status="completed", converged=True, engine="orca", method="wB97M-V",
                            operation="energy", energy_hartree=-1, engine_version="6.1.1",
                            metadata={"execution_kind": "unit-test-fixture"})
    monkeypatch.setattr(module, "run_engine", fixture)
    result = execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp",
                                  **basis_files(tmp_path), process_runner=lambda *a, **kw: None)
    assert result["status"] == "failed" and result["energies"] is None
    assert "actual versioned engine execution" in result["reason"]


def test_counterpoise_arithmetic_sign_uses_five_compatible_energies():
    # Numerical arithmetic fixture, not a molecular benchmark.
    result = counterpoise_interaction(-100.010, -50.003, -50.004, -50.0, -50.0)
    assert result["raw_interaction_hartree"] == pytest.approx(-0.010)
    assert result["cp_interaction_hartree"] == pytest.approx(-0.003)
    assert result["additive_cp_correction_hartree"] == pytest.approx(0.007)


def receipt_contract_fixture(tmp_path):
    """Inert files for receipt validation only; no native calculation is claimed."""
    files = basis_files(tmp_path)
    exporter = tmp_path / "orca_exportbasis"
    exporter.write_text("INERT HASH FIXTURE; NEVER EXECUTED\n")
    paths = {"orbital": files["orbital_basis_file"], "auxiliary": files["auxiliary_basis_file"]}
    receipts, inventory = {}, {}
    for kind, path in paths.items():
        basis_name = "def2-TZVPP" if kind == "orbital" else "def2/J"
        stdout, stderr = tmp_path / f"{kind}.stdout", tmp_path / f"{kind}.stderr"
        stdout.write_text("receipt contract fixture\n")
        stderr.write_text("")
        inventory[kind] = {"sha256": file_digest(path)}
        receipts[kind] = {
            "schema_version": "topos-orca-basis-export/0.1.0",
            "authority_kind": "verified-ORCA-distribution-utility", "basis": basis_name,
            "elements": ["H"], "format": "GAMESS-US", "status": "completed",
            "command": [str(exporter), "-b", basis_name, "-a", "H", "-f", "GAMESS-US", "-o", path.name],
            "output_path": str(path), "output_sha256": file_digest(path),
            "exporter_sha256": file_digest(exporter), "orca_sha256": "a" * 64, "orca_version": "6.1.1",
            "distribution_manifest_sha256": "b" * 64, "archive_sha256": "c" * 64,
            "process": {"status": "completed", "stdout_path": str(stdout), "stderr_path": str(stderr)},
            "evidence": [{"path": str(p), "sha256": file_digest(p), "bytes": p.stat().st_size}
                         for p in (stdout, stderr)],
        }
    return receipts, inventory, paths


def test_basis_receipt_contract_binds_named_basis_and_actual_engine_identity(tmp_path):
    receipts, inventory, paths = receipt_contract_fixture(tmp_path)
    _validate_basis_export_receipts(receipts, inventory, paths, hydrogen_pair(), method(), ("6.1.1", "a" * 64))
    with pytest.raises(IntegrityError, match="actual engine"):
        _validate_basis_export_receipts(receipts, inventory, paths, hydrogen_pair(), method(), ("6.1.1", "d" * 64))


@pytest.mark.parametrize("change", [
    {"basis": "STO-3G"}, {"elements": ["He"]}, {"format": "Gaussian"}, {"process": {}},
    {"authority_kind": "user-declaration"}, {"output_sha256": "d" * 64},
    {"archive_sha256": "not-a-distribution"}, {"evidence": []}, {"command": []},
])
def test_basis_receipt_contract_refuses_inconsistent_authority_or_chemical_identity(tmp_path, change):
    receipts, inventory, paths = receipt_contract_fixture(tmp_path)
    altered = deepcopy(receipts)
    altered["orbital"].update(change)
    with pytest.raises(IntegrityError):
        _validate_basis_export_receipts(altered, inventory, paths, hydrogen_pair(), method())


def test_basis_receipt_contract_requires_distinct_unchanged_native_streams(tmp_path):
    receipts, inventory, paths = receipt_contract_fixture(tmp_path)
    receipts["orbital"]["evidence"][1] = receipts["orbital"]["evidence"][0]
    with pytest.raises(IntegrityError, match="repeats"):
        _validate_basis_export_receipts(receipts, inventory, paths, hydrogen_pair(), method())
    receipts, inventory, paths = receipt_contract_fixture(tmp_path)
    (tmp_path / "orbital.stdout").write_text("tampered bytes")
    with pytest.raises(IntegrityError, match="altered"):
        _validate_basis_export_receipts(receipts, inventory, paths, hydrogen_pair(), method())


def test_counterpoise_retains_verified_exporter_evidence_even_when_cancelled(tmp_path):
    receipts, _, paths = receipt_contract_fixture(tmp_path)
    cancel = Event()
    cancel.set()
    result = execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp",
                                  orbital_basis_file=paths["orbital"], auxiliary_basis_file=paths["auxiliary"],
                                  basis_export_receipts=receipts, cancel_event=cancel,
                                  process_runner=lambda *a, **kw: pytest.fail("Cancelled job must not execute"))
    assert result["status"] == "cancelled" and result["validation_status"] == "not-evaluated"
    assert len(result["artifacts"]) == 6
    assert {a["role"] for a in result["artifacts"]} == {"basis-export-output", "basis-export-receipt"}
    for artifact in result["artifacts"]:
        assert file_digest(Path(artifact["path"])) == artifact["sha256"]


def test_counterpoise_resumes_cancelled_checkpoint_and_refuses_changed_hamiltonian(tmp_path):
    cancel = Event()
    cancel.set()
    basis = basis_files(tmp_path)
    options = {**basis, "cancel_event": cancel, "process_runner": lambda *a, **kw: pytest.fail("Cancelled")}
    first = execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp", **options)
    second = execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp", **options)
    assert first["status"] == second["status"] == "cancelled"
    assert second["resumed_completed_roles"] == []
    assert list((tmp_path / "cp").glob("checkpoint-*.json"))
    changed = hydrogen_pair().model_copy(update={"coordinates": [[0, 0, 0], [0, 0, 4]]})
    with pytest.raises(IntegrityError, match="immutable geometry"):
        execute_counterpoise(changed, method(), ResourceLimits(), tmp_path / "cp", **options)


def test_counterpoise_resume_rejects_mutated_retained_basis_export_bytes(tmp_path):
    receipts, _, paths = receipt_contract_fixture(tmp_path)
    cancel = Event()
    cancel.set()
    options = {"orbital_basis_file": paths["orbital"], "auxiliary_basis_file": paths["auxiliary"],
               "basis_export_receipts": receipts, "cancel_event": cancel,
               "process_runner": lambda *a, **kw: pytest.fail("Cancelled")}
    first = execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp", **options)
    Path(first["artifacts"][1]["path"]).write_text("altered raw export output")
    with pytest.raises(IntegrityError, match="retained artifact"):
        execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp", **options)


@pytest.mark.parametrize("fragment_order", [[0, 1], [1, 0]])
def test_ghost_physical_fragment_preserves_declared_internal_bonds(tmp_path, fragment_order):
    molecule = Molecule(symbols=["H", "H", "He"], coordinates=[[0, 0, 0], [0, 0, .74], [0, 0, 4]],
                        fragments=[fragment_order, [2]], bonds=[{"atom1": 0, "atom2": 1, "order": 1}],
                        fragment_states=[{"atom_indices": [0, 1], "charge": 0, "multiplicity": 1},
                                         {"atom_indices": [2], "charge": 0, "multiplicity": 1}])
    result = run_engine(molecule, method(), ResourceLimits(), tmp_path / "run", operation="energy",
                         ghost_atom_indices=[2], ghost_electronic_state=(0, 1), executable=tmp_path / "missing")
    assert result.status == "unavailable"
    assert result.metadata["physical_molecule"] == counterpoise_plan(molecule, method())[2]["physical_molecule"]


def test_partial_cp_orchestration_reuses_only_verified_completed_legs(tmp_path, monkeypatch):
    """Synthetic parser/orchestration fixtures; no native execution or chemistry validation."""
    import topos.counterpoise as module
    from topos.engines import artifact_inventory
    from topos.fragments import split_fragments

    cancel = Event()
    binary = tmp_path / "inert-orca"
    binary.write_text("INERT ORCHESTRATION FIXTURE: never executed")
    calls = []
    observed_calls = []

    def parser_fixture(molecule, requested_method, resources, workdir, **kwargs):
        folder = Path(workdir)
        folder.mkdir()
        calls.append(folder.name)
        observed_calls.append(utc_now())
        basis = {}
        for kind, option in (("orbital", "orbital_basis_file"), ("auxiliary", "auxiliary_basis_file")):
            path = folder / f"{kind}.bas"
            path.write_bytes(Path(kwargs[option]).read_bytes())
            basis[kind] = {"sha256": file_digest(path)}
        (folder / "job.inp").write_text(_orca_input(molecule, requested_method, resources, "energy",
                         ghost_atom_indices=kwargs["ghost_atom_indices"], ghost_electronic_state=kwargs["ghost_electronic_state"],
                         basis_files={"orbital": "orbital.bas", "auxiliary": "auxiliary.bas"}))
        output = folder / "engine.stdout"
        output.write_text("PARSER FIXTURE ONLY\nProgram Version 6.1.1\nSCF CONVERGED AFTER 1 CYCLES\n"
                          "FINAL SINGLE POINT ENERGY -1.0000\nORCA TERMINATED NORMALLY\n")
        physical = molecule
        if kwargs["ghost_atom_indices"]:
            keep_ids = {molecule.atom_ids[i] for i in range(len(molecule.symbols)) if i not in kwargs["ghost_atom_indices"]}
            physical = next(m for m in split_fragments(molecule) if set(m.atom_ids) == keep_ids)
        if len(calls) == 2:
            cancel.set()
        return EngineResult(status="completed", converged=True, engine="orca", method=requested_method.method,
                            operation="energy", energy_hartree=-1, molecule=physical,
                            engine_version="6.1.1", command=[str(binary), "job.inp"],
                            metadata={"execution_kind": "real", "executable_sha256": file_digest(binary),
                                      "resources": resources.model_dump(mode="json"), "external_basis": basis},
                            diagnostics={"process": {"stdout_path": str(output)}}, artifacts=artifact_inventory(folder))

    monkeypatch.setattr(module, "run_engine", parser_fixture)
    options = {**basis_files(tmp_path), "executable": binary, "process_runner": lambda *a, **kw: None,
               "cancel_event": cancel}
    interrupted = execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp", **options)
    assert interrupted["status"] == "cancelled" and interrupted["energies"] is None and len(calls) == 2
    original_jobs = deepcopy(interrupted["jobs"])
    for entry, observed in zip(original_jobs, observed_calls, strict=True):
        first, last = _leg_execution_timing(EngineResult.model_validate(entry["result"]))
        assert datetime.fromisoformat(first) <= datetime.fromisoformat(observed) <= datetime.fromisoformat(last)
        assert entry["result_sha256"] == digest_json(entry["result"])
    cancel.clear()
    resumed = execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp", **options)
    assert resumed["status"] == "completed" and len(calls) == 5
    assert resumed["resumed_completed_roles"] == ["complex-in-complex-basis", "fragment-0-in-own-basis"]
    assert resumed["validation_status"] == "human-review"  # arbitrary basis files never satisfy the matrix
    assert resumed["jobs"][:2] == original_jobs  # Resume retains actual original invocation times.
    output = Path(resumed["jobs"][0]["result"]["diagnostics"]["process"]["stdout_path"])
    output.write_text(output.read_text().replace("-1.0000", "-2.0000"))
    with pytest.raises(IntegrityError, match="retained artifact"):
        execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp", **options)


def test_unavailable_cp_leg_retains_dated_invocation_without_native_execution_claim(tmp_path):
    before = datetime.fromisoformat(utc_now())
    result = execute_counterpoise(hydrogen_pair(), method(), ResourceLimits(), tmp_path / "cp",
        **basis_files(tmp_path), executable="/missing-licensed-orca",
        process_runner=lambda *a, **kw: pytest.fail("Missing executable must never launch a process"))
    after = datetime.fromisoformat(utc_now())
    assert result["status"] == "unavailable" and len(result["jobs"]) == 1
    entry = result["jobs"][0]
    calculation = EngineResult.model_validate(entry["result"])
    first, last = _leg_execution_timing(calculation)
    assert before <= datetime.fromisoformat(first) <= datetime.fromisoformat(last) <= after
    assert entry["result_sha256"] == digest_json(entry["result"])
    assert calculation.metadata["execution_kind"] != "real"
    assert calculation.energy_hartree is None and not calculation.command


@pytest.mark.parametrize("damage", ["missing", "naive", "reversed", "scope", "extra", "format"])
def test_counterpoise_leg_rejects_invalid_recorded_timing(damage):
    # Explicitly unexecuted contract; no engine output or energy is supplied.
    calculation = EngineResult(status="unavailable", engine="orca", method="HF", operation="energy",
        metadata={"execution_kind": "not-executed", "execution_timing": {
            "started_at": "2026-10-07T00:00:00+00:00", "finished_at": "2026-10-07T00:00:01+00:00",
            "scope": EXECUTION_TIMING_SCOPE}})
    timing = calculation.metadata["execution_timing"]
    if damage == "missing":
        del timing["started_at"]
    elif damage == "naive":
        timing["started_at"] = "2026-10-07T00:00:00"
    elif damage == "reversed":
        timing["finished_at"] = "2026-10-06T23:59:59+00:00"
    elif damage == "scope":
        timing["scope"] = "repackaging old output"
    elif damage == "extra":
        timing["imported_at"] = timing["started_at"]
    else:
        timing["started_at"] = "invented-clock"
    with pytest.raises(IntegrityError, match="wall-clock"):
        _leg_execution_timing(calculation)


def test_historical_counterpoise_leg_without_invocation_timing_stays_undated():
    legacy = EngineResult(status="unavailable", engine="orca", method="HF", operation="energy")
    assert _leg_execution_timing(legacy) == (None, None)
    assert "execution_timing" not in legacy.metadata
