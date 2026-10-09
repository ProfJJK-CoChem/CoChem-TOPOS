"""EFG tensor mathematics and explicitly sourced nuclear quadrupole conversion.

This module does not certify native output. The caller must parse authentic
CFOUR EFG grammar, establish indexed atoms, units and frame, and retain the raw
artifact hashes and the complete BASE runtime receipt before publishing a
native observation. Mathematical arrays are never electronic-structure proof.

The matrix's legacy factor is retained verbatim, not silently replaced by a
newer CODATA value. No nuclear moment or spin is inferred from isotope mass.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np
from pydantic import Field, model_validator

from .cfour_operator import CfourOperatorAuthority, validate_operator_observation
from .models import Contract, Molecule

MATRIX_QUADRUPOLE_FACTOR = 234.96474
MATRIX_QUADRUPOLE_FACTOR_UNITS = "kHz / (atomic-unit EFG * millibarn)"
MATRIX_QUADRUPOLE_FACTOR_SOURCE = "method_matrix_v4:T3C-1h:source-line-3051"
CODATA_REFERENCE = (
    "https://github.com/scipy/scipy/blob/v1.15.3/scipy/constants/_codata.py#L1658"
)


class NuclearDataSource(Contract):
    """A declared independent nuclear-data citation, not a mass-table shortcut."""

    citation: str = Field(min_length=8)
    identifier: str = Field(min_length=8)
    locator: str = Field(min_length=1)

    @model_validator(mode="after")
    def nonblank(self):
        if any(not item.strip() for item in (self.citation, self.identifier, self.locator)):
            raise ValueError("Nuclear data require a nonblank independent source and locator")
        return self


class NuclearReportedUncertaintyComponent(Contract):
    """One source-reported error, without assumed coverage or independence."""

    label: str = Field(min_length=1)
    magnitude_millibarn: float = Field(ge=0, strict=True)
    interpretation: str = Field(min_length=8)
    source: NuclearDataSource

    @model_validator(mode="after")
    def nonblank(self):
        if not self.label.strip() or not self.interpretation.strip():
            raise ValueError("Reported nuclear error components require a nonblank label and interpretation")
        return self


class NuclearQuadrupoleMoment(Contract):
    """Signed spectroscopic Q with an explicit sourced uncertainty interpretation.

    A publication's reported error is not automatically a k=1 standard
    uncertainty. The two branches remain distinct throughout conversion.
    """

    atom_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    mass_number: int = Field(ge=1, strict=True)
    nuclear_spin_twice: int = Field(ge=2, strict=True)
    signed_q_millibarn: float = Field(strict=True)
    q_standard_uncertainty_millibarn: float | None = Field(default=None, ge=0, strict=True)
    q_reported_uncertainty_millibarn: float | None = Field(default=None, ge=0, strict=True)
    q_reported_uncertainty_components: list[NuclearReportedUncertaintyComponent] = Field(default_factory=list)
    q_reported_uncertainty_policy: str | None = Field(default=None, min_length=8)
    q_convention: Literal["spectroscopic-signed-area"] = "spectroscopic-signed-area"
    uncertainty_convention: Literal["standard-uncertainty-k1", "reported-source-uncertainty"] = "standard-uncertainty-k1"
    spin_source: NuclearDataSource
    q_source: NuclearDataSource
    q_uncertainty_source: NuclearDataSource

    @model_validator(mode="after")
    def explicit_uncertainty_interpretation(self):
        if self.uncertainty_convention == "standard-uncertainty-k1":
            if self.q_standard_uncertainty_millibarn is None:
                raise ValueError("A k=1 standard nuclear uncertainty must be supplied explicitly")
            if (self.q_reported_uncertainty_millibarn is not None or self.q_reported_uncertainty_components
                    or self.q_reported_uncertainty_policy is not None):
                raise ValueError("Standard and reported nuclear uncertainty declarations cannot be mixed")
        else:
            if (self.q_reported_uncertainty_millibarn is not None) == bool(self.q_reported_uncertainty_components):
                raise ValueError("Supply exactly one reported nuclear uncertainty scalar or nonempty component list")
            labels = [item.label.strip().casefold() for item in self.q_reported_uncertainty_components]
            if len(set(labels)) != len(labels):
                raise ValueError("Reported nuclear uncertainty component labels must be unique")
            if self.q_standard_uncertainty_millibarn is not None:
                raise ValueError("Reported nuclear uncertainty cannot be relabeled as a k=1 standard uncertainty")
            if self.q_reported_uncertainty_policy is None or not self.q_reported_uncertainty_policy.strip():
                raise ValueError("Reported nuclear uncertainty requires the source's explicit interpretation or policy")
        return self


class CfourEfgConventionDeclaration(Contract):
    """Explicit review of a native convention, not independent verification.

    Native 2.1 output omits an EFG unit/sign label. A caller's citation permits
    a transparently conditional conversion, never full scientific acceptance.
    A compiled independently reviewed native convention is still required.
    """

    engine_version: Literal["2.1"] = "2.1"
    native_units: Literal["atomic-unit-electric-field-gradient"] = "atomic-unit-electric-field-gradient"
    tensor_convention: Literal["traceless-electrostatic-potential-Hessian"] = "traceless-electrostatic-potential-Hessian"
    contribution_scope: Literal["total-electronic-and-other-nuclear"] = "total-electronic-and-other-nuclear"
    source: NuclearDataSource
    reviewed_by: str = Field(min_length=1)
    reviewed_at: datetime
    review_reason: str = Field(min_length=8)

    @model_validator(mode="after")
    def reviewed_declaration(self):
        if not self.reviewed_by.strip() or not self.review_reason.strip():
            raise ValueError("Native EFG conventions require an explicit nonblank review")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("Native EFG convention review requires a timezone-aware timestamp")
        if self.reviewed_at > datetime.now(timezone.utc):
            raise ValueError("Native EFG convention review cannot be future-dated")
        return self


def _finite_array(value: Any, shape: tuple[int, ...], label: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != shape or not np.all(np.isfinite(array)):
        raise ValueError(f"{label} requires finite values with shape {shape}")
    return array


def validate_efg_tensors(tensors_atomic_units: Any, component_rounding_bounds_atomic_units: Any,
                         atom_count: int) -> tuple[np.ndarray, np.ndarray]:
    """Check conventional traceless EFGs; expose only bounded rounding repairs.

    The caller supplies half-last-place bounds derived from authentic tokens,
    never fitted tolerances. Antisymmetry or trace beyond those bounds is an
    error, not permission to remove a physical or parsing discrepancy. Returned
    bounds include the explicit symmetric/traceless rounding normalization.
    """
    if type(atom_count) is not int or atom_count < 1:
        raise ValueError("A positive exact atom count is required")
    raw = _finite_array(tensors_atomic_units, (atom_count, 3, 3), "EFG tensor")
    bound = _finite_array(component_rounding_bounds_atomic_units, raw.shape, "EFG rounding bound")
    if np.any(bound < 0) or np.any(bound > 1e-4):
        raise ValueError("EFG rounding bounds must be between zero and 1e-4 atomic units")
    numeric = 32 * np.finfo(float).eps * np.maximum(1., np.max(np.abs(raw), axis=(1, 2)))
    symmetric_bound = bound + bound.transpose(0, 2, 1)
    if np.any(np.abs(raw - raw.transpose(0, 2, 1)) > symmetric_bound + numeric[:, None, None]):
        raise ValueError("EFG is not symmetric within its observed print rounding")
    trace_bound = np.trace(bound, axis1=1, axis2=2)
    if np.any(np.abs(np.trace(raw, axis1=1, axis2=2)) > trace_bound + numeric):
        raise ValueError("EFG is not traceless within its observed print rounding")
    symmetric = (raw + raw.transpose(0, 2, 1)) / 2
    normalized = symmetric - np.trace(symmetric, axis1=1, axis2=2)[:, None, None] * np.eye(3) / 3
    normalized_bound = (bound + bound.transpose(0, 2, 1)) / 2 + trace_bound[:, None, None] * np.eye(3) / 3
    # Include arithmetic rounding in the bound used by downstream rotations.
    return normalized, normalized_bound + numeric[:, None, None]


def _indexed_tensor_rotation(native_xyz: np.ndarray, requested_xyz: np.ndarray,
                             tensors: np.ndarray, bounds: np.ndarray) -> np.ndarray:
    """Resolve proper rotation and reject an unresolved physical tensor frame."""
    a = native_xyz - native_xyz.mean(axis=0)
    b = requested_xyz - requested_xyz.mean(axis=0)
    u, singular, vt = np.linalg.svd(a.T @ b)
    parity = np.eye(3)
    parity[-1, -1] = np.linalg.det(u @ vt)
    rotation = u @ parity @ vt
    if np.max(np.linalg.norm(a @ rotation - b, axis=1)) > 2e-6:
        raise ValueError("EFG frame changed indexed geometry or requires an improper reflection")
    rank = int(np.count_nonzero(singular > max(float(singular[0]), 1.) * 1e-12))
    if rank < 2:
        # A linear geometry cannot determine rotation about its molecular axis;
        # a monatomic geometry cannot determine any rotation. Only invariant
        # tensors may pass, so SVD's arbitrary null axes never become observables.
        axis = None
        if rank == 1:
            _, _, native_vt = np.linalg.svd(a, full_matrices=False)
            axis = native_vt[0]
        for tensor, bound in zip(tensors, bounds, strict=True):
            invariant = np.zeros((3, 3))
            if axis is not None:
                axial = float(axis @ tensor @ axis)
                invariant = 1.5 * axial * np.outer(axis, axis) - .5 * axial * np.eye(3)
            if np.max(np.abs(tensor - invariant)) > 8 * np.linalg.norm(bound, ord=2):
                raise ValueError("Geometry leaves an unresolved EFG tensor frame")
    return rotation


def rotate_efg_tensors(molecule: Molecule, native_symbols: list[str],
                       native_coordinates_angstrom: Any, tensors_atomic_units: Any,
                       component_rounding_bounds_atomic_units: Any) -> dict[str, Any]:
    """Transform mathematical per-atom tensors into the requested Cartesian frame."""
    molecule = Molecule.model_validate(molecule.model_dump())
    if native_symbols != molecule.symbols:
        raise ValueError("EFG native atoms must preserve the exact indexed element inventory")
    xyz = _finite_array(native_coordinates_angstrom, (len(native_symbols), 3), "Native EFG coordinates")
    tensors, bounds = validate_efg_tensors(tensors_atomic_units, component_rounding_bounds_atomic_units,
                                         len(native_symbols))
    rotation = _indexed_tensor_rotation(xyz, np.asarray(molecule.coordinates), tensors, bounds)
    rotated = rotation.T @ tensors @ rotation
    rotated_bounds = np.abs(rotation).T @ bounds @ np.abs(rotation)
    return {"atom_ids": list(molecule.atom_ids), "symbols": list(molecule.symbols),
            "isotopes": list(molecule.isotopes), "units": "atomic-unit-electric-field-gradient",
            "frame": "requested indexed Cartesian coordinates",
            "native_coordinates_angstrom": xyz.tolist(),
            "requested_coordinates_angstrom": molecule.coordinates,
            "proper_rotation_native_to_requested": rotation.tolist(),
            "raw_tensors_native_frame_atomic_units": np.asarray(tensors_atomic_units).tolist(),
            "raw_component_rounding_bounds_atomic_units": np.asarray(component_rounding_bounds_atomic_units).tolist(),
            "rounding_normalization": "explicit symmetric part and traceless projection, bounded by native print precision",
            "tensors_atomic_units": rotated.tolist(),
            "component_rounding_bounds_atomic_units": rotated_bounds.tolist(),
            "native_execution_verified": False,
            "scope": "tensor mathematics; native atom/frame/unit/source evidence must be established separately"}


def principal_efg(tensor_atomic_units: Any, component_rounding_bounds_atomic_units: Any) -> dict[str, Any]:
    """Use |Vzz| >= |Vyy| >= |Vxx|, withholding unidentifiable axes or eta."""
    tensors, bounds = validate_efg_tensors([tensor_atomic_units], [component_rounding_bounds_atomic_units], 1)
    values, vectors = np.linalg.eigh(tensors[0])
    order = np.argsort(np.abs(values), kind="stable")
    values, vectors = values[order], vectors[:, order]
    radius = float(np.linalg.norm(bounds[0], ord=2))
    distinct = min(abs(values[i] - values[j]) for i in range(3) for j in range(i)) > 2 * radius
    unambiguous_labels = min(abs(abs(values[i]) - abs(values[j])) for i in range(3) for j in range(i)) > 2 * radius
    eta = None if abs(values[2]) <= 2 * radius else abs(float((values[0] - values[1]) / values[2]))
    return {"principal_values_atomic_units": values.tolist(),
            "ordering": "absolute Vxx <= absolute Vyy <= absolute Vzz",
            "eta": eta, "eigenvalue_rounding_bound_atomic_units": radius,
            "principal_axes_columns": vectors.tolist() if distinct and unambiguous_labels else None,
            "axes_unique_up_to_sign": bool(distinct and unambiguous_labels),
            "axis_signs_observable": False}


def nuclear_quadrupole_couplings(molecule: Molecule, tensors_atomic_units: Any,
                                component_rounding_bounds_atomic_units: Any,
                                nuclei: list[NuclearQuadrupoleMoment]) -> dict[str, Any]:
    """Convert signed EFGs without inferring missing nuclear physics from masses."""
    molecule = Molecule.model_validate(molecule.model_dump())
    tensors, bounds = validate_efg_tensors(tensors_atomic_units, component_rounding_bounds_atomic_units,
                                         len(molecule.symbols))
    nuclei = [NuclearQuadrupoleMoment.model_validate(item.model_dump()) for item in nuclei]
    if not nuclei or len({item.atom_id for item in nuclei}) != len(nuclei):
        raise ValueError("Quadrupole conversion requires nonempty unique declared nuclear targets")
    results = []
    for nucleus in nuclei:
        if nucleus.atom_id not in molecule.atom_ids:
            raise ValueError("Quadrupole target atom identity is absent from the molecule")
        index = molecule.atom_ids.index(nucleus.atom_id)
        if molecule.symbols[index] != nucleus.symbol or molecule.isotopes[index] != nucleus.mass_number:
            raise ValueError("Quadrupole conversion requires the exact explicitly declared atom isotope")
        tensor, bound = tensors[index], bounds[index]
        factor = MATRIX_QUADRUPOLE_FACTOR
        coupling = factor * nucleus.signed_q_millibarn * tensor
        principal = principal_efg(tensor, bound)
        # Store the signed Q sensitivity. Only an explicitly declared k=1
        # uncertainty supports standard component errors; a reported source
        # error supplies no inferred distribution, coverage factor or interval.
        sensitivity = factor * tensor
        standard_uncertainty = (np.abs(sensitivity) * nucleus.q_standard_uncertainty_millibarn
                                if nucleus.q_standard_uncertainty_millibarn is not None else None)
        results.append({"atom_id": nucleus.atom_id, "atom_index": index,
                        "nuclear_data": nucleus.model_dump(mode="json"),
                        "coupling_tensor_khz": coupling.tolist(),
                        "principal_couplings_khz": (factor * nucleus.signed_q_millibarn * np.asarray(
                            principal["principal_values_atomic_units"])).tolist(),
                        "efg_principal_axes": principal,
                        "q_sensitivity_khz_per_millibarn": sensitivity.tolist(),
                        "q_only_component_standard_uncertainty_khz": (
                            standard_uncertainty.tolist() if standard_uncertainty is not None else None),
                        "q_only_reported_uncertainty_components": [
                            {"nuclear_component": item.model_dump(mode="json"),
                             "coupling_tensor_magnitude_khz": (np.abs(sensitivity) * item.magnitude_millibarn).tolist(),
                             "principal_coupling_magnitudes_khz": (factor * np.abs(np.asarray(
                                 principal["principal_values_atomic_units"])) * item.magnitude_millibarn).tolist()}
                            for item in nucleus.q_reported_uncertainty_components],
                        "q_reported_components_combination_policy": "Uncombined source-reported magnitudes; no independence, coverage or standard uncertainty inferred",
                        "q_uncertainty_propagation": (
                            "Declared k=1 Q-only standard uncertainty; tensor components share the same scalar Q"
                            if standard_uncertainty is not None else
                            "Source-reported nuclear uncertainty retained without inferred coverage, distribution or standard error bars"),
                        "efg_printing_component_absolute_bound_khz": (abs(factor *
                            nucleus.signed_q_millibarn) * bound).tolist()})
    return {"conversion_factor": MATRIX_QUADRUPOLE_FACTOR,
            "conversion_factor_units": MATRIX_QUADRUPOLE_FACTOR_UNITS,
            "conversion_factor_source": MATRIX_QUADRUPOLE_FACTOR_SOURCE,
            "conversion_factor_policy": "legacy matrix value retained exactly; no claim of exact SI metrology",
            "couplings": results, "native_execution_verified": False,
            "nuclear_data_independently_verified": False,
            "full_uncertainty_available": False,
            "limitations": ["Nuclear citations and signed values are explicit caller declarations, not independently verified here",
                            "Where explicitly supplied, Q-only k=1 standard uncertainty is fully correlated across tensor components",
                            "Source-reported nuclear uncertainty is retained verbatim; no standard error bars or statistical coverage are inferred",
                            "EFG printing bounds exclude electronic-structure, basis, vibrational and legacy-factor error",
                            "EFG printing bounds exclude uncertainty of inferred coordinate rotations and isotope/geometry inertia axes",
                            "Fixed-geometry electronic tensor; no vibrational averaging or geometry optimization claim"]}


def validate_quadrupole_targets(molecule: Molecule, nuclei: list[NuclearQuadrupoleMoment]) -> None:
    """Validate explicit target identity before spending a native budget."""
    if len({item.atom_id for item in nuclei}) != len(nuclei):
        raise ValueError("Nuclear quadrupole targets must be unique")
    for item in nuclei:
        if item.atom_id not in molecule.atom_ids:
            raise ValueError("Nuclear quadrupole target is absent from the molecule")
        index = molecule.atom_ids.index(item.atom_id)
        if molecule.symbols[index] != item.symbol or molecule.isotopes[index] != item.mass_number:
            raise ValueError("Nuclear Q requires the exact explicitly declared molecular isotope")


def inertial_quadrupole_couplings(molecule: Molecule, cartesian_couplings: dict[str, Any]) -> dict[str, Any]:
    """Rigid-isotope inertial axes, withholding unresolved degenerate axes.

    Every isotope must be explicit. This is a fixed-geometry rigid inertial
    frame; no vibrational correction, measured B0 or native default mass is used.
    Off-diagonal signs depend on eigenvector signs and are declared as such.
    """
    from .chemistry import atomic_data_provenance, resolved_masses

    targets = [NuclearQuadrupoleMoment.model_validate(item["nuclear_data"])
               for item in cartesian_couplings["couplings"]]
    validate_quadrupole_targets(molecule, targets)
    for item, target in zip(cartesian_couplings["couplings"], targets, strict=True):
        if item["atom_id"] != target.atom_id or item["atom_index"] != molecule.atom_ids.index(target.atom_id):
            raise ValueError("Inertial nuclear quadrupole output changed the indexed target identity")
    masses, records = resolved_masses(molecule, isotope_policy="require_explicit")
    xyz = np.asarray(molecule.coordinates, dtype=float)
    xyz = xyz - np.average(xyz, axis=0, weights=masses)
    inertia = sum(mass * (np.dot(vector, vector) * np.eye(3) - np.outer(vector, vector))
                  for mass, vector in zip(masses, xyz, strict=True))
    moments, axes = np.linalg.eigh(inertia)
    threshold = max(float(np.max(np.abs(moments))), 1.) * 1e-10
    resolved = min(abs(moments[i] - moments[j]) for i in range(3) for j in range(i)) > threshold
    if np.linalg.det(axes) < 0:
        axes[:, -1] *= -1
    outputs = []
    for item, target in zip(cartesian_couplings["couplings"], targets, strict=True):
        tensor = np.asarray(item["coupling_tensor_khz"], dtype=float)
        bounds = np.asarray(item["efg_printing_component_absolute_bound_khz"], dtype=float)
        sensitivity = np.asarray(item["q_sensitivity_khz_per_millibarn"], dtype=float)
        transformed = axes.T @ tensor @ axes if resolved else None
        transformed_sensitivity = axes.T @ sensitivity @ axes if resolved else None
        outputs.append({"atom_id": item["atom_id"], "atom_index": item["atom_index"],
            "coupling_tensor_abc_khz": transformed.tolist() if resolved else None,
            "chi_aa_bb_cc_khz": np.diag(transformed).tolist() if resolved else None,
            "q_sensitivity_abc_khz_per_millibarn": transformed_sensitivity.tolist() if resolved else None,
            "q_only_component_standard_uncertainty_abc_khz": (np.abs(transformed_sensitivity) *
                target.q_standard_uncertainty_millibarn).tolist()
                if resolved and target.q_standard_uncertainty_millibarn is not None else None,
            "q_uncertainty_convention": target.uncertainty_convention,
            "q_reported_uncertainty_millibarn": target.q_reported_uncertainty_millibarn,
            "q_only_reported_uncertainty_components": [
                {"nuclear_component": component.model_dump(mode="json"),
                 "coupling_tensor_magnitude_abc_khz": (np.abs(transformed_sensitivity) *
                     component.magnitude_millibarn).tolist() if resolved else None}
                for component in target.q_reported_uncertainty_components],
            "q_reported_components_combination_policy": "Uncombined source-reported magnitudes; no independence, coverage or standard uncertainty inferred",
            "q_reported_uncertainty_policy": target.q_reported_uncertainty_policy,
            "efg_printing_component_absolute_bound_abc_khz": (np.abs(axes).T @ bounds @
                np.abs(axes)).tolist() if resolved else None})
    return {"frame": "fixed-geometry rigid inertial axes a,b,c ordered by increasing moments",
            "mass_policy": "require_explicit", "isotope_provenance": records,
            "atomic_data": atomic_data_provenance(), "moments_amu_angstrom2": moments.tolist(),
            "axes_columns_in_requested_cartesian_frame": axes.tolist() if resolved else None,
            "axes_resolved": bool(resolved), "axis_signs_observable": False,
            "axis_uncertainty_propagated": False,
            "axis_sign_policy": "Right-handed representative; individual signs are arbitrary; off-diagonal signs are convention-dependent",
            "degeneracy_threshold_amu_angstrom2": threshold,
            "couplings": outputs, "vibrational_correction_applied": False,
            "measured_rotational_frame": False}


def first_order_quadrupole_output(molecule: Molecule, efg: dict[str, Any],
                                  nuclei: list[NuclearQuadrupoleMoment], frame: str,
                                  operator_authority: CfourOperatorAuthority | None = None) -> tuple[dict | None, list[str]]:
    """Admit exact-build operator evidence or retain conditional conversion.

    Computational coverage is distinct from independent nuclear-data review,
    correlated accuracy, native campaign acceptance and full release readiness.
    A persisted dictionary/boolean alone never authorizes the operator.
    """
    if frame not in {"requested-cartesian", "rigid-inertial"}:
        raise ValueError("Unknown nuclear quadrupole tensor frame")
    validate_quadrupole_targets(molecule, nuclei)
    verified_operator = validate_operator_observation(efg, operator_authority, molecule)
    couplings, reasons = None, []
    if not nuclei:
        reasons.append("Explicit indexed isotope, signed nuclear Q, spin, sourced uncertainty interpretation and independent citations are required for chi")
    if not verified_operator and efg.get("native_convention_declaration") is None:
        reasons.append("The native EFG unit/sign convention is unresolved")
    elif nuclei:
        declaration = (CfourEfgConventionDeclaration.model_validate(efg["native_convention_declaration"])
                       if not verified_operator else None)
        if efg.get("units") != (declaration.native_units if declaration is not None
                                else "atomic-unit-electric-field-gradient"):
            raise ValueError("Native EFG units differ from the declared version-bound convention")
        couplings = nuclear_quadrupole_couplings(molecule, efg["tensors_native_units"],
                    efg["component_rounding_bounds_native_units"], nuclei)
        couplings["unit_sign_authority"] = ("Compiled exact-build empirical RHF conformance; correlated same-xprops operator inference"
            if verified_operator else "Explicit caller-reviewed declaration; native unit/sign independently unverified")
        couplings["native_unit_sign_independently_verified"] = verified_operator
        couplings["validity"] = "human-review"
        couplings["definition"] = ("chi=eQV/h using admitted exact-build empirical EFG convention with inferred correlated operator and explicitly sourced caller nuclear data"
            if verified_operator else "Conditional chi=eQV/h using the explicitly declared, independently unverified native EFG convention")
        if verified_operator:
            couplings["runtime_operator_evidence"] = operator_authority.metadata()
        if frame == "rigid-inertial":
            couplings["inertial_frame"] = inertial_quadrupole_couplings(molecule, couplings)
            if not couplings["inertial_frame"]["axes_resolved"]:
                reasons.append("Requested rigid-inertial chi frame is unresolved because its inertia axes are degenerate")
    if not verified_operator:
        reasons.append("Admitted exact-build CFOUR EFG operator authority is required; caller declarations cannot certify the full row")
    return couplings, reasons
