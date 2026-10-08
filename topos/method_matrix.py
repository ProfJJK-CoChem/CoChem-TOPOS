"""Versioned method-matrix catalog, explicit execution plans, and measured budgets.

The source table is a scientific planning document, not executable ORCA syntax.
A table row becomes runnable only when every required operation has a registered,
verified capability. Merely discovering an executable never supplies that proof.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .data.method_matrix_v4 import ROWS, SOURCE_PATH, SOURCE_REVISION, SOURCE_SHA256
from .data.reviewed_matrix_v010 import RECIPES as REVIEWED_RECIPES
from .data.reviewed_matrix_v010 import REVISION as REVIEWED_REVISION
from .data.reviewed_matrix_v010 import SOURCES as REVIEWED_SOURCES
from .models import Contract

MATRIX_REVISION = SOURCE_REVISION
MAPPING_REVISION = "COCHEM-SPEC-TASK2-4-4-METHOD-MATRIX-MAPPING-2026/1.0.1"
CATALOG_SCHEMA = "topos-method-matrix/1"
TIERS = {"10s": 10, "1min": 60, "30min": 1800, "1h": 3600, "3h": 10800,
         "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800, "1mo": 2592000}
PURPOSES = {1: "search", 2: "potential-surface", 3: "equilibrium-geometry",
            4: "vibrational-averaging", 5: "interaction-energy", 6: "spectroscopic-properties",
            7: "large-amplitude-motion", 8: "infrared", 9: "raman", 10: "other-spectroscopy"}
SCIENTIFIC_POLICIES = {
    "revisions": "The full table is v4; the mapping's v4.1 reference is retained independently.",
    "r2scan-composite": "Use native r2SCAN-3c (mTZVPP); no appended basis, D4, or gCP.",
    "vv10": "wB97X-V and wB97M-V already include VV10; never append D3/D4.",
    "convergence": "Production ORCA optimization uses the named orca-mapping-v4.2 profile; "
                   "the conflicting chunk-3 profile is not silently merged.",
    "deduplication": "Source Stage A uses 0.100 kcal/mol; TOPOS conservative generation uses "
                     "0.05 kcal/mol, explicitly a stricter implementation profile. "
                     "Reporting Stage B rotational threshold is 0.001.",
    "orca-cc-hessian": "Section 8D's analytic ORCA CCSD(T) Hessian assertion conflicts with "
                       "section 9.3 and Tables 4/8. Do not route ORCA VPT2 to CCSD(T).",
    "budget": "Source tiers and [D]/[E] hardware ratios are planning labels, not measured "
              "deadlines or accuracy guarantees. No automatic Hamiltonian substitution.",
    "monomer": "Frozen-iso requires independently validated isolated monomer geometries; "
               "frozen-inc preserves the in-complex geometry and is a different protocol.",
}


class SourceReference(Contract):
    path: str = SOURCE_PATH
    sha256: str = SOURCE_SHA256
    line: int = Field(ge=1)


class MatrixRow(Contract):
    row_id: str
    revision: str = MATRIX_REVISION
    purpose: str
    owner: Literal["TOPOS", "TORQ"]
    track: Literal["shared", "ORCA", "CFOUR"]
    tier: str
    reference_budget_seconds: int = Field(gt=0)
    # The parent document's domain is not an assertion that every method handles all species.
    chemical_domain: str = "isolated gas-phase 5–10 atom van der Waals complexes; see row limits"
    method_text: str
    delivers: str
    concurrency_text: str
    product: Literal["A", "B", "C"] | None
    limitations: str
    expansion: dict[str, Any]
    source: SourceReference
    expansion_source: SourceReference | None = None
    track_gap: bool = False
    alternatives: list[str] = Field(default_factory=list)
    source_conflicts: list[str] = Field(default_factory=list)
    provenance_tags: list[str] = Field(default_factory=list)


class MatrixCatalog(Contract):
    schema_version: str = CATALOG_SCHEMA
    revision: str = MATRIX_REVISION
    source_sha256: str = SOURCE_SHA256
    mapping_revision: str = MAPPING_REVISION
    policies: dict[str, str] = Field(default_factory=lambda: dict(SCIENTIFIC_POLICIES))
    rows: list[MatrixRow]

    def get(self, row_id: str) -> MatrixRow:
        canonical = canonical_row_id(row_id)
        for row in self.rows:
            if row.row_id == canonical:
                return row.model_copy(deep=True)
        raise ValueError(f"Unknown matrix row: {row_id}")

    def select(self, *, purpose: str, tier: str, track: str = "ORCA", product: str = "A") -> MatrixRow:
        """Select a nominal tier explicitly; never infer a scientific method from CPU speed."""
        if tier not in TIERS:
            raise ValueError("Unknown matrix time tier")
        if track not in {"ORCA", "CFOUR"}:
            raise ValueError("Choose an explicit ORCA or CFOUR track")
        matches = [r for r in self.rows if r.purpose == purpose and r.tier == tier
                   and r.track in {track, "shared"} and r.product == product]
        if len(matches) != 1:
            raise ValueError("No unique route for this purpose, tier, track and product")
        # Shared tables explicitly exclude the CFOUR search/surface engines.
        if track == "CFOUR" and matches[0].track == "shared":
            raise ValueError("This table has no CFOUR track; select its stated shared route explicitly")
        return matches[0].model_copy(deep=True)


def canonical_row_id(row_id: str) -> str:
    """Resolve only aliases explicitly used by the source's decision card."""
    if not isinstance(row_id, str) or not re.fullmatch(r"T(?:10|[1-9])[OC]?-(?:10s|1min|30min|1h|3h|12h|1d|3d|1w|1mo)", row_id):
        raise ValueError("Invalid matrix row ID")
    if re.match(r"T[3468]-", row_id):
        return row_id.replace("-", "O-", 1)
    return row_id


def unavailable_by_design(row_id: str) -> dict[str, Any] | None:
    """Cite deliberately absent CFOUR tiers without creating a native recipe.

    The pinned source states this exclusion in its two-track summary and repeats
    the gaps in the archived tables. A capability declaration cannot fill them.
    """
    canonical = canonical_row_id(row_id)
    if not re.fullmatch(r"T(?:3|4|6|8)C-(?:10s|1min)", canonical):
        return None
    archived = next(row for row in ROWS if row["row_id"] == canonical)
    return {
        "row_id": canonical,
        "disposition": "unavailable-by-design",
        "source_path": SOURCE_PATH,
        "source_lines": [36, archived["source_line"]],
        "source_excerpt": "CFOUR has no 10 s or 1 min entry",
        "source_sha256": SOURCE_SHA256,
    }


