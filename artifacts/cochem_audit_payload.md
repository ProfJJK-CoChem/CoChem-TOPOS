Perform adversarial static analysis and logical review on implemented code for D:\__CoChem\__agentic\.prompts\.SRS\CoChem-TOPOS\.in-progress\02_03_topology_graph.md.
Original prompt:
# Task: Implement Graph Cleavage & Routing (`cochem_topos_graph.py`)

## Target Output File
`${COCHEM_WORKSPACE}\GitHub-Repo\CoChem-TOPOS\topology\cochem_topos_graph.py`

## Objective
Convert 3D Cartesian coordinates into a connectivity graph to ascertain whether the input constitutes a single covalent molecule or a loosely bound van der Waals complex.

## Context & Architecture Rules
This stage manages the transition from raw 3D Cartesian coordinates into a mathematical graph topology (Stage 1.1).

## Execution Directives
Implement the `cochem_topos_graph.py` script with the following capabilities:

1. **Distance Matrix Generation**: Compute the pairwise Euclidean distance (Dij) between all atoms i and j using `scipy.spatial`.
2. **The Resonance Protection Trap**: Construct an adjacency matrix (A) derived from covalent radii (R). To prevent transition states, aromatic rings, or elongated metal-ligand bonds from being improperly classified as broken, the threshold must be mathematically scaled by a factor of 1.15x. Function logic: `Aij = 1 if Dij <= 1.15 * (Ri + Rj)`.
3. **Graph Cleavage**: Use `networkx` to evaluate the adjacency matrix for disconnected sub-graphs. 
   - If the graph is fully connected (1 sub-graph): Route the system to the standard monomer GOAT pipeline.
   - If multiple sub-graphs exist: Classify the system as a "Weak Complex", physically sever the coordinates into independent monomer seeds for isolated optimization, and explicitly flag the complex for downstream Counterpoise (CP) assembly.

Modified files content:

--- D:\__CoChem\GitHub-Repo\CoChem-TOPOS\frontend\__init__.py ---
"""CoChem-TOPOS Frontend Package."""

from frontend.cochem_topos_preflight import (
    AtomDiagnostic,
    ElementInfo,
    NuclearClash,
    PreflightReport,
    PreflightStatus,
    align_to_principal_axes,
    assess_valency_and_radicals,
    build_connectivity_matrix,
    center_coordinates,
    compute_center_of_mass,
    compute_geometric_center,
    compute_mass_weighted_coordinates,
    compute_moment_of_inertia_tensor,
    compute_total_molecular_mass,
    detect_nuclear_clashes,
    find_connected_fragments,
    get_element_info,
    get_monoisotopic_mass,
    get_monoisotopic_masses,
    normalize_element_symbol,
    sanitize_and_validate_seed,
    validate_spin_parity,
)

__all__ = [
    "AtomDiagnostic",
    "ElementInfo",
    "NuclearClash",
    "PreflightReport",
    "PreflightStatus",
    "align_to_principal_axes",
    "assess_valency_and_radicals",
    "build_connectivity_matrix",
    "center_coordinates",
    "compute_center_of_mass",
    "compute_geometric_center",
    "compute_mass_weighted_coordinates",
    "compute_moment_of_inertia_tensor",
    "compute_total_molecular_mass",
    "detect_nuclear_clashes",
    "find_connected_fragments",
    "get_element_info",
    "get_monoisotopic_mass",
    "get_monoisotopic_masses",
    "normalize_element_symbol",
    "sanitize_and_validate_seed",
    "validate_spin_parity",
]

--- D:\__CoChem\GitHub-Repo\CoChem-TOPOS\frontend\cochem_topos_preflight.py ---
"""Mathematical Cleansing & Validation Module for CoChem-TOPOS (cochem_topos_preflight.py).

Acts as the mathematical gatekeeper to sanitize raw coordinate seeds and validate physical viability
prior to consuming computational resources in ab initio and cascade pipelines.

Execution Directives:
1. Mono-Isotopic Mass Anchoring:
   - Queries `mendeleev` for exact, lowest-energy / most-abundant isotopic masses (e.g. 12C = 12.00000000 Da,
     1H = 1.00782503 Da, 16O = 15.99491462 Da, 14N = 14.00307400 Da).
   - Prevents mass-weighting drift during Eckart alignments and isotopic Hessian recycling.
   - Computes mass-weighted Cartesian coordinates, Center of Mass (COM), and Moment of Inertia principal axes.

2. Spin Parity Gatekeeping:
   - Calculates total valence electrons: Ne = SUM(Zi) - formal_charge.
   - Enforces fundamental physical parity: if Ne is odd and requested multiplicity is Singlet (2S+1 = 1)
     or any odd multiplicity, forcefully raises ValueError with comprehensive diagnostic context to halt execution.
   - Enforces multiplicity bounds: 1 <= multiplicity <= Ne + 1, and parity consistency (Ne % 2 == (multiplicity - 1) % 2).

3. Coordinate Validation & Nuclear Clash Detection:
   - Validates array shape (N, 3), checks for NaN/Inf values, finite coordinate bounding.
   - Detects nuclear clashes (interatomic distance < 0.5 A or below covalent radius threshold).
   - Performs adjacency/connectivity graph partitioning to identify disconnected molecular fragments.

4. Formal Charge & Valency Diagnostics:
   - Calculates per-atom coordination numbers using covalent radii from `mendeleev`.
   - Flags valency anomalies (hypervalent hydrogens, over-coordinated carbons, uncharged open-shell centers).
   - Produces structured diagnostic reports (`PreflightReport`, `PreflightStatus`, `AtomDiagnostic`, `NuclearClash`).
"""

from __future__ import annotations

import enum
import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, cast

import mendeleev  # type: ignore[import-untyped]
import numpy as np
import numpy.linalg as la

logger = logging.getLogger("cochem_topos_preflight")

# Standard neutral and maximum typical valencies for elements (symbol -> (standard_val, max_val))
STANDARD_VALENCE_MAP: dict[str, tuple[int, int]] = {
    "H": (1, 1),
    "D": (1, 1),
    "T": (1, 1),
    "He": (0, 0),
    "Li": (1, 1),
    "Be": (2, 2),
    "B": (3, 4),
    "C": (4, 4),
    "N": (3, 4),
    "O": (2, 3),
    "F": (1, 1),
    "Ne": (0, 0),
    "Na": (1, 1),
    "Mg": (2, 2),
    "Al": (3, 6),
    "Si": (4, 6),
    "P": (3, 6),
    "S": (2, 6),
    "Cl": (1, 7),
    "Ar": (0, 0),
    "K": (1, 1),
    "Ca": (2, 2),
    "Sc": (3, 6),
    "Ti": (4, 6),
    "V": (5, 6),
    "Cr": (6, 6),
    "Mn": (2, 7),
    "Fe": (2, 6),
    "Co": (2, 6),
    "Ni": (2, 6),
    "Cu": (2, 4),
    "Zn": (2, 4),
    "Ga": (3, 6),
    "Ge": (4, 6),
    "As": (3, 5),
    "Se": (2, 6),
    "Br": (1, 7),
    "Kr": (0, 2),
    "Rb": (1, 1),
    "Sr": (2, 2),
    "Y": (3, 6),
    "Zr": (4, 6),
    "Nb": (5, 6),
    "Mo": (6, 6),
    "Tc": (7, 7),
    "Ru": (3, 8),
    "Rh": (3, 6),
    "Pd": (2, 4),
    "Ag": (1, 4),
    "Cd": (2, 4),
    "In": (3, 6),
    "Sn": (4, 6),
    "Sb": (3, 5),
    "Te": (2, 6),
    "I": (1, 7),
    "Xe": (0, 8),
    "Cs": (1, 1),
    "Ba": (2, 2),
    "La": (3, 6),
    "Ce": (4, 6),
    "Pr": (3, 6),
    "Nd": (3, 6),
    "Sm": (3, 6),
    "Eu": (3, 6),
    "Gd": (3, 6),
    "Tb": (3, 6),
    "Dy": (3, 6),
    "Ho": (3, 6),
    "Er": (3, 6),
    "Tm": (3, 6),
    "Yb": (3, 6),
    "Lu": (3, 6),
    "Hf": (4, 6),
    "Ta": (5, 6),
    "W": (6, 6),
    "Re": (7, 7),
    "Os": (4, 8),
    "Ir": (4, 6),
    "Pt": (2, 6),
    "Au": (1, 4),
    "Hg": (2, 4),
    "Tl": (1, 3),
    "Pb": (2, 4),
    "Bi": (3, 5),
    "Po": (2, 6),
    "At": (1, 7),
    "Rn": (0, 2),
    "Fr": (1, 1),
    "Ra": (2, 2),
    "Ac": (3, 6),
    "Th": (4, 6),
    "Pa": (5, 6),
    "U": (6, 8),
    "Np": (5, 7),
    "Pu": (4, 7),
}


class PreflightStatus(str, enum.Enum):
    """Status enumeration for seed coordinate and system validation."""

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


@dataclass(frozen=True)
class ElementInfo:
    """Immutable metadata container for an elemental atom and its monoisotopic mass."""

    symbol: str
    atomic_number: int
    name: str
    monoisotopic_mass: float
    most_abundant_mass_number: int
    covalent_radius_angstrom: float
    vdw_radius_angstrom: float
    standard_valence: int
    max_valence: int
    group_id: int | None
    period: int


@dataclass
class NuclearClash:
    """Diagnostic detail for a pair of overlapping atoms violating physical distance limits."""

    atom_index_1: int
    symbol_1: str
    atom_index_2: int
    symbol_2: str
    distance_angstrom: float
    min_allowed_distance_angstrom: float
    clash_type: str = "NUCLEAR_CLASH"


@dataclass
class AtomDiagnostic:
    """Per-atom structural, connectivity, and valency assessment."""

    index: int
    symbol: str
    atomic_number: int
    monoisotopic_mass: float
    covalent_radius_angstrom: float
    coordination_number: int
    bonded_neighbors: list[int]
    standard_valence: int
    max_valence: int
    valency_anomaly: bool = False
    warnings: list[str] = field(default_factory=list)


def _make_json_serializable(obj: Any) -> Any:
    """Recursively convert numpy types, Enums, and objects to JSON serializable primitives."""
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    return obj


