"""Continuation policy tests; retained native fixtures are not live acceptance."""
import json
import time
from pathlib import Path
from threading import Event

import pytest

from topos.models import ResourceLimits
from topos.orca_scf_continuation import continue_ordinary_scf
from topos.runtime import ProcessResult


def own_job(tmp_path):
    folder = tmp_path / 'own-job'
    folder.mkdir()
    (folder / 'job.inp').write_text('! HF-3c TightSCF\n%scf ConvCheckMode 0 TolE 1e-10 end\n')
    (folder / 'job.gbw').write_bytes(b'unit-policy-orbitals-not-a-native-result')
    (folder / 'engine.stdout').write_bytes(b'initial native bytes\x00\xff')
    (folder / 'engine.stderr').write_bytes(b'initial stderr\n')
    process = ProcessResult(['/exact/orca', 'job.inp'], 'completed', 0, 4, 10,
                            str(folder / 'engine.stdout'), str(folder / 'engine.stderr'))
    return folder, process


def failed_residual(monkeypatch):
    # Policy-only observation; this never enters a scientific result or receipt.
    monkeypatch.setattr('topos.orca_scf_continuation.observe_scf_numerical_profile',
                        lambda raw: {'failures': ['active final criterion not achieved: RMS-Density change']})


@pytest.mark.parametrize('operation', ['energy', 'gradient'])
def test_one_own_job_continuation_preserves_bytes_input_and_shared_deadline(tmp_path, monkeypatch, operation):
    failed_residual(monkeypatch)
    folder, process = own_job(tmp_path)
    calls = []
    deadline = time.monotonic() + 10

    def runner(command, cwd, resources, **options):
        calls.append((command, cwd, resources, options))
        assert (folder / 'job.gbw').read_bytes() == b'unit-policy-orbitals-not-a-native-result'
        assert resources.budget_seconds <= 10
        (folder / 'engine.stdout').write_text('Checking for AutoStart:\nThe File: job.gbw exists\nGBW file was renamed to GES file\n')
        (folder / 'engine.stderr').write_text('')
        return process

    result = continue_ordinary_scf(process.command, folder, ResourceLimits(budget_seconds=100), process, '',
        operation=operation, deadline=deadline, cancel_event=None, execute_process=runner)
    assert len(calls) == 1 and result[3]['native_own_autostart'] is True
    assert (folder / 'initial-scf/initial-engine.stdout').read_bytes() == b'initial native bytes\x00\xff'
    assert (folder / 'initial-scf/initial-engine.stderr').read_bytes() == b'initial stderr\n'
    assert (folder / 'initial-scf/initial-job.inp').read_bytes() == (folder / 'job.inp').read_bytes()
    assert result[3]['input_unchanged'] is True
    receipt = json.loads((folder / 'scf-continuation.json').read_text())
    assert receipt['maximum_continuations'] == 1
    assert Path(receipt['initial_process']['stdout_path']).read_bytes() == b'initial native bytes\x00\xff'


@pytest.mark.parametrize('failure', ['printed target differs: RMS-Density change', 'missing final SCF row: Energy change',
                                    'final active native converger is not established'])
def test_incomplete_or_changed_native_profile_never_continues(tmp_path, monkeypatch, failure):
    monkeypatch.setattr('topos.orca_scf_continuation.observe_scf_numerical_profile', lambda raw: {'failures': [failure]})
    folder, process = own_job(tmp_path)
    assert continue_ordinary_scf(process.command, folder, ResourceLimits(), process, '', operation='energy',
        deadline=time.monotonic() + 5, cancel_event=None, execute_process=lambda *a, **k: pytest.fail('forbidden launch')) is None
    assert not (folder / 'initial-scf').exists()


@pytest.mark.parametrize('condition', ['optimizer', 'cancelled', 'expired', 'missing-own-gbw', 'failed-process'])
def test_forbidden_or_stopped_continuations_do_not_launch(tmp_path, monkeypatch, condition):
    failed_residual(monkeypatch)
    folder, process = own_job(tmp_path)
    event = Event()
    deadline = time.monotonic() + 5
    if condition == 'cancelled':
        event.set()
    if condition == 'expired':
        deadline = time.monotonic() - 1
    if condition == 'missing-own-gbw':
        (folder / 'job.gbw').unlink()
    if condition == 'failed-process':
        process = ProcessResult(process.command, 'failed', 1, 4, 10, process.stdout_path, process.stderr_path)
    assert continue_ordinary_scf(process.command, folder, ResourceLimits(), process, '',
        operation='optimize' if condition == 'optimizer' else 'gradient', deadline=deadline,
        cancel_event=event, execute_process=lambda *a, **k: pytest.fail('forbidden launch')) is None
    assert not (folder / 'initial-scf').exists()


