Perform adversarial static analysis and logical review on implemented code for D:\__CoChem\__agentic\.prompts\.SRS\CoChem-TOPOS\.in-progress\02_05_mechanics_memory.md.
Original prompt:
# Task: Implement Air-Gapped Router (`cochem_topos_memory.py`)

## Target Output File
`${COCHEM_WORKSPACE}\GitHub-Repo\CoChem-TOPOS\mechanics\cochem_topos_memory.py`

## Objective
Act as the central hardware broker and database initializer, bridging the immutable code environment with the dynamic execution limits of the host machine across the 6-Tier Environment Matrix.

## Context & Architecture Rules
This module (Stage 2.0) must prevent the pipeline from requesting tensor sizes that exceed physical hardware limits. It strictly adheres to the Tripartite Air-Gap Policy.

## Execution Directives
Implement the `cochem_topos_memory.py` script with the following capabilities:

1. **HDF5 SWMR State Manager**: Initialize the master `landscape.h5` tensor database using OS-specific pathing to dynamically resolve to the artifacts directory (e.g., `${COCHEM_WORKSPACE}/CoChem_Artifacts/Databases/`). Open the database with `libver='latest'` and `swmr=True` in `h5py` to allow concurrent reading of geometry trajectories and telemetry via IPC while the engine writes.
2. **Dynamic Resource Brokering**: Import `psutil` (for CPU/RAM) and `pynvml` (for CUDA VRAM) to constantly poll available hardware before every calculation. Cap the ASE calculation batch sizes to prevent OOM segment faults.
3. **Universal Fallback Cascade**: Instantiate a calculation hierarchy state machine based on elemental composition and hardware limits. If heavy metals or unsupported elements are detected by the primary MLFF, dynamically downgrade the engine cascade: MACE-OFF24m -> AIMNet2 -> g-xTB -> xTB2.
4. **Precision Downgrade Protocol**: Detect if the fallback cascade has routed execution from GPU to CPU. If true, cast model weights from FP64 to FP32 to preserve timeline viability and prevent RAM saturation.

Modified files content:

--- D:\__CoChem\GitHub-Repo\CoChem-TOPOS\tests\test_cochem_topos_memory.py ---
"""
Unit and integration tests for CoChem-TOPOS Stage 2.0 Mechanics Memory Subsystem.
Strict Zero-Mock Mandate: Uses real h5py files, real psutil metrics, real torch tensors,
real numpy arrays, real elemental definitions, and real concurrent filelock access.
"""

import os
import time
import concurrent.futures
from pathlib import Path
import pytest
import numpy as np
import torch

from mechanics.cochem_topos_memory import (
    ToposHDF5MemoryManager,
    HardwareResourceBroker,
    HardwareSnapshot,
    GPUDeviceInfo,
    UniversalFallbackCascade,
    FallbackCascadeStateMachine,
    EngineTier,
    FallbackReason,
    DeviceType,
    PrecisionMode,
    CascadeState,
    PrecisionDowngradeProtocol,
    GeometryRecord,
    TrajectoryStep,
    TelemetryRecord,
)


# ============================================================================
# 1. HDF5 SWMR State Manager Tests
# ============================================================================

