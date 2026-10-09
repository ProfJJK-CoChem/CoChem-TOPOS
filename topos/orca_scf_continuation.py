"""One native electronic continuation at the unchanged original SCF targets.

This is confined to a freshly started energy/gradient or analytic Freq job's own GBW.
It never borrows optimization orbitals, changes the deck, or grants a new budget.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from .orca_numerical_profiles import observe_scf_numerical_profile
from .storage import atomic_json, file_digest


def continue_ordinary_scf(command, folder, resources, process, raw, *, operation,
                          deadline, cancel_event, execute_process) -> tuple[Any, str, str, dict] | None:
    """One unchanged energy/gradient continuation; optimizer orbitals are excluded."""
    if operation not in {"energy", "gradient"}:
        return None
    return _continue_own_scf(command, folder, resources, process, raw, operation=operation,
        stem="job", deadline=deadline, cancel_event=cancel_event, execute_process=execute_process)


def continue_frequency_scf(command, folder, resources, process, raw, *,
                           deadline, cancel_event, execute_process) -> tuple[Any, str, str, dict] | None:
    """One analytic Freq continuation using only that independent Freq job's GBW."""
    return _continue_own_scf(command, folder, resources, process, raw, operation="hessian",
        stem="frequency", deadline=deadline, cancel_event=cancel_event, execute_process=execute_process)


def _continue_own_scf(command, folder, resources, process, raw, *, operation, stem,
                      deadline, cancel_event, execute_process) -> tuple[Any, str, str, dict] | None:
    """Continue only a complete native job missing an active numerical residual.

    The caller has already verified its native version, normal termination and
    SCF marker. Failed processes, missing/changed targets and optimization jobs
    do not qualify. Both native stream sets are retained byte for byte.
    """
    observation = observe_scf_numerical_profile(raw)
    if (process.status != "completed"
            or not observation["failures"] or any(not failure.startswith(
                "active final criterion not achieved: ") for failure in observation["failures"])):
        return None
    folder = Path(folder)
    deck, orbitals = folder / (stem + ".inp"), folder / (stem + ".gbw")
    if (command[1:] != [stem + ".inp"] or any(path.is_symlink() or not path.is_file()
            or path.stat().st_size == 0 for path in (deck, orbitals))):
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0 or (cancel_event is not None and cancel_event.is_set()):
        return None
    archive = folder / "initial-scf"
    archive.mkdir(exist_ok=False)
    binding = {"schema": "topos-orca-scf-continuation/1", "maximum_continuations": 1,
               "operation": operation, "unchanged_input_sha256": file_digest(deck),
               "own_initial_gbw_sha256": file_digest(orbitals), "initial_scf": observation,
               "budget_scope": "remaining original attempt deadline; no extension",
               "orbital_scope": "own independently started " + ("analytic Freq" if stem == "frequency" else "energy/gradient") + " job only; no optimization orbitals",
               "manual": "https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/initialguess.html"}
    names = ("job.inp", "job.gbw", "job.engrad", "job.xyz", "job.property.txt")
    if stem == "frequency":
        names = tuple(sorted(path.name for path in folder.glob("frequency.*")
                             if path.name not in {"frequency.stdout", "frequency.stderr"}))
    for name in names:
        path = folder / name
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise ValueError("Native SCF continuation inputs/outputs must be regular files")
            shutil.copyfile(path, archive / ("initial-" + name))
    archived_process = process.to_dict()
    binding["initial_execution_stream_paths"] = {
        key: archived_process[key] for key in ("stdout_path", "stderr_path")}
    for key in ("stdout_path", "stderr_path"):
        path = Path(archived_process[key])
        if path.parent != folder or path.is_symlink() or not path.is_file():
            raise ValueError("Initial native SCF stream is outside its own attempt")
        path.rename(archive / ("initial-" + path.name))
        archived_process[key] = str(archive / ("initial-" + path.name))
    binding["initial_process"] = archived_process
    binding["retained_initial_files_sha256"] = {
        path.name: file_digest(path) for path in sorted(archive.iterdir())}
    binding["status"] = "prepared"
    atomic_json(folder / "scf-continuation.json", binding)
    remaining = deadline - time.monotonic()
    if remaining <= 0 or (cancel_event is not None and cancel_event.is_set()):
        # Keep canonical streams available when the deadline ends during copying.
        for key in ("stdout_path", "stderr_path"):
            shutil.copyfile(archived_process[key], binding["initial_execution_stream_paths"][key])
        binding["status"] = "not-launched-deadline-or-cancellation"
        atomic_json(folder / "scf-continuation.json", binding)
        return None
    if (file_digest(deck) != binding["unchanged_input_sha256"]
            or file_digest(orbitals) != binding["own_initial_gbw_sha256"]):
        raise ValueError("Native SCF continuation input or own orbitals changed")
    options = {"log_prefix": "frequency"} if stem == "frequency" else {}
    continuation = execute_process(command, folder,
        resources.model_copy(update={"budget_seconds": remaining}), cancel_event=cancel_event,
        threads_per_process=1, **options)
    new_raw = Path(continuation.stdout_path).read_text(errors="replace")
    new_stderr = Path(continuation.stderr_path).read_text(errors="replace")
    binding.update(status=continuation.status, continuation_process=continuation.to_dict(),
                   final_scf=observe_scf_numerical_profile(new_raw),
                   input_unchanged=file_digest(deck) == binding["unchanged_input_sha256"],
                   native_own_autostart=("Checking for AutoStart:" in new_raw
                       and "The File: " + stem + ".gbw exists" in new_raw
                       and "GBW file was renamed to GES file" in new_raw))
    atomic_json(folder / "scf-continuation.json", binding)
    if continuation.status == "completed" and (
            not binding["input_unchanged"] or not binding["native_own_autostart"]):
        raise ValueError("Native SCF continuation did not retain its exact input and own-orbital lineage")
    return continuation, new_raw, new_stderr, binding
