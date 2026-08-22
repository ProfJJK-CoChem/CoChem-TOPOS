"""
CoChem-TOPOS v4.0: Graph Cleavage and Pipeline Routing Engine (cochem_topos_graph.py)
Converts 3D Cartesian coordinates into a mathematical connectivity graph to classify
molecular systems as single covalent monomers or non-covalent weak complexes.

Implements:
1. Distance Matrix Generation via scipy.spatial.distance.cdist.
2. The Resonance Protection Trap: Covalent adjacency threshold scaled by 1.15x
   (A_ij = 1 if D_ij <= 1.15 * (R_i + R_j) for i != j).
3. Graph Cleavage via NetworkX connected components:
   - Monomer -> routing_target="MONOMER_GOAT", is_weak_complex=False, classification="Monomer"
   - Weak Complex -> routing_target="COUNTERPOISE_ASSEMBLY", is_weak_complex=True,
     classification="Weak Complex", counterpoise_flag=True, and physically severed monomer seeds.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import networkx as nx
import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.spatial.distance import cdist

logger = logging.getLogger("CoChem.TOPOS.GraphEngine")

# Standard Resonance Protection Scaling Factor
RESONANCE_PROTECTION_SCALE: float = 1.15

# Default fallback covalent radius (Angstroms) for unknown elements
DEFAULT_COVALENT_RADIUS: float = 1.50

# Empirical Single-Bond Covalent Radii (Angstroms)
# Cordero et al. (Dalton Trans. 2008, 2832-2838) & Pyykko-Atsumi (Chem. Eur. J. 2009, 15, 186-197)
COVALENT_RADII: dict[int, float] = {
    1: 0.31,    # H
    2: 0.28,    # He
    3: 1.28,    # Li
    4: 0.96,    # Be
    5: 0.84,    # B
    6: 0.76,    # C
    7: 0.71,    # N
    8: 0.66,    # O
    9: 0.57,    # F
    10: 0.58,   # Ne
    11: 1.66,   # Na
    12: 1.41,   # Mg
    13: 1.21,   # Al
    14: 1.11,   # Si
    15: 1.07,   # P
    16: 1.05,   # S
    17: 1.02,   # Cl
    18: 1.06,   # Ar
    19: 2.03,   # K
    20: 1.76,   # Ca
    21: 1.70,   # Sc
    22: 1.60,   # Ti
    23: 1.53,   # V
    24: 1.39,   # Cr
    25: 1.39,   # Mn
    26: 1.32,   # Fe
    27: 1.26,   # Co
    28: 1.24,   # Ni
    29: 1.32,   # Cu
    30: 1.22,   # Zn
    31: 1.22,   # Ga
    32: 1.20,   # Ge
    33: 1.19,   # As
    34: 1.20,   # Se
    35: 1.20,   # Br
    36: 1.16,   # Kr
    37: 2.20,   # Rb
    38: 1.95,   # Sr
    39: 1.90,   # Y
    40: 1.75,   # Zr
    41: 1.64,   # Nb
    42: 1.54,   # Mo
    43: 1.47,   # Tc
    44: 1.46,   # Ru
    45: 1.42,   # Rh
    46: 1.39,   # Pd
    47: 1.45,   # Ag
    48: 1.44,   # Cd
    49: 1.42,   # In
    50: 1.39,   # Sn
    51: 1.39,   # Sb
    52: 1.38,   # Te
    53: 1.39,   # I
    54: 1.40,   # Xe
    55: 2.44,   # Cs
    56: 2.15,   # Ba
    57: 2.07,   # La
    58: 2.04,   # Ce
    59: 2.03,   # Pr
    60: 2.01,   # Nd
    61: 1.99,   # Pm
    62: 1.98,   # Sm
    63: 1.98,   # Eu
    64: 1.96,   # Gd
    65: 1.94,   # Tb
    66: 1.92,   # Dy
    67: 1.92,   # Ho
    68: 1.89,   # Er
    69: 1.90,   # Tm
    70: 1.87,   # Yb
    71: 1.87,   # Lu
    72: 1.75,   # Hf
    73: 1.70,   # Ta
    74: 1.62,   # W
    75: 1.51,   # Re
    76: 1.44,   # Os
    77: 1.41,   # Ir
    78: 1.36,   # Pt
    79: 1.36,   # Au
    80: 1.32,   # Hg
    81: 1.45,   # Tl
    82: 1.46,   # Pb
    83: 1.48,   # Bi
    84: 1.40,   # Po
    85: 1.50,   # At
    86: 1.50,   # Rn
    87: 2.60,   # Fr
    88: 2.21,   # Ra
    89: 2.15,   # Ac
    90: 2.06,   # Th
    91: 2.00,   # Pa
    92: 1.96,   # U
    93: 1.90,   # Np
    94: 1.87,   # Pu
    95: 1.80,   # Am
    96: 1.69,   # Cm
    97: 1.68,   # Bk
    98: 1.68,   # Cf
    99: 1.65,   # Es
    100: 1.67,  # Fm
    101: 1.73,  # Md
    102: 1.76,  # No
    103: 1.61,  # Lr
    104: 1.57,  # Rf
    105: 1.49,  # Db
    106: 1.43,  # Sg
    107: 1.41,  # Bh
    108: 1.34,  # Hs
    109: 1.29,  # Mt
    110: 1.28,  # Ds
    111: 1.21,  # Rg
    112: 1.22,  # Cn
    113: 1.36,  # Nh
    114: 1.43,  # Fl
    115: 1.62,  # Mc
    116: 1.75,  # Lv
    117: 1.65,  # Ts
    118: 1.57,  # Og
}

# Standard IUPAC Element Symbol Table (Atomic Number -> Symbol)
ELEMENT_SYMBOLS: dict[int, str] = {
    1: "H", 2: "He", 3: "Li", 4: "Be", 5: "B", 6: "C", 7: "N", 8: "O", 9: "F", 10: "Ne",
    11: "Na", 12: "Mg", 13: "Al", 14: "Si", 15: "P", 16: "S", 17: "Cl", 18: "Ar", 19: "K", 20: "Ca",
    21: "Sc", 22: "Ti", 23: "V", 24: "Cr", 25: "Mn", 26: "Fe", 27: "Co", 28: "Ni", 29: "Cu", 30: "Zn",
    31: "Ga", 32: "Ge", 33: "As", 34: "Se", 35: "Br", 36: "Kr", 37: "Rb", 38: "Sr", 39: "Y", 40: "Zr",
    41: "Nb", 42: "Mo", 43: "Tc", 44: "Ru", 45: "Rh", 46: "Pd", 47: "Ag", 48: "Cd", 49: "In", 50: "Sn",
    51: "Sb", 52: "Te", 53: "I", 54: "Xe", 55: "Cs", 56: "Ba", 57: "La", 58: "Ce", 59: "Pr", 60: "Nd",
    61: "Pm", 62: "Sm", 63: "Eu", 64: "Gd", 65: "Tb", 66: "Dy", 67: "Ho", 68: "Er", 69: "Tm", 70: "Yb",
    71: "Lu", 72: "Hf", 73: "Ta", 74: "W", 75: "Re", 76: "Os", 77: "Ir", 78: "Pt", 79: "Au", 80: "Hg",
    81: "Tl", 82: "Pb", 83: "Bi", 84: "Po", 85: "At", 86: "Rn", 87: "Fr", 88: "Ra", 89: "Ac", 90: "Th",
    91: "Pa", 92: "U", 93: "Np", 94: "Pu", 95: "Am", 96: "Cm", 97: "Bk", 98: "Cf", 99: "Es", 100: "Fm",
    101: "Md", 102: "No", 103: "Lr", 104: "Rf", 105: "Db", 106: "Sg", 107: "Bh", 108: "Hs", 109: "Mt", 110: "Ds",
    111: "Rg", 112: "Cn", 113: "Nh", 114: "Fl", 115: "Mc", 116: "Lv", 117: "Ts", 118: "Og"
}

# Standard IUPAC Symbol to Atomic Number Mapping
SYMBOL_TO_ATOMIC_NUM: dict[str, int] = {symbol.upper(): z for z, symbol in ELEMENT_SYMBOLS.items()}

# Standard IUPAC Atomic Weights (amu)
ATOMIC_WEIGHTS: dict[int, float] = {
    1: 1.008, 2: 4.0026, 3: 6.94, 4: 9.0122, 5: 10.81, 6: 12.011, 7: 14.007, 8: 15.999, 9: 18.998, 10: 20.180,
    11: 22.990, 12: 24.305, 13: 26.982, 14: 28.085, 15: 30.974, 16: 32.06, 17: 35.45, 18: 39.948, 19: 39.098, 20: 40.078,
    21: 44.956, 22: 47.867, 23: 50.942, 24: 51.996, 25: 54.938, 26: 55.845, 27: 58.933, 28: 58.693, 29: 63.546, 30: 65.38,
    31: 69.723, 32: 72.630, 33: 74.922, 34: 78.971, 35: 79.904, 36: 83.798, 37: 85.468, 38: 87.62, 39: 88.906, 40: 91.224,
    41: 92.906, 42: 95.95, 43: 98.0, 44: 101.07, 45: 102.91, 46: 106.42, 47: 107.87, 48: 112.41, 49: 114.82, 50: 118.71,
    51: 121.76, 52: 127.60, 53: 126.90, 54: 131.29, 55: 132.91, 56: 137.33, 57: 138.91, 58: 140.12, 59: 140.91, 60: 144.24,
    61: 145.0, 62: 150.36, 63: 151.96, 64: 157.25, 65: 158.93, 66: 162.50, 67: 164.93, 68: 167.26, 69: 168.93, 70: 173.05,
    71: 174.97, 72: 178.49, 73: 180.95, 74: 183.84, 75: 186.21, 76: 190.23, 77: 192.22, 78: 195.08, 79: 196.97, 80: 200.59,
    81: 204.38, 82: 207.2, 83: 208.98, 84: 209.0, 85: 210.0, 86: 222.0, 87: 223.0, 88: 226.0, 89: 227.0, 90: 232.04,
    91: 231.04, 92: 238.03, 93: 237.0, 94: 244.0, 95: 243.0, 96: 247.0, 97: 247.0, 98: 251.0, 99: 252.0, 100: 257.0,
    101: 258.0, 102: 259.0, 103: 266.0, 104: 267.0, 105: 268.0, 106: 269.0, 107: 270.0, 108: 277.0, 109: 278.0, 110: 281.0,
    111: 282.0, 112: 285.0, 113: 286.0, 114: 289.0, 115: 290.0, 116: 293.0, 117: 294.0, 118: 294.0
}


def get_atomic_number(element: str | int) -> int:
    """Resolves an element symbol or number to its integer atomic number (Z)."""
    if isinstance(element, int):
        if 1 <= element <= 118:
            return element
        return element
    elem_str = str(element).strip().upper()
    if elem_str in SYMBOL_TO_ATOMIC_NUM:
        return SYMBOL_TO_ATOMIC_NUM[elem_str]
    try:
        val = int(elem_str)
        return val
    except ValueError as err:
        raise ValueError(f"Unrecognized chemical element symbol or atomic number: '{element}'") from err


def get_atomic_symbol(z: int) -> str:
    """Returns canonical IUPAC element symbol for atomic number Z."""
    return ELEMENT_SYMBOLS.get(z, f"X{z}")


def get_covalent_radius(element: str | int) -> float:
    """Returns the empirical single-bond covalent radius in Angstroms."""
    try:
        z = get_atomic_number(element)
        return COVALENT_RADII.get(z, DEFAULT_COVALENT_RADIUS)
    except ValueError:
        return DEFAULT_COVALENT_RADIUS


def get_atomic_mass(element: str | int) -> float:
    """Returns standard atomic weight in amu."""
    try:
        z = get_atomic_number(element)
        return ATOMIC_WEIGHTS.get(z, 12.0)
    except ValueError:
        return 12.0


def generate_chemical_formula(symbols: Sequence[str]) -> str:
    """
    Constructs a standard Hill system chemical formula.
    Carbon (C) first, then Hydrogen (H), then all remaining elements alphabetically.
    If no Carbon is present, all elements are listed alphabetically.
    """
    counts: dict[str, int] = {}
    for s in symbols:
        std_sym = ELEMENT_SYMBOLS.get(get_atomic_number(s), s.capitalize())
        counts[std_sym] = counts.get(std_sym, 0) + 1

    parts: list[str] = []
    if "C" in counts:
        c_count = counts.pop("C")
        parts.append(f"C{c_count}" if c_count > 1 else "C")
        if "H" in counts:
            h_count = counts.pop("H")
            parts.append(f"H{h_count}" if h_count > 1 else "H")

    for elem in sorted(counts.keys()):
        count = counts[elem]
        parts.append(f"{elem}{count}" if count > 1 else elem)

    return "".join(parts)


def parse_xyz_string(xyz_content: str) -> tuple[list[str], np.ndarray, str]:
    """
    Parses a standard multi-line XYZ formatted string into symbols, coordinates, and comment line.
    """
    lines = [line.strip() for line in xyz_content.strip().splitlines() if line.strip()]
    if not lines:
        raise ValueError("Cannot parse empty XYZ string.")

    # Determine if first line is atom count
    first_token = lines[0].split()[0]
    is_standard_xyz = False
    try:
        num_atoms = int(first_token)
        is_standard_xyz = True
    except ValueError:
        is_standard_xyz = False

    if is_standard_xyz:
        comment = lines[1] if len(lines) > 1 else ""
        coord_lines = lines[2: 2 + num_atoms]
    else:
        comment = ""
        coord_lines = lines

    symbols: list[str] = []
    coords_list: list[list[float]] = []

    for idx, line in enumerate(coord_lines):
        tokens = line.split()
        if len(tokens) < 4:
            raise ValueError(f"Line {idx+1} does not have at least 4 tokens (Symbol X Y Z): '{line}'")
        sym = tokens[0]
        try:
            x, y, z = float(tokens[1]), float(tokens[2]), float(tokens[3])
        except ValueError as err:
            raise ValueError(f"Invalid coordinate floats on line {idx+1}: '{line}'") from err
        symbols.append(sym)
        coords_list.append([x, y, z])

    return symbols, np.array(coords_list, dtype=np.float64), comment


def parse_xyz_file(filepath: str | Path) -> tuple[list[str], np.ndarray, str]:
    """Parses an XYZ coordinate file from the filesystem."""
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"XYZ file not found: {path}")
    content = path.read_text(encoding="utf-8")
    return parse_xyz_string(content)


class MonomerSeed(BaseModel):
    """
    Represents an isolated molecular fragment severed from a larger system.
    Maintains coordinate positions, parent index tracing, and mass properties.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    fragment_index: int = Field(..., description="0-indexed partition ID of this severed monomer.")
    atom_indices: list[int] = Field(..., description="Indices of the constituent atoms in the parent system.")
    symbols: list[str] = Field(..., description="Element symbols for each atom in this monomer.")
    atomic_numbers: list[int] = Field(..., description="Atomic numbers (Z) for each atom.")
    coordinates: list[list[float]] = Field(..., description="Cartesian coordinates in Angstroms (Nx3).")
    formula: str = Field(..., description="Hill notation chemical formula.")
    num_atoms: int = Field(..., description="Total atom count in this monomer.")
    center_of_mass: list[float] = Field(..., description="Mass-weighted Cartesian center of mass [X, Y, Z].")
    total_mass: float = Field(..., description="Total atomic mass in amu.")

    def get_numpy_coordinates(self) -> np.ndarray:
        """Returns coordinates as an (N, 3) NumPy float64 array."""
        return np.array(self.coordinates, dtype=np.float64)

    def to_xyz_string(self, comment: str = "") -> str:
        """Serializes this monomer seed into standard XYZ geometry text."""
        cmt = comment or f"Monomer {self.fragment_index} | Formula: {self.formula} | Atoms: {self.num_atoms}"
        lines = [str(self.num_atoms), cmt]
        for sym, (x, y, z) in zip(self.symbols, self.coordinates, strict=False):
            lines.append(f"{sym:<3} {x:14.8f} {y:14.8f} {z:14.8f}")
        return "\n".join(lines) + "\n"

    def save_xyz(self, filepath: str | Path, comment: str = "") -> Path:
        """Saves this monomer seed to an XYZ file on disk."""
        target_path = Path(filepath)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(self.to_xyz_string(comment=comment), encoding="utf-8")
        return target_path


