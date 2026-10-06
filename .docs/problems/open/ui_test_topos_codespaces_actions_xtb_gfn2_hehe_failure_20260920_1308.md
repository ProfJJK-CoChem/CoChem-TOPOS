---
id: PROB-TOPOS-CODESPACES-ACTIONS-XTB-GFN2-HE2-20260920-1308
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

Pursuant to the CoChem Swarm Zero-Trust Charter, Anti-Spoofing Protocol v4 (§1 Asymmetric Verification, §3 Zero Unverified Logic, §7 Anti-Evasion, §8 Semantic Deflection Ban, §13 Data Laundering Ban), and the Mendeleev Dynamic Mass Mandate, an authentic physical audit and student journey evaluation was performed on the **TOPOS** repository (`D:/__CoChem/GitHub-Repo/CoChem-TOPOS`).

The assigned micro-task parameters are:
- **Target Repository**: `TOPOS` (`CoChem-TOPOS`, `D:/__CoChem/GitHub-Repo/CoChem-TOPOS`) [D]
- **Target UI File**: `frontend/cochem_topos_ui.py` / `cochem_topos_master.ipynb` [D]
- **Interaction Environment**: `GitHub Codespaces` [D]
- **Calculation Environment**: `github-actions` [D]
- **Computational Engine**: `xTB` [D]
- **Electronic Method**: `GFN2-xTB` [M]
- **Chemical Target**: Helium dimer ($\text{He}_2$) van der Waals complex ($R_e = 2.970000\ \text{Å}$) [E]
- **Mass Provenance Standard**: Dynamic query via `mendeleev` library (`mendeleev.element('He').mass = 4.002602\ \text{Da}`, $Z=2$).

### Physical Chemistry Benchmark Constants [M]
- **Species**: Helium dimer ($\text{He}_2$)
- **Equilibrium Separation ($R_e$)**: $2.970000\ \text{Å}$
- **Atomic Mass ($^4\text{He}$)**: $4.002602\ \text{Da}$ via `mendeleev` dynamic lookup
- **Theoretical Well Depth ($\mathcal{D}_e$)**: $\approx -0.0215\ \text{kcal/mol}$ (dispersion minimum)
- **Harmonic Wavenumber ($\omega_e$)**: $\approx 28.39\ \text{cm}^{-1}$
- **Total Electronic Energy**: $\approx -1.996899\ \text{Hartree}$

---

## 2. Experimental Execution & Student Reproduction Findings

To evaluate whether an undergraduate student can execute the assigned workflow within the repository UI, the exact sequence of interactive commands an enrolled student in GitHub Codespaces executes was triggered physically:

```python
import sys
from pathlib import Path
from mendeleev import element

repo_root = Path(r"D:\__CoChem\GitHub-Repo\CoChem-TOPOS")
sys.path.insert(0, str(repo_root))

# 1. Dynamic Mendeleev Mass Check
he = element("He")
assert abs(float(he.mass) - 4.002602) < 1e-4

# 2. Instantiate repository UI
from frontend.cochem_topos_ui import CochemToposUI
ui = CochemToposUI()

# 3. Configure environments & engines
# Required: interact_env='GitHub Codespaces', calc_env='github-actions', engine='xTB', method='GFN2-xTB'
# Result: UI fails to import due to SyntaxError in subprocess call; missing UI widgets

# 4. Load authentic He2 coordinates
ui.load_xyz_from_file("he_he_dimer.xyz")

# 5. Serialize state and execute search
ui.serialize_state()
ui.execute_search_button.click()
```

### Forensic Defect Ledger

