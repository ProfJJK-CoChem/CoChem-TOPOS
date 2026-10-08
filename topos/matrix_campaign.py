"""Predeclared, source-bound acceptance of the 42 available TOPOS matrix rows.

Planning never executes an engine or certifies scientific results. Assessment
requires immutable, completed full-row RunStores for the declared conditions.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .actions.queue_budget import utc_timestamp
from .campaign_authority import base_authority_evidence, retained_registries
from .matrix_workflow import MatrixInputs, _available_inputs, execution_support_report
from .method_matrix import MATRIX_REVISION, HardwareSpec, plan_route, resolve_row
from .models import Contract, RunRequest, utc_now
from .release import source_inventory
from .storage import (
    IntegrityError,
    RunStore,
    atomic_json,
    confined_file,
    digest_json,
    file_digest,
    read_json,
    safe_relative,
)

PLAN_SCHEMA = "topos-reviewed-matrix-campaign-plan/0.2.0"
REPORT_SCHEMA = "topos-reviewed-matrix-campaign-report/0.2.0"
CONDITION = "reviewed_matrix_campaign"
SHA = r"[a-f0-9]{64}"
SCOPE = ("One completed, current-source, predeclared full-row calculation per available TOPOS row; "
         "specified cases only, without benchmark-accuracy, exhaustive-search, full chemical-domain or TORQ certification")



def _recipe(plan: dict[str, Any]) -> dict[str, Any]:
    # Device/capability selections are measured runtime decisions; all scientific
    # compiler fields, required inputs and reviewed revisions stay bound.
    return {"row": plan["row"], "reviewed_revision": plan["reviewed_revision"],
            "required_inputs": plan["required_inputs"],
            "steps": [{key: value for key, value in step.items() if key not in {"device", "selected_capability"}}
                      for step in plan["steps"]]}


def _inputs(request: RunRequest) -> MatrixInputs:
    inputs = MatrixInputs.model_validate(request.matrix_inputs)
    if request.per_geometry_budget_seconds is not None and request.matrix_row_id.startswith("T2-"):
        existing = inputs.scan_options.per_point_budget_seconds
        inputs.scan_options.per_point_budget_seconds = min(request.per_geometry_budget_seconds, existing) if existing else request.per_geometry_budget_seconds
    return inputs


def _compile(request: RunRequest, hardware: HardwareSpec) -> tuple[dict[str, Any], str]:
    support = execution_support_report()
    if request.purpose != "matrix" or request.matrix_revision != MATRIX_REVISION or not request.matrix_row_id:
        raise ValueError("Campaign cases require an explicit full-matrix request and pinned matrix revision")
    row = resolve_row(request.matrix_row_id, product=request.matrix_product)
    if row.owner != "TOPOS" or row.row_id not in support["compiled_complete_recipes"]:
        raise ValueError("Only the 42 available TOPOS full-row recipes can be campaign cases")
    inputs = _inputs(request)
    if inputs.source_resolution in {"orca-f12-reference-singlepoint-v1", "cfour-native-default-mass-corrected-geometry-v1"}:
        raise ValueError("An energy-only or geometry-only compatibility branch cannot complete a full matrix campaign case")
    if (hardware.cpu_threads, hardware.memory_mb, hardware.device) != (request.threads, request.memory_mb, request.device):
        raise ValueError("Predeclared hardware allocation differs from the exact request resources")
    plan = plan_route(row.row_id, hardware=hardware, capabilities=[], product=request.matrix_product,
                      available_inputs=_available_inputs(request, inputs), symbols=request.molecule.symbols,
                      charge=request.molecule.charge, multiplicity=request.molecule.multiplicity,
                      source_resolution=inputs.source_resolution)
    if plan.missing_inputs:
        raise ValueError("Predeclare all scientific inputs: " + ", ".join(plan.missing_inputs))
    if row.source_conflicts and inputs.source_resolution is None:
        raise ValueError("The archived row conflict requires its explicit reviewed scientific resolution")
    if plan.reviewed_revision and plan.reviewed_revision["definition"].get("native_capability_blocker"):
        raise ValueError(plan.reviewed_revision["definition"]["native_capability_blocker"])
    return _recipe(plan.model_dump(mode="json")), digest_json(inputs.model_dump(mode="json"))


SOURCE_TARGET_DOMAIN = "isolated gas-phase 5–10 atom van der Waals complexes; see row limits"
SOURCE_TARGET_ENVIRONMENT = {"phase": "gas"}


class CaseDomainDeclaration(Contract):
    """Reviewed declared applicability, not automatic chemical classification."""

    chemistry_domain: str = Field(min_length=1)
    physical_environment: Literal["isolated-gas-phase"]
    system_class: Literal["noncovalent-complex"]
    fragment_partition: list[list[int]] = Field(min_length=2)
    molecule_sha256: str = Field(pattern=SHA)
    request_environment_sha256: str = Field(pattern=SHA)
    source_row_limits: str
    reviewed_variant_differences: list[str]
    reviewer: str = Field(min_length=1)
    reviewed_at: str
    applicability_rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def timestamp(self):
        utc_timestamp(self.reviewed_at)
        if not self.reviewer.strip() or not self.applicability_rationale.strip():
            raise ValueError("Domain reviewer and applicability rationale must be nonblank")
        return self


def _source_domain_definition(request: RunRequest, recipe: dict[str, Any],
                              domain: CaseDomainDeclaration) -> None:
    row = recipe["row"]
    # Current source has this explicit scope. A changed/overridden source scope
    # requires a reviewed contract revision; never guess new atom thresholds.
    if row["chemical_domain"] != SOURCE_TARGET_DOMAIN or domain.chemistry_domain != row["chemical_domain"]:
        raise ValueError("Release case must bind the exact reviewed source-domain descriptor")
    molecule = request.molecule
    if not 5 <= len(molecule.symbols) <= 10:
        raise ValueError("Source-domain release cases require 5–10 explicitly mapped atoms")
    if molecule.environment != SOURCE_TARGET_ENVIRONMENT:
        raise ValueError("Release case typed environment must explicitly declare isolated gas phase")
    if (domain.molecule_sha256 != digest_json(molecule.model_dump(mode="json"))
            or domain.request_environment_sha256 != digest_json(molecule.environment)):
        raise ValueError("Domain declaration differs from its exact typed molecular/environment identity")
    if len(molecule.fragments) < 2 or domain.fragment_partition != molecule.fragments:
        raise ValueError("Release case needs the exact indexed noncovalent fragment partition")
    owner = {atom: number for number, fragment in enumerate(molecule.fragments) for atom in fragment}
    if any(owner[bond.atom1] != owner[bond.atom2] for bond in molecule.bonds):
        raise ValueError("A declared interfragment bond is incompatible with the noncovalent target declaration")
    revision = recipe.get("reviewed_revision")
    differences = revision["definition"].get("differences", []) if revision else []
    if domain.source_row_limits != row["limitations"] or domain.reviewed_variant_differences != differences:
        raise ValueError("Review must preserve source-specific limits and exact reviewed scientific differences")


class CampaignCase(Contract):
    row_id: str
    request: RunRequest
    hardware: HardwareSpec
    request_sha256: str = Field(pattern=SHA)
    molecule_sha256: str = Field(pattern=SHA)
    resources_sha256: str = Field(pattern=SHA)
    inputs_sha256: str = Field(pattern=SHA)
    recipe: dict[str, Any]
    recipe_sha256: str = Field(pattern=SHA)
    coverage_scope: Literal["diagnostic-control", "source-domain-release"] = "diagnostic-control"
    domain_declaration: CaseDomainDeclaration | None = None
    domain_declaration_sha256: str | None = Field(default=None, pattern=SHA)

    @model_validator(mode="after")
    def bound_definition(self):
        if (digest_json(self.request.model_dump(mode="json")) != self.request_sha256
                or digest_json(self.request.molecule.model_dump(mode="json")) != self.molecule_sha256
                or digest_json(self.request.resources.model_dump(mode="json")) != self.resources_sha256
                or digest_json(self.recipe) != self.recipe_sha256
                or self.recipe.get("row", {}).get("row_id") != self.row_id):
            raise ValueError("Campaign case hashes do not bind its exact typed scientific definition")
        if self.coverage_scope == "diagnostic-control":
            if self.domain_declaration is not None or self.domain_declaration_sha256 is not None:
                raise ValueError("Diagnostic controls cannot attach source-domain release claims")
        else:
            if self.domain_declaration is None:
                raise ValueError("Release coverage requires a predeclared source-domain review")
            if digest_json(self.domain_declaration.model_dump(mode="json")) != self.domain_declaration_sha256:
                raise ValueError("Domain declaration checksum differs from its reviewed scope")
            _source_domain_definition(self.request, self.recipe, self.domain_declaration)
        return self


class CampaignPlan(Contract):
    schema_version: str = PLAN_SCHEMA
    condition: str = CONDITION
    declared_at: str
    source_sha256: dict[str, str]
    available_rows: list[str]
    unavailable_by_design: list[dict[str, Any]]
    torq_owned_rows_excluded: int
    cases: list[CampaignCase] = Field(default_factory=list)
    scope: str = SCOPE

    @model_validator(mode="after")
    def unique_declarations(self):
        utc_timestamp(self.declared_at)
        rows = [case.row_id for case in self.cases]
        if len(rows) != len(set(rows)) or not set(rows) <= set(self.available_rows):
            raise ValueError("Declare at most one exact case for each available TOPOS row")
        for case in self.cases:
            if (case.domain_declaration is not None
                    and utc_timestamp(case.domain_declaration.reviewed_at) > utc_timestamp(self.declared_at)):
                raise ValueError("Domain review must precede the frozen case declaration")
        if self.schema_version != PLAN_SCHEMA or self.condition != CONDITION or self.scope != SCOPE:
            raise ValueError("Unknown matrix campaign plan contract")
        return self


def create_plan(source_root: Path, definitions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Freeze explicit cases and code identity; omitted rows remain pending."""
    support = execution_support_report()
    cases = []
    for definition in definitions or []:
        raw_request = definition.get("request", definition)
        request = RunRequest.model_validate(raw_request)
        hardware_data = definition.get("hardware") if "request" in definition else None
        if hardware_data is None:
            if request.device != "cpu":
                raise ValueError("GPU campaign cases require an explicit named GPU hardware declaration")
            hardware_data = dict(cpu_threads=request.threads, memory_mb=request.memory_mb, device="cpu",
                                 threads_per_worker=request.threads, memory_per_worker_mb=request.memory_mb,
                                 fingerprint="predeclared-campaign-allocation; runtime hardware verified separately")
        hardware = HardwareSpec.model_validate(hardware_data)
        recipe, inputs_digest = _compile(request, hardware)
        coverage_scope = definition.get("coverage_scope", "diagnostic-control") if "request" in definition else "diagnostic-control"
        domain_data = definition.get("domain_declaration") if "request" in definition else None
        domain = CaseDomainDeclaration.model_validate(domain_data) if domain_data is not None else None
        cases.append(CampaignCase(row_id=recipe["row"]["row_id"], request=request, hardware=hardware,
                                  request_sha256=digest_json(request.model_dump(mode="json")),
                                  molecule_sha256=digest_json(request.molecule.model_dump(mode="json")),
                                  resources_sha256=digest_json(request.resources.model_dump(mode="json")),
                                  inputs_sha256=inputs_digest, recipe=recipe, recipe_sha256=digest_json(recipe),
                                  coverage_scope=coverage_scope, domain_declaration=domain,
                                  domain_declaration_sha256=digest_json(domain.model_dump(mode="json")) if domain else None))
    return CampaignPlan(declared_at=utc_now(), source_sha256=source_inventory(source_root),
                        available_rows=support["compiled_complete_recipes"],
                        unavailable_by_design=support["unavailable_by_design"],
                        torq_owned_rows_excluded=support["torq_owned_rows"], cases=cases).model_dump(mode="json")


