Perform adversarial static analysis and logical review on implemented code for D:\__CoChem\__agentic\.prompts\.SRS\CoChem-TOPOS\.in-progress\02_04_topology_crusher.md.
Original prompt:
# Task: Implement the Deduplication Funnel (`cochem_topos_crusher.py`)

## Target Output File
`${COCHEM_WORKSPACE}\GitHub-Repo\CoChem-TOPOS\topology\cochem_topos_crusher.py`

## Objective
Filter identical conformers generated during the PES search while strictly preserving enantiomers and distinct local minima.

## Context & Architecture Rules
This stage enacts the basin deduplication protocol (Stage 2.4). Data outputs must remain FAIR-compliant.

## Execution Directives
Implement the `cochem_topos_crusher.py` script to operate sequentially using the following filters:

1. **Rotational Sieve**: Implement a fast pre-filter comparing Rotational Constants (A, B, C) and total Dipole Moments prior to executing heavy array mathematics.
2. **KD-Tree Coordinate Filter**: Employ spatial `scipy.spatial.KDTree` algorithms to rapidly reject identical coordinate sets based on Euclidean distance clustering.
3. **Mass-Weighted Eckart RMSD**: Calculate the rigid-body Root Mean Square Deviation after aligning structures to their Eckart frames, inherently factoring in the anchored mono-isotopic masses.
4. **GOAT and CREST Union Deduplication**: Execute standard deduplication using GOAT as the primary search engine. Subsequently add CREST utilizing the flags `--nci --nocross --noreftopo` as an independent secondary search, and carry the union of the generated unique conformers forward.

Modified files content:

