"""Finite rigid ML surfaces and frozen interaction screening matrix recipes."""
from __future__ import annotations

import itertools
import os
import time
from pathlib import Path
from threading import Event
from typing import Literal

import h5py
import numpy as np
from pydantic import Field, model_validator
from scipy.spatial.transform import Rotation

from .engines import EngineResult, artifact_inventory
from .fragments import split_fragments
from .ml import (
    BOHR_ANGSTROM,
    HARTREE_EV,
    ML_SCHEMA,
    MLRunner,
    ModelManifest,
    frozen_interaction,
    reduce_committee,
)
from .models import Attempt, Contract, Molecule, Quantity, RunRecord, utc_now
from .storage import (
    IntegrityError,
    atomic_json,
    confined_file,
    digest_json,
    file_digest,
    fsync_directory,
    read_json,
)


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


def _validate_result_batch(results, frames, manifest, folder):
    """Bind every structured prediction to the retained immutable worker bytes."""
    if len(results) != len(frames) or not results:
        raise IntegrityError("Incomplete ML campaign cannot be marked completed")
    expected_manifest = manifest.model_dump(mode="json")
    manifest_sha = digest_json(expected_manifest)
    request_path = confined_file(folder, "ml-request.json")
    native_request, native_output = read_json(request_path), read_json(confined_file(folder, "ml-result.json"))
    request_sha = file_digest(request_path)
    if (native_request.get("schema_version") != ML_SCHEMA or native_output.get("schema_version") != ML_SCHEMA
            or native_request.get("manifest") != expected_manifest
            or native_request.get("molecules") != [m.model_dump(mode="json") for m in frames]
            or native_output.get("manifest_sha256") != manifest_sha
            or native_output.get("request_sha256") != request_sha
            or len(native_output.get("frames", [])) != len(frames)):
        raise IntegrityError("ML native request/result differs from the campaign molecule/model identity")
    package = "aimnet" if manifest.backend == "aimnet2" else "mace-torch"
    if native_output.get("versions", {}).get(package) != manifest.package_version:
        raise IntegrityError("ML native implementation version differs from the campaign protocol")
    try:
        for frame, result, raw in zip(frames, results, native_output["frames"], strict=True):
            if (result.status != "completed" or result.converged is not True
                    or result.engine != manifest.backend or result.method != manifest.family
                    or result.engine_version != manifest.package_version or result.operation != "gradient"
                    or result.molecule != frame or result.metadata.get("execution_kind") != "real"
                    or result.metadata.get("result_kind") != "ML-prediction"
                    or result.metadata.get("manifest") != expected_manifest
                    or result.metadata.get("manifest_sha256") != manifest_sha
                    or result.metadata.get("request_sha256") != request_sha
                    or result.metadata.get("versions") != native_output.get("versions")
                    or result.metadata.get("device") != native_output.get("device")
                    or result.metadata.get("precision") != manifest.precision
                    or result.metadata.get("output_molecule") != frame.model_dump(mode="json")
                    or raw.get("units") != {"energy": "hartree", "gradient": "hartree/bohr"}
                    or result.command != results[0].command or not result.command):
                raise IntegrityError("ML structured prediction lacks exact native method, molecular or execution identity")
            checked = reduce_committee(np.asarray(raw["member_energies_hartree"]) * HARTREE_EV,
                -np.asarray(raw["member_gradients_hartree_per_bohr"]) * HARTREE_EV / BOHR_ANGSTROM,
                len(frame.symbols))
            if (len(raw["member_energies_hartree"]) != len(manifest.members)
                    or np.asarray(result.gradient_hartree_per_bohr).shape != (len(frame.symbols), 3)
                    or np.asarray(raw["gradient_hartree_per_bohr"]).shape != (len(frame.symbols), 3)
                    or not np.isclose(checked["energy_hartree"], result.energy_hartree, rtol=0, atol=1e-12)
                    or not np.isclose(checked["energy_hartree"], raw["energy_hartree"], rtol=0, atol=1e-12)
                    or not np.allclose(checked["gradient_hartree_per_bohr"], result.gradient_hartree_per_bohr, rtol=0, atol=1e-12)
                    or not np.allclose(checked["gradient_hartree_per_bohr"], raw["gradient_hartree_per_bohr"], rtol=0, atol=1e-12)
                    or digest_json(checked) != digest_json(result.metadata.get("predictions"))):
                raise IntegrityError("ML structured prediction differs from native member energies/gradients")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, IntegrityError):
            raise
        raise IntegrityError(f"Invalid ML prediction evidence: {exc}") from exc


