"""
CoChem-TOPOS: Stage 4.1 - Pipeline Master Integrator
Bridges the GOAT/Crusher deduplication loops to the Method Matrix Cascade.
"""

import logging
import h5py
from pathlib import Path

# Internal CoChem architecture imports
try:
    from cochem_topos_cascade_orchestrator import CascadeOrchestrator
except ImportError as e:
    raise ImportError(f"CRITICAL: Failed to load CascadeOrchestrator. Ensure Stage 4.0.2 is deployed. {e}")

logger = logging.getLogger("CoChem.TOPOS.MasterIntegrator")

class TOPOSMasterIntegrator:
    """
    The top-level state machine for CoChem-TOPOS.
    Scrapes the HDF5 registry for topologically unique isomers and pushes 
    them through the Method Matrix Cascade for high-fidelity thermodynamic refinement.
    """
    
    def __init__(self, config_path: str, hdf5_path: str):
        self.config_path = Path(config_path)
        self.hdf5_path = Path(hdf5_path)
        
        if not self.config_path.exists() or not self.hdf5_path.exists():
            raise FileNotFoundError("Master Integrator requires valid cochem_system_config.json and landscape.h5 paths.")
            
        # Initialize the cascade engine
        self.orchestrator = CascadeOrchestrator(
            config_path=str(self.config_path), 
            hdf5_path=str(self.hdf5_path)
        )
        logger.info("TOPOS Master Integrator initialized and bound to Cascade Engine.")

    def run_escalation_phase(self, complex_flag: bool = False):
        """
        Iterates over all deduplicated geometries in the landscape and escalates them.
        """
        logger.info("Initiating Phase 4: Method Matrix Escalation...")
        
        target_group = "/deduplicated_isomers/"
        isomer_payloads = {}
        
        # 1. Read-Only Pass: Safely extract target IDs and initial geometries
        try:
            with h5py.File(self.hdf5_path, 'r', libver='latest', swmr=True) as f:
                if target_group not in f:
                    logger.warning(f"No geometries found at {target_group}. Halting escalation.")
                    return
                
                isomer_group = f[target_group]
                for geom_id in isomer_group.keys():
                    # Extract the XYZ byte-string and decode it
                    raw_bytes = isomer_group[geom_id].get("initial_xyz", b"")
                    if raw_bytes:
                        isomer_payloads[geom_id] = raw_bytes[()].decode('utf-8')
                        
        except Exception as e:
            logger.error(f"Failed to read from SWMR database during setup: {e}")
            raise RuntimeError("Database read lock failed.") from e

        if not isomer_payloads:
            logger.info("Geometry queue is empty. Escalation phase complete.")
            return

        # 2. Execution Pass: Route each geometry through the Cascade Orchestrator
        success_count = 0
        reduced_count = 0
        fail_count = 0
        
        for geom_id, initial_xyz in isomer_payloads.items():
            logger.info(f"--- Processing Isomer: {geom_id} ---")
            try:
                # The Orchestrator inherently handles the SWMR HDF5 commits natively
                result = self.orchestrator.process_geometry(
                    geom_id=geom_id, 
                    initial_xyz=initial_xyz, 
                    complex_flag=complex_flag
                )
                
                if result["final_status"] == "SUCCESS":
                    success_count += 1
                elif "REDUCED_FIDELITY" in result["final_status"]:
                    reduced_count += 1
                    
            except Exception as e:
                logger.error(f"CRITICAL: Unhandled exception processing {geom_id}: {e}")
                fail_count += 1
                continue # Graceful failure: protect the master loop, move to next isomer

        # 3. Final Reporting
        logger.info("=== TOPOS Method Matrix Escalation Complete ===")
        logger.info(f"Total Processed: {len(isomer_payloads)}")
        logger.info(f"Successfully Reached Target Tier: {success_count}")
        logger.info(f"Halted Early (Reduced Fidelity): {reduced_count}")
        logger.info(f"Total Pipeline Failures: {fail_count}")
        
        if fail_count > 0:
            logger.warning("Some isomers failed to process entirely. Review telemetry logs.")

if __name__ == "__main__":
    # Test execution block for local CLI testing
    logging.basicConfig(level=logging.INFO)
    try:
        master = TOPOSMasterIntegrator(
            config_path="cochem_system_config.json", 
            hdf5_path="landscape.h5"
        )
        master.run_escalation_phase(complex_flag=False)
    except FileNotFoundError:
        logger.warning("Dry run skipped: Missing requisite registries in execution directory.")