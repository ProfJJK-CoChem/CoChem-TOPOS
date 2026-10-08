# Molpro F12 protocol review for TOPOS 0.1.0

The reviewed official sources establish distinct Molpro F12 variants and a native
XML/variable interface. They do **not** establish the exact DF-CCSD(T)-F12 geometry
protocol needed to claim a literal Molpro implementation of those matrix rows.
The user subsequently authorized explicitly named ORCA alternatives for the
conflicting MPQC/Molpro rows. The implementation uses a separately reviewed
overlay while preserving the original matrix; the resulting ORCA F12D/RI
protocols must retain their own names, auxiliaries and numerical-derivative
definitions. That authorization does not establish Molpro support or transfer
F12b benchmark accuracy to F12D/RI. Native acceptance remains a separate step.

## Source identities and observations

The official [Molpro PyMolPro repository](https://github.com/molpro/pymolpro) was
reviewed at commit `12545680f47d21680dc2b7c83a5888ce44cdde84`. It uses an MIT license;
that license covers the interface source, not the Molpro executable.

1. [The official thermochemical notebook](https://github.com/molpro/pymolpro/blob/12545680f47d21680dc2b7c83a5888ce44cdde84/docs/source/examples/thermochemical_benchmark_Bak2000_reactions.ipynb)
   explicitly lists `CCSD(T)-F12A`, `CCSD(T)-F12B`, and `CCSD(T)-F12C`, then calls
   `pymolpro.database.run(..., method=method, basis=basis + '-F12', ...)` separately.
   These are distinct methods, not interchangeable spellings. Its tabulated
   results demonstrate single-point benchmarking, not a validated F12 gradient.
2. [The official database test](https://github.com/molpro/pymolpro/blob/12545680f47d21680dc2b7c83a5888ce44cdde84/pymolpro/test_database.py#L305)
   explains its unqualified `ccsd(t)-F12` case: “to cover the case that the Molpro
   ENERGY variable is a vector.” A parser must select an explicit method/state;
   taking the last or first energy without proving its meaning is insufficient.
3. [The official geometry notebook](https://github.com/molpro/pymolpro/blob/12545680f47d21680dc2b7c83a5888ce44cdde84/docs/source/examples/geometry_optimisation.ipynb)
   executes `df-rhf; df-lmp2; optg,gradient=0.00001; put,xyz,final.xyz`.
   This establishes a DF-LMP2 optimization example. It does not establish
   DF-CCSD(T)-F12 derivative support or its F12 variant.
4. [The official ASE interface](https://github.com/molpro/pymolpro/blob/12545680f47d21680dc2b7c83a5888ce44cdde84/pymolpro/ase_molpro.py#L42)
   requests `{force;varsav}`, reads `GRADX/GRADY/GRADZ`, and converts forces using
   `-gradient * Ha / Bohr`. This verifies the interface's unit/sign convention,
   not availability of gradients for every arbitrary method string.
5. [PyMolPro's procedure registry reader](https://github.com/molpro/pymolpro/blob/12545680f47d21680dc2b7c83a5888ce44cdde84/pymolpro/project.py#L1307)
   obtains capabilities from the actual installation's `lib/procedures.registry`.
   Its gradient accessor returns `None` when the XML gradient is absent. Neither
   interface supplies a supported-gradient assertion for the requested F12 row.
6. The retained official native XML example identifies Molpro `2023.1`, an exact
   native SHA, methods, principal energy properties and CML geometry. Its executed
   methods are RHF/MP2/CCSD. It is not an authentic F12 optimization fixture.

Direct retrieval of the official manual pages for explicitly correlated methods,
geometry optimization, XML output and closed-shell CCSD returned proxy HTTP 403
on 2026-10-07. No inaccessible manual wording is quoted or inferred here.

## Matrix consequences

`T5-3h` says **“junChS-F12 composite energy — ORCA F12 single points”**, but its
expansion says **“CCSD(T)-F12b/jun-cc-pVTZ + MP2-F12 CBS + MP2 CV, added.”** ORCA's
implemented `CCSD(T)-F12D/RI` cannot satisfy a literal F12b component. An explicit
source resolution must select a supported engine and preserve the actual F12
variant, auxiliary/CABS basis, frozen-core convention and component arithmetic.
The benchmark `[M]` tag does not resolve this implementation conflict. The
authorized alternative is an explicitly named ORCA F12D/RI composite; it is not
published as the literal junChS-F12b method.

`T3O-1mo` explicitly allows **“Molpro DF-CCSD(T)-F12 optimisation”** or ORCA
`CCSD(T)-F12D/RI cc-pVTZ-F12` reference single points. The latter do not supply a
new optimized geometry. For the former, the matrix omits the exact F12 variant,
DF/reference/frozen-core choices, auxiliary/CABS bases and derivative protocol.
The official examples above cannot fill those details by inference.

A complete native adapter needs an explicitly resolved protocol; documented exact
Molpro-version input and derivative support; actual native method/energy/state,
atom-order, convergence and derivative fixtures; and BASE-authorized installation
and bounded execution. A TOPOS driver using finite differences of real native
energies would be a separately declared numerical derivative protocol. It must
not be described as a demonstrated Molpro analytic-gradient implementation.
