"""Documented file-format fixtures; no fixture claims licensed engine execution."""
import os
import shutil

import numpy as np
import pytest

from topos.engines import EngineParseError, run_engine
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.native_hessian import orca_frequency_input, parse_orca_hessian, run_orca_hessian
from topos.science import BOHR_ANGSTROM


def water():
    return Molecule(symbols=['O', 'H', 'H'], coordinates=[[0, 0, 0], [.95, 0, 0], [-.24, .93, 0]])


def hess_fixture(molecule):
    n = 3 * len(molecule.symbols)
    matrix = np.eye(n) * .2 + np.ones((n, n)) * .01
    rows = ['$hessian', str(n)]
    for start in range(0, n, 5):
        columns = list(range(start, min(start + 5, n)))
        rows.append(' '.join(map(str, columns)))
        rows.extend(str(i) + ' ' + ' '.join(f'{matrix[i, j]:.12E}' for j in columns) for i in range(n))
    rows.extend(['$atoms', str(len(molecule.symbols))])
    for symbol, coordinates in zip(molecule.symbols, molecule.coordinates, strict=True):
        rows.append(f'{symbol} 1.0079 ' + ' '.join(f'{v / BOHR_ANGSTROM:.12E}' for v in coordinates))
    rows.append('$end')
    return '\n'.join(rows), matrix


def test_blocked_hessian_retains_mass_provenance_and_exact_mapping(tmp_path):
    text, expected = hess_fixture(water())
    path = tmp_path / 'format-fixture.hess'
    path.write_text(text)
    parsed = parse_orca_hessian(path, water())
    assert np.allclose(parsed['hessian_hartree_per_bohr2'], expected)
    assert parsed['native_masses_amu'] == [1.0079] * 3
    assert parsed['native_coordinates_units'] == 'bohr'


@pytest.mark.parametrize('mutation', ['truncated', 'wronggeometry', 'missingcolumn', 'asymmetric', 'nonfinite', 'duplicatesection'])
def test_incomplete_or_wrong_hessian_never_supplies_modes(tmp_path, mutation):
    text, _ = hess_fixture(water())
    if mutation == 'truncated':
        text = text[:text.index('$atoms')]
    elif mutation == 'wronggeometry':
        text = text.replace('O 1.0079 0.000000000000E+00', 'O 1.0079 1.000000000000E+00')
    elif mutation == 'missingcolumn':
        text = text.replace('5 6 7 8', '5 6 7 7')
    elif mutation == 'asymmetric':
        text = text.replace('1.000000000000E-02', '2.000000000000E-02', 1)
    elif mutation == 'nonfinite':
        text = text.replace('2.100000000000E-01', 'NaN', 1)
    else:
        text += '\n$atoms\n3\n'
    path = tmp_path / 'format-fixture.hess'
    path.write_text(text)
    with pytest.raises(EngineParseError):
        parse_orca_hessian(path, water())


def test_frequency_input_is_analytic_scf_not_engrad_or_numfreq():
    method = MethodSpec(engine='orca', method='r2SCAN-3c', profile_id='orca-mapping-v4.1')
    deck = orca_frequency_input(water(), method, ResourceLimits())
    assert ' Freq\n' in deck and 'Engrad' not in deck and 'NumFreq' not in deck
    with pytest.raises(ValueError):
        orca_frequency_input(water(), method.model_copy(update={'method': 'DLPNO-CCSD(T)'}), ResourceLimits())
    with pytest.raises(ValueError):
        orca_frequency_input(water(), method.model_copy(update={'constraints': {'frozen_atoms': [0]}}), ResourceLimits())


def test_absent_binary_never_creates_hessian_evidence(tmp_path):
    result = run_orca_hessian(water(), MethodSpec(engine='orca', method='r2SCAN-3c', profile_id='orca-mapping-v4.1'),
                              ResourceLimits(), tmp_path, executable='/missing-native-orca')
    assert result.status == 'unavailable'
    assert 'hessian_hartree_per_bohr2' not in result.metadata


