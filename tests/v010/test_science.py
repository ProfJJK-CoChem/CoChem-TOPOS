"""Scientific contract regressions using analytic invariants, not synthetic engine passes."""
import math
import time
from threading import Event

import numpy as np
import pytest
from pydantic import ValidationError
from scipy import constants
from scipy.spatial.distance import pdist
from scipy.spatial.transform import Rotation

from topos.chemistry import classify_fragments, from_xyz, isotope_mass, to_xyz, validate_chemistry
from topos.models import Bond, Candidate, Molecule, RunRequest
from topos.science import (
    BOHR_ANGSTROM,
    HARTREE_EV,
    HARTREE_KCAL_MOL,
    KB_HARTREE_K,
    compare_candidates,
    compare_molecules,
    convert_ase_quantities,
    counterpoise_interaction,
    energy_comparison_key,
    ensemble_populations,
    geometry_digest,
    harmonic_analysis,
    rotational_constants,
    validate_derivatives,
    validate_stereochemical_preservation,
)


@pytest.fixture
def water():
    return Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.9572, 0, 0], [-.23999, .9273, 0]])


def test_input_rejects_nonfinite_count_spin_isotope_and_overlap(water):
    for update in (
        {"coordinates": [[0, 0, float("nan")], [1, 0, 0], [0, 1, 0]]},
        {"coordinates": [[0, 0, 0]]}, {"multiplicity": 2}, {"isotopes": [99, 1, 1]},
        {"fragments": [[0, 1], [1, 2]]},
    ):
        with pytest.raises((ValueError, ValidationError)):
            Molecule.model_validate({**water.model_dump(), **update})
    overlapping = Molecule(symbols=["He", "He"], coordinates=[[0, 0, 0], [0, 0, 0]])
    with pytest.raises(ValueError, match="coincident"):
        validate_chemistry(overlapping)
    hydrogen_radical = Molecule(symbols=["H"], coordinates=[[0, 0, 0]], multiplicity=2)
    assert hydrogen_radical.multiplicity == 2


def test_credentials_never_appear_in_contract_error(water):
    secret = "private-do-not-echo-test-value"
    with pytest.raises(ValidationError) as error:
        RunRequest(molecule=water, metadata={"nested": {"api_key": secret}})
    assert secret not in str(error.value)
    assert secret not in str(error.value.errors(include_input=False))
    with pytest.raises(ValidationError, match="nonfinite"):
        RunRequest(molecule=water, metadata={"uncertainty": float("inf")})


def test_fragment_states_require_physically_allowed_total_spin_coupling():
    closed_shell_fragments = {
        "symbols": ["He", "He"], "coordinates": [[0, 0, 0], [4, 0, 0]],
        "fragments": [[0], [1]],
        "fragment_states": [{"atom_indices": [0], "charge": 0, "multiplicity": 1},
                            {"atom_indices": [1], "charge": 0, "multiplicity": 1}],
    }
    assert Molecule(**closed_shell_fragments).multiplicity == 1
    with pytest.raises(ValidationError, match="cannot couple"):
        Molecule(**closed_shell_fragments, multiplicity=3)
    radical_fragments = {**closed_shell_fragments, "symbols": ["H", "H"],
        "fragment_states": [{"atom_indices": [0], "charge": 0, "multiplicity": 2},
                            {"atom_indices": [1], "charge": 0, "multiplicity": 2}]}
    assert Molecule(**radical_fragments, multiplicity=1).multiplicity == 1
    assert Molecule(**radical_fragments, multiplicity=3).multiplicity == 3


def test_xyz_preserves_typed_state_and_forbids_appended_frames(water):
    assert from_xyz(to_xyz(water), template=water) == water
    with pytest.raises(ValueError, match="exactly one frame"):
        from_xyz(to_xyz(water) * 2)
    with pytest.raises(ValueError, match="order/composition"):
        from_xyz(to_xyz(water).replace("O ", "S "), template=water)


