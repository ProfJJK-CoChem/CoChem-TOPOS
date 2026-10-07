"""Public native-format evidence and domain gates; no fabricated engine science."""
from pathlib import Path

import pytest
from scipy import constants

from topos.anharmonic import orca_vpt2_input, parse_orca_vpt2, run_orca_vpt2, vpt2_execution_policy
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


@pytest.mark.parametrize('threads,memory', [(1, 4096), (2, 4096), (4, 8192)])
def test_vpt2_serial_policy_retains_original_maxcore_and_base_authority(tmp_path, threads, memory):
    from topos.base_integration import _orca_deck_allocation

    resources = ResourceLimits(budget_seconds=1200, threads=threads, memory_mb=memory)
    policy = vpt2_execution_policy(resources)
    deck = orca_vpt2_input(water(), method(), resources)
    expected_maxcore = int(memory * .75 / threads)
    assert '%pal nprocs 1 end' in deck
    assert f'%maxcore {expected_maxcore}\n' in deck
    assert policy['requested_workers'] == threads and policy['effective_workers'] == 1
    assert policy['native_maxcore_mb'] == expected_maxcore
    assert policy['total_memory_ceiling_mb'] == memory
    (tmp_path / 'anharmonic.inp').write_text(deck)
    effective = resources.model_copy(update={'threads': 1})
    # This is the actual native-deck authority path used by BaseRuntime.
    assert _orca_deck_allocation(['orca', 'anharmonic.inp'], tmp_path, effective) == expected_maxcore
    assert effective.memory_mb == resources.memory_mb and effective.budget_seconds == resources.budget_seconds
    assert f'%pal nprocs {threads} end' in _orca_input(water(), method(), resources, 'gradient')


def test_vpt2_policy_does_not_turn_a_requested_gpu_into_cpu():
    with pytest.raises(ValueError, match='requested GPU'):
        orca_vpt2_input(water(), method(), ResourceLimits(device='gpu', threads=2, memory_mb=4096))


def test_vpt2_recovery_rejects_policy_change_before_native_execution(tmp_path):
    import json

    from topos.storage import IntegrityError

    resources = ResourceLimits(threads=2, memory_mb=4096)
    workdir = tmp_path / 'protocol'
    unavailable = run_orca_vpt2(water(), method(), resources, workdir,
                               executable='/missing-native-orca', semirigid_modes=True)
    assert unavailable.status == 'unavailable'
    manifest = workdir / 'vpt2-protocol.json'
    protocol = json.loads(manifest.read_text())
    assert protocol['resources']['threads'] == 2
    assert protocol['effective_resources']['threads'] == 1
    assert protocol['execution_policy']['native_maxcore_mb'] == 1536
    protocol['execution_policy']['native_maxcore_mb'] = 3072
    manifest.write_text(json.dumps(protocol))
    with pytest.raises(IntegrityError, match='recovery protocol changed'):
        run_orca_vpt2(water(), method(), resources, workdir,
                      executable='/missing-native-orca', semirigid_modes=True)


@pytest.mark.parametrize('case', ['extended', 'licensed_pytest'])
def test_retained_mpi_pickett_failures_cannot_be_read_as_anharmonic_science(case):
    import hashlib
    import json

    folder = Path(__file__).parent / 'fixtures' / 'orca_vpt2_mpi_property_failure'
    provenance = json.loads((folder / 'provenance.json').read_text())
    for artifact in provenance['artifacts']:
        payload = (folder / artifact['path']).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == artifact['sha256']
        assert len(payload) == artifact['bytes']
    raw = (folder / f'{case}.stdout').read_text()
    assert 'writing data to file in Pickett format' in raw
    if case == 'extended':
        assert 'ORCA finished by error termination in PROPERTIES' in raw
        assert 'mpirun -np 2' in raw and 'orca_prop_mpi' in raw
    else:
        assert raw.rstrip().endswith('writing data to file in Pickett format ...')
    assert '%pal nprocs 2 end' in (folder / f'{case}.inp').read_text()
    assert 'ORCA TERMINATED NORMALLY' not in raw
    with pytest.raises(EngineParseError, match='analysis header missing'):
        parse_orca_vpt2(raw, vibrational_modes=3)


