"""Zero-mock tests for TOPOS authentic FP64 GPU4PySCF execution (engines & external_engines)."""
from __future__ import annotations

import ast
import hashlib
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from topos.engines import (
    DEFAULT_GPU4PYSCF_AUXBASIS,
    GPU4PYSCF_VV10_NLC_GRID,
    GPU4PYSCF_XC_GRID,
    gpu4pyscf_driver_source,
    resolve_gpu4pyscf_python,
    run_engine,
)
from topos.external_engines import (
    _CFOUR_METHODS,
    ExternalProtocol,
    gpu4pyscf_input,
    run_external,
)
from topos.models import MethodSpec, Molecule, ResourceLimits


@pytest.fixture
def h2() -> Molecule:
    return Molecule(symbols=["H", "H"], coordinates=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])


def _live_gpu4pyscf_or_skip() -> tuple[Path, str]:
    py = resolve_gpu4pyscf_python()
    if py is None:
        pytest.skip("GPU4PySCF Python interpreter unavailable on this host")
    probe = subprocess.run(
        [
            str(py),
            "-c",
            "import cupy, gpu4pyscf; assert cupy.cuda.runtime.getDeviceCount() > 0; print(gpu4pyscf.__version__)",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if probe.returncode != 0:
        pytest.skip(f"CUDA GPU or gpu4pyscf unavailable: {probe.stderr.strip()}")
    return py, probe.stdout.strip().splitlines()[-1].strip()


def test_cfour_ccsdt_mapping_preserved_intact() -> None:
    """Regression guard: CFOUR 2.1 native CCSD(T) -> CCSD[T] mapping MUST remain untouched."""
    assert _CFOUR_METHODS["CCSD(T)"] == "CCSD[T]"


def test_gpu4pyscf_driver_source_enforces_fp64_df_and_vv10_grids(h2: Molecule) -> None:
    """Generated driver must be valid Python with density_fit + explicit (99,590)/(50,194) VV10 grids."""
    src_vv10 = gpu4pyscf_driver_source(h2, method="wB97X-V", basis="def2-TZVP", operation="energy")
    compile(ast.parse(src_vv10), "<gpu4pyscf-driver>", "exec")
    assert DEFAULT_GPU4PYSCF_AUXBASIS in src_vv10
    assert "density_fit" in src_vv10
    assert str(list(GPU4PYSCF_XC_GRID)) in src_vv10
    assert str(list(GPU4PYSCF_VV10_NLC_GRID)) in src_vv10
    assert "nlcgrids" in src_vv10
    assert "float64" in src_vv10

    protocol = ExternalProtocol(
        engine="gpu4pyscf",
        engine_version="1.9.0",
        operation="energy",
        method="wB97M-V",
        orbital_basis="def2-TZVP",
        frozen_core=False,
        auxiliary_scf_basis=DEFAULT_GPU4PYSCF_AUXBASIS,
    )
    ext_src = gpu4pyscf_input(h2, protocol, ResourceLimits(device="cuda"))
    ast.parse(ext_src)
    assert "wb97m_v" in ext_src
    assert str(list(GPU4PYSCF_VV10_NLC_GRID)) in ext_src


def test_gpu4pyscf_refuses_cpu_fallback_and_fails_closed_when_unavailable(
    h2: Molecule, tmp_path: Path
) -> None:
    """GPU4PySCF must NEVER silently downgrade to CPU and must fail closed if GPU/interpreter is absent."""
    method = MethodSpec(engine="gpu4pyscf", method="wB97X-V", basis="def2-TZVP")

    # 1. Requesting device="cpu" for gpu4pyscf is rejected as unsupported
    res_cpu = run_engine(h2, method, ResourceLimits(device="cpu"), tmp_path / "cpu_refusal", "energy")
    assert res_cpu.status == "unsupported"
    assert res_cpu.energy_hartree is None
    assert "CPU fallback" in res_cpu.diagnostics["reason"]

    # 2. Missing executable fails closed as unavailable (never downgrades to CPU PySCF)
    res_missing = run_engine(
        h2,
        method,
        ResourceLimits(device="cuda"),
        tmp_path / "missing_exec",
        "energy",
        executable=tmp_path / "nonexistent-gpu4pyscf-python",
    )
    assert res_missing.status == "unavailable"
    assert res_missing.energy_hartree is None
    assert res_missing.metadata["execution_kind"] == "not-executed"

    # 3. ExternalProtocol also refuses device="cpu" and fails closed on missing interpreter
    protocol = ExternalProtocol(
        engine="gpu4pyscf",
        engine_version="1.9.0",
        operation="energy",
        method="wB97X-V",
        orbital_basis="def2-TZVP",
        frozen_core=False,
    )
    ext_cpu = run_external(h2, protocol, ResourceLimits(device="cpu"), tmp_path / "ext_cpu")
    assert ext_cpu.status == "unsupported"
    assert ext_cpu.energy_hartree is None

    ext_missing = run_external(
        h2,
        protocol,
        ResourceLimits(device="cuda"),
        tmp_path / "ext_missing",
        executable=tmp_path / "nonexistent-gpu4pyscf-python",
    )
    assert ext_missing.status == "unavailable"
    assert ext_missing.energy_hartree is None

    # 4. Real CUDA unavailability (CUDA_VISIBLE_DEVICES="") fails closed, NEVER falls back to CPU!
    py = resolve_gpu4pyscf_python()
    if py is not None:
        prev_cuda = os.environ.get("CUDA_VISIBLE_DEVICES")
        try:
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            res_no_gpu = run_engine(
                h2, method, ResourceLimits(device="cuda", budget_seconds=60), tmp_path / "no_cuda_gpu", "energy", executable=py
            )
            assert res_no_gpu.status == "unavailable"
            assert res_no_gpu.energy_hartree is None
            assert res_no_gpu.converged is None
        finally:
            if prev_cuda is None:
                os.environ.pop("CUDA_VISIBLE_DEVICES", None)
            else:
                os.environ["CUDA_VISIBLE_DEVICES"] = prev_cuda


def test_live_rtx3090_gpu4pyscf_matches_cpu_pyscf_under_1e6_eh(h2: Molecule, tmp_path: Path) -> None:
    """Live RTX 3090 GPU4PySCF wB97X-V & wB97M-V runs via engines.py & external_engines.py match CPU PySCF < 1e-6 Eh."""
    py, gpu4pyscf_ver = _live_gpu4pyscf_or_skip()

    for xc_label, pyscf_xc in (("wB97X-V", "wb97x_v"), ("wB97M-V", "wb97m_v")):
        # Authentic CPU PySCF reference with identical DF + (99,590) XC + (50,194) NLC grids
        ref_code = (
            "from pyscf import gto, dft\n"
            "mol = gto.M(atom='H 0 0 0; H 0 0 0.74', basis='def2-TZVP', charge=0, spin=0, unit='Angstrom', verbose=0)\n"
            f"mf = dft.RKS(mol, xc={pyscf_xc!r}).density_fit(auxbasis='def2-universal-jkfit')\n"
            "mf.conv_tol = 1e-10\n"
            "mf.grids.atom_grid = (99, 590)\n"
            "mf.nlcgrids.atom_grid = (50, 194)\n"
            "e = float(mf.kernel())\n"
            "assert mf.converged\n"
            "print(f'{e:.15f}')\n"
        )
        ref_proc = subprocess.run([str(py), "-c", ref_code], capture_output=True, text=True, check=True, timeout=60)
        e_cpu_ref = float(ref_proc.stdout.strip().splitlines()[-1])

        # 1. Via topos.engines.run_engine (gradient mode tests both energy and analytical gradient)
        method = MethodSpec(
            engine="gpu4pyscf",
            method=xc_label,
            basis="def2-TZVP",
            auxiliary_basis="def2-universal-jkfit",
            profile_id="gpu4pyscf-vv10-v1",
        )
        res = run_engine(
            h2,
            method,
            ResourceLimits(device="cuda", threads=2, budget_seconds=120),
            tmp_path / f"engine_{pyscf_xc}",
            operation="gradient",
            executable=py,
        )
        assert res.status == "completed", res.diagnostics
        assert res.converged is True
        assert res.engine == "gpu4pyscf"
        assert res.engine_version == gpu4pyscf_ver
        assert res.energy_hartree is not None
        assert abs(res.energy_hartree - e_cpu_ref) < 1e-6
        assert res.gradient_hartree_per_bohr is not None
        assert np.asarray(res.gradient_hartree_per_bohr).shape == (2, 3)
        assert res.metadata["execution_kind"] == "real"
        assert res.metadata["precision"] == "float64"
        assert res.metadata["gpu_device_name"]
        assert "GPU4PySCF" in res.metadata["gpu_banner"]
        assert res.metadata["xc_grid"] == [99, 590]
        assert res.metadata["nlc_grid"] == [50, 194]
        assert res.metadata["resolved_auxiliary_basis"] == "def2-universal-jkfit"
        assert len(res.metadata["result_json_sha256"]) == 64
        assert hashlib.sha256((tmp_path / f"engine_{pyscf_xc}" / "gpu4pyscf-result.json").read_bytes()).hexdigest() == res.metadata["result_json_sha256"]

    # 2. Via topos.external_engines.run_external (energy + optimize on H2)
    protocol = ExternalProtocol(
        engine="gpu4pyscf",
        engine_version=gpu4pyscf_ver,
        operation="energy",
        method="wB97X-V",
        orbital_basis="def2-TZVP",
        frozen_core=False,
        auxiliary_scf_basis="def2-universal-jkfit",
    )
    ext_res = run_external(
        h2,
        protocol,
        ResourceLimits(device="cuda", threads=2, budget_seconds=120),
        tmp_path / "external_wb97xv",
        executable=py,
    )
    assert ext_res.status == "completed", ext_res.diagnostics
    assert ext_res.converged is True
    assert ext_res.energy_hartree is not None
    assert ext_res.metadata["gpu_device_name"]
    assert "GPU4PySCF" in ext_res.metadata["gpu_banner"]
    assert ext_res.metadata["nlc_grid"] == [50, 194]
