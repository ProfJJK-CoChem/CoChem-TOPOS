"""Finite multi-seed GOAT-DIVERSITY/CREST-v4 union and actual CC reranking."""
from __future__ import annotations

import time
from pathlib import Path
from threading import Event

from .correlated import CorrelatedMethod, run_correlated
from .entropy import SAMPLING_TIMING_SCOPE, sampling_execution_timing
from .goat import run_goat
from .matrix_components import run_component
from .matrix_union import native_stage
from .models import Artifact, Attempt, MethodSpec, utc_now
from .sampling import SampledConformer, SamplingResult, run_crest
from .storage import IntegrityError, atomic_json, digest_json, file_digest


def reranking_protocol(supplied: CorrelatedMethod | None) -> CorrelatedMethod:
    if supplied is None or supplied.method != "DLPNO-CCSD(T1)" or supplied.operation != "energy" or supplied.local_energy_decomposition:
        raise ValueError("T1-1mo requires an explicit DLPNO-CCSD(T1) energy protocol, including basis, fitting basis, core and PNO thresholds; no LED or optimization substitution")
    return supplied


def _sample(workflow, record, store, seed, index, engine, inputs, deadline, cancel_event):
    from .runtime import run_process

    method = MethodSpec(engine="xtb", method="GFN2-xTB", engine_version="6.7.1", profile_id="xtb-vtight-v1")
    identity = digest_json({"seed": seed.model_dump(mode="json"), "seed_index": index, "engine": engine,
                            "variant": "goat-diversity-v1" if engine == "goat" else "crest-v4-v1",
                            "method": method.model_dump(mode="json"), "options": inputs.goat_options.model_dump(mode="json")})
    previous = [a for a in record.attempts if a.metadata.get("matrix_diversity_identity") == identity and a.status == "completed"]
    if previous:
        attempt = previous[-1]
        if digest_json(attempt.metadata['native_sampling_result']) != attempt.metadata['native_sampling_result_sha256']:
            raise IntegrityError('Completed diversity sampling result identity changed')
        sampled = SamplingResult.model_validate(attempt.metadata["native_sampling_result"])
        if (attempt.started_at, attempt.finished_at) != sampling_execution_timing(sampled):
            raise IntegrityError("Completed diversity dispatch timestamps differ from retained native evidence")
        for artifact in attempt.artifacts:
            path = store.run_dir / artifact.path
            if path.is_symlink() or not path.resolve().is_relative_to(store.run_dir) or not path.is_file() or file_digest(path) != artifact.sha256:
                raise IntegrityError("Completed diversity search artifact changed")
        return sampled
    if cancel_event is not None and cancel_event.is_set():
        record.status = "cancelled"
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        record.status = "timed-out"
        return None
    runtime = workflow.base_runtime
    runner = runtime.run_process if runtime else run_process if workflow.config.execution_backend == "development" else None
    engine_name = "orca" if engine == "goat" else "crest"
    executable = runtime.resolve_executable(engine_name, workflow.config.executables.get(engine_name)) if runtime else workflow.config.executables.get(engine_name)
    xtb = runtime.resolve_executable("xtb", workflow.config.executables.get("xtb")) if runtime else workflow.config.executables.get("xtb")
    attempt = Attempt(run_id=record.run_id, engine=engine_name, method="GFN2-xTB", status="running", started_at=utc_now(),
                      metadata={"role": "matrix-diversity-search", "matrix_diversity_identity": identity,
                                "seed_index": index, "sampling_engine": engine})
    record.attempts.append(attempt)
    store.commit(record)
    folder = store.run_dir / "attempts" / attempt.attempt_id
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        attempt.status = record.status = "timed-out"
        attempt.finished_at = utc_now()
        store.commit(record)
        return None
    limits = record.request.resources.model_copy(update={"budget_seconds": remaining})
    if engine == "goat":
        result = run_goat(seed, method, limits, folder, executable=executable, xtb_executable=xtb,
                          profile="goat-diversity-v1", energy_window_kcal_mol=60,
                          deterministic=inputs.goat_options.deterministic,
                          max_global_iterations=inputs.goat_options.max_global_iterations,
                          process_runner=runner, cancel_event=cancel_event)
    else:
        result = run_crest(seed, method, limits, folder, executable=executable, xtb_executable=xtb,
                          profile="crest-v4-v1", energy_window_kcal_mol=60,
                          process_runner=runner, cancel_event=cancel_event)
    attempt.finished_at = utc_now()
    result.metadata["execution_timing"] = {
        "started_at": attempt.started_at, "finished_at": attempt.finished_at, "scope": SAMPLING_TIMING_SCOPE}
    sampling_execution_timing(result)
    attempt.status, attempt.converged = result.status, result.converged
    attempt.command, attempt.engine_version, attempt.diagnostics = result.command, result.engine_version, result.diagnostics
    attempt.metadata.update(result.metadata)
    attempt.metadata["native_sampling_result"] = result.model_dump(mode="json")
    attempt.metadata["native_sampling_result_sha256"] = digest_json(attempt.metadata["native_sampling_result"])
    attempt.artifacts = [a.model_copy(update={"path": Path(a.path).relative_to(store.run_dir).as_posix()}) for a in result.artifacts]
    attempt.validation_status = "validated-for-protocol" if result.status == "completed" else "not-evaluated"
    store.commit(record)
    if result.status != "completed" or not result.converged:
        record.status = result.status if result.status != "completed" else "partial"
        record.metadata["termination_reason"] = "A required diversity search did not meet its native finite stopping criteria"
        return None
    return result


