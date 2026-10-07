"""Retain genuine licensed test IDs and source-bound JUnit evidence for release."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from topos.base_integration import BaseRuntime  # noqa: E402
from topos.release import sha256, source_inventory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error('Evidence must remain outside the source checkout')
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / 'pytest-receipt.json'
    junit = output / 'native-pytest.xml'
    log = output / 'native-pytest.log'
    if any(path.exists() for path in (receipt_path, junit, log)):
        parser.error('Refusing to overwrite prior native pytest evidence')
    before = source_inventory(ROOT)
    receipt = {'schema_version': 'topos-native-pytest/1', 'status': 'failed',
               'github_repository': os.environ.get('GITHUB_REPOSITORY'),
               'github_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
               'github_run_id': os.environ.get('GITHUB_RUN_ID'),
               'github_sha': os.environ.get('GITHUB_SHA'),
               'verification': {'source_sha256': before, 'sources_unchanged': False, 'checks': []}}
    exit_code = 3
    try:
        runtime = BaseRuntime(args.registry)
        binary = runtime.resolve_executable('orca')
        receipt['base'] = runtime.provenance()
        receipt['orca_sha256'] = sha256(Path(binary))
        environment = dict(os.environ, TOPOS_ORCA_EXECUTABLE=binary, TOPOS_REQUIRE_BASE='1',
                           COCHEM_CONFIG=str(args.registry.resolve()), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
        command = [sys.executable, '-m', 'pytest', 'tests/v010/test_native_hessian.py',
                   'tests/v010/test_anharmonic.py',
                   'tests/v010/test_reference_thermal.py::test_actual_licensed_orca_ordinary_thermal_reference_import',
                   '-q', f'--junitxml={junit}',
                   '--basetemp', str(output / 'native-pytest-work')]
        with log.open('x') as stream:
            result = subprocess.run(command, cwd=ROOT, env=environment, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=1800, check=False)
        exit_code = result.returncode
        cases = list(ET.parse(junit).iter('testcase')) if junit.is_file() else []
        summary = {'tests': len(cases), 'failures': sum(c.find('failure') is not None for c in cases),
                   'errors': sum(c.find('error') is not None for c in cases),
                   'skipped': sum(c.find('skipped') is not None for c in cases)}
        receipt['verification']['checks'] = [{'check': 'pytest', 'command': command,
            'exit_code': exit_code, 'junit': summary, 'junit_path': junit.name,
            'junit_sha256': sha256(junit) if junit.is_file() else None, 'log_sha256': sha256(log)}]
        unchanged = source_inventory(ROOT) == before
        receipt['verification']['sources_unchanged'] = unchanged
        passed = exit_code == 0 and unchanged and summary['tests'] > 0 and all(
            summary[key] == 0 for key in ('failures', 'errors', 'skipped'))
        receipt['status'] = 'passed' if passed else 'failed'
        if not passed and exit_code == 0:
            exit_code = 1
    except Exception as exc:
        receipt.update(reason=str(exc), exception_type=type(exc).__name__)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status': receipt['status'], 'reason': receipt.get('reason'),
                      'receipt': str(receipt_path), 'checks': receipt['verification']['checks']}))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
