"""CREST parser contracts and live, optional CREST/xTB integration evidence."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from threading import Event

import pytest

from topos.engines import EngineParseError
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.sampling import parse_crest_ensemble, run_crest


@pytest.fixture
def water():
    return Molecule(symbols=["O", "H", "H"],
                    coordinates=[[0, 0, 0], [.9584, 0, 0], [-.239, .927, 0]])


@pytest.fixture
def method():
    return MethodSpec(engine="xtb", method="GFN2-xTB")


@pytest.fixture
def water_dimer():
    return Molecule(symbols=["O", "H", "H", "O", "H", "H"],
                    coordinates=[[0, 0, 0], [.9584, 0, 0], [-.239, .927, 0],
                                 [2.9, 0, 0], [3.15, .92, 0], [3.15, -.92, 0]],
                    fragments=[[0, 1, 2], [3, 4, 5]])


@pytest.fixture
def native_samplers():
    crest = shutil.which(os.environ.get("TOPOS_CREST_EXECUTABLE", "crest"))
    xtb = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if not crest or not xtb:
        pytest.skip("authentic CREST and xTB binaries required; no sampler substitute")
    return {"executable": crest, "xtb_executable": xtb}


def test_unavailable_sampler_is_not_internal_jiggle(water, method, tmp_path):
    result = run_crest(water, method, ResourceLimits(), tmp_path / "run",
                       executable=str(tmp_path / "missing-crest"))
    assert result.status == "unavailable"
    assert not result.ensemble and result.converged is None
    assert result.engine == "crest" and result.method == "GFN2-xTB"
    assert result.metadata["execution_kind"] == "not-executed"


def test_numeric_seed_cannot_be_falsely_claimed(water, method, tmp_path):
    result = run_crest(water, method, ResourceLimits(), tmp_path / "run", seed=17)
    assert result.status == "unsupported" and result.metadata["effective_seed"] is None
    assert "random seed unsupported" in result.diagnostics["reason"]


def test_isotope_md_not_silently_replaced(water, method, tmp_path):
    data = water.model_dump()
    data["isotopes"] = [18, 2, 1]
    result = run_crest(Molecule(**data), method, ResourceLimits(), tmp_path / "run")
    assert result.status == "unsupported" and "isotope" in result.diagnostics["reason"]


@pytest.mark.parametrize("window", [0, -1, float("nan"), float("inf"), True, "12"])
def test_invalid_native_window_is_rejected_before_execution(water, method, tmp_path, window):
    result = run_crest(water, method, ResourceLimits(), tmp_path / "run",
                       energy_window_kcal_mol=window)
    assert result.status == "unsupported"
    assert "finite positive" in result.diagnostics["reason"]
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("nci,fragmented", [(False, False), (False, True), (True, False)])
def test_nci_profile_requires_explicit_confinement_and_fragments(
    water, water_dimer, method, tmp_path, nci, fragmented,
):
    result = run_crest(water_dimer if fragmented else water, method, ResourceLimits(), tmp_path / "run",
                       profile="crest-nci-v1", nci=nci)
    assert result.status == "unsupported"
    assert "at least two declared fragments" in result.diagnostics["reason"]
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("change", [{"method": "GFN-FF"}, {"solvent": "water"},
                                   {"constraints": {"frozen_atoms": [0]}}])
def test_sampler_cannot_change_potential_or_drop_constraints(water, method, tmp_path, change):
    request = method.model_dump()
    request.update(change)
    result = run_crest(water, MethodSpec(**request), ResourceLimits(), tmp_path / "run")
    assert result.status == "unsupported"
    assert result.metadata["potential_spec"] == request


def test_all_frames_and_raw_electronic_energies_preserved(tmp_path, water):
    frame = "3\n{energy} source=mtd1\nO 0 0 0\nH .95 0 0\nH -.24 .92 0\n"
    path = tmp_path / "crest_conformers.xyz"
    path.write_text(frame.format(energy=-5.1) + frame.format(energy=-5.0))
    ensemble = parse_crest_ensemble(path, water)
    assert len(ensemble) == 2
    assert [x.energy_hartree for x in ensemble] == [-5.1, -5.0]
    assert [x.source_index for x in ensemble] == [1, 2]
    assert all(x.molecule.atom_ids == water.atom_ids for x in ensemble)
    assert all(x.metadata["validation_status"] == "requires-common-level-refinement" for x in ensemble)
    assert all("source=mtd1" in x.metadata["raw_comment"] for x in ensemble)
    assert "population" not in ensemble[0].metadata


@pytest.mark.parametrize("text", [
    "3\n-5.0\nO 0 0 0\nH .95 0 0\n",
    "3\nnan\nO 0 0 0\nH .95 0 0\nH -.24 .92 0\n",
    "3\n-5.0\nC 0 0 0\nH .95 0 0\nH -.24 .92 0\n",
    "3\n-5.0\nO 0 0 0\nH nan 0 0\nH -.24 .92 0\n",
    "3\n-5.0\nO 0 0 0\nH garbage 0 0\nH -.24 .92 0\n",
])
def test_partial_nonfinite_or_remapped_ensemble_rejected(tmp_path, water, text):
    path = tmp_path / "crest_conformers.xyz"
    path.write_text(text)
    with pytest.raises(EngineParseError):
        parse_crest_ensemble(path, water)


def test_authentic_crest_ensemble(water, method, tmp_path, native_samplers):
    profile = "crest-mquick-v1"
    result = run_crest(water, method, ResourceLimits(budget_seconds=45), tmp_path / "crest",
                       profile=profile, **native_samplers)
    assert result.status == "completed", result.diagnostics
    assert result.converged and result.ensemble
    assert result.engine_version == "3.0.2" and result.potential_engine_version == "6.7.1"
    assert result.metadata["execution_kind"] == "real"
    assert result.metadata["effective_seed"] is None and result.metadata["exhaustive"] is False
    assert result.metadata["reduced_search"] == (profile == "crest-mquick-v1")
    assert result.ensemble[0].energy_hartree < -5
    assert any(Path(a.path).name == "crest_conformers.xyz" for a in result.artifacts)
    assert any(Path(a.path).name == "crest.stdout" for a in result.artifacts)
    assert "--legacy" in result.command and "--xnam" in result.command
    assert result.diagnostics["native_screening"]["rmsd_threshold_angstrom"] is not None
    assert result.diagnostics["native_screening"]["rotational_threshold"] == pytest.approx(.01)
    # mquick's unoverridden default is 2.5 kcal/mol, not the requested 6.
    assert result.diagnostics["native_screening"]["energy_window_kcal_mol"] == 6
    assert result.command.index("--ewin") > result.command.index("--mquick")
    assert result.metadata["native_energy_window_kcal_mol"] == 6
    assert all(frame.metadata["adapter_attempt_status"] == "completed" for frame in result.ensemble)
    assert all(frame.metadata["partial_native_attempt"] is False for frame in result.ensemble)


def test_authentic_native_single_conformer_gc_failure_is_preserved(water, method, tmp_path, native_samplers):
    # CREST 3.0.2 legacy iMTD-GC has an upstream failure at genetic crossing
    # for this single-conformer water fixture. It must not become a pass or
    # silently switch to --nocross/mquick to hide that scientific limitation.
    result = run_crest(water, method, ResourceLimits(budget_seconds=120), tmp_path / "full",
                       profile="crest-imtdgc-v1", **native_samplers)
    assert result.status == "failed", result.diagnostics
    assert result.converged is False
    assert "lacked enough structures" in result.diagnostics["native_failure"]
    assert "--mquick" not in result.command and "--nocross" not in result.command
    stderr = next(Path(a.path) for a in result.artifacts if Path(a.path).name == "crest.stderr")
    assert "ERROR STOP" in stderr.read_text()


def test_authentic_nci_sampling_records_confinement(water_dimer, method, tmp_path, native_samplers):
    result = run_crest(water_dimer, method, ResourceLimits(budget_seconds=60), tmp_path / "nci",
                       profile="crest-mquick-v1", nci=True, energy_window_kcal_mol=12, **native_samplers)
    assert result.status == "completed", result.diagnostics
    assert result.ensemble and result.metadata["nci_confinement"] is True
    assert "--nci" in result.command
    assert result.ensemble[0].molecule.fragments == water_dimer.fragments
    assert "biases sampling" in result.metadata["nci_semantics"]
    assert result.diagnostics["native_screening"]["energy_window_kcal_mol"] == 12


def test_authentic_cancelled_preflight_does_not_claim_an_ensemble(water, method, tmp_path, native_samplers):
    cancelled = Event()
    cancelled.set()
    result = run_crest(water, method, ResourceLimits(budget_seconds=5), tmp_path / "cancelled",
                       cancel_event=cancelled, **native_samplers)
    assert result.status == "cancelled" and not result.ensemble
    assert result.converged is None
    assert result.metadata["execution_kind"] == "not-executed"
    assert result.command == []


def test_authentic_matrix_nci_profile(water_dimer, method, tmp_path, native_samplers):
    result = run_crest(water_dimer, method, ResourceLimits(budget_seconds=90), tmp_path / "matrix-nci",
                       profile="crest-nci-v1", nci=True, energy_window_kcal_mol=12, **native_samplers)
    assert result.status == "completed", result.diagnostics
    assert result.converged and result.ensemble
    assert result.metadata["reduced_search"] is False
    assert result.metadata["initial_topology_check"] is False
    assert result.metadata["disabled_native_stages"] == ["genetic crossing"]
    assert "--mquick" not in result.command
    assert all(flag in result.command for flag in ("--nocross", "--noreftopo", "--nci"))
    assert result.diagnostics["native_screening"]["energy_window_kcal_mol"] == 12
    assert all(frame.metadata["stationary_point_classification"] == "unclassified" for frame in result.ensemble)
    assert all(frame.metadata["validation_status"] == "requires-common-level-refinement" for frame in result.ensemble)
    raw = (tmp_path / "matrix-nci" / "crest.stdout").read_text()
    assert "Automatically generated ellipsoide potential for NCI mode:" in raw
    assert "--nocross  : skipping GC part." in raw
    assert "CREST terminated normally." in raw
