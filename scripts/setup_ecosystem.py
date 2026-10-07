"""Provision BASE, TOPOS and TORQ through BASE's complete Stage 0 setup.

Run with Python >=3.11 from existing, authorized source checkouts. Licensed
engines are never downloaded by this helper. The default bootstrap is reusable;
--existing-environment validates and reuses an already bootstrapped BASE venv,
then still refreshes dependencies and all eleven mandatory-package phases.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOPOS_ROOT = Path(__file__).resolve().parent.parent
REPOSITORIES = ("CoChem-BASE", "CoChem-TOPOS", "CoChem-TORQ")


@dataclass(frozen=True)
class SetupLayout:
    base_root: Path
    topos_root: Path
    torq_root: Path
    artifacts: Path
    min_disk_space_gb: float = 1.0

    @property
    def python(self) -> Path:
        return self.artifacts / "ui-env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    @property
    def manifest(self) -> Path:
        return self.artifacts / "mandatory-deployment.json"


def require_python(version: tuple[int, ...] = sys.version_info) -> None:
    if version[:2] < (3, 11):
        raise ValueError("CoChem mandatory setup requires Python 3.11 or newer")


def validate_layout(base_root: Path, torq_root: Path, artifacts: Path, *,
                    topos_root: Path = TOPOS_ROOT, min_disk_space_gb: float = 1.0) -> SetupLayout:
    """Validate all paths before installing, downloading, or creating runtime data."""
    require_python()
    import tomllib

    if not math.isfinite(min_disk_space_gb) or min_disk_space_gb <= 0:
        raise ValueError("minimum free disk space must be finite and positive")
    roots = [Path(p).expanduser().resolve() for p in (base_root, topos_root, torq_root)]
    for root, project in zip(roots, REPOSITORIES, strict=True):
        manifest = root / "pyproject.toml"
        if not root.is_dir() or not manifest.is_file():
            raise ValueError(f"{project} requires an existing source checkout with pyproject.toml")
        name = tomllib.loads(manifest.read_text(encoding="utf-8")).get("project", {}).get("name", "")
        if not isinstance(name, str) or name.lower().replace("_", "-") != project.lower():
            raise ValueError(f"Source root does not identify {project}: {root}")
    for entry in (roots[0] / "scripts" / "hosted_dashboard.py", roots[0] / "cli.py"):
        if not entry.is_file():
            raise ValueError(f"CoChem-BASE setup entry point is missing: {entry}")
    destination = Path(artifacts).expanduser().resolve()
    if destination.exists() and not destination.is_dir():
        raise ValueError("artifacts must identify a directory")
    for root in roots:
        if destination == root or destination.is_relative_to(root) or root.is_relative_to(destination):
            raise ValueError("The artifacts directory must be outside and disjoint from all three source checkouts")
    return SetupLayout(roots[0], roots[1], roots[2], destination, min_disk_space_gb)


def deployment_manifest() -> dict[str, list[str]]:
    return {"selected_repositories": list(REPOSITORIES)}


def setup_commands(layout: SetupLayout, *, bootstrap_python: str = sys.executable,
                   wheelhouse: Path | None = None) -> dict[str, list[str]]:
    """Expose concrete argv for review without executing a setup or a shell."""
    commands = {
        "bootstrap": [bootstrap_python, str(layout.base_root / "scripts" / "hosted_dashboard.py"), "setup",
                      "--artifacts", str(layout.artifacts), "--min-disk-space-gb", str(layout.min_disk_space_gb)],
        "install_modules": [str(layout.python), "-m", "pip", "install", "-e", f"{layout.topos_root}[dev,ui]",
                            "-e", str(layout.torq_root)],
        "mandatory_setup": [str(layout.python), str(layout.base_root / "cli.py"), "setup", "--all", "--skip-heavy",
                            "--artifact-dir", str(layout.artifacts), "--min-disk-space-gb", str(layout.min_disk_space_gb), "--json"],
        "pip_check": [str(layout.python), "-m", "pip", "check"],
    }
    if wheelhouse is not None:
        wheels = verified_release_wheels(wheelhouse)
        paths = [str(wheels[name]) for name in ("cochem-base", "cochem-torq", "cochem-topos")]
        # Refresh the three explicitly selected wheels even when version strings
        # match a prior candidate. Dependencies resolve separately and are audited.
        commands["install_modules"] = [str(layout.python), "-m", "pip", "install", "--force-reinstall", "--no-deps", *paths]
        commands["install_release_dependencies"] = [str(layout.python), "-m", "pip", "install", "--find-links", str(wheelhouse.resolve()),
                                                      *paths[:-1], paths[-1] + "[ui]"]
    return commands


def verified_release_wheels(folder: Path) -> dict[str, Path]:
    """Check the explicit local package set before invoking pip or uninstalling."""
    import email
    import zipfile

    folder = folder.expanduser().resolve(strict=True)
    checksums = folder / "SHA256SUMS"
    if checksums.is_symlink() or not checksums.is_file():
        raise ValueError("Release wheelhouse requires SHA256SUMS from its reviewed distribution")
    expected = {}
    for line in checksums.read_text().splitlines():
        parts = line.split()
        if len(parts) != 2 or len(parts[0]) != 64 or Path(parts[1]).name != parts[1]:
            raise ValueError("Invalid or unconfined release checksum entry")
        if parts[1] in expected:
            raise ValueError("Duplicate release checksum filename")
        expected[parts[1]] = parts[0]
    wheels = {}
    ownership = set()
    for path in sorted(folder.glob("*.whl")):
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected.get(path.name):
            raise ValueError(f"Release wheel checksum mismatch: {path.name}")
        with zipfile.ZipFile(path) as archive:
            metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError("Release wheel needs exactly one distribution metadata record")
            name = email.message_from_bytes(archive.read(metadata[0]))["Name"].lower().replace("_", "-")
            if name not in {"cochem-base", "cochem-topos", "cochem-torq"}:
                continue
            if name in wheels:
                raise ValueError("Release wheelhouse has ambiguous module versions")
            payload = {item for item in archive.namelist() if not item.endswith("/") and ".dist-info/" not in item}
            if ownership & payload:
                raise ValueError("Mandatory wheels overlap installed files; resolve distribution ownership before installation")
            ownership.update(payload)
            wheels[name] = path
    if set(wheels) != {"cochem-base", "cochem-topos", "cochem-torq"}:
        raise ValueError("Release wheelhouse must supply all three mandatory CoChem wheels")
    return wheels


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def runtime_environment(layout: SetupLayout, crest: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(COCHEM_ARTIFACT_DIR=str(layout.artifacts),
               COCHEM_CONFIG=str(layout.artifacts / "Registry" / "cochem_system_config.json"),
               COCHEM_MANIFEST_PATH=str(layout.manifest),
               COCHEM_BASE_ROOT=str(layout.base_root), COCHEM_TOPOS_ROOT=str(layout.topos_root),
               COCHEM_CREST_BIN=str(crest), TOPOS_CREST_EXECUTABLE=str(crest),
               TOPOS_EXECUTION_BACKEND="base", COCHEM_HEADLESS="1", QT_QPA_PLATFORM="offscreen")
    # TORQ's present checkout packages Libraries; BASE also supplies a cochem_torq
    # namespace. Require the actual TORQ distribution, without claiming its still
    # unfinished downstream consumer is ready or importing its bootstrap.
    env.pop("COCHEM_TORQ_ROOT", None)
    for variable, silo in {"COCHEM_CORE_SILO": "cochem_core_silo", "COCHEM_UI_SILO": "cochem_ui_silo",
                           "COCHEM_CALC_SILO": "cochem_calc_silo", "COCHEM_ML_SILO": "cochem_mace_silo"}.items():
        env[variable] = str(layout.artifacts / "Silos" / silo)
    xtb_root = layout.artifacts / "free-engines" / "xtb" / "xtb-dist"
    xtb = xtb_root / "bin" / "xtb"
    path_prefix = [str(crest.parent)]
    if xtb.is_file():
        env.update(COCHEM_XTB_BIN=str(xtb), TOPOS_XTB_EXECUTABLE=str(xtb), XTB_CMD=str(xtb),
                   XTBPATH=str(xtb_root / "share" / "xtb"))
        path_prefix.insert(0, str(xtb.parent))
    env["PATH"] = os.pathsep.join([*path_prefix, env.get("PATH", "")])
    return env


def _crest_binary(layout: SetupLayout) -> Path:
    configured = os.environ.get("COCHEM_CREST_BIN")
    if configured:
        executable = shutil.which(configured)
        if executable is None:
            raise ValueError("Explicit COCHEM_CREST_BIN does not identify an executable")
        return Path(executable).resolve()
    module_path = layout.topos_root / "scripts" / "install_crest.py"
    spec = importlib.util.spec_from_file_location("topos_setup_pinned_crest", module_path)
    if spec is None or spec.loader is None:
        raise ValueError("Pinned CREST installer is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.install(layout.artifacts / "tools" / "crest")


EXISTING_BASE_PROBE = """import json, os, sys
if sys.version_info < (3, 11):
    raise RuntimeError('Existing CoChem environment requires Python 3.11 or newer')
