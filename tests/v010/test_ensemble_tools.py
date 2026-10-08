"""Native supplied-ensemble operations; executable tests use actual CREST/xTB.

Handwritten XYZ/ENSO records below exercise only parser arithmetic and rejection
contracts. They are never passed off as native engine evidence.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from threading import Event

import pytest

from topos.engines import EngineParseError, run_engine
from topos.ensemble_tools import parse_cregen_result, run_cregen, run_crest_screen
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.runtime import run_process
from topos.sampling import SampledConformer


@pytest.fixture
def water():
    return Molecule(symbols=["O", "H", "H"],
                    coordinates=[[0, 0, 0], [.9584, 0, 0], [-.239, .927, 0]])


@pytest.fixture
def frame(water):
    # Mathematical serialization fixture, not an asserted chemical calculation.
    return SampledConformer(molecule=water, energy_hartree=-5.01234567891234,
                            source_index=42, source="parser-contract", metadata={"record": "source-42"})


@pytest.fixture
def native_tools():
    tools = {name: shutil.which(os.environ.get(f"TOPOS_{name.upper()}_EXECUTABLE", name))
             for name in ("crest", "xtb")}
    if not all(tools.values()):
        pytest.skip("authentic CREST 3.0.2 and xTB 6.7.1 required; no fabricated executable")
    return tools


@pytest.fixture
def actual_frames(water, native_tools, tmp_path):
    method = MethodSpec(engine="xtb", method="GFN2-xTB", profile_id="xtb-tight-v1")
    optimized = run_engine(water, method, ResourceLimits(budget_seconds=30), tmp_path / "xtb-opt",
                           executable=native_tools["xtb"], process_runner=run_process)
    assert optimized.status == "completed", optimized.diagnostics
    distorted_data = optimized.molecule.model_dump()
    distorted_data["coordinates"][1][0] += .02
    distorted = Molecule(**distorted_data)
    electronic = run_engine(distorted, method, ResourceLimits(budget_seconds=30), tmp_path / "xtb-energy",
                            operation="energy", executable=native_tools["xtb"], process_runner=run_process)
    assert electronic.status == "completed", electronic.diagnostics
    return [
        SampledConformer(molecule=optimized.molecule, energy_hartree=optimized.energy_hartree,
                         source_index=13, source="xtb", metadata={"operation": "optimize"}),
        SampledConformer(molecule=distorted, energy_hartree=electronic.energy_hartree,
                         source_index=29, source="xtb", metadata={"operation": "energy"}),
    ]


def _parser_files(tmp_path, frame, *, tag=None, coordinate=None, energy=None):
    xyz = tmp_path / "crest_ensemble.xyz"
    rows = frame.molecule.coordinates if coordinate is None else coordinate
    xyz.write_text(f"3\n{frame.energy_hartree if energy is None else energy:.8f}\n" + "".join(
        f"{symbol} {x:.10f} {y:.10f} {z:.10f}\n"
        for symbol, (x, y, z) in zip(frame.molecule.symbols, rows, strict=True)
    ))
    tags = tmp_path / "enso.tags"
    tags.write_text(tag if tag is not None else f"{frame.energy_hartree:.17g} !topos_00000001\n")
    return xyz, tags


def test_parser_recovers_exact_source_energy_and_index_without_print_precision_loss(frame, tmp_path):
    files = _parser_files(tmp_path, frame)
    result = parse_cregen_result(*files, [frame], "external-common-level")
    assert len(result) == 1
    assert result[0].energy_hartree == frame.energy_hartree
    assert result[0].source_index == 42
    assert result[0].metadata["input_position"] == 1
    assert result[0].metadata["input_source_index"] == 42
    assert result[0].metadata["input_metadata"] == {"record": "source-42"}
    assert result[0].metadata["native_rounded_energy_hartree"] != frame.energy_hartree
    assert result[0].molecule.atom_ids == frame.molecule.atom_ids
    assert result[0].molecule.charge == frame.molecule.charge
    assert result[0].molecule.multiplicity == frame.molecule.multiplicity


@pytest.mark.parametrize("tag", ["", "-5.0\n", "-5.0 !topos_00000001\n",
                                  "-5.01234567891234 !topos_00000003\n"])
def test_parser_rejects_lost_changed_or_unknown_source_energy_tags(frame, tmp_path, tag):
    files = _parser_files(tmp_path, frame, tag=tag)
    with pytest.raises(EngineParseError):
        parse_cregen_result(*files, [frame], "external-common-level")


def test_parser_rejects_geometry_change_that_cannot_be_native_alignment(frame, tmp_path):
    coordinates = [list(row) for row in frame.molecule.coordinates]
    coordinates[1][0] += .01
    files = _parser_files(tmp_path, frame, coordinate=coordinates)
    with pytest.raises(EngineParseError, match="geometry or atom mapping"):
        parse_cregen_result(*files, [frame], "external-common-level")


def test_parser_rejects_native_energy_replacement(frame, tmp_path):
    files = _parser_files(tmp_path, frame, energy=frame.energy_hartree + .001)
    with pytest.raises(EngineParseError, match="beyond native print rounding"):
        parse_cregen_result(*files, [frame], "external-common-level")


def test_parser_preserves_state_and_isotopes_when_parsing_only(frame, tmp_path):
    # Parsing preserves labels; execution rejects unsupported native mass use.
    frame.molecule = frame.molecule.model_copy(update={"isotopes": [18, 2, 1]})
    result = parse_cregen_result(*_parser_files(tmp_path, frame), [frame], "external-common-level")
    assert result[0].molecule.isotopes == [18, 2, 1]


def test_parser_preserves_charged_open_shell_state(frame, tmp_path):
    data = frame.molecule.model_dump()
    data.update(charge=1, multiplicity=2)
    frame.molecule = Molecule(**data)
    result = parse_cregen_result(*_parser_files(tmp_path, frame), [frame], "external-common-level")
    assert result[0].molecule.charge == 1
    assert result[0].molecule.multiplicity == 2


@pytest.mark.parametrize("setting", [0, -1, float("nan"), float("inf"), True, "0.001"])
def test_bad_thresholds_rejected_before_launch(frame, tmp_path, setting):
    result = run_cregen([frame], ResourceLimits(), tmp_path / "run", comparison_protocol="common",
                        rotational_threshold=setting, process_runner=run_process)
    assert result.status == "unsupported"
    assert "finite positive" in result.diagnostics["reason"]
    assert not (tmp_path / "run").exists()


def test_ensemble_identity_changes_cannot_be_silently_dropped(frame, tmp_path):
    altered = frame.model_copy(deep=True)
    altered.molecule.atom_ids = ["changed", "atom-1", "atom-2"]
    result = run_cregen([frame, altered], ResourceLimits(), tmp_path / "run",
                        comparison_protocol="common", process_runner=run_process)
    assert result.status == "unsupported"
    assert "atom order/IDs" in result.diagnostics["reason"]


def test_isotope_rotational_constants_are_not_silently_ignored(frame, tmp_path):
    frame.molecule = frame.molecule.model_copy(update={"isotopes": [18, None, None]})
    result = run_cregen([frame], ResourceLimits(), tmp_path / "run",
                        comparison_protocol="common", process_runner=run_process)
    assert result.status == "unsupported"
    assert "isotope-mass" in result.diagnostics["reason"]


def test_opposite_handed_inputs_do_not_enter_native_reflection_merge(tmp_path):
    molecule = Molecule(symbols=["C", "F", "Cl", "Br", "H"],
                        coordinates=[[0, 0, 0], [1, 1, 1], [-1, -1, 1], [-1, 1, -1], [1, -1, -1]])
    reflected = molecule.model_copy(update={"coordinates": [[-x, y, z] for x, y, z in molecule.coordinates]})
    frames = [SampledConformer(molecule=m, energy_hartree=-1, source_index=i)
              for i, m in enumerate((molecule, reflected), 1)]
    result = run_cregen(frames, ResourceLimits(), tmp_path / "run",
                        comparison_protocol="geometry-contract", process_runner=run_process)
    assert result.status == "unsupported"
    assert "opposite-handed" in result.diagnostics["reason"]


def test_fresh_workdir_and_common_protocol_required(frame, tmp_path):
    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / "crest_ensemble.xyz").write_text("old native output")
    result = run_cregen([frame], ResourceLimits(), stale, comparison_protocol="common",
                        process_runner=run_process)
    assert result.status == "failed" and "fresh" in result.diagnostics["reason"]
    result = run_cregen([frame], ResourceLimits(), tmp_path / "run", comparison_protocol=" ",
                        process_runner=run_process)
    assert result.status == "unsupported" and "common-level" in result.diagnostics["reason"]


def test_missing_authentic_binary_never_substitutes_internal_dedup(frame, tmp_path):
    result = run_cregen([frame], ResourceLimits(), tmp_path / "run", comparison_protocol="common",
                        executable=tmp_path / "missing", process_runner=run_process)
    assert result.status == "unavailable" and not result.ensemble
    assert result.metadata["execution_kind"] == "not-executed"


def test_default_execution_requires_mandatory_base_setup(frame, tmp_path, monkeypatch):
    monkeypatch.setenv("COCHEM_BASE_ROOT", str(tmp_path / "absent-base-checkout"))
    result = run_cregen([frame], ResourceLimits(), tmp_path / "run", comparison_protocol="common")
    assert result.status == "unavailable"
    assert "COCHEM_BASE_ROOT" in result.diagnostics["reason"]
    assert result.metadata["execution_kind"] == "not-executed"
    assert not (tmp_path / "run").exists()


def test_actual_cregen_preserves_external_energies_and_all_distinct_frames(actual_frames, native_tools, tmp_path):
    result = run_cregen(actual_frames, ResourceLimits(budget_seconds=30), tmp_path / "native-cregen",
                        comparison_protocol="actual-GFN2-xTB-6.7.1", executable=native_tools["crest"],
                        process_runner=run_process)
    assert result.status == "completed", result.diagnostics
    assert result.engine_version == "3.0.2" and result.potential_engine_version is None
    assert result.converged and len(result.ensemble) == 2
    by_source = {f.source_index: f for f in actual_frames}
    assert {f.source_index for f in result.ensemble} == {13, 29}
    for native in result.ensemble:
        assert native.energy_hartree == by_source[native.source_index].energy_hartree
    assert result.diagnostics["native_screening"]["rotational_threshold"] == .001
    assert result.metadata["native_sorted_frame_count"] == 2
    assert result.command[result.command.index("--cregen") + 1] == "ensemble.xyz"
    assert "--enso" in result.command and "--gfn2" not in result.command
    assert {"supplied-ensemble.json", "enso.tags", "ensemble.xyz.sorted", "crest_ensemble.xyz", "cregen.stdout"} <= {
        Path(a.path).name for a in result.artifacts}
    assert result.metadata["execution_kind"] == "real"
    assert all(not f.metadata["partial_native_attempt"] for f in result.ensemble)


def test_actual_native_screen_runs_multilevel_xtb_before_common_refinement(actual_frames, native_tools, tmp_path):
    result = run_crest_screen(actual_frames, ResourceLimits(budget_seconds=45), tmp_path / "native-screen",
                             executable=native_tools["crest"], xtb_executable=native_tools["xtb"],
                             process_runner=run_process)
    assert result.status == "completed", result.diagnostics
    assert result.engine_version == "3.0.2" and result.potential_engine_version == "6.7.1"
    assert result.converged and len(result.ensemble) == 1
    assert result.ensemble[0].energy_hartree < -5
    assert result.ensemble[0].metadata["validation_status"] == "requires-common-level-refinement"
    assert result.metadata["reoptimizes_geometry"]
    assert result.command[result.command.index("--screen") + 1] == "ensemble.xyz"
    assert "--legacy" in result.command and "--xnam" in result.command
    source = json.loads((tmp_path / "native-screen" / "supplied-ensemble.json").read_text())
    assert [row["energy_hartree"] for row in source] == [f.energy_hartree for f in actual_frames]
    assert result.diagnostics["native_screening"]["energy_window_kcal_mol"] == 12


def test_actual_cregen_deduplicates_identical_real_records_without_losing_attribution(actual_frames, native_tools, tmp_path):
    duplicate = actual_frames[0].model_copy(update={"source_index": 101})
    result = run_cregen([actual_frames[0], duplicate], ResourceLimits(budget_seconds=30), tmp_path / "native-duplicate",
                        comparison_protocol="actual-GFN2-xTB-6.7.1", executable=native_tools["crest"],
                        process_runner=run_process)
    assert result.status == "completed", result.diagnostics
    assert len(result.ensemble) == 1
    assert result.ensemble[0].source_index in {13, 101}
    assert result.ensemble[0].energy_hartree == actual_frames[0].energy_hartree
    assert result.metadata["native_sorted_frame_count"] == 1


@pytest.mark.parametrize("operation", ["screen", "cregen"])
def test_actual_native_prelaunch_cancellation_keeps_input_artifacts(frame, native_tools, tmp_path, operation):
    cancel = Event()
    cancel.set()
    keywords = dict(executable=native_tools["crest"], process_runner=run_process, cancel_event=cancel)
    if operation == "screen":
        result = run_crest_screen([frame], ResourceLimits(), tmp_path / "run",
                                 xtb_executable=native_tools["xtb"], **keywords)
    else:
        result = run_cregen([frame], ResourceLimits(), tmp_path / "run", comparison_protocol="parser-contract", **keywords)
    assert result.status == "cancelled"
    assert not result.ensemble and result.converged is None
    assert (tmp_path / "run" / "supplied-ensemble.json").is_file()


def test_actual_native_tiny_deadline_never_reports_completion(frame, native_tools, tmp_path):
    result = run_cregen([frame], ResourceLimits(budget_seconds=1e-8), tmp_path / "run",
                        comparison_protocol="parser-contract", executable=native_tools["crest"],
                        process_runner=run_process)
    assert result.status == "timed-out" and not result.ensemble
    assert result.metadata["execution_kind"] == "not-executed"
