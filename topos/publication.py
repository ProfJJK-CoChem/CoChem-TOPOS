"""Reproducible, verified local research bundles; no network publication actions."""

from __future__ import annotations

import csv
import inspect
import io
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import h5py
from filelock import FileLock

from .references import METHOD_REFERENCES, executed_references
from .review import (
    get_ensemble_manifest,
    list_decisions,
    validate_reviewed_ensemble,
    validate_scientific_candidate,
)
from .storage import (
    IntegrityError,
    RunStore,
    artifact_inventory,
    atomic_json,
    confined_file,
    digest_json,
    file_digest,
    fsync_directory,
    json_bytes,
    read_json,
)

BUNDLE_SCHEMA = "topos-bundle/0.1.0"


def _citation_records(
    record: Mapping[str, Any], ensemble: Mapping[str, Any], supplied: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    references, unresolved = executed_references(record)
    for citation in supplied:
        if not isinstance(citation, Mapping):
            raise IntegrityError("Citation records must be JSON mappings")
        # Preserve supplied additions as such, without upgrading them to verified execution.
        citation = {**dict(citation), "attribution": "author-supplied"}
        if not any(c.get("doi") and c.get("doi") == citation.get("doi") for c in references):
            references.append(citation)
    software = record.get("metadata", {}).get("software")
    if software:
        references.append({"kind": "software", "name": software.get("name", "CoChem-TOPOS"),
                           "version": software.get("version"), "commit": software.get("commit"),
                           "doi": None, "status": "executed software identity; release DOI not supplied"})
    else:
        unresolved.append("TOPOS software release/commit citation metadata has not been supplied")
    methods = sorted({validate_scientific_candidate(record, c)["method"] for c in ensemble["members"]})
    for method in methods:
        reference = METHOD_REFERENCES.get(method.replace("²", "2"))
        if reference:
            if not any(c.get("doi") == reference["doi"] for c in references):
                references.append({"kind": "method", "method": method, **reference,
                                   "verification": "bibliographic metadata in the official method repository"})
        elif not any(c.get("method") == method for c in references):
            unresolved.append(f"Verified scientific method citation not supplied: {method}")
    unresolved.append("Author must verify citation applicability and completeness before public release")
    return references, unresolved


ORCA_DATA_NOTICE = """ORCA-generated DATA: ORCA EULA, June 2025, sections 3(c), 3(d), 3(f).
Scientific journal publication is expressly permitted. Database sharing remains
subject to the EULA's non-commercial purpose, conditions, notices and disclaimer;
this archive does not grant additional rights. No ORCA executable is included.
Source license supplied by the licensee; applicability and any additional written
permissions must be reviewed by the responsible licensee before distribution.

7. DISCLAIMER OF WARRANTY
There is no warranty for SOFTWARE, to the extent permitted by applicable law. Except when otherwise
stated in writing, the copyright holders and/or other parties provide SOFTWARE “as is” without
warranty of any kind, either expressed or implied, including, but not limited to, the implied warranties
of merchantability and fitness for a particular purpose. The entire risk as to the quality and
performance of SOFTWARE is with LICENSEE. Should SOFTWARE prove defective, LICENSEE assumes
the cost of all necessary servicing, repair or correction.
"""


def _license_metadata(identifier: Any, record: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    supported = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC-BY-NC-4.0", "CC-BY-NC-SA-4.0",
                 "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "GPL-3.0-only",
                 "GPL-3.0-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later"}
    if identifier is not None and (not isinstance(identifier, str) or (
            identifier not in supported and not re.fullmatch(r"LicenseRef-[A-Za-z0-9][A-Za-z0-9.-]*", identifier))):
        raise IntegrityError("License must be a supported SPDX identifier or a documented LicenseRef identifier")
    orca = [a["attempt_id"] for a in record.get("attempts", []) if a.get("engine", "").lower() == "orca"
            and a.get("metadata", {}).get("execution_kind") == "real" and a.get("command")]
    issues = []
    if identifier is None:
        issues.append("Artifact licenses/access rights have not been supplied")
    elif identifier.startswith("LicenseRef-"):
        issues.append("Author must supply and review the referenced custom license text")
    if orca:
        issues.append("ORCA DATA license conditions require author review; a bundle license does not override the ORCA EULA")
        if identifier and identifier != "LicenseRef-ORCA-EULA":
            issues.append("Proposed blanket bundle license is not established for ORCA DATA; provide artifact-specific permissions")
    return {
        "identifier": identifier, "status": "author-supplied-unverified" if identifier else "unresolved",
        "scope": "proposed author metadata only; does not grant or override rights for included artifacts",
        "orca_data_attempt_ids": orca,
        "orca_data_notice": "ORCA-DATA-NOTICE.txt" if orca else None,
        "access_review_required": True,
    }, issues


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _write_json(path: Path, value: Any) -> None:
    _write_bytes(path, json_bytes(value) + b"\n")


def _csv(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _selected_rows(record: Mapping[str, Any], ensemble: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    candidates = {c["candidate_id"]: c for c in record["candidates"]}
    for candidate_id in ensemble["member_ids"]:
        candidate = candidates[candidate_id]
        attempt = validate_scientific_candidate(record, candidate)
        electronic = candidate.get("energy_hartree")
        gibbs = candidate.get("gibbs_hartree")
        thermal = attempt.get("metadata", {}).get("thermochemistry") or {}
        rows.append({
            "candidate_id": candidate_id, "attempt_id": attempt["attempt_id"],
            "engine": attempt["engine"], "engine_version": attempt["engine_version"],
            "method": attempt["method"], "comparison_protocol": candidate["comparison_protocol"],
            "electronic_energy_hartree": electronic,
            "gibbs_energy_hartree": gibbs,
            "zpe_hartree": thermal.get("zpe_hartree"),
            "thermal_enthalpy_correction_hartree": thermal.get("thermal_enthalpy_correction_hartree"),
            "entropy_hartree_per_k": thermal.get("entropy_hartree_per_k"),
            "standard_state_correction_hartree": thermal.get("standard_state_correction_hartree"),
            "temperature_k": thermal.get("temperature_k"), "thermal_model": thermal.get("model"),
            "missing_values": "; ".join(
                name + ": not reported"
                for name, value in (("electronic_energy", electronic), ("gibbs_energy", gibbs))
                if value is None
            ),
            "degeneracy": candidate["degeneracy"],
        })
    return rows


def _reproduction_products(record, ensemble, fields):
    """Portable standard-library recipe, copied verbatim into each research bundle."""
    import csv
    import html
    import io

    candidates = {c["candidate_id"]: c for c in record["candidates"]}
    attempts = {a["attempt_id"]: a for a in record["attempts"]}
    rows = []
    for member_id in ensemble["member_ids"]:
        candidate = candidates[member_id]
        attempt = attempts[candidate["attempt_id"]]
        electronic, gibbs = candidate.get("energy_hartree"), candidate.get("gibbs_hartree")
        thermal = attempt.get("metadata", {}).get("thermochemistry") or {}
        rows.append({
            "candidate_id": member_id, "attempt_id": attempt["attempt_id"],
            "engine": attempt["engine"], "engine_version": attempt["engine_version"],
            "method": attempt["method"], "comparison_protocol": candidate["comparison_protocol"],
            "electronic_energy_hartree": electronic, "gibbs_energy_hartree": gibbs,
            "zpe_hartree": thermal.get("zpe_hartree"),
            "thermal_enthalpy_correction_hartree": thermal.get("thermal_enthalpy_correction_hartree"),
            "entropy_hartree_per_k": thermal.get("entropy_hartree_per_k"),
            "standard_state_correction_hartree": thermal.get("standard_state_correction_hartree"),
            "temperature_k": thermal.get("temperature_k"), "thermal_model": thermal.get("model"),
            "missing_values": "; ".join(name + ": not reported" for name, value in (
                ("electronic_energy", electronic), ("gibbs_energy", gibbs)) if value is None),
            "degeneracy": candidate["degeneracy"],
        })
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    present = [row for row in rows if row["electronic_energy_hartree"] is not None]
    minimum = min((row["electronic_energy_hartree"] for row in present), default=None)
    height = max(160, 90 + 40 * len(present))
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="920" height="{height}" viewBox="0 0 920 {height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           '<g font-family="sans-serif" font-size="13" fill="black">',
           '<text x="20" y="25">Reviewed relative electronic energies (hartree); common comparison protocol</text>']
    if minimum is None:
        svg.append('<text x="20" y="65">No electronic energies reported; no numerical values plotted.</text>')
    else:
        span = max(row["electronic_energy_hartree"] - minimum for row in present)
        svg.append('<line x1="330" y1="40" x2="330" y2="' + str(height - 35) + '" stroke="black"/>')
        for index, row in enumerate(present):
            delta = row["electronic_energy_hartree"] - minimum
            x, y = 330 + (380 * delta / span if span > 0 else 0), 65 + 40 * index
            label = html.escape(str(row["candidate_id"]))
            svg.extend([f'<text x="20" y="{y + 4}">{label}</text>',
                        f'<circle cx="{x:.6f}" cy="{y}" r="4" fill="#175d99"/>',
                        f'<text x="740" y="{y + 4}">{delta:.12g} Eh</text>'])
        svg.append(f'<text x="20" y="{height - 10}">Zero = lowest reported selected energy; {len(rows) - len(present)} missing values omitted.</text>')
    svg.extend(["</g>", "</svg>", ""])
    return stream.getvalue().encode("utf-8"), "\n".join(svg).encode("utf-8")


def reviewed_ensemble_sensitivity(
    record: Mapping[str, Any], ensemble: Mapping[str, Any], options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate only the reviewed, comparable observed members; never infer completeness."""
    from .models import Candidate
    from .thermochemistry import ensemble_sensitivity

    options = dict(options or {})
    allowed = {"quantity", "windows_kcal_mol", "missing_states", "missing_gap_kcal_mol"}
    if set(options) - allowed:
        raise IntegrityError("Unknown sampling sensitivity assumption")
    if "missing_gap_kcal_mol" in options and "missing_states" not in options:
        raise IntegrityError("A missing-state energy gap requires an explicitly declared missing-state count")
    candidates_by_id = {candidate["candidate_id"]: candidate for candidate in record["candidates"]}
    members = [candidates_by_id[key] for key in ensemble["member_ids"]]
    for member in members:
        validate_scientific_candidate(record, member)
    quantity = options.get("quantity", "gibbs" if all(c.get("gibbs_hartree") is not None for c in members)
                           else "electronic")
    windows = options.get("windows_kcal_mol", sorted({1.0, 3.0, 6.0,
                          float(record["request"].get("energy_window_kcal_mol", 6.0))}))
    try:
        temperature = float(record["request"].get("temperature_k", 298.15))
        if quantity == "gibbs":
            for member in members:
                thermal = validate_scientific_candidate(record, member).get("metadata", {}).get("thermochemistry")
                if thermal and thermal.get("temperature_k") != temperature:
                    raise ValueError("member Gibbs temperature differs from requested ensemble temperature")
        result = ensemble_sensitivity(
            [Candidate.model_validate(candidate) for candidate in members], temperature_k=temperature,
            quantity=quantity, windows_kcal_mol=tuple(windows),
            missing_states=options.get("missing_states", 0),
            missing_gap_kcal_mol=options.get("missing_gap_kcal_mol"),
        )
    except (TypeError, ValueError) as exc:
        if "all ensemble members require valid" in str(exc):
            return {"schema_version": "topos-sampling-sensitivity/0.1.0", "status": "unavailable",
                    "reason": str(exc), "observed_member_ids": ensemble["member_ids"],
                    "quantity": quantity, "temperature_k": temperature, "options": options,
                    "ensemble": None, "windows": [], "missing_population_upper_bound": None,
                    "completeness": "not-certified; required member scores are absent"}
        raise IntegrityError(f"Invalid sampling sensitivity inputs: {exc}") from exc
    declared = "missing_states" in options
    if not declared:
        result["missing_states_assumption"] = None
        result["missing_degeneracy_assumption"] = None
    elif options["missing_states"] == 0:
        # This is an author's explicit completeness assumption, not a measured result.
        result["missing_population_upper_bound"] = 0.0
    return {"schema_version": "topos-sampling-sensitivity/0.1.0", "status": "completed",
            "scope": "reviewed comparable observed conformers only; does not certify search completeness",
            "observed_member_ids": ensemble["member_ids"], "quantity": quantity,
            "temperature_k": temperature, "missing_state_assumptions_declared": declared,
            "options": options, **result}


def _sensitivity_script() -> bytes:
    return b'''#!/usr/bin/env python3
"""Recompute sensitivity with the archived TOPOS 0.1.0 environment; output must be new.
Usage: python recompute-sensitivity.py OUTPUT_JSON
"""
from pathlib import Path
import json
import sys
from topos.publication import reviewed_ensemble_sensitivity, verify_bundle

root = Path(__file__).resolve().parent
verify_bundle(root)
if len(sys.argv) != 2:
    raise SystemExit("Usage: python recompute-sensitivity.py OUTPUT_JSON")
record = json.loads((root / "run.json").read_text())
ensemble = json.loads((root / "ensemble.json").read_text())
original = json.loads((root / "sampling-sensitivity.json").read_text())
result = reviewed_ensemble_sensitivity(record, ensemble, original["options"])
with Path(sys.argv[1]).open("x", encoding="utf-8") as handle:
    json.dump(result, handle, sort_keys=True, indent=2, allow_nan=False)
    handle.write("\\n")
'''


def _reproduction_script() -> bytes:
    """Regenerate into a separate directory after checking archived input digests."""
    script = '''#!/usr/bin/env python3
"""Regenerate the selected table and energy plot. Requires Python >=3.10 only.

Usage: python regenerate.py OUTPUT_DIRECTORY
Checks the archived manifest/input digests, then creates a new output directory.
Checksums establish integrity, not author identity or scientific correctness.
"""
from pathlib import Path
import hashlib
import json
import sys

'''
    script += inspect.getsource(_reproduction_products)
    script += '''
if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python regenerate.py OUTPUT_DIRECTORY")
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != manifest["manifest_sha256"]:
        raise SystemExit("Manifest checksum mismatch")
    inventory = {entry["path"]: entry for entry in manifest["files"]}
    for name in ("run.json", "ensemble.json", "regenerate.py"):
        content = (root / name).read_bytes()
        if len(content) != inventory[name]["size_bytes"] or hashlib.sha256(content).hexdigest() != inventory[name]["sha256"]:
            raise SystemExit("Input checksum mismatch: " + name)
    record = json.loads((root / "run.json").read_text(encoding="utf-8"))
    ensemble = json.loads((root / "ensemble.json").read_text(encoding="utf-8"))
    table, figure = _reproduction_products(record, ensemble, manifest["table_recipe"]["columns"])
    destination = Path(sys.argv[1])
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "selected.csv").write_bytes(table)
    (destination / "relative-energy.svg").write_bytes(figure)
'''
    return script.encode("utf-8")


def _methods_text(
    record: Mapping[str, Any], ensemble: Mapping[str, Any], references: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "# TOPOS calculation provenance", "",
        f"Run: `{record['run_id']}`. Schema: `{record['schema_version']}`.",
        f"Committed snapshot: `{ensemble['source_snapshot_sha256']}`.",
        f"Reviewed ensemble: `{ensemble['manifest_sha256']}`.", "",
        "This bundle records executed calculations and reviewer decisions. It does not establish "
        "exhaustive conformational sampling, experimental accuracy or external publication.", "",
        "## Search and resource settings", "",
        "The exact request is in `run.json:request`; the method-matrix revision, selected profile, "
        "random seeds, thread/memory/time limits, atom and isotope maps, fragment charge/spin states, "
        "solvent, and constraints are retained there. Attempts distinguish execution from "
        "validation and retain failures as well as successes.", "",
        "## Selected calculations", "",
    ]
    seen = set()
    for candidate in ensemble["members"]:
        attempt = validate_scientific_candidate(record, candidate)
        if attempt["attempt_id"] in seen:
            continue
        seen.add(attempt["attempt_id"])
        derived = attempt.get("metadata", {}).get("result_kind") == "derived-optimization"
        derivation = (
            "Geometry optimization was performed by TOPOS; energy/gradient originate from the "
            f"accepted real derivative attempt `{attempt['metadata']['accepted_derivative_attempt_id']}`. "
            if derived else ""
        )
        if attempt.get("metadata", {}).get("result_kind") == "physical-hessian-thermochemistry":
            thermal = attempt["metadata"].get("thermochemistry")
            derivation = ("TOPOS constructed the physical Cartesian Hessian from retained central "
                          "finite differences of actual engine gradients, projected translations/rotations, "
                          "and verified harmonic-minimum classification. ")
            if thermal:
                derivation += (f"Thermal model: {thermal['model']}, {thermal['temperature_k']} K; "
                               "ZPE, thermal enthalpy, entropy, standard-state correction and G are "
                               "separately recorded. Model settings and frequency scaling are in run.json. ")
        lines.append(
            f"- Attempt `{attempt['attempt_id']}`: {attempt['engine']} "
            f"{attempt['engine_version']}; method {attempt['method']}; "
            f"comparison protocol `{candidate['comparison_protocol']}`. "
            + derivation +
            "Engine input, argument array, raw outputs and structured quantities are retained in run.json "
            "and the checksummed snapshot."
        )
    lines.extend([
        "", "## Reproduction and missing data", "",
        "`run.json` preserves the original request, candidate geometries, atoms/isotopes, "
        "method/basis/solvent/constraints, resources, random seed, attempt history and parser provenance. "
        "`selected.csv` contains the reviewed members in manifest order; null quantities are empty "
        "CSV cells with a reason, never numerical zero sentinels. `candidate-ledger.json` includes "
        "unselected/failed candidates and their recorded reasons. `review.json` preserves the decision chain.",
        "", "Run `python regenerate.py NEW_OUTPUT_DIRECTORY` with Python 3.10 or newer to regenerate "
        "`selected.csv` and `relative-energy.svg` from checksummed inputs; no TOPOS installation is "
        "needed. The figure uses electronic-energy differences in hartree within the reviewed "
        "common comparison protocol; absent energies are omitted and counted explicitly. "
        "No sorting by HDF5 group names or filesystem "
        "globbing determines scientific membership.", "",
        "`sampling-sensitivity.json` records observed-ensemble truncation at explicit energy windows, "
        "temperature and score type. Electronic-energy weights are not Gibbs populations. "
        "Missing-conformer counts and population bounds remain unknown unless the author explicitly "
        "declares a count and minimum energy gap; such bounds are conditional assumptions. "
        "Only reviewed, comparable members enter the calculation. Recompute with "
        "`python recompute-sensitivity.py NEW_OUTPUT_JSON` in the archived TOPOS environment.", "",
        "## Citations and licenses", "",
    ])
    if references:
        lines.append("Citation records in citations.json include verified method references selected "
                     "from executed methods and any author-supplied additions; completeness and "
                     "applicability remain subject to author review.")
    else:
        lines.append("Citation metadata has not been supplied. Resolve software, method, model, "
                     "basis and reference-data citations before any public publication.")
    lines.extend(["", "License/access metadata is recorded in license.json. Missing rights information "
                  "blocks a publication-ready claim; local archive creation does not assign a license.", ""])
    return "\n".join(lines)


def export_bundle(
    run_dir: str | Path, destination: str | Path, *, ensemble_sha256: str | None = None,
    citations: Sequence[Mapping[str, Any]] | None = None,
    license_identifier: str | None = None,
    sensitivity_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze a reviewed current ensemble and every explicitly retained raw artifact.

    Local export is allowed with unresolved citation/license metadata, but the
    output records that incompleteness and never claims readiness to publish.
    """
    store = RunStore(run_dir)
    target = Path(destination).absolute()
    if target.is_symlink():
        raise IntegrityError("Bundle destination cannot be a symlink")
    if target == store.run_dir or store.run_dir in target.parents:
        raise IntegrityError("Export destination must be outside the live run directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(target.parent / f".{target.name}.export.lock"), timeout=10):
        if target.exists():
            raise FileExistsError(f"Immutable bundle already exists: {target}")
        with store.lock:
            record = store.load()
            snapshot = store.verify()
            from .cfour_artifacts import validate_scientific_export_membership

            validate_scientific_export_membership(record, snapshot)
            ensemble = get_ensemble_manifest(run_dir, digest=ensemble_sha256)
            decisions = list_decisions(run_dir)
            rows = _selected_rows(record, ensemble)
            sensitivity = reviewed_ensemble_sensitivity(record, ensemble, sensitivity_options)
            provided = citations if citations is not None else record.get("metadata", {}).get("citations", [])
            references, citation_issues = _citation_records(record, ensemble, provided)
            json_bytes(references)  # Reject nonfinite/nonserializable citation payloads.
            chosen_license = (license_identifier if license_identifier is not None
                              else record.get("metadata", {}).get("license"))
            license_metadata, license_issues = _license_metadata(chosen_license, record)
            staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.pending-", dir=target.parent))
            try:
                source_snapshot = store.snapshot_path()
                shutil.copytree(source_snapshot, staging / "snapshot")
                _write_json(staging / "run.json", record)
                _write_json(staging / "ensemble.json", ensemble)
                _write_json(staging / "review.json", decisions)
                _write_json(staging / "citations.json", references)
                _write_json(staging / "license.json", license_metadata)
                _write_json(staging / "sampling-sensitivity.json", sensitivity)
                _write_bytes(staging / "recompute-sensitivity.py", _sensitivity_script())
                if license_metadata["orca_data_attempt_ids"]:
                    _write_bytes(staging / "ORCA-DATA-NOTICE.txt", ORCA_DATA_NOTICE.encode("utf-8"))
                members = set(ensemble["member_ids"])
                latest = {d["subject_id"]: d for d in decisions}
                ledger = []
                for candidate in record["candidates"]:
                    decision = latest.get(candidate["candidate_id"])
                    ledger.append({
                        "candidate": candidate,
                        "selected": candidate["candidate_id"] in members,
                        "decision": decision,
                        "exclusion_reason": None if candidate["candidate_id"] in members else (
                            decision["reason"] if decision else candidate.get("metadata", {}).get(
                                "exclusion_reason", "Not included in the reviewed ensemble"
                            )
                        ),
                    })
                _write_json(staging / "candidate-ledger.json", ledger)
                fields = [
                    "candidate_id", "attempt_id", "engine", "engine_version", "method",
                    "comparison_protocol", "electronic_energy_hartree", "gibbs_energy_hartree",
                    "zpe_hartree", "thermal_enthalpy_correction_hartree", "entropy_hartree_per_k",
                    "standard_state_correction_hartree", "temperature_k", "thermal_model",
                    "missing_values", "degeneracy",
                ]
                _write_bytes(staging / "selected.csv", _csv(rows, fields))
                recipe_table, figure = _reproduction_products(record, ensemble, fields)
                if recipe_table != _csv(rows, fields):
                    raise IntegrityError("Reproduction recipe differs from validated scientific table")
                _write_bytes(staging / "relative-energy.svg", figure)
                _write_bytes(staging / "regenerate.py", _reproduction_script())
                _write_bytes(staging / "methods.md", _methods_text(record, ensemble, references).encode("utf-8"))
                inventory = []
                for path in sorted(p for p in staging.rglob("*") if p.is_file()):
                    with path.open("rb") as handle:
                        os.fsync(handle.fileno())
                    inventory.append({
                        "path": path.relative_to(staging).as_posix(),
                        "size_bytes": path.stat().st_size, "sha256": file_digest(path),
                    })
                unresolved = [*citation_issues, *license_issues]
                body = {
                    "schema_version": BUNDLE_SCHEMA, "run_id": record["run_id"],
                    "source_snapshot_sha256": snapshot["snapshot_id"],
                    "ensemble_sha256": ensemble["manifest_sha256"],
                    "state": "local-export", "publication_ready": False,
                    "publication_status": "not-published", "version_doi": None, "concept_doi": None,
                    "unresolved": unresolved,
                    "author_review_required": True,
                    "selected_member_ids": ensemble["member_ids"],
                    "table_recipe": {"file": "selected.csv", "columns": fields,
                                     "member_source": "ensemble.json:member_ids", "missing": "empty cell with reason",
                                     "script": "regenerate.py", "python_minimum": "3.10"},
                    "sensitivity_recipe": {"file": "sampling-sensitivity.json",
                                           "script": "recompute-sensitivity.py",
                                           "requires": "CoChem-TOPOS 0.1.0 archived environment",
                                           "scope": "reviewed observed members; missing states unknown unless declared"},
                    "figure_recipe": {"file": "relative-energy.svg", "script": "regenerate.py",
                                      "quantity": "relative electronic energy", "units": "hartree",
                                      "reference": "minimum reported selected electronic energy",
                                      "missing": "omitted and explicitly counted"},
                    "files": inventory,
                }
                manifest = {**body, "manifest_sha256": digest_json(body)}
                atomic_json(staging / "manifest.json", manifest)
                for directory in sorted((p for p in staging.rglob("*") if p.is_dir()), reverse=True):
                    fsync_directory(directory)
                fsync_directory(staging)
                verify_bundle(staging)
                os.replace(staging, target)
                fsync_directory(target.parent)
                return manifest
            finally:
                if staging.exists():
                    shutil.rmtree(staging)


def verify_bundle(destination: str | Path) -> dict[str, Any]:
    root = Path(destination)
    if root.is_symlink():
        raise IntegrityError("Bundle root cannot be a symlink")
    manifest = read_json(confined_file(root, "manifest.json"))
    if manifest.get("schema_version") != BUNDLE_SCHEMA:
        raise IntegrityError("Unsupported bundle schema")
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if digest_json(body) != manifest.get("manifest_sha256"):
        raise IntegrityError("Bundle manifest checksum mismatch")
    expected = {"manifest.json"}
    for entry in manifest.get("files", []):
        if entry["path"] in expected:
            raise IntegrityError("Duplicate bundle membership")
        path = confined_file(root, entry["path"])
        if path.stat().st_size != entry["size_bytes"] or file_digest(path) != entry["sha256"]:
            raise IntegrityError(f"Bundle artifact checksum mismatch: {entry['path']}")
        expected.add(entry["path"])
    if any(p.is_symlink() for p in root.rglob("*")):
        raise IntegrityError("Bundle contains a symlink")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != expected:
        raise IntegrityError("Bundle membership mismatch")
    ensemble = read_json(root / "ensemble.json")
    ensemble_body = {k: v for k, v in ensemble.items() if k != "manifest_sha256"}
    if digest_json(ensemble_body) != manifest.get("ensemble_sha256"):
        raise IntegrityError("Bundle ensemble digest mismatch")
    record = read_json(root / "run.json")
    if record.get("run_id") != manifest.get("run_id"):
        raise IntegrityError("Bundle record belongs to another run")
    if digest_json(record) != ensemble.get("source_record_sha256"):
        raise IntegrityError("Bundle record differs from reviewed record")
    try:
        decisions = json.loads(confined_file(root, "review.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise IntegrityError("Cannot read valid bundle review events") from exc
    validate_reviewed_ensemble(record, ensemble, decisions)
    if manifest.get("selected_member_ids") != ensemble["member_ids"]:
        raise IntegrityError("Bundle selected members differ from the reviewed ensemble")
    snapshot = read_json(root / "snapshot/manifest.json")
    committed_inventory = artifact_inventory(record)
    expected_snapshot_id = digest_json({"record_sha256": digest_json(record),
                                        "artifacts": committed_inventory})
    if (snapshot.get("record_sha256") != digest_json(record)
            or snapshot.get("snapshot_id") != manifest.get("source_snapshot_sha256")
            or snapshot.get("snapshot_id") != expected_snapshot_id
            or snapshot.get("artifacts") != committed_inventory
            or ensemble.get("source_snapshot_sha256") != manifest.get("source_snapshot_sha256")):
        raise IntegrityError("Bundle snapshot does not match its record and ensemble")
    for entry in committed_inventory:
        artifact = confined_file(root, "snapshot/artifacts/" + entry["path"])
        if artifact.stat().st_size != entry["size_bytes"] or file_digest(artifact) != entry["sha256"]:
            raise IntegrityError("Bundle artifact differs from original committed scientific evidence")
    hdf5 = confined_file(root, "snapshot/record.h5")
    if file_digest(hdf5) != snapshot.get("hdf5_sha256"):
        raise IntegrityError("Copied HDF5 differs from the committed snapshot")
    with h5py.File(hdf5, "r") as handle:
        if json_bytes(json.loads(handle["record_json"][()])) != json_bytes(record):
            raise IntegrityError("HDF5 and exported JSON records disagree")
    regenerated = _csv(_selected_rows(record, ensemble), manifest["table_recipe"]["columns"])
    if (root / "selected.csv").read_bytes() != regenerated:
        raise IntegrityError("Scientific table does not reproduce from reviewed records")
    if "figure_recipe" in manifest:
        _, figure = _reproduction_products(record, ensemble, manifest["table_recipe"]["columns"])
        if (root / "relative-energy.svg").read_bytes() != figure:
            raise IntegrityError("Scientific figure does not reproduce from reviewed records")
    if "sensitivity_recipe" in manifest:
        saved = read_json(root / "sampling-sensitivity.json")
        if saved != reviewed_ensemble_sensitivity(record, ensemble, saved["options"]):
            raise IntegrityError("Sampling sensitivity does not reproduce from reviewed records")
    return manifest
