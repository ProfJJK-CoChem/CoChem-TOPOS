# Reviewed TOPOS matrix campaign acceptance

The `reviewed_matrix_campaign` condition requires one predeclared, completed actual full-row RunStore for each of the **42 available TOPOS rows**. This is a calculation acceptance campaign, not a benchmark of chemical accuracy. A compiled recipe, passing unit test, primitive calculation, reference-only branch, or partial compound recipe does not complete a campaign row.

The inventory comes from the current `execution_support_report()` and shared row compiler. The original matrix has 140 rows: 44 belong to TOPOS, including the source-backed **T3C-10s and T3C-1min unavailable-by-design dispositions**. The other 96 rows belong to TORQ and are excluded from this TOPOS condition. No alternative method is assigned to the two unavailable CFOUR tiers.

Before launching calculations, prepare a JSON list of exact `RunRequest` objects, or objects containing `request` and an explicit `hardware` declaration. Requests must use `purpose: "matrix"`, the archived full-matrix revision, an available TOPOS row, and every required scientific input. GPU cases require a named GPU and explicit allocation; reviewed revisions and protocol choices must be supplied. Each declaration binds atom mapping, geometry, isotopes, charge/spin, fragment states, seed, model and calculation protocols, resources, the reviewed compiler recipe, and the complete current source inventory. Duplicate row declarations and compatibility branches are rejected.

```sh
python -m topos.matrix_campaign plan --source-root /path/to/CoChem-TOPOS \
  --cases /path/to/reviewed-cases.json --output /path/to/campaign-plan.json
```

An inventory-only plan can omit `--cases`; all 42 available rows remain pending. Planning executes no engine. Freeze and retain the plan before running its exact requests through the installed BASE/TOPOS ecosystem. Assessment re-verifies every retained immutable snapshot and requires its creation/update observations and each actual native launch timestamp to follow predeclaration. Missing launch timestamps and older cached/imported calculations cannot supply coverage. The operator must retain the predeclaration honestly; its JSON timestamp is a declaration, not an independent timestamping service.

Keep the plan, report and measured RunStores inside one portable campaign bundle outside the source checkout. The report must be written beside its plan, and each RunStore must be below that directory. After calculations finish, supply their original immutable RunStore directories:

```sh
python -m topos.matrix_campaign assess --source-root /path/to/CoChem-TOPOS \
  --plan /path/to/campaign-plan.json --run /path/to/run_one \
  --run /path/to/run_two --output /path/to/campaign-report.json
```

Assessment verifies checksummed immutable snapshots, exact caller request and molecular/resource identity, current executing TOPOS sources, full-row completion, source-row and reviewed-variant receipts, typed matrix-input identity, actual hardware, and completed native attempts with retained raw engine or model-worker evidence. Failed, partial, stale, mismatched, mocked, and zero-engine records remain failed or pending. A successful xTB case counts only its declared row; it does not certify ORCA, CFOUR, GPU training, another time tier, or a broader chemical domain.

The report passes only when all 42 available rows have matching actual completed evidence. The two intentional exclusions retain their original source citations separately. Assessment exits `3` while any required row remains failed/pending or a supplied candidate is invalid. Outputs are written to fresh paths to preserve prior plans and reports.

Report locators use bounded paths relative to the campaign bundle. Copying that complete bundle preserves verification after artifact download or archive relocation; the native records and quantities remain byte-for-byte unchanged. Release consumers call `topos.matrix_campaign.verify_report(report_path, source_root)`. It rechecks the retained plan's exact file digest, current source identity, complete row inventory, and every original RunStore; editing a `passed` flag or reusing a stale summary cannot clear the release condition. This condition complements the separately required native, GPU, external-engine, queue, VPT2-reference, installation, and scientific-validation evidence. It does not certify those other requirements or experimental accuracy.
