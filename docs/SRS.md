---
schema: cochem-srs/5.0
repo: CoChem-TOPOS
status: ACTIVE_CORE (22/50 hosted acceptance clauses verified; 28 verification-pending)
pipeline_baseline: 5.0.0
source_commit: 1b3e4b94d1abcafbbee4053b6d7533a874675a91
decision_ref: swarm-1126-8efd
---

# Software Requirements Specification: CoChem-TOPOS (Pipeline 5.0.0)

## 1. Purpose, Scope & System Classification

`CoChem-TOPOS` (`ProfJJK-CoChem/CoChem-TOPOS`, Python distribution `cochem-topos` v0.1.0) is classified as an **`ACTIVE_CORE`** (`wave1_core_9`) repository in the CoChem Pipeline 5.0.0 ecosystem. It provides traceable molecular topology analysis, conformer and van der Waals isomer search, deduplication, human-in-the-loop (HITL) candidate review, counterpoise and composite thermochemical energy refinement, and verified structural/ensemble export to `CoChem-BASE` and `CoChem-TORQ`.

The authoritative installable package lives under `topos/` (127 tracked production `.py` modules, 0 broken imports, 0 `NotImplementedError` stubs) with console entrypoints declared in `pyproject.toml`:
- `cochem-topos` -> `topos/cli/__init__.py` (`topos.cli:main`, 24 subcommands including `capabilities`, `request-schema`, `doctor`, `matrix`, `plan`, `run`, `ingest`, `receive-base`, `resume`, `inspect`, `basket`, `review`, `handoff`, `export-handoff`, `verify-handoff`, `receive-torq`, `export`, `verify-export`)
- `cochem-topos-release` -> `topos/release.py` (`topos.release:main`)
- `topos-ui` -> `topos/ui.py` (`topos.ui:ui_main`, backed by `topos/streamlit_app.py` and root compatibility shim `frontend/cochem_topos_ui.py`)

Structural ownership transferred from `CoChem-BASE` resides in `topos/structural/graph.py`, `topos/structural/resonance.py`, `topos/structural/rings.py`, `topos/structural/tautomer.py`, and `topos/structural/boundary.py`.

## 2. Pipeline 5.0.0 Architecture Alignment & Resolved Conflicts

`CoChem-TOPOS` conforms to Pipeline 5.0.0 governance ratified under `swarm-1126-8efd` and resolves the following legacy v4.x conflicts:
- **`CONTRA-01` (Compute Topology & `HC-1`):** Supersedes legacy GitHub Actions compute directives (`.docs/ORCA_GITHUB_ACTIONS.md`, `topos/actions/dispatch.py` cloud-runner assumptions). Heavy ORCA, CFOUR, CREST, GOAT, MACE, and AIMNet2 workloads execute via local WSL2 (`host-guard`), Google Colab Pro+ GPU (`w51..w52` via `colab-offload`), GCP Spot CPU, or the Cloud Run `/mcp` and Drive `cochem-mcp-mailbox-request/2` harness. GitHub Actions workflows (`.github/workflows/cochem_topos_ci.yml`, `structural_ownership.yml`, `topos_base_ci.yml`) are restricted to lightweight verification and zero-mock CI gating.
- **`CONTRA-03` (Workstation & Cloud Runner Transport):** File-based immutable handoffs (`topos/base_integration.py`) supersede the retired SQLite WAL `kanban_tasks_v3` IPC described in pre-v5 documents.
- **`CONTRA-05` (Method Matrix & DLPNO Firewall):** New coupled-cluster campaign submissions are subject to Pipeline 5.0.0 `DLPNOExclusionFirewall` (favoring canonical `CCSD(T)` / `CCSD(T)-F12b`, ORCA 6.1.1 `revDSD-PBEP86-D4`, and `GPU4PySCF` `wB97X-V`) and Method Matrix §4.4 explicit `%geom` controls.
- **`CONTRA-06` (Unified Handoff Contracts):** Legacy untagged `TOPOS_CANDIDATE*_TORQ_HANDOFF.json` payloads are transitional; downstream integration targets the shared Pipeline 5.0.0 DRAFT schemas hosted in `CoChem-BASE`.

