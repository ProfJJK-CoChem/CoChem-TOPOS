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
  --output /path/campaign/frozen --measurement-root /path/campaign/runs
```

The two output directories must be fresh siblings. Run each case through TOPOS/BASE using its exact `request`, keeping the resulting RunStore under `campaign/runs`. Supply a bindings JSON object mapping each declared case ID to its explicitly selected `run_dir` and immutable `record_sha256`; bind the hash returned by `RunStore.verify()` rather than an unverified record file. Assessment never launches or repairs calculations:

```sh
python -m topos.scientific_references assess /path/campaign/frozen/frozen-plan.json \
  --bindings bindings.json --output /path/campaign/report.json
```

The final report belongs at the bundle root. Its frozen-plan and RunStore locators are confined relative paths, so the complete bundle can be moved/downloaded and reverified by `verify_report(report_path, source_root)`. Keep the frozen data and all measured snapshots/artifacts. Verification rechecks the current complete release source inventory, exact requests, retained snapshot history, observed engine versions and raw native quantity/derivative evidence. Ordinary ORCA optimization imports enforce all five native optimization conditions and a separate final stationary analytic gradient. Thermal quantities rederive the physical Hessian, harmonic minimum and declared RRHO conditions; CP interaction imports validate all native legs. Native VPT2 imports independently check stationary raw derivatives, spectroscopy, native Hessian alignment and the declared mass/axis transfer.

Local timestamps, fresh output directories and immutable history establish internal declaration/execution order. They do not establish independent trusted timestamping, authorship, citation correctness or peer review. An already published reference can be declared before the measured run; the reference need not have been computed by the evaluated method. Automatic comparison does not replace review of the source extraction, compatible energy zero, experimental conditions or domain-specific tolerances.

The acceptance condition is `scientific_reference_campaign`. Overall `passed` requires all explicitly declared comparisons to pass using genuine BASE engine authority and independent reference citations. Missing/incomplete evidence remains `pending`; an exceeded tolerance is `failed`. CLI assessment exits 0 for `passed`, 3 for `pending`/`failed`, and 2 when malformed or inconsistent evidence is rejected.

An independently executed prior native calculation may instead define a `reproducibility-calibration` campaign. Numerical agreement then produces `comparison_status="passed"`, `calibration_passed=true`, overall `status="pending"` and `release_eligible=false`. This can test the complete integration flow but cannot clear scientific reference acceptance. Tests and public parser fixtures similarly cannot stand in for executed physical validation. A passed campaign only covers its explicitly named cases; it provides no general method-accuracy, exhaustive sampling or experimental-rotor claim.
