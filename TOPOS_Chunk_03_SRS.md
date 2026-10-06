# Software Requirements Specification (SRS): CoChem-TOPOS Subsystem
## Chunk 03: Two-Stage Dynamic Numerical Quadrature & Constraint Discipline
**Document Identifier:** `SRS-TOPOS-V4.2-CHUNK-03-2026-09` [M]  
**Standard Compliance:** IEEE 830 / ISO/IEC/IEEE 29148 [M]  
**Target Repository:** `D:\__CoChem\GitHub-Repo\CoChem-TOPOS` [M]  
**Dropzone Destination:** `D:\__agentic\dropzones\inbox_code\TOPOS_Chunk_03_SRS.md` [M]  

---

### 1. Introduction and Architectural Scope

#### 1.1 Purpose
This Software Requirements Specification (SRS) defines the formal functional, physical, and interface requirements for Chunk 03 of the CoChem-TOPOS subsystem. This chunk governs the implementation of two-stage dynamic numerical quadrature (`defgrid1` to `defgrid3`) and rigorous constraint discipline for non-covalent complexes and conformer cascades.

#### 1.2 System Context & Method Matrix Alignment
All numerical routines must conform strictly to the authoritative standards defined in [`Method_Matrix.md`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/Method_Matrix.md) and [`CoChem_User_Manual.md`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/CoChem_User_Manual.md):
1. **Dynamic Quadrature:** Initial exploratory geometry optimization iterations execute on loose integration grids (`defgrid1`) and dynamically tighten to production-grade integration grids (`defgrid3`) near the energy minimum. The deprecated legacy terms `Grid3` and `Grid5` are strictly rejected.
2. **Intermolecular Convergence:** Weakly bound non-covalent complexes require tightened `%geom` convergence parameters with maximum gradient tolerance `TolMaxG <= 1.0e-5` Hartree/Bohr and energy tolerance `TolE <= 1.0e-6` Hartree.
3. **Constraint Discipline (Frozen-Monomer Protocol):** High-level monomer internal coordinates are frozen to preserve intra-monomer structure ($A$), while the intermolecular distance and angular degrees of freedom ($R, \theta, \phi$) are optimized to define the intermolecular interaction potential ($B, C$).
4. **Hessian Preconditioning:** Geometry optimizations must never use `Calc_Hess true`. Hessian preconditioning must use exact semi-empirical methods (`InHess XTB2`) or empirical models (`InHess Lindh`).
5. **Physical Mass Integrity:** All mass calculations must dynamically query standard IUPAC isotopic masses via `mendeleev` or authentic physical constants tables. No hardcoded or rounded integer masses are permitted.

---

### 2. Functional Requirements

#### 2.1 REQ-TOPOS-012: Dynamic Two-Stage Integration Grid Scheduler
- **Description:** The subsystem shall construct ORCA calculation inputs using a two-stage integration grid protocol.
- **Stage 1 (Coarse Search):** Input generator must configure `! defgrid1` for initial geometric relaxation until root-mean-square force (RMS Force) drops below $1.0 \times 10^{-3}$ Hartree/Bohr.
- **Stage 2 (Fine Tightening):** Upon meeting Stage 1 convergence, the pipeline must read the binary coordinate/wavefunction output (`.gbw`), generate a tightened input file with `! defgrid3`, and run final convergence.
- **Deprecation Enforcement:** Any configuration requesting legacy `Grid3`, `Grid4`, or `Grid5` keywords must raise a validation exception (`InvalidGridConfigurationError`) and fail-fast prior to execution.

#### 2.2 REQ-TOPOS-013: Non-Covalent `%geom` Convergence & Tolerance Block
- **Description:** For intermolecular conformer search and non-covalent complex optimizations, the generator shall inject strict convergence parameters into the `%geom` block:
  ```orca
  %geom
    TolMaxG 1.0e-5
    TolRmsG 5.0e-6
    TolMaxD 1.0e-4
    TolRmsD 5.0e-5
    TolE    1.0e-6
    MaxIter 150
  end
  ```
- **Validation:** Optimization outputs must be verified to have converged on all five metrics. Relaxations terminated solely by `MaxIter` exhaustion must be flagged as `ERR_CONVERGENCE_WALL`.

