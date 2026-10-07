"""Execute the TOPOS matrix recipes that have complete registered runtime adapters.

Each scientific component is an ordinary durable Workflow child. A recipe is never
executed from the source document's shell text, and a single successful component
cannot certify a compound row whose other components are unavailable.
"""
from __future__ import annotations

import time
from pathlib import Path
from threading import Event
from typing import Any, Literal

import numpy as np
from pydantic import Field

from .cfour_counterpoise import CfourCounterpoiseGeometryProtocol
from .correlated import CorrelatedMethod
from .correlated_counterpoise import CorrelatedCounterpoiseProtocol
from .data.runtime_recipes import EXECUTABLE_ROWS, IMPLEMENTED_BRANCH_ROWS
from .energy_composite import EnergyCompositeProtocol
from .entropy import EntropyOptions
from .external_engines import ExternalProtocol
from .higher_composite import HigherGeometryProtocol
from .matrix_r2 import R2MonomerProvenance, R2VPT2Options
from .matrix_sources import SourceEnsembleInput
from .method_matrix import (
    MATRIX_REVISION,
    BackendCapability,
    HardwareSpec,
    plan_route,
    resolve_row,
)
from .ml import ModelManifest
from .ml_training import MACETrainingOptions, TrainingDatasetSpec
from .ml_workflow import RigidMLGrid
from .models import (
    Artifact,
    Attempt,
    Candidate,
    Contract,
    Molecule,
    Quantity,
    RunRecord,
    RunRequest,
)
from .month_geometry import MonthCorrectionProtocol
from .orca_f12_composite import OrcaF12CompositeProtocol
from .orca_numerical_geometry import OrcaF12GeometryProtocol
from .scans import ScanCoordinate, ScanOptions
from .storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest


def execution_support_report() -> dict[str, Any]:
    """Report code coverage without turning availability into scientific validation."""
    from .data.reviewed_matrix_v010 import RECIPES
    from .method_matrix import load_catalog, reviewed_revision, unavailable_by_design

    catalog = load_catalog()
    topos_rows = [r for r in catalog.rows if r.owner == "TOPOS"]
    unresolved = {
        "T3C-1mo": "Conditional explicit HF X2C/native-default HF DBOC corrected geometry is implemented for H/C/N/O/F without explicit isotopes. Numeric native masses are not attested, so all rotor constants and full original-row completion remain withheld.",
    }
    return {
        "catalog_revision": catalog.revision,
        "catalog_source_sha256": catalog.source_sha256,
        "catalog_rows": len(catalog.rows),
        "topos_owned_rows": len(topos_rows),
        "topos_track_gaps": [r.row_id for r in topos_rows if r.track_gap],
        "unavailable_by_design": [disposition for r in topos_rows
                                  if (disposition := unavailable_by_design(r.row_id)) is not None],
        "unresolved_track_gaps": [r.row_id for r in topos_rows if r.track_gap and unavailable_by_design(r.row_id) is None],
        "compiled_complete_recipes": sorted(EXECUTABLE_ROWS),
        "compiled_recipe_count": len(EXECUTABLE_ROWS),
        "implemented_partial_branches": sorted(IMPLEMENTED_BRANCH_ROWS),
        "source_conflict_rows": [r.row_id for r in catalog.rows if r.source_conflicts],
        "reviewed_scientific_revisions": {key: reviewed_revision(key) for key in RECIPES},
        "revision_scope": "Original v4 rows remain archived verbatim. Compiled revised rows require their explicit separately hashed reviewed variant; source benchmark claims are not transferred.",
        "conditional_recipe_resolutions": {
            "T1-3h": {
                "source_literal": "ORCA Freq (native analytic Hessian)",
                "implemented_derivative": "native ORCA analytic Hessian with separate real reference-gradient stationarity evidence",
                "optional_explicit_resolution": "physical-central-gradient-hessian-v1 uses central differences of actual analytic gradients",
                "source_attribution_limit": "Native CREST --screen disables origin tracking; only input counts/exact input overlap and combined-union final provenance are established",
            },
            "T3O-12h": {"required_explicit_resolution": "junchs-same-basis-core-valence-v1",
                         "source_conflict": "source definitions differ for the MP2 core-valence subtraction",
                         "implemented_variant": "ae minus fc at the same cc-pwCVTZ basis; full independent internal-coordinate chart required"},
            "T3O-3d": {"required_explicit_resolution": "autoci-conventional-transformation-v1",
                        "source_conflict": "MDCI AO-direct options cannot be transplanted to AUTOCI",
                        "implemented_variant": "canonical AUTOCI analytic gradients and native integral transformation; no AO-direct claim"},
            "T3O-1d": {"required_explicit_resolution": "orca-f12d-numerical-geometry-dz-v1",
                        "implemented_variant": "canonical frozen-core ORCA F12D/RI with exact cc-pVDZ-F12/CABS/cc-pVDZ/C; checked numerical energy derivatives and explicit stationarity controls"},
            "T3O-1mo": {"required_explicit_resolution": "orca-f12d-numerical-geometry-tz-v1",
                         "implemented_variant": "canonical frozen-core ORCA F12D/RI with exact cc-pVTZ-F12/CABS/cc-pVTZ/C; checked numerical energy derivatives, not Molpro F12b",
                         "compatibility_branch": "orca-f12-reference-singlepoint-v1 remains explicitly energy-only and does not complete the revised geometry protocol"},
            "T5-12h": {"required_input": "complete correlated_protocol with exact correlation fitting basis and core convention",
                        "implemented_variant": "plain DLPNO-CCSD(T1) with cc-pVDZ-F12 orbital basis and native !LED; not an F12 Hamiltonian"},
            "T5-1d": {"required_input": "complete DLPNO protocol; identical reference/settings except consecutive TCutPNO6/7",
                       "implemented_variant": "HF + correlation6 + 1.5*(correlation7-correlation6), then frozen fragment subtraction"},
            "T5-3d": {"required_input": "explicit RI correlation fitting basis omitted by the source row",
                       "implemented_variant": "canonical CCSD(T)-F12D/RI with cc-pVTZ-F12 and its CABS; never relabeled F12b"},
            "T5-3h": {"required_explicit_resolution": "orca-f12d-composite-interaction-v1",
                       "implemented_variant": "five exact ORCA protocols per frozen complex/fragment: F12D/RI base, separate HF+CABS exponential and F12-correlation inverse-power CBS, same-basis MP2 ae-fc correction",
                       "scientific_difference": "Explicit reviewed ORCA approximation; not archived junChS-F12b or its A14 benchmark"},
            "T5-30min": {"required_explicit_resolution": "native-composite-rawinteraction-v1",
                         "implemented_variant": "native r2SCAN-3c frozen interaction including built-in gCP; no separate CP/half-CP claim"},
            "T5-1w": {"required_input": "energy_composite with explicit consecutive CBS bases, HF exponential coefficient, correlation power, core-valence and full-triples bases",
                      "implemented_variant": "eight genuine native CFOUR components per complex/fragment; no named HEAT/Wn recipe or benchmark-accuracy transfer"},
            "T3C geometry rows": {"required_explicit_resolution": "cfour-topos-cartesian-optimizer-v1",
                                  "implemented_variant": "TOPOS Cartesian L-BFGS-B using actual CFOUR analytic gradients; not the source's native internal-coordinate optimizer"},
            "T3C-1w": {"required_input": "higher_geometry with explicit consecutive CBS bases, geometry exponent, CV/full-triples/full-quadruples bases and independent coordinate chart",
                       "implemented_variant": "seven optimizations use native analytic derivatives; the full-quadruples optimization uses checked h/h2 central differences of genuine CFOUR 2.1 NCC CCSDTQ energies",
                       "derivative_limit": "No native CCSDTQ analytic-gradient claim; same torsional-basin membership remains an explicit unverified assumption"},
            "T3O-1w": {"required_explicit_resolution": "cfour-relaxed-counterpoise-geometry-v1",
                       "required_input": "cfour_counterpoise with every native basis/core/chart/numerical derivative choice",
                       "implemented_variant": "sixteen component optimizations: eight raw and eight relaxed CP total surfaces; separate parameter-wise composite geometry bracket",
                       "validation_limit": "Strict conditional CFOUR 2.1 ghost/core/native output contract; live correlated ghost acceptance remains pending, no benchmark or verified composite minimum claim"},
            "T3O-3h": {"required_explicit_resolution": "r2-b3lyp-d4-vpt2-transfer-v1",
                       "implemented_variant": "frozen QZ target plus ordinary DLPNO CP; independently relaxed strict B3LYP-D4/TZVPP native VPT2 reference and explicit axis/mass matched correction transfer",
                       "validation_limit": "Approximate composite with explicitly changed reference functional; archived wB97X-V/VV10 native VPT2 remains unsupported, no automatic fallback or experimental accuracy claim"},
            "T3C-1mo": {"required_explicit_resolution": "cfour-native-default-mass-corrected-geometry-v1",
                        "implemented_variant": "conditional higher composite plus paired HF X2C and native-default HF DBOC geometry increments",
                        "completion_limit": "All rotor constants withheld because numeric native masses are unattested; never certifies the full original row"},
            "T1-30min": {"required_input": "explicit AIMNet2 checkpoint manifest and concurrent ML/ORCA resource allocation",
                         "implemented_variant": "native GOAT-EXPLORE ExtOpt followed by actual common r2SCAN-3c refinement and Stage-A native CREGEN; ML energies remain raw enumeration observations"},
            "T1-1w": {"required_input": "100–500 provenance-verified DFT configurations, group-disjoint data partitions, explicit GPU training/model/allocation, and hash-verified CREST 3.0.2+topos-generic-paths-v1",
                      "implemented_variant": "float64 MACE fine-tuning and held-out evaluation; both native GOAT and patched CREST use the identical trained checkpoint; real common r2SCAN-3c refinement and native Stage-A CREGEN",
                      "validation_limit": "Native reduced-profile CREST/MACE interface passed; no actual GPU training, combined native GOAT/ML or full default compound-campaign acceptance is claimed"},
            "T1-1d": {"required_input": "identical explicit seed geometries at 298.15 K",
                      "implemented_variant": "both native stopping criteria plus abs(GOAT Sconf-CREST Sconf)<0.1; excludes CREST total entropy and delta-RRHO"},
            "T1-1mo": {"required_input": "at least three distinct seeds and an exact coupled-cluster energy protocol",
                       "implemented_variant": "native GOAT-DIVERSITY and CREST-v4, actual common GFN2 refinement, native CREGEN and DLPNO reranking; no exhaustive-sampling proof"},
            "T5-1min": {"required_input": "independent float64 committee and explicit ml_no_energy_culling=True",
                        "implemented_variant": "frozen interaction and paired committee disagreement; retains all structures, no pruning without a separate G4 audit"},
        },
        "additional_adapter_recipes": [
            {"row_id": r.row_id, "purpose": r.purpose, "method": r.method_text,
             "source_conflicts": r.source_conflicts,
             "reason": unresolved.get(r.row_id, "A complete registered recipe adapter is required; the typed plan is available.")}
            for r in topos_rows if not r.track_gap and r.row_id not in EXECUTABLE_ROWS
        ],
        "torq_owned_rows": sum(r.owner == "TORQ" for r in catalog.rows),
        "validation_scope": "Catalog/compiled orchestration coverage only. Each execution must verify its real engines and scientific outputs.",
    }


