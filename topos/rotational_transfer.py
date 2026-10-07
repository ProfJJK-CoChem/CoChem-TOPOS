"""Explicit approximate transfer of native rovibrational rotor corrections.

The algebra and geometric safeguards do not establish that an electronic
structure backend supports the requested anharmonic calculation.
"""
from __future__ import annotations

from itertools import permutations
from typing import Any, Literal

import numpy as np
from pydantic import Field
from scipy import constants

from .engines import EngineResult
from .models import Contract, Molecule


class RotationalTransferOptions(Contract):
    semirigid_same_basin: Literal[True]
    max_aligned_rmsd_angstrom: float = Field(default=.15, gt=0, le=.5, strict=True)
    max_pair_distance_change_angstrom: float = Field(default=.3, gt=0, le=1, strict=True)
    min_relative_moment_gap: float = Field(default=.01, ge=.001, le=.5, strict=True)
    min_axis_overlap: float = Field(default=.95, ge=.9, le=1, strict=True)
    min_axis_assignment_margin: float = Field(default=.1, ge=.01, le=1, strict=True)
    max_correction_fraction: float = Field(default=.1, gt=0, le=.2, strict=True)


def proper_alignment(source: Any, target: Any, masses: Any) -> dict[str, Any]:
    """Mass-weighted atom-preserving row-vector alignment, never reflection."""
    a, b, weights = np.asarray(source, float), np.asarray(target, float), np.asarray(masses, float)
    if (a.ndim != 2 or a.shape[1] != 3 or b.shape != a.shape or weights.shape != (len(a),)
            or not np.isfinite(a).all() or not np.isfinite(b).all()
            or not np.isfinite(weights).all() or min(weights) <= 0):
        raise ValueError('finite matching Cartesian geometries and positive masses required')
    ca, cb = np.average(a, axis=0, weights=weights), np.average(b, axis=0, weights=weights)
    ac, bc = a-ca, b-cb
    u, singular, vt = np.linalg.svd((ac * weights[:, None]).T @ bc)
    handedness = np.linalg.det(u @ vt)
    rotation = u @ np.diag([1., 1., 1. if handedness >= 0 else -1.]) @ vt
    displacement = ac @ rotation - bc
    return {'rotation_source_to_target': rotation.tolist(), 'source_center': ca.tolist(),
            'target_center': cb.tolist(), 'determinant': float(np.linalg.det(rotation)),
            'rmsd_angstrom': float(np.sqrt(np.mean(np.sum(displacement**2, axis=1)))),
            'max_atom_displacement_angstrom': float(np.max(np.linalg.norm(displacement, axis=1))),
            'singular_values': singular.tolist()}