#### 2.3 REQ-TOPOS-014: Frozen-Monomer Coordinate Constraint Generator
- **Description:** The subsystem shall generate coordinate constraints that freeze intra-molecular degrees of freedom of individual monomers while leaving intermolecular orientation degrees of freedom unconstrained.
- **Coordinate Matrix:** For monomer $M_1$ (atoms $1 \dots N_1$) and monomer $M_2$ (atoms $N_1+1 \dots N_1+N_2$), the `%geom` block shall define:
  ```orca
  %geom
    Constraints
      { C 0:11 C }  # Example: Freeze all Cartesian coordinates of Monomer 1
    end
  end
  ```
- **Rotational & Distance Scanning:** Intermolecular separation coordinate $R$ (defined between monomer centers-of-mass) must remain fully unconstrained or systematically scanned across the potential energy curve.

#### 2.4 REQ-TOPOS-015: Hessian Preconditioning Policy
- **Description:** The optimization driver shall enforce model Hessian preconditioning to eliminate unnecessary full ab initio Hessian evaluations during relaxation cycles.
- **Forbidden Parameters:** Configuration containing `Calc_Hess true` or `Calc_Hess exact` within geometry optimization runs shall be intercepted and rejected.
- **Permitted Preconditioners:**
  - `InHess XTB2` for systems supported by the GFN2-xTB parametrization.
  - `InHess Lindh` for general open/closed shell DFT topologies.

#### 2.5 REQ-TOPOS-016: IUPAC Dynamic Mass Matrix & Physical Validation Fixtures
- **Description:** Inertial tensor, center-of-mass, and thermodynamic vibrational partition function evaluations must dynamically query authentic isotopic masses using standard IUPAC 2021 atomic weight tables via the `mendeleev` library.
- **Physical Test Fixtures:** The implementation must be verified against two authentic non-covalent systems:
  1. Water dimer: $(H_2O)_2$ with $C_s$ symmetry.
  2. Formic acid dimer: $(HCOOH)_2$ with $C_{2h}$ double hydrogen-bonding symmetry.
- **Zero-Mock Directive:** No synthetic numbers, mocked test cases, or hardcoded dummy dictionaries are permitted in the test suite.

---

### 3. Non-Functional & Structural Requirements

- **Subprocess Safety:** All ORCA/xTB invocation wrappers must use `subprocess.run(..., check=True, timeout=3600)` wrapped in standard exception handling, with resource auditing via `psutil`.
- **Dynamic Pathing:** Hardcoded absolute drive paths must not be committed to code; paths must be resolved via `pathlib.Path` and environment variables.
- **Typing & Linting:** Strict Python 3.10+ type hints (`typing.Annotated`, `typing.Literal`, `pydantic.BaseModel`) are required across all parameter models.

---

### 4. Verification & Validation Metrics

| Requirement | Metric | Threshold | Provenance |
| :--- | :--- | :--- | :--- |
| REQ-TOPOS-012 | Grid keywords in stage 1 / stage 2 | `defgrid1` -> `defgrid3` | [M] |
| REQ-TOPOS-013 | Maximum energy gradient on non-covalent complex | $\le 1.0 \times 10^{-5}\text{ Hartree/Bohr}$ | [M] |
| REQ-TOPOS-014 | Monomer coordinate variance under constraint | $\Delta r \le 1.0 \times 10^{-8}\text{ \AA}$ | [M] |
| REQ-TOPOS-015 | Static code check for `Calc_Hess true` | 0 occurrences | [M] |
| REQ-TOPOS-016 | Water dimer hydrogen bond distance $R(O\cdots H)$ | $1.95 \pm 0.05\text{ \AA}$ | [E] |

---

### 5. Implementation Tasks

- **Task 3.1:** Implement two-stage numerical quadrature engine transitioning from defgrid1 to defgrid3 based on energy gradient threshold.
- **Task 3.2:** Implement frozen-monomer coordinate constraint generator to freeze monomer geometry A while optimizing intermolecular parameter R.
- **Task 3.3:** Integrate InHess Hessian preconditioning (XTB2/Lindh) and forbid Calc_Hess true in all geometry optimization routines.
- **Task 3.4:** Build dynamic IUPAC isotopic mass lookup module using mendeleev package to eliminate hardcoded atomic weights.
- **Task 3.5:** Validate two-stage optimization and constraint pipelines against authentic water dimer and formic acid dimer reference complexes.
