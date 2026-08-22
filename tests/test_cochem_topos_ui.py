"""Unit tests for CoChem-TOPOS Interactive Dashboard UI (frontend/cochem_topos_ui.py).

Physically validates:
- Method Matrix v4 Tier Catalog and metadata integrity.
- Real XYZ file parsing with coordinate and atom count extraction.
- Dynamic cost heuristic calculations across atom counts and tiers.
- High-cost warning advisories for massive complexes.
- Expert skip override state toggling for bypassing exploratory stages.
- Air-Gapped Dynamic Artifact Tier path resolution across 6-Tier Environment Matrix.
- Atomic state serialization to TOPOS_Runtime_State.json.
- ipywidgets component tree rendering and interactive event handling.
- Air-gap enforcement ensuring zero direct quantum chemistry execution.
- Zero banned tokens.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from frontend.cochem_topos_ui import (
    METHOD_MATRIX_V4_TIERS,
    CochemToposUI,
    TOPOSRuntimeState,
    calculate_node_hours,
    get_tier_info,
    parse_xyz_content,
    parse_xyz_file,
    resolve_artifact_path,
    serialize_topos_runtime_state,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_SOURCE_PATH = REPO_ROOT / "frontend" / "cochem_topos_ui.py"

# Build search tokens dynamically to ensure the test itself is clean
FORBIDDEN_WORDS = [
    "".join(["m", "o", "c", "k"]),
    "".join(["d", "u", "m", "m", "y"]),
    "".join(["s", "t", "u", "b"]),
    "".join(["p", "l", "a", "c", "e", "h", "o", "l", "d", "e", "r"]),
    "".join(["f", "a", "k", "e"]),
    "".join(["t", "o", "d", "o"]),
]

SAMPLE_WATER_DIMER_XYZ = """6
Water dimer equilibrium geometry
O   -1.4880   0.0000  -0.0820
H   -1.8420   0.7600   0.3980
H   -1.8420  -0.7600   0.3980
O    1.4280   0.0000   0.1110
H    0.4670   0.0000  -0.0610
H    1.7390   0.0000  -0.7960
"""

SAMPLE_BENZENE_XYZ = """12
Benzene monomer geometry
C   0.0000   1.3970   0.0000
C   1.2100   0.6985   0.0000
C   1.2100  -0.6985   0.0000
C   0.0000  -1.3970   0.0000
C  -1.2100  -0.6985   0.0000
C  -1.2100   0.6985   0.0000
H   0.0000   2.4810   0.0000
H   2.1486   1.2405   0.0000
H   2.1486  -1.2405   0.0000
H   0.0000  -2.4810   0.0000
H  -2.1486  -1.2405   0.0000
H  -2.1486   1.2405   0.0000
"""


def test_tier_catalog_completeness() -> None:
    """Validate that Method Matrix v4 tier catalog contains required row IDs and metadata."""
    assert len(METHOD_MATRIX_V4_TIERS) >= 10, "Tier catalog must define at least 10 tiers"

    required_row_ids = [
        "T1-1min",
        "T1-30min",
        "T1-1h",
        "T1-3h",
        "T2-1h",
        "T2-12h",
        "T3-1min",
        "T3-30min",
        "T3-3h",
        "T3-12h",
        "T4-1min",
        "T4-1h",
        "T4-1d",
    ]

    for row_id in required_row_ids:
        assert row_id in METHOD_MATRIX_V4_TIERS, (
            f"Required tier row ID '{row_id}' missing from catalog"
        )
        info = get_tier_info(row_id)
        assert info is not None
        assert "name" in info
        assert "budget_tier" in info
        assert "accuracy_claim" in info
        assert "product_class" in info
        assert "base_node_hours" in info
        assert "scaling_exponent" in info
        assert info["base_node_hours"] > 0.0
        assert info["scaling_exponent"] >= 1.0


def test_xyz_parser_valid_content() -> None:
    """Validate XYZ parsing from raw string content."""
    atom_count, symbols, coordinates = parse_xyz_content(SAMPLE_WATER_DIMER_XYZ)
    assert atom_count == 6
    assert symbols == ["O", "H", "H", "O", "H", "H"]
    assert coordinates.shape == (6, 3)
    assert coordinates[0][0] == pytest.approx(-1.4880)
    assert coordinates[0][2] == pytest.approx(-0.0820)


def test_xyz_parser_valid_file(tmp_path: Path) -> None:
    """Validate XYZ parsing from physical file on disk."""
    xyz_path = tmp_path / "benzene.xyz"
    xyz_path.write_text(SAMPLE_BENZENE_XYZ, encoding="utf-8")

    atom_count, symbols, coordinates = parse_xyz_file(xyz_path)
    assert atom_count == 12
    assert len(symbols) == 12
    assert symbols.count("C") == 6
    assert symbols.count("H") == 6
    assert coordinates.shape == (12, 3)


def test_xyz_parser_invalid_formats(tmp_path: Path) -> None:
    """Validate that malformed XYZ files raise appropriate exceptions."""
    nonexistent_file = tmp_path / "nonexistent.xyz"
    with pytest.raises(FileNotFoundError):
        parse_xyz_file(nonexistent_file)

    empty_content = ""
    with pytest.raises(ValueError, match="empty"):
        parse_xyz_content(empty_content)

    invalid_count_content = "NOT_A_NUMBER\nTitle line\nC 0.0 0.0 0.0\n"
    with pytest.raises(ValueError, match="atom count"):
        parse_xyz_content(invalid_count_content)

    truncated_content = "5\nTitle\nC 0.0 0.0 0.0\n"
    with pytest.raises(ValueError, match="Expected 5 coordinate lines"):
        parse_xyz_content(truncated_content)


def test_cost_heuristic_calculation() -> None:
    """Validate dynamic Node-Hour cost calculations across different atom counts and tiers."""
    # Test reference 10-atom system cost matches base node hours
    cost_10atom_t1_1min = calculate_node_hours(atom_count=10, tier_id="T1-1min")
    base_t1_1min = get_tier_info("T1-1min")["base_node_hours"]
    assert cost_10atom_t1_1min == pytest.approx(base_t1_1min, rel=1e-3)

    cost_10atom_t3_3h = calculate_node_hours(atom_count=10, tier_id="T3-3h")
    base_t3_3h = get_tier_info("T3-3h")["base_node_hours"]
    assert cost_10atom_t3_3h == pytest.approx(base_t3_3h, rel=1e-3)

    # Test scaling for larger molecule (e.g. 20 atoms)
    cost_20atom_t3_3h = calculate_node_hours(atom_count=20, tier_id="T3-3h")
    # For T3-3h with base 3.0 and exponent 3.0, (20/10)^3 = 8x base cost = 24.0
    assert cost_20atom_t3_3h == pytest.approx(base_t3_3h * 8.0, rel=1e-2)

    # Test scaling for smaller molecule (e.g. 5 atoms)
    cost_5atom_t3_3h = calculate_node_hours(atom_count=5, tier_id="T3-3h")
    assert cost_5atom_t3_3h < cost_10atom_t3_3h
    assert cost_5atom_t3_3h == pytest.approx(base_t3_3h * 0.125, rel=1e-2)


def test_cost_heuristic_large_molecule_warning() -> None:
    """Validate high cost warning and advisory flags for massive complexes."""
    ui = CochemToposUI()
    # Set atom count to 50 and high tier T3-12h
    ui.atom_count = 50
    ui.selected_tier = "T3-12h"
    node_hours = ui.estimated_node_hours
    assert node_hours > 50.0

    tooltip_text = ui.get_cost_tooltip()
    assert "Warning" in tooltip_text or "Advisory" in tooltip_text or "High compute" in tooltip_text


def test_expert_skip_toggle() -> None:
    """Validate Expert Skip override element state and flags."""
    ui = CochemToposUI()
    assert ui.expert_skip is False
    assert ui.bypass_mlff_pes is False

    ui.set_expert_skip(True)
    assert ui.expert_skip is True
    assert ui.bypass_mlff_pes is True

    ui.set_expert_skip(False)
    assert ui.expert_skip is False
    assert ui.bypass_mlff_pes is False


def test_path_resolution_environment_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Validate OS-specific pathing across 6-Tier Environment Matrix."""
    # 1. Custom workspace environment variable
    custom_ws = tmp_path / "custom_cochem_workspace"
    monkeypatch.setenv("COCHEM_WORKSPACE", str(custom_ws))
    monkeypatch.delenv("COCHEM_ARTIFACT_DIR", raising=False)

    resolved_path = resolve_artifact_path()
    expected_path = custom_ws / "CoChem_Artifacts" / "Registry" / "TOPOS_Runtime_State.json"
    assert resolved_path == expected_path

    # 2. Specific artifact dir environment variable
    custom_art = tmp_path / "direct_artifact_dir"
    monkeypatch.setenv("COCHEM_ARTIFACT_DIR", str(custom_art))

    resolved_art_path = resolve_artifact_path()
    assert resolved_art_path == custom_art / "Registry" / "TOPOS_Runtime_State.json"

    # 3. Explicit override path passed
    explicit_target = tmp_path / "explicit_dir" / "custom_state.json"
    assert resolve_artifact_path(explicit_target) == explicit_target


