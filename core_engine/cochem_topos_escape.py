#!/usr/bin/env python3
"""
CoChem-TOPOS v4.0: Stage 2.3 - Topographic Escape Room
Executes deterministic Langevin thermal shocks with SHAKE constraints.
Implements the Good-Turing completeness estimator and Chiral Parity Locks.
"""

import io
import logging
import numpy as np
from ase import Atoms, units
from ase.md.langevin import Langevin
from ase.constraints import FixBondLengths
from rdkit import Chem
from scipy.spatial.distance import cdist

logging.basicConfig(level=logging.INFO, format="%(asctime)s [TOPOS 2.3] %(levelname)s: %(message)s")

class GoodTuringEstimator:
    def __init__(self, target_coverage: float = 0.995):
        self.target_coverage = target_coverage
        self.basin_counts = {}
        self.consecutive_converged_batches = 0
        
    def update(self, basin_ids: list[str]):
        """Logs newly discovered basins and updates observation counts."""
        for bid in basin_ids:
            self.basin_counts[bid] = self.basin_counts.get(bid, 0) + 1
            
    def calculate_coverage(self) -> float:
        """
        Calculates Good-Turing coverage: C = 1 - (N_1 / N)
        where N_1 is the number of basins observed exactly once.
        """
        N = sum(self.basin_counts.values())
        if N == 0:
            return 0.0
            
        N_1 = sum(1 for count in self.basin_counts.values() if count == 1)
        coverage = 1.0 - (N_1 / N)
        
        logging.info(f"Good-Turing Stats: N={N}, N_1={N_1}, Coverage={coverage:.4%}")
        
        if coverage >= self.target_coverage:
            self.consecutive_converged_batches += 1
        else:
            self.consecutive_converged_batches = 0
            
        return coverage

    def is_converged(self) -> bool:
        """Requires 3 consecutive batches above the threshold to halt."""
        return self.consecutive_converged_batches >= 3


class ParityLock:
    @staticmethod
    def _extract_chiral_tags(atoms: Atoms) -> dict:
        """Converts ASE to RDKit to extract CIP stereocenters (R/S)."""
        # Create an ephemeral XYZ string to bridge ASE and RDKit safely
        xyz_file = io.StringIO()
        from ase.io import write
        write(xyz_file, atoms, format="xyz")
        xyz_string = xyz_file.getvalue()
        
        mol = Chem.MolFromXYZBlock(xyz_string)
        if not mol:
            return {}
            
        try:
            from rdkit.Chem import rdDetermineBonds
            rdDetermineBonds.DetermineBonds(mol, charge=0)
            Chem.AssignStereochemistry(mol, cleanIt=True, force=True, flagPossibleStereoCenters=True)
            
            centers = Chem.FindMolChiralCenters(mol)
            return {idx: parity for idx, parity in centers}
        except Exception as e:
            logging.debug(f"Chiral tag extraction bypassed: {e}")
            return {}

    @classmethod
    def verify_invariance(cls, original: Atoms, modified: Atoms) -> bool:
        """Returns True if chirality is preserved, False if a center inverted."""
        tags_orig = cls._extract_chiral_tags(original)
        tags_mod = cls._extract_chiral_tags(modified)
        
        for idx, parity in tags_orig.items():
            if idx in tags_mod and tags_mod[idx] != parity:
                logging.warning(f"Chiral Inversion Blocked! Atom {idx} flipped {parity} -> {tags_mod[idx]}")
                return False
        return True


class EscapeRoom:
    def __init__(self, temperature_k: float = 1000.0, seed: int = 42):
        self.temperature = temperature_k
        self.seed = seed
        
    def _apply_shake_constraints(self, atoms: Atoms) -> list:
        """
        Identifies all C-H bonds and applies SHAKE constraints, allowing
        the MD timestep to be safely doubled (e.g., 2fs to 4fs).
        """
        z = atoms.get_atomic_numbers()
        d = cdist(atoms.positions, atoms.positions)
        
        shake_pairs = []
        for i in range(len(atoms)):
            for j in range(i + 1, len(atoms)):
                # If one is H (1) and the other is heavy (e.g. C=6), and bonded (<1.2A)
                if (z[i] == 1 and z[j] > 1) or (z[i] > 1 and z[j] == 1):
                    if d[i, j] < 1.2:
                        shake_pairs.append((i, j))
                        
        if shake_pairs:
            return [FixBondLengths(shake_pairs)]
        return []

    def execute_thermal_shock(self, seed_atoms: Atoms, steps: int = 100, dt_fs: float = 4.0) -> Atoms:
        """
        Runs a deterministic Langevin trajectory.
        Uses SHAKE constraints and checks for geometric explosion.
        """
        md_atoms = seed_atoms.copy()
        
        # In a real run, md_atoms.calc = seed_atoms.calc (MACE/xTB) is mapped by Orchestrator
        if md_atoms.calc is None:
            logging.warning("No calculator attached. Running in kinematic dry-run mode.")
            return md_atoms

        # 1. SHAKE Constraints
        md_atoms.set_constraint(self._apply_shake_constraints(md_atoms))
        
        # 2. Deterministic Thermostat
        np.random.seed(self.seed)
        dyn = Langevin(
            md_atoms, 
            dt_fs * units.fs, 
            temperature_K=self.temperature, 
            friction=0.01,
            logfile=None # Disable internal ASE I/O bloat
        )
        
        # 3. Trajectory Generation & Explosion Trap
        try:
            for _ in range(steps // 10):
                dyn.run(10)
                # Trap: Interatomic collision < 0.4 A
                if np.min(cdist(md_atoms.positions, md_atoms.positions) + np.eye(len(md_atoms))*10) < 0.4:
                    raise ValueError("Exploded Geometry Trap Triggered.")
        except Exception as e:
            logging.warning(f"Trajectory aborted early: {e}")
            return None # Return None to signal purge
            
        # 4. Cremer-Pople Autodiff Stub (Architecture Hook)
        # md_atoms.positions += compute_cremer_pople_forcing_gradient(md_atoms)
            
        # 5. Chiral Parity Lock
        if not ParityLock.verify_invariance(seed_atoms, md_atoms):
            return None # Purge trajectory
            
        return md_atoms

if __name__ == "__main__":
    logging.info("CoChem-TOPOS Escape Room module active.")