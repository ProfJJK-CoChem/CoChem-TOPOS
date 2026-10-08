# BASE nuclide handoff boundary

This receiver requires the reviewed BASE 1.0.1 nuclear-identity parser. A handoff contains the unchanged XYZ bytes and one complete `options.topos_request`. Its operation must equal the request purpose; charge and multiplicity must be explicit.

BASE may label nuclei as `18O`, `D`, `T`, `2H`, or another label accepted by its measured-isotope table. TOPOS resolves the elemental labels for comparison with `request.molecule.symbols`, but every explicit XYZ isotope must equal `request.molecule.isotopes` at the same atom index. A missing or different requested isotope is rejected. Element-only XYZ remains compatible with explicitly declared request isotopes. No nuclear mass or electronic state is inferred from a comment line.

The receiver requires exactly one counted XYZ frame and exact ordered coordinates. It does not rewrite the artifact, infer charge or spin, reorder atoms, or execute a calculation during validation. The existing raw artifact hash, manifest hash and complete declared-request digest retain both representations. Actual computation still requires mandatory BASE execution authority; parsing a handoff establishes no scientific result or publication approval.

The focused `tests/v010/test_base_provider_nuclides.py` exercises the actual BASE producer and TOPOS receiver without launching an engine: agreeing labelled and unlabelled inputs, absent or mismatched isotope assignments, atom-order and coordinate differences, invalid nuclear labels, and original operation/options/state guards. The combined outside proposal also tests the GUI and batch transport. Installed-wheel and hosted acceptance must be performed against the final reviewed BASE/TOPOS/TORQ package identities separately.
