"""ORCA 6.1.1 analytic Cartesian Hessians with separate stationarity evidence.

The documented Freq operation is available for SCF HF/DFT, not CC/double
hybrids. An interrupted analytic Hessian restarts in fresh scratch. Only
completed, byte-verified stages are reused. Native thermochemistry is not
silently substituted for TOPOS's explicit isotope/standard-state treatment.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable
from uuid import uuid4

import numpy as np

from .engines import (
    ORCA_VERSION,
    EngineParseError,
    EngineResult,
    _engine_version,
    _method_problem,
    _number,
    _orca_input,
    artifact_inventory,
    run_engine,
)
from .models import MethodSpec, Molecule, ResourceLimits
from .runtime import run_process
from .science import BOHR_ANGSTROM, harmonic_analysis, validate_derivatives
from .storage import IntegrityError, atomic_json, file_digest

FREQUENCY_MANUAL = "https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/frequencies.html"
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"


def parse_orca_hessian(path: str | Path, molecule: Molecule) -> dict[str, Any]:
    """Parse a complete blocked Cartesian .hess matrix and its Bohr geometry.

    Native atomic masses are retained separately; isotope-independent electronic
    derivatives are mass weighted using the explicit TOPOS isotope policy.
    """
    sections: dict[str, list[str]] = {}
    current = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("$"):
            current = stripped.lower()
            if current in sections:
                raise EngineParseError("duplicate ORCA Hessian section")
            sections[current] = []
        elif current and stripped and not stripped.startswith("#"):
            sections[current].append(stripped)
    n = len(molecule.symbols)
    try:
        atoms, matrix = sections["$atoms"], sections["$hessian"]
        if int(atoms[0]) != n or len(atoms) != n + 1 or int(matrix[0]) != 3 * n:
            raise EngineParseError("Hessian atom count/dimension mismatch")
        rows = [line.split() for line in atoms[1:]]
        if any(len(row) != 5 for row in rows) or [r[0].capitalize() for r in rows] != molecule.symbols:
            raise EngineParseError("Hessian atom order mismatch")
        masses = [_number(r[1]) for r in rows]
        xyz = np.asarray([[_number(v) for v in r[2:]] for r in rows]) * BOHR_ANGSTROM
        if min(masses) <= 0 or not np.allclose(xyz, molecule.coordinates, atol=2e-7, rtol=0):
            raise EngineParseError("Hessian masses or reference geometry invalid")
        dimension = 3 * n
        hessian = np.full((dimension, dimension), np.nan)
        cursor = 1
        while cursor < len(matrix):
            columns = [int(value) for value in matrix[cursor].split()]
            cursor += 1
            if not columns or len(columns) > 6 or len(set(columns)) != len(columns) or any(i < 0 or i >= dimension for i in columns):
                raise EngineParseError("Hessian column header invalid")
            for expected in range(dimension):
                values = matrix[cursor].split()
                cursor += 1
                if len(values) != 1 + len(columns) or int(values[0]) != expected:
                    raise EngineParseError("Hessian blocked row missing or reordered")
                if np.isfinite(hessian[expected, columns]).any():
                    raise EngineParseError("Hessian duplicate matrix elements")
                hessian[expected, columns] = [_number(value) for value in values[1:]]
        validate_derivatives(hessian=hessian, natoms=n)
    except (KeyError, IndexError, ValueError) as exc:
        raise EngineParseError(f"incomplete or invalid ORCA Hessian: {exc}") from exc
    return {"hessian_hartree_per_bohr2": hessian.tolist(), "native_masses_amu": masses,
            "units": "hartree/bohr^2", "native_coordinates_units": "bohr",
            "mass_policy": "native masses retained; TOPOS isotope masses used for independent mode analysis"}


def orca_frequency_input(molecule: Molecule, method: MethodSpec, resources: ResourceLimits) -> str:
    problem = _method_problem(method, resources, "gradient")
    if problem or method.engine != "orca" or method.constraints:
        raise ValueError(problem or "native analytic frequencies require unconstrained ORCA HF/DFT")
    # _method_problem restricts to the tested SCF method/basis registry. No
    # generic keyword injection, double hybrid, RI-JK, CC or external basis.
    if method.method not in {"B3LYP", "HF", "HF-3c", "r2SCAN-3c", "r²SCAN-3c", "wB97X-V", "wB97M-V"}:
        raise ValueError("ORCA analytic Freq is restricted to the documented SCF HF/DFT domain")
    lines = _orca_input(molecule, method, resources, "energy").splitlines()
    lines[0] += " Freq"
    return "\n".join(lines) + "\n"


def _read_completed(receipt: Path, root: Path) -> EngineResult | None:
    if not receipt.exists():
        return None
    payload = json.loads(receipt.read_text())
    result = EngineResult.model_validate(payload["result"])
    if result.status != "completed" or result.metadata.get("execution_kind") != "real" or not result.artifacts:
        raise IntegrityError("native derivative receipt does not establish completed actual execution")
    for artifact in result.artifacts:
        path = Path(artifact.path)
        if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file() or file_digest(path) != artifact.sha256:
            raise IntegrityError("native derivative completed artifact changed")
    return result


def run_orca_hessian(molecule: Molecule, method: MethodSpec, resources: ResourceLimits,
                     workdir: str | Path, *, executable: str | Path | None = None,
                     process_runner: Callable[..., Any] | None = None,
                     cancel_event: Event | None = None, gradient_threshold: float = 1e-5) -> EngineResult:
    """Execute Engrad then independent Freq; no Hessian or success from absent data."""
    started = time.monotonic()
    result = EngineResult(status="unsupported", engine="orca", method=method.method, operation="hessian",
                          metadata={"execution_kind": "not-executed", "manual": FREQUENCY_MANUAL,
                                    "derivative_kind": "native-analytic-SCF-Hessian",
                                    "analytic_restart_policy": "reuse completed hashed stages; restart interrupted Freq in fresh scratch"})
    try:
        deck = orca_frequency_input(molecule, method, resources)
        if not np.isfinite(gradient_threshold) or gradient_threshold <= 0:
            raise ValueError("gradient threshold must be finite positive")
    except ValueError as exc:
        result.diagnostics["reason"] = str(exc)
        return result
    binary = shutil.which(str(executable) if executable is not None else os.environ.get("TOPOS_ORCA_EXECUTABLE", "orca"))
    if binary is None:
        result.status, result.diagnostics["reason"] = "unavailable", "ORCA executable missing"
        return result
    binary = str(Path(binary).resolve())
    folder = Path(workdir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    protocol = {"schema": "topos-native-orca-hessian/0.1.0", "molecule": molecule.model_dump(mode="json"),
                "method": method.model_dump(mode="json"), "gradient_threshold": gradient_threshold,
                "resources": resources.model_dump(exclude={"budget_seconds"}), "executable_sha256": file_digest(Path(binary))}
    protocol_path = folder / "protocol.json"
    if protocol_path.exists():
        if json.loads(protocol_path.read_text()) != protocol:
            raise IntegrityError("native Hessian recovery protocol changed")
    elif any(folder.iterdir()):
        raise IntegrityError("native Hessian directory contains unverified evidence")
    else:
        atomic_json(protocol_path, protocol)
    cached = _read_completed(folder / "completed.json", folder)
    if cached is not None:
        cached.metadata["reused_completed_hessian"] = True
        return cached
    result.metadata.update(executable=binary, executable_sha256=protocol["executable_sha256"], protocol=protocol)
    execute = process_runner or run_process

    def remaining() -> ResourceLimits:
        seconds = resources.budget_seconds - (time.monotonic() - started)
        if seconds <= 0:
            raise TimeoutError("native Hessian budget exhausted")
        return resources.model_copy(update={"budget_seconds": seconds})

    try:
        reference = _read_completed(folder / "reference.json", folder)
        if reference is None:
            reference = run_engine(molecule, method, remaining(), folder / ("reference-" + uuid4().hex),
                                   operation="gradient", executable=binary, process_runner=process_runner,
                                   cancel_event=cancel_event)
            if reference.status == "completed":
                atomic_json(folder / "reference.json", {"result": reference.model_dump(mode="json")})
        result.metadata["reference_gradient_result"] = reference.model_dump(mode="json")
        result.artifacts = reference.artifacts.copy()
        if reference.status != "completed":
            result.status = reference.status
            result.diagnostics["reason"] = "reference gradient did not complete"
            return result
        if reference.engine_version != ORCA_VERSION or reference.gradient_hartree_per_bohr is None or reference.energy_hartree is None:
            raise EngineParseError("pinned native reference gradient/energy missing")
        result.energy_hartree = reference.energy_hartree
        result.gradient_hartree_per_bohr = reference.gradient_hartree_per_bohr
        result.engine_version = reference.engine_version
        result.molecule = molecule
        native = folder / ("frequency-" + uuid4().hex)
        native.mkdir()
        (native / "frequency.inp").write_text(deck)
        result.command = [binary, "frequency.inp"]
        result.metadata["execution_kind"] = "real"
        process = execute(result.command, native, remaining(), cancel_event=cancel_event,
                          log_prefix="frequency", threads_per_process=1)
        result.status = process.status
        result.diagnostics["process"] = process.to_dict()
        result.artifacts.extend(artifact_inventory(native))
        if process.status != "completed":
            result.diagnostics["reason"] = process.reason
            return result
        raw = Path(process.stdout_path).read_text(errors="replace")
        energies = re.findall(r"FINAL SINGLE POINT ENERGY\s+(" + _FLOAT + ")", raw)
        if (_engine_version(raw, "orca") != ORCA_VERSION or "ORCA TERMINATED NORMALLY" not in raw
                or "SCF NOT CONVERGED" in raw or not energies):
            raise EngineParseError("native analytic frequency completion/energy unverified")
        if abs(_number(energies[-1]) - reference.energy_hartree) > 1e-7:
            raise EngineParseError("native frequency and reference gradient energies disagree")
        parsed = parse_orca_hessian(native / "frequency.hess", molecule)
        result.metadata.update(parsed)
        result.metadata["analysis"] = harmonic_analysis(molecule, parsed["hessian_hartree_per_bohr2"],
                                                        gradient_hartree_per_bohr=reference.gradient_hartree_per_bohr,
                                                        gradient_threshold=gradient_threshold)
        result.metadata["output_molecule"] = molecule.model_dump(mode="json")
        result.converged = result.metadata["analysis"]["stationary"]
        result.elapsed_seconds = time.monotonic() - started
        atomic_json(folder / "completed.json", {"result": result.model_dump(mode="json")})
        return result
    except TimeoutError as exc:
        result.status, result.diagnostics["reason"] = "timed-out", str(exc)
        return result
    except (ValueError, OSError) as exc:
        result.status, result.diagnostics["reason"] = "failed", str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - started
