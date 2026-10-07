"""Explicit internal-coordinate composites and finite energy arithmetic.

These functions do not run an electronic-structure engine or certify the
provenance, convergence, or stationary-point character of supplied quantities.
The caller must establish those properties before applying a matrix recipe.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Real
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import Field, model_validator

from .models import Contract, Molecule
from .scans import (
    ScanCoordinate,
    constraint_system,
    coordinate_value_jacobian,
    project_scan_geometry,
)
from .science import BOHR_ANGSTROM, geometry_digest, validate_stereochemical_preservation

JUNCHS_CBS_COEFFICIENT = 64 / (64 - 27)


class CompositeCoordinate(Contract):
    """One labelled internal coordinate; atom indices are zero based."""

    kind: Literal["distance", "angle", "dihedral"]
    atoms: list[Annotated[int, Field(strict=True, ge=0)]] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def validate_coordinate(self) -> CompositeCoordinate:
        count = {"distance": 2, "angle": 3, "dihedral": 4}[self.kind]
        if len(self.atoms) != count or len(set(self.atoms)) != count:
            raise ValueError("Composite coordinate needs distinct atom indices matching its kind")
        return self

    @property
    def units(self) -> str:
        return "angstrom" if self.kind == "distance" else "degree"

    def scan_coordinate(self) -> ScanCoordinate:
        # A legal placeholder creates the shared analytic-coordinate contract;
        # actual targets are supplied separately to its projector.
        return ScanCoordinate(kind=self.kind, atoms=self.atoms, units=self.units,
                              values=[1.0 if self.kind == "distance" else 90.0])


class CompositeCoordinateSet(Contract):
    """Complete independent chart and the explicit same-basis CV resolution.

    For nonlinear N >= 3 a chart has exactly 3N-6 nonsingular coordinates.
    One atom has no internal coordinates; a diatomic has one distance. Linear
    polyatomics need a different chart (linear bends) and are not supported.
    """

    coordinates: list[CompositeCoordinate]
    cv_basis: Literal["cc-pwCVTZ"]
    cv_resolution: Literal["same-basis-ae-minus-fc"]
    projection_tolerance_native: float = Field(default=1e-10, gt=0, le=1e-8)


def _finite_real(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real number, not a coerced string or boolean")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def cps67(hf_hartree: float, correlation6_hartree: float,
          correlation7_hartree: float) -> float:
    """HF + Ecorr(6) + 1.5[Ecorr(7)-Ecorr(6)], in hartree.

    The correlation energies include the requested triples contribution and
    must share the same reference, orbital basis, and all settings except the
    1e-6/1e-7 TCutPNO thresholds. These provenance requirements are the caller's
    responsibility. The numerical 6/7 spread is not an uncertainty estimate.
    """
    hf = _finite_real(hf_hartree, "HF energy")
    e6 = _finite_real(correlation6_hartree, "Correlation energy at 1e-6")
    e7 = _finite_real(correlation7_hartree, "Correlation energy at 1e-7")
    try:
        result = math.fsum([hf, -.5 * e6, 1.5 * e7])
    except (OverflowError, ValueError) as exc:
        raise ValueError("CPS(6/7) arithmetic is nonfinite") from exc
    return _finite_real(result, "CPS(6/7) energy")


def weighted_energy_sum(energies: Mapping[str, float], coefficients: Mapping[str, float], *,
                        compatibility_keys: Mapping[str, str]) -> float:
    """Sum energies in hartree with explicit matching component identities.

    All three mappings must contain exactly the same nonempty set of component
    names. A common nonempty compatibility key attests a common chemical state,
    energy definition, units, and any geometry condition imposed by the recipe.
    Component methods/bases may differ by design. A key is a caller assertion,
    not proof of engine provenance or of a scientifically appropriate recipe.
    """
    if not all(isinstance(value, Mapping) for value in
               (energies, coefficients, compatibility_keys)):
        raise ValueError("Energies, coefficients and compatibility keys must be mappings")
    keys = set(energies)
    if not keys or any(not isinstance(key, str) or not key.strip() for key in keys):
        raise ValueError("Energy component keys must be nonempty strings")
    if keys != set(coefficients) or keys != set(compatibility_keys):
        raise ValueError("Energy, coefficient and compatibility component keys must match exactly")
    labels = list(compatibility_keys.values())
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError("Every component requires a nonempty compatibility key")
    if len(set(labels)) != 1:
        raise ValueError("Energy components have incompatible scientific compatibility keys")
    terms = [_finite_real(energies[key], f"Energy {key}")
             * _finite_real(coefficients[key], f"Coefficient {key}") for key in sorted(keys)]
    if not all(math.isfinite(term) for term in terms):
        raise ValueError("Weighted energy arithmetic is nonfinite")
    try:
        result = math.fsum(terms)
    except (OverflowError, ValueError) as exc:
        raise ValueError("Weighted energy arithmetic is nonfinite") from exc
    return _finite_real(result, "Weighted energy")


def _wrap_degrees(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def _increment(high: float, low: float, coordinate: CompositeCoordinate) -> float:
    difference = high - low
    if coordinate.kind == "dihedral":
        difference = _wrap_degrees(difference)
        if math.isclose(abs(difference), 180.0, abs_tol=1e-8, rel_tol=0):
            raise ValueError("A 180-degree dihedral increment has no unique shortest direction")
    return difference


def _geometry_parameters(molecule: Molecule, coordinates: CompositeCoordinateSet,
                         scans: list[ScanCoordinate]) -> tuple[list[float], float | None]:
    xyz = np.asarray(molecule.coordinates, dtype=float) / BOHR_ANGSTROM
    n = len(xyz)
    for index in range(n):
        if n > index + 1 and np.min(np.linalg.norm(xyz[index + 1:] - xyz[index], axis=1)) < 1e-8:
            raise ValueError("Composite component geometry contains coincident atoms")
    if n >= 3:
        singular = np.linalg.svd(xyz - xyz.mean(axis=0), compute_uv=False)
        if singular[1] <= 1e-10 * max(1.0, singular[0]):
            raise ValueError("Linear polyatomics require a nonsingular linear-bend coordinate chart")
    values = []
    for coordinate, scan in zip(coordinates.coordinates, scans, strict=True):
        value, _ = coordinate_value_jacobian(xyz, scan)
        value = value * BOHR_ANGSTROM if coordinate.kind == "distance" else math.degrees(value)
        values.append(_wrap_degrees(value) if coordinate.kind == "dihedral" else value)
    if not scans:
        return values, None
    _, jacobian = constraint_system(xyz, scans, tuple(values))
    singular = np.linalg.svd(jacobian, compute_uv=False)
    return values, float(singular[-1] / singular[0])


def combine_junchs_geometry(base: Molecule, mp2_tz: Molecule, mp2_qz: Molecule,
                            cv_ae: Molecule, cv_fc: Molecule,
                            coordinates: CompositeCoordinateSet) -> dict[str, Any]:
    """Apply RccTZ + (64/37)(Rmp2Q-Rmp2T) + (RaeCV-RfcCV).

    Addition is parameterwise in an explicitly supplied independent internal
    chart. Periodic torsion increments take the shortest direction. Cartesian
    reconstruction uses the shared coordinate Jacobian/Newton projector and
    follows the branch local to the base geometry. This is geometry arithmetic,
    not optimization of a composite energy surface or a minimum certification.
    """
    if not isinstance(coordinates, CompositeCoordinateSet):
        raise ValueError("An explicit typed CompositeCoordinateSet is required")
    coordinates = CompositeCoordinateSet.model_validate(coordinates.model_dump())
    components = {"base": base, "mp2_tz": mp2_tz, "mp2_qz": mp2_qz,
                  "cv_ae": cv_ae, "cv_fc": cv_fc}
    if any(not isinstance(molecule, Molecule) for molecule in components.values()):
        raise ValueError("Each component must be a typed Molecule")
    components = {key: Molecule.model_validate(molecule.model_dump())
                  for key, molecule in components.items()}
    base = components["base"]
    identity = base.model_dump(exclude={"coordinates", "name"})
    stereochemistry_checks = {}
    for key, molecule in components.items():
        if molecule.model_dump(exclude={"coordinates", "name"}) != identity:
            raise ValueError(f"Composite component {key} changes atom/bond/state/isotope identity")
        stereochemistry_checks[key] = validate_stereochemical_preservation(base, molecule)
        if stereochemistry_checks[key]["status"] != "preserved":
            raise ValueError(f"Composite component {key} has unsupported, ambiguous or changed stereochemistry")
    n = len(base.symbols)
    expected_count = 0 if n == 1 else 1 if n == 2 else 3 * n - 6
    if len(coordinates.coordinates) != expected_count:
        raise ValueError(f"A complete independent coordinate set needs exactly {expected_count} coordinates")
    if any(max(coordinate.atoms) >= n for coordinate in coordinates.coordinates):
        raise ValueError("Composite coordinate references a nonexistent atom")
    if n == 2 and coordinates.coordinates[0].kind != "distance":
        raise ValueError("A diatomic composite requires its single distance coordinate")
    scans = [coordinate.scan_coordinate() for coordinate in coordinates.coordinates]
    parameters, rank_ratios = {}, {}
    for key, molecule in components.items():
        parameters[key], rank_ratios[key] = _geometry_parameters(molecule, coordinates, scans)
    targets, cbs_increments, cv_increments = [], [], []
    for index, coordinate in enumerate(coordinates.coordinates):
        cbs = JUNCHS_CBS_COEFFICIENT * _increment(
            parameters["mp2_qz"][index], parameters["mp2_tz"][index], coordinate)
        cv = _increment(parameters["cv_ae"][index], parameters["cv_fc"][index], coordinate)
        target = math.fsum([parameters["base"][index], cbs, cv])
        if not math.isfinite(target):
            raise ValueError("Composite target arithmetic is nonfinite")
        if coordinate.kind == "dihedral":
            target = _wrap_degrees(target)
        if coordinate.kind == "distance" and target <= 0:
            raise ValueError("Composite distance target must be positive")
        if coordinate.kind == "angle" and not 0 < target < 180:
            raise ValueError("Composite bond-angle target must be strictly between 0 and 180 degrees")
        targets.append(target)
        cbs_increments.append(cbs)
        cv_increments.append(cv)
    base_xyz = np.asarray(base.coordinates, dtype=float) / BOHR_ANGSTROM
    projected = project_scan_geometry(base_xyz, scans, tuple(targets),
                                      tolerance=coordinates.projection_tolerance_native) if scans else base_xyz
    output = base.model_dump()
    output["coordinates"] = (projected * BOHR_ANGSTROM).tolist()
    molecule = Molecule.model_validate(output)
    stereochemistry_checks["composite"] = validate_stereochemical_preservation(base, molecule)
    if stereochemistry_checks["composite"]["status"] != "preserved":
        raise ValueError("Composite reconstruction has unsupported, ambiguous or changed stereochemistry")
    realized, rank_ratios["composite"] = _geometry_parameters(molecule, coordinates, scans)
    residual = constraint_system(projected, scans, tuple(targets))[0] if scans else np.array([])
    max_residual = float(np.max(np.abs(residual))) if len(residual) else 0.0
    if max_residual > coordinates.projection_tolerance_native:
        raise ValueError("Composite reconstruction exceeds its internal-coordinate residual tolerance")
    return {
        "schema_version": "topos-junchs-geometry/1",
        "molecule": molecule.model_dump(mode="json"),
        "coordinate_specification": coordinates.model_dump(mode="json"),
        "coordinate_units": [coordinate.units for coordinate in coordinates.coordinates],
        "component_parameters": parameters,
        "component_geometry_sha256": {key: geometry_digest(value) for key, value in components.items()},
        "coefficients": {"base": 1.0, "mp2_qz": JUNCHS_CBS_COEFFICIENT,
                         "mp2_tz": -JUNCHS_CBS_COEFFICIENT, "cv_ae": 1.0, "cv_fc": -1.0},
        "increments": {"cbs": cbs_increments, "core_valence": cv_increments},
        "target_parameters": targets,
        "realized_parameters": realized,
        "residual": {"native_values": residual.tolist(), "max_abs_native": max_residual,
                     "native_units": ["bohr" if c.kind == "distance" else "radian"
                                      for c in coordinates.coordinates]},
        "jacobian_smallest_to_largest_singular_value": rank_ratios,
        "stereochemistry_checks": stereochemistry_checks,
        "claims": {
            "scope": "constructed equilibrium geometry for B_e analysis only",
            "energy_computed": False,
            "stationary_point_verified": False,
            "minimum_verified": False,
            "vibrational_correction_computed": False,
            "component_engine_provenance_verified": False,
            "limitations": "Caller must verify component methods and minima; this arithmetic does not establish B_0 or a composite potential-energy surface.",
        },
    }
