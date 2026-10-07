# ORCA 6.1 basis names and element availability

The reviewed scientific protocol retains its requested basis name. Native input
uses only a documented ORCA keyword with an explicit mapping receipt. The same
resolver serves the DFT and correlated adapters; orbital, Coulomb/exchange,
correlation-fitting and CABS availability are checked separately for every atom.
These checks establish documented input availability, not successful execution
or scientific accuracy.

## Seasonal basis spelling

Hosted run [37650295795](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37650295795)
at TOPOS `4cdcf3853eb839eaf05da9bdae0d4fd4a0a879bc` demonstrated that ORCA
6.1.1 rejects the bare simple-input keyword `jun-cc-pVTZ` before SCF. The unchanged
failure output and its provenance are retained in
`tests/v010/fixtures/orca_611_f12_basis/`.

The [ORCA 6.1 manual, Table 2.22](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/basisset.html#correlation-consistent-basis-sets)
documents `jun-cc-pV(D+d)Z`, `jun-cc-pV(T+d)Z` and `jun-cc-pV(Q+d)Z`.
TOPOS maps the requested D/T/Q names to these native spellings **only for H–Ne**.
The additional tight-d construction does not change those elements' orbital
spaces. The result records both names, atom elements, mapping domain and sources;
the requested scientific protocol is preserved.

This is not a general alias for heavier atoms. In particular, adding the tight-d
construction to Al–Ar changes the orbital basis. TOPOS rejects such an implicit
change. A future exact implementation would require explicit, independently
verified basis coefficients and native import evidence. No coefficient trimming,
different cardinality or alternate basis is silently substituted. The calendar
construction and second-row tight-d basis work are documented respectively by
[DOI 10.1021/ct1005533](https://doi.org/10.1021/ct1005533) and
[DOI 10.1063/1.1367373](https://doi.org/10.1063/1.1367373).

## Fitting and CABS domains

The orbital basis alone does not establish availability of an F12 or RI
calculation. TOPOS checks the exact role-specific tables in the same manual:
2.23 for F12 orbital sets, 2.34 for Coulomb fitting, 2.35 for Coulomb/exchange
fitting, 2.36 for correlation fitting and 2.37 for CABS. For example,
`cc-pVDZ/JK` has no reviewed native entry, and the listed F12 CABS element range
does not include He. Such requests stop before a solver is launched. Explicit
fitting choices remain part of the protocol and are never inferred from the
orbital label.

The preflight receipt includes the manual URL, table number, documented element
range and SHA-256 identifiers of the researched HTML and text. Native version,
executable identity, actual completion, basis-export evidence where required,
and all numerical checks remain separate execution requirements.

The name correction does not change the explicitly approximate
[ORCA F12D/RI composite](TOPOS_ORCA_F12_COMPOSITE.md) into F12b and does not
establish the original F12b benchmark accuracy. A new hosted run must validate
the corrected native inputs and complete composite.
