"""Durable native component ledger for explicitly typed matrix recipes."""
from __future__ import annotations

import math
import re
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable

from .engines import EngineResult
from .models import Artifact, Attempt, Molecule, Quantity, RunRecord, utc_now
from .storage import (
    IntegrityError,
    RunStore,
    atomic_json,
    confined_file,
    digest_json,
    file_digest,
    read_json,
)


def verify_cfour_runtime_receipts(artifacts, root: Path, authority: dict, *, original_artifacts=None):
    """Verify retained process authority offline; this is not a native science parser.

    The original artifact inventory keeps the launch directory binding when a
    campaign is moved. Every receipt, input and output must remain hash-bound.
    """
    if (not isinstance(authority, dict)
            or not re.fullmatch(r"[a-f0-9]{64}", str(authority.get("runtime_seal_sha256", "")))
            or not re.fullmatch(r"[a-f0-9]{64}", str(authority.get("binary_sha256", "")))
            or not Path(str(authority.get("executable", ""))).is_absolute()):
        raise IntegrityError("CFOUR component lacks its retained complete runtime authority")
    entries = [a.model_dump(mode="json") if hasattr(a, "model_dump") else a for a in artifacts]
    originals = entries if original_artifacts is None else original_artifacts
    original_map = {a["path"]: a for a in originals}
    if len(original_map) != len(originals):
        raise IntegrityError("CFOUR original runtime evidence inventory is duplicated")
    files = {}
    for artifact in entries:
        path = Path(artifact["path"])
        relative = path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
        native = confined_file(root, relative)
        if relative in files or native.stat().st_size != artifact["size_bytes"] or file_digest(native) != artifact["sha256"]:
            raise IntegrityError("CFOUR runtime evidence is duplicated or changed")
        files[relative] = (native, artifact)
    outputs = [name for name in files if Path(name).name == "engine.stdout"]
    receipts = {name for name in files if Path(name).name == "engine-cfour-runtime.json"}
    expected_receipts = {(Path(name).parent / "engine-cfour-runtime.json").as_posix() for name in outputs}
    if not outputs or receipts != expected_receipts:
        raise IntegrityError("Every CFOUR native evaluation requires exactly one adjacent sealed-runtime receipt")
    for output in outputs:
        parent = Path(output).parent
        receipt_name = (parent / "engine-cfour-runtime.json").as_posix()
        receipt_path, _ = files[receipt_name]
        binding = read_json(receipt_path)
        original_directory = Path(str(binding.get("workdir", "")))
        if (binding.get("schema") != "topos-cfour-runtime-integrity/1" or binding.get("status") != "verified"
                or binding.get("runtime_before") != authority or binding.get("runtime_after") != authority
                or binding.get("reason") is not None or binding.get("command") != [authority["executable"]]
                or not original_directory.is_absolute() or binding.get("stdout_name") != "engine.stdout"
                or binding.get("stderr_name") != "engine.stderr"
                or set(binding.get("native_inputs_sha256", {})) != {"ZMAT", "GENBAS"}):
            raise IntegrityError("CFOUR process receipt contradicts its complete runtime or launch binding")
        expected = {**binding["native_inputs_sha256"], "engine.stdout": binding.get("stdout_sha256"),
                    "engine.stderr": binding.get("stderr_sha256"), "engine-cfour-runtime.json": file_digest(receipt_path)}
        for name, digest in expected.items():
            entry = files.get((parent / name).as_posix())
            original = original_map.get(str(original_directory / name))
            if entry is None or entry[1]["sha256"] != digest or original is None or original["sha256"] != digest:
                raise IntegrityError("CFOUR runtime receipt is not bound to its exact native directory, inputs and output bytes")
    return {"runtime_seal_sha256": authority["runtime_seal_sha256"], "native_evaluations": len(outputs),
            "scope": "Retained BASE process authority; native scientific validation is separate"}


def _current_cfour_authority(workflow, record):
    runtime = workflow.base_runtime
    if runtime is None or not callable(getattr(runtime, "cfour_runtime_identity", None)):
        raise IntegrityError("CFOUR components require BASE sealed-runtime authorization before execution or reuse")
    observed = runtime.cfour_runtime_identity()
    previous = record.metadata.get("cfour_runtime_authority")
    if previous is None:
        if any(a.engine == "cfour" and a.status == "completed" for a in record.attempts):
            raise IntegrityError("Cannot attach a new runtime seal to unsealed completed CFOUR evidence")
        record.metadata["cfour_runtime_authority"] = observed
    elif previous != observed:
        raise IntegrityError("CFOUR complete runtime changed within the campaign; cached components cannot be reused")
    return observed


