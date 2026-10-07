# ORCA native geometry convergence policy

TOPOS requests `%geom EnforceStrictConvergence true` for ordinary ORCA
optimizations and the stricter VPT2 reference optimization. This controls the
native optimizer's stopping policy. It changes neither the electronic method nor
the five requested numerical tolerances. TOPOS still requires every printed
criterion to pass and separately computes the final Cartesian gradient.

The genuine output from [hosted run 37650295795](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37650295795)
reported “The step convergence is overachieved” and announced convergence even
though the RMS gradient was 4.1450 × 10⁻⁶ Eh/bohr against the requested
3 × 10⁻⁶ threshold. The [unchanged native output](../tests/v010/fixtures/orca_fifth_hosted/incomplete-r2scan-optimization.stdout)
and [provenance](../tests/v010/fixtures/orca_fifth_hosted/provenance.json) remain
rejected evidence. They are not relabeled as converged after this input change.

The [official ORCA 6.1 manual, GOAT section](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/goat.html)
documents `EnforceStrictConvergence` as a policy of ORCA's optimizer and says it
is set to `TRUE` for GOAT to ensure equal criteria across ensemble molecules.
The manual explicitly shows the `%GEOM` setting for changing that policy.
This is documentation of an available option, not proof that a new ordinary
optimization has converged. The source was checked on 7 October 2026.

| Criterion | Ordinary optimization | VPT2 reference |
| --- | ---: | ---: |
| Energy change / Eh | 1 × 10⁻⁷ | 1 × 10⁻¹⁰ |
| Maximum gradient / Eh bohr⁻¹ | 1 × 10⁻⁵ | 1 × 10⁻⁷ |
| RMS gradient / Eh bohr⁻¹ | 3 × 10⁻⁶ | 3 × 10⁻⁸ |
| RMS displacement / bohr | 5 × 10⁻⁵ | 5 × 10⁻⁷ |
| Maximum displacement / bohr | 1 × 10⁻⁴ | 1 × 10⁻⁶ |

The [focused native diagnostic 37671080822](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37671080822)
also exposed one-cycle optimizations whose final table contains four passing
geometry criteria but no energy-change row. ORCA performs an initial energy
evaluation and a final energy evaluation after that single step. TOPOS can
establish the fifth numerical condition from those two actual native energies
only when their sections and the single-cycle calculation are unambiguous.
It preserves the literal energies, source hash, line references, requested
`TolE`, difference and conservative printed-precision bound. This is explicitly
labeled a computed energy-difference condition; no printed row is invented.

For the retained r2SCAN-3c restart, the observed absolute difference is
1.04 × 10⁻¹⁰ Eh, below its 1 × 10⁻⁷ Eh limit. The hybrid restart's difference
is 5.69370 × 10⁻⁷ Eh and still fails that same limit. Neither historical job
is retroactively certified: their separate final gradients were not run.
Ambiguous or incomplete native output cannot supply the missing condition.
The execution parser and DFT importer independently recompute the same evidence
from the retained output and exact requested profile.

The bounded same-protocol continuation remains a fallback within the original
wall-clock budget. Failed numerical conditions, unsupported missing evidence,
failed independent gradients, timeouts and cancellation cannot be promoted to
successful calculations. Every native input, output and continuation receipt
is preserved.

Current DFT-reference import reconstructs the exact required native input.
Pre-change optimizer inputs therefore do not qualify for a new import under
this policy. Their archived RunStore snapshots remain unchanged, and
gradient-only input contracts are unchanged. Source-bound native acceptance of
the new policy is required before claiming that the correction works on ORCA.
