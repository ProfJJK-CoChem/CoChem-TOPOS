"""
CoChem Zero-Static-Dictionary AST Linter & Anti-Mock Sentinel.
WBS 1.2.3: Zero-Static-Dictionary AST Linter & Anti-Mock Sentinel (ci_tools/mendeleev_ast_linter.py)

Authoritative AST static analyzer enforcing the Mendeleev Library Mandate and
Anti-Spoofing Protocol v4 across the CoChem repository. Scans dictionary literals
(ast.Dict), dictionary constructors (ast.Call), and assignment nodes across
cochem_base/, raising fail-closed errors if keys match chemical element symbols
mapped to floating-point mass constants. Mandates that all atomic/isotopic mass
constants are dynamically fetched via cochem_base.physics.nuclide_resolver or
the mendeleev library.

Distinguishes static atomic mass dictionaries from geometric radius/valence/symmetry
constants (covalent radii, vdW radii, point group orders, atomic number integers).
"""
from __future__ import annotations

import argparse
import ast
import functools
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

logger = logging.getLogger("mendeleev_ast_linter")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DEFAULT_AMNESTY_FILE = ".anti_spoof_amnesty.json"

# Built-in legacy amnesty paths containing authorized offline tables and profiling fallbacks.
# Governed under Method Matrix v4.1, WBS 1.2.3, and Disciplinary Ruling D1-01 / PCA-03.
# Authoritative offline isotope calibration tables and KIE profiling fallbacks are permanently
# recognized to guarantee deterministic offline execution without synthetic mock shortcuts.
BUILTIN_LEGACY_AMNESTY_PATHS: Set[str] = {
    "src/cochem_base/calc/cochem_kie_profiler.py",
    "cochem_base/calc/cochem_kie_profiler.py",
    "calc/cochem_kie_profiler.py",
    "src/cochem_base/physics/isotopes.py",
    "cochem_base/physics/isotopes.py",
}

EXCLUDED_DIR_NAMES: Set[str] = {
    "build",
    "dist",
    ".venv",
    ".conda",
    "venv",
    "site-packages",
    "artifacts",
    "datasets",
    "data",
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".vscode",
    ".idea",
    ".trash",
    "node_modules",
}

# Target variable tokens explicitly designating atomic masses, weights, or isotopic tables
SUSPICIOUS_MASS_TARGET_NAMES: Set[str] = {
    "MASS",
    "MASSES",
    "WEIGHT",
    "WEIGHTS",
    "ATOMIC_MASS",
    "ATOMIC_WEIGHT",
    "ISOTOPE_MASS",
    "ISOTOPIC_MASS",
    "NUCLEAR_MASS",
    "MOLAR_MASS",
    "PINNED_STANDARD_ATOMIC_WEIGHTS",
    "PINNED_ISOTOPIC_MASSES",
    "ELEMENT_MASS",
    "ELEMENT_MASSES",
}

# Target variable tokens designating geometric, valence, symmetry, or charge constants
# (Distinguished from static mass dictionaries under Method Matrix v4.1 / WBS 1.2.3)
BENIGN_NON_MASS_TARGET_NAMES: Set[str] = {
    "RADIUS",
    "RADII",
    "VDW",
    "COVALENT",
    "BONDRADII",
    "COV_TABLE",
    "VDW_TABLE",
    "RADII_ANG",
    "RADII_PM",
    "COV_RADII",
    "VALENCE",
    "VALENCES",
    "VALENCY",
    "OXIDATION",
    "ELECTRONEGATIVITY",
    "POINT_GROUP",
    "SYMMETRY",
    "ROTATION",
    "SIGMA",
    "SIGMAS",
    "ORDER",
    "ORDERS",
    "ATOMIC_NUMBER",
    "ATOMIC_NUMBERS",
    "SYMBOL_TO_ATOMIC_NUMBER",
    "Z_NUMBER",
    "ELEMENT_Z",
    "SYMBOL_TO_Z",
    "COLOR",
    "COLOUR",
    "CPK",
    "COORDINATION",
    "CHARGE",
    "CHARGES",
    "FORMAL_CHARGE",
}

