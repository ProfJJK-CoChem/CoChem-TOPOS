#!/usr/bin/env python3
"""
CoChem-TOPOS: Stage 2.3 Escape Room Test Suite
Validates:
- Dynamic minimum sample size and Good-Turing coverage calculations.
- Consecutive batch convergence tracking for conformer discovery.
- Chiral Parity Locks with CIP stereocenter perception and 3D tetrahedral volume fallback.
- Explicit SHAKE constraints for rigid solvent degrees of freedom.
- Deterministic Langevin thermal shock execution, calculator validation, explosion traps, and parity checks.
- Honest engine routing and anti-spoofing verification for photochemical MECP searches.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import numpy as np
import pytest
from ase import Atoms
from ase.calculators.lj import LennardJones
from ase.constraints import FixBondLengths
from rdkit import Chem
from rdkit.Chem import AllChem

from core_engine.cochem_topos_escape import (
    EscapeRoom,
    GoodTuringEstimator,
    ParityLock,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# GoodTuringEstimator Tests
# ==============================================================================

def test_good_turing_estimator_dynamic_min_sample_size() -> None:
    """
    Verify exact dynamic minimum sample size N_min calculations across varying
    rotatable bond counts: N_min = clamp(15 * 2^min(max(n_rot, 0), 4), 15, 150).
    """
    # 0 rotatable bonds: 15 * 2^0 = 15
    estimator_0 = GoodTuringEstimator(n_rotatable_bonds=0)
    assert estimator_0.get_dynamic_min_sample_size() == 15

    # 1 rotatable bond: 15 * 2^1 = 30
    estimator_1 = GoodTuringEstimator(n_rotatable_bonds=1)
    assert estimator_1.get_dynamic_min_sample_size() == 30

    # 2 rotatable bonds: 15 * 2^2 = 60
    estimator_2 = GoodTuringEstimator(n_rotatable_bonds=2)
    assert estimator_2.get_dynamic_min_sample_size() == 60

    # 3 rotatable bonds: 15 * 2^3 = 120
    estimator_3 = GoodTuringEstimator(n_rotatable_bonds=3)
    assert estimator_3.get_dynamic_min_sample_size() == 120

    # 4 rotatable bonds: 15 * 2^4 = 240 -> clamped to upper bound 150
    estimator_4 = GoodTuringEstimator(n_rotatable_bonds=4)
    assert estimator_4.get_dynamic_min_sample_size() == 150

    # 5 rotatable bonds: min(5, 4)=4 -> 240 -> clamped to upper bound 150
    estimator_5 = GoodTuringEstimator(n_rotatable_bonds=5)
    assert estimator_5.get_dynamic_min_sample_size() == 150

    # Large rotatable bonds: clamped to upper bound 150
    estimator_10 = GoodTuringEstimator(n_rotatable_bonds=10)
    assert estimator_10.get_dynamic_min_sample_size() == 150

    # Negative rotatable bonds edge case: clamped to lower bound 15
    estimator_neg = GoodTuringEstimator(n_rotatable_bonds=-2)
    assert estimator_neg.get_dynamic_min_sample_size() == 15


def test_good_turing_estimator_calculate_coverage() -> None:
    """
    Verify Good-Turing coverage formula C = 1 - (N_1 / N) with sample size gating.
    Below N_min, coverage returns 0.0. Above N_min, coverage accurately reflects singleton ratio.
    """
    estimator = GoodTuringEstimator(target_coverage=0.95, n_rotatable_bonds=1)
    min_size = estimator.get_dynamic_min_sample_size()
    assert min_size == 30

    # Gating: total sample count below N_min must return 0.0 coverage
    estimator.update(["basin_alpha", "basin_beta"])
    assert sum(estimator.basin_counts.values()) == 2
    assert estimator.calculate_coverage() == 0.0

    # Populate to exactly N_min (30) with all distinct singletons (N_1 = 30)
    distinct_basins = [f"basin_singleton_{i}" for i in range(28)]
    estimator.update(distinct_basins)
    assert sum(estimator.basin_counts.values()) == 30
    # C = 1 - (30 / 30) = 0.0
    assert estimator.calculate_coverage() == 0.0

    # Populate another estimator with high redundancy (N=30, N_1=0)
    estimator_redundant = GoodTuringEstimator(target_coverage=0.95, n_rotatable_bonds=1)
    estimator_redundant.update(["basin_A"] * 15 + ["basin_B"] * 15)
    # C = 1 - (0 / 30) = 1.0
    assert estimator_redundant.calculate_coverage() == 1.0

    # Populate with known mixed distribution: N=40, N_1=8, N_2+=32
    estimator_mixed = GoodTuringEstimator(target_coverage=0.95, n_rotatable_bonds=1)
    singletons = [f"s_{i}" for i in range(8)]
    duplicates = ["d_1"] * 16 + ["d_2"] * 16
    estimator_mixed.update(singletons + duplicates)
    assert sum(estimator_mixed.basin_counts.values()) == 40
    # C = 1 - (8 / 40) = 0.80
    assert estimator_mixed.calculate_coverage() == pytest.approx(0.80, abs=1e-5)


def test_good_turing_estimator_is_converged_batch_tracking() -> None:
    """
    Verify consecutive converged batch tracking for halt criterion.
    Requires 3 consecutive batches with coverage >= target_coverage to halt.
    Resets consecutive counter to 0 if coverage drops below threshold.
    """
    estimator = GoodTuringEstimator(target_coverage=0.90, n_rotatable_bonds=0)
    assert estimator.get_dynamic_min_sample_size() == 15
    assert estimator.is_converged() is False

    # Batch 1: High redundancy (C = 1.0 >= 0.90) -> consecutive count = 1
    estimator.update(["basin_A"] * 15)
    assert estimator.calculate_coverage() == 1.0
    assert estimator.consecutive_converged_batches == 1
    assert estimator.is_converged() is False

    # Batch 2: Still above threshold -> consecutive count = 2
    estimator.update(["basin_A"] * 5)
    assert estimator.calculate_coverage() == 1.0
    assert estimator.consecutive_converged_batches == 2
    assert estimator.is_converged() is False

    # Batch 3: Still above threshold -> consecutive count = 3 -> CONVERGED
    estimator.update(["basin_A"] * 5)
    assert estimator.calculate_coverage() == 1.0
    assert estimator.consecutive_converged_batches == 3
    assert estimator.is_converged() is True

    # Drop below threshold: inject singletons to drop coverage
    # Current N=25 (all basin_A). Add 10 singletons -> N=35, N_1=10 -> C = 1 - (10/35) = ~0.714 < 0.90
    estimator.update([f"singleton_{i}" for i in range(10)])
    cov = estimator.calculate_coverage()
    assert cov < 0.90
    assert estimator.consecutive_converged_batches == 0
    assert estimator.is_converged() is False


# ==============================================================================
# ParityLock Tests
# ==============================================================================

def test_parity_lock_chiral_enantiomer_inversion_detection() -> None:
    """
    Verify ParityLock on chiral molecules with true stereocenters:
    - Identity and rigid rotation must return True (invariance preserved).
    - Inversion (enantiomer flip) must return False (blocked).
    """
    # 1. Test with tetrahedral bromochlorofluoromethane (CHFClBr)
    pos_r = [
        [0.0, 0.0, 0.0],       # C (index 0)
        [0.0, 0.0, 1.09],      # H (index 1)
        [1.03, 0.0, -0.36],    # F (index 2)
        [-0.51, 0.89, -0.36],  # Cl (index 3)
        [-0.51, -0.89, -0.36], # Br (index 4)
    ]
    mol_r = Atoms(["C", "H", "F", "Cl", "Br"], positions=pos_r)

    # Inverted enantiomer: swap Cl and Br positions (parity flip)
    pos_s = [
        [0.0, 0.0, 0.0],       # C
        [0.0, 0.0, 1.09],      # H
        [1.03, 0.0, -0.36],    # F
        [-0.51, -0.89, -0.36], # Br at old Cl position
        [-0.51, 0.89, -0.36],  # Cl at old Br position
    ]
    mol_s = Atoms(["C", "H", "F", "Cl", "Br"], positions=pos_s)

    # Identity check
    assert ParityLock.verify_invariance(mol_r, mol_r) is True

    # Inversion detection check
    assert ParityLock.verify_invariance(mol_r, mol_s) is False

    # Rigid rotation check (90 deg rotation around z-axis preserves chirality)
    mol_r_rotated = mol_r.copy()
    mol_r_rotated.rotate(90, "z")
    assert ParityLock.verify_invariance(mol_r, mol_r_rotated) is True

    # 2. Test with (R)-alanine and (S)-alanine stereocenters
    mol_rdkit_r = Chem.MolFromSmiles("C[C@@H](N)C(=O)O")
    mol_rdkit_r = Chem.AddHs(mol_rdkit_r)
    AllChem.EmbedMolecule(mol_rdkit_r, randomSeed=42)
    conf_r = mol_rdkit_r.GetConformer()
    atoms_ala_r = Atoms(
        [a.GetSymbol() for a in mol_rdkit_r.GetAtoms()],
        positions=conf_r.GetPositions(),
    )

    mol_rdkit_s = Chem.MolFromSmiles("C[C@H](N)C(=O)O")
    mol_rdkit_s = Chem.AddHs(mol_rdkit_s)
    AllChem.EmbedMolecule(mol_rdkit_s, randomSeed=42)
    conf_s = mol_rdkit_s.GetConformer()
    atoms_ala_s = Atoms(
        [a.GetSymbol() for a in mol_rdkit_s.GetAtoms()],
        positions=conf_s.GetPositions(),
    )

    # Verify R-enantiomer self-invariance
    assert ParityLock.verify_invariance(atoms_ala_r, atoms_ala_r) is True
    # Verify R -> S inversion detection
    assert ParityLock.verify_invariance(atoms_ala_r, atoms_ala_s) is False


def test_parity_lock_3d_tetrahedral_volume_fallback() -> None:
    """
    Verify signed 3D tetrahedral scalar triple product volume fallback (v1 . (v2 x v3)).
    (R)-configuration yields R_vol and (S)-configuration yields S_vol.
    """
    # (R)-configuration tetrahedral geometry
    pos_r = [
        [0.0, 0.0, 0.0],       # C (index 0)
        [0.0, 0.0, 1.09],      # H
        [1.03, 0.0, -0.36],    # F
        [-0.51, 0.89, -0.36],  # Cl
        [-0.51, -0.89, -0.36], # Br
    ]
    mol_r = Atoms(["C", "H", "F", "Cl", "Br"], positions=pos_r)

    # (S)-configuration tetrahedral geometry (swapped coordinates)
    pos_s = [
        [0.0, 0.0, 0.0],       # C
        [0.0, 0.0, 1.09],      # H
        [1.03, 0.0, -0.36],    # F
        [-0.51, -0.89, -0.36], # Br
        [-0.51, 0.89, -0.36],  # Cl
    ]
    mol_s = Atoms(["C", "H", "F", "Cl", "Br"], positions=pos_s)

    vol_r: Dict[int, str] = ParityLock._calculate_tetrahedral_volumes(mol_r)
    vol_s: Dict[int, str] = ParityLock._calculate_tetrahedral_volumes(mol_s)

    assert 0 in vol_r
    assert 0 in vol_s
    assert vol_r[0] != vol_s[0]
    assert {vol_r[0], vol_s[0]} == {"R_vol", "S_vol"}


# ==============================================================================
# EscapeRoom Tests
# ==============================================================================

def test_escape_room_shake_constraints() -> None:
    """
    Verify SHAKE constraints identification for rigid solvent geometries (O-H bonds < 1.1 A).
    Returns FixBondLengths constraint for solvent water and empty list for non-solvent.
    """
    room = EscapeRoom()

    # Water molecule (1 Oxygen, 2 Hydrogens)
    water = Atoms(
        ["O", "H", "H"],
        positions=[[0.0, 0.0, 0.0], [0.0, 0.76, 0.59], [0.0, -0.76, 0.59]],
    )
    constraints = room._apply_shake_constraints(water)
    assert len(constraints) == 1
    assert isinstance(constraints[0], FixBondLengths)
    # 2 explicit O-H bonds constrained
    assert len(constraints[0].pairs) == 2

    # Non-solvent molecule without O-H bonds (methane CH4)
    methane = Atoms(
        "CH4",
        positions=[
            [0.0, 0.0, 0.0],
            [0.63, 0.63, 0.63],
            [-0.63, -0.63, 0.63],
            [-0.63, 0.63, -0.63],
            [0.63, -0.63, -0.63],
        ],
    )
    no_constraints = room._apply_shake_constraints(methane)
    assert len(no_constraints) == 0


def test_escape_room_execute_thermal_shock_success() -> None:
    """
    Verify deterministic Langevin thermal shock trajectory execution with attached calculator.
    Verifies that Langevin MD steps proceed, updates atomic coordinates, and returns valid Atoms.
    """
    room = EscapeRoom(temperature_k=300.0, seed=42)
    atoms = Atoms(
        ["O", "H", "H"],
        positions=[[0.0, 0.0, 0.0], [0.0, 0.76, 0.59], [0.0, -0.76, 0.59]],
    )
    atoms.calc = LennardJones(sigma=1.0, epsilon=0.1)

    initial_pos = atoms.positions.copy()
    result = room.execute_thermal_shock(atoms, steps=20, dt_fs=1.0)

    assert result is not None
    assert isinstance(result, Atoms)
    assert len(result) == 3
    # Coordinates must have evolved under Langevin thermal shock
    assert not np.allclose(initial_pos, result.positions, atol=1e-4)


def test_escape_room_thermal_shock_missing_calculator_error() -> None:
    """
    Verify execute_thermal_shock raises ValueError when seed atoms lack an attached calculator.
    """
    room = EscapeRoom()
    atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
    atoms.calc = None

    with pytest.raises(ValueError, match="No calculator attached. Cannot run thermal shock."):
        room.execute_thermal_shock(atoms)


def test_escape_room_thermal_shock_explosion_trap() -> None:
    """
    Verify exploded geometry trap: when atoms violate minimum distance threshold (< 0.4 A),
    the trap aborts the trajectory early and safely returns None.
    """
    room = EscapeRoom(temperature_k=300.0, seed=42)
    # Place two atoms dangerously close (0.2 A < 0.4 A threshold)
    exploded_atoms = Atoms(["O", "H"], positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.2]])
    exploded_atoms.calc = LennardJones()

    result = room.execute_thermal_shock(exploded_atoms, steps=10, dt_fs=1.0)
    assert result is None


def test_escape_room_thermal_shock_parity_lock_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify that if a thermal shock trajectory violates chiral parity invariance,
    ParityLock blocks acceptance and execute_thermal_shock returns None.
    """
    room = EscapeRoom(temperature_k=300.0, seed=42)
    atoms = Atoms(
        ["O", "H", "H"],
        positions=[[0.0, 0.0, 0.0], [0.0, 0.76, 0.59], [0.0, -0.76, 0.59]],
    )
    atoms.calc = LennardJones(sigma=1.0, epsilon=0.1)

    monkeypatch.setattr(ParityLock, "verify_invariance", lambda orig, mod: False)
    result = room.execute_thermal_shock(atoms, steps=20, dt_fs=1.0)
    assert result is None


