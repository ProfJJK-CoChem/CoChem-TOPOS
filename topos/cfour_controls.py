"""Read the native CFOUR control table, separately from input echoes and prose."""
from __future__ import annotations

import re

from .engines import EngineParseError

_INTERNAL_NAMES = {
    'ABCDTYPE': 'IABCDT', 'BASIS': 'IBASIS', 'CALC_?LEVEL': 'ICLLVL',
    'CC_PROGRAM': 'ICCPRO', 'CHARGE': 'ICHRGE', 'CONTRACTION': 'ICNTYP',
    'DBOC': 'IDBOC', 'DERIV_LEV(?:EL)?': 'IDRLVL', 'DROPMO': 'IDRPMO',
    'FROZEN_CORE': 'IFROCO', 'MULTIPLICI?TY': 'IMULTP', 'MULTIPLICTY': 'IMULTP',
    'PROPS': 'IPROPS', 'REFERENCE': 'IREFNC', 'RELATIVIST(?:IC)?': 'IRELAT',
    'SPHERICAL': 'IDFGHI', 'SYMMETRY': 'ISYM',
}


def native_control_value(raw: str, name: str) -> str:
    """Require one genuine framed table and one exact native control identity.

    The known internal identifier prevents uppercase native prose such as
    ``SPHERICAL HARMONICS ARE USED.`` from impersonating a control row. An
    additional actual row outside the framed table remains ambiguous.
    """
    internal = _INTERNAL_NAMES.get(name)
    if internal is None:
        raise EngineParseError('Unsupported native CFOUR control identity: ' + name)
    failure = 'Missing/ambiguous native control ' + name
    lines = raw.splitlines()
    headings = [i for i, line in enumerate(lines) if line.strip() == 'CFOUR Control Parameters']
    if len(headings) != 1:
        raise EngineParseError(failure + ': expected exactly one native control table')
    start = headings[0]

    def separator(index: int) -> bool:
        return 0 <= index < len(lines) and re.fullmatch(r'[ \t]*-{3,}[ \t]*', lines[index]) is not None

    if (not separator(start - 1) or not separator(start + 1) or start + 4 >= len(lines)
            or lines[start + 2].split() != ['External', 'Internal', 'Value', 'Units']
            or lines[start + 3].split() != ['Name', 'Name'] or not separator(start + 4)):
        raise EngineParseError(failure + ': malformed native control-table header')
    end = start + 5
    while end < len(lines) and not separator(end):
        if lines[end].strip() and not re.fullmatch(r'[ \t]*[A-Z][A-Z0-9_-]*[ \t]+[A-Za-z][A-Za-z0-9_]*[ \t]+[^\r\n]+', lines[end]):
            raise EngineParseError(failure + ': malformed or unterminated native control table')
        end += 1
    if end == len(lines) or end == start + 5:
        raise EngineParseError(failure + ': missing native control-table end')
    row = re.compile(r'[ \t]*(?:' + name + r')[ \t]+' + internal + r'[ \t]+([^\r\n]+)')
    matches = [(i, row.fullmatch(line)) for i, line in enumerate(lines)]
    matches = [(i, match) for i, match in matches if match is not None]
    if len(matches) != 1 or not start + 5 <= matches[0][0] < end:
        raise EngineParseError(failure)
    value = re.split(r'[ \t]*\[|[ \t]+\*\*\*', matches[0][1][1], maxsplit=1)[0].strip()
    if not value:
        raise EngineParseError(failure + ': empty native control value')
    return value