def test_fragment_hypotheses_are_conservative(water):
    assert classify_fragments(water)["classification"] == "monomer"
    coords = np.asarray(water.coordinates)
    dimer = Molecule(symbols=water.symbols * 2, coordinates=np.vstack((coords, coords + [4, 0, 0])).tolist())
    result = classify_fragments(dimer)
    assert result["classification"] == "candidate-weak-complex"
    assert result["fragments"] == [[0, 1, 2], [3, 4, 5]]
    metal = Molecule(symbols=["Fe", "O"], coordinates=[[0, 0, 0], [2, 0, 0]])
    assert classify_fragments(metal)["classification"] == "unresolved"
    coordinated = Molecule.model_validate({**metal.model_dump(), "bonds": [Bond(atom1=0, atom2=1, kind="coordination").model_dump()]})
    assert classify_fragments(coordinated)["classification"] == "candidate-strong-complex"


def test_proper_rotation_permutation_and_state_checks(water):
    order = [2, 0, 1]
    xyz = Rotation.from_rotvec([.3, -.7, 1.1]).apply(np.asarray(water.coordinates))[order] + [4, -3, 2]
    permuted = Molecule(symbols=[water.symbols[i] for i in order], coordinates=xyz.tolist())
    result = compare_molecules(water, permuted)
    assert result["equivalent"] and result["rmsd_angstrom"] < 1e-12
    assert geometry_digest(water) != geometry_digest(permuted)
    triplet = Molecule.model_validate({**water.model_dump(), "multiplicity": 3})
    assert compare_molecules(water, triplet)["status"] == "different-state"


def test_mirror_image_is_not_merged_even_under_loose_rmsd():
    vectors = np.array([[0, 0, 0], [1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]], dtype=float)
    molecule = Molecule(symbols=["C", "H", "F", "Cl", "Br"], coordinates=vectors.tolist(),
                        bonds=[Bond(atom1=0, atom2=i) for i in range(1, 5)])
    mirror = Molecule.model_validate({**molecule.model_dump(), "coordinates": (vectors * [-1, 1, 1]).tolist()})
    assert compare_molecules(molecule, mirror, rmsd_threshold=10)["equivalent"] is False


def test_local_inversion_is_not_hidden_by_other_fragments_or_small_global_rmsd():
    coordinates = np.array([[0, 0, 0], [1, 1, .01], [1, -1, -.01], [-1, 1, -.01], [-1, -1, .01],
                            [10, 0, 0], [0, 20, 0], [0, 0, 30], [10, 20, 30]])
    original = Molecule(symbols=["C", "H", "F", "Cl", "Br", "He", "He", "He", "He"],
                        coordinates=coordinates.tolist(), bonds=[Bond(atom1=0, atom2=i) for i in range(1, 5)])
    coordinates[:5, 2] *= -1
    locally_inverted = original.model_copy(update={"coordinates": coordinates.tolist()})
    comparison = compare_molecules(original, locally_inverted)
    assert comparison["rmsd_angstrom"] < .125
    assert comparison["equivalent"] is False
    assert comparison["reason"] == "orientation differs"


@pytest.fixture
def chiral_molecule():
    return Molecule(
        symbols=["C", "H", "F", "Cl", "Br"],
        coordinates=[[0, 0, 0], [1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]],
        bonds=[Bond(atom1=0, atom2=i) for i in range(1, 5)],
        stereochemistry={"tetrahedral_centers": [{"center_atom_id": "atom-0",
                         "ordered_neighbor_ids": ["atom-1", "atom-2", "atom-3", "atom-4"],
                         "orientation": 1}]},
    )


def test_mapped_stereochemistry_checks_coordinates_despite_copied_labels(chiral_molecule):
    original = chiral_molecule
    transformed = Rotation.from_rotvec([.5, -.8, 1.2]).apply(original.coordinates) + [4, -2, 3]
    rotated = Molecule.model_validate({**original.model_dump(), "coordinates": transformed.tolist()})
    assert validate_stereochemical_preservation(original, rotated)["status"] == "preserved"
    inverted = Molecule.model_validate({**original.model_dump(),
                                        "coordinates": (np.asarray(original.coordinates) * [-1, 1, 1]).tolist()})
    result = validate_stereochemical_preservation(original, inverted)
    assert result["status"] == "inverted"
    assert result["centers"][0]["initial_volume"] > 0 > result["centers"][0]["final_volume"]
    undeclared = original.model_copy(update={"stereochemistry": {}})
    assert validate_stereochemical_preservation(undeclared, inverted.model_copy(update={"stereochemistry": {}}))["status"] == "inverted"