class GoatOptions(Contract):
    deterministic: bool = False
    max_global_iterations: int = Field(default=100, ge=3, le=1000, strict=True)


class MLSearchAllocation(Contract):
    ml_threads: int = Field(ge=1)
    ml_memory_mb: int = Field(ge=64)
    orca_threads: int = Field(ge=1)
    orca_memory_mb: int = Field(ge=64)


class MatrixInputs(Contract):
    r2_vpt2: R2VPT2Options | None = None
    cfour_counterpoise: CfourCounterpoiseGeometryProtocol | None = None
    month_corrections: MonthCorrectionProtocol | None = None
    r2_counterpoise: CorrelatedCounterpoiseProtocol | None = None
    r2_monomer_provenance: list[R2MonomerProvenance] = Field(default_factory=list)
    orca_f12_composite: OrcaF12CompositeProtocol | None = None
    orca_numerical_geometry: OrcaF12GeometryProtocol | None = None
    higher_geometry: HigherGeometryProtocol | None = None
    energy_composite: EnergyCompositeProtocol | None = None
    source_resolution: Literal["native-composite-rawinteraction-v1", "orca-f12-reference-singlepoint-v1",
        "orca-f12d-numerical-geometry-dz-v1", "orca-f12d-numerical-geometry-tz-v1",
        "orca-f12d-composite-interaction-v1", "cfour-native-default-mass-corrected-geometry-v1",
        "cfour-relaxed-counterpoise-geometry-v1", "r2-separate-dft-vpt2-transfer-v1",
        "r2-b3lyp-d4-vpt2-transfer-v1"] | None = None
    external_protocol: ExternalProtocol | None = None
    external_resolution: Literal["cfour-topos-cartesian-optimizer-v1", "cfour-relaxed-counterpoise-geometry-v1"] | None = None
    entropy_seeds: list[Molecule] = Field(default_factory=list)
    entropy_options: EntropyOptions = Field(default_factory=EntropyOptions)
    ml_model: ModelManifest | None = None
    ml_grid: RigidMLGrid | None = None
    ml_gpu_index: int | None = Field(default=None, ge=0)
    ml_gpu_memory_mb: int | None = Field(default=None, gt=0)
    ml_no_energy_culling: bool = False
    ml_search_allocation: MLSearchAllocation | None = None
    ml_search_seeds: list[Molecule] = Field(default_factory=list)
    ml_training_dataset: TrainingDatasetSpec | None = None
    ml_training_options: MACETrainingOptions | None = None
    ml_max_requests: int = Field(default=10000, ge=1, le=1_000_000, strict=True)
    ml_receipt_mb: int = Field(default=1024, ge=4, le=65536, strict=True)
    correlated_protocol: CorrelatedMethod | None = None
    correlated_resolution: Literal["autoci-conventional-transformation-v1", "junchs-same-basis-core-valence-v1"] | None = None
    composite_coordinates: dict[str, Any] | None = None
    goat_ensemble: SourceEnsembleInput | None = None
    crest_ensemble: SourceEnsembleInput | None = None
    derivative_resolution: Literal["physical-central-gradient-hessian-v1"] | None = None
    leading_isomers: list[Molecule] = Field(default_factory=list)
    goat_options: GoatOptions = Field(default_factory=GoatOptions)
    scan_coordinates: list[ScanCoordinate] = Field(default_factory=list)
    scan_options: ScanOptions = Field(default_factory=ScanOptions)
    topology_seeds: list[Molecule] = Field(default_factory=list)
    stage_b_ensemble: list[Molecule] = Field(default_factory=list)
    isolated_monomer_references: list[Molecule] = Field(default_factory=list)
    isolated_monomer_sources: list[str] = Field(default_factory=list)
    # Additional capability declarations may narrow the compiled adapter profile,
    # never supply code, an executable path, or bypass the compiled recipe allowlist.
    backend_capabilities: list[BackendCapability] = Field(default_factory=list)


def runtime_recipe_capabilities() -> list[BackendCapability]:
    """Advertise adapter contracts; actual binary version and result are checked per child.

    Engine discovery is not successful execution. The evidence here describes the
    version-specific TOPOS input/parser adapters; the resulting run stores its own
    real version probes, executable digest and completion evidence.
    """
    elements = ["H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al",
                "Si", "P", "S", "Cl", "Ar", "K", "Ca", "Br", "Kr", "I", "Xe"]
    common = dict(verified=True, evidence="topos version-specific input/parser contract; engine validated during each execution",
                  supported_elements=elements, supported_multiplicities=list(range(1, 10)), supports_ions=True)
    return [
        BackendCapability(engine="xtb", engine_version="6.7.1", methods=["GFN2-xTB"],
                          operations=["optimize", "optimize-seeds", "interaction-energy", "relaxed-scan"], **common),
        BackendCapability(engine="orca", engine_version="6.1.1", methods=["GFN2-xTB", "r2SCAN-3c", "wB97X-V", "wB97M-V"],
                          bases=["def2-TZVPP", "jun-cc-pVTZ"], operations=["optimize", "optimize-ensemble", "hessian-ensemble", "relaxed-scan", "goat", "goat-entropy", "counterpoise", "interaction-energy"],
                          supports_rigid_fragments=True, **common),
        BackendCapability(engine="crest", engine_version="3.0.2", methods=["GFN2-xTB"],
                          operations=["crest-nci", "screen", "cregen-reporting", "entropy"], **common),
        BackendCapability(engine="topos", engine_version="0.1.0", methods=["junChS", "CPS(6/7)", "CBS+CV+fT+fQ"],
                          operations=["union", "composite-geometry", "pno-extrapolation", "entropy-convergence"], **common),
        BackendCapability(engine="orca", engine_version="6.1.1", methods=["MP2", "CCSD(T)", "AUTOCI-CCSD(T)", "DLPNO-CCSD(T1)", "CCSD(T)-F12D/RI"],
                          bases=["jun-cc-pVTZ", "jun-cc-pVQZ", "cc-pwCVTZ", "cc-pVDZ-F12", "cc-pVTZ-F12"],
                          operations=["energy", "optimize", "led-energy-decomposition", "rerank-ensemble"],
                          **{**common, "supported_multiplicities": [1]}),
        BackendCapability(engine="orca+crest", engine_version="6.1.1+3.0.2", methods=["GFN2-xTB"],
                          operations=["exhaustive-union"], **common),
    ]


def _input_data(request: RunRequest) -> MatrixInputs:
    data = getattr(request, "matrix_inputs", None)
    if not data:
        data = request.metadata.get("matrix_inputs", {})
    if not isinstance(data, dict):
        raise ValueError("matrix_inputs must be a structured object")
    return MatrixInputs.model_validate(data)


