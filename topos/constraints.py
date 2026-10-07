"""Rigid-monomer geometry operations with explicit convergence evidence.

This module supplies coordinates and numerical optimization only. It never
substitutes an electronic-structure method. A callback must return an authentic
energy in Eh and its Cartesian derivative in Eh/bohr. The optimizer uses a
limited-memory inverse-Hessian approximation, not a frequency Hessian.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from scipy.constants import physical_constants
from scipy.spatial.distance import pdist
from scipy.spatial.transform import Rotation

from .models import Molecule

BOHR_ANGSTROM = physical_constants["Bohr radius"][0] / 1e-10


class ConstraintError(ValueError):
    """An unsupported or inconsistent constraint was requested."""


class TrajectoryDriftViolationError(ConstraintError):
    """A proposed rigid transformation changed an internal distance."""


class EnergyGradientError(RuntimeError):
    """The energy/gradient provider did not supply a valid evaluation."""


@dataclass(frozen=True)
class ConvergenceProfile:
    """Named thresholds; displacement and gradient use atomic units."""

    profile_id: str
    energy_hartree: float
    max_gradient_hartree_per_bohr: float
    rms_gradient_hartree_per_bohr: float
    rms_displacement_bohr: float
    max_displacement_bohr: float
    max_iterations: int
    rigidity_angstrom: float
    strain_warning_hartree_per_bohr: float = 1e-4

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ConstraintError("a convergence profile must have a provenance identifier")
        for key, value in asdict(self).items():
            if key == "profile_id":
                continue
            if not math.isfinite(value) or value <= 0:
                raise ConstraintError(f"{key} must be finite and positive")
        if not isinstance(self.max_iterations, int):
            raise ConstraintError("max_iterations must be an integer")


PROFILES = {
    "mapping-2026": ConvergenceProfile(
        "mapping-2026", 1e-7, 1e-5, 3e-6, 5e-5, 1e-4, 200, 1e-6
    ),
    "chunk3-2026": ConvergenceProfile(
        "chunk3-2026", 1e-6, 1e-5, 5e-6, 5e-5, 1e-4, 150, 1e-8
    ),
}


@dataclass
class ConstrainedResult:
    molecule: Molecule
    energy_hartree: float | None
    gradient_hartree_per_bohr: list[list[float]] | None
    converged: bool
    status: str
    diagnostics: dict[str, Any]
    evaluations: list[dict[str, Any]] = field(default_factory=list)


def resolve_profile(
    profile: str | ConvergenceProfile | dict[str, Any] | None,
) -> ConvergenceProfile:
    if isinstance(profile, dict):
        try:
            profile = ConvergenceProfile(**profile)
        except (TypeError, ValueError) as exc:
            raise ConstraintError(f"invalid custom convergence profile: {exc}") from exc
    if isinstance(profile, ConvergenceProfile):
        if profile.profile_id in PROFILES and profile != PROFILES[profile.profile_id]:
            raise ConstraintError("a modified profile must use a new identifier; named source thresholds are immutable")
        return profile
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ConstraintError(
            "select an explicit frozen-monomer convergence profile: "
            "mapping-2026 or chunk3-2026; their source tolerances conflict"
        )
    return PROFILES[profile]


def _groups(molecule: Molecule) -> list[list[int]]:
    if not molecule.fragments:
        raise ConstraintError("frozen monomers require an explicit complete fragment partition")
    groups = molecule.fragments
    flattened = [i for group in groups for i in group]
    if any(not group for group in groups) or sorted(flattened) != list(range(len(molecule.symbols))):
        raise ConstraintError("fragments must partition each atom exactly once")
    membership = {atom: f for f, group in enumerate(groups) for atom in group}
    if any(
        bond.kind == "covalent" and membership[bond.atom1] != membership[bond.atom2]
        for bond in molecule.bonds
    ):
        raise ConstraintError("a frozen-monomer boundary crosses a declared covalent bond")
    return groups


def _orthonormal(columns: np.ndarray) -> np.ndarray:
    if not columns.size:
        return np.zeros((columns.shape[0], 0))
    left, values, _ = np.linalg.svd(columns, full_matrices=False)
    if not values.size:
        return left[:, :0]
    threshold = max(columns.shape) * np.finfo(float).eps * max(1.0, values[0]) * 100
    return left[:, values > threshold]


def _rigid_columns(coordinates: np.ndarray) -> np.ndarray:
    """Infinitesimal translations and rotations in Cartesian coordinates."""
    centered = coordinates - coordinates.mean(axis=0)
    columns = [np.tile(axis, (len(coordinates), 1)).ravel() for axis in np.eye(3)]
    columns.extend(np.cross(axis, centered).ravel() for axis in np.eye(3))
    return np.column_stack(columns)


def _bases(
    coordinates: np.ndarray, groups: list[list[int]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[int]]:
    n = len(coordinates)
    fragment_bases = []
    rotation_ranks = []
    for group in groups:
        local = _orthonormal(_rigid_columns(coordinates[group]))
        rotation_ranks.append(local.shape[1] - 3)
        full = np.zeros((3 * n, local.shape[1]))
        rows = [3 * i + j for i in group for j in range(3)]
        full[rows] = local
        fragment_bases.append(full)
    allowed = np.column_stack(fragment_bases)
    global_frame = _orthonormal(_rigid_columns(coordinates))
    # Global motions belong to the fragment-rigid space. Remove exactly their
    # numerical rank, not six hardcoded coordinates and not an entire fragment.
    free = _orthonormal(allowed - global_frame @ (global_frame.T @ allowed))
    return allowed, global_frame, free, rotation_ranks


def constraint_rank(molecule: Molecule) -> dict[str, Any]:
    allowed, global_frame, free, ranks = _bases(np.asarray(molecule.coordinates), _groups(molecule))
    return {
        "fragment_rotation_ranks": ranks,
        "rigid_cartesian_rank": allowed.shape[1],
        "global_frame_rank": global_frame.shape[1],
        "free_rank": free.shape[1],
        "frozen_internal_rank": 3 * len(molecule.symbols) - allowed.shape[1],
    }


def validate_constraints(
    molecule: Molecule,
    constraints: dict[str, Any] | None,
    tolerances: str | ConvergenceProfile | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate before any engine launch and expose the resolved rank/profile."""
    settings = dict(constraints or {})
    allowed_keys = {
        "kind", "profile_id", "reference_source", "reference_uncertainty_angstrom",
        "reference_geometry_id",
    }
    unknown = set(settings) - allowed_keys
    if unknown or settings.get("kind", "frozen-monomers") != "frozen-monomers":
        raise ConstraintError(f"unsupported frozen-monomer constraints: {sorted(unknown) or settings['kind']}")
    profile = resolve_profile(tolerances if tolerances is not None else settings.get("profile_id"))
    if "profile_id" in settings and settings["profile_id"] != profile.profile_id:
        raise ConstraintError("constraint profile and tolerance profile disagree")
    uncertainty = settings.get("reference_uncertainty_angstrom")
    if uncertainty is not None and (
        not isinstance(uncertainty, (int, float)) or not math.isfinite(uncertainty) or uncertainty < 0
    ):
        raise ConstraintError("reference uncertainty must be nonnegative or unknown (null)")
    for key in ("reference_source", "reference_geometry_id"):
        if key in settings and settings[key] is not None and not isinstance(settings[key], str):
            raise ConstraintError(f"{key} must be a string or null")
    return {"profile": asdict(profile), **constraint_rank(molecule)}


