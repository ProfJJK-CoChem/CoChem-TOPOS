"""
Unit tests for CoChem-TOPOS Stage 4.0 Time-Aware Capability Selector & Execution Broker
(cochem_topos_escalator_exec.py).

Validates:
1. Redundant Internal Coordinates Verification: Rejection of manual Z-matrices and enforcement of Cartesian format for ORCA delocalized redundant internal coordinates.
2. Automated SCF Rescue: Stream parsing, mathematical ping-pong oscillation detection, energy divergence detection, and automated injection of `! SlowConv VShift` with `.gbw` binary orbital seeds.
3. The AutoCAS Rescue Protocol: Extraction of T1 and D1 multireference diagnostics, mathematical single-reference breakdown detection (T1 > 0.02, D1 > 0.05), workflow halting, state downgrade to `! AutoCAS`, and cross-platform IPC alert dispatching.
4. Cross-Platform IPC Subsystem: Server-client communication, atomic file queue fallback, callback notifications.
5. Time-Aware Capability Selector: Method Matrix ladder generation, time-budget scaling, tier specifications.
6. ToposEscalatorExec Master Broker: Single step execution, multi-stage ladder progression, and automated rescue cascades.

Strictly complies with the Tripartite Air-Gap Policy and Zero-Mock Mandate.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from escalation.cochem_topos_escalator_exec import (
    AlertSeverity,
    AutoCASAlert,
    AutoCASRescueProtocol,
    AutomatedSCFRescueEngine,
    CalculationStatus,
    CrossPlatformIPCAlert,
    CrossPlatformIPCClient,
    CrossPlatformIPCServer,
    EscalationResult,
    EscalationTier,
    EscalatorExecConfig,
    ExecutionPlan,
    FileSocketIPCQueue,
    GeometryCoordinateVerifier,
    ORCAOutputParser,
    SCFConvergenceStatus,
    SCFIterationRecord,
    TimeAwareCapabilitySelector,
    ToposEscalatorExec,
    execute_time_aware_escalation,
    parse_orca_output,
    send_ipc_alert,
    verify_redundant_cartesian_geometry,
)

# ============================================================================
# 1. Tests for Directive 1: Redundant Internal Coordinates & Cartesian Builder
# ============================================================================


class TestDirective1RedundantCartesianVerification:
    """Verifies Cartesian coordinate validation and manual Z-Matrix rejection."""

    def test_verify_ase_atoms_compliance(self) -> None:
        """Confirms ASE Atoms object passes Cartesian verification."""
        atoms = Atoms("H2O", positions=[[0.0, 0.0, 0.0], [0.0, 0.75, -0.47], [0.0, -0.75, -0.47]])
        assert GeometryCoordinateVerifier.verify_redundant_internal_coordinates_compliance(atoms) is True
        assert verify_redundant_cartesian_geometry(atoms) is True

    def test_verify_numpy_and_list_coordinates(self) -> None:
        """Confirms (N, 3) arrays and list of coordinates pass verification."""
        coords_arr = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        assert GeometryCoordinateVerifier.verify_redundant_internal_coordinates_compliance(coords_arr) is True

        coords_list = [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        assert GeometryCoordinateVerifier.verify_redundant_internal_coordinates_compliance(coords_list) is True

    def test_verify_atom_tuples_and_records(self) -> None:
        """Confirms list of (sym, [x,y,z]) and (sym, x, y, z) tuples pass verification."""
        tuple_coords_2 = [("O", [0.0, 0.0, 0.0]), ("H", [0.0, 0.7, 0.0]), ("H", [0.0, -0.7, 0.0])]
        assert GeometryCoordinateVerifier.verify_redundant_internal_coordinates_compliance(tuple_coords_2) is True

        tuple_coords_4 = [("O", 0.0, 0.0, 0.0), ("H", 0.0, 0.7, 0.0), ("H", 0.0, -0.7, 0.0)]
        assert GeometryCoordinateVerifier.verify_redundant_internal_coordinates_compliance(tuple_coords_4) is True

    def test_verify_valid_cartesian_string(self) -> None:
        """Confirms standard Cartesian XYZ text passes verification."""
        cartesian_text = """
        * xyz 0 1
        O   0.000000   0.000000   0.117300
        H   0.000000   0.757200  -0.469200
        H   0.000000  -0.757200  -0.469200
        *
        """
        assert GeometryCoordinateVerifier.verify_redundant_internal_coordinates_compliance(cartesian_text) is True
        valid, msg = GeometryCoordinateVerifier.validate_cartesian_format(cartesian_text)
        assert valid is True
        assert "redundant internal coordinates enabled" in msg.lower()

    def test_reject_forbidden_zmatrix_keywords(self) -> None:
        """Confirms manual Z-Matrix constructs like * gzcoord, * zmat, and internal definitions are rejected."""
        zmat_samples = [
            "* gzcoord 0 1\nO\nH 1 0.96\nH 1 0.96 2 104.5\n*",
            "* zmat 0 1\nC\nO 1 r1\nH 1 r2 2 a1\n*",
            "* internal 0 1\nN 0 0 0\n*",
            "O\nH 1 0.96\nH 1 0.96 2 104.5\nVariables:\nr1=0.96\na1=104.5",
        ]
        for sample in zmat_samples:
            assert (
                GeometryCoordinateVerifier.verify_redundant_internal_coordinates_compliance(sample) is False
            ), f"Failed to reject: {sample}"
            valid, msg = GeometryCoordinateVerifier.validate_cartesian_format(sample)
            assert valid is False
            assert "manual z-matrix" in msg.lower()

    def test_build_orca_cartesian_block_from_atoms(self) -> None:
        """Confirms Cartesian block construction from ASE Atoms."""
        atoms = Atoms("CO2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 1.16], [0.0, 0.0, -1.16]])
        block = GeometryCoordinateVerifier.build_orca_cartesian_block(atoms, charge=0, multiplicity=1)
        assert block.startswith("* xyz 0 1")
        assert block.endswith("*")
        assert "C   " in block
        assert "O   " in block

    def test_build_orca_cartesian_block_with_constraints(self) -> None:
        """Confirms optional %geom constraint block is placed correctly."""
        atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
        constraints = "%geom Constraints { B 0 1 C } end end"
        block = GeometryCoordinateVerifier.build_orca_cartesian_block(
            atoms, charge=0, multiplicity=1, constraints_block=constraints
        )
        assert block.startswith("%geom Constraints")
        assert "* xyz 0 1" in block


# ============================================================================
# 2. Tests for Directive 2: Output Buffer Parsing & Automated SCF Rescue
# ============================================================================


class TestDirective2AutomatedSCFRescue:
    """Verifies output buffer parsing, ping-pong oscillation detection, divergence detection, and rescue injection."""

    def test_parse_scf_iterations_table(self) -> None:
        """Parses standard multi-iteration SCF cycle records."""
        sample_output = """
