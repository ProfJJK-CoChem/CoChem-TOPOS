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
from numpy import linalg as la

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
        return np.array(self.sanitized_coordinates, dtype=np.float64)

    def get_mass_weighted_coordinates_numpy(self) -> np.ndarray:
        """Return mass-weighted coordinates as a NumPy array of shape (N, 3)."""
        return np.array(self.mass_weighted_coordinates, dtype=np.float64)

    def get_center_of_mass_numpy(self) -> np.ndarray:
        """Return center of mass vector as a 1D NumPy array of shape (3,)."""
        return np.array(self.center_of_mass, dtype=np.float64)

    def get_geometric_center_numpy(self) -> np.ndarray:
        """Return geometric centroid vector as a 1D NumPy array of shape (3,)."""
        return np.array(self.geometric_center, dtype=np.float64)

    def get_principal_moments_numpy(self) -> np.ndarray:
        """Return principal moments of inertia as a 1D NumPy array of shape (3,)."""
        return np.array(self.principal_moments_of_inertia, dtype=np.float64)

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
    return np.array([get_monoisotopic_mass(s) for s in symbols_or_zs], dtype=np.float64)


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
    coords = np.array(cast(Any, coordinates), dtype=np.float64)
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
    coords = np.array(cast(Any, coordinates), dtype=np.float64)
    if coords.ndim != 2 or coords.shape[1] != 3:
        raise ValueError(f"Coordinates must be 2D array of shape (N, 3), got {coords.shape}.")
    return cast(np.ndarray, np.mean(coords, axis=0))


def center_coordinates(
    coordinates: np.ndarray | Sequence[Sequence[float]],
    masses: np.ndarray | Sequence[float] | None = None,
) -> np.ndarray:
    """Translate coordinates to origin (Center of Mass if masses provided, else geometric centroid)."""
    coords = np.array(cast(Any, coordinates), dtype=np.float64).copy()
    if masses is not None:
        m = np.array(cast(Any, masses), dtype=np.float64)
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
    coords = np.array(cast(Any, coordinates), dtype=np.float64)
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
    coords = np.array(cast(Any, coordinates), dtype=np.float64)
    masses = get_monoisotopic_masses(symbols_or_zs)
    shifted = center_coordinates(coords, masses=masses)

    tensor = np.zeros((3, 3), dtype=np.float64)
    for m, r in zip(masses, shifted, strict=False):
        r_sq = float(np.dot(r, r))
        tensor += m * (r_sq * np.eye(3, dtype=np.float64) - np.outer(r, r))
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
    coords = np.array(cast(Any, coordinates), dtype=np.float64)
    masses = get_monoisotopic_masses(symbols_or_zs)
    shifted = center_coordinates(coords, masses=masses)

    if coords.shape[0] == 1:
        # Single atom: already at origin, inertia tensor is zero
        return shifted, np.zeros(3, dtype=np.float64), np.eye(3, dtype=np.float64)

    inertia_tensor = compute_moment_of_inertia_tensor(symbols_or_zs, coordinates)
    eigvals, eigvecs = la.eigh(inertia_tensor)  # type: ignore[attr-defined]

    # Ensure right-handed coordinate system (det = +1)
    if float(la.det(eigvecs)) < 0:  # type: ignore[attr-defined]
        eigvecs[:, -1] *= -1.0

    aligned = shifted @ eigvecs
    return aligned, cast(np.ndarray, eigvals), cast(np.ndarray, eigvecs)


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
    coords = np.array(cast(Any, coordinates), dtype=np.float64)
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
            dist = float(la.norm(coords[i] - coords[j]))  # type: ignore[attr-defined]
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
    coords = np.array(cast(Any, coordinates), dtype=np.float64)
    n_atoms = coords.shape[0]
    cov_radii = [get_element_info(s).covalent_radius_angstrom for s in symbols_or_zs]

    adj_matrix = np.zeros((n_atoms, n_atoms), dtype=np.bool_)
    for i in range(n_atoms):
        for j in range(i + 1, n_atoms):
            dist = float(la.norm(coords[i] - coords[j]))  # type: ignore[attr-defined]
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
    coords = np.array(cast(Any, coordinates), dtype=np.float64)
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
        coords_arr = np.array(cast(Any, coordinates), dtype=np.float64)
    except Exception as exc:
        msg = f"Failed to convert coordinates to float64 numpy array: {exc}"
        if strict:
            raise ValueError(msg) from exc
        errors.append(msg)
        coords_arr = np.zeros((len(symbols_or_zs), 3), dtype=np.float64)

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

    if not bool(np.all(np.isfinite(coords_arr))):  # type: ignore[attr-defined]
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
            sanitized_coords, masses=np.array(monoisotopic_masses_list, dtype=np.float64)
        )

    principal_moments = [0.0, 0.0, 0.0]
    if align_principal_axes_flag and len(sanitized_coords) == len(monoisotopic_masses_list):
        sanitized_coords, moments, _ = align_to_principal_axes(symbols_list, sanitized_coords)
        principal_moments = [float(x) for x in moments]
    elif len(sanitized_coords) == len(monoisotopic_masses_list) and sanitized_coords.shape[0] > 1:
        try:
            inertia_tensor = compute_moment_of_inertia_tensor(symbols_list, sanitized_coords)
            evals, _ = la.eigh(inertia_tensor)  # type: ignore[attr-defined]
            principal_moments = [float(x) for x in evals]
        except Exception:
            principal_moments = [0.0, 0.0, 0.0]

    # Centers
    if total_mass > 0 and len(coords_arr) == len(monoisotopic_masses_list):
        com_vec = compute_center_of_mass(symbols_list, coords_arr)
    else:
        com_vec = np.zeros(3, dtype=np.float64)

    geom_center_vec = (
        compute_geometric_center(coords_arr)
        if coords_arr.ndim == 2 and coords_arr.shape[1] == 3
        else np.zeros(3, dtype=np.float64)
    )

    # Mass-weighted coords
    if total_mass > 0 and len(sanitized_coords) == len(monoisotopic_masses_list):
        mw_coords = sanitized_coords * np.sqrt(np.array(monoisotopic_masses_list, dtype=np.float64)[:, np.newaxis])
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
