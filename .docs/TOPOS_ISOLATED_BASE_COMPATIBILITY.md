# TOPOS compatibility with isolated BASE-managed TORQ

The managed route accepts BASE 1.1.0 without installing TORQ into TOPOS's
interpreter. BASE obtains the canonical module sources and emits the versioned
`cochem.module-sidecar/1` receipt. TOPOS rechecks that installation through BASE
before accepting TORQ availability. It never imports TORQ's shared namespaces
during this discovery and never treats installation as a completed calculation.

This addresses the separate-environment TOPOS finding in BASE's
[module ownership audit](https://github.com/ProfJJK-CoChem/CoChem-BASE/blob/b05f7b048eff39bedf63019c8f371bdde5b5579a/.docs/Module_Ownership_Audit_2026-10-18.md).
The relevant requirements remain BASE Chunk 17 WBS 17.1.3 and proposal §§3.2–3.3,
and TOPOS SRS 0.1.0 §§1, 3 and TOPOS-010-042. Registry, native executable,
resource-ceiling, immutable handoff and scientific checks remain mandatory.

The dependency range is `CoChem-BASE>=1.0.1,<1.2`. The ordinary TORQ dependency
has been removed because BASE and TORQ still publish overlapping paths. Existing
explicit-source discovery remains development support. The older TOPOS-specific
shared-environment setup helper and workflows require their own migration before
they can establish this managed deployment profile.

## Verification scope

Local Linux qualification used BASE
`b05f7b048eff39bedf63019c8f371bdde5b5579a`, TOPOS's candidate changes on
`a6f763c5efce85b6cc3ed7870427f4a6686f3d5d`, and canonical TORQ
`4ce8eecba56e91e27c6abb32473b2ee4d44767c4`. Disposable build copies produced
noneditable BASE/TOPOS wheels. TORQ was fetched, built and installed separately
by BASE's real module installer; package signatures, archive hashes and TLS
verification remained enabled. TOPOS's interpreter contained no installed
CoChem-TORQ distribution.

The installed-wheel boundary accepted the genuine installation and rejected
changed receipt bytes, retained wheel bytes, installed provider bytes, canonical
source bytes, a mismatched revision and a sidecar changed during real
verification. The untouched installation was verified again after restoring
the negative probes. TORQ's bootstrap was not imported. The ordinary test suite
also rejects malformed, oversized, duplicate-field and redirected receipts,
and proves that an invalid configured sidecar cannot fall back to a checkout.

An independent real BASE Stage 0 setup completed all eleven phases with
`DEGRADED_OPERATIONAL` status: checksum-pinned xTB 6.7.1 and CREST 3.0.2 were
available; ORCA and CFOUR were missing. An installed-wheel BASE water handoff
then executed genuine GFN2-xTB through BASE's audited registry and broker,
retained native evidence, verified its immutable snapshot and returned an
honest completed consumption receipt. The water energy was
`-5.070371711236` hartree; scientific validation remained `human-review`.
Precancellation returned cancelled with
no calculated candidates. This is bounded local xTB acceptance; it does not
establish ORCA, CFOUR, hosted Actions or student Codespace execution.

The no-GPU runtime exposed a separate compatibility defect: optional missing
GPU observations caused a Python TypeError, and infinite VRAM was accepted.
TOPOS now rejects those observations as unavailable measured authority. Valid
GPU allocations still require the same device and memory ceilings. These tests
are capability-boundary checks and do not claim actual GPU computation.

The [portable evidence](evidence/2026-10-18-isolated-base-compatibility/README.md)
retains the raw committed native snapshot, handoff, final wheel hash, installed
boundary checks and source hashes. The final runtime wheel SHA-256 is
`08e034766230b34e512f999b061f08f732b18dca596c4d979828ec6710974c0c`.

The whole compatibility profile completed with **2,824 passed and 43 skipped**.
The skipped capabilities require unavailable ABCluster, ORCA, Psi4 or explicit
ML interpreters/models. A prior profile's four failures asserted the superseded
ordinary BASE/TORQ dependency contract. Their updated tests preserve the exact
CFOUR parser pins and historical kit source/wheel gates; all 66 affected tests
passed. Repository-wide Ruff and dependency checks passed.

The compatibility profile loaded the earlier GPU fault-test fixture, identified
by its exact hash in `validation.json`. The final fixture uses the real BASE
schema's explicit construction API to exercise missing observations under both
old and current schemas; its final 11-case follow-up passed. Production runtime
bytes were unchanged. A frozen whole-candidate run remains outstanding and is
coordinated with the remaining canonical structural ownership transfer.

This evidence does not establish BASE's final outer installer/adapter at the
published candidate pin. Full SRS conformance, complete method-matrix scientific
validation and student readiness require additional evidence beyond this
compatibility change.
