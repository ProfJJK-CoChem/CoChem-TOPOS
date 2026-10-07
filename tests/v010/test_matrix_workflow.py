"""Actual matrix orchestration; scientific tests use the real xTB executable."""
from __future__ import annotations

import os
import shutil
import time
from threading import Event

import numpy as np
import pytest

from topos.config import SystemConfig
from topos.matrix_workflow import (
    EXECUTABLE_ROWS,
    MatrixInputs,
    _child_request,
    _validate_ensemble,
    execute_matrix,
    runtime_recipe_capabilities,
)
from topos.method_matrix import MATRIX_REVISION
from topos.models import FragmentState, Molecule, RunRecord, RunRequest
from topos.storage import RunStore, digest_json
from topos.workflow import Workflow


def water():
    return Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [0.9572, 0, 0], [-0.23999, 0.9273, 0]])


def request(row="T3O-10s", **changes):
    return RunRequest(molecule=changes.pop("molecule", water()), purpose="matrix", matrix_row_id=row,
                      matrix_revision=MATRIX_REVISION, budget_seconds=60, **changes)


def dev_config(binary):
    return SystemConfig(execution_backend="development", executables={"xtb": binary})


def real_xtb():
    choices = [os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"), "/workspace/.tools/xtb-dist/bin/xtb"]
    for choice in choices:
        found = shutil.which(choice)
        if found:
            return found
    pytest.skip("A real xTB executable is required; no engine result is simulated")


def test_unimplemented_full_campaign_does_not_execute_a_cheap_component(tmp_path):
    result = Workflow(tmp_path, config=dev_config("/missing/xtb")).run(request("T3O-3h"))
    assert result.status == "unsupported"
    assert not result.attempts
    assert len(result.metadata["matrix_plan"]["steps"]) == 3
    assert "additional" in result.metadata["termination_reason"]


def test_missing_binary_produces_no_matrix_completion_or_fabricated_energy(tmp_path):
    result = Workflow(tmp_path, config=dev_config("/missing/xtb")).run(request())
    assert result.status == "unavailable"
    assert not result.metadata["matrix_execution"]["full_row_completed"]
    assert len(result.metadata["matrix_execution"]["children"]) == 1
    assert all(c.energy_hartree is None for c in result.candidates)
    assert RunStore(tmp_path / result.run_id).load()["status"] == "unavailable"


def test_matrix_source_text_and_advanced_external_capability_cannot_supply_code(tmp_path):
    result = Workflow(tmp_path, config=dev_config("/missing/xtb")).run(
        request("T1-30min", matrix_inputs={"backend_capabilities": [
            dict(engine="orca", engine_version="6.1.1", operations=["goat"], methods=["GFN2-xTB"],
                 supported_elements=["O", "H"], supported_multiplicities=[1], verified=True, evidence="caller")
        ]}))
    assert result.status == "unsupported" and not result.attempts
    assert "T1-30min" not in EXECUTABLE_ROWS


def test_supplied_capabilities_can_narrow_but_not_bypass_runtime_adapter(tmp_path):
    capabilities = runtime_recipe_capabilities()
    capabilities[0].verified = False
    result = Workflow(tmp_path, config=dev_config("/missing/xtb")).run(
        request(matrix_inputs={"backend_capabilities": [c.model_dump() for c in capabilities]}))
    assert result.status == "unsupported" and not result.attempts


def test_explicit_seed_counts_and_rotationally_duplicate_seeds_are_rejected():
    with pytest.raises(ValueError, match="3–9"):
        _validate_ensemble(water(), [water()], minimum=3, maximum=9, distinct=True)
    translated = water().model_copy(deep=True)
    translated.coordinates = (np.asarray(translated.coordinates) + [1, 2, 3]).tolist()
    with pytest.raises(ValueError, match="distinct"):
        _validate_ensemble(water(), [water(), translated], minimum=2, distinct=True)


def test_changed_seed_isotope_or_state_is_not_accepted_as_same_ensemble():
    isotope = water().model_copy(deep=True)
    isotope.isotopes = [18, None, None]
    with pytest.raises(ValueError, match="identity"):
        _validate_ensemble(water(), [isotope], minimum=1)


def test_unknown_matrix_inputs_rejected_without_silently_ignoring_them(tmp_path):
    result = Workflow(tmp_path, config=dev_config("/missing/xtb")).run(request(matrix_inputs={"script": "invented"}))
    assert result.status == "unsupported" and not result.attempts
    with pytest.raises(ValueError):
        MatrixInputs.model_validate({"command": "fake"})


def test_cancellation_and_deadline_before_child_creation_do_not_launch(tmp_path):
    workflow = Workflow(tmp_path, config=dev_config("/missing/xtb"))
    for index, cancelled in enumerate([True, False]):
        record = RunRecord(request=request())
        store = RunStore(tmp_path / str(index))
        store.commit(record)
        event = Event()
        if cancelled:
            event.set()
        execute_matrix(workflow, record, store, time.monotonic() + (100 if cancelled else -1), event)
        assert record.status == ("cancelled" if cancelled else "timed-out")
        assert not record.attempts
        assert not record.metadata["matrix_execution"]["children"]


@pytest.mark.integration
def test_real_xtb_matrix_geometry_and_verified_child_evidence(tmp_path):
    workflow = Workflow(tmp_path, config=dev_config(real_xtb()))
    result = workflow.run(request())
    assert result.status == "completed"
    assert result.metadata["matrix_execution"]["full_row_completed"]
    assert len(result.attempts) == 1
    assert result.attempts[0].metadata["execution_kind"] == "real"
    assert result.attempts[0].engine_version == "6.7.1"
    assert result.candidates[0].energy_hartree == pytest.approx(-5.070544447, abs=2e-8)
    assert result.candidates[0].metadata["matrix_component"]["task_id"] == "geometry"
    assert all(a.path.startswith("matrix-children/") for a in result.attempts[0].artifacts)
    assert any(a.role == "matrix-child-record" for a in result.artifacts)
    store = RunStore(tmp_path / result.run_id)
    assert store.verify()
    assert workflow.resume(store.run_dir).model_dump() == result.model_dump()


@pytest.mark.integration
def test_real_xtb_explicit_seed_matrix_preserves_all_sources_and_deduplicates(tmp_path):
    seeds = [water()]
    for scale in [1.01, 0.99]:
        geometry = water().model_copy(deep=True)
        geometry.coordinates = (np.asarray(geometry.coordinates) * scale).tolist()
        seeds.append(geometry)
    result = Workflow(tmp_path, config=dev_config(real_xtb())).run(
        request("T1-10s", matrix_inputs={"topology_seeds": [s.model_dump() for s in seeds]}))
    assert result.status == "completed"
    assert len(result.attempts) == 3
    assert sum(c.status == "eligible" for c in result.candidates) == 1
    assert len(result.metadata["matrix_execution"]["children"]) == 3
    assert all(c.metadata["matrix_component"] for c in result.candidates)
    assert result.metadata["sampling_complete"] is False


@pytest.mark.integration
def test_real_interaction_row_uses_frozen_fragment_energies_and_never_claims_binding(tmp_path):
    monomer = water()
    dimer = Molecule(symbols=monomer.symbols * 2,
                     coordinates=monomer.coordinates + (np.asarray(monomer.coordinates) + [0, 0, 3.1]).tolist(),
                     fragments=[[0, 1, 2], [3, 4, 5]], fragment_states=[
                         FragmentState(atom_indices=[0, 1, 2], charge=0, multiplicity=1),
                         FragmentState(atom_indices=[3, 4, 5], charge=0, multiplicity=1)])
    result = Workflow(tmp_path, config=dev_config(real_xtb())).run(request("T5-10s", molecule=dimer))
    assert result.status == "completed"
    observed = result.metadata["matrix_interaction_energy"]
    assert observed["value_hartree"] == pytest.approx(observed["complex_energy_hartree"] - sum(observed["fragment_energies_hartree"]))
    assert observed["binding_energy_hartree"] is None
    assert observed["gibbs_energy_hartree"] is None
    assert observed["geometry_state"] == "frozen-inc"
    assert len(result.attempts) == 3
    assert len(result.candidates) == 1
    assert result.candidates[0].molecule.coordinates == dimer.coordinates
    assert RunStore(tmp_path / result.run_id).verify()


@pytest.mark.integration
def test_completed_component_reused_after_parent_interruption_without_reexecution(tmp_path):
    workflow = Workflow(tmp_path, config=dev_config(real_xtb()))
    first = workflow.run(request())
    assert first.status == "completed"
    store = RunStore(tmp_path / first.run_id)
    attempts = [a.attempt_id for a in first.attempts]
    # A parent can be interrupted after child evidence is committed but before its
    # final recipe completion checkpoint. Preserve the committed scientific data.
    first.status = "partial"
    first.metadata["matrix_execution"]["full_row_completed"] = False
    first.metadata["matrix_execution"].pop("completion_scope")
    store.commit(first)
    workflow.config.executables["xtb"] = "/absent/engine-cannot-be-run"
    resumed = workflow.resume(store.run_dir)
    assert resumed.status == "completed"
    assert [a.attempt_id for a in resumed.attempts] == attempts
    assert len(resumed.metadata["matrix_execution"]["children"]) == 1
    assert resumed.metadata["matrix_execution"]["full_row_completed"]


def test_goat_matrix_does_not_substitute_xtb_when_orca_is_missing(tmp_path):
    configuration = dev_config("/missing/xtb")
    configuration.executables["orca"] = "/missing/orca"
    result = Workflow(tmp_path, config=configuration).run(request("T1-1min"))
    assert result.status == "unavailable"
    assert len(result.attempts) == 1
    assert result.attempts[0].metadata["role"] == "matrix-goat-sampler"
    assert result.attempts[0].status == "unavailable"
    assert not result.candidates
    assert not result.metadata["matrix_execution"]["full_row_completed"]


def test_qm_goat_requires_two_or_three_explicit_leading_isomers(tmp_path):
    result = Workflow(tmp_path, config=dev_config("/missing/xtb")).run(
        request("T1-12h", matrix_inputs={"leading_isomers": [water().model_dump()]}))
    assert result.status == "unsupported" and not result.attempts
    assert "2–3" in result.metadata["termination_reason"]


def test_native_goat_rejects_unenforceable_per_geometry_deadline(tmp_path):
    result = Workflow(tmp_path, config=dev_config("/missing/xtb")).run(
        request("T1-1min", per_geometry_budget_seconds=2.0))
    assert result.status == "unsupported" and not result.attempts
    assert "inside native GOAT" in result.metadata["termination_reason"]


def test_matrix_children_retain_explicit_nested_budget_caps():
    parent = request(per_geometry_budget_seconds=3.0, per_ensemble_budget_seconds=20.0)
    child = _child_request(parent, water(), engine="xtb", method="GFN2-xTB", purpose="optimize", remaining=15.0)
    assert child.per_geometry_budget_seconds == 3.0
    assert child.per_ensemble_budget_seconds == 20.0
    assert child.budget_seconds == 15.0


def test_named_basis_counterpoise_requires_canonical_base_authority(tmp_path):
    monomer = water()
    dimer = Molecule(symbols=monomer.symbols * 2,
                     coordinates=monomer.coordinates + (np.asarray(monomer.coordinates) + [0, 0, 3.1]).tolist(),
                     fragments=[[0, 1, 2], [3, 4, 5]], fragment_states=[
                         FragmentState(atom_indices=[0, 1, 2], charge=0, multiplicity=1),
                         FragmentState(atom_indices=[3, 4, 5], charge=0, multiplicity=1)])
    result = Workflow(tmp_path, config=dev_config("/missing/xtb")).run(request("T5-1h", molecule=dimer))
    assert result.status == "unavailable"
    assert "BASE native ORCA basis-export authority" in result.metadata["termination_reason"]
    assert not result.attempts
    assert not result.metadata["matrix_execution"]["full_row_completed"]


@pytest.mark.integration
@pytest.mark.parametrize("unindexed", [False, True])
def test_matrix_recovers_interrupted_or_unindexed_real_child_without_repeating_completed_engine(tmp_path, unindexed):
    workflow = Workflow(tmp_path, config=dev_config(real_xtb()))
    first = workflow.run(request())
    assert first.status == "completed"
    parent_store = RunStore(tmp_path / first.run_id)
    component = first.metadata["matrix_execution"]["children"][0]
    child_store = RunStore(parent_store.run_dir / component["run_path"])
    child_record = RunRecord.model_validate(child_store.load())
    original_attempts = [a.attempt_id for a in child_record.attempts]
    if unindexed:
        # Child commit is durable; simulate loss of its subsequent parent index.
        first.metadata["matrix_execution"]["children"] = []
    else:
        # The component was stopped after its engine checkpoint, before finish.
        child_record.status = "partial"
        child_store.commit(child_record)
        component["status"] = "partial"
        component["record_sha256"] = digest_json(child_store.load())
    first.status = "partial"
    first.metadata["matrix_execution"]["full_row_completed"] = False
    first.metadata["matrix_execution"].pop("completion_scope", None)
    parent_store.commit(first)
    resumed = workflow.resume(parent_store.run_dir)
    assert resumed.status == "completed", resumed.metadata.get("termination_reason")
    assert [a["attempt_id"] for a in child_store.load()["attempts"]] == original_attempts
    latest = resumed.metadata["matrix_execution"]["children"][-1]
    assert latest["run_id"] == child_record.run_id and latest["status"] == "completed"
    assert len(resumed.attempts) == len(original_attempts)
    assert parent_store.verify() and child_store.verify()
