"""Recognize a complete ordinary ORCA SCF iteration-limit failure for own restart.

Recognition permits a bounded restart; it never certifies electronic convergence.
Unrelated native faults and incomplete or changed SCF settings do not qualify.
"""
from __future__ import annotations

import hashlib
import math
import re

_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
_TARGETS = {"TolE": 1e-10, "TolMaxP": 1e-7, "TolRMSP": 5e-9,
            "TolErr": 5e-7, "TolG": 1e-5, "TolX": 1e-5}
_SCF_ERROR = "Error (ORCA_LEANSCF): unfortunately, the SCF has not converged."


def observe_scf_iteration_exhaustion(raw: str, stderr: str) -> dict:
    """Require the specific full native failure and unchanged printed profile.

    The independently verified adapter version/command and original own GBW are
    checked by the caller. This parser is confined to one ordinary SCF stage.
    """
    failures = []
    settings = {}
    final_row = None
    headers = []
    versions = re.findall(r"Program Version\s+(\d+\.\d+\.\d+)", raw)
    if versions != ["6.1.1"]:
        failures.append("one verified ORCA 6.1.1 production header is required")
    if any(marker in raw for marker in ("ORCA TERMINATED NORMALLY", "SCF CONVERGED AFTER",
                                        "FINAL SINGLE POINT ENERGY")):
        failures.append("mixed converged/failed native output does not qualify")
    lean = list(re.finditer(r"(?m)^\s*ORCA LEAN-SCF\s*$", raw))
    starts = list(re.finditer(r"(?m)^\s*SCF SETTINGS\s*$", raw))
    if len(lean) != 1 or len(starts) != 1 or starts[0].start() >= lean[0].start():
        failures.append("one complete independently started SCF settings/stage is required")
    else:
        section = raw[starts[0].end():lean[0].start()]
        checks = re.findall(r"(?m)^\s*Convergence Check Mode\s+ConvCheckMode\s+\.{3,4}\s*(.+)$", section)
        if [check.strip() for check in checks] != ["All-Criteria"]:
            failures.append("native ConvCheckMode is not the declared All-Criteria mode")
        for keyword, target in _TARGETS.items():
            values = re.findall(r"(?m)^.*\b" + keyword + r"\s+\.{3,4}\s*(" + _FLOAT + r")(?:\s+Eh)?\s*$", section)
            if len(values) != 1:
                failures.append("missing or repeated native target: " + keyword)
                continue
            value = float(values[0].replace("D", "E").replace("d", "e"))
            settings[keyword] = value
            if not math.isfinite(value) or value != target:
                failures.append("printed target differs: " + keyword)
        limits = re.findall(r"(?m)^\s*Maximum # iterations\s+MaxIter\s+\.{3,4}\s*(\d+)\s*$", section)
        if len(limits) != 1 or int(limits[0]) <= 0:
            failures.append("finite native SCF iteration limit is absent")
        else:
            settings["MaxIter"] = int(limits[0])
    exhausted = list(re.finditer(r"SCF NOT CONVERGED AFTER\s+(\d+)\s+CYCLES", raw))
    ends = list(re.finditer(r"(?m)^ORCA finished by error termination in LEANSCF\s*$", raw))
    if (len(exhausted) != 1 or len(ends) != 1 or not lean
            or exhausted[0].start() <= lean[-1].start() or ends[0].start() <= exhausted[0].end()
            or not re.search(r"\.{4}\s+aborting the run\s*$", raw)):
        failures.append("complete final native SCF iteration-exhaustion termination is absent")
    else:
        iterations = raw[lean[-1].end():exhausted[0].start()]
        header_matches = list(re.finditer(r"(?m)^-+(D-I-I-S|S-O-S-C-F)-+\s*$", iterations))
        headers = [match.group(1) for match in header_matches]
        final_table = iterations[header_matches[-1].end():] if headers else ""
        columns = r"DIISErr\s+Damp" if headers and headers[-1] == "D-I-I-S" else "MaxGrad"
        if not re.search(r"Iteration\s+Energy \(Eh\)\s+Delta-E\s+RMSDP\s+MaxDP\s+"
                         + columns + r"\s+Time\(sec\)", final_table):
            failures.append("final native iteration columns do not bind the active converger")
        count = 7 if headers and headers[-1] == "D-I-I-S" else 6
        rows = re.findall(r"(?m)^\s*(\d+)\s+" + r"\s+".join(
            ["(" + _FLOAT + ")"] * count) + r"\s*$", final_table)
        if not rows or not headers:
            failures.append("final native iteration and active converger are absent")
        else:
            cycle, *values = rows[-1]
            numeric = [float(value.replace("D", "E").replace("d", "e")) for value in values]
            final_row = {"cycle": int(cycle), "energy_hartree": numeric[0],
                         "energy_change_hartree": numeric[1], "rms_density_change": numeric[2],
                         "max_density_change": numeric[3], "active_error": numeric[4]}
            limit = settings.get("MaxIter", 0)
            reported = int(exhausted[0].group(1))
            if (not all(math.isfinite(value) for value in numeric)
                    or final_row["cycle"] not in {limit - 1, limit}
                    or reported not in {final_row["cycle"] - 1, final_row["cycle"]}):
                failures.append("finite final iteration is not bound to the native iteration limit")
    if _SCF_ERROR not in raw:
        failures.append("explicit native SCF nonconvergence cause is absent")
    if stderr.strip() and _SCF_ERROR not in stderr:
        failures.append("native stderr is not bound to the same SCF nonconvergence cause")
    streams = raw + "\n" + stderr
    if re.search(r"SIGSEGV|SIGBUS|segmentation fault|segfault|out of memory|bad_alloc|"
                 r"no space left|permission denied|error while loading|undefined symbol|"
                 r"cannot open|could not open|unable to open|file not found|MPI_Init|MPI_Abort|"
                 r"ORTE_ERROR|PMIX ERROR|PRTE ERROR|failed to start|unable to launch|"
                 r"not enough slots|lost communication|connection refused", streams, re.I):
        failures.append("unrelated native fault does not qualify")
    if any(signal != "6" for signal in re.findall(r"(?m)^.*Signal:\s*.*\((\d+)\)\s*$", stderr)):
        failures.append("unrelated native signal does not qualify")
    for line in streams.splitlines():
        if re.search(r"\bERROR\s*[:(]", line, re.I) and _SCF_ERROR not in line:
            failures.append("unrelated native error does not qualify")
            break
    return {"schema": "topos-orca-scf-iteration-exhaustion/1",
            "eligible_for_own_gbw_continuation": not failures,
            "raw_stdout_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "raw_stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
            "printed_scf_settings": settings, "final_iteration": final_row,
            "final_active_converger": headers[-1] if headers else None,
            "failures": failures,
            "scope": "restart eligibility only; initial SCF is not converged"}
