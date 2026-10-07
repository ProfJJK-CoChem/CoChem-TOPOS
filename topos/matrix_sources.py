"""Import native search observations from explicitly selected verified local runs."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Literal

from pydantic import Field

from .models import Artifact, Contract, Molecule, RunRecord
from .sampling import SampledConformer
from .storage import IntegrityError, RunStore, atomic_json, confined_file, digest_json, file_digest


class SourceEnsembleInput(Contract):
    run_dir: str
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sampler_attempt_id: str | None = None


class ImportedEnsemble(Contract):
    frames: list[SampledConformer]
    artifacts: list[Artifact]
    provenance: dict


def import_native_ensemble(source: SourceEnsembleInput, *, expected_engine: Literal["goat", "crest"],
                           expected_molecule: Molecule, destination: Path | str) -> ImportedEnsemble:
    if "://" in source.run_dir:
        raise ValueError("Native ensemble inputs must identify a verified local RunStore directory")
    source_dir = Path(source.run_dir).expanduser().resolve(strict=True)
    if not source_dir.is_dir() or not (source_dir / "CURRENT.json").is_file():
        raise ValueError("Native ensemble source is not a completed local snapshot store")
    store = RunStore(source_dir)
    raw = store.load()
    if digest_json(raw) != source.record_sha256:
        raise IntegrityError("Native source record differs from its explicitly selected SHA-256")
    record = RunRecord.model_validate(raw)
    manifest = store.verify()
    snapshot = store.snapshots / manifest["snapshot_id"]
    if manifest["record_sha256"] != source.record_sha256:
        raise IntegrityError("Native source changed during snapshot selection")
    expected_version = "6.1.1" if expected_engine == "goat" else "3.0.2"
    candidates = [a for a in record.attempts if a.status == "completed"
                  and a.validation_status == "validated-for-protocol" and a.command and a.artifacts
                  and a.metadata.get("execution_kind") == "real" and a.engine_version == expected_version
                  and (a.engine == "orca" and a.metadata.get("role") == "matrix-goat-sampler"
                       if expected_engine == "goat" else a.engine == "crest" and a.metadata.get("role") == "sampler")]
    if source.sampler_attempt_id:
        candidates = [a for a in candidates if a.attempt_id == source.sampler_attempt_id]
    if len(candidates) != 1:
        raise ValueError("Select exactly one verified completed native sampler attempt; ambiguous or unverified origins are rejected")
    sampler = candidates[0]
    raw_frames = sampler.metadata.get("raw_ensemble")
    if not isinstance(raw_frames, list) or not raw_frames or len(raw_frames) > 10000:
        raise ValueError("Native sampler has no bounded retained raw ensemble")
    frames = [SampledConformer.model_validate(frame) for frame in raw_frames]
    required_source = "GOAT" if expected_engine == "goat" else "CREST"
    identity = ("symbols", "atom_ids", "isotopes", "charge", "multiplicity", "environment",
                "fragments", "fragment_states", "stereochemistry", "bonds")
    for frame in frames:
        if frame.source != required_source or any(getattr(frame.molecule, key) != getattr(expected_molecule, key) for key in identity):
            raise ValueError("Native ensemble changes source identity, atom mapping, isotopes, electronic state or fragment metadata")

    def native_file(name: str) -> Path:
        found = [a for a in sampler.artifacts if Path(a.path).name == name]
        if len(found) != 1:
            raise IntegrityError(f"Native source requires exactly one retained {name} artifact")
        return confined_file(snapshot, "artifacts/" + found[0].path)

    # A valid snapshot proves retention integrity, not the scientific relation
    # between its structured metadata and the native files. Reparse that relation.
    from .engines import _engine_version
    from .goat import parse_goat_ensemble
    from .sampling import parse_crest_ensemble

    if expected_engine == "goat":
        observed = parse_goat_ensemble(native_file("goat.finalensemble.xyz"), expected_molecule)
        stdout = native_file("goat.stdout").read_text(errors="replace")
        if (_engine_version(stdout, "orca") != expected_version or "ORCA TERMINATED NORMALLY" not in stdout
                or "Writing final ensemble to" not in stdout
                or not re.search(r"Global minimum found\s*!", stdout, re.I)):
            raise IntegrityError("Retained GOAT output does not establish its version and native convergence")
    else:
        observed = parse_crest_ensemble(native_file("crest_conformers.xyz"), expected_molecule)
        stdout = native_file("crest.stdout").read_text(errors="replace")
        version = native_file("crest-version.stdout").read_text(errors="replace")
        if (not re.search(r"(?im)^\s*crest\s+3\.0\.2\s*$", version)
                or "CREST terminated normally." not in stdout or "Use of GFN2-xTB requested" not in stdout):
            raise IntegrityError("Retained CREST output does not establish its version, potential and normal termination")
    if len(observed) != len(frames) or any(
        actual.source != declared.source or actual.source_index != declared.source_index
        or actual.energy_hartree != declared.energy_hartree
        or actual.molecule.coordinates != declared.molecule.coordinates
        for actual, declared in zip(observed, frames, strict=True)
    ):
        raise IntegrityError("Structured native ensemble differs from its retained native XYZ observations")
    target_root = Path(destination).resolve() / source.record_sha256
    if target_root.is_symlink():
        raise IntegrityError("Native source import root cannot be a symlink")
    target_root.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for artifact in sampler.artifacts:
        original = confined_file(snapshot, "artifacts/" + artifact.path)
        target = target_root / "artifacts" / artifact.path
        if not target.resolve().is_relative_to(target_root.resolve()):
            raise IntegrityError("Native artifact destination escapes the import directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise IntegrityError("Native import artifact cannot be a symlink")
        if not target.exists():
            with original.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
        if target.stat().st_size != artifact.size_bytes or file_digest(target) != artifact.sha256:
            raise IntegrityError("Imported native artifact bytes do not match the source snapshot")
        artifacts.append(artifact.model_copy(update={"path": str(target), "role": "imported-native-search-evidence"}))
    for name, payload in (("source-record.json", raw), ("source-manifest.json", manifest)):
        path = target_root / name
        if path.is_symlink():
            raise IntegrityError("Native source identity file cannot be a symlink")
        if path.exists():
            if json.loads(path.read_text()) != payload:
                raise IntegrityError("Native source import changed after it was established")
        else:
            atomic_json(path, payload)
        artifacts.append(Artifact(path=str(path), sha256=file_digest(path), size_bytes=path.stat().st_size,
                                  role="imported-native-source-identity"))
    return ImportedEnsemble(frames=frames, artifacts=artifacts, provenance={
        "source_run_id": record.run_id, "record_sha256": source.record_sha256,
        "snapshot_id": manifest["snapshot_id"], "sampler_attempt_id": sampler.attempt_id,
        "sampler": required_source, "engine_version": sampler.engine_version,
        "native_frame_count": len(frames), "origin_validation": "verified native sampler record and immutable raw artifacts",
        "energy_scope": "native search energies; require common-level comparison before scientific ranking",
    })
