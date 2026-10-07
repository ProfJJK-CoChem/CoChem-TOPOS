# TOPOS 0.1.0 release status

TOPOS now has reproducible wheel/source builds, a mandatory BASE/TOPOS/TORQ
installation path and a tested noneditable installation. Full scientific release
certification remains pending. The [50-requirement acceptance ledger](TOPOS_SRS_ACCEPTANCE.json)
records **33 verified supported-profile requirements and 17 awaiting physical
acceptance**, with no remaining identified coding gaps. It records the current
chapter-by-chapter implementation assessments and outstanding
physical/protocol conditions. A module's presence, a compiled recipe or a refusal
test does not establish successful execution of that scientific pathway.

## What the evidence establishes

The frozen executable source is `e811bda61dbf96f267a38fd668cd04363fcebb57`, with
BASE `705b9d54370d5089da286a02b7a1c4afdcbafec1` and TORQ
`79fbb111125e50627a1a2c129888a45496f368d4`. The exact-source
[local validation](evidence/TOPOS_VALIDATION_20261007T165703Z.json) passed all five
checks, including **1,679 passing tests and two explicitly skipped licensed ORCA
tests**; the [JUnit](evidence/TOPOS_CURRENT_SUITE_20261007T165703Z.xml) retains each
outcome. The source inventory was unchanged before and after execution.

Ordinary [GitHub Actions run 37654067259](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/actions/runs/37654067259)
passed on Python 3.11 and 3.12 at that same commit: **1,588 passed and 42 skipped
per interpreter**. Its [receipt](evidence/TOPOS_ORDINARY_CI_37654067259.json) and
[3.11](evidence/TOPOS_ORDINARY_CI_37654067259_PY311.xml)/[3.12](evidence/TOPOS_ORDINARY_CI_37654067259_PY312.xml)
JUnit files preserve the skips. This editable-install CI is separate from native
licensed acceptance and the following fresh-wheel installation.

The [candidate07 clean-install receipt](evidence/TOPOS_CANDIDATE07_CLEAN_INSTALL.json)
and [installed acceptance](evidence/TOPOS_CANDIDATE07_INSTALLED_ACCEPTANCE.json)
identify an actual twice-built wheel and dependency versions. They exercised the
installed CLI, BASE provider and Streamlit controls, performed genuine
BASE-authorized xTB 6.7.1 water optimization, reviewed the result and verified the
scientific bundle. Water's actual electronic energy was −5.070544054679 Eh;
the completed calculation retains its `human-review` scientific classification.
The controller wheel SHA-256 is
`d50261b0f0f40fbd7cd4285d85e776d1e58a3e3bbb7a80846cfc3d77f600f61f`.
The fresh controller also passed [ASE 3.29 I/O checks](evidence/TOPOS_CANDIDATE07_ASE_IO.json):
energy/force unit conversion, disjoint replay acceptance and reordered-frame leak
rejection. These are mathematical file-contract checks; no DFT, GPU or training
result is inferred. Torch was not imported in that controller check.

The [installed TORQ consumption receipt](evidence/TOPOS_CANDIDATE07_TORQ_CONSUMPTION.json)
records a real producer/consumer round trip for that native xTB result. The
companion TORQ importer preserves exact reviewed geometries, maps, states and
protocols before returning its durable acknowledgment. Its state is explicitly
`imported-awaiting-calculation`; it does not claim that TORQ computed a transition
state, spectrum, reaction rate or dynamics result.

Genuine xTB and CREST scientific workflows have local evidence. The current
isolated worker wheel was independently built twice with SHA-256
`9fd785020e4dbb0007d476d574bcd414717359d55293064ddc3abf5235c2e216`.
Its BASE-authorized [MACE receipt](evidence/TOPOS_WORKER05_MACE_CPU.json) covers
21 actual CPU frames; the [AIMNet2 receipt](evidence/TOPOS_WORKER05_AIMNET_CPU.json)
covers 75 actual CPU frames and four committee members. The
[persistent MACE receipt](evidence/TOPOS_WORKER05_MACE_PERSISTENT_CPU.json)
records three actual callbacks and clean process shutdown. All 82 worker source
files match the frozen controller. Separately retained [model checks](TOPOS_ML_PATHWAYS.md)
exercise numerical derivative and rigid-transformation consistency. These model
predictions and committee disagreements are not DFT results, calibrated error
bars or GPU execution.

The current [BASE-authorized ABCluster receipt](evidence/TOPOS_WORKER05_ABCLUSTER_BASE.json)
records genuine rigidmol 3.4 Ne₂ sampling, two independent GFN2-xTB refinements
and verified recovery without new processes. All 46 retained native artifact
hashes were checked. It does not establish exhaustive sampling or an entire
matrix campaign. The [portable receipt index](evidence/TOPOS_CURRENT_INSTALLATION_EVIDENCE_INDEX.json)
maps unchanged original receipt bytes to retained copies; absolute paths inside
those originals remain historical execution provenance.

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

## Method-matrix and scientific decisions

The full source catalog has 140 rows: 44 owned by TOPOS and 96 by TORQ. Inspect
`cochem-topos matrix support` for the current compiled recipe inventory, partial
branches, prerequisites and exact source conflicts. The reviewed compiler has
42 complete TOPOS recipes;
the remaining two TOPOS rows are intentionally unavailable CFOUR time tiers and are preserved rather
than filled with an invented method. Recipe compilation is distinct from native
acceptance and from the source papers' experimental accuracy claims. The
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
separately retained 1,679-pass run; the earlier result has not been relabeled.
