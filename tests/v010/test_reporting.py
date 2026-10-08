"""Analytical comparison contracts, not quantum-chemistry benchmark energies."""
import time
from threading import Event

import numpy as np
import pytest

from topos.models import Bond, Candidate, Molecule
from topos.reporting import compare_reporting_candidates, enantiomer_relation, reporting_ensemble
from topos.science import HARTREE_KCAL_MOL, compare_molecules


def water():
    return Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.758, 0, .504], [-.758, 0, .504]])


def chiral():
    return Molecule(symbols=["C", "H", "F", "Cl", "Br"],
                    coordinates=[[0, 0, 0], [1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]],
                    bonds=[Bond(atom1=0, atom2=i) for i in range(1, 5)])


def reflected(molecule):
    result = molecule.model_copy(deep=True)
    result.coordinates = [[-x, y, z] for x, y, z in result.coordinates]
    return result


def candidate(molecule=None, *, shift=0, protocol="analytical-comparison-protocol"):
    return Candidate(molecule=molecule or water(), energy_hartree=-1 + shift / HARTREE_KCAL_MOL,
                     comparison_protocol=protocol)


def test_matrix_reporting_requires_declared_qm_refinement():
    result = compare_reporting_candidates(candidate(), candidate(), qm_refined=False)
    assert result["status"] == "unresolved"
    assert not result["equivalent"]


def test_matrix_reporting_all_three_criteria_and_recorded_thresholds():
    result = compare_reporting_candidates(candidate(), candidate(), qm_refined=True)
    assert result["equivalent"]
    assert all(result["criteria"].values())
    assert result["combination"] == "AND"
    assert result["energy_threshold_kcal_mol"] == .05
    assert result["rotational_threshold_fraction"] == .001
    assert result["geometry"]["atom_selection"] == "heavy (Z > 1)"


def test_identical_geometry_cannot_override_energy_threshold():
    result = compare_reporting_candidates(candidate(), candidate(shift=.06), qm_refined=True)
    assert result["status"] == "distinct"
    assert result["criteria"]["energy"] is False


def test_equal_energy_cannot_override_rotational_threshold():
    altered = water()
    altered.coordinates = (np.asarray(altered.coordinates) * 1.001).tolist()
    result = compare_reporting_candidates(candidate(), candidate(altered), qm_refined=True)
    assert result["status"] == "distinct"
    assert result["criteria"]["rotation"] is False


def test_energy_and_inertia_never_merge_enantiomer_identity():
    first = chiral()
    result = compare_reporting_candidates(candidate(first), candidate(reflected(first)), qm_refined=True)
    assert result["criteria"]["energy"]
    assert result["criteria"]["rotation"]
    assert not result["criteria"]["geometry"]
    assert not result["equivalent"]


def test_heavy_rmsd_does_not_silently_reuse_generation_all_atom_rmsd():
    def methyl_rotor(phi):
        return Molecule(symbols=["C", "C", "O", "H"] + ["H"] * 3,
                        coordinates=[[0, 0, 0], [0, 0, 1.5], [1.2, 0, 2.0], [-.9, 0, 2.0]] +
                        [[np.cos(i * 2 * np.pi / 3 + phi), np.sin(i * 2 * np.pi / 3 + phi), -.3] for i in range(3)],
                        bonds=[Bond(atom1=0, atom2=1), Bond(atom1=1, atom2=2, order=2), Bond(atom1=1, atom2=3)] +
                        [Bond(atom1=0, atom2=i) for i in range(4, 7)])
    a, b = methyl_rotor(.1), methyl_rotor(.1 + np.pi / 6)
    assert compare_molecules(a, b)["rmsd_angstrom"] > .125
    result = compare_reporting_candidates(candidate(a), candidate(b), qm_refined=True)
    assert result["equivalent"]
    assert result["geometry"]["rmsd_angstrom"] < 1e-12


def test_protocol_mismatch_is_incomparable():
    result = compare_reporting_candidates(candidate(protocol="one"), candidate(protocol="two"), qm_refined=True)
    assert result["status"] == "incomparable"


def test_missing_energy_cannot_be_reported_as_equal():
    absent = candidate()
    absent.energy_hartree = None
    assert compare_reporting_candidates(candidate(), absent, qm_refined=True)["status"] == "incomparable"


def test_all_hydrogen_reporting_rmsd_explicitly_undefined():
    hydrogen = Molecule(symbols=["H", "H"], coordinates=[[-.4, 0, 0], [.4, 0, 0]])
    result = compare_reporting_candidates(candidate(hydrogen), candidate(hydrogen), qm_refined=True)
    assert result["status"] == "unresolved"
    assert "all-hydrogen" in result["reason"]


