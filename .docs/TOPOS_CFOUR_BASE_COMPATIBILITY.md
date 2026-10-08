# CFOUR runtime compatibility and acceptance boundary

Reviewed 2026-10-08. This note distinguishes executable-provider integration
from successful TOPOS scientific calculations. It does not certify a CFOUR
2.1 calculation, any higher composite, or release readiness.

## Required BASE capabilities

CFOUR requires a BASE installation whose `authorize_engine_execution()` returns
`runtime_seal_sha256`, verifies that seal against the audited registry before
and after execution, and whose `engine_runtime_environment("cfour", ...)`
constructs the CFOUR child environment. These features are present in reviewed
[BASE cc1ef4b](https://github.com/ProfJJK-CoChem/CoChem-BASE/commit/cc1ef4bff7c8b313386a9ddfd5db118b872c862c).
Use an explicitly pinned, reviewed BASE source revision and a fresh completed
Stage 0 audit, including all eleven phases. A package version string alone is
insufficient: both the older and newer source advertise BASE 1.0.0.

The prior scientific baseline, BASE
`705b9d54370d5089da286a02b7a1c4afdcbafec1`, remains usable for its previously
supported non-CFOUR routes. It lacks the required CFOUR seal authority; TOPOS
rejects CFOUR execution and component reuse with that provider. Passing tests
with the earlier baseline does not establish compatibility with a newer BASE
revision. Refreshing the provider requires its own installation, Stage 0 audit,
and relevant genuine scientific acceptance.

TOPOS delegates the runtime inventory and dependency policy to BASE. It does
not reimplement BASE's distribution verifier or replace TOPOS's scientific
protocols with BASE's narrower canonical CFOUR calculation service. In the
reviewed BASE source that service supports HF/MP2/CCSD/CCSD(T), with its own
basis/core/solver conventions; those are not replacements for TOPOS spherical,
frozen-core, higher-CC, scalar-relativistic, DBOC, or ghost-center protocols.

## Execution, persistence and reuse

Each CFOUR launch uses the BASE child environment before credentials are
removed. OpenMP receives the allocated thread count; BLAS thread counts,
including BLIS, remain one. TOPOS rejects per-process environment overrides
that differ from the environment BASE authorizes. Change the installation or
runtime configuration through BASE and repeat setup instead.

Every native directory retains `engine-cfour-runtime.json`, containing the
pre/post authorization identity, original command and working directory,
ZMAT/GENBAS hashes, and complete stdout/stderr hashes. A verified runtime
receipt only establishes process integrity; a failed calculation remains
failed. The scientific adapter separately validates native version, requested
controls, convergence, geometry and requested observable. The ordinary CFOUR
adapter also checks original launcher, source/staged GENBAS, ZMAT and typed
protocol bytes after every evaluation.

The component ledger binds one complete BASE runtime authority to the whole
campaign, checks current authorization before reuse and lost-commit recovery,
and validates every evaluation receipt. A changed helper/library seal cannot
reuse results merely because the launcher and GENBAS are unchanged. Old
unsealed completed components cannot acquire a new seal retrospectively.
Portable campaign verification compares retained receipts against the retained
audited registry, without requiring a binary on the reviewing machine. It
verifies execution authority; this step alone does not independently reparse
all scientific observables. Three-field version/launcher/GENBAS tuples in
scientific derivations are partial identifiers; the record's
`cfour_runtime_authority` supplies the complete BASE runtime association.

## What the local checks establish

Invocation parsing supports actual inline `--invoking executable xjoda` and
two-line `--invoking executable--` followed by a native executable path.
Malformed separators, missing/nonprogram next lines, missing/extra completions,
and nonzero completion statuses remain rejected. Parser transport regressions
use unchanged public outputs labelled with their genuine 2.00beta, 1.01 and 1.2
versions. They are not relabelled as 2.1. A separate unchanged genuine 2.1
HF/6-31G** output from [BASE run 37694454874](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37694454874)
validates the current completion grammar. Its actual SPHERICAL=OFF setting is
explicitly rejected by TOPOS's SPHERICAL=ON protocol; it does not establish
TOPOS scientific acceptance. Native spherical-basis and singlet-state settings
are now checked explicitly rather than inferred from the requested input.

Receipt/ledger tests use expressly labelled bookkeeping identities and unchanged
historical raw output. Real broker infrastructure tests deliberately exit with
failure; they cannot supply a successful chemical result. No local licensed
binary was installed or executed for this repair.

## Next genuine acceptance

BASE's reviewed `cfour_acceptance.yml` provisions its approved private runtime
through the existing `CFOUR_ASSET_READ_TOKEN` and runs BASE's bounded scientific
acceptance after fresh setup. The retained successful BASE calculations establish
provider behavior for their stated protocols, not TOPOS higher-level acceptance. The reviewed
`topos_compute.yml` does not yet provision CFOUR. Workflow source alone does not
establish repository/environment protection settings.

A subsequent TOPOS acceptance workflow must use the actual configured private
license path, a pinned compatible BASE revision, a fresh audited registry, and
retain real CFOUR 2.1 output for the exact requested protocols. Required cases
include actual correlated gradients/geometry identity and finite differences,
scalar and DBOC controls, higher-CC solver identity, ghost-basis/core controls,
relaxed total counterpoise derivatives, and unchanged-runtime replay. Keep the
existing physical applicability gates and deadlines. Native failure or an
unsupported protocol must remain a failure; do not substitute a nearby method.

GENBAS/ECPDATA and licensed executables must stay in the controlled runtime/cache.
Do not upload an unchecked entire TOPOS attempt tree: attempts contain retained
basis bytes. Publish only permitted scientific outputs and integrity receipts,
with licensed files handled through the approved protected distribution path.