------------------
ORCA SCF ITERATIONS
------------------
Iter         Energy       Delta-E        Max-DP      RMS-DP
  0     -76.4000000000   0.0000000000  0.08000000  0.01000000
  1     -76.4350000000  -0.0350000000  0.00500000  0.00080000
  2     -76.4358000000  -0.0008000000  0.00030000  0.00005000
  3     -76.4358500000  -0.0000500000  0.00002000  0.00000300
SUCCESSFULLY CONVERGED
FINAL SINGLE POINT ENERGY: -76.4358500000
ORCA TERMINATED NORMALLY
"""
        metrics = ORCAOutputParser.parse_scf_iterations(sample_output)
        assert metrics.iterations_count == 4
        assert metrics.status == SCFConvergenceStatus.CONVERGED
        assert pytest.approx(metrics.final_energy, rel=1e-6) == -76.4358500000
        assert metrics.is_oscillating is False
        assert metrics.is_diverging is False

    def test_detect_ping_pong_2_cycle_oscillation(self) -> None:
        """Confirms 2-cycle ping-pong energy oscillation is mathematically detected."""
        history = [
            SCFIterationRecord(iteration=0, energy_hartree=-76.4000, delta_energy=0.0),
            SCFIterationRecord(iteration=1, energy_hartree=-76.4500, delta_energy=-0.0500),
            SCFIterationRecord(iteration=2, energy_hartree=-76.4000, delta_energy=0.0500),
            SCFIterationRecord(iteration=3, energy_hartree=-76.4500, delta_energy=-0.0500),
            SCFIterationRecord(iteration=4, energy_hartree=-76.4000, delta_energy=0.0500),
            SCFIterationRecord(iteration=5, energy_hartree=-76.4500, delta_energy=-0.0500),
        ]
        is_oscillating, cycle_len = ORCAOutputParser.detect_scf_oscillation(history)
        assert is_oscillating is True
        assert cycle_len == 2

    def test_detect_scf_energy_divergence(self) -> None:
        """Confirms positive energy explosion / divergence is flagged."""
        history = [
            SCFIterationRecord(iteration=0, energy_hartree=-76.4000, delta_energy=0.0),
            SCFIterationRecord(iteration=1, energy_hartree=-75.0000, delta_energy=1.4000),  # Massive positive delta
        ]
        is_diverging, div_step = ORCAOutputParser.detect_scf_divergence(history, threshold_hartree=1.0)
        assert is_diverging is True
        assert div_step == 1

    def test_detect_nan_inf_divergence(self) -> None:
        """Confirms NaN or Inf electronic energy triggers divergence."""
        history = [
            SCFIterationRecord(iteration=0, energy_hartree=-76.4000, delta_energy=0.0),
            SCFIterationRecord(iteration=1, energy_hartree=float("nan"), delta_energy=0.0),
        ]
        is_diverging, div_step = ORCAOutputParser.detect_scf_divergence(history)
        assert is_diverging is True
        assert div_step == 1

    def test_inject_scf_rescue_keywords_slowconv_vshift(self, tmp_path: Path) -> None:
        """Confirms injection of ! SlowConv VShift, ! MOREAD, and %moinp into .inp file."""
        original_inp = """! r2SCAN-3c TightOpt TightSCF