from pathlib import Path
from cochem_base.core.cochem_core_registry_manager import load_system_config
from cochem_base.core_engine.execution_authority import authorize_engine_execution
config = load_system_config(Path(os.environ['COCHEM_CONFIG']), verify_integrity=True)
if not config.verify_checksum() or config.stage0 is None or len(config.stage0.phases) != 11:
    raise RuntimeError('Existing environment lacks complete, intact BASE Stage 0 authority')
authority = authorize_engine_execution('xtb', registry_path=Path(os.environ['COCHEM_CONFIG']), cores=1)
print(json.dumps({'status': config.status, 'xtb': authority.executable, 'phases': 11}))
"""

VALIDATION_PROBE = """import hashlib, importlib.metadata, json, os, re, subprocess, sys
from pathlib import Path
from topos.base_integration import BaseRuntime
if sys.version_info < (3, 11):
    raise RuntimeError('CoChem environment requires Python 3.11 or newer')
runtime = BaseRuntime(registry_path=Path(os.environ['COCHEM_CONFIG']))
config = runtime.registry
if config.stage0 is None or sorted(p.phase_number for p in config.stage0.phases) != list(range(1, 12)):
    raise RuntimeError('All eleven BASE setup phases are required')
manifest = Path(os.environ['COCHEM_MANIFEST_PATH'])
selected = json.loads(manifest.read_text())['selected_repositories']
if sorted(selected) != sorted(['CoChem-BASE', 'CoChem-TOPOS', 'CoChem-TORQ']):
    raise RuntimeError('Mandatory deployment manifest must select all three repositories')
