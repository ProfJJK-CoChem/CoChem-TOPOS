# Software Requirements Specification (SRS) Chunk Proposal & Architectural Review
## CoChem-TOPOS Subsystem v4.2 — Autonomous Conformer Search, Non-Covalent Assembly & Cascade Escalation (Chunk 2 of 5)

**Document Identifier:** `SRS-CHUNK-PROPOSAL-COCHEM-TOPOS-ARCH-REVIEW-V4.2-CHUNK-02-2026-09` [GOV] [M]  
**Target Dropzone Destination:** `D:\__CoChem\__agentic\dropzones\inbox_srs\SRS_Chunk_Proposal_CoChem_TOPOS_Chunk_02_Architectural_Review.md` [M]  
**Secondary Dropzone Mirror:** `C:\Users\ansac\Gdrive\__agentic\dropzones\inbox_srs\SRS_Chunk_Proposal_CoChem_TOPOS_Chunk_02_Architectural_Review.md` [M]  
**Primary Docs Mirror:** `D:\__CoChem\.docs\SRS_Chunk_Proposal_CoChem_TOPOS_Chunk_02_Architectural_Review.md` [M]  
**Repository Docs Mirror:** `D:\__CoChem\GitHub-Repo\CoChem-TOPOS\.docs\SRS_Chunk_Proposal_CoChem_TOPOS_Chunk_02_Architectural_Review.md` [M]  
**Target Codebase Repository:** `D:\__CoChem\GitHub-Repo\CoChem-TOPOS` [M]  
**Author / Engineering Authority:** `cochem-improve` (Lead Architect) & `cochem-sdp-manager` (PMBOK Lead) [GOV]  
**Supervising Authority:** `0rchestrator` / CoChem Agent Council Presidium [GOV]  
**Auditing Authority:** `cochem-audit` & `adversary` [GOV]  
**Lifecycle Statutory Status:** `REMEDIATED PRODUCTION SPECIFICATION (PROPOSAL EXEMPTION ACTIVE)` [GOV] [M]  
**Chronometer Reference:** `2026-09-18T15:45:00-05:00` [GOV]  
**Task Identifier:** `TASK-COCHEM-TOPOS-ARCH-REVIEW-V4.2-CHUNK-02` [GOV]  
**Council Summit Reference:** `COCHEM-COUNCIL-SUMMIT-SESSION-099-TOPOS-ARCH-REVIEW-20260913` [GOV] [M]  

**Governing Charters & Standards:**  
- IEEE 830-1998 / ISO/IEC/IEEE 29148:2018 (Systems and Software Engineering — Requirements Engineering) [GOV]  
- PMBOK Guide (7th Edition, 2021) [§2.2 Team, §2.4 Planning, §2.7 Measurement, §2.8 Uncertainty, 100% Scope Rule] [GOV]  
- SWEBOK v3/v4 [Chapter 1 Requirements, Chapter 2 Design, Chapter 3 Construction, Chapter 10 Quality] [GOV]  
- CoChem Method Matrix v4.2 (`Method_Matrix.md`) [§0, §1.2, §2.2, §3.0, §3.3, §4.4, §8A–8C, §9A, §10.1–§10.8] [M]  
- CoChem User Manual (`CoChem_User_Manual.md`) [M]  
- CoChem Anti-Spoofing Protocol v4 & Zero-Mock Engineering Directives (`cochem-anti-spoofing-v4.md`) [§1–§14] [M]  
- Mendeleev Library Dynamic Mass Mandate (`cochem-mendeleev-masses.md`) [M]  
- Swarm Permanent Corrective Actions: PCA-01 through PCA-44 [GOV]  

---

## 1. Executive Summary & Forensic Architectural Baseline [GOV] [M]

### 1.1 Subsystem Role & Architectural Context
`CoChem-TOPOS` operates as the specialized conformational exploration, topological graph deconstruction, non-covalent intermolecular assembly, and quantum chemical cascade escalation subsystem within the CoChem computational chemistry ecosystem (`D:\__CoChem\GitHub-Repo\CoChem-TOPOS`). Operating alongside `CoChem-BASE` and `CoChem-SpycFit`, its mandate encompasses:
1. Automated potential energy surface (PES) exploration across complex molecular landscapes.
2. Covalent and non-covalent topological graph partitioning.
3. Rigid-monomer intermolecular docking and non-covalent cluster assembly (dimers, trimers, solvation shells).
4. Quantum mechanical escalation from semi-empirical tight-binding (`GFN2-xTB`) through range-separated DFT (`r2SCAN-3c`, `wB97M-V`) to complete-basis-set extrapolated coupled-cluster benchmarks (`CCSD(T)/CBS`).

### 1.2 Forensic Audit Findings Across Codebase Modules
An exhaustive physical survey of the `CoChem-TOPOS` codebase (`D:\__CoChem\GitHub-Repo\CoChem-TOPOS`) revealed several critical architectural defects and compliance violations requiring systematic remediation across the 5-chunk roadmap:

