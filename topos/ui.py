"""Shared BASE/UI submission contract and an optional Streamlit interface.

Importing this module does not launch a server, read credentials, submit jobs,
create files, or execute chemistry. Every adapter uses the same RunRequest and
Workflow, including exact selections for environment, engine, method and budget.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from topos.models import Molecule, RunRecord, RunRequest


def _error_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
    return str(exc)


def _parse_json(text: str) -> Any:
    """Parse strict JSON without silent duplicate-key or nonfinite-value coercion."""
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate request key: {key}")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError(f"Nonfinite JSON value is invalid: {value}")

    return json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)


def parse_request_json(text: str) -> RunRequest:
    """Parse the identical typed request used by every public interface."""
    value = _parse_json(text)
    if not isinstance(value, dict):
        raise ValueError("A run request must be a JSON object")
    return RunRequest.model_validate(value)


def submit_request(
    request: RunRequest | dict[str, Any],
    output_root: Path | str,
    *,
    cancel_event: threading.Event | None = None,
    config: Any = None,
) -> RunRecord:
    """Submit an explicit request from BASE, the CLI, a notebook, or the browser."""
    from topos.workflow import Workflow

    values = request.model_dump(mode="json") if isinstance(request, RunRequest) else request
    validated = RunRequest.model_validate(values)
    return Workflow(Path(output_root), config=config).run(validated, cancel_event=cancel_event)


@dataclass
class _UIJob:
    """Only runtime state; persisted scientific records remain in RunStore."""

    cancel_event: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    record: Any = None
    error: str | None = None


def _execute_ui_job(
    job: _UIJob, request: RunRequest, output_root: Path, run_dir: Path | None = None,
    config: Any = None, external: bool = False,
) -> None:
    try:
        if run_dir is None:
            job.record = submit_request(request, output_root, cancel_event=job.cancel_event, config=config)
        elif external:
            from topos.ingestion import execute_external

            job.record = execute_external(run_dir, cancel_event=job.cancel_event, config=config)
        else:
            from topos.workflow import Workflow

            job.record = Workflow(output_root, config=config).resume(run_dir, cancel_event=job.cancel_event)
    except Exception as exc:
        job.error = f"{type(exc).__name__}: {_error_message(exc)}"
    finally:
        job.done.set()


def _start_job(
    st: Any, request: RunRequest, output_root: Path, run_dir: Path | None = None,
    *, config: Any = None, external: bool = False,
) -> None:
    from topos.config import SystemConfig

    selected = config if config is not None else st.session_state.get("topos_execution_config")
    validated = SystemConfig.model_validate(selected) if selected is not None else None
    job = _UIJob()
    st.session_state["topos_job"] = job
    threading.Thread(target=_execute_ui_job, args=(job, request, output_root, run_dir, validated, external),
                     daemon=True, name="topos-ui-workflow").start()


def _execution_configuration_panel(st: Any) -> None:
    from topos.config import SystemConfig, load_config

    configured = st.session_state.get("topos_execution_config") or load_config().model_dump(mode="json")
    with st.expander("GitHub Actions calculation project", expanded=False):
        st.caption("Select the student's private calculation repository and the explicit BASE source revision. Authentication is supplied by the BASE/Codespaces runtime; no credential belongs in this form.")
        with st.form("topos_execution_configuration"):
            repository = st.text_input("Private calculation repository (OWNER/REPOSITORY)",
                                       value=configured.get("remote_repository") or "", key="topos_project_repository")
            ref = st.text_input("Calculation workflow branch or tag", value=configured["remote_ref"], key="topos_project_ref")
            base_commit = st.text_input("BASE source commit (40 hexadecimal characters)",
                                        value=configured["remote_base_commit"], key="topos_project_base_commit")
            if st.form_submit_button("Use calculation project"):
                try:
                    if repository and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
                        raise ValueError("Calculation repository must use OWNER/REPOSITORY")
                    if not ref.strip() or any(ord(character) < 33 for character in ref):
                        raise ValueError("Calculation workflow ref must be a branch or tag without whitespace")
                    settings = SystemConfig.model_validate({**configured,
                        "remote_repository": repository or None, "remote_ref": ref,
                        "remote_base_commit": base_commit})
                    st.session_state["topos_execution_config"] = settings.model_dump(mode="json")
                    st.success("Calculation project selected. Prepare an external request again to bind the updated project.")
                except (ValueError, OSError) as exc:
                    st.error(_error_message(exc))


def _workstation_configuration_panel(st: Any) -> None:
    from topos.config import SystemConfig, load_config

    configured = st.session_state.get("topos_execution_config") or load_config().model_dump(mode="json")
    with st.expander("Lab workstation (Drive folder queue)", expanded=False):
        st.caption("Calculations sent to the lab workstation are deposited in the Google Drive folder you assign; "
                   "the workstation runs them when its owner is not using the machine and returns the results there. "
                   "Use a folder synced by Google Drive for desktop, or a drive.google.com folder link (Codespaces). "
                   "Leave empty to use the folder assigned in CoChem-BASE.")
        with st.form("topos_workstation_configuration"):
            folder = st.text_input("Workstation Drive folder", value=configured.get("workstation_folder") or "",
                                   key="topos_workstation_folder")
            student = st.text_input("Student ID", value=configured.get("workstation_student_id") or "",
                                    key="topos_workstation_student")
            keys = st.text_input("Workstation key", value=", ".join(configured.get("workstation_trusted_keys") or []),
                                 key="topos_workstation_keys",
                                 help="Fingerprint from the workstation owner (cochem-runner key). Only results "
                                      "signed by a key you trust are imported.")
            if st.form_submit_button("Use this workstation folder"):
                try:
                    from topos.workstation import _key_fingerprints
                    settings = SystemConfig.model_validate({**configured, "workstation_folder": folder.strip() or None,
                                                            "workstation_student_id": student.strip() or None,
                                                            "workstation_trusted_keys": _key_fingerprints(keys)})
                    if settings.workstation_folder and settings.workstation_student_id:
                        from topos.workstation import open_transport
                        open_transport(settings.workstation_folder, settings.workstation_student_id).ensure(
                            settings.workstation_student_id)
                    st.session_state["topos_execution_config"] = settings.model_dump(mode="json")
                    st.success("Workstation folder selected. Choose the 'workstation' calculation environment to use it.")
                except (ValueError, OSError, RuntimeError) as exc:
                    st.error(_error_message(exc))


def _show_workstation_status(st: Any, record: dict[str, Any]) -> None:
    dispatch = record.get("metadata", {}).get("workstation_dispatch") or {}
    if record.get("metadata", {}).get("execution_kind") != "workstation-request" or not dispatch:
        return
    host = dispatch.get("workstation") or "the lab workstation"
    st.info(f"Queued to {host}. This job uses the workstation's extended resources; you can close this window "
            "and check back later - the job keeps its place and pauses automatically while the workstation "
            "owner uses the machine.")
    state = dispatch.get("state", "SUBMITTED")
    st.write(f"Workstation state: **{state}** - {dispatch.get('message', '')}")
    if dispatch.get("queue_position"):
        st.caption(f"Position in the workstation queue: {dispatch['queue_position']}")
    if dispatch.get("repairs"):
        st.caption("Adjusted by the workstation: " + "; ".join(dispatch["repairs"]))
    progress = {key: value for key, value in (dispatch.get("progress") or {}).items() if not key.startswith("_")}
    if progress:
        st.caption("Progress: " + ", ".join(f"{key} = {value}" for key, value in progress.items()))
    if dispatch.get("output_tail"):
        with st.expander("Latest workstation output"):
            st.code("\n".join(dispatch["output_tail"]))
    run_dir = record.get("metadata", {}).get("run_dir")
    current = st.session_state.get("topos_job")
    if run_dir and st.button("Check the workstation now", key=f"workstation-refresh-{record['run_id']}",
                             disabled=current is not None and not current.done.is_set()):
        _start_job(st, RunRequest.model_validate(record["request"]), Path(run_dir).parent, Path(run_dir))


def _matrix_calculation_panel(st: Any) -> tuple[str, dict[str, Any], str]:
    """Choose an actual compiled row without inferring chemistry from a budget."""
    from topos.data.reviewed_matrix_v010 import RECIPES
    from topos.data.runtime_recipes import EXECUTABLE_ROWS
    from topos.method_matrix import TIERS, load_catalog, resolved_recipe

    catalog = load_catalog()
    rows = [row for row in catalog.rows if row.owner == "TOPOS" and row.row_id in EXECUTABLE_ROWS]
    scientific_purpose = st.selectbox("Matrix scientific purpose", list(dict.fromkeys(row.purpose for row in rows)))
    purpose_rows = [row for row in rows if row.purpose == scientific_purpose]
    tiers = [tier for tier in TIERS if any(row.tier == tier for row in purpose_rows)]
    tier = st.selectbox("Nominal matrix time tier", tiers,
                        help="This selects a method recipe. Set the actual workflow deadline separately.")
    tier_rows = [row for row in purpose_rows if row.tier == tier]
    track = st.selectbox("Matrix engine track", list(dict.fromkeys(row.track for row in tier_rows)))
    choices = [row for row in tier_rows if row.track == track]
    row_id = st.selectbox("Executable matrix row", [row.row_id for row in choices])
    row = catalog.get(row_id)
    st.caption("Archived matrix definition: " + row.method_text)
    st.caption(f"{row.row_id}: {row.delivers}. Domain: {row.chemical_domain}.")
    st.caption("A compiled recipe still requires real installed engines and valid scientific inputs; its native execution records those checks.")
    settings: dict[str, Any] = {"matrix_product": row.product or "A"}
    variants = [name for name, recipe in RECIPES.items() if recipe["row_id"] == row_id]
    if row_id == "T5-30min":
        variants = ["native-composite-rawinteraction-v1"]
    if variants:
        settings["_variant_required"] = True
        resolution = st.selectbox("Reviewed scientific variant", ["Choose explicitly", *variants],
                                  help="Read the differences before choosing; no scientific variant is selected automatically.")
        if resolution != "Choose explicitly":
            settings["source_resolution"] = resolution
            if resolution in RECIPES:
                st.json(RECIPES[resolution], expanded=False)
    steps, required = resolved_recipe(row, settings.get("source_resolution"))
    if not variants or settings.get("source_resolution"):
        st.write("Selected calculation recipe")
        st.dataframe([{"operation": step.operation, "engine": step.engine, "method": step.method,
                       "basis": step.basis} for step in steps], hide_index=True, use_container_width=True)
    st.write("Required scientific inputs: " + ", ".join(required))
    st.caption("Use External starting states to import mapped geometries and ensembles into these inputs. Complete basis, derivative, model and provenance protocols remain explicit.")
    if row_id in {"T2-10s", "T2-30min", "T2-1h"}:
        coordinates = []
        for index in range(2 if row_id == "T2-1h" else 1):
            with st.expander(f"Relaxed scan coordinate {index + 1}", expanded=True):
                kind = st.selectbox("Coordinate kind", ["distance", "angle", "dihedral"], key=f"scan_kind_{index}")
                atoms = st.text_input("Atom indices (zero based, comma separated)", key=f"scan_atoms_{index}")
                targets = st.text_input("Scan targets (comma separated)", key=f"scan_targets_{index}")
                if atoms.strip() or targets.strip():
                    coordinates.append({"kind": kind, "atoms": atoms, "values": targets,
                                        "units": "angstrom" if kind == "distance" else "degree"})
        settings["scan_coordinates"] = coordinates
    text = st.text_area("Matrix scientific inputs (JSON object)", value="{}",
                        help="Advanced typed recipe protocols. Entries must not override the visible scientific variant or scan controls.")
    with st.expander("Scientific input schema"):
        from topos.matrix_workflow import MatrixInputs

        st.json(MatrixInputs.model_json_schema())
    return row_id, settings, text


def _matrix_control_inputs(settings: dict[str, Any], text: str) -> dict[str, Any]:
    """Normalize form values with the same typed scientific-input contract as execution."""
    from topos.matrix_workflow import MatrixInputs

    values = _parse_json(text)
    if not isinstance(values, dict):
        raise ValueError("Matrix scientific inputs must be a JSON object")
    if settings.get("_variant_required") and not settings.get("source_resolution"):
        raise ValueError("Select an explicit reviewed scientific variant before preparing or submitting this row")
    controls = {name: value for name, value in settings.items() if name not in {"matrix_product", "_variant_required"}}
    if values.keys() & controls.keys():
        raise ValueError("Advanced matrix inputs must not override visible scientific controls")
    if "scan_coordinates" in controls:
        normalized = []
        for coordinate in controls["scan_coordinates"]:
            normalized.append({**coordinate,
                "atoms": [int(value.strip()) for value in coordinate["atoms"].split(",")],
                "values": [float(value.strip()) for value in coordinate["values"].split(",")],
            })
        controls["scan_coordinates"] = normalized
    return MatrixInputs.model_validate({**values, **controls}).model_dump(mode="json", exclude_defaults=True)


def calculation_request_download(request: RunRequest | dict[str, Any]) -> bytes:
    """Export the same revalidated contract that BASE's TOPOS executor consumes."""
    value = request.model_dump(mode="json") if isinstance(request, RunRequest) else request
    validated = parse_request_json(json.dumps(value, allow_nan=False))
    return (json.dumps(validated.model_dump(mode="json"), ensure_ascii=False,
                       sort_keys=True, allow_nan=False, indent=2) + "\n").encode("utf-8")


