"""Historical native Hessian persistence contracts; no new licensed calculation.

Retained B3LYP-D4 water output exercises attribution, recovery and export guards.
This does not certify the r2SCAN-3c union recipe or the enclosing VPT2 job.
"""
from __future__ import annotations

import copy
import json
import shutil
import time
from pathlib import Path

import pytest

from topos.config import SystemConfig
from topos.engines import EngineResult
from topos.matrix_components import run_component
from topos.matrix_union import _native_hessian_candidate
from topos.models import Artifact, Attempt, MethodSpec, Quantity, RunRecord, RunRequest
from topos.review import validate_scientific_candidate
from topos.storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest
from topos.workflow import Workflow

FIXTURE = Path(__file__).parent / "fixtures/orca_native_hessian_attribution"


@pytest.fixture
def historical_component(tmp_path):
    proof = json.loads((FIXTURE / "provenance.json").read_text())
    for name, expected in proof["files"].items():
        assert file_digest(FIXTURE / name) == expected["sha256"]
        assert (FIXTURE / name).stat().st_size == expected["size_bytes"]
    native = EngineResult.model_validate(json.loads((FIXTURE / "completed-result.json").read_text())["result"])
    molecule = native.molecule
    spec = MethodSpec.model_validate(native.metadata["requested_method"]).model_copy(update={"purpose": "frequency"})
    record = RunRecord(request=RunRequest(molecule=molecule, engine="orca", method=spec.method,
        basis=spec.basis, auxiliary_basis=spec.auxiliary_basis, dispersion=spec.dispersion,
        purpose="frequency", budget_seconds=60), status="running",
        metadata={"fixture_scope": proof["scope"]})
    source = Attempt(run_id=record.run_id, attempt_id="attempt_historical_native_hessian",
        engine=native.engine, method=native.method, engine_version=native.engine_version,
        status="completed", converged=True, validation_status="validated-for-protocol", command=native.command)
    store = RunStore(tmp_path / record.run_id)
    folder = store.run_dir / "attempts" / source.attempt_id
    folder.mkdir(parents=True)
    names = {"frequency.hess": "frequency.hess", "frequency.stdout": "frequency.stdout",
             "frequency.inp": "frequency.inp", "engine.stdout": "gradient-engine.stdout",
             "job.engrad": "gradient-job.engrad", "job.inp": "gradient-job.inp"}
    # Use an explicitly identified text-only historical evidence subset. Native
    # values remain exact; rebase retained paths without inventing raw output.
    selected = []
    for artifact in native.artifacts:
        name = Path(artifact.path).name
        if name not in names:
            continue
        dest = folder / names[name]
        shutil.copyfile(FIXTURE / names[name], dest)
        assert file_digest(dest) == artifact.sha256
        selected.append(artifact.model_copy(update={"path": str(dest)}))
    native.artifacts = selected
    reference = native.metadata["reference_gradient_result"]
    reference["artifacts"] = [a.model_dump(mode="json") for a in selected if Path(a.path).name.startswith("gradient-")]
    source.metadata = {**copy.deepcopy(native.metadata), "role": "matrix-native-component",
        "component_key": "historical-analytic-hessian", "input_molecule": molecule.model_dump(mode="json"),
        "requested_protocol": spec.model_dump(mode="json"), "native_result": native.model_dump(mode="json")}
    source.metadata["native_result_sha256"] = digest_json(source.metadata["native_result"])
    source.metadata["matrix_component_sha256"] = digest_json({"component_key": "historical-analytic-hessian",
        "molecule": molecule.model_dump(mode="json"), "protocol": spec.model_dump(mode="json")})
    source.quantities = [Quantity(name="electronic_energy", value=native.energy_hartree, units="hartree",
        definition="unchanged retained historical native electronic energy", attempt_id=source.attempt_id,
        method=spec.method, validity="validated-for-protocol"),
        Quantity(name="cartesian_gradient", value=native.gradient_hartree_per_bohr, units="hartree/bohr",
        definition="unchanged retained historical independent native gradient", attempt_id=source.attempt_id,
        method=spec.method, validity="validated-for-protocol")]
    source.artifacts = [a.model_copy(update={"path": Path(a.path).relative_to(store.run_dir).as_posix()}) for a in selected]
    receipt = folder / "matrix-component-result.json"
    atomic_json(receipt, source.metadata["native_result"])
    source.artifacts.append(Artifact(path=receipt.relative_to(store.run_dir).as_posix(), sha256=file_digest(receipt),
        size_bytes=receipt.stat().st_size, role="matrix-native-component-result"))
    record.attempts.append(source)
    store.commit(record)
    workflow = Workflow(tmp_path / "unused", config=SystemConfig(execution_backend="development"))
    return workflow, record, store, source, native, spec