@dataclass
class PreflightReport:
    """Structured result generated by the mathematical gatekeeper."""

    is_valid: bool
    status: PreflightStatus
    total_atoms: int
    total_nuclear_charge: int
    total_electrons: int
    formal_charge: int
    spin_multiplicity: int
    spin_quantum_number_s: float
    num_unpaired_electrons: int
    symbols: list[str]
    atomic_numbers: list[int]
    monoisotopic_masses: list[float]
    total_monoisotopic_mass: float
    center_of_mass: list[float]
    geometric_center: list[float]
    sanitized_coordinates: list[list[float]]
    mass_weighted_coordinates: list[list[float]]
    principal_moments_of_inertia: list[float]
    num_fragments: int
    fragments: list[list[int]]
    nuclear_clashes: list[NuclearClash] = field(default_factory=list)
    atom_diagnostics: list[AtomDiagnostic] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to standard serializable dictionary."""
        data = asdict(self)
        return cast(dict[str, Any], _make_json_serializable(data))

    def to_json(self, indent: int = 2) -> str:
        """Convert report to JSON formatted string."""
        return json.dumps(self.to_dict(), indent=indent)

    def get_coordinates_numpy(self) -> np.ndarray:
        """Return sanitized coordinates as a NumPy array of shape (N, 3)."""
        return np.array(self.sanitized_coordinates, dtype=float)

    def get_mass_weighted_coordinates_numpy(self) -> np.ndarray:
        """Return mass-weighted coordinates as a NumPy array of shape (N, 3)."""
        return np.array(self.mass_weighted_coordinates, dtype=float)

    def get_center_of_mass_numpy(self) -> np.ndarray:
        """Return center of mass vector as a 1D NumPy array of shape (3,)."""
        return np.array(self.center_of_mass, dtype=float)

    def get_geometric_center_numpy(self) -> np.ndarray:
        """Return geometric centroid vector as a 1D NumPy array of shape (3,)."""
        return np.array(self.geometric_center, dtype=float)

    def get_principal_moments_numpy(self) -> np.ndarray:
        """Return principal moments of inertia as a 1D NumPy array of shape (3,)."""
        return np.array(self.principal_moments_of_inertia, dtype=float)

    def summary(self) -> str:
        """Generate human-readable multi-line diagnostic summary."""
        lines = [
            "=== CoChem-TOPOS Preflight Report ===",
            f"Status: {self.status.value} (Valid: {self.is_valid})",
            f"Composition: {self.total_atoms} atoms | Total Mass: {self.total_monoisotopic_mass:.6f} Da",
            f"Electronics: Nuclear Charge Z={self.total_nuclear_charge} | Charge={self.formal_charge:+d} | Electrons Ne={self.total_electrons}",
            f"Spin State: Multiplicity={self.spin_multiplicity} (S={self.spin_quantum_number_s:.1f}, Unpaired={self.num_unpaired_electrons})",
            f"Fragments: {self.num_fragments} connected component(s)",
            f"Nuclear Clashes: {len(self.nuclear_clashes)}",
            f"Warnings ({len(self.warnings)}):" + (" None" if not self.warnings else ""),
        ]
        for w in self.warnings:
            lines.append(f"  - [WARN] {w}")
        if self.errors:
            lines.append(f"Errors ({len(self.errors)}):")
            for e in self.errors:
                lines.append(f"  - [ERROR] {e}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mono-Isotopic Mass Anchoring & Mendeleev Resolution
# ---------------------------------------------------------------------------


def normalize_element_symbol(symbol_or_z: str | int) -> str:
    """Normalize input identifier into a canonical elemental symbol."""
    if isinstance(symbol_or_z, (int, np.integer)):
        z = int(symbol_or_z)
        if z < 1 or z > 118:
            raise ValueError(f"Atomic number Z={z} is out of physical range [1, 118].")
        el = mendeleev.element(z)
        return str(el.symbol)

    if isinstance(symbol_or_z, str):
        s = symbol_or_z.strip()
        if not s:
            raise ValueError("Empty element symbol string provided.")
        if s.isdigit():
            z = int(s)
            if z < 1 or z > 118:
                raise ValueError(f"Atomic number Z={z} is out of physical range [1, 118].")
            el = mendeleev.element(z)
            return str(el.symbol)

        # Check isotope special notations
        s_upper = s.upper()
        if s_upper in ("D", "2H"):
            return "D"
        if s_upper in ("T", "3H"):
            return "T"

        # Standard chemical symbol capitalization (e.g. 'c' -> 'C', 'fe' -> 'Fe', 'CL' -> 'Cl')
        canonical = s.capitalize()
        return canonical

    raise TypeError(f"Expected str or int for element identifier, got {type(symbol_or_z).__name__}.")


@lru_cache(maxsize=256)
def get_element_info(symbol_or_z: str | int) -> ElementInfo:
    """Query `mendeleev` to obtain immutable element metadata and exact monoisotopic mass.

    Results are cached in memory for sub-microsecond subsequent lookups.
    """
    sym = normalize_element_symbol(symbol_or_z)

    # Handle isotopic aliases (Deuterium, Tritium)
    if sym in ("D", "T"):
        el_h = mendeleev.element("H")
        mass_num = 2 if sym == "D" else 3
        iso = next((i for i in el_h.isotopes if i.mass_number == mass_num), None)
        iso_mass = (
            float(iso.mass)
            if (iso and iso.mass is not None)
            else (2.014101778 if sym == "D" else 3.016049281)
        )
        cov_rad = float(el_h.covalent_radius) / 100.0 if el_h.covalent_radius else 0.32
        vdw_rad = float(el_h.vdw_radius) / 100.0 if el_h.vdw_radius else 1.20
        return ElementInfo(
            symbol=sym,
            atomic_number=1,
            name="Deuterium" if sym == "D" else "Tritium",
            monoisotopic_mass=iso_mass,
            most_abundant_mass_number=mass_num,
            covalent_radius_angstrom=cov_rad,
            vdw_radius_angstrom=vdw_rad,
            standard_valence=1,
            max_valence=1,
            group_id=1,
            period=1,
        )

    try:
        el = mendeleev.element(sym)
    except Exception as exc:
        raise ValueError(f"Element '{sym}' not recognized by IUPAC / mendeleev database: {exc}") from exc

    # Identify exact monoisotopic mass (most abundant isotope on Earth or ground-state most stable isotope)
    abundant_isotopes = [
        iso for iso in el.isotopes if iso.abundance is not None and iso.abundance > 0
    ]
    if abundant_isotopes:
        primary_iso = max(abundant_isotopes, key=lambda x: x.abundance)
        mono_mass = float(primary_iso.mass)
        mass_num = int(primary_iso.mass_number)
    else:
        # Synthetic / radioactive element without natural abundance
        valid_isotopes = [iso for iso in el.isotopes if iso.mass is not None]
        if valid_isotopes:
            stable_iso = max(
                valid_isotopes, key=lambda x: (x.half_life if x.half_life is not None else 0)
            )
            mono_mass = float(stable_iso.mass)
            mass_num = int(stable_iso.mass_number)
        else:
            mono_mass = (
                float(el.atomic_weight) if el.atomic_weight is not None else float(el.atomic_number)
            )
            mass_num = int(round(mono_mass))

    # Covalent & VdW radii in Angstroms (mendeleev returns pm, 1 pm = 0.01 A)
    cov_rad_pm = el.covalent_radius
    vdw_rad_pm = el.vdw_radius
    cov_rad = (float(cov_rad_pm) / 100.0) if cov_rad_pm is not None else 1.20
    vdw_rad = (float(vdw_rad_pm) / 100.0) if vdw_rad_pm is not None else (cov_rad + 0.60)

    # Standard and maximum valence
    val_info = STANDARD_VALENCE_MAP.get(el.symbol, (4, 6))
    std_val, max_val = val_info

    group_id = int(el.group_id) if el.group_id is not None else None
    period = int(el.period) if el.period is not None else 1

    return ElementInfo(
        symbol=str(el.symbol),
        atomic_number=int(el.atomic_number),
        name=str(el.name),
        monoisotopic_mass=mono_mass,
        most_abundant_mass_number=mass_num,
        covalent_radius_angstrom=cov_rad,
        vdw_radius_angstrom=vdw_rad,
        standard_valence=std_val,
        max_valence=max_val,
        group_id=group_id,
        period=period,
    )


def get_monoisotopic_mass(symbol_or_z: str | int) -> float:
    """Retrieve exact monoisotopic mass in Daltons (g/mol) for an element.

    Examples:
    >>> get_monoisotopic_mass("C")
    12.0
    >>> get_monoisotopic_mass("H")
    1.00782503...
    """
    return get_element_info(symbol_or_z).monoisotopic_mass


def get_monoisotopic_masses(symbols_or_zs: Sequence[str | int]) -> np.ndarray:
    """Retrieve 1D array of exact monoisotopic masses for a sequence of elements."""
    return np.array([get_monoisotopic_mass(s) for s in symbols_or_zs], dtype=float)


def compute_total_molecular_mass(symbols_or_zs: Sequence[str | int]) -> float:
    """Calculate total monoisotopic mass of the system in Daltons."""
    return float(np.sum(get_monoisotopic_masses(symbols_or_zs)))


# ---------------------------------------------------------------------------
# Coordinate Centering, Center of Mass & Inertia Alignment
# ---------------------------------------------------------------------------


def compute_center_of_mass(
    symbols_or_zs: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
) -> np.ndarray:
    """Compute the 3D Center of Mass (COM) vector using exact monoisotopic masses.

    R_COM = (SUM_i m_i * r_i) / (SUM_i m_i)
    """
    coords = np.array(coordinates, dtype=float)
    if coords.ndim != 2 or coords.shape[1] != 3:
        raise ValueError(f"Coordinates must be 2D array of shape (N, 3), got {coords.shape}.")
    if len(symbols_or_zs) != coords.shape[0]:
        raise ValueError(
            f"Number of symbols ({len(symbols_or_zs)}) != coordinate rows ({coords.shape[0]})."
        )

    masses = get_monoisotopic_masses(symbols_or_zs)
    total_mass = float(np.sum(masses))
    if total_mass <= 0:
        raise ValueError("Total molecular mass must be strictly positive.")

    com = np.sum(coords * masses[:, np.newaxis], axis=0) / total_mass
    return cast(np.ndarray, com)


def compute_geometric_center(coordinates: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
    """Compute the unweighted geometric centroid vector."""
    coords = np.array(coordinates, dtype=float)
    if coords.ndim != 2 or coords.shape[1] != 3:
        raise ValueError(f"Coordinates must be 2D array of shape (N, 3), got {coords.shape}.")
    return cast(np.ndarray, np.mean(coords, axis=0))


def center_coordinates(
    coordinates: np.ndarray | Sequence[Sequence[float]],
    masses: np.ndarray | Sequence[float] | None = None,
) -> np.ndarray:
    """Translate coordinates to origin (Center of Mass if masses provided, else geometric centroid)."""
    coords = np.array(coordinates, dtype=float).copy()
    if masses is not None:
        m = np.array(masses, dtype=float)
        origin = np.sum(coords * m[:, np.newaxis], axis=0) / np.sum(m)
    else:
        origin = np.mean(coords, axis=0)
    return cast(np.ndarray, coords - origin)


def compute_mass_weighted_coordinates(
    symbols_or_zs: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
    center: bool = True,
) -> np.ndarray:
    """Compute mass-weighted Cartesian coordinates q_{i, alpha} = sqrt(m_i) * (r_{i, alpha} - R_COM).

    Mass-weighting anchors coordinates for Eckart frame alignments and Hessian diagonalization.
    """
    coords = np.array(coordinates, dtype=float)
    masses = get_monoisotopic_masses(symbols_or_zs)
    if center:
        coords = center_coordinates(coords, masses=masses)
    return cast(np.ndarray, coords * np.sqrt(masses[:, np.newaxis]))


def compute_moment_of_inertia_tensor(
    symbols_or_zs: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
) -> np.ndarray:
    """Compute the 3x3 Moment of Inertia tensor I_{alpha, beta} relative to Center of Mass.

    I_{alpha, beta} = SUM_i m_i * ( ||r_i||^2 * delta_{alpha, beta} - r_{i, alpha} * r_{i, beta} )
    """
    coords = np.array(coordinates, dtype=float)
    masses = get_monoisotopic_masses(symbols_or_zs)
    shifted = center_coordinates(coords, masses=masses)

    tensor = np.zeros((3, 3), dtype=float)
    for m, r in zip(masses, shifted, strict=False):
        r_sq = float(np.dot(r, r))
        tensor += m * (r_sq * np.eye(3, dtype=float) - np.outer(r, r))
    return tensor


def align_to_principal_axes(
    symbols_or_zs: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rotate molecular coordinates into the principal axes of inertia frame.

    Returns:
        (aligned_coords, principal_moments, rotation_matrix)
    where rotation_matrix is guaranteed to have det = +1 (proper rotation).
    """
    coords = np.array(coordinates, dtype=float)
    masses = get_monoisotopic_masses(symbols_or_zs)
    shifted = center_coordinates(coords, masses=masses)

    if coords.shape[0] == 1:
        # Single atom: already at origin, inertia tensor is zero
        return shifted, np.zeros(3, dtype=float), np.eye(3, dtype=float)

    inertia_tensor = compute_moment_of_inertia_tensor(symbols_or_zs, coordinates)
    eigvals, eigvecs = la.eigh(inertia_tensor)

    # Ensure right-handed coordinate system (det = +1)
    if float(la.det(eigvecs)) < 0:
        eigvecs[:, -1] *= -1.0

    aligned = shifted @ eigvecs
    return aligned, eigvals, eigvecs


