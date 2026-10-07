"""Immutable, checksummed HDF5 run snapshots with one atomic commit pointer.

Readers only inspect completed snapshots. Writers hold a per-run process lock;
this deliberately does not use SWMR. Durability relies on local filesystems
supporting atomic replacement and fsync, rather than network/object stores.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import h5py
from filelock import FileLock

SCHEMA_VERSION = "topos/0.1.0"
SNAPSHOT_SCHEMA = "topos-snapshot/0.1.0"


class IntegrityError(ValueError):
    """A record, manifest or artifact does not match its declared identity."""


def json_bytes(value: Any) -> bytes:
    """Canonical finite JSON used for identity, checksums and reproducible export."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest_json(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise IntegrityError(f"Cannot read valid JSON at {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"Expected JSON object at {path.name}")
    return value


def fsync_directory(path: Path) -> None:
    if os.name == "nt":  # Windows does not expose directory fsync through os.open.
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path: Path, value: Any) -> None:
    """Write and fsync before publishing within the same filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise IntegrityError("Artifact paths must be nonempty portable relative paths")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(p in {"..", "."} for p in value.split("/")):
        raise IntegrityError(f"Unsafe relative artifact path: {value}")
    if any(":" in p for p in relative.parts) or str(relative) != value:
        raise IntegrityError(f"Noncanonical artifact path: {value}")
    return value


def confined_file(root: Path, relative: str) -> Path:
    relative = safe_relative(relative)
    path = root / relative
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise IntegrityError(f"Symlink is not an immutable artifact: {relative}")
    if not path.is_file():
        raise IntegrityError(f"Missing artifact: {relative}")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise IntegrityError(f"Artifact escapes run: {relative}") from exc
    return path


def record_dict(record: Any) -> dict[str, Any]:
    if hasattr(record, "model_dump"):
        record = record.model_dump(mode="json")
    if not isinstance(record, Mapping):
        raise IntegrityError("Run record must be a RunRecord or JSON mapping")
    from .models import RunRecord

    try:
        result = RunRecord.model_validate(dict(record)).model_dump(mode="json")
        result = json.loads(json_bytes(result))
    except (TypeError, ValueError) as exc:
        raise IntegrityError(f"Invalid typed run record: {exc}") from exc
    if result.get("schema_version") != SCHEMA_VERSION:
        raise IntegrityError(f"Unsupported run schema: {result.get('schema_version')}")
    if not isinstance(result.get("run_id"), str) or not result["run_id"]:
        raise IntegrityError("Run record requires run_id")
    attempts = result.get("attempts", [])
    attempt_ids = [a.get("attempt_id") for a in attempts]
    if any(not isinstance(i, str) or not i for i in attempt_ids):
        raise IntegrityError("Every attempt requires an identifier")
    if len(set(attempt_ids)) != len(attempt_ids):
        raise IntegrityError("Duplicate attempt identifiers")
    for attempt in attempts:
        if attempt.get("run_id") != result["run_id"]:
            raise IntegrityError("Attempt belongs to another run")
        parent = attempt.get("parent_attempt_id")
        if parent and (parent not in attempt_ids or parent == attempt["attempt_id"]):
            raise IntegrityError("Invalid attempt parent")
        seen = {attempt["attempt_id"]}
        parents = {a["attempt_id"]: a.get("parent_attempt_id") for a in attempts}
        while parent:
            if parent in seen:
                raise IntegrityError("Attempt ancestry contains a cycle")
            seen.add(parent)
            parent = parents.get(parent)
    candidates = result.get("candidates", [])
    candidate_ids = [c.get("candidate_id") for c in candidates]
    if any(not isinstance(i, str) or not i for i in candidate_ids):
        raise IntegrityError("Every candidate requires an identifier")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise IntegrityError("Duplicate candidate identifiers")
    if any(c.get("attempt_id") and c["attempt_id"] not in attempt_ids for c in candidates):
        raise IntegrityError("Candidate references an unknown attempt")
    return result


def artifact_inventory(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Membership is explicit; nothing is inferred by globbing a run directory."""
    references = list(record.get("artifacts", []))
    for attempt in record.get("attempts", []):
        references.extend(attempt.get("artifacts", []))
    inventory: dict[str, dict[str, Any]] = {}
    for reference in references:
        entry = dict(reference)
        path = safe_relative(entry.get("path", ""))
        if not re.fullmatch(r"[a-f0-9]{64}", entry.get("sha256", "")):
            raise IntegrityError(f"Invalid artifact SHA-256: {path}")
        size = entry.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise IntegrityError(f"Invalid artifact size: {path}")
        if path in inventory:
            previous = inventory[path]
            if (previous["sha256"], previous["size_bytes"]) != (entry["sha256"], size):
                raise IntegrityError(f"Conflicting membership for artifact: {path}")
        else:
            inventory[path] = entry
    return [inventory[p] for p in sorted(inventory)]


