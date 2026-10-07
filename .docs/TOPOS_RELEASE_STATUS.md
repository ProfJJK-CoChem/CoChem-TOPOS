# TOPOS 0.1.0 release status

TOPOS now has reproducible wheel/source builds, a mandatory BASE/TOPOS/TORQ
installation path and a tested noneditable installation. Full scientific release
certification remains pending. The [50-requirement acceptance ledger](TOPOS_SRS_ACCEPTANCE.json)
records the current chapter-by-chapter implementation assessments and outstanding
physical/protocol conditions. A module's presence, a compiled recipe or a refusal
test does not establish successful execution of that scientific pathway.

## What the evidence establishes

The retained [clean-wheel acceptance](evidence/TOPOS_WHEEL_INSTALLATION_20261007.json)
identifies an actual candidate wheel and dependency versions. It exercised the
installed CLI, BASE provider and Streamlit controls, performed genuine
BASE-authorized xTB 6.7.1 water optimization, reviewed the result and verified the
scientific bundle. That receipt applies to its exact wheel and source snapshot;
later source changes require a new candidate build and installation acceptance.

The [installed TORQ consumption receipt](evidence/TOPOS_TORQ_CONSUMPTION_20261007.json)
records a real producer/consumer round trip for that native xTB result. The
companion TORQ importer preserves exact reviewed geometries, maps, states and
protocols before returning its durable acknowledgment. Its state is explicitly
`imported-awaiting-calculation`; it does not claim that TORQ computed a transition
state, spectrum, reaction rate or dynamics result.

Genuine xTB and CREST scientific workflows have local evidence. Separately
identified MACE and [AIMNet2 CPU model checks](TOPOS_ML_PATHWAYS.md) exercise actual
checkpoint inference and numerical derivative/rigid-transformation consistency.
Those checks retain their scope: model predictions and committee disagreement
are not DFT results, calibrated error bars or GPU execution. ABCluster's native
rigid-molecule adapter and its explicit-parameter workflow are implemented; its
latest workflow/BASE authority checks must enter the final source-bound receipt.

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
branches, prerequisites and exact source conflicts; the count changes while
coding continues. The matrix's two intentionally unavailable CFOUR time tiers are preserved rather
than filled with an invented method. Recipe compilation is distinct from native
acceptance and from the source papers' experimental accuracy claims.

The user authorized explicitly named ORCA alternatives for the conflicting
MPQC/Molpro and F12b/F12D rows. A separately reviewed overlay preserves the
original matrix and records the changed Hamiltonian, bases and numerical
derivative protocol. These alternatives require their own implementation and
native evidence; Molpro execution and F12b benchmark accuracy are not inferred.
For R2, the user has selected separately optimized DFT VPT2 and transferred
rotational corrections as an explicitly approximate composite. The implemented
[named B3LYP-D4 variant](TOPOS_R2_TRANSFERRED_CORRECTION.md) records the additional
functional change required by native analytic-Hessian/VPT2 support; the archived
VV10-functional plan remains unavailable. Whole-campaign native acceptance of the
selected variant remains pending.
The [Molpro protocol review](TOPOS_MOLPRO_PROTOCOL_REVIEW.md) records exact official
source evidence and what it does not establish. The authorized approximation
does not claim full-dimensional VPT2 at a nonstationary constrained structure.

## Final acceptance sequence

1. Freeze the reviewed source and companion pins, then retain its complete source
   and authentic parser-fixture digests before and after the full regression run.
2. Preserve all named test results, including unavailable native tests. Refresh
   each SRS requirement only from its actual executed passing acceptance tests.
3. Supply same-source physical engine/GPU evidence for every declared condition.
   A local skip may be covered by the exact named test actually passing elsewhere,
   with a hash-checked JUnit artifact; unrelated hosted success is insufficient.
4. Build the final candidate twice, verify identical archives, and repeat the
   clean mandatory-wheel installation and real BASE → TOPOS → TORQ import flow.
5. Run the separate release gate. Unresolved scientific rows, missing engine
   evidence, stale source, incomplete SRS acceptance or absent licensing evidence
   remain visible blockers. Candidate artifact creation does not publish a release.

The [installation guide](TOPOS_INSTALLATION.md) contains concrete build, install,
upgrade, rollback, worker-silo and gate commands. The earlier
[907-test receipt](evidence/TOPOS_VALIDATION_20261007_113240.json) remains unchanged
as historical evidence. The current validation alias is refreshed only after the
new source-bound acceptance run, and never by relabeling that historical result.
