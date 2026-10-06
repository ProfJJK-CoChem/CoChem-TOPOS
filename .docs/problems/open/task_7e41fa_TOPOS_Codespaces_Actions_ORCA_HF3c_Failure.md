# UI Test Failure: TOPOS_Codespaces_Actions_ORCA_HF3c

| Field | Value |
|---|---|
| **Repository** | `CoChem-TOPOS` |
| **Interaction Environment** | `GitHub Codespaces` |
| **Calculation Environment** | `github-actions` |
| **Engine** | `ORCA` |
| **Method** | `HF-3c` |
| **Input Complex** | `He-He van der Waals dimer` (`he_he_dimer.xyz`, $R_e = 2.97\,\text{\AA}$) |
| **Notebook / UI Entry** | `cochem_topos_master.ipynb` (`frontend.cochem_topos_ui.CochemToposUI`) |
| **Timestamp** | `2026-09-19T20:23:35` |
| **Status** | `FAILED` |
| **Task Code** | `task_7e41fa_TOPOS_Codespaces_Actions_ORCA_HF3c_Failure` |

---

## Failure Summary & Student Impact

A student following the curriculum workflow cannot complete the required physical chemistry micro-task in `CoChem-TOPOS`:
1. **Missing Interaction and Calculation Environment Controls**: The `CochemToposUI` dashboard provides no controls to set the **Interaction Environment** (`GitHub Codespaces`) or **Calculation Environment** (`github-actions`), unlike `CoChem-BASE` which provides parity controls.
2. **Missing Engine & Method Selectors (ORCA HF-3c)**: The UI lacks independent engine and method selectors. The Method Matrix catalog (`METHOD_MATRIX_V4_TIERS`) contains no tier for `HF-3c`.
3. **Physical Chemistry Worker Crash on Noble Gas (He-He Complex)**: When the calculation is dispatched with real coordinates for the He-He van der Waals complex (`he_he_dimer.xyz`), the backend worker spawned by `cochem_topos_runner.py` crashes because it uses ASE's `EMT()` calculator, which does not support Helium (`NotImplementedError: No EMT-potential for He`). It does not invoke ORCA.

---

## Raw Execution Trace (Unmocked Physical Execution)

```text
=== 1. Instantiating CochemToposUI ===
UI instantiated: <class 'frontend.cochem_topos_ui.CochemToposUI'>

=== 2. Inspecting Environment & Engine UI Controls ===
Has Interaction Environment dropdown: False
Has Calculation Environment dropdown: False
Has Engine dropdown: False
Has Method dropdown: False
Rendered widget count: 9
  Child 0: HTML -> 
  Child 1: Dropdown -> Target Tier:
  Child 2: RadioButtons -> Product:
  Child 3: HBox -> HBox
  Child 4: BoundedIntText -> Atom Count (N):
  Child 5: Checkbox -> Expert Skip: Bypass early MLFF/PES exploratory stages (Provide optimized conformers)
  Child 6: HTML -> 
  Child 7: HBox -> HBox
  Child 8: Output -> Output

Tiers featuring xTB: ['T1-10s', 'T1-1min']

=== 3. Loading He-He van der Waals complex ===
Loaded XYZ: D:\__CoChem\GitHub-Repo\CoChem-TOPOS\scratch\he_he_dimer.xyz
Atom count: 2
Selected tier: T1-10s -> Topology Screen (Hand-Enumerated + GFN2-xTB)

=== 4. Triggering Search Execution ===
🚀 Asynchronous Conformer Search Dispatched: topos_job_ba78d36e
   Protocol: GOAT | Tier: T1-10s
   Air-gap scratch allocated; streaming live telemetry...
Dispatched Job ID: topos_job_ba78d36e

=== 5. Polling Telemetry & Worker Execution ===
Poll 1: status=RUNNING | error=None
Poll 2: status=RUNNING | error=None
Poll 3: status=FAILED | error=Process exited with non-zero returncode 1

--- Worker STDOUT ---

--- Worker STDERR ---
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

Worker exit code: 1

=== Student Task Completion Assessment ===
FAILURE: Student cannot select Interaction Environment (GitHub Codespaces) or Calculation Environment (github-actions). Controls are absent in TOPOS UI.
FAILURE: Worker crashed during physical chemistry execution with exit code 1.
```

---

## SRS Remediation Directive

Instruct the SRS pipeline for `TOPOS` to address the following root causes:
1. **Frontend UI Upgrade (`cochem_topos_ui.py`)**:
   - Add environment selector widgets matching the CoChem unified specification:
     - `Interaction Environment`: `GitHub Codespaces`, `Local-Windows (WSL)`, `Local-Linux (Deb)`, `Local-MacOS (OrbStack)`
     - `Calculation Environment`: `github-actions`, `wsl`, `slurm-cluster`, `local`
   - Add engine (`ORCA`, `CFOUR`, `xTB`) and method (`HF-3c`, `r2SCAN-3c`, `wB97X-V`, etc.) selectors, or integrate a dedicated micro-task tier supporting ORCA HF-3c.
2. **Calculation Backend (`cochem_topos_runner.py`)**:
   - Provide an ORCA calculation dispatch adapter that generates genuine ORCA input (`! HF-3c Opt`) and submits to the target calculation environment (`github-actions` / local ORCA binary).
   - If fallback to an empirical/semi-empirical calculator is used for local screening, replace `EMT()` with a calculator that physically supports Helium (e.g. `GFN2-xTB`, `PySCF`, or authentic ORCA binary) rather than hardcoded EMT.
