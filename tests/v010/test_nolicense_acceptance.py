"""Acceptance evidence from genuine xTB/CREST, without licensed ORCA.

The cancellation hook changes only when an actual run is interrupted. Scientific
energies, structures, execution logs, and resumable attempts come from the engines.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from threading import Event

import pytest

from topos.chemistry import molecular_graph, validate_chemistry
from topos.config import SystemConfig
from topos.models import Molecule, RunRequest
from topos.storage import RunStore, file_digest
from topos.workflow import Workflow


def ethanol_molecule() -> Molecule:
    """An explicitly constructed starting geometry, not an experimental structure."""
    return Molecule(
        name="ethanol constructed integration-test seed",
        symbols=["C", "C", "O", "H", "H", "H", "H", "H", "H"],
        coordinates=[
            [-0.748, 0.0, 0.0], [0.748, 0.0, 0.0], [1.292, 1.260, 0.0],
            [-1.131, 0.514, 0.890], [-1.131, 0.514, -0.890], [-1.131, -1.028, 0.0],
            [1.131, -0.514, 0.890], [1.131, -0.514, -0.890], [2.251, 1.260, 0.0],
        ],
        bonds=[{"atom1": a, "atom2": b} for a, b in
               [(0, 1), (1, 2), (0, 3), (0, 4), (0, 5), (1, 6), (1, 7), (2, 8)]],
    )


def _native(name: str) -> str:
    executable = shutil.which(os.environ.get(f"TOPOS_{name.upper()}_EXECUTABLE", name))
    if executable is None:
        reason = f"authentic {name} executable required; no chemical result simulated"
        if os.environ.get("TOPOS_REQUIRE_REAL_ENGINES") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    return executable


def _request(**changes) -> RunRequest:
    settings = {
        "molecule": ethanol_molecule(),
        "engine": "xtb",
        "method": "GFN2-xTB",
        "profile_id": "xtb-vtight-v1",
        "budget_seconds": 90,
        "n_candidates": 3,
        "seed": 741,
        "perturbation_angstrom": 0.04,
    }
    settings.update(changes)
    return RunRequest(**settings)


def _artifacts(run_dir: Path, attempt) -> dict[str, str]:
    assert attempt.artifacts
    digests = {artifact.path: artifact.sha256 for artifact in attempt.artifacts}
    assert all(file_digest(run_dir / path) == digest for path, digest in digests.items())
    return digests


@pytest.mark.integration
def test_real_flexible_ethanol_jiggle_quench_retains_chemistry_and_logs(tmp_path):
    request = _request()
    record = Workflow(tmp_path, config=SystemConfig(executables={"xtb": _native("xtb")})).run(
        request
    )
    assert record.status == "completed", record.metadata.get("termination_reason")
    assert len(record.attempts) == request.n_candidates
    assert record.metadata["search_summary"]["completed_samples"] == request.n_candidates
    assert not record.metadata["search_summary"]["exhaustive"]
    assert all(candidate.status in {"eligible", "duplicate"} for candidate in record.candidates)
    input_edges = set(map(frozenset, molecular_graph(request.molecule).edges))
    run_dir = tmp_path / record.run_id
    for candidate in record.candidates:
        assert candidate.metadata["calculation_completed"]
        assert candidate.energy_hartree is not None and candidate.energy_hartree < -10
        assert candidate.gibbs_hartree is None
        assert candidate.molecule.atom_ids == request.molecule.atom_ids
        assert validate_chemistry(candidate.molecule)["status"] == "valid"
        inferred = candidate.molecule.model_copy(update={"bonds": []})
        assert set(map(frozenset, molecular_graph(inferred).edges)) == input_edges
    for attempt in record.attempts:
        assert attempt.status == "completed" and attempt.converged
        assert attempt.engine_version == "6.7.1"
        assert attempt.metadata["execution_kind"] == "real"
        assert "--opt" in attempt.command and "vtight" in attempt.command
        artifact_paths = _artifacts(run_dir, attempt)
        stdout = next(run_dir / path for path in artifact_paths if Path(path).name == "engine.stdout")
        assert "GEOMETRY OPTIMIZATION CONVERGED" in stdout.read_text()
        assert any(Path(path).name == "xtbopt.xyz" for path in artifact_paths)
    assert RunStore(run_dir).verify()["snapshot_id"]


@pytest.mark.integration
def test_real_cancel_after_committed_result_then_resume_preserves_evidence(tmp_path, monkeypatch):
    workflow = Workflow(tmp_path, config=SystemConfig(executables={"xtb": _native("xtb")}))
    event = Event()
    commit = RunStore.commit
    committed_candidate_ids = []

    def cancel_after_real_commit(store, record):
        result = commit(store, record)
        if not event.is_set():
            completed = [c for c in record.candidates if c.metadata.get("calculation_completed")]
            if completed:
                committed_candidate_ids.extend(c.candidate_id for c in completed)
                event.set()
        return result

    with monkeypatch.context() as context:
        context.setattr(RunStore, "commit", cancel_after_real_commit)
        interrupted = workflow.run(_request(), cancel_event=event)

    assert interrupted.status == "cancelled"
    assert len(committed_candidate_ids) == 1
    assert len(interrupted.attempts) == 1
    previous = interrupted.attempts[0].model_dump(mode="json")
    assert previous["status"] == "completed" and previous["metadata"]["execution_kind"] == "real"
    run_dir = tmp_path / interrupted.run_id
    previous_artifacts = _artifacts(run_dir, interrupted.attempts[0])
    assert RunStore(run_dir).load()["status"] == "cancelled"

    resumed = workflow.resume(run_dir)
    assert resumed.status == "completed"
    assert len(resumed.attempts) == resumed.request.n_candidates
    assert resumed.attempts[0].model_dump(mode="json") == previous
    assert _artifacts(run_dir, resumed.attempts[0]) == previous_artifacts
    assert sum(c.candidate_id == committed_candidate_ids[0] for c in resumed.candidates) == 1
    assert {a.metadata["sample_index"] for a in resumed.attempts} == {0, 1, 2}
    assert resumed.metadata["continuations"][0]["previous_status"] == "cancelled"
    assert RunStore(run_dir).verify()["snapshot_id"]


@pytest.mark.integration
def test_real_union_missing_crest_preserves_jiggle_then_extends_on_resume(tmp_path):
    xtb, crest = _native("xtb"), _native("crest")
    config = SystemConfig(executables={"xtb": xtb, "crest": str(tmp_path / "missing-crest")})
    workflow = Workflow(tmp_path, config=config)
    # Water keeps this interruption/recovery acceptance case short. Flexible
    # molecule discovery is covered independently, without asserting random counts.
    molecule = Molecule(symbols=["O", "H", "H"],
                        coordinates=[[0, 0, 0], [0.9572, 0, 0], [-0.23999, 0.9273, 0]])
    partial = workflow.run(_request(molecule=molecule, search_algorithm="union",
                                    sampler_profile="crest-mquick-v1", n_candidates=2))
    assert partial.status == "partial"
    assert partial.metadata["sampler_pending"] is True
    assert partial.metadata["sampler_incomplete"]["status"] == "unavailable"
    assert any(c.status == "eligible" for c in partial.candidates)
    sampler = next(a for a in partial.attempts if a.engine == "crest")
    assert sampler.status == "unavailable" and not sampler.quantities
    jq_attempts = [a for a in partial.attempts if a.engine == "xtb"]
    assert len(jq_attempts) == 2 and all(a.status == "completed" for a in jq_attempts)
    run_dir = tmp_path / partial.run_id
    old_attempts = {a.attempt_id: a.model_dump(mode="json") for a in jq_attempts}
    old_artifacts = {a.attempt_id: _artifacts(run_dir, a) for a in jq_attempts}
    old_plan = list(partial.metadata["sample_plan"])

    config.executables["crest"] = crest
    resumed = workflow.resume(run_dir)
    assert resumed.status == "completed", resumed.metadata.get("termination_reason")
    assert not resumed.metadata.get("sampler_pending", False)
    assert resumed.metadata["sample_plan"][:len(old_plan)] == old_plan
    assert len(resumed.metadata["sample_plan"]) > len(old_plan)
    for attempt in resumed.attempts:
        if attempt.attempt_id in old_attempts:
            assert attempt.model_dump(mode="json") == old_attempts[attempt.attempt_id]
            assert _artifacts(run_dir, attempt) == old_artifacts[attempt.attempt_id]
    assert all(sum(a.attempt_id == previous for a in resumed.attempts) == 1
               for previous in old_attempts)
    samplers = [a for a in resumed.attempts if a.engine == "crest"]
    assert len(samplers) == 2
    assert samplers[0].model_dump(mode="json") == sampler.model_dump(mode="json")
    assert samplers[1].status == "completed"
    assert samplers[1].parent_attempt_id == sampler.attempt_id
    assert samplers[1].metadata["execution_kind"] == "real"
    eligible = [c for c in resumed.candidates if c.status == "eligible"]
    assert any(set(c.sources) == {"INITIAL_SEED", "JIGGLE_QUENCH", "CREST"} for c in eligible)
    assert RunStore(run_dir).verify()["snapshot_id"]


@pytest.mark.integration
def test_invalid_proposal_is_processed_without_claiming_an_engine_calculation(tmp_path, monkeypatch):
    molecule = Molecule(symbols=["O", "H", "H"],
                        coordinates=[[0, 0, 0], [0.9572, 0, 0], [-0.23999, 0.9273, 0]])
    invalid = molecule.model_copy(deep=True)
    invalid.coordinates[1] = list(invalid.coordinates[0])

    def malformed_seed(request, index):
        assert index == 1
        return invalid

    # Only the proposed input is malformed; the initial seed still executes a
    # genuine xTB optimization. No solver result is supplied by this hook.
    monkeypatch.setattr(Workflow, "_seed", staticmethod(malformed_seed))
    workflow = Workflow(tmp_path, config=SystemConfig(executables={"xtb": _native("xtb")}))
    record = workflow.run(_request(molecule=molecule, n_candidates=2))
    assert record.status == "completed"
    assert len(record.attempts) == 1
    assert record.attempts[0].status == "completed"
    assert record.attempts[0].metadata["execution_kind"] == "real"
    rejected = next(candidate for candidate in record.candidates if candidate.status == "rejected")
    assert rejected.attempt_id is None and rejected.energy_hartree is None
    assert rejected.metadata["calculation_completed"] is False
    assert rejected.metadata["proposal_processed"] is True
    assert record.metadata["search_summary"]["processed_samples"] == 2
    assert record.metadata["search_summary"]["completed_samples"] == 1
    assert any(candidate.status == "eligible" for candidate in record.candidates)
    assert RunStore(tmp_path / record.run_id).verify()["snapshot_id"]
