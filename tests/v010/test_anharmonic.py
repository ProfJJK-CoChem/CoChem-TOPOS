"""Public native-format evidence and domain gates; no fabricated engine science."""
from pathlib import Path

import pytest
from scipy import constants

from topos.anharmonic import orca_vpt2_input, parse_orca_vpt2, run_orca_vpt2
from topos.engines import EngineParseError, _method_problem, _orca_input
from topos.models import MethodSpec, Molecule, ResourceLimits


def water():
    return Molecule(symbols=['O', 'H', 'H'], coordinates=[[0,0,0],[.95,0,0],[-.24,.93,0]])


def method():
    return MethodSpec(engine='orca', method='B3LYP', basis='def2-TZVPP', dispersion='D4',
                      profile_id='orca-vpt2-reference-v1')


def public_excerpt():
    return (Path(__file__).parents[1] / 'fixtures' / 'orca61-vpt2-public-furan.txt').read_text()


def test_public_native_vpt2_tables_preserve_rovibration_and_zero_point():
    result = parse_orca_vpt2(public_excerpt(), vibrational_modes=21)
    assert result['rotational_constants_cm1']['B_0'] == [.31297, .30645, .15475]
    assert result['rotational_constants_mhz']['B_0'][0] == pytest.approx(.31297 * constants.c / 1e4)
    assert result['zero_point_energy']['total_cm1'] == 15201.211
    assert result['zero_point_energy']['rovibrational_correction_cm1'] == 15.797
    assert len(result['fundamental_transitions']) == 21
    assert result['fundamental_transitions'][0]['fundamental_cm1'] == 601.909


@pytest.mark.parametrize('old,new', [
    ('B_0          0.31297', 'B_0          0.41297'),
    ('Total:                        15201.211', 'Total:                        15999.000'),
    ('0      616.272      601.909', '0      616.272      621.909'),
    ('x    0   -0.00000', 'x   99   -0.00000'),
    ('Zero-point ro-vibrational energy [1/cm]', 'Missing native zero point'),
])
def test_inconsistent_or_missing_anharmonic_tables_rejected(old, new):
    raw = public_excerpt()
    assert old in raw
    with pytest.raises(EngineParseError):
        parse_orca_vpt2(raw.replace(old, new), vibrational_modes=21)


def test_vpt2_input_enforces_documented_precision_and_actual_d4():
    deck = orca_vpt2_input(water(), method(), ResourceLimits())
    assert '! B3LYP ExtremeSCF DEFGRID3 D4 def2-TZVPP RIJCOSX def2/J VPT2' in deck
    for setting in ['Z_Tol 1e-14', 'HessianCutoff 1e-12', 'AnharmDisp 0.05', 'PrintLevel 4']:
        assert setting in deck
    assert 'Pickettname "pickett.txt"' in deck
    assert ' Freq' not in deck and 'Engrad' not in deck
    opt = _orca_input(water(), method(), ResourceLimits(), 'optimize')
    assert 'TolMaxG 1e-7' in opt and 'TolRMSG 3e-8' in opt
    assert _method_problem(method(), ResourceLimits(), 'gradient') is None
    assert _method_problem(method().model_copy(update={'method': 'HF'}), ResourceLimits(), 'gradient')


@pytest.mark.parametrize('change', [{'profile_id':'orca-mapping-v4.1'}, {'constraints':{'frozen_atoms':[0]}},
                                    {'method':'CCSD(T)'}, {'dispersion':'D3BJ'}])
def test_incompatible_vpt2_method_rejected(change):
    with pytest.raises(ValueError):
        orca_vpt2_input(water(), method().model_copy(update=change), ResourceLimits())


def test_linear_and_isotope_references_fail_closed():
    linear = Molecule(symbols=['O','C','O'], coordinates=[[0,0,-1.16],[0,0,0],[0,0,1.16]])
    with pytest.raises(ValueError, match='nonlinear'):
        orca_vpt2_input(linear, method(), ResourceLimits())
    isotopic = water().model_copy(update={'isotopes':[18,None,None]})
    with pytest.raises(ValueError, match='isotope'):
        orca_vpt2_input(isotopic, method(), ResourceLimits())


def test_missing_declaration_and_binary_do_not_create_anharmonic_values(tmp_path):
    result = run_orca_vpt2(water(), method(), ResourceLimits(), tmp_path / 'missing-declaration')
    assert result.status == 'unsupported' and 'vpt2' not in result.metadata
    result = run_orca_vpt2(water(), method(), ResourceLimits(), tmp_path / 'missing-binary',
                           executable='/missing-native-orca', semirigid_modes=True)
    assert result.status == 'unavailable' and 'vpt2' not in result.metadata


def test_anharmonic_and_dispersion_citations_require_actual_execution():
    from topos.references import executed_references

    attempt = {'attempt_id': 'protocol-fixture', 'engine': 'orca', 'method': 'B3LYP',
               'engine_version': '6.1.1', 'status': 'failed', 'command': ['orca', 'anharmonic.inp'],
               'metadata': {'execution_kind': 'real', 'requested_method': method().model_dump(),
                            'derivative_kind': 'native-VPT2-analytic-Hessian-differences'}}
    refs, _ = executed_references({'attempts': [attempt]})
    dois = {r.get('doi') for r in refs}
    assert {'10.1063/1.5090222', '10.1063/1.464913', '10.1103/PhysRevB.37.785', '10.1063/1.461259'} <= dois
    attempt['command'] = []
    refs, _ = executed_references({'attempts': [attempt]})
    assert not refs


def test_authentic_orca_vpt2_water_and_completed_recovery(tmp_path):
    import os
    import shutil

    from topos.engines import run_engine

    binary = os.environ.get('TOPOS_ORCA_EXECUTABLE')
    if not binary or not shutil.which(binary):
        pytest.skip('licensed ORCA 6.1.1 must be provisioned explicitly')
    resources = ResourceLimits(budget_seconds=600, threads=2, memory_mb=4096)
    optimized = run_engine(water(), method(), resources, tmp_path / 'strict-optimize', executable=binary)
    assert optimized.status == 'completed', optimized.diagnostics
    assert optimized.molecule is not None
    result = run_orca_vpt2(optimized.molecule, method(), resources, tmp_path / 'native-vpt2',
                           executable=binary, semirigid_modes=True)
    assert result.status == 'completed', result.diagnostics
    assert result.metadata['execution_kind'] == 'real'
    native = result.metadata['vpt2']
    assert len(native['fundamental_transitions']) == 3
    assert native['zero_point_energy']['total_cm1'] > 0
    assert all(value > 0 for value in native['rotational_constants_cm1']['B_0'])
    replay = run_orca_vpt2(optimized.molecule, method(), resources, tmp_path / 'native-vpt2',
                           executable=binary, semirigid_modes=True)
    assert replay.metadata['reused_completed_vpt2']
    assert replay.command == result.command
