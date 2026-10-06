---
id: PROB-TOPOS-CODESPACES-ACTIONS-XTB-GFN2-HE2-20260920-0006
title: Physical Failure of Student UI Micro-Task in TOPOS under GitHub Codespaces with GitHub Actions Engine
category: ui_test_failure
severity: CRITICAL
status: OPEN
date_logged: 2026-09-20
reporter: cochem-audit (Kanban Automated Worker)
target_repository: TOPOS
target_system: He2 van der Waals complex
target_engine: xTB
target_method: GFN2-xTB
interaction_environment: GitHub Codespaces
calculation_environment: github-actions
provenance: [E]
---

# Problem Report: TOPOS Student UI Workflow Failure (GitHub Codespaces + github-actions + xTB / GFN2-xTB)

## 1. Executive Summary & Assigned Micro-Task Specification

Pursuant to the CoChem Swarm Zero-Trust Charter, Anti-Spoofing Protocol v4 (§1 Asymmetric Verification, §3 Zero Mocks or Stub Logic, §7 Counterfeit Compliance, §8 Semantic Spoofing Ban, §13 Data Laundering Ban), and the Mendeleev Dynamic Mass Mandate, an authentic, physical audit was performed on the **TOPOS** repository (`D:/__CoChem/GitHub-Repo/CoChem-TOPOS`).

The assigned micro-task parameters are:
- **Target Repository**: `TOPOS` (`CoChem-TOPOS`, `D:/__CoChem/GitHub-Repo/CoChem-TOPOS`) [D]
- **Target UI File**: `frontend/cochem_topos_ui.py` / `cochem_topos_master.ipynb` [D]
- **Interaction Environment**: `GitHub Codespaces` [D]
- **Calculation Environment**: `github-actions` [D]
- **Computational Engine**: `xTB` [D]
- **Quantum Method**: `GFN2-xTB` [M]
- **Chemical Target**: Helium dimer ($\text{He}_2$) van der Waals complex ($R_e = 2.970000\ \text{Å}$) [E]
- **Mass Provenance**: Dynamic query via `mendeleev` library (`mendeleev.element('He').mass = 4.002602\ \text{Da}`, $Z=2$, atomic number verified).

### Physical Chemistry Benchmark Constants [M]
- **Species**: Helium dimer ($\text{He}_2$)
- **Equilibrium Separation ($R_e$)**: $2.970000\ \text{Å}$
- **Atomic Mass ($^4\text{He}$)**: $4.002602\ \text{Da}$ via `mendeleev` dynamic query
- **Theoretical Well Depth ($\mathcal{D}_e$)**: $\approx -0.0215\ \text{kcal/mol}$ (weakly bound dispersion minimum)
- **Harmonic Wavenumber ($\omega_e$)**: $\approx 28.39\ \text{cm}^{-1}$
- **Total Electronic Energy**: $\approx -1.996899\ \text{Hartree}$ (sum of two isolated He monomers at $-0.998450\ \text{Hartree}$ plus binding potential)

---

## 2. Experimental Execution & Student Reproduction Findings

To evaluate whether a student can successfully execute the assigned micro-task within the repository UI, the exact interactive commands that an undergraduate student in GitHub Codespaces would execute were physically triggered:

```python
import sys
from pathlib import Path
repo_dir = Path(r"D:\__CoChem\GitHub-Repo\CoChem-TOPOS")
sys.path.insert(0, str(repo_dir))
from frontend.cochem_topos_ui import CochemToposUI
from mendeleev import element

ui = CochemToposUI()
# A student in GitHub Codespaces needs to select:
#   Interaction Environment: GitHub Codespaces
#   Calculation Environment: github-actions
#   Engine: xTB
#   Method: GFN2-xTB

# Load authentic He-He van der Waals complex
ui.load_xyz_from_file("scratch/he_he_dimer_student.xyz")
ui.serialize_state()
ui.execute_search_button.click()
```

### Forensic Defect Ledger