def _unavailable_blocker(disposition: dict[str, Any]) -> str:
    return (f"{disposition['row_id']} is unavailable-by-design: {disposition['source_excerpt']} "
            f"({disposition['source_path']}:{disposition['source_lines'][0]}). "
            "Choose a listed alternative explicitly; no replacement recipe is implied.")


def load_catalog(source_path: Path | str | None = None) -> MatrixCatalog:
    """Load bundled rows; optionally assert that a repository document is the pinned source."""
    if source_path is not None:
        if hashlib.sha256(Path(source_path).read_bytes()).hexdigest() != SOURCE_SHA256:
            raise ValueError("Method-matrix source differs from the versioned catalog; re-audit before routing")
    rows = []
    for raw in ROWS:
        rid = raw["row_id"]
        number = int(re.match(r"T(\d+)", rid)[1])
        prefix, tier = rid.split("-")
        expansion = dict(raw["expansion"])
        expansion_line = expansion.pop("source_line", None)
        plain_product = raw["product_text"].replace("*", "")
        conflicts = []
        if rid == "T3O-1d":
            conflicts.append("Source mixes MPQC with ORCA/DLPNO syntax and numerical gradients, "
                             "while section 9.0 restricts MPQC to single points. A corrected "
                             "engine-specific protocol must be approved before execution.")
        if rid == "T5-30min":
            conflicts.append("Main row uses native r2SCAN-3c/gCP; expansion promises raw/CP/half-CP. "
                             "Separate counterpoise on this composite is not specified consistently.")
        if rid == "T5-3h":
            conflicts.append("Source names ORCA F12 single points but specifies CCSD(T)-F12b. "
                             "The verified ORCA F12D/RI protocol is a distinct approximation; "
                             "select an explicit validated F12b backend and full auxiliary/CABS protocol.")
        if rid == "T4O-30min":
            conflicts.append("An ordinary harmonic Hessian alone does not determine vibration–rotation "
                             "alpha constants; the row's harmonic-alpha output needs an explicit "
                             "validated rovibrational protocol.")
        rows.append(MatrixRow(
            row_id=rid, purpose=PURPOSES[number],
            owner="TOPOS" if number in {1, 3, 5} or (number == 2 and tier in {"10s", "1min", "30min", "1h"}) else "TORQ", track="ORCA" if prefix.endswith("O") else
            "CFOUR" if prefix.endswith("C") else "shared", tier=tier,
            reference_budget_seconds=TIERS[tier], method_text=raw["method_text"],
            delivers=raw["delivers"], concurrency_text=raw["concurrency_text"],
            product=plain_product if plain_product in {"A", "B", "C"} else None,
            limitations=raw["limitations"], expansion=expansion,
            source=SourceReference(line=raw["source_line"]),
            expansion_source=SourceReference(line=expansion_line) if expansion_line else None,
            track_gap=plain_product not in {"A", "B", "C"},
            alternatives=list(dict.fromkeys(re.findall(r"T\d+[OC]?-(?:10s|1min|30min|1h|3h|12h|1d|3d|1w|1mo)", raw["limitations"]))),
            source_conflicts=conflicts,
            provenance_tags=sorted(set(re.findall(r"\[([MDE])\]", raw["delivers"] + raw["limitations"]))),
        ))
    return MatrixCatalog(rows=rows)


def resolve_row(row_id: str, *, purpose: str | None = None, product: str = "A") -> MatrixRow:
    row = load_catalog().get(row_id)
    if purpose is not None and purpose != row.purpose:
        raise ValueError("Selected row does not supply the requested scientific purpose")
    if row.product is not None and row.product != product:
        raise ValueError(f"{row.row_id} requires Product {row.product}, not {product}")
    return row


class HardwareSpec(Contract):
    cpu_threads: int = Field(ge=1)
    memory_mb: int = Field(ge=64)
    device: Literal["cpu", "gpu", "auto"] = "cpu"
    gpu_model: str | None = None
    gpu_memory_mb: int | None = Field(default=None, ge=1)
    fingerprint: str = Field(min_length=1)
    workers: int = Field(default=1, ge=1)
    threads_per_worker: int = Field(default=1, ge=1)
    memory_per_worker_mb: int = Field(default=1024, ge=64)
    gpu_workers: int = Field(default=1, ge=1)
    mps_enabled: bool = False
    heterogeneous_concurrent: bool = False

    @model_validator(mode="after")
    def check_allocation(self) -> HardwareSpec:
        if self.workers * self.threads_per_worker > self.cpu_threads:
            raise ValueError("workers × threads exceeds allocated CPU threads")
        if self.workers * self.memory_per_worker_mb > self.memory_mb:
            raise ValueError("workers × memory exceeds allocated RAM")
        if self.device == "gpu" and (not self.gpu_model or not self.gpu_memory_mb):
            raise ValueError("GPU routing requires a named GPU and measured available VRAM")
        if self.gpu_workers > 1 and not self.mps_enabled:
            raise ValueError("Concurrent GPU processes require a verified MPS configuration")
        if self.heterogeneous_concurrent and self.workers * self.threads_per_worker + self.gpu_workers > self.cpu_threads:
            raise ValueError("Concurrent CPU/GPU work requires a reserved host CPU thread per GPU worker")
        if self.gpu_workers > self.cpu_threads:
            raise ValueError("Each GPU worker needs an allocated host CPU thread")
        return self


class BackendCapability(Contract):
    """A verified adapter declaration, not PATH discovery or a blanket engine promise."""
    engine: str
    engine_version: str
    operations: list[str]
    methods: list[str]
    devices: list[Literal["cpu", "gpu"]] = Field(default_factory=lambda: ["cpu"])
    bases: list[str] = Field(default_factory=list)
    verified: bool = False
    evidence: str = ""
    supported_elements: list[str] = Field(default_factory=list)
    supported_multiplicities: list[int] = Field(default_factory=list)
    supports_ions: bool = False
    supports_rigid_fragments: bool = False
    gpu_memory_required_mb: int | None = Field(default=None, ge=1)
    model_sha256: str | None = None
    precision: Literal["float64", "float32", "mixed"] = "float64"


