"""Native CREST 3.0.2 operations on supplied, attributable ensembles.

``--screen`` is a GFN2-xTB multilevel optimization, with native CREGEN
screening between stages. Its energies require subsequent QM refinement.
``--cregen`` only compares supplied structures and energies. Its ENSO tags
retain the exact supplied comment after the unique XYZ output rounds energies
to eight decimals. We verify those tags before returning source energies.

Native algorithm details were checked against the v3.0.2 source:
src/confparse.f90, src/legacy_algos/confscript3.f90 and src/cregen.f90.
CREGEN's bthr is an adaptive base, and its default RMSD includes reflection.
Opposite-handed input pairs and isotope-dependent comparisons are rejected.
No native population or degeneracy is promoted to a TOPOS thermodynamic result.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable

import numpy as np

from .base_integration import BaseIntegrationError, BaseRuntime
from .engines import EngineParseError, _number, artifact_inventory, write_xyz
from .models import ResourceLimits
from .runtime import available_cpu_count
from .sampling import SampledConformer, SamplingResult, parse_crest_ensemble
from .science import _proper_rmsd

_TAG = re.compile(r"^\s*(\S+)\s+!topos_([0-9]{8})\s*$")
_SOURCE = "https://github.com/crest-lab/crest/tree/v3.0.2/src"


def _positive(value: Any) -> bool:
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _input_problem(frames: list[SampledConformer], resources: ResourceLimits,
                   operation: str, rmsd_threshold: float, *, deadline: float,
                   cancel_event: Event | None) -> str | None:
    if not frames or len(frames) > 99_999_999:
        return "a nonempty supplied ensemble with representable provenance tags is required"
    if not all(isinstance(frame, SampledConformer) for frame in frames):
        return "supplied frames must be typed SampledConformer records"
    if resources.device != "cpu" or resources.threads > available_cpu_count():
        return "native CREST requires threads within the current CPU allocation"
    if not _positive(resources.budget_seconds):
        return "a finite positive wall-clock budget is required"
    reference = frames[0].molecule
    identity = reference.model_dump(exclude={"coordinates", "name"})
    if any(isotope is not None for isotope in reference.isotopes):
        return "native CREGEN isotope-mass rotational constants are not validated; isotope labels cannot be ignored"
    if operation == "screen" and reference.environment not in ({}, {"phase": "gas"}):
        return "the native GFN2-xTB screen supports explicit gas phase only"
    from .chemistry import atomic_number

    if operation == "screen" and any(atomic_number(s) > 86 for s in reference.symbols):
        return "GFN2-xTB excludes elements beyond radon"
    for frame in frames:
        if not math.isfinite(frame.energy_hartree):
            return "every input frame requires a finite supplied electronic energy in hartree"
        if frame.molecule.model_dump(exclude={"coordinates", "name"}) != identity:
            return "input frames must share atom order/IDs, charge, spin, isotopes, fragments, bonds, stereo and environment"
    # Native CREGEN uses min(RMSD(proper), RMSD(reflected)). Its native
    # threshold may reach 2*rthr, so reject any pair that could be merged only
    # through reflection. This conservative gate intentionally includes close
    # conformational enantiomers without claiming stereocenter assignment.
    for i, frame in enumerate(frames):
        a = np.asarray(frame.molecule.coordinates)
        for earlier in frames[:i]:
            if cancel_event is not None and cancel_event.is_set():
                return "cancelled during supplied-ensemble comparison preflight"
            if time.monotonic() >= deadline:
                return "wall-clock budget exhausted during supplied-ensemble comparison preflight"
            b = np.asarray(earlier.molecule.coordinates)
            if _proper_rmsd(a, b) <= rmsd_threshold:
                continue
            reflected = b.copy()
            reflected[:, 0] *= -1
            if _proper_rmsd(a, reflected) < 2 * rmsd_threshold:
                return "native CREGEN reflection matching could merge opposite-handed input geometries"
    return None


def _write_supplied(frames: list[SampledConformer], folder: Path) -> None:
    # Original metadata and electronic values are durable even when native
    # screening changes geometry, removes frames, or drops arbitrary comments.
    (folder / "supplied-ensemble.json").write_text(json.dumps(
        [frame.model_dump(mode="json") for frame in frames], indent=2, allow_nan=False
    ) + "\n", encoding="utf-8")
    with (folder / "ensemble.xyz").open("x", encoding="utf-8") as stream:
        for position, frame in enumerate(frames, 1):
            stream.write(f"{len(frame.molecule.symbols)}\n{frame.energy_hartree:.17g} !topos_{position:08d}\n")
            for symbol, xyz in zip(frame.molecule.symbols, frame.molecule.coordinates, strict=True):
                stream.write(symbol + " " + " ".join(format(x, ".17g") for x in xyz) + "\n")
    # Native topology comparison must use the lowest supplied structure, not
    # whichever source file happened to be merged first.
    write_xyz(min(frames, key=lambda frame: frame.energy_hartree).molecule, folder / "input.xyz")


def parse_cregen_result(
    ensemble_path: str | Path,
    tags_path: str | Path,
    inputs: list[SampledConformer],
    comparison_protocol: str,
) -> list[SampledConformer]:
    """Verify native representatives against ENSO tags and their source geometry.

    Input energies remain exact authoritative values; the raw rounded native
    energy is kept separately. Atom-index-preserving proper alignment checks
    reject altered geometry, atom remapping and any native fallback structure.
    ``source_index`` retains the caller's index; ``input_position`` is the
    one-based position used in the unique native provenance tag.
    """
    if not inputs or not comparison_protocol.strip():
        raise EngineParseError("supplied ensemble and a common comparison protocol are required")
    parsed = parse_crest_ensemble(ensemble_path, inputs[0].molecule)
    tags = Path(tags_path).read_text(encoding="utf-8").splitlines()
    if len(tags) != len(parsed):
        raise EngineParseError("native CREGEN ENSO tag count differs from the selected frame count")
    seen: set[int] = set()
    for native, tag in zip(parsed, tags, strict=True):
        match = _TAG.fullmatch(tag)
        if match is None:
            raise EngineParseError("native CREGEN lost the original supplied-energy provenance tag")
        position = int(match.group(2))
        if not 1 <= position <= len(inputs) or position in seen:
            raise EngineParseError("native CREGEN returned an unknown or repeated input provenance tag")
        seen.add(position)
        original = inputs[position - 1]
        if _number(match.group(1)) != original.energy_hartree:
            raise EngineParseError("native CREGEN changed the supplied electronic energy")
        if not math.isclose(native.energy_hartree, original.energy_hartree, rel_tol=0, abs_tol=5.1e-9):
            raise EngineParseError("native CREGEN energy disagrees with its source beyond native print rounding")
        if _proper_rmsd(np.asarray(native.molecule.coordinates), np.asarray(original.molecule.coordinates)) > 5e-8:
            raise EngineParseError("native CREGEN changed geometry or atom mapping rather than rigidly aligning it")
        native_energy = native.energy_hartree
        native.energy_hartree = original.energy_hartree
        native.source_index = original.source_index
        native.source = "CREST-CREGEN"
        native.metadata.update({
            "input_position": position, "input_source_index": original.source_index,
            "input_source": original.source, "input_metadata": original.metadata,
            "native_rounded_energy_hartree": native_energy, "native_enso_tag": tag.strip(),
            "energy_definition": "unchanged supplied common-level electronic energy",
            "comparison_protocol": comparison_protocol,
            "validation_status": "native-selection; caller supplies common-level validation",
            "atom_mapping": "native index order; source tag and proper-alignment geometry verified",
        })
    return parsed


def _run_native(
    frames: list[SampledConformer], resources: ResourceLimits, workdir: str | Path,
    *, operation: str, executable: str | Path | None, xtb_executable: str | Path | None,
    process_runner: Callable[..., Any] | None, cancel_event: Event | None,
    comparison_protocol: str | None, energy_window_kcal_mol: float,
    energy_threshold_kcal_mol: float, rotational_threshold: float, rmsd_threshold_angstrom: float,
) -> SamplingResult:
    start = time.monotonic()
    result = SamplingResult(
        status="unsupported", algorithm="CREST-screen" if operation == "screen" else "CREGEN",
        method="GFN2-xTB" if operation == "screen" else "supplied-common-level",
        potential_engine="xtb" if operation == "screen" else "none; supplied energies only",
        metadata={
            "execution_kind": "not-executed", "operation": operation,
            "resources": resources.model_dump(), "supplied_frame_count": len(frames),
            "comparison_protocol": comparison_protocol, "native_source": _SOURCE,
            "exhaustive": False, "reoptimizes_geometry": operation == "screen",
            "native_enantiomer_policy": "native reflection comparison; potentially affected input pairs rejected",
            "native_threshold_semantics": "CREGEN 3.0.2 adaptive rotational comparison; bthr is the requested base, native bthrmax=0.025",
            "thermodynamic_claims": "native electronic-energy weights and counts are not validated TOPOS populations/degeneracies",
        },
    )
    if not all(_positive(value) for value in (
        energy_window_kcal_mol, energy_threshold_kcal_mol, rotational_threshold, rmsd_threshold_angstrom
    )):
        result.diagnostics["reason"] = "native comparison thresholds must be finite positive values"
        return result
    result.metadata.update(native_energy_window_kcal_mol=energy_window_kcal_mol,
                           native_energy_threshold_kcal_mol=energy_threshold_kcal_mol,
                           native_rotational_threshold=rotational_threshold,
                           native_rmsd_threshold_angstrom=rmsd_threshold_angstrom)
    problem = _input_problem(frames, resources, operation, rmsd_threshold_angstrom,
                             deadline=start + resources.budget_seconds, cancel_event=cancel_event)
    if problem:
        result.diagnostics["reason"] = problem
        if problem.startswith("cancelled"):
            result.status = "cancelled"
        elif problem.startswith("wall-clock budget"):
            result.status = "timed-out"
        result.elapsed_seconds = time.monotonic() - start
        return result
    if operation == "cregen" and (not isinstance(comparison_protocol, str) or not comparison_protocol.strip()):
        result.diagnostics["reason"] = "CREGEN requires an explicit supplied common-level comparison protocol"
        return result
    folder = Path(workdir).resolve()
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        result.status = "failed"
        result.diagnostics["reason"] = "fresh native ensemble attempt directory required"
        return result
    try:
        if process_runner is None:
            base = BaseRuntime()
            base.validate_resources(resources)
            crest = base.resolve_executable("crest", executable)
            xtb = base.resolve_executable("xtb", xtb_executable) if operation == "screen" else None
            execute = base.run_process
            result.metadata["execution_backend"] = base.provenance()
        else:
            execute = process_runner
            crest = shutil.which(str(executable or os.environ.get("TOPOS_CREST_EXECUTABLE", "crest")))
            xtb = (shutil.which(str(xtb_executable or os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb")))
                   if operation == "screen" else None)
            result.metadata["execution_backend"] = {"backend": "explicit-injected-runner"}
        if crest is None or (operation == "screen" and xtb is None):
            result.status = "unavailable"
            result.diagnostics["reason"] = "required authentic CREST/xTB executable is unavailable"
            return result
        crest = str(Path(crest).resolve())
        xtb = str(Path(xtb).resolve()) if xtb else None
        if xtb and not re.fullmatch(r"[/A-Za-z0-9_.+-]+", xtb):
            result.diagnostics["reason"] = "xTB path is unsafe for native CREST shell calls"
            return result
        folder.mkdir(parents=True, exist_ok=True)
        _write_supplied(frames, folder)
        (folder / "operation.json").write_text(json.dumps(result.metadata, indent=2, allow_nan=False) + "\n")
        for label, binary, pattern, version in [
            ("crest", crest, r"(?im)^\s*crest\s+(\d+\.\d+\.\d+)\s*$", "3.0.2"),
            *(([("xtb", xtb, r"xtb version\s+(\d+\.\d+\.\d+)", "6.7.1")]) if xtb else []),
        ]:
            result.metadata[f"{label}_executable"] = binary
            result.metadata[f"{label}_sha256"] = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
            remaining = resources.budget_seconds - (time.monotonic() - start)
            if remaining <= 0:
                result.status = "timed-out"
                result.diagnostics["reason"] = "native ensemble budget exhausted during preflight"
                return result
            probe = execute([binary, "--version"], folder,
                            resources.model_copy(update={"threads": 1, "budget_seconds": min(10, remaining)}),
                            cancel_event=cancel_event, log_prefix=f"{label}-version")
            if probe.status in {"cancelled", "timed-out"}:
                result.status = probe.status
                result.diagnostics["reason"] = probe.reason
                return result
            raw = Path(probe.stdout_path).read_text(errors="replace") + Path(probe.stderr_path).read_text(errors="replace")
            match = re.search(pattern, raw, re.I)
            if probe.status != "completed" or match is None:
                result.status = "unavailable"
                result.diagnostics["reason"] = f"{label} version identity is not established"
                return result
            if label == "crest":
                result.engine_version = match.group(1)
            else:
                result.potential_engine_version = match.group(1)
            if match.group(1) != version:
                result.diagnostics["reason"] = f"{label} version outside validated native profile ({version})"
                return result
        molecule = frames[0].molecule
        command = [crest, "input.xyz", "--" + operation, "ensemble.xyz",
                   "--chrg", str(molecule.charge), "--uhf", str(molecule.multiplicity - 1),
                   "-T", str(resources.threads), "--ewin", format(energy_window_kcal_mol, ".12g"),
                   "--ethr", format(energy_threshold_kcal_mol, ".12g"),
                   "--bthr", format(rotational_threshold, ".12g"),
                   "--rthr", format(rmsd_threshold_angstrom, ".12g")]
        if operation == "screen":
            command.extend(["--gfn2", "--legacy", "--xnam", xtb, "--keepdir"])
            result.metadata["native_schedule"] = "initial reference optimization; crude, loose, very-tight ensemble optimization with intermediate CREGEN screens"
            result.metadata["native_artifact_retention"] = "native screen removes OPTIM child directories; all surviving raw files are inventoried"
        else:
            command.append("--enso")
        result.command = command
        remaining = resources.budget_seconds - (time.monotonic() - start)
        if remaining <= 0:
            result.status = "timed-out"
            result.diagnostics["reason"] = "native ensemble budget exhausted during preflight"
            return result
        result.metadata["execution_kind"] = "real"
        process = execute(command, folder, resources.model_copy(update={"budget_seconds": remaining}),
                          cancel_event=cancel_event, log_prefix=operation)
        result.status = process.status
        result.diagnostics["process"] = process.to_dict()
        if process.status != "completed":
            result.diagnostics["reason"] = process.reason
            return result
        raw = Path(process.stdout_path).read_text(errors="replace")
        if "CREST terminated normally." not in raw:
            raise EngineParseError("native CREST normal termination is not established")
        markers = ({
            "1. crude pre-optimization", "2. optimization with loose thresholds",
            "3. optimization with very tight thresholds", "Use of GFN2-xTB requested", xtb,
        } if operation == "screen" else {"Using only the cregen sorting routine."})
        if any(marker not in raw for marker in markers):
            raise EngineParseError("native log does not confirm the requested operation and its stages")
        native_thresholds = {}
        for name, pattern, requested in (
            ("energy_window_kcal_mol", r"sorting energy window \(EWIN\)\s*:\s*([0-9.]+)", energy_window_kcal_mol),
            ("rmsd_threshold_angstrom", r"RMSD threshold\s*:\s*([0-9.]+)", rmsd_threshold_angstrom),
            ("rotational_threshold", r"Bconst threshold\s*:\s*([0-9.]+)", rotational_threshold),
            ("energy_threshold_kcal_mol", r"(?m)^\s*--ethr\s+([0-9.eE+-]+)\s*$", energy_threshold_kcal_mol),
        ):
            matches = re.findall(pattern, raw)
            if not matches or not math.isclose(float(matches[-1]), requested, rel_tol=0, abs_tol=5.1e-5):
                raise EngineParseError(f"native log does not confirm the requested {name}")
            native_thresholds[name] = float(matches[-1])
        result.diagnostics["native_screening"] = native_thresholds
        if operation == "screen":
            result.ensemble = parse_crest_ensemble(folder / "crest_ensemble.xyz", molecule)
            for frame in result.ensemble:
                frame.source = "CREST-screen"
                frame.metadata.update(energy_definition="native GFN2-xTB screen electronic energy",
                                      supplied_ensemble_artifact="supplied-ensemble.json",
                                      validation_status="requires-common-level-refinement")
        else:
            result.ensemble = parse_cregen_result(folder / "crest_ensemble.xyz", folder / "enso.tags",
                                                 frames, comparison_protocol)
            # Retain and validate the complete native conformer/rotamer file,
            # whose numeric comments have greater precision than unique XYZ.
            sorted_frames = parse_crest_ensemble(folder / "ensemble.xyz.sorted", molecule)
            result.metadata["native_sorted_frame_count"] = len(sorted_frames)
        result.converged = True
        result.metadata["returned_frame_count"] = len(result.ensemble)
        result.metadata["convergence_scope"] = "native operation terminated normally; no exhaustive-search or minimum classification claim"
        return result
    except BaseIntegrationError as exc:
        result.status = "unavailable"
        result.diagnostics["reason"] = str(exc)
        return result
    except (OSError, ValueError) as exc:
        result.status = "failed"
        result.diagnostics["reason"] = str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - start
        if folder.is_dir():
            try:
                result.artifacts = artifact_inventory(folder)
            except (OSError, EngineParseError) as exc:
                result.status = "failed"
                result.diagnostics["artifact_error"] = str(exc)
        if result.status != "completed":
            result.converged = False if result.metadata["execution_kind"] == "real" else None
        for frame in result.ensemble:
            frame.metadata.update(adapter_attempt_status=result.status,
                                  partial_native_attempt=result.status != "completed")


def run_crest_screen(
    frames: list[SampledConformer], resources: ResourceLimits, workdir: str | Path,
    *, executable: str | Path | None = None, xtb_executable: str | Path | None = None,
    process_runner: Callable[..., Any] | None = None, cancel_event: Event | None = None,
    energy_window_kcal_mol: float = 12.0,
) -> SamplingResult:
    """Run native GFN2-xTB screening before common-level QM refinement.

    The caller establishes provenance and a common energy scale for the supplied
    inputs. Default public execution requires the mandatory BASE/TOPOS/TORQ
    installation and BASE audited runtime. An explicit process runner supports
    development with genuine native executables; no alternate science is used.
    """
    return _run_native(
        frames, resources, workdir, operation="screen", executable=executable,
        xtb_executable=xtb_executable, process_runner=process_runner, cancel_event=cancel_event,
        comparison_protocol=None, energy_window_kcal_mol=energy_window_kcal_mol,
        energy_threshold_kcal_mol=.05, rotational_threshold=.01, rmsd_threshold_angstrom=.125,
    )


def run_cregen(
    frames: list[SampledConformer], resources: ResourceLimits, workdir: str | Path,
    *, comparison_protocol: str, executable: str | Path | None = None,
    process_runner: Callable[..., Any] | None = None, cancel_event: Event | None = None,
    energy_window_kcal_mol: float = 12.0, energy_threshold_kcal_mol: float = .05,
    rotational_threshold: float = .001, rmsd_threshold_angstrom: float = .125,
) -> SamplingResult:
    """Run native CREGEN on externally validated, common-level energy records.

    This never launches xTB or replaces QM energies. The comparison protocol is
    a caller-supplied common-level identity, not independently proven by CREGEN.
    The default bthr=.001 is the method matrix reporting-stage setting.
    """
    return _run_native(
        frames, resources, workdir, operation="cregen", executable=executable, xtb_executable=None,
        process_runner=process_runner, cancel_event=cancel_event, comparison_protocol=comparison_protocol,
        energy_window_kcal_mol=energy_window_kcal_mol, energy_threshold_kcal_mol=energy_threshold_kcal_mol,
        rotational_threshold=rotational_threshold, rmsd_threshold_angstrom=rmsd_threshold_angstrom,
    )
