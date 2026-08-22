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
