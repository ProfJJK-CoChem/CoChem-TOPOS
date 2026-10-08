"""Unchanged actual R4 output; mutations are rejection-only controls.

This parses native scientific text offline. It does not relabel the failed hosted
component, create a completed ledger or certify EFG/full-row acceptance.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest

from topos.cfour_controls import native_control_value
from topos.engines import EngineParseError
from topos.external_engines import ExternalProtocol, parse_cfour_output
from topos.models import Molecule
from topos.storage import file_digest

FIXTURE = Path(__file__).parent / "fixtures/cfour_first_order_2_1"
PROOF = json.loads((FIXTURE / "provenance.json").read_text())
RAW = (FIXTURE / "output.stdout").read_text()
MOLECULE = Molecule.model_validate(PROOF["molecule"])
PROTOCOL = ExternalProtocol.model_validate(PROOF["requested_protocol"])


def parse(raw):
    return parse_cfour_output(raw, MOLECULE, PROTOCOL, dipol=(FIXTURE / "DIPOL.out").read_text())


def test_exact_original_native_artifacts_and_control_rows():
    for name, identity in PROOF["files"].items():
        assert file_digest(FIXTURE / name) == identity["sha256"]
        assert (FIXTURE / name).stat().st_size == identity["size_bytes"]
    assert "SPHERICAL HARMONICS ARE USED." in RAW
    assert native_control_value(RAW, "SPHERICAL") == "ON"
    assert native_control_value(RAW, "CALC_?LEVEL") == "CCSD(T)"
    assert native_control_value(RAW, "PROPS") == "FIRST_ORDER"
    assert native_control_value(RAW, "DROPMO") == "NONE"


def test_genuine_spherical_first_order_output_parses_without_native_execution():
    result = parse(RAW)
    assert result["engine_version"] == "2.1"
    assert result["energy_hartree"] == pytest.approx(-76.345753258710815, abs=1e-10)
    assert result["gradient_hartree_per_bohr"] is None
    assert result["parser"] == {"qcengine": "0.51.0", "qcelemental": "0.51.2"}
    native_dipole = np.array([float(v) for v in (FIXTURE / "DIPOL.out").read_text().split()])
    assert np.linalg.norm(result["dipole_atomic_units"]) == pytest.approx(
        np.linalg.norm(native_dipole), abs=1e-10
    )
    assert "efg_tensors_atomic_units" not in result  # Separate property parser work.


@pytest.mark.parametrize(
    "name,identifier",
    [
        ("SPHERICAL", "IDFGHI"),
        ("REFERENCE", "IREFNC"),
        ("FROZEN_CORE", "IFROCO"),
        ("PROPS", "IPROPS"),
    ],
)
@pytest.mark.parametrize(
    "change", ["missing", "duplicate-in-table", "duplicate-outside", "wrong-internal", "echo-only"]
)
def test_real_control_rows_must_be_unique_and_native(name, identifier, change):
    row = re.search(r"(?m)^[ \t]*" + name + r"[ \t]+" + identifier + r"[^\n]+", RAW)[0]
    if change in {"missing", "echo-only"}:
        changed = RAW.replace(row, "")
        if change == "echo-only":
            changed += "\n" + name + "=ON\n"
    elif change == "duplicate-in-table":
        changed = RAW.replace(row, row + "\n" + row)
    elif change == "duplicate-outside":
        changed = RAW + "\n" + row
    else:
        changed = RAW.replace(row, row.replace(identifier, "WRONG"))
    with pytest.raises(EngineParseError, match="Missing/ambiguous native control"):
        native_control_value(changed, name)


@pytest.mark.parametrize(
    "change", ["missing-header", "duplicate-header", "wrong-columns", "missing-footer"]
)
def test_actual_table_framing_cannot_be_missing_or_ambiguous(change):
    lines = RAW.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "CFOUR Control Parameters")
    if change == "missing-header":
        lines[start] = ""
    elif change == "duplicate-header":
        lines.append(lines[start])
    elif change == "wrong-columns":
        lines[start + 2] = "External Value"
    else:
        end = next(i for i in range(start + 5, len(lines)) if re.fullmatch(r"\s*-+\s*", lines[i]))
        lines[end] = ""
    with pytest.raises(EngineParseError, match="native control"):
        native_control_value("\n".join(lines), "SPHERICAL")


@pytest.mark.parametrize(
    "name,old,new",
    [
        ("SPHERICAL", "ON", "OFF"),
        ("FROZEN_CORE", "OFF", "ON"),
        ("REFERENCE", "RHF", "UHF"),
        ("PROPS", "FIRST_ORDER", "OFF"),
    ],
)
def test_actual_wrong_physical_control_remains_rejected(name, old, new):
    row = re.search(r"(?m)^[ \t]*" + name + r"[ \t]+\w+[^\n]+", RAW)[0]
    changed = RAW.replace(row, re.sub(r"\b" + old + r"\b", new, row))
    with pytest.raises(EngineParseError):
        parse(changed)
