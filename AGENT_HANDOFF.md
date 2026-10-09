# CoChem-TOPOS agent handoff — 9 October 2026

**TOPOS is not scientifically complete or release certified.** Continue from this
branch, preserve every failed result, and qualify the new code before delivering
a replacement kit. This handoff is a checkpoint requested by the user, not a
release or permission to merge.

## Start here

```bash
git fetch origin
git switch codex/workstation-qualification-20261008
git pull --ff-only
git status --short
```

This is the head branch of [TOPOS draft PR #3](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/pull/3).
The workstation also has `codex/topos-completion-20261009`; synchronize it with
the handoff head before using that local branch. Do not reset a dirty checkout.
The related [BASE draft PR #12](https://github.com/ProfJJK-CoChem/CoChem-BASE/pull/12)
is on `codex/topos-runtime-completion-20261009`.

Read the [portable evidence index](.docs/handoff/2026-10-09/evidence-index.json),
[importer review](.docs/handoff/2026-10-09/importer-review.json),
[qualification forward plan](.docs/handoff/2026-10-09/qualification-forward-plan-v6.json),
and [prospective matrix input review](.docs/handoff/2026-10-09/prospective-matrix42-v1.json).
The latter two are preparation only; unknown future pins and allocations remain
unset. The bundle manifest hashes the copied checkpoint files.

## User intent and authority

The user asked to finish CoChem-TOPOS using their Windows 11/WSL2 workstation,
check the newer GitHub work, and obtain NIST data for a suitable rigid rotor.
They subsequently requested this repository handoff. Workstation testing,
reversible repairs, and pushing the working branches are authorized. A merge,
tag, release, publication, or upload of licensed ORCA/CFOUR binaries is not
authorized by this checkpoint.

A question about the approved private GitHub repository and ORCA hosted licence
remains unanswered. Do not infer hosted licence approval from the local install.
The existing private repository `ProfJJK-CoChem/cochem_workstation_job_runner`
was found, but no matching configured workflow/variables were established.

## Source identities: keep these distinct

| Role | Last sealed revision |
| --- | --- |
| TOPOS, full workstation qualification | `c8895754e4bb430596b07a26c1e7dcbd11255c1b` |
| BASE manager/controller | `bbbcf02b4dcba86791d93905b03f9b2bccae94b8` |
| BASE scientific worker implementation | `09059f052adbe5bb8208ec68a824bd45a0cab0dc` |
| Mandatory compatible legacy TORQ | `4f323800227dbde00ffb082bd6d9e44d851e1c7a` |
| Separate modern TORQ provider | `4ce8eecba56e91e27c6abb32473b2ee4d44767c4` |

**The handoff head additionally contains two importer repairs, tests, and this
documentation.** Only the focused offline checks below cover those repairs.
No new controller, all-eleven-phase audit, full source suite, scientific
campaign, student kit, or GUI proof has been built from the handoff head.
Do not assign the sealed `c889` results to this newer commit.

At the last fresh GitHub check during handoff preparation, TOPOS main was still
`a6f763c5efce85b6cc3ed7870427f4a6686f3d5d`, and PR #3 was open and draft at
`c889`. Earlier BASE/TORQ main checks recorded `7d5b8ac06d54e9e70578115bbe8634cc1ae76cc4`
and `cbf53f57109c6842ff1ca50025c522058026bfe4`. Fetch again before continuing.

## What the newest repairs do

1. `topos/scientific_references.py` binds ORCA optimizer stdout to the exact
   recorded run/attempt/refinement stage and checks retained hash/size. A valid
   optimizer plus independent final-gradient job naturally has two files named
   `engine.stdout`; the previous basename lookup rejected that valid evidence.
   Foreign paths, traversal, duplicates, tampering and unvalidated refinement
   history still reject.
2. `topos/reference_interaction.py` accepts the intentional `human-review`
   parent state of a completed, exactly bound T5-1h matrix row. Its source,
   inputs, complete-row state and catalogue binding must match. Every existing
   validated five-leg CP, native SCF, raw deck, basis-export, energy and immutable
   receipt check remains mandatory. Standalone energy parents still require
   `validated-for-protocol`. No recorded parent status is rewritten.

The final packaged-layout check passed **42 offline tests, zero failures,
errors or skips**, in 33.04 s; Ruff and `git diff --check` passed. Root rehashed
all 81 reviewed changed files and the actual JUnit. The check includes the two
new test modules and the existing interaction-importer tests. It did not launch
chemistry. The original two positive controls failed with the old module bodies;
earlier fixture/setup failures remain in the local review history.

The 77 new fixture files are selected genuine `c889` native plaintext/data.
Unsupported fixture suffixes `.xyz`, `.bas`, `.log` are stored as `.txt`, with
their exact original locator/hash mapping in provenance. Tests reconstruct the
original names only in scratch. These parser fixtures are not fresh scientific
qualification and contain no engine binaries or model weights.
Narrow `.gitattributes` entries preserve the hash-bound fixtures and handoff
receipts byte-for-byte, including original line endings and native whitespace.

## Verified at the sealed c889 checkpoint

| Item | Actual result and scope |
| --- | --- |
| Whole source regression | 3151 named PASS; 0 fail/error/skip; Ruff and pip-check PASS; 854.25 s pytest. Source, authority and owned cleanup checks passed. |
| TOPOS public CI | [37942562100](https://github.com/ProfJJK-CoChem/CoChem-TOPOS/actions/runs/37942562100): 3019 PASS / 44 declared skips per Python 3.11/3.12, including 10 genuine xTB/stock-CREST controls per version. BASE-dependent suites were separately uncollected. |
| BASE public CI | [37942646480](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37942646480): 221 controls per OS, 225 ring checks, and 1641 Linux tests. |
| Student installation | Clean three-wheel install/ownership, both install orders, AppTest (15 selectboxes/5 buttons), actual xTB 6.7.1 water optimization, snapshot/export and legacy TORQ acknowledgement PASS. Kit assembled unsigned; production release gate BLOCKED. |
| Modern providers | Normal BASE student installation of separate TOPOS/scientific-BASE and modern TORQ environments PASS. This is an installation proof, not scientific execution. |
| Windows GUI | Actual launcher rendered the ordinary stock-CREST interface and prepared a downloadable request. No calculation was submitted in that browser observation; its server was stopped. |
| Live T9 | Actual ORCA spin rejection followed by PySCF 2.14 CAS(3,3)/NEVPT2 PASS: energy −1.514320027296539 Eh, spin 0.7500000000000163. No independent accuracy claim. |
| Cold R2 control | PASS: recognized complete SCF iteration exhaustion, one continuation using its own GBW, unchanged input/resources/deadline, actual strict final SCF and gradient gates. Not full R2. |

The software SRS ledger is **22 verified / 28 verification-pending**, with all
50 software-coverage flags checked and 185 source bindings retained. No physical
status was promoted from source tests. The latest student gate has 33 blockers.
The old delivered v1 kit/report/index and all failed attempts remain unchanged.

## Scientific failures and unfinished measurements

**Full R2 remains failed.** The genuine 5400 s allocation ended after 2263.39 s
of driver work, without timeout or owned orphans. High-level water-monomer
CCSD(T), wB97M-V/QZVPP geometry, and three-leg DLPNO-CCSD(T1) CP completed.
The independent B3LYP-D4/TZVPP reference optimization failed after three bounded
refinements: full Cartesian MAX `1.08597e-7` and RMS `4.704657040e-8` exceed
`1e-7` / `3e-8`, although the native optimizer reported all five criteria passed.
The retained original gradient is overwhelmingly a rigid-motion residual; this
diagnostic decomposition does not replace the full-gradient acceptance gate.

**Cartesian optimizer experiment also failed.** The separately predeclared
`coordsys cartesian`, `ProjectTR false`, Almloef-Hessian experiment completed in
48.58 s, with unchanged SCF, chemistry, thresholds and resources. Independent
MAX `2.20869e-7` / RMS `6.789367093e-8` were worse. No optimizer production
change was adopted. Different printed native norms do not establish that
`ProjectTR` was ignored or identify ORCA's exact reporting transformation.

**Reference-v3 finished with failure.** HF optimize, coarse/fine HF Hessians
and the genuine five-leg S66 CP completed; formic strict optimization failed
after three refinements (MAX `3.00253e-7`, RMS `1.46547814e-7`). No formic
VPT2/B0 calculation ran. The original assessment then rejected duplicate stdout;
the importer fixes are later offline repairs, not a relabeled original campaign.

Diagnostic reparsing of those unchanged native bytes gives:

- HF coarse/fine spectrum difference at most 0.110742 cm⁻¹; the resolution
  condition passes, but 3/12 NIST frequency goals fail.
- Same-thermal HF Be `[236.5248464, 5.89866484, 5.88801106]` GHz fails all
  0.1% prerequisites against `[217.0258806, 6.43136091, 6.42566319]` GHz.
- HF G `−152.11047793934227` Eh is inside its numerical envelope, but combined
  G prerequisites fail; the original source mass convention is unconfirmed.
- CP `−5.011236228439181` kcal/mol differs from S66 `−4.918` by
  `0.093236228439180`, inside the predeclared 0.1 kcal/mol numerical bound.
  This is a historical-data diagnostic; it does not clear the new-source gate.
- Failed formic endpoint Be `[78.12839757, 12.06458781, 10.45077850]` GHz is
  descriptive only, and is a different observable from experimental B0.

The independent NIST trans-formic-acid main-isotopologue ground-state values are
A0 `77512.2310 ± 0.0063`, B0 `12055.1045 ± 0.0008`, C0
`10416.1145 ± 0.0008` MHz, from Willemot et al., JPCRD 9 (1980), Table 1,
[official reprint](https://srd.nist.gov/jpcrdreprint/1.555618.pdf),
DOI `10.1063/1.555618`. Do not substitute Be for B0, transfer a correction
without its native proof, scale to the target, or widen a failed tolerance.

## Next work, in order

1. Verify this checkout and the compact evidence hashes. Recheck workstation
   process ownership and available RAM/disk before any launch. The known owned
   R2/reference/Cartesian jobs are terminal. A read-only WSL
   [process snapshot](.docs/handoff/2026-10-09/process-snapshot.json) at
   20:45 UTC (15:45 America/Chicago) found no recognized active chemistry.
   A later process snapshot may differ. Do not kill unrelated work.
2. Review the held [fixed-original-geometry grid study](.docs/handoff/2026-10-09/grid-study/proposal.json).
   It freezes three cold gradient-only legs: original DEFGRID3, denser COSX,
   denser XC+COSX; exact original 18 coordinates; 2 CPU/4096 MiB; 600 s shared,
   190 s maximum per leg. It is **unexecuted**, has no reviewed executable
   supervisor yet, and changes no production profile. Implement/review bounded
   supervision using the existing subreaper/PID+creation-time guard before GO.
   A single-point pass would not qualify optimization, VPT2 or full R2.
3. Consolidate any demonstrated numerical fix separately from these importer
   repairs. Freeze a clean new TOPOS commit; update only the manager BASE
   `scripts/module-distribution.json` TOPOS pin unless another change is justified.
   Review manager/scientific BASE equivalence and rerun its catalogue/ring checks.
4. Follow the v6 qualification plan: fresh noneditable wheels/controller/silos,
   genuine all-eleven-phase authorities, worker/payload/dependency checks,
   independently sealed native12 and ordinary whole4 bindings, then one whole
   unfiltered source run. Compute the actual new JUnit count; do not hardcode
   3151 after adding tests. Preserve old runtimes and receipts.
5. Reassess scientific protocols/compatible reference coverage honestly. The
   existing failed reference campaign cannot become current-source success.
   Any changed grid needs its own explicit numerical profile and prospective
   evidence. Do not repeat the failed Cartesian experiment without new evidence.
6. Execute the frozen 100 authentic DFT labels, then independent float64 CUDA
   fits (seeds 17 and 43, 50 epochs each). Original split is 80/10/10 with related
   groups held out; replay is 11 training + 4 validation frames. No held-out-test
   tuning, foundation-checkpoint aliasing, old one-point pilot reuse, or CPU
   fallback. All three stages are **pending** at this checkpoint.
7. The two concrete fitted checkpoint hashes are required for T5 committee
   inputs before freezing a full 42-row plan. Then perform a fresh T1-1w fit
   inside its own post-declaration RunStore and its genuine GOAT, patched CREST,
   common refinement and CREGEN. An earlier standalone fit cannot replace that
   same-run history. No future-output/backdating contract was introduced.
8. Execute genuinely declared full-row cases for all 42 available TOPOS rows,
   with reviewed 5–10-atom gas-phase noncovalent source domains, actual typed
   requests, resources and current source/BASE authority. The catalogue has
   44 TOPOS rows (two intentionally unavailable), plus 96 TORQ rows. Existing
   cold/T9/GUI/installation/reference components are not full-42 case receipts.
   The sum of nominal source-tier budgets was 166.82 days, not an ETA or an
   approved execution allocation. The prospective plan leaves all 42 finite
   workflow budgets unset; choose justified allocations prospectively and retain
   honest failures.
9. Finish the approved private hosted ORCA route after resolving the outstanding
   licence/repository question. The baseline five and extended thirteen controls
   must match repository/run/attempt/commit; public skipped CI and local chemistry
   cannot substitute. Check current-source queue/external-engine/GPU conditions,
   update the SRS through actual evidence, then rebuild student/provider/GUI
   proofs and a new delivery index. Do not merge or publish automatically.

## Workstation paths and execution constraints

The shared Windows workspace is:

```text
C:\Users\ansac\Documents\Codex\2026-10-08\codex-threads-01a113a5-0dfb-7736-b0e1-2
```

Let `W` be its `work/completion-20261009` child, using `/mnt/c/Users/...` in WSL.
Let `R` be:

```text
/home/ansac/.local/share/cochem-topos/workstation-20261008/completion-20261009
```

- Writable checkouts: `W/CoChem-TOPOS`, `W/CoChem-BASE`. The original dirty
  `D:\__CoChem\GitHub-Repo\CoChem-TOPOS` is preserved; do not reset or move it.
- Installed sealed controller: `R/base-controller-v5/controller/bin/python`.
  Frozen sources are under `R/base-controller-v5/sources` and
  `R/full-controller-v5/sources`. These are distinct from the newer Windows head.
- Native12 binding: `R/campaign-bindings-v5-native/bindings.json`, SHA
  `7e4d74129b691923964786e3172e9b92f36a1252359c8e2ec3750c6aff381655`;
  profile `R/runtime-profile-v5/env-completion-ml-v5.sh`, SHA
  `0a4100deebd45c41ce4780a282f832f2747b1d4680388c6d4fbf42d4db569941`.
  It uses the separately evidenced patched CREST for ML callbacks.
- Ordinary whole4 binding: `R/campaign-bindings-v5-whole/bindings.json`, SHA
  `4951e3865497bc2612690b995318700641e2313a56cb9bbff4def669c51d2abb`;
  profile `R/runtime-profile-v5/env-completion-whole-v3.sh`, SHA
  `e53b21c773afdddd1c41c4150f9806a84251732f1a3b8c6992154909e49688b6`.
  It uses genuine stock CREST. Apply parent affinity before the phase-1 audit.
- Registry must be exported explicitly as `COCHEM_CONFIG` after sourcing a
  profile. Clear inherited Python/global native-loader/source overrides. Keep
  the actual scoped ORCA loader; do not expose its MPI libraries globally to ML.
- Run chemistry/training **serially**: the workstation previously crashed under
  another agent. Typical native allocation is 2 CPU/4096 MiB. Observe at least
  12 GiB free RAM; check disk separately. GPU is RTX 3090, 24 GiB, one device;
  rate/bandwidth estimates remain unknown, and recorded fp64 capability is false.
  Genuine CUDA float64/no-CPU-fallback fits use explicit 8192 MiB host/VRAM limits.
- Use saved WSL scripts and `wsl.exe -- bash <script>`; avoid fragile inline
  Windows/Bash quoting. Preserve one shared deadline, exact native inputs,
  original raw output, PID+creation-time ownership, subreaper cleanup and no
  lingering descendants. Do not reclaim an unrelated process or broad directory.
- Compatible legacy TORQ and modern TORQ have different interfaces and must
  remain in their verified separate environments. Do not coinstall their
  overlapping namespaces or replace the mandatory legacy pin with latest main.
- Real CFOUR derived runtime: `R/engines/cfour-h-o-junchs-v1`, backed by the
  unchanged licensed parent. Its derived H/O jun basis inventory is finite;
  do not invent other element coverage or use the absent old shortcut path.

## Local evidence locations

The portable index records full SHA256 values for the important local receipts.
Large native snapshots, licensed binaries and model weights stay on the
workstation. Under the Windows workspace:

- `outputs/completion-20261009/full-topos-regression-v3-derived-v1/validation.json`
  and `srs-whole-execution-v1/.docs/ledger-execution.json`.
- `outputs/completion-20261009/student-release-v5/` (including the unsigned zip)
  and `managed-providers-v3/`; their 198 selected retained files were rehashed.
- `outputs/completion-20261009/r2-reprobe-cold-v2/`, `r2-full-failed-v2/`,
  `r2-cartesian-diagnostic-failed-v1/`.
- `outputs/completion-20261009/reference-campaign-v3/retention-manifest.json`:
  33,629 selected copies and 59,747 original hashes, about 587 MB. Raw original
  campaign is `R/evidence/reference-campaign-v3`.
- `W/evidence/reference-importer-proposal-v2/`: all positive baseline failures,
  candidate history, final focused checks, diagnostic values and rigid-motion
  decomposition. No original frozen source or outcome was altered.
- `W/evidence/completion-audit-v2-retry-v1/`: current audit, draft results,
  prospective matrix review and v6 forward plan.
- `W/training-inputs-v1` is **not** the plan location: the frozen inputs are
  `R/training-inputs-v1/producer-plan.json`, SHA
  `97e4cd3ca731f1974b711d7e2820cea08865446c37f04b316f6c9442ed1efaed`.
  Unexecuted v3 producer/fit wrappers and the reviewed outside supervision are
  in `W`. They pin the old runtime; make fresh forward copies for new qualification.
- Actual GUI launcher `W/Start-TOPOS-v2.ps1`, screenshot
  `W/evidence/workstation-gui-v2/prepared-request.jpg`. Launcher targets the
  sealed old installation. There is no qualified general idle-stop shortcut.

The full R2 production resume preserves failed history and can reuse accepted
components, but the old acceptance verifier expects exactly one successful
attempt and rejects retained failure plus a later success. If resuming, use a
separately labeled, history-preserving verifier; never delete/relabel the original
failed single-allocation attempt. Do not silently increase a running deadline.

## Definition of completion

The next agent should report exact source-bound software, installation, native
and independent reference results, retain failures, resolve each remaining SRS
condition with evidence, and clearly distinguish reviewable unsigned candidates
from release certification. Missing licences, failed numerical targets, partial
datasets, unexecuted plans or pending full rows are unfinished work.