def _available_inputs(request: RunRequest, inputs: MatrixInputs) -> list[str]:
    available = ["molecule"]
    if request.molecule.fragments:
        available.append("fragments")
    if request.molecule.fragment_states:
        available.append("fragment_states")
    for name in ("topology_seeds", "stage_b_ensemble", "isolated_monomer_references", "scan_coordinates", "leading_isomers", "goat_ensemble", "crest_ensemble"):
        if getattr(inputs, name):
            available.append(name)
    if inputs.correlated_protocol is not None:
        available.extend(["correlated_protocol", "auxiliary_basis_protocol", "cc_protocol"])
    if inputs.composite_coordinates is not None:
        available.append("coordinate_parameterization")
    if inputs.entropy_seeds:
        available.append("same_seed_ensembles")
    if inputs.external_protocol is not None:
        available.extend(["internal_coordinates", "sapt_basis_protocol"])
    if inputs.energy_composite is not None:
        available.append("composite_basis_protocol")
    if inputs.higher_geometry is not None:
        available.extend(["composite_basis_protocol", "coordinate_parameterization"])
    if inputs.cfour_counterpoise is not None:
        available.append("cfour_counterpoise")
    for name in ('r2_monomer_provenance', 'r2_counterpoise', 'r2_vpt2'):
        if getattr(inputs, name):
            available.append(name)
    if inputs.month_corrections is not None:
        available.append("month_corrections")
        from .cfour_dboc import validate_default_mass_domain

        validate_default_mass_domain(request.molecule)
        available.append("native_default_mass_domain")
    if inputs.orca_numerical_geometry is not None:
        available.append("orca_numerical_geometry")
    if inputs.orca_f12_composite is not None:
        available.append("orca_f12_composite")
    if inputs.ml_model is not None:
        available.append("model_manifest")
    if inputs.ml_training_dataset is not None:
        available.append("reference_training_set")
    if inputs.ml_training_options is not None:
        available.append("training_protocol")
    if inputs.ml_search_allocation is not None:
        available.append("ml_search_allocation")
    if inputs.ml_grid is not None:
        available.append("scan_coordinates")
    if inputs.ml_no_energy_culling:
        available.append("explicit_no_culling_policy")
    return available


def _validate_ensemble(reference: Molecule, geometries: list[Molecule], *, minimum: int,
                       maximum: int = 10000, distinct: bool = False) -> None:
    if not minimum <= len(geometries) <= maximum:
        raise ValueError(f"This route requires {minimum}–{maximum} explicitly supplied geometries")
    identity_fields = ("symbols", "atom_ids", "isotopes", "charge", "multiplicity", "environment", "bonds",
                       "fragments", "fragment_states", "stereochemistry")
    fingerprints = set()
    for molecule in geometries:
        if any(getattr(reference, field) != getattr(molecule, field) for field in identity_fields):
            raise ValueError("Matrix seeds must preserve atom mapping, composition, state, environment and fragment identity")
        xyz = np.asarray(molecule.coordinates)
        distances = np.linalg.norm(xyz[:, None, :] - xyz[None, :, :], axis=-1)
        fingerprints.add(digest_json(np.round(distances, 7).tolist()))
    if distinct and len(fingerprints) != len(geometries):
        raise ValueError("Seed geometries must be distinct; rigidly translated/rotated copies do not add topology coverage")


def _validate_sampled_geometry(reference: Molecule, sampled: Molecule) -> None:
    """Check the original chemistry before a sampler frame becomes a child input."""
    from .science import validate_stereochemical_preservation
    from .workflow import _topology_preserved

    _validate_ensemble(reference, [sampled], minimum=1)
    if not _topology_preserved(reference, sampled):
        raise ValueError("Sampled geometry changed the original inferred covalent topology; raw source retained for separate chemical review")
    if validate_stereochemical_preservation(reference, sampled)["status"] != "preserved":
        raise ValueError("Sampled geometry does not preserve the original mapped stereochemistry; raw source retained for review")


def _child_request(parent: RunRequest, molecule: Molecule, *, engine: str, method: str,
                   purpose: str, remaining: float, basis: str | None = None,
                   constraints: dict[str, Any] | None = None, sampler: bool = False,
                   optimize_first: bool | None = None) -> RunRequest:
    data = parent.model_dump(mode="json")
    data.update(
        molecule=molecule.model_dump(mode="json"), engine=engine, method=method,
        engine_version={"xtb": "6.7.1", "orca": "6.1.1"}[engine], purpose=purpose, basis=basis,
        auxiliary_basis="def2/J" if method in {"wB97X-V", "wB97M-V"} else None, dispersion=None, solvent=None,
        profile_id="xtb-vtight-v1" if engine == "xtb" else "orca-mapping-v4.1",
        matrix_row_id=None, matrix_revision="topos-0.1.0-supported-profile-v1",
        budget_seconds=remaining, constraints=constraints or {}, search_algorithm="crest" if sampler else "jiggle-quench",
        device="cpu",
        sampler_profile="crest-nci-v1" if sampler else "crest-imtdgc-v1", sampler_nci=sampler,
        energy_window_kcal_mol=12.0 if sampler else parent.energy_window_kcal_mol,
        metadata={"matrix_parent_row": parent.matrix_row_id, "matrix_scope": "recipe component; not independent full-row certification"},
    )
    if "matrix_inputs" in data:
        data["matrix_inputs"] = {}
    if optimize_first is not None:
        data["thermochemistry_options"]["optimize_first"] = optimize_first
    return RunRequest.model_validate(data)


def _protocol_identity(request: RunRequest) -> str:
    data = request.model_dump(mode="json")
    data.pop("budget_seconds")
    return digest_json(data)


def _append_child(parent: RunRecord, child: RunRecord, parent_dir: Path, child_dir: Path,
                  task_id: str, *, include_candidates: bool = True) -> None:
    prefix = child_dir.relative_to(parent_dir)
    citations = parent.metadata.setdefault("citations", [])
    existing_citations = {digest_json(citation) for citation in citations}
    for citation in child.metadata.get("citations", []):
        if digest_json(citation) not in existing_citations:
            citations.append(citation)
            existing_citations.add(digest_json(citation))
    existing_attempts = {a.attempt_id for a in parent.attempts}
    for attempt in child.attempts:
        if attempt.attempt_id in existing_attempts:
            continue
        copied = attempt.model_copy(deep=True)
        copied.run_id = parent.run_id
        copied.metadata["matrix_component"] = {"task_id": task_id, "child_run_id": child.run_id}
        for artifact in copied.artifacts:
            artifact.path = (prefix / artifact.path).as_posix()
        parent.attempts.append(copied)
    if include_candidates:
        existing_candidates = {c.candidate_id for c in parent.candidates}
        for candidate in child.candidates:
            if candidate.candidate_id not in existing_candidates:
                copied = candidate.model_copy(deep=True)
                copied.sources.append("MATRIX:" + task_id)
                copied.metadata["matrix_component"] = {"task_id": task_id, "child_run_id": child.run_id}
                parent.candidates.append(copied)
    payload = child.model_dump(mode="json")
    child_record = child_dir / "matrix-child-records" / (digest_json(payload) + ".json")
    if child_record.exists():
        import json

        if json.loads(child_record.read_text()) != payload:
            raise IntegrityError("Completed matrix child evidence changed")
    else:
        atomic_json(child_record, payload)
    path = child_record.relative_to(parent_dir).as_posix()
    if not any(a.path == path for a in parent.artifacts):
        parent.artifacts.append(Artifact(path=path, sha256=file_digest(child_record),
                                         size_bytes=child_record.stat().st_size, role="matrix-child-record"))
    existing_paths = {a.path for a in parent.artifacts}
    for artifact in child.artifacts:
        copied = artifact.model_copy(deep=True)
        copied.path = (prefix / artifact.path).as_posix()
        if copied.path not in existing_paths:
            parent.artifacts.append(copied)
            existing_paths.add(copied.path)


def execute_matrix(workflow: Any, record: RunRecord, store: RunStore, deadline: float,
                   cancel_event: Event | None) -> None:
    """Persist a terminal gate failure without manufacturing component results."""
    try:
        _execute_matrix(workflow, record, store, deadline, cancel_event)
    except IntegrityError:
        raise
    except (ValueError, RuntimeError, OSError) as exc:
        from .models import utc_now

        for attempt in record.attempts:
            if attempt.status == "running":
                attempt.status, attempt.finished_at = "failed", utc_now()
                attempt.diagnostics["reason"] = "Matrix adapter interrupted: " + str(exc)
        record.status = "unsupported" if not record.attempts else "partial"
        record.metadata["termination_reason"] = str(exc)
        store.commit(record)


