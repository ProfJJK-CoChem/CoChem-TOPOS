# Reviewed TOPOS matrix campaign acceptance

The `reviewed_matrix_campaign` condition requires one predeclared, completed actual full-row RunStore with independently verified mandatory BASE authority for each of the **42 available TOPOS rows**. This is a calculation acceptance campaign, not a benchmark of chemical accuracy. A compiled recipe, passing unit test, primitive calculation, reference-only branch, or partial compound recipe does not complete a campaign row.

The inventory comes from the current `execution_support_report()` and shared row compiler. The original matrix has 140 rows: 44 belong to TOPOS, including the source-backed **T3C-10s and T3C-1min unavailable-by-design dispositions**. The other 96 rows belong to TORQ and are excluded from this TOPOS condition. No alternative method is assigned to the two unavailable CFOUR tiers.

The [archived matrix](../wiki/Method_Matrix.md) explicitly states “CFOUR has no 10 s or 1 min entry” (line 36; T3C table entries at lines 3034–3035). These are deliberate missing protocol entries, with no unresolved TOPOS adapter assigned to them. The statement does not establish a measured universal runtime limit. The month tiers `T3O-1mo` and `T3C-1mo` have conditionally compiled, explicitly selected reviewed implementations; native engine availability and complete physical acceptance remain separate prerequisites.

Before launching calculations, prepare a JSON list of typed case declarations. Schema `topos-reviewed-matrix-campaign-plan/0.2.0` and report `topos-reviewed-matrix-campaign-report/0.2.0` distinguish `diagnostic-control` from `source-domain-release`. Bare `RunRequest` objects remain useful diagnostic controls; they cannot supply release-eligible full-row coverage. An object containing `request` can also supply an explicit `hardware` declaration. Requests must use `purpose: "matrix"`, the archived full-matrix revision, an available TOPOS row, and every required scientific input. GPU cases require a named GPU and explicit allocation; reviewed revisions and protocol choices must be supplied. Each declaration binds atom mapping, geometry, isotopes, charge/spin, fragment states, seed, model and calculation protocols, resources, the reviewed compiler recipe, and the complete current source inventory. Duplicate row declarations and compatibility branches are rejected.

A release case must explicitly set `coverage_scope: "source-domain-release"` and provide `domain_declaration`. The current source target is an isolated gas-phase noncovalent complex of **5–10 mapped atoms**, with at least two nonempty indexed fragments exactly matching `request.molecule.fragments`. Geometry does not infer this partition or establish noncovalent identity. A declared interfragment bond is incompatible with this target declaration. Use the existing native-adapter request environment `{"phase":"gas"}`; the declaration separately states `physical_environment: "isolated-gas-phase"`. Do not add unsupported environment keys or strip them before calculation.

`CaseDomainDeclaration` binds the exact source-row domain descriptor and limitations, every explicitly selected reviewed variant's scientific differences, molecular and request-environment hashes, fragment order/mapping, an attributed reviewer, UTC review time, and nonblank applicability rationale. The review must precede the frozen plan. Source-specific restrictions, such as closed-shell, supported elements, native default masses, reference stationarity or semirigid VPT2 applicability, remain explicit obligations; the broad target descriptor does not waive them. A future changed or overridden source-domain descriptor requires a reviewed contract revision, rather than guessed new thresholds.

The following example writes one **declaration**, not a native result or completed campaign. Review the starting structure, fragment chemistry, state/isotope convention and applicable source limits before entering the reviewer and reason. Its coordinates are an illustrative water-dimer seed, not an asserted minimum or reference value. Save the exact request/declaration before launching it. Use actual BASE-audited allocations for the eventual execution; the example's CPU declaration is not measured hardware evidence.

```python
import json
from pathlib import Path

from topos.method_matrix import MATRIX_REVISION, resolve_row
from topos.models import Molecule, RunRequest, utc_now
from topos.storage import digest_json

molecule = Molecule(
    symbols=["O", "H", "H", "O", "H", "H"],
    coordinates=[
        [0, 0, 0], [0.9572, 0, 0], [-0.23999, 0.9273, 0],
        [2.9, 0, 0], [3.8572, 0, 0], [2.66001, 0.9273, 0],
    ],
    fragments=[[0, 1, 2], [3, 4, 5]],
    fragment_states=[
        {"atom_indices": [0, 1, 2], "charge": 0, "multiplicity": 1},
        {"atom_indices": [3, 4, 5], "charge": 0, "multiplicity": 1},
    ],
    environment={"phase": "gas"},
    charge=0,
    multiplicity=1,
)
request = RunRequest(
    molecule=molecule,
    purpose="matrix",
    matrix_revision=MATRIX_REVISION,
    matrix_row_id="T3O-10s",
    budget_seconds=10,
    threads=2,
    memory_mb=2048,
    n_candidates=1,
)
row = resolve_row(request.matrix_row_id)
reviewer = input("Attributed scientific reviewer: ")
rationale = input("Reviewed applicability, exclusions and source-limit rationale: ")
case = {
    "request": request.model_dump(mode="json"),
    "coverage_scope": "source-domain-release",
    "domain_declaration": {
        "chemistry_domain": row.chemical_domain,
        "physical_environment": "isolated-gas-phase",
        "system_class": "noncovalent-complex",
        "fragment_partition": molecule.fragments,
        "molecule_sha256": digest_json(molecule.model_dump(mode="json")),
        "request_environment_sha256": digest_json(molecule.environment),
        "source_row_limits": row.limitations,
        "reviewed_variant_differences": [],  # T3O-10s has no reviewed variant.
        "reviewer": reviewer,
        "reviewed_at": utc_now(),
        "applicability_rationale": rationale,
    },
}
Path("reviewed-cases.json").write_text(json.dumps([case], indent=2) + "\n")
```

