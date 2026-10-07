# Conditional CFOUR month geometry branch

`T3C-1mo` accepts the explicit source resolution
`cfour-native-default-mass-corrected-geometry-v1`. This implements a restricted
geometry deliverable; it does not complete the original matrix row's
isotope-consistent rotational constants. The original matrix remains archived,
and the reviewed definition has a separate content hash.

The caller supplies `higher_geometry`, `month_corrections`, and
`external_resolution="cfour-topos-cartesian-optimizer-v1"`. No increment basis,
CBS power, coordinate chart, or derivative threshold is inferred from a tier
label. The resulting internal-coordinate parameters are

`R_higher + (R_HF,X2C1E − R_HF,nonrel) + (R_HF+DBOC,native-default − R_HF)`.

`R_higher` uses the eight explicit CBS/CV/full-triples/full-quadruples component
geometries. The scalar pair uses one all-electron uncontracted HF basis. The
DBOC pair uses another explicitly supplied all-electron HF basis and the same
contraction within that pair. Every stage shares one CFOUR version, executable
digest, native GENBAS digest, internal-coordinate chart, and geometry deadline.
The pairs use checked numerical derivatives of actual native energies; they do
not claim native analytic correction gradients. DBOC convergence also accounts
for the printed energy precision. The underlying component ledger supports
verified reuse of completed native energies on resume; outer optimizers restart.

Only H, C, N, O and F with no explicitly requested isotopes are supported by the
native-default DBOC contract. Public native output demonstrates the default-mass
path but does not attest its numeric isotope masses. All rotational constants
are therefore withheld, including those at the uncorrected base geometry in
this compound result. TOPOS does not equate its own mass table with CFOUR's.
The final report sets `full_matrix_row_completed=false`; the parent matrix
execution records `implemented_branch_completed=true` and
`full_row_completed=false`.

No composite electronic energy, common-potential stationary point, verified
minimum, vibrational correction or benchmark accuracy is inferred by adding
geometry increments. Common topology and stereochemistry do not prove that
every optimization remains in the same torsional basin.

The related native controls and source evidence are documented in
[CFOUR small corrections](TOPOS_CFOUR_SMALL_CORRECTIONS.md) and
[higher composites](TOPOS_HIGHER_COMPOSITES.md). Tests cover protocol rejection,
mass scope, source revision, cancellation, nested budget propagation and
geometry arithmetic. Licensed CFOUR 2.1 execution remains conditional on actual
installation and retained native evidence; parser tests are not native acceptance.
