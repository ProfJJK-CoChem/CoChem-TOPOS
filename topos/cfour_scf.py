"""Recognize a genuine CFOUR 2.1 correlated density reload within one evaluation."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .engines import EngineParseError

_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
_MARKER = re.compile(r"(?m)^[ \t]*SCF has converged\.[ \t]*$")


def _one(pattern: str, text: str) -> str:
    matches = re.findall(pattern, text, re.M)
    if len(matches) != 1:
        raise EngineParseError("CFOUR density reload lacks one exact framed SCF field")
    return matches[0]


def _decimal(value: str) -> Decimal:
    try:
        number = Decimal(value.replace("D", "E").replace("d", "e"))
    except InvalidOperation as exc:
        raise EngineParseError("CFOUR density reload contains an invalid energy") from exc
    if not number.is_finite():
        raise EngineParseError("CFOUR density reload contains a nonfinite energy")
    return number


def _segments(raw: str) -> list[tuple[str, str]]:
    """Pair every start with its own successful end in native execution order."""
    lines = raw.splitlines(keepends=True)
    starts: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.fullmatch(r"[ \t]*--invoking executable(.*?)[\r\n]*", line)
        if match is None:
            continue
        if match[1].strip() == "--":
            token = lines[index + 1].strip() if index + 1 < len(lines) else ""
            body = index + 2
        else:
            inline = re.fullmatch(r"[ \t]+(\S+)[ \t]*", match[1])
            token = inline[1] if inline else ""
            body = index + 1
        name = Path(token).name
        if not token or re.search(r"\s", token) or re.fullmatch(r"x[A-Za-z0-9_]+", name) is None:
            raise EngineParseError("Malformed CFOUR density-reload invocation framing")
        starts.append((index, body, name))
    segments = []
    for i, (_, begin, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(lines)
        text = "".join(lines[begin:end])
        completions = list(re.finditer(r"(?m)^--executable[ \t]+(\S+)[ \t]+finished with status[ \t]+(-?\d+)[^\r\n]*$", text))
        if len(completions) != 1 or completions[0][1] != name or int(completions[0][2]) != 0:
            raise EngineParseError("CFOUR density-reload module is incomplete, out of order or unsuccessful")
        segments.append((name, text[:completions[0].start()]))
    return segments


def validate_cfour_scf(raw: str, *, engine_version: str, method: str,
                       operation: str, scf_convergence: int) -> dict:
    """Keep one converged SCF, or allow only the observed zero-iteration reload.

    Public CFOUR 2.1's correlated analytic-gradient driver invokes xprepfc2f,
    xvscf (zero iterations, OLDMOS/MOREAD), xvtran, xintprc and xfillfc before
    constructing the density. This reload must reproduce the first SCF energy
    exactly. It is not another geometry, an unconverged solver or a restart.
    Native version/control/geometry/energy/GRD checks remain separate and required.
    """
    markers = list(_MARKER.finditer(raw))
    if len(markers) != len(re.findall(r"SCF has converged\.", raw)):
        raise EngineParseError("CFOUR SCF convergence marker is not a complete native output line")
    if len(markers) == 1:
        return {"profile": "single-converged-scf-v1", "converged_events": 1}
    if (len(markers) != 2 or engine_version != "2.1" or method not in {"MP2", "CCSD", "CCSD(T)"}
            or operation not in {"gradient", "optimize"}):
        raise EngineParseError("Expected one CFOUR Cartesian evaluation, not concatenated jobs/optimization cycles")
    versions = re.findall(r"(?im)^[ \t]*version[ \t]+([\w.+-]+)[ \t]*$", raw)
    if versions != ["2.1"]:
        raise EngineParseError("CFOUR density reload requires exactly one native CFOUR 2.1 job")
    segments = _segments(raw)
    scf = [(i, text) for i, (name, text) in enumerate(segments) if name == "xvscf"]
    if (len(scf) != 2 or sum(len(_MARKER.findall(text)) for _, text in scf) != 2
            or any(len(_MARKER.findall(text)) != 1 for _, text in scf)
            or sum(len(_MARKER.findall(text)) for _, text in segments) != len(markers)):
        raise EngineParseError("CFOUR convergence markers are not bound to exactly two xvscf invocations")
    first_index, first = scf[0]
    reload_index, reload = scf[1]
    names = [name for name, _ in segments]
    if (reload_index <= first_index + 1 or names[reload_index - 1] != "xprepfc2f"
            or names[reload_index + 1:reload_index + 4] != ["xvtran", "xintprc", "xfillfc"]
            or "xvdint" not in names[reload_index + 4:]):
        raise EngineParseError("CFOUR density reload does not follow the native analytic-gradient module sequence")
    for text in (first, reload):
        if _one(r"^[ \t]*SCF reference function:[ \t]+(\S+)[ \t]*$", text) != "RHF":
            raise EngineParseError("CFOUR density reload changed the RHF reference")
    maximum = int(_one(r"^[ \t]*Maximum number of iterations:[ \t]+(\d+)[ \t]*$", first))
    tolerance = int(_one(r"^[ \t]*SCF convergence tolerance:[ \t]+10\*\*\(-([0-9]+)\)[ \t]*$", first))
    if maximum <= 0 or tolerance != scf_convergence:
        raise EngineParseError("The first CFOUR SCF lacks its requested active convergence control")
    if (_one(r"^[ \t]*Maximum number of iterations:[ \t]+(\d+)[ \t]*$", reload) != "0"
            or _one(r"^[ \t]*Initial density matrix:[ \t]+(\S+)[ \t]*$", reload) != "MOREAD"
            or len(re.findall(r"(?m)^[ \t]*starting vectors read from OLDMOS[ \t]*$", reload)) != 1):
        raise EngineParseError("The second CFOUR SCF is not the native zero-iteration OLDMOS density reload")
    energy_row = r"^[ \t]*E\(SCF\)=[ \t]*(" + _FLOAT + r")[ \t]+(" + _FLOAT + r")[ \t]*$"
    first_energy = re.findall(energy_row, first, re.M)
    reload_energy = re.findall(energy_row, reload, re.M)
    zero_rows = re.findall(r"^[ \t]*(\d+)[ \t]+(" + _FLOAT + r")[ \t]+(" + _FLOAT + r")[ \t]*$", reload, re.M)
    if len(first_energy) != 1 or len(reload_energy) != 1 or len(zero_rows) != 1:
        raise EngineParseError("CFOUR density reload lacks unique SCF energy/zero-iteration rows")
    energy = _decimal(first_energy[0][0])
    if (abs(_decimal(first_energy[0][1])) > Decimal(10) ** -scf_convergence
            or _decimal(reload_energy[0][0]) != energy or _decimal(reload_energy[0][1]) != 0
            or zero_rows[0][0] != "0" or _decimal(zero_rows[0][1]) != energy
            or _decimal(zero_rows[0][2]) != 0):
        raise EngineParseError("CFOUR density reload changed the converged SCF energy or performed a new iteration")
    return {"profile": "cfour-2.1-correlated-zero-iteration-density-reload-v1", "requested_method": method,
            "converged_events": 2, "primary_scf_convergence_exponent": tolerance,
            "reload_iterations": 0, "reload_guess": "OLDMOS/MOREAD",
            "identical_printed_scf_energy_hartree": str(energy)}
