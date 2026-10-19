"""CoChem-TOPOS Chemical Perception Subsystem: Prototropic Tautomer Enumeration.

Pure in-memory BFS state traversal, directional SMIRKS transforms, Patterson scoring,
BSSE ghost-atom exclusion, dynamic Mendeleev atomic masses and covalent radii,
structural canonicalization and thread-safe HDF5 persistence. Quantitative
thermodynamics requires matched native calculations in the verified provider.
"""

from __future__ import annotations

import collections
import concurrent.futures
import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import filelock
import h5py
import numpy as np
from cochem_base.physics.isotopes import get_isotope_mass
from cochem_base.physics.nuclide_resolver import get_element, parse_nuclide
from mendeleev import element
from pydantic import BaseModel, ConfigDict, Field, model_validator
from rdkit import Chem
from rdkit.Chem import AllChem

logger = logging.getLogger(__name__)

# Enforce JAX 64-bit precision invariant per Method Matrix
os.environ["JAX_ENABLE_X64"] = "True"

# Intra-process lock for HDF5 persistence (safeguards non-threadsafe h5py builds)
_HDF5_THREAD_LOCK = threading.Lock()


# ============================================================================
# DOMAIN EXCEPTION HIERARCHY
# ============================================================================


class ToposPerceptionError(Exception):
    """Base exception for chemical perception and tautomer failures [D]."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class TautomerEnumerationTimeoutError(ToposPerceptionError):
    """Raised when tautomer state space traversal exceeds execution timeout ceiling [D]."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class TautomerCombinatorialLimitExceededError(ToposPerceptionError):
    """Raised when generated tautomer states exceed configured bounds in 'raise' mode [D]."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class ValenceConservationError(ToposPerceptionError):
    """Raised when a prototropic transform violates octet or valency conservation [D]."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class InvalidTopologyInputError(ToposPerceptionError):
    """Raised when input molecular structure is unparseable or topologically malformed [D]."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class TautomerCanonicalizationError(ToposPerceptionError):
    """Raised when canonical tautomer selection or fixed-H InChIKey hashing fails [D]."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class TautomerPersistenceError(ToposPerceptionError):
    """Raised when HDF5 serialization or deserialization fails [D]."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class TautomerStorageLockTimeoutError(ToposPerceptionError):
    """Raised when acquiring cross-platform filelock exceeds timeout ceiling [D]."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class QuantumChemistryHandshakeError(ToposPerceptionError):
    """Raised when downstream 3D embedding or GFN2-xTB pre-filtering fails [D]."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class GhostAtomSanitizationError(ToposPerceptionError):
    """Raised when BSSE ghost atoms cannot be harmonized with topology contracts [D]."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class TautomerThermodynamicsUnavailableError(QuantumChemistryHandshakeError):
    """Structural candidates do not have matched native thermodynamic evidence."""


# ============================================================================
# PYDANTIC V2 DOMAIN MODELS
# ============================================================================


class TopologyInput(BaseModel):
    """Immutable molecular topology record ingesting 2D/3D inputs with BSSE ghost handling [M][D]."""

    model_config = ConfigDict(frozen=True)

    molecule_id: str = Field(..., description="Unique alphanumeric identifier for the molecule")
    smiles: Optional[str] = Field(default=None, description="Input SMILES string")
    elements: List[str] = Field(..., min_length=1, description="Elemental symbols")
    atomic_numbers: List[int] = Field(..., min_length=1, description="IUPAC atomic numbers Z")
    coordinates: Optional[List[Tuple[float, float, float]]] = Field(
        default=None, description="Cartesian 3D coordinates in Angstroms (x, y, z)"
    )
    bonds: List[Tuple[int, int, float]] = Field(
        default_factory=list, description="Edges: (idx_i, idx_j, order)"
    )
    formal_charges: List[int] = Field(default_factory=list, description="Formal charge per atom")
    masses: Optional[List[float]] = Field(
        default=None, description="Atomic masses dynamically queried via mendeleev"
    )
    is_ghost: List[bool] = Field(
        default_factory=list, description="Mask identifying BSSE ghost atoms"
    )

    @model_validator(mode="before")
    @classmethod
    def pre_validate_arrays_and_defaults(cls, data: Any) -> Any:
        """Pre-validation hook to align default masks, formal charges, and dynamic masses [M][D]."""
        if not isinstance(data, dict):
            return data

        elements_list = data.get("elements", [])
        n_atoms = len(elements_list)
        atomic_numbers = data.get("atomic_numbers", [])

        # Auto-detect ghost atoms: Z=0 or symbol in {"GH", "BQ", "X"}
        if "is_ghost" not in data or not data["is_ghost"]:
            ghost_symbols = {"GH", "BQ", "X"}
            data["is_ghost"] = [
                (z == 0 or sym.upper() in ghost_symbols)
                for z, sym in zip(atomic_numbers, elements_list)  # noqa: B905 - preserve transferred zip semantics
            ] if len(atomic_numbers) == n_atoms else [False] * n_atoms

        if "formal_charges" not in data or not data["formal_charges"]:
            data["formal_charges"] = [0] * n_atoms

        # Dynamic Mendeleev mass retrieval mandate: non-ghosts queried, ghosts get 0.0 without call
        if "masses" not in data or data.get("masses") is None:
            if len(atomic_numbers) == n_atoms:
                computed_masses: List[float] = []
                for z, ghost in zip(atomic_numbers, data["is_ghost"]):  # noqa: B905 - preserve transferred zip semantics
                    if ghost or z == 0:
                        computed_masses.append(0.0)
                    else:
                        computed_masses.append(get_isotope_mass(elements_list[len(computed_masses)]))
                data["masses"] = computed_masses

        return data

    @model_validator(mode="after")
    def validate_integrity(self) -> "TopologyInput":
        """Post-validation enforcing coordinate integrity, array lengths, and bond bounds [M]."""
        n_atoms = len(self.elements)
        if not self.smiles and not self.coordinates and not self.bonds:
            raise ValueError("At least one of smiles, coordinates, or explicit bonds must be provided")

        if self.coordinates is not None and len(self.coordinates) != n_atoms:
            raise ValueError(f"coordinates length {len(self.coordinates)} != elements length {n_atoms}")

        if len(self.atomic_numbers) != n_atoms:
            raise ValueError(f"atomic_numbers length {len(self.atomic_numbers)} != elements length {n_atoms}")

        if len(self.is_ghost) != n_atoms:
            raise ValueError(f"is_ghost length {len(self.is_ghost)} != elements length {n_atoms}")

        if len(self.formal_charges) != n_atoms:
            raise ValueError(f"formal_charges length {len(self.formal_charges)} != elements length {n_atoms}")

        if self.masses is not None and len(self.masses) != n_atoms:
            raise ValueError(f"masses length {len(self.masses)} != elements length {n_atoms}")

        for idx_i, idx_j, order in self.bonds:
            if not (0 <= idx_i < n_atoms and 0 <= idx_j < n_atoms):
                raise ValueError(f"Bond ({idx_i}, {idx_j}) references out-of-bounds atom index for n_atoms={n_atoms}")
            if idx_i == idx_j:
                raise ValueError(f"Self-referential bond ({idx_i}, {idx_j}) detected")
            if order <= 0.0 or order > 4.0:
                raise ValueError(f"Invalid bond order {order} for bond ({idx_i}, {idx_j})")

        return self