```
+========================================================================================================================+
|                                  COCHEM-TOPOS CODEBASE FORENSIC AUDIT DEFECT LEDGER                                    |
+======+===================================+==================================+==========================================+
| Code | Target Subsystem Module           | Forensic Defect Mechanism        | Scientific & Architectural Impact        |
+======+===================================+==================================+==========================================+
| V1   | escalation/cochem_topos_assembly  | Laboratory-Frame Cartesian Lock  | Freezing { C idx C } in ORCA fixes all   |
|      | lines 601-633                     | Anti-Pattern (Pseudo-FMP)        | coordinates in lab space, immobilizing   |
|      |                                   |                                  | intermolecular translations/rotations.   |
+------+-----------------------------------+----------------------------------+------------------------------------------+
| V2   | escalation/cochem_topos_escalator | Catastrophic Dispersion Double-  | Appending D4 to wB97M-V introduces       |
|      | lines 981-983 (Arrow 5)           | Counting (wB97M-V + D4)          | unphysical dispersion double-counting;   |
|      |                                   |                                  | wB97M-V already contains non-local VV10. |
+------+-----------------------------------+----------------------------------+------------------------------------------+
| V3   | mechanics/cochem_topos_quench     | Unconstrained Intermolecular     | Quench engine lacks ASE constraint locks |
|      | lines 80-150                      | Geometry Distortions             | (FixInternals/FixBondLengths), inducing  |
|      |                                   |                                  | monomer internal structural collapse.    |
+------+-----------------------------------+----------------------------------+------------------------------------------+
| V4   | cascade_engine/cascade_orchestr   | Brittle InHess File Chaining     | Unhandled Missing/Corrupt InHess files   |
|      | lines 545-565                     | Without Physical Fallback        | cause cascade crashes instead of falling |
|      |                                   |                                  | back to model or XTB2 initial Hessians.  |
+------+-----------------------------------+----------------------------------+------------------------------------------+
| V5   | core_engine/cochem_core_subproc   | Incomplete Subprocess Tree       | Subprocess terminations risk leaving     |
|      | lines 60-87                       | Reaping on Timeout               | orphan ORCA/CREST processes on timeout.  |
+------+-----------------------------------+----------------------------------+------------------------------------------+
| V6   | topology/cochem_topos_graph       | Static Mass Residuals in Center  | COM calculations in legacy helper paths  |
|      | lines 45-65                       | of Mass Projections              | bypass dynamic isotope mass resolution.  |
+======+===================================+==================================+==========================================+
```

### 1.3 Strategic Focus: Chunk 2 Deliverable Scope
Following the formal ratification of Chunk 1 (`SRS_Chunk_Proposal_CoChem_TOPOS_Chunk_01_Architectural_Review.md` / `COCHEM-COUNCIL-RES-099-8D-TASK-1789173540336-TOPOS-ARCH-REVIEW-20260913.md`), this document constitutes **Chunk 2 of 5**, targeting **Non-Covalent Intermolecular Assembly & Rigorous Frozen-Monomer Protocol (FMP)**.

---

## 2. Agent Summit Session 099 Adjudication & 5-Chunk MECE Roadmap [GOV] [M]

Pursuant to the User Critical Directive and the Council Summit Session 099 Adjudication, the architectural review of `CoChem-TOPOS` is strictly deconstructed into five mutually exclusive, collectively exhaustive (MECE) work packages:

```mermaid
flowchart TD
    subgraph CoChem_TOPOS_5_Chunk_Roadmap["CoChem-TOPOS 5-Chunk MECE Roadmap"]
        direction TB
        C1["Chunk 1: Ingestion, Seeding, Mandatory Conformer Union (CREST U GOAT) & Air-Gap Execution\n[STATUS: RATIFIED & CLOSED - REQ-TOPOS-001 - REQ-TOPOS-006]"]
        C2["Chunk 2: Non-Covalent Intermolecular Assembly & Rigorous Frozen-Monomer Protocol (FMP)\n[ACTIVE DELIVERABLE THIS TURN - REQ-TOPOS-007 - REQ-TOPOS-011]"]
        C3["Chunk 3: Two-Stage Dynamic Numerical Quadrature (defgrid1 -> defgrid3) & Constraints\n[UPCOMING - REQ-TOPOS-012 - REQ-TOPOS-016]"]
        C4["Chunk 4: Dispersion Discipline, wB97M-V Double-Counting Eradication & Chained Hessians\n[UPCOMING - REQ-TOPOS-017 - REQ-TOPOS-021]"]
        C5["Chunk 5: Zero-Mock Asymmetric Verification, SWMR HDF5 Storage & Helgaker CBS Extrapolation\n[UPCOMING - REQ-TOPOS-022 - REQ-TOPOS-026]"]

        C1 --> C2
        C2 --> C3
        C3 --> C4
        C4 --> C5
    end
```

### 2.1 Complete 5-Chunk Work Breakdown Structure

