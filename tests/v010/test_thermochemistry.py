"""Physical identities, failure boundaries and authentic engine Hessian coverage."""
from __future__ import annotations

import json
import math
import os
import shutil
from threading import Event

import numpy as np
import pytest
from scipy import constants

from topos.engines import EngineResult, run_engine
from topos.models import Candidate, MethodSpec, Molecule, ResourceLimits, RunRequest
from topos.science import BOHR_ANGSTROM, HARTREE_J, KB_HARTREE_K, harmonic_analysis
from topos.storage import IntegrityError
from topos.thermochemistry import (
    calculate_thermochemistry,
    derivative_coordinate_frame,
    ensemble_sensitivity,
    finite_difference_hessian,
    mixed_level_gibbs,
    rrho_thermochemistry,
    standard_state_correction,
)


def water():
    return Molecule(symbols=["O", "H", "H"],
                    coordinates=[[0, 0, 0], [0.9584, 0, 0], [-0.239, 0.927, 0]])


def analysis(frequencies=(1595.0, 3657.0, 3756.0)):
    return {"stationary": True, "validity": "harmonic-minimum-within-thresholds",
            "frequencies_cm1": list(frequencies)}


def method():
    return MethodSpec(engine="xtb", method="GFN2-xTB", profile_id="xtb-extreme-v1")


def quadratic_evaluator(reference, hessian, calls):
    """Analytic quadratic differentiation oracle, never an engine integration substitute."""
    origin = np.asarray(reference.coordinates).ravel() / BOHR_ANGSTROM

    def evaluate(molecule, folder, resources):
        calls.append(molecule)
        displacement = np.asarray(molecule.coordinates).ravel() / BOHR_ANGSTROM - origin
        gradient = hessian @ displacement
        return EngineResult(status="completed", engine="analytic-test", method="quadratic-oracle",
                            operation="gradient", energy_hartree=float(0.5 * displacement @ gradient),
                            gradient_hartree_per_bohr=gradient.reshape(-1, 3).tolist(),
                            molecule=molecule, converged=True,
                            metadata={"execution_kind": "analytic-unit-test"})
    return evaluate


def test_finite_differences_recover_coupled_quadratic_and_resume(tmp_path):
    molecule = water()
    rng = np.random.default_rng(4)
    matrix = rng.normal(size=(9, 9))
    hessian = matrix.T @ matrix
    calls = []
    evaluator = quadratic_evaluator(molecule, hessian, calls)
    first = finite_difference_hessian(molecule, method(), ResourceLimits(), tmp_path, evaluator=evaluator)
    assert first["status"] == "completed"
    assert len(calls) == 19
    assert np.allclose(first["hessian_hartree_per_bohr2"], hessian, atol=1e-11, rtol=0)
    assert first["metadata"]["max_energy_gradient_difference_hartree_per_bohr"] < 1e-10
    second = finite_difference_hessian(molecule, method(), ResourceLimits(), tmp_path, evaluator=evaluator)
    assert second["status"] == "completed" and len(calls) == 19
    assert all(e["resumed"] for e in second["evaluations"])
    assert second["metadata"]["protocol"]["evaluator"] == "caller-provided"


def test_hessian_cancelled_before_launch_has_no_derivative(tmp_path):
    event = Event()
    event.set()
    calls = []
    result = finite_difference_hessian(water(), method(), ResourceLimits(), tmp_path, cancel_event=event,
                                       evaluator=quadratic_evaluator(water(), np.eye(9), calls))
    assert result["status"] == "cancelled" and not calls
    assert result["hessian_hartree_per_bohr2"] is None


