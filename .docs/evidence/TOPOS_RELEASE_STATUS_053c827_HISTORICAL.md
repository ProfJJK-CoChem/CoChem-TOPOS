# TOPOS 0.1.0 release status

TOPOS now has reproducible wheel/source builds, a mandatory BASE/TOPOS/TORQ
installation path and a tested noneditable installation. Full scientific release
certification remains pending. The [50-requirement acceptance ledger](TOPOS_SRS_ACCEPTANCE.json)
records **33 verified supported-profile requirements and 17 awaiting physical
acceptance**. All available recipe entry points are implemented. Earlier failed
native ORCA runs exposed integration defects; the current fixes require fresh
native acceptance. The ledger records the current
chapter-by-chapter implementation assessments and outstanding
physical/protocol conditions. A module's presence, a compiled recipe or a refusal
test does not establish successful execution of that scientific pathway.

## What the evidence establishes

The frozen executable source is `053c827638b3481c5c3d645856b69d50c47b387f`, with
BASE `705b9d54370d5089da286a02b7a1c4afdcbafec1` and TORQ
`79fbb111125e50627a1a2c129888a45496f368d4`. The exact-source
[local validation](evidence/TOPOS_VALIDATION_20261007T194749Z.json) passed all 5
checks, including **1,812 passing tests and 2 explicitly skipped licensed ORCA
tests**; the [JUnit](evidence/TOPOS_CURRENT_SUITE_20261007T194749Z.xml) retains each outcome.
The source inventory was unchanged before and after execution. The skips remain
uncovered until the exact named tests pass with matching-source native evidence.

Ordinary [GitHub Actions run 37675577757](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/actions/runs/37675577757)
passed on Python 3.11 and 3.12: **1,719 passed and 42 skipped per interpreter**.
Its [receipt](evidence/TOPOS_ORDINARY_CI_37675577757.json) binds both jobs' actual
merge checkout to the frozen source by identical Git trees. The original artifact
ZIPs match GitHub's digests; unchanged [3.11](evidence/TOPOS_ORDINARY_CI_37675577757_PY311.xml)
and [3.12](evidence/TOPOS_ORDINARY_CI_37675577757_PY312.xml) JUnit files retain every
skip. This ordinary CI remains separate from licensed native acceptance and the
following installed-wheel checks. Earlier ordinary CI receipts remain unchanged
historical evidence for their identified source revisions.

The [candidate12 clean-install receipt](evidence/TOPOS_CANDIDATE12_CLEAN_INSTALL.json)
and [installed acceptance](evidence/TOPOS_CANDIDATE12_INSTALLED_ACCEPTANCE.json)
identify an actual twice-built wheel and the installed dependency versions. Eight
installation steps passed, including both BASE/TORQ ownership reinstall orders;
no mandatory package files overlap. Seven installed command checks and the
Streamlit render passed. The fresh noneditable environment performed genuine
BASE-authorized xTB 6.7.1 water optimization, reviewed the result and verified the
scientific bundle. Water's actual electronic energy was −5.070544054679 Eh;
the completed calculation retains its `human-review` scientific classification.
The controller wheel SHA-256 is
`66957b7780560c795119439d53ed010f15ff950571f4b6c940086dbe44e7be6b`.
The fresh controller also passed all three [ASE 3.29 I/O checks](evidence/TOPOS_CANDIDATE12_ASE_IO.json):
energy/force unit conversion, disjoint replay acceptance and reordered-frame leak
rejection. These mathematical fixtures are not DFT, GPU or training results.
Torch was not imported. The [archive audit](evidence/TOPOS_CANDIDATE12_FIXTURE_ARCHIVE.json)
verifies all 39 tracked native/parser fixture payloads byte for byte in the source
distribution, including ORCA Hessian, EnGrad, input and one-cycle convergence data.

The [installed TORQ consumption receipt](evidence/TOPOS_CANDIDATE12_TORQ_CONSUMPTION.json)
records a real producer/consumer round trip for that native xTB result. The
companion TORQ importer preserves exact reviewed geometries, maps, states and
protocols before returning its durable acknowledgment. Its state is explicitly
`imported-awaiting-calculation`; `computation_performed` is false. No TORQ
transition-state, spectrum, reaction-rate or dynamics computation is claimed.

The current isolated worker wheel was independently built twice with SHA-256
`7c5471d12c37d8912403bccfb7cafeea03d03a797ad27cc8d20aad07ad990b71`.
Its BASE-authorized [MACE receipt](evidence/TOPOS_WORKER08_MACE_CPU.json) covers
21 actual CPU frames; the [AIMNet2 receipt](evidence/TOPOS_WORKER08_AIMNET_CPU.json)
covers 75 actual CPU frames and four committee members. The
[persistent MACE receipt](evidence/TOPOS_WORKER08_MACE_PERSISTENT_CPU.json)
records three actual callbacks and clean process shutdown. All 84 worker source
files match the frozen controller. The [worker08 refresh](evidence/TOPOS_WORKER08_REFRESH.json)
retains installed-worker identities and the stable registry hash. Separately
retained [model checks](TOPOS_ML_PATHWAYS.md) exercise numerical derivative and
rigid-transformation consistency. Model predictions and committee disagreements
are not DFT results, calibrated error bars or GPU execution.

