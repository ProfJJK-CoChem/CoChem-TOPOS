"""Default-mass DBOC grammar, compiler and math; no licensed native execution."""
from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from topos.cfour_corrections import ScalarCampaignStopped
from topos.cfour_dboc import (
    MASS_CONVENTION,
    DefaultMassDBOCProtocol,
    apply_dboc_geometry_increment,
    calculate_default_mass_dboc_geometry,
    dboc_input,
    parse_dboc_output,
    parse_default_mass_dboc_section,
    quantized_gradient_error_bound,
    run_default_mass_dboc,
    validate_default_mass_domain,
)
from topos.engines import EngineParseError
from topos.higher_composite import HigherCoordinateSet, NumericalGeometryOptions
from topos.models import Molecule, ResourceLimits, RunRecord, RunRequest
from topos.storage import RunStore, file_digest

FIXTURES = Path(__file__).parent / "fixtures/cfour_corrections"


def protocol(**updates):
    values = dict(orbital_basis="PCVTZ", contraction="GENERAL", mass_convention=MASS_CONVENTION,
                  genbas_path="/licensed/cfour/basis/GENBAS", genbas_sha256="a" * 64)
    values.update(updates)
    return DefaultMassDBOCProtocol(**values)


def hydrogen(distance=.75):
    return Molecule(symbols=["H", "H"], coordinates=[[0, 0, 0], [0, 0, distance]])


def options(**updates):
    values = dict(step_bohr=.001, maximum_step_disagreement_hartree_per_bohr=1e-7,
                  gradient_max_hartree_per_bohr=1e-5, gradient_rms_hartree_per_bohr=3e-6)
    values.update(updates)
    return NumericalGeometryOptions(**values)


def chart():
    return HigherCoordinateSet(coordinates=[{"kind": "distance", "atoms": [0, 1]}])


def test_explicit_mass_convention_basis_and_contraction_are_required():
    values = protocol().model_dump()
    for key in ("mass_convention", "orbital_basis", "contraction"):
        with pytest.raises(ValueError):
            DefaultMassDBOCProtocol.model_validate({k: v for k, v in values.items() if k != key})


@pytest.mark.parametrize("change", [dict(method="CCSD"), dict(engine_version="2.00beta"),
    dict(relativistic="X2C1E"), dict(mass_convention="assume-mendeleev-masses"),
    dict(frozen_core=True), dict(operation="gradient")])
def test_uncertified_methods_mass_conventions_and_derivatives_are_rejected(change):
    with pytest.raises(ValueError):
        protocol(**change)


def test_dboc_compiler_does_not_disable_required_native_response_machinery():
    dboc = dboc_input(hydrogen(), protocol(), ResourceLimits())
    electronic = dboc_input(hydrogen(), protocol(dboc=False), ResourceLimits())
    for key in ("CALC_LEVEL=SCF", "REFERENCE=RHF", "FROZEN_CORE=OFF", "RELATIVISTIC=OFF", "CONTRACTION=GENERAL"):
        assert key in dboc and key in electronic
    assert "DBOC=ON" in dboc and "DERIV_LEVEL" not in dboc
    assert "DBOC=OFF" in electronic and "DERIV_LEVEL=ZERO" in electronic
    assert "ISOMASS" not in dboc and "%isotopes" not in dboc
    assert "DBOC=ON" not in electronic


@pytest.mark.parametrize("isotopes", [[1, None], [None, 1], [1, 1], [1, 2]])
def test_every_explicit_isotope_is_rejected_including_common_primary_isotopes(isotopes):
    with pytest.raises(ValueError, match="every explicit isotope"):
        validate_default_mass_domain(hydrogen().model_copy(update={"isotopes": isotopes}))


def test_default_mass_domain_does_not_extend_to_unsupported_elements_or_spin():
    with pytest.raises(ValueError, match="restricted to"):
        validate_default_mass_domain(Molecule(symbols=["Cl", "Cl"], coordinates=[[0, 0, 0], [0, 0, 2]]))
    with pytest.raises(ValueError, match="closed-shell"):
        validate_default_mass_domain(hydrogen().model_copy(update={"multiplicity": 3}))


def test_genuine_historical_default_mass_grammar_accepts_consistent_repeated_totals_only():
    raw = (FIXTURES / "carbon12-dboc.out").read_text()
    source = next(x for x in json.loads((FIXTURES / "provenance.json").read_text())["sources"] if x["fixture"] == "carbon12-dboc.out")
    assert file_digest(FIXTURES / source["fixture"]) == source["sha256"]
    # This is a section parser, not successful present-day HF attestation.
    result = parse_default_mass_dboc_section(raw)
    assert result["dboc_energy_hartree"] == pytest.approx(.0016997291)
    assert result["printed_totals_hartree"] == [.0016997291, .0016997291]
    assert result["dboc_print_rounding_bound_hartree"] == pytest.approx(5e-11)
    assert result["mass_convention"]["native_numeric_masses_verified"] is False
    assert result["mass_convention"]["rotor_mass_attestation_available"] is False
    with pytest.raises(EngineParseError, match="exact requested native version"):
        parse_dboc_output(raw, hydrogen(), protocol())