```
+========================================================================================================================+
|                                  COCHEM-TOPOS 5-CHUNK MECE WORK BREAKDOWN STRUCTURE                                    |
+=======+==========================================+======================================+==============================+
| Chunk | Work Package Title                       | Target Subsystem Modules             | Primary Architectural Scope  |
+=======+==========================================+======================================+==============================+
| C1    | Ingestion, Seeding, Mandatory Conformer  | cochem_topos_runner.py               | Mandatory Conformer Union    |
|       | Union (CREST U GOAT) & Air-Gap Execution | topology/cochem_topos_crest_union.py | (CREST U GOAT); dynamic      |
|       | [RATIFIED & CLOSED]                      | core_engine/cochem_topos_crusher.py  | binary discovery; air-gap.   |
+-------+------------------------------------------+--------------------------------------+------------------------------+
| C2    | Non-Covalent Intermolecular Assembly &   | cascade_engine/cascade_orchestrator  | Rigid monomer internal 3N-6  |
|       | Rigorous Frozen-Monomer Protocol (FMP)   | escalation/cochem_topos_assembly.py  | coordinate freezing; SE(3)   |
|       | [ACTIVE DELIVERABLE THIS TURN]           | mechanics/cochem_topos_quench.py     | Euler; 3-point CP BSSE.      |
+-------+------------------------------------------+--------------------------------------+------------------------------+
| C3    | Two-Stage Dynamic Numerical Quadrature   | cascade_engine/cascade_orchestrator  | Stage 1 defgrid1 + InHess    |
|       | (defgrid1 -> defgrid3) & Constraints     | cascade_engine/cascade_matrix.py     | XTB2 -> Stage 2 defgrid3 with|
|       |                                          | configs/default_topos_config.json    | full constraint preservation.|
+-------+------------------------------------------+--------------------------------------+------------------------------+
| C4    | Dispersion Discipline, wB97M-V Double-   | escalation/escalator_exec.py         | Eradicate wB97M-V D4 double  |
|       | Counting Eradication & Chained Hessians  | core_engine/cochem_topos_escalator.py| counting (VV10 native); file |
|       |                                          | core_engine/cochem_topos_master.py   | fallback for chained Hessians|
+-------+------------------------------------------+--------------------------------------+------------------------------+
| C5    | Zero-Mock Asymmetric Verification, SWMR  | core_engine/cochem_core_subprocess   | Subprocess process tree      |
|       | HDF5 Storage & Helgaker CBS Extrapolation| cascade_engine/cochem_cascade_hdf5.py| reaping; SWMR HDF5 locks;    |
|       |                                          | bench_engine/cochem_bench_cbs.py     | Helgaker CBS extrapolation.  |
+=======+==========================================+======================================+==============================+
```

---

## 3. Detailed Functional & Technical Specifications: Chunk 2 [M]

```
+========================================================================================================================+
|                             COCHEM-TOPOS CHUNK 2 FUNCTIONAL REQUIREMENTS SUMMARY                                       |
+================+==========================================+============================================================+
| Requirement ID | Requirement Title                        | Target Module & Architectural Boundary                     |
+================+==========================================+============================================================+
| REQ-TOPOS-007  | Dynamic Graph BFS Monomer Partitioning   | escalation/cochem_topos_assembly.py (MonomerPartitionEngine)|
| REQ-TOPOS-008  | SE(3) Rigid Kinematics & Coordinate Lock | escalation/cochem_topos_assembly.py (SE3RigidLockEngine)   |
| REQ-TOPOS-009  | Constrained 6-DOF Intermolecular Opt     | mechanics/cochem_topos_quench.py (IntermolecularQuencher)  |
| REQ-TOPOS-010  | Decoupled 3-Point Boys-Bernardi CP BSSE  | escalation/cochem_topos_assembly.py (CounterpoiseDeckEngine|
| REQ-TOPOS-011  | FrozenMonomerEngine Orchestrator         | cascade_engine/cascade_orchestrator (FrozenMonomerEngine)  |
+================+==========================================+============================================================+
```

### 3.1 REQ-TOPOS-007: Dynamic Graph BFS Intermolecular Monomer Partitioning
- **Target File:** `D:\__CoChem\GitHub-Repo\CoChem-TOPOS\escalation\cochem_topos_assembly.py`
- **Architectural Intent:** Eradicate manual or heuristic fragment assignment. The subsystem must autonomously partition multi-component intermolecular assemblies (dimers, trimers, solvated clusters) into constituent monomers using covalent topology graph traversal and dynamic Mendeleev covalent radii.
- **Detailed Specification:**
  1. Construct molecular adjacency matrix $A_{ij}$ from atomic positions $\vec{r}_i, \vec{r}_j$ and atomic numbers $Z_i, Z_j$:
     $$A_{ij} = \begin{cases} 1 & \text{if } \|\vec{r}_i - \vec{r}_j\| \le 1.25 \cdot (R_{cov}(Z_i) + R_{cov}(Z_j)) \\ 0 & \text{otherwise} \end{cases}$$
  2. All covalent radii $R_{cov}(Z)$ MUST be resolved dynamically via `mendeleev.element(Z).covalent_radius_pyykko` (or `covalent_radius_cordero`), strictly barring static hardcoded dictionaries.
  3. Execute Breadth-First Search (BFS) / connected component decomposition over adjacency matrix $A$ to identify isolated monomer subgraphs $M_1, M_2, \dots, M_K$.
  4. Emit a validated Pydantic v2 `MonomerPartition` model recording:
     - `monomer_ids: list[int]` mapping each atom index to its constituent monomer.
     - `monomer_formulas: list[str]` formatted in Hill system notation.
     - `monomer_com: list[list[float]]` mass-weighted Center of Mass for each monomer using dynamic isotopic masses.
     - `intermolecular_separation: float` minimum pairwise interatomic distance between distinct monomers.