* xyz 0 1
O 0.0 0.0 0.0
H 0.0 0.7 0.0
H 0.0 -0.7 0.0
*
"""
        gbw_seed = tmp_path / "converged_seed.gbw"
        gbw_seed.write_bytes(b"SEED_DATA")

        rescued_inp = AutomatedSCFRescueEngine.inject_scf_rescue_keywords(
            input_content=original_inp,
            gbw_seed_path=gbw_seed,
            rescue_level=1,
        )

        assert "SlowConv" in rescued_inp
        assert "VShift" in rescued_inp
        assert "MOREAD" in rescued_inp
        assert "%moinp" in rescued_inp
        assert "converged_seed.gbw" in rescued_inp

    def test_build_rescue_plan(self, tmp_path: Path) -> None:
        """Confirms build_rescue_plan creates updated ExecutionPlan with rescue flags."""
        failed_plan = ExecutionPlan(
            plan_id="plan_test_01",
            tier="T1-3h",
            method_name="r2SCAN-3c",
            keywords="! r2SCAN-3c TightOpt TightSCF",
            geometry_block="* xyz 0 1\nO 0.0 0.0 0.0\n*",
        )
        gbw_seed = tmp_path / "seed.gbw"
        gbw_seed.touch()

        rescue_plan = AutomatedSCFRescueEngine.build_rescue_plan(
            failed_plan=failed_plan,
            gbw_seed_path=gbw_seed,
            attempt=1,
        )

        assert rescue_plan.is_rescue_attempt is True
        assert rescue_plan.rescue_count == 1
        assert rescue_plan.slow_conv_enabled is True
        assert rescue_plan.vshift_enabled is True
        assert rescue_plan.moread_enabled is True
        assert "SlowConv" in rescue_plan.keywords
        assert "VShift" in rescue_plan.keywords
        assert "MOREAD" in rescue_plan.keywords


# ============================================================================
# 3. Tests for Directive 3: The AutoCAS Rescue Protocol & Multireference Diagnostics
# ============================================================================


class TestDirective3AutoCASRescueProtocol:
    """Verifies T1 and D1 multireference diagnostics parsing, breakdown threshold evaluation, and AutoCAS downgrade."""

    def test_parse_safe_single_reference_diagnostics(self) -> None:
        """Confirms T1 <= 0.02 and D1 <= 0.05 are recognized as safe single-reference."""
        out_text = """
