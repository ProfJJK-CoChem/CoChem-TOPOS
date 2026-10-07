"""Finite relaxed distance/angle/dihedral grids with real engine gradients.

SLSQP minimizes electronic energy subject to explicit coordinate equalities. The
scientific acceptance check projects the actual engine gradient into the tangent
space of those equalities; optimizer termination alone is insufficient. Both
scan directions are retained to expose hysteresis. No transition state, global
minimum, or variational spectrum is inferred from this finite surface slice.
"""
from __future__ import annotations

import itertools
import json
import math
import os
import time
from pathlib import Path
from threading import Event
from typing import Any, Literal
from uuid import uuid4

import h5py
import numpy as np
from pydantic import Field, model_validator
from scipy.optimize import minimize

from .config import SystemConfig, load_config
from .models import Contract, MethodSpec, Molecule, ResourceLimits, RunRecord, RunRequest
from .science import BOHR_ANGSTROM, geometry_digest
from .storage import (
    IntegrityError,
    RunStore,
    atomic_json,
    digest_json,
    file_digest,
    fsync_directory,
)


class ScanCoordinate(Contract):
    kind: Literal["distance", "angle", "dihedral"]
    atoms: list[int] = Field(min_length=2, max_length=4)
    units: Literal["angstrom", "degree"]
    values: list[float] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def validate_coordinate(self) -> ScanCoordinate:
        count = {"distance": 2, "angle": 3, "dihedral": 4}[self.kind]
        if len(self.atoms) != count or min(self.atoms) < 0 or len(set(self.atoms)) != count:
            raise ValueError("Scan coordinate atom indices must be distinct, nonnegative and match its kind")
        if self.units != ("angstrom" if self.kind == "distance" else "degree"):
            raise ValueError("Distances use angstrom; angles and dihedrals use degree")
        if len(set(self.values)) != len(self.values):
            raise ValueError("Scan values must be distinct")
        if self.kind == "distance" and min(self.values) <= 0:
            raise ValueError("Distance targets must be positive")
        if self.kind == "angle" and any(not 0 < value < 180 for value in self.values):
            raise ValueError("Bond-angle targets must be strictly between 0 and 180 degrees")
        if self.kind == "dihedral" and any(not -180 <= value < 180 for value in self.values):
            raise ValueError("Dihedrals use the unique interval [-180, 180) degrees")
        return self

    def native(self, target: float) -> float:
        return target / BOHR_ANGSTROM if self.kind == "distance" else math.radians(target)


class ScanOptions(Contract):
    profile_id: Literal["matrix-relaxed-scan-v1"] = "matrix-relaxed-scan-v1"
    max_iterations: int = Field(default=200, ge=1, le=2000)
    max_grid_points: int = Field(default=10000, ge=1, le=10000)
    constraint_tolerance_native: float = Field(default=1e-7, gt=0, le=1e-5)
    max_projected_gradient_hartree_per_bohr: float = Field(default=1e-5, gt=0, le=1e-5)
    rms_projected_gradient_hartree_per_bohr: float = Field(default=3e-6, gt=0, le=3e-6)
    # Numerical optimizer stopping tolerance; separate from the chemical acceptance check.
    optimizer_ftol_hartree: float = Field(default=1e-12, gt=0, le=1e-7)
    both_directions: Literal[True] = True
    per_point_budget_seconds: float | None = Field(default=None, gt=0)


