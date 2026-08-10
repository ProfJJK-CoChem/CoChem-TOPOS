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

def test_topos01_inhess_xtb2_preconditioner():
    """Verify TOPOS-01: Prohibited Calc_Hess = True removed and replaced with InHess XTB2 preconditioner."""
    atoms = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])
    crusher = ToposCrusher()
    worker_out = crusher._goat_single_worker(atoms, kick_magnitude=0.2)
    assert worker_out.info.get("InHess") == "XTB2"
    assert "Calc_Hess" not in worker_out.info or worker_out.info["Calc_Hess"] is not True

def test_topos02_two_stage_deduplication_protocol():
    """Verify TOPOS-02: Two-Stage Deduplication Protocol with CREST cross-check and CREGEN referee deduplication."""
    crusher = ToposCrusher(bthr=0.001)
    atoms1 = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])
    res1 = crusher.process_conformer(atoms1, energy_kcal=-10.0)
    assert res1["status"] == "accepted"

    # Secondary CREST crosscheck execution test
    crest_ensemble = crusher._execute_crest_secondary_crosscheck(atoms1, num_conformers=3)
    assert len(crest_ensemble) > 0

    # Near identical conformer should trigger CREGEN referee deduplication (bthr < 0.001)
    atoms2 = atoms1.copy()
    atoms2.positions += 1e-5
    res2 = crusher.process_conformer(atoms2, energy_kcal=-10.0, bthr=0.001)
    assert res2["status"] == "duplicate"
    assert "merged_with" in res2