def test_stereochemical_mapping_uses_atom_ids_and_rejects_false_initial_assignment(chiral_molecule):
    order = [4, 2, 0, 3, 1]
    inverse = {old: new for new, old in enumerate(order)}
    original = chiral_molecule
    permuted = Molecule.model_validate({**original.model_dump(),
        "symbols": [original.symbols[i] for i in order],
        "coordinates": [original.coordinates[i] for i in order],
        "atom_ids": [original.atom_ids[i] for i in order],
        "bonds": [{"atom1": inverse[b.atom1], "atom2": inverse[b.atom2]} for b in original.bonds]})
    assert validate_stereochemical_preservation(original, permuted)["status"] == "preserved"
    incorrect = original.model_dump()
    incorrect["stereochemistry"]["tetrahedral_centers"][0]["orientation"] = -1
    wrong = Molecule.model_validate(incorrect)
    assert validate_stereochemical_preservation(wrong, wrong)["status"] == "invalid-input"


def test_ambiguous_and_unsupported_stereochemistry_require_review(chiral_molecule):
    original = chiral_molecule
    planar = np.asarray(original.coordinates, dtype=float)
    planar[:, 2] = 0
    changed = original.model_copy(update={"coordinates": planar.tolist()})
    assert validate_stereochemical_preservation(original, changed)["status"] == "ambiguous"
    opaque = original.model_copy(update={"stereochemistry": {"atom-0": "R"}})
    assert validate_stereochemical_preservation(opaque, opaque)["status"] == "unsupported"
    malformed = original.model_dump()
    malformed["stereochemistry"]["tetrahedral_centers"][0]["orientation"] = []
    invalid = Molecule.model_validate(malformed)
    assert validate_stereochemical_preservation(invalid, invalid)["status"] == "invalid-input"


def test_permutation_limit_retains_candidates():
    a = Molecule(symbols=["He"] * 4, coordinates=[[0, 0, 0], [4, 0, 0], [0, 5, 0], [0, 0, 6]])
    b = Molecule.model_validate({**a.model_dump(), "coordinates": [[0, 0, 0], [4.5, 0, 0], [0, 5, 0], [0, 0, 6]]})
    result = compare_molecules(a, b, rmsd_threshold=.01, max_permutations=1)
    assert result["status"] == "unresolved" and not result["equivalent"]


def test_fragment_charge_localization_and_partition_are_not_erased():
    neutral = Molecule(symbols=["Na", "Cl"], coordinates=[[0, 0, 0], [5, 0, 0]],
                       fragments=[[0], [1]], fragment_states=[
                           {"atom_indices": [0], "charge": 0, "multiplicity": 2},
                           {"atom_indices": [1], "charge": 0, "multiplicity": 2}])
    ionic = Molecule.model_validate({**neutral.model_dump(), "fragment_states": [
        {"atom_indices": [0], "charge": 1, "multiplicity": 1},
        {"atom_indices": [1], "charge": -1, "multiplicity": 1}]})
    assert compare_molecules(neutral, ionic)["status"] == "different-state"
    a = Candidate(molecule=neutral, energy_hartree=-10, comparison_protocol="same-method")
    b = Candidate(molecule=ionic, energy_hartree=-10, comparison_protocol="same-method")
    assert energy_comparison_key(a) != energy_comparison_key(b)
    assert compare_candidates(a, b)["status"] == "incomparable"

    horizontal = Molecule(symbols=["He"] * 4,
                          coordinates=[[0, 0, 0], [4, 0, 0], [0, 7, 0], [4, 7, 0]],
                          fragments=[[0, 1], [2, 3]])
    vertical = horizontal.model_copy(update={"fragments": [[0, 2], [1, 3]]})
    assert not compare_molecules(horizontal, vertical)["equivalent"]
    relabelled = horizontal.model_copy(update={"fragments": [[2, 3], [1, 0]]})
    assert compare_molecules(horizontal, relabelled)["equivalent"]


