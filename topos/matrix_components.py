"""Durable native component ledger for explicitly typed matrix recipes."""
from __future__ import annotations

import math
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable

from .engines import EngineResult
from .models import Artifact, Attempt, Molecule, Quantity, RunRecord, utc_now
from .storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest


def run_component(workflow: Any, record: RunRecord, store: RunStore, key: str, molecule: Molecule,
                  protocol: Any, executor: Callable[..., EngineResult], deadline: float,
                  cancel_event: Event | None) -> EngineResult | None:
    """Execute/reuse one exact native protocol and preserve unsuccessful history.

    The caller supplies a compiled executor, not a path or source-document shell
    expression. Resume verifies immutable retained bytes and the full typed input.
    """
    protocol_data = protocol.model_dump(mode="json")
    identity = digest_json({"component_key": key, "molecule": molecule.model_dump(mode="json"),
                            "protocol": protocol_data})
    completed = [a for a in record.attempts if a.metadata.get("matrix_component_sha256") == identity
                 and a.status == "completed" and a.validation_status == "validated-for-protocol"]
    if completed:
        attempt = completed[-1]
        for artifact in attempt.artifacts:
            path = store.run_dir / artifact.path
            if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(store.run_dir)
                    or path.stat().st_size != artifact.size_bytes or file_digest(path) != artifact.sha256):
                raise IntegrityError("Completed matrix native component artifact changed")
        payload = attempt.metadata["native_result"]
        if digest_json(payload) != attempt.metadata["native_result_sha256"]:
            raise IntegrityError("Completed native component result identity changed")
        return EngineResult.model_validate(payload)
    if cancel_event is not None and cancel_event.is_set():
        record.status, record.metadata["termination_reason"] = "cancelled", "Matrix component cancelled before execution"
        store.commit(record)
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        record.status, record.metadata["termination_reason"] = "timed-out", "Matrix component deadline reached"
        store.commit(record)
        return None
    cap = record.request.per_geometry_budget_seconds
    if cap is not None:
        remaining = min(cap, remaining)
    runtime = workflow.base_runtime
    engine, method = protocol_data["engine"], protocol_data["method"]
    try:
        executable = runtime.resolve_executable(engine, workflow.config.executables.get(engine)) if runtime else workflow.config.executables.get(engine)
    except (ValueError, RuntimeError, OSError) as exc:
        record.status, record.metadata["termination_reason"] = "unavailable", str(exc)
        store.commit(record)
        return None
    from .runtime import run_process

    runner = runtime.run_process if runtime else run_process if workflow.config.execution_backend == "development" else None
    attempt = Attempt(run_id=record.run_id, engine=engine, method=method, status="running", started_at=utc_now(),
                      metadata={"role": "matrix-native-component", "component_key": key,
                                "matrix_component_sha256": identity, "input_molecule": molecule.model_dump(mode="json"),
                                "requested_protocol": protocol_data})
    record.attempts.append(attempt)
    store.commit(record)
    folder = store.run_dir / "attempts" / attempt.attempt_id
    remaining = min(remaining, deadline - time.monotonic())
    if remaining <= 0:
        attempt.status, attempt.finished_at = "timed-out", utc_now()
        record.status, record.metadata["termination_reason"] = "timed-out", "Matrix component deadline reached during durable prelaunch checkpoint"
        store.commit(record)
        return None
    try:
        result = executor(molecule, protocol, record.request.resources.model_copy(update={"budget_seconds": remaining}),
                          folder, executable=executable, process_runner=runner, cancel_event=cancel_event)
    except Exception as exc:
        # Preserve the prelaunch attempt when an adapter fails unexpectedly;
        # recovery must not mistake an abandoned 'running' row for live work.
        attempt.status, attempt.finished_at = "failed", utc_now()
        attempt.diagnostics = {"reason": str(exc), "exception_type": type(exc).__name__}
        record.status, record.metadata["termination_reason"] = "failed", f"Matrix component {key}: {exc}"
        store.commit(record)
        raise
    attempt.status, attempt.converged = result.status, result.converged
    attempt.finished_at = utc_now()
    attempt.command, attempt.engine_version, attempt.diagnostics = result.command, result.engine_version, result.diagnostics
    attempt.metadata.update(result.metadata)
    attempt.metadata["native_result"] = result.model_dump(mode="json")
    attempt.metadata["native_result_sha256"] = digest_json(attempt.metadata["native_result"])
    interaction = result.metadata.get("native_result", {}).get("interaction_energy_hartree")
    is_sapt = (protocol_data.get("operation") == "sapt-decomposition"
               and result.metadata.get("quantity_kind") == "interaction-energy"
               and isinstance(interaction, (int, float)) and not isinstance(interaction, bool)
               and math.isfinite(interaction) and result.energy_hartree is None)
    if result.status == "completed" and (not result.converged or result.metadata.get("execution_kind") != "real"
                                        or result.energy_hartree is None and not is_sapt
                                        or not result.artifacts or not result.command):
        raise IntegrityError("Native component attempted completion without actual converged scientific evidence")
    expected_operation = protocol_data.get("operation", protocol_data.get("purpose"))
    expected_operation = {"frequency": "hessian"}.get(expected_operation, expected_operation)
    expected_version = protocol_data.get("engine_version")
    if result.status == "completed" and (
            result.engine != engine or result.method != method or result.operation != expected_operation
            or expected_version is not None and result.engine_version != expected_version):
        raise IntegrityError("Native component result differs from the exact requested engine, method, operation or version")
    if result.status == "completed":
        identity_fields = ("symbols", "atom_ids", "isotopes", "charge", "multiplicity", "environment", "bonds", "fragments", "fragment_states", "stereochemistry")
        if result.molecule is None or any(getattr(result.molecule, field) != getattr(molecule, field) for field in identity_fields):
            raise IntegrityError("Native component changed the requested molecular identity")
        if expected_operation != "optimize" and result.molecule.coordinates != molecule.coordinates:
            raise IntegrityError("A non-optimization native component changed the requested geometry")
        if expected_operation == "optimize":
            from .science import validate_stereochemical_preservation
            from .workflow import _topology_preserved

            if not _topology_preserved(molecule, result.molecule):
                raise IntegrityError("Native optimization changed the inferred molecular topology")
            stereo = validate_stereochemical_preservation(molecule, result.molecule)
            if stereo["status"] != "preserved":
                raise IntegrityError("Native optimization did not preserve mapped stereochemistry")
            attempt.metadata["stereochemistry_validation"] = stereo
        for artifact in result.artifacts:
            if not Path(artifact.path).resolve().is_relative_to(folder):
                raise IntegrityError("Native component evidence lies outside its assigned work directory")
    attempt.validation_status = "validated-for-protocol" if result.status == "completed" else "not-evaluated"
    attempt.artifacts = [a.model_copy(update={"path": Path(a.path).resolve().relative_to(store.run_dir).as_posix()}) for a in result.artifacts]
    if result.energy_hartree is not None:
        attempt.quantities.append(Quantity(name="electronic_energy", value=result.energy_hartree, units="hartree",
                                           definition="native component electronic energy at its explicitly recorded method and basis",
                                           method=method, attempt_id=attempt.attempt_id, validity=attempt.validation_status))
    if is_sapt:
        attempt.quantities.append(Quantity(name="interaction_energy", value=interaction, units="hartree",
                                           definition="native SAPT intermolecular interaction energy; not a total electronic energy",
                                           method=method, attempt_id=attempt.attempt_id, validity=attempt.validation_status))
    if result.gradient_hartree_per_bohr is not None:
        attempt.quantities.append(Quantity(name="cartesian_gradient", value=result.gradient_hartree_per_bohr,
                                           units="hartree/bohr", definition="actual native analytic electronic gradient",
                                           method=method, attempt_id=attempt.attempt_id, validity=attempt.validation_status))
    if result.molecule is not None:
        attempt.metadata["output_molecule"] = result.molecule.model_dump(mode="json")
    receipt = folder / "matrix-component-result.json"
    atomic_json(receipt, attempt.metadata["native_result"])
    attempt.artifacts.append(Artifact(path=receipt.relative_to(store.run_dir).as_posix(), sha256=file_digest(receipt),
                                      size_bytes=receipt.stat().st_size, role="matrix-native-component-result"))
    store.commit(record)
    if result.status != "completed":
        record.status = result.status
        record.metadata["termination_reason"] = f"Matrix component {key}: " + str(result.diagnostics.get("reason", result.status))
        store.commit(record)
        return None
    return result
