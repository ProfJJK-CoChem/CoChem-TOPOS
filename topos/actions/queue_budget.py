"""Server-created workflow deadlines bound to unchanged scientific requests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def utc_timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("GitHub budget timestamp must be an ISO-8601 string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid GitHub budget timestamp") from exc
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("GitHub budget timestamps must identify UTC")
    return result.astimezone(timezone.utc)


def queue_accounting(request: dict[str, Any], created_at: str, boundary_at: str) -> dict[str, Any]:
    """Charge queue and installation once; scientific budget is never increased."""
    created, boundary = utc_timestamp(created_at), utc_timestamp(boundary_at)
    elapsed = (boundary - created).total_seconds()
    if elapsed < 0:
        raise ValueError("Runner execution timestamp precedes server workflow creation")
    budget = float(request["budget_seconds"])
    remaining = max(0.0, budget - elapsed)
    return {
        "mode": "queue-setup-execution", "origin": "github-actions-run-created_at",
        "workflow_created_at": created_at, "execution_boundary_at": boundary_at,
        "original_budget_seconds": budget, "pre_execution_elapsed_seconds": elapsed,
        "remaining_execution_seconds": remaining,
        "deadline_at": (created + timedelta(seconds=budget)).isoformat(),
        "expired_before_execution": remaining == 0,
        "clock_assumption": "GitHub server timestamps and hosted runner UTC clocks are synchronized",
    }


def local_request_with_budget(request: dict[str, Any], accounting: dict[str, Any] | None) -> dict[str, Any]:
    local = {**request, "calculation_environment": "local"}
    if request.get("include_queue_in_budget"):
        if accounting is None:
            raise ValueError("Queue-inclusive execution requires server-bound budget evidence")
        # RunRequest budgets are strictly positive. An expired request retains its
        # original request budget but is committed without launching an engine.
        if not accounting["expired_before_execution"]:
            local["budget_seconds"] = accounting["remaining_execution_seconds"]
    elif accounting is not None:
        raise ValueError("Unexpected queue accounting on an execution-only request")
    return local


def verify_queue_record(request: dict[str, Any], record: dict[str, Any],
                        accounting: dict[str, Any] | None, server_created_at: str | None) -> dict[str, Any]:
    if request.get("include_queue_in_budget"):
        if not isinstance(accounting, dict) or server_created_at is None:
            raise ValueError("Queue-inclusive evidence lacks its server-created deadline")
        expected = queue_accounting(request, server_created_at, accounting.get("execution_boundary_at"))
        if accounting != expected or record.get("metadata", {}).get("budget_accounting") != expected:
            raise ValueError("Worker queue accounting differs from the independent server deadline")
        if expected["expired_before_execution"] and (
            record.get("status") != "timed-out" or record.get("attempts") or record.get("candidates")
        ):
            raise ValueError("An expired queued request must have no scientific attempts or candidates")
    elif accounting is not None:
        raise ValueError("Execution-only request was unexpectedly charged queue time")
    return local_request_with_budget(request, accounting)
