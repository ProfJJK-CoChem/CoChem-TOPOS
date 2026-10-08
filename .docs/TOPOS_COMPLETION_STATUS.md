# TOPOS 0.1.0 implementation and student deployment status

The current student deployment is documented in the
[chapter-by-chapter review](TOPOS_STUDENT_READINESS.md) and
[installation guide](TOPOS_INSTALLATION.md). The unfiltered current
[regression](evidence/TOPOS_STUDENT_VALIDATION_20261008.json) records 2,808 passed,
42 explicitly skipped, zero failures/errors and unchanged executable source.
The current ledger binds all 50 SRS clauses to reviewed files and actual named
outcomes; 22 supported-profile clauses are verified and 28 retain scientific/native
conditions. No identified coding gaps remain in that review.

## Historical 7 October assessment

This retains the earlier `053c827` assessment. Current completion work and the
8 October provider observations are tracked in the
[release status](TOPOS_RELEASE_STATUS.md); the historical counts below do not
certify later source revisions.

TOPOS has implemented all 42 available recipe entry points and passed the
source-bound local regression and fresh BASE/TOPOS/TORQ installation checks.
**Full SRS acceptance and scientific release certification remain incomplete.**
The [50-requirement acceptance ledger](TOPOS_SRS_ACCEPTANCE.json) records
**33 verified supported-profile requirements and 17 awaiting acceptance**.
The [release status](TOPOS_RELEASE_STATUS.md) provides the detailed evidence,
scientific conditions and remaining release gates.

## Verified source and installation

The executable snapshot covered by the current regression receipts is
`053c827638b3481c5c3d645856b69d50c47b387f`. Later executable-source changes
require their own validation.

- [Local validation](evidence/TOPOS_VALIDATION_20261007T194749Z.json):
  **1,812 passed and two licensed ORCA tests skipped**, with unchanged source
  inventory before and after execution. The
  [JUnit artifact](evidence/TOPOS_CURRENT_SUITE_20261007T194749Z.xml) preserves
  individual outcomes.
- [Ordinary CI run 37675577757](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/actions/runs/37675577757):
  **1,719 passed and 42 skipped on each of Python 3.11 and 3.12**. Its
  [receipt](evidence/TOPOS_ORDINARY_CI_37675577757.json) binds the merge checkout
  to the frozen executable source by identical Git trees. Ordinary CI does not
  replace licensed native acceptance.
- [Candidate12 clean installation](evidence/TOPOS_CANDIDATE12_CLEAN_INSTALL.json)
  and [installed acceptance](evidence/TOPOS_CANDIDATE12_INSTALLED_ACCEPTANCE.json):
  real noneditable BASE/TOPOS/TORQ packages, CLI/provider/UI checks, genuine
  BASE-authorized xTB 6.7.1 water optimization, human review and scientific-bundle
  verification passed. These receipts identify the actual built wheel and
  dependencies.
- [External TORQ consumption](evidence/TOPOS_CANDIDATE12_TORQ_CONSUMPTION.json):
  the installed companion importer accepted the reviewed native xTB result and
  returned a durable acknowledgment. Its state is `imported-awaiting-calculation`;
  no TORQ transition-state, spectrum, rate or dynamics calculation is established.

Genuine xTB/CREST workflows, MACE and AIMNet2 CPU execution, and BASE-authorized
ABCluster sampling have retained evidence linked from the release status and
[installation evidence index](evidence/TOPOS_CURRENT_INSTALLATION_EVIDENCE_INDEX.json).
CPU model calculations, parser fixtures and contract checks do not establish
physical GPU execution, DFT accuracy or exhaustive sampling.

## Method-matrix coverage

| Coverage | Rows | Meaning |
| --- | ---: | --- |
| Compiled TOPOS recipes | 42 | Implemented entry points; each still requires its engines, inputs, protocol conditions and native scientific acceptance. |
| Intentionally unavailable TOPOS rows | 2 | Source-backed CFOUR time tiers `T3C-10s` and `T3C-1min`; no invented replacement recipe. |
| TORQ-owned rows | 96 | Outside TOPOS's scientific implementation ownership. |
| Full catalog | 140 | Source-hashed Version 4 matrix, including conflicts and hardware requirements. |

Run `cochem-topos matrix support` for exact rows, prerequisites, partial branches
and source conflicts. The reviewed compiler covers all available TOPOS recipes;
the former 27-adapter implementation gap is closed. Compilation does not certify
a complete native matrix campaign or the source papers' accuracy claims.
User-authorized ORCA alternatives and approximate composite protocols retain
explicit provenance and limitations in the release status.

## Native acceptance and remaining work

The earlier full [licensed run 37666938546](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37666938546)
targets executable source `65af1e0`. At this status update, its baseline stage has
failed and its extended stage is still running; its completed artifacts remain
pending. Dispatch and engine provisioning do not establish acceptance.

The separate [baseline diagnostic run 37671080822](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37671080822)
has completed with **two of five cases passing**: HF-3c energy/gradient validation
and native five-leg counterpoise. Its
[portable evidence index](evidence/TOPOS_ORCA_RUN_37671080822_EVIDENCE_INDEX.json)
retains the original acceptance receipt, verified diagnostic summary, 26-snapshot
audit and dispatch/source provenance. It tested the same TOPOS `65af1e0` through
BASE `0e52a9b4ef9b0f5c977b516c79e7b6c04dfea23b`, a workflow-only diagnostic
revision whose `src` and `scripts` trees are identical to pinned BASE `705b9d5`,
with TORQ `79fbb11`.

r2SCAN-3c thermochemistry, wB97X-V optimization and GOAT seed optimization failed:
native early-stop rules signaled convergence with declared criteria unmet, then
one-cycle restarts omitted the `Energy change` row. Strict five-criterion
convergence was therefore not established. This baseline-only diagnostic ran
neither extended acceptance nor licensed pytest. The current strict optimizer
policy and explicit one-cycle energy evidence retain every requested tolerance;
the regression receipts above cover these changes. See the
[native optimizer contract](TOPOS_ORCA_OPTIMIZER_POLICY.md).

The new full [licensed run 37675771359](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37675771359)
tests current source `053c827` through unchanged BASE `705b9d5` and TORQ `79fbb11`.
Its native outcome remains pending. Local passes do not replace that validation.

Earlier hosted native runs contain real component successes and overall failures.
Their unchanged receipts, including the
[run 37650295795 evidence index](evidence/TOPOS_ORCA_RUN_37650295795_EVIDENCE_INDEX.json),
remain historical evidence for their exact source revisions. They do not certify
the current source or cover its two local licensed skips.

Remaining acceptance requires:

1. Retrieve and diagnose the full hosted results, validate subsequent fixes,
   and obtain passing same-source native ORCA evidence for every required case.
2. Complete the 17 pending SRS assessments, including native CFOUR, physical GPU,
   full matrix campaigns and deployed queue/run correlation where required.
3. Run the release gate with source-matched physical, licensing and acceptance
   evidence. Candidate archives remain unsigned, unpublished and uncertified.

The [installation guide](TOPOS_INSTALLATION.md) documents build, installation,
upgrade, rollback and gate commands. The earlier
[907-test receipt](evidence/TOPOS_VALIDATION_20261007_113240.json) and other
historical receipts remain unchanged; current evidence is linked separately.
