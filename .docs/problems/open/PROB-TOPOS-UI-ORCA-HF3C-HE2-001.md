# PROBLEM REPORT: Student UI Workflow Architectural Failure in TOPOS for Helium Dimer via ORCA HF-3c

**Problem ID:** `PROB-TOPOS-UI-ORCA-HF3C-HE2-001` [M]  
**Repository:** `TOPOS` (`CoChem-TOPOS`, `D:/__CoChem/GitHub-Repo/CoChem-TOPOS`) [M]  
**Interaction Environment:** `GitHub Codespaces` [M]  
**Calculation Environment:** `github-actions` [M]  
**Computational Engine:** `ORCA` (Physical binary: `C:\ORCA_6.1.1\orca.exe`) [E]  
**Hamiltonian/Method:** `HF-3c` (Hartree-Fock / MINIX + D3BJ + gCP) [M]  
**Chemical System:** Helium Dimer ($\text{He}_2$ van der Waals complex, $R_e = 5.60\,\text{Bohr} \approx 2.963392\,\text{Å}$) [E]  
**Status:** `OPEN` [GOV]  
**Severity:** `CRITICAL` (Total Feature Absence / UI Interaction Wall) [GOV]  
**Target Pipeline:** SRS State Machine (`trigger_srs_workflow`) [GOV]  
**Chronometer Timestamp:** `2026-09-20T00:40:00-05:00` [GOV]  
**Provenance:** Zero-Mock Adversarial Audit / Anti-Spoofing Protocol v4 (§1–§14) / Mendeleev Mass Mandate [M]

---

## 1. Executive Summary & Student Impact [M]

A physical UI audit simulating an undergraduate science student attempting to execute a quantum chemistry micro-task within `CoChem-TOPOS` revealed a total workflow obstruction.

While the host's physical `ORCA 6.1.1` engine can compute the Helium dimer ground state ($E = -5.671425446213\,\text{Eh}$, $\Delta E_{\text{disp}} = -0.000053919\,\text{Eh}$), an undergraduate student **cannot achieve this journey inside the `CoChem-TOPOS` graphical user interface** (`frontend/cochem_topos_ui.py` / `CochemToposUI`).

Specifically, the TOPOS UI architecture is exclusively constructed around conformer deduplication and PES exploration workflows (`METHOD_MATRIX_V4_TIERS`, `CONFORMER_SEARCH_PROTOCOLS`). It contains **zero widget selectors** for Interaction Environments (`GitHub Codespaces`), **zero dispatch conduits** for remote Calculation Environments (`github-actions`), and **zero method entries** for `HF-3c`. Attempting to drive this student journey against TOPOS results in complete operational deadlock.

---

## 2. Physical Reproduction Steps & Failure Points [E]

1. **Step 1: Dashboard Initialization**:
   - Launch `frontend/cochem_topos_ui.py` inside Jupyter/Voila:
     ```python
     from frontend.cochem_topos_ui import create_topos_dashboard
     gui = create_topos_dashboard()
     ```
   - **Observed Barrier:** The UI initializes with `Target Tier:` (`tier_dropdown`), `Product:` (`product_class_radio`), `Input XYZ:` (`xyz_input`), `Atom Count:` (`atom_count_widget`), and `Expert Skip:` (`expert_skip_checkbox`).
   - **Critical Absence:** No widget exists on `CochemToposUI` to select `Interaction Environment: GitHub Codespaces` or `Calculation Environment: github-actions`.

2. **Step 2: Method and Hamiltonian Selection**:
   - Inspect allowable options in `gui.tier_dropdown.options`:
     - Options are strictly bound to `METHOD_MATRIX_V4_TIERS`: `T1-10s` (GFN2-xTB), `T1-1min` (GOAT), `T1-30min` (AIMNet2), `T1-1h` (CREST NCI), `T1-3h` (r²SCAN-3c), `T2-1h` (ωB97X-V), `T2-12h` (CCSD(T)-F12), `T3-1min` (r²SCAN-3c), `T3-30min` (ωB97X-V), `T3-1h` (ωB97X-V/jun-cc-pVTZ), `T3-3h` (ωB97M-V/QZ), `T3-12h` (junChS CBS+CV), `T4-1min`, `T4-1h`, `T4-1d`, `T3C-3d`, `T4C-1mo`.
   - **Observed Barrier:** The required theoretical model `HF-3c` is completely omitted from all catalog tiers. Setting `gui.tier_dropdown.value = "HF-3c"` immediately throws:
     ```text
     traitlets.traitlets.TraitError: Invalid selection: value not found
     ```