def test_supplied_dipole_disagreement_requires_review_even_when_three_tests_pass():
    result = compare_reporting_candidates(candidate(), candidate(), qm_refined=True,
                                          dipole_a_debye=[0, 0, 1], dipole_b_debye=[0, 0, 2], dipole_error_debye=.1)
    assert all(result["criteria"].values())
    assert result["equivalent"] is False
    assert result["dipole_consistency"] == "requires-review"


def test_only_actual_complete_dipoles_can_supply_a_consistency_check():
    result = compare_reporting_candidates(candidate(), candidate(), qm_refined=True, dipole_a_debye=[0, 0, 1])
    assert result["equivalent"] is False
    assert result["dipole_consistency"] == "incomplete"


def test_reflection_relation_records_proper_failure_and_improper_success():
    first = chiral()
    result = enantiomer_relation(first, reflected(first))
    assert result["relation"] == "enantiomeric-geometries"
    assert result["proper_comparison"]["equivalent"] is False
    assert result["improper_comparison"]["equivalent"] is True
    assert result["degeneracy_assigned"] is False


def test_achiral_water_mirror_is_not_an_enantiomer_pair():
    assert enantiomer_relation(water(), reflected(water()))["relation"] == "same-handed-geometry"


def test_no_universal_degeneracy_two_for_a_single_chiral_candidate():
    result = reporting_ensemble([candidate(chiral())], qm_refined=True, collapse_enantiomers=True, environment_is_achiral=True)
    assert result["representatives"][0].degeneracy == 1


def test_sampled_enantiomer_pair_collapses_only_reporting_group_and_weight_once():
    first = chiral()
    inputs = [candidate(first), candidate(reflected(first)), candidate(first), candidate(reflected(first))]
    result = reporting_ensemble(inputs, qm_refined=True, collapse_enantiomers=True, environment_is_achiral=True)
    assert len(result["representatives"]) == 1
    assert result["representatives"][0].degeneracy == 2
    assert len(result["groups"][0]) == 4
    assert result["identity_records_retained"]
    assert [item.degeneracy for item in inputs] == [1, 1, 1, 1]
    assert "never include both" in result["partition_function_convention"]


def test_existing_degeneracy_is_not_counted_twice():
    first = chiral()
    inputs = [candidate(first), candidate(reflected(first))]
    inputs[0].degeneracy = 2
    result = reporting_ensemble(inputs, qm_refined=True, collapse_enantiomers=True, environment_is_achiral=True)
    assert len(result["representatives"]) == 2
    assert [item.degeneracy for item in result["representatives"]] == [2, 1]


def test_duplicate_hits_do_not_increase_g():
    inputs = [candidate(), candidate(), candidate()]
    result = reporting_ensemble(inputs, qm_refined=True)
    assert len(result["representatives"]) == 1
    assert result["representatives"][0].degeneracy == 1


@pytest.mark.parametrize("environment", [None, False])
def test_chiral_or_unspecified_environment_does_not_allow_enantiomer_collapse(environment):
    with pytest.raises(ValueError, match="achiral"):
        reporting_ensemble([candidate(chiral())], qm_refined=True,
                           collapse_enantiomers=True, environment_is_achiral=environment)


def test_enantiomer_isotopologue_difference_is_not_pairable():
    first = chiral()
    second = reflected(first)
    second.isotopes = [13, None, None, None, None]
    result = enantiomer_relation(first, second)
    assert result["relation"] == "unresolved"
    assert result["proper_comparison"]["status"] == "different-state"


def test_deadline_and_cancel_retain_candidates():
    cancelled = Event()
    cancelled.set()
    for kwargs in [{"deadline": time.monotonic() - 1}, {"cancel_event": cancelled}]:
        result = compare_reporting_candidates(candidate(), candidate(), qm_refined=True, **kwargs)
        assert result["status"] == "unresolved"
        assert result["equivalent"] is False


def test_invalid_budgets_are_rejected():
    with pytest.raises(ValueError):
        compare_reporting_candidates(candidate(), candidate(), qm_refined=True, max_permutations=0)


def test_repeated_candidate_id_cannot_double_partition_function_weight():
    first = candidate()
    with pytest.raises(ValueError, match="unique"):
        reporting_ensemble([first, first], qm_refined=True)


