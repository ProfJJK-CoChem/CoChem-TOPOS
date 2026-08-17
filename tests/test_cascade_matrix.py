"""
CoChem-TOPOS: Unit and Verification Tests for Cascade Method Matrix Rules Engine.
Validates v4 T1 escalation matrix tiers, schema integrity, %geom block thresholds,
BSSE counterpoise logic, multireference traps, and legacy alias equivalence.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from cascade_engine.cochem_topos_cascade_matrix import (
    METHOD_MATRIX_TIERS,
    STANDARD_5_THRESHOLD_GEOM_BLOCK,
    evaluate_calculation_modifiers,
    get_tier_configuration,
)

logger = logging.getLogger(__name__)


def test_topos03_v4_t1_escalation_matrix() -> None:
    """
    Verify TOPOS-03: v4 T1 escalation matrix (T1-10s to T1-3d) tier definitions,
    schema completeness, and exact tier configurations.
    """
    expected_tiers = [
        "T1-10s",
        "T1-1min",
        "T1-30min",
        "T1-1h",
        "T1-3h",
        "T1-12h",
        "T1-1d",
        "T1-3d",
    ]
    required_keys = {
        "time_budget",
        "method",
        "keywords",
        "engine",
        "description",
        "fallback",
    }

    for t_id in expected_tiers:
        assert t_id in METHOD_MATRIX_TIERS, f"Missing expected tier: {t_id}"
        config: dict[str, Any] = get_tier_configuration(t_id)
        assert required_keys.issubset(config.keys()), (
            f"Tier {t_id} missing required schema keys"
        )

        # Verify schema field types and non-empty values
        for key in required_keys:
            assert isinstance(config[key], str), (
                f"Tier {t_id} field '{key}' must be a string"
            )
            assert len(config[key].strip()) > 0, (
                f"Tier {t_id} field '{key}' must not be empty"
            )

        # Verify engine validity
        assert config["engine"] in ("CPU", "GPU"), (
            f"Tier {t_id} engine '{config['engine']}' must be CPU or GPU"
        )

    # Exact check for T1-30min MLFF tier configuration
    t1_30min = get_tier_configuration("T1-30min")
    assert t1_30min["method"] == "MACE-OFF24m / AIMNet2"
    assert t1_30min["engine"] == "GPU"
    assert t1_30min["time_budget"] == "30 min"
    assert t1_30min["fallback"] == "MACE-OFF24m"
    assert "oet_client" in t1_30min["keywords"]
    assert "localhost:8888" in t1_30min["keywords"]
    assert "TolE 1e-5" in t1_30min["keywords"]

    # Verify that QM DFT tiers embed the standard 5-threshold %geom block
    for qm_tier in ["T1-3h", "T1-12h", "T1-3d"]:
        cfg = get_tier_configuration(qm_tier)
        assert STANDARD_5_THRESHOLD_GEOM_BLOCK in cfg["keywords"], (
            f"QM tier {qm_tier} must embed STANDARD_5_THRESHOLD_GEOM_BLOCK in keywords"
        )


def test_standard_5_threshold_geom_block_parameters() -> None:
    """
    Verify exact parameter definitions in STANDARD_5_THRESHOLD_GEOM_BLOCK and
    calculation modifier output.
    """
    expected_parameters = [
        "TolMaxG 1e-5",
        "TolGCon 3e-6",
        "TolRCon 5e-5",
        "TolE 1e-7",
        "TolExtStep 1e-4",
        "TolExtGrad 1e-5",
        "InHess XTB2",
    ]
    for param in expected_parameters:
        assert param in STANDARD_5_THRESHOLD_GEOM_BLOCK, (
            f"Missing parameter '{param}' in STANDARD_5_THRESHOLD_GEOM_BLOCK"
        )

    assert STANDARD_5_THRESHOLD_GEOM_BLOCK.startswith("%geom")
    assert STANDARD_5_THRESHOLD_GEOM_BLOCK.endswith("end")

    # Verify calculation modifiers inject the exact STANDARD_5_THRESHOLD_GEOM_BLOCK
    mods = evaluate_calculation_modifiers(
        complex_flag=True, basis_set="def2-TZVP"
    )
    assert "geom_block" in mods
    assert mods["geom_block"] == STANDARD_5_THRESHOLD_GEOM_BLOCK


@pytest.mark.parametrize(
    "complex_flag,basis_set,expected_cp",
    [
        (True, "def2-TZVP", True),
        (True, "def2-SVP", True),
        (True, "cc-pVTZ", True),
        (True, "r2SCAN-3c", False),
        (True, "aug-cc-pVQZ", False),
        (True, "def2-QZVP", False),
        (True, "aug-cc-pVQZ/C", False),
        (False, "def2-TZVP", False),
        (False, "r2SCAN-3c", False),
        (False, "aug-cc-pVQZ", False),
    ],
)
def test_evaluate_calculation_modifiers_bsse(
    complex_flag: bool, basis_set: str, expected_cp: bool
) -> None:
    """
    Verify BSSE Counterpoise injection logic for complexes and self-correcting
    basis set bypass.
    """
    mods = evaluate_calculation_modifiers(
        complex_flag=complex_flag, basis_set=basis_set
    )
    assert mods["inject_counterpoise"] is expected_cp


@pytest.mark.parametrize(
    "t1,d1,expected_escalate,expected_status",
    [
        (0.0, 0.0, False, "Safe"),
        (0.02, 0.05, False, "Safe"),
        (0.015, 0.04, False, "Safe"),
        (0.021, 0.0, True, "CRITICAL: Multireference Character Detected"),
        (0.0, 0.051, True, "CRITICAL: Multireference Character Detected"),
        (0.03, 0.08, True, "CRITICAL: Multireference Character Detected"),
    ],
)
def test_evaluate_calculation_modifiers_multireference_trap(
    t1: float, d1: float, expected_escalate: bool, expected_status: str
) -> None:
    """
    Verify multireference breakdown trap logic at boundaries and critical
    thresholds.
    """
    mods = evaluate_calculation_modifiers(
        complex_flag=False,
        basis_set="def2-TZVP",
        t1_diagnostic=t1,
        d1_diagnostic=d1,
    )
    assert mods["escalate_to_multireference"] is expected_escalate
    assert mods["status"] == expected_status


@pytest.mark.parametrize(
    "alias_name,canonical_target",
    [
        ("TIER_1_SCREEN", "T1-10s"),
        ("TIER_2_VDW", "T1-3h"),
        ("TIER_3_BULK", "T1-3d"),
        ("TIER_4_EQ_TARGET", "T1-3d"),
    ],
)
def test_legacy_tier_aliases(alias_name: str, canonical_target: str) -> None:
    """
    Verify all 4 legacy tier aliases exist and are exactly equivalent to their
    canonical targets.
    """
    assert alias_name in METHOD_MATRIX_TIERS, (
        f"Alias {alias_name} missing from METHOD_MATRIX_TIERS"
    )
    assert canonical_target in METHOD_MATRIX_TIERS, (
        f"Target {canonical_target} missing from METHOD_MATRIX_TIERS"
    )

    # Assert exact dictionary equivalence in METHOD_MATRIX_TIERS
    # and get_tier_configuration
    assert (
        METHOD_MATRIX_TIERS[alias_name]
        == METHOD_MATRIX_TIERS[canonical_target]
    )
    assert (
        get_tier_configuration(alias_name)
        == get_tier_configuration(canonical_target)
    )


@pytest.mark.parametrize(
    "invalid_tier",
    [
        "INVALID_TIER",
        "",
        "T1-99d",
        "UNKNOWN_TIER",
    ],
)
def test_get_tier_configuration_invalid_tier(invalid_tier: str) -> None:
    """
    Verify get_tier_configuration raises ValueError when requested tier is
    undefined.
    """
    with pytest.raises(
        ValueError,
        match=f"Requested tier {invalid_tier} is not defined in the Method Matrix.",
    ):
        get_tier_configuration(invalid_tier)
