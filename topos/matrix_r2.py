"""R2 geometry/CP and explicitly approximate transferred DFT VPT2 correction."""
from __future__ import annotations

import time
from typing import Literal

from pydantic import Field

from .fragments import assemble_monomer_seed
from .models import Artifact, Contract, MethodSpec, Molecule
from .rotational_transfer import RotationalTransferOptions
from .science import geometry_digest, rotational_constants
from .storage import IntegrityError, atomic_json, digest_json, file_digest


class R2MonomerProvenance(Contract):
    geometry_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    method: Literal['CCSD(T)/CBS', 'fc-CCSD(T)/cc-pVTZ']
    source: str = Field(min_length=1)
    evidence_kind: Literal['cited-literature-geometry', 'declared-calculation-reference']


R2_REVIEWED_RESOLUTION = 'r2-b3lyp-d4-vpt2-transfer-v1'


class R2VPT2Options(Contract):
    semirigid_modes: Literal[True]
    displacement: float = Field(default=.05, gt=0, le=.2)
    transfer: RotationalTransferOptions


class R2AnharmonicProtocol(MethodSpec):
    operation: Literal['anharmonic'] = 'anharmonic'
    displacement: float = Field(gt=0, le=.2)
    semirigid_modes: Literal[True]
    reference_validation_policy: Literal['orca-vpt2-same-native-pose-reference-v1'] = 'orca-vpt2-same-native-pose-reference-v1'

    def native_method(self) -> MethodSpec:
        return MethodSpec.model_validate(self.model_dump(exclude={'operation', 'displacement', 'semirigid_modes',
                                                                  'reference_validation_policy'}))


def r2_reference_method(*, purpose: str = 'optimize') -> MethodSpec:
    return MethodSpec(engine='orca', method='B3LYP', dispersion='D4', purpose=purpose, basis='def2-TZVPP',
                      auxiliary_basis='def2/J', profile_id='orca-vpt2-reference-v1', engine_version='6.1.1')


def _optimize_reference(molecule, method, resources, workdir, **kwargs):
    from .engines import run_engine

    return run_engine(molecule, method, resources, workdir, operation='optimize', **kwargs)


def _calculate_vpt2(molecule, protocol, resources, workdir, **kwargs):
    from .anharmonic import run_orca_vpt2

    return run_orca_vpt2(molecule, protocol.native_method(), resources, workdir,
                         displacement=protocol.displacement, semirigid_modes=protocol.semirigid_modes, **kwargs)


def execute_r2_geometry(workflow, record, store, inputs, child, deadline, cancel_event):
    """Return a genuine stationary QZ geometry on its constrained coordinate manifold.

    A citation or calculation reference is a declared scientific input, never a
    claim that TOPOS executed the isolated high-level monomer calculation.
    """
    references, provenance = inputs.isolated_monomer_references, inputs.r2_monomer_provenance
    if len(references) < 2 or len(provenance) != len(references):
        raise ValueError('R2 requires explicit high-level isolated monomer geometries and one typed provenance declaration each')
    for molecule, source in zip(references, provenance, strict=True):
        if not source.source.strip() or digest_json(molecule.model_dump(mode='json')) != source.geometry_sha256:
            raise ValueError('R2 high-level monomer provenance must bind the exact supplied geometry and nonempty citation/reference')
    seed = assemble_monomer_seed(record.request.molecule, references)
    def within_budget():
        cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled or time.monotonic() >= deadline:
            record.status = 'cancelled' if cancelled else 'timed-out'
            record.metadata['termination_reason'] = 'R2 geometry phase stopped; native child evidence retained'
            store.commit(record)
            return False
        return True
    if not within_budget():
        return None
    constraints = {'kind':'frozen-monomers', 'profile_id':'mapping-2026',
                   'reference_source':'; '.join(p.source for p in provenance)}
    completed = child('R2-frozen-QZ-geometry', seed, engine='orca', method='wB97M-V',
                      basis='def2-QZVPP', constraints=constraints)
    if completed is None or not within_budget():
        return None
    eligible = [candidate for candidate in completed.candidates if candidate.status == 'eligible']
    if len(eligible) != 1:
        raise IntegrityError('R2 geometry requires one actual converged constrained quantum candidate')
    candidate = eligible[0]
    attempt = next(a for a in completed.attempts if a.attempt_id == candidate.attempt_id)
    diagnostics = attempt.metadata.get('constrained_optimizer', {})
    required = ['frozen_gradient_hartree_per_bohr', 'max_frozen_gradient_hartree_per_bohr',
                'max_trajectory_intrafragment_drift_angstrom']
    if (attempt.metadata.get('execution_kind') != 'real' or attempt.converged is not True
            or attempt.validation_status != 'validated-for-protocol' or any(k not in diagnostics for k in required)):
        raise IntegrityError('R2 geometry lacks native convergence, rigid-drift or residual frozen-coordinate gradient evidence')
    derivative_id = attempt.metadata.get('accepted_derivative_attempt_id')
    accepted = [native for native in completed.attempts if native.attempt_id == derivative_id]
    if len(accepted) != 1:
        raise IntegrityError('R2 constrained geometry lacks its unique accepted native derivative attempt')
    derivative = accepted[0]
    identity = [derivative.engine_version, derivative.metadata.get('executable_sha256')]
    if (derivative.engine != 'orca' or derivative.method != 'wB97M-V' or derivative.status != 'completed'
            or derivative.converged is not True or derivative.metadata.get('execution_kind') != 'real'
            or derivative.validation_status != 'validated-for-protocol' or not all(identity)
            or derivative.metadata.get('requested_method', {}).get('profile_id') != 'orca-mapping-v4.2'):
        raise IntegrityError('R2 accepted native QZ derivative lacks real validated engine identity')
    payload = {'molecule':candidate.molecule.model_dump(mode='json'), 'candidate_id':candidate.candidate_id,
        'child_run_id':completed.run_id, 'accepted_derivative_attempt_id':attempt.metadata.get('accepted_derivative_attempt_id'),
        'method':'wB97M-V', 'basis':'def2-QZVPP', 'auxiliary_basis':'def2/J', 'profile':derivative.metadata['requested_method']['profile_id'],
        'engine_identity':identity,
        'equilibrium_rotational_constants_mhz':[v*1000 if v is not None else None for v in rotational_constants(candidate.molecule)['constants_ghz']],
        'frozen_monomer_references':[r.model_dump(mode='json') for r in references],
        'monomer_provenance':[p.model_dump(mode='json') for p in provenance],
        'monomer_provenance_scope':'explicit user-provided source declarations; not newly executed high-level monomer calculations',
        'constraint_diagnostics':diagnostics, 'geometry_state':'frozen-iso',
        'full_molecule_stationary':False, 'anharmonic_correction_applied':False,
        'full_R2_completed':False, 'scope':'geometry phase only; no full-molecule minimum, VPT2 or source accuracy claim'}
    path = store.run_dir / 'R2-geometry' / (digest_json(payload)+'.json')
    atomic_json(path,payload)
    artifact = Artifact(path=path.relative_to(store.run_dir).as_posix(),sha256=file_digest(path),
                        size_bytes=path.stat().st_size,role='R2-constrained-geometry')
    if not any(a.path == artifact.path for a in record.artifacts):
        record.artifacts.append(artifact)
    record.metadata['matrix_r2_geometry'] = {**payload, 'result_path':artifact.path}
    store.commit(record)
    return candidate.molecule


