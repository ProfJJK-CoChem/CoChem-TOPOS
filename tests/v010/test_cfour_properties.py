"""Mathematical EFG tests only: no fabricated CFOUR output or native certification."""
from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from topos.cfour_properties import (
    MATRIX_QUADRUPOLE_FACTOR,
    NuclearQuadrupoleMoment,
    nuclear_quadrupole_couplings,
    principal_efg,
    rotate_efg_tensors,
    validate_efg_tensors,
)
from topos.models import Molecule


def water():
    return Molecule(symbols=["O", "H", "H"], isotopes=[17, 1, 1],
                    coordinates=[[0, 0, 0], [.8, 0, .6], [-.8, 0, .6]])


def moment(**changes):
    # Deliberately mathematical nuclear data, not a measured 17O moment.
    source = {"citation": "Mathematical test declaration; no physical nuclear-data assertion",
              "identifier": "urn:topos:mathematical-test-only", "locator": "test symbol Q"}
    values = dict(atom_id="atom-0", symbol="O", mass_number=17, nuclear_spin_twice=5,
                  signed_q_millibarn=-2., q_standard_uncertainty_millibarn=.1,
                  spin_source=source, q_source=source, q_uncertainty_source=source)
    return NuclearQuadrupoleMoment(**(values | changes))


def tensors():
    # Hessians of a unit-charge Coulomb potential at arbitrary nonzero vectors;
    # these are mathematical tensors, not molecular EFG calculations.
    vectors = np.array([[1., 2., 3.], [-2., 1., 1.], [3., -2., 1.]])
    return np.array([3 * np.outer(r, r) / np.linalg.norm(r)**5 - np.eye(3) / np.linalg.norm(r)**3
                     for r in vectors])


def rotation():
    axis = np.array([1., 2., 3.]) / np.sqrt(14)
    cross = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(.47) * cross + (1 - np.cos(.47)) * cross @ cross


def test_tensor_covariance_and_translation_invariance_in_requested_indexed_frame():
    molecule, native, q = water(), np.asarray(water().coordinates), rotation()
    molecule.coordinates = (native @ q + [3., -2., 1.]).tolist()
    raw = tensors()
    out = rotate_efg_tensors(molecule, molecule.symbols, native, raw, np.zeros_like(raw))
    np.testing.assert_allclose(out["tensors_atomic_units"], q.T @ raw @ q, atol=1e-15)
    np.testing.assert_allclose(out["proper_rotation_native_to_requested"], q, atol=1e-15)
    assert out["atom_ids"] == molecule.atom_ids
    assert out["isotopes"] == [17, 1, 1]
    assert out["native_execution_verified"] is False
    for first, second in zip(raw, out["tensors_atomic_units"], strict=True):
        np.testing.assert_allclose(np.linalg.eigvalsh(first), np.linalg.eigvalsh(second), atol=1e-15)


def test_observed_rounding_bounds_transform_conservatively_without_losing_raw_components():
    molecule = water()
    molecule.coordinates = (np.asarray(molecule.coordinates) @ rotation()).tolist()
    raw = np.around(tensors(), 7)
    bounds = np.full_like(raw, 5e-8)
    out = rotate_efg_tensors(molecule, molecule.symbols, water().coordinates, raw, bounds)
    np.testing.assert_array_equal(out["raw_tensors_native_frame_atomic_units"], raw)
    exact = rotation().T @ tensors() @ rotation()
    assert np.all(np.abs(np.asarray(out["tensors_atomic_units"]) - exact) <=
                  np.asarray(out["component_rounding_bounds_atomic_units"]))


@pytest.mark.parametrize("mutation", ["nonsymmetric", "trace", "shape", "nonfinite", "negative-bound", "loose-bound"])
def test_invalid_tensor_or_fitted_tolerance_is_rejected(mutation):
    raw, bounds = tensors(), np.zeros((3, 3, 3))
    if mutation == "nonsymmetric":
        raw[0, 1, 2] += .1
    elif mutation == "trace":
        raw[0, 0, 0] += .1
    elif mutation == "shape":
        raw = raw[:2]
    elif mutation == "nonfinite":
        raw[0, 0, 0] = np.nan
    elif mutation == "negative-bound":
        bounds[0, 0, 0] = -1e-8
    else:
        bounds[:] = .01
    with pytest.raises(ValueError):
        validate_efg_tensors(raw, bounds, 3)


def test_native_atom_order_and_changed_geometry_are_rejected():
    molecule = water()
    with pytest.raises(ValueError, match="indexed element"):
        rotate_efg_tensors(molecule, ["H", "O", "H"], molecule.coordinates, tensors(), np.zeros((3, 3, 3)))
    changed = np.asarray(molecule.coordinates)
    changed[1, 0] += .1
    with pytest.raises(ValueError, match="indexed geometry"):
        rotate_efg_tensors(molecule, molecule.symbols, changed, tensors(), np.zeros((3, 3, 3)))


def test_improper_reflection_cannot_define_an_efg_frame():
    native = np.array([[0., 0., 0.], [1., 1., 1.], [-1., -1., 1.], [-1., 1., -1.], [1., -1., -1.]])
    molecule = Molecule(symbols=["C", "H", "H", "H", "H"], coordinates=(native * [-1., 1., 1.]).tolist())
    with pytest.raises(ValueError, match="improper reflection"):
        rotate_efg_tensors(molecule, molecule.symbols, native, np.zeros((5, 3, 3)), np.zeros((5, 3, 3)))


