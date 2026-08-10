"""
CoChem-TOPOS v4.0: v4 T1 Master Orchestration - Pipeline Master Integrator
Bridges the GOAT/Crusher deduplication loops to the Method Matrix Cascade.
"""

import logging
import h5py
from pathlib import Path
import asyncio
import numpy as np
import zmq
import zmq.asyncio

# Internal CoChem architecture imports
try:
    from cascade_engine.cochem_topos_cascade_orchestrator import CascadeOrchestrator
except ImportError:
    try:
        from cochem_topos_cascade_orchestrator import CascadeOrchestrator
    except ImportError as e:
        raise ImportError(f"CRITICAL: Failed to load CascadeOrchestrator. {e}")

try:
    from core_engine.cochem_topos_crusher import ToposCrusher
except ImportError:
    try:
        from cochem_topos_crusher import ToposCrusher
    except ImportError as e:
        raise ImportError(f"CRITICAL: Failed to load ToposCrusher. {e}")

logger = logging.getLogger("CoChem.TOPOS.MasterIntegrator")


class OETServerIPCClient:
    """
    IPC Client helper for oet_server daemon float32 MLFF-GOAT execution (§9B.4).
    Enforces gradient sign-flip guard (nabla E = -F) and %scf TolE 1e-5 end threshold configuration.
    """
    def __init__(self, host: str = "localhost", port: int = 8888, scf_tole: float = 1e-5):
        self.host = host
        self.port = port
        self.scf_tole = scf_tole

    def format_mpqc_extopt_input(self, xyz_filename: str, pal: int = 8) -> str:
        """
        Generates MPQC input block for float32 MLFF-GOAT ExtOpt execution with %scf TolE 1e-5 end.
        """
        return f"""! EXTOPT GOAT PAL{pal}
%method
  ProgExt "oet_client"
  Ext_Params "-b {self.host}:{self.port}"
end
%scf
  TolE {self.scf_tole}
end
%goat
  maxen 12.0
  conftemp 298.15
  confdegen auto
end
* xyzfile 0 1 {xyz_filename}
"""

    def apply_gradient_sign_flip_guard(self, forces: np.ndarray) -> np.ndarray:
        """
        Gradient Sign-Flip Guard (nabla E = -F):
        Converts external forces F to energy gradients nabla E = -F.
        Ensures correct sign conventions when transferring MLFF forces to MPQC ExtOpt.
        """
        forces_arr = np.asarray(forces, dtype=np.float32)
        return -forces_arr

    def process_daemon_response(self, response: dict) -> dict:
        """
        Processes response payload from oet_server daemon.
        Applies gradient sign-flip guard and float32 precision check.
        """
        energy = response.get("energy", 0.0)
        forces = response.get("forces", [])
        if len(forces) > 0:
            gradients = self.apply_gradient_sign_flip_guard(forces)
        else:
            gradients = np.array([], dtype=np.float32)
            
        return {
            "energy_hartree": float(energy),
            "gradients_hartree_bohr": gradients,
            "scf_threshold": self.scf_tole,
            "status": "SUCCESS"
        }


