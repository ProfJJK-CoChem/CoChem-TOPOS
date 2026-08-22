"""
CoChem-TOPOS: Stage 2.0 - Air-Gapped Hardware Broker & HDF5 SWMR State Manager
Implements ToposHDF5MemoryManager, HardwareResourceBroker, UniversalFallbackCascade,
and PrecisionDowngradeProtocol.

Strictly complies with the Tripartite Air-Gap Policy and Zero-Mock Mandate.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Sequence, Set, Tuple, Union

import h5py
import numpy as np
import psutil
from filelock import FileLock, Timeout
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Optional acceleration libraries with robust fallback
try:
    import pynvml
except (ImportError, Exception):
    pynvml = None

try:
    import torch
except (ImportError, Exception):
    torch = None

# Initialize module logger
logger = logging.getLogger("CoChem.TOPOS.MechanicsMemory")


# ============================================================================
# Enums and Pydantic Data Models
# ============================================================================

class EngineTier(str, Enum):
    """Supported computational engine hierarchy tiers."""
    MACE_OFF24M = "MACE-OFF24m"
    AIMNET2 = "AIMNet2"
    G_XTB = "g-xTB"
    XTB2 = "xTB2"


class FallbackReason(str, Enum):
    """Reasons for triggering a fallback cascade transition."""
    UNSUPPORTED_ELEMENTS = "unsupported_elements"
    INSUFFICIENT_VRAM = "insufficient_vram"
    INSUFFICIENT_RAM = "insufficient_ram"
    NO_CUDA_DEVICE = "no_cuda_device"
    EXECUTION_FAILURE = "execution_failure"
    USER_OVERRIDE = "user_override"
    NONE = "none"


class DeviceType(str, Enum):
    """Target execution device."""
    CPU = "cpu"
    CUDA = "cuda"
    AUTO = "auto"


class PrecisionMode(str, Enum):
    """Floating point precision mode."""
    FP64 = "float64"
    FP32 = "float32"
    FP16 = "float16"
    BF16 = "bfloat16"


class GPUDeviceInfo(BaseModel):
    """Detailed telemetry for an individual GPU device."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    index: int
    name: str
    total_vram_bytes: int
    free_vram_bytes: int
    used_vram_bytes: int
    utilization_pct: float = 0.0
    temperature_c: Optional[float] = None


class HardwareSnapshot(BaseModel):
    """Complete host machine resource snapshot."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: float = Field(default_factory=time.time)
    cpu_count_logical: int
    cpu_count_physical: int
    cpu_percent: float
    ram_total_bytes: int
    ram_available_bytes: int
    ram_used_bytes: int
    ram_percent: float
    swap_total_bytes: int = 0
    swap_free_bytes: int = 0
    cuda_available: bool = False
    gpu_count: int = 0
    gpu_devices: List[GPUDeviceInfo] = Field(default_factory=list)


class CascadeTransition(BaseModel):
    """Audit record of an engine fallback transition."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    from_engine: EngineTier
    to_engine: EngineTier
    reason: FallbackReason
    timestamp: float = Field(default_factory=time.time)
    details: str = ""


