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


def test_f12_reference_energy_branch_is_separate_from_complete_geometry_rows():
    from topos.data.runtime_recipes import EXECUTABLE_ROWS, IMPLEMENTED_BRANCH_ROWS
    from topos.method_matrix import resolve_row, resolved_recipe

    assert 'T3O-1mo' in EXECUTABLE_ROWS and 'T3O-1mo' in IMPLEMENTED_BRANCH_ROWS
    steps, required = resolved_recipe(resolve_row('T3O-1mo'), 'orca-f12-reference-singlepoint-v1')
    assert steps[0].operation == 'energy' and steps[0].engine == 'orca'
    assert steps[0].options['geometry_optimized'] is False
    assert 'correlated_protocol' in required
    geometry_steps, geometry_inputs = resolved_recipe(resolve_row('T3O-1mo'), 'orca-f12d-numerical-geometry-tz-v1')
    assert geometry_steps[0].operation == 'numerical-energy-geometry'
    assert geometry_steps[0].options['native_analytic_gradient'] is False
    assert geometry_inputs == ['molecule', 'orca_numerical_geometry']
    assert resolved_recipe(resolve_row('T3O-1mo'))[0][0].engine == 'molpro'


def test_matched_entropy_rejects_different_seed_identity():
    rows = entropy_rows()
    rows[1]['seed_geometry_sha256'] = 'different-declared-geometry'
    with pytest.raises(ValueError, match='same exact seed'):
        entropy_comparison(rows, 1)


def test_ml_search_missing_checkpoint_cannot_launch(tmp_path):
    from topos.matrix_ml_search import execute_ml_search

    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development'))
    record = RunRecord(request=RunRequest(molecule=water(), purpose='matrix', matrix_row_id='T1-30min'))
    store = RunStore(tmp_path / record.run_id)
    with pytest.raises(ValueError, match='AIMNet2 checkpoint'):
        execute_ml_search(workflow, record, store, MatrixInputs(), None, time.monotonic()+30, None)
    assert not record.attempts


def test_ml_cache_requires_native_completion_and_confined_raw_evidence(tmp_path):
    from topos.matrix_ml_search import _verified_sampling_cache
    from topos.models import Artifact, Attempt
    from topos.storage import IntegrityError, digest_json, file_digest

    store = RunStore(tmp_path / 'run')
    attempt = Attempt(run_id='test-integrity-only', engine='orca', method='AIMNet2', status='completed')
    with pytest.raises(IntegrityError, match='real converged protocol'):
        _verified_sampling_cache(attempt, store)
    real = store.run_dir / 'real'
    real.mkdir()
    raw = real / 'retained.txt'
    raw.write_text('integrity-test bytes; not an engine output')
    (store.run_dir / 'linked-parent').symlink_to(real, target_is_directory=True)
    payload = {'integrity_test_only':True}
    attempt.converged = True
    attempt.validation_status = 'validated-for-protocol'
    attempt.metadata.update(execution_kind='real', native_sampling_result=payload,
                            native_sampling_result_sha256=digest_json(payload))
    attempt.artifacts = [Artifact(path='linked-parent/retained.txt', sha256=file_digest(raw), size_bytes=raw.stat().st_size)]
    with pytest.raises(IntegrityError, match='[Ss]ymlink'):
        _verified_sampling_cache(attempt, store)


def test_ml_enumerator_forwards_and_hashes_native_randomness_option(tmp_path, monkeypatch):
    """A nonexecuting availability stub checks wiring; no native result is fabricated."""
    from types import SimpleNamespace

    import topos.matrix_ml_search as module

    observed = []
    def unavailable(*args, **kwargs):
        observed.append(kwargs['deterministic'])
        return SamplingResult(status='unavailable', metadata={'execution_kind':'not-executed'})

    monkeypatch.setattr(module, 'run_goat_extopt', unavailable)
    workflow = SimpleNamespace(base_runtime=None)
    manifest = SimpleNamespace(backend='aimnet2', model_dump=lambda **kwargs: {'negative_wiring_test':True})
    allocation = SimpleNamespace(model_dump=lambda: dict(ml_threads=1, ml_memory_mb=256, orca_threads=1, orca_memory_mb=256))
    identities = []
    for deterministic in (False, True):
        record = RunRecord(request=RunRequest(molecule=water(), purpose='matrix', matrix_row_id='T1-30min', threads=2))
        store = RunStore(tmp_path / record.run_id)
        inputs = SimpleNamespace(ml_model=manifest, ml_search_allocation=allocation, ml_search_seeds=[],
            goat_options=SimpleNamespace(deterministic=deterministic, max_global_iterations=3),
            ml_max_requests=10, ml_receipt_mb=4, ml_gpu_index=None, ml_gpu_memory_mb=None)
        assert not module.execute_ml_search(workflow, record, store, inputs, None, time.monotonic()+10, None)
        assert record.status == 'unavailable' and not record.candidates
        identities.append(record.attempts[0].metadata['matrix_ml_search_identity'])
    assert observed == [False, True] and identities[0] != identities[1]


def test_gpu_parent_common_native_refinement_is_explicitly_cpu():
    from topos.matrix_workflow import _child_request

    parent = RunRequest(molecule=water(), purpose='matrix', matrix_row_id='T1-30min', device='gpu')
    child = _child_request(parent, water(), engine='orca', method='r2SCAN-3c', purpose='optimize', remaining=30.)
    assert child.device == 'cpu' and child.method == 'r2SCAN-3c'


def test_sampled_frame_must_preserve_original_topology_before_child_reference_changes():
    from topos.matrix_workflow import _validate_sampled_geometry

    reference = water()
    displaced = reference.model_copy(deep=True)
    displaced.coordinates[1][0] += 10
    with pytest.raises(ValueError, match='original inferred covalent topology'):
        _validate_sampled_geometry(reference, displaced)
    rigid = reference.model_copy(deep=True)
    rigid.coordinates = [[x+5, y-4, z+2] for x, y, z in reference.coordinates]
    _validate_sampled_geometry(reference, rigid)


@pytest.mark.integration
def test_actual_entropy_matrix_retains_completed_crest_when_orca_is_unavailable(tmp_path):
    crest, xtb = os.environ.get('TOPOS_CREST_EXECUTABLE'), os.environ.get('TOPOS_XTB_EXECUTABLE')
    if not crest or not xtb:
        pytest.skip('Pinned actual CREST/xTB required')
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development', executables={
        'orca':'/missing-licensed-orca', 'crest':crest, 'xtb':xtb}))
    request = RunRequest(molecule=water(), purpose='matrix', matrix_row_id='T1-1d', matrix_revision=MATRIX_REVISION,
                         threads=2, memory_mb=2048, budget_seconds=120,
                         matrix_inputs={'entropy_seeds':[water().model_dump(mode='json')]})
    result = workflow.run(request)
    assert result.status == 'partial' and not result.candidates
    crest_attempts = [a for a in result.attempts if a.engine == 'crest']
    assert len(crest_attempts) == 1 and crest_attempts[0].status == 'completed'
    assert crest_attempts[0].metadata['execution_kind'] == 'real'
    assert crest_attempts[0].quantities[0].name == 'configurational_entropy'
    store = RunStore(tmp_path / result.run_id)
    assert store.verify()
    resumed = workflow.resume(store.run_dir, invocation_budget_seconds=30)
    assert resumed.status == 'partial'
    assert [a.attempt_id for a in resumed.attempts if a.engine == 'crest'] == [crest_attempts[0].attempt_id]
    assert store.verify()
