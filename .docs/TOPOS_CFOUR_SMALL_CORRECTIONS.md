# CFOUR scalar and mass-dependent geometry corrections

The conditional scalar adapter in [`cfour_corrections.py`](../topos/cfour_corrections.py)
executes one explicit approximation: all-electron RHF with the same named,
uncontracted basis for the nonrelativistic and spin-free X2C-1e Hamiltonians.
The caller supplies the basis, native GENBAS path/hash, internal-coordinate
chart, finite-difference step and convergence tolerances. No default basis or
benchmark accuracy is assigned. A separate conditional native-default-mass HF
DBOC adapter is available in [`cfour_dboc.py`](../topos/cfour_dboc.py). Neither
adapter certifies the original `T3C-1mo` rotor deliverable: numerical native
masses and arbitrary isotope-dependent DBOC remain unresolved.

## Executable scalar leg

`ScalarRelativisticProtocol` accepts public CFOUR **2.1**, `CALC_LEVEL=SCF`,
`REFERENCE=RHF`, `FROZEN_CORE=OFF`, `CONTRACTION=UNCONTRACTED`, and
`RELATIVISTIC=X2C1E` or the matching `OFF` reference. `DBOC=OFF` is explicit.
`run_scalar_relativistic` executes through BASE by default and requires the
native input, GENBAS and protocol to remain unchanged. It verifies the actual
Hamiltonian/contraction/core/reference/basis/state, requested geometry, SCF
convergence, native version and complete native subprogram termination. The
X2C leg additionally requires successful `xvpropx2c` execution. A keyword
echo, scheduler exit zero or SCF number alone cannot complete the result.

`calculate_scalar_geometry_correction` optimizes both surfaces independently,
using native energy evaluations and checked central differences at `h` and
`h/2`. The measured step disagreement must be at most one quarter of both
gradient thresholds; the final gradient plus that disagreement must satisfy
both thresholds. These are numerical energy derivatives, not claimed analytic
relativistic gradients. Completed native evaluations are recovered only through
the immutable component ledger; the outer optimizer restarts and reuses matching
energies. Interrupted native CC/SCF state is not represented as resumable state.

The geometric correction is assembled parameter-wise in the supplied complete,
independent internal-coordinate chart:

\[
R_{\mathrm{corrected}}=R_{\mathrm{base}}+
  (R_{\mathrm{HF/X2C1e}}-R_{\mathrm{HF/nonrelativistic}}).
\]

Both scalar legs use the same basis and contraction. Atom mapping, isotopes,
electronic state, declared chemical identity, topology, stereochemistry, chart
rank and reconstruction residuals are checked. A bare energy correction is
never added to a bond length or rotational constant. This HF increment omits
correlated relativistic response. Shared topology/stereochemistry does not prove
that independently optimized structures belong to the same torsional well.
The assembled geometry has no independently verified Hessian or stationary-point
claim. It is a scalar leg, not a complete small-correction set.