class TestToposHDF5MemoryManager:
    """Tests for ToposHDF5MemoryManager with real HDF5 files and file locking."""

    def test_database_initialization_and_path_resolution(self, tmp_path: Path):
        """Test database creation, root attributes, and directory resolution."""
        db_file = tmp_path / "test_landscape.h5"
        manager = ToposHDF5MemoryManager(db_path=db_file)
        
        assert manager.db_path == db_file
        assert manager.lock_path == Path(f"{db_file}.lock")
        with manager.lock:
            assert manager.lock_path.exists()

        # Check groups and root attributes
        with manager.open_reader() as f:
            assert f.attrs["pipeline"] == "CoChem-TOPOS"
            assert "version" in f.attrs
            assert "geometries" in f
            assert "trajectories" in f
            assert "telemetry" in f
            assert "metadata" in f

    def test_dynamic_path_resolution_with_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Test path resolution when COCHEM_WORKSPACE is set in environment."""
        workspace_dir = tmp_path / "custom_workspace"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("COCHEM_WORKSPACE", str(workspace_dir))

        manager = ToposHDF5MemoryManager()
        expected_path = workspace_dir / "CoChem_Artifacts" / "Databases" / "landscape.h5"
        assert manager.db_path == expected_path
        assert expected_path.exists()

    def test_write_and_read_geometry_record(self, tmp_path: Path):
        """Test writing and reading a complete geometry record with tensors."""
        db_file = tmp_path / "geom_test.h5"
        manager = ToposHDF5MemoryManager(db_path=db_file)

        # Real water molecule (H2O) data
        atomic_numbers = [8, 1, 1]
        coords = [
            [0.0, 0.0, 0.1173],
            [0.0, 0.7572, -0.4692],
            [0.0, -0.7572, -0.4692],
        ]
        energy = -76.432154
        gradient = [
            [0.0001, -0.0002, 0.0003],
            [-0.0001, 0.0001, -0.0001],
            [0.0000, 0.0001, -0.0002],
        ]
        hessian = np.eye(9, dtype=np.float64).tolist()
        metadata = {"basis": "def2-TZVP", "charge": 0, "multiplicity": 1}

        record = GeometryRecord(
            geom_id="H2O_opt_01",
            atomic_numbers=atomic_numbers,
            coords=coords,
            energy=energy,
            gradient=gradient,
            hessian=hessian,
            metadata=metadata,
        )

        manager.write_geometry(record)

        # Read back and verify
        read_record = manager.read_geometry("H2O_opt_01")
        assert read_record is not None
        assert read_record.geom_id == "H2O_opt_01"
        assert read_record.atomic_numbers == atomic_numbers
        assert np.allclose(read_record.coords, coords)
        assert pytest.approx(read_record.energy, 1e-6) == energy
        assert read_record.gradient is not None
        assert np.allclose(read_record.gradient, gradient)
        assert read_record.hessian is not None
        assert np.allclose(read_record.hessian, hessian)
        assert read_record.metadata["basis"] == "def2-TZVP"

        # List geometries
        geoms = manager.list_geometries()
        assert "H2O_opt_01" in geoms

    def test_trajectory_append_and_read(self, tmp_path: Path):
        """Test writing and reading time-series trajectory steps."""
        db_file = tmp_path / "traj_test.h5"
        manager = ToposHDF5MemoryManager(db_path=db_file)

        geom_id = "traj_mol_42"
        steps_data = []
        for step in range(5):
            t_step = TrajectoryStep(
                geom_id=geom_id,
                step_index=step,
                coords=[[0.0, 0.0, float(step)], [1.0, 1.0, float(step)]],
                energy=-100.0 - float(step) * 0.1,
                forces=[[0.01 * step, 0.0, -0.02], [-0.01 * step, 0.0, 0.02]],
                timestamp=time.time() + step,
            )
            manager.append_trajectory_step(t_step)
            steps_data.append(t_step)

        # Read trajectory back
        read_steps = manager.read_trajectory(geom_id)
        assert len(read_steps) == 5
        for i, s in enumerate(read_steps):
            assert s.step_index == i
            assert pytest.approx(s.energy, 1e-6) == steps_data[i].energy
            assert np.allclose(s.coords, steps_data[i].coords)
            assert np.allclose(s.forces, steps_data[i].forces)

    def test_telemetry_recording_and_retrieval(self, tmp_path: Path):
        """Test recording and reading hardware/engine telemetry."""
        db_file = tmp_path / "telem_test.h5"
        manager = ToposHDF5MemoryManager(db_path=db_file)

        t_rec1 = TelemetryRecord(
            record_id="tel_001",
            timestamp=time.time(),
            engine="MACE-OFF24m",
            device="cuda",
            batch_size=32,
            ram_used_bytes=4294967296,
            vram_used_bytes=2147483648,
            duration_seconds=1.24,
            extra={"temperature_c": 54.0, "status": "nominal"},
        )
        t_rec2 = TelemetryRecord(
            record_id="tel_002",
            timestamp=time.time() + 1,
            engine="xTB2",
            device="cpu",
            batch_size=8,
            ram_used_bytes=3221225472,
            vram_used_bytes=0,
            duration_seconds=0.45,
            extra={"status": "nominal"},
        )

        manager.record_telemetry(t_rec1)
        manager.record_telemetry(t_rec2)

        retrieved1 = manager.read_telemetry("tel_001")
        assert retrieved1 is not None
        assert retrieved1.engine == "MACE-OFF24m"
        assert retrieved1.device == "cuda"
        assert retrieved1.batch_size == 32
        assert retrieved1.extra.get("temperature_c") == 54.0

        all_telems = manager.read_telemetry()
        assert len(all_telems) == 2

    def test_concurrent_read_write_safety(self, tmp_path: Path):
        """Test multi-threaded concurrent write and read operations."""
        db_file = tmp_path / "concurrent_test.h5"
        manager = ToposHDF5MemoryManager(db_path=db_file)

        def worker_write(idx: int):
            record = GeometryRecord(
                geom_id=f"geom_worker_{idx}",
                atomic_numbers=[1, 1],
                coords=[[0.0, 0.0, 0.0], [0.0, 0.0, float(idx) * 0.1]],
                energy=-1.0 - float(idx),
                metadata={"worker_idx": idx},
            )
            manager.write_geometry(record)
            return idx

        def worker_read(idx: int):
            # Attempt to read existing or just-written geometry
            return manager.read_geometry(f"geom_worker_{idx}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            # Write 20 records concurrently
            write_futures = [executor.submit(worker_write, i) for i in range(20)]
            for f in concurrent.futures.as_completed(write_futures):
                assert f.result() >= 0

            # Read them concurrently
            read_futures = [executor.submit(worker_read, i) for i in range(20)]
            for f in concurrent.futures.as_completed(read_futures):
                res = f.result()
                assert res is not None
                assert res.geom_id.startswith("geom_worker_")

        geoms = manager.list_geometries()
        assert len(geoms) == 20

    def test_nonexistent_geometry_returns_none(self, tmp_path: Path):
        """Test that reading a non-existent geometry safely returns None."""
        db_file = tmp_path / "empty_test.h5"
        manager = ToposHDF5MemoryManager(db_path=db_file)
        assert manager.read_geometry("non_existent_key") is None


# ============================================================================
# 2. Dynamic Hardware Resource Broker Tests
# ============================================================================

class TestHardwareResourceBroker:
    """Tests for HardwareResourceBroker with real psutil and pynvml polling."""

    def test_real_psutil_hardware_snapshot(self):
        """Test real system metrics polling with psutil."""
        broker = HardwareResourceBroker()
        snapshot = broker.poll_hardware()

        assert isinstance(snapshot, HardwareSnapshot)
        assert snapshot.timestamp > 0
        assert snapshot.cpu_count_logical > 0
        assert snapshot.cpu_count_physical > 0
        assert snapshot.ram_total_bytes > 0
        assert snapshot.ram_available_bytes > 0
        assert 0.0 <= snapshot.ram_percent <= 100.0
        assert 0.0 <= snapshot.cpu_percent <= 100.0
        assert isinstance(snapshot.cuda_available, bool)
        assert isinstance(snapshot.gpu_devices, list)

    def test_pynvml_safe_handling(self):
        """Test NVML polling executes cleanly without throwing unhandled exceptions."""
        broker = HardwareResourceBroker()
        # Direct call to GPU polling helper
        gpus = broker._poll_gpu_devices()
        assert isinstance(gpus, list)
        for gpu in gpus:
            assert isinstance(gpu, GPUDeviceInfo)
            assert gpu.total_vram_bytes >= 0
            assert gpu.free_vram_bytes >= 0
            assert gpu.used_vram_bytes >= 0

    def test_safe_batch_size_calculation(self):
        """Test dynamic calculation of safe ASE batch size to prevent OOM."""
        broker = HardwareResourceBroker()

        # Small molecule (10 atoms) vs Large molecule (300 atoms)
        small_batch_mace = broker.calculate_safe_batch_size(num_atoms=10, engine=EngineTier.MACE_OFF24M)
        large_batch_mace = broker.calculate_safe_batch_size(num_atoms=300, engine=EngineTier.MACE_OFF24M)

        assert small_batch_mace >= 1
        assert large_batch_mace >= 1
        assert small_batch_mace >= large_batch_mace

        # Semi-empirical calculation batch sizing
        small_batch_xtb = broker.calculate_safe_batch_size(num_atoms=10, engine=EngineTier.XTB2)
        large_batch_xtb = broker.calculate_safe_batch_size(num_atoms=500, engine=EngineTier.XTB2)
        assert small_batch_xtb >= 1
        assert large_batch_xtb >= 1
        assert small_batch_xtb >= large_batch_xtb

    def test_memory_headroom_check(self):
        """Test available memory headroom checks."""
        broker = HardwareResourceBroker()

        # 1 MB should always have headroom on any modern machine
        assert broker.check_memory_headroom(required_bytes=1024 * 1024, target_device=DeviceType.CPU) is True

        # 1 Petabyte should always fail
        assert broker.check_memory_headroom(required_bytes=1024**5, target_device=DeviceType.CPU) is False

    def test_get_optimal_device(self):
        """Test optimal device selection based on engine and hardware."""
        broker = HardwareResourceBroker()
        device = broker.get_optimal_device(engine=EngineTier.XTB2)
        # xTB2 defaults to CPU
        assert device == DeviceType.CPU


# ============================================================================
# 3. Universal Fallback Cascade Tests
# ============================================================================

class TestUniversalFallbackCascade:
    """Tests for UniversalFallbackCascade and FallbackCascadeStateMachine."""

    def test_element_support_validation(self):
        """Test element compatibility checking across engine tiers."""
        cascade = UniversalFallbackCascade()

        # Water: H (1), O (8) -> supported by all
        h2o = [1, 1, 8]
        assert cascade.validate_elements(h2o, EngineTier.MACE_OFF24M)[0] is True
        assert cascade.validate_elements(h2o, EngineTier.AIMNET2)[0] is True
        assert cascade.validate_elements(h2o, EngineTier.G_XTB)[0] is True
        assert cascade.validate_elements(h2o, EngineTier.XTB2)[0] is True

        # Boron / Silicon (B=5, Si=14) -> Not in standard MACE-OFF24m, but in AIMNet2
        borane = [5, 1, 1, 1]
        assert cascade.validate_elements(borane, EngineTier.MACE_OFF24M)[0] is False
        assert cascade.validate_elements(borane, EngineTier.AIMNET2)[0] is True

        # Platinum / Iron (Pt=78, Fe=26) -> Heavy/Transition metals not in MACE/AIMNet2, supported in xTB
        cisplatin = [78, 17, 17, 7, 7, 1, 1, 1, 1, 1, 1]
        assert cascade.validate_elements(cisplatin, EngineTier.MACE_OFF24M)[0] is False
        assert cascade.validate_elements(cisplatin, EngineTier.AIMNET2)[0] is False
        assert cascade.validate_elements(cisplatin, EngineTier.G_XTB)[0] is True
        assert cascade.validate_elements(cisplatin, EngineTier.XTB2)[0] is True

    def test_state_machine_organic_resolution(self):
        """Test resolution for purely organic molecule stays at MACE-OFF24m if hardware allows."""
        sm = FallbackCascadeStateMachine()
        ethanol = [6, 6, 8, 1, 1, 1, 1, 1, 1]
        
        # When GPU is available (or CPU allowed for MLFF)
        state = sm.resolve_engine(atomic_numbers=ethanol, requested_engine=EngineTier.MACE_OFF24M, require_gpu_for_mlff=False)
        assert state.current_engine == EngineTier.MACE_OFF24M
        assert not state.is_downgraded

    def test_state_machine_cascade_on_unsupported_elements(self):
        """Test automatic downgrade cascade when elements are unsupported."""
        sm = FallbackCascadeStateMachine()

        # Case 1: Silicon -> cascades MACE-OFF24m -> AIMNet2
        silane = [14, 1, 1, 1, 1]
        state_silane = sm.resolve_engine(atomic_numbers=silane, requested_engine=EngineTier.MACE_OFF24M, require_gpu_for_mlff=False)
        assert state_silane.current_engine == EngineTier.AIMNET2
        assert state_silane.is_downgraded
        assert len(state_silane.transitions) == 1
        assert state_silane.transitions[0].reason == FallbackReason.UNSUPPORTED_ELEMENTS

        # Case 2: Ferrocene (Fe=26) -> cascades MACE-OFF24m -> AIMNet2 -> g-xTB
        ferrocene = [26, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
        state_fe = sm.resolve_engine(atomic_numbers=ferrocene, requested_engine=EngineTier.MACE_OFF24M, require_gpu_for_mlff=False)
        assert state_fe.current_engine in (EngineTier.G_XTB, EngineTier.XTB2)
        assert state_fe.is_downgraded
        assert len(state_fe.transitions) >= 1

    def test_manual_step_fallback_sequence(self):
        """Test explicit step-by-step state machine transition down the hierarchy."""
        sm = FallbackCascadeStateMachine()
        state = CascadeState(
            current_engine=EngineTier.MACE_OFF24M,
            initial_engine=EngineTier.MACE_OFF24M,
            target_device=DeviceType.CUDA,
            precision_mode=PrecisionMode.FP32,
        )

        # Step 1: MACE -> AIMNet2
        state = sm.step_fallback(state, FallbackReason.INSUFFICIENT_VRAM, "VRAM below 2GB")
        assert state.current_engine == EngineTier.AIMNET2
        assert state.is_downgraded

        # Step 2: AIMNet2 -> g-xTB
        state = sm.step_fallback(state, FallbackReason.NO_CUDA_DEVICE, "Switching to CPU")
        assert state.current_engine == EngineTier.G_XTB
        assert state.target_device == DeviceType.CPU
        assert state.precision_mode == PrecisionMode.FP32

        # Step 3: g-xTB -> xTB2
        state = sm.step_fallback(state, FallbackReason.EXECUTION_FAILURE, "g-xTB convergence failure")
        assert state.current_engine == EngineTier.XTB2

        # Step 4: xTB2 is terminal
        terminal_state = sm.step_fallback(state, FallbackReason.EXECUTION_FAILURE, "Terminal failure")
        assert terminal_state.current_engine == EngineTier.XTB2  # Remains at xTB2 with recorded failure


# ============================================================================
# 4. Precision Downgrade Protocol Tests
# ============================================================================

class TestPrecisionDowngradeProtocol:
    """Tests for PrecisionDowngradeProtocol casting FP64 to FP32 for CPU/memory efficiency."""

    def test_torch_tensor_downgrade(self):
        """Test converting PyTorch float64 tensors to float32."""
        proto = PrecisionDowngradeProtocol()
        t_fp64 = torch.tensor([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=torch.float64)
        assert t_fp64.dtype == torch.float64

        t_fp32 = proto.downgrade_tensors(t_fp64)
        assert isinstance(t_fp32, torch.Tensor)
        assert t_fp32.dtype == torch.float32
        assert torch.allclose(t_fp64.to(torch.float32), t_fp32)

    def test_numpy_array_downgrade(self):
        """Test converting NumPy float64 arrays to float32."""
        proto = PrecisionDowngradeProtocol()
        arr_fp64 = np.array([1.123456789, 2.987654321], dtype=np.float64)
        assert arr_fp64.dtype == np.float64

        arr_fp32 = proto.downgrade_tensors(arr_fp64)
        assert isinstance(arr_fp32, np.ndarray)
        assert arr_fp32.dtype == np.float32
        assert np.allclose(arr_fp64.astype(np.float32), arr_fp32)

    def test_nested_collection_downgrade(self):
        """Test recursive conversion across nested dicts, lists, and tuples."""
        proto = PrecisionDowngradeProtocol()
        data = {
            "geom_id": "water_01",
            "coords": np.array([[0.0, 0.0, 0.0]], dtype=np.float64),
            "energy": torch.tensor(-76.4, dtype=torch.float64),
            "nested_list": [
                np.array([1.0, 2.0], dtype=np.float64),
                {"sub_tensor": torch.tensor([3.0, 4.0], dtype=torch.float64)},
                "string_data",
                42,
            ],
        }

        downgraded = proto.downgrade_tensors(data)
        assert downgraded["coords"].dtype == np.float32
        assert downgraded["energy"].dtype == torch.float32
        assert downgraded["nested_list"][0].dtype == np.float32
        assert downgraded["nested_list"][1]["sub_tensor"].dtype == torch.float32
        assert downgraded["nested_list"][2] == "string_data"
        assert downgraded["nested_list"][3] == 42

    def test_torch_module_weights_downgrade(self):
        """Test casting PyTorch nn.Module parameters from FP64 to FP32."""
        proto = PrecisionDowngradeProtocol()
        model = torch.nn.Linear(4, 2).to(torch.float64)
        assert model.weight.dtype == torch.float64

        downgraded_model = proto.downgrade_model_weights(model)
        assert downgraded_model.weight.dtype == torch.float32
        assert downgraded_model.bias.dtype == torch.float32

    def test_should_downgrade_logic(self):
        """Test decision protocol for when precision downgrade is warranted."""
        proto = PrecisionDowngradeProtocol()

        # GPU -> CPU routing warrants FP32 downgrade to save RAM
        assert proto.should_downgrade(source_device=DeviceType.CUDA, target_device=DeviceType.CPU) is True

        # CPU -> CPU with ample RAM does not strictly require downgrade
        assert proto.should_downgrade(
            source_device=DeviceType.CPU,
            target_device=DeviceType.CPU,
            available_ram_bytes=32 * 1024**3,
        ) is False

        # Constrained RAM (< 4GB) warrants downgrade even on CPU
        assert proto.should_downgrade(
            source_device=DeviceType.CPU,
            target_device=DeviceType.CPU,
            available_ram_bytes=2 * 1024**3,
        ) is True


# ============================================================================
# 5. Integrated Workflow Tests
# ============================================================================

class TestIntegratedMechanicsMemory:
    """End-to-end integration test across all four components."""

    def test_full_pipeline_flow(self, tmp_path: Path):
        """Test end-to-end routing, resource brokering, downgrade, and HDF5 storage."""
        # 1. Initialize DB and broker
        db_path = tmp_path / "integrated_landscape.h5"
        memory_manager = ToposHDF5MemoryManager(db_path=db_path)
        broker = HardwareResourceBroker()
        cascade = FallbackCascadeStateMachine()
        precision = PrecisionDowngradeProtocol()

        # 2. Check hardware snapshot
        hw_snap = broker.poll_hardware()
        assert hw_snap.cpu_count_logical > 0

        # 3. Resolve engine for organometallic complex with Rhodium (Rh=45)
        rh_complex = [45, 6, 6, 8, 1, 1, 1]
        state = cascade.resolve_engine(atomic_numbers=rh_complex, broker=broker)
        assert state.current_engine in (EngineTier.G_XTB, EngineTier.XTB2)
        assert state.is_downgraded

        # 4. Calculate safe batch size
        safe_batch = broker.calculate_safe_batch_size(num_atoms=len(rh_complex), engine=state.current_engine)
        assert safe_batch >= 1

        # 5. Generate FP64 tensor test data (real numpy computation) and downgrade
        raw_coords = np.random.RandomState(42).randn(len(rh_complex), 3).astype(np.float64)
        raw_grad = np.random.RandomState(42).randn(len(rh_complex), 3).astype(np.float64)

        if precision.should_downgrade(source_device=DeviceType.CUDA, target_device=state.target_device):
            processed_coords = precision.downgrade_tensors(raw_coords)
            processed_grad = precision.downgrade_tensors(raw_grad)
            assert processed_coords.dtype == np.float32
        else:
            processed_coords = raw_coords
            processed_grad = raw_grad

        # 6. Store in HDF5
        record = GeometryRecord(
            geom_id="Rh_complex_opt",
            atomic_numbers=rh_complex,
            coords=processed_coords.tolist(),
            energy=-1452.3391,
            gradient=processed_grad.tolist(),
            metadata={"engine": state.current_engine.value, "downgraded": state.is_downgraded},
        )
        memory_manager.write_geometry(record)

        # 7. Record Telemetry
        telemetry = TelemetryRecord(
            record_id="tel_rh_01",
            timestamp=time.time(),
            engine=state.current_engine.value,
            device=state.target_device.value,
            batch_size=safe_batch,
            ram_used_bytes=hw_snap.ram_used_bytes,
            vram_used_bytes=0,
            duration_seconds=0.88,
            extra={"initial_engine": state.initial_engine.value},
        )
        memory_manager.record_telemetry(telemetry)

        # 8. Verify round-trip read
        retrieved_geom = memory_manager.read_geometry("Rh_complex_opt")
        assert retrieved_geom is not None
        assert retrieved_geom.atomic_numbers == rh_complex
        assert np.allclose(retrieved_geom.coords, processed_coords, atol=1e-5)
        assert retrieved_geom.metadata["downgraded"] is True

        retrieved_telem = memory_manager.read_telemetry("tel_rh_01")
        assert retrieved_telem is not None
        assert retrieved_telem.engine == state.current_engine.value

    def test_geometry_validation_errors(self):
        """Test Pydantic validation rejects invalid geometry records."""
        # Empty atomic numbers
        with pytest.raises(ValueError):
            GeometryRecord(
                geom_id="invalid_empty",
                atomic_numbers=[],
                coords=[],
                energy=0.0,
            )

        # Out-of-bounds atomic number (e.g. Z = 150)
        with pytest.raises(ValueError):
            GeometryRecord(
                geom_id="invalid_z",
                atomic_numbers=[150],
                coords=[[0.0, 0.0, 0.0]],
                energy=0.0,
            )

    def test_geometry_overwrite_behavior(self, tmp_path: Path):
        """Test overwriting existing geometry record updates fields cleanly."""
        db_file = tmp_path / "overwrite_test.h5"
        manager = ToposHDF5MemoryManager(db_path=db_file)

        record1 = GeometryRecord(
            geom_id="mol_overwrite",
            atomic_numbers=[1, 1],
            coords=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]],
            energy=-1.1,
            metadata={"version": 1},
        )
        manager.write_geometry(record1)

        # Overwrite with updated coordinates and energy
        record2 = GeometryRecord(
            geom_id="mol_overwrite",
            atomic_numbers=[1, 1],
            coords=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.75]],
            energy=-1.15,
            metadata={"version": 2},
        )
        manager.write_geometry(record2)

        read_back = manager.read_geometry("mol_overwrite")
        assert read_back is not None
        assert pytest.approx(read_back.energy, 1e-6) == -1.15
        assert read_back.metadata["version"] == 2
        assert len(manager.list_geometries()) == 1

    def test_multidimensional_tensor_precision_conversion(self):
        """Test downgrade_tensors with 3D/4D PyTorch tensors and numpy arrays."""
        proto = PrecisionDowngradeProtocol()
        # 3D Tensor
        t3d = torch.randn(2, 4, 3, dtype=torch.float64)
        t3d_down = proto.downgrade_tensors(t3d)
        assert t3d_down.dtype == torch.float32
        assert t3d_down.shape == (2, 4, 3)

        # Upgrade test (float32 to float64)
        t3d_up = proto.downgrade_tensors(t3d_down, target_dtype="float64")
        assert t3d_up.dtype == torch.float64

    def test_superheavy_elements_cascade(self):
        """Test elements beyond Z=86 cascade to terminal xTB2 with warning."""
        cascade = FallbackCascadeStateMachine()
        # Californium (Z=98)
        superheavy = [98, 1, 1]
        state = cascade.resolve_engine(atomic_numbers=superheavy, requested_engine=EngineTier.MACE_OFF24M)
        assert state.current_engine == EngineTier.XTB2
        assert state.is_downgraded


Validate Zero-Mock adherence. Target repo is D:\__CoChem\GitHub-Repo\CoChem-TOPOS.