def base_actions_request_download(request: RunRequest | dict[str, Any]) -> bytes:
    """Explicitly target native local execution inside BASE's private Actions runner."""
    from topos.storage import digest_json

    original = json.loads(calculation_request_download(request))
    validated = RunRequest.model_validate(original)
    if validated.device != "cpu" or validated.threads > 2 or validated.memory_mb > 4096:
        raise ValueError("The BASE hosted CPU profile requires device=cpu, at most 2 threads and 4096 MB; retain other allocations for an appropriate local/HPC/GPU worker")
    values = {**original, "calculation_environment": "local"}
    values["metadata"] = {**original["metadata"], "base_actions_export": {
        "original_calculation_environment": original["calculation_environment"],
        "original_request_sha256": digest_json(original),
        "worker_calculation_environment": "local",
        "delivery": "explicit export for CoChem-BASE private Actions runner",
    }}
    return calculation_request_download(values)


def _download_calculation_request(st: Any, request: dict[str, Any], *, key: str) -> None:
    st.download_button("Download validated calculation request", calculation_request_download(request),
                       file_name="topos-request.json", mime="application/json", key=key)
    st.caption("The canonical request preserves the selected chemistry, entry step and calculation environment. Engine availability and scientific completion are checked during execution.")
    try:
        native_request = base_actions_request_download(request)
    except ValueError as exc:
        st.info(_error_message(exc))
    else:
        st.download_button("Download request for BASE private Actions runner", native_request,
                           file_name="topos-base-actions-request.json", mime="application/json", key=key + "-base-actions")
        st.caption("This explicit export targets native local execution inside BASE's private Actions runner, preserving the chemistry and recording the original selected environment. Commit it to the private project and submit BASE's TOPOS calculation workflow with its separate licensed-engine staging receipts.")


