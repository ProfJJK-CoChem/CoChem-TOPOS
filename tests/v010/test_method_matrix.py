"""Scientific routing contracts: catalog completeness is distinct from execution proof."""
from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from topos.method_matrix import (
    MATRIX_REVISION,
    PRIMITIVE_BINDINGS,
    SCIENTIFIC_POLICIES,
    SOURCE_SHA256,
    TIERS,
    BackendCapability,
    CalibratedRuntimeEstimator,
    CalibrationKey,
    HardwareSpec,
    RuntimeSample,
    canonical_row_id,
    load_catalog,
    plan_route,
    resolve_row,
    validate_request_matrix,
)

ROOT = Path(__file__).parents[2]


def hardware(**changes):
    return HardwareSpec(cpu_threads=4, memory_mb=8192, fingerprint="measured-host-A", **changes)


def capability(engine="xtb", operation="optimize", method="GFN2-xTB", **changes):
    data = dict(engine=engine, engine_version={"xtb": "6.7.1", "orca": "6.1.1", "crest": "3.0.2"}[engine],
                operations=[operation], methods=[method], verified=True, evidence="validation-receipt:sha256",
                supported_elements=["H", "C", "N", "O"], supported_multiplicities=[1])
    data.update(changes)
    return BackendCapability(**data)


def plan(row="T3O-10s", **changes):
    data = dict(hardware=hardware(), capabilities=[capability()], available_inputs=["molecule"], symbols=["O", "H", "H"])
    data.update(changes)
    return plan_route(row, **data)


def key(**changes):
    data = dict(row_id="T3O-10s", engine="xtb", engine_version="6.7.1", method="GFN2-xTB",
                profile_id="xtb-vtight-v1", hardware_fingerprint="measured-host-A", threads=1,
                memory_mb=1024, problem=dict(atom_count=3, charge=0, multiplicity=1,
                                             operation="optimize", constraints_sha256="0" * 64))
    data.update(changes)
    return CalibrationKey(**data)


def sample(i, wall=10.0, queue=0.0, **key_changes):
    return RuntimeSample(key=key(**key_changes), wall_seconds=wall, queue_seconds=queue,
                         measurement_id=f"real-measurement-{i}", evidence_sha256="1" * 64)


def primitive_request(row_id="T3O-10s", **changes):
    engine, method, purpose, basis, profile = PRIMITIVE_BINDINGS[canonical_row_id(row_id)]
    data = dict(matrix_row_id=row_id, matrix_revision=MATRIX_REVISION, engine=engine,
                method=method, purpose=purpose, basis=basis, profile_id=profile, dispersion=None,
                auxiliary_basis="def2/J" if method == "wB97X-V" else None, solvent=None, constraints={}, metadata={})
    data.update(changes)
    return SimpleNamespace(**data)


def test_complete_catalog_matches_source_identity_and_all_fourteen_tables():
    source = ROOT / "wiki/Method_Matrix.md"
    catalog = load_catalog(source)
    assert catalog.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA256
    assert len(catalog.rows) == 140
    assert len({r.row_id for r in catalog.rows}) == 140
    assert set(Counter(r.row_id.split("-")[0] for r in catalog.rows).values()) == {10}
    assert set(r.tier for r in catalog.rows) == set(TIERS)
    lines = source.read_text().splitlines()
    for row in catalog.rows:
        assert row.row_id in lines[row.source.line - 1]
        assert row.method_text in lines[row.source.line - 1]
        assert row.expansion and row.expansion_source
        assert row.owner in {"TOPOS", "TORQ"}
        assert row.reference_budget_seconds == TIERS[row.tier]


def test_source_revision_drift_is_a_failure(tmp_path):
    changed = tmp_path / "changed.md"
    changed.write_text((ROOT / "wiki/Method_Matrix.md").read_text() + "\nchanged\n")
    with pytest.raises(ValueError, match="differs"):
        load_catalog(changed)


@pytest.mark.parametrize("alias,canonical", [("T3-3h", "T3O-3h"), ("T4-1h", "T4O-1h"),
                                             ("T6-10s", "T6O-10s"), ("T8-1h", "T8O-1h")])
def test_only_documented_decision_card_aliases(alias, canonical):
    assert canonical_row_id(alias) == canonical
    assert resolve_row(alias).row_id == canonical


