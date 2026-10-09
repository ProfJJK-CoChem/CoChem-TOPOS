"""Sourced nuclear uncertainty semantics; authentic native parsing stays conditional.

No native calculation is executed. Stone's published Q is a supplied example,
not a default or automatic independent nuclear-data verification.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from topos.cfour_properties import (
    MATRIX_QUADRUPOLE_FACTOR,
    CfourEfgConventionDeclaration,
    NuclearQuadrupoleMoment,
    first_order_quadrupole_output,
    inertial_quadrupole_couplings,
    nuclear_quadrupole_couplings,
)
from topos.external_engines import ExternalProtocol, cfour_input, parse_cfour_output
from topos.matrix_workflow import MatrixInputs
from topos.models import Molecule, ResourceLimits

FIXTURE = Path(__file__).parent / "fixtures/cfour_first_order_2_1"
POLICY = ("Stone 2016 pp.3-4 reported parenthetic error and adoption/rounding policy; "
          "a k=1 standard uncertainty or probability distribution is not established")


def source(locator="Table 1, printed/PDF page 7, ground-state 2H row"):
    return {"citation": "N. J. Stone, Table of nuclear electric quadrupole moments, ADND Tables 111-112 (2016)",
            "identifier": "https://doi.org/10.1016/j.adt.2015.12.002", "locator": locator}


def reported_data(**changes):
    return dict(atom_id="atom-1", symbol="H", mass_number=2, nuclear_spin_twice=2,
                signed_q_millibarn=2.86, uncertainty_convention="reported-source-uncertainty",
                q_reported_uncertainty_millibarn=.02, q_reported_uncertainty_policy=POLICY,
                spin_source=source(), q_source=source(),
                q_uncertainty_source=source("Table 1 page 7, +0.00286(2) barns; error policies pp.3-4")) | changes


def molecule():
    rows = (FIXTURE / "native-ZMAT.inp").read_text().splitlines()[1:4]
    return Molecule(symbols=[row.split()[0] for row in rows], isotopes=[16, 2, 2],
                    coordinates=[[float(value) for value in row.split()[1:]] for row in rows])


def tensors():
    # Pure mathematical traceless tensors, not electronic-structure evidence.
    return np.array([np.diag([-.1, -.2, .3]), np.diag([-.3, -.2, .5]), np.diag([-.2, -.4, .6])])


def test_reported_source_uncertainty_round_trips_typed_matrix_input_without_standard_relabeling():
    inputs = MatrixInputs.model_validate_json(json.dumps({"cfour_quadrupole_moments": [reported_data()]}))
    nucleus = inputs.cfour_quadrupole_moments[0]
    assert nucleus.q_reported_uncertainty_millibarn == .02
    assert nucleus.q_reported_uncertainty_policy == POLICY
    assert nucleus.q_standard_uncertainty_millibarn is None
    assert nucleus.uncertainty_convention == "reported-source-uncertainty"
    assert NuclearQuadrupoleMoment.model_validate_json(nucleus.model_dump_json()) == nucleus


def test_reported_source_uncertainty_retains_signed_coupling_and_sensitivity_with_null_standard_errors():
    nucleus = NuclearQuadrupoleMoment(**reported_data())
    raw = tensors()
    result = nuclear_quadrupole_couplings(molecule(), raw, np.zeros_like(raw), [nucleus])
    output = result["couplings"][0]
    np.testing.assert_allclose(output["coupling_tensor_khz"], 234.96474 * 2.86 * raw[1])
    np.testing.assert_allclose(output["q_sensitivity_khz_per_millibarn"], MATRIX_QUADRUPOLE_FACTOR * raw[1])
    assert output["nuclear_data"]["q_reported_uncertainty_millibarn"] == .02
    assert output["nuclear_data"]["q_reported_uncertainty_policy"] == POLICY
    assert output["q_only_component_standard_uncertainty_khz"] is None
    assert "without inferred coverage" in output["q_uncertainty_propagation"]
    assert result["full_uncertainty_available"] is False
    assert result["nuclear_data_independently_verified"] is False
    assert result["native_execution_verified"] is False
    inertial = inertial_quadrupole_couplings(molecule(), result)
    assert inertial["axes_resolved"] is True
    rotated = inertial["couplings"][0]
    assert rotated["q_only_component_standard_uncertainty_abc_khz"] is None
    assert rotated["q_reported_uncertainty_millibarn"] == .02
    assert rotated["q_reported_uncertainty_policy"] == POLICY
    axes = np.asarray(inertial["axes_columns_in_requested_cartesian_frame"])
    np.testing.assert_allclose(rotated["coupling_tensor_abc_khz"], axes.T @ output["coupling_tensor_khz"] @ axes)


def test_uncertainty_interpretation_changes_no_central_value_and_standard_branch_still_propagates():
    reported = NuclearQuadrupoleMoment(**reported_data())
    standard = NuclearQuadrupoleMoment(**reported_data(
        uncertainty_convention="standard-uncertainty-k1", q_reported_uncertainty_millibarn=None,
        q_reported_uncertainty_policy=None, q_standard_uncertainty_millibarn=.02,
        q_uncertainty_source={"citation": "Mathematical k=1 uncertainty example only, not a Stone interpretation",
            "identifier": "urn:topos:mathematical-k1-test-only", "locator": "declared standard uncertainty"}))
    raw = tensors()
    first = nuclear_quadrupole_couplings(molecule(), raw, np.zeros_like(raw), [reported])
    second = nuclear_quadrupole_couplings(molecule(), raw, np.zeros_like(raw), [standard])
    np.testing.assert_array_equal(first["couplings"][0]["coupling_tensor_khz"], second["couplings"][0]["coupling_tensor_khz"])
    np.testing.assert_allclose(second["couplings"][0]["q_only_component_standard_uncertainty_khz"],
                               np.abs(raw[1]) * 234.96474 * .02)
    inertial = inertial_quadrupole_couplings(molecule(), second)
    sensitivity = np.asarray(inertial["couplings"][0]["q_sensitivity_abc_khz_per_millibarn"])
    np.testing.assert_allclose(inertial["couplings"][0]["q_only_component_standard_uncertainty_abc_khz"],
                               np.abs(sensitivity) * .02)


@pytest.mark.parametrize("changes", [
    {"q_reported_uncertainty_millibarn": None},
    {"q_reported_uncertainty_millibarn": -.02},
    {"q_reported_uncertainty_millibarn": False},
    {"q_reported_uncertainty_millibarn": True},
    {"q_reported_uncertainty_millibarn": float("inf")},
    {"q_reported_uncertainty_millibarn": float("nan")},
    {"q_reported_uncertainty_policy": None},
    {"q_reported_uncertainty_policy": "        "},
    {"q_reported_uncertainty_policy": ""},
    {"q_uncertainty_source": None},
    {"q_standard_uncertainty_millibarn": .02},
    {"uncertainty_convention": "standard-uncertainty-k1", "q_standard_uncertainty_millibarn": .02},
    {"uncertainty_convention": "reported-source-uncertainty-k1"},
])
def test_ambiguous_missing_nonfinite_or_boolean_reported_uncertainty_is_rejected(changes):
    with pytest.raises(ValidationError):
        MatrixInputs.model_validate({"cfour_quadrupole_moments": [reported_data(**changes)]})


@pytest.mark.parametrize("changes", [
    {},
    {"q_standard_uncertainty_millibarn": False},
    {"q_standard_uncertainty_millibarn": True},
    {"q_standard_uncertainty_millibarn": .02, "q_reported_uncertainty_millibarn": .02},
    {"q_standard_uncertainty_millibarn": .02, "q_reported_uncertainty_policy": POLICY},
])
def test_standard_branch_requires_explicit_numeric_uncertainty_and_rejects_reported_fields(changes):
    data = reported_data(uncertainty_convention="standard-uncertainty-k1",
                         q_reported_uncertainty_millibarn=None, q_reported_uncertainty_policy=None)
    with pytest.raises(ValidationError):
        NuclearQuadrupoleMoment(**(data | changes))


def test_authentic_correlated_acquisition_with_reported_nuclear_error_remains_conditional():
    review_source = {"citation": "Mathematical conditional native-convention test only; no physical authority assertion",
                    "identifier": "urn:topos:mathematical-convention-test-only", "locator": "explicit conditional declaration"}
    declaration = CfourEfgConventionDeclaration(source=review_source, reviewed_by="mathematical-test",
        reviewed_at="2026-01-01T00:00:00Z", review_reason="Test conditional conversion only, not native convention certification")
    protocol = ExternalProtocol(engine="cfour", engine_version="2.1", operation="first-order-properties",
        method="CCSD(T)", orbital_basis="PVTZ", frozen_core=False, efg_convention=declaration)
    parsed = parse_cfour_output((FIXTURE / "output.stdout").read_text(), molecule(), protocol,
        dipol=(FIXTURE / "DIPOL.out").read_text(), efg=(FIXTURE / "EFG.out").read_text())
    output, reasons = first_order_quadrupole_output(molecule(), parsed["efg_observation"],
        [NuclearQuadrupoleMoment(**reported_data())], "rigid-inertial")
    assert output["couplings"][0]["q_only_component_standard_uncertainty_khz"] is None
    assert output["inertial_frame"]["couplings"][0]["q_only_component_standard_uncertainty_abc_khz"] is None
    assert output["native_unit_sign_independently_verified"] is False
    assert output["validity"] == "human-review"
    assert reasons and any("caller declarations cannot certify" in reason for reason in reasons)


def component_data(**changes):
    # Mathematical magnitudes exercise separate reported errors, not real Q data.
    declared = {"citation": "Mathematical separate-error contract test; no measured nuclear-data assertion",
                "identifier": "urn:topos:mathematical-error-components-only", "locator": "two symbolic errors"}
    components = [{"label": "estimated-theory-error", "magnitude_millibarn": .00015,
                   "interpretation": "Estimated omitted terms; no probability distribution established", "source": declared},
                  {"label": "experimental-input-error", "magnitude_millibarn": .00018,
                   "interpretation": "Reported experimental input error; coverage not established", "source": declared}]
    return reported_data(q_reported_uncertainty_millibarn=None,
        q_reported_uncertainty_components=components,
        q_reported_uncertainty_policy="Retain both reported errors separately; no combination or k=1 interpretation",
        q_uncertainty_source=declared) | changes


def test_separate_reported_errors_round_trip_without_scalar_combination_or_standard_relabeling():
    inputs = MatrixInputs.model_validate({"cfour_quadrupole_moments": [component_data()]})
    target = inputs.cfour_quadrupole_moments[0]
    assert NuclearQuadrupoleMoment.model_validate_json(target.model_dump_json()) == target
    assert [item.magnitude_millibarn for item in target.q_reported_uncertainty_components] == [.00015, .00018]
    assert target.q_standard_uncertainty_millibarn is target.q_reported_uncertainty_millibarn is None
    assert [item.source.locator for item in target.q_reported_uncertainty_components] == ["two symbolic errors"] * 2


@pytest.mark.parametrize("mutation", ["empty", "scalar-mix", "standard-mix", "duplicate-label",
    "blank-label", "blank-interpretation", "missing-source", "negative", "boolean", "nonfinite"])
def test_ambiguous_or_incomplete_component_declarations_are_rejected(mutation):
    data = component_data()
    components = data["q_reported_uncertainty_components"]
    if mutation == "empty":
        data["q_reported_uncertainty_components"] = []
    elif mutation == "scalar-mix":
        data["q_reported_uncertainty_millibarn"] = .00023
    elif mutation == "standard-mix":
        data.update(uncertainty_convention="standard-uncertainty-k1", q_standard_uncertainty_millibarn=.00023,
                    q_reported_uncertainty_policy=None)
    elif mutation == "duplicate-label":
        components[1]["label"] = " ESTIMATED-THEORY-ERROR "
    elif mutation == "blank-label":
        components[0]["label"] = " "
    elif mutation == "blank-interpretation":
        components[0]["interpretation"] = "        "
    elif mutation == "missing-source":
        del components[1]["source"]
    else:
        components[0]["magnitude_millibarn"] = {"negative": -.1, "boolean": False, "nonfinite": float("inf")}[mutation]
    with pytest.raises(ValidationError):
        NuclearQuadrupoleMoment(**data)


def test_each_reported_error_propagates_individually_in_cartesian_principal_and_isotope_inertial_frames():
    target = NuclearQuadrupoleMoment(**component_data())
    raw = tensors()
    cartesian = nuclear_quadrupole_couplings(molecule(), raw, np.zeros_like(raw), [target])
    output = cartesian["couplings"][0]
    assert output["q_only_component_standard_uncertainty_khz"] is None
    assert cartesian["full_uncertainty_available"] is False
    inertial = inertial_quadrupole_couplings(molecule(), cartesian)
    rotated = inertial["couplings"][0]
    assert rotated["q_only_component_standard_uncertainty_abc_khz"] is None
    sensitivity = np.asarray(rotated["q_sensitivity_abc_khz_per_millibarn"])
    for component, entry, rotated_entry in zip(target.q_reported_uncertainty_components,
            output["q_only_reported_uncertainty_components"], rotated["q_only_reported_uncertainty_components"], strict=True):
        assert entry["nuclear_component"] == rotated_entry["nuclear_component"] == component.model_dump(mode="json")
        np.testing.assert_allclose(entry["coupling_tensor_magnitude_khz"],
                                   234.96474 * np.abs(raw[1]) * component.magnitude_millibarn)
        np.testing.assert_allclose(entry["principal_coupling_magnitudes_khz"],
                                   234.96474 * np.array([.2, .3, .5]) * component.magnitude_millibarn)
        np.testing.assert_allclose(rotated_entry["coupling_tensor_magnitude_abc_khz"],
                                   np.abs(sensitivity) * component.magnitude_millibarn)
    assert "Uncombined" in output["q_reported_components_combination_policy"]
    assert "Uncombined" in rotated["q_reported_components_combination_policy"]


def test_deuterium_uses_hydrogen_electronic_input_and_explicit_mass_aware_inertial_axes():
    from topos.chemistry import resolved_masses

    heavy = molecule()
    heavy.isotopes = [16, 2, 1]
    light = heavy.model_copy(deep=True)
    light.isotopes = [16, 1, 1]
    protocol = ExternalProtocol(engine="cfour", engine_version="2.1", operation="first-order-properties",
                                method="CCSD(T)", orbital_basis="PVTZ", frozen_core=False)
    resources = ResourceLimits(threads=2, memory_mb=4096)
    assert cfour_input(heavy, protocol, resources) == cfour_input(light, protocol, resources)
    native = cfour_input(heavy, protocol, resources)
    assert native.splitlines()[2].startswith("H ") and "BASIS=PVTZ" in native
    assert "PROPS=FIRST_ORDER" in native and "FROZEN_CORE=OFF" in native
    target = NuclearQuadrupoleMoment(**component_data())
    cartesian = nuclear_quadrupole_couplings(heavy, tensors(), np.zeros((3, 3, 3)), [target])
    inertial = inertial_quadrupole_couplings(heavy, cartesian)
    masses, records = resolved_masses(heavy, isotope_policy="require_explicit")
    xyz = np.asarray(heavy.coordinates)
    centered = xyz - np.average(xyz, axis=0, weights=masses)
    expected = sum(mass * (np.dot(r, r) * np.eye(3) - np.outer(r, r)) for mass, r in zip(masses, centered, strict=True))
    axes = np.asarray(inertial["axes_columns_in_requested_cartesian_frame"])
    np.testing.assert_allclose(axes.T @ expected @ axes, np.diag(inertial["moments_amu_angstrom2"]), atol=1e-14)
    assert records == inertial["isotope_provenance"]
    assert records[1]["mass_number"] == 2 and records[1]["mass_u"] > 2
    light_masses, _ = resolved_masses(light, isotope_policy="require_explicit")
    light_centered = xyz - np.average(xyz, axis=0, weights=light_masses)
    light_inertia = sum(mass * (np.dot(r, r) * np.eye(3) - np.outer(r, r))
                        for mass, r in zip(light_masses, light_centered, strict=True))
    assert np.max(np.abs(axes.T @ light_inertia @ axes - np.diag(np.diag(axes.T @ light_inertia @ axes)))) > .01


def test_unresolved_inertial_axes_retain_component_sources_but_withhold_rotated_magnitudes():
    linear = Molecule(symbols=["H", "H"], isotopes=[2, 1], coordinates=[[0, 0, -.4], [0, 0, .4]])
    target = NuclearQuadrupoleMoment(**component_data(atom_id="atom-0"))
    cartesian = nuclear_quadrupole_couplings(linear, [np.diag([-1., -1., 2.])] * 2,
                                            np.zeros((2, 3, 3)), [target])
    inertial = inertial_quadrupole_couplings(linear, cartesian)
    assert inertial["axes_resolved"] is False
    for component, entry in zip(target.q_reported_uncertainty_components,
            inertial["couplings"][0]["q_only_reported_uncertainty_components"], strict=True):
        assert entry["nuclear_component"] == component.model_dump(mode="json")
        assert entry["coupling_tensor_magnitude_abc_khz"] is None
