# Native GOAT acceptance workload and finite budget

The actual ORCA 6.1.1 calculation in [BASE hosted run 37638685260](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37638685260)
timed out after **1,199.832 s** of native GOAT execution. Its first global
cycle completed and the second began. It did not print the finite stopping
marker, normally terminate or produce a completed parent final ensemble.
This remains failed acceptance; no timeout is relabelled as convergence.

The native header establishes the workload:

| Native observation | Value |
|---|---:|
| Available CPUs | 2 |
| Base/final GOAT workers | 4 |
| Minimum global iterations | 3 |
| Optimizations per worker per global iteration | 15 |
| Optimizations per global iteration | 60 |
| Global iterations with a completed summary row | 1 |
| Peak process-group RSS | 505.863 MiB |

The four first-cycle worker outputs contained **232, 249, 250 and 274**
Cartesian gradient evaluations respectively, each paired with an actual SCF
convergence observation: **1,005 r2SCAN-3c gradient evaluations** in that
cycle. Three global cycles do not mean three local optimizations. The four
workers use native scheduling within the two-CPU PAL allocation; their count
does not imply four simultaneous allocated CPU cores.

The [official ORCA 6.1 GOAT manual](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/goat.html)
documents the global/local iteration distinction, the four-temperature worker
structure, the per-worker minimum and the high cost of DFT GOAT. Its
parallelization guidance explicitly recommends substantially more cores for
r2SCAN-3c searches. The hosted record shows ordinary computational workload,
not evidence of an MPI hang or an exhausted memory budget.

The acceptance script now retains the same r2SCAN-3c method, four logical
workers, deterministic native seed setting, TightOpt/TightSCF controls,
minimum/maximum three global iterations and required native stopping marker.
It first obtains an independently verified r2SCAN-3c optimized water seed;
the deliberately distorted water used for derivative checks is no longer
passed directly as the search seed. The seed run and every returned conformer's
independent same-method refinement remain in the durable evidence.

GOAT now receives an explicit cap of **4,800 s**, further capped by the remaining
total acceptance budget. The script's default total budget is **7,200 s**.
The existing hosted invocations can pass an explicit larger total budget;
BASE currently supplies 10,800 s within a 330-minute job timeout that also
contains other acceptance stages. These are finite upper bounds, not a timing
guarantee. A failed stopping criterion, native timeout or unfinished refinement
still fails the acceptance case.

`parse_goat_progress` retains actual workload fields and iteration summary rows
on both completed and interrupted native runs. Its observations do not override
process status or scientific acceptance gates. Regression evidence is the
unchanged native stdout excerpt and actual process receipt in
[`fixtures/goat_hosted_timeout`](../tests/v010/fixtures/goat_hosted_timeout),
with full-source/selection hashes and the four worker-log hashes in
[`provenance.json`](../tests/v010/fixtures/goat_hosted_timeout/provenance.json).
The associated tests check the genuine timeout and reject an iteration heading
without its completed summary row. They do not constitute a new successful
native GOAT run; the revised bounded acceptance must still run on licensed
hosted compute.

Switching the potential to xTB would test a different supported pathway.
That has not replaced this r2SCAN-3c acceptance, and no `otool_xtb` binary was
added to or changed inside the audited ORCA distribution.
