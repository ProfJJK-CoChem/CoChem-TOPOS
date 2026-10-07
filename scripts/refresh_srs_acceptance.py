"""Refresh the reviewed SRS ledger against a retained current whole-suite receipt.

This updates only local regression evidence. It cannot clear coding gaps,
licensed/GPU/external-engine conditions or certify the complete release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refresh(root: Path, ledger_path: Path, validation_path: Path, *, reviewer: str, junit_path: Path) -> dict:
    if not reviewer.strip():
        raise ValueError("A reviewer identity for the requirement/source assessment is required")
    ledger = json.loads(ledger_path.read_text())
    validation = json.loads(validation_path.read_text())
    if ledger.get("srs_sha256") != digest(root / '.docs/CoChem-TOPOS_SRS.md'):
        raise ValueError("SRS changed; requirement assessments need a new chapter-by-chapter review")
    verification = validation.get("verification", {})
    checks = [item for item in verification.get("checks", []) if item.get("check") == "pytest"]
    if len(checks) != 1 or checks[0].get("exit_code") != 0 or verification.get("sources_unchanged") is not True:
        raise ValueError("One completed, source-stable whole-suite pytest receipt is required")
    junit = checks[0].get("junit", {})
    if junit.get("tests", 0) <= 0 or any(junit.get(key) != 0 for key in ("failures", "errors")):
        raise ValueError("Whole-suite evidence must contain executed tests and no failures/errors; skips remain explicit")
    if junit_path.is_symlink() or digest(junit_path) != checks[0].get("junit_sha256"):
        raise ValueError("JUnit artifact does not match the retained validation receipt")
    command = checks[0].get("command", [])
    arguments = command[command.index("pytest") + 1:] if "pytest" in command else []
    if not any(arg in {"tests", "tests/v010"} for arg in arguments) or any(
            arg in {"-k", "-m", "--deselect", "--ignore", "--ignore-glob"}
            or arg.startswith(("--deselect=", "--ignore=", "--ignore-glob=")) for arg in arguments):
        raise ValueError("Receipt must identify an unfiltered complete regression target")
    cases = []
    for case in ET.parse(junit_path).iter("testcase"):
        status = ("failed" if case.find("failure") is not None else "error" if case.find("error") is not None
                  else "skipped" if case.find("skipped") is not None else "passed")
        cases.append({"class": case.get("classname", ""), "name": case.get("name", ""), "status": status})
    if (len(cases) != junit["tests"] or sum(c["status"] == "skipped" for c in cases) != junit.get("skipped")
            or any(c["status"] in {"failed", "error"} for c in cases)):
        raise ValueError("JUnit test outcomes differ from the validation receipt")
    tested = verification.get("source_sha256", {})
    evidence = {"path": os.path.relpath(validation_path.resolve(), ledger_path.parent.resolve()),
                "sha256": digest(validation_path)}
    for requirement in ledger["requirements"].values():
        unverified = []
        for item in requirement["implementation"] + requirement["acceptance_tests"]:
            path = root / item["path"]
            current = digest(path) if path.is_file() and not path.is_symlink() else None
            item["sha256"] = current
            if current is None or tested.get(item["path"]) != current:
                unverified.append(item["path"])
        missing_tests, skipped_tests, executed = [], [], []
        for target in requirement["acceptance_tests"]:
            module = Path(target["path"]).stem
            for function in target.get("test_functions", []):
                matches = [case for case in cases if module in case["class"].split(".")
                           and case["name"].split("[")[0] == function]
                if not matches:
                    missing_tests.append(target["path"] + "::" + function)
                for case in matches:
                    identity = case["class"] + "::" + case["name"]
                    (skipped_tests if case["status"] == "skipped" else executed).append(identity)
        pending = bool(unverified or missing_tests or skipped_tests or not executed)
        requirement["verification"].update(
            pending_current_source_regression=pending, current_suite_tests=junit["tests"],
            current_suite_skipped=junit["skipped"], current_receipt_missing_files=unverified,
            missing_acceptance_tests=missing_tests, skipped_acceptance_tests=skipped_tests,
            executed_passing_acceptance_tests=executed, junit_sha256=digest(junit_path),
            source_assessment_reviewer=reviewer,
        )
        requirement["evidence"] = [item for item in requirement["evidence"] if item["path"] != evidence["path"]] + [evidence]
        conditions = requirement["additional_acceptance_conditions"]
        if not pending and "current_whole_suite" in conditions:
            conditions.remove("current_whole_suite")
        requirement["status"] = ("partial" if requirement["coding_gaps"] else
                                 "verification-pending" if pending or conditions else "verified")
    ledger["generated_at"] = datetime.now(timezone.utc).isoformat()
    ledger["status"] = "verified" if all(item["status"] == "verified" for item in ledger["requirements"].values()) else "incomplete"
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--junit", type=Path, required=True, help="Exact retained JUnit XML bound by the validation receipt")
    parser.add_argument("--reviewer", required=True,
                        help="Identity that reviewed the ledger's behavior assessments and confirms this receipt covers the whole regression suite")
    args = parser.parse_args()
    try:
        ledger = refresh(args.source_root, args.ledger, args.validation, reviewer=args.reviewer, junit_path=args.junit)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"SRS refresh failed: {exc}\n")
    print(json.dumps({"status": ledger["status"], "requirements": {
        state: sum(item["status"] == state for item in ledger["requirements"].values())
        for state in ("verified", "partial", "verification-pending")}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
