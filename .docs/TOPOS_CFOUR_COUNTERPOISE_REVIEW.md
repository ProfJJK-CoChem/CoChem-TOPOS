# CFOUR counterpoise geometry review: T3O-1w

Research date: 2026-10-07. The original matrix's T3O-1w expansion requires
**CCSD(T)/CBS + core-valence + full-triples + full-quadruples, counterpoise-bracketed**.
The existing `T3C-1w` implementation computes explicitly parameterized geometry
increments without that bracket. It cannot certify T3O-1w. Authorization of named
ORCA alternatives for the MPQC/Molpro conflicts does not remove this requirement.

## What the authoritative interfaces establish

- [QCElemental 0.51.2](https://github.com/MolSSI/QCElemental/blob/v0.51.2/qcelemental/molparse/to_string.py#L159-L181)
  writes a ghost basis center as `GH` in CFOUR Cartesian coordinates. The original
  element is intentionally absent from that coordinate label and must be retained
  separately in the basis mapping.
- [QCEngine 0.51.0](https://github.com/MolSSI/QCEngine/blob/v0.51.0/qcengine/programs/cfour/runner.py#L110-L128)
  selects `BASIS=SPECIAL` when a molecule contains ghosts and writes one original
  element/native basis entry for every real or ghost center. A ghost at a carbon
  site needs the carbon basis, not a basis inferred from `GH`. Its runner stages
  the installation's native `GENBAS` file.
- [The QCEngine ghost tests](https://github.com/MolSSI/QCEngine/blob/v0.51.0/qcengine/programs/tests/test_ghost.py)
  explicitly exercise CFOUR HF and MP2 energy/gradient requests. For He with a
  ghost Ne center, the published expected gradient has opposite nonzero center
  forces, approximately `±4.317771e-6 Eh/bohr`; both centers contribute. The tests
  also check real-atom nuclear repulsion and total basis-function counts. Their
  presence is source evidence, not a record that they ran in this environment.
- [The official Psi4 CFOUR interface documentation](https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/doc/sphinxman/source/cfour.rst#L245-L305)
  documents frame/order restoration and per-center `SPECIAL` basis handling.
  Its [current ghost-gradient example](https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/tests/cfour/psi-ghost-grad/input.dat)
  nevertheless comments: **“ghost gradients no longer supported. Use QCEngine
  or QCDB instead.”** Its comparisons are disabled.
- The example's [retained native output](https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/tests/cfour/psi-ghost-grad/output.ref)
  demonstrates `GH`, `SPECIAL` and per-center basis entries, but identifies CFOUR
  **1.2**, dated 2013, with `FROZEN_CORE=OFF`. It is not a CFOUR 2.1 frozen-core
  high-order coupled-cluster acceptance fixture. Applying the actual installed
  QCEngine 0.51.0 harvester to its unchanged first native evaluation raises
  `NotAnElementError: GH`. This result establishes an incompatibility with that
  old output format; it does not establish that every modern ghost output fails.
- [ASH's versioned CFOUR interface](https://github.com/RagnarB83/ash/blob/f43c421f3bca48e3740bab7a10acb5a2676246a0/ash/interfaces/interface_CFour.py#L272-L303)
  distinguishes native `FROZEN_CORE=ON` from explicit `DROPMO` orbital selection.
  Its automatic core table is a chosen convention, not a universal definition
  of a chemically correct frozen core. Ghost basis centers must not contribute
  electrons or frozen occupied orbitals to a physical monomer.

The CFOUR project's direct GhostAtoms and CounterpoiseCalculations pages were
unavailable through the configured proxy (HTTP 403). No inaccessible wording is
quoted or inferred. The separately published interfaces above were inspected at
specific revisions. Source hashes and the actual parser observation are retained
in [the research receipt](evidence/TOPOS_CFOUR_CP_RESEARCH_20261007.json).

## The required potential and its derivatives

At a full complex geometry **R**, let `E_AB^AB` be its ordinary total electronic
energy, `E_i^i` a physical fragment's own-basis energy at its current in-complex
geometry, and `E_i^AB` that same fragment's energy with all partner basis centers
present as ghosts. A relaxed Boys–Bernardi counterpoise surface is

`V_CP(R) = E_AB^AB(R) + sum_i [E_i^i(R_i) − E_i^AB(R_i; R_partner)]`.

The uncorrected surface is `V_raw(R) = E_AB^AB(R)`. The corrected *interaction*
energy `E_AB^AB − sum_i E_i^AB` alone is not the relaxed total potential: optimizing
it would also remove the monomer deformation energies. Frozen-monomer interaction
and relaxed-monomer geometry are different protocols.

A numerical derivative must displace the complete complex **R** and rebuild
**every real/ghost leg at that displaced geometry**. This includes differentiation
with respect to ghost-center coordinates in `E_i^AB`, retaining basis-motion
(Pulay) contributions. Setting those derivatives to zero or displacing only the
physical fragment does not calculate the gradient of `V_CP`.

A complete, explicitly parameterized geometry bracket can run each of the eight
CBS/CV/fT/fQ component optimizations on both `V_raw` and `V_CP`, then combine
optimized internal-coordinate increments separately in each branch. Each term
uses its own declared orbital basis and core convention. Report both resulting
geometries and rotational constants. Their difference is a sensitivity bracket,
not a confidence interval; averaging geometries or calling their midpoint an
uncertainty estimate requires a separately stated convention. Numerical
step-sensitivity, stationarity and retained raw evidence are required for both
branches. A derived composite geometry is not automatically a verified minimum
of a single electronic potential.

## Conditional implementation and remaining native validation

[`topos/cfour_counterpoise.py`](../topos/cfour_counterpoise.py) now implements
`CfourCounterpoiseGeometryProtocol`, a strict `CfourCounterpoiseLeg` contract,
`run_cfour_counterpoise_leg` and `execute_cfour_counterpoise_recipe`. The physical
fragment molecule remains separate from its full real/ghost basis-center inventory.
The dedicated parser checks the native version, `GH`/`SPECIAL` basis mapping,
physical electron count, nuclear repulsion, declared occupied-core selection,
solver and retained basis-library identity. It does not relax the ordinary-molecule
parser or rename the historical output as CFOUR 2.1.

The supported frozen-core convention is explicit and restricted to H–Ne:
H/He contribute zero occupied core orbitals and Li–Ne contribute one. The adapter
uses that physical-nucleus count to select the lowest occupied orbitals with
`DROPMO`; ghost centers contribute none. This is a conventional energy-ordered
core space, not atom-local orbital localization. The all-electron CV leg drops
no orbitals. Different conventions or unknown native output grammar are rejected.

The durable driver performs sixteen component optimizations: eight raw and eight
relaxed-total CP surfaces, followed by separate CBS/CV/fT/fQ geometry combinations.
All displaced coordinates rebuild the basis-center inventory. Both combined
structures and their equilibrium rotational constants are retained, without
averaging the structures or inventing a confidence interval.

[`test_cfour_counterpoise.py`](../tests/v010/test_cfour_counterpoise.py) distinguishes
contract checks, analytical surface/driver checks and the unchanged historical
native fixture. These checks exercise physical/core separation, the relaxed-total
formula, ghost-center motion, sixteen-branch accounting, resource interruption,
and rejection of changed inputs or executables. The 1.2 fixture is deliberately
rejected by the 2.1 execution parser; it only establishes historical coordinate
and basis subgrammar.

Native correlated CFOUR 2.1 acceptance remains outstanding. No authentic 2.1
frozen-core `CCSD(T)`, ECC `CCSDT` or NCC `CCSDTQ` ghost output was established in
the inspected public sources or local runtime. Modern public HF/MP2 ghost tests
and TOPOS's ordinary-molecule high-order fixtures do not jointly prove that
combination. An authorized native execution must validate the complete method,
core-space, basis-motion derivatives and both geometry branches before this
conditional implementation can be called scientifically verified. CFOUR is not
available in the current local runtime; no simulated native result is presented
as such evidence.
