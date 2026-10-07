"""External adapter contracts and authentic historical-output regression tests.

These are not live CFOUR/Psi4 calculations. Fixture provenance retains the
upstream immutable commit and checksums; numerical test doubles are labelled.
"""
import ast
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from topos.engines import EngineParseError
from topos.external_engines import (
    ExternalProtocol,
    _native_genbas,
    _proper_rotation,
    cfour_input,
    parse_cfour_output,
    parse_psi4_result,
    psi4_input,
    run_external,
)
from topos.models import FragmentState, Molecule, ResourceLimits
from topos.runtime import ProcessResult
from topos.science import BOHR_ANGSTROM

FIXTURES = Path(__file__).parent / "fixtures" / "cfour"


def protocol(method="MP2", operation="energy", **changes):
    return ExternalProtocol(engine="cfour", engine_version="1.2", method=method,
                            operation=operation, orbital_basis="PVTZ" if method == "MP2" else "dzp",
                            frozen_core=False, **changes)


def native_fixture(method="MP2"):
    from qcengine.programs.cfour.harvester import harvest_outfile_pass

    text = (FIXTURES / f"{'mp2' if method == 'MP2' else 'ccsd_t'}-native-first-evaluation.stdout").read_text()
    _, native, gradient, *_ = harvest_outfile_pass(text)
    molecule = Molecule(symbols=list(native.symbols), coordinates=(native.geometry * BOHR_ANGSTROM).tolist())
    # Format fixture reconstructed from actual stdout coordinates/derivatives;
    # this tests GRD decoding, not a claim that upstream supplied a GRD file.
    numbers = [8, 1, 1]
    rows = [str(len(numbers))]
    rows += [f"{z} " + " ".join(f"{x:.12f}" for x in row) for z, row in zip(numbers, native.geometry, strict=True)]
    rows += [f"{z} " + " ".join(f"{x:.12f}" for x in row) for z, row in zip(numbers, gradient, strict=True)]
    return text, molecule, "\n".join(rows) + "\n"


def test_authentic_fixture_checksums():
    for source in json.loads((FIXTURES / "provenance.json").read_text())["sources"]:
        assert hashlib.sha256((FIXTURES / source["fixture"]).read_bytes()).hexdigest() == source["excerpt_sha256"]
        assert "23be3de4b1f6cd70e337b98a2a200008cf350274" in source["url"]


@pytest.mark.parametrize("method,energy", [("MP2", -76.332242848098), ("CCSD(T)", -76.244205020359)])
def test_authentic_requested_correlated_energy(method, energy):
    text, molecule, _ = native_fixture(method)
    result = parse_cfour_output(text, molecule, protocol(method))
    assert result["energy_hartree"] == pytest.approx(energy, abs=1e-11)
    assert result["energy_hartree"] != result["reference_energy_hartree"]


@pytest.mark.parametrize("method", ["MP2", "CCSD(T)"])
def test_native_gradient_frame_and_index_preservation(method):
    text, molecule, grd = native_fixture(method)
    expected = parse_cfour_output(text, molecule, protocol(method, "gradient"), grd=grd)
    rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    moved = molecule.model_copy(update={"coordinates": (np.asarray(molecule.coordinates) @ rotation + [4, 5, 6]).tolist()})
    result = parse_cfour_output(text, moved, protocol(method, "gradient"), grd=grd)
    assert np.asarray(result["gradient_hartree_per_bohr"]) == pytest.approx(np.asarray(expected["gradient_hartree_per_bohr"]) @ rotation)


