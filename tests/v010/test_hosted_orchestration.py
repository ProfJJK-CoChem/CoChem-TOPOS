"""Hosted evidence producer graph/source contracts; never launch native chemistry."""
from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PRODUCERS = {
    "baseline": ("accept_orca_topos.py", "topos-orca-evidence"),
    "extended": ("accept_orca_extended.py", "topos-orca-extended"),
    "licensed-pytest": ("accept_orca_pytest.py", "topos-orca-evidence"),
}


def workflow(name):
    # BaseLoader follows the YAML graph without YAML1.1 converting the key
    # "on" into a boolean. It constructs only strings, sequences and mappings.
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def scheduled(expression, outcomes, *, cancelled=False):
    """Evaluate this workflow's small status-condition subset as GitHub does."""
    expression = expression.removeprefix("${{").removesuffix("}}").strip()
    terms = expression.split("&&")
    values = []
    for term in terms:
        term = term.strip()
        if term == "!cancelled()":
            values.append(not cancelled)
        elif match := re.fullmatch(r"steps\.([\w-]+)\.outcome\s*==\s*'success'", term):
            values.append(outcomes.get(match[1]) == "success")
        else:
            raise AssertionError(f"Unexpected evidence scheduling expression: {term}")
    return all(values)


def producer_graph_errors(document):
    """Check evidence completeness from the parsed jobs and command arguments."""
    errors = []
    jobs = document["jobs"]
    locations = {}
    for job_name, job in jobs.items():
        for position, step in enumerate(job.get("steps", [])):
            for producer, (script, output) in PRODUCERS.items():
                if re.search(rf"(?:^|\s)scripts/{re.escape(script)}(?:\s|$)", step.get("run", "")):
                    locations.setdefault(producer, []).append((job_name, position, step, output))
    for producer in PRODUCERS:
        if len(locations.get(producer, [])) != 1:
            errors.append(f"{producer}: expected exactly one actual evidence producer")
    if errors:
        return errors
    if {items[0][0] for items in locations.values()} != {"scientific-acceptance"}:
        errors.append("evidence producers must share the scientific acceptance job")
        return errors
    job = jobs["scientific-acceptance"]
    steps = job["steps"]
    ecosystem = [(i, step) for i, step in enumerate(steps) if step.get("id") == "ecosystem"]
    if len(ecosystem) != 1 or "scripts/setup_ecosystem.py" not in ecosystem[0][1].get("run", ""):
        errors.append("exactly one real ecosystem audit must precede native producers")
        return errors
    for producer, items in locations.items():
        _, index, step, output = items[0]
        if step.get("id") != producer or index <= ecosystem[0][0]:
            errors.append(f"{producer}: identity/order is not bound to the audited ecosystem")
        command = step["run"].replace("\\\n", " ")
        if not re.search(rf'--output\s+"\$RUNNER_TEMP/{output}"(?:\s|$)', command):
            errors.append(f"{producer}: output differs from release consumer location")
        if not re.search(r'--registry\s+"\$COCHEM_CONFIG"(?:\s|$)', command):
            errors.append(f"{producer}: native registry is not the audited shared authority")
        expression = step.get("if", "")
        for baseline_outcome in ("success", "failure"):
            if not scheduled(expression, {"ecosystem": "success", "baseline": baseline_outcome}):
                errors.append(f"{producer}: baseline failure suppresses independent evidence")
        if scheduled(expression, {"ecosystem": "failure", "baseline": "success"}):
            errors.append(f"{producer}: unaudited setup permits native chemistry")
        if scheduled(expression, {"ecosystem": "success"}, cancelled=True):
            errors.append(f"{producer}: cancellation permits a new native producer")
    if any(name in job.get("env", {}) for name in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_REPOSITORY")):
        errors.append("hosted execution identity must be the actual controller identity")
    return errors


def test_all_required_native_receipt_producers_share_one_audited_job():
    assert producer_graph_errors(workflow("topos_orca_acceptance.yml")) == []


@pytest.mark.parametrize("producer", list(PRODUCERS))
def test_omitted_native_producer_is_not_a_complete_hosted_evidence_graph(producer):
    document = copy.deepcopy(workflow("topos_orca_acceptance.yml"))
    steps = document["jobs"]["scientific-acceptance"]["steps"]
    script = PRODUCERS[producer][0]
    steps[:] = [step for step in steps if f"scripts/{script}" not in step.get("run", "")]
    assert any(producer in error for error in producer_graph_errors(document))


@pytest.mark.parametrize("producer", list(PRODUCERS))
@pytest.mark.parametrize("outcome,cancelled,expected", [
    ("success", False, True), ("failure", False, False), ("success", True, False),
])
def test_chemistry_requires_actual_ecosystem_success_and_observes_cancellation(producer, outcome, cancelled, expected):
    job = workflow("topos_orca_acceptance.yml")["jobs"]["scientific-acceptance"]
    step = next(step for step in job["steps"] if step.get("id") == producer)
    # Failure of an earlier scientific case should retain later independent
    # receipts. The all-cases release gate still rejects that scientific miss.
    assert scheduled(step["if"], {"ecosystem": outcome, "baseline": "failure"}, cancelled=cancelled) is expected


def test_private_controller_checks_out_explicit_topos_commit_before_provisioning():
    document = workflow("topos_orca_acceptance.yml")
    for event in ("workflow_dispatch", "workflow_call"):
        source_input = document["on"][event]["inputs"]["topos_commit"]
        assert source_input["type"] == "string" and source_input["required"] == "true"
        assert "default" not in source_input
    job = document["jobs"]["scientific-acceptance"]
    assert job["env"]["TOPOS_COMMIT"] == "${{ inputs.topos_commit }}"
    assert "github.event.repository.private" in job["if"]
    assert "github.event.repository.default_branch" in job["if"]
    steps = job["steps"]
    checkouts = [(index, step) for index, step in enumerate(steps)
                 if step.get("uses", "").startswith("actions/checkout@")]
    topos = [(index, step) for index, step in checkouts
             if step.get("with", {}).get("repository") == "ProfJJK-CoChem/CoChem-TOPOS"]
    assert len(topos) == 1
    index, checkout = topos[0]
    assert checkout["with"]["ref"] == "${{ env.TOPOS_COMMIT }}"
    assert checkout["with"]["persist-credentials"] == "false"
    # An implicit checkout in a reusable workflow would select the private
    # caller's unrelated sources and cannot count as TOPOS evidence.
    assert all("repository" in step.get("with", {}) for _, step in checkouts)
    validation = [step for step in steps[:index] if "TOPOS_COMMIT" in step.get("run", "")]
    assert any("^[0-9a-f]{40}$" in step["run"] for step in validation)
    verified = [i for i, step in enumerate(steps) if "rev-parse HEAD" in step.get("run", "")
                and "TOPOS_COMMIT" in step["run"]]
    base_index = next(i for i, step in checkouts if step["with"]["repository"] == "ProfJJK-CoChem/CoChem-BASE")
    assert len(verified) == 1 and index < verified[0] < base_index


def test_licensed_manual_configuration_guard_precedes_any_package_or_engine_step():
    job = workflow("topos_orca_acceptance.yml")["jobs"]["scientific-acceptance"]
    guard = job["steps"][0]
    # This step must be an actual shell guard, not descriptive job metadata.
    assert guard.get("run") and guard.get("shell") == "bash"
    environment = guard["env"]
    assert environment["EXECUTION_EVENT"] == "${{ github.event_name }}"
    assert environment["REPOSITORY_PRIVATE"] == "${{ github.event.repository.private }}"
    assert job["env"]["ORCA_CLOUD_LICENSE_CONFIRMED"] == "${{ vars.ORCA_CLOUD_LICENSE_CONFIRMED }}"
    command = guard["run"]
    assert 'test "$EXECUTION_EVENT" != workflow_dispatch' in command
    assert 'test "$REPOSITORY_PRIVATE" = true' in command
    assert 'test "$ORCA_CLOUD_LICENSE_CONFIRMED" = true' in command
    assert 'test -z "$ASSET_CREDENTIAL"' in command
    assert "exit 1" in command


def test_same_attempt_artifact_preserves_both_output_trees_for_release_consumer():
    hosted = workflow("topos_orca_acceptance.yml")["jobs"]["scientific-acceptance"]
    uploads = [step for step in hosted["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(uploads) == 1
    upload = uploads[0]
    assert upload["if"] == "always()"
    assert upload["with"]["name"] == "topos-orca-acceptance-${{ github.run_id }}-${{ github.run_attempt }}"
    retained = upload["with"]["path"].splitlines()
    assert "${{ runner.temp }}/topos-orca-evidence/" in retained
    assert "${{ runner.temp }}/topos-orca-extended/" in retained
    release = workflow("topos_release.yml")
    repository = release["on"]["workflow_dispatch"]["inputs"]["hosted_acceptance_repository"]
    assert repository["type"] == "string" and "options" not in repository
    downloads = [step for step in release["jobs"]["candidate"]["steps"]
                 if step.get("uses", "").startswith("actions/download-artifact@")
                 and step.get("with", {}).get("run-id") == "${{ inputs.hosted_acceptance_run_id }}"]
    assert len(downloads) == 1
    download = downloads[0]["with"]
    assert download["repository"] == "${{ inputs.hosted_acceptance_repository }}"
    assert download["name"] == "${{ format('topos-orca-acceptance-{0}-{1}', inputs.hosted_acceptance_run_id, inputs.hosted_acceptance_run_attempt) }}"
    assert "github-token" in download


def reusable_call_errors(caller, callee):
    """Validate required reusable inputs from actual caller/callee YAML graphs."""
    required = {name for name, value in callee["on"]["workflow_call"]["inputs"].items()
                if value.get("required") == "true" and "default" not in value}
    calls = [job for job in caller["jobs"].values()
             if job.get("uses") == "./.github/workflows/topos_orca_acceptance.yml"]
    assert calls, "Compatibility entry point lost its reusable acceptance job"
    return sorted(required - set(job.get("with", {})) for job in calls)


def test_compatibility_entrypoint_forwards_every_required_exact_source_input():
    caller = workflow("orca_hosted.yml")
    callee = workflow("topos_orca_acceptance.yml")
    assert reusable_call_errors(caller, callee) == [set()]
    declared = caller["on"]["workflow_dispatch"]["inputs"]["topos_commit"]
    assert declared["type"] == "string" and declared["required"] == "true"
    assert "default" not in declared
    job = next(job for job in caller["jobs"].values()
               if job.get("uses") == "./.github/workflows/topos_orca_acceptance.yml")
    assert job["with"]["topos_commit"] == "${{ inputs.topos_commit }}"


def test_missing_required_reusable_source_input_is_detected_before_execution():
    caller = copy.deepcopy(workflow("orca_hosted.yml"))
    job = next(job for job in caller["jobs"].values()
               if job.get("uses") == "./.github/workflows/topos_orca_acceptance.yml")
    job.get("with", {}).pop("topos_commit", None)
    assert reusable_call_errors(caller, workflow("topos_orca_acceptance.yml")) == [{"topos_commit"}]