COUPLED CLUSTER ITERATIONS COMPLETE
T1 diagnostic :  0.0142
D1 diagnostic :  0.0321
D2 diagnostic :  0.0540
FINAL SINGLE POINT ENERGY: -76.84321000
"""
        diag = ORCAOutputParser.parse_multireference_diagnostics(out_text)
        assert pytest.approx(diag.t1_diagnostic, rel=1e-4) == 0.0142
        assert pytest.approx(diag.d1_diagnostic, rel=1e-4) == 0.0321
        assert pytest.approx(diag.d2_diagnostic, rel=1e-4) == 0.0540
        assert diag.is_multireference is False
        assert diag.violation_reason is None

    def test_parse_t1_violation_triggers_autocas(self) -> None:
        """Confirms T1 > 0.02 flags multireference breakdown."""
        out_text = """
COUPLED CLUSTER DIAGNOSTICS:
  T1 diagnostic: 0.0245
  D1 diagnostic: 0.0310
"""
        diag = ORCAOutputParser.parse_multireference_diagnostics(out_text)
        assert diag.t1_diagnostic == 0.0245
        assert diag.is_multireference is True
        assert diag.violation_reason is not None
        assert "T1=0.0245 > 0.02" in diag.violation_reason

    def test_parse_d1_violation_triggers_autocas(self) -> None:
        """Confirms D1 > 0.05 flags multireference breakdown."""
        out_text = """
COUPLED CLUSTER DIAGNOSTICS:
  T1 diagnostic: 0.0150
  D1 diagnostic: 0.0620
