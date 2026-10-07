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
`86fd7bdbc77b87ab4303e03e0902b4089054f402`. The original BASE 1.0.0 source revision
`c8d33ac68d4d77f9035d1dbb8ec7e0c3ca52ec86`
duplicates four installed `Libraries` files owned by TORQ. The reviewed companion
BASE packaging change must remove that duplicate wheel ownership. The installer
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

Optional `external` dependencies provide pinned QCEngine/QCElemental parsers.
They do not install or replace CFOUR, Molpro, Psi4 or other native engines.
Install extras from the same reviewed TOPOS wheel, for example
`python -m pip install '/path/to/cochem_topos-0.1.0-py3-none-any.whl[external]'`.

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

Full certification is a separate, failing-until-complete command:

```bash
cochem-topos-release gate --source-root /path/to/CoChem-TOPOS \
  --distribution-manifest /tmp/topos-candidate/distribution-manifest.json \
  --validation .docs/TOPOS_COMPLETION_VALIDATION.json \
  --srs-acceptance .docs/TOPOS_SRS_ACCEPTANCE.json \
  --installation /path/to/installation-acceptance/acceptance/installed-acceptance.json \
  --hosted /path/to/hosted-ORCA/acceptance.json \
  --output /tmp/topos-candidate/release-gate.json
```

The SRS acceptance ledger must bind the current SRS SHA-256 and all 50 exact
requirement IDs to `verified` status and nonempty retained evidence entries
(`path`, `sha256`). Missing requirements cannot be closed by a top-level boolean.
Current tested source hashes, nonzero executed regression tests, zero
failures/errors/skips, full TOPOS matrix implementation, resolved source gaps,
the matching installed wheel and complete correlated hosted ORCA acceptance are
all required. Gate failure preserves the unsigned candidate for review and exits
with status 3. No command in this flow publishes, tags or releases externally.