# ---------------------------------------------------------------------------
# Spin Parity Gatekeeping
# ---------------------------------------------------------------------------


def validate_spin_parity(
    symbols_or_zs: Sequence[str | int],
    charge: int = 0,
    multiplicity: int = 1,
) -> tuple[int, int]:
    """Validate spin parity and physical electronic consistency.

    Calculates:
        Z_tot = SUM(Z_i)
        Ne = Z_tot - charge

    Enforces:
    1. Ne > 0 (strictly positive electron count).
    2. multiplicity >= 1 (S >= 0).
    3. Multiplicity parity: Ne % 2 == (multiplicity - 1) % 2.
       - Odd electron count Ne requires even multiplicity (Doublet=2, Quartet=4, etc.).
         A Singlet (multiplicity=1) with odd Ne is strictly physically impossible and raises ValueError.
       - Even electron count Ne requires odd multiplicity (Singlet=1, Triplet=3, etc.).
    4. Unpaired electrons 2S <= Ne.

    Returns:
        (total_nuclear_charge, total_electrons)

    Raises:
        ValueError: On any physical impossibility or parity violation.
    """
    if not isinstance(charge, (int, np.integer)):
        raise TypeError(f"Charge must be an integer, got {type(charge).__name__}.")
    if not isinstance(multiplicity, (int, np.integer)):
        raise TypeError(f"Multiplicity must be an integer, got {type(multiplicity).__name__}.")

    charge = int(charge)
    multiplicity = int(multiplicity)

    if not symbols_or_zs:
        raise ValueError("Cannot validate spin parity for an empty system (0 atoms).")

    atomic_numbers = [get_element_info(s).atomic_number for s in symbols_or_zs]
    z_tot = sum(atomic_numbers)
    ne = z_tot - charge

    if ne <= 0:
        raise ValueError(
            f"Physical impossibility: Total nuclear charge Z_tot={z_tot} and formal charge {charge:+d} "
            f"yield Ne={ne} electrons. A quantum mechanical system must have at least 1 electron."
        )

    if multiplicity < 1:
        raise ValueError(f"Invalid spin multiplicity {multiplicity}. Multiplicity (2S+1) must be >= 1.")

    num_unpaired = multiplicity - 1
    if num_unpaired > ne:
        raise ValueError(
            f"Physical impossibility: Multiplicity {multiplicity} requires {num_unpaired} unpaired electrons, "
            f"which exceeds total electron count Ne={ne}."
        )

    # Parity check
    ne_is_odd = ne % 2 != 0
    mult_is_odd = multiplicity % 2 != 0

    if ne_is_odd and mult_is_odd:
        # Odd electrons with Singlet (mult=1), Triplet (mult=3), etc.
        if multiplicity == 1:
            raise ValueError(
                f"Spin parity violation: System has {ne} electrons (odd count: Z_tot={z_tot}, charge={charge:+d}), "
                f"which cannot form a Singlet (multiplicity 1). An odd-electron open-shell radical requires an even "
                f"multiplicity (e.g. Doublet=2, Quartet=4). Impossible SCF calculation halted."
            )
        raise ValueError(
            f"Spin parity violation: System has {ne} electrons (odd count), but requested multiplicity is "
            f"{multiplicity} (odd). Odd-electron systems require an even multiplicity (e.g. Doublet=2, Quartet=4)."
        )

    if (not ne_is_odd) and (not mult_is_odd):
        # Even electrons with Doublet (mult=2), Quartet (mult=4), etc.
        raise ValueError(
            f"Spin parity violation: System has {ne} electrons (even count: Z_tot={z_tot}, charge={charge:+d}), "
            f"which cannot form an even multiplicity {multiplicity} (e.g. Doublet/Quartet). Even-electron systems "
            f"require an odd multiplicity (e.g. Singlet=1, Triplet=3)."
        )

    return z_tot, ne


# ---------------------------------------------------------------------------
# Coordinate Validation, Nuclear Clash & Connectivity Graph
# ---------------------------------------------------------------------------


def detect_nuclear_clashes(
    coordinates: np.ndarray | Sequence[Sequence[float]],
    symbols_or_zs: Sequence[str | int] | None = None,
    min_distance_angstrom: float = 0.5,
    covalent_ratio_threshold: float = 0.4,
) -> list[NuclearClash]:
    """Detect nuclear clashes where interatomic distances violate physical limits.

    A clash is identified if interatomic distance d_{ij} < min_distance_angstrom OR
    d_{ij} < covalent_ratio_threshold * (r_cov_i + r_cov_j).
    """
    coords = np.array(coordinates, dtype=float)
    n_atoms = coords.shape[0]
    if n_atoms < 2:
        return []

    cov_radii: list[float] = []
    symbols: list[str] = []
    if symbols_or_zs is not None:
        for s in symbols_or_zs:
            info = get_element_info(s)
            cov_radii.append(info.covalent_radius_angstrom)
            symbols.append(info.symbol)
    else:
        cov_radii = [0.75] * n_atoms
        symbols = [f"X{i}" for i in range(n_atoms)]

    clashes: list[NuclearClash] = []
    for i in range(n_atoms):
        for j in range(i + 1, n_atoms):
            dist = float(la.norm(coords[i] - coords[j]))
            r_sum = cov_radii[i] + cov_radii[j]
            allowed_threshold = max(min_distance_angstrom, covalent_ratio_threshold * r_sum)

            if dist < allowed_threshold:
                clashes.append(
                    NuclearClash(
                        atom_index_1=i,
                        symbol_1=symbols[i],
                        atom_index_2=j,
                        symbol_2=symbols[j],
                        distance_angstrom=dist,
                        min_allowed_distance_angstrom=allowed_threshold,
                        clash_type=(
                            "SUB_COVALENT_OVERLAP"
                            if dist < min_distance_angstrom
                            else "COVALENT_COLLAPSE"
                        ),
                    )
                )

    return clashes


def build_connectivity_matrix(
    symbols_or_zs: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
    tolerance_factor: float = 1.3,
) -> np.ndarray:
    """Build a boolean adjacency matrix based on covalent radius cutoffs.

    Two atoms i and j are connected if d_{ij} <= tolerance_factor * (r_cov_i + r_cov_j).
    """
    coords = np.array(coordinates, dtype=float)
    n_atoms = coords.shape[0]
    cov_radii = [get_element_info(s).covalent_radius_angstrom for s in symbols_or_zs]

    adj_matrix = np.zeros((n_atoms, n_atoms), dtype=bool)
    for i in range(n_atoms):
        for j in range(i + 1, n_atoms):
            dist = float(la.norm(coords[i] - coords[j]))
            cutoff = tolerance_factor * (cov_radii[i] + cov_radii[j])
            if dist <= cutoff:
                adj_matrix[i, j] = True
                adj_matrix[j, i] = True

    return adj_matrix


def find_connected_fragments(adjacency_matrix: np.ndarray) -> list[list[int]]:
    """Identify connected molecular components (fragments) using breadth-first search."""
    n_atoms = adjacency_matrix.shape[0]
    visited = set()
    fragments: list[list[int]] = []

    for start_node in range(n_atoms):
        if start_node in visited:
            continue
        fragment: list[int] = []
        queue = [start_node]
        visited.add(start_node)

        while queue:
            node = queue.pop(0)
            fragment.append(node)
            neighbors = np.where(adjacency_matrix[node])[0]
            for neighbor in neighbors:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(int(neighbor))

        fragments.append(sorted(fragment))

    return fragments


# ---------------------------------------------------------------------------
# Valency & Radical Diagnostic Assessment
# ---------------------------------------------------------------------------


def assess_valency_and_radicals(
    symbols_or_zs: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
    charge: int = 0,
    multiplicity: int = 1,
    tolerance_factor: float = 1.3,
) -> list[AtomDiagnostic]:
    """Perform structural valency, coordination, and radical center analysis.

    Evaluates each atom against its expected coordination bounds and flags hypervalency
    or uncharged radical/ionic states.
    """
    coords = np.array(coordinates, dtype=float)
    n_atoms = coords.shape[0]
    adj_matrix = build_connectivity_matrix(
        symbols_or_zs, coords, tolerance_factor=tolerance_factor
    )

    diagnostics: list[AtomDiagnostic] = []
    for i in range(n_atoms):
        info = get_element_info(symbols_or_zs[i])
        neighbors = [int(j) for j in np.where(adj_matrix[i])[0]]
        coord_num = len(neighbors)
        warnings: list[str] = []
        valency_anomaly = False

        # Check hypervalency
        if coord_num > info.max_valence:
            valency_anomaly = True
            if info.symbol in ("H", "D", "T") and coord_num > 1:
                warnings.append(
                    f"Hypervalent hydrogen at atom {i} ({info.symbol}): coordination {coord_num} > max 1. "
                    f"Connected to atoms {neighbors}."
                )
            elif info.symbol == "C" and coord_num > 4:
                warnings.append(
                    f"Hypervalent carbon at atom {i} ({info.symbol}): coordination {coord_num} > max 4."
                )
            else:
                warnings.append(
                    f"Hypervalent {info.name} at atom {i} ({info.symbol}): coordination {coord_num} > max {info.max_valence}."
                )

        # Main-group uncharged radical / valency checks
        if info.symbol == "C" and coord_num == 3 and charge == 0 and multiplicity == 1:
            warnings.append(
                f"Trivalent carbon at atom {i} with formal charge 0 in singlet state implies uncharged radical center."
            )
        elif info.symbol == "O" and coord_num == 1 and charge == 0 and multiplicity == 1:
            warnings.append(
                f"Monovalent oxygen at atom {i} with formal charge 0 in singlet state implies oxy radical."
            )

        diagnostics.append(
            AtomDiagnostic(
                index=i,
                symbol=info.symbol,
                atomic_number=info.atomic_number,
                monoisotopic_mass=info.monoisotopic_mass,
                covalent_radius_angstrom=info.covalent_radius_angstrom,
                coordination_number=coord_num,
                bonded_neighbors=neighbors,
                standard_valence=info.standard_valence,
                max_valence=info.max_valence,
                valency_anomaly=valency_anomaly,
                warnings=warnings,
            )
        )

    return diagnostics


# ---------------------------------------------------------------------------
# Master Sanitization & Validation Gatekeeper Entrypoint
# ---------------------------------------------------------------------------


