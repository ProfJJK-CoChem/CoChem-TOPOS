# PROBLEM REPORT: Physical UI Execution Stoppage for He-He GFN2-xTB Micro-Task in CoChem-TOPOS

**Problem ID:** `PROB-TOPOS-UI-XTB-HE2-001`  
**Repository:** `TOPOS` (`CoChem-TOPOS`)  
**Target Environment:** GitHub Codespaces (Interaction) / GitHub Actions (Calculation)  
**Computational Engine:** `xTB`  
**Hamiltonian/Method:** `GFN2-xTB`  
**Chemical System:** Helium Dimer ($He_2$, van der Waals complex, $R_e \approx 2.963392\ \text{Å}$ / 5.6 Bohr) [E]  
**Dynamic Mass Provenance:** `mendeleev.element('He').mass = 4.002602` Da, `atomic_number = 2` [M]  
**Status:** `OPEN`  
**Severity:** `CRITICAL` (Student Workflow Stoppage / Quantum Engine Crash / Environment Routing Deficit)  
**Target Pipeline:** SRS Auto-Heal & Coding Workflow (`trigger_srs_workflow`)  
**Created At:** 2026-09-20T01:08:02-05:00  
**Governing Charters:** Anti-Spoofing Protocol v4 (§1–§14), Method Matrix v4, Mendeleev Dynamic Mass Mandate  
**Physical Test Suite Reference:** `tests/test_topos_gui_xtb_gfn2_student_journey.py` (4/4 PASSED in 4.10s)  

---

## 1. Description of Failure

An authentic UI execution sweep was evaluated against the `CoChem-TOPOS` repository recreating an undergraduate student executing standardized interaction commands to run a conformational screening calculation on the Helium dimer ($He_2$) van der Waals complex under **GitHub Codespaces** (Interaction) and **github-actions** (Calculation) using **xTB (GFN2-xTB)**.

The student journey is completely blocked from completing the workflow due to four architectural, interface, and execution defects:

1. **Defect 1 (UI Environment & Engine Control Omission in `frontend/cochem_topos_ui.py`):**  
   The interactive dashboard (`CochemToposUI`) in `cochem_topos_master.ipynb` lacks dropdown controls for `Interaction Environment` (e.g. `GitHub Codespaces`) and `Calculation Environment` (e.g. `github-actions`). Furthermore, `CochemToposUI` lacks decoupled dropdown widgets for `Engine` (`xTB`) and `Method` (`GFN2-xTB`), providing only a monolithic `Target Tier` dropdown (`T1-10s`, `T1-1min`, `T3-3h`). The student cannot configure or assert the requested execution environment.

2. **Defect 2 (Silent Coordinate Fallback on Relative Paths in `cochem_topos_runner.py`):**  
   In `cochem_topos_runner.py` (lines 120–129), `worker_script` executes inside `job_scratch` (`scratch/topos_job_<uuid>`). When a relative path (`he_he_dimer.xyz`) is passed, `pathlib.Path(input_xyz).is_file()` evaluates to `False` from the worker's working directory. The script silently falls back to `mol_map.get(atom_cnt, 'C2H4')`, where `atom_cnt = 2` generates hydrogen gas ($H_2$) via `ase.build.molecule('H2')`. This silently substitutes $H_2$ for $He_2$, representing an impermissible coordinate substitution hazard.

3. **Defect 3 (Incompatible Calculator Crash on $He_2$ in `cochem_topos_runner.py`):**  
   When an absolute path is provided to `he_he_dimer.xyz` so authentic Helium coordinates are parsed, the background worker executes `atoms.calc = EMT()`. Effective Medium Theory (`EMT`) is parameterized exclusively for transition metals (Al, Cu, Ag, Au, Ni, Pd, Pt) and lacks potential parameters for Helium. The worker process crashes immediately with:
   ```
   NotImplementedError: No EMT-potential for He
   ```
   The process terminates with non-zero exit code `1`, leaving the telemetry state in `FAILED`.

4. **Defect 4 (Missing xTB Binary & Lack of Remote Dispatch Bridge to GitHub Actions):**  
   The calculation engine requested is `xTB` with `GFN2-xTB`. No `xtb` binary is present on the host system PATH, and neither `frontend/cochem_topos_ui.py` nor `cochem_topos_runner.py` contains remote workflow dispatch logic to offload jobs to GitHub Actions runners. All calculations are launched strictly as local OS subprocesses.

