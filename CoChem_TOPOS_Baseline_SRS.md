# Software Requirements Specification (SRS): CoChem-TOPOS Ecosystem
## Comprehensive Baseline Architecture & Reverse-Engineered System Specification

- **Specification Identifier:** `SRS-TOPOS-V4.2-BASELINE-2026-10` [M]
- **Document Version:** `4.2.0-RELEASE` [M]
- **Standard Compliance:** IEEE 830-1998 / ISO/IEC/IEEE 29148:2018 / CoChem Anti-Spoofing Protocol v4.2 [M]
- **Target Repository:** `D:\__CoChem\GitHub-Repo\CoChem-TOPOS` [M]
- **Authoritative Provenance:** Synthesized from Physical Codebase, Dual Wiki RAG (`wiki/srs`, `wiki/code`), and `CoChem_User_Manual.md` [M]

---

### Table of Contents
1. [Introduction and Architectural Scope](#1-introduction-and-architectural-scope)
2. [Ecosystem Overview & Tripartite Topology](#2-ecosystem-overview--tripartite-topology)
3. [Method Matrix & Physical Rigor Invariants](#3-method-matrix--physical-rigor-invariants)
4. [Exhaustive File-by-File Module Reverse-Architecture Extraction](#4-exhaustive-file-by-file-module-reverse-architecture-extraction)
   - 4.1 Root Execution Drivers & Infrastructure
   - 4.2 Core Engine Subsystem (`core_engine/`)
   - 4.3 Topology & Deduplication Subsystem (`topology/`)
   - 4.4 Cascade & Multi-Tier Escalation Subsystem (`cascade_engine/` & `escalation/`)
   - 4.5 Mechanics & PES Exploration Subsystem (`mechanics/`)
   - 4.6 Spectroscopy Subsystem (`cochem/spectroscopy/`)
   - 4.7 Frontend & Pre-Flight Gatekeeper (`frontend/` & `topos/`)
   - 4.8 Continuous Integration & Anti-Spoofing Toolchain (`ci_tools/`)
5. [Formal Functional Requirements Catalog (REQ-TOPOS)](#5-formal-functional-requirements-catalog-req-topos)
6. [Non-Functional Requirements & Host Protection (NFR-TOPOS)](#6-non-functional-requirements--host-protection-nfr-topos)
7. [Data Architecture, QCSchema HDF5 & IPC Formats](#7-data-architecture-qcschema-hdf5--ipc-formats)
8. [External Tool & Hardware Integration Contracts](#8-external-tool--hardware-integration-contracts)
9. [Verification, Validation & Traceability Matrix](#9-verification-validation--traceability-matrix)

---

### 1. Introduction and Architectural Scope

#### 1.1 Purpose
This document establishes the authoritative, verified baseline Software Requirements Specification (SRS) for the **CoChem-TOPOS** subsystem within the CoChem ecosystem. It provides an exhaustive, file-by-file reverse-architecture extraction of the physical repository (`D:\__CoChem\GitHub-Repo\CoChem-TOPOS`), cross-referencing:
1. The **Dual Wiki RAG database and SRS chapters** (`wiki/srs`, `wiki/code`, `knowledge_index.db`).
2. The physical codebase in `D:\__CoChem\GitHub-Repo\CoChem-TOPOS`.
3. The official `CoChem_User_Manual.md` and `Method_Matrix.md`.

#### 1.2 System Scope
CoChem-TOPOS is the topological discovery, conformational search, quantum calculation escalation, and microwave spectroscopic prediction engine of CoChem. It is designed to explore complex potential energy surfaces (PES), discover conformational basins and non-covalent complexes (water clusters, organic dimers, solvent-solute assemblies), escalate geometries through rigorous quantum chemical ladders (from force fields/GFN2-xTB to ab initio DFT and coupled-cluster levels), compute vibrational/DVR tunneling corrections, and synthesize publication-grade rotational spectral decks (Pickett `.par`/`.var`/`.int`).

---

### 2. Ecosystem Overview & Tripartite Topology

#### 2.1 Tripartite Air-Gap Execution Architecture
To guarantee computational integrity and prevent host exhaustion, CoChem-TOPOS strictly bifurcates operations across three architectural tiers:
```
+---------------------------------------------------------------------------------------------------+
| 1. PRESENTATION TIER (UI / CLI / Jupyter / Voila)                                                |
| - Parameter ingestion, time-aware capability selection, cost estimation, pre-flight gatekeeping. |
| - State serialized strictly to TOPOS_Runtime_State.json and config.json.                          |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v IPC / Subprocess Trigger
+---------------------------------------------------------------------------------------------------+
| 2. ORCHESTRATION TIER (Subprocess Broker & Telemetry Logger)                                      |
| - Subprocess management via Win32 Job Objects (CREATE_NO_WINDOW = 0x08000000).                    |
| - Hardware monitoring (CPU cores, RAM ceilings, VRAM limits, disk quotas, zombie reaping).        |
| - File-locking telemetry synchronization (telemetry.json, filelock.FileLock).                     |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v Ephemeral Scratch Execution
+---------------------------------------------------------------------------------------------------+
| 3. COMPUTATIONAL TIER (The Execution Engine)                                                     |
| - Isolated scratch sandbox $T_scr ($COCH_SCRATCH/topos_job_<uuid>).                               |
| - Ab initio engines: ORCA 5/6, xTB (GFN2-xTB), CREST, ABCluster, ASE, gpu4pyscf.                 |
| - Atomic promotion of converged outputs to $T_store ($COCH_STORE_DIR / landscape.h5).            |
+---------------------------------------------------------------------------------------------------+
```

#### 2.2 System Component Topology
```
[User Seed / XYZ / SMILES]
            │
            ▼
[frontend/cochem_topos_preflight.py] ──> (Spin Parity, Mendeleev Masses, Nuclear Clash Checks)
            │
            ▼
[topology/cochem_topos_graph.py] ─────> (Distance Matrix, 1.15x Resonance Scaling, Graph Cleavage)
            ├─────────────────────────────────────────┐
            │ (Weak Complex / Monomers)               │ (Strong Complex / Coordinated)
            ▼                                         ▼
[topology/cochem_topos_abcluster.py]      [mechanics/cochem_topos_goat.py]
 (Artificial Bee Colony Swarm Packing)     (Quench <-> Escape Basin-Hopping)
            │                                         │
            └────────────────────┬────────────────────┘
                                 │
                                 ▼
                     [topology/cochem_topos_crest_union.py]
                      (GOAT + CREST iMTD-GC Six-Step Union)
                                 │
                                 ▼
                     [topology/cochem_topos_crusher.py]
                      (5-Tier Rejection Sieve, Coulomb Matrix, Chiral Lock)
                                 │
                                 ▼
                     [cascade_engine/cochem_topos_cascade_orchestrator.py]
                      (Method Matrix Ladder: T1-1min -> T2-3h -> T4O-3d)
                                 │
            ┌────────────────────┴────────────────────┐
            ▼                                         ▼
[pes_h5.py]                               [cochem/spectroscopy/rotational_observables.py]
(HDF5 PESStore, Sinc-DVR, Tensor DVR)     (Pickett SPCAT Decks, Delta B_vib, Quadrupole)
```

---

### 3. Method Matrix & Physical Rigor Invariants

All routines in CoChem-TOPOS must satisfy the following physical and methodological invariants:

1. **Two-Stage Dynamic Numerical Quadrature (`defgrid1` to `defgrid3`):**
   - Exploratory geometric relaxations utilize coarse grids (`! defgrid1`) until the root-mean-square force drops below $1.0 \times 10^{-3}\text{ Hartree/Bohr}$.
   - Production convergence dynamically transitions to fine grids (`! defgrid3`). Legacy grid keywords (`Grid3`, `Grid4`, `Grid5`) are strictly rejected.
2. **Non-Covalent `%geom` Convergence Discipline:**
   - Intermolecular complex relaxations require tightened convergence blocks:
     $$\text{TolMaxG} \le 1.0 \times 10^{-5}\text{ Hartree/Bohr}, \quad \text{TolE} \le 1.0 \times 10^{-6}\text{ Hartree}$$
3. **Frozen-Monomer Protocol & SE(3) Rigid Kinematics Discipline:**
   - Monomer internal degrees of freedom are preserved without unphysical laboratory-frame Cartesian locking (eradicating legacy `{ C idx C }` locks pursuant to DEF-CART-LOCK-01). Intermolecular degrees of freedom ($R, \theta, \phi$) are evaluated via SE(3) rigid kinematics (`SE3RigidKinematicsEngine`) or internal coordinate constraints to ensure uninhibited non-covalent complex relaxation.
4. **Hessian Preconditioning Discipline:**
   - Geometry optimizations must NEVER invoke `Calc_Hess true` or `Calc_Hess exact`. Hessian preconditioning must use exact semi-empirical methods (`InHess XTB2`) or empirical model Hessians (`InHess Lindh`).
5. **Pure Mendeleev Dynamic IUPAC Mass Mandate:**
   - All mass calculations (inertial tensors, center of mass, vibrational frequencies, Eckart alignment, isotopic shifts) must query standard IUPAC isotopic masses dynamically via `mendeleev`. Hardcoded mass dictionaries and rounded integer weights are forbidden.
6. **Zero-Mock Execution Policy:**
   - No mock objects, simulated data generators, empty `pass` blocks, or dead-end `NotImplementedError` stubs are permitted. When external binaries are absent, calibrated authentic physical models (e.g. Lennard-Jones van der Waals with Lorentz-Berthelot mixing) execute physically.
7. **Subprocess Window Suppression:**
   - All Windows subprocess executions must enforce `creationflags = 0x08000000` (`CREATE_NO_WINDOW`) to eliminate host desktop heap exhaustion.

---

### 4. Exhaustive File-by-File Module Reverse-Architecture Extraction

#### 4.1 Root Execution Drivers & Infrastructure

##### `cochem_topos_runner.py` (714 lines)
- **Architectural Role:** Master execution trigger and tripartite air-gap broker for asynchronous conformer search jobs.
- **Physical Classes (5):**
  - `NobleGasLJCalculator(Calculator)`: Authentic 12-6 Lennard-Jones pair potential with Lorentz-Berthelot combination rules ($u_{ij}(r) = 4\epsilon_{ij}[(\sigma_{ij}/r)^{12} - (\sigma_{ij}/r)^6]$) for noble gas systems (He, Ne, Ar, Kr, Xe, Rn).
  - `XTBCLICalculator(Calculator)`: External CLI adapter executing `xtb` binary with authentic total energy and analytical gradient parsing.
  - `TOPOSJobStatus(str, Enum)`: Job state lifecycle (`IDLE`, `RUNNING`, `CANCELLED`, `COMPLETED`, `FAILED`).
  - `TOPOSSearchConfig(BaseModel)`: Pydantic v2 configuration schema (`tier_id`, `protocol`, `product_class`, `atom_count`, `input_xyz_path`, `max_hours`, `scratch_dir`, `store_dir`, `engine`, `method`, `calc_env`, `interact_env`).
  - `TOPOSExecutionBroker`: Spawns background worker processes in ephemeral `$T_scr` sandboxes, manages file-locked telemetry (`telemetry.json`), and atomically promotes converged structures to `$T_store`.
- **Top-Level Functions (5):** `is_xtb_available`, `is_noble_gas_system`, `get_noble_gas_calculator`, `get_xtb_calculator`, `get_conformer_calculator`.

##### `pes_h5.py` (1526 lines)
- **Architectural Role:** Standalone HDF5 interchange layer and Discrete Variable Representation (DVR) tunneling driver.
- **Physical Classes (7):**
  - `HDF5PersistenceConfig(BaseModel)`: Configuration for chunking (~512 points), gzip level 4 compression, byte shuffle, and Fletcher32 integrity checks.
  - `PESStore`: Production-grade QCSchema-compliant HDF5 manager (`/meta`, `/methods/<id>`, `/points/<id>/coordinates`, `/energy`, `/gradient`, `/converged`, `/wall_s`, `/provenance`, `/point_id`, `/grids/<id>`, `/hessians/<label>`). Strictly bans lossy scale-offset compression.
  - `HDF5PersistenceCoordinator`: SWMR multi-worker coordination with `filelock` and restart tracking via `todo()`.
  - `DVRResult1D(BaseModel)`: 1D bound state eigenvalues (cm⁻¹), wavefunctions, and expectation values.
  - `DVRResult2D(BaseModel)`: 2D coupled direct-product DVR eigenstate spectrum.
  - `DVRResult3D(BaseModel)`: 3D bound state energies and wavefunctions.
  - `MatrixFreeDVR3DOperator(scipy.sparse.linalg.LinearOperator)`: Matrix-free 3D tensor contraction operator using `np.einsum` to eliminate dense 32.8 GB matrix allocations.
- **Top-Level Functions (16):** `_get_process_thread_lock`, `_clean_attr`, `get_atomic_mass`, `get_system_mass`, `get_dimer_reduced_mass`, `get_atom_diatom_reduced_mass`, `build_sinc_kinetic_matrix_1d`, `solve_dvr_1d`, `solve_dvr_2d`, `solve_dvr_3d_matrix_free`, `morse_potential`, `analytical_morse_eigenvalues`, `ar_hcl_vdw_potential`, `build_cli_parser`, `run_internal_benchmarks`, `main`.

##### `gpu_point.py` (1567 lines)
- **Architectural Role:** Single-point GPU execution runner, memory footprint benchmarking, and NVIDIA MPS concurrency engine.
- **Physical Classes (6):**
  - `TaskType(str, Enum)`: Execution mode (`ENERGY`, `GRADIENT`, `HESSIAN`, `BENCHMARK_MEMORY`, `BENCHMARK_CONCURRENCY`).
  - `EngineType(str, Enum)`: Quantum backend (`GPU4PYSCF`, `PYSCF_CPU`, `ANALYTICAL_VDW`).
  - `GPUPointConfig(BaseModel)`: Single-point configuration schema (method, basis, auxbasis, spherical, grid, thresholds).
  - `GPUPointResult(BaseModel)`: Full observable output (electronic energy, gradients, Cartesian Hessian, rotational constants $A, B, C$, dipole moments, normal modes, vibrational frequencies).
  - `GPUMemoryBenchmarkResult(BaseModel)`: Memory profile record (allocated, reserved, peak VRAM, baseline).
  - `ConcurrencyBenchmarkResult(BaseModel)`: Throughput record (scaling efficiency, points/sec, wall time).
- **Top-Level Functions (12):** `get_atomic_mass`, `compute_rotational_properties`, `analyze_hessian`, `get_canonical_geometry`, `parse_geometry_input`, `evaluate_analytical_vdw_potential`, `poll_gpu_vram_mb`, `measure_gpu_memory_footprint`, `measure_concurrency_throughput`, `run_gpu_point`, `build_cli_parser`, `main`.

##### `hetero_config.py` (1733 lines)
- **Architectural Role:** Heterogeneous CPU (i7-13700K) + GPU (RTX 3090) dual Parsl executor configuration driver.
- **Physical Classes (14):**
  - `GpuScoutExecutorConfig(BaseModel)`: MPS accelerator pinning and VRAM ceiling parameters.
  - `SetupTier(str, Enum)`: Hardware deployment environments (`SETUP_1_CPU_ONLY`, `SETUP_2_PRODUCTION_WORKSTATION`, `SETUP_3_SLURM_CLUSTER`).
  - `ProviderBackend(str, Enum)`: Execution backend (`LOCAL_THREADPOOL`, `LOCAL_PROCESS_POOL`, `SLURM_PROVIDER`).
  - `CoreAffinityType(str, Enum)`: CPU pinning topology (`BLOCK`, `BLOCK_REVERSE`, `ALTERNATING`, `NONE`).
  - `GuardDecision(str, Enum)`: Method Matrix §8A.5 audit outcome (`PASSED`, `REJECTED`, `THROTTLED`, `ABORTED`).
  - `HardwareSpec(BaseModel)`: Physical hardware envelope (CPU cores, RAM total, GPU model, VRAM limit, power limit).
  - `ExecutorConfig(BaseModel)`: Concrete Parsl executor definition (cores_per_worker, max_workers, cpu_affinity, memory limit).
  - `HeteroParslConfig(BaseModel)`: Multi-executor workflow definition (anchor CPU, scout GPU, orchestrator utility).
  - `MPSConfig(BaseModel)`: NVIDIA MPS daemon controls (active thread percentage, pinned memory limit).
  - `MPSStatus(BaseModel)`: MPS daemon runtime state (active, pipe path, allocated slots).
  - `IntegrityGuardResult(BaseModel)`: Guard validation verdict across G1–G7.
  - `HeteroProvenanceRecord(BaseModel)`: Cryptographic tracking payload for `provenance.jsonl`.
  - `_nvmlMemory_t(ctypes.Structure)`: Low-level C-types memory struct for NVML profiling.
  - `GpuScoutDispatcher`: Task routing broker mapping calculations to CPU Anchor vs GPU Scout.
- **Top-Level Functions (24):** `get_atomic_mass`, `build_hetero_config`, `get_vram_free_gb`, `build_slurm_hetero_config`, `build_cpu_only_config`, `calculate_optimal_mps_workers`, `probe_mps_status`, `generate_mps_startup_script`, `generate_mps_teardown_script`, `detect_gpu_scout_config`, `check_guard_g1_scout_advisory`, `check_guard_g2_high_level_hessian`, `compute_kabsch_rmsd`, `check_guard_g3_basin_identity`, `check_guard_g4_rank_inversion`, `check_guard_g5_uncertainty`, `check_guard_g6_abort_rule`, `create_provenance_event`, `run_hetero_diagnostic`, `build_cli_parser`, `main`, `determine_gpu_executor_pool`, `route_task_by_theory_level`, `teardown_gpu_task`.

##### `make_notebook.py` (1147 lines)
- **Architectural Role:** Automated generator for production Jupyter notebooks (`cochem_topos_master.ipynb`, `CoChem-TOPOS_Research.ipynb`, `CoChem-TOPOS_Visualization.ipynb`).
- **Physical Classes (1):**
  - `VisualizationPipelineSetup`: Manages notebook template generation, cell syntax validation, and widget binding.
- **Top-Level Functions (12):** `get_atomic_mass`, `build_master_voila_notebook`, `build_research_notebook`, `build_visualization_notebook`, `write_notebook_to_disk`, `validate_notebook_content`, `generate_master_notebook`, `generate_research_notebook`, `generate_visualization_notebook`, `generate_all_notebooks`, `parse_arguments`, `main`.

##### `cochem_topos_web.py` (21 lines)
- **Architectural Role:** Minimal web server entrypoint forwarding requests to the Voila runner and dashboard UI.

---

#### 4.2 Core Engine Subsystem (`core_engine/`)

##### `core_engine/cochem_core_subprocess_broker.py` (1696 lines)
- **Architectural Role:** Cross-platform subprocess lifecycle supervisor and process tree isolation broker.
- **Physical Classes (11):**
  - `DiskQuotaError(OSError)`: Raised when scratch disk space drops below safety thresholds.
  - `_IO_COUNTERS(ctypes.Structure)`: Windows Win32 I/O counter telemetry structure.
  - `_JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure)`: Win32 process limit information.
  - `_JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure)`: Win32 extended limit flags (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`).
  - `WindowsJobObject`: Win32 Job Object management wrapper binding child processes.
  - `ZombieReaper`: Background monitor and atexit handler ensuring recursive process-tree termination.
  - `CPUTopologyManager`: P-core and E-core processor affinity scheduler.
  - `RAMDiskOverlayManager`: Volatile RAM-disk scratch workspace allocation.
  - `ZMQHeartbeatManager`: CurveZMQ / IPC socket heartbeat publisher for liveness tracking.
  - `DeadMansSwitchWatchdog`: Watchdog thread terminating orphaned processes if host heartbeat ceases.
  - `SubprocessBroker`: Safe execution gateway enforcing `CREATE_NO_WINDOW = 0x08000000`, process isolation, and dynamic timeout budgets.
- **Top-Level Functions (17):** `is_crash_returncode`, `extract_segfault_hex_dump`, `get_active_popen_processes`, `register_popen_process`, `unregister_popen_process`, `kill_process_tree`, `safe_subprocess_run`, `sweep_zombies`, `check_disk_quota`, `verify_binary_signature`, `route_ramdisk_workspace`, `init_job_object`, `pin_thread_affinity`, `setup_heartbeat_publisher`, `teardown_subprocess_broker`, `parse_cli_arguments`, `main`.

##### `core_engine/cochem_core_telemetry_logger.py` (1306 lines)
- **Architectural Role:** Hardware guard, memory monitoring, and asynchronous trace telemetry logger.
- **Physical Classes (4):**
  - `RotatingJsonlSink`: High-throughput append-only JSONL log writer with automatic size rotation.
  - `TelemetryIPCStreamer`: Non-blocking IPC socket streamer pushing telemetry events to the GUI.
  - `TelemetryIPCListener`: Background listener thread aggregating telemetry packets from workers.
  - `TelemetryLogger`: Master telemetry interface capturing CPU, RAM, disk I/O, and calculation metrics.
- **Top-Level Functions (14):** `get_default_secret_key`, `resolve_telemetry_log_dir`, `capture_crash_telemetry_metrics`, `force_flush_and_close_hdf5_pointers`, `safe_h5py_open`, `get_plaintext_rotating_handler`, `init_telemetry_logger`, `log_calculation_step`, `log_hardware_snapshot`, `emit_telemetry_packet`, `close_telemetry_streams`, `archive_stale_telemetry`, `build_telemetry_report`, `verify_telemetry_integrity`.

##### `core_engine/cochem_topos_master.py` (417 lines)
- **Architectural Role:** Master orchestration engine for multi-step TOPOS workflows.
- **Physical Classes (2):**
  - `OETServerIPCClient`: Socket client communicating with the Open Equivariant Transformer (OET) inference daemon.
  - `TOPOSMasterIntegrator`: High-level workflow controller integrating preflight sanitization, graph cleavage, conformer generation, and cascade escalation.

##### `core_engine/cochem_topos_crusher.py` (1785 lines)
- **Architectural Role:** Core engine conformer deduplication pipeline.
- **Physical Classes (15):** `ElementInfoHolder`, `DeduplicationVerdict`, `RotationalConstants`, `DipoleMoment`, `ConformerCandidate`, `DeduplicationRecord`, `DeduplicatedConformerRecord`, `EnsembleDeduplicationReport`, `MemmapIsomerBuffer`, `RotationalSieve`, `KDTreeCoordinateFilter`, `MassWeightedEckartRMSD`, `GOATConformerEngine`, `CRESTConformerEngine`, `TopologyCrusher`.
- **Top-Level Functions (22):** `normalize_element_symbol`, `get_element_info`, `get_dynamic_monoisotopic_mass`, `get_monoisotopic_masses`, `get_dynamic_covalent_radius`, `get_dynamic_atomic_number`, etc.

##### `core_engine/cochem_topos_escalator.py` (1289 lines)
- **Architectural Role:** Core engine multi-stage calculation escalator.
- **Physical Classes (10):** `PipelineStage`, `StageStatus`, `RecipeType`, `FragmentAssemblerConfig`, `AssembledCandidate`, `StageTransitionEvent`, `EscalationStagePayload`, `StageTransitionReport`, `FragmentAssembler`, `ToposEscalator`.
- **Top-Level Functions (8):** `get_dynamic_atomic_mass`, `get_covalent_radius`, `get_atomic_symbol`, `get_atomic_number`, `calculate_center_of_mass`, `calculate_principal_moments_and_axes`, `assemble_complex_recipe`, `execute_stage_escalation`.

##### `core_engine/cochem_topos_escape.py` (289 lines)
- **Architectural Role:** Core engine topographic escape and parity verification driver.
- **Physical Classes (3):** `GoodTuringEstimator`, `ParityLock`, `EscapeRoom`.

##### `core_engine/oet_server.py` (408 lines)
- **Architectural Role:** Open Equivariant Transformer (OET) surrogate inference server.
- **Physical Classes (3):**
  - `GoatDaemonExecutionError(RuntimeError)`: Raised when the daemon encounters unrecoverable calculation errors.
  - `GoatExploreDaemonConfig(BaseModel)`: Configuration for port, host, scratch directory, and MLFF checkpoint paths.
  - `GoatExploreDaemon`: Local socket daemon managing background conformer exploration and surrogate energy evaluations.
- **Top-Level Functions (5):** `compute_kabsch_rmsd`, `generate_orca_goat_deck`, `parse_ensemble_xyz`, `stream_ensemble_xyz`, `deduplicate_conformers`.

---

#### 4.3 Topology & Deduplication Subsystem (`topology/`)

##### `topology/cochem_topos_graph.py` (887 lines)
- **Architectural Role:** Graph cleavage and pipeline routing engine translating 3D coordinates into adjacency matrices.
- **Physical Classes (6):**
  - `_DynamicCovalentRadiiMapping`: Dynamic Pyykkö covalent radius lookup caching structure.
  - `_DynamicAtomicWeightsMapping`: Dynamic IUPAC atomic weight caching structure.
  - `MonomerSeed(BaseModel)`: Container for isolated monomer coordinates, atomic numbers, and chemical formulas.
  - `ShortestGapTelemetry(BaseModel)`: Telemetry record for inter-fragment distances and closest atom pairs.
  - `TopologyAnalysisResult(BaseModel)`: Classification result (`MONOMER`, `STRONG_COMPLEX`, `WEAK_COMPLEX`, `BYPASS_GOAT`).
  - `TopologyGraphEngine`: Constructs Cartesian distance matrices, applies $1.15\times$ Pyykkö covalent radius breathing tolerance ($T_{ij} = 1.15 \times (R_i + R_j)$), and evaluates NetworkX connected components.
- **Top-Level Functions (13):** `_cleanup_zombie_subprocesses`, `get_mendeleev_element`, `get_atomic_number`, `get_atomic_symbol`, `get_covalent_radius`, `get_atomic_mass`, `calculate_cartesian_distance_matrix`, `build_molecular_adjacency_matrix`, `extract_connected_monomer_seeds`, `compute_shortest_interfragment_gap`, `triage_and_route_topology`, `export_monomer_seeds_xyz`, `run_graph_topology_pipeline`.

##### `topology/cochem_topos_crusher.py` (2128 lines)
- **Architectural Role:** Conformer deduplication funnel filtering identical structures while preserving enantiomers and distinct rotamers.
- **Physical Classes (17):**
  - `EcosystemDependencyError(RuntimeError)`: Raised when required libraries (mendeleev, molsym, h5py) fail to load.
  - `ElementInfoHolder(BaseModel)`: Caches atomic properties retrieved dynamically from mendeleev.
  - `DeduplicationVerdict(str, Enum)`: Decision tag (`DISTINCT`, `DUPLICATE`, `ENANTIOMER_PRESERVED`).
  - `RotationalConstants(BaseModel)`: Rotational constants $A, B, C$ (MHz) with asymmetry parameter $\kappa$.
  - `DipoleMoment(BaseModel)`: Electric dipole moment components $\mu_a, \mu_b, \mu_c$ and total magnitude.
  - `ConformerCandidate(BaseModel)`: Candidate state container (geometry, energy, gradient, point group, connectivity).
  - `DeduplicationRecord(BaseModel)`: Pairwise comparison audit log.
  - `DeduplicatedConformerRecord(BaseModel)`: Final persistent conformer record with degeneracy $g_i$.
  - `EnsembleDeduplicationReport(BaseModel)`: Global deduplication statistics and timing report.
  - `MemmapIsomerBuffer`: Memory-mapped binary array storage (`numpy.memmap`) with SHA-256 header validation.
  - `RotationalSieve`: Spectroscopic filter enforcing rotational constant tolerance (`--bthr 0.001`).
  - `KDTreeCoordinateFilter`: Rapid nearest-neighbor spatial coordinate filter.
  - `MassWeightedEckartRMSD`: Evaluates $\text{RMSD}_{\text{thresh}} = \text{Base} / \sqrt{3N - 6}$.
  - `PhysicalCascadeCalculator`: Physical pair potential calculator for relaxation screening.
  - `GOATConformerEngine`: Conformer generation interface for GOAT basin structures.
  - `CRESTConformerEngine`: Conformer generation interface for CREST ensembles.
  - `TopologyCrusher`: Master deduplication orchestrator executing the 5-tier rejection sieve and Chiral Volume Inversion Lock ($V_{\text{chiral}} = (\vec{r}_1 - \vec{r}_4) \cdot ((\vec{r}_2 - \vec{r}_4) \times (\vec{r}_3 - \vec{r}_4))$, $\vec{r} \to -\vec{r}$, SO(3) Kabsch, $g_i = 2$).
- **Top-Level Functions (22):** `normalize_element_symbol`, `get_element_info`, `get_dynamic_monoisotopic_mass`, `get_monoisotopic_masses`, `get_dynamic_covalent_radius`, `get_dynamic_atomic_number`, etc.

##### `topology/cochem_topos_crest_union.py` (1456 lines)
- **Architectural Role:** CREST iMTD-GC metadynamics search engine and GOAT conformer union referee.
- **Physical Classes (10):**
  - `CRESTSearchConfig(BaseModel)`: Configuration for non-covalent CREST search (`--nci --nocross --noreftopo --ewin 12.0`).
  - `GOATSearchConfig(BaseModel)`: Configuration for stochastic GOAT exploration (`MAXEN 12.0`, `CONFDEGEN auto`).
  - `ConformerUnionConfig(BaseModel)`: Union referee configuration and filtering tolerances.
  - `SourceEngine(str, Enum)`: Origin tag (`GOAT`, `CREST`, `SEED`, `HYBRID`).
  - `UnionConformerCandidate(BaseModel)`: Candidate container tracking provenance and structural metrics.
  - `UnionCoverageDiagnostics(BaseModel)`: Attribution statistics (`GOAT_ONLY`, `CREST_ONLY`, `FOUND_BY_BOTH`, `INITIAL_SEED`).
  - `ConformerUnionReport(BaseModel)`: Complete union execution summary.
  - `CRESTSearchEngine`: Subprocess wrapper executing authentic CREST iMTD-GC runs.
  - `GOATConformerSearchEngine`: Stochastic basin-hopping search engine.
  - `GOATCRESTConformerUnionReferee`: Master referee executing the Method Matrix §9B Six-Step Union Protocol.
- **Top-Level Functions (12):** `cleanup_all_subprocesses`, `get_dynamic_atomic_mass`, `get_dynamic_atomic_number`, `get_dynamic_covalent_radius`, `get_dynamic_vdw_radius`, `get_git_commit_hash`, `execute_six_step_union`, `pool_raw_candidates`, `re_screen_common_level`, `execute_two_stage_deduplication`, `compute_union_coverage`, `export_union_ensemble`.

##### `topology/cochem_topos_abcluster.py` (1617 lines)
- **Architectural Role:** Artificial Bee Colony (ABC) swarm optimization and rigid-monomer packing engine.
- **Physical Classes (7):**
  - `MonomerDefinition(BaseModel)`: Structural specification of rigid monomer units (Cartesian coordinates, elements).
  - `MonomerPose(BaseModel)`: 6-DoF rigid-body spatial pose (COM coordinates $\vec{R}$, Euler angles $\alpha, \beta, \gamma$).
  - `ABClusterConfig(BaseModel)`: Swarm parameters (number of employed bees, onlooker bees, scout limit, bounding sphere radius).
  - `ClusterCandidate(BaseModel)`: Candidate cluster state with total intermolecular energy.
  - `ABClusterResult(BaseModel)`: Converged global minimum cluster geometry and binding energy.
  - `DeterministicClusterSampler`: Reproducible pseudo-random pose generator.
  - `ABClusterEngine`: Vectorized intermolecular potential evaluator (LJ + Coulomb, TIP4P, TIP4P/2005, SPC/E, TIP3P) and ABC swarm optimizer.
- **Top-Level Functions (21):** `_cleanup_zombies`, `get_dynamic_atomic_mass`, `get_dynamic_atomic_number`, `get_dynamic_vdw_radius`, `get_default_lj_parameters`, `euler_zyz_to_rotation_matrix`, `quaternion_to_rotation_matrix`, `apply_rigid_body_transformation`, `evaluate_intermolecular_potential`, `run_employed_bee_phase`, `run_onlooker_bee_phase`, `run_scout_bee_phase`, `quench_rigid_cluster`, `execute_abcluster_optimization`, `compute_principal_moments_and_axes`, `calculate_rotational_constants_ghz`, `calculate_dipole_moment_debye`, `write_cluster_xyz`, `export_abcluster_report`, `parse_cli_arguments`, `main`.

##### `topology/cochem_topos_wiggle.py` (399 lines)
- **Architectural Role:** Jiggle-quench normal mode displacement and torsional perturbation module.
- **Physical Classes (3):**
  - `JiggleQuenchConfig(BaseModel)`: Perturbation amplitudes, temperature parameters, and iteration limits.
  - `JiggleQuenchResult(BaseModel)`: Outcome of basin perturbation and relaxation.
  - `JiggleQuenchArbiter`: Evaluates whether two adjacent basins merge under physical normal mode displacement.
- **Top-Level Functions (3):** `jiggle_perturb_pair`, `execute_lightning_quench`, `arbitrate_basin_merge`.

---

#### 4.4 Cascade & Multi-Tier Escalation Subsystem (`cascade_engine/` & `escalation/`)

##### `cascade_engine/cochem_topos_cascade_orchestrator.py` (1789 lines)
- **Architectural Role:** Method Matrix cascade engine sequencing calculations across fidelity tiers.
- **Physical Classes (15):**
  - `BinaryNotFoundError(FileNotFoundError)`: Executable binary missing from PATH.
  - `MethodMatrixViolationError(ValueError)`: Violation of Method Matrix operational rules.
  - `HessianSpecificationError(MethodMatrixViolationError)`: Invalid Hessian keyword configuration.
  - `InvalidHessianStrategyError(MethodMatrixViolationError)`: Unsupported Hessian strategy.
  - `MissingDataError(FileNotFoundError)`: Required input file or dataset missing.
  - `MissingHessianFileError`: Missing InHess file for chaining.
  - `CorruptHessianFileError`: Malformed or empty InHess file.
  - `HessianChainingError`: Runtime failure during InHess chaining.
  - `SubprocessBroker`: Safe execution wrapper enforcing `CREATE_NO_WINDOW`.
  - `TierConfig(BaseModel)`: Specification of quantum calculation tier (theory, basis, grid, convergence).
  - `CascadeConfig(BaseModel)`: Multi-tier escalation path parameters.
  - `GradientPayload(BaseModel)`: Electronic energy, forces, and convergence status.
  - `TierResult(BaseModel)`: Intermediate result from a single cascade tier.
  - `OrchestratorPayload(BaseModel)`: End-to-end cascade execution receipt.
  - `CascadeOrchestrator`: Sequences calculations through Method Matrix tiers, enforces two-stage quadrature (`defgrid1` $\to$ `defgrid3`), manages InHess preconditioning, and prohibits `Calc_Hess true`.
- **Top-Level Functions (7):** `get_honest_xtb_calculator`, `partition_frozen_monomers`, `validate_in_hess_file`, `write_orca_hessian_file`, `validate_frequency_grid`, `build_two_stage_optimization_decks`, `execute_cascade_escalation`.

##### `cascade_engine/cochem_cascade_hdf5.py` (364 lines)
- **Architectural Role:** HDF5 serialization driver for multi-tier cascade trajectories.
- **Physical Classes (2):**
  - `DatabaseLockTimeoutError(TimeoutError)`: Raised when HDF5 file lock acquisition times out.
  - `CascadeHDF5Serializer`: Writes multi-tier geometries, energies, gradients, and frequencies into hierarchical HDF5 stores with SWMR locking.
- **Top-Level Functions (1):** `write_tier_data`.

##### `cascade_engine/cochem_topos_cascade_matrix.py` (191 lines)
- **Architectural Role:** Static Method Matrix table and parameter modifier resolver.
- **Top-Level Functions (2):** `evaluate_calculation_modifiers`, `get_tier_configuration`.

##### `cascade_engine/cochem_topos_schemas.py` (740 lines)
- **Architectural Role:** Pydantic and Enum schema definitions for cascade task payloads and results.
- **Physical Classes (16):** `CascadeStageEnum`, `MethodMatrixTierEnum`, `EngineType`, `HessianPreconditioner`, `ConcurrencyTag`, `CalculationStatus`, `StandardGeomBlockConfig`, `CalculationModifiers`, `TierConfig`, `CascadeConfig`, `GradientPayload`, `TierResult`, `OrchestratorPayload`, `ToposState`, `ConvergenceWallError`, `IntermolecularConvergenceAudit`.
- **Top-Level Functions (3):** `build_standard_geom_block`, `create_topos_state`, `audit_intermolecular_convergence`.

##### `escalation/cochem_topos_escalator_exec.py` (2974 lines)
- **Architectural Role:** Primary quantum mechanical execution broker and ab initio capability selector.
- **Physical Classes (31):**
  - `EscalationTier(str, Enum)`: Method Matrix tiers (T1-1min, T1-10m, T2-3h, T2-3d, T3-1w, T4O-3d, etc.).
  - `CanonicalArrow(str, Enum)`: 11 canonical pipeline transitions.
  - `SCFConvergenceStatus(str, Enum)`: SCF state (`CONVERGED`, `OSCILLATING`, `DIVERGED`, `WALL_EXHAUSTED`).
  - `CalculationStatus(str, Enum)`: Overall job outcome.
  - `AlertSeverity(str, Enum)`: Diagnostic severity (`INFO`, `WARNING`, `CRITICAL`, `FATAL`).
  - `CoordinateType(str, Enum)`: Coordinate system (`CARTESIAN`, `REDUNDANT_INTERNAL`).
  - `HardwareAllocations(BaseModel)`: Memory and CPU core budgets (%maxcore, %pal nprocs).
  - `OOMAutopsyDiagnostic(BaseModel)`: Diagnostic record for Exit Code 137 / SIGKILL events.
  - `MultireferenceDiagnostics(BaseModel)`: $T_1$ and $D_1$ diagnostic amplitudes.
  - `SCFIterationRecord(BaseModel)`: Single SCF iteration energy and error metrics.
  - `SCFConvergenceMetrics(BaseModel)`: Summary of SCF convergence behavior.
  - `AutoCASAlert(BaseModel)`: Alert payload when multireference breakdown occurs ($T_1 > 0.02$).
  - `CrossPlatformIPCAlert(BaseModel)`: Inter-process communication alert packet.
  - `ExecutionPlan(BaseModel)`: Tiered execution steps and parameter decks.
  - `EscalationStepRecord(BaseModel)`: Step execution telemetry and walltime.
  - `EscalatorExecConfig(BaseModel)`: Orchestrator configuration.
  - `EscalationResult(BaseModel)`: Final ab initio calculation result.
  - `HardwareBroker`: Evaluates system resources and injects `%maxcore` and `%pal` into ORCA inputs.
  - `WavefunctionSeeder`: Extracts binary `.gbw` wavefunctions from converged steps for `! MORead` projection.
  - `GeometricalExplosionTrap`: Monitors interatomic distances; aborts calculation if covalent bonds exceed $4.0\text{ \AA}$.
  - `OOMAutopsyEngine`: Captures OS-level out-of-memory kills and writes `OOM_autopsy.json`.
  - `Canonical11ArrowPipeline`: Constructs input blocks across all 11 tiers of computation.
  - `GeometryCoordinateVerifier`: Validates Cartesian coordinates and redundant internal coordinate construction.
  - `ORCAOutputParser`: Streams and parses `orca.out` live during execution.
  - `AutomatedSCFRescueEngine`: Intercepts SCF oscillations; injects `! SlowConv VShift` and restarts from last converged `.gbw`.
  - `AutoCASRescueProtocol`: Intercepts $T_1 > 0.02$ or $D_1 > 0.05$; triggers `! AutoCAS` multi-reference alert.
  - `FileSocketIPCQueue`: Cross-platform file/socket queue for IPC messaging.
  - `CrossPlatformIPCServer`: IPC socket server.
  - `CrossPlatformIPCClient`: IPC socket client.
  - `TimeAwareCapabilitySelector`: Selects optimal level of theory given user time budget.
  - `ToposEscalatorExec`: Master ab initio execution broker.
- **Top-Level Functions (5):** `send_ipc_alert`, `execute_time_aware_escalation`, `verify_redundant_cartesian_geometry`, `parse_orca_output`, `get_dynamic_atomic_mass`.

##### `escalation/cochem_topos_assembly.py` (1391 lines)
- **Architectural Role:** Molecular assembly and dimer/cluster composition manager.
- **Physical Classes (17):** `FragmentSource`, `DockingCollisionVector`, `StericClashReport`, `InternalCoordinateConstraint`, `MonomerPartition`, `SE3Pose`, `BSSEFragmentConfig`, `AssembledComplexCandidate`, `AssemblyConfig`, `AssemblySessionReport`, `StericClashResolver`, `CounterpoiseBSSEGenerator`, `InternalCoordinateFreezer`, `SE3RigidKinematicsEngine`, `CounterpoiseDeckEngine`, `GeometricDockingEngine`, `ToposCombinatorialAssembler`.
- **Top-Level Functions (1):** `assemble_weak_complex`.

##### `escalation/cochem_topos_iso_recycle.py` (1138 lines)
- **Architectural Role:** Conformer and isomer deduplication cache and isotopic Hessian frequency recycler.
- **Physical Classes (10):** `HessianUnit`, `IsotopeSubstitution`, `IsotopologueDefinition`, `NormalMode`, `ThermochemicalCorrections`, `VibrationalAnalysis`, `IsotopologueRecycleResult`, `HarmonicKIE`, `BatchRecycleReport`, `ToposIsotopologueRecycler`.
- **Top-Level Functions (6):** `get_exact_isotopic_mass`, `get_isotopic_masses`, `mass_weight_hessian`, `project_translations_rotations`, `recycle_hessian_frequencies`, `calculate_harmonic_kie`.

##### `escalation/cochem_topos_tunneling.py` (1453 lines)
- **Architectural Role:** 1D/2D Eckart and WKB quantum tunneling probability calculator for hydrogen transfers and torsional isomerization.
- **Physical Classes (15):** `TunnelingMethod`, `PotentialType`, `CoordinateUnit`, `EnergyUnit`, `PotentialCurve1D`, `WKBActionRecord`, `InstantonPathRecord`, `DVREigenstateRecord`, `DVRAnalysisResult`, `EckartBarrierRecord`, `TunnelingSplittingResult`, `IsotopeSubstitutionSpec`, `IsotopologueTunnelingRecord`, `IsotopicTunnelingComparison`, `ToposTunnelingEngine`.
- **Top-Level Functions (12):** `get_exact_isotopic_mass`, `get_isotopic_masses`, `compute_effective_reduced_mass`, `construct_double_well_potential`, `construct_torsional_potential`, `construct_eckart_potential`, `compute_wkb_action`, `compute_instanton_splitting`, `solve_1d_dvr_tunneling`, `compute_eckart_transmission`, `compute_thermal_tunneling_correction`, `validate_isotopic_tunneling_ratios`.

##### `escalation/subprocess_reaper.py` (2521 lines)
- **Architectural Role:** Advanced process reaper, segfault hex-dump trapper, and hardware governor.
- **Physical Classes (34):** `SubprocessReaperBaseError`, `PreFlightResourceError`, `ResourceGuardError`, `NUMAPinningError`, `ZombieReaperError`, `SegmentationFaultError`, `OSFaultError`, `StreamTrapError`, `LinearDependenceFaultError`, `EnergyMatrixNaNInfFaultError`, `SCFPingPongOscillationError`, `TemporalRoutingError`, `ScratchSpaceReport`, `HardwareRegistryConfig`, `SystemRegistryConfig`, `ThreadPinningResult`, `ZMQEndpointManifest`, `ProcessReapReport`, `StreamTrapEvent`, `StreamTrapReport`, `JSONLDProvenanceBlock`, `ProvenanceFooterPayload`, `ThermalGovernorState`, `TemporalRouteResult`, `IOScratchRouteReport`, `IOCleanupReport`, `PreFlightScratchVerifier`, `NUMA_ThreadPinner`, `ZombieReaper`, `SegfaultTrapper`, `ThermalEvacuationGovernor`, `TemporalRouter`, `HighSpeedIORouter`, `ActiveStreamRegexTrap`.
- **Top-Level Functions (14):** `get_cochem_artifacts_dir`, `get_scratch_workspace_dir`, `get_registry_workspace_dir`, `get_processed_workspace_dir`, `get_element_mass_mendeleev`, `format_hex_dump`, `extract_tail_hex_dump`, `find_scratch_dump_file`, `compute_sha256_hash`, `compute_geometry_hash`, `compute_orca_binary_hash`, `launch_isolated_process`, `execute_protected_subprocess`, `append_jsonld_provenance_footer`.

---

#### 4.5 Mechanics & PES Exploration Subsystem (`mechanics/`)

##### `mechanics/cochem_topos_goat.py` (2014 lines)
- **Architectural Role:** Master mechanics orchestrator executing the continuous Quench $\leftrightarrow$ Escape basin-hopping loop.
- **Physical Classes (20):**
  - `OptimizerToggleReason(str, Enum)`: Reason for optimizer switching.
  - `CascadeStoppingCriterion(str, Enum)`: Convergence or termination trigger.
  - `OptimizerToggleEvent(BaseModel)`: Optimizer switch log event.
  - `GradientNoiseQuenchResult(BaseModel)`: Relaxation result under gradient noise.
  - `GOATCascadeConfig(BaseModel)`: Basin-hopping configuration schema.
  - `CascadeCycleRecord(BaseModel)`: Cycle-by-cycle telemetry record.
  - `GOATCascadeResult(BaseModel)`: Exploration campaign summary.
  - `GOATCascadeReport(BaseModel)`: Full markdown/JSON report.
  - `OrphanedProcessReaper`: Process reaper for orphaned mechanics threads.
  - `JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure)`: Win32 limit struct.
  - `IO_COUNTERS(ctypes.Structure)`: Win32 I/O counter struct.
  - `JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure)`: Win32 extended limit struct.
  - `BaseOptimizer(abc.ABC)`: Abstract optimizer interface.
  - `ASEOptimizerAdapter(BaseOptimizer)`: Adapter wrapping ASE BFGS, FIRE, LBFGS.
  - `GradientNoiseOptimizer(BaseOptimizer)`: Stochastic gradient noise optimizer.
  - `MLFFSingletonLoader`: Thread-safe Singleton loader for MLFF models preventing VRAM fragmentation.
  - `BatchedMLFFInference`: Batched GPU/CPU tensor evaluation (batches of 32 or 64).
  - `ALPBSolvationManager`: Automatically activates ALPB implicit solvation for charged systems ($\text{charge} \ne 0$).
  - `ScratchPurgeManager`: Strictly caps scratch disk space below 10 GB.
  - `ToposGOATCascade`: Master GOAT cascade coordinator.
- **Top-Level Functions (4):** `get_global_reaper`, `reap_all_child_processes`, `load_system_config`, `get_system_charge`.

##### `mechanics/cochem_topos_quench.py` (1597 lines)
- **Architectural Role:** PES Quench relaxation subsystem.
- **Physical Classes (14):**
  - `QuenchAlgorithm(str, Enum)`: Relaxation algorithm (`BFGS`, `LBFGS`, `FIRE`, `CUDA_GRAPH_BFGS`).
  - `MonomerLockMode(str, Enum)`: Constraint mode (`RIGID`, `FROZEN_INTERNAL`, `UNCONSTRAINED`).
  - `QuenchStatus(str, Enum)`: Relaxation outcome.
  - `SoftQuenchTelemetry(BaseModel)`: Optimization trajectory telemetry.
  - `QuenchConfig(BaseModel)`: Force tolerance and step parameters.
  - `QuenchResult(BaseModel)`: Single geometry optimization result.
  - `QuenchBatchResult(BaseModel)`: Batch optimization outcomes.
  - `TorchMLFFCalculator(Calculator)`: PyTorch MLFF ASE calculator interface.
  - `MonomerConstraintLockEngine`: Enforces monomer coordinate locks during intermolecular relaxations.
  - `SoftQuenchGovernor`: Governs force thresholds and dynamic step sizes.
  - `CUDAGraphOptimizerWrapper`: CUDA graph acceleration for fast repetitive relaxation steps.
  - `CalculatorFactory`: Resolves appropriate ASE calculator backend.
  - `ParallelASEQuenchRunner`: Executes concurrent local minimizations across geometry batches.
  - `ToposQuenchOrchestrator`: Master quench subsystem coordinator.

##### `mechanics/cochem_topos_escape.py` (1368 lines)
- **Architectural Role:** Topographic escape room subsystem exploring adjacent PES basins.
- **Physical Classes (16):**
  - `EscapeMechanism(str, Enum)`: Mechanism (`WIGNER_NORMAL_MODE`, `PROGRESSIVE_LANGEVIN`, `PHOTOCHEMICAL_SHOCK`).
  - `EscapeStatus(str, Enum)`: Escape outcome.
  - `WignerModeInfo(BaseModel)`: Soft normal mode frequency and displacement vector.
  - `NormalModeAnalysisResult(BaseModel)`: Vibrational normal modes and eigenvalues.
  - `EscapeTelemetryPacket(BaseModel)`: Real-time escape step telemetry.
  - `FAIRProvenanceRecord(BaseModel)`: Provenance record with [M], [D], [E] tags.
  - `EscapeConfig(BaseModel)`: Escape parameters (temperature ladder, step counts).
  - `EscapeResult(BaseModel)`: Coordinates of newly discovered basin minimum.
  - `ParityLock`: Chiral parity verification enforcing tetrahedral scalar triple product volume checks.
  - `GoodTuringEstimator`: Statistical completeness estimator evaluating unseen basin probabilities.
  - `IPCTelemetryBroadcaster`: Broadcasts escape progress to external listeners.
  - `WignerGuidedEscape`: Displaces geometry along soft imaginary/low-frequency normal modes.
  - `ProgressiveLangevinEscape`: Multi-temperature thermal auto-tuning ($300\text{ K} \to 500\text{ K} \to 1000\text{ K}$).
  - `PhotochemicalShockEngine`: Electronic excitation and Franck-Condon displacement simulator.
  - `ToposEscapeOrchestrator`: Master escape room coordinator.
  - `EscapeRoom`: High-level entrypoint for basin-hopping escapes.
- **Top-Level Functions (3):** `canonical_geometry_hash`, `calculate_rmsd`, `create_fair_provenance_record`.

##### `mechanics/cochem_topos_memory.py` (1666 lines)
- **Architectural Role:** Dynamic hardware resource broker, GPU memory manager, and precision downgrade protocol.
- **Physical Classes (19):** `EngineTier`, `TheoreticalTier`, `FallbackReason`, `DeviceType`, `PrecisionMode`, `GPUDeviceInfo`, `HardwareSnapshot`, `CascadeTransition`, `CascadeState`, `GeometryRecord`, `TrajectoryStep`, `TelemetryRecord`, `QCSchemaPoint`, `EngineOOMError`, `ToposHDF5MemoryManager`, `HardwareResourceBroker`, `UniversalFallbackCascade`, `FallbackCascadeStateMachine`, `PrecisionDowngradeProtocol`.
- **Top-Level Functions (13):** `get_atomic_mass`, `get_element_symbol`, `get_molecular_mass`, `get_cochem_workspace`, `get_artifacts_directory`, `get_registry_directory`, `get_databases_directory`, `get_system_config_path`, `load_system_config`, `sweep_stale_locks`, `generate_oom_autopsy`, `handle_engine_exit_code`, `enforce_precision_tier`.

---

#### 4.6 Spectroscopy Subsystem (`cochem/spectroscopy/`)

##### `cochem/spectroscopy/rotational_observables.py` (1427 lines)
- **Architectural Role:** High-precision microwave spectroscopic observables and Pickett SPCAT deck synthesis engine.
- **Physical Classes (7):**
  - `PrincipalInertiaRecord(BaseModel)`: Moments of inertia $I_a, I_b, I_c$, rotational constants $A, B, C$ (MHz), Ray's asymmetry $\kappa$, inertial defect $\Delta$.
  - `VibrationalCorrectionsRecord(BaseModel)`: Anharmonic vibrational corrections $\Delta B_{\text{vib}}$ across all $3N-6$ normal modes.
  - `CentrifugalDistortionRecord(BaseModel)`: Watson A-reduction ($\Delta_J, \Delta_{JK}, \Delta_K, \delta_J, \delta_K$) and S-reduction ($D_J, D_{JK}, D_K, d_1, d_2$) quartic and sextic centrifugal distortion constants.
  - `NuclearQuadrupoleRecord(BaseModel)`: Electric field gradient tensors and nuclear electric quadrupole coupling constants ($\chi_{aa}, \chi_{bb}, \chi_{cc}$) for nuclei with spin $I \ge 1$.
  - `DipoleObservableRecord(BaseModel)`: Principal inertial dipole moment projections ($\mu_a, \mu_b, \mu_c$) and total dipole magnitude (Debye).
  - `SpectroscopicDeck(BaseModel)`: Formatted Pickett `.par`, `.var`, and `.int` parameter card decks.
  - `SpectroscopicEngine`: Master spectroscopic prediction engine.
- **Top-Level Functions (2):** `resolve_nuclide_properties`, `_parse_spin`.

---

#### 4.7 Frontend & Pre-Flight Gatekeeper (`frontend/` & `topos/`)

##### `frontend/cochem_topos_preflight.py` (1146 lines)
- **Architectural Role:** Mathematical gatekeeper sanitizing raw input structures prior to compute consumption.
- **Physical Classes (5):**
  - `PreflightStatus(str, Enum)`: Preflight status (`PASSED`, `WARNING`, `FAILED`).
  - `ElementInfo(BaseModel)`: Atomic number, symbol, IUPAC mass, covalent radius.
  - `NuclearClash(BaseModel)`: Clash record between atoms with distance below physical thresholds ($r_{ij} < 0.5\text{ \AA}$).
  - `AtomDiagnostic(BaseModel)`: Per-atom coordination number and valency anomaly diagnostic.
  - `PreflightReport(BaseModel)`: Global preflight sanitization report.
- **Top-Level Functions (18):** `_make_json_serializable`, `normalize_element_symbol`, `get_element_info`, `get_monoisotopic_mass`, `get_monoisotopic_masses`, `compute_total_molecular_mass`, `compute_center_of_mass`, `compute_geometric_center`, `center_coordinates`, `compute_mass_weighted_coordinates`, `compute_moment_of_inertia_tensor`, `align_to_principal_axes`, `validate_spin_parity`, `detect_nuclear_clashes`, `build_connectivity_matrix`, `find_connected_fragments`, `assess_valency_and_radicals`, `sanitize_and_validate_seed`.

##### `frontend/cochem_topos_ui.py` (1387 lines)
- **Architectural Role:** Interactive Jupyter/Voila dashboard UI for parameterization, live telemetry, and state serialization (`TOPOS_Runtime_State.json`).
- **Physical Classes (5):**
  - `SafeStreamWrapper`: Stream wrapper preventing Windows cp1252 character crashes.
  - `SafeStatusOutput`: Status widget displaying clean ASCII/ANSI text.
  - `TOPOSRuntimeState(BaseModel)`: Live runtime state schema.
  - `ToposRuntimeConfig(BaseModel)`: User-configured calculation parameters.
  - `CochemToposUI`: Interactive ipywidgets dashboard controller.
- **Top-Level Functions (16):** `reconfigure_stream_encoding`, `sanitize_for_stream`, `safe_print`, `get_conformer_search_protocol`, `clamp_vram_ceiling`, `discover_cuda_devices`, `serialize_topos_runtime_config`, `execute_topos_search`, `cancel_topos_search`, `get_tier_info`, `calculate_node_hours`, `parse_xyz_content`, `parse_xyz_file`, `resolve_artifact_path`, `serialize_topos_runtime_state`, `create_topos_dashboard`.

##### `frontend/cochem_topos_prescreener.py` (327 lines)
- **Architectural Role:** Fast bimolecular intake validation and dissociation screener.
- **Physical Classes (4):** `GeometryClashError`, `UnphysicalDissociationError`, `UnguidedSmilesIntakeError`, `BimolecularPreScreener`.
- **Top-Level Functions (3):** `get_vdw_radius`, `get_covalent_radius`, `partition_fragments`.

##### `frontend/cochem_topos_voila_runner.py` (797 lines)
- **Architectural Role:** Headless Voila execution harness for automated UI integration and Draco test validation.
- **Physical Classes (5):**
  - `VoilaServerStatus(str, Enum)`: Server state (`STARTING`, `READY`, `STOPPED`, `FAILED`).
  - `VoilaLaunchConfig(BaseModel)`: Host, port, notebook path, and timeout settings.
  - `VoilaProcessHandle`: Wrapper around running Voila server process.
  - `VoilaTelemetryReport(BaseModel)`: Startup latency and HTTP responsiveness report.
  - `VoilaRunner`: Manages headless Voila dashboard execution and port binding.
- **Top-Level Functions (8):** `resolve_master_notebook_path`, `is_tcp_port_in_use`, `find_available_tcp_port`, `terminate_process_tree`, `build_voila_cli_args`, `poll_http_readiness`, `launch_voila_dashboard`, `main`.

---

#### 4.8 Continuous Integration & Anti-Spoofing Toolchain (`ci_tools/`)

##### `ci_tools/anti_spoof_linter.py` (352 lines)
- **Architectural Role:** AST-based anti-spoofing scanner enforcing the Zero-Mock Protocol.
- **Physical Classes (1):**
  - `AntiSpoofVisitor(ast.NodeVisitor)`: Scans Python syntax trees for forbidden tokens (`unittest.mock`, `MagicMock`, empty `pass` blocks, dead-end `NotImplementedError` stubs, synthetic loop data generators, and string obfuscation).
- **Top-Level Functions (5):** `load_amnesty_list`, `is_file_exempt`, `check_script`, `run_linter`, `main`.

##### `ci_tools/mendeleev_ast_linter.py` (831 lines)
- **Architectural Role:** AST linter verifying that all atomic mass and elemental radius references query `mendeleev` dynamically and contains zero hardcoded mass tables.
- **Physical Classes (2):**
  - `LinterViolation(NamedTuple)`: File, line, node type, and violation message.
  - `MendeleevASTVisitor(ast.NodeVisitor)`: Scans for hardcoded mass dictionaries, floating-point mass lookups, and unverified element mappings.
- **Top-Level Functions (6):** `load_periodic_table_symbols`, `normalize_path_posix`, `load_amnesty_file`, `scan_file`, `scan_directory`, `main`.

##### `ci_tools/verify_core_integrity.py` (152 lines)
- **Architectural Role:** Cryptographic hashring verification script validating codebase immutability against `.core_infrastructure_hashring.json`.
- **Physical Classes (1):**
  - `HashringModel(BaseModel)`: Hashring schema mapping file paths to expected SHA-256 digests.
- **Top-Level Functions (6):** `get_root_dir`, `get_hashring_file`, `get_core_dirs`, `calculate_hash`, `generate_hashring`, `verify_hashring`.

##### `ci_tools/verify_anti_patching.py` (184 lines)
- **Architectural Role:** AST scanner auditing for unauthorized monkey-patching and dynamic function intercepts.
- **Physical Classes (1):** `AntiPatchingVisitor(ast.NodeVisitor)`.
- **Top-Level Functions (3):** `audit_file`, `audit_repository`, `main`.

##### `ci_tools/cleanup_executor.py` (280 lines)
- **Architectural Role:** Cleanups temporary test artifacts, volatile scratch files, and stale IPC sockets.
- **Top-Level Functions (7):** `load_manifests`, `plan_actions`, `_find_purgeable_dirs`, `execute_plan`, `_dir_size`, `_fmt_size`, `print_results`.

##### `ci_tools/file_triage_classifier.py` (320 lines)
- **Architectural Role:** Audits files for Necessity and File-Triage Protocol (NFTP) compliance.
- **Top-Level Functions (6):** `classify_file`, `TRASH_PATTERN_PATH_CHECK`, `_path_contains_subpath`, `identify_module`, `run_classifier`, `print_summary`.

##### `ci_tools/Log_Sanitizer.py` (44 lines)
- **Architectural Role:** Truncates and sanitizes massive execution logs before LLM ingestion.
- **Top-Level Functions (1):** `sanitize_and_chunk_log`.

---

### 5. Formal Functional Requirements Catalog (REQ-TOPOS)

| ID | Title | Summary / Specification | Priority | Provenance |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-TOPOS-001** | Input Preflight Gatekeeping | Validate Cartesian coordinates for finite values, detect interatomic clashes ($r_{ij} < 0.5\text{ \AA}$), verify spin parity ($N_e$ vs multiplicity), and anchor IUPAC masses via `mendeleev`. | High | [M] `preflight.py` |
| **REQ-TOPOS-002** | Graph Cleavage & Topology Triage | Construct distance matrix, apply $1.15\times$ Pyykkö covalent radius scaling, evaluate NetworkX components, and triage into `MONOMER`, `STRONG_COMPLEX`, or `WEAK_COMPLEX`. | High | [M] `graph.py` |
| **REQ-TOPOS-003** | 4-Atom Bypass Protocol | Automatically flag isolated monomer fragments with $< 4$ atoms with `BYPASS_GOAT` to bypass unneeded thermal conformational exploration. | Medium | [D] `graph.py` |
| **REQ-TOPOS-004** | Rigid Monomer Swarm Packing | Perform Artificial Bee Colony (ABC) swarm optimization over 6-DoF rigid-body monomer coordinates with multi-site water models and harmonic bounding. | High | [M] `abcluster.py` |
| **REQ-TOPOS-005** | GOAT Conformer Exploration | Execute stochastic basin-hopping with Quench $\leftrightarrow$ Escape cycles, batched tensor inference, and ALPB implicit solvation for charged systems. | High | [M] `goat.py` |
| **REQ-TOPOS-006** | CREST iMTD-GC Secondary Search | Run independent CREST metadynamics enforcing non-covalent flags (`--nci --nocross --noreftopo --ewin 12.0`) and bias push damping. | High | [M] `crest_union.py` |
| **REQ-TOPOS-007** | Six-Step Conformer Union Protocol | Execute candidate pooling, common-level re-relaxation, and two-stage deduplication across GOAT, CREST, and initial seeds. | High | [M] `crest_union.py` |
| **REQ-TOPOS-008** | Union Coverage Diagnostics | Compute and log conformational attribution statistics (`GOAT_ONLY`, `CREST_ONLY`, `FOUND_BY_BOTH`, `INITIAL_SEED`). | Medium | [D] `crest_union.py` |
| **REQ-TOPOS-009** | Multi-Tier Crusher Sieve | Filter conformer pairs via Bounding-Box ($>10\%$), MolSym point group, Pyykkö connectivity hash, Coulomb matrix eigenspectrum ($1/r^6$), and DoF-scaled mass-weighted Eckart RMSD. | High | [M] `crusher.py` |
| **REQ-TOPOS-010** | Chiral Volume Inversion Lock | Evaluate signed tetrahedral chiral volume, perform spatial inversion ($\vec{r} \to -\vec{r}$), execute SO(3) Kabsch re-alignment, and tag enantiomer pairs ($g_i = 2$). | High | [M] `crusher.py` |
| **REQ-TOPOS-011** | Memory-Mapped Isomer Storage | Store candidate coordinate arrays out-of-core using `numpy.memmap` with SHA-256 header validation and crash recovery from HDF5 backup. | Medium | [D] `crusher.py` |
| **REQ-TOPOS-012** | Dynamic Two-Stage Quadrature | Schedule ORCA calculations transitioning from `defgrid1` to `defgrid3` when RMS force drops below $1.0 \times 10^{-3}\text{ Eh/Bohr}$; reject legacy `Grid3/5`. | High | [M] `TOPOS_Chunk_03_SRS.md` |
| **REQ-TOPOS-013** | Non-Covalent `%geom` Convergence | Inject strict convergence thresholds: $\text{TolMaxG} \le 1.0\times 10^{-5}$, $\text{TolE} \le 1.0\times 10^{-6}$, $\text{MaxIter} \le 150$. | High | [M] `TOPOS_Chunk_03_SRS.md` |
| **REQ-TOPOS-014** | SE(3) Rigid Kinematics & Monomer Constraints | Enforce monomer internal rigidity via `SE3RigidKinematicsEngine` while scanning intermolecular parameters ($R, \theta, \phi$); ban unphysical laboratory-frame Cartesian `{ C idx C }` locks. | High | [M] `TOPOS_Chunk_03_SRS.md` / `assembly.py` |
| **REQ-TOPOS-015** | Model Hessian Preconditioning | Enforce `InHess XTB2` or `InHess Lindh` preconditioning; forbid `Calc_Hess true` across all geometry optimizations. | High | [M] `TOPOS_Chunk_03_SRS.md` |
| **REQ-TOPOS-016** | Automated SCF Rescue Protocol | Parse `orca.out` for divergence / ping-pong oscillations; inject `! SlowConv VShift` and restart from last `.gbw` orbital seed (`%moinp`). | High | [M] `escalator_exec.py` |
| **REQ-TOPOS-017** | AutoCAS Multireference Trap | Monitor post-HF $T_1$ ($>0.02$) and $D_1$ ($>0.05$) diagnostics; halt calculation and downgrade to `! AutoCAS` upon multireference breakdown. | High | [M] `escalator_exec.py` |
| **REQ-TOPOS-018** | Geometrical Explosion Watchdog | Abort quantum calculations and terminate process groups if any covalent bond stretches $> 4.0\text{ \AA}$ during geometry optimization. | Medium | [M] `escalator_exec.py` |
| **REQ-TOPOS-019** | Subprocess Tree Isolation | Execute all calculation subprocesses under Win32 Job Objects with `CREATE_NO_WINDOW`, atexit zombie reaping, and 10s recursive SIGTERM/SIGKILL termination. | High | [M] `subprocess_broker.py` |
| **REQ-TOPOS-020** | QCSchema HDF5 PES Store | Persist PES scans and trajectories in hierarchical HDF5 stores with gzip+shuffle compression, Fletcher32 checksums, and zero lossy compression. | High | [M] `pes_h5.py` |
| **REQ-TOPOS-021** | Colbert-Miller 1D Sinc-DVR | Solve 1D nuclear Schrödinger equations using Sinc-DVR for infinite Cartesian, radial half-line, and finite box representations. | High | [M] `pes_h5.py` |
| **REQ-TOPOS-022** | Matrix-Free 3D Tensor DVR | Solve coupled 3D nuclear Hamiltonians using `scipy.sparse.linalg.LinearOperator` and `np.einsum` tensor contractions to prevent memory exhaustion. | High | [M] `pes_h5.py` |
| **REQ-TOPOS-023** | Vibrational Rotational Averaging | Compute wavefunction expectation values $\langle \mu_{\alpha\alpha} \rangle$ across DVR states to yield vibrationally averaged ground-state constants $B_0$. | High | [M] `pes_h5.py` |
| **REQ-TOPOS-024** | Pickett SPCAT Deck Synthesis | Synthesize dual-track Pickett `.par`, `.var`, and `.int` catalog files with Watson A/S reduction, centrifugal distortion, and quadrupole tensors. | High | [M] `rotational_observables.py` |
| **REQ-TOPOS-025** | GPU Accelerated Single Points | Execute FP64 DFT single points via `gpu4pyscf` under NVIDIA MPS with dynamic VRAM footprint profiling and CPU fallback. | Medium | [D] `gpu_point.py` |
| **REQ-TOPOS-026** | Heterogeneous Dual Parsl Scheduling | Schedule authoritative ORCA jobs to CPU P-cores (0-6), advisory MLFF to GPU P-core (7 under MPS), and utilities to E-cores. | Medium | [D] `hetero_config.py` |
| **REQ-TOPOS-027** | Method Matrix Integrity Guards | Enforce runtime guards G1 (Advisory authority rejection) through G7 (Cryptographic provenance in `provenance.jsonl`). | High | [M] `hetero_config.py` |
| **REQ-TOPOS-028** | Noble Gas Physical LJ Fallback | Provide calibrated authentic Lennard-Jones van der Waals potential calculation for noble gas systems with Lorentz-Berthelot combination rules. | High | [M] `cochem_topos_runner.py` |
| **REQ-TOPOS-029** | AST Anti-Spoofing Verification | Run AST linters on all code changes to guarantee zero dead-end stubs, no fake data loops, and dynamic Mendeleev mass queries. | High | [M] `ci_tools/` |
| **REQ-TOPOS-030** | Interactive UI State Serialization | Render ipywidgets parameterization dashboards and serialize machine state to `TOPOS_Runtime_State.json` without exposing direct execution code. | Medium | [D] `ui.py` |

---

### 6. Non-Functional Requirements & Host Protection (NFR-TOPOS)

- **NFR-TOPOS-01 (Desktop Heap Protection):** All host subprocess invocations must specify `creationflags = 0x08000000` (`CREATE_NO_WINDOW`). No visual console windows may be allocated.
- **NFR-TOPOS-02 (RAM & Scratch Ceilings):** Local worker scratch directories must be capped at 10 GB per job. When scratch exceeds 10 GB, aggressive pruning of intermediate wavefunctions and temporary matrices must be triggered.
- **NFR-TOPOS-03 (Process Concurrency Bounds):** Total concurrent worker spawns must be governed strictly by the `HardwareGuard`, maintaining at least 15% desktop heap headroom and 20% host RAM headroom.
- **NFR-TOPOS-04 (Zero-Mock Invariant):** All testing and execution must run against physical algorithms and authentic constraints. Stub classes, fake loops, and `pytest.skip` bypasses are strictly forbidden.
- **NFR-TOPOS-05 (Execution Timeout Budgets):** Subprocess invocations must enforce strict timeout ceilings (e.g. 1740s for Layer 2 workers, 3600s for ab initio calculations) with graceful process tree cleanup.
- **NFR-TOPOS-06 (Numerical Precision Standards):** All geometric coordinates, moments of inertia, and Hamiltonian matrices must use IEEE 754 64-bit double precision (`float64`).
- **NFR-TOPOS-07 (Idempotent HDF5 Access):** HDF5 PES files must operate under SWMR (Single-Writer Multiple-Reader) locking with `filelock` protection to prevent corruption during multi-worker access.

---

### 7. Data Architecture, QCSchema HDF5 & IPC Formats

#### 7.1 Hierarchical HDF5 PES Store Layout (`landscape.h5` / `pes.h5`)
```
/
├── meta/                                 [Attributes: schema_name, schema_version, created_utc, complex, n_atoms]
│   └── symbols                           [JSON string array of elemental symbols]
├── methods/
│   └── <method_id>/                      [Attributes: method, basis, aux_basis, program, keywords, driver]
├── points/
│   └── <method_id>/
│       ├── coordinates                   [Dataset (Npts, N, 3) float64 Angstrom, gzip+shuffle]
│       ├── energy                        [Dataset (Npts,) float64 Hartree, gzip+shuffle + Fletcher32]
│       ├── gradient                      [Dataset (Npts, N, 3) float64 Hartree/Bohr, gzip+shuffle]
│       ├── converged                     [Dataset (Npts,) bool]
│       ├── wall_s                        [Dataset (Npts,) float64 seconds]
│       ├── provenance                    [Dataset (Npts,) vlen string JSON metadata]
│       └── point_id                      [Dataset (Npts,) vlen string unique basin ID]
├── grids/
│   └── <grid_id>/                        [Datasets for grid axes, coordinates, and bounding boxes]
├── hessians/
│   └── <label>/                          [Dataset (3N, 3N) float64 Hartree/Bohr^2]
└── deduplicated_isomers/                 [Ensemble records: conformer candidates, chiral tags, degeneracy g_i]
```

#### 7.2 Runtime State JSON Schema (`TOPOS_Runtime_State.json`)
```json
{
  "timestamp": 1791089585.0,
  "system": {
    "chemical_formula": "H4O2",
    "atom_count": 6,
    "multiplicity": 1,
    "charge": 0
  },
  "execution": {
    "tier_id": "T1-10m",
    "protocol": "GOAT",
    "engine": "xTB",
    "method": "GFN2-xTB",
    "status": "RUNNING",
    "scratch_path": "/path/to/scratch/topos_job_12345678",
    "store_path": "/path/to/store/landscape.h5"
  },
  "metrics": {
    "candidates_generated": 142,
    "deduplicated_isomers": 12,
    "lowest_energy_hartree": -152.84729104,
    "chiral_pairs_count": 2
  }
}
```

---

### 8. External Tool & Hardware Integration Contracts

1. **ORCA 5.0 / 6.1:** External ab initio quantum chemistry engine invoked via subprocess. Handles DFT, TD-DFT, MP2, coupled-cluster single-points, and geometry optimizations. Communication via formatted `.inp` files and output buffer parsing (`orca.out`, `.gbw`).
2. **xTB 6.6+ / CREST 2.12+:** Semi-empirical quantum chemistry and metadynamics engines. Invoked via `xtb-python`, `tblite`, or CLI wrappers. Enforces `--nci`, `--nocross`, and `--noreftopo`.
3. **ABCluster 3.2+:** Rigid-body molecular cluster global optimizer. Native Python/NumPy vectorized implementation with optional subprocess hook to external C++ binary.
4. **ASE (Atomic Simulation Environment):** Primary in-memory molecular data structure (`ase.Atoms`), geometry optimization driver (BFGS, FIRE, LBFGS), and calculator adapter.
5. **RDKit:** Chemical informatics toolkit for bond perception, SMILES generation, and 2D/3D structure sanitization.
6. **Pickett SPCAT / SpycFit:** Rotational spectroscopy simulation binaries consuming `.par` parameter files and producing `.cat` frequency predictions.
7. **NVIDIA CUDA & MPS:** Hardware acceleration layer for `gpu4pyscf` and PyTorch MLFF models, partitioned into isolated execution slices (33% thread percentage, 6 GB VRAM limit).

---

### 9. Verification, Validation & Traceability Matrix

| Requirement ID | Verification Method | Physical Test Target / Benchmark | Test Suite Location | Provenance |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-TOPOS-001** | Physical Unit Test | Spin parity of radicals vs closed shells; Mendeleev mass checks | `tests/test_cochem_topos_preflight.py` | [M] |
| **REQ-TOPOS-002** | Physical Unit Test | Water dimer vs Fe-heme cleavage topology | `tests/test_topology_graph.py` | [M] |
| **REQ-TOPOS-003** | Physical Unit Test | Triatomic molecule (H2O, SO2) 4-atom bypass assertion | `tests/test_topology_graph.py` | [D] |
| **REQ-TOPOS-004** | Integration Test | $(H_2O)_6$ water hexamer prism/cage global optimization | `tests/test_cochem_topos_abcluster.py` | [M] |
| **REQ-TOPOS-005** | Integration Test | Ethylene glycol and alanine dipeptide conformational search | `tests/test_cochem_topos_goat.py` | [M] |
| **REQ-TOPOS-006** | Integration Test | Formic acid dimer non-covalent metadynamics pushing | `tests/test_cochem_topos_crest_union.py` | [M] |
| **REQ-TOPOS-007** | Integration Test | Full Six-Step Union execution with candidate pooling | `tests/test_cochem_topos_crest_union.py` | [M] |
| **REQ-TOPOS-009** | Physical Unit Test | Bounding-box, Coulomb eigenvalues, and Eckart RMSD on conformer pairs | `tests/test_topology_crusher.py` | [M] |
| **REQ-TOPOS-010** | Physical Unit Test | Bromochlorofluoromethane enantiomer inversion & $g_i=2$ tagging | `tests/test_topology_crusher.py` | [M] |
| **REQ-TOPOS-012** | AST & Integration | Two-stage grid progression `defgrid1` $\to$ `defgrid3`; reject legacy grids | `tests/topos/test_two_stage_grid_scheduling.py` | [M] |
| **REQ-TOPOS-013** | Integration Test | Non-covalent complex optimization meeting 5 tight gradient criteria | `tests/test_topos_chunk2_frozen_monomer.py` | [M] |
| **REQ-TOPOS-014** | Integration Test | Water dimer frozen monomer distance scan ($R = 2.5 \dots 5.0\text{ \AA}$) | `tests/test_topos_chunk2_frozen_monomer.py` | [M] |
| **REQ-TOPOS-015** | AST Code Audit | Verification that 0 occurrences of `Calc_Hess true` exist | `tests/topos/test_screening_hessian_deferral.py` | [M] |
| **REQ-TOPOS-016** | Unit Test | Parsing simulated oscillating SCF buffer and injecting `! SlowConv` | `tests/test_cochem_topos_escalator_exec.py` | [M] |
| **REQ-TOPOS-017** | Unit Test | $T_1 = 0.025$ post-HF diagnostic triggering `! AutoCAS` alert | `tests/test_cochem_topos_escalator_exec.py` | [M] |
| **REQ-TOPOS-018** | Unit Test | Dissociated bond ($r > 4.0\text{ \AA}$) killing OpenMPI process tree | `tests/test_cochem_topos_escalator_exec.py` | [M] |
| **REQ-TOPOS-019** | System Audit | Subprocess spawn verifying Win32 Job Object and `CREATE_NO_WINDOW` | `tests/test_cochem_core_subprocess_broker.py` | [M] |
| **REQ-TOPOS-020** | Physical File Test | Creation, chunk inspection, and Fletcher32 checksum validation on HDF5 | `tests/test_pes_h5.py` | [M] |
| **REQ-TOPOS-021** | Numerical Benchmark | 1D Morse potential bound states solved via Colbert-Miller Sinc-DVR | `tests/test_pes_h5.py` | [M] |
| **REQ-TOPOS-022** | Numerical Benchmark | Coupled 2D/3D tensor contraction DVR eigenvalues within $0.01\text{ cm}^{-1}$ | `tests/test_pes_h5.py` | [M] |
| **REQ-TOPOS-024** | Physical Benchmark | Rotational constants ($A, B, C$) of $SO_2$ matching experimental NIST data | `tests/test_rotational_observables.py` | [M] |
| **REQ-TOPOS-028** | Physical Benchmark | Helium dimer ($He_2$) potential minimum at $R_e = 2.97\text{ \AA}$ ($D_e = 0.0215\text{ kcal/mol}$) | `tests/test_topos_noble_gas_lj_fallback.py` | [M] |
| **REQ-TOPOS-029** | Static AST Sweep | Automated run of `anti_spoof_linter.py` and `mendeleev_ast_linter.py` | `tests/test_mendeleev_ast_linter.py` | [M] |

---
*End of Baseline Software Requirements Specification: CoChem-TOPOS Ecosystem.*
