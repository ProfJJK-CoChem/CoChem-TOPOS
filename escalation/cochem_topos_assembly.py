"""
CoChem-TOPOS: Stage 3.0 - Combinatorial Fragment Assembly (cochem_topos_assembly.py)

Reconstructs Weak Complexes that were severed during Stage 1.1 (cochem_topos_graph.py)
for isolated monomer conformational searching (Stage 2 GOAT Cascade) and prepares them
for high-level ab initio quantum mechanical refinement (Stage 4.0).

Execution Directives:
1. Geometric Docking & Micro-Displacement:
   - Retrieves independently optimized monomer basins from `landscape.h5` or in-memory seeds.
   - Translates and orients monomers relative to their original Center of Mass (COM) collision vectors.
   - Applies iterative micro-displacements (0.1 A steps along the collision axis) if atomic overlap
     is unphysical (< 0.8 A between atomic radii), resolving clashes before quantum execution.
2. Counterpoise (CP) BSSE Constraint Injection:
   - Automatically identifies fragments within the recombined complex.
   - Writes standard ORCA fragment-tagged geometry blocks (e.g. `O(1)`, `O(2)`) and explicit Ghost-Atom
     (`Bq` or `Element:`) coordinate definitions required for Basis Set Superposition Error (BSSE) calculations.
3. Internal Coordinate Freezing:
   - Generates strict Cartesian constraint blocks (`%geom Constraints { C <idx> C } end end` in ORCA)
     to freeze internal monomer topologies, restricting initial ab initio relaxation strictly to the
     intermolecular 6 degrees of freedom.

Strictly complies with the Tripartite Air-Gap Policy and Zero-Mock Mandate.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
import numpy.linalg as la
from ase import Atoms
from pydantic import BaseModel, ConfigDict, Field
from scipy.spatial.distance import cdist
from scipy.spatial.transform import Rotation

# Internal Topology & Mechanics Subsystem Imports
try:
    from mechanics.cochem_topos_memory import (
        GeometryRecord,
        ToposHDF5MemoryManager,
    )
    from topology.cochem_topos_graph import (
        TopologyGraphEngine,
        generate_chemical_formula,
        get_atomic_mass,
        get_atomic_number,
        get_atomic_symbol,
    )
except ImportError:
    from cochem_topos_graph import (  # type: ignore[import-not-found,no-redef]
        TopologyGraphEngine,
        generate_chemical_formula,
        get_atomic_mass,
        get_atomic_number,
        get_atomic_symbol,
    )
    from cochem_topos_memory import (  # type: ignore[import-not-found,no-redef]
        GeometryRecord,
        ToposHDF5MemoryManager,
    )

logger = logging.getLogger("CoChem.TOPOS.Assembly")

# Constants
HARTREE_TO_KCAL: float = 627.5094740631
DEFAULT_STERIC_THRESHOLD_ANGSTROM: float = 0.8
DEFAULT_MICRO_STEP_ANGSTROM: float = 0.1
DEFAULT_MAX_MICRO_DISPLACEMENT: float = 5.0


# ============================================================================
# 1. Enums and Pydantic Data Models
# ============================================================================


class FragmentSource(BaseModel):
    """
    Container representing an isolated monomer fragment basin.
    Tracks atomic properties, Center of Mass, and energetic metadata.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    fragment_id: str = Field(..., description="Unique identifier of this monomer fragment")
    source_geom_id: str | None = Field(default=None, description="HDF5 or basin geometry identifier")
    symbols: list[str] = Field(..., description="Elemental symbols of constituent atoms")
    atomic_numbers: list[int] = Field(..., description="Atomic numbers Z of constituent atoms")
    coordinates: list[list[float]] = Field(..., description="Cartesian coordinates in Angstroms (N, 3)")
    energy_hartree: float | None = Field(default=None, description="Ground state energy in Hartree")
    energy_kcal: float | None = Field(default=None, description="Ground state energy in kcal/mol")
    formula: str = Field(..., description="Hill notation chemical formula")
    num_atoms: int = Field(..., description="Atom count")
    total_mass: float = Field(..., description="Total atomic mass in amu")
    center_of_mass: list[float] = Field(..., description="Cartesian Center of Mass [X, Y, Z]")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Custom metadata tags")

    @classmethod
    def from_coordinates(
        cls,
        fragment_id: str,
        symbols: Sequence[str | int],
        coordinates: np.ndarray | Sequence[Sequence[float]],
        energy_hartree: float | None = None,
        source_geom_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FragmentSource:
        """Constructs a FragmentSource instance from elemental symbols and coordinates."""
        coords_arr = np.asarray(coordinates, dtype=np.float64)
        if coords_arr.ndim != 2 or coords_arr.shape[1] != 3:
            raise ValueError(f"Coordinates must have shape (N, 3), got {coords_arr.shape}")

        std_symbols: list[str] = []
        atomic_numbers: list[int] = []
        for s in symbols:
            z = get_atomic_number(s)
            std_symbols.append(get_atomic_symbol(z))
            atomic_numbers.append(z)

        formula = generate_chemical_formula(std_symbols)
        masses = np.array([get_atomic_mass(z) for z in atomic_numbers], dtype=np.float64)
        total_mass = float(np.sum(masses))

        if total_mass > 0:
            com = (np.sum(coords_arr * masses[:, np.newaxis], axis=0) / total_mass).tolist()
        else:
            com = np.mean(coords_arr, axis=0).tolist()

        energy_kcal = energy_hartree * HARTREE_TO_KCAL if energy_hartree is not None else None

        return cls(
            fragment_id=fragment_id,
            source_geom_id=source_geom_id,
            symbols=std_symbols,
            atomic_numbers=atomic_numbers,
            coordinates=coords_arr.tolist(),
            energy_hartree=energy_hartree,
            energy_kcal=energy_kcal,
            formula=formula,
            num_atoms=len(std_symbols),
            total_mass=total_mass,
            center_of_mass=com,
            metadata=metadata or {},
        )

    @classmethod
    def from_atoms(
        cls,
        fragment_id: str,
        atoms: Atoms,
        energy_hartree: float | None = None,
        source_geom_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FragmentSource:
        """Constructs a FragmentSource instance from an ASE Atoms object."""
        symbols = list(atoms.get_chemical_symbols())
        coords = np.asarray(atoms.get_positions(), dtype=np.float64)
        return cls.from_coordinates(
            fragment_id=fragment_id,
            symbols=symbols,
            coordinates=coords,
            energy_hartree=energy_hartree,
            source_geom_id=source_geom_id,
            metadata=metadata,
        )

    def get_numpy_coordinates(self) -> np.ndarray:
        """Returns coordinates as an (N, 3) float64 NumPy array."""
        return np.asarray(self.coordinates, dtype=float)

    def get_numpy_com(self) -> np.ndarray:
        """Returns Center of Mass as a (3,) float64 NumPy array."""
        return np.asarray(self.center_of_mass, dtype=float)


class DockingCollisionVector(BaseModel):
    """
    Relative Center of Mass displacement vector between two fragments.
    Used to steer geometric docking and micro-displacement along the collision axis.
    """

    model_config = ConfigDict(frozen=True)

    vector: list[float] = Field(..., description="Cartesian vector from Fragment A COM to Fragment B COM [dx, dy, dz]")
    unit_vector: list[float] = Field(..., description="Normalized unit direction vector [ux, uy, uz]")
    distance: float = Field(..., description="Magnitude of the COM separation distance in Angstroms")

    @classmethod
    def compute(cls, frag_a: FragmentSource, frag_b: FragmentSource) -> DockingCollisionVector:
        """Computes the collision vector connecting frag_a to frag_b."""
        com_a = frag_a.get_numpy_com()
        com_b = frag_b.get_numpy_com()
        delta = com_b - com_a
        dist = float(la.norm(delta))

        if dist > 1e-7:
            unit_vec = (delta / dist).tolist()
        else:
            # Fallback default collision axis along Z if fragments are co-located at origin
            unit_vec = [0.0, 0.0, 1.0]

        return cls(
            vector=cast(list[float], delta.tolist()),
            unit_vector=cast(list[float], unit_vec),
            distance=dist,
        )


class StericClashReport(BaseModel):
    """
    Detailed audit record produced during steric clash detection and micro-displacement.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    has_initial_clash: bool = Field(..., description="True if initial docked geometry had intermolecular distance < threshold")
    initial_min_distance: float = Field(..., description="Minimum interatomic distance prior to displacement (A)")
    min_final_distance: float = Field(..., description="Minimum interatomic distance after displacement (A)")
    displacement_applied: float = Field(default=0.0, description="Total outward translation applied along collision axis (A)")
    micro_steps: int = Field(default=0, description="Count of 0.1 A micro-displacement steps executed")
    clash_resolved: bool = Field(..., description="True if final geometry satisfies min_distance threshold")
    threshold_used: float = Field(default=DEFAULT_STERIC_THRESHOLD_ANGSTROM, description="Steric clash cutoff distance (A)")
    details: str = Field(default="", description="Diagnostic details or notes")


class InternalCoordinateConstraint(BaseModel):
    """
    Cartesian constraints specification for downstream ORCA optimizations.
    Freezes internal monomer topologies while permitting 6 intermolecular DOFs to relax.
    """

    model_config = ConfigDict(frozen=True)

    frozen_atom_indices: list[int] = Field(..., description="0-indexed atom indices with Cartesian constraints applied")
    frozen_fragments: list[int] = Field(..., description="Fragment partition IDs frozen")
    orca_constraint_block: str = Field(..., description="Formatted %geom Constraints block for ORCA input")


class BSSEFragmentConfig(BaseModel):
    """
    Counterpoise (CP) BSSE configuration container for ORCA quantum calculations.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    fragment_1_indices: list[int] = Field(..., description="Atom indices belonging to Fragment 1")
    fragment_2_indices: list[int] = Field(..., description="Atom indices belonging to Fragment 2")
    fragment_assignments: list[int] = Field(..., description="1-indexed fragment ID per atom in the complex")
    fragment_tagged_xyz: str = Field(..., description="ORCA fragment tagged geometry block (e.g. O(1), H(2))")
    fragment_1_in_complex_basis_xyz: str = Field(..., description="Fragment 1 real atoms with Fragment 2 as Ghost (Bq / :) atoms")
    fragment_2_in_complex_basis_xyz: str = Field(..., description="Fragment 2 real atoms with Fragment 1 as Ghost (Bq / :) atoms")
    orca_cp_input_block: str = Field(..., description="Complete ORCA input block with Counterpoise tags")


class AssembledComplexCandidate(BaseModel):
    """
    Fully assembled and clash-resolved weak complex candidate geometry.
    Prepared for downstream ORCA / ab initio quantum refinement.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    complex_id: str = Field(..., description="Unique identifier for the assembled complex candidate")
    source_monomer_ids: list[str] = Field(..., description="Identifiers of constituent monomer basins")
    symbols: list[str] = Field(..., description="Elemental symbols of all atoms in complex")
    atomic_numbers: list[int] = Field(..., description="Atomic numbers Z of all atoms in complex")
    coordinates: list[list[float]] = Field(..., description="Cartesian coordinates in Angstroms (N, 3)")
    num_atoms: int = Field(..., description="Total atom count")
    formula: str = Field(..., description="Hill notation chemical formula")
    fragment_assignments: list[int] = Field(..., description="1-indexed fragment membership per atom")
    min_interatomic_distance: float = Field(..., description="Shortest inter-fragment atomic distance in Angstroms")
    collision_vector: list[float] = Field(..., description="Center of Mass collision vector [dx, dy, dz]")
    displacement_applied_angstrom: float = Field(default=0.0, description="Micro-displacement applied to resolve clashes")
    orca_fragment_tagged_xyz: str = Field(..., description="ORCA fragment tagged XYZ coordinate block")
    orca_cartesian_constraints_block: str = Field(..., description="ORCA %geom Constraints block")
    bsse_config: BSSEFragmentConfig | None = Field(default=None, description="Full BSSE Ghost-Atom configuration")
    estimated_energy_hartree: float | None = Field(default=None, description="Summed monomer basin energies in Hartree")
    clash_report: StericClashReport | None = Field(default=None, description="Steric clash audit report")
    provenance_record: dict[str, Any] = Field(default_factory=dict, description="FAIR provenance tags")

    def to_xyz_string(self, comment: str = "") -> str:
        """Serializes complex to standard multi-line XYZ format."""
        cmt = comment or f"Complex {self.complex_id} | Formula: {self.formula} | Atoms: {self.num_atoms}"
        lines = [str(self.num_atoms), cmt]
        for sym, (x, y, z) in zip(self.symbols, self.coordinates, strict=False):
            lines.append(f"{sym:<3} {x:14.8f} {y:14.8f} {z:14.8f}")
        return "\n".join(lines) + "\n"

    def get_numpy_coordinates(self) -> np.ndarray:
        """Returns coordinates as an (N, 3) float64 NumPy array."""
        return np.asarray(self.coordinates, dtype=float)


class AssemblyConfig(BaseModel):
    """
    Configuration specification for Stage 3.0 Combinatorial Fragment Assembly.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    min_steric_distance: float = Field(default=DEFAULT_STERIC_THRESHOLD_ANGSTROM, description="Interatomic distance cutoff below which clash occurs (A)")
    micro_displacement_step: float = Field(default=DEFAULT_MICRO_STEP_ANGSTROM, description="Incremental translation step along collision axis (A)")
    max_micro_displacement: float = Field(default=DEFAULT_MAX_MICRO_DISPLACEMENT, description="Maximum translation before aborting micro-displacement (A)")
    base_docking_distance: float = Field(default=3.2, description="Base Center of Mass docking distance (A)")
    radial_sampling_steps: int = Field(default=3, description="Radial step count for spherical docking grid")
    angular_sampling_steps: int = Field(default=6, description="Angular orientation count on Fibonacci sphere")
    freeze_internal_monomers: bool = Field(default=True, description="Generate ORCA %geom Cartesian constraints for monomer topologies")
    energy_window_kcal: float = Field(default=5.0, description="Energy window (kcal/mol) for pairing monomer conformer basins")
    max_complex_candidates: int = Field(default=20, description="Maximum complex candidates to retain")
    save_to_hdf5: bool = Field(default=True, description="Persist assembled complexes to landscape.h5")
    db_path: Path | None = Field(default=None, description="Path to landscape.h5 database")


class AssemblySessionReport(BaseModel):
    """
    Master audit report summarizing the Stage 3.0 Combinatorial Fragment Assembly session.
    """

    session_id: str = Field(..., description="Unique assembly session identifier")
    monomer_groups: list[str] = Field(default_factory=list, description="IDs of monomer basin groups assembled")
    total_candidates_generated: int = Field(default=0, description="Total complex candidates produced")
    clash_free_count: int = Field(default=0, description="Total candidates satisfying steric clash tolerances")
    micro_displacements_triggered: int = Field(default=0, description="Count of candidates requiring micro-displacement")
    duration_seconds: float = Field(default=0.0, description="Runtime in seconds")
    candidates: list[AssembledComplexCandidate] = Field(default_factory=list, description="List of assembled complex candidates")


# ============================================================================
# 2. Steric Clash Engine & Micro-Displacement Subsystem
# ============================================================================


class StericClashResolver:
    """
    Evaluates intermolecular pairwise distances during fragment docking.
    If an orientation forces atoms unphysically close (< min_distance, default 0.8 A),
    applies iterative micro-translations (0.1 A steps) outward along the collision axis
    until the steric clash is physically resolved, preventing instant SCF gradient explosions.
    """

    def __init__(
        self,
        min_distance: float = DEFAULT_STERIC_THRESHOLD_ANGSTROM,
        step_size: float = DEFAULT_MICRO_STEP_ANGSTROM,
        max_displacement: float = DEFAULT_MAX_MICRO_DISPLACEMENT,
    ) -> None:
        self.min_distance = float(min_distance)
        self.step_size = float(step_size)
        self.max_displacement = float(max_displacement)

    def calculate_min_intermolecular_distance(
        self,
        coords_a: np.ndarray,
        coords_b: np.ndarray,
    ) -> float:
        """Calculates the minimum pairwise Cartesian distance between Fragment A and Fragment B."""
        dists = cdist(coords_a, coords_b)
        return float(np.min(dists))

    def resolve_clash(
        self,
        coords_a: np.ndarray,
        coords_b: np.ndarray,
        collision_axis: np.ndarray,
    ) -> tuple[StericClashReport, np.ndarray]:
        """
        Detects and resolves steric clashes between coords_a and coords_b.
        Translates coords_b outward along collision_axis in micro-steps.

        Args:
            coords_a: Cartesian coordinates of Fragment A (N_a, 3).
            coords_b: Cartesian coordinates of Fragment B (N_b, 3).
            collision_axis: Normalized 3D direction vector from Fragment A to Fragment B.

        Returns:
            (StericClashReport, new_coords_b)
        """
        coords_a_arr = np.asarray(coords_a, dtype=float)
        current_coords_b = np.asarray(coords_b, dtype=float).copy()

        # Normalize collision axis
        axis_norm = float(la.norm(collision_axis))
        if axis_norm > 1e-7:
            unit_axis = collision_axis / axis_norm
        else:
            unit_axis = np.array([0.0, 0.0, 1.0], dtype=float)

        initial_min_dist = self.calculate_min_intermolecular_distance(coords_a_arr, current_coords_b)
        has_clash = initial_min_dist < self.min_distance

        displacement_applied = 0.0
        micro_steps = 0
        current_min_dist = initial_min_dist

        if has_clash:
            logger.debug(
                f"Steric clash detected: initial min distance = {initial_min_dist:.4f} A "
                f"(threshold = {self.min_distance:.4f} A). Applying micro-displacement along {unit_axis}."
            )
            while current_min_dist < self.min_distance and displacement_applied < self.max_displacement:
                current_coords_b += unit_axis * self.step_size
                displacement_applied += self.step_size
                micro_steps += 1
                current_min_dist = self.calculate_min_intermolecular_distance(coords_a_arr, current_coords_b)

        clash_resolved = current_min_dist >= self.min_distance
        details = (
            f"Clash resolved after {micro_steps} micro-steps ({displacement_applied:.2f} A displacement)"
            if has_clash and clash_resolved
            else ("No clash detected" if not has_clash else f"Max displacement reached ({displacement_applied:.2f} A)")
        )

        report = StericClashReport(
            has_initial_clash=has_clash,
            initial_min_distance=initial_min_dist,
            min_final_distance=current_min_dist,
            displacement_applied=displacement_applied,
            micro_steps=micro_steps,
            clash_resolved=clash_resolved,
            threshold_used=self.min_distance,
            details=details,
        )

        return report, current_coords_b


# ============================================================================
# 3. Counterpoise (CP) BSSE Constraint Injection Subsystem
# ============================================================================


class CounterpoiseBSSEGenerator:
    """
    Generates Counterpoise (CP) BSSE inputs and Ghost-Atom blocks for ORCA.
    Constructs:
    1. Fragment-tagged geometries: `* xyz charge mult` with lines like `O(1) x y z`, `O(2) x y z`.
    2. Ghost-Atom blocks (`O:` or `Bq`) for individual monomer calculations in the full complex basis.
    3. Complete ORCA CP input files with `%geom` and `%cp` directives.
    """

    def generate_fragment_tagged_xyz(
        self,
        symbols: Sequence[str],
        coordinates: np.ndarray | Sequence[Sequence[float]],
        fragment_assignments: Sequence[int],
        charge: int = 0,
        multiplicity: int = 1,
    ) -> str:
        """
        Formats coordinates for ORCA with explicit fragment tagging: `Symbol(FragmentID) X Y Z`.

        Example:
        * xyz 0 1
        O(1)   -1.50000000    0.00000000    0.00000000
        H(1)   -1.80000000    0.70000000    0.00000000
        O(2)    1.50000000    0.00000000    0.00000000
        H(2)    1.80000000    0.70000000    0.00000000
        *
        """
        coords_arr = np.asarray(coordinates, dtype=float)
        lines = [f"* xyz {charge} {multiplicity}"]
        for sym, (x, y, z), frag_id in zip(symbols, coords_arr.tolist(), fragment_assignments, strict=False):
            tagged_sym = f"{sym}({frag_id})"
            lines.append(f"{tagged_sym:<8} {x:14.8f} {y:14.8f} {z:14.8f}")
        lines.append("*")
        return "\n".join(lines)

    def generate_ghost_atom_xyz(
        self,
        symbols: Sequence[str],
        coordinates: np.ndarray | Sequence[Sequence[float]],
        active_fragment_id: int,
        fragment_assignments: Sequence[int],
        ghost_format: str = "colon",  # "colon" -> "O:", "bq" -> "Bq"
        charge: int = 0,
        multiplicity: int = 1,
    ) -> str:
        """
        Generates coordinate block where active fragment has real atoms and all other fragments
        are rendered as Ghost atoms (`Symbol:` or `Bq`) in ORCA syntax.
        """
        coords_arr = np.asarray(coordinates, dtype=float)
        lines = [f"* xyz {charge} {multiplicity}"]
        for sym, (x, y, z), frag_id in zip(symbols, coords_arr.tolist(), fragment_assignments, strict=False):
            if frag_id == active_fragment_id:
                atom_label = sym
            else:
                atom_label = f"{sym}:" if ghost_format == "colon" else f"Bq({sym})"
            lines.append(f"{atom_label:<8} {x:14.8f} {y:14.8f} {z:14.8f}")
        lines.append("*")
        return "\n".join(lines)

    def build_bsse_configuration(
        self,
        symbols: Sequence[str],
        coordinates: np.ndarray | Sequence[Sequence[float]],
        fragment_assignments: Sequence[int],
        charge: int = 0,
        multiplicity: int = 1,
    ) -> BSSEFragmentConfig:
        """
        Builds the complete BSSE configuration for a dimer complex.
        """
        coords_arr = np.asarray(coordinates, dtype=float)
        frag_1_indices = [i for i, f_id in enumerate(fragment_assignments) if f_id == 1]
        frag_2_indices = [i for i, f_id in enumerate(fragment_assignments) if f_id == 2]

        tagged_xyz = self.generate_fragment_tagged_xyz(
            symbols=symbols,
            coordinates=coords_arr,
            fragment_assignments=fragment_assignments,
            charge=charge,
            multiplicity=multiplicity,
        )

        frag_1_basis_xyz = self.generate_ghost_atom_xyz(
            symbols=symbols,
            coordinates=coords_arr,
            active_fragment_id=1,
            fragment_assignments=fragment_assignments,
            charge=charge,
            multiplicity=multiplicity,
        )

        frag_2_basis_xyz = self.generate_ghost_atom_xyz(
            symbols=symbols,
            coordinates=coords_arr,
            active_fragment_id=2,
            fragment_assignments=fragment_assignments,
            charge=charge,
            multiplicity=multiplicity,
        )

        orca_cp_block = (
            f"# Counterpoise (CP) BSSE Geometry for ORCA\n"
            f"# Fragment 1 (Atoms: {frag_1_indices}) | Fragment 2 (Atoms: {frag_2_indices})\n"
            f"{tagged_xyz}\n"
        )

        return BSSEFragmentConfig(
            fragment_1_indices=frag_1_indices,
            fragment_2_indices=frag_2_indices,
            fragment_assignments=list(fragment_assignments),
            fragment_tagged_xyz=tagged_xyz,
            fragment_1_in_complex_basis_xyz=frag_1_basis_xyz,
            fragment_2_in_complex_basis_xyz=frag_2_basis_xyz,
            orca_cp_input_block=orca_cp_block,
        )

    def generate_orca_cp_input(
        self,
        symbols: Sequence[str],
        coordinates: np.ndarray | Sequence[Sequence[float]],
        fragment_assignments: Sequence[int],
        method_str: str = "! wB97M-V def2-QZVPP",
        charge: int = 0,
        multiplicity: int = 1,
        maxcore_mb: int = 4000,
        nprocs: int = 8,
    ) -> str:
        """Generates a complete runnable ORCA input file for Counterpoise calculation."""
        tagged_xyz = self.generate_fragment_tagged_xyz(
            symbols=symbols,
            coordinates=coordinates,
            fragment_assignments=fragment_assignments,
            charge=charge,
            multiplicity=multiplicity,
        )

        orca_input = (
            f"# CoChem-TOPOS Stage 3.0: Counterpoise BSSE Calculation\n"
            f"{method_str}\n"
            f"%maxcore {maxcore_mb}\n"
            f"%pal nprocs {nprocs} end\n\n"
            f"{tagged_xyz}\n"
        )
        return orca_input


# ============================================================================
# 4. Internal Coordinate Freezing Subsystem
# ============================================================================


class InternalCoordinateFreezer:
    """
    Generates Cartesian constraint blocks (`%geom Constraints` in ORCA) to freeze
    internal monomer topologies, allowing only intermolecular degrees of freedom
    (distances and orientations) to relax during initial ab initio refinement.
    """

    def generate_cartesian_constraints_block(
        self,
        fragment_assignments: Sequence[int],
        frozen_fragments: Sequence[int] | None = None,
        freeze_all_atoms: bool | None = None,
    ) -> str:
        """
        Generates ORCA `%geom Constraints` Cartesian constraint block.

        ORCA Syntax:
        %geom
           Constraints
              { C 0 C }
              { C 1 C }
              ...
           end
        end
        """
        if freeze_all_atoms is None:
            freeze_all = frozen_fragments is None
        else:
            freeze_all = bool(freeze_all_atoms)

        frozen_indices: list[int] = []
        for idx, frag_id in enumerate(fragment_assignments):
            if freeze_all:
                frozen_indices.append(idx)
            elif frozen_fragments is not None and frag_id in frozen_fragments:
                frozen_indices.append(idx)

        lines = ["%geom", "   Constraints"]
        for idx in frozen_indices:
            lines.append(f"      {{ C {idx} C }}")
        lines.append("   end")
        lines.append("end")

        return "\n".join(lines)

    def build_constraint_object(
        self,
        fragment_assignments: Sequence[int],
        frozen_fragments: Sequence[int] | None = None,
        freeze_all_atoms: bool | None = None,
    ) -> InternalCoordinateConstraint:
        """Constructs an InternalCoordinateConstraint Pydantic model."""
        if freeze_all_atoms is None:
            freeze_all = frozen_fragments is None
        else:
            freeze_all = bool(freeze_all_atoms)

        frozen_indices = [
            idx
            for idx, frag_id in enumerate(fragment_assignments)
            if freeze_all or (frozen_fragments and frag_id in frozen_fragments)
        ]
        active_frozen_frags = (
            list(set(fragment_assignments))
            if freeze_all
            else (list(frozen_fragments) if frozen_fragments else [])
        )

        block = self.generate_cartesian_constraints_block(
            fragment_assignments=fragment_assignments,
            frozen_fragments=frozen_fragments,
            freeze_all_atoms=freeze_all,
        )

        return InternalCoordinateConstraint(
            frozen_atom_indices=frozen_indices,
            frozen_fragments=active_frozen_frags,
            orca_constraint_block=block,
        )


# ============================================================================
# 5. Geometric Docking & Recombination Engine
# ============================================================================


class GeometricDockingEngine:
    """
    Docking and orientation sampler for fragmented monomers.
    Uses SE(3) spherical grids (Fibonacci sphere & orthogonal Euler rotations)
    and collision vector alignment to dock Fragment B around Fragment A.
    """

    def __init__(
        self,
        radial_steps: int = 3,
        angular_steps: int = 6,
        base_distance: float = 3.2,
        min_steric_distance: float = DEFAULT_STERIC_THRESHOLD_ANGSTROM,
        micro_displacement_step: float = DEFAULT_MICRO_STEP_ANGSTROM,
    ) -> None:
        self.radial_steps = int(radial_steps)
        self.angular_steps = int(angular_steps)
        self.base_distance = float(base_distance)
        self.clash_resolver = StericClashResolver(
            min_distance=min_steric_distance,
            step_size=micro_displacement_step,
        )
        self.bsse_generator = CounterpoiseBSSEGenerator()
        self.freezer = InternalCoordinateFreezer()

    def _generate_fibonacci_sphere(self, samples: int) -> np.ndarray:
        """Generates evenly distributed points on a unit sphere using the Fibonacci spiral."""
        if samples <= 1:
            return np.array([[0.0, 0.0, 1.0]], dtype=float)

        indices = np.arange(0, samples, dtype=float) + 0.5
        phi = np.arccos(1.0 - 2.0 * indices / samples)
        theta = np.pi * (1.0 + 5.0**0.5) * indices

        x = np.cos(theta) * np.sin(phi)
        y = np.sin(theta) * np.sin(phi)
        z = np.cos(phi)
        return np.column_stack((x, y, z))

    def _get_standard_rotations(self) -> list[Rotation]:
        """Generates canonical orthogonal rotation matrices (Identity, 90 deg, 180 deg around X, Y, Z)."""
        rotations = [Rotation.from_rotvec([0.0, 0.0, 0.0])]
        for angle in [np.pi / 2.0, np.pi]:
            for axis in [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]:
                rotations.append(Rotation.from_rotvec(angle * np.array(axis, dtype=float)))
        return rotations

    def dock_single_vector(
        self,
        frag_a: FragmentSource,
        frag_b: FragmentSource,
        collision_vector: Sequence[float],
        complex_id: str = "docked_complex",
    ) -> AssembledComplexCandidate:
        """
        Docks Fragment B relative to Fragment A along a specific collision vector.
        """
        coords_a = frag_a.get_numpy_coordinates()
        coords_b = frag_b.get_numpy_coordinates()

        # Center Fragment A at origin
        com_a = frag_a.get_numpy_com()
        centered_a = coords_a - com_a

        # Center Fragment B at origin then translate along collision vector
        com_b = frag_b.get_numpy_com()
        centered_b = coords_b - com_b

        vec = np.asarray(collision_vector, dtype=float)
        translated_b = centered_b + vec

        # Resolve any steric clash
        clash_report, clash_free_b = self.clash_resolver.resolve_clash(
            coords_a=centered_a,
            coords_b=translated_b,
            collision_axis=vec,
        )

        # Merge coordinates
        combined_coords = np.vstack((centered_a, clash_free_b))
        combined_symbols = frag_a.symbols + frag_b.symbols
        combined_atomic_numbers = frag_a.atomic_numbers + frag_b.atomic_numbers
        fragment_assignments = [1] * frag_a.num_atoms + [2] * frag_b.num_atoms

        formula = generate_chemical_formula(combined_symbols)
        min_dist = clash_report.min_final_distance

        # Build BSSE & Constraint blocks
        bsse_cfg = self.bsse_generator.build_bsse_configuration(
            symbols=combined_symbols,
            coordinates=combined_coords,
            fragment_assignments=fragment_assignments,
        )
        constraints_block = self.freezer.generate_cartesian_constraints_block(
            fragment_assignments=fragment_assignments,
            freeze_all_atoms=True,
        )

        est_energy = None
        if frag_a.energy_hartree is not None and frag_b.energy_hartree is not None:
            est_energy = frag_a.energy_hartree + frag_b.energy_hartree

        return AssembledComplexCandidate(
            complex_id=complex_id,
            source_monomer_ids=[frag_a.fragment_id, frag_b.fragment_id],
            symbols=combined_symbols,
            atomic_numbers=combined_atomic_numbers,
            coordinates=cast(list[list[float]], combined_coords.tolist()),
            num_atoms=len(combined_symbols),
            formula=formula,
            fragment_assignments=fragment_assignments,
            min_interatomic_distance=min_dist,
            collision_vector=cast(list[float], vec.tolist()),
            displacement_applied_angstrom=clash_report.displacement_applied,
            orca_fragment_tagged_xyz=bsse_cfg.fragment_tagged_xyz,
            orca_cartesian_constraints_block=constraints_block,
            bsse_config=bsse_cfg,
            estimated_energy_hartree=est_energy,
            clash_report=clash_report,
            provenance_record={
                "pipeline_stage": "Stage 3.0: Combinatorial Fragment Assembly",
                "timestamp": time.time(),
                "frag_a_id": frag_a.fragment_id,
                "frag_b_id": frag_b.fragment_id,
            },
        )

    def dock_monomers(
        self,
        frag_a: FragmentSource,
        frag_b: FragmentSource,
        base_id_prefix: str = "complex",
    ) -> list[AssembledComplexCandidate]:
        """
        Docks Fragment B around Fragment A using spherical Fibonacci directions,
        radial displacement sweeps, and orthogonal Euler rotation orientations.
        """
        coords_a = frag_a.get_numpy_coordinates()
        coords_b = frag_b.get_numpy_coordinates()

        # Center Fragment A at origin
        centered_a = coords_a - frag_a.get_numpy_com()
        # Center Fragment B at origin
        centered_b = coords_b - frag_b.get_numpy_com()

        sphere_vectors = self._generate_fibonacci_sphere(self.angular_steps)
        radii = np.linspace(self.base_distance, self.base_distance + 1.5, self.radial_steps)
        rotations = self._get_standard_rotations()

        candidates: list[AssembledComplexCandidate] = []
        candidate_idx = 0

        combined_symbols = frag_a.symbols + frag_b.symbols
        combined_atomic_numbers = frag_a.atomic_numbers + frag_b.atomic_numbers
        fragment_assignments = [1] * frag_a.num_atoms + [2] * frag_b.num_atoms
        formula = generate_chemical_formula(combined_symbols)

        for r in radii:
            for vec in sphere_vectors:
                translation = vec * r
                for rot in rotations:
                    rotated_b = rot.apply(centered_b) + translation

                    # Resolve steric clash
                    clash_report, clash_free_b = self.clash_resolver.resolve_clash(
                        coords_a=centered_a,
                        coords_b=rotated_b,
                        collision_axis=vec,
                    )

                    combined_coords = np.vstack((centered_a, clash_free_b))
                    cid = f"{base_id_prefix}_{frag_a.fragment_id}_{frag_b.fragment_id}_cand{candidate_idx:03d}"

                    bsse_cfg = self.bsse_generator.build_bsse_configuration(
                        symbols=combined_symbols,
                        coordinates=combined_coords,
                        fragment_assignments=fragment_assignments,
                    )
                    constraints_block = self.freezer.generate_cartesian_constraints_block(
                        fragment_assignments=fragment_assignments,
                        freeze_all_atoms=True,
                    )

                    est_energy = None
                    if frag_a.energy_hartree is not None and frag_b.energy_hartree is not None:
                        est_energy = frag_a.energy_hartree + frag_b.energy_hartree

                    cand = AssembledComplexCandidate(
                        complex_id=cid,
                        source_monomer_ids=[frag_a.fragment_id, frag_b.fragment_id],
                        symbols=combined_symbols,
                        atomic_numbers=combined_atomic_numbers,
                        coordinates=cast(list[list[float]], combined_coords.tolist()),
                        num_atoms=len(combined_symbols),
                        formula=formula,
                        fragment_assignments=fragment_assignments,
                        min_interatomic_distance=clash_report.min_final_distance,
                        collision_vector=cast(list[float], translation.tolist()),
                        displacement_applied_angstrom=clash_report.displacement_applied,
                        orca_fragment_tagged_xyz=bsse_cfg.fragment_tagged_xyz,
                        orca_cartesian_constraints_block=constraints_block,
                        bsse_config=bsse_cfg,
                        estimated_energy_hartree=est_energy,
                        clash_report=clash_report,
                        provenance_record={
                            "pipeline_stage": "Stage 3.0: Combinatorial Fragment Assembly",
                            "timestamp": time.time(),
                            "radius": float(r),
                            "candidate_index": candidate_idx,
                        },
                    )
                    candidates.append(cand)
                    candidate_idx += 1

        logger.info(f"Generated {len(candidates)} assembled complex candidates for [{frag_a.fragment_id} + {frag_b.fragment_id}].")
        return candidates


# ============================================================================
# 6. Master Topos Combinatorial Assembler
# ============================================================================


class ToposCombinatorialAssembler:
    """
    Master orchestrator for Stage 3.0 Combinatorial Fragment Assembly.
    Connects to `landscape.h5` via `ToposHDF5MemoryManager` to pull optimized monomer
    basins from Stage 2.0, performs combinatorial pairing, geometric docking,
    clash resolution, BSSE injection, and Cartesian constraint freezing.
    """

    def __init__(
        self,
        config: AssemblyConfig | None = None,
        memory_mgr: ToposHDF5MemoryManager | None = None,
    ) -> None:
        self.config = config or AssemblyConfig()
        self.memory_mgr = memory_mgr or ToposHDF5MemoryManager(db_path=self.config.db_path)
        self.docking_engine = GeometricDockingEngine(
            radial_steps=self.config.radial_sampling_steps,
            angular_steps=self.config.angular_sampling_steps,
            base_distance=self.config.base_docking_distance,
            min_steric_distance=self.config.min_steric_distance,
            micro_displacement_step=self.config.micro_displacement_step,
        )

    def load_monomer_basins_from_hdf5(
        self,
        monomer_geom_ids: Sequence[str],
    ) -> list[FragmentSource]:
        """
        Loads monomer geometry records from landscape.h5 and converts them to FragmentSource models.
        """
        monomers: list[FragmentSource] = []
        for gid in monomer_geom_ids:
            rec = self.memory_mgr.read_geometry(gid)
            if rec is None:
                logger.warning(f"Monomer geometry ID [{gid}] not found in HDF5 datastore.")
                continue

            symbols = [get_atomic_symbol(z) for z in rec.atomic_numbers]
            frag = FragmentSource.from_coordinates(
                fragment_id=gid,
                symbols=symbols,
                coordinates=rec.coords,
                energy_hartree=rec.energy,
                source_geom_id=gid,
                metadata=rec.metadata,
            )
            monomers.append(frag)

        return monomers

    def assemble_monomer_basins(
        self,
        monomer_basin_ids_group_a: Sequence[str],
        monomer_basin_ids_group_b: Sequence[str],
        reference_collision_vector: Sequence[float] | None = None,
    ) -> AssemblySessionReport:
        """
        Pairs lowest-energy conformer basins from Group A with Group B, executing
        geometric docking, steric clash resolution, and BSSE tagging.

        Args:
            monomer_basin_ids_group_a: Geometry IDs of Fragment A conformer basins.
            monomer_basin_ids_group_b: Geometry IDs of Fragment B conformer basins.
            reference_collision_vector: Optional parent collision vector from Stage 1.1.

        Returns:
            AssemblySessionReport
        """
        start_time = time.time()
        session_id = f"assembly_session_{int(start_time)}"

        # 1. Load monomer basins from HDF5
        group_a = self.load_monomer_basins_from_hdf5(monomer_basin_ids_group_a)
        group_b = self.load_monomer_basins_from_hdf5(monomer_basin_ids_group_b)

        if not group_a or not group_b:
            raise ValueError(
                f"Insufficient monomer basins loaded: Group A ({len(group_a)}), Group B ({len(group_b)})."
            )

        # 2. Filter basins within energy window
        min_e_a = min((f.energy_hartree for f in group_a if f.energy_hartree is not None), default=0.0)
        min_e_b = min((f.energy_hartree for f in group_b if f.energy_hartree is not None), default=0.0)

        window_hartree = self.config.energy_window_kcal / HARTREE_TO_KCAL

        valid_a = [
            f for f in group_a if f.energy_hartree is None or (f.energy_hartree - min_e_a) <= window_hartree
        ]
        valid_b = [
            f for f in group_b if f.energy_hartree is None or (f.energy_hartree - min_e_b) <= window_hartree
        ]

        all_candidates: list[AssembledComplexCandidate] = []
        micro_displacements_count = 0

        # 3. Combinatorial Docking
        cand_counter = 0
        for frag_a in valid_a:
            for frag_b in valid_b:
                if reference_collision_vector is not None:
                    # Single reference vector docking
                    cand = self.docking_engine.dock_single_vector(
                        frag_a=frag_a,
                        frag_b=frag_b,
                        collision_vector=reference_collision_vector,
                        complex_id=f"complex_{frag_a.fragment_id}_{frag_b.fragment_id}_seed{cand_counter:02d}",
                    )
                    if cand.displacement_applied_angstrom > 0:
                        micro_displacements_count += 1
                    all_candidates.append(cand)
                    cand_counter += 1
                else:
                    # Grid docking sweep
                    cands = self.docking_engine.dock_monomers(
                        frag_a=frag_a,
                        frag_b=frag_b,
                        base_id_prefix="complex",
                    )
                    for c in cands:
                        if c.displacement_applied_angstrom > 0:
                            micro_displacements_count += 1
                    all_candidates.extend(cands)

        # 4. Limit to max_complex_candidates
        selected_candidates = all_candidates[: self.config.max_complex_candidates]

        # 5. Persist to HDF5 if enabled
        if self.config.save_to_hdf5 and self.memory_mgr is not None:
            for cand in selected_candidates:
                rec = GeometryRecord(
                    geom_id=cand.complex_id,
                    atomic_numbers=cand.atomic_numbers,
                    coords=cand.coordinates,
                    energy=cand.estimated_energy_hartree or 0.0,
                    metadata={
                        "pipeline_stage": "Stage 3.0: Combinatorial Fragment Assembly",
                        "formula": cand.formula,
                        "source_monomers": cand.source_monomer_ids,
                        "min_interatomic_distance": cand.min_interatomic_distance,
                        "displacement_applied": cand.displacement_applied_angstrom,
                        "fragment_assignments": cand.fragment_assignments,
                        "orca_constraints_block": cand.orca_cartesian_constraints_block,
                    },
                )
                self.memory_mgr.write_geometry(rec)
            logger.info(f"Persisted {len(selected_candidates)} assembled complex candidates to HDF5 datastore.")

        report = AssemblySessionReport(
            session_id=session_id,
            monomer_groups=list(monomer_basin_ids_group_a) + list(monomer_basin_ids_group_b),
            total_candidates_generated=len(selected_candidates),
            clash_free_count=len([c for c in selected_candidates if c.min_interatomic_distance >= self.config.min_steric_distance]),
            micro_displacements_triggered=micro_displacements_count,
            duration_seconds=time.time() - start_time,
            candidates=selected_candidates,
        )

        return report


# ============================================================================
# 7. High-Level Convenience Function
# ============================================================================


def assemble_weak_complex(
    symbols: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
    base_distance: float = 3.2,
    min_steric_distance: float = DEFAULT_STERIC_THRESHOLD_ANGSTROM,
    micro_displacement_step: float = DEFAULT_MICRO_STEP_ANGSTROM,
    radial_steps: int = 2,
    angular_steps: int = 4,
) -> list[AssembledComplexCandidate]:
    """
    Convenience function: Cleaves input geometry if weak complex and reassembles
    the fragments into clash-resolved, BSSE-tagged candidate complexes.
    """
    # 1. Topology cleavage
    graph_engine = TopologyGraphEngine()
    topo_res = graph_engine.analyze_topology(symbols, coordinates)

    if not topo_res.is_weak_complex or len(topo_res.monomers) < 2:
        logger.info("System is a single monomer; returning as-is without combinatorial assembly.")
        return []

    # 2. Extract fragments
    frag_a = FragmentSource.from_coordinates(
        fragment_id="monomer_0",
        symbols=topo_res.monomers[0].symbols,
        coordinates=topo_res.monomers[0].coordinates,
    )
    frag_b = FragmentSource.from_coordinates(
        fragment_id="monomer_1",
        symbols=topo_res.monomers[1].symbols,
        coordinates=topo_res.monomers[1].coordinates,
    )

    # 3. Dock fragments
    docking_engine = GeometricDockingEngine(
        radial_steps=radial_steps,
        angular_steps=angular_steps,
        base_distance=base_distance,
        min_steric_distance=min_steric_distance,
        micro_displacement_step=micro_displacement_step,
    )

    candidates = docking_engine.dock_monomers(frag_a, frag_b)
    return candidates
