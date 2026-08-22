"""Unit tests for CoChem-TOPOS .gitignore file validation.

Physically validates that the Tripartite Filesystem Air-Gap exclusion rules
are properly formatted in .gitignore and accurately enforced by Git.
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GITIGNORE_PATH = REPO_ROOT / ".gitignore"

MANDATORY_SECTIONS = [
    "# 1. Absolute ban on the Tripartite Data Workspace",
    "# 2. Ban on Persistent Databases & Registries (Prevents path hallucinations on PR merges)",
    "# 3. Ban on Raw User Structural Data",
    "# 4. Ban on Quantum Chemical Wavefunctions & Scratch Tensors",
    "# 5. Standard Python Ignored Environments & Ephemeral IPC",
]

MANDATORY_PATTERNS = [
    "CoChem_Artifacts/",
    "*.h5",
    "*.hdf5",
    "*.parquet",
    "cochem_system_config.json",
    "TOPOS_Runtime_State.json",
    "*.xyz",
    "*.mol",
    "*.pdb",
    "*.cif",
    "*.gbw",
    "*.tmp",
    "*.ges",
    "*.hess",
    "*.chk",
    "*scf*.out",
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "*.sock",
    "*.pid",
]


def _assert_paths_are_ignored(paths: list[str]) -> None:
    """Helper asserting that git check-ignore confirms every path in the list is ignored."""
    for target in paths:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", target],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"Target path '{target}' was expected to be ignored by git, "
            f"but git check-ignore returned code {result.returncode} (stderr: {result.stderr.strip()})"
        )


def _assert_paths_are_not_ignored(paths: list[str]) -> None:
    """Helper asserting that git check-ignore confirms every path in the list is NOT ignored."""
    for target in paths:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", target],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, (
            f"Trackable source target '{target}' was unexpectedly ignored by git."
        )


def test_gitignore_file_exists() -> None:
    """Validate that .gitignore physically exists at repository root."""
    assert GITIGNORE_PATH.is_file(), f"Expected .gitignore at {GITIGNORE_PATH}"
    content = GITIGNORE_PATH.read_text(encoding="utf-8")
    assert len(content.strip()) > 0, ".gitignore file must not be empty"


def test_gitignore_contains_required_sections() -> None:
    """Validate that .gitignore contains all mandatory section headers."""
    content = GITIGNORE_PATH.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]

    for section in MANDATORY_SECTIONS:
        assert section in lines, f"Missing mandatory section header: {section}"


def test_gitignore_contains_required_patterns() -> None:
    """Validate that .gitignore contains all mandatory pattern entries."""
    content = GITIGNORE_PATH.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]

    for pattern in MANDATORY_PATTERNS:
        assert pattern in lines, f"Missing mandatory ignore pattern: {pattern}"


def test_section1_tripartite_data_workspace_ignored() -> None:
    """Validate Section 1: Absolute ban on Tripartite Data Workspace."""
    targets = [
        "CoChem_Artifacts/",
        "CoChem_Artifacts/run_01/output.dat",
        "nested/path/CoChem_Artifacts/",
    ]
    _assert_paths_are_ignored(targets)


def test_section2_persistent_databases_and_registries_ignored() -> None:
    """Validate Section 2: Ban on Persistent Databases & Registries."""
    targets = [
        "trajectory.h5",
        "nested/dir/storage.hdf5",
        "records.parquet",
        "cochem_system_config.json",
        "TOPOS_Runtime_State.json",
    ]
    _assert_paths_are_ignored(targets)


def test_section3_raw_structural_data_ignored() -> None:
    """Validate Section 3: Ban on Raw User Structural Data."""
    targets = [
        "structure.xyz",
        "nested/ligand.mol",
        "protein.pdb",
        "lattice.cif",
    ]
    _assert_paths_are_ignored(targets)


def test_section4_quantum_chemical_wavefunctions_and_scratch_tensors_ignored() -> None:
    """Validate Section 4: Ban on Quantum Chemical Wavefunctions & Scratch Tensors."""
    targets = [
        "wavefunction.gbw",
        "scratch.tmp",
        "orbitals.ges",
        "frequencies.hess",
        "converged.chk",
        "orca_scf.out",
        "scf_energy.out",
        "calculation_scf_final.out",
    ]
    _assert_paths_are_ignored(targets)


def test_section5_python_environments_and_ephemeral_ipc_ignored() -> None:
    """Validate Section 5: Standard Python Ignored Environments & Ephemeral IPC."""
    targets = [
        "__pycache__/",
        "bytecode.pyc",
        ".venv/",
        "ipc_channel.sock",
        "daemon.pid",
    ]
    _assert_paths_are_ignored(targets)


def test_trackable_source_files_not_ignored() -> None:
    """Validate that repository source files and configuration are NOT ignored."""
    targets = [
        "README.md",
        "pyproject.toml",
        "conftest.py",
        "pytest.ini",
        "core_engine/main.py",
        "topology/graph.py",
        "tests/test_gitignore.py",
    ]
    _assert_paths_are_not_ignored(targets)
