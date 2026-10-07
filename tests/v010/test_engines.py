"""Engine parser/runtime tests and optional authentic xTB 6.7.1 integration.

Small Python subprocesses below test process supervision only. Scientific
integration tests require the actual executable; no fake potential is used.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from threading import Event, Timer

import numpy as np
import pytest
from scipy.constants import physical_constants

from topos.engines import (
    EngineParseError,
    _engine_version,
    _orca_convergence,
    _orca_input,
    _orca_version_input,
    parse_orca_engrad,
    parse_xtb_gradient,
    read_xyz,
    run_engine,
    write_xyz,
)
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.runtime import ProcessResult, run_process


@pytest.fixture
def water():
    return Molecule(symbols=["O", "H", "H"],
                    coordinates=[[0, 0, 0], [0.9584, 0, 0], [-0.239, 0.927, 0]])


@pytest.fixture
def native_xtb():
    binary = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if binary is None:
        pytest.skip("authentic xTB executable unavailable; no substitute engine")
    return binary


def spec(**kwargs):
    return MethodSpec(engine="xtb", method="GFN2-xTB", **kwargs)


def test_missing_engine_has_no_scientific_quantities(water, tmp_path):
    result = run_engine(water, spec(), ResourceLimits(), tmp_path / "attempt",
                        executable=str(tmp_path / "missing-xtb"))
    assert result.status == "unavailable"
    assert result.energy_hartree is None
    assert result.gradient_hartree_per_bohr is None
    assert result.converged is None
    assert result.metadata["execution_kind"] == "not-executed"
    assert result.method == "GFN2-xTB"


@pytest.mark.parametrize("update", [
    {"method": "GFN-FF"}, {"basis": "def2-SVP"}, {"solvent": "water"},
    {"constraints": {"frozen_atoms": [0]}}, {"profile_id": "unresolved-matrix"},
    {"dispersion": "D4"}, {"auxiliary_basis": "def2/J"},
])
def test_unsupported_method_cannot_silently_drop_options(water, tmp_path, update):
    data = spec().model_dump()
    data.update(update)
    result = run_engine(water, MethodSpec(**data), ResourceLimits(), tmp_path / "attempt")
    assert result.status == "unsupported"
    assert result.energy_hartree is None
    assert result.metadata["requested_method"] == data


def test_unavailable_orca_does_not_substitute(water, tmp_path):
    method = MethodSpec(engine="orca", method="HF-3c", profile_id="orca-mapping-v4.1")
    result = run_engine(water, method, ResourceLimits(), tmp_path / "attempt",
                        executable=str(tmp_path / "missing-orca"))
    assert result.status == "unavailable"
    assert result.method == "HF-3c" and result.engine == "orca"
    assert result.energy_hartree is None


def test_orca_composite_native_recipe_and_resolved_profile(water):
    method = MethodSpec(engine="orca", method="r2SCAN-3c", profile_id="orca-mapping-v4.1")
    text = _orca_input(water, method, ResourceLimits(threads=2, memory_mb=2048), "optimize")
    assert "! r2SCAN-3c TightSCF DEFGRID3 Opt Engrad" in text
    assert "mTZ2" not in text
    assert "InHess Lindh" in text and "Calc_Hess true" not in text
    assert "nprocs 2" in text and "%maxcore 768" in text
    assert "TolRMSG 3e-6" in text and "TolE 1e-7" in text


def test_orca_requires_all_five_convergence_gates():
    text = "\n".join(f"{name} 1.0E-8 1.0E-6 YES" for name in
                     ["Energy change", "RMS gradient", "MAX gradient", "RMS step", "MAX step"])
    assert len(_orca_convergence(text)) == 5 and all(_orca_convergence(text).values())
    assert not all(_orca_convergence(text.replace("MAX step 1.0E-8", "MAX step 1.0E-3")).values())


def test_orca_diagnostic_is_a_separate_serial_input():
    text = _orca_version_input(ResourceLimits(threads=8, memory_mb=4096))
    assert "HF STO-3G SP" in text and "%pal nprocs 1 end" in text
    assert "* xyz 0 1\nHe " in text
    assert "HF-3c" not in text


@pytest.mark.parametrize("cores,memory,reason", [(2, 1024, "CPU affinity"), (4, 64, "per-worker MaxCore")])
def test_orca_total_workers_cannot_bypass_resource_limits(water, tmp_path, monkeypatch, cores, memory, reason):
    monkeypatch.setattr("topos.engines.available_cpu_count", lambda: cores)
    method = MethodSpec(engine="orca", method="HF-3c", profile_id="orca-mapping-v4.1", engine_version="6.1.1")
    result = run_engine(water, method, ResourceLimits(threads=4, memory_mb=memory), tmp_path / "attempt")
    assert result.status == "unsupported" and reason in result.diagnostics["reason"]
    assert result.energy_hartree is None


@pytest.mark.parametrize("header,expected", [
    ("Program Version 6.1.1 - RELEASE -", "6.1.1"),
    ("Program Version 6.1.1-f.3", "6.1.1-f.3"),
    ("error while loading shared libraries: libmpi.so.40", None),
])
def test_orca_header_parser_does_not_erase_version_suffix(header, expected):
    assert _engine_version(header, "orca") == expected


@pytest.mark.parametrize("probe_status,header,expected", [
    ("failed", "error while loading shared libraries: libmpi.so.40", "unavailable"),
    ("completed", "Program Version 6.0.1", "unsupported"),
    ("completed", "Program Version 6.1.1-f.3", "unsupported"),
])
def test_orca_probe_fixture_failure_blocks_main_job(water, tmp_path, monkeypatch, probe_status, header, expected):
    # Explicit subprocess-contract fixture: no ORCA calculation is performed,
    # and no fixture energy is ever accepted as a molecular scientific result.
    calls = []

    def probe_fixture(command, folder, resources, **kwargs):
        calls.append(command)
        stdout, stderr = folder / "version.stdout", folder / "version.stderr"
        content = header
        if probe_status == "completed":
            content += "\nSCF CONVERGED AFTER 1 CYCLES\nFINAL SINGLE POINT ENERGY 0.0\nORCA TERMINATED NORMALLY\n"
        stdout.write_text(content)
        stderr.write_text("")
        return ProcessResult(command, probe_status, 0 if probe_status == "completed" else 1,
                             0.01, 1.0, str(stdout), str(stderr), "contract fixture")

    monkeypatch.setattr("topos.engines.run_process", probe_fixture)
    method = MethodSpec(engine="orca", method="HF-3c", profile_id="orca-mapping-v4.1", engine_version="6.1.1")
    result = run_engine(water, method, ResourceLimits(), tmp_path / "attempt",
                        executable=sys.executable)
    assert result.status == expected
    assert len(calls) == 1 and calls[0][-1] == "version.inp"
    assert "--version" not in calls[0]
    assert result.energy_hartree is None and result.command == []
    assert result.method == "HF-3c" and result.metadata["execution_kind"] == "not-executed"
    assert result.metadata["version_probe"]["scientific_result_eligibility"] is False
    assert not (tmp_path / "attempt" / "job.inp").exists()
    assert any(Path(a.path).name == "version.inp" and a.role == "engine-input" for a in result.artifacts)


def test_xyz_roundtrip_retains_precision_and_state(water, tmp_path):
    data = water.model_dump()
    data["coordinates"][1][0] = 0.9584123456789012
    molecule = Molecule(**data)
    path = tmp_path / "geometry.xyz"
    write_xyz(molecule, path)
    roundtrip = read_xyz(path, molecule)
    assert np.max(np.abs(np.array(roundtrip.coordinates) - molecule.coordinates)) < 1e-15
    assert roundtrip.atom_ids == molecule.atom_ids
    path.write_text(path.read_text().replace("O ", "C "))
    with pytest.raises(EngineParseError, match="element identity"):
        read_xyz(path, molecule)


def test_zero_gradient_is_present_quantity_and_wrong_geometry_rejected(tmp_path):
    molecule = Molecule(symbols=["He"], coordinates=[[0, 0, 0]])
    path = tmp_path / "gradient"
    path.write_text("$grad\n cycle = 1 SCF energy = -1.0 |dE/dxyz| = 0.0\n"
                    "0 0 0 He\n0.0 0.0 0.0\n$end\n")
    energy, gradient = parse_xtb_gradient(path, molecule)
    assert energy == -1.0 and gradient == [[0.0, 0.0, 0.0]]
    data = molecule.model_dump()
    data["coordinates"] = [[1.0, 0, 0]]
    with pytest.raises(EngineParseError, match="different geometry"):
        parse_xtb_gradient(path, Molecule(**data))


def test_truncated_orca_gradient_is_not_zero(tmp_path, water):
    path = tmp_path / "job.engrad"
    path.write_text("# Number of atoms\n3\n# energy\n-5.0\n# incomplete gradient\n0.0\n")
    with pytest.raises(EngineParseError, match="incomplete"):
        parse_orca_engrad(path, water)


def test_runtime_bounds_threads_and_preserves_streams(tmp_path):
    code = "import os,sys; print(os.environ['OMP_NUM_THREADS']); print('raw error',file=sys.stderr)"
    result = run_process([sys.executable, "-c", code], tmp_path, ResourceLimits(threads=1))
    assert result.status == "completed"
    assert Path(result.stdout_path).read_text() == "1\n"
    assert Path(result.stderr_path).read_text() == "raw error\n"
    assert result.returncode == 0


def test_runtime_timeout_kills_owned_group(tmp_path):
    code = (
        "import subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "print(p.pid,flush=True); time.sleep(30)"
    )
    result = run_process([sys.executable, "-c", code], tmp_path,
                         ResourceLimits(budget_seconds=0.25))
    assert result.status == "timed-out" and result.elapsed_seconds < 3
    child_pid = int(Path(result.stdout_path).read_text().strip())
    proc = Path(f"/proc/{child_pid}/stat")
    assert not proc.exists() or proc.read_text().rsplit(")", 1)[1].split()[0] == "Z"


def test_runtime_cancellation_has_distinct_state(tmp_path):
    event = Event()
    timer = Timer(0.15, event.set)
    timer.start()
    try:
        result = run_process([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path,
                             ResourceLimits(budget_seconds=10), cancel_event=event)
    finally:
        timer.cancel()
    assert result.status == "cancelled" and result.elapsed_seconds < 3


def test_runtime_refuses_to_overwrite_logs(tmp_path):
    (tmp_path / "engine.stdout").write_text("prior scientific output")
    with pytest.raises(FileExistsError):
        run_process([sys.executable, "-c", "print('new')"], tmp_path, ResourceLimits())
    assert (tmp_path / "engine.stdout").read_text() == "prior scientific output"


def test_runtime_memory_limit_is_real(tmp_path):
    result = run_process([sys.executable, "-c", "x=bytearray(256*1024*1024)"], tmp_path,
                         ResourceLimits(memory_mb=64))
    assert result.status == "failed" and result.returncode != 0
    assert "MemoryError" in Path(result.stderr_path).read_text()


@pytest.mark.parametrize("profile", ["screening-v1", "xtb-tight-v1", "xtb-vtight-v1"])
def test_authentic_xtb_optimization(water, tmp_path, native_xtb, profile):
    result = run_engine(water, spec(profile_id=profile), ResourceLimits(budget_seconds=30),
                        tmp_path / profile, executable=native_xtb)
    assert result.status == "completed", result.diagnostics
    assert result.converged is True and result.engine_version == "6.7.1"
    assert result.energy_hartree is not None and result.energy_hartree < -5
    assert result.gradient_hartree_per_bohr is not None
    assert result.metadata["execution_kind"] == "real"
    assert len(result.artifacts) >= 6
    assert all(Path(a.path).stat().st_size == a.size_bytes for a in result.artifacts)
    assert result.molecule.atom_ids == water.atom_ids
    assert "no frequency Hessian" in result.metadata["stationary_point_classification"]


def test_authentic_xtb_gradient_matches_finite_difference(water, tmp_path, native_xtb):
    resources = ResourceLimits(budget_seconds=30)
    reference = run_engine(water, spec(), resources, tmp_path / "reference", "gradient",
                           executable=native_xtb)
    assert reference.status == "completed", reference.diagnostics
    step_angstrom = 1e-4
    energies = []
    for label, sign in [("minus", -1), ("plus", 1)]:
        data = water.model_dump()
        data["coordinates"][1][0] += sign * step_angstrom
        result = run_engine(Molecule(**data), spec(), resources, tmp_path / label, "energy",
                            executable=native_xtb)
        assert result.status == "completed", result.diagnostics
        energies.append(result.energy_hartree)
    bohr_angstrom = physical_constants["Bohr radius"][0] * 1e10
    finite_difference = (energies[1] - energies[0]) / (2 * step_angstrom) * bohr_angstrom
    assert finite_difference == pytest.approx(reference.gradient_hartree_per_bohr[1][0], abs=2e-6)


@pytest.mark.parametrize("charge,multiplicity", [(-1, 1), (0, 2)])
def test_authentic_xtb_charge_and_spin_propagate(tmp_path, native_xtb, charge, multiplicity):
    molecule = Molecule(symbols=["O", "H"], coordinates=[[0, 0, 0], [0.97, 0, 0]],
                        charge=charge, multiplicity=multiplicity)
    result = run_engine(molecule, spec(), ResourceLimits(budget_seconds=30), tmp_path / "oh",
                        "energy", executable=native_xtb)
    assert result.status == "completed", result.diagnostics
    assert result.command[result.command.index("--chrg") + 1] == str(charge)
    assert result.command[result.command.index("--uhf") + 1] == str(multiplicity - 1)
    raw_json = json.loads((tmp_path / "oh" / "xtbout.json").read_text())
    assert raw_json["number of unpaired electrons"] == multiplicity - 1
    assert result.molecule.charge == charge