def test_real_mass_path_crash_and_premature_default_total_do_not_certify_dboc():
    raw = (FIXTURES / "carbon13-failed.out").read_text()
    with pytest.raises(EngineParseError, match="fatal error"):
        parse_default_mass_dboc_section(raw)
    truncated = raw[:raw.index("forrtl: severe")]
    with pytest.raises(EngineParseError, match="native-default mass path"):
        parse_default_mass_dboc_section(truncated)


def test_truncated_default_output_before_mass_path_check_is_insufficient():
    raw = (FIXTURES / "carbon12-dboc.out").read_text()
    with pytest.raises(EngineParseError, match="native-default mass path"):
        parse_default_mass_dboc_section(raw[:raw.index("readis is")])


def test_finer_derivative_includes_known_print_quantization_even_when_steps_agree():
    result = quantized_gradient_error_bound(options(), 5e-11, 0.)
    assert result["print_quantization_gradient_bound_hartree_per_bohr"] == pytest.approx(1e-7)
    assert result["acceptance_margin_hartree_per_bohr"] == pytest.approx(1e-7)
    # Smaller displacement can make an unchanged rounded total falsely appear
    # converged; the nonzero precision bound rejects that insufficient signal.
    with pytest.raises(ValueError, match="quantization"):
        quantized_gradient_error_bound(options(step_bohr=.0001), 5e-11, 0.)


@pytest.mark.parametrize("rounding,step", [(float("nan"), 0), (float("inf"), 0), (-1e-10, 0), (0, -1e-10)])
def test_invalid_precision_cannot_be_reported_as_zero_error(rounding, step):
    with pytest.raises(ValueError, match="nonnegative"):
        quantized_gradient_error_bound(options(), rounding, step)


def test_default_mass_coordinate_increment_does_not_publish_mass_bound_rotor_constants():
    # Mathematical input geometries only; no native DBOC values are fabricated.
    corrected = hydrogen(.754)
    corrected.coordinates = (np.asarray(corrected.coordinates)[:, [1, 2, 0]] + [2, 3, 4]).tolist()
    report = apply_dboc_geometry_increment(hydrogen(.740), corrected, hydrogen(.750), chart())
    assert report["realized_parameters"] == pytest.approx([.744], abs=1e-10)
    assert report["increment_parameters"] == pytest.approx([.004], abs=1e-12)
    assert set(report["component_parameters"]) == {"base", "hf_plus_dboc", "hf_born_oppenheimer"}
    assert not report["claims"]["native_execution_verified"]
    assert not report["claims"]["dboc_geometry_computed"]
    assert not report["claims"]["rotor_constants_publishable"]
    assert not report["claims"]["matrix_row_complete"]
    assert "X2C" not in json.dumps(report)


@pytest.mark.parametrize("stop", ["cancelled", "deadline"])
def test_stopped_dboc_campaign_retains_ledger_without_starting_native_jobs(tmp_path, stop):
    record = RunRecord(request=RunRequest(molecule=hydrogen()))
    store = RunStore(tmp_path / record.run_id)
    store.commit(record)
    event = Event()
    if stop == "cancelled":
        event.set()
    with pytest.raises(ScalarCampaignStopped):
        calculate_default_mass_dboc_geometry(None, record, store, hydrogen(), protocol(), chart(), options(),
            time.monotonic() + (30 if stop == "cancelled" else -1), event)
    restored = RunRecord.model_validate(store.load())
    assert restored.status == ("cancelled" if stop == "cancelled" else "timed-out")
    assert not restored.attempts


