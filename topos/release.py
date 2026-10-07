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
import xml.etree.ElementTree as ET
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
    files.update(path for path in (root / "tests").rglob("*") if path.suffix in {".json", ".txt", ".stdout", ".out"})
    files.update((root / ".github" / "workflows").glob("*.yml"))
    files.update((root / ".docs" / "patches").rglob("*.patch"))
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


def _pytest_cases(receipt: dict[str, Any], receipt_path: Path, current: dict[str, str]) -> dict[str, str]:
    """Read exact named results from a source-bound, hash-checked pytest artifact."""
    verification = receipt.get("verification", {})
    if verification.get("sources_unchanged") is not True or any(
            verification.get("source_sha256", {}).get(name) != value for name, value in current.items()):
        raise ValueError("supplemental pytest source identity is missing or differs from the release")
    checks = [item for item in verification.get("checks", []) if item.get("check") == "pytest"]
    if len(checks) != 1 or checks[0].get("exit_code") != 0:
        raise ValueError("one successful pytest invocation is required per evidence receipt")
    check = checks[0]
    declared = check.get("junit_path")
    if not declared:
        declared = next((arg.split("=", 1)[1] for arg in check.get("command", [])
                         if arg.startswith("--junitxml=")), None)
    if not declared:
        raise ValueError("retained named JUnit artifact path is absent")
    path = Path(declared)
    if not path.is_absolute():
        path = receipt_path.parent / path
    if not path.exists():
        path = receipt_path.parent / Path(declared).name
    if path.is_symlink() or not path.is_file() or sha256(path) != check.get("junit_sha256"):
        raise ValueError("named JUnit artifact is missing or its digest differs")
    cases = {}
    for case in ET.parse(path).iter("testcase"):
        name = case.get("classname", "") + "::" + case.get("name", "")
        if name in cases or not case.get("classname") or not case.get("name"):
            raise ValueError("JUnit testcase identity is missing or duplicated")
        cases[name] = ("failed" if case.find("failure") is not None else "error" if case.find("error") is not None
                       else "skipped" if case.find("skipped") is not None else "passed")
    summary = check.get("junit", {})
    if (len(cases) != summary.get("tests") or not cases
            or sum(value == "skipped" for value in cases.values()) != summary.get("skipped")
            or summary.get("failures") != 0 or summary.get("errors") != 0
            or any(value in {"failed", "error"} for value in cases.values())):
        raise ValueError("retained named JUnit results disagree with the passing summary")
    return cases