The current [BASE-authorized ABCluster receipt](evidence/TOPOS_WORKER08_ABCLUSTER_BASE.json)
records genuine rigidmol 3.4 Ne₂ sampling, two independent GFN2-xTB refinements
and verified recovery without new processes. All 46 retained native artifact
hashes were checked. The [BASE installation audit](evidence/TOPOS_WORKER08_ALL_ELEVEN.json)
completed all eleven phases with `DEGRADED_OPERATIONAL` status and explicitly
retained missing capabilities. It does not establish exhaustive sampling or an
entire matrix campaign. The [portable receipt index](evidence/TOPOS_CURRENT_INSTALLATION_EVIDENCE_INDEX.json)
maps unchanged original receipt bytes to retained copies. The candidate10 and
worker07 records and their specific index remain unchanged historical evidence.

TOPOS's licensed ORCA calculations require their own exact-source hosted evidence.
A successful BASE ORCA job does not by itself verify TOPOS's analytic Hessian,
VPT2, counterpoise, GOAT or end-to-end retrieval contracts. CUDA package metadata
and CPU model execution do not establish a physical GPU calculation. Native
CFOUR/Molpro methods likewise require their own versioned execution evidence.

The intermediate [hosted run 37638685260](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37638685260)
executed TOPOS at commit `581dc1dc0707742d5fb1f621193cfc041f901841` through
BASE `705b9d54370d5089da286a02b7a1c4afdcbafec1`. Its unchanged
[baseline receipt](evidence/TOPOS_ORCA_BASELINE_RUN_37638685260.json) records a
successful native five-leg counterpoise calculation. Its unchanged
[extended receipt](evidence/TOPOS_ORCA_EXTENDED_RUN_37638685260.json) records
successful MP2, CCSD(T), AUTOCI-CCSD(T) gradients, DLPNO-CCSD(T1), F12-MP2 and
F12-RI-MP2 calculations. The overall run failed: other cases exposed native
input/parser errors, and GOAT reached its real time limit. Subsequent fixes and
new protocols require a new hosted run; these historical passes do not certify
the current source or the complete release.

The subsequent [hosted run 37650295795](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37650295795)
has now completed and its artifacts have been retrieved. It tested TOPOS
`4cdcf3853eb839eaf05da9bdae0d4fd4a0a879bc` through the same BASE `705b9d5` commit;
it did not test the current `053c827` executable snapshot. All three acceptance
stages failed overall. Their original bytes are retained with an
[evidence index](evidence/TOPOS_ORCA_RUN_37650295795_EVIDENCE_INDEX.json):

| Stage | Actual outcome |
| --- | --- |
| [Baseline](evidence/TOPOS_ORCA_BASELINE_RUN_37650295795.json) | One of five cases passed: the native five-leg counterpoise calculation. HF-3c validation, r2SCAN-3c thermochemistry, wB97X-V optimization and GOAT refinement did not complete their required acceptance. |
| [Extended](evidence/TOPOS_ORCA_EXTENDED_RUN_37650295795.json) | Eight of thirteen cases passed. Canonical **CCSD(T)-F12D/RI** and **MP2 optimization with a separate final-gradient check** now passed, in addition to repeated MP2, CCSD(T), AUTOCI-CCSD(T), DLPNO-CCSD(T1), F12-MP2 and F12-RI-MP2 passes. Native Hessian, VPT2, DLPNO counterpoise, F12 composite and R2 composite acceptance failed. |
| [Licensed pytest receipt](evidence/TOPOS_ORCA_PYTEST_RUN_37650295795.json) and [JUnit](evidence/TOPOS_ORCA_PYTEST_RUN_37650295795.xml) | 25 passed, **two failed**, zero skipped. The two actual native tests failed at the Hessian reference optimization and VPT2 reference-Hessian stages. The passing parser/contract tests do not replace those native tests. |

The receipts retain the observed failure boundaries: optimization/convergence or
protocol validation, reference-Hessian completion, BASE's audited per-core memory
limit for basis export, and a BASE broker failure in the F12 composite. These are
diagnostic evidence for fixes and a new hosted run. A successful component does
not complete a failed composite; this run supplies neither current-source native
certification nor a passing supplement for the two local licensed skips.

The full [licensed run 37666938546](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37666938546)
targets `65af1e0`. Its baseline stage has failed and its extended stage is still
running at this update; completed artifacts remain pending. Dispatch and engine
provisioning alone do not establish scientific acceptance.

