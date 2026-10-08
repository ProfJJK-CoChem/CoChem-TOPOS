"""Install a verified local worker wheel into its isolated BASE-managed interpreter.

Run this file with the silo's Python -I. This never installs dependencies or model
checkpoints, and refuses controller namespace ownership before any pip mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import zipfile
from pathlib import Path


def install(wheel: Path, manifest_path: Path) -> dict:
    if sys.prefix == sys.base_prefix:
        raise ValueError("The worker requires an isolated virtual environment")
    try:
        importlib.metadata.distribution("cochem-topos")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise ValueError("Refusing worker installation over the TOPOS controller namespace")
    if wheel.is_symlink() or manifest_path.is_symlink():
        raise ValueError("Worker artifacts must be regular files")
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("schema_version") != "topos-ml-worker-distribution/0.1.0"
            or manifest.get("reproducible_archives") is not True
            or manifest["wheel"]["name"] != wheel.name
            or hashlib.sha256(wheel.read_bytes()).hexdigest() != manifest["wheel"]["sha256"]):
        raise ValueError("Worker wheel does not match the reproducible build manifest")
    for name, expected in manifest["dependencies"].items():
        if importlib.metadata.version(name) != expected:
            raise ValueError(f"BASE ML silo dependency differs from worker contract: {name}")
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1 or not metadata_names[0].startswith("cochem_topos_ml_worker-"):
            raise ValueError("This is not an isolated TOPOS worker distribution")
        for name, expected in manifest["source_sha256"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError("Worker payload differs from its exact controller source identity")
    subprocess.run([sys.executable, "-I", "-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall", str(wheel.resolve())], check=True)
    distribution = importlib.metadata.distribution("cochem-topos-ml-worker")
    for name, expected in manifest["source_sha256"].items():
        path = Path(distribution.locate_file(name)).resolve()
        if not path.is_relative_to(Path(sys.prefix).resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Installed worker source differs from verified payload")
    return {"status": "installed", "distribution": "cochem-topos-ml-worker", "version": distribution.version,
            "wheel_sha256": manifest["wheel"]["sha256"], "worker_sha256": manifest["worker_sha256"],
            "source_sha256": manifest["source_sha256"], "prefix": sys.prefix,
            "scope": "isolated inference source installation; no model inference or controller release certification"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        parser.exit(2, "Use a new installation receipt path\n")
    try:
        result = install(args.wheel, args.manifest)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, importlib.metadata.PackageNotFoundError) as exc:
        parser.exit(2, f"Worker installation failed: {exc}\n")
    args.receipt.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "version": result["version"], "prefix": result["prefix"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
