"""Balanced association identities and genuine monomer-first engine execution."""
from __future__ import annotations

import os
import shutil
from threading import Event

import numpy as np
import pytest

from topos.config import SystemConfig
from topos.fragments import (
    assemble_monomer_seed,
    association_energies,
    association_gibbs,
    monomer_first_association,
    split_fragments,
)
from topos.models import Bond, FragmentState, Molecule, RunRequest
from topos.science import geometry_digest
from topos.storage import IntegrityError, RunStore, digest_json
from topos.thermochemistry import rrho_thermochemistry


def dimer():
    return Molecule(symbols=["O", "H", "H"] * 2,
                    coordinates=[[0, 0, 0], [.9584, 0, 0], [-.239, .927, 0],
                                 [2.9, 0, 0], [3.15, .92, 0], [3.15, -.92, 0]],
                    fragments=[[0, 1, 2], [3, 4, 5]],
                    fragment_states=[FragmentState(atom_indices=[0, 1, 2], charge=0, multiplicity=1),
                                     FragmentState(atom_indices=[3, 4, 5], charge=0, multiplicity=1)])


def protocol():
    return {"method": "GFN2-xTB", "engine": "xtb", "engine_version": "6.7.1"}


def thermal(molecule, frequencies, energy):
    record = rrho_thermochemistry(molecule, energy,
                                  {"frequencies_cm1": frequencies, "stationary": True,
                                   "validity": "harmonic-minimum-within-thresholds"})
    record["comparison_protocol"] = protocol()
    return record


def test_fragment_partition_retains_atom_mapping_isotopes_and_electronic_states():
    molecule = dimer()
    molecule.isotopes = [18, 2, 1, 16, 1, 1]
    pieces = split_fragments(molecule)
    assert [p.atom_ids for p in pieces] == [["atom-0", "atom-1", "atom-2"], ["atom-3", "atom-4", "atom-5"]]
    assert pieces[0].isotopes == [18, 2, 1]
    assert [p.multiplicity for p in pieces] == [1, 1]
    assert sum(p.charge for p in pieces) == molecule.charge


def test_fragment_states_are_not_guessed_from_total_state():
    molecule = dimer()
    molecule.fragment_states = []
    with pytest.raises(ValueError, match="explicit partition"):
        split_fragments(molecule)


@pytest.mark.parametrize("kind", ["covalent", "coordination", "unknown"])
def test_fragment_partition_cannot_cleave_specified_bond(kind):
    molecule = dimer()
    molecule.bonds = [Bond(atom1=0, atom2=3, kind=kind)]
    with pytest.raises(ValueError, match="may not cleave"):
        split_fragments(molecule)


def test_monomer_placement_preserves_internal_distances_and_centers():
    molecule = dimer()
    pieces = split_fragments(molecule)
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    changed = []
    for monomer in pieces:
        xyz = np.asarray(monomer.coordinates)
        xyz = (xyz - xyz.mean(0)) * 1.05 @ rotation + [11, 4, -5]
        changed.append(Molecule.model_validate({**monomer.model_dump(), "coordinates": xyz.tolist()}))
    seed = assemble_monomer_seed(molecule, changed)
    for group, monomer in zip(molecule.fragments, changed, strict=True):
        placed = np.asarray(seed.coordinates)[group]
        expected = np.asarray(monomer.coordinates)
        assert np.allclose(np.linalg.norm(placed[:, None] - placed[None, :], axis=2),
                           np.linalg.norm(expected[:, None] - expected[None, :], axis=2))
        assert np.allclose(placed.mean(0), np.asarray(molecule.coordinates)[group].mean(0))


def test_monomer_placement_rejects_isotope_or_atom_mapping_changes():
    molecule = dimer()
    fragments = split_fragments(molecule)
    fragments[0].isotopes = [18, 1, 1]
    with pytest.raises(ValueError, match="isotopes"):
        assemble_monomer_seed(molecule, fragments)


@pytest.mark.parametrize("changes", [{"order": 2}, {"kind": "coordination"}, {"atom2": 2}])
def test_monomer_reference_rejects_changed_explicit_bond_identity(changes):
    molecule = dimer()
    molecule.bonds = [Bond(atom1=0, atom2=1)]
    fragments = split_fragments(molecule)
    fragments[0].bonds = [Bond(**{**fragments[0].bonds[0].model_dump(), **changes})]
    with pytest.raises(ValueError, match="declared bond"):
        assemble_monomer_seed(molecule, fragments)