class TopologyAnalysisResult(BaseModel):
    """
    Structured outcome of the 3D connectivity graph analysis.
    Dictates whether the system enters standard monomer GOAT optimization
    or triggers counterpoise assembly and fragment-isolated workflows.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    num_atoms: int = Field(..., description="Total number of atoms in the parent system.")
    num_fragments: int = Field(..., description="Total number of disconnected sub-graphs detected.")
    is_weak_complex: bool = Field(..., description="True if multiple disconnected sub-graphs exist.")
    classification: str = Field(..., description="'Monomer' or 'Weak Complex'.")
    routing_target: str = Field(..., description="'MONOMER_GOAT' or 'COUNTERPOISE_ASSEMBLY'.")
    counterpoise_flag: bool = Field(..., description="Explicit flag for downstream Counterpoise (CP) assembly.")
    monomers: list[MonomerSeed] = Field(default_factory=list, description="Severed monomer seeds.")
    adjacency_matrix: list[list[int]] = Field(default_factory=list, description="Binary covalent adjacency matrix.")
    distance_matrix: list[list[float]] = Field(default_factory=list, description="Pairwise Cartesian distance matrix.")
    graph_edges: list[tuple[int, int]] = Field(default_factory=list, description="List of covalent bond edges (i, j).")
    resonance_protection_scale: float = Field(default=RESONANCE_PROTECTION_SCALE, description="Applied resonance scaling.")
    summary: str = Field(default="", description="Human-readable topology and routing summary.")

    def get_networkx_graph(self) -> nx.Graph:
        """Reconstructs the NetworkX Graph from graph edges and monomer metadata."""
        g = nx.Graph()
        for monomer in self.monomers:
            for idx, sym, z, coord in zip(monomer.atom_indices, monomer.symbols, monomer.atomic_numbers, monomer.coordinates, strict=False):
                g.add_node(idx, symbol=sym, atomic_number=z, coordinates=coord, fragment=monomer.fragment_index)
        for u, v in self.graph_edges:
            dist = self.distance_matrix[u][v] if self.distance_matrix else 0.0
            g.add_edge(u, v, distance=dist)
        return g

    def to_json(self, indent: int = 2) -> str:
        """Serializes result to JSON string."""
        return self.model_dump_json(indent=indent)

    def to_dict(self) -> dict[str, Any]:
        """Returns result as a standard Python dictionary."""
        return self.model_dump()

    def save_monomers_xyz(self, output_dir: str | Path, base_prefix: str = "monomer") -> list[Path]:
        """Writes each severed monomer seed to an individual XYZ file."""
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        saved_paths: list[Path] = []
        for monomer in self.monomers:
            filename = f"{base_prefix}_{monomer.fragment_index}_{monomer.formula}.xyz"
            target = out_dir / filename
            monomer.save_xyz(target)
            saved_paths.append(target)
        return saved_paths


class TopologyGraphEngine:
    """
    Topology Graph Engine converting 3D Cartesian coordinates into a connectivity graph.
    Applies the 1.15x Resonance Protection Trap and partitions disconnected sub-graphs
    into isolated monomer seeds.
    """

    def __init__(
        self,
        resonance_scale: float = RESONANCE_PROTECTION_SCALE,
        covalent_radii: dict[int | str, float] | None = None
    ) -> None:
        self.resonance_scale: float = float(resonance_scale)
        self.radii_table: dict[int, float] = dict(COVALENT_RADII)
        if covalent_radii is not None:
            for k, v in covalent_radii.items():
                z = get_atomic_number(k)
                self.radii_table[z] = float(v)

    def get_radius(self, element: str | int) -> float:
        """Retrieves covalent radius for given element."""
        z = get_atomic_number(element)
        return self.radii_table.get(z, DEFAULT_COVALENT_RADIUS)

    def compute_distance_matrix(self, coordinates: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
        """
        Computes the pairwise Euclidean distance matrix (Dij) between all atoms.
        Uses scipy.spatial.distance.cdist.
        """
        if isinstance(coordinates, np.ndarray):
            coords_arr = coordinates.astype(float)
        else:
            coords_arr = np.array(list(coordinates), dtype=float)

        if coords_arr.ndim != 2 or coords_arr.shape[1] != 3:
            raise ValueError(f"Cartesian coordinates must have shape (N, 3), received {coords_arr.shape}.")
        return np.asarray(cdist(coords_arr, coords_arr), dtype=float)

    def build_adjacency_matrix(
        self,
        symbols_or_atomic_numbers: Sequence[str | int],
        coordinates: np.ndarray | Sequence[Sequence[float]],
        resonance_scale: float | None = None
    ) -> np.ndarray:
        """
        Constructs the binary adjacency matrix (A) using covalent radii and the Resonance Protection Trap.
        Formula: A_ij = 1 if D_ij <= scale * (R_i + R_j) for i != j, 0 otherwise.
        """
        scale = self.resonance_scale if resonance_scale is None else float(resonance_scale)
        num_atoms = len(symbols_or_atomic_numbers)
        if num_atoms == 0:
            return np.zeros((0, 0), dtype=np.int32)

        if isinstance(coordinates, np.ndarray):
            coords_arr = coordinates.astype(float)
        else:
            coords_arr = np.array(list(coordinates), dtype=float)

        if coords_arr.shape[0] != num_atoms:
            raise ValueError(f"Mismatch: {num_atoms} symbols provided but {coords_arr.shape[0]} coordinate rows.")

        dists = self.compute_distance_matrix(coords_arr)
        radii = np.array([self.get_radius(elem) for elem in symbols_or_atomic_numbers], dtype=float)

        # Sum of covalent radii matrix: R_ij = R_i + R_j
        radii_sum = radii[:, np.newaxis] + radii[np.newaxis, :]
        threshold_matrix = scale * radii_sum

        adjacency = (dists <= threshold_matrix).astype(np.int32)
        np.fill_diagonal(adjacency, 0)
        return adjacency

    def build_graph(
        self,
        symbols_or_atomic_numbers: Sequence[str | int],
        coordinates: np.ndarray | Sequence[Sequence[float]],
        resonance_scale: float | None = None
    ) -> nx.Graph:
        """
        Constructs a NetworkX graph with node and edge attributes derived from Cartesian geometry.
        """
        if isinstance(coordinates, np.ndarray):
            coords_arr = coordinates.astype(float)
        else:
            coords_arr = np.array(list(coordinates), dtype=float)

        num_atoms = len(symbols_or_atomic_numbers)
        adj = self.build_adjacency_matrix(symbols_or_atomic_numbers, coords_arr, resonance_scale=resonance_scale)
        dists = self.compute_distance_matrix(coords_arr)

        g = nx.Graph()
        for i, elem in enumerate(symbols_or_atomic_numbers):
            z = get_atomic_number(elem)
            sym = get_atomic_symbol(z)
            g.add_node(i, symbol=sym, atomic_number=z, coordinates=[float(coords_arr[i, 0]), float(coords_arr[i, 1]), float(coords_arr[i, 2])])

        for i in range(num_atoms):
            for j in range(i + 1, num_atoms):
                if adj[i, j] == 1:
                    g.add_edge(i, j, distance=float(dists[i, j]))

        return g

    def analyze_topology(
        self,
        symbols_or_atomic_numbers: Sequence[str | int],
        coordinates: np.ndarray | Sequence[Sequence[float]],
        resonance_scale: float | None = None
    ) -> TopologyAnalysisResult:
        """
        Main entry point for topological graph evaluation.
        Converts 3D Cartesian coordinates into a connectivity graph, evaluates connected sub-graphs,
        and constructs severed monomer seeds for weak complexes.
        """
        scale = self.resonance_scale if resonance_scale is None else float(resonance_scale)
        num_atoms = len(symbols_or_atomic_numbers)
        if num_atoms == 0:
            raise ValueError("Cannot analyze empty system: At least one atom required.")

        if isinstance(coordinates, np.ndarray):
            coords_arr = coordinates.astype(float)
        else:
            coords_arr = np.array(list(coordinates), dtype=float)

        if coords_arr.ndim != 2 or coords_arr.shape[1] != 3:
            raise ValueError(f"Cartesian coordinates must have shape (N, 3), received {coords_arr.shape}.")
        if coords_arr.shape[0] != num_atoms:
            raise ValueError(f"Mismatch: {num_atoms} element entries but {coords_arr.shape[0]} coordinate rows.")

        # Distance matrix & Adjacency matrix
        d_matrix = self.compute_distance_matrix(coords_arr)
        a_matrix = self.build_adjacency_matrix(symbols_or_atomic_numbers, coords_arr, resonance_scale=scale)

        # Build NetworkX Graph
        g = nx.Graph()
        std_symbols: list[str] = []
        atomic_numbers: list[int] = []

        for i, elem in enumerate(symbols_or_atomic_numbers):
            z = get_atomic_number(elem)
            sym = get_atomic_symbol(z)
            std_symbols.append(sym)
            atomic_numbers.append(z)
            g.add_node(i, symbol=sym, atomic_number=z, coordinates=[float(coords_arr[i, 0]), float(coords_arr[i, 1]), float(coords_arr[i, 2])])

        graph_edges: list[tuple[int, int]] = []
        for i in range(num_atoms):
            for j in range(i + 1, num_atoms):
                if a_matrix[i, j] == 1:
                    g.add_edge(i, j, distance=float(d_matrix[i, j]))
                    graph_edges.append((i, j))

        # Evaluate connected components (disconnected sub-graphs)
        raw_components = list(nx.connected_components(g))
        # Sort components deterministically by minimum atom index
        sorted_components = sorted(raw_components, key=lambda comp: min(comp))
        num_fragments = len(sorted_components)

        is_weak_complex = num_fragments > 1
        classification = "Weak Complex" if is_weak_complex else "Monomer"
        routing_target = "COUNTERPOISE_ASSEMBLY" if is_weak_complex else "MONOMER_GOAT"
        counterpoise_flag = is_weak_complex

        # Physically sever coordinates into isolated monomer seeds
        monomer_seeds: list[MonomerSeed] = []
        for frag_idx, comp in enumerate(sorted_components):
            comp_indices = sorted(list(comp))
            frag_symbols = [std_symbols[idx] for idx in comp_indices]
            frag_z = [atomic_numbers[idx] for idx in comp_indices]
            frag_coords = coords_arr[comp_indices]
            frag_formula = generate_chemical_formula(frag_symbols)

            # Mass properties
            masses = np.array([get_atomic_mass(z) for z in frag_z], dtype=float)
            total_mass = float(np.sum(masses))
            if total_mass > 0:
                com = (np.sum(frag_coords * masses[:, np.newaxis], axis=0) / total_mass).tolist()
            else:
                com = np.mean(frag_coords, axis=0).tolist()

            monomer = MonomerSeed(
                fragment_index=frag_idx,
                atom_indices=comp_indices,
                symbols=frag_symbols,
                atomic_numbers=frag_z,
                coordinates=cast(list[list[float]], frag_coords.tolist()),
                formula=frag_formula,
                num_atoms=len(comp_indices),
                center_of_mass=cast(list[float], com),
                total_mass=total_mass
            )
            monomer_seeds.append(monomer)

        summary_lines = [
            f"Topology Classification: {classification} ({num_fragments} fragment{'s' if num_fragments != 1 else ''})",
            f"Routing Target: {routing_target} | Counterpoise Assembly Flag: {counterpoise_flag}",
            f"Total Atoms: {num_atoms} | Covalent Edges: {len(graph_edges)} | Resonance Scale: {scale:.2f}x",
            f"Fragments: {', '.join([f'{m.formula} (N={m.num_atoms})' for m in monomer_seeds])}"
        ]
        summary_str = " | ".join(summary_lines)

        logger.info(summary_str)

        return TopologyAnalysisResult(
            num_atoms=num_atoms,
            num_fragments=num_fragments,
            is_weak_complex=is_weak_complex,
            classification=classification,
            routing_target=routing_target,
            counterpoise_flag=counterpoise_flag,
            monomers=monomer_seeds,
            adjacency_matrix=cast(list[list[int]], a_matrix.tolist()),
            distance_matrix=cast(list[list[float]], d_matrix.tolist()),
            graph_edges=graph_edges,
            resonance_protection_scale=scale,
            summary=summary_str
        )

    def analyze_xyz_string(self, xyz_str: str, resonance_scale: float | None = None) -> TopologyAnalysisResult:
        """Parses and analyzes an XYZ formatted string."""
        symbols, coords, _ = parse_xyz_string(xyz_str)
        return self.analyze_topology(symbols, coords, resonance_scale=resonance_scale)

    def analyze_xyz_file(self, xyz_filepath: str | Path, resonance_scale: float | None = None) -> TopologyAnalysisResult:
        """Reads and analyzes an XYZ file from disk."""
        symbols, coords, _ = parse_xyz_file(xyz_filepath)
        return self.analyze_topology(symbols, coords, resonance_scale=resonance_scale)

    def analyze_atoms(self, atoms: Any, resonance_scale: float | None = None) -> TopologyAnalysisResult:
        """Analyzes an ASE Atoms object or equivalent container."""
        if hasattr(atoms, "get_chemical_symbols") and hasattr(atoms, "get_positions"):
            symbols = list(atoms.get_chemical_symbols())
            coords = np.asarray(atoms.get_positions(), dtype=np.float64)
            return self.analyze_topology(symbols, coords, resonance_scale=resonance_scale)
        elif hasattr(atoms, "symbols") and hasattr(atoms, "positions"):
            symbols = list(atoms.symbols)
            coords = np.asarray(atoms.positions, dtype=np.float64)
            return self.analyze_topology(symbols, coords, resonance_scale=resonance_scale)
        else:
            raise TypeError("Provided atoms object does not implement standard ASE Atoms interface.")


def analyze_molecular_graph(
    symbols: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
    resonance_scale: float = RESONANCE_PROTECTION_SCALE
) -> TopologyAnalysisResult:
    """
    Convenience function for direct molecular graph evaluation and cleavage routing.
    """
    engine = TopologyGraphEngine(resonance_scale=resonance_scale)
    return engine.analyze_topology(symbols, coordinates)
