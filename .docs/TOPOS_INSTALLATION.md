# Installing and upgrading the mandatory CoChem package

TOPOS 0.1.0 is distributed as a Python wheel and source archive. Its mandatory
package versions are **CoChem-BASE 1.0.0, CoChem-TOPOS 0.1.0 and CoChem-TORQ
0.1.0**, on Python 3.11 or newer. Native calculation acceptance currently targets
Linux CPU. Installing a package does not establish an audited engine allocation,
complete method-matrix coverage, or downstream TORQ scientific readiness.

The current build tooling prepares **unsigned candidates**. It does not create a
GitHub Release, publish to PyPI, or assert final release certification. Inspect
`release-gate.json`: only `release_certified: true` records a passing full release
gate. Missing scientific evidence and source conflicts remain blockers.

## Obtain the complete package set

Use the reviewed private candidate artifact prepared by
[`topos_release.yml`](../.github/workflows/topos_release.yml), or build from the
reviewed source revisions using the commands below. The download should contain:

- The TOPOS wheel, source archive, `distribution-manifest.json` and `SHA256SUMS`.
- A wheelhouse containing the exact three mandatory distributions and its own
  `SHA256SUMS`.
- Installed-package and scientific validation receipts, plus the separate release
  gate report. A successful archive build alone is insufficient.

Do not let a public package index choose similarly named CoChem dependencies.
The installer passes the reviewed BASE, TOPOS and TORQ wheel paths explicitly.
Third-party Python dependencies use the configured package index; the actual
resolved names, versions, metadata hashes and exact-version constraints are
retained by clean installation acceptance.

Verify the downloaded bytes in each directory containing `SHA256SUMS`:

```bash
sha256sum --check SHA256SUMS
```

These checks compare bytes to the supplied manifest. They are not a digital
signature for an unsigned candidate. Keep the reviewed source identities and
artifact hashes together.

## Install into a fresh BASE-managed environment

Unpack the TOPOS source archive. Its `scripts/setup_ecosystem.py` is the installer;
the wheel is the actual noneditable installed application. Provide the reviewed
BASE and TORQ source roots needed by BASE's setup service, and the complete
wheelhouse:

```bash
python scripts/setup_ecosystem.py \
  --base-root /path/to/reviewed/CoChem-BASE \
  --torq-root /path/to/reviewed/CoChem-TORQ \
  --wheelhouse /path/to/reviewed/wheelhouse \
  --artifacts /path/outside/sources/CoChem-0.1.0-runtime
```

The artifacts directory must be new and outside all source roots. The installer
checks wheel checksums and exclusive installed-file ownership before running
pip. It provisions pinned CREST, delegates engine discovery and setup to BASE,
installs all three explicit wheels, resolves dependencies, runs all eleven BASE
audit phases and checks the resulting registry. Source-root import overrides are
removed for the final installed-package validation. ORCA is provisioned by BASE's
licensed workflow separately; no ORCA binary is included in these downloads.

The release workflow pins the companion BASE packaging revision
`705b9d54370d5089da286a02b7a1c4afdcbafec1`. The original BASE 1.0.0 source revision
`c8d33ac68d4d77f9035d1dbb8ec7e0c3ca52ec86`
duplicates four installed `Libraries` files owned by TORQ. The pinned companion
BASE revision removes that duplicate wheel ownership. The installer
refuses the conflicting original wheel set. TOPOS itself no longer distributes
the `frontend` package owned by BASE. Source-tree compatibility shims do not belong
in the installed TOPOS wheel.

Activate the resulting environment and select its audited registry:

```bash
source /path/outside/sources/CoChem-0.1.0-runtime/ui-env/bin/activate
unset PYTHONPATH COCHEM_BASE_ROOT COCHEM_TOPOS_ROOT COCHEM_TORQ_ROOT
export COCHEM_ARTIFACT_DIR=/path/outside/sources/CoChem-0.1.0-runtime
export COCHEM_CONFIG="$COCHEM_ARTIFACT_DIR/Registry/cochem_system_config.json"
export TOPOS_EXECUTION_BACKEND=base
cochem-topos --version
cochem-topos doctor --verify-runtime --registry "$COCHEM_CONFIG"
cochem-topos matrix support
```

The installed commands are `cochem-topos`, `cochem-topos-release` and `topos-ui`.
`topos-ui --port 8501` launches the local browser interface. BASE discovers TOPOS
through its `cochem.modules` provider; `cochem-topos receive-base MANIFEST
--output-root RUNS` explicitly consumes a typed BASE handoff. Source discovery is
not an automatic calculation.

