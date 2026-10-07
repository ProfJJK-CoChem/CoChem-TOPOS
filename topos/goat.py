"""ORCA 6.1.1 native GOAT with retained evidence and mandatory refinement.

Input/ensemble conventions: ORCA 6.1 manual sections 4.10 and 3.5.2.
XTB2 means the external sibling ``otool_xtb``; Native-XTB2 is never substituted.
This adapter has input/parser tests; live licensed ORCA acceptance is separate.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable

from .chemistry import atomic_number
from .engines import (
    ORCA_VERSION,
    EngineParseError,
    _engine_version,
    _method_problem,
    _number,
    _orca_version_input,
    artifact_inventory,
)
from .models import MethodSpec, Molecule, ResourceLimits
from .runtime import run_process
from .sampling import SampledConformer, SamplingResult

GOAT_MANUAL = "https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/goat.html"
XTB_INTERFACE_MANUAL = "https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/semiempirical.html#extended-tight-binding-gfn0-xtb-gfn-xtb-gfn2-xtb"
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"


def goat_input(molecule: Molecule, method: MethodSpec, resources: ResourceLimits, *,
               energy_window_kcal_mol: float = 12.0, uphill_method: str | None = None,
               deterministic: bool = False, max_global_iterations: int = 100,
               entropy_options: dict[str, float] | None = None) -> str:
    """Render only documented GOAT/XTB2 or GOAT/r2SCAN-3c recipes."""
    problem = _method_problem(method, resources, "optimize")
    if problem:
        raise ValueError(problem)
    if (method.engine, method.method) not in {("xtb", "GFN2-xTB"), ("orca", "r2SCAN-3c"), ("orca", "r²SCAN-3c")}:
        raise ValueError("GOAT supports explicit external GFN2-xTB or native r2SCAN-3c profiles")
    if resources.memory_mb * .75 < 16 * resources.threads:
        raise ValueError("GOAT allocation cannot supply ORCA per-rank memory and driver reserve")
    if molecule.environment and molecule.environment != {"phase": "gas"}:
        raise ValueError("GOAT adapter requires a declared gas-phase environment")
    if any(isotope is not None for isotope in molecule.isotopes):
        raise ValueError("GOAT isotope-dependent filtering/degeneracy input is not validated")
    if isinstance(energy_window_kcal_mol, bool) or not math.isfinite(energy_window_kcal_mol) or energy_window_kcal_mol <= 0:
        raise ValueError("GOAT energy window must be finite positive kcal/mol")
    if not isinstance(deterministic, bool):
        raise ValueError("GOAT deterministic option must be boolean")
    if isinstance(max_global_iterations, bool) or not isinstance(max_global_iterations, int) or not 3 <= max_global_iterations <= 1000:
        raise ValueError("GOAT maximum global iterations must be an integer from 3 to 1000")
    if uphill_method not in {None, "GFN-FF"}:
        raise ValueError("Only an explicit GFN-FF uphill alternative is supported")
    if (method.engine == "xtb" or uphill_method == "GFN-FF") and any(atomic_number(symbol) > 86 for symbol in molecule.symbols):
        raise ValueError("The verified external xTB/force-field domain excludes elements beyond radon")
    theory = "XTB2" if method.engine == "xtb" else "r2SCAN-3c"
    if entropy_options is not None:
        if set(entropy_options) != {"temperature_k", "min_delta_s_cal_mol_k"} or any(
                isinstance(v, bool) or not math.isfinite(v) or v <= 0 for v in entropy_options.values()):
            raise ValueError("GOAT entropy requires explicit positive temperature and entropy stopping threshold")
    algorithm = "GOAT-ENTROPY" if entropy_options is not None else "GOAT"
    lines = [f"! {theory} {algorithm} TightOpt TightSCF DEFGRID3",
             f"%pal nprocs {resources.threads} end",
             f"%maxcore {max(16, int(resources.memory_mb * .75 / resources.threads))}",
             "%goat", "  NWORKERS 4", f"  MAXEN {energy_window_kcal_mol:.12g}",
             f"  RANDOMSEED {'false' if deterministic else 'true'}",
             "  MINGLOBALITER 3", f"  MAXGLOBALITER {max_global_iterations}", "  KEEPWORKERDATA true",
             "  CONFDEGEN auto"]
    if entropy_options is not None:
        lines.extend([f"  CONFTEMP {entropy_options['temperature_k']:.12g}",
                      f"  MINDELS {entropy_options['min_delta_s_cal_mol_k']:.12g}"])
    if uphill_method is not None:
        lines.append("  GFNUPHILL gfnff")
    lines.extend(["end", "%geom", "  EnforceStrictConvergence true", "end",
                  f"* xyz {molecule.charge} {molecule.multiplicity}"])
    lines.extend(f"{symbol} {xyz[0]:.16g} {xyz[1]:.16g} {xyz[2]:.16g}"
                 for symbol, xyz in zip(molecule.symbols, molecule.coordinates, strict=True))
    lines.extend(["*", ""])
    return "\n".join(lines)


def parse_goat_ensemble(path: str | Path, reference: Molecule) -> list[SampledConformer]:
    """Read complete native ``Energy <hartree>`` frames without remapping atoms.

    The documented READENSEMBLE convention is ``Energy (float)``. Unrecognized
    comments, altered atom order and truncated files are errors, not zero energy.
    Native energy and geometry remain observations requiring common refinement.
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    n, cursor, result = len(reference.symbols), 0, []
    while cursor < len(lines):
        if not lines[cursor].strip():
            cursor += 1
            continue
        if lines[cursor].strip() != str(n) or cursor + n + 2 > len(lines):
            raise EngineParseError("GOAT ensemble has changed atom count or an incomplete frame")
        comment = lines[cursor + 1].strip()
        match = re.fullmatch(r"Energy\s+(" + _FLOAT + r")(?:\s+(?:Eh|hartree))?", comment, re.I)
        if match is None:
            raise EngineParseError("GOAT frame lacks its documented Energy <hartree> comment")
        energy = _number(match.group(1))
        rows = [line.split() for line in lines[cursor + 2:cursor + n + 2]]
        if any(len(row) != 4 for row in rows) or [row[0] for row in rows] != reference.symbols:
            raise EngineParseError("GOAT changed element order or atom mapping")
        data = reference.model_dump()
        data["coordinates"] = [[_number(value) for value in row[1:]] for row in rows]
        result.append(SampledConformer(
            molecule=Molecule.model_validate(data), energy_hartree=energy,
            source_index=len(result) + 1, source="GOAT", metadata={
                "raw_comment": comment, "energy_units": "hartree", "energy_definition": "GOAT native search electronic energy",
                "validation_status": "requires-common-level-refinement", "stationary_point_classification": "unclassified",
                "atom_mapping": "native index order; complete element sequence checked",
            },
        ))
        cursor += n + 2
    if not result:
        raise EngineParseError("GOAT ensemble has no complete native frames")
    return result


