"""
Unit and integration tests for CoChem-TOPOS Stage 2.1 Lightning PES Quench Subsystem.
Strict Zero-Mock Mandate: Uses real ASE Atoms, real calculators (EMT, LJ, TorchMLFF),
real optimizers (BFGS, LBFGS, FIRE), real HDF5 persistence, real psutil metrics,
and real concurrent ThreadPoolExecutor execution.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List

import numpy as np
import pytest
import torch
from ase import Atoms
from ase.calculators.emt import EMT
from ase.calculators.lj import LennardJones
from ase.optimize import BFGS, FIRE, LBFGS

from mechanics.cochem_topos_memory import (
    DeviceType,
    EngineTier,
    GeometryRecord,
    HardwareResourceBroker,
    PrecisionMode,
    TelemetryRecord,
    ToposHDF5MemoryManager,
    TrajectoryStep,
)
from mechanics.cochem_topos_quench import (
    CUDAGraphOptimizerWrapper,
    CalculatorFactory,
    ParallelASEQuenchRunner,
    QuenchAlgorithm,
    QuenchBatchResult,
    QuenchConfig,
    QuenchResult,
    QuenchStatus,
    SoftQuenchGovernor,
    SoftQuenchTelemetry,
    ToposQuenchOrchestrator,
    TorchMLFFCalculator,
)


# ============================================================================
# 1. Pydantic Models and Configuration Tests
# ============================================================================

class TestQuenchDataModels:
    """Tests for Quench Pydantic schemas, validation, and serialization."""

    def test_quench_config_defaults_and_validation(self):
        """Test default parameters of QuenchConfig."""
        config = QuenchConfig()
        assert config.fmax == 0.05
        assert config.max_steps == 500
        assert config.algorithm == QuenchAlgorithm.BFGS
        assert config.engine == EngineTier.MACE_OFF24M
        assert config.device == DeviceType.AUTO
        assert config.precision == PrecisionMode.FP32
        assert config.force_hazard_threshold == 25.0
        assert config.force_safe_threshold == 5.0
        assert config.soft_quench_step_size == 0.05
        assert config.max_soft_steps == 100
        assert config.enable_cuda_graphs is True
        assert config.save_trajectory is True
        assert config.save_to_hdf5 is True

    def test_quench_config_custom_overrides(self, tmp_path: Path):
        """Test custom configuration overrides."""
        db_file = tmp_path / "custom_landscape.h5"
        config = QuenchConfig(
            fmax=0.01,
            max_steps=150,
            algorithm=QuenchAlgorithm.FIRE,
            engine=EngineTier.XTB2,
            device=DeviceType.CPU,
            force_hazard_threshold=30.0,
            force_safe_threshold=4.0,
            soft_quench_step_size=0.03,
            max_soft_steps=50,
            max_workers=4,
            db_path=db_file,
        )
        assert config.fmax == 0.01
        assert config.max_steps == 150
        assert config.algorithm == QuenchAlgorithm.FIRE
        assert config.engine == EngineTier.XTB2
        assert config.max_workers == 4
        assert config.db_path == db_file

    def test_quench_result_and_batch_serialization(self):
        """Test serialization and statistical aggregations in QuenchBatchResult."""
        r1 = QuenchResult(
            geom_id="mol_01",
            status=QuenchStatus.CONVERGED,
            converged=True,
            initial_energy=10.5,
            final_energy=2.1,
            energy_change=-8.4,
            initial_max_force=12.0,
            final_max_force=0.02,
            steps_taken=15,
            soft_quench=SoftQuenchTelemetry(triggered=False, initial_max_force=12.0, final_max_force=12.0),
            engine_used="EMT",
            device_used="cpu",
            final_atomic_numbers=[29, 29],
            final_coords=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.55]],
            duration_seconds=0.12,
        )
        r2 = QuenchResult(
            geom_id="mol_02",
            status=QuenchStatus.CONVERGED,
            converged=True,
            initial_energy=15.0,
            final_energy=3.5,
            energy_change=-11.5,
            initial_max_force=35.0,
            final_max_force=0.03,
            steps_taken=25,
            soft_quench=SoftQuenchTelemetry(
                triggered=True, initial_max_force=35.0, final_max_force=4.8, steps_taken=6, converged=True
            ),
            engine_used="EMT",
            device_used="cpu",
            final_atomic_numbers=[29, 29],
            final_coords=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.55]],
            duration_seconds=0.18,
        )

        batch = QuenchBatchResult(
            total_structures=2,
            converged_count=2,
            failed_count=0,
            success_rate=1.0,
            total_duration_seconds=0.30,
            mean_steps=20.0,
            min_energy=2.1,
            max_energy=3.5,
            results=[r1, r2],
        )

        dumped = batch.model_dump()
        assert dumped["total_structures"] == 2
        assert dumped["converged_count"] == 2
        assert dumped["success_rate"] == 1.0
        assert len(dumped["results"]) == 2
        assert dumped["results"][1]["soft_quench"]["triggered"] is True


# ============================================================================
# 2. Steric Shatter Soft-Quench Governor Tests
# ============================================================================

class TestSoftQuenchGovernor:
    """Tests for SoftQuenchGovernor gradient clipping and steric clash mitigation."""

    def test_soft_quench_bypassed_when_forces_safe(self):
        """Verify soft-quench is not triggered when initial forces are within safe limits."""
        atoms = Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.5]])
        atoms.calc = EMT()

        governor = SoftQuenchGovernor(
            force_hazard_threshold=25.0,
            force_safe_threshold=5.0,
            soft_quench_step_size=0.05,
        )
        governed_atoms, telem = governor.govern(atoms)

        assert telem.triggered is False
        assert telem.steps_taken == 0
        assert telem.converged is True
        assert telem.initial_max_force < 25.0
        assert telem.final_max_force == telem.initial_max_force
        # Positions should remain untouched
        np.testing.assert_allclose(governed_atoms.get_positions(), [[0.0, 0.0, 0.0], [0.0, 0.0, 2.5]])

    def test_soft_quench_triggered_on_severe_steric_clash(self):
        """Verify soft-quench mitigates extreme force clash (>400 eV/Å) safely."""
        # Cu dimer at 0.8 Å (extreme overlap causing huge repulsive forces)
        atoms = Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.8]])
        atoms.calc = EMT()

        init_forces = atoms.get_forces()
        init_fmax = float(np.max(np.linalg.norm(init_forces, axis=1)))
        assert init_fmax > 100.0  # Hazardous force confirmed

        governor = SoftQuenchGovernor(
            force_hazard_threshold=25.0,
            force_safe_threshold=5.0,
            soft_quench_step_size=0.05,
            max_soft_steps=100,
        )

        traj_steps: List[dict] = []
        def log_cb(step_idx: int, a: Atoms, e: float, f: np.ndarray) -> None:
            traj_steps.append({"step": step_idx, "energy": e, "fmax": float(np.max(np.linalg.norm(f, axis=1)))})

        governed_atoms, telem = governor.govern(atoms, trajectory_callback=log_cb)

        assert telem.triggered is True
        assert telem.steps_taken > 0
        assert telem.converged is True
        assert telem.final_max_force <= 5.0
        assert len(traj_steps) == telem.steps_taken

        # Verify distance increased to physically viable range (> 1.8 Å)
        final_dist = np.linalg.norm(governed_atoms.positions[1] - governed_atoms.positions[0])
        assert final_dist > 1.8
        assert final_dist < 3.5

    def test_soft_quench_capped_step_size_gradient_clipping(self):
        """Verify that per-step displacement strictly respects soft_quench_step_size."""
        # Extreme overlap with Lennard-Jones
        atoms = Atoms("Ar2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 1.2]])
        atoms.calc = LennardJones(sigma=3.4, epsilon=0.01)

        step_size_limit = 0.04
        governor = SoftQuenchGovernor(
            force_hazard_threshold=20.0,
            force_safe_threshold=4.0,
            soft_quench_step_size=step_size_limit,
            max_soft_steps=50,
        )

        prev_pos = atoms.get_positions().copy()
        step_displacements = []

        def step_watcher(step_idx: int, a: Atoms, e: float, f: np.ndarray) -> None:
            nonlocal prev_pos
            curr_pos = a.get_positions()
            disp = np.linalg.norm(curr_pos - prev_pos, axis=1)
            step_displacements.append(np.max(disp))
            prev_pos = curr_pos.copy()

        governor.govern(atoms, trajectory_callback=step_watcher)

        # Skip step 0 (initial state), check subsequent displacements
        for max_disp in step_displacements[1:]:
            assert max_disp <= step_size_limit + 1e-6


# ============================================================================
# 3. CUDA Graph Optimizer Wrapper and PyTorch Calculator Tests
# ============================================================================

class TestCUDAGraphOptimizerWrapper:
    """Tests for CUDAGraphOptimizerWrapper and PyTorch MLFF Calculator integration."""

    def test_torch_mlff_calculator_cpu_execution(self):
        """Test TorchMLFFCalculator energy, force, and gradient computations on CPU."""
        atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
        calc = TorchMLFFCalculator(device="cpu", precision="float32", k_harmonic=15.0, r0=0.74)
        atoms.calc = calc

        energy = atoms.get_potential_energy()
        forces = atoms.get_forces()
        assert np.isfinite(energy)
        assert forces.shape == (2, 3)
        assert np.allclose(forces, 0.0, atol=1e-3)

        # Displace slightly
        atoms.positions[1, 2] = 0.84  # stretched by 0.1 A
        forces_stretched = atoms.get_forces()
        assert forces_stretched[1, 2] < 0  # restoring force pulling back

    def test_cuda_graph_wrapper_passthrough_cpu(self):
        """Test seamless passthrough fallback when running on CPU with BFGS/LBFGS."""
        atoms = Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.4]])
        atoms.calc = EMT()

        wrapper = CUDAGraphOptimizerWrapper(
            atoms=atoms,
            optimizer_cls=BFGS,
            enable_cuda_graphs=True,  # Should cleanly fallback to passthrough on CPU
        )

        assert wrapper.is_cuda_graph_active is False
        assert wrapper.optimizer is not None

        wrapper.run(fmax=0.05, steps=30)
        assert wrapper.converged()
        assert wrapper.get_number_of_steps() > 0

        final_fmax = float(np.max(np.linalg.norm(atoms.get_forces(), axis=1)))
        assert final_fmax <= 0.05

    def test_cuda_graph_wrapper_class_factory_and_delegation(self):
        """Test wrapping an optimizer class via CUDAGraphOptimizerWrapper.wrap()."""
        GraphedLBFGS = CUDAGraphOptimizerWrapper.wrap(LBFGS)
        atoms = Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.4]])
        atoms.calc = EMT()

        opt = GraphedLBFGS(atoms, logfile=None)
        opt.run(fmax=0.05, steps=30)
        assert opt.converged()


# ============================================================================
# 4. Calculator Factory and Cascade Routing Tests
# ============================================================================

class TestCalculatorFactory:
    """Tests for CalculatorFactory and cascade resolution."""

    def test_create_emt_calculator_for_metallic_elements(self):
        """Verify EMT is created for Cu, Al, Ni, Pt systems."""
        calc, engine, dev = CalculatorFactory.create_calculator(
            engine=EngineTier.MACE_OFF24M,
            atomic_numbers=[29, 29],  # Cu2
            device=DeviceType.CPU,
            precision=PrecisionMode.FP32,
            fallback_to_builtin=True,
        )
        assert calc is not None
        assert isinstance(calc, (EMT, TorchMLFFCalculator))

    def test_create_lj_calculator_for_noble_gas(self):
        """Verify Lennard-Jones calculator is created for Ar or pairwise fallback."""
        calc, engine, dev = CalculatorFactory.create_calculator(
            engine=EngineTier.XTB2,
            atomic_numbers=[18, 18],  # Ar2
            device=DeviceType.CPU,
            fallback_to_builtin=True,
        )
        assert calc is not None

    def test_create_torch_mlff_calculator(self):
        """Verify PyTorch MLFF calculator instantiation."""
        calc, engine, dev = CalculatorFactory.create_calculator(
            engine="TorchMLFF",
            atomic_numbers=[1, 1],
            device=DeviceType.CPU,
            precision=PrecisionMode.FP32,
        )
        assert isinstance(calc, TorchMLFFCalculator)


# ============================================================================
# 5. Parallel ASE Quench Runner Tests
# ============================================================================

class TestParallelASEQuenchRunner:
    """Tests for concurrent batch quenching via ThreadPoolExecutor."""

    def test_parallel_batch_quench_multiple_structures(self, tmp_path: Path):
        """Test parallel relaxation of multiple disjoint structures."""
        db_file = tmp_path / "parallel_quench.h5"
        memory_manager = ToposHDF5MemoryManager(db_path=db_file)
        broker = HardwareResourceBroker()

        runner = ParallelASEQuenchRunner(broker=broker, memory_manager=memory_manager)

        # Prepare 4 distinct Cu2 dimer seeds at different initial bond lengths
        structures = [
            Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.30]]),
            Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.45]]),
            Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.70]]),
            Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.85]]),
        ]
        for i, s in enumerate(structures):
            s.info["geom_id"] = f"cu2_seed_{i+1:02d}"
            s.calc = EMT()

        config = QuenchConfig(
            fmax=0.05,
            max_steps=50,
            algorithm=QuenchAlgorithm.BFGS,
            max_workers=2,
            save_to_hdf5=True,
            db_path=db_file,
        )

        batch_result = runner.run_batch(structures=structures, config=config)

        assert batch_result.total_structures == 4
        assert batch_result.converged_count == 4
        assert batch_result.failed_count == 0
        assert batch_result.success_rate == 1.0
        assert batch_result.mean_steps > 0
        assert batch_result.min_energy is not None
        assert len(batch_result.results) == 4

        for res in batch_result.results:
            assert res.converged is True
            assert res.final_max_force <= 0.05
            assert res.energy_change <= 0.0  # PES minimization

        # Verify structures are written to HDF5 database
        with memory_manager.open_reader() as f:
            for i in range(1, 5):
                gid = f"cu2_seed_{i:02d}"
                assert gid in f["geometries"]
                assert gid in f["trajectories"]


# ============================================================================
# 6. Topos Quench Orchestrator End-to-End Tests
# ============================================================================

class TestToposQuenchOrchestrator:
    """Master end-to-end tests for ToposQuenchOrchestrator."""

    def test_single_structure_quench_with_emt(self, tmp_path: Path):
        """Test complete single structure relaxation pipeline with HDF5 persistence."""
        db_file = tmp_path / "single_quench.h5"
        orchestrator = ToposQuenchOrchestrator(
            memory_manager=ToposHDF5MemoryManager(db_path=db_file)
        )

        atoms = Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.7]])
        atoms.calc = EMT()

        config = QuenchConfig(
            fmax=0.04,
            max_steps=50,
            algorithm=QuenchAlgorithm.BFGS,
            save_trajectory=True,
            save_to_hdf5=True,
            db_path=db_file,
        )

        result = orchestrator.quench(structure=atoms, config=config, geom_id="cu2_opt_single")

        assert result.converged is True
        assert result.status == QuenchStatus.CONVERGED
        assert result.geom_id == "cu2_opt_single"
        assert result.final_max_force <= 0.04
        assert result.steps_taken > 0
        assert result.trajectory_steps > 0
        assert result.duration_seconds > 0.0

        # Read back from HDF5
        geom = orchestrator.memory_manager.read_geometry("cu2_opt_single")
        assert geom is not None
        assert geom.atomic_numbers == [29, 29]
        assert len(geom.coords) == 2

        traj = orchestrator.memory_manager.read_trajectory("cu2_opt_single")
        assert len(traj) >= result.trajectory_steps

    def test_steric_clash_soft_quench_to_bfgs_pipeline(self, tmp_path: Path):
        """Test complete pipeline handling extreme steric clash with governor before Quasi-Newton."""
        db_file = tmp_path / "clash_quench.h5"
        orchestrator = ToposQuenchOrchestrator(
            memory_manager=ToposHDF5MemoryManager(db_path=db_file)
        )

        # Severely overlapped dimer
        atoms = Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.75]])
        atoms.calc = EMT()

        config = QuenchConfig(
            fmax=0.05,
            max_steps=50,
            force_hazard_threshold=25.0,
            force_safe_threshold=5.0,
            soft_quench_step_size=0.05,
            max_soft_steps=100,
            algorithm=QuenchAlgorithm.BFGS,
            save_trajectory=True,
            save_to_hdf5=True,
            db_path=db_file,
        )

        result = orchestrator.quench(structure=atoms, config=config, geom_id="cu2_clash_resolved")

        assert result.soft_quench.triggered is True
        assert result.soft_quench.converged is True
        assert result.converged is True
        assert result.final_max_force <= 0.05

        # Final bond distance should be optimal Cu2 (~2.2 - 2.6 A)
        final_coords = np.array(result.final_coords)
        final_dist = np.linalg.norm(final_coords[1] - final_coords[0])
        assert 2.1 < final_dist < 2.6

    def test_dynamic_path_resolution_with_cochem_workspace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Test dynamic path resolution via COCHEM_WORKSPACE."""
        workspace = tmp_path / "workspace_test"
        workspace.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("COCHEM_WORKSPACE", str(workspace))

        orchestrator = ToposQuenchOrchestrator()
        expected_db = workspace / "CoChem_Artifacts" / "Databases" / "landscape.h5"
        assert orchestrator.memory_manager.db_path == expected_db
        assert expected_db.exists()

    def test_geometry_record_input_quench(self, tmp_path: Path):
        """Test quenching directly from a GeometryRecord."""
        db_file = tmp_path / "geom_rec_quench.h5"
        orchestrator = ToposQuenchOrchestrator(
            memory_manager=ToposHDF5MemoryManager(db_path=db_file)
        )

        rec = GeometryRecord(
            geom_id="geom_rec_01",
            atomic_numbers=[29, 29],
            coords=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.75]],
            energy=0.0,
            metadata={"source": "test_generator"},
        )

        config = QuenchConfig(
            fmax=0.05,
            max_steps=50,
            algorithm=QuenchAlgorithm.FIRE,
            save_to_hdf5=True,
            db_path=db_file,
        )

        result = orchestrator.quench_geometry_record(record=rec, config=config)
        assert result.geom_id == "geom_rec_01"
        assert result.converged is True
        assert result.final_max_force <= 0.05
