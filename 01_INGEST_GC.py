#!/usr/bin/env python3
"""
CoChem-TOPOS Stage 1: Smart Ingestion & Gatekeeper
Evaluates atomic connectivity using Scipy and NetworkX.
Separates non-covalent complexes into individual molecular fragments to 
prevent unphysical topologies during initial GOAT optimization.
"""

import os
import json
import logging
import numpy as np
import networkx as nx
from scipy.spatial import distance_matrix
from pathlib import Path

# Standard Covalent Radii in Angstroms (with 20% tolerance buffer for distorted geometries)
COVALENT_RADII = {
    'H': 0.31, 'C': 0.76, 'N': 0.71, 'O': 0.66, 
    'F': 0.57, 'P': 1.07, 'S': 1.05, 'Cl': 1.02, 
    'Br': 1.20, 'I': 1.39
}

TOLERANCE_MULTIPLIER = 1.20 

class Colors:
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'

logging.basicConfig(filename='topos_stage1_ingest.log', level=logging.INFO)

def load_mint_registry() -> dict:
    path = Path("cochem_mint_registry.json")
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return json.load(f)

def save_mint_registry(registry: dict):
    with open("cochem_mint_registry.json", "w") as f:
        json.dump(registry, f, indent=4)

def read_xyz(filepath: Path):
    with open(filepath, 'r') as f:
        lines = f.readlines()
    num_atoms = int(lines[0].strip())
    symbols = []
    coords = []
    for line in lines[2:2+num_atoms]:
        parts = line.split()
        symbols.append(parts[0])
        coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
    return symbols, np.array(coords)

def write_xyz(filepath: Path, symbols: list, coords: np.ndarray, comment: str):
    with open(filepath, 'w') as f:
        f.write(f"{len(symbols)}\n{comment}\n")
        for sym, coord in zip(symbols, coords):
            f.write(f"{sym:2s} {coord[0]:15.8f} {coord[1]:15.8f} {coord[2]:15.8f}\n")

def get_radius(symbol: str) -> float:
    return COVALENT_RADII.get(symbol.capitalize(), 1.50) # Fallback 1.50 for unknown

def graph_fragmentation(symbols: list, coords: np.ndarray) -> list:
    """Constructs distance matrix and extracts connected molecular fragments."""
    num_atoms = len(symbols)
    dist_mat = distance_matrix(coords, coords)
    
    G = nx.Graph()
    G.add_nodes_from(range(num_atoms))
    
    for i in range(num_atoms):
        for j in range(i + 1, num_atoms):
            max_dist = (get_radius(symbols[i]) + get_radius(symbols[j])) * TOLERANCE_MULTIPLIER
            if dist_mat[i, j] <= max_dist:
                G.add_edge(i, j)
                
    components = list(nx.connected_components(G))
    
    fragments = []
    for comp in components:
        comp_indices = sorted(list(comp))
        frag_symbols = [symbols[i] for i in comp_indices]
        frag_coords = coords[comp_indices]
        fragments.append((frag_symbols, frag_coords))
        
    return fragments

def main():
    print(f"\n--- TOPOS Stage 1: Connectivity & Fragmentation ---")
    
    registry = load_mint_registry()
    if not registry or "files" not in registry:
        print(f"{Colors.WARNING}⚠️ No MInt registry found. Please ingest files via CoChem-MInt.py first.{Colors.ENDC}")
        sys.exit(0)
        
    workspace = Path("./TOPOS_Workspace")
    workspace.mkdir(exist_ok=True)
    
    files_to_process = [k for k, v in registry["files"].items() if v.get("status") == "pending_alignment"]
    
    if not files_to_process:
        print(f"{Colors.OKGREEN}✅ No new files pending alignment.{Colors.ENDC}")
        sys.exit(0)
        
    for filename in files_to_process:
        file_info = registry["files"][filename]
        filepath = Path(file_info["path"])
        
        try:
            symbols, coords = read_xyz(filepath)
            fragments = graph_fragmentation(symbols, coords)
            
            if len(fragments) == 1:
                logging.info(f"{filename}: Single molecule detected.")
                out_path = workspace / filename
                write_xyz(out_path, symbols, coords, "TOPOS Monomer")
                file_info["topos_paths"] = [str(out_path)]
            else:
                logging.info(f"{filename}: Complex detected. Fragmented into {len(fragments)} pieces.")
                out_paths = []
                for idx, (f_sym, f_coords) in enumerate(fragments):
                    frag_name = f"{filepath.stem}_frag{idx+1}.xyz"
                    out_path = workspace / frag_name
                    write_xyz(out_path, f_sym, f_coords, f"TOPOS Fragment {idx+1}")
                    out_paths.append(str(out_path))
                file_info["topos_paths"] = out_paths
                
            file_info["status"] = "alignment_complete"
            
        except Exception as e:
            logging.error(f"Failed to process {filename}: {e}")
            file_info["status"] = "error"

    save_mint_registry(registry)
    print(f"{Colors.OKGREEN}✅ Stage 1 processing complete. Files routed to TOPOS_Workspace.{Colors.ENDC}")

if __name__ == "__main__":
    main()