## 3. Authoritative Scientific Engines, Methods & Method Matrix Constraints

`CoChem-TOPOS` orchestrates authentic external electronic-structure, semiempirical, and machine-learning interatomic potential engines with strict zero-mock/no-EMT enforcement:
- **Catalog & Recipes:** `topos/method_matrix.py`, `topos/data/method_matrix_v4.py`, `topos/data/reviewed_matrix_v010.py`, and `topos/data/runtime_recipes.py` implement the 140-row Method Matrix catalog and 42 active TOPOS recipes (`T3C-10s` and `T3C-1min` CFOUR tiers remain explicitly marked unavailable).
- **Conformer & Cluster Search:** `topos/sampling.py`, `topos/goat.py`, `topos/abcluster.py`, `topos/ml_crest.py`, `topos/ml_extopt.py`, `topos/ml_worker.py`, and `topos/ml_training_worker.py` drive CREST, ORCA GOAT, ABCluster, MACE-OFF, and AIMNet2 searches (legacy `EMT()` was permanently purged).
- **Quantum Refinement & Properties:** `topos/engines.py`, `topos/external_engines.py`, `topos/counterpoise.py`, `topos/correlated_counterpoise.py`, `topos/orca_f12_composite.py`, `topos/orca_numerical_geometry.py`, `topos/cfour_operator.py`, `topos/cfour_counterpoise.py`, `topos/cfour_dboc.py`, `topos/cfour_efg.py`, `topos/anharmonic.py`, `topos/thermochemistry.py`, and `topos/rotational_transfer.py`.
- **Method Matrix Constraints:** Explicit 5-criterion `%geom` convergence blocks are required for production ORCA optimizations. Unpaired `! TightOpt` shorthand currently remaining in `topos/ml_extopt.py` and `topos/goat.py` is tracked as a Method Matrix §4.4 remediation item in Section 6.

## 4. Cross-Repo Interfaces, Contracts & Canonical Schemas

- **CoChem-BASE Provider Entrypoint:** `pyproject.toml` exposes `[project.entry-points."cochem.modules"]` `topos = "topos.base_provider:provider"` implemented in `topos/base_provider.py` and `topos/base_integration.py` (`cochem.module-provider/1` protocol, nuclide and structural handoffs).
- **CoChem-TORQ Ensemble Handoff:** `topos/workflow.py`, `topos/review.py`, and `topos/reporting.py` emit reviewed isomer baskets consumed by `cochem-torq import-topos-reviewed` and accept `receive-torq` acknowledgments.
- **Pipeline 5.0.0 Target Schemas:** All cross-repo cloud/workstation handoffs and governance escalations align with the canonical `CoChem-BASE` DRAFT schemas (`cochem-job-handoff/1`, `cochem-quantities/1` under `OWN-117`, and `cochem-portal-dossier/1.1`). Existing untagged `topos-torq-handoff/0.1.0` JSON bundles are retained strictly as transitional compatibility outputs until unified schema adapters land.
- **Namespace Isolation:** The packaged wheel (`pyproject.toml`) includes only `topos*` and `cochem_topos_web.py`, maintaining disjoint package ownership from `CoChem-BASE` and `CoChem-TORQ`.

## 5. Verification, Zero-Mock CI Gates & Acceptance Criteria