def _derived_campaign(row_id, results, points, grid):
    if row_id == "T5-1min":
        return frozen_interaction(results[0], results[1:])
    energies = [r.energy_hartree for r in results]
    return {"grid": grid.model_dump(mode="json"), "grid_points": points,
            "energies_hartree": energies, "relative_energies_hartree": (np.asarray(energies) - min(energies)).tolist(),
            "gradients_hartree_per_bohr": [r.gradient_hartree_per_bohr for r in results],
            "geometry_policy": "frozen-iso",
            "interpretation": "finite ML surface for boundary exploration; not quantitative well-depth validation",
            "energy_culling_authorized": False}


def _validate_surface(path, identity, manifest_sha, frames, points, derived):
    try:
        with h5py.File(path, "r") as handle:
            shapes = {"grid": (len(frames), 6), "coordinates": (len(frames), len(frames[0].symbols), 3),
                      "energies": (len(frames),), "gradients": (len(frames), len(frames[0].symbols), 3),
                      "symbols": (len(frames[0].symbols),)}
            if set(handle.keys()) != set(shapes) or any(
                    not isinstance(handle.get(name, getlink=True), h5py.HardLink) for name in shapes):
                raise IntegrityError("ML surface requires its exact internal dataset membership")
            if any(not isinstance(handle[name], h5py.Dataset) or handle[name].shape != shape
                   or handle[name].is_virtual or handle[name].external for name, shape in shapes.items()):
                raise IntegrityError("ML surface has external storage or an incompatible dataset shape")
            if (handle.attrs.get("schema_version") != "topos-ml-surface/0.1.0"
                    or handle.attrs.get("campaign_sha256") != identity
                    or handle.attrs.get("model_manifest_sha256") != manifest_sha
                    or handle.attrs.get("geometry_policy") != "frozen-iso"
                    or handle.attrs.get("energy_definition") != "unvalidated model potential; boundary exploration only"
                    or handle["grid"].attrs.get("columns") != "dx_A,dy_A,dz_A,rx_deg,ry_deg,rz_deg; extrinsic xyz Euler"
                    or handle["coordinates"].attrs.get("units") != "angstrom"
                    or handle["energies"].attrs.get("units") != "hartree"
                    or handle["gradients"].attrs.get("units") != "hartree/bohr"
                    or handle["symbols"].asstr()[:].tolist() != frames[0].symbols
                    or not np.array_equal(handle["grid"][:], points)
                    or not np.array_equal(handle["coordinates"][:], [m.coordinates for m in frames])
                    or not np.array_equal(handle["energies"][:], derived["energies_hartree"])
                    or not np.array_equal(handle["gradients"][:], derived["gradients_hartree_per_bohr"])):
                raise IntegrityError("ML surface shard differs from the native campaign data or units")
    except (KeyError, OSError, ValueError) as exc:
        if isinstance(exc, IntegrityError):
            raise
        raise IntegrityError(f"Cannot validate ML surface shard: {exc}") from exc