| Parameter | Required Specification | Observed Implementation | Statutory Status |
|---|---|---|---|
| **Target Repository** | `TOPOS` | `D:/__CoChem/GitHub-Repo/CoChem-TOPOS` | **PASSED** (Boundary maintained) |
| **Interaction Env Widget** | `GitHub Codespaces` | `hasattr(ui, 'interact_env') == False` | **FAIL**: No environment selector widget |
| **Calculation Env Widget** | `github-actions` | `hasattr(ui, 'calc_env') == False` | **FAIL**: No execution target selector widget |
| **Engine Selector** | `xTB` | `hasattr(ui, 'engine') == False` | **FAIL**: Engine selector missing from dashboard |
| **Method Selector** | `GFN2-xTB` | `hasattr(ui, 'method') == False` | **FAIL**: Method selector missing from dashboard |
| **Conformer Calculation** | `GFN2-xTB` on $\text{He}_2$ | Hardcoded `EMT()` executed in worker | **FAIL**: Worker crashes with `NotImplementedError` |
| **Remote Actions Dispatch**| `github-actions` trigger | GUI solely invokes local subprocess broker | **FAIL**: Zero remote dispatch wiring in GUI |
| **Local Binary Gate** | Authentic `xtb` binary | `shutil.which('xtb') == None` | **FAIL**: Missing local binary raises `FileNotFoundError` |
| **Mass Provenance** | `mendeleev` | `mendeleev.element('He').mass == 4.002602` | **PASSED**: Authentic dynamic mass verified |

---

## 3. Observed Failure Telemetry & Raw Tracebacks

### Failure Mode 1: GUI Background Conformer Worker Crash (`EMT()` Noble Gas Incompatibility)
When the student loads authentic $\text{He}_2$ coordinates and clicks `Execute TOPOS Conformer Search`, `cochem_topos_runner.py` spawns a background worker subprocess executing Effective Medium Theory (`EMT`):

