"""Native AIMNet2 enumeration followed by genuine common QM refinement."""
from __future__ import annotations

import time
from pathlib import Path
from threading import Event

from .matrix_union import native_stage
from .ml_extopt import ExtOptAllocation, run_goat_extopt
from .models import Attempt, utc_now
from .sampling import SampledConformer, SamplingResult
from .storage import IntegrityError, confined_file, digest_json, file_digest


def _verified_sampling_cache(attempt, store) -> SamplingResult:
    if (attempt.status != 'completed' or attempt.converged is not True
            or attempt.validation_status != 'validated-for-protocol'
            or attempt.metadata.get('execution_kind') != 'real' or not attempt.artifacts):
        raise IntegrityError('Completed ML enumeration lacks real converged protocol evidence')
    payload = attempt.metadata.get('native_sampling_result')
    if not isinstance(payload, dict) or digest_json(payload) != attempt.metadata.get('native_sampling_result_sha256'):
        raise IntegrityError('Completed ML enumeration result identity changed')
    for artifact in attempt.artifacts:
        path = confined_file(store.run_dir, artifact.path)
        if path.stat().st_size != artifact.size_bytes or file_digest(path) != artifact.sha256:
            raise IntegrityError('Completed ML enumeration artifact changed')
    sampled = SamplingResult.model_validate(payload)
    if (sampled.status != 'completed' or sampled.converged is not True
            or sampled.metadata.get('execution_kind') != 'real'):
        raise IntegrityError('Completed ML enumeration result lacks native completion evidence')
    return sampled