class ScientificStep(Contract):
    step_id: str
    operation: str
    owner: Literal["TOPOS", "BASE", "TORQ", "external"] = "BASE"
    engine: str
    engine_version: str | None = None
    method: str | None = None
    basis: str | None = None
    auxiliary_basis: str | None = None
    dispersion: str | None = None
    solvent: str | None = None
    derivative: Literal["none", "energy", "gradient", "hessian", "anharmonic", "properties"] = "none"
    profile_id: str | None = None
    device: Literal["cpu", "gpu", "unresolved"] = "cpu"
    depends_on: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    prerequisite: str | None = None
    selected_capability: str | None = None


class ExecutionPlan(Contract):
    row: MatrixRow
    requested_row_id: str
    hardware: HardwareSpec
    steps: list[ScientificStep]
    required_inputs: list[str]
    missing_inputs: list[str]
    blockers: list[str]
    warnings: list[str]
    reviewed_revision: dict[str, Any] | None = None
    policies: dict[str, str] = Field(default_factory=lambda: dict(SCIENTIFIC_POLICIES))
    runnable: bool = False
    # Tier duration is never copied into a prediction of elapsed time.
    estimated_wall_seconds: float | None = None


def _step(operation: str, engine: str, method: str | None = None, basis: str | None = None,
          *, derivative: str = "none", **options: Any) -> ScientificStep:
    return ScientificStep(
        step_id="", operation=operation, engine=engine, method=method, basis=basis,
        owner="TOPOS" if engine == "topos" else "TORQ" if engine in {"scipy", "kisiel", "orca_vib"} else
        "external" if engine in {"mace", "matrix-recipe"} else "BASE",
        derivative=derivative, options=options,
        engine_version={"orca": "6.1.1", "xtb": "6.7.1", "crest": "3.0.2"}.get(engine),
        profile_id="orca-mapping-v4.2" if engine == "orca" else
        "xtb-vtight-v1" if engine == "xtb" and derivative == "gradient" else None,
        auxiliary_basis="def2/J" if engine == "orca" and method in {"wB97X-V", "wB97M-V"} else None,
    )


