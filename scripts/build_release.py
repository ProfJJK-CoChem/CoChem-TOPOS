"""Build reproducible unsigned TOPOS candidate archives; no publication or tagging."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

SOURCE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOURCE_ROOT))
from topos.release import (  # noqa: E402
    dependency_inventory,
    sha256,
    source_inventory,
)

BUILD_TOOLS = {"setuptools": "80.9.0", "wheel": "0.45.1", "build": "1.3.0", "packaging": "25.0"}
DEFAULT_EPOCH = 1767225600  # 2026-01-01 UTC: archive metadata, never an execution timestamp.
EVIDENCE_TEXT_SUFFIXES = {".txt", ".inp", ".log", ".stdout", ".stderr", ".out", ".hess", ".engrad", ".xyz"}


def _retained_path(base: Path, name: str, evidence: Path) -> Path:
    """Only scoped portable member names, never original machine/archive paths."""
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name or "\0" in name
            or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
            or PurePosixPath(name).as_posix() != name):
        raise ValueError("Unsafe retained evidence member path")
    path = base / name
    if not path.is_relative_to(evidence):
        raise ValueError("Retained evidence member escapes its source evidence directory")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError("Retained evidence sources must not be symlinks")
        if ancestor == evidence:
            break
    if not path.resolve().is_relative_to(evidence.resolve()):
        raise ValueError("Retained evidence member escapes its source evidence directory")
    return path


def verify_evidence_indices(root: Path, files: set[Path]) -> dict[str, dict[str, str]]:
    """Verify explicit retained members only; origin/provenance fields stay inert.

    Index hashes already belong to included_source_sha256. Members cannot index
    their own index, so no circular archive/index checksum is required.
    """
    evidence = root / ".docs/evidence"
    if (evidence.is_symlink() or (root / ".docs").is_symlink()
            or not evidence.resolve().is_relative_to(root.resolve())):
        raise ValueError("Retained evidence sources must not be symlinks")
    result = {}
    for index in sorted(evidence.rglob("*INDEX.json")):
        if index not in files or index.is_symlink():
            raise ValueError("Retained evidence index is absent from selected source files")
        payload = json.loads(index.read_text())
        if not isinstance(payload, dict):
            raise ValueError("Retained evidence index must be an object")
        rows = []
        for collection in ("files", "receipts", "all_retained_members"):
            if collection not in payload:
                continue
            entries = payload[collection]
            if isinstance(entries, dict) and collection == "files":
                base = _retained_path(index.parent, payload.get("directory"), evidence)
                rows.extend((base, name, entry) for name, entry in entries.items())
            elif isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError("Retained evidence member record must be an object")
                    rows.append((index.parent, entry.get("retained_path", entry.get("path")), entry))
            else:
                raise ValueError("Unsupported retained evidence membership collection")
        if not rows:
            raise ValueError("Retained evidence index requires explicit nonempty scoped members")
        selected = {}
        for base, name, entry in rows:
            path = _retained_path(base, name, evidence)
            if (not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
                raise ValueError("Retained evidence member requires its exact SHA256")
            if path == index:
                raise ValueError("Retained evidence index cannot contain its own circular checksum")
            if path not in files or not path.is_file():
                raise ValueError("Indexed retained evidence member is missing or excluded from source archive")
            data = path.read_bytes()
            try:
                data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Retained source evidence must be UTF8 text, not binary artifacts") from exc
            if b"\0" in data:
                raise ValueError("Retained source evidence must be text, not binary artifacts")
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("Retained evidence member checksum differs from its index")
            for size_key in ("bytes", "size_bytes"):
                if size_key in entry and (type(entry[size_key]) is not int or len(data) != entry[size_key]):
                    raise ValueError("Retained evidence member size differs from its index")
            relative = path.relative_to(root).as_posix()
            if relative in selected:
                raise ValueError("Duplicate retained evidence member in one index")
            selected[relative] = entry["sha256"]
        result[index.relative_to(root).as_posix()] = selected
    return result


def verify_archived_evidence(path: Path, indices: dict[str, dict[str, str]], hashes: dict[str, str]) -> None:
    """Reparse each built sdist and compare all indexed member/index bytes."""
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        roots = {PurePosixPath(member.name).parts[0] for member in members if member.name}
        if len(roots) != 1:
            raise ValueError("Source archive must have one extraction root")
        prefix = roots.pop()
        expected = {name: hashes[name] for name in indices}
        for collection in indices.values():
            expected.update(collection)
        names = [member.name for member in members]
        for name, digest in expected.items():
            archived = prefix + "/" + name
            if names.count(archived) != 1:
                raise ValueError("Indexed retained evidence is missing or duplicated in built source archive")
            member = archive.getmember(archived)
            if not member.isfile():
                raise ValueError("Archived retained evidence must be a regular file")
            stream = archive.extractfile(member)
            if stream is None or hashlib.sha256(stream.read()).hexdigest() != digest:
                raise ValueError("Built source archive changed indexed retained evidence bytes")


def release_files(root: Path) -> list[Path]:
    selected = {root / name for name in ("README.md", "LICENSE", "CITATION.cff", "pyproject.toml", "setup.py",
                                         "MANIFEST.in", "requirements.txt", "cochem_topos_web.py")}
    for folder, suffixes in {"topos": {".py", ".json"}, "scripts": {".py", ".txt"},
                            "tests": {".py", ".txt", ".json", ".stdout", ".out", ".hess", ".engrad", ".inp"},
                            "examples": {".json", ".xyz"},
                            ".docs": {".md", ".json", ".patch", ".xml"}, "wiki": {".md"},
                            ".github/workflows": {".yml"}}.items():
        selected.update(path for path in (root / folder).rglob("*") if path.suffix in suffixes)
    selected.update(path for path in (root / ".docs/evidence").rglob("*")
                    if path.suffix in EVIDENCE_TEXT_SUFFIXES)
    result = []
    for path in sorted(selected):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise ValueError(f"Release sources must not be symlinks: {path}")
        if path.is_file():
            result.append(path)
    indices = verify_evidence_indices(root, set(result))
    scoped = {name for members in indices.values() for name in members}
    # New raw evidence formats require explicit index membership. This avoids
    # sweeping unrelated logs, native outputs or environment files into sources.
    return [path for path in result if not (
        path.is_relative_to(root / ".docs/evidence") and path.suffix in EVIDENCE_TEXT_SUFFIXES
        and path.relative_to(root).as_posix() not in scoped)]


def normalize_archive(path: Path, epoch: int) -> None:
    """Normalize container metadata only; package file contents stay unchanged."""
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            values = [(item.filename, archive.read(item), item.external_attr) for item in archive.infolist()]
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data, attributes in sorted(values):
                info = zipfile.ZipInfo(name, time.gmtime(epoch)[:6])
                info.create_system = 3
                info.external_attr = attributes
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data, compresslevel=9)
        path.write_bytes(output.getvalue())
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            members = [(item, archive.extractfile(item).read() if item.isfile() else None) for item in archive.getmembers()]
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for item, data in sorted(members, key=lambda pair: pair[0].name):
                if not (item.isfile() or item.isdir()):
                    raise ValueError("Release source archives cannot contain links or special files")
                item.uid = item.gid = 0
                item.uname = item.gname = ""
                item.mtime = epoch
                item.mode = 0o755 if item.isdir() else 0o644
                item.pax_headers = {}
                archive.addfile(item, io.BytesIO(data) if data is not None else None)
        with path.open("wb") as stream, gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=epoch, compresslevel=9) as output:
            output.write(raw.getvalue())


def build_candidate(root: Path, output: Path, *, epoch: int = DEFAULT_EPOCH) -> dict:
    root, output = root.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError("Candidate output must be a new directory outside the source checkout")
    if not 315532800 <= epoch <= 4354819198:
        raise ValueError("SOURCE_DATE_EPOCH must fit the ZIP timestamp range (1980–2107)")
    actual = {name: importlib.metadata.version(name) for name in BUILD_TOOLS}
    if actual != BUILD_TOOLS:
        raise RuntimeError("Install the exact scripts/release-build-requirements.txt before building")
    files = release_files(root)
    file_hashes = {str(path.relative_to(root)): sha256(path) for path in files}
    evidence_indices = verify_evidence_indices(root, set(files))
    executable_identity = source_inventory(root)
    output.mkdir(parents=True)
    env = os.environ.copy()
    env.update(SOURCE_DATE_EPOCH=str(epoch), PYTHONHASHSEED="0")
    env.pop("PYTHONPATH", None)
    comparisons = []
    with tempfile.TemporaryDirectory(prefix="topos-reproducible-") as scratch:
        scratch = Path(scratch)
        for number in (1, 2):
            stage = scratch / f"source-{number}"
            stage.mkdir()
            for path in files:
                target = stage / path.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
                target.chmod(0o644)
                os.utime(target, (epoch, epoch))
            verify_evidence_indices(stage, {stage / path.relative_to(root) for path in files})
            dist = scratch / f"dist-{number}"
            log = output / f"build-{number}.log"
            with log.open("wb") as stream:
                completed = subprocess.run([sys.executable, "-m", "build", "--no-isolation", "--outdir", str(dist), str(stage)],
                                           cwd=scratch, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
            if completed.returncode:
                raise RuntimeError(f"Candidate build {number} failed; inspect {log}")
            artifacts = list(dist.iterdir())
            if len(artifacts) != 2 or len(list(dist.glob("*.whl"))) != 1 or len(list(dist.glob("*.tar.gz"))) != 1:
                raise RuntimeError("Expected exactly one wheel and one source distribution")
            for path in artifacts:
                normalize_archive(path, epoch)
                if path.name.endswith(".tar.gz"):
                    verify_archived_evidence(path, evidence_indices, file_hashes)
            comparisons.append({path.name: sha256(path) for path in artifacts})
            if number == 1:
                for path in artifacts:
                    shutil.copyfile(path, output / path.name)
        if comparisons[0] != comparisons[1]:
            raise RuntimeError("Independent candidate builds produced different archive bytes")
    if file_hashes != {str(path.relative_to(root)): sha256(path) for path in release_files(root)}:
        raise RuntimeError("Release source changed while building; candidate cannot be certified")
    wheel = next(output.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if any(name.startswith(("frontend/", "mechanics/", "cascade_engine/", "core_engine/")) for name in names):
            raise RuntimeError("TOPOS wheel contains a retired package or overwrites BASE's namespace")
        metadata_file = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata_hash = hashlib.sha256(archive.read(metadata_file)).hexdigest()
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    manifest = {"schema_version": "topos-distribution-candidate/0.1.0", "name": project["name"], "version": project["version"],
                "disposition": "unsigned-candidate", "published": False, "release_certified": False,
                "source_date_epoch": epoch, "archive_metadata_scope": "normalized container timestamps/owners; retained file contents",
                "reproducible_archives": True, "repeated_build_sha256": comparisons,
                "source_sha256": executable_identity, "included_source_sha256": file_hashes,
                "retained_evidence_indices": evidence_indices,
                "build_tools": actual, "python": sys.version, "wheel_metadata_sha256": metadata_hash,
                "requirements": project.get("dependencies", []), "optional_dependencies": project.get("optional-dependencies", {}),
                "build_environment_dependencies": dependency_inventory(),
                "artifacts": [{"name": name, "sha256": digest, "bytes": (output / name).stat().st_size}
                              for name, digest in sorted(comparisons[0].items())]}
    (output / "distribution-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    checksum_files = sorted([*output.glob("*.whl"), *output.glob("*.tar.gz"), output / "distribution-manifest.json"])
    (output / "SHA256SUMS").write_text("".join(f"{sha256(path)}  {path.name}\n" for path in checksum_files))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-date-epoch", type=int, default=DEFAULT_EPOCH)
    args = parser.parse_args()
    try:
        result = build_candidate(args.source_root, args.output, epoch=args.source_date_epoch)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Candidate build failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "built", "reproducible_archives": True, "published": False,
                      "release_certified": False, "artifacts": result["artifacts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
