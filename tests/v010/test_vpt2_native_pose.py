"""Authenticated historical native frame/rejection contracts, not new chemistry."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from topos.anharmonic import (
    parse_orca_vpt2_geometry,
    verify_vpt2_native_frame_reference,
    vpt2_native_reference_pose,
    vpt2_reference_evidence_identity,
    vpt2_reference_policy,
)
from topos.engines import EngineParseError, EngineResult, _orca_input
from topos.matrix_r2 import R2AnharmonicProtocol, r2_reference_method
from topos.models import MethodSpec, ResourceLimits
from topos.native_hessian import orca_frequency_input, parse_orca_hessian
from topos.rotational_transfer import proper_alignment, rotate_cartesian_hessian
from topos.storage import digest_json

FIXTURES = Path(__file__).parent / 'fixtures' / 'orca_vpt2_native_pose'


def retained_case(label):
    reference = EngineResult.model_validate(json.loads((FIXTURES / f'{label}-reference-result.json').read_text())['result'])
    geometry = parse_orca_vpt2_geometry((FIXTURES / f'{label}-native.stdout').read_text(), natoms=3)
    return reference, geometry, FIXTURES / f'{label}-native.hess'


def test_retained_original_vpt2_receipts_match_authenticated_provenance():
    proof = json.loads((FIXTURES / 'provenance.json').read_text())
    assert 'No independent native-pose Freq receipt exists' in proof['scope']
    for artifact in proof['artifacts']:
        payload = (FIXTURES / artifact['path']).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == artifact['sha256']
        assert len(payload) == artifact['bytes']


@pytest.mark.parametrize('label', ['extended', 'licensed_pytest'])
def test_exact_native_pose_comes_from_initial_hessian_not_rounded_table(label):
    reference, geometry, hessian = retained_case(label)
    pose = vpt2_native_reference_pose(reference.molecule, geometry, hessian)
    parsed = parse_orca_hessian(hessian, reference.molecule)
    assert pose.coordinates == parsed['native_coordinates_angstrom']
    assert pose.coordinates != geometry['coordinates_angstrom']
    assert pose.model_dump(exclude={'coordinates'}) == reference.molecule.model_dump(exclude={'coordinates'})
    alignment = proper_alignment(pose.coordinates, reference.molecule.coordinates, geometry['masses_amu'])
    assert alignment['max_atom_displacement_angstrom'] < 6e-9
    # These unchanged outputs explicitly used different finite-grid poses.
    raw = (FIXTURES / f'{label}-native.stdout').read_text()
    assert 'Rotating Geometry into its principle axis frame!' in raw
    assert 'Rotationally invariant grid construction     ... off' in raw
    assert raw.index('Reading Hessian anharmonic.hess') < raw.index('Reading Hessian anharmonic_D001.hess')


@pytest.mark.parametrize('label', ['extended', 'licensed_pytest'])
def test_old_rotated_reference_is_still_rejected_at_original_strict_tolerance(label):
    reference, geometry, hessian = retained_case(label)
    parsed = parse_orca_hessian(hessian, reference.molecule)
    direct = np.asarray(parsed['hessian_hartree_per_bohr2'])
    pose = reference.molecule.model_copy(update={'coordinates': geometry['coordinates_angstrom']})
    principal = parse_orca_hessian(hessian, pose)
    rotation = proper_alignment(pose.coordinates, reference.molecule.coordinates, geometry['masses_amu'])
    composed = rotate_cartesian_hessian(principal['hessian_hartree_per_bohr2'], rotation['rotation_source_to_target'])
    assert np.allclose(direct, composed, atol=1e-14, rtol=0)
    assert 1.9e-5 < np.max(np.abs(direct - reference.metadata['hessian_hartree_per_bohr2'])) < 2.1e-5
    assert not np.allclose(direct, reference.metadata['hessian_hartree_per_bohr2'], atol=1e-7, rtol=1e-6)
    with pytest.raises(EngineParseError, match='exact native equilibrium pose'):
        verify_vpt2_native_frame_reference(reference.molecule, geometry, hessian, reference,
                                           reference.metadata['requested_method'], reference.metadata['executable_sha256'])


@pytest.mark.parametrize('label', ['extended', 'licensed_pytest'])
def test_native_pose_decks_keep_same_hamiltonian_thresholds_and_requested_resources(label):
    reference, geometry, hessian = retained_case(label)
    native_pose = vpt2_native_reference_pose(reference.molecule, geometry, hessian)
    method = MethodSpec.model_validate(reference.metadata['requested_method'])
    resources = ResourceLimits.model_validate(reference.metadata['protocol']['resources'])
    frequency = orca_frequency_input(native_pose, method, resources, check_cpu_affinity=False)
    gradient = _orca_input(native_pose, method, resources, 'gradient')
    original_frequency = (FIXTURES / f'{label}-reference.inp').read_text()
    assert frequency.split('* xyz')[0] == original_frequency.split('* xyz')[0]
    assert frequency != original_frequency
    assert 'ExtremeSCF DEFGRID3 D4 def2-TZVPP RIJCOSX def2/J' in frequency
    assert '%pal nprocs 2 end' in frequency and '%maxcore 1536' in frequency
    assert 'Z_Tol 1e-14' in frequency and ' Engrad' in gradient
    assert 'Opt' not in frequency and 'Opt' not in gradient


def test_policy_enters_component_identity_and_does_not_enter_method_keywords():
    spec = r2_reference_method(purpose='anharmonic')
    protocol = R2AnharmonicProtocol(**spec.model_dump(), displacement=.05, semirigid_modes=True)
    native = protocol.model_dump(mode='json')
    legacy = {k: v for k, v in native.items() if k != 'reference_validation_policy'}
    assert digest_json(native) != digest_json(legacy)
    assert protocol.native_method() == spec
    assert native['reference_validation_policy'] == vpt2_reference_policy()['policy_id']
    assert vpt2_reference_policy()['gradient_threshold_hartree_per_bohr'] == 1e-7
    assert vpt2_reference_policy()['hessian_atol_hartree_per_bohr2'] == 1e-7
    assert vpt2_reference_policy()['hessian_rtol'] == 1e-6


def test_legacy_recovery_manifest_cannot_gain_native_pose_validation_silently(tmp_path):
    from topos.anharmonic import run_orca_vpt2
    from topos.storage import IntegrityError

    reference, _, _ = retained_case('extended')
    spec = MethodSpec.model_validate(reference.metadata['requested_method'])
    resources = ResourceLimits(threads=1, memory_mb=4096)
    result = run_orca_vpt2(reference.molecule, spec, resources, tmp_path,
                           executable='/missing-orca', semirigid_modes=True)
    assert result.status == 'unavailable'
    manifest = tmp_path / 'vpt2-protocol.json'
    protocol = json.loads(manifest.read_text())
    assert protocol['reference_validation_policy'] == vpt2_reference_policy()
    del protocol['reference_validation_policy']
    manifest.write_text(json.dumps(protocol))
    with pytest.raises(IntegrityError, match='recovery protocol changed'):
        run_orca_vpt2(reference.molecule, spec, resources, tmp_path,
                      executable='/missing-orca', semirigid_modes=True)


def test_portable_reference_identity_preserves_science_and_actual_bytes_when_locators_rebind():
    reference, _, _ = retained_case('extended')
    payload = reference.model_dump(mode='json')

    def rebind(value):
        if isinstance(value, dict):
            return {key: rebind(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rebind(item) for item in value]
        return '/imported' + value if isinstance(value, str) and value.startswith('/home/runner/') else value

    relocated = EngineResult.model_validate(rebind(payload))
    assert vpt2_reference_evidence_identity(reference) == vpt2_reference_evidence_identity(relocated)
    altered = relocated.model_copy(deep=True)
    altered.metadata['hessian_hartree_per_bohr2'][0][0] += .01
    assert vpt2_reference_evidence_identity(reference) != vpt2_reference_evidence_identity(altered)
    altered = relocated.model_copy(deep=True)
    altered.artifacts[0].sha256 = '0' * 64
    assert vpt2_reference_evidence_identity(reference) != vpt2_reference_evidence_identity(altered)
