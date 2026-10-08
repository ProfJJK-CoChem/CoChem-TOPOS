"""Explicit receiver for BASE's versioned module artifact handoff.

Discovery is side-effect free. Calling execute_handoff is a separate scientific
action with explicit chemistry and the same mandatory BASE authority as the CLI.
"""
from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Any

import numpy as np

from .config import SystemConfig, load_config
from .models import Artifact, RunRecord, RunRequest, utc_now
from .storage import RunStore, atomic_json, digest_json, file_digest

CONTRACT = "cochem.module-handoff/1"
OPERATIONS = ("energy", "gradient", "optimize", "search", "frequency", "thermochemistry", "association", "matrix")


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
                    cancel_event: Event | None = None) -> dict[str, Any]:
    from .workflow import Workflow

    configuration = config or load_config()
    if configuration.execution_backend != "base":
        raise ValueError("The BASE module receiver requires mandatory BASE execution authority")
    request, provenance = request_from_handoff(manifest_path)
    record: RunRecord = Workflow(output_root, config=configuration).run(request, cancel_event=cancel_event)
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
