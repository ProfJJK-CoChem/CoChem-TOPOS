"""
Test Suite for Zero-Static-Dictionary AST Linter & Anti-Mock Sentinel.
WBS 1.2.3: Zero-Static-Dictionary AST Linter & Anti-Mock Sentinel
Target: ci_tools/mendeleev_ast_linter.py

Verifies AST node traversal, chemical element symbol mapping detection,
static mass dictionary detection, dict() keyword argument inspection,
distinguishing geometric radii/valence/symmetry constants/atomic number integers,
atomic weight import assertions, LRU caching, inline suppression, amnesty filtering,
and clean CLI execution against physical production files.
"""
from __future__ import annotations

import functools
import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure repo root and ci_tools directory are on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
CI_TOOLS_DIR = REPO_ROOT / "ci_tools"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(CI_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(CI_TOOLS_DIR))

try:
    from ci_tools.mendeleev_ast_linter import (
        BUILTIN_LEGACY_AMNESTY_PATHS,
        DEFAULT_AMNESTY_FILE,
        LinterViolation,
        MendeleevASTVisitor,
        load_amnesty_file,
        load_periodic_table_symbols,
        main,
        scan_directory,
        scan_file,
    )
except ImportError:
    from mendeleev_ast_linter import (
        BUILTIN_LEGACY_AMNESTY_PATHS,
        DEFAULT_AMNESTY_FILE,
        LinterViolation,
        MendeleevASTVisitor,
        load_amnesty_file,
        load_periodic_table_symbols,
        main,
        scan_directory,
        scan_file,
    )


# ============================================================================
# Periodic Table Symbol Loading & LRU Cache Tests
# ============================================================================

def test_load_periodic_table_symbols() -> None:
    """Verifies that dynamic periodic table symbols load correctly."""
    symbols = load_periodic_table_symbols()
    assert isinstance(symbols, set)
    assert len(symbols) >= 118
    for required in ["H", "C", "N", "O", "Cl", "Fe", "U", "Og"]:
        assert required in symbols


def test_lru_cache_on_load_periodic_table_symbols() -> None:
    """Requirement 5: Provide @functools.lru_cache on periodic table symbol querying."""
    assert hasattr(load_periodic_table_symbols, "cache_info")
    info_before = load_periodic_table_symbols.cache_info()
    syms_1 = load_periodic_table_symbols()
    syms_2 = load_periodic_table_symbols()
    info_after = load_periodic_table_symbols.cache_info()
    assert syms_1 is syms_2
    assert info_after.hits > info_before.hits


# ============================================================================
# AST Violation Detection Tests
# ============================================================================

def test_scan_file_clean_nuclide_resolver() -> None:
    """Verifies that physical production nuclide_resolver.py has 0 static mass violations."""
    target_file = REPO_ROOT / "src" / "cochem_base" / "physics" / "nuclide_resolver.py"
    assert target_file.is_file(), f"Target file does not exist: {target_file}"

    violations = scan_file(target_file)
    assert len(violations) == 0, f"Expected 0 violations, found: {violations}"


def test_detect_static_mass_dictionary_violation(tmp_path: Path) -> None:
    """Verifies detection of static dictionaries mapping chemical symbols to mass floats."""
    bad_code = '''
# Static mass table
ATOMIC_WEIGHTS = {
    "H": 1.008,
    "C": 12.011,
    "N": 14.007,
    "O": 15.999,
}
'''
    bad_file = tmp_path / "bad_mass_table.py"
    bad_file.write_text(bad_code, encoding="utf-8")

    violations = scan_file(bad_file)
    assert len(violations) >= 1
    assert violations[0].category == "STATIC_MASS_DICTIONARY"
    assert "ATOMIC_WEIGHTS" in violations[0].symbol or "dict" in violations[0].symbol
    assert "H" in violations[0].message


def test_detect_dict_constructor_violation(tmp_path: Path) -> None:
    """Verifies detection of dict(...) constructor calls mapping element symbols to mass floats."""
    bad_code = '''
def compute():
    ELEMENT_MASSES = dict(H=1.008, C=12.011, N=14.007)
    return ELEMENT_MASSES
'''
    bad_file = tmp_path / "bad_dict_call.py"
    bad_file.write_text(bad_code, encoding="utf-8")

    violations = scan_file(bad_file)
    assert len(violations) >= 1
    assert violations[0].category == "STATIC_MASS_DICTIONARY"


# ============================================================================
# Constant Disambiguation Tests (Requirement 3)
# ============================================================================

