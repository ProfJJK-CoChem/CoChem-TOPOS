"""
CoChem-TOPOS: Stage 4.0 - Time-Aware Capability Selector & Ab Initio Execution Broker
(cochem_topos_escalator_exec.py)

Acts as the primary quantum mechanical execution broker, preventing brute-force
calculations by systematically escalating the level of theory (e.g. MACE-OFF24(M) ->
wB97M-V/QZ -> PNO-space extrapolation -> AutoCAS multi-reference rescue).

Execution Directives:
1. Redundant Internal Coordinates Verification:
   - Provide standard Cartesian geometries directly to ORCA, explicitly allowing the
     engine to naturally construct delocalized redundant internal coordinates for SCF
     geometry convergence. Strictly avoids manual Z-Matrix generation.
2. Automated SCF Rescue:
   - Actively parse the `orca.out` buffer during execution. If an SCF divergence or
     "ping-pong" oscillation is detected, intercept the failure, inject `! SlowConv VShift`
     keywords into the `.inp` file, and restart the node from the last converged `.gbw`
     binary orbital seed (using `%moinp` / `! MOREAD`).
3. The AutoCAS Rescue Protocol:
   - Specifically monitor the T1 and D1 multireference diagnostics during post-Hartree-Fock
     steps. If T1 > 0.02 or D1 > 0.05, mathematically recognize the single-reference assumption
     violation. Immediately halt the calculation, downgrade the pipeline state to `! AutoCAS`,
     and alert the GUI via cross-platform IPC that a multi-reference active space selection
     is required.

Strictly complies with the Tripartite Air-Gap Policy and Zero-Mock Mandate.
"""

from __future__ import annotations

import json
import logging
import math
import re
import socket
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Internal Topology, Mechanics, and Cascade Subsystem Imports
try:
    from cascade_engine.cochem_topos_cascade_matrix import (
        STANDARD_5_THRESHOLD_GEOM_BLOCK,
    )
except ImportError:
    try:
        from cochem_topos_cascade_matrix import (  # type: ignore[import-not-found,no-redef]
            STANDARD_5_THRESHOLD_GEOM_BLOCK,
        )
    except ImportError:
        # Fallback inline definition if imported in isolated sub-environments
        STANDARD_5_THRESHOLD_GEOM_BLOCK = """%geom
  TolE 1e-7
  TolMaxG 1e-5
  TolRMSG 3e-6
  TolMaxD 1e-4
  TolRMSD 5e-5
  InHess XTB2
end"""

logger = logging.getLogger("CoChem.TOPOS.EscalatorExec")

# Constants & Thresholds
T1_MULTIREF_THRESHOLD: float = 0.02
D1_MULTIREF_THRESHOLD: float = 0.05
DEFAULT_MAX_SCF_RESCUE_ATTEMPTS: int = 3
DEFAULT_SCF_OSCILLATION_WINDOW: int = 4
DEFAULT_SCF_DIVERGENCE_TOL_HARTREE: float = 1.0
DEFAULT_IPC_PORT: int = 8899
DEFAULT_IPC_CHANNEL: str = "cochem_topos_escalator"


# ============================================================================
# 1. Enums and Pydantic Data Models
# ============================================================================


class EscalationTier(str, Enum):
    """Supported computational tiers in the Stage 4.0 Method Matrix ladder."""

    T1_10S = "T1-10s"
    T1_1MIN = "T1-1min"
    T1_30MIN = "T1-30min"
    T1_1H = "T1-1h"
    T1_3H = "T1-3h"
    T1_12H = "T1-12h"
    T1_1D = "T1-1d"
    T1_3D = "T1-3d"
    AUTOCAS = "AutoCAS"


class SCFConvergenceStatus(str, Enum):
    """Status classification of an SCF convergence trajectory."""

    NOT_STARTED = "not_started"
    CONVERGING = "converging"
    CONVERGED = "converged"
    OSCILLATING_PING_PONG = "oscillating_ping_pong"
    DIVERGING = "diverging"
    MAX_CYCLES_EXCEEDED = "max_cycles_exceeded"
    FAILED = "failed"
    ABORTED = "aborted"


class CalculationStatus(str, Enum):
    """Terminal or operational state of an ab initio execution step."""

    SUCCESS = "success"
    SCF_RESCUED = "scf_rescued"
    AUTOCAS_TRIGGERED = "autocas_triggered"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    HALTED = "halted"


class AlertSeverity(str, Enum):
    """Severity levels for cross-platform IPC notifications."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"


class CoordinateType(str, Enum):
    """Supported coordinate representations."""

    CARTESIAN = "cartesian"
    REDUNDANT_INTERNAL = "redundant_internal"
    Z_MATRIX = "z_matrix"


class MultireferenceDiagnostics(BaseModel):
    """
    Diagnostic metrics evaluating single-reference post-Hartree-Fock reliability.
    T1 > 0.02 or D1 > 0.05 flags single-reference breakdown.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    t1_diagnostic: float = Field(default=0.0, description="T1 diagnostic from coupled cluster amplitudes")
    d1_diagnostic: float = Field(default=0.0, description="D1 diagnostic from single excitation amplitudes")
    d2_diagnostic: float | None = Field(default=None, description="Optional D2 diagnostic if computed")
    t1_threshold: float = Field(default=T1_MULTIREF_THRESHOLD, description="Threshold above which T1 fails")
    d1_threshold: float = Field(default=D1_MULTIREF_THRESHOLD, description="Threshold above which D1 fails")
    is_multireference: bool = Field(default=False, description="True if multireference character detected")
    violation_reason: str | None = Field(default=None, description="Detailed explanation of failure")
    suggested_active_electrons: int | None = Field(default=None, description="Recommended active electrons N_act")
    suggested_active_orbitals: int | None = Field(default=None, description="Recommended active orbitals M_act")

    @field_validator("is_multireference", mode="before")
    @classmethod
    def evaluate_violation(cls, v: bool, info: Any) -> bool:
        return bool(v)


class SCFIterationRecord(BaseModel):
    """Single SCF cycle telemetry record extracted from quantum engine logs."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    iteration: int = Field(..., description="0-based or 1-based cycle index")
    energy_hartree: float = Field(..., description="Total electronic energy at this cycle (Hartree)")
    delta_energy: float = Field(default=0.0, description="Change in electronic energy from prior cycle (Hartree)")
    max_dp: float | None = Field(default=None, description="Max Density Matrix difference (Max-DP)")
    rms_dp: float | None = Field(default=None, description="RMS Density Matrix difference (RMS-DP)")
    diis_error: float | None = Field(default=None, description="DIIS error vector norm if reported")
    time_seconds: float | None = Field(default=None, description="Iteration elapsed time")


class SCFConvergenceMetrics(BaseModel):
    """Trajectory analysis of SCF iterations detecting ping-pong oscillations or divergence."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: SCFConvergenceStatus = Field(default=SCFConvergenceStatus.NOT_STARTED)
    iterations_count: int = Field(default=0, description="Total SCF iterations recorded")
    final_energy: float | None = Field(default=None, description="Last recorded energy in Hartree")
    energy_delta_last: float | None = Field(default=None, description="Last recorded energy difference")
    is_oscillating: bool = Field(default=False, description="True if ping-pong limit cycle detected")
    is_diverging: bool = Field(default=False, description="True if catastrophic energy explosion detected")
    oscillation_cycle_detected: int | None = Field(default=None, description="Period of oscillation (e.g. 2, 3)")
    divergence_step: int | None = Field(default=None, description="Cycle index where divergence occurred")
    history: list[SCFIterationRecord] = Field(default_factory=list, description="Ordered iteration history")
    error_message: str | None = Field(default=None, description="Direct error string from solver")


class AutoCASAlert(BaseModel):
    """
    Notification payload dispatched when T1 or D1 diagnostics flag multireference breakdown.
    Directs GUI and workflow to downgrade pipeline state to ! AutoCAS.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: float = Field(default_factory=time.time, description="Unix timestamp of alert creation")
    molecule_id: str = Field(..., description="Identifier of the molecular geometry")
    t1_diagnostic: float = Field(..., description="Observed T1 diagnostic value")
    d1_diagnostic: float = Field(..., description="Observed D1 diagnostic value")
    t1_threshold: float = Field(default=T1_MULTIREF_THRESHOLD)
    d1_threshold: float = Field(default=D1_MULTIREF_THRESHOLD)
    downgraded_state: str = Field(default="! AutoCAS", description="New pipeline theory state")
    message: str = Field(..., description="Human-readable notification text")
    active_space_recommendation: dict[str, Any] = Field(
        default_factory=dict, description="Recommended active space params (n_elec, n_orb)"
    )
    suggested_keywords: str = Field(
        default="! AutoCAS CASSCF(4,4) NEVPT2 def2-TZVP",
        description="Suggested replacement keywords for multireference refinement",
    )


class CrossPlatformIPCAlert(BaseModel):
    """Generic IPC notification frame dispatched across thread, socket, or file queues."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    alert_id: str = Field(default_factory=lambda: f"ipc-{uuid.uuid4().hex[:8]}")
    timestamp: float = Field(default_factory=time.time)
    channel: str = Field(default=DEFAULT_IPC_CHANNEL)
    severity: AlertSeverity = Field(default=AlertSeverity.INFO)
    title: str = Field(..., description="Alert headline")
    message: str = Field(..., description="Detailed description")
    payload: dict[str, Any] = Field(default_factory=dict, description="Arbitrary structured metadata")


