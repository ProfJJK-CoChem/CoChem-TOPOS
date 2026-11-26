"""Real, fail-closed local xTB and ORCA adapters for TOPOS 0.1.0.

These adapters never change the requested Hamiltonian. Raw inputs, version
probes, stdout/stderr, geometries and derivatives remain in the attempt folder.
Only xTB 6.7.1 has live execution evidence in the initial release profile;
ORCA 6.1.1 is a conditional adapter requiring a licensed installation.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable, Literal

import numpy as np
from pydantic import Field

from .models import Artifact, Contract, ExecutionStatus, MethodSpec, Molecule, ResourceLimits
from .runtime import ProcessResult, available_cpu_count, run_process
from .storage import digest_json

_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
XTB_PROFILES = {
    "screening-v1": "normal", "xtb-normal-v1": "normal",
    "xtb-tight-v1": "tight", "xtb-vtight-v1": "vtight",
    "xtb-extreme-v1": "extreme",
}
ORCA_METHODS = {"B3LYP": "B3LYP", "HF-3c": "HF-3c", "r2SCAN-3c": "r2SCAN-3c",
                "r²SCAN-3c": "r2SCAN-3c", "HF": "HF",
                "wB97X-V": "wB97X-V", "wB97M-V": "wB97M-V"}
ORCA_BASES = {"def2-SVP", "def2-TZVP", "def2-TZVPP", "def2-QZVPP", "jun-cc-pVTZ"}
ORCA_VERSION = "6.1.1"
DEFAULT_GPU4PYSCF_AUXBASIS = "def2-universal-jkfit"
GPU4PYSCF_XC_GRID: tuple[int, int] = (99, 590)
GPU4PYSCF_VV10_NLC_GRID: tuple[int, int] = (50, 194)
GPU4PYSCF_VV10_FUNCTIONALS = frozenset({"wb97x_v", "wb97m_v"})
GPU4PYSCF_METHODS: dict[str, str] = {
    "wb97x-v": "wb97x_v",
    "wb97x_v": "wb97x_v",
    "wb97m-v": "wb97m_v",
    "wb97m_v": "wb97m_v",
    "b3lyp": "b3lyp",
    "pbe0": "pbe0",
    "pbe": "pbe",
    "r2scan": "r2scan",
    "m06-2x": "m062x",
    "m062x": "m062x",
    "m06_2x": "m062x",
    "hf": "hf",
    "rhf": "hf",
    "uhf": "hf",
}
GPU4PYSCF_PROFILES = frozenset({
    "screening-v1",
    "gpu4pyscf-fp64-v1",
    "gpu4pyscf-vv10-v1",
    "orca-mapping-v4.1",
    "orca-mapping-v4.2",
})
_SAFE_BASIS_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+*()._/-]{0,79}\Z")


def _is_gpu_device(device: str) -> bool:
    """Return True for explicit CUDA/GPU device selectors ('cuda', 'gpu', 'cuda:<n>')."""
    return device in {"cuda", "gpu"} or re.fullmatch(r"cuda:\d+", device) is not None


def _gpu_device_index(device: str) -> int | None:
    match = re.fullmatch(r"cuda:(\d+)", device)
    return int(match.group(1)) if match else None


def _normalize_gpu4pyscf_method(method: str) -> str | None:
    return GPU4PYSCF_METHODS.get(method.strip().lower())


def resolve_gpu4pyscf_python(executable: str | Path | None = None) -> Path | None:
    """Resolve an authentic GPU4PySCF Python interpreter without falling back to CPU.

    Uses ``os.path.abspath`` rather than ``Path.resolve()`` so virtual-environment
    ``bin/python`` symlinks keep their ``pyvenv.cfg`` site-packages intact.
    """
    if executable is not None:
        candidate = Path(executable).expanduser()
        if candidate.is_file():
            return Path(os.path.abspath(candidate))
        found = shutil.which(str(executable))
        return Path(os.path.abspath(found)) if found else None

    for env_key in ("TOPOS_GPU4PYSCF_PYTHON", "COCHEM_GPU4PYSCF_PYTHON"):
        configured = os.environ.get(env_key, "").strip()
        if configured:
            candidate = Path(configured).expanduser()
            if candidate.is_file():
                return Path(os.path.abspath(candidate))
            found = shutil.which(configured)
            if found:
                return Path(os.path.abspath(found))
            return None

    wrapper = shutil.which("cochem-gpu4pyscf-python")
    if wrapper:
        return Path(os.path.abspath(wrapper))

    home = Path.home()
    for candidate in (
        home / "CoChem_Workstation_Direct" / "bin" / "cochem-gpu4pyscf-python",
        Path("/home/ansac/.venvs/gpu4pyscf/bin/python"),
        home / ".venvs" / "gpu4pyscf" / "bin" / "python",
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return Path(os.path.abspath(candidate))

    if importlib.util.find_spec("gpu4pyscf") is not None and importlib.util.find_spec("cupy") is not None:
        return Path(os.path.abspath(sys.executable))

    return None


def gpu4pyscf_driver_source(
    molecule: Molecule,
    *,
    method: str,
    basis: str,
    auxbasis: str = DEFAULT_GPU4PYSCF_AUXBASIS,
    operation: Literal["energy", "gradient", "optimize"] = "energy",
    conv_tol: float = 1e-10,
    max_cycle: int = 200,
    max_opt_iter: int = 200,
    grad_max_tol: float = 1e-5,
    grad_rms_tol: float = 3e-6,
    expected_version: str | None = None,
) -> str:
    """Generate a fixed FP64 GPU4PySCF driver script (caller data is JSON-serialized)."""
    xc = _normalize_gpu4pyscf_method(method)
    if xc is None:
        raise ValueError(f"Unsupported GPU4PySCF method: {method!r}")
    if not _SAFE_BASIS_RE.fullmatch(basis):
        raise ValueError(f"Invalid GPU4PySCF orbital basis name: {basis!r}")
    if not _SAFE_BASIS_RE.fullmatch(auxbasis):
        raise ValueError(f"Invalid GPU4PySCF auxiliary basis name: {auxbasis!r}")
    if operation not in {"energy", "gradient", "optimize"}:
        raise ValueError(f"Unsupported GPU4PySCF operation: {operation!r}")

    payload = {
        "symbols": list(molecule.symbols),
        "coordinates": [[float(v) for v in row] for row in molecule.coordinates],
        "charge": int(molecule.charge),
        "multiplicity": int(molecule.multiplicity),
        "method": method,
        "xc": xc,
        "basis": basis,
        "auxbasis": auxbasis,
        "operation": operation,
        "conv_tol": float(conv_tol),
        "max_cycle": int(max_cycle),
        "max_opt_iter": int(max_opt_iter),
        "grad_max_tol": float(grad_max_tol),
        "grad_rms_tol": float(grad_rms_tol),
        "xc_grid": list(GPU4PYSCF_XC_GRID),
        "nlc_grid": list(GPU4PYSCF_VV10_NLC_GRID) if xc in GPU4PYSCF_VV10_FUNCTIONALS else None,
        "expected_version": expected_version,
    }
    return (
        "import hashlib\n"
        "import json\n"
        "import math\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        f"CONFIG = json.loads({json.dumps(payload, allow_nan=False)!r})\n"
        "BOHR_ANGSTROM = 0.529177210903\n"
        "\n"
        "try:\n"
        "    import numpy as np\n"
        "    import cupy\n"
        "    import pyscf\n"
        "    import gpu4pyscf\n"
        "    from pyscf import gto\n"
        "    from gpu4pyscf import dft as gpu_dft\n"
        "    from gpu4pyscf import scf as gpu_scf\n"
        "except Exception as exc:\n"
        "    sys.stderr.write(f'GPU4PYSCF_UNAVAILABLE: {exc}\\n')\n"
        "    raise SystemExit(2)\n"
        "\n"
        "try:\n"
        "    dev_count = int(cupy.cuda.runtime.getDeviceCount())\n"
        "    if dev_count < 1:\n"
        "        raise RuntimeError('Zero CUDA devices visible')\n"
        "    dev_idx = int(cupy.cuda.runtime.getDevice())\n"
        "    props = cupy.cuda.runtime.getDeviceProperties(dev_idx)\n"
        "    raw_name = props['name']\n"
        "    gpu_name = raw_name.decode('utf-8', errors='replace') if isinstance(raw_name, bytes) else str(raw_name)\n"
        "    total_mem_mb = int(props['totalGlobalMem']) // (1024 * 1024)\n"
        "    cc_major = int(props['major'])\n"
        "    cc_minor = int(props['minor'])\n"
        "    cuda_rt = int(cupy.cuda.runtime.runtimeGetVersion())\n"
        "    cuda_ver = f'{cuda_rt // 1000}.{(cuda_rt % 1000) // 10}'\n"
        "except Exception as exc:\n"
        "    sys.stderr.write(f'CUDA_UNAVAILABLE: {exc}; CPU fallback is strictly disabled\\n')\n"
        "    raise SystemExit(3)\n"
        "\n"
        "if CONFIG['expected_version'] is not None and gpu4pyscf.__version__ != CONFIG['expected_version']:\n"
        "    sys.stderr.write(f\"GPU4PYSCF_VERSION_MISMATCH: expected {CONFIG['expected_version']}, found {gpu4pyscf.__version__}\\n\")\n"
        "    raise SystemExit(4)\n"
        "\n"
        "gpu_banner = (\n"
        "    f\"GPU4PySCF {gpu4pyscf.__version__} / PySCF {pyscf.__version__} / \"\n"
        "    f\"CuPy {cupy.__version__} / CUDA {cuda_ver} on {gpu_name} \"\n"
        "    f\"({total_mem_mb} MiB, CC {cc_major}.{cc_minor})\"\n"
        ")\n"
        "print(gpu_banner, flush=True)\n"
        "\n"
        "def build_mf(coords_angstrom):\n"
        "    atoms = [(sym, tuple(float(v) for v in xyz)) for sym, xyz in zip(CONFIG['symbols'], coords_angstrom, strict=True)]\n"
        "    mol = gto.M(\n"
        "        atom=atoms,\n"
        "        basis=CONFIG['basis'],\n"
        "        charge=CONFIG['charge'],\n"
        "        spin=CONFIG['multiplicity'] - 1,\n"
        "        unit='Angstrom',\n"
        "        verbose=4,\n"
        "    )\n"
        "    xc = CONFIG['xc']\n"
        "    if xc == 'hf':\n"
        "        mf = gpu_scf.RHF(mol) if CONFIG['multiplicity'] == 1 else gpu_scf.UHF(mol)\n"
        "    else:\n"
        "        mf = gpu_dft.RKS(mol, xc=xc) if CONFIG['multiplicity'] == 1 else gpu_dft.UKS(mol, xc=xc)\n"
        "    mf = mf.density_fit(auxbasis=CONFIG['auxbasis'])\n"
        "    mf.conv_tol = float(CONFIG['conv_tol'])\n"
        "    mf.max_cycle = int(CONFIG['max_cycle'])\n"
        "    if xc != 'hf':\n"
        "        mf.grids.atom_grid = tuple(CONFIG['xc_grid'])\n"
        "        if CONFIG['nlc_grid'] is not None:\n"
        "            mf.nlcgrids.atom_grid = tuple(CONFIG['nlc_grid'])\n"
        "    return mol, mf\n"
        "\n"
        "def eval_point(coords_angstrom, need_grad):\n"
        "    mol, mf = build_mf(coords_angstrom)\n"
        "    energy = float(np.float64(mf.kernel()))\n"
        "    if not mf.converged or not math.isfinite(energy):\n"
        "        raise RuntimeError(f'GPU4PySCF SCF failed to converge (energy={energy})')\n"
        "    grad = None\n"
        "    if need_grad:\n"
        "        raw_grad = mf.nuc_grad_method().kernel()\n"
        "        if hasattr(raw_grad, 'get'):\n"
        "            raw_grad = raw_grad.get()\n"
        "        grad = np.asarray(raw_grad, dtype=np.float64)\n"
        "        if grad.shape != (len(CONFIG['symbols']), 3) or not np.all(np.isfinite(grad)):\n"
        "            raise RuntimeError('GPU4PySCF analytical nuclear gradient is invalid or nonfinite')\n"
        "    dipole_debye = None\n"
        "    try:\n"
        "        dip = mf.dip_moment(unit='Debye', verbose=0)\n"
        "        if hasattr(dip, 'get'):\n"
        "            dip = dip.get()\n"
        "        dip_arr = np.asarray(dip, dtype=np.float64).ravel()\n"
        "        if dip_arr.shape == (3,) and np.all(np.isfinite(dip_arr)):\n"
        "            dipole_debye = dip_arr.tolist()\n"
        "    except Exception:\n"
        "        dipole_debye = None\n"
        "    return energy, grad, dipole_debye\n"
        "\n"
        "operation = CONFIG['operation']\n"
        "final_coords = np.asarray(CONFIG['coordinates'], dtype=np.float64)\n"
        "opt_info = None\n"
        "eval_counter = [0]\n"
        "\n"
        "if operation == 'optimize':\n"
        "    from scipy.optimize import minimize\n"
        "    cache = {}\n"
        "    def obj(x_bohr):\n"
        "        key = tuple(np.round(x_bohr, 14).tolist())\n"
        "        if key not in cache:\n"
        "            coords_ang = (x_bohr.reshape(-1, 3) * BOHR_ANGSTROM).tolist()\n"
        "            e_val, g_val, dip_val = eval_point(coords_ang, need_grad=True)\n"
        "            eval_counter[0] += 1\n"
        "            cache[key] = (e_val, g_val, dip_val, coords_ang)\n"
        "        e_val, g_val, _, _ = cache[key]\n"
        "        return e_val, g_val.ravel()\n"
        "    x0 = final_coords.ravel() / BOHR_ANGSTROM\n"
        "    opt = minimize(\n"
        "        obj, x0, jac=True, method='L-BFGS-B',\n"
        "        options={'maxiter': CONFIG['max_opt_iter'], 'maxls': 30, 'ftol': 1e-15,\n"
        "                 'gtol': min(CONFIG['grad_max_tol'], CONFIG['grad_rms_tol'])},\n"
        "    )\n"
        "    final_coords = np.asarray(opt.x, dtype=np.float64).reshape(-1, 3) * BOHR_ANGSTROM\n"
        "    energy, grad, dipole_debye = eval_point(final_coords.tolist(), need_grad=True)\n"
        "    eval_counter[0] += 1\n"
        "    max_g = float(np.max(np.abs(grad)))\n"
        "    rms_g = float(np.sqrt(np.mean(grad ** 2)))\n"
        "    converged = bool(max_g <= CONFIG['grad_max_tol'] and rms_g <= CONFIG['grad_rms_tol'])\n"
        "    opt_info = {\n"
        "        'driver': 'TOPOS/scipy-L-BFGS-B with authentic GPU4PySCF analytical nuclear gradients',\n"
        "        'iterations': int(opt.nit),\n"
        "        'evaluations': int(eval_counter[0]),\n"
        "        'max_gradient_hartree_per_bohr': max_g,\n"
        "        'rms_gradient_hartree_per_bohr': rms_g,\n"
        "        'message': str(opt.message),\n"
        "    }\n"
        "else:\n"
        "    energy, grad, dipole_debye = eval_point(final_coords.tolist(), need_grad=(operation == 'gradient'))\n"
        "    eval_counter[0] = 1\n"
        "    converged = True\n"
        "\n"
        "evaluations = eval_counter[0]\n"
        "\n"
        "py_path = Path(os.path.abspath(sys.executable))\n"
        "with py_path.open('rb') as py_fh:\n"
        "    py_sha = hashlib.file_digest(py_fh, 'sha256').hexdigest()\n"
        "\n"
        "result = {\n"
        "    'schema': 'topos-gpu4pyscf-result/1',\n"
        "    'precision': 'float64',\n"
        "    'pyscf_version': pyscf.__version__,\n"
        "    'gpu4pyscf_version': gpu4pyscf.__version__,\n"
        "    'cupy_version': cupy.__version__,\n"
        "    'cuda_runtime_version': cuda_ver,\n"
        "    'gpu_device_name': gpu_name,\n"
        "    'gpu_device_index': dev_idx,\n"
        "    'gpu_total_memory_mb': total_mem_mb,\n"
        "    'gpu_compute_capability': f'{cc_major}.{cc_minor}',\n"
        "    'gpu_banner': gpu_banner,\n"
        "    'python_executable': str(py_path),\n"
        "    'python_executable_sha256': py_sha,\n"
        "    'method': CONFIG['method'],\n"
        "    'xc': CONFIG['xc'],\n"
        "    'basis': CONFIG['basis'],\n"
        "    'auxbasis': CONFIG['auxbasis'],\n"
        "    'density_fitting': True,\n"
        "    'xc_grid': CONFIG['xc_grid'] if CONFIG['xc'] != 'hf' else None,\n"
        "    'nlc_grid': CONFIG['nlc_grid'],\n"
        "    'operation': operation,\n"
        "    'converged': converged,\n"
        "    'energy_hartree': float(energy),\n"
        "    'gradient_hartree_per_bohr': grad.tolist() if grad is not None else None,\n"
        "    'coordinates_angstrom': final_coords.tolist(),\n"
        "    'dipole_cartesian_debye': dipole_debye,\n"
        "    'evaluations': evaluations,\n"
        "    'optimization': opt_info,\n"
        "}\n"
        "Path('gpu4pyscf-result.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')\n"
    )


def _run_gpu_process(
    command: list[str],
    workdir: str | Path,
    resources: ResourceLimits,
    *,
    cancel_event: Event | None = None,
    log_prefix: str = "engine",
) -> ProcessResult:
    """Run an authentic CUDA GPU subprocess with wall-budget enforcement and intact CUDA VM space."""
    if not command or any(not isinstance(arg, str) or "\x00" in arg for arg in command):
        raise ValueError("command must contain non-NUL string arguments")
    if Path(log_prefix).name != log_prefix or not log_prefix:
        raise ValueError("log prefix must be a basename")

    folder = Path(workdir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    stdout_path = folder / f"{log_prefix}.stdout"
    stderr_path = folder / f"{log_prefix}.stderr"
    if stdout_path.exists() or stderr_path.exists():
        raise FileExistsError("raw logs already exist; use a new attempt directory")

    env = os.environ.copy()
    threads = str(max(1, int(resources.threads)))
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = threads
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    dev_idx = _gpu_device_index(resources.device)
    if dev_idx is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(dev_idx)

    start = time.monotonic()
    status, reason = "completed", None
    returncode: int | None = None

    popen_kwargs: dict[str, Any] = {
        "cwd": str(folder),
        "env": env,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        popen_kwargs["creationflags"] = 0x08000000

    with stdout_path.open("xb") as stdout_fh, stderr_path.open("xb") as stderr_fh:
        if cancel_event is not None and cancel_event.is_set():
            return ProcessResult(command, "cancelled", None, 0.0, 0.0,
                                 str(stdout_path), str(stderr_path), "cancelled before launch")
        try:
            proc = subprocess.Popen(command, stdout=stdout_fh, stderr=stderr_fh, **popen_kwargs)
        except OSError as exc:
            return ProcessResult(command, "failed", None, time.monotonic() - start, 0.0,
                                 str(stdout_path), str(stderr_path), f"launch failed: {exc}")
        try:
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    status, reason = "cancelled", "cancellation requested"
                elif time.monotonic() - start >= resources.budget_seconds:
                    status, reason = "timed-out", "attempt wall-clock budget exhausted"
                else:
                    time.sleep(0.02)
                    continue
                if os.name == "posix":
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    time.sleep(0.2)
                    if proc.poll() is None:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                else:
                    proc.terminate()
                    time.sleep(0.2)
                    if proc.poll() is None:
                        proc.kill()
                break
            returncode = proc.wait(timeout=5.0)
            if returncode != 0 and status == "completed":
                status, reason = "failed", f"GPU4PySCF process exited with code {returncode}"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5.0)

    return ProcessResult(command, status, returncode, time.monotonic() - start, 0.0,
                         str(stdout_path), str(stderr_path), reason)


def _parse_gpu4pyscf_output(raw: str, molecule: Molecule, operation: str) -> dict[str, Any]:
    """Validate and parse structured FP64 GPU4PySCF output JSON."""
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("schema") != "topos-gpu4pyscf-result/1":
        raise EngineParseError("GPU4PySCF result payload schema is missing or invalid")
    if data.get("precision") != "float64":
        raise EngineParseError("GPU4PySCF execution did not establish float64 precision")
    gpu_name = str(data.get("gpu_device_name") or "").strip()
    gpu_banner = str(data.get("gpu_banner") or "").strip()
    if not gpu_name or not gpu_banner:
        raise EngineParseError("GPU4PySCF result lacks real CUDA GPU device name or banner")
    if not re.fullmatch(r"[0-9a-f]{64}", str(data.get("python_executable_sha256", ""))):
        raise EngineParseError("GPU4PySCF result lacks valid interpreter SHA-256 provenance")
    energy = _number(str(data["energy_hartree"]))
    coords = data.get("coordinates_angstrom")
    if not isinstance(coords, list) or len(coords) != len(molecule.symbols) or any(len(r) != 3 for r in coords):
        raise EngineParseError("GPU4PySCF output coordinates are incomplete")
    coords_clean = [[_number(str(v)) for v in row] for row in coords]
    gradient = None
    if operation in {"gradient", "optimize"}:
        raw_grad = data.get("gradient_hartree_per_bohr")
        if not isinstance(raw_grad, list) or len(raw_grad) != len(molecule.symbols) or any(len(r) != 3 for r in raw_grad):
            raise EngineParseError("GPU4PySCF analytical nuclear gradient is missing or malformed")
        gradient = [[_number(str(v)) for v in row] for row in raw_grad]
    data["energy_hartree"] = energy
    data["coordinates_angstrom"] = coords_clean
    data["gradient_hartree_per_bohr"] = gradient
    return data


class EngineResult(Contract):
    status: ExecutionStatus
    engine: str
    method: str
    operation: str
    engine_version: str | None = None
    energy_hartree: float | None = None
    gradient_hartree_per_bohr: list[list[float]] | None = None
    molecule: Molecule | None = None
    converged: bool | None = None
    command: list[str] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    elapsed_seconds: float = 0.0
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class EngineParseError(ValueError):
    """Engine artifacts do not establish the requested quantity/state."""


def _number(value: str) -> float:
    result = float(value.replace("D", "E").replace("d", "e"))
    if not math.isfinite(result):
        raise EngineParseError("nonfinite engine quantity")
    return result



def parse_cartesian_dipole(text: str, engine: str) -> dict[str, Any] | None:
    """Parse signed final Cartesian components, with explicit source units.

    xTB 6.7.1 prints CAMM components in atomic units but their norm in Debye.
    This is NOT its distinct AO-density dipole in xtbout.json. ORCA likewise
    prints Total Dipole Moment components in atomic units. The printed norm
    cross-check includes the known component rounding. An absent property is
    unavailable; a malformed advertised property is a parse error.
    """
    from scipy import constants

    atomic_unit_debye = (constants.physical_constants["atomic unit of electric dipole mom."][0]
                         * constants.c * 1e21)
    printed_atomic_unit_debye = atomic_unit_debye
    if engine == "xtb":
        marker = "molecular dipole:"
        if marker not in text:
            return None
        block = text.rsplit(marker, 1)[1].split("molecular quadrupole", 1)[0]
        if not re.search(r"x\s+y\s+z\s+tot \(Debye\)", block):
            raise EngineParseError("xTB molecular dipole units/header are not recognized")
        row = re.search(r"(?m)^\s*full:\s*(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s*$", block)
        if row is None:
            raise EngineParseError("xTB full molecular dipole vector is incomplete")
        vector = [_number(row.group(i)) for i in range(1, 4)]
        magnitude_debye = _number(row.group(4))
        component_rounding = 0.0005  # Fortran 3f12.3, verified in the source below.
        magnitude_rounding = 0.0005
        definition = "GFN2-xTB cumulative atomic multipole molecular dipole (CAMM full)"
        source = "https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/aespot.f90#L701"
    elif engine == "orca":
        markers = list(re.finditer(r"(?m)^\s*DIPOLE MOMENT\s*$", text))
        if not markers:
            return None
        block = text[markers[-1].end():]
        row = re.search(r"(?m)^\s*Total Dipole Moment\s*:\s*(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s*$", block)
        norm_au = re.search(r"Magnitude\s*\(a\.u\.\)\s*:\s*(" + _FLOAT + r")", block)
        norm_debye = re.search(r"Magnitude\s*\(Debye\)\s*:\s*(" + _FLOAT + r")", block)
        if row is None or norm_au is None or norm_debye is None:
            raise EngineParseError("ORCA molecular dipole vector and explicit a.u./Debye magnitudes are required")
        vector = [_number(row.group(i)) for i in range(1, 4)]
        magnitude_debye = _number(norm_debye.group(1))
        def rounding(value: str) -> float:
            mantissa, _, exponent = value.lower().replace("d", "e").partition("e")
            decimals = len(mantissa.partition(".")[2])
            return .5 * 10.0 ** (int(exponent or "0") - decimals)

        component_errors = np.asarray([rounding(row.group(i)) for i in range(1, 4)])
        component_rounding = float(np.max(component_errors))
        magnitude_rounding = rounding(norm_debye.group(1))
        norm_atomic_units = _number(norm_au.group(1))
        norm_rounding = rounding(norm_au.group(1))
        if (norm_atomic_units < 0 or abs(float(np.linalg.norm(vector)) - norm_atomic_units)
                > float(np.linalg.norm(component_errors)) + norm_rounding):
            raise EngineParseError("ORCA Cartesian dipole components and atomic-unit magnitude disagree")
        # ORCA 6.1.1's retained native output uses its 2.541798 Debye/e a0
        # convention, not current CODATA. Validate the engine's printed units
        # separately; scientific Cartesian outputs below use current CODATA.
        printed_atomic_unit_debye = 2.541798
        if (abs(norm_atomic_units * printed_atomic_unit_debye - magnitude_debye)
                > norm_rounding * printed_atomic_unit_debye + magnitude_rounding):
            raise EngineParseError("ORCA dipole magnitudes disagree between atomic units and Debye")
        definition = "ORCA total electronic plus nuclear Cartesian dipole"
        source = "ORCA final DIPOLE MOMENT block; explicit Magnitude (a.u.) and Magnitude (Debye) cross-check"
    else:
        raise ValueError("dipole parser supports xtb or orca only")
    vector_debye = np.asarray(vector) * atomic_unit_debye
    tolerance = np.sqrt(3) * component_rounding * printed_atomic_unit_debye + magnitude_rounding
    native_vector_debye = np.asarray(vector) * printed_atomic_unit_debye
    if magnitude_debye < 0 or abs(float(np.linalg.norm(native_vector_debye)) - magnitude_debye) > tolerance:
        raise EngineParseError(f"{engine} Cartesian dipole components and printed magnitude disagree")
    return {"cartesian_debye": vector_debye.tolist(), "cartesian_atomic_units": vector,
            "printed_magnitude_debye": magnitude_debye, "units": "debye",
            "definition": definition, "parser": f"topos.engines/{engine}-dipole-v1",
            "source": source, "atomic_unit_debye": atomic_unit_debye,
            "cartesian_conversion_convention": "current scipy CODATA atomic unit of electric dipole",
            "printed_atomic_unit_debye": printed_atomic_unit_debye,
            "printed_conversion_convention": "ORCA 6.1.1 native 2.541798 Debye/e a0" if engine == "orca" else "current CODATA",
            "engine_native_cartesian_debye": native_vector_debye.tolist(),
            "printed_component_rounding_bound_debye": component_rounding * atomic_unit_debye,
            "selection": "last advertised molecular dipole block, without fallback to earlier incomplete results",
            "origin": "engine input/output Cartesian origin; charged-molecule origin dependence retained"}


def write_xyz(molecule: Molecule, path: str | Path) -> None:
    lines = [str(len(molecule.symbols)), "TOPOS input; angstrom; atom order preserved"]
    lines.extend(f"{s} {r[0]:.16g} {r[1]:.16g} {r[2]:.16g}"
                 for s, r in zip(molecule.symbols, molecule.coordinates, strict=True))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_xyz(path: str | Path, reference: Molecule) -> Molecule:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    n = len(reference.symbols)
    if len(lines) < 2 or lines[0].strip() != str(n):
        raise EngineParseError("output geometry has incompatible atom count")
    rows = [line.split() for line in lines[2:] if line.strip()]
    if len(rows) != n or any(len(row) != 4 for row in rows):
        raise EngineParseError("output geometry is incomplete or contains trailing structures")
    if [row[0] for row in rows] != reference.symbols:
        raise EngineParseError("output geometry changed element identity or atom order")
    data = reference.model_dump()
    data["coordinates"] = [[_number(v) for v in row[1:]] for row in rows]
    return Molecule.model_validate(data)


def parse_xtb_gradient(path: str | Path, molecule: Molecule) -> tuple[float, list[list[float]]]:
    """Read last Turbomole $grad cycle (Eh, Eh/bohr; coordinates in bohr)."""
    from scipy.constants import physical_constants

    text = Path(path).read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^\s*cycle\s*=", text)
    if len(blocks) < 2 or "$grad" not in blocks[0] or "$end" not in text:
        raise EngineParseError("missing complete xTB gradient cycle")
    lines = blocks[-1].splitlines()
    energy_match = re.search(r"SCF energy\s*=\s*(" + _FLOAT + ")", lines[0])
    if not energy_match:
        raise EngineParseError("missing gradient energy")
    n = len(molecule.symbols)
    rows = [line.split() for line in lines[1:] if line.strip() and not line.lstrip().startswith("$")]
    if len(rows) != 2 * n:
        raise EngineParseError("incomplete xTB gradient/coordinate array")
    if any(len(row) != 4 for row in rows[:n]) or any(len(row) != 3 for row in rows[n:]):
        raise EngineParseError("invalid xTB gradient record shape")
    if [row[3] for row in rows[:n]] != molecule.symbols:
        raise EngineParseError("gradient element mapping mismatch")
    bohr_angstrom = physical_constants["Bohr radius"][0] * 1e10
    coords = np.array([[_number(v) for v in row[:3]] for row in rows[:n]]) * bohr_angstrom
    if not np.allclose(coords, molecule.coordinates, atol=2e-7, rtol=0):
        raise EngineParseError("gradient belongs to a different geometry")
    return _number(energy_match.group(1)), [[_number(v) for v in row] for row in rows[n:]]


def parse_orca_engrad(path: str | Path, molecule: Molecule) -> tuple[float, list[list[float]]]:
    """Read ORCA .engrad including geometry/state array validation."""
    from scipy.constants import physical_constants

    from .chemistry import atomic_number

    rows = [line.split() for line in Path(path).read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    n = len(molecule.symbols)
    if not rows or rows[0] != [str(n)] or len(rows) != 2 + 4 * n:
        raise EngineParseError("incomplete ORCA engrad")
    energy = _number(rows[1][0])
    values = [_number(row[0]) for row in rows[2:2 + 3 * n] if len(row) == 1]
    if len(values) != 3 * n:
        raise EngineParseError("invalid ORCA gradient shape")
    coords = rows[2 + 3 * n:]
    if any(len(row) != 4 for row in coords):
        raise EngineParseError("invalid ORCA coordinate shape")
    if [int(row[0]) for row in coords] != [atomic_number(s) for s in molecule.symbols]:
        raise EngineParseError("ORCA gradient element mapping mismatch")
    bohr_angstrom = physical_constants["Bohr radius"][0] * 1e10
    xyz = np.array([[_number(v) for v in row[1:]] for row in coords]) * bohr_angstrom
    if not np.allclose(xyz, molecule.coordinates, atol=2e-6, rtol=0):
        raise EngineParseError("ORCA derivative belongs to a different geometry")
    return energy, np.array(values).reshape(n, 3).tolist()


def artifact_inventory(folder: Path) -> list[Artifact]:
    result = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise EngineParseError("engine artifact symlinks are not accepted")
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        result.append(Artifact(path=str(path.resolve()), sha256=digest.hexdigest(),
                               size_bytes=path.stat().st_size,
                               role="engine-input" if path.name in {"input.xyz", "job.inp", "version.inp"} else "raw-output"))
    return result


def _method_problem(method: MethodSpec, resources: ResourceLimits, operation: str,
                    *, check_cpu_affinity: bool = True) -> str | None:
    if operation not in {"energy", "gradient", "optimize"}:
        return f"operation {operation!r} has no validated adapter"
    if method.engine == "gpu4pyscf":
        if not _is_gpu_device(resources.device):
            return "GPU4PySCF adapter requires an explicit CUDA/GPU device; CPU fallback is strictly disabled"
        if check_cpu_affinity and resources.threads > available_cpu_count():
            return "requested total worker count exceeds available CPU affinity"
        if method.constraints:
            return "native constraints not supported; use explicit TOPOS constrained-gradient protocol"
        if method.solvent:
            return "solvation requires a version-specific model/solvent profile; no implicit model chosen"
        xc = _normalize_gpu4pyscf_method(method.method)
        if xc is None:
            return f"GPU4PySCF method {method.method!r} is outside the validated FP64 Hamiltonian registry"
        if method.dispersion:
            return "explicit empirical dispersion overrides are not enabled for GPU4PySCF; VV10 is built into wB97X-V/wB97M-V"
        if not method.basis or not _SAFE_BASIS_RE.fullmatch(method.basis):
            return "explicit supported orbital basis required for GPU4PySCF method"
        if method.auxiliary_basis is not None and not _SAFE_BASIS_RE.fullmatch(method.auxiliary_basis):
            return "invalid explicit GPU4PySCF auxiliary density-fitting basis"
        if method.profile_id not in GPU4PYSCF_PROFILES:
            return "unresolved GPU4PySCF numerical profile"
        return None
    if resources.device != "cpu":
        return "native xTB/ORCA adapter supports CPU; requested GPU cannot be silently substituted"
    if check_cpu_affinity and resources.threads > available_cpu_count():
        return "requested total worker count exceeds available CPU affinity"
    if method.constraints:
        return "native constraints not supported; use explicit TOPOS constrained-gradient protocol"
    if method.dispersion and not (method.engine == "orca" and method.method == "B3LYP" and method.dispersion == "D4"):
        return "custom dispersion has not been validated for this adapter"
    if method.auxiliary_basis is not None and not (
            method.engine == "orca" and method.method in {"B3LYP", "wB97X-V", "wB97M-V"}
            and method.auxiliary_basis == "def2/J"):
        return "explicit auxiliary basis is supported only as def2/J for the ORCA hybrid RIJCOSX recipes"
    if method.solvent:
        return "solvation requires a version-specific model/solvent profile; no implicit model chosen"
    if method.engine == "xtb":
        if method.method != "GFN2-xTB":
            return "this adapter currently validates GFN2-xTB only; no potential substitution"
        if method.basis is not None:
            return "GFN2-xTB has no selectable orbital basis"
        if method.profile_id not in XTB_PROFILES:
            return "unresolved xTB convergence profile"
    elif method.engine == "orca":
        if resources.memory_mb * 0.75 < 16 * resources.threads:
            return "ORCA memory budget cannot supply the minimum per-worker MaxCore plus driver reserve"
        if method.method not in ORCA_METHODS:
            return "ORCA method is outside the validated input grammar"
        if method.method in {"HF-3c", "r2SCAN-3c", "r²SCAN-3c"}:
            if method.basis is not None:
                return "3c composite uses its native basis; separate basis override is invalid"
        elif method.basis not in ORCA_BASES:
            return "explicit supported orbital basis required for noncomposite ORCA method"
        from .orca_numerical_profiles import SUPPORTED_PROFILES
        if method.profile_id not in SUPPORTED_PROFILES:
            return "ORCA requires an explicit supported convergence profile; conflicting profiles not guessed"
    else:
        return f"engine {method.engine!r} has no validated local adapter"
    return None


def _orca_input(molecule: Molecule, method: MethodSpec, resources: ResourceLimits, operation: str,
                *, ghost_atom_indices: list[int] | None = None,
                ghost_electronic_state: tuple[int, int] | None = None,
                basis_files: dict[str, str] | None = None) -> str:
    strict_vpt2 = method.profile_id == "orca-vpt2-reference-v1"
    keywords = [ORCA_METHODS[method.method], "ExtremeSCF" if strict_vpt2 else "TightSCF", "DEFGRID3"]
    if method.dispersion == "D4":
        keywords.append("D4")
    if method.basis and not basis_files:
        from .orca_basis_names import resolve_orca_orbital_basis, validate_basis_elements

        resolution = resolve_orca_orbital_basis(molecule, method.basis)
        validate_basis_elements(resolution["native_basis"], "orbital", molecule.symbols)
        keywords.append(resolution["native_basis"])
    if method.method in {"B3LYP", "wB97X-V", "wB97M-V"}:
        keywords.append("RIJCOSX")
        if not basis_files or "auxiliary" not in basis_files:
            keywords.append("def2/J")
    if operation == "optimize":
        # Run-type keywords are mutually exclusive: Engrad after Opt selects
        # a single gradient in ORCA 6.1.1 and does not optimize the geometry.
        keywords.append("Opt")
    elif operation == "gradient":
        keywords.append("Engrad")
    # ORCA MaxCore is per worker; reserve 25% for unaccounted structures/driver.
    lines = ["! " + " ".join(keywords), f"%pal nprocs {resources.threads} end",
             f"%maxcore {max(16, int(resources.memory_mb * 0.75 / resources.threads))}"]
    if strict_vpt2:
        lines.extend(["%method", "  Z_Tol 1e-14", "end"])
    if operation == "optimize":
        # ORCA's default step-overachievement shortcut can stop while a
        # required gradient criterion still fails. The documented optimizer
        # policy used by GOAT enforces the requested criteria without changing
        # their values; five numerical gates and the independent gradient remain.
        lines.extend(["%geom", "  EnforceStrictConvergence true", "  MaxIter 200", "  TolE 1e-10" if strict_vpt2 else "  TolE 1e-7",
                      "  TolMaxG 1e-7" if strict_vpt2 else "  TolMaxG 1e-5",
                      "  TolRMSG 3e-8" if strict_vpt2 else "  TolRMSG 3e-6",
                      "  TolRMSD 5e-7" if strict_vpt2 else "  TolRMSD 5e-5",
                      "  TolMaxD 1e-6" if strict_vpt2 else "  TolMaxD 1e-4",
                      "  InHess Lindh", "end"])
    if basis_files:
        lines.append("%basis")
        for kind, keyword in (("orbital", "GTOName"), ("auxiliary", "GTOAuxJName")):
            if kind in basis_files:
                if basis_files[kind] not in {"orbital.bas", "auxiliary.bas"}:
                    raise ValueError("External ORCA basis filenames must be the fixed staged names")
                lines.append(f'  {keyword} "{basis_files[kind]}"')
        lines.append("end")
    from .orca_numerical_profiles import MAPPING_V42, SCF_BLOCK

    if method.profile_id == MAPPING_V42:
        lines.extend(SCF_BLOCK.rstrip().splitlines())
    charge, multiplicity = ghost_electronic_state or (molecule.charge, molecule.multiplicity)
    lines.append(f"* xyz {charge} {multiplicity}")
    ghosts = set(ghost_atom_indices or [])
    lines.extend(f"{s}{':' if i in ghosts else ''} {r[0]:.16g} {r[1]:.16g} {r[2]:.16g}"
                 for i, (s, r) in enumerate(zip(molecule.symbols, molecule.coordinates, strict=True)))
    lines.extend(["*", ""])
    return "\n".join(lines)


def _orca_version_input(resources: ResourceLimits) -> str:
    """A separate genuine serial calculation establishes ORCA loader/version health.

    ORCA is invoked with an input file, not an assumed ``--version`` option.
    This He/HF/STO-3G diagnostic is never returned as the requested method's
    molecular result and does not test parallel MPI or the production protocol.
    """
    maxcore = max(16, min(64, resources.memory_mb // 2))
    return ("! HF STO-3G SP\n%pal nprocs 1 end\n"
            f"%maxcore {maxcore}\n* xyz 0 1\nHe 0.0 0.0 0.0\n*\n")


def _engine_version(text: str, engine: str) -> str | None:
    pattern = (r"xtb version\s+(\d+\.\d+\.\d+)" if engine == "xtb"
               else r"(?:Program Version|ORCA VERSION)\s+(\S+)")
    match = re.search(pattern, text, re.I)
    return match.group(1) if match else None


def _orca_convergence(text: str) -> dict[str, bool]:
    fields = {"energy_change": "Energy change", "rms_gradient": "RMS gradient",
              "max_gradient": "MAX gradient", "rms_step": "RMS step", "max_step": "MAX step"}
    result = {}
    for key, label in fields.items():
        matches = re.findall(re.escape(label) + r"\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(YES|NO)", text, re.I)
        if matches:
            value, threshold, yes = matches[-1]
            result[key] = yes.upper() == "YES" and abs(_number(value)) <= _number(threshold)
    return result


ORCA_OPTIMIZATION_MAX_RESTARTS = 3


def _orca_refinement_needed(result: EngineResult) -> bool:
    """Only a genuine early native stop can request another optimization."""
    criteria = result.diagnostics.get("convergence", {})
    return (result.engine == "orca" and result.operation == "optimize"
            and result.status == "partial" and result.converged is False
            and result.metadata.get("execution_kind") == "real" and result.molecule is not None
            and result.diagnostics.get("native_optimizer_reported_converged") is True
            and len(criteria) == 5 and all(isinstance(value, bool) for value in criteria.values())
            and (not all(criteria.values())
                 or result.diagnostics.get("independent_stationarity", {}).get("passed") is False))


def run_engine(
    molecule: Molecule, method: MethodSpec, resources: ResourceLimits, workdir: str | Path,
    operation: Literal["energy", "gradient", "optimize"] = "optimize",
    cancel_event: Event | None = None, executable: str | Path | None = None, *,
    process_runner: Callable[..., Any] | None = None,
    ghost_atom_indices: list[int] | None = None, ghost_electronic_state: tuple[int, int] | None = None,
    orbital_basis_file: str | Path | None = None, auxiliary_basis_file: str | Path | None = None,
) -> EngineResult:
    """Run genuine stages within one budget, refining ORCA's early-stop shortcut.

    Native ORCA may announce geometry convergence before all five numerical
    conditions pass. Keep those thresholds and the independent final gradient;
    restart at most three times from its actual returned geometry. Every stage
    retains its original files, status and input. No failed calculation is
    promoted to successful merely because continuation was attempted.
    """
    from .storage import atomic_json, file_digest

    started = time.monotonic()
    folder = Path(workdir).resolve()
    arguments = dict(operation=operation, cancel_event=cancel_event, executable=executable,
                     process_runner=process_runner, ghost_atom_indices=ghost_atom_indices,
                     ghost_electronic_state=ghost_electronic_state,
                     orbital_basis_file=orbital_basis_file, auxiliary_basis_file=auxiliary_basis_file)
    current = _run_engine_once(molecule, method, resources, folder, **arguments)
    if not _orca_refinement_needed(current):
        return current
    stages = []
    stage_input, stage_directory, stage_resources = molecule, ".", resources
    initial_identity = [current.engine_version, current.metadata.get("executable_sha256")]
    for stage_index in range(ORCA_OPTIMIZATION_MAX_RESTARTS + 1):
        receipt = folder / f"optimization-stage-{stage_index}.json"
        try:
            atomic_json(receipt, current.model_dump(mode="json"))
            receipt_identity = {"path": receipt.relative_to(folder).as_posix(), "sha256": file_digest(receipt),
                                "size_bytes": receipt.stat().st_size}
        except OSError as exc:
            current.status, current.converged = "failed", False
            current.diagnostics["reason"] = f"ORCA refinement stage receipt could not be retained: {exc}"
            break
        stage_gradient = (dict(current.metadata["final_gradient_verification"])
                          if current.metadata.get("final_gradient_verification") else None)
        if stage_gradient is not None and stage_directory != ".":
            stage_gradient["directory"] = stage_directory + "/final-gradient"
        stages.append({"stage_directory": stage_directory, "input_molecule": stage_input.model_dump(mode="json"),
            "output_molecule": current.molecule.model_dump(mode="json") if current.molecule else None,
            "status": current.status, "converged": current.converged, "command": current.command,
            "method": method.model_dump(mode="json"), "resources": stage_resources.model_dump(mode="json"),
            "engine_version": current.engine_version, "executable_sha256": current.metadata.get("executable_sha256"),
            "convergence": current.diagnostics.get("convergence", {}),
            "energy_change_evidence": current.diagnostics.get("energy_change_evidence"),
            "native_optimizer_reported_converged": current.diagnostics.get("native_optimizer_reported_converged"),
            "independent_stationarity": current.diagnostics.get("independent_stationarity"),
            "process": current.diagnostics.get("process"),
            "final_gradient_verification": stage_gradient,
            "receipt": receipt_identity})
        if [current.engine_version, current.metadata.get("executable_sha256")] != initial_identity:
            current.status, current.converged = "failed", False
            current.diagnostics["reason"] = "ORCA optimization refinement changed native version or executable"
            break
        if not _orca_refinement_needed(current) or stage_index == ORCA_OPTIMIZATION_MAX_RESTARTS:
            break
        remaining = resources.budget_seconds - (time.monotonic() - started)
        cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled or remaining <= 0:
            current.status, current.converged = "cancelled" if cancelled else "timed-out", False
            current.diagnostics["reason"] = "Original optimization budget or cancellation stopped native refinement"
            break
        stage_input = current.molecule
        stage_directory = f"optimization-refinement-{stage_index+1}"
        stage_resources = resources.model_copy(update={"budget_seconds": remaining})
        current = _run_engine_once(stage_input, method, stage_resources, folder / stage_directory, **arguments)
    current.metadata["optimization_refinement"] = {
        "schema": "topos-orca-optimization-refinement/1", "maximum_restarts": ORCA_OPTIMIZATION_MAX_RESTARTS,
        "attempt_root": str(folder), "accepted_stage_directory": stage_directory if current.status == "completed" else None,
        "final_stage_directory": stage_directory, "initial_molecule": molecule.model_dump(mode="json"),
        "original_resources": resources.model_dump(mode="json"), "stages": stages,
        "policy": "bounded same-protocol native continuation; unchanged five criteria plus independent final gradient",
        "budget_scope": "one original attempt wall budget including all native stages"}
    if stage_directory != ".":
        if current.metadata.get("final_gradient_verification"):
            current.metadata["final_gradient_verification"]["directory"] = stage_directory + "/final-gradient"
        if current.metadata.get("dipole_provenance"):
            current.metadata["dipole_provenance"]["raw_output"] = stage_directory + "/" + current.metadata["dipole_provenance"]["raw_output"]
    try:
        current.artifacts = artifact_inventory(folder)
    except (OSError, EngineParseError) as exc:
        current.status, current.converged = "failed", False
        current.metadata["optimization_refinement"]["accepted_stage_directory"] = None
        current.diagnostics["artifact_error"] = str(exc)
    current.elapsed_seconds = time.monotonic() - started
    if (cancel_event is not None and cancel_event.is_set()) or current.elapsed_seconds >= resources.budget_seconds:
        current.status, current.converged = "cancelled" if cancel_event is not None and cancel_event.is_set() else "timed-out", False
        current.metadata["optimization_refinement"]["accepted_stage_directory"] = None
        current.diagnostics["reason"] = "Optimization refinement ended after the original budget or cancellation"
    return current


def _run_engine_once(
    molecule: Molecule,
    method: MethodSpec,
    resources: ResourceLimits,
    workdir: str | Path,
    operation: Literal["energy", "gradient", "optimize"] = "optimize",
    cancel_event: Event | None = None,
    executable: str | Path | None = None,
    *,
    process_runner: Callable[..., Any] | None = None,
    ghost_atom_indices: list[int] | None = None,
    ghost_electronic_state: tuple[int, int] | None = None,
    orbital_basis_file: str | Path | None = None,
    auxiliary_basis_file: str | Path | None = None,
) -> EngineResult:
    """Run an isolated real attempt; failures keep artifacts and optional quantities null."""
    start = time.monotonic()
    execute_process = process_runner or run_process
    result = EngineResult(status="unsupported", engine=method.engine, method=method.method,
                          operation=operation, metadata={"execution_kind": "not-executed",
                          "profile_id": method.profile_id, "requested_method": method.model_dump(),
                          "resources": resources.model_dump(), "precision": "float64"})
    if method.engine == "orca":
        from .orca_numerical_profiles import numerical_profile_receipt

        profile_receipt = numerical_profile_receipt(method.profile_id)
        if profile_receipt is not None:
            result.metadata["numerical_profile"] = profile_receipt
    problem = _method_problem(method, resources, operation)
    if problem:
        result.diagnostics["reason"] = problem
        return result
    physical_molecule = molecule
    ghosts = list(ghost_atom_indices or [])
    if ghosts or ghost_electronic_state is not None:
        if method.engine != "orca" or operation != "energy" or not ghosts or ghost_electronic_state is None:
            result.diagnostics["reason"] = "Ghost basis centers require explicit ORCA energy-only fragment state"
            return result
        if (len(set(ghosts)) != len(ghosts) or len(ghosts) >= len(molecule.symbols)
                or any(not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= len(molecule.symbols) for i in ghosts)):
            result.diagnostics["reason"] = "Ghost indices must be distinct valid atom indices leaving a physical fragment"
            return result
        real = [i for i in range(len(molecule.symbols)) if i not in ghosts]
        try:
            charge, multiplicity = ghost_electronic_state
            if any(not isinstance(value, int) or isinstance(value, bool) for value in (charge, multiplicity)):
                raise ValueError("Fragment charge and multiplicity must be integers")
            physical_molecule = Molecule(
                symbols=[molecule.symbols[i] for i in real], coordinates=[molecule.coordinates[i] for i in real],
                atom_ids=[molecule.atom_ids[i] for i in real], isotopes=[molecule.isotopes[i] for i in real],
                charge=charge, multiplicity=multiplicity, environment=molecule.environment,
            )
            if any(set(group) == set(real) for group in molecule.fragments):
                from .fragments import split_fragments

                matching = [fragment for fragment in split_fragments(molecule)
                            if set(fragment.atom_ids) == set(physical_molecule.atom_ids)]
                if len(matching) != 1 or (matching[0].charge, matching[0].multiplicity) != (charge, multiplicity):
                    raise ValueError("Ghost electronic state must match the explicit physical fragment")
                physical_molecule = matching[0]
        except (TypeError, ValueError) as exc:
            result.diagnostics["reason"] = f"Invalid physical ghost-fragment state: {exc}"
            return result
        result.metadata.update(ghost_atom_indices=ghosts, basis_center_molecule=molecule.model_dump(mode="json"),
                               physical_molecule=physical_molecule.model_dump(mode="json"),
                               ghost_electronic_state={"charge": charge, "multiplicity": multiplicity})
        from .science import geometry_digest
        result.metadata.update(basis_center_geometry_sha256=geometry_digest(molecule),
                               physical_geometry_sha256=geometry_digest(physical_molecule))
    external_basis = {kind: Path(value) for kind, value in (("orbital", orbital_basis_file), ("auxiliary", auxiliary_basis_file)) if value is not None}
    if external_basis:
        if (method.engine != "orca" or operation != "energy" or "orbital" not in external_basis
                or method.method in {"HF-3c", "r2SCAN-3c", "r²SCAN-3c"}):
            result.diagnostics["reason"] = "Shared external basis files apply only to noncomposite ORCA energy calculations"
            return result
        for path in external_basis.values():
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 16 * 1024 * 1024:
                result.diagnostics["reason"] = "External basis must be a nonempty regular file at most 16 MiB"
                return result
    if molecule.environment:
        if molecule.environment != {"phase": "gas"}:
            result.diagnostics["reason"] = "explicit environment is unsupported by gas-phase adapter"
            return result
    if method.engine == "gpu4pyscf":
        if ghosts or ghost_electronic_state is not None:
            result.diagnostics["reason"] = "Ghost basis centers require explicit ORCA energy-only fragment state"
            return result
        if external_basis:
            result.diagnostics["reason"] = "Shared external basis files apply only to noncomposite ORCA energy calculations"
            return result
        return _run_gpu4pyscf_engine(
            molecule=molecule,
            method=method,
            resources=resources,
            workdir=workdir,
            operation=operation,
            cancel_event=cancel_event,
            executable=executable,
            process_runner=process_runner,
            result=result,
            start=start,
        )
    from .chemistry import atomic_number
    if method.engine == "xtb" and any(atomic_number(s) > 86 for s in molecule.symbols):
        result.diagnostics["reason"] = "GFN2-xTB parameterization does not cover elements beyond radon"
        return result
    if method.engine == "orca":
        from .orca_basis_names import resolve_orca_orbital_basis, validate_basis_elements

        try:
            receipts = []
            if method.basis and not external_basis:
                resolution = resolve_orca_orbital_basis(molecule, method.basis)
                receipts.append(validate_basis_elements(resolution["native_basis"], "orbital", molecule.symbols))
                result.metadata["orbital_basis_resolution"] = resolution
            if method.method in {"B3LYP", "wB97X-V", "wB97M-V"} and "auxiliary" not in external_basis:
                receipts.append(validate_basis_elements("def2/J", "auxiliary_j", molecule.symbols))
            result.metadata["basis_support_receipts"] = receipts
        except ValueError as exc:
            result.diagnostics["reason"] = str(exc)
            return result
    requested = str(executable) if executable is not None else os.environ.get(
        f"TOPOS_{method.engine.upper()}_EXECUTABLE", method.engine)
    binary = shutil.which(requested)
    if binary is None:
        result.status = "unavailable"
        result.diagnostics["reason"] = f"requested {method.engine} executable not found: {requested}"
        return result
    folder = Path(workdir).resolve()
    if folder.exists() and any(folder.iterdir()):
        result.status = "failed"
        result.diagnostics["reason"] = "attempt directory is not empty; stale outputs cannot be reused"
        return result
    folder.mkdir(parents=True, exist_ok=True)
    result.metadata["executable"] = str(Path(binary).resolve())
    result.metadata["executable_sha256"] = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
    try:
        basis_files = {}
        for kind, source in external_basis.items():
            name = f"{kind}.bas"
            data = source.read_bytes()
            if b"\x00" in data:
                raise EngineParseError("External basis file contains a NUL byte")
            (folder / name).write_bytes(data)
            basis_files[kind] = name
            result.metadata.setdefault("external_basis", {})[kind] = {
                "filename": name, "sha256": hashlib.sha256(data).hexdigest(),
                "declared_basis": method.basis if kind == "orbital" else method.auxiliary_basis or "def2/J",
                "format": "GAMESS-US", "source": "explicit supplied ORCA-exported basis; raw bytes retained",
            }
        if basis_files:
            result.metadata["basis_identity_status"] = "user-supplied-unverified"
            result.metadata["basis_comparison_protocol"] = digest_json({
                "method": method.model_dump(mode="json"),
                "basis_sha256": {kind: entry["sha256"] for kind, entry in result.metadata["external_basis"].items()},
            })
        probe_resources = resources.model_copy(update={"budget_seconds": min(resources.budget_seconds, 10.0)})
        if method.engine == "orca":
            (folder / "version.inp").write_text(_orca_version_input(resources), encoding="utf-8")
            probe_command = [str(Path(binary).resolve()), "version.inp"]
            probe_resources = probe_resources.model_copy(update={"threads": 1})
            result.metadata["version_probe"] = {
                "execution_kind": "real-diagnostic", "method": "HF", "basis": "STO-3G",
                "system": "He atom; charge 0; multiplicity 1", "purpose": "loader/version diagnostic",
                "scientific_result_eligibility": False, "parallel_mpi_validated": False,
            }
        else:
            probe_command = [binary, "--version"]
        probe = execute_process(probe_command, folder, probe_resources,
                            cancel_event=cancel_event, log_prefix="version")
        result.diagnostics["version_probe_process"] = probe.to_dict()
        probe_text = Path(probe.stdout_path).read_text(errors="replace") + Path(probe.stderr_path).read_text(errors="replace")
        version = _engine_version(probe_text, method.engine)
        result.diagnostics["observed_probe_version"] = version
        if probe.status in {"cancelled", "timed-out"}:
            result.status = probe.status
            result.diagnostics["reason"] = probe.reason
            return result
        if version is None or probe.status != "completed":
            result.status = "unavailable"
            result.diagnostics["reason"] = "successful engine version/loader probe did not establish executable identity/version"
            return result
        result.engine_version = version
        if method.engine == "orca" and ("ORCA TERMINATED NORMALLY" not in probe_text or
                                         "FINAL SINGLE POINT ENERGY" not in probe_text or
                                         "SCF CONVERGED AFTER" not in probe_text or
                                         "SCF NOT CONVERGED" in probe_text):
            result.status = "unavailable"
            result.diagnostics["reason"] = "ORCA serial version/loader diagnostic did not terminate normally with an energy"
            return result
        if method.engine == "orca":
            probe_energies = re.findall(r"FINAL SINGLE POINT ENERGY\s+(" + _FLOAT + ")", probe_text)
            if not probe_energies:
                result.status = "unavailable"
                result.diagnostics["reason"] = "ORCA version/loader diagnostic has no finite electronic energy"
                return result
            _number(probe_energies[-1])
        expected = method.engine_version
        if expected is not None and expected != result.engine_version:
            result.diagnostics["reason"] = f"requested engine version {expected}; found {result.engine_version}"
            return result
        if (method.engine == "xtb" and result.engine_version != "6.7.1") or (method.engine == "orca" and result.engine_version != ORCA_VERSION):
            result.diagnostics["reason"] = "engine version lies outside the adapter capability profile"
            return result
        remaining = resources.budget_seconds - (time.monotonic() - start)
        if remaining <= 0:
            result.status = "timed-out"
            result.diagnostics["reason"] = "attempt budget exhausted during preflight"
            return result
        write_xyz(molecule, folder / "input.xyz")
        if method.engine == "xtb":
            command = [binary, "input.xyz", "--gfn", "2", "--chrg", str(molecule.charge),
                       "--uhf", str(molecule.multiplicity - 1), "--json"]
            if operation == "optimize":
                command.extend(["--opt", XTB_PROFILES[method.profile_id]])
            # xTB processes run-type flags in order: optimization must precede --grad.
            command.append("--grad")
            runtime_resources = resources.model_copy(update={"budget_seconds": remaining})
        else:
            if operation == "optimize":
                result.metadata["native_optimizer_policy"] = {
                    "name": "EnforceStrictConvergence", "requested_value": True,
                    "scope": "native stopping policy; unchanged requested numerical tolerances",
                    "manual": "https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/goat.html",
                }
            (folder / "job.inp").write_text(_orca_input(molecule, method, resources, operation,
                ghost_atom_indices=ghosts, ghost_electronic_state=ghost_electronic_state, basis_files=basis_files))
            command = [str(Path(binary).resolve()), "job.inp"]
            # %pal accounts for total workers; prevent nested OpenMP oversubscription.
            runtime_resources = resources.model_copy(update={"budget_seconds": remaining})
        result.command = command
        result.metadata["execution_kind"] = "real"
        if method.engine == "orca" and method.method in {"B3LYP", "wB97X-V", "wB97M-V"}:
            result.metadata["resolved_auxiliary_basis"] = "def2/J"
            result.metadata["exchange_approximation"] = "RIJCOSX"
        result.metadata["adapter_validation"] = "live-tested" if method.engine == "xtb" else "conditional-not-live-validated"
        process_options = {"threads_per_process": 1} if method.engine == "orca" else {}
        process = execute_process(command, folder, runtime_resources, cancel_event=cancel_event,
                                  **process_options)
        result.diagnostics["process"] = process.to_dict()
        result.status = process.status
        if process.status != "completed":
            result.diagnostics["reason"] = process.reason
            return result
        raw = Path(process.stdout_path).read_text(errors="replace")
        stderr = Path(process.stderr_path).read_text(errors="replace")
        if method.engine == "xtb":
            if "normal termination of xtb" not in raw + stderr or "convergence criteria satisfied" not in raw:
                raise EngineParseError("xTB normal termination and electronic convergence not established")
            matches = re.findall(r"TOTAL ENERGY\s+(" + _FLOAT + r")\s+Eh", raw)
            if not matches:
                raise EngineParseError("xTB total energy absent")
            energy = _number(matches[-1])
            output_molecule = read_xyz(folder / "xtbopt.xyz", molecule) if operation == "optimize" else molecule
            gradient_energy, gradient = parse_xtb_gradient(folder / "gradient", output_molecule)
            if abs(energy - gradient_energy) > 2e-9:
                raise EngineParseError("xTB energy and gradient artifacts disagree")
            if operation == "optimize":
                converged = "GEOMETRY OPTIMIZATION CONVERGED" in raw
                limits = re.findall(r"grad\. convergence\s+(" + _FLOAT + ")", raw)
                thresholds = re.findall(r"energy convergence\s+(" + _FLOAT + ")", raw)
                if not limits or not thresholds:
                    raise EngineParseError("native optimization thresholds absent")
                threshold = _number(limits[-1])
                norm = float(np.linalg.norm(gradient))
                result.diagnostics["convergence"] = {"profile": method.profile_id,
                    "native_level": XTB_PROFILES[method.profile_id], "native_reported": converged,
                    "gradient_norm_hartree_per_bohr": norm, "gradient_norm_threshold": threshold,
                    "energy_change_threshold_hartree": _number(thresholds[-1]),
                    "criteria_source": "xTB native optimizer; no claim of ORCA mapping tolerances"}
                result.converged = converged and norm <= threshold * (1 + 1e-6)
            else:
                result.converged = True  # electronic convergence only, not geometry classification
        else:
            actual_version = _engine_version(raw, "orca")
            if actual_version != result.engine_version:
                raise EngineParseError("ORCA production header does not match the verified engine version")
            if "ORCA TERMINATED NORMALLY" not in raw:
                raise EngineParseError("ORCA normal termination absent")
            if "SCF CONVERGED AFTER" not in raw:
                raise EngineParseError("ORCA electronic convergence marker absent")
            if re.search(r"SCF NOT CONVERGED|SCF CONVERGENCE FAILURE", raw, re.I):
                raise EngineParseError("ORCA SCF failed to converge")
            if profile_receipt is not None:
                from .orca_numerical_profiles import observe_scf_numerical_profile

                evidence = observe_scf_numerical_profile(raw)
                result.diagnostics["scf_numerical_profile"] = evidence
                if evidence["passed"] is not True:
                    raise EngineParseError("Explicit ORCA numerical profile not achieved: " + "; ".join(evidence["failures"]))
            matches = re.findall(r"FINAL SINGLE POINT ENERGY\s+(" + _FLOAT + ")", raw)
            if not matches:
                raise EngineParseError("ORCA total energy absent")
            energy = _number(matches[-1])
            output_molecule = read_xyz(folder / "job.xyz", molecule) if operation == "optimize" else physical_molecule
            gradient = None
            if operation == "gradient":
                derivative_energy, gradient = parse_orca_engrad(folder / "job.engrad", output_molecule)
                if abs(energy - derivative_energy) > 2e-7:
                    raise EngineParseError("ORCA energy and derivative artifacts disagree")
            if operation == "optimize":
                from .orca_geometry_evidence import convergence_evidence

                energy_tolerance = 1e-10 if method.profile_id == "orca-vpt2-reference-v1" else 1e-7
                criteria, energy_evidence = convergence_evidence(raw, energy_tolerance=energy_tolerance)
                result.diagnostics["convergence"] = criteria
                if energy_evidence is not None:
                    result.diagnostics["energy_change_evidence"] = energy_evidence
                result.diagnostics["native_optimizer_reported_converged"] = "THE OPTIMIZATION HAS CONVERGED" in raw
                result.converged = ("THE OPTIMIZATION HAS CONVERGED" in raw and
                                    len(criteria) == 5 and all(criteria.values()))
                if result.converged:
                    # Opt and EnGrad are distinct native run types. Verify the
                    # returned geometry with a fresh gradient instead of making
                    # assumptions about optimizer scratch-file retention.
                    remaining = resources.budget_seconds - (time.monotonic() - start)
                    if remaining <= 0 or (cancel_event is not None and cancel_event.is_set()):
                        result.status = "cancelled" if cancel_event is not None and cancel_event.is_set() else "timed-out"
                        result.converged = False
                        result.diagnostics["reason"] = "Final optimization gradient was not executed within the active attempt"
                        return result
                    final = run_engine(output_molecule, method, resources.model_copy(update={"budget_seconds": remaining}),
                                       folder / "final-gradient", operation="gradient", cancel_event=cancel_event,
                                       executable=binary, process_runner=execute_process)
                    result.diagnostics["final_gradient"] = {"status": final.status, "diagnostics": final.diagnostics,
                        "command": final.command, "elapsed_seconds": final.elapsed_seconds}
                    if (final.status != "completed" or final.converged is not True
                            or final.gradient_hartree_per_bohr is None or final.energy_hartree is None):
                        result.status = final.status if final.status != "completed" else "failed"
                        result.converged = False
                        result.diagnostics["reason"] = "Independent final optimization gradient did not complete"
                        return result
                    if (final.engine_version != result.engine_version
                            or final.metadata.get("executable_sha256") != result.metadata["executable_sha256"]
                            or abs(energy - final.energy_hartree) > 2e-7):
                        raise EngineParseError("Optimization and final gradient disagree in executable, version or energy")
                    gradient = final.gradient_hartree_per_bohr
                    from .science import RIGID_GRADIENT_RESIDUAL_LIMIT, project_internal_gradient

                    strict = method.profile_id == "orca-vpt2-reference-v1"
                    max_threshold, rms_threshold = (1e-6, 3e-7) if strict else (1e-5, 3e-6)
                    values = np.asarray(gradient, dtype=float)
                    internal_values, rigid_values = project_internal_gradient(output_molecule, values)
                    maximum = float(np.max(np.abs(internal_values)))
                    rms = float(np.sqrt(np.mean(internal_values ** 2)))
                    rigid_maximum = float(np.max(np.abs(rigid_values)))
                    rigid_threshold = max(RIGID_GRADIENT_RESIDUAL_LIMIT, max_threshold)
                    stationary = (
                        maximum <= max_threshold
                        and rms <= rms_threshold
                        and rigid_maximum <= rigid_threshold
                    )
                    result.diagnostics["independent_stationarity"] = {
                        "max_gradient_hartree_per_bohr": maximum, "rms_gradient_hartree_per_bohr": rms,
                        "raw_max_gradient_hartree_per_bohr": float(np.max(np.abs(values))),
                        "raw_rms_gradient_hartree_per_bohr": float(np.sqrt(np.mean(values ** 2))),
                        "rigid_residual_max_hartree_per_bohr": rigid_maximum,
                        "rigid_residual_threshold": rigid_threshold,
                        "max_gradient_threshold": max_threshold, "rms_gradient_threshold": rms_threshold,
                        "projection": "rigid-translation-rotation-removed",
                        "passed": stationary,
                        "scope": "independent final EnGrad projected orthogonal to rigid translations and rotations; no Hessian classification"}
                    result.converged = result.converged and stationary
                    result.metadata["final_gradient_verification"] = {
                        "execution_kind": "real", "method": method.model_dump(mode="json"),
                        "directory": "final-gradient", "energy_hartree": final.energy_hartree,
                        "energy_difference_hartree": final.energy_hartree - energy,
                        "engine": final.engine, "engine_version": final.engine_version,
                        "executable_sha256": final.metadata["executable_sha256"],
                        "command": final.command, "resources": final.metadata["resources"],
                        "input_molecule_sha256": digest_json(output_molecule.model_dump(mode="json")),
                        "native_files_sha256": {
                            name: hashlib.sha256((folder / "final-gradient" / name).read_bytes()).hexdigest()
                            for name in ("job.inp", "engine.stdout", "job.engrad")},
                        "budget_scope": "remaining original attempt wall budget"}
            else:
                result.converged = True
        dipole_output = (folder / "final-gradient" / "engine.stdout"
                         if result.metadata.get("final_gradient_verification") else Path(process.stdout_path))
        dipole = parse_cartesian_dipole(dipole_output.read_text(errors="replace"), method.engine)
        if dipole is not None:
            from .science import geometry_digest

            result.metadata["dipole_cartesian_debye"] = dipole["cartesian_debye"]
            result.metadata["dipole_provenance"] = {
                **dipole, "geometry_digest": geometry_digest(output_molecule),
                "method": method.method, "engine": method.engine, "engine_version": result.engine_version,
                "raw_output": dipole_output.relative_to(folder).as_posix(),
                "raw_output_sha256": hashlib.sha256(dipole_output.read_bytes()).hexdigest(),
            }
        if (result.metadata.get("final_gradient_verification")
                and ((cancel_event is not None and cancel_event.is_set())
                     or time.monotonic() - start >= resources.budget_seconds)):
            result.status = "cancelled" if cancel_event is not None and cancel_event.is_set() else "timed-out"
            result.converged = False
            result.diagnostics["reason"] = "Optimization attempt stopped before final-gradient publication"
            return result
        result.energy_hartree = energy
        result.gradient_hartree_per_bohr = gradient if operation != "energy" else None
        result.molecule = output_molecule
        if not result.converged:
            result.status = "partial"
            result.diagnostics["reason"] = "requested optimization convergence was not established"
        result.metadata["gradient_units"] = "hartree/bohr" if gradient is not None else None
        result.metadata["energy_definition"] = "electronic potential energy; no thermochemical correction"
        result.metadata["convergence_scope"] = "geometry and electronic" if operation == "optimize" else "electronic only"
        result.metadata["stationary_point_classification"] = "unclassified; no frequency Hessian"
        return result
    except (EngineParseError, OSError, ValueError) as exc:
        result.status = "failed"
        result.converged = False
        result.diagnostics["reason"] = str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - start
        try:
            result.artifacts = artifact_inventory(folder)
        except (OSError, EngineParseError) as exc:
            result.status = "failed"
            result.converged = False
            result.diagnostics["artifact_error"] = str(exc)


def _run_gpu4pyscf_engine(
    *,
    molecule: Molecule,
    method: MethodSpec,
    resources: ResourceLimits,
    workdir: str | Path,
    operation: Literal["energy", "gradient", "optimize"],
    cancel_event: Event | None,
    executable: str | Path | None,
    process_runner: Callable[..., Any] | None,
    result: EngineResult,
    start: float,
) -> EngineResult:
    """Execute authentic FP64 GPU4PySCF on CUDA; fail closed if GPU or gpu4pyscf is absent."""
    python_binary = resolve_gpu4pyscf_python(executable)
    if python_binary is None:
        result.status = "unavailable"
        result.diagnostics["reason"] = (
            "GPU4PySCF Python interpreter unavailable; set TOPOS_GPU4PYSCF_PYTHON / COCHEM_GPU4PYSCF_PYTHON "
            "or install cochem-gpu4pyscf-python (CPU fallback is strictly disabled)"
        )
        result.elapsed_seconds = time.monotonic() - start
        return result

    folder = Path(workdir).resolve()
    if folder.exists() and any(folder.iterdir()):
        result.status = "failed"
        result.diagnostics["reason"] = "attempt directory is not empty; stale outputs cannot be reused"
        result.elapsed_seconds = time.monotonic() - start
        return result
    folder.mkdir(parents=True, exist_ok=True)

    auxbasis = method.auxiliary_basis or DEFAULT_GPU4PYSCF_AUXBASIS
    result.metadata["executable"] = str(python_binary)
    result.metadata["executable_sha256"] = hashlib.sha256(python_binary.read_bytes()).hexdigest()
    result.metadata["device"] = resources.device
    result.metadata["resolved_auxiliary_basis"] = auxbasis
    result.metadata["density_fitting"] = True

    try:
        write_xyz(molecule, folder / "input.xyz")
        driver_code = gpu4pyscf_driver_source(
            molecule,
            method=method.method,
            basis=str(method.basis),
            auxbasis=auxbasis,
            operation=operation,
            expected_version=method.engine_version,
        )
        driver_path = folder / "job.py"
        driver_path.write_text(driver_code, encoding="utf-8")
        result.metadata["driver_script_sha256"] = hashlib.sha256(driver_path.read_bytes()).hexdigest()

        command = [str(python_binary), "job.py"]
        result.command = command
        execute_gpu = process_runner or _run_gpu_process
        process = execute_gpu(command, folder, resources, cancel_event=cancel_event, log_prefix="engine")
        result.diagnostics["process"] = process.to_dict()

        stderr_text = Path(process.stderr_path).read_text(errors="replace") if Path(process.stderr_path).is_file() else ""
        if process.status != "completed":
            if "CUDA_UNAVAILABLE:" in stderr_text or "GPU4PYSCF_UNAVAILABLE:" in stderr_text:
                result.status = "unavailable"
                result.metadata["execution_kind"] = "not-executed"
                result.diagnostics["reason"] = stderr_text.strip() or process.reason
            elif "GPU4PYSCF_VERSION_MISMATCH:" in stderr_text:
                result.status = "unsupported"
                result.metadata["execution_kind"] = "not-executed"
                result.diagnostics["reason"] = stderr_text.strip()
            else:
                result.status = process.status
                result.metadata["execution_kind"] = "real"
                result.diagnostics["reason"] = stderr_text.strip() or process.reason
            return result

        result_file = folder / "gpu4pyscf-result.json"
        if not result_file.is_file():
            raise EngineParseError("GPU4PySCF worker completed without producing gpu4pyscf-result.json")
        observed = _parse_gpu4pyscf_output(result_file.read_text(encoding="utf-8"), molecule, operation)

        result.metadata["execution_kind"] = "real"
        result.metadata["adapter_validation"] = "live-tested"
        result.metadata["result_json_sha256"] = hashlib.sha256(result_file.read_bytes()).hexdigest()
        result.metadata["gpu_device_name"] = observed["gpu_device_name"]
        result.metadata["gpu_device_index"] = observed["gpu_device_index"]
        result.metadata["gpu_total_memory_mb"] = observed["gpu_total_memory_mb"]
        result.metadata["gpu_compute_capability"] = observed["gpu_compute_capability"]
        result.metadata["gpu_banner"] = observed["gpu_banner"]
        result.metadata["pyscf_version"] = observed["pyscf_version"]
        result.metadata["gpu4pyscf_version"] = observed["gpu4pyscf_version"]
        result.metadata["cupy_version"] = observed["cupy_version"]
        result.metadata["cuda_runtime_version"] = observed["cuda_runtime_version"]
        result.metadata["python_executable"] = observed["python_executable"]
        result.metadata["python_executable_sha256"] = observed["python_executable_sha256"]
        result.metadata["resolved_xc"] = observed["xc"]
        result.metadata["resolved_basis"] = observed["basis"]
        result.metadata["xc_grid"] = observed["xc_grid"]
        result.metadata["nlc_grid"] = observed["nlc_grid"]
        if observed.get("dipole_cartesian_debye") is not None:
            result.metadata["dipole_cartesian_debye"] = observed["dipole_cartesian_debye"]
        if observed.get("optimization") is not None:
            result.diagnostics["optimization"] = observed["optimization"]

        output_molecule = (
            Molecule.model_validate({**molecule.model_dump(), "coordinates": observed["coordinates_angstrom"]})
            if operation == "optimize" else molecule
        )
        result.engine_version = observed["gpu4pyscf_version"]
        result.energy_hartree = observed["energy_hartree"]
        result.gradient_hartree_per_bohr = observed["gradient_hartree_per_bohr"] if operation != "energy" else None
        result.molecule = output_molecule
        result.converged = bool(observed["converged"])
        result.status = "completed" if result.converged else "partial"
        if not result.converged:
            result.diagnostics["reason"] = "requested GPU4PySCF optimization convergence was not established"
        result.metadata["gradient_units"] = "hartree/bohr" if result.gradient_hartree_per_bohr is not None else None
        result.metadata["energy_definition"] = "electronic potential energy; no thermochemical correction"
        result.metadata["convergence_scope"] = "geometry and electronic" if operation == "optimize" else "electronic only"
        result.metadata["stationary_point_classification"] = "unclassified; no frequency Hessian"
        return result
    except (EngineParseError, OSError, ValueError, json.JSONDecodeError) as exc:
        result.status = "failed"
        result.converged = False
        result.diagnostics["reason"] = str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - start
        try:
            result.artifacts = artifact_inventory(folder)
        except (OSError, EngineParseError) as exc:
            result.status = "failed"
            result.converged = False
            result.diagnostics["artifact_error"] = str(exc)
