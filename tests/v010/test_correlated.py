"""Correlated protocol/parser contracts; no licensed execution is simulated."""
from __future__ import annotations

import pytest

from topos.correlated import (
    CorrelatedMethod,
    _stationarity,
    correlated_input,
    parse_correlated_output,
    parse_led,
    run_correlated,
)
from topos.engines import EngineParseError
from topos.models import Molecule, ResourceLimits
from topos.runtime import run_process


def water():
    return Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.96, 0, 0], [-.24, .93, 0]])


def method(**kwargs):
    values = dict(method="CCSD(T)", orbital_basis="cc-pVTZ", frozen_core=True)
    values.update(kwargs)
    return CorrelatedMethod(**values)


@pytest.mark.parametrize("changes", [
    {"orbital_basis": "cc-pVTZ\n!HF"},
    {"method": "CCSD(T)-F12b"},
    {"method": "CCSD(T)-F12D/RI", "cabs": "cc-pVTZ-F12-CABS"},
    {"cabs": "cc-pVTZ-F12-CABS"},
    {"operation": "gradient"},
    {"auxiliary_jk": "def2/JK"},
    {"scf_integrals": "RIJK"},
    {"method": "AUTOCI-CCSD(T)", "integral_handling": "KC_AOBLAS"},
    {"method": "DLPNO-CCSD(T1)", "auxiliary_c": "cc-pVDZ/C"},
    {"local_energy_decomposition": True},
])
def test_inconsistent_or_unverified_method_options_are_rejected(changes):
    with pytest.raises(ValueError):
        method(**changes)


def test_f12_orbital_basis_does_not_select_an_f12_hamiltonian():
    plain = method(method="DLPNO-CCSD(T1)", orbital_basis="cc-pVDZ-F12", auxiliary_c="cc-pVTZ/C",
                   pno_profile="TightPNO", tcutpno=1e-7)
    deck = correlated_input(water(), plain, ResourceLimits())
    assert "DLPNO-CCSD(T1) cc-pVDZ-F12" in deck
    assert "CABS" not in deck
    assert "TCutPNO 1e-07" in deck
    assert "StorageType Shared" in deck


def test_canonical_analytic_gradient_selects_autoci_and_preserves_explicit_core():
    protocol = method(method="AUTOCI-CCSD(T)", operation="optimize", frozen_core=False)
    deck = correlated_input(water(), protocol, ResourceLimits(threads=1, memory_mb=2048))
    assert "AUTOCI-CCSD(T)" in deck and " Opt" in deck and "Engrad" not in deck
    gradient = correlated_input(water(), protocol.model_copy(update={"operation": "gradient"}), ResourceLimits())
    assert " Engrad" in gradient and " Opt" not in gradient
    assert "NoFrozenCore" in deck and "%mdci" not in deck
    assert "%maxcore 1536" in deck
    assert "TolMaxG 1e-5" in deck and "TolRMSG 3e-6" in deck


def test_final_correlated_stationarity_checks_both_maximum_and_rms():
    # Pure gradient mathematics, not a simulated engine or geometry acceptance.
    assert _stationarity([[0., 0., 0.]])["passed"]
    low_max_high_rms = _stationarity([[4e-6, 4e-6, 4e-6]])
    assert low_max_high_rms["max_gradient_hartree_per_bohr"] < 1e-5
    assert not low_max_high_rms["passed"]
    sparse = [[0., 0., 0.] for _ in range(10)]
    sparse[0][0] = 1.1e-5
    high_max_low_rms = _stationarity(sparse)
    assert high_max_low_rms["rms_gradient_hartree_per_bohr"] < 3e-6
    assert not high_max_low_rms["passed"]
    for malformed in ([], [[0., 0.]], [[float("nan"), 0., 0.]]):
        with pytest.raises(EngineParseError):
            _stationarity(malformed)


def test_f12_never_exposes_unavailable_orca_gradient():
    protocol = method(method="CCSD(T)-F12D/RI", orbital_basis="cc-pVTZ-F12", cabs="cc-pVTZ-F12-CABS", auxiliary_c="cc-pVQZ/C")
    assert protocol.operation == "energy"
    with pytest.raises(ValueError, match="gradients are unavailable"):
        CorrelatedMethod.model_validate({**protocol.model_dump(), "operation": "gradient"})


def test_closed_shell_reference_cannot_be_used_for_undeclared_open_shell():
    radical = Molecule(symbols=["H"], coordinates=[[0, 0, 0]], multiplicity=2)
    with pytest.raises(ValueError, match="closed-shell"):
        correlated_input(radical, method(), ResourceLimits())


def test_hf_total_energy_alone_cannot_certify_correlated_result():
    raw = "Program Version 6.1.1\nSCF CONVERGED AFTER 8 CYCLES\nFINAL SINGLE POINT ENERGY -76.0\nORCA TERMINATED NORMALLY\n"
    with pytest.raises(EngineParseError, match="correlated method"):
        parse_correlated_output(raw, method())


def test_correlated_parser_arithmetic_contract_does_not_claim_native_execution():
    # Artificial grammar fixture only. No executable consumes this text.
    raw = "Program Version 6.1.1\nSCF CONVERGED AFTER 8 CYCLES\nE(0) ... -76.0\nE(CCSD(T)) ... -76.2\nFINAL SINGLE POINT ENERGY -76.2\nORCA TERMINATED NORMALLY\n"
    result = parse_correlated_output(raw, method())
    assert result["total_correlation_energy_hartree"] == pytest.approx(-.2)
    assert result["reference_energy_hartree"] == -76
    assert not result["f12_hamiltonian"]
    with pytest.raises(EngineParseError, match="not confirmed"):
        parse_correlated_output(raw.replace("E(CCSD(T)) ... -76.2", "E(CCSD(T)) ... -76.1"), method())


def test_led_full_sum_keeps_interfragment_energy_distinct_from_binding_energy():
    # Numerical values transcribed from the official ORCA6.1 LED example;
    # parser-only evidence, not a newly executed job.
    raw = """INTER- vs INTRA-FRAGMENT TOTAL ENERGIES (Eh)
Sum of INTRA-fragment total energies = -115.198484076087
Sum of INTER-fragment total energies = -0.071506179140
Total energy = -115.269990255227
"""
    result = parse_led(raw, -115.269990255227)
    assert result["inter_fragment_total_hartree"] == -.071506179140
    assert "not a binding energy" in result["interpretation"]
    with pytest.raises(EngineParseError, match="do not sum"):
        parse_led(raw, -115.0)
    with pytest.raises(EngineParseError, match="absent"):
        parse_led("FINAL SUMMARY DLPNO-CCSD ENERGY DECOMPOSITION", -115)


def test_missing_licensed_binary_has_no_energy_or_fake_artifacts(tmp_path):
    result = run_correlated(water(), method(), ResourceLimits(), tmp_path / "attempt",
                             executable="/missing/orca", process_runner=run_process)
    assert result.status == "unavailable" and result.energy_hartree is None
    assert result.metadata["execution_kind"] == "not-executed"
    assert not result.artifacts
