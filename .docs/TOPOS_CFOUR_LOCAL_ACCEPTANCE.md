# Local CFOUR diagnostics on Windows 11 with WSL2

Run `scripts/accept_cfour_topos.py` inside WSL with the actual compatible
BASE/TOPOS/TORQ Python environment and a freshly completed eleven-phase BASE
audit of the workstation. The native CFOUR 2.1 installation must be authorized
by that registry. The script does not provision an engine, repair an audit,
infer nuclear data, or invoke the generic hosted controller.

Supply an explicit JSON `RunRequest` with `purpose: "matrix"`, the exact
`MATRIX_REVISION`, `calculation_environment: "local"`, CPU resources, and all
scientific inputs. The bounded controller accepts the ordinary external
recipes T3C-30min, T3C-1h, T3C-3h, T3C-12h, T3C-1d and T3C-3d. The request's
`matrix_inputs.external_protocol` must identify CFOUR 2.1, the exact row's
method/basis/core/operation, and the actual audited GENBAS path and digest.
Geometry rows require `external_resolution: "cfour-topos-cartesian-optimizer-v1"`.
The junChS row additionally needs its existing explicit CV resolution and full
coordinate chart. No simpler recipe supplies the higher composites or month row.

The caller must review the molecule, atom/fragment mapping, isotopes, gas-phase
environment and scientific choices before execution. This controller declares
`coverage_scope: "diagnostic-control"`; a molecular size or successful numerical
result does not create a source-domain release declaration. Do not invent a
reviewer, nuclear-Q source, isotope assignment or scientific reference to clear
an unmet condition.

Use a new native execution directory and a separate new evidence directory,
both outside the source checkout. For example, with real paths substituted:

```sh
/path/to/audited-environment/bin/python \
  /path/to/CoChem-TOPOS/scripts/accept_cfour_topos.py \
  --registry /path/to/actual-artifacts/Registry/cochem_system_config.json \
  --request /path/to/reviewed-local-request.json \
  --work-root /path/to/controlled-native-execution/new-case \
  --output /path/to/scientific-evidence/new-case \
  --replay
```

These paths are placeholders. Invoke the installed environment's Python;
the controller compares every imported TOPOS Python/data source with the
source tree beside the script. It rejects an old or modified installed package
even when its version string matches. The original request bytes, canonical
typed request, source inventory, actual sealed runtime, Golden Registry and
genuine adjacent `setup_summary.json` are retained before launch. Typed defaults
are visible in that canonical predeclaration; supplied scientific choices are
not replaced.

Preflight, calculation and optional replay share the original request's wall
budget. `--budget-seconds` may shorten this total, and cannot extend it. A timed
cancellation event enforces that outer deadline without changing the declared
request. Final identity checks and evidence storage may finish afterward.
Geometry convergence, tensor authority, numerical guards and native failure
conditions remain the production checks.

`--replay` calls the production component cache verifier, including fresh BASE
runtime authorization and raw correlated-property reparsing. It prohibits all
new native calculations and all RunStore checkpoints. A missing or corrupt cache
fails; the controller cannot calculate a replacement. If the budget is already
exhausted, replay reports `not-run`. Ordinary `Workflow.resume()` of an already
completed record returns the saved record early and does not itself exercise
this component reauthorization path.

T3C-1h can acquire genuine correlated dipole/EFG while remaining partial. Full
computational row completion requires the independently reviewed exact-build
operator authority and the caller's explicit sourced nuclear inputs described
in [the EFG policy](TOPOS_CFOUR_EFG_POLICY.md). A different locally built runtime,
a caller-only EFG convention, or missing nuclear-Q inputs does not acquire that
authority. The original native outcome remains retained; such a partial row
exits 3.

Only the current verified scientific RunStore snapshot is copied into `--output`
through `stage_committed_run()` and its controlled-library exclusion guard.
GENBAS, ECPDATA, renamed controlled library bytes and unrelated native scratch
remain outside the evidence directory. Retain `--work-root` privately; never
publish or recursively upload it. A failed native calculation's safe scientific
snapshot is exported when verifiable, without promoting it to success. When
export fails, the receipt records that failure and performs no raw-directory
fallback. These scientific files are not a self-contained native rerun kit.

`acceptance.json` records the actual outcome, shared budget, source/input/runtime
identity checks, full-row status, safe export and optional replay. Exit 0 means
that this one explicitly requested diagnostic passed; every unmet condition
exits 3. The receipt always sets `release_eligible: false`,
`scientific_accuracy_certified: false` and `full_matrix_campaign_certified: false`.
It cannot complete the separate 42-row matrix campaign, reference campaign,
installed-release, GPU, ORCA or hosted lifecycle gates.
