---
id: PROB-TOPOS-CODESPACES-XTB-002
title: Failure of Student UI Micro-Task for TOPOS in GitHub Codespaces with GitHub Actions Engine
category: ui_test_failure
severity: CRITICAL
status: OPEN
date_logged: 2026-09-19
reporter: cochem-audit (Zero-Trust Auditor)
target_repository: TOPOS
target_system: He2 van der Waals complex
target_engine: xTB (GFN2-xTB)
interaction_environment: GitHub Codespaces
calculation_environment: github-actions
provenance: [M]
---

# Problem Report: TOPOS Student UI Test Failure on He₂ under GitHub Actions Dispatch

## 1. Executive Summary & Micro-Task Specification

An authentic, zero-mock physical audit was conducted to evaluate the student UI pathway for the **TOPOS** repository (`D:/__CoChem/GitHub-Repo/CoChem-TOPOS`) in a standard **GitHub Codespaces** interaction environment with calculation offloading to **github-actions**.

The assigned student micro-task requires:
- **Repository**: `TOPOS` (`CoChem-TOPOS`)
- **Interaction Environment**: `GitHub Codespaces`
- **Calculation Environment**: `github-actions`
- **Computational Engine**: `xTB`
- **Theoretical Method**: `GFN2-xTB`
- **Physical Chemical Target**: Helium dimer ($\text{He}_2$) van der Waals complex ($R_e \approx 2.963392\ \text{Å}$)
- **Atomic Mass Provenance**: Dynamic retrieval via `mendeleev` library (`mendeleev.element('He').mass = 4.002602\ \text{Da}`, $Z=2$) per `cochem-mendeleev-masses.md`.

The student is completely unable to complete the micro-task. The workflow halts due to compound structural deficits:
1. The repository UI (`cochem_topos_master.ipynb` / `frontend/cochem_topos_ui.py`) omits environment, engine, and method selectors.
2. Loading authentic $\text{He}_2$ coordinates crashes the conformer search worker with `NotImplementedError: No EMT-potential for He` in `ase.calculators.emt.EMT`.
3. Relative XYZ coordinate paths cause silent fallback to hydrogen gas ($H_2$).
4. The UI execution broker triggers only local host subprocesses, with zero dispatch bridge to `github-actions`.
5. Standard Codespaces environments lack `actions: write` permissions, blocking remote GitHub Actions workflow triggers.

---

## 2. Experimental / Execution Audit Details

| Parameter | Specification | Physical Observation | Compliance Determination |
|---|---|---|---|
| **Target Repository** | `TOPOS` | `D:/__CoChem/GitHub-Repo/CoChem-TOPOS` | PASSED (Repository boundary enforced) |
| **Interaction Environment** | `GitHub Codespaces` | Monolithic UI without environment dropdown | **FAIL**: No environment widget in `CochemToposUI` |
| **Calculation Environment** | `github-actions` | UI launches only local subprocesses | **FAIL**: No remote GitHub Actions dispatch bridge |
| **Target Engine** | `xTB` | Worker executes hardcoded ASE `EMT()` | **FAIL**: Engine ignored, metallic EMT invoked |
| **Theoretical Method** | `GFN2-xTB` | `EMT` raises `NotImplementedError` | **FAIL**: Crashes immediately on noble gas |
| **Target Complex** | $\text{He}_2$ ($R = 2.963392\ \text{Å}$) | Authentic XYZ loaded (`scratch/he_he_dimer_student_test.xyz`) | PASSED (Zero mock coordinates) |
| **Atomic Mass Provenance** | `mendeleev` | `element('He').mass = 4.002602 Da` | PASSED (Zero hardcoded constants) |

### Physical Constants & Chemical Ground Truth [M]
- **Element**: Helium (`He`), Atomic Number: 2
- **Standard Atomic Weight**: $4.002602\ \text{Da}$ (queried via `mendeleev`)
- **Equilibrium Interatomic Separation ($R_e$)**: $2.963392\ \text{Å}$ ($5.60\ \text{Bohr}$)
- **Well Depth ($\mathcal{D}_e$)**: $\approx 0.0216\ \text{kcal/mol}$ ($\approx 10.87\ \text{K}$)
- **Reference Harmonic Wavenumber**: $\approx 28.4\ \text{cm}^{-1}$

---

## 3. Observed Failure Points & Raw Execution Telemetry

### Defect 1: Missing Environment & Engine Controls in `CochemToposUI`
When a student launches the master interactive control panel (`cochem_topos_master.ipynb` or `from frontend.cochem_topos_ui import CochemToposUI; ui = CochemToposUI()`):
```python
ui = CochemToposUI()
print(hasattr(ui, 'interact_env'))  # False
print(hasattr(ui, 'calc_env'))      # False
print(hasattr(ui, 'engine'))        # False
print(hasattr(ui, 'method'))        # False
```
`CochemToposUI` only exposes:
- `Target Tier:` (`tier_dropdown`)
- `Product:` (`product_class_radio`)
- `Input XYZ:` (`xyz_input`, `xyz_upload`)
- `Atom Count (N):` (`atom_count_widget`)
- `Expert Skip:` (`expert_skip_checkbox`)