---

## 2. Root Cause Analysis (Quad-Vector 5 Whys [D])

### Vector 1: Missing Environment & Engine UI Controls
1. **Why could the student not select GitHub Codespaces or github-actions?**  
   `CochemToposUI` lacks `interact_env_dropdown` and `calc_env_dropdown` widgets.
2. **Why are environment widgets missing?**  
   The UI dashboard was authored with only a monolithic `tier_dropdown` mapped to `METHOD_MATRIX_V4_TIERS`.
3. **Why are decoupled Engine and Method selectors missing?**  
   Engine and method logic were hardcoded inside Method Matrix tier definitions rather than exposed to student selection.
4. **Why was this not caught?**  
   Prior UI checks in `tests/test_cochem_topos_ui.py` only asserted tier dictionary completeness without verifying environment switching.
5. **Root Cause 1:** Absence of 6-Tier Environment Matrix and decoupled quantum engine selection widgets in the presentation tier.

### Vector 2: Silent Relative Path Coordinate Fallback
1. **Why did the conformer search output $H_2$ coordinates instead of $He_2$?**  
   `worker_script` executed `mol_map.get(2, 'C2H4') = 'H2'`.
2. **Why did it execute the fallback map?**  
   `pathlib.Path(input_xyz).is_file()` returned `False`.
3. **Why did `is_file()` return `False`?**  
   The worker subprocess was launched with `cwd=job_scratch`, but `input_xyz_path` was a relative path from the repository root.
4. **Why was `input_xyz_path` not resolved to an absolute path prior to worker dispatch?**  
   `TOPOSExecutionBroker.launch_search()` serialized the raw configuration string without calling `.resolve()`.
5. **Root Cause 2:** Unsanitized relative path serialization across subprocess working directory boundaries.

### Vector 3: Physical Chemistry Calculation Crash on $He_2$
1. **Why did the conformer search crash when Helium coordinates were loaded?**  
   `atoms.get_potential_energy()` raised `NotImplementedError: No EMT-potential for He`.
2. **Why did it invoke EMT?**  
   `worker_script` hardcoded `from ase.calculators.emt import EMT` and `atoms.calc = EMT()`.
3. **Why was EMT hardcoded instead of xTB?**  
   An uncalibrated calculation routine was embedded in the worker instead of dynamically invoking the configured computational engine.
4. **Why does EMT fail on Helium?**  
   EMT is parameterized strictly for FCC metals and does not compute closed-shell noble gas dispersion interactions.
5. **Root Cause 3:** Hardcoding of a metallic semi-empirical potential (`EMT`) in place of an authentic dispersion-capable quantum chemistry engine (`xTB` with GFN2-xTB).

### Vector 4: Remote Dispatch Deficit
1. **Why did calculations not execute on GitHub Actions?**  
   No API or git dispatch call was triggered to remote runners.
2. **Why was no remote dispatch triggered?**  
   `TOPOSExecutionBroker` only manages local OS `subprocess.Popen` execution trees.
3. **Root Cause 4:** Absence of an asynchronous GitHub Actions workflow dispatcher and artifact retrieval bridge.

---

## 3. Physical State & Method Matrix Compliance Verification [M]

- **Chemical System:** Helium Dimer ($He_2$, van der Waals complex)
- **Equilibrium Separation:** $R_e \approx 2.963392\ \text{Å}$ (5.6 Bohr) [E]
- **Dynamic Mass Provenance:** Strictly verified via `mendeleev.element('He').mass = 4.002602\ \text{Da}` [M]
- **Binding Energy:** Well depth $\approx 0.02\ \text{kcal/mol}$ (requires Grimme D4/D3 dispersion or GFN2-xTB treatment)
- **Physical Test Suite:** Implemented in `tests/test_topos_gui_xtb_gfn2_student_journey.py` and physically verified via pytest (4/4 PASSED in 4.10s):
  1. `test_mendeleev_helium_mass_provenance`: PASSED
  2. `test_topos_ui_environment_and_engine_controls_defect`: PASSED
  3. `test_topos_relative_path_substitution_defect`: PASSED
  4. `test_topos_physical_he2_execution_and_emt_crash`: PASSED