The [pinned Psi4 CFOUR option source](https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/psi4/src/read_options.cc#L4687-L4698)
defines `DPT2` as second-order direct perturbation theory and `X2C1E` as the
spin-free X2C-1e treatment. The new adapter implements the latter only; a `DPT2`
value is rejected rather than treated as an alias. An [authentic historical
Ne output](https://github.com/HPQC-LABS/AI_ENERGIES/blob/3098f558135589f5acf52474428ba020a561d58d/Ne/x2c-unc/2z/ccsd.txt)
shows `RELATIVISTIC=X2C1E`, `CONTRACTION=UNCONTRACTED`, `xvpropx2c` and successful
native completion. That output is CFOUR **2.00beta/CCSD**, not a current native
2.1/HF execution: it establishes historical syntax and control grammar only.
The production parser rejects it as evidence for the requested 2.1 profile.

## Restricted native-default-mass HF DBOC leg

`DefaultMassDBOCProtocol` requires an explicitly selected
`mass_convention: cfour-2.1-native-default-masses-v1`, orbital basis,
contraction (`GENERAL` or `UNCONTRACTED`) and the native GENBAS path/hash. The
profile is public 2.1, all-electron HF/RHF, isolated singlet, nonrelativistic,
and restricted to **H, C, N, O and F**. Every explicit isotope is rejected,
including an explicit label for a common primary isotope. The adapter writes
no `ISOMASS` or `%isotopes` input, requires an empty native directory and rejects
an `ISOMASS` file that appears during execution. This is an explicit choice of
the engine's default convention, not a claim that its numerical masses have
been independently attested.

The compiler uses documented `DBOC=ON` Cartesian input. It omits a conflicting
`DERIV_LEVEL=ZERO`: authentic successful DBOC output enables internal response
and second-derivative machinery. That machinery is not misrepresented as an
analytic derivative of the DBOC-corrected potential. Native default-mass
completion requires `readis is F`, no custom-mass path, consistent nonnegative
Hartree totals, exact requested electronic state/method/basis/version and
successful completion of every native subprogram. The historical default-mass
output prints its total twice; consistent repetitions are retained. The
QCEngine harvester's generic `CCSD DBOC ENERGY` label is not used to label an
HF result: the requested HF method is independently verified and the correction
is parsed separately.

`run_default_mass_dboc` stores **HF electronic energy alone** in the ordinary
electronic-energy field. Its native-result metadata separately stores DBOC,
`E_HF + DBOC`, the potential definition and output rounding bounds. An absent
engine or missing DBOC output produces no zero correction. The separately
executed reference leg explicitly sets `DBOC=OFF`.

`calculate_default_mass_dboc_geometry` performs the two same-basis,
same-contraction optimizations and assembles:

\[
R_{\mathrm{corrected}}=R_{\mathrm{base}}+
\left(R_{\min[E_{\mathrm{HF}}+E_{\mathrm{DBOC,native\ default}}]}
-R_{\min[E_{\mathrm{HF}}]}\right).
\]

Native energies use the same durable component ledger as the scalar leg. The
outer numerical optimizer uses both `h` and `h/2` derivatives. It additionally
bounds the derivative error from rounded native energies: if each endpoint has
rounding bound `epsilon`, the finer central derivative contributes at most
`2*epsilon/h`. This bound plus the observed step disagreement must be below
one quarter of both convergence thresholds and is included in the final
gradient acceptance test. A ten-decimal Hartree correction has a rounding bound
of `5e-11 Eh`; agreement of two rounded derivatives cannot turn that precision
limit into zero error.

The report explicitly records `native_numeric_masses_verified: false` and
`rotor_mass_attestation_available: false`. The successful historical default-mass
job does not print a numeric atomic/nuclear mass table. TOPOS therefore does
not substitute its Mendeleev masses or a historical table as alleged native
CFOUR masses. The combined conditional geometry pipeline may retain the
corrected geometry, but **withholds rotor constants and full original-row
completion** until matching native mass evidence exists. Arbitrary isotope
handling, correlated DBOC, benchmark accuracy and stationary-point/Hessian
certification are not claimed.

## Exact remaining DBOC blocker

The supplied matrix requests a mass-dependent DBOC geometry increment, but does
not choose its electronic method, basis, mass convention or subtraction surface.
The [pinned Psi4 option documentation](https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/psi4/src/read_options.cc#L3891-L3895)
documents `DBOC=ON` **energies** at HF-SCF and CCSD with RHF/UHF. It does not
establish the matrix's broader HF/MP1/MP2/CCSD availability statement or analytic
DBOC geometry derivatives. The independently published [ASH interface](https://github.com/RagnarB83/ash/blob/f43c421f3bca48e3740bab7a10acb5a2676246a0/ash/interfaces/interface_CFour.py#L459-L484)
demonstrates Cartesian DBOC input, but provides no explicit isotopologue mass
binding in that path. Its [energy extraction](https://github.com/RagnarB83/ash/blob/f43c421f3bca48e3740bab7a10acb5a2676246a0/ash/interfaces/interface_CFour.py#L577-L585)
does not establish a successful mass-resolved native run by itself.

The [public carbon-13 output](https://github.com/HPQC-LABS/AI_ENERGIES/blob/3098f558135589f5acf52474428ba020a561d58d/C/DBOC/aug-cc-pCVDZ-NR/CFOUR_13C.txt)
prints `0.0015685427 a.u.`, reads `ISOMASS`, prints atomic mass `13.003354838`
and nuclear mass `13.000063358`, then fails with `SIGSEGV` and native `xjoda`
status **44544**. Its scheduler footer nevertheless says “Job completed
successfully” and exit zero. A [second independent job for carbon cation](https://github.com/HPQC-LABS/AI_ENERGIES/blob/3098f558135589f5acf52474428ba020a561d58d/C%2B/DBOC/aug-cc-pCV2Z-NR/CFOUR_CCSD_13C.txt)
has the same mass-evaluation failure. Neither is successful isotope-resolved
acceptance. A [default-mass carbon job](https://github.com/HPQC-LABS/AI_ENERGIES/blob/3098f558135589f5acf52474428ba020a561d58d/C/DBOC/aug-cc-pCVDZ-NR/CFOUR.txt)
finishes normally and prints `0.0016997291 a.u.`, but does not establish how to
select and validate arbitrary requested isotope masses in public 2.1.

To extend the restricted leg to isotope-specific rotor closure, the required
evidence/choices are:

1. A version-specific public 2.1 mass-input specification and a normally completed
   molecular HF example binding every atom ID to its requested isotope. It must
   distinguish supplied atomic masses from nuclear masses used in the correction.
2. An explicit HF basis and paired surface convention, such as the implemented independent
   optimization of `E_HF + E_DBOC(isotopes)` versus `E_HF` at that same basis,
   followed by an additive internal-coordinate difference. This is a declared
   small-correction approximation, not a default consequence of `DBOC=ON`.
3. A validated native result section that associates the DBOC with those masses,
   with every native subprogram successful. Native 2.1 finite-difference checks
   must demonstrate that the energy output precision supports the requested
   geometric convergence; a fixed ten-decimal DBOC printout can otherwise
   dominate derivative noise.

The CFOUR manual's relativistic, DBOC and isotope pages returned proxy-level
403 denial on 2026-10-07. No alternate access mechanism bypassed that denial;
the independently published sources above were fetched through ordinary HTTPS.
Unknown mass-file syntax, estimated isotope masses, a default-zero DBOC, and
the earlier ORCA resolution of MPQC/Molpro conflicts are not substitutes.

## Validation scope

[`test_cfour_corrections.py`](../tests/v010/test_cfour_corrections.py) and
[`test_cfour_dboc.py`](../tests/v010/test_cfour_dboc.py) exercise
the explicit compiler restrictions, authentic historical control grammar,
rejection of the crashed isotope output, version mismatch, mathematical
coordinate/derivative checks, missing-engine behavior and durable cancellation.
Fixtures retain exact source hashes in
[`provenance.json`](../tests/v010/fixtures/cfour_corrections/provenance.json).
No licensed CFOUR executable was available for current native acceptance.
Native 2.1 X2C and default-mass HF DBOC energy/optimization, paired recovery and
isotope-dependent DBOC remain unverified scientific execution; contract tests
do not supply that evidence.
