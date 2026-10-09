"""External-file contracts and genuine persistent model inference acceptance."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import stat
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from topos.ml_extopt import (
    MAX_MESSAGE_BYTES,
    SOCKET_SCHEMA,
    ExtOptAllocation,
    connect_server,
    crest_client,
    extopt_client,
    goat_extopt_input,
    orca_executable_identity,
    parse_extopt_input,
    receive_json,
    send_json,
)
from topos.models import Molecule, ResourceLimits
from topos.storage import atomic_json, digest_json, file_digest


def water():
    return Molecule(symbols=['O', 'H', 'H'], coordinates=[[0,0,0],[.9584,0,0],[-.239,.927,0]])


def external_files(folder, molecule=None):
    molecule = molecule or water()
    folder.mkdir(parents=True, exist_ok=True)
    xyz = folder / 'ORCA_EXT.xyz'
    xyz.write_text(str(len(molecule.symbols)) + '\nNative external XYZ format fixture\n' + '\n'.join(
        f'{s} {r[0]:.17g} {r[1]:.17g} {r[2]:.17g}' for s, r in zip(molecule.symbols, molecule.coordinates, strict=True)) + '\n')
    inp = folder / 'ORCA_EXT.extinp.tmp'
    inp.write_text('ORCA_EXT.xyz # XYZ filename\n0 # charge\n1 # multiplicity\n1 # cores\n1 # gradient\n')
    return inp


def test_documented_external_contract_keeps_state_units_and_raw_bytes(tmp_path):
    inp = external_files(tmp_path)
    parsed = parse_extopt_input(inp, water().model_dump(mode='json'), tmp_path, maximum_cores=1)
    assert parsed['molecule'] == water().model_dump(mode='json')
    assert parsed['output_path'].endswith('ORCA_EXT.engrad')
    assert parsed['gradient_requested']
    assert parsed['external_input']['coordinate_units'] == 'angstrom'
    assert parsed['external_input']['extinp_sha256'] == file_digest(inp)


@pytest.mark.parametrize('suffix', ['pointcharges.pc\n', '0\n'])
def test_embedding_cannot_be_silently_ignored(tmp_path, suffix):
    inp = external_files(tmp_path)
    inp.write_text(inp.read_text() + suffix)
    with pytest.raises(ValueError, match='point-charge'):
        parse_extopt_input(inp, water().model_dump(mode='json'), tmp_path, maximum_cores=1)


@pytest.mark.parametrize('change', ['charge', 'order', 'nonfinite', 'escape', 'symlink', 'cores'])
def test_external_identity_and_filesystem_boundaries(tmp_path, change):
    root = tmp_path / 'native'
    inp = external_files(root)
    xyz = root / 'ORCA_EXT.xyz'
    if change == 'charge':
        inp.write_text(inp.read_text().replace('0 # charge', '1 # charge'))
    elif change == 'order':
        xyz.write_text(xyz.read_text().replace('O ', 'C '))
    elif change == 'nonfinite':
        xyz.write_text(xyz.read_text().replace('O 0', 'O nan'))
    elif change == 'escape':
        (tmp_path / 'outside.xyz').write_text(xyz.read_text())
        inp.write_text(inp.read_text().replace('ORCA_EXT.xyz', '../outside.xyz'))
    elif change == 'symlink':
        xyz.rename(root / 'actual.xyz')
        xyz.symlink_to(root / 'actual.xyz')
    else:
        inp.write_text(inp.read_text().replace('1 # cores', '2 # cores'))
    with pytest.raises(ValueError):
        parse_extopt_input(inp, water().model_dump(mode='json'), root, maximum_cores=1)


def test_message_size_bound_precedes_payload_allocation():
    first, second = socket.socketpair()
    try:
        first.sendall(struct.pack('!I', MAX_MESSAGE_BYTES + 1))
        with pytest.raises(ValueError, match='byte bound'):
            receive_json(second)
    finally:
        first.close()
        second.close()


def test_concurrent_allocations_and_native_deck_are_explicit(tmp_path):
    total = ResourceLimits(threads=3, memory_mb=3072, device='gpu')
    ExtOptAllocation(1, 2048, 2, 1024).validate(total)
    with pytest.raises(ValueError, match='total CPU'):
        ExtOptAllocation(2, 2048, 2, 1024).validate(total)
    with pytest.raises(ValueError, match='RAM'):
        ExtOptAllocation(1, 3072, 2, 1024).validate(total)
    deck = goat_extopt_input(water(), tmp_path / 'fixed-client', ResourceLimits(threads=2))
    assert '! GOAT-EXPLORE ExtOpt TightOpt' in deck
    assert '%scf\n  TolE 1e-5\nend' in deck
    assert '%geom\n  TolE 1e-5\n' in deck
    assert f'ProgExt "{tmp_path / "fixed-client"}"' in deck
    assert 'NWORKERS 2' in deck and 'MAXEN 12' in deck
    assert 'RANDOMSEED true' in deck
    seeded = goat_extopt_input(water(), tmp_path / 'fixed-client', ResourceLimits(threads=2), deterministic=True)
    assert 'RANDOMSEED false' in seeded
    with pytest.raises(ValueError, match='boolean'):
        goat_extopt_input(water(), tmp_path / 'fixed-client', ResourceLimits(), deterministic='false')


def test_endpoint_rejects_nonprivate_socket(tmp_path):
    tmp_path.chmod(0o700)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(tmp_path / 's'))
        (tmp_path / 's').chmod(0o666)
        with pytest.raises(ValueError, match='0600'):
            connect_server(tmp_path, timeout=1)


def _nonexecuted_hash_contract_file(path):
    """Byte-identity fixture only: never launched or presented as ORCA output."""
    path.write_bytes(b'Nonexecuted executable identity contract fixture.\n')
    path.chmod(0o700)
    return path


def test_actual_executable_identity_reads_bytes_and_resolves_command_alias(tmp_path):
    binary = _nonexecuted_hash_contract_file(tmp_path / 'native-hash-contract')
    alias = tmp_path / 'command-alias'
    alias.symlink_to(binary)
    observed = orca_executable_identity(alias)
    assert observed == {'executable': str(alias), 'resolved_path': str(binary),
                        'sha256': file_digest(binary), 'size_bytes': binary.stat().st_size}
    binary.write_bytes(b'Different nonexecuted executable identity contract bytes.\n')
    changed = orca_executable_identity(alias)
    assert changed['sha256'] != observed['sha256']


@pytest.mark.parametrize('case', ['relative', 'missing', 'directory', 'not-executable'])
def test_executable_identity_requires_actual_executable_regular_file(tmp_path, case):
    path = tmp_path / 'native-hash-contract'
    if case == 'relative':
        path = Path('relative-native-hash-contract')
    elif case == 'directory':
        path.mkdir()
    elif case == 'not-executable':
        path.write_bytes(b'Nonexecuted, nonexecutable identity fixture.\n')
        path.chmod(0o600)
    with pytest.raises((ValueError, OSError)):
        orca_executable_identity(path)


@pytest.mark.parametrize('case', ['bytes', 'alias'])
def test_identity_rejects_binary_or_alias_replacement_during_hash_observation(tmp_path, monkeypatch, case):
    from topos import storage

    binary = _nonexecuted_hash_contract_file(tmp_path / 'native-hash-contract')
    alias = tmp_path / 'command-alias'
    alias.symlink_to(binary)
    replacement = _nonexecuted_hash_contract_file(tmp_path / 'replacement-hash-contract')
    actual_digest = storage.file_digest

    def observe_then_change(path):
        digest = actual_digest(path)
        if case == 'bytes':
            binary.write_bytes(b'Different nonexecuted identity bytes after the actual read.\n')
        else:
            alias.unlink()
            alias.symlink_to(replacement)
        return digest

    monkeypatch.setattr(storage, 'file_digest', observe_then_change)
    with pytest.raises(ValueError, match='changed during'):
        orca_executable_identity(alias)


@pytest.mark.parametrize('change', ['none', 'replace', 'delete'])
def test_extopt_retains_actual_hash_and_rejects_changed_binary_on_blocked_loader(tmp_path, change):
    """Negative launch contract: no ORCA or model process/output is simulated."""
    from topos.ml import ModelManifest
    from topos.ml_extopt import run_goat_extopt

    binary = _nonexecuted_hash_contract_file(tmp_path / 'native-hash-contract')
    initial_hash = file_digest(binary)
    checkpoint = tmp_path / 'unloaded-checkpoint-contract'
    checkpoint.write_bytes(b'Unloaded checkpoint metadata contract; not a scientific model.\n')
    manifest = ModelManifest(backend='mace', family='negative launch contract', package_version='0.3.16',
        members=[{'path': str(checkpoint), 'sha256': file_digest(checkpoint),
                  'training_run_id': 'not-a-scientific-result', 'source': 'unloaded metadata contract'}],
        training_method='metadata contract', license_name='metadata contract', license_url='metadata contract',
        supported_elements=['H', 'O'], supported_charges=[0], supported_multiplicities=[1],
        precision='float64', domain_reference='metadata contract')

    class DeliberatelyBlockedRuntime:
        calls = []

        def resolve_executable(self, engine):
            return str(binary) if engine == 'orca' else sys.executable

        def run_ml_process(self, *args, **kwargs):
            raise AssertionError('Negative native preflight must not start model inference')

        def run_process(self, command, *args, **kwargs):
            self.calls.append(command)
            assert command == [str(binary), 'version.inp']
            if change == 'replace':
                binary.write_bytes(b'Changed nonexecuted native identity during blocked invocation.\n')
            elif change == 'delete':
                binary.unlink()
            raise RuntimeError('Deliberately blocked negative launch; no native process executed')

    runtime = DeliberatelyBlockedRuntime()
    result = run_goat_extopt(water(), manifest, ResourceLimits(threads=2, memory_mb=1024),
        tmp_path / 'attempt', runtime=runtime, allocation=ExtOptAllocation(1, 512, 1, 512))
    assert runtime.calls == [[str(binary), 'version.inp']]
    assert result.status == 'failed' and not result.ensemble and not result.command
    assert result.metadata['execution_kind'] == 'not-executed'
    assert result.metadata['executable'] == str(binary)
    assert result.metadata['executable_sha256'] == initial_hash
    identity = result.metadata['orca_executable_identity']
    assert result.metadata['orca_executable_identity_sha256'] == digest_json(identity)
    assert identity['sha256'] == initial_hash
    observations = result.metadata['orca_executable_observations']
    assert observations[0]['identity'] == identity
    assert observations[0]['phase'] == 'resolved-before-native-invocation'
    assert observations[1]['phase'] == 'before-loader-invocation'
    if change == 'none':
        assert result.metadata['orca_executable_stable'] is True
        assert all(entry['matches_initial'] for entry in observations)
        assert [entry['phase'] for entry in observations][-2:] == [
            'after-loader-invocation', 'finalization-after-server-cleanup']
        assert 'Deliberately blocked' in result.diagnostics['reason']
    else:
        assert result.metadata['orca_executable_stable'] is False and result.converged is False
        assert 'stability could not be established' in result.diagnostics['reason']
        assert 'orca_executable_error' in result.diagnostics
        if change == 'replace':
            assert any(not entry['matches_initial'] for entry in observations)


def test_authentic_persistent_mace_extopt_callback_and_unit_conversion(tmp_path):
    """Actual model/socket/ORCA file bridge; explicitly not BASE/ORCA execution."""
    python = os.environ.get('TOPOS_MACE_PYTHON') or os.environ.get('TOPOS_ML_TEST_PYTHON')
    request_file = os.environ.get('TOPOS_ML_TEST_REQUEST')
    if not python or not request_file:
        pytest.skip('explicit genuine ML interpreter/checkpoint request required')
    from topos import ml_extopt
    from topos.ml import BOHR_ANGSTROM, HARTREE_EV

    original = json.loads(Path(request_file).read_text())
    model = original['manifest']
    assert model['backend'] == 'mace', 'Supplied actual inference request must target MACE'
    molecule = Molecule.model_validate(original['molecules'][0])
    server = tmp_path / 'private-server'
    server.mkdir(mode=0o700)
    native = tmp_path / 'native'
    native.mkdir()
    request = {**original, 'molecules': [molecule.model_dump(mode='json')], 'mode': 'server',
               'server': {'socket_name': 's', 'max_requests': 1_000_000, 'max_receipt_mb': 4, 'request_timeout_seconds': 60,
                          'client_module_sha256': file_digest(Path(ml_extopt.__file__))}}
    request['resources'] = {**request['resources'], 'budget_seconds': 120}
    request_path = server / 'ml-request.json'
    atomic_json(request_path, request)
    # The development test deliberately imports this reviewed working source.
    # Production uses BASE's installed-silo/worker hash proof instead.
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[2]))
    stdout, stderr = (server / 'native-worker.stdout').open('wb'), (server / 'native-worker.stderr').open('wb')
    process = subprocess.Popen([python, '-m', 'topos.ml_worker', '--request', str(request_path)], cwd=server,
                               env=environment, stdout=stdout, stderr=stderr)
    config_path = tmp_path / 'client-config.json'
    manifest_sha = digest_json(request['manifest'])
    config = {'schema_version': SOCKET_SCHEMA, 'server_folder': str(server), 'native_root': str(native),
              'reference_molecule': molecule.model_dump(mode='json'), 'manifest_sha256': manifest_sha,
              'maximum_external_cores': 1, 'timeout_seconds': 60}
    atomic_json(config_path, config)
    try:
        deadline = time.monotonic() + 90
        while not (server / 'ready.json').is_file() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert (server / 'ready.json').is_file(), (server / 'native-worker.stderr').read_text()
        assert stat.S_IMODE((server / 's').stat().st_mode) == 0o600
        energies, gradients = [], []
        step = 1e-4
        for displacement in (0, step, -step):
            data = molecule.model_dump(mode='json')
            data['coordinates'][1][0] += displacement * BOHR_ANGSTROM
            current = Molecule.model_validate(data)
            inp = external_files(native, current)
            extopt_client(config_path, file_digest(config_path), inp)
            engrad = [line.strip() for line in (native / 'ORCA_EXT.engrad').read_text().splitlines() if line.strip() and not line.startswith('#')]
            assert int(engrad[0]) == len(molecule.symbols)
            energies.append(float(engrad[1]))
            gradients.append(np.array([float(v) for v in engrad[2:]]).reshape(-1,3))
        assert (energies[1] - energies[2]) / (2 * step) == pytest.approx(gradients[0][1,0], abs=1e-6)
        receipts = [json.loads(path.read_text()) for path in sorted((server / 'calls').glob('*.json'))]
        assert len(receipts) == 3
        for receipt, energy, gradient in zip(receipts, energies, gradients, strict=True):
            frame = receipt['response']['frame']
            assert frame['energy_hartree'] == energy
            np.testing.assert_array_equal(frame['gradient_hartree_per_bohr'], gradient)
            raw = receipt['request']['external_input']
            assert hashlib.sha256(raw['xyz_text'].encode()).hexdigest() == raw['xyz_sha256']
            assert frame['member_energies_hartree'][0] * HARTREE_EV == pytest.approx(energy * HARTREE_EV)
        generic = native / 'genericinp.xyz'
        external_files(native, molecule)
        generic.write_text((native / 'ORCA_EXT.xyz').read_text())
        crest_client(config_path, file_digest(config_path), generic)
        generic_rows = [line.strip() for line in (native / 'genericinp.engrad').read_text().splitlines()
                        if line.strip() and not line.startswith('#')]
        assert int(generic_rows[0]) == len(molecule.symbols)
        assert float(generic_rows[1]) == pytest.approx(energies[0], abs=1e-12)
        np.testing.assert_allclose(np.array([float(v) for v in generic_rows[2:]]).reshape(-1,3), gradients[0], atol=1e-12, rtol=0)
        generic.write_text('incomplete native geometry\n')
        with pytest.raises(ValueError, match='atom count'):
            crest_client(config_path, file_digest(config_path), generic)
        assert not (native / 'genericinp.engrad').exists(), 'failed CREST callback must remove previous geometry gradient'
        altered = molecule.model_dump(mode='json')
        altered['atom_ids'] = ['altered-' + str(i) for i in range(len(molecule.symbols))]
        with connect_server(server, timeout=10) as connection:
            send_json(connection, {'schema_version': SOCKET_SCHEMA, 'action': 'evaluate', 'manifest_sha256': manifest_sha,
                                   'molecule': altered, 'external_input': {'negative_contract_test': 'changed atom IDs'}})
            rejected = receive_json(connection)
            assert rejected['status'] == 'failed' and 'frame' not in rejected
        with connect_server(server, timeout=10) as connection:
            send_json(connection, {'schema_version': SOCKET_SCHEMA, 'action': 'stop', 'manifest_sha256': manifest_sha})
            assert receive_json(connection)['status'] == 'stopped'
        assert process.wait(timeout=30) == 0, (server / 'native-worker.stderr').read_text()
        summary = json.loads((server / 'ml-result.json').read_text())
        assert summary['model_load_count'] == len(model['members']) == 1
        assert summary['requests'] == 5 and summary['successful_requests'] == 4
        assert summary['request_sha256'] == file_digest(request_path)
        assert summary['max_receipt_mb'] == 4
        assert 5 * 4096 <= summary['receipt_allocated_bytes'] <= 4 * 1024**2
        assert not (server / 's').exists()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        stdout.close()
        stderr.close()
