"""Run one explicitly requested local CFOUR matrix diagnostic through BASE.

The request, executing sources and actual audited runtime are frozen before
calculation. Only verified scientific snapshot members enter --output; native
scratch stays in the separate --work-root. This does not certify a release,
chemical accuracy, or source-domain campaign coverage. Unmet conditions exit 3.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from pathlib import Path
from threading import Event, Timer
from typing import Any

import topos
from topos.actions.hosted_worker import stage_committed_run
from topos.base_integration import BaseRuntime
from topos.campaign_authority import base_authority_evidence, retained_registries
from topos.cfour_artifacts import validate_scientific_export_membership
from topos.config import SystemConfig
from topos.external_matrix_workflow import EXTERNAL_ROWS, junchs_protocols, protocol_for_row
from topos.matrix_components import run_component
from topos.matrix_workflow import MatrixInputs
from topos.method_matrix import MATRIX_REVISION
from topos.models import RunRecord, RunRequest, utc_now
from topos.release import source_inventory
from topos.storage import RunStore, atomic_json, digest_json, file_digest
from topos.workflow import Workflow

SOURCE_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_ROWS = frozenset(row for row in EXTERNAL_ROWS if row.startswith("T3C-"))


class AcceptanceFailure(RuntimeError):
    """A diagnostic condition has not been established."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def executing_sources(source_root: Path, package_root: Path | None = None) -> dict:
    """Bind imported package content, including unexpected files, to reviewed source."""
    package = (package_root or Path(topos.__file__).resolve().parent).resolve()
    inventory = source_inventory(source_root)
    expected = {Path(name).relative_to("topos").as_posix(): digest
                for name, digest in inventory.items() if Path(name).parts[0] == "topos"}
    files = list(package.rglob("*.py")) + list((package / "data").glob("*.json"))
    require(not any(path.is_symlink() for path in files), "Imported TOPOS sources cannot be symbolic links")
    observed = {path.relative_to(package).as_posix(): file_digest(path) for path in files}
    require(bool(expected) and observed == expected,
            "Imported TOPOS package differs from the declared source tree")
    return {"source_root": str(source_root.resolve()), "package_root": str(package),
            "source_files": inventory, "source_inventory_sha256": digest_json(inventory),
            "imported_package_matches_source": True}


def validate_request(payload: dict) -> tuple[RunRequest, MatrixInputs]:
    request = RunRequest.model_validate(payload)
    require(request.purpose == "matrix" and request.matrix_row_id in SUPPORTED_ROWS,
            "This diagnostic supports only the six ordinary CFOUR T3C external matrix recipes")
    require(request.matrix_revision == MATRIX_REVISION, "The exact archived matrix revision is required")
    require(request.calculation_environment == "local" and request.device == "cpu",
            "This diagnostic requires a local CPU request")
    inputs = MatrixInputs.model_validate(request.matrix_inputs)
    protocol = protocol_for_row(request.matrix_row_id, inputs.external_protocol)
    require(protocol.engine_version == "2.1", "This diagnostic requires native CFOUR 2.1")
    if protocol.operation == "optimize":
        require(inputs.external_resolution == "cfour-topos-cartesian-optimizer-v1",
                "CFOUR geometry requires its explicit TOPOS Cartesian optimizer resolution")
    # All choices remain the caller's exact typed values. In particular, this
    # does not supply isotope identities, nuclear moments, or EFG declarations.
    return request, inputs


def _fresh_path(value: Path) -> Path:
    path = value.expanduser().absolute()
    require(not any(part.is_symlink() for part in (path, *path.parents)),
            "Diagnostic paths cannot traverse symbolic links")
    path = path.resolve()
    require(not path.exists(), "Diagnostic output and work directories must be fresh")
    require(not path.is_relative_to(SOURCE_ROOT), "Diagnostic directories must remain outside TOPOS source")
    require(not SOURCE_ROOT.is_relative_to(path), "Diagnostic directories cannot contain TOPOS source")
    return path