def execute_r2_geometry_and_counterpoise(workflow, record, store, inputs, child, deadline, cancel_event):
    """Execute two complete R2 phases without claiming the anharmonic correction."""
    from .correlated_counterpoise import correlated_counterpoise_plan, run_r2_counterpoise

    if inputs.r2_counterpoise is None:
        raise ValueError('R2 requires an explicit ordinary DLPNO counterpoise protocol; an F12 orbital name does not select an F12 Hamiltonian')
    if workflow.base_runtime is None:
        raise ValueError('R2 correlated counterpoise requires BASE native orbital/fitting-basis export authority before geometry execution')
    # Establish physical fragment/core/ghost scope before spending resources on QZ optimization.
    correlated_counterpoise_plan(record.request.molecule, inputs.r2_counterpoise)
    molecule = execute_r2_geometry(workflow, record, store, inputs, child, deadline, cancel_event)
    if molecule is None:
        return None
    contribution = run_r2_counterpoise(workflow, record, store, molecule, inputs.r2_counterpoise, deadline, cancel_event)
    if contribution is None:
        return None
    payload = {'molecule':molecule.model_dump(mode='json'), 'geometry':record.metadata['matrix_r2_geometry'],
               'counterpoise':contribution, 'full_R2_completed':False,
               'vibrational_correction':None, 'ground_state_rotational_constants':None,
               'scope':'actual frozen-monomer QZ geometry plus ordinary DLPNO three-leg CP energy; anharmonic policy remains separate'}
    path = store.run_dir / 'R2-phases' / (digest_json(payload)+'.json')
    atomic_json(path,payload)
    artifact = Artifact(path=path.relative_to(store.run_dir).as_posix(),sha256=file_digest(path),
                        size_bytes=path.stat().st_size,role='R2-geometry-and-counterpoise')
    if not any(a.path == artifact.path for a in record.artifacts):
        record.artifacts.append(artifact)
    record.metadata['matrix_r2_phases'] = {**payload, 'result_path':artifact.path}
    store.commit(record)
    return payload


