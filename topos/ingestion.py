"""Import independent starting geometries without impersonating native execution.

Native GOAT/CREST comments are retained observations, never validated TOPOS
energies. Every imported frame is submitted to the requested real calculation
before the ordinary comparison, review and publication gates can accept it.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Literal

from pydantic import Field, StrictInt, model_validator

from .chemistry import from_xyz, to_xyz, validate_chemistry
from .models import Artifact, Contract, Molecule, RunRecord, RunRequest, utc_now
from .storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest

if TYPE_CHECKING:
    from .config import SystemConfig

MAX_IMPORT_BYTES = 64 * 1024 * 1024
MAX_IMPORT_FRAMES = 10000
IMPORT_SCHEMA = "topos-external-starting-state/0.1.0"
ENTRYPOINTS = (
    "geometry", "refinement", "topology-seeds", "stage-b-ensemble", "leading-isomers",
    "entropy-seeds", "ml-search-seeds", "isolated-monomers",
)
MATRIX_TARGETS = {
    "topology-seeds": ("topology_seeds", {"T1-10s", "T1-1h", "T1-1mo"}),
    "stage-b-ensemble": ("stage_b_ensemble", {"T1-3d"}),
    "leading-isomers": ("leading_isomers", {"T1-12h"}),
    "entropy-seeds": ("entropy_seeds", {"T1-1d"}),
    "ml-search-seeds": ("ml_search_seeds", {"T1-30min", "T1-1w"}),
    "isolated-monomers": ("isolated_monomer_references", {"T3O-1min", "T3O-3h"}),
}
IDENTITY_FIELDS = (
    "symbols", "atom_ids", "isotopes", "charge", "multiplicity", "fragments",
    "fragment_states", "bonds", "environment", "stereochemistry",
)


class ExternalSource(Contract):
    """Caller attribution, explicitly distinguished from observed engine evidence."""

    engine: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    method: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    description: str = Field(min_length=1)
    coordinate_units: Literal["angstrom"] = "angstrom"
    energy_units: Literal["hartree"] | None = None
    atom_order: list[str] = Field(min_length=1, max_length=MAX_IMPORT_FRAMES)
    original_calculation_status: Literal["unknown", "completed", "partial", "failed"] = "unknown"
    source_reference: str | None = None

    @model_validator(mode="after")
    def nonempty_attribution(self) -> ExternalSource:
        for name in ("engine", "engine_version", "method", "created_by", "description"):
            if not getattr(self, name).strip():
                raise ValueError(f"External source {name} must be a nonempty declaration")
        if any(not value.strip() for value in self.atom_order):
            raise ValueError("Declared source atom IDs must be nonempty")
        if self.source_reference is not None and not self.source_reference.strip():
            raise ValueError("An explicitly supplied source reference must be nonempty")
        return self


class ExternalImportSpec(Contract):
    format: Literal["xyz", "crest-ensemble", "goat-ensemble"]
    reference: Molecule
    source: ExternalSource
    entrypoint: Literal[
        "geometry", "refinement", "topology-seeds", "stage-b-ensemble", "leading-isomers",
        "entropy-seeds", "ml-search-seeds", "isolated-monomers",
    ] = "refinement"
    selected_frames: list[StrictInt] | None = Field(default=None, max_length=MAX_IMPORT_FRAMES)

    @model_validator(mode="after")
    def explicit_conventions(self) -> ExternalImportSpec:
        if self.source.atom_order != self.reference.atom_ids:
            raise ValueError("Declared source atom_order must match the reference atom IDs in order")
        if self.format != "xyz" and self.source.energy_units != "hartree":
            raise ValueError("Native ensemble energy comments require explicitly declared hartree units")
        if self.format == "xyz" and self.source.energy_units is not None:
            raise ValueError("Geometry-only XYZ imports do not interpret comment-line energies")
        if self.format == "crest-ensemble" and self.source.engine.lower() != "crest":
            raise ValueError("CREST ensemble format requires a declared CREST source")
        if self.format == "goat-ensemble" and self.source.engine.lower() not in {"orca", "goat"}:
            raise ValueError("GOAT ensemble format requires a declared ORCA/GOAT source")
        if self.selected_frames is not None and (
            not self.selected_frames or any(type(i) is not int or i < 1 for i in self.selected_frames)
            or len(set(self.selected_frames)) != len(self.selected_frames)
        ):
            raise ValueError("Select distinct positive one-based frame indices")
        return self


class ExternalFrame(Contract):
    source_index: int = Field(ge=1)
    molecule: Molecule
    observed_energy_hartree: float | None = None
    metadata: dict = Field(default_factory=dict)


class ExternalImportPreview(Contract):
    schema_version: Literal["topos-external-starting-state/0.1.0"] = IMPORT_SCHEMA
    original_filename: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0, le=MAX_IMPORT_BYTES)
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frames: list[ExternalFrame] = Field(min_length=1, max_length=MAX_IMPORT_FRAMES)
    selected_indices: list[int]
    validation_status: Literal["requires-real-calculation"] = "requires-real-calculation"
    warnings: list[str] = Field(default_factory=lambda: [
        "Source method, atom identity and completion status are caller declarations, not execution attestation.",
        "Element order is checked; permutations of identical elements require the declared stable atom mapping.",
        "Observed source energies are retained without ranking, populations or native scientific acceptance.",
    ])


def _read_bounded(path: Path | str) -> tuple[Path, bytes]:
    chosen = Path(path).expanduser()
    if chosen.is_symlink() or not chosen.is_file():
        raise ValueError("An external input must be a regular local file, not a symlink or archive")
    if not 0 < chosen.stat().st_size <= MAX_IMPORT_BYTES:
        raise ValueError(f"An external input must contain 1–{MAX_IMPORT_BYTES} bytes")
    with chosen.open("rb") as handle:
        raw = handle.read(MAX_IMPORT_BYTES + 1)
    if not 0 < len(raw) <= MAX_IMPORT_BYTES:
        raise ValueError("External input changed size or exceeds the bounded upload limit")
    try:
        raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("External inputs must be UTF-8 text; binary archives are not accepted") from exc
    if b"\x00" in raw:
        raise ValueError("External inputs must be text without NUL bytes")
    return chosen.resolve(strict=True), raw


def _validate_frame(reference: Molecule, molecule: Molecule) -> None:
    from .science import validate_stereochemical_preservation
    from .workflow import _topology_preserved

    if any(getattr(reference, field) != getattr(molecule, field) for field in IDENTITY_FIELDS):
        raise ValueError("External geometry changes molecular state, atom order or fragment identity")
    result = validate_chemistry(molecule)
    if result["status"] != "valid":
        raise ValueError("External geometry is physically suspect: " + "; ".join(result["issues"]))
    if not _topology_preserved(reference, molecule):
        raise ValueError("External geometry changes inferred covalent topology; declare a separate chemical state")
    if validate_stereochemical_preservation(reference, molecule)["status"] != "preserved":
        raise ValueError("External geometry does not preserve the declared mapped stereochemistry")


def preview_external(path: Path | str, spec: ExternalImportSpec | dict) -> ExternalImportPreview:
    """Validate actual bytes using existing native readers, without creating a run."""
    spec = ExternalImportSpec.model_validate(spec)
    original, raw = _read_bounded(path)
    if spec.format != "xyz":
        # Bound allocation before a native parser constructs per-frame models.
        lines = raw.decode("utf-8").splitlines()
        cursor, count, natoms = 0, 0, len(spec.reference.symbols)
        while cursor < len(lines):
            if not lines[cursor].strip():
                cursor += 1
                continue
            if lines[cursor].strip() != str(natoms) or cursor + natoms + 2 > len(lines):
                raise ValueError("External ensemble has an incompatible count or incomplete frame")
            count += 1
            if count > MAX_IMPORT_FRAMES:
                raise ValueError(f"External ensembles are limited to {MAX_IMPORT_FRAMES} frames")
            cursor += natoms + 2
    # Parse a fixed byte capture, so concurrent modifications cannot separate
    # the digest shown to the user from the geometry actually read by a parser.
    with tempfile.TemporaryDirectory(prefix="cochem-topos-intake-") as temporary:
        captured = Path(temporary) / "source.txt"
        captured.write_bytes(raw)
        if spec.format == "xyz":
            frames = [ExternalFrame(source_index=1, molecule=from_xyz(raw.decode("utf-8"),
                                                                       template=spec.reference))]
        else:
            from .goat import parse_goat_ensemble
            from .sampling import parse_crest_ensemble

            parser = parse_goat_ensemble if spec.format == "goat-ensemble" else parse_crest_ensemble
            frames = [ExternalFrame(source_index=frame.source_index, molecule=frame.molecule,
                                    observed_energy_hartree=frame.energy_hartree,
                                    metadata=frame.metadata)
                      for frame in parser(captured, spec.reference)]
    if len(frames) > MAX_IMPORT_FRAMES:
        raise ValueError(f"External ensembles are limited to {MAX_IMPORT_FRAMES} frames")
    for frame in frames:
        _validate_frame(spec.reference, frame.molecule)
    indices = spec.selected_frames if spec.selected_frames is not None else [f.source_index for f in frames]
    if any(index > len(frames) for index in indices):
        raise ValueError("Selected external frame does not exist")
    return ExternalImportPreview(original_filename=original.name,
                                 source_sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw),
                                 spec_sha256=digest_json(spec.model_dump(mode="json")),
                                 frames=frames, selected_indices=indices)


def preview_external_bytes(raw: bytes, spec: ExternalImportSpec | dict, *,
                           filename: str = "uploaded-source.txt") -> ExternalImportPreview:
    """Validate a bounded browser/notebook upload with the identical native readers."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_IMPORT_BYTES:
        raise ValueError("External upload must be bounded nonempty bytes")
    name = Path(filename.replace("\\", "/")).name
    if not name or "\x00" in name:
        raise ValueError("An external upload requires a valid original filename")
    with tempfile.TemporaryDirectory(prefix="cochem-topos-upload-preview-") as temporary:
        captured = Path(temporary) / "source.txt"
        captured.write_bytes(raw)
        preview = preview_external(captured, spec)
    preview.original_filename = name
    return preview