Standard TOPOS installation includes the pinned QCEngine 0.51.0 and
QCElemental 0.51.2 parsers. Both the source `[dev,ui]` setup and the reviewed
wheel `[ui]` installation receive them as required runtime dependencies. The
`external` extra remains a compatibility alias for the same pins; selecting it
is unnecessary. These open-source parsers do not install or replace CFOUR,
Molpro, Psi4 or other native engines, which retain their separate provisioning
and license requirements.

Before launching any CFOUR energy, derivative, counterpoise, scalar-relativistic
or DBOC calculation, TOPOS verifies both parser distribution versions and imports
the actual pinned harvesting functions. Missing, mismatched or broken parser
installations stop the attempt before native execution. Restore the same reviewed
TOPOS installation to repair dependencies; do not spend a native calculation to
diagnose a parser installation failure.

## Verify a downloaded wheel installation

The following command creates another isolated environment with no editable
packages or inherited site-packages, installs the three wheels, checks CLI and
BASE provider discovery, runs genuine BASE-authorized xTB optimization, and
reviews/exports/verifies the retained result:

```bash
python scripts/accept_installed_release.py \
  --wheelhouse /path/to/reviewed/wheelhouse \
  --registry "$COCHEM_CONFIG" \
  --output /path/to/new/installation-acceptance
```

It runs outside the source trees and removes import overrides. Results include
`clean-install.json`, `acceptance/installed-acceptance.json`, the actual run and
research bundle, and `acceptance/requirements-installed.txt`. Pass the latter as
`--constraints` to repeat the same dependency-version resolution on a compatible
platform. Platform wheels and binary hashes remain part of the retained evidence.
Package functionality is separate from scientific classification: any unresolved
symmetry, isotope or minimum-character notes remain in the scientific record.

Candidate12 binds executable source commit
`053c827638b3481c5c3d645856b69d50c47b387f` to controller wheel SHA-256
`66957b7780560c795119439d53ed010f15ff950571f4b6c940086dbe44e7be6b`.
The immutable [installed acceptance](evidence/TOPOS_CANDIDATE12_INSTALLED_ACCEPTANCE.json)
records a fresh installed-wheel run with actual BASE-authorized xTB execution,
result review and TORQ acknowledgment; no downstream TORQ solver was executed.
The [fixture archive receipt](evidence/TOPOS_CANDIDATE12_FIXTURE_ARCHIVE.json)
checks all 39 native fixture payloads. These receipts establish their recorded
installation scope; full release certification remains a separate gate.

## Upgrade and rollback

Keep existing calculations and immutable snapshot stores outside environments.
Build a **new** artifacts directory from the complete replacement wheel set, run
the eleven-phase audit and clean-wheel acceptance, then select its environment
and registry. Keep the previous environment until its replacement is accepted.
Rollback selects the previous environment and matching registry; it does not
rewrite existing scientific evidence.

Do not independently uninstall or overwrite shared BASE/TORQ packages in a live
environment. Wheel ownership must be disjoint, including files with identical
bytes, because pip uninstall removes files based on distribution ownership.
The release installer deliberately rejects `--existing-environment` together
with `--wheelhouse`. Source development retains the separate existing-environment
workflow documented in the [BASE integration guide](TOPOS_BASE_INTEGRATION.md).

## Build reproducible candidates

Use an isolated build interpreter with the recorded build-tool versions:

```bash
python -m venv /tmp/topos-build-env
/tmp/topos-build-env/bin/python -m pip install -r scripts/release-build-requirements.txt
/tmp/topos-build-env/bin/python scripts/build_release.py --output /tmp/topos-candidate
```

The command builds the wheel and sdist twice from fresh source copies, normalizes
archive timestamps/owners while preserving payload bytes, and requires identical
SHA-256 values. It rejects changed source during the build, source symlinks and
retired/conflicting packages. `SOURCE_DATE_EPOCH` is explicit archive metadata,
not an assertion about when scientific tests ran. The source and dependency
inventories distinguish exact candidate contents from installed runtime versions.
The source archive retains native provisioning patches and their byte identities;
the CREST generic-interface patch is part of the tested executable source set.
Retained JUnit XML may be stored under `.docs/evidence` and ships with the source
archive. Generated test receipts are evidence, not executable source inputs.

Full certification is a separate, failing-until-complete command:

```bash
cochem-topos-release gate --source-root /path/to/CoChem-TOPOS \
  --distribution-manifest /tmp/topos-candidate/distribution-manifest.json \
  --validation .docs/TOPOS_COMPLETION_VALIDATION.json \
  --srs-acceptance .docs/TOPOS_SRS_ACCEPTANCE.json \
  --installation /path/to/installation-acceptance/acceptance/installed-acceptance.json \
  --hosted /path/to/hosted-ORCA/acceptance.json \
  --hosted-extended /path/to/hosted-ORCA-extended/acceptance.json \
  --hosted-repository ProfJJK-CoChem/CoChem-BASE \
  --hosted-run-id ACTUAL_RUN_ID --hosted-run-attempt ACTUAL_ATTEMPT \
  --output /tmp/topos-candidate/release-gate.json
```