def test_interaction_binding_and_deformation_balanced_signs():
    energies = association_energies(dimer(), -10.3, [-5.0, -5.0], [-5.05, -5.04],
                                    comparison_protocol=protocol(), bsse_policy="not-applicable-no-atom-centered-basis")
    assert energies["electronic_interaction_hartree"] == pytest.approx(-0.3)
    assert energies["electronic_binding_hartree"] == pytest.approx(-0.21)
    assert energies["fragment_deformation_hartree"] == pytest.approx(0.09)
    assert energies["electronic_binding_hartree"] == pytest.approx(energies["electronic_interaction_hartree"] + energies["fragment_deformation_hartree"])
    assert energies["gibbs_association_hartree"] is None
    assert energies["delta_n"] == -1


def test_negative_deformation_recorded_for_sampling_review():
    result = association_energies(dimer(), -10.3, [-5.1, -5], [-5, -5],
                                  comparison_protocol=protocol(), bsse_policy="not-corrected")
    assert result["negative_deformation_requires_review"] is True


@pytest.mark.parametrize("frozen,relaxed", [([-5], [-5, -5]), ([-5, -5], [-5]), ([float("nan"), -5], [-5, -5])])
def test_unbalanced_or_nonfinite_association_energies_rejected(frozen, relaxed):
    with pytest.raises(ValueError):
        association_energies(dimer(), -10.3, frozen, relaxed, comparison_protocol=protocol(), bsse_policy="not-corrected")


def test_counterpoise_requires_ghost_calculation_evidence_and_preserves_sign():
    molecule = dimer()
    with pytest.raises(ValueError, match="ghost-basis"):
        association_energies(molecule, -10.3, [-5, -5], [-5.04, -5.05],
                            comparison_protocol=protocol(), bsse_policy="counterpoise", ghost_fragment_energies_hartree=[-5.01, -5.02])
    evidence = [{"status": "completed", "execution_kind": "real", "charge": 0, "multiplicity": 1,
                 "basis_center_atom_ids": molecule.atom_ids, "artifacts": ["unit-test-contract-only"],
                 "comparison_protocol_sha256": digest_json(protocol())}] * 2
    result = association_energies(molecule, -10.3, [-5, -5], [-5.04, -5.05],
                                  comparison_protocol=protocol(), bsse_policy="counterpoise",
                                  ghost_fragment_energies_hartree=[-5.01, -5.02], ghost_calculation_evidence=evidence)
    assert result["additive_cp_correction_hartree"] == pytest.approx(0.03)
    assert result["cp_interaction_hartree"] == pytest.approx(-0.27)
    assert result["cp_binding_hartree"] == pytest.approx(-0.18)
    with pytest.raises(ValueError, match="counterpoise"):
        association_energies(molecule, -10.3, [-5, -5], [-5.04, -5.05],
                            comparison_protocol=protocol(), bsse_policy="engine-composite-gCP",
                            ghost_fragment_energies_hartree=[-5.01, -5.02], ghost_calculation_evidence=evidence)


def test_association_gibbs_uses_balanced_thermal_records_and_one_standard_conversion():
    molecule = dimer()
    monomers = [thermal(m, [1500, 3500, 3600], -5.1) for m in split_fragments(molecule)]
    complex_thermal = thermal(molecule, [100, 150, 200, 250, 300, 350, 1500, 1500, 3500, 3500, 3600, 3600], -10.3)
    gas = association_gibbs(molecule, complex_thermal, monomers)
    converted = association_gibbs(molecule, complex_thermal, monomers, concentration_mol_l=1)
    assert gas["gibbs_association_hartree"] == pytest.approx(complex_thermal["gibbs_hartree"] - sum(m["gibbs_hartree"] for m in monomers))
    assert converted["gibbs_association_hartree"] < gas["gibbs_association_hartree"]
    assert converted["standard_state_conversion"]["delta_n"] == -1
    monomers[0]["standard_state"]["kind"] = "ideal-concentration-reference"
    with pytest.raises(ValueError, match="conversion is applied once"):
        association_gibbs(molecule, complex_thermal, monomers, concentration_mol_l=1)


def test_association_gibbs_rejects_wrong_fragment_identity_or_method():
    molecule = dimer()
    monomers = [thermal(m, [1500, 3500, 3600], -5.1) for m in split_fragments(molecule)]
    complex_thermal = thermal(molecule, [200] * 12, -10.3)
    monomers[0]["molecular_state"]["isotopes"] = [18, 1, 1]
    with pytest.raises(ValueError, match="unbalanced"):
        association_gibbs(molecule, complex_thermal, monomers)
    monomers[0]["comparison_protocol"] = {"method": "different"}
    with pytest.raises(ValueError, match="protocols must agree"):
        association_gibbs(molecule, complex_thermal, monomers)