The separate [baseline diagnostic run 37671080822](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37671080822)
has completed and its artifacts have been retrieved. It tested TOPOS
`65af1e05ce505cac5911b1bfe8f985a26dd87864` and TORQ
`79fbb111125e50627a1a2c129888a45496f368d4` through diagnostic BASE
`0e52a9b4ef9b0f5c977b516c79e7b6c04dfea23b`. Only the workflow differs from
pinned BASE `705b9d54370d5089da286a02b7a1c4afdcbafec1`; the `src` and `scripts`
Git trees are identical. The
[portable evidence index](evidence/TOPOS_ORCA_RUN_37671080822_EVIDENCE_INDEX.json)
records exact hashes for the unchanged
[acceptance receipt](evidence/TOPOS_ORCA_BASELINE_RUN_37671080822.json),
[verified diagnostic summary](evidence/TOPOS_ORCA_DIAGNOSTIC_RUN_37671080822_SUMMARY.json),
[26-snapshot audit](evidence/TOPOS_ORCA_DIAGNOSTIC_RUN_37671080822_SNAPSHOTS.json)
and dispatch/source/hosted-status provenance.

**Two of five baseline cases passed:** HF-3c energy/gradient validation and native
five-leg counterpoise. r2SCAN-3c thermochemistry, wB97X-V optimization and GOAT
refinement failed at their reference or seed optimizations. Native early-stop
rules signaled convergence despite unmet declared criteria; subsequent one-cycle
restarts reported four passing gradient/step rows but omitted `Energy change`.
TOPOS therefore did not establish all five requested convergence criteria. The
baseline-only diagnostic intentionally ran neither extended acceptance nor
licensed pytest, so it does not cover the two local licensed skips or certify
the full release.

The frozen source implements `EnforceStrictConvergence` and the narrow
actual-energy evidence check for the one-cycle energy difference while retaining
the requested `TolE`. Parser and regression evidence do not establish successful
current-source native optimization; new licensed hosted acceptance remains required. The existing source also
retains separate optimizer/final-gradient validation, native Hessian frame
alignment and explicit orbital-basis mappings. No historical failure is relabeled
as a pass.

The new [licensed run 37675771359](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37675771359)
targets frozen source `053c827638b3481c5c3d645856b69d50c47b387f` through the mandatory
BASE and TORQ pins above. Dispatch and provisioning establish no scientific pass;
completed native receipts must establish every required acceptance outcome.

## Method-matrix and scientific decisions

The full source catalog has 140 rows: 44 owned by TOPOS and 96 by TORQ. Inspect
`cochem-topos matrix support` for the current compiled recipe inventory, partial
branches, prerequisites and exact source conflicts. The reviewed compiler has
42 complete TOPOS recipes;
the remaining two TOPOS rows are intentionally unavailable CFOUR time tiers and are preserved rather
than filled with an invented method. Recipe compilation is distinct from native
acceptance and from the source papers' experimental accuracy claims. The
[native basis-name mapping](TOPOS_ORCA_BASIS_MAPPING.md) preserves requested
orbital spaces within its documented element domain and rejects unavailable
fitting or CABS combinations before execution. The
[month Product A route](TOPOS_MONTH_GEOMETRY_BRANCH.md) uses directly observed
native atomic masses for its scalar/DBOC-corrected equilibrium rotors. Historical
native output does contain numeric mass tables; earlier absence claims were
incorrect. General isotope campaigns are distinct from this default-isotopologue
deliverable. Its current native CFOUR 2.1 calculations remain unverified.

The user authorized explicitly named ORCA alternatives for the conflicting
MPQC/Molpro and F12b/F12D rows. A separately reviewed overlay preserves the
original matrix and records the changed Hamiltonian, bases and numerical
derivative protocol. These implemented alternatives require their own native evidence; Molpro execution and F12b benchmark accuracy are not inferred.
For R2, the user has selected separately optimized DFT VPT2 and transferred
rotational corrections as an explicitly approximate composite. The implemented
[named B3LYP-D4 variant](TOPOS_R2_TRANSFERRED_CORRECTION.md) records the additional
functional change required by native analytic-Hessian/VPT2 support; the archived
VV10-functional plan remains unavailable. Whole-campaign native acceptance of the
selected variant remains pending.
The [Molpro protocol review](TOPOS_MOLPRO_PROTOCOL_REVIEW.md) records exact official
source evidence and what it does not establish. The authorized approximation
does not claim full-dimensional VPT2 at a nonstationary constrained structure.

## Remaining release acceptance

The source-bound regression, repeatable controller/companion/worker builds and
fresh mandatory installation are complete for the exact hashes above. The source
archive is refreshed separately to retain these documentation receipts while
requiring identical tested wheel bytes.

1. Supply same-source physical engine/GPU evidence for every declared condition.
   A local skip may be covered by the exact named test actually passing elsewhere,
   with a hash-checked JUnit artifact; unrelated hosted success is insufficient.
2. Complete the 17 pending SRS acceptance assessments from their actual evidence,
   including version-matched external engines and hosted queue/run correlation.
3. Run the separate release gate. Missing engine evidence, stale source,
   incomplete SRS acceptance or absent licensing evidence remain visible blockers.
   Candidate artifact creation does not publish a release.

The [installation guide](TOPOS_INSTALLATION.md) contains concrete build, install,
upgrade, rollback, worker-silo and gate commands. Candidate archives contain no
engine binaries or model weights and remain unsigned, unpublished and uncertified.
The earlier [907-test receipt](evidence/TOPOS_VALIDATION_20261007_113240.json) remains
unchanged historical evidence. The current validation alias now points to the
separately retained 1,812-pass run; the earlier result has not been relabeled.