def test_authentic_orca_native_hessian_and_verified_recovery(tmp_path, monkeypatch):
    binary = os.environ.get('TOPOS_ORCA_EXECUTABLE')
    if not binary or not shutil.which(binary):
        pytest.skip('licensed ORCA execution must be provisioned explicitly')
    process_runner = None
    if os.environ.get('TOPOS_REQUIRE_BASE') == '1':
        from topos.base_integration import BaseRuntime

        runtime = BaseRuntime()
        binary = runtime.resolve_executable('orca', binary)
        process_runner = runtime.run_process
    method = MethodSpec(engine='orca', method='r2SCAN-3c', profile_id='orca-mapping-v4.1')
    resources = ResourceLimits(budget_seconds=180, memory_mb=2048)
    optimized = run_engine(water(), method, resources, tmp_path / 'optimize', executable=binary,
                           process_runner=process_runner)
    assert optimized.status == 'completed', optimized.diagnostics
    assert optimized.molecule is not None
    result = run_orca_hessian(optimized.molecule, method, resources, tmp_path / 'native-hessian', executable=binary,
                              process_runner=process_runner)
    assert result.status == 'completed', result.diagnostics
    assert result.metadata['analysis']['validity'] == 'harmonic-minimum-within-thresholds'
    assert len(result.metadata['analysis']['frequencies_cm1']) == 3
    replay = run_orca_hessian(optimized.molecule, method, resources, tmp_path / 'native-hessian', executable=binary,
                              process_runner=process_runner)
    assert replay.metadata['reused_completed_hessian']
    assert replay.command == result.command
    from threading import Event

    from topos import native_hessian
    from topos.storage import file_digest

    folder = tmp_path / 'native-hessian'
    preserved = {str(path.relative_to(folder)): file_digest(path) for path in folder.rglob('*') if path.is_file()}

    def no_new_process(*args, **kwargs):
        raise AssertionError('completed Hessian recovery must not launch a native process')

    # These are genuine completed native receipts. Corrupt one scientific
    # assertion at a time, require rejection without a process, then restore
    # the exact original bytes; raw engine evidence is never edited.
    import json

    from topos.storage import IntegrityError

    completed = folder / 'completed.json'
    reference_receipt = folder / 'reference.json'
    for case in ('energy', 'gradient', 'hessian', 'analysis', 'protocol', 'separate_gradient'):
        receipt = reference_receipt if case == 'separate_gradient' else completed
        original_bytes = receipt.read_bytes()
        payload = json.loads(original_bytes)
        changed = payload['result']
        if case == 'energy':
            changed['energy_hartree'] += .01
        elif case in {'gradient', 'separate_gradient'}:
            changed['gradient_hartree_per_bohr'] = [[0., 0., 0.]] * len(optimized.molecule.symbols)
        elif case == 'hessian':
            changed['metadata']['hessian_hartree_per_bohr2'][0][0] += .01
        elif case == 'analysis':
            changed['metadata']['analysis']['frequencies_cm1'][0] += 1
        else:
            changed['metadata']['protocol']['gradient_threshold'] *= 10
        try:
            receipt.write_text(json.dumps(payload))
            with pytest.raises(IntegrityError):
                run_orca_hessian(optimized.molecule, method, resources, folder, executable=binary,
                                  process_runner=no_new_process)
        finally:
            receipt.write_bytes(original_bytes)
        assert {str(path.relative_to(folder)): file_digest(path) for path in folder.rglob('*') if path.is_file()} == preserved

    for stop_kind in ('cancelled', 'timed-out'):
        cancel = Event()
        clock = {'value': 0.0}
        actual_digest = native_hessian.file_digest

        def digest_then_stop(path, *, actual_digest=actual_digest, stop_kind=stop_kind, cancel=cancel, clock=clock):
            value = actual_digest(path)
            # This is a genuinely completed, unchanged native cache. Stop
            # only after hashing its actual physical Hessian during replay.
            if path.name == 'frequency.hess':
                if stop_kind == 'cancelled':
                    cancel.set()
                else:
                    clock['value'] = resources.budget_seconds + 1
            return value

        with monkeypatch.context() as context:
            context.setattr(native_hessian, 'file_digest', digest_then_stop)
            context.setattr(native_hessian.time, 'monotonic', lambda clock=clock: clock['value'])
            stopped = run_orca_hessian(optimized.molecule, method, resources, folder, executable=binary,
                                       process_runner=no_new_process, cancel_event=cancel)
        assert stopped.status == stop_kind and stopped.converged is False
        assert {str(path.relative_to(folder)): file_digest(path) for path in folder.rglob('*') if path.is_file()} == preserved
