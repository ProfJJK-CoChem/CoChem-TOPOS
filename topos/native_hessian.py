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
    _orca_version_input,
    artifact_inventory,
    parse_orca_engrad,
    run_engine,
)
from .models import MethodSpec, Molecule, ResourceLimits
from .runtime import run_process
from .science import BOHR_ANGSTROM, harmonic_analysis, validate_derivatives
from .storage import IntegrityError, atomic_json, file_digest

FREQUENCY_MANUAL = "https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/frequencies.html"
VV10_MANUAL = "https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/dispersioncorrections.html#non-local-dispersion-correction-vv10-dft-nl"
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"


def parse_orca_hessian(path: str | Path, molecule: Molecule) -> dict[str, Any]:
    """Parse and transform a physical .hess matrix to its requested frame.

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
        if min(masses) <= 0:
            raise EngineParseError("Hessian masses invalid")
        # Native Freq translates to its mass center, and VPT2 additionally
        # rotates into principal axes. Equality of absolute coordinates would
        # reject genuine derivatives. Bind indexed geometry under a proper
        # rigid transformation, then transform the Cartesian tensor itself.
        from .rotational_transfer import proper_alignment, rotate_cartesian_hessian

        alignment = proper_alignment(xyz, molecule.coordinates, masses)
        if alignment['max_atom_displacement_angstrom'] > 2e-7:
            raise EngineParseError("Hessian reference geometry differs beyond a proper rigid transformation")
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
        hessian = rotate_cartesian_hessian(hessian, alignment['rotation_source_to_target'])
    except (KeyError, IndexError, ValueError) as exc:
        raise EngineParseError(f"incomplete or invalid ORCA Hessian: {exc}") from exc
    return {"hessian_hartree_per_bohr2": hessian.tolist(), "native_masses_amu": masses,
            "units": "hartree/bohr^2", "native_coordinates_units": "bohr",
            "native_coordinates_angstrom": xyz.tolist(), "native_to_requested_frame": alignment,
            "hessian_frame": "requested molecule Cartesian frame; native tensor transformed by indexed proper rotation",
            "mass_policy": "native masses retained; TOPOS isotope masses used for independent mode analysis"}


def orca_frequency_input(molecule: Molecule, method: MethodSpec, resources: ResourceLimits,
                         *, check_cpu_affinity: bool = True) -> str:
    # Read-only verification renders the recorded allocation on any controller;
    # native execution retains the current machine's affinity check by default.
    problem = _method_problem(method, resources, "gradient", check_cpu_affinity=check_cpu_affinity)
    if problem or method.engine != "orca" or method.constraints:
        raise ValueError(problem or "native analytic frequencies require unconstrained ORCA HF/DFT")
    if method.method in {"wB97X-V", "wB97M-V"}:
        raise ValueError("ORCA 6.1 VV10/NL second derivatives are unavailable: analytic Hessians and native VPT2 "
                         "cannot use this functional; separately requested numerical frequencies remain possible. " + VV10_MANUAL)
    # _method_problem restricts to the tested SCF method/basis registry. No
    # generic keyword injection, double hybrid, RI-JK, CC or external basis.
    if method.method not in {"B3LYP", "HF", "HF-3c", "r2SCAN-3c", "r²SCAN-3c"}:
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
    seen: set[Path] = set()
    for artifact in result.artifacts:
        path = Path(artifact.path)
        resolved = path.resolve()
        if (resolved in seen or not resolved.is_relative_to(root.resolve()) or path.is_symlink()
                or not path.is_file() or file_digest(path) != artifact.sha256
                or path.stat().st_size != artifact.size_bytes):
            raise IntegrityError("native derivative completed artifact changed")
        seen.add(resolved)
    return result


def _derivative_stopped(result: EngineResult, resources: ResourceLimits, started: float,
                        cancel_event: Event | None, label: str) -> bool:
    """Stop the current call without changing previously completed receipts."""
    elapsed = time.monotonic() - started
    if cancel_event is not None and cancel_event.is_set():
        result.status, result.diagnostics['reason'] = 'cancelled', f'{label} cancelled'
    elif elapsed >= resources.budget_seconds:
        result.status, result.diagnostics['reason'] = 'timed-out', f'{label} budget exhausted'
    else:
        return False
    result.converged = False
    result.elapsed_seconds = elapsed
    return True


def _raw_artifact(result: EngineResult, path: Path, root: Path) -> Path:
    """Require one exact confined retained artifact, never a basename fallback."""
    resolved = path.resolve()
    entries = [a for a in result.artifacts if Path(a.path).resolve() == resolved]
    if (not resolved.is_relative_to(root.resolve()) or len(entries) != 1 or path.is_symlink()
            or not path.is_file() or file_digest(path) != entries[0].sha256
            or path.stat().st_size != entries[0].size_bytes):
        raise IntegrityError('native derivative raw artifact is absent, changed or outside its assigned root')
    return path


def _raw_process(result: EngineResult, root: Path, executable: str, deck_name: str,
                 output_prefix: str, *, key: str = 'process') -> tuple[Path, str]:
    process = result.diagnostics.get(key, {})
    command = [executable, deck_name]
    if (process.get('status') != 'completed' or process.get('returncode') != 0
            or process.get('command') != command or key == 'process' and result.command != command):
        raise IntegrityError('native derivative process/command did not establish actual successful execution')
    stdout = Path(process.get('stdout_path', ''))
    stderr = Path(process.get('stderr_path', ''))
    if stdout.name != output_prefix + '.stdout' or stderr != stdout.with_name(output_prefix + '.stderr'):
        raise IntegrityError('native derivative process output locators differ from the actual operation')
    raw = _raw_artifact(result, stdout, root).read_text(errors='replace')
    errors = _raw_artifact(result, stderr, root).read_text(errors='replace')
    if (_engine_version(raw + errors, 'orca') != ORCA_VERSION or 'ORCA TERMINATED NORMALLY' not in raw
            or 'SCF CONVERGED AFTER' not in raw
            or re.search(r'SCF NOT CONVERGED|SCF CONVERGENCE FAILURE', raw + errors, re.I)):
        raise IntegrityError('native derivative raw version/completion/electronic convergence unverified')
    return stdout.parent, raw


def verify_orca_gradient_result(result: EngineResult, molecule: Molecule, method: MethodSpec,
                                resources: ResourceLimits, root: str | Path, *, executable: str,
                                executable_sha256: str) -> tuple[float, np.ndarray]:
    """Reparse retained physical gradients; does not execute or certify a new job.

    Cache loading separately verifies every retained artifact. This operation
    validator requires the exact scientific input and all raw files used here.
    Its expected executable identity is supplied by the caller's protocol, not
    inferred from the result's metadata.
    """
    root = Path(root)
    md = result.metadata
    try:
        if (result.status != 'completed' or result.converged is not True or result.engine != 'orca'
                or result.operation != 'gradient' or result.method != method.method
                or result.engine_version != ORCA_VERSION or result.molecule != molecule
                or md.get('execution_kind') != 'real' or md.get('requested_method') != method.model_dump(mode='json')
                or md.get('profile_id') != method.profile_id or md.get('executable') != executable
                or md.get('executable_sha256') != executable_sha256
                or ResourceLimits.model_validate(md['resources']).model_dump(exclude={'budget_seconds'})
                   != resources.model_dump(exclude={'budget_seconds'})):
            raise IntegrityError('native gradient cache differs from its requested molecule/method/operation/executable/resources')
        folder, raw = _raw_process(result, root, executable, 'job.inp', 'engine')
        if _raw_artifact(result, folder / 'job.inp', root).read_text() != _orca_input(molecule, method, resources, 'gradient'):
            raise IntegrityError('native gradient input differs from its exact requested compiled deck')
        version_folder, _ = _raw_process(result, root, executable, 'version.inp', 'version', key='version_probe_process')
        if (version_folder != folder or result.diagnostics.get('observed_probe_version') != ORCA_VERSION
                or _raw_artifact(result, folder / 'version.inp', root).read_text() != _orca_version_input(resources)):
            raise IntegrityError('native gradient independent version probe differs from its declared loader diagnostic')
        energy, gradient = parse_orca_engrad(_raw_artifact(result, folder / 'job.engrad', root), molecule)
        literals = re.findall(r'FINAL SINGLE POINT ENERGY\s+(' + _FLOAT + ')', raw)
        if (not literals or abs(_number(literals[-1]) - energy) > 2e-7
                or result.energy_hartree is None or abs(result.energy_hartree - energy) > 1e-10
                or result.gradient_hartree_per_bohr is None
                or not np.allclose(result.gradient_hartree_per_bohr, gradient, atol=1e-12, rtol=0)):
            raise IntegrityError('native gradient cache energy/gradient differs from actual raw derivatives')
        return energy, np.asarray(gradient, dtype=float)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        if isinstance(exc, IntegrityError):
            raise
        raise IntegrityError(f'incomplete native gradient cache evidence: {exc}') from exc


def _analysis_matches(stored: Any, actual: Any) -> bool:
    """Machine-precision comparison, with exact categorical validity gates."""
    if isinstance(actual, dict):
        return (isinstance(stored, dict) and set(stored) == set(actual)
                and all(_analysis_matches(stored[key], value) for key, value in actual.items()))
    if isinstance(actual, list):
        return (isinstance(stored, list) and len(stored) == len(actual)
                and all(_analysis_matches(a, b) for a, b in zip(stored, actual, strict=True)))
    if isinstance(actual, bool) or actual is None or isinstance(actual, str):
        return type(stored) is type(actual) and stored == actual
    return (isinstance(stored, (int, float)) and not isinstance(stored, bool)
            and np.isfinite(stored) and np.isclose(stored, actual, atol=1e-12, rtol=1e-12))


def verify_orca_hessian_result(result: EngineResult, molecule: Molecule, method: MethodSpec,
                               resources: ResourceLimits, root: str | Path, *, executable: str,
                               executable_sha256: str, gradient_threshold: float) -> dict[str, Any]:
    """Revalidate analytic-Hessian receipt and its independently observed gradient."""
    root = Path(root)
    md = result.metadata
    expected = {'schema': 'topos-native-orca-hessian/0.1.0', 'molecule': molecule.model_dump(mode='json'),
                'method': method.model_dump(mode='json'), 'gradient_threshold': gradient_threshold,
                'resources': resources.model_dump(exclude={'budget_seconds'}), 'executable_sha256': executable_sha256}
    try:
        if (result.status != 'completed' or result.engine != 'orca' or result.operation != 'hessian'
                or result.method != method.method or result.engine_version != ORCA_VERSION or result.molecule != molecule
                or md.get('execution_kind') != 'real' or md.get('requested_method') != method.model_dump(mode='json')
                or md.get('output_molecule') != molecule.model_dump(mode='json') or md.get('protocol') != expected
                or md.get('executable') != executable or md.get('executable_sha256') != executable_sha256):
            raise IntegrityError('native Hessian cache differs from its current molecule/method/operation/executable/protocol')
        derivative = EngineResult.model_validate(md['reference_gradient_result'])
        parent_artifacts = {a.path: (a.sha256, a.size_bytes, a.role) for a in result.artifacts}
        if any(parent_artifacts.get(a.path) != (a.sha256, a.size_bytes, a.role) for a in derivative.artifacts):
            raise IntegrityError('native Hessian cache does not retain its exact independent gradient artifacts')
        energy, gradient = verify_orca_gradient_result(derivative, molecule, method, resources, root,
                                                       executable=executable, executable_sha256=executable_sha256)
        folder, raw = _raw_process(result, root, executable, 'frequency.inp', 'frequency')
        if _raw_artifact(result, folder / 'frequency.inp', root).read_text() != orca_frequency_input(
                molecule, method, resources, check_cpu_affinity=False):
            raise IntegrityError('native Hessian cache input differs from its exact compiled analytic Freq deck')
        literals = re.findall(r'FINAL SINGLE POINT ENERGY\s+(' + _FLOAT + ')', raw)
        if not literals or abs(_number(literals[-1]) - energy) > 1e-7:
            raise IntegrityError('native frequency and independent gradient energies disagree')
        parsed = parse_orca_hessian(_raw_artifact(result, folder / 'frequency.hess', root), molecule)
        if (result.energy_hartree is None or abs(result.energy_hartree - energy) > 1e-10
                or result.gradient_hartree_per_bohr is None
                or not np.allclose(result.gradient_hartree_per_bohr, gradient, atol=1e-12, rtol=0)
                or not np.allclose(md['hessian_hartree_per_bohr2'], parsed['hessian_hartree_per_bohr2'], atol=1e-12, rtol=0)
                or any(not _analysis_matches(md.get(field), parsed[field]) for field in (
                    'native_masses_amu', 'native_coordinates_angstrom', 'native_to_requested_frame',
                    'native_coordinates_units', 'units', 'hessian_frame', 'mass_policy'))):
            raise IntegrityError('native Hessian cache scientific metadata differs from its physical raw derivatives')
        analysis = harmonic_analysis(molecule, parsed['hessian_hartree_per_bohr2'],
                                     gradient_hartree_per_bohr=gradient, gradient_threshold=gradient_threshold)
        if not _analysis_matches(md['analysis'], analysis) or result.converged is not analysis['stationary']:
            raise IntegrityError('native Hessian cache analysis/converged differs from its actual Hessian and gradient')
        return analysis
    except (KeyError, TypeError, ValueError, OSError) as exc:
        if isinstance(exc, IntegrityError):
            raise
        raise IntegrityError(f'incomplete native Hessian cache evidence: {exc}') from exc


def run_orca_hessian(molecule: Molecule, method: MethodSpec, resources: ResourceLimits,
                     workdir: str | Path, *, executable: str | Path | None = None,
                     process_runner: Callable[..., Any] | None = None,
                     cancel_event: Event | None = None, gradient_threshold: float = 1e-5) -> EngineResult:
    """Execute Engrad then independent Freq; no Hessian or success from absent data."""
    started = time.monotonic()
    result = EngineResult(status="unsupported", engine="orca", method=method.method, operation="hessian",
                          metadata={"execution_kind": "not-executed", "manual": FREQUENCY_MANUAL,
                                    "requested_method": method.model_dump(mode="json"),
                                    "derivative_kind": "native-analytic-SCF-Hessian",
                                    "analytic_restart_policy": "reuse completed hashed stages; restart interrupted Freq in fresh scratch"})
    def stopped() -> bool:
        return _derivative_stopped(result, resources, started, cancel_event, 'native Hessian')

    if stopped():
        return result
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
    if stopped():
        return result
    cached = _read_completed(folder / "completed.json", folder)
    if stopped():
        return result
    if cached is not None:
        verify_orca_hessian_result(cached, molecule, method, resources, folder, executable=binary,
                                   executable_sha256=protocol['executable_sha256'], gradient_threshold=gradient_threshold)
        separate = _read_completed(folder / 'reference.json', folder)
        if separate is None:
            raise IntegrityError('completed native Hessian lacks its separate gradient reference receipt')
        verify_orca_gradient_result(separate, molecule, method, resources, folder, executable=binary,
                                    executable_sha256=protocol['executable_sha256'])
        if separate.model_dump(mode='json') != cached.metadata['reference_gradient_result']:
            raise IntegrityError('completed native Hessian differs from its separate independent gradient receipt')
        if stopped():
            return result
        cached.metadata["reused_completed_hessian"] = True
        return cached
    result.metadata.update(executable=binary, executable_sha256=protocol["executable_sha256"], protocol=protocol)
    execute = process_runner or run_process

    def remaining() -> ResourceLimits:
        if stopped():
            if result.status == 'cancelled':
                raise InterruptedError(result.diagnostics['reason'])
            raise TimeoutError(result.diagnostics['reason'])
        seconds = resources.budget_seconds - (time.monotonic() - started)
        if seconds <= 0:
            raise TimeoutError("native Hessian budget exhausted")
        return resources.model_copy(update={"budget_seconds": seconds})

    try:
        reference = _read_completed(folder / "reference.json", folder)
        remaining()
        if reference is None:
            reference = run_engine(molecule, method, remaining(), folder / ("reference-" + uuid4().hex),
                                   operation="gradient", executable=binary, process_runner=process_runner,
                                   cancel_event=cancel_event)
            if reference.status == 'completed':
                verify_orca_gradient_result(reference, molecule, method, resources, folder, executable=binary,
                                            executable_sha256=protocol['executable_sha256'])
                atomic_json(folder / "reference.json", {"result": reference.model_dump(mode="json")})
        elif reference.status == 'completed':
            verify_orca_gradient_result(reference, molecule, method, resources, folder, executable=binary,
                                        executable_sha256=protocol['executable_sha256'])
        remaining()
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
        if stopped():
            return result
        result.elapsed_seconds = time.monotonic() - started
        atomic_json(folder / "completed.json", {"result": result.model_dump(mode="json")})
        if stopped():
            return result
        return result
    except InterruptedError as exc:
        result.status, result.diagnostics['reason'] = 'cancelled', str(exc)
        result.converged = False
        return result
    except TimeoutError as exc:
        result.status, result.diagnostics["reason"] = "timed-out", str(exc)
        result.converged = False
        return result
    except (ValueError, OSError) as exc:
        result.status, result.diagnostics["reason"] = "failed", str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - started