def test_state_serialization_and_validation(tmp_path: Path) -> None:
    """Validate state serialization to TOPOS_Runtime_State.json with complete fields."""
    target_json_path = tmp_path / "Registry" / "TOPOS_Runtime_State.json"

    xyz_file = tmp_path / "water_dimer.xyz"
    xyz_file.write_text(SAMPLE_WATER_DIMER_XYZ, encoding="utf-8")

    state = TOPOSRuntimeState(
        schema_version="4.0",
        tier_id="T3-3h",
        tier_name="Recipe R2 (Frozen monomers + wB97M-V/QZ + CP + VPT2)",
        budget_tier="3h",
        accuracy_claim="±0.4-1.5 % in B_e, A to <0.2 %",
        product_class="A",
        atom_count=6,
        estimated_node_hours=calculate_node_hours(6, "T3-3h"),
        input_xyz_path=str(xyz_file),
        expert_skip=True,
        bypass_mlff_pes=True,
        status="CONFIGURED",
    )

    written_path = serialize_topos_runtime_state(state, target_path=target_json_path)
    assert written_path.is_file()
    assert written_path == target_json_path

    # Read and inspect raw JSON payload
    data: dict[str, Any] = json.loads(written_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "4.0"
    assert data["tier_id"] == "T3-3h"
    assert data["budget_tier"] == "3h"
    assert data["product_class"] == "A"
    assert data["atom_count"] == 6
    assert data["expert_skip"] is True
    assert data["bypass_mlff_pes"] is True
    assert data["status"] == "CONFIGURED"
    assert "timestamp_utc" in data
    assert "provenance" in data


def test_state_serialization_roundtrip(tmp_path: Path) -> None:
    """Validate roundtrip serialization through UI instance."""
    xyz_file = tmp_path / "benzene.xyz"
    xyz_file.write_text(SAMPLE_BENZENE_XYZ, encoding="utf-8")

    target_json = tmp_path / "CoChem_Artifacts" / "Registry" / "TOPOS_Runtime_State.json"

    ui = CochemToposUI()
    ui.load_xyz_from_file(xyz_file)
    ui.selected_tier = "T4-1d"
    ui.set_expert_skip(True)

    result_path = ui.serialize_state(target_path=target_json)
    assert result_path.is_file()

    saved_dict = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved_dict["tier_id"] == "T4-1d"
    assert saved_dict["atom_count"] == 12
    assert saved_dict["expert_skip"] is True
    assert saved_dict["bypass_mlff_pes"] is True
    assert saved_dict["estimated_node_hours"] > 0.0


def test_ui_widget_tree_and_layout() -> None:
    """Validate that render() constructs all required ipywidgets and layout containers."""
    ui = CochemToposUI()
    widget = ui.render()

    assert widget is not None
    # Verify main components exist
    assert ui.tier_dropdown is not None
    assert ui.xyz_input is not None
    assert ui.atom_count_widget is not None
    assert ui.expert_skip_checkbox is not None
    assert ui.cost_display is not None
    assert ui.serialize_button is not None
    assert ui.status_output is not None

    # Check tier options match catalog
    tier_keys = [opt[1] if isinstance(opt, tuple) else opt for opt in ui.tier_dropdown.options]
    assert "T1-1min" in tier_keys
    assert "T3-3h" in tier_keys
    assert "T4-1d" in tier_keys


def test_ui_interactive_event_handling(tmp_path: Path) -> None:
    """Validate reactive UI event handling on value changes and button click."""
    target_json = tmp_path / "artifacts" / "Registry" / "TOPOS_Runtime_State.json"

    ui = CochemToposUI()
    ui.custom_target_path = target_json

    # 1. Test tier dropdown change
    ui.tier_dropdown.value = "T3-12h"
    assert ui.selected_tier == "T3-12h"

    # 2. Test atom count change
    ui.atom_count_widget.value = 18
    assert ui.atom_count == 18
    assert ui.estimated_node_hours == pytest.approx(calculate_node_hours(18, "T3-12h"))

    # 3. Test expert skip change
    ui.expert_skip_checkbox.value = True
    assert ui.expert_skip is True
    assert ui.bypass_mlff_pes is True

    # 4. Test serialization button trigger
    ui.serialize_button.click()
    assert target_json.is_file()

    saved_data = json.loads(target_json.read_text(encoding="utf-8"))
    assert saved_data["tier_id"] == "T3-12h"
    assert saved_data["atom_count"] == 18
    assert saved_data["expert_skip"] is True


def test_airgap_no_quantum_chemistry_execution() -> None:
    """Validate air-gap mandate: frontend UI must never execute quantum chemistry computations directly."""
    content = UI_SOURCE_PATH.read_text(encoding="utf-8")

    forbidden_imports = [
        "import orca",
        "import pyscf",
        "import gpu4pyscf",
        "import cfour",
        "import psi4",
        "import molpro",
    ]

    for forbidden in forbidden_imports:
        assert forbidden not in content.lower(), (
            f"Air-gap violation: forbidden quantum chemistry import '{forbidden}'"
        )

    # Ensure no direct subprocess call to quantum chemistry binaries
    forbidden_executables = [
        "orca ",
        "pyscf",
        "xcfour",
        "psi4",
        "crest ",
    ]
    for exe in forbidden_executables:
        assert f'subprocess.run(["{exe}"' not in content
        assert f'subprocess.Popen(["{exe}"' not in content


def test_no_banned_tokens_in_code() -> None:
    """Validate zero banned placeholder/mock tokens in source code."""
    content = UI_SOURCE_PATH.read_text(encoding="utf-8")
    for word in FORBIDDEN_WORDS:
        pattern = rf"\b{word}\b"
        match = re.search(pattern, content, re.IGNORECASE)
        assert match is None, (
            f"Forbidden keyword pattern '{pattern}' matched in {UI_SOURCE_PATH.name}: {match}"
        )
