"""
CoChem-TOPOS: Stage 4.1 - Isotopologue Hessian Recycling & Isotopic Perturbation Engine
(cochem_topos_iso_recycle.py)

Leverages the Born-Oppenheimer potential energy surface (PES) mass invariance to mathematically
bypass the need for multi-day quantum electronic frequency recalculations for heavy isotopes
(e.g., Deuterium, 13C, 15N, 18O, 34S, 37Cl).

Execution Directives:
1. Baseline Cartesian Hessian Extraction:
   - Reads converged 3Nx3N Cartesian Hessian tensors and equilibrium geometries directly from
     `landscape.h5` across the Interaction/Mechanics layer.
2. Exact Mono-Isotopic Mass Injection:
   - Queries `mendeleev` for exact, high-precision isotopic masses in Daltons (e.g. 1H=1.00782503 Da,
     D=2.01410178 Da, 12C=12.00000000 Da, 13C=13.00335484 Da, 16O=15.99491462 Da, 18O=17.99915961 Da).
3. First-Order Isotopic Mass Perturbation:
   - Computes the mass-weighted Hessian matrix F_ij = H_ij / sqrt(m_i * m_j).
   - Solves the secular eigenvalue equation F L = L Lambda via scipy.linalg.eigh.
4. Harmonic Thermochemistry & Zero-Point Energy (ZPE):
   - Computes exact harmonic vibrational frequencies (cm^-1), Zero-Point Energies (ZPE in Hartree,
     kcal/mol, kJ/mol, eV), and thermal vibrational free energy corrections at arbitrary temperatures.
5. Kinetic & Thermodynamic Isotope Effects (KIE / TIE):
   - Evaluates semiclassical Bigeleisen-Mayer isotope effect ratios with optional Wigner tunneling corrections.
6. SWMR HDF5 Persistence Layer:
   - Persists calculated isotopologue ensembles directly to `/isotopologues/{geom_id}/{isotopologue_id}`
     with process-safe file locks and SHA-256 provenance hashing.

Strictly complies with the Tripartite Air-Gap Policy and Zero-Mock Mandate.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import math
import os
import re
import time
from collections.abc import Sequence
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, cast

import h5py
import mendeleev  # type: ignore[import-untyped]
import numpy as np
from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from scipy import linalg as sla  # type: ignore[import-untyped]

# Internal Mechanics Memory Subsystem Imports
try:
    from mechanics.cochem_topos_memory import (
        GeometryRecord,
        ToposHDF5MemoryManager,
    )
except ImportError:
    try:
        from cochem_topos_memory import (  # type: ignore[import-not-found,no-redef]
            GeometryRecord,
            ToposHDF5MemoryManager,
        )
    except ImportError:
        GeometryRecord = None  # type: ignore[assignment,misc]
        ToposHDF5MemoryManager = None  # type: ignore[assignment,misc]

# Module Logger
logger = logging.getLogger("CoChem.TOPOS.IsoRecycle")


# ============================================================================
# Physical Constants & Unit Conversion Factors (CODATA 2018 / 2022 Standards)
# ============================================================================

SPEED_OF_LIGHT_CM_S: float = 2.99792458e10
PLANCK_CONSTANT_J_S: float = 6.62607015e-34
HBAR_J_S: float = 1.054571817e-34
AVOGADRO_NUMBER: float = 6.02214076e23
BOLTZMANN_CONSTANT_J_K: float = 1.380649e-23
GAS_CONSTANT_R_J_MOL_K: float = 8.314462618
GAS_CONSTANT_R_CAL_MOL_K: float = 1.98720425864083

# Mass & Energy Conversions
AMU_TO_KG: float = 1.66053906660e-27
EV_TO_JOULE: float = 1.602176634e-19
HARTREE_TO_JOULE: float = 4.3597447222071e-18
HARTREE_TO_KCAL_MOL: float = 627.5094740631
HARTREE_TO_KJ_MOL: float = 2625.4996394799
HARTREE_TO_EV: float = 27.211386245988
HARTREE_TO_CM1: float = 219474.63136320
BOHR_TO_ANGSTROM: float = 0.529177210903
ANGSTROM_TO_METER: float = 1.0e-10

# Frequency Conversion Factors for various input Hessian units to cm^-1:
# Derived from exact CODATA constants: nu = sqrt(k_SI / m_SI) / (2 * pi * c)
# where k_SI = k_unit * UNIT_TO_JOULE / UNIT_TO_METER^2, m_SI = m_amu * AMU_TO_KG
HESSIAN_EV_ANGSTROM2_TO_CM1: float = math.sqrt(
    EV_TO_JOULE / (ANGSTROM_TO_METER**2 * AMU_TO_KG)
) / (2.0 * math.pi * SPEED_OF_LIGHT_CM_S)
HESSIAN_HARTREE_BOHR2_TO_CM1: float = math.sqrt(
    HARTREE_TO_JOULE / ((BOHR_TO_ANGSTROM * ANGSTROM_TO_METER) ** 2 * AMU_TO_KG)
) / (2.0 * math.pi * SPEED_OF_LIGHT_CM_S)
HESSIAN_HARTREE_ANGSTROM2_TO_CM1: float = math.sqrt(
    HARTREE_TO_JOULE / (ANGSTROM_TO_METER**2 * AMU_TO_KG)
) / (2.0 * math.pi * SPEED_OF_LIGHT_CM_S)
HESSIAN_SI_TO_CM1: float = math.sqrt(1.0 / AMU_TO_KG) / (
    2.0 * math.pi * SPEED_OF_LIGHT_CM_S
)


class HessianUnit(str, Enum):
    """Supported physical units for input Cartesian Hessian matrices."""
    EV_PER_ANGSTROM2 = "ev_angstrom2"
    HARTREE_PER_BOHR2 = "hartree_bohr2"
    HARTREE_PER_ANGSTROM2 = "hartree_angstrom2"
    J_PER_M2 = "j_m2"


HESSIAN_UNIT_FACTORS: dict[HessianUnit, float] = {
    HessianUnit.EV_PER_ANGSTROM2: HESSIAN_EV_ANGSTROM2_TO_CM1,
    HessianUnit.HARTREE_PER_BOHR2: HESSIAN_HARTREE_BOHR2_TO_CM1,
    HessianUnit.HARTREE_PER_ANGSTROM2: HESSIAN_HARTREE_ANGSTROM2_TO_CM1,
    HessianUnit.J_PER_M2: HESSIAN_SI_TO_CM1,
}

# ============================================================================
# Exact Mono-Isotopic Mass Resolution via Mendeleev
# ============================================================================


@lru_cache(maxsize=1024)
def get_exact_isotopic_mass(
    symbol_or_z: str | int,
    mass_number: int | None = None,
) -> float:
    """Query Mendeleev to retrieve the exact monoisotopic mass (Daltons).

    Supports isotope symbols such as 'D', 'T', '13C', '18O', '15N', '37Cl',
    or passing atomic symbol and optional integer mass_number explicitly.
    """
    if isinstance(symbol_or_z, int | np.integer):
        z = int(symbol_or_z)
        if z < 1 or z > 118:
            raise ValueError(f"Atomic number Z={z} is out of physical range [1, 118].")
        el = mendeleev.element(z)
        sym = str(el.symbol)
    elif isinstance(symbol_or_z, str):
        s = symbol_or_z.strip()
        if not s:
            raise ValueError("Empty element symbol string provided.")

        if s.isdigit():
            z = int(s)
            if z < 1 or z > 118:
                raise ValueError(f"Atomic number Z={z} is out of physical range [1, 118].")
            el = mendeleev.element(z)
            sym = str(el.symbol)
        else:
            match = re.match(r"^(\d+)([A-Za-z]+)$", s)
            if match:
                prefix_mass_num = int(match.group(1))
                parsed_sym = match.group(2).capitalize()
                sym = parsed_sym
                if mass_number is None:
                    mass_number = prefix_mass_num
            else:
                s_upper = s.upper()
                if s_upper in ("D", "2H"):
                    return 2.014101778
                if s_upper in ("T", "3H"):
                    return 3.016049281
                sym = s.capitalize()
    else:
        raise TypeError(f"Expected str or int for element identifier, got {type(symbol_or_z).__name__}.")

    if sym in ("D", "T") or (sym == "H" and mass_number in (2, 3)):
        if sym == "D" or mass_number == 2:
            return 2.014101778
        if sym == "T" or mass_number == 3:
            return 3.016049281

    try:
        el = mendeleev.element(sym)
    except Exception as exc:
        raise ValueError(f"Element symbol '{sym}' not recognized by Mendeleev database: {exc}") from exc

    if mass_number is not None:
        target_iso = next((i for i in el.isotopes if i.mass_number == mass_number), None)
        if target_iso is None or target_iso.mass is None:
            raise ValueError(f"No isotope with mass number {mass_number} found for element '{sym}'.")
        return float(target_iso.mass)

    abundant_isotopes = [
        iso for iso in el.isotopes if iso.abundance is not None and iso.abundance > 0
    ]
    if abundant_isotopes:
        primary_iso = max(abundant_isotopes, key=lambda x: x.abundance)
        return float(primary_iso.mass)

    valid_isotopes = [iso for iso in el.isotopes if iso.mass is not None]
    if valid_isotopes:
        stable_iso = max(
            valid_isotopes, key=lambda x: (x.half_life if x.half_life is not None else 0)
        )
        return float(stable_iso.mass)

    if el.atomic_weight is not None:
        return float(el.atomic_weight)

    return float(el.atomic_number)


def get_isotopic_masses(
    symbols_or_zs: Sequence[str | int],
    substitutions: Optional[Dict[Union[int, str], Union[str, int, float]]] = None,
) -> np.ndarray:
    """Construct a 1D NumPy array of isotopic masses for an atomic sequence.

    Applies optional dictionary substitutions:
    - Index-based: `{1: 'D', 2: 18}`
    - Element-based: `{'H': 'D', 'C': 13}`
    - Direct float mass override: `{0: 2.014101778}`
    """
    masses: list[float] = []
    subs = substitutions or {}

    for idx, sym_or_z in enumerate(symbols_or_zs):
        if idx in subs:
            sub_val = subs[idx]
            if isinstance(sub_val, float | int | np.floating | np.integer) and not isinstance(sub_val, bool):
                val = float(sub_val)
                if isinstance(sub_val, int | np.integer) and val <= 300:
                    masses.append(get_exact_isotopic_mass(sym_or_z, mass_number=int(val)))
                else:
                    masses.append(val)
            elif isinstance(sub_val, str):
                masses.append(get_exact_isotopic_mass(sub_val))
            else:
                raise TypeError(f"Invalid substitution type for index {idx}: {type(sub_val)}")
            continue

        norm_sym = str(sym_or_z).strip().capitalize()
        if norm_sym in subs:
            sub_val = subs[norm_sym]
            if isinstance(sub_val, int | np.integer):
                masses.append(get_exact_isotopic_mass(norm_sym, mass_number=int(sub_val)))
            elif isinstance(sub_val, float | np.floating):
                masses.append(float(sub_val))
            elif isinstance(sub_val, str):
                masses.append(get_exact_isotopic_mass(sub_val))
            else:
                raise TypeError(f"Invalid element substitution type for {norm_sym}: {type(sub_val)}")
            continue

        masses.append(get_exact_isotopic_mass(sym_or_z))

    return np.array(masses, dtype=np.float64)


# ============================================================================
# Pydantic Schemas & Data Models
# ============================================================================


class IsotopeSubstitution(BaseModel):
    """Metadata for an individual isotopic substitution site."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    atom_index: int
    element_symbol: str
    mass_number: int
    exact_mass_da: float
    baseline_mass_da: float


