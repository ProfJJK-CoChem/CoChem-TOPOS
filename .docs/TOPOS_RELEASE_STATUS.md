# TOPOS 0.1.0 release status

TOPOS has implementations for all **42 available TOPOS method-matrix recipes**
and a tested mandatory BASE/TOPOS/TORQ installation path. Full SRS acceptance and
scientific release certification remain **blocked**. A compiled recipe, passing
parser test, installed package, or successful individual calculation cannot
complete the remaining physical campaigns.

The original catalog has 140 rows: 44 belong to TOPOS and 96 to TORQ. The matrix
explicitly omits **T3C-10s and T3C-1min**; these are preserved as unavailable
source protocol entries. Both month-tier routes have conditional implementations.
Native CFOUR execution still needs verification.

## Verified source milestones

- At `48f2a05c7fa1dc087af6faf2b77cbaf4102f55a2`, [ordinary CI 37699227832](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/actions/runs/37699227832)
  passed on Python 3.11 and 3.12: **2,010 passed, 44 skipped, zero failures or
  errors per interpreter**. Original artifact digests, JUnits, actual checkout
  trees and BASE/TORQ pins were independently verified. Skips remain explicit.
- The same revision's fresh isolated worker passed actual CPU MACE/AIMNet,
  persistent callbacks, and ABCluster sampling with xTB refinements/recovery.
  Its reproducible wheel contains 89 source files. All eleven actual BASE setup
  phases completed; the registry retains 15 unavailable capabilities.
- The retained [6264 milestone](evidence/TOPOS_CANDIDATE14_WORKER11_6264_20261007_INDEX.json)
  has **1,995 passing configured tests and three named licensed ORCA skips**,
  plus a fresh noneditable mandatory installation, genuine BASE/xTB reviewed
  export and TORQ import acknowledgment. TORQ reported
  `imported-awaiting-calculation`, with `computation_performed=false`.
- The retained [4ed milestone](evidence/TOPOS_WORKER12_CI_4ED_20261007_INDEX.json)
  separately binds its installed-worker and ordinary CI results. These original
  receipts remain tied to their actual source revisions.

The current source additionally rejects consistently checksummed unsuccessful
Stage 0 phases. Further scientific repairs and their complete regression and
installation checks are in progress. The existing
[50-requirement ledger](TOPOS_SRS_ACCEPTANCE.json) still retains the older
`053c827` assessment; it must be rebound to the final tested source before it can
supply current-source acceptance. Its historical statuses are not a new release
claim.

## Native ORCA evidence

[Full run 37675771359](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37675771359)
tested `053c827` and failed overall: **3/5 baseline, 9/13 extended and 26/27
licensed tests passed**. Original artifacts and failures remain retained.

[Focused run 37685531027](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37685531027)
tested `73b3fb8`: **2/4 extended cases and 32/34 licensed pytest cases passed**,
with no skipped tests. DLPNO counterpoise and the F12 composite passed. Native
VPT2 completed but failed its same-level Hessian-reference guard; the R2
independent DFT reference reached its actual deadline without satisfying the
required convergence/stationarity conditions. The older four-thread fixture
failure is corrected in later source. The third native thermal acceptance test
was absent. Every original archive member and immutable snapshot was verified.

[COSX diagnostic 37700474984](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37700474984)
is testing a documented fixed numerical-grid experiment at diagnostic source
`6227e61`. It establishes no numerical outcome until native evidence is retrieved
and verified. The preceding diagnostic stopped before native execution because
its package-origin check mishandled BASE's namespace package; that failure is
retained. Neither diagnostic is full current-source acceptance.

## Remaining release conditions

Release requires the final source's full regression and installation evidence,
complete native ORCA acceptance including all named licensed tests, physical GPU
and CFOUR execution, all 42 BASE-authorized matrix rows, and deployed hosted
completion/expiry/cancellation/retrieval acceptance. The protected controller's
bootstrap and canonical-request corrections are prepared separately.

The [reference campaign](TOPOS_SCIENTIFIC_REFERENCE_CAMPAIGN.md) additionally
requires reviewed coverage for every scientific-reference obligation, with
explicit chemistry domains, observables and executed named tests. A one-point
comparison or reproducibility calibration cannot clear that condition. The
[matrix campaign](TOPOS_REVIEWED_MATRIX_CAMPAIGN.md) requires the retained genuine
BASE registry and all eleven setup reports for every actual executing worker.
Development-backend results remain diagnostic.

Reviewed ORCA substitutions and the separately optimized B3LYP-D4 VPT2 rotational
correction transfer retain their explicit scientific differences and approximate
composite classification. Numerical tolerances, time budgets and native stopping
conditions remain enforced. **No certified release, tag or publication is claimed.**
