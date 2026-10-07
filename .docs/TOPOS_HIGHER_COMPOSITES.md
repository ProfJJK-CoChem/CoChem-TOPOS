# Explicit higher-order geometry composites

`T3C-1w` has a conditional, parameterized CFOUR implementation in
[`higher_composite.py`](../topos/higher_composite.py). A licensed, BASE-audited
public CFOUR 2.1 installation is required. CFOUR has **not** been executed in
this development environment. Implementation and mathematical/parser tests do
not establish native runtime acceptance or the matrix's benchmark accuracy.

## Exact requested calculation

`MatrixInputs.higher_geometry` supplies a `HigherGeometryProtocol` with all of
these explicit choices: pinned native version and GENBAS SHA-256; consecutive
CCSD(T) CBS bases; an inverse-power **geometry** extrapolation exponent;
core-valence, full-triples, and full-quadruples increment bases; a complete
independent internal-coordinate chart; and numerical derivative parameters.
`external_resolution="cfour-topos-cartesian-optimizer-v1"` acknowledges the
outer TOPOS optimizer instead of CFOUR's native internal-coordinate optimizer.

Eight component geometries are computed. The parameter-wise definition is

```text
R_CBS = R_fc-CCSD(T),X + (R_fc-CCSD(T),Y - R_fc-CCSD(T),X)/(1 - (X/Y)^p)
R = R_CBS
    + [R_ae-CCSD(T),CV - R_fc-CCSD(T),CV]
    + [R_fc-CCSDT,T - R_fc-CCSD(T),T]
    + [R_fc-CCSDTQ,Q - R_fc-CCSDT,Q]
```

Each difference uses the same explicit basis on both sides. Full quadruples
means **CCSDTQ**, not perturbative CCSDT(Q). The formula extrapolates optimized
internal parameters; it does not minimize a CBS-extrapolated energy surface.
Torsional increments use the shortest periodic direction. Cartesian frames
are never added. Rank-deficient coordinate charts, changed atom/isotope/state
identity, and ambiguous or changed stereochemistry are rejected.
Both component geometries and the reconstructed result must retain the inferred
bond topology. Even these checks do not prove all component optimizations
remain in the same torsional potential well. That same-conformer assumption is
reported explicitly as unverified, and all component internal parameters remain
available for inspection.

The CCSD(T) and CCSDT component optimizations use native analytic gradients.
CCSDT uses `CC_PROG=ECC,ABCDTYPE=STANDARD`: AO integral treatment is not available
for full triples. The full-quadruples component instead uses native
`CALC_LEVEL=CCSDTQ,CC_PROG=NCC,ABCDTYPE=STANDARD,DERIV_LEVEL=ZERO` energies.
TOPOS forms central differences at `h` and `h/2`, keeps the finer gradient,
and rejects excessive step disagreement at every optimization evaluation.
Both final maximum and RMS gradient criteria must hold after adding the
observed disagreement as a conservative convergence margin. The two-step
comparison is a sensitivity check, **not** a rigorous error bound.

Every actual energy displacement is its own durable native component.
Cancellation and a shared geometry deadline cover all eight optimization
components and all displacements. Resume verifies and reuses completed native
components; it does not claim to restart interrupted CFOUR CC amplitudes.
The result retains component methods, solver provenance, raw artifacts,
geometry digests, gradient diagnostics, and actual attempt IDs.

The constructed geometry supports an equilibrium rotational-constant analysis
using the requested isotopic masses. It is not an independently verified
minimum, a composite electronic energy, a vibrationally corrected structure,
or a transferable `0.04%` accuracy claim. No native `FCMFINAL` is invented.

## Source evidence and its limits

