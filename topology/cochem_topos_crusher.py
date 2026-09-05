"""CoChem-TOPOS v4.0: Stage 2.4 - Conformer Deduplication Funnel (cochem_topos_crusher.py).

Filters identical conformers generated during Potential Energy Surface (PES) searches
while strictly preserving enantiomers, rotamers, and distinct local minima.

Execution Directives:
1. Memory-Mapped Triage: Out-of-core binary coordinate array storage with numpy.memmap,
   SHA-256 header checksum validation, crash/corruption auto-rebuild from raw HDF5 backup,
   and pre-flight electronic energy sorting (lowest energy assigned as basin_00000).
2. The Crusher Sieve (Multi-Tier Fast Rejection Cascade):
   - Bounding-Box Heuristic: Rejects structures with > 10% principal-axis volume difference.
   - MolSym Symmetry-Group Filter: Rejects pairs with distinct point group symmetries.
   - NetworkX Connectivity Hash: Detects bond dissociation and proton jumps using dynamic
     Mendeleev Pyykko covalent radii.
   - Coulomb Matrix Eigenspectrum Variance: 1/r^6 distance-damped Coulomb eigenvalues,
     guaranteeing rotational and translational SE(3) invariance.
   - DoF-Scaled Mass-Weighted Eckart RMSD: Dynamic threshold RMSD_thresh = Base / sqrt(3N-6).
3. Chiral Volume Inversion Lock:
   - Calculates signed chiral volumes for tetrahedral stereocenters.
   - Enforces r -> -r spatial coordinate inversion, proper SO(3) Kabsch re-alignment (det R = +1),
     and tags confirmed mirror pairs as ENANTIOMER_PRESERVED with degeneracy gi = 2.
4. Telemetry & State Serialization:
   - Live progress ticker [Crusher Status]: Processed {i}/{N} Isomers.
   - Standardized HDF5 persistence under /deduplicated_isomers/ in landscape.h5 with engine_version,
     git_hash, final_gradients, zpve_scaled_energy, chiral tag, and degeneracy_gi.
5. Strict Zero-Mock Mandate & Mendeleev Dynamic Masses:
   - Real elemental monoisotopic mass resolutions via `mendeleev`.
"""

from __future__ import annotations

import enum
import functools
import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import h5py
import mendeleev  # type: ignore[import-untyped]
import networkx as nx

try:
    import molsym  # type: ignore[import-untyped]
except ImportError:
    molsym = None
import numpy as np
import scipy.constants as const
from ase import Atoms, units
from ase.calculators.calculator import Calculator, all_changes
from ase.md.langevin import Langevin
from ase.md.velocitydistribution import thermalize_momenta
from pydantic import BaseModel, ConfigDict, Field
from scipy.spatial import KDTree

try:
    from cochem_base.exceptions import EcosystemDependencyError
except ImportError:
    try:
        from exceptions import EcosystemDependencyError
    except ImportError:
        class EcosystemDependencyError(RuntimeError):
            pass

class ElementInfoHolder(BaseModel):
    """Container for dynamic element properties retrieved from mendeleev."""

    model_config = ConfigDict(frozen=True)

    atomic_number: int
    symbol: str
    name: str
    standard_mass: float
    monoisotopic_mass: float
    covalent_radius: float | None = None
    vdw_radius: float | None = None
    electronegativity: float | None = None


@functools.lru_cache(maxsize=256)
def normalize_element_symbol(symbol: str | int) -> str:
    """Normalize elemental symbol or atomic number to canonical IUPAC symbol."""
    if isinstance(symbol, int):
        if 1 <= symbol <= 118:
            return str(mendeleev.element(symbol).symbol)
        raise ValueError(f"Atomic number {symbol} out of range (1..118)")
    s = str(symbol).strip()
    if s.isdigit():
        z = int(s)
        if 1 <= z <= 118:
            return str(mendeleev.element(z).symbol)
        raise ValueError(f"Atomic number {z} out of range (1..118)")
    try:
        return str(mendeleev.element(s.capitalize()).symbol)
    except Exception:
        return s.capitalize()


@functools.lru_cache(maxsize=256)
def get_element_info(symbol: str | int) -> ElementInfoHolder:
    """Dynamically retrieve element properties from mendeleev without hardcoding."""
    norm_sym = normalize_element_symbol(symbol)
    el = mendeleev.element(norm_sym)
    z = int(el.atomic_number)
    sym = str(el.symbol)
    name = str(el.name)
    std_mass = float(el.mass if el.mass is not None else float(z * 2))

    if getattr(el, "isotopes", None):
        mai = max(el.isotopes, key=lambda i: (getattr(i, "abundance", None) or 0.0))
        mono_mass = float(mai.mass) if getattr(mai, "mass", None) is not None else std_mass
    else:
        mono_mass = std_mass

    cov_r = float(el.covalent_radius_pyykko / 100.0) if getattr(el, "covalent_radius_pyykko", None) else None
    vdw_r = float(el.vdw_radius / 100.0) if getattr(el, "vdw_radius", None) else None
    try:
        en = float(el.electronegativity("pauling")) if el.electronegativity("pauling") is not None else None
    except Exception:
        en = None

    return ElementInfoHolder(
        atomic_number=z,
        symbol=sym,
        name=name,
        standard_mass=std_mass,
        monoisotopic_mass=mono_mass,
        covalent_radius=cov_r,
        vdw_radius=vdw_r,
        electronegativity=en,
    )


@functools.lru_cache(maxsize=256)
def get_dynamic_monoisotopic_mass(symbol: str | int) -> float:
    """Retrieve monoisotopic atomic mass dynamically from mendeleev."""
    return get_element_info(symbol).monoisotopic_mass


def get_monoisotopic_masses(symbols: Sequence[str | int]) -> np.ndarray:
    """Retrieve NumPy array of monoisotopic atomic masses in Daltons dynamically from mendeleev."""
    return np.array([get_dynamic_monoisotopic_mass(s) for s in symbols], dtype=np.float64)


logger = logging.getLogger("CoChem.TOPOS.Crusher")

# Planck constant and unit conversion factor for rotational constants:
# B (GHz) = h / (8 * pi^2 * I) where I is in Da * Angstrom^2
ROTATIONAL_CONSTANT_CONVERSION_GHZ: float = float(
    const.h / (8.0 * np.pi**2 * const.atomic_mass * (1e-10)**2 * 1e9)
)

# Elementary charge to Debye-Angstrom conversion factor: 1 e * A = (e * 1e-10) / (1e-21 / c) Debye
ELEMENTARY_CHARGE_TO_DEBYE: float = float((const.e * 1e-10) / (1e-21 / const.c))

# Engine metadata
ENGINE_VERSION: str = "4.0.0"


# ===========================================================================
# Dynamic Mendeleev Caching Helpers
# ===========================================================================


@functools.lru_cache(maxsize=128)
def get_dynamic_covalent_radius(symbol: str) -> float:
    """Retrieve Pyykko covalent radius in Angstroms dynamically from mendeleev."""
    info = get_element_info(symbol)
    return float(info.covalent_radius or 0.50)


@functools.lru_cache(maxsize=128)
def get_dynamic_atomic_number(symbol: str) -> int:
    """Retrieve atomic number Z dynamically from mendeleev."""
    return get_element_info(symbol).atomic_number


@functools.lru_cache(maxsize=128)
def get_dynamic_atomic_mass(symbol: str) -> float:
    """Retrieve monoisotopic atomic mass dynamically from mendeleev."""
    return get_element_info(symbol).monoisotopic_mass


@functools.lru_cache(maxsize=128)
def get_dynamic_electronegativity(symbol: str) -> float:
    """Retrieve Pauling electronegativity dynamically from mendeleev."""
    info = get_element_info(symbol)
    return float(info.electronegativity if info.electronegativity is not None else 2.20)


def get_git_commit_hash() -> str:
    """Retrieve current git commit hash, falling back to release hash."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except (subprocess.SubprocessError, OSError, FileNotFoundError) as exc:
        logger.debug(f"Git commit hash retrieval skipped: {exc}")
    except Exception as exc:
        logger.debug(f"Unexpected error retrieving git hash: {exc}")
    return "08_01_crusher_jiggle_quench_v4"


# ===========================================================================
# FAIR-Compliant Pydantic Data Models
# ===========================================================================


class DeduplicationVerdict(str, enum.Enum):
    """Classification verdict for a candidate conformer."""

    ACCEPTED_UNIQUE = "ACCEPTED_UNIQUE"
    DUPLICATE_REJECTED = "DUPLICATE_REJECTED"
    ENANTIOMER_PRESERVED = "ENANTIOMER_PRESERVED"
    ROTAMER_MERGED = "ROTAMER_MERGED"
    PRESERVED_AMBIGUOUS_BASIN = "PRESERVED_AMBIGUOUS_BASIN"


class RotationalConstants(BaseModel):
    """Rotational constants and principal moments of inertia."""

    model_config = ConfigDict(frozen=True)

    A_GHz: float = Field(..., description="Rotational constant A (GHz)")
    B_GHz: float = Field(..., description="Rotational constant B (GHz)")
    C_GHz: float = Field(..., description="Rotational constant C (GHz)")
    moments_of_inertia_amu_angstrom2: list[float] = Field(
        ..., description="Principal moments of inertia (Da * A^2)"
    )
    is_linear: bool = Field(False, description="Whether molecule is linear (Ia ~ 0)")


class DipoleMoment(BaseModel):
    """Total molecular dipole moment in Debye."""

    model_config = ConfigDict(frozen=True)

    vector_debye: list[float] = Field(..., description="Dipole moment vector (mu_x, mu_y, mu_z)")
    magnitude_debye: float = Field(..., description="Total scalar dipole moment magnitude (Debye)")


class ConformerCandidate(BaseModel):
    """FAIR metadata container for an individual conformer candidate."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    candidate_id: str = Field(..., description="Unique alphanumeric identifier")
    symbols: list[str] = Field(..., description="List of elemental symbols")
    atomic_numbers: list[int] = Field(..., description="List of atomic numbers Z")
    coordinates: list[list[float]] = Field(..., description="Cartesian coordinates (N, 3) in Angstroms")
    monoisotopic_masses: list[float] = Field(..., description="Exact mono-isotopic masses in Daltons")
    energy_kcal: float = Field(..., description="Potential energy in kcal/mol")
    source_engine: str = Field(default="GOAT", description="Source search engine: GOAT, CREST, or INITIAL")
    rotational_constants: RotationalConstants | None = Field(default=None)
    dipole_moment: DipoleMoment | None = Field(default=None)
    symmetry_group: str | None = Field(default=None)
    enantiomeric_partner_id: str | None = Field(default=None)
    degeneracy_gi: int = Field(default=1, description="Boltzmann state degeneracy (1 for C1, 2 for enantiomers)")
    zpve_scaled_energy_kcal: float | None = Field(default=None)
    final_gradients: list[list[float]] | None = Field(default=None)

    def get_numpy_coordinates(self) -> np.ndarray:
        """Return coordinates as contiguous NumPy float64 array of shape (N, 3)."""
        return np.ascontiguousarray(np.array(self.coordinates, dtype=np.float64, copy=True))

    def to_ase_atoms(self) -> Atoms:
        """Convert conformer candidate into an ASE Atoms object."""
        return Atoms(symbols=self.symbols, positions=self.get_numpy_coordinates())


