"""Explicit, hash-bound molecular ML inference through CoChem-BASE.

Predictions describe the supplied checkpoint, never an interchangeable DFT
Hamiltonian. Committee spread is model disagreement, not a calibrated error bar.
No model or training data is downloaded implicitly by a calculation.
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from threading import Event
from typing import Literal

import numpy as np
from pydantic import Field, model_validator

from .engines import EngineResult, artifact_inventory
from .models import Contract, Molecule, ResourceLimits
from .storage import atomic_json, digest_json, file_digest, read_json

HARTREE_EV = 27.211386245988
BOHR_ANGSTROM = 0.529177210903
ML_SCHEMA = "topos-ml/0.1.0"


class ModelMember(Contract):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_run_id: str = Field(min_length=1)
    source: str = Field(min_length=1)

    def verify(self) -> Path:
        path = Path(self.path)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError("A model must be an explicit absolute regular file")
        if file_digest(path) != self.sha256:
            raise ValueError("ML checkpoint checksum mismatch")
        return path


class ModelManifest(Contract):
    schema_version: Literal["topos-ml-model/0.1.0"] = "topos-ml-model/0.1.0"
    backend: Literal["aimnet2", "mace"]
    family: str = Field(min_length=1)
    members: list[ModelMember] = Field(min_length=1, max_length=16)
    package_version: str = Field(min_length=1)
    training_method: str = Field(min_length=1)
    license_name: str = Field(min_length=1)
    license_url: str = Field(min_length=1)
    supported_elements: list[str] = Field(min_length=1)
    supported_charges: list[int] = Field(min_length=1)
    supported_multiplicities: list[int] = Field(min_length=1)
    precision: Literal["float32", "float64"]
    minimum_distance_angstrom: float = Field(default=0.4, gt=0)
    domain_reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_members(self):
        from .chemistry import atomic_number

        for element in self.supported_elements:
            atomic_number(element)
        if any(mult < 1 for mult in self.supported_multiplicities):
            raise ValueError("Multiplicities must be positive")
        if len({m.sha256 for m in self.members}) != len(self.members):
            raise ValueError("Committee members must have distinct checkpoint hashes")
        if len({m.training_run_id for m in self.members}) != len(self.members):
            raise ValueError("Committee members must identify independent training runs")
        if self.backend == "mace" and (self.supported_charges != [0] or self.supported_multiplicities != [1]):
            raise ValueError("The supported MACE-OFF adapter is neutral closed-shell only")
        if self.backend == "aimnet2" and self.precision != "float32":
            raise ValueError("AIMNet2 adapter retains the native float32 model precision")
        return self

    def validate_molecule(self, molecule: Molecule) -> None:
        if not set(molecule.symbols) <= set(self.supported_elements):
            raise ValueError("Element outside declared model domain")
        if molecule.charge not in self.supported_charges or molecule.multiplicity not in self.supported_multiplicities:
            raise ValueError("Charge or spin outside declared model domain")
        if molecule.environment:
            raise ValueError("ML adapter has no validated solvent, periodic or embedding protocol")
        coordinates = np.asarray(molecule.coordinates)
        distances = np.linalg.norm(coordinates[:, None] - coordinates[None, :], axis=2)
        np.fill_diagonal(distances, np.inf)
        if np.any(distances < self.minimum_distance_angstrom):
            raise ValueError("Geometry is outside the declared minimum-distance domain")


def reduce_committee(energies_ev, forces_ev_per_angstrom, natoms: int) -> dict:
    """Preserve correlated member predictions before forming ensemble means."""
    energies = np.asarray(energies_ev, dtype=float)
    forces = np.asarray(forces_ev_per_angstrom, dtype=float)
    if (energies.ndim != 1 or len(energies) < 1 or natoms < 1
            or forces.shape != (len(energies), natoms, 3)
            or not np.isfinite(energies).all() or not np.isfinite(forces).all()):
        raise ValueError("ML energies/forces are incomplete, nonfinite or dimensionally inconsistent")
    gradients = -forces * BOHR_ANGSTROM / HARTREE_EV
    mean_forces = forces.mean(axis=0)
    spread = None
    if len(energies) > 1:
        spread = {
            "members": len(energies), "ddof": 1,
            "energy_std_hartree": float(np.std(energies / HARTREE_EV, ddof=1)),
            "energy_std_per_sqrt_atom_hartree": float(np.std(energies / HARTREE_EV, ddof=1) / math.sqrt(natoms)),
            "max_force_deviation_ev_per_angstrom": float(np.linalg.norm(forces - mean_forces, axis=2).max()),
            "interpretation": "uncalibrated disagreement among independently trained model members",
        }
    return {
        "energy_hartree": float(energies.mean() / HARTREE_EV),
        "gradient_hartree_per_bohr": gradients.mean(axis=0).tolist(),
        "member_energies_hartree": (energies / HARTREE_EV).tolist(),
        "member_gradients_hartree_per_bohr": gradients.tolist(),
        "committee": spread,
        "units": {"energy": "hartree", "gradient": "hartree/bohr"},
    }


class MLRunner:
    """One worker loads a committee once for a finite sequence of structures."""

    def __init__(self, manifest: ModelManifest, runtime, *, gpu_index: int | None = None,
                 gpu_memory_mb: int | None = None):
        self.manifest = manifest
        self.runtime = runtime
        self.gpu_index, self.gpu_memory_mb = gpu_index, gpu_memory_mb

    def evaluate_frames(self, molecules: list[Molecule], workdir: str | Path,
                        resources: ResourceLimits, *, cancel_event: Event | None = None) -> list[EngineResult]:
        if not molecules or len(molecules) > 10000:
            raise ValueError("ML evaluation requires 1–10000 explicit structures")
        if self.runtime is None or not hasattr(self.runtime, "run_ml_process"):
            raise ValueError("Production ML requires the mandatory CoChem-BASE audited ML runtime")
        for molecule in molecules:
            self.manifest.validate_molecule(molecule)
        model_files = {str(m.verify()): m.sha256 for m in self.manifest.members}
        folder = Path(workdir).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        if any(folder.iterdir()):
            raise ValueError("ML calculation requires an empty attempt directory")
        executable = self.runtime.resolve_executable(self.manifest.backend)
        request = {
            "schema_version": ML_SCHEMA, "manifest": self.manifest.model_dump(mode="json"),
            "molecules": [m.model_dump(mode="json") for m in molecules],
            "resources": resources.model_dump(mode="json"), "gpu_memory_mb": self.gpu_memory_mb,
        }
        request_path = folder / "ml-request.json"
        atomic_json(request_path, request)
        request_hash = file_digest(request_path)
        command = [executable, "-m", "topos.ml_worker", "--request", str(request_path)]
        started = time.monotonic()
        process = self.runtime.run_ml_process(
            command, folder, resources, engine=self.manifest.backend,
            request_sha256=request_hash, worker_sha256=file_digest(Path(__file__).with_name("ml_worker.py")),
            model_files=model_files, gpu_index=self.gpu_index, gpu_memory_mb=self.gpu_memory_mb,
            cancel_event=cancel_event,
        )
        inventory = artifact_inventory(folder)
        if process.status != "completed":
            return [EngineResult(status=process.status, engine=self.manifest.backend,
                                 method=self.manifest.family, operation="gradient", command=command,
                                 artifacts=inventory, elapsed_seconds=time.monotonic() - started,
                                 diagnostics={"reason": "ML worker did not complete", "process": process.to_dict()})]
        output = folder / "ml-result.json"
        if output.is_symlink() or not output.is_file():
            raise ValueError("ML worker did not produce its confined result")
        result = read_json(output)
        if (result.get("schema_version") != ML_SCHEMA or result.get("request_sha256") != request_hash
                or result.get("manifest_sha256") != digest_json(request["manifest"])
                or len(result.get("frames", [])) != len(molecules)):
            raise ValueError("ML output does not match the immutable request")
        package = "aimnet" if self.manifest.backend == "aimnet2" else "mace-torch"
        if result["versions"].get(package) != self.manifest.package_version:
            raise ValueError("ML implementation version differs from the explicit model protocol")
        outputs = []
        for molecule, frame in zip(molecules, result["frames"], strict=True):
            checked = reduce_committee(np.asarray(frame["member_energies_hartree"]) * HARTREE_EV,
                -np.asarray(frame["member_gradients_hartree_per_bohr"]) * HARTREE_EV / BOHR_ANGSTROM,
                len(molecule.symbols))
            if (len(frame["member_energies_hartree"]) != len(self.manifest.members)
                    or not np.isclose(checked["energy_hartree"], frame["energy_hartree"], rtol=0, atol=1e-12)
                    or not np.allclose(checked["gradient_hartree_per_bohr"], frame["gradient_hartree_per_bohr"], rtol=0, atol=1e-12)):
                raise ValueError("ML ensemble mean differs from its raw member predictions")
            outputs.append(EngineResult(
                status="completed", engine=self.manifest.backend, method=self.manifest.family,
                operation="gradient", engine_version=self.manifest.package_version,
                energy_hartree=checked["energy_hartree"], gradient_hartree_per_bohr=checked["gradient_hartree_per_bohr"],
                molecule=molecule, converged=True, command=command, artifacts=inventory,
                elapsed_seconds=time.monotonic() - started,
                metadata={"execution_kind": "real", "result_kind": "ML-prediction", "manifest": request["manifest"],
                          "manifest_sha256": result["manifest_sha256"], "request_sha256": request_hash,
                          "output_molecule": molecule.model_dump(mode="json"), "predictions": checked,
                          "versions": result["versions"], "device": result["device"], "precision": self.manifest.precision,
                          "convergence_scope": "finite model inference; geometry and DFT accuracy unclassified",
                          "energy_definition": "checkpoint potential energy, not an executed DFT calculation"},
            ))
        return outputs

    def evaluate(self, molecule: Molecule, workdir: str | Path, resources: ResourceLimits,
                 *, cancel_event: Event | None = None) -> EngineResult:
        return self.evaluate_frames([molecule], workdir, resources, cancel_event=cancel_event)[0]


def frozen_interaction(complex_result: EngineResult, fragment_results: list[EngineResult]) -> dict:
    """Subtract each committee member's frozen monomers before estimating spread."""
    from .fragments import split_fragments

    if complex_result.molecule is None:
        raise ValueError("Missing complex geometry")
    expected = split_fragments(complex_result.molecule)
    if len(fragment_results) != len(expected):
        raise ValueError("Interaction requires every explicitly charged/spin-resolved fragment")
    results = [complex_result, *fragment_results]
    if any(r.status != "completed" or not r.converged for r in results):
        raise ValueError("Interaction requires completed actual ML predictions")
    identity = complex_result.metadata["manifest_sha256"]
    if any(r.metadata.get("manifest_sha256") != identity for r in results):
        raise ValueError("Interaction components require the same ordered model committee")
    for wanted, actual in zip(expected, fragment_results, strict=True):
        if actual.molecule != wanted:
            raise ValueError("Frozen interaction fragments must preserve the exact complex coordinates/state")
    components = [np.asarray(r.metadata["predictions"]["member_energies_hartree"]) for r in results]
    interaction = components[0] - np.sum(components[1:], axis=0)
    return {"electronic_interaction_hartree": float(interaction.mean()),
            "member_interaction_hartree": interaction.tolist(),
            "committee_std_hartree": float(np.std(interaction, ddof=1)) if len(interaction) > 1 else None,
            "geometry_policy": "frozen-inc", "bsse_policy": "no orbital basis counterpoise for ML potential",
            "uncertainty_definition": "paired member interaction disagreement, uncalibrated",
            "energy_culling_authorized": False, "manifest_sha256": identity}