def _recipe(row: MatrixRow) -> tuple[list[ScientificStep], list[str]]:
    """Translate verified, explicit source recipes; opaque campaigns require a row adapter."""
    rid = row.row_id
    inputs = ["molecule"]
    if rid == "T1-10s":
        return [_step("optimize-seeds", "xtb", "GFN2-xTB", derivative="gradient",
                      minimum_seeds=3, maximum_seeds=9, sampling="hand-enumerated")], ["molecule", "topology_seeds"]
    if rid == "T1-1min":
        return [_step("goat", "orca", "GFN2-xTB", derivative="gradient",
                      energy_window_kcal_mol=12.0, confdegen="auto", uphill_method="GFN-FF")], inputs
    if rid == "T1-30min":
        return [_step("goat-explore", "orca+aimnet2", "AIMNet2", derivative="gradient",
                      scf_energy_tolerance_eh=1e-5, report_energies=False)], ["molecule", "model_manifest"]
    if rid == "T1-1h":
        return [_step("crest-nci", "crest", "GFN2-xTB", derivative="gradient",
                      energy_window_kcal_mol=12.0, minimum_seeds=3, nocross=True,
                      noreftopo=True)], ["molecule", "fragments", "topology_seeds"]
    if rid == "T1-3h":
        return [
            _step("union", "topos", preserve_source_attribution=True),
            _step("screen", "crest", "GFN2-xTB"),
            _step("optimize-ensemble", "orca", "r2SCAN-3c", derivative="gradient"),
            _step("hessian-ensemble", "orca", "r2SCAN-3c", derivative="hessian"),
            _step("cregen-reporting", "crest", rotational_fraction=0.001),
        ], ["molecule", "goat_ensemble", "crest_ensemble"]
    if rid == "T1-12h":
        return [_step("goat", "orca", "r2SCAN-3c", derivative="gradient")], ["molecule", "leading_isomers"]
    if rid == "T1-1d":
        return [_step("goat-entropy", "orca", "GFN2-xTB", confdegen="auto"),
                _step("entropy", "crest", "GFN2-xTB"),
                _step("entropy-convergence", "topos", threshold_cal_mol_k=0.1)], ["molecule", "same_seed_ensembles"]
    if rid == "T1-3d":
        return [_step("optimize-ensemble", "orca", "wB97X-V", "def2-TZVPP", derivative="gradient")], ["molecule", "stage_b_ensemble"]
    if rid == "T1-1w":
        training = _step("fine-tune", "mace", "MACE", minimum_points=100, maximum_points=500,
                         experimental=True, required_device="gpu", heldout_evaluation=True)
        training.engine_version = "0.3.16"
        search = _step("goat-and-crest-union", "orca+crest", "custom-MLFF", required_device="gpu",
                       identical_trained_checkpoint=True, native_crest_build="3.0.2+topos-generic-paths-v1")
        search.engine_version = "6.1.1+3.0.2+topos-generic-paths-v1"
        return [training, search,
                _step("optimize-ensemble", "orca", "r2SCAN-3c", derivative="gradient", required_device="cpu"),
                _step("cregen-reporting", "crest", energy_threshold_kcal_mol=0.100,
                      rotational_fraction=0.01, required_device="cpu")], [
                          "molecule", "model_manifest", "reference_training_set", "training_protocol", "ml_search_allocation"]
    if rid == "T1-1mo":
        return [_step("exhaustive-union", "orca+crest", "GFN2-xTB"),
                _step("rerank-ensemble", "orca", "DLPNO-CCSD(T1)")], ["molecule", "topology_seeds", "cc_protocol"]
    if rid in {"T2-10s", "T7-10s"}:
        return [_step("relaxed-scan", "xtb", "GFN2-xTB", derivative="gradient",
                      dimensions=1, both_directions=True)], ["molecule", "scan_coordinates"]
    if rid in {"T2-30min", "T7-30min"}:
        return [_step("relaxed-scan", "orca", "r2SCAN-3c", derivative="gradient",
                      dimensions=1, both_directions=True)], ["molecule", "scan_coordinates"]
    if rid in {"T2-1h", "T7-1h"}:
        return [_step("relaxed-scan", "orca", "wB97X-V", "def2-TZVPP", derivative="gradient",
                      dimensions=2 if rid == "T2-1h" else 1, both_directions=True)], ["molecule", "scan_coordinates"]
    if rid == "T2-3h":
        return [_step("sinc-dvr", "scipy", "sinc-DVR", dimensions=1,
                      precision="float64")], ["potential_grid", "reduced_mass", "boundary_convergence"]
    if rid == "T3O-10s":
        return [_step("optimize", "xtb", "GFN2-xTB", derivative="gradient")], inputs
    if rid == "T3O-1min":
        return [_step("optimize", "orca", "r2SCAN-3c", derivative="gradient",
                      frozen_monomer="frozen-iso")], ["molecule", "isolated_monomer_references", "fragments"]
    if rid in {"T3O-30min", "T3O-1h"}:
        return [_step("optimize", "orca", "wB97X-V",
                      "def2-TZVPP" if rid.endswith("30min") else "jun-cc-pVTZ", derivative="gradient")], inputs
    if rid == "T3O-3h":
        return [
            _step("optimize", "orca", "wB97M-V", "def2-QZVPP", derivative="gradient", frozen_monomer="frozen-iso"),
            _step("counterpoise", "orca", "DLPNO-CCSD(T1)", "cc-pVDZ-F12", derivative="energy",
                  pno="TightPNO", cabs="explicitly-required"),
            _step("vpt2", "orca", "wB97X-V", "def2-TZVPP", derivative="anharmonic"),
        ], ["molecule", "isolated_monomer_references", "fragments", "fragment_states", "cabs_basis", "semirigid_modes"]
    if rid == "T3O-12h":
        return [
            _step("optimize", "orca", "CCSD(T)", "jun-cc-pVTZ", derivative="gradient", frozen_core=True),
            _step("optimize", "orca", "MP2", "jun-cc-pVTZ", derivative="gradient", frozen_core=True),
            _step("optimize", "orca", "MP2", "jun-cc-pVQZ", derivative="gradient", frozen_core=True),
            _step("optimize", "orca", "MP2", "cc-pwCVTZ", derivative="gradient", frozen_core=True),
            _step("optimize", "orca", "MP2", "cc-pwCVTZ", derivative="gradient", frozen_core=False),
            _step("composite-geometry", "topos", "junChS", coordinate_addition="parameter-wise", cbs_exponent=3),
        ], ["molecule", "coordinate_parameterization"]
    if rid == "T4O-10s":
        return [_step("inertial-analysis", "topos")], inputs
    if rid == "T4O-1min":
        return [_step("semiexperimental-scaling", "kisiel", "R6")], ["molecule", "measured_parent_constants", "independent_validation_data"]
    if rid == "T4O-1h":
        step = _step("vpt2", "orca", "B3LYP", "def2-TZVPP", derivative="anharmonic", exclude_linear=True, z_tolerance=1e-14)
        step.dispersion = "D4"
        return [step], ["molecule", "semirigid_modes"]
    if rid == "T4O-12h":
        return [_step("isotope-forcefield-reanalysis", "orca_vib", full_anharmonic_forcefield=True)], ["force_field", "isotopologues"]
    if rid == "T5-10s":
        return [_step("interaction-energy", "xtb", "GFN2-xTB", derivative="energy", frozen_monomer="frozen-inc")], ["molecule", "fragments", "fragment_states"]
    if rid == "T5-1h":
        return [_step("counterpoise", "orca", "wB97M-V", "def2-TZVPP", derivative="energy", reports=["raw", "cp", "half-cp"], shared_basis=True)], ["molecule", "fragments", "fragment_states"]
    if rid == "T5-3d":
        step = _step("energy", "orca", "CCSD(T)-F12D/RI", "cc-pVTZ-F12", derivative="energy")
        step.auxiliary_basis = "cc-pVTZ-F12-CABS"
        return [step], inputs
    if rid == "T5-1d":
        return [_step("energy", "orca", "DLPNO-CCSD(T1)", derivative="energy", tcutpno=1e-6),
                _step("energy", "orca", "DLPNO-CCSD(T1)", derivative="energy", tcutpno=1e-7),
                _step("pno-extrapolation", "topos", "CPS(6/7)", factor=1.5)], ["molecule", "cc_protocol"]
    if rid == "T6O-10s":
        return [_step("inertial-and-dipolar-analysis", "topos")], ["molecule", "nuclear_spin_metadata"]
    if rid == "T6O-1min":
        return [_step("dipole", "xtb", "GFN2-xTB", derivative="properties"),
                _step("signed-principal-axis-projection", "topos")], inputs
    if rid == "T8O-10s":
        return [_step("hessian", "xtb", "GFN2-xTB", derivative="hessian")], inputs
    if rid == "T8O-30min":
        return [_step("hessian", "orca", "r2SCAN-3c", derivative="hessian")], inputs
    if rid == "T8O-1h":
        return [_step("hessian", "orca", "wB97X-V", "def2-TZVPP", derivative="hessian", ir_intensities=True)], inputs
    if rid == "T2-1min":
        return [_step("dense-scan", "mlff", "manifest-bound", derivative="energy", points=1000,
                      report_energies=False)], ["molecule", "scan_coordinates", "model_manifest"]
    if rid == "T3O-1d":
        return [_step("numerical-gradient-optimization", "matrix-recipe", "source-conflicted",
                      derivative="gradient")], ["molecule", "corrected_engine_protocol"]
    if rid == "T3O-3d":
        step = _step("optimize", "orca", "AUTOCI-CCSD(T)", "cc-pVTZ-F12", derivative="gradient",
                     ao_direct=True, correlation_model="canonical-conventional")
        return [step], ["molecule", "auxiliary_basis_protocol"]
    if rid in {"T3O-1w", "T3C-1w", "T3C-1mo"}:
        # Source permits ORCA/CFOUR but does not specify every increment basis.
        # Keep the engine selection explicit; no missing basis is silently guessed.
        engine = "cfour" if rid.startswith("T3C") else "orca"
        steps = [_step("cbs-geometry", engine, "CCSD(T)", derivative="gradient"),
                 _step("core-valence-geometry-increment", engine, "CCSD(T)", derivative="gradient"),
                 _step("full-triples-geometry-increment", engine, "CCSDT", derivative="gradient"),
                 _step("full-quadruples-geometry-increment", engine, "CCSDTQ", derivative="gradient"),
                 _step("composite-geometry", "topos", "CBS+CV+fT+fQ")]
        if rid == "T3C-1w":
            for step in steps[:3]:
                step.options["derivative_mechanism"] = "native analytic gradient"
            steps[3].options.update(
                derivative_mechanism="checked central differences of genuine native NCC CCSDTQ energies",
                native_analytic_gradient=False,
                step_size_check="explicit h and h/2 agreement",
                engine_version="2.1",
            )
        if rid == "T3C-1mo":
            steps.extend([_step("relativistic-geometry-increment", "cfour", derivative="gradient"),
                          _step("dboc-geometry-increment", "cfour", derivative="gradient")])
        return steps, ["molecule", "composite_basis_protocol", "coordinate_parameterization"]
    if rid == "T3O-1mo":
        return [_step("optimize", "molpro", "DF-CCSD(T)-F12", derivative="gradient")], ["molecule", "f12_basis_protocol"]
    if rid in {"T3C-30min", "T3C-3h", "T3C-12h", "T3C-1d"}:
        method, basis, frozen = {
            "T3C-30min": ("MP2", "cc-pVDZ", True),
            "T3C-3h": ("CCSD(T)", "cc-pVTZ", True),
            "T3C-12h": ("CCSD(T)", "cc-pVQZ", True),
            "T3C-1d": ("CCSD(T)", "cc-pCVQZ", False),
        }[rid]
        return [_step("optimize", "cfour", method, basis, derivative="gradient",
                      coordinates="INTERNAL", frozen_core=frozen)], ["molecule", "internal_coordinates"]
    if rid == "T3C-1h":
        return [_step("first-order-properties", "cfour", "CCSD(T)", "cc-pVTZ",
                      derivative="properties", no_geometry_claim=True)], inputs
    if rid == "T3C-3d":
        return [
            _step("optimize", "cfour", "CCSD(T)", "jun-cc-pVTZ", derivative="gradient", frozen_core=True),
            _step("optimize", "cfour", "MP2", "jun-cc-pVTZ", derivative="gradient", frozen_core=True),
            _step("optimize", "cfour", "MP2", "jun-cc-pVQZ", derivative="gradient", frozen_core=True),
            _step("optimize", "cfour", "MP2", "cc-pwCVTZ", derivative="gradient", frozen_core=True),
            _step("optimize", "cfour", "MP2", "cc-pwCVTZ", derivative="gradient", frozen_core=False),
            _step("composite-geometry", "topos", "junChS", coordinate_addition="parameter-wise", cbs_exponent=3),
        ], ["molecule", "coordinate_parameterization", "internal_coordinates"]
    if rid == "T5-1min":
        return [_step("interaction-energy", "mlff", "manifest-bound", derivative="energy",
                      interpretation="broad-screen-only", committee_uncertainty=True,
                      energy_culling_authorized=False,
                      ranking_audit_required_before_culling=True)], ["molecule", "fragments", "fragment_states", "model_manifest", "explicit_no_culling_policy"]
    if rid == "T5-30min":
        return [_step("interaction-energy", "orca", "r2SCAN-3c", derivative="energy",
                      frozen_monomer="frozen-inc", composite_native_gcp=True)], ["molecule", "fragments", "fragment_states"]
    if rid == "T5-3h":
        return [_step("energy", "orca", "CCSD(T)-F12b", "jun-cc-pVTZ", derivative="energy"),
                _step("cbs-energy-increment", "orca", "MP2-F12", derivative="energy"),
                _step("core-valence-energy-increment", "orca", "MP2", "cc-pwCVTZ", derivative="energy"),
                _step("composite-energy", "topos", "junChS-F12")], ["molecule", "fragments", "fragment_states", "f12_basis_protocol"]
    if rid == "T5-12h":
        return [_step("led-energy-decomposition", "orca", "DLPNO-CCSD(T1)", "cc-pVDZ-F12",
                      derivative="energy", pno="TightPNO", tcutpno=1e-7, storage="Shared")], ["molecule", "fragments", "fragment_states", "auxiliary_basis_protocol"]
    if rid == "T5-1w":
        return [_step("cbs-energy", "cfour", "CCSD(T)", derivative="energy"),
                _step("core-valence-energy-increment", "cfour", "CCSD(T)", derivative="energy"),
                _step("full-triples-energy-increment", "cfour", "CCSDT", derivative="energy"),
                _step("composite-energy", "topos", "CBS+CV+fT")], ["molecule", "fragments", "fragment_states", "composite_basis_protocol"]
    if rid == "T5-1mo":
        return [_step("sapt-decomposition", "psi4", "SAPT2+3", derivative="energy")], ["molecule", "fragments", "fragment_states", "sapt_basis_protocol"]
    # Complete catalog coverage must not become guessed method/basis syntax. An external
    # row adapter is explicit, versioned and can be advertised by BASE/TORQ or another code.
    step = _step("matrix-recipe:" + rid, "matrix-recipe")
    step.options = {"source_method": row.method_text, "source_workflow": row.expansion.get("workflow"),
                    "source_revision": row.revision, "source_sha256": row.source.sha256,
                    "outputs": row.delivers, "state_in": row.expansion.get("state_in"),
                    "state_out": row.expansion.get("state_out")}
    step.prerequisite = "Register and validate the complete " + rid + " recipe, including any external dependencies, before execution."
    return [step], ["molecule", "validated_recipe_inputs:" + rid]


