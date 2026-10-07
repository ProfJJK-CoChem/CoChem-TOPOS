"""Analytical geometries: molecular point groups and observable conventions."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from topos.models import Molecule
from topos.symmetry import point_group_analysis, principal_axis_dipole, rotational_observables


def water():
    return Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.758, 0, .504], [-.758, 0, .504]])


def methane():
    return Molecule(symbols=["C"] + ["H"] * 4,
                    coordinates=[[0, 0, 0], [1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]])


@pytest.mark.parametrize("molecule, expected, number", [
    (water(), "C2v", 2),
    (methane(), "Td", 12),
    (Molecule(symbols=["N"] + ["H"] * 3,
              coordinates=[[0, 0, .3], [1, 0, 0], [-.5, np.sqrt(3) / 2, 0], [-.5, -np.sqrt(3) / 2, 0]]), "C3v", 3),
    (Molecule(symbols=["C"] * 6 + ["H"] * 6,
              coordinates=[[r * np.cos(i * np.pi / 3), r * np.sin(i * np.pi / 3), 0]
                           for r in [1.4, 2.4] for i in range(6)]), "D6h", 12),
    (Molecule(symbols=["S"] + ["F"] * 6, coordinates=[[0, 0, 0], [1, 0, 0], [-1, 0, 0],
                                                              [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]), "Oh", 24),
    (Molecule(symbols=["O", "C", "O"], coordinates=[[-1.16, 0, 0], [0, 0, 0], [1.16, 0, 0]]), "Dinfh", 2),
    (Molecule(symbols=["H", "F"], coordinates=[[0, 0, 0], [.9, 0, 0]]), "Cinfv", 1),
    (Molecule(symbols=["He"], coordinates=[[5, 2, 8]]), "Kh", 1),
])
def test_known_point_groups_with_independent_operation_validation(molecule, expected, number):
    analysis = point_group_analysis(molecule)
    assert analysis["point_group"] == expected
    assert analysis["status"] == "stable"
    assert analysis["rotational_symmetry_number"] == number
    assert analysis["is_chiral_geometry"] is False
    assert analysis["algorithm_version"]
    assert analysis["algorithm_reference"].endswith("10.1002/jcc.23493")
    assert len(analysis["tolerance_sweep"]) == 3
    assert analysis["max_operation_residual_angstrom"] < 1e-8


def test_point_group_invariant_under_rigid_motion_and_order():
    molecule = methane()
    rotation = Rotation.from_rotvec([.8, .2, -.4]).as_matrix()
    indices = [4, 2, 0, 3, 1]
    transformed = Molecule(symbols=[molecule.symbols[i] for i in indices],
                           coordinates=(np.asarray(molecule.coordinates)[indices] @ rotation + [6, -3, 9]).tolist())
    assert point_group_analysis(transformed)["point_group"] == "Td"


def test_isotope_broken_water_is_cs_not_c2v():
    molecule = water()
    molecule.isotopes = [None, None, 2]
    analysis = point_group_analysis(molecule)
    assert analysis["point_group"] == "Cs"
    assert analysis["rotational_symmetry_number"] == 1
    assert analysis["isotope_provenance"]


def test_isotope_breaks_linear_inversion():
    molecule = Molecule(symbols=["H", "H"], isotopes=[1, 2], coordinates=[[-.4, 0, 0], [.4, 0, 0]])
    assert point_group_analysis(molecule)["point_group"] == "Cinfv"


def test_tolerance_sweep_flags_near_symmetry_without_changing_geometry():
    molecule = water()
    molecule.coordinates[1][2] += .001
    before = molecule.model_dump()
    analysis = point_group_analysis(molecule)
    assert analysis["status"] == "requires-review"
    assert analysis["uncertainty"] == "tolerance-sensitive-or-unresolved"
    assert analysis["is_chiral_geometry"] is None
    assert {row["point_group"] for row in analysis["tolerance_sweep"]} == {"Cs", "C2v"}
    assert molecule.model_dump() == before


def test_chiral_point_group_does_not_assign_thermodynamic_degeneracy():
    molecule = Molecule(symbols=["C", "H", "F", "Cl", "Br"],
                        coordinates=[[0, 0, 0], [1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]])
    analysis = point_group_analysis(molecule)
    assert analysis["point_group"] == "C1"
    assert analysis["is_chiral_geometry"] is True
    assert "degeneracy" not in analysis


@pytest.mark.parametrize("kwargs", [{"tolerance_angstrom": 0}, {"tolerance_angstrom": float("nan")},
                                    {"sweep_factors": (1,)}, {"sweep_factors": (-1, 1, 10)}])
def test_invalid_symmetry_tolerances(kwargs):
    with pytest.raises(ValueError):
        point_group_analysis(water(), **kwargs)


def test_signed_dipoles_rotate_with_recorded_frame_and_remain_signed():
    molecule = water()
    vector = np.array([-.2, .3, -1.5])
    rotation = Rotation.from_rotvec([.8, .2, -.4]).as_matrix()
    transformed = molecule.model_copy(deep=True)
    transformed.coordinates = (np.asarray(molecule.coordinates) @ rotation + [6, -3, 9]).tolist()
    first = principal_axis_dipole(molecule, vector.tolist(), dipole_method="analytical-vector")
    second = principal_axis_dipole(transformed, (vector @ rotation).tolist(), dipole_method="analytical-vector")
    assert first["status"] == "resolved"
    # The molecular plane's normal gauge is fixed by right handedness.
    assert second["signed_abc_debye"] == pytest.approx(first["signed_abc_debye"])
    assert any(x < 0 for x in first["signed_abc_debye"])
    assert np.linalg.det(first["axes_columns_in_cartesian"]) == pytest.approx(1)


def test_degenerate_spherical_top_dipole_components_are_not_invented():
    result = principal_axis_dipole(methane(), [1, 2, 3], dipole_method="analytical-vector")
    assert result["signed_abc_debye"] == [None, None, None]
    assert result["dark_branches"] == [None, None, None]
    assert result["status"] == "axis-ambiguity"
    assert result["total_dipole_debye"] == pytest.approx(np.sqrt(14))


def test_dark_line_list_filter_preserves_thermodynamic_member():
    result = principal_axis_dipole(water(), [0, 0, 0], dipole_method="analytical-zero-vector")
    assert result["dark_branches"] == [True, True, True]
    assert result["exclude_from_line_list"] is True
    assert result["retain_in_thermodynamic_ensemble"] is True


@pytest.mark.parametrize("vector", [None, [1, 2], [1, 2, float("nan")]])
def test_dipole_missing_is_not_zero(vector):
    with pytest.raises(ValueError):
        principal_axis_dipole(water(), vector, dipole_method="actual-method")


def test_unadjusted_equilibrium_constants_are_not_ground_state_constants():
    result = rotational_observables(water(), geometry_method="analytical-geometry")
    assert result["equilibrium_labels"] == ["Ae", "Be", "Ce"]
    assert result["ground_state_ghz"] is None
    assert result["equilibrium"]["not_measured_B0"] is True


def test_supplied_semi_rigid_alpha_applies_zero_point_half_sum():
    result = rotational_observables(water(), geometry_method="analytical-geometry",
                                   vibration_rotation_alpha_ghz=[[1, 2, 3]] * 3,
                                   correction_method="analytical-alpha", semi_rigid_unconstrained=True)
    assert np.asarray(result["equilibrium"]["constants_ghz"]) - result["ground_state_ghz"] == pytest.approx([1.5, 3, 4.5])
    assert result["experimental"] is False


@pytest.mark.parametrize("kwargs", [
    {"semi_rigid_unconstrained": False, "correction_method": "alpha"},
    {"semi_rigid_unconstrained": True, "correction_method": None},
])
def test_unsupported_alpha_correction_cannot_relabel_equilibrium(kwargs):
    with pytest.raises(ValueError):
        rotational_observables(water(), geometry_method="analytical", vibration_rotation_alpha_ghz=[[1, 2, 3]] * 3, **kwargs)


def test_spherical_inertia_does_not_turn_chiral_tetrahedral_group_into_td():
    # A generic orbit of the twelve proper tetrahedral rotations has T symmetry,
    # equal principal moments, and no mirror operations. MolSym 1.2 proposes Td;
    # the independent operation check corrects its missing T/Td distinction.
    xyz = Rotation.create_group("T").apply([1.0, .2, .3])
    result = point_group_analysis(Molecule(symbols=["He"] * len(xyz), coordinates=xyz.tolist()))
    assert result["point_group"] == "T"
    assert result["is_chiral_geometry"] is True
    assert result["rotational_symmetry_number"] == 12
    assert result["proposal_correction"]
    assert all(op["determinant"] == 1 for op in result["operations"])
