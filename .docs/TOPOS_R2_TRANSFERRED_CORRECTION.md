# Reviewed R2 rotational correction

The explicit `r2-b3lyp-d4-vpt2-transfer-v1` variant implements the user's
2026-10-07 choice of a separately optimized DFT VPT2 reference and an approximate
transferred rotational correction. The request must select this variant; it is
never an automatic fallback from the archived method.

The target geometry retains the R2 frozen-monomer wB97M-V/def2-QZVPP protocol,
including the residual frozen-coordinate gradients and rigid-monomer drift.
Its monomer shapes and source declarations are explicitly bound to supplied
geometries. Its interaction energy uses ordinary frozen-core
DLPNO-CCSD(T1)/cc-pVDZ-F12 TightPNO with three complex-basis counterpoise legs.
Here the F12 suffix identifies the orbital basis, not an F12 Hamiltonian or CABS.

A separate **unconstrained B3LYP-D4/def2-TZVPP** optimization uses the strict
VPT2 reference profile, then native ORCA VPT2 runs only on that independently
stationary full-dimensional DFT reference. All native stages must actually
complete and preserve the exact atom mapping, composition and isotope labels.
No VPT2 force field is computed at the nonstationary frozen-monomer target.

This reference differs scientifically from archived wB97X-V/def2-TZVPP. ORCA
6.1 excludes VV10/nonlocal dispersion from analytic Hessians; native VPT2
requires analytic Hessians. The retained `r2-separate-dft-vpt2-transfer-v1`
wB97X-V plan therefore remains explicitly unavailable. Numerical frequencies
cannot be relabeled as native VPT2. The B3LYP-D4 functional and dispersion change
is recorded in both the separately hashed reviewed method revision and each
actual native attempt.

The transferred observable is

`B0_approx = B_R2 + (B0_DFT − Be_DFT)`.

The correction helper uses one attested native mass convention for both inertia
tensors and checks atom-preserving alignment, nondegenerate principal axes and
unambiguous axis correspondence. It retains the separate geometries, native
spectroscopic tables, axis matching, structural-change diagnostics and explicit
semirigid/same-basin applicability declaration. Earlier TOPOS mass-table rotor
values remain separately identifiable; they are not mixed silently with a native
mass-weighted correction.

The result is an approximate composite. Structural and axis checks do not prove
transferability or sampling completeness. Functional error, basin transfer and
large-amplitude motion can dominate; no matrix benchmark or experimental accuracy
claim is transferred, and no uncalibrated numerical error bar is invented.
Soft-mode, linear, degenerate-axis, isotope, mass or native-capability failures
remain explicit unsupported/partial outcomes with retained evidence.

One matrix deadline bounds the entire campaign, including a requested geometry
budget. Completed verified geometry, counterpoise, DFT optimization and VPT2
components can be reused on resume. An incomplete native VPT2 force field starts
fresh; its old raw attempts remain retained. Native binary/version identities
must agree across the accepted target derivative, CP, DFT optimization and VPT2.

Sources:

- [ORCA 6.1 VPT2](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/vpt2.html)
- [ORCA 6.1 dispersion corrections](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/dispersioncorrections.html)
- [R2 counterpoise implementation](TOPOS_R2_COUNTERPOISE.md)