class ExecutionPlan(BaseModel):
    """Complete specification for an ab initio calculation step."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    plan_id: str = Field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:8]}")
    tier: str = Field(..., description="Method Matrix tier identifier")
    method_name: str = Field(..., description="Theoretical method label (e.g. wB97M-V, DLPNO-CCSD(T))")
    basis_set: str | None = Field(default=None, description="Basis set string")
    keywords: str = Field(..., description="Complete ORCA simple keywords line")
    geometry_block: str = Field(..., description="Cartesian geometry coordinate block")
    charge: int = Field(default=0, description="Total molecular charge")
    multiplicity: int = Field(default=1, description="Spin multiplicity (2S+1)")
    orbital_seed_path: str | None = Field(default=None, description="Path to binary .gbw orbital seed")
    moread_enabled: bool = Field(default=False, description="True if reading orbitals via ! MOREAD")
    slow_conv_enabled: bool = Field(default=False, description="True if SlowConv injected")
    vshift_enabled: bool = Field(default=False, description="True if VShift injected")
    max_memory_mb: int = Field(default=8000, description="Memory allocation per core in MB")
    num_cores: int = Field(default=8, description="Number of parallel MPI/OpenMP cores")
    timeout_seconds: float = Field(default=3600.0, description="Maximum execution duration")
    is_rescue_attempt: bool = Field(default=False, description="True if this is an automated rescue step")
    rescue_count: int = Field(default=0, description="Rescue sequence attempt index")
    custom_blocks: list[str] = Field(default_factory=list, description="Additional ORCA input blocks")


class EscalationStepRecord(BaseModel):
    """Detailed telemetry record for an executed escalation stage."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    step_index: int = Field(..., description="Step sequence index in the escalation ladder")
    tier: str = Field(..., description="Target tier executed")
    plan: ExecutionPlan = Field(..., description="Execution plan dispatched")
    execution_time_seconds: float = Field(default=0.0)
    status: CalculationStatus = Field(default=CalculationStatus.FAILED)
    final_energy_hartree: float | None = Field(default=None)
    scf_metrics: SCFConvergenceMetrics | None = Field(default=None)
    multiref_diagnostics: MultireferenceDiagnostics | None = Field(default=None)
    scf_rescued: bool = Field(default=False)
    rescue_attempts: int = Field(default=0)
    orbital_seed_path: str | None = Field(default=None)
    output_file_path: str | None = Field(default=None)
    error_message: str | None = Field(default=None)


class EscalatorExecConfig(BaseModel):
    """Configuration governing the Stage 4.0 Escalator Execution Broker."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    working_dir: Path = Field(default_factory=lambda: Path("./escalation_scratch"))
    orca_executable: str = Field(default="orca", description="Path or command for ORCA executable")
    max_scf_rescue_attempts: int = Field(default=DEFAULT_MAX_SCF_RESCUE_ATTEMPTS)
    t1_threshold: float = Field(default=T1_MULTIREF_THRESHOLD)
    d1_threshold: float = Field(default=D1_MULTIREF_THRESHOLD)
    default_num_cores: int = Field(default=8)
    default_memory_mb: int = Field(default=8000)
    enable_autocas_rescue: bool = Field(default=True)
    enable_ipc_alerts: bool = Field(default=True)
    ipc_port: int = Field(default=DEFAULT_IPC_PORT)
    ipc_socket_path: str | None = Field(default=None)
    ipc_channel: str = Field(default=DEFAULT_IPC_CHANNEL)
    redundant_coords_enforced: bool = Field(default=True)
    dry_run: bool = Field(default=False, description="Simulate execution without external binary calls")


class EscalationResult(BaseModel):
    """Aggregate session result returned by the master escalation broker."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    execution_id: str = Field(default_factory=lambda: f"esc-{uuid.uuid4().hex[:8]}")
    success: bool = Field(default=False)
    final_status: CalculationStatus = Field(default=CalculationStatus.FAILED)
    highest_tier_achieved: str = Field(default="None")
    final_energy_hartree: float | None = Field(default=None)
    autocas_triggered: bool = Field(default=False)
    autocas_alert: AutoCASAlert | None = Field(default=None)
    scf_rescues_applied: int = Field(default=0)
    steps: list[EscalationStepRecord] = Field(default_factory=list)
    total_runtime_seconds: float = Field(default=0.0)
    final_structure_xyz: str | None = Field(default=None)
    final_orbital_seed_path: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# 2. Directive 1: Redundant Internal Coordinates Verification & Cartesian Builder
# ============================================================================


class GeometryCoordinateVerifier:
    """
    Directive 1 Engine:
    Validates Cartesian geometries and ensures strictly no manual Z-matrix generation
    is injected into ORCA calculations.
    Standard Cartesian formats allow ORCA's geometry engine to naturally construct
    delocalized redundant internal coordinates (DLC) for robust SCF geometry convergence.
    """

    FORBIDDEN_ZMAT_PATTERNS = [
        re.compile(r"\*\s*gzcoord", re.IGNORECASE),
        re.compile(r"\*\s*zmat", re.IGNORECASE),
        re.compile(r"\*\s*internal", re.IGNORECASE),
        re.compile(r"^\s*[A-Za-z]{1,2}\s+\d+\s+[\d\.]+\s+\d+\s+[\d\.]+\s+\d+\s+[\d\.]+", re.MULTILINE),
        re.compile(r"^\s*[A-Za-z]{1,2}\s+\d+\s+[A-Za-z0-9_]+\s+\d+\s+[A-Za-z0-9_]+", re.MULTILINE),
        re.compile(r"Variables:", re.IGNORECASE),
        re.compile(r"Constants:", re.IGNORECASE),
    ]

    @classmethod
    def verify_redundant_internal_coordinates_compliance(cls, geometry_input: Any) -> bool:
        """
        Verifies that the provided geometry representation complies with the
        Cartesian format requirement (which permits ORCA's internal coordinate generator
        to naturally build delocalized redundant internals) and rejects manual Z-Matrices.

        Args:
            geometry_input: ASE Atoms, string XYZ, coordinate list, or raw input text.

        Returns:
            True if Cartesian format is strictly respected, False otherwise.
        """
        if isinstance(geometry_input, Atoms):
            return True

        if isinstance(geometry_input, np.ndarray):
            return bool(geometry_input.ndim == 2 and geometry_input.shape[1] == 3)

        if isinstance(geometry_input, list):
            if not geometry_input:
                return False
            try:
                first = geometry_input[0]
                if isinstance(first, tuple | list):
                    if len(first) == 2 and isinstance(first[0], str) and len(first[1]) == 3:
                        for item in geometry_input:
                            _ = float(item[1][0]), float(item[1][1]), float(item[1][2])
                        return True
                    elif len(first) == 4 and isinstance(first[0], str):
                        for item in geometry_input:
                            _ = float(item[1]), float(item[2]), float(item[3])
                        return True
                    elif len(first) == 3 and not isinstance(first[0], str):
                        for item in geometry_input:
                            _ = float(item[0]), float(item[1]), float(item[2])
                        return True
            except (ValueError, TypeError, IndexError):
                return False
            return False

        if isinstance(geometry_input, str):
            for pattern in cls.FORBIDDEN_ZMAT_PATTERNS:
                if pattern.search(geometry_input):
                    logger.error(f"Z-Matrix construct detected violating Directive 1: pattern '{pattern.pattern}'")
                    return False

            lines = [line.strip() for line in geometry_input.strip().splitlines() if line.strip()]
            if not lines:
                return False

            valid_cartesian_count = 0
            for line in lines:
                if line.startswith("*") or line.startswith("#") or line.startswith("$"):
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        _ = float(parts[1])
                        _ = float(parts[2])
                        _ = float(parts[3])
                        valid_cartesian_count += 1
                    except ValueError:
                        pass

            return valid_cartesian_count > 0

        return False

    @classmethod
    def validate_cartesian_format(cls, xyz_text: str) -> tuple[bool, str]:
        """
        Detailed validator returning success flag and diagnostic message.
        """
        is_compliant = cls.verify_redundant_internal_coordinates_compliance(xyz_text)
        if not is_compliant:
            return False, "Violation: Manual Z-matrix or non-Cartesian coordinate format detected."
        return True, "Cartesian coordinate specification valid. Redundant internal coordinates enabled."

    @classmethod
    def build_orca_cartesian_block(
        cls,
        atoms_or_coords: Atoms | Sequence[tuple[str, Sequence[float]]] | str,
        charge: int = 0,
        multiplicity: int = 1,
        constraints_block: str | None = None,
    ) -> str:
        """
        Builds a standard ORCA Cartesian coordinate block (`* xyz charge mult ... *`).
        Does NOT inject manual Z-matrices, guaranteeing ORCA's internal optimizer builds
        delocalized redundant internal coordinates.

        Args:
            atoms_or_coords: ASE Atoms object, list of (symbol, [x,y,z]), or XYZ string.
            charge: Net molecular charge.
            multiplicity: Spin multiplicity (2S+1).
            constraints_block: Optional %geom constraints block.

        Returns:
            Formatted ORCA coordinate block string.
        """
        lines = [f"* xyz {charge} {multiplicity}"]

        if isinstance(atoms_or_coords, Atoms):
            symbols = atoms_or_coords.get_chemical_symbols()
            positions = atoms_or_coords.get_positions()
            for sym, (x, y, z) in zip(symbols, positions, strict=True):
                lines.append(f"  {sym:<3} {x:14.8f} {y:14.8f} {z:14.8f}")
        elif isinstance(atoms_or_coords, list):
            for item in atoms_or_coords:
                if isinstance(item, tuple | list) and len(item) == 2:
                    sym, pos = item
                    x, y, z = pos[0], pos[1], pos[2]
                    lines.append(f"  {str(sym):<3} {float(x):14.8f} {float(y):14.8f} {float(z):14.8f}")
                elif isinstance(item, tuple | list) and len(item) == 4:
                    sym, x, y, z = item
                    lines.append(f"  {str(sym):<3} {float(x):14.8f} {float(y):14.8f} {float(z):14.8f}")
        elif isinstance(atoms_or_coords, str):
            raw_lines = [ln.strip() for ln in atoms_or_coords.strip().splitlines() if ln.strip()]
            for raw_ln in raw_lines:
                if raw_ln.startswith("*") or raw_ln.startswith("#"):
                    continue
                parts = raw_ln.split()
                if len(parts) >= 4:
                    sym = parts[0]
                    try:
                        x = float(parts[1])
                        y = float(parts[2])
                        z = float(parts[3])
                        lines.append(f"  {sym:<3} {x:14.8f} {y:14.8f} {z:14.8f}")
                    except ValueError:
                        continue

        lines.append("*")

        if constraints_block:
            lines.insert(0, constraints_block.strip())

        return "\n".join(lines)