def test_isotope_placement_and_bond_order_are_part_of_graph_identity():
    labelled = Molecule(symbols=["C", "C", "O"], coordinates=[[0, 0, 0], [1.5, 0, 0], [2, 1.3, 0]],
                        isotopes=[13, 12, 16], bonds=[Bond(atom1=0, atom2=1), Bond(atom1=1, atom2=2)])
    relocated = labelled.model_copy(update={"isotopes": [12, 13, 16]})
    assert compare_molecules(labelled, relocated)["equivalent"] is False
    different_bond = labelled.model_copy(update={"bonds": [Bond(atom1=0, atom2=1, order=2), Bond(atom1=1, atom2=2)]})
    assert compare_molecules(labelled, different_bond)["equivalent"] is False
    unspecified = labelled.model_copy(update={"bonds": [Bond(atom1=0, atom2=1, kind="unknown"), Bond(atom1=1, atom2=2)]})
    assert compare_molecules(unspecified, unspecified)["status"] == "unresolved"


def test_signed_stereo_equivalence_uses_atom_mapping_not_label_spelling(chiral_molecule):
    renamed = chiral_molecule.model_dump()
    names = [f"renamed-{i}" for i in range(5)]
    renamed["atom_ids"] = names
    # Reversing two declared neighbors reverses the signed convention, not
    # the physical stereocenter. Both describe these same coordinates.
    renamed["stereochemistry"] = {"tetrahedral_centers": [{"center_atom_id": names[0],
        "ordered_neighbor_ids": [names[2], names[1], names[3], names[4]], "orientation": -1}]}
    assert compare_molecules(chiral_molecule, Molecule.model_validate(renamed))["equivalent"]
    opaque = chiral_molecule.model_copy(update={"stereochemistry": {"atom-0": "R"}})
    assert compare_molecules(opaque, opaque)["status"] == "unresolved"


def test_partial_graph_search_is_bounded_even_before_an_isomorphism_exists():
    coordinates = [[4 * math.cos(i * math.pi / 3), 4 * math.sin(i * math.pi / 3), 0] for i in range(6)]
    ring = Molecule(symbols=["C"] * 6, coordinates=coordinates,
                    bonds=[Bond(atom1=i, atom2=(i + 1) % 6) for i in range(6)])
    triangles = ring.model_copy(update={"bonds": [Bond(atom1=a, atom2=b) for a, b in
                                                 [(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3)]]})
    comparison = compare_molecules(ring, triangles, max_search_nodes=1)
    assert comparison["status"] == "unresolved" and comparison["permutations"] == 0
    assert comparison["search_nodes"] == 1
    assert "node budget" in comparison["reason"]
    assert compare_molecules(ring, triangles)["status"] == "distinct"


def test_comparison_deadline_and_cancellation_retain_candidates(water):
    candidate = Candidate(molecule=water, energy_hartree=-5, comparison_protocol="gfn2-validated")
    cancelled = Event()
    cancelled.set()
    for compare, args in ((compare_molecules, (water, water)), (compare_candidates, (candidate, candidate))):
        for kwargs in ({"deadline": time.monotonic() - 1}, {"cancel_event": cancelled}):
            result = compare(*args, **kwargs)
            assert result["status"] == "unresolved" and not result["equivalent"]
            assert "retain both" in result["reason"]


@pytest.mark.parametrize("limit", [0, -1, 1.5, True, float("nan"), float("inf")])
@pytest.mark.parametrize("name", ["max_permutations", "max_search_nodes"])
def test_comparison_limits_cannot_silently_disable_the_bound(water, name, limit):
    with pytest.raises(ValueError, match="limits"):
        compare_molecules(water, water, **{name: limit})