def reviewed_revision(source_resolution: str) -> dict[str, Any]:
    if source_resolution not in REVIEWED_RECIPES:
        raise ValueError('No reviewed matrix revision matches this explicit variant')
    definition = {'revision':REVIEWED_REVISION, 'archived_revision':MATRIX_REVISION,
                  'archived_source_sha256':SOURCE_SHA256, 'recipes':REVIEWED_RECIPES, 'sources':REVIEWED_SOURCES}
    digest = hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    return {'revision':REVIEWED_REVISION, 'sha256':digest, 'variant':source_resolution,
            'archived_revision':MATRIX_REVISION, 'archived_source_sha256':SOURCE_SHA256,
            'definition':REVIEWED_RECIPES[source_resolution],
            'sources':REVIEWED_RECIPES[source_resolution].get('sources', REVIEWED_SOURCES),
            'user_decision':REVIEWED_RECIPES[source_resolution].get('decision_basis',
                'User explicitly authorized named ORCA alternatives and documented scientific differences')}


def resolved_recipe(row: MatrixRow, source_resolution: str | None = None) -> tuple[list[ScientificStep], list[str]]:
    """Shared typed branch selection for execution and pre-provision Actions gates."""
    if source_resolution in REVIEWED_RECIPES:
        definition = REVIEWED_RECIPES[source_resolution]
        if definition['row_id'] != row.row_id:
            raise ValueError('Reviewed scientific variant does not match the archived row')
        if definition.get('kind') == 'r2-dft-vpt2-transfer':
            steps = [
                _step('optimize', 'orca', 'wB97M-V', 'def2-QZVPP', derivative='gradient', frozen_monomer='frozen-iso'),
                _step('counterpoise', 'orca', 'DLPNO-CCSD(T1)', 'cc-pVDZ-F12', derivative='energy',
                      frozen_core=True, pno='TightPNO', f12_hamiltonian=False, cabs=None),
                _step('strict-unconstrained-reference-optimize', 'orca', definition['reference_method'], 'def2-TZVPP', derivative='gradient',
                      profile='orca-vpt2-reference-v1', dispersion=definition['reference_dispersion'], independent_from_frozen_geometry=True),
                _step('vpt2', 'orca', definition['reference_method'], 'def2-TZVPP', derivative='anharmonic',
                      reference='separately fully relaxed stationary DFT minimum', dispersion=definition['reference_dispersion'], constraints=False),
                _step('rotational-correction-transfer', 'topos', 'R2-separate-DFT-VPT2',
                      formula='B0_approx=B_R2+(B0_DFT-Be_DFT)', approximate_composite=True, empirical_accuracy=None),
            ]
            steps[1].profile_id = None
            steps[1].options['exact_native_protocol_input'] = 'r2_counterpoise.native'
            for step in steps[2:4]:
                step.profile_id = 'orca-vpt2-reference-v1'
                step.auxiliary_basis = 'def2/J'
                step.dispersion = definition['reference_dispersion']
            return steps, ['molecule', 'fragments', 'fragment_states', 'isolated_monomer_references',
                           'r2_monomer_provenance', 'r2_counterpoise', 'r2_vpt2']
        if definition.get('kind') == 'cfour-counterpoise-geometry':
            steps, _ = _recipe(resolve_row('T3C-1w'))
            for step in steps[:4]:
                step.operation = 'raw-and-cp-' + step.operation
                step.options.update(derivative_mechanism='checked h/h2 central differences of genuine native energies',
                    native_analytic_gradient=False, branches=['raw', 'relaxed-total-counterpoise'],
                    cp_potential='E_AB+sum(E_i_own-E_i_ghost)', engine_version='2.1')
                step.engine_version = '2.1'
            steps[-1].operation = 'counterpoise-bracketed-composite-geometries'
            steps[-1].options.update(midpoint_geometry=False, composite_stationarity_verified=False)
            return steps, ['molecule', 'fragments', 'fragment_states', 'cfour_counterpoise']
        if definition.get('kind') in {'conditional-month-geometry', 'observed-mass-month-geometry'}:
            observed = definition['kind'] == 'observed-mass-month-geometry'
            steps, required = _recipe(resolve_row('T3C-1w'))
            steps.extend([
                _step('scalar-HF-geometry-increment', 'cfour', 'HF', derivative='gradient',
                      derivative_mechanism='checked h/h2 native energy differences',
                      paired_hamiltonians=['OFF', 'X2C1E'], contraction='UNCONTRACTED'),
                _step('default-mass-HF-dboc-geometry-increment', 'cfour', 'HF', derivative='gradient',
                      derivative_mechanism='checked h/h2 native HF+DBOC energy differences with print precision bound',
                      numeric_masses_required=observed, rotor_constants_withheld=not observed,
                      mass_evidence="every actual DBOC-enabled native output, mapped atom order and print precision" if observed else "not published"),
                _step('observed-default-mass-corrected-rotors' if observed else 'conditional-corrected-geometry', 'topos', 'CBS+CV+fT+fQ+HF-corrections',
                      full_matrix_row_completed=observed, rotor_constants_withheld=not observed,
                      native_mass_attestation_required=observed, mass_kind='atomic masses for rigid rotor; nuclear DBOC masses remain native internal convention'),
            ])
            return steps, [*required, 'month_corrections', 'native_default_mass_domain']
        if definition.get('kind') == 'composite-interaction':
            return [_step('energy', 'orca', 'CCSD(T)-F12D/RI', 'jun-cc-pVTZ', derivative='energy', frozen_core=True),
                    _step('mp2-f12-cbs', 'orca', derivative='energy',
                          methods=['F12-MP2', 'F12-RI-MP2'], bases=['jun-cc-pVTZ', 'jun-cc-pVQZ'],
                          extrapolation='separate HF+CABS exponential and F12-correlation power'),
                    _step('same-basis-core-valence', 'orca', 'MP2', 'cc-pwCVTZ', derivative='energy'),
                    _step('composite-interaction', 'topos', 'ORCA-F12D-CBS-CV')], [
                        'molecule', 'fragments', 'fragment_states', 'orca_f12_composite']
        step = _step('numerical-energy-geometry', 'orca', 'CCSD(T)-F12D/RI', definition['orbital_basis'],
                     derivative='gradient', native_analytic_gradient=False,
                     derivative_mechanism='checked h/h2 central differences of actual native energies',
                     frozen_core=True, cabs=definition['cabs'], source_resolution=source_resolution)
        step.auxiliary_basis = definition['auxiliary_c']
        return [step], ['molecule', 'orca_numerical_geometry']
    if source_resolution == "orca-f12-reference-singlepoint-v1" and row.row_id == "T3O-1mo":
        return [_step("energy", "orca", "CCSD(T)-F12D/RI", "cc-pVTZ-F12", derivative="energy",
                      geometry_optimized=False, source_resolution=source_resolution)], ["molecule", "correlated_protocol"]
    if source_resolution is not None and (source_resolution, row.row_id) != ("native-composite-rawinteraction-v1", "T5-30min"):
        raise ValueError("No compiled scientific source-conflict resolution matches this row")
    return _recipe(row)


