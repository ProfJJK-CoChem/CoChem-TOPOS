# Explicit R2 rotational-correction transfer

The selected alternative `r2-b3lyp-d4-vpt2-transfer-v1` changes the anharmonic reference functional to **B3LYP-D4/def2-TZVPP**, with def2/J RIJCOSX, ExtremeSCF, DEFGRID3 and the strict stationary-reference profile. It separately optimizes this unconstrained DFT geometry. Native ORCA 6.1.1 Hessian and VPT2 results then supply the correction in

\[
 B_{0,i}^{\mathrm{approx}}=B_{e,i}^{\mathrm{R2}}+
 \left(B_{0,j}^{\mathrm{DFT}}-B_{e,j}^{\mathrm{DFT}}\right),
\]

where each target principal axis \(i\) is explicitly matched to reference axis \(j\). This is a transferred approximate rotational correction; it is not a VPT2 force field evaluated on the constrained R2 surface. It does not transfer vibrational frequencies, centrifugal distortion constants, intensities or thermal functions. No experimental accuracy follows from completing the computation.

The archived wB97X-V reference is **not** silently replaced. ORCA's functional-specific manual states that wB97X-V and wB97M-V use the VV10 nonlocal term and that second derivatives of the NL functional, including analytic Hessians, are unavailable. Analytic gradients and numerical frequencies are available. ORCA's VPT2 implementation requires analytic Hessians. Accordingly `orca_frequency_input` rejects these two VV10 functionals for analytic Freq and native VPT2, citing the manual. Merely observing that the general frequency chapter supports HF/DFT is insufficient to establish this functional-specific capability.[1–3]

## Geometry, axes and masses

ORCA VPT2 explicitly rotates its input geometry into a principal-axis frame. Its final `Geometry` table prints that equilibrium geometry and the updated VPT2 atomic masses. The public native output used to verify this grammar includes the initial rotation notice and matching final geometry; it is ORCA 6.1.0 parser evidence, not TOPOS 6.1.1 execution acceptance.[4] The adapter requires a proper atom-preserving rigid transformation between the final native table and the requested equilibrium reference (maximum residual 2e-7 Å). It transforms the Cartesian Hessian back into the reference frame before checking it against the independently calculated same-level Hessian. Reflections are not accepted.

Both reference and target inertia tensors use the **same native VPT2 masses**, retained per atom at their printed 1e-6 u precision. The masses are checked against the expected isotope identities, without asserting equality to the independent TOPOS default atomic-data convention. Reconstructed reference equilibrium constants must reproduce the native printed `B_e` within its rounding and the mass/coordinate printing precision. Earlier geometry-stage rotor constants using TOPOS default isotope masses remain a separate observable and must not replace these mass-consistent target constants. Arbitrary explicit-isotope VPT2 is not implemented by this native adapter and is rejected.

`RotationalTransferOptions` requires an explicit same-basin, semirigid declaration. The implementation also checks exact atom IDs/order, elements, charge, multiplicity, isotope labels, fragment states, environment, declared bonds and stereochemistry; inferred connectivity; geometric stereochemical preservation; aligned RMSD; and all pair-distance changes. These are rejection screens, not a proof of a shared conformational basin or torsional barrier.

The default limits are RMSD ≤0.15 Å, maximum pair-distance change ≤0.3 Å, minimum relative principal-moment gap ≥0.01, matched absolute axis overlap ≥0.95, best-vs-second axis-assignment score margin ≥0.1, and absolute correction/target constant ≤0.1. Options are bounded and persisted. Near symmetric tops, incompatible axes, excessive corrections and principal-constant order crossings are rejected. Native modes below 50 cm⁻¹ and nonstationary/unstable reference Hessians are rejected upstream. The branch consequently does not cover floppy complexes through an unsupported harmonic approximation.

## Evidence and implementation boundaries

`calculate_rotational_transfer` is a pure geometry/physics API and always records `native_execution_verified=False`. `transfer_rotational_correction` additionally requires completed, converged, real ORCA 6.1.1 B3LYP-D4 native VPT2 evidence; verifies every inventoried artifact hash; reparses the native rotor and geometry tables; reparses the reference `.hess` and `.engrad`; checks native completion and method identity; and recomputes stationary minimum classification. Matrix orchestration retains the separate optimization and VPT2 attempt identities.

Tests cover genuine public output grammar, analytic tensor rotations, quadratic-form/gradient invariance, independent geometry rotations/translations, mass consistency, axis reordering, near-degeneracy, small-deformation/large-axis-rotation rejection, identity drift, and correction limits. The licensed native VPT2 acceptance test also exercises the evidence-bound transfer on its genuine stationary water reference and rejects altered reference-Hessian metadata. It is skipped when ORCA is absent. Parser/math tests do not certify hosted execution or the scientific accuracy of the R2 approximation.

## Sources

1. ORCA 6.1 manual, §3.4.2, [Non-Local Dispersion Correction (VV10): DFT-NL](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/dispersioncorrections.html#non-local-dispersion-correction-vv10-dft-nl), especially “Some notes on the NL corrections in ORCA.” Retrieved 2026-10-07; locally cached as `orca-dispersioncorrections.txt`.
2. ORCA 6.1 manual, [Vibrational Frequencies](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/frequencies.html), analytic-method restrictions and mass dependencies.
3. ORCA 6.1 manual, [Anharmonic Analysis and Vibrational Corrections using VPT2](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/vpt2.html), analytic-Hessian requirement, stringent convergence, updated masses, and semirigid applicability.
4. Public ORCA 6.1.0 [furan VPT2 output](https://github.com/physicien/parser_vpt2/blob/main/data/VPT2_furan_vpt2.out), SHA256 `4e0d6e4af1dc91d836911526d49cc2870b33baf1171af794fc608729a9937e72`; exact excerpts retained in `tests/fixtures/orca61-vpt2-public-geometry.txt` and `orca61-vpt2-public-furan.txt`.
