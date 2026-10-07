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


def required_native_engines(request: dict[str, Any]) -> set[str]:
    """Reject unknown routes; never make a free-only matrix row require ORCA."""
    if request.get("purpose") == "matrix":
        from ..data.runtime_recipes import EXECUTABLE_ROWS
        from ..method_matrix import _recipe, resolve_row

        row = resolve_row(request.get("matrix_row_id"), product=request.get("matrix_product", "A"))
        if row.row_id not in EXECUTABLE_ROWS or row.owner != "TOPOS" or row.track_gap:
            raise ValueError("Hosted execution requires a registered, complete TOPOS matrix recipe")
        steps, _ = _recipe(row)
        engines = {step.engine for step in steps} - {"topos"}
        if not engines or not engines <= {"xtb", "crest", "orca"}:
            raise ValueError("Matrix recipe requires an unsupported hosted engine installation")
        if "crest" in engines or any(step.engine == "orca" and step.method == "GFN2-xTB" for step in steps):
            engines.add("xtb")
        return engines
    engine = request.get("engine")
    if engine not in {"xtb", "orca"}:
        raise ValueError("Hosted execution requires an explicit supported native engine")
    engines = {engine}
    if request.get("search_algorithm") in {"crest", "union"}:
        engines.update({"crest", "xtb"})
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