def plan_route(row_id: str, *, hardware: HardwareSpec, capabilities: list[BackendCapability],
               product: str = "A", available_inputs: list[str] | None = None,
               symbols: list[str] | None = None, charge: int = 0, multiplicity: int = 1,
               source_resolution: str | None = None) -> ExecutionPlan:
    row = resolve_row(row_id, product=product)
    steps, required = resolved_recipe(row, source_resolution)
    inputs = set(available_inputs or [])
    missing = sorted(set(required) - inputs)
    blockers = list(row.source_conflicts)
    if row.track_gap:
        disposition = unavailable_by_design(row.row_id)
        blockers.append(_unavailable_blocker(disposition) if disposition else
                        "This matrix row is an explicit track gap; choose a listed alternative explicitly.")
    warnings = ["Nominal tier labels do not guarantee completion, sampling coverage or chemical accuracy.",
                row.limitations]
    reviewed = None
    if source_resolution is not None:
        if source_resolution in REVIEWED_RECIPES:
            reviewed = reviewed_revision(source_resolution)
            warnings.extend(blockers)
            blockers = []
            warnings.extend(reviewed['definition']['differences'])
            if reviewed['definition'].get('native_capability_blocker'):
                blockers.append(reviewed['definition']['native_capability_blocker'])
        elif row.row_id == "T3O-1mo" and source_resolution == "orca-f12-reference-singlepoint-v1":
            warnings.append("Only the source's ORCA reference-energy branch is selected; no new reference geometry or B_e is computed")
        elif row.row_id == "T5-30min" and source_resolution == "native-composite-rawinteraction-v1":
            warnings.extend(blockers)
            blockers = []
            warnings.append("Explicit resolution: native r2SCAN-3c interaction including its native gCP; no separate CP or half-CP values are defined")
            steps[0].options["source_resolution"] = source_resolution
            steps[0].options["separate_counterpoise"] = False
        else:
            raise ValueError("No compiled scientific source-conflict resolution matches this row")
    if canonical_row_id(row_id) != row_id:
        warnings.append(f"Decision-card alias {row_id} resolves explicitly to {row.row_id}.")
    if product == "B" and "measured_parent_constants" not in inputs:
        blockers.append("Product B requires cited measured parent constants and independent validation.")
    for index, step in enumerate(steps):
        step.step_id = f"{row.row_id}:{index + 1}"
        if index:
            step.depends_on = [steps[index - 1].step_id]
        step.inputs = required if index == 0 else [steps[index - 1].step_id + ":outputs"]
        step.outputs = (reviewed['definition']['delivers'] if reviewed else [row.delivers]) if index == len(steps) - 1 else [step.operation + ":results"]
        candidates = [c for c in capabilities if c.engine == step.engine and c.verified and c.evidence
                      and step.operation in c.operations and (step.method is None or step.method in c.methods)
                      and (step.engine_version is None or step.engine_version == c.engine_version)
                      and (step.basis is None or step.basis in c.bases)]
        if symbols:
            candidates = [c for c in candidates if c.supported_elements and set(symbols) <= set(c.supported_elements)]
        candidates = [c for c in candidates if (not charge or c.supports_ions)
                      and multiplicity in c.supported_multiplicities]
        if step.options.get("frozen_monomer") == "frozen-iso":
            candidates = [c for c in candidates if c.supports_rigid_fragments]
        selected = None
        for capability in candidates:
            required_device = step.options.get("required_device")
            if required_device == "gpu" and hardware.device == "cpu":
                continue
            wanted = [required_device] if required_device else ([hardware.device] if hardware.device != "auto" else ["cpu", "gpu"])
            for device in wanted:
                if device not in capability.devices:
                    continue
                if step.engine in {"orca", "xtb", "crest"} and device == "gpu":
                    continue
                if device == "gpu":
                    if not hardware.gpu_model or not hardware.gpu_memory_mb:
                        continue
                    if capability.gpu_memory_required_mb is None or (
                        capability.gpu_memory_required_mb * hardware.gpu_workers > hardware.gpu_memory_mb
                    ):
                        continue
                if ("model_manifest" in required and step.engine in {"mlff", "mace", "orca+aimnet2", "orca+crest"}
                        and not capability.model_sha256):
                    continue
                if capability.precision != "float64" and row.row_id not in {"T1-30min", "T2-1min"}:
                    continue
                selected = capability
                step.device = device
                break
            if selected:
                break
        if selected:
            step.selected_capability = selected.engine + "/" + selected.engine_version
        else:
            step.device = "unresolved"
            blockers.append(f"{step.step_id} requires verified {step.engine} {step.engine_version or ''} "
                            f"operation {step.operation}, method {step.method or 'source recipe'} "
                            f"and matching basis, chemistry domain and device.")
    if missing:
        blockers.append("Missing scientific inputs: " + ", ".join(missing))
    return ExecutionPlan(row=row, requested_row_id=row_id, hardware=hardware, steps=steps,
                         required_inputs=required, missing_inputs=missing, blockers=blockers,
                         warnings=warnings, runnable=not blockers, reviewed_revision=reviewed)


