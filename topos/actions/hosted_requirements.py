"""Derive hosted installation needs from the same registered scientific recipes.

The pre-provisioning CLI needs only the standard library and Pydantic (for typed
matrix plans). Chemistry validation remains mandatory inside the installed worker.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from typing import Any


def required_calculation_engines(request: dict[str, Any]) -> set[str]:
    """Classify registered execution dependencies, independently of a host.

    This is an installation plan, not an availability or scientific-completion
    attestation. Executors must separately validate their supported engines,
    models, hardware, complete typed inputs, and native execution authority.
    """
    if request.get("purpose") == "matrix":
        from ..data.runtime_recipes import EXECUTABLE_ROWS, IMPLEMENTED_BRANCH_ROWS
        from ..method_matrix import resolve_row, resolved_recipe

        row = resolve_row(request.get("matrix_row_id"), product=request.get("matrix_product", "A"))
        if row.row_id not in EXECUTABLE_ROWS | IMPLEMENTED_BRANCH_ROWS or row.owner != "TOPOS" or row.track_gap:
            raise ValueError("Execution requires a registered, complete TOPOS matrix recipe")
        matrix_inputs = request.get("matrix_inputs") or request.get("metadata", {}).get("matrix_inputs", {})
        if not isinstance(matrix_inputs, dict):
            raise ValueError("Matrix execution requires structured typed inputs")
        source_resolution = matrix_inputs.get("source_resolution")
        if row.row_id in IMPLEMENTED_BRANCH_ROWS and source_resolution is None:
            raise ValueError("Partial matrix branch requires an explicit compiled source resolution")
        steps, _ = resolved_recipe(row, source_resolution)
        engines: set[str] = set()
        for step in steps:
            if step.engine == "topos":
                continue
            if step.engine == "orca+crest" and step.method in {"GFN2-xTB", "custom-MLFF"}:
                # Only these compiled union recipes name this compound label.
                # The custom-MLFF variant also declares its MACE training step;
                # retaining that dependency prevents a free-only provisioner
                # from treating the composite as an ordinary xTB calculation.
                engines.update({"orca", "crest", "xtb"})
            elif step.engine == "orca+aimnet2" and step.method == "AIMNet2":
                # execute_ml_search performs genuine common ORCA refinement
                # and native CREGEN after enumeration, in addition to the
                # named AIMNet2 ExtOpt dependency. Do not omit those engines.
                engines.update({"orca", "aimnet2", "crest", "xtb"})
            elif step.engine in {"xtb", "crest", "orca", "cfour", "psi4", "mace", "mlff"}:
                engines.add(step.engine)
            else:
                raise ValueError("No compiled execution dependency mapping matches this matrix method; "
                                 "source-conflicted recipes require an explicit reviewed source resolution")
        if not engines:
            raise ValueError("Matrix recipe declares no compiled calculation engine")
        if "crest" in engines or any(step.engine == "orca" and step.method == "GFN2-xTB" for step in steps):
            engines.add("xtb")
        return engines
    engine = request.get("engine")
    if engine not in {"xtb", "orca"}:
        raise ValueError("Primitive execution requires an explicit supported native engine")
    engines = {engine}
    if request.get("search_algorithm") in {"crest", "union"}:
        engines.update({"crest", "xtb"})
    elif request.get("search_algorithm") == "abcluster":
        engines.add("abcluster")
    return engines


def required_native_engines(request: dict[str, Any]) -> set[str]:
    """Apply the generic hosted controller's installation profile explicitly."""
    engines = required_calculation_engines(request)
    if "abcluster" in engines:
        raise ValueError("ABCluster requires an unsupported hosted engine installation in this generic controller. "
                         "Use an audited BASE installation with the actual rigidmol binary and parameters.")
    if not engines <= {"xtb", "crest", "orca"}:
        raise ValueError("Matrix recipe requires an unsupported hosted engine installation in this generic controller. "
                         "CFOUR jobs use CoChem-BASE's separate private TOPOS calculation workflow; other "
                         "recipes require an executor that actually provisions their declared engines and hardware.")
    return engines


def validate_submission(encoded: str, expected_sha256: str, dispatch_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"(?:topos_[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})", dispatch_id):
        raise ValueError("Invalid dispatch correlation ID")
    if len(encoded) > 50_000 or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Invalid hosted request size or checksum")
    request = json.loads(base64.b64decode(encoded, validate=True))
    if not isinstance(request, dict):
        raise ValueError("Hosted request must be a JSON object")
    canonical = json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != expected_sha256:
        raise ValueError("Hosted request checksum differs from its dispatch")
    engines = required_native_engines(request)
    return {"native_engines": sorted(engines), "requires_orca": "orca" in engines}


def main() -> None:
    result = validate_submission(os.environ.get("TOPOS_REQUEST_B64", ""),
                                 os.environ.get("TOPOS_REQUEST_SHA256", ""),
                                 os.environ.get("TOPOS_DISPATCH_ID", ""))
    if result["requires_orca"] and os.environ.get("ORCA_CLOUD_LICENSE_CONFIRMED") != "true":
        raise ValueError("The selected recipe requires the configured ORCA cloud installation decision")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"licensed={'true' if result['requires_orca'] else 'false'}\n")


if __name__ == "__main__":
    main()
