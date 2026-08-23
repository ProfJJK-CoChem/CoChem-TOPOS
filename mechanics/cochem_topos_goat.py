"""
CoChem-TOPOS: Stage 2.3 - The GOAT Cascade Master Orchestrator (cochem_topos_goat.py)

Master execution orchestrator for the mechanics tier, executing continuous looping
between Quench (Relaxation) and Escape (Basin Exploration) phases until conformational
search space is exhausted or convergence criteria are achieved.

Execution Directives:
1. Gradient-Noise Optimizer Toggles: Dynamically monitors PES descent trajectory.
   Defaults to LBFGS for smooth convergence. Intercepts ill-conditioned Hessian updates,
   line-search failures, and gradient noise oscillations, dynamically toggling to FIRE
   (Fast Inertial Relaxation Engine).
2. The Pipeline Loop: Directs continuous handoff between exploring and refining:
   cochem_topos_escape.py (Perturb) -> cochem_topos_quench.py (Relax) ->
   cochem_topos_crusher.py (Deduplicate) -> cochem_topos_memory.py (SWMR HDF5).
3. Orphaned Thread Reaper: Enforces local execution safety. Employs atexit, cross-platform
   process termination (Windows Job Objects / POSIX process groups / psutil), guaranteeing
   that on interruption or crash, all spawned child processes and MPI workers are forcefully reaped.

Strictly complies with the Tripartite Air-Gap Policy and Zero-Mock Mandate.
"""

from __future__ import annotations

import atexit
import ctypes
import enum
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Optional, Union

import h5py
import numpy as np
from ase import Atoms, units
from ase.calculators.emt import EMT
from ase.calculators.lj import LennardJones
from ase.optimize import BFGS, FIRE, LBFGS, QuasiNewton
from ase.optimize.optimize import Optimizer
from pydantic import BaseModel, ConfigDict, Field

# Process utility handling
try:
    import psutil
except ImportError:
    psutil = None

# Internal Mechanics Subsystem Imports
try:
    from mechanics.cochem_topos_escape import (
        EscapeConfig,
        EscapeMechanism,
        EscapeResult,
        EscapeStatus,
        GoodTuringEstimator,
        ParityLock,
        ToposEscapeOrchestrator,
        calculate_rmsd,
        canonical_geometry_hash,
        create_fair_provenance_record,
    )
    from mechanics.cochem_topos_memory import (
        CascadeState,
        DeviceType,
        EngineTier,
        FallbackCascadeStateMachine,
        FallbackReason,
        GeometryRecord,
        GPUDeviceInfo,
        HardwareResourceBroker,
        HardwareSnapshot,
        PrecisionDowngradeProtocol,
        PrecisionMode,
        TelemetryRecord,
        ToposHDF5MemoryManager,
        TrajectoryStep,
        UniversalFallbackCascade,
    )
    from mechanics.cochem_topos_quench import (
        CalculatorFactory,
        CUDAGraphOptimizerWrapper,
        QuenchAlgorithm,
        QuenchConfig,
        QuenchResult,
        QuenchStatus,
        SoftQuenchGovernor,
        ToposQuenchOrchestrator,
        TorchMLFFCalculator,
    )
except ImportError:
    from cochem_topos_escape import (  # type: ignore[import-not-found]
        EscapeConfig,
        EscapeMechanism,
        EscapeResult,
        EscapeStatus,
        GoodTuringEstimator,
        ParityLock,
        ToposEscapeOrchestrator,
        calculate_rmsd,
        canonical_geometry_hash,
        create_fair_provenance_record,
    )
    from cochem_topos_memory import (  # type: ignore[import-not-found]
        CascadeState,
        DeviceType,
        EngineTier,
        FallbackCascadeStateMachine,
        FallbackReason,
        GeometryRecord,
        GPUDeviceInfo,
        HardwareResourceBroker,
        HardwareSnapshot,
        PrecisionDowngradeProtocol,
        PrecisionMode,
        TelemetryRecord,
        ToposHDF5MemoryManager,
        TrajectoryStep,
        UniversalFallbackCascade,
    )
    from cochem_topos_quench import (  # type: ignore[import-not-found]
        CalculatorFactory,
        CUDAGraphOptimizerWrapper,
        QuenchAlgorithm,
        QuenchConfig,
        QuenchResult,
        QuenchStatus,
        SoftQuenchGovernor,
        ToposQuenchOrchestrator,
        TorchMLFFCalculator,
    )

# Topology Crusher Deduplication Subsystem Imports
try:
    from topology.cochem_topos_crusher import (
        ConformerCandidate,
        DeduplicationRecord,
        DeduplicationVerdict,
        EnsembleDeduplicationReport,
        TopologyCrusher,
    )
except ImportError:
    try:
        from core_engine.cochem_topos_crusher import (  # type: ignore[import-not-found]
            TopologyCrusher,  # type: ignore[misc]
        )
    except ImportError:
        TopologyCrusher = None  # type: ignore[assignment,misc]

# Module Logger
logger = logging.getLogger("CoChem.TOPOS.MechanicsGOAT")


# ============================================================================
# 1. Enums and Pydantic Data Models
# ============================================================================


class OptimizerToggleReason(str, enum.Enum):
    """Specific root causes triggering automatic optimizer toggles."""

    HESSIAN_ILL_CONDITIONED = "HESSIAN_ILL_CONDITIONED"
    FORCE_OSCILLATION = "FORCE_OSCILLATION"
    ENERGY_INCREASE_DETECTED = "ENERGY_INCREASE_DETECTED"
    OPTIMIZER_EXCEPTION = "OPTIMIZER_EXCEPTION"
    LINE_SEARCH_FAILURE = "LINE_SEARCH_FAILURE"
    MAX_STEPS_EXCEEDED = "MAX_STEPS_EXCEEDED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class CascadeStoppingCriterion(str, enum.Enum):
    """Halting conditions for the master GOAT cascade exploration loop."""

    MAX_CYCLES_REACHED = "MAX_CYCLES_REACHED"
    TARGET_COVERAGE_REACHED = "TARGET_COVERAGE_REACHED"
    PATIENCE_EXHAUSTED = "PATIENCE_EXHAUSTED"
    ENERGY_WINDOW_EXHAUSTED = "ENERGY_WINDOW_EXHAUSTED"
    USER_INTERRUPTED = "USER_INTERRUPTED"
    HARD_ABORT = "HARD_ABORT"


