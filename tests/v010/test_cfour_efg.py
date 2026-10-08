"""Genuine R4 offline properties and explicitly mathematical nuclear conversion.

The original hosted TOPOS component failed on missing parser dependencies. These
tests parse its retained successful native subprogram output; no native engine
is executed and no current-source/full-matrix scientific acceptance is claimed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from topos.cfour_artifacts import native_text
from topos.cfour_efg import parse_cfour_efg, verify_cfour_property_recovery
from topos.cfour_properties import (
    MATRIX_QUADRUPOLE_FACTOR,
    CfourEfgConventionDeclaration,
    NuclearQuadrupoleMoment,
    first_order_quadrupole_output,
    inertial_quadrupole_couplings,
    nuclear_quadrupole_couplings,
    validate_quadrupole_targets,
)
from topos.engines import EngineParseError
from topos.external_engines import ExternalProtocol, parse_cfour_output
from topos.matrix_workflow import MatrixInputs, _available_inputs
from topos.models import Molecule, RunRequest
from topos.storage import IntegrityError

FIXTURE = Path(__file__).parent / "fixtures/cfour_first_order_2_1"
HASHES = {"output.stdout": "ab0eb467db3af527b8c77a7f26d2a7e2004eaf2516737a74a52ec048add32586",
          "EFG.out": "7e8d0a50fb73d55e5e32725e27a19ef0a62b6af96dc523c0fe86f09b6c78f401",
          "DIPOL.out": "4f9326f65f8de0203952ce52453d03e67dd46315b2055751293bde1c48aa87e2",
          "native-ZMAT.inp": "13bf47ac8be96bfaadda6c6da75cb3ae6a4de23a79c22823f16cd06684eb0467"}


def molecule():
    rows = (FIXTURE / "native-ZMAT.inp").read_text().splitlines()[1:4]
    return Molecule(symbols=[row.split()[0] for row in rows],
                    coordinates=[[float(value) for value in row.split()[1:]] for row in rows])


def protocol(**changes):
    data = {"engine": "cfour", "engine_version": "2.1", "operation": "first-order-properties",
            "method": "CCSD(T)", "orbital_basis": "PVTZ", "frozen_core": False}
    return ExternalProtocol(**(data | changes))


def raw():
    return (FIXTURE / "output.stdout").read_text()


def observation(**changes):
    arguments = {"efg": (FIXTURE / "EFG.out").read_text(),
                 "dipol": (FIXTURE / "DIPOL.out").read_text()}
    return parse_cfour_output(raw(), molecule(), protocol(), **(arguments | changes))


def mathematical_source():
    return {"citation": "Mathematical conditional-conversion test only; no measured nuclear-data assertion",
            "identifier": "urn:topos:mathematical-conditional-only", "locator": "test symbolic Q"}


def declaration():
    return CfourEfgConventionDeclaration(source=mathematical_source(), reviewed_by="mathematical-test",
        reviewed_at="2026-01-01T00:00:00Z", review_reason="Tests conditional computation, not physical native-convention authority")


def nucleus(**changes):
    data = dict(atom_id="atom-0", symbol="O", mass_number=17, nuclear_spin_twice=5,
                signed_q_millibarn=-2., q_standard_uncertainty_millibarn=.1,
                spin_source=mathematical_source(), q_source=mathematical_source(),
                q_uncertainty_source=mathematical_source())
    return NuclearQuadrupoleMoment(**(data | changes))


def test_genuine_fixture_bytes_and_original_failed_component_provenance():
    for name, digest in HASHES.items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == digest
    proof = json.loads((FIXTURE / "provenance.json").read_text())
    assert "37717679093" in json.dumps(proof)
    assert "8bc69a26f4be4e132fcdd2ac28fba09dd4217d7e210df5e3cd1efe64bae913eb" in json.dumps(proof)


def test_authentic_indexed_correlated_efg_is_acquired_without_nuclear_q_or_unit_sign_claim():
    out = observation()
    efg = out["efg_observation"]
    assert out["energy_hartree"] == pytest.approx(-76.345753258711, abs=1e-13)
    assert efg["atom_ids"] == molecule().atom_ids and efg["isotopes"] == [None, None, None]
    assert efg["density_provenance"]["method"] == "CCSD(T)"
    assert efg["density_provenance"]["electrons"] == 10
    spans = efg["density_provenance"]["native_program_spans_utf8_bytes"]
    assert spans["xlambda"]["completion_end"] <= spans["xdens"]["invocation_start"]
    assert spans["xdens"]["completion_end"] <= spans["xprops"]["invocation_start"]
    assert efg["units"] == "native-unlabeled-EFG-components"
    assert efg["native_unit_sign_independently_verified"] is False
    assert efg["native_execution_verified"] is False
    assert efg["builtin_nuclear_chi_ignored_atom_indices"] == [2, 3]
    assert efg["raw_artifacts_sha256"]["EFG"] == HASHES["EFG.out"]
    assert efg["raw_artifacts_sha256"]["DIPOL"] == HASHES["DIPOL.out"]
    np.testing.assert_allclose(efg["tensors_native_units"][0],
        [[.42423455997454135, -.4764478323314227, .584635389424937],
         [-.47644783233142257, 1.1149943913727596, -.6127880748197606],
         [.584635389424937, -.6127880748197606, -1.5392289513473025]], atol=1e-14)
    for original, transformed in zip(efg["raw_tensors_native_frame_native_units"],
                                     efg["tensors_native_units"], strict=True):
        np.testing.assert_allclose(np.linalg.eigvalsh(original), np.linalg.eigvalsh(transformed), atol=2e-10)
    couplings, reasons = first_order_quadrupole_output(molecule(), efg, [], "requested-cartesian")
    assert couplings is None and len(reasons) == 3
    assert any("unit/sign" in reason for reason in reasons)


@pytest.mark.parametrize("mutation", ["missing", "truncated", "extra", "wrong-order", "scf-tensor", "malformed-precision", "nonfinite"])
def test_changed_native_efg_artifacts_fail_closed(mutation):
    text = (FIXTURE / "EFG.out").read_text()
    if mutation == "missing":
        text = None
    elif mutation == "truncated":
        text = "\n".join(text.splitlines()[:-1])
    elif mutation == "extra":
        text += text.splitlines()[0] + "\n"
    elif mutation == "wrong-order":
        lines = text.splitlines()
        text = "\n".join(lines[3:6] + lines[:3] + lines[6:])
    elif mutation == "scf-tensor":
        text = text.replace("1.5726315470", "1.6888731853")
    elif mutation == "malformed-precision":
        text = text.replace("1.5726315470", "1.572631547")
    else:
        text = text.replace("1.5726315470", "NaN")
    with pytest.raises(EngineParseError):
        observation(efg=text)


@pytest.mark.parametrize("mutation", ["missing-density", "wrong-density", "wrong-electrons", "density-failed",
    "props-failed", "missing-correlated", "duplicate-correlated", "wrong-atom", "duplicate-center",
    "missing-center", "missing-component", "bad-chi", "wrong-qcomp-charge", "missing-frame", "duplicate-props"])
def test_changed_genuine_property_provenance_fails_closed(mutation):
    text = raw()
    replacements = {
        "missing-density": ("CCSD(T) density and intermediates are calculated.", "Density attribution removed."),
        "wrong-density": ("CCSD(T) density and intermediates are calculated.", "CCSD density and intermediates are calculated."),
        "wrong-electrons": ("Trace of density matrix :  10.0000000000.", "Trace of density matrix :   9.0000000000."),
        "density-failed": ("--executable xdens finished with status     0", "--executable xdens finished with status     1"),
        "props-failed": ("--executable xprops finished with status     0", "--executable xprops finished with status     1"),
        "missing-correlated": ("@DRVPRP-I, Properties computed from the correlated density matrix follow.", "Correlated header removed."),
        "duplicate-correlated": ("@DRVPRP-I, Properties computed from the SCF density matrix follow.", "@DRVPRP-I, Properties computed from the correlated density matrix follow."),
        "bad-chi": ("CHIxx =       163.10023", "CHIxx =       malformed"),
        "wrong-qcomp-charge": ("O         8         0.00013423", "O         7         0.00013423"),
        "missing-frame": ("Coordinates used in calculation (QCOMP)", "Coordinate frame removed"),
    }
    if mutation in replacements:
        before, after = replacements[mutation]
        assert before in text
        text = text.replace(before, after)
    elif mutation == "duplicate-props":
        text += "\n --invoking executable--\n/native/xprops\n--executable xprops finished with status     0\n"
    else:
        start = text.index("@DRVPRP-I, Properties computed from the correlated density matrix follow.")
        before, correlated = text[:start], text[start:]
        if mutation == "wrong-atom":
            correlated = correlated.replace("Atomic charge is                     8", "Atomic charge is                     7")
        elif mutation == "duplicate-center":
            correlated = correlated.replace("Z-matrix center   2:", "Z-matrix center   1:")
        elif mutation == "missing-center":
            a = correlated.index("Z-matrix center   2:")
            b = correlated.index("Z-matrix center   3:")
            correlated = correlated[:a] + correlated[b:]
        else:
            correlated = correlated.replace("XX =    1.5726315470", "XX =    removed")
        text = before + correlated
    with pytest.raises(EngineParseError):
        parse_cfour_output(text, molecule(), protocol(), efg=(FIXTURE / "EFG.out").read_text(),
                           dipol=(FIXTURE / "DIPOL.out").read_text())


def test_scf_dipole_and_requested_pose_cannot_impersonate_correlated_native_frame():
    with pytest.raises(EngineParseError, match="correlated-density"):
        observation(dipol="-0.0007563272 -0.7979246757 -0.0000000000")
    with pytest.raises(EngineParseError, match="actual stdout QCOMP"):
        parse_cfour_efg(raw(), (FIXTURE / "EFG.out").read_text(), molecule(), molecule().coordinates,
                        engine_version="2.1", method="CCSD(T)")


@pytest.mark.parametrize("changes", [{"engine_version": "2.0"}, {"method": "CCSD"}, {"engine": "psi4"}])
def test_native_convention_cannot_be_transplanted_to_another_protocol(changes):
    with pytest.raises(ValueError):
        protocol(efg_convention=declaration(), **changes)


def test_explicit_nuclear_inputs_and_declared_convention_produce_only_conditional_chi():
    target = molecule().model_copy(update={"isotopes": [17, 1, 1]})
    parsed = parse_cfour_output(raw(), target, protocol(efg_convention=declaration()),
        efg=(FIXTURE / "EFG.out").read_text(), dipol=(FIXTURE / "DIPOL.out").read_text())
    inputs = MatrixInputs.model_validate({"cfour_quadrupole_moments": [nucleus().model_dump()],
                                          "cfour_quadrupole_frame": "rigid-inertial"})
    chi, reasons = first_order_quadrupole_output(target, parsed["efg_observation"],
        inputs.cfour_quadrupole_moments, inputs.cfour_quadrupole_frame)
    assert chi["conversion_factor"] == 234.96474 == MATRIX_QUADRUPOLE_FACTOR
    assert chi["validity"] == "human-review" and len(reasons) == 1
    assert chi["nuclear_data_independently_verified"] is False
    assert chi["inertial_frame"]["axes_resolved"] is True
    assert chi["inertial_frame"]["mass_policy"] == "require_explicit"
    expected = -2. * MATRIX_QUADRUPOLE_FACTOR * np.asarray(parsed["efg_observation"]["tensors_native_units"][0])
    np.testing.assert_allclose(chi["couplings"][0]["coupling_tensor_khz"], expected, atol=1e-10)
    # A changed user dictionary must not convert caller attribution to science authority.
    promoted = copy.deepcopy(parsed["efg_observation"])
    promoted["native_unit_sign_independently_verified"] = True
    promoted["unit_sign_authority"] = "independently verified"
    conditional, still_missing = first_order_quadrupole_output(target, promoted, [nucleus()], "requested-cartesian")
    assert still_missing
    assert conditional["native_unit_sign_independently_verified"] is False
    assert conditional["unit_sign_authority"] == "Explicit caller-reviewed declaration; native unit/sign independently unverified"


@pytest.mark.parametrize("changes", [{"atom_id": "absent"}, {"symbol": "N"}, {"mass_number": 18}])
def test_nuclear_q_target_must_match_the_declared_indexed_isotope(changes):
    target = molecule().model_copy(update={"isotopes": [17, 1, 1]})
    with pytest.raises(ValueError):
        validate_quadrupole_targets(target, [nucleus(**changes)])
    with pytest.raises(ValueError):
        validate_quadrupole_targets(molecule(), [nucleus()])


def test_recovery_reparses_retained_native_raw_files_and_rejects_rehashed_metadata(tmp_path):
    names = {"engine.stdout": "output.stdout", "DIPOL": "DIPOL.out", "EFG": "EFG.out"}
    for name, original in names.items():
        (tmp_path / name).write_bytes((FIXTURE / original).read_bytes())
    paths = [tmp_path / name for name in names]
    original = observation()
    assert verify_cfour_property_recovery(tmp_path, paths, molecule(), protocol().model_dump(), original) == original
    altered = copy.deepcopy(original)
    altered["efg_observation"]["native_unit_sign_independently_verified"] = True
    with pytest.raises(IntegrityError, match="fresh parse"):
        verify_cfour_property_recovery(tmp_path, paths, molecule(), protocol().model_dump(), altered)
    with pytest.raises(IntegrityError, match="adjacent"):
        verify_cfour_property_recovery(tmp_path, paths[:-1], molecule(), protocol().model_dump(), original)
    (tmp_path / "EFG").write_text((tmp_path / "EFG").read_text().replace("1.5726315470", "1.6888731853"))
    with pytest.raises(EngineParseError, match="correlated-density"):
        verify_cfour_property_recovery(tmp_path, paths, molecule(), protocol().model_dump(), original)


def test_isotope_rigid_axes_withhold_linear_degenerate_axes_and_refuse_unspecified_masses():
    target = molecule().model_copy(update={"isotopes": [17, 1, 1]})
    efg = parse_cfour_output(raw(), target, protocol(efg_convention=declaration()),
        efg=(FIXTURE / "EFG.out").read_text(), dipol=(FIXTURE / "DIPOL.out").read_text())["efg_observation"]
    chi, _ = first_order_quadrupole_output(target, efg, [nucleus()], "requested-cartesian")
    with pytest.raises(ValueError, match="explicit"):
        inertial_quadrupole_couplings(molecule(), chi)
    linear = Molecule(symbols=["H", "H"], isotopes=[2, 2], coordinates=[[-.4, 0, 0], [.4, 0, 0]])
    mathematical = nuclear_quadrupole_couplings(linear, [np.diag([2., -1., -1.])] * 2,
        np.zeros((2, 3, 3)), [nucleus(symbol="H", mass_number=2, nuclear_spin_twice=2)])
    result = inertial_quadrupole_couplings(linear, mathematical)
    assert result["axes_resolved"] is False
    assert result["couplings"][0]["chi_aa_bb_cc_khz"] is None


@pytest.mark.parametrize("change", [{"reviewed_by": " "}, {"reviewed_at": "2100-01-01T00:00:00Z"},
                                    {"reviewed_at": "2020-01-01T00:00:00"}])
def test_native_convention_declarations_require_real_attributed_timestamped_review(change):
    values = declaration().model_dump() | change
    with pytest.raises(ValidationError):
        CfourEfgConventionDeclaration.model_validate(values)


def test_matrix_quadrupole_requests_are_typed_and_bound_before_native_routing():
    target = molecule().model_copy(update={"isotopes": [17, 1, 1]})
    inputs = MatrixInputs(cfour_quadrupole_moments=[nucleus()])
    request = RunRequest(molecule=target, purpose="matrix", matrix_row_id="T3C-1h")
    assert "molecule" in _available_inputs(request, inputs)
    for row in ("T3C-3h", "T3O-1h", "T1-1h"):
        with pytest.raises(ValueError, match="T3C-1h only"):
            _available_inputs(request.model_copy(update={"matrix_row_id": row}), inputs)
    with pytest.raises(ValueError, match="explicitly declared"):
        _available_inputs(request.model_copy(update={"molecule": molecule()}), inputs)
    with pytest.raises(ValueError, match="unique"):
        _available_inputs(request, MatrixInputs(cfour_quadrupole_moments=[nucleus(), nucleus()]))
    with pytest.raises(ValidationError):
        MatrixInputs.model_validate({"cfour_quadrupole_moments": [{"atom_id": "atom-0", "mass_number": 17}]})


def test_native_reader_preserves_original_line_endings_in_raw_hash_binding(tmp_path):
    data = (FIXTURE / "output.stdout").read_bytes().replace(b"\n", b"\r\n")
    path = tmp_path / "engine.stdout"
    path.write_bytes(data)
    value = native_text(tmp_path, "engine.stdout", required=True)
    assert value.encode("utf-8") == data
    assert hashlib.sha256(value.encode("utf-8")).hexdigest() == hashlib.sha256(path.read_bytes()).hexdigest()
    # CRLF is not the authentic supported Linux-native grammar. Preservation
    # must not silently replace its bytes with a different acceptable output.
    with pytest.raises(EngineParseError):
        parse_cfour_output(value, molecule(), protocol(), efg=(FIXTURE / "EFG.out").read_text(),
                           dipol=(FIXTURE / "DIPOL.out").read_text())


@pytest.mark.parametrize("field", ["signed_q_millibarn", "q_standard_uncertainty_millibarn"])
@pytest.mark.parametrize("value", [True, False])
def test_boolean_flags_cannot_be_sourced_numeric_nuclear_moments_or_uncertainties(field, value):
    with pytest.raises(ValidationError):
        nucleus(**{field: value})


@pytest.mark.parametrize("name,destination", [("xdens", "xprops"), ("xlambda", "xdens")])
def test_future_completed_density_or_lambda_cannot_attribute_earlier_properties(name, destination):
    text = raw()
    program = re.search(r"(?m)^[ \t]*--invoking executable--[ \t]*\n[^\n]*/" + name
        + r"[ \t]*\n[\s\S]*?^[ \t]*--executable " + name
        + r" finished with status[^\n]*\n", text)
    assert program is not None
    block = program[0]
    changed = text[:program.start()] + text[program.end():]
    following = re.search(r"(?m)^[ \t]*--executable " + destination
                          + r" finished with status[^\n]*\n", changed)
    assert following is not None
    changed = changed[:following.end()] + block + changed[following.end():]
    # Every original program byte remains; only ordering is corrupted. This
    # rejection control does not claim the mutated text is genuine output.
    with pytest.raises(EngineParseError, match="must precede"):
        parse_cfour_output(changed, molecule(), protocol(), efg=(FIXTURE / "EFG.out").read_text(),
                           dipol=(FIXTURE / "DIPOL.out").read_text())