class RunStore:
    """An isolated run directory with immutable snapshots and verified recovery."""

    def __init__(
        self, run_dir: str | Path, *, lock_timeout: float = 10.0,
        max_snapshot_bytes: int | None = None,
    ) -> None:
        self.run_dir = Path(run_dir).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots = self.run_dir / "snapshots"
        self.snapshots.mkdir(exist_ok=True)
        self.lock = FileLock(str(self.run_dir / ".writer.lock"), timeout=lock_timeout)
        self.current = self.run_dir / "CURRENT.json"
        self.max_snapshot_bytes = max_snapshot_bytes

    def _pointer(self) -> dict[str, Any]:
        if not self.current.exists():
            raise FileNotFoundError(f"No committed run snapshot in {self.run_dir}")
        pointer = read_json(self.current)
        if pointer.get("schema_version") != SNAPSHOT_SCHEMA:
            raise IntegrityError("Unsupported commit pointer schema")
        for key in ("snapshot_id", "manifest_sha256"):
            if not re.fullmatch(r"[a-f0-9]{64}", str(pointer.get(key, ""))):
                raise IntegrityError(f"Invalid commit pointer {key}")
        return pointer

    def _read_snapshot(self, pointer: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        directory = self.snapshots / pointer["snapshot_id"]
        if directory.is_symlink():
            raise IntegrityError("Snapshot directory cannot be a symlink")
        manifest = read_json(confined_file(directory, "manifest.json"))
        if digest_json(manifest) != pointer["manifest_sha256"]:
            raise IntegrityError("Snapshot manifest checksum mismatch")
        if manifest.get("schema_version") != SNAPSHOT_SCHEMA:
            raise IntegrityError("Unsupported snapshot schema")
        payload = confined_file(directory, "record.h5")
        if file_digest(payload) != manifest.get("hdf5_sha256"):
            raise IntegrityError("HDF5 snapshot checksum mismatch")
        try:
            with h5py.File(payload, "r") as handle:
                raw = handle["record_json"][()]
                record = json.loads(raw)
                # Validate without rewriting immutable bytes with newly added
                # optional model defaults. Hashes identify the stored document,
                # not today's expanded serialization of an older valid schema.
                record_dict(record)
                if handle.attrs["schema_version"] != SCHEMA_VERSION:
                    raise IntegrityError("HDF5 schema differs from run record")
        except (OSError, KeyError, ValueError, TypeError) as exc:
            raise IntegrityError(f"Invalid HDF5 run snapshot: {exc}") from exc
        if record["run_id"] != manifest.get("run_id") or digest_json(record) != manifest.get("record_sha256"):
            raise IntegrityError("Run record identity mismatch")
        if manifest.get("snapshot_id") != pointer["snapshot_id"]:
            raise IntegrityError("Snapshot identity mismatch")
        entries = artifact_inventory(record)
        if entries != manifest.get("artifacts"):
            raise IntegrityError("Artifact membership differs from run record")
        expected = {"record.h5", "manifest.json"}
        for entry in entries:
            relative = "artifacts/" + entry["path"]
            artifact = confined_file(directory, relative)
            if artifact.stat().st_size != entry["size_bytes"] or file_digest(artifact) != entry["sha256"]:
                raise IntegrityError(f"Snapshot artifact checksum mismatch: {entry['path']}")
            expected.add(relative)
        actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
        if actual != expected:
            raise IntegrityError("Unexpected or missing snapshot payload files")
        return record, manifest

    def load(self) -> dict[str, Any]:
        return self._read_snapshot(self._pointer())[0]

    def verify(self) -> dict[str, Any]:
        return self._read_snapshot(self._pointer())[1]

    def snapshot_path(self) -> Path:
        pointer = self._pointer()
        self._read_snapshot(pointer)
        return self.snapshots / pointer["snapshot_id"]

    def commit(self, record: Any) -> dict[str, Any]:
        value = record_dict(record)
        entries = artifact_inventory(value)
        estimated = len(json_bytes(value)) + sum(a["size_bytes"] for a in entries)
        if self.max_snapshot_bytes is not None and estimated > self.max_snapshot_bytes:
            raise IntegrityError("Snapshot exceeds configured storage quota")
        with self.lock:
            previous = None
            if self.current.exists():
                previous = self.load()
                if previous["run_id"] != value["run_id"]:
                    raise IntegrityError("Run directory already belongs to another run")
                if previous.get("request") != value.get("request"):
                    from .models import RunRequest

                    expanded = RunRequest.model_validate(previous["request"]).model_dump(mode="json")
                    if expanded != value.get("request"):
                        raise IntegrityError("Immutable input/request changed; create a new run")
                    # A compatible reader may expose new optional defaults, but
                    # the original scientific request and its digest stay exact.
                    value["request"] = previous["request"]
                old_ids = {a["attempt_id"] for a in previous.get("attempts", [])}
                new_attempts = {a["attempt_id"]: a for a in value.get("attempts", [])}
                if not old_ids.issubset(new_attempts):
                    raise IntegrityError("A committed attempt cannot be removed")
                for old in previous["attempts"]:
                    new = new_attempts[old["attempt_id"]]
                    if old["status"] not in {"queued", "running"} and new != old:
                        raise IntegrityError("A finished attempt is immutable; create a linked new attempt")
                    if any(old[k] != new[k] for k in ("engine", "method", "parent_attempt_id")):
                        raise IntegrityError("Attempt identity cannot be changed")
                new_candidates = {c["candidate_id"]: c for c in value["candidates"]}
                for old in previous["candidates"]:
                    new = new_candidates.get(old["candidate_id"])
                    if new is None:
                        raise IntegrityError("A committed candidate cannot be removed")
                    if any(old[k] != new[k] for k in (
                        "molecule", "attempt_id", "energy_hartree", "gibbs_hartree", "comparison_protocol"
                    )):
                        raise IntegrityError("Candidate scientific payload is immutable; use a new candidate ID")
                if previous == value:
                    return self.verify()
            record_hash = digest_json(value)
            snapshot_id = digest_json({"record_sha256": record_hash, "artifacts": entries})
            destination = self.snapshots / snapshot_id
            if destination.exists():
                # An explicit retry may finish a interrupted pointer publication,
                # but recovery alone never guesses that an orphan was committed.
                manifest = read_json(confined_file(destination, "manifest.json"))
                pointer = {
                    "schema_version": SNAPSHOT_SCHEMA, "snapshot_id": snapshot_id,
                    "manifest_sha256": digest_json(manifest),
                }
                existing, _ = self._read_snapshot(pointer)
                if existing != value:
                    raise IntegrityError("Existing snapshot does not match the explicitly retried record")
                atomic_json(self.current, pointer)
                return manifest
            staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=self.snapshots))
            try:
                for entry in entries:
                    source = confined_file(self.run_dir, entry["path"])
                    target = staging / "artifacts" / entry["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open("rb") as reader, target.open("xb") as writer:
                        shutil.copyfileobj(reader, writer)
                        writer.flush()
                        os.fsync(writer.fileno())
                    if target.stat().st_size != entry["size_bytes"] or file_digest(target) != entry["sha256"]:
                        raise IntegrityError(f"Source artifact changed or checksum mismatch: {entry['path']}")
                payload = staging / "record.h5"
                with h5py.File(payload, "w") as handle:
                    handle.attrs["schema_version"] = SCHEMA_VERSION
                    handle.attrs["run_id"] = value["run_id"]
                    handle.create_dataset("record_json", data=json_bytes(value))
                    handle.create_group("candidates")
                    sealed = handle.create_group("deduplicated_isomers")
                    sealed.attrs["membership"] = "Requires a separate reviewed ensemble manifest"
                    for candidate in value.get("candidates", []):
                        group = handle["candidates"].create_group(
                            hashlib.sha256(candidate["candidate_id"].encode()).hexdigest()
                        )
                        group.attrs["candidate_id"] = candidate["candidate_id"]
                        group.create_dataset("record_json", data=json_bytes(candidate))
                        group.create_dataset(
                            "coordinates_angstrom", data=candidate["molecule"]["coordinates"], dtype="f8"
                        )
                    handle.flush()
                with payload.open("rb") as handle:
                    os.fsync(handle.fileno())
                manifest = {
                    "schema_version": SNAPSHOT_SCHEMA, "run_id": value["run_id"],
                    "snapshot_id": snapshot_id, "record_sha256": record_hash,
                    "hdf5_sha256": file_digest(payload), "artifacts": entries,
                }
                atomic_json(staging / "manifest.json", manifest)
                if self.max_snapshot_bytes is not None:
                    size = sum(p.stat().st_size for p in staging.rglob("*") if p.is_file())
                    if size > self.max_snapshot_bytes:
                        raise IntegrityError("Serialized snapshot exceeds configured storage quota")
                for directory in sorted((p for p in staging.rglob("*") if p.is_dir()), reverse=True):
                    fsync_directory(directory)
                fsync_directory(staging)
                os.replace(staging, destination)
                fsync_directory(self.snapshots)
                pointer = {
                    "schema_version": SNAPSHOT_SCHEMA, "snapshot_id": snapshot_id,
                    "manifest_sha256": digest_json(manifest),
                }
                self._read_snapshot(pointer)
                atomic_json(self.current, pointer)
                return manifest
            finally:
                if staging.exists():
                    shutil.rmtree(staging)

    def recover(self) -> dict[str, Any]:
        """Return only the verified committed generation; never guess from orphans."""
        with self.lock:
            return self.load()
