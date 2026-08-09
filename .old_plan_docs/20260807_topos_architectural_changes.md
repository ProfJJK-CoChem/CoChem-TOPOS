# CoChem-TOPOS Architectural Changes (2026-08-07)

This document outlines the requisite architectural refactoring for the `CoChem-TOPOS` module, strictly aligned with the *Method Matrix*, *Improving LAM Microwave Predictions*, and the comprehensive *100 Suggestions Gap Analysis*. These structural overhauls are mandatory before generating the executable TOPOS workflow.

## 1. The GOAT Combinatorial Loop Framework
**Target Files:** `core_engine/cochem_topos_crusher.py` and `cascade_engine/cochem_topos_cascade_orchestrator.py`

**Current State:** 
The orchestrator executes a linear progression from Tier 1 to Tier 4 on a static list of initial isomers without combinatorially building complexes or employing advanced early-rejection screens.

**Required Architectural Change:**
- **Nested Assembly State Machine:** `cochem_topos_master.py` must be rewritten to support the three-phase nested loop: `Monomer Search` $\rightarrow$ `Strong Complex Assembly` $\rightarrow$ `Weak Complex Assembly`.
- **Active Learning Pre-Screen (MACE-OFF24m):** To prevent exponential combinatorial explosion ($N^3$) during the assembly phases, a hyper-fast MACE-OFF24m barrier must be injected *before* the first `Crusher`. This MLFF screen evaluates interaction energies in milliseconds, discarding geometrically absurd or highly repulsive clashing complexes before they ever enter the GOAT optimization queue.
- **Dynamic HDF5 State Persistence:** The combinatorial matrices must be continuously streamed to `cochem_state.h5` to survive Jupyter kernel resets.

## 2. Advanced Deduplication & Enantiomer Classification
**Target File:** `core_engine/cochem_topos_crusher.py`

**Current State:** 
Deduplication relies on standard structural RMSD algorithms, which frequently fail to differentiate stereoisomers and struggle with fluxional Van der Waals clusters.

**Required Architectural Change:**
- **Chirality Tracker Integration:** Replace standard RMSD with invariant **Coulomb Matrices** or calculate instantaneous Optical Rotatory Dispersion (ORD) via `g-xTB`. This ensures that enantiomers are rigorously flagged and bucketed into chiral pairs rather than falsely merged.
- **Spectroscopic Override Mode:** If structural RMSD is ambiguous (e.g., highly symmetric rotamers), TOPOS must default to a 'Spectroscopic Override', collapsing isomers only if their theoretical Rotational Constants ($A, B, C$) match within a 1.5% tolerance window.
- **Symmetry Pinning:** If a user manually overrides a symmetry group via the interactive UI (e.g., forcing $C_{2v}$), TOPOS must permanently inject the ORCA point-group constraint (`%geom sym true end`) into the geometry block for all subsequent calculations.

## 3. Eradicating Mock Implementations (JAX-NEB & AIMD)
**Target Files:** `core_engine/cochem_topos_escape.py` and `cochem_topos_crusher.py`

**Current State:** 
Critical kinetic barrier estimations (JAX-NEB) and conformational samplings (AIMD) are relying on placeholder/mock implementations.

**Required Architectural Change:**
- **True MACE-JAX Gradients:** Rip out the mocked Nudged Elastic Band (NEB) logic in `_execute_jax_neb`. It must be replaced with true compiled VRAM gradients leveraging `jax.grad` and `optax` to minimize the elastic band along the Minimum Energy Pathway (MEP).
- **Surface Hopping & Shake Constraints:** The AIMD logic must be expanded to support Non-Adiabatic Surface Hopping (via sTD-DFT) for photochemistry. Furthermore, explicit `_apply_shake_constraints` must be enforced to freeze internal solvent geometries (like rigid water molecules) while allowing the solute cluster to evolve.

## 4. Handoff Telemetry: NCI flags & Hessians
**Target File:** `cascade_engine/cochem_cascade_hdf5.py`

**Current State:** 
TOPOS pushes optimized geometries and basic energies to the HDF5 registry but fails to pass critical mathematical derivatives required by downstream modules.

**Required Architectural Change:**
- **Hessian Preservation:** The `CascadeHDF5Serializer` must be updated to securely serialize the final Force Constant Matrix (Hessian) calculated during the `Crusher (Final)` stage. Passing this matrix directly to `CoChem-TORQ` saves hours of redundant VPT2 second-derivative calculations.
- **Weak Complex / LAM Trigger Indexing:** TOPOS must automatically calculate the Non-Covalent Interaction (NCI) index and the magnitude of the BSSE Counterpoise energy for all assembled complexes. If the interaction energy is $< 5$ kcal/mol, TOPOS must attach a boolean `LAM_TRIGGER_REQUIRED` flag to the tensor, instructing TORQ to initialize 3D Sinc-DVR protocols instead of rigid-rotor approximations.

## 5. Background Daemon Interface
**Target File:** `core_engine/cochem_topos_master.py`

**Current State:** 
TOPOS runs sequentially, blocking the main thread entirely.

**Required Architectural Change:**
- **Asynchronous UI Unblocking:** The Master Integrator must run via `asyncio.create_task()` or a ZeroMQ backend thread. This is mandatory to support the Interactive Jupyter UI (`TOPOS_UI_Architecture.md`), allowing the UI to constantly pull progress updates and pause for human-in-the-loop enantiomer sorting without dropping the kernel connection. 

---
**Next Step Readiness:** 
By implementing these structural pillars, `CoChem-TOPOS` will safely transition from a static geometry escalator into a dynamic, active-learning driven combinatorial engine. Once these changes are approved, the exceptionally detailed and complete UI/Execution Workflow for TOPOS can be securely generated.