def _molecule_input_panel(st: Any) -> dict[str, Any]:
    mode = st.selectbox("Molecular input", ["Molecule JSON", "XYZ with explicit chemical state"])
    if mode == "Molecule JSON":
        return {"mode": mode, "text": st.text_area(
            "Molecule JSON (explicit atoms, coordinates in angstrom, charge, multiplicity and optional state)",
            value=json.dumps({"symbols": ["O", "H", "H"], "coordinates": [[0, 0, 0], [.7586, 0, .5043], [-.7586, 0, .5043]],
                              "charge": 0, "multiplicity": 1}, indent=2), height=220)}
    first, second = st.columns(2)
    with first:
        charge = st.number_input("Molecular charge", value=0, step=1)
    with second:
        multiplicity = st.number_input("Spin multiplicity", min_value=1, value=1, step=1)
    upload = st.file_uploader("Drop a starting XYZ geometry", type=["xyz"])
    text = st.text_area("XYZ geometry (angstrom)", value="3\nDeclared geometry\nO 0 0 0\nH .7586 0 .5043\nH -.7586 0 .5043\n")
    groups = ""
    fragment_states = []
    if st.checkbox("Declare separate complex fragments"):
        groups = st.text_input("Fragment atom-index groups (semicolon separated)",
                               help="Use zero-based indices, for example 0,1,2;3,4,5. Every atom must belong to exactly one declared fragment.")
        for index, group in enumerate(part.strip() for part in groups.split(";") if part.strip()):
            st.write(f"Fragment {index + 1}: atoms {group}")
            fragment_states.append({
                "atom_indices": group,
                "charge": st.number_input("Fragment charge", value=0, step=1, key=f"xyz_fragment_charge_{index}"),
                "multiplicity": st.number_input("Fragment spin multiplicity", min_value=1, value=1, step=1,
                                                key=f"xyz_fragment_multiplicity_{index}"),
            })
    advanced = st.text_area("Atom mapping, isotopes, bonds, stereochemistry and environment (JSON object)", value="{}",
                           help="Optional fields: atom_ids, isotopes, bonds, stereochemistry, environment and name. Explicit state and geometry controls cannot be overridden.")
    return {"mode": mode, "upload": upload, "text": text, "charge": charge,
            "multiplicity": multiplicity, "fragment_states": fragment_states, "advanced": advanced}


def molecule_from_controls(controls: dict[str, Any]) -> dict[str, Any]:
    if controls["mode"] == "Molecule JSON":
        return Molecule.model_validate(_parse_json(controls["text"])).model_dump(mode="json")
    from topos.chemistry import from_xyz
    from topos.ingestion import MAX_IMPORT_BYTES

    upload = controls.get("upload")
    if upload is not None:
        if upload.size > MAX_IMPORT_BYTES:
            raise ValueError("Starting geometries must be at most 64 MiB")
        try:
            text = upload.getvalue().decode("utf-8")
        except UnicodeError as exc:
            raise ValueError("Starting XYZ geometry must be UTF-8 text") from exc
    else:
        text = controls["text"]
    geometry = from_xyz(text, charge=controls["charge"], multiplicity=controls["multiplicity"])
    values = geometry.model_dump(mode="json")
    state = []
    for fragment in controls["fragment_states"]:
        state.append({**fragment, "atom_indices": [int(value.strip()) for value in fragment["atom_indices"].split(",")]})
    values.update(fragments=[fragment["atom_indices"] for fragment in state], fragment_states=state)
    advanced = _parse_json(controls["advanced"])
    if not isinstance(advanced, dict) or set(advanced) - {"atom_ids", "isotopes", "bonds", "stereochemistry", "environment", "name"}:
        raise ValueError("Advanced molecular input may contain only atom_ids, isotopes, bonds, stereochemistry, environment or name")
    return Molecule.model_validate({**values, **advanced}).model_dump(mode="json")


def _upload_filename(value: str) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value or "\\" in value or any(ord(char) < 32 for char in value):
        raise ValueError("An upload filename must be a plain file name without directories")
    return value


def preview_uploaded_starting_state(
    data: bytes, specification: dict[str, Any], filename: str = "external.xyz",
) -> Any:
    """Preview bounded upload bytes through the canonical chemistry importer."""
    from topos.ingestion import MAX_IMPORT_BYTES, ExternalImportSpec, preview_external

    if not isinstance(data, bytes) or not data or len(data) > MAX_IMPORT_BYTES:
        raise ValueError(f"Upload must contain 1–{MAX_IMPORT_BYTES} bytes")
    spec = ExternalImportSpec.model_validate(specification)
    with tempfile.TemporaryDirectory(prefix="cochem-topos-upload-") as directory:
        path = Path(directory) / _upload_filename(filename)
        path.write_bytes(data)
        return preview_external(path, spec)


def stage_uploaded_starting_states(
    uploads: list[dict[str, Any]], request: RunRequest, output_root: Path,
) -> RunRecord:
    """Persist original files and typed entry steps before the normal workflow resumes."""
    from topos.ingestion import MAX_IMPORT_BYTES, ExternalImportSpec, stage_external_many

    total = sum(len(item["data"]) + sum(len(support["data"]) for support in item.get("supporting_files", [])) for item in uploads)
    if not uploads or total > MAX_IMPORT_BYTES:
        raise ValueError(f"The intake requires files totalling at most {MAX_IMPORT_BYTES} bytes")
    with tempfile.TemporaryDirectory(prefix="cochem-topos-intake-") as directory:
        entries = []
        supporting_paths = []
        for index, item in enumerate(uploads):
            data = item["data"]
            if not isinstance(data, bytes) or not data:
                raise ValueError("Each starting-state upload must contain bytes")
            spec = ExternalImportSpec.model_validate(item["specification"])
            item_root = Path(directory) / str(index)
            item_root.mkdir()
            path = item_root / _upload_filename(item.get("filename", "external.xyz"))
            path.write_bytes(data)
            entries.append((path, spec))
            for support_index, support in enumerate(item.get("supporting_files", [])):
                support_root = item_root / f"support-{support_index}"
                support_root.mkdir()
                supporting_path = support_root / _upload_filename(support["filename"])
                supporting_path.write_bytes(support["data"])
                supporting_paths.append(supporting_path)
        return stage_external_many(entries, request, output_root, supporting_files=supporting_paths)


def stage_retained_starting_state(
    run_dir: Path | str, candidate_id: str, *, actor: str, reason: str, budget_seconds: float,
) -> RunRecord:
    """Start a new explicit geometry entry without changing an earlier calculation."""
    from topos.chemistry import to_xyz
    from topos.storage import RunStore, digest_json

    store = RunStore(run_dir)
    snapshot = store.verify()
    record = store.load()
    if digest_json(record) != snapshot["record_sha256"]:
        raise ValueError("The source calculation changed before its starting state could be frozen")
    if _matrix_uses_explicit_seed_channel(record["request"]):
        raise ValueError("This matrix recipe uses explicit seed or ensemble inputs; import retained geometries through External starting states at the named matrix entry step")
    candidates = [candidate for candidate in record["candidates"] if candidate["candidate_id"] == candidate_id]
    if len(candidates) != 1:
        raise ValueError("Select exactly one retained candidate from the verified run")
    candidate = candidates[0]
    molecule = Molecule.model_validate(candidate["molecule"])
    values = {**record["request"], "molecule": molecule.model_dump(mode="json"),
              "starting_geometries": [], "budget_seconds": budget_seconds,
              "metadata": {"retained_starting_state": {
                  "source_run_id": record["run_id"], "source_snapshot_sha256": snapshot["snapshot_id"],
                  "source_candidate_id": candidate_id, "geometry_sha256": digest_json(candidate["molecule"]),
                  "previous_candidate_status": candidate["status"],
                  "entry_policy": "new explicitly requested calculation; previous result is not completion of the new run",
              }}}
    request = RunRequest.model_validate(values)
    specification = {"format": "xyz", "entrypoint": "geometry", "reference": molecule.model_dump(mode="json"),
        "source": {"engine": "CoChem-TOPOS retained geometry", "engine_version": record["schema_version"],
            "method": "explicit geometry entry from a retained candidate", "created_by": actor,
            "description": reason, "source_reference": f"run:{record['run_id']}; snapshot:{snapshot['snapshot_id']}; candidate:{candidate_id}",
            "coordinate_units": "angstrom", "energy_units": None, "atom_order": molecule.atom_ids}}
    staged = stage_uploaded_starting_states([{"data": to_xyz(molecule).encode("utf-8"),
                                             "specification": specification}], request, store.run_dir.parent)
    return staged


