"""External matrix-parent admission only; no native calculation or authority simulated."""
from __future__ import annotations

import pytest

from topos.capabilities import validate_route
from topos.config import SystemConfig
from topos.method_matrix import MATRIX_REVISION
from topos.models import Molecule, RunRequest
from topos.storage import RunStore, digest_json
from topos.workflow import Workflow


@pytest.fixture(autouse=True)
def linux_admission(monkeypatch):
    monkeypatch.setattr("topos.capabilities.platform.system", lambda: "Linux")


def request(engine="cfour", row="T3C-30min", **changes):
    fields = {"molecule": Molecule(symbols=["O", "H", "H"],
        coordinates=[[0., 0., 0.], [.9572, 0., 0.], [-.23999, .9273, 0.]]),
        "purpose": "matrix", "matrix_revision": MATRIX_REVISION, "matrix_row_id": row,
        "engine": engine, "method": "MP2", "threads": 1, "memory_mb": 128}
    fields.update(changes)
    return RunRequest(**fields)


def problem(value):
    return validate_route(value, SystemConfig(execution_backend="development", max_threads=2, max_memory_mb=2048))


@pytest.mark.parametrize("row", ["T3C-30min", "T3C-1h", "T3C-3h", "T3C-12h", "T3C-1d", "T3C-3d", "T3C-1w", "T5-1w"])
def test_compiled_cfour_matrix_parent_reaches_separate_scientific_preflight(row):
    # These are route-only declarations, intentionally without GENBAS or a
    # runtime. Admission cannot establish scientific support or execution.
    assert problem(request(row=row)) is None


def test_psi4_sapt_matrix_parent_reaches_its_own_separate_preflight():
    assert problem(request(engine="psi4", row="T5-1mo", method="SAPT2+3")) is None


@pytest.mark.parametrize("engine,row", [
    ("cfour", "T3O-10s"), ("cfour", "T5-1mo"), ("psi4", "T3C-30min"),
    ("cfour", "T3O-1w"),
])
def test_parent_cannot_borrow_another_compiled_engines_recipe(engine, row):
    result = problem(request(engine=engine, row=row))
    assert result[0] == "unsupported" and "compiled matrix recipe" in result[1]


def test_reviewed_source_resolution_controls_actual_engine_instead_of_track_name():
    # The explicitly reviewed T3O-1w counterpoise branch uses CFOUR despite its
    # ORCA track name. Missing scientific inputs still fail later preflight.
    assert problem(request(row="T3O-1w", matrix_inputs={
        "source_resolution": "cfour-relaxed-counterpoise-geometry-v1"})) is None


@pytest.mark.parametrize("row", ["T3C-10s", "T3C-1min", "T4C-1min"])
def test_unavailable_source_gaps_and_torq_ownership_cannot_admit_external_parent(row):
    result = problem(request(row=row))
    assert result[0] == "unsupported" and "implemented TOPOS matrix recipe" in result[1]


@pytest.mark.parametrize("engine", ["molpro", "mpqc", "unknown", "scipy", "topos"])
def test_arbitrary_or_internal_engine_names_are_not_new_native_adapters(engine):
    assert problem(request(engine=engine))[0] == "unsupported"


def test_contradictory_typed_native_engine_is_rejected_before_a_runtime_is_loaded():
    external = {"engine": "psi4", "engine_version": "1.10.2", "method": "SAPT2+3",
        "operation": "sapt-decomposition", "orbital_basis": "aug-cc-pVDZ", "frozen_core": True,
        "auxiliary_scf_basis": "aug-cc-pVDZ-jkfit", "auxiliary_sapt_basis": "aug-cc-pVDZ-ri"}
    result = problem(request(matrix_inputs={"external_protocol": external}))
    assert result[0] == "unsupported" and "typed native protocol" in result[1]


@pytest.mark.parametrize("inputs", [
    {"source_resolution": "not-reviewed"},
    {"source_resolution": "orca-f12d-numerical-geometry-dz-v1"},
    {"external_protocol": {"engine": "cfour"}},
])
def test_invalid_or_inapplicable_matrix_inputs_do_not_expand_admission(inputs):
    assert problem(request(matrix_inputs=inputs))[0] == "unsupported"


@pytest.mark.parametrize("engine,method,profile", [
    ("cfour", "MP2", "screening-v1"), ("psi4", "SAPT2+3", "screening-v1"),
])
def test_external_engines_remain_unavailable_as_ordinary_workflow_adapters(engine, method, profile):
    assert problem(request(engine=engine, purpose="energy", method=method,
        profile_id=profile, matrix_revision="topos-0.1.0-supported-profile-v1", matrix_row_id=None))[0] == "unsupported"


