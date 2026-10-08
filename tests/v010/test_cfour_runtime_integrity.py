"""Runtime-receipt/ledger bookkeeping only, never a current CFOUR acceptance.

The sole raw output is unchanged public CFOUR 2.00beta. Constructed authority
receipts test byte binding; they are not Stage 0 or native 2.1 evidence.
"""
from __future__ import annotations

import copy
import shutil
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from topos.engines import artifact_inventory
from topos.external_engines import ExternalProtocol
from topos.matrix_components import run_component, verify_cfour_runtime_receipts
from topos.models import Attempt, Molecule, RunRecord, RunRequest
from topos.storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest, read_json


@pytest.fixture
def receipt_bookkeeping(tmp_path):
    root = tmp_path / 'unexecuted-receipt-bookkeeping'
    authority = {'runtime_seal_sha256': 'a' * 64, 'binary_sha256': 'b' * 64,
                 'executable': '/bookkeeping/not-a-native-executable',
                 'identity_scope': 'Unexecuted authority bookkeeping test; not a native runtime'}
    for index in range(2):
        folder = root / f'evaluation-{index:05d}'
        folder.mkdir(parents=True)
        shutil.copyfile(Path(__file__).parent / 'fixtures/cfour_corrections/carbon12-dboc.out', folder / 'engine.stdout')
        (folder / 'engine.stderr').write_text('')
        (folder / 'ZMAT').write_text(f'Unexecuted directory-binding fixture {index}\n')
        (folder / 'GENBAS').write_text('Unexecuted text bookkeeping; not a basis library\n')
        atomic_json(folder / 'engine-cfour-runtime.json', {
            'schema': 'topos-cfour-runtime-integrity/1', 'status': 'verified', 'reason': None,
            'runtime_before': authority, 'runtime_after': authority, 'command': [authority['executable']],
            'workdir': str(folder), 'native_inputs_sha256': {name: file_digest(folder / name) for name in ('ZMAT', 'GENBAS')},
            'stdout_name': 'engine.stdout', 'stderr_name': 'engine.stderr',
            'stdout_sha256': file_digest(folder / 'engine.stdout'), 'stderr_sha256': file_digest(folder / 'engine.stderr'),
        })
    return root, authority


def test_retained_transport_binding_is_portable_without_local_binary(receipt_bookkeeping, tmp_path):
    root, authority = receipt_bookkeeping
    original = artifact_inventory(root)
    proof = verify_cfour_runtime_receipts(original, root, authority)
    assert proof['native_evaluations'] == 2
    assert 'scientific validation is separate' in proof['scope']
    copy = tmp_path / 'portable'
    shutil.copytree(root, copy)
    result = verify_cfour_runtime_receipts(artifact_inventory(copy), copy, authority,
                                         original_artifacts=[a.model_dump(mode='json') for a in original])
    assert result == proof
    assert not Path(authority['executable']).exists()


@pytest.mark.parametrize('change', ['missing', 'extra', 'failed', 'pre-seal', 'post-seal', 'command', 'directory',
                                   'input', 'output', 'original-inventory', 'duplicate'])
