"""Authentic frozen-water workflow through durable review and local export.

These are protocol/provenance tests. The supplied monomer geometries are not
benchmark reference structures and the assertions do not establish accuracy.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from topos.config import SystemConfig
from topos.constraints import intrafragment_drift
from topos.models import Molecule, RunRequest
from topos.publication import export_bundle, verify_bundle
from topos.review import (
    append_decision,
    create_ensemble_manifest,
    validate_scientific_candidate,
)
from topos.storage import RunStore, digest_json, file_digest
from topos.workflow import Workflow


@pytest.mark.integration
def test_real_frozen_water_workflow_retains_derivative_proof_and_exports_reviewed_result(tmp_path):
    executable = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if executable is None:
        pytest.skip("authentic xTB executable is not installed")
    molecule = Molecule(
        symbols=["O", "H", "H"] * 2,
        coordinates=[[0, 0, 0], [.9572, 0, 0], [-.23999, .9273, 0],
                     [2.9, .1, .2], [3.3, .9, .5], [3.4, -.6, -.2]],
        fragments=[[0, 1, 2], [3, 4, 5]],
    )
    request = RunRequest(
        molecule=molecule, engine="xtb", method="GFN2-xTB", purpose="optimize",
        budget_seconds=90, threads=1, n_candidates=1,
        constraints={
            "kind": "frozen-monomers", "profile_id": "mapping-2026",
            "reference_source": "test input geometry; monomer accuracy unverified",
            "reference_uncertainty_angstrom": None,
        },
    )
    workflow = Workflow(tmp_path / "runs", config=SystemConfig(executables={"xtb": executable}))
    record = workflow.run(request)
    assert record.status == "completed", record.model_dump(mode="json")
    assert len(record.candidates) == 1
    candidate = record.candidates[0]
    assert candidate.status == "eligible"
    assert candidate.gibbs_hartree is None
    assert candidate.metadata["stationary_point_classification"] == "constrained stationary point; no frequency Hessian"
    assert candidate.energy_hartree is not None
    assert intrafragment_drift(molecule.coordinates, candidate.molecule.coordinates, molecule.fragments) < 1e-12

    attempts = {a.attempt_id: a for a in record.attempts}
    aggregate = attempts[candidate.attempt_id]
    assert aggregate.metadata["result_kind"] == "derived-optimization"
    assert aggregate.command == ["topos-internal", "rigid-body-optimize"]
    diagnostics = aggregate.metadata["constrained_optimizer"]
    assert diagnostics["profile"]["profile_id"] == "mapping-2026"
    assert all(diagnostics["convergence_criteria"].values())
    assert diagnostics["free_rank"] == 6
    assert diagnostics["max_trajectory_intrafragment_drift_angstrom"] < 1e-12
    assert diagnostics["geometric_strain_warning"] is True
    assert diagnostics["max_frozen_gradient_hartree_per_bohr"] > 1e-4
    assert diagnostics["max_free_gradient_hartree_per_bohr"] <= 1e-5
    accepted_id = aggregate.metadata["accepted_derivative_attempt_id"]
    derivative_ids = aggregate.metadata["derivative_attempt_ids"]
    assert len(derivative_ids) > 1
    assert accepted_id in derivative_ids
    assert aggregate.parent_attempt_id == accepted_id
    accepted = attempts[accepted_id]
    assert accepted.metadata["output_molecule"] == candidate.molecule.model_dump(mode="json")
    assert accepted.metadata.get("result_kind") != "derived-optimization"
    assert accepted.engine_version == aggregate.engine_version

    run_dir = Path(record.metadata["run_dir"])
    for index, identifier in enumerate(derivative_ids):
        derivative = attempts[identifier]
        assert derivative.status == "completed"
        assert derivative.metadata["operation"] == "gradient"
        assert derivative.metadata["execution_kind"] == "real"
        assert derivative.metadata["convergence_scope"] == "electronic only"
        assert derivative.metadata["output_molecule"] == derivative.metadata["input_molecule"]
        assert derivative.command[0] == executable
        assert "--grad" in derivative.command
        assert derivative.method == "GFN2-xTB"
        assert derivative.converged is True
        assert derivative.metadata.get("result_kind") != "derived-optimization"
        if index:
            assert derivative.parent_attempt_id == derivative_ids[index - 1]
        raw_outputs = [a for a in derivative.artifacts if a.path.endswith(".stdout")]
        assert raw_outputs
        assert all(file_digest(run_dir / a.path) == a.sha256 for a in derivative.artifacts)
        assert "GEOMETRY OPTIMIZATION CONVERGED" not in (run_dir / raw_outputs[0].path).read_text()
    for quantity in accepted.quantities:
        assert quantity.attempt_id == accepted_id
        assert quantity.geometry_id is None
    for quantity in aggregate.quantities:
        assert quantity.attempt_id == aggregate.attempt_id
        assert quantity.geometry_id == candidate.candidate_id
    source_gradient = next(q for q in accepted.quantities if q.name == "cartesian_gradient")
    aggregate_gradient = next(q for q in aggregate.quantities if q.name == "cartesian_gradient")
    np.testing.assert_array_equal(source_gradient.value, aggregate_gradient.value)
    source_energy = next(q for q in accepted.quantities if q.name == "electronic_energy")
    assert source_energy.value == candidate.energy_hartree

    store = RunStore(run_dir)
    stored = store.load()
    validate_scientific_candidate(stored, candidate.model_dump(mode="json"))
    before_review = digest_json(stored)
    artifacts_before = {a.path: file_digest(run_dir / a.path) for attempt in record.attempts for a in attempt.artifacts}
    resumed = workflow.resume(run_dir)
    assert [a.attempt_id for a in resumed.attempts] == list(attempts)
    assert digest_json(store.load()) == before_review

    append_decision(
        run_dir, subject_id=candidate.candidate_id, action="accept", actor="integration-test-reviewer",
        reason="Accept this numerically converged constrained result for protocol verification; frozen monomer strain and absent Hessian remain explicit.",
    )
    ensemble = create_ensemble_manifest(run_dir, [candidate.candidate_id], actor="integration-test-reviewer")
    destination = tmp_path / "reviewed-bundle"
    exported = export_bundle(run_dir, destination, ensemble_sha256=ensemble["manifest_sha256"])
    assert verify_bundle(destination) == exported
    assert not exported["publication_ready"]
    assert exported["publication_status"] == "not-published"
    bundled = json.loads((destination / "run.json").read_text())
    assert bundled == stored
    assert digest_json(store.load()) == before_review
    assert {path: file_digest(run_dir / path) for path in artifacts_before} == artifacts_before
    with (destination / "selected.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["candidate_id"] == candidate.candidate_id
    assert rows[0]["attempt_id"] == aggregate.attempt_id
    assert rows[0]["method"] == "GFN2-xTB"
    assert float(rows[0]["electronic_energy_hartree"]) == candidate.energy_hartree
    assert rows[0]["gibbs_energy_hartree"] == ""
    methods = (destination / "methods.md").read_text()
    assert accepted_id in methods
    assert "r2SCAN-3c" not in methods
