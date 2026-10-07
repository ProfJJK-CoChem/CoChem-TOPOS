# CoChem-TOPOS contribution rules

TOPOS is version 0.1.0. Read the current [.docs/CoChem-TOPOS_SRS.md](../.docs/CoChem-TOPOS_SRS.md), [implementation record](../.docs/TOPOS_0.1.0_IMPLEMENTATION.md), [recommendations and errata](../.docs/TOPOS_0.1.0_RECOMMENDATIONS.md), and [references](../.docs/TOPOS_0.1.0_REFERENCES.md) before changing scientific behavior. Historical council resolutions and audit receipts are source evidence, not proof that a capability exists or a calculation succeeded. Qualify reused legacy requirement/resolution IDs by their source document.

## Scientific and execution integrity

- Preserve the requested engine, Hamiltonian, chemical state, units, constraints, and numerical profile. Unsupported or unavailable requests must produce explicit typed outcomes. Never replace missing xTB/ORCA/CREST with a different potential, fabricated output, or local execution labeled as a remote job.
- Keep charge, multiplicity, isotope selectors, atom mapping, stereochemistry, fragments, and environment explicit. Distinguish malformed input, physically suspect geometry, and unsupported chemistry. Graph/radius heuristics are hypotheses; numerical convergence alone does not establish a valid minimum or experimental accuracy.
- Preserve raw engine input/output, executable/software versions, source/artifact hashes, parser identity, and attempt/geometry/quantity linkage. Missing values remain absent with reasons. Physical zero energies/gradients are valid numerical values; detect errors through provenance and numerical checks, not a universal nonzero rule.
- Query element/isotope data through the documented provider and record conventions. Atomic weights are not exact isotope masses. Normalize units once at the boundary and retain the original units/evidence.
- Distinguish search observations, structural identity, equilibrium degeneracy, electronic-energy weights, and thermodynamic populations. Proper rotations cannot replace reflection checks. Search completeness, method accuracy, point-group assignments, and publication readiness require specific evidence.
- Keep method-matrix conflicts explicit. The supplied method matrix is a constraint excerpt; do not invent a full purpose/time/hardware routing table or silently reconcile incompatible convergence profiles.

## Implementation and persistence

- Implement new production behavior in the shared typed `topos` contracts and workflow. UI, CLI, and BASE adapters must preserve the same request and scientific result semantics. Work within assigned file ownership when collaborating; coordinate changes to another contributor's files.
- Scientific engine execution is currently validated on local Linux with bounded owned process groups, finite budgets, thread/memory limits, and preserved cancellation/failure evidence. Do not claim Windows/macOS or remote execution support from portable imports or a running web server. Preserve platform-specific unavailable states until real adapters are tested.
- Use configured executable/output paths, environment variables, and documented defaults. Keep generated scientific records and runtime scratch outside the source repository. Never include credentials in scientific contracts, logs, or publication bundles.
- Storage uses verified immutable snapshots, writer ownership, and an atomic commit pointer on supported local filesystems. A lock or `libver='latest'` is not HDF5 SWMR. Do not claim multi-writer, distributed durability, or full-disk/power-loss recovery without the corresponding implementation and failure tests.
- Preserve completed attempts and scientific source quantities. Corrected science requires traceable new attempts/versions; review annotations must not silently rewrite raw data. Export membership follows explicit run identity and verified artifacts, not arbitrary directory globs.
- Local export, exact-version manifest receipt, public deposition, and external TORQ computation are separate actions. Do not manufacture submission IDs, acknowledgments from an external service, DOI publication, authorship approval, or license rights.

## Verification and reporting

- Collect the entire test suite with `pytest`; do not hide unrelated failures by narrowing `testpaths` or relabeling historical test receipts as current evidence.
- Analytical unit tests, parser fixtures, and infrastructure failure test doubles are legitimate and must be labeled by their purpose. They cannot establish real quantum chemistry or remote execution. Real-engine integration tests must invoke the declared executable and retain genuine command/version/output evidence. An unavailable dependency leaves that capability unverified; never replace it with simulated success.
- Run meaningful checks for the changed behavior, including relevant numerical invariants and negative cases. Report actual targets/counts, skips/unavailable dependencies, hardware/configuration, tested source identity, and limitations. Do not invent successful checks, engine outputs, benchmark speedups, or scientific authority.
- Preserve historical documents as history. Do not restore obsolete generated wheels, coverage files, runtime state, restricted test-collection payloads, or retired production fallbacks. Current evidence belongs in the implementation record and reproducible test/run artifacts.
