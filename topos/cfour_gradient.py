"""Exact CFOUR 2.1 indexed Cartesian gradient table missing from QCEngine 0.51."""
from __future__ import annotations

import re

from .cfour_scf import _segments
from .engines import EngineParseError, _number

_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"


def parse_cfour_2_1_gradient(raw: str, symbols: list[str]) -> list[list[float]]:
    """Require one complete native xvdint table with exact indexed identities.

    This is an independently observed stdout gradient, subsequently checked
    against the separately parsed native GRD at the existing 6e-8 tolerance.
    No gradient is inferred from energy, a stored reference, or another frame.
    """
    versions = re.findall(r"(?im)^[ \t]*version[ \t]+([\w.+-]+)[ \t]*$", raw)
    heading = r"(?m)^[ \t]*Molecular gradient[ \t]*$"
    if versions != ["2.1"] or len(re.findall(heading, raw)) != 1:
        raise EngineParseError("Expected one native CFOUR 2.1 indexed Cartesian gradient table")
    modules = [text for name, text in _segments(raw) if name == "xvdint"]
    if len(modules) != 1 or len(re.findall(heading, modules[0])) != 1:
        raise EngineParseError("CFOUR 2.1 gradient is not bound to one successfully completed xvdint")
    text = re.split(heading, modules[0], maxsplit=1)[1]
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or lines.pop(0).strip() != "------------------":
        raise EngineParseError("Malformed CFOUR 2.1 Cartesian-gradient table header")
    while lines and not lines[0].strip():
        lines.pop(0)
    rows = []
    while lines and lines[0].strip():
        row = re.fullmatch(r"[ \t]*([A-Za-z]{1,2})[ \t]+#(\d+)[ \t]+(" + _FLOAT
            + r")[ \t]+(" + _FLOAT + r")[ \t]+(" + _FLOAT + r")[ \t]*", lines.pop(0))
        if row is None:
            raise EngineParseError("Malformed CFOUR 2.1 indexed gradient row")
        index = len(rows)
        if index >= len(symbols) or int(row[2]) != index + 1 or row[1].upper() != symbols[index].upper():
            raise EngineParseError("CFOUR 2.1 gradient atom identities/order do not match QCOMP")
        rows.append([_number(row[i]) for i in (3, 4, 5)])
    while lines and not lines[0].strip():
        lines.pop(0)
    if (len(rows) != len(symbols) or not lines
            or re.fullmatch(r"[ \t]*Molecular gradient norm[ \t]+" + _FLOAT + r"[ \t]*", lines[0]) is None):
        raise EngineParseError("CFOUR 2.1 Cartesian-gradient table is incomplete or unterminated")
    return rows
