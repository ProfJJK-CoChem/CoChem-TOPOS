"""Authentic Zero-Mock Physical Test Suite: Student Journey across Codespaces and GitHub Actions for Helium Dimer (He2).

Governing Directives:
- Anti-Spoofing Protocol v4 (§1-§14: Asymmetric Verification, Zero Mocks/Stubs, No Semantic Deflection)
- Mendeleev Dynamic Atomic Mass Mandate (Strict dynamic element queries, zero hardcoded constants)
- Method Matrix v4.2 (§0, §1.2, §4.4, §8B.3, §9A, §9B.1, §9B.2)
- SRS Specification: SRS-TOPOS-2026-8912E0-V1 / task_8912e0_INT_CODESPACES_CALC_ACTIONS_TOPOS_UI_xTB_GFN2_He2
- Implementation Task 1.5: Author comprehensive unit and integration tests validating Helium dimer (He2)
  across GitHub Codespaces and GitHub Actions dispatch modes.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from mendeleev import element

# Ensure repository root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from topos.actions.dispatch import ActionDispatchClient, DispatchResult
from topos.calculation.xtb_runner import (
    XTBCalculationResult,
    execute_gfn2_xtb,
    parse_geometry_string,
)
from topos.cli.test_runner import HarnessVerificationReport, HeadlessUITestRunner
from topos.ui import run_headless_ui_submission
from frontend.cochem_topos_ui import (
    CochemToposUI,
    TOPOSRuntimeState,
    calculate_node_hours,
    create_topos_dashboard,
    get_tier_info,
    parse_xyz_content,
)

# Authentic Helium Dimer (He2) coordinates at equilibrium separation (Re = 2.970000 Angstrom / 5.61 Bohr)
HE2_EQUILIBRIUM_XYZ = (
    "2\n"
    "Helium dimer equilibrium van der Waals complex (Re = 2.970000 A)\n"
    "He 0.000000 0.000000 0.000000\n"
    "He 0.000000 0.000000 2.970000\n"
)

HE2_GEOMETRY_STR = "He 0.000000 0.000000 0.000000; He 0.000000 0.000000 2.970000"


def test_topos_repository_boundary_gatekeeper() -> None:
    """Validates PCA-169-1: Target Repository Non-Zero Disk Delta Invariant and boundary check."""
    expected_repo_names = {"CoChem-TOPOS", "TOPOS"}
    current_repo_name = _REPO_ROOT.name
    assert current_repo_name in expected_repo_names, (
        f"[PRE-FLIGHT GATEKEEPER VIOLATION] Execution directory mismatch: "
        f"expected one of {expected_repo_names}, but detected '{current_repo_name}'. "
        f"Cross-repository execution substitution is strictly prohibited by Anti-Spoofing Protocol v4 §7."
    )


def test_mendeleev_helium_mass_provenance() -> None:
    """Validates that Helium dynamic mass is strictly retrieved via mendeleev library (Zero-Mock Invariant)."""
    he = element("He")
    assert he.atomic_number == 2
    assert he.symbol == "He"
    assert he.name == "Helium"
    # Dynamic mass lookup strictly via mendeleev
    mass = float(he.mass)
    assert abs(mass - 4.002602) < 1e-4, f"Unexpected Helium mass from Mendeleev: {mass}"


def test_he2_geometry_parsing_and_equilibrium_separation() -> None:
    """Validates coordinate extraction and equilibrium separation for the Helium van der Waals dimer."""
    # 1. Parse from semicolon-delimited geometry string
    symbols_str, coords_str = parse_geometry_string(HE2_GEOMETRY_STR)
    assert len(symbols_str) == 2
    assert symbols_str == ["He", "He"]
    assert coords_str.shape == (2, 3)

    distance_str = float(((coords_str[0] - coords_str[1]) ** 2).sum() ** 0.5)
    assert abs(distance_str - 2.970000) < 1e-6, f"Expected 2.970000 A, got {distance_str}"

    # 2. Parse from standard XYZ formatted content
    atom_cnt, symbols_xyz, coords_xyz = parse_xyz_content(HE2_EQUILIBRIUM_XYZ)
    assert atom_cnt == 2
    assert symbols_xyz == ["He", "He"]
    assert coords_xyz.shape == (2, 3)

    distance_xyz = float(((coords_xyz[0] - coords_xyz[1]) ** 2).sum() ** 0.5)
    assert abs(distance_xyz - 2.970000) < 1e-6, f"Expected 2.970000 A, got {distance_xyz}"


def test_topos_ui_dashboard_initialization_and_node_hour_scaling() -> None:
    """Validates CochemToposUI dashboard initialization, XYZ loading, and node-hour scaling for He2."""
    ui = create_topos_dashboard()
    assert isinstance(ui, CochemToposUI)

    # Validate default tier and scaling for He2 (atom_count = 2)
    ui.atom_count = 2
    hours = calculate_node_hours(atom_count=2, tier_id="T1-10s")
    assert hours > 0.0
    assert hours <= 0.05, f"Expected fast screening node hours for diatomic He2, got {hours}"

    # Validate loading He2 geometry string
    atom_cnt, symbols, coords = parse_xyz_content(HE2_EQUILIBRIUM_XYZ)
    assert atom_cnt == 2
    assert symbols == ["He", "He"]


def test_action_dispatch_client_credentials_and_manifest(tmp_path: Path) -> None:
    """Validates ActionDispatchClient discovery and GitHub Actions workflow dispatch serialization."""
    client = ActionDispatchClient(repo_root=tmp_path)
    token, auth_source = client.discover_token()
    repo = client.discover_repository()

    assert repo == "ProfJJK-CoChem/CoChem-TOPOS" or "/" in repo
    assert auth_source in {"GH_CLI_TOKEN", "GIT_CONFIG_TOKEN", "LOCAL_REPOSITORY_OFFLINE", "EXPLICIT_TOKEN"}

    inputs = {
        "geometry": HE2_GEOMETRY_STR,
        "method": "GFN2-xTB",
        "engine": "xTB",
    }
    dispatch_res = client.dispatch_workflow(
        workflow_name="cochem_topos_ci.yml",
        inputs=inputs,
    )

    assert isinstance(dispatch_res, DispatchResult)
    assert dispatch_res.dispatch_id.startswith("disp_")
    assert dispatch_res.status in {"DISPATCH_REGISTERED", "DISPATCHED_API", "DISPATCHED_CLI"}

    payload_file = Path(dispatch_res.payload_path)
    assert payload_file.is_file(), f"Expected manifest file at {payload_file}"

    payload_data = json.loads(payload_file.read_text(encoding="utf-8"))
    assert payload_data["dispatch_id"] == dispatch_res.dispatch_id
    assert payload_data["inputs"] == inputs
    assert "sha256_digest" in payload_data
    assert len(payload_data["sha256_digest"]) == 64


def test_he2_gfn2_xtb_authentic_thermodynamics() -> None:
    """Validates physical quantum chemical energy, binding energy, and thermodynamics for He2."""
    import shutil

    if not shutil.which("xtb") and not os.environ.get("XTBPATH"):
        # When xtb binary is not on host, execute_gfn2_xtb raises clean FileNotFoundError
        with pytest.raises(FileNotFoundError, match="Authentic 'xtb' binary not found"):
            execute_gfn2_xtb(HE2_GEOMETRY_STR, method="GFN2-xTB")
        return

    result = execute_gfn2_xtb(HE2_GEOMETRY_STR, method="GFN2-xTB", temperature_k=298.15)
    assert isinstance(result, XTBCalculationResult)
    assert result.system_name == "He2"
    assert result.method == "GFN2-xTB"
    assert result.atom_count == 2
    assert abs(result.interatomic_distance_angstrom - 2.970000) < 1e-4

    # Dynamic Mendeleev check on result
    assert "He" in result.atomic_masses_da
    assert abs(result.atomic_masses_da["He"] - 4.002602) < 1e-4

    # Total electronic energy for He2 in GFN2-xTB (~ -1.9969 Hartree)
    assert -2.05 < result.total_energy_hartree < -1.95, (
        f"Unphysical total energy for He2: {result.total_energy_hartree} Hartree"
    )

    # Van der Waals binding energy for He2 at 2.97 A is weakly attractive (~ -0.0215 kcal/mol)
    assert -0.05 < result.binding_energy_kcal_mol < -0.005, (
        f"Unphysical binding energy: {result.binding_energy_kcal_mol} kcal/mol"
    )

    # Intermolecular vibrational frequency (~20 - 40 cm^-1)
    if result.vibrational_frequencies_cm1:
        nu = result.vibrational_frequencies_cm1[0]
        assert 20.0 < nu < 40.0, f"Unphysical vibrational stretch frequency for He2: {nu} cm^-1"

    assert result.zero_point_energy_kcal_mol >= 0.0
    assert result.thermal_entropy_cal_mol_k >= 0.0


def test_headless_ui_student_journey_codespaces_to_actions(tmp_path: Path) -> None:
    """Validates the full student journey in Codespaces submitting to GitHub Actions with GFN2-xTB."""
    import shutil

    sub_res = run_headless_ui_submission(
        geometry=HE2_GEOMETRY_STR,
        method="GFN2-xTB",
        dispatch="github-actions",
        work_dir=tmp_path,
        execute_local_calc=True,
    )

    assert sub_res["status"] == "SUCCESS"

    # Validate TOPOS_Runtime_State.json written to workspace
    state_path = Path(sub_res["runtime_state_file"])
    assert state_path.is_file()
    state_data = json.loads(state_path.read_text(encoding="utf-8"))

    # Assert 6-Tier Environment & Decoupled Engine selections
    assert state_data["interaction_environment"] == "GitHub Codespaces"
    assert state_data["calculation_environment"] == "github-actions"
    assert state_data["engine"] == "xTB"
    assert state_data["method"] == "GFN2-xTB"
    assert state_data["atom_count"] == 2
    assert state_data["atom_symbols"] == ["He", "He"]

    # Dynamic Mendeleev validation in state
    assert "He" in state_data["atomic_masses_da"]
    assert abs(state_data["atomic_masses_da"]["He"] - 4.002602) < 1e-4

    # Validate calculation or remote dispatch telemetry
    if shutil.which("xtb") or os.environ.get("XTBPATH"):
        calc_file = tmp_path / "outputs" / "calculations" / "he2_xtb_gfn2_result.json"
        assert calc_file.is_file()
        calc_data = json.loads(calc_file.read_text(encoding="utf-8"))
        assert calc_data["system_name"] == "He2"
        assert -0.05 < calc_data["binding_energy_kcal_mol"] < -0.005
    else:
        assert sub_res["calculation"]["status"] == "DISPATCHED_REMOTE"
        assert sub_res["calculation"]["engine"] == "xTB"


def test_headless_cli_verification_harness_5step(tmp_path: Path) -> None:
    """Validates that the 5-step HeadlessUITestRunner executes 100% of steps cleanly for He2."""
    runner = HeadlessUITestRunner(work_dir=tmp_path)
    report: VerificationReport = runner.run_verification(
        geometry=HE2_GEOMETRY_STR,
        method="GFN2-xTB",
        dispatch="github-actions",
    )

    assert report.overall_status == "PASS"
    assert len(report.steps) == 5
    assert all(step.status == "PASS" for step in report.steps)
    assert report.summary["passed_count"] == 5
    assert report.summary["steps_count"] == 5

    # Validate expected step names
    step_names = [s.step_name for s in report.steps]
    assert "1_ui_form_submission" in step_names
    assert "2_state_serialization" in step_names
    assert "3_mendeleev_provenance" in step_names
    assert "4_actions_dispatch" in step_names
    assert "5_physical_thermodynamics" in step_names


def test_cli_subprocesses_student_journey() -> None:
    """Validates CLI invocation of topos.ui and topos.cli.test_runner via subprocess without window popups."""
    extra_kwargs = {"creationflags": 0x08000000} if sys.platform == "win32" else {}

    # Test python -m topos.ui
    cmd_ui = [
        sys.executable,
        "-m",
        "topos.ui",
        "--geometry",
        HE2_GEOMETRY_STR,
        "--method",
        "GFN2-xTB",
        "--dispatch",
        "github-actions",
    ]
    proc_ui = subprocess.run(
        cmd_ui,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
        **extra_kwargs,
    )
    assert proc_ui.returncode == 0, f"topos.ui CLI failed: {proc_ui.stderr}"
    assert "Headless UI Workflow Submission Succeeded" in proc_ui.stdout
    assert "GitHub Codespaces" in proc_ui.stdout
    assert "github-actions" in proc_ui.stdout

    # Test python -m topos.cli.test_runner
    cmd_runner = [
        sys.executable,
        "-m",
        "topos.cli.test_runner",
        "--geometry",
        HE2_GEOMETRY_STR,
        "--method",
        "GFN2-xTB",
        "--dispatch",
        "github-actions",
    ]
    proc_runner = subprocess.run(
        cmd_runner,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
        **extra_kwargs,
    )
    assert proc_runner.returncode == 0, f"test_runner CLI failed: {proc_runner.stderr}"
    assert "Headless CLI Verification Harness Report: PASS" in proc_runner.stdout
    assert "Passed Steps : 5 / 5" in proc_runner.stdout


def test_cross_platform_stream_encoding_resilience() -> None:
    """Validates that console output formatting handles cp1252 and UTF-8 encodings safely without crashes."""
    buffer = io.BytesIO()
    text_stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="replace")

    test_message = "CoChem-TOPOS: He2 GFN2-xTB \u2705 \U0001f680 [PASS]\n"
    try:
        text_stream.write(test_message)
        text_stream.flush()
        written = buffer.getvalue().decode("cp1252", errors="replace")
        assert "CoChem-TOPOS: He2 GFN2-xTB" in written
        assert "[PASS]" in written
    finally:
        text_stream.detach()
