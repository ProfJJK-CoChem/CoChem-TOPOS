#!/usr/bin/env python3
"""
CoChem-TOPOS v3.0: Stage 3.0 - Combinatorial Fragment Assembly
Generates a deterministic SE(3) docking grid to assemble monomer basins into weak complexes.
"""

import logging
import numpy as np
from ase import Atoms
from scipy.spatial.transform import Rotation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [TOPOS 3.0] %(levelname)s: %(message)s")

class FragmentAssembler:
    def __init__(self, radial_steps: int = 4, angular_steps: int = 6) -> None:
        self.radial_steps = radial_steps
        self.angular_steps = angular_steps

    def _generate_fibonacci_sphere(self, samples: int) -> np.ndarray:
        """Generates evenly distributed points on a unit sphere."""
        indices = np.arange(0, samples, dtype=float) + 0.5
        phi = np.arccos(1 - 2 * indices / samples)
        theta = np.pi * (1 + 5**0.5) * indices
        
        x, y, z = np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)
        return np.column_stack((x, y, z))

    def dock_fragments(self, frag_a: Atoms, frag_b: Atoms, base_distance: float = 3.5) -> list[Atoms]:
        """
        Docks Fragment B around Fragment A using a deterministic spherical grid.
        Returns a list of unoptimized seed geometries for the Complex GOAT cascade.
        """
        logging.info(f"Generating combinatorial docking grid for {len(frag_a)} + {len(frag_b)} atoms.")
        
        # Center Fragment A at origin
        pos_a = frag_a.positions - np.mean(frag_a.positions, axis=0)
        base_a = Atoms(numbers=frag_a.get_atomic_numbers(), positions=pos_a)
        
        # Center Fragment B at origin
        pos_b = frag_b.positions - np.mean(frag_b.positions, axis=0)
        
        complex_seeds = []
        vectors = self._generate_fibonacci_sphere(self.angular_steps)
        radii = np.linspace(base_distance, base_distance + 2.0, self.radial_steps)
        
        # 3 Orthogonal Rotations (X, Y, Z axes by 90 degrees) to sample orientations
        rotations = [Rotation.from_rotvec([0, 0, 0])]
        for angle in [np.pi/2, np.pi]:
            for axis in [[1,0,0], [0,1,0], [0,0,1]]:
                rotations.append(Rotation.from_rotvec(angle * np.array(axis)))
        
        for r in radii:
            for vec in vectors:
                # Translation
                translation = vec * r
                        
                for rot in rotations:
                    rotated_pos_b = rot.apply(pos_b) + translation
                    
                    seed = base_a.copy()
                    seed += Atoms(numbers=frag_b.get_atomic_numbers(), positions=rotated_pos_b)
                    complex_seeds.append(seed)
                        
        logging.info(f"Generated {len(complex_seeds)} unique complex seeds.")
        return complex_seeds

if __name__ == "__main__":
    logging.info("CoChem-TOPOS Fragment Assembler module loaded.")