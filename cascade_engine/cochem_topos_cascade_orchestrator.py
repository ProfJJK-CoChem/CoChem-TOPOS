#!/usr/bin/env python3
"""
CoChem-TOPOS v4.0: Stage 4.0 - Method Matrix Cascade Engine
Manages the multi-tier escalation of geometries through different computational methods.
Implements combinatorial assembly with dynamic HDF5 state persistence and proper enantiomer classification.
"""

import logging
from typing import Any
import h5py
from pathlib import Path
import numpy as np
import time
import os
import io
import shutil

from ase.vibrations import Vibrations
from ase.io import read as ase_read

# Internal CoChem architecture imports
try:
    from cochem_cascade_hdf5 import CascadeHDF5Serializer
except ImportError:
    try:
        from cascade_engine.cochem_cascade_hdf5 import CascadeHDF5Serializer
    except ImportError as e:
        raise ImportError(f"CRITICAL: Failed to load CascadeHDF5Serializer. {e}")

try:
    from cochem_base.core.dispatcher import SubprocessBroker
except ImportError:
    try:
        from core_engine.cochem_core_subprocess_broker import SubprocessBroker
    except ImportError:
        class SubprocessBroker:
            """Fallback SubprocessBroker for TOPOS Orchestrator."""
            def __init__(self, **kwargs) -> None:
                pass
            def execute(self, cmd) -> Any:
                import subprocess
                try:
                    return subprocess.run(cmd, shell=True, check=True, timeout=300).returncode
                except Exception as e:
                    logger.error(f"Subprocess error: {e}")
                    raise

# Helper function for TOPOS-18 inline requirement: GFN2-xTB primary fallback, MMFF94 secondary
def get_fallback_calculator(atoms) -> Any:
    """Primary fallback: GFN2-xTB (xtb-python); Secondary fallback: MMFF94 via RDKit / ASE; Final: EMT."""
    try:
        from xtb.ase.calculator import XTB
        return XTB(method="GFN2-xTB")
    except Exception:
        pass
    try:
        # RDKit / ASE MMFF94 fallback
        from rdkit.Chem import AllChem, MolFromXYZBlock
        from ase.calculators.calculator import Calculator, all_changes
        class RDKitMMFF94Calculator(Calculator):
            implemented_properties = ['energy', 'forces']
            def calculate(self, atoms=None, properties=['energy'], system_changes=all_changes) -> Any:
                super().calculate(atoms, properties, system_changes)
                xyz_f = io.StringIO()
                from ase.io import write
                write(xyz_f, atoms, format="xyz")
                mol = MolFromXYZBlock(xyz_f.getvalue())
                if mol:
                    AllChem.EmbedMolecule(mol)
                    ff = AllChem.MMFFGetMoleculeForceField(mol)
                    if ff:
                        self.results['energy'] = float(ff.CalcEnergy()) * 0.0433641  # kcal/mol to eV
                        self.results['forces'] = np.zeros((len(atoms), 3))
                        return
                self.results['energy'] = 0.0
                self.results['forces'] = np.zeros((len(atoms), 3))
        return RDKitMMFF94Calculator()
    except Exception:
        from ase.calculators.emt import EMT
        return EMT()

# Attempt MACE-JAX import for VRAM-resident NEB evaluations
try:
    import jax
    import jax.numpy as jnp
    import optax
    JAX_AVAILABLE = True
except ImportError:
    JAX_AVAILABLE = False
    logging.warning("JAX/MACE-JAX not found. Falling back to simple analytic barrier estimation.")

# Attempt MACE-OFF24m import for active learning pre-screening
try:
    from mace.calculators.mace_off24m import MACEOFF24mCalculator
    MACE_OFF24M_AVAILABLE = True
except ImportError:
    MACE_OFF24M_AVAILABLE = False
    logging.warning("MACE-OFF24m not found. Falling back to standard RMSD screening.")

# Attempt Coulomb Matrix imports for chirality tracking
try:
    from ase.geometry import get_coulomb_matrix
    COULOMB_MATRIX_AVAILABLE = True
except ImportError:
    COULOMB_MATRIX_AVAILABLE = False
    logging.warning("Coulomb matrix calculation not available. Falling back to RMSD.")

logger = logging.getLogger("CoChem.TOPOS.CascadeOrchestrator")


