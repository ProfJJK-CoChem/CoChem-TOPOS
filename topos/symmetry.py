"""Geometry symmetry and observable annotations with explicit numerical scope.

MolSym implements Beruski and Vidal, J. Comput. Chem. (2014),
doi:10.1002/jcc.23493. Its proposed operations are independently checked
against isotope-labelled Cartesian coordinates; a tolerance sweep is retained.
Point groups are not molecular permutation-inversion groups or spin weights.
"""
from __future__ import annotations

from importlib.metadata import version
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from .chemistry import resolved_masses
from .models import Molecule
from .science import geometry_digest, rotational_constants


def _labelled_residual(xyz: np.ndarray, transformed: np.ndarray,
                       labels: list[tuple[str, float]]) -> tuple[float, list[int]]:
    distances = np.linalg.norm(xyz[:, None, :] - transformed[None, :, :], axis=2)
    for i, first in enumerate(labels):
        for j, second in enumerate(labels):
            if first != second:
                distances[i, j] = 1e100
    rows, columns = linear_sum_assignment(distances)
    return float(np.max(distances[rows, columns])), columns.tolist()


def _point_group_at(molecule: Molecule, tolerance: float, isotope_policy: str) -> dict[str, Any]:
    import molsym
    from molsym.symtext.general_irrep_mats import pg_to_symels
    from molsym.symtext.symtext_helper import rotate_mol_to_symels

    masses, _ = resolved_masses(molecule, isotope_policy=isotope_policy)
    xyz = np.asarray(molecule.coordinates, dtype=float)
    xyz = xyz - np.average(xyz, axis=0, weights=masses)
    # Resolved masses make an unspecified most-abundant isotope equivalent to
    # its explicit isotope. Element identity remains a separate hard constraint.
    labels = list(zip(molecule.symbols, masses.tolist(), strict=True))
    if len(xyz) == 1:
        return {"point_group": "Kh", "status": "verified", "geometry_class": "monatomic",
                "has_improper_operations": True, "rotational_symmetry_number": 1,
                "max_operation_residual_angstrom": 0.0,
                "verification": "spherically symmetric single atom; no rotational partition function"}
    if np.max(np.linalg.norm(xyz, axis=1)) <= tolerance:
        return {"point_group": None, "status": "unresolved", "reason": "coincident geometry"}
    _, _, vt = np.linalg.svd(xyz, full_matrices=False)
    axis = vt[0]
    line_residual = float(np.max(np.linalg.norm(xyz - np.outer(xyz @ axis, axis), axis=1)))
    if line_residual <= tolerance:
        inversion_residual, mapping = _labelled_residual(xyz, -xyz, labels)
        centrosymmetric = inversion_residual <= tolerance
        return {"point_group": "Dinfh" if centrosymmetric else "Cinfv", "status": "verified",
                "geometry_class": "linear", "has_improper_operations": True,
                "rotational_symmetry_number": 2 if centrosymmetric else 1,
                "line_residual_angstrom": line_residual,
                "max_operation_residual_angstrom": max(line_residual, inversion_residual) if centrosymmetric else line_residual,
                "inversion_mapping": mapping if centrosymmetric else None,
                "verification": "labelled collinearity and inversion; infinite rotation family analytic"}
    native = molsym.Molecule(molecule.symbols, xyz.copy(), masses)
    native.tol = tolerance
    try:
        proposed_group, (primary_axis, secondary_axis) = molsym.find_point_group(native)
        if proposed_group in {"C0v", "D0h"}:
            # MolSym uses an inertia tolerance too; that cannot substitute for
            # the explicit Cartesian linearity criterion above.
            return {"point_group": None, "status": "unresolved", "reason": "backend linear classification fails Cartesian check"}
        oriented, _, _ = rotate_mol_to_symels(native, primary_axis, secondary_axis)
        symels, _, _ = pg_to_symels(proposed_group)
        operations = []
        for operation in symels:
            matrix = np.asarray(operation.rrep, dtype=float)
            residual, mapping = _labelled_residual(oriented.coords,
                                                   oriented.coords @ matrix.T, labels)
            operations.append({"name": operation.symbol, "determinant": round(float(np.linalg.det(matrix))),
                               "max_residual_angstrom": residual, "atom_mapping": mapping})
        selected_group = proposed_group
        correction = None
        # MolSym 1.2 has no T-vs-Td branch after locating three C2 axes.
        # The proper tetrahedral subgroup is sufficient only when ALL its
        # twelve operations work and NONE of Td's improper operations do.
        proper = [op for op in operations if op["determinant"] > 0]
        improper = [op for op in operations if op["determinant"] < 0]
        if (proposed_group == "Td" and len(proper) == 12 and len(improper) == 12
                and all(op["max_residual_angstrom"] <= tolerance + 1e-12 for op in proper)
                and all(op["max_residual_angstrom"] > tolerance + 1e-12 for op in improper)):
            selected_group, operations = "T", proper
            correction = "verified proper tetrahedral subgroup; all proposed Td improper operations rejected"
        worst = max(op["max_residual_angstrom"] for op in operations)
        verified = worst <= tolerance + 1e-12
        return {"point_group": selected_group if verified else None,
                "proposed_point_group": proposed_group, "proposal_correction": correction,
                "status": "verified" if verified else "unresolved", "geometry_class": "nonlinear",
                "has_improper_operations": any(op["determinant"] < 0 for op in operations) if verified else None,
                "rotational_symmetry_number": sum(op["determinant"] > 0 for op in operations) if verified else None,
                "max_operation_residual_angstrom": worst, "operations": operations,
                "verification": "all generated operations, labelled bijection and Euclidean Cartesian residual"}
    except Exception as exc:  # MolSym also raises plain Exception for unsupported symmetry mappings.
        return {"point_group": None, "status": "unresolved", "reason": f"symmetry backend could not certify geometry ({type(exc).__name__})"}


