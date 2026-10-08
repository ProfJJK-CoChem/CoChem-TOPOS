"""Rigid-rotor arithmetic for explicitly observed atomic masses.

This module is pure geometry arithmetic. Native-output attestation is the
caller's responsibility; this function never certifies native execution.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy import constants

from .models import Molecule
from .science import constants_provenance
from .storage import digest_json


def observed_mass_rotors(molecule: Molecule, masses_amu: list[float],
                         rounding_half_width_amu: list[float]) -> dict[str, Any]:
    """Use the supplied atomic masses without any isotope-table substitution."""
    molecule = Molecule.model_validate(molecule.model_dump())
    masses = np.asarray(masses_amu, dtype=float)
    half_width = np.asarray(rounding_half_width_amu, dtype=float)
    if (masses.shape != (len(molecule.symbols),) or half_width.shape != masses.shape
            or not np.isfinite(masses).all() or not np.isfinite(half_width).all()
            or np.any(half_width <= 0) or np.any(masses <= half_width)):
        raise ValueError("Complete finite positive atomic masses and observed rounding intervals required")
    xyz = np.asarray(molecule.coordinates, dtype=float)

    def principal_moments(weights):
        shifted = xyz - np.average(xyz, axis=0, weights=weights)
        tensor = sum(m * (np.dot(r, r) * np.eye(3) - np.outer(r, r))
                     for m, r in zip(weights, shifted, strict=True))
        moments = np.linalg.eigvalsh(tensor)
        scale = max(float(np.max(np.abs(moments))), 1.0)
        if float(moments.min()) < -1e-12 * scale:
            raise ValueError("Unphysical inertia tensor for supplied atomic masses")
        return np.maximum(moments, 0.0)

    moments = principal_moments(masses)
    low, high = principal_moments(masses - half_width), principal_moments(masses + half_width)
    scale = max(float(np.max(moments)), 1.0)
    factor = constants.h / (8 * np.pi**2 * constants.atomic_mass * constants.angstrom**2) / 1e6
    values, intervals = [], []
    for nominal, lower, upper in zip(moments, low, high, strict=True):
        if nominal <= 1e-12 * scale:
            values.append(None)
            intervals.append(None)
        else:
            if lower <= 0 or not lower <= nominal + 1e-12 * scale <= upper + 2e-12 * scale:
                raise ValueError("Mass-rounding inertia bounds are numerically inconsistent")
            value = float(factor / nominal)
            values.append(value)
            intervals.append([min(float(factor / upper), value), max(float(factor / lower), value)])
    return {
        "schema_version": "topos-native-observed-atomic-mass-rotors/1",
        "observable": "equilibrium-rigid-rotor", "not_measured_B0": True,
        "constants_mhz": values, "moments_amu_angstrom2": moments.tolist(),
        "geometry_class": "monatomic" if len(masses) == 1 else ("linear" if values[0] is None else "nonlinear"),
        "molecule_sha256": digest_json(molecule.model_dump(mode="json")),
        "atom_ids": molecule.atom_ids, "symbols": molecule.symbols,
        "masses_amu": masses.tolist(), "rounding_half_width_amu": half_width.tolist(),
        "mass_kind": "native-observed rotor atomic masses, not DBOC nuclear masses",
        "mass_rounding_intervals_mhz": intervals,
        "interval_definition": "At fixed coordinates, increasing all positive masses increases the centered inertia tensor in positive-semidefinite order. Sorted principal moments at the componentwise mass endpoints bound each sorted rigid-rotor constant; floating-point roundoff is not separately bounded.",
        "uncertainty_scope": "Printed atomic-mass rounding only; no geometry, model, physical-constant or statistical uncertainty claim",
        "constants": constants_provenance(), "native_execution_verified": False,
    }