def sanitize_and_validate_seed(
    symbols_or_zs: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
    charge: int = 0,
    multiplicity: int = 1,
    strict: bool = True,
    center_on_com: bool = True,
    align_principal_axes_flag: bool = False,
    clash_threshold_angstrom: float = 0.5,
    covalent_ratio_threshold: float = 0.4,
    tolerance_factor: float = 1.3,
) -> PreflightReport:
    """Master mathematical gatekeeper to sanitize and validate input coordinate seeds.

    Parameters:
        symbols_or_zs: Elemental symbols (e.g. ['C', 'H', 'H', 'H', 'H']) or atomic numbers.
        coordinates: Cartesian coordinates array of shape (N, 3) in Angstroms.
        charge: Formal charge (default 0).
        multiplicity: Spin multiplicity 2S+1 (default 1).
        strict: If True, raises ValueError on spin parity violation, invalid dimensions, NaN/Inf, or clashes.
        center_on_com: If True, translates coordinates to Center of Mass.
        align_principal_axes_flag: If True, rotates coordinates into inertia principal axes.
        clash_threshold_angstrom: Minimum allowed interatomic distance in Angstroms (default 0.5 A).
        covalent_ratio_threshold: Minimum allowed distance as fraction of covalent radius sum (default 0.4).
        tolerance_factor: Scaling factor for covalent radius connectivity (default 1.3).

    Returns:
        PreflightReport: Comprehensive structured diagnostic report.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Validate symbols
    if not symbols_or_zs:
        msg = "Empty system provided: symbols sequence contains 0 elements."
        if strict:
            raise ValueError(msg)
        errors.append(msg)
        return PreflightReport(
            is_valid=False,
            status=PreflightStatus.FAIL,
            total_atoms=0,
            total_nuclear_charge=0,
            total_electrons=0,
            formal_charge=int(charge),
            spin_multiplicity=int(multiplicity),
            spin_quantum_number_s=float(multiplicity - 1) / 2.0,
            num_unpaired_electrons=max(0, multiplicity - 1),
            symbols=[],
            atomic_numbers=[],
            monoisotopic_masses=[],
            total_monoisotopic_mass=0.0,
            center_of_mass=[0.0, 0.0, 0.0],
            geometric_center=[0.0, 0.0, 0.0],
            sanitized_coordinates=[],
            mass_weighted_coordinates=[],
            principal_moments_of_inertia=[0.0, 0.0, 0.0],
            num_fragments=0,
            fragments=[],
            errors=errors,
        )

    element_infos: list[ElementInfo] = []
    for idx, s in enumerate(symbols_or_zs):
        try:
            info = get_element_info(s)
            element_infos.append(info)
        except Exception as exc:
            msg = f"Invalid element identifier at index {idx} ({s}): {exc}"
            if strict:
                raise ValueError(msg) from exc
            errors.append(msg)

    # 2. Validate coordinates array
    try:
        coords_arr = np.array(coordinates, dtype=float)
    except Exception as exc:
        msg = f"Failed to convert coordinates to float64 numpy array: {exc}"
        if strict:
            raise ValueError(msg) from exc
        errors.append(msg)
        coords_arr = np.zeros((len(symbols_or_zs), 3), dtype=float)

    if coords_arr.ndim != 2 or coords_arr.shape[1] != 3:
        msg = f"Coordinates must be a 2D array of shape (N, 3), got shape {coords_arr.shape}."
        if strict:
            raise ValueError(msg)
        errors.append(msg)

    if coords_arr.shape[0] != len(symbols_or_zs):
        msg = f"Mismatch: {len(symbols_or_zs)} symbols provided but coordinate array has {coords_arr.shape[0]} rows."
        if strict:
            raise ValueError(msg)
        errors.append(msg)

    if not np.all(np.isfinite(coords_arr)):
        msg = "Coordinates array contains NaN, +Inf, or -Inf values."
        if strict:
            raise ValueError(msg)
        errors.append(msg)

    # 3. Spin Parity Gatekeeping
    z_tot = 0
    ne = 0
    try:
        z_tot, ne = validate_spin_parity(symbols_or_zs, charge=charge, multiplicity=multiplicity)
    except ValueError as exc:
        if strict:
            raise
        errors.append(str(exc))
        z_tot = sum(info.atomic_number for info in element_infos) if element_infos else 0
        ne = z_tot - int(charge)

    s_quantum = float(multiplicity - 1) / 2.0
    num_unpaired = max(0, multiplicity - 1)

    symbols_list = [info.symbol for info in element_infos]
    atomic_numbers_list = [info.atomic_number for info in element_infos]
    monoisotopic_masses_list = [info.monoisotopic_mass for info in element_infos]
    total_mass = sum(monoisotopic_masses_list) if monoisotopic_masses_list else 0.0

    # 4. Nuclear Clash Detection
    clashes = detect_nuclear_clashes(
        coords_arr,
        symbols_or_zs=symbols_list,
        min_distance_angstrom=clash_threshold_angstrom,
        covalent_ratio_threshold=covalent_ratio_threshold,
    )
    if clashes:
        clash_summary = ", ".join(
            [
                f"{c.symbol_1}({c.atom_index_1})-{c.symbol_2}({c.atom_index_2}) d={c.distance_angstrom:.3f}A"
                for c in clashes
            ]
        )
        msg = f"Nuclear clashes detected ({len(clashes)} pair(s)): {clash_summary}"
        if strict:
            raise ValueError(f"Physical impossibility: {msg}")
        errors.append(msg)

    # 5. Connectivity & Fragment Analysis
    adj_matrix = build_connectivity_matrix(
        symbols_list, coords_arr, tolerance_factor=tolerance_factor
    )
    fragments = find_connected_fragments(adj_matrix)
    num_fragments = len(fragments)
    if num_fragments > 1:
        warnings.append(
            f"System contains {num_fragments} disconnected fragments (Fragment partitions: {fragments})."
        )

    # 6. Valency & Radical Assessment
    atom_diagnostics = assess_valency_and_radicals(
        symbols_list,
        coords_arr,
        charge=charge,
        multiplicity=multiplicity,
        tolerance_factor=tolerance_factor,
    )
    for diag in atom_diagnostics:
        warnings.extend(diag.warnings)

    # 7. Coordinate Centering & Inertia Alignment
    sanitized_coords = coords_arr.copy()
    if center_on_com and total_mass > 0 and len(sanitized_coords) == len(monoisotopic_masses_list):
        sanitized_coords = center_coordinates(
            sanitized_coords, masses=np.array(monoisotopic_masses_list)
        )

    principal_moments = [0.0, 0.0, 0.0]
    if align_principal_axes_flag and len(sanitized_coords) == len(monoisotopic_masses_list):
        sanitized_coords, moments, _ = align_to_principal_axes(symbols_list, sanitized_coords)
        principal_moments = [float(x) for x in moments]
    elif len(sanitized_coords) == len(monoisotopic_masses_list) and sanitized_coords.shape[0] > 1:
        try:
            inertia_tensor = compute_moment_of_inertia_tensor(symbols_list, sanitized_coords)
            evals, _ = la.eigh(inertia_tensor)
            principal_moments = [float(x) for x in evals]
        except Exception:
            principal_moments = [0.0, 0.0, 0.0]

    # Centers
    if total_mass > 0 and len(coords_arr) == len(monoisotopic_masses_list):
        com_vec = compute_center_of_mass(symbols_list, coords_arr)
    else:
        com_vec = np.zeros(3, dtype=float)

    geom_center_vec = (
        compute_geometric_center(coords_arr)
        if coords_arr.ndim == 2 and coords_arr.shape[1] == 3
        else np.zeros(3, dtype=float)
    )

    # Mass-weighted coords
    if total_mass > 0 and len(sanitized_coords) == len(monoisotopic_masses_list):
        mw_coords = sanitized_coords * np.sqrt(np.array(monoisotopic_masses_list)[:, np.newaxis])
    else:
        mw_coords = sanitized_coords.copy()

    # Determine status
    if errors:
        status = PreflightStatus.FAIL
        is_valid = False
    elif warnings:
        status = PreflightStatus.WARNING
        is_valid = True
    else:
        status = PreflightStatus.PASS
        is_valid = True

    coords_2d = cast(np.ndarray, np.atleast_2d(sanitized_coords))
    mw_coords_2d = cast(np.ndarray, np.atleast_2d(mw_coords))

    return PreflightReport(
        is_valid=is_valid,
        status=status,
        total_atoms=len(symbols_list),
        total_nuclear_charge=z_tot,
        total_electrons=ne,
        formal_charge=int(charge),
        spin_multiplicity=int(multiplicity),
        spin_quantum_number_s=s_quantum,
        num_unpaired_electrons=num_unpaired,
        symbols=symbols_list,
        atomic_numbers=atomic_numbers_list,
        monoisotopic_masses=monoisotopic_masses_list,
        total_monoisotopic_mass=total_mass,
        center_of_mass=[float(x) for x in com_vec],
        geometric_center=[float(x) for x in geom_center_vec],
        sanitized_coordinates=[[float(x) for x in row] for row in coords_2d],
        mass_weighted_coordinates=[[float(x) for x in row] for row in mw_coords_2d],
        principal_moments_of_inertia=principal_moments,
        num_fragments=num_fragments,
        fragments=fragments,
        nuclear_clashes=clashes,
        atom_diagnostics=atom_diagnostics,
        warnings=warnings,
        errors=errors,
        metadata={
            "strict": strict,
            "center_on_com": center_on_com,
            "align_principal_axes": align_principal_axes_flag,
            "clash_threshold_angstrom": clash_threshold_angstrom,
        },
    )

--- D:\__CoChem\GitHub-Repo\CoChem-TOPOS\tests\test_cochem_topos_preflight.py ---
"""Physical Unit Tests for CoChem-TOPOS Preflight Module (test_cochem_topos_preflight.py).

