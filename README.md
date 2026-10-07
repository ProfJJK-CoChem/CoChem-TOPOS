# CoChem-TOPOS 0.1.0

TOPOS searches and compares molecular structures, retains calculation evidence,
and produces reviewed ensembles for CoChem-TORQ. **CoChem-BASE, CoChem-TOPOS and
CoChem-TORQ form a mandatory installation package.** BASE supplies the audited
engine registry and process execution authority; TOPOS supplies the scientific
workflow. TORQ is a separate component whose implementation is still in progress.

The [SRS](.docs/CoChem-TOPOS_SRS.md) defines the requirements, and the
[implementation record](.docs/TOPOS_0.1.0_IMPLEMENTATION.md) maps them to code and
validation. Numerical completion does not establish exhaustive conformer sampling,
experimental accuracy, or publication readiness.

The [current completion status](.docs/TOPOS_COMPLETION_STATUS.md) records **907
passing local tests with zero skips**, supported routes, and the remaining matrix
implementation and live ORCA acceptance work.

## Calculation and analysis pathways

| Pathway | Implemented behavior |
|---|---|
| xTB 6.7.1 / GFN2-xTB | Real energies, analytical gradients, geometry optimization and seeded jiggle–quench on Linux CPU. |
| CREST 3.0.2 + xTB 6.7.1 | Native full/reduced/NCI sampling, common-level refinement, and union with jiggle–quench; original frames, exclusions and source attribution retained. |
| ORCA through BASE | Versioned input/parser adapters and BASE-authorized execution. GitHub provisioning reuses BASE's pinned ORCA setup action and licensed distribution. TOPOS remote execution requires its own correlated validation evidence. |
| Explicit counterpoise | Five actual ORCA energy legs, physical fragment versus ghost-basis separation, BASE-authorized native basis exports, raw/CP/half-CP energies and verified checkpoint reuse. See the [counterpoise contract](.docs/TOPOS_COUNTERPOISE.md). |
| Constrained structures | Rigid-fragment optimization with explicit convergence gates, intrafragment drift, and residual frozen-force diagnostics. |
| Monomer-first association | Separate monomer searches and complex calculations, balanced common-method interaction/binding/deformation energies, and explicit BSSE policy. |
| Frequencies and thermochemistry | Physical Hessians from actual central finite differences of engine gradients; stationary-point classification; separated ZPE, thermal enthalpy, entropy, standard-state correction and Gibbs energy. |
| Symmetry and deduplication | Isotope-aware point-group proposals with independently checked operations and tolerance sensitivity; generation/reporting stages; explicit enantiomer-grouping conditions; unresolved chemistry retained. |
| Review and export | Immutable HDF5 snapshots, scoped decision histories, versioned TORQ producer handoffs, external consumption-receipt validation, and reproducible tables/figures. |

Requests preserve the engine, method, molecular charge/spin, isotopes, constraints
and scientific purpose. Unsupported or unavailable protocols return explicit
states. A constrained stationary point is not automatically a full-dimensional
minimum; harmonic RRHO is not anharmonic spectroscopy; a single search does not
prove completeness.

CREST controls its own native random initialization; the TOPOS seed controls
TOPOS perturbations. Full CREST 3.0.2 sampling can fail in the legacy genetic
crossing stage for a single-conformer water case. TOPOS retains that failure;
`crest-mquick-v1` is a separately selected reduced protocol. Isotope-labelled CREST
dynamics remain blocked until their mass-input contract is validated. See the
[xTB/CREST guide](.docs/TOPOS_OPEN_SOURCE_PATHWAYS.md).

## Method matrix coverage

The [authoritative matrix](wiki/Method_Matrix.md) is compiled into a versioned
catalog with **140 rows**, source SHA-256 and line references, CPU/GPU allocation
checks, dependencies, capability requirements, and unresolved source conflicts.
Catalog coverage is distinct from executable recipe coverage.

