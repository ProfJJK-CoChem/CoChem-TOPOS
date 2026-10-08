# CFOUR T3C-1h: correlated EFG acquisition and sourced nuclear conversion

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

## Native units/sign and independently checked operator admission

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
consistency**; it does not independently establish physical native sign/units.
It supplies no automatic isotope assignment or default nuclear input.

The pinned open PySCF property implementation explicitly constructs the total
potential-Hessian tensor from nuclear minus electronic contributions and uses
eQV/h with atomic EFG units [7]. This corroborates the general convention and
conversion used by the mathematics. The source alone does not establish
CFOUR's native convention.

A separately executed public **PySCF 2.14.0 RHF/cc-pVTZ** calculation used the
retained native fifteen-decimal-bohr MOL coordinates and independently sourced
public basis [8]. Its RHF energy agrees within 2.70×10⁻¹³ Eh, all 58 orbital
energies within 1.89×10⁻¹⁰ Eh, and all 27 SCF EFG components within
3.12×10⁻⁹ atomic units. The prospective EFG limit was 10⁻⁷ au and was not
adjusted after measurement. No fitted rotation, sign, scale or atom permutation
was applied. Sign reversal, ×1000/×0.001 scale changes, and omission of either
nuclear or electronic contributions reject. Independent review re-evaluated
the public integral kernel on the retained converged density and checked every
installed wheel member and retained source/proof hash.

This is **direct empirical RHF operator conformance**, distinct from numerical
CCSD(T) accuracy. The original same successfully completed xprops invocation
contains separate SCF and correlated tables. Applying the same exact-build
traceless nuclear-minus-electronic operator convention to the explicitly
attributed CCSD(T) density is an **inference**, recorded as such in every
admitted operator/χ result. It is not an independent correlated-density
benchmark, arbitrary-method validation, full campaign or release certificate.

The compiled profile requires both stable identities:

- Approved complete packaged inventory SHA-256
  `e9a59cfcaeed3df210d8276b7d3055aed68ba082b2dbc31e826b8eafebd4e286`.
- Actual xprops SHA-256
  `53d4040eedbc7616cf62732b49c2e2ef14aa157d1122b6d029a87afb1c7cf72b`,
  exactly 113368 bytes.

Protocol admission is currently CFOUR 2.1 **CCSD(T) FIRST_ORDER**, explicitly
all electrons correlated, spherical cc-pVTZ/PVTZ, neutral closed-shell vacuum.
The empirical profile concerns the same-build operator convention; it supplies
no accuracy estimate for other molecular geometries or nuclei. Other native
builds, versions, bases, core treatments, charge/spin or environment choices
retain acquisition and the conditional fallback until separately reviewed.

BASE independently re-verifies the actual installed complete runtime and
extracts the property fingerprint before and after FIRST_ORDER execution.
The recorded complete runtime seal includes path-dependent launcher, helpers,
basis and environment bindings; stable inventory/xprops hashes do not replace
that seal. Raw process receipts bind both fingerprints to the complete
authority and exact input/stdout/stderr hashes. A protocol version or caller
flag cannot select this profile. Recovery freshly parses the correlated
density, every tensor/frame/token/rounding field, and the adjacent native
receipt. The internal immutable context binds this complete parsed acquisition;
a copied JSON assertion cannot authorize χ. Offline campaign verification also
compares the fingerprint against the retained audited Stage0 metadata.

Historical R4 receipts **lack this new property context**. Their raw data and
failed hosted status remain unchanged and conditional even though separately
inspected Registry metadata identifies the calibrated binary. No historical
receipt is rewritten or upgraded.

Without admitted exact-build raw receipt context, acquisition reports
`native-unlabeled-EFG-components` and
`native_unit_sign_independently_verified=false`. An optional typed
`external_protocol.efg_convention` requires exact CFOUR 2.1, the explicitly
declared atomic unit, traceless-electrostatic-potential-Hessian and total contribution
conventions, an independent citation/value locator, reviewer, timezone-aware
past timestamp, and nonblank scientific reason. This **caller declaration is
not independently verified authority**. It permits only a labeled conditional
numerical conversion for human review. It cannot promote T3C-1h to full-row or
release acceptance. Admitted new raw receipts report atomic EFG units,
`native_unit_sign_independently_verified=true`, and the full compiled empirical
profile with its explicit correlated-operator inference boundary. Nuclear data
and correlated accuracy remain separate.

## Explicit nuclear inputs and axes