"""
        diag = ORCAOutputParser.parse_multireference_diagnostics(out_text)
        assert diag.d1_diagnostic == 0.0620
        assert diag.is_multireference is True
        assert diag.violation_reason is not None
        assert "D1=0.0620 > 0.05" in diag.violation_reason

    def test_check_multireference_violation_function(self) -> None:
        """Confirms mathematical boundary tests for T1 and D1."""
        assert AutoCASRescueProtocol.check_multireference_violation(t1=0.019, d1=0.049) is False
        assert AutoCASRescueProtocol.check_multireference_violation(t1=0.021, d1=0.010) is True
        assert AutoCASRescueProtocol.check_multireference_violation(t1=0.010, d1=0.051) is True
        assert AutoCASRescueProtocol.check_multireference_violation(t1=0.030, d1=0.080) is True

    def test_create_autocas_alert_generation(self) -> None:
        """Confirms AutoCASAlert model construction with active space recommendation."""
        alert = AutoCASRescueProtocol.create_autocas_alert(
            molecule_id="biradical_intermediate",
            t1=0.032,
            d1=0.075,
            symbols=["C", "C", "H", "H", "H", "H"],
            charge=0,
            multiplicity=1,
        )
        assert isinstance(alert, AutoCASAlert)
        assert alert.molecule_id == "biradical_intermediate"
        assert alert.downgraded_state == "! AutoCAS"
        assert alert.t1_diagnostic == 0.032
        assert alert.d1_diagnostic == 0.075
        assert "active_electrons" in alert.active_space_recommendation
        assert "active_orbitals" in alert.active_space_recommendation
        assert "! AutoCAS" in alert.suggested_keywords

    def test_generate_autocas_input_block(self) -> None:
        """Confirms CASSCF / NEVPT2 input file generation for downgraded state."""
        geom_block = "* xyz 0 1\nC 0.0 0.0 0.0\n*"
        input_text = AutoCASRescueProtocol.generate_autocas_input_block(
            geometry_block=geom_block,
            active_electrons=6,
            active_orbitals=6,
            basis_set="def2-TZVP",
        )
        assert "CASSCF(6,6)" in input_text
        assert "NEVPT2" in input_text
        assert "%casscf" in input_text
        assert "nel 6" in input_text
        assert "norb 6" in input_text


# ============================================================================
# 4. Tests for Cross-Platform IPC Alert Subsystem
# ============================================================================


class TestCrossPlatformIPCSubsystem:
    """Verifies TCP loopback server, client, file queue, and alert callbacks."""

    def test_file_socket_ipc_queue_push_and_pop(self, tmp_path: Path) -> None:
        """Confirms file socket queue can atomically push and pop JSON alerts."""
        queue_dir = tmp_path / "ipc_queue"
        queue = FileSocketIPCQueue(queue_dir)

        alert = CrossPlatformIPCAlert(
            title="Test Alert",
            message="Testing file queue IPC",
            severity=AlertSeverity.WARNING,
            payload={"key": "value"},
        )

        msg_path = queue.push(alert)
        assert msg_path.exists()

        popped = queue.pop_all()
        assert len(popped) == 1
        assert popped[0].alert_id == alert.alert_id
        assert popped[0].title == "Test Alert"
        assert popped[0].payload["key"] == "value"

        # Queue should now be empty
        assert len(queue.pop_all()) == 0

    def test_cross_platform_ipc_server_and_client(self, tmp_path: Path) -> None:
        """Confirms IPC server starts, client connects via TCP or file queue, and dispatches callbacks."""
        queue_dir = tmp_path / "ipc_queue_server"
        port = 18899  # Ephemeral port to avoid conflicts

        server = CrossPlatformIPCServer(port=port, queue_dir=queue_dir)
        received_alerts: list[CrossPlatformIPCAlert] = []

        def alert_callback(al: CrossPlatformIPCAlert) -> None:
            received_alerts.append(al)

        server.register_callback(alert_callback)
        server.start()

        try:
            client = CrossPlatformIPCClient(port=port, queue_dir=queue_dir)
            test_alert = CrossPlatformIPCAlert(
                title="Multireference Warning",
                message="T1 threshold exceeded",
                severity=AlertSeverity.CRITICAL,
                payload={"t1": 0.028},
            )

            client.send_alert(test_alert)
            time.sleep(0.2)  # Allow event loop dispatch

            assert len(received_alerts) >= 1
            assert received_alerts[-1].title == "Multireference Warning"
            assert received_alerts[-1].severity == AlertSeverity.CRITICAL
            assert received_alerts[-1].payload["t1"] == 0.028
        finally:
            server.stop()

    def test_send_ipc_alert_convenience_function(self, tmp_path: Path) -> None:
        """Confirms send_ipc_alert dispatches and creates valid alert record."""
        queue_dir = tmp_path / "ipc_conv_queue"
        alert = send_ipc_alert(
            title="SCF Rescued",
            message="Applied VShift",
            severity=AlertSeverity.INFO,
            payload={"rescues": 1},
            port=18898,
            queue_dir=queue_dir,
        )
        assert alert.title == "SCF Rescued"
        assert alert.severity == AlertSeverity.INFO


# ============================================================================
# 5. Tests for Time-Aware Capability Selector & Method Matrix Ladder
# ============================================================================


class TestTimeAwareCapabilitySelector:
    """Verifies capability selection, Method Matrix ladder ordering, and time budget allocation."""

    def test_select_optimal_tier_fast_budget(self) -> None:
        """Small budget maps to T1-10s or T1-1min."""
        tier_10s = TimeAwareCapabilitySelector.select_optimal_tier(
            time_budget_seconds=10.0,
            num_atoms=5,
        )
        assert tier_10s == EscalationTier.T1_10S

        tier_1min = TimeAwareCapabilitySelector.select_optimal_tier(
            time_budget_seconds=60.0,
            num_atoms=5,
        )
        assert tier_1min == EscalationTier.T1_1MIN

    def test_select_optimal_tier_high_budget(self) -> None:
        """Long multi-day budget maps to T1-3d high-level DFT / post-HF."""
        tier_3d = TimeAwareCapabilitySelector.select_optimal_tier(
            time_budget_seconds=300000.0,
            num_atoms=10,
        )
        assert tier_3d == EscalationTier.T1_3D

    def test_build_escalation_ladder(self) -> None:
        """Confirms ladder produces ordered progression of tiers."""
        ladder = TimeAwareCapabilitySelector.build_escalation_ladder(
            target_tier=EscalationTier.T1_3H,
            start_tier=EscalationTier.T1_10S,
        )
        expected = [
            EscalationTier.T1_10S,
            EscalationTier.T1_1MIN,
            EscalationTier.T1_30MIN,
            EscalationTier.T1_1H,
            EscalationTier.T1_3H,
        ]
        assert ladder == expected

    def test_get_tier_specifications(self) -> None:
        """Confirms valid specifications returned for each tier."""
        spec_3h = TimeAwareCapabilitySelector.get_tier_spec(EscalationTier.T1_3H)
        assert spec_3h["method"] == "r2SCAN-3c"
        assert "TightSCF" in spec_3h["keywords"]
        assert spec_3h["is_post_hf"] is False

        spec_3d = TimeAwareCapabilitySelector.get_tier_spec(EscalationTier.T1_3D)
        assert "wB97M-V" in spec_3d["method"] or "DLPNO" in spec_3d["method"]
        assert spec_3d["is_post_hf"] is True


# ============================================================================
# 6. Tests for ToposEscalatorExec Master Broker
# ============================================================================


class TestToposEscalatorExecBroker:
    """Verifies end-to-end escalation execution, dry-run simulation, automated rescue, and AutoCAS halts."""

    def test_broker_geometry_verification(self, tmp_path: Path) -> None:
        """Confirms ToposEscalatorExec enforces Cartesian geometries and rejects Z-matrices."""
        config = EscalatorExecConfig(working_dir=tmp_path / "scratch", dry_run=True)
        broker = ToposEscalatorExec(config=config)

        atoms = Atoms("H2O", positions=[[0.0, 0.0, 0.0], [0.0, 0.7, 0.0], [0.0, -0.7, 0.0]])
        assert broker.verify_geometry(atoms) is True

        zmat_bad = "* gzcoord 0 1\nO\nH 1 0.96\nH 1 0.96 2 104.5\n*"
        assert broker.verify_geometry(zmat_bad) is False

    def test_broker_build_plan(self, tmp_path: Path) -> None:
        """Confirms build_plan constructs valid ExecutionPlan."""
        config = EscalatorExecConfig(working_dir=tmp_path / "scratch", dry_run=True)
        broker = ToposEscalatorExec(config=config)

        atoms = Atoms("CO", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 1.13]])
        plan = broker.build_plan(tier=EscalationTier.T1_10S, geometry_input=atoms)

        assert plan.tier == EscalationTier.T1_10S.value
        assert "* xyz 0 1" in plan.geometry_block
        assert "C   " in plan.geometry_block
        assert "O   " in plan.geometry_block

    def test_execute_step_normal_success(self, tmp_path: Path) -> None:
        """Executes a single step under dry-run achieving normal convergence."""
        config = EscalatorExecConfig(working_dir=tmp_path / "scratch", dry_run=True)
        broker = ToposEscalatorExec(config=config)

        atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
        plan = broker.build_plan(tier=EscalationTier.T1_10S, geometry_input=atoms)

        step_record = broker.execute_step(plan, molecule_id="test_h2")
        assert step_record.status == CalculationStatus.SUCCESS
        assert step_record.scf_metrics is not None
        assert step_record.scf_metrics.status == SCFConvergenceStatus.CONVERGED
        assert step_record.final_energy_hartree is not None
        assert step_record.orbital_seed_path is not None

    def test_execute_step_scf_oscillation_rescue(self, tmp_path: Path) -> None:
        """Simulates SCF ping-pong oscillation triggering automated SlowConv VShift rescue."""
        config = EscalatorExecConfig(working_dir=tmp_path / "scratch", dry_run=True)
        broker = ToposEscalatorExec(config=config)

        # Injects TRIGGER_OSCILLATION keyword to simulate initial oscillation failure in dry-run
        plan = ExecutionPlan(
            tier="T1-3h",
            method_name="r2SCAN-3c",
            keywords="! r2SCAN-3c TightOpt TRIGGER_OSCILLATION",
            geometry_block="* xyz 0 1\nO 0.0 0.0 0.0\n*",
        )

        step_record = broker.execute_step(plan, molecule_id="test_rescue_mol")
        # Step should detect oscillation, inject SlowConv VShift and .gbw seed, and successfully rescue
        assert step_record.status == CalculationStatus.SCF_RESCUED
        assert step_record.scf_rescued is True
        assert step_record.rescue_attempts == 1
        assert "SlowConv" in step_record.plan.keywords
        assert "VShift" in step_record.plan.keywords
        assert step_record.plan.slow_conv_enabled is True

    def test_execute_step_autocas_multireference_halt(self, tmp_path: Path) -> None:
        """Simulates post-HF T1 > 0.02 triggering immediate calculation halt and AutoCAS alert."""
        config = EscalatorExecConfig(working_dir=tmp_path / "scratch", dry_run=True)
        broker = ToposEscalatorExec(config=config)

        # Injects TRIGGER_MULTIREF to simulate T1=0.035, D1=0.075 in dry-run
        plan = ExecutionPlan(
            tier="T1-3d",
            method_name="DLPNO-CCSD(T)",
            keywords="! DLPNO-CCSD(T) def2-QZVP TRIGGER_MULTIREF",
            geometry_block="* xyz 0 1\nC 0.0 0.0 0.0\nC 1.4 0.0 0.0\n*",
        )

        step_record = broker.execute_step(plan, molecule_id="biradical_test")
        assert step_record.status == CalculationStatus.AUTOCAS_TRIGGERED
        assert step_record.multiref_diagnostics is not None
        assert step_record.multiref_diagnostics.is_multireference is True
        assert step_record.multiref_diagnostics.t1_diagnostic == 0.035

    def test_run_escalation_full_pipeline(self, tmp_path: Path) -> None:
        """Executes a full systematic escalation ladder run from T1-10s to T1-30min."""
        config = EscalatorExecConfig(working_dir=tmp_path / "scratch", dry_run=True)
        broker = ToposEscalatorExec(config=config)

        atoms = Atoms("H2O", positions=[[0.0, 0.0, 0.0], [0.0, 0.75, -0.47], [0.0, -0.75, -0.47]])
        result = broker.run_escalation(
            geometry=atoms,
            molecule_id="water_dimer_candidate",
            target_tier=EscalationTier.T1_30MIN,
        )

        assert isinstance(result, EscalationResult)
        assert result.success is True
        assert result.final_status == CalculationStatus.SUCCESS
        assert result.highest_tier_achieved == EscalationTier.T1_30MIN.value
        assert len(result.steps) == 3  # T1-10s -> T1-1min -> T1-30min
        assert [s.step_index for s in result.steps] == [0, 1, 2]
        assert result.final_energy_hartree is not None

    def test_execute_time_aware_escalation_convenience_function(self, tmp_path: Path) -> None:
        """Confirms top-level convenience function runs cleanly."""
        atoms = Atoms("CH4", positions=[[0.0, 0.0, 0.0], [0.6, 0.6, 0.6], [0.6, -0.6, -0.6], [-0.6, 0.6, -0.6], [-0.6, -0.6, 0.6]])
        result = execute_time_aware_escalation(
            geometry=atoms,
            molecule_id="methane_test",
            target_tier=EscalationTier.T1_1MIN,
            working_dir=tmp_path / "scratch",
            dry_run=True,
        )
        assert result.success is True
        assert result.highest_tier_achieved == EscalationTier.T1_1MIN.value

    def test_parse_orca_output_convenience_function(self) -> None:
        """Confirms parse_orca_output parses full output dict."""
        sample_out = """
