"""Request-correlated TOPOS calculations through BASE on a protected Actions runner."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
from pathlib import Path
from threading import Event
from typing import Any

from topos.actions.hosted_requirements import required_native_engines
from topos.actions.hosted_worker import (
    INVENTORY_SCHEMA,
    WorkerError,
    _fresh_roots,
    cancellation_signals,
    stage_committed_run,
    validate_hosted_context,
    verify_evidence,
)
from topos.config import SystemConfig
from topos.models import RunRequest, utc_now
from topos.storage import atomic_json, digest_json, file_digest
from topos.workflow import Workflow

RECEIPT_SCHEMA = "topos-compute-worker/0.1.0"


def decode_request(encoded: str, expected_sha256: str) -> tuple[dict[str, Any], RunRequest]:
    """Require canonical typed input and bind its semantic digest before execution."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or len(encoded) > 50_000:
        raise ValueError("Request digest or size is invalid")
    try:
        raw = base64.b64decode(encoded, validate=True)
        original = json.loads(raw.decode("utf-8"))
        request = RunRequest.model_validate(original)
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise ValueError("Request must be bounded base64-encoded TOPOS JSON") from exc
    canonical = request.model_dump(mode="json")
    if original != canonical or digest_json(canonical) != expected_sha256:
        raise ValueError("Request must contain canonical defaults and match its SHA-256")
    if request.calculation_environment not in {"github-actions", "github-actions-hosted"}:
        raise ValueError("Hosted request must explicitly select GitHub Actions")
    if request.include_queue_in_budget:
        raise ValueError("This hosted profile does not support charging Actions queue time to the scientific budget")
    if request.budget_seconds > 4 * 3600 or request.threads > 4 or request.memory_mb > 12_288:
        raise ValueError("Request exceeds this workflow's four-hour/4-core/12-GiB limits")
    required_native_engines(canonical)
    # Local execution is deliberate only inside this verified remote worker.
    local = RunRequest.model_validate({**canonical, "calculation_environment": "local"})
    return canonical, local


def run_compute_worker(encoded: str, expected_sha256: str, dispatch_id: str,
                       output_root: Path, evidence_root: Path) -> tuple[dict[str, Any], int]:
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA, "dispatch_id": dispatch_id,
        "request_sha256": expected_sha256, "request": None, "local_request_sha256": None,
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_sha": os.environ.get("GITHUB_SHA"), "started_at": utc_now(),
        "status": "failed", "run_path": None, "context_verified": False,
    }
    evidence = None
    exit_code = 2
    try:
        if not re.fullmatch(r"(?:topos_[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})", dispatch_id):
            raise ValueError("Invalid dispatch correlation ID")
        output, evidence, _ = _fresh_roots(output_root, evidence_root)
        original, local = decode_request(encoded, expected_sha256)
        context, _ = validate_hosted_context(require_orca_license="orca" in required_native_engines(original))
        receipt.update(context=context, context_verified=True)
        receipt.update(request=original, local_request_sha256=digest_json(local.model_dump(mode="json")))
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        if event.get("inputs") != {
            "dispatch_id": dispatch_id, "request_b64": encoded, "request_sha256": expected_sha256,
        }:
            raise ValueError("Worker request differs from the workflow dispatch event")
        registry = os.environ.get("COCHEM_CONFIG")
        if not registry or not Path(registry).is_file():
            raise ValueError("The verified BASE setup registry is required")
        config = SystemConfig(output_root=output, execution_backend="base", base_registry_path=Path(registry),
                              max_threads=4, max_memory_mb=12_288)
        cancel = Event()
        with cancellation_signals(cancel):
            record = Workflow(output, config=config).run(local, cancel_event=cancel)
        staged = stage_committed_run(Path(record.metadata["run_dir"]), evidence,
                                     receipt["local_request_sha256"])
        staged.pop("relative_paths")
        receipt.update(status=record.status, validation_status=record.validation_status,
                       run_path="run", run=staged)
        exit_code = 0 if record.status == "completed" else 3
    except (ValueError, RuntimeError, OSError) as exc:
        receipt["failure"] = {"code": exc.code if isinstance(exc, WorkerError) else type(exc).__name__,
                              "message": str(exc)}
    finally:
        receipt["finished_at"] = utc_now()
        if evidence is not None:
            atomic_json(evidence / "worker-receipt.json", receipt)
            members = [{"path": p.relative_to(evidence).as_posix(), "sha256": file_digest(p),
                        "size_bytes": p.stat().st_size} for p in sorted(evidence.rglob("*")) if p.is_file()]
            atomic_json(evidence / "evidence-inventory.json", {"schema_version": INVENTORY_SCHEMA, "files": members})
            verify_evidence(evidence)
    return receipt, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    args = parser.parse_args()
    receipt, code = run_compute_worker(os.environ.get("TOPOS_REQUEST_B64", ""),
                                      os.environ.get("TOPOS_REQUEST_SHA256", ""),
                                      os.environ.get("TOPOS_DISPATCH_ID", ""),
                                      args.output_root, args.evidence_root)
    # The artifact contains full evidence; logs need only its non-sensitive identity.
    print(json.dumps({key: receipt[key] for key in ("dispatch_id", "status", "github_run_id")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
