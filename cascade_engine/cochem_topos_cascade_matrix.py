"""
CoChem-TOPOS: Stage 4.0.1 - Method Matrix Rules Engine
Integrates the CoChem-Cascade Method Matrix logic into the TOPOS workflow.

This module provides the deterministic rules for routing molecular geometries
through the 12-tier escalation matrix, applying automated BSSE (Counterpoise)
corrections, and trapping closed-shell multireference breakdowns.
"""

import logging

# Initialize module-level logger
logger = logging.getLogger("CoChem.TOPOS.CascadeMatrix")

def evaluate_calculation_modifiers(complex_flag: bool, basis_set: str, t1_diagnostic: float = 0.0, d1_diagnostic: float = 0.0) -> dict:
    """
    Handles automated flag routing for BSSE injection, multireference traps,
    and coupled-cluster escalation parameters on the local workstation.
    
    Args:
        complex_flag (bool): True if the structure is an intermolecular complex (Stage 3.5 output).
        basis_set (str): The active basis set string from the Method Matrix tier.
        t1_diagnostic (float): T1 diagnostic from coupled-cluster output (default 0.0 for lower tiers).
        d1_diagnostic (float): D1 diagnostic from coupled-cluster output (default 0.0 for lower tiers).
        
    Returns:
        dict: A dictionary of operational modifiers to dictate downstream ORCA input generation.
    """
    modifiers = {
        "inject_counterpoise": False,
        "escalate_to_multireference": False,
        "status": "Safe"
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

# Define the Method Matrix Execution Tiers mapped to the CoChem-Cascade Blueprint
METHOD_MATRIX_TIERS = {
    "TIER_1_SCREEN": {
        "time_budget": "10 sec",
        "method": "MACE-OFF23",
        "keywords": "mace-torch default",
        "engine": "GPU",
        "description": "Structural pre-screening (+/- 0.1 A)",
        "fallback": "g-xTB"
    },
    "TIER_2_VDW": {
        "time_budget": "1 min",
        "method": "r2SCAN-3c",
        "keywords": "! r2SCAN-3c TightSCF DefGrid3 Opt",
        "engine": "CPU",
        "description": "Initial vdW geometry optimization",
        "fallback": "! B3LYP D4 def2-TZVP def2/J TightSCF DefGrid3 Opt"
    },
    "TIER_3_BULK": {
        "time_budget": "30 min",
        "method": "wB97X-D4",
        "keywords": "! wB97X-D4 def2-TZVP def2/J def2/JK TightSCF DefGrid3 Opt CPCM(Water)",
        "engine": "GPU (gpu4pscf)",
        "description": "Bulk solvent-relaxed local minima",
        "fallback": "Add 1-3 explicit micro-solvation shell molecules"
    },
    "TIER_4_EQ_TARGET": {
        "time_budget": "12 hours",
        "method": "DLPNO-CCSD(T)",
        "keywords": "! DLPNO-CCSD(T) def2-TZVPP def2/J def2/C ExtremeSCF DefGrid3 Opt",
        "engine": "CPU",
        "description": "Wavefunction-level equilibrium targets",
        "fallback": "Apply double-hybrid anharmonic corrections"
    }
}

def get_tier_configuration(tier_id: str) -> dict:
    """
    Retrieves the Method Matrix configuration for a requested tier.
    """
    if tier_id not in METHOD_MATRIX_TIERS:
        raise ValueError(f"Requested tier {tier_id} is not defined in the Method Matrix.")
    return METHOD_MATRIX_TIERS[tier_id]