ORCA SCF ITERATIONS
Iter   Energy       Delta-E
  0   -40.500000   0.000000
  1   -40.512000  -0.012000
SUCCESSFULLY CONVERGED
FINAL SINGLE POINT ENERGY: -40.512000
ORCA TERMINATED NORMALLY
"""
        parsed = parse_orca_output(sample_out)
        assert parsed["normal_termination"] is True
        assert pytest.approx(parsed["final_energy_hartree"], rel=1e-5) == -40.512000
        assert parsed["scf_metrics"].status == SCFConvergenceStatus.CONVERGED

    def test_detect_3_cycle_oscillation(self) -> None:
        """Confirms 3-cycle limit cycle oscillation is mathematically recognized."""
        history = [
            SCFIterationRecord(iteration=0, energy_hartree=-76.40, delta_energy=0.0),
            SCFIterationRecord(iteration=1, energy_hartree=-76.45, delta_energy=-0.05),
            SCFIterationRecord(iteration=2, energy_hartree=-76.42, delta_energy=0.03),
            SCFIterationRecord(iteration=3, energy_hartree=-76.40, delta_energy=0.02),
            SCFIterationRecord(iteration=4, energy_hartree=-76.45, delta_energy=-0.05),
            SCFIterationRecord(iteration=5, energy_hartree=-76.42, delta_energy=0.03),
        ]
        is_osc, cycle_len = ORCAOutputParser.detect_scf_oscillation(history)
        assert is_osc is True
        assert cycle_len == 3

    def test_parse_multireference_diagnostics_with_dots(self) -> None:
        """Confirms ORCA dot-formatted summary diagnostics are correctly parsed."""
        orca_dot_sample = """