def _verified_ml_campaign(record, store, identity, manifest, frames, points, grid):
    """Return a completed campaign only after checking every publication layer."""
    completed = [a for a in record.attempts if a.metadata.get("ml_campaign_sha256") == identity
                 and a.status == "completed"]
    if not completed:
        return None
    attempt, row_id = completed[-1], record.request.matrix_row_id
    if (attempt.converged is not True or attempt.validation_status != "validated-for-protocol"
            or attempt.metadata.get("execution_kind") != "real" or not attempt.artifacts
            or attempt.metadata.get("role") != "ML-screening-campaign"
            or attempt.metadata.get("energy_culling_authorized") is not False
            or attempt.metadata.get("matrix_row_id") != row_id
            or attempt.engine != manifest.backend or attempt.method != manifest.family
            or attempt.engine_version != manifest.package_version
            or attempt.metadata.get("model") != manifest.model_dump(mode="json")):
        raise IntegrityError("Completed ML campaign lacks validated real native evidence")
    prefix = f"attempts/{attempt.attempt_id}/"
    paths = {}
    for artifact in attempt.artifacts:
        if not artifact.path.startswith(prefix) or artifact.path in paths:
            raise IntegrityError("ML campaign artifact escapes its own attempt or is duplicated")
        path = confined_file(store.run_dir, artifact.path)
        if path.stat().st_size != artifact.size_bytes or file_digest(path) != artifact.sha256:
            raise IntegrityError("Completed ML campaign artifact changed")
        paths[artifact.path] = path
    required = ["ml-campaign.json", "ml-request.json", "ml-result.json"]
    if row_id == "T2-1min":
        required.append("ml-surface.h5")
    if any(prefix + name not in paths for name in required):
        raise IntegrityError("Completed ML campaign lacks its native/derived receipt or surface shard")
    receipt = paths[prefix + "ml-campaign.json"]
    payload = read_json(receipt)
    manifest_sha = digest_json(manifest.model_dump(mode="json"))
    if (attempt.metadata.get("derived_result_sha256") != file_digest(receipt)
            or payload.get("schema_version") != "topos-ml-campaign/0.1.0"
            or payload.get("campaign_sha256") != identity or payload.get("model_manifest_sha256") != manifest_sha):
        raise IntegrityError("ML campaign derived receipt differs from the declared identity/hash")
    try:
        results = [EngineResult.model_validate(item) for item in payload["frame_results"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrityError(f"Invalid ML campaign frame receipt: {exc}") from exc
    _validate_result_batch(results, frames, manifest, receipt.parent)
    derived = _derived_campaign(row_id, results, points, grid)
    if (digest_json(payload.get("derived")) != digest_json(derived)
            or digest_json(attempt.metadata.get("derived")) != digest_json(derived)
            or attempt.command != results[0].command):
        raise IntegrityError("Published ML derived result differs from retained native predictions")
    name, value = (("electronic_interaction", derived["electronic_interaction_hartree"])
                   if row_id == "T5-1min" else ("ML_surface_energies", derived["energies_hartree"]))
    if (len(attempt.quantities) != 1 or attempt.quantities[0].name != name
            or attempt.quantities[0].value != value or attempt.quantities[0].units != "hartree"
            or attempt.quantities[0].attempt_id != attempt.attempt_id
            or attempt.quantities[0].validity != "validated-for-protocol"
            or attempt.quantities[0].method != manifest.family):
        raise IntegrityError("Published ML quantity differs from its native derived receipt")
    if row_id == "T2-1min":
        _validate_surface(paths[prefix + "ml-surface.h5"], identity, manifest_sha, frames, points, derived)
    return attempt, derived


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
    def stopped():
        cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled or time.monotonic() >= deadline:
            record.status = "cancelled" if cancelled else "timed-out"
            record.metadata["termination_reason"] = "ML campaign stopped before execution or completed-cache publication"
            store.commit(record)
            return True
        return False

    if stopped():
        return True
    identity = digest_json({"row": row_id, "model": manifest.model_dump(mode="json"),
                            "frames": [m.model_dump(mode="json") for m in frames],
                            "grid": inputs.ml_grid.model_dump(mode="json") if inputs.ml_grid else None})
    cached = _verified_ml_campaign(record, store, identity, manifest, frames, points, inputs.ml_grid)
    if cached is not None:
        if stopped():
            return True
        cached_attempt, derived = cached
        record.metadata["ml_campaign"] = {"attempt_id": cached_attempt.attempt_id, "derived": derived}
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
    record.metadata.pop("ml_campaign", None)
    store.commit(record)
    folder = store.run_dir / "attempts" / attempt.attempt_id
    runner = MLRunner(manifest, workflow.base_runtime, gpu_index=inputs.ml_gpu_index,
                      gpu_memory_mb=inputs.ml_gpu_memory_mb)
    try:
        def check_stop():
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("ML campaign cancelled before publication")
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError("ML campaign budget exhausted before publication")
            return seconds

        remaining = check_stop()
        results = runner.evaluate_frames(frames, folder, record.request.resources.model_copy(update={"budget_seconds": remaining}),
                                         cancel_event=cancel_event)
        if not results:
            raise IntegrityError("ML inference returned no native results")
        first = results[0]
        attempt.command, attempt.engine_version = first.command, first.engine_version
        attempt.diagnostics = first.diagnostics
        if first.status != "completed":
            attempt.status = record.status = first.status
            attempt.converged, attempt.validation_status = False, "not-evaluated"
            attempt.finished_at = utc_now()
            attempt.artifacts = [a.model_copy(update={"path": Path(a.path).relative_to(store.run_dir).as_posix()})
                                 for a in artifact_inventory(folder)]
            store.commit(record)
            return True
        _validate_result_batch(results, frames, manifest, folder)
        attempt.metadata["execution_kind"] = "real"
        check_stop()
        derived = _derived_campaign(row_id, results, points, inputs.ml_grid)
        if row_id == "T5-1min":
            quantity = Quantity(name="electronic_interaction", value=derived["electronic_interaction_hartree"],
                units="hartree", method=manifest.family, attempt_id=attempt.attempt_id,
                validity="validated-for-protocol", definition="frozen-inc paired ML committee interaction; uncalibrated screening only")
        else:
            quantity = Quantity(name="ML_surface_energies", value=derived["energies_hartree"], units="hartree",
                method=manifest.family, attempt_id=attempt.attempt_id, validity="validated-for-protocol",
                definition="explicit frozen-iso model potential at every recorded finite grid point")
            shard = folder / "ml-surface.h5"
            with h5py.File(shard, "x") as handle:
                handle.attrs.update(schema_version="topos-ml-surface/0.1.0", campaign_sha256=identity,
                                    model_manifest_sha256=first.metadata["manifest_sha256"],
                                    geometry_policy="frozen-iso", energy_definition="unvalidated model potential; boundary exploration only")
                dataset = handle.create_dataset("grid", data=np.asarray(points))
                dataset.attrs["columns"] = "dx_A,dy_A,dz_A,rx_deg,ry_deg,rz_deg; extrinsic xyz Euler"
                dataset = handle.create_dataset("coordinates", data=np.asarray([m.coordinates for m in frames]), compression="gzip")
                dataset.attrs["units"] = "angstrom"
                dataset = handle.create_dataset("energies", data=np.asarray(derived["energies_hartree"]))
                dataset.attrs["units"] = "hartree"
                dataset = handle.create_dataset("gradients", data=np.asarray(derived["gradients_hartree_per_bohr"]), compression="gzip")
                dataset.attrs["units"] = "hartree/bohr"
                handle.create_dataset("symbols", data=np.asarray(record.request.molecule.symbols, dtype=h5py.string_dtype()))
                handle.flush()
            with shard.open("rb") as stream:
                os.fsync(stream.fileno())
            fsync_directory(folder)
        receipt = folder / "ml-campaign.json"
        atomic_json(receipt, {"schema_version": "topos-ml-campaign/0.1.0", "campaign_sha256": identity, "derived": derived,
                             "model_manifest_sha256": first.metadata["manifest_sha256"],
                             "frame_results": [r.model_dump(mode="json", exclude={"artifacts"}) for r in results]})
        check_stop()
        attempt.artifacts = [a.model_copy(update={"path": Path(a.path).relative_to(store.run_dir).as_posix(),
            "role": "derived-output" if Path(a.path).name == "ml-campaign.json" else
                    "ML-surface-shard" if Path(a.path).name == "ml-surface.h5" else a.role})
            for a in artifact_inventory(folder)]
        attempt.quantities = [quantity]
        attempt.metadata.update(execution_kind="real", derived_result_sha256=file_digest(receipt), derived=derived,
            limitations=["Model disagreement is not calibrated DFT error", "No ML energy culling without independent G4 correlation audit"])
        # All raw and derived files exist durably before completion is proposed.
        # The same strict validator used on resume checks this pending commit.
        attempt.status, attempt.converged, attempt.validation_status = "completed", True, "validated-for-protocol"
        attempt.finished_at = utc_now()
        _verified_ml_campaign(record, store, identity, manifest, frames, points, inputs.ml_grid)
        check_stop()
        record.metadata["ml_campaign"] = {"attempt_id": attempt.attempt_id, "derived": derived}
        record.status = "completed"
        store.commit(record)
        return True
    except Exception as exc:
        from .base_integration import BaseIntegrationError

        # A commit can publish its atomic pointer and then lose its caller's
        # acknowledgement. Do not rewrite an immutable finished attempt when
        # the complete published snapshot independently verifies.
        try:
            published = RunRecord.model_validate(store.load())
            finished = next((a for a in published.attempts if a.attempt_id == attempt.attempt_id), None)
            if finished is not None and finished.status not in {"queued", "running"}:
                if finished.status == "completed":
                    verified = _verified_ml_campaign(published, store, identity, manifest, frames, points, inputs.ml_grid)
                    if verified is None or verified[0].attempt_id != attempt.attempt_id:
                        raise IntegrityError("Published ML completion belongs to another campaign")
                record.status, record.attempts, record.metadata = published.status, published.attempts, published.metadata
                return True
        except (ValueError, OSError):
            pass
        state = ("unavailable" if isinstance(exc, (BaseIntegrationError, ImportError)) else
                 "cancelled" if isinstance(exc, InterruptedError) else
                 "timed-out" if isinstance(exc, TimeoutError) else "failed")
        attempt.status = record.status = state
        attempt.converged, attempt.validation_status = False, "rejected"
        attempt.finished_at = utc_now()
        attempt.quantities = []
        attempt.diagnostics["reason"] = str(exc)
        attempt.diagnostics["exception_type"] = type(exc).__name__
        record.metadata["termination_reason"] = str(exc)
        record.metadata.pop("ml_campaign", None)
        attempt.artifacts = []
        if folder.is_dir() and not folder.is_symlink():
            try:
                attempt.artifacts = [a.model_copy(update={"path": Path(a.path).relative_to(store.run_dir).as_posix()})
                                     for a in artifact_inventory(folder)]
            except (ValueError, OSError) as inventory_error:
                attempt.diagnostics["artifact_inventory_error"] = str(inventory_error)
        store.commit(record)
        return True
