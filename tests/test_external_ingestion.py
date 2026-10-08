"""Actual retained native text and starting-state integrity; no replay physics claims."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from threading import Event

import pytest
from pydantic import ValidationError

from topos.actions.dispatch import DispatchResult
from topos.chemistry import to_xyz
from topos.cli import main
from topos.config import SystemConfig
from topos.ingestion import (
    MAX_IMPORT_BYTES,
    ExternalImportSpec,
    ExternalSource,
    execute_external,
    prepare_external_request,
    preview_external,
    preview_external_bytes,
    stage_external,
    stage_external_many,
)
from topos.models import FragmentState, Molecule, RunRequest
from topos.review import validate_scientific_candidate
from topos.storage import IntegrityError, RunStore, digest_json, file_digest
from topos.workflow import Workflow

NATIVE_GOAT = Path(__file__).parent / "v010/fixtures/goat_hosted_finalensemble/native-ensemble.txt"


@pytest.fixture
def water():
    return Molecule(symbols=["O", "H", "H"],
                    coordinates=[[0, 0, 0], [.95, 0, 0], [-.24, .93, 0]],
                    atom_ids=["water-O", "water-Ha", "water-Hb"])


def specification(water, **changes):
    source = ExternalSource(engine="orca", engine_version="6.1.1", method="r2SCAN-3c",
                            created_by="student", description="Historical native GOAT output; not a current-source acceptance run",
                            coordinate_units="angstrom", energy_units="hartree", atom_order=water.atom_ids)
    return ExternalImportSpec(format="goat-ensemble", reference=water, source=source, **changes)


def geometry_spec(molecule, **changes):
    return ExternalImportSpec(format="xyz", reference=molecule,
                              source=ExternalSource(engine="external", engine_version="declared-unknown",
                                                    method="geometry preparation", created_by="student",
                                                    description="User supplied geometry only; no computed energy",
                                                    atom_order=molecule.atom_ids), **changes)


def test_unchanged_retained_goat_bytes_preview_without_a_native_acceptance_claim(water):
    assert file_digest(NATIVE_GOAT) == "6fadc245d22151d2ec0e9d7f786b3d9a105ceb8015e73394648ae2b06d53a91b"
    preview = preview_external(NATIVE_GOAT, specification(water))
    assert preview.source_sha256 == file_digest(NATIVE_GOAT)
    assert preview.frames[0].observed_energy_hartree == -76.4189354908
    assert preview.frames[0].metadata["native_frame_converged"] is True
    assert preview.frames[0].molecule.atom_ids == water.atom_ids
    assert preview.validation_status == "requires-real-calculation"
    assert "caller declarations" in preview.warnings[0]


def test_browser_bytes_preview_uses_same_native_parser_and_does_not_create_a_run(water):
    preview = preview_external_bytes(NATIVE_GOAT.read_bytes(), specification(water),
                                     filename="student-goat.finalensemble.xyz")
    assert preview.original_filename == "student-goat.finalensemble.xyz"
    assert preview.source_sha256 == file_digest(NATIVE_GOAT)
    assert preview.frames[0].observed_energy_hartree == -76.4189354908
    with pytest.raises(ValueError, match="bounded nonempty"):
        preview_external_bytes(b"", specification(water))


def test_original_native_and_associated_output_bytes_are_durable_inputs_only(tmp_path, water):
    original = NATIVE_GOAT.read_bytes()
    stdout = NATIVE_GOAT.parent / "native-search.stdout"
    record = stage_external(NATIVE_GOAT, specification(water),
                            RunRequest(molecule=water, purpose="energy"), tmp_path / "runs",
                            supporting_files=[stdout])
    store = RunStore(tmp_path / "runs" / record.run_id)
    snapshot = store.snapshot_path() / "artifacts"
    assert (snapshot / "external-inputs/input-0001.txt").read_bytes() == original
    assert (snapshot / "external-inputs/support-0001.txt").read_bytes() == stdout.read_bytes()
    assert record.status == "queued" and not record.attempts and not record.candidates
    assert len(record.request.starting_geometries) == 1
    assert record.request.starting_geometries[0] == preview_external(NATIVE_GOAT, specification(water)).frames[0].molecule
    assert record.request.metadata["external_starting_states"][0]["declaration"]["method"] == "r2SCAN-3c"
    assert record.request.method == "GFN2-xTB"
    assert "energy_hartree" not in record.request.metadata["external_starting_states"][0]
    assert store.verify()["record_sha256"]
    with pytest.raises(IntegrityError, match="no calculation attempt"):
        validate_scientific_candidate(record.model_dump(mode="json"),
                                      {"candidate_id": "external-frame", "attempt_id": None})


def test_xyz_comment_energy_is_not_interpreted(tmp_path, water):
    path = tmp_path / "user.xyz"
    path.write_text(to_xyz(water, "Energy -123456.0 hartree; comment only"))
    preview = preview_external(path, geometry_spec(water, entrypoint="geometry"))
    assert preview.frames[0].observed_energy_hartree is None


@pytest.mark.parametrize("purpose", ["search", "optimize", "energy", "gradient", "frequency",
                                   "thermochemistry", "association", "matrix"])
def test_geometry_entrypoint_binds_every_supported_calculation_purpose(water, purpose):
    spec = specification(water, entrypoint="geometry")
    preview = preview_external(NATIVE_GOAT, spec)
    request = prepare_external_request(preview, spec, RunRequest(molecule=water, purpose=purpose))
    assert request.purpose == purpose
    assert request.molecule.coordinates == preview.frames[0].molecule.coordinates
    assert not request.starting_geometries


@pytest.mark.parametrize("field", ["topology_seeds", "stage_b_ensemble", "leading_isomers",
                                 "entropy_seeds", "ml_search_seeds", "goat_ensemble", "crest_ensemble"])
def test_geometry_import_rejects_shadowing_matrix_starting_states_without_creating_a_run(tmp_path, water, field):
    spec = specification(water, entrypoint="geometry")
    prior = ([water.model_dump(mode="json")] if field.endswith("seeds") or field in {
        "stage_b_ensemble", "leading_isomers"
    } else {"run_dir": str(tmp_path / "unresolved-native-source"), "record_sha256": "0" * 64})
    request = RunRequest(molecule=water, purpose="matrix", matrix_row_id="T1-3d",
                         matrix_inputs={field: prior})
    before = request.model_dump(mode="json")
    destination = tmp_path / "runs"
    with pytest.raises(ValueError, match="matching named entrypoint"):
        stage_external(NATIVE_GOAT, spec, request, destination)
    assert request.model_dump(mode="json") == before
    assert not destination.exists()


def test_geometry_import_preserves_isolated_monomer_references_and_protocols(water):
    spec = specification(water, entrypoint="geometry")
    original = RunRequest(molecule=water, purpose="matrix", matrix_row_id="T3O-1min",
                          matrix_inputs={"isolated_monomer_references": [water.model_dump(mode="json")],
                                         "isolated_monomer_sources": ["declared standalone reference"]})
    result = prepare_external_request(preview_external(NATIVE_GOAT, spec), spec, original)
    assert result.molecule.coordinates != original.molecule.coordinates
    assert result.matrix_inputs["isolated_monomer_references"] == original.matrix_inputs["isolated_monomer_references"]
    assert result.matrix_inputs["isolated_monomer_sources"] == original.matrix_inputs["isolated_monomer_sources"]


@pytest.mark.parametrize("purpose", ["search", "optimize", "energy", "gradient"])
def test_refinement_has_serializable_declared_frames_and_no_source_energy_acceptance(water, purpose):
    spec = specification(water)
    request = prepare_external_request(preview_external(NATIVE_GOAT, spec), spec,
                                       RunRequest(molecule=water, purpose=purpose, search_algorithm="crest"
                                                  if purpose == "search" else "jiggle-quench"))
    roundtrip = RunRequest.model_validate_json(request.model_dump_json())
    assert roundtrip.starting_geometries == request.starting_geometries
    assert roundtrip.search_algorithm == "jiggle-quench"
    assert roundtrip.metadata["external_starting_states"][0]["enumeration_policy"].startswith("explicit external")


def test_explicit_external_plan_does_not_generate_jiggles_or_launch_a_sampler(tmp_path, water):
    spec = specification(water)
    record = stage_external(NATIVE_GOAT, spec, RunRequest(molecule=water, n_candidates=999), tmp_path / "runs")
    workflow = Workflow(tmp_path / "runs", config=SystemConfig(execution_backend="development"))
    store = RunStore(tmp_path / "runs" / record.run_id)
    plan = workflow._sample_plan(record, store, 0, None)
    assert len(plan) == 1
    assert plan[0]["source"] == "EXTERNAL_START"
    assert not record.attempts
    assert "no new" in record.metadata["enumeration_scope"]


def test_cancellation_does_not_turn_imported_energy_into_completed_chemistry(tmp_path, water):
    record = stage_external(NATIVE_GOAT, specification(water), RunRequest(molecule=water), tmp_path / "runs")
    event = Event()
    event.set()
    result = execute_external(tmp_path / "runs" / record.run_id, cancel_event=event,
                              config=SystemConfig(execution_backend="development"))
    assert result.status == "cancelled" and not result.attempts and not result.candidates


@pytest.mark.parametrize("text", [
    "3\nEnergy -5.0\nO 0 0 0\nH .95 0 0\n",  # incomplete
    "3\nEnergy -5.0\nO 0 0 0\nH .95 0 0\nC -.24 .93 0\n",  # remapped composition
    "3\nEnergy nan\nO 0 0 0\nH .95 0 0\nH -.24 .93 0\n",
    "3\nEnergy -5.0\nO 0 0 0\nH nan 0 0\nH -.24 .93 0\n",
    "3\nEnergy -5.0\nO 0 0 0\nH 0 0 0\nH -.24 .93 0\n",  # collision
    "3\nEnergy -5.0\nO 0 0 0\nH 8 0 0\nH -.24 .93 0\n",  # topology broken
    "3\n-5.0 converged=false\nO 0 0 0\nH .95 0 0\nH -.24 .93 0\n",
])
def test_invalid_external_native_material_never_creates_a_run(tmp_path, water, text):
    path = tmp_path / "bad-goat.txt"
    path.write_text(text)
    with pytest.raises(ValueError):
        stage_external(path, specification(water), RunRequest(molecule=water), tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


def test_units_atom_order_and_source_engine_cannot_be_implicit_or_mismatched(water):
    spec = specification(water).model_dump(mode="json")
    for change in ({"energy_units": None}, {"energy_units": "kcal/mol"},
                   {"coordinate_units": "bohr"}, {"atom_order": list(reversed(water.atom_ids))},
                   {"engine": "crest"}, {"created_by": "   "}):
        with pytest.raises(ValueError):
            ExternalImportSpec.model_validate({**spec, "source": {**spec["source"], **change}})


def test_unsafe_and_oversized_material_is_rejected_without_archives_or_pickle(tmp_path, water):
    actual = tmp_path / "source.xyz"
    actual.write_text(to_xyz(water))
    symbolic = tmp_path / "link.xyz"
    symbolic.symlink_to(actual)
    with pytest.raises(ValueError, match="symlink"):
        preview_external(symbolic, geometry_spec(water))
    binary = tmp_path / "binary.txt"
    binary.write_bytes(b"3\x00binary")
    with pytest.raises(ValueError, match="NUL"):
        preview_external(binary, geometry_spec(water))
    oversized = tmp_path / "large.txt"
    with oversized.open("wb") as handle:
        handle.truncate(MAX_IMPORT_BYTES + 1)
    with pytest.raises(ValueError, match="bytes"):
        preview_external(oversized, geometry_spec(water))


@pytest.mark.parametrize("selection", [[], [0], [1, 1], [2], [True], ["1"], [1.0]])
def test_frame_selection_must_exist_and_be_explicit_unique(water, selection):
    with pytest.raises(ValueError):
        preview_external(NATIVE_GOAT, specification(water, selected_frames=selection))


def test_crest_reader_preserves_each_source_energy_without_ranking_or_culling(tmp_path, water):
    path = tmp_path / "crest_conformers.xyz"
    path.write_text(to_xyz(water, "-5.0 source=mtd1") + to_xyz(water, "-6.0 source=mtd2"))
    source = ExternalSource(engine="crest", engine_version="3.0.2", method="GFN2-xTB",
                            created_by="student", description="Format fixture only; never native calculation evidence",
                            atom_order=water.atom_ids, energy_units="hartree")
    spec = ExternalImportSpec(format="crest-ensemble", reference=water, source=source, selected_frames=[2, 1])
    preview = preview_external(path, spec)
    assert [f.observed_energy_hartree for f in preview.frames] == [-5.0, -6.0]
    request = prepare_external_request(preview, spec, RunRequest(molecule=water))
    assert request.n_candidates == 2
    assert request.metadata["external_starting_states"][0]["source_frames"] == [2, 1]
    record = stage_external(path, spec, RunRequest(molecule=water), tmp_path / "runs")
    workflow = Workflow(tmp_path / "runs", config=SystemConfig(execution_backend="development"))
    plan = workflow._sample_plan(record, RunStore(record.metadata["run_dir"]), 0, None)
    assert [p["source_frame"] for p in plan] == [2, 1]


@pytest.mark.parametrize("entrypoint,row,target", [
    ("topology-seeds", "T1-10s", "topology_seeds"),
    ("topology-seeds", "T1-1h", "topology_seeds"),
    ("topology-seeds", "T1-1mo", "topology_seeds"),
    ("leading-isomers", "T1-12h", "leading_isomers"),
    ("entropy-seeds", "T1-1d", "entropy_seeds"),
    ("ml-search-seeds", "T1-30min", "ml_search_seeds"),
    ("ml-search-seeds", "T1-1w", "ml_search_seeds"),
])
def test_named_matrix_entrypoints_use_real_format_readers_and_typed_inputs(tmp_path, water, entrypoint, row, target):
    path = tmp_path / "format-fixture-crest.xyz"
    frames = []
    for index in range(3):
        geometry = water.model_copy(deep=True)
        geometry.coordinates[1][0] += index * .002
        frames.append(to_xyz(geometry, f"{-5.0 + .001 * index} format-fixture-only"))
    path.write_text("".join(frames))
    source = ExternalSource(engine="crest", engine_version="3.0.2", method="GFN2-xTB",
                            created_by="student", description="Reader format fixture; no scientific energy claim",
                            atom_order=water.atom_ids, energy_units="hartree")
    spec = ExternalImportSpec(format="crest-ensemble", reference=water, source=source,
                              entrypoint=entrypoint)
    request = prepare_external_request(preview_external(path, spec), spec,
                                       RunRequest(molecule=water, purpose="matrix", matrix_row_id=row))
    assert len(request.matrix_inputs[target]) == 3
    assert not request.starting_geometries
    assert request.matrix_row_id == row
    with pytest.raises(ValueError, match="already exist"):
        prepare_external_request(preview_external(path, spec), spec, request)


def test_topology_entry_rejects_rigid_copies_as_distinct_topology_coverage(tmp_path, water):
    path = tmp_path / "not-independent.xyz"
    path.write_text(to_xyz(water, "-5.0") * 3)
    source = ExternalSource(engine="crest", engine_version="3.0.2", method="GFN2-xTB",
                            created_by="student", description="Repeated format fixture only",
                            atom_order=water.atom_ids, energy_units="hartree")
    spec = ExternalImportSpec(format="crest-ensemble", reference=water, source=source,
                              entrypoint="topology-seeds")
    with pytest.raises(ValueError, match="distinct"):
        prepare_external_request(preview_external(path, spec), spec,
                                 RunRequest(molecule=water, purpose="matrix", matrix_row_id="T1-10s"))


def test_stage_b_ensemble_enters_typed_matrix_input_and_preserves_requested_recipe(water):
    spec = specification(water, entrypoint="stage-b-ensemble")
    original = RunRequest(molecule=water, purpose="matrix", matrix_row_id="T1-3d")
    request = prepare_external_request(preview_external(NATIVE_GOAT, spec), spec, original)
    assert request.matrix_row_id == original.matrix_row_id
    assert len(request.matrix_inputs["stage_b_ensemble"]) == 1
    assert request.matrix_inputs["stage_b_ensemble"][0]["atom_ids"] == water.atom_ids
    assert request.matrix_inputs["goat_ensemble"] is None
    with pytest.raises(ValueError, match="applies only"):
        prepare_external_request(preview_external(NATIVE_GOAT, spec), spec,
                                 RunRequest(molecule=water, purpose="matrix", matrix_row_id="T5-10s"))


@pytest.mark.parametrize("row", ["T3O-1min", "T3O-3h"])
def test_two_independently_uploaded_monomers_are_ordered_by_the_declared_partition(tmp_path, water, row):
    second = water.model_copy(deep=True)
    second.atom_ids = ["second-O", "second-Ha", "second-Hb"]
    second.coordinates = [[x + 3, y, z] for x, y, z in water.coordinates]
    complex_molecule = Molecule(symbols=water.symbols + second.symbols,
                                coordinates=water.coordinates + second.coordinates,
                                atom_ids=water.atom_ids + second.atom_ids,
                                fragments=[[0, 1, 2], [3, 4, 5]],
                                fragment_states=[FragmentState(atom_indices=[0, 1, 2], charge=0, multiplicity=1),
                                                 FragmentState(atom_indices=[3, 4, 5], charge=0, multiplicity=1)])
    paths = []
    provenance = []
    for index, monomer in enumerate((second, water)):
        path = tmp_path / f"upload-{index}.xyz"
        path.write_text(to_xyz(monomer))
        spec = geometry_spec(monomer, entrypoint="isolated-monomers")
        if row == "T3O-3h":
            citation = f"parser-fixture-reference-{index}; not scientific evidence"
            spec.source.method = "fc-CCSD(T)/cc-pVTZ"
            spec.source.source_reference = citation
            provenance.append({"geometry_sha256": digest_json(monomer.model_dump(mode="json")),
                               "method": spec.source.method, "source": citation,
                               "evidence_kind": "cited-literature-geometry"})
        paths.append((path, spec))
    record = stage_external_many(paths, RunRequest(molecule=complex_molecule, purpose="matrix",
                                                 matrix_row_id=row,
                                                 matrix_inputs={"r2_monomer_provenance": provenance}), tmp_path / "runs")
    references = record.request.matrix_inputs["isolated_monomer_references"]
    assert [m["atom_ids"] for m in references] == [water.atom_ids, second.atom_ids]
    assert len(record.request.matrix_inputs["isolated_monomer_sources"]) == 2
    assert len([a for a in record.artifacts if a.role == "external-original-input"]) == 2
    assert not record.attempts
    if row == "T3O-3h":
        typed = record.request.matrix_inputs["r2_monomer_provenance"]
        assert [p["geometry_sha256"] for p in typed] == [digest_json(m) for m in references]


def test_r2_input_requires_a_matching_high_level_declaration_not_an_invented_label(tmp_path, water):
    from topos.fragments import split_fragments

    complex_molecule = Molecule(symbols=water.symbols * 2,
                                coordinates=water.coordinates + [[x + 3, y, z] for x, y, z in water.coordinates],
                                atom_ids=water.atom_ids + ["second-O", "second-Ha", "second-Hb"],
                                fragments=[[0, 1, 2], [3, 4, 5]],
                                fragment_states=[FragmentState(atom_indices=[0, 1, 2], charge=0, multiplicity=1),
                                                 FragmentState(atom_indices=[3, 4, 5], charge=0, multiplicity=1)])
    fragment = split_fragments(complex_molecule)[0]
    path = tmp_path / "ordinary-geometry.xyz"
    path.write_text(to_xyz(fragment))
    spec = geometry_spec(fragment, entrypoint="isolated-monomers")
    request = RunRequest(molecule=complex_molecule, purpose="matrix", matrix_row_id="T3O-3h",
                         matrix_inputs={"r2_monomer_provenance": [{
                             "geometry_sha256": digest_json(fragment.model_dump(mode="json")),
                             "method": "fc-CCSD(T)/cc-pVTZ", "source": "unit-format-fixture only",
                             "evidence_kind": "declared-calculation-reference"}]})
    with pytest.raises(ValueError, match="matching typed high-level"):
        prepare_external_request(preview_external(path, spec), spec, request)


def test_input_identity_cannot_be_changed_or_existing_starting_states_overwritten(water):
    spec = specification(water)
    preview = preview_external(NATIVE_GOAT, spec)
    other = water.model_copy(deep=True)
    other.atom_ids = ["wrong-O", "wrong-Ha", "wrong-Hb"]
    with pytest.raises(ValueError, match="different molecular"):
        prepare_external_request(preview, spec, RunRequest(molecule=other))
    prepared = prepare_external_request(preview, spec, RunRequest(molecule=water))
    with pytest.raises(ValueError, match="already exist"):
        prepare_external_request(preview, spec, prepared)
    geometry_specification = specification(water, entrypoint="geometry")
    with pytest.raises(ValueError, match="cannot silently replace or bypass"):
        prepare_external_request(preview_external(NATIVE_GOAT, geometry_specification),
                                 geometry_specification, prepared)
    with pytest.raises(ValidationError, match="preserve complete"):
        RunRequest(molecule=water, starting_geometries=[other])
    with pytest.raises(ValidationError, match="no native sampler"):
        RunRequest(molecule=water, starting_geometries=[water], search_algorithm="crest")


@pytest.mark.parametrize("malformed", ["prior-source", None, {}, ["prior-source"]])
def test_reserved_source_provenance_rejects_malformed_shapes_without_request_mutation(water, malformed):
    spec = specification(water)
    request = RunRequest(molecule=water, metadata={"external_starting_states": malformed})
    before = request.model_dump(mode="json")
    with pytest.raises(ValueError, match="list of structured"):
        prepare_external_request(preview_external(NATIVE_GOAT, spec), spec, request)
    assert request.model_dump(mode="json") == before


def test_cli_preview_and_queued_import_share_the_backend(tmp_path, water, capsys):
    spec = tmp_path / "spec.json"
    spec.write_text(specification(water).model_dump_json())
    request = tmp_path / "request.json"
    request.write_text(RunRequest(molecule=water, purpose="energy").model_dump_json())
    assert main(["external-preview", "--input", str(NATIVE_GOAT), "--spec", str(spec)]) == 0
    assert json.loads(capsys.readouterr().out)["frames"][0]["observed_energy_hartree"] == -76.4189354908
    assert main(["ingest", "--input", str(NATIVE_GOAT), "--spec", str(spec), "--request", str(request),
                 "--output-root", str(tmp_path / "runs")]) == 0
    staged = json.loads(capsys.readouterr().out)
    assert staged["status"] == "queued" and not staged["attempts"]


def test_pristine_hosted_import_serializes_all_frames_once_and_retains_original_bytes(tmp_path, water, monkeypatch):
    from topos import remote_workflow

    path = tmp_path / "student-combined-native-frames.txt"
    # Two unchanged retained native frames; this combination is an import
    # fixture, not a newly executed GOAT search or additional physics evidence.
    path.write_bytes(NATIVE_GOAT.read_bytes() + NATIVE_GOAT.read_bytes())
    config = SystemConfig(remote_repository="lab/student-controller")
    record = stage_external(path, specification(water),
                            RunRequest(molecule=water, calculation_environment="github-actions", purpose="energy"),
                            tmp_path / "runs")
    original_snapshot = RunStore(record.metadata["run_dir"]).snapshot_path()
    calls = []

    class UnavailableTransport:
        def dispatch_request(self, request, *, ref):
            calls.append(request.model_dump(mode="json"))
            return DispatchResult("topos_" + "a" * 32, "topos_compute.yml", config.remote_repository,
                                  request.model_dump(mode="json"), ref,
                                  request_sha256=digest_json(request.model_dump(mode="json")),
                                  base_commit=config.remote_base_commit,
                                  details="Transport unit fixture: no hosted job was submitted")

    monkeypatch.setattr(remote_workflow, "ActionDispatchClient", lambda **kwargs: UnavailableTransport())
    result = execute_external(record.metadata["run_dir"], config=config)
    assert result.status == "unavailable" and not result.attempts
    assert len(calls) == 1 and len(calls[0]["starting_geometries"]) == 2
    assert calls[0]["metadata"]["external_starting_states"][0]["source_sha256"] == file_digest(path)
    store = RunStore(record.metadata["run_dir"])
    assert (store.snapshot_path() / "artifacts/external-inputs/input-0001.txt").read_bytes() == path.read_bytes()
    assert original_snapshot.exists()
    assert execute_external(record.metadata["run_dir"], config=config).status == "unavailable"
    assert len(calls) == 1
    workflow = Workflow(tmp_path / "runs", config=config)
    with pytest.raises(IntegrityError, match="pristine"):
        remote_workflow.run_remote(workflow, record.request, staged_record=record)
    assert len(calls) == 1


def test_changed_import_manifest_is_rejected_before_hosted_submission(tmp_path, water, monkeypatch):
    from topos import remote_workflow

    record = stage_external(NATIVE_GOAT, specification(water),
                            RunRequest(molecule=water, calculation_environment="github-actions", purpose="energy"),
                            tmp_path / "runs")
    store = RunStore(record.metadata["run_dir"])
    manifest = store.snapshot_path() / "artifacts/external-inputs/manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b"changed")
    monkeypatch.setattr(remote_workflow, "ActionDispatchClient",
                        lambda **kwargs: pytest.fail("changed imported evidence attempted hosted transport"))
    with pytest.raises(IntegrityError, match="checksum"):
        execute_external(record.metadata["run_dir"], config=SystemConfig(remote_repository="lab/controller"))


def test_cli_execute_honestly_records_a_missing_engine_without_source_energy_substitution(tmp_path, water, capsys, monkeypatch):
    spec = tmp_path / "spec.json"
    spec.write_text(specification(water).model_dump_json())
    request = tmp_path / "request.json"
    request.write_text(RunRequest(molecule=water, purpose="energy").model_dump_json())
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"execution_backend": "development",
                                  "executables": {"xtb": str(tmp_path / "missing-native-xtb")}}))
    monkeypatch.setenv("TOPOS_CONFIG", str(config))
    assert main(["ingest", "--input", str(NATIVE_GOAT), "--spec", str(spec), "--request", str(request),
                 "--output-root", str(tmp_path / "runs"), "--execute"]) == 3
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "unavailable"
    assert record["attempts"][0]["engine"] == "xtb"
    assert record["candidates"][0]["energy_hartree"] is None


@pytest.mark.integration
@pytest.mark.parametrize("copies", [1, 2])
def test_real_xtb_calculates_imported_goat_geometry_at_its_new_level(tmp_path, water, copies):
    binary = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if not binary:
        pytest.skip("Authentic xTB is needed for current native refinement; no result is simulated")
    source = tmp_path / "retained-native-frames.txt"
    source.write_bytes(NATIVE_GOAT.read_bytes() * copies)
    staged = stage_external(source, specification(water),
                            RunRequest(molecule=water, purpose="energy", budget_seconds=60), tmp_path / "runs")
    result = execute_external(tmp_path / "runs" / staged.run_id,
                              config=SystemConfig(execution_backend="development", executables={"xtb": binary}))
    assert result.status == "completed", result.metadata.get("termination_reason")
    assert len(result.attempts) == copies and len(result.candidates) == copies
    eligible = [c for c in result.candidates if c.status == "eligible"]
    assert len(eligible) == 1
    candidate = eligible[0]
    attempt = next(a for a in result.attempts if a.attempt_id == candidate.attempt_id)
    assert attempt.metadata["execution_kind"] == "real"
    assert attempt.engine == "xtb" and attempt.method == "GFN2-xTB"
    assert candidate.energy_hartree is not None and candidate.energy_hartree != -76.4189354908
    assert candidate.sources == ["EXTERNAL_START"]
    assert any(a.role == "external-original-input" for a in result.artifacts)
    validate_scientific_candidate(result.model_dump(mode="json"), candidate.model_dump(mode="json"))
    if copies == 2:
        assert len([c for c in result.candidates if c.status == "duplicate"]) == 1
        assert all(a.engine == "xtb" and a.metadata["execution_kind"] == "real" for a in result.attempts)
    RunStore(tmp_path / "runs" / staged.run_id).verify()