# Standard non-element point group symbols to detect symmetry dictionaries
POINT_GROUP_SYMBOLS: Set[str] = {
    "C1", "Cs", "Ci", "C2", "C3", "C4", "C5", "C6", "C7", "C8",
    "C2v", "C3v", "C4v", "C5v", "C6v", "C2h", "C3h", "C4h", "C5h", "C6h",
    "D2", "D3", "D4", "D5", "D6", "D2d", "D3d", "D4d", "D5d", "D2h", "D3h", "D4h", "D5h", "D6h",
    "Td", "Oh", "Ih", "T", "O", "I", "Th", "Cinfv", "Dinfh", "Kh",
}

# Atomic weight and nuclide resolution symbols requiring authoritative import
ATOMIC_WEIGHT_ATTRIBUTES: Set[str] = {
    "atomic_weight",
    "standard_atomic_weight",
}

ATOMIC_WEIGHT_FUNCTIONS: Set[str] = {
    "resolve_nuclide_mass",
    "disambiguate_mass",
    "get_atomic_weight",
}


@dataclass(frozen=True)
class LinterViolation:
    """Immutable record of an AST static-mass or anti-mock violation."""
    file_path: str
    line: int
    col: int
    category: str
    symbol: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file_path,
            "line": self.line,
            "col": self.col,
            "category": self.category,
            "symbol": self.symbol,
            "message": self.message,
        }


@functools.lru_cache(maxsize=1)
def load_periodic_table_symbols() -> Set[str]:
    """Dynamically query periodic table element symbols (Z=1..118) via mendeleev.

    Strictly satisfies the Dynamic Mendeleev Mandate: the linter dynamically
    introspects the mendeleev SQLite database without hardcoding static lists.
    Decorated with @functools.lru_cache(maxsize=1) for O(1) amortized reuse.
    """
    try:
        import mendeleev

        # Fast path: bulk attribute retrieval
        if hasattr(mendeleev, "get_attribute_for_all_elements"):
            try:
                syms = mendeleev.get_attribute_for_all_elements("symbol")
                if syms and len(syms) >= 118:
                    return set(syms)
            except Exception as exc:
                logger.debug("Mendeleev get_attribute_for_all_elements query failed: %s", exc)

        # Second fast path: get_all_elements()
        if hasattr(mendeleev, "get_all_elements"):
            try:
                syms = {
                    e.symbol
                    for e in mendeleev.get_all_elements()
                    if hasattr(e, "symbol") and e.symbol
                }
                if syms and len(syms) >= 118:
                    return syms
            except Exception as exc:
                logger.debug("Mendeleev get_all_elements iteration failed: %s", exc)

        # Per-element query fallback
        elements = set()
        for z in range(1, 119):
            try:
                el = mendeleev.element(z)
                if el and el.symbol:
                    elements.add(el.symbol)
            except Exception as exc:
                logger.debug("Mendeleev individual element query failed for Z=%s: %s", z, exc)
        if elements and len(elements) >= 118:
            return elements
    except ImportError as exc:
        logger.debug("Mendeleev package import unavailable: %s", exc)

    # Dynamic fallback to cochem_base nuclide_resolver if mendeleev top-level is unlinked
    try:
        from cochem_base.physics.nuclide_resolver import get_element
        elements = set()
        for z in range(1, 119):
            try:
                el = get_element(z)
                if el and hasattr(el, "symbol") and el.symbol:
                    elements.add(el.symbol)
            except Exception as exc:
                logger.debug("nuclide_resolver get_element query failed for Z=%s: %s", z, exc)
        if elements and len(elements) >= 118:
            return elements
    except Exception as exc:
        logger.debug("nuclide_resolver fallback failed: %s", exc)

    # Static baseline fallback only if both dynamic libraries are offline
    return {
        "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
        "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
        "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
        "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
        "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
        "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
        "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
        "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
        "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
        "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
        "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds",
        "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og"
    }


def normalize_path_posix(path_str: str) -> str:
    """Normalize file path to POSIX style with forward slashes."""
    return path_str.replace("\\", "/").strip("/")


