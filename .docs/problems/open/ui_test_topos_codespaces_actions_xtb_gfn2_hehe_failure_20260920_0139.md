---
id: PROB-TOPOS-CODESPACES-ACTIONS-XTB-GFN2-HE2-20260920-0139
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

To evaluate whether an undergraduate student can execute the assigned workflow within the repository UI, the exact sequence of interactive commands an enrolled student in GitHub Codespaces executes was triggered:

```python
import sys
from pathlib import Path
from mendeleev import element

repo_root = Path(r"D:\__CoChem\GitHub-Repo\CoChem-TOPOS")
sys.path.insert(0, str(repo_root))

from frontend.cochem_topos_ui import CochemToposUI

# 1. Instantiate repository UI
ui = CochemToposUI()

# 2. Inspect student environment & engine configuration controls
# Expected attributes: interact_env='GitHub Codespaces', calc_env='github-actions', engine='xTB', method='GFN2-xTB'
# Result: Missing widget controls on interactive dashboard

# 3. Load authentic He2 van der Waals complex coordinates
he = element("He")
assert abs(float(he.mass) - 4.002602) < 1e-4
ui.load_xyz_from_file("scratch/he_he_dimer_student.xyz")

# 4. Serialize state and execute conformer search
ui.serialize_state()
ui.execute_search_button.click()
```

### Forensic Defect Ledger

| Parameter | Required Specification | Observed Implementation | Statutory Status |
|---|---|---|---|
| **Target Repository** | `TOPOS` | `D:/__CoChem/GitHub-Repo/CoChem-TOPOS` | **PASSED** (Boundary maintained) |
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

### Failure Mode 1: GUI Background Conformer Worker Halt (`EMT()` Noble Gas Incompatibility)
When the student inputs authentic $\text{He}_2$ coordinates and activates `Execute TOPOS Conformer Search`, `cochem_topos_runner.py` executes a background worker utilizing Effective Medium Theory (`EMT`):

```text
Traceback (most recent call last):
  File "<string>", line 29, in <module>
    initial_e = atoms.get_potential_energy() * ev_to_kcal
  File "ase/atoms.py", line 1971, in get_potential_energy
    energy = self._calc.get_potential_energy(self)
  File "ase/calculators/abc.py", line 25, in get_potential_energy
    return self.get_property(name, atoms)
  File "ase/calculators/calculator.py", line 517, in get_property
    self.calculate(atoms, [name], system_changes)
  File "ase/calculators/emt.py", line 191, in calculate
    self.initialize(self.atoms)
  File "ase/calculators/emt.py", line 95, in initialize
    raise NotImplementedError(f'No EMT-potential for {sym}')
NotImplementedError: No EMT-potential for He
```

**Worker Return Code**: `1`  
**Telemetry File State**:
```json
{
  "job_id": "topos_job_5e6dab34",
  "status": "FAILED",
  "start_time": 1789886319.5616114,
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

### Failure Mode 2: Headless Micro-Task Runner Gate (`FileNotFoundError`)
When invoking the programmatic runner (`scripts/run_ui_microtask.py --notebook cochem_topos_master.ipynb --interact-env "GitHub Codespaces" --calc-env github-actions --method GFN2-xTB --work-dir D:\__CoChem\GitHub-Repo\CoChem-TOPOS`), the authentic quantum evaluation step enforces the zero-tolerance binary verification gate:

```text
Traceback (most recent call last):
  File "scripts/run_ui_microtask.py", line 408, in run_ui_microtask
    calc_res = execute_authentic_he2_xtb_harness(
        geometry=geometry,
        method=method,
        temperature_k=298.15,
        pressure_atm=1.0,
        work_dir=effective_work_dir,
    )
  File "scripts/run_ui_microtask.py", line 265, in execute_authentic_he2_xtb_harness
    calc_res: XTBCalculationResult = execute_gfn2_xtb(
        geometry_str=geometry,
        method=method,
        temperature_k=temperature_k,
    )
  File "topos/calculation/xtb_runner.py", line 235, in execute_gfn2_xtb
    raise FileNotFoundError(
        "Authentic 'xtb' binary not found on system PATH or XTBPATH. In accordance with Anti-Spoofing Protocol v4 and Method Matrix v4, empirical approximations and unverified thermodynamic substitutions are strictly prohibited. Calculation must be dispatched to an authentic calculation environment (e.g., github-actions runner or Codespaces container equipped with GFN2-xTB)."
    )
