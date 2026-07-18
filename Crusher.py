#!/usr/bin/env python3
"""
CoChem-TOPOS Stage 2.5: Crusher (Jiggle-Quench Deduplication)
Mathematically purges redundant thermodynamic basins to save downstream CCSD(T) time.
Tier 1: Coulomb Matrix Eigenspectrum Variance (O(N^3) Translationally Invariant)
Tier 2: Kabsch Algorithm RMSD (Rigorous spatial alignment)
"""

import os
import shutil
import logging
from pathlib import Path

try:
    import numpy as np
    from scipy.spatial.distance import cdist
    from scipy.linalg import orthogonal_procrustes
    from ase.io import read
except ImportError:
    print("❌ FATAL: 'scipy', 'numpy', and 'ase' are required for Crusher.py.")
    sys.exit(1)

class Colors:
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    OKCYAN = '\033[96m'
    ENDC = '\033[0m'

logging.basicConfig(filename='topos_stage2_crusher.log', level=logging.INFO)

# Atomic number mapping for Coulomb Matrix
ATOMIC_NUMBERS = {
    'H': 1, 'C': 6, 'N': 7, 'O': 8, 'F': 9, 'P': 15, 'S': 16, 'Cl': 17, 'Br': 35, 'I': 53
}

def get_coulomb_eigenvalues(atoms) -> np.ndarray:
    """Tier 1 Check: Generates the sorted eigenspectrum of the Coulomb Matrix."""
    coords = atoms.get_positions()
    symbols = atoms.get_chemical_symbols()
    z = np.array([ATOMIC_NUMBERS.get(s, 6) for s in symbols])
    
    n = len(z)
    mat = np.zeros((n, n))
    
    # Calculate pairwise distances (add small epsilon to diagonal to prevent div zero logic, though diagonal is handled below)
    dist = cdist(coords, coords)
    
    for i in range(n):
        for j in range(n):
            if i == j:
                mat[i, j] = 0.5 * (z[i] ** 2.4)
            else:
                mat[i, j] = (z[i] * z[j]) / dist[i, j]
                
    eigenvalues = np.linalg.eigvalsh(mat)
    eigenvalues.sort() # Sort descending/ascending to ensure permutation invariance
    return eigenvalues[::-1]

def kabsch_rmsd(coords1: np.ndarray, coords2: np.ndarray) -> float:
    """Tier 2 Check: Aligns two point clouds using Kabsch and calculates RMSD."""
    # Center to origin
    c1 = coords1 - np.mean(coords1, axis=0)
    c2 = coords2 - np.mean(coords2, axis=0)
    
    # Calculate optimal rotation matrix
    R, sca = orthogonal_procrustes(c1, c2)
    
    # Apply rotation and get RMSD
    c2_rotated = np.dot(c2, R.T)
    rmsd = np.sqrt(np.mean((c1 - c2_rotated) ** 2))
    return float(rmsd)

def deduplicate_batch(input_files: list, eigen_tol=1e-3, rmsd_tol=0.1) -> list:
    """Executes the dual-tier deduplication funnel."""
    unique_structures = []
    duplicates = []
    
    for file in input_files:
        atoms = read(str(file))
        eigen = get_coulomb_eigenvalues(atoms)
        is_duplicate = False
        
        for u_file, u_atoms, u_eigen in unique_structures:
            # Tier 1: Check Eigenspectrum Variance (Fast)
            if np.allclose(eigen, u_eigen, atol=eigen_tol):
                # Tier 2: Check Kabsch RMSD (Rigorous)
                rmsd = kabsch_rmsd(atoms.get_positions(), u_atoms.get_positions())
                if rmsd < rmsd_tol:
                    is_duplicate = True
                    duplicates.append((file, u_file, rmsd))
                    break
                    
        if not is_duplicate:
            unique_structures.append((file, atoms, eigen))
            
    return [u[0] for u in unique_structures], duplicates

def main():
    print(f"\n{Colors.OKCYAN}--- TOPOS Stage 2.5: Crusher Deduplication ---{Colors.ENDC}")
    
    opt_workspace = Path("./TOPOS_Workspace/optimized")
    dup_workspace = Path("./TOPOS_Workspace/duplicates")
    dup_workspace.mkdir(exist_ok=True)
    
    if not opt_workspace.exists():
        print(f"{Colors.WARNING}⚠️ No optimized directory found. Run GOAT.py first.{Colors.ENDC}")
        return
        
    input_files = list(opt_workspace.glob("*.xyz"))
    if not input_files:
        print(f"{Colors.WARNING}⚠️ No files to deduplicate.{Colors.ENDC}")
        return
        
    print(f"🔨 Feeding {len(input_files)} structures into the Jiggle-Quench Deduplicator...")
    
    unique_files, duplicates = deduplicate_batch(input_files)
    
    # Archive duplicates
    for dup_file, parent_file, rmsd in duplicates:
        logging.info(f"Archived {dup_file.name} as duplicate of {parent_file.name} (RMSD: {rmsd:.4f} A)")
        shutil.move(str(dup_file), str(dup_workspace / dup_file.name))
        
    print(f"{Colors.OKGREEN}✅ Deduplication Complete.{Colors.ENDC}")
    print(f"🧬 Unique thermodynamic basins preserved: {len(unique_files)}")
    print(f"🗑️  Redundant geometries mathematically archived: {len(duplicates)}")

if __name__ == "__main__":
    main()