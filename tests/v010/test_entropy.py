"""Analytic partition identities and explicitly labelled native parser fixtures."""
import math

import pytest
from scipy import constants

from topos.engines import EngineParseError
from topos.entropy import (
    EntropyOptions,
    configurational_statistics,
    parse_crest_entropy,
    parse_goat_entropy,
    run_matched_entropy,
)
from topos.goat import goat_input
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.science import KB_HARTREE_K


def test_equal_energy_distinct_microstates_have_r_log_n_entropy():
    result = configurational_statistics([-5, -5], 298.15, [1, 2], degeneracy_definition='three independently established equal-energy microstates')
    assert result['populations'] == pytest.approx([1/3, 2/3])
    assert result['configurational_entropy_j_mol_k'] == pytest.approx(constants.R * math.log(3))
    assert result['relative_configurational_free_energy_hartree'] == pytest.approx(-KB_HARTREE_K * 298.15 * math.log(3))


def test_partition_shift_invariance_and_cold_limit():
    first = configurational_statistics([-10, -9], .1, [1, 1], degeneracy_definition='one state per conformer')
    second = configurational_statistics([0, 1], .1, [1, 1], degeneracy_definition='one state per conformer')
    assert first['populations'] == second['populations'] == [1, 0]
    assert first['configurational_entropy_j_mol_k'] == 0


@pytest.mark.parametrize('degeneracies', [[0], [1.5], [True], [], [1, 1]])
def test_no_invented_degeneracy(degeneracies):
    with pytest.raises(ValueError):
        configurational_statistics([-5], 298.15, degeneracies, degeneracy_definition='explicit')


GOAT_FIXTURE = '''DOCUMENTED OUTPUT FORMAT FIXTURE, NOT REAL CHEMISTRY
1 -34.346656 4.432 -0.551
2 -34.346656 4.528 -0.559
3 -34.346656 4.541 -0.560
Global minimum found!
Sconf at 298.15 K : 4.54 cal/(molK)
Gconf at 298.15 K : -0.56 kcal/mol
'''
CREST_FIXTURE = '''DOCUMENTED OUTPUT FORMAT FIXTURE, NOT REAL CHEMISTRY
Containing 3 conformers :
 S(conf) 1.000000
Convergence w.r.t. conformers: T
Convergence w.r.t. entropy   : T
FINAL ENTROPY (max conf.) : 1.000000
FINAL MOLECULAR ENTROPY AT T= 298.15 K
Sconf = 1.000000
+ δSrrho = -0.100000
= S(total) = 0.900000 (cal mol⁻¹ K⁻¹)
H(T)-H(0) = 0.100000
= G(total) = -0.168335 (H-T*S) (kcal mol⁻¹)
'''


def test_native_entropy_definitions_remain_separate_and_traceable():
    goat = parse_goat_entropy(GOAT_FIXTURE, 298.15)
    crest = parse_crest_entropy(CREST_FIXTURE)
    assert len(goat['trajectory']) == 3
    assert goat['sampling_converged'] and crest['sampling_converged']
    assert not goat['includes_intrinsic_rrho'] and crest['includes_intrinsic_rrho']
    assert not crest['extrapolated']


@pytest.mark.parametrize('mutation', ['missing', 'temperature', 'identity'])
def test_incomplete_or_inconsistent_entropy_rejected(mutation):
    raw = CREST_FIXTURE
    if mutation == 'missing':
        raw = raw.replace('Sconf =', 'missing =')
    elif mutation == 'temperature':
        raw = raw.replace('298.15 K', '310.00 K')
    else:
        raw = raw.replace('-0.168335', '-0.500000')
    with pytest.raises(EngineParseError):
        parse_crest_entropy(raw)