- **Zero-Mock & Anti-Spoofing Gate:** `tests/test_zero_mock_and_no_sim_gate.py` enforces AST scanning over production code, tests, and notebooks with `.anti_spoof_amnesty.json` strictly empty (`[]`). Commit `1b3e4b94` excluded the CI-only `.cochem-dependencies/` checkout from the gate scan so PR #9 CI verifies cleanly.
- **Unit & Structural Verification:** 116 test modules under `tests/v010/` (including `tests/v010/test_base_provider.py`, `tests/v010/test_method_matrix.py`, `tests/v010/test_cfour_operator.py`, `tests/v010/test_orca_f12_composite.py`, `tests/v010/test_structural_ownership.py`, `tests/v010/test_torq_sidecar.py`, and `tests/test_external_ingestion.py`) verify math, constraints, storage, and structural boundaries.
- **Branch Protection & Release Gate:** `main` is branch-protected requiring authentic completion of `blind-s3-p10` (`blind.s3.hof.gpu4pyscf.wb97xv.p1` RTX 3090 parity `-175.5545602130 Eh`) plus green `verify` and `installed-structural-wheel` CI checks.
- **Acceptance Ledger:** `.docs/TOPOS_SRS_ACCEPTANCE.json` tracks 50 formal acceptance clauses (`22 verified`, `28 verification-pending`, `0 coding_gaps`).

## 6. Verified Implementation Gaps, Known Holds & Non-Goals

The following verified gaps from the 2026-11-26 Opus-verified audit remain open and MUST NOT be misrepresented as complete:
1. **28 Pending Hosted/Native/GPU Acceptance Clauses:** `.docs/TOPOS_SRS_ACCEPTANCE.json` remains `incomplete` (`22 verified`, `28 verification-pending`) awaiting hosted ORCA strict 5-criterion convergence (`r2SCAN-3c`, `wB97X-V`, `GOAT` failures from run `37671080822`), native CFOUR runs, physical GPU MLFF models, and scientific reference campaigns; release archives remain unsigned/unpublished.
2. **Workstation Queue UI Hook (`PLAN.md` Phase 3):** `topos/ui.py` and `frontend/cochem_topos_ui.py` do not yet detect `QUEUED_TO_WORKSTATION` status or tail `workstation_health.json` / `<job_id>_telemetry.json`.
3. **Open Legacy Problem Ticket (`task_9b32e1`):** `topos/calculation/orca_runner.py` and `--engine ORCA --method HF-3c` flags on `topos/ui.py` do not exist (`topos/ui.py` accepts `--port` for Streamlit launch; CLI engine execution lives in `topos/cli/__init__.py`).
4. **Method Matrix `! TightOpt` Drift:** `topos/ml_extopt.py` and `topos/goat.py` still emit `! TightOpt` shorthand and must be audited/converted to explicit 5-criterion `%geom` blocks.
5. **Residual Top-Level Namespace Directory:** Untracked/PEP-420 `cochem/` packaging hygiene and pinning the published TOPOS wheel in `CoChem-BASE` remain open.
6. **Non-Goals:** `CoChem-TOPOS` does not perform full rovibrational VPT2/SPCAT spectral fitting (`CoChem-TORQ`/`CoChem-SPYFY`), laboratory safety routing (`CoChem-EHS`), or automated publication manuscript assembly (`CoChem-SCRIBE`).

## 7. Legacy Specification Disposition (Non-Normative Archive)

All pre-Pipeline 5.0.0 SRS documents in `CoChem-TOPOS` are superseded by this canonical `docs/SRS.md` and indexed in [`docs/archive/README.md`](archive/README.md):
- Root `CoChem-TOPOS_SRS.md`, `CoChem_TOPOS_Baseline_SRS.md`, and `TOPOS_Chunk_03_SRS.md` remain at their original paths as **non-normative legacy archives** to avoid breaking path-checking tests or historical scripts.
- `.docs/CoChem-TOPOS_SRS.md` (`0.1.0-draft.1`) and `.docs/TOPOS_SRS_ACCEPTANCE.json` remain as the historical 50-clause verification trace ledger referenced by `scripts/refresh_srs_acceptance.py`.
- Legacy `.docs/ORCA_GITHUB_ACTIONS.md` and `.docs/problems/open/*Codespaces*` tickets are superseded under `CONTRA-01` (`HC-1`).