@pytest.mark.parametrize('change', [{'profile_id':'orca-mapping-v4.1'}, {'constraints':{'frozen_atoms':[0]}},
                                    {'method':'CCSD(T)'}, {'dispersion':'D3BJ'}])
def test_incompatible_vpt2_method_rejected(change):
    with pytest.raises(ValueError):
        orca_vpt2_input(water(), method().model_copy(update=change), ResourceLimits())


@pytest.mark.parametrize('functional', ['wB97X-V', 'wB97M-V'])
def test_vv10_native_analytic_derivatives_are_explicitly_unavailable(functional, tmp_path):
    spec = method().model_copy(update={'method': functional, 'dispersion': None})
    with pytest.raises(ValueError, match='VV10/NL second derivatives'):
        orca_vpt2_input(water(), spec, ResourceLimits())
    result = run_orca_vpt2(water(), spec, ResourceLimits(), tmp_path / 'must-not-execute', semirigid_modes=True)
    assert result.status == 'unsupported'
    assert 'dispersioncorrections.html' in result.diagnostics['reason']
    assert not result.command and not (tmp_path / 'must-not-execute').exists()


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
    process_runner = None
    if os.environ.get('TOPOS_REQUIRE_BASE') == '1':
        from topos.base_integration import BaseRuntime

        runtime = BaseRuntime()
        binary = runtime.resolve_executable('orca', binary)
        process_runner = runtime.run_process
    resources = ResourceLimits(budget_seconds=600, threads=2, memory_mb=4096)
    optimized = run_engine(water(), method(), resources, tmp_path / 'strict-optimize', executable=binary,
                           process_runner=process_runner)
    assert optimized.status == 'completed', optimized.diagnostics
    assert optimized.molecule is not None
    result = run_orca_vpt2(optimized.molecule, method(), resources, tmp_path / 'native-vpt2',
                           executable=binary, semirigid_modes=True, process_runner=process_runner)
    assert result.status == 'completed', result.diagnostics
    assert result.metadata['execution_kind'] == 'real'
    assert result.metadata['requested_resources']['threads'] == 2
    assert result.metadata['native_execution_resources']['threads'] == 1
    assert result.metadata['native_execution_resources']['memory_mb'] == resources.memory_mb
    assert result.metadata['execution_policy']['native_maxcore_mb'] == 1536
    assert result.metadata['reference_hessian_result']['metadata']['requested_method'] == method().model_dump(mode='json')
    native = result.metadata['vpt2']
    assert len(native['fundamental_transitions']) == 3
    assert native['zero_point_energy']['total_cm1'] > 0
    assert all(value > 0 for value in native['rotational_constants_cm1']['B_0'])
    from topos.rotational_transfer import RotationalTransferOptions, transfer_rotational_correction

    # Actual native derivative evidence drives transfer onto the same geometry
    # here. This validates the mass/frame/algebra boundary, not an R2 optimization.
    transferred = transfer_rotational_correction(optimized.molecule, result,
                                                RotationalTransferOptions(semirigid_same_basin=True))
    assert transferred['native_execution_verified'] is True
    assert len(transferred['constants_ghz']) == 3
    altered = result.model_copy(deep=True)
    altered.metadata['reference_hessian_result']['metadata']['hessian_hartree_per_bohr2'][0][0] += .01
    with pytest.raises(ValueError, match='raw derivatives'):
        transfer_rotational_correction(optimized.molecule, altered, RotationalTransferOptions(semirigid_same_basin=True))
    changed_policy = result.model_copy(deep=True)
    changed_policy.metadata['execution_policy']['effective_workers'] = 2
    with pytest.raises(ValueError, match='execution policy'):
        transfer_rotational_correction(optimized.molecule, changed_policy,
                                       RotationalTransferOptions(semirigid_same_basin=True))
    changed_allocation = result.model_copy(deep=True)
    changed_allocation.metadata['native_execution_resources']['threads'] = 2
    with pytest.raises(ValueError, match='process allocation'):
        transfer_rotational_correction(optimized.molecule, changed_allocation,
                                       RotationalTransferOptions(semirigid_same_basin=True))
    replay = run_orca_vpt2(optimized.molecule, method(), resources, tmp_path / 'native-vpt2',
                           executable=binary, semirigid_modes=True, process_runner=process_runner)
    assert replay.metadata['reused_completed_vpt2']
    assert replay.command == result.command