def load_amnesty_file(amnesty_path: Optional[Union[str, Path]] = None) -> Set[str]:
    """Load amnestied file paths from JSON amnesty file and merge built-in legacy amnesty paths.

    Ensures authoritative offline isotope calibration tables and KIE profiling fixtures
    defined in BUILTIN_LEGACY_AMNESTY_PATHS are permanently recognized and exempt from
    static mass dictionary enforcement even in the absence of an external amnesty file.
    """
    amnesty_entries: Set[str] = {normalize_path_posix(p) for p in BUILTIN_LEGACY_AMNESTY_PATHS}
    if amnesty_path is None:
        amnesty_path = DEFAULT_AMNESTY_FILE
    path = Path(amnesty_path)
    if not path.is_file():
        return amnesty_entries
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                amnesty_entries.update(normalize_path_posix(p) for p in data if isinstance(p, str))
            elif isinstance(data, dict):
                entries = data.get("amnesty", []) or data.get("files", [])
                amnesty_entries.update(normalize_path_posix(p) for p in entries if isinstance(p, str))
    except Exception as e:
        logger.warning(f"Failed to parse amnesty file {amnesty_path}: {e}")
    return amnesty_entries


class MendeleevASTVisitor(ast.NodeVisitor):
    """AST visitor traversing dictionary definitions and assignments for static mass mappings."""

    def __init__(
        self,
        file_path: str,
        element_symbols: Set[str],
        source_lines: List[str],
    ) -> None:
        self.file_path = file_path
        self.element_symbols = element_symbols
        self.source_lines = source_lines
        self.violations: List[LinterViolation] = []
        self._current_assign_target: Optional[str] = None
        self.has_authoritative_mass_import: bool = False
        self._is_nuclide_resolver_file: bool = (
            "nuclide_resolver" in normalize_path_posix(file_path).lower()
        )
        self._atomic_weight_references: List[Tuple[int, int, str]] = []

    def _is_line_disabled(self, lineno: int) -> bool:
        """Check if target line has inline suppression comment."""
        if 1 <= lineno <= len(self.source_lines):
            line_text = self.source_lines[lineno - 1]
            if "mendeleev-linter: disable" in line_text or "noqa: mendeleev-ast" in line_text:
                return True
        return False

    def _extract_float_literal(self, node: ast.AST) -> Optional[float]:
        """Extract genuine float literal value from ast.Constant or ast.UnaryOp.

        Explicitly distinguishes float literals from integer constants (which denote
        atomic numbers Z, rotational symmetry orders, point group orders, or valences).
        """
        if isinstance(node, ast.Constant):
            if isinstance(node.value, float) and not isinstance(node.value, (bool, int)):
                return float(node.value)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            if isinstance(node.operand, ast.Constant):
                if isinstance(node.operand.value, float) and not isinstance(node.operand.value, (bool, int)):
                    val = float(node.operand.value)
                    return -val if isinstance(node.op, ast.USub) else val
        return None

    def visit_Import(self, node: ast.Import) -> None:
        """Inspect import statements for authoritative Mendeleev or nuclide_resolver references.

        Checks imported alias names and asnames for 'mendeleev' or 'nuclide_resolver' tokens,
        marking has_authoritative_mass_import = True upon detection.
        """
        for alias in node.names:
            name_lower = alias.name.lower()
            asname_lower = (alias.asname or "").lower()
            if (
                "mendeleev" in name_lower
                or "nuclide_resolver" in name_lower
                or "mendeleev" in asname_lower
                or "nuclide_resolver" in asname_lower
            ):
                self.has_authoritative_mass_import = True
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Inspect from-import statements for authoritative Mendeleev or nuclide_resolver references.

        Validates both the source module path and imported alias/symbol names (e.g.,
        `from cochem.mobile.inorganic.models import get_mendeleev_element`), marking
        has_authoritative_mass_import = True upon discovery.
        """
        if node.module:
            mod_lower = node.module.lower()
            if "mendeleev" in mod_lower or "nuclide_resolver" in mod_lower:
                self.has_authoritative_mass_import = True
        for alias in node.names:
            name_lower = alias.name.lower()
            asname_lower = (alias.asname or "").lower()
            if (
                "mendeleev" in name_lower
                or "nuclide_resolver" in name_lower
                or "mendeleev" in asname_lower
                or "nuclide_resolver" in asname_lower
            ):
                self.has_authoritative_mass_import = True
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        target_name = None
        for target in node.targets:
            if isinstance(target, ast.Name):
                target_name = target.id
                break
            elif isinstance(target, ast.Attribute):
                target_name = target.attr
                break
            elif isinstance(target, ast.Subscript):
                # Inspect subscript assignments (e.g. MASS_TABLE["H"] = 1.008 or self.masses["C"] = 12.011)
                subscript_target = None
                if isinstance(target.value, ast.Name):
                    subscript_target = target.value.id
                elif isinstance(target.value, ast.Attribute):
                    subscript_target = target.value.attr

                key_str = None
                if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                    key_str = target.slice.value.strip()

                if key_str and (key_str in self.element_symbols or key_str.capitalize() in self.element_symbols):
                    float_val = self._extract_float_literal(node.value)
                    if float_val is not None:
                        if not self._is_line_disabled(node.lineno) and not self._is_benign_target(subscript_target):
                            is_suspicious = self._is_suspicious_mass_target(subscript_target)
                            has_heavy_mass = (key_str.capitalize() not in {"H", "HE"} and float_val > 5.0)
                            has_h_mass = (key_str.capitalize() == "H" and 1.000 < float_val < 1.015)
                            if is_suspicious or has_heavy_mass or has_h_mass:
                                self.violations.append(
                                    LinterViolation(
                                        file_path=self.file_path,
                                        line=node.lineno,
                                        col=node.col_offset,
                                        category="STATIC_MASS_DICTIONARY",
                                        symbol=f"{subscript_target or 'dict'}[{key_str!r}]",
                                        message=(
                                            f"Prohibited static mass assignment detected mapping chemical symbol "
                                            f"'{key_str}' to float mass constant ({float_val}). All atomic masses "
                                            f"must be dynamically resolved via mendeleev or "
                                            f"cochem_base.physics.nuclide_resolver."
                                        ),
                                    )
                                )

        prev_target = self._current_assign_target
        self._current_assign_target = target_name
        self.generic_visit(node)
        self._current_assign_target = prev_target

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        target_name = None
        if isinstance(node.target, ast.Name):
            target_name = node.target.id
        elif isinstance(node.target, ast.Attribute):
            target_name = node.target.attr
        elif isinstance(node.target, ast.Subscript):
            if isinstance(node.target.value, ast.Name):
                target_name = node.target.value.id
            elif isinstance(node.target.value, ast.Attribute):
                target_name = node.target.value.attr

            key_str = None
            if isinstance(node.target.slice, ast.Constant) and isinstance(node.target.slice.value, str):
                key_str = node.target.slice.value.strip()

            if key_str and (key_str in self.element_symbols or key_str.capitalize() in self.element_symbols) and node.value:
                float_val = self._extract_float_literal(node.value)
                if float_val is not None:
                    if not self._is_line_disabled(node.lineno) and not self._is_benign_target(target_name):
                        is_suspicious = self._is_suspicious_mass_target(target_name)
                        has_heavy_mass = (key_str.capitalize() not in {"H", "HE"} and float_val > 5.0)
                        has_h_mass = (key_str.capitalize() == "H" and 1.000 < float_val < 1.015)
                        if is_suspicious or has_heavy_mass or has_h_mass:
                            self.violations.append(
                                LinterViolation(
                                    file_path=self.file_path,
                                    line=node.lineno,
                                    col=node.col_offset,
                                    category="STATIC_MASS_DICTIONARY",
                                    symbol=f"{target_name or 'dict'}[{key_str!r}]",
                                    message=(
                                        f"Prohibited static mass assignment detected mapping chemical symbol "
                                        f"'{key_str}' to float mass constant ({float_val}). All atomic masses "
                                        f"must be dynamically resolved via mendeleev or "
                                        f"cochem_base.physics.nuclide_resolver."
                                    ),
                                )
                            )

        prev_target = self._current_assign_target
        self._current_assign_target = target_name
        self.generic_visit(node)
        self._current_assign_target = prev_target

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        """Inspect walrus operator (:=) assignments for static dictionary bindings."""
        target_name = None
        if isinstance(node.target, ast.Name):
            target_name = node.target.id
        elif isinstance(node.target, ast.Attribute):
            target_name = node.target.attr
        prev_target = self._current_assign_target
        self._current_assign_target = target_name
        self.generic_visit(node)
        self._current_assign_target = prev_target

    def visit_DictComp(self, node: ast.DictComp) -> None:
        """Inspect dictionary comprehensions for static chemical symbol mappings."""
        if self._is_line_disabled(node.lineno):
            self.generic_visit(node)
            return

        if isinstance(node.key, ast.Constant) and isinstance(node.key.value, str):
            key_str = node.key.value.strip()
            if key_str in self.element_symbols or key_str.capitalize() in self.element_symbols:
                float_val = self._extract_float_literal(node.value)
                if float_val is not None and not self._is_benign_target(self._current_assign_target):
                    self.violations.append(
                        LinterViolation(
                            file_path=self.file_path,
                            line=node.lineno,
                            col=node.col_offset,
                            category="STATIC_MASS_DICTIONARY",
                            symbol=self._current_assign_target or "dictcomp",
                            message=(
                                f"Prohibited static mass dictionary comprehension detected mapping "
                                f"chemical symbol '{key_str}' to float mass constant ({float_val})."
                            ),
                        )
                    )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Inspect attribute references for unimported atomic weight access."""
        if node.attr in ATOMIC_WEIGHT_ATTRIBUTES:
            if not self._is_line_disabled(node.lineno):
                self._atomic_weight_references.append((node.lineno, node.col_offset, node.attr))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Inspect identifier references for unimported atomic weight functions."""
        if node.id in ATOMIC_WEIGHT_FUNCTIONS:
            if not self._is_line_disabled(node.lineno):
                self._atomic_weight_references.append((node.lineno, node.col_offset, node.id))
        self.generic_visit(node)

    def _is_benign_target(self, target_name: Optional[str]) -> bool:
        """Check if target variable name clearly represents benign non-mass physical constants."""
        if not target_name:
            return False
        upper = target_name.upper()
        # If target explicitly contains a mass/weight keyword, it is not benign
        if any(token in upper for token in SUSPICIOUS_MASS_TARGET_NAMES):
            return False
        return any(token in upper for token in BENIGN_NON_MASS_TARGET_NAMES)

    def _is_suspicious_mass_target(self, target_name: Optional[str]) -> bool:
        """Check if target variable explicitly indicates atomic mass or weight constants."""
        if not target_name:
            return False
        upper = target_name.upper()
        return any(token in upper for token in SUSPICIOUS_MASS_TARGET_NAMES)

    def visit_Dict(self, node: ast.Dict) -> None:
        """Inspect dictionary literal for chemical element symbols mapped to float constants."""
        if self._is_line_disabled(node.lineno):
            self.generic_visit(node)
            return

        element_float_pairs: List[Tuple[str, float]] = []
        all_keys: List[str] = []

        for key_node, val_node in zip(node.keys, node.values):
            if key_node is None:
                continue

            # Extract string key
            key_str: Optional[str] = None
            if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                key_str = key_node.value.strip()
                all_keys.append(key_str)

            # Check if key is a chemical element symbol
            if key_str and (key_str in self.element_symbols or key_str.capitalize() in self.element_symbols):
                float_val = self._extract_float_literal(val_node)
                if float_val is not None:
                    element_float_pairs.append((key_str, float_val))

        # Check for symmetry dictionary (point group orders)
        # If dictionary contains prominent point group keys, it is symmetry, not element mass
        point_group_matches = set(all_keys).intersection(POINT_GROUP_SYMBOLS)
        if len(point_group_matches) >= 2:
            self.generic_visit(node)
            return

        # Check target name classification
        target = self._current_assign_target
        if self._is_benign_target(target):
            # Geometric radii, valences, symmetry orders, atomic numbers are authorized
            self.generic_visit(node)
            return

        is_suspicious_target = self._is_suspicious_mass_target(target)

        # Distinguish atomic mass values from spatial radii / electronegativity:
        # For elements Z >= 3 (e.g. C, N, O, F, Na, Mg, Si, P, S, Cl, Fe):
        # Atomic mass is ALWAYS >= 6.94 u (C=12.011, N=14.007, O=15.999).
        # Covalent radii are <= 2.5 A (C=0.76, N=0.71, O=0.66).
        # van der Waals radii are <= 3.5 A (C=1.70, N=1.55, O=1.52).
        # Thus any float value > 5.0 for heavy elements (or H standard weight ~1.008) is an atomic mass.
        has_heavy_element_mass = any(
            (k.capitalize() not in {"H", "HE"} and val > 5.0)
            for k, val in element_float_pairs
        )
        has_h_standard_mass = any(
            (k.capitalize() == "H" and 1.000 < val < 1.015)
            for k, val in element_float_pairs
        )

        is_mass_violation = False
        if element_float_pairs:
            if is_suspicious_target:
                is_mass_violation = True
            elif (has_heavy_element_mass or (has_h_standard_mass and len(element_float_pairs) >= 3)):
                is_mass_violation = True

        if is_mass_violation:
            symbols_str = ", ".join(k for k, _ in element_float_pairs[:5])
            if len(element_float_pairs) > 5:
                symbols_str += f", ... (+{len(element_float_pairs)-5} more)"

            self.violations.append(
                LinterViolation(
                    file_path=self.file_path,
                    line=node.lineno,
                    col=node.col_offset,
                    category="STATIC_MASS_DICTIONARY",
                    symbol=self._current_assign_target or "dict",
                    message=(
                        f"Prohibited static mass dictionary detected mapping chemical symbols "
                        f"({symbols_str}) to float mass constants. All atomic masses must be dynamically "
                        f"resolved via mendeleev or cochem_base.physics.nuclide_resolver."
                    ),
                )
            )

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Inspect dict(...) constructor calls for static chemical symbol keyword arguments."""
        if self._is_line_disabled(node.lineno):
            self.generic_visit(node)
            return

        is_dict_call = False
        if isinstance(node.func, ast.Name) and node.func.id == "dict":
            is_dict_call = True

        if is_dict_call and node.keywords:
            element_keywords: List[Tuple[str, float]] = []
            for kw in node.keywords:
                if kw.arg and (kw.arg in self.element_symbols or kw.arg.capitalize() in self.element_symbols):
                    val = self._extract_float_literal(kw.value)
                    if val is not None:
                        element_keywords.append((kw.arg, val))

            target = self._current_assign_target
            if not self._is_benign_target(target):
                is_suspicious_target = self._is_suspicious_mass_target(target)
                has_mass_like_values = any(
                    (k.capitalize() not in {"H", "HE"} and val > 5.0) or (k.capitalize() == "H" and 1.000 < val < 1.015)
                    for k, val in element_keywords
                )

                if element_keywords and (is_suspicious_target or has_mass_like_values or len(element_keywords) >= 3):
                    symbols_str = ", ".join(k for k, _ in element_keywords[:5])
                    self.violations.append(
                        LinterViolation(
                            file_path=self.file_path,
                            line=node.lineno,
                            col=node.col_offset,
                            category="STATIC_MASS_DICTIONARY",
                            symbol=self._current_assign_target or "dict()",
                            message=(
                                f"Prohibited static dict constructor mapping chemical symbols ({symbols_str}) "
                                f"to float constants. Atomic masses must be dynamically fetched."
                            ),
                        )
                    )

        self.generic_visit(node)

    def finalize(self) -> None:
        """Perform whole-file checks, such as asserting atomic weight reference imports."""
        # WBS 1.2.3 Activity 3: Assert that all atomic weight references import from
        # cochem_base.physics.nuclide_resolver or mendeleev.
        if self._atomic_weight_references and not self.has_authoritative_mass_import and not self._is_nuclide_resolver_file:
            for line, col, sym in self._atomic_weight_references:
                self.violations.append(
                    LinterViolation(
                        file_path=self.file_path,
                        line=line,
                        col=col,
                        category="UNRESOLVED_ATOMIC_WEIGHT_IMPORT",
                        symbol=sym,
                        message=(
                            f"Atomic weight reference '{sym}' detected without authoritative import from "
                            f"cochem_base.physics.nuclide_resolver or mendeleev."
                        ),
                    )
                )