def coordinate_value_jacobian(xyz_bohr: np.ndarray, coordinate: ScanCoordinate) -> tuple[float, np.ndarray]:
    """Coordinate value and analytic Cartesian Jacobian (bohr, radians)."""
    xyz = np.asarray(xyz_bohr, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all():
        raise ValueError("Coordinates must be finite N×3 Cartesian data")
    if max(coordinate.atoms) >= len(xyz):
        raise ValueError("Scan coordinate references a nonexistent atom")
    jac = np.zeros_like(xyz)
    points = xyz[coordinate.atoms]
    if coordinate.kind == "distance":
        vector = points[0] - points[1]
        distance = float(np.linalg.norm(vector))
        if distance < 1e-10:
            raise ValueError("A zero-length distance has no coordinate Jacobian")
        jac[coordinate.atoms[0]] = vector / distance
        jac[coordinate.atoms[1]] = -vector / distance
        return distance, jac.ravel()
    if coordinate.kind == "angle":
        u, v = points[0] - points[1], points[2] - points[1]
        nu, nv = np.linalg.norm(u), np.linalg.norm(v)
        if min(nu, nv) < 1e-10:
            raise ValueError("A bond angle requires nonzero bonds")
        cosine = float(np.clip(np.dot(u, v) / (nu * nv), -1.0, 1.0))
        sine = math.sqrt(max(0.0, 1 - cosine * cosine))
        if sine < 1e-8:
            raise ValueError("A collinear bond angle has a singular Cartesian Jacobian")
        ga = (cosine * u / (nu * nu) - v / (nu * nv)) / sine
        gc = (cosine * v / (nv * nv) - u / (nu * nv)) / sine
        jac[coordinate.atoms[0]], jac[coordinate.atoms[2]] = ga, gc
        jac[coordinate.atoms[1]] = -ga - gc
        return math.acos(cosine), jac.ravel()
    b1, b2, b3 = points[1] - points[0], points[2] - points[1], points[3] - points[2]
    length = float(np.linalg.norm(b2))
    c1, c2 = np.cross(b1, b2), np.cross(b2, b3)
    if length < 1e-10 or min(np.linalg.norm(c1), np.linalg.norm(c2)) < 1e-10:
        raise ValueError("A dihedral requires a nonzero central bond and two noncollinear planes")
    d12, d23, d13 = np.dot(b1, b2), np.dot(b2, b3), np.dot(b1, b3)
    triple = float(np.dot(b1, c2))
    x, y = float(np.dot(c1, c2)), length * triple
    denominator = x * x + y * y
    dx = (b2 * d23 - b3 * length**2,
          b1 * d23 + b3 * d12 - 2 * b2 * d13,
          b2 * d12 - b1 * length**2)
    dy = (length * c2, b2 / length * triple + length * np.cross(b3, b1), length * c1)
    gradients = [(x * iy - y * ix) / denominator for ix, iy in zip(dx, dy, strict=True)]
    jac[coordinate.atoms[0]] = -gradients[0]
    jac[coordinate.atoms[1]] = gradients[0] - gradients[1]
    jac[coordinate.atoms[2]] = gradients[1] - gradients[2]
    jac[coordinate.atoms[3]] = gradients[2]
    return math.atan2(y, x), jac.ravel()


def constraint_system(xyz_bohr: np.ndarray, coordinates: list[ScanCoordinate],
                      targets: tuple[float, ...]) -> tuple[np.ndarray, np.ndarray]:
    if len(coordinates) != len(targets):
        raise ValueError("Every scan coordinate requires one target")
    residuals, rows = [], []
    for coordinate, target in zip(coordinates, targets, strict=True):
        value, jacobian = coordinate_value_jacobian(xyz_bohr, coordinate)
        delta = value - coordinate.native(target)
        if coordinate.kind == "dihedral":
            delta = math.atan2(math.sin(delta), math.cos(delta))
        residuals.append(delta)
        rows.append(jacobian)
    jacobian = np.asarray(rows)
    singular = np.linalg.svd(jacobian, compute_uv=False)
    if not len(singular) or singular[-1] <= 1e-10 * max(1.0, singular[0]):
        raise ValueError("Scan coordinates are redundant or locally singular")
    return np.asarray(residuals), jacobian


def project_scan_geometry(xyz_bohr: np.ndarray, coordinates: list[ScanCoordinate],
                          targets: tuple[float, ...], *, tolerance: float = 1e-9) -> np.ndarray:
    """Minimum-displacement Newton projection onto the specified equalities."""
    xyz = np.array(xyz_bohr, dtype=float, copy=True)
    for _ in range(100):
        residual, jacobian = constraint_system(xyz, coordinates, targets)
        if np.max(np.abs(residual)) <= tolerance:
            return xyz
        displacement = -jacobian.T @ np.linalg.solve(jacobian @ jacobian.T, residual)
        # Bound the geometric proposal, not an engine force or its convergence tolerance.
        scale = min(1.0, 0.5 / max(float(np.linalg.norm(displacement)), 1e-15))
        xyz += (scale * displacement).reshape(xyz.shape)
    raise ValueError("Could not construct a feasible geometry for the requested scan constraints")


def projected_stationarity(gradient: np.ndarray, jacobian: np.ndarray) -> dict[str, Any]:
    vector = np.asarray(gradient, dtype=np.float64).ravel()
    if len(vector) != jacobian.shape[1] or not np.isfinite(vector).all():
        raise ValueError("Gradient must match the finite Cartesian constraint space")
    multipliers = np.linalg.solve(jacobian @ jacobian.T, jacobian @ vector)
    free = vector - jacobian.T @ multipliers
    degrees = len(vector) - len(jacobian)
    if degrees <= 0:
        raise ValueError("Scan constraints leave no free Cartesian directions")
    return {"projected_gradient_hartree_per_bohr": free.reshape((-1, 3)).tolist(),
            "max_projected_gradient_hartree_per_bohr": float(np.max(np.abs(free))),
            "rms_projected_gradient_hartree_per_bohr": float(np.linalg.norm(free) / math.sqrt(degrees)),
            "constraint_gradient_components": multipliers.tolist(), "constraint_rank": len(jacobian),
            "free_cartesian_rank": degrees}


def _surface_artifact(folder: Path, state: dict[str, Any], molecule: Molecule,
                      coordinates: list[ScanCoordinate]) -> dict[str, Any]:
    """Publish an immutable, lossless numerical surface separate from conformer membership."""
    points = state["points"]
    name = "surface-" + uuid4().hex + ".h5"
    target = folder / name
    staging = folder / (".pending-" + name)
    try:
        with h5py.File(staging, "w") as handle:
            handle.attrs.update(schema_version="topos-relaxed-scan-surface/1",
                                protocol_sha256=state["protocol_sha256"],
                                scientific_scope="constrained electronic-energy slice; not an ensemble of free minima",
                                scan_coordinates_json=json.dumps([c.model_dump(mode="json") for c in coordinates]))
            arrays = {
                "targets": (np.asarray([p["targets"] for p in points], dtype="f8").reshape((-1, len(coordinates))), "per-coordinate units in scan_coordinates_json"),
                "electronic_energy_hartree": (np.asarray([p["energy_hartree"] for p in points], dtype="f8"), "hartree"),
                "coordinates_angstrom": (np.asarray([p["molecule"]["coordinates"] for p in points], dtype="f8").reshape((-1, len(molecule.symbols), 3)), "angstrom"),
                "max_projected_gradient": (np.asarray([p["diagnostics"]["max_projected_gradient_hartree_per_bohr"] for p in points], dtype="f8"), "hartree/bohr"),
            }
            for key, (values, units) in arrays.items():
                dataset = handle.create_dataset(key, data=values, compression="gzip", shuffle=True, fletcher32=True)
                dataset.attrs["units"] = units
            string_type = h5py.string_dtype("utf-8")
            handle.create_dataset("direction", data=[p["direction"] for p in points], dtype=string_type)
            handle.create_dataset("point_sha256", data=[p["point_sha256"] for p in points], dtype=string_type)
            handle.create_dataset("symbols", data=molecule.symbols, dtype=string_type)
            handle.flush()
        with staging.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(staging, target)
        fsync_directory(folder)
    finally:
        staging.unlink(missing_ok=True)
    return {"path": name, "sha256": file_digest(target), "size_bytes": target.stat().st_size,
            "role": "relaxed-scan-surface", "media_type": "application/x-hdf5"}


class _ScanStopped(RuntimeError):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status


def run_relaxed_scan(molecule: Molecule, method: MethodSpec, resources: ResourceLimits,
                     coordinates: list[ScanCoordinate], workdir: Path | str, *,
                     config: SystemConfig | None = None, options: ScanOptions | None = None,
                     cancel_event: Event | None = None) -> dict[str, Any]:
    """Run/recover a finite grid using ordinary real-gradient child Workflows.

    Every completed child and scan point is durable. Resume verifies hashes and
    scientific protocol compatibility before reusing it. A failed/timed-out point
    contributes no completed surface energy.
    """
    from .workflow import Workflow

    options = options or ScanOptions()
    config = config or load_config()
    coordinates = [ScanCoordinate.model_validate(c.model_dump() if isinstance(c, ScanCoordinate) else c) for c in coordinates]
    if not 1 <= len(coordinates) <= 2:
        raise ValueError("This relaxed-scan adapter supports one or two explicit coordinates")
    if math.prod(len(coordinate.values) for coordinate in coordinates) > options.max_grid_points:
        raise ValueError("The explicit scan grid exceeds its finite point limit")
    grid = list(itertools.product(*(coordinate.values for coordinate in coordinates)))
    if method.constraints:
        raise ValueError("Combining frozen-monomer and scanned internal-coordinate constraints requires a separate registered protocol")
    if resources.device != "cpu" or method.engine not in {"xtb", "orca"}:
        raise ValueError("The registered scan gradient adapters require CPU xTB or ORCA")
    # Validate all indices, coordinate independence and the initial domain before launching.
    initial = np.asarray(molecule.coordinates) / BOHR_ANGSTROM
    constraint_system(initial, coordinates, grid[0])
    folder = Path(workdir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    protocol = {"schema_version": "topos-relaxed-scan/1", "molecule": molecule.model_dump(mode="json"),
                "method": method.model_dump(mode="json"),
                "resources": resources.model_dump(mode="json", exclude={"budget_seconds"}),
                "coordinates": [c.model_dump(mode="json") for c in coordinates], "options": options.model_dump(mode="json"),
                "execution_backend": config.execution_backend}
    protocol_sha = digest_json(protocol)
    protocol_path = folder / "scan-protocol.json"
    if protocol_path.exists():
        if json.loads(protocol_path.read_text()) != protocol:
            raise IntegrityError("Relaxed-scan resume protocol differs from its immutable input")
    elif any(folder.iterdir()):
        raise IntegrityError("Scan directory contains output without a verified protocol")
    else:
        atomic_json(protocol_path, protocol)
    state_path = folder / "scan-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "schema_version": "topos-relaxed-scan/1", "protocol_sha256": protocol_sha,
        "status": "running", "points": [], "evaluations": [], "failures": [],
        "engine_identity": None, "hysteresis": [], "grid_points_per_direction": len(grid),
        "directions": ["forward", "reverse"], "minimum_or_transition_state_claim": False,
        "scope": "finite constrained electronic-energy slice; no exhaustive PES, minimum or transition-state certification",
    }
    if state["protocol_sha256"] != protocol_sha:
        raise IntegrityError("Scan state and protocol identity differ")
    workflow = Workflow(folder / "gradient-runs", config=config)
    started = time.monotonic()
    deadline = started + resources.budget_seconds
    point_deadline = deadline
    observations: dict[str, tuple[float, np.ndarray, dict[str, Any]]] = {}

    def check_stop() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise _ScanStopped("cancelled", "Relaxed scan cancelled; completed points remain reusable")
        if time.monotonic() >= min(deadline, point_deadline):
            raise _ScanStopped("timed-out", "Relaxed-scan workflow or per-point deadline reached; completed points remain reusable")

    def load_observation(entry: dict[str, Any]) -> tuple[float, np.ndarray, dict[str, Any]]:
        child_dir = folder / entry["run_path"]
        if not child_dir.resolve().is_relative_to((folder / "gradient-runs").resolve()):
            raise IntegrityError("Scan gradient evidence escapes the recorded directory")
        child = RunRecord.model_validate(RunStore(child_dir).recover())
        if digest_json(child.model_dump(mode="json")) != entry["record_sha256"]:
            raise IntegrityError("Scan gradient evidence changed after completion")
        if geometry_digest(child.request.molecule) != entry["geometry_sha256"]:
            raise IntegrityError("Scan gradient belongs to a different geometry")
        if child.request.method_spec.model_dump(mode="json") != method.model_copy(update={"purpose": "gradient"}).model_dump(mode="json"):
            raise IntegrityError("Scan gradient scientific method differs from the scan protocol")
        valid = [a for a in child.attempts if a.status == "completed" and a.validation_status == "validated-for-protocol"
                 and a.metadata.get("execution_kind") == "real"]
        if child.status != "completed" or len(valid) != 1:
            raise IntegrityError("Scan gradient lacks one verified real engine evaluation")
        attempt = valid[0]
        identity = {"engine": attempt.engine, "method": attempt.method,
                    "engine_version": attempt.engine_version, "executable_sha256": attempt.metadata.get("executable_sha256")}
        if not identity["engine_version"] or not identity["executable_sha256"]:
            raise IntegrityError("Scan engine identity is incomplete")
        if state["engine_identity"] is not None and identity != state["engine_identity"]:
            raise IntegrityError("Scan points cannot mix different engine binaries or methods")
        state["engine_identity"] = identity
        energies = [q.value for q in attempt.quantities if q.name == "electronic_energy" and q.units == "hartree"]
        gradients = [q.value for q in attempt.quantities if q.name == "cartesian_gradient" and q.units == "hartree/bohr"]
        if len(energies) != 1 or len(gradients) != 1:
            raise IntegrityError("Gradient evidence does not contain one energy and Cartesian gradient")
        return float(energies[0]), np.asarray(gradients[0], dtype=float), entry

    for entry in state["evaluations"]:
        if entry["status"] == "completed":
            observations[entry["geometry_sha256"]] = load_observation(entry)
    for point in state["points"]:
        if point["status"] != "completed" or point["geometry_sha256"] not in observations:
            raise IntegrityError("A completed scan point has no verified matching gradient")
        if digest_json({k: v for k, v in point.items() if k != "point_sha256"}) != point["point_sha256"]:
            raise IntegrityError("Completed scan point payload changed")
        output = Molecule.model_validate(point["molecule"])
        energy, gradient, _ = observations[point["geometry_sha256"]]
        if geometry_digest(output) != point["geometry_sha256"] or point["energy_hartree"] != energy:
            raise IntegrityError("Scan point geometry/energy does not match its actual gradient evidence")
        if tuple(point["targets"]) not in grid or point["direction"] not in {"forward", "reverse"}:
            raise IntegrityError("Scan point lies outside the registered grid")
        residual, jac = constraint_system(np.asarray(output.coordinates) / BOHR_ANGSTROM, coordinates, tuple(point["targets"]))
        actual_stationarity = projected_stationarity(gradient, jac)
        if (max(abs(residual)) > options.constraint_tolerance_native
                or actual_stationarity["max_projected_gradient_hartree_per_bohr"] > options.max_projected_gradient_hartree_per_bohr
                or actual_stationarity["rms_projected_gradient_hartree_per_bohr"] > options.rms_projected_gradient_hartree_per_bohr):
            raise IntegrityError("Saved scan point fails its actual geometric or stationary-point checks")
    state["status"] = "running"
    atomic_json(state_path, state)

    def evaluate(x: np.ndarray) -> tuple[float, np.ndarray, dict[str, Any]]:
        check_stop()
        geometry = Molecule.model_validate({**molecule.model_dump(), "coordinates": (x.reshape((-1, 3)) * BOHR_ANGSTROM).tolist()})
        identifier = geometry_digest(geometry)
        if identifier in observations:
            return observations[identifier]
        data = dict(molecule=geometry, engine=method.engine, method=method.method,
                    engine_version=method.engine_version, purpose="gradient", basis=method.basis,
                    auxiliary_basis=method.auxiliary_basis, dispersion=method.dispersion,
                    solvent=method.solvent, profile_id=method.profile_id, **resources.model_dump())
        data["budget_seconds"] = max(1e-9, min(deadline, point_deadline) - time.monotonic())
        child = workflow.run(RunRequest(**data), cancel_event=cancel_event)
        entry = {"run_id": child.run_id, "run_path": (workflow.output_root / child.run_id).relative_to(folder).as_posix(),
                 "record_sha256": digest_json(child.model_dump(mode="json")), "geometry_sha256": identifier,
                 "status": child.status}
        state["evaluations"].append(entry)
        atomic_json(state_path, state)
        if child.status != "completed":
            raise _ScanStopped(child.status, "Real gradient evaluation did not complete: " + str(child.metadata.get("termination_reason", child.status)))
        observation = load_observation(entry)
        observations[identifier] = observation
        return observation

    try:
        for direction, points in (("forward", grid), ("reverse", list(reversed(grid)))):
            seed = np.array(initial, copy=True)
            for targets in points:
                point_deadline = deadline
                check_stop()
                completed = next((p for p in state["points"] if p["direction"] == direction and p["targets"] == list(targets)), None)
                if completed:
                    seed = np.asarray(completed["molecule"]["coordinates"]) / BOHR_ANGSTROM
                    continue
                if options.per_point_budget_seconds is not None:
                    point_deadline = min(deadline, time.monotonic() + options.per_point_budget_seconds)
                seed = project_scan_geometry(seed, coordinates, targets)
                previous_evaluations = len(state["evaluations"])

                def objective(x: np.ndarray) -> tuple[float, np.ndarray]:
                    energy, gradient, _ = evaluate(x)
                    return energy, gradient.ravel()

                def equality(x: np.ndarray, targets: tuple[float, ...] = targets) -> np.ndarray:
                    return constraint_system(x.reshape((-1, 3)), coordinates, targets)[0]

                def jacobian(x: np.ndarray, targets: tuple[float, ...] = targets) -> np.ndarray:
                    return constraint_system(x.reshape((-1, 3)), coordinates, targets)[1]

                minimized = minimize(objective, seed.ravel(), jac=True, method="SLSQP",
                                     constraints={"type": "eq", "fun": equality, "jac": jacobian},
                                     options={"maxiter": options.max_iterations, "ftol": options.optimizer_ftol_hartree})
                final = minimized.x.reshape((-1, 3))
                energy, gradient, evidence = evaluate(minimized.x)
                residual, jac = constraint_system(final, coordinates, targets)
                stationary = projected_stationarity(gradient, jac)
                valid = bool(minimized.success and max(abs(residual)) <= options.constraint_tolerance_native
                             and stationary["max_projected_gradient_hartree_per_bohr"] <= options.max_projected_gradient_hartree_per_bohr
                             and stationary["rms_projected_gradient_hartree_per_bohr"] <= options.rms_projected_gradient_hartree_per_bohr)
                diagnostics = {"optimizer": "scipy.optimize.SLSQP", "optimizer_success": bool(minimized.success),
                               "optimizer_message": str(minimized.message), "iterations": int(minimized.nit),
                               "constraint_residual_native": residual.tolist(), **stationary,
                               "stationarity_definition": "actual electronic gradient projected tangent to the scanned equalities; no unconstrained-minimum claim"}
                if not valid:
                    state["failures"].append({"direction": direction, "targets": list(targets), "diagnostics": diagnostics})
                    raise _ScanStopped("failed", "Scan point failed optimizer, target-drift or free-subspace gradient acceptance")
                output = Molecule.model_validate({**molecule.model_dump(), "coordinates": (final * BOHR_ANGSTROM).tolist()})
                point = {"direction": direction, "targets": list(targets), "status": "completed",
                         "energy_hartree": energy, "molecule": output.model_dump(mode="json"),
                         "geometry_sha256": geometry_digest(output), "diagnostics": diagnostics,
                         "gradient_evidence": evidence,
                         "new_gradient_evaluations": len(state["evaluations"]) - previous_evaluations}
                point["point_sha256"] = digest_json(point)
                state["points"].append(point)
                seed = final
                atomic_json(state_path, state)
        state["hysteresis"] = []
        for targets in grid:
            pair = [p for p in state["points"] if p["targets"] == list(targets)]
            state["hysteresis"].append({"targets": list(targets),
                                        "forward_minus_reverse_hartree": next(p["energy_hartree"] for p in pair if p["direction"] == "forward") - next(p["energy_hartree"] for p in pair if p["direction"] == "reverse")})
        state["max_absolute_hysteresis_hartree"] = max(abs(p["forward_minus_reverse_hartree"]) for p in state["hysteresis"])
        state["status"] = "completed"
        state.pop("reason", None)
    except _ScanStopped as exc:
        state["status"], state["reason"] = exc.status, str(exc)
    except (ValueError, np.linalg.LinAlgError) as exc:
        state["status"], state["reason"] = "failed", str(exc)
    state["surface_artifact"] = _surface_artifact(folder, state, molecule, coordinates)
    state["invocation_seconds"] = time.monotonic() - started
    atomic_json(state_path, state)
    return state