class TautomerCandidate(BaseModel):
    """Immutable record representing an enumerated tautomeric state [M][D]."""

    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(..., description="Unique candidate hash")
    smiles: str = Field(..., min_length=1, description="Canonical SMILES of the tautomer")
    inchi_key: str = Field(..., min_length=27, max_length=27, description="Standard InChIKey (27 chars)")
    fixed_h_inchi_key: str = Field(..., min_length=27, max_length=27, description="Fixed-H InChIKey (27 chars)")
    canonical_score: float = Field(..., description="Patterson structural canonicalization heuristic; not an energy or population")
    relative_energy_kcal_mol: None = Field(default=None, description="No native thermodynamic evidence is attached to structural enumeration")
    unvalidated_legacy_energy_kcal_mol: Optional[float] = Field(default=None, allow_inf_nan=False,
        description="Imported historical number with unknown method/provenance; excluded from ranking and populations")
    is_canonical: bool = Field(default=False, description="Deterministic structural canonical tautomer; does not identify the thermodynamic minimum")
    transform_depth: int = Field(..., ge=0, description="Number of elementary prototropic shifts from parent")
    transform_history: List[str] = Field(default_factory=list, description="Sequence of SMIRKS applied")


class TautomerEnumerationConfig(BaseModel):
    """Configuration parameters and combinatorial ceilings for tautomer exploration [M][D]."""

    model_config = ConfigDict(frozen=True)

    max_tautomers: int = Field(default=500, ge=1, le=10000, description="Max unique tautomers before truncation")
    max_transform_depth: int = Field(default=6, ge=1, le=20, description="Max search depth from parent topology")
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0, description="Process-level timeout limit in seconds")
    energy_cutoff_kcal_mol: float = Field(default=15.0, ge=0.0, description="Thermodynamic exclusion ceiling")
    truncation_policy: Literal["raise", "truncate"] = Field(
        default="truncate",
        description="Behavior when max_tautomers limit is reached"
    )


class TautomerEnsemble(BaseModel):
    """Validated ensemble of enumerated tautomer candidates for a parent molecule [M][D]."""

    model_config = ConfigDict(frozen=True)

    parent_id: str = Field(..., description="Parent molecule identifier")
    canonical_tautomer_id: str = Field(..., description="ID of designated canonical tautomer")
    total_generated: int = Field(..., ge=1, description="Total unique tautomers identified")
    candidates: List[TautomerCandidate] = Field(..., min_length=1, description="List of generated tautomer candidates")
    execution_duration_seconds: float = Field(..., ge=0.0, description="Wall-clock runtime for enumeration")
    acceptance_scope: Literal["structural_enumeration_only"] = "structural_enumeration_only"
    thermodynamic_validation_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_ensemble_consistency(self) -> "TautomerEnsemble":
        """Ensures ensemble internal consistency: counts, canonical pointer, and uniqueness [M]."""
        if len(self.candidates) != self.total_generated:
            raise ValueError(f"Candidate count {len(self.candidates)} != total_generated {self.total_generated}")

        candidate_map = {c.candidate_id: c for c in self.candidates}
        if self.canonical_tautomer_id not in candidate_map:
            raise ValueError(f"canonical_tautomer_id '{self.canonical_tautomer_id}' not found in candidates")

        canonical_count = sum(1 for c in self.candidates if c.is_canonical)
        if canonical_count != 1:
            raise ValueError(f"Exactly one candidate must have is_canonical=True; found {canonical_count}")

        if not candidate_map[self.canonical_tautomer_id].is_canonical:
            raise ValueError("Candidate matching canonical_tautomer_id must have is_canonical=True")

        return self


