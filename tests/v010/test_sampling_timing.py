"""Dispatch timing and recovery integrity; fixtures never stand in for chemistry."""
from __future__ import annotations

import copy
import json
import os
import shutil
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from topos.config import SystemConfig
from topos.entropy import SAMPLING_TIMING_SCOPE, run_matched_entropy, sampling_execution_timing
from topos.matrix_diversity import _sample
from topos.matrix_entropy import execute_entropy_recipe
from topos.matrix_workflow import MatrixInputs
from topos.models import MethodSpec, Molecule, ResourceLimits, RunRecord, RunRequest, utc_now
from topos.sampling import SamplingResult
from topos.storage import IntegrityError, RunStore, atomic_json, digest_json
from topos.workflow import Workflow


def water():
    return Molecule(symbols=['O', 'H', 'H'], coordinates=[[0, 0, 0], [.9584, 0, 0], [-.239, .927, 0]])


def method():
    return MethodSpec(engine='xtb', method='GFN2-xTB', profile_id='xtb-vtight-v1')


def assert_boundaries(start, finish, before, after):
    assert datetime.fromisoformat(before) <= datetime.fromisoformat(start) <= datetime.fromisoformat(finish) <= datetime.fromisoformat(after)


@pytest.mark.parametrize('mutation', ['naive', 'non-utc', 'backwards', 'scope', 'extra', 'missing', 'type'])
def test_malformed_sampling_dispatch_timing_rejected(mutation):
    timing = {'started_at': '2026-01-01T00:00:00+00:00', 'finished_at': '2026-01-01T00:00:01+00:00',
              'scope': SAMPLING_TIMING_SCOPE}
    if mutation == 'naive':
        timing['started_at'] = '2026-01-01T00:00:00'
    elif mutation == 'non-utc':
        timing['started_at'] = '2026-01-01T01:00:00+01:00'
    elif mutation == 'backwards':
        timing['finished_at'] = '2025-12-31T23:59:59+00:00'
    elif mutation == 'scope':
        timing['scope'] = 'time of evidence import, not its invocation'
    elif mutation == 'extra':
        timing['invented'] = True
    elif mutation == 'missing':
        timing.pop('started_at')
    else:
        timing['started_at'] = 1
    with pytest.raises(IntegrityError, match='execution wall-clock timing'):
        sampling_execution_timing(SamplingResult(status='unavailable', metadata={'execution_timing': timing}))


def test_undated_historical_sampling_is_never_assigned_import_times():
    assert sampling_execution_timing(SamplingResult(status='unavailable')) == (None, None)


def test_actual_unavailable_entropy_dispatch_retains_hash_bound_boundaries(tmp_path):
    before = utc_now()
    result = run_matched_entropy([water()], method(), ResourceLimits(threads=1, memory_mb=2048), tmp_path,
                                orca_executable='/missing-native-orca', crest_executable='/missing-native-crest',
                                xtb_executable='/missing-native-xtb')
    after = utc_now()
    assert result['status'] == 'partial'
    assert len(result['results']) == 2
    for row in result['results']:
        sampled = SamplingResult.model_validate(row['result'])
        assert sampled.status == 'unavailable' and sampled.metadata['execution_kind'] == 'not-executed'
        assert not sampled.ensemble and sampled.metadata.get('native_entropy') is None
        assert_boundaries(*sampling_execution_timing(sampled), before, after)
        receipt = json.loads((tmp_path / f"seed-0000-{row['engine']}.json").read_text())
        assert receipt['result'] == row['result'] and receipt['result_sha256']


def test_changed_entropy_timing_receipt_rejected_before_any_retry(tmp_path):
    kwargs = dict(orca_executable='/missing-native-orca', crest_executable='/missing-native-crest', xtb_executable='/missing-native-xtb')
    run_matched_entropy([water()], method(), ResourceLimits(threads=1, memory_mb=2048), tmp_path, **kwargs)
    path = tmp_path / 'seed-0000-goat.json'
    receipt = json.loads(path.read_text())
    receipt['result']['metadata']['execution_timing']['started_at'] = '2026-01-01T00:00:00+00:00'
    atomic_json(path, receipt)
    with pytest.raises(IntegrityError, match='timing identity changed'):
        run_matched_entropy([water()], method(), ResourceLimits(threads=1, memory_mb=2048), tmp_path, **kwargs)


