"""Historical raw-file integrity checks, not current licensed calculation acceptance.

The genuine old receipt and unchanged text files are deliberately an incomplete
cache (binary scratch is omitted). These tests call nonexecuting raw validators;
they never write a completed cache receipt or invent a native process result.
"""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from topos.engines import EngineResult
from topos.models import MethodSpec, ResourceLimits
from topos.native_hessian import (
    _analysis_matches,
    parse_orca_hessian,
    verify_orca_gradient_result,
    verify_orca_hessian_result,
)
from topos.science import constants_provenance, harmonic_analysis
from topos.storage import IntegrityError


@pytest.fixture
def historical_derivatives(tmp_path):
    fixture = Path(__file__).parent / 'fixtures' / 'orca_native_hessian_attribution'
    provenance = json.loads((fixture / 'provenance.json').read_text())
    original_prefix = '/home/runner/work/_temp/topos-orca-extended/native-vpt2/native/reference/'
    source_prefix = '/workspace/.cochem-setup/base-topos-proposal/seventh-topos-artifact/topos-orca-extended/native-vpt2/native/reference/'
    for name, identity in provenance['files'].items():
        data = (fixture / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == identity['sha256']
        assert len(data) == identity['size_bytes']
        if name != 'completed-result.json':
            path = tmp_path / identity['source_path'].removeprefix(source_prefix)
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fixture / name, path)

    def relocate(value):
        if isinstance(value, dict):
            return {key: relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        if isinstance(value, str):
            return value.replace(original_prefix, str(tmp_path) + '/')
        return value

    result = EngineResult.model_validate(relocate(json.loads((fixture / 'completed-result.json').read_text())['result']))
    method = MethodSpec.model_validate(result.metadata['requested_method'])
    resources = ResourceLimits.model_validate({**result.metadata['protocol']['resources'], 'budget_seconds': 600})
    identity = {'executable': result.metadata['executable'],
                'executable_sha256': result.metadata['executable_sha256']}
    # Expected identity comes from separately authenticated historical protocol,
    # not an observed local executable or a claim of current ORCA execution.
    return result, method, resources, tmp_path, identity


def verify_hessian(evidence, result=None, **identity_changes):
    historical, method, resources, root, identity = evidence
    return verify_orca_hessian_result(result or historical, historical.molecule, method, resources, root,
                                      gradient_threshold=1e-7, **(identity | identity_changes))


def verify_gradient(evidence, result=None):
    historical, method, resources, root, identity = evidence
    gradient = result or EngineResult.model_validate(historical.metadata['reference_gradient_result'])
    return verify_orca_gradient_result(gradient, historical.molecule, method, resources, root, **identity)


def test_authentic_historical_derivatives_reparse_without_a_completed_cache_or_execution(historical_derivatives):
    evidence = historical_derivatives
    historical = evidence[0]
    energy, gradient = verify_gradient(evidence)
    if historical.metadata['analysis']['constants']['version'] == constants_provenance()['version']:
        analysis = verify_hessian(evidence)
    else:
        # The authentic receipt retains its original SciPy profile. A different
        # provider version must not become a reusable completed cache, even when
        # its physical constants and independently reparsed quantities agree.
        with pytest.raises(IntegrityError, match='cache analysis/converged'):
            verify_hessian(evidence)
        folder = Path(historical.diagnostics['process']['stdout_path']).parent
        parsed = parse_orca_hessian(folder / 'frequency.hess', historical.molecule)
        analysis = harmonic_analysis(historical.molecule, parsed['hessian_hartree_per_bohr2'],
                                     gradient_hartree_per_bohr=gradient, gradient_threshold=1e-7)
        stored = historical.metadata['analysis']
        # Retain the validator's original 1e-12 numerical comparison and all
        # categorical physical gates. Only the provider version is expected to
        # differ, and that difference has already required cache rejection.
        assert _analysis_matches({k: v for k, v in stored.items() if k != 'constants'},
                                 {k: v for k, v in analysis.items() if k != 'constants'})
        assert {k: v for k, v in stored['constants'].items() if k != 'version'} == {
            k: v for k, v in analysis['constants'].items() if k != 'version'}
        assert analysis['constants'] == constants_provenance()
    assert analysis['validity'] == 'harmonic-minimum-within-thresholds'
    assert analysis['stationary'] is True and len(analysis['frequencies_cm1']) == 3
    assert energy == evidence[0].energy_hartree
    assert gradient.tolist() == evidence[0].gradient_hartree_per_bohr
    assert not (evidence[3] / 'completed.json').exists()
    assert not (evidence[3] / 'reference.json').exists()


@pytest.mark.parametrize('field', [
    'energy', 'gradient', 'molecule', 'operation', 'method', 'version', 'converged',
    'requested_method', 'profile', 'executable', 'executable_hash', 'resources',
    'command', 'process_command', 'returncode', 'process_status', 'version_probe',
])
def test_historical_gradient_metadata_corruption_is_rejected(historical_derivatives, field):
    result = EngineResult.model_validate(historical_derivatives[0].metadata['reference_gradient_result'])
    md = result.metadata
    if field == 'energy':
        result.energy_hartree += .01
    elif field == 'gradient':
        result.gradient_hartree_per_bohr = [[0., 0., 0.]] * 3
    elif field == 'molecule':
        result.molecule.coordinates[0][0] += .01
    elif field == 'operation':
        result.operation = 'energy'
    elif field == 'method':
        result.method = 'HF'
    elif field == 'version':
        result.engine_version = '6.1.0'
    elif field == 'converged':
        result.converged = False
    elif field == 'requested_method':
        md['requested_method']['basis'] = 'def2-SVP'
    elif field == 'profile':
        md['profile_id'] = 'orca-mapping-v4.1'
    elif field == 'executable':
        md['executable'] += '-different'
    elif field == 'executable_hash':
        md['executable_sha256'] = '0' * 64
    elif field == 'resources':
        md['resources']['threads'] = 1
    elif field == 'command':
        result.command[-1] = 'frequency.inp'
    elif field == 'process_command':
        result.diagnostics['process']['command'][-1] = 'frequency.inp'
    elif field == 'returncode':
        result.diagnostics['process']['returncode'] = 1
    elif field == 'process_status':
        result.diagnostics['process']['status'] = 'failed'
    else:
        result.diagnostics['version_probe_process']['command'][-1] = 'job.inp'
    with pytest.raises(IntegrityError):
        verify_gradient(historical_derivatives, result)


@pytest.mark.parametrize('field', [
    'energy', 'gradient', 'hessian', 'analysis_frequency', 'analysis_stationary',
    'analysis_validity', 'converged', 'masses', 'coordinates', 'alignment', 'units',
    'protocol_method', 'protocol_resources', 'protocol_executable', 'output_molecule',
    'reference_gradient', 'reference_artifact', 'operation', 'process_returncode',
])
def test_historical_hessian_metadata_corruption_is_rejected(historical_derivatives, field):
    result = historical_derivatives[0].model_copy(deep=True)
    md = result.metadata
    if field == 'energy':
        result.energy_hartree += .01
    elif field == 'gradient':
        result.gradient_hartree_per_bohr = [[0., 0., 0.]] * 3
    elif field == 'hessian':
        md['hessian_hartree_per_bohr2'][0][0] += .01
    elif field == 'analysis_frequency':
        md['analysis']['frequencies_cm1'][0] += 1
    elif field == 'analysis_stationary':
        md['analysis']['stationary'] = False
    elif field == 'analysis_validity':
        md['analysis']['validity'] = 'unverified'
    elif field == 'converged':
        result.converged = False
    elif field == 'masses':
        md['native_masses_amu'][0] += 1
    elif field == 'coordinates':
        md['native_coordinates_angstrom'][0][0] += .01
    elif field == 'alignment':
        md['native_to_requested_frame']['max_atom_displacement_angstrom'] += .01
    elif field == 'units':
        md['units'] = 'kcal/mol/angstrom^2'
    elif field == 'protocol_method':
        md['protocol']['method']['basis'] = 'def2-SVP'
    elif field == 'protocol_resources':
        md['protocol']['resources']['threads'] = 1
    elif field == 'protocol_executable':
        md['protocol']['executable_sha256'] = '0' * 64
    elif field == 'output_molecule':
        md['output_molecule']['charge'] = 1
    elif field == 'reference_gradient':
        md['reference_gradient_result']['gradient_hartree_per_bohr'] = [[0., 0., 0.]] * 3
    elif field == 'reference_artifact':
        md['reference_gradient_result']['artifacts'][0]['size_bytes'] += 1
    elif field == 'operation':
        result.operation = 'gradient'
    else:
        result.diagnostics['process']['returncode'] = 1
    with pytest.raises(IntegrityError):
        verify_hessian(historical_derivatives, result)


@pytest.mark.parametrize('field', ['method', 'molecule', 'resources', 'executable_hash', 'gradient_threshold'])
def test_historical_receipt_cannot_be_used_for_a_different_current_protocol(historical_derivatives, field):
    result, method, resources, root, identity = historical_derivatives
    molecule = result.molecule.model_copy(deep=True)
    threshold = 1e-7
    if field == 'method':
        method = method.model_copy(update={'basis': 'def2-SVP'})
    elif field == 'molecule':
        molecule.coordinates[0][0] += .01
    elif field == 'resources':
        resources = resources.model_copy(update={'threads': 1})
    elif field == 'executable_hash':
        identity = identity | {'executable_sha256': '0' * 64}
    else:
        threshold = 1e-5
    with pytest.raises(IntegrityError):
        verify_orca_hessian_result(result, molecule, method, resources, root, gradient_threshold=threshold, **identity)


@pytest.mark.parametrize('field', ['gradient_deck', 'frequency_deck', 'version_deck', 'version_stdout', 'completion_stdout', 'engrad'])
def test_rehashed_changed_raw_text_cannot_override_the_physical_protocol(historical_derivatives, field):
    result = historical_derivatives[0].model_copy(deep=True)
    derivative = result.metadata['reference_gradient_result']
    if field == 'frequency_deck':
        path = Path(result.diagnostics['process']['stdout_path']).with_name('frequency.inp')
        changed = path.read_text().replace(' Freq', ' NumFreq')
    elif field == 'completion_stdout':
        path = Path(result.diagnostics['process']['stdout_path'])
        changed = path.read_text().replace('ORCA TERMINATED NORMALLY', 'completion absent')
    else:
        folder = Path(derivative['diagnostics']['process']['stdout_path']).parent
        name = {'gradient_deck': 'job.inp', 'version_deck': 'version.inp',
                'version_stdout': 'version.stdout', 'engrad': 'job.engrad'}[field]
        path = folder / name
        raw = path.read_text()
        if field == 'gradient_deck':
            changed = raw.replace(' Engrad', ' SP')
        elif field == 'version_deck':
            changed = raw.replace('STO-3G', 'def2-SVP')
        elif field == 'version_stdout':
            changed = raw.replace('6.1.1', '6.1.0')
        else:
            changed = raw.replace(f'{result.energy_hartree:.12f}', f'{result.energy_hartree + .01:.12f}')
    assert changed != path.read_text()
    path.write_text(changed)
    for inventory in (result.artifacts, derivative['artifacts']):
        for artifact in inventory:
            locator = artifact.path if hasattr(artifact, 'path') else artifact['path']
            if locator == str(path):
                identity = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size_bytes': path.stat().st_size}
                if isinstance(artifact, dict):
                    artifact.update(identity)
                else:
                    artifact.sha256, artifact.size_bytes = identity['sha256'], identity['size_bytes']
    with pytest.raises(IntegrityError):
        verify_hessian(historical_derivatives, result)