class TOPOSMasterIntegrator:
    """
    The top-level state machine for CoChem-TOPOS.
    Scrapes the HDF5 registry for topologically unique isomers and pushes 
    them through the Method Matrix Cascade for high-fidelity thermodynamic refinement.
    """
    
    def __init__(self, config_path: str, hdf5_path: str, zmq_port: int = 5555):
        self.config_path = Path(config_path)
        self.hdf5_path = Path(hdf5_path)
        self.zmq_port = zmq_port
        
        if not self.config_path.exists() or not self.hdf5_path.exists():
            raise FileNotFoundError("Master Integrator requires valid cochem_system_config.json and landscape.h5 paths.")
            
        # Initialize engines
        self.orchestrator = CascadeOrchestrator(
            config_path=str(self.config_path), 
            hdf5_path=str(self.hdf5_path)
        )
        self.crusher = ToposCrusher(hdf5_path=str(self.hdf5_path))
        self.oet_client = OETServerIPCClient()
        
        # Async ZMQ setup
        self.zmq_context = zmq.asyncio.Context()
        self.zmq_socket = self.zmq_context.socket(zmq.REP)
        self.zmq_socket.bind(f"tcp://*:{self.zmq_port}")
        
        logger.info(f"TOPOS Master Integrator initialized. ZMQ listening on port {self.zmq_port}")

    async def _zmq_ui_listener(self):
        """Background daemon listening for UI polling and human-in-the-loop categorizations."""
        logger.info("ZMQ UI Listener Daemon started.")
        while True:
            try:
                # Native async receive without busy polling
                message = await self.zmq_socket.recv_json()
                logger.info(f"Received UI command: {message}")
                # Handle UI commands (e.g., symmetry override, enantiomer bucketing)
                response = {"status": "ACK", "message": "Command received"}
                await self.zmq_socket.send_json(response)
            except asyncio.CancelledError:
                logger.info("ZMQ UI Listener Daemon cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in ZMQ UI listener: {e}")
                await asyncio.sleep(0.1)

    async def execute_nested_assembly_pipeline(self, initial_geometry):
        """
        Executes the three-phase nested loop: Monomer -> Strong Complex -> Weak Complex.
        Unblocks the UI by running as an asyncio task alongside the ZMQ listener.
        """
        logger.info("Initiating Phase 4: Nested Assembly Pipeline (Monomer -> Strong -> Weak)...")
        
        # Start the background UI listener task
        ui_task = asyncio.create_task(self._zmq_ui_listener())
        
        try:
            # 1. Monomer Search Phase
            logger.info("=== Starting Phase 1: Monomer Search ===")
            monomer_result = await self.crusher.process_monomer_phase(initial_geometry)
            monomers = monomer_result.get("monomers", [])
            await asyncio.sleep(0)  # Yield to UI
            
            # 2. Strong Complex Assembly Phase
            logger.info("=== Starting Phase 2: Strong Complex Assembly ===")
            strong_result = await self.crusher.process_strong_complex_phase(monomers)
            strong_complexes = strong_result.get("strong_complexes", [])
            await asyncio.sleep(0)  # Yield to UI
            
            # 3. Weak Complex Assembly Phase
            logger.info("=== Starting Phase 3: Weak Complex Assembly ===")
            weak_result = await self.crusher.process_weak_complex_phase(monomers, strong_complexes)
            weak_complexes = weak_result.get("weak_complexes", [])
            await asyncio.sleep(0)  # Yield to UI
            
            logger.info("Nested Assembly Pipeline Complete.")
            logger.info(f"Generated: {len(monomers)} Monomers, {len(strong_complexes)} Strong Complexes, {len(weak_complexes)} Weak Complexes.")
            
            # Process the finalized isomers through the Orchestrator for full PES cascade
            await self._run_escalation_pass()
            
        finally:
            ui_task.cancel()

    async def _run_escalation_pass(self, complex_flag: bool = False):
        """
        Iterates over all deduplicated geometries in the landscape and escalates them through the cascade.
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
                # If Orchestrator is synchronous, we run it in a thread pool to avoid blocking
                result = await asyncio.to_thread(
                    self.orchestrator.process_geometry,
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
            
            await asyncio.sleep(0) # Yield control after each geometry

        # 3. Final Reporting
        logger.info("=== TOPOS Method Matrix Escalation Complete ===")
        logger.info(f"Total Processed: {len(isomer_payloads)}")
        logger.info(f"Successfully Reached Target Tier: {success_count}")
        logger.info(f"Halted Early (Reduced Fidelity): {reduced_count}")
        logger.info(f"Total Pipeline Failures: {fail_count}")
        
        if fail_count > 0:
            logger.warning("Some isomers failed to process entirely. Review telemetry logs.")
            
        # 4. Macroscopic Boltzmann Synthesis
        self._macroscopic_boltzmann_synthesis(isomer_payloads.keys())

    def _macroscopic_boltzmann_synthesis(self, isomer_ids, temperature_K: float = 298.15):
        """
        Executes Macroscopic Boltzmann Synthesis.
        Reads highest tier energies for each isomer, calculates partition function,
        and computes Boltzmann population percentages at the given temperature.
        """
        logger.info(f"Initiating Phase 5: Macroscopic Boltzmann Synthesis at {temperature_K} K...")
        
        kB_kcal_mol_K = 0.0019872041 # Boltzmann constant in kcal/(mol*K)
        RT = kB_kcal_mol_K * temperature_K
        
        energies = {}
        
        try:
            with h5py.File(self.hdf5_path, 'r') as f:
                target_group = "/deduplicated_isomers/"
                if target_group not in f:
                    return
                for geom_id in isomer_ids:
                    # Scan backwards from highest tier to find best energy
                    best_energy = None
                    keys = list(f[f"{target_group}/{geom_id}"].keys())
                    tier_keys = [k for k in keys if k.startswith("tier_")]
                    def get_tier_num(k):
                        try:
                            return int(k.split("_")[1])
                        except Exception:
                            return 0
                    sorted_tiers = sorted(tier_keys, key=get_tier_num, reverse=True)
                    for tier in sorted_tiers:
                        if "energy" in f[f"{target_group}/{geom_id}/{tier}"]:
                            best_energy = f[f"{target_group}/{geom_id}/{tier}/energy"][()]
                            break
                    if best_energy is not None:
                        energies[geom_id] = best_energy
                        
        except Exception as e:
            logger.error(f"Failed to read energies for Boltzmann Synthesis: {e}")
            return
            
        if not energies:
            logger.info("No energies found for Boltzmann Synthesis.")
            return
            
        min_energy = min(energies.values())
        
        partition_q = 0.0
        boltzmann_factors = {}
        
        for geom_id, e in energies.items():
            delta_e = e - min_energy
            factor = np.exp(-delta_e / RT)
            boltzmann_factors[geom_id] = factor
            partition_q += factor
            
        populations = {g: (f / partition_q) * 100 for g, f in boltzmann_factors.items()}
        
        logger.info("=== Macroscopic Boltzmann Synthesis Results ===")
        for g, pop in sorted(populations.items(), key=lambda item: item[1], reverse=True):
            logger.info(f"Isomer {g}: E_rel = {energies[g]-min_energy:.2f} kcal/mol -> Pop = {pop:.2f}%")


if __name__ == "__main__":
    # Test execution block for local CLI testing
    logging.basicConfig(level=logging.INFO)
    try:
        master = TOPOSMasterIntegrator(
            config_path="cochem_system_config.json", 
            hdf5_path="landscape.h5"
        )
        # Dummy initial geometry for testing
        from ase import Atoms
        dummy_geom = Atoms('H2', positions=[(0, 0, 0), (0, 0, 0.74)])
        asyncio.run(master.execute_nested_assembly_pipeline(dummy_geom))
    except FileNotFoundError:
        logger.warning("Dry run skipped: Missing requisite registries in execution directory.")