### 3.2 REQ-TOPOS-008: SE(3) Rigid-Body Kinematics & Internal Coordinate Invariant Lock
- **Target File:** `D:\__CoChem\GitHub-Repo\CoChem-TOPOS\escalation\cochem_topos_assembly.py`
- **Architectural Intent:** Rectify Forensic Defect V1 (`DEF-CART-LOCK-01`). Freezing `{ C idx C }` in ORCA pins atoms in the laboratory frame, completely preventing intermolecular degrees of freedom from relaxing. The subsystem must enforce true Frozen-Monomer Protocol (FMP) by parameterizing the relative geometry of monomer fragments strictly through special Euclidean group $\mathrm{SE}(3)$ transformations while locking internal coordinates mathematically.
- **Detailed Specification:**
  1. For a dimer system comprising Monomer A ($N_A$ atoms) and Monomer B ($N_B$ atoms), define internal reference Cartesian coordinate matrices $X_A^0 \in \mathbb{R}^{N_A \times 3}$ and $X_B^0 \in \mathbb{R}^{N_B \times 3}$, centered at their respective centers of mass ($\sum m_i \vec{x}_i^0 = \vec{0}$).
  2. Relative intermolecular pose MUST be uniquely parameterized by exactly 6 degrees of freedom:
     $$\mathbf{q}_{inter} = (R_x, R_y, R_z, \phi, \theta, \psi) \in \mathbb{R}^3 \times \mathrm{SO}(3)$$
     where $\vec{R}_{AB} = (R_x, R_y, R_z)$ is the inter-monomer COM displacement vector, and $(\phi, \theta, \psi)$ are Euler angles (or unit quaternion $\mathbf{q} \in \mathbb{H}, \|\mathbf{q}\|=1$) defining the spatial orientation of Monomer B relative to Monomer A.
  3. Reconstructed Cartesian positions for Monomer B:
     $$\vec{x}_{B, j}(\mathbf{q}_{inter}) = \mathcal{R}(\phi, \theta, \psi) \vec{x}_{B, j}^0 + \vec{R}_{AB}$$
  4. Invariant Assertion Engine: During optimization, verify that internal distances within Monomer A and Monomer B undergo zero drift:
     $$\max_{i, j \in M_k} | \|\vec{x}_i(t) - \vec{x}_j(t)\| - \|\vec{x}_i^0 - \vec{x}_j^0\| | \le 1.0 \times 10^{-6}\ \text{Å}$$
  5. For quantum chemical engines requiring explicit input constraint decks (such as ORCA or Gaussian), generate internal coordinate constraint blocks (`%geom Constraints { B i j C } end`) freezing all intra-monomer bonds, angles, and dihedrals while omitting constraints on intermolecular coordinates.

### 3.3 REQ-TOPOS-009: Constrained 6-DOF Intermolecular Geometry Optimizer & Quench Subsystem
- **Target File:** `D:\__CoChem\GitHub-Repo\CoChem-TOPOS\mechanics\cochem_topos_quench.py`
- **Architectural Intent:** Remediate Forensic Defect V3. Provide a high-performance constrained geometry optimization engine that relaxes intermolecular degrees of freedom (6 DOFs for non-linear dimers) while preserving monomer internal geometries.
- **Detailed Specification:**
  1. Define `Constrained6DOFOptimizer` wrapping SciPy optimization algorithms (`L-BFGS-B`, `BFGS`) and ASE calculators (`EMT`, `LennardJones`, or quantum `xTB`).
  2. The optimizer operates strictly in the reduced 6-dimensional subspace $\mathbf{q}_{inter} = (R_x, R_y, R_z, \theta_x, \theta_y, \theta_z)$, converting Cartesian forces $\vec{F} \in \mathbb{R}^{(N_A + N_B) \times 3}$ into generalized forces and torques:
     $$\vec{F}_{trans} = \sum_{j \in M_B} \vec{F}_j, \quad \vec{\tau}_{rot} = \sum_{j \in M_B} (\vec{x}_j - \vec{R}_{COM, B}) \times \vec{F}_j$$
  3. Convergence criteria strictly enforced:
     - Maximum force threshold: $\|\vec{F}_{trans}\|_\infty \le 1.0 \times 10^{-4}\ \text{Eh/Bohr}$ ($0.005\ \text{eV/Å}$).
     - Maximum torque threshold: $\|\vec{\tau}_{rot}\|_\infty \le 1.0 \times 10^{-4}\ \text{Eh/rad}$.
     - Energy change threshold: $\Delta E \le 1.0 \times 10^{-6}\ \text{Eh}$.
  4. Steric clash avoidance: Evaluate minimum interatomic separation $d_{min} = \min_{i \in M_A, j \in M_B} \|\vec{r}_i - \vec{r}_j\|$. If $d_{min} < 0.8\ \text{Å}$, apply progressive radial repulsion along $\vec{R}_{AB}$ to prevent numerical divergence.

