"""Numerical composite contracts; constructed inputs are mathematical fixtures.

No fixture in this module represents an electronic-structure engine result.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from topos.composites import (
    JUNCHS_CBS_COEFFICIENT,
    CompositeCoordinate,
    CompositeCoordinateSet,
    combine_junchs_geometry,
    cps67,
    weighted_energy_sum,
)
from topos.models import Molecule


def chart(definitions):
    return CompositeCoordinateSet(
        coordinates=[CompositeCoordinate(kind=kind, atoms=atoms) for kind, atoms in definitions],
        cv_basis="cc-pwCVTZ", cv_resolution="same-basis-ae-minus-fc")


def water_chart():
    return chart([("distance", [0, 1]), ("distance", [0, 2]), ("angle", [1, 0, 2])])


def water(r1=.96, r2=.97, angle=104.):
    angle = math.radians(angle)
    return Molecule(symbols=["O", "H", "H"],
                    coordinates=[[0, 0, 0], [r1, 0, 0],
                                 [r2 * math.cos(angle), r2 * math.sin(angle), 0]],
                    bonds=[{"atom1": 0, "atom2": 1}, {"atom1": 0, "atom2": 2}],
                    isotopes=[18, 2, None], atom_ids=["oxygen", "deuterium", "hydrogen"])


def parameters(molecule):
    xyz = np.asarray(molecule.coordinates)
    u, v = xyz[1] - xyz[0], xyz[2] - xyz[0]
    return [np.linalg.norm(u), np.linalg.norm(v),
            math.degrees(math.acos(np.dot(u, v) / np.linalg.norm(u) / np.linalg.norm(v)))]


def transformed(molecule, angle, translation):
    angle = math.radians(angle)
    rotation = np.array([[math.cos(angle), -math.sin(angle), 0],
                         [math.sin(angle), math.cos(angle), 0], [0, 0, 1]])
    data = molecule.model_dump()
    data["coordinates"] = (np.asarray(molecule.coordinates) @ rotation + translation).tolist()
    return Molecule.model_validate(data)


def chain(torsion):
    """An analytic four-centre internal-coordinate fixture, not optimized HOOH."""
    theta, phi, tau = map(math.radians, [108, 109, torsion])
    return Molecule(symbols=["H", "O", "O", "H"], coordinates=[
        [.97 * math.cos(theta), .97 * math.sin(theta), 0], [0, 0, 0], [1.45, 0, 0],
        [1.45 - .98 * math.cos(phi), .98 * math.sin(phi) * math.cos(tau),
         .98 * math.sin(phi) * math.sin(tau)]])


def chain_chart():
    return chart([("distance", [0, 1]), ("distance", [1, 2]), ("distance", [2, 3]),
                  ("angle", [0, 1, 2]), ("angle", [1, 2, 3]), ("dihedral", [0, 1, 2, 3])])


def test_internal_composite_matches_analytic_water_parameters_and_preserves_identity():
    values = [[.96, .97, 104], [1., 1.01, 102], [.99, 1.012, 102.5],
              [1.001, 1.003, 103.2], [1., 1., 103]]
    molecules = [water(*item) for item in values]
    before = [molecule.model_dump() for molecule in molecules]
    report = combine_junchs_geometry(*molecules, water_chart())
    result = Molecule.model_validate(report["molecule"])
    expected = np.array(values[0]) + 64 / 37 * (np.array(values[2]) - values[1]) + np.array(values[3]) - values[4]
    np.testing.assert_allclose(parameters(result), expected, atol=1e-8, rtol=0)
    np.testing.assert_allclose(report["target_parameters"], expected, atol=1e-12, rtol=0)
    assert result.model_dump(exclude={"coordinates"}) == molecules[0].model_dump(exclude={"coordinates"})
    assert report["residual"]["max_abs_native"] < 1e-10
    assert report["coordinate_units"] == ["angstrom", "angstrom", "degree"]
    assert len(report["component_geometry_sha256"]) == 5
    assert all(value > 1e-10 for value in report["jacobian_smallest_to_largest_singular_value"].values())
    assert [molecule.model_dump() for molecule in molecules] == before
    assert report["claims"]["scope"] == "constructed equilibrium geometry for B_e analysis only"
    assert not any(value for key, value in report["claims"].items() if isinstance(value, bool))


def test_independent_component_rotations_and_translations_do_not_change_composite():
    molecules = [water(), water(1.01, .99, 105), water(1.011, .994, 105.2),
                 water(.961, .971, 104.3), water()]
    original = combine_junchs_geometry(*molecules, water_chart())
    moved = [transformed(molecule, 31 * index + 12, [3 * index, -index, .4 * index])
             for index, molecule in enumerate(molecules)]
    rotated = combine_junchs_geometry(*moved, water_chart())
    np.testing.assert_allclose(rotated["target_parameters"], original["target_parameters"], atol=1e-12)
    expected = transformed(Molecule.model_validate(original["molecule"]), 12, [0, 0, 0])
    np.testing.assert_allclose(rotated["molecule"]["coordinates"], expected.coordinates, atol=1e-10)


def test_periodic_dihedral_increments_cross_seam_in_shortest_direction():
    report = combine_junchs_geometry(chain(179), chain(179), chain(-179),
                                     chain(-179), chain(179), chain_chart())
    expected = (179 + 64 / 37 * 2 + 2 + 180) % 360 - 180
    assert report["increments"]["cbs"][-1] == pytest.approx(64 / 37 * 2)
    assert report["increments"]["core_valence"][-1] == pytest.approx(2)
    assert report["target_parameters"][-1] == pytest.approx(expected)
    assert report["realized_parameters"][-1] == pytest.approx(expected, abs=1e-8)
    assert report["residual"]["max_abs_native"] < 1e-10
    assert np.linalg.norm(np.array(report["molecule"]["coordinates"]) - chain(179).coordinates) < .1


def test_antipodal_dihedral_increment_is_rejected_as_ambiguous():
    with pytest.raises(ValueError, match="no unique shortest direction"):
        combine_junchs_geometry(chain(90), chain(0), chain(180), chain(90), chain(90), chain_chart())


@pytest.mark.parametrize("replacement", [
    {"charge": 2}, {"multiplicity": 3}, {"isotopes": [16, 2, None]},
    {"atom_ids": ["different", "deuterium", "hydrogen"]}, {"bonds": []},
    {"fragments": [[0, 1, 2]]}, {"environment": {"solvent": "water"}},
    {"stereochemistry": {"declared": "different"}},
])
def test_chemical_identity_cannot_change_between_components(replacement):
    molecule = water()
    data = molecule.model_dump()
    data.update(replacement)
    changed = Molecule.model_validate(data)
    with pytest.raises(ValueError, match="identity"):
        combine_junchs_geometry(molecule, changed, molecule, molecule, molecule, water_chart())


def test_incomplete_and_redundant_coordinate_charts_are_rejected():
    molecule = water()
    incomplete = chart([("distance", [0, 1])])
    redundant = chart([("distance", [0, 1]), ("distance", [1, 0]), ("angle", [1, 0, 2])])
    with pytest.raises(ValueError, match="exactly 3"):
        combine_junchs_geometry(*([molecule] * 5), incomplete)
    with pytest.raises(ValueError, match="redundant or locally singular"):
        combine_junchs_geometry(*([molecule] * 5), redundant)


def test_chart_rank_checked_in_every_component():
    # All pair distances form a valid nonlinear-triatomic chart, but cease to
    # be independent at the collinear CV component.
    distances = chart([("distance", [0, 1]), ("distance", [0, 2]), ("distance", [1, 2])])
    data = water().model_dump()
    data["coordinates"] = [[0, 0, 0], [1, 0, 0], [-1, 0, 0]]
    with pytest.raises(ValueError, match="Linear polyatomics"):
        combine_junchs_geometry(water(), water(), water(), Molecule.model_validate(data), water(), distances)


def test_copied_stereo_labels_cannot_hide_a_reflected_component():
    points = [[1, 1, 1], [-1, -1, 1], [-1, 1, -1], [1, -1, -1]]
    determinant = np.linalg.det(np.array(points[:3]) - points[3])
    molecule = Molecule(symbols=["C", "H", "F", "Cl", "Br"],
                        coordinates=[[0, 0, 0], *points],
                        bonds=[{"atom1": 0, "atom2": index} for index in range(1, 5)],
                        stereochemistry={"tetrahedral_centers": [{
                            "center_atom_id": "atom-0", "ordered_neighbor_ids": [f"atom-{index}" for index in range(1, 5)],
                            "orientation": int(np.sign(determinant))}]})
    coordinates = chart([("distance", [0, index]) for index in range(1, 5)]
                        + [("angle", [first, 0, second]) for first, second in
                           [(1, 2), (1, 3), (1, 4), (2, 3), (2, 4)]])
    unchanged = combine_junchs_geometry(*([molecule] * 5), coordinates)
    assert unchanged["stereochemistry_checks"]["composite"]["status"] == "preserved"
    assert unchanged["stereochemistry_checks"]["composite"]["centers"]
    data = molecule.model_dump()
    data["coordinates"] = (np.asarray(molecule.coordinates) * [-1, 1, 1]).tolist()
    reflected = Molecule.model_validate(data)
    with pytest.raises(ValueError, match="changed stereochemistry"):
        combine_junchs_geometry(molecule, reflected, molecule, molecule, molecule, coordinates)


def test_opaque_stereo_labels_need_a_validated_interpreter():
    data = water().model_dump()
    data["stereochemistry"] = {"opaque-label": "cannot-certify"}
    molecule = Molecule.model_validate(data)
    with pytest.raises(ValueError, match="unsupported.*stereochemistry"):
        combine_junchs_geometry(*([molecule] * 5), water_chart())


@pytest.mark.parametrize("kind,atoms", [
    ("distance", [0, 0]), ("angle", [0, 1]), ("dihedral", [0, 1, 2]),
    ("distance", [-1, 1]), ("distance", [False, 1]), ("distance", [0., 1]),
])
def test_coordinate_indices_are_strict_distinct_and_kind_specific(kind, atoms):
    with pytest.raises(ValueError):
        CompositeCoordinate(kind=kind, atoms=atoms)


def test_unknown_atom_and_untyped_chart_rejected():
    invalid = chart([("distance", [0, 1]), ("distance", [0, 3]), ("angle", [1, 0, 2])])
    with pytest.raises(ValueError, match="nonexistent atom"):
        combine_junchs_geometry(*([water()] * 5), invalid)
    with pytest.raises(ValueError, match="explicit typed"):
        combine_junchs_geometry(*([water()] * 5), water_chart().model_dump())


@pytest.mark.parametrize("updates", [{"cv_basis": "cc-pVTZ"}, {"cv_resolution": "mixed-basis"}])
def test_core_valence_basis_and_resolution_cannot_be_silently_changed(updates):
    data = water_chart().model_dump()
    data.update(updates)
    with pytest.raises(ValueError):
        CompositeCoordinateSet.model_validate(data)
    data = water_chart().model_dump()
    del data["cv_resolution"]
    with pytest.raises(ValueError):
        CompositeCoordinateSet.model_validate(data)


@pytest.mark.parametrize("components,match", [
    ([water(.5), water(2), water(.1), water(), water()], "distance target"),
    ([water(angle=100), water(angle=1), water(angle=179), water(), water()], "bond-angle target"),
])
def test_extrapolation_cannot_create_unphysical_targets(components, match):
    with pytest.raises(ValueError, match=match):
        combine_junchs_geometry(*components, water_chart())


def test_geometrically_impossible_triangle_rejected_even_with_positive_distance_targets():
    # Base sides 1,1,1 and MP2 increment (0,0,1) extrapolate a third side > 2.
    def triangle(third):
        return water(1., 1., math.degrees(2 * math.asin(third / 2)))
    coordinates = chart([("distance", [0, 1]), ("distance", [0, 2]), ("distance", [1, 2])])
    with pytest.raises(ValueError, match="singular|feasible"):
        combine_junchs_geometry(triangle(1), triangle(.5), triangle(1.5),
                                 triangle(1), triangle(1), coordinates)


def test_one_atom_has_no_composite_internal_change_and_diatomic_uses_one_distance():
    atom = Molecule(symbols=["He"], coordinates=[[2, 3, 4]])
    moved_atom = Molecule(symbols=["He"], coordinates=[[-6, 3, 7]])
    result = combine_junchs_geometry(atom, moved_atom, atom, atom, moved_atom, chart([]))
    assert result["molecule"] == atom.model_dump(mode="json")
    assert result["target_parameters"] == []
    assert result["residual"]["max_abs_native"] == 0
    molecules = [Molecule(symbols=["H", "H"], coordinates=[[0, 0, 0], [r, 0, 0]])
                 for r in [.74, .75, .76, .742, .741]]
    result = combine_junchs_geometry(*molecules, chart([("distance", [0, 1])]))
    xyz = np.array(result["molecule"]["coordinates"])
    assert np.linalg.norm(xyz[1] - xyz[0]) == pytest.approx(.74 + 64 / 37 * .01 + .001)


def test_cps67_uses_correlation_extrapolation_and_adds_reference_once():
    assert JUNCHS_CBS_COEFFICIENT == 64 / 37
    assert cps67(-75, -.2, -.22) == pytest.approx(-75.23)
    assert cps67(5, -.2, -.22) - cps67(0, -.2, -.22) == pytest.approx(5)
    assert cps67(-75, -.2, -.2) == pytest.approx(-75.2)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "-75"])
@pytest.mark.parametrize("position", [0, 1, 2])
def test_cps67_rejects_nonfinite_or_coerced_inputs(value, position):
    values = [-75, -.2, -.22]
    values[position] = value
    with pytest.raises(ValueError):
        cps67(*values)


def test_weighted_energy_is_stable_and_requires_exact_matching_keys():
    energies = {"base": -100, "large": -100.2, "small": -100.1}
    weights = {"base": 1, "large": 1, "small": -1}
    keys = dict.fromkeys(energies, "same-composition-state-geometry-hartree")
    assert weighted_energy_sum(energies, weights, compatibility_keys=keys) == pytest.approx(-100.1)
    assert weighted_energy_sum({"a": 1e16, "b": 1, "c": -1e16}, dict.fromkeys("abc", 1),
                               compatibility_keys=dict.fromkeys("abc", "compatible")) == 1
    for changes in [{"base": 1}, {**weights, "extra": 0}]:
        with pytest.raises(ValueError, match="match exactly"):
            weighted_energy_sum(energies, changes, compatibility_keys=keys)
    with pytest.raises(ValueError, match="match exactly"):
        weighted_energy_sum(energies, weights, compatibility_keys={"base": "compatible"})
    with pytest.raises(ValueError, match="incompatible"):
        weighted_energy_sum(energies, weights, compatibility_keys={**keys, "small": "different-geometry"})


@pytest.mark.parametrize("energies,weights,keys", [
    ({}, {}, {}), ({"": 1}, {"": 1}, {"": "same"}),
    ({"a": 1}, {"a": 1}, {"a": ""}), ({"a": 1}, {"a": True}, {"a": "same"}),
    ({"a": "1"}, {"a": 1}, {"a": "same"}),
    ({"a": float("nan")}, {"a": 1}, {"a": "same"}),
    ({"a": 1}, {"a": float("inf")}, {"a": "same"}),
    ({"a": 1e308}, {"a": 10}, {"a": "same"}),
])
def test_weighted_energy_refuses_missing_identity_nonfinite_and_overflow(energies, weights, keys):
    with pytest.raises(ValueError):
        weighted_energy_sum(energies, weights, compatibility_keys=keys)


def test_cps67_overflow_cannot_return_an_energy():
    with pytest.raises(ValueError, match="nonfinite|finite"):
        cps67(1e308, -1e308, 1e308)
