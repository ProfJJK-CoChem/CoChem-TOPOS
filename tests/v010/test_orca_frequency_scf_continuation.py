"""Real native parser fixtures and continuation policy; no fixture is live acceptance."""
import json
import time
from pathlib import Path
from threading import Event

import pytest

from topos.models import ResourceLimits
from topos.orca_numerical_profiles import observe_scf_numerical_profile
from topos.orca_scf_continuation import continue_frequency_scf
from topos.runtime import ProcessResult

FIXTURES = Path(__file__).parent / 'fixtures/orca_frequency_scf_residual'


def raw(name='initial-frequency.stdout'):
    return (FIXTURES / name).read_text()


def own_frequency(tmp_path):
    folder = tmp_path / 'independent-frequency'
    folder.mkdir()
    (folder / 'frequency.inp').write_bytes((FIXTURES / 'frequency.inp').read_bytes())
    (folder / 'frequency.gbw').write_bytes(b'policy-test-placeholder-not-native-orbitals')
    (folder / 'frequency.hess').write_bytes(b'initial-hessian-policy-placeholder')
    (folder / 'frequency.stdout').write_bytes((FIXTURES / 'initial-frequency.stdout').read_bytes())
    (folder / 'frequency.stderr').write_bytes(b'initial-stderr\x00\xff')
    process = ProcessResult(['/exact/orca', 'frequency.inp'], 'completed', 0, 4, 100,
        str(folder / 'frequency.stdout'), str(folder / 'frequency.stderr'))
    return folder, process


def test_retained_cold_frequency_miss_is_electronic_scf_not_cpscf_response():
    initial = raw()
    evidence = observe_scf_numerical_profile(initial)
    assert initial.index('SCF CONVERGENCE\n') < initial.index('SHARK CP-SCF DRIVER')
    assert evidence['failures'] == ['active final criterion not achieved: RMS-Density change']
    assert evidence['final_printed_rows']['RMS-Density change']['value'] > 5e-9
    assert evidence['final_printed_rows']['RMS-Density change']['threshold'] == 5e-9
    assert evidence['final_active_converger'] == 'S-O-S-C-F'
    assert evidence['inactive_DIIS_residual_retained'] is True
    assert observe_scf_numerical_profile(raw('continued-frequency.stdout'))['passed'] is True


def test_one_frequency_own_gbw_continuation_preserves_first_hessian_and_exact_input(tmp_path):
    folder, process = own_frequency(tmp_path)
    initial = {path.name: path.read_bytes() for path in folder.iterdir()}
    calls = []
    deadline = time.monotonic() + 10

    def runner(command, cwd, resources, **options):
        calls.append((command, cwd, resources, options))
        assert resources.budget_seconds <= 10 and resources.memory_mb == 2048 and resources.threads == 2
        assert options['log_prefix'] == 'frequency' and options['threads_per_process'] == 1
        assert (folder / 'frequency.inp').read_bytes() == initial['frequency.inp']
        assert (folder / 'frequency.gbw').read_bytes() == initial['frequency.gbw']
        (folder / 'frequency.stdout').write_text(raw('continued-frequency.stdout'))
        (folder / 'frequency.stderr').write_text('')
        (folder / 'frequency.hess').write_bytes(b'new-hessian-policy-placeholder')
        return process

    result = continue_frequency_scf(process.command, folder, ResourceLimits(budget_seconds=100, memory_mb=2048, threads=2),
        process, raw(), deadline=deadline, cancel_event=None, execute_process=runner)
    assert len(calls) == 1 and result[3]['native_own_autostart'] is True
    assert result[3]['operation'] == 'hessian' and result[3]['maximum_continuations'] == 1
    assert result[3]['input_unchanged'] is True and result[3]['final_scf']['passed'] is True
    for name, value in initial.items():
        assert (folder / 'initial-scf' / ('initial-' + name)).read_bytes() == value
    binding = json.loads((folder / 'scf-continuation.json').read_text())
    assert binding['initial_scf']['passed'] is False and binding['final_scf']['passed'] is True
    assert binding['budget_scope'] == 'remaining original attempt deadline; no extension'
    with pytest.raises(FileExistsError):
        continue_frequency_scf(process.command, folder, ResourceLimits(), process, raw(),
            deadline=deadline, cancel_event=None, execute_process=lambda *a, **k: pytest.fail('second continuation'))


@pytest.mark.parametrize('condition', ['wrong-target', 'missing-row', 'missing-convergence', 'expired',
    'cancelled', 'failed-process', 'only-foreign-job-gbw', 'wrong-input-command', 'symlinked-hessian'])
