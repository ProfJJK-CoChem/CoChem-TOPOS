"""
CoChem-TOPOS: Stage 4.0.1 - v4 T1 Method Matrix Rules Engine
Integrates the v4 CoChem-Cascade Method Matrix logic into the TOPOS workflow.

This module provides the deterministic rules for routing molecular geometries
through the v4 T1 escalation matrix (T1-10s to T1-3d), applying automated BSSE (Counterpoise)
corrections, and trapping closed-shell multireference breakdowns.
"""

import logging
import os

# Initialize module-level logger
logger = logging.getLogger("CoChem.TOPOS.CascadeMatrix")

STANDARD_5_THRESHOLD_GEOM_BLOCK = """%geom
  TolE 1e-7
  TolMaxG 1e-5
  TolRMSG 3e-6
  TolMaxD 1e-4
  TolRMSD 5e-5
  InHess XTB2
end"""

def evaluate_calculation_modifiers(complex_flag: bool, basis_set: str, t1_diagnostic: float = 0.0, d1_diagnostic: float = 0.0) -> dict:
    """
    handles automated flag routing for BSSE injection, multireference traps,
    and coupled-cluster escalation parameters on the local workstation.
    Injects standard 5-threshold %geom block (TolMaxG, TolRMSG, TolMaxD, TolRMSD, TolE).
    
    Args:
        complex_flag (bool): True if the structure is an intermolecular complex (Stage 3.5 output).
        basis_set (str): The active basis set string from the Method Matrix tier.
        t1_diagnostic (float): T1 diagnostic from coupled-cluster output (default 0.0 for lower tiers).
        d1_diagnostic (float): D1 diagnostic from coupled-cluster output (default 0.0 for lower tiers).
        
    Returns:
        dict: A dictionary of operational modifiers to dictate downstream MPQC input generation.
    """
    modifiers = {
        "inject_counterpoise": False,
        "escalate_to_multireference": False,
        "status": "Safe",
        "geom_block": STANDARD_5_THRESHOLD_GEOM_BLOCK
    }
    
    # 1. Automated BSSE Logic
    # Self-correcting composite or vast quadruple-zeta bases do not get CP blocks to avoid over-correction
    self_correcting_basis_sets = ["r2SCAN-3c", "aug-cc-pVQZ", "def2-QZVP", "aug-cc-pVQZ/C"]
    
    if complex_flag and (basis_set not in self_correcting_basis_sets):
        modifiers["inject_counterpoise"] = True
        logger.info(f"BSSE Trap: Counterpoise correction injected for complex using {basis_set}.")
        
    # 2. Multireference Trap Logic (Closed-Shell Thresholds)
    # T1 > 0.02 or D1 > 0.05 indicates the single-reference CCSD(T) assumption is breaking down.
    if t1_diagnostic > 0.02 or d1_diagnostic > 0.05:
        modifiers["escalate_to_multireference"] = True
        modifiers["status"] = "CRITICAL: Multireference Character Detected"
        logger.warning(f"Multireference Trap Triggered: T1={t1_diagnostic}, D1={d1_diagnostic}")
        
    return modifiers

OET_SERVER_ADDRESS = os.environ.get("OET_SERVER_ADDRESS", "localhost:8888")

# Define the v4 T1 Method Matrix Execution Tiers (T1-10s to T1-3d)
METHOD_MATRIX_TIERS = {
    "T1-10s": {
        "time_budget": "10 sec",
        "method": "XTB2",
        "keywords": "! XTB2 TightOpt",
        "engine": "CPU",
        "description": "Hand-enumerated binding topologies pre-screening",
        "fallback": "g-xTB"
    },
    "T1-1min": {
        "time_budget": "1 min",
        "method": "GOAT-XTB2",
        "keywords": "! GOAT XTB2 PAL8",
        "engine": "CPU",
        "description": "Primary GOAT stochastic conformer discovery",
        "fallback": "GFN-FF"
    },
    "T1-30min": {
        "time_budget": "30 min",
        "method": "MACE-OFF24m / AIMNet2",
        "keywords": f"! GOAT-EXPLORE ExtOpt TightOpt PAL8\n%method ProgExt \"oet_client\" Ext_Params \"-b {OET_SERVER_ADDRESS}\" end\n%scf\n  TolE 1e-5\nend",
        "engine": "GPU",
        "description": "MLFF-driven GOAT exploration via oet_server daemon",
        "fallback": "MACE-OFF24m"
    },
    "T1-1h": {
        "time_budget": "1 hour",
        "method": "CREST-NCI",
        "keywords": "crest --nci --gfn2 --ewin 12 --nocross --noreftopo",
        "engine": "CPU",
        "description": "Secondary CREST independent non-covalent cross-check",
        "fallback": "crest --gfn2 --ewin 12"
    },
    "T1-3h": {
        "time_budget": "3 hours",
        "method": "r2SCAN-3c",
        "keywords": f"! r2SCAN-3c TightOpt TightSCF defgrid3\n{STANDARD_5_THRESHOLD_GEOM_BLOCK}",
        "engine": "CPU",
        "description": "Union merge CREGEN screening and r2SCAN-3c re-optimization",
        "fallback": "! B3LYP D4 def2-TZVP def2/J TightSCF defgrid3 Opt"
    },
    "T1-12h": {
        "time_budget": "12 hours",
        "method": "GOAT-r2SCAN-3c",
        "keywords": f"! GOAT r2SCAN-3c defgrid3\n{STANDARD_5_THRESHOLD_GEOM_BLOCK}",
        "engine": "CPU",
        "description": "QM-level GOAT search around assigned minima",
        "fallback": "! r2SCAN-3c TightOpt TightSCF defgrid3"
    },
    "T1-1d": {
        "time_budget": "1 day",
        "method": "GOAT-ENTROPY-XTB2",
        "keywords": "! GOAT-ENTROPY XTB2",
        "engine": "CPU",
        "description": "Conformer entropy convergence diagnostic",
        "fallback": "crest --entropy"
    },
    "T1-3d": {
        "time_budget": "3 days",
        "method": "wB97X-V / def2-TZVPP",
        "keywords": f"! wB97X-V def2-TZVPP defgrid3 TightOpt TightSCF\n{STANDARD_5_THRESHOLD_GEOM_BLOCK}",
        "engine": "CPU",
        "description": "High-level DFT re-optimization of Stage-B survivors",
        "fallback": "! CCSD(T)-F12 cc-pVTZ-F12 defgrid3 Opt"
    }
}

# Legacy aliases for backwards compatibility
METHOD_MATRIX_TIERS["TIER_1_SCREEN"] = METHOD_MATRIX_TIERS["T1-10s"]
METHOD_MATRIX_TIERS["TIER_2_VDW"] = METHOD_MATRIX_TIERS["T1-3h"]
METHOD_MATRIX_TIERS["TIER_3_BULK"] = METHOD_MATRIX_TIERS["T1-3d"]
METHOD_MATRIX_TIERS["TIER_4_EQ_TARGET"] = METHOD_MATRIX_TIERS["T1-3d"]

def get_tier_configuration(tier_id: str) -> dict:
    """
    Retrieves the Method Matrix configuration for a requested tier.
    """
    if tier_id not in METHOD_MATRIX_TIERS:
        raise ValueError(f"Requested tier {tier_id} is not defined in the Method Matrix.")
    return METHOD_MATRIX_TIERS[tier_id]