def run_goat(molecule: Molecule, method: MethodSpec, resources: ResourceLimits,
             workdir: str | Path, seed: int | None = None, cancel_event: Event | None = None,
             executable: str | Path | None = None, *, xtb_executable: str | Path | None = None,
             profile: str = "goat-v1", energy_window_kcal_mol: float = 12.0,
             uphill_method: str | None = None, deterministic: bool = False,
             max_global_iterations: int = 100,
             entropy_options: dict[str, float] | None = None,
             process_runner: Callable[..., Any] | None = None) -> SamplingResult:
    """Execute native GOAT via a caller-supplied BASE runner, never as refinement.

    The audit-bound xTB executable must byte-match ORCA's sibling ``otool_xtb``
    whenever external xTB or GFN-FF is used. This adapter neither installs nor
    copies binaries. Process deadlines include probes and native search.
    """
    started = time.monotonic()
    execute = process_runner or run_process
    result = SamplingResult(status="unsupported", engine="orca", algorithm="GOAT", method=method.method,
                            potential_engine=method.engine, metadata={
        "execution_kind": "not-executed", "profile": profile, "refinement_profile": method.profile_id,
        "potential_spec": method.model_dump(), "resources": resources.model_dump(),
        "requested_seed": seed, "effective_seed": None,
        "randomness": "native RANDOMSEED false; numerical differences may remain" if deterministic else "engine-controlled random initialization",
        "uphill_method": uphill_method or method.method, "downhill_method": method.method,
        "native_energy_window_kcal_mol": energy_window_kcal_mol,
        "native_optimization": "TightOpt and explicit EnforceStrictConvergence true; separate common-level refinement required",
        "degeneracy": "native CONFDEGEN auto is retained as native sampling provenance; not copied into TOPOS population weights",
        "nworkers": 4, "worker_allocation": "ORCA schedules four logical workers within the total PAL allocation",
        "max_global_iterations": max_global_iterations, "exhaustive": False,
        "method_reference": "https://doi.org/10.1002/anie.202500393",
        "manuals": [GOAT_MANUAL, XTB_INTERFACE_MANUAL],
        "adapter_validation": "input/parser tested; live ORCA 6.1.1 acceptance pending",
    })
    try:
        if profile != "goat-v1" or seed is not None:
            raise ValueError("Select goat-v1; native RANDOMSEED is boolean, not a numeric TOPOS seed")
        deck = goat_input(molecule, method, resources, energy_window_kcal_mol=energy_window_kcal_mol,
                          uphill_method=uphill_method, deterministic=deterministic,
                          max_global_iterations=max_global_iterations, entropy_options=entropy_options)
    except (ValueError, TypeError) as exc:
        result.diagnostics["reason"] = str(exc)
        return result
    if entropy_options is not None:
        result.algorithm = "GOAT-ENTROPY"
        result.metadata["entropy_options"] = entropy_options
    orca = shutil.which(str(executable) if executable is not None else os.environ.get("TOPOS_ORCA_EXECUTABLE", "orca"))
    if orca is None:
        result.status, result.diagnostics["reason"] = "unavailable", "Requested ORCA executable is missing"
        return result
    binary = Path(orca).resolve()
    need_xtb = method.engine == "xtb" or uphill_method == "GFN-FF"
    xtb = None
    if need_xtb:
        xtb = shutil.which(str(xtb_executable) if xtb_executable is not None else os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
        helper = binary.parent / "otool_xtb"
        if xtb is None or not helper.is_file() or not os.access(helper, os.X_OK):
            result.status, result.diagnostics["reason"] = "unavailable", "External xTB and executable ORCA-sibling otool_xtb are required"
            return result
        expected_digest = hashlib.sha256(Path(xtb).read_bytes()).hexdigest()
        if hashlib.sha256(helper.read_bytes()).hexdigest() != expected_digest:
            result.status, result.diagnostics["reason"] = "unavailable", "ORCA otool_xtb differs from the explicitly audited xTB executable"
            return result
        result.metadata.update(xtb_executable=str(Path(xtb).resolve()), xtb_sha256=expected_digest,
                               otool_xtb=str(helper), otool_xtb_sha256=expected_digest)
    folder = Path(workdir).resolve()
    if folder.exists() and any(folder.iterdir()):
        result.status, result.diagnostics["reason"] = "failed", "GOAT requires a fresh attempt directory"
        return result
    folder.mkdir(parents=True, exist_ok=True)
    result.metadata.update(executable=str(binary), executable_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    try:
        def limits(probe: bool = False):
            remaining = resources.budget_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("GOAT invocation budget exhausted")
            return resources.model_copy(update={"threads": 1 if probe else resources.threads,
                                                 "budget_seconds": min(10, remaining) if probe else remaining})

        if need_xtb:
            probe = execute([str(Path(xtb).resolve()), "--version"], folder, limits(True),
                            cancel_event=cancel_event, log_prefix="xtb-version")
            result.diagnostics["xtb_probe"] = probe.to_dict()
            text = Path(probe.stdout_path).read_text(errors="replace") + Path(probe.stderr_path).read_text(errors="replace")
            xtb_version = _engine_version(text, "xtb")
            if probe.status != "completed" or xtb_version != "6.7.1":
                result.status = probe.status if probe.status in {"cancelled", "timed-out"} else "unavailable"
                result.diagnostics["reason"] = "Audited xTB 6.7.1 probe did not complete"
                return result
            result.metadata["uphill_xtb_version"] = xtb_version
            if method.engine == "xtb":
                result.potential_engine_version = xtb_version
                if method.engine_version is not None and method.engine_version != xtb_version:
                    raise ValueError("Requested xTB version differs from the verified external potential")
        (folder / "version.inp").write_text(_orca_version_input(resources), encoding="utf-8")
        probe = execute([str(binary), "version.inp"], folder, limits(True), cancel_event=cancel_event, log_prefix="version")
        result.diagnostics["orca_probe"] = probe.to_dict()
        probe_text = Path(probe.stdout_path).read_text(errors="replace")
        version = _engine_version(probe_text, "orca")
        if probe.status != "completed" or version != ORCA_VERSION or not all(marker in probe_text for marker in (
                "ORCA TERMINATED NORMALLY", "SCF CONVERGED AFTER", "FINAL SINGLE POINT ENERGY")) or "SCF NOT CONVERGED" in probe_text:
            result.status = probe.status if probe.status in {"cancelled", "timed-out"} else "unavailable"
            result.diagnostics["reason"] = "ORCA 6.1.1 serial loader/version diagnostic did not complete"
            return result
        energies = re.findall(r"FINAL SINGLE POINT ENERGY\s+(" + _FLOAT + ")", probe_text)
        if not energies:
            raise EngineParseError("ORCA diagnostic lacks a finite electronic energy")
        _number(energies[-1])
        result.engine_version = version
        result.metadata["version_probe"] = {"purpose": "serial He/HF/STO-3G loader diagnostic", "scientific_result_eligibility": False}
        if method.engine == "orca":
            result.potential_engine_version = version
            if method.engine_version is not None and method.engine_version != version:
                raise ValueError("Requested ORCA version differs from the verified potential")
        (folder / "goat.inp").write_text(deck, encoding="utf-8")
        result.command = [str(binary), "goat.inp"]
        result.metadata["execution_kind"] = "real"
        process = execute(result.command, folder, limits(), cancel_event=cancel_event,
                          log_prefix="goat", threads_per_process=1)
        result.diagnostics["process"] = process.to_dict()
        result.status = process.status
        raw = Path(process.stdout_path).read_text(errors="replace")
        ensemble = folder / "goat.finalensemble.xyz"
        if ensemble.is_file():
            try:
                result.ensemble = parse_goat_ensemble(ensemble, molecule)
            except (ValueError, OSError) as exc:
                if process.status == "completed":
                    raise
                result.diagnostics["partial_ensemble_parse_error"] = str(exc)
        if process.status != "completed":
            result.diagnostics["reason"] = process.reason
            return result
        if _engine_version(raw, "orca") != version or "ORCA TERMINATED NORMALLY" not in raw:
            raise EngineParseError("Native GOAT version or normal termination is unverified")
        if "Writing final ensemble to" not in raw or not result.ensemble:
            raise EngineParseError("Native GOAT did not produce its complete final ensemble")
        windows = re.findall(r"Maximum Conf\. Energy\s*\.\.\.\s*(" + _FLOAT + r")\s+kcal/mol", raw)
        if not windows or abs(_number(windows[-1]) - energy_window_kcal_mol) > 5e-4:
            raise EngineParseError("Native GOAT energy window differs from the explicit request")
        minima = re.findall(r"Lowest energy conformer\s*:\s*(" + _FLOAT + r")\s+Eh", raw)
        if not minima or abs(_number(minima[-1]) - min(frame.energy_hartree for frame in result.ensemble)) > 1e-5:
            raise EngineParseError("Native GOAT ensemble energy disagrees with its final summary")
        result.converged = bool(re.search(r"Global minimum found\s*!", raw, re.I))
        if not result.converged:
            result.status = "partial"
            result.diagnostics["reason"] = "Native GOAT convergence marker absent; ensemble retained for separate review/refinement"
        if entropy_options is not None:
            from .entropy import parse_goat_entropy

            result.metadata["native_entropy"] = parse_goat_entropy(raw, entropy_options["temperature_k"])
        result.metadata["termination_scope"] = "native finite GOAT stopping criterion; not proof of a global minimum or exhaustive ensemble"
        if need_xtb and hashlib.sha256((binary.parent / "otool_xtb").read_bytes()).hexdigest() != result.metadata["otool_xtb_sha256"]:
            raise EngineParseError("ORCA xTB helper identity changed during execution")
        return result
    except TimeoutError as exc:
        result.status, result.diagnostics["reason"] = "timed-out", str(exc)
        return result
    except (ValueError, OSError) as exc:
        result.status, result.diagnostics["reason"] = "failed", str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - started
        try:
            result.artifacts = artifact_inventory(folder)
        except (OSError, EngineParseError) as exc:
            result.status, result.diagnostics["artifact_error"] = "failed", str(exc)