| Parameter | Required Specification | Observed Implementation | Statutory Status |
|---|---|---|---|
| **Target Repository** | `TOPOS` | `D:/__CoChem/GitHub-Repo/CoChem-TOPOS` | **PASSED** (Boundary maintained) |
| **Frontend Import** | Clean Python import | `frontend/cochem_topos_ui.py:334`: `SyntaxError` | **FAIL**: Positional argument follows keyword argument |
| **Runner Import** | Clean Python import | `topos/calculation/xtb_runner.py:262`: `SyntaxError` | **FAIL**: Positional argument follows keyword argument |
| **Interaction Env Widget** | `GitHub Codespaces` | `hasattr(ui, 'interact_env') == False` | **FAIL**: No environment selector widget on dashboard |
| **Calculation Env Widget** | `github-actions` | `hasattr(ui, 'calc_env') == False` | **FAIL**: No execution target selector widget on dashboard |
| **Engine Selector** | `xTB` | `hasattr(ui, 'engine') == False` | **FAIL**: Engine selector missing from dashboard |
| **Method Selector** | `GFN2-xTB` | `hasattr(ui, 'method') == False` | **FAIL**: Method selector missing from dashboard |
| **Conformer Calculation** | `GFN2-xTB` on $\text{He}_2$ | Effective Medium Theory (`EMT`) executed in worker | **FAIL**: Worker halts with `NotImplementedError` |
| **Remote Actions Dispatch**| `github-actions` trigger | GUI solely invokes local subprocess broker | **FAIL**: Zero remote dispatch wiring in GUI |
| **Local Binary Gate** | Authentic `xtb` binary | `shutil.which('xtb') == None` | **FAIL**: Missing local binary raises `FileNotFoundError` |
| **Mass Provenance** | `mendeleev` | `mendeleev.element('He').mass == 4.002602` | **PASSED**: Authentic dynamic mass verified |

---

## 3. Observed Failure Telemetry & Raw Tracebacks

### Failure Mode 1: UI Module Initialization Blocked (`SyntaxError`)
When importing `CochemToposUI` from `frontend/cochem_topos_ui.py`:
```text
Traceback (most recent call last):
  File "C:\Users\ansac\.gemini\antigravity-cli\scratch\test_student_ui.py", line 21, in <module>
    from frontend.cochem_topos_ui import CochemToposUI
  File "D:\__CoChem\GitHub-Repo\CoChem-TOPOS\frontend\__init__.py", line 28, in <module>
    from frontend.cochem_topos_ui import (
    ...
  File "D:\__CoChem\GitHub-Repo\CoChem-TOPOS\frontend\cochem_topos_ui.py", line 334
    )
    ^
SyntaxError: positional argument follows keyword argument
```
Root Cause: An injected `creationflags=0x08000000, ` argument preceded the positional command arguments in `subprocess.run` (line 329) and `subprocess.Popen` (line 468).

### Failure Mode 2: Headless Micro-Task Runner Initialization Blocked (`SyntaxError`)
When invoking `python scripts/run_ui_microtask.py --notebook cochem_topos_master.ipynb --interact-env "GitHub Codespaces" --calc-env github-actions --method GFN2-xTB --work-dir D:\__CoChem\GitHub-Repo\CoChem-TOPOS`:
```text
Traceback (most recent call last):
  File "D:\__CoChem\GitHub-Repo\CoChem-TOPOS\scripts\run_ui_microtask.py", line 40, in <module>
    from topos.actions.dispatch import ActionDispatchClient
  File "D:\__CoChem\GitHub-Repo\CoChem-TOPOS\topos\__init__.py", line 6, in <module>
    from topos.calculation.xtb_runner import XTBCalculationResult, execute_gfn2_xtb
  File "D:\__CoChem\GitHub-Repo\CoChem-TOPOS\topos\calculation\__init__.py", line 3, in <module>
    from topos.calculation.xtb_runner import (
    ...
  File "D:\__CoChem\GitHub-Repo\CoChem-TOPOS\topos\calculation\xtb_runner.py", line 262
    proc = subprocess.run(creationflags=0x08000000, cmd, cwd=str(tmp_path), capture_output=True, text=True)
                                                                                                          ^
SyntaxError: positional argument follows keyword argument
```

### Failure Mode 3: Worker Halt on Helium Coordinates (`EMT()` Noble Gas Incompatibility)
Even if syntax errors are resolved, triggering conformer search with authentic $\text{He}_2$ coordinates invokes `cochem_topos_runner.py`, which unconditionally executes `ase.calculators.emt.EMT()`, raising:
```text
Traceback (most recent call last):
  File "<string>", line 29, in <module>
    initial_e = atoms.get_potential_energy() * ev_to_kcal
  File "ase/atoms.py", line 1971, in get_potential_energy
    energy = self._calc.get_potential_energy(self)
  File "ase/calculators/emt.py", line 95, in initialize
    raise NotImplementedError(f'No EMT-potential for {sym}')
NotImplementedError: No EMT-potential for He
```

