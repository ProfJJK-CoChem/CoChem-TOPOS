# Installing and upgrading the mandatory CoChem package

TOPOS 0.1.0 build tooling produces a Python wheel and source archive. Its mandatory
package versions are **CoChem-BASE 1.0.1, CoChem-TOPOS 0.1.0 and CoChem-TORQ
0.1.0**, on Python 3.11 or newer. Native calculation acceptance currently targets
Linux CPU. Installing a package does not establish an audited engine allocation,
complete method-matrix coverage, or downstream TORQ scientific readiness.

The current build tooling prepares **unsigned candidates**. It does not create a
GitHub Release, publish to PyPI, or assert final release certification. Inspect
`release-gate.json`: only `release_certified: true` records a passing full release
gate. Missing scientific evidence and source conflicts remain blockers.

## Student installation through BASE

Use the [student deployment review](TOPOS_STUDENT_READINESS.md) and BASE's
[installed dashboard guide](https://github.com/ProfJJK-CoChem/CoChem-BASE/blob/main/docs/topos_student_deployment.md).
The coded student path is:

1. Obtain the instructor-reviewed complete ecosystem kit matching BASE's current
   source/wheel/helper catalog. Extract it outside all source checkouts. The final
   candidate's accompanying source and installation receipts identify the exact
   compatible set; an arbitrary newer `main` or a standalone TOPOS wheel is not
   that set.
2. Open BASE's **Module installation and execution** panel. Choose
   **CoChem-TOPOS**, set external **Module storage**, provide the **CoChem kit
   directory**, and select **Install selected recipient**. BASE installs the
   complete BASE/TOPOS/compatible-core-TORQ package into its independent
   noneditable environment and audits its actual runtime.
3. Refresh availability and select **Open complete TOPOS interface**. The
   installed Streamlit application runs in that audited environment. Use the
   provided local or Codespaces URL; keep a Codespaces forwarded port private.
4. Select the scientific purpose or exact matrix recipe, chemical state,
   resources and inputs. Use **External starting states** for previous
   GOAT/CREST/XYZ work; its named intake stages retain original source bytes and
   require genuine target calculations before scientific review.

This installation/launcher path is implemented. Its final source-bound clean
installation, browser-service and student deployment receipts must accompany the
candidate; this document does not assert that the current working changes have
already been published or accepted on a student's machine.

The compatible-core TORQ line includes the reviewed `4f32380` importer milestone.
That compatibility history does not make a later TORQ calculator interchangeable
in the same interpreter. The newer TORQ student calculator uses a separately
isolated BASE module environment because shared Python/package paths can overlap.
Read the actual kit/catalog and TORQ deployment profile for their exact source
identities; keep both module environments and their registries distinct.

The equivalent installed BASE commands are:

```bash
python -I -B -m scripts.manage_modules install --modules topos \
  --root /external/modules --ecosystem-kit /external/reviewed-kit --json
python -I -B -m scripts.manage_modules verify --modules topos \
  --root /external/modules --json
python -I -B -m scripts.module_dashboard --root /external/modules --port 8501
```

The dashboard command remains in the foreground. Add its supported private-project
options when configuring remote calculations, and retain the installation and
all eleven BASE setup reports. Use Linux locally, in Codespaces, or under Windows
WSL2 for Linux native engines. Package discovery alone does not certify an engine
allocation or downstream TORQ solver.

## Export requests for private Actions calculations

The TOPOS GUI validates and downloads the same typed request used by the CLI and
BASE provider. **Download validated calculation request** preserves the selected
calculation environment. **Download request for BASE private Actions runner** is
an explicit separate export: it targets local native execution *inside* BASE's
private Actions runner, preserves the chemistry and records the original selected
environment. Its current CPU worker profile accepts at most two threads and
4096 MB. GPU/model or other allocations need their declared suitable worker;
export does not replace them with a CPU Hamiltonian.

Use **Prepare imported request for BASE Actions** to export the selected external
frames and named matrix entry step after preserving their original files in a
queued canonical run. Ordinary form validation cannot replace this imported
request with a different frame set. See [independent starting states](TOPOS_EXTERNAL_STARTING_STATES.md).

BASE's dedicated `topos_calculation.yml` workflow and private TOPOS Actions panel
are being integrated for source-pinned native execution with separate kit and
licensed-engine staging receipts. Commit the exported request to the student's
private project and use that explicit BASE submission path for ORCA/CFOUR.
Staging receipts remain separate from scientific request metadata. Implementation
is not evidence of a successful hosted deployment; current-source private native
acceptance and the complete student lifecycle still need genuine receipts.

The generic TOPOS correlated Actions adapter has a different, bounded installation
profile. It must reject engines or model/hardware requirements it does not
provision rather than claim a successful substituted calculation. A student's
personal private repository uses that account's Actions allowance, with its own
authorized account access; it does not inherit organization Actions secrets.
Organization-owned projects use the organization execution context. Codespaces
and Actions authentication are configured separately through BASE's private
staging contracts; no licensed binary belongs in the public source kit.

## Obtain the complete package set

Use the reviewed private candidate artifact prepared by
[`topos_release.yml`](../.github/workflows/topos_release.yml), or build from the
reviewed source revisions using the commands below. The download should contain:

- The TOPOS wheel, source archive, `distribution-manifest.json` and `SHA256SUMS`.
- A wheelhouse containing the exact three mandatory distributions and its own
  `SHA256SUMS`.
- Matching BASE, TOPOS and TORQ source archives, plus the separately installed ML
  worker wheel and its source manifest.
- Installed-package and scientific validation receipts, plus the separate release
  gate report. A successful archive build alone is insufficient.

For **Prepare and verify unsigned TOPOS release candidate**, supply the reviewed
full lowercase 40-character BASE commit in the required `base_commit` dispatch
input. Automation may instead configure repository variable `COCHEM_BASE_COMMIT`.
The workflow fails before companion checkout when neither is set or the value is
not an immutable commit. There is no historical foundation or moving-branch
default. Select the BASE revision whose installed catalog binds this exact TOPOS
commit, wheel and setup helper; retain that selection in the companion build
manifest. The BASE catalog is finalized after TOPOS is frozen, so a fixed reverse
pin in TOPOS would create a circular revision dependency.

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

The kit identifies the compatible BASE/TOPOS/TORQ sources and wheel identities.
The installer rejects duplicate installed-file ownership, including byte-identical
files: shared namespace ownership can make pip uninstall damage another
mandatory distribution. Historical incompatible wheel sets are not current
installation defaults. TOPOS no longer ships BASE's `frontend` package; its
source compatibility shims do not belong in the installed TOPOS wheel.

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

### Historical candidate12 installation evidence

The original candidate12 binds executable source commit
`053c827638b3481c5c3d645856b69d50c47b387f` to controller wheel SHA-256
`66957b7780560c795119439d53ed010f15ff950571f4b6c940086dbe44e7be6b`.
The immutable [installed acceptance](evidence/TOPOS_CANDIDATE12_INSTALLED_ACCEPTANCE.json)
records a fresh installed-wheel run with actual BASE-authorized xTB execution,
result review and TORQ acknowledgment; no downstream TORQ solver was executed.
The [fixture archive receipt](evidence/TOPOS_CANDIDATE12_FIXTURE_ARCHIVE.json)
checks all 39 native fixture payloads. These immutable historical receipts establish only their recorded
source and installation scope; they are not the installation evidence for later
GUI, intake, transport or package changes. Full release certification remains a
separate gate.

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
  --hosted-repository OWNER/PRIVATE_CALCULATION_PROJECT \
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
this private repository requires actual artifact-read authorization through the
configured private BASE execution context.
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

The companion revisions in each historical installation receipt remain part of
that receipt's immutable provenance. Use the new candidate's catalog and exact
source/installation receipts for a new deployment; do not turn those older
acceptances into operational defaults or infer scientific TORQ completion from
an importer acknowledgment.