def _matrix_uses_explicit_seed_channel(request: dict[str, Any]) -> bool:
    return request.get("purpose") == "matrix" and any(request.get("matrix_inputs", {}).get(name)
        for name in ("topology_seeds", "stage_b_ensemble", "leading_isomers", "entropy_seeds",
                     "ml_search_seeds", "goat_ensemble", "crest_ensemble"))


def _external_panel(st: Any) -> None:
    st.subheader("Resume from external starting states")
    st.caption("Import GOAT/CREST ensembles or XYZ geometries, keep their original evidence, and start at an explicit CoChem step. Imported search scores do not become validated refinement energies.")
    prepared = st.session_state.get("topos_prepared_request")
    if prepared is None:
        st.info("Choose the calculation route, chemical state and resources in Calculate, then click Prepare request for external starting states.")
        return
    request = RunRequest.model_validate(prepared)
    output_root = Path(st.session_state["topos_prepared_output_root"])
    identity = json.dumps(prepared, sort_keys=True, allow_nan=False)
    if st.session_state.get("topos_intake_request") != identity:
        st.session_state["topos_intake_request"] = identity
        st.session_state["topos_intake_queue"] = []
        st.session_state.pop("topos_upload_preview", None)
        st.session_state.pop("topos_external_export_run", None)
        st.session_state.pop("topos_external_export_request", None)
    with st.expander("Prepared calculation settings", expanded=False):
        st.json(prepared)
        settings = st.session_state["topos_prepared_execution_config"]
        st.json({name: settings.get(name) for name in ("remote_repository", "remote_ref", "remote_base_commit")})
        st.caption(f"Results: {output_root}. Prepare the request again after changing Calculate settings.")
    st.download_button("Download prepared request", json.dumps(prepared, indent=2, allow_nan=False),
                       file_name="topos-request.json", mime="application/json")
    entry_labels = {
        "geometry": "Starting geometry for this calculation",
        "refinement": "Refine externally sampled conformers; skip repeating the search",
        "topology-seeds": "Matrix topology seeds",
        "stage-b-ensemble": "Matrix ensemble for Stage B refinement",
        "leading-isomers": "Matrix leading isomers",
        "entropy-seeds": "Matrix common entropy seeds",
        "ml-search-seeds": "Matrix ML search seeds",
        "isolated-monomers": "Matrix independently calculated isolated monomer references",
    }
    choices = ["geometry"]
    if request.purpose in {"search", "optimize", "energy", "gradient"}:
        choices.append("refinement")
    if request.purpose == "matrix":
        from topos.ingestion import MATRIX_TARGETS

        choices.extend(name for name, (_, rows) in MATRIX_TARGETS.items() if request.matrix_row_id in rows)
    entrypoint = st.selectbox("Entry step", choices, format_func=entry_labels.__getitem__)
    format_name = st.selectbox("External file format", ["xyz", "goat-ensemble", "crest-ensemble"])
    st.caption("Each XYZ frame must use angstrom coordinates and preserve the declared atom order. Declare charge, spin, fragments, isotopes and stereochemistry in the reference; they are never inferred from a search comment.")
    st.caption("Repeated elements must already follow the declared stable atom IDs. Element symbols alone cannot reveal a permutation of identical atoms.")
    reference = request.molecule
    if entrypoint == "isolated-monomers":
        from topos.fragments import split_fragments

        try:
            references = split_fragments(request.molecule)
            fragment_index = st.selectbox("Declared monomer fragment", list(range(len(references))),
                format_func=lambda index: f"Fragment {index + 1}: {', '.join(references[index].atom_ids)}")
            reference = references[fragment_index]
        except ValueError as exc:
            st.error(_error_message(exc))
            return
    reference_text = st.text_area("External reference molecule (JSON)",
        value=json.dumps(reference.model_dump(mode="json"), indent=2),
        help="For isolated-monomer intake, supply that monomer with the exact parent fragment atom IDs and electronic state.")
    source_engine = st.text_input("Source engine", value="crest" if format_name == "crest-ensemble" else "orca" if format_name == "goat-ensemble" else "user")
    source_version = st.text_input("Source engine version")
    source_method = st.text_input("Source method or geometry preparation procedure")
    created_by = st.text_input("Starting-state author")
    description = st.text_area("Source calculation, parameters and scientific scope",
                               help="Record the specialized GOAT/CREST settings or cite the source calculation. Keep credentials out of scientific metadata.")
    source_reference = st.text_input("Source citation or calculation reference (optional)",
                                    help="R2 isolated references must match the method, geometry digest and citation declared in the prepared r2_monomer_provenance protocol.")
    prior_status = st.selectbox("Declared previous calculation status", ["unknown", "completed", "partial", "failed"],
                               help="A source declaration does not attest a successful CoChem calculation.")
    energy_units = st.selectbox("Native search score units", ["hartree"],
                               disabled=format_name == "xyz")
    upload = st.file_uploader("Drop an external geometry or ensemble here", type=["xyz"],
                              help="Maximum total intake size: 64 MiB. Files are parsed as molecular data, never executed.")
    supporting_uploads = st.file_uploader("Optional original input, output and parameter files",
        type=["out", "inp", "log", "txt", "json", "stdout", "stderr"], accept_multiple_files=True,
        help="Retained as unvalidated source evidence alongside the geometry. They never establish native execution or replace required typed scientific protocols.")
    if st.button("Preview uploaded starting state", disabled=upload is None):
        try:
            from topos.models import Molecule

            reference = Molecule.model_validate(_parse_json(reference_text))
            specification = {
                "format": format_name, "entrypoint": entrypoint, "reference": reference.model_dump(mode="json"),
                "source": {"engine": source_engine, "engine_version": source_version,
                    "method": source_method, "created_by": created_by, "description": description,
                    "coordinate_units": "angstrom", "atom_order": reference.atom_ids,
                    "source_reference": source_reference or None,
                    "original_calculation_status": prior_status,
                    "energy_units": None if format_name == "xyz" else energy_units},
            }
            from topos.ingestion import MAX_IMPORT_BYTES

            if upload.size + sum(item.size for item in supporting_uploads) > MAX_IMPORT_BYTES:
                raise ValueError("Combined geometry and supporting uploads must be at most 64 MiB")
            data = upload.getvalue()
            preview = preview_uploaded_starting_state(data, specification, upload.name)
            st.session_state["topos_upload_preview"] = {
                "data": data, "filename": upload.name, "specification": specification,
                "supporting_files": [{"filename": item.name, "data": item.getvalue()} for item in supporting_uploads],
                "preview": preview.model_dump(mode="json"),
            }
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(_error_message(exc))
    state = st.session_state.get("topos_upload_preview")
    if state is not None:
        frames = state["preview"]["frames"]
        st.write(f"Preview: {len(frames)} frame(s).")
        with st.expander("Parsed starting-state evidence", expanded=False):
            st.json(state["specification"])
            st.json(state["preview"])
        indices = [frame["source_index"] for frame in frames]
        inspected = st.selectbox("Preview structure frame", indices)
        _show_structure(st, frames[indices.index(inspected)]["molecule"],
                        key=f"external-{state['preview']['source_sha256']}-{inspected}")
        selected = st.multiselect("Frames to ingest (one based)", indices,
            default=[indices[0]] if state["specification"]["entrypoint"] == "geometry" else indices)
        if st.button("Add selected frames to intake", disabled=not selected):
            try:
                specification = {**state["specification"], "selected_frames": selected}
                from topos.ingestion import prepare_external_request

                selected_preview = preview_uploaded_starting_state(state["data"], specification,
                                                                   state.get("filename", "external.xyz"))
                prepare_external_request(selected_preview, specification, request)
                st.session_state["topos_intake_queue"].append({
                    "data": state["data"], "filename": state.get("filename", "external.xyz"),
                    "specification": specification, "supporting_files": state.get("supporting_files", []),
                })
                st.success("Starting states added. Add another file for additional monomer references or run the intake.")
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(_error_message(exc))
    queue = st.session_state["topos_intake_queue"]
    if queue:
        st.write("Queued starting states")
        st.json([{"entry_step": item["specification"]["entrypoint"],
                  "frames": item["specification"]["selected_frames"],
                  "bytes": len(item["data"]), "source": item["specification"]["source"]} for item in queue])
        if st.button("Clear starting-state intake"):
            st.session_state["topos_intake_queue"] = []
            st.rerun()
    job = st.session_state.get("topos_job")
    active = job is not None and not job.done.is_set()
    prepare_export = st.button("Prepare imported request for BASE Actions", disabled=not queue or active)
    if prepare_export:
        try:
            staged = stage_uploaded_starting_states(queue, request, output_root)
            st.session_state["topos_export_request"] = staged.request.model_dump(mode="json")
            st.session_state["topos_external_export_request"] = staged.request.model_dump(mode="json")
            st.session_state["topos_external_export_run"] = str(output_root / staged.run_id)
            st.session_state["topos_intake_queue"] = []
            st.success(f"Imported request prepared; original sources retained in {output_root / staged.run_id}.")
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(_error_message(exc))
    if st.session_state.get("topos_external_export_run"):
        from topos.storage import RunStore

        try:
            staged_store = RunStore(st.session_state["topos_external_export_run"])
            staged_store.verify()
            exported = st.session_state["topos_external_export_request"]
            if staged_store.load()["request"] != exported:
                raise ValueError("The imported export differs from its retained canonical request")
            _download_calculation_request(st, exported, key="topos_imported_request_download")
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(_error_message(exc))
    if st.button("Run calculation from imported starting states", disabled=not queue or active):
        try:
            staged = stage_uploaded_starting_states(queue, request, output_root)
            st.session_state["topos_intake_queue"] = []
            _start_job(st, staged.request, output_root, output_root / staged.run_id,
                       config=st.session_state.get("topos_prepared_execution_config"), external=True)
            st.success(f"Starting states persisted for {staged.run_id}. Calculate shows progress and cancellation.")
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(_error_message(exc))