---

## 4. Raw Execution Telemetry & Error Traceback

### Raw Worker Subprocess STDERR on Authentic He2 Coordinates
```
Traceback (most recent call last):
  File "<string>", line 29, in <module>
    initial_e = atoms.get_potential_energy() * ev_to_kcal
                ~~~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "C:\Users\ansac\AppData\Roaming\Python\Python314\site-packages\ase\atoms.py", line 1971, in get_potential_energy
    energy = self._calc.get_potential_energy(self)
  File "C:\Users\ansac\AppData\Roaming\Python\Python314\site-packages\ase\calculators\abc.py", line 25, in get_potential_energy
    return self.get_property(name, atoms)
           ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "C:\Users\ansac\AppData\Roaming\Python\Python314\site-packages\ase\calculators\calculator.py", line 517, in get_property
    self.calculate(atoms, [name], system_changes)
    ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\ansac\AppData\Roaming\Python\Python314\site-packages\ase\calculators\emt.py", line 191, in calculate
    self.initialize(self.atoms)
    ~~~~~~~~~~~~~~~^^^^^^^^^^^^
  File "C:\Users\ansac\AppData\Roaming\Python\Python314\site-packages\ase\calculators\emt.py", line 95, in initialize
    raise NotImplementedError(f'No EMT-potential for {sym}')
NotImplementedError: No EMT-potential for He
```

### Telemetry JSON State Recorded in Scratch
```json
{
  "job_id": "topos_job_c66f26d1",
  "status": "FAILED",
  "start_time": 1726796302.28,
  "tier_id": "T3-3h",
  "protocol": "GOAT",
  "candidates_found": 0,
  "lowest_energy_kcal": 0.0,
  "current_temperature_k": 300.0,
  "rotamers_evaluated": 0,
  "deduplicated_count": 0,
  "error": "Process exited with non-zero returncode 1"
}
```

---

## 5. Mandatory SRS Pipeline Remediation Directives

The CoChem SRS state machine must ingest this report and execute a structured remediation cycle:

1. **Presentation Tier (`frontend/cochem_topos_ui.py`):**
   - Introduce explicit `Interact Env` dropdown with options: `['GitHub Codespaces', 'Local-Windows (WSL)', 'Local-MacOS', 'Local-Linux', 'HPC']` (Default: `'GitHub Codespaces'`).
   - Introduce explicit `Calc Env` dropdown with options: `['github-actions', 'local', 'wsl', 'hpc-slurm']` (Default: `'github-actions'`).
   - Decouple `Engine` dropdown (`['xTB', 'ORCA', 'CFOUR', 'CREST']`) and `Method` dropdown (`['GFN2-xTB', 'GFN1-xTB', 'GFN-FF', 'HF-3c', 'r2SCAN-3c']`) from monolithic tier presets.
   - Sanitize all input paths to absolute paths (`Path(p).resolve()`) prior to state serialization.

2. **Orchestration Tier (`cochem_topos_runner.py`):**
   - Remove hardcoded `from ase.calculators.emt import EMT` and `atoms.calc = EMT()`.
   - Implement dynamic engine dispatch matching the UI configuration:
     - When `Engine == 'xTB'`, invoke authentic `GFN2-xTB` calculation via ASE external calculator or CLI interface (`xtb <file> --gfn 2`).
     - For noble gases ($He_2$, $Ne_2$, $Ar_2$) where dispersion is primary, provide an ab initio Lennard-Jones/Grimme-D4 fallback if local `xtb` binary is uninstalled on the host.
   - Enforce mandatory absolute path resolution in `launch_search()` before passing `input_xyz_path` to worker scripts.

3. **Remote Dispatch Tier (`github-actions` Bridge):**
   - Implement remote workflow dispatch trigger via `gh workflow run` or GitHub Actions REST API when `Calc Env == 'github-actions'`.
   - Provide polling and artifact synchronization from GitHub Actions run artifacts down to `$COCH_STORE_DIR`.

4. **Continuous Integration & Non-Regression Invariant:**
   - Incorporate `tests/test_topos_gui_xtb_gfn2_student_journey.py` into regular test sweeps to guarantee non-regression across all student interaction journeys.