def _selected(preview: ExternalImportPreview, spec: ExternalImportSpec) -> list[ExternalFrame]:
    if preview.spec_sha256 != digest_json(spec.model_dump(mode="json")):
        raise IntegrityError("External preview does not match the explicit import specification")
    expected = spec.selected_frames if spec.selected_frames is not None else [f.source_index for f in preview.frames]
    if preview.selected_indices != expected or any(not 1 <= i <= len(preview.frames) for i in expected):
        raise IntegrityError("External preview frame selection differs from the explicit specification")
    frames = [preview.frames[index - 1] for index in preview.selected_indices]
    for frame in frames:
        _validate_frame(spec.reference, frame.molecule)
    return frames


def prepare_external_request(preview: ExternalImportPreview, spec: ExternalImportSpec | dict,
                             request: RunRequest | dict) -> RunRequest:
    """Bind an explicitly selected starting stage to the ordinary typed request."""
    spec = ExternalImportSpec.model_validate(spec)
    request = RunRequest.model_validate(request)
    selected = _selected(preview, spec)
    geometries = [frame.molecule for frame in selected]
    values = request.model_dump(mode="json")
    prior_sources = values["metadata"].get("external_starting_states", [])
    if not isinstance(prior_sources, list) or any(not isinstance(item, dict) for item in prior_sources):
        raise ValueError("Reserved external_starting_states provenance must be a list of structured source declarations")
    if spec.entrypoint != "isolated-monomers" and any(
        getattr(request.molecule, field) != getattr(spec.reference, field) for field in IDENTITY_FIELDS
    ):
        raise ValueError("The requested calculation and imported source declare different molecular identities")
    source = {"source_sha256": preview.source_sha256, "format": spec.format,
              "entrypoint": spec.entrypoint, "declaration": spec.source.model_dump(mode="json"),
              "source_frames": preview.selected_indices,
              "execution_attestation": "external-declaration; not a TOPOS calculation"}
    if spec.entrypoint == "geometry":
        if len(geometries) != 1:
            raise ValueError("A geometry entrypoint requires exactly one explicitly selected frame")
        if request.starting_geometries:
            raise ValueError("Explicit starting_geometries already exist; a geometry import cannot silently replace or bypass them")
        if request.purpose not in {"search", "optimize", "energy", "gradient", "frequency",
                                   "thermochemistry", "association", "matrix"}:
            raise ValueError("The requested purpose has no supported geometry entrypoint")
        if request.purpose == "matrix":
            from .matrix_workflow import MatrixInputs

            existing = MatrixInputs.model_validate(request.matrix_inputs)
            if any(getattr(existing, key) for key in (
                "topology_seeds", "stage_b_ensemble", "leading_isomers", "entropy_seeds",
                "ml_search_seeds", "goat_ensemble", "crest_ensemble",
            )):
                raise ValueError("Existing matrix starting states may override the selected geometry; "
                                 "use the matching named entrypoint with a fresh request")
        values["molecule"] = geometries[0].model_dump(mode="json")
    elif spec.entrypoint == "refinement":
        if request.purpose not in {"search", "optimize", "energy", "gradient"}:
            raise ValueError("Multi-frame refinement supports search, optimize, energy or gradient requests")
        if request.starting_geometries:
            raise ValueError("Explicit starting_geometries already exist; import does not silently replace them")
        source["enumeration_policy"] = "explicit external refinement entrypoint; no new native enumeration"
        source["previous_request_search_algorithm"] = request.search_algorithm
        values.update(molecule=geometries[0].model_dump(mode="json"),
                      starting_geometries=[m.model_dump(mode="json") for m in geometries],
                      search_algorithm="jiggle-quench", sampler_nci=False,
                      sampler_profile="crest-imtdgc-v1", abcluster_options=None,
                      n_candidates=len(geometries))
    else:
        from .matrix_workflow import MatrixInputs, _validate_ensemble

        target, rows = MATRIX_TARGETS[spec.entrypoint]
        if request.purpose != "matrix" or request.matrix_row_id not in rows:
            raise ValueError(f"{spec.entrypoint} applies only to matrix rows {', '.join(sorted(rows))}")
        inputs = MatrixInputs.model_validate(values["matrix_inputs"]).model_dump(mode="json")
        if spec.entrypoint == "isolated-monomers":
            from .fragments import _matching_fragment, split_fragments

            references = split_fragments(request.molecule)
            by_ids = {tuple(m.atom_ids): m for m in references}
            for geometry in geometries:
                reference = by_ids.get(tuple(geometry.atom_ids))
                if reference is None:
                    raise ValueError("Imported monomer atom IDs do not identify a declared complex fragment")
                _matching_fragment(reference, geometry)
                if request.matrix_row_id == "T3O-3h":
                    matches = [p for p in inputs["r2_monomer_provenance"]
                               if p["geometry_sha256"] == digest_json(geometry.model_dump(mode="json"))]
                    if (len(matches) != 1 or matches[0]["method"] != spec.source.method
                            or not spec.source.source_reference
                            or matches[0]["source"] != spec.source.source_reference):
                        raise ValueError("R2 monomer import requires matching typed high-level geometry, method and source provenance")
            existing = {tuple(m["atom_ids"]): (m, declaration)
                        for m, declaration in zip(inputs[target], inputs["isolated_monomer_sources"], strict=True)}
            for geometry in geometries:
                key = tuple(geometry.atom_ids)
                if key in existing:
                    raise ValueError("An isolated monomer reference is already supplied for this fragment")
                existing[key] = (geometry.model_dump(mode="json"),
                                 spec.source.source_reference or
                                 f"external-source-sha256:{preview.source_sha256}; {spec.source.description}")
            ordered = [existing[tuple(m.atom_ids)] for m in references if tuple(m.atom_ids) in existing]
            inputs[target] = [item[0] for item in ordered]
            inputs["isolated_monomer_sources"] = [item[1] for item in ordered]
        else:
            if inputs[target]:
                raise ValueError(f"Explicit {target} already exist; import does not silently replace them")
            minimum = 3 if spec.entrypoint == "topology-seeds" else 2 if spec.entrypoint == "leading-isomers" else 1
            maximum = 9 if request.matrix_row_id == "T1-10s" else 3 if spec.entrypoint == "leading-isomers" else MAX_IMPORT_FRAMES
            _validate_ensemble(request.molecule, geometries, minimum=minimum, maximum=maximum,
                               distinct=spec.entrypoint in {"topology-seeds", "leading-isomers", "entropy-seeds"})
            inputs[target] = [m.model_dump(mode="json") for m in geometries]
        values["matrix_inputs"] = MatrixInputs.model_validate(inputs).model_dump(mode="json")
    values["metadata"]["external_starting_states"] = [*prior_sources, source]
    return RunRequest.model_validate(values)


