"""Build and assemble a complete, unsigned CoChem installation candidate.

This command never publishes or certifies a release. Native acceptance and the
source-bound scientific release gate remain separate retained evidence.
"""
from __future__ import annotations

import argparse
import email
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

# Scripts must also work from an extracted TOPOS source distribution.
SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))
from build_release import DEFAULT_EPOCH, normalize_archive  # noqa: E402
from setup_ecosystem import verified_release_wheels  # noqa: E402

PROJECTS = {"base": "1.1.0", "torq": "0.1.0"}
PACKAGE_VERSIONS = {"cochem-base": PROJECTS["base"], "cochem-topos": "0.1.0", "cochem-torq": PROJECTS["torq"]}
MODEL_SUFFIXES = {".pt", ".pth", ".safetensors", ".onnx", ".ckpt", ".gguf"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Required evidence must be a regular file: {path}")
    result = json.loads(path.read_text())
    if not isinstance(result, dict):
        raise ValueError(f"Evidence must be a JSON object: {path}")
    return result


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def confined_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (not name or "\\" in name or path.is_absolute() or ".." in path.parts
            or path.as_posix() != name.rstrip("/") or path.as_posix() == "."):
        raise ValueError(f"Unconfined archive path: {name}")
    return path


def audit_payload(name: str, data: bytes) -> None:
    confined_name(name)
    if data.startswith((b"\x7fELF", b"MZ", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf")):
        raise ValueError(f"Native executable is not part of this installation kit: {name}")
    if PurePosixPath(name).suffix.lower() in MODEL_SUFFIXES:
        raise ValueError(f"Model checkpoint is not part of this installation kit: {name}")


def audit_archive(path: Path) -> None:
    """Inspect every payload, without extracting untrusted archive members."""
    seen: set[str] = set()
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                confined_name(member.filename)
                if member.filename in seen:
                    raise ValueError("Duplicate wheel member")
                seen.add(member.filename)
                kind = (member.external_attr >> 16) & 0o170000
                if kind not in (0, 0o100000, 0o040000):
                    raise ValueError("Wheel links and special files are not supported")
                if not member.is_dir():
                    audit_payload(member.filename, archive.read(member))
    else:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                confined_name(member.name)
                if member.name in seen:
                    raise ValueError("Duplicate source archive member")
                seen.add(member.name)
                if not (member.isfile() or member.isdir()):
                    raise ValueError("Source archive links and special files are not supported")
                if member.isfile():
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ValueError("Source archive payload is absent")
                    audit_payload(member.name, stream.read())


def git_source(root: Path, pin: str, prefix: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{40}", pin):
        raise ValueError("Companion source requires an explicit full lowercase Git commit")
    actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", pin + "^{commit}"], text=True).strip()
    if actual != pin:
        raise ValueError("Git source commit differs from the requested companion pin")
    # Git archive applies text conversion settings too. The downloaded source
    # must preserve the reviewed Linux bytes regardless of Windows Git defaults.
    return subprocess.check_output(["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf",
                                    "-C", str(root), "archive", "--format=tar.gz", "--prefix=" + prefix + "/", pin])


def write_checksums(folder: Path, paths: list[Path]) -> None:
    (folder / "SHA256SUMS").write_text("".join(
        f"{digest(path)}  {path.relative_to(folder).as_posix()}\n" for path in sorted(paths)
    ))


def prepare_companions(roots: dict[str, Path], pins: dict[str, str], output: Path) -> dict:
    """Build companion wheels twice from the exact archived Git trees."""
    if output.exists():
        raise ValueError("Companion output must be a new directory")
    output.mkdir(parents=True)
    (output / "sources").mkdir()
    result = {"schema_version": "cochem-companion-build/0.1.0", "companions": {}}
    environment = os.environ.copy()
    environment.update(SOURCE_DATE_EPOCH=str(DEFAULT_EPOCH), PYTHONHASHSEED="0")
    environment.pop("PYTHONPATH", None)
    for project, version in PROJECTS.items():
        prefix = f"cochem_{project}-{version}"
        source = output / "sources" / f"{prefix}-{pins[project][:12]}.tar.gz"
        source.write_bytes(git_source(roots[project], pins[project], prefix))
        audit_archive(source)
        hashes = []
        with tempfile.TemporaryDirectory(prefix="cochem-companion-build-") as temporary:
            temporary = Path(temporary)
            for repeat in (1, 2):
                stage = temporary / f"build-{repeat}"
                stage.mkdir()
                with tarfile.open(source) as archive:
                    # audit_archive already rejected links, special files and traversal.
                    archive.extractall(stage, filter="data")
                destination = temporary / f"dist-{repeat}"
                log = output / f"{project}-build-{repeat}.log"
                with log.open("wb") as stream:
                    completed = subprocess.run(
                        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(destination), str(stage / prefix)],
                        cwd=temporary, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=False,
                    )
                if completed.returncode:
                    raise RuntimeError(f"Companion build failed; inspect {log}")
                wheels = list(destination.glob("*.whl"))
                if len(wheels) != 1:
                    raise ValueError("Expected one companion wheel per build")
                wheel = wheels[0]
                normalize_archive(wheel, DEFAULT_EPOCH)
                audit_archive(wheel)
                hashes.append(digest(wheel))
                if repeat == 1:
                    shutil.copyfile(wheel, output / wheel.name)
            if hashes[0] != hashes[1]:
                raise ValueError(f"{project} companion wheel builds are not reproducible")
        result["companions"][project] = {
            "source_commit": pins[project], "source_archive": str(source.relative_to(output)),
            "source_archive_sha256": digest(source), "wheel_name": wheel.name,
            "wheel_sha256": hashes[0], "repeated_wheel_sha256": hashes,
        }
    write_json(output / "companion-build-manifest.json", result)
    write_checksums(output, list(output.glob("*.whl")))
    return result


def checked_file(folder: Path, name: str, expected: str, size: int | None = None) -> Path:
    relative = confined_name(name)
    path = folder.joinpath(*relative.parts)
    if (not re.fullmatch(r"[0-9a-f]{64}", expected)
            or (size is not None and (type(size) is not int or size < 0))
            or path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(folder.resolve())
            or digest(path) != expected or (size is not None and path.stat().st_size != size)):
        raise ValueError(f"Artifact differs from its retained hash/size: {name}")
    return path


def verify_wheel_package(path: Path, name: str, version: str) -> None:
    with zipfile.ZipFile(path) as archive:
        records = [item for item in archive.namelist() if item.endswith(".dist-info/METADATA")]
        if len(records) != 1:
            raise ValueError("Wheel requires exactly one package metadata record")
        metadata = email.message_from_bytes(archive.read(records[0]))
        actual_name = (metadata.get("Name") or "").lower().replace("_", "-")
        if actual_name != name or metadata.get("Version") != version:
            raise ValueError("Wheel package name/version differs from the mandatory release set")


def verify_source_payload(path: Path, prefix: str, identity: dict[str, str]) -> None:
    if not identity:
        raise ValueError("Source hash inventory is empty")
    with tarfile.open(path, "r:gz") as archive:
        for name, expected in identity.items():
            relative = confined_name(name)
            member = archive.getmember(f"{prefix}/{relative.as_posix()}")
            if not member.isfile():
                raise ValueError("Declared source payload must be a regular file")
            stream = archive.extractfile(member)
            if stream is None or hashlib.sha256(stream.read()).hexdigest() != expected:
                raise ValueError(f"Source archive payload differs from retained source identity: {name}")


def verify_wheel_sources(path: Path, identity: dict[str, str]) -> None:
    with zipfile.ZipFile(path) as archive:
        for name, expected in identity.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError("Wheel payload differs from its declared controller source")


def verify_companion_source(path: Path, project: str, version: str) -> None:
    prefix = f"cochem_{project}-{version}"
    with tarfile.open(path, "r:gz") as archive:
        if any(PurePosixPath(member.name).parts[0] != prefix for member in archive):
            raise ValueError("Companion source archive has an unexpected extraction root")
        stream = archive.extractfile(prefix + "/pyproject.toml")
        if stream is None:
            raise ValueError("Companion source project metadata is absent")
        metadata = tomllib.loads(stream.read().decode())["project"]
        if metadata["name"].lower().replace("_", "-") != "cochem-" + project or metadata["version"] != version:
            raise ValueError("Companion source package differs from the mandatory release set")


def verify_inputs(candidate: Path, wheelhouse: Path, installation: Path) -> dict:
    manifest = read_json(candidate / "distribution-manifest.json")
    if (manifest.get("schema_version") != "topos-distribution-candidate/0.1.0"
            or manifest.get("version") != "0.1.0"
            or manifest.get("reproducible_archives") is not True):
        raise ValueError("Repeated TOPOS archive builds are required")
    artifacts = manifest.get("artifacts", [])
    if len(artifacts) != 2 or len({item["name"] for item in artifacts}) != 2:
        raise ValueError("Exactly one TOPOS wheel and source archive are required")
    archives = [checked_file(candidate, item["name"], item["sha256"], item["bytes"]) for item in artifacts]
    wheels = [path for path in archives if path.suffix == ".whl"]
    sources = [path for path in archives if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Exactly one TOPOS wheel and source archive are required")
    topos_wheel, source = wheels[0], sources[0]
    repeated = {path.name: digest(path) for path in archives}
    if manifest.get("repeated_build_sha256") != [repeated, repeated]:
        raise ValueError("Repeated TOPOS archive digests differ")
    for archive in archives:
        audit_archive(archive)
    included = manifest.get("included_source_sha256", {})
    source_identity = manifest.get("source_sha256", {})
    if not source_identity or any(included.get(name) != value for name, value in source_identity.items()):
        raise ValueError("Executable identity differs from the included source inventory")
    verify_source_payload(source, "cochem_topos-0.1.0", included)
    selected = verified_release_wheels(wheelhouse)
    if {path.name for path in wheelhouse.glob("*.whl")} != {path.name for path in selected.values()}:
        raise ValueError("Wheelhouse may contain only the mandatory release wheel set")
    for name, path in selected.items():
        audit_archive(path)
        verify_wheel_package(path, name, PACKAGE_VERSIONS[name])
    controller_payload = {name: value for name, value in source_identity.items()
                          if name.startswith("topos/") or name == "cochem_topos_web.py"}
    verify_wheel_sources(topos_wheel, controller_payload)
    if digest(selected["cochem-topos"]) != digest(topos_wheel):
        raise ValueError("Wheelhouse TOPOS differs from the candidate")
    clean = read_json(installation / "clean-install.json")
    receipt_path = installation / "acceptance" / "installed-acceptance.json"
    receipt = read_json(receipt_path)
    if (clean.get("schema_version") != "topos-clean-install/0.1.0"
            or clean.get("status") != "passed" or receipt.get("status") != "passed"
            or clean.get("acceptance_sha256") != digest(receipt_path)
            or receipt.get("topos_wheel_sha256") != digest(topos_wheel)
            or clean.get("distribution_ownership_clean") is not True
            or receipt.get("editable") is not False or receipt.get("execution_backend") != "base"
            or receipt.get("torq_consumer_ready") is not True
            or receipt.get("torq_handoff", {}).get("status") != "passed"
            or receipt.get("torq_handoff", {}).get("computation_performed") is not False
            or receipt.get("native_run", {}).get("status") != "completed"
            or receipt.get("native_run", {}).get("execution_kind") != "real"):
        raise ValueError("The exact candidate requires genuine passing noneditable installation evidence")
    for name, path in selected.items():
        if clean.get("wheels", {}).get(name, {}).get("sha256") != digest(path):
            raise ValueError("Mandatory wheel differs from its clean-installed identity")
    companions = read_json(wheelhouse / "companion-build-manifest.json")
    if companions.get("schema_version") != "cochem-companion-build/0.1.0":
        raise ValueError("Exact companion build identity is required")
    companion_sources = {}
    for project in PROJECTS:
        identity = companions.get("companions", {}).get(project, {})
        pin = identity.get("source_commit", "")
        wheel = selected["cochem-" + project]
        if (not re.fullmatch(r"[0-9a-f]{40}", pin) or identity.get("wheel_name") != wheel.name
                or identity.get("wheel_sha256") != digest(wheel)
                or identity.get("repeated_wheel_sha256") != [digest(wheel), digest(wheel)]):
            raise ValueError("Companion wheel reproducibility does not match the installed package")
        companion_sources[project] = checked_file(wheelhouse, identity["source_archive"], identity["source_archive_sha256"])
        audit_archive(companion_sources[project])
        verify_companion_source(companion_sources[project], project, PROJECTS[project])
    worker_folder = candidate / "ml-worker"
    worker = read_json(worker_folder / "worker-distribution-manifest.json")
    expected_worker = {name: value for name, value in manifest["source_sha256"].items()
                       if name.startswith("topos/") and name.endswith((".py", ".json"))}
    if ("topos/ml_worker.py" not in expected_worker
            or worker.get("source_sha256") != expected_worker
            or worker.get("reproducible_archives") is not True):
        raise ValueError("Isolated worker source differs from the controller")
    worker_wheel = checked_file(worker_folder, worker["wheel"]["name"], worker["wheel"]["sha256"], worker["wheel"]["bytes"])
    audit_archive(worker_wheel)
    verify_wheel_package(worker_wheel, "cochem-topos-ml-worker", "0.1.0")
    verify_wheel_sources(worker_wheel, expected_worker)
    gate = read_json(candidate / "release-gate.json")
    if (gate.get("schema_version") != "topos-release-gate/0.1.0"
            or gate.get("status") not in {"passed", "blocked"}
            or gate.get("source_sha256") != manifest["source_sha256"]):
        raise ValueError("Scientific gate evidence does not identify this candidate source")
    for path in [*archives, *selected.values(), *companion_sources.values(), worker_wheel]:
        audit_archive(path)
    return {"manifest": manifest, "selected": selected, "source": source, "companions": companions,
            "companion_sources": companion_sources, "worker_wheel": worker_wheel, "gate": gate}


INSTALL_README = f"""# CoChem TOPOS 0.1.0 unsigned installation candidate

This complete package contains BASE {PROJECTS['base']}, TOPOS 0.1.0 and TORQ {PROJECTS['torq']},
matching source archives, wheels, an isolated ML worker and actual installation
evidence. It is unsigned and unpublished. Read `evidence/release-gate.json` for
scientific acceptance status and remaining blockers; building this kit does not
certify that every calculation pathway is ready. TORQ import evidence records
`imported-awaiting-calculation`, not a downstream scientific calculation.

Use Linux x86_64 and Python 3.11 or newer. Network access is required for
third-party dependencies and BASE engine provisioning. Licensed executables and
model weights are not included. BASE provisions licensed engines separately.
Access to this private download is limited to authorized repository members.

From this extracted candidate directory:

```bash
sha256sum --check SHA256SUMS
mkdir source
for archive in sources/*.tar.gz; do tar -xzf "$archive" -C source; done
python source/cochem_topos-0.1.0/scripts/setup_ecosystem.py \\
  --base-root source/cochem_base-{PROJECTS['base']} \\
  --torq-root source/cochem_torq-{PROJECTS['torq']} \\
  --wheelhouse wheels \\
  --artifacts /absolute/path/outside/sources/CoChem-0.1.0-runtime
```

The artifacts directory must be new. Existing BASE users keep their current
runtime intact, install this reviewed three-package set into a fresh runtime,
and switch only after BASE's eleven audit phases and TOPOS diagnostics pass.
Read `source/cochem_topos-0.1.0/.docs/TOPOS_INSTALLATION.md` for activation,
registry selection, upgrade/rollback, calculation requests and capability checks.

The separate `ml-worker` wheel belongs only in BASE-managed model silos. Never
install it in the controller environment: it intentionally shares the `topos`
namespace. Follow the installation guide to audit its exact source and model
locks. Checksums establish retained bytes; they are not a digital signature.
"""


def assemble(candidate: Path, wheelhouse: Path, installation: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("Kit output must be a new directory")
    inputs = verify_inputs(candidate, wheelhouse, installation)
    # Stage everything before exposing a final kit; a failed audit leaves no output.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cochem-kit-", dir=output.parent) as temporary:
        stage = Path(temporary)
        root = stage / "cochem-topos-0.1.0-candidate"
        for name in ("wheels", "sources", "ml-worker", "evidence/native-acceptance"):
            (root / name).mkdir(parents=True)
        for path in inputs["selected"].values():
            shutil.copyfile(path, root / "wheels" / path.name)
        for path in [inputs["source"], *inputs["companion_sources"].values()]:
            shutil.copyfile(path, root / "sources" / path.name)
        for path in [inputs["worker_wheel"], candidate / "ml-worker/worker-distribution-manifest.json"]:
            shutil.copyfile(path, root / "ml-worker" / path.name)
        for source, name in [
            (candidate / "distribution-manifest.json", "distribution-manifest.json"),
            (candidate / "release-gate.json", "release-gate.json"),
            (wheelhouse / "companion-build-manifest.json", "companion-build-manifest.json"),
            (installation / "clean-install.json", "clean-install.json"),
        ]:
            shutil.copyfile(source, root / "evidence" / name)
        for name in ("source-commit.json", "documentation-refresh.json"):
            path = candidate / name
            if path.exists():
                read_json(path)
                shutil.copyfile(path, root / "evidence" / name)
        for path in sorted((installation / "acceptance").rglob("*")):
            if path.is_symlink():
                raise ValueError("Installation evidence cannot contain symlinks")
            if path.is_file() and "__pycache__" not in path.parts:
                relative = path.relative_to(installation / "acceptance")
                audit_payload(relative.as_posix(), path.read_bytes())
                destination = root / "evidence/native-acceptance" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        manifest = {
            "schema_version": "cochem-unsigned-download/0.1.0", "release_certified": False, "published": False,
            "source_pins": {key.upper(): value["source_commit"] for key, value in inputs["companions"]["companions"].items()},
            "topos_source_sha256": inputs["manifest"]["source_sha256"],
            "tested_topos_wheel_sha256": digest(inputs["selected"]["cochem-topos"]),
            "clean_installation_status": "passed", "scientific_gate_status": inputs["gate"].get("status"),
            "engines_included": False, "model_weights_included": False,
            "scope": "Unsigned installation candidate; separate scientific gate does not certify unfinished TORQ calculations",
        }
        write_json(root / "candidate-manifest.json", manifest)
        (root / "README.md").write_text(INSTALL_README)
        for folder in (root / "wheels", root / "sources", root / "ml-worker"):
            write_checksums(folder, [path for path in folder.iterdir() if path.is_file()])
        write_checksums(root, [path for path in root.rglob("*") if path.is_file()])
        target = stage / "cochem-topos-0.1.0-unsigned-candidate.zip"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(path for path in root.rglob("*") if path.is_file()):
                info = zipfile.ZipInfo(path.relative_to(stage).as_posix(), (2026, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes(), compresslevel=9)
        write_checksums(stage, [target])
        result = {"archive": target.name, "sha256": digest(target), "bytes": target.stat().st_size,
                  "release_certified": False, "published": False}
        shutil.move(str(stage), str(output))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    companions = commands.add_parser("companions", help="Twice-build exact pinned companion sources")
    for project in PROJECTS:
        companions.add_argument(f"--{project}-root", type=Path, required=True)
        companions.add_argument(f"--{project}-pin", required=True)
    companions.add_argument("--output", type=Path, required=True)
    kit = commands.add_parser("assemble", help="Verify and package the complete unsigned installation kit")
    for name in ("candidate", "wheelhouse", "installation", "output"):
        kit.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "companions":
            result = prepare_companions({name: getattr(args, name + "_root") for name in PROJECTS},
                                        {name: getattr(args, name + "_pin") for name in PROJECTS}, args.output.resolve())
        else:
            result = assemble(args.candidate.resolve(), args.wheelhouse.resolve(), args.installation.resolve(), args.output.resolve())
    except (ValueError, KeyError, OSError, RuntimeError, tarfile.TarError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        print(f"CoChem candidate preparation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