def test_every_evaluation_receipt_is_required_and_byte_bound(receipt_bookkeeping, change):
    root, authority = receipt_bookkeeping
    original = [a.model_dump(mode='json') for a in artifact_inventory(root)]
    receipt = root / 'evaluation-00001/engine-cfour-runtime.json'
    payload = read_json(receipt)
    if change == 'missing':
        receipt.unlink()
    elif change == 'extra':
        shutil.copyfile(receipt, root / 'engine-cfour-runtime.json')
    elif change == 'failed':
        payload['status'] = 'failed'
    elif change in {'pre-seal', 'post-seal'}:
        field = 'runtime_before' if change == 'pre-seal' else 'runtime_after'
        payload[field]['runtime_seal_sha256'] = 'c' * 64
    elif change == 'command':
        payload['command'].append('unapproved')
    elif change == 'directory':
        payload['workdir'] = str(root / 'different-native-directory')
    elif change == 'input':
        (receipt.parent / 'ZMAT').write_text('Changed input\n')
    elif change == 'output':
        (receipt.parent / 'engine.stdout').write_text('Changed output\n')
    elif change == 'original-inventory':
        original = [a for a in original if a['path'] != str(receipt.parent / 'GENBAS')]
    if change not in {'missing', 'extra', 'input', 'output', 'original-inventory', 'duplicate'}:
        atomic_json(receipt, payload)
    artifacts = artifact_inventory(root)
    if change == 'duplicate':
        artifacts.append(artifacts[0])
    with pytest.raises(IntegrityError, match='CFOUR'):
        verify_cfour_runtime_receipts(artifacts, root, authority, original_artifacts=original)


def test_current_fullseal_rejects_changed_helpers_with_same_launcher_and_genbas(receipt_bookkeeping):
    root, authority = receipt_bookkeeping
    changed = {**authority, 'runtime_seal_sha256': 'c' * 64}
    with pytest.raises(IntegrityError, match='runtime or launch binding'):
        verify_cfour_runtime_receipts(artifact_inventory(root), root, changed)


def ledger_bookkeeping(tmp_path, authority, *, retain_authority=True):
    molecule = Molecule(symbols=['He'], coordinates=[[0, 0, 0]])
    protocol = ExternalProtocol(engine='cfour', engine_version='2.1', method='HF', operation='energy', orbital_basis='cc-pVDZ', frozen_core=False)
    record = RunRecord(request=RunRequest(molecule=molecule), status='running')
    key = 'unexecuted-ledger-bookkeeping'
    attempt = Attempt(run_id=record.run_id, engine='cfour', method='HF', status='completed', metadata={
        'matrix_component_sha256': digest_json({'component_key': key, 'molecule': molecule.model_dump(mode='json'),
                                              'protocol': protocol.model_dump(mode='json')}),
        'scope': 'Deliberately incomplete ledger declaration; no scientific result',
    })
    record.attempts.append(attempt)
    if retain_authority:
        record.metadata['cfour_runtime_authority'] = copy.deepcopy(authority)
    store = RunStore(tmp_path / 'ledger')
    store.commit(record)
    return record, store, key, molecule, protocol


@pytest.mark.parametrize('state', ['legacy-base', 'unsealed-record', 'changed-current', 'changed-during-reuse'])
def test_reuse_reauthorizes_before_any_cached_scientific_result(tmp_path, state, monkeypatch):
    authority = {'runtime_seal_sha256': 'a' * 64, 'executable': '/bookkeeping/no-engine', 'binary_sha256': 'b' * 64}
    record, store, key, molecule, protocol = ledger_bookkeeping(tmp_path, authority, retain_authority=state != 'unsealed-record')
    calls = []

    def current():
        calls.append('authorized')
        return {**authority, 'runtime_seal_sha256': 'c' * 64 if state == 'changed-current' or len(calls) == 2 else 'a' * 64}

    runtime = SimpleNamespace() if state == 'legacy-base' else SimpleNamespace(cfour_runtime_identity=current)
    workflow = SimpleNamespace(base_runtime=runtime)
    monkeypatch.setattr('topos.matrix_components._verified_component', lambda *args: pytest.fail('Must reject before cached science'))
    with pytest.raises(IntegrityError, match='CFOUR|runtime seal'):
        run_component(workflow, record, store, key, molecule, protocol,
                      lambda *args, **kwargs: pytest.fail('Must not execute'), time.monotonic() + 30, None)
    assert len(record.attempts) == 1