Enforces Zero-Tolerance Anti-Mocking:
- Real elemental monoisotopic mass resolutions via `mendeleev`.
- Real physical molecules (H2O, CH4, C6H6, OH, CH3, NO, O2, NH4+, OH-, etc.).
- Real Cartesian coordinate matrices and inertia tensor calculations.
"""

from __future__ import annotations

import json
import math

import numpy as np
import numpy.linalg as la
import pytest

from frontend.cochem_topos_preflight import (
    PreflightStatus,
    align_to_principal_axes,
    assess_valency_and_radicals,
    build_connectivity_matrix,
    center_coordinates,
    compute_center_of_mass,
    compute_geometric_center,
    compute_mass_weighted_coordinates,
    compute_moment_of_inertia_tensor,
    compute_total_molecular_mass,
    detect_nuclear_clashes,
    find_connected_fragments,
    get_element_info,
    get_monoisotopic_mass,
    get_monoisotopic_masses,
    normalize_element_symbol,
    sanitize_and_validate_seed,
    validate_spin_parity,
)

# ===========================================================================
# 1. Mono-Isotopic Mass Anchoring & Mendeleev Resolution Tests
# ===========================================================================


class TestMonoisotopicMassAnchoring:
    """Test exact IUPAC/NIST monoisotopic mass resolutions with real elements."""

    def test_carbon_12_exact_mass(self) -> None:
        """Carbon-12 must be exactly 12.000000000 Da by IUPAC definition."""
        c_mass = get_monoisotopic_mass("C")
        assert math.isclose(c_mass, 12.0, rel_tol=1e-12, abs_tol=1e-12)

        info_c = get_element_info("C")
        assert info_c.symbol == "C"
        assert info_c.atomic_number == 6
        assert info_c.most_abundant_mass_number == 12
        assert math.isclose(info_c.monoisotopic_mass, 12.0, abs_tol=1e-12)

    def test_common_element_monoisotopic_masses(self) -> None:
        """Verify exact monoisotopic masses for standard organic/inorganic elements."""
        # Hydrogen (1H = ~1.007825 Da)
        h_mass = get_monoisotopic_mass("H")
        assert 1.0078 < h_mass < 1.0079

        # Nitrogen (14N = ~14.003074 Da)
        n_mass = get_monoisotopic_mass("N")
        assert 14.0030 < n_mass < 14.0032

        # Oxygen (16O = ~15.994915 Da)
        o_mass = get_monoisotopic_mass("O")
        assert 15.9948 < o_mass < 15.9950

        # Fluorine (19F = ~18.998403 Da)
        f_mass = get_monoisotopic_mass("F")
        assert 18.9983 < f_mass < 18.9985

        # Chlorine (35Cl = ~34.968853 Da)
        cl_mass = get_monoisotopic_mass("Cl")
        assert 34.968 < cl_mass < 34.970

        # Bromine (79Br = ~78.918338 Da)
        br_mass = get_monoisotopic_mass("Br")
        assert 78.918 < br_mass < 78.920

        # Iodine (127I = ~126.904473 Da)
        i_mass = get_monoisotopic_mass("I")
        assert 126.90 < i_mass < 126.91

    def test_hydrogen_isotopic_aliases(self) -> None:
        """Deuterium (D/2H) and Tritium (T/3H) must resolve exact isotopic masses."""
        d_mass = get_monoisotopic_mass("D")
        h2_mass = get_monoisotopic_mass("2H")
        assert math.isclose(d_mass, h2_mass, rel_tol=1e-6)
        assert 2.014 < d_mass < 2.015

        t_mass = get_monoisotopic_mass("T")
        h3_mass = get_monoisotopic_mass("3H")
        assert math.isclose(t_mass, h3_mass, rel_tol=1e-6)
        assert 3.015 < t_mass < 3.017

    def test_symbol_normalization_and_atomic_numbers(self) -> None:
        """Test symbol normalization (case insensitivity, atomic numbers)."""
        assert normalize_element_symbol("c") == "C"
        assert normalize_element_symbol("FE") == "Fe"
        assert normalize_element_symbol("cl") == "Cl"
        assert normalize_element_symbol(6) == "C"
        assert normalize_element_symbol("6") == "C"
        assert normalize_element_symbol(1) == "H"
        assert normalize_element_symbol(8) == "O"

        with pytest.raises(ValueError, match="Atomic number Z=0 is out of physical range"):
            normalize_element_symbol(0)

        with pytest.raises(ValueError, match="Atomic number Z=150 is out of physical range"):
            normalize_element_symbol(150)

        with pytest.raises(ValueError, match="Empty element symbol"):
            normalize_element_symbol("   ")

    def test_molecular_mass_vector_and_total(self) -> None:
        """Test monoisotopic mass array and total molecular mass computation."""
        # Water H2O
        water_symbols = ["O", "H", "H"]
        masses = get_monoisotopic_masses(water_symbols)
        assert len(masses) == 3
        total_h2o = compute_total_molecular_mass(water_symbols)
        expected_h2o = get_monoisotopic_mass("O") + 2 * get_monoisotopic_mass("H")
        assert math.isclose(total_h2o, expected_h2o, rel_tol=1e-9)
        assert 18.010 < total_h2o < 18.011

        # Chloroform CHCl3
        chcl3_symbols = ["C", "H", "Cl", "Cl", "Cl"]
        total_chcl3 = compute_total_molecular_mass(chcl3_symbols)
        expected_chcl3 = 12.0 + get_monoisotopic_mass("H") + 3 * get_monoisotopic_mass("Cl")
        assert math.isclose(total_chcl3, expected_chcl3, rel_tol=1e-9)


# ===========================================================================
# 2. Spin Parity Gatekeeping Tests
# ===========================================================================


class TestSpinParityGatekeeping:
    """Test strict quantum mechanical electron and spin parity enforcement."""

    def test_neutral_closed_shell_singlets_pass(self) -> None:
        """Even electron count systems with Singlet multiplicity must pass."""
        # Water H2O: Z = 8 + 1 + 1 = 10 e-
        z_tot, ne = validate_spin_parity(["O", "H", "H"], charge=0, multiplicity=1)
        assert z_tot == 10
        assert ne == 10

        # Methane CH4: Z = 6 + 4*1 = 10 e-
        z_tot, ne = validate_spin_parity(["C", "H", "H", "H", "H"], charge=0, multiplicity=1)
        assert z_tot == 10
        assert ne == 10

        # Nitrogen N2: Z = 7 + 7 = 14 e-
        z_tot, ne = validate_spin_parity(["N", "N"], charge=0, multiplicity=1)
        assert z_tot == 14
        assert ne == 14

        # Benzene C6H6: Z = 6*6 + 6*1 = 42 e-
        z_tot, ne = validate_spin_parity(["C"] * 6 + ["H"] * 6, charge=0, multiplicity=1)
        assert z_tot == 42
        assert ne == 42

    def test_neutral_open_shell_triplet_passes(self) -> None:
        """Triplet ground-state oxygen O2 (16 e-, mult=3) must pass."""
        z_tot, ne = validate_spin_parity(["O", "O"], charge=0, multiplicity=3)
        assert z_tot == 16
        assert ne == 16

    def test_odd_electron_singlet_raises_value_error(self) -> None:
        """Odd electron count with Singlet multiplicity (mult=1) MUST raise ValueError."""
        # Neutral methyl radical CH3: Z = 6 + 3 = 9 e-
        with pytest.raises(
            ValueError, match=r"Spin parity violation.*9 electrons.*cannot form a Singlet"
        ):
            validate_spin_parity(["C", "H", "H", "H"], charge=0, multiplicity=1)

        # Hydroxyl radical OH: Z = 8 + 1 = 9 e-
        with pytest.raises(
            ValueError, match=r"Spin parity violation.*9 electrons.*cannot form a Singlet"
        ):
            validate_spin_parity(["O", "H"], charge=0, multiplicity=1)

        # Nitric oxide NO: Z = 7 + 8 = 15 e-
        with pytest.raises(
            ValueError, match=r"Spin parity violation.*15 electrons.*cannot form a Singlet"
        ):
            validate_spin_parity(["N", "O"], charge=0, multiplicity=1)

        # Methoxy radical CH3O: Z = 6 + 3 + 8 = 17 e-
        with pytest.raises(
            ValueError, match=r"Spin parity violation.*17 electrons.*cannot form a Singlet"
        ):
            validate_spin_parity(["C", "H", "H", "H", "O"], charge=0, multiplicity=1)

    def test_odd_electron_radicals_with_doublet_pass(self) -> None:
        """Odd electron radicals with Doublet multiplicity (mult=2) must pass."""
        # Methyl radical CH3: 9 e-, mult=2 (Doublet)
        z_tot, ne = validate_spin_parity(["C", "H", "H", "H"], charge=0, multiplicity=2)
        assert z_tot == 9
        assert ne == 9

        # Hydroxyl radical OH: 9 e-, mult=2
        z_tot, ne = validate_spin_parity(["O", "H"], charge=0, multiplicity=2)
        assert z_tot == 9
        assert ne == 9

        # Nitric oxide NO: 15 e-, mult=2
        z_tot, ne = validate_spin_parity(["N", "O"], charge=0, multiplicity=2)
        assert z_tot == 15
        assert ne == 15

    def test_even_electron_system_with_doublet_raises_value_error(self) -> None:
        """Even electron count with even multiplicity (e.g. Doublet mult=2) MUST raise ValueError."""
        # Water H2O (10 e-) with mult=2
        with pytest.raises(
            ValueError,
            match=r"Spin parity violation.*10 electrons.*cannot form an even multiplicity 2",
        ):
            validate_spin_parity(["O", "H", "H"], charge=0, multiplicity=2)

    def test_charged_ions_spin_parity(self) -> None:
        """Test ionic species (cations, anions) with formal charges."""
        # Hydroxide anion OH-: Z = 9, Charge = -1 => Ne = 10 (Singlet passes)
        z_tot, ne = validate_spin_parity(["O", "H"], charge=-1, multiplicity=1)
        assert z_tot == 9
        assert ne == 10

        # Ammonium cation NH4+: Z = 11, Charge = +1 => Ne = 10 (Singlet passes)
        z_tot, ne = validate_spin_parity(["N", "H", "H", "H", "H"], charge=1, multiplicity=1)
        assert z_tot == 11
        assert ne == 10

        # Methyl cation CH3+: Z = 9, Charge = +1 => Ne = 8 (Singlet passes)
        z_tot, ne = validate_spin_parity(["C", "H", "H", "H"], charge=1, multiplicity=1)
        assert z_tot == 9
        assert ne == 8

        # Methyl anion CH3-: Z = 9, Charge = -1 => Ne = 10 (Singlet passes)
        z_tot, ne = validate_spin_parity(["C", "H", "H", "H"], charge=-1, multiplicity=1)
        assert z_tot == 9
        assert ne == 10

    def test_impossible_electron_and_multiplicity_bounds(self) -> None:
        """Test edge cases: negative electrons, multiplicity < 1, or 2S > Ne."""
        # 0 or negative electrons (e.g. H+ with charge +2)
        with pytest.raises(ValueError, match=r"Physical impossibility.*yield Ne=-1"):
            validate_spin_parity(["H"], charge=2, multiplicity=1)

        # Multiplicity < 1
        with pytest.raises(ValueError, match=r"Invalid spin multiplicity 0"):
            validate_spin_parity(["H", "H"], charge=0, multiplicity=0)

        # Unpaired electrons exceed total electrons (e.g. H2 with 2 e-, mult=5 requires 4 unpaired e-)
        with pytest.raises(
            ValueError,
            match=r"Physical impossibility.*requires 4 unpaired electrons.*exceeds total electron count Ne=2",
        ):
            validate_spin_parity(["H", "H"], charge=0, multiplicity=5)


# ===========================================================================
# 3. Coordinate Centering, Center of Mass & Inertia Alignment Tests
# ===========================================================================


class TestCoordinatesAndEckartGeometry:
    """Test Center of Mass, Centroid, and Inertia alignment transformations."""

    @pytest.fixture
    def water_geometry(self) -> tuple[list[str], np.ndarray]:
        """Return real C2v water geometry in Angstroms."""
        symbols = ["O", "H", "H"]
        coords = np.array(
            [
                [0.000000, 0.000000, 0.117300],
                [0.000000, 0.757200, -0.469200],
                [0.000000, -0.757200, -0.469200],
            ],
            dtype=np.float64,
        )
        return symbols, coords

    def test_center_of_mass_calculation(self, water_geometry: tuple[list[str], np.ndarray]) -> None:
        """Center of mass for C2v water must be heavily shifted towards the oxygen atom."""
        symbols, coords = water_geometry
        com = compute_center_of_mass(symbols, coords)
        assert com.shape == (3,)
        # In x and y it must be 0 by symmetry
        assert math.isclose(com[0], 0.0, abs_tol=1e-6)
        assert math.isclose(com[1], 0.0, abs_tol=1e-6)
        # In z it is close to oxygen z (0.1173)
        assert 0.04 < com[2] < 0.06

    def test_geometric_centroid(self, water_geometry: tuple[list[str], np.ndarray]) -> None:
        """Geometric centroid is unweighted arithmetic mean."""
        symbols, coords = water_geometry
        centroid = compute_geometric_center(coords)
        expected = np.mean(coords, axis=0)
        np.testing.assert_allclose(centroid, expected, atol=1e-9)

    def test_center_coordinates(self, water_geometry: tuple[list[str], np.ndarray]) -> None:
        """Centering coordinates sets new COM to (0,0,0)."""
        symbols, coords = water_geometry
        masses = get_monoisotopic_masses(symbols)
        centered = center_coordinates(coords, masses=masses)
        new_com = compute_center_of_mass(symbols, centered)
        np.testing.assert_allclose(new_com, np.zeros(3), atol=1e-9)

    def test_mass_weighted_coordinates(self, water_geometry: tuple[list[str], np.ndarray]) -> None:
        """Mass weighted coordinates scale as sqrt(m_i)."""
        symbols, coords = water_geometry
        masses = get_monoisotopic_masses(symbols)
        mw_coords = compute_mass_weighted_coordinates(symbols, coords, center=True)
        assert mw_coords.shape == (3, 3)
        # Check that norm of oxygen mass-weighted row is scaled by sqrt(15.9949)
        centered = center_coordinates(coords, masses=masses)
        np.testing.assert_allclose(mw_coords[0], centered[0] * math.sqrt(masses[0]), atol=1e-9)
        np.testing.assert_allclose(mw_coords[1], centered[1] * math.sqrt(masses[1]), atol=1e-9)

    def test_inertia_tensor_and_principal_alignment(
        self, water_geometry: tuple[list[str], np.ndarray]
    ) -> None:
        """Principal axis alignment must diagonalize the inertia tensor and maintain det(R) = +1."""
        symbols, coords = water_geometry
        aligned_coords, moments, rot_matrix = align_to_principal_axes(symbols, coords)

        # Check proper rotation
        det = float(la.det(rot_matrix))
        assert math.isclose(det, 1.0, rel_tol=1e-7, abs_tol=1e-7)

        # Check that principal moments are strictly positive and ascending
        assert len(moments) == 3
        assert moments[0] > 0
        assert moments[1] >= moments[0]
        assert moments[2] >= moments[1]

        # Recomputed inertia tensor of aligned coords must be diagonal
        aligned_tensor = compute_moment_of_inertia_tensor(symbols, aligned_coords)
        off_diagonals = aligned_tensor - np.diag(np.diag(aligned_tensor))
        np.testing.assert_allclose(off_diagonals, np.zeros((3, 3)), atol=1e-6)


# ===========================================================================
# 4. Nuclear Clash & Coordinate Validation Tests
# ===========================================================================


class TestNuclearClashesAndCoordinateSanity:
    """Test detection of unphysical overlaps and invalid array shapes / values."""

    def test_clean_molecule_has_no_clashes(self) -> None:
        """Equilibrium methane must have zero nuclear clashes."""
        symbols = ["C", "H", "H", "H", "H"]
        # Tetrahedral methane
        d = 1.089 / math.sqrt(3)
        coords = np.array(
            [
                [0.0, 0.0, 0.0],
                [d, d, d],
                [d, -d, -d],
                [-d, d, -d],
                [-d, -d, d],
            ]
        )
        clashes = detect_nuclear_clashes(coords, symbols_or_zs=symbols, min_distance_angstrom=0.5)
        assert len(clashes) == 0

    def test_overlapping_atoms_trigger_clash_detection(self) -> None:
        """Two atoms placed 0.2 A apart must trigger nuclear clash detection."""
        symbols = ["C", "C"]
        coords = np.array(
            [
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.2],  # Extreme clash (0.2 A vs typical C-C 1.54 A)
            ]
        )
        clashes = detect_nuclear_clashes(coords, symbols_or_zs=symbols, min_distance_angstrom=0.5)
        assert len(clashes) == 1
        clash = clashes[0]
        assert clash.atom_index_1 == 0
        assert clash.atom_index_2 == 1
        assert math.isclose(clash.distance_angstrom, 0.2, abs_tol=1e-6)

    def test_strict_mode_raises_on_clash(self) -> None:
        """sanitize_and_validate_seed in strict mode must raise ValueError on clashes."""
        symbols = ["O", "H", "H"]
        clashing_coords = np.array(
            [
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.1],  # Overlap
                [0.0, 0.8, 0.0],
            ]
        )
        with pytest.raises(ValueError, match="Physical impossibility: Nuclear clashes detected"):
            sanitize_and_validate_seed(symbols, clashing_coords, strict=True)

    def test_non_strict_mode_records_clash_in_report(self) -> None:
        """sanitize_and_validate_seed in non-strict mode records clash without crashing."""
        symbols = ["O", "H", "H"]
        clashing_coords = np.array(
            [
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.1],
                [0.0, 0.8, 0.0],
            ]
        )
        report = sanitize_and_validate_seed(symbols, clashing_coords, strict=False)
        assert report.status == PreflightStatus.FAIL
        assert not report.is_valid
        assert len(report.nuclear_clashes) >= 1
        assert any("Nuclear clashes detected" in err for err in report.errors)

    def test_nan_and_inf_coordinates_raise(self) -> None:
        """Coordinates containing NaN or Inf must raise ValueError."""
        symbols = ["H", "H"]
        nan_coords = np.array([[0.0, 0.0, 0.0], [0.0, np.nan, 0.74]])
        with pytest.raises(ValueError, match="Coordinates array contains NaN"):
            sanitize_and_validate_seed(symbols, nan_coords, strict=True)

        inf_coords = np.array([[0.0, 0.0, 0.0], [0.0, np.inf, 0.74]])
        with pytest.raises(ValueError, match="Coordinates array contains NaN"):
            sanitize_and_validate_seed(symbols, inf_coords, strict=True)

    def test_dimension_mismatch_raises(self) -> None:
        """Mismatch between symbol count and coordinate rows must raise ValueError."""
        symbols = ["C", "H", "H"]
        coords_4 = np.zeros((4, 3))
        with pytest.raises(
            ValueError, match="Mismatch: 3 symbols provided but coordinate array has 4 rows"
        ):
            sanitize_and_validate_seed(symbols, coords_4, strict=True)


# ===========================================================================
# 5. Connectivity Graph & Fragment Identification Tests
# ===========================================================================


class TestConnectivityAndFragments:
    """Test molecular adjacency matrix and disconnected fragment partitioning."""

    def test_single_molecule_connectivity(self) -> None:
        """Water molecule forms a single connected component."""
        symbols = ["O", "H", "H"]
        coords = np.array(
            [
                [0.000000, 0.000000, 0.117300],
                [0.000000, 0.757200, -0.469200],
                [0.000000, -0.757200, -0.469200],
            ]
        )
        adj = build_connectivity_matrix(symbols, coords)
        # O (index 0) connected to H1 (index 1) and H2 (index 2)
        assert adj[0, 1] and adj[1, 0]
        assert adj[0, 2] and adj[2, 0]
        assert not adj[1, 2]  # H-H distance is ~1.51 A > cutoff

        fragments = find_connected_fragments(adj)
        assert len(fragments) == 1
        assert fragments[0] == [0, 1, 2]

    def test_separated_bimolecular_dimer_identifies_two_fragments(self) -> None:
        """Two water molecules separated by 10 A must be detected as 2 separate fragments."""
        symbols = ["O", "H", "H", "O", "H", "H"]
        coords = np.array(
            [
                # Water 1
                [0.0, 0.0, 0.117],
                [0.0, 0.757, -0.469],
                [0.0, -0.757, -0.469],
                # Water 2 (translated by 10 A in x)
                [10.0, 0.0, 0.117],
                [10.0, 0.757, -0.469],
                [10.0, -0.757, -0.469],
            ]
        )
        adj = build_connectivity_matrix(symbols, coords)
        fragments = find_connected_fragments(adj)
        assert len(fragments) == 2
        assert fragments[0] == [0, 1, 2]
        assert fragments[1] == [3, 4, 5]

        report = sanitize_and_validate_seed(symbols, coords, strict=False)
        assert report.num_fragments == 2
        assert report.status == PreflightStatus.WARNING
        assert any("2 disconnected fragments" in w for w in report.warnings)


# ===========================================================================
# 6. Valency Assessment & Diagnostic Warnings Tests
# ===========================================================================


class TestValencyAndDiagnostics:
    """Test per-atom valency bounds and uncharged radical diagnostic flags."""

    def test_hypervalent_hydrogen_warning(self) -> None:
        """Hydrogen atom placed symmetrically between two carbon atoms (bridging) triggers hypervalent warning."""
        symbols = ["C", "H", "C"]
        coords = np.array(
            [
                [-1.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],  # H bonded to both C atoms at 1.0 A
                [1.0, 0.0, 0.0],
            ]
        )
        diagnostics = assess_valency_and_radicals(symbols, coords)
        h_diag = diagnostics[1]
        assert h_diag.symbol == "H"
        assert h_diag.coordination_number == 2
        assert h_diag.valency_anomaly
        assert any("Hypervalent hydrogen" in w for w in h_diag.warnings)

    def test_hypervalent_carbon_warning(self) -> None:
        """Carbon atom bonded to 5 hydrogens triggers hypervalent carbon warning."""
        symbols = ["C", "H", "H", "H", "H", "H"]
        coords = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.09, 0.0, 0.0],
                [-1.09, 0.0, 0.0],
                [0.0, 1.09, 0.0],
                [0.0, -1.09, 0.0],
                [0.0, 0.0, 1.09],
            ]
        )
        diagnostics = assess_valency_and_radicals(symbols, coords)
        c_diag = diagnostics[0]
        assert c_diag.symbol == "C"
        assert c_diag.coordination_number == 5
        assert c_diag.valency_anomaly
        assert any("Hypervalent carbon" in w for w in c_diag.warnings)


# ===========================================================================
# 7. Master Preflight Entrypoint & Reporting Tests
# ===========================================================================


class TestMasterSanitizeAndValidateSeed:
    """Test full preflight pipeline and report serialization."""

    def test_water_full_preflight_pass(self) -> None:
        """Standard water seed must pass preflight with PASS status."""
        symbols = ["O", "H", "H"]
        coords = np.array(
            [
                [0.000000, 0.000000, 0.117300],
                [0.000000, 0.757200, -0.469200],
                [0.000000, -0.757200, -0.469200],
            ]
        )
        report = sanitize_and_validate_seed(
            symbols,
            coords,
            charge=0,
            multiplicity=1,
            strict=True,
            center_on_com=True,
            align_principal_axes_flag=True,
        )
        assert report.is_valid
        assert report.status == PreflightStatus.PASS
        assert report.total_atoms == 3
        assert report.total_nuclear_charge == 10
        assert report.total_electrons == 10
        assert report.formal_charge == 0
        assert report.spin_multiplicity == 1
        assert report.num_fragments == 1
        assert len(report.nuclear_clashes) == 0

        # Coordinates retrieved as numpy
        coords_np = report.get_coordinates_numpy()
        assert coords_np.shape == (3, 3)

        # Summary string check
        summary = report.summary()
        assert "CoChem-TOPOS Preflight Report" in summary
        assert "Status: PASS" in summary

        # JSON Serialization check
        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["status"] == "PASS"
        assert data["total_atoms"] == 3
        assert data["total_electrons"] == 10

    def test_empty_system_handling(self) -> None:
        """Empty input system in non-strict mode returns clean FAIL report."""
        report = sanitize_and_validate_seed([], [], strict=False)
        assert not report.is_valid
        assert report.status == PreflightStatus.FAIL
        assert report.total_atoms == 0
        assert any("Empty system" in e for e in report.errors)

    def test_open_shell_radical_methyl_preflight(self) -> None:
        """Doublet methyl radical CH3 passes preflight."""
        symbols = ["C", "H", "H", "H"]
        # Planar D3h methyl radical
        r = 1.08
        coords = [
            [0.0, 0.0, 0.0],
            [r, 0.0, 0.0],
            [-0.5 * r, math.sqrt(3) / 2 * r, 0.0],
            [-0.5 * r, -math.sqrt(3) / 2 * r, 0.0],
        ]
        # Multiplicity 2 (Doublet) -> Passes!
        report = sanitize_and_validate_seed(
            symbols, coords, charge=0, multiplicity=2, strict=True, center_on_com=True
        )
        assert report.is_valid
        assert report.total_electrons == 9
        assert report.spin_multiplicity == 2
        assert report.num_unpaired_electrons == 1
        assert math.isclose(report.spin_quantum_number_s, 0.5, abs_tol=1e-6)

        # Multiplicity 1 (Singlet) in strict mode -> Raises ValueError
        with pytest.raises(ValueError, match="Spin parity violation"):
            sanitize_and_validate_seed(symbols, coords, charge=0, multiplicity=1, strict=True)

    def test_ammonium_and_hydroxide_ions_preflight(self) -> None:
        """Cations and anions validate correctly with non-zero formal charge."""
        # NH4+ cation
        nh4_symbols = ["N", "H", "H", "H", "H"]
        d = 1.02 / math.sqrt(3)
        nh4_coords = [
            [0.0, 0.0, 0.0],
            [d, d, d],
            [d, -d, -d],
            [-d, d, -d],
            [-d, -d, d],
        ]
        report_nh4 = sanitize_and_validate_seed(
            nh4_symbols, nh4_coords, charge=1, multiplicity=1, strict=True
        )
        assert report_nh4.is_valid
        assert report_nh4.formal_charge == 1
        assert report_nh4.total_electrons == 10

        # OH- anion
        oh_symbols = ["O", "H"]
        oh_coords = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.96]]
        report_oh = sanitize_and_validate_seed(
            oh_symbols, oh_coords, charge=-1, multiplicity=1, strict=True
        )
        assert report_oh.is_valid
        assert report_oh.formal_charge == -1
        assert report_oh.total_electrons == 10

    def test_heavy_and_isotopic_water(self) -> None:
        """Deuterated water D2O and mixed HOD resolve proper isotopic masses and COM."""
        # D2O
        d2o_symbols = ["O", "D", "D"]
        d2o_coords = [
            [0.0, 0.0, 0.117],
            [0.0, 0.757, -0.469],
            [0.0, -0.757, -0.469],
        ]
        report_d2o = sanitize_and_validate_seed(d2o_symbols, d2o_coords, strict=True)
        assert report_d2o.is_valid
        # Mass of D2O is ~ 15.9949 + 2*2.0141 = ~ 20.0231 Da
        assert 20.02 < report_d2o.total_monoisotopic_mass < 20.03

        # HOD
        hod_symbols = ["O", "H", "D"]
        report_hod = sanitize_and_validate_seed(hod_symbols, d2o_coords, strict=True)
        assert report_hod.is_valid
        assert 19.01 < report_hod.total_monoisotopic_mass < 19.03

    def test_report_numpy_accessors(self) -> None:
        """Verify all numpy accessor methods on PreflightReport."""
        symbols = ["O", "H", "H"]
        coords = np.array(
            [
                [0.000000, 0.000000, 0.117300],
                [0.000000, 0.757200, -0.469200],
                [0.000000, -0.757200, -0.469200],
            ]
        )
        report = sanitize_and_validate_seed(symbols, coords, strict=True)

        geom_center = report.get_geometric_center_numpy()
        assert geom_center.shape == (3,)

        com = report.get_center_of_mass_numpy()
        assert com.shape == (3,)

        mw_coords = report.get_mass_weighted_coordinates_numpy()
        assert mw_coords.shape == (3, 3)

        moments = report.get_principal_moments_numpy()
        assert moments.shape == (3,)

--- D:\__CoChem\GitHub-Repo\CoChem-TOPOS\tests\test_topology_graph.py ---
"""
Unit tests for CoChem-TOPOS Graph Cleavage and Routing Engine (cochem_topos_graph.py).
Validates covalent connectivity graph construction, resonance protection trap scaling,
and physical coordinate severing into monomer seeds for counterpoise assembly.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from topology.cochem_topos_graph import (
    TopologyAnalysisResult,
    TopologyGraphEngine,
    analyze_molecular_graph,
    generate_chemical_formula,
    get_covalent_radius,
    parse_xyz_file,
    parse_xyz_string,
)


