"""Portable BASE audit verification shared by physical release campaigns.

This verifies retained execution authority only. Native scientific observables,
current source identity and protocol completion require their separate verifiers.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .storage import (
    IntegrityError,
    RunStore,
    confined_file,
    digest_json,
    file_digest,
    read_json,
    safe_relative,
)

SHA = r"[a-f0-9]{64}"


def retained_registries(bundle_root: Path, paths: list[Path]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Verify portable audit bytes, without consulting the originating machine."""
    registries, receipts = {}, []
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(bundle_root):
            raise IntegrityError("BASE registry snapshots must be regular files inside the campaign bundle")
        relative = safe_relative(path.resolve().relative_to(bundle_root).as_posix())
        retained = confined_file(bundle_root, relative)
        try:
            from cochem_base.cochem_core_registry_schema import CoChemSystemConfig

            registry = CoChemSystemConfig.model_validate(read_json(retained))
            if (registry.status not in {"LOCKED", "ACTIVE", "PASSED", "DEGRADED_OPERATIONAL"}
                    or not registry.verify_checksum() or registry.stage0 is None):
                raise ValueError("A completed Stage 0 audit and valid Golden Registry checksum are required")
        except (ImportError, ValueError, TypeError) as exc:
            raise IntegrityError(f"Retained BASE registry cannot establish audited execution authority: {exc}") from exc
        summary_relative = (Path(relative).parent / "setup_summary.json").as_posix()
        summary_path = confined_file(bundle_root, summary_relative)
        summary = read_json(summary_path)
        try:
            original_path = Path(summary["registry_path"])
            if (summary.get("dry_run") is not False or not original_path.is_absolute()
                    or original_path.parent.parent != Path(summary["artifact_dir"])):
                raise ValueError("Actual setup summary must identify its original authority root and executed setup")
            entries = summary["phases_executed"]
            if sorted(entry["phase_number"] for entry in entries) != list(range(1, 12)):
                raise ValueError("Actual setup summary requires each mandatory phase one through eleven exactly once")
            phases = {phase.phase_number: phase for phase in registry.stage0.phases}
            phase_proofs = []
            for entry in entries:
                phase = phases[entry["phase_number"]]
                report = entry["report"]
                report_digest = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
                if (phase.status not in {"PASSED", "DEGRADED"} or entry.get("success") is not True
                        or entry["status"] != phase.status or report.get("status") != phase.status
                        or report.get("errors") or report_digest != phase.sha256):
                    raise ValueError("Actual phase status, unresolved errors or report bytes contradict the Golden Registry audit")
                phase_proofs.append({"phase_number": phase.phase_number, "status": phase.status,
                                     "report_sha256": report_digest, "audit_errors": False})
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityError(f"Retained BASE setup reports cannot establish actual audited authority: {exc}") from exc
        digest = file_digest(retained)
        if digest in registries:
            raise IntegrityError("Duplicate retained BASE registry identities do not add authority")
        registries[digest] = {**registry.model_dump(mode="json"), "retained_setup_registry_path": str(original_path)}
        receipts.append({"path": relative, "registry_sha256": digest, "registry_checksum": registry.registry_checksum,
                         "setup_summary_path": summary_relative, "setup_summary_sha256": file_digest(summary_path),
                         "verified_phase_reports": phase_proofs})
    return registries, receipts