# ============================================================================
# DIRECTIONAL SMIRKS TRANSFORM LIBRARY
# ============================================================================

PROTOTROPIC_SMIRKS: Dict[str, str] = {
    # 1,3-Prototropic Shifts
    "keto_enol_fwd": "[O,S,Se,Te:1]=[#6:2]-[#6:3]-[#1:4]>>[#1:4]-[O,S,Se,Te:1]-[#6:2]=[#6:3]",
    "keto_enol_rev": "[#1:4]-[O,S,Se,Te:1]-[#6:2]=[#6:3]>>[O,S,Se,Te:1]=[#6:2]-[#6:3]-[#1:4]",
    "lactam_lactim_fwd": "[O,S:1]=[#6:2]-[#7:3]-[#1:4]>>[#1:4]-[O,S:1]-[#6:2]=[#7:3]",
    "lactam_lactim_rev": "[#1:4]-[O,S:1]-[#6:2]=[#7:3]>>[O,S:1]=[#6:2]-[#7:3]-[#1:4]",
    "heteroaromatic_lactam_lactim_fwd": "[O,S:1]=[c,C:2]:[n:3]-[#1:4]>>[#1:4]-[O,S:1]-[c:2]:[n:3]",
    "heteroaromatic_lactam_lactim_rev": "[#1:4]-[O,S:1]-[c,C:2]:[n:3]>>[O,S:1]=[c,C:2]:[n:3]-[#1:4]",
    "amidine_fwd": "[#7:1]=[#6:2]-[#7:3]-[#1:4]>>[#1:4]-[#7:1]-[#6:2]=[#7:3]",
    "amidine_rev": "[#1:4]-[#7:1]-[#6:2]=[#7:3]>>[#7:1]=[#6:2]-[#7:3]-[#1:4]",
    "imine_enamine_fwd": "[#7:1]=[#6:2]-[#6:3]-[#1:4]>>[#1:4]-[#7:1]-[#6:2]=[#6:3]",
    "imine_enamine_rev": "[#1:4]-[#7:1]-[#6:2]=[#6:3]>>[#7:1]=[#6:2]-[#6:3]-[#1:4]",
    "nitroso_oxime_fwd": "[O:1]=[#7:2]-[#6:3]-[#1:4]>>[#1:4]-[O:1]-[#7:2]=[#6:3]",
    "nitroso_oxime_rev": "[#1:4]-[O:1]-[#7:2]=[#6:3]>>[O:1]=[#7:2]-[#6:3]-[#1:4]",
    # 1,5-Prototropic Shifts (Conjugated & Vinylogous Systems)
    "vinylogous_keto_enol_fwd": "[O,S:1]=[#6:2]-[#6:3]=[#6:4]-[#6:5]-[#1:6]>>[#1:6]-[O,S:1]-[#6:2]=[#6:3]-[#6:4]=[#6:5]",
    "vinylogous_keto_enol_rev": "[#1:6]-[O,S:1]-[#6:2]=[#6:3]-[#6:4]=[#6:5]>>[O,S:1]=[#6:2]-[#6:3]=[#6:4]-[#6:5]-[#1:6]",
    "vinylogous_amide_fwd": "[O,S:1]=[#6:2]-[#6:3]=[#6:4]-[#7:5]-[#1:6]>>[#1:6]-[O,S:1]-[#6:2]=[#6:3]-[#6:4]=[#7:5]",
    "vinylogous_amide_rev": "[#1:6]-[O,S:1]-[#6:2]=[#6:3]-[#6:4]-[#7:5]>>[O,S:1]=[#6:2]-[#6:3]=[#6:4]-[#7:5]-[#1:6]",
    # Heterocyclic Annular Shifts
    "diaza_1_3": "[#1:6]-[n:1]1:[c,n:2]:[n:3]:[c,n:4]:[c,n:5]1>>[n:1]1:[c,n:2]:[n:3](-[#1:6]):[c,n:4]:[c,n:5]1",
    "diaza_1_2": "[#1:6]-[n:1]1:[n:2]:[c,n:3]:[c,n:4]:[c,n:5]1>>[n:1]1:[n:2](-[#1:6]):[c,n:3]:[c,n:4]:[c,n:5]1",
}


# ============================================================================
# CANONICAL PATTERSON SCORING
# ============================================================================


