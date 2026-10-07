"""Experimental training followed by both native model-driven searches.

A fitted checkpoint is durable state. Neither successful fitting nor either
single sampler is sufficient to complete the compound T1-1w recipe.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event

from .engines import artifact_inventory
from .matrix_union import native_stage
from .ml import ModelManifest
from .ml_extopt import ExtOptAllocation, run_goat_extopt
from .ml_training import run_mace_finetuning
from .models import Artifact, Attempt, utc_now
from .sampling import SampledConformer, SamplingResult
from .storage import IntegrityError, atomic_json, confined_file, digest_json, file_digest


def _verified_cached(record, store, identity: str, role: str):
    completed = [a for a in record.attempts if a.metadata.get("compound_stage_sha256") == identity
                 and a.metadata.get("role") == role and a.status == "completed"]
    if not completed:
        return None
    attempt = completed[-1]
    if (attempt.validation_status != "validated-for-protocol" or attempt.converged is not True
            or attempt.metadata.get("execution_kind") != "real" or not attempt.artifacts):
        raise IntegrityError("Completed model campaign stage lacks protocol validation")
    for artifact in attempt.artifacts:
        path = confined_file(store.run_dir, artifact.path)
        if path.stat().st_size != artifact.size_bytes or file_digest(path) != artifact.sha256:
            raise IntegrityError("Completed model campaign evidence changed")
    payload = attempt.metadata.get("stage_result")
    if (not isinstance(payload, dict) or payload.get("status") != "completed"
            or digest_json(payload) != attempt.metadata.get("stage_result_sha256")):
        raise IntegrityError("Completed model campaign result changed")
    return payload


def _verified_checkpoint(record, store, identity: str):
    """Find a completed fit whose separate held-out evaluation needs recovery."""
    for attempt in reversed(record.attempts):
        if (attempt.metadata.get("compound_stage_sha256") != identity
                or attempt.metadata.get("role") != "experimental-fine-tuning"):
            continue
        payload = attempt.metadata.get("stage_result")
        if (not isinstance(payload, dict) or payload.get("checkpoint") is None
                or payload.get("heldout_errors") is not None
                or payload.get("process", {}).get("status") != "completed"):
            continue
        if (attempt.metadata.get("execution_kind") != "real" or not attempt.artifacts
                or digest_json(payload) != attempt.metadata.get("stage_result_sha256")):
            raise IntegrityError("Retained training checkpoint lacks unchanged native evidence")
        for artifact in attempt.artifacts:
            path = confined_file(store.run_dir, artifact.path)
            if path.stat().st_size != artifact.size_bytes or file_digest(path) != artifact.sha256:
                raise IntegrityError("Retained training checkpoint evidence changed")
        return payload
    return None


@contextmanager
def _durable_stage(record, store, attempt, folder):
    """Persist exceptional exits as failed attempts without discarding native files."""
    try:
        yield
    except Exception as exc:
        attempt.status = "failed"
        attempt.converged = False
        attempt.validation_status = "rejected"
        attempt.finished_at = utc_now()
        attempt.diagnostics["exception"] = {"type": type(exc).__name__, "reason": str(exc)}
        attempt.artifacts = []
        if folder.is_dir() and not folder.is_symlink():
            try:
                attempt.artifacts = [a.model_copy(update={"path": Path(a.path).relative_to(store.run_dir).as_posix()})
                                     for a in artifact_inventory(folder)]
            except (OSError, ValueError, RuntimeError) as inventory_error:
                attempt.diagnostics["inventory_failure"] = str(inventory_error)
        record.status = "failed"
        record.metadata["termination_reason"] = "Model campaign stage failed; native evidence retained"
        store.commit(record)
        raise


def execute_ml_training(workflow, record, store, inputs, child, deadline: float,
                        cancel_event: Event | None) -> bool:
    from .matrix_workflow import _validate_ensemble, _validate_sampled_geometry
    from .ml_crest import run_crest_ml, validate_crest_ml_distribution

    if inputs.ml_model is None or inputs.ml_training_dataset is None or inputs.ml_training_options is None:
        raise ValueError("T1-1w requires the foundation manifest, authentic DFT dataset and explicit training protocol")
    if inputs.ml_search_allocation is None or workflow.base_runtime is None:
        raise ValueError("Fine-tuned native searches require actual BASE authority and explicit concurrent allocation")
    if record.request.resources.device != "gpu":
        raise ValueError("T1-1w training requires GPU execution; the CPU fallback is not a matrix implementation")
    options = inputs.ml_training_options
    if options.gpu_index != inputs.ml_gpu_index or options.gpu_memory_mb != inputs.ml_gpu_memory_mb:
        raise ValueError("Training and search must share the explicitly allocated GPU and VRAM ceiling")
    allocation = ExtOptAllocation(**inputs.ml_search_allocation.model_dump())
    allocation.validate(record.request.resources)
    # Reject the known stock CREST calculator defect before costly model fitting.
    validate_crest_ml_distribution(workflow.base_runtime.resolve_executable("crest"))
    workflow.base_runtime.resolve_executable("orca")
    seeds = inputs.ml_search_seeds or [record.request.molecule]
    _validate_ensemble(record.request.molecule, seeds, minimum=1, distinct=True)

    def remaining():
        if cancel_event is not None and cancel_event.is_set():
            record.status = "cancelled"
            record.metadata["termination_reason"] = "Experimental model campaign cancelled; completed stages retained"
            store.commit(record)
            return None
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            record.status = "timed-out"
            record.metadata["termination_reason"] = "Experimental model campaign budget exhausted; completed stages retained"
            store.commit(record)
            return None
        return record.request.resources.model_copy(update={"budget_seconds": seconds})

    if remaining() is None:
        return False
    identity = digest_json({"manifest": inputs.ml_model.model_dump(mode="json"),
                            "dataset": inputs.ml_training_dataset.model_dump(mode="json"),
                            "options": options.model_dump(mode="json"),
                            "expected_molecule": record.request.molecule.model_dump(mode="json")})
    report = _verified_cached(record, store, identity, "experimental-fine-tuning")
    if remaining() is None:
        return False
    if report is None:
        checkpoint = _verified_checkpoint(record, store, identity)
        limits = remaining()
        if limits is None:
            return False
        attempt = Attempt(run_id=record.run_id, engine="mace",
            method="MACE-heldout-evaluation" if checkpoint is not None else "MACE-multihead-fine-tuning",
            status="running", started_at=utc_now(), metadata={"role": "experimental-fine-tuning",
            "compound_stage_sha256": identity, "experimental": True, "accuracy_guarantee": None})
        record.attempts.append(attempt)
        store.commit(record)
        folder = store.run_dir / "attempts" / attempt.attempt_id
        with _durable_stage(record, store, attempt, folder):
            report = run_mace_finetuning(inputs.ml_model, inputs.ml_training_dataset, options, limits, folder,
                                         runtime=workflow.base_runtime, cancel_event=cancel_event,
                                         expected_molecule=record.request.molecule, resume_report=checkpoint)
            attempt.status, attempt.finished_at = report["status"], utc_now()
            attempt.command = (report.get("command", []) if checkpoint is not None else
                               report.get("process", {}).get("command", report.get("command", [])))
            attempt.engine_version = inputs.ml_model.package_version
            attempt.converged = report["status"] == "completed"
            attempt.validation_status = "validated-for-protocol" if attempt.converged else "not-evaluated"
            attempt.artifacts = [Artifact.model_validate(a).model_copy(update={
                "path": Path(a["path"]).relative_to(store.run_dir).as_posix()}) for a in report.get("artifacts", [])]
            attempt.metadata.update(execution_kind=report["execution_kind"], stage_result=report,
                                    stage_result_sha256=digest_json(report))
            store.commit(record)
    if report["status"] != "completed" or report.get("checkpoint") is None or report.get("heldout_errors") is None:
        record.status = report["status"] if report["status"] != "completed" else "partial"
        record.metadata["termination_reason"] = report.get("reason", "Training and independent held-out evaluation incomplete")
        store.commit(record)
        return False
    model = ModelManifest.model_validate(report["checkpoint"])
    for member in model.members:
        member.verify()
    if remaining() is None:
        return False
    record.metadata["experimental_trained_model"] = {
        "manifest": model.model_dump(mode="json"), "heldout_errors": report["heldout_errors"],
        "accuracy_guarantee": None, "experimental": True, "both_samplers_completed": False}
    store.commit(record)
    refined, candidate_ids, source_counts = [], [], []
    for sampler in ("GOAT", "CREST"):
        for index, seed in enumerate(seeds):
            if remaining() is None:
                return False
            stage_identity = digest_json({"model": model.model_dump(mode="json"), "sampler": sampler,
                "seed_index": index, "seed": seed.model_dump(mode="json"), "allocation": allocation.__dict__,
                "goat_options": inputs.goat_options.model_dump(mode="json"), "crest_profile": "crest-imtdgc-v1", "max_requests": inputs.ml_max_requests,
                "max_receipt_mb": inputs.ml_receipt_mb, "gpu_index": inputs.ml_gpu_index,
                "gpu_memory_mb": inputs.ml_gpu_memory_mb})
            saved = _verified_cached(record, store, stage_identity, "post-training-native-search")
            if remaining() is None:
                return False
            if saved is not None:
                sampled = SamplingResult.model_validate(saved)
            else:
                limits = remaining()
                if limits is None:
                    return False
                attempt = Attempt(run_id=record.run_id, engine="orca" if sampler == "GOAT" else "crest",
                    method=model.family, status="running", started_at=utc_now(), metadata={
                        "role": "post-training-native-search", "compound_stage_sha256": stage_identity,
                        "sampler": sampler, "model_manifest_sha256": digest_json(model.model_dump(mode="json"))})
                record.attempts.append(attempt)
                store.commit(record)
                folder = store.run_dir / "attempts" / attempt.attempt_id
                with _durable_stage(record, store, attempt, folder):
                    executor = run_goat_extopt if sampler == "GOAT" else run_crest_ml
                    settings = {"max_global_iterations": inputs.goat_options.max_global_iterations,
                                "deterministic": inputs.goat_options.deterministic} if sampler == "GOAT" else {"profile": "crest-imtdgc-v1"}
                    sampled = executor(seed, model, limits, folder, runtime=workflow.base_runtime, allocation=allocation,
                        gpu_index=inputs.ml_gpu_index, gpu_memory_mb=inputs.ml_gpu_memory_mb,
                        max_requests=inputs.ml_max_requests, max_receipt_mb=inputs.ml_receipt_mb,
                        cancel_event=cancel_event, **settings)
                    attempt.status, attempt.converged, attempt.finished_at = sampled.status, sampled.converged, utc_now()
                    attempt.command, attempt.engine_version, attempt.diagnostics = sampled.command, sampled.engine_version, sampled.diagnostics
                    attempt.validation_status = "validated-for-protocol" if sampled.status == "completed" and sampled.converged else "not-evaluated"
                    attempt.artifacts = [a.model_copy(update={"path": Path(a.path).relative_to(store.run_dir).as_posix()}) for a in sampled.artifacts]
                    attempt.metadata.update(sampled.metadata)
                    attempt.metadata.update(stage_result=sampled.model_dump(mode="json"),
                                            stage_result_sha256=digest_json(sampled.model_dump(mode="json")))
                    store.commit(record)
            if sampled.status != "completed" or sampled.converged is not True or not sampled.ensemble:
                record.status = sampled.status if sampled.status != "completed" else "partial"
                record.metadata["termination_reason"] = f"Post-training {sampler} did not complete its actual search"
                store.commit(record)
                return False
            source_counts.append({"sampler": sampler, "seed_index": index, "native_frames": len(sampled.ensemble)})
            for frame in sampled.ensemble:
                _validate_sampled_geometry(record.request.molecule, frame.molecule)
                result = child(f"trained-{sampler}-QM-{index:04d}-{frame.source_index:06d}", frame.molecule,
                               engine="orca", method="r2SCAN-3c")
                if result is None:
                    return False
                eligible = [c for c in result.candidates if c.status == "eligible" and c.energy_hartree is not None]
                if len(eligible) != 1:
                    raise IntegrityError("Post-training observations need genuine chemically preserved common-QM refinement")
                candidate = eligible[0]
                candidate_ids.append(candidate.candidate_id)
                refined.append(SampledConformer(molecule=candidate.molecule, energy_hartree=candidate.energy_hartree,
                    source_index=len(refined)+1, source=f"{sampler}-trained-model-common-r2SCAN-3c", metadata={
                        "candidate_id": candidate.candidate_id, "sampler": sampler, "seed_index": index,
                        "native_source_index": frame.source_index, "comparison_protocol": candidate.comparison_protocol}))
    protocols = {frame.metadata["comparison_protocol"] for frame in refined}
    if len(protocols) != 1:
        raise IntegrityError("Post-training union must use one common refinement protocol")
    unique = native_stage(workflow, record, store, refined, "cregen", deadline, cancel_event,
                          comparison_protocol=next(iter(protocols)), energy_threshold_kcal_mol=.100,
                          rotational_threshold=.01)
    if unique is None:
        return False
    if remaining() is None:
        return False
    survivors = {frame.metadata["input_metadata"]["candidate_id"] for frame in unique}
    for candidate in record.candidates:
        if candidate.candidate_id in candidate_ids and candidate.candidate_id not in survivors:
            candidate.status = "excluded-native-cregen"
    summary = {"experimental": True, "training_campaign_sha256": identity,
               "checkpoint": model.model_dump(mode="json"), "heldout_errors": report["heldout_errors"],
               "source_counts": source_counts, "retained_candidate_ids": sorted(survivors),
               "both_samplers_completed": True, "common_refinement": "native r2SCAN-3c",
               "ML_energies_reported_as_candidate_quantities": False,
               "accuracy_guarantee": None, "exhaustive": False}
    path = store.run_dir / ("experimental-trained-search-" + digest_json(summary)[:20] + ".json")
    atomic_json(path, summary)
    relative = path.relative_to(store.run_dir).as_posix()
    if not any(artifact.path == relative for artifact in record.artifacts):
        record.artifacts.append(Artifact(path=relative, sha256=file_digest(path),
                                         size_bytes=path.stat().st_size, role="experimental-trained-search"))
    record.metadata["experimental_trained_model"] = summary
    store.commit(record)
    return True
