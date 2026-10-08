"""Install three actual wheels in a new venv and exercise installed TOPOS via BASE."""
from __future__ import annotations

import argparse
import email
import hashlib
import json
import os
import subprocess
import sys
import venv
import zipfile
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wheel_inventory(folder: Path) -> tuple[dict[str, Path], list[dict]]:
    required = {"cochem-base", "cochem-topos", "cochem-torq"}
    wheels = {}
    owners: dict[str, list[dict]] = {}
    for path in sorted(folder.glob("*.whl")):
        if path.is_symlink():
            raise ValueError("Wheel input cannot be a symlink")
        with zipfile.ZipFile(path) as archive:
            metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError("Wheel needs exactly one distribution metadata record")
            message = email.message_from_bytes(archive.read(metadata[0]))
            name = message["Name"].lower().replace("_", "-")
            if name not in required:
                continue
            if name in wheels:
                raise ValueError(f"Ambiguous multiple {name} wheels")
            wheels[name] = path.resolve()
            for filename in archive.namelist():
                if ".dist-info/" not in filename and not filename.endswith("/"):
                    owners.setdefault(filename, []).append({"distribution": name, "sha256": hashlib.sha256(archive.read(filename)).hexdigest()})
    if set(wheels) != required:
        raise ValueError("Provide exactly one actual BASE, TOPOS and TORQ wheel")
    collisions = [{"path": filename, "owners": items, "same_bytes": len({item["sha256"] for item in items}) == 1}
                  for filename, items in sorted(owners.items()) if len(items) > 1]
    return wheels, collisions


def accept(wheelhouse: Path, registry: Path, output: Path, *, constraints: Path | None = None,
           extras: str = "ui") -> dict:
    output, registry = output.resolve(), registry.resolve(strict=True)
    if output.exists():
        raise ValueError("Installed acceptance requires a new output directory")
    if not set(extras.split(",")) <= {"ui", "external", ""}:
        raise ValueError("Supported installation extras are ui and external")
    wheels, collisions = wheel_inventory(wheelhouse)
    if collisions:
        raise ValueError("Mandatory wheel files overlap; resolve package ownership before installation acceptance")
    output.mkdir(parents=True)
    receipt = {"schema_version": "topos-clean-install/0.1.0", "status": "running", "published": False,
               "wheels": {name: {"path": str(path), "sha256": digest(path)} for name, path in wheels.items()},
               "package_file_collisions": collisions, "registry_sha256": digest(registry), "steps": []}
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "COCHEM_BASE_ROOT", "COCHEM_TOPOS_ROOT", "COCHEM_TORQ_ROOT", "TOPOS_CONFIG"):
        env.pop(name, None)
    env.update(TOPOS_EXECUTION_BACKEND="base", COCHEM_CONFIG=str(registry), COCHEM_HEADLESS="1", QT_QPA_PLATFORM="offscreen",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    python = output / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def run(name, command):
        log = output / f"{name}.log"
        with log.open("wb") as stream:
            process = subprocess.run(command, cwd=output, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
        receipt["steps"].append({"name": name, "command": command, "returncode": process.returncode,
                                 "log": log.name, "log_sha256": digest(log)})
        if process.returncode:
            raise RuntimeError(f"{name} failed; see {log}")

    try:
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(output / "venv")
        command = [str(python), "-I", "-m", "pip", "install", "--report", str(output / "pip-install-report.json"),
                   "--find-links", str(wheelhouse.resolve())]
        if constraints:
            command.extend(["--constraint", str(constraints.resolve(strict=True))])
            receipt["constraints_sha256"] = digest(constraints)
        command.extend([str(wheels["cochem-base"]), str(wheels["cochem-torq"]),
                        str(wheels["cochem-topos"]) + (f"[{extras}]" if extras else "")])
        run("install", command)
        package_probe = (
            "from pathlib import Path; import importlib.metadata as m; "
            "import cochem_base.core_engine.execution_authority; import Libraries.cochem_torq_dvr as d; "
            "import topos; from topos.base_provider import metadata; "
            "assert metadata()['integration_contract']=='cochem.module-handoff/1'; "
            "assert Path(d.__file__).is_relative_to(Path(__import__('sys').prefix)); "
            "assert m.version('CoChem-BASE')=='1.0.1' and m.version('CoChem-TORQ')=='0.1.0'"
        )
        for number, order in enumerate((("cochem-base", "cochem-torq"), ("cochem-torq", "cochem-base")), start=1):
            for name in order:
                run(f"ownership-order-{number}-{name}", [str(python), "-I", "-m", "pip", "install", "--no-deps",
                                                           "--force-reinstall", str(wheels[name])])
            run(f"ownership-order-{number}-probe", [str(python), "-I", "-c", package_probe])
        run("installed-check", [str(python), "-I", "-m", "topos.release", "installed-check", "--wheel", str(wheels["cochem-topos"]),
                                 "--registry", str(registry), "--output", str(output / "acceptance")])
        tested = json.loads((output / "acceptance" / "installed-acceptance.json").read_text())
        tested["package_file_collisions"] = collisions
        tested["installation_manifest_sha256"] = hashlib.sha256(json.dumps(receipt["wheels"], sort_keys=True).encode()).hexdigest()
        (output / "acceptance" / "installed-acceptance.json").write_text(json.dumps(tested, indent=2) + "\n")
        receipt.update(status="passed", acceptance_receipt="acceptance/installed-acceptance.json",
                       acceptance_sha256=digest(output / "acceptance" / "installed-acceptance.json"),
                       distribution_ownership_clean=not collisions)
    except Exception as exc:
        receipt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    (output / "clean-install.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--constraints", type=Path)
    parser.add_argument("--extras", default="ui")
    args = parser.parse_args()
    try:
        result = accept(args.wheelhouse, args.registry, args.output, constraints=args.constraints, extras=args.extras)
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc), "published": False}), file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output), "published": False}))
    return 0 if result["status"] == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