def rotate_cartesian_hessian(hessian: Any, rotation_source_to_target: Any) -> np.ndarray:
    """Transform d²E/dx² under row coordinates x_target = x_source @ R."""
    h, r = np.asarray(hessian, float), np.asarray(rotation_source_to_target, float)
    if (h.ndim != 2 or h.shape[0] != h.shape[1] or h.shape[0] % 3 or r.shape != (3, 3)
            or not np.isfinite(h).all() or not np.isfinite(r).all()
            or not np.allclose(r.T @ r, np.eye(3), atol=1e-10, rtol=0) or np.linalg.det(r) < .999999):
        raise ValueError('physical Hessian dimensions and proper orthogonal rotation required')
    transform = np.kron(np.eye(len(h)//3), r.T)
    return transform @ h @ transform.T


def _inertia(coordinates: Any, masses: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xyz = np.asarray(coordinates, float)
    xyz = xyz - np.average(xyz, axis=0, weights=masses)
    tensor = sum(m * (np.dot(r, r) * np.eye(3) - np.outer(r, r))
                 for m, r in zip(masses, xyz, strict=True))
    moments, axes = np.linalg.eigh(tensor)
    if min(moments) <= 1e-10 * max(moments):
        raise ValueError('rotational transfer requires nonlinear molecules')
    values = constants.h / (8*np.pi**2 * moments * constants.atomic_mass * constants.angstrom**2) / 1e9
    return moments, axes, values


def _identity(molecule: Molecule) -> dict[str, Any]:
    identity = molecule.model_dump(mode='json', exclude={'name', 'coordinates'})
    identity['bonds'] = sorted((min(b.atom1, b.atom2), max(b.atom1, b.atom2), b.order, b.kind)
                               for b in molecule.bonds)
    return identity


def calculate_rotational_transfer(target: Molecule, reference: Molecule, native_geometry: dict[str, Any],
                                  native_be_cm1: Any, native_b0_cm1: Any,
                                  options: RotationalTransferOptions) -> dict[str, Any]:
    """Pure physics/geometry calculation; no assertion of native execution.

    Native masses and principal-frame geometry are mandatory. Both geometries
    use those same printed masses. The caller must separately prove that the
    supplied values came from a stationary native anharmonic calculation.
    """
    from .chemistry import molecular_graph, resolved_masses
    from .science import validate_stereochemical_preservation

    target = Molecule.model_validate(target.model_dump(mode='json'))
    reference = Molecule.model_validate(reference.model_dump(mode='json'))
    options = RotationalTransferOptions.model_validate(options.model_dump(mode='json'))
    if _identity(target) != _identity(reference):
        raise ValueError('target and DFT reference atom/state/isotope/fragment/bond identities differ')
    if any(i is not None for i in reference.isotopes):
        raise ValueError('explicit isotope native VPT2 input is not validated')
    masses = np.asarray(native_geometry['masses_amu'], float)
    native_xyz = np.asarray(native_geometry['coordinates_angstrom'], float)
    if (native_geometry['symbols'] != reference.symbols or masses.shape != (len(reference.symbols),)
            or native_xyz.shape != (len(reference.symbols), 3) or not np.isfinite(masses).all()
            or min(masses) <= 0):
        raise ValueError('native VPT2 geometry/mass atom order invalid')
    expected, isotopes = resolved_masses(reference)
    # ORCA's updated mass table is independent of TOPOS's isotope data. This
    # checks isotope identity, not equality of mass conventions or constants.
    if not np.allclose(masses, expected, atol=2e-5, rtol=0):
        raise ValueError('native VPT2 masses do not identify the expected isotopologue')
    native_alignment = proper_alignment(native_xyz, reference.coordinates, masses)
    if native_alignment['max_atom_displacement_angstrom'] > 2e-7:
        raise ValueError('native VPT2 geometry is not the same equilibrium reference under a proper rotation')
    for candidate in (reference, target):
        inferred = molecular_graph(candidate.model_copy(update={'bonds': []}))
        # Identical explicit labels alone cannot excuse geometry dissociation.
        if candidate is reference:
            reference_edges = set(inferred.edges())
        elif set(inferred.edges()) != reference_edges:
            raise ValueError('target and reference distance-inferred connectivity differs')
    stereo = validate_stereochemical_preservation(reference, target)
    if stereo['status'] != 'preserved':
        raise ValueError('target/reference stereochemical geometry is inverted or ambiguous')
    alignment = proper_alignment(reference.coordinates, target.coordinates, masses)
    ra, ta = np.asarray(reference.coordinates), np.asarray(target.coordinates)
    pair_change = float(np.max(np.abs(np.linalg.norm(ra[:, None]-ra[None, :], axis=2)
                                      - np.linalg.norm(ta[:, None]-ta[None, :], axis=2))))
    if alignment['rmsd_angstrom'] > options.max_aligned_rmsd_angstrom or pair_change > options.max_pair_distance_change_angstrom:
        raise ValueError('target/reference geometric change exceeds declared same-basin transfer limits')
    rm, rv, rbe = _inertia(reference.coordinates, masses)
    tm, tv, tbe = _inertia(target.coordinates, masses)
    gaps = [float(np.min(np.diff(moments) / np.maximum(moments[:-1], moments[1:]))) for moments in (rm, tm)]
    if min(gaps) < options.min_relative_moment_gap:
        raise ValueError('near-degenerate principal moments make rotational correction transfer ambiguous')
    # Native x/y/z ordering need not equal sorted A/B/C. Determine its unique
    # association from Be, independently of eigenvector signs.
    be, b0 = np.asarray(native_be_cm1, float), np.asarray(native_b0_cm1, float)
    if be.shape != (3,) or b0.shape != (3,) or not np.isfinite(be).all() or not np.isfinite(b0).all() or min(be) <= 0 or min(b0) <= 0:
        raise ValueError('finite positive native Be/B0 triplets required')
    conversion = constants.c / 1e7  # cm^-1 -> GHz
    # Native Be is printed to 5 decimals; printed masses (6) and coordinates
    # (9) impose an additional small reconstruction error.
    tolerance = 5.1e-6 + float(max(be)) * 1.1e-6
    native_permutations = [p for p in permutations(range(3))
                           if np.allclose(be[list(p)], rbe/conversion, atol=tolerance, rtol=0)]
    if len(native_permutations) != 1:
        raise ValueError('native Be does not uniquely match reference inertia and native masses')
    native_order = native_permutations[0]
    rotation = np.asarray(alignment['rotation_source_to_target'])
    aligned_reference_axes = rotation.T @ rv
    overlaps = np.abs(tv.T @ aligned_reference_axes)
    scores = sorted(((float(sum(overlaps[i, p[i]] for i in range(3))), p)
                     for p in permutations(range(3))), reverse=True)
    margin = scores[0][0]-scores[1][0]
    mapping = scores[0][1]  # each sorted target axis -> sorted reference axis
    matched_overlaps = [float(overlaps[i, mapping[i]]) for i in range(3)]
    if min(matched_overlaps) < options.min_axis_overlap or margin < options.min_axis_assignment_margin:
        raise ValueError('principal-axis correspondence is incompatible or ambiguous')
    correction_native = (b0-be)*conversion
    correction = np.asarray([correction_native[native_order[mapping[i]]] for i in range(3)])
    fractions = np.abs(correction)/tbe
    if max(fractions) > options.max_correction_fraction or min(tbe+correction) <= 0:
        raise ValueError('native rotational correction exceeds declared perturbative-transfer limit')
    approximate = tbe+correction
    if not np.all(np.diff(approximate) < 0):
        raise ValueError('transferred correction crosses principal-constant ordering')
    return {'schema': 'topos-transferred-rotational-correction/0.1.0',
            'formula': 'B0_approx = B_R2 + (B0_DFT - Be_DFT)', 'units': 'GHz',
            'observable': 'approximate-ground-state-rotational-constants',
            'constants_ghz': approximate.tolist(), 'target_equilibrium_constants_ghz': tbe.tolist(),
            'reference_equilibrium_constants_ghz': rbe.tolist(),
            'transferred_correction_ghz': correction.tolist(),
            'native_be_cm1': be.tolist(), 'native_b0_cm1': b0.tolist(),
            'target_molecule': target.model_dump(mode='json'), 'reference_molecule': reference.model_dump(mode='json'),
            'atom_mapping': [{'atom_id': a, 'target_index': i, 'reference_index': i} for i, a in enumerate(target.atom_ids)],
            'mass_provenance': {'masses_amu': masses.tolist(), 'source': 'native VPT2 Geometry table Mass [u]',
                                'policy': 'identical native printed masses for both rotor tensors',
                                'precision_amu': 1e-6, 'isotope_sanity_check': isotopes,
                                'not_identical_to_TOPOS_default_mass_convention': True},
            'axis_correspondence': {'native_axis_for_sorted_reference': list(native_order),
                                    'reference_axis_for_sorted_target': list(mapping),
                                    'absolute_overlaps': matched_overlaps, 'assignment_margin': margin,
                                    'minimum_relative_moment_gaps': gaps},
            'geometry_diagnostics': {'native_reference_alignment': native_alignment, 'target_reference_alignment': alignment,
                                     'maximum_pair_distance_change_angstrom': pair_change, 'stereochemistry': stereo},
            'options': options.model_dump(mode='json'), 'native_execution_verified': False,
            'limitations': ['Separate fully relaxed DFT reference; not a constrained VPT2 force field.',
                            'The declared same conformational basin is screened by geometry, graph and stereo, not proven by barriers.',
                            'First-order transferred correction; no empirical accuracy or isotope-reanalysis guarantee.',
                            'No transferred centrifugal distortion constants, fundamentals or thermochemistry.']}


def transfer_rotational_correction(target: Molecule, native_vpt2: EngineResult,
                                  options: RotationalTransferOptions) -> dict[str, Any]:
    """Require immutable native evidence before evaluating the transfer."""
    import json
    from pathlib import Path

    from .anharmonic import (
        orca_vpt2_input,
        parse_orca_vpt2,
        parse_orca_vpt2_geometry,
        vpt2_execution_policy,
    )
    from .engines import _engine_version, _orca_input, parse_orca_engrad
    from .models import MethodSpec, ResourceLimits
    from .native_hessian import orca_frequency_input, parse_orca_hessian
    from .science import harmonic_analysis
    from .storage import file_digest

    result = native_vpt2
    md = result.metadata
    method = md.get('requested_method', {})
    if (result.status != 'completed' or result.converged is not True or result.engine != 'orca'
            or result.engine_version != '6.1.1' or result.operation != 'anharmonic'
            or md.get('execution_kind') != 'real' or not result.command or not result.artifacts
            or result.molecule is None or method.get('method') != 'B3LYP' or result.method != 'B3LYP'
            or method.get('basis') != 'def2-TZVPP' or method.get('constraints')
            or method.get('dispersion') != 'D4' or method.get('solvent')
            or method.get('profile_id') != 'orca-vpt2-reference-v1' or md.get('semirigid_declared') is not True):
        raise ValueError('transfer requires completed native ORCA 6.1.1 stationary B3LYP-D4/def2-TZVPP VPT2 evidence')
    paths = set()
    for artifact in result.artifacts:
        path = Path(artifact.path)
        if path.is_symlink() or not path.is_file() or file_digest(path) != artifact.sha256 or path.stat().st_size != artifact.size_bytes:
            raise ValueError('native VPT2 artifact changed')
        paths.add(str(path.resolve()))
    stdout = Path(result.diagnostics.get('process', {}).get('stdout_path', ''))
    if str(stdout.resolve()) not in paths:
        raise ValueError('native VPT2 stdout is not in the verified artifact inventory')
    raw = stdout.read_text()
    if 'ORCA TERMINATED NORMALLY' not in raw or _engine_version(raw, 'orca') != '6.1.1':
        raise ValueError('native VPT2 normal completion missing')
    native = parse_orca_vpt2(raw, vibrational_modes=3*len(target.symbols)-6)
    geometry = parse_orca_vpt2_geometry(raw, natoms=len(target.symbols))
    if native != md.get('vpt2') or geometry != md.get('vpt2_geometry'):
        raise ValueError('native VPT2 metadata differs from immutable raw evidence')
    reference = md.get('reference_hessian_result', {})
    reference_md = reference.get('metadata', {})
    if (reference.get('status') != 'completed' or reference.get('molecule') != result.molecule.model_dump(mode='json')
            or reference.get('engine_version') != result.engine_version or reference.get('method') != result.method
            or reference_md.get('execution_kind') != 'real' or reference_md.get('requested_method') != method
            or reference_md.get('executable_sha256') != md.get('executable_sha256')):
        raise ValueError('same-level native reference Hessian evidence missing')
    reference_stdout = Path(reference.get('diagnostics', {}).get('process', {}).get('stdout_path', ''))
    reference_hessian = reference_stdout.parent / 'frequency.hess'
    derivative = reference_md.get('reference_gradient_result', {})
    derivative_stdout = Path(derivative.get('diagnostics', {}).get('process', {}).get('stdout_path', ''))
    derivative_file = derivative_stdout.parent / 'job.engrad'
    for path in (reference_stdout, reference_hessian, derivative_stdout, derivative_file):
        if str(path.resolve()) not in paths:
            raise ValueError('native stationary reference raw derivatives are not inventoried')
    protocol = md.get('protocol', {})
    protocol_path = stdout.parent.parent / 'vpt2-protocol.json'
    if str(protocol_path.resolve()) not in paths or json.loads(protocol_path.read_text()) != protocol:
        raise ValueError('native VPT2 recovery protocol differs from immutable artifact evidence')
    if (protocol.get('schema') != 'topos-native-orca-vpt2/0.1.0'
            or protocol.get('method') != method or protocol.get('molecule') != result.molecule.model_dump(mode='json')):
        raise ValueError('native VPT2 protocol does not bind reference method and molecule')
    spec = MethodSpec.model_validate(method)
    resources = ResourceLimits.model_validate(protocol['resources'])
    expected_policy = vpt2_execution_policy(resources)
    effective_resources = resources.model_copy(update={'threads': 1}).model_dump(exclude={'budget_seconds'})
    if (protocol.get('execution_policy') != expected_policy
            or md.get('execution_policy') != expected_policy
            or protocol.get('effective_resources') != effective_resources):
        raise ValueError('native VPT2 execution policy differs from its requested and effective resources')
    native_allocation = md.get('native_execution_resources')
    if not isinstance(native_allocation, dict) or set(native_allocation) != set(resources.model_dump()):
        raise ValueError('native VPT2 process allocation evidence missing or incomplete')
    native_resources = ResourceLimits.model_validate(native_allocation)
    if native_resources.model_dump(exclude={'budget_seconds'}) != effective_resources:
        raise ValueError('native VPT2 process allocation differs from its declared serial policy')
    requested_allocation = md.get('requested_resources')
    if not isinstance(requested_allocation, dict) or set(requested_allocation) != set(resources.model_dump()):
        raise ValueError('native VPT2 requested resource evidence missing or incomplete')
    requested_resources = ResourceLimits.model_validate(requested_allocation)
    if (requested_resources.model_dump(exclude={'budget_seconds'}) != protocol['resources']
            or native_resources.budget_seconds > requested_resources.budget_seconds):
        raise ValueError('native VPT2 allocation exceeds or differs from its original request')
    decks = {stdout.parent / 'anharmonic.inp': orca_vpt2_input(result.molecule, spec, resources,
                                                              displacement=protocol['displacement']),
             reference_stdout.parent / 'frequency.inp': orca_frequency_input(result.molecule, spec, resources),
             derivative_stdout.parent / 'job.inp': _orca_input(result.molecule, spec, resources, 'gradient')}
    for path, expected_deck in decks.items():
        if str(path.resolve()) not in paths or path.read_text() != expected_deck:
            raise ValueError('native VPT2/reference method differs from actual compiled input')
    for output in (reference_stdout, derivative_stdout):
        evidence = output.read_text()
        if 'ORCA TERMINATED NORMALLY' not in evidence or _engine_version(evidence, 'orca') != '6.1.1':
            raise ValueError('native stationary reference derivative did not complete')
    parsed_hessian = parse_orca_hessian(reference_hessian, result.molecule)
    energy, gradient = parse_orca_engrad(derivative_file, result.molecule)
    if (not np.allclose(parsed_hessian['hessian_hartree_per_bohr2'], reference_md['hessian_hartree_per_bohr2'], atol=1e-12, rtol=0)
            or not np.allclose(gradient, reference['gradient_hartree_per_bohr'], atol=1e-12, rtol=0)
            or not np.isclose(energy, reference['energy_hartree'], atol=1e-10, rtol=0)):
        raise ValueError('native stationary reference metadata differs from raw derivatives')
    analysis = harmonic_analysis(result.molecule, parsed_hessian['hessian_hartree_per_bohr2'],
                                 gradient_hartree_per_bohr=gradient, gradient_threshold=1e-7)
    if analysis['validity'] != 'harmonic-minimum-within-thresholds' or min(analysis['frequencies_cm1']) < 50:
        raise ValueError('native VPT2 reference is not a strict stationary semirigid minimum')
    report = calculate_rotational_transfer(target, result.molecule, geometry,
                                           native['rotational_constants_cm1']['B_e'],
                                           native['rotational_constants_cm1']['B_0'], options)
    report.update(native_execution_verified=True, native_source={'command': result.command,
                  'engine_version': result.engine_version, 'requested_method': method,
                  'artifacts': [a.model_dump(mode='json') for a in result.artifacts]})
    return report
