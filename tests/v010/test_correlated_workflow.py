"""Correlated routing and native component durability without simulated ORCA.

Positive ledger tests execute genuine GFN2-xTB under its own MethodSpec. They
test engine-independent persistence, never correlated chemistry or ORCA success.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from threading import Event

import pytest

from topos.config import SystemConfig
from topos.correlated import CorrelatedMethod
from topos.correlated_workflow import _protocol_for_row, execute_correlated_recipe
from topos.engines import run_engine
from topos.matrix_components import run_component
from topos.matrix_workflow import MatrixInputs
from topos.models import MethodSpec, Molecule, RunRecord, RunRequest
from topos.storage import IntegrityError, RunStore, digest_json, file_digest
from topos.workflow import Workflow


def water():
    return Molecule(symbols=["O", "H", "H"],
                    coordinates=[[0, 0, 0], [.9584, 0, 0], [-.239, .927, 0]])


def dimer():
    return Molecule(symbols=["He", "He"], coordinates=[[0, 0, 0], [4, 0, 0]],
                    fragments=[[0], [1]], fragment_states=[
                        {"atom_indices": [0], "charge": 0, "multiplicity": 1},
                        {"atom_indices": [1], "charge": 0, "multiplicity": 1}])


def local_protocol(**updates):
    data = dict(method="DLPNO-CCSD(T1)", orbital_basis="cc-pVDZ-F12", frozen_core=True,
                auxiliary_c="cc-pVTZ/C", pno_profile="TightPNO", tcutpno=1e-7,
                local_energy_decomposition=True)
    data.update(updates)
    return CorrelatedMethod(**data)


def f12_protocol(**updates):
    data = dict(method="CCSD(T)-F12D/RI", orbital_basis="cc-pVTZ-F12", frozen_core=True,
                auxiliary_c="cc-pVQZ/C", cabs="cc-pVTZ-F12-CABS")
    data.update(updates)
    return CorrelatedMethod(**data)


def canonical_protocol(**updates):
    data = dict(method="AUTOCI-CCSD(T)", orbital_basis="cc-pVTZ-F12",
                frozen_core=True, operation="optimize")
    data.update(updates)
    return CorrelatedMethod(**data)


@pytest.mark.parametrize("row,protocol", [
    ("T5-12h", local_protocol()), ("T5-1d", local_protocol(local_energy_decomposition=False)),
    ("T5-3d", f12_protocol()), ("T3O-3d", canonical_protocol()),
])
def test_row_binding_preserves_exact_typed_protocol_without_defaults(row, protocol):
    assert _protocol_for_row(row, protocol).model_dump() == protocol.model_dump()
    with pytest.raises(ValueError, match="explicit correlated_protocol"):
        _protocol_for_row(row, None)


@pytest.mark.parametrize("row,protocol", [
    ("T5-12h", local_protocol(orbital_basis="cc-pVTZ-F12")),
    ("T5-12h", local_protocol(tcutpno=1e-6)),
    ("T5-12h", local_protocol(local_energy_decomposition=False)),
    ("T5-3d", f12_protocol(orbital_basis="cc-pVDZ-F12")),
    ("T5-3d", f12_protocol(cabs="cc-pVDZ-F12-CABS")),
    ("T5-3d", local_protocol()),
    ("T3O-3d", canonical_protocol(operation="gradient")),
    ("T3O-3d", canonical_protocol(orbital_basis="cc-pVTZ")),
    ("T3O-3d", CorrelatedMethod(method="MP2", orbital_basis="cc-pVTZ-F12", operation="optimize", frozen_core=True)),
    ("T5-1d", local_protocol()), ("T5-1d", f12_protocol()),
])
def test_wrong_row_method_basis_operation_or_pno_recipe_is_rejected(row, protocol):
    with pytest.raises(ValueError):
        _protocol_for_row(row, protocol)


@pytest.mark.parametrize("row", ["T5-3h", "T1-3h", "unknown-row"])
def test_unimplemented_row_cannot_reuse_arbitrary_correlated_protocol(row):
    with pytest.raises(ValueError, match="no compiled correlated"):
        _protocol_for_row(row, local_protocol())


def context(tmp_path, *, row="T5-12h", molecule=None, executables=None, cap=None):
    workflow = Workflow(tmp_path / "runs", config=SystemConfig(
        execution_backend="development", executables=executables or {"orca": "/missing/licensed-orca"}))
    request = RunRequest(molecule=molecule or dimer(), purpose="matrix", matrix_row_id=row,
                         budget_seconds=60, per_geometry_budget_seconds=cap)
    record = RunRecord(request=request, status="running")
    store = RunStore(workflow.output_root / record.run_id)
    store.commit(record)
    return workflow, record, store


@pytest.mark.parametrize("row,inputs,reason", [
    ("T5-12h", MatrixInputs(), "correlated_protocol"),
    ("T3O-3d", MatrixInputs(correlated_protocol=canonical_protocol()), "correlated_resolution"),
    ("T3O-12h", MatrixInputs(), "same-basis core-valence"),
])
def test_underspecified_recipes_do_not_launch_or_claim_any_result(tmp_path, row, inputs, reason):
    workflow, record, store = context(tmp_path, row=row)
    assert not execute_correlated_recipe(workflow, record, store, inputs, time.monotonic() + 30, None)
    assert record.status == "unsupported" and not record.attempts
    assert reason in record.metadata["termination_reason"]
    assert "matrix_correlated" not in record.metadata


@pytest.mark.parametrize("row,protocol,resolution", [
    ("T5-12h", local_protocol(), None),
    ("T5-1d", local_protocol(local_energy_decomposition=False), None),
    ("T5-3d", f12_protocol(), None),
    ("T3O-3d", canonical_protocol(), "autoci-conventional-transformation-v1"),
])
def test_missing_licensed_binary_persists_unavailable_without_derived_completion(tmp_path, row, protocol, resolution):
    workflow, record, store = context(tmp_path, row=row)
    inputs = MatrixInputs(correlated_protocol=protocol, correlated_resolution=resolution)
    assert not execute_correlated_recipe(workflow, record, store, inputs, time.monotonic() + 30, None)
    assert record.status == "unavailable"
    assert len(record.attempts) == 1 and record.attempts[0].status == "unavailable"
    assert not record.attempts[0].quantities
    assert record.attempts[0].metadata["native_result"]["energy_hartree"] is None
    assert record.attempts[0].metadata["native_result"]["metadata"]["execution_kind"] == "not-executed"
    assert "matrix_correlated" not in record.metadata
    assert store.load()["status"] == "unavailable"
    assert store.verify()


def test_interaction_recipe_requires_two_explicit_fragments_before_execution(tmp_path):
    workflow, record, store = context(tmp_path, molecule=water())
    assert not execute_correlated_recipe(workflow, record, store,
        MatrixInputs(correlated_protocol=local_protocol()), time.monotonic() + 30, None)
    assert "explicit partition and fragment charge/spin states" in record.metadata["termination_reason"]
    assert record.status == "unsupported" and not record.attempts


def xtb_method():
    return MethodSpec(engine="xtb", method="GFN2-xTB", engine_version="6.7.1",
                      purpose="energy", profile_id="xtb-vtight-v1")


def execute_xtb(molecule, protocol, resources, folder, **kwargs):
    """Adapt the generic ledger signature to the real xTB energy adapter."""
    return run_engine(molecule, protocol, resources, folder, operation="energy", **kwargs)


@pytest.fixture
def genuine_component(tmp_path):
    choices = [os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"), "/workspace/.tools/xtb-dist/bin/xtb"]
    binary = next((shutil.which(choice) for choice in choices if shutil.which(choice)), None)
    if binary is None:
        pytest.skip("A real xTB binary is required; no scientific output is simulated")
    workflow, record, store = context(tmp_path, molecule=water(), executables={"xtb": binary}, cap=15.)
    result = run_component(workflow, record, store, "genuine-xtb-energy", water(), xtb_method(),
                           execute_xtb, time.monotonic() + 30, None)
    assert result is not None and result.status == "completed", record.metadata
    assert result.engine == "xtb" and result.method == "GFN2-xTB"
    return workflow, record, store, result


@pytest.mark.integration
def test_real_xtb_component_receipt_resources_and_reuse_are_durable(genuine_component):
    workflow, record, store, result = genuine_component
    attempt = record.attempts[0]
    assert attempt.engine == "xtb" and attempt.method == "GFN2-xTB"
    assert attempt.engine_version == "6.7.1" and attempt.converged
    assert result.metadata["execution_kind"] == "real"
    assert 0 < result.metadata["resources"]["budget_seconds"] <= 15
    assert result.metadata["resources"]["threads"] == record.request.threads
    receipt = next(item for item in attempt.artifacts if item.role == "matrix-native-component-result")
    payload = json.loads((store.run_dir / receipt.path).read_text())
    assert payload == result.model_dump(mode="json")
    assert digest_json(payload) == attempt.metadata["native_result_sha256"]
    for artifact in attempt.artifacts:
        assert not Path(artifact.path).is_absolute()
        assert file_digest(store.run_dir / artifact.path) == artifact.sha256
    assert attempt.quantities[0].value == result.energy_hartree
    assert store.verify()
    restored = RunRecord.model_validate(store.load())
    workflow.config.executables["xtb"] = "/missing/xtb"
    cached = run_component(workflow, restored, store, "genuine-xtb-energy", water(), xtb_method(),
                           execute_xtb, time.monotonic() + 30, None)
    assert cached == result and len(restored.attempts) == 1


@pytest.mark.integration
@pytest.mark.parametrize("mutation", ["bytes", "missing", "symlink"])
def test_retained_native_evidence_tampering_cannot_be_resumed(genuine_component, mutation):
    workflow, record, store, _ = genuine_component
    path = store.run_dir / record.attempts[0].artifacts[0].path
    if mutation == "bytes":
        path.write_bytes(b"corrupted native evidence")
    elif mutation == "missing":
        path.unlink()
    else:
        target = store.run_dir / "copied-native-evidence"
        shutil.copyfile(path, target)
        path.unlink()
        path.symlink_to(target)
    with pytest.raises(IntegrityError):
        run_component(workflow, record, store, "genuine-xtb-energy", water(), xtb_method(),
                      execute_xtb, time.monotonic() + 30, None)


@pytest.mark.integration
def test_modified_in_memory_result_payload_fails_digest_check(genuine_component):
    workflow, record, store, _ = genuine_component
    record.attempts[0].metadata["native_result"]["energy_hartree"] += 1
    with pytest.raises(IntegrityError, match="result identity"):
        run_component(workflow, record, store, "genuine-xtb-energy", water(), xtb_method(),
                      execute_xtb, time.monotonic() + 30, None)


@pytest.mark.integration
@pytest.mark.parametrize("change", ["molecule", "protocol", "component-key"])
def test_resume_requires_exact_component_input_and_protocol(genuine_component, change):
    workflow, record, store, _ = genuine_component
    molecule, protocol, key = water(), xtb_method(), "genuine-xtb-energy"
    if change == "molecule":
        molecule.coordinates[1][0] += .001
    elif change == "protocol":
        protocol.profile_id = "xtb-tight-v1"
    else:
        key = "distinct-component"
    workflow.config.executables["xtb"] = "/missing/xtb"
    assert run_component(workflow, record, store, key, molecule, protocol,
                         execute_xtb, time.monotonic() + 30, None) is None
    assert len(record.attempts) == 2 and record.attempts[-1].status == "unavailable"
    assert record.attempts[0].status == "completed"


@pytest.mark.parametrize("stop", ["cancelled", "timed-out"])
def test_preexecution_cancellation_and_deadline_are_durable_without_native_results(tmp_path, stop):
    workflow, record, store = context(tmp_path, molecule=water())
    event = Event()
    if stop == "cancelled":
        event.set()
    deadline = time.monotonic() + (30 if stop == "cancelled" else -1)
    def never_called(*args, **kwargs):
        raise AssertionError("A stopped component must not launch any executor")
    assert run_component(workflow, record, store, "stopped", water(), xtb_method(), never_called,
                         deadline, event) is None
    assert record.status == stop and not record.attempts
    assert store.load()["status"] == stop


@pytest.mark.integration
def test_real_xtb_result_cannot_certify_different_requested_xtb_method(genuine_component):
    workflow, record, store, _ = genuine_component
    # An intentionally miswired adapter executes real GFN2, whereas its input
    # asks GFN1. Only rejection is expected; no fabricated success is supplied.
    requested = xtb_method().model_copy(update={"method": "GFN1-xTB"})
    def miswired_executor(molecule, protocol, resources, folder, **kwargs):
        return execute_xtb(molecule, xtb_method(), resources, folder, **kwargs)
    with pytest.raises(IntegrityError, match="method|protocol|identity"):
        run_component(workflow, record, store, "wrong-method", water(), requested,
                      miswired_executor, time.monotonic() + 30, None)
