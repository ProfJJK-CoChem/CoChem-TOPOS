"""Interactive Dashboard UI module for the CoChem-TOPOS pipeline (cochem_topos_ui.py).

Acts as the human-in-the-loop interaction point for the CoChem-TOPOS pipeline.
Translates human intent into a serialized machine state (TOPOS_Runtime_State.json)
without exposing underlying quantum mechanics Python code or running direct calculations.

Execution Directives:
1. Time-Aware Capability Selector: ipywidgets graphical interface with Method Matrix v4 row IDs.
2. Cost Heuristic Tooltips: Dynamically calculates estimated Node-Hour costs based on atom count.
3. Expert Skip Toggle: Boolean override to bypass early MLFF/PES exploratory stages.
4. Air-Gapped State Serialization: Validates selections and writes TOPOS_Runtime_State.json securely.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import ipywidgets as widgets  # type: ignore[import-untyped]
import numpy as np

# Method Matrix v4 Tier Catalog
METHOD_MATRIX_V4_TIERS: dict[str, dict[str, Any]] = {
    "T1-10s": {
        "name": "Topology Screen (Hand-Enumerated + GFN2-xTB)",
        "table": "Table 1 (Search)",
        "budget_tier": "10s",
        "accuracy_claim": "Topology screen only, no quantitative window [M]",
        "product_class": "A",
        "engine": "xtb",
        "concurrency": "C",
        "base_node_hours": 0.0028,
        "scaling_exponent": 2.0,
        "description": "Rapid initial binding topology screening and seed minimization.",
    },
    "T1-1min": {
        "name": "GOAT Exploration (GFN2-xTB / GFN-FF)",
        "table": "Table 1 (Search)",
        "budget_tier": "1min",
        "accuracy_claim": "±1-5 % in B_e [M]",
        "product_class": "A",
        "engine": "ORCA",
        "concurrency": "C",
        "base_node_hours": 0.0167,
        "scaling_exponent": 2.0,
        "description": "Fast stochastic uphill conformer enumeration at semi-empirical level.",
    },
    "T1-30min": {
        "name": "MLFF Exploratory Search (AIMNet2 / ExtOpt)",
        "table": "Table 1 (Search)",
        "budget_tier": "30min",
        "accuracy_claim": "Free-topology enumeration, Stage A deduplication [M]",
        "product_class": "A",
        "engine": "ORCA + AIMNet2",
        "concurrency": "G",
        "base_node_hours": 0.50,
        "scaling_exponent": 2.0,
        "description": "GPU-accelerated exploratory conformer search using machine-learned potential.",
    },
    "T1-1h": {
        "name": "CREST NCI Cross-Check & Union",
        "table": "Table 1 (Search)",
        "budget_tier": "1h",
        "accuracy_claim": "Independent second ensemble union [M]",
        "product_class": "A",
        "engine": "CREST",
        "concurrency": "C",
        "base_node_hours": 1.00,
        "scaling_exponent": 2.0,
        "description": "Independent non-covalent conformer search cross-check via CREST NCI.",
    },
    "T1-3h": {
        "name": "Union Refinement (CREST + ORCA r²SCAN-3c)",
        "table": "Table 1 (Search)",
        "budget_tier": "3h",
        "accuracy_claim": "Stage B deduplication, ±1-3 kcal/mol [E]",
        "product_class": "A",
        "engine": "ORCA + CREST",
        "concurrency": "P",
        "base_node_hours": 3.00,
        "scaling_exponent": 2.5,
        "description": "QM-level union screening and spectroscopic deduplication.",
    },
    "T2-1h": {
        "name": "2-D Relaxed PES Grid (ωB97X-V/def2-TZVPP)",
        "table": "Table 2 (PES)",
        "budget_tier": "1h",
        "accuracy_claim": "2-D surface, ±1-2 kcal/mol [E]",
        "product_class": "A",
        "engine": "ORCA",
        "concurrency": "P",
        "base_node_hours": 1.00,
        "scaling_exponent": 3.0,
        "description": "Concurrent relaxed 2-D potential energy surface scan.",
    },
    "T2-12h": {
        "name": "Active Learning Δ-PES (DFT/PIP + CCSD(T)-F12)",
        "table": "Table 2 (PES)",
        "budget_tier": "12h",
        "accuracy_claim": "Fitted surface, RMS 3-10 cm⁻¹ [E]",
        "product_class": "A",
        "engine": "ORCA + MOLPIPx",
        "concurrency": "P",
        "base_node_hours": 12.00,
        "scaling_exponent": 3.5,
        "description": "Active learning Delta-machine-learning potential surface generation.",
    },
    "T3-1min": {
        "name": "Recipe R1: Frozen Monomers + r²SCAN-3c Intermolecular",
        "table": "Table 3 (Geometry)",
        "budget_tier": "1min",
        "accuracy_claim": "B_e ±1-3 %, A to <0.2 % [D]",
        "product_class": "A",
        "engine": "ORCA",
        "concurrency": "C",
        "base_node_hours": 0.0167,
        "scaling_exponent": 2.5,
        "description": "Cheapest defensible complex geometry; frozen high-level monomer frameworks.",
    },
    "T3-30min": {
        "name": "ωB97X-V/def2-TZVPP Full Optimization",
        "table": "Table 3 (Geometry)",
        "budget_tier": "30min",
        "accuracy_claim": "B_e ±0.5-3 % [E]",
        "product_class": "A",
        "engine": "ORCA",
        "concurrency": "P",
        "base_node_hours": 0.50,
        "scaling_exponent": 3.0,
        "description": "Full DFT geometry optimization at triple-zeta basis.",
    },
    "T3-1h": {
        "name": "ωB97X-V/jun-cc-pVTZ Diffuse Optimization",
        "table": "Table 3 (Geometry)",
        "budget_tier": "1h",
        "accuracy_claim": "B_e ±0.5-2 % [E]",
        "product_class": "A",
        "engine": "ORCA",
        "concurrency": "P",
        "base_node_hours": 1.00,
        "scaling_exponent": 3.0,
        "description": "DFT optimization with diffuse calendar basis functions on all centers.",
    },
    "T3-3h": {
        "name": "Recipe R2: Frozen Monomers + ωB97M-V/QZ + 3-Leg CP + VPT2",
        "table": "Table 3 (Geometry)",
        "budget_tier": "3h",
        "accuracy_claim": "±0.4-1.5 % in B_e, A to <0.2 %, ΔB_vib included [E]",
        "product_class": "A",
        "engine": "ORCA",
        "concurrency": "P",
        "base_node_hours": 3.00,
        "scaling_exponent": 3.0,
        "description": "Best de novo accuracy-per-core-hour protocol with frozen monomers and CP.",
    },
    "T3-12h": {
        "name": "Recipe R4: junChS CBS+CV Composite Geometry",
        "table": "Table 3 (Geometry)",
        "budget_tier": "12h",
        "accuracy_claim": "B_e MAE 0.13 % for ≤16 atoms [M]",
        "product_class": "A",
        "engine": "ORCA compound scripts / CFOUR",
        "concurrency": "C",
        "base_node_hours": 12.00,
        "scaling_exponent": 4.0,
        "description": "Published 0.1% accuracy workhorse composite scheme.",
    },
    "T4-1min": {
        "name": "Semi-Experimental Parent Scaling (Product B)",
        "table": "Table 4 (Vibrational)",
        "budget_tier": "1min",
        "accuracy_claim": "B₀ 0.03-0.1 % [M]",
        "product_class": "B",
        "engine": "Kisiel structural suite",
        "concurrency": "C",
        "base_node_hours": 0.0167,
        "scaling_exponent": 1.0,
        "description": "Scale trial geometry to reproduce experimental parent constants.",
    },
    "T4-1h": {
        "name": "ωB97X-V/def2-TZVPP DFT VPT2",
        "table": "Table 4 (Vibrational)",
        "budget_tier": "1h",
        "accuracy_claim": "ΔB_vib ±0.05-0.1 % of B₀, quartic distortion free [E]",
        "product_class": "A",
        "engine": "ORCA",
        "concurrency": "S",
        "base_node_hours": 1.00,
        "scaling_exponent": 3.0,
        "description": "Anharmonic VPT2 force field yielding vibrational corrections and centrifugal distortion.",
    },
    "T4-1d": {
        "name": "Production Anharmonic VPT2 (Semi-Rigid Manifold)",
        "table": "Table 4 (Vibrational)",
        "budget_tier": "1d",
        "accuracy_claim": "B₀ 0.3-0.5 % semi-rigid, 1-2 % floppy [D]",
        "product_class": "A",
        "engine": "ORCA / CFOUR",
        "concurrency": "S",
        "base_node_hours": 24.00,
        "scaling_exponent": 3.5,
        "description": "High-level semi-rigid manifold vibrational corrections and B₀ prediction.",
    },
    "T3C-3d": {
        "name": "CFOUR Analytic CCSD(T) Anharmonic Force Field",
        "table": "Table 3-C / 8-C (CFOUR)",
        "budget_tier": "3d",
        "accuracy_claim": "B_e MAE 0.13 % [M], sextic distortion enabled",
        "product_class": "A",
        "engine": "CFOUR",
        "concurrency": "S",
        "base_node_hours": 72.00,
        "scaling_exponent": 4.5,
        "description": "Exact analytic second derivatives at coupled-cluster level.",
    },
    "T4C-1mo": {
        "name": "CFOUR Complete Sextic + Isotopologue Campaign",
        "table": "Table 4-C / 8-C (CFOUR)",
        "budget_tier": "1mo",
        "accuracy_claim": "B₀ 0.04 % semi-rigid [M], full closed set",
        "product_class": "A",
        "engine": "CFOUR",
        "concurrency": "S",
        "base_node_hours": 720.00,
        "scaling_exponent": 5.0,
        "description": "Reference multi-isotopologue coupled-cluster force field campaign.",
    },
}


@dataclass
class TOPOSRuntimeState:
    """Air-Gapped runtime state payload for CoChem-TOPOS execution."""

    schema_version: str = "4.0"
    tier_id: str = "T3-3h"
    tier_name: str = "Recipe R2 (Frozen monomers + wB97M-V/QZ + CP + VPT2)"
    budget_tier: str = "3h"
    accuracy_claim: str = "±0.4-1.5 % in B_e, A to <0.2 %"
    product_class: str = "A"
    atom_count: int = 10
    estimated_node_hours: float = 3.00
    input_xyz_path: str | None = None
    expert_skip: bool = False
    bypass_mlff_pes: bool = False
    status: str = "CONFIGURED"
    timestamp_utc: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    provenance: dict[str, Any] = field(
        default_factory=lambda: {
            "creator": "CoChem-TOPOS UI",
            "host_os": platform.system(),
            "python_version": platform.python_version(),
        }
    )


def get_tier_info(tier_id: str) -> dict[str, Any]:
    """Retrieve metadata for a specified Method Matrix v4 tier ID."""
    if tier_id not in METHOD_MATRIX_V4_TIERS:
        raise KeyError(f"Tier ID '{tier_id}' is not recognized in Method Matrix v4.")
    return METHOD_MATRIX_V4_TIERS[tier_id]


def calculate_node_hours(atom_count: int, tier_id: str) -> float:
    """Calculate estimated Node-Hours based on atom count and Method Matrix v4 tier scaling."""
    info = get_tier_info(tier_id)
    base_hours = float(info.get("base_node_hours", 1.0))
    exponent = float(info.get("scaling_exponent", 3.0))

    clamped_atoms = max(1, int(atom_count))
    reference_atoms = 10.0

    scaling_factor = (clamped_atoms / reference_atoms) ** exponent
    calculated_hours = base_hours * scaling_factor
    return round(float(calculated_hours), 4)


def parse_xyz_content(content: str) -> tuple[int, list[str], np.ndarray]:
    """Parse raw XYZ content string into atom count, element symbols, and Cartesian coordinates."""
    stripped = content.strip()
    if not stripped:
        raise ValueError("XYZ content is empty.")

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(lines) < 3:
        raise ValueError(
            "Malformed XYZ content: requires at least 3 lines (count, title, coordinates)."
        )

    try:
        atom_count = int(lines[0].split()[0])
    except (ValueError, IndexError) as err:
        raise ValueError(f"Invalid atom count in first line of XYZ: {lines[0]}") from err

    coord_lines = lines[2:]
    if len(coord_lines) < atom_count:
        raise ValueError(
            f"Expected {atom_count} coordinate lines in XYZ, but found {len(coord_lines)}."
        )

    symbols: list[str] = []
    coords_list: list[list[float]] = []

    for i in range(atom_count):
        parts = coord_lines[i].split()
        if len(parts) < 4:
            raise ValueError(f"Malformed coordinate line {i + 1}: '{coord_lines[i]}'")
        symbol = parts[0]
        try:
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
        except ValueError as err:
            raise ValueError(
                f"Invalid coordinate float value on line {i + 1}: '{coord_lines[i]}'"
            ) from err

        symbols.append(symbol)
        coords_list.append([x, y, z])

    coords_array = np.array(coords_list, dtype=np.float64)
    return atom_count, symbols, coords_array


def parse_xyz_file(file_path: Path | str) -> tuple[int, list[str], np.ndarray]:
    """Parse an XYZ file from disk into atom count, symbols, and coordinates."""
    path_obj = Path(file_path)
    if not path_obj.is_file():
        raise FileNotFoundError(f"XYZ file not found at: {path_obj}")

    text = path_obj.read_text(encoding="utf-8")
    return parse_xyz_content(text)


def resolve_artifact_path(explicit_path: Path | str | None = None) -> Path:
    """Resolve OS-specific Dynamic Artifact Tier path compatible with the 6-Tier Environment Matrix."""
    if explicit_path is not None:
        target = Path(explicit_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    cochem_artifact_dir = os.environ.get("COCHEM_ARTIFACT_DIR")
    if cochem_artifact_dir:
        base_dir = Path(cochem_artifact_dir)
        target = base_dir / "Registry" / "TOPOS_Runtime_State.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    cochem_workspace = os.environ.get("COCHEM_WORKSPACE")
    if cochem_workspace:
        base_dir = Path(cochem_workspace) / "CoChem_Artifacts" / "Registry"
        target = base_dir / "TOPOS_Runtime_State.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    # Fallback to user home directory
    fallback_dir = Path.home() / ".cochem_artifacts" / "Registry"
    target = fallback_dir / "TOPOS_Runtime_State.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def serialize_topos_runtime_state(
    state: TOPOSRuntimeState, target_path: Path | str | None = None
) -> Path:
    """Atomically serialize validated runtime state to TOPOS_Runtime_State.json."""
    resolved_target = resolve_artifact_path(target_path)
    resolved_target.parent.mkdir(parents=True, exist_ok=True)

    state_dict = asdict(state)

    # Validate state attributes
    if state.atom_count < 1:
        raise ValueError(f"Invalid atom count in state: {state.atom_count}")
    if state.tier_id not in METHOD_MATRIX_V4_TIERS:
        raise ValueError(f"Unrecognized tier ID: {state.tier_id}")
    if state.product_class not in {"A", "B", "C"}:
        raise ValueError(f"Invalid product class '{state.product_class}'. Expected 'A', 'B', or 'C'.")

    # Write atomically via tempfile to prevent partial writes
    temp_dir = resolved_target.parent
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(temp_dir),
        delete=False,
        suffix=".tmp",
    ) as tmp_file:
        json.dump(state_dict, tmp_file, indent=2)
        temp_path = Path(tmp_file.name)

    temp_path.replace(resolved_target)
    return resolved_target


class CochemToposUI:
    """Interactive ipywidgets Control Panel Dashboard for CoChem-TOPOS."""

    def __init__(self) -> None:
        self.selected_tier: str = "T3-3h"
        self.product_class: str = "A"
        self.atom_count: int = 10
        self.input_xyz_path: str | None = None
        self.expert_skip: bool = False
        self.bypass_mlff_pes: bool = False
        self.custom_target_path: Path | None = None

        # Build widget components
        self._init_widgets()
        self._bind_events()
        self._update_cost_display()

    @property
    def estimated_node_hours(self) -> float:
        """Dynamically calculated Node-Hour estimate."""
        return calculate_node_hours(self.atom_count, self.selected_tier)

    def set_expert_skip(self, value: bool) -> None:
        """Update Expert Skip override state."""
        self.expert_skip = bool(value)
        self.bypass_mlff_pes = bool(value)
        if hasattr(self, "expert_skip_checkbox"):
            self.expert_skip_checkbox.value = bool(value)

    def get_cost_tooltip(self) -> str:
        """Generate descriptive tooltip and advisory text for cost heuristic."""
        hours = self.estimated_node_hours
        tier_info = get_tier_info(self.selected_tier)
        base = tier_info["base_node_hours"]
        exp = tier_info["scaling_exponent"]

        if self.atom_count > 30 and hours > 50.0:
            return (
                f"⚠️ High compute advisory: {hours:.2f} Node-Hours estimated for {self.atom_count} atoms "
                f"at {self.selected_tier} (Scaling: (N/10)^{exp}). Consider screening at lower tier."
            )
        if hours > 100.0:
            return (
                f"⚠️ Warning: Extremely large job ({hours:.2f} Node-Hours). "
                f"Base: {base}h, Scaling exponent: {exp}."
            )
        return (
            f"Cost Heuristic: {hours:.3f} Node-Hours estimated ({self.atom_count} atoms, "
            f"Tier: {self.selected_tier}, Base: {base}h, Exp: {exp})."
        )

    def _init_widgets(self) -> None:
        """Initialize all ipywidgets controls."""
        tier_options = [
            (
                f"[{tier_id}] {info['budget_tier']} - {info['name']} ({info['accuracy_claim']})",
                tier_id,
            )
            for tier_id, info in METHOD_MATRIX_V4_TIERS.items()
        ]

        self.title_banner = widgets.HTML(
            value="<h3 style='margin-bottom: 2px;'>🔬 CoChem-TOPOS Interactive Dashboard</h3>"
            "<p style='color: #555; margin-top: 0;'>Method Matrix v4 Human-in-the-Loop State Configurator</p>"
        )

        self.tier_dropdown = widgets.Dropdown(
            options=tier_options,
            value=self.selected_tier,
            description="Target Tier:",
            style={"description_width": "120px"},
            layout=widgets.Layout(width="98%"),
        )

        self.product_class_radio = widgets.RadioButtons(
            options=[
                ("Product A: Absolute de novo (0.3-0.5% rigid, 1-2% floppy)", "A"),
                ("Product B: Semi-experimental parent anchored (0.03-0.06%)", "B"),
                ("Product C: Differences / Isotopologues (0.02-0.1%)", "C"),
            ],
            value=self.product_class,
            description="Product:",
            style={"description_width": "120px"},
            layout=widgets.Layout(width="98%"),
        )

        self.xyz_input = widgets.Text(
            value="",
            description="Input XYZ:",
            tooltip="Path to input .xyz coordinate file",
            style={"description_width": "120px"},
            layout=widgets.Layout(width="70%"),
        )

        self.xyz_upload = widgets.FileUpload(
            accept=".xyz",
            multiple=False,
            description="Upload .xyz",
            layout=widgets.Layout(width="25%"),
        )

        self.atom_count_widget = widgets.BoundedIntText(
            value=self.atom_count,
            min=1,
            max=100000,
            description="Atom Count (N):",
            style={"description_width": "120px"},
            layout=widgets.Layout(width="250px"),
        )

        self.expert_skip_checkbox = widgets.Checkbox(
            value=self.expert_skip,
            description="Expert Skip: Bypass early MLFF/PES exploratory stages (Provide optimized conformers)",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="98%"),
        )

        self.cost_display = widgets.HTML(
            value="",
            layout=widgets.Layout(width="98%", margin="10px 0px"),
        )

        self.serialize_button = widgets.Button(
            description="💾 Serialize State to TOPOS_Runtime_State.json",
            button_style="success",
            icon="save",
            layout=widgets.Layout(width="400px", height="38px", margin="10px 0px"),
        )

        self.status_output = widgets.Output(
            layout=widgets.Layout(width="98%", border="1px solid #ddd", padding="8px")
        )

    def _bind_events(self) -> None:
        """Bind interactive event handlers to UI widgets."""
        self.tier_dropdown.observe(self._on_tier_change, names="value")
        self.product_class_radio.observe(self._on_product_class_change, names="value")
        self.atom_count_widget.observe(self._on_atom_count_change, names="value")
        self.xyz_input.observe(self._on_xyz_path_change, names="value")
        self.xyz_upload.observe(self._on_xyz_upload, names="value")
        self.expert_skip_checkbox.observe(self._on_expert_skip_change, names="value")
        self.serialize_button.on_click(self._on_serialize_clicked)

    def _on_tier_change(self, change: dict[str, Any]) -> None:
        """Handle target tier selection change."""
        self.selected_tier = str(change["new"])
        tier_info = get_tier_info(self.selected_tier)
        # Update product class default if recommended
        recommended_prod = tier_info.get("product_class", "A")
        if recommended_prod in ["A", "B", "C"] and self.product_class != recommended_prod:
            self.product_class = recommended_prod
            self.product_class_radio.value = recommended_prod
        self._update_cost_display()

    def _on_product_class_change(self, change: dict[str, Any]) -> None:
        """Handle product class radio change."""
        self.product_class = str(change["new"])
        self._update_cost_display()

    def _on_atom_count_change(self, change: dict[str, Any]) -> None:
        """Handle atom count value change."""
        val = int(change["new"])
        if val > 0:
            self.atom_count = val
            self._update_cost_display()

    def _on_xyz_path_change(self, change: dict[str, Any]) -> None:
        """Handle manual XYZ path string input."""
        path_str = str(change["new"]).strip()
        if path_str:
            self.input_xyz_path = path_str
            path_obj = Path(path_str)
            if path_obj.is_file():
                try:
                    count, _, _ = parse_xyz_file(path_obj)
                    self.atom_count = count
                    self.atom_count_widget.value = count
                    self._update_cost_display()
                except Exception as err:
                    with self.status_output:
                        self.status_output.clear_output()
                        print(f"⚠️ XYZ path parse warning: {err}")

    def _on_xyz_upload(self, change: dict[str, Any]) -> None:
        """Handle direct XYZ file upload."""
        upload_data = change["new"]
        if upload_data:
            first_item = (
                upload_data[0] if isinstance(upload_data, list) else list(upload_data.values())[0]
            )
            content_bytes = first_item.get("content", b"")
            if isinstance(content_bytes, memoryview):
                content_bytes = content_bytes.tobytes()
            content_str = content_bytes.decode("utf-8", errors="ignore")
            try:
                count, _, _ = parse_xyz_content(content_str)
                self.atom_count = count
                self.atom_count_widget.value = count
                filename = first_item.get("name", "uploaded.xyz")
                self.xyz_input.value = filename
                self.input_xyz_path = filename
                self._update_cost_display()
            except Exception as err:
                with self.status_output:
                    self.status_output.clear_output()
                    print(f"❌ Upload parsing error: {err}")

    def _on_expert_skip_change(self, change: dict[str, Any]) -> None:
        """Handle Expert Skip checkbox change."""
        self.set_expert_skip(bool(change["new"]))
        self._update_cost_display()

    def _update_cost_display(self) -> None:
        """Update HTML cost display and tooltips."""
        hours = self.estimated_node_hours
        tier_info = get_tier_info(self.selected_tier)
        tooltip = self.get_cost_tooltip()

        warning_style = ""
        badge_color = "#28a745"
        if hours > 10.0:
            badge_color = "#ffc107"
            warning_style = "border-left: 4px solid #ffc107; background: #fffdf0;"
        if hours > 50.0:
            badge_color = "#dc3545"
            warning_style = "border-left: 4px solid #dc3545; background: #fff5f5;"

        skip_badge = (
            "<span style='background:#17a2b8; color:white; padding:2px 6px; border-radius:3px;'>Expert Skip: ON</span>"
            if self.expert_skip
            else ""
        )

        html_content = f"""
        <div style='padding: 10px; border: 1px solid #ddd; border-radius: 4px; {warning_style}' title='{tooltip}'>
            <strong>Cost Heuristic Estimate:</strong>
            <span style='font-size: 1.2em; font-weight: bold; color: {badge_color};'>{hours:.3f} Node-Hours</span>
            &nbsp;|&nbsp; <strong>Tier:</strong> <code>{self.selected_tier}</code> ({tier_info["budget_tier"]})
            &nbsp;|&nbsp; <strong>Atoms (N):</strong> <code>{self.atom_count}</code>
            &nbsp;|&nbsp; <strong>Accuracy:</strong> {tier_info["accuracy_claim"]}
            &nbsp;{skip_badge}
            <br><small style='color: #666;'>{tooltip}</small>
        </div>
        """
        self.cost_display.value = html_content

    def _on_serialize_clicked(self, _btn: widgets.Button) -> None:
        """Handle serialize button click event."""
        with self.status_output:
            self.status_output.clear_output()
            try:
                state_path = self.serialize_state()
                print(f"✅ Successfully serialized state to: {state_path}")
                print(f"   Tier: {self.selected_tier} | Atom Count: {self.atom_count}")
                print(f"   Estimated Node-Hours: {self.estimated_node_hours:.4f}")
                print(
                    f"   Expert Skip: {self.expert_skip} (Bypass MLFF/PES: {self.bypass_mlff_pes})"
                )
            except Exception as err:
                print(f"❌ Serialization error: {err}")

    def load_xyz_from_file(self, file_path: Path | str) -> None:
        """Programmatically load an XYZ file and update state."""
        path_obj = Path(file_path)
        count, _, _ = parse_xyz_file(path_obj)
        self.input_xyz_path = str(path_obj)
        self.atom_count = count
        self.atom_count_widget.value = count
        self.xyz_input.value = str(path_obj)
        self._update_cost_display()

    def serialize_state(self, target_path: Path | str | None = None) -> Path:
        """Construct and serialize current state to TOPOS_Runtime_State.json."""
        effective_path = target_path or self.custom_target_path
        tier_info = get_tier_info(self.selected_tier)

        state = TOPOSRuntimeState(
            schema_version="4.0",
            tier_id=self.selected_tier,
            tier_name=tier_info["name"],
            budget_tier=tier_info["budget_tier"],
            accuracy_claim=tier_info["accuracy_claim"],
            product_class=self.product_class,
            atom_count=self.atom_count,
            estimated_node_hours=self.estimated_node_hours,
            input_xyz_path=self.input_xyz_path,
            expert_skip=self.expert_skip,
            bypass_mlff_pes=self.bypass_mlff_pes,
            status="CONFIGURED",
        )

        return serialize_topos_runtime_state(state, target_path=effective_path)

    def render(self) -> widgets.VBox:
        """Return the complete composite ipywidgets layout container."""
        xyz_box = widgets.HBox(
            [self.xyz_input, self.xyz_upload],
            layout=widgets.Layout(width="98%"),
        )

        controls_box = widgets.VBox(
            [
                self.title_banner,
                self.tier_dropdown,
                self.product_class_radio,
                xyz_box,
                self.atom_count_widget,
                self.expert_skip_checkbox,
                self.cost_display,
                self.serialize_button,
                self.status_output,
            ],
            layout=widgets.Layout(padding="12px", border="1px solid #ccc", border_radius="6px"),
        )
        return controls_box


def create_topos_dashboard() -> CochemToposUI:
    """Factory helper to construct and return a new CochemToposUI instance."""
    return CochemToposUI()


if __name__ == "__main__":
    ui = create_topos_dashboard()
    print("CoChem-TOPOS UI Initialized successfully.")
    print(f"Default Tier: {ui.selected_tier}, Estimated Node-Hours: {ui.estimated_node_hours}")
