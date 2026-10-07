"""Finite rigid ML surfaces and frozen interaction screening matrix recipes."""
from __future__ import annotations

import itertools
import time
from pathlib import Path
from threading import Event
from typing import Literal

import h5py
import numpy as np
from pydantic import Field, model_validator
from scipy.spatial.transform import Rotation

from .engines import artifact_inventory
from .fragments import split_fragments
from .ml import MLRunner, ModelManifest, frozen_interaction
from .models import Artifact, Attempt, Contract, Molecule, Quantity, utc_now
from .storage import IntegrityError, atomic_json, digest_json, file_digest


class RigidMLGrid(Contract):
    """Extrinsic XYZ Euler rotations of one rigid fragment about its centroid.

    Translation values are displacements from the supplied complex, in its
    Cartesian frame. Intrafragment coordinates remain exactly rigid. These are
    explicit finite points, with no interpolation or inferred dissociation limit.
    """
    geometry_policy: Literal["frozen-iso"] = "frozen-iso"
    moving_fragment: int = Field(ge=0)
    translation_x_angstrom: list[float] = Field(default_factory=lambda: [0.0], min_length=1)
    translation_y_angstrom: list[float] = Field(default_factory=lambda: [0.0], min_length=1)
    translation_z_angstrom: list[float] = Field(default_factory=lambda: [0.0], min_length=1)
    rotation_x_degree: list[float] = Field(default_factory=lambda: [0.0], min_length=1)
    rotation_y_degree: list[float] = Field(default_factory=lambda: [0.0], min_length=1)
    rotation_z_degree: list[float] = Field(default_factory=lambda: [0.0], min_length=1)
    isolated_fragment_geometry_sources: list[str] = Field(min_length=2)

    def axes(self) -> list[list[float]]:
        return [self.translation_x_angstrom, self.translation_y_angstrom, self.translation_z_angstrom,
                self.rotation_x_degree, self.rotation_y_degree, self.rotation_z_degree]

    @model_validator(mode="after")
    def valid_grid(self):
        if any(len(set(axis)) != len(axis) for axis in self.axes()):
            raise ValueError("Rigid grid axes must not repeat points")
        count = int(np.prod([len(axis) for axis in self.axes()], dtype=object))
        if not 1 <= count <= 10000:
            raise ValueError("Rigid grid must contain 1–10000 explicit points")
        if any(not source.strip() for source in self.isolated_fragment_geometry_sources):
            raise ValueError("Frozen-iso grids require isolated-fragment geometry provenance")
        return self

    def frames(self, molecule: Molecule) -> tuple[list[Molecule], list[list[float]]]:
        fragments = split_fragments(molecule)
        if len(fragments) != 2 or self.moving_fragment >= len(fragments):
            raise ValueError("This rigid grid requires exactly two explicitly state-resolved fragments")
        if len(self.isolated_fragment_geometry_sources) != len(fragments):
            raise ValueError("Every frozen-iso fragment requires its isolated geometry source")
        moving = molecule.fragments[self.moving_fragment]
        reference = np.asarray(molecule.coordinates, dtype=float)
        centroid = reference[moving].mean(axis=0)
        frames, coordinates = [], []
        for point in itertools.product(*self.axes()):
            xyz = reference.copy()
            xyz[moving] = (Rotation.from_euler("xyz", point[3:], degrees=True).apply(reference[moving] - centroid)
                           + centroid + np.asarray(point[:3]))
            frame = molecule.model_copy(update={"coordinates": xyz.tolist()})
            frames.append(Molecule.model_validate(frame.model_dump(mode="json")))
            coordinates.append(list(point))
        return frames, coordinates


