"""Deterministic admission/deadline tests; no engine outputs are fabricated."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from topos.budget import ExecutionBudget, ResourceCapacity, ResourceScheduler, ScheduledJob


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@pytest.fixture
def clock():
    return Clock()


def job(name, **kwargs):
    return ScheduledJob(name, "a" * 64, **kwargs)


@pytest.mark.parametrize("seconds", [0, -1, float("inf"), float("nan"), True])
def test_budget_rejects_nonfinite_or_nonpositive_limits(seconds):
    with pytest.raises(ValueError):
        ExecutionBudget(seconds)


def test_queue_exclusion_and_inclusion_are_different_deadlines(clock):
    execution = ExecutionBudget(10, scope="geometry", include_queue=False, clock=clock)
    elapsed = ExecutionBudget(10, scope="workflow", include_queue=True, clock=clock)
    clock.advance(6)
    assert execution.remaining_seconds() == 10
    assert elapsed.remaining_seconds() == 4
    assert execution.start() == 116
    assert elapsed.start() == 110
    clock.advance(3)
    assert execution.snapshot()["charged_seconds"] == 3
    assert elapsed.snapshot()["charged_seconds"] == 9
    assert execution.snapshot()["queue_seconds"] == 6
    assert elapsed.snapshot()["execution_seconds"] == 3


def test_expired_queue_never_claims_started_or_completed(clock):
    budget = ExecutionBudget(3, include_queue=True, clock=clock)
    scheduler = ResourceScheduler(ResourceCapacity(2, 2048), budget)
    scheduler.submit(job("one"))
    clock.advance(4)
    assert scheduler.claim_ready() == []
    receipt = scheduler.snapshot()
    assert receipt["budget"]["status"] == "timed-out"
    assert receipt["outcomes"][0]["engine_started"] is False
    assert receipt["outcomes"][0]["attempt_id"] is None
    assert receipt["outcomes"][0]["status"] == "timed-out"


def test_deadline_cannot_be_renewed_and_clock_cannot_run_backward(clock):
    budget = ExecutionBudget(5, clock=clock)
    budget.start()
    with pytest.raises(ValueError, match="once"):
        budget.start()
    clock.advance(-1)
    with pytest.raises(ValueError, match="monotonic"):
        budget.snapshot()


def test_terminal_receipt_is_frozen_and_late_completion_is_not_promoted(clock):
    budget = ExecutionBudget(5, clock=clock)
    with pytest.raises(ValueError, match="unstarted"):
        budget.finish("completed")
    budget.start()
    clock.advance(6)
    with pytest.raises(TimeoutError):
        budget.finish("completed")
    budget.finish("timed-out")
    receipt = budget.snapshot()
    clock.advance(30)
    assert budget.snapshot() == receipt
    with pytest.raises(ValueError):
        budget.finish("failed")


@pytest.mark.parametrize("kwargs", [{"threads": 0}, {"memory_mb": True}, {"workers": -1}])
def test_capacity_requires_positive_integer_allocations(kwargs):
    with pytest.raises(ValueError):
        ResourceCapacity(**{"threads": 4, "memory_mb": 4096, "workers": 2, **kwargs})


def test_total_workers_threads_and_memory_are_enforced(clock):
    scheduler = ResourceScheduler(ResourceCapacity(4, 4000, workers=2), ExecutionBudget(60, clock=clock))
    scheduler.submit(job("large", threads=3, memory_mb=3000))
    scheduler.submit(job("medium", threads=2, memory_mb=2000))
    scheduler.submit(job("small", threads=1, memory_mb=1000))
    first = scheduler.claim_ready()
    assert [item.job.job_id for item in first] == ["large", "small"]
    receipt = scheduler.snapshot()
    assert receipt["reserved_threads"] == 4
    assert receipt["reserved_memory_mb"] == 4000
    assert scheduler.claim_ready() == []
    clock.advance(1)
    scheduler.finish(first[0], "completed")
    assert [item.job.job_id for item in scheduler.claim_ready()] == ["medium"]
    assert scheduler.snapshot()["reserved_threads"] == 3


def test_oversized_or_duplicate_job_is_not_silently_clamped(clock):
    scheduler = ResourceScheduler(ResourceCapacity(1, 1024), ExecutionBudget(20, clock=clock))
    with pytest.raises(ValueError, match="capacity"):
        scheduler.submit(job("large", memory_mb=1025))
    scheduler.submit(job("one"))
    with pytest.raises(ValueError, match="Duplicate"):
        scheduler.submit(job("one"))


def test_per_job_queue_budget_and_parent_deadline_both_bound_execution(clock):
    scheduler = ResourceScheduler(ResourceCapacity(1, 1024), ExecutionBudget(20, clock=clock))
    scheduler.submit(job("first", budget_seconds=50))
    scheduler.submit(job("queue-bounded", budget_seconds=2, include_queue=True))
    scheduler.submit(job("execution-only", budget_seconds=3, include_queue=False))
    first = scheduler.claim_ready()[0]
    assert first.deadline == 120
    clock.advance(4)
    scheduler.finish(first, "completed")
    second = scheduler.claim_ready()[0]
    assert second.job.job_id == "execution-only"
    assert second.deadline == 107
    timed_out = [item for item in scheduler.snapshot()["outcomes"] if item["status"] == "timed-out"]
    assert timed_out[0]["job_id"] == "queue-bounded"
    assert timed_out[0]["queue_seconds"] == 4


def test_expiry_signals_but_does_not_release_live_worker_resources(clock):
    scheduler = ResourceScheduler(ResourceCapacity(1, 1024), ExecutionBudget(10, clock=clock))
    scheduler.submit(job("running", budget_seconds=2))
    scheduler.submit(job("waiting"))
    lease = scheduler.claim_ready()[0]
    clock.advance(3)
    assert scheduler.expire() == [lease]
    assert lease.cancel_event.is_set()
    assert scheduler.snapshot()["reserved_threads"] == 1
    assert scheduler.claim_ready() == []
    with pytest.raises(TimeoutError, match="Late completion"):
        scheduler.finish(lease, "completed")
    scheduler.finish(lease, "timed-out", reason="BASE confirmed process-tree termination")
    assert scheduler.claim_ready()[0].job.job_id == "waiting"


def test_cancellation_does_not_claim_process_death(clock):
    scheduler = ResourceScheduler(ResourceCapacity(1, 1024), ExecutionBudget(10, clock=clock))
    scheduler.submit(job("running"))
    scheduler.submit(job("waiting"))
    lease = scheduler.claim_ready()[0]
    assert scheduler.cancel() == [lease]
    assert lease.cancel_event.is_set()
    receipt = scheduler.snapshot()
    assert receipt["active_attempt_ids"] == [lease.attempt_id]
    assert receipt["reserved_memory_mb"] == 1024
    assert receipt["outcomes"][0]["status"] == "cancelled"
    assert receipt["outcomes"][0]["engine_started"] is False
    scheduler.finish(lease, "cancelled")
    assert scheduler.snapshot()["reserved_memory_mb"] == 0
    with pytest.raises(ValueError):
        scheduler.submit(job("later"))


def test_explicit_retry_preserves_protocol_and_parent_and_cannot_run_forever(clock):
    scheduler = ResourceScheduler(ResourceCapacity(1, 1024), ExecutionBudget(15, clock=clock))
    scheduler.submit(job("retry", max_attempts=2))
    first = scheduler.claim_ready()[0]
    clock.advance(1)
    scheduler.finish(first, "failed")
    scheduler.retry("retry", delay_seconds=2)
    assert scheduler.claim_ready() == []
    clock.advance(2)
    second = scheduler.claim_ready()[0]
    assert second.attempt_id != first.attempt_id
    assert second.parent_attempt_id == first.attempt_id
    assert second.attempt_number == 2
    assert second.job is first.job
    scheduler.finish(second, "failed")
    with pytest.raises(ValueError, match="limit"):
        scheduler.retry("retry")


def test_retries_do_not_recompute_completed_jobs_or_extend_parent_budget(clock):
    scheduler = ResourceScheduler(ResourceCapacity(1, 1024), ExecutionBudget(5, clock=clock))
    scheduler.submit(job("complete", max_attempts=2))
    scheduler.submit(job("fail", max_attempts=2))
    lease = scheduler.claim_ready()[0]
    scheduler.finish(lease, "completed")
    with pytest.raises(ValueError, match="completed"):
        scheduler.retry("complete")
    lease = scheduler.claim_ready()[0]
    scheduler.finish(lease, "failed")
    with pytest.raises(TimeoutError, match="remaining"):
        scheduler.retry("fail", delay_seconds=5)


def test_changed_or_duplicate_lease_cannot_release_resources(clock):
    scheduler = ResourceScheduler(ResourceCapacity(1, 1024), ExecutionBudget(5, clock=clock))
    scheduler.submit(job("one"))
    lease = scheduler.claim_ready()[0]
    with pytest.raises(ValueError, match="changed"):
        scheduler.finish(replace(lease, job=replace(lease.job, threads=100)), "completed")
    assert scheduler.snapshot()["reserved_threads"] == 1
    scheduler.finish(lease, "completed")
    with pytest.raises(ValueError, match="finished"):
        scheduler.finish(lease, "completed")


def test_snapshot_caller_cannot_rewrite_scheduler_history(clock):
    scheduler = ResourceScheduler(ResourceCapacity(1, 1024), ExecutionBudget(5, clock=clock))
    scheduler.submit(job("one"))
    lease = scheduler.claim_ready()[0]
    scheduler.finish(lease, "failed")
    snapshot = scheduler.snapshot()
    snapshot["outcomes"][0]["status"] = "completed"
    assert scheduler.snapshot()["outcomes"][0]["status"] == "failed"


def test_competing_dispatchers_cannot_double_admit_or_oversubscribe(clock):
    scheduler = ResourceScheduler(ResourceCapacity(4, 4096, workers=4), ExecutionBudget(30, clock=clock))
    for index in range(20):
        scheduler.submit(job(f"job-{index}"))
    barrier = Barrier(8)

    def claim():
        barrier.wait()
        return scheduler.claim_ready()

    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(pool.map(lambda _: claim(), range(8)))
    leases = [lease for batch in batches for lease in batch]
    assert len(leases) == 4
    assert len({lease.job.job_id for lease in leases}) == 4
    assert scheduler.snapshot()["reserved_threads"] == 4
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda lease: scheduler.finish(lease, "completed"), leases))
    assert len({receipt["attempt_id"] for receipt in receipts}) == 4
    assert scheduler.snapshot()["reserved_threads"] == 0


@pytest.mark.parametrize("include_queue, preparation_seconds, expected", [(False, 6, "unsupported"), (True, 11, "timed-out")])
def test_workflow_uses_measured_preparation_queue_without_starting_engines(
    clock, tmp_path, monkeypatch, include_queue, preparation_seconds, expected,
):
    from topos import workflow as workflow_module
    from topos.config import SystemConfig
    from topos.models import Molecule, RunRequest
    from topos.storage import RunStore

    original_commit = RunStore.commit
    commits = 0

    def commit(store, record):
        nonlocal commits
        result = original_commit(store, record)
        commits += 1
        if commits == 1:
            clock.advance(preparation_seconds)
        return result

    monkeypatch.setattr(RunStore, "commit", commit)
    monkeypatch.setattr(workflow_module, "ExecutionBudget", lambda *args, **kwargs: ExecutionBudget(*args, **kwargs, clock=clock))
    molecule = Molecule(symbols=["He"], coordinates=[[0, 0, 0]])
    request = RunRequest(molecule=molecule, budget_seconds=10, device="cuda", include_queue_in_budget=include_queue)
    flow = workflow_module.Workflow(tmp_path, config=SystemConfig(execution_backend="development"))
    result = flow.run(request)
    assert result.status == expected
    assert not result.attempts
    accounting = result.metadata["budget_accounting"]
    assert accounting["scope"] == "workflow"
    assert accounting["queue_seconds"] == preparation_seconds
    assert accounting["execution_seconds"] == 0
    assert accounting["queue_time_in_budget"] is include_queue
    assert accounting["charged_seconds"] == (preparation_seconds if include_queue else 0)
    assert result.metadata["invocation_budget_history"] == [accounting]
    stored = RunStore(tmp_path / result.run_id).load()
    assert stored["metadata"]["budget_accounting"] == accounting
    if not include_queue:
        clock.advance(100)
        resumed = flow.resume(tmp_path / result.run_id)
        assert len(resumed.metadata["invocation_budget_history"]) == 2
        assert resumed.metadata["invocation_budget_history"][0] == accounting
        assert resumed.metadata["budget_accounting"]["queue_seconds"] == 0


def test_overall_budget_scope_remains_workflow_with_separate_nested_limits():
    from pydantic import ValidationError

    from topos.models import Molecule, RunRequest

    with pytest.raises(ValidationError):
        RunRequest(molecule=Molecule(symbols=["He"], coordinates=[[0, 0, 0]]), budget_scope="geometry")


@pytest.mark.parametrize("field", ["per_geometry_budget_seconds", "per_ensemble_budget_seconds"])
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True])
def test_nested_limits_reject_invalid_durations(field, value):
    from pydantic import ValidationError

    from topos.models import Molecule, RunRequest

    with pytest.raises(ValidationError):
        RunRequest(molecule=Molecule(symbols=["He"], coordinates=[[0, 0, 0]]), **{field: value})


def _genuine_nested_budget_workflow(tmp_path, monkeypatch, clock, engine_elapsed):
    """Control orchestration time only; every returned chemistry result is real xTB.

    A deterministic extra elapsed interval models scheduling/parsing work without
    sleeping or fabricating energies, gradients, files or convergence flags.
    """
    import os
    import shutil
    from types import SimpleNamespace

    from topos import advanced_workflow
    from topos import workflow as module
    from topos.config import SystemConfig

    binary = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if binary is None:
        pytest.skip("genuine xTB required; nested timing tests do not synthesize chemistry")
    actual_engine = module.run_engine
    calls = []

    def measured_engine(molecule, method, resources, *args, **kwargs):
        actual = actual_engine(molecule, method, resources, *args, **kwargs)
        calls.append({"budget_seconds": resources.budget_seconds, "status": actual.status,
                      "operation": kwargs["operation"], "raw_artifacts": len(actual.artifacts)})
        assert actual.status == "completed", actual.diagnostics
        clock.advance(engine_elapsed[len(calls) - 1])
        return actual

    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=clock))
    monkeypatch.setattr(advanced_workflow, "time", SimpleNamespace(monotonic=clock))
    monkeypatch.setattr(module, "ExecutionBudget", lambda *a, **k: ExecutionBudget(*a, **k, clock=clock))
    monkeypatch.setattr(module, "run_engine", measured_engine)
    return module.Workflow(tmp_path, config=SystemConfig(
        execution_backend="development", executables={"xtb": binary})), calls


def _budget_water():
    from topos.models import Molecule

    return Molecule(symbols=["O", "H", "H"],
                    coordinates=[[0, 0, 0], [.9572, 0, 0], [-.23999, .9273, 0]])


@pytest.mark.integration
def test_one_geometry_timeout_retains_real_evidence_and_allows_next_proposal(tmp_path, monkeypatch, clock):
    from topos.models import RunRequest
    from topos.storage import RunStore

    flow, calls = _genuine_nested_budget_workflow(tmp_path, monkeypatch, clock, [11, .25])
    result = flow.run(RunRequest(molecule=_budget_water(), budget_seconds=100,
                                per_ensemble_budget_seconds=50, per_geometry_budget_seconds=10,
                                profile_id="xtb-vtight-v1", n_candidates=2, perturbation_angstrom=.05))
    assert result.status == "partial"
    assert len(calls) == 2 and all(c["raw_artifacts"] for c in calls)
    assert all(c["budget_seconds"] == 10 for c in calls)
    assert [a.status for a in result.attempts] == ["timed-out", "completed"]
    assert result.candidates[0].metadata["geometry_budget_exhausted"] is True
    assert result.candidates[0].status == "timed-out"
    assert result.candidates[1].status == "eligible"
    assert result.candidates[1].energy_hartree is not None
    receipt = result.metadata["nested_budget_accounting"]
    assert [g["elapsed_seconds"] for g in receipt["geometries"]] == [11, .25]
    assert receipt["ensemble"]["elapsed_seconds"] == 11.25
    assert receipt["ensemble"]["deadline_exhausted"] is False
    assert result.metadata["nested_budget_history"] == [receipt]
    RunStore(tmp_path / result.run_id).verify()


@pytest.mark.integration
def test_sampler_preparation_and_refinement_share_one_ensemble_deadline(tmp_path, monkeypatch, clock):
    from topos.models import RunRequest

    flow, calls = _genuine_nested_budget_workflow(tmp_path, monkeypatch, clock, [3])
    actual_plan = flow._sample_plan

    def planned(record, store, deadline, cancel_event):
        plan = actual_plan(record, store, deadline, cancel_event)
        clock.advance(4)
        return plan

    monkeypatch.setattr(flow, "_sample_plan", planned)
    result = flow.run(RunRequest(molecule=_budget_water(), budget_seconds=100,
                                per_ensemble_budget_seconds=5, per_geometry_budget_seconds=10,
                                profile_id="xtb-vtight-v1", n_candidates=2))
    assert result.status == "timed-out"
    assert len(calls) == 1
    assert calls[0]["budget_seconds"] == 1
    assert result.attempts[0].status == "timed-out"
    receipt = result.metadata["nested_budget_accounting"]
    assert receipt["ensemble"]["allocated_seconds"] == 5
    assert receipt["ensemble"]["elapsed_seconds"] == 7
    assert receipt["ensemble"]["deadline_exhausted"] is True
    assert receipt["geometries"][0]["allocated_seconds"] == 1
    assert not any(c.status == "eligible" for c in result.candidates)


@pytest.mark.integration
def test_constrained_optimizer_all_gradients_share_geometry_budget(tmp_path, monkeypatch, clock):
    from topos.models import Molecule, RunRequest

    flow, calls = _genuine_nested_budget_workflow(tmp_path, monkeypatch, clock, [4, 7])
    molecule = Molecule(symbols=["O", "H", "H"] * 2,
                        coordinates=[[0, 0, 0], [.9572, 0, 0], [-.23999, .9273, 0],
                                     [2.9, .1, .2], [3.3, .9, .5], [3.4, -.6, -.2]],
                        fragments=[[0, 1, 2], [3, 4, 5]])
    result = flow.run(RunRequest(molecule=molecule, purpose="optimize", budget_seconds=100,
                                per_geometry_budget_seconds=10, n_candidates=1,
                                constraints={"kind": "frozen-monomers", "profile_id": "mapping-2026",
                                             "reference_source": "test input; benchmark accuracy unverified"}))
    assert result.status == "timed-out"
    assert len(calls) == 2 and all(c["operation"] == "gradient" for c in calls)
    assert [c["budget_seconds"] for c in calls] == [10, 6]
    assert [a.status for a in result.attempts] == ["completed", "timed-out"]
    assert len(result.metadata["nested_budget_accounting"]["geometries"]) == 1
    assert result.metadata["nested_budget_accounting"]["geometries"][0]["elapsed_seconds"] == 11


@pytest.mark.integration
def test_physical_hessian_campaign_does_not_renew_geometry_budget_each_gradient(tmp_path, monkeypatch, clock):
    from topos.models import RunRequest, ThermalOptions

    flow, calls = _genuine_nested_budget_workflow(tmp_path, monkeypatch, clock, [4, 7])
    result = flow.run(RunRequest(molecule=_budget_water(), purpose="frequency", budget_seconds=100,
                                per_geometry_budget_seconds=10,
                                thermochemistry_options=ThermalOptions(optimize_first=False)))
    assert result.status == "timed-out"
    assert len(calls) == 2
    assert [c["budget_seconds"] for c in calls] == [10, 6]
    assert not any(q.name == "cartesian_hessian" for a in result.attempts for q in a.quantities)
    geometry = result.metadata["nested_budget_accounting"]["geometries"][0]
    assert geometry["task"] == "frequency" and geometry["elapsed_seconds"] == 11