For a revised row, select its explicit `source_resolution` in `request.matrix_inputs`, and copy the exact `reviewed_revision.definition.differences` returned by the shared row compiler into `reviewed_variant_differences`. Do not reuse the example's empty list or an energy-only/geometry-only compatibility branch. CPU cases may use the request-derived allocation declaration; GPU cases additionally require the explicit named `hardware` object described above. None of these declarations certifies engine availability, physical convergence, timing or method accuracy.

```sh
python -m topos.matrix_campaign plan --source-root /path/to/CoChem-TOPOS \
  --cases /path/to/reviewed-cases.json --output /path/campaign/campaign-plan.json
```

An inventory-only plan can omit `--cases`; all 42 available rows remain pending. Planning executes no engine. Freeze and retain the plan before running its exact requests through the installed BASE/TOPOS ecosystem. Assessment re-verifies every retained immutable snapshot and requires its creation/update observations and each actual native launch timestamp to follow predeclaration. Missing launch timestamps and older cached/imported calculations cannot supply coverage. The operator must retain the predeclaration honestly; its JSON timestamp is a declaration, not an independent timestamping service.

Keep the plan, report, measured RunStores and actual BASE authority snapshots inside one portable campaign bundle outside the source checkout. The report must be written beside its plan, and each RunStore must be below that directory. Retain each executing worker's Golden Registry with its adjacent genuine `setup_summary.json`; distinct workers can use separate subdirectories:

```text
campaign/
  campaign-plan.json
  runs/<run-id>/...
  authority/worker-1/cochem_system_config.json
  authority/worker-1/setup_summary.json
  campaign-report.json
```

The shared authority verifier checks the official BASE schema/checksum and the actual non-dry-run setup reports for exactly phases 1–11. Each report's status and hash must match the registry's Stage 0 audit, with no reported audit errors. It then binds the run's original registry path and digest/checksum, mandatory ecosystem, native executable identity and allocation, and retained child-run evidence. ML calculations additionally require their retained audited worker/model allocation evidence. Registry metadata alone, an arbitrary hash, or a copied backend label cannot establish execution authority. Do not rewrite original absolute paths inside the retained authority files when relocating the bundle.

After calculations finish, supply their immutable RunStore directories and each distinct authority snapshot. Repeat `--run` for the measured rows and `--base-registry` for additional workers:

```sh
python -m topos.matrix_campaign assess --source-root /path/to/CoChem-TOPOS \
  --plan /path/campaign/campaign-plan.json --run /path/campaign/runs/run_one \
  --run /path/campaign/runs/run_two \
  --base-registry /path/campaign/authority/worker-1/cochem_system_config.json \
  --output /path/campaign/campaign-report.json
```

This abbreviated command shows path layout and repeatable options; two runs do not represent a complete 42-row campaign. It supplies no reviewed scientific requests or assumed outcomes.

Assessment verifies checksummed immutable snapshots, exact caller request and molecular/resource identity, current executing TOPOS sources, full-row completion, source-row and reviewed-variant receipts, typed matrix-input identity, actual hardware, and completed native attempts with retained raw engine or model-worker evidence. Failed, partial, stale, mismatched, mocked, and zero-engine records remain failed or pending. A successful xTB case counts only its declared row; it does not certify ORCA, CFOUR, GPU training, another time tier, or a broader chemical domain.

An actual calculation can retain a row's diagnostic `status="passed"` if its native full-row evidence is valid. A `diagnostic-control` remains `release_eligible=false` even with independently verified BASE authority, and retains its scope blocker. A `source-domain-release` also needs genuine BASE authority; missing or unverifiable authority leaves it `release_eligible=false`, with an evidence-level `release_blocker`. The diagnostic `counts.passed` is therefore different from `release_eligible_rows`; even 42 development/native diagnostic passes cannot clear this release condition.

The overall report has `status="passed"` and `release_eligible=true` only when **all 42 rows have explicit source-domain release declarations, completed genuine full-row evidence and independently verified BASE authority**, and no supplied candidate is invalid. Incomplete coverage remains `pending` or `blocked`, as indicated in the report; no additional worker is silently substituted. The two intentional exclusions retain their original source citations separately. Assessment exits `3` for a pending/blocked report. Outputs are written to fresh paths to preserve prior plans and reports.

Report locators use bounded paths relative to the campaign bundle. Copying the complete bundle, including every registry/setup-summary pair, preserves verification after artifact download or archive relocation; the native records and quantities remain byte-for-byte unchanged. Release consumers call `topos.matrix_campaign.verify_report(report_path, source_root)`. It rechecks the retained plan's exact file digest, current source identity, complete row inventory, every original RunStore and the retained authority bytes. Editing a `passed` flag, relabeling a diagnostic monomer, changing a reviewed domain/partition, dropping setup reports or reusing a stale summary cannot clear the release condition. Prior schema plans/reports remain historical evidence under their original source; rewriting their schema or adding a later review does not make old calculations predeclared current-source release coverage. The release gate independently requires `release_eligible=true`.

Matrix execution coverage complements the separately required native, GPU, external-engine, queue, VPT2-reference, installation, and [scientific-reference coverage](TOPOS_SCIENTIFIC_REFERENCE_CAMPAIGN.md). It does not certify those other conditions, the twenty reviewed reference dispositions, or experimental accuracy. Neither this guide nor its example commands constitute a reviewed campaign or a passing scientific assessment.
