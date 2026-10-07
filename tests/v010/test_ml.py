"""Scientific invariants for explicit molecular ML inference and rigid grids."""
import copy

import numpy as np
import pytest

from topos.ml import BOHR_ANGSTROM, HARTREE_EV, ModelManifest, reduce_committee
from topos.ml_workflow import RigidMLGrid
from topos.models import Molecule


def manifest_data():
    return {"backend": "mace", "family": "explicit-test-model", "members": [
        {"path": "/models/first.model", "sha256": "a" * 64, "training_run_id": "first", "source": "fixture"},
        {"path": "/models/second.model", "sha256": "b" * 64, "training_run_id": "second", "source": "fixture"}],
        "package_version": "0.3.16", "training_method": "explicit-DFT-reference", "license_name": "fixture",
        "license_url": "fixture", "supported_elements": ["H", "O"], "supported_charges": [0],
        "supported_multiplicities": [1], "precision": "float64", "domain_reference": "fixture"}


def test_force_to_gradient_sign_and_length_unit():
    result = reduce_committee([HARTREE_EV], [[[1.0, -2.0, 0.0]]], 1)
    assert result["energy_hartree"] == 1.0
    assert result["gradient_hartree_per_bohr"][0] == pytest.approx([-BOHR_ANGSTROM/HARTREE_EV, 2*BOHR_ANGSTROM/HARTREE_EV, 0])
    assert result["committee"] is None


def test_committee_sample_spread_is_not_zero_or_standard_error():
    result = reduce_committee([0, 2*HARTREE_EV], [[[1, 0, 0]], [[-1, 0, 0]]], 1)
    assert result["committee"]["energy_std_hartree"] == pytest.approx(np.sqrt(2))
    assert result["committee"]["max_force_deviation_ev_per_angstrom"] == 1
    assert result["gradient_hartree_per_bohr"] == [[0, 0, 0]]


@pytest.mark.parametrize("energies,forces,natoms", [([np.nan], [[[0,0,0]]], 1), ([0], [], 1),
    ([0,1], [[[0,0,0]]], 1), ([0], [[[np.inf,0,0]]], 1), ([0], [[[0,0,0]]], 2)])
def test_incomplete_or_nonfinite_prediction_refused(energies, forces, natoms):
    with pytest.raises(ValueError):
        reduce_committee(energies, forces, natoms)


@pytest.mark.parametrize("field", ["sha256", "training_run_id"])
def test_repeated_committee_member_refused(field):
    data = manifest_data()
    data["members"][1][field] = data["members"][0][field]
    with pytest.raises(ValueError, match="Committee"):
        ModelManifest.model_validate(data)


def test_mace_cannot_ignore_charge_or_spin():
    data = manifest_data()
    data["supported_charges"] = [0, 1]
    with pytest.raises(ValueError, match="neutral closed-shell"):
        ModelManifest.model_validate(data)


def test_domain_rejects_collision_and_embedding():
    model = ModelManifest.model_validate(manifest_data())
    molecule = Molecule(symbols=["H", "H"], coordinates=[[0, 0, 0], [0.2, 0, 0]])
    with pytest.raises(ValueError, match="minimum-distance"):
        model.validate_molecule(molecule)
    data = molecule.model_dump(mode="json")
    data["coordinates"][1][0] = 1.0
    data["environment"] = {"solvent": "water"}
    with pytest.raises(ValueError, match="solvent"):
        model.validate_molecule(Molecule.model_validate(data))


def test_rigid_grid_preserves_every_internal_distance_and_fixed_fragment():
    mol = Molecule(symbols=["O","H","H","O","H","H"],
        coordinates=[[0,0,0],[0.96,0,0],[-0.24,0.93,0],[4,0,0],[4.96,0,0],[3.76,0.93,0]],
        fragments=[[0,1,2],[3,4,5]], fragment_states=[
            {"atom_indices":[0,1,2],"charge":0,"multiplicity":1},
            {"atom_indices":[3,4,5],"charge":0,"multiplicity":1}])
    original = copy.deepcopy(mol.model_dump())
    grid = RigidMLGrid(moving_fragment=1, translation_x_angstrom=[-0.1,0,0.1], rotation_x_degree=[0,90],
                       rotation_y_degree=[0,60], isolated_fragment_geometry_sources=["sourceA", "sourceB"])
    frames, points = grid.frames(mol)
    assert len(frames) == len(points) == 12
    reference = np.asarray(mol.coordinates)[3:]
    distances = np.linalg.norm(reference[:,None]-reference[None,:], axis=2)
    for frame in frames:
        assert frame.coordinates[:3] == mol.coordinates[:3]
        xyz = np.asarray(frame.coordinates)[3:]
        np.testing.assert_allclose(np.linalg.norm(xyz[:,None]-xyz[None,:],axis=2), distances, atol=1e-14)
    assert mol.model_dump() == original


def test_grid_rejects_repeated_and_excessive_points():
    with pytest.raises(ValueError, match="repeat"):
        RigidMLGrid(moving_fragment=0, translation_x_angstrom=[0,0], isolated_fragment_geometry_sources=["a","b"])
    with pytest.raises(ValueError, match="10000"):
        RigidMLGrid(moving_fragment=0, translation_x_angstrom=list(range(101)), translation_y_angstrom=list(range(101)),
                    isolated_fragment_geometry_sources=["a","b"])