@pytest.mark.parametrize("row", ["T3O-5h", "T11-1h", "T1-3h;orcaspoof", "T3O-1h\n", "", None])
def test_invalid_row_identifiers_rejected(row):
    with pytest.raises(ValueError):
        resolve_row(row)


def test_purpose_product_and_track_are_separate_selections():
    c = load_catalog()
    assert c.select(purpose="equilibrium-geometry", tier="30min").row_id == "T3O-30min"
    assert c.select(purpose="equilibrium-geometry", tier="30min", track="CFOUR").row_id == "T3C-30min"
    with pytest.raises(ValueError, match="CFOUR track"):
        c.select(purpose="search", tier="1h", track="CFOUR")
    with pytest.raises(ValueError, match="Product B"):
        resolve_row("T4O-1min")
    with pytest.raises(ValueError, match="purpose"):
        resolve_row("T3O-30min", purpose="search")
    assert resolve_row("T4O-1min", product="B").product == "B"


def test_no_executable_discovery_or_nominal_budget_can_make_a_plan_runnable():
    p = plan(capabilities=[])
    assert not p.runnable and p.blockers
    assert p.estimated_wall_seconds is None
    assert p.row.reference_budget_seconds == 10
    assert p.steps[0].device == "unresolved"


def test_verified_exact_capability_and_inputs_make_a_plan_ready_not_executed():
    p = plan()
    assert p.runnable and not p.blockers
    assert p.steps[0].method == "GFN2-xTB"
    assert p.steps[0].owner == "BASE"
    assert p.steps[0].selected_capability == "xtb/6.7.1"
    assert "completed" not in type(p).model_fields


@pytest.mark.parametrize("changes", [dict(verified=False), dict(evidence=""), dict(engine_version="6.6.0"),
                                     dict(methods=["GFN-FF"]), dict(operations=["energy"]),
                                     dict(supported_elements=["C", "H"]), dict(supported_multiplicities=[3])])
def test_adapter_method_version_operation_and_chemical_domain_are_not_interchangeable(changes):
    assert not plan(capabilities=[capability(**changes)]).runnable


def test_charged_and_open_shell_inputs_need_explicit_capabilities():
    assert not plan(charge=1).runnable
    assert plan(charge=1, capabilities=[capability(supports_ions=True)]).runnable
    assert not plan(multiplicity=3).runnable


def test_frozen_monomer_reference_and_rigid_adapter_are_mandatory():
    cap = capability("orca", "optimize", "r2SCAN-3c")
    p = plan("T3O-1min", capabilities=[cap])
    assert not p.runnable
    assert "isolated_monomer_references" in p.missing_inputs
    cap.supports_rigid_fragments = True
    p = plan("T3O-1min", capabilities=[cap], available_inputs=["molecule", "fragments", "isolated_monomer_references"])
    assert p.runnable
    assert p.steps[0].basis is None
    assert p.steps[0].dispersion is None
    assert p.steps[0].options["frozen_monomer"] == "frozen-iso"


def test_same_functional_with_a_different_basis_is_a_different_route():
    cap = capability("orca", "optimize", "wB97X-V", bases=["def2-TZVPP"])
    assert plan("T3O-30min", capabilities=[cap]).runnable
    assert not plan("T3O-1h", capabilities=[cap]).runnable


def test_orca_is_never_accelerated_by_merely_selecting_gpu():
    cap = capability("orca", "optimize", "wB97X-V", bases=["def2-TZVPP"], devices=["gpu"])
    p = plan("T3O-30min", capabilities=[cap], hardware=hardware(device="gpu", gpu_model="RTX3090", gpu_memory_mb=24000))
    assert not p.runnable


@pytest.mark.parametrize("settings", [dict(workers=3, threads_per_worker=2),
                                     dict(workers=4, memory_per_worker_mb=4096),
                                     dict(device="gpu"), dict(gpu_workers=2, mps_enabled=False)])
def test_worker_products_ram_vram_and_mps_are_bounded(settings):
    with pytest.raises(ValidationError):
        hardware(**settings)


