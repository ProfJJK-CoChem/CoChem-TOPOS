# CoChem-TOPOS Master Execution Workflow (2026-08-07)

This document maps the complete, step-by-step execution workflow for the `CoChem-TOPOS` module. This workflow fully implements the combinatorial `GOAT` engine, active learning screens, and topological enantiomer sorting described in the *Method Matrix* and the *20260807 Architectural Changes* documents.

## Stage 1: Pipeline Handoff & Synchronization
1. **BASE Handoff:** `CoChem-BASE` concludes its operations and yields execution to `CoChem-TOPOS`, passing the memory-mapped lock for `cochem_state.h5`.
2. **Daemon Spawning:** TOPOS initializes its internal ZeroMQ endpoints and connects to the active `CoChem-SCRIBE` background archiver. 
3. **Data Extraction:** TOPOS reads the baseline `.xyz` geometry, hardware limits, and temporal Time-Tier budget from the HDF5 registry.

## Stage 2: Monomer Phase (The First GOAT Loop)
1. **Stochastic Seeding:** The input geometry is passed to the Global Optimization Algorithm (GOAT). Using active heating (via MD) and randomized kicks, TOPOS generates 1,000+ potential monomer conformer geometries.
2. **Crusher (Initial Triage):** The raw geometries are evaluated via `g-xTB`. Geometries that relax to identical structures (using basic RMSD filters) or shatter into fragments are rapidly discarded.
3. **Crusher (Interactive UI):** 
   - The Jupyter backend pauses execution and renders the top unique monomer isomers via an interactive 3D `nglview` carousel.
   - **Human-in-the-loop:** The user rotates the structures and buckets them into *Unique*, *Duplicate*, or *Enantiomer* categories. 
   - If a specific point group is desired, the user inputs the Schoenflies symbol (e.g., $C_{2v}$) to enforce symmetry on subsequent calculations.
4. **GOAT (Normal) & Crusher (Final):** The user-approved monomers are subjected to high-level DFT relaxation (e.g., `r2SCAN-3c`). The final topologies and energies are written to the HDF5 tensor.

## Stage 3: Strong Complex Combinatorial Phase
1. **Combinatorial Assembly:** TOPOS takes the user-approved monomer fragments and combinatorializes them into all possible permutations of "Strong Complexes" (e.g., covalently bound dimers or tightly hydrogen-bonded species).
2. **Active Learning MLFF Screen:** 
   - **Threshold Gate:** TOPOS applies a spatial hashing cutoff. Complexes exceeding a hard atom-count limit (e.g., >150 atoms) are discarded instantly to prevent GPU OOM crashes.
   - Because combinatorics create exponential numbers of structures ($N^2, N^3$), passing them all to `g-xTB` or DFT is impossible.
   - TOPOS forces all permutations through `MACE-OFF24m`. Evaluating in milliseconds, MACE discards 80-95% of the structures that exhibit unphysical steric clashes or repulsive interaction energies.
3. **GOAT Loop:** The surviving subset is passed through the same `EscRm -> Crusher -> GOAT -> Crusher (Interactive) -> GOAT (Normal)` sequence.
4. **Enantiomer Classification:** During the interactive Crusher loop, TOPOS employs Coulomb Matrices and Optical Rotatory Dispersion (ORD) to precisely flag enantiomeric pairs that evade standard RMSD detection. 
5. **Crusher (Final):** The surviving Strong Complexes undergo rigorous DFT optimization. The final geometries and calculated **Force Constant Matrices (Hessians)** are securely serialized to `cochem_state.h5`.

## Stage 4: Weak Complex Combinatorial Phase & LAM Detection
1. **Weak Complex Assembly:** The approved Monomers and Strong Complexes are combinatorialized into highly fluxional Van der Waals clusters.
2. **MLFF Screen & GOAT:** The exact same Active Learning Screen and GOAT loops from Stage 3 are executed.
3. **Dynamic Protocol Trigger (NCI/BSSE):**
   - As the final geometries are resolved, TOPOS calculates the Non-Covalent Interaction (NCI) index and the magnitude of the BSSE Counterpoise energy for the complex.
   - **Decision Gate:** If the interaction energy is $< 5$ kcal/mol, the complex is flagged as a true "Weak Complex".
   - A bold warning is generated in the UI, and TOPOS automatically appends the `LAM_TRIGGER_REQUIRED` boolean flag to the HDF5 tensor. This alerts the downstream `TORQ` engine that the rigid-rotor harmonic approximation is invalid, and 3D Sinc-DVR Large Amplitude Motion protocols must be employed.

## Stage 5: True Physics Kinetics (JAX-NEB & AIMD)
1. **Barrier Estimation:** For the finalized unique isomers, TOPOS isolates the Minimum Energy Pathways (MEP) separating them. It executes a true `optax`/`jax.grad` accelerated Nudged Elastic Band (NEB) calculation to determine interconversion barrier heights.
2. **Conformational Sampling:** If specified by the Time-Tier, TOPOS runs Ab Initio Molecular Dynamics (AIMD).
   - If explicit solvent is present, `_apply_shake_constraints` is executed to freeze internal solvent geometries.
   - If photochemistry is required, Non-Adiabatic Surface Hopping (sTDA) is triggered to map conical intersections.

## Stage 5: Final Serialization & TORQ Handoff
1. **Data Aggregation:** The final coordinates, DFT energies, NEB kinetic barriers, enantiomer chiral buckets, manually enforced symmetry flags, and the critical pre-calculated Hessians are bundled together.
2. **HDF5 Commit:** TOPOS flushes the bundle to the `cochem_state.h5` shared tensor.
3. **SCRIBE Notification:** The `CoChem-SCRIBE` background daemon acknowledges the payload commit and archives the final matrix.
4. **Pipeline Handoff:** TOPOS gracefully concludes execution, prompting the user in the UI that Stage 2 is complete, and instructing them to initialize the `CoChem-TORQ` notebook for Phase 3 (PES Scans and Anharmonicity).