def _completed_result(result, molecule, protocol_data, folder):
    """Recheck exact input identity on both fresh and cached native results."""
    interaction = result.metadata.get("native_result", {}).get("interaction_energy_hartree")
    is_sapt = (protocol_data.get("operation") == "sapt-decomposition"
               and result.metadata.get("quantity_kind") == "interaction-energy"
               and isinstance(interaction, (int, float)) and not isinstance(interaction, bool)
               and math.isfinite(interaction) and result.energy_hartree is None)
    if (result.status != "completed" or result.converged is not True
            or result.metadata.get("execution_kind") != "real"
            or result.energy_hartree is None and not is_sapt or not result.artifacts or not result.command):
        raise IntegrityError("Native component lacks actual converged scientific evidence")
    operation = protocol_data.get("operation", protocol_data.get("purpose"))
    operation = {"frequency": "hessian"}.get(operation, operation)
    if (result.engine != protocol_data["engine"] or result.method != protocol_data["method"]
            or result.operation != operation
            or protocol_data.get("engine_version") is not None
            and result.engine_version != protocol_data["engine_version"]):
        raise IntegrityError("Native component result differs from the exact requested engine, method, operation or version")
    fields = ("symbols", "atom_ids", "isotopes", "charge", "multiplicity", "environment", "bonds",
              "fragments", "fragment_states", "stereochemistry")
    if result.molecule is None or any(getattr(result.molecule, field) != getattr(molecule, field) for field in fields):
        raise IntegrityError("Native component changed the requested molecular identity")
    if operation != "optimize" and result.molecule.coordinates != molecule.coordinates:
        raise IntegrityError("A non-optimization native component changed the requested geometry")
    stereo = None
    if operation == "optimize":
        from .science import validate_stereochemical_preservation
        from .workflow import _topology_preserved

        if not _topology_preserved(molecule, result.molecule):
            raise IntegrityError("Native optimization changed the inferred molecular topology")
        stereo = validate_stereochemical_preservation(molecule, result.molecule)
        if stereo["status"] != "preserved":
            raise IntegrityError("Native optimization did not preserve mapped stereochemistry")
    for artifact in result.artifacts:
        try:
            relative = Path(artifact.path).absolute().relative_to(folder.absolute()).as_posix()
        except ValueError as exc:
            raise IntegrityError("Native component evidence lies outside its assigned work directory") from exc
        path = confined_file(folder, relative)
        if path.stat().st_size != artifact.size_bytes or file_digest(path) != artifact.sha256:
            raise IntegrityError("Native component evidence changed")
    return is_sapt, stereo


