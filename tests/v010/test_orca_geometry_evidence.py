"""Parse genuine retained output; no replay claims a completed calculation.

Mutations below only test rejection of damaged or insufficient evidence. Native
success still requires an actual independently executed final-gradient stage.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from topos.engines import _orca_convergence
from topos.orca_geometry_evidence import convergence_evidence

FIXTURES = Path(__file__).parent / "fixtures/orca_one_cycle_native"


def raw(name="r2scan"):
    return (FIXTURES / f"{name}-refinement-1.stdout").read_text()


def test_retained_native_stdout_matches_unchanged_hosted_provenance():
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    assert provenance["run_url"].endswith("/37671080822")
    for source in provenance["sources"]:
        data = (FIXTURES / source["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == source["sha256"]
        assert len(data) == source["size_bytes"]


@pytest.mark.parametrize("name,passed,delta,lines", [
    ("r2scan", True, "1.04E-10", [847, 1530]),
    ("wb97xv", False, "5.69370E-7", [928, 1679]),
])
def test_actual_one_cycle_energy_difference_can_pass_or_fail_unchanged_tolerance(name, passed, delta, lines):
    text = raw(name)
    original = _orca_convergence(text)
    assert len(original) == 4 and all(original.values())
    criteria, evidence = convergence_evidence(text, energy_tolerance=1e-7)
    assert criteria == {**original, "energy_change": passed}
    assert evidence["passed"] is passed and evidence["threshold_hartree"] == "1E-7"
    assert evidence["signed_energy_change_hartree"] == delta
    assert evidence["native_energy_lines"] == lines
    assert evidence["raw_stdout_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert Decimal(evidence["printed_rounding_allowance_hartree"]) == Decimal("1e-12")
    assert Decimal(evidence["absolute_energy_change_upper_bound_hartree"]) == abs(Decimal(delta)) + Decimal("1e-12")
    assert "not a printed convergence row" in evidence["source"]
    assert evidence["printed_energy_change_status"] == "NOT_EVALUATED"
    assert evidence["printed_geometry_criteria"] == original
    assert "independent final gradient remain required" in evidence["scope"]
    for number, literal in zip(lines, evidence["native_energy_literals_hartree"], strict=True):
        assert text.splitlines()[number - 1].strip() == "FINAL SINGLE POINT ENERGY       " + literal


@pytest.mark.parametrize("damage", [
    "missing-initial-energy", "missing-final-energy", "extra-energy", "nonfinite-energy",
    "extra-cycle", "wrong-cycle", "wrong-final-count", "missing-final-section", "duplicate-final-section",
    "missing-scf", "extra-scf", "scf-failed", "missing-termination", "duplicate-termination",
    "missing-banner", "duplicate-table", "duplicate-row", "missing-geometry", "version",
    "energy-before-final-section", "wrong-native-threshold", "duplicate-threshold",
    "failed-gradient", "false-numeric-gradient", "malformed-energy-row",
])
def test_missing_ambiguous_or_failed_native_evidence_cannot_supply_energy_gate(damage):
    text = raw()
    first = "FINAL SINGLE POINT ENERGY       -76.418935490707"
    final = "FINAL SINGLE POINT ENERGY       -76.418935490603"
    marker = "FINAL ENERGY EVALUATION AT THE STATIONARY POINT"
    gradient = "          RMS gradient        0.0000002070            0.0000030000      YES"
    if damage == "missing-initial-energy":
        text = text.replace(first, "", 1)
    elif damage == "missing-final-energy":
        text = text.replace(final, "", 1)
    elif damage == "extra-energy":
        text += "\n" + first + "\n"
    elif damage == "nonfinite-energy":
        text = text.replace(final, "FINAL SINGLE POINT ENERGY       NaN", 1)
    elif damage == "extra-cycle":
        text += "\nGEOMETRY OPTIMIZATION CYCLE 2\n"
    elif damage == "wrong-cycle":
        text = text.replace("GEOMETRY OPTIMIZATION CYCLE   1", "GEOMETRY OPTIMIZATION CYCLE   2")
    elif damage == "wrong-final-count":
        text = text.replace("(AFTER    1 CYCLES)", "(AFTER    2 CYCLES)")
    elif damage == "missing-final-section":
        text = text.replace(marker, "REMOVED STATIONARY SECTION")
    elif damage == "duplicate-final-section":
        text += "\n" + marker + " ***\n *** (AFTER 1 CYCLES)\n"
    elif damage == "missing-scf":
        text = text.replace("SCF CONVERGED AFTER  11 CYCLES", "REMOVED SCF EVIDENCE")
    elif damage == "extra-scf":
        text = text.replace(first, "SCF CONVERGED AFTER 1 CYCLES\n" + first)
    elif damage == "scf-failed":
        text += "\nSCF NOT CONVERGED\n"
    elif damage == "missing-termination":
        text = text.replace("ORCA TERMINATED NORMALLY", "REMOVED TERMINATION")
    elif damage == "duplicate-termination":
        text += "\nORCA TERMINATED NORMALLY\n"
    elif damage == "missing-banner":
        text = text.replace("THE OPTIMIZATION HAS CONVERGED", "REMOVED OPTIMIZATION BANNER")
    elif damage == "duplicate-table":
        text += "\n|Geometry convergence|\n"
    elif damage == "duplicate-row":
        text = text.replace(gradient, gradient + "\n" + gradient)
    elif damage == "missing-geometry":
        text = text.replace("CARTESIAN COORDINATES (ANGSTROEM)", "REMOVED GEOMETRY", 1)
    elif damage == "version":
        text = text.replace("Program Version 6.1.1", "Program Version 6.0.1")
    elif damage == "energy-before-final-section":
        text = text.replace(final, "").replace(marker, final + "\n" + marker)
    elif damage == "wrong-native-threshold":
        text = text.replace("1.0000e-07 Eh", "1.0000e-06 Eh", 1)
    elif damage == "duplicate-threshold":
        text = text.replace("Convergence Tolerances:", "Convergence Tolerances:\nEnergy Change TolE .... 1.0000e-07 Eh")
    elif damage == "failed-gradient":
        text = text.replace(gradient, gradient.replace("YES", "NO"))
    elif damage == "malformed-energy-row":
        text = text.replace(gradient, "          Energy change NaN 1e-7 NO\n" + gradient)
    else:
        text = text.replace(gradient, gradient.replace("0.0000002070", "0.0000207000"))
    original = _orca_convergence(text)
    criteria, evidence = convergence_evidence(text, energy_tolerance=1e-7)
    assert evidence is None and criteria == original and "energy_change" not in criteria


def test_a_printed_energy_gate_is_never_replaced_by_another_energy_difference():
    text = (Path(__file__).parent / "fixtures/orca_fifth_hosted/incomplete-r2scan-optimization.stdout").read_text()
    criteria, evidence = convergence_evidence(text, energy_tolerance=1e-7)
    assert criteria == _orca_convergence(text) and evidence is None
    assert len(criteria) == 5 and not all(criteria.values())


def test_caller_threshold_must_equal_native_optimizer_threshold():
    criteria, evidence = convergence_evidence(raw(), energy_tolerance=1e-10)
    assert len(criteria) == 4 and evidence is None


def test_printed_precision_cannot_turn_an_uncertain_energy_gate_into_a_pass():
    # Deliberately damaged tolerance for a precision-bound rejection check,
    # not a newly executed native protocol. Nominal 1.04e-10 is insufficient.
    text = raw().replace("1.0000e-07 Eh", "1.0450e-10 Eh", 1)
    criteria, evidence = convergence_evidence(text, energy_tolerance=1.045e-10)
    assert Decimal(evidence["signed_energy_change_hartree"]) < Decimal("1.045e-10")
    assert Decimal(evidence["absolute_energy_change_upper_bound_hartree"]) > Decimal("1.045e-10")
    assert criteria["energy_change"] is False and evidence["passed"] is False


@pytest.mark.parametrize("threshold", [0., -1e-7, float("nan"), float("inf")])
def test_nonphysical_requested_energy_threshold_is_rejected(threshold):
    with pytest.raises(ValueError, match="finite positive"):
        convergence_evidence(raw(), energy_tolerance=threshold)
