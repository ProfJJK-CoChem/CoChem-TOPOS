import pytest
from ase import Atoms
import numpy as np
from core_engine.cochem_topos_crusher import ToposCrusher, ChiralDiscriminationError

def test_topos_crusher_distance_matrix_hash():
    atoms = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)])
    crusher = ToposCrusher()
    hash_val = crusher.distance_matrix_hash(atoms)
    assert isinstance(hash_val, np.ndarray)
    assert len(hash_val) == 50

def test_goat_conformer_generation():
    atoms = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])
    crusher = ToposCrusher()
    conformers = crusher._execute_goat_conformer_generation(atoms, num_conformers=3)
    assert len(conformers) == 3
    for conf in conformers:
        assert len(conf) == 3

def test_coulomb_matrix_error_handling():
    atoms1 = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)])
    atoms2 = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.80)])
    crusher = ToposCrusher()
    try:
        res = crusher._coulomb_matrix_rmsd(atoms1, atoms2)
        assert res >= 0
    except ChiralDiscriminationError:
        pass
