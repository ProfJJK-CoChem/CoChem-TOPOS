"""Analytical rigid-rotor checks, not native electronic-structure acceptance."""
import numpy as np
import pytest
from scipy import constants

from topos.models import Molecule
from topos.native_mass_rotors import observed_mass_rotors


def diatomic():
    return Molecule(symbols=['H', 'H'], coordinates=[[0, 0, 0], [0, 0, .74]])


def test_diatomic_reduced_mass_rotor_and_printed_mass_interval():
    molecule = diatomic()
    mass, precision = 1.007825035, 5e-10
    result = observed_mass_rotors(molecule, [mass, mass], [precision, precision])
    moment = mass / 2 * .74**2
    expected = constants.h / (8 * np.pi**2 * moment * constants.atomic_mass * constants.angstrom**2) / 1e6
    assert result['constants_mhz'] == pytest.approx([None, expected, expected])
    assert result['geometry_class'] == 'linear'
    assert result['native_execution_verified'] is False
    assert result['mass_rounding_intervals_mhz'][0] is None
    for value, bounds in zip(result['constants_mhz'][1:], result['mass_rounding_intervals_mhz'][1:], strict=True):
        assert bounds[0] < value < bounds[1]
        assert bounds[0] == pytest.approx(expected * mass / (mass + precision), rel=1e-14)
        assert bounds[1] == pytest.approx(expected * mass / (mass - precision), rel=1e-14)


def test_mass_rounding_encloses_mixed_mass_changes_and_rigid_motion():
    molecule = Molecule(symbols=['O', 'H', 'H'], coordinates=[[0, 0, 0], [.7586, 0, .5043], [-.7586, 0, .5043]])
    masses, half_width = np.array([15.994914630, 1.007825035, 1.007825035]), np.array([.0005, .0005, .0005])
    result = observed_mass_rotors(molecule, masses.tolist(), half_width.tolist())
    for signs in np.random.default_rng(317).uniform(-1, 1, (20, 3)):
        varied = observed_mass_rotors(molecule, (masses + signs * half_width).tolist(), [1e-12]*3)
        for value, bounds in zip(varied['constants_mhz'], result['mass_rounding_intervals_mhz'], strict=True):
            assert bounds[0] <= value <= bounds[1]
    angle = .731
    rotation = np.array([[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
    transformed = molecule.model_copy(update={'coordinates': (np.asarray(molecule.coordinates) @ rotation + [3, -8, 4]).tolist()})
    moved = observed_mass_rotors(transformed, masses.tolist(), half_width.tolist())
    assert moved['constants_mhz'] == pytest.approx(result['constants_mhz'], rel=1e-13)
    assert moved['molecule_sha256'] != result['molecule_sha256']


@pytest.mark.parametrize(('masses', 'widths'), [([1.0], [1e-9]), ([1., float('nan')], [1e-9, 1e-9]),
    ([1., 1.], [0., 1e-9]), ([1., 1.], [-1., 1e-9]), ([1., 1.], [1.1, 1e-9]),
    ([1., 1.], [float('inf'), 1e-9])])
def test_incomplete_or_nonphysical_mass_evidence_rejected(masses, widths):
    with pytest.raises(ValueError, match='Complete finite positive'):
        observed_mass_rotors(diatomic(), masses, widths)


def test_no_table_substitution_and_mass_is_not_labelled_nuclear():
    result = observed_mass_rotors(diatomic(), [2., 2.], [1e-9, 1e-9])
    reference = observed_mass_rotors(diatomic(), [1., 1.], [1e-9, 1e-9])
    assert result['constants_mhz'][1] == pytest.approx(reference['constants_mhz'][1] / 2)
    assert result['masses_amu'] == [2., 2.]
    assert 'not DBOC nuclear masses' in result['mass_kind']
    assert 'no geometry, model' in result['uncertainty_scope']
