"""
Unit tests for CoChem-TOPOS Combinatorial Fragment Assembly (Stage 3.0: cochem_topos_assembly.py).
Validates geometric docking, steric clash detection with micro-displacement along collision vectors,
Counterpoise (CP) BSSE ghost-atom block generation, and Cartesian constraint freezing for ORCA.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numpy.linalg as la
import pytest
from ase import Atoms

from escalation.cochem_topos_assembly import (
    AssemblyConfig,
    AssemblySessionReport,
    BSSEFragmentConfig,
    CounterpoiseBSSEGenerator,
    DockingCollisionVector,
    FragmentSource,
    GeometricDockingEngine,
    InternalCoordinateFreezer,
    StericClashResolver,
    ToposCombinatorialAssembler,
    assemble_weak_complex,
)
from mechanics.cochem_topos_memory import GeometryRecord, ToposHDF5MemoryManager

# ============================================================================
# 1. Tests for Data Models & Collision Vector Calculations
# ============================================================================


class TestFragmentSourceAndCollisionVector:
    """Verifies fragment source extraction, mass calculation, and collision vectors."""

    def test_fragment_source_from_coordinates(self) -> None:
        """Confirms FragmentSource computes correct mass, COM, and Hill formula."""
        symbols = ["O", "H", "H"]
        coords = [
            [0.0, 0.0, 0.1173],
            [0.0, 0.7572, -0.4692],
            [0.0, -0.7572, -0.4692],
        ]
        frag = FragmentSource.from_coordinates(
            fragment_id="monomer_H2O",
            symbols=symbols,
            coordinates=coords,
            energy_hartree=-76.432,
        )

        assert frag.fragment_id == "monomer_H2O"
        assert frag.num_atoms == 3
        assert frag.formula == "H2O"
        assert frag.atomic_numbers == [8, 1, 1]
        assert pytest.approx(frag.total_mass, rel=1e-3) == 18.015
        assert pytest.approx(frag.center_of_mass[0], abs=1e-4) == 0.0
        assert pytest.approx(frag.center_of_mass[1], abs=1e-4) == 0.0

    def test_fragment_source_from_ase_atoms(self) -> None:
        """Confirms FragmentSource creation from an ASE Atoms object."""
        atoms = Atoms("CH4", positions=[
            [0.0, 0.0, 0.0],
            [0.6276, 0.6276, 0.6276],
            [0.6276, -0.6276, -0.6276],
            [-0.6276, 0.6276, -0.6276],
            [-0.6276, -0.6276, 0.6276],
        ])
        frag = FragmentSource.from_atoms(
            fragment_id="monomer_CH4",
            atoms=atoms,
            energy_hartree=-40.512,
        )
        assert frag.num_atoms == 5
        assert frag.formula == "CH4"
        assert len(frag.coordinates) == 5

    def test_docking_collision_vector_calculation(self) -> None:
        """Confirms collision vector and unit axis between two monomer fragments."""
        frag_a = FragmentSource.from_coordinates(
            fragment_id="frag_a",
            symbols=["O", "H", "H"],
            coordinates=[[-1.5, 0.0, 0.0], [-1.8, 0.7, 0.0], [-0.6, 0.0, 0.0]],
        )
        frag_b = FragmentSource.from_coordinates(
            fragment_id="frag_b",
            symbols=["O", "H", "H"],
            coordinates=[[1.5, 0.0, 0.0], [1.8, 0.7, 0.0], [1.8, -0.7, 0.0]],
        )

        col_vec = DockingCollisionVector.compute(frag_a, frag_b)
        assert col_vec.distance > 0.0
        assert len(col_vec.vector) == 3
        assert len(col_vec.unit_vector) == 3
        assert pytest.approx(la.norm(col_vec.unit_vector), rel=1e-5) == 1.0
        # X-component should be primary direction
        assert col_vec.unit_vector[0] > 0.9

    def test_zero_distance_collision_vector_fallback(self) -> None:
        """Confirms robust default collision axis if two fragments share identical COM."""
        frag_a = FragmentSource.from_coordinates(
            fragment_id="frag_a",
            symbols=["C"],
            coordinates=[[0.0, 0.0, 0.0]],
        )
        frag_b = FragmentSource.from_coordinates(
            fragment_id="frag_b",
            symbols=["C"],
            coordinates=[[0.0, 0.0, 0.0]],
        )
        col_vec = DockingCollisionVector.compute(frag_a, frag_b)
        assert col_vec.distance == 0.0
        assert col_vec.unit_vector == [0.0, 0.0, 1.0]


# ============================================================================
# 2. Tests for Steric Clash Engine & Micro-Displacement
# ============================================================================


class TestStericClashResolver:
    """Verifies steric clash detection and micro-displacement along collision axis."""

    def test_no_clash_when_well_separated(self) -> None:
        """Well separated fragments should require zero micro-displacement."""
        coords_a = np.array([[-2.0, 0.0, 0.0], [-2.5, 0.7, 0.0]])
        coords_b = np.array([[2.0, 0.0, 0.0], [2.5, 0.7, 0.0]])
        unit_vec = np.array([1.0, 0.0, 0.0])

        resolver = StericClashResolver(min_distance=0.8, step_size=0.1)
        report, new_coords_b = resolver.resolve_clash(
            coords_a=coords_a,
            coords_b=coords_b,
            collision_axis=unit_vec,
        )

        assert report.has_initial_clash is False
        assert report.displacement_applied == 0.0
        assert report.micro_steps == 0
        assert report.min_final_distance >= 0.8
        np.testing.assert_allclose(new_coords_b, coords_b)

    def test_clash_detected_and_micro_displacement_applied(self) -> None:
        """Severe clash (< 0.8 A) triggers iterative outward displacement."""
        # Atoms placed 0.3 A apart
        coords_a = np.array([[0.0, 0.0, 0.0]])
        coords_b = np.array([[0.3, 0.0, 0.0]])
        unit_vec = np.array([1.0, 0.0, 0.0])

        resolver = StericClashResolver(min_distance=0.8, step_size=0.1)
        report, new_coords_b = resolver.resolve_clash(
            coords_a=coords_a,
            coords_b=coords_b,
            collision_axis=unit_vec,
        )

        assert report.has_initial_clash is True
        assert report.initial_min_distance == pytest.approx(0.3, abs=1e-4)
        assert report.min_final_distance >= 0.8
        assert report.displacement_applied >= 0.5  # Needs at least 5 steps of 0.1 A
        assert report.micro_steps >= 5
        assert report.clash_resolved is True
        # Verify new distance is >= 0.8 A
        new_dist = float(la.norm(coords_a[0] - new_coords_b[0]))
        assert new_dist >= 0.8

    def test_max_displacement_limit_respected(self) -> None:
        """Excessive clash that cannot be resolved within max_displacement stops gracefully."""
        coords_a = np.array([[0.0, 0.0, 0.0]])
        coords_b = np.array([[0.0, 0.0, 0.0]])
        # Set max displacement very small
        resolver = StericClashResolver(min_distance=2.0, step_size=0.1, max_displacement=0.5)
        report, _ = resolver.resolve_clash(
            coords_a=coords_a,
            coords_b=coords_b,
            collision_axis=np.array([1.0, 0.0, 0.0]),
        )
        assert report.displacement_applied <= 0.55
        assert report.micro_steps == 5


# ============================================================================
# 3. Tests for Counterpoise (CP) BSSE Constraint Injection
# ============================================================================


class TestCounterpoiseBSSEGenerator:
    """Verifies fragment tagging and Ghost atom (Bq / :) block generation for ORCA."""

    def test_generate_orca_fragment_tagged_xyz(self) -> None:
        """Confirms ORCA fragment tagged geometry format: Element(FragmentIndex) X Y Z."""
        symbols = ["O", "H", "H", "O", "H", "H"]
        coords = [
            [-1.5, 0.0, 0.0],
            [-1.8, 0.7, 0.0],
            [-0.6, 0.0, 0.0],
            [1.5, 0.0, 0.0],
            [1.8, 0.7, 0.0],
            [1.8, -0.7, 0.0],
        ]
        fragment_assignments = [1, 1, 1, 2, 2, 2]

        generator = CounterpoiseBSSEGenerator()
        tagged_xyz = generator.generate_fragment_tagged_xyz(
            symbols=symbols,
            coordinates=coords,
            fragment_assignments=fragment_assignments,
            charge=0,
            multiplicity=1,
        )

        assert "* xyz 0 1" in tagged_xyz
        assert "O(1)" in tagged_xyz
        assert "H(1)" in tagged_xyz
        assert "O(2)" in tagged_xyz
        assert "H(2)" in tagged_xyz
        assert tagged_xyz.strip().endswith("*")

    def test_generate_ghost_atom_blocks_for_monomer_a_and_b(self) -> None:
        """
        Confirms Ghost Atom (Bq / Element:) blocks for individual CP monomer calculations:
        - Monomer A in complex basis: Monomer A real, Monomer B ghost (e.g. O:, H: or Bq)
        - Monomer B in complex basis: Monomer B real, Monomer A ghost
        """
        symbols = ["O", "H", "H", "O", "H", "H"]
        coords = [
            [-1.5, 0.0, 0.0],
            [-1.8, 0.7, 0.0],
            [-0.6, 0.0, 0.0],
            [1.5, 0.0, 0.0],
            [1.8, 0.7, 0.0],
            [1.8, -0.7, 0.0],
        ]
        fragment_assignments = [1, 1, 1, 2, 2, 2]

        generator = CounterpoiseBSSEGenerator()
        bsse_cfg = generator.build_bsse_configuration(
            symbols=symbols,
            coordinates=coords,
            fragment_assignments=fragment_assignments,
        )

        assert isinstance(bsse_cfg, BSSEFragmentConfig)
        assert bsse_cfg.fragment_1_indices == [0, 1, 2]
        assert bsse_cfg.fragment_2_indices == [3, 4, 5]

        # Monomer A in full basis has Monomer B as ghost atoms
        monomer_a_basis_xyz = bsse_cfg.fragment_1_in_complex_basis_xyz
        assert "O " in monomer_a_basis_xyz or "O  " in monomer_a_basis_xyz
        assert "O: " in monomer_a_basis_xyz or "Bq" in monomer_a_basis_xyz or "O:" in monomer_a_basis_xyz

        # Monomer B in full basis has Monomer A as ghost atoms
        monomer_b_basis_xyz = bsse_cfg.fragment_2_in_complex_basis_xyz
        assert "O: " in monomer_b_basis_xyz or "Bq" in monomer_b_basis_xyz or "O:" in monomer_b_basis_xyz

    def test_orca_cp_input_block_generation(self) -> None:
        """Confirms ORCA %cp block and complete CP driver input strings."""
        symbols = ["O", "H", "H", "O", "H", "H"]
        coords = [
            [-1.5, 0.0, 0.0],
            [-1.8, 0.7, 0.0],
            [-0.6, 0.0, 0.0],
            [1.5, 0.0, 0.0],
            [1.8, 0.7, 0.0],
            [1.8, -0.7, 0.0],
        ]
        fragment_assignments = [1, 1, 1, 2, 2, 2]

        generator = CounterpoiseBSSEGenerator()
        orca_inp = generator.generate_orca_cp_input(
            symbols=symbols,
            coordinates=coords,
            fragment_assignments=fragment_assignments,
            method_str="! wB97M-V def2-QZVPP",
            charge=0,
            multiplicity=1,
        )

        assert "! wB97M-V def2-QZVPP" in orca_inp
        assert "* xyz 0 1" in orca_inp
        assert "O(1)" in orca_inp
        assert "O(2)" in orca_inp


# ============================================================================
# 4. Tests for Internal Coordinate Freezing
# ============================================================================


class TestInternalCoordinateFreezing:
    """Verifies generation of Cartesian constraint blocks (%geom Constraints) for ORCA."""

    def test_freeze_all_internal_monomer_coordinates(self) -> None:
        """
        Confirms generation of Cartesian constraints freezing internal atoms of each monomer,
        leaving 6 intermolecular degrees of freedom free to relax.
        """
        fragment_assignments = [1, 1, 1, 2, 2, 2]  # Water dimer, 6 atoms total

        freezer = InternalCoordinateFreezer()
        constraints_block = freezer.generate_cartesian_constraints_block(
            fragment_assignments=fragment_assignments,
            freeze_all_atoms=True,
        )

        assert "%geom" in constraints_block
        assert "Constraints" in constraints_block
        assert "end" in constraints_block
        # All 6 atoms should have Cartesian constraints { C <idx> C }
        for i in range(6):
            assert f"{{ C {i} C }}" in constraints_block

    def test_freeze_specific_monomer_only(self) -> None:
        """Confirms selective freezing of only Fragment 1 while Fragment 2 is fully unconstrained."""
        fragment_assignments = [1, 1, 1, 2, 2, 2]

        freezer = InternalCoordinateFreezer()
        constraints_block = freezer.generate_cartesian_constraints_block(
            fragment_assignments=fragment_assignments,
            frozen_fragments=[1],
        )

        for i in [0, 1, 2]:
            assert f"{{ C {i} C }}" in constraints_block
        for i in [3, 4, 5]:
            assert f"{{ C {i} C }}" not in constraints_block


# ============================================================================
# 5. Tests for Geometric Docking Engine
# ============================================================================


class TestGeometricDockingEngine:
    """Verifies systematic docking grids, rotation sampling, and assembly."""

    def test_dock_two_water_monomers_with_clash_resolution(self) -> None:
        """Docks two water monomers across orientation grids and verifies clash-free outputs."""
        frag_a = FragmentSource.from_coordinates(
            fragment_id="h2o_a",
            symbols=["O", "H", "H"],
            coordinates=[[0.0, 0.0, 0.1173], [0.0, 0.7572, -0.4692], [0.0, -0.7572, -0.4692]],
        )
        frag_b = FragmentSource.from_coordinates(
            fragment_id="h2o_b",
            symbols=["O", "H", "H"],
            coordinates=[[0.0, 0.0, 0.1173], [0.0, 0.7572, -0.4692], [0.0, -0.7572, -0.4692]],
        )

        engine = GeometricDockingEngine(
            radial_steps=3,
            angular_steps=4,
            base_distance=2.8,
            min_steric_distance=0.8,
        )
        candidates = engine.dock_monomers(frag_a, frag_b)

        assert len(candidates) > 0
        for cand in candidates:
            assert cand.num_atoms == 6
            assert cand.formula == "H4O2"
            assert cand.min_interatomic_distance >= 0.8
            assert len(cand.coordinates) == 6
            assert cand.fragment_assignments == [1, 1, 1, 2, 2, 2]
            assert "%geom" in cand.orca_cartesian_constraints_block
            assert "* xyz 0 1" in cand.orca_fragment_tagged_xyz

    def test_dock_monomers_using_original_collision_vector(self) -> None:
        """Reconstructs dimer along specific reference collision vector."""
        frag_a = FragmentSource.from_coordinates(
            fragment_id="co2",
            symbols=["C", "O", "O"],
            coordinates=[[0.0, 0.0, 0.0], [0.0, 0.0, 1.16], [0.0, 0.0, -1.16]],
        )
        frag_b = FragmentSource.from_coordinates(
            fragment_id="h2o",
            symbols=["O", "H", "H"],
            coordinates=[[0.0, 0.0, 0.0], [0.0, 0.76, 0.58], [0.0, -0.76, 0.58]],
        )

        reference_collision_vector = [0.0, 3.0, 0.0]
        engine = GeometricDockingEngine(min_steric_distance=0.8)
        candidate = engine.dock_single_vector(
            frag_a=frag_a,
            frag_b=frag_b,
            collision_vector=reference_collision_vector,
        )

        assert candidate.num_atoms == 6
        assert candidate.formula == "CH2O3"
        assert candidate.min_interatomic_distance >= 0.8
        # Monomer A should be centered near origin and Monomer B translated along Y axis
        com_b = np.mean(np.array(candidate.coordinates)[3:6], axis=0)
        assert com_b[1] == pytest.approx(3.0, abs=0.3)


# ============================================================================
# 6. Tests for ToposCombinatorialAssembler & HDF5 Memory Persistence
# ============================================================================


class TestToposCombinatorialAssembler:
    """Verifies end-to-end combinatorial basin pairing and HDF5 persistence."""

    def test_assemble_from_topology_and_hdf5(self, tmp_path: Path) -> None:
        """
        Simulates:
        1. Stage 1.1 cleaves a water dimer into 2 monomer seeds.
        2. Stage 2.0 optimizes monomers and writes basins to landscape.h5.
        3. Stage 3.0 retrieves monomer basins, docks them, and writes complex candidates.
        """
        db_path = tmp_path / "landscape.h5"
        memory_mgr = ToposHDF5MemoryManager(db_path=db_path)

        # 1. Write optimized monomer basins into HDF5
        monomer_a_record = GeometryRecord(
            geom_id="seed_0_basin_0",
            atomic_numbers=[8, 1, 1],
            coords=[
                [0.0, 0.0, 0.1173],
                [0.0, 0.7572, -0.4692],
                [0.0, -0.7572, -0.4692],
            ],
            energy=-76.4320,
            metadata={"fragment_index": 0, "formula": "H2O", "tier": "MACE-OFF24m"},
        )
        monomer_b_record = GeometryRecord(
            geom_id="seed_1_basin_0",
            atomic_numbers=[8, 1, 1],
            coords=[
                [0.0, 0.0, 0.1173],
                [0.0, 0.7572, -0.4692],
                [0.0, -0.7572, -0.4692],
            ],
            energy=-76.4318,
            metadata={"fragment_index": 1, "formula": "H2O", "tier": "MACE-OFF24m"},
        )
        memory_mgr.write_geometry(monomer_a_record)
        memory_mgr.write_geometry(monomer_b_record)

        # 2. Configure and run ToposCombinatorialAssembler
        config = AssemblyConfig(
            min_steric_distance=0.8,
            micro_displacement_step=0.1,
            radial_sampling_steps=2,
            angular_sampling_steps=3,
            base_docking_distance=3.0,
            freeze_internal_monomers=True,
            save_to_hdf5=True,
            db_path=db_path,
        )

        assembler = ToposCombinatorialAssembler(config=config, memory_mgr=memory_mgr)
        report = assembler.assemble_monomer_basins(
            monomer_basin_ids_group_a=["seed_0_basin_0"],
            monomer_basin_ids_group_b=["seed_1_basin_0"],
            reference_collision_vector=[0.0, 0.0, 3.2],
        )

        assert isinstance(report, AssemblySessionReport)
        assert report.total_candidates_generated > 0
        assert report.clash_free_count == report.total_candidates_generated
        assert len(report.candidates) > 0

        # Verify first assembled complex
        best_complex = report.candidates[0]
        assert best_complex.num_atoms == 6
        assert best_complex.formula == "H4O2"
        assert best_complex.min_interatomic_distance >= 0.8
        assert best_complex.bsse_config is not None
        assert "* xyz 0 1" in best_complex.orca_fragment_tagged_xyz
        assert "%geom" in best_complex.orca_cartesian_constraints_block

        # 3. Verify written to HDF5
        saved_geoms = memory_mgr.list_geometries()
        assert any(best_complex.complex_id in gid for gid in saved_geoms)
        loaded_complex = memory_mgr.read_geometry(best_complex.complex_id)
        assert loaded_complex is not None
        assert len(loaded_complex.coords) == 6
        assert loaded_complex.atomic_numbers == [8, 1, 1, 8, 1, 1]

    def test_convenience_assemble_weak_complex_function(self) -> None:
        """Tests one-line convenience function assemble_weak_complex."""
        symbols = ["O", "H", "H", "O", "H", "H"]
        coordinates = [
            [-1.5, 0.0, 0.0],
            [-1.8, 0.7, 0.0],
            [-0.6, 0.0, 0.0],
            [1.5, 0.0, 0.0],
            [1.8, 0.7, 0.0],
            [1.8, -0.7, 0.0],
        ]
        candidates = assemble_weak_complex(
            symbols=symbols,
            coordinates=coordinates,
            base_distance=2.9,
            min_steric_distance=0.8,
        )

        assert len(candidates) > 0
        cand = candidates[0]
        assert cand.num_atoms == 6
        assert cand.min_interatomic_distance >= 0.8
        assert cand.bsse_config is not None

    def test_formic_acid_dimer_assembly(self) -> None:
        """Tests assembly of hydrogen-bonded formic acid dimer ((HCOOH)2)."""
        symbols = [
            "C", "O", "O", "H", "H",
            "C", "O", "O", "H", "H",
        ]
        coordinates = [
            [-1.34,  0.13,  0.00],
            [-1.25,  1.32,  0.00],
            [-2.39, -0.66,  0.00],
            [-0.38, -0.42,  0.00],
            [-2.23, -1.61,  0.00],
            [ 1.34, -0.13,  0.00],
            [ 1.25, -1.32,  0.00],
            [ 2.39,  0.66,  0.00],
            [ 0.38,  0.42,  0.00],
            [ 2.23,  1.61,  0.00],
        ]
        candidates = assemble_weak_complex(
            symbols=symbols,
            coordinates=coordinates,
            base_distance=3.5,
            min_steric_distance=0.8,
        )
        assert len(candidates) > 0
        cand = candidates[0]
        assert cand.num_atoms == 10
        assert cand.formula == "C2H4O4"
        assert cand.min_interatomic_distance >= 0.8
        assert cand.fragment_assignments == [1, 1, 1, 1, 1, 2, 2, 2, 2, 2]

    def test_argon_hf_van_der_waals_complex_assembly(self) -> None:
        """Tests assembly of noble gas vdW complex Ar...HF."""
        symbols = ["Ar", "H", "F"]
        coordinates = [
            [0.0, 0.0, -2.0],
            [0.0, 0.0,  1.0],
            [0.0, 0.0,  1.92],
        ]
        candidates = assemble_weak_complex(
            symbols=symbols,
            coordinates=coordinates,
            base_distance=3.0,
            min_steric_distance=0.8,
        )
        assert len(candidates) > 0
        cand = candidates[0]
        assert cand.num_atoms == 3
        assert cand.formula in ("ArFH", "ArHF", "FArH", "HArF")
        assert cand.min_interatomic_distance >= 0.8

    def test_open_shell_radical_counterpoise_block(self) -> None:
        """Tests CP BSSE block generation for an open-shell doublet complex (e.g. OH radical + H2O)."""
        symbols = ["O", "H", "O", "H", "H"]
        coordinates = [
            [-1.5, 0.0, 0.0],
            [-0.6, 0.0, 0.0],
            [ 1.5, 0.0, 0.0],
            [ 1.8, 0.7, 0.0],
            [ 1.8, -0.7, 0.0],
        ]
        fragment_assignments = [1, 1, 2, 2, 2]
        generator = CounterpoiseBSSEGenerator()
        orca_inp = generator.generate_orca_cp_input(
            symbols=symbols,
            coordinates=coordinates,
            fragment_assignments=fragment_assignments,
            charge=0,
            multiplicity=2,  # Doublet
        )
        assert "* xyz 0 2" in orca_inp
        assert "O(1)" in orca_inp
        assert "O(2)" in orca_inp