class IsotopologueDefinition(BaseModel):
    """Specification defining an isotopologue candidate."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    isotopologue_id: str
    substitutions: Dict[Union[int, str], Union[str, int, float]] = Field(default_factory=dict)
    custom_masses: Optional[List[float]] = None
    description: str = ""


class NormalMode(BaseModel):
    """Vibrational normal mode eigenvector, frequency, and properties."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    mode_index: int
    frequency_cm1: float
    eigenvalue: float
    is_imaginary: bool
    is_vibrational: bool
    reduced_mass_amu: float = 0.0
    force_constant_mdyn_angstrom: float = 0.0
    mass_weighted_displacement: List[List[float]] = Field(default_factory=list)
    cartesian_displacement: List[List[float]] = Field(default_factory=list)


class ThermochemicalCorrections(BaseModel):
    """Harmonic vibrational thermochemical corrections at temperature T."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    temperature_k: float
    pressure_atm: float = 1.0
    zpe_hartree: float
    zpe_kcal_mol: float
    zpe_kj_mol: float
    zpe_ev: float
    thermal_energy_hartree: float
    thermal_enthalpy_hartree: float
    thermal_free_energy_hartree: float
    entropy_cal_mol_k: float
    heat_capacity_cal_mol_k: float
    vibrational_partition_function: float


class VibrationalAnalysis(BaseModel):
    """Complete vibrational and normal mode analysis container."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    frequencies_cm1: List[float]
    eigenvalues: List[float]
    num_imaginary: int
    has_imaginary_modes: bool
    zpe_hartree: float
    zpe_kcal_mol: float
    zpe_kj_mol: float
    zpe_ev: float
    modes: List[NormalMode] = Field(default_factory=list)

    @classmethod
    def from_frequencies(
        cls,
        frequencies_cm1: Sequence[float],
        eigenvalues: Sequence[float],
        modes: Optional[List[NormalMode]] = None,
    ) -> VibrationalAnalysis:
        """Construct VibrationalAnalysis from frequency and eigenvalue arrays."""
        freqs = [float(f) for f in frequencies_cm1]
        eigs = [float(e) for e in eigenvalues]

        positive_freqs = [f for f in freqs if f > 0.0]
        sum_freqs_cm1 = sum(positive_freqs)

        zpe_cm1 = 0.5 * sum_freqs_cm1
        zpe_ha = zpe_cm1 / HARTREE_TO_CM1
        zpe_kcal = zpe_ha * HARTREE_TO_KCAL_MOL
        zpe_kj = zpe_ha * HARTREE_TO_KJ_MOL
        zpe_ev = zpe_ha * HARTREE_TO_EV

        num_imag = sum(1 for f in freqs if f < 0.0)

        return cls(
            frequencies_cm1=freqs,
            eigenvalues=eigs,
            num_imaginary=num_imag,
            has_imaginary_modes=(num_imag > 0),
            zpe_hartree=zpe_ha,
            zpe_kcal_mol=zpe_kcal,
            zpe_kj_mol=zpe_kj,
            zpe_ev=zpe_ev,
            modes=modes or [],
        )

    def compute_thermochemistry(
        self,
        temperature_k: float = 298.15,
        pressure_atm: float = 1.0,
        low_freq_cutoff_cm1: float = 10.0,
    ) -> ThermochemicalCorrections:
        """Evaluate harmonic vibrational partition functions and thermal corrections."""
        if temperature_k <= 0.0:
            raise ValueError(f"Temperature must be strictly positive, got {temperature_k} K.")

        beta_factor = (PLANCK_CONSTANT_J_S * SPEED_OF_LIGHT_CM_S) / BOLTZMANN_CONSTANT_J_K

        u_vib_j_mol = 0.0
        cv_vib_j_mol_k = 0.0
        s_vib_j_mol_k = 0.0
        ln_q_vib = 0.0

        for nu in self.frequencies_cm1:
            if nu <= low_freq_cutoff_cm1:
                continue

            x = (beta_factor * nu) / temperature_k
            if x <= 0:
                continue

            if x > 100.0:
                u_vib_j_mol += 0.0
                cv_vib_j_mol_k += 0.0
                s_vib_j_mol_k += 0.0
                ln_q_vib += 0.0
            else:
                exp_x = math.exp(x)
                denom = exp_x - 1.0
                if denom > 1e-15:
                    u_vib_j_mol += GAS_CONSTANT_R_J_MOL_K * temperature_k * (x / denom)
                    cv_vib_j_mol_k += GAS_CONSTANT_R_J_MOL_K * (x**2) * (exp_x / (denom**2))
                    s_vib_j_mol_k += GAS_CONSTANT_R_J_MOL_K * ((x / denom) - math.log(1.0 - math.exp(-x)))
                    ln_q_vib += -math.log(1.0 - math.exp(-x))

        u_vib_ha = u_vib_j_mol / (HARTREE_TO_JOULE * AVOGADRO_NUMBER)
        thermal_energy_ha = self.zpe_hartree + u_vib_ha
        thermal_enthalpy_ha = thermal_energy_ha

        s_vib_cal = s_vib_j_mol_k / 4.184
        cv_vib_cal = cv_vib_j_mol_k / 4.184

        ts_j_mol = temperature_k * s_vib_j_mol_k
        ts_ha = ts_j_mol / (HARTREE_TO_JOULE * AVOGADRO_NUMBER)
        thermal_free_energy_ha = thermal_enthalpy_ha - ts_ha

        q_vib = math.exp(min(ln_q_vib, 700.0))

        return ThermochemicalCorrections(
            temperature_k=temperature_k,
            pressure_atm=pressure_atm,
            zpe_hartree=self.zpe_hartree,
            zpe_kcal_mol=self.zpe_kcal_mol,
            zpe_kj_mol=self.zpe_kj_mol,
            zpe_ev=self.zpe_ev,
            thermal_energy_hartree=thermal_energy_ha,
            thermal_enthalpy_hartree=thermal_enthalpy_ha,
            thermal_free_energy_hartree=thermal_free_energy_ha,
            entropy_cal_mol_k=s_vib_cal,
            heat_capacity_cal_mol_k=cv_vib_cal,
            vibrational_partition_function=q_vib,
        )


