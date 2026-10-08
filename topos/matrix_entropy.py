"""Matched native entropy evidence, without conflating unlike entropy terms."""
from __future__ import annotations

import time
from pathlib import Path
from threading import Event

from .entropy import run_matched_entropy, sampling_execution_timing
from .models import Artifact, Attempt, MethodSpec, Quantity
from .sampling import SamplingResult
from .storage import IntegrityError, atomic_json, digest_json, file_digest


def entropy_comparison(results: list[dict], seed_count: int) -> dict:
    """Compare only each engine's configurational term at matched temperature."""
    pairs = []
    for index in range(seed_count):
        rows = [row for row in results if row["seed_index"] == index]
        if len(rows) != 2 or {row["engine"] for row in rows} != {"goat", "crest"}:
            raise ValueError("Every declared seed requires exactly one native GOAT and CREST result")
        if len({row["seed_geometry_sha256"] for row in rows}) != 1:
            raise ValueError("GOAT and CREST entropy searches must use the same exact seed geometry")
        sampled = {row["engine"]: SamplingResult.model_validate(row["result"]) for row in rows}
        native = {key: value.metadata.get("native_entropy") for key, value in sampled.items()}
        if any(value is None for value in native.values()):
            raise ValueError("Native entropy evidence is incomplete")
        if any(value["temperature_k"] != 298.15 for value in native.values()):
            raise ValueError("Native stopping criteria require the same explicit 298.15 K temperature")
        delta = abs(native["goat"]["sconf_cal_mol_k"] - native["crest"]["sconf_cal_mol_k"])
        converged = all(value.status == "completed" and value.converged and
                        native[key]["sampling_converged"] for key, value in sampled.items())
        pairs.append({"seed_index": index, "seed_geometry_sha256": rows[0]["seed_geometry_sha256"],
                      "goat_sconf_cal_mol_k": native["goat"]["sconf_cal_mol_k"],
                      "crest_sconf_cal_mol_k": native["crest"]["sconf_cal_mol_k"],
                      "absolute_difference_cal_mol_k": delta, "native_searches_converged": converged,
                      "threshold_satisfied": converged and delta < .1,
                      "native_definitions": {key: value["definition"] for key, value in native.items()}})
    return {"temperature_k": 298.15, "pairs": pairs,
            "convergence_evidence_satisfied": bool(pairs) and all(pair["threshold_satisfied"] for pair in pairs),
            "criterion": "both native searches converged and abs(GOAT Sconf - CREST Sconf) < 0.1 cal mol^-1 K^-1 for every seed",
            "excluded_terms": ["CREST delta-Srrho", "CREST total entropy", "absolute molecular RRHO entropy"],
            "exhaustive": False, "energy_ranking_claim": False}


def execute_entropy_recipe(workflow, record, store, inputs, deadline: float, cancel_event: Event | None) -> bool:
    from .matrix_workflow import _validate_ensemble
    from .runtime import run_process

    seeds = inputs.entropy_seeds
    _validate_ensemble(record.request.molecule, seeds, minimum=1, distinct=True)
    if inputs.entropy_options.temperature_k != record.request.temperature_k:
        raise ValueError("Entropy options and request temperature must match exactly")
    if cancel_event is not None and cancel_event.is_set():
        record.status = "cancelled"
        return False
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        record.status = "timed-out"
        return False
    runtime = workflow.base_runtime
    binaries = {name: runtime.resolve_executable(name, workflow.config.executables.get(name)) if runtime else
                workflow.config.executables.get(name) for name in ("orca", "crest", "xtb")}
    runner = runtime.run_process if runtime else run_process if workflow.config.execution_backend == "development" else None
    result = run_matched_entropy(seeds, MethodSpec(engine="xtb", method="GFN2-xTB", engine_version="6.7.1",
                                 profile_id="xtb-vtight-v1"),
                                 record.request.resources.model_copy(update={"budget_seconds": remaining}),
                                 store.run_dir / "matched-entropy", options=inputs.entropy_options,
                                 orca_executable=binaries["orca"], crest_executable=binaries["crest"],
                                 xtb_executable=binaries["xtb"], process_runner=runner, cancel_event=cancel_event)
    native_attempt_ids = []
    for row in result["results"]:
        sampled = SamplingResult.model_validate(row["result"])
        invocation_started_at, invocation_finished_at = sampling_execution_timing(sampled)
        # Per-engine native directories are immutable; mutable top-level cache
        # receipts are deliberately not attached as immutable evidence.
        identifier = "attempt_entropy_" + digest_json({"seed": row["seed_index"], "result": row["result"]})[:24]
        native_attempt_ids.append(identifier)
        if any(attempt.attempt_id == identifier for attempt in record.attempts):
            continue
        artifacts = []
        for artifact in sampled.artifacts:
            path = Path(artifact.path)
            if not path.resolve().is_relative_to(store.run_dir) or path.is_symlink() or file_digest(path) != artifact.sha256:
                raise IntegrityError("Entropy native artifact is unverified or outside its run")
            artifacts.append(artifact.model_copy(update={"path": path.relative_to(store.run_dir).as_posix()}))
        native = sampled.metadata.get("native_entropy")
        attempt = Attempt(attempt_id=identifier, run_id=record.run_id, engine=sampled.engine, method=sampled.method,
                          status=sampled.status, converged=sampled.converged, engine_version=sampled.engine_version,
                          started_at=invocation_started_at, finished_at=invocation_finished_at,
                          command=sampled.command, diagnostics=sampled.diagnostics, artifacts=artifacts,
                          validation_status="validated-for-protocol" if sampled.status == "completed" and native else "not-evaluated",
                          metadata={**sampled.metadata, "role": "matrix-native-entropy", "native_engine": row["engine"],
                                    "seed_index": row["seed_index"], "seed_geometry_sha256": row["seed_geometry_sha256"]})
        if native:
            attempt.quantities.append(Quantity(name="configurational_entropy", value=native["sconf_cal_mol_k"],
                units="cal/mol/K", definition=native["definition"], method=sampled.method,
                attempt_id=identifier, validity=attempt.validation_status))
        record.attempts.append(attempt)
    if result["status"] != "completed":
        record.status = result["status"]
        record.metadata["termination_reason"] = "Matched native entropy searches did not all complete; independent completed stages retained"
        store.commit(record)
        return False
    comparison = entropy_comparison(result["results"], len(seeds))
    payload = {"schema_version": "topos-matched-entropy-comparison/0.1.0", "protocol": result["protocol"],
               "comparison": comparison, "component_attempt_ids": native_attempt_ids}
    receipt = store.run_dir / "entropy-results" / (digest_json(payload) + ".json")
    atomic_json(receipt, payload)
    artifact = Artifact(path=receipt.relative_to(store.run_dir).as_posix(), sha256=file_digest(receipt),
                        size_bytes=receipt.stat().st_size, role="native-entropy-comparison")
    if not any(item.path == artifact.path for item in record.artifacts):
        record.artifacts.append(artifact)
    record.metadata["matrix_entropy"] = {**comparison, "result_path": artifact.path}
    if not comparison["convergence_evidence_satisfied"]:
        record.status, record.metadata["termination_reason"] = "partial", "Native entropy runs completed but the matrix convergence criterion was not satisfied"
        store.commit(record)
        return False
    return True