class OptimizerToggleEvent(BaseModel):
    """Detailed telemetry record for an optimizer switch event."""

    model_config = ConfigDict(frozen=True)

    geom_id: str = Field(..., description="Unique geometry identifier")
    step_index: int = Field(..., description="Optimization step index where switch triggered")
    reason: OptimizerToggleReason = Field(..., description="Root cause for the optimizer switch")
    from_optimizer: QuenchAlgorithm = Field(..., description="Original optimizer algorithm")
    to_optimizer: QuenchAlgorithm = Field(..., description="New target optimizer algorithm")
    current_fmax: float = Field(..., description="Maximum atomic force (eV/A) at toggle time")
    current_energy: float = Field(..., description="Potential energy (eV or Hartree) at toggle time")
    details: str = Field(default="", description="Diagnostic details or exception message")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp of event")


class GOATCascadeConfig(BaseModel):
    """Configuration specification for the master GOAT Cascade execution loop."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    max_cycles: int = Field(10, description="Maximum number of Escape-Quench cycles")
    patience: int = Field(3, description="Cycles without discovering a new basin before early stopping")
    target_coverage: float = Field(0.95, description="Good-Turing completeness threshold (0.0 to 1.0)")
    primary_optimizer: QuenchAlgorithm = Field(QuenchAlgorithm.LBFGS, description="Primary optimizer algorithm")
    fallback_optimizer: QuenchAlgorithm = Field(QuenchAlgorithm.FIRE, description="Fallback optimizer algorithm")
    oscillation_window: int = Field(5, description="Rolling window size for detecting force/energy oscillations")
    oscillation_force_tol: float = Field(0.01, description="Force variance threshold indicating oscillation")
    fmax: float = Field(0.05, description="Force convergence threshold (eV/A)")
    max_quench_steps: int = Field(300, description="Maximum steps per quench evaluation")
    enable_process_reaper: bool = Field(True, description="Enable automated OS process and thread reaping")
    save_to_hdf5: bool = Field(True, description="Persist all discovered basins and telemetry to SWMR HDF5")
    db_path: Optional[Path] = Field(None, description="Target path to HDF5 landscape file")
    temperature_schedule: list[float] = Field(
        default_factory=lambda: [300.0, 500.0, 1000.0],
        description="Progressive Langevin thermal shock temperatures (K)",
    )
    langevin_steps_per_stage: int = Field(100, description="Langevin MD steps per thermal stage")
    langevin_dt_fs: float = Field(2.0, description="Langevin time step (fs)")
    basin_rmsd_threshold: float = Field(0.08, description="Minimum RMSD (A) to qualify as a distinct basin")
    basin_energy_threshold_ev: float = Field(1e-4, description="Minimum energy delta (eV) for distinct basin")
    engine: EngineTier = Field(EngineTier.MACE_OFF24M, description="Default calculation engine tier")
    device: DeviceType = Field(DeviceType.AUTO, description="Hardware compute device target")
    precision: PrecisionMode = Field(PrecisionMode.FP32, description="Calculation floating point precision")
    max_workers: int = Field(4, description="Parallel worker count for batch operations")


class CascadeCycleRecord(BaseModel):
    """Comprehensive log of an individual exploration and refinement cycle."""

    cycle_index: int = Field(..., description="1-indexed cycle number")
    seed_geom_id: str = Field(..., description="Identifier of seed basin perturbed in this cycle")
    escape_status: str = Field(..., description="Status returned by escape room exploration")
    escape_mechanism: Optional[str] = Field(None, description="Mechanism successfully breaching basin")
    candidates_generated: int = Field(0, description="Count of candidate structures generated")
    quench_converged_count: int = Field(0, description="Count of relaxed geometries achieving convergence")
    unique_basins_discovered: int = Field(0, description="New unique basins accepted by Crusher")
    duplicates_rejected: int = Field(0, description="Candidate structures rejected as duplicates")
    enantiomers_preserved: int = Field(0, description="Chiral enantiomeric partners preserved")
    optimizer_toggles_count: int = Field(0, description="Count of LBFGS -> FIRE toggles in this cycle")
    duration_seconds: float = Field(0.0, description="Wall clock runtime for this cycle")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp")


class GOATCascadeResult(BaseModel):
    """Metadata container for an accepted unique basin produced by the GOAT cascade."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    basin_id: str = Field(..., description="Unique basin identifier")
    energy_hartree: float = Field(..., description="Converged potential energy in Hartree")
    energy_kcal: float = Field(..., description="Converged potential energy in kcal/mol")
    fmax: float = Field(..., description="Final maximum residual force (eV/A)")
    converged: bool = Field(..., description="Whether optimization achieved fmax criteria")
    optimizer_used: QuenchAlgorithm = Field(..., description="Final optimizer that achieved convergence")
    toggle_events: list[OptimizerToggleEvent] = Field(default_factory=list, description="Optimizer toggles")
    atomic_numbers: list[int] = Field(..., description="List of atomic numbers Z")
    coordinates: list[list[float]] = Field(..., description="Cartesian coordinates (N, 3) in Angstroms")
    is_enantiomer: bool = Field(False, description="Whether this basin is a chiral enantiomeric partner")
    enantiomer_partner_id: Optional[str] = Field(None, description="ID of corresponding enantiomeric partner")
    source_cycle: int = Field(0, description="Cascade cycle index where this basin was discovered")
    provenance_record: Optional[dict[str, Any]] = Field(default=None, description="FAIR provenance tags")