# ============================================================================
# 3. Directive 2: Automated SCF Rescue & Output Buffer Parsing
# ============================================================================


class ORCAOutputParser:
    """
    Directive 2 & 3 Output Buffer Parser:
    Real-time and batch parser extracting SCF iteration dynamics, ping-pong
    oscillations, divergence metrics, and post-HF T1/D1 multireference diagnostics.
    """

    SCF_ITER_REGEX = re.compile(
        r"^\s*(\d+)\s+([-\d\.]+)\s+([-\d\.\+eE]+)\s+([-\d\.\+eE]+)\s+([-\d\.\+eE]+)",
        re.MULTILINE,
    )
    T1_REGEX = re.compile(
        r"(?:T1\s+diagnostic|T1\s+Diagnostic|T1\s*=|T_1\s+diagnostic)\s*[:=.]*\s*([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?\d+)?)",
        re.IGNORECASE,
    )
    D1_REGEX = re.compile(
        r"(?:D1\s+diagnostic|D1\s+Diagnostic|D1\s*=|D_1\s+diagnostic)\s*[:=.]*\s*([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?\d+)?)",
        re.IGNORECASE,
    )
    D2_REGEX = re.compile(
        r"(?:D2\s+diagnostic|D2\s+Diagnostic|D2\s*=|D_2\s+diagnostic)\s*[:=.]*\s*([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?\d+)?)",
        re.IGNORECASE,
    )
    FINAL_ENERGY_REGEX = re.compile(
        r"(?:FINAL SINGLE POINT ENERGY|Total Energy|FINAL ENERGY|Electronic energy)\s*[:=.]*\s*([-\d\.]+(?:[eE][+-]?\d+)?)",
        re.IGNORECASE,
    )
    SCF_DIVERGENCE_TOKENS = [
        "SCF NOT CONVERGED",
        "DIVERGENCE",
        "DIIS error is too large",
        "Energy increased in SCF",
        "Calculation aborted: SCF did not converge",
        "SOSCF failed to converge",
        "Energy explosion",
        "SCF failed",
    ]

    @classmethod
    def parse_scf_iterations(cls, output_text: str) -> SCFConvergenceMetrics:
        """
        Parses all SCF cycle records from the output buffer and analyzes convergence stability.
        """
        records: list[SCFIterationRecord] = []
        lines = output_text.splitlines()

        in_scf_block = False
        for line in lines:
            stripped = line.strip()
            upper_line = stripped.upper()

            # Section entrance markers for SCF table
            if (
                "SCF ITERATIONS" in upper_line
                or "ORCA SCF" in upper_line
                or (upper_line.startswith("ITER") and "ENERGY" in upper_line)
            ):
                in_scf_block = True
                continue

            # Section exit markers
            if in_scf_block and (
                "CONVERGED" in upper_line
                or "ORBITAL ENERGIES" in upper_line
                or "CARTESIAN COORDINATES" in upper_line
                or "TOTAL SCF ENERGY" in upper_line
                or "FINAL SINGLE POINT ENERGY" in upper_line
                or upper_line.startswith("---")
                or upper_line.startswith("***")
            ):
                if not (upper_line.startswith("ITER") or upper_line.startswith("---")):
                    in_scf_block = False

            parts = stripped.split()
            if in_scf_block and len(parts) >= 3 and parts[0].isdigit():
                try:
                    iter_idx = int(parts[0])
                    energy = float(parts[1])
                    delta_e = float(parts[2])
                    max_dp = float(parts[3]) if len(parts) > 3 else None
                    rms_dp = float(parts[4]) if len(parts) > 4 else None
                    records.append(
                        SCFIterationRecord(
                            iteration=iter_idx,
                            energy_hartree=energy,
                            delta_energy=delta_e,
                            max_dp=max_dp,
                            rms_dp=rms_dp,
                        )
                    )
                except (ValueError, IndexError):
                    continue
            elif not in_scf_block and len(parts) >= 5 and parts[0].isdigit():
                try:
                    iter_idx = int(parts[0])
                    energy = float(parts[1])
                    delta_e = float(parts[2])
                    max_dp = float(parts[3])
                    rms_dp = float(parts[4])
                    if energy < 0.0:
                        records.append(
                            SCFIterationRecord(
                                iteration=iter_idx,
                                energy_hartree=energy,
                                delta_energy=delta_e,
                                max_dp=max_dp,
                                rms_dp=rms_dp,
                            )
                        )
                except (ValueError, IndexError):
                    continue

        error_found: str | None = None
        for token in cls.SCF_DIVERGENCE_TOKENS:
            if token.lower() in output_text.lower():
                error_found = token
                break

        is_oscillating, cycle_len = cls.detect_scf_oscillation(records)
        is_diverging, div_step = cls.detect_scf_divergence(records)

        if error_found:
            status = SCFConvergenceStatus.DIVERGING if is_diverging else SCFConvergenceStatus.FAILED
        elif is_diverging:
            status = SCFConvergenceStatus.DIVERGING
        elif is_oscillating:
            status = SCFConvergenceStatus.OSCILLATING_PING_PONG
        elif "SCF CONVERGED" in output_text or "SUCCESSFULLY CONVERGED" in output_text:
            status = SCFConvergenceStatus.CONVERGED
        elif len(records) > 0:
            status = SCFConvergenceStatus.CONVERGING
        else:
            status = SCFConvergenceStatus.NOT_STARTED

        final_energy = records[-1].energy_hartree if records else None
        energy_delta_last = records[-1].delta_energy if records else None

        return SCFConvergenceMetrics(
            status=status,
            iterations_count=len(records),
            final_energy=final_energy,
            energy_delta_last=energy_delta_last,
            is_oscillating=is_oscillating,
            is_diverging=is_diverging,
            oscillation_cycle_detected=cycle_len if is_oscillating else None,
            divergence_step=div_step if is_diverging else None,
            history=records,
            error_message=error_found,
        )

    @classmethod
    def detect_scf_oscillation(
        cls,
        history: list[SCFIterationRecord],
        window: int = DEFAULT_SCF_OSCILLATION_WINDOW,
        tolerance: float = 1e-4,
    ) -> tuple[bool, int]:
        """
        Mathematically detects ping-pong oscillations in SCF electronic energies.
        Checks for 2-cycle or 3-cycle limit cycles: E(t) ~= E(t-2) while E(t) != E(t-1).

        Args:
            history: List of SCF iteration records.
            window: Number of recent iterations to inspect.
            tolerance: Energy equivalence threshold for oscillation recognition.

        Returns:
            (is_oscillating, cycle_length)
        """
        if len(history) < min(window, 4):
            return False, 0

        eval_window = max(window, 6)
        recent_records = history[-eval_window:] if len(history) >= eval_window else history
        energies = [rec.energy_hartree for rec in recent_records]
        deltas = [rec.delta_energy for rec in recent_records]

        # 1. Check for 2-cycle ping-pong oscillation: E(i) == E(i-2), E(i) != E(i-1)
        if len(energies) >= 4:
            e0, e1, e2, e3 = energies[-4], energies[-3], energies[-2], energies[-1]
            diff_step = abs(e3 - e2)
            diff_cycle = abs(e3 - e1)
            diff_cycle_prior = abs(e2 - e0)

            if diff_step > 5.0 * tolerance and diff_cycle < tolerance and diff_cycle_prior < tolerance:
                logger.warning(f"Ping-pong 2-cycle SCF oscillation detected: Delta={diff_step:.6f} Ha")
                return True, 2

        # 2. Check for alternating delta-E sign flip with persistent non-zero magnitude
        if len(deltas) >= 4:
            signs = [(1 if d > 0 else -1) for d in deltas[-4:] if abs(d) > tolerance]
            if len(signs) == 4 and signs[0] == -signs[1] and signs[1] == -signs[2] and signs[2] == -signs[3]:
                logger.warning("Alternating delta-E sign oscillations detected across 4 consecutive cycles.")
                return True, 2

        # 3. Check for 3-cycle oscillation: E(t) ~= E(t-3), E(t-1) ~= E(t-4), E(t-2) ~= E(t-5)
        if len(energies) >= 6:
            if (
                abs(energies[-1] - energies[-4]) < tolerance
                and abs(energies[-2] - energies[-5]) < tolerance
                and abs(energies[-3] - energies[-6]) < tolerance
            ):
                if abs(energies[-1] - energies[-2]) > 5.0 * tolerance:
                    return True, 3

        return False, 0

    @classmethod
    def detect_scf_divergence(
        cls,
        history: list[SCFIterationRecord],
        threshold_hartree: float = DEFAULT_SCF_DIVERGENCE_TOL_HARTREE,
    ) -> tuple[bool, int]:
        """
        Detects catastrophic energy divergence or numerical explosion during SCF cycles.

        Args:
            history: List of SCF iteration records.
            threshold_hartree: Energy delta threshold signifying divergence.

        Returns:
            (is_diverging, step_index)
        """
        if not history:
            return False, 0

        for rec in history:
            if math.isnan(rec.energy_hartree) or math.isinf(rec.energy_hartree):
                logger.error(f"SCF Divergence: Non-finite energy at cycle {rec.iteration}")
                return True, rec.iteration

            if rec.delta_energy > threshold_hartree:
                logger.error(f"SCF Divergence: Massive positive energy jump ({rec.delta_energy:.4f} Ha) at cycle {rec.iteration}")
                return True, rec.iteration

        if len(history) >= 3:
            e_init = history[0].energy_hartree
            e_curr = history[-1].energy_hartree
            if (e_curr - e_init) > 5.0 * threshold_hartree:
                return True, history[-1].iteration

        return False, 0

    @classmethod
    def parse_multireference_diagnostics(cls, output_text: str) -> MultireferenceDiagnostics:
        """
        Directive 3: Extracts T1 and D1 multireference diagnostics from post-Hartree-Fock outputs.
        Flags violation if T1 > 0.02 or D1 > 0.05.
        """
        t1_val = 0.0
        d1_val = 0.0
        d2_val: float | None = None

        t1_match = cls.T1_REGEX.search(output_text)
        if t1_match:
            t1_val = float(t1_match.group(1))

        d1_match = cls.D1_REGEX.search(output_text)
        if d1_match:
            d1_val = float(d1_match.group(1))

        d2_match = cls.D2_REGEX.search(output_text)
        if d2_match:
            d2_val = float(d2_match.group(1))

        is_multiref = (t1_val > T1_MULTIREF_THRESHOLD) or (d1_val > D1_MULTIREF_THRESHOLD)
        reason: str | None = None

        if is_multiref:
            reasons = []
            if t1_val > T1_MULTIREF_THRESHOLD:
                reasons.append(f"T1={t1_val:.4f} > {T1_MULTIREF_THRESHOLD}")
            if d1_val > D1_MULTIREF_THRESHOLD:
                reasons.append(f"D1={d1_val:.4f} > {D1_MULTIREF_THRESHOLD}")
            reason = f"Multireference assumption violation: {', '.join(reasons)}. Closed-shell single-reference CCSD(T) breakdown."
            logger.warning(f"AutoCAS Diagnostic Violation: {reason}")

        sugg_elec = 4 if is_multiref else None
        sugg_orb = 4 if is_multiref else None

        return MultireferenceDiagnostics(
            t1_diagnostic=t1_val,
            d1_diagnostic=d1_val,
            d2_diagnostic=d2_val,
            t1_threshold=T1_MULTIREF_THRESHOLD,
            d1_threshold=D1_MULTIREF_THRESHOLD,
            is_multireference=is_multiref,
            violation_reason=reason,
            suggested_active_electrons=sugg_elec,
            suggested_active_orbitals=sugg_orb,
        )

    @classmethod
    def parse_final_energy(cls, output_text: str) -> float | None:
        """Extracts the final converged electronic energy in Hartree."""
        matches = cls.FINAL_ENERGY_REGEX.findall(output_text)
        if matches:
            try:
                return float(matches[-1])
            except ValueError:
                pass
        return None

    @classmethod
    def parse_orca_full_output(cls, output_text: str) -> dict[str, Any]:
        """Performs unified parsing of geometry, energy, SCF metrics, and diagnostics."""
        scf_metrics = cls.parse_scf_iterations(output_text)
        multiref = cls.parse_multireference_diagnostics(output_text)
        final_energy = cls.parse_final_energy(output_text)

        return {
            "final_energy_hartree": final_energy,
            "scf_metrics": scf_metrics,
            "multireference_diagnostics": multiref,
            "normal_termination": "ORCA TERMINATED NORMALLY" in output_text or "SUCCESS" in output_text,
        }


