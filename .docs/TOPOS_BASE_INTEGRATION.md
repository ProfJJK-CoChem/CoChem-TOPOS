# TOPOS execution through the mandatory CoChem package

CoChem-BASE, CoChem-TOPOS and CoChem-TORQ must be provisioned together. BASE owns
Stage 0 engine identity and the subprocess broker. TOPOS owns molecular requests,
scientific validation, resource ceilings, persistence, review and research export.
Installing or finding an ORCA binary on PATH does not establish BASE authority.

This integration uses the reviewed source revisions:

| Component | GitHub Actions source revision |
|---|---|
| CoChem-BASE | `705b9d54370d5089da286a02b7a1c4afdcbafec1` |
| CoChem-TORQ | `79fbb111125e50627a1a2c129888a45496f368d4` |
| CoChem-TOPOS | The dispatched controller workflow revision, recorded with the request/result correlation |

Pinning a TORQ checkout makes package identity explicit. It does not certify that
TORQ's unfinished scientific workflows are complete.

## Local production setup

Use Python 3.11 or newer on Linux and run:

```bash
python scripts/setup_ecosystem.py \
  --base-root /path/to/CoChem-BASE \
  --torq-root /path/to/CoChem-TORQ \
  --artifacts /path/outside/repositories/CoChem_Artifacts
```

The helper installs CREST before BASE audits engines, runs BASE's eleven setup
phases, installs all three components, then re-audits the mandatory selected
repositories. The artifact directory is outside the source worktrees. Use the
emitted environment and registry paths; do not replace the BASE registry with a
TOPOS settings file.

`topos.base_integration.inspect_ecosystem()` inspects the three components.
`BaseRuntime` verifies the BASE registry checksum and delegates executable
identity/hash checks and process containment to BASE. Explicit source checkouts
can be selected during development with `COCHEM_BASE_ROOT` and `COCHEM_TORQ_ROOT`;
TORQ discovery avoids importing its side-effectful bootstrap.

```bash
cochem-topos doctor
cochem-topos doctor --verify-runtime --registry /absolute/path/to/cochem_system_config.json
```

TOPOS defaults to `execution_backend: "base"`. The explicit
`TOPOS_EXECUTION_BACKEND=development` setting supports numerical unit/integration
tests without asserting production installation authority. It is not a fallback
when a production BASE check fails.

## Private GitHub controller

The production TOPOS workflow is
[`.github/workflows/topos_compute.yml`](../.github/workflows/topos_compute.yml).
It accepts only a manual dispatch on the private repository's default branch,
uses a protected `cochem-student-tests` environment, and checks the canonical
request SHA-256 before provisioning.

Configure that environment with:

| Setting | Purpose |
|---|---|
| Secret `COCHEM_SOURCE_READ_TOKEN` | Contents-read access to the private BASE and TORQ source repositories used by checkout. |
| Secret `PRIVATE_ORCA_ASSET_CREDENTIAL` | Contents-read access to the private ORCA distribution repository configured by BASE, currently `ProfJJK-CoChem/CoChem-ORCA`. Required only for licensed provisioning. |
| Variable `ORCA_CLOUD_LICENSE_CONFIRMED` | `true` when the responsible licensee has established the applicable deployment scope; required for ORCA-bearing requests. |

Restrict the controller's membership, default-branch changes and dispatch rights
to the intended authorized group. Configure environment review rules supported
by the repository's GitHub plan. Anyone who can read a private Release repository
can download its assets; environment review does not change that asset access.

The workflow reuses BASE's pinned `setup-orca` composite action. BASE selects the
reviewed complete ORCA 6.1.1 archive from its distribution manifest, verifies its
SHA-256, builds/tests pinned Open MPI 4.1.8, and records installation provenance.
TOPOS does not maintain a competing production ORCA distribution path. After
provisioning, BASE performs setup/audit, TOPOS and TORQ are installed, and
`topos.actions.compute_worker` executes the correlated request through BASE.

## Client configuration and credentials

Create a TOPOS settings file and select it with `TOPOS_CONFIG`:

```json
{
  "output_root": "/absolute/path/to/TOPOS-runs",
  "execution_backend": "base",
  "remote_repository": "OWNER/PRIVATE-TOPOS-CONTROLLER",
  "remote_ref": "main"
}
```

Use `calculation_environment: "github-actions"` in the scientific request. The
client uses its separately supplied GitHub credential (`GH_TOKEN`/`GITHUB_TOKEN`,
or the explicit client credential argument) for Actions dispatch, polling,
cancellation and artifact retrieval. Give it the necessary Actions permissions
on the controller repository. Never put a token in `RunRequest`, arbitrary
metadata, source files, raw chemistry inputs or a research bundle.

Dispatch sends canonical request bytes, their digest and a unique dispatch ID.
The consumer checks the matching workflow run and result receipt before treating
retrieved evidence as belonging to the request. Queued, failed, cancelled,
timed-out and unavailable jobs remain explicit states. Credential values are
removed from scientific execution environments and receipts.

