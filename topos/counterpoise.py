"""Actual ORCA Boys–Bernardi energy legs with a shared explicit basis inventory.

The physical fragment and full set of basis centers are distinct objects. No
molecular charge/spin is assigned to ghost nuclei, no complex wavefunction is
reused for a fragment, and built-in gCP composites cannot acquire another CP.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any, Callable

from .chemistry import atomic_number
from .engines import EngineResult, _engine_version, _orca_input, run_engine
from .fragments import _matching_fragment, split_fragments
from .models import MethodSpec, Molecule, ResourceLimits, utc_now
from .science import counterpoise_interaction, geometry_digest
from .storage import IntegrityError, atomic_json, digest_json, file_digest

CP_SCHEMA = "topos-counterpoise/0.1.0"
ORCA_GHOST_SOURCE = "https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/counterpoise.html"
ORCA_BASIS_SOURCE = "https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/basisset.html#reading-basis-sets-from-a-file"
EXECUTION_TIMING_SCOPE = "UTC wall clock measured around the actual energy adapter invocation, including version probe and evidence parsing"


def _leg_execution_timing(calculation: EngineResult) -> tuple[str | None, str | None]:
    """Validate recorded call boundaries; never assign import times to old evidence."""
    timing = calculation.metadata.get("execution_timing")
    if timing is None:
        return None, None
    try:
        start, finish = timing["started_at"], timing["finished_at"]
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(finish)
        if (set(timing) != {"started_at", "finished_at", "scope"}
                or timing["scope"] != EXECUTION_TIMING_SCOPE or first.utcoffset() is None
                or last.utcoffset() is None or last < first):
            raise ValueError("Invalid wall-clock boundary")
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrityError("Counterpoise leg has invalid recorded execution wall-clock timing") from exc
    return start, finish


def _verify_artifacts(artifacts, folder):
    for item in artifacts:
        path = Path(item["path"])
        if (path.is_symlink() or not path.resolve().is_relative_to(folder) or not path.is_file()
                or path.stat().st_size != item["size_bytes"] or file_digest(path) != item["sha256"]):
            raise IntegrityError("Counterpoise retained artifact is missing, changed or outside its work directory")


def _validate_completed_leg(entry, job, basis, method, folder):
    """Re-read native evidence before either caching or using a completed energy."""
    if entry.get("result_sha256") != digest_json(entry.get("result")):
        raise IntegrityError("Counterpoise leg result digest changed")
    calculation = EngineResult.model_validate(entry["result"])
    _leg_execution_timing(calculation)
    if (entry.get("role") != job["role"] or calculation.status != "completed"
            or calculation.converged is not True or calculation.energy_hartree is None
            or calculation.engine != "orca" or calculation.operation != "energy"
            or calculation.engine_version != "6.1.1" or calculation.metadata.get("execution_kind") != "real"
            or not calculation.command or not calculation.artifacts):
        raise IntegrityError("Counterpoise requires actual versioned engine execution evidence for every leg")
    _verify_artifacts(entry["result"]["artifacts"], folder)
    inventory = {str(Path(item.path).resolve()): item for item in calculation.artifacts}
    stdout = Path(calculation.diagnostics.get("process", {}).get("stdout_path", ""))
    if str(stdout.resolve()) not in inventory:
        raise IntegrityError("Counterpoise leg lacks a retained actual native output")
    raw = stdout.read_text(errors="replace")
    match = re.findall(r"FINAL SINGLE POINT ENERGY\s+([-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?)", raw)
    if (_engine_version(raw, "orca") != "6.1.1" or "ORCA TERMINATED NORMALLY" not in raw
            or "SCF CONVERGED AFTER" not in raw or re.search(r"SCF NOT CONVERGED|SCF CONVERGENCE FAILURE", raw, re.I)
            or not match or abs(float(match[-1].replace("D", "E").replace("d", "e")) - calculation.energy_hartree) > 1e-10):
        raise IntegrityError("Counterpoise energy is inconsistent with the retained converged native output")
    deck = stdout.parent / "job.inp"
    expected = _orca_input(Molecule.model_validate(job["molecule"]), method,
                           ResourceLimits.model_validate(calculation.metadata["resources"]), "energy",
                           ghost_atom_indices=job["ghost_atom_indices"],
                           ghost_electronic_state=tuple(job["ghost_electronic_state"]) if job["ghost_electronic_state"] else None,
                           basis_files={kind: f"{kind}.bas" for kind in basis})
    if str(deck.resolve()) not in inventory or deck.read_text() != expected:
        raise IntegrityError("Counterpoise native deck does not match its immutable method, state and basis centers")
    for kind, description in basis.items():
        actual = calculation.metadata.get("external_basis", {}).get(kind, {})
        path = stdout.parent / f"{kind}.bas"
        if (actual.get("sha256") != description["sha256"] or str(path.resolve()) not in inventory
                or file_digest(path) != description["sha256"]):
            raise IntegrityError("Counterpoise leg did not use the exact shared basis bytes")
    executable = Path(calculation.command[0])
    if not executable.is_file() or file_digest(executable) != calculation.metadata.get("executable_sha256"):
        raise IntegrityError("Counterpoise executable identity changed or is unavailable")
    physical = Molecule.model_validate(job.get("physical_molecule", job["molecule"]))
    if calculation.molecule is None or geometry_digest(calculation.molecule) != geometry_digest(physical):
        raise IntegrityError("Counterpoise energy does not identify the physical fragment geometry")
    return calculation


def _validate_basis_export_receipts(receipts, basis, paths, molecule, method, engine_identity=None):
    """Verify native BASE export records against the files and actual calculation engine.

    This is content/provenance verification, not authentication of arbitrary
    untrusted receipt authors. Production receipts originate from
    BaseRuntime.export_orca_basis, whose broker verifies the full distribution.
    """
    if not isinstance(receipts, dict) or set(receipts) != set(basis):
        raise IntegrityError("Native basis export receipts must cover exactly the shared basis files")
    distribution = set()
    for kind, receipt in receipts.items():
        expected_name = method.basis if kind == "orbital" else method.auxiliary_basis or "def2/J"
        required = {"schema_version", "authority_kind", "basis", "elements", "format", "command",
                    "output_path", "output_sha256", "exporter_sha256", "orca_sha256", "orca_version",
                    "distribution_manifest_sha256", "archive_sha256", "process", "status", "evidence"}
        if not isinstance(receipt, dict) or not required.issubset(receipt):
            raise IntegrityError("Incomplete native basis export receipt")
        command = receipt["command"]
        elements = sorted(set(molecule.symbols))
        if not isinstance(receipt["output_path"], str) or not isinstance(command, list) or not command:
            raise IntegrityError("Native basis receipt requires an explicit output path and command")
        expected_command = [command[0], "-b", expected_name, "-a", *elements,
                            "-f", "GAMESS-US", "-o", Path(receipt["output_path"]).name]
        if (receipt["schema_version"] != "topos-orca-basis-export/0.1.0"
                or receipt["authority_kind"] != "verified-ORCA-distribution-utility"
                or receipt["basis"] != expected_name
                or receipt["elements"] != elements
                or receipt["format"] != "GAMESS-US"
                or not isinstance(receipt["process"], dict)
                or receipt["status"] != "completed" or receipt["process"].get("status") != "completed"
                or receipt["orca_version"] != "6.1.1"
                or engine_identity is not None and (receipt["orca_version"], receipt["orca_sha256"]) != engine_identity
                or receipt["output_sha256"] != basis[kind]["sha256"]
                or command != expected_command):
            raise IntegrityError("Native basis export receipt does not match the requested basis or actual engine")
        source = Path(receipt["output_path"])
        exporter = Path(command[0])
        if (source.is_symlink() or not source.is_file() or file_digest(source) != basis[kind]["sha256"]
                or exporter.is_symlink() or not exporter.is_file() or exporter.name != "orca_exportbasis"
                or file_digest(exporter) != receipt["exporter_sha256"]
                or file_digest(paths[kind]) != receipt["output_sha256"]):
            raise IntegrityError("Native basis/exporter files do not match their retained receipt")
        for key in ("distribution_manifest_sha256", "archive_sha256", "orca_sha256"):
            value = receipt[key]
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise IntegrityError("Native basis receipt requires verified distribution hashes")
        evidence = receipt["evidence"]
        if not isinstance(evidence, list) or len(evidence) != 2:
            raise IntegrityError("Native basis receipt requires both complete exporter output streams")
        expected_streams = {receipt["process"].get("stdout_path"), receipt["process"].get("stderr_path")}
        if None in expected_streams or len(expected_streams) != 2:
            raise IntegrityError("Native basis receipt lacks separate exporter output streams")
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {"path", "sha256", "bytes"} or item["path"] not in expected_streams:
                raise IntegrityError("Native basis exporter evidence does not match the actual process streams")
            path = Path(item["path"])
            if (path.is_symlink() or not path.is_file() or path.stat().st_size != item["bytes"]
                    or file_digest(path) != item["sha256"]):
                raise IntegrityError("Native basis exporter output was altered or is unavailable")
        if {item["path"] for item in evidence} != expected_streams:
            raise IntegrityError("Native basis receipt repeats an output stream")
        distribution.add((receipt["archive_sha256"], receipt["distribution_manifest_sha256"],
                          receipt["exporter_sha256"], receipt["orca_sha256"]))
    if len(distribution) != 1:
        raise IntegrityError("Shared orbital and auxiliary bases must originate from the same verified ORCA distribution")


def counterpoise_plan(molecule: Molecule, method: MethodSpec, *,
                      isolated_references: list[Molecule] | None = None) -> list[dict[str, Any]]:
    """Construct the five balanced frozen-geometry energy legs before execution."""
    fragments = split_fragments(molecule)
    if len(fragments) != 2:
        raise ValueError("This Boys–Bernardi adapter requires exactly two explicit fragments")
    if (method.engine != "orca" or method.method not in {"HF", "wB97X-V", "wB97M-V"}
            or method.basis is None or method.dispersion or method.solvent or method.constraints):
        raise ValueError("Counterpoise requires an explicit supported ORCA orbital basis, gas-phase energy protocol, and no extra dispersion/gCP/composite correction")
    if molecule.environment not in ({}, {"phase": "gas"}):
        raise ValueError("Counterpoise adapter requires a gas-phase physical state")
    if any(atomic_number(symbol) > 36 for symbol in molecule.symbols):
        raise ValueError("Shared external-basis counterpoise currently requires all-electron H–Kr; ECP basis exports need an explicit ECP contract")
    jobs = [{"role": "complex-in-complex-basis", "molecule": molecule.model_dump(mode="json"),
             "ghost_atom_indices": [], "ghost_electronic_state": None}]
    all_indices = set(range(len(molecule.symbols)))
    for index, (group, fragment) in enumerate(zip(molecule.fragments, fragments, strict=True)):
        jobs.append({"role": f"fragment-{index}-in-own-basis", "molecule": fragment.model_dump(mode="json"),
                     "ghost_atom_indices": [], "ghost_electronic_state": None})
        jobs.append({"role": f"fragment-{index}-in-complex-basis", "molecule": molecule.model_dump(mode="json"),
                     "physical_molecule": fragment.model_dump(mode="json"),
                     "ghost_atom_indices": sorted(all_indices - set(group)),
                     "ghost_electronic_state": [fragment.charge, fragment.multiplicity]})
    if isolated_references is not None:
        if len(isolated_references) != 2:
            raise ValueError("Provide one isolated reference geometry per fragment")
        for index, (fragment, reference) in enumerate(zip(fragments, isolated_references, strict=True)):
            _matching_fragment(fragment, reference)
            jobs.append({"role": f"isolated-reference-{index}", "molecule": reference.model_dump(mode="json"),
                         "ghost_atom_indices": [], "ghost_electronic_state": None})
    return jobs


def execute_counterpoise(
    molecule: Molecule, method: MethodSpec, resources: ResourceLimits, workdir: str | Path, *,
    orbital_basis_file: str | Path, auxiliary_basis_file: str | Path | None = None,
    isolated_references: list[Molecule] | None = None, executable: str | Path | None = None,
    process_runner: Callable[..., Any] | None = None, cancel_event: Event | None = None,
    basis_export_receipts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute all required real energy legs; return no CP energy after any failure.

    Basis files must be ORCA-exported GAMESS-US files for the declared method's
    orbital/auxiliary bases. They are copied byte-for-byte into every leg and
    their identities are retained. Missing files never trigger an automatic
    replacement. The optional isolated references supply electronic deformation
    and binding relative to those geometries; their minimum character is not
    implied by a single-point calculation.
    """
    plan = counterpoise_plan(molecule, method, isolated_references=isolated_references)
    basis_paths = {"orbital": Path(orbital_basis_file)}
    if auxiliary_basis_file is not None:
        basis_paths["auxiliary"] = Path(auxiliary_basis_file)
    if method.method in {"wB97X-V", "wB97M-V"} and "auxiliary" not in basis_paths:
        raise ValueError("RIJCOSX counterpoise requires the shared exported Coulomb-fitting basis as well")
    basis = {}
    for name, path in basis_paths.items():
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 16 * 1024 * 1024:
            raise ValueError("Shared counterpoise basis must be a nonempty regular file at most 16 MiB")
        if b"\x00" in path.read_bytes():
            raise ValueError("Shared counterpoise basis must be a text file")
        basis[name] = {"sha256": file_digest(path), "size_bytes": path.stat().st_size,
                       "declared_name": method.basis if name == "orbital" else method.auxiliary_basis or "def2/J"}
    folder = Path(workdir).resolve()
    previous = None
    if folder.exists() and any(folder.iterdir()):
        checkpoint = folder / "counterpoise-result.json"
        if checkpoint.is_symlink() or not checkpoint.is_file():
            raise IntegrityError("Counterpoise nonempty scratch lacks a resumable result checkpoint")
        previous = json.loads(checkpoint.read_text())
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result = {
        "schema_version": CP_SCHEMA, "status": "running", "validation_status": "not-evaluated",
        "geometry_sha256": geometry_digest(molecule), "method": method.model_dump(mode="json"),
        "basis": basis, "plan": plan, "jobs": [], "energies": None, "artifacts": [],
        "basis_identity": {"status": "user-supplied-unverified",
                           "reason": "File hashes establish shared bytes, not that these are the declared native ORCA basis parameters"},
        "provenance": {"ghost_syntax": "Element: x y z", "manual": ORCA_GHOST_SOURCE,
                       "basis_manual": ORCA_BASIS_SOURCE, "wavefunction_reuse": "none across legs",
                       "basis_policy": "identical exported orbital/auxiliary bytes for all legs",
                       "energy_definition": "electronic interaction at a fixed complex geometry; negative is attractive",
                       "execution_timing_policy": "New adapter invocations retain hashed UTC wall-clock boundaries; historical cached legs without them remain undated and cannot satisfy predeclared fresh-calculation acceptance",
                       "limitations": ["No ZPE, thermal or solvation correction", "CP is not a complete-basis or accuracy guarantee",
                                       "Optional isolated reference minima must be established separately"]},
    }
    if basis_export_receipts is not None:
        result["basis_export_receipts"] = basis_export_receipts
    result["comparison_protocol_definition"] = {
        "method": method.model_dump(mode="json"),
        "basis_sha256": {name: entry["sha256"] for name, entry in basis.items()},
        "complex_state": {"charge": molecule.charge, "multiplicity": molecule.multiplicity,
                          "fragment_states": [state.model_dump(mode="json") for state in molecule.fragment_states]},
        "complex_geometry_sha256": geometry_digest(molecule),
    }
    result["comparison_protocol"] = digest_json(result["comparison_protocol_definition"])
    cached = {}
    if previous is not None:
        for field in ("schema_version", "geometry_sha256", "method", "basis", "plan"):
            if previous.get(field) != result[field]:
                raise IntegrityError(f"Counterpoise resume changes immutable {field}")
        _verify_artifacts(previous["artifacts"], folder)
        plan_by_role = {job["role"]: job for job in plan}
        for entry in previous["jobs"]:
            if entry["result_sha256"] != digest_json(entry["result"]):
                raise IntegrityError("Counterpoise checkpoint leg digest changed")
            if entry["result"]["status"] == "completed":
                _validate_completed_leg(entry, plan_by_role[entry["role"]], basis, method, folder)
                cached[entry["role"]] = entry
        result["jobs"] = previous["jobs"]
        result["artifacts"] = previous["artifacts"]
        history = folder / f"checkpoint-{digest_json(previous)}.json"
        if not history.exists():
            atomic_json(history, previous)
        result["resumed_completed_roles"] = sorted(cached)

    def finish(status, reason=None):
        result["status"] = status
        unique_artifacts = {}
        for item in result["artifacts"]:
            old = unique_artifacts.get(item["path"])
            if old is not None and (old["sha256"], old["size_bytes"]) != (item["sha256"], item["size_bytes"]):
                raise IntegrityError("Counterpoise artifact identity changed during execution")
            unique_artifacts[item["path"]] = item
        result["artifacts"] = list(unique_artifacts.values())
        if reason:
            result["reason"] = reason
        result["elapsed_seconds"] = time.monotonic() - started
        atomic_json(folder / "counterpoise-result.json", result)
        return result

    if basis_export_receipts is not None:
        try:
            _validate_basis_export_receipts(basis_export_receipts, basis, basis_paths, molecule, method)
            evidence_folder = folder / f"basis-export-evidence-{digest_json(basis_export_receipts)}"
            evidence_folder.mkdir(exist_ok=True)
            for kind, receipt in basis_export_receipts.items():
                receipt_file = evidence_folder / f"{kind}-receipt.json"
                if receipt_file.exists():
                    if json.loads(receipt_file.read_text()) != receipt:
                        raise IntegrityError("Retained basis export receipt changed")
                else:
                    atomic_json(receipt_file, receipt)
                result["artifacts"].append({"path": str(receipt_file), "sha256": file_digest(receipt_file),
                                            "size_bytes": receipt_file.stat().st_size, "role": "basis-export-receipt"})
                for index, item in enumerate(receipt["evidence"]):
                    destination = evidence_folder / f"{kind}-{index}.log"
                    if not destination.exists():
                        shutil.copyfile(item["path"], destination)
                    if file_digest(destination) != item["sha256"]:
                        raise IntegrityError("Native basis exporter stream changed while retaining evidence")
                    result["artifacts"].append({"path": str(destination), "sha256": item["sha256"],
                                                "size_bytes": item["bytes"], "role": "basis-export-output"})
        except (IntegrityError, OSError, TypeError, ValueError) as exc:
            return finish("failed", f"Native basis identity could not be established: {exc}")

    if process_runner is None:
        from .base_integration import BaseIntegrationError, BaseRuntime
        try:
            runtime = BaseRuntime()
            executable = runtime.resolve_executable("orca", executable)
            runtime.validate_resources(resources)
            process_runner = runtime.run_process
            result["provenance"]["base"] = runtime.provenance()
        except BaseIntegrationError as exc:
            return finish("unavailable", str(exc))
    identity = None
    values = {}
    for index, job in enumerate(plan):
        if cancel_event is not None and cancel_event.is_set():
            return finish("cancelled", "Counterpoise cancelled before the next energy leg")
        remaining = resources.budget_seconds - (time.monotonic() - started)
        if remaining <= 0:
            return finish("timed-out", "Counterpoise total budget exhausted")
        for name, path in basis_paths.items():
            if file_digest(path) != basis[name]["sha256"]:
                return finish("failed", "Shared basis changed between counterpoise legs")
        if job["role"] in cached:
            entry = cached[job["role"]]
            calculation = EngineResult.model_validate(entry["result"])
        else:
            retries = sum(entry["role"] == job["role"] for entry in result["jobs"])
            while (folder / f"leg-{index}-attempt-{retries}").exists():
                retries += 1
            leg_started_at = utc_now()
            calculation = run_engine(
                Molecule.model_validate(job["molecule"]), method,
                resources.model_copy(update={"budget_seconds": remaining}), folder / f"leg-{index}-attempt-{retries}",
                operation="energy", executable=executable, process_runner=process_runner, cancel_event=cancel_event,
                ghost_atom_indices=job["ghost_atom_indices"],
                ghost_electronic_state=tuple(job["ghost_electronic_state"]) if job["ghost_electronic_state"] else None,
                orbital_basis_file=basis_paths["orbital"], auxiliary_basis_file=basis_paths.get("auxiliary"),
            )
            calculation.metadata["execution_timing"] = {
                "started_at": leg_started_at, "finished_at": utc_now(), "scope": EXECUTION_TIMING_SCOPE}
            payload = calculation.model_dump(mode="json")
            entry = {"role": job["role"], "result": payload, "result_sha256": digest_json(payload)}
            result["jobs"].append(entry)
            result["artifacts"].extend(payload["artifacts"])
            finish("running")
        if calculation.status != "completed" or calculation.converged is not True or calculation.energy_hartree is None:
            return finish(calculation.status if calculation.status != "completed" else "failed",
                          f"Counterpoise leg did not supply converged energy: {job['role']}")
        try:
            _validate_completed_leg(entry, job, basis, method, folder)
        except (IntegrityError, OSError, ValueError, KeyError, TypeError) as exc:
            return finish("failed", str(exc))
        actual_identity = (calculation.engine_version, calculation.metadata.get("executable_sha256"))
        if executable is not None and file_digest(Path(executable).resolve()) != actual_identity[1]:
            return finish("failed", "Counterpoise cached execution differs from the currently authorized executable")
        if identity is not None and actual_identity != identity:
            return finish("failed", "Counterpoise legs used different engine versions or executables")
        identity = actual_identity
        values[job["role"]] = calculation.energy_hartree
    energies = counterpoise_interaction(
        values["complex-in-complex-basis"], values["fragment-0-in-complex-basis"],
        values["fragment-1-in-complex-basis"], values["fragment-0-in-own-basis"],
        values["fragment-1-in-own-basis"],
    )
    energies["half_cp_interaction_hartree"] = (energies["raw_interaction_hartree"] + energies["cp_interaction_hartree"]) / 2
    energies["leg_energies_hartree"] = values
    if isolated_references is not None:
        deformation = sum(values[f"fragment-{i}-in-own-basis"] - values[f"isolated-reference-{i}"] for i in range(2))
        energies.update(fragment_deformation_hartree=deformation,
                        raw_binding_hartree=energies["raw_interaction_hartree"] + deformation,
                        cp_binding_hartree=energies["cp_interaction_hartree"] + deformation,
                        half_cp_binding_hartree=energies["half_cp_interaction_hartree"] + deformation)
    result["energies"] = energies
    result["comparison_protocol_definition"]["engine_identity"] = {"version": identity[0], "executable_sha256": identity[1]}
    result["comparison_protocol"] = digest_json(result["comparison_protocol_definition"])
    result["validation_status"] = "human-review"
    if basis_export_receipts is not None:
        try:
            _validate_basis_export_receipts(basis_export_receipts, basis, basis_paths, molecule, method, identity)
        except (IntegrityError, OSError, TypeError, ValueError, IndexError) as exc:
            result["energies"] = None
            return finish("failed", f"Native basis identity could not be established: {exc}")
        result["basis_identity"] = {"status": "native-export-verified",
                                    "receipt_sha256": digest_json(basis_export_receipts),
                                    "scope": "BASE export receipts, actual file hashes, engine identity and named basis agree"}
        result["validation_status"] = "validated-for-protocol"
    return finish("completed")