def test_distinguish_covalent_radii(tmp_path: Path) -> None:
    """Requirement 3: Distinguish geometric covalent radius constants."""
    code = '''
COVALENT_RADII_ANG = {
    "H": 0.31,
    "He": 0.28,
    "Li": 1.28,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
}
'''
    f = tmp_path / "covalent_radii.py"
    f.write_text(code, encoding="utf-8")

    violations = scan_file(f)
    assert len(violations) == 0, f"Expected 0 violations for covalent radii, got: {violations}"


def test_distinguish_vdw_radii(tmp_path: Path) -> None:
    """Requirement 3: Distinguish geometric van der Waals radius constants."""
    code = '''
vdw_table = {
    "H": 1.20,
    "He": 1.40,
    "Li": 1.82,
    "C": 1.70,
    "N": 1.55,
    "O": 1.52,
    "F": 1.47,
}
'''
    f = tmp_path / "vdw_radii.py"
    f.write_text(code, encoding="utf-8")

    violations = scan_file(f)
    assert len(violations) == 0, f"Expected 0 violations for vdW radii, got: {violations}"


def test_distinguish_valence_constants(tmp_path: Path) -> None:
    """Requirement 3: Distinguish valence / oxidation state constants."""
    code = '''
standard_max_valences = {
    "H": 1,
    "C": 4,
    "N": 4,
    "O": 2,
    "F": 1,
    "Cl": 1,
}
'''
    f = tmp_path / "valences.py"
    f.write_text(code, encoding="utf-8")

    violations = scan_file(f)
    assert len(violations) == 0, f"Expected 0 violations for valences, got: {violations}"


def test_distinguish_symmetry_point_groups(tmp_path: Path) -> None:
    """Requirement 3: Distinguish symmetry constants and point group orders."""
    code = '''
_POINT_GROUP_SIGMAS = {
    "C1": 1,
    "Cs": 1,
    "Ci": 1,
    "C2": 2,
    "C2v": 2,
    "C3v": 3,
    "D3h": 6,
    "Oh": 24,
}
'''
    f = tmp_path / "symmetry.py"
    f.write_text(code, encoding="utf-8")

    violations = scan_file(f)
    assert len(violations) == 0, f"Expected 0 violations for point group sigmas, got: {violations}"


def test_distinguish_atomic_number_integers(tmp_path: Path) -> None:
    """Requirement 3: Distinguish atomic number integer tables."""
    code = '''
ATOMIC_NUMBERS = {
    "H": 1,
    "He": 2,
    "Li": 3,
    "Be": 4,
    "B": 5,
    "C": 6,
    "N": 7,
    "O": 8,
    "F": 9,
}
'''
    f = tmp_path / "atomic_numbers.py"
    f.write_text(code, encoding="utf-8")

    violations = scan_file(f)
    assert len(violations) == 0, f"Expected 0 violations for atomic number integers, got: {violations}"


# ============================================================================
# Atomic Weight Import Assertion Tests (Requirement 4)
# ============================================================================

def test_assert_atomic_weight_import_missing(tmp_path: Path) -> None:
    """Requirement 4: Flag atomic weight reference missing authoritative import."""
    code = '''
def calculate_mass(elem):
    return elem.atomic_weight
'''
    f = tmp_path / "missing_import.py"
    f.write_text(code, encoding="utf-8")

    violations = scan_file(f)
    assert len(violations) >= 1
    assert any(v.category == "UNRESOLVED_ATOMIC_WEIGHT_IMPORT" for v in violations)


def test_assert_atomic_weight_import_present_mendeleev(tmp_path: Path) -> None:
    """Requirement 4: Pass atomic weight reference with mendeleev import."""
    code = '''
import mendeleev

def calculate_mass(sym):
    el = mendeleev.element(sym)
    return el.atomic_weight
'''
    f = tmp_path / "valid_mendeleev.py"
    f.write_text(code, encoding="utf-8")

    violations = scan_file(f)
    assert len(violations) == 0, f"Expected 0 violations, got: {violations}"


def test_assert_atomic_weight_import_present_nuclide_resolver(tmp_path: Path) -> None:
    """Requirement 4: Pass atomic weight reference with nuclide_resolver import."""
    code = '''
from cochem_base.physics.nuclide_resolver import disambiguate_mass

def get_weight(sym):
    return disambiguate_mass(sym)
'''
    f = tmp_path / "valid_resolver.py"
    f.write_text(code, encoding="utf-8")

    violations = scan_file(f)
    assert len(violations) == 0, f"Expected 0 violations, got: {violations}"