@pytest.mark.parametrize("change", ["version", "core", "charge", "basis", "termination", "convergence", "concatenation", "method"])
def test_unestablished_scientific_result_rejected(change):
    text, molecule, _ = native_fixture()
    selected = protocol()
    if change == "version":
        selected = selected.model_copy(update={"engine_version": "2.1"})
    elif change == "core":
        selected = selected.model_copy(update={"frozen_core": True})
    elif change == "charge":
        molecule = molecule.model_copy(update={"charge": 2})
    elif change == "basis":
        selected = selected.model_copy(update={"orbital_basis": "cc-pVDZ"})
    elif change == "termination":
        text = text.replace("--executable xvdint finished with status            0", "--executable xvdint finished with status            1")
    elif change == "convergence":
        text = text.replace("SCF has converged.", "SCF has NOT CONVERGED.")
    elif change == "concatenation":
        text += text
    else:
        selected = selected.model_copy(update={"method": "CCSD(T)"})
    with pytest.raises(EngineParseError):
        parse_cfour_output(text, molecule, selected)


def test_gradient_artifacts_must_agree():
    text, molecule, grd = native_fixture()
    with pytest.raises(EngineParseError, match="GRD artifact"):
        parse_cfour_output(text, molecule, protocol(operation="gradient"))
    with pytest.raises(EngineParseError, match="same indexed result"):
        parse_cfour_output(text, molecule, protocol(operation="gradient"), grd=grd.replace("-0.000916441700", "-0.100916441700"))


def test_higher_level_job_cannot_impersonate_its_mp2_intermediate():
    text, molecule, _ = native_fixture("CCSD(T)")
    selected = protocol().model_copy(update={"orbital_basis": "dzp"})
    with pytest.raises(EngineParseError, match="CALC_LEVEL"):
        parse_cfour_output(text, molecule, selected)


def test_geometry_or_reflection_cannot_be_laundered_as_same_result():
    xyz = np.array([[0., 0., 0.], [1., 0., 0.], [0., 2., 0.], [0., 0., 3.]])
    with pytest.raises(EngineParseError, match="reflection"):
        _proper_rotation(xyz, xyz * [-1, 1, 1])
    text, molecule, _ = native_fixture()
    changed = np.asarray(molecule.coordinates)
    changed[0, 0] += .1
    with pytest.raises(EngineParseError, match="geometry changed"):
        parse_cfour_output(text, molecule.model_copy(update={"coordinates": changed.tolist()}), protocol())


def test_cartesian_input_does_not_distort_water_or_claim_native_optimization():
    _, molecule, _ = native_fixture()
    resources = ResourceLimits(memory_mb=512, threads=2)
    deck = cfour_input(molecule, protocol(operation="optimize"), resources)
    assert "COORDINATES=CARTESIAN" in deck and "DERIV_LEVEL=FIRST" in deck
    assert "VIB" not in deck and "ANHARM" not in deck and "GEO_METHOD" not in deck
    assert "ABCDTYPE=AOBASIS" in deck and "MEMORY_SIZE=50331648" in deck
    observed = np.array([[float(v) for v in row.split()[1:]] for row in deck.splitlines()[1:4]])
    assert observed == pytest.approx(np.asarray(molecule.coordinates))
    assert "PROPS=FIRST_ORDER" in cfour_input(molecule, protocol(operation="first-order-properties"), resources)


@pytest.mark.parametrize("basis", ["cc-pVDZ\nPROPS=OFF", "../../basis", "cc-pVDZ);system('id')", "x y"])
def test_native_basis_keyword_injection_rejected(basis):
    with pytest.raises(ValidationError):
        ExternalProtocol(engine="cfour", engine_version="2.1", operation="energy", method="MP2", orbital_basis=basis, frozen_core=True)


def test_genbas_tied_to_native_installation_and_element_inventory(tmp_path):
    binary = tmp_path / "install" / "bin" / "xcfour"
    binary.parent.mkdir(parents=True)
    binary.write_text("fixture executable placeholder; not run")
    genbas = binary.parent / "GENBAS"
    genbas.write_text("O:PVTZ\nfixture\nH:PVTZ\nfixture\n")
    p = protocol(genbas_path=str(genbas), genbas_sha256=hashlib.sha256(genbas.read_bytes()).hexdigest())
    _, molecule, _ = native_fixture()
    assert _native_genbas(binary, p, molecule) == genbas
    genbas.write_text("O:PVTZ\nfixture\n")
    with pytest.raises(ValueError, match="unchanged"):
        _native_genbas(binary, p, molecule)
    p = p.model_copy(update={"genbas_sha256": hashlib.sha256(genbas.read_bytes()).hexdigest()})
    with pytest.raises(ValueError, match="lacks H"):
        _native_genbas(binary, p, molecule)


