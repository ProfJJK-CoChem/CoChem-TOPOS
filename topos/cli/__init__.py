"""Command line adapter to the same validated workflow used by BASE and the UI."""
from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError


def _emit(value: Any, *, error: bool = False) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), file=sys.stderr if error else sys.stdout)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="topos", description="CoChem-TOPOS 0.1.0 scientific workflow")
    parser.add_argument("--version", action="version", version="CoChem-TOPOS 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("capabilities", help="Inspect available engines, supported chemistry, and limitations")
    sub.add_parser("request-schema", help="Print the shared request JSON schema")
    doctor = sub.add_parser("doctor", help="Check the mandatory BASE/TOPOS/TORQ installation")
    doctor.add_argument("--verify-runtime", action="store_true", help="Also verify BASE Stage 0 registry authority")
    doctor.add_argument("--registry", type=Path, help="Explicit BASE system registry")
    matrix = sub.add_parser("matrix", help="Inspect authoritative purpose/time/hardware routes")
    matrix_sub = matrix.add_subparsers(dest="matrix_command", required=True)
    matrix_sub.add_parser("support", help="Separate compiled executable recipes from catalog-only routes")
    matrix_list = matrix_sub.add_parser("list", help="List the source-bound matrix rows")
    matrix_list.add_argument("--owner", choices=["TOPOS", "TORQ"])
    matrix_list.add_argument("--purpose")
    matrix_show = matrix_sub.add_parser("show", help="Show one exact row with source citations")
    matrix_show.add_argument("row_id")
    matrix_plan = matrix_sub.add_parser("plan", help="Validate a route against declared capabilities and allocation")
    matrix_plan.add_argument("row_id")
    matrix_plan.add_argument("--hardware", required=True, type=Path, help="HardwareSpec JSON file")
    matrix_plan.add_argument("--capabilities", type=Path, help="JSON array of verified BackendCapability records")
    matrix_plan.add_argument("--product", choices=["A", "B", "C"], default="A")
    matrix_plan.add_argument("--input", action="append", default=[], dest="available_inputs")
    matrix_plan.add_argument("--symbols", help="Comma-separated chemical element symbols")
    matrix_plan.add_argument("--charge", type=int, default=0)
    matrix_plan.add_argument("--multiplicity", type=int, default=1)
    run = sub.add_parser("run", help="Execute an explicit request; Ctrl-C cancels owned calculations")
    run.add_argument("--request", required=True, type=Path, help="UTF-8 request JSON file")
    run.add_argument("--output-root", required=True, type=Path, help="Directory for isolated per-run records")
    base_receiver = sub.add_parser("receive-base", help="Consume a BASE module handoff with its explicit TOPOS request")
    base_receiver.add_argument("manifest", type=Path)
    base_receiver.add_argument("--output-root", required=True, type=Path)
    resume = sub.add_parser("resume", help="Continue a compatible run from verified committed evidence")
    resume.add_argument("--run-dir", required=True, type=Path)
    inspect = sub.add_parser("inspect", help="Verify and read a committed run")
    inspect.add_argument("run_dir", type=Path)
    inspect.add_argument("--recover", action="store_true", help="Recover the last valid committed snapshot")
    decisions = sub.add_parser("decisions", help="Read the append-only review history")
    decisions.add_argument("run_dir", type=Path)
    basket = sub.add_parser("basket", help="Read candidates, eligibility, unresolved chemistry and review history")
    basket.add_argument("run_dir", type=Path)
    review = sub.add_parser("review", help="Record an explicit human decision with actor and reason")
    review.add_argument("run_dir", type=Path)
    review.add_argument("--subject", required=True)
    review.add_argument("--action", required=True, choices=["accept", "reject", "annotate", "needs-review", "withdraw"])
    review.add_argument("--actor", required=True)
    review.add_argument("--reason", required=True)
    review.add_argument("--supersedes")
    review.add_argument("--scope", default="candidate")
    review.add_argument("--annotations", type=Path, help="JSON annotation object; never changes raw observations")
    handoff = sub.add_parser("handoff", help="Freeze a reviewed ensemble manifest for TORQ")
    handoff.add_argument("run_dir", type=Path)
    handoff.add_argument("--member", required=True, action="append", help="Accepted candidate ID; repeat for each member")
    handoff.add_argument("--actor", required=True)
    handoff.add_argument("--reason", default="")
    handoff.add_argument("--expected-snapshot-sha256")
    handoff.add_argument("--destination", type=Path, help="Also export the versioned TORQ producer contract")
    transfer = sub.add_parser("export-handoff", help="Export the current reviewed ensemble for external TORQ consumption")
    transfer.add_argument("run_dir", type=Path)
    transfer.add_argument("--destination", required=True, type=Path)
    transfer.add_argument("--ensemble-sha256")
    verify_handoff = sub.add_parser("verify-handoff", help="Verify a portable TOPOS/TORQ handoff")
    verify_handoff.add_argument("path", type=Path)
    receipt = sub.add_parser("receive-torq", help="Validate an externally produced TORQ consumption receipt")
    receipt.add_argument("run_dir", type=Path)
    receipt.add_argument("--receipt", required=True, type=Path)
    ack = sub.add_parser("ack", help="Record operator manifest receipt only; does not establish TORQ consumption")
    ack.add_argument("run_dir", type=Path)
    ack.add_argument("--manifest-sha256", required=True)
    ack.add_argument("--actor", required=True)
    ack.add_argument("--schema-version", default="topos-ensemble/0.1.0")
    export = sub.add_parser("export", help="Build a verified local publication archive from the reviewed ensemble")
    export.add_argument("run_dir", type=Path)
    export.add_argument("--destination", required=True, type=Path, help="New bundle directory outside the live run directory")
    export.add_argument("--ensemble-sha256")
    export.add_argument("--license", dest="license_identifier", help="Author-supplied license identifier")
    verify = sub.add_parser("verify-export", help="Verify membership and digests of a local publication archive")
    verify.add_argument("destination", type=Path)
    return parser


def _with_cancellation(function: Any) -> Any:
    cancel_event = threading.Event()
    previous = {}
    if threading.current_thread() is threading.main_thread():
        def cancel(signum: int, frame: Any) -> None:
            cancel_event.set()
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, cancel)
    try:
        return function(cancel_event)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _run_file(request_file: Path, output_root: Path) -> Any:
    from topos.ui import parse_request_json, submit_request

    request = parse_request_json(request_file.read_text(encoding="utf-8"))
    return _with_cancellation(lambda event: submit_request(request, output_root, cancel_event=event))


