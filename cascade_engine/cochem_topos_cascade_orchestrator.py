"""
CoChem-TOPOS: Stage 4.0.2 - Cascade Orchestrator & IPC Handoff
Manages the multi-tier escalation of geometries, routing tasks through the 
Subprocess Broker and committing finalized tensors to the SWMR HDF5 registry.
"""

import logging
import json
from pathlib import Path
from typing import Dict, Any

# Internal CoChem architecture imports
from cochem_topos_cascade_matrix import get_tier_configuration, evaluate_calculation_modifiers

# Downstream/Upstream bridge placeholders (Assumes CoChem-CORE is accessible via micro-silo)
try:
    from cochem_core.subprocess_broker import SubprocessBroker
    from cochem_cascade_hdf5 import CascadeHDF5Serializer
except ImportError as e:
    logging.warning(f"CRITICAL: CoChem-CORE dependency missing during Orchestrator init. {e}")

logger = logging.getLogger("CoChem.TOPOS.CascadeOrchestrator")

class CascadeOrchestrator:
    """
    Orchestrates the escalation of geometries from low-fidelity ML potentials 
    up to wavefunction-level targets (e.g., DLPNO-CCSD(T)).
    """
    
    def __init__(self, config_path: str, hdf5_path: str):
        self.config_path = Path(config_path)
        self.hdf5_path = Path(hdf5_path)
        
        # Load Authoritative Registry
        if not self.config_path.exists():
            raise FileNotFoundError(f"Authoritative registry {self.config_path} not found. Halting.")
            
        with open(self.config_path, 'r') as f:
            self.sys_cfg = json.load(f)
            
        # Initialize the IPC Broker and HDF5 SWMR Writer
        self.broker = SubprocessBroker(config_dict=self.sys_cfg)
        self.serializer = CascadeHDF5Serializer(db_path=self.hdf5_path)
        
        # Define the exact escalation sequence
        self.escalation_sequence = ["TIER_1_SCREEN", "TIER_2_VDW", "TIER_3_BULK", "TIER_4_EQ_TARGET"]

    def process_geometry(self, geom_id: str, initial_xyz: str, complex_flag: bool = False) -> Dict[str, Any]:
        """
        Loops a single geometry through the Method Matrix cascade.
        Fails gracefully to the last successful tier if a high-tier method OOMs or diverges.
        """
        current_xyz = initial_xyz
        final_status = "SUCCESS"
        highest_completed_tier = None
        
        # Initialize default diagnostics
        diagnostics = {"t1_diagnostic": 0.0, "d1_diagnostic": 0.0}

        logger.info(f"Initiating Cascade for Geometry ID: {geom_id}")

        for tier_id in self.escalation_sequence:
            logger.info(f"Escalating {geom_id} to {tier_id}...")
            
            try:
                # 1. Fetch Tier Configuration & Modifiers
                tier_cfg = get_tier_configuration(tier_id)
                modifiers = evaluate_calculation_modifiers(
                    complex_flag=complex_flag,
                    basis_set=tier_cfg.get("keywords", ""),
                    t1_diagnostic=diagnostics["t1_diagnostic"],
                    d1_diagnostic=diagnostics["d1_diagnostic"]
                )
                
                # 2. Multireference Trap Check
                if modifiers["escalate_to_multireference"]:
                    logger.warning(f"[{geom_id}] Multireference trap triggered at {tier_id}. Halting single-reference cascade.")
                    final_status = "REDUCED_FIDELITY: Multireference required"
                    break # Break loop, save last good state
                
                # 3. Construct IPC Payload
                job_payload = {
                    "job_id": f"{geom_id}_{tier_id}",
                    "engine": tier_cfg["engine"],
                    "method": tier_cfg["method"],
                    "keywords": tier_cfg["keywords"],
                    "geometry": current_xyz,
                    "inject_counterpoise": modifiers["inject_counterpoise"]
                }
                
                # 4. Dispatch via Subprocess Broker (Blocking wait for this specific tier)
                result_payload = self.broker.execute_task(job_payload)
                
                if result_payload["status"] != "COMPLETED":
                    raise RuntimeError(f"Engine failure at {tier_id}: {result_payload.get('error', 'Unknown Error')}")
                
                # 5. Extract Results & Update State
                current_xyz = result_payload["optimized_geometry"]
                diagnostics["t1_diagnostic"] = result_payload.get("t1_diagnostic", 0.0)
                diagnostics["d1_diagnostic"] = result_payload.get("d1_diagnostic", 0.0)
                
                # 6. Flush to HDF5 securely via SWMR
                self.serializer.write_tier_data(
                    geom_id=geom_id,
                    tier_id=tier_id,
                    energy=result_payload["energy"],
                    gradient=result_payload.get("gradient_matrix", []),
                    hessian=result_payload.get("hessian_matrix", []),
                    geometry=current_xyz
                )
                
                highest_completed_tier = tier_id
                
            except Exception as e:
                logger.error(f"[{geom_id}] Cascade interrupted at {tier_id}. Reason: {e}")
                final_status = f"REDUCED_FIDELITY: Failed at {tier_id}"
                break # Halt further escalation, but do not crash the pipeline

        return {
            "geom_id": geom_id,
            "final_status": final_status,
            "highest_tier": highest_completed_tier,
            "final_geometry": current_xyz
        }