The student cannot specify `GitHub Codespaces`, `github-actions`, `xTB`, or `GFN2-xTB`.

### Defect 2: Conformer Search Worker Crash on Helium Dimer (`EMT` Failure)
When the student provides the authentic Helium dimer XYZ file (`he_he_dimer_student_test.xyz`) and clicks the `🚀 Execute TOPOS Conformer Search` button (`ui.execute_search_button.click()`):
The UI invokes `TOPOSExecutionBroker.launch_search()`, which spawns a background worker (`_run_topos_worker_script`).
The worker script hardcodes:
```python
from ase.calculators.emt import EMT
...
atoms.calc = EMT()
initial_e = atoms.get_potential_energy() * ev_to_kcal
```
Because Effective Medium Theory is parameterized strictly for FCC transition metals (Al, Cu, Ag, Au, Ni, Pd, Pt), ASE immediately raises an exception.

#### Raw Subprocess Traceback:
```text
Traceback (most recent call last):
  File "<string>", line 29, in <module>
    initial_e = atoms.get_potential_energy() * ev_to_kcal
  File "C:\Users\ansac\AppData\Roaming\Python\Python314\site-packages\ase\atoms.py", line 1971, in get_potential_energy
    energy = self._calc.get_potential_energy(self)
  File "C:\Users\ansac\AppData\Roaming\Python\Python314\site-packages\ase\calculators\abc.py", line 25, in get_potential_energy
    return self.get_property(name, atoms)
  File "C:\Users\ansac\AppData\Roaming\Python\Python314\site-packages\ase\calculators\calculator.py", line 517, in get_property
    self.calculate(atoms, [name], system_changes)
  File "C:\Users\ansac\AppData\Roaming\Python\Python314\site-packages\ase\calculators\emt.py", line 191, in calculate
    self.initialize(self.atoms)
  File "C:\Users\ansac\AppData\Roaming\Python\Python314\site-packages\ase\calculators\emt.py", line 95, in initialize
    raise NotImplementedError(f'No EMT-potential for {sym}')
NotImplementedError: No EMT-potential for He
```

