"""Typed, JSON-serializable contracts for TOPOS 0.1.0.

Coordinates are angstroms; scientific quantities carry their own explicit units.
No missing result is represented by a numerical sentinel.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "topos/0.1.0"
ExecutionStatus = Literal[
    "queued", "running", "completed", "partial", "timed-out", "cancelled",
    "failed", "unavailable", "unsupported",
]
ValidationStatus = Literal[
    "not-evaluated", "rejected", "validated-for-protocol", "human-review",
]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, allow_inf_nan=False, hide_input_in_errors=True,
    )

    @model_validator(mode="before")
    @classmethod
    def reject_secrets_and_nonfinite_metadata(cls, value: Any) -> Any:
        """Keep credential values and non-JSON floats out of persisted contracts."""
        import math

        def check(item: Any) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    normalized = str(key).lower().replace("-", "_")
                    if any(word in normalized for word in (
                        "password", "passwd", "secret", "api_key", "apikey", "authorization",
                        "credential", "private_key", "access_token", "refresh_token",
                    )) or normalized == "token" or normalized.endswith("_token"):
                        raise ValueError("credential-bearing keys are forbidden in scientific records")
                    check(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    check(child)
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("nonfinite values are forbidden in scientific records")

        check(value)
        return value


class Bond(Contract):
    atom1: int = Field(ge=0)
    atom2: int = Field(ge=0)
    order: float = Field(default=1.0, gt=0)
    kind: Literal["covalent", "coordination", "unknown"] = "covalent"


class FragmentState(Contract):
    atom_indices: list[int]
    charge: int
    multiplicity: int = Field(ge=1)


class Molecule(Contract):
    symbols: list[str] = Field(min_length=1)
    coordinates: list[list[float]]
    coordinate_units: Literal["angstrom"] = "angstrom"
    charge: int = 0
    multiplicity: int = Field(default=1, ge=1)
    isotopes: list[int | None] = Field(default_factory=list)
    atom_ids: list[str] = Field(default_factory=list)
    fragments: list[list[int]] = Field(default_factory=list)
    fragment_states: list[FragmentState] = Field(default_factory=list)
    bonds: list[Bond] = Field(default_factory=list)
    stereochemistry: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    name: str | None = None

    @model_validator(mode="after")
    def validate_structure(self) -> Molecule:
        import math

        n = len(self.symbols)
        if len(self.coordinates) != n or any(len(row) != 3 for row in self.coordinates):
            raise ValueError("coordinates must have exactly one finite x,y,z row per atom")
        if any(not math.isfinite(x) for row in self.coordinates for x in row):
            raise ValueError("coordinates must be finite")
        if not self.isotopes:
            object.__setattr__(self, "isotopes", [None] * n)
        if not self.atom_ids:
            object.__setattr__(self, "atom_ids", [f"atom-{i}" for i in range(n)])
        if len(self.isotopes) != n or any(a is not None and a <= 0 for a in self.isotopes):
            raise ValueError("isotopes must specify a positive mass number or null per atom")
        if len(self.atom_ids) != n or len(set(self.atom_ids)) != n:
            raise ValueError("atom_ids must be unique and match the atom count")
        if self.fragments:
            indices = [i for fragment in self.fragments for i in fragment]
            if any(not fragment for fragment in self.fragments) or sorted(indices) != list(range(n)):
                raise ValueError("fragments must partition all atom indices exactly once")
        seen = set()
        for bond in self.bonds:
            pair = tuple(sorted((bond.atom1, bond.atom2)))
            if pair[0] == pair[1] or pair[1] >= n or pair in seen:
                raise ValueError("bonds must have distinct valid atom indices and no duplicate edges")
            seen.add(pair)
        from .chemistry import atomic_number, isotope_mass

        electrons = sum(atomic_number(s) for s in self.symbols) - self.charge
        unpaired = self.multiplicity - 1
        if electrons < 0 or unpaired > electrons or (electrons - unpaired) % 2:
            raise ValueError("charge/multiplicity is inconsistent with electron count and spin parity")
        for symbol, mass_number in zip(self.symbols, self.isotopes, strict=True):
            if mass_number is not None:
                isotope_mass(symbol, mass_number)
        if self.fragment_states:
            state_groups = [sorted(s.atom_indices) for s in self.fragment_states]
            if sorted(state_groups) != sorted(sorted(g) for g in self.fragments):
                raise ValueError("fragment_states must match the declared fragment partition")
            if sum(s.charge for s in self.fragment_states) != self.charge:
                raise ValueError("fragment charges must sum to molecular charge")
            for state in self.fragment_states:
                ne = sum(atomic_number(self.symbols[i]) for i in state.atom_indices) - state.charge
                u = state.multiplicity - 1
                if ne < u or (ne - u) % 2:
                    raise ValueError("fragment charge/multiplicity violates electron parity")
            coupled_spins = {0}
            for state in self.fragment_states:
                fragment_spin = state.multiplicity - 1
                coupled_spins = {total for previous in coupled_spins
                                 for total in range(abs(previous - fragment_spin), previous + fragment_spin + 1, 2)}
            if unpaired not in coupled_spins:
                raise ValueError("molecular spin cannot couple from the specified fragment spin states")
        return self


class ResourceLimits(Contract):
    budget_seconds: float = Field(default=300.0, gt=0)
    threads: int = Field(default=1, ge=1)
    memory_mb: int = Field(default=1024, ge=64)
    device: str = "cpu"


class MethodSpec(Contract):
    engine: str
    method: str
    purpose: str = "optimize"
    basis: str | None = None
    auxiliary_basis: str | None = None
    dispersion: str | None = None
    solvent: str | None = None
    engine_version: str | None = None
    profile_id: str = "screening-v1"
    constraints: dict[str, Any] = Field(default_factory=dict)


class ThermalOptions(Contract):
    optimize_first: bool = True
    step_bohr: float = Field(default=0.005, gt=0, le=0.1)
    pressure_pa: float = Field(default=101325, gt=0)
    concentration_mol_l: float | None = Field(default=None, gt=0)
    symmetry_number: int | None = Field(default=None, ge=1)
    frequency_scale: float = Field(default=1.0, gt=0)
    low_frequency_policy: Literal["reject", "frequency-floor"] = "reject"
    cutoff_cm1: float = Field(default=10, gt=0)


class RigidmolAtomParameter(Contract):
    atom_id: str = Field(min_length=1)
    charge_e: float = Field(strict=True)
    epsilon_kj_mol: float = Field(ge=0, strict=True)
    sigma_angstrom: float = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def repulsion_has_a_length(self):
        if self.epsilon_kj_mol > 0 and self.sigma_angstrom <= 0:
            raise ValueError("A nonzero Lennard-Jones well depth requires a positive sigma")
        return self


class RigidmolOptions(Contract):
    atomic_parameters: list[RigidmolAtomParameter] = Field(min_length=1)
    parameter_source: str = Field(min_length=1)
    population: int = Field(default=20, ge=5, le=100000, strict=True)
    generations: int = Field(default=20, ge=1, le=1000000, strict=True)
    scout_limit: int = Field(default=3, ge=1, le=1000000, strict=True)
    amplitude_angstrom: float = Field(default=4, gt=0, le=100, strict=True)
    max_saved_minima: int = Field(default=30, ge=1, le=10000, strict=True)

    @model_validator(mode="after")
    def explicit_parameter_identity(self):
        if not self.parameter_source.strip():
            raise ValueError("ABCluster requires a nonempty cited force-field parameter source")
        identities = [parameter.atom_id for parameter in self.atomic_parameters]
        if len(set(identities)) != len(identities):
            raise ValueError("ABCluster parameters must identify each input atom only once")
        return self


class RunRequest(Contract):
    molecule: Molecule
    engine: str = "xtb"
    method: str = "GFN2-xTB"
    engine_version: str | None = None
    purpose: str = "search"
    search_algorithm: Literal["jiggle-quench", "crest", "union", "abcluster"] = "jiggle-quench"
    abcluster_options: RigidmolOptions | None = None
    sampler_profile: Literal["crest-imtdgc-v1", "crest-mquick-v1", "crest-nci-v1"] = "crest-imtdgc-v1"
    sampler_nci: bool = False
    sampler_budget_fraction: float = Field(default=0.5, gt=0, lt=1)
    presentation_environment: str = "local"
    calculation_environment: str = "local"
    budget_seconds: float = Field(default=300.0, gt=0)
    budget_scope: Literal["workflow"] = "workflow"
    include_queue_in_budget: bool = False
    per_geometry_budget_seconds: float | None = Field(default=None, gt=0, strict=True)
    per_ensemble_budget_seconds: float | None = Field(default=None, gt=0, strict=True)
    seed: int = Field(default=0, ge=0)
    n_candidates: int = Field(default=4, ge=1, le=10000)
    threads: int = Field(default=1, ge=1)
    memory_mb: int = Field(default=1024, ge=64)
    device: str = "cpu"
    profile_id: str = "screening-v1"
    matrix_revision: str = "topos-0.1.0-supported-profile-v1"
    matrix_row_id: str | None = None
    matrix_product: Literal["A", "B", "C"] = "A"
    matrix_inputs: dict[str, Any] = Field(default_factory=dict)
    basis: str | None = None
    auxiliary_basis: str | None = None
    dispersion: str | None = None
    solvent: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    temperature_k: float = Field(default=298.15, gt=0)
    thermochemistry_options: ThermalOptions = Field(default_factory=ThermalOptions)
    deduplication_stage: Literal["generation", "reporting"] = "generation"
    collapse_enantiomers: bool = False
    environment_is_achiral: bool | None = None
    dipole_method_error_debye: float | None = Field(default=None, gt=0)
    symmetry_tolerance_angstrom: float = Field(default=0.001, gt=0, le=0.1)
    rmsd_threshold_angstrom: float = Field(default=0.125, gt=0)
    dedup_energy_threshold_kcal_mol: float = Field(default=0.05, gt=0)
    dedup_rotational_threshold_fraction: float = Field(default=0.01, gt=0, lt=1)
    energy_window_kcal_mol: float = Field(default=6.0, gt=0)
    perturbation_angstrom: float = Field(default=0.15, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_sampling_options(self) -> RunRequest:
        if self.search_algorithm == "abcluster":
            if self.purpose not in {"search", "association"} or self.abcluster_options is None:
                raise ValueError("ABCluster applies to search/association and requires explicit abcluster_options")
            if {p.atom_id for p in self.abcluster_options.atomic_parameters} != set(self.molecule.atom_ids):
                raise ValueError("ABCluster force-field parameters must match every input atom ID exactly")
        elif self.abcluster_options is not None:
            raise ValueError("ABCluster force-field options require an explicit abcluster sampler selection")
        if self.sampler_nci:
            if self.purpose not in {"search", "association"} or self.search_algorithm not in {"crest", "union"}:
                raise ValueError("sampler_nci applies only to CREST or union searches")
            if len(self.molecule.fragments) < 2:
                raise ValueError("NCI sampling requires at least two explicitly declared fragments")
        if self.sampler_profile == "crest-nci-v1" and not self.sampler_nci:
            raise ValueError("crest-nci-v1 requires sampler_nci=true and declared fragments")
        return self

    @property
    def resources(self) -> ResourceLimits:
        return ResourceLimits(**{k: getattr(self, k) for k in ResourceLimits.model_fields})

    @property
    def method_spec(self) -> MethodSpec:
        fields = {k: getattr(self, k) for k in MethodSpec.model_fields if hasattr(self, k)}
        return MethodSpec(**fields)


class Quantity(Contract):
    name: str
    value: float | list[float] | list[list[float]] | None
    units: str
    definition: str
    geometry_id: str | None = None
    attempt_id: str | None = None
    method: str | None = None
    parser: str | None = None
    validity: ValidationStatus = "not-evaluated"
    metadata: dict[str, Any] = Field(default_factory=dict)


class Artifact(Contract):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    role: str = "raw-output"
    media_type: str | None = None


class Attempt(Contract):
    attempt_id: str = Field(default_factory=lambda: new_id("attempt"))
    run_id: str
    parent_attempt_id: str | None = None
    engine: str
    method: str
    status: ExecutionStatus = "queued"
    validation_status: ValidationStatus = "not-evaluated"
    started_at: str | None = None
    finished_at: str | None = None
    converged: bool | None = None
    command: list[str] = Field(default_factory=list)
    engine_version: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    quantities: list[Quantity] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Candidate(Contract):
    candidate_id: str = Field(default_factory=lambda: new_id("candidate"))
    molecule: Molecule
    attempt_id: str | None = None
    energy_hartree: float | None = None
    gibbs_hartree: float | None = None
    comparison_protocol: str | None = None
    degeneracy: float = Field(default=1.0, gt=0)
    status: str = "unreviewed"
    sources: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunRecord(Contract):
    run_id: str = Field(default_factory=lambda: new_id("run"))
    schema_version: Literal["topos/0.1.0"] = SCHEMA_VERSION
    request: RunRequest
    status: ExecutionStatus = "queued"
    validation_status: ValidationStatus = "not-evaluated"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    attempts: list[Attempt] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
