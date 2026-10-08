"""GOAT input/parser/control fixtures, explicitly not licensed ORCA execution.

The runner fixture writes tiny labelled output examples to test adapter decisions.
Its executable marker files are never executed and supply no chemical evidence.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from topos.engines import EngineParseError
from topos.goat import goat_input, parse_goat_ensemble, run_goat
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.runtime import ProcessResult


@pytest.fixture
def molecule():
    return Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [0.95, 0, 0], [-.24, .93, 0]])


@pytest.fixture
def method():
    return MethodSpec(engine="xtb", method="GFN2-xTB", engine_version="6.7.1", profile_id="xtb-vtight-v1")


@pytest.fixture
def fixture_runner(tmp_path):
    installed = tmp_path / "fixture-only-not-real-engines"
    installed.mkdir()
    orca, xtb, helper = installed / "orca", installed / "xtb", installed / "otool_xtb"
    orca.write_bytes(b"parser infrastructure marker; never execute")
    xtb.write_bytes(b"matching xTB identity fixture; never execute")
    helper.write_bytes(xtb.read_bytes())
    for path in (orca, xtb, helper):
        path.chmod(0o700)
    calls = []
    state = {"orca_version": "6.1.1", "xtb_version": "6.7.1", "status": "completed",
             "window": 12.0, "minimum": -10.0, "converged": True,
             "ensemble": "3\nEnergy -10.0\nO 0 0 0\nH .95 0 0\nH -.24 .93 0\n",
             "write_final": True, "normal": True}

    def runner(command, folder, resources, *, cancel_event=None, log_prefix="engine", **kwargs):
        folder = Path(folder)
        calls.append({"command": command, "resources": resources, "prefix": log_prefix, **kwargs})
        if log_prefix == "xtb-version":
            raw, status = f"xtb version {state['xtb_version']}\n", "completed"
        elif log_prefix == "version":
            raw = (f"Program Version {state['orca_version']}\nSCF CONVERGED AFTER 1 CYCLES\n"
                   "FINAL SINGLE POINT ENERGY -1.0\nORCA TERMINATED NORMALLY\n")
            status = "completed"
        else:
            raw = (f"Program Version {state['orca_version']}\n"
                   f"Maximum Conf. Energy ... {state['window']:.3f} kcal/mol\n"
                   f"Lowest energy conformer : {state['minimum']:.6f} Eh\n")
            if state["converged"]:
                raw += "Global minimum found!\n"
            if state["normal"]:
                raw += "ORCA TERMINATED NORMALLY\n"
            if state["write_final"]:
                raw += "Writing final ensemble to goat.finalensemble.xyz\n"
                (folder / "goat.finalensemble.xyz").write_text(state["ensemble"])
            status = state["status"]
        stdout, stderr = folder / f"{log_prefix}.stdout", folder / f"{log_prefix}.stderr"
        stdout.write_text(raw)
        stderr.write_text("")
        return ProcessResult(command, status, 0 if status == "completed" else -1,
                             0.001, 1, str(stdout), str(stderr), "fixture termination" if status != "completed" else None)

    return orca, xtb, helper, runner, state, calls


def test_goat_deck_keeps_external_xtb_identity_and_explicit_uphill_controls(molecule, method):
    deck = goat_input(molecule, method, ResourceLimits(threads=1, memory_mb=1024),
                      uphill_method="GFN-FF", deterministic=True, max_global_iterations=7)
    assert "! XTB2 GOAT TightOpt TightSCF DEFGRID3" in deck
    assert "Native-XTB" not in deck
    assert "%pal nprocs 1 end" in deck and "%maxcore 768" in deck
    assert "NWORKERS 4" in deck and "MAXGLOBALITER 7" in deck
    assert "MINGLOBALITER 3" in deck and "RANDOMSEED false" in deck
    assert "KEEPWORKERDATA true" in deck and "CONFDEGEN auto" in deck
    assert "GFNUPHILL gfnff" in deck and "MAXEN 12" in deck
    assert "EnforceStrictConvergence true" in deck
    assert "* xyz 0 1" in deck


def test_composite_keeps_native_recipe_and_does_not_add_force_field(molecule):
    method = MethodSpec(engine="orca", method="r2SCAN-3c", engine_version="6.1.1", profile_id="orca-mapping-v4.1")
    deck = goat_input(molecule, method, ResourceLimits())
    assert "! r2SCAN-3c GOAT" in deck
    assert "GFNUPHILL" not in deck and "def2" not in deck


@pytest.mark.parametrize("options", [
    {"energy_window_kcal_mol": 0}, {"energy_window_kcal_mol": float("nan")},
    {"deterministic": 1}, {"max_global_iterations": 1}, {"max_global_iterations": True},
    {"uphill_method": "invented"},
])
def test_unsupported_native_options_rejected(molecule, method, options):
    with pytest.raises(ValueError):
        goat_input(molecule, method, ResourceLimits(), **options)


def test_unsupported_constraints_isotopes_and_methods_are_not_dropped(molecule, method):
    with pytest.raises(ValueError, match="constraints"):
        goat_input(molecule, method.model_copy(update={"constraints": {"freeze": [0]}}), ResourceLimits())
    with pytest.raises(ValueError, match="isotope"):
        goat_input(molecule.model_copy(update={"isotopes": [16, 1, 1]}), method, ResourceLimits())
    with pytest.raises(ValueError):
        goat_input(molecule, method.model_copy(update={"method": "GFN-FF"}), ResourceLimits())


def test_native_frames_keep_mapping_comment_and_observation_status(molecule, tmp_path):
    path = tmp_path / "native.xyz"
    path.write_text("3\nEnergy -10.0\nO 0 0 0\nH .95 0 0\nH -.24 .93 0\n"
                    "3\nEnergy -9.9 Eh\nO .1 0 0\nH 1.05 0 0\nH -.14 .93 0\n")
    frames = parse_goat_ensemble(path, molecule)
    assert [frame.energy_hartree for frame in frames] == [-10, -9.9]
    assert [frame.source_index for frame in frames] == [1, 2]
    assert all(frame.source == "GOAT" for frame in frames)
    assert frames[1].molecule.atom_ids == molecule.atom_ids
    assert frames[1].metadata["validation_status"] == "requires-common-level-refinement"
    assert frames[1].metadata["raw_comment"] == "Energy -9.9 Eh"


@pytest.mark.parametrize("text", [
    "3\nEnergy NaN\nO 0 0 0\nH .95 0 0\nH -.24 .93 0\n",
    "3\nEnergy -10 kcal/mol\nO 0 0 0\nH .95 0 0\nH -.24 .93 0\n",
    "3\nEnergy -10\nO 0 0 0\nH .95 0 0\n",
    "3\nEnergy -10\nH 0 0 0\nO .95 0 0\nH -.24 .93 0\n",
    "",
])
def test_malformed_native_ensemble_never_invents_results(molecule, tmp_path, text):
    path = tmp_path / "bad.xyz"
    path.write_text(text)
    with pytest.raises(EngineParseError):
        parse_goat_ensemble(path, molecule)


def run_fixture(molecule, method, fixture_runner, tmp_path, **kwargs):
    orca, xtb, _, runner, _, _ = fixture_runner
    return run_goat(molecule, method, ResourceLimits(budget_seconds=30), tmp_path / "attempt",
                    executable=orca, xtb_executable=xtb, process_runner=runner, **kwargs)


def test_adapter_pipeline_preserves_real_command_identity_under_explicit_runner_fixture(molecule, method, fixture_runner, tmp_path):
    result = run_fixture(molecule, method, fixture_runner, tmp_path, uphill_method="GFN-FF")
    assert result.status == "completed", result.diagnostics
    assert result.engine == "orca" and result.engine_version == "6.1.1"
    assert result.potential_engine == "xtb" and result.potential_engine_version == "6.7.1"
    assert result.command[-1] == "goat.inp"
    assert [call["prefix"] for call in fixture_runner[-1]] == ["xtb-version", "version", "goat"]
    assert len(result.ensemble) == 1 and result.converged
    assert result.metadata["exhaustive"] is False
    assert result.metadata["version_probe"]["scientific_result_eligibility"] is False
    assert "live ORCA 6.1.1 acceptance pending" in result.metadata["adapter_validation"]
    assert {Path(item.path).name for item in result.artifacts} >= {"goat.inp", "goat.stdout", "goat.finalensemble.xyz"}


def test_composite_goat_needs_no_external_xtb_when_no_xtb_uphill_selected(molecule, fixture_runner, tmp_path):
    method = MethodSpec(engine="orca", method="r2SCAN-3c", profile_id="orca-mapping-v4.1")
    fixture_runner[2].unlink()
    result = run_fixture(molecule, method, fixture_runner, tmp_path)
    assert result.status == "completed"
    assert result.potential_engine_version == "6.1.1"
    assert [call["prefix"] for call in fixture_runner[-1]] == ["version", "goat"]


def test_total_pal_allocation_is_separate_from_nested_thread_limit(molecule, method, fixture_runner, tmp_path, monkeypatch):
    monkeypatch.setattr("topos.engines.available_cpu_count", lambda: 4)
    orca, xtb, _, runner, _, calls = fixture_runner
    result = run_goat(molecule, method, ResourceLimits(threads=4), tmp_path / "parallel",
                      executable=orca, xtb_executable=xtb, process_runner=runner)
    assert result.status == "completed", result.diagnostics
    assert calls[-1]["resources"].threads == 4
    assert calls[-1]["threads_per_process"] == 1
    assert all(call["resources"].threads == 1 for call in calls[:-1])


def test_unverified_helper_cannot_be_replaced_by_other_xtb_or_native_xtb(molecule, method, fixture_runner, tmp_path):
    fixture_runner[2].write_bytes(b"different helper")
    result = run_fixture(molecule, method, fixture_runner, tmp_path)
    assert result.status == "unavailable" and not result.ensemble
    assert not fixture_runner[-1]
    assert "differs" in result.diagnostics["reason"]


@pytest.mark.parametrize("name,value", [("orca_version", "6.1.2"), ("xtb_version", "6.6.0")])
def test_version_mismatch_blocks_search(molecule, method, fixture_runner, tmp_path, name, value):
    fixture_runner[4][name] = value
    result = run_fixture(molecule, method, fixture_runner, tmp_path)
    assert result.status == "unavailable" and not result.ensemble
    assert all(call["prefix"] != "goat" for call in fixture_runner[-1])


@pytest.mark.parametrize("name,value", [("window", 6), ("minimum", -20), ("write_final", False), ("normal", False)])
def test_contradictory_or_incomplete_native_output_cannot_be_success(molecule, method, fixture_runner, tmp_path, name, value):
    fixture_runner[4][name] = value
    result = run_fixture(molecule, method, fixture_runner, tmp_path)
    assert result.status == "failed"


def test_global_iteration_limit_without_native_convergence_keeps_partial_observations(molecule, method, fixture_runner, tmp_path):
    fixture_runner[4]["converged"] = False
    result = run_fixture(molecule, method, fixture_runner, tmp_path)
    assert result.status == "partial" and result.converged is False
    assert len(result.ensemble) == 1


@pytest.mark.parametrize("status", ["timed-out", "cancelled"])
def test_native_stop_and_truncated_ensemble_do_not_become_success(molecule, method, fixture_runner, tmp_path, status):
    fixture_runner[4].update(status=status, ensemble="3\nEnergy -10\nO 0 0 0\n")
    result = run_fixture(molecule, method, fixture_runner, tmp_path)
    assert result.status == status
    assert not result.ensemble
    assert "partial_ensemble_parse_error" in result.diagnostics


def test_missing_orca_and_numeric_seed_have_no_fabricated_ensemble(molecule, method, tmp_path):
    missing = run_goat(molecule, method, ResourceLimits(), tmp_path / "absent", executable=tmp_path / "missing")
    assert missing.status == "unavailable" and not missing.ensemble
    numeric = run_goat(molecule, method, ResourceLimits(), tmp_path / "seed", seed=1)
    assert numeric.status == "unsupported" and not numeric.ensemble