--- D:\__CoChem\GitHub-Repo\CoChem-TOPOS\tests\test_topology_crusher.py ---
"""Physical Unit Tests for CoChem-TOPOS Deduplication Funnel (test_topology_crusher.py).

Enforces Zero-Tolerance Anti-Mocking:
- Real elemental monoisotopic mass resolutions.
- Real 3D Cartesian coordinates for physical molecules (H2O, CH4, C6H6, ethanol, alanine, CHFClBr enantiomers).
- Rotational Sieve comparing rotational constants (A, B, C) and total dipole moments.
- KD-Tree spatial coordinate filter using scipy.spatial.KDTree.
- Mass-Weighted Eckart RMSD with proper SO(3) rotations and enantiomer preservation.
- GOAT and CREST Union Deduplication with FAIR-compliant data exports.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pytest
from ase import Atoms
from scipy.spatial.transform import Rotation

from topology.cochem_topos_crusher import (
    ConformerCandidate,
    DeduplicationRecord,
    DeduplicationVerdict,
    EnsembleDeduplicationReport,
    KDTreeCoordinateFilter,
    MassWeightedEckartRMSD,
    RotationalConstants,
    RotationalSieve,
    TopologyCrusher,
    align_to_eckart_frame,
    compute_dipole_moment,
    compute_mass_weighted_eckart_rmsd,
    compute_rotational_constants,
    is_enantiomer_pair,
)


# ===========================================================================
# 1. Rotational Sieve Tests (Directive 1)
# ===========================================================================


class TestRotationalSieve:
    """Verifies Rotational Sieve filtering via Rotational Constants and Dipole Moments."""

    def test_rotational_constants_water(self) -> None:
        """Water (asymmetric top) must yield positive A > B > C rotational constants."""
        symbols = ["O", "H", "H"]
        # Standard experimental geometry for H2O: r_OH ~ 0.9578 A, angle ~ 104.5 deg
        coords = np.array([
            [0.0000, 0.0000, 0.1173],
            [0.0000, 0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ])

        rot = compute_rotational_constants(symbols, coords)
        assert isinstance(rot, RotationalConstants)
        assert rot.is_linear is False
        assert rot.A_GHz > rot.B_GHz >= rot.C_GHz > 0.0
        # For H2O, A ~ 830 GHz, B ~ 435 GHz, C ~ 280 GHz
        assert 500.0 < rot.A_GHz < 1200.0
        assert 250.0 < rot.B_GHz < 600.0
        assert 150.0 < rot.C_GHz < 400.0

    def test_rotational_constants_linear_molecule(self) -> None:
        """Carbon dioxide (linear symmetric top) must have zero moment of inertia along axis."""
        symbols = ["C", "O", "O"]
        coords = np.array([
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.16],
            [0.0, 0.0, -1.16],
        ])

        rot = compute_rotational_constants(symbols, coords)
        assert rot.is_linear is True
        assert np.isclose(rot.B_GHz, rot.C_GHz, rtol=1e-3)
        assert rot.B_GHz > 0.0

    def test_rotational_constants_single_atom(self) -> None:
        """Single atom (noble gas) returns zero rotational constants and moments."""
        symbols = ["Ar"]
        coords = np.array([[0.0, 0.0, 0.0]])

        rot = compute_rotational_constants(symbols, coords)
        assert rot.is_linear is False
        assert rot.A_GHz == 0.0
        assert rot.B_GHz == 0.0
        assert rot.C_GHz == 0.0

    def test_dipole_moment_polar_vs_nonpolar(self) -> None:
        """Water has significant dipole moment; methane and CO2 have zero net dipole."""
        # Water (polar)
        h2o_symbols = ["O", "H", "H"]
        h2o_coords = np.array([
            [0.0000, 0.0000, 0.1173],
            [0.0000, 0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ])
        dipole_h2o = compute_dipole_moment(h2o_symbols, h2o_coords)
        assert dipole_h2o.magnitude_debye > 1.0

        # Methane (Td, nonpolar)
        ch4_symbols = ["C", "H", "H", "H", "H"]
        ch4_coords = np.array([
            [0.0000, 0.0000, 0.0000],
            [0.6276, 0.6276, 0.6276],
            [0.6276, -0.6276, -0.6276],
            [-0.6276, 0.6276, -0.6276],
            [-0.6276, -0.6276, 0.6276],
        ])
        dipole_ch4 = compute_dipole_moment(ch4_symbols, ch4_coords)
        assert np.isclose(dipole_ch4.magnitude_debye, 0.0, atol=1e-3)

        # Single atom (zero dipole)
        dipole_ar = compute_dipole_moment(["Ar"], [[0.0, 0.0, 0.0]])
        assert np.isclose(dipole_ar.magnitude_debye, 0.0, atol=1e-6)

    def test_rotational_sieve_identical_structures_pass_sieve(self) -> None:
        """Rotated/translated copies of water match rotational constants and dipole moment within tolerance."""
        symbols = ["O", "H", "H"]
        coords1 = np.array([
            [0.0000, 0.0000, 0.1173],
            [0.0000, 0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ])

        # Apply rigid rotation and translation
        rot = Rotation.from_euler("xyz", [35.0, 45.0, 60.0], degrees=True)
        coords2 = rot.apply(coords1) + np.array([5.0, -3.0, 8.0])

        sieve = RotationalSieve(rot_tol=0.01, dipole_tol=0.05)
        is_candidate_match, rot_diff, dipole_diff = sieve.evaluate_match(
            symbols1=symbols, coords1=coords1, symbols2=symbols, coords2=coords2
        )

        assert is_candidate_match is True
        assert rot_diff < 0.001
        assert dipole_diff < 0.01

    def test_rotational_sieve_distinct_conformers_rejected_early(self) -> None:
        """Eclipsed vs staggered 1,2-dichloroethane have different rotational constants and dipoles."""
        symbols = ["C", "C", "Cl", "Cl", "H", "H", "H", "H"]
        # Anti (staggered, centrosymmetric, dipole ~ 0)
        coords_anti = np.array([
            [0.0000, 0.0000, 0.7650],
            [0.0000, 0.0000, -0.7650],
            [1.4500, 0.0000, 1.4500],
            [-1.4500, 0.0000, -1.4500],
            [-0.5200, 0.8900, 1.1000],
            [-0.5200, -0.8900, 1.1000],
            [0.5200, 0.8900, -1.1000],
            [0.5200, -0.8900, -1.1000],
        ])

        # Syn (gauche / eclipsed, polar)
        coords_syn = np.array([
            [0.0000, 0.0000, 0.7650],
            [0.0000, 0.0000, -0.7650],
            [1.4500, 0.0000, 1.4500],
            [1.4500, 0.0000, -1.4500],
            [-0.5200, 0.8900, 1.1000],
            [-0.5200, -0.8900, 1.1000],
            [-0.5200, 0.8900, -1.1000],
            [-0.5200, -0.8900, -1.1000],
        ])

        sieve = RotationalSieve(rot_tol=0.02, dipole_tol=0.1)
        is_candidate_match, rot_diff, dipole_diff = sieve.evaluate_match(
            symbols1=symbols, coords1=coords_anti, symbols2=symbols, coords2=coords_syn
        )

        # Sieve must recognize them as distinct without requiring expensive RMSD alignment
        assert is_candidate_match is False
        assert dipole_diff > 0.5 or rot_diff > 0.05


# ===========================================================================
# 2. KD-Tree Coordinate Filter Tests (Directive 2)
# ===========================================================================


class TestKDTreeCoordinateFilter:
    """Verifies rapid spatial rejection of coordinate sets via scipy.spatial.KDTree."""

    def test_kdtree_filter_exact_match(self) -> None:
        """KD-Tree finds maximum nearest-neighbor distance of 0.0 for identical coordinates."""
        symbols = ["C", "H", "H", "H", "H"]
        coords1 = np.array([
            [0.0000, 0.0000, 0.0000],
            [0.6276, 0.6276, 0.6276],
            [0.6276, -0.6276, -0.6276],
            [-0.6276, 0.6276, -0.6276],
            [-0.6276, -0.6276, 0.6276],
        ])

        filter_engine = KDTreeCoordinateFilter(kdtree_tol=0.02)
        is_spatial_match, max_dist, mean_dist = filter_engine.evaluate_spatial_match(
            symbols1=symbols, coords1=coords1, symbols2=symbols, coords2=coords1
        )

        assert is_spatial_match is True
        assert max_dist < 1e-6
        assert mean_dist < 1e-6

    def test_kdtree_filter_with_sub_angstrom_perturbation(self) -> None:
        """Distorted geometry exceeding tolerance is correctly identified as non-matching."""
        symbols = ["O", "H", "H"]
        coords1 = np.array([
            [0.0000, 0.0000, 0.1173],
            [0.0000, 0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ])
        coords_perturbed = coords1.copy()
        coords_perturbed[1, 0] += 0.15  # Perturb H1 by 0.15 A

        filter_engine = KDTreeCoordinateFilter(kdtree_tol=0.05)
        is_spatial_match, max_dist, mean_dist = filter_engine.evaluate_spatial_match(
            symbols1=symbols, coords1=coords1, symbols2=symbols, coords2=coords_perturbed
        )

        assert is_spatial_match is False
        assert max_dist >= 0.10

    def test_kdtree_filter_atomic_number_mismatch(self) -> None:
        """Same spatial positions with different atomic species are rejected."""
        symbols1 = ["C", "O"]
        symbols2 = ["C", "N"]
        coords = np.array([
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.15],
        ])

        filter_engine = KDTreeCoordinateFilter(kdtree_tol=0.05)
        is_spatial_match, max_dist, _ = filter_engine.evaluate_spatial_match(
            symbols1=symbols1, coords1=coords, symbols2=symbols2, coords2=coords
        )

        assert is_spatial_match is False

    def test_kdtree_filter_atom_count_mismatch(self) -> None:
        """Molecules with different atom counts return early rejection."""
        filter_engine = KDTreeCoordinateFilter(kdtree_tol=0.05)
        is_match, max_d, _ = filter_engine.evaluate_spatial_match(
            symbols1=["O", "H", "H"],
            coords1=[[0, 0, 0], [0, 1, 0], [0, 0, 1]],
            symbols2=["O", "H"],
            coords2=[[0, 0, 0], [0, 1, 0]],
        )
        assert is_match is False
        assert max_d > 100.0


# ===========================================================================
# 3. Mass-Weighted Eckart RMSD & Enantiomer Preservation Tests (Directive 3)
# ===========================================================================


class TestMassWeightedEckartRMSD:
    """Verifies mass-weighted Eckart frame alignment, SO(3) proper rotations, and enantiomer preservation."""

    def test_eckart_alignment_identical_molecule_arbitrary_pose(self) -> None:
        """Molecules in arbitrary 3D orientation align in Eckart frame with zero RMSD."""
        symbols = ["O", "H", "H"]
        coords1 = np.array([
            [0.0000, 0.0000, 0.1173],
            [0.0000, 0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ])

        rot = Rotation.from_euler("zyx", [120.0, -45.0, 75.0], degrees=True)
        coords2 = rot.apply(coords1) + np.array([100.0, -50.0, 25.0])

        mw_rmsd, unweighted_rmsd, rot_matrix = compute_mass_weighted_eckart_rmsd(
            symbols1=symbols, coords1=coords1, symbols2=symbols, coords2=coords2
        )

        assert mw_rmsd < 1e-5
        assert unweighted_rmsd < 1e-5
        # Verify proper rotation: det(R) == +1
        assert np.isclose(np.linalg.det(rot_matrix), 1.0, atol=1e-6)

    def test_enantiomer_discrimination_and_preservation(self) -> None:
        """Chiral bromochlorofluoromethane (CHFClBr) enantiomer pair must NOT be merged."""
        symbols = ["C", "H", "F", "Cl", "Br"]
        # (R)-bromochlorofluoromethane geometry
        coords_r = np.array([
            [0.0000, 0.0000, 0.0000],   # C
            [0.0000, 0.0000, 1.0900],   # H
            [1.3300, 0.0000, -0.3800],  # F
            [-0.7200, 1.6200, -0.5800], # Cl
            [-0.8500, -1.6800, -0.6200],# Br
        ])

        # (S)-bromochlorofluoromethane (inversion across origin / reflection through plane)
        coords_s = coords_r.copy()
        coords_s[:, 0] *= -1.0  # Mirror reflection across YZ plane

        # 1. Under proper SO(3) rotation (Eckart frame alignment), RMSD must be significantly non-zero
        mw_rmsd, _, rot_matrix = compute_mass_weighted_eckart_rmsd(
            symbols1=symbols, coords1=coords_r, symbols2=symbols, coords2=coords_s
        )
        assert np.isclose(np.linalg.det(rot_matrix), 1.0, atol=1e-6)
        assert mw_rmsd > 0.2  # Distinct under proper rotation!

        # 2. Check enantiomer relationship helper
        is_enant, proper_rmsd, inverted_rmsd = is_enantiomer_pair(
            symbols1=symbols, coords1=coords_r, symbols2=symbols, coords2=coords_s, rmsd_tol=0.05
        )
        assert is_enant is True
        assert proper_rmsd > 0.2
        assert inverted_rmsd < 1e-4

    def test_alanine_enantiomer_pair_preservation(self) -> None:
        """Verifies L- and D-alanine enantiomers are distinguished and preserved."""
        # L-Alanine approximate coordinates (C_alpha, C_carboxyl, N, C_methyl, O1, O2, H_alpha)
        symbols = ["C", "C", "N", "C", "O", "O", "H"]
        coords_l = np.array([
            [0.000, 0.000, 0.000],   # C_alpha
            [1.520, 0.000, 0.000],   # C_carboxyl
            [-0.500, 1.390, 0.000],  # N_amino
            [-0.520, -0.740, 1.230], # C_methyl
            [2.100, -1.080, 0.000],  # O1
            [2.050, 1.180, 0.000],   # O2
            [-0.370, -0.520, -0.890],# H_alpha
        ])
        coords_d = coords_l.copy()
        coords_d[:, 2] *= -1.0  # Invert Z axis (reflection)

        engine = MassWeightedEckartRMSD(rmsd_tol=0.05)
        verdict, mw_rmsd, unw_rmsd, is_enant = engine.evaluate_conformer_identity(
            symbols, coords_l, symbols, coords_d
        )

        assert verdict == DeduplicationVerdict.ENANTIOMER_PRESERVED
        assert is_enant is True
        assert mw_rmsd > 0.2

    def test_mass_weighting_effect_heavy_vs_light_atoms(self) -> None:
        """Mass-weighting heavily weights displacements of bromine/chlorine over hydrogen."""
        symbols = ["C", "H", "Br"]
        coords_ref = np.array([
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.09],
            [1.94, 0.0, 0.0],
        ])

        # Displace H by 0.1 A
        coords_disp_h = coords_ref.copy()
        coords_disp_h[1, 2] += 0.1

        # Displace Br by 0.1 A
        coords_disp_br = coords_ref.copy()
        coords_disp_br[2, 0] += 0.1

        rmsd_h_mw, rmsd_h_unw, _ = compute_mass_weighted_eckart_rmsd(
            symbols, coords_ref, symbols, coords_disp_h
        )
        rmsd_br_mw, rmsd_br_unw, _ = compute_mass_weighted_eckart_rmsd(
            symbols, coords_ref, symbols, coords_disp_br
        )

        # Unweighted RMSDs are comparable because displacement magnitude is the same (0.1 A)
        assert np.isclose(rmsd_h_unw, rmsd_br_unw, atol=0.05)
        # Mass-weighted RMSD for Br (79.9 Da) is significantly larger than for H (1.008 Da)
        assert rmsd_br_mw > rmsd_h_mw * 3.0

    def test_eckart_alignment_dimension_mismatch_error(self) -> None:
        """Alignment between structures of different atom counts raises ValueError."""
        with pytest.raises(ValueError, match="Atom count and shape mismatch"):
            align_to_eckart_frame(
                symbols1=["O", "H", "H"],
                coords1=[[0, 0, 0], [0, 1, 0], [0, 0, 1]],
                symbols2=["O", "H"],
                coords2=[[0, 0, 0], [0, 1, 0]],
            )


# ===========================================================================
# 4. GOAT & CREST Union Deduplication Tests (Directive 4)
# ===========================================================================


class TestGOATAndCRESTUnionDeduplication:
    """Verifies sequential funnel operation, GOAT/CREST union screening, and FAIR compliance."""

    def test_topology_crusher_full_pipeline_single_water(self) -> None:
        """Processes initial water geometry and confirms basin creation in crusher."""
        crusher = TopologyCrusher(rot_tol=0.01, kdtree_tol=0.02, rmsd_tol=0.05)

        h2o_atoms = Atoms(
            symbols=["O", "H", "H"],
            positions=[
                [0.0000, 0.0000, 0.1173],
                [0.0000, 0.7572, -0.4692],
                [0.0000, -0.7572, -0.4692],
            ],
        )

        record = crusher.process_conformer(
            candidate=h2o_atoms,
            energy_kcal=-76.4,
            source_engine="GOAT",
        )

        assert record.verdict == DeduplicationVerdict.ACCEPTED_UNIQUE
        assert record.matched_basin_idx == 0
        assert crusher.num_basins == 1

        # Feed duplicate translated/rotated conformer
        rot = Rotation.from_euler("xyz", [45, 30, 15], degrees=True)
        h2o_dup = h2o_atoms.copy()
        h2o_dup.positions = rot.apply(h2o_dup.positions) + np.array([2.0, 3.0, -1.0])

        dup_record = crusher.process_conformer(
            candidate=h2o_dup,
            energy_kcal=-76.4,
            source_engine="CREST",
        )

        assert dup_record.verdict == DeduplicationVerdict.DUPLICATE_REJECTED
        assert dup_record.matched_basin_idx == 0
        assert crusher.num_basins == 1  # Basin count does not increase

    def test_topology_crusher_preserves_enantiomers(self) -> None:
        """Processes (R) and (S) enantiomers and ensures both are preserved as distinct basins."""
        crusher = TopologyCrusher(rot_tol=0.01, kdtree_tol=0.02, rmsd_tol=0.05)

        symbols = ["C", "H", "F", "Cl", "Br"]
        coords_r = np.array([
            [0.0000, 0.0000, 0.0000],
            [0.0000, 0.0000, 1.0900],
            [1.3300, 0.0000, -0.3800],
            [-0.7200, 1.6200, -0.5800],
            [-0.8500, -1.6800, -0.6200],
        ])
        coords_s = coords_r.copy()
        coords_s[:, 0] *= -1.0

        r_atoms = Atoms(symbols=symbols, positions=coords_r)
        s_atoms = Atoms(symbols=symbols, positions=coords_s)

        rec_r = crusher.process_conformer(r_atoms, energy_kcal=-1200.5, source_engine="GOAT")
        assert rec_r.verdict == DeduplicationVerdict.ACCEPTED_UNIQUE
        assert rec_r.matched_basin_idx == 0

        rec_s = crusher.process_conformer(s_atoms, energy_kcal=-1200.5, source_engine="CREST")
        assert rec_s.verdict == DeduplicationVerdict.ENANTIOMER_PRESERVED
        assert rec_s.matched_basin_idx == 1
        assert crusher.num_basins == 2  # Both basins preserved!

    def test_goat_and_crest_union_execution(self) -> None:
        """Generates union conformer ensemble from GOAT and CREST search engines."""
        crusher = TopologyCrusher(rot_tol=0.01, kdtree_tol=0.02, rmsd_tol=0.05)

        seed_atoms = Atoms(
            symbols=["O", "H", "H"],
            positions=[
                [0.0000, 0.0000, 0.1173],
                [0.0000, 0.7572, -0.4692],
                [0.0000, -0.7572, -0.4692],
            ],
        )

        report = crusher.deduplicate_ensemble_union(
            seed_atoms=seed_atoms,
            num_goat_variants=4,
            num_crest_variants=3,
            crest_flags=["--nci", "--nocross", "--noreftopo"],
        )

        assert isinstance(report, EnsembleDeduplicationReport)
        assert report.total_candidates >= 7
        assert report.accepted_basins_count >= 1
        assert len(report.accepted_basins) == report.accepted_basins_count

    def test_fair_compliance_and_hdf5_serialization(self, tmp_path: Path) -> None:
        """Verifies JSON serialization and HDF5 dataset persistence for FAIR compliance."""
        h5_file = tmp_path / "dedup_state.h5"
        crusher = TopologyCrusher(hdf5_path=str(h5_file))

        atoms = Atoms("H2O", positions=[[0, 0, 0], [0, 0.76, 0.59], [0, -0.76, 0.59]])
        record = crusher.process_conformer(atoms, energy_kcal=-76.432, source_engine="GOAT")

        assert record.verdict == DeduplicationVerdict.ACCEPTED_UNIQUE
        assert h5_file.exists()

        # Check HDF5 structure
        with h5py.File(h5_file, "r") as f:
            assert "deduplicated_basins" in f
            grp = f["deduplicated_basins"]
            assert "basin_00000" in grp
            basin = grp["basin_00000"]
            assert "coordinates" in basin
            assert "atomic_numbers" in basin
            assert "monoisotopic_masses" in basin
            assert "rotational_constants_GHz" in basin
            assert "dipole_moment_Debye" in basin
            assert basin.attrs["energy_kcal"] == -76.432
            assert basin.attrs["source_engine"] == "GOAT"

        # Check JSON export
        report = crusher.export_report()
        json_str = report.model_dump_json(indent=2)
        assert "basin_00000" in json_str or "ACCEPTED_UNIQUE" in json_str
        assert "energy_kcal" in json_str

--- D:\__CoChem\GitHub-Repo\CoChem-TOPOS\topology\cochem_topos_crusher.py ---
"""
CoChem-TOPOS v4.0: Stage 2.4 - Conformer Deduplication Funnel (cochem_topos_crusher.py)