class GOATCascadeReport(BaseModel):
    """Master FAIR report summarizing the entire GOAT cascade exploration session."""

    session_id: str = Field(..., description="Unique exploration session identifier")
    total_cycles_executed: int = Field(0, description="Total number of cycles completed")
    total_unique_basins: int = Field(0, description="Total count of unique conformer basins accepted")
    total_duplicates_rejected: int = Field(0, description="Total count of duplicate structures rejected")
    total_enantiomers_preserved: int = Field(0, description="Total count of chiral enantiomers preserved")
    total_optimizer_toggles: int = Field(0, description="Total count of optimizer toggles triggered")
    final_completeness_estimate: float = Field(0.0, description="Good-Turing completeness estimate")
    converged_stopping_criterion: str = Field(..., description="Condition that terminated the cascade")
    duration_seconds: float = Field(0.0, description="Total wall-clock runtime in seconds")
    cycle_records: list[CascadeCycleRecord] = Field(default_factory=list, description="Per-cycle logs")
    unique_basins: list[GOATCascadeResult] = Field(default_factory=list, description="Accepted unique basins")
    toggle_events: list[OptimizerToggleEvent] = Field(default_factory=list, description="All toggle events")


# ============================================================================
# 2. Orphaned Thread Reaper Subsystem
# ============================================================================


class OrphanedProcessReaper:
    """
    Cross-platform process safety and orphaned thread reaping engine.
    Guarantees that on process termination, user interruption (Ctrl+C), or segmentation fault,
    all spawned subprocesses, MPI ranks, and worker pools are forcefully killed.
    """

    _instance: Optional[OrphanedProcessReaper] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._tracked_processes: list[subprocess.Popen] = []
        self._tracked_threads: list[threading.Thread] = []
        self._cleanup_callbacks: list[Callable[[], None]] = []
        self._job_object_handle: Optional[int] = None
        self._is_closed: bool = False
        self._lock = threading.Lock()

        # Initialize Windows Job Object if running on Windows
        if sys.platform == "win32":
            self._init_windows_job_object()

        # Register standard atexit and signal handlers
        self._register_handlers()

    @classmethod
    def get_instance(cls) -> OrphanedProcessReaper:
        """Retrieve or construct the global singleton process reaper."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _init_windows_job_object(self) -> None:
        """Create a Windows Job Object with KILL_ON_JOB_CLOSE flag set."""
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            # Create Job Object
            job = kernel32.CreateJobObjectW(None, None)
            if job:
                # Set JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)
                class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                    _fields_ = [
                        ("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", ctypes.c_uint32),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", ctypes.c_uint32),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", ctypes.c_uint32),
                        ("SchedulingClass", ctypes.c_uint32),
                    ]

                class IO_COUNTERS(ctypes.Structure):
                    _fields_ = [
                        ("ReadOperationCount", ctypes.c_uint64),
                        ("WriteOperationCount", ctypes.c_uint64),
                        ("OtherOperationCount", ctypes.c_uint64),
                        ("ReadTransferCount", ctypes.c_uint64),
                        ("WriteTransferCount", ctypes.c_uint64),
                        ("OtherTransferCount", ctypes.c_uint64),
                    ]

                class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                    _fields_ = [
                        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryLimit", ctypes.c_size_t),
                        ("PeakJobMemoryLimit", ctypes.c_size_t),
                    ]

                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

                res = kernel32.SetInformationJobObject(
                    job,
                    9,  # JobObjectExtendedLimitInformation
                    ctypes.byref(info),
                    ctypes.sizeof(info),
                )
                if res:
                    self._job_object_handle = job
                    # Assign current process to Job Object
                    current_proc = kernel32.GetCurrentProcess()
                    kernel32.AssignProcessToJobObject(job, current_proc)
                    logger.debug("Windows Job Object initialized with KILL_ON_JOB_CLOSE.")
        except Exception as exc:
            logger.warning(f"Unable to initialize Windows Job Object: {exc}")

    def _register_handlers(self) -> None:
        """Register atexit and signal hooks for clean shutdown."""
        atexit.register(self.reap_all)

        # Handle SIGINT and SIGTERM gracefully
        for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    prev_handler = signal.getsignal(sig)

                    def make_handler(original_h: Any, s_name: str) -> Any:
                        def _signal_handler(signum: int, frame: Any) -> None:
                            logger.info(f"Reaper intercepted {s_name} ({signum}). Terminating all child processes.")
                            self.reap_all()
                            if callable(original_h) and original_h not in (
                                signal.SIG_IGN,
                                signal.SIG_DFL,
                                _signal_handler,
                            ):
                                original_h(signum, frame)
                            else:
                                sys.exit(128 + signum)

                        return _signal_handler

                    signal.signal(sig, make_handler(prev_handler, sig_name))
                except (ValueError, AttributeError, RuntimeError):
                    pass

    def register_process(self, proc: subprocess.Popen) -> None:
        """Register a subprocess for tracked lifecycle management."""
        with self._lock:
            if proc not in self._tracked_processes:
                self._tracked_processes.append(proc)
            # If on Windows and Job Object active, assign child process to Job Object
            if sys.platform == "win32" and self._job_object_handle and proc.pid:
                try:
                    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                    h_proc = kernel32.OpenProcess(0x1F0FFF, False, proc.pid)  # PROCESS_ALL_ACCESS
                    if h_proc:
                        kernel32.AssignProcessToJobObject(self._job_object_handle, h_proc)
                        kernel32.CloseHandle(h_proc)
                except Exception as exc:
                    logger.debug(f"AssignProcessToJobObject failed for PID {proc.pid}: {exc}")

    def register_thread(self, thread: threading.Thread) -> None:
        """Register a worker thread for tracked lifecycle management."""
        with self._lock:
            if thread not in self._tracked_threads:
                self._tracked_threads.append(thread)

    def register_cleanup_callback(self, callback: Callable[[], None]) -> None:
        """Register an arbitrary cleanup routine to execute during reaping."""
        with self._lock:
            if callback not in self._cleanup_callbacks:
                self._cleanup_callbacks.append(callback)

    @property
    def tracked_processes(self) -> list[subprocess.Popen]:
        """Return a copy of currently tracked subprocesses."""
        with self._lock:
            return list(self._tracked_processes)

    def reap_process(self, proc: subprocess.Popen, timeout_seconds: float = 2.0) -> None:
        """Forcefully terminate an individual subprocess and its entire descendant tree."""
        if proc.poll() is not None:
            return

        pid = proc.pid
        logger.info(f"Reaping subprocess PID={pid}...")

        # Terminate via psutil tree if available
        if psutil is not None and pid:
            try:
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                parent.terminate()

                # Wait for graceful exit
                _, alive = psutil.wait_procs(children + [parent], timeout=timeout_seconds)
                for p in alive:
                    try:
                        p.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                pass

        # Native fallback termination
        try:
            proc.terminate()
            proc.wait(timeout=timeout_seconds)
        except (subprocess.TimeoutExpired, Exception):
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass

    def reap_all(self) -> None:
        """Forcefully reap all registered processes, worker threads, and child trees."""
        with self._lock:
            if self._is_closed:
                return
            self._is_closed = True

            # 1. Execute custom callbacks
            for cb in self._cleanup_callbacks:
                try:
                    cb()
                except Exception as exc:
                    logger.warning(f"Error executing cleanup callback: {exc}")

            # 2. Reap tracked subprocesses
            for proc in self._tracked_processes:
                try:
                    self.reap_process(proc, timeout_seconds=1.0)
                except Exception as exc:
                    logger.warning(f"Error reaping process {proc}: {exc}")
            self._tracked_processes.clear()

            # 3. Scan for any orphaned child processes of the current PID
            if psutil is not None:
                try:
                    current_proc = psutil.Process()
                    children = current_proc.children(recursive=True)
                    if children:
                        logger.info(f"Reaping {len(children)} residual child processes...")
                        for child in children:
                            try:
                                child.terminate()
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                        _, alive = psutil.wait_procs(children, timeout=1.0)
                        for p in alive:
                            try:
                                p.kill()
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                except Exception:
                    pass

    def __enter__(self) -> OrphanedProcessReaper:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.reap_all()


def get_global_reaper() -> OrphanedProcessReaper:
    """Retrieve the global singleton process reaper."""
    return OrphanedProcessReaper.get_instance()


def reap_all_child_processes(procs: Sequence[subprocess.Popen]) -> None:
    """Convenience utility to forcefully terminate a list of subprocesses."""
    reaper = get_global_reaper()
    for p in procs:
        reaper.reap_process(p)


# ============================================================================
# 3. Gradient-Noise Optimizer Toggle Engine
# ============================================================================


class GradientNoiseQuenchResult(BaseModel):
    """Output metadata container for GradientNoiseOptimizer relaxation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    geom_id: str
    status: QuenchStatus
    converged: bool
    initial_energy: float
    final_energy: float
    energy_change: float
    initial_max_force: float
    final_max_force: float
    steps_taken: int
    active_optimizer: QuenchAlgorithm
    toggle_events: list[OptimizerToggleEvent] = Field(default_factory=list)
    final_positions: list[list[float]] = Field(default_factory=list)
    final_forces: list[list[float]] = Field(default_factory=list)
    duration_seconds: float = 0.0
    error_message: Optional[str] = None