def test_native_continuation_without_own_orbital_marker_cannot_be_accepted(tmp_path, monkeypatch):
    failed_residual(monkeypatch)
    folder, process = own_job(tmp_path)

    def runner(*args, **kwargs):
        (folder / 'engine.stdout').write_text('a different initial guess')
        (folder / 'engine.stderr').write_text('')
        return process

    with pytest.raises(ValueError, match='own-orbital lineage'):
        continue_ordinary_scf(process.command, folder, ResourceLimits(), process, '', operation='gradient',
            deadline=time.monotonic() + 5, cancel_event=None, execute_process=runner)


def test_native_continuation_cannot_change_the_scientific_input(tmp_path, monkeypatch):
    failed_residual(monkeypatch)
    folder, process = own_job(tmp_path)

    def runner(*args, **kwargs):
        (folder / 'job.inp').write_text('changed Hamiltonian')
        (folder / 'engine.stdout').write_text('Checking for AutoStart:\nThe File: job.gbw exists\nGBW file was renamed to GES file\n')
        (folder / 'engine.stderr').write_text('')
        return process

    with pytest.raises(ValueError, match='exact input'):
        continue_ordinary_scf(process.command, folder, ResourceLimits(), process, '', operation='gradient',
            deadline=time.monotonic() + 5, cancel_event=None, execute_process=runner)


def test_deadline_expiring_during_archive_restores_streams_without_launch(tmp_path, monkeypatch):
    failed_residual(monkeypatch)
    folder, process = own_job(tmp_path)
    times = iter((1.0, 3.0))
    monkeypatch.setattr('topos.orca_scf_continuation.time.monotonic', lambda: next(times))
    assert continue_ordinary_scf(process.command, folder, ResourceLimits(), process, '', operation='gradient',
        deadline=2.0, cancel_event=None, execute_process=lambda *a, **k: pytest.fail('expired launch')) is None
    assert (folder / 'engine.stdout').read_bytes() == b'initial native bytes\x00\xff'
    assert (folder / 'engine.stderr').read_bytes() == b'initial stderr\n'
    assert json.loads((folder / 'scf-continuation.json').read_text())['status'] == 'not-launched-deadline-or-cancellation'


def test_cancellation_during_archive_restores_streams_without_launch(tmp_path, monkeypatch):
    import shutil

    failed_residual(monkeypatch)
    folder, process = own_job(tmp_path)
    event = Event()
    original = shutil.copyfile

    def copy_and_cancel(src, dst):
        copied = original(src, dst)
        event.set()
        return copied

    monkeypatch.setattr('topos.orca_scf_continuation.shutil.copyfile', copy_and_cancel)
    assert continue_ordinary_scf(process.command, folder, ResourceLimits(), process, '', operation='energy',
        deadline=time.monotonic() + 5, cancel_event=event, execute_process=lambda *a, **k: pytest.fail('cancelled launch')) is None
    assert (folder / 'engine.stdout').read_bytes() == b'initial native bytes\x00\xff'


def test_changed_own_orbitals_after_archive_do_not_launch(tmp_path, monkeypatch):
    import shutil

    failed_residual(monkeypatch)
    folder, process = own_job(tmp_path)
    original = shutil.copyfile

    def copy_then_change_orbitals(src, dst):
        copied = original(src, dst)
        if Path(src).name == 'job.gbw':
            Path(src).write_bytes(b'foreign orbitals')
        return copied

    monkeypatch.setattr('topos.orca_scf_continuation.shutil.copyfile', copy_then_change_orbitals)
    with pytest.raises(ValueError, match='own orbitals changed'):
        continue_ordinary_scf(process.command, folder, ResourceLimits(), process, '', operation='gradient',
            deadline=time.monotonic() + 5, cancel_event=None, execute_process=lambda *a, **k: pytest.fail('changed-orbital launch'))


def test_a_second_continuation_is_rejected_before_another_native_launch(tmp_path, monkeypatch):
    failed_residual(monkeypatch)
    folder, process = own_job(tmp_path)
    (folder / 'initial-scf').mkdir()
    with pytest.raises(FileExistsError):
        continue_ordinary_scf(process.command, folder, ResourceLimits(), process, '', operation='energy',
            deadline=time.monotonic() + 5, cancel_event=None, execute_process=lambda *a, **k: pytest.fail('second continuation'))