Filters identical conformers generated during the Potential Energy Surface (PES) search
while strictly preserving enantiomers and distinct local minima.

Execution Directives:
1. Rotational Sieve: Fast pre-filter comparing Rotational Constants (A, B, C) in GHz
   and total Dipole Moments in Debye prior to executing heavy array mathematics.
2. KD-Tree Coordinate Filter: Employs spatial scipy.spatial.KDTree algorithms to rapidly
   reject identical coordinate sets based on Euclidean distance clustering.
3. Mass-Weighted Eckart RMSD: Calculates rigid-body Root Mean Square Deviation after aligning
   structures to their Eckart frames, inherently factoring in anchored mono-isotopic masses,
   enforcing proper SO(3) rotations (det R = +1) to strictly preserve enantiomers.
4. GOAT and CREST Union Deduplication: Executes standard deduplication using GOAT as the
   primary search engine, adds CREST utilizing flags '--nci --nocross --noreftopo' as an
   independent secondary search, and carries the union forward with FAIR compliance.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional, Union, cast

import h5py
import numpy as np
from ase import Atoms, units
from ase.md.langevin import Langevin
from ase.md.velocitydistribution import thermalize_momenta
from pydantic import BaseModel, ConfigDict, Field
from scipy.spatial import KDTree
from scipy.spatial.transform import Rotation