def _load_plan(path: Path, source_root: Path) -> CampaignPlan:
    if path.is_symlink():
        raise IntegrityError("Matrix campaign plan must be a regular retained file")
    raw = read_json(path)
    plan = CampaignPlan.model_validate(raw)
    support = execution_support_report()
    if (raw != plan.model_dump(mode="json") or plan.source_sha256 != source_inventory(source_root)
            or plan.available_rows != support["compiled_complete_recipes"]
            or plan.unavailable_by_design != support["unavailable_by_design"]
            or plan.torq_owned_rows_excluded != support["torq_owned_rows"]):
        raise IntegrityError("Campaign plan differs from the current source, exact row inventory or canonical declaration")
    for case in plan.cases:
        recipe, inputs_digest = _compile(case.request, case.hardware)
        if recipe != case.recipe or inputs_digest != case.inputs_sha256:
            raise IntegrityError("Campaign case differs from the current reviewed row compiler or typed protocol")
    return plan


def _native_evidence(record: dict[str, Any], store: RunStore) -> list[dict[str, Any]]:
    proofs = []
    snapshot = store.snapshot_path() / "artifacts"
    for attempt in record["attempts"]:
        if attempt["status"] in {"queued", "running"}:
            raise IntegrityError("Completed matrix record still contains an executing attempt")
        if attempt["status"] != "completed" or not attempt["command"] or attempt["command"][0] == "topos-internal":
            continue
        metadata = attempt["metadata"]
        if (metadata.get("execution_kind") != "real" or attempt["converged"] is not True
                or attempt["validation_status"] != "validated-for-protocol" or not attempt["engine_version"]
                or not Path(attempt["command"][0]).is_absolute() or not attempt["artifacts"]):
            raise IntegrityError("Native attempt lacks actual converged execution, version, command or artifacts")
        artifacts = attempt["artifacts"]
        raw_files = [a for a in artifacts if a["size_bytes"] > 0 and "version" not in Path(a["path"]).name
                     and Path(a["path"]).suffix in {".stdout", ".stderr", ".out"}]
        engine = attempt["engine"]
        identity = metadata.get("crest_sha256") if engine == "crest" else metadata.get("executable_sha256")
        training = metadata.get("stage_result") if metadata.get("role") == "experimental-fine-tuning" else None
        if isinstance(training, dict):
            if (digest_json(training) != metadata.get("stage_result_sha256")
                    or training.get("schema_version") != "topos-mace-finetuning/1"
                    or training.get("status") != "completed" or not training.get("checkpoint")
                    or training.get("heldout_execution_kind") != "real" or not training.get("heldout_errors")):
                raise IntegrityError("GPU training requires its completed actual fitting and independent held-out receipt")
            source_fit = training.get("fitted_checkpoint_source", training)
            if (source_fit.get("training_performed") is not True
                    or source_fit.get("process", {}).get("status") != "completed"
                    or source_fit.get("process", {}).get("returncode") != 0):
                raise IntegrityError("A checkpoint-only training stub cannot certify a native GPU fit")
            identity = digest_json(training["checkpoint"])
        elif engine == "psi4":
            from .external_engines import ExternalProtocol, parse_psi4_result

            files = [a for a in artifacts if Path(a["path"]).name == "native-result.json"]
            if len(files) != 1 or not re.fullmatch(SHA, str(identity or "")) or not raw_files:
                raise IntegrityError("Psi4 SAPT needs its actual native decomposition and raw output")
            parse_psi4_result(confined_file(snapshot, files[0]["path"]).read_text(),
                              ExternalProtocol.model_validate(metadata["requested_protocol"]))
        elif engine in {"mace", "aimnet2"}:
            results = [a for a in artifacts if Path(a["path"]).name == "ml-result.json"]
            requests = [a for a in artifacts if Path(a["path"]).name == "ml-request.json"]
            if len(results) != 1 or len(requests) != 1:
                raise IntegrityError("ML inference needs its actual request/result and model-bound worker receipts")
            request_file = confined_file(snapshot, requests[0]["path"])
            request = read_json(request_file)
            result = read_json(confined_file(snapshot, results[0]["path"]))
            identity = digest_json(request["manifest"])
            if (result.get("request_sha256") != file_digest(request_file)
                    or result.get("manifest_sha256") != identity or not result.get("frames")):
                raise IntegrityError("ML worker result differs from its immutable model and request")
        else:
            if engine == "orca" and "server_summary" in metadata:
                # Native binary identity and model/callback completion are
                # separate proofs; neither may replace or bypass the other.
                server = metadata["server_summary"]
                manifest = metadata.get("manifest_sha256")
                if (not isinstance(server, dict) or not re.fullmatch(SHA, str(manifest or ""))
                        or server.get("manifest_sha256") != manifest
                        or type(server.get("successful_requests")) is not int or server["successful_requests"] < 1
                        or type(server.get("requests")) is not int
                        or server["successful_requests"] != server["requests"]):
                    raise IntegrityError("Native ExtOpt requires a model-bound successful callback session")
            if not re.fullmatch(SHA, str(identity or "")) or not raw_files:
                raise IntegrityError("Native engine requires a hashed executable and nonempty calculation output")
            raw = "\n".join(confined_file(snapshot, a["path"]).read_text(errors="replace") for a in raw_files)
            markers = {"xtb": "normal termination of xtb", "orca": "ORCA TERMINATED NORMALLY",
                       "crest": "CREST terminated normally.", "cfour": "SCF has converged."}
            if engine not in markers or markers[engine] not in raw:
                raise IntegrityError("Native calculation output does not establish supported engine completion")
        proofs.append({"attempt_id": attempt["attempt_id"], "engine": engine,
                       "engine_version": attempt["engine_version"], "identity_sha256": identity,
                       "raw_artifacts": artifacts})
    if not proofs:
        raise IntegrityError("Compiled recipes and derived arithmetic without actual native attempts cannot pass")
    return proofs


