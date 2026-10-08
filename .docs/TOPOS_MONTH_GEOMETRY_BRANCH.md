# CFOUR month small corrections and native-observed masses

`T3C-1mo` Product A requests equilibrium rotational constants with scalar
relativistic and diagonal Born–Oppenheimer correction closure. The archived row
at [Method Matrix line 3043](../wiki/Method_Matrix.md#L3043), expanded at line
3057, does not request an arbitrary isotope campaign. That separate deliverable
appears in `T4C-1w`/`T4C-1mo` at lines 3109–3110. The archival file is unchanged.

The explicit reviewed resolution
`cfour-observed-default-mass-small-correction-v1`, paired with
`month_corrections.rotor_policy="native-observed-atomic-mass-rotors"`, implements
Product A for the supported native-default isotopologue. It requires actual
CFOUR 2.1 output to attest the complete mapped atomic-mass vector in every
DBOC-enabled energy evaluation. Merely supplying a vector in request metadata
cannot establish that evidence. The separate compatibility resolution
`cfour-native-default-mass-corrected-geometry-v1` retains its geometry-only
behavior and never completes the rotor deliverable.

The caller supplies `higher_geometry`, `month_corrections`, and
`external_resolution="cfour-topos-cartesian-optimizer-v1"`. No increment basis,
CBS power, coordinate chart, or derivative threshold is inferred from a tier
label. The resulting independent internal-coordinate parameters are

`R_higher + (R_HF,X2C1E − R_HF,nonrel) + (R_HF+DBOC,native-default − R_HF)`.

`R_higher` uses eight explicit CBS/CV/full-triples/full-quadruples component
geometries. The scalar pair uses one all-electron uncontracted HF basis. The
DBOC pair uses another explicitly supplied all-electron HF basis and the same
contraction within that pair. Every stage shares one CFOUR version, executable
digest, native GENBAS digest, internal-coordinate chart, and geometry deadline.
The pairs use checked numerical derivatives of actual native energies; they do
not claim native analytic correction gradients. DBOC convergence accounts for
printed energy precision. Verified completed native energies can be reused on
resume; outer optimizers restart and incomplete native jobs run in fresh folders.

Only H, C, N, O and F with no explicitly requested isotopes are supported.
Successful historical native output **does print numeric atomic masses**:
`carbon12-dboc.out` lines 1834–1835 reports `12.000000000` in its normal-coordinate
mass table. A public [CFOUR 1.01 water output](https://github.com/zorkzou/UniMoVib/blob/d354fd6f6b6e9bb79f34ea11928c62c6b2b6c2dc/test/CFour/h2o-nosymm/h2o-c1.out)
reports a molecular vector in the same table. These establish parser grammar;
they are not successful current CFOUR 2.1 HF molecular DBOC acceptance. The
previous statement that the native output did not print numeric masses was
incorrect.

Every actual DBOC-enabled observation must retain its source output, hash,
native atom order, geometry alignment, mass precision and native engine/basis
identity. All such observations must agree. The final corrected geometry's
inertia tensor uses these observed **atomic masses** directly. TOPOS does not
substitute its isotope database, equate them with the DBOC algorithm's internal
**nuclear masses**, or infer arbitrary isotope support. The Born–Oppenheimer
HF-only surface is mass-independent and does not require a fictitious mass
observation. Its native identity must nevertheless match all other stages.

The final report includes the geometry, equilibrium rigid-rotor constants in
MHz, mapped atomic masses, observation receipts, and intervals arising only
from their printed decimal precision. At fixed coordinates, componentwise
positive mass increases increase the centered inertia tensor in positive
semidefinite order. Eigenvalues at the mass interval endpoints therefore bound
sorted rotor constants. These are rounding intervals, not model-error bars or
statistical confidence intervals; floating-point error is not separately bounded.

For the observed-mass variant, `full_matrix_row_completed=true` is set only
after the native evidence is validated and the Product A rotor is computed.
It does not claim generic isotope campaigns, a composite electronic energy,
a common-potential stationary point, a verified minimum, vibrational correction,
measured B0, or benchmark accuracy. Common topology and stereochemistry do not
prove that every optimized component remains in the same torsional basin.

See [CFOUR small corrections](TOPOS_CFOUR_SMALL_CORRECTIONS.md) and
[higher composites](TOPOS_HIGHER_COMPOSITES.md). Native CFOUR 2.1 execution
remains conditional on actual installation and retained native evidence;
parser, orchestration and pure arithmetic tests are not native acceptance.
