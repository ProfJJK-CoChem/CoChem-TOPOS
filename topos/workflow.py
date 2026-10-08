"""One local, auditable workflow shared by BASE, CLI and the optional UI.

Every engine invocation has its own immutable input and fresh scratch directory.
Search is finite seeded jiggle–quench, not an exhaustive conformer claim.
"""

from __future__ import annotations

import importlib.metadata
import logging
import math
import platform
import subprocess
import time
from pathlib import Path
from threading import Event
from typing import Any

import numpy as np
from filelock import FileLock

from . import __version__
from .budget import ExecutionBudget
from .capabilities import capability_report, validate_route
from .chemistry import classify_fragments, molecular_graph, to_xyz, validate_chemistry
from .config import SystemConfig, load_config
from .engines import EngineResult, run_engine
from .models import (
    Artifact,
    Attempt,
    Candidate,
    MethodSpec,
    Molecule,
    Quantity,
    RunRecord,
    RunRequest,
    utc_now,
)
from .references import method_references
from .storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest

LOGGER = logging.getLogger("cochem.workflow")


def software_provenance() -> dict[str, Any]:
    root = Path(__file__).resolve().parent.parent
    result: dict[str, Any] = {
        "name": "CoChem-TOPOS",
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "commit": None,
        "dirty": None,
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ["numpy", "scipy", "networkx", "pydantic", "mendeleev", "h5py"]
        },
    }
    if (root / ".git").exists():
        try:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            state = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if head.returncode == 0:
                result["commit"] = head.stdout.strip()
            if state.returncode == 0:
                result["dirty"] = bool(state.stdout.strip())
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["revision_lookup"] = type(exc).__name__
    else:
        result["revision_lookup"] = "installed distribution; source commit unavailable"
    # A dirty checkout cannot be identified by HEAD alone. Hash executing sources.
    result["source_files"] = {
        p.relative_to(root).as_posix(): file_digest(p)
        for p in sorted((root / "topos").rglob("*.py"))
    }
    return result


def _artifact(path: Path, run_dir: Path, role: str) -> Artifact:
    return Artifact(
        path=path.relative_to(run_dir).as_posix(),
        sha256=file_digest(path),
        size_bytes=path.stat().st_size,
        role=role,
    )


def _topology_preserved(before: Molecule, after: Molecule) -> bool:
    """Explicit atom order is fixed by engine parsing; distance graph guards reactions."""
    # Re-infer output bonds even when an input bond list exists: copying the input
    # graph into an optimized geometry would conceal bond breaking/proton transfer.
    a = Molecule.model_validate({**before.model_dump(), "bonds": []})
    b = Molecule.model_validate({**after.model_dump(), "bonds": []})
    ga, gb = molecular_graph(a), molecular_graph(b)
    return set(map(frozenset, ga.edges)) == set(map(frozenset, gb.edges))


class _EvaluationStopped(RuntimeError):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status