def test_assert_atomic_weight_import_present_alias_mendeleev(tmp_path: Path) -> None:
    """Verifies that imported alias containing 'mendeleev' (e.g. get_mendeleev_element) passes."""
    code = '''
from cochem.mobile.inorganic.models import get_mendeleev_element

def get_weight(symbol: str) -> float:
    elem = get_mendeleev_element(symbol)
    return float(elem.atomic_weight)
'''
    f = tmp_path / "valid_alias_mendeleev.py"
    f.write_text(code, encoding="utf-8")

    violations = scan_file(f)
    assert len(violations) == 0, f"Expected 0 violations for mendeleev alias import, got: {violations}"


def test_assert_atomic_weight_import_present_alias_nuclide_resolver(tmp_path: Path) -> None:
    """Verifies that imported alias containing 'nuclide_resolver' passes."""
    code = '''
from custom_utils import helper as custom_nuclide_resolver

def get_weight(sym: str) -> float:
    return custom_nuclide_resolver.disambiguate_mass(sym)
'''
    f = tmp_path / "valid_alias_resolver.py"
    f.write_text(code, encoding="utf-8")

    violations = scan_file(f)
    assert len(violations) == 0, f"Expected 0 violations for nuclide_resolver alias import, got: {violations}"


def test_assert_atomic_weight_import_present_asname(tmp_path: Path) -> None:
    """Verifies that 'import ... as mendeleev' or 'import ... as nuclide_resolver' passes."""
    code = '''
import chemical_data_provider as mendeleev

def get_weight(sym: str) -> float:
    el = mendeleev.element(sym)
    return el.atomic_weight
'''
    f = tmp_path / "valid_import_as_mendeleev.py"
    f.write_text(code, encoding="utf-8")

    violations = scan_file(f)
    assert len(violations) == 0, f"Expected 0 violations for asname import, got: {violations}"



# ============================================================================
# Benign Dictionary & Suppression Tests
# ============================================================================

def test_benign_dictionary_no_false_positive(tmp_path: Path) -> None:
    """Verifies that general configuration dictionaries do not trigger false positives."""
    good_code = '''
# General configuration
CONFIG = {
    "temperature": 298.15,
    "pressure": 1.0,
    "timeout": 30.0,
}
'''
    good_file = tmp_path / "good_config.py"
    good_file.write_text(good_code, encoding="utf-8")

    violations = scan_file(good_file)
    assert len(violations) == 0


def test_inline_suppression_comment(tmp_path: Path) -> None:
    """Verifies that inline comment suppression disables linter on specific lines."""
    code = '''
# Offline calibration fixture
CALIBRATION_REF = { "H": 1.008, "C": 12.011 }  # mendeleev-linter: disable
'''
    suppressed_file = tmp_path / "suppressed.py"
    suppressed_file.write_text(code, encoding="utf-8")

    violations = scan_file(suppressed_file)
    assert len(violations) == 0


def test_amnesty_file_bypass(tmp_path: Path) -> None:
    """Verifies that files listed in the amnesty JSON file are bypassed."""
    bad_code = '''
ISOTOPE_TABLE = {"H": 1.008, "C": 12.011, "O": 15.999}
'''
    amnestied_file = tmp_path / "legacy_table.py"
    amnestied_file.write_text(bad_code, encoding="utf-8")

    amnesty_json = tmp_path / "test_amnesty.json"
    amnesty_data = [str(amnestied_file)]
    amnesty_json.write_text(json.dumps(amnesty_data), encoding="utf-8")

    amnesty_paths = load_amnesty_file(amnesty_json)
    violations = scan_file(amnestied_file, amnesty_paths=amnesty_paths)
    assert len(violations) == 0


def test_builtin_legacy_amnesty_paths_content() -> None:
    """Verifies BUILTIN_LEGACY_AMNESTY_PATHS contains all required legacy offline tables."""
    expected_paths = {
        "src/cochem_base/calc/cochem_kie_profiler.py",
        "cochem_base/calc/cochem_kie_profiler.py",
        "calc/cochem_kie_profiler.py",
        "src/cochem_base/physics/isotopes.py",
        "cochem_base/physics/isotopes.py",
    }
    assert BUILTIN_LEGACY_AMNESTY_PATHS == expected_paths

    # Verify load_amnesty_file returns all built-in paths even with non-existent file
    loaded = load_amnesty_file("non_existent_file.json")
    for expected in expected_paths:
        assert expected in loaded


