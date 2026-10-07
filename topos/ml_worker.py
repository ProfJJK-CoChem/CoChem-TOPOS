"""Isolated finite ML inference worker; models never auto-download.

MACE serialized models must be trusted, separately provisioned artifacts. The
parent binds their exact SHA-256 and BASE binds the isolated interpreter.
"""
from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path

from .ml import ML_SCHEMA, ModelManifest, reduce_committee
from .models import Molecule, ResourceLimits
from .storage import atomic_json, digest_json, file_digest, read_json


def evaluate(request: dict) -> dict:
    import numpy as np
    import torch
    from ase import Atoms

    if set(request) != {"schema_version", "manifest", "molecules", "resources", "gpu_memory_mb"} or request["schema_version"] != ML_SCHEMA:
        raise ValueError("Unknown ML worker request contract")
    manifest = ModelManifest.model_validate(request["manifest"])
    resources = ResourceLimits.model_validate(request["resources"])
    molecules = [Molecule.model_validate(m) for m in request["molecules"]]
    if not 1 <= len(molecules) <= 10000:
        raise ValueError("Invalid frame count")
    for molecule in molecules:
        manifest.validate_molecule(molecule)
    for member in manifest.members:
        member.verify()
    package = "aimnet" if manifest.backend == "aimnet2" else "mace-torch"
    versions = {name: importlib.metadata.version(name) for name in (package, "torch", "numpy", "ase")}
    if versions[package] != manifest.package_version:
        raise ValueError("ML package version differs from manifest")
    torch.set_num_threads(resources.threads)
    torch.use_deterministic_algorithms(True)
    device = "cpu"
    if resources.device == "gpu":
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            raise ValueError("GPU request requires one explicitly selected CUDA device")
        limit = request["gpu_memory_mb"]
        total = torch.cuda.get_device_properties(0).total_memory / 1024**2
        if type(limit) is not int or not 0 < limit <= total:
            raise ValueError("Invalid per-device GPU allocator limit")
        torch.cuda.set_per_process_memory_fraction(limit / total, device=0)
        torch.backends.cuda.matmul.allow_tf32 = False
        device = "cuda:0"
    elif resources.device != "cpu" or request["gpu_memory_mb"] is not None:
        raise ValueError("Requested ML device is unsupported or inconsistent")
    calculators = []
    for member in manifest.members:
        if manifest.backend == "mace":
            from mace.calculators import MACECalculator

            calculator = MACECalculator(model_paths=member.path, device=device, default_dtype=manifest.precision)
            allowed = set(int(z) for z in calculator.models[0].atomic_numbers.tolist())
        else:
            from aimnet.calculators import AIMNet2Calculator

            calculator = AIMNet2Calculator(member.path, device=device, compile_model=False, deterministic=True)
            if any(m.multiplicity != 1 for m in molecules) and not calculator.is_nse:
                raise ValueError("AIMNet checkpoint ignores spin multiplicity; refusing open-shell inference")
            allowed = set((calculator.metadata or {}).get("implemented_species", []))
            if not allowed:
                raise ValueError("AIMNet checkpoint must advertise its supported atomic numbers")
        if any(not set(Atoms(m.symbols).numbers) <= allowed for m in molecules):
            raise ValueError("Requested elements are outside actual checkpoint metadata")
        calculators.append(calculator)
    frames = []
    for molecule in molecules:
        energies, forces = [], []
        atoms = Atoms(molecule.symbols, positions=molecule.coordinates)
        for calculator in calculators:
            if manifest.backend == "mace":
                atoms.calc = calculator
                energies.append(float(atoms.get_potential_energy()))
                forces.append(np.asarray(atoms.get_forces(), dtype=float).tolist())
            else:
                output = calculator({"coord": np.asarray(molecule.coordinates), "numbers": atoms.numbers,
                                     "charge": float(molecule.charge), "mult": float(molecule.multiplicity)}, forces=True)
                energies.append(float(output["energy"].detach().cpu().item()))
                forces.append(output["forces"].detach().cpu().numpy().tolist())
        frames.append(reduce_committee(energies, forces, len(molecule.symbols)))
    for member in manifest.members:
        member.verify()
    return {"schema_version": ML_SCHEMA, "manifest_sha256": digest_json(request["manifest"]),
            "versions": versions, "device": device, "frames": frames}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    path = args.request
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError("ML request must be a bounded absolute regular file")
    digest = file_digest(path)
    result = evaluate(read_json(path))
    if file_digest(path) != digest:
        raise ValueError("ML request changed during inference")
    result["request_sha256"] = digest
    output = path.parent / "ml-result.json"
    if output.exists() or output.is_symlink():
        raise ValueError("Refusing to overwrite an existing ML result")
    atomic_json(output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