def test_partial_hessian_resumes_only_missing_displacements(tmp_path):
    event = Event()
    calls = []
    oracle = quadratic_evaluator(water(), np.eye(9), calls)

    def callback(*args):
        result = oracle(*args)
        if len(calls) == 5:
            event.set()
        return result

    result = finite_difference_hessian(water(), method(), ResourceLimits(), tmp_path, evaluator=callback, cancel_event=event)
    assert result["status"] == "cancelled" and len(calls) == 5
    assert result["hessian_hartree_per_bohr2"] is None
    event.clear()
    resumed = finite_difference_hessian(water(), method(), ResourceLimits(), tmp_path, evaluator=oracle, cancel_event=event)
    assert resumed["status"] == "completed" and len(calls) == 19
    assert sum(e["resumed"] for e in resumed["evaluations"]) == 5


def test_hessian_restart_tamper_or_changed_protocol_rejected(tmp_path):
    callback = quadratic_evaluator(water(), np.eye(9), [])
    finite_difference_hessian(water(), method(), ResourceLimits(), tmp_path, evaluator=callback)
    with pytest.raises(IntegrityError, match="protocol differs"):
        finite_difference_hessian(water(), method(), ResourceLimits(), tmp_path, evaluator=callback, step_bohr=0.01)
    receipt = tmp_path / "reference.json"
    saved = json.loads(receipt.read_text())
    saved["result"]["energy_hartree"] = 10.0
    receipt.write_text(json.dumps(saved))
    with pytest.raises(IntegrityError, match="receipt failed"):
        finite_difference_hessian(water(), method(), ResourceLimits(), tmp_path, evaluator=callback)


def test_nonsymmetric_derivative_field_not_repaired_into_physical_hessian(tmp_path):
    matrix = np.eye(9)
    matrix[1, 2] = 1.0
    result = finite_difference_hessian(water(), method(), ResourceLimits(), tmp_path,
                                       evaluator=quadratic_evaluator(water(), matrix, []))
    assert result["status"] == "failed"
    assert result["metadata"]["max_antisymmetry_hartree_per_bohr2"] == pytest.approx(1)
    assert result["hessian_hartree_per_bohr2"] is None


def test_inconsistent_engine_energy_gradient_detected(tmp_path):
    callback = quadratic_evaluator(water(), np.eye(9), [])

    def inconsistent(molecule, folder, resources):
        result = callback(molecule, folder, resources)
        result.energy_hartree += molecule.coordinates[0][0]
        return result

    result = finite_difference_hessian(water(), method(), ResourceLimits(), tmp_path, evaluator=inconsistent)
    assert result["status"] == "failed" and result["hessian_hartree_per_bohr2"] is None


def test_missing_engine_cannot_generate_frequency_or_thermochemistry(tmp_path):
    result = calculate_thermochemistry(water(), method(), ResourceLimits(), tmp_path, executable=tmp_path / "missing")
    assert result["status"] == "unavailable"
    assert result["analysis"] is None and result["thermochemistry"] is None


def test_monatomic_ideal_gas_matches_sackur_tetrode():
    helium = Molecule(symbols=["He"], coordinates=[[0, 0, 0]], isotopes=[4])
    result = rrho_thermochemistry(helium, -2.8, analysis(()), temperature_k=298.15)
    # NIST's ideal-gas He entropy at 298.15 K / 1 bar is 126.15 J mol-1 K-1;
    # this record uses 1 atm, an explicit small pressure-reference difference.
    entropy_j_mol = result["entropy_hartree_per_k"] * HARTREE_J * constants.Avogadro
    assert entropy_j_mol == pytest.approx(126.15 - constants.R * math.log(1.01325), abs=0.03)
    assert result["thermal_enthalpy_correction_hartree"] == pytest.approx(2.5 * KB_HARTREE_K * 298.15)
    assert result["zpe_hartree"] == 0
    assert result["components"]["rotation_energy_hartree"] == 0