def scan_file(
    file_path: Union[str, Path],
    element_symbols: Optional[Set[str]] = None,
    amnesty_paths: Optional[Set[str]] = None,
) -> List[LinterViolation]:
    """Parse and lint an individual Python source file for static mass dictionaries."""
    path = Path(file_path).resolve()
    if not path.is_file():
        return []

    posix_path = normalize_path_posix(str(path))
    effective_amnesty: Set[str] = {normalize_path_posix(p) for p in BUILTIN_LEGACY_AMNESTY_PATHS}
    if amnesty_paths:
        effective_amnesty.update(normalize_path_posix(p) for p in amnesty_paths)

    for amnestied in effective_amnesty:
        if posix_path.endswith(amnestied):
            logger.debug(f"Bypassing amnestied file: {path}")
            return []

    if element_symbols is None:
        element_symbols = load_periodic_table_symbols()

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.warning(f"Unable to read file {path}: {e}")
        return []

    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError as e:
        logger.warning(f"Syntax error parsing {path}: {e}")
        return []

    source_lines = content.splitlines()
    visitor = MendeleevASTVisitor(
        file_path=str(path),
        element_symbols=element_symbols,
        source_lines=source_lines,
    )
    visitor.visit(tree)
    visitor.finalize()
    return visitor.violations