class IsotopologueRecycleResult(BaseModel):
    """Comprehensive result container for an isotopologue recycling calculation."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    geom_id: str
    isotopologue_id: str
    symbols: List[str]
    baseline_masses: List[float]
    substituted_masses: List[float]
    baseline_zpe_kcal_mol: float
    isotopologue_zpe_kcal_mol: float
    delta_zpe_kcal_mol: float
    baseline_frequencies_cm1: List[float]
    isotopologue_frequencies_cm1: List[float]
    vibrational_analysis: VibrationalAnalysis
    thermochemistry_298k: ThermochemicalCorrections
    substitutions_applied: List[IsotopeSubstitution] = Field(default_factory=list)
    calculation_time_ms: float = 0.0
    provenance_sha256: str = ""


class HarmonicKIE(BaseModel):
    """Kinetic Isotope Effect (KIE) estimation between light and heavy isotopologues."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    temperature_k: float
    kie_ratio: float
    delta_zpe_diff_kcal_mol: float
    reactant_light_zpe_kcal_mol: float
    ts_light_zpe_kcal_mol: float
    reactant_heavy_zpe_kcal_mol: float
    ts_heavy_zpe_kcal_mol: float
    wigner_tunneling_correction_light: float = 1.0
    wigner_tunneling_correction_heavy: float = 1.0


