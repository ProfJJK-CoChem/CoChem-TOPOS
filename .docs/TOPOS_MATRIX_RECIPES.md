# TOPOS 0.1.0 matrix recipe contracts

The immutable matrix catalog is `method-matrix-v4-2026-08-09`, SHA-256
`d4b382c88d9734eef844e6dcaafdca06e5901c482fa0f4c17ca1efeb4f5c989d`.
`topos matrix support` reports registered complete recipes, implemented partial
branches, and the exact unresolved scientific prerequisites. These categories
are code coverage, not evidence that every engine ran successfully on a given
machine. Every calculation still requires its actual audited BASE installation.
The user-approved named ORCA alternatives are a separate reviewed 0.1.0 overlay:
the original rows remain unchanged, while selected plans/results retain the
overlay's exact scientific definition and SHA-256.

A compound request uses `purpose: matrix`, its explicit `matrix_row_id`, the
catalog revision, and structured `matrix_inputs`. There are no executable shell
fragments or unvalidated input decks in this interface. The source document's
nominal time tiers do not determine runtime estimates or guarantee accuracy.
Global, ensemble, and geometry budgets are enforced independently; native
samplers that cannot honor an internal geometry deadline reject that option.

## Rigid molecular packing

The ordinary search and association workflows accept `search_algorithm:
abcluster` with typed `abcluster_options`. The actual ABCluster 3.4 `rigidmol`
program requires a cited charge, Lennard–Jones epsilon (kJ/mol), and sigma
(angstrom) for every identified real atom. TOPOS does not invent atom types,
charges, virtual sites, or force-field parameters. Explicit fragment charges
must match the supplied atomic charges, and every fragment requires a repulsive
site. Population, generations, scout limit, packing amplitude and saved-minimum
limit are recorded native controls.

ABCluster preserves the internal monomer geometries and chooses its own random
initial packing. Its classical intermolecular scores remain raw observations;
independent quantum refinement produces the electronic candidate energies used
for deduplication, review and export. Association requests first perform the
mandatory isolated quantum monomer searches, then pack and refine the complex.
Finishing the requested generations does not certify an exhaustive search.
Native Ne2 and methanol-dimer executions verify energy units, rigid shapes and
atom identity; the public workflow tests additionally exercise real xTB
refinement, association, persistence, review and export.

