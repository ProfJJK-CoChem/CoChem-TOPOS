"""Zero-launch parser checks against exact retained native optimizer data.

The selected fixture is historical c889 scientific evidence, not a current
calculation, a complete RunStore, or scientific qualification of these tests.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from topos.models import RunRecord
from topos.scientific_references import ReferenceCase, _native_value, _orca_optimizer_stdout
from topos.storage import IntegrityError, file_digest

FIXTURE = Path(__file__).parent / 'fixtures/orca_reference_optimizer_stdout'


@pytest.fixture
def native_fixture(tmp_path, monkeypatch):
    import topos.engines

    def forbidden(*args, **kwargs):
        pytest.fail('Offline native importer must never launch an engine')

    monkeypatch.setattr(topos.engines, 'run_engine', forbidden)
    provenance = json.loads((FIXTURE / 'provenance.json').read_text())
    for name, digest in provenance['fixture_json_sha256'].items():
        assert file_digest(FIXTURE / name) == digest
    snapshot = tmp_path / 'relocated-parser-fixture'
    for name, identity in provenance['selected_exact_native_files'].items():
        path = FIXTURE / 'artifacts' / identity.get('stored_path', name)
        assert file_digest(path) == identity['sha256']
        assert path.stat().st_size == identity['size_bytes']
        original = snapshot / 'artifacts' / name
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, original)
    record = RunRecord.model_validate_json((FIXTURE / 'record.json').read_text())
    case = ReferenceCase.model_validate_json((FIXTURE / 'case.json').read_text())
    return case, record, snapshot


def test_genuine_optimizer_and_final_gradient_stdout_import_exact_optimizer(native_fixture):
    case, record, snapshot = native_fixture
    attempt = record.attempts[0]
    matches = [a for a in attempt.artifacts if Path(a.path).name == 'engine.stdout']
    assert len(matches) == 2 and len({a.sha256 for a in matches}) == 2
    value, proof = _native_value(case, record, SimpleNamespace(snapshot_path=lambda: snapshot))
    assert value == pytest.approx(-152.132799930134, abs=1e-12)
    assert proof['native_stdout_sha256'] == '4d3043c80f71348300a6c6c5d75e2a134b4577b240614f5ecbb8bb32b11df424'
    assert all(proof['optimization']['all_five_native_optimizer_conditions'].values())
    assert len(proof['optimization']['independent_final_gradient']) == 3
    assert record.status == 'completed' and record.validation_status == 'human-review'


@pytest.mark.parametrize('change', ['final-gradient', 'foreign-run', 'foreign-attempt', 'relative', 'traversal', 'missing'])
def test_optimizer_process_cannot_select_other_or_unbound_stdout(native_fixture, change):
    case, record, snapshot = native_fixture
    attempt = record.attempts[0]
    original = attempt.diagnostics['process']['stdout_path']
    if change == 'final-gradient':
        altered = original.replace('/engine.stdout', '/final-gradient/engine.stdout')
    elif change == 'foreign-run':
        altered = original.replace(record.run_id, 'run_foreign')
    elif change == 'foreign-attempt':
        altered = original.replace(attempt.attempt_id, 'attempt_foreign')
    elif change == 'relative':
        altered = f'{record.run_id}/attempts/{attempt.attempt_id}/engine.stdout'
    elif change == 'traversal':
        altered = original.replace('/engine.stdout', '/../' + attempt.attempt_id + '/engine.stdout')
    else:
        altered = None
    attempt.diagnostics['process']['stdout_path'] = altered
    with pytest.raises(IntegrityError, match='stdout'):
        _native_value(case, record, SimpleNamespace(snapshot_path=lambda: snapshot))


@pytest.mark.parametrize('change', ['duplicate', 'missing', 'raw-tamper', 'same-size-raw-tamper', 'foreign-run'])
def test_exact_optimizer_membership_and_raw_bytes_remain_mandatory(native_fixture, change):
    case, record, snapshot = native_fixture
    attempt = record.attempts[0]
    artifact = next(a for a in attempt.artifacts if a.path == f'attempts/{attempt.attempt_id}/engine.stdout')
    raw = snapshot / 'artifacts' / artifact.path
    if change == 'duplicate':
        attempt.artifacts.append(artifact.model_copy())
    elif change == 'missing':
        attempt.artifacts.remove(artifact)
    elif change == 'raw-tamper':
        raw.write_bytes(raw.read_bytes() + b'\nchanged\n')
    elif change == 'same-size-raw-tamper':
        data = raw.read_bytes()
        raw.write_bytes(b'X' + data[1:])
    else:
        attempt.run_id = 'run_foreign'
    with pytest.raises(IntegrityError, match='exactly one|artifact changed|different measured run'):
        _native_value(case, record, SimpleNamespace(snapshot_path=lambda: snapshot))


def test_foreign_same_basename_does_not_create_or_replace_optimizer_identity(native_fixture):
    case, record, snapshot = native_fixture
    expected = _native_value(case, record, SimpleNamespace(snapshot_path=lambda: snapshot))
    attempt = record.attempts[0]
    artifact = next(a for a in attempt.artifacts if a.path == f'attempts/{attempt.attempt_id}/engine.stdout')
    attempt.artifacts.append(artifact.model_copy(update={'path': 'unrelated-history/engine.stdout'}))
    assert _native_value(case, record, SimpleNamespace(snapshot_path=lambda: snapshot)) == expected


def test_optimizer_stdout_stage_is_selected_only_by_validated_refinement_contract(native_fixture, monkeypatch):
    import topos.ml_training

    _case, record, snapshot = native_fixture
    attempt, molecule = record.attempts[0], record.candidates[0].molecule
    artifact = next(a for a in attempt.artifacts if a.path == f'attempts/{attempt.attempt_id}/engine.stdout')
    selected = artifact.model_copy(update={'path': f'attempts/{attempt.attempt_id}/optimization-refinement-2/engine.stdout'})
    path = snapshot / 'artifacts' / selected.path
    path.parent.mkdir()
    shutil.copyfile(snapshot / 'artifacts' / artifact.path, path)
    attempt.artifacts.append(selected)
    attempt.diagnostics['process']['stdout_path'] = attempt.diagnostics['process']['stdout_path'].replace(
        '/engine.stdout', '/optimization-refinement-2/engine.stdout')
    # Selector-only control: model the stage returned by the already separately
    # tested full refinement validator, never claim fabricated chemistry/history.
    monkeypatch.setattr(topos.ml_training, '_optimization_refinement_contract',
                        lambda *args: [{'stage_directory': 'optimization-refinement-2'}])
    actual, retained = _orca_optimizer_stdout(attempt, molecule, snapshot)
    assert actual == selected and retained == path.resolve()
    attempt.diagnostics['process']['stdout_path'] = attempt.diagnostics['process']['stdout_path'].replace(
        '/optimization-refinement-2/', '/optimization-refinement-1/')
    with pytest.raises(IntegrityError, match='stage identity'):
        _orca_optimizer_stdout(attempt, molecule, snapshot)


def test_unvalidated_refinement_history_cannot_supply_stdout_stage(native_fixture):
    case, record, snapshot = native_fixture
    record.attempts[0].metadata['optimization_refinement'] = {'accepted_stage_directory': 'optimization-refinement-2'}
    with pytest.raises(IntegrityError, match='original geometry and bounded protocol'):
        _native_value(case, record, SimpleNamespace(snapshot_path=lambda: snapshot))