def _copy_bound(source: Path, destination: Path) -> str:
    require(source.is_file() and not source.is_symlink(), "Authority and request inputs must be regular files")
    digest = file_digest(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, destination.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
    require(file_digest(source) == digest and file_digest(destination) == digest,
            "An input changed while its predeclaration was retained")
    return digest


def _input_path(value: Path) -> Path:
    path = value.expanduser().absolute()
    require(not any(part.is_symlink() for part in (path, *path.parents)),
            "Authority and request input paths cannot traverse symbolic links")
    return path.resolve()


def _record_proof(record: RunRecord, store: RunStore, registries: dict) -> dict:
    manifest = store.verify()
    payload = record.model_dump(mode="json")
    require(store.load() == payload, "Returned record differs from its committed snapshot")
    membership = validate_scientific_export_membership(payload, manifest)
    proof = base_authority_evidence(payload, store, registries)
    native = [attempt for attempt in record.attempts
              if attempt.command and attempt.command[0] != "topos-internal"]
    require(bool(native), "No actual native calculation was retained")
    require(all(attempt.engine == "cfour" and attempt.engine_version == "2.1"
                and attempt.status == "completed" and attempt.converged is True
                and attempt.validation_status == "validated-for-protocol"
                and attempt.metadata.get("execution_kind") == "real" for attempt in native),
            "A requested native CFOUR calculation is incomplete or lacks genuine validated evidence")
    return {"snapshot_id": manifest["snapshot_id"], "record_sha256": manifest["record_sha256"],
            "scientific_export_membership": membership, "base_authority": proof,
            "native_attempt_ids": [attempt.attempt_id for attempt in native]}


class _ReadOnlyReplayStore:
    """Forbid a cache miss from altering the original calculation's history."""

    def __init__(self, store: RunStore):
        self.store = store

    def __getattr__(self, name: str) -> Any:
        return getattr(self.store, name)

    def commit(self, *args: Any, **kwargs: Any) -> None:
        raise AcceptanceFailure("Read-only replay cannot checkpoint or start another calculation")


def replay_components(workflow: Workflow, record: RunRecord, store: RunStore, inputs: MatrixInputs,
                      deadline: float, event: Event) -> dict:
    """Exercise real cache authorization/parsing, with every new launch prohibited."""
    if deadline <= time.monotonic() or event.is_set():
        return {"status": "not-run", "reason": "Shared diagnostic budget exhausted",
                "additional_native_launches": 0}
    row = record.request.matrix_row_id
    protocol = protocol_for_row(row, inputs.external_protocol)
    components = ({"external-T3C-3d-" + role: component for role, component in junchs_protocols(protocol).items()}
                  if row == "T3C-3d" else {"external-" + row: protocol})
    before = store.verify()
    stored = store.load()
    copied = record.model_copy(deep=True)

    def forbid_execution(*args: Any, **kwargs: Any) -> None:
        raise AcceptanceFailure("Read-only replay cannot execute a native calculation")

    replayed = []
    for key, component in components.items():
        result = run_component(workflow, copied, _ReadOnlyReplayStore(store), key,
                               record.request.molecule, component, forbid_execution, deadline, event)
        require(result is not None, "Authenticated replay did not finish inside the shared diagnostic budget")
        replayed.append(key)
    require(store.verify() == before and store.load() == stored,
            "Read-only replay changed the original committed calculation")
    require([attempt.model_dump(mode="json") for attempt in copied.attempts]
            == [attempt.model_dump(mode="json") for attempt in record.attempts],
            "Authenticated replay changed native attempts or quantities")
    return {"status": "passed", "component_keys": replayed, "additional_native_launches": 0,
            "scope": "Fresh sealed-runtime authorization and production cache/raw-property verification; new execution is prohibited"}


def run_acceptance(registry: Path, request_file: Path, output: Path, work_root: Path, *,
                   budget_seconds: float | None = None, replay: bool = False) -> tuple[dict, int]:
    output, work_root = _fresh_path(output), _fresh_path(work_root)
    require(not output.is_relative_to(work_root) and not work_root.is_relative_to(output),
            "Scientific evidence and controlled native scratch must be separate directories")
    output.mkdir(parents=True)
    work_root.mkdir(parents=True)
    started = time.monotonic()
    report: dict[str, Any] = {
        "schema_version": "topos-cfour-local-diagnostic/1", "status": "failed", "started_at": utc_now(),
        "scope": "One explicit native matrix calculation and scientific storage/authority checks",
        "release_eligible": False, "scientific_accuracy_certified": False,
        "full_matrix_campaign_certified": False, "native_rerun_self_contained": False,
        "predeclaration": None, "run": None,
        "replay": {"status": "not-run", "reason": "Not requested" if not replay else "Calculation not yet verified",
                   "additional_native_launches": 0},
        "checks": {"sources_unchanged": None, "registry_unchanged": None,
                   "setup_summary_unchanged": None, "request_unchanged": None, "runtime_unchanged": None},
        "controlled_work_root": str(work_root),
    }
    timer, runtime, record, request, inputs = None, None, None, None, None
    source_before, runtime_before, bound_inputs = None, None, {}
    error = None
    event = Event()
    try:
        source_before = executing_sources(SOURCE_ROOT)
        registry, request_file = _input_path(registry), _input_path(request_file)
        bound_inputs["request_unchanged"] = (request_file, _copy_bound(request_file, output / "request-original.json"))
        request, inputs = validate_request(json.loads((output / "request-original.json").read_text(encoding="utf-8")))
        shared_budget = request.budget_seconds if budget_seconds is None else budget_seconds
        require(not isinstance(shared_budget, bool) and math.isfinite(shared_budget) and 0 < shared_budget <= request.budget_seconds,
                "The shared diagnostic budget must be finite, positive and no larger than the original request budget")
        deadline = started + shared_budget
        report["budget"] = {"shared_seconds": shared_budget, "request_seconds": request.budget_seconds,
                            "scope": "Preflight, calculation and optional replay share one wall-clock deadline; final evidence storage may outlive it"}
        bound_inputs["registry_unchanged"] = (registry, _copy_bound(registry, output / "authority" / registry.name))
        summary = registry.parent / "setup_summary.json"
        bound_inputs["setup_summary_unchanged"] = (summary, _copy_bound(summary, output / "authority" / "setup_summary.json"))
        registries, authority = retained_registries(output, [output / "authority" / registry.name])
        runtime = BaseRuntime(registry)
        runtime.validate_resources(request.resources)
        runtime_before = runtime.cfour_runtime_identity()
        native = runtime.registry.model_dump(mode="json")["engines"]["cfour"]
        genbas = native["runtime_metadata"]["basis"]["GENBAS"]
        require(Path(inputs.external_protocol.genbas_path).resolve() == Path(genbas["path"]).resolve()
                and inputs.external_protocol.genbas_sha256 == genbas["sha256"],
                "Requested GENBAS differs from the actual audited runtime dependency")
        predeclaration = {"declared_at": utc_now(), "coverage_scope": "diagnostic-control",
                          "request": request.model_dump(mode="json"),
                          "request_sha256": digest_json(request.model_dump(mode="json")),
                          "original_request_file_sha256": bound_inputs["request_unchanged"][1],
                          "source": source_before, "runtime": runtime_before,
                          "base": runtime.provenance(), "retained_authority": authority,
                          "acceptance_script_sha256": file_digest(Path(__file__)),
                          "timestamp_scope": "Local predeclaration; not an independent timestamping service"}
        atomic_json(output / "predeclaration.json", predeclaration)
        report["predeclaration"] = {"path": "predeclaration.json", "sha256": file_digest(output / "predeclaration.json")}
        atomic_json(output / "acceptance.json", report)
        require(deadline > time.monotonic(), "Shared diagnostic budget exhausted during preflight")
        timer = Timer(deadline - time.monotonic(), event.set)
        timer.daemon = True
        timer.start()
        workflow = Workflow(work_root / "runs", config=SystemConfig(execution_backend="base",
            base_registry_path=registry, max_threads=request.threads, max_memory_mb=request.memory_mb))
        record = workflow.run(request, cancel_event=event)
        store = RunStore(Path(record.metadata["run_dir"]))
        report["run"] = {"run_id": record.run_id, "status": record.status,
                         "termination_reason": record.metadata.get("termination_reason"),
                         "full_row_completed": record.metadata.get("matrix_execution", {}).get("full_row_completed") is True}
        report["run"].update(_record_proof(record, store, registries))
        require(record.status == "completed" and report["run"]["full_row_completed"],
                f"Requested full row did not complete: {record.metadata.get('termination_reason', record.status)}")
        if replay:
            report["replay"] = replay_components(workflow, record, store, inputs, deadline, event)
        require(not event.is_set() and time.monotonic() <= deadline, "Shared diagnostic budget exhausted")
    except Exception as exc:
        error = {"exception_type": type(exc).__name__, "message": str(exc)}
    finally:
        if timer is not None:
            timer.cancel()
        if source_before is not None:
            try:
                report["checks"]["sources_unchanged"] = executing_sources(SOURCE_ROOT) == source_before
            except Exception:
                report["checks"]["sources_unchanged"] = False
        for key, (path, digest) in bound_inputs.items():
            try:
                report["checks"][key] = path.is_file() and not path.is_symlink() and file_digest(path) == digest
            except OSError:
                report["checks"][key] = False
        if runtime_before is not None:
            try:
                report["checks"]["runtime_unchanged"] = runtime.cfour_runtime_identity() == runtime_before
            except Exception as exc:
                report["checks"]["runtime_unchanged"] = False
                report["runtime_finalization_error"] = {"exception_type": type(exc).__name__, "message": str(exc)}
        if request is not None:
            try:
                # A failure may occur after commit and before Workflow returns.
                # Only this fresh, single-invocation execution root is inspected.
                if record is None and (work_root / "runs").is_dir():
                    runs = [path for path in (work_root / "runs").iterdir() if path.is_dir() and not path.is_symlink()]
                    require(len(runs) == 1, "No unique committed run is available for failure evidence")
                    record = RunRecord.model_validate(RunStore(runs[0]).load())
                if record is not None:
                    store = RunStore(Path(record.metadata["run_dir"]))
                    require(store.run_dir.parent == work_root / "runs", "Returned run escaped its assigned execution root")
                    report["scientific_export"] = stage_committed_run(store.run_dir, output,
                        digest_json(request.model_dump(mode="json")))
                    if report["run"] is None:
                        report["run"] = {"run_id": record.run_id, "status": record.status,
                            "termination_reason": record.metadata.get("termination_reason"), "recovered_failure_snapshot": True}
            except Exception as exc:
                report["export_error"] = {"exception_type": type(exc).__name__, "message": str(exc)}
                error = error or report["export_error"]
        passed = (error is None and all(value is True for value in report["checks"].values())
                  and report.get("scientific_export") is not None)
        report["status"] = "passed" if passed else "failed"
        if error is not None:
            report["failure"] = error
        elif not passed:
            report["failure"] = {"exception_type": "AcceptanceFailure", "message": "Source/input/runtime identity or scientific export verification failed"}
        report["finished_at"] = utc_now()
        report["elapsed_seconds"] = time.monotonic() - started
        atomic_json(output / "acceptance.json", report)
    return report, 0 if report["status"] == "passed" else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--budget-seconds", type=float)
    parser.add_argument("--replay", action="store_true", help="Verify completed component reuse without allowing another native calculation")
    args = parser.parse_args(argv)
    try:
        report, code = run_acceptance(args.registry, args.request, args.output, args.work_root,
                                     budget_seconds=args.budget_seconds, replay=args.replay)
    except (AcceptanceFailure, OSError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        return 3
    print(json.dumps({"status": report["status"], "failure": report.get("failure"),
                      "receipt": str(args.output.resolve() / "acceptance.json")}, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
