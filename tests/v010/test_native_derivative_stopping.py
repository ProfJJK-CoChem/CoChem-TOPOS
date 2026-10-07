"""Stop-order contracts without invented native calculations or cache receipts."""
import sys
from pathlib import Path
from threading import Event

import pytest

from topos.anharmonic import run_orca_vpt2
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.native_hessian import run_orca_hessian


def inputs():
    return (Molecule(symbols=['O', 'H', 'H'], coordinates=[[0, 0, 0], [.95, 0, 0], [-.24, .93, 0]]),
            MethodSpec(engine='orca', method='B3LYP', basis='def2-TZVPP', dispersion='D4',
                       profile_id='orca-vpt2-reference-v1'), ResourceLimits(budget_seconds=10, threads=1, memory_mb=2048))


def forbidden_process(*args, **kwargs):
    raise AssertionError('a stopped derivative call must not execute a native process')


@pytest.mark.parametrize('runner', [run_orca_hessian, run_orca_vpt2])
def test_pre_cancelled_call_preserves_existing_files_without_process_or_binary_lookup(tmp_path, runner, monkeypatch):
    from topos import native_hessian

    molecule, method, resources = inputs()
    marker = tmp_path / 'existing-nonscientific-file.txt'
    marker.write_text('Preserved directory sentinel; no completed native science is claimed.\n')
    before = marker.read_bytes()
    cancel = Event()
    cancel.set()
    monkeypatch.setattr(native_hessian.shutil, 'which', forbidden_process)
    options = {'semirigid_modes': True} if runner is run_orca_vpt2 else {}
    result = runner(molecule, method, resources, tmp_path, executable='/absent-orca',
                     process_runner=forbidden_process, cancel_event=cancel, **options)
    assert result.status == 'cancelled' and result.converged is False
    assert result.metadata['execution_kind'] == 'not-executed'
    assert sorted(p.name for p in tmp_path.iterdir()) == [marker.name]
    assert marker.read_bytes() == before


@pytest.mark.parametrize('stop_kind', ['cancelled', 'timed-out'])
def test_hessian_stops_after_empty_cache_scan_without_a_native_launch(tmp_path, monkeypatch, stop_kind):
    from topos import native_hessian

    molecule, method, resources = inputs()
    cancel = Event()
    clock = {'value': 0.0}
    original = native_hessian._read_completed

    def scan_then_stop(receipt, root):
        # Read the real empty cache. No completed result or native output is made.
        actual = original(receipt, root)
        assert actual is None
        if stop_kind == 'cancelled':
            cancel.set()
        else:
            clock['value'] = resources.budget_seconds + 1
        return actual

    monkeypatch.setattr(native_hessian.time, 'monotonic', lambda: clock['value'])
    monkeypatch.setattr(native_hessian, '_read_completed', scan_then_stop)
    # This real file is only a prelaunch identity operand. It never executes,
    # produces ORCA output, or becomes a positive scientific fixture.
    result = run_orca_hessian(molecule, method, resources, tmp_path, executable=sys.executable,
                              process_runner=forbidden_process, cancel_event=cancel)
    assert result.status == stop_kind and result.converged is False
    assert result.metadata['execution_kind'] == 'not-executed'
    assert not (tmp_path / 'completed.json').exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ['protocol.json']


@pytest.mark.parametrize('stop_kind', ['cancelled', 'timed-out'])
def test_vpt2_stops_after_real_deck_preparation_before_reference_execution(tmp_path, monkeypatch, stop_kind):
    from topos import anharmonic

    molecule, method, resources = inputs()
    cancel = Event()
    clock = {'value': 0.0}
    original = anharmonic.orca_vpt2_input

    def prepare_then_stop(*args, **kwargs):
        deck = original(*args, **kwargs)
        if stop_kind == 'cancelled':
            cancel.set()
        else:
            clock['value'] = resources.budget_seconds + 1
        return deck

    monkeypatch.setattr(anharmonic.time, 'monotonic', lambda: clock['value'])
    monkeypatch.setattr(anharmonic, 'orca_vpt2_input', prepare_then_stop)
    monkeypatch.setattr(anharmonic, 'run_orca_hessian', forbidden_process)
    result = run_orca_vpt2(molecule, method, resources, tmp_path, executable='/absent-orca',
                           process_runner=forbidden_process, cancel_event=cancel, semirigid_modes=True)
    assert result.status == stop_kind and result.converged is False
    assert result.metadata['execution_kind'] == 'not-executed'
    assert not (tmp_path / 'completed.json').exists()
    assert not (tmp_path / 'reference').exists()
    assert all(path.suffix == '.json' for path in Path(tmp_path).iterdir())