class CascadeState(BaseModel):
    """State machine output tracking active engine and execution parameters."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    current_engine: EngineTier
    initial_engine: EngineTier
    target_device: DeviceType = DeviceType.CPU
    precision_mode: PrecisionMode = PrecisionMode.FP32
    is_downgraded: bool = False
    transitions: List[CascadeTransition] = Field(default_factory=list)


class GeometryRecord(BaseModel):
    """Complete molecular geometry tensor payload."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    geom_id: str
    atomic_numbers: List[int]
    coords: List[List[float]]
    energy: float
    gradient: Optional[List[List[float]]] = None
    hessian: Optional[List[List[float]]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("atomic_numbers")
    @classmethod
    def validate_atomic_numbers(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("atomic_numbers list must not be empty.")
        for z in v:
            if not isinstance(z, int) or z < 1 or z > 118:
                raise ValueError(f"Invalid atomic number: {z}")
        return v


class TrajectoryStep(BaseModel):
    """Single step in a molecular dynamics or optimization trajectory."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    geom_id: str
    step_index: int
    coords: List[List[float]]
    energy: float
    forces: Optional[List[List[float]]] = None
    timestamp: float = Field(default_factory=time.time)


class TelemetryRecord(BaseModel):
    """Telemetry log entry capturing runtime metrics."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    record_id: str
    timestamp: float = Field(default_factory=time.time)
    engine: str
    device: str
    batch_size: int
    ram_used_bytes: int
    vram_used_bytes: int = 0
    duration_seconds: Optional[float] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# 1. HDF5 SWMR State Manager
# ============================================================================

class ToposHDF5MemoryManager:
    """
    HDF5 SWMR State Manager for CoChem-TOPOS.
    Dynamically resolves artifact database pathing, initializes landscape.h5
    with SWMR capability and multi-process file locking for concurrent read/write.
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        lock_timeout: float = 30.0,
    ) -> None:
        self.db_path = self._resolve_db_path(db_path)
        self.lock_timeout = lock_timeout
        self.lock_path = Path(f"{self.db_path}.lock")
        self.lock = FileLock(str(self.lock_path), timeout=self.lock_timeout)

        # Initialize the master datastore
        self._initialize_database()

    @staticmethod
    def _resolve_db_path(db_path: Optional[Union[str, Path]] = None) -> Path:
        """Dynamically resolve database path to artifacts directory or workspace."""
        if db_path is not None:
            resolved = Path(db_path).resolve()
        else:
            workspace_env = os.environ.get("COCHEM_WORKSPACE")
            if workspace_env:
                resolved = Path(workspace_env).resolve() / "CoChem_Artifacts" / "Databases" / "landscape.h5"
            else:
                # Default relative fallback to local artifacts/Databases
                resolved = Path.cwd().resolve() / "artifacts" / "Databases" / "landscape.h5"

        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    def _initialize_database(self) -> None:
        """Create and provision master HDF5 database structure with SWMR support."""
        try:
            with self.lock:
                if not self.db_path.exists() or self.db_path.stat().st_size == 0:
                    with h5py.File(self.db_path, "w", libver="latest") as f:
                        f.attrs["description"] = "CoChem-TOPOS Master Tensor Database"
                        f.attrs["pipeline"] = "CoChem-TOPOS"
                        f.attrs["version"] = "2.0"
                        f.attrs["format_version"] = "1.0"
                        f.attrs["created_at"] = time.time()

                        # Core group hierarchy
                        f.create_group("geometries")
                        f.create_group("trajectories")
                        f.create_group("telemetry")
                        f.create_group("metadata")

                        try:
                            f.swmr_mode = True
                        except (AttributeError, RuntimeError):
                            # SWMR mode setting can be driver/platform dependent on creation
                            pass
                    logger.info(f"Initialized HDF5 database at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize HDF5 database at {self.db_path}: {e}")
            raise RuntimeError(f"HDF5 database initialization failed: {e}") from e

    @contextmanager
    def open_reader(self) -> Generator[h5py.File, None, None]:
        """Open HDF5 file in read mode with latest libver (SWMR safe)."""
        f = None
        try:
            try:
                f = h5py.File(self.db_path, "r", libver="latest", swmr=True)
            except (RuntimeError, ValueError):
                f = h5py.File(self.db_path, "r", libver="latest")
            yield f
        finally:
            if f is not None:
                f.close()

    def write_geometry(self, record: Union[GeometryRecord, Dict[str, Any]]) -> None:
        """
        Safely write a molecular geometry and associated tensors to the database.
        """
        if isinstance(record, dict):
            record = GeometryRecord(**record)

        try:
            with self.lock:
                with h5py.File(self.db_path, "a", libver="latest") as f:
                    geoms_grp = f["geometries"]
                    if record.geom_id in geoms_grp:
                        del geoms_grp[record.geom_id]

                    g = geoms_grp.create_group(record.geom_id)
                    g.create_dataset("atomic_numbers", data=np.array(record.atomic_numbers, dtype=np.int32))
                    g.create_dataset("coordinates", data=np.array(record.coords, dtype=np.float64))
                    g.attrs["electronic_energy_hartree"] = float(record.energy)

                    if record.gradient is not None and len(record.gradient) > 0:
                        g.create_dataset("gradient_matrix", data=np.array(record.gradient, dtype=np.float64))

                    if record.hessian is not None and len(record.hessian) > 0:
                        g.create_dataset("hessian_matrix", data=np.array(record.hessian, dtype=np.float64))

                    g.attrs["metadata_json"] = json.dumps(record.metadata)
                    g.attrs["updated_at"] = time.time()
                    f.flush()
            logger.debug(f"Successfully serialized geometry [{record.geom_id}] to {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to write geometry [{record.geom_id}]: {e}")
            raise RuntimeError(f"HDF5 geometry write failure: {e}") from e

    def read_geometry(self, geom_id: str) -> Optional[GeometryRecord]:
        """
        Read a geometry record and its associated tensors.
        """
        try:
            with self.open_reader() as f:
                if "geometries" not in f or geom_id not in f["geometries"]:
                    return None

                g = f["geometries"][geom_id]
                atomic_numbers = g["atomic_numbers"][:].astype(int).tolist()
                coords = g["coordinates"][:].astype(float).tolist()
                energy = float(g.attrs.get("electronic_energy_hartree", 0.0))

                gradient = None
                if "gradient_matrix" in g:
                    gradient = g["gradient_matrix"][:].astype(float).tolist()

                hessian = None
                if "hessian_matrix" in g:
                    hessian = g["hessian_matrix"][:].astype(float).tolist()

                metadata_json = g.attrs.get("metadata_json", "{}")
                try:
                    metadata = json.loads(metadata_json)
                except Exception:
                    metadata = {}

                return GeometryRecord(
                    geom_id=geom_id,
                    atomic_numbers=atomic_numbers,
                    coords=coords,
                    energy=energy,
                    gradient=gradient,
                    hessian=hessian,
                    metadata=metadata,
                )
        except Exception as e:
            logger.error(f"Failed to read geometry [{geom_id}]: {e}")
            return None

    def append_trajectory_step(self, step: Union[TrajectoryStep, Dict[str, Any]]) -> None:
        """
        Append a single step in a molecular dynamics / optimization trajectory.
        """
        if isinstance(step, dict):
            step = TrajectoryStep(**step)

        try:
            with self.lock:
                with h5py.File(self.db_path, "a", libver="latest") as f:
                    trajs_grp = f["trajectories"]
                    if step.geom_id not in trajs_grp:
                        traj_geom = trajs_grp.create_group(step.geom_id)
                    else:
                        traj_geom = trajs_grp[step.geom_id]

                    step_key = f"{step.step_index:06d}"
                    if step_key in traj_geom:
                        del traj_geom[step_key]

                    sg = traj_geom.create_group(step_key)
                    sg.create_dataset("coordinates", data=np.array(step.coords, dtype=np.float64))
                    sg.attrs["energy"] = float(step.energy)
                    sg.attrs["timestamp"] = float(step.timestamp)
                    sg.attrs["step_index"] = int(step.step_index)

                    if step.forces is not None and len(step.forces) > 0:
                        sg.create_dataset("forces", data=np.array(step.forces, dtype=np.float64))

                    f.flush()
        except Exception as e:
            logger.error(f"Failed to append trajectory step for [{step.geom_id}]: {e}")
            raise RuntimeError(f"HDF5 trajectory append failure: {e}") from e

    def read_trajectory(self, geom_id: str) -> List[TrajectoryStep]:
        """
        Read the entire trajectory sequence for a geometry ID, sorted by step index.
        """
        results: List[TrajectoryStep] = []
        try:
            with self.open_reader() as f:
                if "trajectories" not in f or geom_id not in f["trajectories"]:
                    return results

                traj_geom = f["trajectories"][geom_id]
                sorted_step_keys = sorted(traj_geom.keys())

                for step_key in sorted_step_keys:
                    sg = traj_geom[step_key]
                    coords = sg["coordinates"][:].astype(float).tolist()
                    energy = float(sg.attrs.get("energy", 0.0))
                    timestamp = float(sg.attrs.get("timestamp", 0.0))
                    step_index = int(sg.attrs.get("step_index", int(step_key)))

                    forces = None
                    if "forces" in sg:
                        forces = sg["forces"][:].astype(float).tolist()

                    results.append(
                        TrajectoryStep(
                            geom_id=geom_id,
                            step_index=step_index,
                            coords=coords,
                            energy=energy,
                            forces=forces,
                            timestamp=timestamp,
                        )
                    )
            return results
        except Exception as e:
            logger.error(f"Failed to read trajectory for [{geom_id}]: {e}")
            return []

    def record_telemetry(self, telemetry: Union[TelemetryRecord, Dict[str, Any]]) -> None:
        """
        Record host hardware and calculation telemetry.
        """
        if isinstance(telemetry, dict):
            telemetry = TelemetryRecord(**telemetry)

        try:
            with self.lock:
                with h5py.File(self.db_path, "a", libver="latest") as f:
                    telem_grp = f["telemetry"]
                    if telemetry.record_id in telem_grp:
                        del telem_grp[telemetry.record_id]

                    tg = telem_grp.create_group(telemetry.record_id)
                    tg.attrs["timestamp"] = float(telemetry.timestamp)
                    tg.attrs["engine"] = str(telemetry.engine)
                    tg.attrs["device"] = str(telemetry.device)
                    tg.attrs["batch_size"] = int(telemetry.batch_size)
                    tg.attrs["ram_used_bytes"] = int(telemetry.ram_used_bytes)
                    tg.attrs["vram_used_bytes"] = int(telemetry.vram_used_bytes)
                    if telemetry.duration_seconds is not None:
                        tg.attrs["duration_seconds"] = float(telemetry.duration_seconds)
                    tg.attrs["extra_json"] = json.dumps(telemetry.extra)
                    f.flush()
        except Exception as e:
            logger.error(f"Failed to record telemetry [{telemetry.record_id}]: {e}")
            raise RuntimeError(f"HDF5 telemetry write failure: {e}") from e

    def read_telemetry(self, record_id: Optional[str] = None) -> Union[List[TelemetryRecord], Optional[TelemetryRecord]]:
        """
        Read telemetry records. If record_id is specified, returns that single record;
        otherwise returns all records.
        """
        try:
            with self.open_reader() as f:
                if "telemetry" not in f:
                    return None if record_id else []

                telem_grp = f["telemetry"]
                if record_id is not None:
                    if record_id not in telem_grp:
                        return None
                    tg = telem_grp[record_id]
                    return TelemetryRecord(
                        record_id=record_id,
                        timestamp=float(tg.attrs.get("timestamp", 0.0)),
                        engine=str(tg.attrs.get("engine", "")),
                        device=str(tg.attrs.get("device", "cpu")),
                        batch_size=int(tg.attrs.get("batch_size", 1)),
                        ram_used_bytes=int(tg.attrs.get("ram_used_bytes", 0)),
                        vram_used_bytes=int(tg.attrs.get("vram_used_bytes", 0)),
                        duration_seconds=float(tg.attrs.get("duration_seconds")) if "duration_seconds" in tg.attrs else None,
                        extra=json.loads(tg.attrs.get("extra_json", "{}")),
                    )
                else:
                    all_records = []
                    for rid in telem_grp.keys():
                        tg = telem_grp[rid]
                        all_records.append(
                            TelemetryRecord(
                                record_id=rid,
                                timestamp=float(tg.attrs.get("timestamp", 0.0)),
                                engine=str(tg.attrs.get("engine", "")),
                                device=str(tg.attrs.get("device", "cpu")),
                                batch_size=int(tg.attrs.get("batch_size", 1)),
                                ram_used_bytes=int(tg.attrs.get("ram_used_bytes", 0)),
                                vram_used_bytes=int(tg.attrs.get("vram_used_bytes", 0)),
                                duration_seconds=float(tg.attrs.get("duration_seconds")) if "duration_seconds" in tg.attrs else None,
                                extra=json.loads(tg.attrs.get("extra_json", "{}")),
                            )
                        )
                    return all_records
        except Exception as e:
            logger.error(f"Failed to read telemetry: {e}")
            return None if record_id else []

    def list_geometries(self) -> List[str]:
        """List all geometry IDs currently registered in the database."""
        try:
            with self.open_reader() as f:
                if "geometries" in f:
                    return list(f["geometries"].keys())
                return []
        except Exception as e:
            logger.error(f"Failed to list geometries: {e}")
            return []


# ============================================================================
# 2. Dynamic Hardware Resource Broker
# ============================================================================

class HardwareResourceBroker:
    """
    Dynamic hardware resource monitor and calculation capacity broker.
    Polls real psutil and pynvml metrics to compute safe batch sizes
    and prevent host OOM crashes across CPU and GPU hardware tiers.
    """

    def __init__(self) -> None:
        self._nvml_initialized = False

    def _poll_gpu_devices(self) -> List[GPUDeviceInfo]:
        """Poll NVIDIA GPU devices via pynvml with fail-safe exception handling."""
        gpus: List[GPUDeviceInfo] = []
        if pynvml is None:
            return gpus

        try:
            if not self._nvml_initialized:
                pynvml.nvmlInit()
                self._nvml_initialized = True

            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                raw_name = pynvml.nvmlDeviceGetName(handle)
                name = raw_name.decode("utf-8") if isinstance(raw_name, bytes) else str(raw_name)

                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
                except Exception:
                    util = 0.0

                try:
                    temp = float(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
                except Exception:
                    temp = None

                gpus.append(
                    GPUDeviceInfo(
                        index=i,
                        name=name,
                        total_vram_bytes=int(mem_info.total),
                        free_vram_bytes=int(mem_info.free),
                        used_vram_bytes=int(mem_info.used),
                        utilization_pct=float(util),
                        temperature_c=temp,
                    )
                )
        except Exception as e:
            logger.debug(f"NVIDIA GPU polling inactive or unavailable: {e}")
            self._nvml_initialized = False

        return gpus

    def poll_hardware(self) -> HardwareSnapshot:
        """Capture an instantaneous hardware resource snapshot."""
        cpu_perc = float(psutil.cpu_percent(interval=None))
        cpu_logical = psutil.cpu_count(logical=True) or 1
        cpu_physical = psutil.cpu_count(logical=False) or cpu_logical

        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()

        gpus = self._poll_gpu_devices()
        cuda_avail = len(gpus) > 0

        return HardwareSnapshot(
            timestamp=time.time(),
            cpu_count_logical=cpu_logical,
            cpu_count_physical=cpu_physical,
            cpu_percent=cpu_perc,
            ram_total_bytes=int(vm.total),
            ram_available_bytes=int(vm.available),
            ram_used_bytes=int(vm.used),
            ram_percent=float(vm.percent),
            swap_total_bytes=int(swap.total),
            swap_free_bytes=int(swap.free),
            cuda_available=cuda_avail,
            gpu_count=len(gpus),
            gpu_devices=gpus,
        )

    def calculate_safe_batch_size(
        self,
        num_atoms: int,
        engine: Union[EngineTier, str],
        target_device: Union[DeviceType, str] = DeviceType.AUTO,
        memory_safety_factor: float = 0.75,
    ) -> int:
        """
        Calculate the maximum safe ASE batch size to prevent OOM segmentation faults.
        
        Args:
            num_atoms: Number of atoms in the molecular system.
            engine: Computational engine tier.
            target_device: CPU, CUDA, or AUTO.
            memory_safety_factor: Fraction of available memory permitted (default 0.75).
            
        Returns:
            int: Safe batch size (>= 1).
        """
        snapshot = self.poll_hardware()
        engine_str = engine.value if isinstance(engine, EngineTier) else str(engine)
        dev_str = target_device.value if isinstance(target_device, DeviceType) else str(target_device).lower()

        # Resolve target device if AUTO
        if dev_str == DeviceType.AUTO.value:
            if snapshot.cuda_available and snapshot.gpu_devices:
                dev_str = DeviceType.CUDA.value
            else:
                dev_str = DeviceType.CPU.value

        # Determine available memory pool
        if dev_str == DeviceType.CUDA.value and snapshot.gpu_devices:
            # Pick device with the most free VRAM
            best_gpu = max(snapshot.gpu_devices, key=lambda g: g.free_vram_bytes)
            usable_bytes = best_gpu.free_vram_bytes * memory_safety_factor
        else:
            usable_bytes = snapshot.ram_available_bytes * memory_safety_factor

        # Estimate memory scaling per atom and engine model
        # Base overhead + per-sample memory footprint in bytes
        if "MACE" in engine_str:
            base_overhead = 300 * 1024 * 1024  # ~300MB base model
            mem_per_sample = max(1024 * 1024, num_atoms * 3 * 1024 * 1024)
            max_ceiling = 128
        elif "AIMNet" in engine_str:
            base_overhead = 200 * 1024 * 1024  # ~200MB base model
            mem_per_sample = max(1024 * 1024, num_atoms * 2 * 1024 * 1024)
            max_ceiling = 128
        elif "g-xTB" in engine_str:
            base_overhead = 50 * 1024 * 1024   # ~50MB runtime
            # O(N^2) scaling for semi-empirical Hamiltonian
            mem_per_sample = max(512 * 1024, int((num_atoms * 12) ** 2 * 8))
            max_ceiling = 256
        else:  # xTB2 or generic semi-empirical
            base_overhead = 60 * 1024 * 1024   # ~60MB runtime
            mem_per_sample = max(512 * 1024, int((num_atoms * 16) ** 2 * 8))
            max_ceiling = 256

        available_for_batch = max(0, usable_bytes - base_overhead)
        calculated_batch = int(available_for_batch // mem_per_sample)
        safe_batch = max(1, min(calculated_batch, max_ceiling))

        logger.debug(
            f"Calculated safe batch size: {safe_batch} (Atoms: {num_atoms}, Engine: {engine_str}, Device: {dev_str})"
        )
        return safe_batch

    def check_memory_headroom(
        self,
        required_bytes: int,
        target_device: Union[DeviceType, str] = DeviceType.AUTO,
    ) -> bool:
        """Verify if host machine has sufficient headroom for a required allocation."""
        snapshot = self.poll_hardware()
        dev_str = target_device.value if isinstance(target_device, DeviceType) else str(target_device).lower()

        if dev_str == DeviceType.AUTO.value:
            dev_str = DeviceType.CUDA.value if snapshot.cuda_available else DeviceType.CPU.value

        if dev_str == DeviceType.CUDA.value and snapshot.gpu_devices:
            max_vram = max(g.free_vram_bytes for g in snapshot.gpu_devices)
            return max_vram >= required_bytes
        else:
            return snapshot.ram_available_bytes >= required_bytes

    def get_optimal_device(
        self,
        engine: Union[EngineTier, str],
        required_vram_bytes: int = 1536 * 1024 * 1024,
    ) -> DeviceType:
        """Determine optimal execution device (CUDA vs CPU) based on engine and hardware."""
        engine_str = engine.value if isinstance(engine, EngineTier) else str(engine)

        # Classical/Semi-empirical xTB natively defaults to multi-core CPU
        if engine_str in (EngineTier.G_XTB.value, EngineTier.XTB2.value):
            return DeviceType.CPU

        snapshot = self.poll_hardware()
        if snapshot.cuda_available and snapshot.gpu_devices:
            best_gpu = max(snapshot.gpu_devices, key=lambda g: g.free_vram_bytes)
            if best_gpu.free_vram_bytes >= required_vram_bytes:
                return DeviceType.CUDA

        return DeviceType.CPU


# ============================================================================
# 3. Universal Fallback Cascade State Machine
# ============================================================================

class UniversalFallbackCascade:
    """
    Elemental compatibility definitions and tier cascade rules.
    Hierarchy: MACE-OFF24m -> AIMNet2 -> g-xTB -> xTB2.
    """

    # Element support sets (Atomic Numbers Z)
    # MACE-OFF24m: Standard organic/biomolecular subset (H, C, N, O, F, P, S, Cl, Br, I)
    MACE_OFF24M_ELEMENTS: Set[int] = {1, 6, 7, 8, 9, 15, 16, 17, 35, 53}

    # AIMNet2: Extended organic subset (H, B, C, N, O, F, Si, P, S, Cl, As, Se, Br, I)
    AIMNET2_ELEMENTS: Set[int] = {1, 5, 6, 7, 8, 9, 14, 15, 16, 17, 33, 34, 35, 53}

    # g-xTB and xTB2 support elements Z=1 through Z=86 (up to Radon)
    XTB_ELEMENTS: Set[int] = set(range(1, 87))

    @classmethod
    def get_supported_elements(cls, engine: Union[EngineTier, str]) -> Set[int]:
        """Return the set of supported atomic numbers for an engine."""
        engine_tier = EngineTier(engine) if isinstance(engine, str) else engine
        if engine_tier == EngineTier.MACE_OFF24M:
            return cls.MACE_OFF24M_ELEMENTS
        elif engine_tier == EngineTier.AIMNET2:
            return cls.AIMNET2_ELEMENTS
        elif engine_tier in (EngineTier.G_XTB, EngineTier.XTB2):
            return cls.XTB_ELEMENTS
        return set()

    @classmethod
    def validate_elements(
        cls,
        atomic_numbers: Sequence[int],
        engine: Union[EngineTier, str],
    ) -> Tuple[bool, List[int]]:
        """
        Validate whether all elements in the composition are supported by the engine.
        
        Returns:
            Tuple[bool, List[int]]: (is_supported, list_of_unsupported_atomic_numbers)
        """
        supported = cls.get_supported_elements(engine)
        unsupported = [z for z in atomic_numbers if z not in supported]
        return len(unsupported) == 0, sorted(list(set(unsupported)))

    @classmethod
    def get_next_tier(cls, engine: EngineTier) -> Optional[EngineTier]:
        """Return the next fallback engine tier in the cascade hierarchy."""
        cascade_map = {
            EngineTier.MACE_OFF24M: EngineTier.AIMNET2,
            EngineTier.AIMNET2: EngineTier.G_XTB,
            EngineTier.G_XTB: EngineTier.XTB2,
            EngineTier.XTB2: None,
        }
        return cascade_map.get(engine)


class FallbackCascadeStateMachine:
    """
    Autonomous state machine executing the universal calculation fallback cascade.
    Dynamically routes molecular calculations based on elemental composition
    and physical host hardware constraints.
    """

    def __init__(self, broker: Optional[HardwareResourceBroker] = None) -> None:
        self.broker = broker or HardwareResourceBroker()

    def resolve_engine(
        self,
        atomic_numbers: Sequence[int],
        requested_engine: Optional[Union[EngineTier, str]] = None,
        broker: Optional[HardwareResourceBroker] = None,
        require_gpu_for_mlff: bool = True,
    ) -> CascadeState:
        """
        Resolve the appropriate computational engine tier for a molecular system.
        
        Args:
            atomic_numbers: Atomic numbers of the system.
            requested_engine: Initial target engine (default: MACE-OFF24m).
            broker: Hardware resource broker instance.
            require_gpu_for_mlff: Whether MLFF requires CUDA availability.
            
        Returns:
            CascadeState: Final resolved state with audit trail of transitions.
        """
        active_broker = broker or self.broker
        initial_tier = (
            EngineTier(requested_engine)
            if isinstance(requested_engine, str)
            else (requested_engine or EngineTier.MACE_OFF24M)
        )

        current_tier = initial_tier
        transitions: List[CascadeTransition] = []
        is_downgraded = False

        # Step 1: Resolve elemental compatibility cascade
        while True:
            is_supp, unsupp = UniversalFallbackCascade.validate_elements(atomic_numbers, current_tier)
            if is_supp:
                break

            next_tier = UniversalFallbackCascade.get_next_tier(current_tier)
            if next_tier is None:
                # Reached bottom of cascade
                break

            transition = CascadeTransition(
                from_engine=current_tier,
                to_engine=next_tier,
                reason=FallbackReason.UNSUPPORTED_ELEMENTS,
                details=f"Unsupported atomic numbers: {unsupp}",
            )
            transitions.append(transition)
            logger.warning(
                f"Cascade trigger: {current_tier.value} -> {next_tier.value} due to unsupported elements {unsupp}"
            )
            current_tier = next_tier
            is_downgraded = True

        # Step 2: Resolve hardware resource limits
        snapshot = active_broker.poll_hardware()
        target_device = active_broker.get_optimal_device(current_tier)

        if require_gpu_for_mlff and current_tier in (EngineTier.MACE_OFF24M, EngineTier.AIMNET2):
            if not snapshot.cuda_available or target_device == DeviceType.CPU:
                # If GPU is required for MLFF but unavailable, route to semi-empirical CPU engine
                next_tier = EngineTier.G_XTB
                transition = CascadeTransition(
                    from_engine=current_tier,
                    to_engine=next_tier,
                    reason=FallbackReason.NO_CUDA_DEVICE if not snapshot.cuda_available else FallbackReason.INSUFFICIENT_VRAM,
                    details="GPU acceleration unavailable for MLFF tier; routing to CPU semi-empirical cascade.",
                )
                transitions.append(transition)
                logger.info(f"Hardware cascade trigger: {current_tier.value} -> {next_tier.value} (No CUDA device)")
                current_tier = next_tier
                target_device = DeviceType.CPU
                is_downgraded = True

        # Step 3: Precision mode determination
        precision_mode = PrecisionMode.FP32 if target_device == DeviceType.CPU else PrecisionMode.FP32

        return CascadeState(
            current_engine=current_tier,
            initial_engine=initial_tier,
            target_device=target_device,
            precision_mode=precision_mode,
            is_downgraded=is_downgraded,
            transitions=transitions,
        )

    def step_fallback(
        self,
        state: CascadeState,
        reason: FallbackReason,
        details: str = "",
    ) -> CascadeState:
        """
        Advance the state machine to the next available tier in response to runtime failure.
        """
        next_tier = UniversalFallbackCascade.get_next_tier(state.current_engine)
        if next_tier is None:
            # Already at terminal tier (xTB2)
            transition = CascadeTransition(
                from_engine=state.current_engine,
                to_engine=state.current_engine,
                reason=reason,
                details=f"Terminal tier reached. Cannot downgrade further. {details}",
            )
            state.transitions.append(transition)
            return state

        target_device = DeviceType.CPU if next_tier in (EngineTier.G_XTB, EngineTier.XTB2) else state.target_device
        precision_mode = PrecisionMode.FP32 if target_device == DeviceType.CPU else state.precision_mode

        transition = CascadeTransition(
            from_engine=state.current_engine,
            to_engine=next_tier,
            reason=reason,
            details=details,
        )

        return CascadeState(
            current_engine=next_tier,
            initial_engine=state.initial_engine,
            target_device=target_device,
            precision_mode=precision_mode,
            is_downgraded=True,
            transitions=state.transitions + [transition],
        )


# ============================================================================
# 4. Precision Downgrade Protocol
# ============================================================================

class PrecisionDowngradeProtocol:
    """
    Precision Downgrade Protocol.
    Detects GPU -> CPU routing and casts model weights, tensors, and arrays
    from FP64 to FP32 to preserve runtime viability and prevent host RAM saturation.
    """

    @staticmethod
    def should_downgrade(
        source_device: Union[DeviceType, str],
        target_device: Union[DeviceType, str],
        available_ram_bytes: Optional[int] = None,
    ) -> bool:
        """
        Determine if precision downgrade (FP64 -> FP32) is required.
        """
        src = source_device.value if isinstance(source_device, DeviceType) else str(source_device).lower()
        dst = target_device.value if isinstance(target_device, DeviceType) else str(target_device).lower()

        # Downgrade when execution moves from GPU to CPU
        if src == DeviceType.CUDA.value and dst == DeviceType.CPU.value:
            return True

        # Downgrade if system RAM is critically constrained (< 4 GB available)
        if available_ram_bytes is not None and available_ram_bytes < 4 * 1024 * 1024 * 1024:
            return True

        return False

    @classmethod
    def downgrade_tensors(cls, data: Any, target_dtype: str = "float32") -> Any:
        """
        Recursively traverse and cast PyTorch tensors and NumPy arrays from FP64 to FP32.
        
        Args:
            data: Arbitrary structure (tensor, array, dict, list, tuple, primitive).
            target_dtype: Target precision string ("float32" or "float64").
            
        Returns:
            Precision-converted data structure.
        """
        # PyTorch Tensor handling
        if torch is not None and isinstance(data, torch.Tensor):
            if target_dtype == "float32" and data.dtype == torch.float64:
                return data.to(torch.float32)
            elif target_dtype == "float64" and data.dtype == torch.float32:
                return data.to(torch.float64)
            return data

        # PyTorch nn.Module handling
        if torch is not None and hasattr(torch, "nn") and isinstance(data, torch.nn.Module):
            if target_dtype == "float32":
                return data.to(torch.float32)
            return data

        # NumPy ndarray handling
        if isinstance(data, np.ndarray):
            if target_dtype == "float32" and data.dtype == np.float64:
                return data.astype(np.float32)
            elif target_dtype == "float64" and data.dtype == np.float32:
                return data.astype(np.float64)
            return data

        # Dictionary traversal
        if isinstance(data, dict):
            return {k: cls.downgrade_tensors(v, target_dtype) for k, v in data.items()}

        # List traversal
        if isinstance(data, list):
            return [cls.downgrade_tensors(item, target_dtype) for item in data]

        # Tuple traversal
        if isinstance(data, tuple):
            return tuple(cls.downgrade_tensors(item, target_dtype) for item in data)

        return data

    @classmethod
    def downgrade_model_weights(cls, model_or_weights: Any) -> Any:
        """Cast PyTorch model parameters or state dict to FP32."""
        return cls.downgrade_tensors(model_or_weights, target_dtype="float32")
