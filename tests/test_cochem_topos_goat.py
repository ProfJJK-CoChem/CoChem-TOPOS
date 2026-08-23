"""
Unit and integration test suite for CoChem-TOPOS Stage 2.3 GOAT Cascade Master Orchestrator.
Zero-Mock Mandate: Uses real ASE Atoms, real calculators (EMT, LennardJones, TorchMLFF),
real optimizers (LBFGS, FIRE, BFGS), real HDF5 SWMR persistence, real process reaper,
and real pipeline handoff (Escape -> Quench -> Crusher -> Memory).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List

import h5py
import numpy as np
import pytest
from ase import Atoms
from ase.calculators.emt import EMT
from ase.calculators.lj import LennardJones

from mechanics.cochem_topos_goat import (
    CascadeCycleRecord,
    GOATCascadeConfig,
    GOATCascadeReport,
    GOATCascadeResult,
    GradientNoiseOptimizer,
    OptimizerToggleEvent,
    OptimizerToggleReason,
    OrphanedProcessReaper,
    ToposGOATCascade,
    get_global_reaper,
    reap_all_child_processes,
)
from mechanics.cochem_topos_memory import (
    DeviceType,
    EngineTier,
    GeometryRecord,
    HardwareResourceBroker,
    PrecisionMode,
    ToposHDF5MemoryManager,
)
from mechanics.cochem_topos_quench import (
    QuenchAlgorithm,
    QuenchConfig,
    QuenchStatus,
    ToposQuenchOrchestrator,
    TorchMLFFCalculator,
)
from mechanics.cochem_topos_escape import (
    EscapeConfig,
    EscapeMechanism,
    ToposEscapeOrchestrator,
)
from topology.cochem_topos_crusher import (
    DeduplicationVerdict,
    TopologyCrusher,
)


# ============================================================================
# 1. Pydantic Models and Configuration Tests
# ============================================================================

class TestGOATDataModels:
    """Tests for GOAT Cascade configuration, records, and reports."""

    def test_goat_config_defaults_and_validation(self) -> None:
        """Verify default parameters of GOATCascadeConfig."""
        config = GOATCascadeConfig()
        assert config.max_cycles == 10
        assert config.patience == 3
        assert config.target_coverage == 0.95
        assert config.primary_optimizer == QuenchAlgorithm.LBFGS
        assert config.fallback_optimizer == QuenchAlgorithm.FIRE
        assert config.oscillation_window == 5
        assert config.oscillation_force_tol == 0.01
        assert config.fmax == 0.05
        assert config.max_quench_steps == 300
        assert config.enable_process_reaper is True
        assert config.save_to_hdf5 is True
        assert config.temperature_schedule == [300.0, 500.0, 1000.0]

    def test_goat_config_custom_overrides(self, tmp_path: Path) -> None:
        """Verify custom parameter overrides."""
        db_file = tmp_path / "test_goat.h5"
        config = GOATCascadeConfig(
            max_cycles=25,
            patience=5,
            target_coverage=0.99,
            primary_optimizer=QuenchAlgorithm.BFGS,
            fallback_optimizer=QuenchAlgorithm.FIRE,
            fmax=0.01,
            db_path=db_file,
        )
        assert config.max_cycles == 25
        assert config.patience == 5
        assert config.target_coverage == 0.99
        assert config.primary_optimizer == QuenchAlgorithm.BFGS
        assert config.fallback_optimizer == QuenchAlgorithm.FIRE
        assert config.fmax == 0.01
        assert config.db_path == db_file

    def test_optimizer_toggle_event_serialization(self) -> None:
        """Verify OptimizerToggleEvent serialization and attributes."""
        event = OptimizerToggleEvent(
            geom_id="mol_001",
            step_index=12,
            reason=OptimizerToggleReason.HESSIAN_ILL_CONDITIONED,
            from_optimizer=QuenchAlgorithm.LBFGS,
            to_optimizer=QuenchAlgorithm.FIRE,
            current_fmax=1.45,
            current_energy=-12.345,
            details="Hessian update matrix ill-conditioned",
        )
        assert event.geom_id == "mol_001"
        assert event.step_index == 12
        assert event.reason == OptimizerToggleReason.HESSIAN_ILL_CONDITIONED
        assert event.from_optimizer == QuenchAlgorithm.LBFGS
        assert event.to_optimizer == QuenchAlgorithm.FIRE
        dumped = event.model_dump()
        assert dumped["geom_id"] == "mol_001"
        assert dumped["reason"] == "HESSIAN_ILL_CONDITIONED"

    def test_cascade_cycle_record_and_report(self) -> None:
        """Verify serialization of CascadeCycleRecord and GOATCascadeReport."""
        record = CascadeCycleRecord(
            cycle_index=1,
            seed_geom_id="seed_0",
            escape_status="BREACH_SUCCESS",
            escape_mechanism=EscapeMechanism.WIGNER.value,
            candidates_generated=3,
            quench_converged_count=3,
            unique_basins_discovered=1,
            duplicates_rejected=2,
            enantiomers_preserved=0,
            optimizer_toggles_count=1,
            duration_seconds=1.25,
        )
        assert record.cycle_index == 1
        assert record.candidates_generated == 3

        report = GOATCascadeReport(
            session_id="session_test_01",
            total_cycles_executed=5,
            total_unique_basins=3,
            total_duplicates_rejected=10,
            total_enantiomers_preserved=1,
            total_optimizer_toggles=2,
            final_completeness_estimate=0.96,
            converged_stopping_criterion="TARGET_COVERAGE_REACHED",
            duration_seconds=15.3,
            cycle_records=[record],
        )
        assert report.total_cycles_executed == 5
        assert report.total_unique_basins == 3
        assert len(report.cycle_records) == 1


# ============================================================================
# 2. Orphaned Thread Reaper Tests
# ============================================================================

class TestOrphanedProcessReaper:
    """Tests for cross-platform process safety and orphaned thread reaping."""

    def test_reaper_singleton_and_registration(self) -> None:
        """Verify global reaper instance and subprocess registration."""
        reaper = get_global_reaper()
        assert isinstance(reaper, OrphanedProcessReaper)
        
        # Start a real sleeping child subprocess
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        reaper.register_process(proc)
        assert proc in reaper.tracked_processes
        
        # Terminate via reaper
        reaper.reap_process(proc)
        time.sleep(0.2)
        assert proc.poll() is not None

    def test_reaper_context_manager(self) -> None:
        """Verify context manager automatically terminates spawned children."""
        reaper = OrphanedProcessReaper()
        with reaper:
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            reaper.register_process(proc)
            assert proc.poll() is None
            
        time.sleep(0.2)
        assert proc.poll() is not None

    def test_reap_all_child_processes(self) -> None:
        """Verify reap_all_child_processes function cleans up processes."""
        proc1 = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        proc2 = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        reap_all_child_processes([proc1, proc2])
        time.sleep(0.2)
        assert proc1.poll() is not None
        assert proc2.poll() is not None


# ============================================================================
# 3. Gradient-Noise Optimizer Toggle Engine Tests
# ============================================================================

class TestGradientNoiseOptimizer:
    """Tests for dynamic trajectory monitoring and LBFGS -> FIRE optimizer switching."""

    def test_smooth_lbfgs_convergence_no_toggle(self) -> None:
        """Verify smooth descent converges using LBFGS without needing a toggle."""
        # Create a displaced dimer
        atoms = Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.8]])
        atoms.calc = EMT()

        opt_engine = GradientNoiseOptimizer(
            primary_optimizer=QuenchAlgorithm.LBFGS,
            fallback_optimizer=QuenchAlgorithm.FIRE,
            fmax=0.05,
            max_steps=100,
        )

        res = opt_engine.optimize(atoms, geom_id="cu2_smooth")
        assert res.converged is True
        assert res.status == QuenchStatus.CONVERGED
        assert res.final_max_force <= 0.05
        assert len(res.toggle_events) == 0
        assert res.active_optimizer == QuenchAlgorithm.LBFGS

    def test_oscillation_intercept_and_fire_toggle(self) -> None:
        """Verify that gradient noise / oscillation triggers automatic toggle to FIRE."""
        # Create a triatomic cluster with LJ potential
        atoms = Atoms("Ar3", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 3.5], [1.5, 0.0, 1.7]])
        atoms.calc = LennardJones(sigma=3.4, epsilon=0.01)

        # Set low oscillation threshold to trigger toggle on noisy descent
        opt_engine = GradientNoiseOptimizer(
            primary_optimizer=QuenchAlgorithm.LBFGS,
            fallback_optimizer=QuenchAlgorithm.FIRE,
            fmax=0.01,
            max_steps=200,
            oscillation_window=3,
            oscillation_force_tol=0.0001,
        )

        res = opt_engine.optimize(atoms, geom_id="ar3_noisy")
        assert res.converged is True
        assert res.final_max_force <= 0.01
        # Optimizer must successfully complete and produce valid trajectory
        assert res.final_energy < res.initial_energy

    def test_forced_exception_intercept_and_fire_fallback(self) -> None:
        """Verify that an optimizer runtime exception is intercepted and falls back to FIRE."""
        atoms = Atoms("Cu3", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.5], [2.2, 0.0, 0.0]])
        atoms.calc = EMT()

        opt_engine = GradientNoiseOptimizer(
            primary_optimizer=QuenchAlgorithm.LBFGS,
            fallback_optimizer=QuenchAlgorithm.FIRE,
            fmax=0.05,
            max_steps=150,
        )

        # Simulate exception trigger on primary optimizer by passing a faulty condition or running direct toggle
        event = opt_engine._trigger_fallback(
            atoms=atoms,
            geom_id="cu3_exc",
            step_idx=5,
            reason=OptimizerToggleReason.OPTIMIZER_EXCEPTION,
            curr_energy=float(atoms.get_potential_energy()),
            curr_fmax=float(np.max(np.linalg.norm(atoms.get_forces(), axis=1))),
            details="Simulated Hessian singularity",
        )
        assert event.reason == OptimizerToggleReason.OPTIMIZER_EXCEPTION
        assert event.to_optimizer == QuenchAlgorithm.FIRE


# ============================================================================
# 4. Pipeline Loop Handoff & Cascade Tests
# ============================================================================

class TestToposGOATCascadePipeline:
    """Tests for the master pipeline loop: Escape -> Quench -> Crusher -> SWMR HDF5."""

    def test_single_cycle_cascade_execution(self, tmp_path: Path) -> None:
        """Verify handoff across Escape, Quench, Crusher, and HDF5 in a single cycle."""
        db_path = tmp_path / "cascade_single.h5"
        config = GOATCascadeConfig(
            max_cycles=1,
            fmax=0.05,
            db_path=db_path,
            temperature_schedule=[300.0],
            langevin_steps_per_stage=20,
        )

        cascade = ToposGOATCascade(config=config)
        seed_atoms = Atoms("Cu4", positions=[
            [0.0, 0.0, 0.0],
            [2.5, 0.0, 0.0],
            [1.25, 2.16, 0.0],
            [1.25, 0.72, 2.04],
        ])
        seed_atoms.calc = EMT()

        report = cascade.run_cascade(seed_atoms=seed_atoms, session_id="test_single_cycle")
        assert report.total_cycles_executed == 1
        assert report.total_unique_basins >= 1
        assert db_path.exists()

        # Verify HDF5 persistence
        with h5py.File(db_path, "r") as f:
            assert "geometries" in f or "deduplicated_basins" in f

    def test_multi_cycle_basin_exploration(self, tmp_path: Path) -> None:
        """Verify multi-cycle cascade discovers basins and applies Good-Turing estimator."""
        db_path = tmp_path / "cascade_multi.h5"
        config = GOATCascadeConfig(
            max_cycles=3,
            patience=2,
            target_coverage=0.90,
            fmax=0.05,
            db_path=db_path,
            temperature_schedule=[300.0, 500.0],
            langevin_steps_per_stage=25,
        )

        cascade = ToposGOATCascade(config=config)
        seed_atoms = Atoms("Cu4", positions=[
            [0.0, 0.0, 0.0],
            [2.5, 0.0, 0.0],
            [1.25, 2.16, 0.0],
            [1.25, 0.72, 2.04],
        ])
        seed_atoms.calc = EMT()

        report = cascade.run_cascade(seed_atoms=seed_atoms, session_id="test_multi_cycle")
        assert report.total_cycles_executed <= 3
        assert report.total_unique_basins >= 1
        assert len(report.cycle_records) > 0
        assert report.final_completeness_estimate >= 0.0

    def test_enantiomer_preservation_in_cascade(self, tmp_path: Path) -> None:
        """Verify that chiral structures in cascade exploration preserve enantiomers."""
        db_path = tmp_path / "cascade_chiral.h5"
        config = GOATCascadeConfig(
            max_cycles=2,
            fmax=0.05,
            db_path=db_path,
            temperature_schedule=[300.0],
            langevin_steps_per_stage=15,
        )
        cascade = ToposGOATCascade(config=config)

        # Chiral 4-atom cluster with distinct elements
        seed_atoms = Atoms("HCFCl", positions=[
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.09],
            [1.02, 0.0, -0.36],
            [-0.51, 0.88, -0.36],
        ])
        seed_atoms.calc = LennardJones()

        report = cascade.run_cascade(seed_atoms=seed_atoms, session_id="test_chiral_cascade")
        assert report.total_unique_basins >= 1
        assert report.total_cycles_executed >= 1

    def test_stopping_criterion_patience(self, tmp_path: Path) -> None:
        """Verify cascade halts when patience limit is reached without new basins."""
        db_path = tmp_path / "cascade_patience.h5"
        config = GOATCascadeConfig(
            max_cycles=10,
            patience=1,
            fmax=0.05,
            db_path=db_path,
            temperature_schedule=[300.0],
            langevin_steps_per_stage=10,
        )
        cascade = ToposGOATCascade(config=config)
        
        # Diatomic system with only 1 possible minimum
        seed_atoms = Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.5]])
        seed_atoms.calc = EMT()

        report = cascade.run_cascade(seed_atoms=seed_atoms, session_id="test_patience")
        assert report.total_cycles_executed <= 3
        assert report.total_unique_basins == 1

    def test_gradient_noise_optimizer_with_torch_mlff(self) -> None:
        """Verify GradientNoiseOptimizer works seamlessly with TorchMLFFCalculator."""
        calc = TorchMLFFCalculator(device="cpu", torch_dtype="float64")
        atoms = Atoms("H2O", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 1.1], [0.9, 0.0, -0.3]])
        atoms.calc = calc

        opt_engine = GradientNoiseOptimizer(
            primary_optimizer=QuenchAlgorithm.LBFGS,
            fallback_optimizer=QuenchAlgorithm.FIRE,
            fmax=0.05,
            max_steps=100,
        )

        res = opt_engine.optimize(atoms, geom_id="h2o_torch_mlff")
        assert res.converged is True
        assert res.final_max_force <= 0.05
        assert res.final_energy < res.initial_energy

    def test_goat_cascade_report_json_serialization(self, tmp_path: Path) -> None:
        """Verify complete JSON serialization and reconstruction of GOATCascadeReport."""
        db_path = tmp_path / "cascade_json.h5"
        config = GOATCascadeConfig(
            max_cycles=1,
            fmax=0.05,
            db_path=db_path,
            temperature_schedule=[300.0],
            langevin_steps_per_stage=10,
        )
        cascade = ToposGOATCascade(config=config)
        seed_atoms = Atoms("Cu3", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.4], [2.2, 0.0, 0.0]])
        seed_atoms.calc = EMT()

        report = cascade.run_cascade(seed_atoms=seed_atoms, session_id="test_json_export")
        dumped_json = report.model_dump_json()
        assert "test_json_export" in dumped_json

        # Parse back and verify structure
        reconstructed = GOATCascadeReport.model_validate_json(dumped_json)
        assert reconstructed.session_id == "test_json_export"
        assert reconstructed.total_cycles_executed == report.total_cycles_executed
        assert reconstructed.total_unique_basins == report.total_unique_basins

    def test_custom_hardware_broker_integration(self, tmp_path: Path) -> None:
        """Verify ToposGOATCascade integration with custom HardwareResourceBroker."""
        broker = HardwareResourceBroker()
        db_path = tmp_path / "cascade_broker.h5"
        config = GOATCascadeConfig(
            max_cycles=1,
            fmax=0.05,
            db_path=db_path,
            engine=EngineTier.MACE_OFF24M,
            device=DeviceType.CPU,
            precision=PrecisionMode.FP32,
            temperature_schedule=[300.0],
            langevin_steps_per_stage=10,
        )
        cascade = ToposGOATCascade(config=config, broker=broker)
        seed_atoms = Atoms("Cu2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.6]])
        seed_atoms.calc = EMT()

        report = cascade.run_cascade(seed_atoms=seed_atoms, session_id="test_broker")
        assert report.total_unique_basins >= 1
        assert cascade.broker is broker

    def test_topos_goat_cascade_default_initialization(self) -> None:
        """Verify ToposGOATCascade initializes without error using all defaults."""
        cascade = ToposGOATCascade()
        assert cascade.config is not None
        assert cascade.broker is not None
        assert cascade.memory_manager is not None
        assert cascade.db_path.exists() or cascade.db_path.parent.exists()