def test_water_rrho_consistent_components_and_symmetry_entropy():
    first = rrho_thermochemistry(water(), -76.0, analysis(), symmetry_number=1)
    symmetric = rrho_thermochemistry(water(), -76.0, analysis(), symmetry_number=2)
    assert symmetric["entropy_hartree_per_k"] - first["entropy_hartree_per_k"] == pytest.approx(-KB_HARTREE_K * math.log(2))
    assert symmetric["gibbs_hartree"] - first["gibbs_hartree"] == pytest.approx(KB_HARTREE_K * 298.15 * math.log(2))
    assert first["gibbs_hartree"] == pytest.approx(first["enthalpy_hartree"] - 298.15 * first["entropy_hartree_per_k"])
    assert first["thermal_enthalpy_correction_hartree"] >= 4 * KB_HARTREE_K * 298.15
    assert first["zpe_hartree"] > first["components"]["vibration_thermal_energy_hartree"]


def test_linear_rotor_and_explicit_spin_entropy():
    h2 = Molecule(symbols=["H", "H"], coordinates=[[0, 0, 0], [0, 0, 0.74]])
    result = rrho_thermochemistry(h2, -1.1, analysis((4401,)), symmetry_number=2)
    assert result["rotation"]["geometry_class"] == "linear"
    assert result["components"]["rotation_energy_hartree"] == pytest.approx(KB_HARTREE_K * 298.15)
    atom = Molecule(symbols=["H"], coordinates=[[0, 0, 0]], multiplicity=2)
    doublet = rrho_thermochemistry(atom, -0.5, analysis(()))
    assert doublet["components"]["electronic_entropy_hartree_per_k"] == pytest.approx(KB_HARTREE_K * math.log(2))


@pytest.mark.parametrize("update", [{"stationary": False}, {"validity": "unstable-modes"},
                                      {"subspace": "constrained"}, {"constraints": {"frozen": True}}])
def test_rrho_rejects_unvalidated_stationary_point_and_constrained_subspace(update):
    with pytest.raises(ValueError, match="full-dimensional stationary minimum"):
        rrho_thermochemistry(water(), -76, {**analysis(), **update})


@pytest.mark.parametrize("frequencies", [(-3, 1000, 2000), (0, 1000, 2000), (1000, 2000), (math.nan, 1000, 2000)])
def test_rrho_does_not_discard_invalid_or_missing_modes(frequencies):
    with pytest.raises(ValueError):
        rrho_thermochemistry(water(), -76, analysis(frequencies), low_frequency_policy="frequency-floor")


def test_low_frequency_policy_is_explicit_and_preserves_zpe():
    modes = analysis((5, 1000, 2000))
    with pytest.raises(ValueError, match="near-zero"):
        rrho_thermochemistry(water(), -76, modes)
    floor = rrho_thermochemistry(water(), -76, modes, low_frequency_policy="frequency-floor", cutoff_cm1=100)
    harmonic = rrho_thermochemistry(water(), -76, modes, cutoff_cm1=1)
    assert floor["zpe_hartree"] == harmonic["zpe_hartree"]
    assert floor["entropy_hartree_per_k"] < harmonic["entropy_hartree_per_k"]
    assert floor["model"] == "ideal-gas-modified-HO-frequency-floor"


def test_standard_state_conversion_sign_and_scale():
    result = standard_state_correction(temperature_k=298.15, delta_n=-1)
    kcal = result["correction_hartree"] * HARTREE_J * constants.Avogadro / 4184
    assert kcal == pytest.approx(-1.893, abs=0.002)
    gas = rrho_thermochemistry(water(), -76, analysis())
    solution_reference = rrho_thermochemistry(water(), -76, analysis(), concentration_mol_l=1)
    assert solution_reference["gibbs_hartree"] - gas["gibbs_hartree"] == pytest.approx(-result["correction_hartree"])
    assert solution_reference["solvation_correction_hartree"] is None


def test_mixed_level_gibbs_never_double_counts_low_electronic_energy():
    low = rrho_thermochemistry(water(), -5.0, analysis())
    mixed = mixed_level_gibbs(-76, low, high_method={"method": "test-high"}, rationale="Declared composite test")
    assert mixed["gibbs_hartree"] == pytest.approx(-76 + low["gibbs_hartree"] + 5)
    assert mixed["gibbs_hartree"] != pytest.approx(-76 + low["gibbs_hartree"])


