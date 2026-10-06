"""Authentic End-to-End Integration Test: TOPOS Headless UI, Action Dispatch, and He2 GFN2-xTB Thermodynamics.

Governed by Anti-Spoofing Protocol v4 (§1-§14), Method Matrix v4, and Mendeleev Dynamic Mass Mandate.
Validates:
1. Deterministic headless UI form submission replicating student journey in GitHub Codespaces.
2. Standardized ActionDispatchClient leveraging repository credentials for GitHub Actions execution.
3. Authentic GFN2-xTB potential energy, binding energy, vibrational frequencies, and thermodynamics
   for the weakly bound Helium van der Waals dimer (He2, R = 3.0 A).
4. Strict Mendeleev mass provenance without stubs, mocks, or hardcoded constants.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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
from topos.cli.test_runner import HeadlessUITestRunner
from topos.ui import run_headless_ui_submission

HE2_GEOMETRY_STR = "He 0.0 0.0 0.0; He 0.0 0.0 3.0"


def test_mendeleev_helium_mass_provenance() -> None:
    """Verifies that atomic mass is retrieved dynamically via Mendeleev."""
    he = element("He")
    mass = float(he.mass)
    assert abs(mass - 4.002602) < 1e-4, f"Unexpected helium mass: {mass}"
    assert he.atomic_number == 2
    assert he.symbol == "He"


def test_geometry_parsing_and_interatomic_distance() -> None:
    """Tests geometry string parsing for the Helium dimer at 3.0 Angstrom separation."""
    symbols, coords = parse_geometry_string(HE2_GEOMETRY_STR)
    assert len(symbols) == 2
    assert symbols == ["He", "He"]
    assert coords.shape == (2, 3)

    distance = float(((coords[0] - coords[1]) ** 2).sum() ** 0.5)
    assert abs(distance - 3.0) < 1e-6, f"Expected 3.0 A, got {distance}"


def test_he2_gfn2_xtb_authentic_thermodynamics() -> None:
    """Verifies that GFN2-xTB calculations enforce authentic execution without stubs."""
    import os
    import shutil

    if not shutil.which("xtb") and not os.environ.get("XTBPATH"):
        with pytest.raises(FileNotFoundError, match="Authentic 'xtb' binary not found"):
            execute_gfn2_xtb(HE2_GEOMETRY_STR, method="GFN2-xTB")
        return

    result = execute_gfn2_xtb(HE2_GEOMETRY_STR, method="GFN2-xTB", temperature_k=298.15)

    assert isinstance(result, XTBCalculationResult)
    assert result.system_name == "He2"
    assert result.method == "GFN2-xTB"
    assert result.atom_count == 2
    assert abs(result.interatomic_distance_angstrom - 3.0) < 1e-6

    # Dynamic Mendeleev check
    assert "He" in result.atomic_masses_da
    assert abs(result.atomic_masses_da["He"] - 4.002602) < 1e-4

    # Physical energy constraints:
    # He monomer in GFN2 is ~ -0.9984 Hartree; dimer is ~ -1.9969 Hartree
    assert -2.05 < result.total_energy_hartree < -1.95, (
        f"Unphysical total energy for He2: {result.total_energy_hartree}"
    )

    # Van der Waals binding energy for He2 at 3.0 A is ~ -0.0215 kcal/mol (weakly bound)
    assert -0.05 < result.binding_energy_kcal_mol < -0.005, (
        f"Unphysical binding energy: {result.binding_energy_kcal_mol} kcal/mol"
    )

    # Fundamental vibrational frequency (low-frequency intermolecular stretch ~25-35 cm^-1)
    if result.vibrational_frequencies_cm1:
        nu = result.vibrational_frequencies_cm1[0]
        assert 20.0 < nu < 40.0, f"Unphysical vibrational frequency for He2: {nu} cm^-1"

    # Thermodynamic properties
    assert result.zero_point_energy_kcal_mol >= 0.0
    assert result.thermal_entropy_cal_mol_k >= 0.0


def test_action_dispatch_client_local_credentials(tmp_path: Path) -> None:
    """Verifies standardized ActionDispatchClient handles credentials and writes verified manifests."""
    client = ActionDispatchClient(repo_root=tmp_path)
    token, auth_source = client.discover_token()
    repo = client.discover_repository()

    assert repo == "ProfJJK-CoChem/CoChem-TOPOS" or "/" in repo
    assert auth_source is not None

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
    assert payload_file.is_file()
    payload_data = json.loads(payload_file.read_text(encoding="utf-8"))
    assert payload_data["dispatch_id"] == dispatch_res.dispatch_id
    assert payload_data["inputs"] == inputs
    assert "sha256_digest" in payload_data


def test_headless_ui_form_submission(tmp_path: Path) -> None:
    """Verifies run_headless_ui_submission replicates UI form submission without a browser."""
    import os
    import shutil

    sub_res = run_headless_ui_submission(
        geometry=HE2_GEOMETRY_STR,
        method="GFN2-xTB",
        dispatch="github-actions",
        work_dir=tmp_path,
        execute_local_calc=True,
    )

    assert sub_res["status"] == "SUCCESS"

    # Validate TOPOS_Runtime_State.json
    state_path = Path(sub_res["runtime_state_file"])
    assert state_path.is_file()
    state_data = json.loads(state_path.read_text(encoding="utf-8"))

    assert state_data["interaction_environment"] == "GitHub Codespaces"
    assert state_data["calculation_environment"] == "github-actions"
    assert state_data["method"] == "GFN2-xTB"
    assert state_data["engine"] == "xTB"
    assert state_data["atom_count"] == 2
    assert state_data["atom_symbols"] == ["He", "He"]
    assert abs(state_data["atomic_masses_da"]["He"] - 4.002602) < 1e-4

    # Validate calculation artifact
    if shutil.which("xtb") or os.environ.get("XTBPATH"):
        calc_out_file = tmp_path / "outputs" / "calculations" / "he2_xtb_gfn2_result.json"
        assert calc_out_file.is_file()
        calc_data = json.loads(calc_out_file.read_text(encoding="utf-8"))
        assert calc_data["system_name"] == "He2"
        assert -0.05 < calc_data["binding_energy_kcal_mol"] < -0.005
    else:
        assert sub_res["calculation"]["status"] == "DISPATCHED_REMOTE"


def test_headless_cli_verification_harness_e2e(tmp_path: Path) -> None:
    """Verifies the HeadlessUITestRunner executes the 5-step verification harness to 100% pass."""
    runner = HeadlessUITestRunner(work_dir=tmp_path)
    report = runner.run_verification(
        geometry=HE2_GEOMETRY_STR,
        method="GFN2-xTB",
        dispatch="github-actions",
    )

    assert report.overall_status == "PASS"
    assert len(report.steps) == 5
    assert all(s.status == "PASS" for s in report.steps)
    assert report.summary["passed_count"] == 5


def test_cli_invocation_student_journey() -> None:
    """Verifies CLI execution of python -m topos.ui and python -m topos.cli.test_runner."""
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
        creationflags=0x08000000 if sys.platform == "win32" else 0,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc_ui.returncode == 0, f"topos.ui failed: {proc_ui.stderr}"
    assert "Headless UI Workflow Submission Succeeded" in proc_ui.stdout
    assert "GitHub Codespaces" in proc_ui.stdout
    assert "github-actions" in proc_ui.stdout

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
        creationflags=0x08000000 if sys.platform == "win32" else 0,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc_runner.returncode == 0, f"test_runner failed: {proc_runner.stderr}"
    assert "Headless CLI Verification Harness Report: PASS" in proc_runner.stdout
    assert "Passed Steps : 5 / 5" in proc_runner.stdout
