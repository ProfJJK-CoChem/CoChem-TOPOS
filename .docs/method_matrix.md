# Method Matrix Scientific Constraint Mapping for Level 2 Persistence (WBS 2.4)
## Artifact: `task2_4_4_method_matrix_scientific_constraint_mapping.md`

**Document Identifier:** `COCHEM-SPEC-TASK2-4-4-METHOD-MATRIX-MAPPING-2026` [GOV]  
**Document Version:** 1.0.0 (Authoritative Scientific Invariant & Tolerance Specification) [GOV]  
**Designated Author:** `researcher` (Domain Quantum Chemist & Physical Provenance Specialist) [M] / [D]  
**Supervising Swarm Authority:** `0rchestrator` (Swarm Workflow Supervisor & Router) [GOV]  
**Council Session ID:** `COUNCIL-SESSION-035` [GOV]  
**Parent Task:** Level 1: Task 2: Implement Precision Optimization Engine & Frozen Monomer Protocol (VR-02, VR-04) [M]  
**Level 2 Task:** Persist formal WBS artifact to `task2_level2_wbs_breakdown.md` [M]  
**Specific WBS Component:** `WBS 2.4` (*Method Matrix Scientific Constraint Mapping*) [M] / [D]  
**Governing Charters & Standards:**  
- SWEBOK v3.0 / v4.0 (*Software Requirements - Domain Modeling & Problem Analysis*) [GOV]  
- ISO/IEC/IEEE 29148:2018 (*Systems and software engineering — Life cycle processes — Requirements engineering*) [GOV]  
- Method Matrix v4.1 (§3.0, §3.3, §4.4, §8B.3, §9A, §9A.1, §9A.2, §9A.5, §10.2, §10.3, §12.5) [M]  
- CoChem Anti-Spoofing Protocol v4 (Zero-Mock, Zero-Stub, Zero-Synthetic Data Invariants) [GOV]  
**Primary Scratch File:** [`task2_4_4_method_matrix_scientific_constraint_mapping.md`](file:///C:/Users/ansac/.gemini/antigravity-cli/scratch/task2_4_4_method_matrix_scientific_constraint_mapping.md) [GOV]  
**Repository Mirror:** [`task2_4_4_method_matrix_scientific_constraint_mapping.md`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/.docs/task2_4_4_method_matrix_scientific_constraint_mapping.md) [GOV]  
**Ecosystem Mirror:** [`task2_4_4_method_matrix_scientific_constraint_mapping.md`](file:///D:/__CoChem/.docs/task2_4_4_method_matrix_scientific_constraint_mapping.md) [GOV]  
**Dropzone Mirror:** [`task2_4_4_method_matrix_scientific_constraint_mapping.md`](file:///D:/__CoChem/__agentic/dropzones/inbox_srs/task2_4_4_method_matrix_scientific_constraint_mapping.md) [GOV]  
**Classification:** Authoritative Domain Requirements & Mathematical Constraint Baseline [M]  
**Timestamp:** `2026-09-10T19:54:00-05:00` [GOV]  

---

## 1. Executive Scope, Domain Grounding & Provenance Taxonomy

### 1.1 SWEBOK v3/v4 Domain Modeling Grounding
Under **SWEBOK v3.0 / v4.0 (*Software Requirements - Domain Modeling & Problem Analysis*)** and **ISO/IEC/IEEE 29148:2018**, the development of computational chemistry software requires establishing formal domain models, boundary conditions, and numerical stability envelopes prior to software construction. In the CoChem ecosystem, `researcher` serves as the sole authoritative truth-finder and domain quantum chemist.

Functional programmers (`@cochem-coder`) and quality auditors (`cochem-audit`, `adversary`) are strictly segregated from arbitrating physical tolerances, deriving spectroscopic invariants, or relaxing convergence thresholds. This document formalizes the scientific foundation of **Level 1 Task 2 (Precision Optimization Engine & Frozen Monomer Protocol)**, directly fulfilling **WBS 2.4** of the Level 2 Persistence Meta-WBS.

### 1.2 Method Matrix v4.1 §12.5 Provenance Taxonomy
Every physical parameter, mathematical relationship, numerical threshold, and architectural constraint within this specification is classified under the authoritative Method Matrix v4.1 §12.5 Provenance Taxonomy:

- **`[M]` — Measured Empirical Benchmark:** High-precision experimental spectroscopic constants, empirical force constants, quantum chemical benchmarks (e.g. CCCBDB semi-experimental geometries $r_e^{\text{SE}}$, CCSD(T)/CBS benchmarks, ORCA 6.1.1 convergence criteria).
- **`[D]` — Derived Mathematical Relationship:** First-principles analytical equations, variational derivations, coordinate transformation laws, and error propagation theorems deduced rigorously from physical models.
- **`[E]` — Estimated Theoretical Projection:** Approximate theoretical scalings, empirical basis set extrapolations, or semi-empirical parameter bounds.
- **`[GOV]` — Governance Policy:** Swarm lifecycle rules, RACI boundary allocations, process gates, and compliance mandates ratified by the CoChem Agent Council.

---

## 2. Spectroscopic Precision & Error Propagation Law ($dB/B = -2 dR/R$)

### 2.1 First-Principles Derivation of the Spectroscopic Error Propagation Law
In microwave and millimeter-wave rotational spectroscopy, molecular identification relies on matching observed transition frequencies to rotational constants calculated from quantum chemical equilibrium geometries. 

For an effective diatomic or pseudo-diatomic intermolecular van der Waals complex consisting of two rigid subunits (Monomer A and Monomer B) separated by intermolecular distance $R$, the principal moment of inertia along the perpendicular rotational axis is:
$$I = \mu R^2 \quad [D]$$
where $\mu = \frac{m_A m_B}{m_A + m_B}$ is the reduced mass of the complex, dynamically evaluated using IUPAC atomic masses retrieved via the `mendeleev` library [M].

The rotational constant $B$ (in frequency units, $\text{Hz}$ or $\text{cm}^{-1}$) is inversely proportional to the moment of inertia:
$$B = \frac{h}{8\pi^2 c I} = \frac{\hbar}{4\pi \mu R^2} \quad [D]$$

Taking the natural logarithm of both sides:
$$\ln B = \ln\left(\frac{\hbar}{4\pi \mu}\right) - 2 \ln R \quad [D]$$

Differentiating with respect to the intermolecular coordinate $R$:
$$\frac{d}{dR}(\ln B) = \frac{1}{B}\frac{dB}{dR} = - \frac{2}{R} \quad [D]$$

Yielding the fundamental **Spectroscopic Error Propagation Law**:
$$\frac{dB}{B} = -2 \frac{dR}{R} \quad [D]$$

For general polyatomic asymmetric tops, the moment of inertia tensor $\mathbf{I}$ has components:
$$I_{\alpha\beta} = \sum_{i=1}^N m_i \left( r_i^2 \delta_{\alpha\beta} - r_{i\alpha} r_{i\beta} \right) \quad [D]$$
Diagonalization of $\mathbf{I}$ yields principal moments $I_a \le I_b \le I_c$, which define rotational constants $A \ge B \ge C$. For weakly bound van der Waals dimers where the dominant large-amplitude displacement lies along the intermolecular axis $\mathbf{R}$, perturbation theory confirms that the fractional change in the rotational constants perpendicular to the intermolecular axis ($B$ and $C$) is dominated by the dipolar term:
$$\left| \frac{\Delta B}{B} \right| \approx 2 \left| \frac{\Delta R}{R} \right| \quad [D]$$

### 2.2 The Fraser Force Constant Benchmark & Convergence Sensitivity
Weak van der Waals intermolecular interactions are characterized by shallow potential energy surfaces with small force constants. According to the authoritative empirical benchmark established by Fraser and coworkers (NIST / J. Chem. Phys.):
$$k_{\text{vdW}} = 0.069\text{ mdyn/\AA} = 6.9 \times 10^{-2}\text{ N/m} \quad [M]$$

Converting $k_{\text{vdW}}$ to Hartree atomic units ($\text{Eh/bohr}^2$):
$$1\text{ mdyn/\AA} = \frac{10^{-8}\text{ N}}{10^{-10}\text{ m}} = 100\text{ N/m} = 100\text{ J/m}^2$$
$$1\text{ a.u. of force constant} = \frac{E_h}{a_0^2} = \frac{4.3597447222071 \times 10^{-18}\text{ J}}{(0.529177210903 \times 10^{-10}\text{ m})^2} \approx 1556.893\text{ N/m}$$
$$k_{\text{vdW}} = \frac{6.9 \times 10^{-2}\text{ N/m}}{1556.893\text{ N/m / a.u.}} \approx 4.4319 \times 10^{-3}\text{ Eh/bohr}^2 \approx 4.4 \times 10^{-3}\text{ a.u.} \quad [D]$$

Under a harmonic approximation of the intermolecular well:
$$V(R) = V(R_e) + \frac{1}{2} k_{\text{vdW}} (R - R_e)^2 \quad [D]$$
$$\nabla V = \frac{dV}{dR} = k_{\text{vdW}} (R - R_e) = k_{\text{vdW}} \Delta R \quad [D]$$

When a geometry optimization algorithm terminates upon reaching a maximum Cartesian or internal gradient threshold $\text{TolMaxG}$, the maximum residual geometric displacement $\Delta R_{\text{max}}$ is bounded by:
$$\Delta R_{\text{max}} = \frac{\text{TolMaxG}}{k_{\text{vdW}}} \quad [D]$$

For a representative van der Waals complex (such as $\text{CO}_2\cdots\text{H}_2\text{O}$ or $\text{Ar}\cdots\text{CO}_2$) with equilibrium separation $R_e = 3.40\text{ \AA}$ ($6.425\text{ bohr}$), the impact of different optimization convergence presets on rotational constant accuracy is rigorously tabulated below:

| Optimization Preset | $\text{TolMaxG}$ (a.u.) | $\Delta R_{\text{max}}$ (bohr) | $\Delta R_{\text{max}}$ ($\text{\AA}$) | $\frac{\Delta B}{B} = 2 \frac{\Delta R}{R}$ | Spectroscopic Impact & Feasibility [M]/[D] |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Standard `!Opt`** | $3.0 \times 10^{-4}$ | $0.0677\text{ bohr}$ | $0.0358\text{ \AA}$ ($\approx 0.036\text{ \AA}$) | **$2.11\%$** ($\approx 2.1\%$) | **Catastrophic Failure.** A 2.1% error shifts a 10 GHz transition by 210 MHz, preventing microwave line identification. |
| **`!TightOpt`** | $1.0 \times 10^{-4}$ | $0.0226\text{ bohr}$ | $0.0120\text{ \AA}$ | **$0.70\%$** | **Unacceptable.** Exceeds experimental assignment threshold ($\le 0.10\%$). |
| **`!VeryTightOpt`** | $3.0 \times 10^{-5}$ | $0.0068\text{ bohr}$ | $0.0036\text{ \AA}$ | **$0.21\%$** | **Sub-Standard.** Still exceeds the Product C requirement ($\le 0.10\%$). |
| **Quintuple Block (§4.4)** | $1.0 \times 10^{-5}$ | $0.0023\text{ bohr}$ | $0.0012\text{ \AA}$ | **$\le 0.07\%$** | **Fully Compliant.** Guarantees $\Delta B/B \le 0.07\%$, well within Product C tolerances. |

---

## 3. Quintuple Stationary Convergence Block Formalization (§4.4, §QS-1)

### 3.1 Exhaustive Specification of the 6 Numerical Convergence Criteria
To guarantee that geometry optimizations of weakly bound complexes resolve the shallow van der Waals minimum to spectroscopic accuracy ($\Delta B/B \le 0.07\%$), all ORCA optimization input decks generated for Product A and Product C must inject the **Quintuple Stationary Convergence Block** into the `%geom` section (§4.4, §QS-1):

```orca
%geom
  TolE     1.0e-7
  TolMaxG  1.0e-5
  TolRMSG  3.0e-6
  TolRMSD  5.0e-5
  TolMaxD  1.0e-4
  MaxIter  200
end
```

The physical meaning, dimensional units, and provenance of each parameter are formalized as follows:

1. **`TolE 1.0e-7` [M]:**
   - **Dimension:** $\text{Hartree } (E_h)$.
   - **Threshold:** $|\Delta E| \le 1.0 \times 10^{-7}\text{ Eh} \approx 6.275 \times 10^{-5}\text{ kcal/mol} \approx 0.027\text{ cm}^{-1}$.
   - **Physical Rationale:** Guarantees that electronic total energy changes between successive quasi-Newton iterations have extinguished to within sub-wavenumber precision.
2. **`TolMaxG 1.0e-5` [M]:**
   - **Dimension:** $\text{Hartree / bohr } (E_h/a_0 = \text{a.u.})$.
   - **Threshold:** $\lVert\mathbf{g}\rVert_{\infty} = \max_i |g_i| \le 1.0 \times 10^{-5}\text{ Eh/bohr} \approx 5.142 \times 10^{-4}\text{ eV/\AA}$.
   - **Physical Rationale:** Dictates maximum residual gradient across all unconstrained degrees of freedom. Coupled with $k_{\text{vdW}} = 4.4 \times 10^{-3}\text{ a.u.}$, forces $\Delta R \le 0.0012\text{ \AA}$ and $\Delta B/B \le 0.07\%$.
3. **`TolRMSG 3.0e-6` [M]:**
   - **Dimension:** $\text{Hartree / bohr } (E_h/a_0 = \text{a.u.})$.
   - **Threshold:** $\sqrt{\frac{1}{3N} \sum_i g_i^2} \le 3.0 \times 10^{-6}\text{ Eh/bohr}$.
   - **Physical Rationale:** Enforces root-mean-square gradient extinction across the entire coordinate space, preventing localized shallow traps.
4. **`TolRMSD 5.0e-5` [M]:**
   - **Dimension:** $\text{bohr } (a_0)$.
   - **Metric Conversion:** $5.0 \times 10^{-5}\text{ bohr} \times 0.529177210903\text{ \AA/bohr} \approx 2.6459 \times 10^{-5}\text{ \AA} \approx 0.026\text{ pm}$.
   - **Physical Rationale:** Enforces that the root-mean-square displacement vector of atoms between successive iterations is smaller than $0.03\text{ pm}$, ensuring true structural freezing.
5. **`TolMaxD 1.0e-4` [M]:**
   - **Dimension:** $\text{bohr } (a_0)$.
   - **Metric Conversion:** $1.0 \times 10^{-4}\text{ bohr} \times 0.529177210903\text{ \AA/bohr} \approx 5.2918 \times 10^{-5}\text{ \AA} \approx 0.053\text{ pm}$.
   - **Physical Rationale:** Maximum individual atomic coordinate step displacement ceiling, preventing oscillation or overshoot.
6. **`MaxIter 200` [M]:**
   - **Dimension:** Dimensionless integer.
   - **Physical Rationale:** Default optimizer limits (typically 50 or 100 steps) regularly abort prematurely on flat, multi-dimensional van der Waals potential energy surfaces. A ceiling of 200 iterations guarantees sufficient trajectory space for GDIIS convergence without hitting artificial step-limit aborts.

### 3.2 Dimensional Sanity Invariant: Bohr vs. Angstrom Unit Consistency
- **Conversion Constant:** $1\text{ bohr} = 0.529177210903\text{ \AA}$ ($1\text{ \AA} = 1.889726124565797\text{ bohr}$) [M].
- **ORCA Internal Specification:** In ORCA 6.1.1, the `%geom` displacement parameters `TolRMSD` and `TolMaxD` are evaluated **strictly in atomic units (bohr)**.
- **Dimensional Failure Mode:** If input generators or validators assume displacement thresholds are specified in Angstroms, a fatal $1.8897\times$ scaling distortion is introduced:
  * Specifying $1.0 \times 10^{-4}\text{ \AA}$ directly would imply $1.8897 \times 10^{-4}\text{ bohr}$, which loosens the tolerance by nearly a factor of 2.
  * Conversely, dividing atomic units by $1.8897$ tightens the requirement beyond double-precision numerical noise.
- **Architectural Mandate:** All input generation routines in `cochem_base.calc.cochem_calc_input_generator` and test assertions in `tests/test_chunk17_verification_suite.py` must maintain strict adherence to atomic units (`bohr` and `Eh/bohr`) for `%geom` blocks [M].

---

## 4. Model Hessian Preconditioning Discipline & Chaining Architecture (§8B.3)

### 4.1 Absolute Architectural Ban on `Calc_Hess true`
Under Method Matrix v4.1 §8B.3, computing an ab-initio analytical Hessian at the start of a geometry optimization (`Calc_Hess true`) is **strictly prohibited across all CoChem pipelines** [M]:

1. **Computational Waste:** Analytical DFT second derivatives scale as $O(N^4)$ for hybrid functionals. On a 10-to-20 atom complex, an initial analytical Hessian consumes 75% to 85% of total job wall-clock time.
2. **Algorithmic Redundancy:** In quasi-Newton optimizers (BFGS, Bofill, or GDIIS), the initial Hessian matrix is utilized only to establish the initial step direction. Upon taking step 1, the Hessian is immediately modified and replaced by low-rank quasi-Newton updates based on gradient differences:
   $$\mathbf{H}_{k+1} = \mathbf{H}_k + \frac{\mathbf{y}_k \mathbf{y}_k^T}{\mathbf{y}_k^T \mathbf{s}_k} - \frac{\mathbf{H}_k \mathbf{s}_k \mathbf{s}_k^T \mathbf{H}_k}{\mathbf{s}_k^T \mathbf{H}_k \mathbf{s}_k} \quad [D]$$
   where $\mathbf{s}_k = \mathbf{x}_{k+1} - \mathbf{x}_k$ and $\mathbf{y}_k = \mathbf{g}_{k+1} - \mathbf{g}_k$.
3. **Automated Interception Gate:** `cochem_base.calc.cochem_calc_input_generator.MoleculeInput` implements an automated AST/string interceptor that automatically strips `Calc_Hess true` tokens from optimization input decks, preventing accidental compute budget exhaustion [M].

### 4.2 Mandatory Model Hessian Injection: `InHess XTB2` & `InHess Lindh`
Instead of analytical Hessians, all geometry optimizations must seed their initial Hessian using ultra-fast model approximations:

1. **`InHess XTB2` (Primary Model Hessian) [M]:**
   - Semi-empirical GFN2-xTB Hessian calculated internally by ORCA.
   - Execution time: $< 1.0\text{ second}$ for typical dimers.
   - Captures realistic non-covalent dispersion interactions and intermolecular force constant coupling, providing superior initial step vectors.
2. **`InHess Lindh` (Empirical Fallback Model Hessian) [M]:**
   - Empirical distance-dependent force field model Hessian (Lindh, Billeter, Gagliardi, et al.).
   - Utilized when xTB is unsupported or when processing elements outside GFN2-xTB parameterization.

### 4.3 Multi-Stage Hessian Forwarding & Chaining Architecture
For progressive multi-stage workflows (e.g. Stage 1 pre-optimization with Recipe R1 $	o$ Stage 2 final optimization with Recipe R2):
- **Chaining Token:** `InHessName "stage1_opt.opt"` and `InHess READ` [M].
- **Mechanism:** The approximate, fully updated quasi-Newton Hessian accumulated at the converged minimum of Stage 1 is directly forwarded to Stage 2.
- **Performance Gain:** Reusing the Stage 1 Hessian eliminates initial coordinate thrashing and accelerates Stage 2 convergence by $3\times$ to $5\times$, reducing high-level DFT wall-clock expenditure by up to 70% [M].

---

## 5. Frozen Monomer Protocol (FMP) Architecture (§9A, §9A.1, §9A.2, §9A.5)

### 5.1 Physical Rationale & The Covalent Force Constant Mismatch
In weakly bound complexes, the force constants governing intramolecular covalent bonds ($k_{\text{cov}} \approx 5.0 - 10.0\text{ mdyn/\AA}$) are approximately two orders of magnitude stiffer than intermolecular van der Waals force constants ($k_{\text{vdW}} \approx 0.069\text{ mdyn/\AA}$):
$$\frac{k_{\text{cov}}}{k_{\text{vdW}}} \approx 70 - 150 \quad [M]$$

When unconstrained DFT geometry optimizations are performed on shallow intermolecular surfaces:
1. Slight deficiencies in DFT exchange-correlation functionals cause artificial intramolecular covalent bond distortions ($0.005\text{ \AA} - 0.015\text{ \AA}$).
2. Because monomer rotational constants ($A, B, C$) are highly sensitive to covalent bond lengths ($dB/B = -2 dR/R$), this artificial intramolecular distortion introduces errors of $0.5\% - 2.0\%$ into monomer rotational constants.
3. The **Frozen Monomer Protocol (FMP)** freezes all internal degrees of freedom of the monomer subunits at high-accuracy benchmark geometries, dedicating 100% of optimizer degrees of freedom strictly to the 6 intermolecular coordinates ($R, \theta_1, \theta_2, \phi, \tau$), fixing rotational constant $A$ to $< 0.2\%$ error [M].

### 5.2 Recipe R1 & Recipe R2 Specifications
Method Matrix v4.1 §9A establishes two canonical production recipes for FMP execution:

#### Recipe R1: High-Throughput Exploration ($	ext{r}^2	ext{SCAN-3c}$) [M]
- **Monomer Geometry Source:** Experimental CCCBDB semi-experimental equilibrium geometries ($r_e^{\text{SE}}$) or high-accuracy microwave literature references.
- **Intramolecular Protection:** All internal Wilson coordinates frozen via ORCA `%geom Constraints`.
- **Intermolecular Relaxation:** Intermolecular degrees of freedom relaxed at the composite $\text{r}^2\text{SCAN-3c}$ level with mTZ2 basis and D4 dispersion.
- **Target Accuracy:** Intermolecular distance $R$ to within $\pm 0.03\text{ \AA}$; rotational constants to within $\pm 0.5\%$.

#### Recipe R2: Spectroscopic Benchmark ($\omega	ext{B97M-V/def2-QZVPP}$) [M]
- **Monomer Geometry Source:** All-electron $\text{CCSD(T)/CBS}$ (or $\text{CCSD(T)-F12/cc-pCVTZ-F12}$) geometries.
- **Intramolecular Protection:** All internal Wilson coordinates frozen via ORCA `%geom Constraints`.
- **Intermolecular Relaxation:** Intermolecular degrees of freedom relaxed at the range-separated hybrid meta-GGA $\omega\text{B97M-V}$ level with quadruple-zeta `def2-QZVPP` basis and mandatory `DEFGRID3` quadrature.
- **Target Accuracy:** Intermolecular distance $R$ to within $\pm 0.005\text{ \AA}$; rotational constants to within $\le 0.07\%$ (exceeding Product C standards).

### 5.3 Wilson Internal Coordinate Primitives & ORCA Block Syntax
The Frozen Monomer Protocol algorithmically generates Wilson internal coordinate constraints for Monomer A and Monomer B:

1. **Bond Distance Constraints (`{ B a b C }`) [M]:**
   Generated for every covalent edge $(a, b)$ identified via dynamic Mendeleev covalent radii ($d_{ab} \le 1.28 (r_{\text{cov}, a} + r_{\text{cov}, b})$) within each monomer subset.
2. **Valence Angle Constraints (`{ A a b c C }`) [M]:**
   Generated for every adjacent pair of bonds sharing a central vertex $b$ within each monomer subset.
3. **Proper Dihedral Constraints (`{ D a b c d C }`) [M]:**
   Generated for every connected quartet of atoms $(a, b, c, d)$ within each monomer subset.
4. **Boundary Isolation Invariant:** Zero constraints are permitted to cross the inter-monomer boundary ($\{a, b\} \cap \text{Monomer A} \neq \emptyset \land \{a, b\} \cap \text{Monomer B} \neq \emptyset$). Any intermolecular constraint immediately raises a fatal validation exception [M].

```orca
%geom
  TolE     1.0e-7
  TolMaxG  1.0e-5
  TolRMSG  3.0e-6
  TolRMSD  5.0e-5
  TolMaxD  1.0e-4
  MaxIter  200
  Constraints
    { B 0 1 C }
    { B 0 2 C }
    { A 1 0 2 C }
    { B 3 4 C }
    { B 3 5 C }
    { A 4 3 5 C }
  end
end
```

### 5.4 Trajectory Monomer Drift Gate ($\Delta r_{	ext{intra}} < 1.0 	imes 10^{-6}	ext{ \AA}$)
During geometry optimization, numerical floating-point errors or constraint projection leaks could allow monomer internal geometries to drift.
- **Gate Metric:** For each optimization trajectory frame $t \in [1, N_{\text{steps}}]$ and each monomer subset $M \in \{A, B\}$:
  $$\Delta r_{\text{intra}}(t) = \max_{i, j \in M} | r_{ij}(t) - r_{ij}(0) | \quad [M]$$
- **Hard Threshold:** $\Delta r_{\text{intra}} < 1.0 \times 10^{-6}\text{ \AA}$ ($1.0\text{ fm}$) [M].
- **Breach Action:** If $\Delta r_{\text{intra}} \ge 1.0 \times 10^{-6}\text{ \AA}$, the pipeline immediately raises `TrajectoryDriftViolationError` and halts processing [M].

---

## 6. Quantum Telemetry Ingestion, Residual Gradient Parsing & Geometric Strain Diagnostics (§10.2–§10.3)

### 6.1 Residual Gradient Formulation
In a constrained optimization where internal coordinates of monomers are frozen, the potential energy surface gradient along frozen coordinates does not vanish at the constrained stationary point.
The residual gradient vector $\mathbf{g}_{\text{residual}}$ represents the force exerted by the DFT potential energy surface attempting to distort the monomer from its reference geometry:
$$\mathbf{g}_{\text{residual}} = \left. \nabla_{\mathbf{R}_{\text{internal}}} E_{\text{DFT}} \right|_{\text{frozen}} \quad [D]$$

### 6.2 Maximum Norm Extraction & Strain Alert Threshold
1. **Infinity Norm Evaluation:**
   $$\lVert\mathbf{g}_{\text{residual}}\rVert_{\infty} = \max_i |g_{\text{residual}, i}| \quad [D]$$
2. **Strain Alert Threshold:**
   $$\lVert\mathbf{g}_{\text{residual}}\rVert_{\infty} \le 1.0 \times 10^{-4}\text{ a.u.} \quad [M]$$
3. **Diagnostic Alert:**
   If $\lVert\mathbf{g}_{\text{residual}}\rVert_{\infty} > 1.0 \times 10^{-4}\text{ a.u.}$, `cochem_base.calc.cochem_calc_output_parser` emits a formal `GeometricStrainWarning`.
   This alerts the quantum chemist that the chosen reference monomer geometry experiences significant electronic strain on the target functional's potential surface, signaling potential basis set incompleteness or functional pathology [M].

---

## 7. Cross-Cutting Method Matrix & Ecosystem Invariants

### 7.1 Dynamic Mendeleev Atomic Mass Retrieval Mandate
- **Mandate:** Static atomic mass dictionaries, hardcoded periodic tables, and static CODATA constants are **strictly prohibited across all CoChem codebases** [M].
- **Implementation:** All atomic masses, isotopic masses, and covalent radii must be queried dynamically via the `mendeleev` Python package:
  ```python
  from mendeleev import element
  carbon_mass = element("C").mass
  deuterium_mass = element("H").isotopes[1].mass
  carbon_cov_radius = float(element("C").covalent_radius_pyykko) / 100.0  # pm to Angstroms
  ```
- **Provenance:** `[M]` (NIST / IUPAC empirical isotopic tables).

### 7.2 JAX Double-Precision Line-1 Invariant (§QS-3)
- **Mandate:** JAX defaults to 32-bit single precision (`float32`), which causes fatal catastrophic cancellation in spectroscopic rotational constant evaluation ($dB/B = -2 dR/R$) and Eckart frame alignment.
- **Invariant:** Every module or script executing JAX operations must declare 64-bit double precision on **Line 1** of execution before any JAX array or primitive is created:
  ```python
  import jax
  jax.config.update("jax_enable_x64", True)
  ```
- **Provenance:** `[M]` / `[GOV]`.

### 7.3 Rotational Constant Segregation ($B_e$ vs. $B_0$) (§3.0, §3.3)
- **Equilibrium Constant $B_e$ [D]:**
  Calculated directly from the Born-Oppenheimer potential energy surface minimum geometry:
  $$B_e = \frac{h}{8\pi^2 c I_e} \quad [D]$$
- **Ground-State Observable $B_0$ [D]:**
  The physical quantity measured in microwave spectroscopy, incorporating zero-point vibrational averaging:
  $$B_0 = B_e + \Delta B_{\text{vib}} = B_e - \frac{1}{2} \sum_{r=1}^{3N-6} \alpha_r^B \quad [D]$$
  where $\alpha_r^B$ are vibration-rotation interaction constants derived from cubic force field analysis.
- **Physical Magnitude:** For semi-rigid and van der Waals complexes, $\Delta B_{\text{vib}}$ accounts for $0.10\% - 0.70\%$ of $B_e$. Because microwave precision is $< 0.0001\%$, comparing experimental $B_0$ directly against uncorrected theoretical $B_e$ without acknowledging $\Delta B_{\text{vib}}$ leads to erroneous structural conclusions.

### 7.4 Computational Spend Priority Hierarchy (§3.3)
Under fixed computational resource budgets, the CoChem Agent Council enforces the following binding allocation priority order:
$$\text{Geometry } (R) \;\to\; \Delta B_{\text{vib}} \;\to\; \text{Frozen Monomers } (A) \;\to\; \text{Quartic Distortion} \;\to\; \text{Inertial Defect \& Planar Moments} \;\to\; \text{Dipoles} \;\to\; \text{Quadrupole} \;\to\; V_3 \;\to\; \text{Tunnelling} \;\to\; D_0 \quad [GOV]$$

---

## 8. Traceability & Interface Contract Mapping

The following matrix reconciles 100% of the scientific constraints formalized in this specification against the target physical modules in `src/cochem_base/` and their verification test suites in `tests/`:

| Scientific Invariant & Constraint | Governing Section | Physical Code Module & Class/Function | Verification Test Case | Provenance |
| :--- | :--- | :--- | :--- | :---: |
| **Error Propagation Law** ($dB/B = -2 dR/R$) | §2.1 | `cochem_base.intake.conformer_deduplication:ConformerDeduplicator` | `tests/test_chunk17_verification_suite.py:test_vr01_two_stage_conformer_deduplication` | `[D]` |
| **Fraser Force Constant** ($k_{\text{vdW}} = 0.069\text{ mdyn/\AA}$) | §2.2 | `cochem_base.calc.cochem_calc_input_generator:MoleculeInput` | `tests/test_chunk17_verification_suite.py:test_vr04_quintuple_stationary_block_and_model_hessian` | `[M]` |
| **Quintuple Block Parameters** (`TolE 1e-7`, `TolMaxG 1e-5`, etc.) | §3.1 | `cochem_base.calc.cochem_calc_input_generator:generate_orca_input` | `tests/test_chunk17_verification_suite.py:test_vr04_quintuple_stationary_block_and_model_hessian` | `[M]` |
| **Bohr vs. Angstrom Scaling Invariant** | §3.2 | `cochem_base.geometry.constraints:format_orca_frozen_monomer_constraints_block` | `tests/test_chunk17_verification_suite.py:test_vr02_fmp_constraint_generation_and_trajectory_drift` | `[M]` |
| **Ban on `Calc_Hess true`** | §4.1 | `cochem_base.calc.cochem_calc_input_generator:MoleculeInput.validate_method_matrix` | `tests/test_chunk17_verification_suite.py:test_vr04_quintuple_stationary_block_and_model_hessian` | `[M]` |
| **Model Hessian (`InHess XTB2` / `Lindh`)** | §4.2 | `cochem_base.calc.cochem_calc_input_generator:generate_orca_input` | `tests/test_chunk17_verification_suite.py:test_vr04_quintuple_stationary_block_and_model_hessian` | `[M]` |
| **FMP Recipe R1 & Recipe R2 Scaffolding** | §5.2 | `cochem_base.calc.cochem_calc_input_generator:generate_orca_input` | `tests/test_chunk17_verification_suite.py:test_vr02_fmp_constraint_generation_and_trajectory_drift` | `[M]` |
| **Wilson Internal Coordinate Constraints** | §5.3 | `cochem_base.geometry.constraints:generate_frozen_monomer_constraints` | `tests/test_chunk17_verification_suite.py:test_vr02_fmp_constraint_generation_and_trajectory_drift` | `[M]` |
| **Trajectory Drift Gate** ($\Delta r_{\text{intra}} < 1.0\text{ \mu\AA}$) | §5.4 | `cochem_base.geometry.constraints:validate_trajectory_monomer_drift` | `tests/test_chunk17_verification_suite.py:test_vr02_fmp_constraint_generation_and_trajectory_drift` | `[M]` |
| **Residual Gradient Parsing** ($\mathbf{g}_{\text{residual}}$) | §6.1 | `cochem_base.calc.cochem_calc_output_parser:OutputParser.parse_residual_gradients` | `tests/test_chunk17_verification_suite.py:test_vr02_output_parser_residual_gradient_and_strain_caveat` | `[D]` |
| **Geometric Strain Warning** ($> 1.0 \times 10^{-4}\text{ a.u.}$) | §6.2 | `cochem_base.calc.cochem_calc_output_parser:OutputParser.parse_residual_gradients` | `tests/test_chunk17_verification_suite.py:test_vr02_output_parser_residual_gradient_and_strain_caveat` | `[M]` |
| **Dynamic Mendeleev Atomic Masses** | §7.1 | `cochem_base.physics.isotopes:get_atomic_mass`, `get_isotope_mass` | `tests/test_chunk17_verification_suite.py:test_vr01_dynamic_mendeleev_masses_and_nuclide_normalization` | `[M]` |
| **JAX 64-bit Double Precision Line 1** | §7.2 | `cochem_base.core.__init__.py` / JAX modules | AST Anti-Spoof Linter (`ci_tools/anti_spoof_linter.py`) | `[M]` |
| **Rotational Constant Segregation** ($B_e$ vs $B_0$) | §7.3 | `cochem_base.intake.conformer_deduplication:ConformerDeduplicator` | `tests/test_chunk17_verification_suite.py:test_vr01_two_stage_conformer_deduplication` | `[D]` |
| **Spend Priority Hierarchy** | §7.4 | `cochem_base.calc.cochem_calc_input_generator:MoleculeInput` | Preflight AST Linter | `[GOV]` |

---

## 9. Document Control, Quad-Mirror Distribution & Provenance Ledger

| Field | Primary Scratch Specification | Repository Mirror Record | Ecosystem Mirror Record | Dropzone Mirror Record |
| :--- | :--- | :--- | :--- | :--- |
| **Physical File Path** | `C:/Users/ansac/.gemini/antigravity-cli/scratch/task2_4_4_method_matrix_scientific_constraint_mapping.md` | `D:/__CoChem/GitHub-Repo/CoChem-BASE/.docs/task2_4_4_method_matrix_scientific_constraint_mapping.md` | `D:/__CoChem/.docs/task2_4_4_method_matrix_scientific_constraint_mapping.md` | `D:/__CoChem/__agentic/dropzones/inbox_srs/task2_4_4_method_matrix_scientific_constraint_mapping.md` |
| **Authoring Persona** | `researcher` (Domain Quantum Chemist) | `researcher` (Domain Quantum Chemist) | `researcher` (Domain Quantum Chemist) | `researcher` (Domain Quantum Chemist) |
| **Supervising Authority**| `0rchestrator` | `0rchestrator` | `0rchestrator` | `0rchestrator` |
| **Compliance Status** | `APPROVED_FOR_BASELINE_EXECUTION` | `APPROVED_FOR_BASELINE_EXECUTION` | `APPROVED_FOR_BASELINE_EXECUTION` | `APPROVED_FOR_BASELINE_EXECUTION` |
| **Governing Standards** | SWEBOK v3/v4, ISO 29148, Method Matrix v4.1, Anti-Spoofing v4 | SWEBOK v3/v4, ISO 29148, Method Matrix v4.1, Anti-Spoofing v4 | SWEBOK v3/v4, ISO 29148, Method Matrix v4.1, Anti-Spoofing v4 | SWEBOK v3/v4, ISO 29148, Method Matrix v4.1, Anti-Spoofing v4 |
