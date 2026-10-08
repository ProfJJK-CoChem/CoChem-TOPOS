# CFOUR T3C-1h: correlated EFG acquisition and conditional nuclear conversion

T3C-1h requires fixed-geometry native **CCSD(T)/cc-pVTZ**, `PROPS=FIRST_ORDER`,
correlated dipole components and **EFG → χ**. `PVTZ` remains the reviewed native
basis alias. Frozen-core treatment is explicitly supplied and retained; no
all-electron result certifies a frozen-core result. A dipole-only result cannot
complete this row. The exact archived matrix conversion factor remains
**234.96474 kHz/(atomic-unit EFG × millibarn)** [1].

## Genuine native grammar and retained failure

Private BASE Actions run [37717679093][2], attempt 1, used TOPOS
`663a97bb435b48b322a4d85cd591412986323687`, BASE
`14202e182e1fa4f99258ed32a8ae9ba8c1c565ad` and native CFOUR 2.1. Native CCSD(T)
subprograms completed successfully, while the hosted TOPOS component failed
because `qcengine` was unavailable. The original failure is preserved.
Offline parsing of its authentic native output does not relabel the job as a
successful current-source workflow, scientifically eligible matrix-domain case,
or full-row acceptance. The diagnostic molecule is a three-atom water control.

Scientific artifact ZIP 11524806124 has original API-verified SHA-256
`8bc69a26f4be4e132fcdd2ac28fba09dd4217d7e210df5e3cd1efe64bae913eb`.
Verbatim fixture provenance and raw hashes are retained under
`tests/v010/fixtures/cfour_first_order_2_1/`. No native distribution, GENBAS or
ECPDATA belongs in this scientific fixture/export.

The parser independently requires the following observed structure:

- One successful `xdens` invocation explicitly calculates **CCSD(T) density and
  intermediates**, completes the density, and prints the requested electron
  count. Its completed invocation must precede the exact single xprops
  invocation, and its converged lambda-response invocation must complete before
  density construction. Byte spans/order and program hashes are retained and
  checked again during raw recovery. A correlated energy alone is insufficient
  density attribution.
- One successful `xprops` invocation identifies separate SCF and correlated
  property blocks. The parser selects exactly the latter, bounded by its actual
  native completion structure; earlier SCF values cannot supply missing data.
- Each declared Z-matrix center appears exactly once in indexed order, with its
  exact nuclear charge and all six ten-decimal Cartesian components. `EFG`
  contains exactly three Cartesian rows per atom and equals the correlated
  stdout tensor at the same printed precision. Partial, duplicated, permuted,
  nonfinite or lower-level tensors are rejected.
- The property table's coordinate frame is the indexed stdout **QCOMP**,
  explicitly printed in bohr. Its inventory and coordinates must match the
  harvester's actual QCOMP coordinates. Only proper indexed rotation and
  translation transport to the requested geometry is permitted. A charged
  dipole includes the origin-dependent translation term; EFG tensors do not.
- Native `DIPOL` must equal the correlated stdout dipole. Every completed/cached
  property component reparses its hash-bound raw stdout, DIPOL and EFG before
  its stored observation and quantity values can be reused. BASE pre/post
  sealed-runtime authority remains a separate required check.

Native tensors are retained before explicit symmetric/traceless normalization.
Only discrepancies bounded by the observed half-last-place precision,
**5×10⁻¹¹ native units per printed component**, are normalized. Arithmetic and
rotation bounds are propagated separately; these bounds do not represent
electronic-structure accuracy or full experimental uncertainty.

The rotated bounds propagate EFG token rounding **under the nominal inferred
rotation**. QCOMP coordinates are printed to eight decimal places in bohr, and
the indexed geometry fit uses the existing 2×10⁻⁶ Å guard. Uncertainty in that
rotation from coordinate printing/alignment, requested geometry and isotope
inertial axes is not propagated. These conditional component bounds are not a
complete Cartesian-frame or inertial-frame physical uncertainty bound.

## Unresolved independent native units and sign