#### Raw Telemetry JSON Record:
```json
{
  "job_id": "topos_job_1b786d51",
  "status": "FAILED",
  "start_time": 1789874931.3663769,
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

### Defect 3: Silent Relative Path Substitution of H₂ for He₂
In `cochem_topos_runner.py` (lines 120–129):
When a relative path (`he_he_dimer.xyz`) is supplied, the worker subprocess (running inside `scratch/topos_job_<id>`) fails `pathlib.Path(input_xyz).is_file()`.
It silently executes:
```python
mol_name = mol_map.get(atom_cnt, "C2H4")
atoms = ase.build.molecule(mol_name)
```
For `atom_cnt = 2`, `mol_map.get(2)` yields `"H2"`, laundering hydrogen coordinates in place of helium. This violates Anti-Spoofing Protocol v4 §13.

### Defect 4: Complete Absence of GitHub Actions Dispatch Bridge in UI
`CochemToposUI` and `TOPOSExecutionBroker` contain no GitHub Actions API integration. Clicking `Execute` only launches local Python subprocesses. Even when headless `topos/ui.py` is invoked with `--dispatch github-actions`, standard student Codespaces instances lack `actions: write` permissions, halting remote execution.

---

## 4. Root Cause Analysis (Quad-Vector 5 Whys [D])

```
+======================================================================================================================+
|                                    QUAD-VECTOR 5 WHYS ROOT CAUSE ANALYSIS MATRIX                                     |
+======================================================================================================================+
| VECTOR 1: UI PRESENTATION & PARAMETER BINDING DEFICIT                                                                |
| 1. Why could the student not select GitHub Codespaces or github-actions in the UI?                                   |
|    -> CochemToposUI lacks interact_env_dropdown and calc_env_dropdown controls.                                      |
| 2. Why are environment widgets missing?                                                                              |
|    -> The UI was designed with a monolithic Tier dropdown tied to local execution assumptions.                      |
| 3. Why were Engine and Method dropdowns not exposed?                                                                 |
|    -> Engine and method were embedded statically within tier definitions rather than parameterized.                  |
| 4. Root Cause 1: Lack of 6-Tier Environment Matrix and decoupled quantum engine selectors in the UI layer.          |
+----------------------------------------------------------------------------------------------------------------------+
| VECTOR 2: CONFORMER WORKER CALCULATOR CRASH ON NOBLE GAS                                                             |
| 1. Why did the conformer calculation crash on the Helium dimer?                                                      |
|    -> atoms.calc = EMT() raised NotImplementedError: No EMT-potential for He.                                        |
| 2. Why was EMT used instead of GFN2-xTB?                                                                             |
|    -> The worker script in cochem_topos_runner.py hardcoded EMT as a generic placeholder calculator.                 |
| 3. Why does EMT fail on Helium?                                                                                      |
|    -> EMT only parameterizes FCC metals and possesses zero physics for van der Waals dispersion in noble gases.      |
| 4. Root Cause 2: Incompatible hardcoded metallic calculator (EMT) instead of authentic dispersion-capable GFN2-xTB. |
+----------------------------------------------------------------------------------------------------------------------+
| VECTOR 3: WORKING DIRECTORY PATH RESOLUTION GAP                                                                      |
| 1. Why did relative paths cause H2 substitution?                                                                     |
|    -> pathlib.Path(input_xyz).is_file() evaluated to False inside the scratch directory.                             |
| 2. Why did it fall back to H2?                                                                                       |
|    -> mol_map.get(2, 'C2H4') returned 'H2', silently generating hydrogen coordinates.                               |
| 3. Root Cause 3: Failure to resolve input coordinate paths to absolute paths prior to worker dispatch.              |
+----------------------------------------------------------------------------------------------------------------------+
| VECTOR 4: REMOTE DISPATCH & CODESPACES CREDENTIAL BARRIER                                                            |
| 1. Why did the job not execute on GitHub Actions?                                                                    |
|    -> TOPOSExecutionBroker does not implement GitHub Actions REST dispatch.                                          |
| 2. Why does Codespaces fail when remote dispatch is attempted?                                                       |
|    -> Default student Codespaces GITHUB_TOKEN possesses read-only permissions (actions: read).                       |
| 3. Root Cause 4: Lack of authenticated GitHub Actions dispatch bridge and missing Codespaces permission triage.      |
+======================================================================================================================+
```

---

## 5. Mandatory Remediation Directives for the SRS Pipeline

The Software Requirements Specification (SRS) pipeline (`cochem-kanban:trigger_srs_workflow`) is hereby formally instructed to implement the following architectural, interface, and scientific remediations:

1. **Integrate 6-Tier Environment Matrix into `frontend/cochem_topos_ui.py`**:
   - Add `interact_env_dropdown` with choices: `['GitHub Codespaces', 'Local-Windows (WSL)', 'Local-MacOS (OrbStack)', 'Local-Linux (Debian)', 'HPC', 'GitHub Actions']`. Default: `'GitHub Codespaces'`.
   - Add `calc_env_dropdown` with choices: `['github-actions', 'local', 'hpc', 'linux', 'macos', 'wsl']`. Default: `'github-actions'`.
   - Add decoupled `engine_dropdown` (`['xTB', 'ORCA', 'CFOUR', 'CREST']`) and `method_dropdown` (`['GFN2-xTB', 'GFN1-xTB', 'GFN-FF', 'r2SCAN-3c']`).
   - Bind these controls into `TOPOSRuntimeState` serialization.

2. **Replace Hardcoded EMT Calculator in `cochem_topos_runner.py`**:
   - Completely eradicate `from ase.calculators.emt import EMT` and `atoms.calc = EMT()`.
   - Implement dynamic quantum engine dispatch:
     - When `engine == 'xTB'` and `method == 'GFN2-xTB'`, route to `topos.calculation.xtb_runner.execute_gfn2_xtb` or `xtb-python` (`from xtb.ase.calculator import XTB`).
     - Support noble gases ($\text{He}, \text{Ne}, \text{Ar}, \text{Kr}, \text{Xe}$) with authentic physical dispersion potentials (e.g. Lennard-Jones (12-6) or PySCF HF-3c/DFT) when local native binary is absent.

3. **Sanitize Coordinate File Paths in `cochem_topos_runner.py`**:
   - Enforce `input_xyz_path = str(Path(input_xyz_path).resolve())` before launching worker processes or serializing configs to ensure paths survive `cwd` changes.
   - Remove silent fallback to `mol_map.get()` to prevent semantic data laundering. If an input file is missing, raise an immediate, explicit `FileNotFoundError`.

4. **Permission-Aware GitHub Actions Dispatcher**:
   - Connect UI execution triggers to `topos.actions.dispatch.ActionDispatchClient`.
   - Inspect ambient credentials (`gh auth status` or `GITHUB_TOKEN`). If write permissions are absent in GitHub Codespaces, gracefully fallback to local execution with an informative didactic badge rather than crashing.

5. **Empirical Regression Invariant**:
   - Retain and execute `tests/test_topos_gui_xtb_gfn2_student_journey.py` as an asymmetric verification gate requiring all 4 tests to pass under zero-mock constraints.