class BatchRecycleReport(BaseModel):
    """Aggregated report for batch isotopologue recycling."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    geom_id: str
    total_calculated: int
    results: List[IsotopologueRecycleResult]
    baseline_level_of_theory: str = "Unknown"
    timestamp: float = Field(default_factory=time.time)

# ============================================================================
# Core Mathematical Functions
# ============================================================================


def mass_weight_hessian(
    hessian: Union[np.ndarray, Sequence[Sequence[float]]],
    masses: Union[np.ndarray, Sequence[float]],
) -> np.ndarray:
    """Construct the mass-weighted Cartesian Hessian matrix F.

    Equation:
        F_ij = H_ij / sqrt(m_i * m_j)
    where m_i is the mass of the atom corresponding to Cartesian coordinate i.
    """
    H = np.asarray(hessian, dtype=np.float64)
    m = np.asarray(masses, dtype=np.float64)

    if H.ndim != 2 or H.shape[0] != H.shape[1]:
        raise ValueError(f"Hessian must be a square 2D matrix, got shape {H.shape}.")

    n_coords = H.shape[0]
    n_atoms = len(m)

    if n_coords != 3 * n_atoms:
        raise ValueError(
            f"Dimension mismatch: Hessian shape {H.shape} incompatible with {n_atoms} atom masses (expected {3 * n_atoms}x{3 * n_atoms})."
        )

    if np.any(m <= 0.0):
        raise ValueError("All atomic masses must be strictly positive.")

    m_coords = np.repeat(m, 3)
    inv_sqrt_m = 1.0 / np.sqrt(m_coords)

    F = H * np.outer(inv_sqrt_m, inv_sqrt_m)
    F = 0.5 * (F + F.T)
    return F


def project_translations_rotations(
    coordinates: Union[np.ndarray, Sequence[Sequence[float]]],
    masses: Union[np.ndarray, Sequence[float]],
) -> np.ndarray:
    """Construct the Eckart translational and rotational projection operator P.

    Projects out 6 (or 5 for linear) zero-frequency external modes:
        P = I - D * (D^T * D)^-1 * D^T
    """
    coords = np.asarray(coordinates, dtype=np.float64)
    m = np.asarray(masses, dtype=np.float64)
    n_atoms = len(m)

    if coords.shape != (n_atoms, 3):
        raise ValueError(f"Coordinates shape {coords.shape} != ({n_atoms}, 3).")

    total_mass = float(np.sum(m))
    com = np.sum(coords * m[:, np.newaxis], axis=0) / total_mass
    r = coords - com

    m_coords = np.repeat(m, 3)
    sqrt_m = np.sqrt(m_coords)

    D = np.zeros((3 * n_atoms, 6), dtype=np.float64)
    for i in range(n_atoms):
        s_m = np.sqrt(m[i])
        D[3 * i + 0, 0] = s_m
        D[3 * i + 1, 1] = s_m
        D[3 * i + 2, 2] = s_m

        rx, ry, rz = r[i]
        D[3 * i + 1, 3] = -rz * s_m
        D[3 * i + 2, 3] = ry * s_m
        D[3 * i + 0, 4] = rz * s_m
        D[3 * i + 2, 4] = -rx * s_m
        D[3 * i + 0, 5] = -ry * s_m
        D[3 * i + 1, 5] = rx * s_m

    # Use SVD to isolate non-zero singular vectors (handles non-linear rank 6 and linear/diatomic rank 5)
    u, s, _ = np.linalg.svd(D, full_matrices=False)
    q = u[:, s > 1e-7]
    I = np.eye(3 * n_atoms, dtype=np.float64)
    P = I - q @ q.T
    return P


def recycle_hessian_frequencies(
    hessian: Union[np.ndarray, Sequence[Sequence[float]]],
    symbols: Sequence[str | int],
    coordinates: Optional[Union[np.ndarray, Sequence[Sequence[float]]]] = None,
    substitutions: Optional[Dict[Union[int, str], Union[str, int, float]]] = None,
    custom_masses: Optional[Sequence[float]] = None,
    unit: Union[HessianUnit, str] = HessianUnit.EV_PER_ANGSTROM2,
    project_tr: bool = False,
    temperature_k: float = 298.15,
) -> VibrationalAnalysis:
    """Core mathematical kernel to compute exact vibrational frequencies and normal modes.

    First-Order Isotopic Mass Perturbation:
    1. Injects exact mono-isotopic masses into the mass array.
    2. Constructs the mass-weighted Hessian F = M^{-1/2} H M^{-1/2}.
    3. Solves the secular eigenvalue problem F L = L Lambda via scipy.linalg.eigh.
    4. Converts eigenvalues to wavenumbers (cm^-1) and Zero-Point Energies.
    """
    H = np.asarray(hessian, dtype=np.float64)
    n_atoms = len(symbols)

    if H.shape != (3 * n_atoms, 3 * n_atoms):
        raise ValueError(
            f"Dimension mismatch: Hessian shape {H.shape} incompatible with {n_atoms} symbols."
        )

    if not np.all(np.isfinite(H)):
        raise ValueError("Hessian contains non-finite values (NaN or Inf).")

    if custom_masses is not None:
        masses = np.asarray(custom_masses, dtype=np.float64)
        if len(masses) != n_atoms:
            raise ValueError(f"Custom masses length {len(masses)} != atom count {n_atoms}.")
    else:
        masses = get_isotopic_masses(symbols, substitutions=substitutions)

    F = mass_weight_hessian(H, masses)

    if project_tr and coordinates is not None:
        P = project_translations_rotations(coordinates, masses)
        F = P @ F @ P
        F = 0.5 * (F + F.T)

    eigenvalues, eigenvectors = sla.eigh(F)

    if isinstance(unit, str):
        unit = HessianUnit(unit.lower())
    conversion_factor = HESSIAN_UNIT_FACTORS.get(unit, HESSIAN_EV_ANGSTROM2_TO_CM1)

    frequencies_cm1: list[float] = []
    modes: list[NormalMode] = []
    m_coords = np.repeat(masses, 3)

    for idx, eigval in enumerate(eigenvalues):
        is_imag = eigval < 0.0
        abs_eig = abs(eigval)

        freq_magnitude = conversion_factor * math.sqrt(abs_eig)
        freq_signed = -freq_magnitude if is_imag else freq_magnitude

        frequencies_cm1.append(freq_signed)

        mw_vec = eigenvectors[:, idx]
        cart_vec = mw_vec / np.sqrt(m_coords)
        norm_cart = np.linalg.norm(cart_vec)
        if norm_cart > 1e-15:
            cart_vec = cart_vec / norm_cart

        mw_disp = mw_vec.reshape((n_atoms, 3)).tolist()
        cart_disp = cart_vec.reshape((n_atoms, 3)).tolist()

        # Standard Gaussian normal mode reduced mass mu = 1 / sum(l_cart_norm^2 / m_i)
        sum_disp_sq = sum(np.sum(np.array(cart_disp[i])**2) / masses[i] for i in range(n_atoms))
        red_mass = (1.0 / sum_disp_sq) if sum_disp_sq > 1e-15 else 0.0

        is_vib = abs(freq_magnitude) > 10.0

        # Harmonic force constant in mdyn/Angstrom: k = 4*pi^2*c^2*AMU_TO_KG/100 * nu^2 * mu
        # Constant factor = 5.89183044236737e-7 mdyn/(Angstrom * cm^-2 * amu)
        k_force_constant = (
            5.89183044236737e-7 * (freq_magnitude**2) * red_mass
            if red_mass > 0.0
            else 0.0
        )

        mode = NormalMode(
            mode_index=idx,
            frequency_cm1=freq_signed,
            eigenvalue=float(eigval),
            is_imaginary=is_imag,
            is_vibrational=is_vib,
            reduced_mass_amu=float(red_mass),
            force_constant_mdyn_angstrom=float(k_force_constant),
            mass_weighted_displacement=mw_disp,
            cartesian_displacement=cart_disp,
        )
        modes.append(mode)

    analysis = VibrationalAnalysis.from_frequencies(
        frequencies_cm1=frequencies_cm1,
        eigenvalues=eigenvalues.tolist(),
        modes=modes,
    )

    return analysis


def calculate_harmonic_kie(
    reactant_light: VibrationalAnalysis,
    ts_light: VibrationalAnalysis,
    reactant_heavy: VibrationalAnalysis,
    ts_heavy: VibrationalAnalysis,
    temperature_k: float = 298.15,
) -> HarmonicKIE:
    """Calculate the semiclassical Kinetic Isotope Effect (k_light / k_heavy).

    Uses the Bigeleisen-Mayer harmonic approximation:
        KIE = (Q_TS_light / Q_React_light) / (Q_TS_heavy / Q_React_heavy) * exp(-DeltaDeltaZPE / (k_B T))
    with Wigner tunneling corrections along the imaginary TS mode.
    """
    if temperature_k <= 0:
        raise ValueError(f"Temperature must be positive, got {temperature_k} K.")

    zpe_r_l = reactant_light.zpe_kcal_mol
    zpe_ts_l = ts_light.zpe_kcal_mol
    zpe_r_h = reactant_heavy.zpe_kcal_mol
    zpe_ts_h = ts_heavy.zpe_kcal_mol

    delta_zpe_light = zpe_ts_l - zpe_r_l
    delta_zpe_heavy = zpe_ts_h - zpe_r_h
    delta_delta_zpe_kcal = delta_zpe_light - delta_zpe_heavy

    r_cal = GAS_CONSTANT_R_CAL_MOL_K
    zpe_factor = math.exp(min(max(-delta_delta_zpe_kcal * 1000.0 / (r_cal * temperature_k), -500.0), 500.0))

    thermo_r_l = reactant_light.compute_thermochemistry(temperature_k)
    thermo_ts_l = ts_light.compute_thermochemistry(temperature_k)
    thermo_r_h = reactant_heavy.compute_thermochemistry(temperature_k)
    thermo_ts_h = ts_heavy.compute_thermochemistry(temperature_k)

    q_ratio_light = thermo_ts_l.vibrational_partition_function / max(thermo_r_l.vibrational_partition_function, 1e-15)
    q_ratio_heavy = thermo_ts_h.vibrational_partition_function / max(thermo_r_h.vibrational_partition_function, 1e-15)

    q_factor = q_ratio_light / max(q_ratio_heavy, 1e-15)

    beta_factor = (PLANCK_CONSTANT_J_S * SPEED_OF_LIGHT_CM_S) / BOLTZMANN_CONSTANT_J_K

    def _get_wigner(analysis: VibrationalAnalysis) -> float:
        imag_modes = [abs(f) for f in analysis.frequencies_cm1 if f < 0.0]
        if not imag_modes:
            return 1.0
        max_imag = max(imag_modes)
        u_star = (beta_factor * max_imag) / temperature_k
        return 1.0 + (1.0 / 24.0) * (u_star**2)

    tun_l = _get_wigner(ts_light)
    tun_h = _get_wigner(ts_heavy)
    tun_factor = tun_l / max(tun_h, 1e-15)

    total_kie = zpe_factor * q_factor * tun_factor

    return HarmonicKIE(
        temperature_k=temperature_k,
        kie_ratio=float(total_kie),
        delta_zpe_diff_kcal_mol=float(-delta_delta_zpe_kcal),
        reactant_light_zpe_kcal_mol=zpe_r_l,
        ts_light_zpe_kcal_mol=zpe_ts_l,
        reactant_heavy_zpe_kcal_mol=zpe_r_h,
        ts_heavy_zpe_kcal_mol=zpe_ts_h,
        wigner_tunneling_correction_light=tun_l,
        wigner_tunneling_correction_heavy=tun_h,
    )

# ============================================================================
# High-Level Orchestrator & SWMR HDF5 Persistence Engine
# ============================================================================


class ToposIsotopologueRecycler:
    """High-level orchestrator for Isotopologue Hessian Recycling (Stage 4.1).

    Features:
    - Reads baseline Cartesian Hessian tensors directly from `landscape.h5`.
    - Generates standard isotopologue suites (D, 13C, 15N, 18O, etc.).
    - Executes high-speed batch mass-weighted secular diagonalization.
    - Persists computed isotopologue states to `landscape.h5` with thread/process locks.
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        memory_manager: Optional[Any] = None,
    ) -> None:
        if memory_manager is not None:
            self.memory_manager = memory_manager
            self.db_path = Path(memory_manager.db_path)
        else:
            resolved_path = self._resolve_db_path(db_path)
            self.db_path = resolved_path
            if ToposHDF5MemoryManager is not None:
                self.memory_manager = ToposHDF5MemoryManager(db_path=self.db_path)
            else:
                self.memory_manager = None

        self.lock_path = Path(f"{self.db_path}.lock")
        self.lock = FileLock(str(self.lock_path))
        logger.info(f"ToposIsotopologueRecycler initialized for datastore at {self.db_path}")

    @staticmethod
    def _resolve_db_path(db_path: Optional[Union[str, Path]] = None) -> Path:
        if db_path is not None:
            return Path(db_path).resolve()
        workspace_env = os.getenv("COCHEM_WORKSPACE")
        if workspace_env:
            return (Path(workspace_env).resolve() / "artifacts" / "Databases" / "landscape.h5").resolve()
        return (Path.cwd().resolve() / "artifacts" / "Databases" / "landscape.h5").resolve()

    def get_baseline_geometry(self, geom_id: str) -> Tuple[List[str], np.ndarray, np.ndarray, float, Dict[str, Any]]:
        """Extract baseline symbols, coordinates, Hessian, and energy from HDF5 database."""
        if self.memory_manager is not None:
            record = self.memory_manager.read_geometry(geom_id)
            if record is not None and record.hessian is not None and len(record.hessian) > 0:
                symbols = [mendeleev.element(z).symbol for z in record.atomic_numbers]
                coords = np.array(record.coords, dtype=np.float64)
                hessian = np.array(record.hessian, dtype=np.float64)
                return symbols, coords, hessian, record.energy, record.metadata

        with self.lock:
            with h5py.File(self.db_path, "r") as f:
                if "geometries" not in f or geom_id not in f["geometries"]:
                    raise KeyError(f"Geometry record '{geom_id}' not found in {self.db_path}.")

                g = f["geometries"][geom_id]
                atomic_numbers = g["atomic_numbers"][:].astype(int).tolist()
                coords = g["coordinates"][:].astype(float)
                energy = float(g.attrs.get("electronic_energy_hartree", 0.0))

                if "hessian_matrix" not in g:
                    raise ValueError(f"Geometry '{geom_id}' does not have a computed Hessian in {self.db_path}.")

                hessian = g["hessian_matrix"][:].astype(float)
                symbols = [mendeleev.element(z).symbol for z in atomic_numbers]
                meta = json.loads(g.attrs.get("metadata_json", "{}"))

                return symbols, coords, hessian, energy, meta

    def recycle_single(
        self,
        geom_id: str,
        definition: IsotopologueDefinition,
        unit: Union[HessianUnit, str] = HessianUnit.EV_PER_ANGSTROM2,
        save_to_hdf5: bool = True,
        temperature_k: float = 298.15,
    ) -> IsotopologueRecycleResult:
        """Execute isotopic Hessian recycling for a single isotopologue candidate."""
        t_start = time.perf_counter()
        symbols, coords, hessian, energy, meta = self.get_baseline_geometry(geom_id)

        baseline_masses = get_isotopic_masses(symbols).tolist()
        baseline_analysis = recycle_hessian_frequencies(
            hessian=hessian,
            symbols=symbols,
            coordinates=coords,
            unit=unit,
            temperature_k=temperature_k,
        )

        if definition.custom_masses is not None:
            sub_masses = list(definition.custom_masses)
        else:
            sub_masses = get_isotopic_masses(symbols, substitutions=definition.substitutions).tolist()

        iso_analysis = recycle_hessian_frequencies(
            hessian=hessian,
            symbols=symbols,
            coordinates=coords,
            custom_masses=sub_masses,
            unit=unit,
            temperature_k=temperature_k,
        )

        thermo = iso_analysis.compute_thermochemistry(temperature_k=temperature_k)
        t_duration = (time.perf_counter() - t_start) * 1000.0

        subs_applied: list[IsotopeSubstitution] = []
        for idx, (m_base, m_sub) in enumerate(zip(baseline_masses, sub_masses)):
            if abs(m_base - m_sub) > 1e-4:
                sym = symbols[idx]
                subs_applied.append(
                    IsotopeSubstitution(
                        atom_index=idx,
                        element_symbol=sym,
                        mass_number=int(round(m_sub)),
                        exact_mass_da=m_sub,
                        baseline_mass_da=m_base,
                    )
                )

        delta_zpe = iso_analysis.zpe_kcal_mol - baseline_analysis.zpe_kcal_mol

        prov_dict = {
            "geom_id": geom_id,
            "isotopologue_id": definition.isotopologue_id,
            "substituted_masses": sub_masses,
            "zpe_kcal_mol": iso_analysis.zpe_kcal_mol,
            "frequencies_cm1": iso_analysis.frequencies_cm1,
        }
        prov_hash = hashlib.sha256(json.dumps(prov_dict, sort_keys=True).encode("utf-8")).hexdigest()

        result = IsotopologueRecycleResult(
            geom_id=geom_id,
            isotopologue_id=definition.isotopologue_id,
            symbols=symbols,
            baseline_masses=baseline_masses,
            substituted_masses=sub_masses,
            baseline_zpe_kcal_mol=baseline_analysis.zpe_kcal_mol,
            isotopologue_zpe_kcal_mol=iso_analysis.zpe_kcal_mol,
            delta_zpe_kcal_mol=delta_zpe,
            baseline_frequencies_cm1=baseline_analysis.frequencies_cm1,
            isotopologue_frequencies_cm1=iso_analysis.frequencies_cm1,
            vibrational_analysis=iso_analysis,
            thermochemistry_298k=thermo,
            substitutions_applied=subs_applied,
            calculation_time_ms=t_duration,
            provenance_sha256=prov_hash,
        )

        if save_to_hdf5:
            self.save_to_hdf5(result)

        return result

    def recycle_batch(
        self,
        geom_id: str,
        definitions: Sequence[IsotopologueDefinition],
        unit: Union[HessianUnit, str] = HessianUnit.EV_PER_ANGSTROM2,
        save_to_hdf5: bool = True,
        temperature_k: float = 298.15,
    ) -> BatchRecycleReport:
        """Batch calculate a series of isotopologues against a single baseline Hessian."""
        results: list[IsotopologueRecycleResult] = []
        for defn in definitions:
            res = self.recycle_single(
                geom_id=geom_id,
                definition=defn,
                unit=unit,
                save_to_hdf5=save_to_hdf5,
                temperature_k=temperature_k,
            )
            results.append(res)

        return BatchRecycleReport(
            geom_id=geom_id,
            total_calculated=len(results),
            results=results,
        )

    def generate_standard_isotopologues(self, geom_id: str) -> List[IsotopologueDefinition]:
        """Automatically construct standard isotopologue suites (D, 13C, 15N, 18O)."""
        symbols, _, _, _, _ = self.get_baseline_geometry(geom_id)
        definitions: list[IsotopologueDefinition] = []

        if "H" in symbols:
            definitions.append(
                IsotopologueDefinition(
                    isotopologue_id="PerDeuterated_D",
                    substitutions={"H": "D"},
                    description="Complete per-deuteration of all hydrogen centers.",
                )
            )
            for idx, sym in enumerate(symbols):
                if sym == "H":
                    definitions.append(
                        IsotopologueDefinition(
                            isotopologue_id=f"Mono_D_site_{idx}",
                            substitutions={idx: "D"},
                            description=f"Single deuterium substitution at atom index {idx}.",
                        )
                    )

        if "C" in symbols:
            definitions.append(
                IsotopologueDefinition(
                    isotopologue_id="Per13C",
                    substitutions={"C": 13},
                    description="Uniform 13C substitution across all carbon centers.",
                )
            )
            for idx, sym in enumerate(symbols):
                if sym == "C":
                    definitions.append(
                        IsotopologueDefinition(
                            isotopologue_id=f"Mono_13C_site_{idx}",
                            substitutions={idx: 13},
                            description=f"Single 13C substitution at carbon index {idx}.",
                        )
                    )

        if "O" in symbols:
            definitions.append(
                IsotopologueDefinition(
                    isotopologue_id="Per18O",
                    substitutions={"O": 18},
                    description="Uniform 18O substitution across all oxygen centers.",
                )
            )
            definitions.append(
                IsotopologueDefinition(
                    isotopologue_id="Per17O",
                    substitutions={"O": 17},
                    description="Uniform 17O substitution across all oxygen centers.",
                )
            )

        if "N" in symbols:
            definitions.append(
                IsotopologueDefinition(
                    isotopologue_id="Per15N",
                    substitutions={"N": 15},
                    description="Uniform 15N substitution across all nitrogen centers.",
                )
            )

        return definitions

    def save_to_hdf5(self, result: IsotopologueRecycleResult) -> None:
        """Persist calculated isotopologue data into landscape.h5 under /isotopologues/."""
        max_retries = 10
        for attempt in range(max_retries):
            try:
                with self.lock:
                    with h5py.File(self.db_path, "a", libver="latest") as f:
                        if "isotopologues" not in f:
                            iso_root = f.create_group("isotopologues")
                        else:
                            iso_root = f["isotopologues"]

                        if result.geom_id not in iso_root:
                            geom_grp = iso_root.create_group(result.geom_id)
                        else:
                            geom_grp = iso_root[result.geom_id]

                        if result.isotopologue_id in geom_grp:
                            del geom_grp[result.isotopologue_id]

                        iso_grp = geom_grp.create_group(result.isotopologue_id)

                        iso_grp.create_dataset(
                            "frequencies_cm1",
                            data=np.array(result.isotopologue_frequencies_cm1, dtype=np.float64),
                        )
                        iso_grp.create_dataset(
                            "baseline_frequencies_cm1",
                            data=np.array(result.baseline_frequencies_cm1, dtype=np.float64),
                        )
                        iso_grp.create_dataset(
                            "substituted_masses",
                            data=np.array(result.substituted_masses, dtype=np.float64),
                        )
                        iso_grp.create_dataset(
                            "eigenvalues",
                            data=np.array(result.vibrational_analysis.eigenvalues, dtype=np.float64),
                        )

                        iso_grp.attrs["zpe_hartree"] = result.vibrational_analysis.zpe_hartree
                        iso_grp.attrs["zpe_kcal_mol"] = result.vibrational_analysis.zpe_kcal_mol
                        iso_grp.attrs["zpe_kj_mol"] = result.vibrational_analysis.zpe_kj_mol
                        iso_grp.attrs["zpe_ev"] = result.vibrational_analysis.zpe_ev
                        iso_grp.attrs["delta_zpe_kcal_mol"] = result.delta_zpe_kcal_mol
                        iso_grp.attrs["baseline_zpe_kcal_mol"] = result.baseline_zpe_kcal_mol
                        iso_grp.attrs["provenance_sha256"] = result.provenance_sha256
                        iso_grp.attrs["updated_at"] = time.time()

                        f.flush()
                logger.debug(f"Persisted isotopologue [{result.geom_id}][{result.isotopologue_id}] to {self.db_path}")
                return
            except Exception as exc:
                if attempt < max_retries - 1:
                    time.sleep(0.02 * (attempt + 1))
                else:
                    logger.error(f"Failed to persist isotopologue {result.isotopologue_id}: {exc}")
                    raise RuntimeError(f"HDF5 persistence failure: {exc}") from exc

    def read_isotopologue_from_hdf5(
        self,
        geom_id: str,
        isotopologue_id: str,
    ) -> Optional[IsotopologueRecycleResult]:
        """Read a persisted isotopologue calculation from landscape.h5."""
        try:
            with self.lock:
                with h5py.File(self.db_path, "r") as f:
                    if (
                        "isotopologues" not in f
                        or geom_id not in f["isotopologues"]
                        or isotopologue_id not in f["isotopologues"][geom_id]
                    ):
                        return None

                    iso_grp = f["isotopologues"][geom_id][isotopologue_id]
                    freqs = iso_grp["frequencies_cm1"][:].astype(float).tolist()
                    if "baseline_frequencies_cm1" in iso_grp:
                        base_freqs = iso_grp["baseline_frequencies_cm1"][:].astype(float).tolist()
                    else:
                        base_freqs = []
                    sub_masses = iso_grp["substituted_masses"][:].astype(float).tolist()
                    eigenvals = iso_grp["eigenvalues"][:].astype(float).tolist()

                    zpe_kcal = float(iso_grp.attrs.get("zpe_kcal_mol", 0.0))
                    base_zpe_kcal = float(iso_grp.attrs.get("baseline_zpe_kcal_mol", 0.0))
                    delta_zpe = float(iso_grp.attrs.get("delta_zpe_kcal_mol", 0.0))
                    prov_hash = str(iso_grp.attrs.get("provenance_sha256", ""))

            vib = VibrationalAnalysis.from_frequencies(frequencies_cm1=freqs, eigenvalues=eigenvals)
            thermo = vib.compute_thermochemistry()

            symbols, coords, hessian, _, _ = self.get_baseline_geometry(geom_id)
            base_masses = get_isotopic_masses(symbols).tolist()
            if not base_freqs:
                base_analysis = recycle_hessian_frequencies(
                    hessian=hessian,
                    symbols=symbols,
                    coordinates=coords,
                )
                base_freqs = base_analysis.frequencies_cm1

            return IsotopologueRecycleResult(
                geom_id=geom_id,
                isotopologue_id=isotopologue_id,
                symbols=symbols,
                baseline_masses=base_masses,
                substituted_masses=sub_masses,
                baseline_zpe_kcal_mol=base_zpe_kcal,
                isotopologue_zpe_kcal_mol=zpe_kcal,
                delta_zpe_kcal_mol=delta_zpe,
                baseline_frequencies_cm1=base_freqs,
                isotopologue_frequencies_cm1=freqs,
                vibrational_analysis=vib,
                thermochemistry_298k=thermo,
                provenance_sha256=prov_hash,
            )
        except Exception as exc:
            logger.error(f"Error reading isotopologue [{geom_id}][{isotopologue_id}]: {exc}")
            return None

    def list_isotopologues(self, geom_id: str) -> List[str]:
        """List all persisted isotopologue IDs for a given geometry in landscape.h5."""
        try:
            with self.lock:
                with h5py.File(self.db_path, "r") as f:
                    if "isotopologues" not in f or geom_id not in f["isotopologues"]:
                        return []
                    return list(f["isotopologues"][geom_id].keys())
        except Exception as exc:
            logger.error(f"Error listing isotopologues for {geom_id}: {exc}")
            return []