def test_generation_dedup_requires_energy_and_rotation_and_geometry(water):
    first = Candidate(molecule=water, energy_hartree=-5, comparison_protocol="gfn2-v1")
    energetically_distinct = first.model_copy(update={"energy_hartree": -5 + .051 / HARTREE_KCAL_MOL})
    energy_result = compare_candidates(first, energetically_distinct)
    assert not energy_result["equivalent"] and energy_result["criteria"]["energy"] is False
    assert energy_result["energy_difference_kcal_mol"] == pytest.approx(.051)

    # A 1% bond expansion is well within the RMSD cutoff, but changes the
    # rigid-rotor constants by ~1.97%, beyond the declared 1% generation gate.
    expanded = water.model_copy(update={"coordinates": (np.asarray(water.coordinates) * 1.01).tolist()})
    assert compare_molecules(water, expanded)["equivalent"]
    rotation_result = compare_candidates(first, first.model_copy(update={"molecule": expanded}))
    assert not rotation_result["equivalent"] and rotation_result["criteria"]["rotation"] is False
    assert rotation_result["rotational_fractional_differences"] == pytest.approx([1 - 1 / 1.01**2] * 3)

    rotated = water.model_copy(update={"coordinates": (Rotation.from_rotvec([.4, -.3, 1.1]).apply(water.coordinates) + [2, 4, -3]).tolist()})
    geometry_result = compare_candidates(first, first.model_copy(update={"molecule": rotated}))
    assert geometry_result["equivalent"] and all(geometry_result["criteria"].values())
    assert geometry_result["combination"] == "AND" and geometry_result["atom_selection"] == "all"


def test_homometric_inertia_and_equal_energy_do_not_prove_geometry_identity():
    # Classic one-dimensional homometric sets: equal multisets of all pair
    # distances and hence equal inertia, but neither translations nor mirrors.
    positions = ([0, 1, 4, 10, 12, 17], [0, 1, 8, 11, 13, 17])
    molecules = [Molecule(symbols=["He"] * 6, coordinates=[[4 * x, 0, 0] for x in group]) for group in positions]
    assert np.allclose(np.sort(pdist(molecules[0].coordinates)), np.sort(pdist(molecules[1].coordinates)))
    assert rotational_constants(molecules[0])["constants_ghz"][1:] == pytest.approx(rotational_constants(molecules[1])["constants_ghz"][1:])
    candidates = [Candidate(molecule=molecule, energy_hartree=-1, comparison_protocol="common-level") for molecule in molecules]
    result = compare_candidates(*candidates)
    assert result["criteria"] == {"comparable_energy": True, "energy": True, "rotation": True, "geometry": False}
    assert result["status"] == "distinct" and not result["equivalent"]


def test_generation_dedup_keeps_enantiomers_even_with_identical_spectra(chiral_molecule):
    # Remove declared stereo so that coordinate/graph identity carries the
    # decision instead of allowing copied metadata to decide the result.
    molecule = chiral_molecule.model_copy(update={"stereochemistry": {}})
    mirror = molecule.model_copy(update={"coordinates": (np.asarray(molecule.coordinates) * [-1, 1, 1]).tolist()})
    first, second = [Candidate(molecule=m, energy_hartree=-1, comparison_protocol="common-level") for m in (molecule, mirror)]
    result = compare_candidates(first, second, rmsd_threshold=10)
    assert result["criteria"]["energy"] and result["criteria"]["rotation"]
    assert not result["equivalent"] and result["reason"] == "orientation differs"


def test_planar_double_bond_stereoisomers_are_separate_under_loose_rmsd():
    trans = Molecule(symbols=["C", "C", "H", "F", "H", "F"],
                     coordinates=[[0, 0, 0], [1.34, 0, 0], [-.5, -.9, 0], [-.5, 1.2, 0],
                                  [1.84, .9, 0], [1.84, -1.2, 0]],
                     bonds=[Bond(atom1=0, atom2=1, order=2), Bond(atom1=0, atom2=2),
                            Bond(atom1=0, atom2=3), Bond(atom1=1, atom2=4), Bond(atom1=1, atom2=5)])
    cis_coordinates = np.asarray(trans.coordinates)
    cis_coordinates[4:, 1] *= -1
    cis = trans.model_copy(update={"coordinates": cis_coordinates.tolist()})
    result = compare_molecules(trans, cis, rmsd_threshold=10)
    assert not result["equivalent"] and result["reason"] == "orientation differs"
    assert result["rmsd_angstrom"] < 10
    # Exchanging entire alkene ends and atom ordering must not itself create
    # a false cis/trans difference.
    order = [1, 0, 4, 5, 2, 3]
    inverse = {old: new for new, old in enumerate(order)}
    swapped = Molecule.model_validate({**trans.model_dump(),
        "symbols": [trans.symbols[i] for i in order],
        "coordinates": (Rotation.from_rotvec([.2, .6, .4]).apply(trans.coordinates)[order] + [3, -1, 2]).tolist(),
        "bonds": [{**bond.model_dump(), "atom1": inverse[bond.atom1], "atom2": inverse[bond.atom2]} for bond in trans.bonds]})
    assert compare_molecules(trans, swapped)["equivalent"]
    ambiguous_coordinates = np.asarray(trans.coordinates)
    ambiguous_coordinates[2] = [-1, 0, 0]
    ambiguous_coordinates[3] = [-2, 0, 0]
    ambiguous = trans.model_copy(update={"coordinates": ambiguous_coordinates.tolist()})
    assert compare_molecules(ambiguous, ambiguous)["status"] == "unresolved"