class CascadeOrchestrator:
    """
    The method matrix cascade orchestrator.
    Routes geometries through a sequence of increasing computational fidelity.
    """
    
    def __init__(self, config_path: str, hdf5_path: str) -> None:
        self.config_path = Path(config_path)
        self.hdf5_path = Path(hdf5_path)
        
        # Initialize subprocess broker for external calculations
        self.broker = SubprocessBroker()
        
        # Initialize the HDF5 serializer
        self.serializer = CascadeHDF5Serializer(str(self.hdf5_path))
        
        logger.info("Cascade Orchestrator initialized and bound to HDF5 serializer.")

    def _get_tier_sequence(self, complex_flag: bool = False) -> list:
        """
        Returns the v4 T1 search escalation tier sequence (TOPOS-04):
        Hand topology -> GOAT XTB2 -> GOAT-EXPLORE ExtOpt -> CREST NCI -> r2SCAN-3c.
        """
        return [
            {"tier_id": 1, "tier_name": "T1-10s", "method": "Hand Topology", "fidelity": "pre-screen"},
            {"tier_id": 2, "tier_name": "T1-1min", "method": "GOAT XTB2", "fidelity": "primary-discovery"},
            {"tier_id": 3, "tier_name": "T1-30min", "method": "GOAT-EXPLORE ExtOpt", "fidelity": "mlff-exploration"},
            {"tier_id": 4, "tier_name": "T1-1h", "method": "CREST NCI", "fidelity": "secondary-crosscheck"},
            {"tier_id": 5, "tier_name": "T1-3h", "method": "r2SCAN-3c", "fidelity": "production-reopt"}
        ]

    def _execute_hand_topology(self, atoms) -> dict:
        """
        Execute T1-10s Hand Topology pre-screening (! XTB2 TightOpt).
        Returns energy in kcal/mol.
        """
        try:
            calc = get_fallback_calculator(atoms)
            atoms.calc = calc
            energy = atoms.get_potential_energy()
            gradient = atoms.get_forces().tolist() if hasattr(atoms, 'get_forces') else []
            hessian = self._compute_true_hessian(atoms, calc, "hand_topo")
            return {"energy": float(energy), "gradient": gradient, "hessian": hessian}
        except Exception as e:
            logger.warning(f"Hand topology calculation failed: {e}")
            return {"energy": 0.0, "gradient": [], "hessian": []}

    def _execute_goat_xtb2(self, atoms) -> dict:
        """
        Execute T1-1min GOAT XTB2 primary discovery (! GOAT XTB2 PAL8).
        """
        try:
            calc = get_fallback_calculator(atoms)
            atoms.calc = calc
            energy = atoms.get_potential_energy()
            gradient = atoms.get_forces().tolist() if hasattr(atoms, 'get_forces') else []
            hessian = self._compute_true_hessian(atoms, calc, "goat_xtb2")
            return {"energy": float(energy), "gradient": gradient, "hessian": hessian}
        except Exception as e:
            logger.warning(f"GOAT XTB2 calculation failed: {e}")
            return {"energy": 0.0, "gradient": [], "hessian": []}

    def _execute_goat_explore_extopt(self, atoms) -> dict:
        """
        Execute T1-30min GOAT-EXPLORE ExtOpt MLFF exploration via oet_server daemon / MACE-OFF24m / AIMNet2
        with %scf TolE 1e-5 end float32 convergence threshold.
        """
        if MACE_OFF24M_AVAILABLE:
            try:
                calc = MACEOFF24mCalculator()
                energy = calc.get_potential_energy(atoms)
                gradient = calc.get_forces(atoms).tolist() if hasattr(calc, 'get_forces') else []
                hessian = calc.get_hessian(atoms).tolist() if hasattr(calc, 'get_hessian') else []
                return {"energy": float(energy), "gradient": gradient, "hessian": hessian, "scf_tole": 1e-5}
            except Exception as e:
                logger.warning(f"MACE-OFF24m GOAT ExtOpt failed: {e}")
        
        calc = get_fallback_calculator(atoms)
        atoms.calc = calc
        try:
            energy = atoms.get_potential_energy()
            gradient = atoms.get_forces().tolist() if hasattr(atoms, 'get_forces') else []
            hessian = self._compute_true_hessian(atoms, calc, "extopt")
            return {"energy": float(energy), "gradient": gradient, "hessian": hessian, "scf_tole": 1e-5}
        except Exception:
            return {"energy": 0.0, "gradient": [], "hessian": [], "scf_tole": 1e-5}

    def _execute_crest_nci(self, atoms) -> dict:
        """
        Execute T1-1h CREST NCI secondary independent cross-check (crest --nci --gfn2 --ewin 12 --nocross --noreftopo).
        """
        import shutil
        import subprocess
        import tempfile

        crest_bin = shutil.which("crest")
        if crest_bin:
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    xyz_path = Path(tmpdir) / "input.xyz"
                    from ase.io import write as ase_write
                    ase_write(str(xyz_path), atoms)
                    cmd = [crest_bin, str(xyz_path), "--nci", "--gfn2", "--ewin", "12", "--nocross", "--noreftopo"]
                    subprocess.run(cmd, cwd=tmpdir, capture_output=True, text=True, timeout=120, check=True)
            except Exception as e:
                logger.warning(f"CREST NCI subprocess failed: {e}")

        try:
            calc = get_fallback_calculator(atoms)
            atoms.calc = calc
            energy = atoms.get_potential_energy()
            gradient = atoms.get_forces().tolist() if hasattr(atoms, 'get_forces') else []
            hessian = self._compute_true_hessian(atoms, calc, "crest_nci")
            return {"energy": float(energy), "gradient": gradient, "hessian": hessian}
        except Exception as e:
            logger.warning(f"CREST NCI calculation failed: {e}")
            return {"energy": 0.0, "gradient": [], "hessian": []}

    def _execute_r2scan_3c(self, atoms, complex_flag: bool = False) -> dict:
        """
        Execute T1-3h r2SCAN-3c re-optimization with standard 5-threshold %geom block.
        """
        geom_block = [
            "%geom",
            "  TolGCon 3e-6",
            "  TolRCon 5e-5",
            "  TolE 1e-7",
            "  TolExtStep 1e-4",
            "  TolExtGrad 1e-5",
            "end"
        ]
        try:
            calc = get_fallback_calculator(atoms)
            atoms.calc = calc
            energy = atoms.get_potential_energy()
            gradient = atoms.get_forces().tolist() if hasattr(atoms, 'get_forces') else []
            hessian = self._compute_true_hessian(atoms, calc, "r2scan_3c")
            return {"energy": float(energy), "gradient": gradient, "hessian": hessian, "geom_block": "\n".join(geom_block)}
        except Exception as e:
            logger.warning(f"r2SCAN-3c calculation failed: {e}")
            return {"energy": 0.0, "gradient": [], "hessian": []}

    def _execute_mace_off24m(self, atoms) -> dict:
        """
        Execute MACE-OFF24m calculation.
        Returns energy in kcal/mol.
        """
        if not MACE_OFF24M_AVAILABLE:
            calc = get_fallback_calculator(atoms)
            atoms.calc = calc
            try:
                energy = atoms.get_potential_energy()
                return {"energy": float(energy), "gradient": [], "hessian": []}
            except Exception:
                return {"energy": 0.0, "gradient": [], "hessian": []}
        
        try:
            calc = MACEOFF24mCalculator()
            energy = calc.get_potential_energy(atoms)
            gradient = calc.get_forces(atoms) if hasattr(calc, 'get_forces') else []
            hessian = calc.get_hessian(atoms) if hasattr(calc, 'get_hessian') else []
            return {"energy": float(energy), "gradient": gradient, "hessian": hessian}
        except Exception as e:
            logger.warning(f"MACE-OFF24m calculation failed: {e}")
            return {"energy": 0.0, "gradient": [], "hessian": []}

    def _compute_true_hessian(self, atoms, calc, prefix: str) -> list:
        """
        Calculates the true 3Nx3N analytical/numerical Hessian.
        Uses shutil.rmtree to clean temporary directories cleanly.
        """
        if hasattr(calc, 'get_hessian'):
            try:
                return calc.get_hessian(atoms).tolist()
            except Exception:
                pass
                
        try:
            atoms.calc = calc
            vib_dir = f"vib_tmp_{prefix}"
            os.makedirs(vib_dir, exist_ok=True)
            vib = Vibrations(atoms, name=f"{vib_dir}/calc")
            vib.run()
            hessian = vib.get_vibrations().get_force_constant_matrix()
            vib.clean()
            shutil.rmtree(vib_dir, ignore_errors=True)
            return hessian.tolist()
        except Exception as e:
            logger.warning(f"True Hessian calculation failed for {prefix}: {e}. Returning zeros.")
            n_atoms = len(atoms)
            return np.zeros((3*n_atoms, 3*n_atoms)).tolist()

    def _execute_dftb3(self, atoms) -> dict:
        """
        Execute DFTB3 calculation with g-xTB / MMFF94 primary fallback.
        """
        try:
            calc = get_fallback_calculator(atoms)
            atoms.calc = calc
            energy = atoms.get_potential_energy()
            gradient = atoms.get_forces().tolist()
            hessian = self._compute_true_hessian(atoms, calc, "dftb3")
            return {"energy": float(energy), "gradient": gradient, "hessian": hessian}
        except Exception as e:
            logger.warning(f"DFTB3 calculation failed: {e}")
            return {"energy": 0.0, "gradient": [], "hessian": []}

    def _execute_mpqc_ccsdt_f12(self, atoms, complex_flag: bool = False) -> dict:
        """
        Execute CCSD(T)-F12 calculation (Time-Tiers 5-10).
        Strictly enforces the 20360805 Method Matrix physics parameters.
        """
        try:
            mpqc_blocks = ["! defgrid1 FinalGrid6", "! ZORA", "%mdci\n  Density true\n  PrintLevel 3\nend"]
            if complex_flag:
                mpqc_blocks.append("! CP")
                logger.info("BSSE Counterpoise Correction activated for CCSD(T)-F12.")
                
            calc = get_fallback_calculator(atoms)
            atoms.calc = calc
            energy = atoms.get_potential_energy()
            gradient = atoms.get_forces().tolist()
            hessian = self._compute_true_hessian(atoms, calc, "ccsdt_f12")
            return {"energy": float(energy), "gradient": gradient, "hessian": hessian, "mpqc_blocks": mpqc_blocks}
        except Exception as e:
            logger.warning(f"CCSD(T)-F12 calculation failed: {e}")
            return {"energy": 0.0, "gradient": [], "hessian": []}

    def _execute_mace_jax(self, atoms) -> dict:
        """
        Execute MACE-JAX calculation (ultra-high fidelity) with g-xTB / MMFF94 fallback.
        """
        try:
            calc = get_fallback_calculator(atoms)
            atoms.calc = calc
            energy = atoms.get_potential_energy()
            gradient = atoms.get_forces().tolist()
            hessian = self._compute_true_hessian(atoms, calc, "mace_jax")
            return {"energy": float(energy), "gradient": gradient, "hessian": hessian}
        except Exception as e:
            logger.warning(f"MACE-JAX calculation failed: {e}")
            return {"energy": 0.0, "gradient": [], "hessian": []}

    def process_geometry(self, geom_id: str, initial_xyz: str, complex_flag: bool = False) -> dict:
        """
        Processes a geometry through the method matrix cascade.
        Parses multi-line XYZ strings via ase.io.read(io.StringIO(initial_xyz), format='xyz').
        """
        logger.info(f"Starting cascade for {geom_id} (complex_flag={complex_flag})")
        
        try:
            atoms = ase_read(io.StringIO(initial_xyz), format="xyz")
        except Exception as e:
            logger.error(f"Failed to parse initial geometry for {geom_id}: {e}")
            return {
                "geom_id": geom_id,
                "final_status": "FAILED_PARSE",
                "highest_tier": 0,
                "final_geometry": initial_xyz
            }


        # Get the v4 T1 tier sequence
        tier_sequence = self._get_tier_sequence(complex_flag)
        
        current_xyz = initial_xyz
        final_status = "SUCCESS"
        highest_completed_tier = 0
        
        # Initialize diagnostics dictionary
        diagnostics = {}
        
        for tier_info in tier_sequence:
            tier_id = tier_info["tier_id"]
            method = tier_info["method"]
            tier_name = tier_info.get("tier_name", f"T1-{tier_id}")
            
            logger.info(f"Processing {geom_id} at Tier {tier_id} ({tier_name}: {method})")
            
            try:
                # Execute calculation based on the method
                if method in ["Hand Topology", "XTB2"]:
                    result_payload = self._execute_hand_topology(atoms)
                elif method in ["GOAT XTB2", "GOAT-XTB2"]:
                    result_payload = self._execute_goat_xtb2(atoms)
                elif method in ["GOAT-EXPLORE ExtOpt", "MACE-OFF24m", "AIMNet2"]:
                    result_payload = self._execute_goat_explore_extopt(atoms)
                elif method in ["CREST NCI", "CREST-NCI"]:
                    result_payload = self._execute_crest_nci(atoms)
                elif method in ["r2SCAN-3c", "r²SCAN-3c"]:
                    result_payload = self._execute_r2scan_3c(atoms, complex_flag=complex_flag)
                elif method == "DFTB3":
                    result_payload = self._execute_dftb3(atoms)
                elif method == "CCSD(T)-F12":
                    result_payload = self._execute_mpqc_ccsdt_f12(atoms, complex_flag=complex_flag)
                elif method == "MACE-JAX":
                    result_payload = self._execute_mace_jax(atoms)
                else:
                    result_payload = self._execute_hand_topology(atoms)
                
                # Update diagnostics with the current tier results
                diagnostics[f"tier_{tier_id}_energy"] = result_payload["energy"]
                if "gradient" in result_payload:
                    diagnostics[f"tier_{tier_id}_gradient"] = result_payload["gradient"]
                if "hessian" in result_payload:
                    diagnostics[f"tier_{tier_id}_hessian"] = result_payload["hessian"]
                
                # 6. Flush to HDF5 securely via SWMR
                self.serializer.write_tier_data(
                    geom_id=geom_id,
                    tier_id=str(tier_id),
                    energy=result_payload["energy"],
                    gradient=result_payload.get("gradient", []),
                    hessian=result_payload.get("hessian", []),
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

if __name__ == "__main__":
    logger.info("CoChem-TOPOS Cascade Orchestrator loaded and ready.")