def test_frequency_missing_changed_stopped_or_foreign_evidence_cannot_continue(tmp_path, condition):
    folder, process = own_frequency(tmp_path)
    evidence = raw()
    event = Event()
    deadline = time.monotonic() + 10
    if condition == 'wrong-target':
        evidence = evidence.replace('Tolerance :   5.0000e-09', 'Tolerance :   5.0000e-08')
    elif condition == 'missing-row':
        evidence = '\n'.join(line for line in evidence.splitlines() if 'Last RMS-Density change' not in line)
    elif condition == 'missing-convergence':
        evidence = evidence.replace('SCF CONVERGED AFTER', 'TEST REMOVED CONVERGENCE MARKER')
    elif condition == 'expired':
        deadline = time.monotonic() - 1
    elif condition == 'cancelled':
        event.set()
    elif condition == 'failed-process':
        process = ProcessResult(process.command, 'failed', 1, 4, 100, process.stdout_path, process.stderr_path)
    elif condition == 'only-foreign-job-gbw':
        (folder / 'frequency.gbw').rename(folder / 'job.gbw')
    elif condition == 'wrong-input-command':
        process = ProcessResult(['/exact/orca', 'job.inp'], 'completed', 0, 4, 100, process.stdout_path, process.stderr_path)
    elif condition == 'symlinked-hessian':
        other = folder / 'other.hess'
        (folder / 'frequency.hess').rename(other)
        (folder / 'frequency.hess').symlink_to(other)
    def call():
        return continue_frequency_scf(process.command, folder, ResourceLimits(), process, evidence,
            deadline=deadline, cancel_event=event, execute_process=lambda *a, **k: pytest.fail('forbidden launch'))
    if condition == 'symlinked-hessian':
        with pytest.raises(ValueError, match='regular files'):
            call()
    else:
        assert call() is None
        assert not (folder / 'initial-scf').exists()


def test_frequency_cannot_accept_continuation_without_own_autostart_lineage(tmp_path):
    folder, process = own_frequency(tmp_path)

    def runner(*args, **kwargs):
        (folder / 'frequency.stdout').write_text(raw('continued-frequency.stdout').replace(
            'The File: frequency.gbw exists', 'TEST REMOVED OWN GBW MARKER'))
        (folder / 'frequency.stderr').write_text('')
        return process

    with pytest.raises(ValueError, match='own-orbital lineage'):
        continue_frequency_scf(process.command, folder, ResourceLimits(), process, raw(),
            deadline=time.monotonic() + 10, cancel_event=None, execute_process=runner)


@pytest.mark.parametrize('stop_kind', ['cancelled', 'timed-out'])
def test_hessian_caller_reports_stop_during_frequency_archive_without_second_launch(tmp_path, monkeypatch, stop_kind):
    # Policy-only boundary test: placeholder process/reference data are never
    # accepted as scientific results. The call must stop before Hessian parsing.
    from topos import native_hessian
    from topos.engines import EngineResult
    from topos.models import MethodSpec, Molecule

    molecule = Molecule(symbols=['O', 'H', 'H'], coordinates=[[0, 0, 0], [.95, 0, 0], [-.24, .93, 0]])
    method = MethodSpec(engine='orca', method='r2SCAN-3c', profile_id='orca-mapping-v4.2')
    reference = EngineResult(status='completed', engine='orca', engine_version='6.1.1', method='r2SCAN-3c',
        operation='gradient', converged=True, molecule=molecule, energy_hartree=-76.4189355748,
        gradient_hartree_per_bohr=[[0., 0., 0.]] * 3)
    monkeypatch.setattr(native_hessian, 'run_engine', lambda *a, **k: reference)
    monkeypatch.setattr(native_hessian, 'verify_orca_gradient_result', lambda *a, **k: None)
    clock = {'value': 0.}
    event = Event()
    monkeypatch.setattr(native_hessian.time, 'monotonic', lambda: clock['value'])

    def stop_during_archive(*args, **kwargs):
        if stop_kind == 'cancelled':
            event.set()
        else:
            clock['value'] = 181.
        return None

    monkeypatch.setattr('topos.orca_scf_continuation.continue_frequency_scf', stop_during_archive)
    binary = tmp_path / 'policy-placeholder-orca'
    binary.write_bytes(b'not-a-native-executable; process runner below is a policy stub')
    binary.chmod(0o755)
    calls = []

    def runner(command, folder, resources, **options):
        calls.append(command)
        (folder / 'frequency.stdout').write_text(raw())
        (folder / 'frequency.stderr').write_text('')
        return ProcessResult(command, 'completed', 0, 3, 100,
            str(folder / 'frequency.stdout'), str(folder / 'frequency.stderr'))

    result = native_hessian.run_orca_hessian(molecule, method, ResourceLimits(budget_seconds=180),
        tmp_path / 'stopped-hessian', executable=binary, process_runner=runner, cancel_event=event)
    assert result.status == stop_kind and result.converged is False
    assert len(calls) == 1
    assert 'hessian_hartree_per_bohr2' not in result.metadata
    assert not (tmp_path / 'stopped-hessian/completed.json').exists()
