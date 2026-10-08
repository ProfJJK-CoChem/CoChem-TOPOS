"""Finite invocation budgets and resource admission for native scientific jobs.

This module schedules ownership; BASE/runtime executes and terminates processes.
A cancellation signal or expired lease is not evidence that a process stopped.
Workers must report their real terminal outcome before their resources are freed.
No timing estimate or Hamiltonian change is inferred from a budget or retry.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from threading import Event, RLock
from typing import Callable, Literal
from uuid import uuid4

BudgetScope = Literal["geometry", "ensemble", "workflow"]
TerminalStatus = Literal["completed", "partial", "timed-out", "cancelled", "failed", "unavailable", "unsupported"]
TERMINAL_STATUSES = {"completed", "partial", "timed-out", "cancelled", "failed", "unavailable", "unsupported"}


def _positive(value: float, name: str) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return float(value)


def _integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


class ExecutionBudget:
    """One invocation's monotonic deadline with explicit queue accounting.

    An unstarted budget excludes queue time only when ``include_queue=False``.
    Resuming a run requires a new budget object and a recorded continuation;
    this object never silently renews its deadline.
    """

    def __init__(self, seconds: float, *, scope: BudgetScope = "workflow",
                 include_queue: bool = False, clock: Callable[[], float] = time.monotonic):
        self.seconds = _positive(seconds, "budget seconds")
        if scope not in {"geometry", "ensemble", "workflow"}:
            raise ValueError("Unknown budget scope")
        if not isinstance(include_queue, bool):
            raise ValueError("include_queue must be boolean")
        self.scope, self.include_queue, self._clock = scope, include_queue, clock
        self.queued_at = self._now()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.status = "queued"
        self._last_time = self.queued_at

    def _now(self) -> float:
        now = float(self._clock())
        if not math.isfinite(now) or now < getattr(self, "_last_time", now):
            raise ValueError("Budget clock must be finite and monotonic")
        self._last_time = now
        return now

    @property
    def deadline(self) -> float | None:
        anchor = self.queued_at if self.include_queue else self.started_at
        if anchor is None:
            return None
        deadline = anchor + self.seconds
        if not math.isfinite(deadline):
            raise ValueError("Budget deadline must remain finite")
        return deadline

    def start(self) -> float:
        if self.status != "queued":
            raise ValueError("An invocation budget can start only once")
        now = self._now()
        if self.include_queue and now >= self.queued_at + self.seconds:
            self.status, self.finished_at = "timed-out", now
            raise TimeoutError("Invocation budget expired while queued")
        self.started_at, self.status = now, "running"
        return self.deadline

    def remaining_seconds(self) -> float:
        now = self.finished_at if self.finished_at is not None else self._now()
        if self.status in TERMINAL_STATUSES:
            return 0.0
        return self.seconds if self.deadline is None else max(0.0, self.deadline - now)

    def finish(self, status: TerminalStatus) -> None:
        if status not in TERMINAL_STATUSES or self.status in TERMINAL_STATUSES:
            raise ValueError("Invalid or duplicate terminal budget transition")
        if status == "completed" and self.started_at is None:
            raise ValueError("An unstarted invocation cannot be completed")
        now = self._now()
        if status == "completed" and self.deadline is not None and now > self.deadline:
            raise TimeoutError("A completed invocation cannot exceed its declared execution budget")
        self.status, self.finished_at = status, now

    def snapshot(self) -> dict[str, object]:
        now = self.finished_at if self.finished_at is not None else self._now()
        queue_end = self.started_at if self.started_at is not None else now
        execution = 0.0 if self.started_at is None else now - self.started_at
        remaining = (0.0 if self.status in TERMINAL_STATUSES else self.seconds
                     if self.deadline is None else max(0.0, self.deadline - now))
        return {
            "scope": self.scope, "budget_seconds": self.seconds,
            "queue_time_in_budget": self.include_queue, "status": self.status,
            "queue_seconds": queue_end - self.queued_at, "execution_seconds": execution,
            "elapsed_seconds": now - self.queued_at,
            "charged_seconds": execution + (queue_end - self.queued_at if self.include_queue else 0.0),
            "remaining_seconds": remaining,
            "clock": "monotonic; timestamps are process-local and not portable restart state",
        }


@dataclass(frozen=True)
class ResourceCapacity:
    threads: int
    memory_mb: int
    workers: int = 1

    def __post_init__(self) -> None:
        for name in ("threads", "memory_mb", "workers"):
            _integer(getattr(self, name), name)


@dataclass(frozen=True)
class ScheduledJob:
    job_id: str
    protocol_sha256: str
    threads: int = 1
    memory_mb: int = 1024
    budget_seconds: float | None = None
    include_queue: bool = False
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if not self.job_id or any(ord(c) < 32 for c in self.job_id):
            raise ValueError("A nonempty, printable job ID is required")
        if len(self.protocol_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.protocol_sha256):
            raise ValueError("An exact SHA-256 scientific protocol identity is required")
        for name in ("threads", "memory_mb", "max_attempts"):
            _integer(getattr(self, name), name)
        if self.budget_seconds is not None:
            _positive(self.budget_seconds, "job budget seconds")
        if not isinstance(self.include_queue, bool):
            raise ValueError("include_queue must be boolean")


@dataclass(frozen=True)
class ExecutionLease:
    attempt_id: str
    job: ScheduledJob
    attempt_number: int
    parent_attempt_id: str | None
    queued_at: float
    started_at: float
    deadline: float
    cancel_event: Event = field(default_factory=Event, compare=False, repr=False)

    def remaining_seconds(self, now: float | None = None) -> float:
        instant = time.monotonic() if now is None else now
        if not math.isfinite(instant) or instant < self.started_at:
            raise ValueError("Lease time must be finite and cannot precede execution")
        return max(0.0, self.deadline - instant)


class ResourceScheduler:
    """Admit oldest ready jobs that fit explicit CPU/RAM/worker ceilings.

    Active leases count against capacity until ``finish`` records a real outcome.
    ``expire`` and ``cancel`` signal active workers and finalize only queued work.
    Retry is explicit, bounded, and immutable in scientific protocol and resources.
    Scheduler methods are safe to call from worker completion threads.
    """

    def __init__(self, capacity: ResourceCapacity, budget: ExecutionBudget):
        self.capacity, self.budget = capacity, budget
        self._jobs: dict[str, ScheduledJob] = {}
        self._pending: dict[str, tuple[float, float]] = {}
        self._active: dict[str, ExecutionLease] = {}
        self._attempts: dict[str, int] = {}
        self._last_attempt: dict[str, str] = {}
        self._outcomes: list[dict[str, object]] = []
        self._cancelled = False
        self._lock = RLock()

    def submit(self, job: ScheduledJob) -> None:
        with self._lock:
            if self._cancelled or self.budget.status in TERMINAL_STATUSES:
                raise ValueError("Cannot submit to a terminal or cancelled invocation")
            if job.job_id in self._jobs:
                raise ValueError("Duplicate job identity; use an explicit retry for a failed attempt")
            if job.threads > self.capacity.threads or job.memory_mb > self.capacity.memory_mb:
                raise ValueError("Job exceeds the total allocated CPU or memory capacity")
            now = self.budget._now()
            self._jobs[job.job_id], self._pending[job.job_id] = job, (now, now)
            self._attempts[job.job_id] = 0

    def _unstarted_outcome(self, job_id: str, now: float, status: str, reason: str) -> None:
        queued, _ = self._pending.pop(job_id)
        self._outcomes.append({
            "job_id": job_id, "protocol_sha256": self._jobs[job_id].protocol_sha256,
            "attempt_id": None, "attempt_number": self._attempts[job_id],
            "parent_attempt_id": self._last_attempt.get(job_id), "status": status,
            "queue_seconds": now - queued, "execution_seconds": 0.0, "reason": reason,
            "engine_started": False,
        })

    def claim_ready(self) -> list[ExecutionLease]:
        with self._lock:
            if self._cancelled:
                return []
            if self.budget.status == "queued":
                try:
                    self.budget.start()
                except TimeoutError:
                    self.expire()
                    return []
            self.expire()
            if self.budget.remaining_seconds() <= 0:
                return []
            now, result = self.budget._now(), []
            cores = sum(item.job.threads for item in self._active.values())
            memory = sum(item.job.memory_mb for item in self._active.values())
            for job_id, (queued, ready) in list(self._pending.items()):
                if len(self._active) >= self.capacity.workers:
                    break
                job = self._jobs[job_id]
                if ready > now or cores + job.threads > self.capacity.threads or memory + job.memory_mb > self.capacity.memory_mb:
                    continue
                deadline = self.budget.deadline
                if job.budget_seconds is not None:
                    deadline = min(deadline, (queued if job.include_queue else now) + job.budget_seconds)
                if deadline <= now:
                    self._unstarted_outcome(job_id, now, "timed-out", "Per-job budget expired in queue")
                    continue
                number = self._attempts[job_id] + 1
                lease = ExecutionLease(f"attempt-{uuid4().hex}", job, number,
                                       self._last_attempt.get(job_id), queued, now, deadline)
                self._attempts[job_id] = number
                self._last_attempt[job_id] = lease.attempt_id
                self._active[lease.attempt_id] = lease
                self._pending.pop(job_id)
                cores, memory = cores + job.threads, memory + job.memory_mb
                result.append(lease)
            return result

    def finish(self, lease: ExecutionLease, status: TerminalStatus, *, reason: str | None = None,
               engine_started: bool | None = None) -> dict[str, object]:
        with self._lock:
            if status not in TERMINAL_STATUSES:
                raise ValueError("Workers must report a real terminal outcome")
            if engine_started is not None and not isinstance(engine_started, bool):
                raise ValueError("Actual engine-start evidence must be boolean or unevaluated")
            if self._active.get(lease.attempt_id) is not lease:
                raise ValueError("Unknown, changed or already finished resource lease")
            now = self.budget._now()
            if status == "completed" and now > lease.deadline:
                raise TimeoutError("Late completion needs a truthful timed-out or partial outcome")
            outcome = {
                "job_id": lease.job.job_id, "protocol_sha256": lease.job.protocol_sha256,
                "attempt_id": lease.attempt_id, "attempt_number": lease.attempt_number,
                "parent_attempt_id": lease.parent_attempt_id, "status": status,
                "queue_seconds": lease.started_at - lease.queued_at,
                "execution_seconds": now - lease.started_at,
                "threads": lease.job.threads, "memory_mb": lease.job.memory_mb,
                "allocated_budget_seconds": lease.deadline - lease.started_at,
                "cancellation_requested": lease.cancel_event.is_set(),
                "reason": reason, "worker_admitted": True, "engine_started": engine_started,
            }
            self._active.pop(lease.attempt_id)
            self._outcomes.append(outcome)
            return dict(outcome)

    def retry(self, job_id: str, *, delay_seconds: float = 0.0) -> None:
        """Explicitly retry the same immutable job, after optional bounded backoff."""
        with self._lock:
            if isinstance(delay_seconds, bool) or not math.isfinite(delay_seconds) or delay_seconds < 0:
                raise ValueError("Retry backoff must be finite and nonnegative")
            if job_id not in self._jobs or job_id in self._pending or any(item.job.job_id == job_id for item in self._active.values()):
                raise ValueError("Only a known terminal job can be retried")
            outcomes = [item for item in self._outcomes if item["job_id"] == job_id]
            if not outcomes or outcomes[-1]["status"] == "completed":
                raise ValueError("A completed job is not automatically recomputed")
            if self._cancelled or self.budget.remaining_seconds() <= delay_seconds:
                raise TimeoutError("Retry does not fit the remaining invocation budget")
            if self._attempts[job_id] >= self._jobs[job_id].max_attempts:
                raise ValueError("Explicit retry attempt limit reached")
            now = self.budget._now()
            self._pending[job_id] = (now, now + delay_seconds)

    def expire(self) -> list[ExecutionLease]:
        """Signal expired active leases; never claim their processes stopped."""
        with self._lock:
            now = self.budget._now()
            workflow_expired = self.budget.remaining_seconds() <= 0
            for job_id, (queued, _) in list(self._pending.items()):
                job = self._jobs[job_id]
                if workflow_expired or (job.include_queue and job.budget_seconds is not None and now >= queued + job.budget_seconds):
                    self._unstarted_outcome(job_id, now, "timed-out", "Invocation or per-job queue budget expired")
            expired = [item for item in self._active.values() if now >= item.deadline]
            for item in expired:
                item.cancel_event.set()
            return expired

    def cancel(self) -> list[ExecutionLease]:
        with self._lock:
            self._cancelled = True
            now = self.budget._now()
            for job_id in list(self._pending):
                self._unstarted_outcome(job_id, now, "cancelled", "Cancelled before engine launch")
            for item in self._active.values():
                item.cancel_event.set()
            return list(self._active.values())

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "capacity": asdict(self.capacity), "budget": self.budget.snapshot(),
                "queued_job_ids": list(self._pending), "active_attempt_ids": list(self._active),
                "reserved_threads": sum(item.job.threads for item in self._active.values()),
                "reserved_memory_mb": sum(item.job.memory_mb for item in self._active.values()),
                "cancellation_requested": self._cancelled,
                "outcomes": [dict(item) for item in self._outcomes],
                "scope": "admission and accounting; native execution and process cleanup remain BASE/runtime-owned",
            }
