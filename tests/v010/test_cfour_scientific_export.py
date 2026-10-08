"""Storage and omission bookkeeping; no constructed successful native calculation.

The stdout is the unchanged genuine failed first-order diagnostic. Library files
below are inert byte markers, never chemical coefficients or licensed payloads.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from topos.actions.hosted_worker import stage_committed_run
from topos.base_integration import BaseIntegrationError, _cfour_controlled_dependencies
from topos.cfour_artifacts import (
    POLICY_NAME,
    finalize_artifacts,
    validate_scientific_export_membership,
)
from topos.engines import EngineResult
from topos.models import Artifact, Attempt, Molecule, RunRecord, RunRequest
from topos.storage import IntegrityError, RunStore, atomic_json, file_digest, read_json

FIXTURE = Path(__file__).parent / "fixtures/cfour_failed_first_order"


def failed_collection(tmp_path):
    folder = tmp_path / "component"
    native = folder / "evaluation-00000"
    native.mkdir(parents=True)
    (native / "ZMAT").write_bytes((FIXTURE / "native-ZMAT.inp").read_bytes())
    (native / "engine.stdout").write_bytes((FIXTURE / "output.stdout").read_bytes())
    (native / "engine.stderr").write_text("")
    (folder / "protocol.json").write_text("{}")
    (native / "GENBAS").write_text("Inert GENBAS marker; not a licensed basis library\n")
    (native / "ECPDATA").write_text("Inert ECPDATA marker; not a licensed basis library\n")
    # A renamed copy with an allowed native evidence name still must be omitted.
    (native / "GRD").write_bytes((native / "GENBAS").read_bytes())
    (native / "JAINDX").write_bytes(b"Inert scratch marker")
    basis = {"path": "/controlled/GENBAS", "sha256": file_digest(native / "GENBAS")}
    result = EngineResult(
        engine="cfour",
        method="CCSD(T)",
        operation="first-order-properties",
        status="failed",
        diagnostics={"reason": "Genuine xjoda control failure"},
        metadata={
            "basis_library": basis,
            "requested_protocol": {"genbas_path": basis["path"], "genbas_sha256": basis["sha256"]},
        },
    )
    finalize_artifacts(result, folder)
    return folder, native, result


def record_and_manifest(folder, result):
    artifacts = [
        {
            **a.model_dump(mode="json"),
            "path": "components/failed/" + Path(a.path).relative_to(folder).as_posix(),
        }
        for a in result.artifacts
    ]
    return {
        "attempts": [
            {
                "engine": "cfour",
                "status": "failed",
                "metadata": copy.deepcopy(result.metadata),
                "artifacts": artifacts,
            }
        ]
    }, {"artifacts": copy.deepcopy(artifacts)}


def rebind_policy(record, manifest):
    from hashlib import sha256

    from topos.storage import json_bytes

    attempt = record["attempts"][0]
    encoded = json_bytes(attempt["metadata"]["cfour_evidence_policy"]) + b"\n"
    digest = sha256(encoded).hexdigest()
    attempt["metadata"]["cfour_evidence_policy_sha256"] = digest
    for artifact in [*attempt["artifacts"], *manifest["artifacts"]]:
        if artifact["role"] == "cfour-evidence-policy":
            artifact.update(sha256=digest, size_bytes=len(encoded))


def test_collection_retains_scientific_failure_and_omits_libraries_scratch_and_copies(tmp_path):
    folder, native, result = failed_collection(tmp_path)
    assert (
        result.status == "failed"
        and result.diagnostics["reason"] == "Genuine xjoda control failure"
    )
    assert not result.converged and result.energy_hartree is None
    policy = read_json(folder / POLICY_NAME)
    assert policy == result.metadata["cfour_evidence_policy"]
    assert result.metadata["cfour_evidence_policy_sha256"] == file_digest(folder / POLICY_NAME)
    omitted = {a["path"]: a for a in policy["omitted_files"]}
    assert set(omitted) == {
        f"evaluation-00000/{name}" for name in ("GENBAS", "ECPDATA", "GRD", "JAINDX")
    }
    assert omitted["evaluation-00000/GRD"]["classification"] == "licensed-basis"
    assert omitted["evaluation-00000/JAINDX"]["classification"] == "native-scratch"
    assert (
        policy["native_rerun_self_contained"] is False
        and policy["licensed_assets_included"] is False
    )
    assert (native / "GENBAS").is_file()  # Remains only in controlled execution storage.
    proof = validate_scientific_export_membership(*record_and_manifest(folder, result))
    assert proof["cfour_attempts"] == 1 and proof["native_rerun_self_contained"] is False


@pytest.mark.parametrize("name", ["GENBAS", "ECPDATA", "nested/GENBAS", "nested/ecpdata"])
def test_reserved_library_names_rejected_even_without_cfour_attempt(tmp_path, name):
    item = {"path": name, "sha256": "a" * 64, "size_bytes": 1}
    with pytest.raises(IntegrityError, match="Licensed CFOUR"):
        validate_scientific_export_membership({"attempts": []}, {"artifacts": [item]})


@pytest.mark.parametrize("location", ["top-level", "attempt"])
def test_renamed_library_copy_cannot_enter_export(tmp_path, location):
    folder, native, result = failed_collection(tmp_path)
    record, manifest = record_and_manifest(folder, result)
    artifact = {
        "path": "renamed-allowed-looking.txt",
        "sha256": file_digest(native / "ECPDATA"),
        "size_bytes": (native / "ECPDATA").stat().st_size,
        "role": "raw-output",
    }
    manifest["artifacts"].append(artifact)
    if location == "attempt":
        record["attempts"][0]["artifacts"].append(artifact)
    with pytest.raises(IntegrityError, match="Licensed CFOUR|undeclared native payload"):
        validate_scientific_export_membership(record, manifest)


@pytest.mark.parametrize(
    "change",
    [
        "missing-policy",
        "hash",
        "size",
        "retained-hash",
        "unsupported",
        "omission-type",
        "omission-classification",
        "omission-path",
        "omission-duplicate",
        "retained-omission",
        "link-type",
        "link-path",
        "link-disposition",
        "link-duplicate",
        "dependencies-list",
        "dependencies-incomplete",
        "basis-missing",
        "basis-changed",
        "protocol-changed",
        "source-directory",
        "duplicate-artifact",
    ],
)
def test_export_rejects_inconsistent_or_malformed_policy(tmp_path, change):
    folder, _, result = failed_collection(tmp_path)
    record, manifest = record_and_manifest(folder, result)
    attempt = record["attempts"][0]
    policy = attempt["metadata"]["cfour_evidence_policy"]
    if change == "missing-policy":
        del attempt["metadata"]["cfour_evidence_policy"]
    elif change == "hash":
        attempt["metadata"]["cfour_evidence_policy_sha256"] = "0" * 64
    elif change == "size":
        next(a for a in attempt["artifacts"] if Path(a["path"]).name == "engine.stdout")[
            "size_bytes"
        ] += 1
    elif change == "retained-hash":
        next(iter(policy["retained_files"].values()))["sha256"] = "0" * 64
    elif change == "unsupported":
        policy["retained_files"]["JAINDX"] = {"sha256": "0" * 64, "size_bytes": 1}
    elif change == "omission-type":
        policy["omitted_files"] = None
    elif change == "omission-classification":
        policy["omitted_files"][0]["classification"] = "ignore"
    elif change == "omission-path":
        policy["omitted_files"][0]["path"] = "../GENBAS"
    elif change == "omission-duplicate":
        policy["omitted_files"].append(copy.deepcopy(policy["omitted_files"][0]))
    elif change == "retained-omission":
        policy["omitted_files"][0]["path"] = next(iter(policy["retained_files"]))
    elif change.startswith("link-"):
        link = {"path": "link", "link_text": "/not-read", "disposition": "not-followed-or-retained"}
        policy["omitted_links"] = [link]
        if change == "link-type":
            policy["omitted_links"] = None
        if change == "link-path":
            link["path"] = "../link"
        if change == "link-disposition":
            link["disposition"] = "followed"
        if change == "link-duplicate":
            policy["omitted_links"].append(copy.deepcopy(link))
    elif change == "dependencies-list":
        policy["controlled_runtime_dependencies"] = []
    elif change == "dependencies-incomplete":
        policy["controlled_runtime_dependencies"] = {"GENBAS": {}}
    elif change == "basis-missing":
        policy["controlled_basis_library"] = {}
    elif change == "basis-changed":
        policy["controlled_basis_library"]["sha256"] = "0" * 64
    elif change == "protocol-changed":
        attempt["metadata"]["requested_protocol"]["genbas_sha256"] = "0" * 64
    elif change == "source-directory":
        policy["source_directory"] = "relative"
    else:
        attempt["artifacts"].append(copy.deepcopy(attempt["artifacts"][0]))
    if change not in {"missing-policy", "hash"}:
        rebind_policy(record, manifest)
    with pytest.raises(IntegrityError):
        validate_scientific_export_membership(record, manifest)


@pytest.mark.parametrize("value", [None, [], 1, {}, ["GENBAS", "ECPDATA"]])
def test_malformed_runtime_dependency_collection_preserves_primary_error(tmp_path, value):
    folder, native, result = failed_collection(tmp_path)
    atomic_json(native / "engine-cfour-runtime.json", {"controlled_runtime_dependencies": value})
    finalize_artifacts(result, folder)
    assert (
        result.status == "failed"
        and result.diagnostics["reason"] == "Genuine xjoda control failure"
    )
    assert "dependency inventory is incomplete" in result.diagnostics["artifact_error"]


@pytest.mark.parametrize("value", [None, [], 1])
def test_malformed_basis_metadata_preserves_primary_error(tmp_path, value):
    folder, _, result = failed_collection(tmp_path)
    result.metadata["basis_library"] = value
    finalize_artifacts(result, folder)
    assert (
        result.status == "failed"
        and result.diagnostics["reason"] == "Genuine xjoda control failure"
    )
    assert "basis library identity must be an object" in result.diagnostics["artifact_error"]


@pytest.mark.parametrize("alias", ["relative/GENBAS", "/original-host/library-alias/GENBAS"])
def test_export_binds_requested_basis_bytes_without_resolving_original_path_alias(tmp_path, alias):
    folder, _, result = failed_collection(tmp_path)
    record, manifest = record_and_manifest(folder, result)
    record["attempts"][0]["metadata"]["requested_protocol"]["genbas_path"] = alias
    assert validate_scientific_export_membership(record, manifest)["cfour_attempts"] == 1


@pytest.mark.parametrize("suffix", ["/../other", "/./other", "/", "//other"])
def test_export_rejects_noncanonical_source_directory(tmp_path, suffix):
    folder, _, result = failed_collection(tmp_path)
    record, manifest = record_and_manifest(folder, result)
    record["attempts"][0]["metadata"]["cfour_evidence_policy"]["source_directory"] += suffix
    rebind_policy(record, manifest)
    with pytest.raises(IntegrityError, match="original native directory"):
        validate_scientific_export_membership(record, manifest)


@pytest.mark.parametrize("name", [POLICY_NAME, "matrix-component-result.json"])
@pytest.mark.parametrize("kind", ["omitted_files", "omitted_links"])
def test_policy_cannot_omit_retained_policy_or_matrix_receipt(tmp_path, name, kind):
    folder, _, result = failed_collection(tmp_path)
    record, manifest = record_and_manifest(folder, result)
    attempt = record["attempts"][0]
    policy = attempt["metadata"]["cfour_evidence_policy"]
    if name == "matrix-component-result.json":
        # Opaque metadata membership only, never a native result or authority.
        artifact = {
            "path": "components/failed/" + name,
            "sha256": "d" * 64,
            "size_bytes": 1,
            "role": "matrix-native-component-result",
        }
        attempt["artifacts"].append(artifact)
        manifest["artifacts"].append(copy.deepcopy(artifact))
    if kind == "omitted_files":
        policy[kind].append(
            {"path": name, "sha256": "e" * 64, "size_bytes": 1, "classification": "native-scratch"}
        )
    else:
        policy[kind].append(
            {
                "path": name,
                "link_text": "/never-followed",
                "disposition": "not-followed-or-retained",
            }
        )
    rebind_policy(record, manifest)
    with pytest.raises(IntegrityError, match="retained CFOUR scientific export"):
        validate_scientific_export_membership(record, manifest)


def test_staging_copies_only_verified_scientific_snapshot(tmp_path):
    folder, native, result = failed_collection(tmp_path)
    request = RunRequest(molecule=Molecule(symbols=["He"], coordinates=[[0, 0, 0]]))
    record = RunRecord(request=request, status="failed")
    for artifact in result.artifacts:
        artifact.path = str(Path(artifact.path).relative_to(tmp_path))
    record.attempts = [
        Attempt(
            run_id=record.run_id,
            engine="cfour",
            method="CCSD(T)",
            status="failed",
            artifacts=result.artifacts,
            diagnostics=result.diagnostics,
            metadata=result.metadata,
        )
    ]
    store = RunStore(tmp_path)
    store.commit(record)
    evidence = tmp_path.parent / (tmp_path.name + "-evidence")
    evidence.mkdir()
    from topos.storage import digest_json

    receipt = stage_committed_run(tmp_path, evidence, digest_json(request.model_dump(mode="json")))
    assert receipt["status"] == "failed"
    assert receipt["scientific_export_membership"]["native_rerun_self_contained"] is False
    staged = RunStore(evidence / "run")
    assert staged.verify() == store.verify() and staged.load() == store.load()
    assert not list(evidence.rglob("GENBAS")) and not list(evidence.rglob("ECPDATA"))
    controlled_hashes = {file_digest(native / name) for name in ("GENBAS", "ECPDATA")}
    assert all(file_digest(p) not in controlled_hashes for p in evidence.rglob("*") if p.is_file())


@pytest.mark.parametrize("engine", ["cfour", "infrastructure"])
def test_staging_rejects_old_unqualified_library_payload_before_copy(tmp_path, engine):
    request = RunRequest(molecule=Molecule(symbols=["He"], coordinates=[[0, 0, 0]]))
    record = RunRecord(request=request, status="failed")
    path = tmp_path / "GENBAS"
    path.write_text("Inert byte marker; no licensed content")
    artifact = Artifact(path="GENBAS", sha256=file_digest(path), size_bytes=path.stat().st_size)
    if engine == "cfour":
        record.attempts = [
            Attempt(
                run_id=record.run_id,
                engine=engine,
                method="HF",
                status="failed",
                artifacts=[artifact],
            )
        ]
    else:
        record.artifacts = [artifact]
    RunStore(tmp_path).commit(record)
    evidence = tmp_path.parent / (tmp_path.name + "-evidence")
    evidence.mkdir()
    from topos.storage import digest_json

    with pytest.raises(IntegrityError, match="Licensed CFOUR"):
        stage_committed_run(tmp_path, evidence, digest_json(request.model_dump(mode="json")))
    assert not list(evidence.iterdir())


def registry_dependency_metadata():
    # Independently retained genuine Stage 0 metadata, no library bytes.
    basis = read_json(
        Path(__file__).parent / "fixtures/cfour_controlled_transport/registry-basis-excerpt.json"
    )
    return {"runtime_metadata": {"basis": basis}}, {"GENBAS": basis["GENBAS"]["sha256"]}


def test_broker_dependency_receipt_uses_actual_audited_registry_identities():
    registry, native_inputs = registry_dependency_metadata()
    actual = _cfour_controlled_dependencies(registry, native_inputs)
    assert set(actual) == {"GENBAS", "ECPDATA"}
    for name, entry in registry["runtime_metadata"]["basis"].items():
        assert actual[name] == {
            "path": entry["path"],
            "sha256": entry["sha256"],
            "size_bytes": entry["bytes"],
        }


@pytest.mark.parametrize("change", ["missing", "sha256", "path", "bool-size", "staged-mismatch"])
def test_broker_rejects_unbound_dependency_before_native_launch(change):
    registry, inputs = registry_dependency_metadata()
    item = registry["runtime_metadata"]["basis"]["ECPDATA"]
    if change == "missing":
        del registry["runtime_metadata"]["basis"]["ECPDATA"]
    if change == "sha256":
        item["sha256"] = "wrong"
    if change == "path":
        item["path"] = "relative"
    if change == "bool-size":
        item["bytes"] = True
    if change == "staged-mismatch":
        inputs["GENBAS"] = "0" * 64
    with pytest.raises(BaseIntegrationError, match="dependency identities|differs from"):
        _cfour_controlled_dependencies(registry, inputs)


@pytest.mark.parametrize('level', ['record', 'runtime_metadata', 'basis', 'GENBAS', 'ECPDATA'])
@pytest.mark.parametrize('value', [None, [], 1])
def test_broker_rejects_malformed_dependency_containers(level, value):
    registry, inputs = registry_dependency_metadata()
    if level == 'record':
        registry = value
    elif level == 'runtime_metadata':
        registry['runtime_metadata'] = value
    elif level == 'basis':
        registry['runtime_metadata']['basis'] = value
    else:
        registry['runtime_metadata']['basis'][level] = value
    with pytest.raises(BaseIntegrationError, match='dependency identities'):
        _cfour_controlled_dependencies(registry, inputs)