def _predeclaration_evidence(record: dict[str, Any], store: RunStore, declared_at: str) -> list[str]:
    """Verify retained history; late imports cannot hide pre-plan observations."""
    declared = utc_timestamp(declared_at)

    def verify_observation(observation):
        if (observation["run_id"] != record["run_id"]
                or utc_timestamp(observation["created_at"]) < declared
                or utc_timestamp(observation["updated_at"]) < declared):
            raise IntegrityError("Run history predates the predeclared campaign; post-hoc case selection does not pass")
        for attempt in observation["attempts"]:
            if (attempt["command"] and attempt["command"][0] != "topos-internal"
                    and attempt["metadata"].get("execution_kind") == "real"):
                if not attempt.get("started_at") or utc_timestamp(attempt["started_at"]) < declared:
                    raise IntegrityError("Native attempt began before predeclaration or lacks its actual launch timestamp")

    verify_observation(record)
    history = []
    for directory in sorted(store.snapshots.iterdir()):
        if directory.name.startswith(".pending-"):
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise IntegrityError("Unexpected retained RunStore history member")
        manifest = read_json(confined_file(directory, "manifest.json"))
        historical, _ = store._read_snapshot({"snapshot_id": directory.name, "manifest_sha256": digest_json(manifest)})
        verify_observation(historical)
        history.append(directory.name)
    if not history:
        raise IntegrityError("Campaign evidence lacks its immutable RunStore history")
    return history