def release_gate(root: Path, *, validation: Path | None = None, installation: Path | None = None,
                 hosted: Path | None = None, srs_acceptance: Path | None = None,
                 distribution_manifest: Path | None = None,
                 supplemental_validations: list[Path] | None = None,
                 hosted_extended: Path | None = None, hosted_repository: str | None = None,
                 hosted_run_id: str | None = None, hosted_run_attempt: str | None = None) -> dict[str, Any]:
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
    unresolved_gaps = support.get("unresolved_track_gaps", support["topos_track_gaps"])
    if unresolved_gaps:
        blockers.append("Method matrix: unresolved source track gaps " + ", ".join(unresolved_gaps))
    classified = {item["row_id"] for item in support.get("unavailable_by_design", [])}
    if set(support["topos_track_gaps"]) - set(unresolved_gaps) != classified:
        blockers.append("Method matrix: omitted track gaps lack an explicit unavailable-by-design classification")
    for item in support.get("unavailable_by_design", []):
        path = (root / item.get("source_path", "")).resolve()
        source_lines = item.get("source_lines", [])
        if (item.get("disposition") != "unavailable-by-design" or not path.is_relative_to(root)
                or not path.is_file() or path.is_symlink() or sha256(path) != item.get("source_sha256")
                or not source_lines or not item.get("source_excerpt")):
            blockers.append("Method matrix: unavailable-by-design classification lacks matching source evidence")
            continue
        lines = path.read_text().splitlines()
        if (any(not isinstance(line, int) or isinstance(line, bool) or not 1 <= line <= len(lines) for line in source_lines)
                or item["source_excerpt"] not in "\n".join(lines[line - 1] for line in source_lines)):
            blockers.append("Method matrix: unavailable-by-design source excerpt does not match its cited lines")
    coverage = {"local_skipped": [], "covered_by_supplements": {}, "uncovered": []}
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
                or any(pytest.get(key) != 0 for key in ("failures", "errors"))
                or not isinstance(pytest.get("skipped"), int) or pytest.get("skipped", -1) < 0):
            blockers.append("Regression: nonzero executed tests with zero failures/errors and explicit skip accounting required")
        if pytest.get("skipped", 0):
            try:
                local = _pytest_cases(verified, validation, current)
                missing = {name for name, status in local.items() if status == "skipped"}
                coverage["local_skipped"] = sorted(missing)
                for index, path in enumerate(supplemental_validations or []):
                    supplement = load(path, f"supplemental pytest {index + 1}")
                    actual = _pytest_cases(supplement, path, current)
                    passed = {name for name, status in actual.items() if status == "passed"}
                    for name in sorted(missing & passed):
                        coverage["covered_by_supplements"][name] = {"receipt": str(path), "sha256": sha256(path)}
                    missing -= passed
                coverage["uncovered"] = sorted(missing)
                if missing:
                    blockers.append(f"Regression: {len(missing)} named skipped tests lack matching-source executed passing evidence")
            except (ValueError, OSError, ET.ParseError, TypeError) as exc:
                blockers.append(f"Regression testcase coverage: {exc}")
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
                    or entry.get("coding_gaps") or entry.get("additional_acceptance_conditions")
                    or entry.get("verification", {}).get("pending_current_source_regression") is True
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
        if (installed.get("torq_consumer_ready") is not True
                or installed.get("torq_handoff", {}).get("status") != "passed"
                or installed.get("torq_handoff", {}).get("computation_performed") is not False):
            blockers.append("Installation: actual versioned TORQ consumption round trip is missing")
        native = installed.get("native_run", {})
        if (native.get("status") != "completed" or native.get("execution_kind") != "real"
                or native.get("engine_version") != "6.7.1" or not native.get("snapshot") or not native.get("bundle")):
            blockers.append("Installed wheel: actual versioned calculation, snapshot and verified export are missing")
        expected_wheels = {item["sha256"] for item in manifest.get("artifacts", []) if item.get("name", "").endswith(".whl")}
        if not expected_wheels or installed.get("topos_wheel_sha256") not in expected_wheels:
            blockers.append("Installed wheel: tested TOPOS wheel does not match the candidate artifact")
    expected_identity = {"github_repository": hosted_repository, "github_run_id": hosted_run_id,
                         "github_run_attempt": hosted_run_attempt}
    hosted_identity = None
    native_receipts = [
        (hosted, "hosted ORCA acceptance", "topos-orca-physical-acceptance/0.1.0",
         "scripts/accept_orca_topos.py", "acceptance_script_sha256",
         {"hf3c-energy-gradient", "r2scan3c-optimization-thermochemistry", "wb97xv-optimization", "counterpoise", "goat-refinement"}),
        (hosted_extended, "extended hosted ORCA acceptance", "topos-orca-extended-acceptance/0.1.0",
         "scripts/accept_orca_extended.py", "script_sha256",
         {"native-hessian", "native-vpt2", "MP2", "MP2-optimization", "CCSD(T)", "AUTOCI-CCSD(T)", "DLPNO-CCSD(T1)", "DLPNO-counterpoise",
          "CCSD(T)-F12D/RI", "F12-MP2", "F12-RI-MP2", "F12-composite", "R2-composite"}),
    ]
    for path, label, schema, script, digest_key, required in native_receipts:
        licensed = load(path, label)
        if not licensed:
            continue
        cases = licensed.get("cases", {})
        if (licensed.get("schema_version") != schema or licensed.get("status") != "passed"
                or not isinstance(cases, dict) or not required.issubset(cases)
                or any(not isinstance(cases[key], dict) or cases[key].get("status") != "passed"
                       for key in required & set(cases))):
            blockers.append(f"Hosted ORCA ({label}): every required native case must pass")
        identity = {key: str(licensed.get(key) or "") for key in
                    ("github_repository", "github_run_id", "github_run_attempt", "github_sha")}
        if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", identity["github_repository"])
                or not re.fullmatch(r"[1-9][0-9]*", identity["github_run_id"])
                or not re.fullmatch(r"[1-9][0-9]*", identity["github_run_attempt"])
                or not re.fullmatch(r"[0-9a-fA-F]{40}", identity["github_sha"])):
            blockers.append(f"Hosted ORCA ({label}): exact repository/run/attempt/commit identity required")
        if any(value is not None and identity[key] != str(value) for key, value in expected_identity.items()):
            blockers.append(f"Hosted ORCA ({label}): receipt differs from the selected repository/run/attempt")
        if hosted_identity is not None and identity != hosted_identity:
            blockers.append(f"Hosted ORCA ({label}): baseline and extended evidence refer to different runs")
        hosted_identity = hosted_identity or identity
        if licensed.get(digest_key) != current.get(script):
            blockers.append(f"Hosted ORCA ({label}): acceptance script differs from current release source")
        native_source = licensed.get("source", {}).get("source_files", {})
        package_files = {name: digest for name, digest in current.items() if name.startswith("topos/") and name.endswith(".py")}
        if any(native_source.get(name) != digest for name, digest in package_files.items()):
            blockers.append(f"Hosted ORCA ({label}): current package source has not been correlated with native execution")
    if hosted_identity is not None:
        for index, path in enumerate(supplemental_validations or []):
            supplement = load(path, f"supplemental pytest {index + 1}")
            if (supplement.get("schema_version") == "topos-native-pytest/1"
                    and any(str(supplement.get(key) or "") != value for key, value in hosted_identity.items())):
                blockers.append(f"Hosted ORCA: supplemental pytest {index + 1} differs from selected native run identity")
    return {"schema_version": "topos-release-gate/0.1.0", "status": "blocked" if blockers else "passed",
            "release_certified": not blockers, "published": False, "source_sha256": current,
            "matrix_support": support, "evidence": evidence, "testcase_coverage": coverage, "blockers": blockers,
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
        from .review import (
            accept_torq_receipt,
            append_decision,
            create_ensemble_manifest,
            export_torq_handoff,
        )
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
        from Libraries import cochem_torq_topos_handoff as receiver

        receiver_path = Path(receiver.__file__).resolve()
        if not receiver_path.is_relative_to(Path(sys.prefix).resolve()):
            raise RuntimeError("TORQ consumer imports outside its noneditable distribution")
        handoff = export_torq_handoff(folder, output / "torq-handoff.json")
        consumed = receiver.consume_topos_handoff(output / "torq-handoff.json", output / "torq-import")
        if (consumed != receiver.load_imported_ensemble(output / "torq-import")
                or consumed["ensemble"]["members"] != handoff["members"]
                or consumed["ensemble"].get("computation_performed") is not False):
            raise RuntimeError("TORQ import did not preserve exact reviewed member identity")
        accepted = accept_torq_receipt(folder, output / "torq-import/receipt.json")
        if accepted != consumed["receipt"]:
            raise RuntimeError("TOPOS did not accept the actual installed TORQ consumer receipt")
        result["torq_handoff"] = {"status": "passed", "computation_performed": False,
                                   "receipt": accepted, "consumer_source_sha256": sha256(receiver_path)}
        result["torq_consumer_ready"] = True
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
    for name in ("validation", "installation", "hosted", "hosted-extended", "srs-acceptance", "distribution-manifest"):
        gate.add_argument("--" + name, type=Path)
    for name in ("hosted-repository", "hosted-run-id", "hosted-run-attempt"):
        gate.add_argument("--" + name, help="Require the hosted receipt to match the explicitly selected artifact run")
    gate.add_argument("--output", type=Path, required=True)
    gate.add_argument("--supplemental-validation", type=Path, action="append", default=[],
                      help="Same-source pytest receipt and hashed JUnit artifact covering named local skips; repeatable")
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
                              distribution_manifest=args.distribution_manifest,
                              supplemental_validations=args.supplemental_validation,
                              hosted_extended=args.hosted_extended, hosted_repository=args.hosted_repository,
                              hosted_run_id=args.hosted_run_id, hosted_run_attempt=args.hosted_run_attempt)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(args.output), "published": False}))
    return 0 if result["status"] == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