def test_builtin_legacy_amnesty_bypasses_files(tmp_path: Path) -> None:
    """Verifies that files matching built-in legacy amnesty paths bypass static mass checks."""
    bad_code = '''
# Legacy offline table
MASS_TABLE = {"H": 1.008, "C": 12.011, "O": 15.999}
'''
    calc_dir = tmp_path / "calc"
    calc_dir.mkdir(parents=True)
    profiler_file = calc_dir / "cochem_kie_profiler.py"
    profiler_file.write_text(bad_code, encoding="utf-8")

    violations = scan_file(profiler_file)
    assert len(violations) == 0, f"Expected profiler to be amnestied, got violations: {violations}"

    physics_dir = tmp_path / "cochem_base" / "physics"
    physics_dir.mkdir(parents=True)
    isotopes_file = physics_dir / "isotopes.py"
    isotopes_file.write_text(bad_code, encoding="utf-8")

    violations = scan_file(isotopes_file)
    assert len(violations) == 0, f"Expected isotopes to be amnestied, got violations: {violations}"


def test_physical_amnestied_files_scan_clean() -> None:
    """Verifies that physical repo files in BUILTIN_LEGACY_AMNESTY_PATHS scan with 0 violations."""
    profiler = REPO_ROOT / "src" / "cochem_base" / "calc" / "cochem_kie_profiler.py"
    if profiler.is_file():
        violations = scan_file(profiler)
        assert len(violations) == 0, f"Expected 0 violations for amnestied profiler, got: {violations}"

    isotopes = REPO_ROOT / "src" / "cochem_base" / "physics" / "isotopes.py"
    if isotopes.is_file():
        violations = scan_file(isotopes)
        assert len(violations) == 0, f"Expected 0 violations for amnestied isotopes, got: {violations}"



# ============================================================================
# CLI Execution Tests
# ============================================================================

def test_cli_main_clean_pass() -> None:
    """Verifies CLI execution against compliant source file returns 0."""
    target_file = str(REPO_ROOT / "src" / "cochem_base" / "physics" / "nuclide_resolver.py")
    ret = main([target_file, "--json"])
    assert ret == 0


def test_detect_subscript_assignment_violation(tmp_path: Path) -> None:
    """Verifies detection of subscript assignments mapping chemical symbols to mass floats."""
    bad_code = '''
MASS_TABLE = {}
MASS_TABLE["H"] = 1.008
MASS_TABLE["C"] = 12.011
'''
    bad_file = tmp_path / "bad_subscript.py"
    bad_file.write_text(bad_code, encoding="utf-8")

    violations = scan_file(bad_file)
    assert len(violations) >= 1
    assert violations[0].category == "STATIC_MASS_DICTIONARY"
    assert "MASS_TABLE" in violations[0].symbol


def test_detect_attribute_assignment_violation(tmp_path: Path) -> None:
    """Verifies detection of object attribute assignments with static mass dictionaries."""
    bad_code = '''
class MassHolder:
    def __init__(self):
        self.ATOMIC_WEIGHTS = {"H": 1.008, "C": 12.011}
'''
    bad_file = tmp_path / "bad_attr_target.py"
    bad_file.write_text(bad_code, encoding="utf-8")

    violations = scan_file(bad_file)
    assert len(violations) >= 1
    assert violations[0].category == "STATIC_MASS_DICTIONARY"


def test_detect_walrus_assignment_violation(tmp_path: Path) -> None:
    """Verifies detection of walrus operator static mass assignments."""
    bad_code = '''
def run():
    if (MASSES := {"H": 1.008, "C": 12.011}):
        return True
'''
    bad_file = tmp_path / "bad_walrus.py"
    bad_file.write_text(bad_code, encoding="utf-8")

    violations = scan_file(bad_file)
    assert len(violations) >= 1
    assert violations[0].category == "STATIC_MASS_DICTIONARY"


def test_detect_dictcomp_violation(tmp_path: Path) -> None:
    """Verifies detection of dictcomp mapping chemical symbols to float constants."""
    bad_code = '''
STATIC_MASS_DICT = {"H": 1.008 for _ in range(1)}
'''
    bad_file = tmp_path / "bad_dictcomp.py"
    bad_file.write_text(bad_code, encoding="utf-8")

    violations = scan_file(bad_file)
    assert len(violations) >= 1
    assert violations[0].category == "STATIC_MASS_DICTIONARY"


def test_cli_main_violation_returns_nonzero(tmp_path: Path) -> None:
    """Verifies CLI execution against bad file returns exit code 1."""
    bad_file = tmp_path / "bad_cli_target.py"
    bad_file.write_text('STATIC_MASSES = {"H": 1.008, "C": 12.011, "O": 15.999}\n', encoding="utf-8")

    ret = main([str(bad_file), "--fail-on-violation", "--json"])
    assert ret == 1