class GradientNoiseOptimizer:
    """
    Dynamic Potential Energy Surface descent monitor with automatic optimizer toggling.
    Defaults to LBFGS for fast, smooth descent. Dynamically detects ill-conditioned
    Hessian updates, force oscillations, or runtime exceptions, intercepting the failure
    and seamlessly continuing relaxation with FIRE (Fast Inertial Relaxation Engine).
    """

    def __init__(
        self,
        primary_optimizer: QuenchAlgorithm = QuenchAlgorithm.LBFGS,
        fallback_optimizer: QuenchAlgorithm = QuenchAlgorithm.FIRE,
        fmax: float = 0.05,
        max_steps: int = 300,
        oscillation_window: int = 5,
        oscillation_force_tol: float = 0.01,
    ) -> None:
        self.primary_optimizer = primary_optimizer
        self.fallback_optimizer = fallback_optimizer
        self.fmax = float(fmax)
        self.max_steps = int(max_steps)
        self.oscillation_window = int(oscillation_window)
        self.oscillation_force_tol = float(oscillation_force_tol)

    def _get_optimizer_class(self, algo: QuenchAlgorithm) -> type[Optimizer]:
        """Resolve QuenchAlgorithm enum to the corresponding ASE Optimizer class."""
        mapping = {
            QuenchAlgorithm.BFGS: BFGS,
            QuenchAlgorithm.LBFGS: LBFGS,
            QuenchAlgorithm.FIRE: FIRE,
            QuenchAlgorithm.QUASI_NEWTON: QuasiNewton,
        }
        return mapping.get(algo, LBFGS)

    def _trigger_fallback(
        self,
        atoms: Atoms,
        geom_id: str,
        step_idx: int,
        reason: OptimizerToggleReason,
        curr_energy: float,
        curr_fmax: float,
        details: str = "",
    ) -> OptimizerToggleEvent:
        """Create and log an optimizer toggle event."""
        event = OptimizerToggleEvent(
            geom_id=geom_id,
            step_index=step_idx,
            reason=reason,
            from_optimizer=self.primary_optimizer,
            to_optimizer=self.fallback_optimizer,
            current_fmax=curr_fmax,
            current_energy=curr_energy,
            details=details,
        )
        logger.warning(
            f"[{geom_id}] Gradient-Noise Optimizer Toggle Triggered at step {step_idx}: "
            f"{self.primary_optimizer.value} -> {self.fallback_optimizer.value} "
            f"(Reason: {reason.value}, fmax={curr_fmax:.4f} eV/A, ΔE={curr_energy:.4f}, Details: {details})"
        )
        return event

    def optimize(
        self,
        atoms: Atoms,
        geom_id: str = "geom_opt",
    ) -> GradientNoiseQuenchResult:
        """
        Execute gradient-noise monitored PES optimization.

        Args:
            atoms: ASE Atoms object with attached Calculator.
            geom_id: Identification string for logging and telemetry.

        Returns:
            GradientNoiseQuenchResult: Structured optimization output.
        """
        start_time = time.time()
        toggle_events: list[OptimizerToggleEvent] = []

        if atoms.calc is None:
            raise ValueError(f"Atoms object for [{geom_id}] has no attached Calculator.")

        # Compute initial state
        init_energy = float(atoms.get_potential_energy())
        init_forces = atoms.get_forces()
        init_fmax = float(np.max(np.linalg.norm(init_forces, axis=1)))

        if init_fmax <= self.fmax:
            return GradientNoiseQuenchResult(
                geom_id=geom_id,
                status=QuenchStatus.CONVERGED,
                converged=True,
                initial_energy=init_energy,
                final_energy=init_energy,
                energy_change=0.0,
                initial_max_force=init_fmax,
                final_max_force=init_fmax,
                steps_taken=0,
                active_optimizer=self.primary_optimizer,
                toggle_events=[],
                final_positions=atoms.get_positions().tolist(),
                final_forces=init_forces.tolist(),
                duration_seconds=time.time() - start_time,
            )

        # Tracking queues for oscillation monitoring
        force_history: deque[float] = deque(maxlen=self.oscillation_window)
        energy_history: deque[float] = deque(maxlen=self.oscillation_window)

        curr_optimizer_algo = self.primary_optimizer
        primary_cls = self._get_optimizer_class(self.primary_optimizer)
        fallback_cls = self._get_optimizer_class(self.fallback_optimizer)

        total_steps = 0
        switched_to_fallback = False
        opt_instance: Optional[Optimizer] = None

        def step_monitor_callback() -> None:
            nonlocal switched_to_fallback, opt_instance
            if switched_to_fallback or opt_instance is None:
                return

            s_idx = opt_instance.get_number_of_steps()
            try:
                e_val = float(atoms.get_potential_energy())
                f_val = atoms.get_forces()
                f_max = float(np.max(np.linalg.norm(f_val, axis=1)))

                # Check for numerical NaN/Inf breakdown
                if np.isnan(e_val) or np.isnan(f_max) or np.isinf(e_val) or np.isinf(f_max):
                    event = self._trigger_fallback(
                        atoms=atoms,
                        geom_id=geom_id,
                        step_idx=s_idx,
                        reason=OptimizerToggleReason.HESSIAN_ILL_CONDITIONED,
                        curr_energy=e_val,
                        curr_fmax=f_max,
                        details="NaN or Inf detected in energy/forces during trajectory",
                    )
                    toggle_events.append(event)
                    switched_to_fallback = True
                    return

                force_history.append(f_max)
                energy_history.append(e_val)

                # Check for oscillation in sliding window: forces fail to decrease and bounce around
                if len(force_history) >= self.oscillation_window:
                    f_diffs = np.diff(list(force_history))
                    # Check if gradient noise is causing sign flips in consecutive force steps
                    sign_flips = np.sum(np.diff(np.sign(f_diffs)) != 0)
                    f_std = float(np.std(list(force_history)))

                    if sign_flips >= 2 and f_std < self.oscillation_force_tol:
                        event = self._trigger_fallback(
                            atoms=atoms,
                            geom_id=geom_id,
                            step_idx=s_idx,
                            reason=OptimizerToggleReason.FORCE_OSCILLATION,
                            curr_energy=e_val,
                            curr_fmax=f_max,
                            details=f"Oscillation detected: {sign_flips} sign flips, force std={f_std:.6f}",
                        )
                        toggle_events.append(event)
                        switched_to_fallback = True
                        return

            except Exception as mon_exc:
                event = self._trigger_fallback(
                    atoms=atoms,
                    geom_id=geom_id,
                    step_idx=s_idx,
                    reason=OptimizerToggleReason.OPTIMIZER_EXCEPTION,
                    curr_energy=init_energy,
                    curr_fmax=init_fmax,
                    details=f"Trajectory callback exception: {mon_exc}",
                )
                toggle_events.append(event)
                switched_to_fallback = True

        # Phase 1: Attempt optimization with Primary Optimizer (LBFGS)
        try:
            opt_instance = primary_cls(atoms, logfile=None)
            opt_instance.attach(step_monitor_callback, interval=1)
            opt_instance.run(fmax=self.fmax, steps=self.max_steps)
            total_steps += opt_instance.get_number_of_steps()

        except Exception as opt_exc:
            # Intercept any optimizer crash (e.g. LinAlgError, line search error)
            curr_pos = atoms.get_positions()
            curr_e = float(atoms.get_potential_energy()) if not np.isnan(curr_pos).any() else init_energy
            curr_f = atoms.get_forces() if not np.isnan(curr_pos).any() else init_forces
            curr_fm = float(np.max(np.linalg.norm(curr_f, axis=1)))

            event = self._trigger_fallback(
                atoms=atoms,
                geom_id=geom_id,
                step_idx=total_steps,
                reason=OptimizerToggleReason.OPTIMIZER_EXCEPTION,
                curr_energy=curr_e,
                curr_fmax=curr_fm,
                details=f"Primary optimizer exception intercepted: {opt_exc}",
            )
            toggle_events.append(event)
            switched_to_fallback = True

        # Check if primary converged or if fallback is required
        final_forces = atoms.get_forces()
        final_fmax = float(np.max(np.linalg.norm(final_forces, axis=1)))
        final_energy = float(atoms.get_potential_energy())
        is_converged = final_fmax <= self.fmax

        # Phase 2: If primary did not converge or triggered toggle, engage Fallback Optimizer (FIRE)
        if not is_converged or switched_to_fallback:
            if not switched_to_fallback:
                event = self._trigger_fallback(
                    atoms=atoms,
                    geom_id=geom_id,
                    step_idx=total_steps,
                    reason=OptimizerToggleReason.MAX_STEPS_EXCEEDED,
                    curr_energy=final_energy,
                    curr_fmax=final_fmax,
                    details="Primary optimizer exhausted steps without converging. Switching to FIRE.",
                )
                toggle_events.append(event)

            curr_optimizer_algo = self.fallback_optimizer
            remaining_steps = max(50, self.max_steps - total_steps)

            try:
                fire_instance = fallback_cls(atoms, logfile=None)
                fire_instance.run(fmax=self.fmax, steps=remaining_steps)
                total_steps += fire_instance.get_number_of_steps()

                final_forces = atoms.get_forces()
                final_fmax = float(np.max(np.linalg.norm(final_forces, axis=1)))
                final_energy = float(atoms.get_potential_energy())
                is_converged = final_fmax <= self.fmax
            except Exception as fb_exc:
                logger.error(f"[{geom_id}] Fallback optimizer ({self.fallback_optimizer.value}) failed: {fb_exc}")
                return GradientNoiseQuenchResult(
                    geom_id=geom_id,
                    status=QuenchStatus.FAILED,
                    converged=False,
                    initial_energy=init_energy,
                    final_energy=final_energy,
                    energy_change=final_energy - init_energy,
                    initial_max_force=init_fmax,
                    final_max_force=final_fmax,
                    steps_taken=total_steps,
                    active_optimizer=curr_optimizer_algo,
                    toggle_events=toggle_events,
                    final_positions=atoms.get_positions().tolist(),
                    final_forces=final_forces.tolist(),
                    duration_seconds=time.time() - start_time,
                    error_message=str(fb_exc),
                )

        status = QuenchStatus.CONVERGED if is_converged else QuenchStatus.MAX_STEPS_EXCEEDED
        return GradientNoiseQuenchResult(
            geom_id=geom_id,
            status=status,
            converged=is_converged,
            initial_energy=init_energy,
            final_energy=final_energy,
            energy_change=final_energy - init_energy,
            initial_max_force=init_fmax,
            final_max_force=final_fmax,
            steps_taken=total_steps,
            active_optimizer=curr_optimizer_algo,
            toggle_events=toggle_events,
            final_positions=atoms.get_positions().tolist(),
            final_forces=final_forces.tolist(),
            duration_seconds=time.time() - start_time,
        )