def dimer():
    return Molecule(symbols=["He", "He"], coordinates=[[0, 0, 0], [0, 0, 3]], fragments=[[0], [1]],
                    fragment_states=[FragmentState(atom_indices=[0], charge=0, multiplicity=1),
                                     FragmentState(atom_indices=[1], charge=0, multiplicity=1)])


def sapt_protocol():
    return ExternalProtocol(engine="psi4", engine_version="1.9.1", operation="sapt-decomposition", method="SAPT2+3",
                            orbital_basis="aug-cc-pVDZ", auxiliary_scf_basis="aug-cc-pVDZ-jkfit",
                            auxiliary_sapt_basis="aug-cc-pVDZ-ri", frozen_core=True)


def test_psi4_driver_is_valid_fixed_python_with_explicit_method_and_states():
    text = psi4_input(dimer(), sapt_protocol(), ResourceLimits())
    ast.parse(text)
    assert "psi4.energy('sapt2+3'" in text and "sapt__nat_orbs_t2': False" in text
    assert "df_basis_sapt" in text and "no_reorient" in text and "no_com" in text
    assert "native-result.json" in text and "SAPT TOTAL ENERGY" in text
    with pytest.raises(ValueError, match="partition"):
        psi4_input(dimer().model_copy(update={"fragments": [], "fragment_states": []}), sapt_protocol(), ResourceLimits())


def test_sapt_sum_arithmetic_is_interaction_not_electronic_energy():
    # Analytical arithmetic fixture only, not a claimed quantum-chemistry result.
    data = {"engine_version": "1.9.1", "method": "SAPT2+3", "returned_interaction_hartree": -.001, "native_core_sha256": "0" * 64,
            "quantities_hartree": {"SAPT ELST ENERGY": -.002, "SAPT EXCH ENERGY": .004,
                                   "SAPT IND ENERGY": -.001, "SAPT DISP ENERGY": -.002,
                                   "SAPT TOTAL ENERGY": -.001}}
    result = parse_psi4_result(json.dumps(data), sapt_protocol())
    assert result["interaction_energy_hartree"] == -.001
    assert "energy_hartree" not in result
    data["quantities_hartree"]["SAPT IND ENERGY"] = -.002
    with pytest.raises(EngineParseError, match="sum"):
        parse_psi4_result(json.dumps(data), sapt_protocol())


@pytest.mark.parametrize("engine", ["molpro", "mpqc"])
def test_underspecified_external_rows_are_explicitly_unsupported(tmp_path, engine):
    p = ExternalProtocol(engine=engine, engine_version="2025.1", operation="optimize", method="unspecified",
                         orbital_basis="cc-pVTZ-F12", frozen_core=True)
    result = run_external(dimer(), p, ResourceLimits(), tmp_path / engine, process_runner=lambda *a, **k: pytest.fail("Must not launch"))
    assert result.status == "unsupported" and result.energy_hartree is None
    assert result.metadata["execution_kind"] == "not-executed"


def test_missing_cfour_is_unavailable_not_a_fake_success(tmp_path):
    _, molecule, _ = native_fixture()
    result = run_external(molecule, protocol(), ResourceLimits(), tmp_path / "attempt", executable=tmp_path / "missing-xcfour",
                          process_runner=lambda *a, **k: pytest.fail("Must not launch"))
    assert result.status == "unavailable" and result.energy_hartree is None and not result.converged