def test_generation_dedup_handles_monatomic_and_linear_zero_inertia_axes():
    helium = Molecule(symbols=["He"], coordinates=[[0, 0, 0]])
    hydrogen = Molecule(symbols=["H", "H"], coordinates=[[-.37, 0, 0], [.37, 0, 0]])
    for molecule, undefined in ((helium, 3), (hydrogen, 1)):
        first = Candidate(molecule=molecule, energy_hartree=-1, comparison_protocol="common-level")
        second = first.model_copy(update={"molecule": molecule.model_copy(update={"coordinates":
            (Rotation.from_rotvec([.2, .6, .9]).apply(molecule.coordinates) + [4, -3, 2]).tolist()})})
        result = compare_candidates(first, second)
        assert result["equivalent"]
        assert result["rotational_fractional_differences"].count(None) == undefined


@pytest.mark.parametrize("update", [{"comparison_protocol": None}, {"comparison_protocol": " "},
                                     {"comparison_protocol": "another-method"}, {"energy_hartree": None},
                                     {"energy_hartree": float("nan")}])
def test_generation_dedup_never_merges_missing_or_incomparable_energies(water, update):
    first = Candidate(molecule=water, energy_hartree=-5, comparison_protocol="gfn2-v1")
    second = first.model_copy(update=update)
    result = compare_candidates(first, second)
    assert result["status"] == "incomparable" and not result["equivalent"]


def test_atomic_units_and_derivative_sign_are_consistent():
    result = convert_ase_quantities(HARTREE_EV, [[-HARTREE_EV / BOHR_ANGSTROM, 0, 0]],
                                    np.eye(3) * HARTREE_EV / BOHR_ANGSTROM ** 2, natoms=1)
    assert result["energy_hartree"] == pytest.approx(1)
    assert np.allclose(result["gradient_hartree_per_bohr"], [[1, 0, 0]])
    assert np.allclose(result["hessian_hartree_per_bohr2"], np.eye(3))
    validate_derivatives(np.zeros((1, 3)), np.zeros((3, 3)), natoms=1)
    with pytest.raises(ValueError, match="symmetric"):
        validate_derivatives(hessian=[[0, 1, 0], [0, 0, 0], [0, 0, 0]], natoms=1)


def test_isotope_inertia_and_linear_axis_are_physical():
    h2 = Molecule(symbols=["H", "H"], coordinates=[[-.37, 0, 0], [.37, 0, 0]], isotopes=[1, 1])
    d2 = Molecule.model_validate({**h2.model_dump(), "isotopes": [2, 2]})
    first, second = rotational_constants(h2), rotational_constants(d2)
    assert first["geometry_class"] == "linear"
    assert first["constants_ghz"][0] is None
    ratio = isotope_mass("H", 2) / isotope_mass("H", 1)
    assert first["constants_ghz"][1] / second["constants_ghz"][1] == pytest.approx(ratio)
    assert first["not_measured_B0"] is True


