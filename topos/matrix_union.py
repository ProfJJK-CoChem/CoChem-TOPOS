"""Verified native ensemble union, common refinement, Hessian and CREGEN stages.

The matrix's literal analytic ``Freq`` is the default. A central-gradient
derivative is available only under an explicit recorded resolution. Native CREST screening cannot attribute its output
frames to individual input searches; input evidence and that limitation survive.
"""
from __future__ import annotations

import time
from pathlib import Path
from threading import Event
from typing import Any, Callable

from .ensemble_tools import run_cregen, run_crest_screen
from .matrix_sources import import_native_ensemble
from .models import Artifact, Attempt, Candidate, RunRecord, utc_now
from .sampling import SampledConformer
from .storage import IntegrityError, RunStore, digest_json, file_digest


def _stop(record: RunRecord, deadline: float, cancel_event: Event | None) -> bool:
    if cancel_event is not None and cancel_event.is_set():
        record.status, record.metadata["termination_reason"] = "cancelled", "Matrix union cancelled; completed stages retained"
        return True
    if time.monotonic() >= deadline:
        record.status, record.metadata["termination_reason"] = "timed-out", "Matrix union deadline reached; completed stages retained"
        return True
    return False


def native_stage(workflow: Any, record: RunRecord, store: RunStore, frames: list[SampledConformer],
                 operation: str, deadline: float, cancel_event: Event | None,
                 *, comparison_protocol: str | None = None,
                 energy_window_kcal_mol: float = 12.0,
                 energy_threshold_kcal_mol: float = .05,
                 rotational_threshold: float = .001) -> list[SampledConformer] | None:
    """Checkpoint one genuine native operation; reuse only identical retained inputs."""
    if operation not in {"screen", "cregen"}:
        raise ValueError("Only compiled native screen/CREGEN operations are supported")
    if _stop(record, deadline, cancel_event):
        return None
    identity = digest_json({"operation": operation, "frames": [f.model_dump(mode="json") for f in frames],
                            "comparison_protocol": comparison_protocol, "ewin": energy_window_kcal_mol,
                            "ethr": energy_threshold_kcal_mol, "rthr": .125,
                            "bthr": rotational_threshold if operation == "cregen" else .01})
    cached = [a for a in record.attempts if a.metadata.get("matrix_native_identity") == identity
              and a.status == "completed" and a.validation_status == "validated-for-protocol"]
    if cached:
        for artifact in cached[-1].artifacts:
            path = store.run_dir / artifact.path
            if path.is_symlink() or file_digest(path) != artifact.sha256 or path.stat().st_size != artifact.size_bytes:
                raise IntegrityError("Completed native union-stage artifact changed")
        if _stop(record, deadline, cancel_event):
            return None
        return [SampledConformer.model_validate(f) for f in cached[-1].metadata["raw_ensemble"]]
    if _stop(record, deadline, cancel_event):
        return None
    runtime = workflow.base_runtime
    try:
        crest = runtime.resolve_executable("crest", workflow.config.executables.get("crest")) if runtime else workflow.config.executables.get("crest")
        xtb = runtime.resolve_executable("xtb", workflow.config.executables.get("xtb")) if runtime and operation == "screen" else workflow.config.executables.get("xtb")
    except (ValueError, OSError, RuntimeError) as exc:
        record.status, record.metadata["termination_reason"] = "unavailable", str(exc)
        return None
    from .runtime import run_process

    runner = runtime.run_process if runtime else run_process if workflow.config.execution_backend == "development" else None
    attempt = Attempt(run_id=record.run_id, engine="crest", method="GFN2-xTB" if operation == "screen" else "supplied-common-level",
                      status="running", started_at=utc_now(),
                      metadata={"role": "matrix-native-" + operation, "matrix_native_identity": identity})
    record.attempts.append(attempt)
    store.commit(record)
    # Native screen/CREGEN remain CPU stages even after a GPU model campaign.
    resources = record.request.resources.model_copy(update={"device": "cpu",
        "budget_seconds": max(1e-9, deadline - time.monotonic())})
    directory = store.run_dir / "attempts" / attempt.attempt_id
    if operation == "screen":
        result = run_crest_screen(frames, resources, directory, executable=crest, xtb_executable=xtb,
                                  process_runner=runner, cancel_event=cancel_event, energy_window_kcal_mol=energy_window_kcal_mol)
    else:
        result = run_cregen(frames, resources, directory, executable=crest, comparison_protocol=comparison_protocol,
                            process_runner=runner, cancel_event=cancel_event, energy_window_kcal_mol=energy_window_kcal_mol,
                            energy_threshold_kcal_mol=energy_threshold_kcal_mol,
                            rotational_threshold=rotational_threshold, rmsd_threshold_angstrom=.125)
    attempt.status, attempt.converged = result.status, result.converged
    attempt.finished_at = utc_now()
    attempt.command, attempt.engine_version, attempt.diagnostics = result.command, result.engine_version, result.diagnostics
    attempt.metadata.update(result.metadata)
    attempt.metadata.update(raw_ensemble=[frame.model_dump(mode="json") for frame in result.ensemble],
                            potential_engine=result.potential_engine, potential_engine_version=result.potential_engine_version)
    attempt.artifacts = [a.model_copy(update={"path": Path(a.path).resolve().relative_to(store.run_dir).as_posix()}) for a in result.artifacts]
    attempt.validation_status = "validated-for-protocol" if result.status == "completed" else "not-evaluated"
    store.commit(record)
    if result.status != "completed":
        record.status = result.status
        record.metadata["termination_reason"] = f"Native {operation} did not complete: " + str(result.diagnostics.get("reason", result.status))
        return None
    return result.ensemble