def main(argv: list[str] | None = None) -> int:
    """Return 0 for a completed action, 2 for invalid input, or 3 for incomplete execution."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "capabilities":
            from topos.capabilities import capability_report
            result = capability_report()
        elif args.command == "doctor":
            from topos.base_integration import BaseRuntime, inspect_ecosystem
            result = inspect_ecosystem().to_dict()
            if args.verify_runtime:
                result["runtime"] = BaseRuntime(args.registry).provenance()
            _emit(result)
            return 0 if result["available"] else 3
        elif args.command == "matrix":
            from topos.method_matrix import (
                BackendCapability,
                HardwareSpec,
                load_catalog,
                plan_route,
            )
            from topos.ui import _parse_json
            catalog = load_catalog()
            if args.matrix_command == "support":
                from topos.matrix_workflow import execution_support_report
                result = execution_support_report()
            elif args.matrix_command == "list":
                result = {"revision": catalog.revision, "source_sha256": catalog.source_sha256,
                          "rows": [row.model_dump(mode="json") for row in catalog.rows
                                   if (not args.owner or row.owner == args.owner)
                                   and (not args.purpose or row.purpose == args.purpose)]}
            elif args.matrix_command == "show":
                result = catalog.get(args.row_id)
            else:
                hardware = HardwareSpec.model_validate(_parse_json(args.hardware.read_text(encoding="utf-8")))
                values = _parse_json(args.capabilities.read_text(encoding="utf-8")) if args.capabilities else []
                if not isinstance(values, list):
                    raise ValueError("Backend capabilities must be a JSON array")
                result = plan_route(args.row_id, hardware=hardware,
                                    capabilities=[BackendCapability.model_validate(value) for value in values],
                                    product=args.product, available_inputs=args.available_inputs,
                                    symbols=args.symbols.split(",") if args.symbols else None,
                                    charge=args.charge, multiplicity=args.multiplicity)
        elif args.command == "request-schema":
            from topos.models import RunRequest
            result = RunRequest.model_json_schema()
        elif args.command == "run":
            result = _run_file(args.request, args.output_root)
            _emit(result)
            return 0 if result.status == "completed" else 3
        elif args.command == "receive-base":
            from topos.base_provider import execute_handoff
            result = _with_cancellation(lambda event: execute_handoff(args.manifest, args.output_root, cancel_event=event))
            _emit(result)
            return 0 if result["record"]["status"] == "completed" else 3
        elif args.command == "resume":
            from topos.workflow import Workflow
            result = _with_cancellation(lambda event: Workflow(args.run_dir.parent).resume(args.run_dir, cancel_event=event))
            _emit(result)
            return 0 if result.status == "completed" else 3
        elif args.command == "inspect":
            from topos.storage import RunStore
            store = RunStore(args.run_dir)
            if args.recover:
                result = store.recover()
            else:
                store.verify()
                result = store.load()
        elif args.command == "decisions":
            from topos.review import list_decisions
            result = list_decisions(args.run_dir)
        elif args.command == "basket":
            from topos.review import review_basket
            result = review_basket(args.run_dir)
        elif args.command == "review":
            from topos.review import append_decision
            from topos.ui import _parse_json
            annotations = _parse_json(args.annotations.read_text(encoding="utf-8")) if args.annotations else None
            result = append_decision(args.run_dir, subject_id=args.subject, action=args.action,
                                     actor=args.actor, reason=args.reason, supersedes=args.supersedes,
                                     scope=args.scope, annotations=annotations)
        elif args.command == "handoff":
            from topos.review import create_ensemble_manifest
            result = create_ensemble_manifest(args.run_dir, args.member, actor=args.actor,
                                             reason=args.reason, expected_snapshot_sha256=args.expected_snapshot_sha256)
            if args.destination:
                from topos.review import export_torq_handoff
                result = export_torq_handoff(args.run_dir, args.destination,
                                             ensemble_sha256=result["manifest_sha256"])
        elif args.command == "export-handoff":
            from topos.review import export_torq_handoff
            result = export_torq_handoff(args.run_dir, args.destination, ensemble_sha256=args.ensemble_sha256)
        elif args.command == "verify-handoff":
            from topos.review import verify_torq_handoff
            result = verify_torq_handoff(args.path)
        elif args.command == "receive-torq":
            from topos.review import accept_torq_receipt
            result = accept_torq_receipt(args.run_dir, args.receipt)
        elif args.command == "ack":
            from topos.review import acknowledge_torq
            result = acknowledge_torq(args.run_dir, args.manifest_sha256, actor=args.actor,
                                      schema_version=args.schema_version)
        elif args.command == "export":
            from topos.publication import export_bundle
            result = export_bundle(args.run_dir, args.destination, ensemble_sha256=args.ensemble_sha256,
                                   license_identifier=args.license_identifier)
        else:
            from topos.publication import verify_bundle
            result = verify_bundle(args.destination)
        _emit(result)
        return 0
    except ValidationError as exc:
        _emit({"status": "invalid", "errors": [{"location": list(e["loc"]), "message": e["msg"]}
                                                 for e in exc.errors(include_input=False, include_url=False)]}, error=True)
        return 2
    except (OSError, ValueError, RuntimeError) as exc:
        _emit({"status": "error", "message": str(exc)}, error=True)
        return 2
    except KeyboardInterrupt:
        _emit({"status": "cancelled", "message": "Interrupted before a workflow could be committed."}, error=True)
        return 130


__all__ = ["main"]