FileNotFoundError: Authentic 'xtb' binary not found on system PATH or XTBPATH.
```

---

## 4. Root Cause Analysis (5 Whys)

1. **Why could a student not complete the assigned micro-task in the repository UI?**  
   The UI dashboard (`frontend/cochem_topos_ui.py`) terminates the worker process upon clicking execution and lacks interactive selectors to configure the assigned environments (`GitHub Codespaces`, `github-actions`) and decoupled methods (`xTB`, `GFN2-xTB`).
2. **Why did the worker process terminate?**  
   `cochem_topos_runner.py` unconditionally initializes `atoms.calc = EMT()`, which lacks parameterization for noble gas atoms ($\text{He}$), raising `NotImplementedError: No EMT-potential for He`.
3. **Why did the UI fail to dispatch to github-actions via GFN2-xTB?**  
   The interactive dashboard widget tree in `frontend/cochem_topos_ui.py` does not contain input selectors for `interaction_environment`, `calculation_environment`, `engine`, or `method`, and does not bind the execution trigger to `topos.actions.dispatch.ActionDispatchClient`.
4. **Why was local fallback prevented?**  
   In compliance with Anti-Spoofing Protocol v4, `topos/calculation/xtb_runner.py` checks host PATH and halts with `FileNotFoundError` when the native binary is missing rather than returning fabricated thermodynamic numbers.
5. **Why does this architectural defect persist (5th Why)?**  
   The front-end presentation layer (`frontend/cochem_topos_ui.py`) and local subprocess broker (`cochem_topos_runner.py`) are architecturally isolated from the remote execution harness (`topos/actions/dispatch.py`), leaving students reliant on a monolithic dashboard unable to evaluate noble gas complexes.

---

## 5. SRS Pipeline Instruction & Mandatory Remediation Tasks

The **SRS (Software Requirements Specification) Pipeline** is instructed to schedule and resolve the following remediation requirements:

- **SRS-REQ-TOPOS-01**: **UI Environment & Method Decoupling**  
  Update `frontend/cochem_topos_ui.py` to add controls for:
  - `interact_env`: `['GitHub Codespaces', 'Local Host', 'HPC Cluster']` (Default: `GitHub Codespaces`)
  - `calc_env`: `['github-actions', 'Local Host', 'Slurm HPC']` (Default: `github-actions`)
  - `engine`: `['xTB', 'ORCA', 'CREST', 'AIMNet2']` (Default: `xTB`)
  - `method`: `['GFN2-xTB', 'GFN1-xTB', 'GFN-FF', 'HF-3c', 'r2SCAN-3c']` (Default: `GFN2-xTB`)
- **SRS-REQ-TOPOS-02**: **Noble Gas & Quantum Engine Worker Routing**  
  Refactor `cochem_topos_runner.py` to inspect input atomic symbols. When noble gas atoms ($\text{He}$, $\text{Ne}$, $\text{Ar}$, $\text{Kr}$) are present or quantum engines are requested, delegate to `topos.calculation.xtb_runner.execute_gfn2_xtb()` or a remote runner rather than attempting `EMT()`.
- **SRS-REQ-TOPOS-03**: **Remote Dispatch Bridge in GUI**  
  Wire `CochemToposUI._on_execute_search_clicked` to `topos.actions.dispatch.ActionDispatchClient` when `calc_env == 'github-actions'`, saving verified workflow manifests and updating runtime telemetry.
- **SRS-REQ-TOPOS-04**: **End-to-End Test Suite Validation**  
  Verify the full student journey against authentic test suites without unverified data structures.
