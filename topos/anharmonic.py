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
from .models import MethodSpec, Molecule, ResourceLimits
from .native_hessian import (
    _read_completed,
    orca_frequency_input,
    parse_orca_hessian,
    run_orca_hessian,
)
from .runtime import run_process
from .science import HARTREE_J, rotational_constants
from .storage import IntegrityError, atomic_json, digest_json

VPT2_MANUAL = 'https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/vpt2.html'
PARSER_SOURCE = 'https://github.com/physicien/parser_vpt2/blob/main/data/VPT2_furan_vpt2.out'
_FLOAT = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?'


def orca_vpt2_input(molecule: Molecule, method: MethodSpec, resources: ResourceLimits,
                    *, displacement: float = .05) -> str:
    if not np.isfinite(displacement) or not 0 < displacement <= .2:
        raise ValueError('VPT2 dimensionless normal-coordinate displacement must be positive and at most 0.2')
    if method.profile_id != 'orca-vpt2-reference-v1':
        raise ValueError('VPT2 requires the explicit ExtremeSCF/strict stationary reference profile')
    if method.constraints or rotational_constants(molecule)['geometry_class'] != 'nonlinear':
        raise ValueError('native VPT2 requires an unconstrained nonlinear full-dimensional reference')
    if any(isotope is not None for isotope in molecule.isotopes):
        raise ValueError('native VPT2 isotope-specific force-field/reanalysis input is not validated')
    lines = orca_frequency_input(molecule, method, resources).splitlines()
    lines[0] = lines[0].removesuffix(' Freq') + ' VPT2'
    start = next(i for i, line in enumerate(lines) if line.startswith('* xyz'))
    lines[start:start] = ['%vpt2', '  VPT2 On', f'  AnharmDisp {displacement:.12g}',
                          '  HessianCutoff 1e-12', '  PrintLevel 4', '  MinimiseOrcaPrint False', 'end']
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
                                    'semirigid_declared': semirigid_modes, 'low_mode_threshold_cm1': 50.0})
    try:
        deck = orca_vpt2_input(molecule, method, resources, displacement=displacement)
        if semirigid_modes is not True:
            raise ValueError('explicit semirigid_modes=True applicability declaration required')
    except ValueError as exc:
        result.diagnostics['reason'] = str(exc)
        return result
    folder = Path(workdir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    protocol = {'molecule': molecule.model_dump(mode='json'), 'method': method.model_dump(mode='json'),
                'resources': resources.model_dump(exclude={'budget_seconds'}), 'displacement': displacement,
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
        if reference.status != 'completed':
            result.status = reference.status
            result.diagnostics['reason'] = 'VPT2 reference Hessian did not complete'
            return result
        analysis = reference.metadata['analysis']
        if analysis['validity'] != 'harmonic-minimum-within-thresholds' or min(analysis['frequencies_cm1']) < 50:
            result.diagnostics['reason'] = 'VPT2 requires a tightly stationary full-dimensional semirigid minimum with modes >=50 cm-1'
            return result
        cached = _read_completed(folder / 'completed.json', folder)
        if cached is not None:
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
        process = execute(result.command, native, remaining(), cancel_event=cancel_event,
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
        parsed_hessian = parse_orca_hessian(native / 'anharmonic.hess', molecule)
        if not np.allclose(parsed_hessian['hessian_hartree_per_bohr2'], reference.metadata['hessian_hartree_per_bohr2'], atol=1e-7, rtol=1e-6):
            raise EngineParseError('VPT2 native reference Hessian differs from its same-level stationary reference')
        result.metadata['vpt2'] = parse_orca_vpt2(raw, vibrational_modes=3 * len(molecule.symbols) - 6)
        result.metadata['native_masses_amu'] = parsed_hessian['native_masses_amu']
        result.metadata['native_force_field'] = str(force_field)
        result.converged = True
        result.elapsed_seconds = time.monotonic() - started
        atomic_json(folder / 'completed.json', {'result': result.model_dump(mode='json')})
        return result
    except TimeoutError as exc:
        result.status, result.diagnostics['reason'] = 'timed-out', str(exc)
        return result
    except (ValueError, OSError) as exc:
        result.status, result.diagnostics['reason'] = 'failed', str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - started