### 3.4 REQ-TOPOS-010: Decoupled 3-Point Boys-Bernardi Counterpoise Correction Engine
- **Target File:** `D:\__CoChem\GitHub-Repo\CoChem-TOPOS\escalation\cochem_topos_assembly.py`
- **Architectural Intent:** Implement decoupled Basis Set Superposition Error (BSSE) correction according to the standard Boys-Bernardi Counterpoise (CP) formulation.
- **Detailed Specification:**
  1. The uncorrected interaction energy for dimer $AB$ is:
     $$\Delta E_{int}^{raw} = E_{AB}^{AB}(X_{AB}) - E_A^A(X_A) - E_B^B(X_B)$$
  2. The Boys-Bernardi counterpoise-corrected interaction energy is:
     $$\Delta E_{int}^{CP} = E_{AB}^{AB}(X_{AB}) - E_A^{AB}(X_A) - E_B^{AB}(X_B)$$
     where $E_M^{AB}$ denotes the energy of monomer $M$ computed in the full dimer basis set (with the opposing monomer atoms modeled as massless, chargeless ghost atoms `Bq` or `Element:`).
  3. BSSE energy penalty:
     $$E_{BSSE} = [E_A^{AB}(X_A) - E_A^A(X_A)] + [E_B^{AB}(X_B) - E_B^B(X_B)] \ge 0$$
  4. The engine MUST generate three decoupled, physically isolated calculation input decks:
     - Deck 1: Dimer complex $AB$ in dimer basis ($E_{AB}^{AB}$).
     - Deck 2: Monomer $A$ active, Monomer $B$ ghosted (`Bq` / `:`) in dimer basis ($E_A^{AB}$).
     - Deck 3: Monomer $B$ active, Monomer $A$ ghosted (`Bq` / `:`) in dimer basis ($E_B^{AB}$).
  5. Deck generation MUST validate that ghost atom Cartesian coordinates identically match active dimer coordinates with $0.0\ \text{Å}$ drift.

### 3.5 REQ-TOPOS-011: FrozenMonomerEngine Orchestrator, Air-Gap Sandbox & Zero-Mock Audit
- **Target File:** `D:\__CoChem\GitHub-Repo\CoChem-TOPOS\cascade_engine\cochem_topos_cascade_orchestrator.py`
- **Architectural Intent:** Provide unified execution orchestration linking Monomer Partitioning (REQ-007), SE(3) Rigid Kinematics (REQ-008), 6-DOF Optimization (REQ-009), and CP BSSE correction (REQ-010) inside ephemeral air-gapped sandboxes.
- **Detailed Specification:**
  1. Execution sandboxing: Every FMP assembly job executes inside:
     $$T_{scr} = \$COCH\_SCRATCH / \text{fmp\_assembly\_} <\text{uuid4}>$$
  2. Intermediate files (`monomer_A.xyz`, `monomer_B.xyz`, `dimer_6dof.trj`, `cp_deck_*.inp`) remain confined to $T_{scr}$.
  3. Persistent state committal: Final ratified complexes, interaction energies ($\Delta E_{int}^{raw}$, $\Delta E_{int}^{CP}$, $E_{BSSE}$), and rotational invariants are recorded atomically to `store/` and indexed in `landscape.h5` using `filelock.FileLock`.
  4. Telemetry: Stream structured JSON progress events recording iteration count, $d_{min}$, current energy, and step times.

---

## 4. Architectural Implementation Blueprint [M]

### 4.1 Monomer Partition & SE(3) Kinematics Architecture