def test_cancelled_monomer_first_workflow_does_not_produce_binding(tmp_path):
    event = Event()
    event.set()
    request = RunRequest(molecule=dimer(), purpose="association", n_candidates=1)
    result = monomer_first_association(dimer(), request, tmp_path, cancel_event=event,
                                      config=SystemConfig(executables={"xtb": str(tmp_path / "missing")}, execution_backend="development"))
    assert result["status"] == "cancelled" and result["energies"] is None
    assert result["monomer_runs"] == []


def test_association_workflow_saves_missing_fragment_state_rejection(tmp_path):
    from topos.workflow import Workflow

    molecule = dimer()
    molecule.fragment_states = []
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend="development"))
    record = workflow.run(RunRequest(molecule=molecule, purpose="association"))
    assert record.status == "unsupported"
    assert "explicit partition" in record.metadata["termination_reason"]
    assert not record.attempts and not record.candidates
    RunStore(tmp_path / record.run_id).verify()


@pytest.mark.integration
def test_genuine_xtb_monomer_first_binding_workflow(tmp_path):
    executable = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if executable is None:
        pytest.skip("real xTB is required, with no substituted potential")
    request = RunRequest(molecule=dimer(), purpose="association", n_candidates=1,
                         profile_id="xtb-vtight-v1", budget_seconds=90)
    result = monomer_first_association(dimer(), request, tmp_path,
                                      config=SystemConfig(executables={"xtb": executable}, execution_backend="development"))
    assert result["status"] == "completed", result.get("reason")
    assert len(result["monomer_runs"]) == 2
    assert result["small_fragment_bypass"] is False
    assert len(result["fragment_evaluations"]) == 2
    for child in [*result["monomer_runs"], result["complex_run"]]:
        assert child["status"] == "completed"
        RunStore(child["metadata"]["run_dir"]).verify()
        assert child["attempts"][0]["metadata"]["execution_kind"] == "real"
    assert all(e["engine_version"] == "6.7.1" and e["artifacts"] for e in result["fragment_evaluations"])
    energy = result["energies"]
    assert energy["electronic_binding_hartree"] < 0
    assert energy["electronic_binding_hartree"] == pytest.approx(energy["electronic_interaction_hartree"] + energy["fragment_deformation_hartree"])
    assert energy["gibbs_association_hartree"] is None
    assert geometry_digest(Molecule.model_validate(result["input_molecule"])) == geometry_digest(dimer())
    with pytest.raises(IntegrityError, match="protocol differs"):
        monomer_first_association(dimer(), request.model_copy(update={"seed": request.seed + 1}), tmp_path,
                                  config=SystemConfig(executables={"xtb": executable}, execution_backend="development"))


@pytest.mark.integration
def test_association_workflow_imports_real_child_evidence_for_review(tmp_path):
    import copy

    from topos.review import validate_scientific_candidate
    from topos.workflow import Workflow

    executable = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if executable is None:
        pytest.skip("genuine xTB required for association evidence")
    workflow = Workflow(tmp_path, config=SystemConfig(executables={"xtb": executable}, execution_backend="development"))
    record = workflow.run(RunRequest(molecule=dimer(), purpose="association", n_candidates=1,
                                    profile_id="xtb-vtight-v1", budget_seconds=90))
    assert record.status == "completed", record.metadata.get("termination_reason")
    candidate = record.candidates[0]
    validated = validate_scientific_candidate(record.model_dump(mode="json"), candidate.model_dump(mode="json"))
    assert validated["metadata"]["execution_kind"] == "real"
    assert len(candidate.metadata["monomer_run_ids"]) == 2
    assert record.metadata["association"]["gibbs_association_hartree"] is None
    assert sum(a.metadata.get("advanced_role") == "frozen-fragment-energy" for a in record.attempts) == 2
    assert len({a.metadata.get("source_child_run_id") for a in record.attempts if a.metadata.get("source_child_run_id")}) == 3
    RunStore(tmp_path / record.run_id).verify()
    for mutation in ("source-energy", "missing-component"):
        altered = copy.deepcopy(record.model_dump(mode="json"))
        selected = altered["candidates"][0]
        aggregate = next(a for a in altered["attempts"] if a["attempt_id"] == selected["attempt_id"])
        if mutation == "missing-component":
            aggregate["metadata"]["component_attempt_ids"].pop()
        else:
            component_id = aggregate["metadata"]["monomer_reference_attempt_ids"][0]
            component = next(a for a in altered["attempts"] if a["attempt_id"] == component_id)
            next(q for q in component["quantities"] if q["name"] == "electronic_energy")["value"] += 0.01
        with pytest.raises(IntegrityError):
            validate_scientific_candidate(altered, selected)


