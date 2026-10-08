"""Native imports versus numerical identities; neither establishes literature accuracy."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from topos.models import Molecule, RunRecord, RunRequest
from topos.reference_thermal import (
    FREQUENCY_DEFINITION,
    ROTOR_DEFINITION,
    _close,
    _reconstruct_hessian,
    extract_reference_value,
)
from topos.science import harmonic_analysis
from topos.storage import IntegrityError, RunStore, confined_file
from topos.thermochemistry import rrho_thermochemistry


def water():
    return Molecule(symbols=["O", "H", "H"], isotopes=[16, 1, 1],
                    coordinates=[[0, 0, 0], [.9584, 0, 0], [-.239, .927, 0]])


def case_for(record, observable="gibbs_energy"):
    definitions = {"gibbs_energy": "ideal-gas-RRHO; explicit reference state and symmetry",
                   "harmonic_frequencies": FREQUENCY_DEFINITION,
                   "equilibrium_rotational_constants": ROTOR_DEFINITION}
    units = {"gibbs_energy": "hartree", "harmonic_frequencies": "cm^-1", "equilibrium_rotational_constants": "GHz"}
    return SimpleNamespace(request=record.request, observable=observable, definition=definitions[observable],
                           units=units[observable], geometry_role="harmonic-minimum",
                           engine_version="6.7.1" if record.request.engine == "xtb" else "6.1.1")


def quadratic_pairs(matrix, central_gradient, *, step=.005):
    """An analytic differentiation oracle, explicitly not a native calculation."""
    gradients, energies = [central_gradient.reshape(-1, 3)], [-10.0]
    for column in range(matrix.shape[0]):
        for sign in (1, -1):
            displacement = np.zeros(matrix.shape[0])
            displacement[column] = sign * step
            gradients.append((central_gradient + matrix @ displacement).reshape(-1, 3))
            energies.append(float(-10 + central_gradient @ displacement + .5 * displacement @ matrix @ displacement))
    return gradients, energies


def test_coupled_quadratic_reconstruction_is_an_independent_mathematical_identity():
    rng = np.random.default_rng(314)
    factor = rng.normal(size=(9, 9))
    expected = factor.T @ factor
    central_gradient = np.linspace(-1e-6, 1e-6, 9)
    gradients, energies = quadratic_pairs(expected, central_gradient)
    observed, checks = _reconstruct_hessian(gradients, energies, .005)
    np.testing.assert_allclose(observed, expected, atol=1e-13, rtol=0)
    assert checks["max_antisymmetry_hartree_per_bohr2"] < 1e-12
    assert checks["max_energy_gradient_difference_hartree_per_bohr"] < 1e-12
    assert checks["step_convergence"] == "not-established-by-one-displacement-size"


@pytest.mark.parametrize("alteration", ["missing", "nonfinite", "asymmetric", "nonconservative"])
def test_invalid_derivative_field_cannot_become_a_harmonic_reference(alteration):
    matrix = np.eye(9)
    if alteration == "asymmetric":
        matrix[0, 1] = .1
    gradients, energies = quadratic_pairs(matrix, np.zeros(9))
    if alteration == "missing":
        gradients.pop()
    elif alteration == "nonfinite":
        gradients[3][0, 0] = np.nan
    elif alteration == "nonconservative":
        energies[1] += .001
    with pytest.raises(IntegrityError):
        _reconstruct_hessian(gradients, energies, .005)


def test_numerical_rrho_reference_separates_symmetry_temperature_isotopes_and_standard_state():
    molecule = water()
    # Positive quadratic Cartesian tensor is only a numerical oracle. It is
    # projected by the same physical algebra, with no claim of chemical modes.
    analysis = harmonic_analysis(molecule, np.eye(9), gradient_hartree_per_bohr=np.zeros((3, 3)))
    first = rrho_thermochemistry(molecule, -10., analysis, symmetry_number=2)
    concentration = rrho_thermochemistry(molecule, -10., analysis, symmetry_number=2, concentration_mol_l=1.)
    heated = rrho_thermochemistry(molecule, -10., analysis, symmetry_number=2, temperature_k=400.)
    assert concentration["standard_state"]["kind"] == "ideal-concentration-reference"
    assert concentration["gibbs_hartree"] != first["gibbs_hartree"] != heated["gibbs_hartree"]
    assert first["isotope_provenance"][0]["mass_number"] == 16
    changed = dict(first, symmetry_number=1)
    with pytest.raises(IntegrityError, match="symmetry_number"):
        _close(changed, first, label="RRHO")


@pytest.mark.parametrize("alteration", ["units", "geometry", "constraint", "request", "unsupported"])
def test_reference_contract_rejects_substitution_before_native_import(tmp_path, alteration):
    request = RunRequest(molecule=water(), purpose="thermochemistry", budget_seconds=120.)
    record = RunRecord(request=request)
    case = case_for(record)
    if alteration == "units":
        case.units = "GHz"
    elif alteration == "geometry":
        case.geometry_role = "supplied-input"
    elif alteration == "constraint":
        record.request.constraints = {"freeze_atoms": [0]}
    elif alteration == "request":
        case.request = request.model_copy(update={"temperature_k": 400.})
    else:
        case.observable = "ground_state_rotational_constants"
    with pytest.raises(LookupError if alteration == "unsupported" else IntegrityError):
        extract_reference_value(case, record, RunStore(tmp_path))


@pytest.fixture(scope="module")
def native_thermal(tmp_path_factory):
    from topos.config import SystemConfig
    from topos.workflow import Workflow

    executable = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if executable is None:
        pytest.skip("Actual xTB 6.7.1 required; numerical test doubles cannot establish native thermal import")
    output = tmp_path_factory.mktemp("reference-thermal-native")
    record = Workflow(output, config=SystemConfig(executables={"xtb": executable}, execution_backend="development")).run(
        RunRequest(molecule=water(), purpose="thermochemistry", budget_seconds=120.,
                   temperature_k=325., thermochemistry_options={"symmetry_number": 2, "concentration_mol_l": 1.,
                                                               "frequency_scale": .98}))
    assert record.status == "completed", record.metadata.get("termination_reason")
    return record, RunStore(output / record.run_id)


@pytest.mark.integration
@pytest.mark.parametrize("observable", ["gibbs_energy", "harmonic_frequencies", "equilibrium_rotational_constants"])
def test_actual_xtb_native_import_recomputes_all_derivatives_and_declared_physics(native_thermal, observable):
    record, store = native_thermal
    value, proof = extract_reference_value(case_for(record, observable), record, store)
    candidate = next(candidate for candidate in record.candidates if candidate.status == "eligible")
    assert len(proof["native_derivatives"]) == len(proof["derivative_attempt_ids"]) == 19
    assert len({entry["executable_sha256"] for entry in proof["native_derivatives"]}) == 1
    assert all(len(entry["native_artifacts"]) == 6 for entry in proof["native_derivatives"])
    assert all("command" not in entry and not Path(entry["executable_basename"]).is_absolute()
               for entry in proof["native_derivatives"])
    assert proof["scientific_accuracy_certified"] is False
    if observable == "gibbs_energy":
        assert value == pytest.approx(candidate.gibbs_hartree, abs=1e-10)
        thermal = proof["thermochemistry"]
        assert thermal["temperature_k"] == 325. and thermal["symmetry_number"] == 2
        assert thermal["frequency_scale"] == .98
        assert thermal["standard_state"]["kind"] == "ideal-concentration-reference"
        assert value != candidate.energy_hartree
    elif observable == "harmonic_frequencies":
        assert len(value) == 3 and min(value) > 0
        assert value == pytest.approx(candidate.metadata["frequency_analysis"]["frequencies_cm1"], abs=1e-7)
    else:
        assert value == pytest.approx(candidate.metadata["rotational_constants"]["constants_ghz"], abs=1e-7)


def portable_store(original, target):
    """Relocate only real immutable evidence; no original live scratch required."""
    target.mkdir()
    shutil.copyfile(original.current, target / "CURRENT.json")
    snapshot = original.snapshot_path()
    shutil.copytree(snapshot, target / "snapshots" / snapshot.name)
    return RunStore(target)


@pytest.mark.integration
def test_native_thermal_import_is_portable_and_ignores_live_scratch(native_thermal, tmp_path):
    record, original = native_thermal
    store = portable_store(original, tmp_path / "relocated")
    value, proof = extract_reference_value(case_for(record), record, store)
    assert value == pytest.approx(next(c for c in record.candidates if c.status == "eligible").gibbs_hartree, abs=1e-10)
    assert proof["snapshot_id"] == original.verify()["snapshot_id"]
    assert not (store.run_dir / "attempts").exists()


@pytest.mark.integration
def test_native_thermal_raw_derivative_tampering_is_rejected(native_thermal, tmp_path):
    record, original = native_thermal
    store = portable_store(original, tmp_path / "tampered")
    source = next(a for a in record.attempts if a.metadata.get("advanced_role") == "physical-hessian-derivative")
    gradient = next(entry for entry in source.artifacts if Path(entry.path).name == "gradient")
    raw = confined_file(store.snapshot_path(), "artifacts/" + gradient.path)
    raw.write_text(raw.read_text().replace("SCF energy", "different energy", 1))
    with pytest.raises(IntegrityError, match="checksum"):
        extract_reference_value(case_for(record), record, store)


@pytest.mark.integration
@pytest.mark.parametrize("alteration", ["definition", "version", "modified-record"])
def test_native_thermal_observable_context_cannot_be_relabelled(native_thermal, alteration):
    record, store = native_thermal
    case = case_for(record)
    if alteration == "definition":
        case.definition = "electronic energy without thermal corrections"
    elif alteration == "version":
        case.engine_version = "6.6.0"
    else:
        record = record.model_copy(deep=True)
        record.candidates[-1].gibbs_hartree += .1
    with pytest.raises(IntegrityError):
        extract_reference_value(case, record, store)


@pytest.mark.integration
def test_actual_licensed_orca_ordinary_thermal_reference_import(tmp_path):
    """Runs only with an explicitly provisioned licensed ORCA; otherwise pending."""
    from topos.config import SystemConfig
    from topos.workflow import Workflow

    binary = os.environ.get("TOPOS_ORCA_EXECUTABLE")
    if not binary or not shutil.which(binary):
        pytest.skip("Licensed ORCA 6.1.1 must be provisioned explicitly for native thermal-reference acceptance")
    backend = "base" if os.environ.get("TOPOS_REQUIRE_BASE") == "1" else "development"
    workflow = Workflow(tmp_path, config=SystemConfig(executables={"orca": binary}, execution_backend=backend))
    record = workflow.run(RunRequest(
        molecule=water(), engine="orca", method="r2SCAN-3c", engine_version="6.1.1", profile_id="orca-mapping-v4.2",
        purpose="thermochemistry", budget_seconds=1200., memory_mb=2048, threads=1,
        thermochemistry_options={"symmetry_number": 2}))
    assert record.status == "completed", record.metadata.get("termination_reason")
    store = RunStore(tmp_path / record.run_id)
    candidate = next(c for c in record.candidates if c.status == "eligible")
    for observable in ("gibbs_energy", "harmonic_frequencies", "equilibrium_rotational_constants"):
        value, proof = extract_reference_value(case_for(record, observable), record, store)
        assert len(proof["native_derivatives"]) == 19
        assert all(p["engine_version"] == "6.1.1" for p in proof["native_derivatives"])
        assert proof["scientific_accuracy_certified"] is False
        if observable == "gibbs_energy":
            assert value == pytest.approx(candidate.gibbs_hartree, abs=2e-7)
        else:
            assert len(value) == 3 and min(value) > 0