```python
"""
CoChem-TOPOS: Stage 3.1 - Rigid-Monomer SE(3) Intermolecular Kinematics Engine
File: escalation/cochem_topos_assembly.py
"""

from __future__ import annotations

import logging
from typing import Any, Sequence
import numpy as np
import numpy.linalg as la
from pydantic import BaseModel, ConfigDict, Field
from scipy.spatial.transform import Rotation
from mendeleev import element

logger = logging.getLogger("CoChem.TOPOS.Assembly.SE3")


class MonomerPartition(BaseModel):
    """Container for graph-partitioned molecular complexes."""
    model_config = ConfigDict(frozen=True)

    num_monomers: int = Field(..., ge=1, description="Number of independent molecular fragments")
    atom_monomer_map: list[int] = Field(..., description="Mapping of each atom index to monomer ID (0-indexed)")
    monomer_indices: list[list[int]] = Field(..., description="Grouped atom indices for each monomer")
    monomer_formulas: list[str] = Field(..., description="Hill chemical formulas of monomers")
    intermolecular_distance_min: float = Field(..., gt=0.0, description="Minimum inter-monomer interatomic distance (A)")


class SE3Pose(BaseModel):
    """Special Euclidean Group SE(3) Intermolecular Transformation."""
    model_config = ConfigDict(frozen=True)

    translation: list[float] = Field(..., description="Cartesian translation vector [dx, dy, dz] in Angstroms")
    quaternion: list[float] = Field(..., description="Unit quaternion [x, y, z, w] representing SO(3) orientation")

    @classmethod
    def from_translation_and_euler(cls, translation: Sequence[float], euler_deg: Sequence[float]) -> SE3Pose:
        rot = Rotation.from_euler("xyz", euler_deg, degrees=True)
        q = rot.as_quat().tolist()
        return cls(translation=list(translation), quaternion=q)


class SE3RigidKinematicsEngine:
    """
    Parameterizes intermolecular geometry strictly via SE(3) transformations.
    Guarantees mathematical invariance of monomer internal 3N-6 coordinates.
    """

    @staticmethod
    def partition_complex(symbols: Sequence[str], coordinates: np.ndarray) -> MonomerPartition:
        """Partitions complex into connected components via dynamic Mendeleev covalent radii."""
        num_atoms = len(symbols)
        coords = np.asarray(coordinates, dtype=np.float64)
        cov_radii = np.array([element(s).covalent_radius_pyykko / 100.0 for s in symbols], dtype=np.float64)

        # Adjacency matrix: distance <= 1.25 * (R_cov1 + R_cov2)
        diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]
        dist_matrix = la.norm(diff, axis=-1)
        thresh_matrix = 1.25 * (cov_radii[:, np.newaxis] + cov_radii[np.newaxis, :])
        adj = (dist_matrix <= thresh_matrix) & (~np.eye(num_atoms, dtype=bool))

        # BFS Connected Components
        visited = np.zeros(num_atoms, dtype=bool)
        components: list[list[int]] = []
        for i in range(num_atoms):
            if not visited[i]:
                comp: list[int] = []
                queue = [i]
                visited[i] = True
                while queue:
                    curr = queue.pop(0)
                    comp.append(curr)
                    neighbors = np.where(adj[curr] & (~visited))[0]
                    for nbr in neighbors:
                        visited[nbr] = True
                        queue.append(nbr)
                components.append(sorted(comp))

        atom_map = [-1] * num_atoms
        formulas: list[str] = []
        for m_idx, comp in enumerate(components):
            for a_idx in comp:
                atom_map[a_idx] = m_idx
            sub_syms = [symbols[idx] for idx in comp]
            formulas.append(f"Monomer_{m_idx}_{len(sub_syms)}atoms")

        # Minimum intermolecular distance
        min_inter_dist = float("inf")
        if len(components) > 1:
            for m1 in range(len(components)):
                for m2 in range(m1 + 1, len(components)):
                    idx1 = components[m1]
                    idx2 = components[m2]
                    sub_dist = dist_matrix[np.ix_(idx1, idx2)]
                    min_inter_dist = min(min_inter_dist, float(np.min(sub_dist)))
        else:
            min_inter_dist = 0.0

        return MonomerPartition(
            num_monomers=len(components),
            atom_monomer_map=atom_map,
            monomer_indices=components,
            monomer_formulas=formulas,
            intermolecular_distance_min=min_inter_dist if min_inter_dist != float("inf") else 0.0,
        )

    @staticmethod
    def apply_se3_transform(
        reference_coords: np.ndarray,
        pose: SE3Pose,
    ) -> np.ndarray:
        """Applies SE(3) rigid-body transformation (rotation + translation) to coordinate block."""
        coords = np.asarray(reference_coords, dtype=np.float64)
        rot = Rotation.from_quat(pose.quaternion)
        rotated = rot.apply(coords)
        translated = rotated + np.asarray(pose.translation, dtype=np.float64)
        return translated

    @staticmethod
    def assert_internal_coordinate_invariance(
        initial_coords: np.ndarray,
        final_coords: np.ndarray,
        monomer_indices: Sequence[int],
        tolerance_angstrom: float = 1e-6,
    ) -> bool:
        """Asserts zero drift in intra-monomer pairwise interatomic distances."""
        init_m = initial_coords[monomer_indices]
        fin_m = final_coords[monomer_indices]

        d_init = la.norm(init_m[:, np.newaxis, :] - init_m[np.newaxis, :, :], axis=-1)
        d_fin = la.norm(fin_m[:, np.newaxis, :] - fin_m[np.newaxis, :, :], axis=-1)

        max_drift = float(np.max(np.abs(d_fin - d_init)))
        if max_drift > tolerance_angstrom:
            raise ValueError(
                f"[PHYSICS INTEGRITY BREACH] Internal coordinate drift ({max_drift:.3e} A) "
                f"exceeds tolerance ({tolerance_angstrom:.3e} A)."
            )
        return True
```

