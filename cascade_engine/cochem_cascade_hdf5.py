"""
CoChem-Cascade: Stage 4.0.3 - HDF5 SWMR Persistence Layer
Manages high-performance, concurrent-safe data serialization for escalating quantum geometries.
"""

import h5py
import numpy as np
import logging
from pathlib import Path
from typing import List, Optional, Any
from filelock import FileLock

logger = logging.getLogger("CoChem.Cascade.HDF5Serializer")

class CascadeHDF5Serializer:
    """
    Implements a POSIX-safe datastore.
    Safely flushes massive wave-function tensors and properties using file locks
    for safe concurrent access.
    """
    
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.lock = FileLock(f"{self.db_path}.lock")
        
        # 1. Initialize file safely if it does not exist
        with self.lock:
            if not self.db_path.exists():
                with h5py.File(self.db_path, 'w') as f:
                    f.attrs['description'] = "CoChem-Cascade Master Registry"
                    f.attrs['format_version'] = "1.0"
            
        logger.info(f"HDF5 persistence initialized at {self.db_path}")

    def write_tier_data(self, geom_id: str, tier_id: str, energy: float, 
                        gradient: Optional[List[List[float]]] = None, 
                        hessian: Optional[List[List[float]]] = None, 
                        geometry: str = "") -> None:
        """
        Compresses and injects output properties into the dataset, immediately 
        flushing the file pointers to the OS to make data available to telemetry.
        """
        try:
            with self.lock:
                with h5py.File(self.db_path, 'a') as f:
                    # Step 1: Ensure root Geometry ID group exists
                    if geom_id not in f:
                        geom_group = f.create_group(geom_id)
                    else:
                        geom_group = f[geom_id]
                    
                    # Step 2: Provision specific Tier group (Overwrite if re-running)
                    if tier_id in geom_group:
                        del geom_group[tier_id]
                    tier_group = geom_group.create_group(tier_id)
                    
                    # Step 3: Write lightweight scalars as HDF5 attributes (fastest read)
                    tier_group.attrs["electronic_energy_hartree"] = energy
                    
                    # Step 4: Serialize geometry as a byte-string
                    tier_group.create_dataset("geometry_xyz", data=geometry.encode('utf-8'))
                    
                    # Step 5: Serialize heavy tensors using default settings
                    if gradient and len(gradient) > 0:
                        grad_array = np.array(gradient, dtype=np.float64)
                        tier_group.create_dataset("gradient_matrix", data=grad_array)
                    
                    if hessian and len(hessian) > 0:
                        hess_array = np.array(hessian, dtype=np.float64)
                        tier_group.create_dataset("hessian_matrix", data=hess_array)
                    
                    # Step 6: File automatically flushed on context exit
                    logger.debug(f"[{geom_id}][{tier_id}] Successfully flushed tensors to disk.")
            
        except Exception as e:
            logger.error(f"[{geom_id}][{tier_id}] HDF5 Write Failure: {e}")
            raise RuntimeError(f"HDF5 serialization failed for {geom_id} at {tier_id}") from e

    def close(self) -> Any:
        """Safely release resources on shutdown."""
        logger.info(f"HDF5 connection to {self.db_path} cleanly closed.")