# ============================================================================
# 4. Master GOAT Cascade Orchestrator
# ============================================================================


class ToposGOATCascade:
    """
    Master Execution Orchestrator for the Mechanics Subsystem (Stage 2.3).
    Loops continuously between Quench (Refinement) and Escape (Exploration) phases,
    directing handoffs across:
      1. cochem_topos_escape.py (Wigner kicks / Progressive Langevin Thermal schedule)
      2. cochem_topos_quench.py & GradientNoiseOptimizer (PES descent with LBFGS -> FIRE toggle)
      3. cochem_topos_crusher.py (Rotational Sieve -> KDTree -> Mass-Weighted Eckart RMSD)
      4. cochem_topos_memory.py (HDF5 SWMR persistent datastore with [M], [D], [E] FAIR provenance)
    """

    def __init__(
        self,
        config: Optional[GOATCascadeConfig] = None,
        broker: Optional[HardwareResourceBroker] = None,
        memory_manager: Optional[ToposHDF5MemoryManager] = None,
        crusher: Optional[TopologyCrusher] = None,
    ) -> None:
        self.config = config or GOATCascadeConfig()
        self.broker = broker or HardwareResourceBroker()
        self.reaper = get_global_reaper() if self.config.enable_process_reaper else None

        # Resolve HDF5 datastore path
        self.db_path = self.config.db_path or Path(tempfile.gettempdir()) / "topos_goat_landscape.h5"
        self.memory_manager = memory_manager or ToposHDF5MemoryManager(db_path=self.db_path)

        # Initialize Subsystem Orchestrators
        escape_cfg = EscapeConfig(
            thermal_schedule=self.config.temperature_schedule,
            langevin_steps_per_stage=self.config.langevin_steps_per_stage,
            langevin_dt_fs=self.config.langevin_dt_fs,
            basin_rmsd_threshold=self.config.basin_rmsd_threshold,
            basin_energy_threshold_ev=self.config.basin_energy_threshold_ev,
            quench_fmax=self.config.fmax,
            save_to_hdf5=self.config.save_to_hdf5,
            db_path=self.db_path,
        )
        self.escape_orchestrator = ToposEscapeOrchestrator(
            config=escape_cfg,
            memory_manager=self.memory_manager,
        )

        quench_cfg = QuenchConfig(
            fmax=self.config.fmax,
            max_steps=self.config.max_quench_steps,
            algorithm=self.config.primary_optimizer,
            engine=self.config.engine,
            device=self.config.device,
            precision=self.config.precision,
            db_path=self.db_path,
            save_to_hdf5=self.config.save_to_hdf5,
            max_workers=self.config.max_workers,
        )
        self.quench_orchestrator = ToposQuenchOrchestrator(
            broker=self.broker,
            memory_manager=self.memory_manager,
            default_config=quench_cfg,
        )

        self.adaptive_optimizer = GradientNoiseOptimizer(
            primary_optimizer=self.config.primary_optimizer,
            fallback_optimizer=self.config.fallback_optimizer,
            fmax=self.config.fmax,
            max_steps=self.config.max_quench_steps,
            oscillation_window=self.config.oscillation_window,
            oscillation_force_tol=self.config.oscillation_force_tol,
        )

        # Initialize Crusher Deduplication Funnel
        if crusher is not None:
            self.crusher = crusher
        elif TopologyCrusher is not None:
            self.crusher = TopologyCrusher(
                rot_tol=0.015,
                dipole_tol=0.05,
                kdtree_tol=0.02,
                rmsd_tol=self.config.basin_rmsd_threshold,
                hdf5_path=self.db_path if self.config.save_to_hdf5 else None,
            )
        else:
            self.crusher = None

        self.good_turing = GoodTuringEstimator()

    def run_cascade(
        self,
        seed_atoms: Atoms,
        session_id: Optional[str] = None,
    ) -> GOATCascadeReport:
        """
        Execute the master GOAT cascade exploration loop on the given seed geometry.

        Handoff Protocol:
        Seed -> Initial Quench (LBFGS/FIRE) -> Seed Basin Accepted ->
        Loop:
          1. Basin Selection ->
          2. ToposEscapeOrchestrator (Perturb via Wigner / Langevin shock) ->
          3. Adaptive Quench with Gradient-Noise Toggle (Relax) ->
          4. TopologyCrusher (Deduplicate / Eckart RMSD / Chiral Enantiomers) ->
          5. ToposHDF5MemoryManager (SWMR Write) ->
          6. Good-Turing Completeness Check & Stopping Criteria Evaluation.

        Args:
            seed_atoms: Starting molecular geometry (ASE Atoms).
            session_id: Optional unique exploration session ID.

        Returns:
            GOATCascadeReport: Comprehensive exploration session report.
        """
        session = session_id or f"goat_session_{int(time.time()*1000)}"
        start_time = time.time()
        logger.info(f"[{session}] Initiating Master GOAT Cascade exploration...")

        discovered_basins: list[GOATCascadeResult] = []
        all_toggle_events: list[OptimizerToggleEvent] = []
        cycle_records: list[CascadeCycleRecord] = []

        total_duplicates_rejected = 0
        total_enantiomers_preserved = 0
        consecutive_zero_discovery_cycles = 0
        halting_reason = CascadeStoppingCriterion.MAX_CYCLES_REACHED

        # Step 0: Ensure seed atoms have a valid calculator attached
        if seed_atoms.calc is None:
            # Default to EMT for simple metallic systems or Lennard-Jones
            symbols = seed_atoms.get_chemical_symbols()
            if all(s in ["Cu", "Al", "Ni", "Pd", "Pt", "Au", "Ag"] for s in symbols):
                seed_atoms.calc = EMT()
            else:
                seed_atoms.calc = LennardJones()

        # Step 1: Initial Quench of Seed Geometry
        logger.info(f"[{session}] Performing initial relaxation on seed geometry...")
        seed_quench = self.adaptive_optimizer.optimize(seed_atoms, geom_id=f"{session}_seed_initial")
        all_toggle_events.extend(seed_quench.toggle_events)

        quenched_seed_atoms = seed_atoms.copy()
        quenched_seed_atoms.set_positions(seed_quench.final_positions)
        quenched_seed_atoms.calc = seed_atoms.calc

        seed_energy_h = seed_quench.final_energy * 0.0367493  # Convert eV to Hartree
        seed_energy_kcal = seed_quench.final_energy * 23.060541945329  # Convert eV to kcal/mol
        seed_atomic_numbers = quenched_seed_atoms.get_atomic_numbers().tolist()
        seed_geom_id = f"{session}_basin_0000"

        # Register seed in Crusher
        if self.crusher is not None:
            self.crusher.process_conformer(
                quenched_seed_atoms,
                energy_kcal=seed_energy_kcal,
                source_engine="INITIAL",
                candidate_id=seed_geom_id,
            )

        # Register in Good-Turing estimator
        self.good_turing.update([seed_geom_id])

        # Record Initial Basin
        initial_basin = GOATCascadeResult(
            basin_id=seed_geom_id,
            energy_hartree=seed_energy_h,
            energy_kcal=seed_energy_kcal,
            fmax=seed_quench.final_max_force,
            converged=seed_quench.converged,
            optimizer_used=seed_quench.active_optimizer,
            toggle_events=seed_quench.toggle_events,
            atomic_numbers=seed_atomic_numbers,
            coordinates=seed_quench.final_positions,
            is_enantiomer=False,
            source_cycle=0,
            provenance_record={"tier": "INITIAL_SEED", "tags": ["[M]", "[D]"]},
        )
        discovered_basins.append(initial_basin)

        # Write initial seed to HDF5 SWMR store
        if self.config.save_to_hdf5 and self.memory_manager is not None:
            self.memory_manager.write_geometry(
                GeometryRecord(
                    geom_id=seed_geom_id,
                    atomic_numbers=seed_atomic_numbers,
                    coords=seed_quench.final_positions,
                    energy=seed_energy_h,
                    metadata={"status": "INITIAL_SEED", "session": session},
                )
            )

        # Active pool of basins to perturb
        active_basin_queue: list[Atoms] = [quenched_seed_atoms]

        # Step 2: The Master Cascade Exploration Loop
        for cycle_idx in range(1, self.config.max_cycles + 1):
            cycle_start = time.time()
            logger.info(f"[{session}] === Starting Cascade Cycle {cycle_idx}/{self.config.max_cycles} ===")

            # Select target basin from pool (cycle through queue)
            current_seed = active_basin_queue[(cycle_idx - 1) % len(active_basin_queue)].copy()
            current_seed.calc = seed_atoms.calc
            current_seed_id = f"{session}_seed_cycle_{cycle_idx}"

            # Phase A: Escape Room Perturbation (cochem_topos_escape.py)
            escape_res: EscapeResult = self.escape_orchestrator.run_escape_search(
                seed_atoms=current_seed,
                escape_id=f"{session}_esc_{cycle_idx:03d}",
            )

            cycle_candidates_generated = 1 if escape_res.breached else 0
            cycle_quench_converged = 0
            cycle_unique_basins = 0
            cycle_duplicates = 0
            cycle_enantiomers = 0
            cycle_toggles = 0

            if escape_res.breached:
                # Phase B: Adaptive Quench Relaxation with Gradient-Noise Toggle (cochem_topos_quench.py)
                cand_atoms = Atoms(
                    numbers=escape_res.atomic_numbers,
                    positions=escape_res.quenched_coords,
                )
                cand_atoms.calc = seed_atoms.calc

                cand_quench = self.adaptive_optimizer.optimize(
                    cand_atoms,
                    geom_id=f"{session}_cand_c{cycle_idx:03d}",
                )
                cycle_toggles += len(cand_quench.toggle_events)
                all_toggle_events.extend(cand_quench.toggle_events)

                if cand_quench.converged:
                    cycle_quench_converged += 1

                cand_quenched_atoms = cand_atoms.copy()
                cand_quenched_atoms.set_positions(cand_quench.final_positions)
                cand_quenched_atoms.calc = seed_atoms.calc

                cand_e_kcal = cand_quench.final_energy * 23.060541945329
                cand_e_h = cand_quench.final_energy * 0.0367493
                cand_id = f"{session}_basin_{len(discovered_basins):04d}"

                # Phase C: Crusher Deduplication & Chiral Enantiomer Verification (cochem_topos_crusher.py)
                if self.crusher is not None:
                    dedup_rec: DeduplicationRecord = self.crusher.process_conformer(
                        cand_quenched_atoms,
                        energy_kcal=cand_e_kcal,
                        source_engine="GOAT",
                        candidate_id=cand_id,
                    )

                    if dedup_rec.verdict == DeduplicationVerdict.ACCEPTED_UNIQUE:
                        cycle_unique_basins += 1
                        self.good_turing.update([cand_id])
                        active_basin_queue.append(cand_quenched_atoms)

                        basin_obj = GOATCascadeResult(
                            basin_id=cand_id,
                            energy_hartree=cand_e_h,
                            energy_kcal=cand_e_kcal,
                            fmax=cand_quench.final_max_force,
                            converged=cand_quench.converged,
                            optimizer_used=cand_quench.active_optimizer,
                            toggle_events=cand_quench.toggle_events,
                            atomic_numbers=escape_res.atomic_numbers,
                            coordinates=cand_quench.final_positions,
                            is_enantiomer=False,
                            source_cycle=cycle_idx,
                            provenance_record=escape_res.provenance.model_dump() if escape_res.provenance else None,
                        )
                        discovered_basins.append(basin_obj)

                        # Phase D: SWMR HDF5 Write (cochem_topos_memory.py)
                        if self.config.save_to_hdf5 and self.memory_manager is not None:
                            self.memory_manager.write_geometry(
                                GeometryRecord(
                                    geom_id=cand_id,
                                    atomic_numbers=escape_res.atomic_numbers,
                                    coords=cand_quench.final_positions,
                                    energy=cand_e_h,
                                    metadata={
                                        "status": "ACCEPTED_UNIQUE",
                                        "cycle": cycle_idx,
                                        "session": session,
                                        "provenance": basin_obj.provenance_record,
                                    },
                                )
                            )

                    elif dedup_rec.verdict == DeduplicationVerdict.ENANTIOMER_PRESERVED:
                        cycle_enantiomers += 1
                        total_enantiomers_preserved += 1
                        self.good_turing.update([f"{cand_id}_enantiomer"])

                        basin_obj = GOATCascadeResult(
                            basin_id=f"{cand_id}_enantiomer",
                            energy_hartree=cand_e_h,
                            energy_kcal=cand_e_kcal,
                            fmax=cand_quench.final_max_force,
                            converged=cand_quench.converged,
                            optimizer_used=cand_quench.active_optimizer,
                            toggle_events=cand_quench.toggle_events,
                            atomic_numbers=escape_res.atomic_numbers,
                            coordinates=cand_quench.final_positions,
                            is_enantiomer=True,
                            enantiomer_partner_id=f"{session}_basin_{dedup_rec.matched_basin_idx:04d}"
                            if dedup_rec.matched_basin_idx is not None
                            else None,
                            source_cycle=cycle_idx,
                            provenance_record=escape_res.provenance.model_dump() if escape_res.provenance else None,
                        )
                        discovered_basins.append(basin_obj)

                    else:
                        cycle_duplicates += 1
                        total_duplicates_rejected += 1
                        # Update duplicate frequency in Good-Turing
                        matched_id = (
                            f"{session}_basin_{dedup_rec.matched_basin_idx:04d}"
                            if dedup_rec.matched_basin_idx is not None
                            else seed_geom_id
                        )
                        self.good_turing.update([matched_id])
                else:
                    # Fallback when crusher is absent
                    cycle_unique_basins += 1
                    basin_obj = GOATCascadeResult(
                        basin_id=cand_id,
                        energy_hartree=cand_e_h,
                        energy_kcal=cand_e_kcal,
                        fmax=cand_quench.final_max_force,
                        converged=cand_quench.converged,
                        optimizer_used=cand_quench.active_optimizer,
                        toggle_events=cand_quench.toggle_events,
                        atomic_numbers=escape_res.atomic_numbers,
                        coordinates=cand_quench.final_positions,
                        is_enantiomer=False,
                        source_cycle=cycle_idx,
                    )
                    discovered_basins.append(basin_obj)

            # Record cycle metrics
            cycle_duration = time.time() - cycle_start
            cycle_rec = CascadeCycleRecord(
                cycle_index=cycle_idx,
                seed_geom_id=current_seed_id,
                escape_status=escape_res.status.value,
                escape_mechanism=escape_res.mechanism_used.value if escape_res.mechanism_used else None,
                candidates_generated=cycle_candidates_generated,
                quench_converged_count=cycle_quench_converged,
                unique_basins_discovered=cycle_unique_basins,
                duplicates_rejected=cycle_duplicates,
                enantiomers_preserved=cycle_enantiomers,
                optimizer_toggles_count=cycle_toggles,
                duration_seconds=cycle_duration,
            )
            cycle_records.append(cycle_rec)

            # Update patience counter
            if cycle_unique_basins == 0:
                consecutive_zero_discovery_cycles += 1
            else:
                consecutive_zero_discovery_cycles = 0

            # Evaluate Good-Turing Completeness
            completeness = self.good_turing.calculate_coverage()
            logger.info(
                f"[{session}] Cycle {cycle_idx} complete: +{cycle_unique_basins} basins, "
                f"+{cycle_duplicates} duplicates, Completeness={completeness:.3f} (Patience={consecutive_zero_discovery_cycles}/{self.config.patience})"
            )

            # Check Stopping Criteria
            if completeness >= self.config.target_coverage and len(discovered_basins) > 1:
                logger.info(
                    f"[{session}] Halting criterion met: Target coverage {self.config.target_coverage:.2f} reached."
                )
                halting_reason = CascadeStoppingCriterion.TARGET_COVERAGE_REACHED
                break

            if consecutive_zero_discovery_cycles >= self.config.patience:
                logger.info(
                    f"[{session}] Halting criterion met: Patience limit ({self.config.patience}) reached with zero new basins."
                )
                halting_reason = CascadeStoppingCriterion.PATIENCE_EXHAUSTED
                break

        total_duration = time.time() - start_time
        final_completeness = self.good_turing.calculate_coverage()

        report = GOATCascadeReport(
            session_id=session,
            total_cycles_executed=len(cycle_records),
            total_unique_basins=len(discovered_basins),
            total_duplicates_rejected=total_duplicates_rejected,
            total_enantiomers_preserved=total_enantiomers_preserved,
            total_optimizer_toggles=len(all_toggle_events),
            final_completeness_estimate=final_completeness,
            converged_stopping_criterion=halting_reason.value,
            duration_seconds=total_duration,
            cycle_records=cycle_records,
            unique_basins=discovered_basins,
            toggle_events=all_toggle_events,
        )

        logger.info(
            f"[{session}] GOAT Cascade finished in {total_duration:.2f}s: "
            f"{report.total_unique_basins} unique basins, {report.total_duplicates_rejected} duplicates rejected, "
            f"{report.total_enantiomers_preserved} enantiomers preserved, {report.total_optimizer_toggles} optimizer toggles."
        )
        return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("CoChem-TOPOS Stage 2.3 GOAT Cascade active.")