@pytest.mark.integration
def test_frozen_association_preserves_supplied_reference_monomer_geometry(tmp_path):
    from topos.constraints import intrafragment_drift

    executable = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if executable is None:
        pytest.skip("genuine xTB required for frozen-reference association")
    molecule = dimer()
    request = RunRequest(molecule=molecule, purpose="association", n_candidates=1,
                         budget_seconds=120, profile_id="xtb-vtight-v1",
                         constraints={"kind": "frozen-monomers", "profile_id": "mapping-2026",
                                      "reference_source": "test supplied geometry; accuracy unverified"})
    result = monomer_first_association(molecule, request, tmp_path,
                                      config=SystemConfig(execution_backend="development", executables={"xtb": executable}))
    assert result["status"] == "completed", result.get("reason")
    assert result["complex_seed_policy"] == "preserve-explicit-frozen-reference-geometries"
    assert result["complex_seed"]["coordinates"] == molecule.coordinates
    assert intrafragment_drift(molecule.coordinates, result["complex_molecule"]["coordinates"], molecule.fragments) < 1e-12
    assert result["energies"]["fragment_deformation_hartree"] > 0


@pytest.mark.integration
@pytest.mark.parametrize("interrupt_at", ["monomer-completed", "monomer-partial", "frozen-fragment-completed"])
def test_association_resume_reuses_completed_child_jobs_and_raw_evidence(tmp_path, monkeypatch, interrupt_at):
    from topos import fragments as fragment_module
    from topos import workflow as workflow_module
    from topos.review import validate_scientific_candidate
    from topos.workflow import Workflow

    executable = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if executable is None:
        pytest.skip("genuine xTB required for association recovery acceptance")
    event = Event()
    calls = []
    native_engine = workflow_module.run_engine
    native_frozen = fragment_module.run_engine
    native_run = Workflow.run

    def engine_observer(*args, **kwargs):
        result = native_engine(*args, **kwargs)
        calls.append(("search", str(args[3])))
        if interrupt_at == "monomer-partial" and len(calls) == 1:
            event.set()
        return result

    def fragment_observer(*args, **kwargs):
        result = native_frozen(*args, **kwargs)
        calls.append(("frozen", str(args[3])))
        if interrupt_at == "frozen-fragment-completed" and sum(kind == "frozen" for kind, _ in calls) == 1:
            event.set()
        return result

    def stage_observer(self, request, **kwargs):
        record = native_run(self, request, **kwargs)
        if (interrupt_at == "monomer-completed" and record.request.metadata.get("association_stage") == "monomer-0"
                and record.status == "completed"):
            event.set()
        return record

    monkeypatch.setattr(workflow_module, "run_engine", engine_observer)
    monkeypatch.setattr(fragment_module, "run_engine", fragment_observer)
    monkeypatch.setattr(Workflow, "run", stage_observer)
    workflow = Workflow(tmp_path, config=SystemConfig(executables={"xtb": executable}, execution_backend="development"))
    count = 2 if interrupt_at == "monomer-partial" else 1
    record = workflow.run(RunRequest(molecule=dimer(), purpose="association", n_candidates=count,
                                    profile_id="xtb-vtight-v1", budget_seconds=120), cancel_event=event)
    assert record.status == "cancelled", record.metadata.get("termination_reason")
    old_ids = {a.attempt_id for a in record.attempts}
    first_child = next(a.metadata["source_child_run_id"] for a in record.attempts if a.metadata.get("source_child_run_id"))
    event.clear()
    resumed = workflow.resume(tmp_path / record.run_id, cancel_event=event)
    assert resumed.status == "completed", resumed.metadata.get("termination_reason")
    assert old_ids.issubset({a.attempt_id for a in resumed.attempts})
    assert resumed.candidates[-1].metadata["monomer_run_ids"][0] == first_child
    assert len(calls) == 3 * count + 2  # Two monomer searches + one complex search + two frozen energies.
    assert len({path for _, path in calls}) == len(calls)
    assert len(resumed.attempts) == len(calls) + 1  # One separately attributable derived association result.
    validate_scientific_candidate(resumed.model_dump(mode="json"), resumed.candidates[-1].model_dump(mode="json"))
    RunStore(tmp_path / record.run_id).verify()
