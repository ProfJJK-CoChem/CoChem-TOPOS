# R2 scientific boundary and reviewed ORCA alternatives

Research date: 2026-10-07. This records contradictions in the scientific source,
not successful execution of a missing calculation. The original matrix remains
unchanged. A corrected protocol must be named in the request and its provenance;
an adapter must not silently choose a different Hamiltonian to satisfy a row ID.

The user has now authorized explicitly named ORCA alternatives with documented
scientific differences. The implemented [reviewed numerical geometries](TOPOS_REVIEWED_ORCA_GEOMETRIES.md)
replace the contradictory MPQC/Molpro geometry instructions. The implemented
[R2 counterpoise contribution](TOPOS_R2_COUNTERPOISE.md) uses ordinary ORCA
DLPNO-CCSD(T1) with the stated F12 orbital basis; it does not claim an F12
Hamiltonian. These decisions resolve the engine/method conflicts below.
For the anharmonic contribution, the user has selected a **separately optimized,
fully relaxed DFT VPT2 reference with transferred rotational corrections**. Its
explicit approximate composite is
`B₀(approx) = Bₑ(R2) + [B₀(DFT) − Bₑ(DFT)]`, independently for each verified
corresponding principal axis. The explicitly reviewed
[`r2-b3lyp-d4-vpt2-transfer-v1`](TOPOS_R2_TRANSFERRED_CORRECTION.md) reference is
**B3LYP-D4/def2-TZVPP**. This differs from archived ωB97X-V/def2-TZVPP: ORCA 6.1
does not provide the VV10/nonlocal-dispersion analytic Hessians required by native
VPT2 [1,6]. The original-functional plan remains unavailable; the named B3LYP-D4
variant requires explicit selection and is never a silent fallback. The
transfer is implemented, while its complete native acceptance remains pending. The
decision resolves the protocol choice, not evidence of its accuracy or successful
ORCA 6.1.1 execution. None of the reviewed alternatives inherits benchmark accuracy
from the original methods.

## T3O-3h / R2: three independent issues

