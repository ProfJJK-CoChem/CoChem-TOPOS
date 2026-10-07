"""Isolate ORCA 6.1.1's initial Pickett property writer through BASE.

This diagnostic runs four physical B3LYP-D4/def2-TZVPP single points on an
unchanged geometry from the retained failed native water input. It compares
serial/MPI execution, each with/without the official Pickett output keyword.
It does not calculate the VPT2 force field and cannot satisfy VPT2 acceptance.
Licensed installation is supplied by the existing BASE hosted provisioner.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topos-root', required=True, type=Path)
    parser.add_argument('--registry', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--budget-seconds-per-case', type=float, default=90)
    args = parser.parse_args()
    root, output = args.topos_root.resolve(), args.output.resolve()
    if output.is_relative_to(root) or output.exists():
        parser.error('Use a fresh evidence directory outside TOPOS source')
    sys.path.insert(0, str(root))
    from topos.base_integration import BaseRuntime
    from topos.engines import ORCA_VERSION, _engine_version, _orca_input, artifact_inventory
    from topos.models import MethodSpec, Molecule, ResourceLimits, utc_now
    from topos.release import source_inventory
    from topos.storage import atomic_json, file_digest

    source_before = source_inventory(root)
    fixture_dir = root / 'tests/v010/fixtures/orca_vpt2_mpi_property_failure'
    fixture = fixture_dir / 'extended.inp'
    fixture_manifest = json.loads((fixture_dir / 'provenance.json').read_text())
    entry = next(item for item in fixture_manifest['artifacts'] if item['path'] == fixture.name)
    if file_digest(fixture) != entry['sha256'] or fixture.stat().st_size != entry['bytes']:
        raise ValueError('Native geometry source differs from retained failure evidence')
    coordinates = re.search(r'(?ms)^\* xyz 0 1\s*\n(.*?)^\*\s*$', fixture.read_text())
    if coordinates is None:
        raise ValueError('Expected retained neutral-singlet native input geometry')
    rows = [line.split() for line in coordinates[1].splitlines() if line.strip()]
    if len(rows) != 3 or [row[0] for row in rows] != ['O', 'H', 'H'] or any(len(row) != 4 for row in rows):
        raise ValueError('Unexpected retained water geometry')
    molecule = Molecule(symbols=[row[0] for row in rows], coordinates=[[float(value) for value in row[1:]] for row in rows])
    method = MethodSpec(engine='orca', method='B3LYP', basis='def2-TZVPP', dispersion='D4',
                        profile_id='orca-vpt2-reference-v1')
    requested = ResourceLimits(budget_seconds=args.budget_seconds_per_case, threads=2, memory_mb=4096)
    output.mkdir(parents=True)
    receipt_path = output / 'pickett-property-diagnostic.json'
    receipt = {
        'schema': 'topos-orca-pickett-property-diagnostic/0.1.0',
        'status': 'running', 'started_at': utc_now(),
        'scope': 'SCF Pickett property writer compatibility only; no VPT2 force field or acceptance',
        'geometry_source': {'run_url': fixture_manifest['run_url'], 'artifact': fixture.name,
                            'sha256': entry['sha256'], 'original_artifact_path': entry['original_artifact_path']},
        'source_sha256': source_before, 'script_sha256': file_digest(Path(__file__)),
        'github_repository': os.environ.get('GITHUB_REPOSITORY'),
        'github_run_id': os.environ.get('GITHUB_RUN_ID'), 'github_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        'github_sha': os.environ.get('GITHUB_SHA'), 'cases': {},
    }
    atomic_json(receipt_path, receipt)
    try:
        runtime = BaseRuntime(args.registry)
        runtime.validate_resources(requested)
        binary = runtime.resolve_executable('orca')
        receipt.update(base=runtime.provenance(), executable_sha256=file_digest(Path(binary)))
        for workers, pickett in ((1, False), (2, False), (1, True), (2, True)):
            name = f'{"serial" if workers == 1 else "mpi2"}-{"pickett" if pickett else "control"}'
            folder = output / name
            folder.mkdir()
            allocation = requested.model_copy(update={'threads': workers})
            # Build the original requested per-worker MaxCore (1536 MiB),
            # then vary only native worker count and Pickett output request.
            deck = _orca_input(molecule, method, requested, 'energy')
            deck = deck.replace('%pal nprocs 2 end', f'%pal nprocs {workers} end')
            if pickett:
                deck = deck.replace('* xyz', '%output\n  Pickettname "pickett.txt"\nend\n* xyz', 1)
            (folder / 'property.inp').write_text(deck)
            process = runtime.run_process([binary, 'property.inp'], folder, allocation,
                                          log_prefix='property', threads_per_process=1)
            raw = Path(process.stdout_path).read_text(errors='replace')
            normal = 'ORCA TERMINATED NORMALLY' in raw and _engine_version(raw, 'orca') == ORCA_VERSION
            native_energies = re.findall(r'(?m)^FINAL SINGLE POINT ENERGY\s+([-+0-9.]+)\s*$', raw)
            pickett_file = folder / 'pickett.txt'
            receipt['cases'][name] = {
                'process': process.to_dict(), 'resources': allocation.model_dump(mode='json'),
                'native_maxcore_mb': 1536, 'method': method.model_dump(mode='json'),
                'normal_completion': normal, 'final_energy_literals': native_energies,
                'initial_pickett_write_reached': 'writing data to file in Pickett format' in raw,
                'properties_error_printed': 'ORCA finished by error termination in PROPERTIES' in raw,
                'pickett_file': {'exists': pickett_file.is_file(),
                                 'bytes': pickett_file.stat().st_size if pickett_file.is_file() else None,
                                 'sha256': file_digest(pickett_file) if pickett_file.is_file() else None},
                'artifacts': [item.model_dump(mode='json') for item in artifact_inventory(folder)],
            }
            atomic_json(receipt_path, receipt)
        receipt['sources_unchanged'] = source_inventory(root) == source_before
        receipt['serial_pickett_supported'] = (
            receipt['cases']['serial-pickett']['process']['status'] == 'completed'
            and receipt['cases']['serial-pickett']['normal_completion']
            and bool(receipt['cases']['serial-pickett']['final_energy_literals'])
            and (receipt['cases']['serial-pickett']['pickett_file']['bytes'] or 0) > 0)
        receipt['parallel_pickett_supported'] = (
            receipt['cases']['mpi2-pickett']['process']['status'] == 'completed'
            and receipt['cases']['mpi2-pickett']['normal_completion']
            and bool(receipt['cases']['mpi2-pickett']['final_energy_literals'])
            and (receipt['cases']['mpi2-pickett']['pickett_file']['bytes'] or 0) > 0)
        receipt['status'] = 'diagnostic-retained' if receipt['sources_unchanged'] else 'source-integrity-failed'
    except Exception as exc:
        receipt.update(status='diagnostic-failed', reason=str(exc), exception_type=type(exc).__name__)
    receipt['completed_at'] = utc_now()
    atomic_json(receipt_path, receipt)
    print(json.dumps({'status': receipt['status'], 'receipt': str(receipt_path),
                      'serial_pickett_supported': receipt.get('serial_pickett_supported'),
                      'parallel_pickett_supported': receipt.get('parallel_pickett_supported')}))
    return 0 if receipt['status'] == 'diagnostic-retained' else 1


if __name__ == '__main__':
    raise SystemExit(main())
