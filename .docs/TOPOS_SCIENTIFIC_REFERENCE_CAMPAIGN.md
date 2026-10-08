# Predeclared scientific reference campaigns

SRS acceptance A11 requires named references for each declared chemistry domain, observable and tolerance. `topos.scientific_references` provides a typed comparison plan, a freeze step before native measurement, and an assessment that independently reads immutable RunStores. This is an acceptance mechanism; adding a plan or passing unit tests does not establish the accuracy of a calculation method.

The caller supplies the reference data, citation, exact extracted value, uncertainty or explicitly unknown uncertainty, and justified absolute/relative tolerance. TOPOS supplies no literature values, invented uncertainty or default publication accuracy. Each datum binds the comparison context by SHA-256. The independent reference protocol states its method, basis, core treatment, CP convention, typed geometry role and convention, energy zero, electronic state/environment and isotope masses. Fixed-input/frozen-complex references additionally require `geometry_sha256 = digest_json(request.molecule.model_dump(mode="json", exclude={"name"}))`; a source fixed geometry cannot silently become an optimized-geometry reference. The evaluated `RunRequest` remains separate. Comparing a DFT method with a cited CCSD(T)/CBS interaction reference is possible without relabeling that reference as a DFT result.

Electronic energy, Gibbs energy, harmonic frequencies, equilibrium rotational constants, native VPT2 ground-state rotational constants, CP electronic interaction energy and approximate transferred R2 ground-state constants have separate typed definitions. Electronic energy cannot replace Gibbs energy; equilibrium constants cannot replace B0; frozen CP interaction cannot replace relaxed binding, half-CP or thermally corrected association. Equilibrium rotor references require a genuine unconstrained stationary optimizer endpoint or full-dimensional harmonic minimum; arbitrary input coordinates and frozen monomers cannot certify Be. The R2 transfer remains explicitly approximate. Its geometric safeguards and genuine native VPT2 evidence do not independently calibrate transferability error. A separately declared approximate transferred B0 prediction may be assessed against an actual ground-state reference, retaining both roles and its comparison rationale.

Generate the schema and validate an authored plan:

```sh
python -m topos.scientific_references schema > reference-plan.schema.json
python -m topos.scientific_references validate plan.json
```

Freeze references into a fresh portable bundle before independently running the exact predeclared native requests:

```sh
python -m topos.scientific_references freeze plan.json \
  --output /path/campaign/frozen --measurement-root /path/campaign/runs \
  --source-root /path/to/CoChem-TOPOS
```

The two output directories must be fresh siblings. Run each case through TOPOS/BASE using its exact `request`, keeping the resulting RunStore under `campaign/runs`. Supply a bindings JSON object mapping each declared case ID to its explicitly selected `run_dir` and immutable `record_sha256`; bind the hash returned by `RunStore.verify()` rather than an unverified record file. Assessment never launches or repairs calculations.

Retain the actual executing worker's Golden Registry and its adjacent `setup_summary.json` inside the same bundle. These must be the original authority bytes associated with the measured runs. For example, a bundle using one worker can contain:

```text
campaign/
  frozen/frozen-plan.json
  frozen/references/...
  runs/<run-id>/...
  authority/worker-1/cochem_system_config.json
  authority/worker-1/setup_summary.json
  report.json
```

The setup summary must identify a genuine, non-dry-run setup with exactly phases 1–11, matching phase statuses, no reported audit errors, and report hashes matching the registry's Stage 0 audit. Verification checks the official BASE schema and registry checksum, the original registry path, the mandatory ecosystem, the observed executable identities and allocations, and applicable retained child-run authority. A backend label or a 64-character registry hash alone is insufficient. Preserve original paths recorded inside these files when relocating the bundle; portable report locators do not rewrite execution history.

Supply each distinct worker registry explicitly; place different workers' registry/summary pairs in separate directories and repeat `--base-registry` when needed:

```sh
python -m topos.scientific_references assess /path/campaign/frozen/frozen-plan.json \
  --bindings bindings.json --output /path/campaign/report.json \
  --base-registry /path/campaign/authority/worker-1/cochem_system_config.json \
  --source-root /path/to/CoChem-TOPOS
```

The final report belongs at the bundle root. Its frozen-plan, RunStore and authority locators are confined relative paths, so the complete bundle can be moved/downloaded and reverified by `verify_report(report_path, source_root)`. Keep the frozen data, reviewed ledger when supplied, all measured snapshots/artifacts, and every referenced registry/summary pair. Verification rechecks the current complete release source inventory, exact requests, retained snapshot history, observed engine versions and raw native quantity/derivative evidence. Ordinary ORCA optimization imports enforce all five native optimization conditions and a separate final stationary analytic gradient. Thermal quantities rederive the physical Hessian, harmonic minimum and declared RRHO conditions; CP interaction imports validate all native legs. Native VPT2 imports independently check stationary raw derivatives, spectroscopy, native Hessian alignment and the declared mass/axis transfer.

## Reviewed requirement coverage

A narrow reference comparison does not need a broad release-coverage declaration. To establish eligibility for the `scientific_reference_campaign` release condition, the plan must additionally contain an explicit `requirement_coverage` review before it is frozen. No default review, literature value, tolerance or campaign is generated. A single CP interaction-energy case cannot clear the twenty requirement obligations **TOPOS-010-019–036 and TOPOS-010-049–050**.

