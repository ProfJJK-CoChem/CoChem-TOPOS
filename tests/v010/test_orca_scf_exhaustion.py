"""Retained native failure/parser and restart contracts; no live acceptance here."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from topos.engines import run_engine
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.orca_scf_continuation import continue_frequency_scf, continue_ordinary_scf
from topos.orca_scf_exhaustion import observe_scf_iteration_exhaustion
from topos.runtime import ProcessResult

FIXTURE = Path(__file__).parent / 'fixtures/orca_scf_exhaustion'


def original(name):
    provenance = json.loads((FIXTURE / 'provenance.json').read_text())
    data = (FIXTURE / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == provenance['files'][name]
    return data.decode()


def test_actual_retained_scf_exhaustion_is_restart_eligible_but_not_converged():
    evidence = observe_scf_iteration_exhaustion(original('engine.stdout'), original('engine.stderr'))
    assert evidence['eligible_for_own_gbw_continuation'] is True
    assert evidence['failures'] == [] and evidence['final_active_converger'] == 'S-O-S-C-F'
    assert evidence['printed_scf_settings'] == {'MaxIter': 125, 'TolE': 1e-10, 'TolMaxP': 1e-7,
        'TolRMSP': 5e-9, 'TolErr': 5e-7, 'TolG': 1e-5, 'TolX': 1e-5}
    assert evidence['final_iteration']['cycle'] == 125
    assert evidence['final_iteration']['energy_change_hartree'] == 1.70e-9
    assert evidence['final_iteration']['rms_density_change'] == 4.47e-8
    assert evidence['final_iteration']['max_density_change'] == 1e-6
    assert 'initial SCF is not converged' in evidence['scope']


@pytest.mark.parametrize('keyword', ['TolE', 'TolRMSP', 'TolMaxP', 'TolErr', 'TolG', 'TolX'])
def test_changed_native_scf_target_cannot_qualify_for_restart(keyword):
    raw = re.sub(r'(?m)(^.*\b' + keyword + r'\s+\.{4}\s*)[^\n]+', r'\g<1>9.000e-3',
                 original('engine.stdout'))
    evidence = observe_scf_iteration_exhaustion(raw, original('engine.stderr'))
    assert evidence['eligible_for_own_gbw_continuation'] is False
    assert 'printed target differs: ' + keyword in evidence['failures']


@pytest.mark.parametrize('damage', ['truncated', 'absent-settings', 'missing-target', 'mode',
    'earlier-converged-stage', 'normal-termination', 'wrong-version', 'missing-cause', 'missing-final-row',
    'mismatched-iteration-limit', 'repeated-settings', 'truncated-final-table', 'changed-active-columns',
    'segfault', 'unrelated-mpi', 'unrelated-error', 'foreign-stderr'])
def test_incomplete_mixed_or_unrelated_native_failure_never_qualifies(damage):
    raw, stderr = original('engine.stdout'), original('engine.stderr')
    if damage == 'truncated':
        raw = raw[:raw.index('SCF NOT CONVERGED AFTER')]
    elif damage == 'absent-settings':
        raw = raw.replace('SCF SETTINGS', 'absent settings')
    elif damage == 'missing-target':
        raw = re.sub(r'(?m)^.*TolRMSP[^\n]*\n', '', raw)
    elif damage == 'mode':
        raw = raw.replace('All-Criteria', 'Energy')
    elif damage == 'earlier-converged-stage':
        raw = 'SCF CONVERGED AFTER 1 CYCLES\n' + raw
    elif damage == 'normal-termination':
        raw += '\nORCA TERMINATED NORMALLY\n'
    elif damage == 'wrong-version':
        raw = raw.replace('Program Version 6.1.1', 'Program Version 6.0.1')
    elif damage == 'missing-cause':
        raw = raw.replace('Error (ORCA_LEANSCF): unfortunately, the SCF has not converged.', 'other termination')
    elif damage == 'missing-final-row':
        raw = re.sub(r'(?m)^\s*12[45]\s+-152\.[^\n]*\n', '', raw)
    elif damage == 'mismatched-iteration-limit':
        raw = raw.replace('MaxIter         ....   125', 'MaxIter         ....   200')
    elif damage == 'repeated-settings':
        raw = 'SCF SETTINGS\n' + raw
    elif damage == 'truncated-final-table':
        raw = raw.replace('SCF NOT CONVERGED AFTER', '\n----------------S-O-S-C-F----------------\nSCF NOT CONVERGED AFTER')
    elif damage == 'changed-active-columns':
        raw = raw.replace('MaxGrad    Time(sec)', 'DIISErr    Time(sec)')
    elif damage == 'segfault':
        stderr += '\nSignal: Segmentation fault (11)\n'
    elif damage == 'unrelated-mpi':
        stderr += '\nMPI_Init failed to start a daemon\n'
    elif damage == 'unrelated-error':
        stderr += '\nError: invalid input file\n'
    else:
        stderr = 'unrelated native stderr\n'
    evidence = observe_scf_iteration_exhaustion(raw, stderr)
    assert evidence['eligible_for_own_gbw_continuation'] is False and evidence['failures']


@pytest.mark.parametrize('damage', ['missing-normal-termination', 'appended-scf-failure'])
def test_complete_residual_table_does_not_replace_native_termination_requirements(tmp_path, damage):
    folder, process = own_failed_job(tmp_path)
    raw = (FIXTURE.parent / 'orca_frequency_scf_residual/initial-frequency.stdout').read_text()
    if damage == 'missing-normal-termination':
        raw = raw.replace('ORCA TERMINATED NORMALLY', 'native job interrupted')
    else:
        raw += '\nSCF CONVERGENCE FAILURE\n'
    assert continue_ordinary_scf(process.command, folder, ResourceLimits(), process, raw,
        operation='gradient', deadline=time.monotonic() + 10, cancel_event=None,
        execute_process=lambda *a, **k: pytest.fail('invalid residual continuation')) is None
    assert not (folder / 'initial-scf').exists()


def own_failed_job(tmp_path):
    folder = tmp_path / 'own-failed-job'
    folder.mkdir()
    for name in ('job.inp', 'engine.stdout', 'engine.stderr'):
        (folder / name).write_bytes((FIXTURE / name).read_bytes())
    # Explicit bookkeeping bytes test ownership; they are not native orbitals.
    (folder / 'job.gbw').write_bytes(b'unit-policy-checkpoint-not-native-orbitals')
    process = ProcessResult(['/contract-only/orca', 'job.inp'], 'completed', 0, 149.25, 300,
                            str(folder / 'engine.stdout'), str(folder / 'engine.stderr'))
    return folder, process


def test_recognized_exhaustion_restarts_once_with_exact_input_allocation_and_remaining_deadline(tmp_path):
    folder, process = own_failed_job(tmp_path)
    resources = ResourceLimits(threads=2, memory_mb=2048, budget_seconds=100)
    calls = []
    before = (folder / 'job.inp').read_bytes()

    def runner(command, cwd, allocated, **options):
        calls.append(command)
        assert cwd == folder and allocated.threads == 2 and allocated.memory_mb == 2048
        assert 0 < allocated.budget_seconds <= 10 and options['threads_per_process'] == 1
        assert (folder / 'job.inp').read_bytes() == before
        (folder / 'engine.stdout').write_text('Checking for AutoStart:\nThe File: job.gbw exists\nGBW file was renamed to GES file\n')
        (folder / 'engine.stderr').write_text('')
        return process

    result = continue_ordinary_scf(process.command, folder, resources, process, original('engine.stdout'),
        operation='gradient', deadline=time.monotonic() + 10, cancel_event=None,
        execute_process=runner, stderr=original('engine.stderr'))
    assert calls == [process.command]
    binding = result[3]
    assert binding['maximum_continuations'] == 1 and binding['input_unchanged'] is True
    assert binding['initial_scf_exhaustion']['eligible_for_own_gbw_continuation'] is True
    assert binding['initial_scf']['passed'] is False and binding['final_scf']['passed'] is False
    assert (folder / 'initial-scf/initial-engine.stdout').read_bytes() == (FIXTURE / 'engine.stdout').read_bytes()
    assert (folder / 'initial-scf/initial-engine.stderr').read_bytes() == (FIXTURE / 'engine.stderr').read_bytes()
    with pytest.raises(FileExistsError):
        continue_ordinary_scf(process.command, folder, resources, process, original('engine.stdout'),
            operation='gradient', deadline=time.monotonic() + 10, cancel_event=None,
            execute_process=lambda *a, **k: pytest.fail('second continuation'), stderr=original('engine.stderr'))


@pytest.mark.parametrize('condition', ['failed-process', 'missing-gbw', 'empty-gbw', 'symlink-gbw',
    'foreign-command', 'stale-gradient', 'cancelled', 'expired', 'optimizer', 'frequency'])
def test_exhaustion_does_not_expand_unrelated_or_stopped_restart_scope(tmp_path, condition):
    folder, process = own_failed_job(tmp_path)
    event = Event()
    deadline = time.monotonic() + 10
    if condition == 'failed-process':
        process = replace(process, status='failed', returncode=1)
    elif condition == 'missing-gbw':
        (folder / 'job.gbw').unlink()
    elif condition == 'empty-gbw':
        (folder / 'job.gbw').write_bytes(b'')
    elif condition == 'symlink-gbw':
        (folder / 'job.gbw').rename(folder / 'foreign.gbw')
        (folder / 'job.gbw').symlink_to(folder / 'foreign.gbw')
    elif condition == 'foreign-command':
        process.command[-1] = 'different.inp'
    elif condition == 'stale-gradient':
        (folder / 'job.engrad').write_text('unrelated gradient')
    elif condition == 'cancelled':
        event.set()
    elif condition == 'expired':
        deadline = time.monotonic() - 1
    options = dict(deadline=deadline, cancel_event=event,
                   execute_process=lambda *a, **k: pytest.fail('forbidden continuation'))
    if condition == 'frequency':
        result = continue_frequency_scf(process.command, folder, ResourceLimits(), process,
                                       original('engine.stdout'), **options)
    else:
        result = continue_ordinary_scf(process.command, folder, ResourceLimits(), process,
            original('engine.stdout'), operation='optimize' if condition == 'optimizer' else 'gradient',
            stderr=original('engine.stderr'), **options)
    assert result is None and not (folder / 'initial-scf').exists()


@pytest.mark.parametrize('profile', ['orca-mapping-v4.1', 'orca-mapping-v4.2'])
@pytest.mark.parametrize('stop', [None, 'cancelled', 'timed-out'])
def test_adapter_considers_only_new_profile_recovery_before_rejection_and_retains_stop_reason(tmp_path, monkeypatch, profile, stop):
    # Subprocess/orchestration contract only. No scientific result is accepted.
    event, clock, calls = Event(), [0.0], []
    monkeypatch.setattr('topos.engines.time.monotonic', lambda: clock[0])

    def runner(command, folder, resources, **options):
        prefix = options.get('log_prefix', 'engine')
        stdout, stderr = folder / (prefix + '.stdout'), folder / (prefix + '.stderr')
        if prefix == 'version':
            stdout.write_text('Program Version 6.1.1\nSCF CONVERGED AFTER 1 CYCLES\nFINAL SINGLE POINT ENERGY 0.0\nORCA TERMINATED NORMALLY\n')
            stderr.write_text('')
        else:
            stdout.write_text(original('engine.stdout'))
            stderr.write_text(original('engine.stderr'))
            (folder / 'job.gbw').write_bytes(b'contract-only-checkpoint')
        return ProcessResult(command, 'completed', 0, .01, 1, str(stdout), str(stderr))

    def decline(command, folder, resources, process, raw, **options):
        calls.append(options)
        assert options['operation'] == 'gradient' and options['deadline'] == 10
        assert options['stderr'] == original('engine.stderr')
        if stop == 'cancelled':
            event.set()
        elif stop == 'timed-out':
            clock[0] = 11
        return None

    monkeypatch.setattr('topos.orca_scf_continuation.continue_ordinary_scf', decline)
    molecule = Molecule(symbols=['O', 'H', 'H'], coordinates=[[0, 0, 0], [.96, 0, 0], [-.24, .93, 0]])
    method = MethodSpec(engine='orca', method='wB97M-V', basis='def2-QZVPP',
                        auxiliary_basis='def2/J', profile_id=profile, engine_version='6.1.1')
    result = run_engine(molecule, method, ResourceLimits(threads=2, memory_mb=2048, budget_seconds=10),
                        tmp_path / 'attempt', operation='gradient', executable=sys.executable,
                        process_runner=runner, cancel_event=event)
    assert len(calls) == (profile == 'orca-mapping-v4.2')
    expected = stop if profile == 'orca-mapping-v4.2' and stop else 'failed'
    assert result.status == expected and result.energy_hartree is None
    assert result.gradient_hartree_per_bohr is None