class TestCovalentRadiiAndFormulas:
    """Verifies empirical covalent radii lookup and chemical formula formatting."""

    def test_covalent_radii_lookup_by_symbol_and_atomic_number(self) -> None:
        """Confirms covalent radii match Cordero / Pyykko standards for common elements."""
        assert get_covalent_radius("H") == 0.31
        assert get_covalent_radius(1) == 0.31
        assert get_covalent_radius("C") == 0.76
        assert get_covalent_radius(6) == 0.76
        assert get_covalent_radius("N") == 0.71
        assert get_covalent_radius(7) == 0.71
        assert get_covalent_radius("O") == 0.66
        assert get_covalent_radius(8) == 0.66
        assert get_covalent_radius("F") == 0.57
        assert get_covalent_radius(9) == 0.57
        assert get_covalent_radius("Ar") == 1.06
        assert get_covalent_radius(18) == 1.06

    def test_covalent_radii_fallback(self) -> None:
        """Confirms unlisted or synthetic elements fall back to a reasonable default radius."""
        fallback_radius = get_covalent_radius(999)
        assert fallback_radius == 1.50

    def test_generate_chemical_formula(self) -> None:
        """Validates Hill notation chemical formula generation."""
        assert generate_chemical_formula(["O", "H", "H"]) == "H2O"
        assert generate_chemical_formula(["C", "H", "H", "H", "H"]) == "CH4"
        assert generate_chemical_formula(["C", "C", "C", "C", "C", "C", "H", "H", "H", "H", "H", "H"]) == "C6H6"
        assert generate_chemical_formula(["C", "O", "O"]) == "CO2"
        assert generate_chemical_formula(["Ar"]) == "Ar"
        assert generate_chemical_formula(["H", "F"]) == "FH" or generate_chemical_formula(["H", "F"]) == "HF"