def test_population_sensitivity_retains_missing_state_assumptions():
    candidates = [Candidate(molecule=water(), energy_hartree=energy, gibbs_hartree=energy,
                            comparison_protocol="same-method") for energy in (-76, -75.99)]
    result = ensemble_sensitivity(candidates, missing_states=1, missing_gap_kcal_mol=0)
    assert result["windows"][0]["retained_count"] == 1
    assert result["windows"][0]["ensemble_energy_shift_hartree"] >= 0
    assert result["missing_population_upper_bound"] == pytest.approx(0.5, abs=0.0001)
    assert "not-certified" in result["completeness"]


@pytest.mark.integration
def test_authentic_xtb_water_hessian_and_thermochemistry(tmp_path):
    executable = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if executable is None:
        pytest.skip("authentic xTB required; no synthetic engine substitute")
    oriented, transformation = derivative_coordinate_frame(water())
    assert np.linalg.det(transformation["rotation"]) == pytest.approx(1)
    optimized = run_engine(oriented, method(), ResourceLimits(budget_seconds=60), tmp_path / "optimization", executable=executable)
    assert optimized.status == "completed" and optimized.converged
    result = calculate_thermochemistry(optimized.molecule, method(), ResourceLimits(budget_seconds=120),
                                       tmp_path / "hessian", executable=executable, symmetry_number=2)
    assert result["status"] == "completed", result.get("reason")
    assert len(result["hessian"]["evaluations"]) == 19
    assert all(e["result"]["engine_version"] == "6.7.1" and e["result"]["artifacts"] for e in result["hessian"]["evaluations"])
    modes = result["analysis"]["frequencies_cm1"]
    assert len(modes) == 3 and all(1000 < frequency < 5000 for frequency in modes)
    assert result["analysis"]["stationary"] is True
    assert 0.015 < result["thermochemistry"]["zpe_hartree"] < 0.03
    assert result["thermochemistry"]["gibbs_hartree"] != result["hessian"]["energy_hartree"]
    # A second displacement size tests actual derivative convergence rather
    # than merely asserting the central-difference implementation is symmetric.
    second = finite_difference_hessian(optimized.molecule, method(), ResourceLimits(budget_seconds=120),
                                       tmp_path / "half-step", executable=executable, step_bohr=0.0025)
    assert second["status"] == "completed"
    finer = harmonic_analysis(optimized.molecule, second["hessian_hartree_per_bohr2"],
                              gradient_hartree_per_bohr=second["gradient_hartree_per_bohr"])
    assert np.max(np.abs(np.asarray(finer["frequencies_cm1"]) - modes)) < 1.0


