"""Native matrix-stage integration and honest compound-recipe capability gates.

The positive native tests execute CREST/xTB. No ORCA result or GOAT source is
manufactured, and these tests do not certify the complete licensed QM pipeline.
"""
from __future__ import annotations

import os
import shutil
import time
from threading import Event

import pytest

from topos.config import SystemConfig
from topos.matrix_union import native_stage
from topos.matrix_workflow import runtime_recipe_capabilities
from topos.method_matrix import MATRIX_REVISION, HardwareSpec, plan_route
from topos.models import Molecule, RunRecord, RunRequest
from topos.sampling import SampledConformer
from topos.storage import IntegrityError, RunStore
from topos.workflow import Workflow


def water():
    return Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.9584, 0, 0], [-.239, .927, 0]])


def union_request(**changes):
    return RunRequest(molecule=water(), purpose="matrix", matrix_revision=MATRIX_REVISION,
                      matrix_row_id="T1-3h", budget_seconds=60, **changes)


@pytest.fixture
def real_context(tmp_path):
    paths = {engine: shutil.which(os.environ.get(f"TOPOS_{engine.upper()}_EXECUTABLE", engine))
             for engine in ("crest", "xtb")}
    if not all(paths.values()):
        pytest.skip("Native stage validation requires installed real CREST/xTB")
    workflow = Workflow(tmp_path / "runs", config=SystemConfig(execution_backend="development", executables=paths))
    result = workflow.run(RunRequest(molecule=water(), purpose="optimize", budget_seconds=30))
    assert result.status == "completed"
    candidate = next(c for c in result.candidates if c.status == "eligible")
    frames = [SampledConformer(molecule=candidate.molecule, energy_hartree=candidate.energy_hartree,
                               source_index=7, source="actual-xTB", metadata={"attempt_id": candidate.attempt_id})]
    record = RunRecord(request=union_request())
    store = RunStore(tmp_path / "union" / record.run_id)
    store.commit(record)
    return workflow, record, store, frames


@pytest.mark.integration
def test_actual_native_stage_checkpoint_resume_without_binary_reexecution(real_context):
    workflow, record, store, frames = real_context
    screened = native_stage(workflow, record, store, frames, "screen", time.monotonic() + 30, None)
    assert screened is not None and len(screened) == 1
    assert record.attempts[-1].metadata["execution_kind"] == "real"
    assert record.attempts[-1].engine_version == "3.0.2"
    assert record.attempts[-1].metadata["potential_engine_version"] == "6.7.1"
    assert store.verify()
    restored = RunRecord.model_validate(store.recover())
    saved = dict(workflow.config.executables)
    workflow.config.executables = {"xtb": "/missing/xtb", "crest": "/missing/crest"}
    cached = native_stage(workflow, restored, store, frames, "screen", time.monotonic() + 30, None)
    assert cached == screened
    assert len(restored.attempts) == 1
    workflow.config.executables = saved
    unique = native_stage(workflow, restored, store, screened, "cregen", time.monotonic() + 30, None,
                          comparison_protocol="actual-GFN2-native-stage-test")
    assert len(unique) == 1 and unique[0].energy_hartree == screened[0].energy_hartree
    assert unique[0].source_index == screened[0].source_index
    assert restored.attempts[-1].metadata["role"] == "matrix-native-cregen"
    assert store.verify()


@pytest.mark.integration
def test_gpu_parent_uses_actual_cpu_cregen_after_model_search(real_context, tmp_path):
    """Real xTB frames + real CREGEN; this does not pretend GPU training ran."""
    workflow, source_record, _, frames = real_context
    request = source_record.request.model_copy(update={"device": "gpu", "matrix_row_id": "T1-1w"})
    record = RunRecord(request=request)
    store = RunStore(tmp_path / "gpu-parent" / record.run_id)
    store.commit(record)
    unique = native_stage(workflow, record, store, frames, "cregen", time.monotonic() + 30, None,
                          comparison_protocol="actual-GFN2-GPU-parent-allocation-regression")
    assert unique is not None and len(unique) == 1
    assert record.request.device == "gpu"
    attempt = record.attempts[-1]
    assert attempt.status == "completed" and attempt.metadata["execution_kind"] == "real"
    assert attempt.metadata["resources"]["device"] == "cpu"
    assert attempt.metadata["resources"]["threads"] == record.request.threads
    assert attempt.metadata["resources"]["memory_mb"] == record.request.memory_mb
    assert unique[0].energy_hartree == frames[0].energy_hartree
    assert store.verify()


