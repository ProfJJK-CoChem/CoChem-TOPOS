"""Faithful hosted ORCA 6.1.1 output replay; these tests do not execute ORCA."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from topos.correlated import CorrelatedMethod, parse_correlated_output
from topos.engines import EngineParseError
from topos.orca_f12_composite import parse_f12_mp2_partition

FIXTURES = Path(__file__).parent / "fixtures" / "orca_611_correlated"


def native_case(name):
    provenance = json.loads((FIXTURES / "provenance.json").read_text())["files"][name]
    raw = (FIXTURES / provenance["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == provenance["sha256"]
    assert len(raw) == provenance["size_bytes"]
    assert provenance["native_process_status"] == "completed"
    return raw.decode(), CorrelatedMethod.model_validate(provenance["native_protocol"])


@pytest.mark.parametrize("name,energy,reference", [
    ("MP2", -76.228481977056, -76.02664055123651),
    ("F12-MP2", -76.357856229527, -76.05832266501386),
    ("F12-RI-MP2", -76.357854652257, -76.05832266501386),
    ("CCSD(T)-F12D_RI", -76.353781291528, -76.05832266501386),
])
def test_genuine_hosted_result_and_precise_orbital_reference(name, energy, reference):
    raw, protocol = native_case(name)
    result = parse_correlated_output(raw, protocol)
    assert result["energy_hartree"] == energy
    assert result["reference_energy_hartree"] == reference
    assert result["reference_energy_sources"]["total_scf_energy"] == reference
    if name != "MP2":
        assert "not the pure F12 correlation partition" in result["total_correlation_energy_scope"]


def test_actual_f12d_unscaled_triples_confirmation_cannot_select_scaled_alternative():
    raw, protocol = native_case("CCSD(T)-F12D_RI")
    result = parse_correlated_output(raw, protocol)
    assert result["method_result_energy_hartree"] == -76.353781292
    assert "F12-ECCSD(T) with (T) scaled through CCSD" in raw
    # Corruption cases derive from the unchanged native fixture. The adjacent
    # CCSD and scaled-(T) results cannot stand in for unscaled CCSD(T)-F12D/RI.
    missing = re.sub(r"(?m)^.*F12-E\(CCSD\(T\)\).*$", "", raw)
    with pytest.raises(EngineParseError, match="not confirmed"):
        parse_correlated_output(missing, protocol)
    scaled = re.sub(r"(FINAL SINGLE POINT ENERGY\s+)-76\.353781291528", r"\g<1>-76.354884062", raw)
    with pytest.raises(EngineParseError, match="not confirmed"):
        parse_correlated_output(scaled, protocol)


@pytest.mark.parametrize("damage", ["normal-termination", "scf", "version", "reference"])
def test_f12d_native_format_acceptance_keeps_failure_gates(damage):
    raw, protocol = native_case("CCSD(T)-F12D_RI")
    if damage == "normal-termination":
        raw = raw.replace("ORCA TERMINATED NORMALLY", "ORCA TERMINATED ABNORMALLY")
    elif damage == "scf":
        raw = raw.replace("SCF CONVERGED AFTER", "SCF NOT CONVERGED AFTER")
    elif damage == "version":
        raw = raw.replace("Program Version 6.1.1", "Program Version 6.0.1")
    else:
        raw = re.sub(r"(E\(0\)\s*\.\.\.\s*)-76\.058322665", r"\g<1>-76.048322665", raw)
    with pytest.raises(EngineParseError):
        parse_correlated_output(raw, protocol)


@pytest.mark.parametrize("name,correlation,total", [
    ("F12-MP2", -.296078613898, -76.357856229527),
    ("F12-RI-MP2", -.296077036628, -76.357854652257),
])
def test_actual_conventional_and_ri_partitions_keep_hf_cabs_and_correlation_distinct(name, correlation, total):
    raw, protocol = native_case(name)
    parsed = parse_f12_mp2_partition(raw)
    verified = parse_correlated_output(raw, protocol)
    assert parsed["total_hartree"] == verified["energy_hartree"] == total
    assert parsed["hf_hartree"] == pytest.approx(verified["reference_energy_hartree"], abs=1e-11)
    assert parsed["cabs_singles_hartree"] == -.003454950615
    assert parsed["hf_plus_cabs_hartree"] == -76.061777615629
    assert parsed["f12_correlation_hartree"] == correlation
    assert parsed["hf_plus_cabs_hartree"] + correlation == pytest.approx(total, abs=2e-12)
    assert abs((total - parsed["hf_hartree"]) - correlation) > .003


def test_different_spelled_cabs_labels_cannot_duplicate_one_physical_term():
    raw, _ = native_case("F12-MP2")
    with pytest.raises(EngineParseError, match="duplicates"):
        parse_f12_mp2_partition(raw + "\n(2)_S CABS correction to EHF : -0.003454950615\n")
    with pytest.raises(EngineParseError, match="do not sum"):
        parse_f12_mp2_partition(raw.replace("-0.003454950615", "-0.004454950615"))


def test_reference_is_scoped_to_scf_block_and_compared_with_f12_reference():
    raw, protocol = native_case("F12-MP2")
    # An unscoped total elsewhere cannot replace the HF result.
    result = parse_correlated_output(raw + "\nTotal Energy : -100.0 Eh\n", protocol)
    assert result["reference_energy_hartree"] == -76.05832266501386
    inconsistent = raw.replace("Hartree-Fock energy                :     -76.058322665014",
                               "Hartree-Fock energy                :     -76.048322665014")
    with pytest.raises(EngineParseError, match="HF reference labels disagree"):
        parse_correlated_output(inconsistent, protocol)