def _one_candidate(result: RunRecord, *, require_minimum: bool = False) -> Candidate:
    candidates = [c for c in result.candidates if c.status == "eligible" and c.energy_hartree is not None]
    if len(candidates) != 1:
        raise ValueError("Common-level component has no unique scientifically eligible candidate")
    candidate = candidates[0]
    native = next(a for a in result.attempts if a.attempt_id == candidate.attempt_id)
    if (native.status != "completed" or native.validation_status != "validated-for-protocol"
            or native.metadata.get("execution_kind") != "real" or not native.metadata.get("executable_sha256")
            or not native.engine_version):
        raise ValueError("Common-level candidate lacks verified real engine identity")
    if require_minimum and candidate.metadata.get("stationary_point_classification") != "harmonic-minimum-within-thresholds":
        raise ValueError("A refined union member is not a verified harmonic minimum within the explicit numerical thresholds")
    return candidate


def execute_union(workflow: Any, record: RunRecord, store: RunStore, inputs: Any,
                  child: Callable[..., RunRecord | None], deadline: float,
                  cancel_event: Event | None) -> bool:
    state = record.metadata.setdefault("matrix_union", {"imports": {}})
    state["derivative_resolution"] = {
        "selected": inputs.derivative_resolution or "native-orca-analytic-hessian-v1", "source_literal": "ORCA Freq: native analytic Hessian",
        "executed": "central finite differences of actual r2SCAN-3c analytic gradients" if inputs.derivative_resolution else "native ORCA Freq analytic Hessian plus independent reference gradient",
        "step_bohr": record.request.thermochemistry_options.step_bohr if inputs.derivative_resolution else None,
        "stationary_point_acceptance": "positive vibrational Hessian and residual gradient within the physical Hessian thresholds",
    }
    union: list[SampledConformer] = []
    try:
        for origin, source in (("goat", inputs.goat_ensemble), ("crest", inputs.crest_ensemble)):
            if source is None:
                raise ValueError("T1-3h requires both verified native GOAT and CREST source ensembles")
            if origin not in state["imports"]:
                if _stop(record, deadline, cancel_event):
                    return False
                imported = import_native_ensemble(source, expected_engine=origin,
                                                  expected_molecule=record.request.molecule,
                                                  destination=store.run_dir / "union-sources")
                artifacts = []
                for artifact in imported.artifacts:
                    copied = artifact.model_copy(update={"path": Path(artifact.path).relative_to(store.run_dir).as_posix()})
                    artifacts.append(copied.model_dump(mode="json"))
                    if not any(a.path == copied.path for a in record.artifacts):
                        record.artifacts.append(copied)
                state["imports"][origin] = {"frames": [f.model_dump(mode="json") for f in imported.frames],
                                             "artifacts": artifacts, "provenance": imported.provenance}
                store.commit(record)
            imported_data = state["imports"][origin]
            for entry in imported_data["artifacts"]:
                artifact = Artifact.model_validate(entry)
                path = store.run_dir / artifact.path
                if path.is_symlink() or file_digest(path) != artifact.sha256 or path.stat().st_size != artifact.size_bytes:
                    raise IntegrityError("Imported source evidence changed during matrix union resume")
            for frame_data in imported_data["frames"]:
                frame = SampledConformer.model_validate(frame_data)
                frame.metadata.update(origin=origin.upper(), native_source_index=frame.source_index,
                                      source_record_sha256=source.record_sha256)
                frame.source_index = len(union) + 1
                union.append(frame)
        # Count exact atom-mapped observations only. Equal geometries are not a
        # proof that two searches independently sampled the same physical basin.
        geometry_sets = {
            source: {digest_json(f.molecule.model_dump(exclude={"name"})) for f in union if f.metadata["origin"] == source}
            for source in ("GOAT", "CREST")
        }
        overlap = geometry_sets["GOAT"] & geometry_sets["CREST"]
        state["input_counts"] = {
            "GOAT_frames": len(state["imports"]["goat"]["frames"]), "CREST_frames": len(state["imports"]["crest"]["frames"]),
            "raw_union_frames": len(union), "exact_geometry_GOAT_only": len(geometry_sets["GOAT"] - overlap),
            "exact_geometry_CREST_only": len(geometry_sets["CREST"] - overlap), "exact_geometry_both": len(overlap),
            "exact_geometry_union": len(geometry_sets["GOAT"] | geometry_sets["CREST"]),
            "scope": "exact atom-mapped input observations; not a conformer basin-coverage estimate",
        }
        state["source_attribution"] = {
            "screened_frames": "combined verified GOAT+CREST input union",
            "individual_search_origin": "unresolved after native CREST --screen disables origin tracking",
            "source": "CREST v3.0.2 src/confparse.f90 crest_screen sets trackorigin=.false.; legacy screen_cleanup removes intermediate optimizer files",
        }
        # Native potentials may differ across source runs. Common GFN2 values
        # are measured before screen so it never compares mixed native energies.
        rescored: list[SampledConformer] = []
        binary_identities = set()
        for frame in union:
            result = child(f"union-score-{frame.source_index:05d}", frame.molecule, engine="xtb", method="GFN2-xTB",
                           purpose="energy", include_candidates=False)
            if result is None:
                return False
            candidate = _one_candidate(result)
            native = next(a for a in result.attempts if a.attempt_id == candidate.attempt_id)
            binary_identities.add((native.engine_version, native.metadata.get("executable_sha256")))
            rescored.append(frame.model_copy(update={"energy_hartree": candidate.energy_hartree,
                                                     "metadata": {**frame.metadata, "common_energy_attempt_id": candidate.attempt_id,
                                                                  "original_native_energy_hartree": frame.energy_hartree}}))
        if len(binary_identities) != 1 or not all(next(iter(binary_identities))):
            raise IntegrityError("Union rescoring mixed different real potential binaries")
        screened = native_stage(workflow, record, store, rescored, "screen", deadline, cancel_event)
        if screened is None:
            return False
        screen_attempt = next(a for a in reversed(record.attempts) if a.metadata.get("role") == "matrix-native-screen" and a.status == "completed")
        if (screen_attempt.metadata.get("potential_engine_version"), screen_attempt.metadata.get("xtb_sha256")) != next(iter(binary_identities)):
            raise IntegrityError("Union rescoring and native screen used different GFN2-xTB binaries")
        state["native_screen_count"] = len(screened)
        if len(screened) > record.request.n_candidates:
            record.status, record.metadata["termination_reason"] = "partial", "Native screened ensemble exceeds the explicit QM candidate cap; all raw frames are retained"
            return False
        refined: list[Candidate] = []
        qm_binary_identities = set()
        for frame in screened:
            result = child(f"union-qm-{frame.source_index:05d}", frame.molecule, engine="orca", method="r2SCAN-3c",
                           purpose="optimize", include_candidates=False)
            if result is None:
                return False
            optimized = _one_candidate(result)
            optimized_attempt = next(a for a in result.attempts if a.attempt_id == optimized.attempt_id)
            qm_binary_identities.add((optimized_attempt.engine_version, optimized_attempt.metadata["executable_sha256"]))
            if inputs.derivative_resolution:
                result = child(f"union-hessian-{frame.source_index:05d}", optimized.molecule, engine="orca", method="r2SCAN-3c",
                               purpose="frequency", optimize_first=False, include_candidates=True)
                if result is None:
                    return False
                candidate = _one_candidate(result, require_minimum=True)
                hessian_attempt = next(a for a in result.attempts if a.attempt_id == candidate.attempt_id)
            else:
                from .matrix_components import run_component
                from .matrix_workflow import _child_request
                from .models import MethodSpec, Quantity
                from .native_hessian import run_orca_hessian

                spec = MethodSpec(engine="orca", method="r2SCAN-3c", purpose="frequency",
                                  profile_id="orca-mapping-v4.1", engine_version="6.1.1")
                native = run_component(workflow, record, store, f"union-native-hessian-{frame.source_index:05d}",
                                       optimized.molecule, spec, run_orca_hessian, deadline, cancel_event)
                if native is None:
                    return False
                analysis = native.metadata["analysis"]
                if analysis["validity"] != "harmonic-minimum-within-thresholds":
                    raise ValueError("Native Hessian does not establish a harmonic minimum within the explicit thresholds")
                hessian_attempt = next(a for a in reversed(record.attempts) if a.metadata.get("component_key") == f"union-native-hessian-{frame.source_index:05d}" and a.status == "completed")
                existing = next((c for c in record.candidates if c.attempt_id == hessian_attempt.attempt_id), None)
                if existing is None:
                    temp = RunRecord(request=_child_request(record.request, optimized.molecule, engine="orca", method="r2SCAN-3c",
                                                           purpose="frequency", remaining=max(1e-9, deadline - time.monotonic()), optimize_first=False))
                    candidate = workflow._candidate(temp, optimized.molecule, hessian_attempt, native, frame.source_index, "MATRIX:native-Freq")
                    candidate.metadata.update(stationary_point_classification=analysis["validity"], frequency_analysis=analysis)
                    hessian_attempt.metadata.update(result_kind="native-analytic-hessian", requested_method=spec.model_dump(mode="json"))
                    hessian_attempt.quantities.append(Quantity(name="cartesian_hessian", value=native.metadata["hessian_hartree_per_bohr2"],
                                                               units="hartree/bohr^2", definition="native ORCA analytic Cartesian Hessian",
                                                               attempt_id=hessian_attempt.attempt_id, geometry_id=candidate.candidate_id,
                                                               method="r2SCAN-3c", validity="validated-for-protocol"))
                    record.candidates.append(candidate)
                else:
                    candidate = existing
            qm_binary_identities.add((hessian_attempt.engine_version, hessian_attempt.metadata["executable_sha256"]))
            if len(qm_binary_identities) != 1:
                raise IntegrityError("Union optimization and Hessian stages used different ORCA binaries")
            # The parent contains the same immutable candidate identifier, with
            # copied attempt artifacts. Keep that object for membership decisions.
            parent_candidate = next(c for c in record.candidates if c.candidate_id == candidate.candidate_id)
            parent_candidate.metadata["matrix_union_source"] = dict(state["source_attribution"])
            refined.append(parent_candidate)
        protocols = {c.comparison_protocol for c in refined}
        if len(protocols) != 1 or not next(iter(protocols)):
            raise IntegrityError("QM union contains incompatible energy/derivative comparison protocols")
        comparison_protocol = next(iter(protocols))
        supplied = [SampledConformer(molecule=c.molecule, energy_hartree=c.energy_hartree,
                                      source_index=index, source="TOPOS-common-QM",
                                      metadata={"candidate_id": c.candidate_id, "comparison_protocol": comparison_protocol,
                                                "minimum_classification": c.metadata["stationary_point_classification"]})
                    for index, c in enumerate(refined, 1)]
        unique = native_stage(workflow, record, store, supplied, "cregen", deadline, cancel_event,
                              comparison_protocol=comparison_protocol)
        if unique is None:
            return False
        selected = {f.source_index for f in unique}
        if not selected or not selected.issubset(set(range(1, len(refined) + 1))):
            raise IntegrityError("Native CREGEN representatives lost their common-QM source identity")
        for index, candidate in enumerate(refined, 1):
            if index not in selected:
                candidate.status = "excluded-native-cregen"
                candidate.metadata["reason"] = "not selected by native CREGEN; deduplication/window/topology reason is retained in the native logs, not inferred"
            else:
                candidate.status = "eligible"
            candidate.metadata["native_cregen_selected"] = index in selected
        state["final_native_representatives"] = [refined[index - 1].candidate_id for index in sorted(selected)]
        state["qm_harmonic_minimum_count"] = len(refined)
        record.metadata["deduplication"] = {
            "status": "completed", "profile": "CREST-3.0.2-native-CREGEN-explicit-stage-B", "stage": "reporting",
            "energy_threshold_kcal_mol": .05, "energy_window_kcal_mol": 12.0,
            "rmsd_threshold_angstrom": .125, "rotational_threshold_fraction": .001,
            "rotational_threshold_semantics": "native adaptive base; actual implementation permits adaptation up to .025",
            "pair_comparisons": None, "inconclusive_comparisons": 0,
            "enantiomers": "reflection-sensitive supplied sets rejected before native execution",
            "interpretation": "native CREGEN selected representatives of one verified common-QM harmonic-minimum ensemble; no inferred degeneracy",
        }
        store.commit(record)
        return True
    except IntegrityError:
        raise
    except (ValueError, OSError, RuntimeError) as exc:
        record.status, record.metadata["termination_reason"] = "partial" if record.attempts else "unsupported", str(exc)
        return False
