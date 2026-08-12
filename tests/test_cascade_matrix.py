import logging
logger = logging.getLogger(__name__)
import pytest
from cascade_engine.cochem_topos_cascade_matrix import (
    METHOD_MATRIX_TIERS,
    evaluate_calculation_modifiers,
    get_tier_configuration,
    STANDARD_5_THRESHOLD_GEOM_BLOCK
)

def test_topos03_v4_t1_escalation_matrix() -> None:
    """Verify TOPOS-03: v4 T1 escalation matrix (T1-10s to T1-3d), MACE-OFF24m/AIMNet2, and 5-threshold %geom block."""
    # Check all v4 T1 tiers present
    expected_tiers = ["T1-10s", "T1-1min", "T1-30min", "T1-1h", "T1-3h", "T1-12h", "T1-1d", "T1-3d"]
    for t_id in expected_tiers:
        assert t_id in METHOD_MATRIX_TIERS
        config = get_tier_configuration(t_id)
        assert "time_budget" in config
        assert "method" in config
        assert "keywords" in config

    # Check MACE-OFF24m / AIMNet2 reference in T1-30min
    t1_30min = get_tier_configuration("T1-30min")
    assert "MACE-OFF24m" in t1_30min["method"] or "AIMNet2" in t1_30min["method"]

    # Check standard 5-threshold %geom block in modifiers
    mods = evaluate_calculation_modifiers(complex_flag=True, basis_set="def2-TZVP")
    assert "geom_block" in mods
    geom_str = mods["geom_block"]
    assert "TolGCon" in geom_str
    assert "TolRCon" in geom_str
    assert "TolE" in geom_str
    assert "TolExtStep" in geom_str
    assert "TolExtGrad" in geom_str

def test_legacy_tier_aliases() -> None:
    """Verify legacy aliases remain accessible for backwards compatibility."""
    assert "TIER_1_SCREEN" in METHOD_MATRIX_TIERS
    assert "TIER_2_VDW" in METHOD_MATRIX_TIERS
