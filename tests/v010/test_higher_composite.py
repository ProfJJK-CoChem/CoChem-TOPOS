"""Higher-geometry mathematics, native input contracts and authentic NCC grammar.

No test here executes licensed CFOUR. Model potentials below are explicitly
mathematical optimizer fixtures, never fabricated native scientific output.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from topos.engines import EngineParseError
from topos.external_engines import (
    ExternalProtocol,
    _cfour_cc_converged,
    _ncc_total_energy,
    cfour_input,
)
from topos.higher_composite import (
    HigherGeometryProtocol,
    NumericalGeometryOptions,
    _ComponentStop,
    _numerical_optimize,
    checked_energy_gradient,
    combine_higher_geometry,
    execute_higher_recipe,
)
from topos.models import Molecule, ResourceLimits, RunRecord, RunRequest
from topos.science import BOHR_ANGSTROM
from topos.storage import RunStore


def numerical(**updates):
    fields = dict(step_bohr=.001, maximum_step_disagreement_hartree_per_bohr=1e-7,
                  gradient_max_hartree_per_bohr=1e-5, gradient_rms_hartree_per_bohr=3e-6)
    fields.update(updates)
    return NumericalGeometryOptions(**fields)


def specification(**updates):
    fields = dict(template=ExternalProtocol(engine="cfour", engine_version="2.1", method="CCSD(T)",
        operation="optimize", orbital_basis="PVTZ", frozen_core=True,
        genbas_path="/licensed/cfour/basis/GENBAS", genbas_sha256="a" * 64),
        low_basis="PVTZ", high_basis="PVQZ", geometry_inverse_power=3., core_valence_basis="PCVTZ",
        full_triples_basis="PVTZ", full_quadruples_basis="PVDZ",
        coordinates={"coordinates": [{"kind": "distance", "atoms": [0, 1]}]},
        numerical_quadruples=numerical(), convention="explicit-geometry-CBS-CV-fT-fQ-v1")
    fields.update(updates)
    return HigherGeometryProtocol(**fields)


def diatomic(distance=.76):
    return Molecule(symbols=["H", "H"], coordinates=[[0, 0, 0], [0, 0, distance]], isotopes=[1, 2])


def geometries():
    # Exact R(X)=R_inf+A/X^3 model plus separately known geometric increments.
    distances = dict(cc_low=.74 + .27/27, cc_high=.74 + .27/64,
                     cv_ae=.747, cv_fc=.750, triples_full=.748, triples_parent=.746,
                     quadruples_full=.746, quadruples_parent=.747)
    return {role: diatomic(value) for role, value in distances.items()}


def test_parameterwise_geometry_cbs_and_full_quadruples_have_correct_signs():
    combined = combine_higher_geometry(geometries(), specification())
    assert combined["target_parameters"] == pytest.approx([.738], abs=1e-12)
    assert combined["realized_parameters"] == pytest.approx([.738], abs=1e-10)
    assert combined["increments"]["core_valence"] == pytest.approx([-.003])
    assert combined["increments"]["full_triples"] == pytest.approx([.002])
    assert combined["increments"]["full_quadruples"] == pytest.approx([-.001])
    assert combined["claims"]["accuracy_claim"] is None
    assert not combined["claims"]["energy_computed"]
    assert not combined["claims"]["minimum_verified"]


def test_geometry_arithmetic_independent_of_component_cartesian_frames():
    components = geometries()
    for i, (key, molecule) in enumerate(components.items()):
        xyz = np.asarray(molecule.coordinates)
        components[key] = molecule.model_copy(update={"coordinates": (xyz[:, [2, 0, 1]] + [i, -i, 3*i]).tolist()})
    assert combine_higher_geometry(components, specification())["realized_parameters"] == pytest.approx([.738])


@pytest.mark.parametrize("updates", [dict(high_basis="PV5Z"), dict(low_basis="jun-cc-pVTZ"),
    dict(geometry_inverse_power=1e-20), dict(core_valence_basis="PVTZ"),
    dict(full_quadruples_basis="PVDZ\nDBOC=ON"), dict(convention="HEAT-benchmark-certified")])
def test_unspecified_or_incompatible_family_choices_rejected(updates):
    with pytest.raises(ValueError):
        specification(**updates)


def test_missing_component_and_isotope_changes_rejected():
    components = geometries()
    components.pop("quadruples_full")
    with pytest.raises(ValueError, match="eight"):
        combine_higher_geometry(components, specification())
    components = geometries()
    components["quadruples_full"] = components["quadruples_full"].model_copy(update={"isotopes": [1, 1]})
    with pytest.raises(ValueError, match="identity"):
        combine_higher_geometry(components, specification())


def test_complete_independent_chart_cannot_be_omitted():
    with pytest.raises(ValueError, match="complete independent"):
        combine_higher_geometry(geometries(), specification(coordinates={"coordinates": []}))


def test_extrapolation_cannot_break_bond_despite_individually_preserved_components():
    # Every component is bonded; the exaggerated cumulative correction is not.
    components = {role: diatomic(.70) for role in specification().protocols()}
    for role in ("cc_high", "cv_ae", "triples_full", "quadruples_full"):
        components[role] = diatomic(.75)
    with pytest.raises(ValueError, match="Reconstructed composite.*topology"):
        combine_higher_geometry(components, specification())


def test_same_basis_core_and_full_t_q_protocols_and_native_integral_restriction():
    native = specification().protocols()
    assert native["cv_ae"].orbital_basis == native["cv_fc"].orbital_basis
    assert not native["cv_ae"].frozen_core and native["cv_fc"].frozen_core
    assert native["triples_full"].orbital_basis == native["triples_parent"].orbital_basis
    assert native["quadruples_full"].orbital_basis == native["quadruples_parent"].orbital_basis
    assert native["quadruples_full"].method == "CCSDTQ" and native["quadruples_parent"].method == "CCSDT"
    assert native["quadruples_full"].operation == "energy"
    q = cfour_input(diatomic(), native["quadruples_full"], ResourceLimits())
    t = cfour_input(diatomic(), native["triples_full"], ResourceLimits())
    assert "ABCDTYPE=STANDARD" in q and "CC_PROG=NCC" in q and "DERIV_LEVEL=ZERO" in q
    assert "ABCDTYPE=STANDARD" in t and "CC_PROG=ECC" in t and "DERIV_LEVEL=FIRST" in t
    assert "AOBASIS" not in q and "MRCC" not in q
    assert "AOBASIS" not in t


@pytest.mark.parametrize("operation", ["gradient", "optimize", "first-order-properties"])
def test_full_quadruples_never_claims_analytic_derivative(operation):
    value = specification().protocols()["quadruples_full"].model_dump()
    with pytest.raises(ValueError, match="energy-only"):
        ExternalProtocol.model_validate({**value, "operation": operation})


def test_authentic_ncc_convergence_and_total_grammar_has_immutable_provenance():
    folder = Path(__file__).parent / "fixtures" / "cfour"
    provenance = json.loads((folder / "ncc-provenance.json").read_text())
    raw = (folder / provenance["fixture"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == provenance["sha256"]
    assert "3098f558135589f5acf52474428ba020a561d58d" in provenance["url"]
    text = raw.decode()
    assert _cfour_cc_converged(text, "CCSDT")
    assert not _cfour_cc_converged(text, "CCSDTQ")
    assert _ncc_total_energy(text, "CCSDT") == pytest.approx(-76.374364172144837, abs=1e-12)
    with pytest.raises(EngineParseError):
        _ncc_total_energy(text, "CCSDTQ")
    with pytest.raises(EngineParseError):
        _ncc_total_energy(text + text, "CCSDT")
    with pytest.raises(EngineParseError):
        _ncc_total_energy(text.replace("iterations converged", "iterations failed"), "CCSDT")


def test_checked_central_derivative_against_exact_quadratic_and_quartic_math():
    x = np.array([.1, -.2, .3, .4, -.1, -.3])
    # Explicit model potential, not an engine output or chemistry benchmark.
    def energy(q):
        return float(.5 * np.dot(q, q) + .01 * np.sum(q**4))
    value, gradient, diagnostic = checked_energy_gradient(energy, x, numerical())
    assert value == energy(x)
    assert gradient == pytest.approx(x + .04*x**3, abs=5e-9)
    assert not diagnostic["analytic_derivative"] and not diagnostic["rigorous_uncertainty_estimate"]


def test_step_instability_and_fabricated_nonfinite_energies_rejected():
    with pytest.raises(ValueError, match="sensitivity"):
        checked_energy_gradient(lambda x: float(np.sum(100*x**4)), np.ones(6), numerical())
    with pytest.raises(ValueError, match="finite actual energy"):
        checked_energy_gradient(lambda x: float("nan"), np.ones(6), numerical())
    with pytest.raises(ValueError, match="one quarter"):
        numerical(maximum_step_disagreement_hartree_per_bohr=1e-5)


def test_numerical_optimizer_against_explicit_isotropic_harmonic_bond_model(tmp_path, monkeypatch):
    # Mathematical callback fixture only. It bypasses the electronic engine and
    # never writes a fabricated CFOUR output or passes the native ledger gate.
    import topos.higher_composite as module

    record = RunRecord(request=RunRequest(molecule=diatomic(), purpose="matrix", matrix_row_id="T3C-1w"), status="running")
    store = RunStore(tmp_path / record.run_id)
    store.commit(record)
    sampled = []

    def model_component(workflow, record, store, key, molecule, protocol, executor, deadline, cancel):
        xyz = np.asarray(molecule.coordinates) / BOHR_ANGSTROM
        radius = np.linalg.norm(xyz[1]-xyz[0])
        sampled.append(key)
        return SimpleNamespace(energy_hartree=.5*(radius-.74/BOHR_ANGSTROM)**2,
                               engine_version="2.1", metadata={"executable_sha256": "a"*64,
                                                              "basis_library": {"sha256": "b"*64}})

    monkeypatch.setattr(module, "run_component", model_component)
    molecule, diagnostic, identities = _numerical_optimize(None, record, store,
        specification().protocols()["quadruples_full"], numerical(), time.monotonic()+30, None)
    assert np.linalg.norm(np.asarray(molecule.coordinates)[1]-molecule.coordinates[0]) == pytest.approx(.74, abs=1e-6)
    assert diagnostic["energy_geometries"] == len(set(sampled))
    assert not diagnostic["analytic_gradient"] and not diagnostic["minimum_hessian_verified"]
    assert len(identities) == 1


@pytest.mark.parametrize("kind", ["cancel", "deadline"])
def test_numerical_campaign_stops_before_any_component_when_cancelled_or_expired(tmp_path, monkeypatch, kind):
    import topos.higher_composite as module

    record = RunRecord(request=RunRequest(molecule=diatomic(), purpose="matrix", matrix_row_id="T3C-1w"), status="running")
    store = RunStore(tmp_path / record.run_id)
    store.commit(record)
    event = Event()
    if kind == "cancel":
        event.set()
    monkeypatch.setattr(module, "run_component", lambda *args: pytest.fail("No energy may be launched"))
    with pytest.raises(_ComponentStop):
        _numerical_optimize(None, record, store, specification().protocols()["quadruples_full"], numerical(),
                            time.monotonic() + (30 if kind == "cancel" else -1), event)
    assert record.status == ("cancelled" if kind == "cancel" else "timed-out")


@pytest.mark.parametrize("row", ["T3O-1w", "T3C-1mo"])
def test_missing_cp_or_small_corrections_cannot_claim_other_complete_rows(tmp_path, row):
    record = RunRecord(request=RunRequest(molecule=diatomic(), purpose="matrix", matrix_row_id=row), status="running")
    store = RunStore(tmp_path / record.run_id)
    store.commit(record)
    inputs = SimpleNamespace(higher_geometry=specification(), external_resolution="cfour-topos-cartesian-optimizer-v1")
    assert not execute_higher_recipe(None, record, store, inputs, time.monotonic()+30, None)
    assert record.status == "unsupported" and not record.attempts