def execute_reviewed_r2(workflow, record, store, inputs, child, deadline, cancel_event) -> bool:
    """Run the selected approximate composite; frozen geometry never feeds VPT2."""
    from .anharmonic import orca_vpt2_input
    from .matrix_components import run_component
    from .method_matrix import reviewed_revision
    from .rotational_transfer import transfer_rotational_correction

    def within_budget():
        cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled or time.monotonic() >= deadline:
            record.status = 'cancelled' if cancelled else 'timed-out'
            record.metadata['termination_reason'] = 'Reviewed R2 shared budget/cancellation reached; completed components retained'
            store.commit(record)
            return False
        return True

    try:
        if not within_budget():
            return False
        if record.request.matrix_row_id != 'T3O-3h' or inputs.source_resolution != R2_REVIEWED_RESOLUTION:
            raise ValueError('R2 requires the explicit separately relaxed DFT VPT2 transfer source resolution')
        if inputs.r2_vpt2 is None:
            raise ValueError('Explicit r2_vpt2 semirigid/same-basin applicability and correction-transfer controls are required')
        options = R2VPT2Options.model_validate(inputs.r2_vpt2.model_dump())
        reference_method = r2_reference_method()
        vpt2_protocol = R2AnharmonicProtocol(**r2_reference_method(purpose='anharmonic').model_dump(),
                                            displacement=options.displacement, semirigid_modes=options.semirigid_modes)
        # Reject unsupported native derivative/isotope/domain controls before QZ and CP costs.
        orca_vpt2_input(record.request.molecule, vpt2_protocol.native_method(), record.request.resources,
                        displacement=options.displacement)
        phases = execute_r2_geometry_and_counterpoise(workflow, record, store, inputs, child, deadline, cancel_event)
        if phases is None or not within_budget():
            return False
        expected_identity = phases['counterpoise']['engine_identity']
        if phases['geometry']['engine_identity'] != expected_identity:
            raise IntegrityError('R2 frozen QZ derivative and counterpoise used different native ORCA identities')
        target = Molecule.model_validate(phases['molecule'])
        reference = run_component(workflow, record, store, 'r2-independent-dft-reference-optimize', target,
                                  reference_method, _optimize_reference, deadline, cancel_event)
        if reference is None or not within_budget():
            return False
        if reference.molecule is None:
            raise IntegrityError('R2 DFT reference optimization returned no actual geometry')
        native = run_component(workflow, record, store, 'r2-independent-dft-vpt2', reference.molecule,
                               vpt2_protocol, _calculate_vpt2, deadline, cancel_event)
        if native is None or not within_budget():
            return False
        if any([result.engine_version, result.metadata.get('executable_sha256')] != expected_identity
               for result in (reference, native)):
            raise IntegrityError('R2 CP, independent DFT optimization and VPT2 used different native ORCA identities')
        correction = transfer_rotational_correction(target, native, options.transfer)
        if not within_budget():
            return False
        payload = {
            'row_id':'T3O-3h', 'output_kind':'approximate-transferred-ground-state-rotational-constants',
            'source_resolution':R2_REVIEWED_RESOLUTION,
            'reviewed_method_revision':reviewed_revision(R2_REVIEWED_RESOLUTION),
            'geometry':phases['geometry'], 'counterpoise':phases['counterpoise'],
            'target_geometry_sha256':geometry_digest(target),
            'reference_geometry_sha256':geometry_digest(reference.molecule),
            'target_molecule':target.model_dump(mode='json'), 'reference_molecule':reference.molecule.model_dump(mode='json'),
            'reference_method':reference_method.model_dump(mode='json'), 'vpt2_protocol':vpt2_protocol.model_dump(mode='json'),
            'correction_transfer':correction, 'options':options.model_dump(mode='json'),
            'approximate_ground_state_rotational_constants_mhz':[value * 1000 for value in correction['constants_ghz']],
            'mass_matched_target_rotational_constants_mhz':[value * 1000 for value in correction['target_equilibrium_constants_ghz']],
            'formula':'B0_approx = B_R2 + (B0_DFT - Be_DFT), axis- and mass-matched',
            'component_attempt_ids':[a.attempt_id for a in record.attempts if a.status == 'completed'
                                     and str(a.metadata.get('component_key','')).startswith('r2-')],
            'engine_identity':expected_identity, 'full_reviewed_R2_completed':True,
            'original_nonstationary_vpt2_performed':False,
            'reference_full_molecule_relaxed':True, 'target_full_molecule_stationary':False,
            'approximate_composite':True, 'experimental_accuracy_claim':None,
            'numerical_transfer_uncertainty':None,
            'uncertainty_scope':'Native numerical/printed diagnostics retained; transferability error is not empirically calibrated and no numerical experimental error bar is assigned',
            'restart_scope':'Verified completed geometry/CP/reference optimization/VPT2 components reused; incomplete native VPT2 restarts in fresh scratch with previous raw attempts retained',
        }
        path = store.run_dir / 'R2-reviewed-result' / (digest_json(payload)+'.json')
        atomic_json(path,payload)
        artifact = Artifact(path=path.relative_to(store.run_dir).as_posix(),sha256=file_digest(path),
                            size_bytes=path.stat().st_size,role='matrix-reviewed-R2-result')
        if not any(a.path == artifact.path for a in record.artifacts):
            record.artifacts.append(artifact)
        record.metadata['matrix_r2'] = {**payload,'result_path':artifact.path}
        store.commit(record)
        return True
    except IntegrityError:
        raise
    except (ValueError, RuntimeError, OSError) as exc:
        record.status = 'partial' if record.attempts else 'unsupported'
        record.metadata['termination_reason'] = str(exc)
        store.commit(record)
        return False
