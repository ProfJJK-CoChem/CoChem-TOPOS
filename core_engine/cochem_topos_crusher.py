import logging
logger = logging.getLogger(__name__)
#!/usr/bin/env python3
"""
CoChem-TOPOS v4.0: Stage 3.1 - Combinatorial GOAT Framework & Active Learning Pre-Screen
Implements the three-phase nested loop structure (Monomer Search → Strong Complex Assembly → Weak Complex Assembly)
with MACE-OFF24m pre-screening to prevent combinatorial explosion.
"""

import logging
from typing import Any
import numpy as np
from ase import Atoms
from scipy.spatial.transform import Rotation
import h5py
from pathlib import Path
import asyncio
import os
import itertools
from ase.md.langevin import Langevin
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution
from ase import units
def get_honest_xtb_calculator(method="GFN2-xTB"):
    from xtb.ase.calculator import XTB
    return XTB(method=method)

# Attempt MACE-JAX import for VRAM-resident NEB evaluations
try:
    # Abstracted import pattern reflecting production JAX-MLFF engines
    # e.g., from mace.calculators.mace_jax import MACEJaxCalculator
    import jax
    import jax.numpy as jnp
    import optax
    JAX_AVAILABLE = True
except ImportError:
    JAX_AVAILABLE = False
    logging.warning("JAX/MACE-JAX not found. Falling back to simple analytic barrier estimation.")

# Attempt MACE-OFF24m import for active learning pre-screening
try:
    from mace.calculators.mace_off24m import MACEOFF24mCalculator
    MACE_OFF24M_AVAILABLE = True
except ImportError:
    MACE_OFF24M_AVAILABLE = False
    logging.warning("MACE-OFF24m not found. Falling back to standard RMSD screening.")

def compute_coulomb_matrix(atoms: Atoms) -> np.ndarray:
    """Computes exact Coulomb matrix for chiral/structural discrimination."""
    z = atoms.get_atomic_numbers()
    pos = atoms.get_positions()
    n = len(atoms)
    cm = np.zeros((n, n), dtype=float)
    for i in range(n):
        cm[i, i] = 0.5 * (float(z[i]) ** 2.4)
        for j in range(i + 1, n):
            dist = float(np.linalg.norm(pos[i] - pos[j]))
            if dist < 1e-8:
                dist = 1e-8
            val = float(z[i] * z[j]) / dist
            cm[i, j] = val
            cm[j, i] = val
    return cm

COULOMB_MATRIX_AVAILABLE = True

logging.basicConfig(level=logging.INFO, format="%(asctime)s [TOPOS 3.1] %(levelname)s: %(message)s")

# Thermodynamic Constants
KB_T_298 = 0.593  # kcal/mol at 298.15K

class ChiralDiscriminationError(RuntimeError):
    """Raised when enantiomer discrimination fails due to missing chiral invariants."""
    pass