# Bind only rows representable by one primitive RunRequest. Compound recipes must use
# their execution plan; a successful optimization must never certify a CP/VPT2 campaign.
PRIMITIVE_BINDINGS = {
    "T3O-10s": ("xtb", "GFN2-xTB", "optimize", None, "xtb-vtight-v1"),
    "T3O-1min": ("orca", "r2SCAN-3c", "optimize", None, "orca-mapping-v4.2"),
    "T3O-30min": ("orca", "wB97X-V", "optimize", "def2-TZVPP", "orca-mapping-v4.2"),
    "T3O-1h": ("orca", "wB97X-V", "optimize", "jun-cc-pVTZ", "orca-mapping-v4.2"),
    "T8O-10s": ("xtb", "GFN2-xTB", "hessian", None, "xtb-vtight-v1"),
    "T8O-30min": ("orca", "r2SCAN-3c", "hessian", None, "orca-mapping-v4.2"),
    "T8O-1h": ("orca", "wB97X-V", "hessian", "def2-TZVPP", "orca-mapping-v4.2"),
}


def validate_request_matrix(request: Any) -> tuple[str, str] | None:
    """Reject mismatched explicit row requests without mutating a user's scientific state."""
    row_id = getattr(request, "matrix_row_id", None)
    if row_id is None:
        return None
    if request.matrix_revision != MATRIX_REVISION:
        return "unsupported", "Explicit matrix rows require the pinned full-matrix revision."
    try:
        row = resolve_row(row_id, product=getattr(request, "matrix_product", "A"))
    except ValueError as exc:
        return "unsupported", str(exc)
    disposition = unavailable_by_design(row.row_id)
    if disposition is not None:
        return "unsupported", _unavailable_blocker(disposition)
    if row.source_conflicts or row.track_gap:
        return "unsupported", "; ".join(row.source_conflicts) or "Selected row is a matrix track gap."
    if row.row_id not in PRIMITIVE_BINDINGS:
        return "unsupported", "This row requires a complete matrix execution plan, not one primitive calculation."
    engine, method, purpose, basis, profile = PRIMITIVE_BINDINGS[row.row_id]
    actual = (request.engine, request.method, request.purpose, request.basis, request.profile_id)
    if actual != (engine, method, purpose, basis, profile):
        return "unsupported", "Engine, method, purpose, basis or convergence profile does not match the selected row."
    if request.dispersion or request.solvent:
        return "unsupported", "The matrix row does not permit additional dispersion or solvent models."
    expected_aux = "def2/J" if method in {"wB97X-V", "wB97M-V"} else None
    if request.auxiliary_basis != expected_aux:
        return "unsupported", "Auxiliary basis does not match the selected row."
    if row.row_id == "T3O-1min":
        if request.constraints.get("kind", "frozen-monomers") != "frozen-monomers" or not request.constraints or not request.metadata.get("isolated_monomer_references"):
            return "unsupported", "R1 requires rigid fragments and provenance for isolated reference monomers."
    return None


