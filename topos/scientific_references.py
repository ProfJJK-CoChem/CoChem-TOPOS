"""Predeclared, cited reference comparisons against immutable native run evidence.

This module never invents literature values, tolerances or uncertainty. A repeat
of a prior native result can test reproducibility, but cannot pass the scientific
reference release condition. Local timestamps/hashes demonstrate internal order
and integrity; they are not independent trusted timestamping or peer review.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import Field, field_validator, model_validator

from .models import Contract, MethodSpec, Molecule, ResourceLimits, RunRecord, RunRequest, utc_now
from .release import source_inventory
from .storage import IntegrityError, RunStore, atomic_json, confined_file, digest_json, file_digest

Observable = Literal['electronic_energy', 'gibbs_energy', 'equilibrium_rotational_constants',
                     'ground_state_rotational_constants', 'approximate_transferred_ground_state_rotational_constants',
                     'harmonic_frequencies', 'cp_interaction_energy']
GeometryRole = Literal['supplied-input', 'optimized-stationary-geometry', 'harmonic-minimum',
                       'ground-state-average', 'approximate-transferred-ground-state-average', 'frozen-complex-geometry']
HASH_PATTERN = r'^[0-9a-f]{64}$'
ENERGY_DEFINITION = 'electronic potential energy at recorded output geometry; no ZPE or thermal corrections'
ROTOR_DEFINITION = 'rigid-rotor constants from the recorded geometry and declared isotope masses; no vibrational correction'
CP_DEFINITION = 'counterpoise-corrected electronic interaction energy at the predeclared frozen complex geometry; no relaxation, ZPE or thermal corrections'
FREQUENCY_DEFINITION = 'positive mass-weighted harmonic vibrational frequencies at a validated full-dimensional minimum; rigid translations and rotations removed'
B0_DEFINITION = 'ground-state rotational constants from the actual native stationary semirigid VPT2 reference; no transferred correction'
TRANSFER_DEFINITION = 'approximate composite B0 = Be_target + (B0_DFT - Be_DFT), with native semirigid VPT2 and mass- and axis-matched correction transfer'


def _timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError('An explicit timezone is required for predeclaration evidence')
    return timestamp


class ReferenceCitation(Contract):
    title: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    kind: Literal['peer-reviewed', 'data-repository', 'official-documentation', 'native-reproducibility-calibration']
    extraction_notes: str = Field(min_length=1)


class ReferenceTolerance(Contract):
    absolute: float = Field(ge=0, strict=True)
    relative: float = Field(ge=0, strict=True)
    rationale: str = Field(min_length=1)

    @model_validator(mode='after')
    def declared(self):
        if self.absolute == self.relative == 0:
            raise ValueError('An independently justified positive comparison tolerance is required')
        return self


class ReferenceProtocol(Contract):
    """Published/reference physics, independently of the method being evaluated."""
    method: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    core_treatment: str = Field(min_length=1)
    counterpoise: str = Field(min_length=1)
    geometry_convention: str = Field(min_length=1)
    geometry_role: GeometryRole
    geometry_sha256: str | None = Field(pattern=HASH_PATTERN)
    energy_zero: str = Field(min_length=1)
    state_and_environment: str = Field(min_length=1)
    isotope_mass_convention: str = Field(min_length=1)
    source_limitations: str = Field(min_length=1)


class ReferenceDatum(Contract):
    name: str = Field(min_length=1)
    context_sha256: str = Field(pattern=HASH_PATTERN)
    value: float | list[float]
    uncertainty: float | list[float] | None
    uncertainty_definition: str = Field(min_length=1)

    @field_validator('value', 'uncertainty', mode='before')
    @classmethod
    def numeric(cls, value):
        if value is None:
            return value
        values = value if isinstance(value, list) else [value]
        if not values or any(type(item) not in {int, float} or not math.isfinite(item) for item in values):
            raise ValueError('Reference data must contain finite numeric values, never missing-value sentinels')
        return value

    @model_validator(mode='after')
    def uncertainty_shape(self):
        if self.uncertainty is not None:
            uncertainty = np.asarray(self.uncertainty)
            if uncertainty.shape != np.asarray(self.value).shape or np.any(uncertainty < 0):
                raise ValueError('Reference uncertainty must be nonnegative and match the observable shape')
        return self


class ReferenceDataFile(Contract):
    schema_version: Literal['topos-reference-data/1'] = 'topos-reference-data/1'
    data: dict[str, ReferenceDatum]


class ReferenceCase(Contract):
    case_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')
    chemistry_domain: str = Field(min_length=1)
    request: RunRequest
    observable: Observable
    definition: str = Field(min_length=1)
    units: Literal['hartree', 'GHz', 'cm^-1']
    geometry_role: GeometryRole
    engine_version: str = Field(min_length=1)
    reference_file: str = Field(min_length=1)
    reference_sha256: str = Field(pattern=HASH_PATTERN)
    datum_id: str = Field(min_length=1)
    citation: ReferenceCitation
    tolerance: ReferenceTolerance
    reference_protocol: ReferenceProtocol
    comparison_rationale: str = Field(min_length=1)

    @model_validator(mode='after')
    def observable_contract(self):
        energy = self.observable in {'electronic_energy', 'gibbs_energy', 'cp_interaction_energy'}
        expected_units = 'cm^-1' if self.observable == 'harmonic_frequencies' else 'hartree' if energy else 'GHz'
        if self.units != expected_units:
            raise ValueError('Observable units must match exactly; automatic conversion is not a reference comparison')
        if (self.observable == 'ground_state_rotational_constants') != (self.geometry_role == 'ground-state-average'):
            raise ValueError('Ground-state rotational averages and equilibrium geometry are distinct observables')
        if (self.observable == 'approximate_transferred_ground_state_rotational_constants') != (self.geometry_role == 'approximate-transferred-ground-state-average'):
            raise ValueError('Approximate transferred B0 and directly calculated native B0 are distinct observables')
        if self.observable == 'electronic_energy' and self.definition != ENERGY_DEFINITION:
            raise ValueError('Electronic reference definition must exclude thermal/Gibbs corrections explicitly')
        if self.observable == 'equilibrium_rotational_constants' and self.definition != ROTOR_DEFINITION:
            raise ValueError('Equilibrium rotor definition must exclude vibrational averaging explicitly')
        if self.observable == 'equilibrium_rotational_constants' and (
                self.geometry_role not in {'optimized-stationary-geometry', 'harmonic-minimum'} or self.request.constraints):
            raise ValueError('Equilibrium rotor references require an unconstrained stationary optimization or full-dimensional harmonic minimum')
        expected_definitions = {'cp_interaction_energy': CP_DEFINITION, 'harmonic_frequencies': FREQUENCY_DEFINITION,
                                'ground_state_rotational_constants': B0_DEFINITION,
                                'approximate_transferred_ground_state_rotational_constants': TRANSFER_DEFINITION}
        if self.observable in expected_definitions and self.definition != expected_definitions[self.observable]:
            raise ValueError('The predeclared observable definition must identify its exact native or approximate quantity')
        if self.observable == 'cp_interaction_energy' and self.geometry_role != 'frozen-complex-geometry':
            raise ValueError('CP electronic interaction references require the frozen complex geometry')
        if self.observable in {'gibbs_energy', 'harmonic_frequencies'} and self.geometry_role != 'harmonic-minimum':
            raise ValueError('Thermal and harmonic references require a validated full-dimensional harmonic minimum')
        if self.geometry_role == 'supplied-input' and self.request.purpose != 'energy':
            raise ValueError('A supplied-input reference requires an explicit fixed-geometry energy request')
        if self.geometry_role == 'optimized-stationary-geometry' and self.request.purpose != 'optimize':
            raise ValueError('An optimized geometry reference requires an explicit optimization request')
        if self.geometry_role in {'optimized-stationary-geometry', 'harmonic-minimum'} and self.request.constraints:
            raise ValueError('Full-dimensional stationary reference roles cannot declare frozen or constrained coordinates')
        compatible_roles = {self.geometry_role}
        if self.geometry_role in {'optimized-stationary-geometry', 'harmonic-minimum'}:
            compatible_roles = {'optimized-stationary-geometry', 'harmonic-minimum'}
        if self.geometry_role == 'approximate-transferred-ground-state-average':
            compatible_roles.add('ground-state-average')
        if self.reference_protocol.geometry_role not in compatible_roles:
            raise ValueError('Source reference geometry role differs from the predeclared physical observable')
        if self.geometry_role in {'supplied-input', 'frozen-complex-geometry'} and (
                self.reference_protocol.geometry_sha256 != digest_json(self.request.molecule.model_dump(mode='json', exclude={'name'}))):
            raise ValueError('Fixed reference geometry/state hash must match the exact declared molecular input')
        return self

    def context(self) -> dict[str, Any]:
        # Time/resource ceilings and presentation labels do not alter the
        # Hamiltonian. They remain exactly bound in the predeclared request.
        scientific = self.request.model_dump(mode='json', exclude={
            'budget_seconds', 'threads', 'memory_mb', 'presentation_environment', 'metadata',
            'include_queue_in_budget', 'per_geometry_budget_seconds', 'per_ensemble_budget_seconds',
        })
        return {'request': scientific, 'observable': self.observable, 'definition': self.definition,
                'units': self.units, 'geometry_role': self.geometry_role, 'engine_version': self.engine_version,
                'reference_protocol': self.reference_protocol.model_dump(mode='json'),
                'comparison_rationale': self.comparison_rationale}


class ReferenceCampaign(Contract):
    schema_version: Literal['topos-reference-plan/1'] = 'topos-reference-plan/1'
    campaign_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')
    assessment_kind: Literal['scientific-reference', 'reproducibility-calibration']
    predeclaration_rationale: str = Field(min_length=1)
    cases: list[ReferenceCase] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_scopes(self):
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError('Reference case identities must be unique')
        if self.assessment_kind == 'scientific-reference' and any(
                case.citation.kind == 'native-reproducibility-calibration' for case in self.cases):
            raise ValueError('Native reproducibility references cannot certify independent scientific accuracy')
        return self


def _datum(case: ReferenceCase, path: Path) -> ReferenceDatum:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024**2:
        raise ValueError('Reference data must be a bounded regular local file')
    if file_digest(path) != case.reference_sha256:
        raise IntegrityError('Cited reference data checksum changed')
    data = ReferenceDataFile.model_validate(json.loads(path.read_text()))
    if case.datum_id not in data.data:
        raise ValueError('Explicit reference datum is absent')
    datum = data.data[case.datum_id]
    if datum.context_sha256 != digest_json(case.context()):
        raise ValueError('Reference observable, geometry, Hamiltonian, isotope/state or conditions differ')
    if case.observable == 'harmonic_frequencies':
        from .science import rotational_constants
        geometry_class = rotational_constants(case.request.molecule)['geometry_class']
        n = len(case.request.molecule.symbols)
        expected_shape = (max(0, 3*n-(5 if geometry_class == 'linear' else 6)),)
    else:
        expected_shape = () if case.observable in {'electronic_energy', 'gibbs_energy', 'cp_interaction_energy'} else (3,)
    if np.asarray(datum.value).shape != expected_shape:
        raise ValueError('Reference observable dimension is incomplete or incompatible')
    return datum


def validate_plan(plan_path: Path) -> ReferenceCampaign:
    campaign = ReferenceCampaign.model_validate(json.loads(plan_path.read_text()))
    for case in campaign.cases:
        _datum(case, plan_path.parent / case.reference_file)
    return campaign


def freeze_plan(plan_path: Path, output: Path, measurement_root: Path, *, source_root: Path) -> Path:
    """Copy cited data and freeze the comparison before any measured run exists."""
    campaign = validate_plan(plan_path)
    output, measurement_root = output.resolve(), measurement_root.resolve()
    if output.exists() or measurement_root.exists() or output == measurement_root:
        raise ValueError('Freeze output and measurement root must both be fresh and distinct')
    if output.is_relative_to(measurement_root) or measurement_root.is_relative_to(output):
        raise ValueError('Reference freeze and measured RunStores must have distinct directory ownership')
    if output.parent != measurement_root.parent:
        raise ValueError('Frozen references and measured RunStores must be sibling directories in one portable campaign bundle')
    output.mkdir(parents=True)
    references = output / 'references'
    references.mkdir()
    assets = {}
    for case in campaign.cases:
        original = plan_path.parent / case.reference_file
        target = references / (case.reference_sha256 + '.json')
        if not target.exists():
            target.write_bytes(original.read_bytes())
        _datum(case, target)
        assets[case.case_id] = str(target.relative_to(output))
    frozen = {'schema_version': 'topos-reference-freeze/1', 'plan': campaign.model_dump(mode='json'),
              'frozen_at': utc_now(), 'measurement_root': '../' + measurement_root.name, 'reference_assets': assets,
              'source_sha256': source_inventory(source_root),
              'predeclaration_limit': 'Local timestamps, directory freshness and immutable RunStore history; no independent trusted timestamping or authorship proof'}
    frozen['freeze_sha256'] = digest_json(frozen)
    path = output / 'frozen-plan.json'
    atomic_json(path, frozen)
    measurement_root.mkdir(parents=True)
    return path


def _measurement_root(frozen_path: Path, frozen: dict) -> Path:
    relative = frozen.get('measurement_root', '')
    if not re.fullmatch(r'\.\./[A-Za-z0-9_.-]+', relative):
        raise IntegrityError('Measured RunStore root must be a bounded sibling of the frozen reference directory')
    root = frozen_path.parent.parent.resolve(strict=True)
    measurement = (frozen_path.parent / relative).resolve(strict=True)
    if measurement.parent != root or measurement.is_symlink() or not measurement.is_dir():
        raise IntegrityError('Measured RunStore root escapes its portable campaign bundle')
    return measurement


def _frozen(path: Path, source_root: Path) -> tuple[dict, ReferenceCampaign]:
    if path.is_symlink() or not path.is_file():
        raise IntegrityError('A physical regular frozen plan is required')
    frozen = json.loads(path.read_text())
    identity = {key: value for key, value in frozen.items() if key != 'freeze_sha256'}
    if frozen.get('schema_version') != 'topos-reference-freeze/1' or digest_json(identity) != frozen.get('freeze_sha256'):
        raise IntegrityError('Frozen reference plan identity changed')
    if frozen.get('source_sha256') != source_inventory(source_root):
        raise IntegrityError('Reference campaign executable/test source differs from the frozen revision')
    _timestamp(frozen['frozen_at'])
    _measurement_root(path, frozen)
    campaign = ReferenceCampaign.model_validate(frozen['plan'])
    if set(frozen['reference_assets']) != {case.case_id for case in campaign.cases}:
        raise IntegrityError('Frozen reference data membership changed')
    for case in campaign.cases:
        _datum(case, confined_file(path.parent, frozen['reference_assets'][case.case_id]))
    return frozen, campaign


def _orca_optimization_proof(attempt, molecule: Molecule, snapshot: Path) -> tuple[float, dict]:
    """Reuse production native optimizer/gradient gates without ML label restrictions."""
    from .engines import _orca_input, parse_orca_engrad, read_xyz
    from .ml_training import (
        _dft_output_energy,
        _final_gradient_contract,
        _optimization_refinement_contract,
        _optimization_refinement_evidence,
        _reference_artifact,
        _validate_final_stationarity,
    )
    from .orca_geometry_evidence import convergence_evidence

    method = MethodSpec.model_validate(attempt.metadata['requested_method'])
    resources = ResourceLimits.model_validate(attempt.metadata['resources'])
    initial = Molecule.model_validate(attempt.metadata['input_molecule'])
    if method.method != attempt.method or method.engine != 'orca' or method.constraints or method.solvent:
        raise IntegrityError('Native optimizer reference changed its recorded Hamiltonian or constrained domain')
    stages = _optimization_refinement_contract(attempt, initial, molecule, method, resources)
    retained = _optimization_refinement_evidence(snapshot, attempt, stages, method)
    selected = stages[-1]['stage_directory'] if stages else ''
    stage_initial = Molecule.model_validate(stages[-1]['input_molecule']) if stages else initial
    files = {name: _reference_artifact(snapshot, attempt, name, stage=selected)
             for name in ('job.inp', 'engine.stdout', 'job.xyz')}
    if files['job.inp'].read_text() != _orca_input(stage_initial, method, resources, 'optimize'):
        raise IntegrityError('Native optimizer input differs from its exact typed method and geometry')
    stdout, optimizer_energy = _dft_output_energy(files['engine.stdout'])
    tolerance = 1e-10 if method.profile_id == 'orca-vpt2-reference-v1' else 1e-7
    criteria, energy_evidence = convergence_evidence(stdout, energy_tolerance=tolerance)
    if ('THE OPTIMIZATION HAS CONVERGED' not in stdout or len(criteria) != 5 or not all(criteria.values())
            or criteria != attempt.diagnostics.get('convergence')
            or energy_evidence != attempt.diagnostics.get('energy_change_evidence')
            or read_xyz(files['job.xyz'], stage_initial) != molecule):
        raise IntegrityError('Native optimizer endpoint lacks all five genuine convergence conditions and exact geometry')
    final = _final_gradient_contract(attempt, molecule, method, resources, optimization_stage=selected)
    gradient_files = {name: _reference_artifact(snapshot, attempt, name, stage=final['directory'])
                      for name in final['native_files_sha256']}
    if (any(file_digest(path) != final['native_files_sha256'][name] for name, path in gradient_files.items())
            or gradient_files['job.inp'].read_text() != _orca_input(
                molecule, method, ResourceLimits.model_validate(final['resources']), 'gradient')):
        raise IntegrityError('Independent final gradient differs from its exact bound native input and bytes')
    _, final_energy = _dft_output_energy(gradient_files['engine.stdout'])
    energy, gradient = parse_orca_engrad(gradient_files['job.engrad'], molecule)
    if (abs(energy-final_energy) > 2e-7 or abs(energy-optimizer_energy) > 2e-7
            or final.get('energy_hartree') != final_energy
            or final.get('energy_difference_hartree') != final_energy-optimizer_energy):
        raise IntegrityError('Independent final gradient and native optimizer energies disagree')
    _validate_final_stationarity(gradient, method, attempt.diagnostics.get('independent_stationarity', {}))
    quantities = [q for q in attempt.quantities if q.name == 'cartesian_gradient']
    if (len(quantities) != 1 or quantities[0].units != 'hartree/bohr'
            or quantities[0].validity != 'validated-for-protocol'
            or not np.allclose(quantities[0].value, gradient, atol=1e-12, rtol=0)):
        raise IntegrityError('Independent native final gradient differs from its structured quantity')
    retained.update(files)
    retained.update({final['directory'] + '/' + name: path for name, path in gradient_files.items()})
    return energy, {'all_five_native_optimizer_conditions': criteria,
                    'independent_final_gradient': final['native_files_sha256'],
                    'retained_native_files_sha256': {name: file_digest(path) for name, path in retained.items()}}


def _vpt2_value(case: ReferenceCase, record: RunRecord, store: RunStore) -> tuple[Any, dict]:
    """Reparse immutable native spectroscopy and recompute the declared transfer."""
    from .engines import EngineResult, _engine_version, _number, _orca_input, parse_orca_engrad
    from .native_hessian import parse_orca_hessian
    from .rotational_transfer import (
        RotationalTransferOptions,
        proper_alignment,
        rotate_cartesian_hessian,
        transfer_rotational_correction,
    )

    transferred = case.observable == 'approximate_transferred_ground_state_rotational_constants'
    payload = record.metadata.get('matrix_r2') if transferred else None
    if transferred:
        if (not isinstance(payload, dict) or payload.get('row_id') != 'T3O-3h'
                or payload.get('source_resolution') != 'r2-b3lyp-d4-vpt2-transfer-v1'
                or payload.get('approximate_composite') is not True
                or payload.get('target_full_molecule_stationary') is not False
                or payload.get('reference_full_molecule_relaxed') is not True):
            raise IntegrityError('Transferred B0 requires the explicitly reviewed approximate R2 composite')
        result_path = payload.get('result_path', '')
        receipt = json.loads(confined_file(store.snapshot_path(), 'artifacts/' + result_path).read_text())
        if receipt != {key: value for key, value in payload.items() if key != 'result_path'}:
            raise IntegrityError('R2 composite differs from its immutable scientific result receipt')
        target = Molecule.model_validate(payload['target_molecule'])
        options = RotationalTransferOptions.model_validate(payload['options']['transfer'])
        derivatives = [a for a in record.attempts if a.attempt_id == payload['geometry']['accepted_derivative_attempt_id']]
        if len(derivatives) != 1:
            raise IntegrityError('R2 target lacks its unique actual QZ derivative')
        derivative = derivatives[0]
        if (derivative.engine != 'orca' or derivative.method != 'wB97M-V' or derivative.engine_version != case.engine_version
                or derivative.status != 'completed' or derivative.validation_status != 'validated-for-protocol'
                or derivative.converged is not True or derivative.metadata.get('execution_kind') != 'real'
                or derivative.metadata.get('output_molecule') != target.model_dump(mode='json')):
            raise IntegrityError('R2 target differs from its actual quantum derivative geometry and state')
        gradients = [a for a in derivative.artifacts if Path(a.path).name == 'job.engrad']
        inputs = [a for a in derivative.artifacts if Path(a.path).name == 'job.inp']
        outputs = [a for a in derivative.artifacts if Path(a.path).name == 'engine.stdout']
        if len(gradients) != 1 or len(inputs) != 1 or len(outputs) != 1:
            raise IntegrityError('R2 target requires an immutable native Cartesian derivative')
        method = MethodSpec.model_validate(derivative.metadata['requested_method'])
        if (method.method != 'wB97M-V' or method.basis != 'def2-QZVPP' or method.auxiliary_basis != 'def2/J'
                or method.profile_id != 'orca-mapping-v4.1' or method.solvent or method.dispersion or method.constraints):
            raise IntegrityError('R2 target derivative differs from the reviewed exact QZ Hamiltonian')
        deck = confined_file(store.snapshot_path(), 'artifacts/' + inputs[0].path)
        if deck.read_text() != _orca_input(target, method, ResourceLimits.model_validate(derivative.metadata['resources']), 'gradient'):
            raise IntegrityError('R2 target raw derivative input differs from its quantum geometry and method')
        raw = confined_file(store.snapshot_path(), 'artifacts/' + outputs[0].path).read_text()
        literals = re.findall(r'FINAL SINGLE POINT ENERGY\s+([-+0-9.EeDd]+)', raw)
        derivative_energy, _ = parse_orca_engrad(confined_file(store.snapshot_path(), 'artifacts/' + gradients[0].path), target)
        if (not literals or abs(_number(literals[-1])-derivative_energy) > 2e-7
                or _engine_version(raw, 'orca') != case.engine_version or 'ORCA TERMINATED NORMALLY' not in raw
                or 'SCF CONVERGED AFTER' not in raw or re.search(r'SCF NOT CONVERGED|SCF CONVERGENCE FAILURE', raw, re.I)):
            raise IntegrityError('R2 target raw electronic/derivative output lacks genuine consistent native convergence')
        attempts = [a for a in record.attempts if a.metadata.get('component_key') == 'r2-independent-dft-vpt2'
                    and a.status == 'completed']
    else:
        attempts = [a for a in record.attempts if a.metadata.get('native_result', {}).get('operation') == 'anharmonic'
                    and a.status == 'completed' and a.method == case.request.method]
        options = RotationalTransferOptions(semirigid_same_basin=True)
    if len(attempts) != 1:
        raise IntegrityError('Native ground-state constants require one explicit genuine VPT2 attempt; Be cannot substitute')
    attempt = attempts[0]
    native = attempt.metadata.get('native_result')
    if (not isinstance(native, dict) or digest_json(native) != attempt.metadata.get('native_result_sha256')
            or attempt.engine_version != case.engine_version or attempt.validation_status != 'validated-for-protocol'
            or attempt.converged is not True or attempt.metadata.get('execution_kind') != 'real'):
        raise IntegrityError('Native VPT2 result lacks immutable receipt, actual execution or exact version')
    receipts = [a for a in attempt.artifacts if a.role == 'matrix-native-component-result']
    if len(receipts) != 1 or json.loads(confined_file(store.snapshot_path(), 'artifacts/' + receipts[0].path).read_text()) != native:
        raise IntegrityError('Native VPT2 metadata differs from its retained engine result')
    native_result = EngineResult.model_validate(native)
    if native_result.molecule is None:
        raise IntegrityError('Native VPT2 has no stationary reference geometry')
    if not transferred:
        target = native_result.molecule
        identity = target.model_dump(exclude={'name', 'coordinates'})
        if identity != case.request.molecule.model_dump(exclude={'name', 'coordinates'}):
            raise IntegrityError('Native VPT2 reference changed the declared molecular identity')
        if native_result.metadata.get('requested_method') != case.request.method_spec.model_dump(mode='json'):
            raise IntegrityError('Native VPT2 reference differs from the exact predeclared method, basis or derivative profile')
    # Reconstruct exact native directory hierarchy from verified snapshot bytes.
    # Path rebinding changes only locators, never science, hashes or source data.
    originals = {a.path: a for a in native_result.artifacts}
    common = Path(os.path.commonpath(list(originals)))
    if common in map(Path, originals):
        common = common.parent
    if (native_result.command != attempt.command or native_result.engine != attempt.engine
            or native_result.method != attempt.method or native_result.operation != 'anharmonic'
            or not originals):
        raise IntegrityError('Native VPT2 receipt changes the actual attempt identity')
    with tempfile.TemporaryDirectory(prefix='topos-reference-vpt2-') as scratch:
        replacements = {}
        for original, artifact in originals.items():
            relative = Path(original).relative_to(common)
            matching = [a for a in attempt.artifacts if a.path.endswith('/' + relative.as_posix())
                        and (a.sha256, a.size_bytes, a.role) == (artifact.sha256, artifact.size_bytes, artifact.role)]
            if len(matching) != 1:
                raise IntegrityError('Native VPT2 receipt artifact is absent from its immutable attempt')
            recorded = matching[0]
            source = confined_file(store.snapshot_path(), 'artifacts/' + recorded.path)
            destination = Path(scratch) / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            replacements[original] = str(destination)

        def rebind(value):
            if isinstance(value, dict):
                return {key: rebind(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rebind(item) for item in value]
            return replacements.get(value, value) if isinstance(value, str) else value

        relocated = EngineResult.model_validate(rebind(native))
        recomputed = transfer_rotational_correction(target, relocated, options)
        geometry = relocated.metadata['vpt2_geometry']
        native_molecule = relocated.molecule.model_copy(update={'coordinates': geometry['coordinates_angstrom']})
        stdout = Path(relocated.diagnostics['process']['stdout_path'])
        hessian_path = stdout.parent/'anharmonic.hess'
        force_field = Path(relocated.metadata['native_force_field'])
        pickett = Path(relocated.metadata['native_pickett_template'])
        if any(str(path) not in replacements.values() or path.stat().st_size == 0
               for path in (hessian_path, force_field, pickett)):
            raise IntegrityError('Native VPT2 reference Hessian, force field or Pickett output is absent from its immutable inventory')
        parsed_hessian = parse_orca_hessian(hessian_path, native_molecule)
        alignment = proper_alignment(geometry['coordinates_angstrom'], relocated.molecule.coordinates, geometry['masses_amu'])
        rotated = rotate_cartesian_hessian(parsed_hessian['hessian_hartree_per_bohr2'], alignment['rotation_source_to_target'])
        reference_hessian = relocated.metadata['reference_hessian_result']['metadata']['hessian_hartree_per_bohr2']
        if not np.allclose(rotated, reference_hessian, atol=1e-7, rtol=1e-6):
            raise IntegrityError('Actual VPT2 reference Hessian differs from the same-level stationary derivative reference')
    if transferred:
        expected = payload['correction_transfer']
        actual_science = {key: value for key, value in recomputed.items() if key != 'native_source'}
        expected_science = {key: value for key, value in expected.items() if key != 'native_source'}
        if actual_science != expected_science or not np.allclose(
                np.asarray(payload['approximate_ground_state_rotational_constants_mhz']) / 1000,
                recomputed['constants_ghz'], atol=1e-12, rtol=0):
            raise IntegrityError('R2 approximate correction differs from independently reparsed native spectroscopy and transfer')
        value = recomputed['constants_ghz']
    else:
        from scipy.constants import c
        order = recomputed['axis_correspondence']['native_axis_for_sorted_reference']
        value = (np.asarray(recomputed['native_b0_cm1'])[order] * c / 1e7).tolist()
    return value, {'attempt_id': attempt.attempt_id, 'engine_version': attempt.engine_version,
                   'native_result_sha256': attempt.metadata['native_result_sha256'],
                   'native_artifacts_sha256': {a.path: a.sha256 for a in attempt.artifacts},
                   'geometry_sha256': digest_json(target.model_dump(mode='json')),
                   'parser': 'immutable-native-VPT2-stationary-hessian-and-axis-matched-transfer',
                   'approximate_composite': transferred,
                   'recomputed_science': {key: value for key, value in recomputed.items() if key != 'native_source'}}


def _native_value(case: ReferenceCase, record: RunRecord, store: RunStore) -> tuple[Any, dict]:
    """Import the actual observable through its dedicated raw-evidence validator."""
    if case.observable == 'cp_interaction_energy':
        from .reference_interaction import extract_reference_value
        return extract_reference_value(case, record, store)
    if case.observable in {'gibbs_energy', 'harmonic_frequencies'} or case.geometry_role == 'harmonic-minimum':
        from .reference_thermal import extract_reference_value
        return extract_reference_value(case, record, store)
    if case.observable in {'ground_state_rotational_constants', 'approximate_transferred_ground_state_rotational_constants'}:
        return _vpt2_value(case, record, store)
    candidates = [candidate for candidate in record.candidates if candidate.status == 'eligible']
    if len(candidates) != 1:
        raise ValueError('A predeclared unique eligible candidate is required; no post hoc candidate selection')
    candidate = candidates[0]
    attempts = [attempt for attempt in record.attempts if attempt.attempt_id == candidate.attempt_id]
    if len(attempts) != 1:
        raise ValueError('Native candidate must identify exactly one measured attempt')
    attempt = attempts[0]
    if (attempt.status != 'completed' or attempt.validation_status != 'validated-for-protocol'
            or attempt.converged is not True or attempt.metadata.get('execution_kind') != 'real'
            or not attempt.command or not attempt.artifacts or attempt.engine_version != case.engine_version
            or attempt.engine != case.request.engine or attempt.method != case.request.method):
        raise ValueError('Measured quantity lacks eligible actual-engine execution/version/method evidence')
    if attempt.metadata.get('requested_method') != case.request.method_spec.model_dump(mode='json'):
        raise IntegrityError('Native requested method/basis/profile differs from the predeclared comparison Hamiltonian')
    process = attempt.diagnostics.get('process', {})
    if (process.get('status') != 'completed' or process.get('returncode') != 0
            or process.get('command') != attempt.command or not Path(attempt.command[0]).is_absolute()
            or not re.fullmatch(HASH_PATTERN, str(attempt.metadata.get('executable_sha256', '')))):
        raise IntegrityError('Native observation lacks its successful actual process and hashed executable identity')
    if attempt.metadata.get('output_molecule') != candidate.molecule.model_dump(mode='json'):
        raise ValueError('Measured native output geometry differs from the eligible candidate')
    snapshot = store.snapshot_path()
    stdout_name = Path(attempt.diagnostics.get('process', {}).get('stdout_path', '')).name
    outputs = [artifact for artifact in attempt.artifacts if Path(artifact.path).name == stdout_name]
    if len(outputs) != 1:
        raise ValueError('Native process stdout is not uniquely inventoried')
    raw = confined_file(snapshot, 'artifacts/' + outputs[0].path).read_text(errors='replace')
    from .engines import XTB_PROFILES, _engine_version, _number, parse_xtb_gradient, read_xyz

    if attempt.engine == 'xtb':
        command = ['input.xyz', '--gfn', '2', '--chrg', str(case.request.molecule.charge),
                   '--uhf', str(case.request.molecule.multiplicity-1), '--json']
        if case.request.purpose == 'optimize':
            command.extend(['--opt', XTB_PROFILES[case.request.profile_id]])
        command.append('--grad')
        inputs = [artifact for artifact in attempt.artifacts if Path(artifact.path).name == 'input.xyz']
        if (attempt.command[1:] != command or len(inputs) != 1
                or read_xyz(confined_file(snapshot, 'artifacts/' + inputs[0].path), case.request.molecule) != case.request.molecule):
            raise IntegrityError('Native xTB command/input differs from its exact declared state and numerical profile')
        gradients = [artifact for artifact in attempt.artifacts if Path(artifact.path).name == 'gradient']
        error_outputs = [artifact for artifact in attempt.artifacts if Path(artifact.path).name == Path(process.get('stderr_path', '')).name]
        errors = confined_file(snapshot, 'artifacts/' + error_outputs[0].path).read_text(errors='replace') if len(error_outputs) == 1 else ''
        if (len(gradients) != 1 or 'convergence criteria satisfied' not in raw
                or 'normal termination of xtb' not in raw + errors):
            raise ValueError('Native xTB electronic/derivative evidence is incomplete')
        energy, gradient = parse_xtb_gradient(confined_file(snapshot, 'artifacts/' + gradients[0].path), candidate.molecule)
        literals = re.findall(r'TOTAL ENERGY\s+([-+0-9.EeDd]+)\s+Eh', raw)
        if not literals or abs(_number(literals[-1]) - energy) > 2e-9:
            raise ValueError('Native xTB energy differs from its actual gradient evaluation')
        # xTB's version was observed in its independently retained probe.
        version_outputs = [artifact for artifact in attempt.artifacts if Path(artifact.path).name == 'version.stdout']
        if len(version_outputs) != 1 or _engine_version(confined_file(snapshot, 'artifacts/' + version_outputs[0].path).read_text(), 'xtb') != case.engine_version:
            raise ValueError('Native xTB version is not independently retained')
        if case.request.purpose == 'optimize':
            optimized = [artifact for artifact in attempt.artifacts if Path(artifact.path).name == 'xtbopt.xyz']
            limits = re.findall(r'grad\. convergence\s+([-+0-9.EeDd]+)', raw)
            thresholds = re.findall(r'energy convergence\s+([-+0-9.EeDd]+)', raw)
            norm = float(np.linalg.norm(gradient))
            if (len(optimized) != 1 or 'GEOMETRY OPTIMIZATION CONVERGED' not in raw or not limits or not thresholds
                    or read_xyz(confined_file(snapshot, 'artifacts/' + optimized[0].path), case.request.molecule) != candidate.molecule
                    or norm > _number(limits[-1]) * (1+1e-6)):
                raise IntegrityError('Native xTB optimized rotor lacks its actual unconstrained profile-specific stationary endpoint')
            actual_convergence = {'profile': case.request.profile_id, 'native_level': XTB_PROFILES[case.request.profile_id],
                                 'native_reported': True, 'gradient_norm_hartree_per_bohr': norm,
                                 'gradient_norm_threshold': _number(limits[-1]),
                                 'energy_change_threshold_hartree': _number(thresholds[-1]),
                                 'criteria_source': 'xTB native optimizer; no claim of ORCA mapping tolerances'}
            if actual_convergence != attempt.diagnostics.get('convergence'):
                raise IntegrityError('Native xTB stationary endpoint diagnostics differ from its raw optimizer and gradient')
    elif attempt.engine == 'orca':
        if ('ORCA TERMINATED NORMALLY' not in raw or 'SCF CONVERGED AFTER' not in raw
                or re.search(r'SCF NOT CONVERGED|SCF CONVERGENCE FAILURE', raw, re.I)
                or _engine_version(raw, 'orca') != case.engine_version):
            raise IntegrityError('Native ORCA output lacks actual version, normal termination or converged SCF')
        literals = re.findall(r'FINAL SINGLE POINT ENERGY\s+([-+0-9.EeDd]+)', raw)
        if not literals:
            raise ValueError('Native ORCA electronic energy absent')
        energy = _number(literals[-1])
        if case.request.purpose == 'optimize':
            energy, optimization_proof = _orca_optimization_proof(attempt, candidate.molecule, snapshot)
        elif case.request.purpose == 'energy':
            from .engines import _orca_input
            inputs = [artifact for artifact in attempt.artifacts if Path(artifact.path).name == 'job.inp']
            resources = ResourceLimits.model_validate(attempt.metadata['resources'])
            if (len(inputs) != 1 or candidate.molecule != case.request.molecule
                    or confined_file(snapshot, 'artifacts/' + inputs[0].path).read_text() != _orca_input(
                        candidate.molecule, case.request.method_spec, resources, 'energy')):
                raise IntegrityError('Native ORCA fixed-geometry input differs from the predeclared typed method and geometry')
        else:
            raise ValueError('Ordinary reference requires an exact single-point or optimization request')
    else:
        raise LookupError('This native engine requires a dedicated verified reference importer')
    quantities = [quantity for quantity in attempt.quantities if quantity.name == 'electronic_energy']
    if (len(quantities) != 1 or quantities[0].units != 'hartree' or quantities[0].definition != ENERGY_DEFINITION
            or quantities[0].validity != 'validated-for-protocol' or quantities[0].attempt_id != attempt.attempt_id
            or quantities[0].geometry_id != candidate.candidate_id or quantities[0].method != attempt.method
            or not isinstance(quantities[0].value, float) or abs(quantities[0].value - energy) > 2e-9
            or candidate.energy_hartree is None or abs(candidate.energy_hartree - energy) > 2e-9):
        raise ValueError('Structured electronic quantity differs from its raw native observation')
    value = quantities[0].value
    if case.observable == 'equilibrium_rotational_constants':
        from .science import rotational_constants

        rotors = rotational_constants(candidate.molecule)
        if rotors != candidate.metadata.get('rotational_constants') or any(value is None for value in rotors['constants_ghz']):
            raise ValueError('Complete equilibrium rotor constants differ from recorded isotope-mass geometry arithmetic')
        value = rotors['constants_ghz']
    return value, {'candidate_id': candidate.candidate_id, 'attempt_id': attempt.attempt_id,
                   'engine_version': attempt.engine_version, 'geometry_sha256': digest_json(candidate.molecule.model_dump(mode='json')),
                   'native_stdout_sha256': outputs[0].sha256, 'parser': quantities[0].parser,
                   **({'optimization': optimization_proof} if attempt.engine == 'orca' and case.request.purpose == 'optimize' else {})}


def _case_result(case: ReferenceCase, frozen: dict, frozen_path: Path, binding: dict, *, source_root: Path) -> dict:
    datum = _datum(case, confined_file(frozen_path.parent, frozen['reference_assets'][case.case_id]))
    result = {'case_id': case.case_id, 'chemistry_domain': case.chemistry_domain, 'status': 'pending',
              'observable': case.observable, 'units': case.units, 'definition': case.definition,
              'geometry_role': case.geometry_role, 'reference': datum.model_dump(mode='json'),
              'reference_sha256': case.reference_sha256, 'citation': case.citation.model_dump(mode='json'),
              'tolerance': case.tolerance.model_dump(mode='json'), 'context_sha256': digest_json(case.context()),
              'reference_protocol': case.reference_protocol.model_dump(mode='json'),
              'comparison_rationale': case.comparison_rationale}
    if not binding:
        return {**result, 'reason': 'No measured native RunStore supplied'}
    run_dir = Path(binding['run_dir']).resolve(strict=True)
    if not run_dir.is_relative_to(_measurement_root(frozen_path, frozen)) or not (run_dir / 'CURRENT.json').is_file():
        raise ValueError('Measured run must belong to the fresh predeclared measurement root')
    store = RunStore(run_dir)
    raw, manifest = store.load(), store.verify()
    if manifest['record_sha256'] != binding['record_sha256'] or digest_json(raw) != binding['record_sha256']:
        raise IntegrityError('Measured scientific snapshot changed after explicit selection')
    record = RunRecord.model_validate(raw)
    if record.request != case.request or digest_json(raw['request']) != record.metadata.get('request_sha256'):
        raise ValueError('Measured immutable request differs from the predeclared scientific protocol')
    frozen_at = _timestamp(frozen['frozen_at'])
    if _timestamp(record.created_at) < frozen_at or any(
            not attempt.started_at or _timestamp(attempt.started_at) < frozen_at for attempt in record.attempts):
        raise ValueError('Reference plan was frozen after the measured run or one of its attempts began')
    # Verify every retained snapshot, including incomplete historical states.
    # A late imported/repackaged final snapshot cannot erase its earlier history.
    history = []
    for directory in sorted(store.snapshots.iterdir()):
        if directory.name.startswith('.pending-'):
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise IntegrityError('Unexpected RunStore history member')
        historical_manifest = json.loads(confined_file(directory, 'manifest.json').read_text())
        historical, _ = store._read_snapshot({'snapshot_id': directory.name, 'manifest_sha256': digest_json(historical_manifest)})
        if historical['run_id'] != record.run_id or _timestamp(historical['created_at']) < frozen_at:
            raise ValueError('Historical RunStore observation precedes the frozen reference plan')
        history.append(directory.name)
    expected_sources = {key: value for key, value in frozen['source_sha256'].items() if key.startswith('topos/') and key.endswith('.py')}
    if record.metadata.get('software', {}).get('source_files') != expected_sources:
        raise IntegrityError('Measured native workflow source differs from the predeclared campaign')
    authority = record.metadata.get('execution_authority', {})
    base = authority.get('backend') == 'cochem-base' and bool(re.fullmatch(HASH_PATTERN, str(authority.get('registry_sha256', ''))))
    result.update(run_id=record.run_id, snapshot_id=manifest['snapshot_id'], record_sha256=manifest['record_sha256'],
                  verified_snapshot_history=history, base_authority_verified=base)
    if record.status != 'completed':
        return {**result, 'reason': 'Actual native workflow did not complete; reference acceptance remains pending'}
    if frozen['plan']['assessment_kind'] == 'scientific-reference' and not base:
        return {**result, 'reason': 'Scientific release comparison requires mandatory BASE execution authority'}
    try:
        actual, native = _native_value(case, record, store)
    except LookupError as exc:
        return {**result, 'reason': str(exc)}
    if np.asarray(actual).shape != np.asarray(datum.value).shape or not np.isfinite(np.asarray(actual)).all():
        raise IntegrityError('Imported native observable is nonfinite or dimensionally different from its exact reference')
    delta = np.abs(np.asarray(actual) - np.asarray(datum.value))
    allowed = case.tolerance.absolute + case.tolerance.relative * np.abs(np.asarray(datum.value))
    result.update(status='passed' if bool(np.all(delta <= allowed)) else 'failed', measured_value=actual,
                  absolute_difference=delta.tolist(), allowed_difference=allowed.tolist(), native=native,
                  comparison_formula='abs(measured-reference) <= declared_absolute + declared_relative*abs(reference)',
                  uncertainty_policy='Reference uncertainty is retained separately; it never automatically widens the predeclared tolerance')
    return result


def assess_campaign(frozen_path: Path, bindings: dict[str, dict], *, source_root: Path) -> dict:
    frozen, campaign = _frozen(frozen_path, source_root)
    if set(bindings) - {case.case_id for case in campaign.cases}:
        raise ValueError('Measurement bindings contain undeclared reference cases')
    cases = []
    for case in campaign.cases:
        cases.append(_case_result(case, frozen, frozen_path, bindings.get(case.case_id, {}), source_root=source_root))
    statuses = {case['status'] for case in cases}
    comparison_status = 'failed' if 'failed' in statuses else 'pending' if 'pending' in statuses else 'passed'
    eligible = comparison_status == 'passed' and campaign.assessment_kind == 'scientific-reference'
    status = 'pending' if comparison_status == 'passed' and not eligible else comparison_status
    return {'schema_version': 'topos-scientific-reference-campaign/1', 'campaign_id': campaign.campaign_id,
            'status': status, 'comparison_status': comparison_status, 'assessment_kind': campaign.assessment_kind,
            'release_eligible': eligible, 'scientific_reference_campaign': eligible,
            'calibration_passed': comparison_status == 'passed' and campaign.assessment_kind == 'reproducibility-calibration',
            'condition': 'scientific_reference_campaign', 'source_sha256': frozen['source_sha256'],
            'freeze_sha256': frozen['freeze_sha256'], 'frozen_plan_sha256': file_digest(frozen_path),
            'predeclaration_limit': frozen['predeclaration_limit'], 'cases': cases,
            'scope': 'Only explicitly named matched reference cases; no general method accuracy or exhaustive sampling claim'}


def write_report(frozen_path: Path, bindings: dict[str, dict], output: Path, *, source_root: Path) -> dict:
    if output.exists():
        raise ValueError('A reference assessment cannot overwrite prior evidence')
    if output.parent.resolve() != frozen_path.parent.parent.resolve():
        raise ValueError('The report must belong to the campaign bundle root beside its frozen and measured directories')
    report = assess_campaign(frozen_path, bindings, source_root=source_root)
    report.update(frozen_plan=os.path.relpath(frozen_path.resolve(), output.parent.resolve()),
                  measured_runs={case_id: {'run_dir': os.path.relpath(Path(binding['run_dir']).resolve(), output.parent.resolve()),
                                          'record_sha256': binding['record_sha256']} for case_id, binding in bindings.items()},
                  assessed_at=utc_now())
    atomic_json(output, report)
    return report


def verify_report(report_path: Path, source_root: Path) -> dict:
    """Recompute the entire report from frozen data and actual native RunStores."""
    if report_path.is_symlink() or not report_path.is_file():
        raise IntegrityError('Scientific reference report must be a regular retained file')
    report = json.loads(report_path.read_text())
    frozen_path = confined_file(report_path.parent, report['frozen_plan'])
    bindings = {}
    for case_id, binding in report['measured_runs'].items():
        relative = Path(binding['run_dir'])
        if relative.is_absolute() or '..' in relative.parts:
            raise IntegrityError('Measured report locator escapes its portable campaign bundle')
        run_dir = (report_path.parent / relative).resolve(strict=True)
        if not run_dir.is_relative_to(report_path.parent.resolve()):
            raise IntegrityError('Measured report locator escapes its portable campaign bundle')
        bindings[case_id] = {**binding, 'run_dir': str(run_dir)}
    actual = assess_campaign(frozen_path, bindings, source_root=source_root)
    expected = {key: value for key, value in report.items() if key not in {'frozen_plan', 'measured_runs', 'assessed_at'}}
    if actual != expected or _timestamp(report['assessed_at']) < _timestamp(json.loads(frozen_path.read_text())['frozen_at']):
        raise IntegrityError('Scientific reference report differs from recomputed immutable evidence')
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('schema')
    validate = sub.add_parser('validate')
    validate.add_argument('plan', type=Path)
    freeze = sub.add_parser('freeze')
    freeze.add_argument('plan', type=Path)
    freeze.add_argument('--output', type=Path, required=True)
    freeze.add_argument('--measurement-root', type=Path, required=True)
    assess = sub.add_parser('assess')
    assess.add_argument('frozen_plan', type=Path)
    assess.add_argument('--bindings', type=Path, required=True)
    assess.add_argument('--output', type=Path, required=True)
    for command in (freeze, assess):
        command.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    try:
        if args.command == 'schema':
            print(json.dumps(ReferenceCampaign.model_json_schema(), indent=2))
        elif args.command == 'validate':
            print(json.dumps({'status': 'valid', 'campaign_id': validate_plan(args.plan).campaign_id}))
        elif args.command == 'freeze':
            print(json.dumps({'status': 'frozen', 'frozen_plan': str(freeze_plan(args.plan, args.output, args.measurement_root, source_root=args.source_root))}))
        else:
            bindings = json.loads(args.bindings.read_text())
            report = write_report(args.frozen_plan, bindings, args.output, source_root=args.source_root)
            print(json.dumps({'status': report['status'], 'scientific_reference_campaign': report['scientific_reference_campaign'], 'report': str(args.output)}))
            return 0 if report['status'] == 'passed' else 3
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f'Scientific reference assessment rejected: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
