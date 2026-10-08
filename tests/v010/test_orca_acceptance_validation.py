"""Acceptance state-policy checks; no calculation or native output is mocked."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/accept_orca_topos.py"
spec = importlib.util.spec_from_file_location("topos_acceptance_validation", SCRIPT)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


@pytest.mark.parametrize("record_status", ["human-review", "validated-for-protocol"])
def test_native_protocol_validation_does_not_imply_operator_review(record_status):
    record = SimpleNamespace(validation_status=record_status, attempts=[
        SimpleNamespace(command=["native-engine"], validation_status="validated-for-protocol")])
    acceptance._require_calculation_validation(record)
    assert record.validation_status == record_status


@pytest.mark.parametrize("record_status,native_status", [
    ("rejected", "validated-for-protocol"),
    ("not-evaluated", "validated-for-protocol"),
    ("human-review", "human-review"),
    ("validated-for-protocol", "rejected"),
])
def test_unvalidated_native_observations_cannot_pass(record_status, native_status):
    record = SimpleNamespace(validation_status=record_status, attempts=[
        SimpleNamespace(command=["native-engine"], validation_status=native_status)])
    with pytest.raises(acceptance.AcceptanceFailure, match="protocol validation"):
        acceptance._require_calculation_validation(record)


def test_internal_bookkeeping_is_not_native_calculation_evidence():
    record = SimpleNamespace(validation_status="human-review", attempts=[
        SimpleNamespace(command=["topos-internal"], validation_status="validated-for-protocol")])
    with pytest.raises(acceptance.AcceptanceFailure, match="No real native"):
        acceptance._require_calculation_validation(record)
