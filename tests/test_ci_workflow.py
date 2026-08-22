"""Unit tests for CoChem-TOPOS CI/CD GitHub Actions workflow.

Physically validates:
- .github/workflows/cochem_topos_ci.yml exists and is valid YAML.
- Canonical .yml extension is enforced and obsolete .yaml is absent.
- Matrix runners include ['ubuntu-latest', 'macos-latest', 'windows-latest'].
- Matrix python versions include ['3.10', '3.11', '3.12'].
- Mandatory Air-Gap Enforcement bash snippet is present verbatim.
- Execution logic of the Air-Gap script passes on clean directories and fails on forbidden files.
- Complete step sequence: checkout, setup-python, air-gap, install, lint/type-check, test with coverage, artifact upload.
- Zero banned mock/stub/placeholder tokens.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
CANONICAL_WORKFLOW_PATH = WORKFLOW_DIR / "cochem_topos_ci.yml"
OBSOLETE_WORKFLOW_PATH = WORKFLOW_DIR / "cochem_topos_ci.yaml"

MANDATORY_AIRGAP_SCRIPT = (
    'if [ -n "$(find . -type f \\( -name "*.h5" -o -name "*.gbw" -o -name "*.xyz" -o -name "cochem_system_config.json" \\))" ]; then\n'
    '  echo "Air-Gap Violation: Forbidden files found in the repository."\n'
    "  exit 1\n"
    "fi"
)

REQUIRED_RUNNERS = ["ubuntu-latest", "macos-latest", "windows-latest"]
REQUIRED_PYTHON_VERSIONS = ["3.10", "3.11", "3.12"]

BANNED_KEYWORD_PATTERNS = [
    r"\bmock\b",
    r"\bdummy\b",
    r"\bstub\b",
    r"\bplaceholder\b",
    r"\bfake\b",
    r"\btodo\b",
    r"\bfixme\b",
]


def _load_workflow_data() -> Dict[str, Any]:
    """Helper to parse workflow YAML file into dictionary."""
    assert CANONICAL_WORKFLOW_PATH.is_file(), f"Workflow file missing at {CANONICAL_WORKFLOW_PATH}"
    content = CANONICAL_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert isinstance(data, dict), "Workflow YAML must parse as a mapping/dictionary"
    return data


def _get_bash_executable() -> str:
    """Find the best available bash executable across Linux, macOS, and Windows."""
    # On Windows, Git Bash provides native Windows path resolution matching GitHub Actions runners
    git_bash_candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Git\bin\bash.exe",
    ]
    for candidate in git_bash_candidates:
        if Path(candidate).is_file():
            return candidate
    system_bash = shutil.which("bash")
    if system_bash:
        return system_bash
    raise FileNotFoundError("bash executable not found on system")


def _execute_bash_script(script: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Helper to execute a bash script in a target working directory."""
    bash_path = _get_bash_executable()
    return subprocess.run(
        [bash_path, "-c", script],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def test_workflow_file_exists_and_canonical() -> None:
    """Validate that cochem_topos_ci.yml physically exists and obsolete .yaml is absent."""
    assert CANONICAL_WORKFLOW_PATH.is_file(), f"Expected canonical workflow file at {CANONICAL_WORKFLOW_PATH}"
    assert not OBSOLETE_WORKFLOW_PATH.exists(), f"Obsolete workflow file {OBSOLETE_WORKFLOW_PATH} must be removed"
    content = CANONICAL_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert len(content.strip()) > 0, "cochem_topos_ci.yml must not be empty"


def test_workflow_valid_yaml() -> None:
    """Validate that cochem_topos_ci.yml parses as valid YAML with standard top-level keys."""
    data = _load_workflow_data()
    assert "name" in data, "Workflow must contain a 'name' field"
    assert "jobs" in data, "Workflow must contain a 'jobs' mapping"
    assert data.get("name") == "CoChem-TOPOS CI"


def test_workflow_triggers() -> None:
    """Validate triggers include push, pull_request, and workflow_dispatch."""
    data = _load_workflow_data()
    on_triggers = data.get("on")
    if on_triggers is None:
        raw_dict: Dict[Any, Any] = data
        on_triggers = raw_dict.get(True)
    assert on_triggers is not None, "Workflow must define 'on' triggers"

    assert "push" in on_triggers, "Workflow must trigger on 'push'"
    assert "pull_request" in on_triggers, "Workflow must trigger on 'pull_request'"
    assert "workflow_dispatch" in on_triggers, "Workflow must trigger on 'workflow_dispatch'"

    push_branches = on_triggers["push"].get("branches", [])
    pr_branches = on_triggers["pull_request"].get("branches", [])

    assert "main" in push_branches, "Push triggers must monitor 'main'"
    assert "dev" in push_branches, "Push triggers must monitor 'dev'"
    assert "main" in pr_branches, "Pull request triggers must monitor 'main'"
    assert "dev" in pr_branches, "Pull request triggers must monitor 'dev'"


def test_workflow_matrix_runners_and_python_versions() -> None:
    """Validate matrix strategy includes all 3 required runners and Python 3.10, 3.11, 3.12."""
    data = _load_workflow_data()
    jobs = data.get("jobs", {})
    assert len(jobs) >= 1, "At least one job must be defined in workflow"

    target_job = None
    for job_id, job_body in jobs.items():
        if "strategy" in job_body and "matrix" in job_body["strategy"]:
            target_job = job_body
            break

    assert target_job is not None, "Matrix job must be defined in workflow"
    strategy = target_job.get("strategy", {})
    matrix = strategy.get("matrix", {})

    os_matrix = matrix.get("os", [])
    py_matrix = matrix.get("python-version", [])

    for runner in REQUIRED_RUNNERS:
        assert runner in os_matrix, f"Matrix 'os' missing required runner '{runner}'"

    str_py_matrix = [str(v) for v in py_matrix]
    for py_ver in REQUIRED_PYTHON_VERSIONS:
        assert py_ver in str_py_matrix, f"Matrix 'python-version' missing required version '{py_ver}'"

    assert target_job.get("runs-on") == "${{ matrix.os }}", "runs-on must parameterize over ${{ matrix.os }}"


def test_workflow_exact_airgap_step_present() -> None:
    """Validate exact presence and structure of the mandatory Air-Gap Enforcement bash step."""
    data = _load_workflow_data()
    jobs = data.get("jobs", {})

    steps: List[Dict[str, Any]] = []
    for job in jobs.values():
        steps.extend(job.get("steps", []))

    airgap_step = None
    for step in steps:
        if step.get("name") == "Air-Gap Enforcement":
            airgap_step = step
            break

    assert airgap_step is not None, "Step named 'Air-Gap Enforcement' must exist in workflow"
    assert airgap_step.get("shell") == "bash", "Air-Gap Enforcement step must explicitly set 'shell: bash'"

    run_script = airgap_step.get("run", "").strip()

    # Verify key tokens in the find command
    assert 'find . -type f \\( -name "*.h5" -o -name "*.gbw" -o -name "*.xyz" -o -name "cochem_system_config.json" \\)' in run_script, (
        "Air-Gap find command does not match mandatory pattern specification"
    )
    assert 'Air-Gap Violation: Forbidden files found in the repository.' in run_script, (
        "Air-Gap violation message does not match mandatory specification"
    )
    assert "exit 1" in run_script, "Air-Gap step must exit 1 on violation"


def test_workflow_step_ordering() -> None:
    """Validate that Air-Gap Enforcement runs before any install, lint, or test steps."""
    data = _load_workflow_data()
    jobs = data.get("jobs", {})

    for job in jobs.values():
        steps = job.get("steps", [])
        step_names = [s.get("name", "") for s in steps]

        assert "Air-Gap Enforcement" in step_names, "Air-Gap Enforcement step missing from job steps"
        airgap_idx = step_names.index("Air-Gap Enforcement")

        for idx, step in enumerate(steps):
            run_cmd = step.get("run", "").lower()
            name_lower = step.get("name", "").lower()

            if "pip install" in run_cmd or "install" in name_lower:
                assert airgap_idx < idx, "Air-Gap Enforcement must precede dependency installation"
            if "ruff" in run_cmd or "mypy" in run_cmd or "lint" in name_lower:
                assert airgap_idx < idx, "Air-Gap Enforcement must precede linting/type-checking"
            if "pytest" in run_cmd or "test" in name_lower:
                if step.get("name") != "Air-Gap Enforcement":
                    assert airgap_idx < idx, "Air-Gap Enforcement must precede test execution"


def test_workflow_all_required_steps_present() -> None:
    """Validate presence of all mandatory steps: checkout, setup-python, airgap, install, lint, test, upload."""
    data = _load_workflow_data()
    jobs = data.get("jobs", {})

    all_steps: List[Dict[str, Any]] = []
    for job in jobs.values():
        all_steps.extend(job.get("steps", []))

    uses_list = [s.get("uses", "") for s in all_steps]
    runs_list = [s.get("run", "") for s in all_steps]
    all_runs_text = "\n".join(runs_list)

    # 1. Checkout
    assert any("actions/checkout" in u for u in uses_list), "Workflow missing 'actions/checkout' step"

    # 2. Setup Python
    assert any("actions/setup-python" in u for u in uses_list), "Workflow missing 'actions/setup-python' step"

    # 3. Air-Gap Enforcement
    assert any(s.get("name") == "Air-Gap Enforcement" for s in all_steps), "Workflow missing Air-Gap step"

    # 4. Install Dependencies
    assert "pip install" in all_runs_text, "Workflow missing 'pip install' step"

    # 5. Lint and Type Check
    assert "ruff check" in all_runs_text, "Workflow missing 'ruff check' step"
    assert "mypy" in all_runs_text, "Workflow missing 'mypy' step"

    # 6. Run Unit Tests with Coverage
    assert "pytest" in all_runs_text, "Workflow missing 'pytest' step"
    assert "--cov" in all_runs_text, "Pytest step must include coverage flags"

    # 7. Upload Artifacts
    assert any("actions/upload-artifact" in u for u in uses_list), "Workflow missing 'actions/upload-artifact' step"


def test_workflow_no_banned_keywords() -> None:
    """Validate zero banned placeholder/mock tokens in workflow file."""
    content = CANONICAL_WORKFLOW_PATH.read_text(encoding="utf-8")
    for pattern in BANNED_KEYWORD_PATTERNS:
        match = re.search(pattern, content, re.IGNORECASE)
        assert match is None, f"Forbidden keyword pattern '{pattern}' matched in workflow YAML: {match}"


def test_physical_airgap_bash_execution_on_clean_dir(tmp_path: Path) -> None:
    """Physically execute the Air-Gap script in a clean temporary directory and verify exit 0."""
    (tmp_path / "README.md").write_text("# Clean Repository", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='cochem-topos'", encoding="utf-8")
    src_dir = tmp_path / "core_engine"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("print('Hello')", encoding="utf-8")

    result = _execute_bash_script(MANDATORY_AIRGAP_SCRIPT, cwd=tmp_path)
    assert result.returncode == 0, f"Air-Gap script failed on clean directory: {result.stderr}"
    assert "Air-Gap Violation" not in result.stdout


@pytest.mark.parametrize(
    "forbidden_filename",
    [
        "restricted_checkpoint.h5",
        "wavefunction.gbw",
        "geometry.xyz",
        "cochem_system_config.json",
    ],
)
def test_physical_airgap_bash_execution_on_forbidden_files(tmp_path: Path, forbidden_filename: str) -> None:
    """Physically execute the Air-Gap script against forbidden files and verify exit 1."""
    test_dir = tmp_path / f"test_{forbidden_filename.replace('.', '_')}"
    test_dir.mkdir()
    (test_dir / "valid_code.py").write_text("# benign file", encoding="utf-8")
    (test_dir / forbidden_filename).write_text("FORBIDDEN CONTENT", encoding="utf-8")

    result = _execute_bash_script(MANDATORY_AIRGAP_SCRIPT, cwd=test_dir)
    assert result.returncode == 1, (
        f"Air-Gap script unexpectedly passed on forbidden file '{forbidden_filename}'"
    )
    assert "Air-Gap Violation: Forbidden files found in the repository." in result.stdout


def test_physical_airgap_bash_execution_on_nested_forbidden_files(tmp_path: Path) -> None:
    """Physically execute the Air-Gap script against forbidden files in deep subdirectories."""
    nested_dir = tmp_path / "deep" / "nested" / "cache"
    nested_dir.mkdir(parents=True)
    (nested_dir / "quantum_state.gbw").write_text("WAVEFUNCTION", encoding="utf-8")

    result = _execute_bash_script(MANDATORY_AIRGAP_SCRIPT, cwd=tmp_path)
    assert result.returncode == 1, "Air-Gap script failed to detect nested forbidden .gbw file"
    assert "Air-Gap Violation: Forbidden files found in the repository." in result.stdout


def test_physical_airgap_bash_execution_on_current_repo() -> None:
    """Physically execute the Air-Gap script on the actual CoChem-TOPOS repository root."""
    result = _execute_bash_script(MANDATORY_AIRGAP_SCRIPT, cwd=REPO_ROOT)
    assert result.returncode == 0, (
        f"Air-Gap violation detected in actual CoChem-TOPOS repository!\n"
        f"Stdout: {result.stdout}\nStderr: {result.stderr}"
    )