def test_workflow_reporting_request_does_not_assert_xtb_screening_is_qm_refinement():
    from topos.models import RunRecord, RunRequest
    from topos.workflow import Workflow

    record = RunRecord(request=RunRequest(molecule=water(), deduplication_stage="reporting"),
                       candidates=[candidate(), candidate()])
    for item in record.candidates:
        item.status = "eligible"
    assert Workflow._compare(record) == "completed"
    assert record.metadata["deduplication"]["inconclusive_comparisons"] == 1
    assert record.metadata["reporting_ensemble"]["status"] == "requires-review"
    assert all(item.status == "eligible" for item in record.candidates)
    assert all(not evidence["verified"] for evidence in record.metadata["reporting_refinement"].values())


def test_workflow_near_symmetry_flags_review_without_inventing_a_new_species():
    from topos.models import RunRecord, RunRequest
    from topos.workflow import Workflow

    record = RunRecord(request=RunRequest(molecule=water()), candidates=[candidate(), candidate()])
    for item, group in zip(record.candidates, ["C2v", "Cs"], strict=True):
        item.status = "eligible"
        item.metadata["point_group"] = {"status": "stable", "point_group": group}
    Workflow._compare(record)
    assert sorted(item.status for item in record.candidates) == ["duplicate", "eligible"]
    comparison = next(item.metadata["identity_comparisons"][0] for item in record.candidates if item.metadata["identity_comparisons"])
    assert comparison["status"] == "equivalent"
    assert comparison["symmetry_review"]["point_groups"]
    assert all(item.metadata["symmetry_review_required"] for item in record.candidates)


def test_reporting_refinement_gate_binds_attempt_geometry_and_energy():
    """Synthetic provenance-contract records; no ORCA calculation is claimed."""
    from topos.models import Artifact, Attempt, Quantity, RunRecord, RunRequest
    from topos.workflow import Workflow

    item = candidate()
    attempt = Attempt(run_id="analytical-contract", engine="orca", method="HF-3c",
                      engine_version="6.1.1", command=["analytical-unit-contract"], status="completed",
                      converged=True, validation_status="validated-for-protocol",
                      artifacts=[Artifact(path="analytical-contract.txt", sha256="0" * 64, size_bytes=0)],
                      metadata={"operation": "optimize", "execution_kind": "real",
                                "comparison_protocol": item.comparison_protocol,
                                "output_molecule": item.molecule.model_dump(mode="json")},
                      quantities=[Quantity(name="electronic_energy", value=item.energy_hartree, units="hartree",
                                           definition="analytical contract value, not an ORCA result", geometry_id=item.candidate_id,
                                           validity="validated-for-protocol")])
    item.attempt_id = attempt.attempt_id
    record = RunRecord(request=RunRequest(molecule=water(), engine="orca", method="HF-3c", deduplication_stage="reporting"),
                       candidates=[item], attempts=[attempt])
    assert Workflow._reporting_refinement(record, item)["verified"] is True
    attempt.metadata["operation"] = "energy"
    assert Workflow._reporting_refinement(record, item)["verified"] is False
    attempt.metadata["operation"] = "optimize"
    item.molecule.coordinates[1][0] += .01
    assert Workflow._reporting_refinement(record, item)["verified"] is False
    item.molecule = water()
    item.energy_hartree -= .1
    assert Workflow._reporting_refinement(record, item)["verified"] is False


def test_actual_stored_dipoles_are_checked_only_with_declared_method_error():
    first, second = candidate(), candidate()
    first.metadata["dipole"] = {"cartesian_debye": [0, 0, 1]}
    second.metadata["dipole"] = {"cartesian_debye": [0, 0, 2]}
    unspecified = compare_reporting_candidates(first, second, qm_refined=True)
    assert unspecified["dipole_consistency"] == "not-evaluated-method-error-unavailable"
    checked = compare_reporting_candidates(first, second, qm_refined=True, dipole_error_debye=.1)
    assert checked["dipole_consistency"] == "requires-review"
    assert not checked["equivalent"]


def test_reporting_ensemble_does_not_bypass_enantiomer_dipole_disagreement():
    first = candidate(chiral())
    second = candidate(reflected(first.molecule))
    first.metadata["dipole"] = {"cartesian_debye": [1, 0, 0]}
    second.metadata["dipole"] = {"cartesian_debye": [-2, 0, 0]}
    result = reporting_ensemble([first, second], qm_refined=True, collapse_enantiomers=True,
                                environment_is_achiral=True, dipole_error_debye=.1)
    assert len(result["representatives"]) == 2
    assert result["decisions"][0]["enantiomer_dipole_check"]["dipole_consistency"] == "requires-review"
    second.metadata["dipole"]["cartesian_debye"] = [-1, 0, 0]
    result = reporting_ensemble([first, second], qm_refined=True, collapse_enantiomers=True,
                                environment_is_achiral=True, dipole_error_debye=.1)
    assert len(result["representatives"]) == 1
    assert result["representatives"][0].degeneracy == 2