```text
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

**Worker Process Return Code**: `1`  
**Telemetry File State**:
```json
{
  "job_id": "topos_job_e9424333",
  "status": "FAILED",
  "start_time": 1789881930.12,
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

### Failure Mode 2: Headless Micro-Task Runner Gate Failure (`FileNotFoundError`)
When executing via the programmatic headless harness (`scripts/run_ui_microtask.py --geometry scratch/he_he_dimer_student.xyz --method GFN2-xTB --calc-env github-actions --interact-env "GitHub Codespaces"`), the authentic quantum evaluation step enforces the zero-mock Authentic Binary Execution Gate:

```text
Traceback (most recent call last):
  File "D:\__CoChem\GitHub-Repo\CoChem-TOPOS\scripts\run_ui_microtask.py", line 408, in run_ui_microtask
    calc_res = execute_authentic_he2_xtb_harness(
        geometry=geometry,
        method=method,
        temperature_k=298.15,
        pressure_atm=1.0,
        work_dir=effective_work_dir,
    )
  File "D:\__CoChem\GitHub-Repo\CoChem-TOPOS\scripts\run_ui_microtask.py", line 265, in execute_authentic_he2_xtb_harness
    calc_res: XTBCalculationResult = execute_gfn2_xtb(
        geometry_str=geometry,
        method=method,
        temperature_k=temperature_k,
    )
  File "D:\__CoChem\GitHub-Repo\CoChem-TOPOS\topos\calculation\xtb_runner.py", line 235, in execute_gfn2_xtb
    raise FileNotFoundError(
        "Authentic 'xtb' binary not found on system PATH or XTBPATH. In accordance with Anti-Spoofing Protocol v4 (§1-§14) and Method Matrix v4, classical approximations, dummy potentials, and synthetic thermodynamic substitutions are strictly prohibited. Calculation must be dispatched to an authentic calculation environment (e.g., github-actions runner or Codespaces container equipped with GFN2-xTB)."
    )
FileNotFoundError: Authentic 'xtb' binary not found on system PATH or XTBPATH.
```

### Failure Mode 3: Student Journey Regression Pytest Verification
Physical execution of `pytest tests/test_topos_gui_xtb_gfn2_student_journey.py -v`:
```text
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-8.4.2, pluggy-1.5.0
cachedir: .pytest_cache
rootdir: D:\__CoChem\GitHub-Repo\CoChem-TOPOS
configfile: pytest.ini
collected 4 items

tests/test_topos_gui_xtb_gfn2_student_journey.py::test_mendeleev_helium_mass_provenance PASSED [ 25%]
tests/test_topos_gui_xtb_gfn2_student_journey.py::test_topos_ui_environment_and_engine_controls_defect PASSED [ 50%]
tests/test_topos_gui_xtb_gfn2_student_journey.py::test_topos_relative_path_substitution_defect PASSED [ 75%]
tests/test_topos_gui_xtb_gfn2_student_journey.py::test_topos_physical_he2_execution_and_emt_crash PASSED [100%]

============================== 4 passed in 4.38s ==============================
```

---

## 4. Root Cause Analysis (5 Whys)

1. **Why could a student not complete the assigned micro-task in the repository UI?**  
   The UI dashboard (`CochemToposUI`) crashed the background worker immediately upon clicking the execution button, and lacked controls to configure the required environments and engine.
2. **Why did the background worker crash?**  
   `cochem_topos_runner.py` unconditionally initializes `atoms.calc = EMT()`, which lacks parameterization for noble gas atoms ($\text{He}$), raising an unhandled `NotImplementedError`.
3. **Why did the UI fail to route the calculation to github-actions via GFN2-xTB?**  
   The interactive dashboard widget tree in `frontend/cochem_topos_ui.py` does not possess input selectors for `interaction_environment` (`GitHub Codespaces`), `calculation_environment` (`github-actions`), `engine` (`xTB`), or `method` (`GFN2-xTB`), and does not connect the execute button to `topos.actions.dispatch.ActionDispatchClient`.
4. **Why was local fallback to `xTB` prevented?**  
   In compliance with Anti-Spoofing Protocol v4, `topos.calculation.xtb_runner.execute_gfn2_xtb` strictly enforces zero-mock execution and halts with `FileNotFoundError` when the native binary is missing from the host environment rather than synthesising fake physics.
5. **Why does this systemic defect persist (5th Why)?**  
   The front-end presentation tier (`frontend/cochem_topos_ui.py`) and asynchronous execution broker (`cochem_topos_runner.py`) remain architecturally decoupled from the headless dispatch harness (`topos/ui.py` and `topos/actions/dispatch.py`), leaving undergraduate students reliant on legacy monolithic widgets that crash on noble gas non-covalent complexes.

---

## 5. SRS Pipeline Instruction & Mandatory Remediation Tasks

The **SRS (Software Requirements Specification) Pipeline** is hereby formally instructed to prioritize, schedule, and resolve the following remediation requirements:

- **SRS-REQ-TOPOS-01**: **UI Environment & Method Decoupling**  
  Update `frontend/cochem_topos_ui.py` to add first-class ipywidget dropdowns for:
  - `interact_env`: `['GitHub Codespaces', 'Local Host', 'HPC Cluster']` (Default: `GitHub Codespaces`)
  - `calc_env`: `['github-actions', 'Local Host', 'Slurm HPC']` (Default: `github-actions`)
  - `engine`: `['xTB', 'ORCA', 'CREST', 'AIMNet2']` (Default: `xTB`)
  - `method`: `['GFN2-xTB', 'GFN1-xTB', 'GFN-FF', 'HF-3c', 'r2SCAN-3c']` (Default: `GFN2-xTB`)
- **SRS-REQ-TOPOS-02**: **Noble Gas & Quantum Engine Worker Routing**  
  Refactor `cochem_topos_runner.py` worker script to inspect input elements. When noble gas atoms ($\text{He}$, $\text{Ne}$, $\text{Ar}$, $\text{Kr}$) are present or quantum engines (`xTB`, `ORCA`) are requested, delegate to `topos.calculation.xtb_runner.execute_gfn2_xtb()` or an authentic remote runner rather than attempting `EMT()`.
- **SRS-REQ-TOPOS-03**: **Remote Dispatch Bridge in GUI**  
  Wire `CochemToposUI._on_execute_search_clicked` to `topos.actions.dispatch.ActionDispatchClient` whenever `calc_env == 'github-actions'`, saving verified workflow payloads to disk and updating `TOPOS_Runtime_State.json` with dispatch telemetry.
- **SRS-REQ-TOPOS-04**: **End-to-End Test Suite Validation**  
  Verify the full student journey against `tests/test_topos_gui_xtb_gfn2_student_journey.py` and `tests/test_topos_xtb_he2_actions_integration.py` to ensure zero mock data and 100% compliance across all test fixtures.