def attribute(context):
    workflow, record, store, source, native, spec = context
    return _native_hessian_candidate(workflow, record, store, native.molecule, source, native,
                                     spec, 1, time.monotonic() + 30)


def test_native_union_candidate_commits_and_reuses_without_mutating_component(historical_component):
    workflow, record, store, source, native, spec = historical_component
    before = source.model_dump(mode="json")
    candidate = attribute(historical_component)
    assert source.model_dump(mode="json") == before
    attribution = record.attempts[-1]
    assert attribution.parent_attempt_id == source.attempt_id
    assert attribution.metadata["native_hessian_attempt_id"] == source.attempt_id
    assert attribution.metadata["attribution_only"] is True
    assert attribution.command == ["topos-internal", "native-hessian-candidate-attribution"]
    assert candidate.attempt_id == attribution.attempt_id
    assert all(q.attempt_id == attribution.attempt_id and q.geometry_id == candidate.candidate_id
               for q in attribution.quantities)
    assert {q.name for q in source.quantities} == {"electronic_energy", "cartesian_gradient"}
    validate_scientific_candidate(record.model_dump(mode="json"), candidate.model_dump(mode="json"))
    assert store.verify()
    restored = RunRecord.model_validate(store.recover())
    restored_source = next(a for a in restored.attempts if a.attempt_id == source.attempt_id)

    def forbidden_execution(*args, **kwargs):
        pytest.fail("Completed immutable native component was reexecuted")

    cached = run_component(workflow, restored, store, "historical-analytic-hessian", native.molecule,
                           spec, forbidden_execution, time.monotonic() + 30, None)
    assert cached == native
    again = attribute((workflow, restored, store, restored_source, cached, spec))
    assert again.candidate_id == candidate.candidate_id
    assert len(restored.attempts) == 2 and len(restored.candidates) == 1
    again.metadata["native_cregen_selected"] = True
    store.commit(restored)
    assert store.verify()
    assert restored_source.model_dump(mode="json") == before


@pytest.mark.parametrize("published", [False, True])
def test_native_union_recovers_atomic_attribution_after_commit_failure(historical_component, monkeypatch, published):
    workflow, record, store, source, native, spec = historical_component
    real_commit = store.commit

    def interrupted(value):
        if published:
            real_commit(value)
        raise RuntimeError("Injected publication acknowledgement interruption")

    monkeypatch.setattr(store, "commit", interrupted)
    with pytest.raises(RuntimeError, match="acknowledgement"):
        attribute(historical_component)
    monkeypatch.setattr(store, "commit", real_commit)
    restored = RunRecord.model_validate(store.recover())
    restored_source = next(a for a in restored.attempts if a.attempt_id == source.attempt_id)
    candidate = attribute((workflow, restored, store, restored_source, native, spec))
    assert len(restored.attempts) == 2 and len(restored.candidates) == 1
    assert candidate.attempt_id == restored.attempts[-1].attempt_id
    assert store.verify()


@pytest.mark.parametrize("damage", ["source-link", "parent-link", "source-hash", "source-command", "metadata",
                                   "source-quantity", "source-binary", "artifacts", "hessian-geometry", "internal-command"])
def test_native_union_export_rejects_damaged_source_attribution(historical_component, damage):
    _, record, _, _, _, _ = historical_component
    candidate = attribute(historical_component)
    data = record.model_dump(mode="json")
    derived = data["attempts"][-1]
    source = data["attempts"][0]
    if damage == "source-link":
        derived["metadata"]["native_hessian_attempt_id"] = "missing"
    elif damage == "parent-link":
        derived["parent_attempt_id"] = "missing"
    elif damage == "source-hash":
        derived["metadata"]["native_hessian_result_sha256"] = "f" * 64
    elif damage == "source-command":
        source["command"] = derived["command"]
    elif damage == "metadata":
        derived["metadata"]["analysis"]["frequencies_cm1"][0] += 1
    elif damage == "source-quantity":
        source["quantities"][0]["value"] += .1
    elif damage == "source-binary":
        source["metadata"]["executable_sha256"] = "f" * 64
    elif damage == "artifacts":
        derived["artifacts"].pop()
    elif damage == "hessian-geometry":
        next(q for q in derived["quantities"] if q["name"] == "cartesian_hessian")["geometry_id"] = "wrong"
    else:
        derived["command"] = source["command"]
    with pytest.raises(IntegrityError):
        validate_scientific_candidate(data, candidate.model_dump(mode="json"))


def test_native_union_completed_attribution_cache_rejects_mutation(historical_component):
    attribute(historical_component)
    historical_component[1].attempts[-1].metadata["native_hessian_result_sha256"] = "f" * 64
    with pytest.raises(IntegrityError, match="attribution changed"):
        attribute(historical_component)
