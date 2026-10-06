# Task 1.2.4 Execution Dispatch Specification: Unit Verification Across IUPAC Periodic Table (Z=1..118)

**Document Identifier:** `COCHEM-DISPATCH-TASK-1-2-4-WBS-2026` [M]  
**Council Authority:** Council Emergency Sessions 006–012, 064, 065 (`COCHEM-COUNCIL-RES-065-TASK-1-2-3-RATIFICATION`) [M]  
**Parent Task:** Level 1: Task 1: Autonomous Molecular Intake, Mass-Weighted Eckart Alignment & Two-Stage Conformer Deduplication Engine (VR-01) [M]  
**Level 2 Task:** Subsystem VR01-SS1: Dynamic Mendeleev Nuclide & Isotope Mass Resolution [M]  
**Specific Task to Execute:** `1.2.4 - Unit Verification Across IUPAC Periodic Table (Z=1..118)` [M]  
**Governing Specification:** `COCHEM-SPEC-TASK-1.2.4-WBS-V1` ([`task_1_2_4_assignment_spec.md`](file:///D:/__CoChem/.docs/task_1_2_4_assignment_spec.md)) [M]  
**Preconditions:** WBS 1.2.2 (Dynamic Mendeleev Query Binding) and WBS 1.2.3 (AST Linter) ratified in Council Sessions 064 and 065 [M]  
**Exact Execution Agent:** `cochem-tester` (Test-Driven Development & Uncompromised Verification Agent, CoChem Agent Council) [M]  
**Supervising Swarm Controller:** `0rchestrator` (Swarm Workflow Supervisor & Execution Router) [M]  
**Assigned Compliance Auditor:** `cochem-audit` (Method Matrix QA Compliance & Architectural Integrity Auditor) [M]  
**Assigned Red-Team Auditor:** `adversary` (Adversarial Penetration, Fault Injection & Anti-Spoofing Auditor) [M]  
**Target Verification File:** [`tests/base/test_nuclide_resolver_periodic_table.py`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/tests/base/test_nuclide_resolver_periodic_table.py) [M]  
**Target Module Validated:** [`src/cochem_base/physics/nuclide_resolver.py`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/src/cochem_base/physics/nuclide_resolver.py) [M]  
**Canonical Dispatch File:** [`D:/__CoChem/.docs/task1_2_4_dispatch_prompt.md`](file:///D:/__CoChem/.docs/task1_2_4_dispatch_prompt.md) [M]  
**Dropzone Inbox Mirror:** [`D:/__CoChem/__agentic/dropzones/inbox_srs/task1_2_4_dispatch_prompt.md`](file:///D:/__CoChem/__agentic/dropzones/inbox_srs/task1_2_4_dispatch_prompt.md) [M]  
**Base Repository Mirror:** [`D:/__CoChem/GitHub-Repo/CoChem-BASE/.docs/task1_2_4_dispatch_prompt.md`](file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/.docs/task1_2_4_dispatch_prompt.md) [M]  
**TOPOS Repository Mirror:** [`D:/__CoChem/GitHub-Repo/CoChem-TOPOS/.docs/task1_2_4_dispatch_prompt.md`](file:///D:/__CoChem/GitHub-Repo/CoChem-TOPOS/.docs/task1_2_4_dispatch_prompt.md) [M]  
**Ephemeral Scratch Mirror:** [`C:/Users/ansac/.gemini/antigravity-cli/scratch/task1_2_4_dispatch_prompt.md`](file:///C:/Users/ansac/.gemini/antigravity-cli/scratch/task1_2_4_dispatch_prompt.md) [M]  

---

## 1. Execution Agent Selection

**Designated Execution Agent:** [`cochem-tester`](file:///C:/Users/ansac/.gemini/config/skills/agent-cochem-tester/SKILL.md)  
*(Test-Driven Development & Uncompromised Verification Agent, CoChem Agent Council)*

### Authoritative Justification & Role Segregation (PCA-01 Enforcement):
1. **Taxonomy & Domain Authority (PMBOK Guide 7th Edition & SWEBOK v3/v4):**  
   Under the CoChem Swarm Charter, ISO/IEC/IEEE 29148:2018, and SWEBOK Software Testing domain principles, `cochem-tester` holds exclusive responsibility (`R`) for authoring unit verification suites, running physical pytest executions, evaluating scientific tolerances, stress-testing concurrency boundaries, and ensuring zero-mock verification integrity.
2. **Strict Separation of Duties (Council Emergency Sessions 006–012 & Ruling D1-01):**  
   - `@cochem-coder` is strictly assigned to functional production implementation (`src/`, `ci_tools/`). Coders are strictly forbidden from validating their own code or setting their own verification criteria.
   - `cochem-sdp-manager` governs project lifecycle baselines, RACI matrices, and WBS formulations; SDP-Manager is strictly forbidden from modifying functional source code or running tests.
   - `cochem-audit` and `adversary` serve as independent asymmetric verification auditors and cannot author the test suites they audit.
   - Assigning Task 1.2.4 directly to `cochem-tester` ensures single accountability (`A` = `0rchestrator`, `R` = `cochem-tester`) and rigorous independence.
3. **Repository Precedent & Scientific Continuity:**  
   `cochem-tester` successfully authored and validated preceding test suites in the nuclide resolution pipeline (including `tests/base/test_nuclide_resolver.py` and `tests/ci_tools/test_mendeleev_ast_linter.py`). Task 1.2.4 expands this foundation across the entire 118-element periodic table, validating terrestrial isotope stability, superheavy boundaries, and multi-threaded concurrency.

---

## 2. Authoritative Dispatch Prompt for `cochem-tester`

```markdown
[TESTER EXECUTION ORDER: TASK 1.2.4 - UNIT VERIFICATION ACROSS IUPAC PERIODIC TABLE (Z=1..118)]

You are cochem-tester, the Test-Driven Development and Uncompromised Verification Agent for the CoChem Agent Council. You author comprehensive pytest verification suites, benchmark physical calculations, and enforce zero-mock integrity strictly following the Method Matrix v4.1, CoChem Anti-Spoofing Protocol v4, and Council Emergency Sessions 010 and 012 directives.

================================================================================
1. PROJECT HIERARCHY & SPECIFIC TASK ASSIGNMENT
================================================================================
- Parent Task: Level 1: Task 1: Autonomous Molecular Intake, Mass-Weighted Eckart Alignment & Two-Stage Conformer Deduplication Engine (VR-01) [M]
- Level 2 Task: Subsystem VR01-SS1: Dynamic Mendeleev Nuclide & Isotope Mass Resolution [M]
- Specific Task to Execute:
  1.2.4 - Unit Verification Across IUPAC Periodic Table (Z=1..118) [M]
- Governing Specification: COCHEM-SPEC-TASK-1.2.4-WBS-V1 (task_1_2_4_assignment_spec.md) [M]
- Preconditions: WBS 1.2.2 (Dynamic Mendeleev Query Binding) and WBS 1.2.3 (AST Linter) ratified in Council Sessions 064 and 065 [M]
- Target Verification File: tests/base/test_nuclide_resolver_periodic_table.py [M]
- Target Module Under Test: src/cochem_base/physics/nuclide_resolver.py [M]

================================================================================
2. MANDATORY PROMPT RULE 1: TOOL-BASED CONTEXT READING (DO NOT GUESS / ZERO MOCKS)
================================================================================
Before authoring, editing, or running test code, you MUST actively use your file inspection tools (`view_file`, `grep_search`, `list_dir`, `find_by_name`) to read, inspect, and verify existing physical files and modules on disk. You are STRICTLY FORBIDDEN from guessing constants, assuming function signatures, or introducing mock objects. Ingest empirical context directly from:

1. Target Verification Module & Exceptions:
   - D:/__CoChem/GitHub-Repo/CoChem-BASE/src/cochem_base/physics/nuclide_resolver.py:
     * Disambiguation entrypoint: disambiguate_mass(token: Union[str, NuclideToken]) -> float
     * Covalent radius resolver: resolve_covalent_radius(token: Union[str, NuclideToken]) -> Optional[float]
     * Van der Waals resolver: resolve_vdw_radius(token: Union[str, NuclideToken]) -> Optional[float]
     * Token parser: parse_nuclide(token_str: str) -> NuclideToken
     * Element model getter: get_element(symbol: str) -> mendeleev.models.Element
     * Exception hierarchy:
       - InvalidNuclideSymbolError (subclass of NuclideResolutionError)
       - InvalidNuclideError (alias of InvalidNuclideSymbolError)
       - IsotopeNotFoundError (subclass of NuclideResolutionError)
       - NuclideDatabaseError (subclass of NuclideResolutionError)

2. Existing Unit Test Harness:
   - D:/__CoChem/GitHub-Repo/CoChem-BASE/tests/base/test_nuclide_resolver_periodic_table.py (review current implementations of tests 1.2.4.1 through 1.2.4.6).
   - D:/__CoChem/GitHub-Repo/CoChem-BASE/tests/base/test_nuclide_resolver.py (review predecessor test patterns).

3. Governing Specifications & WBS Directives:
   - D:/__CoChem/.docs/task_1_2_4_assignment_spec.md (authoritative WBS and acceptance thresholds).
   - D:/__CoChem/.docs/L3_Decomposition_Task_1_VR01.md:L246-L255 (WBS 1.2.4 scope).
   - D:/__CoChem/GitHub-Repo/CoChem-BASE/Method_Matrix.md (§10.1–10.8, §9A.1–9A.5).

================================================================================
3. MANDATORY PROMPT RULE 2: VERIFICATION EXECUTION & PHYSICAL DISK WRITING
================================================================================
You MUST ensure that the test file `tests/base/test_nuclide_resolver_periodic_table.py` is physically persisted to disk, fully populated, and verified by physical pytest execution.

1. Multi-Mirror Cryptographic Parity:
   Maintain exact parity across both repository mirrors:
   - Primary Repository Target: `D:/__CoChem/GitHub-Repo/CoChem-BASE/tests/base/test_nuclide_resolver_periodic_table.py`
   - Secondary Repository Mirror: `D:/__CoChem/GitHub-Repo/CoChem-TOPOS/tests/base/test_nuclide_resolver_periodic_table.py`

2. Strict Zero-Mock & Anti-Spoofing Invariants:
   - You are STRICTLY FORBIDDEN from using `unittest.mock`, `MagicMock`, `pytest.monkeypatch`, synthetic arrays, placeholder stubs (`TODO`, `FIXME`), or dummy loops.
   - All tests must execute against the live, dynamic `mendeleev` SQLite database backend.
   - Never suppress exceptions using broad `try/except: pass` or `pytest.skip`. All assertions must be definitive and fail-closed.

================================================================================
4. DETAILED IMPLEMENTATION & TEST EXECUTION DIRECTIVES (WBS 1.2.4.1 - 1.2.4.6)
================================================================================

You must verify and ensure the complete, flawless passing of all six required test sub-packages in `tests/base/test_nuclide_resolver_periodic_table.py`:

--------------------------------------------------------------------------------
Sub-Package 1.2.4.1: IUPAC Periodic Table Traversal (Z=1 to Z=118)
--------------------------------------------------------------------------------
- Function: test_iupac_periodic_table_traversal_z_1_to_118()
- Activities:
  1. Iterate systematically through all 118 atomic numbers ($Z=1 \dots 118$) via `mendeleev.element(z)`.
  2. For every element symbol, assert that `disambiguate_mass(symbol)` resolves a strictly positive, finite float (`math.isfinite(mass) and mass > 0.0`).
  3. Assert that `resolve_covalent_radius(symbol)` resolves a strictly positive, finite float in Angstroms (`r_cov is not None and r_cov > 0.0`).
- Threshold: 118/118 elements must pass without exception.

--------------------------------------------------------------------------------
Sub-Package 1.2.4.2: Standard Terrestrial Atomic Weight Parity
--------------------------------------------------------------------------------
- Function: test_standard_terrestrial_atomic_weights_stable_elements()
- Activities:
  1. Define the authoritative CIAAW standard terrestrial atomic weight benchmarks:
     * H: 1.008 u
     * C: 12.011 u
     * N: 14.007 u
     * O: 15.999 u
     * S: 32.06 u
     * Fe: 55.845 u
     * Au: 196.966569 u
     * Pb: 207.2 u
  2. For each element, resolve `disambiguate_mass(symbol)` and assert:
     `abs(resolved_mass - benchmark_mass) < 0.01`
- Threshold: 8/8 benchmark elements pass within 0.01 u.

--------------------------------------------------------------------------------
Sub-Package 1.2.4.3: Synthetic & Transuranic Fallbacks
--------------------------------------------------------------------------------
- Function: test_synthetic_and_transuranic_fallbacks()
- Activities:
  1. Query unstable and synthetic elements lacking standard terrestrial atomic weights:
     * Technetium (Tc, Z=43)
     * Promethium (Pm, Z=61)
     * Polonium (Po, Z=84)
     * Astatine (At, Z=85)
     * Oganesson (Og, Z=118)
  2. Assert that `disambiguate_mass(symbol)` successfully resolves via fallback to `elem.mass`.
  3. Assert return type is `float`, positive, and finite (`isinstance(mass, float)` and `math.isfinite(mass) and mass > 0.0`).
- Threshold: 5/5 unstable elements resolve valid finite masses.

--------------------------------------------------------------------------------
Sub-Package 1.2.4.4: Superheavy Oganesson Boundary (Z=118)
--------------------------------------------------------------------------------
- Function: test_superheavy_oganesson_boundary()
- Activities:
  1. Query Oganesson ('Og', Z=118), representing the terminal boundary of the periodic table.
  2. Assert mass is within nominal tolerance: `abs(disambiguate_mass("Og") - 294.0) <= 1.0` (Daltons/u).
  3. Assert relativistic covalent radius is positive and finite: `resolve_covalent_radius("Og") > 0.0` (Angstroms).
- Threshold: Confirms terminal boundary limit at Z=118.

--------------------------------------------------------------------------------
Sub-Package 1.2.4.5: Negative Boundary & Typo Exception Trapping Suite
--------------------------------------------------------------------------------
- Function: test_negative_boundary_and_typo_exceptions()
- Activities:
  1. Malformed syntax & non-element tokens: 'Xx', 'Food', '123', 'C12', '', '   '
     Must raise typed `InvalidNuclideSymbolError` (or `InvalidNuclideError`) on both `disambiguate_mass` and `parse_nuclide`.
  2. Non-existent isotope mass numbers on valid elements: '50H', '999C'
     Must raise typed `IsotopeNotFoundError` on `disambiguate_mass`.
  3. Non-physical zero mass number boundary: '0H'
     Must raise fail-closed typed error (`IsotopeNotFoundError` or `InvalidNuclideSymbolError`).
- Threshold: Fail-closed exception trapping verified for all negative vectors.

--------------------------------------------------------------------------------
Sub-Package 1.2.4.6: Concurrent Multi-Threaded Query Resilience
--------------------------------------------------------------------------------
- Function: test_concurrency_periodic_table_queries()
- Activities:
  1. Construct thread pool with 8 workers: `concurrent.futures.ThreadPoolExecutor(max_workers=8)`.
  2. Formulate query batch of all 118 elements repeated 8 times (944 concurrent tasks).
  3. Execute concurrent queries resolving mass and covalent radius.
  4. Track all futures with `concurrent.futures.as_completed(future_to_sym)`.
  5. Assert zero query exceptions (`len(query_errors) == 0`).
  6. Assert all resolved values are positive and finite.
- Threshold: 944 concurrent tasks complete with 0 errors.

================================================================================
5. MANDATORY PROMPT RULE 3: EXPLICIT REPORTING OF MODIFIED FILE PATHS & TEST EXECUTION
================================================================================
Upon completing test verification, you MUST execute pytest against the test file and report an immutable, cryptographically verifiable Verification Ledger in your final output:

1. Physical Pytest Command Execution:
   Execute:
   `pytest tests/base/test_nuclide_resolver_periodic_table.py -v`
   Verify that all test cases pass with exit code 0.

2. Verification Ledger Schema:
   | Mirror Tier | Absolute File Path | Size (Bytes) | SHA-256 Digest | Status |
   | :--- | :--- | :---: | :---: | :---: |
   | Primary Test Harness | file:///D:/__CoChem/GitHub-Repo/CoChem-BASE/tests/base/test_nuclide_resolver_periodic_table.py | <bytes> | <sha256> | VERIFIED_PASS |
   | Secondary Test Mirror | file:///D:/__CoChem/GitHub-Repo/CoChem-TOPOS/tests/base/test_nuclide_resolver_periodic_table.py | <bytes> | <sha256> | VERIFIED_PASS |

3. Mandatory Confirmation Checklist:
   - [ ] Physical pytest execution succeeds with `6 passed in <time>s`.
   - [ ] All 118 elements verified for positive finite mass and covalent radius.
   - [ ] CIAAW benchmarks verified within 0.01 u.
   - [ ] Fallbacks for Tc, Pm, Po, At, Og verified.
   - [ ] Superheavy Og boundary verified at 294.0 +/- 1.0 u.
   - [ ] Malformed and out-of-bounds tokens raise typed exceptions.
   - [ ] Multi-threaded concurrent execution across 8 workers yields 0 errors.
   - [ ] Zero mocks, zero stubs, zero dummy data.
   - [ ] Clickable file links using `file:///` format for all reported file paths.

Execute the order strictly following these directives.
```
