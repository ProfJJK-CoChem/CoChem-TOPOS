# TOPOS 0.1.0 implementation status — 7 October 2026

The current implementation passes its local verification suite: **907 tests,
zero failures, errors or skips**. The mandatory BASE/TOPOS/TORQ installation and
TOPOS's supported xTB/CREST workflows have real execution evidence. **Full SRS
acceptance remains incomplete:** additional matrix recipes need implementation,
and the licensed TOPOS workflows need their own live ORCA/Actions evidence.

The [chapter-by-chapter checklist](TOPOS_COMPLETION_CHECKLIST.md) covers all 50
SRS requirements. The [validation receipt](TOPOS_COMPLETION_VALIDATION.json)
records exact source hashes, commands, dependencies, outcomes and limitations.
Historical receipts remain unchanged.

## Implemented in this pass

- Production execution through BASE's checked registry and process broker,
  mandatory package setup, and a registered BASE handoff receiver that validates
  and preserves the original scientific request.
- Real jiggle–quench, CREST sampling and union workflows; common-method refinement;
  isotope-aware symmetry, deduplication, review and publication exports.
- Constrained optimization/scans, physical gradient-derived Hessians, RRHO
  thermochemistry, monomer-first association and balanced fragment energies.
- Nested workflow/ensemble/geometry deadlines and verified recovery of completed,
  partial and orphaned child jobs. Completed calculation evidence is retained.
- ORCA/GOAT and five-leg counterpoise adapters, native basis-export provenance,
  correlated Actions dispatch/retrieval/cancellation, and a dedicated licensed
  acceptance workflow. Their code and contract tests do not establish live ORCA
  success.

The retired production code that fabricated missing-engine results is replaced
by the typed `topos` package. Missing engines and unsupported scientific routes
return explicit outcomes. The [implementation record](TOPOS_0.1.0_IMPLEMENTATION.md)
preserves the retirement inventory and its original source references.

## Method-matrix coverage

| Coverage | Rows | Meaning |
| --- | ---: | --- |
| Registered TOPOS recipes | 15 | Complete orchestration adapters; actual execution still requires their engines, inputs and scientific validation. |
| Additional TOPOS recipes | 27 | Plans are cataloged, but complete execution adapters are absent. |
| Explicit TOPOS track gaps | 2 | `T3C-10s` and `T3C-1min` have no recipe in the supplied matrix. |
| TORQ-owned rows | 96 | Outside TOPOS's scientific implementation ownership. |
| Full catalog | 140 | Source-hashed Version 4 matrix, including conflicts and hardware requirements. |

Run `cochem-topos matrix support` for the exact row lists and restrictions.
The conditional `T1-3h` route requires verified native source ensembles and an
explicit numerical-Hessian resolution. It does not claim the matrix's literal
native analytic `Freq`. Native CREST screening loses individual search origins;
TOPOS preserves input evidence and reports combined-union provenance afterward.

The remaining recipes include ML/GPU, entropy, higher-level composite, CFOUR,
F12/coupled-cluster and SAPT pathways. Some source protocols also conflict.
They remain unavailable; a successful lower-cost calculation cannot fulfill them.

## Verification and limits

The complete suite ran in Python 3.12.14 with genuine xTB 6.7.1 and CREST 3.0.2
required, plus the actual installed BASE package and Stage 0 registry. It includes
analytical and parser fixtures, transport/failure tests, UI interactions and real
engine integration tests. Fixture passes are not licensed calculations or
experimental accuracy benchmarks.

Ruff, dependency consistency, actionlint for all five workflows, source/wheel
builds and an independent wheel import passed. The wheel loads the full catalog,
current request schema and BASE provider and excludes the retired legacy packages.
All checked code/test/workflow hashes remained unchanged during verification.
Retained BASE calculation snapshots and their raw artifact hashes were also
reverified. Generated packaging metadata was cleaned up; installed package
discovery and BASE authority still pass afterward.

BASE's eleven-phase setup completed with `DEGRADED_OPERATIONAL` status, with all
three repositories selected. This status retains absent optional/licensed engines
and TORQ's unfinished consumer as explicit limitations.

## Remaining acceptance work

1. Implement and validate the 27 additional TOPOS matrix recipes where their
   scientific protocols and required engine/model installations are established.
2. Run [TOPOS licensed acceptance](../.github/workflows/topos_orca_acceptance.yml)
   using BASE's ORCA distribution and the configured private controller. Local
   preflight correctly failed because ORCA is absent here. No live TOPOS Actions
   dispatch or ORCA calculation is claimed by this receipt.
3. Obtain an actual external TORQ consumption receipt when TORQ implements the
   [producer/consumer contract](TOPOS_TORQ_HANDOFF.md). Installation and TOPOS's
   receipt-validation tests do not complete TORQ's solver.

Remote queue-inclusive deadlines and non-Linux execution remain unsupported.
The declared numerical profile does not certify exhaustive sampling or universal
chemical accuracy.

Changes are present in the working tree and have not been committed or pushed.
Reusable cloud installation/startup instructions and repository configuration
were saved as a draft. Review and save that draft in environment settings, then
publish the environment to activate it; fresh-task restoration has not been
verified.