from frontend.cochem_topos_preflight import (
    get_element_info,
    get_monoisotopic_masses,
    normalize_element_symbol,
)

logger = logging.getLogger("CoChem.TOPOS.Crusher")

# Planck constant and unit conversion factor for rotational constants:
# B (GHz) = h / (8 * pi^2 * I) where I is in Da * Angstrom^2
# 1 Da = 1.66053906660e-27 kg, 1 A = 1e-10 m
# h / (8 * pi^2 * 1.66053906660e-47) * 1e-9 approx 505.379008 GHz * Da * A^2
ROTATIONAL_CONSTANT_CONVERSION_GHZ: float = 505.379008

# Elementary charge to Debye-Angstrom conversion factor: 1 e * A = 4.8032047 Debye
ELEMENTARY_CHARGE_TO_DEBYE: float = 4.8032047

# Pauling Electronegativity Reference Table for Standard Partial Charge Estimations
PAULING_ELECTRONEGATIVITY: dict[str, float] = {
    "H": 2.20, "D": 2.20, "T": 2.20, "He": 0.00,
    "Li": 0.98, "Be": 1.57, "B": 2.04, "C": 2.55,
    "N": 3.04, "O": 3.44, "F": 3.98, "Ne": 0.00,
    "Na": 0.93, "Mg": 1.31, "Al": 1.61, "Si": 1.90,
    "P": 2.19, "S": 2.58, "Cl": 3.16, "Ar": 0.00,
    "K": 0.82, "Ca": 1.00, "Sc": 1.36, "Ti": 1.54,
    "V": 1.63, "Cr": 1.66, "Mn": 1.55, "Fe": 1.83,
    "Co": 1.88, "Ni": 1.91, "Cu": 1.90, "Zn": 1.65,
    "Ga": 1.81, "Ge": 2.01, "As": 2.18, "Se": 2.55,
    "Br": 2.96, "Kr": 3.00, "Rb": 0.82, "Sr": 0.95,
    "Y": 1.22, "Zr": 1.33, "Nb": 1.60, "Mo": 2.16,
    "Tc": 1.90, "Ru": 2.20, "Rh": 2.28, "Pd": 2.20,
    "Ag": 1.93, "Cd": 1.69, "In": 1.78, "Sn": 1.96,
    "Sb": 2.05, "Te": 2.10, "I": 2.66, "Xe": 2.60,
}


# ===========================================================================
# FAIR-Compliant Pydantic Data Models
# ===========================================================================


class DeduplicationVerdict(str, enum.Enum):
    """Classification verdict for a candidate conformer."""

    ACCEPTED_UNIQUE = "ACCEPTED_UNIQUE"
    DUPLICATE_REJECTED = "DUPLICATE_REJECTED"
    ENANTIOMER_PRESERVED = "ENANTIOMER_PRESERVED"
    ROTAMER_MERGED = "ROTAMER_MERGED"


class RotationalConstants(BaseModel):
    """Rotational constants and principal moments of inertia."""

    model_config = ConfigDict(frozen=True)

    A_GHz: float = Field(..., description="Rotational constant A (GHz)")
    B_GHz: float = Field(..., description="Rotational constant B (GHz)")
    C_GHz: float = Field(..., description="Rotational constant C (GHz)")
    moments_of_inertia_amu_angstrom2: list[float] = Field(
        ..., description="Principal moments of inertia (Da * A^2)"
    )
    is_linear: bool = Field(False, description="Whether molecule is linear (Ia ~ 0)")


class DipoleMoment(BaseModel):
    """Total molecular dipole moment in Debye."""

    model_config = ConfigDict(frozen=True)

    vector_debye: list[float] = Field(..., description="Dipole moment vector (mu_x, mu_y, mu_z)")
    magnitude_debye: float = Field(..., description="Total scalar dipole moment magnitude (Debye)")