def point_group_analysis(molecule: Molecule, *, tolerance_angstrom: float = 1e-3,
                         sweep_factors: tuple[float, ...] = (0.1, 1.0, 10.0),
                         isotope_policy: str = "most_abundant") -> dict[str, Any]:
    """Assign isotope-aware point groups with a mandatory tolerance sweep.

    ``stable`` means stable only over the supplied numerical tolerances. It is
    not an accuracy estimate for the geometry, proof of a minimum, or a claim
    about large-amplitude molecular symmetry. Symmetry never changes identity.
    """
    if (not np.isfinite(tolerance_angstrom) or tolerance_angstrom <= 0
            or not sweep_factors or any(not np.isfinite(x) or x <= 0 for x in sweep_factors)):
        raise ValueError("symmetry tolerances must be finite and positive")
    factors = sorted(set((*sweep_factors, 1.0)))
    if not any(x < 1 for x in factors) or not any(x > 1 for x in factors):
        raise ValueError("symmetry sweep must include tolerances below and above the requested value")
    sweep = [{"tolerance_angstrom": tolerance_angstrom * factor,
              **_point_group_at(molecule, tolerance_angstrom * factor, isotope_policy)} for factor in factors]
    primary = sweep[factors.index(1.0)]
    stable = all(item["status"] == "verified" and item["point_group"] == primary["point_group"] for item in sweep)
    _, isotope_records = resolved_masses(molecule, isotope_policy=isotope_policy)
    return {**primary, "status": "stable" if stable else "requires-review",
            "geometry_digest": geometry_digest(molecule), "coordinate_units": "angstrom",
            "algorithm": "MolSym point-group proposal with independent isotope-labelled operation verification",
            "algorithm_version": version("molsym"), "algorithm_reference": "https://doi.org/10.1002/jcc.23493",
            "isotope_policy": isotope_policy, "isotope_provenance": isotope_records,
            "tolerance_sweep": sweep, "uncertainty": "stable-over-declared-sweep" if stable else "tolerance-sensitive-or-unresolved",
            "is_chiral_geometry": not primary["has_improper_operations"] if stable and primary.get("has_improper_operations") is not None else None,
            "scope": "static nuclear geometry; not permutation-inversion symmetry or nuclear spin statistics",
            "backend_tolerance_note": "MolSym uses its native scalar tolerance for internal Cartesian/inertia tests; every reported operation separately meets the stated Cartesian tolerance"}