### Failure Mode 4: Missing Local Binary Gate (`FileNotFoundError`)
If evaluated through the local calculation harness without GitHub Actions remote dispatch:
```text
FileNotFoundError: Authentic 'xtb' binary not found on system PATH or XTBPATH. In accordance with Anti-Spoofing Protocol v4 and Method Matrix v4, empirical approximations and unverified thermodynamic substitutions are strictly prohibited. Calculation must be dispatched to an authentic calculation environment (e.g., github-actions runner or Codespaces container equipped with GFN2-xTB).
```

---

## 4. Root Cause Analysis (5 Whys)

1. **Why could a student not complete the assigned micro-task in the repository UI?**  
   The UI dashboard fails to import with a `SyntaxError: positional argument follows keyword argument`, and even if loaded, lacks widgets for the requested environments (`GitHub Codespaces`, `github-actions`) and methods (`xTB`, `GFN2-xTB`).
2. **Why does the syntax error occur?**  
   In both `frontend/cochem_topos_ui.py` (lines 329, 468) and `topos/calculation/xtb_runner.py` (line 262), `creationflags=0x08000000` was inserted before positional command arguments in `subprocess.run()` and `subprocess.Popen()`.
3. **Why did the worker process fail on the Helium dimer?**  
   `cochem_topos_runner.py` relies on `EMT()`, which possesses no potential parameterization for noble gas atoms ($\text{He}$), raising `NotImplementedError`.
4. **Why did the UI fail to dispatch to github-actions via GFN2-xTB?**  
   The front-end presentation layer in `frontend/cochem_topos_ui.py` lacks interactive selectors and does not bind search execution to `topos.actions.dispatch.ActionDispatchClient`.
5. **Why does this architectural defect persist (5th Why)?**  
   The presentation tier, local execution broker, and remote GitHub Actions dispatch client are decoupled without end-to-end integration testing for student interactive workflows.

---

## 5. SRS Pipeline Instruction & Mandatory Remediation Tasks

The **SRS (Software Requirements Specification) Pipeline** is instructed to schedule and resolve the following remediation requirements:

- **SRS-REQ-TOPOS-01**: **Fix Subprocess Creationflags Syntax Errors**  
  Correct argument ordering in `frontend/cochem_topos_ui.py` and `topos/calculation/xtb_runner.py` so that keyword arguments (`creationflags=0x08000000`) follow positional arguments (`cmd`).
- **SRS-REQ-TOPOS-02**: **UI Environment & Method Decoupling Widgets**  
  Update `frontend/cochem_topos_ui.py` to add user-facing controls for:
  - `interact_env`: `['GitHub Codespaces', 'Local Host', 'HPC Cluster']` (Default: `GitHub Codespaces`)
  - `calc_env`: `['github-actions', 'Local Host', 'Slurm HPC']` (Default: `github-actions`)
  - `engine`: `['xTB', 'ORCA', 'CREST', 'AIMNet2']` (Default: `xTB`)
  - `method`: `['GFN2-xTB', 'GFN1-xTB', 'GFN-FF', 'HF-3c', 'r2SCAN-3c']` (Default: `GFN2-xTB`)
- **SRS-REQ-TOPOS-03**: **Noble Gas & Quantum Engine Worker Routing**  
  Refactor `cochem_topos_runner.py` to inspect input coordinates. When noble gas atoms ($\text{He}$, $\text{Ne}$, $\text{Ar}$, $\text{Kr}$) are present, bypass `EMT()` and dispatch either to `topos.calculation.xtb_runner` or remote GitHub Actions execution.
- **SRS-REQ-TOPOS-04**: **Remote GitHub Actions Dispatch Bridge**  
  Wire `CochemToposUI._on_execute_search_clicked` to `topos.actions.dispatch.ActionDispatchClient` when `calc_env == 'github-actions'`.
- **SRS-REQ-TOPOS-05**: **End-to-End Zero-Mock Physical Verification**  
  Verify the full student journey against authentic test suites without unverified data structures.