engines = {}
probe_env = os.environ.copy()
probe_env.update(OMP_NUM_THREADS='1', OMP_THREAD_LIMIT='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
for engine, expected in [('xtb', '6.7.1'), ('crest', '3.0.2')]:
    executable = runtime.resolve_executable(engine)
    expected_path = os.environ[f'COCHEM_{engine.upper()}_BIN']
    if Path(executable).resolve() != Path(expected_path).resolve():
        raise RuntimeError(f'BASE authority resolved an unexpected {engine} executable')
    result = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=30, check=True, env=probe_env)
    output = result.stdout + result.stderr
    pattern = r'xtb version\\s+(\\d+\\.\\d+\\.\\d+)' if engine == 'xtb' else r'Version\\s+(\\d+\\.\\d+\\.\\d+)'
    match = re.search(pattern, output, re.I)
    if match is None or match.group(1) != expected:
        raise RuntimeError(f'{engine} version does not match the TOPOS validated profile')
    engines[engine] = {'executable': executable, 'version': expected,
                       'sha256': hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
                       'probe': '--version', 'execution_kind': 'real-version-probe'}
versions = {name: importlib.metadata.version(name) for name in ('CoChem-BASE', 'cochem-topos', 'CoChem-TORQ')}
evidence = {'status': 'verified', 'base_registry_status': config.status,
            'phases': [p.model_dump(mode='json') for p in config.stage0.phases],
            'selected_repositories': selected, 'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
            'runtime': runtime.provenance(), 'engines': engines, 'distributions': versions,
            'torq_consumer_readiness': 'not certified by installation; TORQ remains a separate implementation workstream'}
