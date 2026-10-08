"""Actual browser/controller intake and dispatch contracts, not native science acceptance."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from topos.chemistry import to_xyz
from topos.models import Bond, Molecule, RunRequest
from topos.storage import IntegrityError, RunStore
from topos.ui import (
    base_actions_request_download,
    calculation_request_download,
    preview_uploaded_starting_state,
    stage_retained_starting_state,
    stage_uploaded_starting_states,
    structure_figure,
    verified_bundle_download,
)


def browser():
    testing = pytest.importorskip("streamlit.testing.v1")
    application = testing.AppTest.from_file(str(Path(__file__).resolve().parents[2] / "topos/streamlit_app.py"))
    application.run(timeout=30)
    assert not application.exception
    return application


def widget(application, kind, label):
    return next(item for item in getattr(application, kind) if item.label == label)


def water():
    return Molecule(symbols=["O", "H", "H"],
                    coordinates=[[0, 0, 0], [.7586, 0, .5043], [-.7586, 0, .5043]])


def import_spec(reference, *, entrypoint="refinement", format_name="goat-ensemble"):
    return {"format": format_name, "reference": reference.model_dump(mode="json"),
            "entrypoint": entrypoint, "source": {
                "engine": "orca", "engine_version": "6.1.1", "method": "declared external GOAT/XTB2",
                "created_by": "student contract fixture", "description": "Independent starting states; no native execution attestation",
                "coordinate_units": "angstrom", "energy_units": "hartree" if format_name != "xyz" else None,
                "atom_order": reference.atom_ids,
            }}


def goat_frames(reference):
    first = to_xyz(reference).splitlines()
    first[1] = "-5.000000 converged=true"
    displaced = reference.model_copy(deep=True)
    displaced.coordinates[1][0] += .01
    second = to_xyz(displaced).splitlines()
    second[1] = "-4.999999 converged=true"
    return ("\n".join([*first, *second]) + "\n").encode("utf-8")


def test_browser_reaches_every_compiled_topos_row():
    from topos.data.runtime_recipes import EXECUTABLE_ROWS

    app = browser()
    widget(app, "selectbox", "Purpose").select("matrix")
    app.run(timeout=30)
    found = set()
    purposes = widget(app, "selectbox", "Matrix scientific purpose").options
    for purpose in purposes:
        widget(app, "selectbox", "Matrix scientific purpose").select(purpose)
        app.run(timeout=30)
        tiers = widget(app, "selectbox", "Nominal matrix time tier").options
        for tier in tiers:
            widget(app, "selectbox", "Nominal matrix time tier").select(tier)
            app.run(timeout=30)
            tracks = widget(app, "selectbox", "Matrix engine track").options
            for track in tracks:
                widget(app, "selectbox", "Matrix engine track").select(track)
                app.run(timeout=30)
                assert not app.exception
                found.update(widget(app, "selectbox", "Executable matrix row").options)
    assert found == EXECUTABLE_ROWS


def test_browser_scan_controls_dispatch_exact_matrix_request(tmp_path):
    app = browser()
    widget(app, "selectbox", "Purpose").select("matrix")
    widget(app, "selectbox", "Calculation environment").select("github-actions")
    app.run(timeout=30)
    widget(app, "selectbox", "Matrix scientific purpose").select("potential-surface")
    app.run(timeout=30)
    assert widget(app, "selectbox", "Executable matrix row").value == "T2-10s"
    widget(app, "text_input", "Atom indices (zero based, comma separated)").set_value("0,1")
    widget(app, "text_input", "Scan targets (comma separated)").set_value("0.8,1.0")
    widget(app, "text_input", "Output directory").set_value(str(tmp_path / "matrix"))
    widget(app, "button", "Run requested calculation").click()
    app.run(timeout=30)
    job = app.session_state["topos_job"]
    assert job.done.wait(15) and job.error is None
    request = job.record.request
    assert request.matrix_row_id == "T2-10s" and request.matrix_product == "A"
    assert request.matrix_inputs["scan_coordinates"] == [
        {"kind": "distance", "atoms": [0, 1], "values": [.8, 1.0], "units": "angstrom"},
    ]
    assert job.record.status == "unavailable" and not job.record.attempts


def test_browser_rejects_malformed_scan_before_creating_a_job(tmp_path):
    app = browser()
    widget(app, "selectbox", "Purpose").select("matrix")
    app.run(timeout=30)
    widget(app, "selectbox", "Matrix scientific purpose").select("potential-surface")
    app.run(timeout=30)
    widget(app, "text_input", "Atom indices (zero based, comma separated)").set_value("0,0")
    widget(app, "text_input", "Scan targets (comma separated)").set_value("0.8")
    widget(app, "text_input", "Output directory").set_value(str(tmp_path / "invalid"))
    widget(app, "button", "Run requested calculation").click()
    app.run(timeout=30)
    assert not app.exception
    assert "topos_job" not in app.session_state
    assert any("distinct" in error.value for error in app.error)
    assert not (tmp_path / "invalid").exists()


def test_browser_requires_explicit_scientific_variant_before_submission(tmp_path):
    app = browser()
    widget(app, "selectbox", "Purpose").select("matrix")
    app.run(timeout=30)
    widget(app, "selectbox", "Matrix scientific purpose").select("equilibrium-geometry")
    app.run(timeout=30)
    widget(app, "selectbox", "Nominal matrix time tier").select("3h")
    app.run(timeout=30)
    assert widget(app, "selectbox", "Executable matrix row").value == "T3O-3h"
    widget(app, "text_input", "Output directory").set_value(str(tmp_path / "unresolved"))
    widget(app, "button", "Run requested calculation").click()
    app.run(timeout=30)
    assert not app.exception and "topos_job" not in app.session_state
    assert any("explicit reviewed scientific variant" in error.value for error in app.error)
    assert not (tmp_path / "unresolved").exists()


def test_browser_private_project_form_preserves_execution_authority_and_rejects_bad_pin():
    from topos.config import load_config

    original = load_config()
    app = browser()
    widget(app, "text_input", "Private calculation repository (OWNER/REPOSITORY)").set_value("student/project")
    widget(app, "text_input", "Calculation workflow branch or tag").set_value("reviewed-main")
    widget(app, "text_input", "BASE source commit (40 hexadecimal characters)").set_value("1" * 40)
    widget(app, "button", "Use calculation project").click()
    app.run(timeout=30)
    configured = app.session_state["topos_execution_config"]
    assert configured["remote_repository"] == "student/project"
    assert configured["remote_ref"] == "reviewed-main" and configured["remote_base_commit"] == "1" * 40
    assert configured["execution_backend"] == original.execution_backend
    assert configured["base_registry_path"] == original.model_dump(mode="json")["base_registry_path"]
    widget(app, "text_input", "BASE source commit (40 hexadecimal characters)").set_value("latest")
    widget(app, "button", "Use calculation project").click()
    app.run(timeout=30)
    assert not app.exception and app.error
    assert app.session_state["topos_execution_config"] == configured


def test_browser_xyz_state_forms_export_exact_request_without_starting_engines(tmp_path):
    app = browser()
    widget(app, "selectbox", "Purpose").select("energy")
    widget(app, "selectbox", "Molecular input").select("XYZ with explicit chemical state")
    app.run(timeout=30)
    widget(app, "number_input", "Molecular charge").set_value(1)
    widget(app, "number_input", "Spin multiplicity").set_value(2)
    widget(app, "text_input", "Output directory").set_value(str(tmp_path / "export-only"))
    widget(app, "button", "Validate calculation request for BASE Actions").click()
    app.run(timeout=30)
    assert not app.exception
    payload = json.loads(calculation_request_download(app.session_state["topos_export_request"]))
    assert payload["purpose"] == "energy" and payload["engine"] == "xtb" and payload["method"] == "GFN2-xTB"
    assert payload["molecule"]["charge"] == 1 and payload["molecule"]["multiplicity"] == 2
    assert "topos_job" not in app.session_state
    assert not (tmp_path / "export-only").exists()
    assert len(app.get("download_button")) >= 1


def test_explicit_base_actions_export_changes_only_execution_target_and_provenance():
    from topos.storage import digest_json

    request = RunRequest(molecule=water(), calculation_environment="github-actions", purpose="optimize")
    original = request.model_dump(mode="json")
    canonical = json.loads(calculation_request_download(request))
    exported = json.loads(base_actions_request_download(request))
    assert canonical == original and request.model_dump(mode="json") == original
    assert exported["calculation_environment"] == "local"
    provenance = exported["metadata"].pop("base_actions_export")
    assert provenance["original_request_sha256"] == digest_json(original)
    assert provenance["original_calculation_environment"] == "github-actions"
    exported["calculation_environment"] = original["calculation_environment"]
    assert exported == original
    request.device = "gpu"
    with pytest.raises(ValueError, match="hosted CPU profile"):
        base_actions_request_download(request)


def test_upload_controller_preserves_all_external_frames_without_native_success(tmp_path):
    reference = water()
    data = goat_frames(reference)
    spec = import_spec(reference)
    preview = preview_uploaded_starting_state(data, spec)
    assert len(preview.frames) == 2
    assert preview.validation_status == "requires-real-calculation"
    request = RunRequest(molecule=reference, purpose="optimize")
    queued = stage_uploaded_starting_states([{"data": data, "specification": spec}], request, tmp_path)
    store = RunStore(tmp_path / queued.run_id)
    record = store.load()
    assert queued.status == "queued" and not queued.attempts and not queued.candidates
    assert len(queued.request.starting_geometries) == 2
    assert record["metadata"]["external_import"]["validation_status"] == "requires-real-calculation"
    original = [item for item in record["artifacts"] if item["role"] == "external-original-input"]
    assert len(original) == 1
    assert (store.snapshot_path() / "artifacts" / original[0]["path"]).read_bytes() == data


@pytest.mark.parametrize("data", [b"", b"PK\x03\x04archive", b"3\ntruncated\nO 0 0 0\n"])
def test_upload_controller_rejects_invalid_bytes_without_a_run(tmp_path, data):
    with pytest.raises(ValueError):
        stage_uploaded_starting_states([{"data": data, "specification": import_spec(water())}],
                                      RunRequest(molecule=water()), tmp_path / "runs")
    assert not list((tmp_path / "runs").glob("run_*"))


def test_browser_external_preview_selection_reaches_real_remote_rejection(tmp_path):
    """AppTest lacks file-uploader input; use its real bounded byte controller for preview."""
    app = browser()
    widget(app, "selectbox", "Purpose").select("optimize")
    widget(app, "selectbox", "Calculation environment").select("github-actions")
    widget(app, "text_input", "Output directory").set_value(str(tmp_path / "external"))
    widget(app, "button", "Prepare request for external starting states").click()
    app.run(timeout=30)
    assert not app.exception
    reference = Molecule.model_validate(app.session_state["topos_prepared_request"]["molecule"])
    data = goat_frames(reference)
    specification = import_spec(reference)
    preview = preview_uploaded_starting_state(data, specification)
    app.session_state["topos_upload_preview"] = {
        "data": data, "specification": specification, "preview": preview.model_dump(mode="json"),
    }
    app.run(timeout=30)
    widget(app, "multiselect", "Frames to ingest (one based)").set_value([2])
    widget(app, "button", "Add selected frames to intake").click()
    app.run(timeout=30)
    widget(app, "button", "Run calculation from imported starting states").click()
    app.run(timeout=30)
    assert not app.exception
    job = app.session_state["topos_job"]
    assert job.done.wait(15) and job.error is None
    assert job.record.status == "unavailable" and not job.record.attempts
    assert len(job.record.request.starting_geometries) == 1
    assert job.record.request.molecule == preview.frames[1].molecule
    assert job.record.request.metadata["external_starting_states"][0]["source_frames"] == [2]


def test_browser_imported_request_export_preserves_selection_and_original_bytes(tmp_path):
    app = browser()
    widget(app, "selectbox", "Purpose").select("optimize")
    widget(app, "text_input", "Output directory").set_value(str(tmp_path / "imported-export"))
    widget(app, "button", "Prepare request for external starting states").click()
    app.run(timeout=30)
    reference = Molecule.model_validate(app.session_state["topos_prepared_request"]["molecule"])
    data = goat_frames(reference)
    specification = import_spec(reference)
    preview = preview_uploaded_starting_state(data, specification, "specialized-goat.xyz")
    app.session_state["topos_upload_preview"] = {
        "data": data, "filename": "specialized-goat.xyz", "specification": specification,
        "preview": preview.model_dump(mode="json"),
    }
    app.run(timeout=30)
    widget(app, "multiselect", "Frames to ingest (one based)").set_value([2, 1])
    widget(app, "button", "Add selected frames to intake").click()
    app.run(timeout=30)
    widget(app, "button", "Prepare imported request for BASE Actions").click()
    app.run(timeout=30)
    assert not app.exception
    request = RunRequest.model_validate(json.loads(calculation_request_download(app.session_state["topos_export_request"])))
    assert request.starting_geometries == [preview.frames[1].molecule, preview.frames[0].molecule]
    assert request.metadata["external_starting_states"][0]["source_frames"] == [2, 1]
    store = RunStore(Path(app.session_state["topos_external_export_run"]))
    record = store.load()
    assert record["status"] == "queued" and not record["attempts"] and not record["candidates"]
    original = next(item for item in record["artifacts"] if item["role"] == "external-original-input")
    assert (store.snapshot_path() / "artifacts" / original["path"]).read_bytes() == data
    assert "topos_job" not in app.session_state
    # A second ordinary validation with the same visible controls must not replace
    # the imported download while its durable source still contains two frames.
    imported_path = app.session_state["topos_external_export_run"]
    widget(app, "button", "Validate calculation request for BASE Actions").click()
    app.run(timeout=30)
    assert not app.exception
    assert not app.session_state["topos_export_request"]["starting_geometries"]
    assert app.session_state["topos_external_export_run"] == imported_path
    retained_export = app.session_state["topos_external_export_request"]
    assert retained_export == store.load()["request"]
    assert len(json.loads(calculation_request_download(retained_export))["starting_geometries"]) == 2


def test_retained_starting_state_creates_new_unexecuted_run_with_independent_budget(tmp_path):
    from test_storage_publication import reviewed

    source = tmp_path / "run"
    record, _ = reviewed(source)
    snapshot = RunStore(source).verify()
    staged = stage_retained_starting_state(source, record.candidates[0].candidate_id,
        actor="student", reason="Continue from an independently retained geometry", budget_seconds=123.)
    assert staged.run_id != record.run_id and staged.status == "queued"
    assert not staged.attempts and not staged.candidates
    assert staged.request.budget_seconds == 123.
    origin = staged.request.metadata["retained_starting_state"]
    assert origin["source_run_id"] == record.run_id
    assert origin["source_snapshot_sha256"] == snapshot["snapshot_id"]
    assert staged.request.molecule == record.candidates[0].molecule
    assert RunStore(source).verify() == snapshot


def test_retained_matrix_seed_channel_cannot_silently_replay_previous_ensemble(tmp_path):
    from test_storage_publication import make_record

    source = tmp_path / "run"
    record = make_record(source)
    record.request.purpose = "matrix"
    record.request.matrix_row_id = "T1-3d"
    record.request.matrix_inputs = {"stage_b_ensemble": [record.request.molecule.model_dump(mode="json")]}
    RunStore(source).commit(record)
    with pytest.raises(ValueError, match="explicit seed or ensemble"):
        stage_retained_starting_state(source, record.candidates[0].candidate_id,
            actor="student", reason="Continue a particular frame", budget_seconds=123.)
    assert len(list(tmp_path.glob("run*"))) == 1


def test_structure_figure_keeps_atom_mapping_geometry_and_only_declared_bonds():
    pytest.importorskip("plotly")
    molecule = water()
    molecule.bonds = [Bond(atom1=0, atom2=1)]
    figure = structure_figure(molecule)
    assert len(figure.data) == 2
    assert list(figure.data[-1].x) == [point[0] for point in molecule.coordinates]
    assert list(figure.data[-1].z) == [point[2] for point in molecule.coordinates]
    assert molecule.atom_ids[1] in figure.data[-1].text[1]
    assert list(figure.data[0].x) == [molecule.coordinates[index][0] for index in [0, 1]]
    assert figure.layout.scene.xaxis.title.text == "x (Å)"


def test_verified_browser_archive_contains_exact_reproducible_membership(tmp_path):
    from test_storage_publication import reviewed

    from topos.publication import export_bundle

    run = tmp_path / "run"
    reviewed(run)  # Genuine analytical child-process fixture; not a licensed engine claim.
    bundle = tmp_path / "bundle"
    manifest = export_bundle(run, bundle)
    archive = verified_bundle_download(bundle)
    with zipfile.ZipFile(io.BytesIO(archive)) as handle:
        assert set(handle.namelist()) == {"manifest.json", *(item["path"] for item in manifest["files"])}
        assert json.loads(handle.read("manifest.json")) == manifest
        assert handle.read("regenerate.py") == (bundle / "regenerate.py").read_bytes()
    (bundle / "selected.csv").write_text("corrupted scientific result")
    with pytest.raises(IntegrityError):
        verified_bundle_download(bundle)


def test_browser_review_renders_mapped_structures_and_serves_verified_export(tmp_path):
    pytest.importorskip("plotly")
    from test_storage_publication import reviewed

    from topos.publication import verify_bundle

    run = tmp_path / "run"
    record, _ = reviewed(run)
    before = RunStore(run).verify()
    app = browser()
    widget(app, "text_input", "Run directory").set_value(str(run))
    app.run(timeout=30)
    assert not app.exception
    assert len(app.get("plotly_chart")) == 2  # Input and selected candidate, actual mapped geometry.
    assert widget(app, "button", "Resume saved calculation").disabled
    bundle = tmp_path / "download"
    widget(app, "text_input", "Local bundle folder").set_value(str(bundle))
    widget(app, "button", "Create local publication archive").click()
    app.run(timeout=30)
    assert not app.exception
    assert verify_bundle(bundle)["run_id"] == record.run_id
    assert app.session_state["topos_publication_bundle"]["path"] == str(bundle)
    assert len(app.get("download_button")) == 1
    assert RunStore(run).verify() == before


def test_browser_saved_run_resume_retries_original_request_without_creating_new_run(tmp_path):
    from topos.workflow import Workflow

    output = tmp_path / "runs"
    record = Workflow(output).run(RunRequest(molecule=water(), calculation_environment="github-actions"))
    assert record.status == "unavailable" and not record.attempts
    app = browser()
    widget(app, "text_input", "Run directory").set_value(str(output / record.run_id))
    app.run(timeout=30)
    widget(app, "button", "Resume saved calculation").click()
    app.run(timeout=30)
    job = app.session_state["topos_job"]
    assert job.done.wait(15) and job.error is None
    assert job.record.run_id == record.run_id
    assert job.record.request == record.request
    assert job.record.status == "unavailable"
    assert len(list(output.glob("run_*"))) == 1
