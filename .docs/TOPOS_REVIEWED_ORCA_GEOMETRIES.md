# Explicit ORCA geometry alternatives for TOPOS 0.1.0

The user authorized explicitly named ORCA alternatives with their scientific
differences documented. The original `wiki/Method_Matrix.md` and its v4 catalog
remain unchanged. `topos/data/reviewed_matrix_v010.py` defines a separate reviewed
revision. Every selected plan and derived result records its revision, canonical
SHA-256, exact variant, archived matrix SHA and sources. Resuming a campaign after
that recorded definition changes is rejected. The archived benchmark and timing
claims are not inherited by these alternatives.

| Archived row | Explicit `source_resolution` | Native electronic model |
|---|---|---|
| T3O-1d | `orca-f12d-numerical-geometry-dz-v1` | RHF frozen-core CCSD(T)-F12D/RI, cc-pVDZ-F12, cc-pVDZ-F12-CABS, cc-pVDZ/C |
| T3O-1mo | `orca-f12d-numerical-geometry-tz-v1` | RHF frozen-core CCSD(T)-F12D/RI, cc-pVTZ-F12, cc-pVTZ-F12-CABS, cc-pVTZ/C |

Both specify conventional HF integrals, `VeryTightSCF`, CPU execution and
gas-phase closed-shell states. Canonical ORCA F12D/RI is a different approximation
from local DLPNO, MPQC or Molpro F12b. No MPQC/Molpro label, analytic F12 gradient,
complete-basis result, reference accuracy or time-tier guarantee is asserted.
The [ORCA 6.1 correlated-method manual](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/mdci.html)
describes the native F12 approximations; the
[basis manual](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/basisset.html)
documents the separate orbital, fitting and complementary bases. The Hamiltonian
is selected explicitly; an orbital basis containing `F12` is not sufficient.

## Numerical geometry protocol

`matrix_inputs.orca_numerical_geometry` contains the exact energy protocol and
explicit numerical controls. TOPOS evaluates central differences at displacement
`h` and `h/2`, retaining the finer derivative. The largest difference between
those gradients must lie below the declared sensitivity threshold, which cannot
exceed one quarter of either stationarity threshold. A gradient evaluation needs
up to `12*N + 1` actual scalar energies for `N` atoms, before exact reuse. This is
substantially more expensive than an analytic-gradient calculation.

The external L-BFGS-B driver requires both maximum and RMS gradients, including
the measured displacement-sensitivity margin, below the declared bounds. Their
limits cannot be looser than `1e-5` and `3e-6` hartree/bohr respectively. This
sensitivity is a diagnostic, not a rigorous uncertainty estimate; noisy energy
calculations may fail it. Exact electronic identity, final inferred connectivity
and mapped stereochemistry must be preserved.

The calculation reports stationary geometry, actual electronic energy,
rigid-rotor constants at that geometry and numerical-gradient diagnostics. It does not establish a
minimum without a Hessian, provide vibrational corrections or certify experimental
accuracy. All native inputs, outputs and energy components are retained. A shared
geometry deadline bounds the entire optimization. Accepted-iteration checkpoints
restart the optimizer from verified coordinates; full L-BFGS history is not claimed
restored. Completed energy components can be reused only under their exact immutable
geometry/protocol identities and verified raw evidence.

The earlier `orca-f12-reference-singlepoint-v1` option remains an explicitly
energy-only compatibility branch. It does not complete either new geometry recipe.

## Validation scope

Tests reject method/core/basis/CABS drift, loose stationarity settings, changed
reviewed revisions, missing engines and cancelled runs. Mathematical functions test
optimizer semantics. A genuine xTB energy-only optimization was independently
checked against xTB's analytic gradient to validate the engine-independent numerical
driver. That test is not ORCA evidence. Actual licensed ORCA 6.1.1 executions remain
necessary to establish native acceptance of these F12 geometry campaigns.