def _verified_component(attempt, store, molecule, protocol_data, identity, cfour_authority=None):
    folder = store.run_dir / "attempts" / attempt.attempt_id
    if (attempt.status != "completed" or attempt.validation_status != "validated-for-protocol"
            or attempt.converged is not True or attempt.metadata.get("execution_kind") != "real"
            or not attempt.artifacts or not attempt.command
            or attempt.metadata.get("matrix_component_sha256") != identity
            or attempt.metadata.get("requested_protocol") != protocol_data
            or attempt.metadata.get("input_molecule") != molecule.model_dump(mode="json")):
        raise IntegrityError("Completed matrix component lacks real converged native evidence or exact requested protocol")
    artifacts = {}
    for artifact in attempt.artifacts:
        path = confined_file(store.run_dir, artifact.path)
        if not path.is_relative_to(folder) or artifact.path in artifacts:
            raise IntegrityError("Completed native component evidence escapes its attempt or is duplicated")
        if path.stat().st_size != artifact.size_bytes or file_digest(path) != artifact.sha256:
            raise IntegrityError("Completed matrix native component artifact changed")
        artifacts[artifact.path] = artifact
    payload = attempt.metadata.get("native_result")
    if not isinstance(payload, dict) or digest_json(payload) != attempt.metadata.get("native_result_sha256"):
        raise IntegrityError("Completed native component result identity changed")
    receipts = [a for a in attempt.artifacts if a.role == "matrix-native-component-result"]
    expected = (folder / "matrix-component-result.json").relative_to(store.run_dir).as_posix()
    if len(receipts) != 1 or receipts[0].path != expected or read_json(store.run_dir / expected) != payload:
        raise IntegrityError("Completed component requires its exact durable native result receipt")
    cached = EngineResult.model_validate(payload)
    is_sapt, _ = _completed_result(cached, molecule, protocol_data, folder)
    if cached.engine == "cfour":
        retained_authority = attempt.metadata.get("cfour_runtime_authority")
        if cfour_authority is not None and retained_authority != cfour_authority:
            raise IntegrityError("Cached CFOUR authority differs from the current campaign runtime")
        verify_cfour_runtime_receipts(cached.artifacts, folder, retained_authority)
    if (attempt.engine != cached.engine or attempt.method != cached.method
            or attempt.engine_version != cached.engine_version or attempt.command != cached.command):
        raise IntegrityError("Completed component identity differs from its native receipt")
    for artifact in cached.artifacts:
        relative = Path(artifact.path).absolute().relative_to(store.run_dir).as_posix()
        if relative not in artifacts or (artifacts[relative].sha256, artifacts[relative].size_bytes, artifacts[relative].role) != (
                artifact.sha256, artifact.size_bytes, artifact.role):
            raise IntegrityError("Native result artifact membership differs from the completed component")
    expected_values = {"interaction_energy" if is_sapt else "electronic_energy":
                       cached.metadata["native_result"]["interaction_energy_hartree"] if is_sapt else cached.energy_hartree}
    if cached.gradient_hartree_per_bohr is not None:
        expected_values["cartesian_gradient"] = cached.gradient_hartree_per_bohr
    if (len(attempt.quantities) != len(expected_values) or {q.name for q in attempt.quantities} != set(expected_values)) or any(
            q.name not in expected_values or q.value != expected_values[q.name] or q.attempt_id != attempt.attempt_id
            or q.method != cached.method or q.validity != "validated-for-protocol"
            or q.units != ("hartree/bohr" if q.name == "cartesian_gradient" else "hartree") for q in attempt.quantities):
        raise IntegrityError("Completed component quantities differ from the native receipt")
    return cached


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
    cancelled = cancel_event is not None and cancel_event.is_set()
    if cancelled or deadline <= time.monotonic():
        record.status = "cancelled" if cancelled else "timed-out"
        record.metadata["termination_reason"] = "Matrix component stopped before execution or completed-cache reuse"
        store.commit(record)
        return None
    cfour_authority = None
    if protocol_data["engine"] == "cfour":
        cfour_authority = _current_cfour_authority(workflow, record)

    def checked_cached(attempt):
        current = _current_cfour_authority(workflow, record) if cfour_authority is not None else None
        cached = _verified_component(attempt, store, molecule, protocol_data, identity, current)
        cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled or deadline <= time.monotonic():
            record.status = "cancelled" if cancelled else "timed-out"
            record.metadata["termination_reason"] = "Matrix component stopped during authority/evidence verification"
            store.commit(record)
            return None
        return cached

    completed = [a for a in record.attempts if a.metadata.get("matrix_component_sha256") == identity
                 and a.status == "completed"]
    if completed:
        return checked_cached(completed[-1])
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
    if cfour_authority is not None:
        attempt.metadata["cfour_runtime_authority"] = cfour_authority
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
        attempt.command, attempt.engine_version, attempt.diagnostics = result.command, result.engine_version, result.diagnostics
        attempt.metadata.update(result.metadata)
        attempt.metadata["native_result"] = result.model_dump(mode="json")
        attempt.metadata["native_result_sha256"] = digest_json(attempt.metadata["native_result"])
        is_sapt, stereo = False, None
        if result.status == "completed":
            is_sapt, stereo = _completed_result(result, molecule, protocol_data, folder)
        if stereo is not None:
            attempt.metadata["stereochemistry_validation"] = stereo
        attempt.artifacts = []
        for artifact in result.artifacts:
            relative = Path(artifact.path).absolute().relative_to(folder.absolute()).as_posix()
            path = confined_file(folder, relative)
            attempt.artifacts.append(artifact.model_copy(update={"path": path.relative_to(store.run_dir).as_posix()}))
        if result.molecule is not None:
            attempt.metadata["output_molecule"] = result.molecule.model_dump(mode="json")
        receipt = folder / "matrix-component-result.json"
        atomic_json(receipt, attempt.metadata["native_result"])
        attempt.artifacts.append(Artifact(path=receipt.relative_to(store.run_dir).as_posix(), sha256=file_digest(receipt),
                                          size_bytes=receipt.stat().st_size, role="matrix-native-component-result"))
        # Completion is prepared only after the durable receipt and full evidence
        # exist. Any publication failure below rejects this pending attempt.
        attempt.status, attempt.converged, attempt.finished_at = result.status, result.converged, utc_now()
        attempt.validation_status = "validated-for-protocol" if result.status == "completed" else "not-evaluated"
        if result.energy_hartree is not None:
            attempt.quantities.append(Quantity(name="electronic_energy", value=result.energy_hartree, units="hartree",
                definition="native component electronic energy at its explicitly recorded method and basis",
                method=method, attempt_id=attempt.attempt_id, validity=attempt.validation_status))
        if is_sapt:
            interaction = result.metadata["native_result"]["interaction_energy_hartree"]
            attempt.quantities.append(Quantity(name="interaction_energy", value=interaction, units="hartree",
                definition="native SAPT intermolecular interaction energy; not a total electronic energy",
                method=method, attempt_id=attempt.attempt_id, validity=attempt.validation_status))
        if result.gradient_hartree_per_bohr is not None:
            attempt.quantities.append(Quantity(name="cartesian_gradient", value=result.gradient_hartree_per_bohr,
                units="hartree/bohr", definition="actual native analytic electronic gradient",
                method=method, attempt_id=attempt.attempt_id, validity=attempt.validation_status))
        if result.status == "completed":
            if cfour_authority is not None:
                _current_cfour_authority(workflow, record)
            _verified_component(attempt, store, molecule, protocol_data, identity, cfour_authority)
        else:
            record.status = result.status
            record.metadata["termination_reason"] = f"Matrix component {key}: " + str(result.diagnostics.get("reason", result.status))
        store.commit(record)
        if result.status == "completed" and (deadline <= time.monotonic() or cancel_event is not None and cancel_event.is_set()):
            record.status = "cancelled" if cancel_event is not None and cancel_event.is_set() else "timed-out"
            record.metadata["termination_reason"] = "Matrix component stopped during completed-evidence verification"
            store.commit(record)
            return None
        return result if result.status == "completed" else None
    except Exception as exc:
        # A commit can publish successfully and then lose its acknowledgement.
        # Verify the independent published snapshot before rewriting its attempt.
        published_completion, recovery_error = None, None
        try:
            published = RunRecord.model_validate(store.load())
            persisted = next((a for a in published.attempts if a.attempt_id == attempt.attempt_id), None)
            if (persisted is not None and persisted.status not in {"queued", "running"}
                    and persisted.model_dump(mode="json") == attempt.model_dump(mode="json")):
                published_completion = published
                if (cfour_authority is not None
                        and published.metadata.get("cfour_runtime_authority") != cfour_authority):
                    raise IntegrityError("Published CFOUR component changed its campaign runtime authority")
                cached = checked_cached(persisted) if persisted.status == "completed" else None
                record.attempts = published.attempts
                if cached is not None or persisted.status != "completed":
                    record.status, record.metadata = published.status, published.metadata
                return cached
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as recovery_exc:
            recovery_error = recovery_exc
        if published_completion is not None:
            # Published attempts are immutable historical facts, even when a
            # changed installation makes their current reuse unauthorized.
            record.attempts, record.metadata = published_completion.attempts, published_completion.metadata
            record.status = "failed"
            record.metadata["termination_reason"] = f"Published matrix component recovery rejected: {recovery_error}"
            store.commit(record)
            raise IntegrityError(record.metadata["termination_reason"]) from recovery_error
        attempt.status, attempt.converged, attempt.validation_status = "failed", False, "rejected"
        attempt.finished_at, attempt.quantities = utc_now(), []
        attempt.diagnostics.update({"reason": str(exc), "exception_type": type(exc).__name__})
        record.status, record.metadata["termination_reason"] = "failed", f"Matrix component {key}: {exc}"
        # Preserve actual raw files even if postprocessing or receipt publication
        # failed. Never follow links or accept evidence outside this attempt.
        roles = {a.path:a.role for a in attempt.artifacts}
        attempt.artifacts = []
        if folder.is_dir():
            for path in sorted(folder.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    try:
                        native = confined_file(folder, path.relative_to(folder).as_posix())
                    except IntegrityError:
                        continue
                    relative = native.relative_to(store.run_dir).as_posix()
                    attempt.artifacts.append(Artifact(path=relative, sha256=file_digest(native), size_bytes=native.stat().st_size,
                        role=roles.get(relative, "interrupted-native-evidence")))
        store.commit(record)
        raise