def test_full_r2_cp_and_vpt2_recipe_cannot_collapse_to_one_optimizer():
    p = plan("T3O-3h", capabilities=[capability("orca", "optimize", "wB97M-V", bases=["def2-QZVPP"])])
    assert [s.operation for s in p.steps] == ["optimize", "counterpoise", "vpt2"]
    assert p.steps[1].method == "DLPNO-CCSD(T1)"
    assert "cabs_basis" in p.missing_inputs
    assert not p.runnable
    assert all(s.depends_on == [p.steps[i - 1].step_id] for i, s in enumerate(p.steps) if i)


def test_junchs_includes_all_geometry_components_and_explicit_n_cubed_extrapolation():
    p = plan("T3O-12h")
    assert len(p.steps) == 6
    assert [s.options["frozen_core"] for s in p.steps[:5]] == [True, True, True, True, False]
    assert p.steps[-1].options == {"coordinate_addition": "parameter-wise", "cbs_exponent": 3}


def test_crest_union_refines_at_one_common_level_before_reporting_deduplication():
    p = plan("T1-3h")
    assert [s.operation for s in p.steps] == ["union", "screen", "optimize-ensemble", "hessian-ensemble", "cregen-reporting"]
    assert p.steps[-1].options["rotational_fraction"] == 0.001
    assert p.steps[2].method == p.steps[3].method == "r2SCAN-3c"
    assert {"goat_ensemble", "crest_ensemble"} <= set(p.required_inputs)


def test_independent_crest_nci_route_requires_multiple_seeds_and_exact_energy_window():
    p = plan("T1-1h")
    assert p.steps[0].options["minimum_seeds"] == 3
    assert p.steps[0].options["energy_window_kcal_mol"] == 12
    assert p.steps[0].options["nocross"] and p.steps[0].options["noreftopo"]


def test_contradictory_orca_and_mpqc_source_never_becomes_an_orca_command():
    p = plan("T3O-1d")
    assert p.row.source_conflicts
    assert not p.runnable
    assert "MPQC" in p.row.source_conflicts[0]
    assert "8D" in SCIENTIFIC_POLICIES["orca-cc-hessian"]


@pytest.mark.parametrize("row", ["T3C-10s", "T4C-1min", "T6O-1mo", "T8O-1mo"])
def test_source_track_gaps_remain_explicit_with_alternatives(row):
    p = plan(row)
    assert p.row.track_gap
    assert p.row.alternatives
    assert not p.runnable


def test_all_140_rows_have_a_typed_plan_without_claiming_unavailable_recipe_execution():
    for row in load_catalog().rows:
        p = plan(row.row_id, product=row.product or "A")
        assert p.steps and p.row.row_id == row.row_id
        if p.steps[0].engine == "matrix-recipe":
            assert not p.runnable
            if p.steps[0].operation.startswith("matrix-recipe:"):
                assert p.steps[0].prerequisite
                assert p.steps[0].options["source_sha256"] == SOURCE_SHA256


def test_catalog_calls_return_independent_mutable_models():
    c = load_catalog()
    changed = c.get("T1-10s")
    changed.expansion["workflow"] = "wrong"
    assert c.get("T1-10s").expansion["workflow"] != "wrong"


def test_primitive_execution_preserves_exact_row_binding():
    assert validate_request_matrix(primitive_request()) is None
    assert validate_request_matrix(SimpleNamespace(matrix_row_id=None)) is None
    assert validate_request_matrix(primitive_request("T3-30min")) is None


@pytest.mark.parametrize("changes", [dict(method="GFN-FF"), dict(engine="orca"), dict(purpose="search"),
                                     dict(basis="def2-TZVPP"), dict(profile_id="screening-v1"),
                                     dict(solvent="water"), dict(dispersion="D4"),
                                     dict(matrix_revision="v4.1"), dict(auxiliary_basis="wrong")])
def test_primitive_row_mismatch_is_rejected(changes):
    assert validate_request_matrix(primitive_request(**changes))[0] == "unsupported"


def test_compound_row_cannot_be_laundered_as_primitive_execution():
    request = primitive_request(matrix_row_id="T3O-3h")
    assert "complete matrix execution plan" in validate_request_matrix(request)[1]


def test_runtime_unknown_hardware_and_small_samples_never_claim_budget_fit():
    estimator = CalibratedRuntimeEstimator()
    assert estimator.estimate(key()).fits_budget(10) is None
    estimator.add(sample(1, 10))
    estimator.add(sample(2, 12))
    estimate = estimator.estimate(key())
    assert estimate.matching_samples == 2
    assert estimate.median_seconds == 11
    assert not estimate.calibrated
    assert estimate.fits_budget(100000) is None