1. The pinned public [ASH CFOUR documentation, lines 120–134](https://github.com/RagnarB83/ash-documentation/blob/1230964f43ebe62fa894527794d9b85b39ecbf96/docs/CFour-interface.rst#L120-L134)
   describes `CC_PROG='NCC'` as “Recommended for CCSDT(Q) and CCSDTQ. Only
   closed-shell.” It describes `ABCDTYPE='AOBASIS'` as “available up to
   CCSD(T).” The matching [ASH adapter](https://github.com/RagnarB83/ash/blob/f43c421f3bca48e3740bab7a10acb5a2676246a0/ash/interfaces/interface_CFour.py#L83-L87)
   switches higher CC methods to `STANDARD`. This documents a native command
   contract, not proof that a particular installed binary supports it.
2. The pinned [QCEngine 0.51.0 CFOUR harvester](https://github.com/MolSSI/QCEngine/blob/v0.51.0/qcengine/programs/cfour/harvester.py)
   parses native NCC iteration completion and method-specific total energies.
   TOPOS additionally requires the exact native version, method, basis, core
   treatment, solver, native `xncc` invocation, and complete successful driver
   subprocess termination. An MRCC-backed output cannot impersonate NCC.
3. The immutable [historical native NCC CCSDT output](https://github.com/HPQC-LABS/AI_ENERGIES/blob/3098f558135589f5acf52474428ba020a561d58d/H2O/9z_cfour-ncc.txt)
   is retained unchanged as a parser fixture with a SHA-256 manifest. It tests
   convergence/energy grammar only. It lacks the parent driver header and is
   neither a complete native execution receipt nor a CCSDTQ calculation.
4. The [Psi4 CFOUR option source](https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/psi4/src/read_options.cc)
   documents ECC support for closed-shell CCSDT and states that DBOC is
   available for “HF-SCF and CCSD using RHF or UHF reference functions.” Its
   option list does not establish general analytic quadruples or DBOC
   geometry derivatives. The direct CFOUR manual was inaccessible through
   the environment network during this review; no claim depends on having
   read an inaccessible manual page.

## Rows that remain distinct

`T3O-1w` additionally requests a **counterpoise-bracketed geometry**. A frozen
interaction-energy CP correction or an unbracketed CFOUR geometry is not that
deliverable. This adapter refuses that row until the genuine bracketed
geometry calculation is available.

`T3C-1mo` additionally requests relativistic and DBOC geometry increments.
The presence of `RELATIVISTIC=DPT2`/`X2C1E` and `DBOC=ON` keywords alone does not
specify compatible increment methods, bases, nuclear masses, or geometry
derivatives. Native DBOC is an energy correction: it cannot be added directly
to a geometry or rotational constant. The matrix's broader HF/MP1/MP2/CCSD
statement also exceeds the cited option documentation and requires explicit
version-specific resolution. The current adapter refuses this row; it does
not substitute zero corrections or claim those quantities were computed.

There is a concrete acceptance trap in the immutable [historical carbon-13
DBOC output](https://github.com/HPQC-LABS/AI_ENERGIES/blob/3098f558135589f5acf52474428ba020a561d58d/C/DBOC/aug-cc-pCVDZ-NR/CFOUR_13C.txt):
it prints `0.0015685427 a.u.` and the carbon-13 mass, then reports
`SIGSEGV, segmentation fault occurred` during “Evaluating DBOC using custom
masses”; `xjoda` finishes with status `44544`. This is CFOUR 2.00beta/UHF
historical evidence of a failed run, not successful public 2.1 mass-resolved
acceptance. A DBOC number in stdout cannot replace the complete native
termination, electronic-state, isotope, and correction-definition checks.

Validation is in [`test_higher_composite.py`](../tests/v010/test_higher_composite.py).
It includes exact extrapolation models, coordinate-frame/isotope checks,
analytic model-potential derivative comparisons, cancellation/deadline checks,
native input restrictions, and the authentic historical NCC parser fixture.
Numerical model-potential tests are explicitly labelled; no fabricated native
CFOUR output is used to claim an executed scientific calculation.