def compute_patterson_score(mol: Chem.Mol) -> float:
    """Computes heuristic Patterson canonical score for tautomer ranking [M][D].

    Scoring criteria:
    - +100 per fully aromatic ring
    - +50 per keto/carbonyl group over enol (non-phenolic context)
    - +25 per lactam over lactim group
    - -50 per aci-nitro group
    - -100 per isolated charge pair / zwitterionic separation
    """
    score = 0.0

    # 1. Fully aromatic rings (+100 each)
    ssr = Chem.GetSymmSSSR(mol)
    for ring_atom_indices in ssr:
        if all(mol.GetAtomWithIdx(idx).GetIsAromatic() for idx in ring_atom_indices):
            score += 100.0

    # 2. Keto / carbonyl group over enol (+50 each)
    # Carbonyl [#6;!$([#6](=O)[O,N,S,F,Cl,Br,I])](=O)
    keto_smarts = "[#6;!$([#6](=O)[O,N,S,F,Cl,Br,I])](=O)"
    keto_query = Chem.MolFromSmarts(keto_smarts)
    if keto_query is not None:
        score += 50.0 * len(mol.GetSubstructMatches(keto_query))

    # 3. Lactam over lactim group (+25 each)
    lactam_smarts = "[O,S]=[#6,c;R]-[n,N;R;!H0]"
    lactam_query = Chem.MolFromSmarts(lactam_smarts)
    if lactam_query is not None:
        score += 25.0 * len(mol.GetSubstructMatches(lactam_query))

    # 4. Aci-nitro group (-50 each)
    aci_smarts = "[#6]=[N+](-[O-])[O;H1]"
    aci_query = Chem.MolFromSmarts(aci_smarts)
    if aci_query is not None:
        score -= 50.0 * len(mol.GetSubstructMatches(aci_query))

    # 5. Isolated charge or zwitterionic separation (-100 per separated pair = -50 per charge)
    total_abs_charge = sum(abs(a.GetFormalCharge()) for a in mol.GetAtoms())
    score -= 50.0 * float(total_abs_charge)

    return score


# ============================================================================
# HELPER: GRAPH CONSTRUCTION AND SANITIZATION
# ============================================================================


def _build_rdkit_mol_from_topology(top: TopologyInput) -> Chem.Mol:
    """Builds an RDKit Mol object from TopologyInput, honoring dynamic covalent radii [M][D]."""
    if top.smiles:
        mol = Chem.MolFromSmiles(top.smiles)
        if mol is None:
            raise InvalidTopologyInputError(f"Failed to parse SMILES '{top.smiles}'")
        return mol

    n_atoms = len(top.elements)
    em = Chem.EditableMol(Chem.Mol())

    # Add atoms
    for i in range(n_atoms):
        z = top.atomic_numbers[i]
        ghost = top.is_ghost[i]
        atom = Chem.Atom(0 if (ghost or z == 0) else int(z))
        atom.SetFormalCharge(top.formal_charges[i])
        if not ghost and z != 0:
            nuclear = parse_nuclide(top.elements[i])
            if int(get_element(nuclear.symbol).atomic_number) != z:
                raise InvalidTopologyInputError("Nuclear label differs from the explicit atomic number")
            if nuclear.mass_number is not None:
                atom.SetIsotope(nuclear.mass_number)
        em.AddAtom(atom)

    if top.bonds:
        # Explicit bond connectivity
        for idx_i, idx_j, order in top.bonds:
            if order >= 3.5:
                btype = Chem.BondType.QUADRUPLE
            elif order >= 2.5:
                btype = Chem.BondType.TRIPLE
            elif order >= 1.75:
                btype = Chem.BondType.DOUBLE
            elif order >= 1.25:
                btype = Chem.BondType.AROMATIC
            else:
                btype = Chem.BondType.SINGLE
            em.AddBond(idx_i, idx_j, btype)
        mol = em.GetMol()
    elif top.coordinates is not None:
        # Reconstruct connectivity from 3D Cartesian coordinates using Pyykkö covalent radii
        coords_arr = np.asarray(top.coordinates, dtype=np.float64)
        covalent_radii: List[float] = []
        for i in range(n_atoms):
            if top.is_ghost[i] or top.atomic_numbers[i] == 0:
                covalent_radii.append(0.0)
            else:
                el = element(int(top.atomic_numbers[i]))
                cov_pm = el.covalent_radius_pyykko
                if cov_pm is None or not np.isfinite(cov_pm) or cov_pm <= 0:
                    raise InvalidTopologyInputError("A dynamically queried Pyykko radius is required; no guessed radius is permitted")
                covalent_radii.append(float(cov_pm) / 100.0)

        for i in range(n_atoms):
            if top.is_ghost[i] or top.atomic_numbers[i] == 0:
                continue
            for j in range(i + 1, n_atoms):
                if top.is_ghost[j] or top.atomic_numbers[j] == 0:
                    continue
                dist = float(np.linalg.norm(coords_arr[i] - coords_arr[j]))
                r0 = covalent_radii[i] + covalent_radii[j]
                if not np.isfinite(dist) or dist <= .40:
                    raise InvalidTopologyInputError("Real nuclei require finite non-overlapping input coordinates")
                if dist <= 1.28 * r0:
                    em.AddBond(i, j, Chem.BondType.SINGLE)
        mol = em.GetMol()
    else:
        raise InvalidTopologyInputError("TopologyInput lacks smiles, explicit bonds, and coordinates")

    try:
        Chem.SanitizeMol(mol)
    except Exception as exc:
        raise InvalidTopologyInputError(f"RDKit sanitization failed on constructed topology: {exc}") from exc

    return mol