def test_matrix_entropy_imports_original_dispatch_boundaries(tmp_path):
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development', executables={
        'orca': '/missing-native-orca', 'crest': '/missing-native-crest', 'xtb': '/missing-native-xtb'}))
    record = RunRecord(request=RunRequest(molecule=water(), purpose='matrix', matrix_row_id='T1-1d', threads=1, memory_mb=2048))
    store = RunStore(tmp_path / record.run_id)
    before = utc_now()
    assert not execute_entropy_recipe(workflow, record, store, MatrixInputs(entropy_seeds=[water()]), time.monotonic()+30, None)
    after = utc_now()
    assert record.status == 'partial' and len(record.attempts) == 2
    store.verify()
    for attempt in record.attempts:
        assert attempt.status == 'unavailable' and not attempt.quantities
        timing = attempt.metadata['execution_timing']
        assert (attempt.started_at, attempt.finished_at) == (timing['started_at'], timing['finished_at'])
        assert_boundaries(attempt.started_at, attempt.finished_at, before, after)


@pytest.mark.parametrize('engine', ['goat', 'crest'])
def test_diversity_records_actual_dispatch_and_durable_prelaunch_start(tmp_path, engine):
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development', executables={
        'orca': '/missing-native-orca', 'crest': '/missing-native-crest', 'xtb': '/missing-native-xtb'}))
    record = RunRecord(request=RunRequest(molecule=water(), purpose='matrix', matrix_row_id='T1-1mo', threads=1, memory_mb=2048))
    store = RunStore(tmp_path / record.run_id)
    before = utc_now()
    assert _sample(workflow, record, store, water(), 0, engine, MatrixInputs(), time.monotonic()+30, None) is None
    after = utc_now()
    attempt = record.attempts[0]
    assert attempt.status == 'unavailable' and record.status == 'unavailable'
    sampled = SamplingResult.model_validate(attempt.metadata['native_sampling_result'])
    assert (attempt.started_at, attempt.finished_at) == sampling_execution_timing(sampled)
    assert_boundaries(attempt.started_at, attempt.finished_at, before, after)
    manifests = list(store.snapshots.glob('*/manifest.json'))
    assert len(manifests) == 2
    # Durable snapshots include the actual prelaunch identity, before completion.
    statuses = []
    for path in manifests:
        manifest = json.loads(path.read_text())
        raw, _ = store._read_snapshot({'snapshot_id': path.parent.name, 'manifest_sha256': digest_json(manifest)})
        statuses.append(raw['attempts'][0])
    running = next(row for row in statuses if row['status'] == 'running')
    assert running['started_at'] == attempt.started_at and running['finished_at'] is None


def test_diversity_prelaunch_deadline_abort_has_truthful_end_without_execution(tmp_path, monkeypatch):
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development'))
    record = RunRecord(request=RunRequest(molecule=water(), purpose='matrix', matrix_row_id='T1-1mo'))
    store = RunStore(tmp_path / record.run_id)
    clock = iter([0., 200.])
    monkeypatch.setattr('topos.matrix_diversity.time', SimpleNamespace(monotonic=lambda: next(clock)))
    assert _sample(workflow, record, store, water(), 0, 'crest', MatrixInputs(), 100., None) is None
    attempt = record.attempts[0]
    assert attempt.status == record.status == 'timed-out'
    assert attempt.started_at and attempt.finished_at and not attempt.command and not attempt.quantities
    store.verify()


@pytest.fixture(scope='module')
def genuine_completed_entropy(tmp_path_factory):
    crest, xtb = os.environ.get('TOPOS_CREST_EXECUTABLE'), os.environ.get('TOPOS_XTB_EXECUTABLE')
    if not crest or not xtb or not shutil.which(crest) or not shutil.which(xtb):
        pytest.skip('authentic pinned CREST/xTB required for immutable timing recovery')
    folder = tmp_path_factory.mktemp('genuine-timed-entropy')
    kwargs = dict(orca_executable='/missing-native-orca', crest_executable=crest, xtb_executable=xtb)
    resources = ResourceLimits(threads=1, memory_mb=2048, budget_seconds=120)
    result = run_matched_entropy([water()], method(), resources, folder, **kwargs)
    assert result['results'][1]['result']['status'] == 'completed', result
    assert result['results'][1]['result']['metadata']['execution_kind'] == 'real'
    return folder, kwargs, resources, result


