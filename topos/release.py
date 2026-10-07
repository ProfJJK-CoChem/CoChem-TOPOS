"""Distribution evidence and a fail-closed release gate; never publishes software."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def source_inventory(root: Path) -> dict[str, str]:
    """Identity of executable/distribution sources, excluding generated evidence."""
    root = root.resolve()
    files = {root / name for name in ("pyproject.toml", "setup.py", "MANIFEST.in", "requirements.txt", "cochem_topos_web.py",
                                     "scripts/release-build-requirements.txt")}
    for folder in ("topos", "scripts", "tests"):
        files.update((root / folder).rglob("*.py"))
    files.update((root / "topos" / "data").glob("*.json"))
    files.update((root / ".github" / "workflows").glob("*.yml"))
    if any(path.is_symlink() for path in files):
        raise ValueError("Executable/distribution source files must not be symlinks")
    return {str(path.relative_to(root)): sha256(path) for path in sorted(files)
            if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts}


def dependency_inventory() -> list[dict[str, Any]]:
    """Observed package identity, not a promise that unpinned resolution repeats."""
    values = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        item: dict[str, Any] = {"name": name, "version": distribution.version,
                                "requires_dist": sorted(distribution.requires or [])}
        metadata = distribution.read_text("METADATA")
        if metadata:
            item["metadata_sha256"] = hashlib.sha256(metadata.encode()).hexdigest()
        direct = distribution.read_text("direct_url.json")
        if direct:
            declaration = json.loads(direct)
            item["editable"] = bool(declaration.get("dir_info", {}).get("editable"))
            # Never persist URL userinfo or credentials in an environment report.
            item["direct_origin_kind"] = "vcs" if "vcs_info" in declaration else "local-or-archive"
        values.append(item)
    return sorted(values, key=lambda item: item["name"].lower())


def release_gate(root: Path, *, validation: Path | None = None, installation: Path | None = None,
                 hosted: Path | None = None, srs_acceptance: Path | None = None,
                 distribution_manifest: Path | None = None) -> dict[str, Any]:
    """Require current, correlated evidence for a full TOPOS release certification.

    Receipts are local evidence supplied by the responsible maintainer; hashes
    establish correlation, not an independent signature or scientific audit.
    Preparation of unsigned candidate archives does not require this gate to pass.
    """
    from .matrix_workflow import execution_support_report

    root = root.resolve()
    current = source_inventory(root)
    support = execution_support_report()
    blockers = []
    evidence = {}

    def load(path: Path | None, label: str) -> dict[str, Any]:
        if path is None or not path.is_file() or path.is_symlink():
            blockers.append(f"{label}: current evidence file is missing")
            return {}
        try:
            value = json.loads(path.read_text())
            if not isinstance(value, dict):
                raise ValueError("receipt must be an object")
        except (ValueError, OSError) as exc:
            blockers.append(f"{label}: invalid receipt ({exc})")
            return {}
        evidence[label] = {"path": str(path.resolve()), "sha256": sha256(path)}
        return value

    if support["additional_adapter_recipes"]:
        blockers.append(f"Method matrix: {len(support['additional_adapter_recipes'])} TOPOS recipe adapters remain incomplete")
    if support["topos_track_gaps"]:
        blockers.append("Method matrix: unresolved source track gaps " + ", ".join(support["topos_track_gaps"]))
    verified = load(validation, "regression")
    if verified:
        check = verified.get("verification", {})
        tested = check.get("source_sha256", {})
        stale = [path for path, digest in current.items() if tested.get(path) != digest]
        if stale:
            blockers.append(f"Regression: {len(stale)} current source files lack matching tested hashes")
        pytest_checks = [item for item in check.get("checks", []) if item.get("check") == "pytest"]
        pytest = check.get("pytest", verified.get("pytest", {}))
        if len(pytest_checks) == 1:
            pytest = pytest_checks[0].get("junit", {})
            if pytest_checks[0].get("exit_code") != 0:
                blockers.append("Regression: pytest process did not exit successfully")
        if check.get("sources_unchanged") is not True:
            blockers.append("Regression: source stability throughout verification has not been established")
        if (not isinstance(pytest.get("tests"), int) or pytest.get("tests", 0) < 1
                or any(pytest.get(key) != 0 for key in ("failures", "errors", "skipped"))):
            blockers.append("Regression: complete nonzero executed tests with zero failures/errors/skips required")
        if verified.get("all_srs_acceptance_complete") is not True or verified.get("all_matrix_recipes_implemented") is not True:
            blockers.append("Regression receipt explicitly lacks full SRS/matrix acceptance")
    ledger = load(srs_acceptance, "SRS acceptance")
    if ledger:
        srs = root / ".docs" / "CoChem-TOPOS_SRS.md"
        expected = set(re.findall(r"TOPOS-010-\d{3}", srs.read_text()))
        rows = ledger.get("requirements", {})
        if (len(expected) != 50 or not isinstance(rows, dict)
                or ledger.get("srs_sha256") != sha256(srs) or set(rows) != expected):
            blockers.append("SRS acceptance: exact current document and complete requirement inventory required")
        if not isinstance(rows, dict):
            rows = {}
        for name, entry in rows.items():
            if (not isinstance(entry, dict) or entry.get("status") != "verified"
                    or not isinstance(entry.get("evidence"), list) or not entry["evidence"]):
                blockers.append(f"SRS acceptance: {name} is not verified with retained evidence")
                continue
            for item in entry["evidence"]:
                if not isinstance(item, dict):
                    blockers.append(f"SRS acceptance: {name} has invalid evidence metadata")
                    continue
                path = (srs_acceptance.parent / str(item.get("path", ""))).resolve()
                if not path.is_file() or path.is_symlink() or item.get("sha256") != sha256(path):
                    blockers.append(f"SRS acceptance: {name} evidence file is missing or changed")
    manifest = load(distribution_manifest, "distribution")
    if manifest and (manifest.get("source_sha256") != current or manifest.get("reproducible_archives") is not True):
        blockers.append("Distribution: current source and independently repeated identical archives required")
    installed = load(installation, "installed-wheel acceptance")
    if installed:
        if (installed.get("schema_version") != "topos-installed-release-acceptance/0.1.0"
                or installed.get("status") != "passed" or installed.get("editable") is not False
                or installed.get("execution_backend") != "base"):
            blockers.append("Installed wheel: successful noneditable mandatory-ecosystem native acceptance required")
        if installed.get("package_file_collisions"):
            blockers.append("Mandatory ecosystem: distributions own overlapping files; safe install/upgrade ownership remains unresolved")
        native = installed.get("native_run", {})
        if (native.get("status") != "completed" or native.get("execution_kind") != "real"
                or native.get("engine_version") != "6.7.1" or not native.get("snapshot") or not native.get("bundle")):
            blockers.append("Installed wheel: actual versioned calculation, snapshot and verified export are missing")
        expected_wheels = {item["sha256"] for item in manifest.get("artifacts", []) if item.get("name", "").endswith(".whl")}
        if not expected_wheels or installed.get("topos_wheel_sha256") not in expected_wheels:
            blockers.append("Installed wheel: tested TOPOS wheel does not match the candidate artifact")
    licensed = load(hosted, "hosted ORCA acceptance")
    if licensed:
        required = {"hf3c-energy-gradient", "r2scan3c-optimization-thermochemistry", "wb97xv-optimization", "counterpoise", "goat-refinement"}
        cases = licensed.get("cases", {})
        if (licensed.get("schema_version") != "topos-orca-physical-acceptance/0.1.0"
                or licensed.get("status") != "passed" or not licensed.get("github_run_id") or not licensed.get("github_sha")
                or not required.issubset(cases) or any(cases[key].get("status") != "passed" for key in required & set(cases))):
            blockers.append("Hosted ORCA: all required native cases on an identified GitHub Actions run must pass")
        if licensed.get("acceptance_script_sha256") != current.get("scripts/accept_orca_topos.py"):
            blockers.append("Hosted ORCA: acceptance script differs from current release source")
        native_source = licensed.get("source", {}).get("source_files", {})
        package_files = {path: digest for path, digest in current.items() if path.startswith("topos/") and path.endswith(".py")}
        if any(native_source.get(path) != digest for path, digest in package_files.items()):
            blockers.append("Hosted ORCA: current package source has not been correlated with native execution")
    return {"schema_version": "topos-release-gate/0.1.0", "status": "blocked" if blockers else "passed",
            "release_certified": not blockers, "published": False, "source_sha256": current,
            "matrix_support": support, "evidence": evidence, "blockers": blockers,
            "scope": "Full TOPOS requirement acceptance; does not certify TORQ's unfinished scientific implementation"}


def installed_acceptance(wheel: Path, registry: Path, output: Path) -> dict[str, Any]:
    """Run from an isolated interpreter, with actual installed mandatory packages."""
    if output.exists():
        raise ValueError("Installed acceptance requires a fresh output directory")
    output.mkdir(parents=True)
    result: dict[str, Any] = {"schema_version": "topos-installed-release-acceptance/0.1.0",
                              "status": "running", "editable": False, "execution_backend": "base",
                              "topos_wheel_sha256": sha256(wheel), "python": sys.version,
                              "platform": platform.platform(), "prefix": sys.prefix, "packages": {}, "checks": []}
    receipt = output / "installed-acceptance.json"
    try:
        if sys.prefix == sys.base_prefix:
            raise RuntimeError("A separate virtual environment is required")
        config = Path(sys.prefix) / "pyvenv.cfg"
        if "include-system-site-packages = true" in config.read_text().lower():
            raise RuntimeError("Clean installation cannot inherit system site packages")
        for key in ("PYTHONPATH", "COCHEM_BASE_ROOT", "COCHEM_TOPOS_ROOT", "COCHEM_TORQ_ROOT"):
            if os.environ.get(key):
                raise RuntimeError(f"Source import override must be absent: {key}")
        for project in ("CoChem-BASE", "cochem-topos", "CoChem-TORQ"):
            dist = importlib.metadata.distribution(project)
            direct = json.loads(dist.read_text("direct_url.json") or "{}")
            if direct.get("dir_info", {}).get("editable"):
                raise RuntimeError(f"{project} is editable")
            location = Path(dist.locate_file("")).resolve()
            if not location.is_relative_to(Path(sys.prefix).resolve()):
                raise RuntimeError(f"{project} is outside the isolated environment")
            result["packages"][project] = {"version": dist.version, "location": str(location),
                                            "direct_url_sha256": hashlib.sha256(json.dumps(direct, sort_keys=True).encode()).hexdigest()}
        import topos

        from .base_integration import BaseRuntime
        from .config import SystemConfig
        from .models import Molecule, RunRequest
        from .publication import export_bundle, verify_bundle
        from .review import append_decision, create_ensemble_manifest
        from .storage import RunStore
        from .workflow import Workflow

        if not Path(topos.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
            raise RuntimeError("TOPOS imports from outside the installed environment")
        providers = list(importlib.metadata.entry_points(group="cochem.modules", name="topos"))
        if len(providers) != 1 or providers[0].load().metadata()["integration_contract"] != "cochem.module-handoff/1":
            raise RuntimeError("Installed BASE module provider is missing or ambiguous")
        # BASE owns this package name; TOPOS must never replace it on installation.
        own_files = {str(path) for path in importlib.metadata.distribution("cochem-topos").files or []}
        if any(path.startswith("frontend/") for path in own_files):
            raise RuntimeError("TOPOS wheel overwrites BASE's frontend namespace")
        for arguments in (["-m", "pip", "check"], ["-m", "topos", "--version"],
                          ["-m", "topos", "request-schema"], ["-m", "topos", "matrix", "support"]):
            completed = subprocess.run([sys.executable, "-I", *arguments], text=True, capture_output=True, check=False, timeout=120)
            result["checks"].append({"command": [sys.executable, "-I", *arguments], "returncode": completed.returncode,
                                     "stdout": completed.stdout, "stderr": completed.stderr})
            if completed.returncode:
                raise RuntimeError("Installed command failed: " + " ".join(arguments))
        executable_folder = Path(sys.executable).parent
        for name, argument in (("cochem-topos", "--version"), ("cochem-topos-release", "--help"), ("topos-ui", "--help")):
            command = [str(executable_folder / name), argument]
            completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=120)
            result["checks"].append({"command": command, "returncode": completed.returncode,
                                     "stdout": completed.stdout, "stderr": completed.stderr})
            if completed.returncode:
                raise RuntimeError(f"Installed console entry point failed: {name}")
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(Path(topos.__file__).parent / "streamlit_app.py")).run(timeout=30)
        if app.exception or not app.selectbox or not app.button:
            raise RuntimeError("Installed browser app failed to render its scientific controls")
        result["browser"] = {"status": "passed", "source": str(Path(topos.__file__).parent / "streamlit_app.py"),
                               "selectboxes": len(app.selectbox), "buttons": len(app.button),
                               "scope": "real installed Streamlit application render; native computation checked separately"}
        runtime = BaseRuntime(registry)
        result["base"] = runtime.provenance()
        result["registry_sha256"] = sha256(registry)
        water = Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.9572, 0, 0], [-.2399872, .927297, 0]])
        request = RunRequest(molecule=water, purpose="optimize", engine="xtb", method="GFN2-xTB", budget_seconds=90)
        record = Workflow(output / "runs", config=SystemConfig(execution_backend="base", base_registry_path=registry)).run(request)
        if record.status != "completed" or not record.candidates or record.candidates[0].status != "eligible":
            raise RuntimeError("Installed TOPOS did not complete genuine BASE-authorized xTB optimization")
        attempt = record.attempts[0]
        if (attempt.metadata.get("execution_kind") != "real" or attempt.engine_version != "6.7.1"
                or attempt.validation_status != "validated-for-protocol"):
            raise RuntimeError("Native engine execution provenance is missing")
        folder = Path(record.metadata["run_dir"])
        candidate = record.candidates[0]
        append_decision(folder, subject_id=candidate.candidate_id, action="accept", actor="installed-release-acceptance",
                        reason="Acceptance checks retained numerical evidence, not molecular research conclusions")
        ensemble = create_ensemble_manifest(folder, [candidate.candidate_id], actor="installed-release-acceptance")
        bundle = output / "research-bundle"
        export_bundle(folder, bundle, ensemble_sha256=ensemble["manifest_sha256"])
        verified = verify_bundle(bundle)
        result["native_run"] = {"run_id": record.run_id, "status": record.status, "validation_status": record.validation_status,
                                 "execution_kind": attempt.metadata["execution_kind"],
                                 "engine_version": attempt.engine_version, "energy_hartree": candidate.energy_hartree,
                                 "snapshot": RunStore(folder).verify(), "bundle": verified}
        result["dependencies"] = dependency_inventory()
        constraints = output / "requirements-installed.txt"
        constraints.write_text("".join(f"{item['name']}=={item['version']}\n" for item in result["dependencies"]
                                        if item["name"].lower().replace("_", "-") not in {"cochem-base", "cochem-topos", "cochem-torq"}))
        result["dependency_constraints"] = {"path": constraints.name, "sha256": sha256(constraints)}
        result["torq_consumer_ready"] = False
        result["status"] = "passed"
    except Exception as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    receipt.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gate = sub.add_parser("gate", help="Check evidence; never creates a tag or publishes")
    gate.add_argument("--source-root", required=True, type=Path)
    for name in ("validation", "installation", "hosted", "srs-acceptance", "distribution-manifest"):
        gate.add_argument("--" + name, type=Path)
    gate.add_argument("--output", type=Path, required=True)
    installed = sub.add_parser("installed-check", help="Verify noneditable wheel packages and real BASE calculation")
    installed.add_argument("--wheel", type=Path, required=True)
    installed.add_argument("--registry", type=Path, required=True)
    installed.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "installed-check":
        result = installed_acceptance(args.wheel.resolve(), args.registry.resolve(), args.output.resolve())
    else:
        result = release_gate(args.source_root, validation=args.validation, installation=args.installation,
                              hosted=args.hosted, srs_acceptance=args.srs_acceptance,
                              distribution_manifest=args.distribution_manifest)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(args.output), "published": False}))
    return 0 if result["status"] == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