# ============================================================================
# WORKER PROCESS INITIALIZER AND BFS EXPLORATION ENGINE
# ============================================================================


def _cpu_worker_init() -> None:
    """Worker initializer enforcing strict CPU-bound execution and zero GPU context allocation [M]."""
    os.environ["CUDA_VISIBLE_DEVICES"] = ""


def _bfs_tautomer_worker(
    input_topology: TopologyInput,
    config: TautomerEnumerationConfig,
) -> TautomerEnsemble:
    """Internal algorithmic BFS worker executing bounded prototropic state traversal [M][D]."""
    start_time = time.perf_counter()

    root_mol = _build_rdkit_mol_from_topology(input_topology)

    # Check for all-ghost empty topology
    cleaned_root = Chem.DeleteSubstructs(root_mol, Chem.MolFromSmarts("[#0]"))
    if cleaned_root.GetNumAtoms() == 0:
        raise GhostAtomSanitizationError("Sanitization resulted in an empty molecular graph (only ghost atoms present)")

    # Prepare reaction objects
    rxn_objects: List[Tuple[str, AllChem.ChemicalReaction]] = [
        (name, AllChem.ReactionFromSmarts(smirks))
        for name, smirks in PROTOTROPIC_SMIRKS.items()
    ]

    # Convert root to explicit Hs for prototropic migration
    root_mol_hs = Chem.AddHs(root_mol)
    net_charge = sum(a.GetFormalCharge() for a in root_mol_hs.GetAtoms())
    total_hydrogens = sum(1 for a in root_mol_hs.GetAtoms() if a.GetAtomicNum() == 1)

    # State tracking: keyed by fixed-H InChIKey (the definitive deduplication key)
    visited_candidates: Dict[str, TautomerCandidate] = {}
    visited_depths: Dict[str, int] = {}

    def _register_candidate(mol: Chem.Mol, depth: int, history: List[str]) -> Optional[str]:
        """Processes and registers a molecular candidate. Returns fixed_h_inchi_key."""
        # Purge dummy/ghost atoms prior to computing InChI/InChIKeys
        cleaned_mol = Chem.DeleteSubstructs(mol, Chem.MolFromSmarts("[#0]"))
        if cleaned_mol.GetNumAtoms() == 0:
            return None

        # Remove explicit Hs for canonical SMILES generation
        mol_no_hs = Chem.RemoveHs(cleaned_mol)
        c_smiles = Chem.MolToSmiles(mol_no_hs)
        c_inchi_key = Chem.MolToInchiKey(cleaned_mol)
        c_fixed_h = Chem.MolToInchiKey(cleaned_mol, options="-FixedH")

        if not c_inchi_key or not c_fixed_h or len(c_inchi_key) != 27 or len(c_fixed_h) != 27:
            raise TautomerCanonicalizationError(
                f"Failed to generate valid 27-character InChIKeys for candidate '{c_smiles}'"
            )

        if c_fixed_h in visited_candidates:
            # Retain minimal transform depth
            if depth < visited_candidates[c_fixed_h].transform_depth:
                existing = visited_candidates[c_fixed_h]
                visited_candidates[c_fixed_h] = existing.model_copy(
                    update={"transform_depth": depth, "transform_history": history}
                )
            return c_fixed_h

        # New candidate: check combinatorial bound
        if len(visited_candidates) >= config.max_tautomers:
            if config.truncation_policy == "raise":
                raise TautomerCombinatorialLimitExceededError(
                    f"Generated tautomer count exceeded combinatorial limit of {config.max_tautomers}"
                )
            return None

        score = compute_patterson_score(mol_no_hs)
        cand_id = f"cand_{hashlib.sha256(f'{input_topology.molecule_id}_{c_fixed_h}'.encode('utf-8')).hexdigest()[:16]}"

        cand = TautomerCandidate(
            candidate_id=cand_id,
            smiles=c_smiles,
            inchi_key=c_inchi_key,
            fixed_h_inchi_key=c_fixed_h,
            canonical_score=score,
            relative_energy_kcal_mol=None,
            is_canonical=False,
            transform_depth=depth,
            transform_history=history,
        )
        visited_candidates[c_fixed_h] = cand
        visited_depths[c_fixed_h] = depth
        return c_fixed_h

    # Register root state
    root_fixed_h = _register_candidate(root_mol_hs, depth=0, history=[])
    if root_fixed_h is None:
        raise ToposPerceptionError("Failed to perceive and register parent root tautomer")

    # Queue holds: (mol_hs, depth, history)
    queue: collections.deque[Tuple[Chem.Mol, int, List[str]]] = collections.deque()
    queue.append((root_mol_hs, 0, []))

    # BFS Traversal loop
    while queue:
        # Check timeout ceiling
        if (time.perf_counter() - start_time) > config.timeout_seconds:
            raise TautomerEnumerationTimeoutError(
                f"Tautomer state space exploration exceeded timeout ceiling of {config.timeout_seconds}s"
            )

        current_mol, current_depth, current_history = queue.popleft()

        if current_depth >= config.max_transform_depth:
            continue

        for rule_name, rxn in rxn_objects:
            # Check timeout inside loop
            if (time.perf_counter() - start_time) > config.timeout_seconds:
                raise TautomerEnumerationTimeoutError(
                    f"Tautomer state space exploration exceeded timeout ceiling of {config.timeout_seconds}s"
                )

            try:
                products_list = rxn.RunReactants((current_mol,))
            except Exception:
                continue

            for prod_tuple in products_list:
                prod_mol = prod_tuple[0]

                # Sanitize and assign stereochemistry
                try:
                    Chem.SanitizeMol(prod_mol)
                    Chem.AssignStereochemistry(prod_mol, cleanIt=True, force=True)
                except Chem.AtomValenceException as val_err:
                    raise ValenceConservationError(f"Valence violation during transform '{rule_name}': {val_err}") from val_err
                except Exception:
                    continue

                # Conservation safeguards: net charge and total hydrogens (explicit nodes + implicit)
                q_prod = sum(a.GetFormalCharge() for a in prod_mol.GetAtoms())
                h_explicit = sum(1 for a in prod_mol.GetAtoms() if a.GetAtomicNum() == 1)
                h_implicit = sum(a.GetNumImplicitHs() for a in prod_mol.GetAtoms())
                total_h_prod = h_explicit + h_implicit
                if q_prod != net_charge:
                    raise ValenceConservationError(
                        f"Net formal charge violation: {q_prod} != parent {net_charge} under '{rule_name}'"
                    )
                if h_implicit > 0 or total_h_prod != total_hydrogens:
                    raise ValenceConservationError(
                        f"Hydrogen conservation violation: {h_explicit} explicit + {h_implicit} implicit != parent {total_hydrogens} under '{rule_name}'"
                    )

                next_depth = current_depth + 1
                next_history = current_history + [rule_name]

                # Clean ghost atoms for fixed_h lookup
                cleaned_prod = Chem.DeleteSubstructs(prod_mol, Chem.MolFromSmarts("[#0]"))
                prod_fixed_h = Chem.MolToInchiKey(cleaned_prod, options="-FixedH")

                if prod_fixed_h not in visited_candidates:
                    registered_key = _register_candidate(prod_mol, next_depth, next_history)
                    if registered_key is not None:
                        queue.append((prod_mol, next_depth, next_history))
                    elif config.truncation_policy == "truncate" and len(visited_candidates) >= config.max_tautomers:
                        # Graceful halt when combinatorial limit reached
                        queue.clear()
                        break
                else:
                    if next_depth < visited_depths.get(prod_fixed_h, 999):
                        visited_depths[prod_fixed_h] = next_depth
                        _register_candidate(prod_mol, next_depth, next_history)

    # Designate canonical tautomer: highest Patterson score, tie-break by lexicographically smallest SMILES
    candidates_list = list(visited_candidates.values())
    if not candidates_list:
        raise ToposPerceptionError("Tautomer exploration generated zero valid candidate states")

    # Sort: descending by canonical_score, ascending by canonical smiles
    candidates_list.sort(key=lambda c: (-c.canonical_score, c.smiles))

    canonical_id = candidates_list[0].candidate_id

    # Rebuild candidate list flagging exactly the single canonical winner
    final_candidates: List[TautomerCandidate] = []
    for c in candidates_list:
        is_can = (c.candidate_id == canonical_id)
        final_candidates.append(c.model_copy(update={"is_canonical": is_can}))

    elapsed = round(time.perf_counter() - start_time, 4)

    return TautomerEnsemble(
        parent_id=input_topology.molecule_id,
        canonical_tautomer_id=canonical_id,
        total_generated=len(final_candidates),
        candidates=final_candidates,
        execution_duration_seconds=elapsed,
    )