def test_missing_native_engine_never_yields_a_zero_dboc_substitute(tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Missing engine must not execute")
    result = run_default_mass_dboc(hydrogen(), protocol(), ResourceLimits(), tmp_path / "native",
        executable="/missing/licensed/xcfour", process_runner=forbidden)
    assert result.status == "unavailable" and result.energy_hartree is None
    assert "native_result" not in result.metadata
    assert result.metadata["execution_kind"] == "not-executed"


def test_existing_custom_mass_file_is_rejected_before_engine_lookup(tmp_path):
    native = tmp_path / "native"
    native.mkdir()
    (native / "ISOMASS").write_text("Existing user input; no inferred syntax")
    result = run_default_mass_dboc(hydrogen(), protocol(), ResourceLimits(), native,
        executable="/missing/licensed/xcfour", process_runner=lambda *args, **kwargs: None)
    assert result.status == "unsupported"
    assert "fresh directory" in result.diagnostics["reason"]
    assert (native / "ISOMASS").read_text() == "Existing user input; no inferred syntax"


def native_mass_water():
    from topos.science import BOHR_ANGSTROM

    return Molecule(symbols=['H','O','H'], coordinates=(np.asarray([
        [0,-1.42462544,.99592406], [0,0,-.12550454], [0,1.42462544,.99592406]])*BOHR_ANGSTROM).tolist())


def test_authentic_atomic_mass_observations_do_not_claim_current_native_execution():
    from topos.cfour_dboc import parse_cfour_rotor_mass_table

    carbon = Molecule(symbols=['C'],coordinates=[[0,0,0]],multiplicity=3)
    observed = parse_cfour_rotor_mass_table((FIXTURES/'carbon12-dboc.out').read_text(),carbon)
    assert observed['masses_amu'] == [12.]
    assert observed['rounding_half_width_amu'] == [5e-10]
    assert observed['mass_table_observations'][0]['source_lines'] == [1834,1835]
    assert observed['native_execution_verified'] is False
    assert observed['internal_dboc_nuclear_masses_numerically_verified'] is False
    assert observed['mass_values_substituted'] is False
    assert observed['arbitrary_isotopes_supported'] is False


def test_authentic_multiatom_mass_order_and_proper_rotated_reference_geometry():
    from scipy.spatial.transform import Rotation

    from topos.cfour_dboc import parse_cfour_rotor_mass_table

    source=json.loads((FIXTURES/'h2o-native-mass.provenance.json').read_text())
    assert source['commit'] == 'd354fd6f6b6e9bb79f34ea11928c62c6b2b6c2dc'
    assert file_digest(FIXTURES/'h2o-native-mass.out') == source['sha256']
    molecule=native_mass_water()
    rotation=Rotation.from_rotvec([.3,-.7,.5]).as_matrix()
    molecule.coordinates=(np.asarray(molecule.coordinates)@rotation+[3,-2,5]).tolist()
    observed=parse_cfour_rotor_mass_table((FIXTURES/'h2o-native-mass.out').read_text(),molecule)
    assert observed['atom_ids']==molecule.atom_ids and observed['symbols']==['H','O','H']
    assert observed['masses_amu']==[1.007825035,15.994914630,1.007825035]
    assert observed['rounding_half_width_amu']==[5e-10]*3
    assert observed['native_geometries'][0]['source_lines']==[279,285]
    assert observed['mass_table_observations'][0]['source_lines']==[2993,2994]
    assert not observed['native_execution_verified']
    # Genuine historical1.01 grammar cannot satisfy the production2.1 gate.
    with pytest.raises(EngineParseError,match='exact requested native version'):
        parse_dboc_output((FIXTURES/'h2o-native-mass.out').read_text(),molecule,protocol())


@pytest.mark.parametrize('old,new',[
    ('   1.007825035     15.994914630      1.007825035','   1.007825035     15.994914630'),
    ('   1.007825035     15.994914630      1.007825035','   1.007825035     15.994914630      1.007825035 1.007825035'),
    ('   1.007825035     15.994914630      1.007825035','   15.994914630     1.007825035      1.007825035'),
    ('   1.007825035     15.994914630      1.007825035','   1.007276     15.990526      1.007276'),
    ('   1.007825035     15.994914630      1.007825035','   1.008     15.995      1.008'),
    ('masses used (in AMU) in vibrational analysis:','mass header absent:'),
    ('H         1         0.00000000    -1.42462544','H         1         0.00000000    -1.82462544'),
    ('O         8         0.00000000','H         1         0.00000000'),
])
def test_mutated_historical_mass_geometry_grammar_cannot_certify_rotors(old,new):
    from topos.cfour_dboc import parse_cfour_rotor_mass_table

    raw=(FIXTURES/'h2o-native-mass.out').read_text()
    assert old in raw
    with pytest.raises(EngineParseError):
        parse_cfour_rotor_mass_table(raw.replace(old,new),native_mass_water())


def test_wrapped_vectors_keep_native_values_and_conflicting_repetitions_fail():
    from topos.cfour_dboc import parse_cfour_rotor_mass_table

    raw=(FIXTURES/'h2o-native-mass.out').read_text()
    row='   1.007825035     15.994914630      1.007825035'
    wrapped=raw.replace(row,'   1.007825035\n     15.994914630      1.007825035')
    # Formatting-only parser test; no modified native output claims execution.
    assert parse_cfour_rotor_mass_table(wrapped,native_mass_water())['masses_amu']==[1.007825035,15.994914630,1.007825035]
    contradictory=raw+'\n masses used (in AMU) in vibrational analysis:\n 1.007825036 15.994914630 1.007825035\n Normal Coordinate Analysis\n'
    with pytest.raises(EngineParseError,match='Repeated'):
        parse_cfour_rotor_mass_table(contradictory,native_mass_water())


def test_injected_mass_aggregate_without_any_native_components_cannot_close_month(tmp_path):
    from topos.cfour_dboc import validate_rotor_mass_attestation
    from topos.storage import IntegrityError

    record=RunRecord(request=RunRequest(molecule=hydrogen()))
    store=RunStore(tmp_path/record.run_id)
    store.commit(record)
    report={'native_optimizations':{'hf_plus_dboc':{'protocol':protocol().model_dump(mode='json')}},
            'rotor_mass_attestation':{'masses_amu':[1.007825035]*2,'native_execution_verified':True}}
    with pytest.raises(IntegrityError,match='No completed native'):
        validate_rotor_mass_attestation(report,record,store,hydrogen(),['2.1','a'*64,'b'*64])