def execute_ml_search(workflow, record, store, inputs, child, deadline: float, cancel_event: Event | None) -> bool:
    from .matrix_workflow import _validate_ensemble, _validate_sampled_geometry

    if inputs.ml_model is None or inputs.ml_model.backend != 'aimnet2':
        raise ValueError('T1-30min requires its explicit AIMNet2 checkpoint manifest; another model is not the named method')
    if inputs.ml_search_allocation is None:
        raise ValueError('Concurrent ExtOpt requires explicit ml_search_allocation within total CPU/RAM limits')
    allocation = ExtOptAllocation(**inputs.ml_search_allocation.model_dump())
    allocation.validate(record.request.resources)
    seeds = inputs.ml_search_seeds or [record.request.molecule]
    _validate_ensemble(record.request.molecule, seeds, minimum=1, distinct=True)
    frames, source_counts, candidate_ids = [], [], []
    for index, seed in enumerate(seeds):
        identity = digest_json({'seed': seed.model_dump(mode='json'), 'seed_index': index,
            'manifest': inputs.ml_model.model_dump(mode='json'), 'allocation': allocation.__dict__,
            'max_global_iterations': inputs.goat_options.max_global_iterations, 'max_requests': inputs.ml_max_requests,
            'max_receipt_mb': inputs.ml_receipt_mb, 'deterministic': inputs.goat_options.deterministic,
            'gpu_index': inputs.ml_gpu_index, 'gpu_memory_mb': inputs.ml_gpu_memory_mb})
        cached = [a for a in record.attempts if a.metadata.get('matrix_ml_search_identity') == identity and a.status == 'completed']
        if cached:
            attempt = cached[-1]
            sampled = _verified_sampling_cache(attempt, store)
        else:
            if cancel_event is not None and cancel_event.is_set():
                record.status = 'cancelled'
                return False
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                record.status = 'timed-out'
                return False
            attempt = Attempt(run_id=record.run_id, engine='orca', method='AIMNet2', status='running', started_at=utc_now(),
                              metadata={'role':'matrix-ML-enumerator', 'matrix_ml_search_identity':identity})
            record.attempts.append(attempt)
            store.commit(record)
            sampled = run_goat_extopt(seed, inputs.ml_model,
                record.request.resources.model_copy(update={'budget_seconds':max(1e-9, deadline-time.monotonic())}),
                store.run_dir/'attempts'/attempt.attempt_id, runtime=workflow.base_runtime, allocation=allocation,
                gpu_index=inputs.ml_gpu_index, gpu_memory_mb=inputs.ml_gpu_memory_mb,
                max_global_iterations=inputs.goat_options.max_global_iterations,
                deterministic=inputs.goat_options.deterministic,
                max_requests=inputs.ml_max_requests, max_receipt_mb=inputs.ml_receipt_mb, cancel_event=cancel_event)
            attempt.status, attempt.converged, attempt.finished_at = sampled.status, sampled.converged, utc_now()
            attempt.command, attempt.engine_version, attempt.diagnostics = sampled.command, sampled.engine_version, sampled.diagnostics
            attempt.metadata.update(sampled.metadata)
            attempt.metadata['native_sampling_result'] = sampled.model_dump(mode='json')
            attempt.metadata['native_sampling_result_sha256'] = digest_json(attempt.metadata['native_sampling_result'])
            attempt.artifacts = [a.model_copy(update={'path':Path(a.path).relative_to(store.run_dir).as_posix()}) for a in sampled.artifacts]
            attempt.validation_status = 'validated-for-protocol' if sampled.status == 'completed' and sampled.converged else 'not-evaluated'
            store.commit(record)
        if sampled.status != 'completed' or not sampled.converged:
            record.status = sampled.status if sampled.status != 'completed' else 'partial'
            record.metadata['termination_reason'] = 'Native ML enumeration did not complete its stopping criteria'
            return False
        source_counts.append({'seed_index':index, 'native_frames':len(sampled.ensemble)})
        for frame in sampled.ensemble:
            _validate_sampled_geometry(record.request.molecule, frame.molecule)
            # ML values remain raw enumeration observations. Every reported
            # candidate energy is actually recomputed at the same QM level.
            result = child(f'ML-QM-refine-{index:04d}-{frame.source_index:06d}', frame.molecule,
                           engine='orca', method='r2SCAN-3c')
            if result is None:
                return False
            eligible = [c for c in result.candidates if c.status == 'eligible' and c.energy_hartree is not None]
            if len(eligible) != 1:
                raise IntegrityError('ML source requires a chemically preserved, actually converged common-QM candidate')
            candidate = eligible[0]
            candidate_ids.append(candidate.candidate_id)
            frames.append(SampledConformer(molecule=candidate.molecule, energy_hartree=candidate.energy_hartree,
                source_index=len(frames)+1, source='common-r2SCAN-3c-refinement', metadata={
                    'candidate_id':candidate.candidate_id, 'seed_index':index, 'native_source_frame':frame.source_index,
                    'comparison_protocol':candidate.comparison_protocol}))
    protocols = {f.metadata['comparison_protocol'] for f in frames}
    if len(protocols) != 1:
        raise IntegrityError('ML ensemble common-QM comparison protocols are not identical')
    unique = native_stage(workflow, record, store, frames, 'cregen', deadline, cancel_event,
                          comparison_protocol=next(iter(protocols)), energy_threshold_kcal_mol=.100,
                          rotational_threshold=.01)
    if unique is None:
        return False
    surviving = {f.metadata['input_metadata']['candidate_id'] for f in unique}
    for candidate in record.candidates:
        if candidate.candidate_id in candidate_ids and candidate.candidate_id not in surviving:
            candidate.status = 'excluded-native-cregen'
    record.metadata['matrix_ml_search'] = {'source_counts':source_counts, 'retained_candidate_ids':sorted(surviving),
        'ML_energies_reported_as_candidate_quantities':False, 'common_refinement':'native r2SCAN-3c',
        'stage_A':{'RMSD_angstrom':.125,'energy_kcal_mol':.100,'rotational_fraction':.01},
        'exhaustive':False,'accuracy_claim':None,'source_resolution':'native-ML-enumeration-with-real-QM-refinement-v1'}
    return True