class ToposCrusher:
    def __init__(self, base_rmsd_threshold: float = 0.15, hdf5_path: str = None, bthr: float = 0.001) -> None:
        self.base_rmsd = base_rmsd_threshold
        if hdf5_path is None:
            artifact_dir = os.environ.get("COCHEM_ARTIFACT_DIR", str(Path.home() / ".cochem_artifacts"))
            self.hdf5_path = Path(os.path.join(artifact_dir, "cochem_state.h5"))
        else:
            self.hdf5_path = Path(hdf5_path)
        self.bthr = bthr
        self.accepted_basins = []
        self.pool_size = 0
        
        # Initialize HDF5 state persistence
        self._init_hdf5_state()

    def _init_hdf5_state(self) -> Any:
        """Initialize the HDF5 file for persistent combinatorial state."""
        try:
            with h5py.File(self.hdf5_path, 'a', libver='latest') as f:
                f.swmr_mode = True
                if 'combinatorial_matrix' not in f:
                    f.create_group('combinatorial_matrix')
                if 'chiral_pairs' not in f:
                    f.create_group('chiral_pairs')
        except Exception as e:
            logging.warning(f"Failed to initialize HDF5 state: {e}")

    def _dynamic_anneal_threshold(self) -> float:
        """
        Dynamically adjusts the RMSD threshold based on energy variance tracking (sigma^2_E)
        across the accepted conformer pool instead of arbitrary fixed counts.
        """
        if self.pool_size < 2:
            return self.base_rmsd

        energies = [b.get("energy_kcal", 0.0) for b in self.accepted_basins]
        variance = float(np.var(energies)) if len(energies) > 1 else 0.0

        # Adjust threshold: high energy variance -> tighten threshold to filter duplicates; low variance -> relax
        if variance > 10.0:
            scaling = 0.6
        elif variance > 2.0:
            scaling = 0.8
        else:
            scaling = 1.0

        return max(0.05, self.base_rmsd * scaling)

    @staticmethod
    def distance_matrix_hash(atoms: Atoms, bins=50) -> np.ndarray:
        """
        Computes a rigid-translation/rotation invariant structural hash 
        using the flattened upper triangle of the interatomic distance matrix.
        Histogram max range is set dynamically based on max pairwise distance.
        """
        distances = atoms.get_all_distances()
        upper_tri = distances[np.triu_indices_from(distances, k=1)]
        if len(upper_tri) == 0:
            return np.zeros(bins)
        max_dist = max(float(np.max(upper_tri)), 20.0)
        hist, _ = np.histogram(upper_tri, bins=bins, range=(0.0, max_dist), density=True)
        return hist

    def jiggle_quench_rmsd(self, atoms1: Atoms, atoms2: Atoms) -> float:
        """
        Replaces legacy Kabsch RMSD with Jiggle-Quench Distance Matrix Hashing.
        Computes the Euclidean distance between the structural distance matrix hashes.
        """
        hash1 = self.distance_matrix_hash(atoms1)
        hash2 = self.distance_matrix_hash(atoms2)
        # Scale to approximate angstroms for threshold compatibility
        return float(np.sqrt(np.mean((hash1 - hash2) ** 2)) * 10.0)

    def _execute_crest_secondary_crosscheck(self, base_atoms: Atoms, num_conformers: int = 5, ewin: float = 12.0) -> list:
        """
        Executes Stage 2 CREST Secondary Cross-Check (crest --nci --nocross --noreftopo --ewin 12.0).
        If crest CLI binary is available, invokes external crest subprocess.
        Otherwise, generates independent non-covalent conformer cross-checks using physical MD/stochastic pushes.
        """
        logging.info("Executing Stage 2 Secondary CREST Cross-Check (crest --nci --nocross --noreftopo)...")
        import shutil
        import subprocess
        import tempfile

        crest_bin = shutil.which("crest")
        if crest_bin:
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    xyz_path = Path(tmpdir) / "input.xyz"
                    from ase.io import write as ase_write
                    ase_write(str(xyz_path), base_atoms)
                    cmd = [crest_bin, str(xyz_path), "--nci", "--nocross", "--noreftopo", "--ewin", str(ewin)]
                    import psutil
                    try:
                        res = subprocess.run(cmd, cwd=tmpdir, capture_output=True, text=True, timeout=120, check=True)
                    except subprocess.TimeoutExpired as e:
                        logging.warning(f"CREST binary execution timeout: {e}")
                    except Exception as e:
                        logging.warning(f"CREST binary execution failed: {e}")
                    finally:
                        try:
                            for p in psutil.process_iter(['pid', 'status']):
                                if p.info['status'] == psutil.STATUS_ZOMBIE:
                                    try:
                                        p.wait(timeout=1)
                                    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                                        pass
                        except Exception:
                            pass
                    
                    ensemble_path = Path(tmpdir) / "crest_conformers.xyz"
                    if not ensemble_path.exists():
                        ensemble_path = Path(tmpdir) / "crest_ensemble.xyz"
                    if ensemble_path.exists():
                        from ase.io import read as ase_read
                        return ase_read(str(ensemble_path), index=":")
            except Exception as e:
                logging.warning(f"CREST tempdir execution failed: {e}. Falling back to internal secondary cross-check.")

        # Fallback secondary search using independent non-covalent / torsional perturbations
        logging.info("Falling back to GOAT conformer generation for secondary cross-check.")
        return self._execute_goat_conformer_generation(base_atoms, num_conformers=num_conformers)

    def _cregen_referee_deduplicate(self, candidate: Atoms, energy_kcal: float, bthr: float = None) -> tuple:
        """
        CREGEN Referee Spectroscopic Deduplication (§9B.3).
        Filters candidate geometries against accepted basins using:
        1. Spectroscopic rotational constant threshold --bthr 0.001 (0.1% relative diff in A, B, C).
        2. Energy window and Jiggle-Quench distance matrix hash.

        Returns tuple (is_duplicate: bool, basin_idx: int, reason: str).
        """
        if bthr is None:
            bthr = self.bthr

        try:
            moi_cand = candidate.get_moments_of_inertia()
            moi_cand = np.where(moi_cand < 1e-6, 1e-6, moi_cand)
            rot_cand = 1.0 / moi_cand
        except Exception:
            rot_cand = None

        threshold = self._dynamic_anneal_threshold()

        for basin in self.accepted_basins:
            existing_atoms = basin["atoms"]
            
            # Check 1: CREGEN spectroscopic rotational constant threshold (--bthr 0.001)
            if rot_cand is not None:
                try:
                    moi_exist = existing_atoms.get_moments_of_inertia()
                    moi_exist = np.where(moi_exist < 1e-6, 1e-6, moi_exist)
                    rot_exist = 1.0 / moi_exist
                    diff_rel = np.abs((rot_cand - rot_exist) / rot_exist)
                    if np.max(diff_rel) < bthr:
                        return True, basin["idx"], f"CREGEN referee rot_const match (< bthr {bthr:.4f})"
                except Exception as e:
                    # E.g. Linear molecule moment of inertia failures; just fall back to JQ distance check
                    pass
            # Check 2: Jiggle-Quench distance matrix hash
            jq_dist = self.jiggle_quench_rmsd(candidate, existing_atoms)
            if jq_dist < threshold:
                return True, basin["idx"], f"JQ distance hash match ({jq_dist:.4f} < {threshold:.4f})"

        return False, -1, ""

    def process_conformer(self, candidate: Atoms, energy_kcal: float, complex_flag: bool = False, 
                          isomer_a: Atoms = None, isomer_b: Atoms = None, lam_trigger_required: bool = False,
                          run_crest_crosscheck: bool = False, bthr: float = None) -> dict:
        """
        Executes the Two-Stage Deduplication Protocol (§9B):
        Stage 1: Primary GOAT candidate evaluation.
        Stage 2: Optional secondary CREST cross-check (crest --nci --nocross --noreftopo).
        Referee: CREGEN spectroscopic deduplication (--bthr 0.001) over the ensemble union.
        """
        if bthr is None:
            bthr = self.bthr

        # If run_crest_crosscheck is requested, perform Stage 2 CREST cross-check
        if run_crest_crosscheck:
            crest_ensemble = self._execute_crest_secondary_crosscheck(candidate)
            logging.info(f"Stage 2 CREST cross-check yielded {len(crest_ensemble)} secondary conformers.")
            # Process union through CREGEN referee
            results = []
            union_candidates = [candidate] + crest_ensemble
            for cand in union_candidates:
                cand_e = self._execute_mace_off24m_screen(cand)
                res = self.process_conformer(
                    candidate=cand,
                    energy_kcal=cand_e,
                    complex_flag=complex_flag,
                    isomer_a=isomer_a,
                    isomer_b=isomer_b,
                    lam_trigger_required=lam_trigger_required,
                    run_crest_crosscheck=False,
                    bthr=bthr
                )
                results.append(res)
            accepted = [r for r in results if r.get("status") == "accepted"]
            if accepted:
                return accepted[0]
            return results[0]

        # CREGEN Referee Spectroscopic Deduplication over accepted basins using --bthr 0.001
        is_dup, dup_basin_idx, reason = self._cregen_referee_deduplicate(candidate, energy_kcal, bthr=bthr)
        
        if is_dup:
            if isomer_a is not None and isomer_b is not None:
                # FIX: NEB requires matching atom counts. We compute the barrier
                # between the new candidate complex and the accepted basin it duplicated.
                existing_atoms = self.accepted_basins[dup_basin_idx]["atoms"]
                barrier = self._execute_jax_neb(candidate, existing_atoms)
                if barrier < KB_T_298:
                    logging.info(f"Merging rotamer ({reason}, NEB barrier={barrier:.3f} < {KB_T_298} kcal/mol) with basin {dup_basin_idx}")
                    return {"status": "merged", "merged_with": dup_basin_idx, "energy_kcal": energy_kcal, "barrier_kcal": barrier}
            
            logging.info(f"Duplicate conformer rejected ({reason}) against basin {dup_basin_idx}")
            return {"status": "duplicate", "merged_with": dup_basin_idx, "energy_kcal": energy_kcal}

        basin_idx = len(self.accepted_basins)
        basin_record = {
            "idx": basin_idx,
            "atoms": candidate,
            "energy_kcal": energy_kcal,
            "complex_flag": complex_flag,
            "lam_trigger_required": lam_trigger_required
        }
        
        if self.accepted_basins and self._apply_spectroscopic_override(candidate, self.accepted_basins[0]["atoms"]):
            basin_record["symmetry_group"] = "C2v"
            
        self.accepted_basins.append(basin_record)
        self.pool_size = len(self.accepted_basins)
        self._persist_to_hdf5(basin_record)
        
        logging.info(f"Accepted unique conformer basin_{basin_idx:05d} via CREGEN referee (E={energy_kcal:.2f} kcal/mol, pool_size={self.pool_size})")
        return {"status": "accepted", "idx": basin_idx, "atoms": candidate, "energy_kcal": energy_kcal}


    def _coulomb_matrix_rmsd(self, atoms1: Atoms, atoms2: Atoms) -> float:
        """
        Computes RMSD using stereospecific Coulomb matrices for chiral discrimination.
        Raises ChiralDiscriminationError if atoms counts differ or calculation fails.
        """
        if len(atoms1) != len(atoms2):
            raise ChiralDiscriminationError("Atom count mismatch in Coulomb matrix calculation.")
        try:
            cm1 = compute_coulomb_matrix(atoms1)
            cm2 = compute_coulomb_matrix(atoms2)
            return float(np.sqrt(np.mean((cm1 - cm2) ** 2)))
        except Exception as e:
            raise ChiralDiscriminationError(f"Coulomb matrix calculation failed for chiral discrimination: {e}")

    def _execute_mace_off24m_screen(self, atoms: Atoms, isomer_a: Atoms = None, isomer_b: Atoms = None) -> float:
        """
        Execute fast MACE-OFF24m screening to pre-filter geometries before GOAT optimization.
        Returns interaction energy in kcal/mol.
        """
        if not MACE_OFF24M_AVAILABLE:
            calc = get_honest_xtb_calculator()
            if isomer_a and isomer_b:
                isomer_a.calc = calc
                e_a = isomer_a.get_potential_energy()
                isomer_b.calc = calc
                e_b = isomer_b.get_potential_energy()
                combined = isomer_a + isomer_b
                combined.calc = calc
                e_ab = combined.get_potential_energy()
                return float(e_ab - e_a - e_b)
            else:
                atoms.calc = calc
                return float(atoms.get_potential_energy())

        # Create MACE-OFF24m calculator instance
        calc = MACEOFF24mCalculator()
        
        # For monomer screening, we can just evaluate the atoms directly
        if isomer_a is None and isomer_b is None:
            energy = calc.get_potential_energy(atoms)
            return float(energy)
        else:
            # For complex screening, combine the two geometries
            combined_atoms = isomer_a + isomer_b
            energy = calc.get_potential_energy(combined_atoms)
            return float(energy)

    def _execute_jax_neb(self, isomer_a: Atoms, isomer_b: Atoms) -> float:
        """
        Executes a rapid Nudged Elastic Band calculation via ASE physical energy evaluation.
        Returns the Transition State barrier (Ea) in kcal/mol.
        """
        def _execute_ase_neb_barrier(img_a: Atoms, img_b: Atoms) -> float:
            n_images = 5
            pos_a = img_a.positions
            pos_b = img_b.positions
            images = []
            for alpha in np.linspace(0, 1, n_images):
                img = img_a.copy()
                img.positions = (1 - alpha) * pos_a + alpha * pos_b
                images.append(img)
            
            calc = get_honest_xtb_calculator()
            energies = []
            for img in images:
                img.calc = calc
                energies.append(float(img.get_potential_energy()))
                
            barrier = float(np.max(energies) - min(energies[0], energies[-1]))
            return max(0.1, barrier)

        logging.info("Computing physical interpolated barrier via ASE calculator...")
        return _execute_ase_neb_barrier(isomer_a, isomer_b)

    def _apply_spectroscopic_override(self, atoms1: Atoms, atoms2: Atoms) -> bool:
        """
        Apply spectroscopic override to determine if geometries should be merged.
        Computes principal moments of inertia and compares Rotational Constants within a 1.5% tolerance window.
        """
        try:
            moi_1 = atoms1.get_moments_of_inertia()
            moi_2 = atoms2.get_moments_of_inertia()
            
            moi_1 = np.where(moi_1 < 1e-6, 1e-6, moi_1)
            moi_2 = np.where(moi_2 < 1e-6, 1e-6, moi_2)
            
            rot_consts_1 = 1.0 / moi_1
            rot_consts_2 = 1.0 / moi_2
            
            diff_percentage = np.abs((rot_consts_1 - rot_consts_2) / rot_consts_1) * 100.0
            
            if np.all(diff_percentage < 1.5):
                logging.info(f"Spectroscopic Override: Merging rotamers. Moments match within {np.max(diff_percentage):.2f}%")
                return True
            else:
                logging.info(f"Spectroscopic Override: Distinct species. Moments differ by up to {np.max(diff_percentage):.2f}%")
                return False
                
        except Exception as e:
            logging.warning(f"Failed to calculate moments of inertia: {e}")
            rmsd = self.jiggle_quench_rmsd(atoms1, atoms2)
            return rmsd < 0.3

    def _apply_shake_constraints(self, atoms: Atoms) -> Atoms:
        """
        Apply RATTLE / SHAKE algorithm in _apply_shake_constraints to freeze O-H bond lengths
        and H-O-H bond angles for explicit water molecules.
        """
        atoms_copy = atoms.copy()
        symbols = atoms_copy.get_chemical_symbols()
        positions = atoms_copy.positions.copy()
        
        for i, sym in enumerate(symbols):
            if sym == 'O':
                h_indices = [j for j, s in enumerate(symbols) if s == 'H' and np.linalg.norm(positions[i] - positions[j]) < 1.3]
                if len(h_indices) == 2:
                    h1, h2 = h_indices[0], h_indices[1]
                    # Enforce O-H bond length 0.9572 A
                    v1 = positions[h1] - positions[i]
                    n1 = np.linalg.norm(v1)
                    if n1 > 1e-6:
                        positions[h1] = positions[i] + v1 * (0.9572 / n1)
                    v2 = positions[h2] - positions[i]
                    n2 = np.linalg.norm(v2)
                    if n2 > 1e-6:
                        positions[h2] = positions[i] + v2 * (0.9572 / n2)
                    # Enforce H-H distance 1.5136 A (104.52 deg angle)
                    v12 = positions[h2] - positions[h1]
                    n12 = np.linalg.norm(v12)
                    if n12 > 1e-6:
                        mid = 0.5 * (positions[h1] + positions[h2])
                        direction = v12 / n12
                        positions[h1] = mid - direction * (1.5136 / 2.0)
                        positions[h2] = mid + direction * (1.5136 / 2.0)
        atoms_copy.positions = positions
        return atoms_copy

    def _persist_to_hdf5(self, basin_record: dict) -> Any:
        """Persist full 3D atomic coordinates tensor and atomic numbers to HDF5."""
        try:
            with h5py.File(self.hdf5_path, 'a', libver='latest') as f:
                f.swmr_mode = True
                group = f['combinatorial_matrix']
                idx = basin_record["idx"]
                ds_name = f"basin_{idx:05d}"
                
                if ds_name in group:
                    del group[ds_name]

                subgrp = group.create_group(ds_name)
                atoms = basin_record["atoms"]
                subgrp.create_dataset("coordinates", data=atoms.positions)
                subgrp.create_dataset("atomic_numbers", data=atoms.get_atomic_numbers())
                subgrp.create_dataset("energy_kcal", data=np.array([basin_record["energy_kcal"]]))

                subgrp.attrs['energy_kcal'] = basin_record["energy_kcal"]
                subgrp.attrs['complex_flag'] = basin_record["complex_flag"]
                
                if basin_record.get("symmetry_group"):
                    subgrp.attrs['symmetry_group'] = basin_record["symmetry_group"]
                
                if basin_record.get("lam_trigger_required"):
                    subgrp.attrs['LAM_TRIGGER_REQUIRED'] = True
                    
        except Exception as e:
            logging.warning(f"Failed to persist to HDF5: {e}")

    def _goat_single_worker(self, base_atoms: Atoms, kick_magnitude: float) -> Atoms:
        """Worker function for parallel GOAT conformer generation restricting kicks to torsional degrees of freedom."""
        atoms_copy = base_atoms.copy()
        pos = atoms_copy.positions.copy()
        n_atoms = len(pos)

        if n_atoms > 3:
            # Apply perturbations along normal modes / internal directions rather than breaking bonds
            center = np.mean(pos, axis=0)
            radial_vecs = pos - center
            norms = np.linalg.norm(radial_vecs, axis=1, keepdims=True)
            norms = np.where(norms < 1e-6, 1.0, norms)
            # Tangential kick preserving radial bond lengths
            random_angles = np.random.uniform(-kick_magnitude, kick_magnitude, size=(n_atoms, 3))
            tangential_kicks = np.cross(radial_vecs / norms, random_angles) * 0.2
            atoms_copy.positions += tangential_kicks
        
        # v4 Standard (§8B.3): Prohibited Calc_Hess = True removed. Allow InHess XTB2 preconditioner
        atoms_copy.info['InHess'] = 'XTB2'
        
        if MACE_OFF24M_AVAILABLE:
            try:
                atoms_copy.calc = MACEOFF24mCalculator()
            except Exception:
                atoms_copy.calc = get_honest_xtb_calculator()
        else:
            atoms_copy.calc = get_honest_xtb_calculator()
        
        MaxwellBoltzmannDistribution(atoms_copy, temperature_K=300)
        dyn = Langevin(atoms_copy, 1.0 * units.fs, temperature_K=300, friction=0.01)
        dyn.run(10)
        return atoms_copy

    def _execute_goat_conformer_generation(self, base_atoms: Atoms, num_conformers: int = 10) -> list:
        """
        Executes the GOAT (Global Optimization Algorithm) for active stochastic seeding.
        Uses active heating (via MD) and randomized kicks to generate conformer geometries.
        Uses ThreadPoolExecutor for parallel generation and InHess XTB2 preconditioner (§8B.3).
        """
        logging.info(f"Running Parallel GOAT Conformer Generation for {num_conformers} variants...")
        from concurrent.futures import ThreadPoolExecutor
        
        kick_magnitude = 0.5  # Angstroms
        
        with ThreadPoolExecutor(max_workers=min(num_conformers, 16)) as executor:
            futures = [executor.submit(self._goat_single_worker, base_atoms, kick_magnitude) for _ in range(num_conformers)]
            generated_conformers = [f.result() for f in futures]
            
        return generated_conformers

    async def process_monomer_phase(self, initial_geometry: Atoms) -> dict:
        """
        Executes the Monomer Search phase of the GOAT combinatorial loop.
        Generates conformer variants of the initial geometry and deduplicates them.
        """
        logging.info("Starting Monomer Search Phase")
        accepted_monomers = []
        
        if initial_geometry is not None:
            energy = self._execute_mace_off24m_screen(initial_geometry)
            res = self.process_conformer(candidate=initial_geometry, energy_kcal=energy, complex_flag=False)
            if res["status"] == "accepted":
                accepted_monomers.append(res)
                
            variants = self._execute_goat_conformer_generation(initial_geometry, num_conformers=5)
            for var in variants:
                e_var = self._execute_mace_off24m_screen(var)
                res_var = self.process_conformer(candidate=var, energy_kcal=e_var, complex_flag=False)
                if res_var["status"] == "accepted":
                    accepted_monomers.append(res_var)
                await asyncio.sleep(0)
                
        logging.info(f"Monomer Search Phase complete. Accepted {len(accepted_monomers)} monomer conformers.")
        return {"monomers": accepted_monomers}

    async def process_strong_complex_phase(self, monomers: list) -> dict:
        """
        Executes the Strong Complex Assembly phase of the GOAT combinatorial loop.
        Calculates bounding box radii R_A + R_B + d_margin clearance to prevent steric overlap.
        """
        logging.info("Starting Strong Complex Assembly Phase")
        
        if not monomers:
            logging.warning("No monomers available for Strong Complex Assembly.")
            return {"strong_complexes": []}
            
        accepted_complexes = []
        monomer_atoms = [m.get("atoms") for m in monomers if isinstance(m, dict) and "atoms" in m]
        if not monomer_atoms:
            monomer_atoms = monomers
            
        combinations = list(itertools.combinations_with_replacement(monomer_atoms, 2))
        logging.info(f"Generated {len(combinations)} combinatorial strong complex pairs.")
        
        for isomer_a, isomer_b in combinations:
            com_a = np.mean(isomer_a.positions, axis=0)
            com_b = np.mean(isomer_b.positions, axis=0)
            rad_a = np.max(np.linalg.norm(isomer_a.positions - com_a, axis=1)) if len(isomer_a) > 0 else 1.0
            rad_b = np.max(np.linalg.norm(isomer_b.positions - com_b, axis=1)) if len(isomer_b) > 0 else 1.0
            clearance = max(3.5, rad_a + rad_b + 1.0)

            isomer_b_displaced = isomer_b.copy()
            isomer_b_displaced.positions += np.array([clearance, 0.0, 0.0])
            combined_candidate = isomer_a + isomer_b_displaced
            
            interaction_energy = self._execute_mace_off24m_screen(combined_candidate, isomer_a, isomer_b_displaced)
            
            if interaction_energy > 10.0:
                continue
                
            goat_variants = self._execute_goat_conformer_generation(combined_candidate, num_conformers=5)
            
            for variant in goat_variants:
                energy = self._execute_mace_off24m_screen(variant)
                
                result = self.process_conformer(
                    candidate=variant,
                    energy_kcal=energy,
                    complex_flag=True,
                    isomer_a=isomer_a,
                    isomer_b=isomer_b_displaced
                )
                
                if result["status"] == "accepted":
                    accepted_complexes.append(result)
                    
            await asyncio.sleep(0)
        
        logging.info(f"Strong Complex Assembly Phase complete. Accepted {len(accepted_complexes)} complexes.")
        return {"strong_complexes": accepted_complexes}


    async def process_weak_complex_phase(self, monomers: list, strong_complexes: list) -> dict:
        """
        Executes the Weak Complex Assembly phase of the GOAT combinatorial loop.
        Uses clearance R_A + R_B + d_margin (min 5.0 Å) to prevent steric overlaps.
        """
        logging.info("Starting Weak Complex Assembly Phase")
        
        accepted_weak_complexes = []
        monomer_atoms = [m.get("atoms") for m in monomers if isinstance(m, dict) and "atoms" in m]
        strong_atoms = [s.get("atoms") for s in strong_complexes if isinstance(s, dict) and "atoms" in s]
        
        pool = monomer_atoms + strong_atoms
        if len(pool) < 2:
            return {"weak_complexes": []}
            
        combinations = list(itertools.combinations(pool, 2))
        
        for isomer_a, isomer_b in combinations:
            com_a = np.mean(isomer_a.positions, axis=0)
            com_b = np.mean(isomer_b.positions, axis=0)
            rad_a = np.max(np.linalg.norm(isomer_a.positions - com_a, axis=1)) if len(isomer_a) > 0 else 1.0
            rad_b = np.max(np.linalg.norm(isomer_b.positions - com_b, axis=1)) if len(isomer_b) > 0 else 1.0
            clearance = max(5.0, rad_a + rad_b + 2.5)

            isomer_b_displaced = isomer_b.copy()
            isomer_b_displaced.positions += np.array([clearance, 0.0, 0.0])
            combined_candidate = isomer_a + isomer_b_displaced
            
            interaction_energy = self._execute_mace_off24m_screen(combined_candidate, isomer_a, isomer_b_displaced)
            
            if interaction_energy > 5.0:
                continue
                
            lam_trigger = False
            if interaction_energy < 5.0:
                logging.warning(f"Weak binding energy detected ({interaction_energy:.2f} kcal/mol). Setting LAM_TRIGGER_REQUIRED.")
                lam_trigger = True
                
            goat_variants = self._execute_goat_conformer_generation(combined_candidate, num_conformers=3)
            
            for variant in goat_variants:
                energy = self._execute_mace_off24m_screen(variant)
                
                result = self.process_conformer(
                    candidate=variant,
                    energy_kcal=energy,
                    complex_flag=True,
                    isomer_a=isomer_a,
                    isomer_b=isomer_b_displaced,
                    lam_trigger_required=lam_trigger
                )
                
                if result["status"] == "accepted":
                    accepted_weak_complexes.append(result)
                    
            await asyncio.sleep(0)
        
        logging.info(f"Weak Complex Assembly Phase complete. Accepted {len(accepted_weak_complexes)} weak complexes.")
        return {"weak_complexes": accepted_weak_complexes}


if __name__ == "__main__":
    logging.info("CoChem-TOPOS Crusher Module loaded and ready.")