@pytest.mark.parametrize('stop', ['cancel', 'deadline'])
def test_reuse_checks_stop_after_authority_and_artifacts(tmp_path, monkeypatch, stop):
    """Opaque cached sentinel tests control flow, without inventing an EngineResult."""
    authority = {'runtime_seal_sha256': 'a' * 64, 'executable': '/bookkeeping/no-engine', 'binary_sha256': 'b' * 64}
    record, store, key, molecule, protocol = ledger_bookkeeping(tmp_path, authority)
    workflow = SimpleNamespace(base_runtime=SimpleNamespace(cfour_runtime_identity=lambda: authority))
    cancel = Event()
    clock = [100.]
    monkeypatch.setattr('topos.matrix_components.time.monotonic', lambda: clock[0])

    def checked_evidence(*args):
        if stop == 'cancel':
            cancel.set()
        else:
            clock[0] = 102.
        return object()

    monkeypatch.setattr('topos.matrix_components._verified_component', checked_evidence)
    result = run_component(workflow, record, store, key, molecule, protocol,
                           lambda *args, **kwargs: pytest.fail('Must not execute'), 101., cancel)
    assert result is None and record.status == ('cancelled' if stop == 'cancel' else 'timed-out')


@pytest.mark.parametrize('change_after_publish', [False, True])
def test_lost_commit_acknowledgement_rechecks_current_seal(tmp_path, monkeypatch, change_after_publish):
    """Pure ledger control flow using an opaque result, without any EngineResult.

    Scientific verification is explicitly bypassed in this bookkeeping test;
    no native stdout, energy, gradient, or physical acceptance is fabricated.
    """
    authority = {'runtime_seal_sha256': 'a' * 64, 'executable': '/bookkeeping/no-engine', 'binary_sha256': 'b' * 64}
    record, store, key, molecule, protocol = ledger_bookkeeping(tmp_path, authority)
    record.attempts.clear()
    store = RunStore(tmp_path / 'fresh-ledger')
    store.commit(record)
    state = {'changed': False, 'published': False, 'verifications': 0}

    def current():
        return {**authority, 'runtime_seal_sha256': 'c' * 64 if state['changed'] else 'a' * 64}

    workflow = SimpleNamespace(base_runtime=SimpleNamespace(cfour_runtime_identity=current,
        resolve_executable=lambda *args: authority['executable'], run_process=None),
        config=SimpleNamespace(executables={}, execution_backend='development'))
    opaque = object()

    def verify_bookkeeping(*args):
        state['verifications'] += 1
        return opaque

    monkeypatch.setattr('topos.matrix_components._completed_result', lambda *args: (False, None))
    monkeypatch.setattr('topos.matrix_components._verified_component', verify_bookkeeping)
    original_commit = store.commit

    def interrupted_commit(value):
        original_commit(value)
        if value.attempts and value.attempts[-1].status == 'completed' and not state['published']:
            state.update(published=True, changed=change_after_publish)
            raise RuntimeError('Bookkeeping publication acknowledgement lost')

    monkeypatch.setattr(store, 'commit', interrupted_commit)
    ledger_only = SimpleNamespace(command=['bookkeeping-no-native-launch'], engine_version=None, diagnostics={},
        metadata={'scope': 'Opaque ledger control only; no native result'}, model_dump=lambda **kwargs: {'scope': 'no science'},
        status='completed', artifacts=[], molecule=None, converged=True, energy_hartree=None, gradient_hartree_per_bohr=None)

    def executor(*args, **kwargs):
        return ledger_only

    if change_after_publish:
        with pytest.raises(IntegrityError, match='recovery rejected.*runtime changed'):
            run_component(workflow, record, store, key, molecule, protocol, executor, time.monotonic() + 30, None)
        retained = RunRecord.model_validate(store.load())
        assert retained.status == 'failed' and retained.attempts[-1].status == 'completed'
        assert retained.attempts[-1].metadata['scope'] == 'Opaque ledger control only; no native result'
        assert state['verifications'] == 1
    else:
        assert run_component(workflow, record, store, key, molecule, protocol, executor, time.monotonic() + 30, None) is opaque
        assert state['verifications'] == 2
    assert state['published']