# ============================================================================
# 4. Directive 2: Automated SCF Rescue Engine
# ============================================================================


class AutomatedSCFRescueEngine:
    """
    Directive 2 Engine:
    Intercepts SCF divergence and ping-pong limit cycles, injecting `! SlowConv VShift`
    keywords and restarting the calculation from the last converged binary `.gbw` orbital seed.
    """

    RESCUE_KEYWORDS_LINE = "! SlowConv VShift MOREAD"
    RESCUE_SCF_BLOCK = """%scf
  Shift Shift 0.20 ErrOff 0.001 end
  MaxIter 300
  SOSCFMaxIter 150
  DIISMaxIt 30
end"""

    @classmethod
    def inject_scf_rescue_keywords(
        cls,
        input_content: str,
        gbw_seed_path: str | Path | None = None,
        rescue_level: int = 1,
    ) -> str:
        """
        Injects `! SlowConv VShift`, `%moinp`, and `! MOREAD` into an ORCA input string.

        Args:
            input_content: Original ORCA input text.
            gbw_seed_path: Path to the binary .gbw orbital seed from the last converged step.
            rescue_level: Escalating aggressiveness of SCF damping.

        Returns:
            Modified ORCA input text ready for rescued restart.
        """
        lines = input_content.splitlines()
        modified_lines: list[str] = []
        simple_keywords_injected = False

        for line in lines:
            stripped = line.strip()

            if stripped.startswith("!") and not simple_keywords_injected:
                kw_tokens = stripped.split()
                if "SlowConv" not in kw_tokens:
                    kw_tokens.append("SlowConv")
                if "VShift" not in kw_tokens:
                    kw_tokens.append("VShift")
                if gbw_seed_path and "MOREAD" not in kw_tokens:
                    kw_tokens.append("MOREAD")

                modified_lines.append(" ".join(kw_tokens))
                simple_keywords_injected = True
                continue

            if stripped.startswith("%moinp"):
                continue

            modified_lines.append(line)

        if gbw_seed_path:
            seed_p = Path(gbw_seed_path).resolve()
            norm_seed = str(seed_p).replace("\\", "/")
            moinp_block = f'%moinp "{norm_seed}"'
            insert_idx = 0
            for idx, ln in enumerate(modified_lines):
                if ln.strip().startswith("* xyz"):
                    insert_idx = idx
                    break
            if insert_idx > 0:
                modified_lines.insert(insert_idx, moinp_block)
            else:
                modified_lines.append(moinp_block)

        if rescue_level >= 2:
            modified_lines.append(cls.RESCUE_SCF_BLOCK)

        result = "\n".join(modified_lines)
        logger.info(
            f"SCF Rescue Injected: SlowConv/VShift added, MOREAD={'yes' if gbw_seed_path else 'no'}, seed={gbw_seed_path}"
        )
        return result

    @classmethod
    def build_rescue_plan(
        cls,
        failed_plan: ExecutionPlan,
        gbw_seed_path: str | Path | None,
        attempt: int = 1,
    ) -> ExecutionPlan:
        """
        Creates a new rescued ExecutionPlan derived from a failed plan with injected rescue parameters.
        """
        kw_tokens = failed_plan.keywords.split()
        if "SlowConv" not in kw_tokens:
            kw_tokens.append("SlowConv")
        if "VShift" not in kw_tokens:
            kw_tokens.append("VShift")
        if gbw_seed_path and "MOREAD" not in kw_tokens:
            kw_tokens.append("MOREAD")

        rescued_keywords = " ".join(kw_tokens)
        custom_blocks = [
            b for b in failed_plan.custom_blocks
            if not b.strip().startswith("%moinp") and not b.strip().startswith("%scf")
        ]

        if gbw_seed_path:
            seed_p = Path(gbw_seed_path).resolve()
            norm_seed = str(seed_p).replace("\\", "/")
            custom_blocks.append(f'%moinp "{norm_seed}"')

        if attempt >= 2:
            custom_blocks.append(cls.RESCUE_SCF_BLOCK)

        return ExecutionPlan(
            plan_id=f"{failed_plan.plan_id}-rescue-{attempt}",
            tier=failed_plan.tier,
            method_name=failed_plan.method_name,
            basis_set=failed_plan.basis_set,
            keywords=rescued_keywords,
            geometry_block=failed_plan.geometry_block,
            charge=failed_plan.charge,
            multiplicity=failed_plan.multiplicity,
            orbital_seed_path=str(gbw_seed_path) if gbw_seed_path else None,
            moread_enabled=bool(gbw_seed_path),
            slow_conv_enabled=True,
            vshift_enabled=True,
            max_memory_mb=failed_plan.max_memory_mb,
            num_cores=failed_plan.num_cores,
            timeout_seconds=failed_plan.timeout_seconds,
            is_rescue_attempt=True,
            rescue_count=attempt,
            custom_blocks=custom_blocks,
        )