@pytest.mark.integration
def test_complete_thermochemistry_workflow_has_reviewable_derivative_provenance(tmp_path):
    import copy

    from topos.config import SystemConfig
    from topos.publication import export_bundle, verify_bundle
    from topos.review import (
        append_decision,
        create_ensemble_manifest,
        validate_scientific_candidate,
    )
    from topos.storage import RunStore
    from topos.workflow import Workflow

    executable = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if executable is None:
        pytest.skip("real xTB required for physical Hessian acceptance")
    workflow = Workflow(tmp_path, config=SystemConfig(executables={"xtb": executable}, execution_backend="development"))
    record = workflow.run(RunRequest(molecule=water(), purpose="thermochemistry", budget_seconds=120,
                                    thermochemistry_options={"symmetry_number": 2}))
    assert record.status == "completed", record.metadata.get("termination_reason")
    assert record.validation_status == "validated-for-protocol"
    candidate = record.candidates[-1]
    assert candidate.gibbs_hartree is not None and candidate.status == "eligible"
    source = validate_scientific_candidate(record.model_dump(mode="json"), candidate.model_dump(mode="json"))
    assert source["metadata"]["result_kind"] == "physical-hessian-thermochemistry"
    assert len(source["metadata"]["derivative_attempt_ids"]) == 19
    assert record.metadata["frequency_optimization_policy"]["hamiltonian_changed"] is False
    assert record.metadata["derivative_coordinate_frame"]["kind"] == "proper-rigid-coordinate-transformation"
    store = RunStore(tmp_path / record.run_id)
    snapshot = store.verify()["snapshot_id"]
    assert workflow.resume(store.run_dir).model_dump(mode="json") == record.model_dump(mode="json")
    assert store.verify()["snapshot_id"] == snapshot
    for alteration in ("missing-derivative", "hessian", "gibbs", "geometry"):
        changed = copy.deepcopy(record.model_dump(mode="json"))
        selected = changed["candidates"][-1]
        aggregate = next(a for a in changed["attempts"] if a["attempt_id"] == selected["attempt_id"])
        if alteration == "missing-derivative":
            aggregate["metadata"]["derivative_attempt_ids"].pop()
        elif alteration == "hessian":
            next(q for q in aggregate["quantities"] if q["name"] == "cartesian_hessian")["value"][0][0] += 0.1
        elif alteration == "gibbs":
            selected["gibbs_hartree"] += 0.1
            next(q for q in aggregate["quantities"] if q["name"] == "gibbs_energy")["value"] += 0.1
        else:
            derivative = next(a for a in changed["attempts"] if a["attempt_id"] == aggregate["metadata"]["accepted_derivative_attempt_id"])
            derivative["metadata"]["output_molecule"]["coordinates"][0][0] += 0.1
        with pytest.raises(IntegrityError):
            validate_scientific_candidate(changed, selected)
    append_decision(store.run_dir, subject_id=candidate.candidate_id, action="accept", actor="thermochemistry-integration-test",
                    reason="Authentic derivative/provenance acceptance fixture, not an accuracy assertion")
    create_ensemble_manifest(store.run_dir, [candidate.candidate_id], actor="thermochemistry-integration-test")
    export_bundle(store.run_dir, tmp_path / "publication")
    verify_bundle(tmp_path / "publication")


@pytest.mark.integration
def test_frequency_workflow_cancellation_keeps_partial_native_work_and_resumes(tmp_path, monkeypatch):
    from topos.config import SystemConfig
    from topos.storage import RunStore
    from topos.workflow import Workflow

    executable = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if executable is None:
        pytest.skip("real xTB required for numerical derivative recovery")
    event = Event()
    workflow = Workflow(tmp_path, config=SystemConfig(executables={"xtb": executable}, execution_backend="development"))
    original = workflow._engine_attempt
    count = 0

    def interrupt_after_three_gradients(*args, **kwargs):
        nonlocal count
        attempt, result = original(*args, **kwargs)
        if result.operation == "gradient":
            count += 1
            if count == 3:
                event.set()
        return attempt, result

    monkeypatch.setattr(workflow, "_engine_attempt", interrupt_after_three_gradients)
    record = workflow.run(RunRequest(molecule=water(), purpose="frequency", budget_seconds=120,
                                    thermochemistry_options={"symmetry_number": 2}), cancel_event=event)
    assert record.status == "cancelled"
    assert count == 3
    native_ids = {a.attempt_id for a in record.attempts if a.metadata.get("advanced_role") == "physical-hessian-derivative"}
    event.clear()
    resumed = workflow.resume(tmp_path / record.run_id, cancel_event=event)
    assert resumed.status == "completed", resumed.metadata.get("termination_reason")
    assert count == 19
    assert native_ids.issubset({a.attempt_id for a in resumed.attempts})
    assert any(c.status == "cancelled" for c in resumed.candidates)
    assert resumed.candidates[-1].status == "eligible"
    RunStore(tmp_path / record.run_id).verify()