@pytest.mark.integration
def test_cached_native_stage_tamper_is_rejected(real_context):
    workflow, record, store, frames = real_context
    result = native_stage(workflow, record, store, frames, "cregen", time.monotonic() + 30, None,
                          comparison_protocol="actual-GFN2-native-stage-test")
    assert result is not None
    artifact = record.attempts[-1].artifacts[0]
    (store.run_dir / artifact.path).write_bytes(b"tampered retained evidence")
    with pytest.raises(IntegrityError, match="artifact changed"):
        native_stage(workflow, record, store, frames, "cregen", time.monotonic() + 30, None,
                      comparison_protocol="actual-GFN2-native-stage-test")


@pytest.mark.integration
@pytest.mark.parametrize("cancelled", [True, False])
def test_completed_native_cache_cannot_override_cancellation_or_deadline(real_context, cancelled):
    workflow, record, store, frames = real_context
    result = native_stage(workflow, record, store, frames, "cregen", time.monotonic() + 30, None,
                          comparison_protocol="actual-GFN2-native-stage-test")
    assert result is not None and record.attempts[-1].status == "completed"
    event = Event()
    if cancelled:
        event.set()
    cached = native_stage(workflow, record, store, frames, "cregen", 0 if not cancelled else time.monotonic()+30,
                          event, comparison_protocol="actual-GFN2-native-stage-test")
    assert cached is None and record.status == ("cancelled" if cancelled else "timed-out")
    assert len(record.attempts) == 1 and record.attempts[0].status == "completed"


def test_native_stage_cancellation_before_execution_retains_no_fabricated_result(tmp_path):
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend="development", executables={"crest": "/missing"}))
    record = RunRecord(request=union_request())
    store = RunStore(tmp_path / record.run_id)
    event = Event()
    event.set()
    result = native_stage(workflow, record, store, [], "screen", time.monotonic() + 5, event)
    assert result is None and record.status == "cancelled" and not record.attempts


def test_default_native_analytic_hessian_still_requires_verified_sources(tmp_path):
    result = Workflow(tmp_path, config=SystemConfig(execution_backend="development")).run(union_request())
    assert result.status == "unsupported" and not result.attempts
    assert "goat_ensemble" in result.metadata["termination_reason"]
    assert "crest_ensemble" in result.metadata["termination_reason"]
    assert "derivative_resolution" not in result.metadata["termination_reason"]


def test_explicit_resolution_still_requires_both_native_source_records(tmp_path):
    result = Workflow(tmp_path, config=SystemConfig(execution_backend="development")).run(
        union_request(matrix_inputs={"derivative_resolution": "physical-central-gradient-hessian-v1"}))
    assert result.status == "unsupported" and not result.attempts
    assert "goat_ensemble" in result.metadata["termination_reason"]
    assert "crest_ensemble" in result.metadata["termination_reason"]


def test_plain_molecules_cannot_be_declared_native_goat_provenance(tmp_path):
    result = Workflow(tmp_path, config=SystemConfig(execution_backend="development")).run(
        union_request(matrix_inputs={"derivative_resolution": "physical-central-gradient-hessian-v1",
                                     "goat_ensemble": [water().model_dump()]}))
    assert result.status == "unsupported" and not result.attempts


def test_native_screen_cannot_silently_ignore_nested_geometry_cap(tmp_path):
    result = Workflow(tmp_path, config=SystemConfig(execution_backend="development")).run(
        union_request(per_geometry_budget_seconds=1.0,
                      matrix_inputs={"derivative_resolution": "physical-central-gradient-hessian-v1"}))
    assert result.status == "unsupported" and not result.attempts
    assert "per-geometry wall cap" in result.metadata["termination_reason"]


def test_full_union_plan_has_all_compiled_component_capabilities():
    plan = plan_route("T1-3h", hardware=HardwareSpec(cpu_threads=1, memory_mb=4096,
                      threads_per_worker=1, memory_per_worker_mb=4096, fingerprint="test-allocation"),
                      capabilities=runtime_recipe_capabilities(), symbols=["O", "H", "H"],
                      available_inputs=["molecule", "goat_ensemble", "crest_ensemble"])
    assert plan.runnable, plan.blockers
    assert [step.operation for step in plan.steps] == ["union", "screen", "optimize-ensemble", "hessian-ensemble", "cregen-reporting"]