The genuine output prints “Electric field gradient” without an EFG atomic-unit
or physical sign label. An atomic field-gradient unit is known independently
from CODATA, and the matrix specifies a conversion factor [1,5], but neither
establishes whether this particular native tensor uses the Hessian of
electrostatic potential, its negative (the gradient of electric field), or an
electronic-only versus total contribution convention. Its built-in `CHIxx`
values for “Mass number 2” are an internal consistency observation; they are
**never a user isotope assignment, nuclear-Q source, or independent sign proof**.

The public official CFOUR property/EFG manual and NIST/DOI resources could not be
retrieved through this environment's configured proxy (403). Public GitHub
repository searches for CFOUR manuals/EFG/quadrupole documentation produced no
independent native-convention source. Direct official-page checks returned the
proxy 403. No alternate proxy, proprietary source download or license
installation establishes a convention.
The pinned ASH documentation corroborates FIRST_ORDER correlated density
capability, including CCSD(T) dipoles and EFG, but supplies no EFG units/sign
definition [3]. Psi4's cited interface explicitly lacks property handling [4].

An independently retrieved primary compilation by Stone (2016), Table 1,
printed/PDF page 7, gives ground-state deuterium spin/parity 1+ and the legacy
central value **Q=+0.00286(2) barns=+2.86(2) millibarns** [6]. Its reported
uncertainty is 0.02 millibarns under the publication's own interpretation; this
is not silently relabeled as a new standard-uncertainty measurement. Using the
fixed central value and exact matrix factor, all twelve printed correlated
H-center components in the native diagnostic reproduce its built-in mass-2 χ
within their own print precision. Maximum discrepancy is
4.13268937568×10⁻⁶ kHz, below the 5.03359995782×10⁻⁶ kHz combined native
print bound. The physical Q uncertainty is separate and does not excuse a
numerical conversion mismatch. This establishes **internal legacy conversion
consistency**, while physical native sign/unit authority remains unverified.
It supplies no automatic isotope assignment or default nuclear input.

The pinned open PySCF property implementation explicitly constructs the total
potential-Hessian tensor from nuclear minus electronic contributions and uses
eQV/h with atomic EFG units [7]. This corroborates the general convention and
conversion used by the conditional mathematics. It does not establish CFOUR's
native operator convention; no PySCF calculation was performed.

Accordingly raw acquisition reports `native-unlabeled-EFG-components` and
`native_unit_sign_independently_verified=false`. An optional typed
`external_protocol.efg_convention` requires exact CFOUR 2.1, the explicitly
declared atomic unit, traceless-electrostatic-potential-Hessian and total contribution
conventions, an independent citation/value locator, reviewer, timezone-aware
past timestamp, and nonblank scientific reason. This **caller declaration is
not independently verified authority**. It permits only a labeled conditional
numerical conversion for human review. It cannot promote T3C-1h to full-row or
release acceptance. A separately reviewed independent native-convention source
is still required before compiling a positive scientific-authority rule.

## Explicit nuclear inputs and axes

`matrix_inputs.cfour_quadrupole_moments` is a list of typed nuclear targets:
exact `atom_id`, element, explicitly declared molecular isotope mass number,
twice nuclear spin (at least 2), **signed spectroscopic Q in millibarns**,
standard uncertainty with coverage factor 1, and separate source citations,
persistent identifiers and exact table/value locators for spin, Q and
uncertainty. Q is an area, not e×area. No nuclear moment, spin or Q sign is
inferred from a mass or native Mass-number default. Nuclear target identity is
validated before native work. EFG acquisition does not require Q.

Under the explicitly conditional declared potential-Hessian convention,
`χ=eQV/h` uses the matrix factor exactly. The output retains the full signed
Cartesian tensor, EFG principal values/η, signed Q sensitivity, Q-only standard
uncertainty and separate print-rounding bounds. All Q uncertainties across a
tensor share the same scalar Q; components are not independent random errors.
Nuclear citations remain caller declarations, not automatic verification.
Electronic-structure, basis, geometry, vibrational and legacy-factor errors are
not included in these partial uncertainty terms.

