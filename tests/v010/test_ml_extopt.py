"""External-file contracts and genuine persistent model inference acceptance."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import stat
import struct
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from topos.ml_extopt import (
    MAX_MESSAGE_BYTES,
    SOCKET_SCHEMA,
    ExtOptAllocation,
    connect_server,
    extopt_client,
    goat_extopt_input,
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


def test_endpoint_rejects_nonprivate_socket(tmp_path):
    tmp_path.chmod(0o700)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(tmp_path / 's'))
        (tmp_path / 's').chmod(0o666)
        with pytest.raises(ValueError, match='0600'):
            connect_server(tmp_path, timeout=1)


def test_authentic_persistent_mace_extopt_callback_and_unit_conversion(tmp_path):
    """Actual model/socket/ORCA file bridge; explicitly not BASE/ORCA execution."""
    python = os.environ.get('TOPOS_ML_TEST_PYTHON')
    request_file = os.environ.get('TOPOS_ML_TEST_REQUEST')
    if not python or not request_file:
        pytest.skip('explicit genuine ML interpreter/checkpoint request required')
    from topos import ml_extopt
    from topos.ml import BOHR_ANGSTROM, HARTREE_EV

    original = json.loads(Path(request_file).read_text())
    model = original['manifest']
    if model['backend'] != 'mace':
        pytest.skip('this actual inference acceptance targets supplied MACE checkpoint')
    molecule = Molecule.model_validate(original['molecules'][0])
    server = tmp_path / 'private-server'
    server.mkdir(mode=0o700)
    native = tmp_path / 'native'
    native.mkdir()
    request = {**original, 'molecules': [molecule.model_dump(mode='json')], 'mode': 'server',
               'server': {'socket_name': 's', 'max_requests': 20, 'request_timeout_seconds': 60,
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
        with connect_server(server, timeout=10) as connection:
            send_json(connection, {'schema_version': SOCKET_SCHEMA, 'action': 'stop', 'manifest_sha256': manifest_sha})
            assert receive_json(connection)['status'] == 'stopped'
        assert process.wait(timeout=30) == 0, (server / 'native-worker.stderr').read_text()
        summary = json.loads((server / 'ml-result.json').read_text())
        assert summary['model_load_count'] == len(model['members']) == 1
        assert summary['requests'] == summary['successful_requests'] == 3
        assert summary['request_sha256'] == file_digest(request_path)
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