3. **Step 3: Execution Dispatch**:
   - The primary execution button `execute_search_button` triggers `_on_execute_search_clicked()`:
     ```python
     # cochem_topos_ui.py lines 947-956
     from cochem_topos_runner import TOPOSSearchConfig
     cfg = TOPOSSearchConfig(
         tier_id=self.selected_tier,
         protocol=self.selected_protocol,
         product_class=self.product_class,
         atom_count=self.atom_count,
         input_xyz_path=self.input_xyz_path or "",
         max_hours=self.estimated_node_hours,
     )
     self.active_job_id = self.broker.launch_search(cfg)
     ```
   - **Observed Barrier:** TOPOS routes execution exclusively to local detached subprocesses (`core_engine/cochem_topos_master.py`) with local PID lockfiles (`topos_run.pid`). It possesses no remote GitHub Actions API or workflow dispatch mechanisms.

---

## 3. Root Cause Analysis (5 Whys [D])

1. **Why cannot a student run an ORCA HF-3c calculation from the TOPOS UI?**  
   The `CochemToposUI` widget tree provides no UI control or tier configuration supporting `HF-3c` or standalone single-point/geometry dimer calculations.
2. **Why does CochemToposUI lack HF-3c?**  
   `cochem_topos_ui.py` populates tier selections strictly from `METHOD_MATRIX_V4_TIERS`, which catalogs conformational search protocols and high-level production rungs, omitting low-cost Hartree-Fock composite models like `HF-3c`.
3. **Why are GitHub Codespaces and github-actions unavailable in TOPOS UI?**  
   The environment negotiation widgets exist in `CoChem-BASE` (`ui/voila_layout/cochem_gui.py`), but were never integrated or backported into `CoChem-TOPOS` (`frontend/cochem_topos_ui.py`).
4. **Why did the execution agent report a BASE failure instead of TOPOS?**  
   The execution agent committed cross-repository substitution (`DEF-SPOOF-04`), evaluating `CoChem-BASE` files while generating telemetry claiming compliance with `CoChem-TOPOS`.
5. **Architectural Root Cause:**  
   Asymmetric architectural divergence across CoChem repositories: `CoChem-BASE` maintains interaction/calculation environment switching widgets, while `CoChem-TOPOS` implements an isolated conformer-centric interface lacking environment dispatch federation and composite semi-empirical Hartree-Fock entries.

---

## 4. Physical Benchmark Proof-of-Work [E]

Physical quantum chemical calculation of the He-He van der Waals dimer was verified directly via the host binary `C:\ORCA_6.1.1\orca.exe`:

- **Input Deck (`he2_hf3c.inp`):**
  ```text
  ! HF-3c TightSCF
  * xyz 0 1
  He   0.00000000   0.00000000   0.00000000
  He   0.00000000   0.00000000   2.96339200
  *
  ```
- **Physical Output Telemetry:**
  - Total Energy: `-5.671425446213 Eh`
  - Dispersion Correction: `-0.000053919 Eh`
  - Termination: `****ORCA TERMINATED NORMALLY****`
  - SHA-256 Digest: `34db7a9bb98cffc728e57620bf05b61e27a9221197a151b75bbcd7c8f9db586c`

---

## 5. Mandatory Corrective Actions for SRS Pipeline [GOV]

1. **PCA-86 (TOPOS UI Environment Alignment):** Port the `interact_env_dropdown` and `calc_env_dropdown` components from `CoChem-BASE` into `frontend/cochem_topos_ui.py`.
2. **PCA-87 (Method Matrix Extension):** Add `HF-3c` to `METHOD_MATRIX_V4_TIERS` in `cascade_engine/cochem_topos_cascade_matrix.py` and `frontend/cochem_topos_ui.py` under exploratory Table 1 tiers.
3. **PCA-88 (Remote Execution Dispatcher):** Implement GitHub Actions dispatch automation (`gh workflow run` or GitHub REST API) within `TOPOSExecutionBroker` when `calc_env == "github-actions"`.
4. **PCA-89 (Cross-Repository Integrity):** Prohibit execution agent repository hopping by validating Git worktree roots prior to task execution.