def _execute_matrix(workflow: Any, record: RunRecord, store: RunStore, deadline: float,
                   cancel_event: Event | None) -> None:
    """Execute supported full recipes, preserving completed components across resume."""
    from .workflow import Workflow

    request = record.request
    try:
        if not request.matrix_row_id or request.matrix_revision != MATRIX_REVISION:
            raise ValueError("Matrix execution requires an explicit row and pinned full-matrix revision")
        row = resolve_row(request.matrix_row_id, product=getattr(request, "matrix_product", "A"))
        inputs = _input_data(request)
        explicit_variants = {
            'T3O-3h': {'r2-separate-dft-vpt2-transfer-v1', 'r2-b3lyp-d4-vpt2-transfer-v1'},
            'T3O-1w': {'cfour-relaxed-counterpoise-geometry-v1'},
            'T3C-1mo': {'cfour-native-default-mass-corrected-geometry-v1'},
            'T3O-1d': {'orca-f12d-numerical-geometry-dz-v1'},
            'T3O-1mo': {'orca-f12d-numerical-geometry-tz-v1', 'orca-f12-reference-singlepoint-v1'},
            'T5-3h': {'orca-f12d-composite-interaction-v1'},
        }
        if row.row_id in explicit_variants and inputs.source_resolution not in explicit_variants[row.row_id]:
            raise ValueError(f"{row.row_id} requires an explicit compiled scientific source_resolution: "
                             + ', '.join(sorted(explicit_variants[row.row_id])))
        per_geometry_cap = getattr(request, "per_geometry_budget_seconds", None)
        if per_geometry_cap is not None and row.row_id in {"T1-1min", "T1-30min", "T1-3h", "T1-12h", "T1-1d", "T1-1w", "T1-1mo"}:
            raise ValueError("A per-geometry wall cap cannot currently be enforced inside native GOAT or CREST screening; use its explicit ensemble/workflow budget")
        if per_geometry_cap is not None and row.row_id.startswith("T2-"):
            existing = inputs.scan_options.per_point_budget_seconds
            inputs.scan_options.per_point_budget_seconds = min(per_geometry_cap, existing) if existing else per_geometry_cap
        gpu = {}
        if request.device == "gpu":
            if inputs.ml_model is None or workflow.base_runtime is None:
                raise ValueError("GPU matrix execution requires an explicit ML manifest and BASE hardware authority")
            runtime = workflow.base_runtime
            runtime.validate_resources(request.resources, engine=inputs.ml_model.backend,
                                       gpu_index=inputs.ml_gpu_index, gpu_memory_mb=inputs.ml_gpu_memory_mb)
            metrics = runtime.registry.hardware.gpu_compute_metrics
            devices = getattr(metrics, "devices", [])
            selected = [device for device in devices if device.device_index == inputs.ml_gpu_index]
            if len(selected) == 1:
                device = selected[0]
                measured_mb = int(device.vram_bytes / 1024**2) if device.vram_bytes else int(device.vram_gb * 1024)
                gpu_model = device.name
            elif metrics.device_count == 1 and inputs.ml_gpu_index == 0:
                measured_mb, gpu_model = int(metrics.vram_gb * 1024), metrics.gpu_profile
            else:
                raise ValueError("Multi-GPU planning requires per-device measured memory; aggregate VRAM cannot certify the selected GPU")
            if not gpu_model or gpu_model == "None" or inputs.ml_gpu_memory_mb > measured_mb:
                raise ValueError("Requested GPU allocation exceeds the individually measured BASE device")
            gpu = {"gpu_model": gpu_model, "gpu_memory_mb": inputs.ml_gpu_memory_mb}
        limits = HardwareSpec(cpu_threads=request.threads, memory_mb=request.memory_mb,
                              threads_per_worker=request.threads, memory_per_worker_mb=request.memory_mb,
                              fingerprint="execution-allocation; runtime calibration not supplied", device=request.device, **gpu)
        capabilities = inputs.backend_capabilities or runtime_recipe_capabilities()
        if inputs.r2_vpt2 is not None and not inputs.backend_capabilities:
            common = dict(verified=True, supported_elements=list(set(request.molecule.symbols)),
                supported_multiplicities=[1], supports_ions=True,
                evidence='explicit R2/B3LYP-D4 compiled native contracts; native completion and correction transfer validated per execution')
            capabilities.extend([
                BackendCapability(engine='orca', engine_version='6.1.1', methods=['wB97M-V', 'B3LYP', 'DLPNO-CCSD(T1)'],
                    bases=['def2-QZVPP', 'def2-TZVPP', 'cc-pVDZ-F12'], supports_rigid_fragments=True,
                    operations=['optimize', 'counterpoise', 'strict-unconstrained-reference-optimize', 'vpt2'], **common),
                BackendCapability(engine='topos', engine_version='0.1.0', methods=['R2-separate-DFT-VPT2'],
                    operations=['rotational-correction-transfer'], **common)])
        if inputs.orca_numerical_geometry is not None and not inputs.backend_capabilities:
            native = inputs.orca_numerical_geometry.energy_protocol
            capabilities.append(BackendCapability(engine='orca', engine_version=native.engine_version,
                methods=[native.method], bases=[native.orbital_basis], operations=['numerical-energy-geometry'],
                verified=True, evidence='checked numerical derivative driver over genuine native ORCA energies; execution validated per component',
                supported_elements=list(set(request.molecule.symbols)), supported_multiplicities=[1], supports_ions=True))
        if inputs.orca_f12_composite is not None and not inputs.backend_capabilities:
            common = dict(verified=True, evidence='explicit ORCA F12D composite protocol; actual native partitions checked per execution',
                          supported_elements=list(set(request.molecule.symbols)), supported_multiplicities=[1], supports_ions=True)
            capabilities.extend([
                BackendCapability(engine='orca', engine_version='6.1.1',
                    methods=['CCSD(T)-F12D/RI', 'MP2', inputs.orca_f12_composite.mp2_low.method],
                    bases=['jun-cc-pVTZ', 'jun-cc-pVQZ', 'cc-pwCVTZ'],
                    operations=['energy', 'mp2-f12-cbs', 'same-basis-core-valence'], **common),
                BackendCapability(engine='topos', engine_version='0.1.0', methods=['ORCA-F12D-CBS-CV'],
                    operations=['composite-interaction'], **common)])
        if inputs.external_protocol is not None and not inputs.backend_capabilities:
            external = inputs.external_protocol
            capabilities.append(BackendCapability(engine=external.engine, engine_version=external.engine_version,
                methods=["MP2", "CCSD(T)"] if row.row_id == "T3C-3d" else [external.method],
                bases=["cc-pVDZ", "cc-pVTZ", "cc-pVQZ", "cc-pCVQZ", "jun-cc-pVTZ", "jun-cc-pVQZ", "cc-pwCVTZ"],
                operations=[external.operation], verified=True,
                evidence="explicit native protocol and parser contract; installed binary/GENBAS identities verified on execution",
                supported_elements=list(set(request.molecule.symbols)), supported_multiplicities=[1], supports_ions=True))
        if inputs.energy_composite is not None and not inputs.backend_capabilities:
            template = inputs.energy_composite.template
            capabilities.extend([
                BackendCapability(engine="cfour", engine_version=template.engine_version,
                    methods=["CCSD(T)", "CCSDT"],
                    operations=["cbs-energy", "core-valence-energy-increment", "full-triples-energy-increment"],
                    verified=True, evidence="explicit CBS/CV/full-triples recipe, native GENBAS/output checked during execution",
                    supported_elements=list(set(request.molecule.symbols)), supported_multiplicities=[1], supports_ions=True),
                BackendCapability(engine="topos", engine_version="0.1.0", methods=["CBS+CV+fT"],
                    operations=["composite-energy"], verified=True, evidence="finite explicit native component arithmetic",
                    supported_elements=list(set(request.molecule.symbols)), supported_multiplicities=[1], supports_ions=True)])
        if inputs.higher_geometry is not None and not inputs.backend_capabilities:
            capabilities.append(BackendCapability(engine="cfour", engine_version="2.1", methods=["CCSD(T)", "CCSDT", "CCSDTQ"],
                operations=["cbs-geometry", "core-valence-geometry-increment", "full-triples-geometry-increment", "full-quadruples-geometry-increment"],
                verified=True, evidence="explicit higher composite with native analytic derivatives and checked physical central energy differences for full quadruples",
                supported_elements=list(set(request.molecule.symbols)), supported_multiplicities=[1], supports_ions=True))
        if inputs.cfour_counterpoise is not None and not inputs.backend_capabilities:
            common = dict(verified=True, supported_elements=['H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne'],
                supported_multiplicities=[1], supports_ions=True,
                evidence='conditional exact native CFOUR 2.1 ghost/core energy contracts and checked raw/CP numerical derivatives')
            capabilities.extend([
                BackendCapability(engine='cfour', engine_version='2.1', methods=['CCSD(T)', 'CCSDT', 'CCSDTQ'],
                    operations=['raw-and-cp-cbs-geometry', 'raw-and-cp-core-valence-geometry-increment',
                                'raw-and-cp-full-triples-geometry-increment', 'raw-and-cp-full-quadruples-geometry-increment'], **common),
                BackendCapability(engine='topos', engine_version='0.1.0', methods=['CBS+CV+fT+fQ'],
                    operations=['counterpoise-bracketed-composite-geometries'], **common)])
        if inputs.month_corrections is not None and not inputs.backend_capabilities:
            common = dict(verified=True, supported_elements=['H', 'C', 'N', 'O', 'F'],
                supported_multiplicities=[1], supports_ions=True,
                evidence='conditional native HF correction adapters; actual native controls, identity, energies and precision checked per component')
            capabilities.extend([
                BackendCapability(engine='cfour', engine_version='2.1', methods=['HF'],
                    operations=['scalar-HF-geometry-increment', 'default-mass-HF-dboc-geometry-increment'], **common),
                BackendCapability(engine='topos', engine_version='0.1.0', methods=['CBS+CV+fT+fQ+HF-corrections'],
                    operations=['conditional-corrected-geometry'], **common)])
        if inputs.ml_model is not None and not inputs.backend_capabilities:
            manifest = inputs.ml_model
            capabilities.append(BackendCapability(engine="mlff", engine_version=manifest.package_version,
                methods=["manifest-bound"], operations=["dense-scan", "interaction-energy"],
                verified=True, evidence="explicit manifest-bound adapter; checkpoint identity and BASE silo checked during execution",
                supported_elements=manifest.supported_elements, supported_multiplicities=manifest.supported_multiplicities,
                supports_ions=any(charge != 0 for charge in manifest.supported_charges),
                model_sha256=digest_json(manifest.model_dump(mode="json")), precision=manifest.precision,
                devices=["gpu"] if request.device == "gpu" else ["cpu"],
                gpu_memory_required_mb=inputs.ml_gpu_memory_mb if request.device == "gpu" else None,
                supports_rigid_fragments=True))
            if row.row_id == "T1-1w" and manifest.backend == "mace":
                from .ml_crest import (
                    CREST_GENERIC_CAPABILITY_VERSION,
                    validate_crest_ml_distribution,
                )

                if request.device != "gpu" or workflow.base_runtime is None:
                    raise ValueError("T1-1w requires GPU training and actual BASE authority")
                build = validate_crest_ml_distribution(workflow.base_runtime.resolve_executable("crest"))
                model_identity = digest_json(manifest.model_dump(mode="json"))
                model_common = dict(verified=True, supported_elements=manifest.supported_elements,
                    supported_multiplicities=manifest.supported_multiplicities,
                    supports_ions=any(charge != 0 for charge in manifest.supported_charges), precision="float64",
                    model_sha256=model_identity, devices=["gpu"], gpu_memory_required_mb=inputs.ml_gpu_memory_mb)
                capabilities.extend([
                    BackendCapability(engine="mace", engine_version=manifest.package_version,
                        methods=["MACE"], operations=["fine-tune"],
                        evidence="explicit GPU float64 fine-tuning and group-disjoint held-out evaluation contract", **model_common),
                    BackendCapability(engine="orca+crest", engine_version="6.1.1+" + CREST_GENERIC_CAPABILITY_VERSION,
                        methods=["custom-MLFF"], operations=["goat-and-crest-union"],
                        evidence="verified native generic-calculator distribution " + build["binary_sha256"] +
                        "; identical trained model and genuine native completion checked by both samplers", **model_common),
                ])
            if manifest.backend == "aimnet2":
                capabilities.append(BackendCapability(engine="orca+aimnet2", engine_version="6.1.1+"+manifest.package_version,
                    methods=["AIMNet2"], operations=["goat-explore"], verified=True,
                    evidence="persistent BASE-audited ML ExtOpt bridge; native ORCA and model identities checked on execution",
                    supported_elements=manifest.supported_elements, supported_multiplicities=manifest.supported_multiplicities,
                    supports_ions=any(charge != 0 for charge in manifest.supported_charges), precision=manifest.precision,
                    model_sha256=digest_json(manifest.model_dump(mode="json")),
                    devices=["gpu"] if request.device == "gpu" else ["cpu"],
                    gpu_memory_required_mb=inputs.ml_gpu_memory_mb if request.device == "gpu" else None))
        plan = plan_route(row.row_id, hardware=limits, capabilities=capabilities,
                          available_inputs=_available_inputs(request, inputs),
                          symbols=request.molecule.symbols, charge=request.molecule.charge,
                          multiplicity=request.molecule.multiplicity, product=row.product or "A",
                          source_resolution=inputs.source_resolution)
        previous_reviewed = record.metadata.get('matrix_plan', {}).get('reviewed_revision')
        if previous_reviewed is not None and previous_reviewed != plan.reviewed_revision:
            raise IntegrityError('Reviewed matrix revision changed since the recorded campaign; resume cannot replace its scientific definition')
        record.metadata["matrix_plan"] = plan.model_dump(mode="json")
        if request.constraints and row.row_id != "T3O-1min":
            raise ValueError("This matrix recipe does not include the requested constraints; choose an explicit constrained protocol")
        if row.row_id not in EXECUTABLE_ROWS | IMPLEMENTED_BRANCH_ROWS:
            from .method_matrix import unavailable_by_design

            disposition = unavailable_by_design(row.row_id)
            record.status = "unsupported"
            record.metadata["termination_reason"] = (
                f"{row.row_id} is unavailable by design: {disposition['source_excerpt']} "
                f"({disposition['source_path']}:{disposition['source_lines'][0]})"
                if disposition is not None else
                f"{row.row_id} requires additional {row.owner} recipe adapters. The complete plan and "
                "specific capability prerequisites are recorded; no cheaper method was substituted."
            )
            return
        if not plan.runnable:
            raise ValueError("; ".join(plan.blockers))
        if row.row_id in {"T2-10s", "T2-30min", "T2-1h"} and len(inputs.scan_coordinates) != (2 if row.row_id == "T2-1h" else 1):
            raise ValueError("The selected scan row requires exactly " + ("two" if row.row_id == "T2-1h" else "one") + " explicit scan coordinate(s)")
        if row.row_id == "T1-10s":
            _validate_ensemble(request.molecule, inputs.topology_seeds, minimum=3, maximum=9, distinct=True)
        elif row.row_id == "T1-1h":
            _validate_ensemble(request.molecule, inputs.topology_seeds, minimum=3, distinct=True)
        elif row.row_id == "T1-12h":
            _validate_ensemble(request.molecule, inputs.leading_isomers, minimum=2, maximum=3, distinct=True)
        elif row.row_id == "T1-3d":
            _validate_ensemble(request.molecule, inputs.stage_b_ensemble, minimum=1)
        elif row.row_id == "T3O-1min":
            if len(inputs.isolated_monomer_sources) != len(inputs.isolated_monomer_references) or any(
                not source.strip() for source in inputs.isolated_monomer_sources
            ):
                raise ValueError("Each isolated monomer reference requires a cited or calculation-linked source")
    except IntegrityError:
        raise
    except (ValueError, TypeError) as exc:
        record.status = "unsupported"
        record.metadata["termination_reason"] = str(exc)
        return

    state = record.metadata.setdefault("matrix_execution", {
        "row_id": row.row_id, "source_sha256": row.source.sha256,
        "inputs_sha256": digest_json(inputs.model_dump(mode="json")), "children": [],
        "full_row_completed": False,
    })
    if (state["row_id"] != row.row_id or state["source_sha256"] != row.source.sha256
            or state["inputs_sha256"] != digest_json(inputs.model_dump(mode="json"))):
        raise IntegrityError("Matrix row or inputs changed across resume")
    store.commit(record)

    def child(task_id: str, molecule: Molecule, *, engine: str, method: str,
              purpose: str = "optimize", basis: str | None = None,
              constraints: dict[str, Any] | None = None, sampler: bool = False,
              include_candidates: bool = True, optimize_first: bool | None = None) -> RunRecord | None:
        if (molecule.atom_ids == request.molecule.atom_ids and molecule.symbols == request.molecule.symbols):
            _validate_sampled_geometry(request.molecule, molecule)
        if cancel_event is not None and cancel_event.is_set():
            record.status = "cancelled"
            record.metadata["termination_reason"] = "Matrix recipe cancelled before next component"
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            record.status = "timed-out"
            record.metadata["termination_reason"] = "Matrix recipe deadline reached; completed components retained"
            return None
        component = _child_request(request, molecule, engine=engine, method=method, purpose=purpose,
                                   remaining=remaining, basis=basis, constraints=constraints, sampler=sampler,
                                   optimize_first=optimize_first)
        identity = _protocol_identity(component)
        completed = [c for c in state["children"] if c["task_id"] == task_id and c["status"] == "completed"]
        if completed:
            saved = completed[-1]
            if saved["protocol_sha256"] != identity:
                raise IntegrityError("Matrix child protocol differs from the committed component")
            child_dir = store.run_dir / saved["run_path"]
            if not child_dir.resolve().is_relative_to((store.run_dir / "matrix-children").resolve()):
                raise IntegrityError("Matrix child escapes its parent evidence directory")
            raw = RunStore(child_dir).recover()
            result = RunRecord.model_validate(raw)
            if digest_json(raw) != saved["record_sha256"]:
                raise IntegrityError("Matrix child record changed after component completion")
            return result
        child_workflow = Workflow(store.run_dir / "matrix-children" / task_id, config=workflow.config)
        interrupted = [c for c in state["children"] if c["task_id"] == task_id]
        if interrupted:
            saved = interrupted[-1]
            if saved["protocol_sha256"] != identity:
                raise IntegrityError("Interrupted matrix child protocol changed")
            child_dir = store.run_dir / saved["run_path"]
            if not child_dir.resolve().is_relative_to(child_workflow.output_root.resolve()):
                raise IntegrityError("Interrupted matrix child escapes its evidence directory")
            if digest_json(RunStore(child_dir).load()) != saved["record_sha256"]:
                raise IntegrityError("Interrupted matrix child record changed")
            result = child_workflow.resume(child_dir, cancel_event=cancel_event, invocation_budget_seconds=remaining)
        else:
            # A process can stop after the child commits but before the parent
            # records its identity. Recover that single matching durable child,
            # never infer success from loose scratch files or directory names.
            orphans = []
            for possible in child_workflow.output_root.glob("*/CURRENT.json"):
                raw = RunStore(possible.parent).load()
                candidate = RunRecord.model_validate(raw)
                if _protocol_identity(candidate.request) == identity:
                    orphans.append(possible.parent)
            if len(orphans) > 1:
                raise IntegrityError("Multiple unbound matrix children require explicit recovery selection")
            result = (child_workflow.resume(orphans[0], cancel_event=cancel_event, invocation_budget_seconds=remaining)
                      if orphans else child_workflow.run(component, cancel_event=cancel_event))
        child_dir = child_workflow.output_root / result.run_id
        _append_child(record, result, store.run_dir, child_dir, task_id, include_candidates=include_candidates)
        state["children"].append({"task_id": task_id, "run_id": result.run_id,
                                  "run_path": child_dir.relative_to(store.run_dir).as_posix(),
                                  "status": result.status, "protocol_sha256": identity,
                                  "record_sha256": digest_json(RunStore(child_dir).load())})
        store.commit(record)
        if result.status != "completed":
            record.status = result.status
            record.metadata["termination_reason"] = f"Matrix component {task_id} did not complete: " + str(result.metadata.get("termination_reason", result.status))
            return None
        return result

    row_id = row.row_id
    if row_id == 'T3O-3h' and inputs.source_resolution == 'r2-b3lyp-d4-vpt2-transfer-v1':
        from .matrix_r2 import execute_reviewed_r2

        if request.per_geometry_budget_seconds is not None:
            # The child closure captures this same deadline: all R2 phases
            # share the cap, rather than refreshing it for each calculation.
            deadline = min(deadline, time.monotonic() + request.per_geometry_budget_seconds)
        if not execute_reviewed_r2(workflow, record, store, inputs, child, deadline, cancel_event):
            return
    elif row_id in {'T3O-1d', 'T3O-1mo'} and inputs.source_resolution in {
            'orca-f12d-numerical-geometry-dz-v1', 'orca-f12d-numerical-geometry-tz-v1'}:
        from .orca_numerical_geometry import execute_orca_numerical_geometry

        if not execute_orca_numerical_geometry(workflow, record, store, inputs, deadline, cancel_event):
            return
    elif row_id == 'T5-3h' and inputs.source_resolution == 'orca-f12d-composite-interaction-v1':
        from .orca_f12_composite import execute_orca_f12_composite

        if not execute_orca_f12_composite(workflow, record, store, inputs, deadline, cancel_event):
            return
    elif row_id == 'T3O-1w' and inputs.source_resolution == 'cfour-relaxed-counterpoise-geometry-v1':
        from .cfour_counterpoise import execute_cfour_counterpoise_recipe

        if not execute_cfour_counterpoise_recipe(workflow, record, store, inputs, deadline, cancel_event):
            return
    elif row_id == 'T3C-1mo' and inputs.source_resolution == 'cfour-native-default-mass-corrected-geometry-v1':
        from .month_geometry import execute_month_geometry

        if not execute_month_geometry(workflow, record, store, inputs, deadline, cancel_event):
            return
        state['full_row_completed'] = False
        state['implemented_branch_completed'] = True
        state['completion_scope'] = 'Conditional corrected geometry only; native numeric isotope masses and all rotor constants remain unverified/withheld'
        record.status, record.validation_status = 'completed', 'human-review'
        store.commit(record)
        return
    elif row_id == "T3C-1w":
        from .higher_composite import execute_higher_recipe

        if not execute_higher_recipe(workflow, record, store, inputs, deadline, cancel_event):
            return
    elif row_id == "T5-1w":
        from .energy_composite import execute_energy_composite

        if not execute_energy_composite(workflow, record, store, inputs, deadline, cancel_event):
            return
    elif row_id in {"T3C-30min", "T3C-1h", "T3C-3h", "T3C-12h", "T3C-1d", "T3C-3d", "T5-1mo"}:
        from .external_matrix_workflow import execute_external_recipe

        if not execute_external_recipe(workflow, record, store, inputs, deadline, cancel_event):
            return
    elif row_id in {"T2-1min", "T5-1min"}:
        from .ml_workflow import execute_ml_matrix

        if row_id == "T5-1min" and not inputs.ml_no_energy_culling:
            raise ValueError("T5-1min requires explicit ml_no_energy_culling=True until an independent G4 ranking audit authorizes pruning")
        execute_ml_matrix(workflow, record, store, deadline, cancel_event, inputs)
        if record.status != "completed":
            return
    elif row_id == "T1-30min":
        from .matrix_ml_search import execute_ml_search

        if not execute_ml_search(workflow, record, store, inputs, child, deadline, cancel_event):
            return
    elif row_id == "T1-1w":
        from .matrix_ml_training import execute_ml_training

        if not execute_ml_training(workflow, record, store, inputs, child, deadline, cancel_event):
            return
    elif row_id == "T1-1d":
        from .matrix_entropy import execute_entropy_recipe

        if not execute_entropy_recipe(workflow, record, store, inputs, deadline, cancel_event):
            return
    elif row_id == "T1-1mo":
        from .matrix_diversity import execute_diversity_recipe

        if not execute_diversity_recipe(workflow, record, store, inputs, child, deadline, cancel_event):
            return
    elif row_id in {"T5-12h", "T5-1d", "T5-3d", "T3O-12h", "T3O-3d", "T3O-1mo"}:
        from .correlated_workflow import execute_correlated_recipe

        if not execute_correlated_recipe(workflow, record, store, inputs, deadline, cancel_event):
            return
        if row_id in IMPLEMENTED_BRANCH_ROWS and inputs.source_resolution == 'orca-f12-reference-singlepoint-v1':
            state["full_row_completed"] = False
            state["implemented_branch_completed"] = True
            state["completion_scope"] = "ORCA reference electronic energy on supplied geometry only; Molpro reference-geometry branch is unimplemented"
            record.status, record.validation_status = "completed", "human-review"
            store.commit(record)
            return
    elif row_id == "T1-3h":
        from .matrix_union import execute_union

        if not execute_union(workflow, record, store, inputs, child, deadline, cancel_event):
            return
    elif row_id == "T5-1h":
        from .counterpoise import execute_counterpoise
        from .models import MethodSpec

        runtime = workflow.base_runtime
        if runtime is None:
            record.status = "unavailable"
            record.metadata["termination_reason"] = "Named-basis matrix counterpoise requires BASE native ORCA basis-export authority"
            return
        cp_deadline = deadline
        if getattr(request, "per_geometry_budget_seconds", None) is not None:
            cp_deadline = min(deadline, time.monotonic() + request.per_geometry_budget_seconds)
        method = MethodSpec(engine="orca", method="wB97M-V", purpose="energy", basis="def2-TZVPP",
                            auxiliary_basis="def2/J", profile_id="orca-mapping-v4.1", engine_version="6.1.1")
        exports = state.setdefault("counterpoise_exports", {})
        try:
            orca = runtime.resolve_executable("orca", workflow.config.executables.get("orca"))
            for kind, basis in (("orbital", "def2-TZVPP"), ("auxiliary", "def2/J")):
                if cancel_event is not None and cancel_event.is_set():
                    record.status = "cancelled"
                    return
                if kind in exports:
                    # execute_counterpoise re-verifies receipt, basis, exporter and ORCA bytes.
                    continue
                remaining = cp_deadline - time.monotonic()
                if remaining <= 0:
                    record.status = "timed-out"
                    return
                from .models import new_id

                export_dir = store.run_dir / "counterpoise-exports" / new_id(kind)
                receipt = runtime.export_orca_basis(basis, sorted(set(request.molecule.symbols)), export_dir,
                                                    request.resources.model_copy(update={"budget_seconds": remaining, "threads": 1}),
                                                    cancel_event=cancel_event)
                for file in export_dir.rglob("*"):
                    if file.is_file() and not file.is_symlink():
                        relative = file.relative_to(store.run_dir).as_posix()
                        record.artifacts.append(Artifact(path=relative, sha256=file_digest(file), size_bytes=file.stat().st_size,
                                                         role="native-ORCA-basis-export"))
                if receipt["status"] != "completed":
                    record.status = receipt["status"]
                    record.metadata["termination_reason"] = "Native ORCA basis export did not complete"
                    return
                exports[kind] = receipt
                store.commit(record)
            remaining = cp_deadline - time.monotonic()
            if remaining <= 0:
                record.status = "timed-out"
                return
            result = execute_counterpoise(
                request.molecule, method, request.resources.model_copy(update={"budget_seconds": remaining}),
                store.run_dir / "counterpoise-calculation", orbital_basis_file=exports["orbital"]["output_path"],
                auxiliary_basis_file=exports["auxiliary"]["output_path"], basis_export_receipts=exports,
                executable=orca, process_runner=runtime.run_process, cancel_event=cancel_event)
        except (ValueError, RuntimeError, OSError) as exc:
            record.status, record.metadata["termination_reason"] = "unavailable", str(exc)
            return
        for job in result["jobs"]:
            from .engines import EngineResult

            engine_result = EngineResult.model_validate(job["result"])
            identifier = "attempt_cp_" + job["result_sha256"][:24]
            if any(a.attempt_id == identifier for a in record.attempts):
                continue
            attempt = Attempt(attempt_id=identifier, run_id=record.run_id, engine="orca", method=method.method,
                              status=engine_result.status, converged=engine_result.converged,
                              validation_status="validated-for-protocol" if engine_result.status == "completed" else "not-evaluated",
                              command=engine_result.command, engine_version=engine_result.engine_version,
                              diagnostics=engine_result.diagnostics, metadata={**engine_result.metadata, "counterpoise_role": job["role"]},
                              artifacts=[a.model_copy(update={"path": Path(a.path).resolve().relative_to(store.run_dir).as_posix()}) for a in engine_result.artifacts])
            if engine_result.energy_hartree is not None:
                attempt.quantities.append(Quantity(name="electronic_energy", value=engine_result.energy_hartree, units="hartree",
                                                   definition="actual counterpoise component electronic energy; basis centers and electronic state in raw input",
                                                   attempt_id=identifier, method=method.method, validity=attempt.validation_status))
            record.attempts.append(attempt)
        result_path = store.run_dir / "counterpoise-results" / (digest_json(result) + ".json")
        atomic_json(result_path, result)
        result_artifact = Artifact(path=result_path.relative_to(store.run_dir).as_posix(), sha256=file_digest(result_path),
                                   size_bytes=result_path.stat().st_size, role="counterpoise-result")
        if not any(a.path == result_artifact.path for a in record.artifacts):
            record.artifacts.append(result_artifact)
        for artifact in result.get("artifacts", []):
            copied = Artifact.model_validate(artifact)
            copied.path = Path(copied.path).resolve().relative_to(store.run_dir).as_posix()
            if not any(a.path == copied.path for a in record.artifacts):
                record.artifacts.append(copied)
        record.metadata["matrix_counterpoise"] = {"status": result["status"], "validation_status": result["validation_status"],
                                                 "basis_identity": result.get("basis_identity"), "energies": result.get("energies"),
                                                 "result_path": result_path.relative_to(store.run_dir).as_posix()}
        if result["status"] != "completed" or result["validation_status"] != "validated-for-protocol":
            record.status = result["status"] if result["status"] != "completed" else "partial"
            record.metadata["termination_reason"] = result.get("reason", "Counterpoise has not established the exact native basis identity")
            return
        aggregate_id = "attempt_cp_derived_" + digest_json(result["comparison_protocol"])[:24]
        if not any(a.attempt_id == aggregate_id for a in record.attempts):
            last_legs = {a.metadata["counterpoise_role"]: a for a in record.attempts
                         if a.status == "completed" and "counterpoise_role" in a.metadata}
            aggregate = Attempt(
                attempt_id=aggregate_id, run_id=record.run_id, engine="orca", method=method.method,
                status="completed", converged=True, validation_status="validated-for-protocol", engine_version="6.1.1",
                command=["topos-internal", "boys-bernardi-counterpoise"], artifacts=[result_artifact.model_copy()],
                metadata={"execution_kind": "real", "result_kind": "derived-counterpoise",
                          "component_attempt_ids": [a.attempt_id for a in last_legs.values()],
                          "comparison_protocol": result["comparison_protocol"],
                          "basis_identity": result["basis_identity"],
                          "geometry_state": "frozen-inc", "binding_or_thermal_claim": False},
            )
            for key, definition in (
                ("raw_interaction_hartree", "E_complex - E_A(own basis) - E_B(own basis), all at complex geometry"),
                ("cp_interaction_hartree", "Boys–Bernardi: E_complex - E_A(complex basis) - E_B(complex basis)"),
                ("additive_cp_correction_hartree", "CP interaction minus raw interaction"),
                ("half_cp_interaction_hartree", "one half of the sum of raw and CP interaction energies; a convention, not an error bound"),
            ):
                aggregate.quantities.append(Quantity(name=key.removesuffix("_hartree"), value=result["energies"][key],
                                                     units="hartree", definition=definition,
                                                     attempt_id=aggregate_id, method=method.method,
                                                     validity="validated-for-protocol"))
            record.attempts.append(aggregate)
    elif row_id in {"T1-1min", "T1-12h"}:
        from .goat import run_goat
        from .models import MethodSpec, utc_now
        from .sampling import SampledConformer

        seeds = [request.molecule] if row_id == "T1-1min" else inputs.leading_isomers
        method = MethodSpec(engine="xtb" if row_id == "T1-1min" else "orca",
                            method="GFN2-xTB" if row_id == "T1-1min" else "r2SCAN-3c",
                            profile_id="xtb-vtight-v1" if row_id == "T1-1min" else "orca-mapping-v4.1",
                            engine_version="6.7.1" if row_id == "T1-1min" else "6.1.1")
        for seed_index, molecule in enumerate(seeds):
            identity = digest_json({"molecule": molecule.model_dump(mode="json"),
                                    "method": method.model_dump(mode="json"),
                                    "goat_options": inputs.goat_options.model_dump(mode="json"), "row": row_id})
            cached = [a for a in record.attempts if a.metadata.get("matrix_goat_identity") == identity and a.status == "completed"]
            if cached:
                attempt = cached[-1]
                ensemble = [SampledConformer.model_validate(frame) for frame in attempt.metadata["raw_ensemble"]]
            else:
                if cancel_event is not None and cancel_event.is_set():
                    record.status = "cancelled"
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    record.status = "timed-out"
                    return
                runtime = workflow.base_runtime
                try:
                    orca = runtime.resolve_executable("orca", workflow.config.executables.get("orca")) if runtime else workflow.config.executables.get("orca")
                    xtb = (runtime.resolve_executable("xtb", workflow.config.executables.get("xtb")) if runtime else workflow.config.executables.get("xtb")) if method.engine == "xtb" else None
                except (ValueError, OSError, RuntimeError) as exc:
                    record.status, record.metadata["termination_reason"] = "unavailable", str(exc)
                    return
                attempt = Attempt(run_id=record.run_id, engine="orca", method=method.method,
                                  status="running", started_at=utc_now(),
                                  metadata={"role": "matrix-goat-sampler", "matrix_goat_identity": identity,
                                            "input_molecule": molecule.model_dump(mode="json")})
                record.attempts.append(attempt)
                store.commit(record)
                sampled = run_goat(
                    molecule, method, request.resources.model_copy(update={"budget_seconds": remaining}),
                    store.run_dir / "attempts" / attempt.attempt_id, executable=orca, xtb_executable=xtb,
                    energy_window_kcal_mol=12.0, uphill_method="GFN-FF" if row_id == "T1-1min" else None,
                    deterministic=inputs.goat_options.deterministic,
                    max_global_iterations=inputs.goat_options.max_global_iterations,
                    process_runner=runtime.run_process if runtime else None, cancel_event=cancel_event)
                attempt.status, attempt.converged = sampled.status, sampled.converged
                attempt.finished_at = utc_now()
                attempt.command, attempt.engine_version = sampled.command, sampled.engine_version
                attempt.diagnostics = sampled.diagnostics
                attempt.metadata.update(sampled.metadata)
                attempt.metadata.update(raw_ensemble=[frame.model_dump(mode="json") for frame in sampled.ensemble],
                                        potential_engine=sampled.potential_engine,
                                        potential_engine_version=sampled.potential_engine_version)
                attempt.artifacts = [artifact.model_copy(update={"path": Path(artifact.path).resolve().relative_to(store.run_dir).as_posix()}) for artifact in sampled.artifacts]
                attempt.validation_status = "validated-for-protocol" if sampled.status == "completed" else "not-evaluated"
                store.commit(record)
                if sampled.status != "completed":
                    record.status = sampled.status
                    record.metadata["termination_reason"] = "Native GOAT search did not complete: " + str(sampled.diagnostics.get("reason", sampled.status))
                    return
                ensemble = sampled.ensemble
            if not ensemble:
                record.status, record.metadata["termination_reason"] = "failed", "Native GOAT returned no observed ensemble"
                return
            omitted = max(0, len(ensemble) - request.n_candidates)
            for frame in sorted(ensemble, key=lambda f: (f.energy_hartree, f.source_index))[:request.n_candidates]:
                refined = child(f"goat-{seed_index:04d}-frame-{frame.source_index:05d}", frame.molecule,
                                engine=method.engine, method=method.method)
                if refined is None:
                    return
                expected_digest = attempt.metadata.get("xtb_sha256") if method.engine == "xtb" else attempt.metadata.get("executable_sha256")
                if any(a.metadata.get("executable_sha256") != expected_digest for a in refined.attempts if a.status == "completed"):
                    record.status, record.metadata["termination_reason"] = "failed", "GOAT potential and common refinement used different verified binaries"
                    return
            if omitted:
                record.status = "partial"
                record.metadata["termination_reason"] = f"GOAT completed but {omitted} native frames exceed the explicit common-refinement candidate cap; raw ensemble is archived"
                return
    elif row_id in {"T2-10s", "T2-30min", "T2-1h"}:
        from .models import MethodSpec
        from .scans import run_relaxed_scan

        step = plan.steps[0]
        method = MethodSpec(engine=step.engine, method=step.method, purpose="gradient",
                            basis=step.basis, auxiliary_basis=step.auxiliary_basis,
                            profile_id=step.profile_id, engine_version=step.engine_version)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            record.status = "timed-out"
            return
        scan_folder = store.run_dir / "relaxed-scan"
        try:
            result = run_relaxed_scan(request.molecule, method,
                                      request.resources.model_copy(update={"budget_seconds": remaining}),
                                      inputs.scan_coordinates, scan_folder, config=workflow.config,
                                      options=inputs.scan_options, cancel_event=cancel_event)
        except ValueError as exc:
            record.status, record.metadata["termination_reason"] = "unsupported", str(exc)
            return
        for entry in result["evaluations"]:
            child_dir = scan_folder / entry["run_path"]
            gradient_record = RunRecord.model_validate(RunStore(child_dir).recover())
            _append_child(record, gradient_record, store.run_dir, child_dir,
                          "scan-gradient:" + entry["geometry_sha256"], include_candidates=False)
        for point in result["points"]:
            candidate_id = "candidate_scan_" + point["point_sha256"][:24]
            if any(c.candidate_id == candidate_id for c in record.candidates):
                continue
            evidence = point["gradient_evidence"]
            gradient_record = RunRecord.model_validate(RunStore(scan_folder / evidence["run_path"]).recover())
            source_attempt = next(a for a in gradient_record.attempts if a.status == "completed")
            attempt_id = "attempt_scan_" + point["point_sha256"][:24]
            attempt = Attempt(
                attempt_id=attempt_id, run_id=record.run_id, engine=step.engine, method=step.method,
                status="completed", converged=True, validation_status="validated-for-protocol",
                engine_version=source_attempt.engine_version, parent_attempt_id=source_attempt.attempt_id,
                command=["topos-internal", "equality-constrained-relaxed-scan"],
                diagnostics=point["diagnostics"],
                metadata={"execution_kind": "real", "result_kind": "derived-constrained-scan",
                          "operation": "relaxed-scan", "direction": point["direction"], "targets": point["targets"],
                          "output_molecule": point["molecule"], "point_sha256": point["point_sha256"],
                          "executable_sha256": source_attempt.metadata.get("executable_sha256")},
                quantities=[Quantity(name="electronic_energy", value=point["energy_hartree"], units="hartree",
                                     definition="electronic energy at a constrained relaxed scan point; not an unconstrained minimum",
                                     attempt_id=attempt_id, geometry_id=candidate_id, method=step.method,
                                     validity="validated-for-protocol")],
            )
            attempt.artifacts = [artifact.model_copy(update={"path": (scan_folder / evidence["run_path"] / artifact.path).relative_to(store.run_dir).as_posix()}) for artifact in source_attempt.artifacts]
            attempt.metadata["accepted_gradient_attempt_id"] = source_attempt.attempt_id
            record.attempts.append(attempt)
            record.candidates.append(Candidate(
                candidate_id=candidate_id, molecule=Molecule.model_validate(point["molecule"]),
                attempt_id=attempt_id, energy_hartree=point["energy_hartree"], status="scan-point",
                comparison_protocol=digest_json({"method": method.model_dump(mode="json"),
                                                 "scan_targets": point["targets"], "scan_protocol": result["protocol_sha256"]}),
                sources=["MATRIX:" + row_id + ":" + point["direction"]],
                metadata={"matrix_scan_targets": point["targets"], "scan_direction": point["direction"],
                          "stationary_point_classification": "constrained slice point; not a free minimum or transition state",
                          "point_sha256": point["point_sha256"]},
            ))
        result_path = store.run_dir / "scan-results" / (digest_json(result) + ".json")
        if not result_path.exists():
            atomic_json(result_path, result)
        relative = result_path.relative_to(store.run_dir).as_posix()
        if not any(a.path == relative for a in record.artifacts):
            record.artifacts.append(Artifact(path=relative, role="relaxed-scan-result", sha256=file_digest(result_path),
                                             size_bytes=result_path.stat().st_size))
        surface = dict(result["surface_artifact"])
        surface["path"] = (scan_folder / surface["path"]).relative_to(store.run_dir).as_posix()
        record.artifacts.append(Artifact.model_validate(surface))
        record.metadata["matrix_scan"] = {"status": result["status"], "result_path": relative,
                                           "surface_hdf5": surface["path"],
                                           "export_scope": "surface artifacts; scan points are not eligible conformer ensemble members",
                                           "completed_points": len(result["points"]),
                                           "grid_points_per_direction": result["grid_points_per_direction"],
                                           "max_absolute_hysteresis_hartree": result.get("max_absolute_hysteresis_hartree")}
        if result["status"] != "completed":
            record.status = result["status"]
            record.metadata["termination_reason"] = result.get("reason", "Relaxed scan did not complete")
            return
    elif row_id in {"T1-10s", "T1-1h", "T1-3d"}:
        geometries = inputs.stage_b_ensemble if row_id == "T1-3d" else inputs.topology_seeds
        for index, molecule in enumerate(geometries):
            result = child(f"seed-{index:04d}", molecule, engine="orca" if row_id == "T1-3d" else "xtb",
                           method="wB97X-V" if row_id == "T1-3d" else "GFN2-xTB",
                           basis="def2-TZVPP" if row_id == "T1-3d" else None,
                           purpose="search" if row_id == "T1-1h" else "optimize", sampler=row_id == "T1-1h")
            if result is None:
                return
            if row_id == "T1-1h" and result.metadata.get("sampler_exclusions"):
                record.status = "partial"
                record.metadata["termination_reason"] = "CREST completed but the explicit candidate cap omitted ensemble refinement; raw frames remain archived"
                return
    elif row_id in {"T5-10s", "T5-30min"}:
        from .fragments import split_fragments

        try:
            fragments = split_fragments(request.molecule)
        except ValueError as exc:
            record.status, record.metadata["termination_reason"] = "unsupported", str(exc)
            return
        interaction_engine, interaction_method = ("xtb", "GFN2-xTB") if row_id == "T5-10s" else ("orca", "r2SCAN-3c")
        complex_run = child("interaction-complex", request.molecule, engine=interaction_engine, method=interaction_method, purpose="energy")
        if complex_run is None:
            return
        energy_candidates = [c for c in complex_run.candidates if c.status == "eligible" and c.energy_hartree is not None]
        if len(energy_candidates) != 1:
            record.status, record.metadata["termination_reason"] = "failed", "Complex energy is not a unique validated result"
            return
        complex_energy = energy_candidates[0].energy_hartree
        fragment_energies = []
        engine_identities = []
        for index, molecule in enumerate(fragments):
            result = child(f"interaction-fragment-{index:04d}", molecule, engine=interaction_engine, method=interaction_method,
                           purpose="energy", include_candidates=False)
            if result is None:
                return
            candidates = [c for c in result.candidates if c.status == "eligible" and c.energy_hartree is not None]
            if len(candidates) != 1:
                record.status, record.metadata["termination_reason"] = "failed", "A fragment energy is not a unique validated result"
                return
            fragment_energies.append(candidates[0].energy_hartree)
            engine_identities.extend((a.engine_version, a.metadata.get("executable_sha256")) for a in result.attempts if a.status == "completed")
        engine_identities.extend((a.engine_version, a.metadata.get("executable_sha256")) for a in complex_run.attempts if a.status == "completed")
        if len(set(engine_identities)) != 1 or not all(engine_identities[0]):
            record.status, record.metadata["termination_reason"] = "failed", "Interaction components have incompatible engine identities"
            return
        record.metadata["matrix_interaction_energy"] = {
            "value_hartree": complex_energy - sum(fragment_energies),
            "definition": "E_complex - sum(E_fragment at the same complex geometry)",
            "complex_energy_hartree": complex_energy, "fragment_energies_hartree": fragment_energies,
            "bsse_policy": "no selectable orbital basis; no counterpoise applied" if row_id == "T5-10s" else
                           "native r2SCAN-3c including native gCP in each leg; no additional gCP, CP or half-CP calculation",
            "source_resolution": inputs.source_resolution,
            "geometry_state": "frozen-inc", "binding_energy_hartree": None,
            "gibbs_energy_hartree": None, "engine_version": engine_identities[0][0],
            "executable_sha256": engine_identities[0][1],
        }
    else:
        step = plan.steps[0]
        molecule = request.molecule
        constraints = None
        if row_id == "T3O-1min":
            from .fragments import assemble_monomer_seed

            try:
                molecule = assemble_monomer_seed(molecule, inputs.isolated_monomer_references)
            except ValueError as exc:
                record.status, record.metadata["termination_reason"] = "unsupported", str(exc)
                return
            constraints = {"kind": "frozen-monomers", "profile_id": "mapping-2026",
                           "reference_source": "; ".join(inputs.isolated_monomer_sources)}
        if child("geometry", molecule, engine=step.engine, method=step.method,
                 basis=step.basis, constraints=constraints) is None:
            return
    comparison = "completed" if row_id in {"T1-3h", "T1-30min", "T1-1w"} else workflow._compare(record, deadline=deadline, cancel_event=cancel_event)
    if comparison != "completed":
        record.status = comparison
        return
    state["full_row_completed"] = True
    state["completion_scope"] = "specified finite recipe only; no exhaustive sampling or source benchmark accuracy certification"
    record.status = "completed"
    record.validation_status = "human-review"
    record.metadata.pop("termination_reason", None)
    store.commit(record)
