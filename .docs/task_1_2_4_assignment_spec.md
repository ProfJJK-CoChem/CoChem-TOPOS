# CoChem Swarm Council Task Assignment Specification & Work Breakdown Structure
## TASK-1.2.4: Unit Verification Across IUPAC Periodic Table (Z=1..118)

**Document Identifier:** `COCHEM-SPEC-TASK-1.2.4-WBS-V1` [M]  
**Security & Governance Baseline:** Council Emergency Session 010 (`COCHEM-COUNCIL-RES-010-8D-ZERO-TRUST`) & Session 012 (`COCHEM-COUNCIL-RES-012-8D-ZERO-TRUST`) [M]  
**Effective Date:** 2026-09-11T08:05:00-05:00 [E]  
**Presiding Chair / Author:** `cochem-sdp-manager` (Software Development Project Manager & PMBOK/SWEBOK Architect) [M]  
**Supervising Swarm Controller:** `0rchestrator` (Swarm Workflow Supervisor & Execution Router) [M]  
**Assigned Functional Code Developer:** `@cochem-coder` (Autonomous Iterative Implementation & Feature Building Agent - Read-Only Architectural Review) [M]  
**Designated Execution Agent:** `cochem-tester` (Test-Driven Development & Uncompromised Verification Agent - Primary Responsible `[R]`) [M]  
**Assigned Compliance Auditor:** `cochem-audit` (Method Matrix QA Compliance & Architectural Integrity Auditor) [M]  
**Assigned Red-Team Auditor:** `adversary` (Adversarial Penetration, Fault Injection & Anti-Spoofing Auditor) [M]  
**Governing Authorities:** PMBOK Guide (7th Edition), SWEBOK v3/v4, ISO/IEC/IEEE 29148:2018, Method Matrix v4.1 (§10.1–10.8, §9A.1–9A.5), CoChem Anti-Spoofing Protocol v4 [M]  
**Target Repository:** `CoChem-BASE` ([`CoChem-BASE`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE)) and `CoChem-TOPOS` ([`CoChem-TOPOS`](file:///D:/__CoChem/GitHub-Repo/CoChem-TOPOS)) [M]  
**Target Verification File:** [`tests/base/test_nuclide_resolver_periodic_table.py`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/tests/base/test_nuclide_resolver_periodic_table.py) [M]  
**Target Validation Module:** [`src/cochem_base/physics/nuclide_resolver.py`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/src/cochem_base/physics/nuclide_resolver.py) [M]  
**Lifecycle Status:** `APPROVED_FOR_EXECUTION` [M]  

---

## 1. Executive Summary & Document Control [M]

### 1.1 Mission Charter & Work Order Mandate [M]
Under Article IV of the CoChem Swarm Zero-Trust Charter, Council Emergency Session 010 Resolution (`COCHEM-COUNCIL-RES-010-8D-ZERO-TRUST`), Council Emergency Session 012 Resolution (`COCHEM-COUNCIL-RES-012-8D-ZERO-TRUST`), and Permanent Corrective Action 05 (PCA-05: Strict Role Segregation & Dispatch Gate), the Presiding Chair hereby promulgates **Work Order Specification `COCHEM-SPEC-TASK-1.2.4-WBS-V1`** [M].

This specification governs the physical, algorithmic, and architectural implementation of **Task 1.2.4**:
> **Task 1.2.4: Unit Verification Across IUPAC Periodic Table (Z=1..118)** (Subsystem VR01-SS1 / [`L3_Decomposition_Task_1_VR01.md:L246-L255`](file:///D:/__CoChem/.docs/L3_Decomposition_Task_1_VR01.md#L246-L255) [M]).

The primary objective of Task 1.2.4 is to establish an uncompromised, zero-mock, real-world physical verification test harness across the entire IUPAC Periodic Table of the Elements ($Z=1 \dots 118$) in [`tests/base/test_nuclide_resolver_periodic_table.py`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/tests/base/test_nuclide_resolver_periodic_table.py), validating [`src/cochem_base/physics/nuclide_resolver.py`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/src/cochem_base/physics/nuclide_resolver.py).

In compliance with the Dynamic Mendeleev Mandate, Anti-Spoofing Protocol v4, and Method Matrix v4.1, all atomic mass determinations, isotopic distributions, and covalent radii must be dynamically retrieved from the underlying `mendeleev` SQLite database backend. Task 1.2.4 delivers rigorous verification across six core dimensions:
1. **IUPAC Periodic Table Traversal ($Z=1 \dots 118$):** Systematic verification that all 118 elements resolve strictly positive, finite masses ($m_i > 0.0\,\text{u}$) and positive single-bond covalent radii ($r_{\text{cov}} > 0.0\,\text{\AA}$) [M].
2. **Standard Terrestrial Atomic Weight Parity:** Precision benchmark verification for key stable elements (H, C, N, O, S, Fe, Au, Pb) asserting parity with Commission on Isotopic Abundances and Atomic Weights (CIAAW) standard values within $|\Delta m| < 0.01\,\text{u}$ [M].
3. **Synthetic & Transuranic Fallbacks:** Robust resolution for unstable, radioactive, and synthetic elements lacking terrestrial isotopic compositions (Tc, Pm, Po, At, Og), asserting valid finite mass fallbacks to the most stable isotope (`elem.mass`) [M].
4. **Superheavy Terminal Boundary Limits ($Z=118$ Oganesson):** Physical verification of terminal boundary element Oganesson ($^{294}\text{Og}$), confirming resolved mass $294.0 \pm 1.0\,\text{u}$ and positive covalent radius ($r_{\text{cov}} > 0.0\,\text{\AA}$) [M].
5. **Fail-Closed Negative Boundary & Typo Exception Trapping:** Exhaustive verification that malformed chemical symbols, non-elements, invalid casing, and out-of-bounds mass numbers raise typed exceptions (`InvalidNuclideSymbolError`, `IsotopeNotFoundError`) rather than returning default values or corrupting downstream calculations [M].
6. **Concurrent Multi-Threaded Query Resilience:** Empirical stress-testing under an 8-worker thread pool (`concurrent.futures.ThreadPoolExecutor(max_workers=8)`), executing 944 concurrent queries ($118 \times 8$) with zero thread-safety exceptions, zero race conditions, and zero deadlocks [M].

### 1.2 Document Control & Provenance Registry [M]

```
+---------------------------------------------------------------------------------------------------------+
|                                    DOCUMENT CONTROL & SPECIFICATION LEDGER                             |
+--------------------------+------------------------------------------------------------------------------+
| Document Identifier      | COCHEM-SPEC-TASK-1.2.4-WBS-V1 [M]                                            |
| Governing Work Package   | Subsystem VR01-SS1 / Task 1.2.4 [M]                                          |
| Standards Compliance     | PMBOK Guide 7th Ed., SWEBOK v3/v4, ISO/IEC/IEEE 29148:2018, Method Matrix v4 |
| Classification           | Zero-Trust Engineering Work Order / Binding Assignment Spec [M]              |
| Predecessor Deliverables | Task 1.2.2 (Dynamic Mendeleev Binding - Ratified Session 064) [M]            |
|                          | Task 1.2.3 (AST Linter & Sentinel - Ratified Session 065) [M]               |
| Successor Deliverables   | Task 1.3.1 (Mass-Weighted Center-of-Mass Vector Accumulator) [M]             |
| Target Test File         | tests/base/test_nuclide_resolver_periodic_table.py [M]                       |
| Target Validation Module | src/cochem_base/physics/nuclide_resolver.py [M]                              |
| Primary Disk Target      | D:/__CoChem/.docs/task_1_2_4_assignment_spec.md [M]                          |
| Mirror Disk Targets      | D:/__CoChem/__agentic/dropzones/inbox_srs/task_1_2_4_assignment_spec.md [M]    |
|                          | D:/__CoChem/GitHub-Repo/CoChem-BASE/.docs/task_1_2_4_assignment_spec.md [M]  |
|                          | D:/__CoChem/GitHub-Repo/CoChem-TOPOS/.docs/task_1_2_4_assignment_spec.md [M] |
| Minimum Coverage Bound   | 100% test passing rate across Z=1..118; 0 mock objects; 0 stubs [M]         |
+--------------------------+------------------------------------------------------------------------------+
```

### 1.3 Strict Role Separation Mandate (Ruling D1-01 / PCA-01 Enforcement) [M]
In strict obedience to Council Disciplinary Ruling D1-01, Council Emergency Sessions 006–012, and PMBOK/SWEBOK governance principles:
- The Presiding PMBOK Chair (`cochem-sdp-manager`) is **STRICTLY PROHIBITED FROM AUTHORING OR MODIFYING FUNCTIONAL OR PRODUCTION SOURCE CODE** in `src/`, `scripts/`, or `Libraries/` [M].
- Functional implementation is authored by `@cochem-coder` [M].
- **Test authoring, test execution, and physical verification for Task 1.2.4 are exclusively, strictly, and irrevocably assigned to `cochem-tester`** [M].
- Compliance auditing and AST inspections are assigned to `cochem-audit` [M].
- Independent red-team penetration, fault injection, and anti-spoofing verification tasks are assigned to `adversary` [M].
- Swarm supervisory routing and final state ratification are managed by `0rchestrator` [M].

Any tool invocation or dispatch request violating these boundaries invokes the fail-closed abort trigger `[HARD_ABORT: ROLE_MISATTRIBUTION_PROHIBITED]` [M].

---

## 2. RACI Governance & Agent Capability Matrix [M]

### 2.1 Swarm RACI Matrix for Task 1.2.4 Work Packages [M]
The following RACI matrix governs all activities associated with Task 1.2.4:
- **R - Responsible:** The designated agent who performs the work to create the deliverable.
- **A - Accountable:** The agent possessing ultimate authority and veto power over the delivery (Single Accountability Principle).
- **C - Consulted:** Agents possessing technical or scientific domain knowledge providing inputs.
- **I - Informed:** Agents notified of status changes, milestones, and audit receipts.

```
+--------------------------------------------------------------------+-----+-----+-----+-----+-----+-----+
| Work Breakdown Element                                             | SDP | ORC | COD | TST | AUD | ADV |
+--------------------------------------------------------------------+-----+-----+-----+-----+-----+-----+
| 1.2.4-WBS Formulation & Document Control (task_1_2_4_spec.md)      |  R  |  A  |  C  |  I  |  C  |  C  |
| 1.2.4.1 IUPAC Periodic Table Traversal (Z=1 to Z=118)              |  C  |  A  |  C  |  R  |  I  |  I  |
| 1.2.4.2 Standard Terrestrial Atomic Weight Parity (CIAAW Benchmarks|  C  |  A  |  C  |  R  |  I  |  I  |
| 1.2.4.3 Synthetic & Transuranic Fallbacks (Tc, Pm, Po, At, Og)    |  C  |  A  |  C  |  R  |  I  |  I  |
| 1.2.4.4 Superheavy Oganesson Boundary (Z=118 Mass & Radius)        |  C  |  A  |  C  |  R  |  I  |  I  |
| 1.2.4.5 Negative Boundary & Typo Exception Trapping Suite          |  C  |  A  |  C  |  R  |  I  |  I  |
| 1.2.4.6 Concurrent Multi-Threaded Query Resilience (8 Workers)     |  C  |  A  |  C  |  R  |  I  |  I  |
| 1.2.4.7 Dual Asymmetric Audit & Cryptographic Certification        |  I  |  A  |  I  |  I  |  R  |  R  |
| Final Council Ratification & Roll-Call Verification                |  C  |  A  |  I  |  I  |  R  |  R  |
+--------------------------------------------------------------------+-----+-----+-----+-----+-----+-----+
Legend: SDP: cochem-sdp-manager | ORC: 0rchestrator | COD: @cochem-coder | TST: cochem-tester | AUD: cochem-audit | ADV: adversary
```

### 2.2 Agent Capability Matrix (ACM) & Execution Gates [M]

```
+---------------------+-------------------+---------------------+--------------------+---------------------+
| Swarm Persona       | Production Source | Test Harness Trees  | Governance Artifact| Shell / Subprocess  |
|                     | (src/, scripts/)  | (tests/)            | (.docs/, .prompts/)| Execution Rights    |
+---------------------+-------------------+---------------------+--------------------+---------------------+
| cochem-sdp-manager  | FORBIDDEN [M]     | FORBIDDEN [M]       | FULL PERMISSION    | READ_ONLY [M]       |
| 0rchestrator        | READ_ONLY [M]     | READ_ONLY [M]       | FULL PERMISSION    | ROUTER / DISPATCH   |
| @cochem-coder       | FULL PERMISSION   | READ_ONLY (Review)  | READ_ONLY          | PYTEST / LINTER     |
| cochem-tester       | READ_ONLY [M]     | FULL PERMISSION     | READ_ONLY          | PYTEST / BENCHMARK  |
| cochem-audit        | READ_ONLY [M]     | READ_ONLY [M]       | AUDIT CERTS ONLY   | AST_SCAN / READ     |
| adversary           | READ_ONLY [M]     | READ_ONLY [M]       | AUDIT CERTS ONLY   | FAULT_INJECTION     |
| cochem-scribe       | FORBIDDEN [M]     | FORBIDDEN [M]       | USER MANUAL / SRS  | READ_ONLY           |
| cochem-improve      | FORBIDDEN [M]     | FORBIDDEN [M]       | PROFILING LOGS     | READ_ONLY           |
| cochem-debug        | FORBIDDEN [M]     | FORBIDDEN [M]       | DIAGNOSTIC TRACES  | KERNEL / IPC TRACE  |
+---------------------+-------------------+---------------------+--------------------+---------------------+
```

---

## 3. Method Matrix Compliance Invariants & Scientific Directives [M]

All verification logic implemented under Task 1.2.4 must comply strictly with the governing scientific specifications defined in [`Method_Matrix.md`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/Method_Matrix.md) v4.1 and [`L3_Decomposition_Task_1_VR01.md`](file:///D:/__CoChem/.docs/L3_Decomposition_Task_1_VR01.md).

```
                  +----------------------------------------------------------+
                  |               TASK 1.2.4 SCIENTIFIC INVARIANTS           |
                  +----------------------------------------------------------+
                                               |
        +--------------------------------------+--------------------------------------+
        |                                      |                                      |
        v                                      v                                      v
+-----------------------+            +-----------------------+            +-----------------------+
|  IUPAC Traversal      |            |  CIAAW Standard Wts   |            |  Superheavy Boundary  |
|   Z = 1 to 118        |            |   Stable Benchmarks   |            |   Z=118 Oganesson     |
|   m_i > 0.0 u finite  |            |   |dm| < 0.01 u       |            |   294.0 +/- 1.0 u     |
|   r_cov > 0.0 A       |            |   AME2020 High Prec   |            |   r_cov > 0.0 A       |
+-----------------------+            +-----------------------+            +-----------------------+
        |                                      |                                      |
        +--------------------------------------+--------------------------------------+
                                               |
        +--------------------------------------+--------------------------------------+
        |                                                                             |
        v                                                                             v
+-----------------------+                                                   +-----------------------+
|  Fail-Closed Trapping |                                                   |  Thread Concurrency   |
|   InvalidNuclideError |                                                   |   8 Worker Threads    |
|   IsotopeNotFoundError|                                                   |   Zero Deadlocks      |
|   Zero-Default Ban    |                                                   |   Zero Exceptions     |
+-----------------------+                                                   +-----------------------+
```

### 3.1 Dynamic Mendeleev Invariant & Zero-Static-Dictionary Mandate [M]
1. **Dynamic Backend Binding:** All mass queries (`disambiguate_mass`) and covalent radius lookups (`resolve_covalent_radius`) must query the underlying SQLite relational tables of the `mendeleev` package dynamically [M].
2. **Zero Hardcoded Mass Dictionaries:** Test assertions and target modules must not utilize static dictionaries mapping chemical symbols to mass numbers or atomic weights [M].
3. **AST Linter Verification:** The test file `tests/base/test_nuclide_resolver_periodic_table.py` must cleanly pass `ci_tools/mendeleev_ast_linter.py` with zero static dictionary violations [M].

### 3.2 IUPAC Traversal Invariant ($Z=1 \dots 118$) [M]
1. **Complete Periodic Coverage:** Every atomic number $Z \in [1, 118]$ recognized by IUPAC must resolve deterministically [M].
2. **Strict Positivity & Finiteness:**
   $$\forall Z \in \{1, \dots, 118\}: \quad m(Z) > 0.0\,\text{u}, \quad \text{math.isfinite}(m(Z)) = \text{True} \quad [M]$$
3. **Covalent Radius Spatial Metric:**
   $$\forall Z \in \{1, \dots, 118\}: \quad r_{\text{cov}}(Z) > 0.0\,\text{\AA}, \quad r_{\text{cov}}(Z) \ne \text{None} \quad [M]$$

### 3.3 CIAAW Terrestrial Atomic Weight Parity Invariant [M]
For stable benchmark elements where terrestrial isotopic abundances are well-defined by the Commission on Isotopic Abundances and Atomic Weights (CIAAW), the resolved standard atomic weight must match the benchmark within $\pm 0.01\,\text{u}$ [M]:
- Hydrogen ($\text{H}$): $m_{\text{CIAAW}} = 1.008\,\text{u} \implies |m(\text{'H'}) - 1.008| < 0.01\,\text{u}$ [M]
- Carbon ($\text{C}$): $m_{\text{CIAAW}} = 12.011\,\text{u} \implies |m(\text{'C'}) - 12.011| < 0.01\,\text{u}$ [M]
- Nitrogen ($\text{N}$): $m_{\text{CIAAW}} = 14.007\,\text{u} \implies |m(\text{'N'}) - 14.007| < 0.01\,\text{u}$ [M]
- Oxygen ($\text{O}$): $m_{\text{CIAAW}} = 15.999\,\text{u} \implies |m(\text{'O'}) - 15.999| < 0.01\,\text{u}$ [M]
- Sulfur ($\text{S}$): $m_{\text{CIAAW}} = 32.06\,\text{u} \implies |m(\text{'S'}) - 32.06| < 0.01\,\text{u}$ [M]
- Iron ($\text{Fe}$): $m_{\text{CIAAW}} = 55.845\,\text{u} \implies |m(\text{'Fe'}) - 55.845| < 0.01\,\text{u}$ [M]
- Gold ($\text{Au}$): $m_{\text{CIAAW}} = 196.966569\,\text{u} \implies |m(\text{'Au'}) - 196.966569| < 0.01\,\text{u}$ [M]
- Lead ($\text{Pb}$): $m_{\text{CIAAW}} = 207.2\,\text{u} \implies |m(\text{'Pb'}) - 207.2| < 0.01\,\text{u}$ [M]

### 3.4 Synthetic & Transuranic Fallback Mass Invariant [M]
Radioactive elements lacking stable terrestrial isotopic distributions (Technetium $Z=43$, Promethium $Z=61$, Polonium $Z=84$, Astatine $Z=85$, and Oganesson $Z=118$) lack `elem.atomic_weight` [M]. The resolver must transparently fall back to `float(elem.mass)` (the mass number or mass of the most stable or longest-lived isotope) [M]:
$$\forall X \in \{\text{'Tc'}, \text{'Pm'}, \text{'Po'}, \text{'At'}, \text{'Og'}\}: \quad m(X) > 0.0\,\text{u}, \quad \text{math.isfinite}(m(X)) = \text{True} \quad [M]$$

### 3.5 Superheavy Oganesson Terminal Boundary Invariant ($Z=118$) [M]
Oganesson ($^{294}\text{Og}$, $Z=118$) represents the physical terminal boundary of the 7th period of the periodic table [M]:
1. **Nominal Superheavy Mass:**
   $$|m(\text{'Og'}) - 294.0\,\text{u}| \le 1.0\,\text{u} \quad [M]$$
2. **Relativistic Pyykkö Covalent Radius:**
   $$r_{\text{cov}}(\text{'Og'}) > 0.0\,\text{\AA} \quad (r_{\text{cov}} \approx 1.57\,\text{\AA} \text{ derived from relativistic Dirac-Fock DFT}) \quad [M]$$

### 3.6 Fail-Closed Negative Boundary & Typo Exception Trapping Invariant [M]
Robust software engineering (SWEBOK v4 Software Quality) mandates that invalid inputs fail closed immediately without silent data corruption [M]:
1. **Malformed Symbols & Non-Elements:** Input tokens violating regex invariant $R_{\text{nuclide}} = {}^{\wedge}(\backslash d+)?([A-Za-z]+)\$$ or representing non-existent elements (`'Xx'`, `'Food'`, `'123'`, `'C12'`, `''`, `'   '`) must raise `InvalidNuclideSymbolError` (or `InvalidNuclideError`) [M].
2. **Non-Existent Isotope Mass Numbers:** Valid elements paired with out-of-bounds mass numbers (`'50H'`, `'999C'`) must raise `IsotopeNotFoundError` [M].
3. **Physical Zero Mass Boundary:** Explicit non-physical mass number zero (`'0H'`) must raise fail-closed typed error (`InvalidNuclideSymbolError` or `IsotopeNotFoundError`) [M].

### 3.7 Concurrent Multi-Threaded Query Resilience Invariant [M]
High-throughput conformer deduplication and trajectory alignment run parallel worker pools. Task 1.2.4 mandates:
1. **Thread Pool Stress:** Concurrent execution across 8 worker threads (`concurrent.futures.ThreadPoolExecutor(max_workers=8)`) [M].
2. **Query Batch Volume:** A minimum batch of 944 queries ($118 \text{ elements} \times 8 \text{ iterations}$) executed simultaneously [M].
3. **Zero Error Toleration:** Exactly zero uncaught exceptions, zero corrupted return records, and zero thread deadlocks [M].

### 3.8 Method Matrix Scientific Constraint Mapping (§10.1–10.8, §9A.1–9A.5) [M]
Nuclide mass and radius resolution underpin the entire physical engine of CoChem:
- **§10.1 Center of Mass Translation Zeroing:**
  $$\mathbf{R}_{\text{COM}} = \frac{1}{M_{\text{tot}}} \sum_{i=1}^N m_i \mathbf{r}_i, \quad \tilde{\mathbf{r}}_i = \mathbf{r}_i - \mathbf{R}_{\text{COM}}, \quad \left\|\sum_{i=1}^N m_i \tilde{\mathbf{r}}_i\right\|_2 < 10^{-12}\,\text{u}\cdot\text{\AA} \quad [D]$$
  Exact masses resolved by Task 1.2.4 prevent numerical drift in COM translation.
- **§10.2 Mass-Weighted Coordinates:**
  $$\mathbf{w}_i = \sqrt{m_i} \tilde{\mathbf{r}}_i \quad [D]$$
- **§10.3 Mass-Weighted Covariance (Gram) Matrix:**
  $$C = X^T W Y = \sum_{i=1}^N m_i (\mathbf{r}_i^A)(\mathbf{r}_i^B)^T \in \mathbb{R}^{3 \times 3} \quad [D]$$
- **§10.4–10.6 SVD Factorization & SO(3) Proper Rotation Closure:**
  $$C = V \Sigma W_R^T, \quad S = \text{diag}(1, 1, \det(V W_R^T)), \quad U = V S W_R^T, \quad \det(U) = +1.000000000000 \pm 10^{-12} \quad [D]$$
- **§10.7 Eckart Angular Momentum Cross-Product Residual:**
  $$\|\mathbf{L}_{\text{Eckart}}\|_2 = \left\| \sum_{i=1}^N m_i (\mathbf{r}_i^A \times U \mathbf{r}_i^B) \right\|_2 < 10^{-10}\,\text{a.u.} \quad [D]$$
  Eradicates Coriolis vibration-rotation coupling during rotational spectroscopic alignment.
- **§10.8 Rotational Constants ($B_e$ vs $B_0$) & Principal Moments of Inertia:**
  $$I = \sum_{i=1}^N m_i (\|\mathbf{r}_i\|^2 I_3 - \mathbf{r}_i \mathbf{r}_i^T), \quad I_a \le I_b \le I_c, \quad A, B, C = \frac{h}{8\pi^2 c I_{a,b,c}} \quad [M]$$
  Mandatory distinction between equilibrium $B_e$ (minimum of Born–Oppenheimer surface) and ground-state observable $B_0 = B_e + \Delta B_{\text{vib}}$ (§3.0) [M].
- **§9A.1 Recipe R1/R2 Frozen Monomer Protocol (FMP):**
  Freezes monomers to fix $A$, optimizes intermolecular distance $R$ to fix $B$ and $C$ [M].
- **§9A.2 Intermolecular van der Waals Constraints:**
  $$R_{\text{vdw}} \ge 0.85 \times (r_{\text{vdw}, A} + r_{\text{vdw}, B}) \quad [D]$$
  Prevents unphysical nuclear overlap during molecular intake.
- **§9A.3 Pyykkö Relativistic Covalent Radii Network:**
  Dynamically queries $r_{\text{cov}}$ from Pyykkö (2009) tables ($1\,\text{pm} = 0.01\,\text{\AA}$), defining covalent adjacency:
  $$d_{ij} \le 1.28 \times (r_{\text{cov}, i} + r_{\text{cov}, j}) \quad [D]$$
  Forms the topological graph for Weisfeiler-Lehman conformer deduplication (VR01-SS4).
- **§9A.5 Prohibition of Additive Diffuse Corrections and Small-System ONIOM:**
  Additive diffuse corrections degrade energy MAE from 1.52% to 12.74% [M], and ONIOM QM/QM2 partitioning is strictly forbidden for 5–10 atom systems [M].

---

## 4. Microscopic WBS Level 4 Breakdown for Task 1.2.4 [M]

```
1.2.4: Task 1.2.4 - Unit Verification Across IUPAC Periodic Table (Z=1..118)
│
├── 1.2.4.1: IUPAC Periodic Table Traversal (Z=1 to Z=118) (Agent: cochem-tester) [M]
│   ├── [ ] 1.2.4.1.1: Dynamic Periodic Table Iteration Engine [M]
│   │   ├── Precondition: WBS 1.2.2 and WBS 1.2.3 ratified; mendeleev active [M]
│   │   ├── Deliverable: Parameterized or looped pytest test iterating Z=1 to Z=118 via mendeleev.element(z) [M]
│   │   ├── Provenance: [M] (Dynamic IUPAC periodic table Z=1..118)
│   │   └── Acceptance Criteria: Iterates through all 118 elements without missing indices [M]
│   │
│   ├── [ ] 1.2.4.1.2: Positive Finite Mass Assertion [M]
│   │   ├── Precondition: 1.2.4.1.1 active [M]
│   │   ├── Deliverable: Assert disambiguate_mass(symbol) returns positive, finite float for all 118 elements [M]
│   │   ├── Provenance: [M] (Physical mass finiteness invariant)
│   │   └── Acceptance Criteria: math.isfinite(mass) and mass > 0.0 for 118/118 elements [M]
│   │
│   └── [ ] 1.2.4.1.3: Covalent Radius Non-Null & Positivity Assertion [M]
│       ├── Precondition: 1.2.4.1.2 active [M]
│       ├── Deliverable: Assert resolve_covalent_radius(symbol) returns positive float (in Angstroms) for all 118 elements [M]
│       ├── Provenance: [M] (Pyykkö/Cordero covalent radius spatial metric)
│       └── Acceptance Criteria: r_cov is not None and r_cov > 0.0 for 118/118 elements [M]
│
├── 1.2.4.2: Standard Terrestrial Atomic Weight Parity (Agent: cochem-tester) [M]
│   ├── [ ] 1.2.4.2.1: CIAAW Benchmark Stable Element Selection [M]
│   │   ├── Precondition: 1.2.4.1 complete [M]
│   │   ├── Deliverable: Establish reference list of stable benchmark elements: H, C, N, O, S, Fe, Au, Pb [M]
│   │   ├── Provenance: [M] (CIAAW standard terrestrial atomic weights)
│   │   └── Acceptance Criteria: Correct CIAAW target values defined for all 8 benchmark elements [M]
│   │
│   ├── [ ] 1.2.4.2.2: Mass Parity Verification Loop [M]
│   │   ├── Precondition: 1.2.4.2.1 complete [M]
│   │   ├── Deliverable: Query disambiguate_mass for each benchmark element and calculate absolute deviation [M]
│   │   ├── Provenance: [M] (Empirical mass comparison)
│   │   └── Acceptance Criteria: Evaluates abs(resolved_mass - benchmark_mass) for each element [M]
│   │
│   └── [ ] 1.2.4.2.3: Tolerance Gate Enforcement (|Delta m| < 0.01 u) [M]
│       ├── Precondition: 1.2.4.2.2 complete [M]
│       ├── Deliverable: Enforce strict tolerance assertion: abs(resolved - benchmark) < 0.01 u [M]
│       ├── Provenance: [M] (Scientific tolerance gate)
│       └── Acceptance Criteria: 8/8 benchmark elements pass with deviation < 0.01 u [M]
│
├── 1.2.4.3: Synthetic & Transuranic Fallbacks (Agent: cochem-tester) [M]
│   ├── [ ] 1.2.4.3.1: Unstable & Transuranic Element Suite Formulation [M]
│   │   ├── Precondition: 1.2.4.2 complete [M]
│   │   ├── Deliverable: Define test vector of unstable/synthetic elements: Tc (43), Pm (61), Po (84), At (85), Og (118) [M]
│   │   ├── Provenance: [M] (Non-terrestrial isotopic element set)
│   │   └── Acceptance Criteria: Test vector includes light radioactive and heavy transuranics [M]
│   │
│   ├── [ ] 1.2.4.3.2: Fallback Mass Resolution & Type Verification [M]
│   │   ├── Precondition: 1.2.4.3.1 complete [M]
│   │   ├── Deliverable: Query disambiguate_mass for unstable elements and verify fallback to elem.mass [M]
│   │   ├── Provenance: [M] (Mendeleev nominal mass fallback)
│   │   └── Acceptance Criteria: All unstable elements return valid float instances [M]
│   │
│   └── [ ] 1.2.4.3.3: Positivity & Finiteness Assertions [M]
│       ├── Precondition: 1.2.4.3.2 complete [M]
│       ├── Deliverable: Assert fallback masses are positive, finite floats [M]
│       ├── Provenance: [M] (Physical validity check)
│       └── Acceptance Criteria: math.isfinite(mass) and mass > 0.0 for all synthetic test elements [M]
│
├── 1.2.4.4: Superheavy Oganesson Boundary (Z=118) (Agent: cochem-tester) [M]
│   ├── [ ] 1.2.4.4.1: Terminal Element Query Execution [M]
│   │   ├── Precondition: 1.2.4.3 complete [M]
│   │   ├── Deliverable: Query disambiguate_mass('Og') and resolve_covalent_radius('Og') [M]
│   │   ├── Provenance: [M] (Periodic table terminal boundary query)
│   │   └── Acceptance Criteria: Queries complete without raising exceptions [M]
│   │
│   ├── [ ] 1.2.4.4.2: Terminal Mass Invariant Assertion (294.0 +/- 1.0 u) [M]
│   │   ├── Precondition: 1.2.4.4.1 complete [M]
│   │   ├── Deliverable: Assert abs(disambiguate_mass('Og') - 294.0) <= 1.0 u [M]
│   │   ├── Provenance: [M] (AME2020/IUPAC 294Og benchmark)
│   │   └── Acceptance Criteria: Oganesson mass resolves to 294.0 +/- 1.0 u [M]
│   │
│   └── [ ] 1.2.4.4.3: Terminal Covalent Radius Assertion [M]
│       ├── Precondition: 1.2.4.4.2 complete [M]
│       ├── Deliverable: Assert resolve_covalent_radius('Og') is not None and > 0.0 Angstroms [M]
│       ├── Provenance: [M] (Pyykkö relativistic covalent radius for Z=118)
│       └── Acceptance Criteria: Oganesson covalent radius is positive and finite [M]
│
├── 1.2.4.5: Negative Boundary & Typo Exception Trapping Suite (Agent: cochem-tester) [M]
│   ├── [ ] 1.2.4.5.1: Malformed Token & Non-Element Trapping [M]
│   │   ├── Precondition: 1.2.4.4 complete [M]
│   │   ├── Deliverable: Test invalid tokens: 'Xx', 'Food', '123', 'C12', '', '   ' raising InvalidNuclideSymbolError [M]
│   │   ├── Provenance: [M] (Syntax & element existence fail-closed error gate)
│   │   └── Acceptance Criteria: disambiguate_mass and parse_nuclide raise InvalidNuclideSymbolError for all [M]
│   │
│   ├── [ ] 1.2.4.5.2: Out-of-Bounds Isotope Mass Number Trapping [M]
│   │   ├── Precondition: 1.2.4.5.1 complete [M]
│   │   ├── Deliverable: Test out-of-bounds isotopes: '50H', '999C' raising IsotopeNotFoundError [M]
│   │   ├── Provenance: [M] (Isotope table traversal error gate)
│   │   └── Acceptance Criteria: disambiguate_mass raises IsotopeNotFoundError [M]
│   │
│   └── [ ] 1.2.4.5.3: Non-Physical Zero Mass Number Boundary Trapping [M]
│       ├── Precondition: 1.2.4.5.2 complete [M]
│       ├── Deliverable: Test zero mass number '0H' asserting fail-closed exception [M]
│       ├── Provenance: [M] (Physical mass number lower bound A >= 1)
│       └── Acceptance Criteria: '0H' raises InvalidNuclideSymbolError or IsotopeNotFoundError [M]
│
├── 1.2.4.6: Concurrent Multi-Threaded Query Resilience (Agent: cochem-tester) [M]
│   ├── [ ] 1.2.4.6.1: ThreadPoolExecutor Formulation (8 Worker Threads) [M]
│   │   ├── Precondition: 1.2.4.5 complete [M]
│   │   ├── Deliverable: Construct ThreadPoolExecutor(max_workers=8) stress harness [M]
│   │   ├── Provenance: [M] (CPython concurrent.futures threading model)
│   │   └── Acceptance Criteria: Successfully initializes pool with 8 concurrent worker threads [M]
│   │
│   ├── [ ] 1.2.4.6.2: Concurrent Query Batch Scheduling (944 Queries) [M]
│   │   ├── Precondition: 1.2.4.6.1 complete [M]
│   │   ├── Deliverable: Schedule 944 concurrent tasks (118 elements x 8 repeats) querying mass and radius [M]
│   │   ├── Provenance: [M] (High-throughput stress batch)
│   │   └── Acceptance Criteria: All 944 futures scheduled and tracked via as_completed [M]
│   │
│   └── [ ] 1.2.4.6.3: Thread-Safety & Zero-Error Verification [M]
│       ├── Precondition: 1.2.4.6.2 complete [M]
│       ├── Deliverable: Assert query_errors list is empty (len == 0) and all returned values are positive and finite [M]
│       ├── Provenance: [M] (Thread-safety and cache reentrancy invariant)
│       └── Acceptance Criteria: Zero thread exceptions; 100% successful resolution across all threads [M]
│
└── 1.2.4.7: Dual Asymmetric Audit & Cryptographic Certification (Auditors) [M]
    ├── [ ] 1.2.4.7.1: Asymmetric Architectural Compliance Audit (cochem-audit) [M]
    │   ├── Precondition: test_nuclide_resolver_periodic_table.py committed to physical disk [M]
    │   ├── Deliverable: Architectural compliance verification & signoff receipt [M]
    │   ├── Provenance: [M] (.audit/task_1_2_4_audit_receipt.json)
    │   └── Acceptance Criteria: Emits [STATUS: PASS] verifying zero mocks and AST compliance [M]
    │
    └── [ ] 1.2.4.7.2: Adversarial Red-Team Penetration Audit (adversary) [M]
        ├── Precondition: 1.2.4.7.1 complete [M]
        ├── Deliverable: Anti-spoofing verification and tamper-resistance certificate [M]
        ├── Provenance: [M] (Adversarial fault injection audit)
        └── Acceptance Criteria: Confirms zero stubs, zero mocks, and fail-closed error trapping [M]
```

---

## 5. Acceptance Criteria, Target Whitelists, and Anti-Spoofing Invariants [M]

### 5.1 Comprehensive Acceptance Criteria Matrix [M]

```
+-----------+-----------------------------------------------+-------------------------------------------------------------+
| WBS ID    | Verification Activity                         | Mandatory Acceptance Threshold                              |
+-----------+-----------------------------------------------+-------------------------------------------------------------+
| 1.2.4.1   | IUPAC Traversal (Z=1..118)                    | 118/118 elements: m > 0.0 u (finite), r_cov > 0.0 A (finite)|
| 1.2.4.2   | CIAAW Benchmark Parity                        | H, C, N, O, S, Fe, Au, Pb match CIAAW within |dm| < 0.01 u   |
| 1.2.4.3   | Synthetic / Transuranic Fallbacks             | Tc, Pm, Po, At, Og resolve positive finite mass (elem.mass) |
| 1.2.4.4   | Superheavy Boundary (Z=118)                   | Og mass == 294.0 +/- 1.0 u; r_cov > 0.0 A                   |
| 1.2.4.5   | Negative Boundary & Typo Trapping             | 'Xx', 'Food', '123', 'C12', '', ' ' -> InvalidNuclideError |
|           |                                               | '50H', '999C' -> IsotopeNotFoundError                       |
|           |                                               | '0H' -> InvalidNuclideSymbolError / IsotopeNotFoundError    |
| 1.2.4.6   | Multi-Threaded Concurrency (8 Workers)        | 944 concurrent queries: 0 exceptions, 0 deadlocks           |
| 1.2.4.7   | Zero-Mock AST Verification                    | 0 mock objects, 0 stub returns, passes mendeleev_ast_linter |
+-----------+-----------------------------------------------+-------------------------------------------------------------+
```

### 5.2 Target Path Whitelist (PCA-02 Enforcement) [M]
Any tool call attempting to mutate files outside the following whitelist during Task 1.2.4 execution triggers instant fail-closed abort (`[HARD_ABORT: OFF_TARGET_MUTATION_TRAP]`):

```
+---------------------------------------------------------------------------------------------------------+
|                                      TASK 1.2.4 TARGET PATH WHITELIST                                   |
+-------------------------------------------------------------+-------------------------------------------+
| Whitelisted Path                                            | Authorized Action / Role Boundary         |
+-------------------------------------------------------------+-------------------------------------------+
| tests/base/test_nuclide_resolver_periodic_table.py          | Unit Test Authoring & Execution (tester)  |
| GitHub-Repo/CoChem-BASE/tests/base/test_...periodic_table.py| Mirror Unit Test Execution (tester)       |
| GitHub-Repo/CoChem-TOPOS/tests/base/test_...periodic_table.py| Secondary Mirror Unit Test (tester)       |
| .docs/task_1_2_4_assignment_spec.md                         | Specification Artifact (sdp-manager)      |
| GitHub-Repo/CoChem-BASE/.docs/task_1_2_4_assignment_spec.md| Mirror Specification Artifact (sdp-manager)|
| GitHub-Repo/CoChem-TOPOS/.docs/task_1_2_4_assignment_spec.md| Mirror Specification Artifact (sdp-manager)|
| __agentic/dropzones/inbox_srs/task_1_2_4_assignment_spec.md | Dropzone Inbox Mirror (sdp-manager)       |
| .docs/task1_2_4_dispatch_prompt.md                          | Dispatch Prompt Artifact (sdp-manager)    |
| __agentic/dropzones/inbox_srs/task1_2_4_dispatch_prompt.md  | Dropzone Inbox Dispatch Mirror            |
| GitHub-Repo/CoChem-BASE/.docs/task1_2_4_dispatch_prompt.md  | Base Repo Dispatch Mirror                 |
| GitHub-Repo/CoChem-TOPOS/.docs/task1_2_4_dispatch_prompt.md | TOPOS Repo Dispatch Mirror                |
| .audit/task_1_2_4_audit_receipt.json                        | Cryptographic Audit Receipt (auditors)    |
+-------------------------------------------------------------+-------------------------------------------+
```

### 5.3 Anti-Spoofing Protocol v4 Invariants [M]
1. **Absolute Prohibition of Mocks and Stubs:** No `unittest.mock`, `MagicMock`, monkeypatching of Mendeleev models, or synthetic dictionaries permitted [M].
2. **Semantic Spoofing Ban:** No dummy loops, placeholder return values, or fabricated coordinate/mass vectors [M].
3. **Data Laundering Ban:** All physical test inputs must derive from genuine physical constants or standard IUPAC/CIAAW references [M].
4. **Silent Skip Ban:** Core tests must never be bypassed using unconditional `pytest.skip` or broad `except Exception: pass` blocks [M].
5. **Asymmetric Ephemeral Verification Gate:** `cochem-tester` generates test results; independent verification is executed by `cochem-audit` and `adversary` [M].

### 5.4 Minimum Delta Invariants & Test Execution Thresholds (PCA-03 Enforcement) [M]
1. $\text{Lines}(\text{tests/base/test_nuclide_resolver_periodic_table.py}) \ge 160$ lines [M].
2. Physical test execution via `pytest tests/base/test_nuclide_resolver_periodic_table.py` must yield `6 passed` (or more) with 0 failures and 0 errors [M].
3. Execution time across all 118 elements and concurrent stress queries must be $< 5.0\,\text{s}$ under LRU cache acceleration [M].

---

## 6. Council Roll-Call Ledger (PCA-06 Compliance) [M]

In strict obedience to **PCA-06 (Non-Presumptive Ratification Protocol)** and Council sanctions against presumptive consensus, the Council records the formal roll-call vote on Work Order `COCHEM-SPEC-TASK-1.2.4-WBS-V1`. Independent red-team auditors (`adversary`) and quality compliance auditors (`cochem-audit`) are strictly recorded as `PENDING_PHYSICAL_AUDIT` pending post-implementation verification on physical disk [M]:

```
+---------------------+---------------------------------+------------------------+-------------------------------------------------------------+
| Council Member      | Role                            | Roll-Call Vote         | Attestation & Qualification Context                         |
+---------------------+---------------------------------+------------------------+-------------------------------------------------------------+
| 0rchestrator        | Swarm Workflow Supervisor       | AYE (RATIFIED)         | Work order dispatched; state machine transition unlocked.   |
| cochem-sdp-manager  | Presiding Council Chair / SDPM  | AYE (RATIFIED)         | WBS authored; test authoring strictly assigned to tester.   |
| @cochem-coder       | Functional Implementation Agent | AYE (RATIFIED)         | Nuclide resolver validated; ready for tester execution [M]. |
| cochem-tester       | TDD & Verification Specialist   | AYE (ASSIGNED)         | Task 1.2.4 accepted; physical test harness active [M].     |
| cochem-scribe       | Lead Technical Author           | AYE (RATIFIED)         | Specification mirrored across documentation tiers [M].      |
| cochem-improve      | Kaizen & Optimization Lead      | AYE (RATIFIED)         | Concurrency and LRU cache benchmark gates approved [M].     |
| cochem-debug        | Diagnostics & Subprocess Lead   | AYE (RATIFIED)         | Exception trapping and thread resilience approved [M].      |
| cochem-audit        | Architectural Integrity Auditor | PENDING_PHYSICAL_AUDIT | RESERVED pending physical pytest execution & AST audit [M]. |
| adversary           | Independent Red-Team Auditor    | PENDING_PHYSICAL_AUDIT | RESERVED pending zero-mock & anti-spoof audit on disk [M].  |
+---------------------+---------------------------------+------------------------+-------------------------------------------------------------+
```

### 6.1 Council Resolution Decree [M]
1. **Work Order Ratification:** Work Order `COCHEM-SPEC-TASK-1.2.4-WBS-V1` is hereby ratified and declared the authoritative verification standard for Task 1.2.4 [M].
2. **Execution Dispatch:** `cochem-tester` is directed to execute the physical verification test harness in [`tests/base/test_nuclide_resolver_periodic_table.py`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/tests/base/test_nuclide_resolver_periodic_table.py) under the strict path whitelist [M].
3. **Audit Reservation:** Final task closure remains blocked until `cochem-audit` and `adversary` physically audit the resulting test run on physical disk and convert their status from `PENDING_PHYSICAL_AUDIT` to `AYE` [M].