def test_axial_linear_tensors_are_rotation_invariant_but_azimuthal_ones_are_rejected():
    native = np.array([[0., 0., -.4], [0., 0., .4]])
    q = rotation()
    molecule = Molecule(symbols=["H", "H"], coordinates=(native @ q).tolist())
    raw = np.array([np.diag([-1., -1., 2.])] * 2)
    out = rotate_efg_tensors(molecule, molecule.symbols, native, raw, np.zeros_like(raw))
    np.testing.assert_allclose(out["tensors_atomic_units"], q.T @ raw @ q, atol=1e-14)
    raw[0] = np.diag([-1., -.5, 1.5])
    with pytest.raises(ValueError, match="unresolved EFG tensor frame"):
        rotate_efg_tensors(molecule, molecule.symbols, native, raw, np.zeros_like(raw))


def test_monatomic_frame_accepts_zero_tensor_and_rejects_orientation_dependent_tensor():
    molecule = Molecule(symbols=["He"], coordinates=[[4., 5., 6.]])
    raw = np.zeros((1, 3, 3))
    rotate_efg_tensors(molecule, molecule.symbols, [[0., 0., 0.]], raw, raw)
    with pytest.raises(ValueError, match="unresolved EFG tensor frame"):
        rotate_efg_tensors(molecule, molecule.symbols, [[0., 0., 0.]], [np.diag([-1., -1., 2.])], raw)


@pytest.mark.parametrize("diagonal,eta,axes", [([-1., -1., 2.], 0., False),
    ([-1.2, -.8, 2.], .2, True), ([-1., 0., 1.], 1., False), ([0., 0., 0.], None, False)])
def test_principal_value_ordering_and_degenerate_axis_policy(diagonal, eta, axes):
    out = principal_efg(np.diag(diagonal), np.zeros((3, 3)))
    values = out["principal_values_atomic_units"]
    assert abs(values[0]) <= abs(values[1]) <= abs(values[2])
    assert out["eta"] == pytest.approx(eta) if eta is not None else out["eta"] is None
    assert out["axes_unique_up_to_sign"] is axes
    assert (out["principal_axes_columns"] is not None) is axes
    assert out["axis_signs_observable"] is False


def test_nearly_degenerate_axes_are_not_claimed_resolved_beyond_print_precision():
    out = principal_efg(np.diag([-1.-1e-8, -1.+1e-8, 2.]), np.full((3, 3), 5e-7))
    assert out["principal_axes_columns"] is None


def test_signed_matrix_factor_and_nuclear_uncertainty_are_preserved():
    raw = tensors()
    negative = nuclear_quadrupole_couplings(water(), raw, np.zeros_like(raw), [moment()])
    positive = nuclear_quadrupole_couplings(water(), raw, np.zeros_like(raw), [moment(signed_q_millibarn=2.)])
    minus, plus = negative["couplings"][0], positive["couplings"][0]
    assert MATRIX_QUADRUPOLE_FACTOR == 234.96474
    np.testing.assert_allclose(minus["coupling_tensor_khz"], -2 * 234.96474 * raw[0])
    np.testing.assert_allclose(minus["coupling_tensor_khz"], -np.asarray(plus["coupling_tensor_khz"]))
    np.testing.assert_allclose(minus["q_only_component_standard_uncertainty_khz"], np.abs(raw[0]) * 234.96474 * .1)
    assert negative["native_execution_verified"] is False
    assert negative["nuclear_data_independently_verified"] is False
    assert negative["full_uncertainty_available"] is False
    assert "no claim of exact SI" in negative["conversion_factor_policy"]


@pytest.mark.parametrize("change", [dict(nuclear_spin_twice=1), dict(nuclear_spin_twice=2.5),
    dict(q_standard_uncertainty_millibarn=-.1), dict(signed_q_millibarn=float("inf")),
    dict(q_convention="isotope-mass-derived"), dict(q_uncertainty_source=None), dict(spin_source=None)])
def test_unsupported_or_missing_nuclear_physics_is_rejected(change):
    with pytest.raises(ValidationError):
        moment(**change)


@pytest.mark.parametrize("mutation", ["unspecified-isotope", "changed-isotope", "wrong-element", "absent-atom", "duplicate", "empty"])
def test_coupling_requires_explicit_exact_unique_nuclear_targets(mutation):
    molecule, nucleus = water(), moment()
    nuclei = [nucleus]
    if mutation == "unspecified-isotope":
        molecule.isotopes = [None, 1, 1]
    elif mutation == "changed-isotope":
        molecule.isotopes = [18, 1, 1]
    elif mutation == "wrong-element":
        nuclei = [moment(symbol="N")]
    elif mutation == "absent-atom":
        nuclei = [moment(atom_id="absent")]
    elif mutation == "duplicate":
        nuclei = [nucleus, nucleus]
    else:
        nuclei = []
    with pytest.raises(ValueError):
        nuclear_quadrupole_couplings(molecule, tensors(), np.zeros((3, 3, 3)), nuclei)