def execute_ml_matrix(workflow, record, store, deadline: float, cancel_event: Event | None, inputs) -> bool:
    row_id = record.request.matrix_row_id
    if row_id not in {"T2-1min", "T5-1min"}:
        return False
    manifest = inputs.ml_model
    if manifest is None:
        raise ValueError("ML matrix rows require an explicit checkpoint manifest")
    manifest = ModelManifest.model_validate(manifest)
    if workflow.base_runtime is None:
        raise ValueError("ML matrix execution requires an actual BASE-audited ML silo")
    if record.request.per_geometry_budget_seconds is not None:
        raise ValueError("Batched ML currently enforces the complete campaign budget; a per-geometry cap cannot be ignored")
    if row_id == "T2-1min":
        if inputs.ml_grid is None:
            raise ValueError("T2-1min requires an explicit frozen-iso dense rigid grid")
        frames, points = inputs.ml_grid.frames(record.request.molecule)
        if len(frames) < 1000:
            raise ValueError("T2-1min requires at least 1000 finite ML grid points")
    else:
        if len(manifest.members) < 2:
            raise ValueError("T5-1min requires at least two independently trained committee members")
        frames = [record.request.molecule, *split_fragments(record.request.molecule)]
        if len(frames) < 3:
            raise ValueError("Frozen-inc interaction requires explicitly state-resolved fragments")
        points = []
    identity = digest_json({"row": row_id, "model": manifest.model_dump(mode="json"),
                            "frames": [m.model_dump(mode="json") for m in frames],
                            "grid": inputs.ml_grid.model_dump(mode="json") if inputs.ml_grid else None})
    completed = [a for a in record.attempts if a.metadata.get("ml_campaign_sha256") == identity and a.status == "completed"]
    if completed:
        for artifact in completed[-1].artifacts:
            path = store.run_dir / artifact.path
            if path.is_symlink() or not path.is_file() or file_digest(path) != artifact.sha256:
                raise IntegrityError("Completed ML campaign artifact changed")
        record.status = "completed"
        store.commit(record)
        return True
    if cancel_event is not None and cancel_event.is_set():
        record.status = "cancelled"
        store.commit(record)
        return True
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        record.status = "timed-out"
        store.commit(record)
        return True
    attempt = Attempt(run_id=record.run_id, engine=manifest.backend, method=manifest.family,
                      status="running", started_at=utc_now(), metadata={"ml_campaign_sha256": identity,
                      "matrix_row_id": row_id, "model": manifest.model_dump(mode="json"),
                      "role": "ML-screening-campaign", "energy_culling_authorized": False})
    record.attempts.append(attempt)
    store.commit(record)
    folder = store.run_dir / "attempts" / attempt.attempt_id
    runner = MLRunner(manifest, workflow.base_runtime, gpu_index=inputs.ml_gpu_index,
                      gpu_memory_mb=inputs.ml_gpu_memory_mb)
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            attempt.status = record.status = "timed-out"
            attempt.finished_at = utc_now()
            store.commit(record)
            return True
        results = runner.evaluate_frames(frames, folder, record.request.resources.model_copy(update={"budget_seconds": remaining}),
                                         cancel_event=cancel_event)
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        from .base_integration import BaseIntegrationError

        attempt.status = record.status = "unavailable" if isinstance(exc, (BaseIntegrationError, ImportError)) else "failed"
        attempt.finished_at = utc_now()
        attempt.diagnostics["reason"] = str(exc)
        record.metadata["termination_reason"] = str(exc)
        if folder.is_dir():
            attempt.artifacts = [a.model_copy(update={"path": Path(a.path).relative_to(store.run_dir).as_posix()})
                                 for a in artifact_inventory(folder)]
        store.commit(record)
        return True
    first = results[0]
    attempt.command, attempt.engine_version = first.command, first.engine_version
    attempt.artifacts = [a.model_copy(update={"path": Path(a.path).relative_to(store.run_dir).as_posix()}) for a in first.artifacts]
    attempt.status = first.status
    attempt.finished_at = utc_now()
    attempt.diagnostics = first.diagnostics
    if first.status != "completed":
        record.status = first.status
        store.commit(record)
        return True
    if len(results) != len(frames):
        raise IntegrityError("Incomplete ML campaign cannot be marked completed")
    if row_id == "T5-1min":
        derived = frozen_interaction(results[0], results[1:])
        attempt.quantities.append(Quantity(name="electronic_interaction", value=derived["electronic_interaction_hartree"],
            units="hartree", method=manifest.family, attempt_id=attempt.attempt_id,
            validity="validated-for-protocol", definition="frozen-inc paired ML committee interaction; uncalibrated screening only"))
    else:
        energies = [r.energy_hartree for r in results]
        derived = {"grid": inputs.ml_grid.model_dump(mode="json"), "grid_points": points,
                   "energies_hartree": energies, "relative_energies_hartree": (np.asarray(energies) - min(energies)).tolist(),
                   "gradients_hartree_per_bohr": [r.gradient_hartree_per_bohr for r in results],
                   "geometry_policy": "frozen-iso", "interpretation": "finite ML surface for boundary exploration; not quantitative well-depth validation",
                   "energy_culling_authorized": False}
        attempt.quantities.append(Quantity(name="ML_surface_energies", value=energies, units="hartree",
            method=manifest.family, attempt_id=attempt.attempt_id, validity="validated-for-protocol",
            definition="explicit frozen-iso model potential at every recorded finite grid point"))
        shard = folder / "ml-surface.h5"
        with h5py.File(shard, "x") as handle:
            handle.attrs.update(schema_version="topos-ml-surface/0.1.0", campaign_sha256=identity,
                                model_manifest_sha256=first.metadata["manifest_sha256"],
                                geometry_policy="frozen-iso", energy_definition="unvalidated model potential; boundary exploration only")
            dataset = handle.create_dataset("grid", data=np.asarray(points))
            dataset.attrs["columns"] = "dx_A,dy_A,dz_A,rx_deg,ry_deg,rz_deg; extrinsic xyz Euler"
            dataset = handle.create_dataset("coordinates", data=np.asarray([m.coordinates for m in frames]), compression="gzip")
            dataset.attrs["units"] = "angstrom"
            dataset = handle.create_dataset("energies", data=np.asarray(energies))
            dataset.attrs["units"] = "hartree"
            dataset = handle.create_dataset("gradients", data=np.asarray([r.gradient_hartree_per_bohr for r in results]), compression="gzip")
            dataset.attrs["units"] = "hartree/bohr"
            handle.create_dataset("symbols", data=np.asarray(record.request.molecule.symbols, dtype=h5py.string_dtype()))
            handle.flush()
        attempt.artifacts.append(Artifact(path=shard.relative_to(store.run_dir).as_posix(), sha256=file_digest(shard),
                                          size_bytes=shard.stat().st_size, role="ML-surface-shard"))
    receipt = folder / "ml-campaign.json"
    atomic_json(receipt, {"schema_version": "topos-ml-campaign/0.1.0", "campaign_sha256": identity, "derived": derived,
                         "model_manifest_sha256": first.metadata["manifest_sha256"],
                         "frame_results": [r.model_dump(mode="json", exclude={"artifacts"}) for r in results]})
    attempt.artifacts.append(Artifact(path=receipt.relative_to(store.run_dir).as_posix(), sha256=file_digest(receipt),
                                      size_bytes=receipt.stat().st_size, role="derived-output"))
    attempt.converged, attempt.validation_status = True, "validated-for-protocol"
    attempt.metadata.update(execution_kind="real", derived_result_sha256=file_digest(receipt), derived=derived,
                            limitations=["Model disagreement is not calibrated DFT error", "No ML energy culling without independent G4 correlation audit"])
    record.metadata["ml_campaign"] = {"attempt_id": attempt.attempt_id, "derived": derived}
    record.status = "completed"
    store.commit(record)
    return True