def structure_figure(molecule: Molecule | dict[str, Any]) -> Any:
    """Display the declared float64 geometry and bonds without inventing topology."""
    import plotly.graph_objects as go

    molecule = Molecule.model_validate(molecule)
    colors = {"H": "#cbd5e1", "C": "#334155", "N": "#2563eb", "O": "#dc2626",
              "F": "#16a34a", "Cl": "#16a34a", "S": "#eab308", "P": "#ea580c"}
    xyz = molecule.coordinates
    figure = go.Figure()
    for bond in molecule.bonds:
        first, second = xyz[bond.atom1], xyz[bond.atom2]
        figure.add_trace(go.Scatter3d(x=[first[0], second[0]], y=[first[1], second[1]],
            z=[first[2], second[2]], mode="lines", line={"color": "#94a3b8", "width": 5},
            name=f"Declared {bond.kind} bond", hoverinfo="name", showlegend=False))
    labels = [f"{index}: {atom_id} · {symbol}" for index, (atom_id, symbol) in
              enumerate(zip(molecule.atom_ids, molecule.symbols, strict=True))]
    figure.add_trace(go.Scatter3d(x=[point[0] for point in xyz], y=[point[1] for point in xyz],
        z=[point[2] for point in xyz], mode="markers+text", text=labels,
        marker={"size": [7 if symbol == "H" else 11 for symbol in molecule.symbols],
                "color": [colors.get(symbol, "#7c3aed") for symbol in molecule.symbols]},
        textposition="top center", hovertemplate="%{text}<br>(%{x}, %{y}, %{z}) Å<extra></extra>",
        name="Declared atoms", showlegend=False))
    figure.update_layout(scene={"aspectmode": "data", "xaxis_title": "x (Å)",
                                "yaxis_title": "y (Å)", "zaxis_title": "z (Å)"},
                         margin={"l": 0, "r": 0, "t": 0, "b": 0}, height=420,
                         uirevision="declared-geometry")
    return figure


def _show_structure(st: Any, molecule: dict[str, Any], *, key: str) -> None:
    try:
        figure = structure_figure(molecule)
    except ImportError:
        st.info("Install the browser visualization dependencies with: pip install 'cochem-topos[ui]'")
        return
    st.plotly_chart(figure, use_container_width=True, key=key)
    st.caption("Coordinates: angstrom. Labels use zero-based atom indices and stable atom IDs; lines show explicitly declared bonds.")