@pytest.mark.integration
def test_genuine_entropy_cache_retains_original_dispatch_times_without_reexecution(genuine_completed_entropy):
    folder, kwargs, resources, original = genuine_completed_entropy
    before = utc_now()
    result = run_matched_entropy([water()], method(), resources, folder, **kwargs)
    cached, previous = result['results'][1], original['results'][1]
    assert cached['reused_completed'] and cached['result'] == previous['result']
    assert datetime.fromisoformat(sampling_execution_timing(SamplingResult.model_validate(cached['result']))[1]) < datetime.fromisoformat(before)
    assert len(list(folder.rglob('crest.stdout'))) == 1


@pytest.mark.integration
def test_genuine_undated_historical_entropy_cache_keeps_missing_times(genuine_completed_entropy):
    folder, kwargs, resources, _ = genuine_completed_entropy
    receipt_path = folder / 'seed-0000-crest.json'
    original = json.loads(receipt_path.read_text())
    historical = copy.deepcopy(original)
    historical.pop('result_sha256')
    historical['result']['metadata'].pop('execution_timing')
    try:
        atomic_json(receipt_path, historical)
        result = run_matched_entropy([water()], method(), resources, folder, **kwargs)
        cached = result['results'][1]
        assert cached['reused_completed'] and cached['result'] == historical['result']
        assert sampling_execution_timing(SamplingResult.model_validate(cached['result'])) == (None, None)
        assert len(list(folder.rglob('crest.stdout'))) == 1
    finally:
        atomic_json(receipt_path, original)


@pytest.mark.integration
def test_timed_genuine_entropy_cache_requires_its_result_digest(genuine_completed_entropy):
    folder, kwargs, resources, _ = genuine_completed_entropy
    receipt_path = folder / 'seed-0000-crest.json'
    original = json.loads(receipt_path.read_text())
    unsigned = copy.deepcopy(original)
    unsigned.pop('result_sha256')
    try:
        atomic_json(receipt_path, unsigned)
        with pytest.raises(IntegrityError, match='timing identity changed'):
            run_matched_entropy([water()], method(), resources, folder, **kwargs)
    finally:
        atomic_json(receipt_path, original)


@pytest.mark.integration
def test_genuine_diversity_cache_preserves_native_times_and_rejects_changed_attempt_boundaries(tmp_path):
    crest, xtb = os.environ.get('TOPOS_CREST_EXECUTABLE'), os.environ.get('TOPOS_XTB_EXECUTABLE')
    if not crest or not xtb or not shutil.which(crest) or not shutil.which(xtb):
        pytest.skip('authentic pinned CREST/xTB required for diversity timing recovery')
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development', executables={'crest': crest, 'xtb': xtb}))
    record = RunRecord(request=RunRequest(molecule=water(), purpose='matrix', matrix_row_id='T1-1mo', threads=1, memory_mb=2048))
    store = RunStore(tmp_path / record.run_id)
    inputs = MatrixInputs()
    first = _sample(workflow, record, store, water(), 0, 'crest', inputs, time.monotonic()+120, None)
    assert first is not None and first.status == 'completed' and first.metadata['execution_kind'] == 'real'
    attempt = record.attempts[0]
    before = utc_now()
    second = _sample(workflow, record, store, water(), 0, 'crest', inputs, time.monotonic()+120, None)
    assert second == first and len(record.attempts) == 1
    assert datetime.fromisoformat(attempt.finished_at) < datetime.fromisoformat(before)
    assert len(list(store.run_dir.rglob('crest.stdout'))) >= 1
    original = attempt.started_at
    try:
        attempt.started_at = before
        with pytest.raises(IntegrityError, match='timestamps differ'):
            _sample(workflow, record, store, water(), 0, 'crest', inputs, time.monotonic()+120, None)
    finally:
        attempt.started_at = original
    store.verify()
