"""Deadline arithmetic and evidence validation, without simulated calculations."""
import pytest

from topos.actions.queue_budget import (
    local_request_with_budget,
    queue_accounting,
    verify_queue_record,
)


def test_queue_setup_and_execution_share_single_absolute_budget():
    request = {"budget_seconds": 120, "include_queue_in_budget": True, "calculation_environment": "github-actions"}
    accounting = queue_accounting(request, "2026-10-07T12:00:00Z", "2026-10-07T12:01:30.5+00:00")
    assert accounting["remaining_execution_seconds"] == 29.5
    assert accounting["deadline_at"] == "2026-10-07T12:02:00+00:00"
    assert local_request_with_budget(request, accounting)["budget_seconds"] == 29.5
    assert request["budget_seconds"] == 120


@pytest.mark.parametrize("created,boundary", [("invalid", "2026-10-07T12:00:00Z"),
                                              ("2026-10-07T12:00:00", "2026-10-07T12:00:00Z"),
                                              ("2026-10-07T12:00:01Z", "2026-10-07T12:00:00Z")])
def test_queue_origin_requires_ordered_utc_server_timestamps(created, boundary):
    with pytest.raises(ValueError):
        queue_accounting({"budget_seconds": 120}, created, boundary)


def test_expired_evidence_cannot_contain_scientific_attempts():
    request = {"budget_seconds": 1, "include_queue_in_budget": True}
    accounting = queue_accounting(request, "2026-10-07T12:00:00Z", "2026-10-07T12:00:02Z")
    record = {"status": "timed-out", "attempts": [{"status": "running"}], "metadata": {"budget_accounting": accounting}}
    with pytest.raises(ValueError, match="no scientific attempts"):
        verify_queue_record(request, record, accounting, "2026-10-07T12:00:00Z")