The current TOPOS recipe adapters cover **15 rows**, including one conditional
derivative resolution:
`T1-10s`, `T1-1min`, `T1-1h`, `T1-3h`, `T1-12h`, `T1-3d`, `T2-10s`, `T2-30min`, `T2-1h`,
`T3O-10s`, `T3O-1min`, `T3O-30min`, `T3O-1h`, `T5-10s`, and `T5-1h`.
Of 44 TOPOS-owned rows, two are source track gaps and 27 require
additional complete recipe adapters. The remaining 96 catalog rows belong to
TORQ. Typed plans preserve those requirements and refuse execution when required
methods, inputs or adapters are absent. Native GOAT rows require the versioned
ORCA adapter and retained sampling/refinement evidence. GPU/ML, higher-level
composite recipes and TORQ spectroscopy are not made available by a catalog entry.

`T1-3h` requires verified native GOAT and CREST source ensembles and the explicit
`physical-central-gradient-hessian-v1` derivative resolution. It uses actual
r²SCAN-3c gradients to construct a numerical Hessian; the matrix's literal native
analytic `Freq` is not claimed. CREST screening loses individual input origins,
so TOPOS retains original search evidence and reports combined-union provenance
for screened frames. The complete licensed route still needs live ORCA acceptance.

```bash
cochem-topos matrix support
cochem-topos matrix list --owner TOPOS
cochem-topos matrix show T3O-30min
cochem-topos matrix plan T3O-30min --hardware hardware.json
```

A plan's time tier is not a runtime estimate. Explicit verified capabilities can
be supplied with `--capabilities capabilities.json`. Use `purpose: "matrix"`, an
exact `matrix_row_id`, the catalog's `matrix_revision`, and the required
`matrix_inputs` to run a compiled complete recipe. Direct calculation purposes
can also bind to compatible primitive matrix rows.

## Install the mandatory ecosystem

For reviewed wheels, checksums, clean installation acceptance and upgrades, use
the [installation and release guide](.docs/TOPOS_INSTALLATION.md). Candidate
archives remain distinct from a passing full release certificate.

Production setup requires Python 3.11 or newer and a Linux engine host. Check out
all three repositories, then run TOPOS's ecosystem setup helper:

```bash
python scripts/setup_ecosystem.py \
  --base-root /path/to/CoChem-BASE \
  --torq-root /path/to/CoChem-TORQ \
  --artifacts /path/outside/repositories/CoChem_Artifacts
```

The helper installs the supported CREST binary, delegates the eleven setup
phases to BASE, installs the mandatory package, and repeats BASE's audit after
installation. Follow its emitted environment/registry paths. ORCA provisioning
remains BASE's responsibility under the applicable license. No licensed executable
is distributed in TOPOS research exports.

```bash
cochem-topos doctor
cochem-topos doctor --verify-runtime --registry /path/to/Registry/cochem_system_config.json
cochem-topos capabilities
```

Installing `cochem-topos` alone does not establish production execution authority.
The default execution backend is `base`. Developers can explicitly select
`TOPOS_EXECUTION_BACKEND=development` for isolated numerical tests; this setting is
recorded and does not certify the mandatory production installation.

`TOPOS_CONFIG` selects a TOPOS JSON settings file. Its keys include `output_root`,
`executables`, `max_threads`, `max_memory_mb`, `execution_backend`,
`base_registry_path`, `remote_repository` and `remote_ref`. TOPOS's settings file
is separate from BASE's checksummed registry. Missing explicit files or malformed
settings fail. Keep run outputs outside source repositories.

## Calculate, inspect and resume

```bash
cochem-topos request-schema
cochem-topos run --request examples/water-search.json --output-root /tmp/topos-runs
cochem-topos inspect /tmp/topos-runs/RUN_ID
cochem-topos resume --run-dir /tmp/topos-runs/RUN_ID
cochem-topos receive-base /path/to/module_handoff.json --output-root /tmp/topos-runs
```

Requests use the same `RunRequest` contract in the CLI, browser and BASE-facing
Python API. Purposes include `search`, `optimize`, `energy`, `gradient`,
`frequency`, `thermochemistry`, `association` and `matrix`. Consult the schema for
explicit thermal settings, fragment states, matrix inputs, and reporting-stage
controls. Run records separate execution status from scientific validation and
retain failed attempts and missing quantities.

CLI exit codes are 0 for a completed action, 2 for invalid input/action, and 3
for incomplete/unavailable execution. Resume verifies retained evidence and
preserves completed attempts; cancellation retains completed records. A continued
invocation has a new explicit budget. Completed runs are returned without
recalculation.

