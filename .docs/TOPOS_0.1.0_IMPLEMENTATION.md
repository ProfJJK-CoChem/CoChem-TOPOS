# TOPOS 0.1.0 implementation and verification record

**Status: the current TOPOS implementation includes mandatory BASE execution, matrix planning and registered recipes, search/refinement, symmetry/reporting, thermochemistry, review and publication contracts. Supported implementation, actual execution, and scientific validation are distinct claims; conditional capabilities and remaining limits are recorded below.**

This document tracks the [0.1.0 SRS](CoChem-TOPOS_SRS.md), replacement of obsolete implementation paths, current contracts and their evidence. The [completion checklist](TOPOS_COMPLETION_CHECKLIST.md) records the current acceptance state. Historical receipts retain their original source hashes and counts and do not validate subsequent changes.

## Current implementation scope

- **Mandatory package:** [BASE integration](TOPOS_BASE_INTEGRATION.md) requires CoChem-BASE, TOPOS and TORQ together. Production execution uses BASE's checked registry and subprocess broker. The [setup helper](../scripts/setup_ecosystem.py) installs dependencies and pinned CREST, runs BASE setup, and publishes all eleven phases for the three-repository deployment. A real local setup completed with BASE status `DEGRADED_OPERATIONAL`; this status does not imply that optional licensed/GPU engines or TORQ's unfinished consumer are available.
- **Methods and execution:** the full matrix is a source-hashed typed catalog with purpose, time tier, hardware, inputs and capability constraints. [Compiled recipes](../topos/matrix_workflow.py) execute only registered complete routes; `cochem-topos matrix support` exposes unsupported routes rather than treating every catalog row as executable. CPU xTB/CREST paths have real local evidence. ORCA provisioning belongs to BASE; the user's successful BASE Actions integration does not by itself establish execution of every TOPOS ORCA recipe.
- **Scientific workflows:** monomer-first association, bounded scans, derivative-based Hessians and RRHO thermochemistry join search and frozen-fragment refinement. [Symmetry](../topos/symmetry.py) records isotope convention, verified operations and tolerance uncertainty. [Reporting](../topos/reporting.py) implements the matrix's tighter QM reporting comparisons, explicit sampled-enantiomer bookkeeping, and actual signed dipole annotations. Missing properties and unsupported physical models remain explicit.
- **Interfaces and evidence:** [remote orchestration](../topos/actions/dispatch.py) implements request/commit/job correlation, polling, cancellation and verified artifact retrieval through the BASE-backed worker. Transport tests are not a live TOPOS Actions receipt. Typed TORQ acceptance, methods/reference exports and failure recovery are implemented; downstream TORQ calculations and public deposition require their own evidence.

The [xTB/CREST pathway receipt](TOPOS_OPEN_SOURCE_VALIDATION.json), [original rebuild receipt](TOPOS_0.1.0_VALIDATION.json), and [earlier hosted-preparation receipt](ORCA_HOSTED_VALIDATION.json) remain historical evidence for their recorded revisions. Current numerical and integration checks include genuine engines, analytical/parser contracts, BASE authority tests, Streamlit AppTest interactions, and setup validation; the completion checklist and final current receipt distinguish these scopes.

## Legacy audit and retirement

The inspected legacy source is commit `ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf`. Historical documentation, scientific recommendations, council resolutions and audit receipts remain in Git and in the documentation tree. Retired source/tests remain accessible in Git history. The replacement production implementation uses the `topos` package; old API-specific tests are retired explicitly rather than hidden from collection. Deterministic unit fixtures and infrastructure failure test doubles are legitimate tests; fabricated production scientific outputs are not.

