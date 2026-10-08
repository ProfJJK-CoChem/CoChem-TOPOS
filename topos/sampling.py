"""Authentic CREST 3.0.2 iMTD-GC search through an explicit xTB 6.7.1 backend.

CREST's engine-controlled random initialization is not a TOPOS numeric seed.
Its ensemble energies are search observations, not common-level validated
conformer energies, populations, minimum classifications or exhaustiveness.
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

from pydantic import Field

from .engines import EngineParseError, _method_problem, _number, artifact_inventory, write_xyz
from .models import Artifact, Contract, ExecutionStatus, MethodSpec, Molecule, ResourceLimits
from .runtime import available_cpu_count, run_process

CREST_PROFILES = {
    "crest-imtdgc-v1": [],
    "crest-mquick-v1": ["--mquick"],
    "crest-entropy-v1": ["--entropy"],
    "crest-v4-v1": ["--v4"],
    # The method matrix's independent NCI search. These are requested settings,
    # never a recovery switch after an iMTD-GC failure.
    "crest-nci-v1": ["--nocross", "--noreftopo"],
}


class SampledConformer(Contract):
    molecule: Molecule
    energy_hartree: float
    source_index: int = Field(ge=1)
    source: str = "CREST"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SamplingResult(Contract):
    status: ExecutionStatus
    engine: str = "crest"
    algorithm: str = "iMTD-GC"
    method: str = "GFN2-xTB"
    engine_version: str | None = None
    potential_engine: str = "xtb"
    potential_engine_version: str | None = None
    ensemble: list[SampledConformer] = Field(default_factory=list)
    converged: bool | None = None
    command: list[str] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    elapsed_seconds: float = 0.0
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


def parse_crest_ensemble(path: str | Path, reference: Molecule) -> list[SampledConformer]:
    """Read every complete native XYZ frame; reject truncated or remapped records.

    The native comment's first token is the electronic energy in hartree. The
    complete comment is retained. CREST output precision is not inflated.
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    n, cursor, result = len(reference.symbols), 0, []
    while cursor < len(lines):
        if not lines[cursor].strip():
            cursor += 1
            continue
        if lines[cursor].strip() != str(n) or cursor + n + 2 > len(lines):
            raise EngineParseError("CREST ensemble has incompatible atom count or incomplete frame")
        comment = lines[cursor + 1].strip()
        if not comment:
            raise EngineParseError("CREST ensemble frame lacks its native electronic energy")
        try:
            energy = _number(comment.split()[0])
        except ValueError as exc:
            raise EngineParseError("CREST energy comment is not a finite hartree value") from exc
        rows = [line.split() for line in lines[cursor + 2:cursor + n + 2]]
        if any(len(row) != 4 for row in rows) or [row[0] for row in rows] != reference.symbols:
            raise EngineParseError("CREST changed atom count, element identity, or mapping")
        data = reference.model_dump()
        try:
            data["coordinates"] = [[_number(v) for v in row[1:]] for row in rows]
        except ValueError as exc:
            raise EngineParseError("CREST ensemble coordinates are not finite angstrom values") from exc
        result.append(SampledConformer(molecule=Molecule.model_validate(data), energy_hartree=energy,
                                       source_index=len(result) + 1, metadata={
                                           "raw_comment": comment,
                                           "energy_units": "hartree",
                                           "energy_definition": "CREST native search electronic energy",
                                           "validation_status": "requires-common-level-refinement",
                                           "stationary_point_classification": "unclassified",
                                           "atom_mapping": "native index order; element sequence checked",
                                       }))
        cursor += n + 2
    if not result:
        raise EngineParseError("CREST ensemble contains no complete structures")
    return result