The SRS acceptance ledger must bind the current SRS SHA-256 and all 50 exact
requirement IDs to `verified` status and nonempty retained evidence entries
(`path`, `sha256`). Missing requirements cannot be closed by a top-level boolean.
Current tested source hashes, nonzero executed regression tests, zero
failures/errors, full TOPOS matrix implementation, resolved source gaps,
the matching installed wheel and complete correlated hosted ORCA acceptance are
all required. Gate failure preserves the unsigned candidate for review and exits
with status 3. No command in this flow publishes, tags or releases externally.

A local licensed-engine skip can be covered by an actual passing execution of the
**same named test on exactly the same sources** in a different environment. Add
`--supplemental-validation /path/to/native-pytest-receipt.json` (repeatable). Each
receipt needs `verification.source_sha256`, `sources_unchanged: true` and one
successful pytest check with counts, `junit_path` and `junit_sha256`. Retain the
actual JUnit XML beside that receipt, using a relative path. The gate checks every
named skipped testcase against the supplemental executed results. A generic
hosted success, an unrelated ORCA calculation or altered source cannot cover it.
Unresolved GPU, external-engine and other physical acceptance conditions in the
SRS ledger remain blockers independently of testcase coverage.
The primary whole-suite receipt must likewise reference a retained, hash-checked
JUnit artifact. For the repository receipt, use a relative `junit_path` such as
`evidence/TOPOS_REGRESSION.xml`; a temporary build-machine path is insufficient
for another machine to repeat the gate.

The release workflow accepts the repository, run ID and exact run attempt that
produced the licensed artifacts. The BASE companion uploads
`topos-orca-acceptance-RUN_ID-ATTEMPT`, with `topos-orca-evidence/acceptance.json`,
`topos-orca-extended/acceptance.json` and the retained native pytest files. Reading
this private repository requires the existing `COCHEM_SOURCE_READ_TOKEN` or
`BASE_SOURCE_READ_TOKEN` binding to have Actions artifact read access there.
Baseline evidence must pass GOAT, counterpoise and all three core calculation
cases; the extended evidence must separately pass native Hessian, VPT2 and the
declared correlated methods. The gate requires matching source, repository, run,
attempt and workflow commit across both receipts. A passing baseline does not
override a failed or absent extended calculation.

## Isolated ML inference worker

The mandatory controller environment still installs BASE, TOPOS and TORQ together.
BASE runs ML inference in its separately locked interpreter so incompatible model
frameworks cannot alter the controller's numerical environment. The worker carries
identical TOPOS source bytes in a separate `cochem-topos-ml-worker` distribution.
It has no BASE/TORQ/UI distribution dependency, downloads no checkpoints and does
not provide an independently supported TOPOS application.

Build its exact-source wheel twice and verify byte reproducibility:

```bash
/tmp/topos-build-env/bin/python scripts/build_ml_worker.py --output /tmp/topos-ml-worker
```

The BASE-managed ML silo must already match the recorded core dependencies and
have its separately validated model framework/checkpoints. Install using that
silo's interpreter, never the controller's interpreter:

```bash
/path/to/BASE/Silos/cochem_mace_silo/bin/python -I scripts/install_ml_worker.py \
  --wheel /tmp/topos-ml-worker/cochem_topos_ml_worker-0.1.0-py3-none-any.whl \
  --manifest /tmp/topos-ml-worker/worker-distribution-manifest.json \
  --receipt /tmp/ml-worker-installation.json
```

The installer refuses a `cochem-topos` controller distribution before running pip,
checks every declared dependency and source digest, uses only the local wheel with
`--no-index --no-deps`, and verifies the installed source. This separation matters
because both distributions own the `topos` Python module namespace and must never
be co-installed. BASE must re-audit the updated silo before approving inference.
The wheel manifest binds the current worker bytes; later source changes require
rebuilding and reinstalling the worker, not a `PYTHONPATH` override.

## TORQ consumption acceptance

Clean installation acceptance now requires the companion TORQ contract importer.
It exports the actual reviewed xTB result, imports its exact member/state/protocol
manifest through installed TORQ, and checks that TOPOS accepts TORQ's durable
consumption receipt. The import is `imported-awaiting-calculation`; no TORQ solver,
reaction rate or transition-state calculation is represented by this receipt.

The reviewed companion source pins are BASE `705b9d54370d5089da286a02b7a1c4afdcbafec1`
and TORQ `79fbb111125e50627a1a2c129888a45496f368d4`; their companion pull requests
remain separate from publication of a final TOPOS release.
