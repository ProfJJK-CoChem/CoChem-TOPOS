"""Hard CI AST & regex gate enforcing zero mocks, zero fakes, and zero simulation modes."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SELF_REL_PATH = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "build",
    "dist",
    "__pycache__",
    ".pytest_cache",
}
EXCLUDED_REL_PATHS = {
    "ci_tools/anti_spoof_linter.py",
    SELF_REL_PATH,
}

BANNED_IMPORT_ROOTS = ("unittest.mock", "mock", "pytest_mock")
BANNED_AST_REFS = {
    "MagicMock",
    "Mock",
    "AsyncMock",
    "PropertyMock",
    "create_autospec",
    "NonCallableMock",
    "mock_open",
    "monkeypatch",
}
BANNED_EXACT_SYMBOLS = {
    "generate_deterministic_solver_output",
    "poll_or_simulate_execution",
    "COLAB_WORKER_FAKE_GPU_NAME",
    "simulated_temp",
    "dummy_force",
}
BANNED_PREFIXES = ("fake_", "FAKE_")
SIMULATION_MODE_RE = re.compile(r"""mode\s*=\s*['"]simulation['"]""")


def _iter_repo_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if rel.as_posix() in EXCLUDED_REL_PATHS:
            continue
        files.append(path)
    return files


def _is_banned_symbol(name: str) -> bool:
    return name in BANNED_EXACT_SYMBOLS or name.startswith(BANNED_PREFIXES)


def _scan_python_file(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root).as_posix()
    source = path.read_text(encoding="utf-8", errors="replace")
    violations: list[str] = []

    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as exc:
        return [f"{rel}:{exc.lineno}: syntax error: {exc.msg}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for banned in BANNED_IMPORT_ROOTS:
                    if alias.name == banned or alias.name.startswith(f"{banned}."):
                        violations.append(
                            f"{rel}:{node.lineno}: banned import '{alias.name}'"
                        )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for banned in BANNED_IMPORT_ROOTS:
                if mod == banned or mod.startswith(f"{banned}."):
                    violations.append(
                        f"{rel}:{node.lineno}: banned from-import '{mod}'"
                    )
            if mod == "unittest":
                for alias in node.names:
                    if alias.name == "mock":
                        violations.append(
                            f"{rel}:{node.lineno}: banned import 'from unittest import mock'"
                        )
        elif isinstance(node, ast.Name):
            if node.id in BANNED_AST_REFS:
                violations.append(
                    f"{rel}:{node.lineno}: banned AST reference '{node.id}'"
                )
            elif _is_banned_symbol(node.id):
                violations.append(
                    f"{rel}:{node.lineno}: banned symbol '{node.id}'"
                )
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_AST_REFS:
                violations.append(
                    f"{rel}:{node.lineno}: banned AST attribute '{node.attr}'"
                )
            elif _is_banned_symbol(node.attr):
                violations.append(
                    f"{rel}:{node.lineno}: banned attribute '{node.attr}'"
                )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in BANNED_AST_REFS or _is_banned_symbol(node.name):
                violations.append(
                    f"{rel}:{node.lineno}: banned definition '{node.name}'"
                )
        elif isinstance(node, ast.arg):
            if node.arg in BANNED_AST_REFS or _is_banned_symbol(node.arg):
                violations.append(
                    f"{rel}:{node.lineno}: banned argument '{node.arg}'"
                )

    for line_no, line in enumerate(source.splitlines(), start=1):
        if SIMULATION_MODE_RE.search(line):
            violations.append(
                f"{rel}:{line_no}: banned simulation mode pattern"
            )

    return violations


def test_zero_mock_and_no_sim_ast_gate() -> None:
    """Repository must contain zero mock/monkeypatch/fake/simulation patterns."""
    all_violations: list[str] = []
    py_files = _iter_repo_python_files(REPO_ROOT)
    assert py_files, "Expected at least one Python file to scan in repository"
    for py_file in py_files:
        all_violations.extend(_scan_python_file(py_file, REPO_ROOT))
    assert not all_violations, (
        f"Zero-mock/zero-sim CI gate failed with {len(all_violations)} violation(s):\n"
        + "\n".join(all_violations)
    )


def test_anti_spoof_amnesty_empty_if_present() -> None:
    """If .anti_spoof_amnesty.json is present, it must parse to an empty list []."""
    amnesty_path = REPO_ROOT / ".anti_spoof_amnesty.json"
    if amnesty_path.exists():
        data = json.loads(amnesty_path.read_text(encoding="utf-8"))
        assert data == [], (
            f"{amnesty_path.name} must be empty ([]), found {len(data) if isinstance(data, list) else type(data).__name__}"
        )
