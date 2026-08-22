"""Unit tests for CoChem-TOPOS requirements.txt validation.

Physically validates that the requirements specification defines exactly the
lightweight orchestration and topological routing dependencies while strictly
excluding heavy computational engines and forbidden keywords.
"""

from pathlib import Path
import re
from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_PATH = REPO_ROOT / "requirements.txt"

MANDATORY_DEPENDENCIES = [
    "networkx",
    "scipy",
    "numpy",
    "h5py",
    "ipywidgets",
    "plotly",
    "pydantic",
    "mendeleev",
    "ase",
    "jinja2",
    "psutil",
    "pynvml",
]

DISALLOWED_HEAVY_PACKAGES = [
    "torch",
    "pytorch",
    "orca",
    "pyscf",
    "tensorflow",
    "jax",
    "openmm",
    "psi4",
    "qiskit",
    "cp2k",
    "vasp",
    "gaussian",
]

BANNED_KEYWORD_PATTERNS = [
    r"\bmock\b",
    r"\bexample\b",
    r"\bstub\b",
    r"\bdummy\b",
    r"\bplaceholder\b",
    r"\bfake\b",
    r"\bsample\b",
    r"\btodo\b",
]


def _load_raw_lines() -> list[str]:
    """Helper to load all raw lines from requirements.txt."""
    assert REQUIREMENTS_PATH.is_file(), f"Expected requirements.txt at {REQUIREMENTS_PATH}"
    content = REQUIREMENTS_PATH.read_text(encoding="utf-8")
    return content.splitlines()


def _load_cleaned_requirements() -> list[str]:
    """Helper to extract active dependency lines ignoring comments and blank lines."""
    raw_lines = _load_raw_lines()
    cleaned = []
    for line in raw_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            cleaned.append(stripped)
    return cleaned


def test_requirements_file_exists_and_non_empty() -> None:
    """Validate that requirements.txt physically exists at repository root and is not empty."""
    assert REQUIREMENTS_PATH.is_file(), f"requirements.txt missing at {REQUIREMENTS_PATH}"
    content = REQUIREMENTS_PATH.read_text(encoding="utf-8")
    assert len(content.strip()) > 0, "requirements.txt must not be empty"


def test_requirements_contains_all_mandatory_dependencies() -> None:
    """Validate that all 12 mandatory dependencies are defined in requirements.txt."""
    req_lines = _load_cleaned_requirements()
    parsed_names = [Requirement(line).name.lower() for line in req_lines]

    for dep in MANDATORY_DEPENDENCIES:
        assert dep.lower() in parsed_names, f"Mandatory dependency '{dep}' missing from requirements.txt"


def test_requirements_exact_package_set() -> None:
    """Validate that requirements.txt contains exactly the 12 expected packages and no unexpected extras."""
    req_lines = _load_cleaned_requirements()
    parsed_names = {Requirement(line).name.lower() for line in req_lines}
    expected_names = {dep.lower() for dep in MANDATORY_DEPENDENCIES}

    missing = expected_names - parsed_names
    unexpected = parsed_names - expected_names

    assert not missing, f"Missing required dependencies: {sorted(missing)}"
    assert not unexpected, f"Unexpected additional dependencies found: {sorted(unexpected)}"


def test_requirements_exact_line_sequence() -> None:
    """Validate that the non-empty active requirements match the exact ordered sequence."""
    req_lines = _load_cleaned_requirements()
    assert req_lines == MANDATORY_DEPENDENCIES, (
        f"Active requirements lines do not match expected sequence.\n"
        f"Actual: {req_lines}\nExpected: {MANDATORY_DEPENDENCIES}"
    )


def test_requirements_disallowed_heavy_packages_absent() -> None:
    """Validate that heavy computational physics/quantum packages are absent."""
    req_lines = _load_cleaned_requirements()
    parsed_names = {Requirement(line).name.lower() for line in req_lines}

    for heavy in DISALLOWED_HEAVY_PACKAGES:
        assert heavy.lower() not in parsed_names, (
            f"Disallowed heavy compute package '{heavy}' must not be in lightweight routing requirements.txt"
        )


def test_requirements_no_forbidden_keywords() -> None:
    """Validate that requirements.txt contains zero mock/stub/placeholder tokens."""
    content = REQUIREMENTS_PATH.read_text(encoding="utf-8")
    for pattern in BANNED_KEYWORD_PATTERNS:
        match = re.search(pattern, content, re.IGNORECASE)
        assert match is None, f"Forbidden keyword pattern '{pattern}' matched in requirements.txt: {match}"


def test_requirements_uniqueness_and_no_duplicates() -> None:
    """Validate that no duplicate package specifications exist."""
    req_lines = _load_cleaned_requirements()
    parsed_names = [Requirement(line).name.lower() for line in req_lines]
    unique_names = set(parsed_names)

    assert len(parsed_names) == len(unique_names), (
        f"Duplicate package entries found in requirements.txt: {parsed_names}"
    )


def test_requirements_valid_pep508_format() -> None:
    """Validate that every dependency entry is a well-formed PEP 508 requirement specification."""
    req_lines = _load_cleaned_requirements()
    for line in req_lines:
        req = Requirement(line)
        assert req.name, f"Invalid requirement specification: '{line}'"
        assert line == line.strip(), f"Requirement line has leading or trailing whitespace: '{line}'"


def test_requirements_line_count() -> None:
    """Validate that the active requirement lines count is exactly 12."""
    req_lines = _load_cleaned_requirements()
    assert len(req_lines) == 12, f"Expected exactly 12 active dependency lines, got {len(req_lines)}"