class CalibrationKey(Contract):
    """An exact cache boundary; no transfer between unknown hardware or Hamiltonians."""
    row_id: str
    matrix_revision: str = MATRIX_REVISION
    engine: str
    engine_version: str
    method: str
    basis: str | None = None
    profile_id: str
    hardware_fingerprint: str = Field(min_length=1)
    device: Literal["cpu", "gpu"] = "cpu"
    threads: int = Field(ge=1)
    memory_mb: int = Field(ge=64)
    # Includes basis count, charge/spin, atom count, task, constraints, numerical/grid
    # settings and model digest. Calibration producers must retain these explicitly.
    problem: dict[str, str | int | float | bool]

    @model_validator(mode="after")
    def complete_problem(self) -> CalibrationKey:
        required = {"atom_count", "charge", "multiplicity", "operation", "constraints_sha256"}
        if not required <= self.problem.keys():
            raise ValueError("Calibration needs atom count, charge, multiplicity, operation and constraint digest")
        for name in ("atom_count", "multiplicity"):
            value = self.problem[name]
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"Calibration {name} must be a positive integer")
        if not isinstance(self.problem["charge"], int) or isinstance(self.problem["charge"], bool):
            raise ValueError("Calibration charge must be an integer")
        if not isinstance(self.problem["operation"], str) or not self.problem["operation"].strip():
            raise ValueError("Calibration operation must be explicit")
        if not isinstance(self.problem["constraints_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", self.problem["constraints_sha256"]):
            raise ValueError("Calibration constraint state requires a SHA-256 digest")
        if self.matrix_revision != MATRIX_REVISION:
            raise ValueError("Calibration matrix revision is not current")
        from .orca_numerical_profiles import MAPPING_V42, numerical_profile_receipt

        if self.profile_id == MAPPING_V42:
            receipt = numerical_profile_receipt(self.profile_id)
            if (self.engine != "orca" or self.engine_version != "6.1.1"
                    or self.problem.get("numerical_profile_sha256") != receipt["definition_sha256"]):
                raise ValueError("Runtime calibration must bind the exact versioned ORCA numerical profile")
        canonical_row_id(self.row_id)
        return self

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"),
                                        allow_nan=False).encode()).hexdigest()


class RuntimeSample(Contract):
    key: CalibrationKey
    wall_seconds: float = Field(gt=0)
    queue_seconds: float = Field(default=0, ge=0)
    status: Literal["completed"] = "completed"
    measurement_id: str = Field(min_length=1)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RuntimeEstimate(Contract):
    matching_samples: int
    median_seconds: float | None = None
    lower_seconds: float | None = None
    upper_seconds: float | None = None
    interval_coverage: float | None = None
    includes_queue: bool
    calibrated: bool = False
    interpretation: str

    def fits_budget(self, budget_seconds: float) -> bool | None:
        if not math.isfinite(budget_seconds) or budget_seconds <= 0:
            raise ValueError("Budget must be finite and positive")
        if self.upper_seconds is None:
            return None
        return self.upper_seconds <= budget_seconds


class CalibratedRuntimeEstimator:
    """Exact-context measured wall times with an explicit log-normal prediction interval.

    With fewer than three measurements, report the observations but no uncertainty
    interval or schedulability decision. This is not an accuracy estimator. Runs are
    never scaled using reference-table ratios, core counts or guessed GPU throughput.
    """

    def __init__(self, samples: list[RuntimeSample] | None = None):
        self._samples: list[RuntimeSample] = []
        for sample in samples or []:
            self.add(sample)

    def add(self, sample: RuntimeSample) -> None:
        if any(s.measurement_id == sample.measurement_id for s in self._samples):
            raise ValueError("A measurement may not be counted twice")
        self._samples.append(sample.model_copy(deep=True))

    def estimate(self, key: CalibrationKey, *, include_queue: bool = True,
                 interval_coverage: float = 0.95) -> RuntimeEstimate:
        if not 0 < interval_coverage < 1:
            raise ValueError("Prediction-interval coverage must be between zero and one")
        values = [s.wall_seconds + (s.queue_seconds if include_queue else 0)
                  for s in self._samples if s.key.digest() == key.digest()]
        if not values:
            return RuntimeEstimate(matching_samples=0, includes_queue=include_queue,
                                   interpretation="Uncalibrated: run matched pilot calculations on this hardware; no timing prediction.")
        median = statistics.median(values)
        if len(values) < 3:
            return RuntimeEstimate(matching_samples=len(values), median_seconds=median,
                                   includes_queue=include_queue,
                                   interpretation="Fewer than three matched measurements; no prediction interval or budget-fit claim.")
        from scipy.stats import t

        logs = [math.log(v) for v in values]
        mean = statistics.mean(logs)
        half_width = float(t.ppf((1 + interval_coverage) / 2, len(values) - 1)) * statistics.stdev(logs) * math.sqrt(1 + 1 / len(values))
        try:
            lower, upper = math.exp(mean - half_width), math.exp(mean + half_width)
        except OverflowError:
            lower, upper = None, None
        return RuntimeEstimate(
            matching_samples=len(values), median_seconds=median, lower_seconds=lower,
            upper_seconds=upper, interval_coverage=interval_coverage if upper is not None else None,
            includes_queue=include_queue, calibrated=upper is not None,
            interpretation="Prediction interval assumes independent log-normal durations for the exact matched context; "
                           "it measures timing variability, not chemistry accuracy or exhaustive search. "
                           "Changed methods, hardware, state, constraints or numerical settings require new calibration.",
        )

    def save(self, path: Path | str) -> None:
        from .storage import atomic_json

        payload = {"schema_version": "topos-runtime-calibration/1",
                   "samples": [s.model_dump() for s in self._samples]}
        atomic_json(Path(path), payload)

    @classmethod
    def load(cls, path: Path | str) -> CalibratedRuntimeEstimator:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if set(data) != {"schema_version", "samples"} or data["schema_version"] != "topos-runtime-calibration/1":
            raise ValueError("Unknown runtime calibration cache schema")
        return cls([RuntimeSample.model_validate(s) for s in data["samples"]])
