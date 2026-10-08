"""Scalar correction contracts and mathematics; no licensed CFOUR execution.

The two raw historical files are authentic public outputs with SHA-bound
provenance. Their control grammar is tested without promoting either old output
to successful native public-2.1 energy or isotope-specific DBOC evidence.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from topos.cfour_corrections import (
    ScalarCampaignStopped,
    ScalarRelativisticProtocol,
    apply_scalar_geometry_increment,
    calculate_scalar_geometry_correction,
    optimize_scalar_geometry,
    parse_scalar_output,
    run_scalar_relativistic,
    scalar_controls,
    scalar_input,
)
from topos.engines import EngineParseError
from topos.external_engines import ExternalProtocol, _native_completion
from topos.higher_composite import (
    HigherCoordinateSet,
    NumericalGeometryOptions,
    checked_energy_gradient,
)
from topos.models import Molecule, ResourceLimits, RunRecord, RunRequest
from topos.storage import RunStore, file_digest

FIXTURES = Path(__file__).parent / "fixtures/cfour_corrections"


def protocol(**updates):
    values = dict(orbital_basis="PCVTZ", genbas_path="/licensed/cfour/basis/GENBAS",
                  genbas_sha256="a" * 64, relativistic="X2C1E")
    values.update(updates)
    return ScalarRelativisticProtocol(**values)


def diatomic(distance=.75):
    return Molecule(symbols=["H", "H"], isotopes=[1, 2], coordinates=[[0, 0, 0], [0, 0, distance]])


def chart():
    return HigherCoordinateSet(coordinates=[{"kind": "distance", "atoms": [0, 1]}])


def options():
    return NumericalGeometryOptions(step_bohr=.001, maximum_step_disagreement_hartree_per_bohr=1e-7,
        gradient_max_hartree_per_bohr=1e-5, gradient_rms_hartree_per_bohr=3e-6)


def test_native_input_changes_only_the_explicit_scalar_hamiltonian_between_paired_legs():
    relativistic = scalar_input(diatomic(), protocol(), ResourceLimits())
    reference = scalar_input(diatomic(), protocol(relativistic="OFF"), ResourceLimits())
    assert relativistic.replace("RELATIVISTIC=X2C1E", "RELATIVISTIC=OFF") == reference
    for text in (relativistic, reference):
        for flag in ("CALC_LEVEL=SCF", "REFERENCE=RHF", "FROZEN_CORE=OFF", "CONTRACTION=UNCONTRACTED",
                     "BASIS=PCVTZ", "DERIV_LEVEL=ZERO", "DBOC=OFF"):
            assert flag in text
        assert "DPT2" not in text and "DERIV_LEVEL=FIRST" not in text


@pytest.mark.parametrize("change", [dict(method="CCSD(T)"), dict(frozen_core=True),
    dict(contraction="GENERAL"), dict(engine_version="2.00beta"), dict(relativistic="DPT2"),
    dict(operation="gradient"), dict(orbital_basis="PCVTZ\nDBOC=ON")])
def test_unsupported_hamiltonians_or_analytic_derivatives_cannot_enter_profile(change):
    with pytest.raises(ValueError):
        protocol(**change)


def test_historical_native_provenance_and_real_x2c_control_grammar():
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    for source in provenance["sources"]:
        assert file_digest(FIXTURES / source["fixture"]) == source["sha256"]
    raw = (FIXTURES / "ne-x2c.out").read_text()
    controls = scalar_controls(raw, "X2C1E")
    assert controls["CONTRACTION"] == "UNCONTRACTED"
    assert controls["DBOC"] == "OFF"
    with pytest.raises(EngineParseError, match="RELATIVIST"):
        scalar_controls(raw, "OFF")
    # Old genuine grammar evidence is never accepted as a current 2.1 run.
    with pytest.raises(EngineParseError, match="exact requested native version"):
        parse_scalar_output(raw, Molecule(symbols=["Ne"], coordinates=[[0, 0, 0]]), protocol())


def test_partial_x2c_native_program_cannot_be_accepted_from_echoed_keyword():
    raw = (FIXTURES / "ne-x2c.out").read_text()
    unfinished = raw[:raw.index("--executable xvpropx2c finished")]
    with pytest.raises(EngineParseError, match="xvpropx2c completion"):
        scalar_controls(unfinished, "X2C1E")


def test_actual_historical_dboc_number_with_crashed_mass_evaluation_is_rejected():
    raw = (FIXTURES / "carbon13-failed.out").read_text()
    assert "0.0015685427 a.u." in raw and "13.003354838" in raw
    assert "SIGSEGV, segmentation fault occurred" in raw
    assert "xjoda finished with status 44544" in raw
    assert "Job completed successfully." in raw  # scheduler success is insufficient
    old = ExternalProtocol(engine="cfour", engine_version="2.00beta", method="CCSD",
                           orbital_basis="SPECIAL", operation="energy", frozen_core=False)
    with pytest.raises(EngineParseError):
        _native_completion(raw, old)
    with pytest.raises(EngineParseError):
        scalar_controls(raw, "OFF")


def test_parameterwise_scalar_increment_preserves_sign_units_and_frame_invariance():
    # Mathematical geometries only, not electronic-structure results.
    reference, scalar = diatomic(.751), diatomic(.749)
    scalar.coordinates = (np.asarray(scalar.coordinates)[:, [2, 0, 1]] + [4, -3, 1]).tolist()
    result = apply_scalar_geometry_increment(diatomic(.742), scalar, reference, chart())
    assert result["increment_parameters"] == pytest.approx([-.002], abs=1e-12)
    assert result["realized_parameters"] == pytest.approx([.740], abs=1e-10)
    assert result["claims"]["native_execution_verified"] is False
    assert result["claims"]["dboc_computed"] is False
    assert result["claims"]["matrix_row_complete"] is False
    assert result["claims"]["stationary_point_verified"] is False


def test_isotope_changes_and_broken_reconstructed_topology_are_rejected():
    changed = diatomic().model_copy(update={"isotopes": [1, 1]})
    with pytest.raises(ValueError, match="identity"):
        apply_scalar_geometry_increment(diatomic(), changed, diatomic(), chart())
    # All individual H-H distances remain bonded; the extrapolated sum does not.
    with pytest.raises(ValueError, match="Reconstructed.*topology"):
        apply_scalar_geometry_increment(diatomic(.75), diatomic(.75), diatomic(.50), chart())


def test_harmonic_model_energy_derivatives_are_checked_without_engine_claims():
    x = np.array([.3, -.2, .1, -.1, .5, .7])
    centre = np.array([.1, .1, .1, -.1, -.2, .3])
    diagonal = np.arange(1, 7) * .01
    value, gradient, report = checked_energy_gradient(lambda q: float(.5 * np.sum(diagonal * (q-centre)**2)), x, options())
    assert value == pytest.approx(.5 * np.sum(diagonal * (x-centre)**2))
    np.testing.assert_allclose(gradient, diagonal * (x-centre), atol=1e-12)
    assert report["maximum_step_disagreement_hartree_per_bohr"] < 1e-12


@pytest.mark.parametrize("stop", ["cancelled", "deadline"])
def test_durable_scalar_campaign_stops_before_any_native_job(tmp_path, stop):
    record = RunRecord(request=RunRequest(molecule=diatomic()))
    store = RunStore(tmp_path / record.run_id)
    store.commit(record)
    event = Event()
    if stop == "cancelled":
        event.set()
    with pytest.raises(ScalarCampaignStopped):
        optimize_scalar_geometry(None, record, store, protocol(), options(),
                                 time.monotonic() + (30 if stop == "cancelled" else -1), event)
    restored = RunRecord.model_validate(store.load())
    assert restored.status == ("cancelled" if stop == "cancelled" else "timed-out")
    assert restored.attempts == []


def test_absent_cfour_returns_no_energy_and_never_executes_supplied_runner(tmp_path):
    def must_not_run(*args, **kwargs):
        raise AssertionError("Missing CFOUR cannot launch a calculation")
    result = run_scalar_relativistic(diatomic(), protocol(), ResourceLimits(), tmp_path / "native",
        executable="/no/real/cfour/xcfour", process_runner=must_not_run)
    assert result.status == "unavailable" and result.energy_hartree is None
    assert result.metadata["execution_kind"] == "not-executed"
    assert not result.artifacts and not result.command


def test_paired_correction_cannot_be_requested_as_nonrelativistic_only():
    with pytest.raises(ValueError, match="explicitly select X2C1E"):
        calculate_scalar_geometry_correction(SimpleNamespace(), None, None, diatomic(),
            protocol(relativistic="OFF"), chart(), options(), time.monotonic() + 1)