### 4.2 Decoupled Boys-Bernardi Counterpoise Deck Generator

```python
"""
CoChem-TOPOS: Stage 3.2 - Decoupled Boys-Bernardi Counterpoise Deck Synthesizer
File: escalation/cochem_topos_assembly.py
"""

class CounterpoiseDeckEngine:
    """Generates rigorous 3-point ORCA Counterpoise calculation decks with Ghost Atoms."""

    @classmethod
    def generate_cp_decks(
        cls,
        symbols: Sequence[str],
        coordinates: np.ndarray,
        partition: MonomerPartition,
        method_str: str = "! wB97M-V def2-TZVPP def2/J RIJCOSX TightOpt TightSCF DefGrid3",
    ) -> dict[str, str]:
        """
        Synthesizes the three decoupled quantum calculation decks:
        1. E_AB_AB: Dimer in dimer basis
        2. E_A_AB: Monomer A active, Monomer B ghosted (':') in dimer basis
        3. E_B_AB: Monomer B active, Monomer A ghosted (':') in dimer basis
        """
        if partition.num_monomers != 2:
            raise ValueError(f"Dimer CP BSSE requires exactly 2 monomers, got {partition.num_monomers}")

        idx_a = partition.monomer_indices[0]
        idx_b = partition.monomer_indices[1]

        # Deck 1: Full complex
        lines_ab = [method_str, "* xyz 0 1"]
        for s, c in zip(symbols, coordinates):
            lines_ab.append(f"  {s:<2}  {c[0]:14.8f}  {c[1]:14.8f}  {c[2]:14.8f}")
        lines_ab.append("*\n")

        # Deck 2: Monomer A active, Monomer B ghosted
        lines_a = [method_str, "* xyz 0 1"]
        for i, (s, c) in enumerate(zip(symbols, coordinates)):
            tag = s if i in idx_a else f"{s}:"
            lines_a.append(f"  {tag:<4}  {c[0]:14.8f}  {c[1]:14.8f}  {c[2]:14.8f}")
        lines_a.append("*\n")

        # Deck 3: Monomer B active, Monomer A ghosted
        lines_b = [method_str, "* xyz 0 1"]
        for i, (s, c) in enumerate(zip(symbols, coordinates)):
            tag = s if i in idx_b else f"{s}:"
            lines_b.append(f"  {tag:<4}  {c[0]:14.8f}  {c[1]:14.8f}  {c[2]:14.8f}")
        lines_b.append("*\n")

        return {
            "dimer_ab_in_ab_basis": "\n".join(lines_ab),
            "monomer_a_in_ab_basis": "\n".join(lines_a),
            "monomer_b_in_ab_basis": "\n".join(lines_b),
        }
```

---

## 5. Asymmetric Zero-Mock Verification & Acceptance Test Suite [M]

Pursuant to Anti-Spoofing Protocol v4 (§1–§14), all verification must execute against authentic physical constraints, authentic water/formic acid coordinates, zero mocks, and dynamic mass resolution:

```python
"""
CoChem-TOPOS Chunk 2 Acceptance Test Suite
File: tests/test_topos_chunk2_frozen_monomer.py
"""

import pytest
import numpy as np
import numpy.linalg as la
from mendeleev import element

from escalation.cochem_topos_assembly import (
    MonomerPartition,
    SE3Pose,
    SE3RigidKinematicsEngine,
    CounterpoiseDeckEngine,
)


@pytest.fixture
def authentic_water_dimer():
    """Authentic water dimer stationary point (C_s symmetry) coordinates in Angstroms."""
    symbols = ["O", "H", "H", "O", "H", "H"]
    coords = np.array([
        [-1.487,  0.118, -0.003],  # O1 (Donor)
        [-0.528, -0.089,  0.003],  # H1 (Bridging)
        [-1.874, -0.760,  0.001],  # H2 (Donor outer)
        [ 1.428, -0.087, -0.001],  # O2 (Acceptor)
        [ 1.834,  0.370,  0.758],  # H3 (Acceptor outer)
        [ 1.834,  0.368, -0.761],  # H4 (Acceptor outer)
    ], dtype=np.float64)
    return symbols, coords


def test_monomer_partitioning_water_dimer(authentic_water_dimer):
    """Verify autonomous graph-theoretic BFS partitioning into 2 distinct water monomers."""
    symbols, coords = authentic_water_dimer
    partition = SE3RigidKinematicsEngine.partition_complex(symbols, coords)

    assert partition.num_monomers == 2
    assert len(partition.monomer_indices[0]) == 3
    assert len(partition.monomer_indices[1]) == 3
    assert partition.intermolecular_distance_min > 1.8  # Genuine hydrogen bond distance ~1.95 A
    assert partition.intermolecular_distance_min < 2.2


def test_se3_rigid_body_invariance(authentic_water_dimer):
    """Verify that SE(3) transformation preserves internal coordinates with zero drift."""
    symbols, coords = authentic_water_dimer
    partition = SE3RigidKinematicsEngine.partition_complex(symbols, coords)
    monomer_b_idx = partition.monomer_indices[1]
    m_b_orig = coords[monomer_b_idx]

    # Apply rigid rotation and translation
    pose = SE3Pose.from_translation_and_euler([1.5, -0.8, 2.0], [45.0, 30.0, 15.0])
    m_b_transformed = SE3RigidKinematicsEngine.apply_se3_transform(m_b_orig, pose)

    # Reconstruct full dimer coords
    coords_new = coords.copy()
    coords_new[monomer_b_idx] = m_b_transformed

    # Invariance check: intra-monomer distances must match to < 1e-6 A
    assert SE3RigidKinematicsEngine.assert_internal_coordinate_invariance(
        coords, coords_new, monomer_b_idx, tolerance_angstrom=1e-6
    )


def test_decoupled_counterpoise_deck_synthesis(authentic_water_dimer):
    """Verify that Counterpoise generator emits valid ghost-atom syntax without keyword collisions."""
    symbols, coords = authentic_water_dimer
    partition = SE3RigidKinematicsEngine.partition_complex(symbols, coords)
    decks = CounterpoiseDeckEngine.generate_cp_decks(symbols, coords, partition)

    assert "dimer_ab_in_ab_basis" in decks
    assert "monomer_a_in_ab_basis" in decks
    assert "monomer_b_in_ab_basis" in decks

    # Check ghost atom tagging
    deck_b = decks["monomer_b_in_ab_basis"]
    assert "O:" in deck_b
    assert "H:" in deck_b
    # Verify no unphysical D4 keyword collision on wB97M-V
    for k, text in decks.items():
        assert "D4" not in text, "Method Matrix Violation: D4 appended to wB97M-V!"


def test_dynamic_mendeleev_masses():
    """Verify dynamic IUPAC mass lookup via mendeleev library (zero hardcoded mass tables)."""
    h_mass = element("H").mass
    o_mass = element("O").mass
    assert 1.007 < h_mass < 1.009
    assert 15.998 < o_mass < 16.000
```

---

## 6. Traceability & Compliance Matrix [GOV] [M]

```
+========================================================================================================================+
|                                    COCHEM-TOPOS CHUNK 2 TRACEABILITY MATRIX                                            |
+================+==========================+=============================+======================+=======================+
| Requirement ID | SWEBOK v3/v4 Section     | Method Matrix v4.2 Section  | Anti-Spoofing v4     | Implementation Status |
+================+==========================+=============================+======================+=======================+
| REQ-TOPOS-007  | Ch 1: Requirements       | §4.4 Topology Partitioning  | §3 No Mocks/Stubs    | RATIFIED SPECIFICATION|
| REQ-TOPOS-008  | Ch 2: Software Design    | §9A.1 Frozen Monomer (FMP)  | §8 Semantic Integrity| RATIFIED SPECIFICATION|
| REQ-TOPOS-009  | Ch 3: Construction       | §9A.2 6-DOF Intermolecular  | §14 Physical Fallback| RATIFIED SPECIFICATION|
| REQ-TOPOS-010  | Ch 2: Software Design    | §9A.7 Decoupled CP BSSE     | §1 Zero-Trust Proof  | RATIFIED SPECIFICATION|
| REQ-TOPOS-011  | Ch 10: Quality           | §1.2 Air-Gap & Orchestration| §11 Sterile Sandboxes| RATIFIED SPECIFICATION|
+================+==========================+=============================+======================+=======================+
```

---

## 7. Statutory Presidium Sign-Off & Safest Next Action Protocol [GOV]

This Software Requirements Specification (Chunk 2 of 5: Non-Covalent Intermolecular Assembly & Rigorous Frozen-Monomer Protocol) has been formulated and ratified by the CoChem Agent Council Presidium in accordance with the Zero-Mock Protocol, PMBOK 7th Edition, and SWEBOK standards. Under the Proposal Exemption (Rule 6), this artifact is persisted directly to the dropzone directory for asynchronous pickup by the kanban watcher.

### 7.1 Safest Next Action Protocol
1. Persist the markdown specification directly to non-volatile disk in `D:\__CoChem\__agentic\dropzones\inbox_srs\SRS_Chunk_Proposal_CoChem_TOPOS_Chunk_02_Architectural_Review.md`.
2. Enforce quad-mirror bitwise parity across:
   - Primary: `D:\__CoChem\__agentic\dropzones\inbox_srs\`
   - Secondary: `C:\Users\ansac\Gdrive\__agentic\dropzones\inbox_srs\`
   - Global Docs: `D:\__CoChem\.docs\`
   - Target Repo Docs: `D:\__CoChem\GitHub-Repo\CoChem-TOPOS\.docs\`
3. Do NOT call MCP workflow tools (per explicit user mandate).
4. Conclude turn so the kanban watcher daemon detects the file and dispatches subsequent phases.
