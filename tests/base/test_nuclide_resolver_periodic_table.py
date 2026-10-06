"""
Unit Verification Across IUPAC Periodic Table (Z=1..118) for CoChem Physical Nuclide Resolver.
Task 1.2.4: Unit Verification Across IUPAC Periodic Table Z=1..118
Target Module: src/cochem_base/physics/nuclide_resolver.py
Council Governance: Council Emergency Session 012 (COCHEM-COUNCIL-RES-012-8D-ZERO-TRUST)

Authoritative real-world physical unit test suite verifying zero-mock periodic table traversal,
AME2020/CIAAW standard terrestrial atomic weights, transuranic/synthetic element fallbacks,
superheavy boundary limits (Oganesson Z=118), fail-closed negative boundary trapping,
and multi-threaded concurrent query resilience.
"""
from __future__ import annotations

import concurrent.futures
import math
import sys
from pathlib import Path

import mendeleev
import pytest

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cochem_base.physics.nuclide_resolver import (
    InvalidNuclideError,
    InvalidNuclideSymbolError,
    IsotopeNotFoundError,
    NuclideResolutionError,
    NuclideToken,
    disambiguate_mass,
    get_element,
    parse_nuclide,
    resolve_covalent_radius,
)


# ============================================================================
# Task 1.2.4.1: IUPAC Periodic Table Traversal (Z=1 to Z=118)
# ============================================================================

def test_iupac_periodic_table_traversal_z_1_to_118() -> None:
    """Iterate through all 118 IUPAC elements (Z=1 to Z=118) and assert positive finite mass and covalent radius."""
    for z in range(1, 119):
        element_obj = mendeleev.element(z)
        symbol = element_obj.symbol

        mass = disambiguate_mass(symbol)
        assert math.isfinite(mass) and mass > 0.0, (
            f"Atomic mass for Z={z} ({symbol}) must be positive and finite, got {mass}."
        )

        r_cov = resolve_covalent_radius(symbol)
        assert r_cov is not None and r_cov > 0.0, (
            f"Covalent radius for Z={z} ({symbol}) must be positive and non-null, got {r_cov}."
        )


# ============================================================================
# Task 1.2.4.2: Standard Terrestrial Atomic Weight Parity
# ============================================================================

def test_standard_terrestrial_atomic_weights_stable_elements() -> None:
    """Assert standard terrestrial atomic weights for H, C, N, O, S, Fe, Au, Pb match CIAAW benchmarks within 0.01 u."""
    ciaaw_targets = [
        ("H", 1.008),
        ("C", 12.011),
        ("N", 14.007),
        ("O", 15.999),
        ("S", 32.06),
        ("Fe", 55.845),
        ("Au", 196.966569),
        ("Pb", 207.2),
    ]
    for symbol, benchmark_mass in ciaaw_targets:
        resolved_mass = disambiguate_mass(symbol)
        assert abs(resolved_mass - benchmark_mass) < 0.01, (
            f"Element {symbol} standard atomic weight {resolved_mass} deviates from CIAAW benchmark {benchmark_mass} by >= 0.01 u."
        )


# ============================================================================
# Task 1.2.4.3: Synthetic & Transuranic Fallbacks
# ============================================================================

def test_synthetic_and_transuranic_fallbacks() -> None:
    """Assert Tc (Z=43), Pm (Z=61), Po (Z=84), At (Z=85), and Og (Z=118) resolve valid finite masses."""
    unstable_elements = ["Tc", "Pm", "Po", "At", "Og"]
    for symbol in unstable_elements:
        mass = disambiguate_mass(symbol)
        assert isinstance(mass, float), (
            f"Element {symbol} mass must be float instance, got {type(mass).__name__}."
        )
        assert math.isfinite(mass) and mass > 0.0, (
            f"Element {symbol} fallback mass must be positive and finite, got {mass}."
        )


# ============================================================================
# Task 1.2.4.4: Superheavy Oganesson Boundary
# ============================================================================

def test_superheavy_oganesson_boundary() -> None:
    """Assert terminal periodic table element Oganesson (Og, Z=118) resolves mass 294.0 +/- 1.0 u and positive radius."""
    og_mass = disambiguate_mass("Og")
    assert abs(og_mass - 294.0) <= 1.0, (
        f"Oganesson mass {og_mass} deviates from expected 294.0 +/- 1.0 u."
    )

    r_cov_og = resolve_covalent_radius("Og")
    assert r_cov_og is not None and r_cov_og > 0.0, (
        f"Oganesson covalent radius must be positive, got {r_cov_og}."
    )


# ============================================================================
# Task 1.2.4.5: Negative Boundary & Typo Exception Trapping Suite
# ============================================================================

def test_negative_boundary_and_typo_exceptions() -> None:
    """Assert fail-closed typed exceptions on malformed symbols and out-of-bounds mass numbers."""
    invalid_nuclide_tokens = ["Xx", "Food", "123", "C12", "", "   "]
    for token in invalid_nuclide_tokens:
        with pytest.raises(InvalidNuclideSymbolError):
            disambiguate_mass(token)
        with pytest.raises(InvalidNuclideSymbolError):
            parse_nuclide(token)

    # Assert IsotopeNotFoundError raised on out-of-bounds mass numbers
    for token in ["50H", "999C"]:
        with pytest.raises(IsotopeNotFoundError):
            disambiguate_mass(token)

    # 0H tests non-physical zero mass number boundary
    with pytest.raises((IsotopeNotFoundError, InvalidNuclideSymbolError)):
        disambiguate_mass("0H")


# ============================================================================
# Task 1.2.4.6: Concurrent Multi-Threaded Query Resilience
# ============================================================================

def test_concurrency_periodic_table_queries() -> None:
    """Run concurrent queries across worker threads using concurrent.futures.ThreadPoolExecutor and assert zero errors."""
    symbols = [mendeleev.element(z).symbol for z in range(1, 119)]
    query_batch = symbols * 8

    def _query_element(symbol: str) -> tuple[float, float | None]:
        mass = disambiguate_mass(symbol)
        radius = resolve_covalent_radius(symbol)
        return mass, radius

    query_errors: list[Exception] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_sym = {executor.submit(_query_element, s): s for s in query_batch}
        for future in concurrent.futures.as_completed(future_to_sym):
            try:
                m, r = future.result()
                assert math.isfinite(m) and m > 0.0
                assert r is not None and r > 0.0
            except Exception as exc:
                query_errors.append(exc)

    assert len(query_errors) == 0, (
        f"Concurrent periodic table queries failed with {len(query_errors)} errors: {query_errors}"
    )