| Finding | Immutable source evidence | Consequence and disposition |
| --- | --- | --- |
| Default pytest collection excludes most tests | [pytest.ini:3](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/pytest.ini#L3) | `testpaths` selected only `test_cochem_topos_iso_recycle.py`. Restore whole-suite collection in packaging/CI; do not treat the previous selected suite as global validation. |
| Missing ORCA returns fabricated successful output and wavefunction | [escalator:1777](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/escalation/cochem_topos_escalator_exec.py#L1777), [missing-binary branch:1797](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/escalation/cochem_topos_escalator_exec.py#L1797) | Retire production dry-run output generator and fake `.gbw` bytes. Missing engine must remain unavailable. |
| EMT/Lennard-Jones/analytic calculator is relabeled xTB | [quench:719](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/mechanics/cochem_topos_quench.py#L719) | Retire automatic Hamiltonian substitution. Same method/device changes and changed chemistry require distinct policies and provenance. |
| CREST replacement executes LJ/Langevin sampling | [union:588](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/topology/cochem_topos_crest_union.py#L588) | Retire pseudo-CREST fallback; only genuine CREST invocation may carry the CREST identity. |
| He monomer energy is hardcoded; absent thermal terms become zero | [xTB parser:132](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/topos/calculation/xtb_runner.py#L132) | Replace parser with typed absent quantities and genuine source evidence; interaction energy requires compatible fragment calculations. |
| Offline registration and local execution are presented as successful Actions submission | [dispatch:235](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/topos/actions/dispatch.py#L235), [UI:91](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/topos/ui.py#L91) | Replace with explicit unavailable/queued/running/completed states and real job evidence; no local substitution for requested remote execution. |
| Missing publication energy becomes 0 Eh | [exporter:92](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/export_utils/cochem_topos_export.py#L92) | Only eligible typed results enter scientific tables; absent quantities remain absent with a reason. |
| HDF5 lock/ordinary append is mislabeled SWMR | [serializer:43](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/cascade_engine/cochem_cascade_hdf5.py#L43) | Replace with explicit writer/commit/recovery semantics; claim no live SWMR until its protocol is tested. |
| Multiple obsolete package trees disagree on schema/routing and engine identity | [master](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/core_engine/cochem_topos_master.py), [cascade](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/cascade_engine/cochem_topos_cascade_orchestrator.py), [crusher](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/topology/cochem_topos_crusher.py) | Consolidate into one typed implementation and preserve useful scientific regression intent in new tests. |
| Stale coding payload instructs restricted test collection | [coding payload](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/blob/ce6cd25b8cd7a3b44e7dd7b0f54429d5c8a971cf/artifacts/cochem_coder_payload.md) | Remove obsolete execution payloads from the active repository; historical source remains available. |

### Production retirement inventory

The following tracked paths were approved for retirement as one obsolete implementation. Useful algorithmic intent—proper rotations, isotope-aware inertia, typed quantities, fragment rigidity and transparent failure—must be demonstrated by replacement tests rather than inherited solely from old code comments.

- `cascade_engine/cochem_cascade_hdf5.py`
- `cascade_engine/cochem_topos_cascade_matrix.py`
- `cascade_engine/cochem_topos_cascade_orchestrator.py`
- `cascade_engine/cochem_topos_cascade_orchestrator_backup.py`
- `cascade_engine/cochem_topos_schemas.py`
- `core_engine/01_INGEST_GC.py`
- `core_engine/cochem_topos_crusher.py`
- `core_engine/cochem_topos_escalator.py`
- `core_engine/cochem_topos_escape.py`
- `core_engine/cochem_topos_master.py`
- `escalation/__init__.py`
- `escalation/cochem_topos_assembly.py`
- `escalation/cochem_topos_escalator_exec.py`
- `escalation/cochem_topos_iso_recycle.py`
- `export_utils/cochem_topos_export.py`
- `mechanics/__init__.py`
- `mechanics/cochem_topos_escape.py`
- `mechanics/cochem_topos_goat.py`
- `mechanics/cochem_topos_memory.py`
- `mechanics/cochem_topos_quench.py`
- `topology/__init__.py`
- `topology/cochem_topos_crest_union.py`
- `topology/cochem_topos_crusher.py`
- `topology/cochem_topos_graph.py`
- `topos/calculation/__init__.py`
- `topos/calculation/xtb_runner.py`

### Compatibility paths rebuilt in place

The former implementation in `topos/ui.py`, `topos/actions/dispatch.py`, `topos/cli/__init__.py`, `frontend/cochem_topos_ui.py`, `frontend/cochem_topos_preflight.py` and `cochem_topos_web.py` was replaced by adapters to the new typed workflow. `topos/cli/test_runner.py` now delegates to the real CLI; it does not retain the historical physical-pass harness. Root packaging removed the restrictive `pytest.ini` and obsolete root `conftest.py`; `pyproject.toml` collects the entire `tests` directory. The CI and packaging changes are reviewed with the new suite rather than the retired package names. Active `.github/copilot-instructions.md` was replaced with current contribution rules: real integration is distinguished from unit doubles, zero values remain physical, snapshot persistence is not relabeled SWMR, and Linux execution limits are explicit. Its obsolete agent roster remains in Git history.

### Test retirement inventory

These legacy tests target removed module APIs, stale source/packaging expectations, or unsupported scientific-success/fallback behavior. Their removal is not represented as those tests passing. The replacement acceptance suite must test the new API and retain relevant scientific/infrastructure regression cases. Nuclear-motion/isotope-frequency/kinetic capabilities that are not rebuilt remain explicitly unsupported.

- `tests/base/test_nuclide_resolver_periodic_table.py`
- `tests/ci_tools/test_mendeleev_ast_linter.py`
- `tests/test_cascade_matrix.py`
- `tests/test_cascade_orchestrator.py`
- `tests/test_ci_workflow.py`
- `tests/test_cochem_topos_assembly.py`
- `tests/test_cochem_topos_escalator_exec.py`
- `tests/test_cochem_topos_escape.py`
- `tests/test_cochem_topos_goat.py`
- `tests/test_cochem_topos_iso_recycle.py`
- `tests/test_cochem_topos_memory.py`
- `tests/test_cochem_topos_preflight.py`
- `tests/test_cochem_topos_quench.py`
- `tests/test_cochem_topos_ui.py`
- `tests/test_cochem_topos_wiggle.py`
- `tests/test_cochem_topos_xtb_student_journey.py`
- `tests/test_crusher.py`
- `tests/test_escape.py`
- `tests/test_export.py`
- `tests/test_gitignore.py`
- `tests/test_master.py`
- `tests/test_mendeleev_ast_linter.py`
- `tests/test_requirements.py`
- `tests/test_topology_crusher.py`
- `tests/test_topology_graph.py`
- `tests/test_topos_xtb_he2_actions_integration.py`

### Generated and stale runtime artifact retirement

Checked-in wheels, packaging metadata, coverage/runtime state and obsolete agent payloads can misrepresent the rebuilt revision. They are removed from the active tree and regenerated only by the appropriate build/runtime process. Historical council/audit documents are preserved.

- `.coverage`
- `artifacts/cochem_audit_payload.md`
- `artifacts/cochem_coder_payload.md`
- `cochem_topos.egg-info/PKG-INFO`
- `cochem_topos.egg-info/SOURCES.txt`
- `cochem_topos.egg-info/dependency_links.txt`
- `cochem_topos.egg-info/requires.txt`
- `cochem_topos.egg-info/top_level.txt`
- `dist/cochem_topos-0.1.0-py3-none-any.whl`
- `swarm_state.json`

### Retired notebooks and obsolete policy linter

The following additional paths were retired because the notebooks execute/import removed APIs and the source-policy linter enforces obsolete token/constant rules. Legitimate infrastructure test doubles are not prohibited by word matching. The replacement suite validates actual numerical and execution contracts; historical notebook outputs are not release evidence.

- `notebooks/CoChem-TOPOS_Research.ipynb`
- `notebooks/True_Research_CoChem-TOPOS.ipynb`
- `ci_tools/mendeleev_ast_linter.py`

## Requirement implementation and evidence

The status applies to declared TOPOS 0.1.0 profiles. **Implemented** means an executable contract exists within the stated domain. **Partial** identifies an absent part of a requirement; **Conditional** identifies implemented code that needs separate engine/platform or scientific evidence. An explicitly rejected unsupported route is not a completed calculation.

### Chapter coverage

| SRS chapters | Implemented replacement | Explicit limit |
| --- | --- | --- |
| 1–2: scope and sources | Versioned contracts, source-qualified governance, cited recommendations and independent matrix revision | No council ratification or universal scientific-validation claim |
| 3: execution contract | Shared UI/CLI workflow, mandatory BASE authority and correlated remote transport | A live remote scientific result needs its own verified receipt |
| 4: input and triage | State/isotope/fragment validation and monomer-first association | General protonation and coordination/stereochemical perception remain domain-limited |
| 5: methods and hardware | Full typed matrix catalog, capability-constrained planning, registered recipes, calibrated runtime-estimate contract and resource accounting | Catalog coverage is broader than compiled engine adapters; GPU/ML and advanced methods require their own adapters/evidence |
| 6: search and refinement | Jiggle–quench, CREST, common-level union, rigid refinement and conditional ORCA search recipes | Finite sampling is not exhaustive; ABCluster and automatic multireference rescue are not asserted |
| 7: identity and spectroscopy | Mapped proper rotations, point-group operation verification/sweeps, tight reporting comparisons, explicit enantiomer groups and signed dipoles | Static point groups are not molecular symmetry groups; general VPT2/DVR/large-amplitude spectroscopy is separate |
| 8: quantities and thermodynamics | Actual-gradient numerical Hessians, stationarity checks, RRHO/standard states, balanced association and conditional counterpoise orchestration | Low-frequency models are named; no invented anharmonic, rotor, solvent or kinetic quantities |
| 9: persistence | Verified immutable local snapshots, explicit membership, interruption and ENOSPC behavior | No SWMR or universal distributed-filesystem durability claim |
| 10: execution state/protection | BASE broker, local/remote lifecycle contracts, Linux resource limits and owned cancellation | Hosted TOPOS execution and other platforms need their own execution evidence |
| 11: review and handoff | Immutable review decisions, versioned payload and consumer acceptance contract | TORQ installation is mandatory; unfinished TORQ science is not completed by TOPOS |
| 12: publication | Eligible exports, methods tables, citations, inventories and missing-data/license notices | No automatic public deposition or journal-readiness certification |
| 13: verification | Analytical, parser, real-engine, BASE, filesystem and interface checks | Evidence is bounded by the actual tested source/configuration and chemical examples |

### Requirement traceability

Each row covers exactly one current `TOPOS-010-*` ID. The legacy source-qualified IDs and all 108 original proposals remain mapped in the [recommendations](TOPOS_0.1.0_RECOMMENDATIONS.md); the table does not silently redefine them.

| Requirement | Status | Implementation and executable evidence | Remaining limit / interpretation |
| --- | --- | --- | --- |
| TOPOS-010-001 | Implemented, supported scope | [models](../topos/models.py), [workflow](../topos/workflow.py), [storage](../topos/storage.py): run/attempt IDs, request and input digests, matrix/profile, schema, source hashes, parent attempts; [workflow regressions](../tests/v010/test_workflow.py). | Dirty source hashes supplement the historical Git HEAD. Identity and provenance do not certify scientific results. |
| TOPOS-010-002 | Implemented | [RunRequest](../topos/models.py), UI/CLI and [remote workflow](../topos/remote_workflow.py) preserve independent presentation/calculation/method choices; correlated Actions requests have distinct lifecycle records. | Absent controller credentials/configuration remains unavailable; no requested remote calculation becomes local execution. |
| TOPOS-010-003 | Implemented | UI, CLI and compatibility frontend call the same typed workflow; interface tests compare semantic requests and remote outcomes. | Unsupported historical APIs were retired; GUI availability alone is not engine validation. |
| TOPOS-010-004 | Implemented | [engines](../topos/engines.py), [capabilities](../topos/capabilities.py), [remote adapter](../topos/actions/dispatch.py); [engine tests](../tests/v010/test_engines.py) cover missing executables/unsupported options. | No automatic method substitution, mock production output or offline queue registration. |
| TOPOS-010-005 | Implemented, supported scope | Typed molecules validate finite coordinates, counts, symbols, isotope selectors, electron parity, mapping and fragments; [science tests](../tests/v010/test_science.py). | Mapped tetrahedral-orientation checks have focused tests; opaque CIP/R/S assignments, general stereochemical perception and all electronic-state chemistry are not inferred. |
| TOPOS-010-006 | Implemented, conservative scope | [chemistry](../topos/chemistry.py) separates coincident/malformed geometry, radius-relative suspect contacts and unsupported/unresolved chemistry. | Radius heuristics are screening hypotheses; they are not a universal bond/valence validator. |
| TOPOS-010-007 | Implemented | Dynamic `mendeleev` element/isotope/radius queries with provider provenance; [science](../topos/science.py) records mass convention and constants. | Unspecified isotope defaults to an explicitly recorded most-abundant-isotope policy, not an exact atomic-weight interpretation. |
| TOPOS-010-008 | Implemented, declared identity scope | State signatures, typed molecule identity, explicit candidate observations and proper-rotation comparison distinguish formula/charge/spin/isotope/environment. | Distinct declared protonation/state/isotope/stereochemical identities are preserved. Automatic protonation enumeration and general CIP assignment are not required by this ID and are not claimed. |
| TOPOS-010-009 | Implemented, conservative scope | Connectivity triage returns monomer, candidate weak/strong complex, or unresolved; explicit coordination and declared partitions retained. | Ambiguous coordination/metal connectivity blocks unsupported execution for review; no validated general multicenter-bond model. |
| TOPOS-010-010 | Implemented, declared fragments | [fragments](../topos/fragments.py) searches mapped monomers before the complex, retains child runs and evaluates frozen-fragment/relaxed-reference energies; [fragment tests](../tests/v010/test_fragments.py). | Fragment charge/spin/partition must be supplied consistently. Lowest sampled monomers are not certified global minima. |
| TOPOS-010-011 | Implemented, registered algorithms | Jiggle–quench, genuine CREST, their union, rigid-fragment perturbation and conditional [GOAT](../topos/goat.py) retain algorithm and confinement identity. | ABCluster and exhaustive packing are not asserted; ORCA search needs licensed engine evidence at the requested method. |
| TOPOS-010-012 | Implemented catalog/planner; conditional recipe coverage | [method matrix](../topos/method_matrix.py) validates the source-hashed catalog; [matrix workflow](../topos/matrix_workflow.py) executes registered complete recipes and exposes coverage; matrix tests validate source identities and route gates. | Rows requiring an unregistered adapter remain blocked. A parsed table or runnable plan is not evidence that all matrix calculations were executed. |
| TOPOS-010-013 | Implemented accounting and estimate contracts | [budget](../topos/budget.py) records budget scope, queue accounting, resource leases, bounded retries/cancellation; matrix planning accepts measured calibration data with uncertainty and otherwise leaves estimates unavailable. | No universal runtime/accuracy guarantee; empirical calibration is specific to hardware, chemistry and protocol. |
| TOPOS-010-014 | Implemented for local CPU | [runtime](../topos/runtime.py) limits owned process resources/threads; request/device checks reject unsupported GPU routes; engine tests exercise memory and timing limits. | GPU precision/model equivalence and distributed scheduling are unvalidated. |
| TOPOS-010-015 | Implemented inputs; conditional ORCA execution evidence | Native HF-3c/r²SCAN-3c recipes and explicit hybrid RIJCOSX/def2/J grammar preserve methods; xTB remains basis-inapplicable; [input/dipole tests](../tests/v010/test_dipoles.py). | A successful BASE ORCA installation does not certify every TOPOS recipe. Exact engine versions, complete outputs and derivatives are checked for each actual attempt. |
| TOPOS-010-016 | Unavailable | Unsupported ML/model/solvation routes are refused before scientific success; requested metadata remains in the contract. | No MACE/OFF model artifact/domain/license validation or GPU execution; no ALPB/CPCM/SMD equivalence claim. |
| TOPOS-010-017 | Implemented, explicit profiles | Native xTB profiles including derivative-appropriate extreme convergence retain thresholds and gradient checks; ORCA requires all five native convergence criteria and declared grids; rigid refinement separates free and frozen residuals. | Convergence is not molecular accuracy. Unsupported engine/grid profiles remain blocked. |
| TOPOS-010-018 | Implemented separation of optimization and frequency Hessians | Routine optimization retains supported approximate preconditioning; [advanced workflow](../topos/advanced_workflow.py) requests physical derivative Hessians only for explicit frequency/thermochemistry work. | Numerical Hessians require genuine compatible gradients; no general TS solver or speedup claim is inferred. |
| TOPOS-010-019 | Implemented, finite local search | Seeded samples, original/perturbed geometry, constraints, attempts, retained/rejected candidates and termination persist in workflow records. | Cartesian proposals can be inefficient for flexible/high-barrier systems; search counts are not exhaustive coverage. |
| TOPOS-010-020 | Implemented CREST; conditional ORCA search | [sampling](../topos/sampling.py) preserves CREST 3.0.2/xTB 6.7.1 identity, full/reduced/NCI flags and raw ensembles; [GOAT](../topos/goat.py) supplies explicit ORCA search contracts. | Live CREST successes and authentic upstream failures remain separate evidence. ORCA GOAT parser/input tests do not establish live licensed sampling; ABCluster is not implemented. |
| TOPOS-010-021 | Implemented supported union; partial wider validation | INITIAL_SEED/JIGGLE_QUENCH/CREST attribution, raw observed ensemble, explicit refinement-cap exclusions, common-level xTB refinement, chemistry checks and proper mapped comparisons. | Quantitative discovery robustness and cross-method accuracy studies remain absent; native search energies never replace refined comparison energies. |
| TOPOS-010-022 | Partial | Resume preserves prior attempts and parent identity; incomplete attempts are recorded rather than fabricated successful. | No orbital/basis restart import, automated diagnostic rescue, T1/D1/AutoCAS or multireference decision ladder. |
| TOPOS-010-023 | Implemented, explicit references | Rigid-fragment reference state, mapping, degrees of freedom and drift are recorded; monomer-first workflow generates traceable sampled references where selected. | A sampled reference is not automatically a high-level or globally optimal monomer geometry. |
| TOPOS-010-024 | Implemented for explicit profiles | Rigid retraction, intrafragment drift, free-subspace convergence and frozen residual forces; [genuine constrained workflow integration](../tests/v010/test_workflow_constraints.py); source-conflicting `mapping-2026`/`chunk3-2026` profiles remain explicit. | A converged constrained stationary point is not a full-dimensional minimum; no constrained thermal model is inferred. |
| TOPOS-010-025 | Implemented, conservative comparison | Exact input digests identify records; graph isomorphism and coordinate comparison decide candidate equivalence. | No descriptor-only identity; permutation-budget exhaustion returns unresolved and retains candidates. |
| TOPOS-010-026 | Implemented, declared comparison model | Proper Kabsch rotations, labelled graph permutations and all-atom stereo guards are tested; [reporting tests](../tests/v010/test_reporting.py) separately enforce heavy-atom RMSD, 0.05 kcal/mol energy and 0.1% ABC AND criteria after matched QM refinement. | Generation uses its documented conservative fixed screen; it is not relabeled as CREGEN dynamic thresholds. Unknown coordination/stereo remains unresolved. |
| TOPOS-010-027 | Implemented, static geometry | [symmetry](../topos/symmetry.py) independently verifies MolSym-proposed operations against isotope-labelled geometry and retains algorithm/version, tolerance sweep and uncertainty; [known-group tests](../tests/v010/test_symmetry.py). | Tolerance-sensitive labels trigger review annotations, not extra species. Static point groups do not determine permutation-inversion groups or nuclear-spin weights. |
| TOPOS-010-028 | Implemented, explicit ensemble convention | [reporting](../topos/reporting.py) distinguishes proper/improper mappings and can group two observed unit-weight enantiomers only in an explicitly achiral environment; repeated hits and pre-existing weights are not counted twice. | No unsampled universal g=2 or rotamer multiplicity is invented. Reporting groups retain original molecular identities and declare how weights enter a partition function. |
| TOPOS-010-029 | Implemented labels and supplied-correction contract | Isotope-aware Ae/Be/Ce remain equilibrium quantities. Optional supplied provenance-bearing vibration–rotation alpha values produce A0/B0/C0 only under the explicit semi-rigid unconstrained nonlinear contract. | This arithmetic does not calculate VPT2 or DVR, establish experimental scaling, or solve large-amplitude motion. Signed actual dipoles preserve axis/sign and degeneracy conventions. |
| TOPOS-010-030 | Implemented for executed/derived quantities | Typed energies, gradients, Hessians, frequencies and thermal quantities retain units, definitions, geometry/attempt references and validity. Actual dipole parsing binds the signed vector to raw-output hash and geometry. | xTB CAMM stdout components are atomic units with a Debye norm; the distinct JSON AO-density dipole is not silently substituted. Missing properties remain absent. |
| TOPOS-010-031 | Implemented, genuine derivative workflow | [thermochemistry](../topos/thermochemistry.py) computes bounded finite-difference Hessians from genuine gradients, checks stationarity, symmetry and rigid modes, and records derivative frame/provenance; real-xTB tests complement analytical contracts. | A numerical Hessian and its step-size/gradient checks establish only the declared approximation, not benchmark frequency accuracy. |
| TOPOS-010-032 | Implemented, balanced declared systems | [fragments](../topos/fragments.py) binds complex, frozen fragment and relaxed monomer calculations to compatible state/protocol/executable identities, separates interaction/binding/deformation and validates thermal association inputs. | No absent fragment energy or correction becomes zero; solvent/mixed-state processes require supported explicit models. |
| TOPOS-010-033 | Implemented arithmetic; conditional engine orchestration | [counterpoise](../topos/counterpoise.py) orchestrates explicit ORCA full-basis/ghost fragment jobs and retains signs, fragment states and inputs alongside the numerical counterpoise contract. | Requires a compatible noncomposite basis recipe and actual licensed ORCA results. Parser/input contracts are not a measured BSSE correction. |
| TOPOS-010-034 | Implemented finite-temperature harmonic profile | Actual-gradient Hessians feed stationarity/minimum validation, ideal-gas RRHO, explicit pressure/concentration standard states and named low-frequency policy; constrained thermal inputs are rejected. | Frequency-floor regularization is labelled modified-HO, not a hindered-rotor or general quasi-RRHO model. Anharmonic/large-amplitude and solvent thermodynamics remain separate capabilities. |
| TOPOS-010-035 | Implemented, declared weights and sensitivity | Common-protocol log-sum-exp weights use explicit degeneracy and quantity definitions; ensemble sensitivity reports energy-window/perturbation dependence while retaining electronic-versus-Gibbs labels. | Sensitivity analysis is not proof of conformer completeness or a universal uncertainty estimate. |
| TOPOS-010-036 | Unavailable kinetics; structural rule implemented | Structural identity remains independent of barriers/kinetics; no low-barrier deletion or automatic merge. | No NEB/TS/TST/TORQ kinetic solver or timescale-dependent group model. |
| TOPOS-010-037 | Implemented, local snapshot schema | [storage](../topos/storage.py) links versioned typed runs/attempts/candidates/artifacts and retains originals; verified resume via workflow. | HDF5 groups are an interchange representation of the typed record, not compatibility with every historic reader. |
| TOPOS-010-038 | Implemented, local filesystem | Per-run writer lock, immutable snapshot, fsync and atomic CURRENT pointer; [storage tests](../tests/v010/test_storage_publication.py). | No SWMR, network/object-store durability guarantee or arbitrary concurrent writers. |
| TOPOS-010-039 | Implemented, tested local failure scope | Verified immutable membership/digests and recovery retain prior committed snapshots; [completion I/O tests](../tests/v010/test_completion_io.py) include genuine OS ENOSPC errno behavior and failed-publication preservation. | Power loss, distributed recovery and arbitrary filesystem guarantees still require platform-specific evidence. |
| TOPOS-010-040 | Implemented | Separate execution/validation enums survive CLI/UI/storage; unavailable/partial/cancelled/failed are visible. | Numerical convergence is only protocol validation, not chemical accuracy or a full-dimensional minimum. |
| TOPOS-010-041 | Implemented transport; live remote validation conditional | BASE-backed execution retains commands/versions/resources and credential-free solver environments; [remote dispatch](../topos/actions/dispatch.py) implements authenticated commit/request/job correlation, polling, cancellation and verified receipt/snapshot retrieval. | Transport fixtures and local worker checks are distinct from a TOPOS remote scientific run. BASE ORCA evidence must be correlated with the actual TOPOS request before reuse. |
| TOPOS-010-042 | Implemented Linux scope; unavailable other platforms | Owned POSIX groups, timeout/cancellation cleanup, thread and hard memory limits; process tests. | Linux `/proc` is required for tested memory/process monitoring; Windows Job Objects remain unimplemented. |
| TOPOS-010-043 | Implemented local review | [review](../topos/review.py), CLI/UI baskets and hash-linked actor/reason/superseding decisions; explicit acceptance needed. | Actor attribution is not identity authentication or a multi-user authorization system; annotations cannot establish missing physics. |
| TOPOS-010-044 | Implemented TOPOS producer/consumer contract | Versioned exact-snapshot payload, review ledger, embedded member digests and explicit acceptance/acknowledgment checks are implemented and tested. | No claim that the unfinished external TORQ engine consumed a TOPOS ensemble or completed torsional/kinetic science; mandatory package installation alone does not establish that. |
| TOPOS-010-045 | Implemented for eligible local records | [publication](../topos/publication.py) exports selected reviewed records, verifies attempt/geometry/quantity/protocol consistency, rejects duplicate observations, and leaves missing quantities empty with reasons. | Eligibility does not establish complete sampling, method accuracy or journal readiness. |
| TOPOS-010-046 | Implemented local archive; partial wider metadata | Explicit snapshot artifact inventory, hashes, raw outputs, request/settings, candidate/review ledger and selected table recipe; bundle verification. | Selected tables and relative-energy SVG can be regenerated independently from archived inputs. License/citation metadata can remain unresolved and is reported; no FAIR certification or external repository validation. |
| TOPOS-010-047 | Implemented execution-aware metadata; author verification remains | [references](../topos/references.py) credits executed software/methods, ORCA 6, MolSym algorithm/software and actual numerical transformations; exports preserve unresolved basis/model/license items. | Bibliographic completeness and compatibility of all publication licenses still need author verification; no automatic DOI/deposition or FAIR certification is inferred. |
| TOPOS-010-048 | Implemented local boundary; deposition unavailable | Bundle state is `local-export`, `not-published`, publication-ready false; no DOI is fabricated. | No public deposit, DOI reservation, license granting, authorship approval or journal submission occurs. |
| TOPOS-010-049 | Implemented evidence separation | The current suite separates analytical/parser contracts, actual xTB/CREST calculations, genuine BASE authority, filesystem/ENOSPC behavior and Streamlit interfaces. | Live TOPOS ORCA/Actions and unsupported scientific domains need their own evidence; historical receipt counts do not apply to changed sources. |
| TOPOS-010-050 | Implemented provenance/evidence record | This traceability record, [completion checklist](TOPOS_COMPLETION_CHECKLIST.md), setup receipt, source hashes, JUnit logs and final current validation receipt identify scope and limitations. | Evidence remains specific to the tested configuration. Supported implementation is not universal method-matrix execution or experimental accuracy certification. |

## Historical baseline validation record

The baseline integrated test run collected the entire `tests` directory through `pyproject.toml`: **131 passed, 0 failed, 0 errors, 0 skipped in 76.17 seconds**, on Linux with Python **3.12.14**, pytest **9.1.1**, genuine **xTB 6.7.1** and **CREST 3.0.2**. The JUnit start timestamp is `2026-10-07T01:31:13.173092+00:00`. Statement coverage was **2,552/3,012 = 84.73%**, displayed as **85%**; branch coverage was not measured. Coverage is a code-execution metric, not scientific accuracy or full-SRS fulfillment.

| Test file | Passed cases | Evidence scope |
| --- | ---: | --- |
| `test_constraints.py` | 11 | Analytical rigid-manifold invariants and genuine xTB gradient integration |
| `test_engines.py` | 25 | Authentic xTB optimization/gradient/state tests, parser/input checks, missing-engine and bounded-process failures |
| `test_interfaces.py` | 21 | Shared contract, CLI/BASE parity, real Streamlit form interactions, safe remote-unavailable routing and export destination |
| `test_sampling.py` | 13 | Native CREST ensemble parsing, reduced-search/NCI integration and preserved authentic upstream failure |
| `test_science.py` | 24 | State/isotope/geometry/unit invariants, mapped tetrahedral orientation, stable weights and supplied-Hessian utilities |
| `test_storage_publication.py` | 29 | Real filesystem/process integrity, analytical fixtures, recovery, concurrency, mutation rejection, review and bundle eligibility |
| `test_workflow.py` | 7 | Local pipeline, actual xTB search/review/export, genuine CREST common-level refinement, cancellation and unavailable-to-real resume |
| `test_workflow_constraints.py` | 1 | Real frozen-water optimization with linked derivative proof, explicit review and verified export |
| **Total** | **131** | **No skipped case in this configured environment** |

The machine-readable [validation receipt](TOPOS_0.1.0_VALIDATION.json) records reproducibility details and persistent demonstration identities. Detailed workspace evidence is retained outside the repository:

- `/workspace/.cochem-setup/rebuild-pytest.log`: full collection, outcomes and statement-coverage table.
- `/workspace/.cochem-setup/rebuild-tests.xml`: 131 tests, zero failures/errors/skips, elapsed time and timestamp.
- `/workspace/.cochem-setup/rebuild-coverage.xml`: exact covered/valid statement counts.
- `/workspace/.cochem-setup/final-evidence.json`: persistent authentic run/export evidence, with source/artifact identity in the corresponding records.
- `/workspace/.cochem-setup/rebuilt-dist/`: successfully built 0.1.0 wheel and source distribution. Ruff checks for production/tests/scripts and `pip check` passed. The installed CLI worked from `/tmp`, and the installed UI server health endpoint responded from `/tmp`; server health alone is not scientific validation.

The baseline CI used genuine xTB and CREST and built distributions. The current [CI workflow](../.github/workflows/cochem_topos_ci.yml) and [BASE integration guide](TOPOS_BASE_INTEGRATION.md) define the current provisioning path; this historical local run does not assert that GitHub Actions executed either workflow.

### Interpretation of the historical baseline engine evidence

The xTB cases include water normal/tight/vtight optimization, an energy finite-difference check against authentic gradients, and OH−/OH-doublet charge/spin propagation. Actual workflow tests add deduplication, resume, rigid-fragment refinement and reviewed export. These are method/runtime integration checks, not experimental accuracy benchmarks. ORCA inputs/parsers are tested; no licensed ORCA execution occurred.

Genuine CREST reduced `mquick` water sampling and `mquick --nci` water-dimer sampling completed using external xTB. Full native iMTD-GC on the one-conformer water case failed in upstream genetic crossing (`Not enough structures to perform GC!`, missing `confcross_0.xyz`); TOPOS retained that failure and did not silently disable crossing. Reduced `mquick` omits native normal MD/genetic-crossing stages and carries its own algorithm label. A 45-second native ethanol run timed out with 104 observed frames retained; those observations do not establish a completed search or an eligible refined ensemble.

Analytical numerical test functions and the explicitly named `analytical-test` storage fixture verify mathematical/infrastructure behavior. They are not substituted xTB/ORCA production outputs. Tests that expect a genuine engine failure to remain a failure are successful negative tests, not successful chemical calculations. No external Actions, HPC, TORQ calculation or public deposition is certified by this suite.

## Current scientific and operational limits

The supported scientific profile includes real gas-phase xTB/CREST workflows, explicit rigid-fragment refinement, balanced association, derivative/Hessian and harmonic thermal workflows, source-qualified method-matrix recipes, conservative structural comparison, reporting annotations, review and immutable export. It does not certify exhaustive sampling, global minima, experimental accuracy, automatic absolute stereochemistry, or every advanced method appearing in the matrix.

The machine-readable catalog and planner cover more rows than the registered executable recipes. Use `cochem-topos matrix coverage` and each route's blockers to distinguish catalog ownership, complete recipe compilation, availability of actual engines, and scientific execution. ORCA is supplied by mandatory BASE and checked per attempt; licensed advanced recipes, GPU/ML/CFOUR/ABCluster extensions, general anharmonic/large-amplitude spectroscopy, kinetics and public deposition retain their stated capability/evidence limits. TORQ's scientific completion remains its own workstream.

The complete eleven-phase local package setup has a separate genuine receipt at `/workspace/.cochem-base-runtime/setup-receipt.json`; `DEGRADED_OPERATIONAL` records the absence of optional capabilities rather than full engine availability. The reproducible [setup helper](../scripts/setup_ecosystem.py) writes its own current receipt for each installation. Local success is not an automatically inherited GitHub-hosted TOPOS calculation.

Historical council/audit statements and the [historical student-journey receipt](../COCHEM-DELIVERABLE-RECEIPT-TASK-1-5-TOPOS-XTB-STUDENT-JOURNEY.json) remain history; their helium-dimer values and remote claims do not validate this revision. Historical validation receipts are immutable.

Snapshots currently copy each retained artifact into each immutable generation. This favors reviewable recovery for small local workloads but can produce quadratic storage as attempts accumulate. Content-addressed reuse, automatic storage backpressure and large-ensemble scaling remain separate validation work.