def verified_bundle_download(destination: Path | str) -> bytes:
    """Archive exactly the verified scientific membership, with a bounded memory ceiling."""
    from topos.cfour_artifacts import validate_scientific_export_membership
    from topos.publication import verify_bundle
    from topos.storage import IntegrityError, confined_file, read_json

    root = Path(destination)
    manifest = verify_bundle(root)
    validate_scientific_export_membership(read_json(root / "run.json"), read_json(root / "snapshot/manifest.json"))
    if sum(entry["size_bytes"] for entry in manifest["files"]) > 256 * 1024 * 1024:
        raise ValueError("Browser downloads are limited to 256 MiB; use the verified local bundle folder for larger exports")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in manifest["files"]:
            data = confined_file(root, entry["path"]).read_bytes()
            if len(data) != entry["size_bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise IntegrityError("Bundle changed while preparing the browser download")
            archive.writestr(entry["path"], data)
        manifest_data = confined_file(root, "manifest.json").read_bytes()
        if json.loads(manifest_data) != manifest:
            raise IntegrityError("Bundle manifest changed while preparing the browser download")
        archive.writestr("manifest.json", manifest_data)
    return stream.getvalue()


def _show_record(st: Any, record: dict[str, Any], *, view: str = "execution") -> None:
    st.write(f"Execution: **{record['status']}** · Validation: **{record['validation_status']}**")
    st.caption(f"Run: {record['run_id']}")
    if record.get("status") in {"queued", "running"}:
        _show_workstation_status(st, record)
    st.json(record.get("metadata", {}), expanded=False)
    with st.expander("Input structure", expanded=False):
        _show_structure(st, record["request"]["molecule"], key=f"{view}-{record['run_id']}-input")
    st.subheader("Candidate basket")
    candidates = record.get("candidates", [])
    if candidates:
        st.dataframe([{"candidate_id": candidate["candidate_id"], "status": candidate.get("status", "unreviewed"),
                       "electronic_energy_hartree": candidate.get("energy_hartree"),
                       "gibbs_energy_hartree": candidate.get("gibbs_hartree"),
                       "sources": ", ".join(candidate.get("sources", []))} for candidate in candidates],
                      hide_index=True, use_container_width=True)
        by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
        selected = st.selectbox("Candidate to inspect", list(by_id), key=f"{view}-{record['run_id']}-candidate")
        candidate = by_id[selected]
        _show_structure(st, candidate["molecule"], key=f"{view}-{candidate['candidate_id']}-structure")
        with st.expander("Selected candidate evidence"):
            st.json(candidate)
    else:
        st.info("This run has no candidate structures.")
    with st.expander("Execution attempts and requested protocol"):
        st.json({"request": record["request"], "attempts": record.get("attempts", [])})


def _review_panel(st: Any) -> None:
    from topos.publication import export_bundle
    from topos.review import (
        accept_torq_receipt,
        append_decision,
        create_ensemble_manifest,
        export_torq_handoff,
        list_decisions,
        review_basket,
    )
    from topos.storage import RunStore

    st.subheader("Review a saved run")
    run_text = st.text_input("Run directory", key="review_run_dir")
    if not run_text:
        return
    run_dir = Path(run_text).expanduser()
    try:
        store = RunStore(run_dir)
        snapshot = store.verify()
        record = store.load()
        _show_record(st, record, view="review")
        current_job = st.session_state.get("topos_job")
        active = current_job is not None and not current_job.done.is_set()
        if st.button("Resume saved calculation", disabled=active or record["status"] == "completed",
                     help="Resume verified committed work using its original request and BASE authority. Remote runs refresh their recorded job; local work retries unfinished steps."):
            _start_job(st, RunRequest.model_validate(record["request"]), run_dir.resolve().parent, run_dir.resolve())
            st.info("Resume requested. Calculate shows progress and cancellation.")
        decisions = list_decisions(run_dir)
        with st.expander("Review history"):
            st.json(decisions)
        with st.expander("Scientific eligibility and unresolved chemistry"):
            st.json(review_basket(run_dir))
        if record.get("candidates") and _matrix_uses_explicit_seed_channel(record["request"]):
            st.info("This matrix recipe uses explicit seed or ensemble inputs. Use External starting states at its named entry step to prepare retained geometries for a new calculation.")
        elif record.get("candidates"):
            with st.form("retained_geometry_entry"):
                st.caption("Prepare a separate run from the selected retained candidate. Its new calculation must establish its own convergence and scientific eligibility.")
                actor = st.text_input("New starting-state author")
                reason = st.text_area("Reason for the new calculation")
                continuation_budget = st.number_input("New workflow budget (seconds)", min_value=.001,
                                                       value=float(record["request"]["budget_seconds"]))
                if st.form_submit_button("Prepare new run from selected retained geometry", disabled=active):
                    selected = st.session_state[f"review-{record['run_id']}-candidate"]
                    staged = stage_retained_starting_state(run_dir, selected, actor=actor, reason=reason,
                                                          budget_seconds=continuation_budget)
                    st.session_state["topos_retained_request"] = staged.request.model_dump(mode="json")
                    st.session_state["topos_export_request"] = staged.request.model_dump(mode="json")
                    st.success(f"New starting state prepared in {run_dir.resolve().parent / staged.run_id}.")
            if st.session_state.get("topos_retained_request"):
                _download_calculation_request(st, st.session_state["topos_retained_request"], key="topos_retained_request_download")
        with st.form("review_decision"):
            subject = st.text_input("Candidate ID")
            action = st.selectbox("Decision", ["accept", "reject", "annotate", "needs-review", "withdraw"])
            actor = st.text_input("Reviewer identity")
            reason = st.text_area("Reason and scope")
            supersedes = st.text_input("Superseded decision ID (optional)")
            scope = st.text_input("Decision scope", value="candidate")
            annotation_text = st.text_area("Annotations (JSON object)", value="{}")
            if st.form_submit_button("Record decision"):
                st.json(append_decision(run_dir, subject_id=subject, action=action, actor=actor,
                                        reason=reason, supersedes=supersedes or None, scope=scope,
                                        annotations=_parse_json(annotation_text)))
        with st.form("freeze_ensemble"):
            selected = st.multiselect("Ensemble members (each needs an accept decision)",
                                     [c["candidate_id"] for c in record.get("candidates", [])])
            actor = st.text_input("Ensemble author")
            reason = st.text_input("Selection rationale")
            if st.form_submit_button("Freeze reviewed ensemble"):
                st.json(create_ensemble_manifest(run_dir, selected, actor=actor, reason=reason,
                                                 expected_snapshot_sha256=snapshot["snapshot_id"]))
        with st.form("torq_handoff"):
            destination = st.text_input("TORQ handoff file", value=str(run_dir.parent / f"{run_dir.name}-torq.json"))
            if st.form_submit_button("Export reviewed ensemble for TORQ"):
                st.json(export_torq_handoff(run_dir, destination))
                st.info("Handoff exported. TORQ consumption requires a receipt from the consumer.")
        with st.form("torq_receipt"):
            receipt_path = st.text_input("Receipt file produced by TORQ")
            if st.form_submit_button("Verify TORQ consumption receipt"):
                st.json(accept_torq_receipt(run_dir, receipt_path))
        with st.form("publication_export"):
            destination = st.text_input("Local bundle folder", value=str(run_dir.parent / f"{run_dir.name}-publication"))
            license_id = st.text_input("Proposed artifact license (SPDX or LicenseRef identifier)")
            if st.form_submit_button("Create local publication archive"):
                st.json(export_bundle(run_dir, Path(destination), license_identifier=license_id or None))
                st.session_state["topos_publication_bundle"] = {"path": destination, "run_id": record["run_id"]}
                st.caption("Local archive only. Run its regenerate.py script to reproduce the table and figure; publication requires author review.")
        bundle = st.session_state.get("topos_publication_bundle")
        if bundle and bundle["run_id"] == record["run_id"]:
            st.download_button("Download verified publication bundle", verified_bundle_download(bundle["path"]),
                               file_name=f"{record['run_id']}-publication.zip", mime="application/zip")
    except (OSError, ValueError, RuntimeError) as exc:
        st.error(_error_message(exc))


def _matrix_panel(st: Any) -> None:
    """Inspect source-bound routes without treating PATH discovery as validation."""
    import psutil

    from topos.method_matrix import BackendCapability, HardwareSpec, load_catalog, plan_route
    from topos.runtime import available_cpu_count

    catalog = load_catalog()
    st.subheader("Purpose, time tier and hardware routes")
    st.caption(f"Matrix revision: {catalog.revision}. A time tier is a planning category, not a predicted runtime.")
    with st.expander("Executable recipes and remaining adapters"):
        from topos.matrix_workflow import execution_support_report
        st.json(execution_support_report())
    owner = st.selectbox("Matrix owner", ["TOPOS", "TORQ", "All"])
    rows = [row for row in catalog.rows if owner == "All" or row.owner == owner]
    row_id = st.selectbox("Matrix row", [row.row_id for row in rows])
    row = catalog.get(row_id)
    st.json(row.model_dump(mode="json"), expanded=False)
    if row.owner == "TORQ":
        st.info("This route belongs to TORQ. TOPOS can export the reviewed ensemble for that component.")
    with st.form("matrix_plan"):
        cpu = st.number_input("Allocated CPU threads", min_value=1, value=available_cpu_count())
        ram = st.number_input("Allocated memory (MB)", min_value=64,
                              value=max(64, int(psutil.virtual_memory().available // 1048576)))
        device = st.selectbox("Planning device", ["cpu", "auto", "gpu"])
        gpu = st.text_input("GPU model (required for GPU allocation)")
        gpu_memory = st.number_input("Available GPU memory (MB)", min_value=1, value=1024)
        fingerprint = st.text_input("Hardware fingerprint", value="interactive-local-observation")
        product = st.selectbox("Matrix product", ["A", "B", "C"])
        from .data.reviewed_matrix_v010 import RECIPES

        source_resolution = st.selectbox("Explicit source-conflict resolution", ["None",
            "native-composite-rawinteraction-v1", "orca-f12-reference-singlepoint-v1", *RECIPES],
            help="Choose only when the selected row documents this resolution. Reference single points do not complete an optimized-geometry row.")
        capabilities = st.text_area("Verified backend capabilities (JSON array)", value="[]",
                                    help="Use actual versioned adapter evidence. With no declarations, the plan reports missing capabilities.")
        inputs = st.text_input("Available scientific input names (comma separated)")
        if st.form_submit_button("Inspect execution plan"):
            try:
                values = _parse_json(capabilities)
                if not isinstance(values, list):
                    raise ValueError("Verified backend capabilities must be a JSON array")
                hardware = HardwareSpec(cpu_threads=cpu, memory_mb=ram,
                                        memory_per_worker_mb=min(1024, ram),
                                        device=device, gpu_model=gpu or None,
                                        gpu_memory_mb=gpu_memory if gpu else None,
                                        fingerprint=fingerprint)
                plan = plan_route(row_id, hardware=hardware, product=product,
                                  capabilities=[BackendCapability.model_validate(value) for value in values],
                                  available_inputs=[name.strip() for name in inputs.split(",") if name.strip()],
                                  source_resolution=None if source_resolution == "None" else source_resolution)
                st.json(plan.model_dump(mode="json"))
                st.caption("Plan inspection does not submit calculations or establish that all required adapters are implemented.")
            except (ValueError, OSError, RuntimeError) as exc:
                st.error(_error_message(exc))


def render_streamlit() -> None:
    """Render the genuine workflow; requires the optional ``ui`` installation extra."""
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError("Install the UI extra with: pip install 'cochem-topos[ui]'") from exc
    from topos.capabilities import capability_report
    from topos.config import load_config
    st.set_page_config(page_title="CoChem-TOPOS 0.1.0", layout="wide")
    st.title("CoChem-TOPOS 0.1.0")
    st.caption("Molecular search, scientific evidence, reviewed ensembles, and local publication archives")
    with st.expander("Available capabilities and limitations"):
        st.json(capability_report())
    with st.expander("CoChem installation"):
        from topos.base_integration import inspect_ecosystem
        ecosystem = inspect_ecosystem()
        st.json(ecosystem.to_dict())
        if not ecosystem.available:
            st.info("Provision the mandatory CoChem-BASE, TOPOS and TORQ package before calculation.")
    _execution_configuration_panel(st)
    _workstation_configuration_panel(st)
    run_tab, external_tab, review_tab, matrix_tab = st.tabs([
        "Calculate", "External starting states", "Review and export", "Method matrix",
    ])
    with run_tab:
        job = st.session_state.get("topos_job")
        active = job is not None and not job.done.is_set()
        with st.container():
            first, second = st.columns(2)
            with first:
                presentation = st.selectbox("Presentation environment", ["local", "codespaces", "base", "jupyter"])
                purpose = st.selectbox("Purpose", ["search", "optimize", "energy", "gradient", "frequency", "thermochemistry", "association", "matrix"])
                engine = st.selectbox("Calculation engine", ["xtb", "orca"]) if purpose != "matrix" else "xtb"
                budget = st.number_input("Workflow budget (seconds)", min_value=1.0, value=300.0)
            with second:
                environment = st.selectbox("Calculation environment", ["local", "github-actions", "hpc", "workstation"],
                                           help="workstation: queue to the lab workstation through your assigned Drive folder")
                method = st.selectbox("Method", capability_report()["engines"][engine]["methods"]) if purpose != "matrix" else "GFN2-xTB"
                device = st.selectbox("Calculation device", ["cpu", "gpu"] if purpose == "matrix" else ["cpu", "cuda"])
                basis = st.text_input("Basis (empty for native composite or not applicable)") if purpose != "matrix" else ""
            profile_options = [name for name, values in capability_report()["profiles"].items()
                               if values["engine"] == engine]
            profile = st.selectbox("Convergence profile", profile_options) if purpose != "matrix" else "screening-v1"
            matrix_settings: dict[str, Any] = {}
            if purpose == "matrix":
                st.caption("The selected matrix recipe controls its native engines, methods, bases and convergence profiles.")
                matrix_row, matrix_settings, matrix_input_text = _matrix_calculation_panel(st)
            else:
                matrix_row = st.text_input("Method matrix row (optional)",
                    help="Use an exact row such as T3O-30min. The selected engine, method and purpose must satisfy its validated binding.")
                matrix_input_text = "{}"
            if matrix_row.strip() and purpose != "matrix":
                matrix_settings["matrix_product"] = st.selectbox("Requested matrix product", ["A", "B", "C"])
                matrix_input_text = st.text_area("Matrix scientific inputs (JSON object)", value="{}",
                    help="Use topology_seeds, stage_b_ensemble, isolated_monomer_references and isolated_monomer_sources as required by the selected recipe.")
            if purpose == "matrix":
                st.caption("The chosen matrix row specifies the calculation methods and required scientific inputs. Only compiled complete recipes can execute.")
            search_settings = {}
            abcluster_input_text = None
            if purpose == "search":
                algorithm = st.selectbox("Search algorithm", ["jiggle-quench", "crest", "union", "abcluster"],
                                         format_func=lambda value: {"jiggle-quench": "Jiggle–quench", "crest": "CREST", "union": "Jiggle–quench + CREST union", "abcluster": "ABCluster rigid packing"}[value])
                search_settings["search_algorithm"] = algorithm
                count, randomization = st.columns(2)
                with count:
                    search_settings["n_candidates"] = st.number_input(
                        "Candidate limit per search source", min_value=1, max_value=10000, value=4,
                        help="Jiggle–quench includes the input in this limit. CREST supplies up to this many native frames, plus the input. Union retains both sources.",
                    )
                with randomization:
                    search_settings["seed"] = st.number_input("TOPOS perturbation seed", min_value=0, value=0)
                if algorithm in {"jiggle-quench", "union"}:
                    search_settings["perturbation_angstrom"] = st.number_input(
                        "Jiggle displacement scale (angstrom)", min_value=0.0, value=0.15, step=0.01,
                        help="Controls TOPOS perturbations before local optimization; it does not establish exhaustive sampling.",
                    )
                if algorithm == "abcluster":
                    abcluster_input_text = st.text_area("ABCluster force-field parameters and sampling options (JSON object)", value="{}",
                        help="Supply atomic_parameters with atom_id, charge_e, epsilon_kj_mol and sigma_angstrom for every real atom, plus a cited parameter_source. Optional controls: population (at least 5), generations, scout_limit, amplitude_angstrom and max_saved_minima.")
                    search_settings["sampler_budget_fraction"] = st.slider("ABCluster fraction of remaining workflow budget",
                        min_value=.05, max_value=.95, value=.5, step=.05)
                    st.caption("Declare rigid fragments and their charge/spin states. ABCluster generates packing seeds using your classical force field; TOPOS independently refines them with the selected quantum method. Classical scores are retained as sampling evidence. Native randomness is engine-controlled.")
                if algorithm in {"crest", "union"}:
                    sampler_profile = st.selectbox("CREST sampling protocol", ["crest-imtdgc-v1", "crest-mquick-v1", "crest-nci-v1"])
                    fraction = st.slider("CREST fraction of remaining workflow budget", min_value=0.05,
                                         max_value=0.95, value=0.5, step=0.05)
                    nci = sampler_profile == "crest-nci-v1"
                    if not nci:
                        nci = st.checkbox("Noncovalent complex confinement (NCI)")
                    search_settings.update(sampler_profile=sampler_profile, sampler_budget_fraction=fraction,
                                           sampler_nci=nci)
                    st.caption("CREST routes require unconstrained GFN2-xTB. The TOPOS seed controls jiggle perturbations; CREST controls its own random initialization. Isotope-labelled molecular dynamics is unsupported.")
                    if nci:
                        st.caption("NCI requires at least two explicitly declared fragments. Its confinement potential biases sampling; final xTB refinement uses the requested physical potential without this confinement.")
                    if sampler_profile == "crest-mquick-v1":
                        st.caption("mquick uses a reduced sampling protocol with normal molecular dynamics and genetic crossing disabled. It does not establish conformational completeness.")
                with st.expander("Energy window and deduplication"):
                    search_settings["deduplication_stage"] = st.selectbox("Deduplication stage", ["generation", "reporting"])
                    if search_settings["deduplication_stage"] == "reporting":
                        st.caption("Reporting requires validated refined geometry and energy. Ineligible candidates remain unresolved.")
                    search_settings["collapse_enantiomers"] = st.checkbox("Group validated sampled mirror partners", value=False)
                    if search_settings["collapse_enantiomers"]:
                        environment_symmetry = st.selectbox("Chiral environment declaration", ["unspecified", "achiral", "chiral"])
                        search_settings["environment_is_achiral"] = {"unspecified": None, "achiral": True, "chiral": False}[environment_symmetry]
                        st.caption("Grouping needs explicit achiral conditions and a verified sampled mirror partner; no missing partner is invented.")
                    search_settings["symmetry_tolerance_angstrom"] = st.number_input(
                        "Point-group tolerance (angstrom)", min_value=0.000001, max_value=0.1, value=0.001, format="%.6f")
                    search_settings["energy_window_kcal_mol"] = st.number_input(
                        "Electronic-energy window (kcal/mol)", min_value=0.001, value=6.0,
                        help="Applied to refined candidates and passed to CREST's native ensemble window. This is not a free-energy or population criterion.",
                    )
                    search_settings["rmsd_threshold_angstrom"] = st.number_input(
                        "Deduplication RMSD threshold (angstrom)", min_value=0.0001, value=0.125, format="%.4f",
                    )
                    search_settings["dedup_energy_threshold_kcal_mol"] = st.number_input(
                        "Deduplication energy tolerance (kcal/mol)", min_value=0.0001, value=0.05, format="%.4f",
                    )
                    search_settings["dedup_rotational_threshold_fraction"] = st.number_input(
                        "Deduplication rotational-constant relative tolerance", min_value=0.0001, max_value=0.9999, value=0.01, format="%.4f",
                        help="A fractional tolerance: 0.01 means 1%. Rotational constants alone do not establish identity.",
                    )
            if purpose in {"frequency", "thermochemistry"}:
                with st.expander("Frequency and thermochemistry protocol", expanded=True):
                    search_settings["temperature_k"] = st.number_input("Temperature (K)", min_value=0.001, value=298.15)
                    thermal = {
                        "optimize_first": st.checkbox("Optimize before evaluating frequencies", value=True),
                        "step_bohr": st.number_input("Hessian displacement (bohr)", min_value=0.00001, max_value=0.1, value=0.005, format="%.5f"),
                        "pressure_pa": st.number_input("Gas standard pressure (Pa)", min_value=0.001, value=101325.0),
                        "frequency_scale": st.number_input("Frequency scale factor", min_value=0.001, value=1.0),
                        "low_frequency_policy": st.selectbox("Low-frequency treatment", ["reject", "frequency-floor"]),
                        "cutoff_cm1": st.number_input("Low-frequency cutoff (cm⁻¹)", min_value=0.001, value=10.0),
                    }
                    if st.checkbox("Use a solution concentration standard state"):
                        thermal["concentration_mol_l"] = st.number_input("Standard concentration (mol/L)", min_value=0.00001, value=1.0)
                    if st.checkbox("Specify rotational symmetry number"):
                        thermal["symmetry_number"] = st.number_input("Rotational symmetry number", min_value=1, value=1)
                    search_settings["thermochemistry_options"] = thermal
                    st.caption("Imaginary modes and nonstationary geometries require review. A frequency floor is an explicit approximation, not an anharmonic calculation.")
            if purpose == "association":
                st.info("Declare fragments and each fragment's charge and multiplicity in the molecule. Association runs retain separate monomer and complex evidence at a common method.")
            molecule_controls = _molecule_input_panel(st)
            advanced_text = st.text_area(
                "Search, resource and protocol settings (JSON)",
                value=json.dumps({"threads": 1, "memory_mb": 1024}, indent=2),
            )
            output_root = st.text_input("Output directory", value=str(load_config().output_root.expanduser().resolve()))
            prepared = st.button("Prepare request for external starting states", disabled=active,
                                 help="Validate and freeze the visible calculation settings before selecting externally calculated geometries or ensembles.")
            validate_export = st.button("Validate calculation request for BASE Actions", disabled=active)
            submitted = st.button("Run requested calculation", disabled=active)
        if submitted or prepared or validate_export:
            try:
                fields = _parse_json(advanced_text)
                if not isinstance(fields, dict):
                    raise ValueError("Search and resource settings must be a JSON object")
                selections = {"molecule": molecule_from_controls(molecule_controls), "engine": engine, "method": method,
                              "purpose": purpose, "presentation_environment": presentation,
                              "calculation_environment": environment, "budget_seconds": budget,
                              "device": device, "basis": basis or None, "profile_id": profile,
                              **search_settings}
                if abcluster_input_text is not None:
                    parameters = _parse_json(abcluster_input_text)
                    if not isinstance(parameters, dict):
                        raise ValueError("ABCluster options must be a JSON object")
                    selections["abcluster_options"] = parameters
                if matrix_row.strip():
                    from topos.method_matrix import MATRIX_REVISION
                    matrix_inputs = _matrix_control_inputs(matrix_settings, matrix_input_text)
                    selections.update(matrix_row_id=matrix_row.strip(), matrix_revision=MATRIX_REVISION,
                                      matrix_product=matrix_settings.get("matrix_product", "A"), matrix_inputs=matrix_inputs)
                if fields.keys() & selections.keys():
                    raise ValueError("Advanced settings must not override the explicit selectors")
                request = parse_request_json(json.dumps({**fields, **selections}, allow_nan=False))
                st.session_state["topos_prepared_request"] = request.model_dump(mode="json")
                st.session_state["topos_export_request"] = request.model_dump(mode="json")
                st.session_state["topos_prepared_output_root"] = str(Path(output_root).expanduser().resolve())
                st.session_state["topos_prepared_execution_config"] = st.session_state.get("topos_execution_config") or load_config().model_dump(mode="json")
                if submitted:
                    _start_job(st, request, Path(output_root).expanduser())
                elif prepared:
                    st.success("Calculation settings prepared. Select External starting states to preview, choose the entry step, and run the imported geometries.")
                else:
                    st.success("Typed calculation request validated. Download it for the BASE TOPOS calculation workflow.")
            except (OSError, ValueError) as exc:
                st.error(_error_message(exc))
        if st.session_state.get("topos_export_request") is not None:
            _download_calculation_request(st, st.session_state["topos_export_request"], key="topos_calc_request_download")
        if st.session_state.get("topos_job") is not None:
            @st.fragment(run_every=1.0)
            def progress() -> None:
                current = st.session_state["topos_job"]
                if not current.done.is_set():
                    st.info("Calculation is running; completed evidence will be preserved if cancelled.")
                    if st.button("Cancel this calculation"):
                        current.cancel_event.set()
                        st.info("Cancellation requested.")
                elif current.error is not None:
                    st.error(current.error)
                else:
                    _show_record(st, current.record.model_dump(mode="json"))
            progress()
    with external_tab:
        _external_panel(st)
    with review_tab:
        _review_panel(st)
    with matrix_tab:
        _matrix_panel(st)


def main() -> int:
    """``python -m topos.ui`` accepts the same CLI commands as ``python -m topos``."""
    from topos.cli import main as cli_main
    return cli_main()


def ui_main(argv: list[str] | None = None) -> int:
    """Launch the installed browser application on a local loopback port."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="topos-ui", description="Launch the CoChem-TOPOS browser interface")
    parser.add_argument("--port", type=int, default=8501, help="Local HTTP port (default: 8501)")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        from streamlit.web import cli as streamlit_cli
    except ImportError:
        print("Install browser support with: pip install 'cochem-topos[ui]'", file=sys.stderr)
        return 2
    script = Path(__file__).with_name("streamlit_app.py")
    result = streamlit_cli.main(
        args=["run", str(script), "--server.address", "127.0.0.1", "--server.port", str(args.port),
              "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        prog_name="topos-ui", standalone_mode=False,
    )
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
