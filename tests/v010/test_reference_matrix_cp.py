"""Import the actual T5-1h parent state without changing human review.

Test-created RunStores wrap selected genuine c889 CP data. They are offline
parser controls, never fresh calculations or scientific qualification receipts.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from topos.models import RunRecord
from topos.reference_interaction import extract_reference_value
from topos.scientific_references import ReferenceCase
from topos.storage import IntegrityError, RunStore, digest_json, file_digest

FIXTURE = Path(__file__).parent / 'fixtures/orca_reference_matrix_cp'


@pytest.fixture
def native_cp(tmp_path, monkeypatch):
    import topos.engines

    def forbidden(*args, **kwargs):
        pytest.fail('Offline CP importer must never launch an engine')

    monkeypatch.setattr(topos.engines, 'run_engine', forbidden)
    provenance = json.loads((FIXTURE / 'provenance.json').read_text())
    for name, digest in provenance['fixture_json_sha256'].items():
        assert file_digest(FIXTURE / name) == digest
    selected = provenance['selected_exact_native_files']
    folder = tmp_path / 'test-created-native-cp-subset'
    for name, identity in selected.items():
        path = FIXTURE / 'artifacts' / identity.get('stored_path', name)
        assert file_digest(path) == identity['sha256']
        assert path.stat().st_size == identity['size_bytes']
        original = folder / name
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, original)
    record = RunRecord.model_validate_json((FIXTURE / 'record.json').read_text())
    assert record.status == 'completed' and record.validation_status == 'human-review'
    # Only the test wrapper omits binary scratch. Exact original JSON remains
    # separately retained and never changes its statuses or native receipts.
    record.artifacts = [a for a in record.artifacts if a.path in selected]
    for attempt in record.attempts:
        attempt.artifacts = [a for a in attempt.artifacts if a.path in selected]
    store = RunStore(folder)
    store.commit(record)
    case = ReferenceCase.model_validate_json((FIXTURE / 'case.json').read_text())
    return case, record, store


def test_actual_completed_t5_parent_imports_validated_cp_without_relabeling_review(native_cp):
    case, record, store = native_cp
    before = store.verify()
    value, proof = extract_reference_value(case, record, store)
    assert value == pytest.approx(-0.007985913257996913, abs=1e-14)
    assert len(proof['native_legs']) == 5 and len(proof['basis_exports']) == 2
    assert value != proof['recomputed_energies_hartree']['half_cp_interaction_hartree']
    assert record.validation_status == store.load()['validation_status'] == 'human-review'
    assert store.verify() == before


@pytest.mark.parametrize('change', [
    'partial', 'not-completed', 'missing-state', 'malformed-state', 'wrong-state-row', 'wrong-request-row',
    'wrong-source', 'wrong-inputs', 'wrong-binding', 'wrong-parent-validation',
    'invalid-component', 'invalid-leg', 'standalone-human-review',
])
def test_matrix_parent_cannot_replace_full_row_or_component_qualification(native_cp, change):
    case, record, store = native_cp
    if change == 'partial':
        record.status = 'partial'
    elif change == 'not-completed':
        record.metadata['matrix_execution']['full_row_completed'] = False
    elif change == 'missing-state':
        record.metadata.pop('matrix_execution')
    elif change == 'malformed-state':
        record.metadata['matrix_execution'] = ['not-a-matrix-state']
    elif change == 'wrong-state-row':
        record.metadata['matrix_execution']['row_id'] = 'T5-1min'
    elif change == 'wrong-request-row':
        record.request = record.request.model_copy(update={'matrix_row_id': 'T5-1min'})
        case = case.model_copy(update={'request': record.request})
    elif change == 'wrong-source':
        record.metadata['matrix_execution']['source_sha256'] = 'a' * 64
    elif change == 'wrong-inputs':
        record.metadata['matrix_execution']['inputs_sha256'] = 'a' * 64
    elif change == 'wrong-binding':
        record.metadata['matrix_binding']['row_id'] = 'T5-1min'
    elif change == 'wrong-parent-validation':
        record.validation_status = 'rejected'
    elif change == 'invalid-component':
        record.metadata['matrix_counterpoise']['validation_status'] = 'human-review'
    elif change == 'invalid-leg':
        next(a for a in record.attempts if a.metadata.get('counterpoise_role')).validation_status = 'human-review'
    else:
        record.request = record.request.model_copy(update={
            'purpose': 'energy', 'matrix_row_id': None})
        case = case.model_copy(update={'request': record.request})
    if (record.request.model_dump(mode='json') != store.load()['request']
            or change == 'invalid-leg'):
        # A changed-request negative gets a separate test-created store;
        # production immutability is never bypassed or weakened for this test.
        changed = store.run_dir.parent / 'test-created-changed-request'
        for artifact in [*record.artifacts, *(a for attempt in record.attempts for a in attempt.artifacts)]:
            source = store.run_dir / artifact.path
            target = changed / artifact.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        store = RunStore(changed)
    store.commit(record)
    with pytest.raises(IntegrityError, match='exact completed|full-row binding|T5-1h matrix route|five-leg|native attempt identity'):
        extract_reference_value(case, record, store)


def test_matrix_full_row_flag_does_not_override_rehashed_native_cp_error(native_cp):
    case, record, store = native_cp
    artifact = next(a for a in record.artifacts if a.role == 'counterpoise-result')
    path = store.run_dir / artifact.path
    payload = json.loads(path.read_text())
    payload['energies']['cp_interaction_hartree'] = payload['energies']['half_cp_interaction_hartree']
    target = store.run_dir / 'counterpoise-results' / (digest_json(payload) + '.json')
    target.write_text(json.dumps(payload))
    record.artifacts.remove(artifact)
    record.artifacts.append(artifact.model_copy(update={
        'path': target.relative_to(store.run_dir).as_posix(),
        'sha256': file_digest(target), 'size_bytes': target.stat().st_size}))
    record.metadata['matrix_counterpoise']['result_path'] = target.relative_to(store.run_dir).as_posix()
    record.metadata['matrix_counterpoise']['energies'] = payload['energies']
    store.commit(record)
    with pytest.raises(IntegrityError, match='independently recomputed five native energies'):
        extract_reference_value(case, record, store)
