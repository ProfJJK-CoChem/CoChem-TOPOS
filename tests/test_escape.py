import pytest
from ase import Atoms
from core_engine.cochem_topos_escape import GoodTuringEstimator, ParityLock, EscapeRoom

def test_good_turing_estimator_dynamic_min_sample_size():
    estimator = GoodTuringEstimator(n_rotatable_bonds=2)
    min_size = estimator.get_dynamic_min_sample_size()
    assert min_size >= 15
    
    # Below min_size, calculate_coverage should return 0.0
    estimator.update(["basin_1", "basin_2"])
    coverage = estimator.calculate_coverage()
    assert coverage == 0.0

def test_parity_lock_3d_volume_fallback():
    # Tetrahedral carbon center
    atoms = Atoms('CH4', positions=[
        [0.0, 0.0, 0.0],
        [0.63, 0.63, 0.63],
        [-0.63, -0.63, 0.63],
        [-0.63, 0.63, -0.63],
        [0.63, -0.63, -0.63]
    ])
    inv = ParityLock.verify_invariance(atoms, atoms)
    assert inv is True

def test_escape_room_photochemical_shock():
    atoms = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)])
    room = EscapeRoom()
    res = room.execute_photochemical_shock(atoms, excited_state=1)
    assert res is not None
    assert len(res) == 2