# ============================================================================
# PUBLIC API: ENUMERATION, FILTERING, PERSISTENCE
# ============================================================================


def enumerate_tautomers(
    input_topology: TopologyInput,
    config: TautomerEnumerationConfig,
) -> TautomerEnsemble:
    """Pure in-memory Tier 2 prototropic graph enumeration kernel [M][D].

    Executes bounded Breadth-First Search inside an isolated subprocess worker,
    adhering to CPU-only boundaries, process timeouts, and fixed-H InChIKey deduplication.
    """
    executor = concurrent.futures.ProcessPoolExecutor(max_workers=1, initializer=_cpu_worker_init)
    try:
        future = executor.submit(_bfs_tautomer_worker, input_topology, config)
        return future.result(timeout=config.timeout_seconds)
    except (concurrent.futures.TimeoutError, TimeoutError) as exc:
        for p in list(executor._processes.values()):
            try:
                p.terminate()
            except Exception as term_exc:
                logger.debug("Process termination handled: %s", term_exc)
        raise TautomerEnumerationTimeoutError(
            f"Tautomer enumeration exceeded timeout ceiling of {config.timeout_seconds} seconds"
        ) from exc
    except ToposPerceptionError:
        raise
    except Exception as exc:
        # Forward domain exceptions if raised in child process
        exc_str = str(exc)
        if "TautomerCombinatorialLimitExceededError" in exc_str:
            raise TautomerCombinatorialLimitExceededError(exc_str) from exc
        if "TautomerEnumerationTimeoutError" in exc_str:
            raise TautomerEnumerationTimeoutError(exc_str) from exc
        if "ValenceConservationError" in exc_str:
            raise ValenceConservationError(exc_str) from exc
        if "InvalidTopologyInputError" in exc_str:
            raise InvalidTopologyInputError(exc_str) from exc
        if "GhostAtomSanitizationError" in exc_str:
            raise GhostAtomSanitizationError(exc_str) from exc
        raise ToposPerceptionError(f"Tautomer enumeration failed: {exc}") from exc
    finally:
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception as shut_exc:
            logger.debug("Executor shutdown handled: %s", shut_exc)