def base_authority_evidence(record: dict[str, Any], store: RunStore,
                             registries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Bind the parent and each copied native child to the actual audited engine."""
    from .models import RunRecord

    snapshot = store.snapshot_path() / "artifacts"

    def authority_for(observation: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        authority = observation["metadata"].get("execution_authority", {})
        digest = authority.get("registry_sha256")
        ecosystem = authority.get("ecosystem", {})
        components = ecosystem.get("components", {})
        if (authority.get("backend") != "cochem-base" or observation["metadata"].get("execution_provider") != "CoChem-BASE"
                or ecosystem.get("available") is not True or ecosystem.get("problems")
                or any(components.get(name, {}).get("available") is not True
                       for name in ("CoChem-BASE", "CoChem-TOPOS", "CoChem-TORQ"))):
            raise IntegrityError("Release calculation coverage requires the mandatory BASE execution authority for parent and every child")
        registry = registries.get(digest)
        if (not registry or authority.get("registry_checksum") != registry["registry_checksum"]
                or authority.get("registry_path") != registry["retained_setup_registry_path"]):
            raise IntegrityError("BASE authority lacks its exact independently verified retained Stage 0 registry")
        resources = observation["request"]
        hardware = registry["hardware"]
        if (resources["threads"] > hardware["allocatable_compute_cores"]
                or resources["memory_mb"] > hardware["ram_gb"] * 1024):
            raise IntegrityError("Run allocation exceeds its retained audited BASE hardware")
        return digest, registry

    parent_digest, parent_registry = authority_for(record)
    children = {}
    declarations = record["metadata"].get("matrix_execution", {}).get("children", [])
    artifacts = [a for a in record["artifacts"] if a["role"] == "matrix-child-record"]
    for artifact in artifacts:
        child = read_json(confined_file(snapshot, artifact["path"]))
        canonical = RunRecord.model_validate(child).model_dump(mode="json")
        if canonical != child or Path(artifact["path"]).stem != digest_json(child):
            raise IntegrityError("Retained matrix child record is not its exact canonical immutable identity")
        matches = [item for item in declarations if item["run_id"] == child["run_id"]]
        components = [a["metadata"].get("matrix_component", {}) for a in record["attempts"]
                      if a["metadata"].get("matrix_component", {}).get("child_run_id") == child["run_id"]]
        tasks = {item.get("task_id") for item in components}
        # Relaxed-scan gradient records are retained by _append_child but are
        # listed in the scan evaluation receipt rather than children[]. The
        # exact immutable child plus copied attempt identities still bind them.
        if (len(matches) > 1 or child["run_id"] in children or len(tasks) != 1 or None in tasks
                or matches and (matches[0]["record_sha256"] != digest_json(child) or matches[0]["task_id"] not in tasks)):
            raise IntegrityError("Retained matrix child lacks its unique exact full-row compiler declaration")
        digest, registry = authority_for(child)
        declaration = matches[0] if matches else {"task_id": tasks.pop()}
        children[child["run_id"]] = (child, declaration, digest, registry, artifact["path"])
    if not {item["run_id"] for item in declarations} <= set(children):
        raise IntegrityError("Every declared matrix child requires its independently retained exact BASE authority")
    proofs = []
    for attempt in record["attempts"]:
        if attempt["status"] != "completed" or not attempt["command"] or attempt["command"][0] == "topos-internal":
            continue
        component = attempt["metadata"].get("matrix_component")
        digest, registry = parent_digest, parent_registry
        owner = record
        if component:
            child, declaration, digest, registry, child_path = children.get(component.get("child_run_id"), (None,) * 5)
            if child is None or component.get("task_id") != declaration["task_id"]:
                raise IntegrityError("Native parent attempt lacks its genuine declared child authority")
            matches = [item for item in child["attempts"] if item["attempt_id"] == attempt["attempt_id"]]
            if len(matches) != 1:
                raise IntegrityError("Copied native attempt is absent from its retained child record")
            original = matches[0]
            copied = dict(attempt)
            copied["run_id"] = child["run_id"]
            copied["metadata"] = {key: value for key, value in copied["metadata"].items() if key != "matrix_component"}
            prefix = Path(child_path).parent.parent
            copied["artifacts"] = [{**a, "path": Path(a["path"]).relative_to(prefix).as_posix()} for a in copied["artifacts"]]
            if copied != original:
                raise IntegrityError("Copied native attempt differs from the exact retained child execution")
            owner = child
        engine = attempt["engine"]
        native = registry["engines"].get(engine)
        if (not isinstance(native, dict) or native.get("status") not in {"found", "ready"}
                or native.get("path") != attempt["command"][0]
                or not re.fullmatch(SHA, str(native.get("hash", "")))):
            raise IntegrityError("Native command contradicts its independently retained audited BASE executable")
        metadata = attempt["metadata"]
        allocation = metadata.get("resources", metadata.get("protocol", {}).get("resources"))
        if allocation and (allocation["threads"] > owner["request"]["threads"]
                           or allocation["memory_mb"] > owner["request"]["memory_mb"]):
            raise IntegrityError("Native allocation exceeds its declared BASE request ceiling")
        observed = metadata.get("crest_sha256") if engine == "crest" else metadata.get("executable_sha256")
        if engine in {"mace", "aimnet2"}:
            bindings = [(read_json(confined_file(snapshot, a["path"])), a["path"]) for a in attempt["artifacts"]
                        if Path(a["path"]).name.endswith("-authority.json")]
            bindings = [(item, path) for item, path in bindings if item.get("schema_version") == "topos-base-ml-authority/0.1.0"
                        and item.get("engine") == engine]
            if not bindings or (metadata.get("role") != "experimental-fine-tuning" and len(bindings) != 1):
                raise IntegrityError("Native ML execution lacks its retained BASE worker authority")
            silo = registry["stage0"]["micro_silos"].get(native.get("track"), {})
            for binding, binding_path in bindings:
                worker = {"topos.ml_worker": "topos/ml_worker.py", "topos.ml_training_worker": "topos/ml_training_worker.py"}.get(binding.get("worker_module"))
                worker_digest = owner["metadata"].get("software", {}).get("source_files", {}).get(worker)
                allocation = binding.get("resources", {})
                folder = Path(binding_path).parent
                request_name = "training-worker-request.json" if worker == "topos/ml_training_worker.py" else "ml-request.json"
                probe_file = confined_file(snapshot, (folder / (Path(binding_path).stem + ".stdout")).as_posix())
                request_file = confined_file(snapshot, (folder / request_name).as_posix())
                if (binding.get("registry_sha256") != digest or binding.get("interpreter") != native["path"]
                        or binding.get("interpreter_sha256") != native["hash"]
                        or not worker_digest or binding.get("worker_sha256") != worker_digest
                        or binding.get("observed", {}).get("worker_sha256") != worker_digest
                        or read_json(probe_file) != binding.get("observed")
                        or file_digest(request_file) != binding.get("request_sha256")
                        or silo.get("python_executable") != native["path"]
                        or binding.get("observed", {}).get("packages") != silo.get("packages")
                        or binding.get("probe", {}).get("status") != "completed"
                        or binding.get("probe", {}).get("returncode") != 0
                        or allocation.get("threads", 0) > owner["request"]["threads"]
                        or allocation.get("memory_mb", 0) > owner["request"]["memory_mb"]):
                    raise IntegrityError("Retained BASE ML worker receipt contradicts audited interpreter or package authority")
                if allocation.get("device") == "gpu":
                    gpu = registry["hardware"]["gpu_compute_metrics"]
                    if (native.get("gpu_support") is not True or not isinstance(binding.get("gpu_index"), int)
                            or not 0 <= binding["gpu_index"] < gpu["device_count"]
                            or not isinstance(binding.get("gpu_memory_mb"), int)
                            or not 0 < binding["gpu_memory_mb"] <= gpu["vram_gb"] * 1024):
                        raise IntegrityError("Native ML GPU request exceeds retained BASE device authority")
            observed = native["hash"]
        if observed != native["hash"]:
            raise IntegrityError("Observed native executable identity differs from its retained BASE audit")
        proofs.append({"attempt_id": attempt["attempt_id"], "registry_sha256": digest,
                       "engine": engine, "executable_sha256": observed})
    if not proofs:
        raise IntegrityError("BASE registry metadata alone cannot certify a native calculation")
    return {"parent_registry_sha256": parent_digest,
            "child_run_ids": sorted(children), "native_attempts": proofs}
