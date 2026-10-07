"""Native ORCA VPT2 for explicitly suitable unconstrained semirigid molecules.

Method and applicability follow ORCA 6.1 section 5.19. Native 6.1 output grammar
was checked against the publicly archived furan output cited in PARSER_SOURCE;
that source is parser evidence, not TOPOS ORCA 6.1.1 execution acceptance.
No full-molecule VPT2 is inferred for nonstationary frozen-monomer structures.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable
from uuid import uuid4

import numpy as np
from scipy import constants

from .engines import (
    ORCA_VERSION,
    EngineParseError,
    EngineResult,
    _engine_version,
    _number,
    artifact_inventory,
)
from .models import Artifact, MethodSpec, Molecule, ResourceLimits
from .native_hessian import (
    _analysis_matches,
    _derivative_stopped,
    _raw_artifact,
    _raw_process,
    _read_completed,
    orca_frequency_input,
    parse_orca_hessian,
    run_orca_hessian,
    verify_orca_hessian_result,
)
from .runtime import run_process
from .science import HARTREE_J, rotational_constants
from .storage import IntegrityError, atomic_json, digest_json, file_digest

VPT2_MANUAL = 'https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/vpt2.html'
PARSER_SOURCE = 'https://github.com/physicien/parser_vpt2/blob/main/data/VPT2_furan_vpt2.out'
_FLOAT = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?'
VPT2_REFERENCE_POLICY_ID = 'orca-vpt2-same-native-pose-reference-v1'


def vpt2_reference_policy() -> dict[str, Any]:
    """Bind independent derivatives to the actual VPT2 numerical-grid pose."""
    return {'policy_id': VPT2_REFERENCE_POLICY_ID,
            'schema': 'topos-vpt2-stationary-reference-policy/0.1.0',
            'pose_source': 'initial native anharmonic.hess $atoms; unrounded bohr coordinates',
            'preflight': 'immutable independent derivatives at requested input pose',
            'native_pose_reference': 'independently executed same-level EnGrad and analytic Freq; no optimization',
            'gradient_threshold_hartree_per_bohr': 1e-7, 'minimum_mode_cm1': 50.0,
            'hessian_atol_hartree_per_bohr2': 1e-7, 'hessian_rtol': 1e-6,
            'deadline_policy': 'original shared wall-clock budget; no automatic extension',
            'manual': VPT2_MANUAL}


def vpt2_native_reference_pose(molecule: Molecule, geometry: dict[str, Any],
                               hessian_path: str | Path) -> Molecule:
    """Verify indexed rigid identity and retain the native equilibrium pose."""
    from .rotational_transfer import proper_alignment

    if geometry['symbols'] != molecule.symbols:
        raise EngineParseError('native VPT2 atom order differs from reference')
    alignment = proper_alignment(geometry['coordinates_angstrom'], molecule.coordinates, geometry['masses_amu'])
    if alignment['max_atom_displacement_angstrom'] > 2e-7:
        raise EngineParseError('native VPT2 geometry is not the reference under a proper rigid rotation')
    table_molecule = molecule.model_copy(update={'coordinates': geometry['coordinates_angstrom']})
    parsed = parse_orca_hessian(hessian_path, table_molecule)
    return molecule.model_copy(update={'coordinates': parsed['native_coordinates_angstrom']})


def vpt2_reference_evidence_identity(reference: EngineResult) -> dict[str, Any]:
    """Portable receipt identity: scientific/process fields and artifact bytes.

    Locators can be rebound when immutable snapshots are imported. Native
    artifact hashes, actual process outcomes and scientific fields cannot.
    """
    md = reference.metadata
    derivative = EngineResult.model_validate(md['reference_gradient_result'])

    def process_identity(result):
        return {'status': result.status, 'converged': result.converged,
                'engine': result.engine, 'method': result.method, 'operation': result.operation,
                'engine_version': result.engine_version, 'command_arguments': result.command[1:],
                'molecule': result.molecule.model_dump(mode='json') if result.molecule is not None else None,
                'energy_hartree': result.energy_hartree, 'gradient_hartree_per_bohr': result.gradient_hartree_per_bohr,
                'executable_sha256': result.metadata.get('executable_sha256'),
                'requested_method': result.metadata.get('requested_method'),
                'process_status': result.diagnostics.get('process', {}).get('status'),
                'process_returncode': result.diagnostics.get('process', {}).get('returncode'),
                'artifacts': [{'sha256': a.sha256, 'size_bytes': a.size_bytes, 'role': a.role} for a in result.artifacts]}

    return {'reference': process_identity(reference), 'derivative': process_identity(derivative),
            'protocol': md.get('protocol'), 'hessian_hartree_per_bohr2': md.get('hessian_hartree_per_bohr2'),
            'analysis': md.get('analysis'), 'native_masses_amu': md.get('native_masses_amu'),
            'native_coordinates_angstrom': md.get('native_coordinates_angstrom')}


def verify_vpt2_native_frame_reference(molecule: Molecule, geometry: dict[str, Any],
                                      hessian_path: str | Path, reference: EngineResult,
                                      method: dict[str, Any], executable_sha256: str) -> dict[str, Any]:
    """Require a separately executed stationary Hessian in the exact native pose.

    Finite XC/COSX grids need not produce rotationally covariant derivatives
    at the elementwise identity tolerance. Comparing independently calculated
    tensors in their actual common pose preserves that tolerance.
    Raw input/process/derivative checks remain the consumer's responsibility.
    """
    pose = vpt2_native_reference_pose(molecule, geometry, hessian_path)
    md = reference.metadata
    if (reference.status != 'completed' or reference.converged is not True
            or reference.operation != 'hessian' or reference.engine != 'orca'
            or reference.engine_version != ORCA_VERSION or reference.method != method['method']
            or reference.molecule is None or reference.molecule.model_dump(mode='json') != pose.model_dump(mode='json')
            or md.get('execution_kind') != 'real' or md.get('requested_method') != method
            or md.get('executable_sha256') != executable_sha256
            or reference.energy_hartree is None or reference.gradient_hartree_per_bohr is None
            or not reference.command or not reference.artifacts):
        raise EngineParseError('VPT2 requires independent actual Hessian evidence in its exact native equilibrium pose')
    from .science import harmonic_analysis

    parsed = parse_orca_hessian(hessian_path, pose)
    analysis = harmonic_analysis(pose, md['hessian_hartree_per_bohr2'],
                                gradient_hartree_per_bohr=reference.gradient_hartree_per_bohr,
                                gradient_threshold=1e-7)
    if analysis['validity'] != 'harmonic-minimum-within-thresholds' or min(analysis['frequencies_cm1']) < 50:
        raise EngineParseError('VPT2 native-pose reference is not a strict stationary semirigid minimum')
    if not np.allclose(parsed['hessian_hartree_per_bohr2'], md['hessian_hartree_per_bohr2'], atol=1e-7, rtol=1e-6):
        raise EngineParseError('VPT2 native reference Hessian differs from its independently executed same-pose stationary reference')
    return {'policy_id': VPT2_REFERENCE_POLICY_ID,
            'native_equilibrium_molecule_sha256': digest_json(pose.model_dump(mode='json')),
            'initial_native_hessian_sha256': file_digest(Path(hessian_path)),
            'reference_evidence_sha256': digest_json(vpt2_reference_evidence_identity(reference)),
            'comparison_frame': 'actual initial native Hessian $atoms Cartesian frame',
            'hessian_atol_hartree_per_bohr2': 1e-7, 'hessian_rtol': 1e-6}


def vpt2_execution_policy(resources: ResourceLimits) -> dict[str, Any]:
    """Declare the pinned VPT2 serial policy before any native execution.

    Two retained ORCA 6.1.1 MPI water runs stopped while producing the requested
    Pickett template: one printed a property-writer error, one stalled until
    its deadline. Serial execution is a compatibility choice awaiting native
    acceptance, not a change of method.
    Preserve the original per-worker MaxCore so the audited per-core memory
    allocation is never inflated when the native VPT2 worker count is reduced.
    The total hard RAM ceiling, wall-clock budget and all scientific settings
    remain the caller's. The preceding reference derivatives use the original
    requested allocation.
    """
    return {
        'schema': 'topos-orca-vpt2-execution-policy/0.1.0',
        'policy_id': 'orca-6.1.1-vpt2-serial-preserve-maxcore-v1',
        'requested_workers': resources.threads, 'effective_workers': 1,
        'native_maxcore_mb': max(16, int(resources.memory_mb * .75 / resources.threads)),
        'total_memory_ceiling_mb': resources.memory_mb,
        'reference_resources': 'requested allocation; unchanged',
        'scientific_settings': 'unchanged method, basis, dispersion, thresholds and displacements',
        'deadline_policy': 'original shared wall-clock budget; no automatic extension',
        'reason': 'ORCA 6.1.1 MPI runs errored or stalled before VPT2 displacements while writing Pickett output',
        'native_acceptance': 'serial policy requires its own completed native evidence',
        'manual': VPT2_MANUAL,
    }


def orca_vpt2_input(molecule: Molecule, method: MethodSpec, resources: ResourceLimits,
                    *, displacement: float = .05, check_cpu_affinity: bool = True) -> str:
    if not np.isfinite(displacement) or not 0 < displacement <= .2:
        raise ValueError('VPT2 dimensionless normal-coordinate displacement must be positive and at most 0.2')
    if method.profile_id != 'orca-vpt2-reference-v1':
        raise ValueError('VPT2 requires the explicit ExtremeSCF/strict stationary reference profile')
    if method.constraints or rotational_constants(molecule)['geometry_class'] != 'nonlinear':
        raise ValueError('native VPT2 requires an unconstrained nonlinear full-dimensional reference')
    if any(isotope is not None for isotope in molecule.isotopes):
        raise ValueError('native VPT2 isotope-specific force-field/reanalysis input is not validated')
    lines = orca_frequency_input(molecule, method, resources, check_cpu_affinity=check_cpu_affinity).splitlines()
    lines[0] = lines[0].removesuffix(' Freq') + ' VPT2'
    # Keep MaxCore from the caller's original per-worker allocation. BASE
    # authorizes this actual input allocation, independently of the total RAM
    # hard ceiling retained by the serial process launcher.
    pal = next(i for i, line in enumerate(lines) if line.startswith('%pal '))
    lines[pal] = '%pal nprocs 1 end'
    start = next(i for i, line in enumerate(lines) if line.startswith('* xyz'))
    lines[start:start] = ['%vpt2', '  VPT2 On', f'  AnharmDisp {displacement:.12g}',
                          '  HessianCutoff 1e-12', '  PrintLevel 4', '  MinimiseOrcaPrint False', 'end',
                          '%output', '  Pickettname "pickett.txt"', 'end']
    return '\n'.join(lines) + '\n'


def parse_orca_vpt2(text: str, *, vibrational_modes: int) -> dict[str, Any]:
    """Read native mode/alpha/Be/B0/ZPE tables, checking printed identities.

    Printed precision is retained. VPT2 anharmonic fundamentals must not be
    substituted into harmonic partition functions to claim anharmonic RRHO.
    """
    if isinstance(vibrational_modes, bool) or not isinstance(vibrational_modes, int) or vibrational_modes <= 0:
        raise ValueError('positive vibrational mode count required')
    if 'ORCA VPT2/GVPT2 Analysis' not in text:
        raise EngineParseError('native VPT2 analysis header missing')
    try:
        alpha_block = text.rsplit('Vibrational-rotational constants [1/cm]', 1)[1].split('Rotational constants B_e and B_0 [1/cm]', 1)[0]
        rotation_block = text.rsplit('Rotational constants B_e and B_0 [1/cm]', 1)[1].split('Vibrational Analysis', 1)[0]
        modes_block = text.rsplit('Fundamental transitions [1/cm]', 1)[1].split('Zero-point ro-vibrational energy [1/cm]', 1)[0]
        zpe_block = text.rsplit('Zero-point ro-vibrational energy [1/cm]', 1)[1]
    except IndexError as exc:
        raise EngineParseError('native VPT2 required spectroscopy tables missing') from exc
    alpha = np.full((3, vibrational_modes), np.nan)
    pattern = r'(?m)^\s*([xyz])\s+(\d+)\s+(' + _FLOAT + r')\s+(' + _FLOAT + r')\s+(' + _FLOAT + r')\s+(' + _FLOAT + r')\s*$'
    for axis, index, one, two, three, total in re.findall(pattern, alpha_block):
        a, i = 'xyz'.index(axis), int(index)
        if i >= vibrational_modes or np.isfinite(alpha[a, i]):
            raise EngineParseError('duplicate or invalid VPT2 vibrational-rotational mode')
        parts = [_number(v) for v in (one, two, three, total)]
        if abs(sum(parts[:3]) - parts[3]) > 2.1e-5:
            raise EngineParseError('VPT2 alpha components violate their printed sum')
        alpha[a, i] = parts[3]
    if not np.isfinite(alpha).all():
        raise EngineParseError('VPT2 alpha tensor incomplete')
    rotation = {}
    for label in ('B_e', 'B_0', 'B_e-B_0'):
        matches = re.findall(r'(?m)^\s*' + re.escape(label) + r'\s+(' + _FLOAT + r')\s+(' + _FLOAT + r')\s+(' + _FLOAT + r')\s*$', rotation_block)
        if len(matches) != 1:
            raise EngineParseError('native rotational constant row missing/ambiguous')
        rotation[label] = np.asarray([_number(v) for v in matches[0]])
    if (min(rotation['B_e']) <= 0 or min(rotation['B_0']) <= 0
            or not np.allclose(rotation['B_e'] - rotation['B_0'], rotation['B_e-B_0'], atol=1.51e-5, rtol=0)
            or not np.allclose(alpha.sum(axis=1) / 2, rotation['B_e-B_0'], atol=vibrational_modes * 2.5e-6 + 1.01e-5, rtol=0)):
        raise EngineParseError('VPT2 Be/B0/alpha zero-point correction inconsistent')
    modes = {}
    pattern = r'(?m)^\s*(\d+)\s+(' + _FLOAT + r')\s+(' + _FLOAT + r')\s+(' + _FLOAT + r')\s*$'
    for index, harmonic, fundamental, difference in re.findall(pattern, modes_block):
        i = int(index)
        values = [_number(v) for v in (harmonic, fundamental, difference)]
        if i in modes or i >= vibrational_modes or min(values[:2]) <= 0 or abs(values[1] - values[0] - values[2]) > .00151:
            raise EngineParseError('VPT2 fundamental mode invalid or inconsistent')
        modes[i] = {'mode_index': i, 'harmonic_cm1': values[0], 'fundamental_cm1': values[1], 'correction_cm1': values[2]}
    if sorted(modes) != list(range(vibrational_modes)):
        raise EngineParseError('VPT2 fundamental table incomplete')
    zpe = {}
    for key, label in {'harmonic_cm1': 'Harmonic contribution', 'anharmonic_correction_cm1': 'Anharmonic correction',
                       'rovibrational_correction_cm1': 'Ro-vibrational correction', 'total_cm1': 'Total'}.items():
        match = re.search(r'(?m)^\s*' + re.escape(label) + r':\s*(' + _FLOAT + r')\s*$', zpe_block)
        if match is None:
            raise EngineParseError('VPT2 zero-point component missing')
        zpe[key] = _number(match[1])
    if abs(zpe['harmonic_cm1'] + zpe['anharmonic_correction_cm1'] + zpe['rovibrational_correction_cm1'] - zpe['total_cm1']) > .00201:
        raise EngineParseError('VPT2 zero-point components inconsistent')
    if abs(sum(m['harmonic_cm1'] for m in modes.values()) / 2 - zpe['harmonic_cm1']) > .00025 * vibrational_modes + .00051:
        raise EngineParseError('VPT2 harmonic zero-point term differs from its modes')
    return {'vibrational_modes': vibrational_modes, 'fundamental_transitions': [modes[i] for i in sorted(modes)],
            'alpha_cm1': alpha.tolist(), 'axis_order': 'native principal x/y/z axes',
            'rotational_constants_cm1': {k: v.tolist() for k, v in rotation.items()},
            'rotational_constants_mhz': {k: (v * constants.c / 1e4).tolist() for k, v in rotation.items()},
            'zero_point_energy': zpe, 'zero_point_total_hartree': zpe['total_cm1'] * constants.h * constants.c * 100 / HARTREE_J,
            'observable': 'native VPT2 ground-state rotational constants and anharmonic fundamentals',
            'thermal_partition_function': 'not computed; fundamentals are not harmonic oscillator spacings',
            'precision': 'native printed precision; no empirical accuracy guarantee',
            'manual': VPT2_MANUAL, 'parser_format_source': PARSER_SOURCE}


def parse_orca_vpt2_geometry(text: str, *, natoms: int) -> dict[str, Any]:
    """Read the equilibrium geometry in the VPT2 principal-axis frame.

    ORCA explicitly rotates the input before building its force field. This
    final Geometry table carries the updated VPT2 atomic masses, whereas a
    preceding ordinary Freq calculation may use different default masses.
    The run adapter separately proves rigid equivalence to its input.
    """
    if 'ORCA VPT2/GVPT2 Analysis' not in text:
        raise EngineParseError('native VPT2 analysis missing')
    analysis = text.rsplit('ORCA VPT2/GVPT2 Analysis', 1)[1]
    match = re.search(r'Coordinates in Angstroem\s*\n-+\s*\nAtom\s+x\s+y\s+z\s+Mass \[u\]\s*\n-+\s*\n(.*?)\n-+', analysis, re.S)
    if match is None:
        raise EngineParseError('native VPT2 equilibrium geometry/mass table missing')
    rows = [line.split() for line in match[1].splitlines() if line.strip()]
    if len(rows) != natoms or any(len(row) != 5 or not re.fullmatch('[A-Z][a-z]?', row[0]) for row in rows):
        raise EngineParseError('native VPT2 geometry atom count or row invalid')
    masses = [_number(row[4]) for row in rows]
    if min(masses) <= 0:
        raise EngineParseError('native VPT2 masses must be positive')
    return {'symbols': [row[0] for row in rows],
            'coordinates_angstrom': [[_number(v) for v in row[1:4]] for row in rows],
            'masses_amu': masses, 'coordinate_frame': 'native VPT2 principal axes',
            'geometry_role': 'equilibrium input after rigid principal-axis transformation',
            'mass_source': 'native VPT2 Geometry table Mass [u]',
            'mass_precision_amu': 1e-6, 'coordinate_precision_angstrom': 1e-9}


def _verify_completed_vpt2(result: EngineResult, molecule: Molecule, method: MethodSpec,
                            resources: ResourceLimits, folder: Path, protocol: dict[str, Any],
                            preflight: EngineResult) -> None:
    """Reparse complete native spectroscopy and both independently raw-verified references."""
    md = result.metadata
    binary = preflight.metadata['executable']
    binary_hash = preflight.metadata['executable_sha256']
    if (result.status != 'completed' or result.converged is not True or result.engine != 'orca'
            or result.engine_version != ORCA_VERSION or result.method != method.method or result.operation != 'anharmonic'
            or result.molecule != molecule or md.get('requested_method') != method.model_dump(mode='json')
            or md.get('output_molecule') != molecule.model_dump(mode='json') or md.get('execution_kind') != 'real'
            or md.get('executable') != binary or md.get('executable_sha256') != binary_hash
            or md.get('protocol') != protocol or md.get('reference_validation_policy') != vpt2_reference_policy()
            or md.get('execution_policy') != vpt2_execution_policy(resources) or md.get('semirigid_declared') is not True):
        raise IntegrityError('completed VPT2 differs from its current requested identity and execution/reference protocol')
    native, raw = _raw_process(result, folder, binary, 'anharmonic.inp', 'anharmonic')
    if _raw_artifact(result, native / 'anharmonic.inp', folder).read_text() != orca_vpt2_input(
            molecule, method, resources, displacement=protocol['displacement'], check_cpu_affinity=False):
        raise IntegrityError('completed VPT2 input differs from its exact requested compiled deck')
    requested = ResourceLimits.model_validate(md['requested_resources'])
    effective = ResourceLimits.model_validate(md['native_execution_resources'])
    if (requested.model_dump(exclude={'budget_seconds'}) != resources.model_dump(exclude={'budget_seconds'})
            or effective.model_dump(exclude={'budget_seconds'}) != resources.model_copy(update={'threads': 1}).model_dump(exclude={'budget_seconds'})
            or effective.budget_seconds > requested.budget_seconds):
        raise IntegrityError('completed VPT2 resource observations differ from its declared serial allocation')
    original = EngineResult.model_validate(md['reference_hessian_result'])
    parent_artifacts = {a.path: (a.sha256, a.size_bytes, a.role) for a in result.artifacts}
    if any(parent_artifacts.get(a.path) != (a.sha256, a.size_bytes, a.role) for a in original.artifacts):
        raise IntegrityError('completed VPT2 does not retain its exact independent original reference artifacts')
    verify_orca_hessian_result(original, molecule, method, resources, folder / 'reference',
                               executable=binary, executable_sha256=binary_hash, gradient_threshold=1e-7)
    if (vpt2_reference_evidence_identity(original) != vpt2_reference_evidence_identity(preflight)
            or result.energy_hartree is None or abs(result.energy_hartree - preflight.energy_hartree) > 1e-10
            or result.gradient_hartree_per_bohr is None
            or not np.allclose(result.gradient_hartree_per_bohr, preflight.gradient_hartree_per_bohr, atol=1e-12, rtol=0)):
        raise IntegrityError('completed VPT2 original preflight differs from independently reverified raw derivatives')
    geometry = parse_orca_vpt2_geometry(raw, natoms=len(molecule.symbols))
    if (md.get('vpt2') != parse_orca_vpt2(raw, vibrational_modes=3 * len(molecule.symbols) - 6)
            or md.get('vpt2_geometry') != geometry or md.get('native_masses_amu') != geometry['masses_amu']):
        raise IntegrityError('completed VPT2 spectroscopy/geometry/masses differ from immutable native stdout')
    hessian_path = _raw_artifact(result, native / 'anharmonic.hess', folder)
    native_pose = vpt2_native_reference_pose(molecule, geometry, hessian_path)
    parsed = parse_orca_hessian(hessian_path, native_pose)
    from .rotational_transfer import proper_alignment

    alignment = proper_alignment(geometry['coordinates_angstrom'], molecule.coordinates, geometry['masses_amu'])
    if (md.get('hessian_masses_amu') != parsed['native_masses_amu']
            or not _analysis_matches(md.get('vpt2_reference_alignment'), alignment)
            or md.get('native_frame_reference_molecule') != native_pose.model_dump(mode='json')):
        raise IntegrityError('completed VPT2 native Hessian frame/mass observations changed')
    for field, name in (('native_force_field', 'anharmonic.vpt2'), ('native_pickett_template', 'pickett.txt')):
        path = native / name
        if md.get(field) != str(path) or _raw_artifact(result, path, folder).stat().st_size == 0:
            raise IntegrityError('completed VPT2 force-field/Pickett locator differs from its actual inventoried native output')
    frame_reference = EngineResult.model_validate(md['native_frame_reference_hessian_result'])
    if any(parent_artifacts.get(a.path) != (a.sha256, a.size_bytes, a.role) for a in frame_reference.artifacts):
        raise IntegrityError('completed VPT2 does not retain its exact independent native-pose reference artifacts')
    frame_folder = folder / 'native-frame-reference' / digest_json(native_pose.model_dump(mode='json'))
    verify_orca_hessian_result(frame_reference, native_pose, method, resources, frame_folder,
                               executable=binary, executable_sha256=binary_hash, gradient_threshold=1e-7)
    receipt = _raw_artifact(result, folder / 'native-frame-reference-result.json', folder)
    if EngineResult.model_validate(json.loads(receipt.read_text())['result']).model_dump(mode='json') != frame_reference.model_dump(mode='json'):
        raise IntegrityError('completed VPT2 actual-pose reference differs from its immutable result receipt')
    frame_protocol = _raw_artifact(result, frame_folder / 'protocol.json', folder)
    if json.loads(frame_protocol.read_text()) != frame_reference.metadata['protocol']:
        raise IntegrityError('completed VPT2 actual-pose reference differs from its immutable protocol')
    association = verify_vpt2_native_frame_reference(molecule, geometry, hessian_path, frame_reference,
                                                     method.model_dump(mode='json'), binary_hash)
    if association != md.get('native_frame_reference_association'):
        raise IntegrityError('completed VPT2 native-pose reference association changed')


def verify_completed_vpt2(result: EngineResult, molecule: Molecule, method: MethodSpec,
                           resources: ResourceLimits, folder: Path, protocol: dict[str, Any],
                           preflight: EngineResult) -> None:
    """Reject incomplete as well as inconsistent completed spectroscopy evidence."""
    try:
        _verify_completed_vpt2(result, molecule, method, resources, folder, protocol, preflight)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        if isinstance(exc, IntegrityError):
            raise
        raise IntegrityError(f'incomplete completed VPT2 cache evidence: {exc}') from exc


def run_orca_vpt2(molecule: Molecule, method: MethodSpec, resources: ResourceLimits,
                  workdir: str | Path, *, executable: str | Path | None = None,
                  process_runner: Callable[..., Any] | None = None, cancel_event: Event | None = None,
                  displacement: float = .05, semirigid_modes: bool = False) -> EngineResult:
    """Execute physical reference Hessian then native anharmonic force field.

    The caller explicitly declares the semirigid approximation applicable. Soft
    (<50 cm-1), imaginary, linear, constrained and nonstationary cases are rejected
    rather than silently interpreting hindered internal rotors as harmonic modes.
    Completed verified stages survive recovery; incomplete native VPT2 is restarted
    in fresh scratch with all preceding raw artifacts preserved for inspection.
    """
    started = time.monotonic()
    result = EngineResult(status='unsupported', engine='orca', method=method.method, operation='anharmonic',
                          metadata={'execution_kind': 'not-executed', 'manual': VPT2_MANUAL,
                                    'requested_method': method.model_dump(mode='json'),
                                    'derivative_kind': 'native-VPT2-analytic-Hessian-differences',
                                    'partial_restart_policy': 'completed stages reused; incomplete VPT2 starts fresh',
                                    'semirigid_declared': semirigid_modes, 'low_mode_threshold_cm1': 50.0,
                                    'requested_resources': resources.model_dump(mode='json'),
                                    'execution_policy': vpt2_execution_policy(resources),
                                    'reference_validation_policy': vpt2_reference_policy()})
    def stopped() -> bool:
        return _derivative_stopped(result, resources, started, cancel_event, 'VPT2')

    if stopped():
        return result
    try:
        deck = orca_vpt2_input(molecule, method, resources, displacement=displacement)
        if semirigid_modes is not True:
            raise ValueError('explicit semirigid_modes=True applicability declaration required')
    except ValueError as exc:
        result.diagnostics['reason'] = str(exc)
        return result
    folder = Path(workdir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    effective_resources = resources.model_copy(update={'threads': 1})
    protocol = {'schema': 'topos-native-orca-vpt2/0.1.0',
                'molecule': molecule.model_dump(mode='json'), 'method': method.model_dump(mode='json'),
                'resources': resources.model_dump(exclude={'budget_seconds'}), 'displacement': displacement,
                'effective_resources': effective_resources.model_dump(exclude={'budget_seconds'}),
                'execution_policy': vpt2_execution_policy(resources),
                'reference_validation_policy': vpt2_reference_policy(),
                'semirigid_modes': semirigid_modes, 'deck_sha256': digest_json(deck)}
    manifest = folder / 'vpt2-protocol.json'
    if manifest.exists():
        if json.loads(manifest.read_text()) != protocol:
            raise IntegrityError('VPT2 recovery protocol changed')
    elif any(folder.iterdir()):
        raise IntegrityError('VPT2 directory contains unverified previous output')
    else:
        atomic_json(manifest, protocol)
    execute = process_runner or run_process

    def remaining():
        if stopped():
            if result.status == 'cancelled':
                raise InterruptedError(result.diagnostics['reason'])
            raise TimeoutError(result.diagnostics['reason'])
        seconds = resources.budget_seconds - (time.monotonic() - started)
        if seconds <= 0:
            raise TimeoutError('VPT2 budget exhausted')
        return resources.model_copy(update={'budget_seconds': seconds})

    try:
        # Always pass through the reference's binary/protocol gate, even when
        # the final VPT2 receipt already exists.
        reference = run_orca_hessian(molecule, method, remaining(), folder / 'reference', executable=executable,
                                     process_runner=process_runner, cancel_event=cancel_event, gradient_threshold=1e-7)
        result.metadata['reference_hessian_result'] = reference.model_dump(mode='json')
        result.artifacts = reference.artifacts.copy()
        result.artifacts.append(Artifact(path=str(manifest), sha256=file_digest(manifest),
                                         size_bytes=manifest.stat().st_size, role='recovery-protocol'))
        if reference.status != 'completed':
            result.status = reference.status
            result.diagnostics['reason'] = 'VPT2 reference Hessian did not complete'
            return result
        analysis = reference.metadata['analysis']
        if analysis['validity'] != 'harmonic-minimum-within-thresholds' or min(analysis['frequencies_cm1']) < 50:
            result.diagnostics['reason'] = 'VPT2 requires a tightly stationary full-dimensional semirigid minimum with modes >=50 cm-1'
            return result
        remaining()
        cached = _read_completed(folder / 'completed.json', folder)
        remaining()
        if cached is not None:
            verify_completed_vpt2(cached, molecule, method, resources, folder, protocol, reference)
            remaining()
            cached.metadata['reused_completed_vpt2'] = True
            return cached
        result.energy_hartree = reference.energy_hartree
        result.gradient_hartree_per_bohr = reference.gradient_hartree_per_bohr
        result.molecule, result.engine_version = molecule, reference.engine_version
        native = folder / ('vpt2-' + uuid4().hex)
        native.mkdir()
        (native / 'anharmonic.inp').write_text(deck)
        binary = reference.metadata['executable']
        result.command = [binary, 'anharmonic.inp']
        result.metadata.update(execution_kind='real', executable=binary,
                               executable_sha256=reference.metadata['executable_sha256'],
                               output_molecule=molecule.model_dump(mode='json'), protocol=protocol)
        native_resources = remaining().model_copy(update={'threads': 1})
        result.metadata['native_execution_resources'] = native_resources.model_dump(mode='json')
        process = execute(result.command, native, native_resources, cancel_event=cancel_event,
                          log_prefix='anharmonic', threads_per_process=1)
        result.status = process.status
        result.diagnostics['process'] = process.to_dict()
        result.artifacts.extend(artifact_inventory(native))
        if process.status != 'completed':
            result.diagnostics['reason'] = process.reason
            return result
        raw = Path(process.stdout_path).read_text(errors='replace')
        if _engine_version(raw, 'orca') != ORCA_VERSION or 'ORCA TERMINATED NORMALLY' not in raw:
            raise EngineParseError('native VPT2 completion or pinned version unverified')
        force_field = native / 'anharmonic.vpt2'
        if not force_field.is_file() or force_field.stat().st_size == 0:
            raise EngineParseError('native VPT2 force-field artifact missing')
        from .rotational_transfer import proper_alignment

        geometry = parse_orca_vpt2_geometry(raw, natoms=len(molecule.symbols))
        native_pose = vpt2_native_reference_pose(molecule, geometry, native / 'anharmonic.hess')
        alignment = proper_alignment(geometry['coordinates_angstrom'], molecule.coordinates, geometry['masses_amu'])
        parsed_hessian = parse_orca_hessian(native / 'anharmonic.hess', native_pose)
        # ORCA rotates before constructing its finite XC/COSX grids. A rigidly
        # equivalent original-pose derivative is a useful preflight, but does
        # not certify stationarity or tensor identity in this numerical pose.
        frame_folder = folder / 'native-frame-reference' / digest_json(native_pose.model_dump(mode='json'))
        frame_reference = run_orca_hessian(native_pose, method, remaining(), frame_folder,
                                           executable=binary, process_runner=process_runner,
                                           cancel_event=cancel_event, gradient_threshold=1e-7)
        result.metadata['native_frame_reference_hessian_result'] = frame_reference.model_dump(mode='json')
        result.artifacts.extend(frame_reference.artifacts)
        frame_receipt = folder / 'native-frame-reference-result.json'
        atomic_json(frame_receipt, {'result': frame_reference.model_dump(mode='json')})
        for path, role in ((frame_receipt, 'vpt2-native-frame-reference-result'),
                           (frame_folder / 'protocol.json', 'vpt2-native-frame-reference-protocol')):
            if path.is_file():
                result.artifacts.append(Artifact(path=str(path), sha256=file_digest(path),
                                                 size_bytes=path.stat().st_size, role=role))
        if frame_reference.status != 'completed':
            result.status = frame_reference.status
            result.diagnostics['reason'] = 'VPT2 independently executed native-pose reference Hessian did not complete'
            return result
        association = verify_vpt2_native_frame_reference(molecule, geometry, native / 'anharmonic.hess',
                                                         frame_reference, method.model_dump(mode='json'),
                                                         result.metadata['executable_sha256'])
        result.metadata['native_frame_reference_association'] = association
        result.metadata['native_frame_reference_molecule'] = native_pose.model_dump(mode='json')
        result.metadata['reference_energy_role'] = 'original requested-pose stationary preflight; actual native-pose derivatives retained separately'
        result.metadata['vpt2'] = parse_orca_vpt2(raw, vibrational_modes=3 * len(molecule.symbols) - 6)
        result.metadata['vpt2_geometry'] = geometry
        result.metadata['vpt2_reference_alignment'] = alignment
        result.metadata['hessian_masses_amu'] = parsed_hessian['native_masses_amu']
        result.metadata['native_masses_amu'] = geometry['masses_amu']
        result.metadata['native_force_field'] = str(force_field)
        pickett = native / 'pickett.txt'
        if not pickett.is_file() or pickett.stat().st_size == 0:
            raise EngineParseError('Requested native Pickett spectroscopy template missing')
        result.metadata['native_pickett_template'] = str(pickett)
        result.converged = True
        remaining()
        result.elapsed_seconds = time.monotonic() - started
        atomic_json(folder / 'completed.json', {'result': result.model_dump(mode='json')})
        remaining()
        return result
    except InterruptedError as exc:
        result.status, result.diagnostics['reason'] = 'cancelled', str(exc)
        result.converged = False
        return result
    except TimeoutError as exc:
        result.status, result.diagnostics['reason'] = 'timed-out', str(exc)
        result.converged = False
        return result
    except (ValueError, OSError) as exc:
        result.status, result.diagnostics['reason'] = 'failed', str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - started