class Workflow:
    def __init__(
        self, output_root: str | Path | None = None, *, config: SystemConfig | None = None
    ) -> None:
        self.config = config if config is not None else load_config()
        self.base_runtime = None
        self.output_root = Path(output_root or self.config.output_root).expanduser().resolve()
        source_root = Path(__file__).resolve().parent.parent
        if (source_root / ".git").exists() and self.output_root.is_relative_to(source_root):
            raise ValueError(
                "Run scratch and scientific records must be outside the source repository"
            )
        self.output_root.mkdir(parents=True, exist_ok=True)

    def run(
        self, request: RunRequest | dict[str, Any], *, cancel_event: Event | None = None,
        invocation_budget_seconds: float | None = None,
        invocation_budget_context: dict[str, Any] | None = None,
    ) -> RunRecord:
        preparation_started = time.monotonic()
        if invocation_budget_seconds is not None and (
            isinstance(invocation_budget_seconds, bool)
            or not isinstance(invocation_budget_seconds, (int, float))
            or not math.isfinite(invocation_budget_seconds) or invocation_budget_seconds < 0
        ):
            raise ValueError("Initial invocation allocation must be finite and nonnegative")
        request = RunRequest.model_validate(
            request.model_dump(mode="python") if isinstance(request, RunRequest) else request
        )
        if invocation_budget_seconds is not None and invocation_budget_seconds > request.budget_seconds:
            raise ValueError("Initial invocation allocation cannot increase the declared scientific budget")
        context_metadata = {}
        if invocation_budget_context is not None:
            if (not isinstance(invocation_budget_context, dict)
                    or set(invocation_budget_context) != {"hosted_budget_control", "budget_accounting"}
                    or not isinstance(invocation_budget_context["hosted_budget_control"], dict)
                    or invocation_budget_context["budget_accounting"] is not None
                    and not isinstance(invocation_budget_context["budget_accounting"], dict)):
                raise ValueError("Invocation budget context must contain its separate control and accounting")
            context_metadata = {
                "hosted_budget_control": invocation_budget_context["hosted_budget_control"],
                "hosted_budget_control_sha256": digest_json(invocation_budget_context["hosted_budget_control"]),
            }
            if invocation_budget_context["budget_accounting"] is not None:
                context_metadata["hosted_budget_accounting"] = invocation_budget_context["budget_accounting"]
        if request.calculation_environment in {"github-actions", "github-actions-hosted"}:
            if invocation_budget_seconds is not None or invocation_budget_context is not None:
                raise ValueError("Initial invocation controls apply only inside the assigned local worker")
            from .remote_workflow import run_remote

            return run_remote(self, request, cancel_event=cancel_event)
        allocated = request.budget_seconds if invocation_budget_seconds is None else max(
            0.0, invocation_budget_seconds - (time.monotonic() - preparation_started)
        )
        invocation_budget = ExecutionBudget(
            allocated if allocated > 0 else request.budget_seconds, scope=request.budget_scope,
            include_queue=request.include_queue_in_budget,
        )
        record = RunRecord(request=request, metadata=context_metadata)
        run_dir = self.output_root / record.run_id
        run_dir.mkdir(exist_ok=False)
        record.metadata.update(
            {
                "run_dir": str(run_dir),
                "input_sha256": digest_json(request.molecule.model_dump(mode="json")),
                "request_sha256": digest_json(request.model_dump(mode="json")),
                "software": software_provenance(),
                "citations": method_references(request.engine, request.method),
                "capability_profile": capability_report(),
                "budget_scope": "workflow invocation; queue is local preparation before execution; execution includes chemistry preflight and intermediate commits; final evidence commit may outlive deadline",
                "queue_time_in_budget": request.include_queue_in_budget,
                "algorithm": "external-starting-geometries" if request.starting_geometries else request.search_algorithm
                if request.purpose == "search"
                else request.purpose,
                "sampling_complete": False,
                "stationary_point_classification": "not-evaluated: no frequency Hessian",
            }
        )
        if invocation_budget_seconds is not None:
            record.metadata.update(invocation_budget_override_seconds=invocation_budget_seconds,
                                   invocation_budget_allocated_seconds=allocated,
                                   invocation_budget_override_policy="reduce only this invocation; immutable request remains unchanged")
        atomic_json(run_dir / "request.json", request.model_dump(mode="json"))
        (run_dir / "input.xyz").write_text(to_xyz(request.molecule), encoding="utf-8")
        record.artifacts.extend(
            [
                _artifact(run_dir / "request.json", run_dir, "request"),
                _artifact(run_dir / "input.xyz", run_dir, "input-geometry"),
            ]
        )
        store = RunStore(run_dir)
        store.commit(record)
        with FileLock(str(run_dir / ".execution.lock"), timeout=0):
            if allocated == 0:
                record.status = "timed-out"
                record.metadata.update(execution_kind="no-execution", invocation_started_at=None,
                                       termination_reason="Queue and setup exhausted the scientific budget before execution")
                expired = self._finish(record, store, invocation_budget)
                # ExecutionBudget requires a positive deadline. This unstarted
                # object is only a terminal clock for the zero-allocation case;
                # its accounting must retain the actual zero execution budget.
                expired.metadata["budget_accounting"]["budget_seconds"] = 0.0
                store.commit(expired)
                return expired
            return self._execute(record, store, cancel_event, invocation_budget=invocation_budget)

    def resume(self, run_dir: str | Path, *, cancel_event: Event | None = None,
               invocation_budget_seconds: float | None = None) -> RunRecord:
        if invocation_budget_seconds is not None and (
            isinstance(invocation_budget_seconds, bool)
            or not math.isfinite(invocation_budget_seconds) or invocation_budget_seconds <= 0
        ):
            raise ValueError("Continuation budget must be finite and positive")
        store = RunStore(run_dir)
        if store.run_dir.parent != self.output_root:
            raise ValueError("Resume run directory must belong to this output root")
        with FileLock(str(store.run_dir / ".execution.lock"), timeout=0):
            stored = store.recover()
            record = RunRecord.model_validate(stored)
            if record.request.calculation_environment in {"github-actions", "github-actions-hosted"}:
                from .remote_workflow import resume_remote

                return resume_remote(self, record, store, cancel_event=cancel_event,
                                     invocation_budget_seconds=invocation_budget_seconds,
                                     original_request=stored["request"])
            if (
                digest_json(stored["request"])
                != record.metadata.get("request_sha256")
            ):
                raise IntegrityError("Saved request differs from immutable request identity")
            if (
                digest_json(record.request.molecule.model_dump(mode="json"))
                != record.metadata.get("input_sha256")
            ):
                raise IntegrityError("Saved molecule differs from immutable input identity")
            if record.status == "completed":
                return record
            current_request = record.request.model_dump(mode="json")
            if current_request != stored["request"]:
                record.metadata["request_default_expansion"] = {
                    "original_sha256": digest_json(stored["request"]),
                    "view_sha256": digest_json(current_request),
                    "added_fields": sorted(set(current_request) - set(stored["request"])),
                    "policy": "validate original request with current optional defaults; preserve stored original",
                }
            invocation_budget = ExecutionBudget(
                record.request.budget_seconds if invocation_budget_seconds is None else invocation_budget_seconds,
                scope=record.request.budget_scope,
                include_queue=record.request.include_queue_in_budget,
            )
            record.metadata.setdefault("continuations", []).append(
                {
                    "requested_at": utc_now(),
                    "previous_status": record.status,
                    "previous_termination_reason": record.metadata.get("termination_reason"),
                    "budget_seconds": record.request.budget_seconds if invocation_budget_seconds is None else invocation_budget_seconds,
                    "software": software_provenance(),
                }
            )
            # Resume only verified committed results. Interrupted attempts become
            # explicit failed history and retries get new IDs/directories.
            for attempt in record.attempts:
                if attempt.status in {"queued", "running"}:
                    attempt.status = "failed"
                    attempt.finished_at = utc_now()
                    attempt.diagnostics["reason"] = "interrupted before a scientific result commit"
            record.status = "queued"
            return self._execute(record, store, cancel_event, invocation_budget=invocation_budget)

    def _execute(self, record: RunRecord, store: RunStore, cancel_event: Event | None,
                 *, invocation_budget: ExecutionBudget | None = None) -> RunRecord:
        request = record.request
        start = invocation_budget if invocation_budget is not None else ExecutionBudget(
            request.budget_seconds, scope=request.budget_scope,
            include_queue=request.include_queue_in_budget,
        )
        record.status = "running"
        record.metadata.pop("termination_reason", None)
        record.metadata.pop("electronic_weights_by_protocol", None)
        record.metadata.pop("comparison_warning", None)
        try:
            deadline = start.start()
        except TimeoutError:
            record.status = "timed-out"
            record.metadata["termination_reason"] = "Workflow budget expired during local input preparation/queueing"
            record.metadata["invocation_started_at"] = None
            return self._finish(record, store, start)
        record.metadata["invocation_started_at"] = utc_now()
        route_problem = validate_route(request, self.config)
        if route_problem:
            record.status, reason = route_problem
            record.metadata["termination_reason"] = reason
            return self._finish(record, store, start)
        if self.config.execution_backend == "base":
            from .base_integration import BaseRuntime

            try:
                self.base_runtime = BaseRuntime(registry_path=self.config.base_registry_path)
                if request.device == "gpu" and request.purpose == "matrix":
                    from .ml import ModelManifest

                    manifest = ModelManifest.model_validate(request.matrix_inputs["ml_model"])
                    self.base_runtime.validate_resources(
                        request.resources, engine=manifest.backend,
                        gpu_index=request.matrix_inputs.get("ml_gpu_index"),
                        gpu_memory_mb=request.matrix_inputs.get("ml_gpu_memory_mb"),
                    )
                else:
                    self.base_runtime.validate_resources(request.resources)
                engines = set() if request.purpose == "matrix" else {request.engine}
                if request.search_algorithm in {"crest", "union"}:
                    engines.update({"crest", "xtb"})
                elif request.search_algorithm == "abcluster":
                    engines.add("abcluster")
                for engine in engines:
                    self.config.executables[engine] = self.base_runtime.resolve_executable(
                        engine, self.config.executables.get(engine)
                    )
                record.metadata["execution_provider"] = "CoChem-BASE"
                record.metadata["execution_authority"] = self.base_runtime.provenance()
            except (ValueError, RuntimeError, OSError, ImportError) as exc:
                record.status = "unavailable"
                record.metadata["termination_reason"] = str(exc)
                return self._finish(record, store, start)
        else:
            record.metadata["execution_provider"] = "explicit-development-runtime; not mandatory ecosystem acceptance"
        if request.matrix_row_id:
            from .method_matrix import load_catalog, resolve_row

            row = resolve_row(request.matrix_row_id, product=request.matrix_product)
            record.metadata["matrix_binding"] = {
                "row_id": request.matrix_row_id,
                "catalog_revision": load_catalog().revision,
                "row": row.model_dump(mode="json") if hasattr(row, "model_dump") else vars(row),
            }
        try:
            input_validation = validate_chemistry(request.molecule)
            triage = classify_fragments(request.molecule)
        except ValueError as exc:
            record.status, record.validation_status = "failed", "rejected"
            record.metadata["termination_reason"] = str(exc)
            return self._finish(record, store, start)
        record.metadata["input_validation"] = input_validation
        record.metadata["fragment_triage"] = triage
        from .science import validate_stereochemical_preservation

        stereo = validate_stereochemical_preservation(request.molecule, request.molecule)
        record.metadata["input_stereochemistry"] = stereo
        if stereo["status"] != "preserved":
            record.status, record.validation_status = "unsupported", "human-review"
            record.metadata["termination_reason"] = (
                "Input stereochemistry is ambiguous, inconsistent, or outside the supported signed-tetrahedral convention"
            )
            return self._finish(record, store, start)
        if input_validation["status"] != "valid" or triage["classification"] == "unresolved":
            record.status, record.validation_status = "unsupported", "human-review"
            record.metadata["termination_reason"] = (
                "Input chemistry or fragment classification requires resolution before execution"
            )
            return self._finish(record, store, start)
        if request.constraints:
            from .constraints import validate_constraints

            try:
                validate_constraints(request.molecule, request.constraints)
            except (ValueError, TypeError) as exc:
                record.status = "unsupported"
                record.metadata["termination_reason"] = str(exc)
                return self._finish(record, store, start)
        # Nested budgets never renew the enclosing workflow deadline. The
        # ensemble includes native sampling, every refinement and comparison;
        # a geometry includes the complete optimizer/derivative campaign, not
        # a fresh allowance for each gradient evaluation.
        ensemble_started = time.monotonic()
        ensemble_limit = min(
            max(0.0, deadline - ensemble_started),
            request.per_ensemble_budget_seconds
            if request.per_ensemble_budget_seconds is not None else float("inf"),
        )
        deadline = ensemble_started + ensemble_limit
        record.metadata["nested_budget_accounting"] = {
            "invocation_started_at": record.metadata["invocation_started_at"],
            "semantics": "new invocation allocations; completed validated subjobs are reused; final evidence commit is outside execution deadlines",
            "ensemble": {
                "requested_seconds": request.per_ensemble_budget_seconds,
                "allocated_seconds": ensemble_limit,
                "started_at_execution_seconds": start.snapshot()["execution_seconds"],
                "scope": "sampling, refinements and comparison, bounded by workflow",
            },
            "geometries": [],
        }
        if request.purpose == "matrix":
            from .matrix_workflow import execute_matrix

            execute_matrix(self, record, store, deadline, cancel_event)
            return self._finish(record, store, start)
        if request.purpose in {"frequency", "thermochemistry", "association"}:
            from .advanced_workflow import execute_advanced

            geometry_started = time.monotonic()
            geometry_deadline = deadline
            if request.purpose != "association" and request.per_geometry_budget_seconds is not None:
                geometry_deadline = min(deadline, geometry_started + request.per_geometry_budget_seconds)
            execute_advanced(self, record, store, geometry_deadline, cancel_event)
            if request.purpose != "association":
                if time.monotonic() >= geometry_deadline and record.status == "completed":
                    record.status = "partial" if record.candidates else "timed-out"
                    record.metadata["termination_reason"] = "Geometry derivative-campaign budget exhausted"
                record.metadata["nested_budget_accounting"]["geometries"].append({
                    "task": request.purpose,
                    "requested_seconds": request.per_geometry_budget_seconds,
                    "allocated_seconds": max(0.0, geometry_deadline - geometry_started),
                    "elapsed_seconds": time.monotonic() - geometry_started,
                    "status": record.status,
                    "scope": "optimization plus all physical-Hessian derivative evaluations and thermal analysis",
                })
            return self._finish(record, store, start)
        plans = self._sample_plan(record, store, deadline, cancel_event)
        if plans is None:
            return self._finish(record, store, start)
        target = len(plans)
        completed_indices = {
            c.metadata["sample_index"]
            for c in record.candidates
            if c.metadata.get("proposal_processed", c.metadata.get("calculation_completed"))
        }
        store.commit(record)
        interrupted: str | None = None
        for index in range(target):
            if index in completed_indices:
                continue
            if cancel_event is not None and cancel_event.is_set():
                interrupted = "cancelled"
                break
            if time.monotonic() >= deadline:
                interrupted = "timed-out"
                break
            seed = Molecule.model_validate(plans[index]["molecule"])
            source = plans[index]["source"]
            old = [a for a in record.attempts if a.metadata.get("sample_index") == index]
            parent = old[-1].attempt_id if old else None
            try:
                validation = validate_chemistry(seed)
            except ValueError as exc:
                validation = {"status": "invalid", "issues": [str(exc)]}
            if validation["status"] != "valid":
                record.candidates.append(
                    Candidate(
                        molecule=seed,
                        status="rejected",
                        sources=[source],
                        metadata={
                            "sample_index": index,
                            "calculation_completed": False,
                            "proposal_processed": True,
                            "reason": "perturbed input is physically suspect",
                            "validation": validation,
                        },
                    )
                )
                store.commit(record)
                continue
            geometry_started = time.monotonic()
            geometry_deadline = min(
                deadline, geometry_started + request.per_geometry_budget_seconds
                if request.per_geometry_budget_seconds is not None else deadline,
            )
            if request.constraints and request.purpose in {"search", "optimize"}:
                attempt, result = self._constrained(
                    record, store, seed, index, parent, geometry_deadline, cancel_event
                )
            else:
                operation = "optimize" if request.purpose == "search" else request.purpose
                attempt, result = self._engine_attempt(
                    record, store, seed, index, parent, geometry_deadline, cancel_event, operation
                )
            geometry_elapsed = time.monotonic() - geometry_started
            if result.status == "completed" and time.monotonic() >= geometry_deadline:
                result.status, result.converged = "timed-out", False
                result.diagnostics["reason"] = "Geometry budget exhausted before result validation completed"
                attempt.status, attempt.converged = "timed-out", False
                attempt.validation_status = "not-evaluated"
                attempt.diagnostics["reason"] = result.diagnostics["reason"]
                for quantity in attempt.quantities:
                    quantity.validity = "not-evaluated"
            geometry_receipt = {
                "sample_index": index, "attempt_id": attempt.attempt_id,
                "requested_seconds": request.per_geometry_budget_seconds,
                "allocated_seconds": max(0.0, geometry_deadline - geometry_started),
                "elapsed_seconds": geometry_elapsed, "status": result.status,
                "scope": "one complete geometry operation, including all constrained optimizer gradients",
            }
            record.metadata["nested_budget_accounting"]["geometries"].append(geometry_receipt)
            attempt.metadata["geometry_budget"] = geometry_receipt
            candidate = self._candidate(record, seed, attempt, result, index, source)
            candidate.metadata["sampling_origin"] = {
                key: value for key, value in plans[index].items() if key != "molecule"
            }
            attempt.metadata["sampling_origin"] = candidate.metadata["sampling_origin"]
            record.candidates.append(candidate)
            if (result.status == "timed-out" and geometry_deadline < deadline
                    and time.monotonic() < deadline):
                # One expensive proposal cannot consume every later proposal's
                # allocation. Keep its incomplete evidence and continue within
                # the same finite ensemble/workflow budget.
                candidate.metadata["geometry_budget_exhausted"] = True
                store.commit(record)
                continue
            if result.status in {"unavailable", "unsupported", "cancelled", "timed-out"}:
                interrupted = result.status
                record.metadata["termination_reason"] = result.diagnostics.get(
                    "reason", result.status
                )
                store.commit(record)
                break
            store.commit(record)
        comparison_status = self._compare(record, deadline=deadline, cancel_event=cancel_event)
        if comparison_status != "completed" and interrupted is None:
            interrupted = comparison_status
        eligible = [c for c in record.candidates if c.status == "eligible"]
        done = {
            c.metadata.get("sample_index")
            for c in record.candidates
            if c.metadata.get("proposal_processed", c.metadata.get("calculation_completed"))
        }
        failures = any(
            c.status
            in {"partial", "failed", "unavailable", "unsupported", "cancelled", "timed-out"}
            for c in record.candidates
            if c.metadata.get("sample_index") not in done
        )
        if interrupted:
            record.status = (
                "partial"
                if eligible and interrupted in {"unavailable", "unsupported"}
                else interrupted
            )
        elif len(done) == target and eligible:
            record.status = "partial" if failures else "completed"
        else:
            record.status = "partial" if eligible else (
                "timed-out" if any(c.metadata.get("geometry_budget_exhausted") for c in record.candidates)
                else "failed"
            )
        if record.metadata.get("sampler_pending") and record.status == "completed":
            record.status = "partial"
        if (record.status in {"partial", "timed-out"}
                and any(c.metadata.get("geometry_budget_exhausted")
                        and c.metadata.get("sample_index") not in done for c in record.candidates)):
            record.metadata.setdefault(
                "termination_reason", "One or more geometry budgets exhausted; incomplete observations were retained"
            )
        record.validation_status = "human-review" if eligible else "rejected"
        record.metadata["search_summary"] = {
            "requested_samples": target,
            "processed_samples": len(done),
            "completed_samples": len({
                c.metadata.get("sample_index") for c in record.candidates
                if c.metadata.get("calculation_completed")
            }),
            "unique_eligible": len(eligible),
            "uniqueness": "retained by conservative tests; unresolved comparisons are kept separately",
            "candidate_observations": len(record.candidates),
            "exhaustive": False,
        }
        if eligible and comparison_status == "completed" and not record.metadata["deduplication"]["inconclusive_comparisons"]:
            from .science import ensemble_populations

            protocols = sorted({c.comparison_protocol for c in eligible})
            record.metadata["electronic_weights_by_protocol"] = {
                protocol: ensemble_populations(
                    [c for c in eligible if c.comparison_protocol == protocol],
                    temperature_k=request.temperature_k,
                    quantity="electronic",
                )
                for protocol in protocols
            }
            record.metadata["electronic_weights_status"] = "sampled-ensemble electronic weights; not Gibbs populations"
            if len(protocols) > 1:
                record.metadata["comparison_warning"] = (
                    "Engine/protocol revisions differ; ensembles and energy windows are partitioned and require common-level refinement before union."
                )
        else:
            record.metadata["electronic_weights_status"] = (
                "not-computed: no eligible ensemble or incomplete/unresolved identity comparisons"
            )
        return self._finish(record, store, start)

    def _sample_plan(
        self, record: RunRecord, store: RunStore, deadline: float, cancel_event: Event | None
    ) -> list[dict[str, Any]] | None:
        """Freeze source observations before common-level refinement; reuse on resume."""
        if "sample_plan" in record.metadata and not record.metadata.get("sampler_pending"):
            return record.metadata["sample_plan"]
        request = record.request
        if request.starting_geometries:
            sources = request.metadata.get("external_starting_states", [])
            refinement_sources = [source for source in sources if isinstance(source, dict)
                                  and source.get("entrypoint") == "refinement"] if isinstance(sources, list) else []
            indices = refinement_sources[-1].get("source_frames", []) if refinement_sources else []
            if not isinstance(indices, list) or len(indices) != len(request.starting_geometries):
                indices = [None] * len(request.starting_geometries)
            plans = [{"molecule": molecule.model_dump(mode="json"), "source": "EXTERNAL_START",
                      "source_frame": indices[index], "starting_geometry_index": index + 1,
                      "source_provenance": sources,
                      "energy_definition": "no accepted energy; imported geometry requires the requested real calculation"}
                     for index, molecule in enumerate(request.starting_geometries)]
            record.metadata["sample_plan"] = plans
            record.metadata["refinement_cap_scope"] = "all explicitly provided starting geometries; native enumeration was not requested"
            record.metadata["enumeration_scope"] = "external starting geometries; no new jiggle/CREST/GOAT search"
            return plans
        cached_plan = record.metadata.get("sample_plan")
        plans = list(cached_plan) if cached_plan is not None else [
            {"molecule": request.molecule.model_dump(mode="json"), "source": "INITIAL_SEED"}
        ]
        if request.purpose != "search":
            record.metadata["sample_plan"] = plans
            return plans
        if cached_plan is None and request.search_algorithm in {"jiggle-quench", "union"}:
            plans.extend(
                {
                    "molecule": self._seed(request, index).model_dump(mode="json"),
                    "source": "JIGGLE_QUENCH",
                }
                for index in range(1, request.n_candidates)
            )
        if request.search_algorithm in {"crest", "union", "abcluster"}:
            from .sampling import run_crest

            classical = request.search_algorithm == "abcluster"
            sampler_name = "ABCluster" if classical else "CREST"
            old = [a for a in record.attempts if a.metadata.get("role") == "sampler"]
            attempt = Attempt(
                run_id=record.run_id,
                engine="abcluster" if classical else "crest",
                method="CHARMM-pairwise-rigid" if classical else "GFN2-xTB",
                parent_attempt_id=old[-1].attempt_id if old else None,
                status="running",
                started_at=utc_now(),
                metadata={
                    "role": "sampler",
                    "input_molecule": request.molecule.model_dump(mode="json"),
                },
            )
            record.attempts.append(attempt)
            store.commit(record)
            remaining = deadline - time.monotonic()
            if remaining <= 0 or (cancel_event is not None and cancel_event.is_set()):
                attempt.status = (
                    "cancelled" if cancel_event and cancel_event.is_set() else "timed-out"
                )
                attempt.finished_at = utc_now()
                record.status = attempt.status
                record.metadata["termination_reason"] = "Stopped before " + sampler_name + " sampling"
                return None
            if classical:
                from .abcluster import run_rigidmol

                result = run_rigidmol(
                    request.molecule, request.abcluster_options,
                    request.resources.model_copy(update={"budget_seconds": remaining * request.sampler_budget_fraction}),
                    store.run_dir / "attempts" / attempt.attempt_id,
                    executable=self.config.executables.get("abcluster"), cancel_event=cancel_event,
                    process_runner=self.base_runtime.run_process if self.base_runtime else None)
            else:
                result = run_crest(
                    request.molecule,
                    request.method_spec,
                    request.resources.model_copy(
                        update={"budget_seconds": remaining * request.sampler_budget_fraction}
                    ),
                    store.run_dir / "attempts" / attempt.attempt_id,
                    seed=None,
                    cancel_event=cancel_event,
                    executable=self.config.executables.get("crest"),
                    xtb_executable=self.config.executables.get("xtb"),
                    profile=request.sampler_profile,
                    nci=request.sampler_nci,
                    energy_window_kcal_mol=request.energy_window_kcal_mol,
                    process_runner=self.base_runtime.run_process if self.base_runtime else None,
                )
            attempt.status, attempt.converged = result.status, result.converged
            attempt.finished_at = utc_now()
            attempt.command, attempt.engine_version = result.command, result.engine_version
            attempt.metadata.update(result.metadata)
            attempt.metadata["algorithm"] = result.algorithm
            attempt.metadata["potential_engine"] = result.potential_engine
            attempt.metadata["potential_engine_version"] = result.potential_engine_version
            attempt.metadata["raw_ensemble"] = [c.model_dump(mode="json") for c in result.ensemble]
            attempt.metadata["topos_seed_scope"] = (
                "jiggle perturbations only; native " + sampler_name + " randomness is engine-controlled"
            )
            attempt.diagnostics = result.diagnostics
            attempt.artifacts = [
                a.model_copy(
                    update={"path": Path(a.path).resolve().relative_to(store.run_dir).as_posix()}
                )
                for a in result.artifacts
            ]
            # Native termination validates an observed ensemble, never complete sampling.
            attempt.validation_status = (
                "validated-for-protocol" if result.status == "completed" else "not-evaluated"
            )
            if result.status != "completed":
                record.status = result.status
                record.metadata["termination_reason"] = result.diagnostics.get(
                    "reason", sampler_name + " did not complete its native search protocol"
                )
                # Both sources were explicitly requested. A failed CREST search
                # does not erase the separately requested jiggle–quench branch.
                # Its observed frames remain unrefined evidence, not a substitute
                # completed CREST ensemble. Resume retries CREST and appends new
                # frames while retaining stable indices for completed jiggles.
                if request.search_algorithm == "union" and result.status != "cancelled":
                    record.metadata["sample_plan"] = plans
                    record.metadata["sampler_pending"] = True
                    record.metadata["sampler_incomplete"] = {
                        "attempt_id": attempt.attempt_id,
                        "status": result.status,
                        "reason": record.metadata["termination_reason"],
                    }
                    return plans
                return None
            record.metadata.pop("sampler_pending", None)
            record.metadata.pop("sampler_incomplete", None)
            record.metadata.pop("termination_reason", None)
            selected = sorted(result.ensemble, key=lambda c: (c.energy_hartree, c.source_index))[
                : request.n_candidates
            ]
            plans.extend(
                {
                    "molecule": c.molecule.model_dump(mode="json"),
                    "source": sampler_name.upper(),
                    "sampler_attempt_id": attempt.attempt_id,
                    "source_frame": c.source_index,
                    "search_energy_hartree": c.energy_hartree,
                    "search_energy_definition": "classical intermolecular score, not electronic energy" if classical else "native GFN2-xTB search electronic energy",
                }
                for c in selected
            )
            included = {c.source_index for c in selected}
            record.metadata["sampler_exclusions"] = [
                {
                    "source_index": c.source_index,
                    "reason": "outside explicit per-source refinement cap; original frame retained in raw ensemble",
                }
                for c in result.ensemble
                if c.source_index not in included
            ]
            record.metadata["citations"].extend(
                [{"kind": "software", "title": "ABCluster rigidmol", "version": result.engine_version,
                  "url": result.metadata["manual"]},
                 {"kind": "force-field-parameter-source", "title": request.abcluster_options.parameter_source,
                  "url": result.metadata["force_field_manual"]}] if classical else
                [
                    {
                        "kind": "software",
                        "title": "CREST",
                        "version": result.engine_version,
                        "url": "https://github.com/crest-lab/crest",
                    },
                    {
                        "kind": "peer-reviewed-method",
                        "title": "Automated Exploration of the Low-Energy Chemical Space with Fast Quantum Chemical Methods",
                        "doi": "10.1039/C9CP06869D",
                        "year": 2020,
                    },
                    {
                        "kind": "peer-reviewed-software",
                        "title": "CREST—A Program for the Exploration of Low-Energy Molecular Chemical Space",
                        "doi": "10.1063/5.0197592",
                        "year": 2024,
                    },
                ]
            )
        record.metadata["sample_plan"] = plans
        record.metadata["refinement_cap_scope"] = (
            "n_candidates total for jiggle-quench; up to n_candidates native lowest-score sampler frames plus input; union contains jiggle and CREST, without implicit completeness"
        )
        return plans

    def _finish(self, record: RunRecord, store: RunStore, start: ExecutionBudget) -> RunRecord:
        record.updated_at = utc_now()
        nested = record.metadata.get("nested_budget_accounting")
        if nested and nested.get("invocation_started_at") == record.metadata.get("invocation_started_at"):
            ensemble = nested["ensemble"]
            ensemble["elapsed_seconds"] = max(
                0.0, start.snapshot()["execution_seconds"] - ensemble["started_at_execution_seconds"]
            )
            ensemble["deadline_exhausted"] = ensemble["elapsed_seconds"] >= ensemble["allocated_seconds"]
            if ensemble["deadline_exhausted"] and record.status == "completed":
                record.status = "partial" if any(c.status == "eligible" for c in record.candidates) else "timed-out"
                record.metadata["termination_reason"] = "Ensemble budget exhausted before final evidence commit"
            ensemble["status"] = record.status
            import copy

            record.metadata.setdefault("nested_budget_history", []).append(copy.deepcopy(nested))
        if start.status in {"queued", "running"}:
            try:
                start.finish(record.status)
            except TimeoutError:
                start.finish("timed-out")
                record.status = "partial" if any(c.status == "eligible" for c in record.candidates) else "timed-out"
                record.metadata["termination_reason"] = "Workflow execution budget exhausted before final evidence commit"
        accounting = start.snapshot()
        record.metadata["budget_accounting"] = accounting
        record.metadata.setdefault("invocation_budget_history", []).append(accounting)
        record.metadata["queue_seconds"] = accounting["queue_seconds"]
        record.metadata["elapsed_seconds"] = accounting["execution_seconds"]
        record.metadata["total_invocation_seconds"] = (
            record.metadata.get("total_invocation_seconds", 0.0)
            + record.metadata["elapsed_seconds"]
        )
        store.commit(record)
        return record

    @staticmethod
    def _seed(request: RunRequest, index: int) -> Molecule:
        if index == 0:
            return request.molecule.model_copy(deep=True)
        rng = np.random.default_rng(np.random.SeedSequence([request.seed, index]))
        if request.constraints:
            from .constraints import rigid_perturb

            return rigid_perturb(
                request.molecule, rng, translation_angstrom=request.perturbation_angstrom
            )
        xyz = np.asarray(request.molecule.coordinates, dtype=np.float64)
        xyz = xyz + rng.normal(0.0, request.perturbation_angstrom, xyz.shape)
        return Molecule.model_validate(
            {**request.molecule.model_dump(), "coordinates": xyz.tolist()}
        )

    def _engine_attempt(
        self,
        record: RunRecord,
        store: RunStore,
        molecule: Molecule,
        index: int,
        parent: str | None,
        deadline: float,
        cancel_event: Event | None,
        operation: str,
        *,
        strip_constraints: bool = False,
        method_override: MethodSpec | None = None,
    ) -> tuple[Attempt, EngineResult]:
        request = record.request
        attempt = Attempt(
            run_id=record.run_id,
            parent_attempt_id=parent,
            engine=request.engine,
            method=request.method,
            status="running",
            started_at=utc_now(),
            metadata={
                "sample_index": index,
                "seed": request.seed,
                "input_molecule": molecule.model_dump(mode="json"),
                "operation": operation,
            },
        )
        record.attempts.append(attempt)
        # Commit the running identity before execution; a crash cannot turn it into a pass.
        store.commit(record)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result = EngineResult(
                status="timed-out",
                engine=request.engine,
                method=request.method,
                operation=operation,
                diagnostics={"reason": "workflow budget exhausted"},
            )
        else:
            method = method_override or request.method_spec
            if method.engine != request.engine or method.method != request.method:
                raise ValueError("An internal numerical profile override cannot change the requested Hamiltonian")
            if strip_constraints:
                method = method.model_copy(update={"constraints": {}})
            result = run_engine(
                molecule,
                method,
                request.resources.model_copy(update={"budget_seconds": remaining}),
                store.run_dir / "attempts" / attempt.attempt_id,
                operation=operation,
                cancel_event=cancel_event,
                executable=self.config.executables.get(request.engine),
                process_runner=self.base_runtime.run_process if self.base_runtime else None,
            )
        if result.status == "completed" and time.monotonic() >= deadline:
            result.status, result.converged = "timed-out", False
            result.diagnostics["reason"] = (
                "Allocated geometry/ensemble/workflow deadline exhausted before engine result validation completed"
            )
        attempt.status = result.status
        attempt.finished_at = utc_now()
        attempt.engine_version = result.engine_version
        attempt.command = result.command
        attempt.converged = result.converged
        attempt.validation_status = (
            "validated-for-protocol"
            if result.status == "completed" and result.converged
            else "rejected"
        )
        attempt.metadata.update(result.metadata)
        if result.molecule is not None:
            attempt.metadata["output_molecule"] = result.molecule.model_dump(mode="json")
        attempt.metadata["elapsed_seconds"] = result.elapsed_seconds
        attempt.diagnostics = result.diagnostics
        for artifact in result.artifacts:
            path = Path(artifact.path).resolve()
            attempt.artifacts.append(
                artifact.model_copy(update={"path": path.relative_to(store.run_dir).as_posix()})
            )
        if result.energy_hartree is not None:
            attempt.quantities.append(
                Quantity(
                    name="electronic_energy",
                    value=result.energy_hartree,
                    units="hartree",
                    definition="electronic potential energy at recorded output geometry; no ZPE or thermal corrections",
                    attempt_id=attempt.attempt_id,
                    method=request.method,
                    parser=f"topos.engines/{__version__}",
                    validity=attempt.validation_status,
                )
            )
        if result.gradient_hartree_per_bohr is not None:
            attempt.quantities.append(
                Quantity(
                    name="cartesian_gradient",
                    value=result.gradient_hartree_per_bohr,
                    units="hartree/bohr",
                    definition="dE/dx at the output geometry",
                    attempt_id=attempt.attempt_id,
                    method=request.method,
                    parser=f"topos.engines/{__version__}",
                    validity=attempt.validation_status,
                )
            )
        return attempt, result

    def _constrained(
        self,
        record: RunRecord,
        store: RunStore,
        molecule: Molecule,
        index: int,
        parent: str | None,
        deadline: float,
        cancel_event: Event | None,
    ) -> tuple[Attempt, EngineResult]:
        from .constraints import constrained_optimize

        evaluations: list[tuple[Attempt, EngineResult]] = []

        def evaluate(geometry: Molecule) -> tuple[float, list[list[float]]]:
            nonlocal parent
            attempt, result = self._engine_attempt(
                record,
                store,
                geometry,
                index,
                parent,
                deadline,
                cancel_event,
                "gradient",
                strip_constraints=True,
            )
            evaluations.append((attempt, result))
            parent = attempt.attempt_id
            if (
                result.status != "completed"
                or result.energy_hartree is None
                or result.gradient_hartree_per_bohr is None
            ):
                raise _EvaluationStopped(
                    result.status, result.diagnostics.get("reason", "derivative unavailable")
                )
            return result.energy_hartree, result.gradient_hartree_per_bohr

        try:
            optimized = constrained_optimize(
                molecule,
                evaluate,
                constraints=record.request.constraints,
                budget_seconds=max(1e-9, deadline - time.monotonic()),
                cancel_event=cancel_event,
            )
        except _EvaluationStopped:
            return evaluations[-1]
        status = (
            optimized.status
            if optimized.status in {"completed", "timed-out", "cancelled"}
            else "partial"
        )
        accepted = [
            i for i, evaluation in enumerate(optimized.evaluations) if evaluation.get("accepted")
        ]
        source_attempt, source_result = evaluations[accepted[-1]] if accepted else (None, None)
        result = EngineResult(
            status=status,
            engine=record.request.engine,
            method=record.request.method,
            operation="constrained-optimize",
            molecule=optimized.molecule,
            energy_hartree=optimized.energy_hartree,
            gradient_hartree_per_bohr=optimized.gradient_hartree_per_bohr,
            converged=optimized.converged,
            diagnostics={"constraints": optimized.diagnostics, "reason": optimized.status},
        )
        attempt = Attempt(
            run_id=record.run_id,
            parent_attempt_id=source_attempt.attempt_id if source_attempt else parent,
            engine=record.request.engine,
            method=record.request.method,
            status=status,
            converged=optimized.converged,
            started_at=evaluations[0][0].started_at if evaluations else utc_now(),
            finished_at=utc_now(),
            command=["topos-internal", "rigid-body-optimize"],
            metadata={
                "sample_index": index,
                "execution_kind": "real" if source_attempt else "not-executed",
                "result_kind": "derived-optimization",
                "algorithm": "TOPOS rigid-body optimizer",
                "derivative_attempt_ids": [a.attempt_id for a, _ in evaluations],
                "accepted_derivative_attempt_id": source_attempt.attempt_id
                if source_attempt
                else None,
                "constraint_reference": molecule.model_dump(mode="json"),
                "constrained_optimizer": optimized.diagnostics,
            },
            diagnostics=result.diagnostics,
        )
        if source_attempt and source_result:
            result.engine_version = source_attempt.engine_version
            result.metadata["executable_sha256"] = source_result.metadata.get("executable_sha256")
            attempt.engine_version = source_attempt.engine_version
            attempt.artifacts = [a.model_copy(deep=True) for a in source_attempt.artifacts]
            attempt.quantities = [
                q.model_copy(deep=True, update={"attempt_id": attempt.attempt_id})
                for q in source_attempt.quantities
            ]
        attempt.validation_status = (
            "validated-for-protocol"
            if optimized.converged
            and source_attempt
            and source_attempt.validation_status == "validated-for-protocol"
            else "rejected"
        )
        for quantity in attempt.quantities:
            quantity.validity = attempt.validation_status
        record.attempts.append(attempt)
        return attempt, result

    @staticmethod
    def _candidate(
        record: RunRecord,
        seed: Molecule,
        attempt: Attempt,
        result: EngineResult,
        index: int,
        source: str,
    ) -> Candidate:
        molecule = result.molecule or seed
        protocol = digest_json(
            {
                "method": record.request.method_spec.model_dump(mode="json"),
                "engine_version": result.engine_version,
                "executable_sha256": result.metadata.get("executable_sha256"),
                "composition": sorted(
                    zip(molecule.symbols, molecule.isotopes, strict=True), key=str
                ),
                "charge": molecule.charge,
                "multiplicity": molecule.multiplicity,
                "environment": molecule.environment,
            }
        )
        candidate = Candidate(
            molecule=molecule,
            attempt_id=attempt.attempt_id,
            energy_hartree=result.energy_hartree,
            comparison_protocol=protocol,
            status="eligible"
            if result.status == "completed" and result.converged
            else result.status,
            sources=[source],
            metadata={
                "sample_index": index,
                "seed_geometry": seed.model_dump(mode="json"),
                "calculation_completed": result.status == "completed",
                "proposal_processed": result.status == "completed",
                "observation_source": source,
                "reason": result.diagnostics.get("reason"),
                "stationary_point_classification": "constrained stationary point; no frequency Hessian"
                if record.request.constraints and result.converged
                else "not-evaluated: no frequency Hessian",
            },
        )
        attempt.metadata["output_molecule"] = molecule.model_dump(mode="json")
        attempt.metadata["comparison_protocol"] = protocol
        for quantity in attempt.quantities:
            quantity.geometry_id = candidate.candidate_id
        if candidate.status == "eligible":
            try:
                validation = validate_chemistry(molecule)
                preserved = _topology_preserved(record.request.molecule, molecule)
            except ValueError as exc:
                validation, preserved = (
                    {"status": "physically-suspect", "issues": [str(exc)]},
                    False,
                )
            candidate.metadata["post_optimization_validation"] = validation
            if validation["status"] != "valid" or not preserved:
                candidate.status = "rejected"
                candidate.metadata["reason"] = (
                    "geometry is suspect or inferred connectivity changed; chemistry review required"
                )
                attempt.validation_status = "human-review"
            from .science import rotational_constants, validate_stereochemical_preservation

            stereo = validate_stereochemical_preservation(record.request.molecule, molecule)
            candidate.metadata["stereochemistry_validation"] = stereo
            if stereo["status"] != "preserved":
                candidate.status = "rejected"
                candidate.metadata["reason"] = (
                    "Stereochemistry inverted, ambiguous, or unsupported; human resolution required"
                )
                attempt.validation_status = "human-review"

            try:
                candidate.metadata["rotational_constants"] = rotational_constants(molecule)
            except ValueError as exc:
                candidate.metadata["rotational_constants"] = {
                    "status": "unavailable",
                    "reason": str(exc),
                }
        from .symmetry import point_group_analysis, principal_axis_dipole, rotational_observables

        candidate.metadata["point_group"] = point_group_analysis(
            molecule, tolerance_angstrom=record.request.symmetry_tolerance_angstrom,
        )
        candidate.metadata["rotational_observables"] = rotational_observables(
            molecule, geometry_method=(f"{result.engine}/{result.method} optimized geometry"
                                       if result.operation in {"optimize", "constrained-optimize"}
                                       else f"supplied geometry; {result.engine}/{result.method} {result.operation}"),
        )
        vector = result.metadata.get("dipole_cartesian_debye")
        if vector is not None and result.metadata.get("dipole_provenance"):
            candidate.metadata["dipole"] = principal_axis_dipole(
                molecule, vector, dipole_method=f"{result.engine}/{result.method}",
            )
            candidate.metadata["dipole"]["provenance"] = result.metadata["dipole_provenance"]
        else:
            candidate.metadata["dipole"] = {"status": "unavailable", "reason": "no parsed Cartesian dipole with engine provenance"}
        return candidate

    @staticmethod
    def _reporting_refinement(record: RunRecord, candidate: Candidate) -> dict[str, Any]:
        """Check recorded computation evidence before matrix Stage B is enabled."""
        from .science import geometry_digest

        attempt = next((a for a in record.attempts if a.attempt_id == candidate.attempt_id), None)
        result: dict[str, Any] = {"verified": False, "attempt_id": candidate.attempt_id,
                                  "reason": "reporting requires a converged, validated QM optimization with matching output geometry and energy"}
        if attempt is None:
            return result
        operation = attempt.metadata.get("operation")
        if attempt.metadata.get("result_kind") == "derived-optimization":
            operation = "constrained-optimize"
        if (attempt.engine != "orca" or operation not in {"optimize", "constrained-optimize"}
                or attempt.status != "completed" or attempt.converged is not True
                or attempt.validation_status != "validated-for-protocol"
                or attempt.metadata.get("execution_kind") != "real" or not attempt.engine_version
                or not attempt.command or not attempt.artifacts
                or attempt.metadata.get("comparison_protocol") != candidate.comparison_protocol):
            return result
        output = attempt.metadata.get("output_molecule")
        if not output or geometry_digest(Molecule.model_validate(output)) != geometry_digest(candidate.molecule):
            return {**result, "reason": "attempt output geometry does not match candidate geometry"}
        energies = [q for q in attempt.quantities if q.name == "electronic_energy" and q.units == "hartree"
                    and q.validity == "validated-for-protocol" and q.geometry_id == candidate.candidate_id]
        if not any(q.value == candidate.energy_hartree for q in energies) or candidate.energy_hartree is None:
            return {**result, "reason": "candidate lacks a matching validated electronic-energy quantity"}
        return {**result, "verified": True, "reason": "validated common-level quantum optimization evidence",
                "engine": attempt.engine, "engine_version": attempt.engine_version,
                "method": attempt.method, "operation": operation,
                "comparison_protocol": candidate.comparison_protocol,
                "geometry_digest": geometry_digest(candidate.molecule)}

    @staticmethod
    def _compare(
        record: RunRecord, *, deadline: float | None = None, cancel_event: Event | None = None
    ) -> str:
        from scipy.constants import Avogadro, physical_constants

        from .reporting import compare_reporting_candidates, reporting_ensemble
        from .science import compare_candidates, energy_comparison_key

        reporting = record.request.deduplication_stage == "reporting"
        refinement = {c.candidate_id: Workflow._reporting_refinement(record, c) for c in record.candidates} if reporting else {}
        energy_scale = physical_constants["Hartree energy"][0] * Avogadro / 4184.0
        pool = [
            c for c in record.candidates if c.status in {"eligible", "duplicate", "excluded-window"}
        ]
        pool.sort(
            key=lambda c: (
                float("inf") if c.energy_hartree is None else c.energy_hartree,
                c.candidate_id,
            )
        )
        retained: list[Candidate] = []
        status = "completed"
        pair_count = 0
        inconclusive = 0
        for candidate in pool:
            candidate.status = "eligible"
            for key in ("duplicate_of", "identity_decision", "observations",
                        "relative_electronic_energy_kcal_mol", "discovery_sources", "reason"):
                candidate.metadata.pop(key, None)
            candidate.metadata["identity_comparisons"] = []
            source = candidate.metadata.get("observation_source")
            if source is not None:
                candidate.sources = [source]
        for candidate in pool:
            if energy_comparison_key(candidate) is None:
                candidate.status = "human-review"
                candidate.metadata["reason"] = "missing energy or comparison protocol"
                continue
            for earlier in retained:
                if cancel_event is not None and cancel_event.is_set():
                    status = "cancelled"
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    status = "timed-out"
                    break
                if reporting:
                    comparison = compare_reporting_candidates(
                        candidate, earlier,
                        qm_refined=refinement[candidate.candidate_id]["verified"] and refinement[earlier.candidate_id]["verified"],
                        dipole_error_debye=record.request.dipole_method_error_debye,
                        deadline=deadline, cancel_event=cancel_event,
                    )
                else:
                    comparison = compare_candidates(
                        candidate,
                        earlier,
                        rmsd_threshold=record.request.rmsd_threshold_angstrom,
                        energy_threshold_kcal_mol=record.request.dedup_energy_threshold_kcal_mol,
                        rotational_threshold_fraction=record.request.dedup_rotational_threshold_fraction,
                        deadline=deadline,
                        cancel_event=cancel_event,
                    )
                first_pg, second_pg = candidate.metadata.get("point_group"), earlier.metadata.get("point_group")
                if first_pg and second_pg and (first_pg["status"] != "stable" or second_pg["status"] != "stable"
                                               or first_pg["point_group"] != second_pg["point_group"]):
                    comparison["symmetry_review"] = {"point_groups": [first_pg["point_group"], second_pg["point_group"]],
                                                     "reason": "symmetry differs or is tolerance sensitive; symmetry labels do not establish identity"}
                    candidate.metadata["symmetry_review_required"] = True
                    earlier.metadata["symmetry_review_required"] = True
                    # A label changes with numerical tolerance, while the mapped
                    # chemistry/geometry criteria directly test conformer identity.
                    # Keep the review annotation without inventing another species.
                pair_count += 1
                inconclusive += comparison.get("status") == "unresolved"
                candidate.metadata["identity_comparisons"].append({
                    "against_candidate_id": earlier.candidate_id, **comparison,
                })
                if comparison["equivalent"]:
                    candidate.status = "duplicate"
                    candidate.metadata["duplicate_of"] = earlier.candidate_id
                    candidate.metadata["identity_decision"] = comparison
                    earlier.sources = sorted(set(earlier.sources + candidate.sources))
                    earlier.metadata["observations"] = sorted(
                        set(earlier.metadata.get("observations", []) + [candidate.candidate_id])
                    )
                    break
            if candidate.status == "eligible":
                retained.append(candidate)
            if status != "completed":
                break
        if cancel_event is not None and cancel_event.is_set():
            status = "cancelled"
        elif deadline is not None and time.monotonic() >= deadline:
            status = "timed-out"
        # An interrupted comparison keeps every unprocessed observation eligible
        # for review. It does not certify that those structures are unique.
        eligible = [c for c in pool if c.status == "eligible"]
        minima: dict[str, float] = {}
        for candidate in eligible:
            key = energy_comparison_key(candidate)
            if key is not None:
                minima[key] = min(minima.get(key, float("inf")), candidate.energy_hartree)
        for candidate in eligible:
            key = energy_comparison_key(candidate)
            if key is None:
                continue
            relative = (candidate.energy_hartree - minima[key]) * energy_scale
            candidate.metadata["relative_electronic_energy_kcal_mol"] = relative
            candidate.metadata["energy_comparison_key"] = key
            candidate.metadata["discovery_sources"] = sorted(set(candidate.sources))
            if relative > record.request.energy_window_kcal_mol:
                candidate.status = "excluded-window"
                candidate.metadata["reason"] = (
                    "outside declared electronic energy window; not proof of physical absence"
                )
        record.metadata["deduplication"] = {
            "status": status,
            "profile": "method-matrix-A.1-stage-B" if reporting else "topos-conservative-generation-v1",
            "stage": record.request.deduplication_stage,
            "source": "wiki/Method_Matrix.md Appendix A.1; SRS chapters 6–7",
            "energy_threshold_kcal_mol": 0.05 if reporting else record.request.dedup_energy_threshold_kcal_mol,
            "rotational_threshold_fraction": 0.001 if reporting else record.request.dedup_rotational_threshold_fraction,
            "rmsd_threshold_angstrom": 0.125 if reporting else record.request.rmsd_threshold_angstrom,
            "pair_comparisons": pair_count,
            "inconclusive_comparisons": inconclusive,
            "enantiomers": "kept distinct; no inferred degeneracy",
            "interpretation": "common-QM reporting AND screen; original identity records retained" if reporting else "fixed conservative generation screen; not adaptive CREGEN or spectroscopic identity",
        }
        if reporting:
            record.metadata["reporting_refinement"] = refinement
            valid = bool(pool) and all(refinement[c.candidate_id]["verified"] for c in pool)
            collapse = getattr(record.request, "collapse_enantiomers", record.request.metadata.get("reporting_collapse_enantiomers", False))
            achiral = getattr(record.request, "environment_is_achiral", record.request.metadata.get("environment_is_achiral"))
            if valid and status == "completed" and not inconclusive:
                ensemble = reporting_ensemble(pool, qm_refined=True, collapse_enantiomers=collapse,
                                               environment_is_achiral=achiral,
                                               dipole_error_debye=record.request.dipole_method_error_debye,
                                               deadline=deadline, cancel_event=cancel_event)
                ensemble["representatives"] = [c.model_dump(mode="json") for c in ensemble["representatives"]]
                group_unresolved = any(d["comparison"]["status"] == "unresolved" for d in ensemble["decisions"])
                if cancel_event is not None and cancel_event.is_set():
                    status = "cancelled"
                elif deadline is not None and time.monotonic() >= deadline:
                    status = "timed-out"
                record.metadata["reporting_ensemble"] = {"status": "requires-review" if group_unresolved or status != "completed" else "completed", **ensemble}
                record.metadata["deduplication"]["status"] = status
            else:
                record.metadata["reporting_ensemble"] = {"status": "requires-review",
                                                         "reason": "missing QM refinement evidence or incomplete/uncertain comparisons; no grouping certified",
                                                         "identity_records_retained": True}
        return status
