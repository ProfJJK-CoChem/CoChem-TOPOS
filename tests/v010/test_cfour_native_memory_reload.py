"""Actual CFOUR 2.1 output regressions plus deliberate malformed-output negatives.

The fixtures are unmodified owned scientific output from the original licensed
runtime. No native code, basis bytes or simulated scientific data are included.
"""
import json
from pathlib import Path

import pytest

from topos.cfour_gradient import parse_cfour_2_1_gradient
from topos.cfour_memory import cfour_memory_plan
from topos.cfour_scf import validate_cfour_scf
from topos.engines import EngineParseError
from topos.external_engines import ExternalProtocol, cfour_input, parse_cfour_output, run_external
from topos.models import Molecule, ResourceLimits
from topos.storage import file_digest

FIXTURES = Path(__file__).parent / "fixtures/cfour_2_1_mp2_density_reload"


def native(name="water-dimer-seed"):
    folder = FIXTURES / name
    text = (folder / "engine.stdout").read_bytes().decode("utf-8")
    rows = (folder / "ZMAT").read_text().splitlines()[1:]
    rows = rows[:rows.index("")]
    molecule = Molecule(symbols=[row.split()[0] for row in rows],
        coordinates=[[float(v) for v in row.split()[1:]] for row in rows])
    return text, molecule, (folder / "GRD").read_text()


def protocol(**changes):
    return ExternalProtocol(engine="cfour", engine_version="2.1", method="MP2",
        operation="gradient", orbital_basis="PVDZ", frozen_core=True).model_copy(update=changes)


def validate(text, **changes):
    selected = protocol(**changes)
    return validate_cfour_scf(text, engine_version=selected.engine_version, method=selected.method,
        operation=selected.operation, scf_convergence=selected.scf_convergence)


def test_owned_native_output_fixture_hashes_and_scientific_only_membership():
    proof = json.loads((FIXTURES / "provenance.json").read_text())
    assert proof["licensed_assets_included"] is False
    assert proof["scope"] == "Native one-evaluation regression output; not a completed matrix row or independent accuracy reference"
    for name, identity in proof["files"].items():
        assert Path(name).name in {"ZMAT", "GRD", "engine.stdout"}
        assert file_digest(FIXTURES / name) == identity["sha256"]
        assert (FIXTURES / name).stat().st_size == identity["size_bytes"]


@pytest.mark.parametrize("name,energy", [("water", -76.228428602587),
                                         ("water-dimer-seed", -152.461054810568)])
def test_actual_completed_mp2_gradient_accepts_only_its_zero_iteration_density_reload(name, energy):
    text, molecule, grd = native(name)
    result = parse_cfour_output(text, molecule, protocol(), grd=grd)
    assert result["energy_hartree"] == pytest.approx(energy, abs=1e-11)
    assert result["scf_validation"]["profile"] == "cfour-2.1-correlated-zero-iteration-density-reload-v1"
    assert result["scf_validation"]["converged_events"] == 2
    assert result["scf_validation"]["reload_iterations"] == 0
    assert len(result["gradient_hartree_per_bohr"]) == len(molecule.symbols)


@pytest.mark.parametrize("name,method,energy", [
    ("ccsd-water", "CCSD", -76.237995462605),
    ("ccsd-water-dimer-seed", "CCSD", -152.479535405082),
    ("ccsd_t-water", "CCSD(T)", -76.241030496051),
    ("ccsd_t-water-dimer-seed", "CCSD(T)", -152.485944132547)])
def test_actual_ccsd_and_ccsd_t_gradients_have_the_same_verified_density_reload(name, method, energy):
    text, molecule, grd = native(name)
    result = parse_cfour_output(text, molecule, protocol(method=method), grd=grd)
    assert result["energy_hartree"] == pytest.approx(energy, abs=1e-11)
    assert result["scf_validation"]["requested_method"] == method
    assert result["scf_validation"]["reload_iterations"] == 0
    assert len(result["gradient_hartree_per_bohr"]) == len(molecule.symbols)


@pytest.mark.parametrize("change", ["reload_iterations", "reload_guess", "reload_oldmos", "reload_energy",
    "reload_delta", "reload_row", "primary_tolerance", "primary_delta", "reload_reference",
    "preparation_module", "next_module", "completion_order", "truncation", "bare_marker", "embedded_marker",
    "unframed_marker", "repeated_marker", "concatenated_jobs", "initial_scf_repeated"])
