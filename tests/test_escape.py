import logging
logger = logging.getLogger(__name__)
import pytest
from ase import Atoms
from core_engine.cochem_topos_escape import GoodTuringEstimator, ParityLock, EscapeRoom

def test_good_turing_estimator_dynamic_min_sample_size() -> None:
    estimator = GoodTuringEstimator(n_rotatable_bonds=2)
    min_size = estimator.get_dynamic_min_sample_size()
    assert min_size >= 15
    
    # Below min_size, calculate_coverage should return 0.0
    estimator.update(["basin_1", "basin_2"])
    coverage = estimator.calculate_coverage()
    assert coverage == 0.0

def test_parity_lock_3d_volume_fallback() -> None:
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

def test_escape_room_photochemical_shock() -> None:
    from unittest import mock
    import os
    atoms = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)])
    room = EscapeRoom()
    
    with mock.patch("shutil.which", return_value="/mock/orca"), \
         mock.patch("subprocess.run") as mock_run:
         
        def side_effect(*args, **kwargs):
            tmpdir = kwargs.get("cwd")
            # create dummy mecp.xyz
            with open(os.path.join(tmpdir, "mecp.xyz"), "w") as f:
                f.write("2\n\nH 0.0 0.0 0.0\nH 0.0 0.0 0.74\n")
            return mock.Mock(returncode=0)
            
        mock_run.side_effect = side_effect
        
        res = room.execute_photochemical_shock(atoms, excited_state=1)
        assert len(res) == 2
        mock_run.assert_called_once()