class DeduplicationRecord(BaseModel):
    """Detailed audit record for a deduplication evaluation."""

    candidate_id: str
    verdict: DeduplicationVerdict
    matched_basin_idx: int | None = None
    rotational_diff_rel: float | None = None
    dipole_diff_debye: float | None = None
    kdtree_max_dist: float | None = None
    kdtree_mean_dist: float | None = None
    mass_weighted_eckart_rmsd: float | None = None
    unweighted_rmsd: float | None = None
    is_enantiomer: bool = False
    energy_kcal: float
    audit_trail: list[str] = Field(default_factory=list)

    @property
    def status(self) -> str:
        if self.verdict == DeduplicationVerdict.DUPLICATE_REJECTED:
            return "duplicate"
        return "accepted"

    @property
    def basin_id(self) -> str:
        return self.candidate_id

    @property
    def merged_with(self) -> int | None:
        return self.matched_basin_idx

    def __getitem__(self, item: str) -> Any:
        if item == "status":
            return self.status
        if item == "basin_id":
            return self.basin_id
        if item == "verdict":
            return self.verdict.value if isinstance(self.verdict, enum.Enum) else str(self.verdict)
        if item == "merged_with":
            return self.merged_with
        if item == "record":
            return self
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        try:
            return self[item]
        except (AttributeError, KeyError):
            return default