def test_runtime_prediction_interval_calibrates_measured_repeatability_not_theory():
    estimator = CalibratedRuntimeEstimator([sample(1, 10), sample(2, 12), sample(3, 9), sample(4, 11)])
    estimate = estimator.estimate(key())
    assert estimate.calibrated and estimate.matching_samples == 4
    assert 0 < estimate.lower_seconds < 9 < estimate.median_seconds < 12 < estimate.upper_seconds
    assert estimate.fits_budget(100)
    assert not estimate.fits_budget(1)
    assert "not chemistry accuracy" in estimate.interpretation


@pytest.mark.parametrize("changes", [dict(hardware_fingerprint="different-host"), dict(threads=2),
                                     dict(engine_version="6.8.0"), dict(method="GFN-FF"),
                                     dict(profile_id="screening-v1"), dict(memory_mb=2048), dict(device="gpu")])
def test_runtime_cache_never_transfers_between_incompatible_scientific_or_hardware_contexts(changes):
    estimator = CalibratedRuntimeEstimator([sample(1), sample(2), sample(3)])
    assert estimator.estimate(key(**changes)).matching_samples == 0


def test_runtime_cache_state_and_constraint_changes_invalidate_measurements():
    estimator = CalibratedRuntimeEstimator([sample(1), sample(2), sample(3)])
    problem = dict(key().problem)
    problem["charge"] = 1
    assert estimator.estimate(key(problem=problem)).matching_samples == 0
    problem["charge"] = 0
    problem["constraints_sha256"] = "2" * 64
    assert estimator.estimate(key(problem=problem)).matching_samples == 0


def test_queue_time_is_explicit_and_optional():
    estimator = CalibratedRuntimeEstimator([sample(1, 10, 100), sample(2, 10, 100), sample(3, 10, 100)])
    assert estimator.estimate(key(), include_queue=True).median_seconds == 110
    assert estimator.estimate(key(), include_queue=False).median_seconds == 10


def test_runtime_evidence_persistence_roundtrip_and_duplicate_protection(tmp_path):
    estimator = CalibratedRuntimeEstimator([sample(1, 10), sample(2, 12), sample(3, 9)])
    path = tmp_path / "measurements.json"
    estimator.save(path)
    loaded = CalibratedRuntimeEstimator.load(path)
    assert loaded.estimate(key()) == estimator.estimate(key())
    with pytest.raises(ValueError, match="counted twice"):
        loaded.add(sample(1))
    path.write_text('{"schema_version":"unknown", "samples":[]}')
    with pytest.raises(ValueError, match="schema"):
        CalibratedRuntimeEstimator.load(path)


def test_mutating_a_sample_does_not_rewrite_prior_measurements():
    original = sample(1, 10)
    estimator = CalibratedRuntimeEstimator([original])
    original.wall_seconds = 999
    assert estimator.estimate(key()).median_seconds == 10


@pytest.mark.parametrize("wall", [0, -1, float("nan"), float("inf")])
def test_invalid_or_nonfinite_runtime_measurements_rejected(wall):
    with pytest.raises(ValidationError):
        sample(1, wall)


def test_timeouts_cannot_be_used_as_converged_runtime_calibrations():
    with pytest.raises(ValidationError):
        RuntimeSample(key=key(), wall_seconds=10, status="timed-out", measurement_id="x", evidence_sha256="1" * 64)


def test_heterogeneous_concurrency_reserves_host_threads_for_gpu_workers():
    with pytest.raises(ValidationError, match="reserved host CPU"):
        hardware(workers=4, heterogeneous_concurrent=True)
    assert hardware(workers=3, heterogeneous_concurrent=True).workers == 3


@pytest.mark.parametrize("field,value", [("atom_count", 0), ("multiplicity", -1),
                                       ("charge", "neutral"), ("operation", ""),
                                       ("constraints_sha256", "unspecified")])
def test_runtime_problem_features_must_be_valid_explicit_scientific_context(field, value):
    problem = dict(key().problem)
    problem[field] = value
    with pytest.raises(ValidationError):
        key(problem=problem)
