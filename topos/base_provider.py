"""Explicit receiver for BASE's versioned module artifact handoff.

Discovery is side-effect free. Calling execute_handoff is a separate scientific
action with explicit chemistry and the same mandatory BASE authority as the CLI.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from threading import Event
from typing import Any

import numpy as np

from .config import SystemConfig, load_config
from .models import Artifact, RunRecord, RunRequest, utc_now
from .storage import RunStore, atomic_json, digest_json, file_digest

CONTRACT = "cochem.module-handoff/1"
OPERATIONS = ("energy", "gradient", "optimize", "search", "frequency", "thermochemistry", "association", "matrix")
HOSTED_BUDGET_SCHEMA = "cochem.topos-hosted-budget/1"
HOSTED_WORKFLOW = ".github/workflows/topos_calculation.yml"


def hosted_budget_context(control: dict[str, Any], request: RunRequest,
                          declared_request_sha256: str) -> tuple[float | None, dict[str, Any]]:
    """Check the separate BASE-authenticated control at the final provider boundary.

    BASE's controller authenticates the live private repository/run and passes
    this bounded control separately from the immutable scientific handoff. The
    isolated provider retains no GitHub credentials; it independently binds the
    control to the request and actual runner environment, and recalculates time.
    A request metadata label is never a replacement for this explicit argument.
    """
    from .actions.queue_budget import queue_accounting

    keys = {"schema_version", "request_sha256", "repository", "repository_id", "owner_id",
            "source_sha", "ref", "workflow_path", "run_id", "run_attempt", "workflow_created_at"}
    if (not isinstance(control, dict) or set(control) != keys
            or control.get("schema_version") != HOSTED_BUDGET_SCHEMA):
        raise ValueError("The hosted budget requires its exact separate BASE control")
    if (not isinstance(control["request_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", control["request_sha256"])
            or control["request_sha256"] != declared_request_sha256):
        raise ValueError("Hosted budget control differs from the declared scientific request")
    if (not isinstance(control["repository"], str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", control["repository"])
            or any(type(control[key]) is not int or control[key] < 1
                   for key in ("repository_id", "owner_id", "run_id", "run_attempt"))
            or not isinstance(control["source_sha"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", control["source_sha"])
            or control["source_sha"] == "0" * 40
            or not isinstance(control["ref"], str) or not control["ref"].startswith("refs/heads/")
            or len(control["ref"]) > 255 or any(ord(character) < 33 for character in control["ref"])
            or control["workflow_path"] != HOSTED_WORKFLOW):
        raise ValueError("Hosted budget requires the exact owning project/workflow/run/source identity")
    environment = {"GITHUB_REPOSITORY": control["repository"],
                   "GITHUB_REPOSITORY_ID": str(control["repository_id"]),
                   "GITHUB_REPOSITORY_OWNER_ID": str(control["owner_id"]),
                   "GITHUB_SHA": control["source_sha"], "GITHUB_REF": control["ref"],
                   "GITHUB_WORKFLOW_REF": f"{control['repository']}/{HOSTED_WORKFLOW}@{control['ref']}",
                   "GITHUB_RUN_ID": str(control["run_id"]), "GITHUB_RUN_ATTEMPT": str(control["run_attempt"])}
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or any(os.environ.get(key) != value for key, value in environment.items())
            or request.calculation_environment != "local" or request.device != "cpu"):
        raise ValueError("Hosted budget differs from the assigned local CPU Actions worker")
    if not isinstance(control["workflow_created_at"], str) or not control["workflow_created_at"].endswith("Z"):
        raise ValueError("Hosted budget requires the actual server-created UTC timestamp")
    accounting = queue_accounting(request.model_dump(mode="json"), control["workflow_created_at"], utc_now())
    if not request.include_queue_in_budget:
        accounting = None
    allocation = accounting["remaining_execution_seconds"] if accounting is not None else None
    return allocation, {"hosted_budget_control": control, "budget_accounting": accounting}


def metadata() -> dict[str, Any]:
    return {"module_id": "topos", "version": "0.1.0", "integration_contract": CONTRACT,
            "operations": list(OPERATIONS), "artifact_kinds": ["geometry_xyz"],
            "execution_verified": False, "execution": "explicit execute_handoff call through BASE authority"}


def request_from_handoff(manifest_path: str | Path) -> tuple[RunRequest, dict[str, Any]]:
    from cochem_base.geometry.nuclide_geometry import parse_geometry_identity
    from cochem_base.interfaces.artifact_handoff import load_module_handoff

    path = Path(manifest_path).expanduser().resolve(strict=True)
    if not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError("BASE handoff manifest must be a bounded regular JSON file")
    manifest_hash = file_digest(path)
    handoff = load_module_handoff(path)
    if handoff.module_id != "topos" or handoff.artifact.kind != "geometry_xyz":
        raise ValueError("This TOPOS receiver accepts BASE geometry_xyz handoffs addressed to TOPOS")
    if handoff.operation not in OPERATIONS:
        raise ValueError("BASE handoff operation has no matching TOPOS request adapter")
    if set(handoff.options) != {"topos_request"}:
        raise ValueError("BASE handoff options require exactly one explicit topos_request")
    payload = handoff.options["topos_request"]
    if not isinstance(payload, dict) or not isinstance(payload.get("molecule"), dict):
        raise ValueError("BASE handoff requires a complete typed molecular request")
    if not {"charge", "multiplicity"}.issubset(payload["molecule"]):
        raise ValueError("XYZ has no electronic state: declare charge and multiplicity explicitly")
    request = RunRequest.model_validate(payload)
    if request.purpose != handoff.operation:
        raise ValueError("BASE handoff operation and TOPOS scientific purpose differ")
    if "base_handoff" in request.metadata:
        raise ValueError("BASE provenance is populated by the verified receiver, not request metadata")
    artifact = path.parent / handoff.artifact.filename
    if artifact.stat().st_size > 2_000_000:
        raise ValueError("BASE XYZ handoff exceeds this receiver's input limit")
    raw = artifact.read_text(encoding="utf-8")
    # The immutable artifact retains its original labels and bytes. BASE 1.0.1
    # resolves elemental identity separately from explicit nuclear labels; no
    # isotope is inferred from XYZ's comment or silently dropped at this boundary.
    lines = raw.splitlines()
    try:
        count = int(lines[0].strip()) if len(lines) >= 2 else 0
    except ValueError as error:
        raise ValueError("BASE XYZ requires an explicit atom count") from error
    if (count < 1 or len(lines) < count + 2 or any(line.strip() for line in lines[count + 2:])
            or any(len(line.split()) != 4 for line in lines[2:count + 2])):
        raise ValueError("BASE XYZ must contain exactly one complete counted frame")
    identity = parse_geometry_identity(raw)
    for index, number in enumerate(identity.mass_numbers):
        if number is not None and (index >= len(request.molecule.isotopes)
                                   or request.molecule.isotopes[index] != number):
            raise ValueError("BASE artifact isotope differs from the explicit TOPOS request at atom " + str(index))
    if list(identity.elements) != request.molecule.symbols or not np.array_equal(
        np.asarray(identity.coordinates_angstrom), np.asarray(request.molecule.coordinates)
    ):
        raise ValueError("BASE artifact atom order/coordinates differ from the explicit TOPOS request")
    if file_digest(path) != manifest_hash or file_digest(artifact) != handoff.artifact.sha256:
        raise ValueError("BASE handoff changed during receiver validation")
    original = handoff.model_dump(mode="json")
    provenance = {"schema_version": CONTRACT, "handoff_id": handoff.handoff_id,
                  "manifest_file_sha256": manifest_hash, "manifest": original,
                  "artifact_sha256": handoff.artifact.sha256, "artifact_xyz": raw,
                  "declared_request_sha256": digest_json(request.model_dump(mode="json")),
                  "producer_scientific_execution_performed": False}
    # Include original input evidence in the immutable request before executing,
    # so interruption cannot leave an untraceable calculation.
    request.metadata["base_handoff"] = provenance
    return request, provenance


def execute_handoff(manifest_path: str | Path, output_root: str | Path, *,
                    config: SystemConfig | None = None,
                    cancel_event: Event | None = None,
                    hosted_budget: dict[str, Any] | None = None) -> dict[str, Any]:
    from .workflow import Workflow

    configuration = config or load_config()
    if configuration.execution_backend != "base":
        raise ValueError("The BASE module receiver requires mandatory BASE execution authority")
    request, provenance = request_from_handoff(manifest_path)
    allocation, context = None, None
    if hosted_budget is not None:
        allocation, context = hosted_budget_context(hosted_budget, request, provenance["declared_request_sha256"])
    elif request.include_queue_in_budget and os.environ.get("GITHUB_ACTIONS") == "true":
        raise ValueError("Queue-inclusive hosted execution requires BASE's separate authenticated budget control")
    record: RunRecord = Workflow(output_root, config=configuration).run(
        request, cancel_event=cancel_event, invocation_budget_seconds=allocation,
        invocation_budget_context=context,
    )
    folder = Path(record.metadata["run_dir"])
    receipt = {"schema_version": "topos-base-consumption/0.1.0", "received_at": utc_now(),
               "handoff_id": provenance["handoff_id"],
               "manifest_file_sha256": provenance["manifest_file_sha256"],
               "artifact_sha256": provenance["artifact_sha256"],
               "declared_request_sha256": provenance["declared_request_sha256"],
               "execution_request_sha256": digest_json(request.model_dump(mode="json")),
               "run_id": record.run_id, "status": record.status,
               "validation_status": record.validation_status,
               "execution_provider": record.metadata.get("execution_provider"),
               "source_snapshot_sha256": RunStore(folder).verify()["snapshot_id"]}
    if context is not None:
        control_path = folder / "base-hosted-budget-control.json"
        atomic_json(control_path, hosted_budget)
        record.artifacts.append(Artifact(path=control_path.name, sha256=file_digest(control_path),
                                         size_bytes=control_path.stat().st_size, role="base-hosted-budget-control"))
        receipt.update(hosted_budget_control_sha256=digest_json(hosted_budget),
                       budget_accounting=context["budget_accounting"])
    destination = folder / "base-consumption-receipt.json"
    atomic_json(destination, receipt)
    record.artifacts.append(Artifact(path=destination.name, sha256=file_digest(destination),
                                     size_bytes=destination.stat().st_size, role="base-consumption-receipt"))
    record.metadata["base_consumption"] = receipt
    RunStore(folder).commit(record)
    return {"receipt": receipt, "record": record.model_dump(mode="json")}


class ToposProvider:
    metadata = staticmethod(metadata)
    request_from_handoff = staticmethod(request_from_handoff)
    execute_handoff = staticmethod(execute_handoff)


provider = ToposProvider()