`cfour_quadrupole_frame="requested-cartesian"` is the default. Optional
`"rigid-inertial"` requires **every molecular isotope explicitly declared** and
records the actual isotope masses/provider. Inertial a,b,c axes are ordered by
increasing rigid moments; the tensor is properly transformed before displaying
χaa, χbb, χcc. Eigenvector signs remain arbitrary, and off-diagonal signs are
explicitly convention-dependent. Degenerate or unresolved axes are withheld,
using the declared relative moment threshold 10⁻¹⁰. No measured B₀ or
vibrationally averaged tensor is implied. EFG principal axes are independently
withheld when tensor degeneracy or native print precision makes them
unidentifiable.

Without explicit nuclear Q, raw property acquisition is retained and χ is null.
Without independently established native unit/sign authority, the matrix
record stays **partial, human-review, full_matrix_row_completed=false**,
including when conditional χ values can be calculated. Native dipole and EFG
quantities are stored separately; the EFG quantity remains human-review.

## Sources

1. Archived `topos/data/method_matrix_v4.py`, T3C-1h, original source lines
   3037/3051: CCSD(T)/cc-pVTZ FIRST_ORDER, dipole and EFG→χ, exact legacy factor.
2. [Original private native diagnostic run 37717679093][2], unchanged scientific
   ZIP/fixture provenance described above. Grammar/frame/density observations
   only; no independent native sign/unit or current-source workflow acceptance.
3. [ASH CFour-interface documentation, pinned commit
   1230964f43ebe62fa894527794d9b85b39ecbf96][3], lines 362–370. FIRST_ORDER
   calculates the requested correlated density, including CCSD(T), for dipoles
   and EFGs; capability evidence, not this particular run's proof.
4. [Psi4 CFOUR interface documentation, pinned commit
   23be3de4b1f6cd70e337b98a2a200008cf350274][4], property handling listed as
   unimplemented. Its energy/coordinate harvester cannot prove EFG semantics.
5. [SciPy v1.15.3 CODATA 2022 transcription][5]: atomic field-gradient unit
   9.7173624424×10²¹ V m⁻², e=1.602176634×10⁻¹⁹ C and
   h=6.62607015×10⁻³⁴ J Hz⁻¹ give 234.9647784716322522 kHz/(au×mbarn).
   The archived matrix factor differs by about 1.63734×10⁻⁷ fraction and is
   retained without a claim of exact SI metrology. This does not establish
   CFOUR's native sign/contribution convention.
6. N. J. Stone, “Table of nuclear electric quadrupole moments,” *Atomic Data and
   Nuclear Data Tables* **111–112**, 1–28 (2016), DOI
   [10.1016/j.adt.2015.12.002](https://doi.org/10.1016/j.adt.2015.12.002).
   [Original article PDF retained in a legitimate public repository][6], pinned
   commit 67e8cc68529cace924455ce56ac2a5210bd7ce91, SHA-256
   d735474fb0d2c95aa0f10c1cd3dab6e53f43c44cfe9eb5defbd8197d12894b1b.
   Table 1 p.7 gives the legacy deuterium moment; pp.3–4 establish units/sign
   and published uncertainty policies. The underlying cited 1979 experiment
   was not retrieved. No latest-adopted-value claim is made.
7. [Open PySCF RHF EFG implementation][7], pinned commit
   4eee5a430fb47eca5962f36fdcaf75c2b87e7ede, SHA-256
   cb79741703b4174dcdaa1b661953c38eb51dde6eeb82da0d5203b9647180ffd5.
   Lines 90–93/160–169 define its nuclear-minus-electronic potential-Hessian
   convention; lines 133/141–154 give atomic-unit labeling and eQV/h conversion.
   This is general open implementation evidence, not native CFOUR authority.

[2]: https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37717679093
[3]: https://github.com/RagnarB83/ash-documentation/blob/1230964f43ebe62fa894527794d9b85b39ecbf96/docs/CFour-interface.rst
[4]: https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/doc/sphinxman/source/cfour.rst
[5]: https://github.com/scipy/scipy/blob/v1.15.3/scipy/constants/_codata.py
[6]: https://raw.githubusercontent.com/IlyaKuprov/Spinach/67e8cc68529cace924455ce56ac2a5210bd7ce91/kernel/conventions/moments/stone_nqi_2016.pdf
[7]: https://github.com/pyscf/properties/blob/4eee5a430fb47eca5962f36fdcaf75c2b87e7ede/pyscf/prop/efg/rhf.py