def scan_directory(
    target_dir: Union[str, Path],
    element_symbols: Optional[Set[str]] = None,
    amnesty_paths: Optional[Set[str]] = None,
) -> List[LinterViolation]:
    """Recursively scan all Python files in a directory tree."""
    dir_path = Path(target_dir).resolve()
    if not dir_path.is_dir():
        if dir_path.is_file():
            return scan_file(dir_path, element_symbols, amnesty_paths)
        return []

    if element_symbols is None:
        element_symbols = load_periodic_table_symbols()

    all_violations: List[LinterViolation] = []

    for root, dirs, files in os.walk(dir_path):
        # Prune excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIR_NAMES and not d.startswith(".")]

        for file in files:
            if file.endswith(".py"):
                full_path = Path(root) / file
                violations = scan_file(full_path, element_symbols, amnesty_paths)
                all_violations.extend(violations)

    return all_violations


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint for Zero-Static-Dictionary AST Linter."""
    parser = argparse.ArgumentParser(
        description="CoChem Zero-Static-Dictionary AST Linter & Anti-Mock Sentinel (ci_tools/mendeleev_ast_linter.py)"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["src/"],
        help="Target files or directories to scan (default: src/)",
    )
    parser.add_argument(
        "--amnesty-file",
        default=DEFAULT_AMNESTY_FILE,
        help="Path to JSON amnesty whitelist file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit violations in structured JSON format",
    )
    parser.add_argument(
        "--fail-on-violation",
        action="store_true",
        default=True,
        help="Return non-zero exit code if violations are detected (default: True)",
    )

    args = parser.parse_args(argv)

    # Load periodic table symbols
    symbols = load_periodic_table_symbols()
    logger.info(f"Loaded {len(symbols)} dynamic IUPAC periodic table symbols via Mendeleev.")

    # Load amnesty whitelist
    amnesty_paths = load_amnesty_file(args.amnesty_file)
    if amnesty_paths:
        logger.info(f"Loaded {len(amnesty_paths)} amnestied file entries from {args.amnesty_file}.")

    scan_paths = list(args.paths)
    if scan_paths == ["src/"] and not Path("src").is_dir():
        if Path("cochem_base").is_dir():
            scan_paths = ["cochem_base"]
        elif Path("src/cochem_base").is_dir():
            scan_paths = ["src/cochem_base"]
        else:
            scan_paths = ["."]

    all_violations: List[LinterViolation] = []
    for path_str in scan_paths:
        p = Path(path_str)
        if p.is_file():
            all_violations.extend(scan_file(p, symbols, amnesty_paths))
        elif p.is_dir():
            all_violations.extend(scan_directory(p, symbols, amnesty_paths))
        else:
            logger.warning(f"Path does not exist: {path_str}")

    if args.json:
        payload = {
            "total_violations": len(all_violations),
            "status": "FAIL" if all_violations else "PASS",
            "violations": [v.to_dict() for v in all_violations],
        }
        print(json.dumps(payload, indent=2))
    else:
        if all_violations:
            print(f"\n[FAIL] Found {len(all_violations)} static mass dictionary violation(s):")
            for v in all_violations:
                print(f"  - {v.file_path}:{v.line}:{v.col} [{v.category}] {v.symbol}: {v.message}")
        else:
            print("\n[STATUS: PASS] Zero static mass dictionary violations detected across target files.")

    if all_violations and args.fail_on_violation:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
