# Explicit ORCA counterpoise energy legs

`topos.counterpoise` implements the five energy calculations needed to report
raw, Boys–Bernardi counterpoise (CP), and half-CP interaction energies for a
specified two-fragment complex:

1. Complex in the complete complex basis.
2. Fragment A at its geometry in the complex, in its own basis.
3. Fragment A at that same geometry, with the other fragment's basis centers as ghosts.
4. Fragment B in its own basis.
5. Fragment B in the complete complex basis.

All five calculations must complete, converge electronically, retain actual raw
artifacts, report ORCA 6.1.1 and use the same executable and shared basis hashes.
A failed, cancelled, missing or inconsistent leg leaves the derived energies
absent. Total wall time applies to the complete sequence. Separate working
directories prevent cross-leg `.gbw` reuse.

The physical fragment and the complete set of basis centers are different
objects. The native input uses `Element:` for ghost centers and the physical
fragment's charge/multiplicity. A full complex's electron count is never used to
validate a fragment doublet. Provenance separately identifies the physical
geometry and basis-center geometry. This adapter is energy-only; ghost forces
are not silently treated as a counterpoise geometry optimizer.

```python
from topos.counterpoise import execute_counterpoise
from topos.base_integration import BaseRuntime
from topos.models import MethodSpec, ResourceLimits

runtime = BaseRuntime()
allocation = ResourceLimits(budget_seconds=1800, threads=1, memory_mb=2048)
exports = {
    role: runtime.export_orca_basis(basis, complex_molecule.symbols,
                                    f"/new/basis-exports/{role}", allocation)
    for role, basis in (("orbital", "def2-TZVPP"), ("auxiliary", "def2/J"))
}
if any(receipt["status"] != "completed" for receipt in exports.values()):
    raise RuntimeError("Native ORCA basis export did not complete")

result = execute_counterpoise(
    complex_molecule,
    MethodSpec(engine="orca", method="wB97M-V", basis="def2-TZVPP",
               auxiliary_basis="def2/J", profile_id="orca-mapping-v4.1"),
    allocation,
    "/new/counterpoise/workdir",
    orbital_basis_file=exports["orbital"]["output_path"],
    auxiliary_basis_file=exports["auxiliary"]["output_path"],
    basis_export_receipts=exports,
)
```

Without an explicit process runner the adapter uses the mandatory BASE registry
and broker. The molecule must contain exactly two complete `fragments` and
`fragment_states`; specified covalent/coordination bonds may not be cut. The
present external-basis profile covers all-electron H–Kr. ECP-dependent elements
require an additional explicit ECP contract. Solvent, native constraints,
additional dispersion tokens, and 3c/gCP composites are rejected. In particular,
no D4 is added to the VV10 functionals and no extra CP is added to native gCP.

The orbital and Coulomb-fitting `.bas` files are identical archived GAMESS-US
exports across all legs. They enter the comparison protocol by SHA-256, not just
by a user-supplied basis name. This prevents two different files labelled
`def2-TZVPP` from being treated as the same Hamiltonian.

**Basis identity requires native export evidence.** The supported BASE utility
path verifies both `orca` and `orca_exportbasis` against BASE's installed full
distribution inventory, pinned archive manifest and Stage 0 engine authority.
The exporter runs through BASE's resource broker. TOPOS requires matching named
bases, elements, exact command, engine and exporter hashes, native output bytes,
and complete stdout/stderr. The calculation retains those receipts and logs.
Only a matching native receipt permits `validation_status: validated-for-protocol`
and `basis_identity.status: native-export-verified`. This is a traceable local
execution contract; arbitrary externally authored JSON is not authenticated by
its own checksums.

Shared bytes alone do not prove that supplied files contain ORCA's canonical
named basis. Successful calculations without native export receipts have
`validation_status: human-review` and
`basis_identity.status: user-supplied-unverified`; they do not establish exact
T5-1h method-matrix compliance. Missing full-distribution provenance blocks
automatic export. The adapter does not run an unaudited sibling utility.

ORCA documents the native export command, for example:

```bash
orca_exportbasis -b def2-TZVPP -a H O -f GAMESS-US -o def2-TZVPP.bas
orca_exportbasis -b def2/J -a H O -f GAMESS-US -o def2-J.bas
```

These commands are documentation for an authorized ORCA installation, not actions
performed by TOPOS in this environment. Preserve the exported files, native
utility identity, command and provenance when supplying them.

A repeated call with the same work directory resumes a compatible checkpoint.
It verifies the immutable molecular state, method, basis hashes and energy-leg
plan; rechecks retained raw bytes; reparses native electronic convergence and
energy; and compares the exact original input deck before reusing a completed
leg. Unfinished legs get fresh scratch directories. Earlier checkpoints and
unsuccessful attempts remain retained. Each resumed invocation has its own
explicit wall-time budget. Parser/orchestration tests exercise this behavior;
resumed native ORCA execution still requires licensed acceptance evidence.

If isolated reference geometries with matching atom IDs, isotope/state and
stereochemistry are supplied, the adapter evaluates them separately and reports
fragment deformation and raw/CP/half-CP binding relative to those geometries.
A single-point reference does not establish an optimized monomer minimum. The
reported interaction/binding quantities are electronic energies; they contain no
ZPE, thermal entropy, standard-state or solvation correction.

Validation here covers input grammar, state/fragment separation, shared basis
identity handling, failure/cancellation boundaries and energy arithmetic. No
licensed ORCA CP calculation has been executed in this workspace. An actual
licensed hosted acceptance test remains necessary.

Sources checked in the ORCA 6.1 manual:

- [Coordinate special definitions](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/coordinates.html#special-definitions): ghost atom colon syntax.
- [Counterpoise corrections](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/counterpoise.html): Boys–Bernardi energy legs and distinction from CP optimization.
- [Reading basis sets](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/basisset.html#reading-basis-sets-from-a-file): `GTOName` and `GTOAuxJName` with GAMESS-US files.
- [orca_exportbasis](https://www.faccts.de/docs/orca/6.1/manual/contents/utilitiesvisualization/utilities.html#sec-utilities-exportbasis): supported native export options.