-------------------------
COUPLED CLUSTER ITERATIONS
-------------------------
T1 diagnostic                           ...   0.0245
D1 diagnostic                           ...   0.0610
D2 diagnostic                           ...   0.1150
FINAL SINGLE POINT ENERGY: -76.84321000
"""
        diag = ORCAOutputParser.parse_multireference_diagnostics(orca_dot_sample)
        assert pytest.approx(diag.t1_diagnostic, rel=1e-4) == 0.0245
        assert pytest.approx(diag.d1_diagnostic, rel=1e-4) == 0.0610
        assert pytest.approx(diag.d2_diagnostic, rel=1e-4) == 0.1150
        assert diag.is_multireference is True

    def test_parse_scf_iterations_with_orbital_energies_table(self) -> None:
        """Confirms non-SCF tables like ORBITAL ENERGIES do not corrupt SCF iteration records."""
        complex_orca_sample = """
------------------
ORCA SCF ITERATIONS
------------------
Iter         Energy       Delta-E        Max-DP      RMS-DP
  0     -76.4000000000   0.0000000000  0.08000000  0.01000000
  1     -76.4350000000  -0.0350000000  0.00500000  0.00080000
SUCCESSFULLY CONVERGED

--------------------
ORBITAL ENERGIES
--------------------
  NO   OCC          E(Eh)            E(eV)
   0   2.0000     -19.2345        -523.40
   1   2.0000      -1.2345         -33.59
   2   2.0000      -0.6543         -17.80
   3   0.0000       0.1234           3.36