def principal_axis_dipole(molecule: Molecule, cartesian_dipole_debye: list[float], *,
                          dipole_method: str, dark_threshold_debye: float = 0.1,
                          degeneracy_relative_tolerance: float = 1e-7) -> dict[str, Any]:
    """Transform an actual supplied vector into the isotope-specific a,b,c axes.

    Eigenvector signs use ordered atom IDs as a deterministic gauge, then a
    right-handed frame. Degenerate eigenspaces have no unique components;
    those components and per-axis dark flags are omitted, with their norm kept.
    """
    vector = np.asarray(cartesian_dipole_debye, dtype=float)
    if vector.shape != (3,) or not np.isfinite(vector).all() or not dipole_method.strip():
        raise ValueError("a finite Cartesian dipole vector and its method are required")
    if any(not np.isfinite(x) or x <= 0 for x in (dark_threshold_debye, degeneracy_relative_tolerance)):
        raise ValueError("dipole annotation tolerances must be finite and positive")
    masses, _ = resolved_masses(molecule)
    xyz = np.asarray(molecule.coordinates, dtype=float)
    xyz -= np.average(xyz, axis=0, weights=masses)
    tensor = sum(m * (np.dot(r, r) * np.eye(3) - np.outer(r, r)) for m, r in zip(masses, xyz, strict=True))
    moments, axes = np.linalg.eigh(tensor)
    order = sorted(range(len(xyz)), key=lambda i: molecule.atom_ids[i])
    for index in range(3):
        projected = xyz @ axes[:, index]
        usable = [i for i in order if abs(projected[i]) > 1e-10]
        if usable and projected[usable[0]] < 0:
            axes[:, index] *= -1
    if np.linalg.det(axes) < 0:
        axes[:, 2] *= -1
    components = vector @ axes
    scale = max(float(np.max(abs(moments))), 1e-12)
    ambiguous = [any(i != j and abs(moments[i] - moments[j]) <= degeneracy_relative_tolerance * scale
                     for j in range(3)) for i in range(3)]
    signed = [None if ambiguous[i] else float(components[i]) for i in range(3)]
    dark = [None if x is None else abs(x) < dark_threshold_debye for x in signed]
    # A spherical top still has a known total magnitude, but no unique branches.
    all_dark = float(np.linalg.norm(vector)) < dark_threshold_debye if any(ambiguous) else all(dark)
    return {"cartesian_debye": vector.tolist(), "signed_abc_debye": signed,
            "dipole_method": dipole_method, "axes_columns_in_cartesian": axes.tolist(),
            "axis_order": ["a", "b", "c"], "axis_sign_convention": "ordered atom-ID projection; right-handed frame",
            "moments_amu_angstrom2": moments.tolist(), "degenerate_axes": ambiguous,
            "degeneracy_relative_tolerance": degeneracy_relative_tolerance,
            "total_dipole_debye": float(np.linalg.norm(vector)), "dark_branches": dark,
            "dark_threshold_debye": dark_threshold_debye,
            "exclude_from_line_list": all_dark, "retain_in_thermodynamic_ensemble": True,
            "status": "axis-ambiguity" if any(ambiguous) else "resolved",
            "geometry_digest": geometry_digest(molecule),
            "origin_convention": "supplied vector in input coordinate origin; charged-species dipoles are origin dependent",
            "sign_warning": "signed components require the recorded frame; arbitrary eigenvector signs must not be compared directly"}


def rotational_observables(molecule: Molecule, *, geometry_method: str,
                           vibration_rotation_alpha_ghz: list[list[float]] | None = None,
                           correction_method: str | None = None,
                           semi_rigid_unconstrained: bool = False) -> dict[str, Any]:
    """Label Ae/Be/Ce and optionally apply supplied, provenance-bearing alpha_r.

    B0 = Be - 1/2 sum(alpha_r) applies here only to an explicitly asserted
    semi-rigid unconstrained nonlinear molecule with all 3N-6 modes. This does
    not calculate VPT2, model tunnelling, or relabel an empirical Be as B0.
    """
    if not geometry_method.strip():
        raise ValueError("geometry method provenance is required")
    equilibrium = rotational_constants(molecule)
    result = {"equilibrium": equilibrium, "geometry_method": geometry_method,
              "equilibrium_labels": ["Ae", "Be", "Ce"], "ground_state_ghz": None,
              "correction_model": None, "uncertainty": "not-established-by-geometry-alone"}
    if vibration_rotation_alpha_ghz is None:
        return result
    alpha = np.asarray(vibration_rotation_alpha_ghz, dtype=float)
    if not semi_rigid_unconstrained or equilibrium["geometry_class"] != "nonlinear":
        raise ValueError("alpha zero-point correction requires an explicitly semi-rigid unconstrained nonlinear molecule")
    if not correction_method or not correction_method.strip():
        raise ValueError("vibration-rotation correction method provenance is required")
    if alpha.shape != (3 * len(molecule.symbols) - 6, 3) or not np.isfinite(alpha).all():
        raise ValueError("alpha must contain finite (3N-6) by 3 GHz values")
    ground = np.asarray(equilibrium["constants_ghz"]) - 0.5 * alpha.sum(axis=0)
    if np.any(ground <= 0):
        raise ValueError("vibration-rotation correction produced nonpositive rotational constants")
    return {**result, "ground_state_ghz": ground.tolist(), "ground_state_labels": ["A0", "B0", "C0"],
            "vibration_rotation_alpha_ghz": alpha.tolist(), "correction_method": correction_method,
            "correction_model": "semi-rigid-nonlinear-zero-point-alpha-sum", "experimental": False}