Path(sys.argv[1]).write_text(json.dumps(evidence, indent=2) + '\\n')
"""


def provision(layout: SetupLayout, *, existing_environment: bool = False,
              wheelhouse: Path | None = None) -> dict[str, Any]:
    """Perform real installations and record command/log evidence for every stage."""
    if wheelhouse is not None:
        verified_release_wheels(wheelhouse)
        if existing_environment or layout.artifacts.exists():
            raise ValueError("Release wheel installation requires fresh artifacts; upgrades create a new audited environment")
    layout.artifacts.mkdir(parents=True, exist_ok=True)
    logs = layout.artifacts / "setup-logs"
    logs.mkdir(exist_ok=True)
    receipt_path = layout.artifacts / "setup-receipt.json"
    start = time.monotonic()
    receipt: dict[str, Any] = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
                               "source_roots": {name: str(root) for name, root in zip(REPOSITORIES, (layout.base_root, layout.topos_root, layout.torq_root), strict=True)},
                               "python": str(layout.python), "existing_environment": existing_environment,
                               "min_disk_space_gb": layout.min_disk_space_gb, "steps": [],
                               "scope": "mandatory package installation and BASE execution authority; no licensed ORCA installation or calculation"}
    _write_json(receipt_path, receipt)

    def execute(name: str, command: list[str], env: dict[str, str], *, timeout: float | None = None) -> None:
        path = logs / f"{name}.log"
        entry: dict[str, Any] = {"name": name, "command": command, "log": str(path), "status": "running"}
        receipt["steps"].append(entry)
        _write_json(receipt_path, receipt)
        print(f"CoChem setup: {name}; log: {path}", flush=True)
        try:
            with path.open("w", encoding="utf-8") as output:
                result = subprocess.run(command, cwd=layout.base_root, env=env, stdout=output,
                                        stderr=subprocess.STDOUT, timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            entry.update(status="failed", reason=type(exc).__name__)
            raise
        entry.update(returncode=result.returncode, status="completed" if result.returncode == 0 else "failed")
        if result.returncode:
            raise RuntimeError(f"{name} failed with exit status {result.returncode}; inspect {path}")

    try:
        crest = _crest_binary(layout)
        receipt["crest_provisioning"] = {"source": "explicit COCHEM_CREST_BIN" if os.environ.get("COCHEM_CREST_BIN") else "checksum-pinned official CREST archive",
                                         "executable": str(crest), "sha256": hashlib.sha256(crest.read_bytes()).hexdigest()}
        commands = setup_commands(layout, wheelhouse=wheelhouse)
        env = runtime_environment(layout, crest)
        if existing_environment:
            if not layout.python.is_file():
                raise ValueError("--existing-environment requires the existing artifacts/ui-env interpreter")
            execute("verify-existing-base", [str(layout.python), "-c", EXISTING_BASE_PROBE], env, timeout=60)
        else:
            execute("bootstrap-base", commands["bootstrap"], env)
        if not layout.python.is_file():
            raise RuntimeError("BASE bootstrap did not create artifacts/ui-env")
        xtb = layout.artifacts / "free-engines" / "xtb" / "xtb-dist" / "bin" / "xtb"
        if not xtb.is_file():
            raise RuntimeError("BASE bootstrap did not provision its audited free-engine xTB installation")
        env = runtime_environment(layout, crest)
        execute("install-mandatory-modules", commands["install_modules"], env)
        if wheelhouse is not None:
            execute("install-release-dependencies", commands["install_release_dependencies"], env)
            receipt["distribution_mode"] = "noneditable-reviewed-wheels"
            for variable in ("COCHEM_BASE_ROOT", "COCHEM_TOPOS_ROOT", "COCHEM_TORQ_ROOT", "PYTHONPATH"):
                env.pop(variable, None)
        _write_json(layout.manifest, deployment_manifest())
        execute("mandatory-stage0", commands["mandatory_setup"], env)
        execute("pip-check", commands["pip_check"], env, timeout=60)
        evidence_path = layout.artifacts / "mandatory-validation.json"
        evidence_path.unlink(missing_ok=True)
        execute("verify-mandatory-runtime", [str(layout.python), "-c", VALIDATION_PROBE, str(evidence_path)], env, timeout=120)
        receipt["validation"] = json.loads(evidence_path.read_text(encoding="utf-8"))
        receipt["status"] = "completed"
    except Exception as exc:
        receipt.update(status="failed", failure=str(exc))
        raise
    finally:
        receipt["elapsed_seconds"] = time.monotonic() - start
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(receipt_path, receipt)
    print(f"CoChem mandatory setup completed; receipt: {receipt_path}", flush=True)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-root", type=Path, required=True)
    parser.add_argument("--torq-root", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--min-disk-space-gb", type=float, default=1.0,
                        help="Minimum free storage for bounded small-molecule acceptance (default 1 GiB)")
    parser.add_argument("--existing-environment", action="store_true",
                        help="Validate and reuse artifacts/ui-env; still refresh dependencies and all eleven package setup phases")
    parser.add_argument("--wheelhouse", type=Path, help="Reviewed local BASE/TOPOS/TORQ wheels plus SHA256SUMS; fresh deployment only")
    args = parser.parse_args(argv)
    try:
        layout = validate_layout(args.base_root, args.torq_root, args.artifacts,
                                 min_disk_space_gb=args.min_disk_space_gb)
        provision(layout, existing_environment=args.existing_environment, wheelhouse=args.wheelhouse)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"CoChem setup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