def test_entropy_native_keywords_and_unsupported_temperature(tmp_path):
    molecule = Molecule(symbols=['O', 'H', 'H'], coordinates=[[0,0,0],[.95,0,0],[-.24,.93,0]])
    method = MethodSpec(engine='xtb', method='GFN2-xTB', profile_id='xtb-vtight-v1')
    deck = goat_input(molecule, method, ResourceLimits(), entropy_options={'temperature_k': 298.15, 'min_delta_s_cal_mol_k': .1})
    assert 'GOAT-ENTROPY' in deck and 'CONFTEMP 298.15' in deck and 'MINDELS 0.1' in deck
    with pytest.raises(ValueError, match='298.15'):
        run_matched_entropy([molecule], method, ResourceLimits(), tmp_path, options=EntropyOptions(temperature_k=310))


def test_authentic_crest_entropy_water(tmp_path):
    import os
    import shutil

    from topos.sampling import run_crest

    crest, xtb = os.environ.get('TOPOS_CREST_EXECUTABLE'), os.environ.get('TOPOS_XTB_EXECUTABLE')
    if not crest or not xtb or not shutil.which(crest) or not shutil.which(xtb):
        pytest.skip('authentic pinned CREST/xTB required')
    molecule = Molecule(symbols=['O', 'H', 'H'], coordinates=[[0,0,0],[.9584,0,0],[-.239,.927,0]])
    result = run_crest(molecule, MethodSpec(engine='xtb', method='GFN2-xTB', profile_id='xtb-vtight-v1'),
                       ResourceLimits(budget_seconds=120, threads=2, memory_mb=2048), tmp_path / 'native',
                       executable=crest, xtb_executable=xtb, profile='crest-entropy-v1', energy_window_kcal_mol=12)
    assert result.status == 'completed', result.diagnostics
    assert result.algorithm == 'sMTD-iMTD entropy'
    assert result.metadata['execution_kind'] == 'real'
    entropy = result.metadata['native_entropy']
    assert entropy['sampling_converged'] and entropy['sconf_cal_mol_k'] == pytest.approx(0, abs=1e-6)
    assert len(entropy['trajectory']) >= 2
    assert result.artifacts and all(not __import__('pathlib').Path(a.path).is_symlink() for a in result.artifacts)
    assert result.metadata['native_symlink_materialization']


def test_authentic_completed_crest_entropy_reused_when_partner_unavailable(tmp_path):
    import os
    import shutil
    from pathlib import Path

    from topos.storage import IntegrityError

    crest, xtb = os.environ.get('TOPOS_CREST_EXECUTABLE'), os.environ.get('TOPOS_XTB_EXECUTABLE')
    if not crest or not xtb or not shutil.which(crest) or not shutil.which(xtb):
        pytest.skip('authentic pinned CREST/xTB required')
    molecule = Molecule(symbols=['O', 'H', 'H'], coordinates=[[0,0,0],[.9584,0,0],[-.239,.927,0]])
    method = MethodSpec(engine='xtb', method='GFN2-xTB', profile_id='xtb-vtight-v1')
    kwargs = {'orca_executable': '/missing-native-orca', 'crest_executable': crest, 'xtb_executable': xtb}
    first = run_matched_entropy([molecule], method, ResourceLimits(budget_seconds=120, threads=2, memory_mb=2048), tmp_path, **kwargs)
    assert first['status'] == 'partial'
    assert first['results'][0]['result']['status'] == 'unavailable'
    assert first['results'][1]['result']['status'] == 'completed'
    raw = list(tmp_path.rglob('crest.stdout'))
    assert len(raw) == 1
    second = run_matched_entropy([molecule], method, ResourceLimits(budget_seconds=30, threads=2, memory_mb=2048), tmp_path, **kwargs)
    assert second['status'] == 'partial' and second['results'][1]['reused_completed']
    assert second['results'][1]['result']['command'] == first['results'][1]['result']['command']
    assert list(tmp_path.rglob('crest.stdout')) == raw
    artifact = Path(first['results'][1]['result']['artifacts'][0]['path'])
    artifact.write_bytes(artifact.read_bytes() + b'\ntampered evidence\n')
    with pytest.raises(IntegrityError, match='artifact changed'):
        run_matched_entropy([molecule], method, ResourceLimits(budget_seconds=30, threads=2, memory_mb=2048), tmp_path, **kwargs)
