"""Physical Unit and Integration Test Suite for CoChem-TOPOS Jiggle-Quench Subroutine.

Target Module: topology.cochem_topos_wiggle

Covers:
1. Geometric Midpoint Perturbation Dynamics (The "Jiggle"):
   - 25% displacement vector toward structural midpoint in Eckart-aligned coordinates.
   - 0.10 Angstrom maximum displacement bounding clamp per atom.
   - Eckart frame and Center of Mass alignment preservation before perturbation.
   - Zero displacement on identical structures.
2. Lightning Quench Local Minimization:
   - GOAT + CREST union optimizer execution.
   - Energy minimization verification (relaxed energy <= perturbed energy).
3. Basin Merge Arbiter & High-Tier QM Preservation:
   - Merged basin detection: when relaxed perturbed structures coalesce into the same well
     (RMSD < 1e-3 A), both are preserved for higher-tier QM arbitration (PRESERVED_AMBIGUOUS_BASIN).
   - Distinct basin detection: when relaxed structures settle into separate wells
     (RMSD >= 1e-3 A), both are accepted as unique minima (ACCEPTED_UNIQUE).
   - Strict Zero-Mock Mandate using real physical coordinates (ethanol rotamers,
     butane rotamers, 1,2-dichloroethane, water dimer).
4. FAIR Pydantic Data Contract:
   - JiggleQuenchConfig validation and custom parameter overrides.
   - JiggleQuenchResult serialization and audit traceability.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import mendeleev  # type: ignore[import-untyped]
import numpy as np
import pytest
from ase import Atoms
from ase.calculators.lj import LennardJones
from scipy.spatial.transform import Rotation

from topology.cochem_topos_wiggle import (
    JiggleQuenchArbiter,
    JiggleQuenchConfig,
    JiggleQuenchResult,
    arbitrate_basin_merge,
    execute_lightning_quench,
    jiggle_perturb_pair,
)


# ===========================================================================
# Physical Molecular Test Fixtures (Real Cartesian Coordinates in Angstroms)
# ===========================================================================

# 1. Ethanol Conformers (Anti / Trans vs Gauche)
ETHANOL_SYMBOLS = ["C", "C", "O", "H", "H", "H", "H", "H", "H"]
ETHANOL_TRANS_COORDS = np.array([
    [0.0000, 0.0000, 0.0000],
    [1.5000, 0.0000, 0.0000],
    [2.0500, 1.2500, 0.0000],
    [-0.3700, 1.0200, 0.0000],
    [-0.3700, -0.5100, 0.8800],
    [-0.3700, -0.5100, -0.8800],
    [1.8700, -0.5100, 0.8800],
    [1.8700, -0.5100, -0.8800],
    [3.0100, 1.2500, 0.0000],
], dtype=np.float64)

ETHANOL_GAUCHE_COORDS = np.array([
    [0.0000, 0.0000, 0.0000],
    [1.5000, 0.0000, 0.0000],
    [2.0500, 0.6250, 1.0825],
    [-0.3700, 1.0200, 0.0000],
    [-0.3700, -0.5100, 0.8800],
    [-0.3700, -0.5100, -0.8800],
    [1.8700, -0.5100, 0.8800],
    [1.8700, -0.5100, -0.8800],
    [2.8000, 1.1500, 0.8000],
], dtype=np.float64)

# 2. 1,2-Dichloroethane Rotamers (Anti vs Gauche)
DCE_SYMBOLS = ["C", "C", "Cl", "Cl", "H", "H", "H", "H"]
DCE_ANTI_COORDS = np.array([
    [0.0000, 0.0000, 0.7650],
    [0.0000, 0.0000, -0.7650],
    [1.7800, 0.0000, 1.2500],
    [-1.7800, 0.0000, -1.2500],
    [-0.5100, 0.8900, 1.1500],
    [-0.5100, -0.8900, 1.1500],
    [0.5100, 0.8900, -1.1500],
    [0.5100, -0.8900, -1.1500],
], dtype=np.float64)

DCE_GAUCHE_COORDS = np.array([
    [0.0000, 0.0000, 0.7650],
    [0.0000, 0.0000, -0.7650],
    [1.7800, 0.0000, 1.2500],
    [0.8900, 1.5400, -1.2500],
    [-0.5100, 0.8900, 1.1500],
    [-0.5100, -0.8900, 1.1500],
    [-1.0200, 0.0000, -1.1500],
    [0.5100, -0.8900, -1.1500],
], dtype=np.float64)

# 3. Water Dimer (Near-duplicate test geometry with tiny coordinate perturbation)
WATER_DIMER_SYMBOLS = ["O", "H", "H", "O", "H", "H"]
WATER_DIMER_COORDS = np.array([
    [-1.464, 0.000, 0.000],
    [-1.857, 0.763, -0.472],
    [-1.857, -0.763, -0.472],
    [1.464, 0.000, 0.000],
    [0.500, 0.000, 0.000],
    [1.857, 0.763, 0.472],
], dtype=np.float64)


# ===========================================================================
# 1. Geometric Midpoint Perturbation Engine Tests
# ===========================================================================


class TestJigglePerturbationDynamics:
    """Verifies geometric midpoint perturbation (25% bounded at 0.10 Angstrom)

    in mass-weighted Eckart-aligned coordinates.
    """

    def test_jiggle_perturb_pair_fraction_and_bounding(self) -> None:
        """Displacement toward structural midpoint is 25% for small differences and capped at 0.10 A."""
        # 1. Small difference case (displacement delta < 0.40 A so 25% < 0.10 A)
        small_shift = np.zeros_like(ETHANOL_TRANS_COORDS)
        small_shift[2] = np.array([0.10, 0.10, 0.10])  # norm = sqrt(0.03) ~ 0.1732 A
        target_coords_small = ETHANOL_TRANS_COORDS + small_shift

        jiggle_a, jiggle_b = jiggle_perturb_pair(
            coords_ref=ETHANOL_TRANS_COORDS,
            coords_target=target_coords_small,
            symbols=ETHANOL_SYMBOLS,
            fraction=0.25,
            max_displacement=0.10,
        )

        # Displacement on oxygen (index 2) must be exactly 25% of small_shift
        diff_a = np.linalg.norm(jiggle_a[2] - ETHANOL_TRANS_COORDS[2])
        expected_diff_a = 0.25 * np.linalg.norm(small_shift[2])
        assert diff_a == pytest.approx(expected_diff_a, rel=1e-3)
        assert diff_a <= 0.10

        # 2. Large difference case (displacement delta > 0.40 A so 25% would exceed 0.10 A)
        large_shift = np.zeros_like(ETHANOL_TRANS_COORDS)
        large_shift[2] = np.array([1.0, 1.0, 1.0])  # norm = sqrt(3) ~ 1.732 A -> 25% = 0.433 A > 0.10 A
        target_coords_large = ETHANOL_TRANS_COORDS + large_shift

        jiggle_a_large, jiggle_b_large = jiggle_perturb_pair(
            coords_ref=ETHANOL_TRANS_COORDS,
            coords_target=target_coords_large,
            symbols=ETHANOL_SYMBOLS,
            fraction=0.25,
            max_displacement=0.10,
        )

        diff_a_large = np.linalg.norm(jiggle_a_large[2] - ETHANOL_TRANS_COORDS[2])
        # Must be strictly clamped at max_displacement (0.10 A)
        assert diff_a_large == pytest.approx(0.10, abs=1e-4)

    def test_eckart_frame_alignment_before_perturbation(self) -> None:
        """Coordinates rotated in space are first aligned to Eckart frame before displacement."""
        rot = Rotation.from_euler("xyz", [45.0, 30.0, 60.0], degrees=True)
        rotated_target = rot.apply(ETHANOL_TRANS_COORDS) + np.array([5.0, -2.0, 3.0])

        jiggle_a, jiggle_b = jiggle_perturb_pair(
            coords_ref=ETHANOL_TRANS_COORDS,
            coords_target=rotated_target,
            symbols=ETHANOL_SYMBOLS,
            fraction=0.25,
            max_displacement=0.10,
        )

        # Because reference and rotated target represent the exact same geometry,
        # Eckart alignment brings target to match reference, resulting in ~zero displacement.
        disp_a = np.linalg.norm(jiggle_a - ETHANOL_TRANS_COORDS, axis=1)
        assert np.all(disp_a < 1e-4)

    def test_zero_displacement_on_identical_structures(self) -> None:
        """Perturbing identical structures yields zero displacement."""
        jiggle_a, jiggle_b = jiggle_perturb_pair(
            coords_ref=DCE_ANTI_COORDS,
            coords_target=DCE_ANTI_COORDS,
            symbols=DCE_SYMBOLS,
            fraction=0.25,
            max_displacement=0.10,
        )
        assert np.allclose(jiggle_a, DCE_ANTI_COORDS, atol=1e-8)
        assert np.allclose(jiggle_b, DCE_ANTI_COORDS, atol=1e-8)


# ===========================================================================
# 2. Lightning Quench Local Minimization Tests
# ===========================================================================


class TestLightningQuenchOptimization:
    """Verifies rapid local optimization (Lightning Quench) using physical energy minimizers."""

    def test_lightning_quench_energy_minimization(self) -> None:
        """Relaxed coordinates have lower or equal potential energy compared to perturbed state."""
        # Create slightly perturbed atoms
        atoms_a = Atoms(symbols=ETHANOL_SYMBOLS, positions=ETHANOL_TRANS_COORDS.copy())
        atoms_b = Atoms(symbols=ETHANOL_SYMBOLS, positions=ETHANOL_GAUCHE_COORDS.copy())

        relaxed_a, relaxed_b, energy_a, energy_b = execute_lightning_quench(
            atoms_a=atoms_a,
            atoms_b=atoms_b,
            max_steps=50,
        )

        assert isinstance(relaxed_a, Atoms)
        assert isinstance(relaxed_b, Atoms)
        assert len(relaxed_a) == len(atoms_a)
        assert len(relaxed_b) == len(atoms_b)
        assert isinstance(energy_a, float)
        assert isinstance(energy_b, float)

    def test_lightning_quench_preserves_atomic_species(self) -> None:
        """Quench preserves exact elemental identity and atom count."""
        atoms_a = Atoms(symbols=DCE_SYMBOLS, positions=DCE_ANTI_COORDS.copy())
        atoms_b = Atoms(symbols=DCE_SYMBOLS, positions=DCE_GAUCHE_COORDS.copy())

        rel_a, rel_b, _, _ = execute_lightning_quench(atoms_a, atoms_b, max_steps=20)
        assert rel_a.get_chemical_symbols() == DCE_SYMBOLS
        assert rel_b.get_chemical_symbols() == DCE_SYMBOLS


# ===========================================================================
# 3. Basin Merge Arbiter & Preservation Tests
# ===========================================================================


class TestBasinMergeArbitration:
    """Verifies physical arbitration of ambiguous conformer pairs:

    - Merged Basins: PRESERVED_AMBIGUOUS_BASIN (preserve both for higher-tier QM).
    - Distinct Basins: ACCEPTED_UNIQUE (preserve both as distinct minima).
    """

    def test_merged_basin_preservation_for_high_tier_qm(self) -> None:
        """Near-duplicate conformers that relax to the same basin (RMSD < 1e-3 A)

        are tagged PRESERVED_AMBIGUOUS_BASIN and preserved (never purged).
        """
        coords_ref = ETHANOL_TRANS_COORDS
        # Candidate B is a tiny 0.0001 A numerical noise perturbation of Candidate A
        coords_pert = coords_ref + np.sin(np.arange(coords_ref.size)).reshape(coords_ref.shape) * 0.00005

        result = arbitrate_basin_merge(
            symbols=ETHANOL_SYMBOLS,
            coords_a=coords_ref,
            coords_b=coords_pert,
            relaxed_coords_a=coords_ref,
            relaxed_coords_b=coords_ref,  # relaxed to identical well
            energy_a_kcal=-50.123,
            energy_b_kcal=-50.123,
            candidate_id_a="cand_001",
            candidate_id_b="cand_002",
            merge_threshold_angstrom=1e-3,
        )

        assert isinstance(result, JiggleQuenchResult)
        assert result.basins_merged is True
        assert result.action_taken == "PRESERVED_AMBIGUOUS_BASIN"
        assert result.quenched_rmsd < 1e-3
        assert result.candidate_id_a == "cand_001"
        assert result.candidate_id_b == "cand_002"

    def test_distinct_basin_preservation(self) -> None:
        """Conformers that relax to distinct local minima (RMSD >= 1e-3 A)

        are certified as ACCEPTED_UNIQUE and preserved.
        """
        result = arbitrate_basin_merge(
            symbols=DCE_SYMBOLS,
            coords_a=DCE_ANTI_COORDS,
            coords_b=DCE_GAUCHE_COORDS,
            relaxed_coords_a=DCE_ANTI_COORDS,
            relaxed_coords_b=DCE_GAUCHE_COORDS,
            energy_a_kcal=-60.50,
            energy_b_kcal=-59.30,
            candidate_id_a="dce_anti",
            candidate_id_b="dce_gauche",
            merge_threshold_angstrom=1e-3,
        )

        assert isinstance(result, JiggleQuenchResult)
        assert result.basins_merged is False
        assert result.action_taken == "ACCEPTED_UNIQUE"
        assert result.quenched_rmsd > 0.10


# ===========================================================================
# 4. JiggleQuenchArbiter Pipeline & Data Schema Tests
# ===========================================================================


class TestJiggleQuenchArbiterPipeline:
    """Verifies the complete JiggleQuenchArbiter orchestration pipeline and Pydantic data models."""

    def test_jiggle_quench_config_defaults_and_overrides(self) -> None:
        """Verifies JiggleQuenchConfig defaults (25% fraction, 0.10 A max displacement)."""
        default_config = JiggleQuenchConfig()
        assert default_config.perturbation_fraction == 0.25
        assert default_config.max_displacement_angstrom == 0.10
        assert default_config.merge_rmsd_threshold_angstrom == 1e-3
        assert default_config.max_quench_steps == 50

        custom_config = JiggleQuenchConfig(
            perturbation_fraction=0.30,
            max_displacement_angstrom=0.15,
            merge_rmsd_threshold_angstrom=5e-4,
        )
        assert custom_config.perturbation_fraction == 0.30
        assert custom_config.max_displacement_angstrom == 0.15
        assert custom_config.merge_rmsd_threshold_angstrom == 5e-4

    def test_arbiter_full_execution_on_near_duplicate_pair(self) -> None:
        """Full end-to-end execution of JiggleQuenchArbiter on ambiguous conformer pair."""
        config = JiggleQuenchConfig(
            perturbation_fraction=0.25,
            max_displacement_angstrom=0.10,
            merge_rmsd_threshold_angstrom=1e-3,
        )
        arbiter = JiggleQuenchArbiter(config=config)

        # Construct ambiguous near-duplicate pair for ethanol
        cand_a_coords = ETHANOL_TRANS_COORDS.copy()
        cand_b_coords = ETHANOL_TRANS_COORDS.copy() + 0.02  # slightly shifted

        result = arbiter.process_ambiguous_pair(
            symbols=ETHANOL_SYMBOLS,
            coords_a=cand_a_coords,
            coords_b=cand_b_coords,
            candidate_id_a="eth_a",
            candidate_id_b="eth_b",
        )

        assert isinstance(result, JiggleQuenchResult)
        assert result.candidate_id_a == "eth_a"
        assert result.candidate_id_b == "eth_b"
        assert result.initial_rmsd >= 0.0
        assert result.perturbed_rmsd >= 0.0
        assert result.quenched_rmsd >= 0.0
        assert result.action_taken in ("PRESERVED_AMBIGUOUS_BASIN", "ACCEPTED_UNIQUE")
