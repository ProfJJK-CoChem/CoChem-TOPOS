"""Public external-recipe contracts and optional genuine Psi4 acceptance."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from topos.config import SystemConfig
from topos.external_engines import ExternalProtocol
from topos.external_matrix_workflow import (
    execute_external_recipe,
    junchs_protocols,
    protocol_for_row,
)
from topos.matrix_workflow import MatrixInputs
from topos.method_matrix import MATRIX_REVISION
from topos.models import Molecule, RunRecord, RunRequest
from topos.storage import RunStore
from topos.workflow import Workflow


def cfour(**changes):
    fields = dict(engine="cfour", engine_version="2.1", method="CCSD(T)", orbital_basis="PVTZ",
                  operation="optimize", frozen_core=True, genbas_path="/licensed/cfour/basis/GENBAS",
                  genbas_sha256="0" * 64)
    fields.update(changes)
    return ExternalProtocol(**fields)


def sapt():
    return ExternalProtocol(engine="psi4", engine_version=os.environ.get("TOPOS_PSI4_VERSION", "1.10.2"),
                            method="SAPT2+3", operation="sapt-decomposition", frozen_core=True,
                            orbital_basis="aug-cc-pVDZ", auxiliary_scf_basis="aug-cc-pVDZ-jkfit",
                            auxiliary_sapt_basis="aug-cc-pVDZ-ri")


def water_dimer():
    return Molecule(symbols=["O", "H", "H", "O", "H", "H"],
                    coordinates=[[-1.551007, -.114520, 0], [-1.934259, .762503, 0], [-.599677, .040712, 0],
                                 [1.350625, .111469, 0], [1.680398, -.373741, -.758561], [1.680398, -.373741, .758561]],
                    fragments=[[0, 1, 2], [3, 4, 5]],
                    fragment_states=[{"atom_indices": [0, 1, 2], "charge": 0, "multiplicity": 1},
                                     {"atom_indices": [3, 4, 5], "charge": 0, "multiplicity": 1}])


@pytest.mark.parametrize("row,selected", [
    ("T3C-30min", cfour(method="MP2", orbital_basis="PVDZ")),
    ("T3C-1h", cfour(operation="first-order-properties")),
    ("T3C-3h", cfour()), ("T3C-12h", cfour(orbital_basis="PVQZ")),
    ("T3C-1d", cfour(orbital_basis="PCVQZ", frozen_core=False)), ("T5-1mo", sapt()),
    ("T3C-3d", cfour(orbital_basis="jun-cc-pVTZ")),
])
def test_row_method_basis_core_operation_exact_binding(row, selected):
    assert protocol_for_row(row, selected) == selected
    with pytest.raises(ValueError, match="external_protocol"):
        protocol_for_row(row, None)


@pytest.mark.parametrize("row,selected", [
    ("T3C-30min", cfour()), ("T3C-1h", cfour()),
    ("T3C-3h", cfour(frozen_core=False)), ("T3C-12h", cfour()),
    ("T3C-1d", cfour(orbital_basis="PCVQZ")), ("T5-1mo", cfour()),
    ("T3C-3d", cfour()), ("T3C-1w", cfour()), ("T3O-1mo", cfour()),
    ("T3C-3h", cfour(genbas_path=None, genbas_sha256=None)),
])
def test_wrong_or_incomplete_recipes_cannot_borrow_external_adapter(row, selected):
    with pytest.raises(ValueError):
        protocol_for_row(row, selected)


def test_cfour_optimizer_resolution_required_before_engine_work(tmp_path):
    workflow = Workflow(tmp_path / "runs", config=SystemConfig(execution_backend="development"))
    request = RunRequest(molecule=water_dimer(), purpose="matrix", matrix_row_id="T3C-3h")
    record = RunRecord(request=request, status="running")
    store = RunStore(workflow.output_root / record.run_id)
    store.commit(record)
    assert not execute_external_recipe(workflow, record, store, MatrixInputs(external_protocol=cfour()), time.monotonic() + 30, None)
    assert record.status == "unsupported" and not record.attempts
    assert "external_resolution" in record.metadata["termination_reason"]


def test_cfour_junchs_components_retain_exact_engine_and_native_library():
    supplied = cfour(orbital_basis="jun-cc-pVTZ")
    components = junchs_protocols(supplied)
    assert {role: (p.method, p.orbital_basis, p.frozen_core) for role, p in components.items()} == {
        "base": ("CCSD(T)", "jun-cc-pVTZ", True), "mp2_tz": ("MP2", "jun-cc-pVTZ", True),
        "mp2_qz": ("MP2", "jun-cc-pVQZ", True), "cv_ae": ("MP2", "cc-pwCVTZ", False),
        "cv_fc": ("MP2", "cc-pwCVTZ", True)}
    assert all(p.operation == "optimize" and p.engine_version == supplied.engine_version
               and p.genbas_path == supplied.genbas_path and p.genbas_sha256 == supplied.genbas_sha256
               for p in components.values())


@pytest.mark.parametrize("resolution,coordinates,reason", [
    (None, None, "same-basis-core-valence"),
    ("junchs-same-basis-core-valence-v1", None, "CompositeCoordinateSet"),
    ("junchs-same-basis-core-valence-v1", {"coordinates": [], "cv_basis": "cc-pwCVTZ", "cv_resolution": "same-basis-ae-minus-fc"}, "coordinate"),
])
def test_cfour_junchs_rejects_missing_resolution_or_incomplete_chart_before_compute(tmp_path, monkeypatch, resolution, coordinates, reason):
    workflow = Workflow(tmp_path / "runs", config=SystemConfig(execution_backend="development"))
    molecule = Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.958, 0, 0], [-.24, .927, 0]])
    record = RunRecord(request=RunRequest(molecule=molecule, purpose="matrix", matrix_row_id="T3C-3d"), status="running")
    store = RunStore(workflow.output_root / record.run_id)
    store.commit(record)
    monkeypatch.setattr("topos.external_matrix_workflow.run_component", lambda *a, **k: pytest.fail("No native execution before chart resolution"))
    inputs = MatrixInputs(external_protocol=cfour(orbital_basis="jun-cc-pVTZ"),
                          external_resolution="cfour-topos-cartesian-optimizer-v1",
                          correlated_resolution=resolution, composite_coordinates=coordinates)
    assert not execute_external_recipe(workflow, record, store, inputs, time.monotonic() + 30, None)
    assert record.status == "unsupported" and not record.attempts
    assert reason.lower() in record.metadata["termination_reason"].lower()


def test_genuine_psi4_public_matrix_request_and_verified_resume(tmp_path, monkeypatch):
    executable = os.environ.get("TOPOS_PSI4_EXECUTABLE")
    if not executable or not Path(executable).is_file():
        pytest.skip("Genuine optional Psi4 installation not configured; no simulated SAPT calculation")
    workflow = Workflow(tmp_path / "runs", config=SystemConfig(execution_backend="development", executables={"psi4": executable}))
    request = RunRequest(molecule=water_dimer(), purpose="matrix", matrix_row_id="T5-1mo", matrix_revision=MATRIX_REVISION, threads=2,
                         memory_mb=4096, budget_seconds=120, matrix_inputs={"external_protocol": sapt().model_dump(mode="json")})
    record = workflow.run(request)
    assert record.status == "completed", record.metadata.get("termination_reason")
    assert record.metadata["matrix_execution"]["full_row_completed"]
    native = [a for a in record.attempts if a.metadata.get("role") == "matrix-native-component"]
    assert len(native) == 1 and native[0].engine == "psi4" and native[0].status == "completed"
    output = record.metadata["matrix_external"]
    assert output["interaction_energy_hartree"] == pytest.approx(-.007180024787318715, abs=3e-8)
    assert output["geometry_optimized"] is False and output["automatic_pes_performed"] is False
    assert "electronic_energy_hartree" not in output
    assert not any(q.name == "electronic_energy" for q in native[0].quantities)
    assert len(native[0].metadata["native_result"]["metadata"]["native_result"]["native_core_sha256"]) == 64
    store = RunStore(workflow.output_root / record.run_id)

    def do_not_recompute(*args, **kwargs):
        pytest.fail("Verified completed native result must be reused, not recalculated")

    monkeypatch.setattr("topos.external_matrix_workflow.run_external", do_not_recompute)
    assert execute_external_recipe(workflow, record, store, MatrixInputs(external_protocol=sapt()), time.monotonic() + 20, None)
    assert [a.attempt_id for a in record.attempts if a.metadata.get("role") == "matrix-native-component"] == [native[0].attempt_id]