def test_ensemble_uses_one_protocol_stable_weights_and_no_duplicate_observations(water):
    t = 298.15
    candidates = [Candidate(molecule=water, energy_hartree=-75, comparison_protocol="xtb-v1"),
                  Candidate(molecule=water, energy_hartree=-75 + KB_HARTREE_K * t * math.log(3), comparison_protocol="xtb-v1")]
    result = ensemble_populations(candidates, temperature_k=t)
    assert list(result["populations"].values()) == pytest.approx([.75, .25])
    assert result["weight_kind"] == "electronic-energy-weights-not-Gibbs-populations"
    shifted = [c.model_copy(update={"energy_hartree": c.energy_hartree + 10}) for c in candidates]
    assert list(ensemble_populations(shifted)["populations"].values()) == pytest.approx([.75, .25])
    with pytest.raises(ValueError, match="duplicate candidate"):
        ensemble_populations([candidates[0], candidates[0]])
    with pytest.raises(ValueError, match="comparison protocol"):
        ensemble_populations([candidates[0], candidates[1].model_copy(update={"comparison_protocol": "orca-v1"})])
    with pytest.raises(ValueError, match="gibbs_hartree"):
        ensemble_populations(candidates, quantity="gibbs")
    candidates[0].gibbs_hartree = -74.9
    candidates[1].gibbs_hartree = -74.9
    assert list(ensemble_populations(candidates, quantity="gibbs")["populations"].values()) == pytest.approx([.5, .5])


def test_counterpoise_sign_and_reference_subtractions():
    result = counterpoise_interaction(-2.01, -1.001, -1.002, -1, -1)
    assert result["raw_interaction_hartree"] == pytest.approx(-.01)
    assert result["cp_interaction_hartree"] == pytest.approx(-.007)
    assert result["additive_cp_correction_hartree"] == pytest.approx(.003)


def test_diatomic_modes_isotope_ratio_and_zpe_units():
    h2 = Molecule(symbols=["H", "H"], coordinates=[[-.37, 0, 0], [.37, 0, 0]], isotopes=[1, 1])
    hessian = np.zeros((6, 6))
    # Analytic Cartesian Hessian for a radial harmonic spring at equilibrium.
    hessian[0, 0] = hessian[3, 3] = 1
    hessian[0, 3] = hessian[3, 0] = -1
    h = harmonic_analysis(h2, hessian, gradient_hartree_per_bohr=np.zeros((2, 3)))
    d = harmonic_analysis(h2.model_copy(update={"isotopes": [2, 2]}), hessian,
                          gradient_hartree_per_bohr=np.zeros((2, 3)))
    assert h["vibrational_modes"] == 1 and h["removed_rigid_modes"] == 5
    assert h["frequencies_cm1"][0] / d["frequencies_cm1"][0] == pytest.approx(math.sqrt(isotope_mass("H", 2) / isotope_mass("H", 1)))
    expected_zpe = .5 * constants.h * constants.c * 100 * h["frequencies_cm1"][0] / constants.physical_constants["Hartree energy"][0]
    assert h["zpe_hartree"] == pytest.approx(expected_zpe)
    assert harmonic_analysis(h2, hessian)["zpe_hartree"] is None
    with pytest.raises(ValueError, match="constrained thermochemistry"):
        harmonic_analysis(h2, hessian, constraints={"frozen_fragments": True})


def test_nonlinear_projection_and_unstable_mode_classification(water):
    good = harmonic_analysis(water, np.eye(9), gradient_hartree_per_bohr=np.zeros((3, 3)))
    assert good["vibrational_modes"] == 3 and good["removed_rigid_modes"] == 6
    bad = harmonic_analysis(water, -np.eye(9), gradient_hartree_per_bohr=np.zeros((3, 3)))
    assert bad["validity"] == "unstable-modes" and bad["zpe_hartree"] is None
    nonstationary = harmonic_analysis(water, np.eye(9), gradient_hartree_per_bohr=np.ones((3, 3)))
    assert nonstationary["validity"] == "nonstationary" and nonstationary["zpe_hartree"] is None


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("name", ["gradient_threshold", "imaginary_tolerance_cm1"])
def test_harmonic_analysis_rejects_nonfinite_classification_thresholds(water, threshold, name):
    with pytest.raises(ValueError, match="thresholds"):
        harmonic_analysis(water, np.eye(9), **{name: threshold})
