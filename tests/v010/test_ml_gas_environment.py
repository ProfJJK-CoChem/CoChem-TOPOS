"""Explicit gas admission retains identity and rejects unsupported environment physics."""
import copy

import pytest

from topos.ml import ModelManifest, molecule_system_identity
from topos.models import Molecule


def model(backend='mace'):
    return ModelManifest(backend=backend, family='environment-admission-fixture',
        members=[{'path': '/not-loaded/domain-fixture.model', 'sha256': 'a' * 64,
                  'training_run_id': 'domain-check-only', 'source': 'fixture; no inference'}],
        package_version='0.3.16' if backend == 'mace' else '0.2.0',
        training_method='fixture; no inference', license_name='fixture', license_url='fixture',
        supported_elements=['H', 'O'], supported_charges=[0], supported_multiplicities=[1],
        precision='float64' if backend == 'mace' else 'float32', domain_reference='domain check only')


def water(environment):
    return Molecule(symbols=['O', 'H', 'H'], coordinates=[[0, 0, 0], [.96, 0, 0], [-.24, .93, 0]],
        isotopes=[16, 1, 1], atom_ids=['O', 'H1', 'H2'], environment=environment)


@pytest.mark.parametrize('backend', ['mace', 'aimnet2'])
@pytest.mark.parametrize('environment', [{}, {'phase': 'gas'}])
def test_explicit_isolated_gas_admission_preserves_all_input_identity(backend, environment):
    molecule = water(environment)
    before = copy.deepcopy(molecule.model_dump(mode='json'))
    identity = molecule_system_identity(molecule)
    model(backend).validate_molecule(molecule)
    assert molecule.model_dump(mode='json') == before
    assert molecule_system_identity(molecule) == identity


@pytest.mark.parametrize('environment', [
    {'phase': 'liquid'}, {'phase': 'Gas'}, {'phase': 'gas', 'solvent': 'water'},
    {'phase': 'gas', 'solvent': None}, {'solvent': 'water'}, {'phase': 'gas', 'periodic': True},
    {'phase': 'gas', 'periodic': False}, {'phase': 'gas', 'external_field': [0, 0, 0]},
    {'phase': 'gas', 'embedding': {}}, {'phase': 'gas', 'unknown_key': False},
])
def test_gas_label_cannot_hide_solvent_periodicity_fields_or_unknown_physics(environment):
    molecule = water(environment)
    before = copy.deepcopy(molecule.model_dump(mode='json'))
    with pytest.raises(ValueError, match='solvent, periodic or embedding'):
        model().validate_molecule(molecule)
    assert molecule.model_dump(mode='json') == before


def test_gas_admission_preserves_system_specific_isotope_and_environment_bindings():
    molecule = water({'phase': 'gas'})
    manifest = model().model_copy(update={'system_identity_sha256': molecule_system_identity(molecule)})
    manifest.validate_molecule(molecule)
    for altered in (molecule.model_copy(update={'isotopes': [18, 1, 1]}), water({})):
        with pytest.raises(ValueError, match='system-specific'):
            manifest.validate_molecule(altered)


@pytest.mark.parametrize('change,reason', [
    ({'charge': 1}, 'Charge or spin'), ({'multiplicity': 3}, 'Charge or spin'),
    ({'coordinates': [[0, 0, 0], [.1, 0, 0], [-.24, .93, 0]]}, 'minimum-distance'),
])
def test_gas_admission_keeps_state_and_geometry_domain_checks(change, reason):
    with pytest.raises(ValueError, match=reason):
        model().validate_molecule(water({'phase': 'gas'}).model_copy(update=change))
