import logging
logger = logging.getLogger(__name__)
#!/usr/bin/env python3
"""
CoChem-TOPOS v4.0: v4 T1 Search Pipeline - Stage 1.1 Mathematical Ingestion & Hashing
Implements Dispersion-Weighted Graph Hashing using approximate D4 C6 coefficients
to track and deduplicate non-covalent complexes mathematically prior to 3D Kabsch alignment.
"""

import os
import json
import hashlib
import logging
from typing import Any
import numpy as np
import networkx as nx
from scipy.spatial.distance import cdist
from ase.io import read
from ase import Atoms

logging.basicConfig(level=logging.INFO, format="%(asctime)s [TOPOS 1.1] %(levelname)s: %(message)s")

# Empirical Covalent Radii (Angstroms)
COVALENT_RADII = {
    1: 0.31, 6: 0.76, 7: 0.71, 8: 0.66, 9: 0.57, 
    15: 1.07, 16: 1.05, 17: 1.02, 35: 1.02
}

# Approximate Grimme D4 C6 Coefficients (atomic units) for heuristic edge weighting
# Used exclusively to mathematically differentiate weak interaction orientations
C6_HEURISTICS = {
    1: 3.14,    # H
    6: 46.6,    # C
    7: 33.6,    # N
    8: 22.0,    # O
    9: 13.9,    # F
    15: 133.0,  # P
    16: 134.0,  # S
    17: 106.0   # Cl
}

def build_dispersion_weighted_graph(atoms: Atoms) -> nx.Graph:
    """
    Builds a NetworkX graph of the molecule. Covalent bonds are unweighted (1.0).
    Non-covalent/Intermolecular contacts are weighted using C6 coefficients and 1/r^6.
    """
    coords = atoms.get_positions()
    atomic_nums = atoms.get_atomic_numbers()
    dist_matrix = cdist(coords, coords)
    
    G = nx.Graph()
    for i, z in enumerate(atomic_nums):
        G.add_node(i, z=z)
        
    num_atoms = len(atoms)
    
    # Pass 1: Covalent Topology
    covalent_edges = []
    for i in range(num_atoms):
        for j in range(i + 1, num_atoms):
            z_i, z_j = atomic_nums[i], atomic_nums[j]
            r_cov = COVALENT_RADII.get(z_i, 1.5) + COVALENT_RADII.get(z_j, 1.5)
            # 1.2x tolerance for covalent bonds
            if dist_matrix[i, j] < (r_cov * 1.2):
                G.add_edge(i, j, weight=1.0, interaction="covalent")
                covalent_edges.append((i, j))
                
    # Detect Fragments
    fragments = list(nx.connected_components(G))
    is_complex = len(fragments) > 1
    
    if is_complex:
        logging.info(f"Detected {len(fragments)} fragments. Applying D4 C6 dispersion hashing.")
        # Pass 2: Weak Interaction Topology
        # Add edges between separate fragments weighted by approximate dispersion
        for frag_idx, frag_a in enumerate(fragments):
            for frag_b in fragments[frag_idx+1:]:
                for i in frag_a:
                    for j in frag_b:
                        # Only consider intermolecular contacts under 4.5 Angstroms
                        r = dist_matrix[i, j]
                        if r < 4.5:
                            c6_i = C6_HEURISTICS.get(atomic_nums[i], 20.0)
                            c6_j = C6_HEURISTICS.get(atomic_nums[j], 20.0)
                            # Approximate dispersion weighting: sqrt(C6_i * C6_j) / r^6
                            disp_weight = np.sqrt(c6_i * c6_j) / (r**6)
                            G.add_edge(i, j, weight=round(disp_weight, 4), interaction="dispersion")

    return G, is_complex

def hash_topology(G: nx.Graph, is_complex: bool) -> str:
    """
    Generates a cryptographic hash of the NetworkX graph.
    Uses Weisfeiler-Lehman graph hashing natively to ensure isomorphism invariance
    (handles scrambled atomic indices elegantly).
    """
    # Create a string representation using the Weisfeiler-Lehman algorithm
    # Edge weights are factored in to differentiate non-covalent complexes
    def edge_attr(e) -> Any:
        return str(e.get('weight', 1.0))
        
    graph_hash_gen = nx.weisfeiler_lehman_graph_hash(G, node_attr='z', edge_attr='weight')
    
    # Shorten the hash for filesystem safety and append complex tag
    short_hash = hashlib.sha256(graph_hash_gen.encode()).hexdigest()[:8]
    prefix = "cmplx" if is_complex else "mono"
    
    return f"CCO_{prefix}_{short_hash}"

def process_input_geometry(filepath: str) -> dict:
    """Ingests an XYZ, builds the graph, and returns the strictly formatted basin seed."""
    try:
        atoms = read(filepath)
    except Exception as e:
        logging.error(f"Failed to read {filepath}: {e}")
        return {"status": "error", "reason": "invalid_format"}

    # Trap exploded geometries instantly
    if len(atoms) > 1 and np.min(cdist(atoms.positions, atoms.positions) + np.eye(len(atoms))*100) < 0.4:
        logging.warning("Geometry trapped: Unphysical atomic overlap (<0.4 A) detected.")
        return {"status": "error", "reason": "exploded_geometry"}

    G, is_complex = build_dispersion_weighted_graph(atoms)
    topo_hash = hash_topology(G, is_complex)
    
    logging.info(f"Ingestion successful. Assigned Topology Hash: {topo_hash}")
    
    return {
        "status": "success",
        "topology_hash": topo_hash,
        "is_complex": is_complex,
        "atom_count": len(atoms),
        "source_file": os.path.basename(filepath)
    }

if __name__ == "__main__":
    # Test execution hook
    logging.info("CoChem-TOPOS Ingestor loaded and ready.")