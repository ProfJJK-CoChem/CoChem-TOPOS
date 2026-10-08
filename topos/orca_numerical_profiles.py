"""Explicit ORCA numerical repair; legacy profiles retain their original meaning.

The retained water experiment establishes internal numerical consistency only.
It does not establish scientific accuracy or live acceptance of other routes.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

from .storage import IntegrityError

MAPPING_V42 = "orca-mapping-v4.2"
SUPPORTED_PROFILES = frozenset({"orca-mapping-v4.1", MAPPING_V42, "orca-vpt2-reference-v1"})
SCF_BLOCK = "%scf\n  ConvCheckMode 0\n  TolE 1e-10\nend\n"
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"


def numerical_profile_receipt(profile_id: str) -> dict | None:
    """Fresh canonical definition/identity; no relabeling of historical receipts."""
    if profile_id != MAPPING_V42:
        return None
    definition = {
        "schema": "topos-orca-numerical-profile/1", "profile_id": MAPPING_V42,
        "legacy_base_profile": "orca-mapping-v4.1", "engine_version": "6.1.1",
        "scf_keyword": "TightSCF", "scf_controls": {"ConvCheckMode": 0, "TolE": 1e-10},
        "unchanged_scf_targets": {"MAX-Density change": 1e-7, "RMS-Density change": 5e-9,
                                  "DIIS Error": 5e-7, "Orbital Gradient": 1e-5,
                                  "Orbital Rotation": 1e-5},
        "final_scf_policy": "All printed targets must match; all active final criteria must be achieved; DIIS residual is inactive after a native SOSCF switch",
        "grid_keyword": "DEFGRID3", "hamiltonian_changed": False,
        "optimizer_targets": {"TolE": 1e-7, "TolMaxG": 1e-5, "TolRMSG": 3e-6,
                              "TolRMSD": 5e-5, "TolMaxD": 1e-4},
        "optimizer_stopping_policy": "EnforceStrictConvergence true",
        "independent_final_gradient_energy_guard_hartree": 2e-7,
        "deadline_policy": "original caller budget; no extension",
    }
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"definition": definition, "definition_sha256": hashlib.sha256(canonical).hexdigest(),
            "manual": "https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/scf.html#convergence-tolerances",
            "retained_diagnostic": {"run_id": 37713499250,
                "verification_receipt_sha256": "7876cda4be0cc91dc91a3561d2f01398703cc46ac75ad08dafe2f04597d03b30",
                "scope": "historical-source wB97X-V/def2-TZVPP water consistency only; other methods and R2 require separate live evidence"}}


def observe_scf_numerical_profile(raw: str) -> dict:
    """Reparse native tables, including inactive residuals and failure reasons."""
    targets = {"Energy change": 1e-10, "MAX-Density change": 1e-7,
               "RMS-Density change": 5e-9, "DIIS Error": 5e-7,
               "Orbital Gradient": 1e-5, "Orbital Rotation": 1e-5}
    convergence = list(re.finditer(r"SCF CONVERGED AFTER\s+(\d+)\s+CYCLES", raw))
    final = convergence[-1] if convergence else None
    summaries = list(re.finditer(r"(?m)^\s*SCF CONVERGENCE\s*$", raw))
    summary = summaries[-1] if summaries and final and summaries[-1].start() > final.end() else None
    final_rows = raw[summary.end():] if summary else ""
    rows = {}
    for label, target in targets.items():
        values = re.findall(r"Last " + re.escape(label) + r"\s*\.\.\.\s*(" + _FLOAT
                            + r")\s+Tolerance\s*:\s*(" + _FLOAT + r")", final_rows)
        if values:
            value, threshold = (float(v.replace("D", "E").replace("d", "e")) for v in values[-1])
            rows[label] = {"value": value, "threshold": threshold, "declared_target": target,
                           "target_matches": math.isfinite(threshold) and threshold == target,
                           "achieved": math.isfinite(value) and abs(value) <= threshold}
    checks = re.findall(r"(?m)^\s*Convergence Check Mode\s+ConvCheckMode\s+\.{3,4}\s*(.+)$", raw)
    # Each optimization geometry can introduce another SCF iteration table.
    # A missing final header must not inherit a previous geometry's converger.
    previous_end = convergence[-2].end() if len(convergence) > 1 else 0
    lean_start = raw.rfind("ORCA LEAN-SCF", 0, final.start()) if final else -1
    iteration_start = max(previous_end, lean_start)
    final_iteration = raw[iteration_start:final.start()] if final else ""
    headers = re.findall(r"(?m)^-+(D-I-I-S|S-O-S-C-F)-+\s*$", final_iteration)
    active = headers[-1] if headers else None
    settings_start = raw.rfind("SCF SETTINGS", 0, final.start()) if final else -1
    previous_lean = raw.rfind("ORCA LEAN-SCF", 0, lean_start) if lean_start >= 0 else -1
    # ORCA prints settings before its LEAN-SCF heading, once per solver stage.
    # Reused settings within that stage are valid; a prior stage's are not.
    final_checks = re.findall(r"(?m)^\s*Convergence Check Mode\s+ConvCheckMode\s+\.{3,4}\s*(.+)$",
                             raw[settings_start:final.start()]
                             if final and lean_start >= 0 and settings_start > previous_lean else "")
    required = set(targets) - {"DIIS Error"} if active == "S-O-S-C-F" else set(targets)
    failures = []
    if (not checks or any(check.strip() != "All-Criteria" for check in checks)
            or len(final_checks) != 1 or final_checks[0].strip() != "All-Criteria"):
        failures.append("native ConvCheckMode is not the declared All-Criteria mode")
    if final is None or summary is None or "ORCA LEAN-SCF" in raw[final.end():]:
        failures.append("final native SCF convergence marker and summary are not bound")
    if active not in {"D-I-I-S", "S-O-S-C-F"}:
        failures.append("final active native converger is not established")
    for label in targets:
        if label not in rows:
            failures.append("missing final SCF row: " + label)
        elif not rows[label]["target_matches"]:
            failures.append("printed target differs: " + label)
        elif label in required and not rows[label]["achieved"]:
            failures.append("active final criterion not achieved: " + label)
    return {"profile_id": MAPPING_V42, "raw_stdout_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "native_checks": checks, "final_active_converger": active, "final_printed_rows": rows,
            "final_native_checks": final_checks, "final_scf_cycles": int(final.group(1)) if final else None,
            "DIIS_residual_mandatory": active != "S-O-S-C-F",
            "inactive_DIIS_residual_retained": active == "S-O-S-C-F",
            "failures": failures, "passed": not failures}


def verify_numerical_profile_receipt(profile_id: str, metadata: dict, diagnostics: dict, raw: str) -> None:
    """Reject promoted/changed caches through exact definition and real raw rows."""
    expected = numerical_profile_receipt(profile_id)
    if expected is None:
        return
    if metadata.get("numerical_profile") != expected:
        raise IntegrityError("ORCA numerical profile receipt differs from the explicit versioned definition")
    evidence = observe_scf_numerical_profile(raw)
    if diagnostics.get("scf_numerical_profile") != evidence or evidence["passed"] is not True:
        raise IntegrityError("ORCA numerical profile evidence differs from achieved active raw SCF criteria")


def require_achieved_scf_numerical_profile(profile_id: str, raw: str) -> None:
    """Validate separately bound derivative raw files without inventing metadata."""
    if profile_id == MAPPING_V42 and observe_scf_numerical_profile(raw)["passed"] is not True:
        raise IntegrityError("ORCA derivative raw SCF criteria do not achieve the explicit numerical profile")


def bind_numerical_profile_calibration_problem(profile_id: str, metadata: dict, diagnostics: dict,
                                             raw: str, problem: dict) -> dict:
    """Bind a measured key to validated settings; never create a timing sample.

    A producer supplies its retained native result and original raw output.
    Legacy contexts remain unchanged. The historical injected diagnostic is
    still labeled v4.1 and cannot be relabeled through this helper.
    """
    expected = numerical_profile_receipt(profile_id)
    if expected is None:
        return dict(problem)
    if (metadata.get("profile_id") != profile_id
            or metadata.get("requested_method", {}).get("profile_id") != profile_id):
        raise IntegrityError("Calibration requires an originally authored native result for the declared profile")
    verify_numerical_profile_receipt(profile_id, metadata, diagnostics, raw)
    identity = expected["definition_sha256"]
    if "numerical_profile_sha256" in problem and problem["numerical_profile_sha256"] != identity:
        raise IntegrityError("Calibration context already declares a different numerical profile identity")
    return {**problem, "numerical_profile_sha256": identity}