def execute_diversity_recipe(workflow, record, store, inputs, child, deadline: float, cancel_event: Event | None) -> bool:
    from .matrix_workflow import _validate_ensemble, _validate_sampled_geometry

    protocol = reranking_protocol(inputs.correlated_protocol)
    _validate_ensemble(record.request.molecule, inputs.topology_seeds, minimum=3, distinct=True)
    frames, counts = [], []
    for index, seed in enumerate(inputs.topology_seeds):
        for engine in ("goat", "crest"):
            sampled = _sample(workflow, record, store, seed, index, engine, inputs, deadline, cancel_event)
            if sampled is None:
                return False
            counts.append({"seed_index": index, "engine": engine, "native_frames": len(sampled.ensemble)})
            for source in sampled.ensemble:
                _validate_sampled_geometry(record.request.molecule, source.molecule)
                # All native SloppyOpt/v4 structures acquire one common actual
                # geometry/energy protocol before duplicate comparison.
                task = f"diversity-refine-{index:04d}-{engine}-{source.source_index:06d}"
                refined = child(task, source.molecule, engine="xtb", method="GFN2-xTB", include_candidates=False)
                if refined is None:
                    return False
                eligible = [c for c in refined.candidates if c.status == "eligible" and c.energy_hartree is not None]
                if len(eligible) != 1:
                    raise IntegrityError("Diversity refinement lacks one validated stationary candidate")
                candidate = eligible[0]
                frames.append(SampledConformer(molecule=candidate.molecule, energy_hartree=candidate.energy_hartree,
                              source_index=len(frames) + 1, source=engine.upper(),
                              metadata={"source_seed": index, "source_frame": source.source_index,
                                        "refinement_run_id": refined.run_id, "comparison_protocol": candidate.comparison_protocol}))
    protocols = {frame.metadata["comparison_protocol"] for frame in frames}
    if len(protocols) != 1:
        raise IntegrityError("Diversity union refinement energy protocols are incompatible")
    unique = native_stage(workflow, record, store, frames, "cregen", deadline, cancel_event,
                          comparison_protocol=next(iter(protocols)), energy_window_kcal_mol=60)
    if unique is None:
        return False
    ranked = []
    for index, frame in enumerate(unique):
        result = run_component(workflow, record, store, f"diversity-CC-{index:06d}", frame.molecule,
                               protocol, run_correlated, deadline, cancel_event)
        if result is None:
            return False
        ranked.append({"molecule": frame.molecule.model_dump(mode="json"), "electronic_energy_hartree": result.energy_hartree,
                       "source_refinement": frame.metadata, "engine_version": result.engine_version,
                       "executable_sha256": result.metadata["executable_sha256"]})
    if not ranked or len({(item["engine_version"], item["executable_sha256"]) for item in ranked}) != 1:
        raise IntegrityError("Coupled-cluster reranking requires one verified executable identity and nonempty ensemble")
    ranked.sort(key=lambda item: item["electronic_energy_hartree"])
    minimum = ranked[0]["electronic_energy_hartree"]
    for item in ranked:
        item["relative_electronic_energy_hartree"] = item["electronic_energy_hartree"] - minimum
    payload = {"schema_version": "topos-diversity-reranking/0.1.0", "source_counts": counts,
               "native_union_count": len(frames), "common_refined_unique_count": len(unique),
               "protocol": protocol.model_dump(mode="json"), "ranked": ranked,
               "geometry_level": "GFN2-xTB vtight", "energy_level": "explicit DLPNO-CCSD(T1) protocol",
               "minimum_hessian_verified": False, "exhaustive": False,
               "scope": "all explicitly supplied seeds and both requested native variants; finite sampling does not establish completeness"}
    path = store.run_dir / "diversity-results" / (digest_json(payload) + ".json")
    atomic_json(path, payload)
    artifact = Artifact(path=path.relative_to(store.run_dir).as_posix(), sha256=file_digest(path), size_bytes=path.stat().st_size,
                        role="matrix-coupled-cluster-reranking")
    if not any(a.path == artifact.path for a in record.artifacts):
        record.artifacts.append(artifact)
    record.metadata["matrix_diversity"] = {**payload, "result_path": artifact.path}
    return True