def _assess_run(case: CampaignCase, store: RunStore, plan: CampaignPlan, bundle_root: Path,
                registries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    manifest = store.verify()
    record = store.load()
    metadata = record["metadata"]
    if record["status"] != "completed" or metadata.get("matrix_execution", {}).get("full_row_completed") is not True:
        raise IntegrityError("A complete full-row RunStore is required; partial and compatibility branches do not pass")
    history = _predeclaration_evidence(record, store, plan.declared_at)
    if (digest_json(record["request"]) != case.request_sha256
            or metadata.get("request_sha256") != case.request_sha256
            or metadata.get("input_sha256") != case.molecule_sha256):
        raise IntegrityError("Run request, molecule/state or resource identity differs from its declared case")
    expected_sources = {name: value for name, value in plan.source_sha256.items() if name.startswith("topos/") and name.endswith(".py")}
    if metadata.get("software", {}).get("source_files") != expected_sources:
        raise IntegrityError("Run did not execute the complete current TOPOS source identity")
    state = metadata["matrix_execution"]
    actual_plan = metadata.get("matrix_plan", {})
    if (state.get("row_id") != case.row_id or state.get("source_sha256") != case.recipe["row"]["source"]["sha256"]
            or state.get("inputs_sha256") != case.inputs_sha256 or _recipe(actual_plan) != case.recipe):
        raise IntegrityError("Run matrix row, reviewed scientific variant or compiler protocol receipt differs")
    hardware = actual_plan["hardware"]
    for field in ("cpu_threads", "memory_mb", "device", "gpu_model", "gpu_memory_mb"):
        if hardware[field] != getattr(case.hardware, field):
            raise IntegrityError("Actual matrix hardware differs from the predeclared resource/device allocation")
    native = _native_evidence(record, store)
    try:
        authority = base_authority_evidence(record, store, registries)
        release_eligible, reason = True, None
    except (ValueError, KeyError, TypeError) as exc:
        authority, release_eligible, reason = None, False, str(exc)
    if case.coverage_scope != "source-domain-release":
        release_eligible = False
        domain_reason = "Diagnostic control is outside the predeclared source-domain release coverage"
        reason = domain_reason + ("; " + reason if reason else "")
    return {"run_path": store.run_dir.relative_to(bundle_root).as_posix(), "run_id": record["run_id"], "snapshot_id": manifest["snapshot_id"],
            "record_sha256": manifest["record_sha256"], "verified_snapshot_history": history,
            "native_attempts": native, "release_eligible": release_eligible,
            "coverage_scope": case.coverage_scope,
            "domain_declaration_sha256": case.domain_declaration_sha256,
            "source_domain_declaration_verified": case.coverage_scope == "source-domain-release",
            "base_authority": authority, "release_blocker": reason}


def assess(plan_path: Path, run_dirs: list[Path], source_root: Path,
           base_registry_paths: list[Path] | None = None) -> dict[str, Any]:
    """Read immutable scientific evidence; never launch, repair or fabricate runs."""
    if plan_path.is_symlink():
        raise IntegrityError("Matrix campaign plan must be a regular retained file")
    plan_path = plan_path.resolve()
    bundle_root = plan_path.parent
    plan = _load_plan(plan_path, source_root)
    registries, registry_receipts = retained_registries(bundle_root, base_registry_paths or [])
    cases = {case.row_id: case for case in plan.cases}
    candidates: dict[str, list[dict[str, Any]]] = {row: [] for row in plan.available_rows}
    invalid = []
    resolved_runs = []
    for path in run_dirs:
        path = path.resolve()
        if path == bundle_root or not path.is_relative_to(bundle_root):
            raise IntegrityError("Candidate RunStores must remain strictly inside the campaign plan bundle")
        resolved_runs.append(safe_relative(path.relative_to(bundle_root).as_posix()))
    if len(resolved_runs) != len(set(resolved_runs)):
        raise IntegrityError("Duplicate candidate RunStore directories do not add campaign coverage")
    for directory in resolved_runs:
        folder = bundle_root / directory
        try:
            if not folder.is_dir() or not (folder / "CURRENT.json").is_file() or not (folder / "snapshots").is_dir():
                raise IntegrityError("Candidate must be an existing committed immutable RunStore")
            store = RunStore(folder)
            record = store.load()
            row_id = record.get("metadata", {}).get("matrix_execution", {}).get("row_id")
            if row_id not in cases:
                raise IntegrityError("Candidate has no matching predeclared available TOPOS full-row case")
            try:
                evidence = _assess_run(cases[row_id], store, plan, bundle_root, registries)
                candidates[row_id].append({"status": "passed", "evidence": evidence})
            except (ValueError, KeyError, TypeError) as exc:
                candidates[row_id].append({"status": "failed", "run_path": directory, "reason": str(exc)})
        except (ValueError, OSError, KeyError, TypeError) as exc:
            invalid.append({"run_path": directory, "reason": str(exc)})
    rows = []
    for row in plan.available_rows:
        results = candidates[row]
        status = "passed" if any(item["status"] == "passed" for item in results) else "failed" if results else "pending"
        release_eligible = any(item["status"] == "passed" and item["evidence"]["release_eligible"] for item in results)
        rows.append({"row_id": row, "status": status, "release_eligible": release_eligible,
                     "reason": "No predeclared scientific case" if row not in cases else "No matching completed actual RunStore" if not results else None,
                     "case_request_sha256": cases[row].request_sha256 if row in cases else None, "results": results})
    counts = {status: sum(row["status"] == status for row in rows) for status in ("passed", "failed", "pending")}
    release_count = sum(row["release_eligible"] for row in rows)
    release_eligible = release_count == len(plan.available_rows) and not invalid
    return {"schema_version": REPORT_SCHEMA, "condition": CONDITION,
            "status": "passed" if release_eligible else "pending" if counts["passed"] and not counts["failed"] and not invalid else "blocked",
            "release_eligible": release_eligible, "release_eligible_rows": release_count,
            "plan_path": plan_path.name, "plan_file_sha256": file_digest(plan_path), "plan_sha256": digest_json(plan.model_dump(mode="json")),
            "source_sha256": plan.source_sha256, "candidate_runs": resolved_runs, "rows": rows, "counts": counts,
            "base_registries": registry_receipts,
            "unavailable_by_design": plan.unavailable_by_design, "torq_owned_rows_excluded": plan.torq_owned_rows_excluded,
            "invalid_candidates": invalid, "scope": SCOPE}


def verify_report(report_path: Path, source_root: Path) -> dict[str, Any]:
    """Recompute every pass from the retained plan and actual immutable RunStores."""
    if report_path.is_symlink():
        raise IntegrityError("Campaign report must be a regular retained file")
    report = read_json(report_path)
    if report.get("schema_version") != REPORT_SCHEMA or report.get("condition") != CONDITION:
        raise IntegrityError("Unknown matrix campaign report contract")
    try:
        bundle_root = report_path.resolve().parent
        plan_path = confined_file(bundle_root, report["plan_path"])
        candidates = []
        for relative in report["candidate_runs"]:
            directory = bundle_root / safe_relative(relative)
            confined_file(bundle_root, relative + "/CURRENT.json")
            candidates.append(directory)
        registry_paths = [confined_file(bundle_root, item["path"]) for item in report["base_registries"]]
        expected = assess(plan_path, candidates, source_root, registry_paths)
    except (KeyError, TypeError) as exc:
        raise IntegrityError("Campaign report lacks its retained plan or candidate RunStore identity") from exc
    if report != expected:
        raise IntegrityError("Campaign report differs from its frozen plan or reverified actual RunStores")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--source-root", type=Path, default=Path.cwd())
    plan_parser.add_argument("--cases", type=Path, help="JSON list of exact requests or request/hardware declarations")
    plan_parser.add_argument("--output", type=Path, required=True)
    assess_parser = commands.add_parser("assess")
    assess_parser.add_argument("--source-root", type=Path, default=Path.cwd())
    assess_parser.add_argument("--plan", type=Path, required=True)
    assess_parser.add_argument("--run", type=Path, action="append", default=[])
    assess_parser.add_argument("--base-registry", type=Path, action="append", default=[],
                               help="Exact audited registry snapshot retained inside the portable campaign bundle; repeat for multiple workers")
    assess_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.error("Output already exists; retain the original and choose a fresh path")
    if args.command == "plan":
        import json

        definitions = json.loads(args.cases.read_text()) if args.cases else []
        if not isinstance(definitions, list):
            parser.error("Campaign cases must be a JSON list")
        report = create_plan(args.source_root, definitions)
    else:
        if args.output.resolve().parent != args.plan.resolve().parent:
            parser.error("Keep the campaign report beside its retained plan inside the portable campaign bundle")
        report = assess(args.plan, args.run, args.source_root, args.base_registry)
    atomic_json(args.output, report)
    print(str(args.output.resolve()))
    return 0 if args.command == "plan" or report["status"] == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