Verified evidence is retained by Actions for 14 days in
`topos-evidence-DISPATCH_ID`; retrieve it before expiry. The workflow cleans its
licensed installation at the end. An Actions job's green status alone does not
establish scientific validity: inspect the TOPOS execution/validation states,
request correlation, actual engine versions/hashes, output membership and parsed
quantities.

## BASE module handoff receiver

TOPOS registers the `cochem.modules` provider entry point and exposes the explicit
`topos.base_provider.execute_handoff` receiver. Its CLI equivalent is:

```bash
cochem-topos receive-base /path/to/module_handoff.json --output-root /path/to/TOPOS-runs
```

The BASE manifest must include `options.topos_request`, with explicit charge,
spin, engine and purpose. The receiver verifies the producer artifact hashes and
requires the request geometry and atom ordering to match the handed-off XYZ. It
executes through mandatory BASE authority, retains producer provenance in the
run, and writes a separate consumption receipt with the actual execution and
validation states. Provider discovery is side-effect free; registration does not
claim that BASE's browser automatically dispatches a calculation.

## Validation boundary

The BASE workstream has reported a successful ORCA calculation on GitHub Actions.
This TOPOS integration is separate code and needs its own live hosted validation.
No TOPOS-hosted calculation is claimed here merely because BASE succeeded or
because a local transport/worker test passed. Live acceptance requires the configured private repository access, source and
licensed distribution credentials, and the workflow protection settings. Retained
job receipts identify the exact candidate commits and the stages that actually ran.

Actual local BASE-native tests and transport/worker contract tests are separate
evidence categories. The validation receipt records their outcomes and source
identities. TOPOS/TORQ handoff consumption remains subject to the
[versioned producer contract](TOPOS_TORQ_HANDOFF.md); the legacy TORQ reader is not
a substitute for that contract.


## Queue-inclusive deadlines

With `include_queue_in_budget: true`, the worker reads its own authenticated
GitHub run `created_at` timestamp and subtracts queueing and installation from the
original scientific budget. The original request remains unchanged in the receipt;
the local worker request records only the remaining execution allowance. A separate
deadline cancels native processes if that allowance expires. When queueing/setup
already exhaust the budget, TOPOS commits a timed-out record with no scientific
attempts. Retrieval independently checks the server timestamp, request adaptation,
and recorded accounting. This assumes GitHub server and hosted-runner UTC clocks
are synchronized; artifact transfer time is not scientific execution time.

## Audited machine-learning workers

A separate `cochem-topos-ml-worker` wheel installs exact TOPOS source bytes into the
BASE MACE silo. Its dependency lock does not install the controller or GUI there;
the controller environment still requires BASE, TOPOS, and TORQ. The reproducible
builder and installer are `scripts/build_ml_worker.py` and
`scripts/install_ml_worker.py`. The installer refuses overlap with the full TOPOS
distribution, checks pinned dependencies, and records the worker wheel/source
hashes. BASE authority checks the isolated interpreter/package lock, installed
worker source manifest, immutable model/request files, and allocation before
launch. The supplied verified MACE profile uses MACE 0.3.16 and CPU Torch 2.8.0;
CUDA execution additionally requires an audited CUDA-capable package profile and
actual measured device memory. A CPU lock never establishes GPU capability.

Psi4 registration includes a bounded native He/HF calculation and hashes its
compiled core and interpreter. A successful `psi4 --version` alone is insufficient.


The BASE companion now provides two explicit MACE profiles. `COCHEM_ML_TORCH_PROFILE=cpu`
uses the genuinely tested Torch 2.8.0+cpu/MACE 0.3.16 environment. `cuda128` selects
an independent Linux x86-64 CPython 3.12 lock with official Torch 2.8.0 and its
15 exact NVIDIA/Triton dependencies, each downloaded by pinned wheel URL and
SHA-256. Selecting another profile for an existing silo fails verification;
it does not replace that environment. The CUDA wheel set is approximately
3.9 GB compressed. CUDA installation and native GPU calculations have not been
verified on this CPU-only development machine. Device authority still requires
the actual BASE hardware audit and a successful native Torch CUDA probe.

AIMNet2 has its own isolated CPU silo (`cochem_aimnet2_silo`), with actual
`aimnet==0.2.0`, Warp 1.18.0 and nvalchemi-toolkit-ops 0.4.1 imports and an exact
52-package lock. Its provisioner does not install models or claim GPU readiness.
Both ML silos require the separate source-bound TOPOS worker wheel before use.

The reviewed CREST generic-calculator repair is selected explicitly with
`COCHEM_CREST_BIN`. BASE records `3.0.2+topos-generic-paths-v1` and binds its
upstream commit, source patch, native banner, binary, installation manifest and
shared libraries. The original upstream installation remains separate. ABCluster
is audited as `abcluster`, resolving its actual `rigidmol` executable and component
version; the current generic hosted TOPOS worker rejects ABCluster requests until
that hosted installation is explicitly provisioned.