def _write_original(destination: Path, raw: bytes) -> None:
    with destination.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def stage_external_many(inputs: list[tuple[Path | str, ExternalImportSpec | dict]],
                        request: RunRequest | dict, output_root: Path | str, *,
                        supporting_files: list[Path | str] | None = None) -> RunRecord:
    """Preserve original uploads and publish a queued, recoverable canonical run.

    Multiple files are useful for distinct isolated monomers. Associated native
    .out/.inp/.log text can be retained, but never interpreted as native success.
    Every destination name is generated; caller filenames are only metadata.
    """
    if not inputs or len(inputs) > MAX_IMPORT_FRAMES:
        raise ValueError("Supply a bounded nonempty list of explicit external inputs")
    if len(inputs) > 1 and any(ExternalImportSpec.model_validate(spec).entrypoint != "isolated-monomers"
                               for _, spec in inputs):
        raise ValueError("Multiple inputs must identify distinct isolated monomer references; ensemble files contain their own frames")
    prepared = RunRequest.model_validate(request)
    captures = []
    total_bytes = 0
    for path, specification in inputs:
        spec = ExternalImportSpec.model_validate(specification)
        preview = preview_external(path, spec)
        origin, raw = _read_bounded(path)
        if hashlib.sha256(raw).hexdigest() != preview.source_sha256:
            raise IntegrityError("External source changed after its validation preview")
        prepared = prepare_external_request(preview, spec, prepared)
        captures.append((origin.name, raw, preview, spec))
        total_bytes += len(raw)
        if total_bytes > MAX_IMPORT_BYTES:
            raise ValueError("Combined external uploads exceed the bounded import limit")
    supplements = []
    for path in supporting_files or []:
        origin, raw = _read_bounded(path)
        if origin.suffix.lower() not in {".out", ".log", ".inp", ".json", ".txt", ".xyz", ".stdout", ".stderr"}:
            raise ValueError("Supporting inputs must be explicit native text or JSON files, not archives")
        supplements.append((origin.name, raw))
        total_bytes += len(raw)
        if total_bytes > MAX_IMPORT_BYTES:
            raise ValueError("Combined external uploads exceed the bounded import limit")
    if total_bytes > MAX_IMPORT_BYTES:
        raise ValueError("Combined external uploads exceed the bounded import limit")
    if any(spec.entrypoint == "isolated-monomers" for _, _, _, spec in captures):
        from .fragments import assemble_monomer_seed

        assemble_monomer_seed(prepared.molecule, [Molecule.model_validate(m)
                                               for m in prepared.matrix_inputs["isolated_monomer_references"]])
        if prepared.matrix_row_id == "T3O-3h":
            values = prepared.model_dump(mode="json")
            provenance = {p["geometry_sha256"]: p for p in values["matrix_inputs"]["r2_monomer_provenance"]}
            values["matrix_inputs"]["r2_monomer_provenance"] = [
                provenance[digest_json(m)] for m in values["matrix_inputs"]["isolated_monomer_references"]
            ]
            prepared = RunRequest.model_validate(values)
    # Workflow owns output-root validation, including the source repository guard.
    from .capabilities import capability_report
    from .references import method_references
    from .workflow import Workflow, software_provenance

    workflow = Workflow(output_root)
    record = RunRecord(request=prepared)
    run_dir = workflow.output_root / record.run_id
    run_dir.mkdir(exist_ok=False)
    originals = run_dir / "external-inputs"
    originals.mkdir()
    manifest = {"schema_version": IMPORT_SCHEMA, "imported_at": utc_now(),
                "execution_attestation": "not-executed", "inputs": [], "supporting_files": []}
    for index, (filename, raw, preview, spec) in enumerate(captures, 1):
        destination = originals / f"input-{index:04d}.txt"
        _write_original(destination, raw)
        relative = destination.relative_to(run_dir).as_posix()
        record.artifacts.append(Artifact(path=relative, sha256=preview.source_sha256,
                                         size_bytes=len(raw), role="external-original-input"))
        manifest["inputs"].append({"path": relative, "original_filename": filename,
                                   "spec": spec.model_dump(mode="json"),
                                   "preview": preview.model_dump(mode="json")})
    for index, (filename, raw) in enumerate(supplements, 1):
        destination = originals / f"support-{index:04d}.txt"
        _write_original(destination, raw)
        relative = destination.relative_to(run_dir).as_posix()
        sha = hashlib.sha256(raw).hexdigest()
        record.artifacts.append(Artifact(path=relative, sha256=sha, size_bytes=len(raw),
                                         role="external-unvalidated-supporting-input"))
        manifest["supporting_files"].append({"path": relative, "original_filename": filename,
                                             "sha256": sha, "size_bytes": len(raw)})
    manifest_path = originals / "manifest.json"
    atomic_json(manifest_path, manifest)
    request_path = run_dir / "request.json"
    atomic_json(request_path, prepared.model_dump(mode="json"))
    geometry_path = run_dir / "input.xyz"
    geometry_path.write_text(to_xyz(prepared.molecule), encoding="utf-8")
    for path, role in ((manifest_path, "external-import-manifest"), (request_path, "request"),
                       (geometry_path, "input-geometry")):
        record.artifacts.append(Artifact(path=path.relative_to(run_dir).as_posix(),
                                         sha256=file_digest(path), size_bytes=path.stat().st_size, role=role))
    record.metadata.update(run_dir=str(run_dir),
                           request_sha256=digest_json(prepared.model_dump(mode="json")),
                           input_sha256=digest_json(prepared.molecule.model_dump(mode="json")),
                           software=software_provenance(), citations=method_references(prepared.engine, prepared.method),
                           capability_profile=capability_report(), sampling_complete=False,
                           external_import={"manifest_path": manifest_path.relative_to(run_dir).as_posix(),
                                            "manifest_sha256": file_digest(manifest_path),
                                            "validation_status": "requires-real-calculation", "execution_kind": "not-executed"},
                           stationary_point_classification="not-evaluated: imported starting state")
    RunStore(run_dir).commit(record)
    return record


