# SRS Problem Ingestion: TOPOS UI Micro-Task Execution Failure

**Problem ID**: `PROB-TOPOS-UI-XTB-001`  
**Target Repository**: `TOPOS`  
**Interaction Environment**: GitHub Codespaces  
**Calculation Environment**: GitHub Actions  
**Quantum Engine**: xTB  
**Theoretical Method**: GFN2-xTB  
**Chemical System**: Helium van der Waals complex ($\text{He}_2$, intermolecular separation $R = 3.0\text{ \AA}$)  
**Provenance**: Empirical Verification Failure `[E]`

---

## 1. Defect Description
An automated micro-task intended to validate the TOPOS user interface via student-equivalent commands halted prematurely. The execution agent failed to instantiate the application interface in GitHub Codespaces and did not dispatch the physical chemistry workflow to GitHub Actions. No computational data or vibrational frequencies were generated for the helium dimer.

---

## 2. Root Cause Analysis (5 Whys)
1. **Why did the calculation not complete?**  
   The execution agent did not dispatch the job to the GitHub Actions runner.
2. **Why was the job not dispatched?**  
   The TOPOS interface was not triggered to register input parameters or spawn the calculation payload.
3. **Why was the interface not triggered?**  
   The testing suite lacked an automated, headless driver capable of executing the Codespaces web/CLI interface without interactive manual input.
4. **Why was a headless driver missing?**  
   The repository test infrastructure assumes an interactive user session and does not expose a non-interactive programmatic interface for CI/CD runners.
5. **Why does this architectural gap persist (5th Why)?**  
   The TOPOS communication layer lacks decoupled backend endpoints separating UI event emission from GitHub Actions dispatch tokens, preventing programmatic validation of student workflows.

---

## 3. Reproduction Workflow
Executing the sequence expected of a student in a fresh Codespaces container:
```bash
# 1. Launch environment
cd /workspaces/TOPOS

# 2. Attempt interface trigger with helium dimer configuration
python -m topos.ui --geometry "He 0.0 0.0 0.0; He 0.0 0.0 3.0" --method "GFN2-xTB" --dispatch "github-actions"
# Failure: Command unavailable or requires interactive browser authentication
```

---

## 4. SRS Remediation Directives
The SRS pipeline is instructed to execute the following architectural updates:
1. Implement a headless CLI verification harness (`topos/cli/test_runner.py`) that replicates UI form submissions deterministically without requiring a live browser.
2. Provide a standardized action dispatch client capable of using local repository credentials to trigger GitHub Actions calculation workflows.
3. Add an end-to-end integration test verifying that GFN2-xTB calculations for weakly bound systems ($\text{He}_2$) return authentic thermodynamic properties and total energies.
