# TOPOS 0.1.0 chapter-by-chapter completion checklist

This is the current implementation assessment for all 50 requirements in the
[canonical SRS](CoChem-TOPOS_SRS.md). The [machine-readable acceptance ledger](TOPOS_SRS_ACCEPTANCE.json)
binds each requirement to specific source files, named tests, retained evidence
and outstanding native/scientific conditions. Source existence and passing refusal
or parser tests do not establish successful execution of a requested calculation.

BASE, TOPOS and TORQ are mandatory companion packages. BASE authorizes execution;
TOPOS owns these workflows, validation, review and producer/consumer contracts.
The installed TORQ importer is implemented and tested, with an explicit
`imported-awaiting-calculation` state; TORQ scientific solvers remain a separate
project. BASE's ORCA success alone does not validate TOPOS scientific pathways.

## Current acceptance scope

Genuine xTB, CREST, ABCluster and isolated MACE/AIMNet2 CPU checks have local
component evidence. Native ORCA analytic-Hessian, VPT2, correlated, GOAT and
counterpoise adapters are coded; the exact-source hosted acceptance receipts must
establish their successful calculations. GPU execution and unavailable external
engines remain separate physical acceptance conditions. No model prediction is
reported as a DFT result or calibrated uncertainty.

The complete catalog contains 140 rows, of which 44 belong to TOPOS. The
current compiler has **42 complete recipes**, plus explicitly partial compatibility branches
and two intentionally unavailable CFOUR time tiers. The conditional
CFOUR raw/relaxed-CP high-order geometry adapter is implemented, with native
correlated CFOUR 2.1 validation outstanding. **T3O-3h** implements the reviewed
separately optimized B3LYP-D4 VPT2 and transferred rotational-correction
approximation; its whole native campaign remains unverified. **T3C-1mo** Product A
now implements scalar/DBOC geometry closure and equilibrium rotors using observed
native atomic masses. The archived row does not require an arbitrary isotope
campaign; those are separate T4C products. The geometry-only compatibility branch
remains partial. The reviewed ORCA replacements preserve the original source matrix and
identify the changed F12D/RI approximation. Compilation is not native acceptance
or a transfer of benchmark accuracy. `cochem-topos matrix support` is the current
executable inventory.

The current-source [regression](evidence/TOPOS_VALIDATION_20261007T165703Z.json)
passed all five checks: **1,679 tests passed and two licensed ORCA tests were
skipped**, with unchanged source hashes. The ledger has **33 verified supported-profile
requirements, 17 awaiting physical acceptance, and no identified coding gaps**.
The [fresh mandatory-wheel installation](evidence/TOPOS_CANDIDATE07_INSTALLED_ACCEPTANCE.json)
passed actual BASE-authorized xTB, reviewed export and TORQ import; separate
[ASE I/O checks](evidence/TOPOS_CANDIDATE07_ASE_IO.json) passed without importing Torch.
The [ordinary hosted CI](evidence/TOPOS_ORDINARY_CI_37654067259.json) passed on Python
3.11 and 3.12, with 1,588 passed and 42 skipped per interpreter. The
[portable current-evidence index](evidence/TOPOS_CURRENT_INSTALLATION_EVIDENCE_INDEX.json)
links exact installation, CPU worker and BASE-authorized ABCluster receipts.
The [907-test receipt](evidence/TOPOS_VALIDATION_20261007_113240.json) remains
unchanged historical evidence, not the count for this source tree.
The [release status](TOPOS_RELEASE_STATUS.md) and [installation guide](TOPOS_INSTALLATION.md)
describe the separate release gate. An unsigned candidate is not a certified release.

## 3. System boundaries and execution contract

