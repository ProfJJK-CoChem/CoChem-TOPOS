"""Native failure evidence and exact naming contracts; no simulated success."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from topos.correlated import (
    CorrelatedMethod,
    correlated_input,
    parse_correlated_output,
    run_correlated,
)
from topos.engines import EngineParseError
from topos.models import Molecule, ResourceLimits
from topos.orca_basis_names import resolve_orca_orbital_basis
from topos.storage import file_digest

FIXTURES = Path(__file__).parent / "fixtures/orca_611_f12_basis"


def water():
    return Molecule(symbols=["O", "H", "H"], coordinates=[[0., 0., 0.], [.96, 0., 0.], [-.24, .93, 0.]])


@pytest.mark.parametrize("zeta", ["D", "T", "Q"])
def test_first_row_seasonal_spelling_keeps_requested_orbital_space(zeta):
    requested = f"jun-cc-pV{zeta}Z"
    receipt = resolve_orca_orbital_basis(water(), requested)
    assert receipt["requested_basis"] == requested
    assert receipt["native_basis"] == f"jun-cc-pV({zeta}+d)Z"
    assert receipt["mapping"] == "exact-H-Ne-seasonal-name"
    assert receipt["orbital_space_changed"] is False
    assert receipt["elements"] == ["H", "O"]
    protocol = CorrelatedMethod(method="MP2", orbital_basis=requested, frozen_core=True)
    deck = correlated_input(water(), protocol, ResourceLimits())
    assert f" MP2 {receipt['native_basis']} " in deck
    assert protocol.orbital_basis == requested
    assert "FrozenCore" in deck


@pytest.mark.parametrize("symbol", ["Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar"])
def test_second_row_bare_jun_is_not_silently_replaced_by_extra_tight_d(symbol):
    # Pure input domain fixture, not an atomic electronic calculation.
    from topos.chemistry import atomic_number

    atom = Molecule(symbols=[symbol], coordinates=[[0., 0., 0.]], multiplicity=1 + atomic_number(symbol) % 2)
    with pytest.raises(ValueError, match="not an alias outside H-Ne"):
        resolve_orca_orbital_basis(atom, "jun-cc-pVTZ")


def test_undocumented_jun_five_zeta_and_unexpected_calendar_names_fail_closed():
    for name in ("jun-cc-pV5Z", "jun-cc-pVTZ\n! HF", "jun-cc-pV(T+d)Z"):
        with pytest.raises(ValueError, match="only for D/T/Q"):
            resolve_orca_orbital_basis(water(), name)
    unchanged = resolve_orca_orbital_basis(water(), "cc-pVTZ-F12")
    assert unchanged["native_basis"] == "cc-pVTZ-F12"
    assert unchanged["mapping"] == "native-keyword"


def test_missing_element_cabs_is_rejected_before_any_native_or_binary_lookup(tmp_path):
    helium = Molecule(symbols=["He"], coordinates=[[0., 0., 0.]])
    protocol = CorrelatedMethod(method="F12-MP2", orbital_basis="cc-pVTZ-F12", frozen_core=True,
                                cabs="cc-pVTZ-F12-CABS")
    result = run_correlated(helium, protocol, ResourceLimits(), tmp_path / "must-not-launch",
                            executable="/missing/licensed-orca")
    assert result.status == "unsupported"
    assert "cabs" in result.diagnostics["reason"] and "He" in result.diagnostics["reason"]
    assert result.energy_hartree is None and result.metadata["execution_kind"] == "not-executed"
    assert not (tmp_path / "must-not-launch").exists()


def test_actual_hosted_failure_establishes_missing_keyword_not_a_scientific_result():
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    for name, identity in provenance["files"].items():
        assert file_digest(FIXTURES / name) == identity["sha256"]
    raw = (FIXTURES / "jun-tz-rejected.stdout").read_text()
    assert "UNRECOGNIZED OR DUPLICATED KEYWORD(S) IN SIMPLE INPUT LINE" in raw
    assert "JUN-CC-PVTZ" in raw
    assert "FINAL SINGLE POINT ENERGY" not in raw
    assert "ORCA TERMINATED NORMALLY" not in raw
    protocol = CorrelatedMethod.model_validate_json((FIXTURES / "jun-tz-rejected.protocol.json").read_text())
    with pytest.raises(EngineParseError, match="normal termination"):
        parse_correlated_output(raw, protocol)
    # Only the invalid native spelling changes; the exact method/core/CABS and
    # the scientific requested basis remain as recorded in the failed job.
    old = (FIXTURES / "jun-tz-rejected.inp").read_text()
    rows = [line.split() for line in old.splitlines()[4:-1] if line.strip() != "*"]
    molecule = Molecule(symbols=[row[0] for row in rows],
                        coordinates=[[float(value) for value in row[1:]] for row in rows])
    new = correlated_input(molecule, protocol, ResourceLimits(threads=2, memory_mb=4096))
    assert new == old.replace("jun-cc-pVTZ", "jun-cc-pV(T+d)Z")
