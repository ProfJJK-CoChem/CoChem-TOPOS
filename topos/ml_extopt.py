"""Persistent, confined ORCA ExtOpt callbacks to explicit molecular ML models.

The client imports only the standard library: models stay loaded in the audited
BASE ML worker. Native energies are enumeration observations, never DFT results.
File contract: repository method matrix section 10 / ORCA 6.1 external methods.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import socket
import stat
import struct
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ml import ModelManifest
    from .models import Molecule, ResourceLimits
    from .sampling import SamplingResult

SOCKET_SCHEMA = 'topos-ml-extopt/0.1.0'
MAX_MESSAGE_BYTES = 2_000_000
EXTERNAL_MANUAL = 'https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/optimizations.html'


def send_json(connection: socket.socket, value: dict) -> None:
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if not 0 < len(encoded) <= MAX_MESSAGE_BYTES:
        raise ValueError('Persistent inference message exceeds its byte bound')
    connection.sendall(struct.pack('!I', len(encoded)) + encoded)


def receive_json(connection: socket.socket) -> dict:
    def read_exact(count: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < count:
            chunk = connection.recv(count - len(chunks))
            if not chunk:
                raise ValueError('Incomplete persistent inference message')
            chunks.extend(chunk)
        return bytes(chunks)

    size = struct.unpack('!I', read_exact(4))[0]
    if not 0 < size <= MAX_MESSAGE_BYTES:
        raise ValueError('Persistent inference message exceeds its byte bound')
    value = json.loads(read_exact(size))
    if not isinstance(value, dict):
        raise ValueError('Persistent inference message must be an object')
    return value


def _confined_regular(path: Path, root: Path, *, maximum_bytes: int = MAX_MESSAGE_BYTES) -> Path:
    root = root.resolve()
    candidate = path if path.is_absolute() else root / path
    if not candidate.resolve().is_relative_to(root):
        raise ValueError('External input path escapes its native attempt')
    relative = candidate.relative_to(root)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError('External input symlinks are not accepted')
    if not candidate.is_file() or candidate.stat().st_size > maximum_bytes:
        raise ValueError('External input must be a bounded regular file')
    return candidate


def parse_extopt_input(path: str | Path, reference: dict, native_root: str | Path, *, maximum_cores: int) -> dict:
    """Read documented extinp/XYZ without guessing charge, units or embedding."""
    root = Path(native_root).resolve()
    source = Path(path)
    source = source if source.is_absolute() else Path.cwd() / source
    source = _confined_regular(source, root)
    if not source.name.endswith('.extinp.tmp'):
        raise ValueError('Expected ORCA basename_EXT.extinp.tmp file')
    raw = source.read_text(encoding='utf-8')
    rows = [line.split('#', 1)[0].strip() for line in raw.splitlines() if line.split('#', 1)[0].strip()]
    if len(rows) != 5:
        raise ValueError('Exactly five external input fields required; point-charge embedding is unsupported')
    xyz_name, charge, multiplicity, ncores, gradient = rows
    try:
        charge, multiplicity, ncores, gradient = map(int, (charge, multiplicity, ncores, gradient))
    except ValueError as exc:
        raise ValueError('External state/core/gradient fields must be integers') from exc
    if (charge != reference['charge'] or multiplicity != reference['multiplicity']
            or not 1 <= ncores <= maximum_cores or gradient not in {0, 1}):
        raise ValueError('External state, requested cores or gradient flag differs from the bound contract')
    xyz_path = Path(xyz_name)
    if xyz_path.suffix.lower() != '.xyz':
        raise ValueError('External coordinate filename must be XYZ')
    xyz_path = xyz_path if xyz_path.is_absolute() else source.parent / xyz_path
    xyz_path = _confined_regular(xyz_path, root)
    xyz_text = xyz_path.read_text(encoding='utf-8')
    xyz = xyz_text.splitlines()
    n = len(reference['symbols'])
    if len(xyz) < 2 or xyz[0].strip() != str(n):
        raise ValueError('External XYZ atom count changed')
    atoms = [line.split() for line in xyz[2:] if line.strip()]
    if len(atoms) != n or any(len(row) != 4 for row in atoms) or [row[0] for row in atoms] != reference['symbols']:
        raise ValueError('External XYZ atom identity/order changed or geometry is incomplete')
    coordinates = [[float(value) for value in row[1:]] for row in atoms]
    if any(not math.isfinite(value) for row in coordinates for value in row):
        raise ValueError('External XYZ coordinates must be finite angstrom values')
    molecule = {**reference, 'coordinates': coordinates}
    output = source.with_name(source.name.removesuffix('.extinp.tmp') + '.engrad')
    if output.is_symlink():
        raise ValueError('External gradient output may not be a symlink')
    return {'molecule': molecule, 'output_path': str(output), 'gradient_requested': bool(gradient),
            'external_input': {'extinp_relative': source.relative_to(root).as_posix(),
                               'xyz_relative': xyz_path.relative_to(root).as_posix(),
                               'extinp_text': raw, 'xyz_text': xyz_text,
                               'extinp_sha256': hashlib.sha256(raw.encode()).hexdigest(),
                               'xyz_sha256': hashlib.sha256(xyz_text.encode()).hexdigest(),
                               'coordinate_units': 'angstrom', 'gradient_requested': bool(gradient), 'ncores': ncores}}


def connect_server(folder: str | Path, *, timeout: float) -> socket.socket:
    """Use a directory descriptor to avoid UNIX path-length limits without links."""
    folder = Path(folder)
    if not folder.is_absolute() or folder.is_symlink() or stat.S_IMODE(folder.stat().st_mode) != 0o700:
        raise ValueError('ML server directory must be an absolute private regular directory')
    path = folder / 's'
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('ML endpoint must be a private 0600 UNIX socket')
    descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    try:
        connection.connect(f'/proc/self/fd/{descriptor}/s')
    except BaseException:
        connection.close()
        raise
    finally:
        os.close(descriptor)
    return connection


def extopt_client(config_path: str | Path, config_sha256: str, input_path: str | Path) -> None:
    config_path = Path(config_path)
    if not config_path.is_absolute() or config_path.is_symlink() or not config_path.is_file():
        raise ValueError('ExtOpt configuration must be an absolute regular file')
    raw_config = config_path.read_bytes()
    if hashlib.sha256(raw_config).hexdigest() != config_sha256:
        raise ValueError('ExtOpt client configuration changed')
    config = json.loads(raw_config)
    if config.get('schema_version') != SOCKET_SCHEMA:
        raise ValueError('Unsupported ExtOpt client contract')
    parsed = parse_extopt_input(input_path, config['reference_molecule'], config['native_root'],
                               maximum_cores=config['maximum_external_cores'])
    message = {'schema_version': SOCKET_SCHEMA, 'action': 'evaluate', 'manifest_sha256': config['manifest_sha256'],
               'molecule': parsed['molecule'], 'external_input': parsed['external_input']}
    with connect_server(config['server_folder'], timeout=config['timeout_seconds']) as connection:
        send_json(connection, message)
        response = receive_json(connection)
    if response.get('status') != 'completed' or response.get('manifest_sha256') != config['manifest_sha256']:
        raise ValueError('Persistent ML callback failed: ' + str(response.get('reason', 'identity/status mismatch')))
    frame = response['frame']
    n = len(parsed['molecule']['symbols'])
    energy, gradients = frame['energy_hartree'], frame['gradient_hartree_per_bohr']
    if (frame.get('units') != {'energy': 'hartree', 'gradient': 'hartree/bohr'} or not math.isfinite(energy)
            or len(gradients) != n or any(len(row) != 3 or any(not math.isfinite(v) for v in row) for row in gradients)):
        raise ValueError('Persistent ML result lacks finite energy/gradient in the exact external units')
    rows = ['# ORCA ExtOpt: exact model energy Eh and gradient Eh/bohr', str(n), f'{energy:.17g}']
    if parsed['gradient_requested']:
        rows.extend(f'{value:.17g}' for row in gradients for value in row)
    output = Path(parsed['output_path'])
    descriptor, temporary = tempfile.mkstemp(prefix='.engrad-', dir=output.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write('\n'.join(rows) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        if output.is_symlink():
            raise ValueError('External output path changed into a symlink')
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


@dataclass(frozen=True)
class ExtOptAllocation:
    ml_threads: int
    ml_memory_mb: int
    orca_threads: int
    orca_memory_mb: int

    def validate(self, resources: ResourceLimits) -> None:
        values = (self.ml_threads, self.ml_memory_mb, self.orca_threads, self.orca_memory_mb)
        if (any(type(value) is not int for value in values) or min(self.ml_threads, self.orca_threads) < 1
                or min(self.ml_memory_mb, self.orca_memory_mb) < 64
                or self.ml_threads + self.orca_threads > resources.threads
                or self.ml_memory_mb + self.orca_memory_mb > resources.memory_mb):
            raise ValueError('Explicit concurrent ML/ORCA allocations must fit the total CPU and RAM budget')


def goat_extopt_input(molecule: Molecule, wrapper: str | Path, resources: ResourceLimits, *,
                      energy_window_kcal_mol: float = 12, max_global_iterations: int = 100) -> str:
    path = str(wrapper)
    if not Path(path).is_absolute() or any(character in path for character in '\n\r"\x00'):
        raise ValueError('ExtOpt wrapper must have a safe absolute path')
    if not math.isfinite(energy_window_kcal_mol) or energy_window_kcal_mol <= 0:
        raise ValueError('Explicit positive native energy window required')
    if type(max_global_iterations) is not int or not 3 <= max_global_iterations <= 1000:
        raise ValueError('GOAT iteration bound must be an integer from 3 to 1000')
    if resources.device != 'cpu':
        raise ValueError('ORCA driver allocation must be CPU; only the model server may use GPU')
    lines = ['! GOAT-EXPLORE ExtOpt TightOpt', f'%pal nprocs {resources.threads} end',
             f'%maxcore {max(16, int(resources.memory_mb * .75 / resources.threads))}',
             '%method', f'  ProgExt "{path}"', 'end', '%scf', '  TolE 1e-5', 'end',
             '%geom', '  TolE 1e-5', '  EnforceStrictConvergence true', 'end',
             '%goat', f'  NWORKERS {resources.threads}', f'  MAXEN {energy_window_kcal_mol:.12g}',
             '  MINGLOBALITER 3', f'  MAXGLOBALITER {max_global_iterations}', '  KEEPWORKERDATA true',
             'end', f'* xyz {molecule.charge} {molecule.multiplicity}']
    lines.extend(f'{s} {r[0]:.16g} {r[1]:.16g} {r[2]:.16g}' for s, r in zip(molecule.symbols, molecule.coordinates, strict=True))
    return '\n'.join([*lines, '*', ''])


def run_goat_extopt(molecule: Molecule, manifest: ModelManifest, resources: ResourceLimits,
                    workdir: str | Path, *, runtime, allocation: ExtOptAllocation,
                    gpu_index: int | None = None, gpu_memory_mb: int | None = None,
                    energy_window_kcal_mol: float = 12, max_global_iterations: int = 100,
                    max_requests: int = 10000, cancel_event: Event | None = None) -> SamplingResult:
    """Execute the native enumerator and persistent model via mandatory BASE."""
    import re

    from .engines import (
        ORCA_VERSION,
        _engine_version,
        _number,
        _orca_version_input,
        artifact_inventory,
    )
    from .goat import parse_goat_ensemble
    from .ml import ML_SCHEMA
    from .sampling import SamplingResult
    from .storage import atomic_json, digest_json, file_digest, read_json

    started = time.monotonic()
    result = SamplingResult(status='unsupported', engine='orca', algorithm='GOAT-EXPLORE ExtOpt',
                            method=manifest.family, potential_engine=manifest.backend,
                            potential_engine_version=manifest.package_version,
                            metadata={'execution_kind': 'not-executed', 'profile': 'goat-extopt-ml-v1',
                                      'manifest': manifest.model_dump(mode='json'), 'energy_culling_authorized': False,
                                      'energy_definition': 'explicit ML checkpoint enumeration potential, not executed DFT',
                                      'refinement_required': True, 'exhaustive': False, 'manual': EXTERNAL_MANUAL,
                                      'topology_policy': 'native GOAT-EXPLORE may break bonds; every frame requires explicit chemistry validation',
                                      'randomness': 'native GOAT engine-controlled independent initialization',
                                      'concurrent_allocations': allocation.__dict__})
    folder = Path(workdir).resolve()
    internal_cancel = Event()
    server_future = None
    executor = None
    try:
        if runtime is None or not hasattr(runtime, 'run_ml_process') or not hasattr(runtime, 'run_process'):
            raise ValueError('GOAT ExtOpt production execution requires mandatory BASE ML and ORCA authority')
        allocation.validate(resources)
        manifest.validate_molecule(molecule)
        if any(isotope is not None for isotope in molecule.isotopes):
            raise ValueError('GOAT ML isotope-dependent filtering is not validated')
        if type(max_requests) is not int or not 1 <= max_requests <= 10000:
            raise ValueError('Persistent ML request count must be bounded at 10000')
        if folder.exists() and any(folder.iterdir()):
            raise ValueError('GOAT ExtOpt requires a fresh attempt directory')
        folder.mkdir(parents=True, exist_ok=True)
        server = folder / 'ml-server'
        native = folder / 'orca'
        server.mkdir(mode=0o700)
        native.mkdir()
        orca = runtime.resolve_executable('orca')
        python = runtime.resolve_executable(manifest.backend)
        models = {str(member.verify()): member.sha256 for member in manifest.members}

        def remaining():
            seconds = resources.budget_seconds - (time.monotonic() - started)
            if seconds <= 0:
                raise TimeoutError('GOAT ExtOpt combined wall budget exhausted')
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError('GOAT ExtOpt cancelled')
            return seconds

        orca_resources = resources.model_copy(update={'threads': allocation.orca_threads,
            'memory_mb': allocation.orca_memory_mb, 'device': 'cpu', 'budget_seconds': remaining()})
        (native / 'version.inp').write_text(_orca_version_input(orca_resources))
        probe = runtime.run_process([orca, 'version.inp'], native,
                                     orca_resources.model_copy(update={'threads': 1, 'budget_seconds': min(10, remaining())}),
                                     cancel_event=cancel_event, log_prefix='version')
        result.diagnostics['orca_probe'] = probe.to_dict()
        probe_text = Path(probe.stdout_path).read_text(errors='replace')
        if (probe.status != 'completed' or _engine_version(probe_text, 'orca') != ORCA_VERSION
                or 'ORCA TERMINATED NORMALLY' not in probe_text or 'FINAL SINGLE POINT ENERGY' not in probe_text):
            result.status = probe.status if probe.status in {'cancelled', 'timed-out'} else 'unavailable'
            result.diagnostics['reason'] = 'ORCA6.1.1 actual loader diagnostic did not complete'
            return result
        result.engine_version = ORCA_VERSION
        ml_resources = resources.model_copy(update={'threads': allocation.ml_threads,
            'memory_mb': allocation.ml_memory_mb, 'budget_seconds': remaining()})
        worker = Path(__file__).with_name('ml_worker.py')
        request = {'schema_version': ML_SCHEMA, 'manifest': manifest.model_dump(mode='json'),
                   'molecules': [molecule.model_dump(mode='json')], 'resources': ml_resources.model_dump(mode='json'),
                   'gpu_memory_mb': gpu_memory_mb, 'mode': 'server',
                   'server': {'socket_name': 's', 'max_requests': max_requests,
                              'client_module_sha256': file_digest(Path(__file__)), 'request_timeout_seconds': min(600, remaining())}}
        request_path = server / 'ml-request.json'
        atomic_json(request_path, request)
        server_command = [python, '-m', 'topos.ml_worker', '--request', str(request_path)]
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='topos-owned-ml-server')
        server_future = executor.submit(runtime.run_ml_process, server_command, server, ml_resources,
            engine=manifest.backend, request_sha256=file_digest(request_path), worker_sha256=file_digest(worker),
            model_files=models, gpu_index=gpu_index, gpu_memory_mb=gpu_memory_mb, cancel_event=internal_cancel,
            log_prefix='ml-server')
        while not (server / 'ready.json').is_file():
            remaining()
            if server_future.done():
                process = server_future.result()
                result.status = process.status if process.status != 'completed' else 'failed'
                result.diagnostics.update(reason='Persistent ML worker failed before readiness', ml_server=process.to_dict())
                return result
            time.sleep(.02)
        ready = read_json(server / 'ready.json')
        if ready.get('manifest_sha256') != digest_json(request['manifest']):
            raise ValueError('Persistent ML ready receipt model identity differs')
        config = {'schema_version': SOCKET_SCHEMA, 'server_folder': str(server), 'native_root': str(native),
                  'reference_molecule': molecule.model_dump(mode='json'), 'manifest_sha256': ready['manifest_sha256'],
                  'maximum_external_cores': allocation.orca_threads, 'timeout_seconds': min(600, remaining())}
        config_path = folder / 'client-config.json'
        atomic_json(config_path, config)
        wrapper = folder / 'extopt-client'
        if any(c.isspace() for c in python) or '\x00' in python or not Path(python).is_absolute():
            raise ValueError('Audited ML interpreter path is incompatible with a fixed executable shebang')
        wrapper.write_text(f'#!{python} -I\nfrom topos.ml_extopt import extopt_client\nimport sys\n'
                           f'extopt_client({str(config_path)!r}, {file_digest(config_path)!r}, sys.argv[1])\n')
        wrapper.chmod(0o700)
        deck = goat_extopt_input(molecule, wrapper, orca_resources, energy_window_kcal_mol=energy_window_kcal_mol,
                                max_global_iterations=max_global_iterations)
        (native / 'goat.inp').write_text(deck)
        result.command = [orca, 'goat.inp']
        result.metadata.update(execution_kind='real', server_command=server_command,
                               manifest_sha256=ready['manifest_sha256'], worker_sha256=file_digest(worker),
                               client_module_sha256=file_digest(Path(__file__)), wrapper_sha256=file_digest(wrapper),
                               versions=ready['versions'], native_energy_window_kcal_mol=energy_window_kcal_mol)
        process = runtime.run_process(result.command, native,
            orca_resources.model_copy(update={'budget_seconds': remaining()}), cancel_event=cancel_event,
            log_prefix='goat', threads_per_process=1)
        result.status = process.status
        result.diagnostics['process'] = process.to_dict()
        # Graceful shutdown writes the final model revalidation and count receipt.
        if not server_future.done():
            with connect_server(server, timeout=min(10, max(.01, resources.budget_seconds - (time.monotonic() - started)))) as connection:
                send_json(connection, {'schema_version': SOCKET_SCHEMA, 'action': 'stop', 'manifest_sha256': ready['manifest_sha256']})
                receive_json(connection)
        server_process = server_future.result(timeout=max(.01, resources.budget_seconds - (time.monotonic() - started)))
        result.diagnostics['ml_server'] = server_process.to_dict()
        if process.status != 'completed':
            result.status = process.status
            result.diagnostics['reason'] = process.reason
            ensemble = native / 'goat.finalensemble.xyz'
            if ensemble.is_file():
                try:
                    result.ensemble = parse_goat_ensemble(ensemble, molecule)
                except ValueError as exc:
                    result.diagnostics['partial_ensemble_error'] = str(exc)
            return result
        if server_process.status != 'completed':
            result.status = server_process.status
            result.diagnostics['reason'] = 'Persistent ML server did not complete its verification receipt'
            return result
        server_summary = read_json(server / 'ml-result.json')
        if (server_summary.get('request_sha256') != file_digest(request_path) or server_summary.get('manifest_sha256') != ready['manifest_sha256']
                or server_summary.get('requests', 0) < 1 or server_summary.get('requests') != server_summary.get('successful_requests')):
            raise ValueError('Persistent ML session has no complete matching sequence of successful callbacks')
        result.metadata['server_summary'] = server_summary
        raw = Path(process.stdout_path).read_text(errors='replace')
        ensemble = native / 'goat.finalensemble.xyz'
        if ensemble.is_file():
            result.ensemble = parse_goat_ensemble(ensemble, molecule)
            for frame in result.ensemble:
                frame.source = 'GOAT-EXPLORE ExtOpt'
                frame.metadata.update(energy_definition='ML checkpoint enumeration energy; no DFT claim',
                                      potential_engine=manifest.backend, manifest_sha256=ready['manifest_sha256'])
        if process.status != 'completed':
            result.diagnostics['reason'] = process.reason
            return result
        if _engine_version(raw, 'orca') != ORCA_VERSION or 'ORCA TERMINATED NORMALLY' not in raw or not result.ensemble:
            raise ValueError('Native external GOAT did not establish its completed ensemble')
        windows = re.findall(r'Maximum Conf\. Energy\s*\.\.\.\s*([-+0-9.eE]+)\s+kcal/mol', raw)
        minima = re.findall(r'Lowest energy conformer\s*:\s*([-+0-9.eE]+)\s+Eh', raw)
        if (not windows or abs(_number(windows[-1]) - energy_window_kcal_mol) > 5e-4
                or not minima or abs(_number(minima[-1]) - min(frame.energy_hartree for frame in result.ensemble)) > 1e-5):
            raise ValueError('Native ML ensemble energy/window differs from its explicit protocol summary')
        result.converged = bool(re.search(r'Global minimum found\s*!', raw, re.I))
        if not result.converged:
            result.status = 'partial'
            result.diagnostics['reason'] = 'Native GOAT stopping criterion not satisfied; raw ML enumeration retained'
        result.metadata['convergence_scope'] = 'native finite ML enumeration only; actual DFT refinement and chemistry checks required'
        return result
    except InterruptedError as exc:
        result.status, result.diagnostics['reason'] = 'cancelled', str(exc)
        return result
    except TimeoutError as exc:
        result.status, result.diagnostics['reason'] = 'timed-out', str(exc)
        return result
    except (ValueError, OSError, RuntimeError) as exc:
        result.status, result.diagnostics['reason'] = 'failed', str(exc)
        return result
    finally:
        if server_future is not None and not server_future.done():
            internal_cancel.set()
            try:
                server_future.result(timeout=10)
            except Exception as exc:
                result.diagnostics['server_cleanup'] = str(exc)
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        if folder.exists():
            try:
                result.artifacts = artifact_inventory(folder)
            except (ValueError, OSError) as exc:
                result.status, result.diagnostics['artifact_error'] = 'failed', str(exc)
        result.elapsed_seconds = time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('extinp', type=Path)
    args = parser.parse_args()
    extopt_client(args.config, args.sha256, args.extinp)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