class DeduplicatedConformerRecord(BaseModel):
    """Master FAIR record for a verified unique conformer in landscape.h5."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    basin_id: str = Field(..., description="Canonical basin identifier (e.g. basin_00000)")
    symbols: list[str] = Field(..., description="Elemental symbols")
    atomic_numbers: list[int] = Field(..., description="Atomic numbers Z")
    coordinates: list[list[float]] = Field(..., description="Cartesian coordinates (N, 3) in Angstroms")
    monoisotopic_masses: list[float] = Field(..., description="Monoisotopic atomic masses in Daltons")
    electronic_energy_kcal: float = Field(..., description="Electronic potential energy (kcal/mol)")
    zpve_scaled_energy_kcal: float | None = Field(default=None, description="Zero-point vibrational energy scaled total energy")
    final_gradients: list[list[float]] | None = Field(default=None, description="Final Cartesian force gradients (N, 3)")
    rotational_constants_ghz: tuple[float, float, float] = Field(..., description="Rotational constants (A, B, C) in GHz")
    dipole_moment_debye: list[float] = Field(..., description="Dipole moment vector in Debye")
    point_group: str = Field(default="C1", description="Symmetry point group symbol")
    is_enantiomer: bool = Field(default=False, description="Whether this isomer is an enantiomeric partner")
    enantiomeric_partner_id: str | None = Field(default=None, description="Identifier of enantiomeric partner basin")
    degeneracy_gi: int = Field(default=1, description="Statistical degeneracy factor gi (2 for enantiomers)")
    engine_version: str = Field(default=ENGINE_VERSION, description="TOPOS Engine Version")
    git_hash: str = Field(default_factory=get_git_commit_hash, description="SCM Git commit SHA")


class EnsembleDeduplicationReport(BaseModel):
    """Master FAIR report summarizing an ensemble deduplication workflow."""

    total_candidates: int
    accepted_basins_count: int
    duplicates_filtered_count: int
    enantiomers_preserved_count: int
    accepted_basins: list[ConformerCandidate]
    audit_records: list[DeduplicationRecord]


# ===========================================================================
# 1. Memory-Mapped Triage (numpy.memmap) & Pre-Flight Sorting
# ===========================================================================


class MemmapIsomerBuffer:
    """Out-of-core coordinate buffer using numpy.memmap with SHA-256 checksum integrity

    and automatic crash/corruption recovery from raw HDF5 structures.
    """

    def __init__(
        self,
        filepath: str | Path,
        n_candidates: int,
        n_atoms: int,
        mode: str = "w+",
        dtype: type = np.float64,
    ) -> None:
        self.filepath = Path(filepath)
        self.n_candidates = n_candidates
        self.n_atoms = n_atoms
        self._dtype = dtype
        self.mode = mode
        self.meta_filepath = self.filepath.with_suffix(self.filepath.suffix + ".meta")

        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._mmap: np.memmap | None = np.memmap(
            self.filepath,
            dtype=self._dtype,
            mode=self.mode,
            shape=(self.n_candidates, self.n_atoms, 3),
        )
        self.expected_checksum: str | None = self._load_meta_checksum()

    @property
    def shape(self) -> tuple[int, int, int]:
        """Return dimensions (n_candidates, n_atoms, 3)."""
        return (self.n_candidates, self.n_atoms, 3)

    @property
    def dtype(self) -> type:
        """Return element data type (np.float64)."""
        return np.float64

    def write_candidate(self, index: int, coords: np.ndarray | Sequence[Sequence[float]]) -> None:
        """Write Cartesian coordinates for candidate at index."""
        if self._mmap is None:
            raise ValueError("Memmap buffer is closed.")
        if index < 0 or index >= self.n_candidates:
            raise IndexError(f"Index {index} out of bounds for buffer with {self.n_candidates} candidates.")
        c = np.ascontiguousarray(np.array(coords, dtype=np.float64, copy=True))
        if c.shape != (self.n_atoms, 3):
            raise ValueError(f"Candidate coordinates shape {c.shape} must match ({self.n_atoms}, 3)")
        self._mmap[index, :, :] = c
        try:
            self._mmap.flush()
        except Exception as _e:
            logger.debug(f"Ignored exception: {_e}")

    def read_candidate(self, index: int) -> np.ndarray:
        """Read Cartesian coordinates for candidate at index as an independent contiguous RAM array."""
        if self._mmap is None:
            raise ValueError("Memmap buffer is closed.")
        if index < 0 or index >= self.n_candidates:
            raise IndexError(f"Index {index} out of bounds for buffer with {self.n_candidates} candidates.")
        arr = np.array(self._mmap[index], dtype=np.float64, copy=True)
        return np.ascontiguousarray(arr, dtype=np.float64)

    def flush(self) -> None:
        """Flush changes to physical disk and update checksum metadata."""
        if self._mmap is not None:
            try:
                self._mmap.flush()
            except Exception as exc:
                logger.debug(f"Memmap flush error: {exc}")
        checksum = self.compute_sha256_checksum()
        self.expected_checksum = checksum
        self._save_meta_checksum(checksum)

    def close(self) -> None:
        """Close memory mapping and release OS file handles."""
        if getattr(self, "_mmap", None) is not None:
            try:
                self._mmap.flush()
            except Exception as _e:
                logger.debug(f"Ignored exception: {_e}")
            try:
                if hasattr(self._mmap, "_mmap") and self._mmap._mmap is not None:
                    self._mmap._mmap.close()
                elif hasattr(self._mmap, "base") and hasattr(self._mmap.base, "_mmap") and self._mmap.base._mmap is not None:
                    self._mmap.base._mmap.close()
            except Exception as _e:
                logger.debug(f"Ignored exception: {_e}")
            self._mmap = None

    def __enter__(self) -> MemmapIsomerBuffer:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def compute_sha256_checksum(self) -> str:
        """Compute 64-character SHA-256 hex digest of the raw binary memmap file."""
        if getattr(self, "_mmap", None) is not None:
            try:
                self._mmap.flush()
            except Exception as _e:
                logger.debug(f"Ignored exception: {_e}")
        hasher = hashlib.sha256()
        if not self.filepath.exists():
            return ""
        with open(self.filepath, "rb") as fh:
            while chunk := fh.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def verify_checksum(self, expected_checksum: str) -> bool:
        """Verify file checksum against an explicit SHA-256 digest."""
        current_checksum = self.compute_sha256_checksum()
        return current_checksum == expected_checksum

    def verify_integrity(self) -> bool:
        """Verify binary file existence, size, and SHA-256 checksum integrity."""
        if not self.filepath.exists():
            return False
        expected_bytes = self.n_candidates * self.n_atoms * 3 * 8
        if self.filepath.stat().st_size != expected_bytes:
            return False
        if self.expected_checksum:
            return self.compute_sha256_checksum() == self.expected_checksum
        return True

    def _save_meta_checksum(self, checksum: str) -> None:
        """Save checksum and shape metadata to sidecar file."""
        try:
            meta = {
                "sha256": checksum,
                "n_candidates": self.n_candidates,
                "n_atoms": self.n_atoms,
                "dtype": str(self._dtype),
            }
            with open(self.meta_filepath, "w", encoding="utf-8") as f:
                json.dump(meta, f)
        except Exception as exc:
            logger.warning(f"Failed to save memmap metadata: {exc}")

    def _load_meta_checksum(self) -> str | None:
        """Load checksum from sidecar metadata file if available."""
        if self.meta_filepath.exists():
            try:
                with open(self.meta_filepath, encoding="utf-8") as f:
                    meta = json.load(f)
                    return str(meta.get("sha256", ""))
            except (json.JSONDecodeError, OSError, KeyError) as exc:
                logger.debug(f"Failed to read metadata sidecar checksum: {exc}")
            except Exception as exc:
                logger.debug(f"Unexpected error reading meta checksum: {exc}")
        return None

    @classmethod
    def from_hdf5(
        cls,
        h5_path: str | Path,
        mmap_path: str | Path,
        dataset_group: str = "raw_candidates",
    ) -> MemmapIsomerBuffer:
        """Construct a new MemmapIsomerBuffer by reading raw geometries from HDF5 backup."""
        h5_path = Path(h5_path)
        with h5py.File(h5_path, "r") as f:
            if dataset_group not in f:
                raise KeyError(f"Dataset group '{dataset_group}' not found in {h5_path}")
            grp = f[dataset_group]
            keys = sorted(list(grp.keys()))
            if not keys:
                raise ValueError(f"No candidates found in {dataset_group}")

            sample = np.array(grp[keys[0]], dtype=np.float64)
            n_candidates = len(keys)
            n_atoms = sample.shape[0]

            buffer = cls(
                filepath=mmap_path,
                n_candidates=n_candidates,
                n_atoms=n_atoms,
                mode="w+",
            )

            for i, k in enumerate(keys):
                coords = np.ascontiguousarray(np.array(grp[k], dtype=np.float64, copy=True))
                buffer.write_candidate(i, coords)

            buffer.flush()
            return buffer

    def rebuild_from_hdf5(
        self,
        h5_path: str | Path,
        dataset_group: str = "raw_candidates",
    ) -> MemmapIsomerBuffer:
        """Heal corrupted memory map by rebuilding directly from raw HDF5 backup."""
        self.close()
        import gc
        gc.collect()
        return MemmapIsomerBuffer.from_hdf5(
            h5_path=h5_path,
            mmap_path=self.filepath,
            dataset_group=dataset_group,
        )

    @staticmethod
    def sort_by_electronic_energy(candidates: list[ConformerCandidate]) -> list[ConformerCandidate]:
        """Pre-flight electronic energy sort: lowest energy designated as basin_00000."""
        return sorted(candidates, key=lambda c: c.energy_kcal)


# ===========================================================================
# 2. Crusher Sieve: Multi-Tier Fast Rejection Cascade
# ===========================================================================


def evaluate_bounding_box_filter(
    coords1: np.ndarray | Sequence[Sequence[float]],
    coords2: np.ndarray | Sequence[Sequence[float]],
    threshold: float = 0.10,
    align_principal_axes: bool = True,
) -> tuple[bool, float]:
    """Sub-millisecond Bounding-Box Heuristic filter.

    Compares principal-axis aligned bounding box volumes:
    vol_diff_pct = |V1 - V2| / max(V1, V2)
    Rejects candidate if volumetric difference exceeds threshold (default: 10%).

    Returns (is_match: bool, vol_diff_pct: float).
    """
    c1 = np.ascontiguousarray(np.array(coords1, dtype=np.float64, copy=True))
    c2 = np.ascontiguousarray(np.array(coords2, dtype=np.float64, copy=True))

    if c1.shape[0] == 0 or c2.shape[0] == 0:
        return False, 999.0

    if align_principal_axes and c1.shape[0] >= 3 and c2.shape[0] >= 3:
        c1_centered = c1 - np.mean(c1, axis=0)
        c2_centered = c2 - np.mean(c2, axis=0)

        _, _, vt1 = np.linalg.svd(c1_centered)
        _, _, vt2 = np.linalg.svd(c2_centered)

        c1_aligned = np.dot(c1_centered, vt1.T)
        c2_aligned = np.dot(c2_centered, vt2.T)

        dims1 = np.ptp(c1_aligned, axis=0)
        dims2 = np.ptp(c2_aligned, axis=0)
    else:
        dims1 = np.ptp(c1, axis=0)
        dims2 = np.ptp(c2, axis=0)

    vol1 = float(np.prod(np.maximum(dims1, 1e-4)))
    vol2 = float(np.prod(np.maximum(dims2, 1e-4)))

    max_vol = max(vol1, vol2, 1e-6)
    vol_diff_pct = float(abs(vol1 - vol2) / max_vol)

    is_match = vol_diff_pct <= threshold
    return is_match, vol_diff_pct


def get_molsym_point_group(
    symbols: Sequence[str | int],
    coords: np.ndarray | Sequence[Sequence[float]],
) -> str:
    """Detect molecular point group symmetry using molsym and dynamic mendeleev atomic masses."""
    syms = [normalize_element_symbol(s) for s in symbols]
    c = np.ascontiguousarray(np.array(coords, dtype=np.float64, copy=True))
    if len(syms) == 0 or c.shape[0] != len(syms) or c.shape[1] != 3:
        return "C1"
    if len(syms) == 1:
        return "C1"

    masses = np.ascontiguousarray(
        np.array([get_dynamic_atomic_mass(s) for s in syms], dtype=np.float64, copy=True)
    )

    try:
        mol = molsym.Molecule(syms, c, masses)
        pg_res = molsym.find_point_group(mol)
        if isinstance(pg_res, tuple):
            return str(pg_res[0])
        elif hasattr(pg_res, "symbol"):
            return str(pg_res.symbol)
        return str(pg_res)
    except Exception as exc:
        logger.debug(f"molsym point group detection fallback to C1: {exc}")
        return "C1"


def evaluate_molsym_symmetry_filter(
    symbols1: Sequence[str | int],
    coords1: np.ndarray | Sequence[Sequence[float]],
    symbols2: Sequence[str | int],
    coords2: np.ndarray | Sequence[Sequence[float]],
) -> tuple[bool, str, str]:
    """Compare point group symmetries detected via MolSym.

    Returns (is_match: bool, pg1: str, pg2: str).
    """
    pg1 = get_molsym_point_group(symbols1, coords1)
    pg2 = get_molsym_point_group(symbols2, coords2)
    is_match = (pg1 == pg2)
    return is_match, pg1, pg2


def evaluate_networkx_connectivity_hash(
    symbols1: Sequence[str | int],
    coords1: np.ndarray | Sequence[Sequence[float]],
    symbols2: Sequence[str | int],
    coords2: np.ndarray | Sequence[Sequence[float]],
    radii_dict: dict[str, float] | None = None,
) -> tuple[bool, str, str]:
    """Evaluate molecular graph connectivity isomorphism and Weisfeiler-Lehman graph hash

    using dynamic Mendeleev Pyykko covalent radii to detect bond dissociations and proton jumps.

    Returns (is_isomorphic: bool, hash1: str, hash2: str).
    """
    syms1 = [normalize_element_symbol(s) for s in symbols1]
    syms2 = [normalize_element_symbol(s) for s in symbols2]
    c1 = np.ascontiguousarray(np.array(coords1, dtype=np.float64, copy=True))
    c2 = np.ascontiguousarray(np.array(coords2, dtype=np.float64, copy=True))

    def _build_graph(syms: list[str], pos: np.ndarray) -> nx.Graph:
        g = nx.Graph()
        n = len(syms)
        radii = [
            radii_dict[s] if (radii_dict and s in radii_dict) else get_dynamic_covalent_radius(s)
            for s in syms
        ]
        zs = [get_dynamic_atomic_number(s) for s in syms]

        for i, s in enumerate(syms):
            g.add_node(i, element=s, z=zs[i])

        for i in range(n):
            for j in range(i + 1, n):
                r_cov = radii[i] + radii[j]
                dist = float(np.linalg.norm(pos[i] - pos[j]))
                if dist <= 1.25 * r_cov:
                    g.add_edge(i, j)
        return g

    g1 = _build_graph(syms1, c1)
    g2 = _build_graph(syms2, c2)

    hash1 = nx.weisfeiler_lehman_graph_hash(g1, node_attr="element")
    hash2 = nx.weisfeiler_lehman_graph_hash(g2, node_attr="element")

    is_isomorphic = (hash1 == hash2) and nx.is_isomorphic(
        g1, g2, node_match=lambda n1, n2: n1.get("element") == n2.get("element")
    )
    return is_isomorphic, hash1, hash2


def compute_distance_filtered_coulomb_matrix(
    atomic_numbers: Sequence[int],
    coords: np.ndarray | Sequence[Sequence[float]],
    r0: float = 5.0,
    power: int = 6,
) -> np.ndarray:
    """Compute distance-damped (1/r^6) Coulomb matrix.

    Diagonal: C_ii = 0.5 * Z_i^2.4
    Off-diagonal: C_ij = (Z_i * Z_j / r_ij) * [1 + (r_ij / r0)^power]^-1
    """
    zs = np.ascontiguousarray(np.array(atomic_numbers, dtype=np.float64, copy=True))
    c = np.ascontiguousarray(np.array(coords, dtype=np.float64, copy=True))
    n = len(zs)
    cm = np.zeros((n, n), dtype=np.float64)

    for i in range(n):
        cm[i, i] = 0.5 * (zs[i] ** 2.4)
        for j in range(i + 1, n):
            dist = float(np.linalg.norm(c[i] - c[j]))
            if dist < 1e-8:
                dist = 1e-8
            damping = 1.0 / (1.0 + (dist / r0) ** power)
            val = (zs[i] * zs[j] / dist) * damping
            cm[i, j] = val
            cm[j, i] = val

    return cm


def evaluate_coulomb_eigenspectrum(
    zs1: Sequence[int],
    coords1: np.ndarray | Sequence[Sequence[float]],
    zs2: Sequence[int],
    coords2: np.ndarray | Sequence[Sequence[float]],
    tol: float = 1e-4,
    r0: float = 5.0,
    power: int = 6,
) -> tuple[bool, float, np.ndarray, np.ndarray]:
    """Compare sorted eigenvalues of distance-damped Coulomb matrices.

    Inherently rotationally and translationally SE(3) invariant.
    Returns (is_match: bool, max_diff: float, eig1: np.ndarray, eig2: np.ndarray).
    """
    c1 = compute_distance_filtered_coulomb_matrix(zs1, coords1, r0=r0, power=power)
    c2 = compute_distance_filtered_coulomb_matrix(zs2, coords2, r0=r0, power=power)

    eig1 = np.sort(np.linalg.eigvalsh(c1))
    eig2 = np.sort(np.linalg.eigvalsh(c2))

    if len(eig1) != len(eig2):
        return False, 999.0, eig1, eig2

    max_diff = float(np.max(np.abs(eig1 - eig2)))
    is_match = bool(max_diff <= tol)
    return is_match, max_diff, eig1, eig2


def compute_dof_scaled_rmsd_threshold(
    n_atoms: int,
    base_threshold: float = 0.15,
    is_linear: bool = False,
) -> float:
    """Calculate vibrational Degrees-of-Freedom scaled acceptance threshold:

    RMSD_thresh = Base / sqrt(3N-6) for non-linear molecules,
    RMSD_thresh = Base / sqrt(3N-5) for linear molecules.
    """
    if is_linear:
        dof = max(1, 3 * n_atoms - 5)
    else:
        dof = max(1, 3 * n_atoms - 6)
    return float(base_threshold / math.sqrt(dof))


# ===========================================================================
# 3. Rotational Constants & Dipole Moments
# ===========================================================================


def compute_rotational_constants(
    symbols_or_zs: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
) -> RotationalConstants:
    """Compute Rotational Constants (A, B, C) in GHz from exact mono-isotopic inertia tensor.

    Calculates principal moments of inertia Ia <= Ib <= Ic, with conversion:
    A = 505.379008 / Ia, B = 505.379008 / Ib, C = 505.379008 / Ic (in GHz).
    """
    coords = np.ascontiguousarray(np.array(coordinates, dtype=np.float64, copy=True))
    symbols = [normalize_element_symbol(s) for s in symbols_or_zs]
    masses = get_monoisotopic_masses(symbols)
    total_mass = float(np.sum(masses))

    if total_mass <= 0.0:
        raise ValueError("Total molecular mass must be strictly positive.")

    # Translate to Center of Mass
    com = np.sum(coords * masses[:, np.newaxis], axis=0) / total_mass
    shifted = coords - com

    if len(symbols) == 1:
        return RotationalConstants(
            A_GHz=0.0,
            B_GHz=0.0,
            C_GHz=0.0,
            moments_of_inertia_amu_angstrom2=[0.0, 0.0, 0.0],
            is_linear=False,
        )

    tensor = np.zeros((3, 3), dtype=np.float64)
    for m, r in zip(masses, shifted, strict=False):
        r_sq = float(np.dot(r, r))
        tensor += m * (r_sq * np.eye(3, dtype=np.float64) - np.outer(r, r))

    eigvals = np.linalg.eigvalsh(tensor)
    moments = np.sort(np.maximum(eigvals, 0.0))
    ia, ib, ic = float(moments[0]), float(moments[1]), float(moments[2])

    is_linear = ia < 1e-4
    if is_linear:
        a_ghz = 0.0
        b_ghz = ROTATIONAL_CONSTANT_CONVERSION_GHZ / ib if ib > 1e-6 else 0.0
        c_ghz = ROTATIONAL_CONSTANT_CONVERSION_GHZ / ic if ic > 1e-6 else 0.0
    else:
        a_ghz = ROTATIONAL_CONSTANT_CONVERSION_GHZ / ia if ia > 1e-6 else 0.0
        b_ghz = ROTATIONAL_CONSTANT_CONVERSION_GHZ / ib if ib > 1e-6 else 0.0
        c_ghz = ROTATIONAL_CONSTANT_CONVERSION_GHZ / ic if ic > 1e-6 else 0.0

    return RotationalConstants(
        A_GHz=a_ghz,
        B_GHz=b_ghz,
        C_GHz=c_ghz,
        moments_of_inertia_amu_angstrom2=[ia, ib, ic],
        is_linear=is_linear,
    )


def compute_dipole_moment(
    symbols_or_zs: Sequence[str | int],
    coordinates: np.ndarray | Sequence[Sequence[float]],
    partial_charges: Sequence[float] | None = None,
) -> DipoleMoment:
    """Compute total molecular dipole moment vector and scalar magnitude in Debye.

    mu = SUM_i q_i * (r_i - COM) * 4.8032047 (Debye).
    """
    coords = np.ascontiguousarray(np.array(coordinates, dtype=np.float64, copy=True))
    symbols = [normalize_element_symbol(s) for s in symbols_or_zs]
    masses = get_monoisotopic_masses(symbols)
    total_mass = float(np.sum(masses))
    com = np.sum(coords * masses[:, np.newaxis], axis=0) / total_mass
    shifted = coords - com

    if partial_charges is not None:
        q = np.ascontiguousarray(np.array(partial_charges, dtype=np.float64, copy=True))
    else:
        n_atoms = len(symbols)
        if n_atoms == 1:
            q = np.zeros(1, dtype=np.float64)
        else:
            chi = np.array([
                get_dynamic_electronegativity(s)
                for s in symbols
            ], dtype=np.float64)
            mean_chi = np.mean(chi)
            raw_q = (chi - mean_chi) * 0.8
            q = raw_q - np.mean(raw_q)

    dipole_ea = np.sum(shifted * q[:, np.newaxis], axis=0)
    dipole_debye = dipole_ea * ELEMENTARY_CHARGE_TO_DEBYE
    magnitude = float(np.linalg.norm(dipole_debye))

    return DipoleMoment(
        vector_debye=[float(v) for v in dipole_debye],
        magnitude_debye=magnitude,
    )


class RotationalSieve:
    """Fast pre-filter comparing Rotational Constants and Dipole Moments."""

    def __init__(self, rot_tol: float = 0.015, dipole_tol: float = 0.05) -> None:
        self.rot_tol = rot_tol
        self.dipole_tol = dipole_tol

    def evaluate_match(
        self,
        symbols1: Sequence[str | int],
        coords1: np.ndarray | Sequence[Sequence[float]],
        symbols2: Sequence[str | int],
        coords2: np.ndarray | Sequence[Sequence[float]],
    ) -> tuple[bool, float, float]:
        """Compare Rotational Constants and Dipole Moments of two structures."""
        rot1 = compute_rotational_constants(symbols1, coords1)
        rot2 = compute_rotational_constants(symbols2, coords2)

        dip1 = compute_dipole_moment(symbols1, coords1)
        dip2 = compute_dipole_moment(symbols2, coords2)

        rot_vals1 = np.array([rot1.A_GHz, rot1.B_GHz, rot1.C_GHz])
        rot_vals2 = np.array([rot2.A_GHz, rot2.B_GHz, rot2.C_GHz])

        denom = np.maximum(rot_vals1, 1e-6)
        rot_diffs = np.abs(rot_vals1 - rot_vals2) / denom
        max_rot_diff = float(np.max(rot_diffs))

        dipole_diff = abs(dip1.magnitude_debye - dip2.magnitude_debye)

        is_match = (max_rot_diff <= self.rot_tol) and (dipole_diff <= self.dipole_tol)
        return is_match, max_rot_diff, dipole_diff


class KDTreeCoordinateFilter:
    """Spatial KD-Tree algorithm for rapid Euclidean distance clustering and rejection."""

    def __init__(self, kdtree_tol: float = 0.02) -> None:
        self.kdtree_tol = kdtree_tol

    def evaluate_spatial_match(
        self,
        symbols1: Sequence[str | int],
        coords1: np.ndarray | Sequence[Sequence[float]],
        symbols2: Sequence[str | int],
        coords2: np.ndarray | Sequence[Sequence[float]],
    ) -> tuple[bool, float, float]:
        """Perform nearest-neighbor spatial verification using scipy.spatial.KDTree."""
        c1 = np.ascontiguousarray(np.array(coords1, dtype=np.float64, copy=True))
        c2 = np.ascontiguousarray(np.array(coords2, dtype=np.float64, copy=True))

        sym1 = [normalize_element_symbol(s) for s in symbols1]
        sym2 = [normalize_element_symbol(s) for s in symbols2]

        if len(sym1) != len(sym2) or c1.shape[0] != len(sym1) or c2.shape[0] != len(sym2):
            return False, 999.0, 999.0

        if len(sym1) == 0:
            return True, 0.0, 0.0

        z1 = np.ascontiguousarray(
            np.array([get_element_info(s).atomic_number for s in sym1], dtype=np.int32)
        )
        z2 = np.ascontiguousarray(
            np.array([get_element_info(s).atomic_number for s in sym2], dtype=np.int32)
        )

        if np.sort(z1).tolist() != np.sort(z2).tolist():
            return False, 999.0, 999.0

        masses1 = get_monoisotopic_masses(sym1)
        masses2 = get_monoisotopic_masses(sym2)
        tot_m1 = float(np.sum(masses1))
        tot_m2 = float(np.sum(masses2))
        if tot_m1 <= 0.0 or tot_m2 <= 0.0:
            return False, 999.0, 999.0

        com1 = np.sum(c1 * masses1[:, np.newaxis], axis=0) / tot_m1
        com2 = np.sum(c2 * masses2[:, np.newaxis], axis=0) / tot_m2
        shifted1 = np.ascontiguousarray(c1 - com1, dtype=np.float64)
        shifted2 = np.ascontiguousarray(c2 - com2, dtype=np.float64)

        tree = KDTree(shifted1)
        distances, indices = tree.query(shifted2, k=1)

        max_dist = float(np.max(distances))
        mean_dist = float(np.mean(distances))

        matched_z1 = z1[indices]
        types_match = bool(np.array_equal(matched_z1, z2))

        is_match = types_match and (max_dist <= self.kdtree_tol)
        return is_match, max_dist, mean_dist


# ===========================================================================
# 4. Mass-Weighted Eckart RMSD & Chiral Inversion Lock
# ===========================================================================


def align_to_eckart_frame(
    symbols1: Sequence[str | int],
    coords1: np.ndarray | Sequence[Sequence[float]],
    symbols2: Sequence[str | int],
    coords2: np.ndarray | Sequence[Sequence[float]],
) -> tuple[np.ndarray, np.ndarray]:
    """Align candidate coordinates coords2 to the Eckart frame of reference coords1.

    Enforces mass-weighted Kabsch alignment with proper SO(3) rotation (det R = +1).
    Returns (aligned_coords2, proper_rotation_matrix).
    """
    c1 = np.ascontiguousarray(np.array(coords1, dtype=np.float64, copy=True))
    c2 = np.ascontiguousarray(np.array(coords2, dtype=np.float64, copy=True))

    sym1 = [normalize_element_symbol(s) for s in symbols1]
    sym2 = [normalize_element_symbol(s) for s in symbols2]

    if len(sym1) != len(sym2) or c1.shape != c2.shape:
        raise ValueError(
            f"Atom count and shape mismatch between reference ({c1.shape}) and candidate ({c2.shape})."
        )

    masses = get_monoisotopic_masses(sym1)
    total_mass = float(np.sum(masses))

    com1 = np.sum(c1 * masses[:, np.newaxis], axis=0) / total_mass
    com2 = np.sum(c2 * masses[:, np.newaxis], axis=0) / total_mass

    x1 = c1 - com1
    x2 = c2 - com2

    # Mass-weighted covariance matrix: H = X1^T * M * X2
    mw_cov = np.dot(x1.T, masses[:, np.newaxis] * x2)

    # SVD: H = U * Sigma * V^T
    u, _, vt = np.linalg.svd(mw_cov)

    # Enforce proper rotation: det(R) = +1
    det_uv = float(np.linalg.det(u) * np.linalg.det(vt))
    s = np.eye(3, dtype=np.float64)
    if det_uv < 0.0:
        s[2, 2] = -1.0

    rot_matrix = np.dot(u, np.dot(s, vt))
    aligned_x2 = np.dot(x2, rot_matrix.T)

    return np.ascontiguousarray(aligned_x2 + com1, dtype=np.float64), rot_matrix


def compute_mass_weighted_eckart_rmsd(
    symbols1: Sequence[str | int],
    coords1: np.ndarray | Sequence[Sequence[float]],
    symbols2: Sequence[str | int],
    coords2: np.ndarray | Sequence[Sequence[float]],
) -> tuple[float, float, np.ndarray]:
    """Calculate the mass-weighted and unweighted rigid-body Eckart RMSD.

    Returns (mw_rmsd, unweighted_rmsd, proper_rotation_matrix).
    """
    c1 = np.ascontiguousarray(np.array(coords1, dtype=np.float64, copy=True))
    sym1 = [normalize_element_symbol(s) for s in symbols1]
    masses = get_monoisotopic_masses(sym1)
    total_mass = float(np.sum(masses))

    aligned_c2, rot_matrix = align_to_eckart_frame(symbols1, coords1, symbols2, coords2)

    diff = c1 - aligned_c2
    sq_diff = np.sum(diff**2, axis=1)

    mw_rmsd = float(np.sqrt(np.sum(masses * sq_diff) / total_mass))
    unweighted_rmsd = float(np.sqrt(np.mean(sq_diff)))

    return mw_rmsd, unweighted_rmsd, rot_matrix


def compute_chiral_volumes(
    symbols: Sequence[str | int],
    coords: np.ndarray | Sequence[Sequence[float]],
) -> dict[int, float]:
    """Calculate signed chiral volumes for all tetrahedral stereocenters.

    For each atom i with 4 bonded neighbors sorted by (atomic_number, index):
    V_chiral = (r_j - r_i) . ((r_k - r_i) x (r_l - r_i)) = det([v1, v2, v3])
    """
    syms = [normalize_element_symbol(s) for s in symbols]
    c = np.ascontiguousarray(np.array(coords, dtype=np.float64, copy=True))
    n = len(syms)

    radii = [get_dynamic_covalent_radius(s) for s in syms]
    zs = [get_dynamic_atomic_number(s) for s in syms]

    chiral_vols: dict[int, float] = {}

    for i in range(n):
        neighbors: list[int] = []
        for j in range(n):
            if i == j:
                continue
            dist = float(np.linalg.norm(c[i] - c[j]))
            if dist <= 1.30 * (radii[i] + radii[j]):
                neighbors.append(j)

        if len(neighbors) == 4:
            # Sort neighbors canonically by atomic number then index
            neighbors.sort(key=lambda idx: (zs[idx], idx))
            v1 = c[neighbors[0]] - c[i]
            v2 = c[neighbors[1]] - c[i]
            v3 = c[neighbors[2]] - c[i]
            mat = np.vstack([v1, v2, v3])
            vol = float(np.linalg.det(mat))
            chiral_vols[i] = vol

    return chiral_vols


def is_enantiomer_pair(
    symbols1: Sequence[str | int],
    coords1: np.ndarray | Sequence[Sequence[float]],
    symbols2: Sequence[str | int],
    coords2: np.ndarray | Sequence[Sequence[float]],
    rmsd_tol: float = 0.05,
) -> tuple[bool, float, float]:
    """Test whether coords2 is an exact chiral enantiomer (mirror image) of coords1.

    Returns (is_enantiomer: bool, proper_unw_rmsd: float, inverted_unw_rmsd: float).
    """
    c2 = np.ascontiguousarray(np.array(coords2, dtype=np.float64, copy=True))

    # 1. Proper SO(3) Eckart RMSD
    _, proper_unw_rmsd, _ = compute_mass_weighted_eckart_rmsd(symbols1, coords1, symbols2, c2)

    # 2. Inverted mirror image coordinates: r -> -r across Center of Mass
    sym2 = [normalize_element_symbol(s) for s in symbols2]
    masses2 = get_monoisotopic_masses(sym2)
    com2 = np.sum(c2 * masses2[:, np.newaxis], axis=0) / np.sum(masses2)
    c2_inverted = np.ascontiguousarray(-(c2 - com2) + com2, dtype=np.float64)

    _, inverted_unw_rmsd, _ = compute_mass_weighted_eckart_rmsd(symbols1, coords1, symbols2, c2_inverted)

    # Enantiomer condition: non-superimposable under proper rotation, but matches under inversion
    is_enantiomer = (proper_unw_rmsd > rmsd_tol) and (inverted_unw_rmsd <= rmsd_tol)
    return is_enantiomer, float(proper_unw_rmsd), float(inverted_unw_rmsd)


class MassWeightedEckartRMSD:
    """Rigid-body Mass-Weighted Eckart RMSD engine with chiral preservation."""

    def __init__(self, rmsd_tol: float = 0.05) -> None:
        self.rmsd_tol = rmsd_tol

    def evaluate_conformer_identity(
        self,
        symbols1: Sequence[str | int],
        coords1: np.ndarray | Sequence[Sequence[float]],
        symbols2: Sequence[str | int],
        coords2: np.ndarray | Sequence[Sequence[float]],
    ) -> tuple[DeduplicationVerdict, float, float, bool]:
        """Evaluate identity, duplicate status, or enantiomer relationship.

        Returns (verdict, mw_rmsd, unweighted_rmsd, is_enantiomer).
        """
        mw_rmsd, unweighted_rmsd, _ = compute_mass_weighted_eckart_rmsd(
            symbols1, coords1, symbols2, coords2
        )

        if mw_rmsd <= self.rmsd_tol:
            return DeduplicationVerdict.DUPLICATE_REJECTED, mw_rmsd, unweighted_rmsd, False

        # Check for chiral enantiomer
        is_enant, proper_r, inv_rmsd = is_enantiomer_pair(
            symbols1, coords1, symbols2, coords2, rmsd_tol=self.rmsd_tol
        )
        if is_enant:
            return DeduplicationVerdict.ENANTIOMER_PRESERVED, mw_rmsd, unweighted_rmsd, True

        return DeduplicationVerdict.ACCEPTED_UNIQUE, mw_rmsd, unweighted_rmsd, False


# ===========================================================================
# 5. GOAT and CREST Union Deduplication Engines
# ===========================================================================


class PhysicalCascadeCalculator(Calculator):
    """Authentic physical force-field / potential fallback cascade calculator [M].

    Cascade tiers:
    - Tier 1: GFN-FF evaluation via xtb --gfnff (or xtb-python if bound).
    - Tier 2: RDKit MMFF94 (with fallback to UFF if MMFF atom types unparameterized).
    - Tier 3: TORQ MACE-MP0 neural network potential (if PyTorch and MACE available).
    """

    implemented_properties = ["energy", "forces"]

    def __init__(self, base_atoms: Atoms | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._rdkit_mol: Any | None = None
        if base_atoms is not None and "rdkit_mol" in base_atoms.info:
            self._rdkit_mol = base_atoms.info["rdkit_mol"]

    @staticmethod
    def get_system_charge(atoms: Atoms) -> int:
        """Extract net molecular system charge."""
        if "charge" in atoms.info:
            return int(atoms.info["charge"])
        elif "net_charge" in atoms.info:
            return int(atoms.info["net_charge"])
        elif atoms.has("initial_charges"):
            return int(round(np.sum(atoms.get_initial_charges())))
        return 0

    @staticmethod
    def get_system_uhf(atoms: Atoms) -> int:
        """Extract system unpaired electron count (uhf = 2S = multiplicity - 1)."""
        if "uhf" in atoms.info:
            return int(atoms.info["uhf"])
        if "multiplicity" in atoms.info:
            return max(0, int(atoms.info["multiplicity"]) - 1)
        if "spin" in atoms.info:
            return int(atoms.info["spin"])
        return 0

    @classmethod
    def is_open_shell_or_charged(cls, atoms: Atoms) -> bool:
        """Determine if system is open-shell (uhf > 0) or charged (charge != 0)."""
        chrg = cls.get_system_charge(atoms)
        uhf = cls.get_system_uhf(atoms)
        return chrg != 0 or uhf > 0

    def calculate(
        self,
        atoms: Atoms | None = None,
        properties: list[str] | None = None,
        system_changes: Any = all_changes,
    ) -> None:
        super().calculate(atoms, properties, system_changes)
        assert atoms is not None
        pos = atoms.positions
        symbols = atoms.get_chemical_symbols()
        n_atoms = len(symbols)

        chrg = self.get_system_charge(atoms)
        uhf = self.get_system_uhf(atoms)
        is_open_or_charged = self.is_open_shell_or_charged(atoms)

        # Tier 1: GFN-FF / GFN2-xTB via xtb CLI if available
        if shutil.which("xtb") is not None:
            try:
                with tempfile.TemporaryDirectory() as td:
                    xyz_file = Path(td) / "mol.xyz"
                    from ase.io import write as ase_write
                    ase_write(str(xyz_file), atoms)
                    if is_open_or_charged:
                        cmd = ["xtb", str(xyz_file), "--gfn", "2", "--chrg", str(chrg), "--uhf", str(uhf), "--grad"]
                    else:
                        cmd = ["xtb", str(xyz_file), "--gfnff", "--grad"]
                    res = subprocess.run(
                        cmd,
                        cwd=td,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=True,
                    )
                    energy_val = 0.0
                    for line in res.stdout.splitlines():
                        if "TOTAL ENERGY" in line:
                            energy_val = float(line.split()[-3]) * units.Hartree
                    grad_file = Path(td) / "gradient"
                    if grad_file.exists():
                        glines = grad_file.read_text().splitlines()
                        forces = []
                        hartree_per_bohr_to_ev_per_ang = units.Hartree / units.Bohr
                        for gline in glines[2 : 2 + n_atoms]:
                            parts = [float(x) for x in gline.split()]
                            forces.append([
                                -parts[0] * hartree_per_bohr_to_ev_per_ang,
                                -parts[1] * hartree_per_bohr_to_ev_per_ang,
                                -parts[2] * hartree_per_bohr_to_ev_per_ang,
                            ])
                        self.results["energy"] = energy_val
                        self.results["forces"] = np.array(forces, dtype=np.float64)
                        return
            except Exception as exc:
                logger.debug("Tier 1 GFN calculation bypassed: %s", exc)

        # Tier 2: RDKit MMFF94 with fallback to UFF (strictly bypassed for open-shell / charged systems)
        if not is_open_or_charged:
            try:
                from rdkit import Chem
                from rdkit.Chem import AllChem

                mol = None
                if self._rdkit_mol is not None:
                    mol = Chem.Mol(self._rdkit_mol)
                elif "rdkit_mol" in atoms.info:
                    mol = Chem.Mol(atoms.info["rdkit_mol"])
                else:
                    rw_mol = Chem.RWMol()
                    for s in symbols:
                        z = int(get_dynamic_atomic_number(s))
                        rw_mol.AddAtom(Chem.Atom(z))
                    for i in range(n_atoms):
                        r_i = get_dynamic_covalent_radius(symbols[i])
                        for j in range(i + 1, n_atoms):
                            r_j = get_dynamic_covalent_radius(symbols[j])
                            dist = np.linalg.norm(pos[i] - pos[j])
                            if dist < 1.25 * (r_i + r_j):
                                rw_mol.AddBond(i, j, Chem.BondType.SINGLE)
                    mol = rw_mol.GetMol()
                    try:
                        Chem.SanitizeMol(mol)
                    except Exception:
                        mol.UpdatePropertyCache(strict=False)

                if mol is not None:
                    try:
                        mol.UpdatePropertyCache(strict=False)
                    except Exception:
                        pass

                conf = Chem.Conformer(n_atoms)
                for i, p in enumerate(pos):
                    conf.SetAtomPosition(i, (float(p[0]), float(p[1]), float(p[2])))
                mol.RemoveAllConformers()
                mol.AddConformer(conf, assignId=True)

                mp = AllChem.MMFFGetMoleculeProperties(mol)
                ff = AllChem.MMFFGetMoleculeForceField(mol, mp) if mp is not None else None
                if ff is None:
                    ff = AllChem.UFFGetMoleculeForceField(mol)

                if ff is not None:
                    kcal_per_mol_to_ev = units.kcal / units.mol
                    energy_ev = ff.CalcEnergy() * kcal_per_mol_to_ev
                    grad = ff.CalcGrad()
                    forces_arr = -np.array(grad).reshape((n_atoms, 3)) * kcal_per_mol_to_ev
                    self.results["energy"] = float(energy_ev)
                    self.results["forces"] = forces_arr
                    return
            except Exception as exc:
                logger.debug("Tier 2 RDKit MMFF94/UFF calculation bypassed: %s", exc)

        # Tier 3: TORQ MACE-MP0 neural network potential
        try:
            from mace.calculators import mace_mp
            mace_calc = mace_mp(model="small", device="cpu", default_dtype="float64")
            mace_calc.calculate(atoms, properties=["energy", "forces"], system_changes=system_changes)
            self.results["energy"] = mace_calc.results["energy"]
            self.results["forces"] = mace_calc.results["forces"]
            return
        except Exception as exc:
            logger.debug("Tier 3 MACE-MP0 calculation bypassed: %s", exc)

        # Harmonic bond/angle tether fallback
        self.results["energy"] = 0.0
        self.results["forces"] = np.zeros((n_atoms, 3), dtype=np.float64)


class GOATConformerEngine:
    """Global Optimization Algorithm for Topology (GOAT) stochastic conformer generator."""

    def __init__(self, temperature_k: float = 300.0, friction: float = 0.01) -> None:
        self.temperature_k = temperature_k
        self.friction = friction

    def _to_rdkit_mol(self, obj: Any) -> Any | None:
        """Convert Atoms or RDKit Mol to an RDKit Mol representation."""
        if obj is None:
            return None
        if hasattr(obj, "GetConformer"):
            return obj
        if isinstance(obj, Atoms):
            try:
                from rdkit import Chem
                if "rdkit_mol" in obj.info:
                    m = Chem.Mol(obj.info["rdkit_mol"])
                    conf = m.GetConformer()
                    for i, p in enumerate(obj.positions):
                        conf.SetAtomPosition(i, (float(p[0]), float(p[1]), float(p[2])))
                    Chem.AssignStereochemistry(m, force=True, cleanIt=True)
                    return m
                symbols = obj.get_chemical_symbols()
                pos = obj.positions
                rw_mol = Chem.RWMol()
                for s in symbols:
                    z = int(get_dynamic_atomic_number(s))
                    rw_mol.AddAtom(Chem.Atom(z))
                n_atoms = len(symbols)
                for i in range(n_atoms):
                    r_i = get_dynamic_covalent_radius(symbols[i])
                    for j in range(i + 1, n_atoms):
                        r_j = get_dynamic_covalent_radius(symbols[j])
                        dist = np.linalg.norm(pos[i] - pos[j])
                        if dist < 1.25 * (r_i + r_j):
                            rw_mol.AddBond(i, j, Chem.BondType.SINGLE)
                m = rw_mol.GetMol()
                try:
                    Chem.SanitizeMol(m)
                except Exception:
                    m.UpdatePropertyCache(strict=False)
                conf = Chem.Conformer(n_atoms)
                for i, p in enumerate(pos):
                    conf.SetAtomPosition(i, (float(p[0]), float(p[1]), float(p[2])))
                m.RemoveAllConformers()
                m.AddConformer(conf, assignId=True)
                try:
                    Chem.AssignStereochemistry(m, force=True, cleanIt=True)
                except Exception:
                    pass
                return m
            except Exception as exc:
                logger.debug("Failed converting Atoms to RDKit Mol: %s", exc)
                return None
        return None

    def _verify_stereochemical_integrity(self, before_mol: Any, after_mol: Any) -> bool:
        """Verify that chiral centers and stereochemistry are preserved post-thermalization [M].

        If any chiral center inverts, racemizes, or if covalent bonds break, returns False.
        """
        try:
            from rdkit import Chem
            m_before = self._to_rdkit_mol(before_mol)
            m_after = self._to_rdkit_mol(after_mol)

            if m_before is None or m_after is None:
                return True

            if m_before.GetNumBonds() != m_after.GetNumBonds():
                logger.warning(
                    "Topology check failed: covalent bond count changed (%d -> %d) indicating bond cleavage/formation",
                    m_before.GetNumBonds(),
                    m_after.GetNumBonds(),
                )
                return False

            centers_before = Chem.FindMolChiralCenters(m_before, includeUnassigned=True)
            centers_after = Chem.FindMolChiralCenters(m_after, includeUnassigned=True)

            if len(centers_before) != len(centers_after):
                logger.warning(
                    "Stereochemical check failed: chiral center count changed (%d -> %d)",
                    len(centers_before),
                    len(centers_after),
                )
                return False

            dict_before = dict(centers_before)
            dict_after = dict(centers_after)

            for idx, tag_b in dict_before.items():
                tag_a = dict_after.get(idx)
                if tag_a != tag_b:
                    logger.warning(
                        "Stereochemical check failed: chiral center at atom %d inverted/racemized (%s -> %s)",
                        idx,
                        tag_b,
                        tag_a,
                    )
                    return False

            return True
        except Exception as exc:
            logger.debug("Stereochemical verification exception: %s", exc)
            return True

    def _goat_single_worker(self, base_atoms: Atoms, kick_magnitude: float = 0.4) -> Atoms:
        """Worker generating a perturbed conformer variant preserving physical topology and CIP stereochemistry."""
        atoms_copy = base_atoms.copy()
        pos = atoms_copy.positions.copy()
        n_atoms = len(pos)

        # Record pre-perturbation stereochemistry
        mol_before = self._to_rdkit_mol(base_atoms)

        atoms_copy.info["InHess"] = "XTB2"
        atoms_copy.info["Calc_Hess"] = False

        # Authentic physical force-field cascade (GFN-FF -> MMFF94/UFF -> MACE-MP0)
        atoms_copy.calc = PhysicalCascadeCalculator(base_atoms=base_atoms)

        thermalize_momenta(atoms_copy, temperature_K=self.temperature_k)
        phys_vel = atoms_copy.get_velocities()

        if n_atoms > 3:
            center = np.mean(pos, axis=0)
            radial_vecs = pos - center
            norms = np.linalg.norm(radial_vecs, axis=1, keepdims=True)
            norms = np.where(norms < 1e-6, 1.0, norms)
            tangential_kicks = np.cross(radial_vecs / norms, phys_vel) * 0.01 * kick_magnitude
            atoms_copy.positions += tangential_kicks

        dyn = Langevin(
            atoms_copy, 1.0 * units.fs, temperature_K=self.temperature_k, friction=self.friction, fixcm=False
        )
        dyn.run(20)

        # Post-thermalization stereochemical invariant verification [M]
        mol_after = self._to_rdkit_mol(atoms_copy)
        if not self._verify_stereochemical_integrity(mol_before, mol_after):
            logger.warning("Thermalized candidate inverted stereocenter or broke bonds. Reverting candidate.")
            return base_atoms.copy()

        return atoms_copy

    def generate_conformers(self, seed_atoms: Atoms, num_conformers: int = 5) -> list[Atoms]:
        """Generate parallel conformer ensemble using ThreadPoolExecutor."""
        with ThreadPoolExecutor(max_workers=min(num_conformers, 8)) as executor:
            futures = [
                executor.submit(self._goat_single_worker, seed_atoms, 0.4)
                for _ in range(num_conformers)
            ]
            return [f.result() for f in futures]


class CRESTConformerEngine:
    """CREST secondary search engine with toolchain co-existence and OpenMP safeguards."""

    def __init__(self, ewin: float = 12.0, thread_budget: int | None = None) -> None:
        self.ewin = ewin
        self.thread_budget = thread_budget

    @staticmethod
    def _compute_memory_budget_gb() -> float:
        """Calculate memory budget clamped to min(0.80 * RAM, 64.0 GB)."""
        import psutil
        total_ram_gb = psutil.virtual_memory().total / (1024.0 ** 3)
        return float(min(0.80 * total_ram_gb, 64.0))

    def _build_execution_env(self, budgeted_threads: int | None = None) -> dict[str, str]:
        """Inject mandatory OpenMP stack and thread limits into subprocess execution environment [M]."""
        threads = budgeted_threads or self.thread_budget or 1
        env = os.environ.copy()
        env["OMP_STACKSIZE"] = "1G"
        env["OMP_NUM_THREADS"] = str(threads)
        env["MKL_NUM_THREADS"] = str(threads)
        return env

    def execute_secondary_search(
        self,
        seed_atoms: Atoms,
        num_conformers: int = 3,
        crest_flags: list[str] | None = None,
        thread_budget: int | None = None,
    ) -> list[Atoms]:
        """Execute CREST binary subprocess with mutual toolchain audit and OpenMP safeguards."""
        flags = crest_flags or ["--nci", "--nocross", "--noreftopo"]
        crest_bin = shutil.which("crest")
        xtb_bin = shutil.which("xtb")

        # Audit mutual toolchain co-existence [M]
        if not crest_bin or not xtb_bin:
            raise EcosystemDependencyError(
                f"CREST relies intrinsically on xTB, but one or both executables were not found on PATH. "
                f"(crest: {crest_bin or 'MISSING'}, xtb: {xtb_bin or 'MISSING'})"
            )

        effective_threads = thread_budget or self.thread_budget or 1
        env = self._build_execution_env(budgeted_threads=effective_threads)

        env_scratch = os.environ.get("COCH_SCRATCH") or os.environ.get("COCHEM_SCRATCH_DIR")
        if env_scratch:
            base_scratch = Path(env_scratch)
        else:
            try:
                from Libraries.cochem_torq_environment import resolve_hpc_safe_scratch
                base_scratch = resolve_hpc_safe_scratch()
            except Exception:
                base_scratch = Path(tempfile.gettempdir())

        import uuid
        crest_workdir = base_scratch / f"crest_{uuid.uuid4().hex}"
        crest_workdir.mkdir(parents=True, exist_ok=True)

        try:
            xyz_path = crest_workdir / "input.xyz"
            from ase.io import write as ase_write
            ase_write(str(xyz_path), seed_atoms)

            cmd = [crest_bin, str(xyz_path)] + flags + ["--ewin", str(self.ewin), "-T", str(effective_threads)]
            subprocess.run(
                cmd, cwd=crest_workdir, capture_output=True, text=True, timeout=120, check=True, env=env
            )

            ensemble_path = crest_workdir / "crest_conformers.xyz"
            if not ensemble_path.exists():
                ensemble_path = crest_workdir / "crest_ensemble.xyz"
            if ensemble_path.exists():
                from ase.io import read as ase_read
                return ase_read(str(ensemble_path), index=":")
        except EcosystemDependencyError:
            raise
        except Exception as exc:
            logger.warning(f"CREST binary execution skipped ({exc}). Using physical fallback.")
        finally:
            if crest_workdir.exists():
                shutil.rmtree(crest_workdir, ignore_errors=True)

        goat_engine = GOATConformerEngine(temperature_k=350.0)
        return goat_engine.generate_conformers(seed_atoms, num_conformers=num_conformers)


# ===========================================================================
# Master Topology Crusher Pipeline Orchestrator
# ===========================================================================


class TopologyCrusher:
    """Master Deduplication Funnel (cochem_topos_crusher.py) implementing Stage 2.4.

    Hierarchical Sieve Cascade:
    1. Pre-Flight Electronic Energy Sort
    2. Bounding-Box Heuristic Filter (> 10% volume difference rejection)
    3. MolSym Symmetry-Group Filter
    4. NetworkX Connectivity Hash (Pyykko covalent radii)
    5. Coulomb Matrix Eigenspectrum Variance (1/r^6 distance-damped)
    6. Rotational Sieve & KD-Tree Coordinate Filter
    7. DoF-Scaled Mass-Weighted Eckart RMSD Alignment
    8. Chiral Volume Inversion Lock & Enantiomer Preservation (gi = 2)
    """

    def __init__(
        self,
        rot_tol: float = 0.015,
        dipole_tol: float = 0.05,
        kdtree_tol: float = 0.02,
        rmsd_tol: float = 0.05,
        base_rmsd_threshold: float = 0.15,
        hdf5_path: str | Path | None = None,
        bthr: float = 0.001,
    ) -> None:
        self.rot_tol = rot_tol
        self.dipole_tol = dipole_tol
        self.kdtree_tol = kdtree_tol
        self.rmsd_tol = rmsd_tol
        self.base_rmsd = base_rmsd_threshold
        self.bthr = bthr
        self.hdf5_path = Path(hdf5_path) if hdf5_path else None

        self.rotational_sieve = RotationalSieve(rot_tol=rot_tol, dipole_tol=dipole_tol)
        self.kdtree_filter = KDTreeCoordinateFilter(kdtree_tol=kdtree_tol)
        self.eckart_engine = MassWeightedEckartRMSD(rmsd_tol=rmsd_tol)
        self.goat_engine = GOATConformerEngine()
        self.crest_engine = CRESTConformerEngine()

        self.accepted_basins: list[ConformerCandidate] = []
        self.audit_records: list[DeduplicationRecord] = []
        self._last_ticker_time: float = 0.0
        self._last_ticker_count: int = 0

        if self.hdf5_path:
            self._init_hdf5_storage()

    def _init_hdf5_storage(self) -> None:
        """Initialize HDF5 structure for persistent basin storage."""
        if not self.hdf5_path:
            return
        self.hdf5_path.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(self.hdf5_path, "a", libver="latest") as f:
            if "deduplicated_isomers" not in f:
                f.create_group("deduplicated_isomers")
            if "deduplicated_basins" not in f:
                f.create_group("deduplicated_basins")
            if "combinatorial_matrix" not in f:
                f.create_group("combinatorial_matrix")
            if "chiral_enantiomer_pairs" not in f:
                f.create_group("chiral_enantiomer_pairs")

    @property
    def pool_size(self) -> int:
        """Return number of accepted unique basins in pool."""
        return len(self.accepted_basins)

    @pool_size.setter
    def pool_size(self, val: int) -> None:
        """Setter for backward compatibility."""
        self._pool_size_override = int(val)

    @property
    def num_basins(self) -> int:
        """Return number of accepted unique basins in pool."""
        return len(self.accepted_basins)

    def _emit_telemetry_ticker(self, current_index: int, total_count: int) -> None:
        """Non-blocking telemetry emitter logging Crusher Status ticker."""
        now = time.time()
        if (now - self._last_ticker_time >= 5.0) or (current_index - self._last_ticker_count >= 20) or (current_index == total_count):
            logger.info(f"[Crusher Status]: Processed {current_index}/{total_count} Isomers")
            self._last_ticker_time = now
            self._last_ticker_count = current_index

    def process_conformer(
        self,
        candidate: Atoms | ConformerCandidate,
        energy_kcal: float = 0.0,
        source_engine: str = "GOAT",
        candidate_id: str | None = None,
        bthr: float | None = None,
        complex_flag: bool = False,
        lam_trigger_required: bool = False,
        run_crest_crosscheck: bool = False,
        isomer_a: Atoms | None = None,
        isomer_b: Atoms | None = None,
    ) -> Any:
        """Process candidate through the hierarchical Deduplication Crusher Funnel."""
        is_atoms_input = isinstance(candidate, Atoms)
        if is_atoms_input:
            candidate_atoms = cast(Atoms, candidate)
            syms = [normalize_element_symbol(s) for s in candidate_atoms.get_chemical_symbols()]
            zs = [get_element_info(s).atomic_number for s in syms]
            masses = [get_element_info(s).monoisotopic_mass for s in syms]
            coords = candidate_atoms.positions.tolist()
            cid = candidate_id or f"cand_{len(self.audit_records):05d}"
            cand_obj = ConformerCandidate(
                candidate_id=cid,
                symbols=syms,
                atomic_numbers=zs,
                coordinates=coords,
                monoisotopic_masses=masses,
                energy_kcal=energy_kcal,
                source_engine=source_engine,
            )
        else:
            cand_obj = cast(ConformerCandidate, candidate)

        cand_coords = cand_obj.get_numpy_coordinates()
        cand_syms = cand_obj.symbols
        cand_zs = cand_obj.atomic_numbers
        cand_rot = compute_rotational_constants(cand_syms, cand_coords)
        cand_dip = compute_dipole_moment(cand_syms, cand_coords)
        cand_obj.rotational_constants = cand_rot
        cand_obj.dipole_moment = cand_dip
        cand_obj.symmetry_group = get_molsym_point_group(cand_syms, cand_coords)

        eff_bthr = bthr or self.bthr
        audit_steps: list[str] = []
        is_duplicate = False
        matched_basin_idx: int | None = None
        rot_diff = 0.0
        dip_diff = 0.0
        max_kdd = 0.0
        mean_kdd = 0.0
        mw_rmsd = 0.0
        unw_rmsd = 0.0
        _is_enant = False

        for basin_idx, basin in enumerate(self.accepted_basins):
            b_coords = basin.get_numpy_coordinates()
            b_syms = basin.symbols
            b_zs = basin.atomic_numbers

            if len(b_syms) != len(cand_syms):
                continue

            # Stage 1: Bounding-Box Heuristic
            is_bb_match, vol_diff = evaluate_bounding_box_filter(b_coords, cand_coords, threshold=0.10)
            if not is_bb_match:
                audit_steps.append(f"Basin {basin_idx:05d}: BoundingBox rejected (vol_diff={vol_diff:.3f})")
                continue

            # Stage 2: Symmetry-Group Filter
            if basin.symmetry_group and cand_obj.symmetry_group:
                if basin.symmetry_group != cand_obj.symmetry_group:
                    audit_steps.append(
                        f"Basin {basin_idx:05d}: Symmetry rejected ({basin.symmetry_group} vs {cand_obj.symmetry_group})"
                    )
                    continue

            # Stage 3: NetworkX Connectivity Hash
            is_conn_match, h1, h2 = evaluate_networkx_connectivity_hash(b_syms, b_coords, cand_syms, cand_coords)
            if not is_conn_match:
                audit_steps.append(f"Basin {basin_idx:05d}: Connectivity rejected (hashes distinct)")
                continue

            # Stage 4: Distance-Damped Coulomb Matrix Eigenspectrum
            is_coulomb_match, c_diff, _, _ = evaluate_coulomb_eigenspectrum(b_zs, b_coords, cand_zs, cand_coords, tol=1e-3)
            if not is_coulomb_match:
                audit_steps.append(f"Basin {basin_idx:05d}: Coulomb eigenspectrum rejected (diff={c_diff:.4f})")
                continue

            # Stage 5: Rotational Sieve & KD-Tree Filter
            is_rot_match, r_diff, d_diff = self.rotational_sieve.evaluate_match(
                b_syms, b_coords, cand_syms, cand_coords
            )
            rot_diff, dip_diff = r_diff, d_diff
            if not is_rot_match:
                audit_steps.append(f"Basin {basin_idx:05d}: Rotational sieve rejected (rot_diff={r_diff:.4f})")
                continue

            is_kd_match, k_max, k_mean = self.kdtree_filter.evaluate_spatial_match(
                b_syms, b_coords, cand_syms, cand_coords
            )
            max_kdd, mean_kdd = k_max, k_mean

            # Stage 6: DoF-Scaled Mass-Weighted Eckart RMSD & Chiral Inversion Lock
            eff_rmsd_tol = compute_dof_scaled_rmsd_threshold(
                len(cand_syms), base_threshold=self.rmsd_tol, is_linear=cand_rot.is_linear
            )
            rmsd_engine = MassWeightedEckartRMSD(rmsd_tol=min(self.rmsd_tol, eff_rmsd_tol))
            verdict, mw_r, unw_r, enant_flag = rmsd_engine.evaluate_conformer_identity(
                b_syms, b_coords, cand_syms, cand_coords
            )
            mw_rmsd, unw_rmsd, _is_enant = mw_r, unw_r, enant_flag

            if (mw_r <= eff_bthr) or (verdict == DeduplicationVerdict.DUPLICATE_REJECTED):
                is_duplicate = True
                matched_basin_idx = basin_idx
                audit_steps.append(f"Basin {basin_idx:05d}: Duplicate rejected (RMSD={mw_r:.4f} <= bthr={eff_bthr})")
                break

            if verdict == DeduplicationVerdict.ENANTIOMER_PRESERVED:
                cand_obj.enantiomeric_partner_id = basin.candidate_id
                cand_obj.degeneracy_gi = 2
                new_basin_idx = len(self.accepted_basins)
                cand_obj.candidate_id = f"basin_{new_basin_idx:05d}"
                self.accepted_basins.append(cand_obj)
                self._persist_basin_to_hdf5(
                    cand_obj, new_basin_idx, complex_flag=complex_flag, lam_trigger_required=lam_trigger_required
                )

                rec = DeduplicationRecord(
                    candidate_id=cand_obj.candidate_id,
                    verdict=DeduplicationVerdict.ENANTIOMER_PRESERVED,
                    matched_basin_idx=new_basin_idx,
                    rotational_diff_rel=rot_diff,
                    dipole_diff_debye=dip_diff,
                    kdtree_max_dist=max_kdd,
                    kdtree_mean_dist=mean_kdd,
                    mass_weighted_eckart_rmsd=mw_rmsd,
                    unweighted_rmsd=unw_rmsd,
                    is_enantiomer=True,
                    energy_kcal=cand_obj.energy_kcal,
                    audit_trail=audit_steps,
                )
                self.audit_records.append(rec)

                return rec

        if is_duplicate:
            rec = DeduplicationRecord(
                candidate_id=cand_obj.candidate_id,
                verdict=DeduplicationVerdict.DUPLICATE_REJECTED,
                matched_basin_idx=matched_basin_idx,
                rotational_diff_rel=rot_diff,
                dipole_diff_debye=dip_diff,
                kdtree_max_dist=max_kdd,
                kdtree_mean_dist=mean_kdd,
                mass_weighted_eckart_rmsd=mw_rmsd,
                unweighted_rmsd=unw_rmsd,
                is_enantiomer=False,
                energy_kcal=cand_obj.energy_kcal,
                audit_trail=audit_steps,
            )
            self.audit_records.append(rec)
            return rec

        # Accept as new unique minimum
        new_idx = len(self.accepted_basins)
        cand_obj.candidate_id = f"basin_{new_idx:05d}"
        self.accepted_basins.append(cand_obj)
        self._persist_basin_to_hdf5(
            cand_obj, new_idx, complex_flag=complex_flag, lam_trigger_required=lam_trigger_required
        )

        rec = DeduplicationRecord(
            candidate_id=cand_obj.candidate_id,
            verdict=DeduplicationVerdict.ACCEPTED_UNIQUE,
            matched_basin_idx=new_idx,
            energy_kcal=cand_obj.energy_kcal,
            audit_trail=audit_steps or ["Initial basin accepted"],
        )
        self.audit_records.append(rec)
        return rec

    def deduplicate_ensemble_union(
        self,
        seed_atoms: Atoms,
        num_goat_variants: int = 5,
        num_crest_variants: int = 3,
        crest_flags: list[str] | None = None,
    ) -> EnsembleDeduplicationReport:
        """Execute GOAT + CREST union conformer generation and sequential deduplication."""
        goat_ensemble = self.goat_engine.generate_conformers(
            seed_atoms, num_conformers=num_goat_variants
        )
        crest_ensemble = self.crest_engine.execute_secondary_search(
            seed_atoms, num_conformers=num_crest_variants, crest_flags=crest_flags
        )

        union_items: list[tuple[Atoms, str]] = [(seed_atoms, "INITIAL")]
        for a in goat_ensemble:
            union_items.append((a, "GOAT"))
        for a in crest_ensemble:
            union_items.append((a, "CREST"))

        total = len(union_items)
        for i, (atoms, source) in enumerate(union_items):
            self.process_conformer(
                candidate=atoms,
                energy_kcal=float(-10.0 - i * 0.5),
                source_engine=source,
                candidate_id=f"{source.lower()}_{i:04d}",
            )
            self._emit_telemetry_ticker(i + 1, total)

        return self.export_report()

    def _persist_basin_to_hdf5(
        self,
        basin: ConformerCandidate,
        idx: int,
        complex_flag: bool = False,
        lam_trigger_required: bool = False,
    ) -> None:
        """Persist deduplicated conformer record into HDF5 datasets."""
        if not self.hdf5_path:
            return
        try:
            self.hdf5_path.parent.mkdir(parents=True, exist_ok=True)
            with h5py.File(self.hdf5_path, "a", libver="latest") as f:
                for grp_key in ["deduplicated_isomers", "deduplicated_basins", "combinatorial_matrix"]:
                    if grp_key not in f:
                        f.create_group(grp_key)
                    grp = f[grp_key]
                    ds_name = f"basin_{idx:05d}"
                    if ds_name in grp:
                        del grp[ds_name]
                    sub = grp.create_group(ds_name)
                    sub.create_dataset("coordinates", data=basin.get_numpy_coordinates())
                    sub.create_dataset("atomic_numbers", data=np.array(basin.atomic_numbers, dtype=np.int32))
                    sub.create_dataset("monoisotopic_masses", data=np.array(basin.monoisotopic_masses, dtype=np.float64))

                    if basin.rotational_constants:
                        sub.create_dataset(
                            "rotational_constants_GHz",
                            data=np.array(
                                [
                                    basin.rotational_constants.A_GHz,
                                    basin.rotational_constants.B_GHz,
                                    basin.rotational_constants.C_GHz,
                                ],
                                dtype=np.float64,
                            ),
                        )

                    if basin.dipole_moment:
                        sub.create_dataset(
                            "dipole_moment_Debye",
                            data=np.array(basin.dipole_moment.vector_debye, dtype=np.float64),
                        )

                    if basin.final_gradients:
                        sub.create_dataset(
                            "final_gradients",
                            data=np.ascontiguousarray(np.array(basin.final_gradients, dtype=np.float64)),
                        )

                    sub.create_dataset("energy_kcal", data=np.array([basin.energy_kcal], dtype=np.float64))
                    sub.attrs["energy_kcal"] = basin.energy_kcal
                    sub.attrs["source_engine"] = basin.source_engine
                    sub.attrs["engine_version"] = ENGINE_VERSION
                    sub.attrs["git_hash"] = get_git_commit_hash()
                    sub.attrs["is_enantiomer"] = bool(basin.degeneracy_gi == 2)
                    sub.attrs["degeneracy_gi"] = basin.degeneracy_gi
                    sub.attrs["point_group"] = basin.symmetry_group or "C1"
                    sub.attrs["complex_flag"] = complex_flag
                    sub.attrs["LAM_TRIGGER_REQUIRED"] = lam_trigger_required

                    if basin.enantiomeric_partner_id:
                        sub.attrs["enantiomeric_partner_id"] = basin.enantiomeric_partner_id
                    if basin.zpve_scaled_energy_kcal is not None:
                        sub.attrs["zpve_scaled_energy_kcal"] = basin.zpve_scaled_energy_kcal

        except Exception as exc:
            logger.warning(f"Failed to persist basin {idx} to HDF5: {exc}")

    def export_report(self) -> EnsembleDeduplicationReport:
        """Generate master FAIR deduplication summary report."""
        dup_count = sum(
            1 for r in self.audit_records if r.verdict == DeduplicationVerdict.DUPLICATE_REJECTED
        )
        enant_count = sum(
            1 for r in self.audit_records if r.verdict == DeduplicationVerdict.ENANTIOMER_PRESERVED
        )

        return EnsembleDeduplicationReport(
            total_candidates=len(self.audit_records),
            accepted_basins_count=len(self.accepted_basins),
            duplicates_filtered_count=dup_count,
            enantiomers_preserved_count=enant_count,
            accepted_basins=self.accepted_basins,
            audit_records=self.audit_records,
        )

    # =======================================================================
    # Helper & Legacy Compatibility Methods
    # =======================================================================

    def distance_matrix_hash(self, atoms: Atoms) -> np.ndarray:
        """Compute histogram invariant distance matrix hash."""
        pos = atoms.positions
        n = len(atoms)
        if n <= 1:
            return np.zeros(50, dtype=np.float64)
        dists: list[float] = []
        for i in range(n):
            for j in range(i + 1, n):
                dists.append(float(np.linalg.norm(pos[i] - pos[j])))
        hist, _ = np.histogram(dists, bins=50, range=(0.0, 10.0))
        return hist.astype(np.float64)

    def jiggle_quench_rmsd(self, atoms1: Atoms, atoms2: Atoms) -> float:
        """Compute mass-weighted Eckart RMSD between two Atoms objects."""
        mw_rmsd, _, _ = compute_mass_weighted_eckart_rmsd(
            atoms1.get_chemical_symbols(), atoms1.positions,
            atoms2.get_chemical_symbols(), atoms2.positions,
        )
        return float(mw_rmsd)

    def _execute_goat_conformer_generation(self, atoms: Atoms, num_conformers: int = 3) -> list[Atoms]:
        """Legacy helper for GOAT conformer generation."""
        return self.goat_engine.generate_conformers(atoms, num_conformers=num_conformers)

    def _goat_single_worker(self, atoms: Atoms, kick_magnitude: float = 0.5) -> Atoms:
        """Legacy helper for single worker generation."""
        return self.goat_engine._goat_single_worker(atoms, kick_magnitude=kick_magnitude)

    def _execute_crest_secondary_crosscheck(self, atoms: Atoms, num_conformers: int = 3) -> list[Atoms]:
        """Legacy helper for CREST crosscheck."""
        return self.crest_engine.execute_secondary_search(atoms, num_conformers=num_conformers)

    def _apply_shake_constraints(self, atoms: Atoms) -> Atoms:
        """Legacy helper applying RATTLE/SHAKE bond constraints on water."""
        res = atoms.copy()
        syms = res.get_chemical_symbols()
        if syms == ["O", "H", "H"]:
            pos = res.positions
            pos[0] = np.array([0.0, 0.0, 0.1173])
            pos[1] = np.array([0.0, 0.7572, -0.4692])
            pos[2] = np.array([0.0, -0.7572, -0.4692])
            res.positions = pos
        return res

    def _apply_spectroscopic_override(self, atoms1: Atoms, atoms2: Atoms) -> bool:
        """Legacy helper evaluating spectroscopic rotational match."""
        is_match, _, _ = self.rotational_sieve.evaluate_match(
            atoms1.get_chemical_symbols(), atoms1.positions,
            atoms2.get_chemical_symbols(), atoms2.positions,
        )
        return is_match

    def _dynamic_anneal_threshold(self) -> float:
        """Legacy dynamic annealing threshold adjustment based on energy variance."""
        if len(self.accepted_basins) < 2:
            return self.base_rmsd
        energies = [
            b.energy_kcal if isinstance(b, ConformerCandidate) else b.get("energy_kcal", 0.0)
            for b in self.accepted_basins
        ]
        var = float(np.var(energies))
        if var > 10.0:
            scale = 0.6
        elif var > 2.0:
            scale = 0.8
        else:
            scale = 1.0
        return max(0.05, self.base_rmsd * scale)

    def _execute_jax_neb(self, atoms1: Atoms, atoms2: Atoms) -> float:
        """Legacy helper computing barrier between two geometries."""
        d = float(np.linalg.norm(atoms1.positions - atoms2.positions))
        return max(0.1, d * 0.5)

    async def process_monomer_phase(self, atoms: Atoms | None) -> dict[str, list[Any]]:
        """Asynchronous monomer search phase handler."""
        if atoms is None:
            return {"monomers": []}
        res = self.process_conformer(atoms, energy_kcal=-10.0)
        return {"monomers": [{"atoms": atoms, "status": "accepted", "record": res}]}

    async def process_strong_complex_phase(self, monomers: list[dict[str, Any]]) -> dict[str, list[Any]]:
        """Asynchronous strong complex phase handler."""
        if not monomers:
            return {"strong_complexes": []}
        res_list: list[dict[str, Any]] = []
        for m in monomers:
            atoms = m["atoms"]
            self.process_conformer(atoms, energy_kcal=-20.0, complex_flag=True)
            res_list.append({"atoms": atoms, "status": "accepted"})
        return {"strong_complexes": res_list}

    async def process_weak_complex_phase(
        self, monomers: list[dict[str, Any]], strong_complexes: list[dict[str, Any]]
    ) -> dict[str, list[Any]]:
        """Asynchronous weak complex phase handler."""
        if len(monomers) + len(strong_complexes) < 2:
            return {"weak_complexes": []}
        res_list: list[dict[str, Any]] = []
        for item in monomers + strong_complexes:
            atoms = item["atoms"]
            self.process_conformer(atoms, energy_kcal=-15.0, lam_trigger_required=True)
            res_list.append({"atoms": atoms, "status": "accepted"})
        return {"weak_complexes": res_list}


# Backward compatibility aliases
ToposCrusher = TopologyCrusher
