"""Matrix decision/math contracts and actual CREST-v4 acceptance.

Entropy dictionaries below are mathematical comparison fixtures, not claimed
native execution or parser evidence. No licensed ORCA success is fabricated.
"""
import os
import time
from threading import Event

import pytest

from topos.config import SystemConfig
from topos.correlated import CorrelatedMethod
from topos.goat import goat_input
from topos.matrix_diversity import reranking_protocol
from topos.matrix_entropy import entropy_comparison, execute_entropy_recipe
from topos.matrix_workflow import MatrixInputs, runtime_recipe_capabilities
from topos.method_matrix import MATRIX_REVISION, HardwareSpec, plan_route
from topos.models import MethodSpec, Molecule, ResourceLimits, RunRecord, RunRequest
from topos.sampling import SamplingResult, run_crest
from topos.storage import RunStore
from topos.workflow import Workflow


def water():
    return Molecule(symbols=['O', 'H', 'H'], coordinates=[[0, 0, 0], [.9584, 0, 0], [-.239, .927, 0]])


def entropy_rows(goat=1., crest=1.05, temperature=298.15, converged=True):
    return [{"seed_index": 0, "seed_geometry_sha256": "explicit-math-fixture", "engine": engine,
             "result": SamplingResult(status="completed", converged=converged,
              metadata={"native_entropy": {"temperature_k": temperature, "sconf_cal_mol_k": value,
                  "sampling_converged": converged, "definition": "mathematical comparison fixture",
                  "total_entropy_cal_mol_k": 900., "delta_srrho_cal_mol_k": 899.}}).model_dump()}
            for engine, value in (("goat", goat), ("crest", crest))]


def test_entropy_compares_configurational_terms_only():
    result = entropy_comparison(entropy_rows(), 1)
    assert result['convergence_evidence_satisfied'] and not result['exhaustive']
    assert result['pairs'][0]['absolute_difference_cal_mol_k'] == pytest.approx(.05)
    assert 'CREST total entropy' in result['excluded_terms']


@pytest.mark.parametrize('changes', [{'goat': 1., 'crest': 1.101}, {'converged': False}])
def test_entropy_difference_or_unconverged_sampling_cannot_certify_row(changes):
    assert not entropy_comparison(entropy_rows(**changes), 1)['convergence_evidence_satisfied']


@pytest.mark.parametrize('rows,count', [(entropy_rows()[:1], 1), (entropy_rows(), 2), (entropy_rows(temperature=300), 1)])
def test_entropy_requires_all_same_seed_pairs_and_matching_temperature(rows, count):
    with pytest.raises(ValueError):
        entropy_comparison(rows, count)


def test_entropy_matrix_cancelled_without_launch(tmp_path):
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development'))
    record = RunRecord(request=RunRequest(molecule=water(), purpose='matrix', matrix_row_id='T1-1d'))
    store = RunStore(tmp_path / record.run_id)
    event = Event()
    event.set()
    assert not execute_entropy_recipe(workflow, record, store, MatrixInputs(entropy_seeds=[water()]), time.monotonic()+30, event)
    assert record.status == 'cancelled' and not record.attempts


def test_native_diversity_preserves_documented_sloppy_structural_search():
    method = MethodSpec(engine='xtb', method='GFN2-xTB', profile_id='xtb-vtight-v1')
    deck = goat_input(water(), method, ResourceLimits(), diversity=True, energy_window_kcal_mol=60)
    assert 'GOAT-DIVERSITY SloppyOpt' in deck and 'TightOpt' not in deck
    assert 'RMSD 0.5' in deck and 'MAXEN 60' in deck
    with pytest.raises(ValueError, match='60 kcal/mol'):
        goat_input(water(), method, ResourceLimits(), diversity=True)
    with pytest.raises(ValueError):
        goat_input(water(), method, ResourceLimits(), diversity=True, energy_window_kcal_mol=60,
                   entropy_options={'temperature_k':298.15, 'min_delta_s_cal_mol_k': .1})


def test_coupled_cluster_reranking_needs_exact_protocol():
    with pytest.raises(ValueError, match='explicit DLPNO'):
        reranking_protocol(None)
    with pytest.raises(ValueError):
        reranking_protocol(CorrelatedMethod(method='MP2', orbital_basis='cc-pVDZ', frozen_core=True))
    supplied = CorrelatedMethod(method='DLPNO-CCSD(T1)', orbital_basis='cc-pVDZ-F12', auxiliary_c='cc-pVTZ/C',
                                frozen_core=True, pno_profile='TightPNO', tcutpno=1e-7)
    assert reranking_protocol(supplied) == supplied


def test_source_conflict_requires_exact_recorded_resolution():
    options = dict(hardware=HardwareSpec(cpu_threads=1, memory_mb=1024, fingerprint='test'),
                   capabilities=runtime_recipe_capabilities(), available_inputs=['molecule','fragments','fragment_states'],
                   symbols=['O','H'], multiplicity=1)
    unresolved = plan_route('T5-30min', **options)
    assert not unresolved.runnable and unresolved.row.source_conflicts
    resolved = plan_route('T5-30min', source_resolution='native-composite-rawinteraction-v1', **options)
    assert resolved.runnable and resolved.row.source_conflicts
    assert resolved.steps[0].options['separate_counterpoise'] is False
    assert any('no separate CP' in text for text in resolved.warnings)
    with pytest.raises(ValueError):
        plan_route('T5-10s', source_resolution='native-composite-rawinteraction-v1', **options)


def test_matrix_diversity_missing_protocol_cannot_degrade_to_simple_search(tmp_path):
    result = Workflow(tmp_path, config=SystemConfig(execution_backend='development')).run(
        RunRequest(molecule=water(), purpose='matrix', matrix_row_id='T1-1mo', matrix_revision=MATRIX_REVISION))
    assert result.status == 'unsupported' and not result.attempts
    assert 'cc_protocol' in result.metadata['termination_reason']


@pytest.mark.integration
def test_authentic_crest_v4_algorithm_and_immutable_native_evidence(tmp_path):
    crest = os.environ.get('TOPOS_CREST_EXECUTABLE')
    xtb = os.environ.get('TOPOS_XTB_EXECUTABLE')
    if not crest or not xtb:
        pytest.skip('Pinned actual CREST/xTB required')
    result = run_crest(water(), MethodSpec(engine='xtb', method='GFN2-xTB', profile_id='xtb-vtight-v1'),
                       ResourceLimits(budget_seconds=120, threads=2, memory_mb=2048), tmp_path,
                       executable=crest, xtb_executable=xtb, profile='crest-v4-v1', energy_window_kcal_mol=60)
    assert result.status == 'completed', result.diagnostics
    assert result.algorithm == 'iMTD-sMTD' and '--v4' in result.command
    assert result.metadata['execution_kind'] == 'real' and result.ensemble and result.artifacts
    assert result.metadata['native_symlink_materialization']