def stage_external(path: Path | str, spec: ExternalImportSpec | dict,
                   request: RunRequest | dict, output_root: Path | str, *,
                   supporting_files: list[Path | str] | None = None) -> RunRecord:
    """Stage one input; execute with the ordinary ``Workflow.resume`` API."""
    return stage_external_many([(path, spec)], request, output_root,
                               supporting_files=supporting_files)


def execute_external(run_dir: Path | str, *, cancel_event: Event | None = None,
                     config: SystemConfig | None = None) -> RunRecord:
    """Execute a staged import explicitly; later continuations use normal resume.

    A pristine hosted import receives its first dispatch only through this
    explicit entrypoint. Ordinary remote resume still only polls an owned job.
    """
    from .workflow import Workflow

    store = RunStore(run_dir)
    store.verify()
    record = RunRecord.model_validate(store.load())
    imported = record.metadata.get("external_import")
    if not isinstance(imported, dict) or imported.get("validation_status") != "requires-real-calculation":
        raise ValueError("The selected run is not a canonical staged external import")
    workflow = Workflow(store.run_dir.parent, config=config)
    if (record.request.calculation_environment in {"github-actions", "github-actions-hosted"}
            and "remote_dispatch" not in record.metadata):
        if record.status != "queued" or record.attempts or record.candidates:
            raise IntegrityError("Only a pristine queued external import can receive an initial remote dispatch")
        from .remote_workflow import run_remote

        return run_remote(workflow, record.request, cancel_event=cancel_event, staged_record=record)
    if record.request.calculation_environment == "workstation" and "workstation_dispatch" not in record.metadata:
        if record.status != "queued" or record.attempts or record.candidates:
            raise IntegrityError("Only a pristine queued external import can be sent to the workstation")
        from .workstation import run_workstation

        return run_workstation(workflow, record.request, cancel_event=cancel_event, staged_record=record)
    return workflow.resume(store.run_dir, cancel_event=cancel_event)