def _align(moving: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Proper rotation only; a reflection must never change stereochemistry."""
    a, b = moving.mean(axis=0), reference.mean(axis=0)
    u, _, vt = np.linalg.svd((moving - a).T @ (reference - b))
    proper = np.eye(3)
    proper[-1, -1] = np.linalg.det(u @ vt)
    return (moving - a) @ u @ proper @ vt + b


def _retract(
    current: np.ndarray, target: np.ndarray, groups: list[list[int]], reference: np.ndarray,
) -> np.ndarray:
    candidate = np.empty_like(current)
    for group in groups:
        candidate[group] = _align(current[group], target[group])
    return _align(candidate, reference)


def intrafragment_drift(
    reference_angstrom: np.ndarray | list[list[float]],
    coordinates_angstrom: np.ndarray | list[list[float]],
    fragments: list[list[int]],
) -> float:
    reference, coordinates = np.asarray(reference_angstrom), np.asarray(coordinates_angstrom)
    if reference.shape != coordinates.shape or not np.all(np.isfinite(coordinates)):
        raise ConstraintError("drift evaluation requires matching finite coordinates")
    return max(
        (float(np.max(np.abs(pdist(coordinates[g]) - pdist(reference[g])))) for g in fragments if len(g) > 1),
        default=0.0,
    )


def _molecule_at(molecule: Molecule, coordinates: np.ndarray) -> Molecule:
    return Molecule.model_validate({**molecule.model_dump(), "coordinates": coordinates.tolist()})


def rigid_perturb(
    molecule: Molecule,
    rng: np.random.Generator,
    translation_angstrom: float = 0.15,
    rotation_radians: float = 0.15,
) -> Molecule:
    """Apply independent Gaussian fragment poses and remove the global frame.

    The amplitudes are component standard deviations. This proposes geometry;
    it does not perform an energy evaluation, clash filter, or quench.
    """
    if any(not math.isfinite(v) or v < 0 for v in (translation_angstrom, rotation_radians)):
        raise ConstraintError("perturbation amplitudes must be finite and nonnegative")
    groups = _groups(molecule)
    original = np.asarray(molecule.coordinates, dtype=float)
    candidate = original.copy()
    for group in groups:
        center = original[group].mean(axis=0)
        rotation = Rotation.from_rotvec(rng.normal(size=3) * rotation_radians)
        candidate[group] = rotation.apply(original[group] - center) + center
        candidate[group] += rng.normal(size=3) * translation_angstrom
    candidate = _align(candidate, original)
    return _molecule_at(molecule, candidate)


def _gradient_diagnostics(
    coordinates: np.ndarray, gradient: np.ndarray, groups: list[list[int]],
) -> tuple[np.ndarray, dict[str, Any]]:
    allowed, global_frame, free, rotation_ranks = _bases(coordinates, groups)
    vector = gradient.ravel()
    projected = free @ (free.T @ vector)
    frozen = vector - allowed @ (allowed.T @ vector)
    frame = global_frame @ (global_frame.T @ vector)
    return projected, {
        "free_rank": free.shape[1],
        "global_frame_rank": global_frame.shape[1],
        "fragment_rotation_ranks": rotation_ranks,
        "frozen_internal_rank": len(vector) - allowed.shape[1],
        "free_gradient_hartree_per_bohr": projected.reshape(gradient.shape).tolist(),
        "frozen_gradient_hartree_per_bohr": frozen.reshape(gradient.shape).tolist(),
        "global_frame_gradient_hartree_per_bohr": frame.reshape(gradient.shape).tolist(),
        "max_free_gradient_hartree_per_bohr": float(np.max(np.abs(projected))),
        "rms_free_gradient_hartree_per_bohr": float(np.linalg.norm(projected) / math.sqrt(max(1, free.shape[1]))),
        "max_frozen_gradient_hartree_per_bohr": float(np.max(np.abs(frozen))),
        "gradient_projection": "Euclidean Cartesian rigid tangent; remove whole-system translations/rotations",
        "rms_gradient_definition": "norm(projected Cartesian gradient) / sqrt(free_rank)",
    }


def _lbfgs_direction(
    gradient: np.ndarray, history: list[tuple[np.ndarray, np.ndarray]],
) -> np.ndarray:
    q = gradient.copy()
    alphas = []
    for step, change in reversed(history):
        alpha = float(step @ q / (step @ change))
        alphas.append(alpha)
        q -= alpha * change
    scale = 100.0
    if history:
        step, change = history[-1]
        scale = float(np.clip((step @ change) / (change @ change), 1e-2, 1e5))
    result = scale * q
    for (step, change), alpha in zip(history, reversed(alphas), strict=True):
        beta = float(change @ result / (step @ change))
        result += step * (alpha - beta)
    return -result


def constrained_optimize(
    molecule: Molecule,
    energy_gradient_callback: Callable[[Molecule], Any],
    constraints: dict[str, Any] | None = None,
    tolerances: str | ConvergenceProfile | dict[str, Any] | None = None,
    *,
    budget_seconds: float = 300.0,
    max_evaluations: int = 1000,
    max_step_angstrom: float = 0.2,
    cancel_event: Any = None,
) -> ConstrainedResult:
    """Minimize an authentic energy on the rigid-fragment configuration space.

    Callback outputs are ``(energy_hartree, gradient_hartree_per_bohr)`` or an
    EngineResult with those attributes. Callback exceptions propagate, allowing
    the workflow to retain engine-specific failure evidence. The callback must
    also enforce its own remaining wall-clock/process budget. The final state
    is the last accepted evaluation, never an unevaluated line-search proposal.
    """
    settings = dict(constraints or {})
    validated = validate_constraints(molecule, settings, tolerances)
    profile = ConvergenceProfile(**validated["profile"])
    if not math.isfinite(budget_seconds) or budget_seconds <= 0 or not math.isfinite(max_step_angstrom) or max_step_angstrom <= 0:
        raise ConstraintError("budget and maximum step must be finite and positive")
    if not isinstance(max_evaluations, int) or max_evaluations < 1:
        raise ConstraintError("max_evaluations must be a positive integer")
    uncertainty = settings.get("reference_uncertainty_angstrom")
    groups = _groups(molecule)
    reference_angstrom = np.asarray(molecule.coordinates, dtype=float)
    reference = reference_angstrom / BOHR_ANGSTROM
    coordinates = reference.copy()
    started = time.monotonic()
    logs: list[dict[str, Any]] = []
    history: list[tuple[np.ndarray, np.ndarray]] = []
    energy: float | None = None
    gradient: np.ndarray | None = None
    diagnostics: dict[str, Any] = {
        "constraint_kind": "frozen-monomers",
        "profile": asdict(profile),
        "reference_source": settings.get("reference_source", "user-supplied input geometry; accuracy unverified"),
        "reference_uncertainty_angstrom": uncertainty,
        "reference_geometry_id": settings.get("reference_geometry_id"),
        "reference_coordinates_angstrom": molecule.coordinates,
        "atom_ids": molecule.atom_ids,
        "isotopes": molecule.isotopes,
        "fragments": groups,
        "fragment_states": [s.model_dump() for s in molecule.fragment_states],
        "charge": molecule.charge,
        "multiplicity": molecule.multiplicity,
        "optimizer": "rigid-retraction projected L-BFGS with Armijo line search",
        "hessian_model": "limited-memory inverse quasi-Newton approximation; no frequency Hessian",
        "classification": "constrained stationary point only; full-dimensional stability not established",
        "iteration": 0,
    }

    def stop_status() -> str | None:
        if cancel_event is not None and cancel_event.is_set():
            return "cancelled"
        if time.monotonic() - started >= budget_seconds:
            return "timed-out"
        if len(logs) >= max_evaluations:
            return "evaluation-limit"
        return None

    def evaluate(position: np.ndarray) -> tuple[float, np.ndarray]:
        candidate = _molecule_at(molecule, position * BOHR_ANGSTROM)
        drift = intrafragment_drift(reference_angstrom, candidate.coordinates, groups)
        if drift >= profile.rigidity_angstrom:
            raise TrajectoryDriftViolationError(f"intrafragment drift {drift:.12g} Å breaches {profile.profile_id}")
        value = energy_gradient_callback(candidate)
        if isinstance(value, tuple) and len(value) == 2:
            e, g = value
        else:
            if getattr(value, "status", None) != "completed":
                raise EnergyGradientError(f"gradient callback status is {getattr(value, 'status', 'invalid')}")
            e, g = value.energy_hartree, value.gradient_hartree_per_bohr
        if e is None or g is None:
            raise EnergyGradientError("both energy and gradient are required; missing is not zero")
        e, g = float(e), np.asarray(g, dtype=float)
        if not math.isfinite(e) or g.shape != position.shape or not np.all(np.isfinite(g)):
            raise EnergyGradientError("energy/gradient must be finite and gradient must have shape (atoms, 3)")
        logs.append({
            "evaluation": len(logs) + 1,
            "elapsed_seconds": time.monotonic() - started,
            "coordinates_angstrom": candidate.coordinates,
            "energy_hartree": e,
            "gradient_hartree_per_bohr": g.tolist(),
            "intrafragment_drift_angstrom": drift,
            "accepted": False,
        })
        return e, g

    def finish(status: str, converged: bool = False) -> ConstrainedResult:
        diagnostics["elapsed_seconds"] = time.monotonic() - started
        diagnostics["evaluation_count"] = len(logs)
        diagnostics["max_trajectory_intrafragment_drift_angstrom"] = max((e["intrafragment_drift_angstrom"] for e in logs), default=0.0)
        diagnostics["termination"] = status
        if gradient is not None:
            _, projected = _gradient_diagnostics(coordinates, gradient, groups)
            diagnostics.update(projected)
            diagnostics["geometric_strain_warning"] = projected["max_frozen_gradient_hartree_per_bohr"] > profile.strain_warning_hartree_per_bohr
        return ConstrainedResult(
            _molecule_at(molecule, coordinates * BOHR_ANGSTROM), energy,
            None if gradient is None else gradient.tolist(), converged,
            "completed" if converged else status, diagnostics, logs,
        )

    stopped = stop_status()
    if stopped:
        return finish(stopped)
    energy, gradient = evaluate(coordinates)
    logs[-1]["accepted"] = True
    free_gradient, projected = _gradient_diagnostics(coordinates, gradient, groups)
    diagnostics.update(projected)

    for iteration in range(1, profile.max_iterations + 1):
        stopped = stop_status()
        if stopped:
            return finish(stopped)
        _, _, free, _ = _bases(coordinates, groups)
        direction = _lbfgs_direction(free_gradient, history)
        direction = free @ (free.T @ direction)
        if float(direction @ free_gradient) >= 0 and np.linalg.norm(free_gradient) > 1e-15:
            history.clear()
            direction = -100.0 * free_gradient
        largest_step = float(np.max(np.linalg.norm(direction.reshape((-1, 3)), axis=1)))
        if largest_step > max_step_angstrom / BOHR_ANGSTROM:
            direction *= max_step_angstrom / BOHR_ANGSTROM / largest_step
        accepted = False
        for line_search in range(30):
            stopped = stop_status()
            if stopped:
                return finish(stopped)
            alpha = 0.5**line_search
            proposed = _retract(coordinates, coordinates + alpha * direction.reshape((-1, 3)), groups, reference)
            trial_energy, trial_gradient = evaluate(proposed)
            # A tiny allowance addresses floating-point cancellation at the
            # minimum; it is far below either documented energy tolerance.
            armijo = energy + 1e-4 * alpha * float(free_gradient @ direction)
            if trial_energy <= armijo + 1e-14 * max(1.0, abs(energy)):
                accepted = True
                logs[-1]["accepted"] = True
                break
        if not accepted:
            return finish("line-search-failed")
        step = (proposed - coordinates).ravel()
        new_free_gradient, projected = _gradient_diagnostics(proposed, trial_gradient, groups)
        energy_change = abs(trial_energy - energy)
        max_displacement = float(np.max(np.abs(step)))
        rms_displacement = float(np.linalg.norm(step) / math.sqrt(len(step)))
        criteria = {
            "energy": energy_change <= profile.energy_hartree,
            "max_free_gradient": projected["max_free_gradient_hartree_per_bohr"] <= profile.max_gradient_hartree_per_bohr,
            "rms_free_gradient": projected["rms_free_gradient_hartree_per_bohr"] <= profile.rms_gradient_hartree_per_bohr,
            "rms_displacement": rms_displacement <= profile.rms_displacement_bohr,
            "max_displacement": max_displacement <= profile.max_displacement_bohr,
        }
        change = new_free_gradient - free_gradient
        if float(step @ change) > 1e-10 * np.linalg.norm(step) * np.linalg.norm(change) and np.linalg.norm(step) > 1e-14:
            history.append((step, change))
            history = history[-10:]
        coordinates, energy, gradient = proposed, trial_energy, trial_gradient
        free_gradient = new_free_gradient
        diagnostics.update(projected)
        diagnostics.update({
            "iteration": iteration, "energy_change_hartree": energy_change,
            "max_displacement_bohr": max_displacement,
            "rms_displacement_bohr": rms_displacement,
            "rms_displacement_definition": "norm(aligned Cartesian step) / sqrt(3N)",
            "convergence_criteria": criteria,
        })
        if all(criteria.values()):
            # A result that arrived after its allotted wall time is partial,
            # even if its numerical convergence criteria pass.
            if time.monotonic() - started >= budget_seconds:
                return finish("timed-out")
            if cancel_event is not None and cancel_event.is_set():
                return finish("cancelled")
            return finish("converged", True)
    return finish("iteration-limit")