The literal [matrix recipe R2](../wiki/Method_Matrix.md#9a6-the-recipe-menu-r1r9)
uses **ωB97M-V/def2-QZVPP** intermolecular optimization with frozen high-level
monomers, **DLPNO-CCSD(T1)/cc-pVDZ-F12** counterpoise energies, and
**ωB97X-V/def2-TZVPP VPT2**. r²SCAN-3c belongs to **R1 / T3O-1min**, not R2.

1. **Frozen monomers and native VPT2 describe different stationary problems.**
   The frozen optimization generally leaves nonzero intramolecular Cartesian
   forces. Changing from ωB97M-V/QZ to ωB97X-V/TZ also changes the potential, so
   even the movable intermolecular directions need not remain stationary.
   ORCA's official VPT2 protocol requires a tightly converged starting geometry,
   derives cubic and semiquartic force constants by differences of analytic
   Hessians, and excludes linear molecules and methods without analytic Hessians
   [1,2]. The documented native controls do not specify a constrained rigid-body
   anharmonic Hamiltonian or define which mixed intramolecular/intermolecular
   cubic terms to retain. `semirigid_modes=True` is an applicability declaration;
   it does not supply such a Hamiltonian.

   A Cartesian Hessian projected onto selected directions alone is insufficient
   at a constrained minimum. For a nonlinear rigid-monomer coordinate map
   **x = x(q)**, the chain rule gives

   \[
   \frac{\partial^2 E}{\partial q_a\partial q_b}
   = J_a^T H_x J_b +
   \sum_i (g_x)_i\frac{\partial^2 x_i}{\partial q_a\partial q_b}.
   \]

   The second term can survive when the Cartesian residual force is nonzero.
   Cubic/quartic derivatives, the coordinate-dependent kinetic energy metric,
   Coriolis terms, and vibration-rotation coupling require consistent treatment
   too. Dropping soft modes or zeroing forces cannot establish that treatment.

2. **The R2 title and its energy instructions name different methods.**
   The title says MPQC CCSD(T)-F12, while the detailed step and ORCA expansion say
   `DLPNO-CCSD(T1) TightPNO cc-pVDZ-F12`. The last token selects an orbital basis;
   it does not activate explicit correlation. ORCA documents separate
   `DLPNO-CCSD(T1)-F12` and `DLPNO-CCSD(T1)-F12D` methods and additional CABS and
   fitting requirements [3]. Supplying a CABS does not convert ordinary
   DLPNO-CCSD(T1) into one of those methods.

3. **Three counterpoise legs are a dimer protocol.**
   At fixed complex geometry, a dimer has one complex and two ghost-basis
   monomer calculations. An arbitrary many-fragment input needs a separately
   declared generalization. CP interaction energy excludes deformation; a
   relaxed binding energy additionally needs the isolated reference energies.
   Counterpoise does not repair a nonstationary VPT2 reference.

Reviewed choices and the selected resolution:

| Decision | Scientifically explicit outcome | Drawback / additional work |
| --- | --- | --- |
| Retain frozen R2 geometry; report equilibrium constants and CP interaction only | Preserves the intended frozen high-level monomers and measured residual forces; no B₀ claim | This is a named partial R2 result, not completion of its VPT2 step. |
| **Selected named variant:** compute a separate tightly optimized, fully relaxed B3LYP-D4/TZ native VPT2 reference; transfer its correction to R2 equilibrium constants | An explicitly approximate composite `B₀ ≈ Bₑ(R2) + [B₀−Bₑ](DFT)` with two retained geometries, the same verified native mass convention and verified principal-axis correspondence | Changes the literal frozen-manifold recipe and the archived VV10 functional. Transferability and basin correspondence require validation. Ambiguous axes, topology/stereochemistry changes or corrections outside declared bounds must prevent transfer. |
| Retain a literal frozen-monomer vibrational manifold | Requires an explicit reduced-dimensional rovibrational Hamiltonian, coordinate chart, masses/metric, coupling truncation, resonance treatment and benchmarks | Substantial new scientific implementation; a native ORCA VPT2 keyword cannot specify it. |

The selected correction is not a VPT2 calculation on the constrained R2 manifold.
Reference stationarity, a successful native analytic Hessian/VPT2 calculation,
compatible isotopic masses, axis assignment and structural correspondence are
independent acceptance requirements. Near-degenerate or ambiguous axes must not
be silently reassigned; a failed native B3LYP-D4 calculation leaves the selected
transfer unavailable. The approximate composite must retain both source geometries and
its explicit transfer assumptions when published.

For the energy leg, the reviewed implementation chooses **ordinary ORCA
DLPNO-CCSD(T1) in the stated F12 orbital basis**. An explicitly named ORCA
DLPNO-F12 variant or specified MPQC canonical F12 protocol would be different
methods, requiring their own auxiliaries and validation. None can be assigned
the other's benchmark accuracy by renaming a result.

## T3O-1d: an executable protocol cannot satisfy the contradictory wording

The [Table 3-O expansion](../wiki/Method_Matrix.md#table-3-o--orca-track) contains
`! MPQC CCSD(T)-F12 TightPNO ... NumGrad Opt`, calls the engine ORCA, and explains
the cost using the lack of DLPNO analytic gradients. Meanwhile matrix §9.0
restricts MPQC to single-point energies on geometries from a PySCF escalator.
`MPQC` is not an ORCA method keyword; TightPNO is an ORCA local-correlation
control, not the canonical MPQC wavefunction specification.

The official ORCA manual confirms that F12 gradients and DLPNO analytic
gradients are unavailable. It describes numerical DLPNO gradients as attempted
successfully, while warning that cutoff-based potential surfaces are not
perfectly smooth [3]. Thus numerical differentiation is technically possible,
but requires an explicit step-size/noise-convergence and optimizer protocol.
It does not remove the source's engine/Hamiltonian contradiction.

The official MPQC source independently defines a `CCSD(T)F12` energy class that
combines CCSD-F12 and a perturbative triples contribution. Its published input
examples use JSON wavefunction/property objects, separate orbital/fitting/
auxiliary bases and a geminal factor [4,5]. This demonstrates that MPQC is a
distinct backend. It does not certify equivalence to ORCA DLPNO-F12 or establish
an accepted geometry-optimization workflow for the matrix row.

The reviewed ORCA numerical-geometry alternative resolves the following original
choices; they are retained here to explain the scientific difference:

- Preserve the MPQC single-point restriction and revise T3O-1d into a specified
  MPQC energy refinement at an explicitly supplied optimized geometry.
- Preserve numerical geometry optimization and explicitly choose a native ORCA
  F12/local Hamiltonian, its orbital/CABS/fitting/core choices, finite-difference
  step/convergence controls and time budget. This changes the MPQC-labelled row.
- Authorize a distinct external MPQC numerical-gradient geometry optimizer,
  explicitly overriding §9.0 and supplying a complete MPQC F12 protocol and
  genuine native acceptance evidence.

The matrix's throughput and accuracy estimates cannot select this decision:
they concern different algorithms and require local calibration. In particular,
an F12 basis does not reach an exact CBS limit and cannot eliminate runtime
uncertainty.

## Official sources checked

1. [ORCA 6.1 VPT2/GVPT2](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/vpt2.html).
2. [ORCA 6.1 vibrational frequencies](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/frequencies.html).
3. [ORCA 6.1 MDCI, explicit correlation §3.10.7 and DLPNO discussion](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/mdci.html).
4. [Official MPQC CCSD(T)F12 implementation](https://github.com/ValeevGroup/mpqc/blob/98fa03e8db0481c63554dd2720164ee463e1402b/src/mpqc/chemistry/qc/lcao/f12/ccsd_t_f12.h).
5. [Official MPQC F12 JSON input example](https://github.com/ValeevGroup/mpqc/blob/98fa03e8db0481c63554dd2720164ee463e1402b/tests/validation/reference/inputs/h2o-ccsdf12-631g-pvdz-apvdz.json).
6. [ORCA 6.1 dispersion corrections and nonlocal-correlation limitations](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/dispersioncorrections.html).

The official MPQC generated-documentation host was denied by this environment's
proxy during this check. Independently published source files were read from
the project's own GitHub repository; no alternate route to the denied host was
used. ABCluster's official host subsequently responded normally and is covered
separately in [the implemented rigidmol protocol](TOPOS_ABCLUSTER.md).
