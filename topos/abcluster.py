"""Native ABCluster 3.4 rigidmol packing with explicit classical parameters.

The native intermolecular CHARMM score is an enumeration score, never a
molecular electronic energy. No force-field typing, virtual sites, internal
deformation, implicit solvent, or global-minimum guarantee is inferred here.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable
from uuid import uuid4

import numpy as np
from scipy.constants import Avogadro, physical_constants

from .engines import EngineParseError, artifact_inventory
from .models import Molecule, ResourceLimits, RigidmolAtomParameter, RigidmolOptions
from .runtime import available_cpu_count, run_process
from .sampling import SampledConformer, SamplingResult
from .storage import IntegrityError, atomic_json, file_digest

__all__ = ["RigidmolAtomParameter", "RigidmolOptions", "rigidmol_inputs", "parse_rigidmol", "run_rigidmol"]
VERSION = "3.4"
MANUAL = "https://zhjun-sci.com/abcluster/doc/eg-h2o6.html"
FORCE_FIELD_MANUAL = "https://zhjun-sci.com/abcluster/doc/charmmff.html"
KJ_MOL_PER_HARTREE = physical_constants["Hartree energy"][0] * Avogadro / 1000
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][-+]?\d+)?"


def _number(value: str) -> float:
    parsed = float(value.replace("D", "E").replace("d", "e"))
    if not math.isfinite(parsed):
        raise EngineParseError("rigidmol returned a nonfinite number")
    return parsed


def _validate(molecule: Molecule, options: RigidmolOptions) -> dict[str, RigidmolAtomParameter]:
    if molecule.environment or molecule.multiplicity != 1:
        raise ValueError("rigidmol CHARMM packing requires a closed-shell gas-phase system")
    if len(molecule.fragments) < 2 or len(molecule.fragment_states) != len(molecule.fragments):
        raise ValueError("rigidmol requires explicit fragments and balanced fragment charge/spin states")
    if any(state.multiplicity != 1 for state in molecule.fragment_states):
        raise ValueError("this classical potential does not describe open-shell fragment electronic states")
    params = {p.atom_id: p for p in options.atomic_parameters}
    if len(params) != len(options.atomic_parameters) or set(params) != set(molecule.atom_ids):
        raise ValueError("provide exactly one explicit force-field parameter for every input atom ID")
    group_for = {atom: group for group, indices in enumerate(molecule.fragments) for atom in indices}
    if any(group_for[b.atom1] != group_for[b.atom2] for b in molecule.bonds):
        raise ValueError("rigid packing cannot cut a declared bond across fragments")
    states = {tuple(sorted(s.atom_indices)): s for s in molecule.fragment_states}
    for indices in molecule.fragments:
        ps = [params[molecule.atom_ids[i]] for i in indices]
        if abs(sum(p.charge_e for p in ps) - states[tuple(sorted(indices))].charge) > 1e-6:
            raise ValueError("partial atomic charges must sum to each declared fragment charge")
        if not any(p.epsilon_kj_mol > 0 and p.sigma_angstrom > 0 for p in ps):
            raise ValueError("every fragment requires an explicit nonzero Lennard-Jones repulsive site")
        if any((p.epsilon_kj_mol > 0) != (p.sigma_angstrom > 0) for p in ps):
            raise ValueError("Lennard-Jones epsilon and sigma must both be positive or both zero")
    return params


def rigidmol_inputs(molecule: Molecule, options: RigidmolOptions) -> dict[str, str]:
    """Compile the documented native input; every fragment has a unique file.

    Native output therefore follows the declared fragment/index ordering even
    when chemically identical fragments carry different persistent atom IDs.
    """
    params = _validate(molecule, options)
    files: dict[str, str] = {}
    cluster = [str(len(molecule.fragments))]
    for number, indices in enumerate(molecule.fragments):
        name = f"fragment-{number:04d}.xyz"
        rows = [str(len(indices)), f"TOPOS fragment {number}"]
        rows.extend(f"{molecule.symbols[i]} " + " ".join(f"{v:.16g}" for v in molecule.coordinates[i])
                    for i in indices)
        rows.append("explicit q(e) epsilon(kJ/mol) sigma(angstrom); see protocol.json")
        rows.extend(" ".join(f"{v:.16g}" for v in (params[molecule.atom_ids[i]].charge_e,
                                                  params[molecule.atom_ids[i]].epsilon_kj_mol,
                                                  params[molecule.atom_ids[i]].sigma_angstrom))
                    for i in indices)
        files[name] = "\n".join(rows) + "\n"
        cluster.append(f"{name} 1")
    cluster.append(f"* {options.amplitude_angstrom:.16g}")
    files["packing.cluster"] = "\n".join(cluster) + "\n"
    files["packing.inp"] = "\n".join(map(str, ("packing.cluster", options.population,
        options.generations, options.scout_limit, options.amplitude_angstrom, "packing",
        options.max_saved_minima))) + "\n"
    return files


def _read_frame(path: Path, molecule: Molecule, index: int) -> SampledConformer:
    if path.is_symlink() or not path.is_file():
        raise EngineParseError("native rigidmol frame must be a regular local file")
    lines = path.read_text().splitlines()
    n = len(molecule.symbols)
    if len(lines) != n + 2 or lines[0].strip() != str(n):
        raise EngineParseError("rigidmol frame count/order is incompatible, truncated, or contains virtual sites")
    match = re.fullmatch(r"Energy:\s*(" + _FLOAT + r")\s*", lines[1].strip())
    if not match:
        raise EngineParseError("rigidmol frame lacks its explicit native Energy score")
    energy = _number(match[1])
    order = [i for group in molecule.fragments for i in group]
    rows = [line.split() for line in lines[2:]]
    if any(len(row) != 4 for row in rows) or [r[0] for r in rows] != [molecule.symbols[i] for i in order]:
        raise EngineParseError("rigidmol changed the native fragment/atom order")
    coordinates = np.zeros((n, 3))
    for i, row in zip(order, rows, strict=True):
        coordinates[i] = [_number(v) for v in row[1:]]
    original = np.asarray(molecule.coordinates)
    for indices in molecule.fragments:
        before, after = original[indices], coordinates[indices]
        distances_before = np.linalg.norm(before[:, None] - before[None, :], axis=2)
        distances_after = np.linalg.norm(after[:, None] - after[None, :], axis=2)
        if np.max(np.abs(distances_before - distances_after)) > 5e-7:
            raise EngineParseError("rigidmol deformed an explicitly frozen monomer")
        # Distances alone also admit reflection. Native rigid motions must be proper.
        left, _, right = np.linalg.svd((before - before.mean(0)).T @ (after - after.mean(0)))
        rotation = left @ np.diag([1., 1., np.linalg.det(left @ right)]) @ right
        if np.max(np.abs((before - before.mean(0)) @ rotation - (after - after.mean(0)))) > 5e-7:
            raise EngineParseError("rigidmol changed a monomer's handedness or atom mapping")
    data = molecule.model_dump(mode="json")
    data["coordinates"] = coordinates.tolist()
    return SampledConformer(molecule=Molecule.model_validate(data), source_index=index + 1,
        source="ABCLUSTER_RIGIDMOL", energy_hartree=energy / KJ_MOL_PER_HARTREE,
        metadata={"native_energy_kj_mol": energy, "energy_units": "hartree (converted classical score)",
                  "energy_definition": "classical pairwise intermolecular CHARMM energy; excludes monomer internal energies",
                  "is_electronic_energy": False, "raw_comment": lines[1], "raw_file": str(path.resolve()),
                  "validation_status": "requires-common-level-refinement",
                  "stationary_point_classification": "unclassified",
                  "atom_mapping": "declared fragment/index order inverted back to original atom IDs"})


def parse_rigidmol(stdout: str, folder: str | Path, molecule: Molecule,
                   options: RigidmolOptions) -> list[SampledConformer]:
    """Require actual native completion, full cycle table and matching scores."""
    _validate(molecule, options)
    folder = Path(folder).resolve()
    versions = set(re.findall(r"^rigidmol\s+(\d+\.\d+(?:\.\d+)?)\s*$", stdout, re.M))
    if versions != {VERSION} or "Artificial Bee Colony Optimization Finished!" not in stdout:
        raise EngineParseError("pinned rigidmol 3.4 native search completion is missing")
    if "Normal termination at " not in stdout or "Error termination" in stdout:
        raise EngineParseError("rigidmol did not terminate normally")
    for label, expected in (("Population size", options.population), ("Maximal generation", options.generations),
                            ("Scout limit", options.scout_limit), ("# of saved LMs", options.max_saved_minima)):
        match = re.search(re.escape(label) + r":\s*(\d+)\b", stdout)
        if match is None or int(match[1]) != expected:
            raise EngineParseError("native rigidmol control parameters disagree with the typed protocol")
    amplitude = re.search(r"^Amplitude:\s*(" + _FLOAT + ")", stdout, re.M)
    field = re.search(r"External electric field:\s*(" + _FLOAT + r")\s+Volt/Angstrom", stdout)
    if (amplitude is None or abs(_number(amplitude[1]) - options.amplitude_angstrom) > 1e-7
            or field is None or abs(_number(field[1])) > 1e-10):
        raise EngineParseError("native packing scale or zero-field environment disagrees with the request")
    cycles = re.findall(r"^\s*(\d+)\s+" + _FLOAT + r"\s+" + _FLOAT + r"\s+(" + _FLOAT + r")\s+\d+\s+\d+\s+\d+\s*$", stdout, re.M)
    if [int(c[0]) for c in cycles] != list(range(1, options.generations + 1)):
        raise EngineParseError("rigidmol native generation evidence is incomplete")
    count = re.search(r"\*\s+(\d+) LMs will be saved in \[ packing-LM \]", stdout)
    if count is None or not 1 <= int(count[1]) <= options.max_saved_minima:
        raise EngineParseError("rigidmol did not report a valid observed local-minimum count")
    minimum = re.search(r"Final Global Minimal Energy:\s*(" + _FLOAT + ")", stdout)
    if minimum is None:
        raise EngineParseError("rigidmol native best energy is absent")
    lm = folder / "packing-LM"
    if lm.is_symlink() or not lm.is_dir():
        raise EngineParseError("native local-minimum directory is absent or linked")
    paths = {p.name for p in lm.glob("*.xyz")}
    if paths != {f"{i}.xyz" for i in range(int(count[1]))}:
        raise EngineParseError("native local-minimum inventory disagrees with its result count")
    frames = [_read_frame(lm / f"{i}.xyz", molecule, i) for i in range(int(count[1]))]
    energies = [f.metadata["native_energy_kj_mol"] for f in frames]
    reports = re.findall(r"^\s*(\d+)\s+(" + _FLOAT + r")\s+" + _FLOAT + r"\s*$",
                         stdout.split(" -- Results Report --")[-1], re.M)
    if ([int(row[0]) for row in reports] != list(range(len(frames)))
            or any(abs(_number(row[1]) - energy) > 1e-7 for row, energy in zip(reports, energies, strict=False))):
        raise EngineParseError("native local-minimum energies disagree with their saved structures")
    if any(b < a - 1e-7 for a, b in zip(energies, energies[1:], strict=False)):
        raise EngineParseError("native local minima are not in the documented energy order")
    if abs(energies[0] - _number(minimum[1])) > 1e-7 or abs(energies[0] - _number(cycles[-1][1])) > 1e-7:
        raise EngineParseError("native best structure, cycle table and final energy disagree")
    best = _read_frame(folder / "packing-OPT.xyz", molecule, 0)
    if abs(best.energy_hartree - frames[0].energy_hartree) > 1e-10:
        raise EngineParseError("native best XYZ score disagrees with the saved ensemble")
    return frames


def run_rigidmol(molecule: Molecule, options: RigidmolOptions, resources: ResourceLimits,
                 workdir: str | Path, *, executable: str | Path | None = None,
                 process_runner: Callable[..., Any] | None = None,
                 cancel_event: Event | None = None) -> SamplingResult:
    """Execute bounded native ABC packing; completed immutable stages are reused."""
    start = time.monotonic()
    result = SamplingResult(status="unsupported", engine="abcluster", algorithm="artificial-bee-colony-rigidmol",
        method="CHARMM-pairwise-rigid", potential_engine="abcluster", metadata={
            "execution_kind": "not-executed", "profile": "abcluster-rigidmol-3.4-v1", "exhaustive": False,
            "randomness": "native engine-controlled; numeric seed unavailable", "effective_seed": None,
            "native_energy_units": "kJ/mol", "energy_definition": "classical intermolecular packing score",
            "refinement_required": True, "frozen_monomer_policy": "all intrafragment distances and handedness preserved",
            "initial_packing": "native random placement; input supplies monomer shapes, not relative fragment placement",
            "confinement": "amplitude defines initial/search packing scale, not a validated physical container",
            "clash_handling": "native CHARMM Lennard-Jones repulsion and native local optimization",
            "manual": MANUAL, "force_field_manual": FORCE_FIELD_MANUAL})
    try:
        files = rigidmol_inputs(molecule, options)
        if resources.device != "cpu" or resources.threads > available_cpu_count():
            raise ValueError("rigidmol 3.4 adapter requires an available explicit CPU allocation")
    except ValueError as exc:
        result.diagnostics["reason"] = str(exc)
        return result
    binary = str(Path(executable).expanduser().resolve()) if executable else shutil.which("rigidmol")
    if binary is None or not Path(binary).is_file():
        result.status = "unavailable"
        result.diagnostics["reason"] = "ABCluster rigidmol executable is not provisioned"
        return result
    folder = Path(workdir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    protocol = {"molecule": molecule.model_dump(mode="json"), "options": options.model_dump(mode="json"),
                "resources": resources.model_dump(exclude={"budget_seconds"}), "executable": binary,
                "executable_sha256": file_digest(Path(binary)), "version": VERSION, "inputs": files}
    manifest = folder / "protocol.json"
    if manifest.is_symlink():
        raise IntegrityError("rigidmol protocol cannot be a symbolic link")
    if manifest.exists():
        if json.loads(manifest.read_text()) != protocol:
            raise IntegrityError("rigidmol recovery protocol changed")
    elif any(folder.iterdir()):
        raise IntegrityError("rigidmol directory contains unverified earlier evidence")
    else:
        atomic_json(manifest, protocol)
    receipt = folder / "completed.json"
    if receipt.is_symlink():
        raise IntegrityError("rigidmol completed receipt cannot be a symbolic link")
    if receipt.exists():
        cached = SamplingResult.model_validate(json.loads(receipt.read_text()))
        if cached.status != "completed" or cached.metadata.get("execution_kind") != "real":
            raise IntegrityError("rigidmol receipt does not establish actual completed execution")
        for artifact in cached.artifacts:
            p = Path(artifact.path)
            if p.is_symlink() or not p.resolve().is_relative_to(folder) or not p.is_file() or file_digest(p) != artifact.sha256:
                raise IntegrityError("completed rigidmol raw artifact changed")
        native = Path(cached.metadata["native_directory"])
        if native.is_symlink() or not native.resolve().is_relative_to(folder):
            raise IntegrityError("rigidmol native evidence must remain within its run directory")
        parsed = parse_rigidmol((native / "rigidmol.stdout").read_text(), native, molecule, options)
        if [p.model_dump(mode="json") for p in parsed] != [p.model_dump(mode="json") for p in cached.ensemble]:
            raise IntegrityError("rigidmol receipt disagrees with native raw ensemble")
        cached.metadata["reused_completed_search"] = True
        return cached
    native = folder / ("native-" + uuid4().hex)
    native.mkdir()
    for name, content in files.items():
        (native / name).write_text(content)
    result.command = [binary, "packing.inp"]
    result.metadata.update(execution_kind="real", protocol=protocol, native_directory=str(native),
                           recovery_policy="completed verified search reused; interrupted native campaign starts fresh")
    execute = process_runner or run_process
    remaining = resources.budget_seconds - (time.monotonic() - start)
    if remaining <= 0:
        result.status = "timed-out"
        result.diagnostics["reason"] = "rigidmol budget exhausted preparing and verifying native inputs"
        result.artifacts = artifact_inventory(folder)
        result.elapsed_seconds = time.monotonic() - start
        return result
    process = execute(result.command, native, resources.model_copy(update={"budget_seconds": remaining}),
                      cancel_event=cancel_event, log_prefix="rigidmol")
    result.status = process.status
    result.diagnostics["process"] = process.to_dict()
    if process.status == "completed":
        try:
            result.ensemble = parse_rigidmol(Path(process.stdout_path).read_text(), native, molecule, options)
            if file_digest(Path(binary)) != protocol["executable_sha256"]:
                raise IntegrityError("rigidmol executable changed during the calculation")
            result.engine_version = result.potential_engine_version = VERSION
            result.converged = True
            result.metadata["convergence_definition"] = "requested native generations completed; no completeness or electronic minimum claim"
        except (ValueError, OSError, EngineParseError) as exc:
            result.status = "failed"
            result.converged = False
            result.diagnostics["reason"] = str(exc)
    else:
        result.diagnostics["reason"] = process.reason
    result.artifacts = artifact_inventory(folder)
    result.elapsed_seconds = time.monotonic() - start
    if result.status == "completed":
        atomic_json(receipt, result.model_dump(mode="json"))
    return result
