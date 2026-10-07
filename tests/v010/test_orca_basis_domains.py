"""Manual-backed basis boundaries and exact DFT native naming; no fake solver."""
import pytest

from topos.engines import _orca_input, run_engine
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.orca_basis_names import resolve_orca_orbital_basis, validate_basis_elements


def water():
    return Molecule(symbols=['O', 'H', 'H'], coordinates=[[0, 0, 0], [.96, 0, 0], [-.24, .93, 0]])


def test_dft_jun_uses_exact_first_row_native_name_and_keeps_requested_identity(tmp_path):
    method = MethodSpec(engine='orca', method='wB97X-V', basis='jun-cc-pVTZ',
                        auxiliary_basis='def2/J', profile_id='orca-mapping-v4.1')
    deck = _orca_input(water(), method, ResourceLimits(), 'gradient')
    assert ' jun-cc-pV(T+d)Z ' in deck.splitlines()[0]
    assert ' jun-cc-pVTZ ' not in deck.splitlines()[0]
    result = run_engine(water(), method, ResourceLimits(), tmp_path/'absent-native', executable='/missing-orca')
    assert result.status == 'unavailable' and result.energy_hartree is None
    assert result.metadata['requested_method']['basis'] == 'jun-cc-pVTZ'
    assert result.metadata['orbital_basis_resolution']['orbital_space_changed'] is False
    assert result.metadata['orbital_basis_resolution']['native_basis'] == 'jun-cc-pV(T+d)Z'
    assert {item['role'] for item in result.metadata['basis_support_receipts']} == {'orbital', 'auxiliary_j'}


def test_second_row_bare_jun_is_rejected_before_native_probe(tmp_path):
    molecule = Molecule(symbols=['S'], coordinates=[[0, 0, 0]], multiplicity=3)
    method = MethodSpec(engine='orca', method='wB97X-V', basis='jun-cc-pVTZ', profile_id='orca-mapping-v4.1')
    def no_launch(*args, **kwargs):
        raise AssertionError('No native process may start with a known unsupported basis request')
    result = run_engine(molecule, method, ResourceLimits(), tmp_path/'attempt', executable='/missing-orca', process_runner=no_launch)
    assert result.status == 'unsupported' and result.energy_hartree is None
    assert 'not an alias outside H-Ne' in result.diagnostics['reason']
    assert not (tmp_path/'attempt').exists()


@pytest.mark.parametrize('element', ['He', 'Li', 'Be', 'Na', 'Mg'])
def test_orbital_f12_availability_does_not_imply_cabs_availability(element):
    assert validate_basis_elements('cc-pVDZ-F12', 'orbital', [element])['source_table'] == '2.23'
    with pytest.raises(ValueError, match='unsupported requested elements'):
        validate_basis_elements('cc-pVDZ-F12-CABS', 'cabs', [element])


@pytest.mark.parametrize('element', ['He', 'Li', 'Be', 'Ne', 'Na', 'Mg', 'Ar', 'Kr'])
def test_jk_holes_are_distinct_from_correlation_fitting_domain(element):
    with pytest.raises(ValueError, match='unsupported requested elements'):
        validate_basis_elements('cc-pVTZ/JK', 'auxiliary_jk', [element])
    assert validate_basis_elements('cc-pVTZ/C', 'auxiliary_c', [element])


def test_nonexistent_double_zeta_jk_and_seasonal_five_zeta_names_rejected():
    with pytest.raises(ValueError, match='no verified manual entry'):
        validate_basis_elements('cc-pVDZ/JK', 'auxiliary_jk', ['H', 'O'])
    with pytest.raises(ValueError, match='only for D/T/Q'):
        resolve_orca_orbital_basis(water(), 'jun-cc-pV5Z')


def test_cardinality_dependent_transition_metal_domains_do_not_expand_by_template():
    assert validate_basis_elements('cc-pVTZ/C', 'auxiliary_c', ['Sc'])
    with pytest.raises(ValueError, match='unsupported requested elements'):
        validate_basis_elements('cc-pVDZ/C', 'auxiliary_c', ['Sc'])
    assert validate_basis_elements('cc-pwCVTZ', 'orbital', ['Sc'])
    with pytest.raises(ValueError, match='unsupported requested elements'):
        validate_basis_elements('cc-pwCVDZ', 'orbital', ['Sc'])


@pytest.mark.parametrize(('name', 'role'), [('may-cc-pVTZ', 'orbital'), ('aug-cc-pwCVTZ', 'orbital'),
                                         ('cc-pVTZ-F12-CABS', 'auxiliary_c')])
def test_not_compiled_or_wrong_role_is_not_silently_accepted(name, role):
    with pytest.raises(ValueError, match='no verified manual entry'):
        validate_basis_elements(name, role, ['H', 'O'])