The native syntax and force-field units are documented in the
[ABCluster rigidmol example](https://zhjun-sci.com/abcluster/doc/eg-h2o6.html)
and [force-field documentation](https://zhjun-sci.com/abcluster/doc/charmmff.html).
Example parameter values used in acceptance tests are explicitly attributed to
the official 3.4 distribution's `misc/charmm36` data, not fitted test outputs.

## Correlated energies and geometry

`correlated_protocol` specifies the native method, orbital basis, frozen-core
convention, operation, fitting bases, and F12/CABS or PNO choices where applicable.
An orbital basis named `cc-pVTZ-F12` does **not** activate an F12 Hamiltonian.
Canonical CCSD(T), AUTOCI CCSD(T), DLPNO-CCSD(T1), and F12D/RI remain different
protocols. Solvated, unrestricted, and unsupported spin variants are not inferred.

- **T5-12h** requires plain DLPNO-CCSD(T1)/cc-pVDZ-F12, TightPNO, TCutPNO
  `1e-7`, an explicit correlation-fitting basis and native `! LED`. The native
  final LED intra/inter decomposition is retained separately from the three-leg
  frozen interaction energy. This is not an F12 Hamiltonian or a binding energy.
- **T5-1d** evaluates consecutive TCutPNO `1e-6`/`1e-7` with otherwise identical
  settings, verifies the same HF solution, and forms
  `E_HF + E_corr(6) + 1.5*(E_corr(7)-E_corr(6))` for every frozen complex/fragment.
  The extrapolation is a PNO-convergence measure, not a canonical accuracy bound.
- **T5-3d** requires CCSD(T)-F12D/RI, cc-pVTZ-F12, cc-pVTZ-F12-CABS and an explicit
  RI correlation-fitting basis. It cannot certify the source's F12b recipe.
- **T3O-3d** requires `correlated_resolution:
  autoci-conventional-transformation-v1`. The native AUTOCI analytic-gradient
  optimization does not inherit MDCI AO-direct integral controls. It reports the
  resulting geometry and equilibrium constants, not vibrationally corrected
  constants or a Hessian-certified minimum.
- **T3O-12h** and **T3C-3d** optimize all five junChS geometry components and
  combine a supplied, independent internal-coordinate chart. The explicit
  `junchs-same-basis-core-valence-v1` resolution selects ae-minus-fc MP2 at the
  **same** cc-pwCVTZ basis, resolving contradictory source descriptions.
  Coordinate addition is not Cartesian addition. Component energies are
  retained; an electronic energy at the composite geometry is not invented.

ORCA's native method and basis contracts are documented in the
[MDCI manual](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/mdci.html),
[AUTOCI manual](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/autoci.html),
[basis-set manual](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/basisset.html),
[LED manual](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/led.html),
and [extrapolation tutorial](https://www.faccts.de/docs/orca/6.1/tutorials/workflows/extrapol.html).
Input construction and parser contracts alone do not replace a native ORCA
6.1.1 acceptance run.

## Explicit CBS + core + full-triples energy family

**T5-1w** accepts `energy_composite`, containing an exact CFOUR protocol template,
consecutive cc-pVXZ orbital bases, an explicit HF exponential coefficient,
an explicit inverse-power correlation exponent, a core-valence basis and a
full-triples correction basis. Each geometry executes eight native components:
HF and frozen-core CCSD(T) at both CBS bases, ae/fc CCSD(T) at the same CV basis,
and frozen-core CCSDT/CCSD(T) at the same correction basis.

The calculation verifies matched HF solutions and unchanged executable/GENBAS
identities before arithmetic. Extrapolation uses numerically stable denominators
and rejects ill-conditioned parameters. It forms the frozen complex energy minus
all same-protocol frozen fragment energies. No separate counterpoise, thermal
binding energy, equilibrium geometry, HEAT/Wn identity, or source benchmark
accuracy is claimed. Component coefficients and all raw inputs are retained.

## Native source resolutions and external engines

**T5-30min** requires `source_resolution:
native-composite-rawinteraction-v1`. This computes the main row's native
r2SCAN-3c frozen interaction, with native D4/gCP included in each leg. The source's
conflicting expansion promising separate raw/CP/half-CP is retained as a warning;
no extra gCP or unspecified CP correction is added.

CFOUR geometry routes require `external_resolution:
cfour-topos-cartesian-optimizer-v1`: TOPOS drives Cartesian L-BFGS-B with genuine
CFOUR analytic gradients. This differs explicitly from the source's internal
coordinate optimizer. Exact engine version and a native GENBAS path plus checksum
are required. First-order properties remain fixed-geometry properties.

**T5-1mo** supports the explicit Psi4 SAPT2+3 branch with named orbital, SCF-fit,
and SAPT-fit bases. Its interaction energy and decomposition are not a total
electronic energy. It performs no automatic PES construction and makes no
SAPT(DFT) claim. See the [version-pinned Psi4 SAPT source documentation](https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/doc/sphinxman/source/sapt.rst).

**T3O-1mo** retains an energy-only compatibility branch selected by `source_resolution:
orca-f12-reference-singlepoint-v1`. A native F12D/RI reference energy is computed
at the supplied geometry. `implemented_branch_completed` can be true while
`full_row_completed` stays false: a new Molpro F12 reference geometry is still
not supplied. This branch is excluded from the complete-recipe count.

**T3O-1d** and **T3O-1mo** also support the explicitly reviewed
`orca-f12d-numerical-geometry-dz-v1` and
`orca-f12d-numerical-geometry-tz-v1` alternatives. These execute canonical ORCA
F12D/RI energies with matching orbital/CABS/correlation-fitting bases and
checked h/h2 numerical derivatives. They report stationary geometry and rotor
constants at that geometry, without a Hessian-verified equilibrium-minimum claim.
See [the full geometry contract](TOPOS_REVIEWED_ORCA_GEOMETRIES.md).

**T5-3h** has the reviewed `orca-f12d-composite-interaction-v1` alternative:
an F12D/RI base, separately extrapolated HF+CABS and F12 correlation terms, and
same-basis MP2 core-valence correction. This is an explicitly defined ORCA
approximation, not the archived junChS-F12b Hamiltonian or its benchmark errors.
See [the exact five-component algebra](TOPOS_ORCA_F12_COMPOSITE.md).

## Native sampling and entropy

**T1-1d** runs GOAT-ENTROPY with CONFDEGEN auto and CREST entropy on identical
explicit seeds at 298.15 K. This temperature is required by the pinned CREST
3.0.2 entropy stopping implementation. Every pair must satisfy both native
stopping criteria and `abs(GOAT Sconf - CREST Sconf) < 0.1 cal mol^-1 K^-1`.
CREST total entropy and its delta-RRHO correction are preserved separately and
are not substituted for configurational entropy. Failed comparisons retain the
actual trajectories and return partial convergence evidence.

**T1-1mo** executes GOAT-DIVERSITY and CREST `--v4` for every explicit seed,
reoptimizes all frames at a common GFN2 level, invokes native CREGEN and performs
actual DLPNO-CCSD(T1) reranking under one explicit protocol. GOAT-DIVERSITY retains
its documented SloppyOpt, 0.5-Angstrom structural filter and 60-kcal/mol window;
it is not silently tightened into ordinary GOAT. The finite union is never
reported as proof of exhaustive sampling.

See the [ORCA GOAT manual](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/goat.html)
and [CREST 3.0.2 source](https://github.com/crest-lab/crest/tree/v3.0.2), especially
`src/confparse.f90` and `src/entropy/entropy.f90`, for native algorithm and stopping
semantics.

**T1-30min** requires a hash-bound AIMNet2 manifest and an explicit concurrent
ML/ORCA allocation. Native GOAT-EXPLORE uses the persistent BASE-authorized
ExtOpt model. Raw ML values remain sampling observations; reported candidates
are actually refined at r2SCAN-3c and passed through Stage-A native CREGEN.
Checkpoint identity, force units, callback receipt capacity, and host/GPU budgets
remain explicit. A trained model or a model disagreement is not a DFT result.

**T1-1w** requires 100–500 provenance-verified DFT configurations, explicit
group-disjoint train/validation/test partitions, and GPU float64 MACE training.
Held-out errors are reported independently of the training objective. Both
native GOAT and native CREST then use the identical trained checkpoint, followed
by actual common r2SCAN-3c refinement and Stage-A native CREGEN. The input
manifest, training protocol, concurrent resource allocation, callback limits and
receipt-storage ceiling are explicit scientific inputs.

Stock CREST 3.0.2 caches stale generic-calculator paths across its parallel
sampling jobs. This route therefore requires the source-pinned
`3.0.2+topos-generic-paths-v1` build, its source patch and installation manifest,
verified executable/source hashes, and BASE authority. The planner and compound
workflow check this requirement before training. The patch and native interface
passed a real CPU MACE/CREST reduced-profile campaign with all six production
metadynamics runs and 3,851 successful model callbacks. This proves that native
interface, not GPU training, a full default campaign, or the complete combined
GOAT/CREST workflow. Those acceptance scopes remain separate.

## Recovery and verification limits

Completed native components are reused only when their typed protocol, geometry,
result payload and retained artifact hashes match. Failed native attempts retain
separate fresh directories. Outer matrix children resume their durable workflows;
completed derivative evaluations are not intentionally discarded. A corrupted
basis, molecular identity, inferred topology, stereochemistry or raw artifact
cannot certify a completed component.

Focused development validation exercised actual xTB 6.7.1, CREST 3.0.2 (including
`--v4`, screening and CREGEN), and Psi4 1.10.2 SAPT2+3. Mathematical fixtures test
composite formulas; negative corruption tests reject altered real results.
Licensed ORCA/CFOUR execution evidence must be supplied by their native acceptance
runs. See the generated support report for remaining scientific source conflicts
and missing complete adapters; their catalog entries remain visible.