@pytest.mark.parametrize("engine,method,profile", [
    ("xtb", "GFN2-xTB", "xtb-vtight-v1"), ("orca", "HF-3c", "orca-mapping-v4.2"),
])
def test_existing_ordinary_profile_admission_is_preserved(engine, method, profile):
    assert problem(request(engine=engine, purpose="energy", method=method,
        profile_id=profile, matrix_revision="topos-0.1.0-supported-profile-v1", matrix_row_id=None)) is None


def test_shared_resource_limits_are_still_applied_after_external_parent_admission():
    assert problem(request(memory_mb=4096)) == ("unavailable", "Requested engine memory exceeds available or configured memory.")


def test_local_gas_phase_and_cpu_gates_still_apply_to_external_matrix_parents():
    assert problem(request(calculation_environment="github-actions"))[0] == "unavailable"
    assert problem(request(device="gpu"))[0] == "unsupported"
    molecule = request().molecule.model_copy(update={"environment": {"phase": "liquid"}})
    assert problem(request(molecule=molecule))[0] == "unsupported"


def external_inputs(**changes):
    # This is a declared input contract, not an installed runtime or a claim
    # that this nonexistent library has passed native identity verification.
    protocol = {"engine": "cfour", "engine_version": "2.1", "method": "MP2",
        "operation": "optimize", "orbital_basis": "PVDZ", "frozen_core": True,
        "genbas_path": "/nonexistent-test-only/GENBAS", "genbas_sha256": "0" * 64}
    protocol.update(changes)
    return {"external_resolution": "cfour-topos-cartesian-optimizer-v1",
        "external_protocol": protocol}


def test_workflow_preserves_honest_cfour_parent_and_dispatches_exact_external_recipe(tmp_path, monkeypatch):
    from topos.external_engines import run_external

    observed = []
    guard = "Test boundary guard: native chemistry deliberately not run"

    def stop_before_native(workflow, record, store, key, molecule, protocol, runner, deadline, cancel_event):
        assert record.request.engine == "cfour"
        assert key == "external-T3C-30min"
        assert (protocol.engine, protocol.engine_version, protocol.method,
            protocol.operation, protocol.orbital_basis, protocol.frozen_core) == (
                "cfour", "2.1", "MP2", "optimize", "PVDZ", True)
        assert runner is run_external
        observed.append(key)
        raise RuntimeError(guard)

    monkeypatch.setattr("topos.external_matrix_workflow.run_component", stop_before_native)
    declared = request(engine_version="2.1", basis="cc-pVDZ", matrix_inputs=external_inputs())
    result = Workflow(tmp_path / "runs", config=SystemConfig(execution_backend="development")).run(declared)
    assert observed == ["external-T3C-30min"]
    assert result.status == "unsupported" and result.metadata["termination_reason"] == guard
    assert result.metadata["matrix_plan"]["runnable"] is True
    assert result.request.engine == "cfour" and not result.attempts and not result.candidates
    saved = RunStore(result.metadata["run_dir"]).recover()
    assert saved["request"] == declared.model_dump(mode="json")
    assert saved["request"]["engine"] == "cfour"
    assert saved["metadata"]["request_sha256"] == digest_json(saved["request"])


@pytest.mark.parametrize("row,inputs,reason", [
    ("T3O-10s", external_inputs(), "compiled matrix recipe"),
    ("T3C-30min", {"external_protocol": {
        "engine": "psi4", "engine_version": "1.10.2", "method": "SAPT2+3",
        "operation": "sapt-decomposition", "orbital_basis": "aug-cc-pVDZ", "frozen_core": True,
        "auxiliary_scf_basis": "aug-cc-pVDZ-jkfit", "auxiliary_sapt_basis": "aug-cc-pVDZ-ri"}},
        "typed native protocol"),
    ("T3C-30min", external_inputs(method="CCSD(T)"), "method MP2 and matching basis"),
    ("T3C-30min", {"external_protocol": external_inputs()["external_protocol"]}, "external_resolution"),
])
def test_workflow_route_and_exact_scientific_gates_precede_native_boundary(tmp_path, monkeypatch, row, inputs, reason):
    def forbidden_native(*args, **kwargs):
        pytest.fail("Invalid request reached the native component boundary")

    monkeypatch.setattr("topos.external_matrix_workflow.run_component", forbidden_native)
    result = Workflow(tmp_path / "runs", config=SystemConfig(execution_backend="development")).run(
        request(row=row, matrix_inputs=inputs))
    assert result.status == "unsupported" and reason in result.metadata["termination_reason"]
    assert not result.attempts and not result.candidates
    assert RunStore(result.metadata["run_dir"]).recover()["request"]["engine"] == "cfour"