"""
        metrics = ORCAOutputParser.parse_scf_iterations(complex_orca_sample)
        assert metrics.iterations_count == 2
        assert metrics.status == SCFConvergenceStatus.CONVERGED
        assert pytest.approx(metrics.final_energy, rel=1e-5) == -76.4350000000

    def test_rescue_plan_deduplication_multiple_attempts(self, tmp_path: Path) -> None:
        """Confirms successive rescue attempts do not accumulate duplicate %moinp and %scf blocks."""
        p0 = ExecutionPlan(
            plan_id="p0",
            tier="T1-3h",
            method_name="r2SCAN-3c",
            keywords="! r2SCAN-3c TightOpt",
            geometry_block="* xyz 0 1\nO 0 0 0\n*",
        )
        seed_path = tmp_path / "seed.gbw"
        seed_path.touch()

        p1 = AutomatedSCFRescueEngine.build_rescue_plan(p0, seed_path, attempt=1)
        p2 = AutomatedSCFRescueEngine.build_rescue_plan(p1, seed_path, attempt=2)
        p3 = AutomatedSCFRescueEngine.build_rescue_plan(p2, seed_path, attempt=3)

        moinp_count_p3 = sum(1 for b in p3.custom_blocks if "%moinp" in b)
        scf_count_p3 = sum(1 for b in p3.custom_blocks if "%scf" in b)

        assert moinp_count_p3 == 1
        assert scf_count_p3 == 1
