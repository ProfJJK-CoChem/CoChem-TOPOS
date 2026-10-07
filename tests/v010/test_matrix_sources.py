"""Verified matrix source imports from an actual CREST workflow.

One genuine native run supplies all positive evidence. Negative tests repackage
its real files with deliberately inconsistent record fields to check rejection;
they never create an executable, engine log, or synthetic successful calculation.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from topos.config import SystemConfig
from topos.matrix_sources import SourceEnsembleInput, import_native_ensemble
from topos.models import Bond, Molecule, RunRecord, RunRequest
from topos.storage import IntegrityError, RunStore, digest_json, file_digest
from topos.workflow import Workflow


@pytest.fixture(scope="module")
def real_source(tmp_path_factory):
    executables = {engine: shutil.which(os.environ.get(f"TOPOS_{engine.upper()}_EXECUTABLE", engine))
                   for engine in ("crest", "xtb")}
    if not all(executables.values()):
        pytest.skip("genuine CREST and xTB are required to create native source evidence")
    molecule = Molecule(symbols=["O", "H", "H"],
                        coordinates=[[0, 0, 0], [.9584, 0, 0], [-.239, .927, 0]])
    root = tmp_path_factory.mktemp("genuine-matrix-source")
    workflow = Workflow(root, config=SystemConfig(execution_backend="development", executables=executables))
    record = workflow.run(RunRequest(
        molecule=molecule, search_algorithm="crest", sampler_profile="crest-mquick-v1",
        n_candidates=1, budget_seconds=60, profile_id="xtb-tight-v1", seed=37,
    ))
    assert record.status == "completed", record.metadata
    native = [attempt for attempt in record.attempts if attempt.engine == "crest"]
    assert len(native) == 1 and native[0].status == "completed"
    assert native[0].engine_version == "3.0.2"
    assert native[0].metadata["execution_kind"] == "real" and native[0].metadata["raw_ensemble"]
    run_dir = root / record.run_id
    store = RunStore(run_dir)
    store.verify()
    return run_dir, molecule, native[0].attempt_id


def _selected(run_dir: Path, attempt_id: str | None = None) -> SourceEnsembleInput:
    return SourceEnsembleInput(run_dir=str(run_dir), record_sha256=digest_json(RunStore(run_dir).load()),
                               sampler_attempt_id=attempt_id)


def _repackage_negative_case(real_source, tmp_path, mutate) -> tuple[Path, Molecule, str]:
    """Create an intentionally inconsistent record using real native artifacts.

    Native artifacts remain exact bytes. This helper is used only to require
    rejection (or explicitly select the unmodified authentic attempt).
    """
    original_dir, molecule, attempt_id = real_source
    original = RunStore(original_dir)
    data = original.load()
    mutate(data)
    destination = tmp_path / "inconsistent-source"
    shutil.copytree(original.snapshot_path() / "artifacts", destination)
    RunStore(destination).commit(RunRecord.model_validate(data))
    return destination, molecule, attempt_id


def test_actual_native_ensemble_import_copies_verified_raw_evidence(real_source, tmp_path):
    run_dir, molecule, attempt_id = real_source
    selected = _selected(run_dir)
    result = import_native_ensemble(selected, expected_engine="crest", expected_molecule=molecule,
                                    destination=tmp_path / "imports")
    record = RunStore(run_dir).load()
    original = next(row for row in record["attempts"] if row["attempt_id"] == attempt_id)
    assert [frame.model_dump(mode="json") for frame in result.frames] == original["metadata"]["raw_ensemble"]
    assert result.provenance["record_sha256"] == selected.record_sha256
    assert result.provenance["sampler_attempt_id"] == attempt_id
    assert result.provenance["engine_version"] == "3.0.2"
    assert result.provenance["native_frame_count"] == len(result.frames)
    assert result.provenance["sampler"] == "CREST"
    assert len(result.artifacts) == len(original["artifacts"]) + 2
    root = tmp_path / "imports" / selected.record_sha256
    for artifact in result.artifacts:
        assert Path(artifact.path).is_relative_to(root)
        assert file_digest(Path(artifact.path)) == artifact.sha256
        assert Path(artifact.path).stat().st_size == artifact.size_bytes
    assert json.loads((root / "source-record.json").read_text()) == record
    assert json.loads((root / "source-manifest.json").read_text()) == RunStore(run_dir).verify()
    repeated = import_native_ensemble(selected, expected_engine="crest", expected_molecule=molecule,
                                      destination=tmp_path / "imports")
    assert repeated == result


def test_explicit_source_record_digest_cannot_silently_select_latest(real_source, tmp_path):
    original, molecule, _ = real_source
    clone = tmp_path / "source"
    shutil.copytree(original, clone)
    selected = _selected(clone)
    store = RunStore(clone)
    record = RunRecord.model_validate(store.load())
    record.metadata["source_selection_test"] = "new genuine record revision"
    store.commit(record)
    with pytest.raises(IntegrityError, match="SHA-256"):
        import_native_ensemble(selected, expected_engine="crest", expected_molecule=molecule,
                               destination=tmp_path / "imports")
    assert not (tmp_path / "imports").exists()


def test_wrong_record_digest_is_rejected_before_copy(real_source, tmp_path):
    run_dir, molecule, _ = real_source
    selected = SourceEnsembleInput(run_dir=str(run_dir), record_sha256="0" * 64)
    with pytest.raises(IntegrityError, match="SHA-256"):
        import_native_ensemble(selected, expected_engine="crest", expected_molecule=molecule,
                               destination=tmp_path / "imports")


def test_crest_source_cannot_be_relabelled_as_goat(real_source, tmp_path):
    run_dir, molecule, _ = real_source
    with pytest.raises(ValueError, match="native sampler"):
        import_native_ensemble(_selected(run_dir), expected_engine="goat", expected_molecule=molecule,
                               destination=tmp_path / "imports")


@pytest.mark.parametrize("field,value", [("engine_version", "3.0.1"), ("status", "failed"),
                                         ("validation_status", "not-evaluated")])
def test_source_requires_verified_completed_matching_version(real_source, tmp_path, field, value):
    def change(data):
        sampler = next(row for row in data["attempts"] if row["engine"] == "crest")
        sampler[field] = value
    run_dir, molecule, _ = _repackage_negative_case(real_source, tmp_path, change)
    with pytest.raises(ValueError, match="native sampler"):
        import_native_ensemble(_selected(run_dir), expected_engine="crest", expected_molecule=molecule,
                               destination=tmp_path / "imports")


def test_changed_native_frame_source_label_is_rejected(real_source, tmp_path):
    def change(data):
        sampler = next(row for row in data["attempts"] if row["engine"] == "crest")
        sampler["metadata"]["raw_ensemble"][0]["source"] = "GOAT"
    run_dir, molecule, _ = _repackage_negative_case(real_source, tmp_path, change)
    with pytest.raises(ValueError, match="source identity"):
        import_native_ensemble(_selected(run_dir), expected_engine="crest", expected_molecule=molecule,
                               destination=tmp_path / "imports")


def test_raw_metadata_energy_must_match_authentic_native_artifact(real_source, tmp_path):
    def change(data):
        sampler = next(row for row in data["attempts"] if row["engine"] == "crest")
        sampler["metadata"]["raw_ensemble"][0]["energy_hartree"] += .1
    run_dir, molecule, _ = _repackage_negative_case(real_source, tmp_path, change)
    with pytest.raises((ValueError, IntegrityError), match="ensemble|native|artifact"):
        import_native_ensemble(_selected(run_dir), expected_engine="crest", expected_molecule=molecule,
                               destination=tmp_path / "imports")


def test_ambiguous_native_attempts_require_explicit_selection(real_source, tmp_path):
    def change(data):
        sampler = next(row for row in data["attempts"] if row["engine"] == "crest")
        duplicate = json.loads(json.dumps(sampler))
        duplicate["attempt_id"] = "attempt-duplicate-evidence-reference"
        data["attempts"].append(duplicate)
    run_dir, molecule, authentic_attempt = _repackage_negative_case(real_source, tmp_path, change)
    with pytest.raises(ValueError, match="exactly one"):
        import_native_ensemble(_selected(run_dir), expected_engine="crest", expected_molecule=molecule,
                               destination=tmp_path / "ambiguous")
    # Select only the unmodified authentic attempt; duplicated evidence is not
    # represented as a second successful execution by this positive assertion.
    result = import_native_ensemble(_selected(run_dir, authentic_attempt), expected_engine="crest",
                                    expected_molecule=molecule, destination=tmp_path / "explicit")
    assert result.provenance["sampler_attempt_id"] == authentic_attempt


@pytest.mark.parametrize("change", [
    {"charge": 1, "multiplicity": 2},
    {"isotopes": [18, None, None]},
    {"atom_ids": ["other-oxygen", "atom-1", "atom-2"]},
    {"bonds": [Bond(atom1=0, atom2=1), Bond(atom1=0, atom2=2)]},
])
def test_source_molecular_identity_must_match_requested_chemistry(real_source, tmp_path, change):
    run_dir, molecule, _ = real_source
    data = molecule.model_dump()
    data.update(change)
    expected = Molecule(**data)
    with pytest.raises(ValueError, match="identity|mapping|state|metadata"):
        import_native_ensemble(_selected(run_dir), expected_engine="crest", expected_molecule=expected,
                               destination=tmp_path / "imports")


def test_snapshot_artifact_tamper_is_rejected(real_source, tmp_path):
    original, molecule, attempt_id = real_source
    clone = tmp_path / "source"
    shutil.copytree(original, clone)
    store = RunStore(clone)
    selected = _selected(clone)
    native = next(row for row in store.load()["attempts"] if row["attempt_id"] == attempt_id)
    artifact = next(row for row in native["artifacts"] if Path(row["path"]).name == "crest_conformers.xyz")
    path = store.snapshot_path() / "artifacts" / artifact["path"]
    path.write_bytes(path.read_bytes() + b"\ncorrupted artifact\n")
    with pytest.raises(IntegrityError, match="checksum"):
        import_native_ensemble(selected, expected_engine="crest", expected_molecule=molecule,
                               destination=tmp_path / "imports")


def test_mutable_working_file_tamper_cannot_replace_verified_snapshot(real_source, tmp_path):
    original, molecule, attempt_id = real_source
    clone = tmp_path / "source"
    shutil.copytree(original, clone)
    store = RunStore(clone)
    native = next(row for row in store.load()["attempts"] if row["attempt_id"] == attempt_id)
    artifact = next(row for row in native["artifacts"] if Path(row["path"]).name == "crest_conformers.xyz")
    (clone / artifact["path"]).write_text("working file changed; snapshot remains authoritative")
    result = import_native_ensemble(_selected(clone), expected_engine="crest", expected_molecule=molecule,
                                    destination=tmp_path / "imports")
    copied = next(a for a in result.artifacts if Path(a.path).name == "crest_conformers.xyz")
    assert copied.sha256 == artifact["sha256"] and file_digest(Path(copied.path)) == artifact["sha256"]


def test_existing_import_evidence_cannot_be_silently_replaced(real_source, tmp_path):
    run_dir, molecule, _ = real_source
    selected = _selected(run_dir)
    result = import_native_ensemble(selected, expected_engine="crest", expected_molecule=molecule,
                                    destination=tmp_path / "imports")
    artifact = next(a for a in result.artifacts if Path(a.path).name == "crest_conformers.xyz")
    Path(artifact.path).write_text("corrupted prior import")
    with pytest.raises(IntegrityError, match="Imported native artifact"):
        import_native_ensemble(selected, expected_engine="crest", expected_molecule=molecule,
                               destination=tmp_path / "imports")


def test_import_root_symlink_cannot_redirect_raw_evidence_outside_destination(real_source, tmp_path):
    run_dir, molecule, _ = real_source
    selected = _selected(run_dir)
    outside = tmp_path / "unrelated-directory"
    outside.mkdir()
    destination = tmp_path / "imports"
    destination.mkdir()
    (destination / selected.record_sha256).symlink_to(outside, target_is_directory=True)
    with pytest.raises(IntegrityError, match="root cannot be a symlink"):
        import_native_ensemble(selected, expected_engine="crest", expected_molecule=molecule,
                               destination=destination)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("filename", ["source-record.json", "source-manifest.json"])
def test_dangling_identity_file_symlink_is_rejected(real_source, tmp_path, filename):
    run_dir, molecule, _ = real_source
    selected = _selected(run_dir)
    destination = tmp_path / "imports"
    source_root = destination / selected.record_sha256
    source_root.mkdir(parents=True)
    unrelated_target = tmp_path / "unrelated-missing-file.json"
    identity_path = source_root / filename
    identity_path.symlink_to(unrelated_target)
    with pytest.raises(IntegrityError, match="identity file cannot be a symlink"):
        import_native_ensemble(selected, expected_engine="crest", expected_molecule=molecule,
                               destination=destination)
    assert identity_path.is_symlink()
    assert not unrelated_target.exists()


@pytest.mark.parametrize("url", ["https://example.invalid/run", "file:///tmp/run", "s3://bucket/run"])
def test_urls_are_not_treated_as_authorized_local_native_sources(tmp_path, url):
    molecule = Molecule(symbols=["He"], coordinates=[[0, 0, 0]])
    source = SourceEnsembleInput(run_dir=url, record_sha256="0" * 64)
    with pytest.raises(ValueError, match="local RunStore"):
        import_native_ensemble(source, expected_engine="crest", expected_molecule=molecule,
                               destination=tmp_path / "imports")
    assert not (tmp_path / "imports").exists()
