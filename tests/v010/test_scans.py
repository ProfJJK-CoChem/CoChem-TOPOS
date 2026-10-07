"""Constrained-coordinate mathematics and genuine engine-backed relaxed scans."""
from __future__ import annotations

import copy
import os
import shutil
from threading import Event

import h5py
import numpy as np
import pytest

from topos.config import SystemConfig
from topos.method_matrix import MATRIX_REVISION
from topos.models import MethodSpec, Molecule, ResourceLimits, RunRequest
from topos.scans import (
    ScanCoordinate,
    ScanOptions,
    constraint_system,
    coordinate_value_jacobian,
    project_scan_geometry,
    projected_stationarity,
    run_relaxed_scan,
)
from topos.science import BOHR_ANGSTROM
from topos.storage import IntegrityError, RunStore
from topos.workflow import Workflow


def water():
    return Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.9572, 0, 0], [-.23999, .9273, 0]])


def distance(values=None):
    return ScanCoordinate(kind="distance", atoms=[0, 1], units="angstrom", values=values or [.92, .98, 1.04])


def method():
    return MethodSpec(engine="xtb", method="GFN2-xTB", purpose="gradient", profile_id="xtb-vtight-v1", engine_version="6.7.1")


def config():
    for choice in [os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"), "/workspace/.tools/xtb-dist/bin/xtb"]:
        if shutil.which(choice):
            return SystemConfig(execution_backend="development", executables={"xtb": shutil.which(choice)})
    pytest.skip("Real xTB is required; a gradient is never simulated")


@pytest.mark.parametrize("kind,atoms", [("distance", [0, 1]), ("angle", [0, 1, 2]), ("dihedral", [0, 1, 2, 3])])
def test_analytic_coordinate_jacobians_agree_with_independent_finite_differences(kind, atoms):
    xyz = np.asarray([[.2, 1., .1], [0., 0., 0.], [1.2, .1, .2], [1., 1., 1.]])
    coordinate = ScanCoordinate(kind=kind, atoms=atoms, units="angstrom" if kind == "distance" else "degree", values=[1] if kind == "distance" else [45])
    _, jacobian = coordinate_value_jacobian(xyz, coordinate)
    numeric = []
    for index in range(xyz.size):
        increment = np.zeros(xyz.size)
        increment[index] = 1e-6
        high = coordinate_value_jacobian(xyz + increment.reshape(xyz.shape), coordinate)[0]
        low = coordinate_value_jacobian(xyz - increment.reshape(xyz.shape), coordinate)[0]
        delta = high - low
        if kind == "dihedral":
            delta = np.arctan2(np.sin(delta), np.cos(delta))
        numeric.append(delta / 2e-6)
    assert np.max(np.abs(jacobian - numeric)) < 1e-8
    assert np.max(np.abs(jacobian.reshape((-1, 3)).sum(axis=0))) < 1e-12


@pytest.mark.parametrize("payload", [
    dict(kind="distance", atoms=[0, 0], units="angstrom", values=[1]),
    dict(kind="distance", atoms=[0, 1], units="degree", values=[1]),
    dict(kind="distance", atoms=[0, 1], units="angstrom", values=[0]),
    dict(kind="angle", atoms=[0, 1, 2], units="degree", values=[180]),
    dict(kind="dihedral", atoms=[0, 1, 2, 3], units="degree", values=[180]),
    dict(kind="distance", atoms=[0, 1], units="angstrom", values=[1, 1]),
    dict(kind="distance", atoms=[0, 1], units="angstrom", values=[float("nan")]),
])
def test_invalid_coordinate_domains_and_ambiguous_units_fail(payload):
    with pytest.raises(ValueError):
        ScanCoordinate(**payload)


def test_two_coordinate_projection_preserves_exact_distance_and_angle_equalities():
    coordinates = [distance([1.05]), ScanCoordinate(kind="angle", atoms=[1, 0, 2], units="degree", values=[110])]
    projected = project_scan_geometry(np.asarray(water().coordinates) / BOHR_ANGSTROM, coordinates, (1.05, 110))
    residual, jacobian = constraint_system(projected, coordinates, (1.05, 110))
    assert max(abs(residual)) < 1e-9
    # A pure normal gradient is a constraint force, not a failure of free relaxation.
    normal = jacobian.T @ [0.1, -0.2]
    report = projected_stationarity(normal, jacobian)
    assert report["max_projected_gradient_hartree_per_bohr"] < 1e-12
    tangent = np.arange(9, dtype=float)
    tangent -= jacobian.T @ np.linalg.solve(jacobian @ jacobian.T, jacobian @ tangent)
    assert projected_stationarity(tangent, jacobian)["max_projected_gradient_hartree_per_bohr"] > 0.1


def test_dihedral_wrap_uses_short_physical_angular_difference():
    coordinate = ScanCoordinate(kind="dihedral", atoms=[0, 1, 2, 3], units="degree", values=[-179])
    # Projection crosses the periodic seam without attempting a 358-degree jump.
    xyz = np.asarray([[0., 1., 0.], [0., 0., 0.], [1., 0., 0.], [1., -1., .02]])
    projected = project_scan_geometry(xyz, [coordinate], (-179,))
    residual, _ = constraint_system(projected, [coordinate], (-179,))
    assert abs(residual[0]) < 1e-9
    assert np.linalg.norm(projected - xyz) < .1


def test_redundant_or_singular_coordinates_cannot_claim_an_independent_scan():
    xyz = np.asarray(water().coordinates) / BOHR_ANGSTROM
    with pytest.raises(ValueError, match="redundant"):
        constraint_system(xyz, [distance(), distance()], (.98, .98))
    collinear = np.asarray([[0., 0., 0.], [1., 0., 0.], [2., 0., 0.]])
    angle = ScanCoordinate(kind="angle", atoms=[0, 1, 2], units="degree", values=[100])
    with pytest.raises(ValueError, match="singular"):
        coordinate_value_jacobian(collinear, angle)


def test_cancelled_before_scan_does_not_spawn_an_engine(tmp_path):
    event = Event()
    event.set()
    result = run_relaxed_scan(water(), method(), ResourceLimits(budget_seconds=10), [distance()], tmp_path,
                              config=SystemConfig(execution_backend="development", executables={"xtb": "/missing/xtb"}), cancel_event=event)
    assert result["status"] == "cancelled"
    assert not result["points"] and not result["evaluations"]


def test_missing_engine_cannot_return_a_surface_energy(tmp_path):
    result = run_relaxed_scan(water(), method(), ResourceLimits(budget_seconds=10), [distance()], tmp_path,
                              config=SystemConfig(execution_backend="development", executables={"xtb": "/missing/xtb"}))
    assert result["status"] == "unavailable"
    assert not result["points"]


@pytest.mark.integration
def test_real_water_bond_scan_shape_constraints_stationarity_and_resume(tmp_path):
    installed = config()
    result = run_relaxed_scan(water(), method(), ResourceLimits(budget_seconds=90), [distance()], tmp_path,
                              config=installed)
    assert result["status"] == "completed", result.get("reason")
    assert len(result["points"]) == 6
    assert result["engine_identity"]["engine_version"] == "6.7.1"
    assert result["engine_identity"]["executable_sha256"]
    assert not result["minimum_or_transition_state_claim"]
    for direction in ("forward", "reverse"):
        points = sorted([p for p in result["points"] if p["direction"] == direction], key=lambda p: p["targets"])
        assert points[1]["energy_hartree"] < min(points[0]["energy_hartree"], points[2]["energy_hartree"])
        for point in points:
            xyz = np.asarray(point["molecule"]["coordinates"])
            assert np.linalg.norm(xyz[0] - xyz[1]) == pytest.approx(point["targets"][0], abs=1e-7)
            assert point["diagnostics"]["max_projected_gradient_hartree_per_bohr"] <= 1e-5
            assert point["diagnostics"]["rms_projected_gradient_hartree_per_bohr"] <= 3e-6
    assert result["max_absolute_hysteresis_hartree"] < 1e-7
    with h5py.File(tmp_path / result["surface_artifact"]["path"]) as surface:
        assert surface.attrs["schema_version"] == "topos-relaxed-scan-surface/1"
        assert np.array_equal(surface["electronic_energy_hartree"][:], [p["energy_hartree"] for p in result["points"]])
        assert np.array_equal(surface["coordinates_angstrom"][:], [p["molecule"]["coordinates"] for p in result["points"]])
        assert surface["electronic_energy_hartree"].attrs["units"] == "hartree"
        assert surface["coordinates_angstrom"].fletcher32
    count = len(result["evaluations"])
    installed.executables["xtb"] = "/missing/no-reexecution-possible"
    resumed = run_relaxed_scan(water(), method(), ResourceLimits(budget_seconds=90), [distance()], tmp_path, config=installed)
    assert resumed["status"] == "completed"
    assert len(resumed["evaluations"]) == count
    assert resumed["points"] == result["points"]
    changed = method().model_copy(update={"profile_id": "screening-v1"})
    with pytest.raises(IntegrityError, match="protocol"):
        run_relaxed_scan(water(), changed, ResourceLimits(budget_seconds=90), [distance()], tmp_path, config=installed)


@pytest.mark.integration
def test_matrix_scan_routes_actual_gradients_and_preserves_slice_points_without_dedup(tmp_path):
    workflow = Workflow(tmp_path, config=config())
    request = RunRequest(molecule=water(), purpose="matrix", matrix_row_id="T2-10s", matrix_revision=MATRIX_REVISION,
                         budget_seconds=90, matrix_inputs={"scan_coordinates": [distance([.96]).model_dump()]})
    result = workflow.run(request)
    assert result.status == "completed", result.metadata.get("termination_reason")
    assert result.metadata["matrix_scan"]["completed_points"] == 2
    assert result.metadata["matrix_execution"]["full_row_completed"]
    assert len(result.candidates) == 2
    assert all(c.status == "scan-point" for c in result.candidates)
    assert all(a.metadata["execution_kind"] == "real" for a in result.attempts)
    assert any(a.metadata.get("result_kind") == "derived-constrained-scan" for a in result.attempts)
    assert any(a.role == "relaxed-scan-result" for a in result.artifacts)
    assert result.metadata["matrix_scan"]["surface_hdf5"].endswith(".h5")
    assert all(a.artifacts and a.metadata["accepted_gradient_attempt_id"]
               for a in result.attempts if a.metadata.get("result_kind") == "derived-constrained-scan")
    assert RunStore(tmp_path / result.run_id).verify()


@pytest.mark.integration
def test_per_point_deadline_stops_real_gradient_dispatch_and_retains_evidence(tmp_path):
    result = run_relaxed_scan(water(), method(), ResourceLimits(budget_seconds=30), [distance()], tmp_path,
                              config=config(), options=ScanOptions(per_point_budget_seconds=.001))
    assert result["status"] == "timed-out"
    assert not result["points"]
    assert "deadline" in result["reason"] or "gradient" in result["reason"].lower()


@pytest.mark.integration
def test_completed_scan_point_tampering_is_detected(tmp_path):
    import json

    result = run_relaxed_scan(water(), method(), ResourceLimits(budget_seconds=90), [distance([.96])], tmp_path, config=config())
    assert result["status"] == "completed"
    changed = copy.deepcopy(result)
    changed["points"][0]["energy_hartree"] += 1.0
    (tmp_path / "scan-state.json").write_text(json.dumps(changed))
    with pytest.raises(IntegrityError, match="payload changed"):
        run_relaxed_scan(water(), method(), ResourceLimits(budget_seconds=90), [distance([.96])], tmp_path, config=config())