class TestMonomerIdentification:
    """Verifies that single covalent molecules are routed directly to MONOMER_GOAT."""

    def test_water_monomer(self) -> None:
        """Evaluates single water molecule connectivity and routing target."""
        symbols = ["O", "H", "H"]
        coordinates = np.array([
            [0.0000,  0.0000,  0.1173],
            [0.0000,  0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ])

        engine = TopologyGraphEngine()
        result = engine.analyze_topology(symbols, coordinates)

        assert isinstance(result, TopologyAnalysisResult)
        assert result.num_atoms == 3
        assert result.num_fragments == 1
        assert result.is_weak_complex is False
        assert result.classification == "Monomer"
        assert result.routing_target == "MONOMER_GOAT"
        assert result.counterpoise_flag is False
        assert len(result.monomers) == 1

        monomer = result.monomers[0]
        assert monomer.fragment_index == 0
        assert monomer.num_atoms == 3
        assert monomer.symbols == ["O", "H", "H"]
        assert monomer.atomic_numbers == [8, 1, 1]
        assert monomer.atom_indices == [0, 1, 2]
        assert monomer.formula == "H2O"
        np.testing.assert_allclose(monomer.get_numpy_coordinates(), coordinates, atol=1e-5)

    def test_methane_monomer(self) -> None:
        """Evaluates methane molecule connectivity and single component topology."""
        symbols = ["C", "H", "H", "H", "H"]
        coordinates = np.array([
            [0.0000,  0.0000,  0.0000],
            [0.6276,  0.6276,  0.6276],
            [0.6276, -0.6276, -0.6276],
            [-0.6276,  0.6276, -0.6276],
            [-0.6276, -0.6276,  0.6276],
        ])

        result = analyze_molecular_graph(symbols, coordinates)

        assert result.num_atoms == 5
        assert result.num_fragments == 1
        assert result.is_weak_complex is False
        assert result.classification == "Monomer"
        assert result.routing_target == "MONOMER_GOAT"
        assert result.counterpoise_flag is False
        assert result.monomers[0].formula == "CH4"

    def test_benzene_monomer(self) -> None:
        """Evaluates aromatic benzene ring connectivity under 1.15x covalent threshold."""
        symbols = [
            "C", "C", "C", "C", "C", "C",
            "H", "H", "H", "H", "H", "H"
        ]
        coordinates = np.array([
            [ 0.0000,  1.3970,  0.0000],
            [ 1.2098,  0.6985,  0.0000],
            [ 1.2098, -0.6985,  0.0000],
            [ 0.0000, -1.3970,  0.0000],
            [-1.2098, -0.6985,  0.0000],
            [-1.2098,  0.6985,  0.0000],
            [ 0.0000,  2.4790,  0.0000],
            [ 2.1469,  1.2395,  0.0000],
            [ 2.1469, -1.2395,  0.0000],
            [ 0.0000, -2.4790,  0.0000],
            [-2.1469, -1.2395,  0.0000],
            [-2.1469,  1.2395,  0.0000],
        ])

        result = analyze_molecular_graph(symbols, coordinates)

        assert result.num_atoms == 12
        assert result.num_fragments == 1
        assert result.is_weak_complex is False
        assert result.classification == "Monomer"
        assert result.routing_target == "MONOMER_GOAT"
        assert result.counterpoise_flag is False
        assert result.monomers[0].formula == "C6H6"


class TestResonanceProtectionTrap:
    """Verifies that the 1.15x scaling factor preserves elongated transition state bonds."""

    def test_elongated_carbon_bond_scaling_protection(self) -> None:
        """
        Tests an elongated C-C bond at 1.65 Angstroms (e.g. transition state).
        Standard covalent sum = 0.76 + 0.76 = 1.52 A.
        Unscaled threshold (1.00x) = 1.52 A < 1.65 A -> False fragmentation.
        Scaled threshold (1.15x) = 1.15 * 1.52 = 1.748 A >= 1.65 A -> Protected single molecule!
        """
        symbols = ["C", "C", "H", "H", "H", "H", "H", "H"]
        # Stretched ethane with C-C distance = 1.65 A and C-H distances = 1.018 A (< 1.07 A)
        coordinates = np.array([
            [-0.8250,  0.0000,  0.0000],
            [ 0.8250,  0.0000,  0.0000],
            [-1.1650,  0.9600,  0.0000],
            [-1.1650, -0.4800,  0.8314],
            [-1.1650, -0.4800, -0.8314],
            [ 1.1650,  0.9600,  0.0000],
            [ 1.1650, -0.4800,  0.8314],
            [ 1.1650, -0.4800, -0.8314],
        ])

        engine_scaled = TopologyGraphEngine(resonance_scale=1.15)
        result_scaled = engine_scaled.analyze_topology(symbols, coordinates)
        assert result_scaled.num_fragments == 1
        assert result_scaled.is_weak_complex is False
        assert result_scaled.classification == "Monomer"
        assert result_scaled.routing_target == "MONOMER_GOAT"

        engine_unscaled = TopologyGraphEngine(resonance_scale=1.00)
        result_unscaled = engine_unscaled.analyze_topology(symbols, coordinates)
        assert result_unscaled.num_fragments == 2
        assert result_unscaled.is_weak_complex is True
        assert result_unscaled.classification == "Weak Complex"
        assert result_unscaled.routing_target == "COUNTERPOISE_ASSEMBLY"


class TestWeakComplexDetectionAndCleavage:
    """Verifies that non-covalent complexes are severed into isolated monomer seeds."""

    def test_water_dimer_cleavage(self) -> None:
        """
        Tests water dimer (H2O...H2O) with hydrogen bond distance ~1.95 A (O...H) and ~2.9 A (O...O).
        Both exceed covalent cutoffs and result in 2 severed water monomer seeds.
        """
        symbols = ["O", "H", "H", "O", "H", "H"]
        coordinates = np.array([
            # Monomer A (indices 0, 1, 2)
            [-1.464, -0.019,  0.021],
            [-1.765,  0.888,  0.002],
            [-0.499, -0.008, -0.063],
            # Monomer B (indices 3, 4, 5)
            [ 1.442,  0.001, -0.004],
            [ 1.761, -0.457,  0.778],
            [ 1.745, -0.479, -0.771],
        ])

        engine = TopologyGraphEngine(resonance_scale=1.15)
        result = engine.analyze_topology(symbols, coordinates)

        assert result.num_atoms == 6
        assert result.num_fragments == 2
        assert result.is_weak_complex is True
        assert result.classification == "Weak Complex"
        assert result.routing_target == "COUNTERPOISE_ASSEMBLY"
        assert result.counterpoise_flag is True
        assert len(result.monomers) == 2

        # Verify monomer A
        monomer_a = result.monomers[0]
        assert monomer_a.num_atoms == 3
        assert monomer_a.symbols == ["O", "H", "H"]
        assert monomer_a.atom_indices == [0, 1, 2]
        assert monomer_a.formula == "H2O"
        np.testing.assert_allclose(monomer_a.get_numpy_coordinates(), coordinates[0:3], atol=1e-5)

        # Verify monomer B
        monomer_b = result.monomers[1]
        assert monomer_b.num_atoms == 3
        assert monomer_b.symbols == ["O", "H", "H"]
        assert monomer_b.atom_indices == [3, 4, 5]
        assert monomer_b.formula == "H2O"
        np.testing.assert_allclose(monomer_b.get_numpy_coordinates(), coordinates[3:6], atol=1e-5)

    def test_formic_acid_dimer_cleavage(self) -> None:
        """Tests hydrogen-bonded formic acid dimer ((HCOOH)2) cleavage into 2 HCOOH monomers."""
        symbols = [
            "C", "O", "O", "H", "H",
            "C", "O", "O", "H", "H"
        ]
        coordinates = np.array([
            # Monomer 1 (HCOOH)
            [-1.3400,  0.1300,  0.0000],
            [-1.2500,  1.3200,  0.0000],
            [-2.3900, -0.6600,  0.0000],
            [-0.3800, -0.4200,  0.0000],
            [-2.2300, -1.6100,  0.0000],
            # Monomer 2 (HCOOH)
            [ 1.3400, -0.1300,  0.0000],
            [ 1.2500, -1.3200,  0.0000],
            [ 2.3900,  0.6600,  0.0000],
            [ 0.3800,  0.4200,  0.0000],
            [ 2.2300,  1.6100,  0.0000],
        ])

        result = analyze_molecular_graph(symbols, coordinates)

        assert result.num_atoms == 10
        assert result.num_fragments == 2
        assert result.is_weak_complex is True
        assert result.classification == "Weak Complex"
        assert result.routing_target == "COUNTERPOISE_ASSEMBLY"
        assert result.counterpoise_flag is True

        assert len(result.monomers) == 2
        assert result.monomers[0].num_atoms == 5
        assert result.monomers[0].formula == "CH2O2"
        assert result.monomers[1].num_atoms == 5
        assert result.monomers[1].formula == "CH2O2"

    def test_carbon_dioxide_water_complex(self) -> None:
        """Tests hetero-dimer CO2...H2O cleavage into CO2 and H2O monomers."""
        symbols = ["C", "O", "O", "O", "H", "H"]
        coordinates = np.array([
            # CO2
            [ 0.000,  0.000, -1.500],
            [ 0.000,  0.000, -0.340],
            [ 0.000,  0.000, -2.660],
            # H2O
            [ 0.000,  0.000,  1.500],
            [ 0.000,  0.757,  2.087],
            [ 0.000, -0.757,  2.087],
        ])

        result = analyze_molecular_graph(symbols, coordinates)

        assert result.num_atoms == 6
        assert result.num_fragments == 2
        assert result.is_weak_complex is True
        assert result.classification == "Weak Complex"
        assert result.routing_target == "COUNTERPOISE_ASSEMBLY"
        assert result.counterpoise_flag is True

        formulas = sorted([m.formula for m in result.monomers])
        assert formulas == ["CO2", "H2O"]

    def test_argon_hydrogen_fluoride_complex(self) -> None:
        """Tests noble-gas van der Waals complex Ar...HF."""
        symbols = ["Ar", "H", "F"]
        coordinates = np.array([
            [0.0000, 0.0000, -2.0000],  # Ar
            [0.0000, 0.0000,  1.0000],  # H
            [0.0000, 0.0000,  1.9200],  # F
        ])

        result = analyze_molecular_graph(symbols, coordinates)

        assert result.num_atoms == 3
        assert result.num_fragments == 2
        assert result.is_weak_complex is True
        assert result.classification == "Weak Complex"
        assert result.routing_target == "COUNTERPOISE_ASSEMBLY"
        assert result.counterpoise_flag is True

        atom_counts = sorted([m.num_atoms for m in result.monomers])
        assert atom_counts == [1, 2]

    def test_water_trimer_multi_fragment_cleavage(self) -> None:
        """Tests three-body cluster (H2O)3 cleavage into 3 distinct monomer seeds."""
        symbols = ["O", "H", "H", "O", "H", "H", "O", "H", "H"]
        coordinates = np.array([
            # Monomer 1
            [ 1.500,  0.000, 0.000],
            [ 2.000,  0.757, 0.000],
            [ 2.000, -0.757, 0.000],
            # Monomer 2
            [-1.500,  1.500, 0.000],
            [-1.000,  2.257, 0.000],
            [-1.000,  0.743, 0.000],
            # Monomer 3
            [-1.500, -1.500, 0.000],
            [-1.000, -0.743, 0.000],
            [-1.000, -2.257, 0.000],
        ])

        result = analyze_molecular_graph(symbols, coordinates)

        assert result.num_atoms == 9
        assert result.num_fragments == 3
        assert result.is_weak_complex is True
        assert result.classification == "Weak Complex"
        assert result.routing_target == "COUNTERPOISE_ASSEMBLY"
        assert result.counterpoise_flag is True
        assert len(result.monomers) == 3
        for monomer in result.monomers:
            assert monomer.num_atoms == 3
            assert monomer.formula == "H2O"


class TestCoordinateSlicingAndXYZExport:
    """Verifies XYZ parsing, string output, file export, and coordinate integrity."""

    def test_monomer_seed_xyz_string_and_export(self, tmp_path: Path) -> None:
        """Confirms monomer seeds can be written to XYZ strings and files."""
        symbols = ["O", "H", "H", "O", "H", "H"]
        coordinates = np.array([
            [-1.5, 0.0, 0.0],
            [-1.8, 0.7, 0.0],
            [-0.6, 0.0, 0.0],
            [ 1.5, 0.0, 0.0],
            [ 1.8, 0.7, 0.0],
            [ 1.8,-0.7, 0.0],
        ])

        engine = TopologyGraphEngine()
        result = engine.analyze_topology(symbols, coordinates)

        # Verify monomer XYZ string format
        monomer_a_xyz = result.monomers[0].to_xyz_string(comment="Monomer 0")
        lines = monomer_a_xyz.strip().split("\n")
        assert lines[0] == "3"
        assert lines[1] == "Monomer 0"
        assert len(lines) == 5

        # Export all monomers to tmp_path
        exported_paths = result.save_monomers_xyz(tmp_path, base_prefix="isolated_seed")
        assert len(exported_paths) == 2
        for path in exported_paths:
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert content.startswith("3\n")

    def test_parse_xyz_string_and_file(self, tmp_path: Path) -> None:
        """Validates XYZ parser on both raw strings and disk files."""
        raw_xyz = """3
Water monomer test coordinate
O  0.0000  0.0000  0.1173
H  0.0000  0.7572 -0.4692
H  0.0000 -0.7572 -0.4692
"""
        parsed_symbols, parsed_coords, title = parse_xyz_string(raw_xyz)
        assert parsed_symbols == ["O", "H", "H"]
        assert parsed_coords.shape == (3, 3)
        assert title == "Water monomer test coordinate"

        file_path = tmp_path / "water.xyz"
        file_path.write_text(raw_xyz, encoding="utf-8")

        file_symbols, file_coords, file_title = parse_xyz_file(file_path)
        assert file_symbols == parsed_symbols
        np.testing.assert_allclose(file_coords, parsed_coords)

        # Analyze directly via engine method
        engine = TopologyGraphEngine()
        res_from_file = engine.analyze_xyz_file(file_path)
        assert res_from_file.classification == "Monomer"
        assert res_from_file.routing_target == "MONOMER_GOAT"

    def test_ase_atoms_ingestion(self) -> None:
        """Validates ingestion from an ASE Atoms object."""
        atoms = Atoms(symbols=["O", "H", "H"], positions=[
            [0.0000,  0.0000,  0.1173],
            [0.0000,  0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ])

        engine = TopologyGraphEngine()
        result = engine.analyze_atoms(atoms)
        assert result.classification == "Monomer"
        assert result.routing_target == "MONOMER_GOAT"
        assert result.num_atoms == 3


class TestSerializationAndValidation:
    """Verifies Pydantic model serialization, validation, and error traps."""

    def test_pydantic_serialization(self) -> None:
        """Verifies JSON round-trip serialization of TopologyAnalysisResult."""
        symbols = ["O", "H", "H"]
        coordinates = np.array([
            [0.0000,  0.0000,  0.1173],
            [0.0000,  0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ])

        engine = TopologyGraphEngine()
        result = engine.analyze_topology(symbols, coordinates)

        json_str = result.to_json()
        data = json.loads(json_str)

        assert data["num_atoms"] == 3
        assert data["classification"] == "Monomer"
        assert data["routing_target"] == "MONOMER_GOAT"
        assert len(data["monomers"]) == 1

        reconstructed = TopologyAnalysisResult.model_validate(data)
        assert reconstructed.num_atoms == result.num_atoms
        assert reconstructed.routing_target == result.routing_target

    def test_single_atom_validation(self) -> None:
        """Confirms monoatomic system is treated as a monomer."""
        symbols = ["He"]
        coordinates = np.array([[0.0, 0.0, 0.0]])

        result = analyze_molecular_graph(symbols, coordinates)
        assert result.num_atoms == 1
        assert result.num_fragments == 1
        assert result.classification == "Monomer"
        assert result.routing_target == "MONOMER_GOAT"
        assert result.counterpoise_flag is False

    def test_empty_coordinates_error(self) -> None:
        """Confirms empty inputs raise ValueError."""
        engine = TopologyGraphEngine()
        with pytest.raises(ValueError, match="At least one atom"):
            engine.analyze_topology([], np.empty((0, 3)))

    def test_dimension_mismatch_error(self) -> None:
        """Confirms symbol count and coordinate count mismatch raises ValueError."""
        symbols = ["O", "H"]
        coordinates = np.array([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
        ])
        engine = TopologyGraphEngine()
        with pytest.raises(ValueError, match="Mismatch"):
            engine.analyze_topology(symbols, coordinates)

    def test_invalid_coordinate_shape_error(self) -> None:
        """Confirms 2D or 1D coordinate array raises ValueError."""
        symbols = ["O", "H"]
        coordinates = np.array([[0.0, 0.0], [1.0, 0.0]])
        engine = TopologyGraphEngine()
        with pytest.raises(ValueError, match="Cartesian coordinates must have shape"):
            engine.analyze_topology(symbols, coordinates)

Validate Zero-Mock adherence. Target repo is D:\__CoChem\GitHub-Repo\CoChem-TOPOS.