def test_native_timeout_preserves_status_without_scientific_values(tmp_path):
    binary = tmp_path / "install" / "bin" / "xcfour"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 1\n")
    binary.chmod(0o700)
    genbas = binary.parent / "GENBAS"
    genbas.write_text("O:PVTZ\nfixture\nH:PVTZ\nfixture\n")
    p = protocol(genbas_path=str(genbas), genbas_sha256=hashlib.sha256(genbas.read_bytes()).hexdigest())
    _, molecule, _ = native_fixture()

    def infrastructure_timeout(command, folder, resources, **kwargs):
        assert resources.budget_seconds < 20
        out, err = folder / "engine.stdout", folder / "engine.stderr"
        out.write_text("deliberately empty infrastructure timeout fixture\n")
        err.write_text("")
        return ProcessResult(command, "timed-out", -15, .02, 0, str(out), str(err), "test budget")

    result = run_external(molecule, p, ResourceLimits(budget_seconds=20), tmp_path / "attempt",
                          executable=binary, process_runner=infrastructure_timeout)
    assert result.status == "timed-out" and result.energy_hartree is None and result.artifacts


@pytest.mark.parametrize("termination", ["converged", "deadline", "cancelled"])
def test_optimizer_uses_actual_gradient_callback_and_one_campaign_budget(tmp_path, monkeypatch, termination):
    """Analytical harmonic-function fixture; explicitly not a CFOUR calculation."""
    from threading import Event

    import topos.external_engines as adapter

    binary = tmp_path / "installation" / "bin" / "xcfour"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 1\n")
    binary.chmod(0o700)
    genbas = binary.parent / "GENBAS"
    genbas.write_text("H:PVTZ\nanalytical test basis placeholder\n")
    p = protocol(operation="optimize", genbas_path=str(genbas), genbas_sha256=hashlib.sha256(genbas.read_bytes()).hexdigest())
    molecule = Molecule(symbols=["H", "H"], coordinates=[[0, 0, 0], [0, 0, 1.2]])
    event, calls, clock = Event(), [], [1000.]
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock[0])

    def callback_fixture(raw, current, selected, **kwargs):
        xyz = np.asarray(current.coordinates) / BOHR_ANGSTROM
        vector = xyz[1] - xyz[0]
        distance = np.linalg.norm(vector)
        derivative = (distance - 1.5) * vector / distance
        return {"energy_hartree": .5 * (distance - 1.5)**2,
                "gradient_hartree_per_bohr": [(-derivative).tolist(), derivative.tolist()], "engine_version": "1.2"}

    monkeypatch.setattr(adapter, "parse_cfour_output", callback_fixture)

    def native_fixture_runner(command, folder, resources, **kwargs):
        calls.append(resources.budget_seconds)
        clock[0] += 5. if termination == "deadline" else .1
        if termination == "cancelled":
            event.set()
        out, err = folder / "engine.stdout", folder / "engine.stderr"
        out.write_text("analytical derivative callback fixture, not native quantum chemistry\n")
        err.write_text("")
        return ProcessResult(command, "completed", 0, .1, 0, str(out), str(err))

    result = run_external(molecule, p, ResourceLimits(budget_seconds=2), tmp_path / "run", executable=binary,
                          process_runner=native_fixture_runner, cancel_event=event)
    if termination == "converged":
        assert result.status == "completed" and result.converged and len(calls) >= 2
        assert result.energy_hartree == pytest.approx(0, abs=1e-14)
        assert np.linalg.norm(np.asarray(result.molecule.coordinates)[1] - result.molecule.coordinates[0]) == pytest.approx(1.5 * BOHR_ANGSTROM)
        assert result.diagnostics["optimization"]["native_cfour_optimizer"] is False
        assert all(a > b for a, b in zip(calls, calls[1:], strict=False))
    else:
        assert result.status == {"deadline": "timed-out", "cancelled": "cancelled"}[termination]
        assert len(calls) == 1 and result.converged is not True