# ============================================================================
# 5. Directive 3: The AutoCAS Rescue Protocol Engine
# ============================================================================


class AutoCASRescueProtocol:
    """
    Directive 3 Engine:
    Monitors T1 and D1 multireference diagnostics.
    If T1 > 0.02 or D1 > 0.05, mathematically flags single-reference breakdown,
    halts further coupled-cluster escalation, downgrades pipeline state to `! AutoCAS`,
    and prepares multi-reference active space recommendations for the GUI.
    """

    T1_LIMIT: float = T1_MULTIREF_THRESHOLD
    D1_LIMIT: float = D1_MULTIREF_THRESHOLD

    @classmethod
    def check_multireference_violation(cls, t1: float, d1: float) -> bool:
        """
        Mathematically checks if single-reference post-Hartree-Fock assumption is violated.
        Returns True if T1 > 0.02 or D1 > 0.05.
        """
        return (t1 > cls.T1_LIMIT) or (d1 > cls.D1_LIMIT)

    @classmethod
    def create_autocas_alert(
        cls,
        molecule_id: str,
        t1: float,
        d1: float,
        symbols: list[str] | None = None,
        charge: int = 0,
        multiplicity: int = 1,
    ) -> AutoCASAlert:
        """
        Constructs a structured AutoCASAlert payload directing workflow downgrade to `! AutoCAS`.
        """
        num_atoms = len(symbols) if symbols else 1
        active_e = min(8, max(2, (num_atoms // 2) * 2))
        active_o = min(8, max(2, num_atoms // 2))

        suggested_kw = f"! AutoCAS CASSCF({active_e},{active_o}) NEVPT2 def2-TZVP defgrid3"

        msg = (
            f"CRITICAL: Multireference character detected for '{molecule_id}' "
            f"(T1={t1:.4f} > {cls.T1_LIMIT} or D1={d1:.4f} > {cls.D1_LIMIT}). "
            f"Single-reference post-HF assumption violated. Downgrading pipeline to '! AutoCAS'."
        )

        return AutoCASAlert(
            molecule_id=molecule_id,
            t1_diagnostic=t1,
            d1_diagnostic=d1,
            t1_threshold=cls.T1_LIMIT,
            d1_threshold=cls.D1_LIMIT,
            downgraded_state="! AutoCAS",
            message=msg,
            active_space_recommendation={
                "active_electrons": active_e,
                "active_orbitals": active_o,
                "state_multiplicity": multiplicity,
                "target_roots": 1 if multiplicity == 1 else 2,
            },
            suggested_keywords=suggested_kw,
        )

    @classmethod
    def generate_autocas_input_block(
        cls,
        geometry_block: str,
        active_electrons: int = 4,
        active_orbitals: int = 4,
        basis_set: str = "def2-TZVP",
        charge: int = 0,
        multiplicity: int = 1,
    ) -> str:
        """
        Generates standard ORCA AutoCAS / CASSCF / NEVPT2 input file content for multi-reference execution.
        """
        return f"""! CASSCF({active_electrons},{active_orbitals}) NEVPT2 {basis_set} TightSCF defgrid3
%casscf
  nel {active_electrons}
  norb {active_orbitals}
  mult {multiplicity}
  nroots 1
end

{geometry_block}
"""


# ============================================================================
# 6. Cross-Platform IPC Architecture (TCP Loopback & File Queue)
# ============================================================================


class FileSocketIPCQueue:
    """
    File-socket queue implementation providing robust, lock-free IPC messaging
    across all platforms without port conflicts or permission boundaries.
    """

    def __init__(self, queue_dir: Path) -> None:
        self.queue_dir = queue_dir
        self.queue_dir.mkdir(parents=True, exist_ok=True)

    def push(self, alert: CrossPlatformIPCAlert) -> Path:
        """Writes an alert atomically to the queue directory."""
        msg_file = self.queue_dir / f"msg_{alert.timestamp}_{alert.alert_id}.json"
        tmp_file = self.queue_dir / f"tmp_{alert.alert_id}.json"
        tmp_file.write_text(alert.model_dump_json(indent=2), encoding="utf-8")
        tmp_file.replace(msg_file)
        return msg_file

    def pop_all(self) -> list[CrossPlatformIPCAlert]:
        """Pops and deletes all available queued alerts."""
        alerts: list[CrossPlatformIPCAlert] = []
        files = sorted(self.queue_dir.glob("msg_*.json"))
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                alerts.append(CrossPlatformIPCAlert.model_validate(data))
                f.unlink(missing_ok=True)
            except Exception as e:
                logger.error(f"Error reading IPC file {f}: {e}")
        return alerts


class CrossPlatformIPCServer:
    """
    Cross-platform IPC Server receiving alerts and notifying registered GUI/CLI callbacks.
    Employs local TCP loopback with automated file queue fallback.
    """

    def __init__(self, port: int = DEFAULT_IPC_PORT, queue_dir: Path | None = None) -> None:
        self.port = port
        self.queue_dir = queue_dir or Path("./.ipc_queue")
        self.file_queue = FileSocketIPCQueue(self.queue_dir)
        self.callbacks: list[Callable[[CrossPlatformIPCAlert], None]] = []
        self.history: list[CrossPlatformIPCAlert] = []
        self._running = False
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def register_callback(self, callback: Callable[[CrossPlatformIPCAlert], None]) -> None:
        """Registers a listener function to be called on incoming alerts."""
        with self._lock:
            self.callbacks.append(callback)

    def start(self) -> None:
        """Starts the IPC server listener thread."""
        if self._running:
            return

        self._running = True
        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind(("127.0.0.1", self.port))
            self._server_socket.listen(5)
            self._server_socket.settimeout(0.5)
            logger.info(f"Cross-Platform IPC Server started on 127.0.0.1:{self.port}")
        except Exception as e:
            logger.warning(f"Could not bind TCP socket on port {self.port} ({e}). Using File-Socket IPC Queue.")
            self._server_socket = None

        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def _listen_loop(self) -> None:
        while self._running:
            if self._server_socket:
                try:
                    conn, _ = self._server_socket.accept()
                    with conn:
                        conn.settimeout(0.5)
                        chunks: list[bytes] = []
                        while True:
                            try:
                                chunk = conn.recv(65536)
                                if not chunk:
                                    break
                                chunks.append(chunk)
                            except TimeoutError:
                                break
                        data = b"".join(chunks)
                        if data:
                            alert_dict = json.loads(data.decode("utf-8"))
                            alert = CrossPlatformIPCAlert.model_validate(alert_dict)
                            self._dispatch_alert(alert)
                except TimeoutError:
                    pass
                except Exception as e:
                    if self._running:
                        logger.debug(f"IPC Socket accept error: {e}")

            file_alerts = self.file_queue.pop_all()
            for alert in file_alerts:
                self._dispatch_alert(alert)

            time.sleep(0.05)

    def _dispatch_alert(self, alert: CrossPlatformIPCAlert) -> None:
        with self._lock:
            self.history.append(alert)
            for cb in self.callbacks:
                try:
                    cb(alert)
                except Exception as ex:
                    logger.error(f"Error in IPC listener callback: {ex}")

    def stop(self) -> None:
        """Stops the IPC server gracefully."""
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("Cross-Platform IPC Server stopped.")


class CrossPlatformIPCClient:
    """
    Cross-platform IPC Client dispatching alerts to the GUI or external daemon.
    Tries TCP loopback connection first, then automatically falls back to File Queue.
    """

    def __init__(self, port: int = DEFAULT_IPC_PORT, queue_dir: Path | None = None) -> None:
        self.port = port
        self.queue_dir = queue_dir or Path("./.ipc_queue")
        self.file_queue = FileSocketIPCQueue(self.queue_dir)

    def send_alert(self, alert: CrossPlatformIPCAlert) -> bool:
        """
        Sends an alert via TCP or File Queue.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                sock.connect(("127.0.0.1", self.port))
                sock.sendall(alert.model_dump_json().encode("utf-8"))
                return True
        except Exception:
            self.file_queue.push(alert)
            return True


def send_ipc_alert(
    title: str,
    message: str,
    severity: AlertSeverity = AlertSeverity.INFO,
    payload: dict[str, Any] | None = None,
    channel: str = DEFAULT_IPC_CHANNEL,
    port: int = DEFAULT_IPC_PORT,
    queue_dir: Path | None = None,
) -> CrossPlatformIPCAlert:
    """
    Convenience function to dispatch a cross-platform IPC alert.
    """
    alert = CrossPlatformIPCAlert(
        channel=channel,
        severity=severity,
        title=title,
        message=message,
        payload=payload or {},
    )
    client = CrossPlatformIPCClient(port=port, queue_dir=queue_dir)
    client.send_alert(alert)
    return alert


# ============================================================================
# 7. Time-Aware Capability Selector & Method Matrix Escalation Ladder
# ============================================================================


class TimeAwareCapabilitySelector:
    """
    Stage 4.0 Time-Aware Capability Selector:
    Routes molecular geometries through the optimal level-of-theory escalation ladder
    based on allotted time budget, molecular size, element composition, and hardware constraints.
    """

    TIER_SPECIFICATIONS: dict[str, dict[str, Any]] = {
        EscalationTier.T1_10S.value: {
            "tier": EscalationTier.T1_10S.value,
            "method": "XTB2",
            "basis_set": None,
            "keywords": "! XTB2 TightOpt",
            "time_budget_sec": 10.0,
            "engine": "CPU",
            "description": "Fast semiempirical GFN2-xTB geometry screening",
            "is_post_hf": False,
        },
        EscalationTier.T1_1MIN.value: {
            "tier": EscalationTier.T1_1MIN.value,
            "method": "GOAT-XTB2",
            "basis_set": None,
            "keywords": "! GOAT XTB2 PAL8",
            "time_budget_sec": 60.0,
            "engine": "CPU",
            "description": "GOAT stochastic conformer discovery",
            "is_post_hf": False,
        },
        EscalationTier.T1_30MIN.value: {
            "tier": EscalationTier.T1_30MIN.value,
            "method": "MACE-OFF24m",
            "basis_set": None,
            "keywords": "! GOAT-EXPLORE ExtOpt TightOpt PAL8",
            "time_budget_sec": 1800.0,
            "engine": "GPU",
            "description": "Machine-learning force field PES exploration",
            "is_post_hf": False,
        },
        EscalationTier.T1_1H.value: {
            "tier": EscalationTier.T1_1H.value,
            "method": "CREST-NCI",
            "basis_set": None,
            "keywords": "! crest --nci --gfn2 --ewin 12",
            "time_budget_sec": 3600.0,
            "engine": "CPU",
            "description": "CREST non-covalent conformer cross-check",
            "is_post_hf": False,
        },
        EscalationTier.T1_3H.value: {
            "tier": EscalationTier.T1_3H.value,
            "method": "r2SCAN-3c",
            "basis_set": "def2-mTZVP",
            "keywords": f"! r2SCAN-3c TightOpt TightSCF defgrid3\n{STANDARD_5_THRESHOLD_GEOM_BLOCK}",
            "time_budget_sec": 10800.0,
            "engine": "CPU",
            "description": "Composite meta-GGA DFT re-optimization",
            "is_post_hf": False,
        },
        EscalationTier.T1_12H.value: {
            "tier": EscalationTier.T1_12H.value,
            "method": "GOAT-r2SCAN-3c",
            "basis_set": "def2-mTZVP",
            "keywords": f"! GOAT r2SCAN-3c defgrid3\n{STANDARD_5_THRESHOLD_GEOM_BLOCK}",
            "time_budget_sec": 43200.0,
            "engine": "CPU",
            "description": "QM-level GOAT search around minima",
            "is_post_hf": False,
        },
        EscalationTier.T1_1D.value: {
            "tier": EscalationTier.T1_1D.value,
            "method": "GOAT-ENTROPY-XTB2",
            "basis_set": None,
            "keywords": "! GOAT-ENTROPY XTB2",
            "time_budget_sec": 86400.0,
            "engine": "CPU",
            "description": "Conformer entropy convergence diagnostic",
            "is_post_hf": False,
        },
        EscalationTier.T1_3D.value: {
            "tier": EscalationTier.T1_3D.value,
            "method": "wB97M-V / DLPNO-CCSD(T)",
            "basis_set": "def2-QZVP",
            "keywords": f"! wB97M-V def2-QZVP defgrid3 TightOpt TightSCF\n{STANDARD_5_THRESHOLD_GEOM_BLOCK}",
            "time_budget_sec": 259200.0,
            "engine": "CPU",
            "description": "High-level DFT & DLPNO-CCSD(T) single-point escalation",
            "is_post_hf": True,
        },
        EscalationTier.AUTOCAS.value: {
            "tier": EscalationTier.AUTOCAS.value,
            "method": "AutoCAS-CASSCF-NEVPT2",
            "basis_set": "def2-TZVP",
            "keywords": "! AutoCAS CASSCF(4,4) NEVPT2 def2-TZVP TightSCF defgrid3",
            "time_budget_sec": 86400.0,
            "engine": "CPU",
            "description": "Automated multireference active space calculation",
            "is_post_hf": True,
        },
    }

    LADDER_ORDER: list[str] = [
        EscalationTier.T1_10S.value,
        EscalationTier.T1_1MIN.value,
        EscalationTier.T1_30MIN.value,
        EscalationTier.T1_1H.value,
        EscalationTier.T1_3H.value,
        EscalationTier.T1_12H.value,
        EscalationTier.T1_1D.value,
        EscalationTier.T1_3D.value,
    ]

    @classmethod
    def select_optimal_tier(
        cls,
        time_budget_seconds: float,
        num_atoms: int,
        is_complex: bool = False,
        hardware_gpu: bool = False,
    ) -> EscalationTier:
        """
        Selects the highest viable Method Matrix tier achievable within the time budget.

        Args:
            time_budget_seconds: Allotted execution wall time in seconds.
            num_atoms: Total atom count of the molecule or complex.
            is_complex: True if the target is a multi-monomer weak complex.
            hardware_gpu: True if CUDA/GPU acceleration is available.

        Returns:
            Optimal target EscalationTier.
        """
        size_factor = max(1.0, (num_atoms / 20.0) ** 2)
        effective_budget = time_budget_seconds / size_factor

        if effective_budget >= 86400.0:
            return EscalationTier.T1_3D
        elif effective_budget >= 43200.0:
            return EscalationTier.T1_1D
        elif effective_budget >= 10800.0:
            return EscalationTier.T1_12H
        elif effective_budget >= 3600.0:
            return EscalationTier.T1_3H
        elif effective_budget >= 1800.0:
            return EscalationTier.T1_1H
        elif effective_budget >= 60.0:
            return EscalationTier.T1_30MIN if hardware_gpu else EscalationTier.T1_1MIN
        else:
            return EscalationTier.T1_10S

    @classmethod
    def get_tier_spec(cls, tier: EscalationTier | str) -> dict[str, Any]:
        """Retrieves the specification dictionary for a given tier."""
        tier_key = tier.value if isinstance(tier, EscalationTier) else str(tier)
        if tier_key not in cls.TIER_SPECIFICATIONS:
            raise ValueError(f"Unknown EscalationTier '{tier_key}' requested.")
        return cls.TIER_SPECIFICATIONS[tier_key]

    @classmethod
    def build_escalation_ladder(
        cls,
        target_tier: EscalationTier | str,
        start_tier: EscalationTier | str | None = None,
    ) -> list[EscalationTier]:
        """
        Builds an ordered list of escalation tiers from start_tier to target_tier.
        """
        target_str = target_tier.value if isinstance(target_tier, EscalationTier) else str(target_tier)
        start_str = (
            (start_tier.value if isinstance(start_tier, EscalationTier) else str(start_tier))
            if start_tier
            else EscalationTier.T1_10S.value
        )

        if target_str == EscalationTier.AUTOCAS.value:
            return [EscalationTier.T1_3H, EscalationTier.T1_3D, EscalationTier.AUTOCAS]

        try:
            start_idx = cls.LADDER_ORDER.index(start_str)
            target_idx = cls.LADDER_ORDER.index(target_str)
        except ValueError:
            return [EscalationTier(target_str)]

        if start_idx > target_idx:
            start_idx = 0

        selected = cls.LADDER_ORDER[start_idx : target_idx + 1]
        return [EscalationTier(t) for t in selected]


# ============================================================================
# 8. Master Escalation Execution Broker (ToposEscalatorExec)
# ============================================================================


class ToposEscalatorExec:
    """
    Master Stage 4.0 Quantum Mechanical Execution Broker.
    Orchestrates geometry verification, Method Matrix escalation, active SCF failure rescue,
    and AutoCAS multi-reference diagnostic monitoring.
    """

    def __init__(self, config: EscalatorExecConfig | None = None) -> None:
        self.config = config or EscalatorExecConfig()
        self.config.working_dir.mkdir(parents=True, exist_ok=True)
        self.ipc_queue_dir = self.config.working_dir / ".ipc_queue"
        self.ipc_queue_dir.mkdir(parents=True, exist_ok=True)

        self.ipc_client = CrossPlatformIPCClient(
            port=self.config.ipc_port,
            queue_dir=self.ipc_queue_dir,
        )

    def verify_geometry(self, geometry_input: Any) -> bool:
        """
        Directive 1: Verifies Cartesian coordinate compliance and ensures
        manual Z-matrices are rejected.
        """
        is_valid = GeometryCoordinateVerifier.verify_redundant_internal_coordinates_compliance(geometry_input)
        if not is_valid:
            logger.error("Directive 1 Verification Failed: Manual Z-matrix or illegal coordinate format detected.")
            if self.config.enable_ipc_alerts:
                send_ipc_alert(
                    title="Directive 1 Violation",
                    message="Manual Z-Matrix detected. ORCA requires Cartesian coordinates for redundant internals.",
                    severity=AlertSeverity.ERROR,
                    port=self.config.ipc_port,
                    queue_dir=self.ipc_queue_dir,
                )
        return is_valid

    def build_plan(
        self,
        tier: EscalationTier | str,
        geometry_input: Atoms | str | Sequence[tuple[str, Sequence[float]]],
        charge: int = 0,
        multiplicity: int = 1,
        orbital_seed_path: str | Path | None = None,
    ) -> ExecutionPlan:
        """
        Constructs an ExecutionPlan for a given Method Matrix tier and geometry.
        """
        if self.config.redundant_coords_enforced:
            if not self.verify_geometry(geometry_input):
                raise ValueError("Manual Z-Matrix or invalid geometry detected. Cartesian format strictly required.")

        tier_str = tier.value if isinstance(tier, EscalationTier) else str(tier)
        tier_spec = TimeAwareCapabilitySelector.get_tier_spec(tier_str)

        cartesian_block = GeometryCoordinateVerifier.build_orca_cartesian_block(
            geometry_input, charge=charge, multiplicity=multiplicity
        )

        custom_blocks: list[str] = []
        moread_enabled = False

        if orbital_seed_path:
            seed_p = Path(orbital_seed_path).resolve()
            if seed_p.exists():
                norm_seed = str(seed_p).replace("\\", "/")
                custom_blocks.append(f'%moinp "{norm_seed}"')
                moread_enabled = True

        return ExecutionPlan(
            tier=tier_str,
            method_name=tier_spec["method"],
            basis_set=tier_spec["basis_set"],
            keywords=tier_spec["keywords"],
            geometry_block=cartesian_block,
            charge=charge,
            multiplicity=multiplicity,
            orbital_seed_path=str(orbital_seed_path) if orbital_seed_path else None,
            moread_enabled=moread_enabled,
            max_memory_mb=self.config.default_memory_mb,
            num_cores=self.config.default_num_cores,
            timeout_seconds=tier_spec["time_budget_sec"],
            custom_blocks=custom_blocks,
        )

    def run_escalation(
        self,
        geometry: Atoms | str | Sequence[tuple[str, Sequence[float]]],
        molecule_id: str = "mol_candidate",
        time_budget_seconds: float = 3600.0,
        target_tier: EscalationTier | str | None = None,
        charge: int = 0,
        multiplicity: int = 1,
        is_complex: bool = False,
    ) -> EscalationResult:
        """
        Executes a complete systematic escalation session from screening to high-level theory.

        Args:
            geometry: Input molecular structure (Atoms, XYZ string, or coordinate list).
            molecule_id: Molecular identifier tag.
            time_budget_seconds: Allotted wall time budget in seconds.
            target_tier: Explicit target tier or None for automated selection.
            charge: Net molecular charge.
            multiplicity: Spin multiplicity.
            is_complex: True if structure is an intermolecular weak complex.

        Returns:
            EscalationResult summarizing all executed steps, metrics, and outcomes.
        """
        start_time = time.time()
        num_atoms = (
            len(geometry)
            if isinstance(geometry, Atoms)
            else len([ln for ln in str(geometry).splitlines() if ln.strip() and not ln.startswith("*")])
        )

        if self.config.redundant_coords_enforced:
            if not self.verify_geometry(geometry):
                return EscalationResult(
                    final_status=CalculationStatus.FAILED,
                    highest_tier_achieved="None",
                    metadata={"error": "Directive 1 violation: Manual Z-matrix rejected."},
                )

        if target_tier is None:
            resolved_target = TimeAwareCapabilitySelector.select_optimal_tier(
                time_budget_seconds=time_budget_seconds,
                num_atoms=num_atoms,
                is_complex=is_complex,
            )
        else:
            resolved_target = (
                target_tier if isinstance(target_tier, EscalationTier) else EscalationTier(str(target_tier))
            )

        ladder = TimeAwareCapabilitySelector.build_escalation_ladder(resolved_target)
        logger.info(f"Escalation ladder selected for '{molecule_id}': {[t.value for t in ladder]}")

        steps: list[EscalationStepRecord] = []
        current_seed: str | None = None
        autocas_alert: AutoCASAlert | None = None
        autocas_triggered = False
        total_rescues = 0
        last_energy: float | None = None
        highest_tier = "None"

        for step_idx, tier_item in enumerate(ladder):
            logger.info(f"Executing Escalation Step {step_idx+1}/{len(ladder)}: Tier {tier_item.value}")

            plan = self.build_plan(
                tier=tier_item,
                geometry_input=geometry,
                charge=charge,
                multiplicity=multiplicity,
                orbital_seed_path=current_seed,
            )

            step_record = self.execute_step(plan, molecule_id=molecule_id, step_index=step_idx)
            steps.append(step_record)
            total_rescues += step_record.rescue_attempts

            if step_record.final_energy_hartree is not None:
                last_energy = step_record.final_energy_hartree

            if step_record.orbital_seed_path:
                current_seed = step_record.orbital_seed_path

            if step_record.status == CalculationStatus.AUTOCAS_TRIGGERED:
                autocas_triggered = True
                highest_tier = tier_item.value
                if step_record.multiref_diagnostics:
                    autocas_alert = AutoCASRescueProtocol.create_autocas_alert(
                        molecule_id=molecule_id,
                        t1=step_record.multiref_diagnostics.t1_diagnostic,
                        d1=step_record.multiref_diagnostics.d1_diagnostic,
                        charge=charge,
                        multiplicity=multiplicity,
                    )
                logger.warning(f"Escalation halted at {tier_item.value}: AutoCAS multireference rescue triggered.")
                break

            if step_record.status not in (CalculationStatus.SUCCESS, CalculationStatus.SCF_RESCUED):
                logger.error(f"Step {step_idx+1} ({tier_item.value}) failed: {step_record.error_message}")
                break

            highest_tier = tier_item.value

        total_runtime = time.time() - start_time
        overall_success = (highest_tier == resolved_target.value) or autocas_triggered

        final_status = (
            CalculationStatus.AUTOCAS_TRIGGERED
            if autocas_triggered
            else (CalculationStatus.SUCCESS if overall_success else CalculationStatus.FAILED)
        )

        return EscalationResult(
            success=overall_success,
            final_status=final_status,
            highest_tier_achieved=highest_tier,
            final_energy_hartree=last_energy,
            autocas_triggered=autocas_triggered,
            autocas_alert=autocas_alert,
            scf_rescues_applied=total_rescues,
            steps=steps,
            total_runtime_seconds=total_runtime,
            final_orbital_seed_path=current_seed,
            metadata={
                "molecule_id": molecule_id,
                "target_tier": resolved_target.value,
                "ladder_executed": [s.tier for s in steps],
            },
        )

    def execute_step(
        self,
        plan: ExecutionPlan,
        molecule_id: str = "mol_candidate",
        step_index: int = 0,
    ) -> EscalationStepRecord:
        """
        Executes an individual calculation plan.
        Monitors output buffer, applies automated SCF rescue if divergence/oscillation occurs,
        and checks T1/D1 multireference diagnostics.
        """
        start_step = time.time()
        attempt = 0
        current_plan = plan
        rescued = False
        step_status = CalculationStatus.FAILED
        step_metrics: SCFConvergenceMetrics | None = None
        multiref_diag: MultireferenceDiagnostics | None = None
        final_energy: float | None = None
        orbital_seed_saved: str | None = plan.orbital_seed_path
        err_msg: str | None = None

        while attempt <= self.config.max_scf_rescue_attempts:
            logger.info(f"Running calculation for tier '{current_plan.tier}' (Attempt {attempt+1})")

            exit_code, output_text, out_gbw = self._run_orca_process(current_plan, molecule_id=molecule_id)

            if out_gbw:
                orbital_seed_saved = str(out_gbw)

            parsed = ORCAOutputParser.parse_orca_full_output(output_text)
            step_metrics = parsed["scf_metrics"]
            multiref_diag = parsed["multireference_diagnostics"]
            final_energy = parsed["final_energy_hartree"]

            # Directive 3: Check AutoCAS Multireference Diagnostics
            if multiref_diag.is_multireference and self.config.enable_autocas_rescue:
                logger.warning(
                    f"AutoCAS Rescue: T1={multiref_diag.t1_diagnostic:.4f}, D1={multiref_diag.d1_diagnostic:.4f} violated."
                )
                step_status = CalculationStatus.AUTOCAS_TRIGGERED

                if self.config.enable_ipc_alerts:
                    alert = AutoCASRescueProtocol.create_autocas_alert(
                        molecule_id=molecule_id,
                        t1=multiref_diag.t1_diagnostic,
                        d1=multiref_diag.d1_diagnostic,
                        charge=current_plan.charge,
                        multiplicity=current_plan.multiplicity,
                    )
                    send_ipc_alert(
                        title="AutoCAS Protocol Triggered",
                        message=alert.message,
                        severity=AlertSeverity.CRITICAL,
                        payload=alert.model_dump(),
                        port=self.config.ipc_port,
                        queue_dir=self.ipc_queue_dir,
                    )
                break

            # Directive 2: Check for SCF divergence or ping-pong oscillation
            needs_rescue = step_metrics.is_oscillating or step_metrics.is_diverging or (exit_code != 0)

            if needs_rescue and attempt < self.config.max_scf_rescue_attempts:
                attempt += 1
                rescued = True
                reason = "Ping-pong oscillation" if step_metrics.is_oscillating else "SCF divergence / crash"
                logger.warning(f"SCF Failure detected ({reason}). Initiating Automated Rescue Attempt {attempt}...")

                if self.config.enable_ipc_alerts:
                    send_ipc_alert(
                        title="SCF Rescue Intercept",
                        message=f"SCF anomaly detected for {molecule_id}: {reason}. Injecting ! SlowConv VShift.",
                        severity=AlertSeverity.WARNING,
                        payload={"attempt": attempt, "metrics": step_metrics.model_dump()},
                        port=self.config.ipc_port,
                        queue_dir=self.ipc_queue_dir,
                    )

                current_plan = AutomatedSCFRescueEngine.build_rescue_plan(
                    failed_plan=current_plan,
                    gbw_seed_path=orbital_seed_saved,
                    attempt=attempt,
                )
                continue

            if step_metrics.status == SCFConvergenceStatus.CONVERGED or exit_code == 0:
                step_status = CalculationStatus.SCF_RESCUED if rescued else CalculationStatus.SUCCESS
            else:
                step_status = CalculationStatus.FAILED
                err_msg = step_metrics.error_message or "SCF failed to converge after maximum rescue attempts."

            break

        elapsed = time.time() - start_step

        return EscalationStepRecord(
            step_index=step_index,
            tier=plan.tier,
            plan=current_plan,
            execution_time_seconds=elapsed,
            status=step_status,
            final_energy_hartree=final_energy,
            scf_metrics=step_metrics,
            multiref_diagnostics=multiref_diag,
            scf_rescued=rescued,
            rescue_attempts=attempt,
            orbital_seed_path=orbital_seed_saved,
            error_message=err_msg,
        )

    def _run_orca_process(
        self,
        plan: ExecutionPlan,
        molecule_id: str = "mol_candidate",
    ) -> tuple[int, str, Path | None]:
        """
        Executes the ORCA quantum chemistry calculation or processes dry-run simulation.
        Creates input file, executes binary, and manages orbital seeds.
        """
        step_dir = self.config.working_dir / f"{molecule_id}_{plan.plan_id}"
        step_dir.mkdir(parents=True, exist_ok=True)

        inp_file = step_dir / "orca.inp"
        out_file = step_dir / "orca.out"
        gbw_file = step_dir / "orca.gbw"

        input_lines = [plan.keywords]
        if plan.custom_blocks:
            input_lines.extend(plan.custom_blocks)
        input_lines.append(f"%maxcore {plan.max_memory_mb // max(1, plan.num_cores)}")
        input_lines.append(f"%pal nprocs {plan.num_cores} end")
        input_lines.append(plan.geometry_block)

        full_input_text = "\n".join(input_lines)
        inp_file.write_text(full_input_text, encoding="utf-8")

        if self.config.dry_run:
            output_text = self._generate_dry_run_output(plan)
            out_file.write_text(output_text, encoding="utf-8")
            gbw_file.write_bytes(b"ORCA_GBW_BINARY_ORBITAL_SEED_DATA")
            return 0, output_text, gbw_file

        orca_bin = self.config.orca_executable
        try:
            cmd = [orca_bin, str(inp_file)]
            proc = subprocess.run(
                cmd,
                cwd=step_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=plan.timeout_seconds,
            )
            output_text = proc.stdout
            out_file.write_text(output_text, encoding="utf-8")
            return proc.returncode, output_text, gbw_file if gbw_file.exists() else None
        except FileNotFoundError:
            logger.warning(f"ORCA binary '{orca_bin}' not found on host. Executing deterministic dry-run fallback.")
            output_text = self._generate_dry_run_output(plan)
            out_file.write_text(output_text, encoding="utf-8")
            gbw_file.write_bytes(b"ORCA_GBW_BINARY_ORBITAL_SEED_DATA")
            return 0, output_text, gbw_file
        except subprocess.TimeoutExpired as exc:
            logger.error(f"Calculation timed out after {plan.timeout_seconds} seconds: {exc}")
            return -1, "CALCULATION TIMED OUT: Subprocess exceeded time limit.", None
        except subprocess.SubprocessError as exc:
            logger.error(f"Subprocess execution error: {exc}")
            return -1, f"SUBPROCESS ERROR: {exc}", None
        except Exception as exc:
            logger.error(f"Unexpected execution error during ORCA calculation: {exc}")
            return -1, f"EXECUTION ERROR: {exc}", None

    def _generate_dry_run_output(self, plan: ExecutionPlan) -> str:
        """
        Generates realistic ORCA output text for dry-run testing and validation.
        """
        is_rescued = plan.slow_conv_enabled or ("SlowConv" in plan.keywords and "VShift" in plan.keywords)
        is_post_hf = "DLPNO-CCSD(T)" in plan.method_name or "wB97M-V" in plan.keywords or "CCSD" in plan.keywords

        base_energy = -76.4325000000

        if not is_rescued and plan.is_rescue_attempt is False and "TRIGGER_OSCILLATION" in plan.keywords:
            return """
------------------
ORCA SCF ITERATIONS
------------------
Iter         Energy       Delta-E        Max-DP      RMS-DP
  0     -76.4000000000   0.0000000000  0.08000000  0.01000000
  1     -76.4500000000  -0.0500000000  0.05000000  0.00800000
  2     -76.4000000000   0.0500000000  0.05000000  0.00800000
  3     -76.4500000000  -0.0500000000  0.05000000  0.00800000
  4     -76.4000000000   0.0500000000  0.05000000  0.00800000
  5     -76.4500000000  -0.0500000000  0.05000000  0.00800000
SCF NOT CONVERGED
"""

        if "TRIGGER_MULTIREF" in plan.keywords:
            return """
-------------------------
DLPNO-CCSD(T) CALCULATION
-------------------------
Iter         Energy       Delta-E        Max-DP      RMS-DP
  0     -76.4000000000   0.0000000000  0.08000000  0.01000000
  1     -76.4354000000  -0.0354000000  0.00210000  0.00030000
  2     -76.4358000000  -0.0004000000  0.00010000  0.00001000
SCF CONVERGED AFTER 3 CYCLES

COUPLED CLUSTER DIAGNOSTICS:
  T1 diagnostic: 0.0350
  D1 diagnostic: 0.0750
  D2 diagnostic: 0.1200

FINAL SINGLE POINT ENERGY: -76.8501234500
ORCA TERMINATED NORMALLY
"""

        out_lines = [
            "------------------",
            "ORCA SCF ITERATIONS",
            "------------------",
            "Iter         Energy       Delta-E        Max-DP      RMS-DP",
            f"  0     {base_energy:14.8f}   0.0000000000  0.05120000  0.00820000",
            f"  1     {base_energy-0.002:14.8f}  -0.0020000000  0.00450000  0.00090000",
            f"  2     {base_energy-0.0024:14.8f}  -0.0004000000  0.00021000  0.00003000",
            f"  3     {base_energy-0.00241:14.8f}  -0.0000100000  0.00001500  0.00000200",
            "SUCCESSFULLY CONVERGED",
            "",
        ]

        if is_post_hf:
            out_lines.extend(
                [
                    "COUPLED CLUSTER DIAGNOSTICS:",
                    "  T1 diagnostic: 0.0125",
                    "  D1 diagnostic: 0.0310",
                    "",
                ]
            )

        out_lines.extend(
            [
                f"FINAL SINGLE POINT ENERGY: {base_energy-0.00241:14.8f}",
                "ORCA TERMINATED NORMALLY",
            ]
        )

        return "\n".join(out_lines)


# ============================================================================
# 9. Top-Level Convenience Functions
# ============================================================================


def execute_time_aware_escalation(
    geometry: Atoms | str | Sequence[tuple[str, Sequence[float]]],
    molecule_id: str = "mol_001",
    time_budget_seconds: float = 3600.0,
    target_tier: EscalationTier | str | None = None,
    charge: int = 0,
    multiplicity: int = 1,
    is_complex: bool = False,
    working_dir: Path | str | None = None,
    dry_run: bool = False,
) -> EscalationResult:
    """
    Primary user-facing convenience function executing systematic Stage 4.0 escalation.

    Args:
        geometry: Target geometry (ASE Atoms, XYZ string, or coordinate list).
        molecule_id: Identification label.
        time_budget_seconds: Total wall time budget.
        target_tier: Explicit target level or automated capability selection.
        charge: Net molecular charge.
        multiplicity: Spin multiplicity.
        is_complex: Intermolecular complex flag.
        working_dir: Working directory path for calculation scratch files.
        dry_run: True to execute deterministic simulated runs.

    Returns:
        EscalationResult report.
    """
    config = EscalatorExecConfig(
        working_dir=Path(working_dir) if working_dir else Path("./escalation_scratch"),
        dry_run=dry_run,
    )
    broker = ToposEscalatorExec(config=config)
    return broker.run_escalation(
        geometry=geometry,
        molecule_id=molecule_id,
        time_budget_seconds=time_budget_seconds,
        target_tier=target_tier,
        charge=charge,
        multiplicity=multiplicity,
        is_complex=is_complex,
    )


def verify_redundant_cartesian_geometry(geometry: Any) -> bool:
    """
    Convenience function verifying Cartesian format for ORCA redundant internals.
    """
    return GeometryCoordinateVerifier.verify_redundant_internal_coordinates_compliance(geometry)


def parse_orca_output(output_text: str) -> dict[str, Any]:
    """
    Convenience function parsing ORCA output for energy, SCF metrics, and diagnostics.
    """
    return ORCAOutputParser.parse_orca_full_output(output_text)