The typed `ReferenceCoverageReview` requires:

| Field | Required meaning |
|---|---|
| `reviewer`, `reviewed_at`, `review_rationale` | Named review of applicability and scope, completed before the measurement freeze. This is retained attribution, not an authenticated signature or peer-review certificate. |
| `srs_sha256` | Exact current SRS file digest. |
| `acceptance_ledger_file`, `acceptance_ledger_sha256` | The reviewed ledger and its exact file digest. Freezing retains a copy as `reviewed-acceptance-ledger.json`. |
| `acceptance_ledger_scope_sha256` | `digest_json(reference_ledger_scope(ledger))`, binding requirement text, assessments, coding gaps, implementation and test inventories. |
| `requirements` | One reviewed disposition for every reference-condition obligation, with exact clause identity, scope, rationale, exclusions and named acceptance tests. Partial inventories remain useful declarations but cannot establish release eligibility. |

Each disposition binds `requirement_source_sha256 = digest_json(ledger["requirements"][requirement_id]["requirement_source"])`. That source must be the actual SRS clause belonging to the selected ID. `acceptance_test_references` use exact `tests/.../test_module.py::test_function` identities from that requirement's reviewed ledger, with matching current source hashes. The release gate independently requires executed passing named JUnit results, including the relevant parameterizations; matching-source supplemental evidence may cover skipped cases. Reviewing an applicability rationale never waives these tests or other native acceptance conditions.

For `applicability="numerical-reference"`, declare every `required_chemistry_domains` entry and explicit `case_claims`. Each claim names an existing case, its exact chemistry domain, observable and `digest_json(case.context())`, together with a scientific scope and rationale. All required observable roles must be represented **within every declared domain**:

| Requirement | Reference observables required by the coverage contract |
|---|---|
| 029 | Equilibrium rotational constants **and** native ground-state or explicitly approximate transferred ground-state constants. The latter two remain distinct observables. |
| 031 | Harmonic frequencies. Separate derivative-consistency, dimension, conversion and provenance tests remain required. |
| 032 | CP interaction energy at the declared frozen complex geometry. This scope does not establish relaxed binding, reservoir treatment or general association thermodynamics. |
| 033 | CP interaction energy with its actual native legs and declared fragment/state/basis convention. |
| 034 | Harmonic frequencies **and** Gibbs energy with the declared minimum, thermal model and reference state. |

The other obligations—019–028, 030, 035–036 and 049–050—use `applicability="non-numerical-contract"`, explicit rationale, scope/exclusions and named tests. They cannot attach numerical accuracy claims in place of algorithmic evidence. In particular, energy or rotor agreement cannot prove deduplication correctness, chirality preservation, exhaustive sampling, kinetics, or publication provenance. These dispositions assess reference applicability only; their report keeps `full_requirement_verified=false`.

The frozen review binds the exact original ledger bytes as well as its semantic scope. The release ledger may subsequently update verification status, receipts and cleared conditions. Changing the SRS, scientific assessment, coding gaps, implementation or test inventory requires a new matching review; the release gate will reject a changed scope. Dropping a pending-condition string does not remove the fixed twenty coverage obligations. Additional scientific-reference conditions in the release ledger also require coverage.

Local timestamps, fresh output directories and immutable history establish internal declaration/execution order. They do not establish independent trusted timestamping, authorship, citation correctness or peer review. An already published reference can be declared before the measured run; the reference need not have been computed by the evaluated method. Automatic comparison does not replace review of the source extraction, compatible energy zero, experimental conditions or domain-specific tolerances.

## Comparison outcomes and release eligibility

`comparison_status` describes agreement for the declared observations only. A complete scientific comparison with verified BASE authority can have `status="passed"` while `release_eligible=false` because broad reviewed requirement coverage is absent. A single successful case remains a useful narrow comparison; it does not clear the release condition. `scientific_reference_campaign=true` requires all declared comparisons to pass, independently verified BASE authority, and complete reviewed reference-condition coverage. The full release gate additionally verifies the current ledger scope, named tests and all other required evidence.

Genuine development/native observations, or runs lacking verifiable retained BASE authority, can retain measured values and `comparison_status="passed"` for diagnosis. Their overall scientific status remains `pending`, with `base_authority_verified=false` and an authority blocker; metadata relabeling cannot make them eligible. Missing/incomplete measured evidence remains `pending`; an exceeded numerical tolerance is `failed`. CLI assessment exits 0 for `status="passed"`, 3 for `pending`/`failed`, and 2 when malformed or inconsistent evidence is rejected. Exit 0 alone does not imply release eligibility.

An independently executed prior native calculation may instead define a `reproducibility-calibration` campaign. Numerical agreement then produces `comparison_status="passed"`, `calibration_passed=true`, overall `status="pending"` and `release_eligible=false`, even when genuine BASE authority is fully verified. Calibration cannot carry scientific release coverage. It can test the integration flow but cannot clear independent scientific reference acceptance. Tests and public parser fixtures similarly cannot stand in for executed physical validation. Agreement only covers the explicitly named cases; it provides no general method-accuracy, exhaustive sampling or experimental-rotor claim.