The optional browser interface is launched with `topos-ui`. It exposes calculation
settings, matrix inspection, installation diagnostics, candidate review, TORQ
handoff and local export. BASE/notebooks can use:

```python
from topos.ui import submit_request
result = submit_request(payload, output_root)
```

Credentials are not scientific request metadata. Native Windows/macOS engine
execution and a general HPC scheduler adapter are not validated by this Linux
implementation.

## GitHub Actions through CoChem-BASE

[`topos_compute.yml`](.github/workflows/topos_compute.yml) provisions the mandatory
package, reuses the pinned BASE ORCA setup action when needed, and executes a
correlated TOPOS request. The client supports dispatch, polling, cancellation and
verified artifact retrieval. Configure a private controller repository and its
protected `cochem-student-tests` environment as described in the
[BASE integration guide](.docs/TOPOS_BASE_INTEGRATION.md).

The CoChem-BASE workstream's successful ORCA calculation establishes its own
integration evidence. This TOPOS workflow still needs a real hosted run with
its configured repository, secrets and environment; local tests do not establish
that it has executed on GitHub. The older standalone
[ORCA installation smoke workflow](.docs/ORCA_GITHUB_ACTIONS.md) is historical
infrastructure, separate from TOPOS's production BASE route.

## Review, TORQ handoff and research export

1. Use `basket RUN_DIR` to inspect candidate eligibility, original observations,
   unresolved chemistry and review history.
2. Use `review` to record an actor, reason and decision. Revisions must explicitly
   supersede the earlier decision. Optional scope/annotations preserve manual
   grouping without rewriting raw data.
3. Use `handoff` with accepted member IDs to freeze the current reviewed ensemble,
   then `export-handoff --destination HANDOFF.json` to export the producer contract.
4. An actual TORQ consumer must emit the exact-version consumption receipt;
   `receive-torq --receipt RECEIPT.json` validates it. The legacy `ack` command
   records only an operator's manifest receipt.
5. Use `export --destination NEW_FOLDER` and `verify-export NEW_FOLDER` for a local
   research bundle. Run `python NEW_FOLDER/regenerate.py REPRODUCED_FOLDER` to
   regenerate its selected table and relative-energy figure with standard Python.

The [handoff/export specification](.docs/TOPOS_TORQ_HANDOFF.md) defines the schemas
and validation boundaries. A TOPOS handoff does not mean TORQ consumed it, and a
consumer receipt does not prove a downstream calculation. The current legacy
TORQ loader does not yet implement this versioned contract.

Bundles retain explicit raw-artifact membership, failed/excluded observations,
units, methods, seeds, matrix/profile choices, parser/software versions, review,
citations and license issues. Missing values remain absent. ORCA-derived DATA
carry the required software citation and EULA notice/disclaimer; a proposed
bundle license does not override those terms. Export is separate from draft
deposit and public release: no DOI, publication or journal submission is created.

## Validation

```bash
TOPOS_EXECUTION_BACKEND=development python -m pytest
python -m ruff check topos frontend scripts tests setup.py cochem_topos_web.py
python -m build --outdir /tmp/topos-dist
```

Real-engine tests require the supported executables; a skipped integration test
is not chemical evidence. `TOPOS_REQUIRE_REAL_ENGINES=1` makes missing xTB/CREST
an error. BASE-authorized integration tests additionally exercise the mandatory
registry and process broker. Numerical fixtures and contract fixtures are labelled.

Persistence tests exercise corruption, interrupted commits, quotas, concurrent
runs, recovery, and actual kernel `ENOSPC` handling through isolated `/dev/full`
writes. They do not claim physical disk exhaustion or universal power-loss/network
filesystem guarantees. Snapshots retain required raw evidence and need explicit
storage planning.

See the [implementation record](.docs/TOPOS_0.1.0_IMPLEMENTATION.md),
[scientific references](.docs/TOPOS_0.1.0_REFERENCES.md), and
[risk-ranked recommendations](.docs/TOPOS_0.1.0_RECOMMENDATIONS.md) for remaining
scope and scientific limitations.
