"""Build an exact-source, reproducible ML worker wheel for a BASE-managed silo.

This is not a standalone TOPOS controller. The mandatory BASE/TOPOS/TORQ
controller lives in its own environment; this wheel must never coexist with the
controller distribution because both deliberately use the topos module namespace.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

from build_release import BUILD_TOOLS, DEFAULT_EPOCH, normalize_archive

ROOT = Path(__file__).resolve().parent.parent
DEPENDENCIES = {
    "numpy": "2.5.3", "scipy": "1.18.1", "networkx": "3.6.1", "pydantic": "2.13.5",
    "h5py": "3.16.0", "mendeleev": "1.3.0", "filelock": "3.32.3", "psutil": "7.2.2", "MolSym": "1.2.0",
    "ase": "3.29.0",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def worker_sources(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted((root / "topos").rglob("*")):
        if path.suffix not in {".py", ".json"} or "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise ValueError("Worker source cannot contain symlinks")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    if "topos/ml_worker.py" not in result:
        raise ValueError("Actual ML worker source is absent")
    return result


def build_worker(root: Path, output: Path) -> dict:
    root, output = root.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError("Worker output must be a fresh directory outside the controller checkout")
    if {key: importlib.metadata.version(key) for key in BUILD_TOOLS} != BUILD_TOOLS:
        raise ValueError("Install the pinned release-build-requirements.txt before building")
    identity = worker_sources(root)
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    manifest = {"schema_version": "topos-ml-worker-distribution/0.1.0", "version": version,
                "scope": "BASE-managed isolated inference worker; not a standalone controller",
                "controller_packages_required_in_parent": ["CoChem-BASE", "cochem-topos", "CoChem-TORQ"],
                "forbidden_silo_distribution": "cochem-topos", "source_sha256": identity,
                "worker_sha256": identity["topos/ml_worker.py"], "dependencies": DEPENDENCIES,
                "model_backends": "provisioned independently by verified BASE ML lock; no checkpoint download",
                "build_tools": BUILD_TOOLS, "published": False}
    output.mkdir(parents=True)
    hashes = []
    with tempfile.TemporaryDirectory(prefix="topos-worker-build-") as folder:
        scratch = Path(folder)
        for index in (1, 2):
            stage = scratch / str(index)
            stage.mkdir()
            for name in identity:
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((root / name).read_bytes())
                os.utime(target, (DEFAULT_EPOCH, DEFAULT_EPOCH))
            (stage / "topos/data/ml_worker_distribution.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
            dependencies = [f"{name}=={value}" for name, value in DEPENDENCIES.items()]
            (stage / "pyproject.toml").write_text(
                '[build-system]\nrequires=["setuptools==80.9.0","wheel==0.45.1"]\nbuild-backend="setuptools.build_meta"\n'
                '[project]\nname="cochem-topos-ml-worker"\nversion=' + json.dumps(version)
                + '\nrequires-python=">=3.11"\ndescription="Isolated BASE-controlled TOPOS ML inference worker"\n'
                'license="Apache-2.0"\ndependencies=' + json.dumps(dependencies)
                + '\n[tool.setuptools.packages.find]\ninclude=["topos*"]\n'
                '[tool.setuptools.package-data]\n"topos.data"=["*.json"]\n')
            shutil.copyfile(root / "LICENSE", stage / "LICENSE")
            dist = scratch / f"dist-{index}"
            env = {**os.environ, "SOURCE_DATE_EPOCH": str(DEFAULT_EPOCH), "PYTHONHASHSEED": "0"}
            env.pop("PYTHONPATH", None)
            with (output / f"build-{index}.log").open("wb") as log:
                process = subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(dist), str(stage)],
                                         cwd=scratch, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
            if process.returncode:
                raise RuntimeError("Worker wheel build failed; see retained build log")
            wheels = list(dist.glob("*.whl"))
            if len(wheels) != 1:
                raise RuntimeError("Expected one worker wheel")
            wheel = wheels[0]
            normalize_archive(wheel, DEFAULT_EPOCH)
            hashes.append(digest(wheel))
            if index == 1:
                shutil.copyfile(wheel, output / wheel.name)
    if hashes[0] != hashes[1] or identity != worker_sources(root):
        raise RuntimeError("Worker source/build bytes changed; no reproducible artifact can be certified")
    wheel = next(output.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        for name, expected in identity.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise RuntimeError("Worker wheel payload differs from controller source")
    receipt = {**manifest, "reproducible_archives": True, "wheel": {"name": wheel.name, "sha256": hashes[0], "bytes": wheel.stat().st_size}}
    (output / "worker-distribution-manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (output / "SHA256SUMS").write_text("".join(f"{digest(p)}  {p.name}\n" for p in [wheel, output / "worker-distribution-manifest.json"]))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_worker(args.source_root, args.output)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"Worker build failed: {exc}\n")
    print(json.dumps({"status": "built", "reproducible_archives": True, "wheel": result["wheel"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