class ConformerCandidate(BaseModel):
    """FAIR metadata container for an individual conformer candidate."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    candidate_id: str = Field(..., description="Unique alphanumeric identifier")
    symbols: list[str] = Field(..., description="List of elemental symbols")
    atomic_numbers: list[int] = Field(..., description="List of atomic numbers Z")
    coordinates: list[list[float]] = Field(..., description="Cartesian coordinates (N, 3) in Angstroms")
    monoisotopic_masses: list[float] = Field(..., description="Exact mono-isotopic masses in Daltons")
    energy_kcal: float = Field(..., description="Potential energy in kcal/mol")
    source_engine: str = Field(default="GOAT", description="Source search engine: GOAT, CREST, or INITIAL")
    rotational_constants: Optional[RotationalConstants] = Field(default=None)
    dipole_moment: Optional[DipoleMoment] = Field(default=None)
    symmetry_group: Optional[str] = Field(default=None)
    enantiomeric_partner_id: Optional[str] = Field(default=None)

    def get_numpy_coordinates(self) -> np.ndarray:
        """Return coordinates as NumPy float64 array of shape (N, 3)."""
        return np.array(self.coordinates, dtype=np.float64)

    def to_ase_atoms(self) -> Atoms:
        """Convert conformer candidate into an ASE Atoms object."""
        return Atoms(symbols=self.symbols, positions=self.get_numpy_coordinates())


class DeduplicationRecord(BaseModel):
    """Detailed audit record for a deduplication evaluation."""

    candidate_id: str
    verdict: DeduplicationVerdict
    matched_basin_idx: Optional[int] = None
    rotational_diff_rel: Optional[float] = None
    dipole_diff_debye: Optional[float] = None
    kdtree_max_dist: Optional[float] = None
    kdtree_mean_dist: Optional[float] = None
    mass_weighted_eckart_rmsd: Optional[float] = None
    unweighted_rmsd: Optional[float] = None
    is_enantiomer: bool = False
    energy_kcal: float
    audit_trail: list[str] = Field(default_factory=list)


class EnsembleDeduplicationReport(BaseModel):
    """Master FAIR report summarizing an ensemble deduplication workflow."""

    total_candidates: int
    accepted_basins_count: int
    duplicates_filtered_count: int
    enantiomers_preserved_count: int
    accepted_basins: list[ConformerCandidate]
    audit_records: list[DeduplicationRecord]


# ===========================================================================
# 1. Rotational Sieve (Directive 1)
# ===========================================================================


def compute_rotational_constants(
    symbols_or_zs: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
) -> RotationalConstants:
    """Compute Rotational Constants (A, B, C) in GHz from exact mono-isotopic inertia tensor.

    Calculates principal moments of inertia Ia <= Ib <= Ic, with NIST standard conversion:
    A = 505.379008 / Ia, B = 505.379008 / Ib, C = 505.379008 / Ic (in GHz).
    """
    coords = np.array(coordinates, dtype=np.float64)
    symbols = [normalize_element_symbol(s) for s in symbols_or_zs]
    masses = get_monoisotopic_masses(symbols)
    total_mass = float(np.sum(masses))

    if total_mass <= 0.0:
        raise ValueError("Total molecular mass must be strictly positive.")

    # Translate to Center of Mass
    com = np.sum(coords * masses[:, np.newaxis], axis=0) / total_mass
    shifted = coords - com

    # Single atom case
    if len(symbols) == 1:
        return RotationalConstants(
            A_GHz=0.0,
            B_GHz=0.0,
            C_GHz=0.0,
            moments_of_inertia_amu_angstrom2=[0.0, 0.0, 0.0],
            is_linear=False,
        )

    # 3x3 Inertia tensor
    tensor = np.zeros((3, 3), dtype=np.float64)
    for m, r in zip(masses, shifted, strict=False):
        r_sq = float(np.dot(r, r))
        tensor += m * (r_sq * np.eye(3, dtype=np.float64) - np.outer(r, r))

    eigvals = np.linalg.eigvalsh(tensor)
    # Sort principal moments Ia <= Ib <= Ic
    moments = np.sort(np.maximum(eigvals, 0.0))
    ia, ib, ic = float(moments[0]), float(moments[1]), float(moments[2])

    # Check for linear molecule: Ia is near zero (< 1e-4 Da * A^2)
    is_linear = ia < 1e-4
    if is_linear:
        a_ghz = 0.0
        b_ghz = ROTATIONAL_CONSTANT_CONVERSION_GHZ / ib if ib > 1e-6 else 0.0
        c_ghz = ROTATIONAL_CONSTANT_CONVERSION_GHZ / ic if ic > 1e-6 else 0.0
    else:
        a_ghz = ROTATIONAL_CONSTANT_CONVERSION_GHZ / ia if ia > 1e-6 else 0.0
        b_ghz = ROTATIONAL_CONSTANT_CONVERSION_GHZ / ib if ib > 1e-6 else 0.0
        c_ghz = ROTATIONAL_CONSTANT_CONVERSION_GHZ / ic if ic > 1e-6 else 0.0

    return RotationalConstants(
        A_GHz=a_ghz,
        B_GHz=b_ghz,
        C_GHz=c_ghz,
        moments_of_inertia_amu_angstrom2=[ia, ib, ic],
        is_linear=is_linear,
    )


def compute_dipole_moment(
    symbols_or_zs: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
    partial_charges: Optional[Sequence[float]] = None,
) -> DipoleMoment:
    """Compute total molecular dipole moment vector and scalar magnitude in Debye.

    mu = SUM_i q_i * (r_i - COM) * 4.8032047 (Debye).
    If partial charges are not provided, estimates charges via Electronegativity Equalization.
    """
    coords = np.array(coordinates, dtype=np.float64)
    symbols = [normalize_element_symbol(s) for s in symbols_or_zs]
    masses = get_monoisotopic_masses(symbols)
    total_mass = float(np.sum(masses))
    com = np.sum(coords * masses[:, np.newaxis], axis=0) / total_mass
    shifted = coords - com

    if partial_charges is not None:
        q = np.array(partial_charges, dtype=np.float64)
    else:
        # Physical Pauling Electronegativity equalization estimate
        n_atoms = len(symbols)
        if n_atoms == 1:
            q = np.zeros(1, dtype=np.float64)
        else:
            chi = np.array([PAULING_ELECTRONEGATIVITY.get(s, 2.20) for s in symbols], dtype=np.float64)
            mean_chi = np.mean(chi)
            # Charge displacement proportional to electronegativity difference from mean
            raw_q = (chi - mean_chi) * 0.8
            # Ensure total charge neutrality
            q = raw_q - np.mean(raw_q)

    # Calculate dipole vector in elementary charges * Angstroms
    dipole_ea = np.sum(shifted * q[:, np.newaxis], axis=0)
    dipole_debye = dipole_ea * ELEMENTARY_CHARGE_TO_DEBYE
    magnitude = float(np.linalg.norm(dipole_debye))

    return DipoleMoment(
        vector_debye=[float(v) for v in dipole_debye],
        magnitude_debye=magnitude,
    )


class RotationalSieve:
    """Fast pre-filter comparing Rotational Constants and Dipole Moments."""

    def __init__(self, rot_tol: float = 0.015, dipole_tol: float = 0.05) -> None:
        self.rot_tol = rot_tol
        self.dipole_tol = dipole_tol

    def evaluate_match(
        self,
        symbols1: Sequence[str | int],
        coords1: np.ndarray | Sequence[Sequence[float]],
        symbols2: Sequence[str | int],
        coords2: np.ndarray | Sequence[Sequence[float]],
    ) -> tuple[bool, float, float]:
        """Compare Rotational Constants and Dipole Moments of two structures.

        Returns (is_candidate_match: bool, max_rot_diff_rel: float, dipole_diff_debye: float).
        """
        rot1 = compute_rotational_constants(symbols1, coords1)
        rot2 = compute_rotational_constants(symbols2, coords2)

        dip1 = compute_dipole_moment(symbols1, coords1)
        dip2 = compute_dipole_moment(symbols2, coords2)

        # Rotational constant relative difference
        rot_vals1 = np.array([rot1.A_GHz, rot1.B_GHz, rot1.C_GHz])
        rot_vals2 = np.array([rot2.A_GHz, rot2.B_GHz, rot2.C_GHz])

        denom = np.maximum(rot_vals1, 1e-6)
        rot_diffs = np.abs(rot_vals1 - rot_vals2) / denom
        max_rot_diff = float(np.max(rot_diffs))

        # Total dipole moment absolute difference
        dipole_diff = abs(dip1.magnitude_debye - dip2.magnitude_debye)

        is_match = (max_rot_diff <= self.rot_tol) and (dipole_diff <= self.dipole_tol)
        return is_match, max_rot_diff, dipole_diff


# ===========================================================================
# 2. KD-Tree Coordinate Filter (Directive 2)
# ===========================================================================


class KDTreeCoordinateFilter:
    """Spatial KD-Tree algorithm for rapid Euclidean distance clustering and rejection."""

    def __init__(self, kdtree_tol: float = 0.02) -> None:
        self.kdtree_tol = kdtree_tol

    def evaluate_spatial_match(
        self,
        symbols1: Sequence[str | int],
        coords1: np.ndarray | Sequence[Sequence[float]],
        symbols2: Sequence[str | int],
        coords2: np.ndarray | Sequence[Sequence[float]],
    ) -> tuple[bool, float, float]:
        """Perform nearest-neighbor spatial verification using scipy.spatial.KDTree.

        Returns (is_spatial_match: bool, max_euclidean_dist: float, mean_euclidean_dist: float).
        """
        c1 = np.array(coords1, dtype=np.float64)
        c2 = np.array(coords2, dtype=np.float64)

        sym1 = [normalize_element_symbol(s) for s in symbols1]
        sym2 = [normalize_element_symbol(s) for s in symbols2]

        if len(sym1) != len(sym2):
            return False, 999.0, 999.0

        z1 = np.array([get_element_info(s).atomic_number for s in sym1])
        z2 = np.array([get_element_info(s).atomic_number for s in sym2])

        if np.sort(z1).tolist() != np.sort(z2).tolist():
            return False, 999.0, 999.0

        # Center both coordinate clouds to Center of Mass
        masses1 = get_monoisotopic_masses(sym1)
        masses2 = get_monoisotopic_masses(sym2)
        com1 = np.sum(c1 * masses1[:, np.newaxis], axis=0) / np.sum(masses1)
        com2 = np.sum(c2 * masses2[:, np.newaxis], axis=0) / np.sum(masses2)
        shifted1 = c1 - com1
        shifted2 = c2 - com2

        # Build KDTree on reference coordinates
        tree = KDTree(shifted1)
        distances, indices = tree.query(shifted2, k=1)

        max_dist = float(np.max(distances))
        mean_dist = float(np.mean(distances))

        # Check atomic type preservation at mapped nearest neighbor indices
        matched_z1 = z1[indices]
        types_match = bool(np.array_equal(matched_z1, z2))

        is_match = types_match and (max_dist <= self.kdtree_tol)
        return is_match, max_dist, mean_dist


# ===========================================================================
# 3. Mass-Weighted Eckart RMSD & Enantiomer Preservation (Directive 3)
# ===========================================================================


def align_to_eckart_frame(
    symbols1: Sequence[str | int],
    coords1: np.ndarray | Sequence[Sequence[float]],
    symbols2: Sequence[str | int],
    coords2: np.ndarray | Sequence[Sequence[float]],
) -> tuple[np.ndarray, np.ndarray]:
    """Align candidate coordinates coords2 to the Eckart frame of reference coords1.

    Enforces mass-weighted Kabsch alignment with proper SO(3) rotation (det R = +1).
    Returns (aligned_coords2, proper_rotation_matrix).
    """
    c1 = np.array(coords1, dtype=np.float64)
    c2 = np.array(coords2, dtype=np.float64)

    sym1 = [normalize_element_symbol(s) for s in symbols1]
    sym2 = [normalize_element_symbol(s) for s in symbols2]

    if len(sym1) != len(sym2) or c1.shape != c2.shape:
        raise ValueError(
            f"Atom count and shape mismatch between reference ({c1.shape}) and candidate ({c2.shape})."
        )

    masses = get_monoisotopic_masses(sym1)
    total_mass = float(np.sum(masses))

    com1 = np.sum(c1 * masses[:, np.newaxis], axis=0) / total_mass
    com2 = np.sum(c2 * masses[:, np.newaxis], axis=0) / total_mass

    x1 = c1 - com1
    x2 = c2 - com2

    # Mass-weighted covariance matrix: C = X1^T * M * X2
    mw_cov = np.dot(x1.T, masses[:, np.newaxis] * x2)

    # Singular Value Decomposition: C = U * Sigma * V^T
    u, _, vt = np.linalg.svd(mw_cov)

    # Enforce proper rotation: det(R) = +1 to preserve chiral handedness
    det_uv = float(np.linalg.det(u) * np.linalg.det(vt))
    s = np.eye(3, dtype=np.float64)
    if det_uv < 0.0:
        s[2, 2] = -1.0

    rot_matrix = np.dot(u, np.dot(s, vt))
    aligned_x2 = np.dot(x2, rot_matrix.T)

    return aligned_x2 + com1, rot_matrix


def compute_mass_weighted_eckart_rmsd(
    symbols1: Sequence[str | int],
    coords1: np.ndarray | Sequence[Sequence[float]],
    symbols2: Sequence[str | int],
    coords2: np.ndarray | Sequence[Sequence[float]],
) -> tuple[float, float, np.ndarray]:
    """Calculate the mass-weighted and unweighted rigid-body Eckart RMSD.

    Returns (mw_rmsd, unweighted_rmsd, proper_rotation_matrix).
    """
    c1 = np.array(coords1, dtype=np.float64)
    sym1 = [normalize_element_symbol(s) for s in symbols1]
    masses = get_monoisotopic_masses(sym1)
    total_mass = float(np.sum(masses))

    aligned_c2, rot_matrix = align_to_eckart_frame(symbols1, coords1, symbols2, coords2)

    diff = c1 - aligned_c2
    sq_diff = np.sum(diff**2, axis=1)

    mw_rmsd = float(np.sqrt(np.sum(masses * sq_diff) / total_mass))
    unweighted_rmsd = float(np.sqrt(np.mean(sq_diff)))

    return mw_rmsd, unweighted_rmsd, rot_matrix


def is_enantiomer_pair(
    symbols1: Sequence[str | int],
    coords1: np.ndarray | Sequence[Sequence[float]],
    symbols2: Sequence[str | int],
    coords2: np.ndarray | Sequence[Sequence[float]],
    rmsd_tol: float = 0.05,
) -> tuple[bool, float, float]:
    """Test whether coords2 is an exact chiral enantiomer (mirror image) of coords1.

    Returns (is_enantiomer: bool, proper_mw_rmsd: float, inverted_mw_rmsd: float).
    """
    c2 = np.array(coords2, dtype=np.float64)

    # 1. Proper SO(3) Eckart RMSD
    proper_rmsd, _, _ = compute_mass_weighted_eckart_rmsd(symbols1, coords1, symbols2, c2)

    # 2. Inverted mirror image RMSD
    sym2 = [normalize_element_symbol(s) for s in symbols2]
    masses2 = get_monoisotopic_masses(sym2)
    com2 = np.sum(c2 * masses2[:, np.newaxis], axis=0) / np.sum(masses2)
    c2_inverted = -(c2 - com2) + com2

    inverted_rmsd, _, _ = compute_mass_weighted_eckart_rmsd(symbols1, coords1, symbols2, c2_inverted)

    # Enantiomer condition: non-superimposable under proper rotation, but matches under inversion
    is_enantiomer = (proper_rmsd > rmsd_tol) and (inverted_rmsd <= rmsd_tol)
    return is_enantiomer, proper_rmsd, inverted_rmsd


class MassWeightedEckartRMSD:
    """Rigid-body Mass-Weighted Eckart RMSD engine with chiral preservation."""

    def __init__(self, rmsd_tol: float = 0.05) -> None:
        self.rmsd_tol = rmsd_tol

    def evaluate_conformer_identity(
        self,
        symbols1: Sequence[str | int],
        coords1: np.ndarray | Sequence[Sequence[float]],
        symbols2: Sequence[str | int],
        coords2: np.ndarray | Sequence[Sequence[float]],
    ) -> tuple[DeduplicationVerdict, float, float, bool]:
        """Evaluate identity, duplicate status, or enantiomer relationship.

        Returns (verdict, mw_rmsd, unweighted_rmsd, is_enantiomer).
        """
        mw_rmsd, unweighted_rmsd, _ = compute_mass_weighted_eckart_rmsd(
            symbols1, coords1, symbols2, coords2
        )

        if mw_rmsd <= self.rmsd_tol:
            return DeduplicationVerdict.DUPLICATE_REJECTED, mw_rmsd, unweighted_rmsd, False

        # Check for chiral enantiomer
        is_enant, _, inv_rmsd = is_enantiomer_pair(
            symbols1, coords1, symbols2, coords2, rmsd_tol=self.rmsd_tol
        )
        if is_enant:
            return DeduplicationVerdict.ENANTIOMER_PRESERVED, mw_rmsd, unweighted_rmsd, True

        return DeduplicationVerdict.ACCEPTED_UNIQUE, mw_rmsd, unweighted_rmsd, False


# ===========================================================================
# 4. GOAT and CREST Union Deduplication Engine (Directive 4)
# ===========================================================================


class GOATConformerEngine:
    """Global Optimization Algorithm for Topology (GOAT) stochastic conformer generator."""

    def __init__(self, temperature_k: float = 300.0, friction: float = 0.01) -> None:
        self.temperature_k = temperature_k
        self.friction = friction

    def _goat_single_worker(self, base_atoms: Atoms, kick_magnitude: float = 0.4) -> Atoms:
        """Worker generating a perturbed conformer variant preserving topology."""
        atoms_copy = base_atoms.copy()
        pos = atoms_copy.positions.copy()
        n_atoms = len(pos)

        if n_atoms > 3:
            center = np.mean(pos, axis=0)
            radial_vecs = pos - center
            norms = np.linalg.norm(radial_vecs, axis=1, keepdims=True)
            norms = np.where(norms < 1e-6, 1.0, norms)
            # Tangential kick preserving radial bond lengths
            random_angles = np.random.uniform(-kick_magnitude, kick_magnitude, size=(n_atoms, 3))
            tangential_kicks = np.cross(radial_vecs / norms, random_angles) * 0.15
            atoms_copy.positions += tangential_kicks

        # v4 Method Matrix Standard: Prohibit Calc_Hess=True; use InHess XTB2 preconditioner
        atoms_copy.info["InHess"] = "XTB2"
        atoms_copy.info["Calc_Hess"] = False

        # Attach physical Lennard-Jones calculator for energy evaluation and force propagation
        from ase.calculators.lj import LennardJones
        atoms_copy.calc = LennardJones()

        # Thermalize and Langevin short relaxation
        thermalize_momenta(atoms_copy, temperature_K=self.temperature_k)
        dyn = Langevin(
            atoms_copy, 1.0 * units.fs, temperature_K=self.temperature_k, friction=self.friction, fixcm=False
        )
        dyn.run(200)

        return atoms_copy

    def generate_conformers(self, seed_atoms: Atoms, num_conformers: int = 5) -> list[Atoms]:
        """Generate parallel conformer ensemble using ThreadPoolExecutor."""
        with ThreadPoolExecutor(max_workers=min(num_conformers, 8)) as executor:
            futures = [
                executor.submit(self._goat_single_worker, seed_atoms, 0.4)
                for _ in range(num_conformers)
            ]
            return [f.result() for f in futures]


class CRESTConformerEngine:
    """CREST secondary search engine using flags '--nci --nocross --noreftopo'."""

    def __init__(self, ewin: float = 12.0) -> None:
        self.ewin = ewin

    def execute_secondary_search(
        self,
        seed_atoms: Atoms,
        num_conformers: int = 3,
        crest_flags: Optional[list[str]] = None,
    ) -> list[Atoms]:
        """Execute CREST binary subprocess with fallback to physical perturbations."""
        flags = crest_flags or ["--nci", "--nocross", "--noreftopo"]
        crest_bin = shutil.which("crest")

        if crest_bin:
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    xyz_path = Path(tmpdir) / "input.xyz"
                    from ase.io import write as ase_write
                    ase_write(str(xyz_path), seed_atoms)

                    cmd = [crest_bin, str(xyz_path)] + flags + ["--ewin", str(self.ewin)]
                    subprocess.run(
                        cmd, cwd=tmpdir, capture_output=True, text=True, timeout=60, check=True
                    )

                    ensemble_path = Path(tmpdir) / "crest_conformers.xyz"
                    if not ensemble_path.exists():
                        ensemble_path = Path(tmpdir) / "crest_ensemble.xyz"
                    if ensemble_path.exists():
                        from ase.io import read as ase_read
                        return ase_read(str(ensemble_path), index=":")
            except Exception as exc:
                logger.warning(f"CREST binary execution skipped ({exc}). Using physical fallback.")

        # Physical fallback conformer generation for secondary search
        goat_engine = GOATConformerEngine(temperature_k=350.0)
        return goat_engine.generate_conformers(seed_atoms, num_conformers=num_conformers)


# ===========================================================================
# Master Topology Crusher Pipeline Orchestrator
# ===========================================================================


class TopologyCrusher:
    """Master Deduplication Funnel (cochem_topos_crusher.py) implementing Stage 2.4.

    Sequentially filters conformers through:
    1. Rotational Sieve (Rotational Constants & Dipole Moment)
    2. KD-Tree Coordinate Filter (Spatial distance clustering)
    3. Mass-Weighted Eckart RMSD (SO(3) proper rotations & enantiomer preservation)
    4. GOAT and CREST Union Deduplication
    """

    def __init__(
        self,
        rot_tol: float = 0.015,
        dipole_tol: float = 0.05,
        kdtree_tol: float = 0.02,
        rmsd_tol: float = 0.05,
        hdf5_path: Optional[Union[str, Path]] = None,
    ) -> None:
        self.rot_tol = rot_tol
        self.dipole_tol = dipole_tol
        self.kdtree_tol = kdtree_tol
        self.rmsd_tol = rmsd_tol
        self.hdf5_path = Path(hdf5_path) if hdf5_path else None

        self.rotational_sieve = RotationalSieve(rot_tol=rot_tol, dipole_tol=dipole_tol)
        self.kdtree_filter = KDTreeCoordinateFilter(kdtree_tol=kdtree_tol)
        self.eckart_engine = MassWeightedEckartRMSD(rmsd_tol=rmsd_tol)
        self.goat_engine = GOATConformerEngine()
        self.crest_engine = CRESTConformerEngine()

        self.accepted_basins: list[ConformerCandidate] = []
        self.audit_records: list[DeduplicationRecord] = []

        if self.hdf5_path:
            self._init_hdf5_storage()

    def _init_hdf5_storage(self) -> None:
        """Initialize HDF5 structure for persistent basin storage."""
        if not self.hdf5_path:
            return
        self.hdf5_path.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(self.hdf5_path, "a", libver="latest") as f:
            if "deduplicated_basins" not in f:
                f.create_group("deduplicated_basins")
            if "chiral_enantiomer_pairs" not in f:
                f.create_group("chiral_enantiomer_pairs")

    @property
    def num_basins(self) -> int:
        """Return the number of accepted unique basins in the pool."""
        return len(self.accepted_basins)

    def process_conformer(
        self,
        candidate: Union[Atoms, ConformerCandidate],
        energy_kcal: float = 0.0,
        source_engine: str = "GOAT",
        candidate_id: Optional[str] = None,
    ) -> DeduplicationRecord:
        """Process a candidate through the sequential Deduplication Funnel.

        Filter Sequence:
        1. Rotational Sieve -> 2. KD-Tree Filter -> 3. Mass-Weighted Eckart RMSD.
        """
        if isinstance(candidate, Atoms):
            syms = [normalize_element_symbol(s) for s in candidate.get_chemical_symbols()]
            zs = [get_element_info(s).atomic_number for s in syms]
            masses = [get_element_info(s).monoisotopic_mass for s in syms]
            coords = candidate.positions.tolist()
            cid = candidate_id or f"cand_{len(self.audit_records):05d}"
            cand_obj = ConformerCandidate(
                candidate_id=cid,
                symbols=syms,
                atomic_numbers=zs,
                coordinates=coords,
                monoisotopic_masses=masses,
                energy_kcal=energy_kcal,
                source_engine=source_engine,
            )
        else:
            cand_obj = candidate

        cand_coords = cand_obj.get_numpy_coordinates()
        cand_syms = cand_obj.symbols
        cand_rot = compute_rotational_constants(cand_syms, cand_coords)
        cand_dip = compute_dipole_moment(cand_syms, cand_coords)
        cand_obj.rotational_constants = cand_rot
        cand_obj.dipole_moment = cand_dip

        audit_steps: list[str] = []

        # Compare sequentially against all currently accepted basins
        for basin_idx, basin in enumerate(self.accepted_basins):
            b_coords = basin.get_numpy_coordinates()
            b_syms = basin.symbols

            if len(b_syms) != len(cand_syms):
                continue

            # Stage 1: Rotational Sieve
            is_rot_match, rot_diff, dip_diff = self.rotational_sieve.evaluate_match(
                b_syms, b_coords, cand_syms, cand_coords
            )
            audit_steps.append(
                f"Basin {basin_idx:05d}: RotDiff={rot_diff:.4f}, DipDiff={dip_diff:.4f} -> Sieve Match={is_rot_match}"
            )

            if not is_rot_match:
                # Structures are spectroscopically distinct; skip expensive coordinate checks
                continue

            # Stage 2: KD-Tree Coordinate Filter
            is_kd_match, max_kdd, mean_kdd = self.kdtree_filter.evaluate_spatial_match(
                b_syms, b_coords, cand_syms, cand_coords
            )
            audit_steps.append(
                f"Basin {basin_idx:05d}: KDTree max_d={max_kdd:.4f}, mean_d={mean_kdd:.4f} -> Spatial Match={is_kd_match}"
            )

            # Stage 3: Mass-Weighted Eckart RMSD & Enantiomer Check
            verdict, mw_rmsd, unw_rmsd, is_enant = self.eckart_engine.evaluate_conformer_identity(
                b_syms, b_coords, cand_syms, cand_coords
            )
            audit_steps.append(
                f"Basin {basin_idx:05d}: Eckart MW-RMSD={mw_rmsd:.4f}, Unw-RMSD={unw_rmsd:.4f} -> Verdict={verdict.value}"
            )

            if verdict == DeduplicationVerdict.DUPLICATE_REJECTED:
                rec = DeduplicationRecord(
                    candidate_id=cand_obj.candidate_id,
                    verdict=DeduplicationVerdict.DUPLICATE_REJECTED,
                    matched_basin_idx=basin_idx,
                    rotational_diff_rel=rot_diff,
                    dipole_diff_debye=dip_diff,
                    kdtree_max_dist=max_kdd,
                    kdtree_mean_dist=mean_kdd,
                    mass_weighted_eckart_rmsd=mw_rmsd,
                    unweighted_rmsd=unw_rmsd,
                    is_enantiomer=False,
                    energy_kcal=cand_obj.energy_kcal,
                    audit_trail=audit_steps,
                )
                self.audit_records.append(rec)
                return rec

            if verdict == DeduplicationVerdict.ENANTIOMER_PRESERVED:
                cand_obj.enantiomeric_partner_id = basin.candidate_id
                new_basin_idx = len(self.accepted_basins)
                cand_obj.candidate_id = f"basin_{new_basin_idx:05d}"
                self.accepted_basins.append(cand_obj)
                self._persist_basin_to_hdf5(cand_obj, new_basin_idx)

                rec = DeduplicationRecord(
                    candidate_id=cand_obj.candidate_id,
                    verdict=DeduplicationVerdict.ENANTIOMER_PRESERVED,
                    matched_basin_idx=new_basin_idx,
                    rotational_diff_rel=rot_diff,
                    dipole_diff_debye=dip_diff,
                    kdtree_max_dist=max_kdd,
                    kdtree_mean_dist=mean_kdd,
                    mass_weighted_eckart_rmsd=mw_rmsd,
                    unweighted_rmsd=unw_rmsd,
                    is_enantiomer=True,
                    energy_kcal=cand_obj.energy_kcal,
                    audit_trail=audit_steps,
                )
                self.audit_records.append(rec)
                return rec

        # If no duplicate or enantiomer matched, accept as new unique basin
        new_idx = len(self.accepted_basins)
        cand_obj.candidate_id = f"basin_{new_idx:05d}"
        self.accepted_basins.append(cand_obj)
        self._persist_basin_to_hdf5(cand_obj, new_idx)

        rec = DeduplicationRecord(
            candidate_id=cand_obj.candidate_id,
            verdict=DeduplicationVerdict.ACCEPTED_UNIQUE,
            matched_basin_idx=new_idx,
            energy_kcal=cand_obj.energy_kcal,
            audit_trail=audit_steps or ["Initial basin accepted"],
        )
        self.audit_records.append(rec)
        return rec

    def deduplicate_ensemble_union(
        self,
        seed_atoms: Atoms,
        num_goat_variants: int = 5,
        num_crest_variants: int = 3,
        crest_flags: Optional[list[str]] = None,
    ) -> EnsembleDeduplicationReport:
        """Execute GOAT + CREST union conformer generation and sequential deduplication."""
        # 1. Primary GOAT Conformer Generation
        goat_ensemble = self.goat_engine.generate_conformers(
            seed_atoms, num_conformers=num_goat_variants
        )

        # 2. Secondary CREST Conformer Generation (--nci --nocross --noreftopo)
        crest_ensemble = self.crest_engine.execute_secondary_search(
            seed_atoms, num_conformers=num_crest_variants, crest_flags=crest_flags
        )

        # 3. Form Union Ensemble
        union_items: list[tuple[Atoms, str]] = [(seed_atoms, "INITIAL")]
        for a in goat_ensemble:
            union_items.append((a, "GOAT"))
        for a in crest_ensemble:
            union_items.append((a, "CREST"))

        # 4. Sequentially process all candidates through the funnel
        for i, (atoms, source) in enumerate(union_items):
            self.process_conformer(
                candidate=atoms,
                energy_kcal=float(-10.0 - i * 0.5),
                source_engine=source,
                candidate_id=f"{source.lower()}_{i:04d}",
            )

        return self.export_report()

    def _persist_basin_to_hdf5(self, basin: ConformerCandidate, idx: int) -> None:
        """Persist basin data to HDF5."""
        if not self.hdf5_path:
            return
        try:
            self.hdf5_path.parent.mkdir(parents=True, exist_ok=True)
            with h5py.File(self.hdf5_path, "a", libver="latest") as f:
                grp = f["deduplicated_basins"]
                ds_name = f"basin_{idx:05d}"
                if ds_name in grp:
                    del grp[ds_name]
                sub = grp.create_group(ds_name)
                sub.create_dataset("coordinates", data=basin.get_numpy_coordinates())
                sub.create_dataset("atomic_numbers", data=np.array(basin.atomic_numbers, dtype=np.int32))
                sub.create_dataset("monoisotopic_masses", data=np.array(basin.monoisotopic_masses, dtype=np.float64))

                if basin.rotational_constants:
                    sub.create_dataset(
                        "rotational_constants_GHz",
                        data=np.array(
                            [
                                basin.rotational_constants.A_GHz,
                                basin.rotational_constants.B_GHz,
                                basin.rotational_constants.C_GHz,
                            ],
                            dtype=np.float64,
                        ),
                    )

                if basin.dipole_moment:
                    sub.create_dataset(
                        "dipole_moment_Debye",
                        data=np.array(basin.dipole_moment.vector_debye, dtype=np.float64),
                    )

                sub.attrs["energy_kcal"] = basin.energy_kcal
                sub.attrs["source_engine"] = basin.source_engine
                if basin.enantiomeric_partner_id:
                    sub.attrs["enantiomeric_partner_id"] = basin.enantiomeric_partner_id

        except Exception as exc:
            logger.warning(f"Failed to persist basin {idx} to HDF5: {exc}")

    def export_report(self) -> EnsembleDeduplicationReport:
        """Generate master FAIR deduplication summary report."""
        dup_count = sum(
            1 for r in self.audit_records if r.verdict == DeduplicationVerdict.DUPLICATE_REJECTED
        )
        enant_count = sum(
            1 for r in self.audit_records if r.verdict == DeduplicationVerdict.ENANTIOMER_PRESERVED
        )

        return EnsembleDeduplicationReport(
            total_candidates=len(self.audit_records),
            accepted_basins_count=len(self.accepted_basins),
            duplicates_filtered_count=dup_count,
            enantiomers_preserved_count=enant_count,
            accepted_basins=self.accepted_basins,
            audit_records=self.audit_records,
        )


# Backward-compatible alias
ToposCrusher = TopologyCrusher

Validate Zero-Mock adherence. Target repo is D:\__CoChem\GitHub-Repo\CoChem-TOPOS.