def test_malformed_or_unrelated_second_scf_does_not_become_a_density_reload(change):
    text, _, _ = native()
    original_text = text
    first, second = text.split("  Maximum number of iterations:    0", 1)
    if change == "reload_iterations":
        text = first + "  Maximum number of iterations:    1" + second
    elif change == "reload_guess":
        text = first + "  Maximum number of iterations:    0" + second.replace("MOREAD", "HUCKEL")
    elif change == "reload_oldmos":
        text = text.replace("starting vectors read from OLDMOS", "starting vectors read from OTHER")
    elif change == "reload_energy":
        text = first + "  Maximum number of iterations:    0" + second.replace("-152.055057096780018", "-152.055057096780019")
    elif change == "reload_delta":
        text = first + "  Maximum number of iterations:    0" + second.replace("0.0000000000D+00", "0.0000000001D+00")
    elif change == "reload_row":
        text = first + "  Maximum number of iterations:    0" + second.replace("       0          -152.", "       1          -152.")
    elif change == "primary_tolerance":
        text = text.replace("SCF convergence tolerance: 10**(-10)", "SCF convergence tolerance: 10**(-8)")
    elif change == "primary_delta":
        text = first.replace("0.3209255084D-10", "0.3209255084D-08") + "  Maximum number of iterations:    0" + second
    elif change == "reload_reference":
        prefix, suffix = text.rsplit("SCF reference function:  RHF", 1)
        text = prefix + "SCF reference function:  UHF" + suffix
    elif change == "preparation_module":
        text = text.replace("xprepfc2f", "xother")
    elif change == "next_module":
        text = first + "  Maximum number of iterations:    0" + second.replace("xfillfc", "xother")
    elif change == "completion_order":
        text = first + "  Maximum number of iterations:    0" + second.replace("--executable xvscf finished", "--executable xvtran finished", 1)
    elif change == "truncation":
        text = text[:text.rindex("--executable xjoda finished")]
    elif change == "bare_marker":
        text += "\nSCF has converged.\n"
    elif change == "embedded_marker":
        text += "\nUnrelated prose SCF has converged. is not a native event.\n"
    elif change == "unframed_marker":
        text = text.replace("  SCF has converged.\n", "", 1)
        text += "\nSCF has converged.\n"
    elif change == "repeated_marker":
        text = text.replace("  SCF has converged.\n", "  SCF has converged.\n  SCF has converged.\n", 1)
    elif change == "concatenated_jobs":
        text += text
    elif change == "initial_scf_repeated":
        text = first + "  Maximum number of iterations:  150" + second.replace("10**(-**)", "10**(-10)")
    assert text != original_text, "Negative test did not alter the actual native output"
    with pytest.raises(EngineParseError):
        validate(text)


@pytest.mark.parametrize("change", [{"engine_version": "1.2"}, {"method": "CCSDT"},
                                    {"operation": "energy"}, {"scf_convergence": 11}])
def test_unobserved_version_method_operation_or_convergence_cannot_borrow_reload(change):
    text, _, _ = native()
    with pytest.raises(EngineParseError):
        validate(text, **change)


def test_reload_acceptance_still_requires_the_actual_native_grd():
    text, molecule, grd = native()
    with pytest.raises(EngineParseError, match="GRD artifact"):
        parse_cfour_output(text, molecule, protocol())
    with pytest.raises(EngineParseError, match="same indexed result"):
        parse_cfour_output(text, molecule, protocol(), grd=grd.replace("0.0097555502", "0.1097555502"))


@pytest.mark.parametrize("change", ["symbol", "index", "missing_row", "extra_row", "missing_norm",
                                     "extra_table", "missing_completion", "other_version"])
def test_native_indexed_gradient_layout_rejects_incomplete_ambiguous_or_reidentified_table(change):
    text, molecule, _ = native()
    original = text
    line = " O #1       0.0097555502            0.0055965107            0.0000000000"
    assert line in text
    if change == "symbol":
        text = text.replace(line, line.replace("O #1", "C #1"))
    elif change == "index":
        text = text.replace(line, line.replace("#1", "#2"))
    elif change == "missing_row":
        text = text.replace(line + "\n", "")
    elif change == "extra_row":
        text = text.replace(line, line + "\n" + line)
    elif change == "missing_norm":
        text = text.replace("Molecular gradient norm", "Missing gradient norm")
    elif change == "extra_table":
        text += "\n Molecular gradient\n"
    elif change == "missing_completion":
        text = text.replace("--executable xvdint finished", "--executable xother finished")
    elif change == "other_version":
        text = text.replace("Version 2.1", "Version 1.2")
    assert text != original
    with pytest.raises(EngineParseError):
        parse_cfour_2_1_gradient(text, molecule.symbols)


@pytest.mark.parametrize("total,threads,native_mib", [(1024, 1, 256), (2048, 1, 1280),
    (2048, 2, 1152), (2048, 4, 896), (4096, 2, 3072)])
def test_native_workspace_leaves_static_blas_headroom_inside_unchanged_total_bound(total, threads, native_mib):
    resources = ResourceLimits(memory_mb=total, threads=threads)
    before = resources.model_dump()
    plan = cfour_memory_plan(resources)
    assert plan["native_integer_words"] * 8 == native_mib * 1024**2
    assert plan["native_workspace_bytes"] + plan["reserved_headroom_bytes"] <= plan["total_limit_bytes"]
    assert resources.model_dump() == before
    _, molecule, _ = native("water")
    deck = cfour_input(molecule, protocol(), resources)
    assert f"MEMORY_SIZE={native_mib * 1024**2 // 8}" in deck
    assert "MEM_UNIT=INTEGERWORDS" in deck and "SCF_CONV=10" in deck


@pytest.mark.parametrize("total,threads", [(512, 1), (768, 1), (1024, 3)])
def test_impossible_static_blas_reservation_is_rejected_before_native_launch(tmp_path, total, threads):
    resources = ResourceLimits(memory_mb=total, threads=threads)
    _, molecule, _ = native("water")
    def forbidden(*args, **kwargs):
        pytest.fail("Native subprocess launched despite impossible memory reservation")
    result = run_external(molecule, protocol(), resources, tmp_path / "attempt", process_runner=forbidden)
    assert result.status == "unsupported" and "headroom" in result.diagnostics["reason"]
    assert result.metadata["execution_kind"] == "not-executed"
    assert not (tmp_path / "attempt").exists()