def filter_tautomers_thermodynamics(
    ensemble: TautomerEnsemble,
    config: TautomerEnumerationConfig,
    scratch_dir: Path,
) -> TautomerEnsemble:
    """Refuse an unsupported thermal filter without pruning any structure.

    This historical interface provides no explicit spin, geometry/minimum,
    method, temperature, standard state or matched native provenance contract.
    ETKDG guesses and candidate-specific xTB/MMFF/UFF fallbacks cannot supply
    that evidence. BASE's verified TOPOS optimize/frequency/thermochemistry
    workflow is the scientific route; its reports compare qualified protocols.
    """
    raise TautomerThermodynamicsUnavailableError(
        "Tautomer structural enumeration cannot perform thermodynamic filtering: request matched native optimization, minimum qualification and thermochemistry through BASE's verified TOPOS provider; no candidates were recalculated or discarded"
    )


def save_tautomer_ensemble_to_hdf5(
    ensemble: TautomerEnsemble,
    hdf5_path: Path,
    lock_timeout: float = 30.0,
) -> Path:
    """Tier 3 persistence: serializes tautomer candidates and metadata into HDF5 archive [M][D].

    Uses fixed-width UTF-8 strings (S256 for SMILES, S32 for InChIKeys), chunking,
    GZIP level 4 compression, and filelock synchronization.
    """
    hdf5_path = Path(hdf5_path)
    lock_path = hdf5_path.with_suffix(".h5.lock")
    flock = filelock.FileLock(str(lock_path), timeout=lock_timeout)

    try:
        with _HDF5_THREAD_LOCK:
            try:
                with flock.acquire(timeout=lock_timeout):
                    hdf5_path.parent.mkdir(parents=True, exist_ok=True)
                    with h5py.File(hdf5_path, "a") as f:
                        grp_name = f"/tautomers/{ensemble.parent_id}"
                        if grp_name in f:
                            del f[grp_name]
                        grp = f.create_group(grp_name)

                        # Group metadata
                        grp.attrs["parent_id"] = str(ensemble.parent_id)
                        grp.attrs["canonical_tautomer_id"] = str(ensemble.canonical_tautomer_id)
                        grp.attrs["total_generated"] = int(ensemble.total_generated)
                        grp.attrs["execution_duration_seconds"] = float(ensemble.execution_duration_seconds)

                        n = len(ensemble.candidates)
                        chunks = (min(n, 128),) if n > 0 else None

                        # Explicit fixed-width datatypes
                        s256_dt = h5py.string_dtype(encoding="utf-8", length=256)
                        s32_dt = h5py.string_dtype(encoding="utf-8", length=32)
                        s64_dt = h5py.string_dtype(encoding="utf-8", length=64)

                        cand_ids = np.array([c.candidate_id for c in ensemble.candidates], dtype=s64_dt)
                        smiles_arr = np.array([c.smiles for c in ensemble.candidates], dtype=s256_dt)
                        ik_arr = np.array([c.inchi_key for c in ensemble.candidates], dtype=s32_dt)
                        fik_arr = np.array([c.fixed_h_inchi_key for c in ensemble.candidates], dtype=s32_dt)
                        scores_arr = np.array([c.canonical_score for c in ensemble.candidates], dtype=np.float64)
                        rel_e_arr = np.array(
                            [
                                c.relative_energy_kcal_mol if c.relative_energy_kcal_mol is not None else np.nan
                                for c in ensemble.candidates
                            ],
                            dtype=np.float64,
                        )
                        is_canon_arr = np.array([c.is_canonical for c in ensemble.candidates], dtype=np.bool_)
                        depths_arr = np.array([c.transform_depth for c in ensemble.candidates], dtype=np.int32)

                        grp.create_dataset("candidate_id", data=cand_ids, dtype=s64_dt, chunks=chunks, compression="gzip", compression_opts=4)
                        grp.create_dataset("smiles", data=smiles_arr, dtype=s256_dt, chunks=chunks, compression="gzip", compression_opts=4)
                        grp.create_dataset("inchi_key", data=ik_arr, dtype=s32_dt, chunks=chunks, compression="gzip", compression_opts=4)
                        grp.create_dataset("fixed_h_inchi_key", data=fik_arr, dtype=s32_dt, chunks=chunks, compression="gzip", compression_opts=4)
                        grp.create_dataset("canonical_score", data=scores_arr, dtype=np.float64, chunks=chunks, compression="gzip", compression_opts=4)
                        grp.create_dataset("relative_energy_kcal_mol", data=rel_e_arr, dtype=np.float64, chunks=chunks, compression="gzip", compression_opts=4)
                        legacy_e_arr = np.array([c.unvalidated_legacy_energy_kcal_mol if c.unvalidated_legacy_energy_kcal_mol is not None else np.nan for c in ensemble.candidates], dtype=np.float64)
                        grp.create_dataset("unvalidated_legacy_energy_kcal_mol", data=legacy_e_arr, dtype=np.float64, chunks=chunks, compression="gzip", compression_opts=4)
                        grp.attrs["energy_scope"] = "structural_enumeration_only; legacy_numbers_unverified"
                        grp.create_dataset("is_canonical", data=is_canon_arr, dtype=np.bool_, chunks=chunks, compression="gzip", compression_opts=4)
                        grp.create_dataset("transform_depth", data=depths_arr, dtype=np.int32, chunks=chunks, compression="gzip", compression_opts=4)

                    return hdf5_path
            except filelock.Timeout as exc:
                raise TautomerStorageLockTimeoutError(
                    f"Timed out acquiring storage filelock on '{lock_path}' after {lock_timeout}s"
                ) from exc
    except ToposPerceptionError:
        raise
    except Exception as exc:
        raise TautomerPersistenceError(f"Failed to persist tautomer ensemble to '{hdf5_path}': {exc}") from exc