`matrix_inputs.cfour_quadrupole_moments` is a list of typed nuclear targets:
exact `atom_id`, element, explicitly declared molecular isotope mass number,
twice nuclear spin (at least 2), **signed spectroscopic Q in millibarns**,
sourced uncertainty interpretation, and separate source citations,
persistent identifiers and exact table/value locators for spin, Q and
uncertainty. Q is an area, not e×area. No nuclear moment, spin or Q sign is
inferred from a mass or native Mass-number default. Nuclear target identity is
validated before native work. EFG acquisition does not require Q.

The uncertainty contract has two mutually exclusive branches:

- `uncertainty_convention="standard-uncertainty-k1"` (the compatibility default)
  requires `q_standard_uncertainty_millibarn` and its independent source. It
  rejects source-reported uncertainty fields.
- `uncertainty_convention="reported-source-uncertainty"` requires
  `q_reported_uncertainty_millibarn`, a nonblank
  `q_reported_uncertainty_policy`, and `q_uncertainty_source`. It rejects a
  simultaneous standard uncertainty. The output retains the declared source
  error, citation and policy; standard component error bars are null in both
  Cartesian and inertial frames. It does not infer a probability distribution,
  coverage factor, confidence interval or standard uncertainty.

For example, an explicitly declared deuterium target may cite Stone's Table 1
p.7 [6] for Q=+2.86 millibarns, twice spin=2, and the **reported** parenthetic
uncertainty 0.02 millibarns. Its policy should identify Stone's pp.3–4 rounding
and adoption conventions and state that a k=1 statistical interpretation has
not been established. This is an explicit user nuclear-data declaration, never
a built-in moment, isotope default, or automatic independent verification.

Under the explicitly conditional declared potential-Hessian convention,
`χ=eQV/h` uses the matrix factor exactly. The output retains the full signed
Cartesian tensor, EFG principal values/η, signed Q sensitivity, Q-only standard
uncertainty where explicitly declared, and separate print-rounding bounds.
The Q sensitivity is retained for both uncertainty branches. In the k=1 branch,
all Q standard uncertainties across a tensor share the same scalar Q;
components are not independent random errors.
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

The computational full-row path is reachable only when a new verified native
component has the admitted operator receipt, exact CCSD(T) density/dipole/EFG,
explicit indexed isotope/spin/signed-Q/citations/uncertainty interpretation,
and every requested tensor frame (including all explicit isotope masses for
rigid-inertial output). Missing Q leaves χ null; missing operator context or
caller-only convention leaves the row partial. `full_matrix_row_completed`
reports **computational coverage**, while nuclear citations remain explicit
caller declarations and χ remains human-review. It does not certify measured
accuracy, independent nuclear-data adoption, global native campaign acceptance
or release readiness. The original diagnostic and mathematical/transport tests
do not establish current native full-row completion.

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
8. Independently executed PySCF 2.14.0 RHF operator diagnostic, retained as
   `pyscf-cfour-scf-efg-20261008`, producer `FINAL_RECEIPT.json` SHA-256
   `761ec90e63a2a3ee125ff238d97823872e8a7ef8f16eee87dc16c5116e45536d`.
   Independent empirical review SHA-256
   `b56d554d4054eb35e5401e719b060735fd1d913f6c47e4e69f698f423993eda6`;
   independent native inventory/complete-seal metadata review SHA-256
   `ac822f283e040d370065f4a1083571175e6bdd5aa8e89c68544c575f32b35969`.
   The compiled evidence identifiers are retained in `topos/cfour_operator.py`.
   The raw native target is the original artifact from [2]. The empirical target
   is its SCF-density block, never the distinct CCSD(T) EFG file. Public basis
   span and every printed native entry agree; unprinted native GENBAS columns
   are not claimed bytewise verified. This source admits only the explicitly
   scoped empirical operator convention; it supplies no current native full-row
   or correlated accuracy acceptance.

[2]: https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37717679093
[3]: https://github.com/RagnarB83/ash-documentation/blob/1230964f43ebe62fa894527794d9b85b39ecbf96/docs/CFour-interface.rst
[4]: https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/doc/sphinxman/source/cfour.rst
[5]: https://github.com/scipy/scipy/blob/v1.15.3/scipy/constants/_codata.py
[6]: https://raw.githubusercontent.com/IlyaKuprov/Spinach/67e8cc68529cace924455ce56ac2a5210bd7ce91/kernel/conventions/moments/stone_nqi_2016.pdf
[7]: https://github.com/pyscf/properties/blob/4eee5a430fb47eca5962f36fdcaf75c2b87e7ede/pyscf/prop/efg/rhf.py