def run_crest(
    molecule: Molecule,
    method: MethodSpec,
    resources: ResourceLimits,
    workdir: str | Path,
    seed: int | None = None,
    cancel_event: Event | None = None,
    executable: str | Path | None = None,
    *,
    xtb_executable: str | Path | None = None,
    profile: str = "crest-imtdgc-v1",
    nci: bool = False,
    energy_window_kcal_mol: float = 6.0,
    process_runner: Callable[..., Any] | None = None,
    entropy_options: dict[str, float] | None = None,
) -> SamplingResult:
    """Run CREST without fallback; native randomness is disclosed, never invented.

    MethodSpec defines the potential; its profile_id is the *subsequent TOPOS
    refinement* profile. The separate ``profile`` argument selects CREST's own
    search/optimization schedule. ``crest-nci-v1`` requires declared fragments
    and explicit confinement; it disables crossing and the *initial* topology
    check, not TOPOS's later chemistry checks. The native screening window is
    passed explicitly, including for reduced profiles with narrower defaults.
    Every sampled frame returned by CREST is retained, independently
    of a later TOPOS refinement cap. Native constraints/solvation are unsupported.
    """
    start = time.monotonic()
    execute_process = process_runner or run_process
    result = SamplingResult(status="unsupported", method=method.method,
                            algorithm={"crest-mquick-v1": "CREST-mquick",
                                       "crest-v4-v1": "iMTD-sMTD",
                                       "crest-nci-v1": "iMTD-NCI (no genetic crossing)"}.get(profile, "iMTD-GC"),
                            metadata={"execution_kind": "not-executed", "profile": profile,
                                      "requested_seed": seed, "effective_seed": None,
                                      "randomness": "engine-controlled; numeric seed unavailable in this adapter",
                                      "exhaustive": False,
                                      "refinement_profile": method.profile_id,
                                      "potential_spec": method.model_dump(),
                                      "resources": resources.model_dump(),
                                      "thread_allocation": "CREST 3.0.2 new_ompautoset distributes total -T between jobs and per-job cores",
                                      "nci_confinement": nci,
                                      "nci_semantics": "ellipsoidal potential biases sampling; native ensemble must be refined",
                                      "ancillary_methods": ["GFN0-xTB WBO/flexibility estimation"],
                                      "sampling_schedule": "native CREST 3.0.2 schedule; see archived logs",
                                      "disabled_native_stages": (
                                          ["normal MD", "genetic crossing"] if profile == "crest-mquick-v1"
                                          else ["genetic crossing"] if profile in {"crest-nci-v1", "crest-v4-v1"} else []),
                                      "initial_topology_check": profile != "crest-nci-v1",
                                      "topology_check_semantics": "noreftopo disables initial native checking only; later TOPOS chemistry validation is required",
                                      "reduced_search": profile == "crest-mquick-v1"})
    if profile == "crest-entropy-v1":
        if entropy_options is None:
            entropy_options = {"temperature_k": 298.15, "entropy_growth_threshold": .005, "conformer_growth_threshold": .02}
        if (set(entropy_options) != {"temperature_k", "entropy_growth_threshold", "conformer_growth_threshold"}
                or entropy_options["temperature_k"] != 298.15
                or any(isinstance(v, bool) or not math.isfinite(v) or v <= 0 for v in entropy_options.values())
                or max(entropy_options["entropy_growth_threshold"], entropy_options["conformer_growth_threshold"]) >= 1):
            result.diagnostics["reason"] = "CREST entropy requires 298.15 K and positive fractional stopping thresholds below one"
            return result
        result.algorithm = "sMTD-iMTD entropy"
        result.metadata["entropy_options"] = entropy_options
    elif entropy_options is not None:
        result.diagnostics["reason"] = "entropy options require crest-entropy-v1"
        return result
    if seed is not None:
        result.diagnostics["reason"] = "CREST numeric random seed unsupported; use seed=None and disclose engine-controlled initialization"
        return result
    if profile not in CREST_PROFILES:
        result.diagnostics["reason"] = "unresolved CREST sampling profile"
        return result
    if (not isinstance(energy_window_kcal_mol, (int, float)) or isinstance(energy_window_kcal_mol, bool)
            or not math.isfinite(energy_window_kcal_mol) or energy_window_kcal_mol <= 0):
        result.diagnostics["reason"] = "native energy window must be a finite positive kcal/mol value"
        return result
    result.metadata["native_energy_window_kcal_mol"] = energy_window_kcal_mol
    if profile == "crest-nci-v1" and (not nci or len(molecule.fragments) < 2):
        result.diagnostics["reason"] = "crest-nci-v1 requires explicit nci=True and at least two declared fragments"
        return result
    problem = _method_problem(method, resources, "gradient")
    if problem or method.engine != "xtb":
        result.diagnostics["reason"] = problem or "CREST adapter requires the explicit xTB potential backend"
        return result
    if resources.threads > available_cpu_count():
        result.diagnostics["reason"] = "requested worker count exceeds CPU affinity"
        return result
    if molecule.environment not in ({}, {"phase": "gas"}):
        result.diagnostics["reason"] = "only explicit gas-phase chemistry is supported"
        return result
    from .chemistry import atomic_number

    if any(atomic_number(s) > 86 for s in molecule.symbols):
        result.diagnostics["reason"] = "GFN2-xTB parameterization excludes elements beyond radon"
        return result
    if any(a is not None for a in molecule.isotopes):
        result.diagnostics["reason"] = "CREST native MD isotope-mass input not validated; isotope substitution cannot be silently ignored"
        return result
    requested = str(executable) if executable is not None else os.environ.get("TOPOS_CREST_EXECUTABLE", "crest")
    requested_xtb = str(xtb_executable) if xtb_executable is not None else os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb")
    crest, xtb = shutil.which(requested), shutil.which(requested_xtb)
    if crest is None or xtb is None:
        result.status = "unavailable"
        result.diagnostics["reason"] = f"required executable missing: {'CREST' if crest is None else 'xTB'}"
        return result
    # CREST legacy uses shell system calls internally: reject shell-sensitive backend paths.
    crest, xtb = str(Path(crest).resolve()), str(Path(xtb).resolve())
    if not re.fullmatch(r"[/A-Za-z0-9_.+-]+", xtb):
        result.diagnostics["reason"] = "xTB executable path is unsafe for CREST native system-call syntax"
        return result
    folder = Path(workdir).resolve()
    if folder.exists() and any(folder.iterdir()):
        result.status = "failed"
        result.diagnostics["reason"] = "fresh sampler attempt directory required; old artifacts cannot be reused"
        return result
    folder.mkdir(parents=True, exist_ok=True)
    try:
        for label, binary, pattern in [
            ("crest", crest, r"(?im)^\s*crest\s+(\d+\.\d+\.\d+)\s*$"),
            ("xtb", xtb, r"xtb version\s+(\d+\.\d+\.\d+)"),
        ]:
            result.metadata[f"{label}_executable"] = binary
            result.metadata[f"{label}_sha256"] = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
            remaining = resources.budget_seconds - (time.monotonic() - start)
            if remaining <= 0:
                result.status = "timed-out"
                result.diagnostics["reason"] = "sampler budget exhausted during preflight"
                return result
            probe = execute_process([binary, "--version"], folder,
                                resources.model_copy(update={"threads": 1, "budget_seconds": min(10, remaining)}),
                                cancel_event=cancel_event, log_prefix=f"{label}-version")
            text = Path(probe.stdout_path).read_text(errors="replace") + Path(probe.stderr_path).read_text(errors="replace")
            if probe.status in {"cancelled", "timed-out"}:
                result.status = probe.status
                result.diagnostics["reason"] = probe.reason
                return result
            match = re.search(pattern, text, re.I)
            if probe.status != "completed" or match is None:
                result.status = "unavailable"
                result.diagnostics["reason"] = f"{label} version identity not established by successful probe"
                return result
            if label == "crest":
                result.engine_version = match.group(1)
            else:
                result.potential_engine_version = match.group(1)
        if result.engine_version != "3.0.2" or result.potential_engine_version != "6.7.1":
            result.diagnostics["reason"] = "CREST/xTB versions outside tested adapter profile (3.0.2/6.7.1)"
            return result
        if method.engine_version is not None and method.engine_version != result.potential_engine_version:
            result.diagnostics["reason"] = "requested potential engine version does not match installed xTB"
            return result
        write_xyz(molecule, folder / "input.xyz")
        command = [crest, "input.xyz", "--gfn2", "--legacy", "--xnam", xtb,
                   "--chrg", str(molecule.charge), "--uhf", str(molecule.multiplicity - 1),
                   "-T", str(resources.threads), "--keepdir", "--origin", *CREST_PROFILES[profile]]
        if entropy_options is not None:
            command.extend(["--ssthr", format(entropy_options["entropy_growth_threshold"], ".12g"),
                            "--scthr", format(entropy_options["conformer_growth_threshold"], ".12g")])
        if nci:
            command.append("--nci")
        # Order matters: --mquick changes the native default to 2.5 kcal/mol.
        command.extend(["--ewin", format(energy_window_kcal_mol, ".12g")])
        result.command = command
        remaining = resources.budget_seconds - (time.monotonic() - start)
        if remaining <= 0:
            result.status = "timed-out"
            result.diagnostics["reason"] = "sampler budget exhausted during preflight"
            return result
        result.metadata["execution_kind"] = "real"
        process = execute_process(command, folder,
                              resources.model_copy(update={"budget_seconds": remaining}),
                              cancel_event=cancel_event, log_prefix="crest")
        result.status = process.status
        result.diagnostics["process"] = process.to_dict()
        raw = Path(process.stdout_path).read_text(errors="replace")
        final_ensemble = folder / "crest_conformers.xyz"
        if final_ensemble.is_file():
            try:
                result.ensemble = parse_crest_ensemble(final_ensemble, molecule)
                for frame in result.ensemble:
                    frame.metadata["native_attempt_status"] = process.status
                    frame.metadata["partial_native_attempt"] = process.status != "completed"
            except (EngineParseError, ValueError) as exc:
                result.diagnostics["ensemble_error"] = str(exc)
                if process.status == "completed":
                    result.status = "failed"
                    return result
        if process.status != "completed":
            result.diagnostics["reason"] = process.reason
            if "Not enough structures to perform GC!" in raw:
                result.diagnostics["native_failure"] = (
                    "CREST 3.0.2 legacy genetic-crossing stage lacked enough structures; "
                    "no alternate search algorithm was substituted"
                )
            result.converged = False
            return result
        normal = "CREST terminated normally." in raw
        if not normal or not result.ensemble:
            result.status = "failed"
            result.diagnostics["reason"] = "native normal termination and nonempty final ensemble not established"
            result.converged = False
            return result
        if "Use of GFN2-xTB requested" not in raw or xtb not in raw:
            raise EngineParseError("native log does not confirm requested GFN2-xTB/external executable")
        if nci and "Automatically generated ellipsoide potential for NCI mode:" not in raw:
            raise EngineParseError("native log does not establish the requested NCI confinement wall")
        if profile == "crest-nci-v1" and "--nocross  : skipping GC part." not in raw:
            raise EngineParseError("native log does not establish the requested disabled genetic crossing")
        if profile == "crest-v4-v1" and not re.search(r"--?v4\s*:\s*iMTD-sMTD", raw):
            raise EngineParseError("native log does not establish the requested iMTD-sMTD (--v4) algorithm")
        result.converged = True
        if entropy_options is not None:
            from .entropy import parse_crest_entropy

            result.metadata["native_entropy"] = parse_crest_entropy(raw, entropy_options["temperature_k"])
            result.converged = result.metadata["native_entropy"]["sampling_converged"]
            if not result.converged:
                result.status = "partial"
                result.diagnostics["reason"] = "Native entropy finished without both entropy and conformer convergence"
        result.metadata["convergence_scope"] = "native search termination; no claim of exhaustive search or frequency-verified minima"
        result.metadata["returned_frame_count"] = len(result.ensemble)
        # Keep native screens separate from TOPOS chemical identity decisions.
        result.diagnostics["native_screening"] = {
            key: float(re.findall(pattern, raw, re.I)[-1]) if re.findall(pattern, raw, re.I) else None
            for key, pattern in {
                "rmsd_threshold_angstrom": r"RMSD threshold\s*:\s*([0-9.]+)",
                "energy_window_kcal_mol": r"sorting energy window \(EWIN\)\s*:\s*([0-9.]+)",
                "rotational_threshold": r"(?:rotational constant|Bconst) threshold\s*:\s*([0-9.]+)",
            }.items()
        }
        reported_window = result.diagnostics["native_screening"]["energy_window_kcal_mol"]
        if reported_window is None or not math.isclose(reported_window, energy_window_kcal_mol, abs_tol=5.1e-5):
            raise EngineParseError("native final screening window does not confirm requested kcal/mol window")
        return result
    except (OSError, ValueError) as exc:
        result.status = "failed"
        result.diagnostics["reason"] = str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - start
        try:
            if profile in {"crest-entropy-v1", "crest-v4-v1"}:
                # Native sMTD scratch links the bias XYZ back into its own
                # parent job. Archive the exact target bytes, recording this
                # representation change; external/dangling links stay errors.
                materialized = []
                for link in sorted(folder.rglob("*")):
                    if not link.is_symlink():
                        continue
                    target = link.resolve()
                    if not target.is_relative_to(folder) or not target.is_file():
                        raise EngineParseError("entropy scratch symlink points outside its native job or is dangling")
                    data = target.read_bytes()
                    materialized.append({"path": str(link.relative_to(folder)),
                                         "native_link_target": str(link.readlink()),
                                         "archived_target_sha256": hashlib.sha256(data).hexdigest()})
                    link.unlink()
                    link.write_bytes(data)
                if materialized:
                    result.metadata["native_symlink_materialization"] = materialized
            result.artifacts = artifact_inventory(folder)
        except (OSError, EngineParseError) as exc:
            result.status = "failed"
            result.diagnostics["artifact_error"] = str(exc)
        if result.status != "completed":
            result.converged = False if result.metadata["execution_kind"] == "real" else None
        for frame in result.ensemble:
            frame.metadata["adapter_attempt_status"] = result.status
            frame.metadata["partial_native_attempt"] = result.status != "completed"
