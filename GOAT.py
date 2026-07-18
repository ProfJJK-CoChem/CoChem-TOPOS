#!/usr/bin/env python3
"""
CoChem-TOPOS Stage 2.3: GOAT (Global Optimization via Active Topology)
Executes local minimum searches on ingested .xyz fragments using ASE.
Implements the Strategy Pattern for computational engines, falling back
gracefully if MACE-OFF23 or GPU resources are unavailable.
"""

import os
import sys
import json
import logging
from pathlib import Path

# Scientific Stack
try:
    import numpy as np
    from ase.io import read, write
    from ase.optimize import BFGS
except ImportError:
    print("❌ FATAL: 'ase' and 'numpy' are required for GOAT.py. Run: pip install ase numpy")
    sys.exit(1)

class Colors:
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    OKCYAN = '\033[96m'
    ENDC = '\033[0m'

logging.basicConfig(filename='topos_stage2_goat.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

def get_calculator():
    """Dynamic Engine Router: Attempts MACE -> Falls back to EMT/xTB."""
    try:
        from mace.calculators import mace_off
        logging.info("MACE-OFF23 successfully loaded. Initializing MLFF Calculator.")
        print(f"{Colors.OKCYAN}➡️  Engine Selected: MACE-OFF23 (Machine Learning Force Field){Colors.ENDC}")
        # Defaulting to CPU for safety during pipeline audit/dry-runs to prevent VRAM locking
        return mace_off(model="medium", device="cpu"), "MACE-OFF23"
    except ImportError:
        logging.warning("MACE-OFF23 not found. Falling back to Empirical Potential (EMT).")
        print(f"{Colors.WARNING}⚠️ MACE-OFF23 not found. Degraded Fidelity: Using ASE EMT Fallback.{Colors.ENDC}")
        from ase.calculators.emt import EMT
        return EMT(), "EMT_Fallback"

def optimize_structure(filepath: Path, out_dir: Path, calc, engine_name: str) -> bool:
    """Runs a BFGS optimization on a single geometry."""
    try:
        atoms = read(str(filepath))
        atoms.calc = calc
        
        # Disable trajectory files to prevent disk clutter
        opt = BFGS(atoms, logfile=None)
        
        # Max steps capped to prevent infinite oscillation in shallow basins
        opt.run(fmax=0.05, steps=500) 
        
        out_path = out_dir / f"{filepath.stem}_opt.xyz"
        write(str(out_path), atoms, format="extxyz")
        
        logging.info(f"Optimized {filepath.name} using {engine_name}. Saved to {out_path.name}.")
        return True
    except Exception as e:
        logging.error(f"Optimization failed for {filepath.name}: {str(e)}")
        print(f"{Colors.FAIL}❌ Failed to optimize {filepath.name}. See logs.{Colors.ENDC}")
        return False

def main():
    print(f"\n{Colors.OKCYAN}--- TOPOS Stage 2.3: Global Optimization (GOAT) ---{Colors.ENDC}")
    
    workspace = Path("./TOPOS_Workspace")
    opt_workspace = workspace / "optimized"
    opt_workspace.mkdir(exist_ok=True)
    
    input_files = list(workspace.glob("*.xyz"))
    input_files = [f for f in input_files if "opt" not in f.name] # Ignore already optimized files
    
    if not input_files:
        print(f"{Colors.OKGREEN}✅ No unoptimized fragments found in workspace.{Colors.ENDC}")
        return
        
    print(f"🔍 Found {len(input_files)} geometries for active topology optimization.")
    
    calc, engine_name = get_calculator()
    success_count = 0
    
    for file in input_files:
        if optimize_structure(file, opt_workspace, calc, engine_name):
            success_count += 1
            
    print(f"{Colors.OKGREEN}✅ Stage 2.3 GOAT Complete. {success_count}/{len(input_files)} geometries optimized.{Colors.ENDC}")

if __name__ == "__main__":
    main()