def load_tautomer_ensemble_from_hdf5(
    hdf5_path: Path,
    molecule_id: str,
    lock_timeout: float = 30.0,
) -> TautomerEnsemble:
    """Tier 3 persistence: retrieves and reconstructs validated TautomerEnsemble from HDF5 archive [M][D]."""
    hdf5_path = Path(hdf5_path)
    if not hdf5_path.exists():
        raise TautomerPersistenceError(f"Target HDF5 archive does not exist: '{hdf5_path}'")

    lock_path = hdf5_path.with_suffix(".h5.lock")
    flock = filelock.FileLock(str(lock_path), timeout=lock_timeout)

    try:
        with _HDF5_THREAD_LOCK:
            try:
                with flock.acquire(timeout=lock_timeout):
                    with h5py.File(hdf5_path, "r") as f:
                        grp_path = f"/tautomers/{molecule_id}"
                        if grp_path not in f:
                            raise TautomerPersistenceError(
                                f"Molecule ID '{molecule_id}' not found under '/tautomers/' in '{hdf5_path}'"
                            )
                        grp = f[grp_path]

                        parent_id = str(grp.attrs["parent_id"])
                        canonical_tautomer_id = str(grp.attrs["canonical_tautomer_id"])
                        total_generated = int(grp.attrs["total_generated"])
                        exec_duration = float(grp.attrs["execution_duration_seconds"])

                        cand_ids = grp["candidate_id"][:]
                        smiles_arr = grp["smiles"][:]
                        ik_arr = grp["inchi_key"][:]
                        fik_arr = grp["fixed_h_inchi_key"][:]
                        scores_arr = grp["canonical_score"][:]
                        rel_e_arr = grp["relative_energy_kcal_mol"][:]
                        legacy_e_arr = grp["unvalidated_legacy_energy_kcal_mol"][:] if "unvalidated_legacy_energy_kcal_mol" in grp else rel_e_arr
                        is_canon_arr = grp["is_canonical"][:]
                        depths_arr = grp["transform_depth"][:]

                        candidates: List[TautomerCandidate] = []
                        for i in range(len(cand_ids)):
                            cid = cand_ids[i].decode("utf-8") if isinstance(cand_ids[i], bytes) else str(cand_ids[i])
                            smi = smiles_arr[i].decode("utf-8") if isinstance(smiles_arr[i], bytes) else str(smiles_arr[i])
                            ik = ik_arr[i].decode("utf-8") if isinstance(ik_arr[i], bytes) else str(ik_arr[i])
                            fik = fik_arr[i].decode("utf-8") if isinstance(fik_arr[i], bytes) else str(fik_arr[i])
                            sc = float(scores_arr[i])
                            re = float(legacy_e_arr[i])
                            rel_e = None if np.isnan(re) else re
                            is_c = bool(is_canon_arr[i])
                            dep = int(depths_arr[i])

                            candidates.append(
                                TautomerCandidate(
                                    candidate_id=cid,
                                    smiles=smi,
                                    inchi_key=ik,
                                    fixed_h_inchi_key=fik,
                                    canonical_score=sc,
                                    relative_energy_kcal_mol=None,
                                    unvalidated_legacy_energy_kcal_mol=rel_e,
                                    is_canonical=is_c,
                                    transform_depth=dep,
                                    transform_history=[],
                                )
                            )

                        return TautomerEnsemble(
                            parent_id=parent_id,
                            canonical_tautomer_id=canonical_tautomer_id,
                            total_generated=total_generated,
                            candidates=candidates,
                            execution_duration_seconds=exec_duration,
                        )
            except filelock.Timeout as exc:
                raise TautomerStorageLockTimeoutError(
                    f"Timed out acquiring storage filelock on '{lock_path}' after {lock_timeout}s"
                ) from exc
    except ToposPerceptionError:
        raise
    except Exception as exc:
        raise TautomerPersistenceError(f"Failed to load tautomer ensemble from '{hdf5_path}': {exc}") from exc