| Requirement | Implemented behavior and evidence | Remaining acceptance |
| --- | --- | --- |
| TOPOS-010-001 | Run/input identities, immutable attempts and retry parentage survive snapshots, resume and export. [models.py](../topos/models.py); [workflow.py](../topos/workflow.py); [test_workflow.py](../tests/v010/test_workflow.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-002 | Typed selections preserve presentation/calculation environment, engine, recipe, purpose, budget and matrix identity. [models.py](../topos/models.py); [__init__.py](../topos/cli/__init__.py); [test_interfaces.py](../tests/v010/test_interfaces.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-003 | One RunRequest/RunRecord contract drives CLI, Streamlit and BASE producer/receiver; installed provider and actual BASE xTB handoff exercised. [models.py](../topos/models.py); [__init__.py](../topos/cli/__init__.py); [test_interfaces.py](../tests/v010/test_interfaces.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-004 | Missing binaries and unsupported recipes return explicit states; no replacement potential generates a success result. [capabilities.py](../topos/capabilities.py); [engines.py](../topos/engines.py); [test_engines.py](../tests/v010/test_engines.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
## 4. Scientific inputs and fragment triage

| Requirement | Implemented behavior and evidence | Remaining acceptance |
| --- | --- | --- |
| TOPOS-010-005 | Atom inventory, explicit state/isotopes/maps/fragments/stereochemistry and finite Cartesian coordinates are validated without neutral-singlet coercion. [models.py](../topos/models.py); [chemistry.py](../topos/chemistry.py); [test_science.py](../tests/v010/test_science.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-006 | Exact overlaps are invalid, chemistry/radius-based close contacts are reviewable and coordination ambiguities remain explicit; rules record provider/version. [chemistry.py](../topos/chemistry.py); [test_science.py](../tests/v010/test_science.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-007 | Mendeleev supplies versioned isotope masses and radii; inertia records isotope convention and validates isotope substitutions. [chemistry.py](../topos/chemistry.py); [science.py](../topos/science.py); [test_science.py](../tests/v010/test_science.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-008 | Electronic states, mapped stereochemistry and isotope identities are independent of sampled observations; enantiomer and homometric regression cases remain distinct. [models.py](../topos/models.py); [science.py](../topos/science.py); [test_science.py](../tests/v010/test_science.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-009 | Specified fragment connectivity/state is preserved; distance graphs are hypotheses and unsupported coordination/proton-transfer classifications require review. [chemistry.py](../topos/chemistry.py); [test_science.py](../tests/v010/test_science.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-010 | Actual monomer-first xTB optimization and association preserve source mapping, reference states, deformation and completed-child resume evidence. [fragments.py](../topos/fragments.py); [advanced_workflow.py](../topos/advanced_workflow.py); [test_fragments.py](../tests/v010/test_fragments.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-011 | Rigid-molecule ABCluster 3.4 adapter and workflow preserve explicit atom-mapped force-field parameters, native classical-score identity, bounded execution and immutable recovery. Genuine neon/methanol sampling and quantum-refined search, deduplication, resume, review, export and monomer-first association passed focused tests. CREST/GOAT identities remain separate. The current whole suite passed; a [BASE-authorized native Ne₂ run](evidence/TOPOS_WORKER05_ABCLUSTER_BASE.json) completed rigidmol sampling, two actual xTB refinements and recovery without new processes. Its 46 artifact hashes were checked; no exhaustive-search or full-matrix claim is made. [constraints.py](../topos/constraints.py); [sampling.py](../topos/sampling.py); [test_constraints.py](../tests/v010/test_constraints.py). | Exact-source hosted ORCA calculations pending. |
## 5. Method matrix, purpose, and hardware

| Requirement | Implemented behavior and evidence | Remaining acceptance |
| --- | --- | --- |
| TOPOS-010-012 | The immutable original matrix has 140 rows, including 44 TOPOS-owned rows. All 42 available TOPOS rows now have complete explicitly selected compiled recipes; two CFOUR time tiers are source-backed unavailable-by-design. Reviewed ORCA alternatives retain distinct F12D/RI and B3LYP-D4 VPT2-transfer conventions without claiming MPQC, Molpro, F12b or inherited benchmark accuracy. The CFOUR month Product A route implements scalar/DBOC geometry corrections and equilibrium rotors using observed native atomic masses; arbitrary isotope campaigns are separate T4C products, not a prerequisite for this row. Partial compatibility branches remain explicitly labeled. Compilation is separate from complete native/GPU execution acceptance. [method_matrix.py](../topos/method_matrix.py); [matrix_workflow.py](../topos/matrix_workflow.py); [test_method_matrix.py](../tests/v010/test_method_matrix.py). | Exact-source hosted ORCA calculations pending. Version-matched external-engine execution pending. Physical GPU/model acceptance pending. |
| TOPOS-010-013 | Geometry/ensemble/workflow limits, queue accounting, retries and calibration predicates are explicit; deadlines preserve partial work without convergence claims. [budget.py](../topos/budget.py); [runtime.py](../topos/runtime.py); [test_budget.py](../tests/v010/test_budget.py). | Actual hosted queue/run timing correlation pending. |
| TOPOS-010-014 | BASE enforces audited CPU/thread/memory allocations and isolated model workers. Genuine MACE and AIMNet2 CPU inference and worker packaging have focused evidence. CUDA package profiles and device checks are implemented, but no physical GPU execution or broad hardware timing calibration is claimed. [runtime.py](../topos/runtime.py); [base_integration.py](../topos/base_integration.py); [test_runtime_allocations.py](../tests/v010/test_runtime_allocations.py). | Physical GPU/model acceptance pending. |
| TOPOS-010-015 | Native HF-3c/r2SCAN-3c recipes reject arbitrary basis/correction overrides; xTB has no fabricated basis flag. Parser/deck tests distinguish recipe from successful native execution. [engines.py](../topos/engines.py); [capabilities.py](../topos/capabilities.py); [test_engines.py](../tests/v010/test_engines.py). | Exact-source hosted ORCA calculations pending. |
| TOPOS-010-016 | Hash-bound MACE/AIMNet manifests declare source/license/training Hamiltonian/domain/units/API/dtype; actual CPU inference is implemented and tested. Committee disagreement is not calibrated accuracy; ORCA-labelled active-learning acquisition requires real matching-method calculations. Solvation and incompatible model/domain requests remain refused. [ml.py](../topos/ml.py); [engines.py](../topos/engines.py); [test_ml.py](../tests/v010/test_ml.py). | Physical GPU/model acceptance pending. |
| TOPOS-010-017 | Resolved convergence profiles and projected free gradients are explicit; only genuine engine output proves convergence; native ORCA final profile requires live acceptance. [engines.py](../topos/engines.py); [constraints.py](../topos/constraints.py); [test_engines.py](../tests/v010/test_engines.py). | Exact-source hosted ORCA calculations pending. |
| TOPOS-010-018 | Routine optimization uses Lindh/L-BFGS approximations; later physical derivative calculations are separately identified and never reuse quasi-Newton Hessians as frequencies. [engines.py](../topos/engines.py); [constraints.py](../topos/constraints.py); [test_engines.py](../tests/v010/test_engines.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
## 6. Search, refinement, and union

| Requirement | Implemented behavior and evidence | Remaining acceptance |
| --- | --- | --- |
| TOPOS-010-019 | Seeded searches preserve input/perturbations/windows/source observations, failure reasons and budget termination; discovery counts do not imply exhaustive coverage. [workflow.py](../topos/workflow.py); [sampling.py](../topos/sampling.py); [test_workflow.py](../tests/v010/test_workflow.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-020 | Rigid-molecule ABCluster 3.4 adapter and workflow preserve explicit atom-mapped force-field parameters, native classical-score identity, bounded execution and immutable recovery. Genuine neon/methanol sampling and quantum-refined search, deduplication, resume, review, export and monomer-first association passed focused tests. CREST/GOAT identities remain separate. The current whole suite passed; a [BASE-authorized native Ne₂ run](evidence/TOPOS_WORKER05_ABCLUSTER_BASE.json) completed rigidmol sampling, two actual xTB refinements and recovery without new processes. Its 46 artifact hashes were checked; no exhaustive-search or full-matrix claim is made. [sampling.py](../topos/sampling.py); [goat.py](../topos/goat.py); [test_sampling.py](../tests/v010/test_sampling.py). | Exact-source hosted ORCA calculations pending. |
| TOPOS-010-021 | Source-labelled seeds undergo common-level refinement and staged deduplication; rejected members remain. Native combined CREST screening reports lost per-input attribution honestly. [workflow.py](../topos/workflow.py); [matrix_union.py](../topos/matrix_union.py); [test_workflow.py](../tests/v010/test_workflow.py). | Exact-source hosted ORCA calculations pending. |
| TOPOS-010-022 | Restart checks state/protocol/input and completed raw artifacts; retries are immutable linked attempts. Missing electronic diagnostics are not inferred; automatic active-space/method changes are not enabled. [workflow.py](../topos/workflow.py); [correlated.py](../topos/correlated.py); [test_workflow.py](../tests/v010/test_workflow.py). | Exact-source hosted ORCA calculations pending. |
| TOPOS-010-023 | Frozen monomer references retain geometry/state/maps and rank-checked rigid/free coordinates; genuine xTB rigid-dimer optimization preserves internal distances. [constraints.py](../topos/constraints.py); [fragments.py](../topos/fragments.py); [test_constraints.py](../tests/v010/test_constraints.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-024 | Explicit 1e-6/1e-8 Angstrom profiles reject ambiguity, record distance drift and projected/residual forces, and limit claims to the allowed subspace. [constraints.py](../topos/constraints.py); [workflow.py](../topos/workflow.py); [test_constraints.py](../tests/v010/test_constraints.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
## 7. Deduplication, chirality, and spectroscopy

| Requirement | Implemented behavior and evidence | Remaining acceptance |
| --- | --- | --- |
| TOPOS-010-025 | Fingerprints and inertia are screens; final proper-rotation graph/state comparison keeps homometric collisions and ambiguous mappings. [science.py](../topos/science.py); [test_science.py](../tests/v010/test_science.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-026 | Final comparison specifies mapped atoms, proper rotations, graph permutations, RMSD units and thresholds; atoms/linear molecules and mirror cases have explicit regression tests. [science.py](../topos/science.py); [reporting.py](../topos/reporting.py); [test_science.py](../tests/v010/test_science.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-027 | MolSym proposals undergo independent isotope-labelled operation checks and tolerance sweeps; near symmetry and uncertain classification require review. [symmetry.py](../topos/symmetry.py); [reporting.py](../topos/reporting.py); [test_symmetry.py](../tests/v010/test_symmetry.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-028 | Sampled enantiomers and degeneracy have explicit achiral-environment assumptions; no universal factor two; structural IDs remain distinct. [symmetry.py](../topos/symmetry.py); [reporting.py](../topos/reporting.py); [test_symmetry.py](../tests/v010/test_symmetry.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-029 | Equilibrium rotational constants remain distinct from native ORCA VPT2 vibration-rotation corrections and explicitly supplied corrections. Literal native analytic Hessian/VPT2 adapters are implemented with method and stationarity restrictions; licensed current-source acceptance remains separate. TORQ-owned DVR/large-amplitude spectroscopy is not claimed. The conditional CFOUR raw/CP geometry bracket preserves two derived structures and their separate equilibrium rotational constants; it does not infer a confidence interval or a single composite-potential minimum. The reviewed R2 B3LYP-D4/def2-TZVPP VPT2 correction transfer is implemented with two retained geometries, native-mass inertia checks, proper-axis alignment, basin/topology guards and explicit approximate-composite labeling; its full native campaign remains unverified. The observed-native-mass month Product A route now computes equilibrium rotors from its corrected geometry with every mass observation bound to genuine native outputs; decimal-rounding intervals remain distinct from scientific model uncertainty. Native CFOUR 2.1 acceptance is pending. [symmetry.py](../topos/symmetry.py); [cfour_counterpoise.py](../topos/cfour_counterpoise.py); [test_symmetry.py](../tests/v010/test_symmetry.py). | Exact-source hosted ORCA calculations pending. Version-matched external-engine execution pending. |
## 8. Quantities, corrections, and thermodynamics

| Requirement | Implemented behavior and evidence | Remaining acceptance |
| --- | --- | --- |
| TOPOS-010-030 | Structured quantities bind units, definition, method/parser, geometry/attempt and validation to retained actual raw artifacts; absent values remain absent. [models.py](../topos/models.py); [engines.py](../topos/engines.py); [test_engines.py](../tests/v010/test_engines.py). | Exact-source hosted ORCA calculations pending. Version-matched external-engine execution pending. Physical GPU/model acceptance pending. |
| TOPOS-010-031 | Physical central-gradient Hessians preserve displaced native evidence, step-size consistency, modes and stationarity. A native ORCA analytic-Hessian reader/compiler is also implemented and refuses unsupported correlated methods. Real xTB numerical evidence, authentic parser tests and pending licensed ORCA execution are distinguished. [thermochemistry.py](../topos/thermochemistry.py); [review.py](../topos/review.py); [test_thermochemistry.py](../tests/v010/test_thermochemistry.py). | Exact-source hosted ORCA calculations pending. |
| TOPOS-010-032 | Balanced state/stoichiometry/common method comparisons separate frozen interaction, monomer deformation and binding; reference energies are independently retained. [fragments.py](../topos/fragments.py); [advanced_workflow.py](../topos/advanced_workflow.py); [test_fragments.py](../tests/v010/test_fragments.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-033 | Five-leg Boys–Bernardi raw/CP/half-CP interaction arithmetic and a separate ordinary-DLPNO R2 three-leg CP contribution preserve physical fragment states and ghost basis centers. Named-basis identity requires actual BASE exporter receipts; local contracts are tested while live ORCA acceptance remains required. The R2 three-leg contribution does not invent own-basis or deformation energies. The separately implemented conditional CFOUR adapter differentiates the relaxed-total CP surface with every ghost center displaced, retains separate raw and CP geometry branches, and restricts its declared conventional core count to physical H–Ne atoms. Native correlated CFOUR 2.1 validation remains outstanding. [counterpoise.py](../topos/counterpoise.py); [engines.py](../topos/engines.py); [test_counterpoise.py](../tests/v010/test_counterpoise.py). | Exact-source hosted ORCA calculations pending. Version-matched external-engine execution pending. |
| TOPOS-010-034 | Electronic, ZPE, enthalpy, entropy and standard-state terms are separate. RRHO, labelled frequency-floor sensitivity and native VPT2 adapters exist; constrained full-dimensional RRHO/VPT2 is refused without a defined stationary model. Genuine CREST entropy and xTB thermal workflows have local evidence; native ORCA anharmonic acceptance remains separate. [thermochemistry.py](../topos/thermochemistry.py); [advanced_workflow.py](../topos/advanced_workflow.py); [test_thermochemistry.py](../tests/v010/test_thermochemistry.py). | Exact-source hosted ORCA calculations pending. |
| TOPOS-010-035 | Stable common-protocol weights count declared degeneracy once. Publication now computes observed-window sensitivity, labels electronic versus Gibbs scores and leaves missing-state bounds unknown unless explicitly declared. [science.py](../topos/science.py); [thermochemistry.py](../topos/thermochemistry.py); [test_science.py](../tests/v010/test_science.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-036 | Structural deduplication is independent of barriers; scans do not claim saddles/minima or delete species. Automatic kinetic grouping is explicitly unavailable; no unsupported TOPOS/TORQ kinetics contract is fabricated. [capabilities.py](../topos/capabilities.py); [scans.py](../topos/scans.py); [test_scans.py](../tests/v010/test_scans.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
## 9. Persistence and recovery

| Requirement | Implemented behavior and evidence | Remaining acceptance |
| --- | --- | --- |
| TOPOS-010-037 | Schema links inputs/attempts/quantities/artifacts/review/export; immutable snapshots and validated protocol-matched resume preserve originals and rejected evidence. [models.py](../topos/models.py); [storage.py](../topos/storage.py); [test_schema_evolution.py](../tests/v010/test_schema_evolution.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-038 | Single-writer atomic snapshot commits and stable concurrent readers are exercised; code makes no unsupported SWMR claim. [storage.py](../topos/storage.py); [test_storage_publication.py](../tests/v010/test_storage_publication.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-039 | Interrupted commits/corruption/membership/duplicate attempts/concurrency/quota failures are exercised. ENOSPC uses the actual Linux /dev/full kernel error at an isolated write boundary, not physical disk exhaustion. [storage.py](../topos/storage.py); [publication.py](../topos/publication.py); [test_storage_publication.py](../tests/v010/test_storage_publication.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
## 10. Execution state and host protection

| Requirement | Implemented behavior and evidence | Remaining acceptance |
| --- | --- | --- |
| TOPOS-010-040 | Execution and scientific validation states remain separate in persisted results and UI; actual installed xTB completion retains its human-review classification rather than relabeling it validated. [models.py](../topos/models.py); [workflow.py](../topos/workflow.py); [test_workflow.py](../tests/v010/test_workflow.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-041 | Remote submission correlates exact request/commit/run IDs and safe retrieval/cancellation with credential filtering; fixture and process contracts are distinct from live GitHub execution. [dispatch.py](../topos/actions/dispatch.py); [compute_worker.py](../topos/actions/compute_worker.py); [test_remote_dispatch.py](../tests/v010/test_remote_dispatch.py). | Exact-source hosted ORCA calculations pending. Actual hosted queue/run timing correlation pending. |
| TOPOS-010-042 | Finite resource limits and owned POSIX process groups enforce timeout/cancellation and preserve prior work; Windows execution is unavailable in this supported Linux profile. [runtime.py](../topos/runtime.py); [budget.py](../topos/budget.py); [test_runtime_allocations.py](../tests/v010/test_runtime_allocations.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
## 11. Human review and TORQ handoff

| Requirement | Implemented behavior and evidence | Remaining acceptance |
| --- | --- | --- |
| TOPOS-010-043 | Review baskets expose candidate evidence and unresolved checks; actor/reason/scope and superseding decisions are append-only; manual symmetry is an annotation. [review.py](../topos/review.py); [ui.py](../topos/ui.py); [test_completion_io.py](../tests/v010/test_completion_io.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-044 | TOPOS emits a portable versioned producer manifest. The minimal TORQ companion patch now durably imports exact members and produces a real acknowledgment; actual installed-wheel xTB round trip and seven contract tests passed, with computation_performed=false. [review.py](../topos/review.py); [base_provider.py](../topos/base_provider.py); [test_completion_io.py](../tests/v010/test_completion_io.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
## 12. Publication and academic rigor

| Requirement | Implemented behavior and evidence | Remaining acceptance |
| --- | --- | --- |
| TOPOS-010-045 | Publication selects explicit reviewed eligible members backed by native/derived proof; missing values remain empty with reasons and failed observations remain in the ledger. [publication.py](../topos/publication.py); [review.py](../topos/review.py); [test_storage_publication.py](../tests/v010/test_storage_publication.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-046 | Bundle inventories inputs/raw evidence/software/model metadata/review/membership; table and figure regenerate independently, sensitivity recomputes through its recorded TOPOS environment; original artifact hashes survive outer-manifest tampering. [publication.py](../topos/publication.py); [storage.py](../topos/storage.py); [test_storage_publication.py](../tests/v010/test_storage_publication.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-047 | Actual executed attempts drive ORCA6, xTB, CREST, GOAT, ABCluster, MolSym, correlated/basis, external-engine and ML artifact citations. Configuring a method does not earn execution credit. Authors must still review scientific attribution and model/data rights; bibliography presence never proves computation. [references.py](../topos/references.py); [publication.py](../topos/publication.py); [test_completion_io.py](../tests/v010/test_completion_io.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
| TOPOS-010-048 | Local export, candidate packaging and public release are separate; no DOI or external publication is fabricated and missing rights block publication-ready claims. [publication.py](../topos/publication.py); [release.py](../topos/release.py); [test_completion_io.py](../tests/v010/test_completion_io.py). | Verified for the supported local profile by the current source-bound regression; see the linked ledger. |
## 13. Verification and acceptance

| Requirement | Implemented behavior and evidence | Remaining acceptance |
| --- | --- | --- |
| TOPOS-010-049 | Deterministic, analytical, authentic fixture, genuine xTB/CREST, installed BASE and remote evidence are distinguished; unavailable licensed/model/external engines remain unverified. [release.py](../topos/release.py); [test_nolicense_acceptance.py](../tests/v010/test_nolicense_acceptance.py). | Exact-source hosted ORCA calculations pending. Version-matched external-engine execution pending. Physical GPU/model acceptance pending. |
| TOPOS-010-050 | Receipts bind source hashes, environment, counts, logs, limitations and artifact identities; deterministic candidates and fresh wheel acceptance are implemented. Historical receipts are not current-source certification. [release.py](../topos/release.py); [test_release.py](../tests/v010/test_release.py). | Verified supported-profile regression, repeatable builds and fresh installation; full scientific certification remains separate. |

## Specific scientific boundaries

- [ABCluster](TOPOS_ABCLUSTER.md) is implemented with explicit atom parameters,
  native score provenance and independent quantum refinement. No automatic force-field
  typing or electronic-energy interpretation of classical scores is claimed.
- [ML workflows](TOPOS_ML_PATHWAYS.md) and [native sampling bridges](TOPOS_ML_EXTOPT.md)
  retain checkpoint, source, license, domain, units and execution identity. CPU
  consistency checks do not establish GPU execution or DFT accuracy.
- [Native derivatives](TOPOS_NATIVE_DERIVATIVES.md) distinguish actual analytic
  ORCA Hessians/VPT2 from physical numerical Hessians and optimizer approximations.
- [Reviewed ORCA geometries](TOPOS_REVIEWED_ORCA_GEOMETRIES.md) and the
  [F12 composite](TOPOS_ORCA_F12_COMPOSITE.md) name their replacement protocols;
  they do not claim Molpro, MPQC or F12b results.
- [R2 counterpoise](TOPOS_R2_COUNTERPOISE.md) and the reviewed
  [separately optimized B3LYP-D4 VPT2 and transferred rotational corrections](TOPOS_R2_TRANSFERRED_CORRECTION.md)
  form an explicitly selected approximate R2 composite. Its complete integration
  is coded; whole-campaign native acceptance remains pending.
- [CFOUR CP geometry](TOPOS_CFOUR_COUNTERPOISE_REVIEW.md) implements a conditional
  sixteen-component raw/relaxed-CP bracket with explicit conventional H–Ne core
  selection. Native correlated 2.1 validation is outstanding. The
  [small corrections](TOPOS_CFOUR_SMALL_CORRECTIONS.md) and
  [observed-native-mass month branch](TOPOS_MONTH_GEOMETRY_BRANCH.md) complete the
  coded default-isotopologue Product A route only when all native mass observations
  validate. Historical outputs do print numeric atomic-mass tables; they establish
  parser grammar, not current native acceptance or arbitrary-isotope support.
- [TORQ consumption evidence](evidence/TOPOS_CANDIDATE07_TORQ_CONSUMPTION.json) proves
  a durable import and acknowledgment, not a downstream spectrum or kinetic result.

The release gate checks complete requirement evidence, matrix coverage, matching
source hashes and native receipts, reproducible archives, and a clean installed
BASE → TOPOS → TORQ import flow. Outstanding physical execution conditions
remain visible blockers. This checklist does not certify all-SRS completion.