def test_escape_room_photochemical_shock_honest_engine_routing_and_fallback() -> None:
    """
    Verify TD-DFT MECP photochemical shock engine routing and anti-spoofing behavior:
    1. Primary routing attempts PySCF/GPU4PySCF.
    2. Fallback routes to ORCA subprocess.
    3. When neither engine is available in PATH, strictly raises RuntimeError declaring honest failure.
    """
    room = EscapeRoom()
    atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])

    # Without an active ORCA / PySCF binary in testing environment, must honestly raise RuntimeError
    with pytest.raises(RuntimeError, match="Honest MECP optimization failed"):
        room.execute_photochemical_shock(atoms, excited_state=1)


def test_escape_room_photochemical_shock_orca_input_formatting() -> None:
    """
    Verify ORCA TD-DFT MECP input syntax formatting generated by EscapeRoom.format_orca_mecp_input
    adheres to computational chemistry specifications.
    """
    room = EscapeRoom()
    atoms = Atoms(["H", "H"], positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
    excited_state = 2
    orca_input = room.format_orca_mecp_input(atoms, excited_state=excited_state)

    assert "! B3LYP def2-SVP" in orca_input
    assert "iroot 2" in orca_input
    assert "nroots 3" in orca_input
    assert "mecp true" in orca_input
    assert "H 0.00000 0.00000 0.00000" in orca_input
    assert "H 0.00000 0.00000 0.74000" in orca_input


def test_escape_room_photochemical_shock_orca_subprocess_execution() -> None:
    """
    Verify execute_photochemical_shock writes formatted input to disk, invokes ORCA subprocess,
    and parses the resulting mecp.xyz geometry.
    """
    from ase.io import write as ase_write

    room = EscapeRoom()
    atoms = Atoms(["H", "H"], positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])

    captured_inputs: list[str] = []

    def fake_subprocess_run(cmd: list[str], stdout: Any, cwd: str, check: bool) -> mock.MagicMock:
        inp_file = Path(cwd) / "mecp.inp"
        assert inp_file.exists()
        captured_inputs.append(inp_file.read_text(encoding="utf-8"))

        # Produce mock output mecp.xyz geometry
        mecp_atoms = Atoms(["H", "H"], positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.85]])
        ase_write(os.path.join(cwd, "mecp.xyz"), mecp_atoms)
        return mock.MagicMock(returncode=0)

    with (
        mock.patch("shutil.which", return_value="/mock/bin/orca"),
        mock.patch("subprocess.run", side_effect=fake_subprocess_run) as mock_run,
    ):
        result = room.execute_photochemical_shock(atoms, excited_state=2)
        mock_run.assert_called_once()
        assert len(captured_inputs) == 1
        assert "! B3LYP def2-SVP" in captured_inputs[0]
        assert "iroot 2" in captured_inputs[0]
        assert "mecp true" in captured_inputs[0]
        assert result is not None
        assert isinstance(result, Atoms)
        assert len(result) == 2
        assert np.isclose(result.positions[1, 2], 0.85)

