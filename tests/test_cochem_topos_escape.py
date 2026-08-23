"""
Unit and integration test suite for CoChem-TOPOS Stage 2.2 Topographic Escape Room.
Zero-Mock Mandate: Uses real ASE Atoms, real calculators (TorchMLFF, EMT, LennardJones),
real optimizers (BFGS, FIRE), real Langevin MD dynamics, real RDKit stereochemistry perception,
real TCP localhost IPC broadcasting, and real HDF5 persistence with FAIR-compliant [M], [D], [E] tags.
"""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.calculators.emt import EMT
from ase.calculators.lj import LennardJones
from ase.constraints import FixBondLengths
from rdkit import Chem
from rdkit.Chem import AllChem

from mechanics.cochem_topos_escape import (
    EscapeConfig,
    EscapeMechanism,
    EscapeResult,
    EscapeRoom,
    EscapeStatus,
    EscapeTelemetryPacket,
    FAIRProvenanceRecord,
    GoodTuringEstimator,
    IPCTelemetryBroadcaster,
    ParityLock,
    PhotochemicalShockEngine,
    ProgressiveLangevinEscape,
    ToposEscapeOrchestrator,
    WignerGuidedEscape,
    WignerModeInfo,
    calculate_rmsd,
    canonical_geometry_hash,
    create_fair_provenance_record,
)
from mechanics.cochem_topos_memory import (
    ToposHDF5MemoryManager,
)
from mechanics.cochem_topos_quench import (
    TorchMLFFCalculator,
)

# ============================================================================
# 1. Pydantic Models and Configuration Tests
# ============================================================================

class TestEscapeDataModels:
    """Tests for Escape room Pydantic models, configurations, and validations."""

    def test_escape_config_defaults_and_validation(self) -> None:
        """Verify default parameters of EscapeConfig."""
        config = EscapeConfig()
        assert config.soft_mode_cutoff_cm1 == 100.0
        assert config.wigner_samples_per_mode == 3
        assert config.wigner_kick_scale == 1.0
        assert config.hessian_delta_angstrom == 0.005
        assert config.thermal_schedule == [300.0, 500.0, 1000.0]
        assert config.langevin_steps_per_stage == 100
        assert config.langevin_dt_fs == 2.0
        assert config.basin_rmsd_threshold == 0.08
        assert config.basin_energy_threshold_ev == 1e-4
        assert config.quench_fmax == 0.05
        assert config.quench_max_steps == 300
        assert config.ipc_streaming_enabled is True
        assert config.save_to_hdf5 is True
        assert config.seed == 42

    def test_escape_config_custom_overrides(self, tmp_path: Path) -> None:
        """Verify custom configuration overrides."""
        custom_db = tmp_path / "custom_escape.h5"
        config = EscapeConfig(
            soft_mode_cutoff_cm1=150.0,
            wigner_samples_per_mode=5,
            wigner_kick_scale=1.5,
            thermal_schedule=[400.0, 800.0],
            langevin_steps_per_stage=50,
            basin_rmsd_threshold=0.12,
            quench_fmax=0.01,
            ipc_port=9999,
            db_path=custom_db,
            seed=123,
        )
        assert config.soft_mode_cutoff_cm1 == 150.0
        assert config.wigner_samples_per_mode == 5
        assert config.wigner_kick_scale == 1.5
        assert config.thermal_schedule == [400.0, 800.0]
        assert config.langevin_steps_per_stage == 50
        assert config.basin_rmsd_threshold == 0.12
        assert config.quench_fmax == 0.01
        assert config.ipc_port == 9999
        assert config.db_path == custom_db
        assert config.seed == 123

    def test_escape_models_serialization(self) -> None:
        """Verify serialization and validation of telemetry and provenance models."""
        # EscapeTelemetryPacket
        packet = EscapeTelemetryPacket(
            step_index=10,
            mechanism="wigner",
            temperature_k=300.0,
            coords=[[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
            energy_hartree=-1.123456,
            max_force_ev_angstrom=0.025,
            coordinate_delta_rmsd=0.15,
            geometry_hash="test_sha256_hash",
        )
        packet_dict = packet.model_dump()
        assert packet_dict["step_index"] == 10
        assert packet_dict["mechanism"] == "wigner"
        assert packet_dict["coordinate_delta_rmsd"] == 0.15

        # FAIRProvenanceRecord
        prov = FAIRProvenanceRecord(
            provenance_id="prov_001",
            parent_hash="hash_parent",
            conformer_hash="hash_conformer",
            method_tag="[M:WIGNER_ESCAPE]",
            data_tag="[D:RMSD:0.12]",
            energy_tag="[E:DELTA_E:-0.05]",
            tags=["[M:WIGNER_ESCAPE]", "[D:RMSD:0.12]"],
        )
        assert prov.provenance_id == "prov_001"
        assert len(prov.tags) == 2

        # EscapeResult
        result = EscapeResult(
            escape_id="esc_01",
            status=EscapeStatus.BREACH_SUCCESS,
            breached=True,
            mechanism_used=EscapeMechanism.WIGNER,
            initial_energy=-1.0,
            quenched_energy=-1.05,
            energy_delta_hartree=-0.05,
            rmsd_from_parent=0.18,
            initial_geometry_hash="hash_a",
            quenched_geometry_hash="hash_b",
            initial_coords=[[0.0, 0.0, 0.0]],
            quenched_coords=[[0.1, 0.1, 0.1]],
            atomic_numbers=[6],
            provenance=prov,
        )
        assert result.breached is True
        assert result.status == EscapeStatus.BREACH_SUCCESS
        assert result.mechanism_used == EscapeMechanism.WIGNER


# ============================================================================
# 2. Cryptographic Provenance & Geometry Hashing Tests
# ============================================================================

class TestCryptographicProvenance:
    """Tests for canonical hashing, RMSD calculation, and FAIR provenance records."""

    def test_canonical_geometry_hash_deterministic(self) -> None:
        """Verify deterministic canonical geometry hashing."""
        z = [1, 1]
        coords1 = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.741234]]
        coords2 = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.741235]]  # differs at 6th decimal
        coords3 = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.850000]]  # differs significantly

        hash1 = canonical_geometry_hash(z, coords1, precision=6)
        hash2 = canonical_geometry_hash(z, coords2, precision=6)
        hash3 = canonical_geometry_hash(z, coords3, precision=6)

        assert isinstance(hash1, str)
        assert len(hash1) == 64  # SHA-256 hex digest length
        assert hash1 == canonical_geometry_hash(z, coords1, precision=6)
        assert hash1 != hash2
        assert hash1 != hash3

    def test_create_fair_provenance_record_tags(self) -> None:
        """Verify [M], [D], [E] FAIR provenance tag construction."""
        prov = create_fair_provenance_record(
            parent_hash="parent_sha256_full_hash",
            conformer_hash="conformer_sha256_full_hash",
            mechanism=EscapeMechanism.LANGEVIN_500K,
            initial_energy_hartree=-1.0,
            quenched_energy_hartree=-1.02,
            rmsd=0.15432,
            converged=True,
            engine_tier="TorchMLFF",
        )
        assert "[M:LANGEVIN_500K]" in prov.method_tag
        assert "[D:PARENT_SHA256:parent_sha256_fu]" in prov.data_tag
        assert "[D:RMSD:0.1543]" in prov.data_tag
        assert "[E:DELTA_E_HARTREE:-0.02000000]" in prov.energy_tag
        assert "[E:ENGINE:TorchMLFF]" in prov.energy_tag
        assert "[E:CONVERGED:True]" in prov.energy_tag

    def test_calculate_rmsd_properties(self) -> None:
        """Verify RMSD metric calculation between identical and displaced geometries."""
        c1 = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]])
        # Identical geometry -> RMSD = 0.0
        assert calculate_rmsd(c1, c1) == pytest.approx(0.0, abs=1e-9)

        # Rigid translation -> Centered RMSD = 0.0
        c1_translated = c1 + np.array([2.5, 3.5, 4.5])
        assert calculate_rmsd(c1, c1_translated) == pytest.approx(0.0, abs=1e-7)

        # Actual coordinate deformation
        c2 = c1.copy()
        c2[1, 2] += 0.5
        rmsd = calculate_rmsd(c1, c2)
        assert rmsd > 0.1


# ============================================================================
# 3. Chiral ParityLock Tests
# ============================================================================

class TestParityLock:
    """Tests for CIP stereocenter verification and 3D tetrahedral scalar triple product fallback."""

    def test_parity_lock_chiral_enantiomer_inversion_detection(self) -> None:
        """
        Verify ParityLock on tetrahedral bromochlorofluoromethane (CHFClBr):
        - Identity and rigid rotation return True.
        - Enantiomer inversion returns False.
        """
        pos_r = [
            [0.0, 0.0, 0.0],       # C (index 0)
            [0.0, 0.0, 1.09],      # H (index 1)
            [1.03, 0.0, -0.36],    # F (index 2)
            [-0.51, 0.89, -0.36],  # Cl (index 3)
            [-0.51, -0.89, -0.36], # Br (index 4)
        ]
        mol_r = Atoms(["C", "H", "F", "Cl", "Br"], positions=pos_r)

        # Inverted enantiomer: swap Cl and Br positions
        pos_s = [
            [0.0, 0.0, 0.0],       # C
            [0.0, 0.0, 1.09],      # H
            [1.03, 0.0, -0.36],    # F
            [-0.51, -0.89, -0.36], # Br at old Cl position
            [-0.51, 0.89, -0.36],  # Cl at old Br position
        ]
        mol_s = Atoms(["C", "H", "F", "Cl", "Br"], positions=pos_s)

        assert ParityLock.verify_invariance(mol_r, mol_r) is True
        assert ParityLock.verify_invariance(mol_r, mol_s) is False

        # Rigid rotation preserves chirality
        mol_r_rot = mol_r.copy()
        mol_r_rot.rotate(45, "y")
        assert ParityLock.verify_invariance(mol_r, mol_r_rot) is True

    def test_parity_lock_alanine_stereocenters(self) -> None:
        """Verify ParityLock on R-alanine vs S-alanine."""
        mol_rdkit_r = Chem.MolFromSmiles("C[C@@H](N)C(=O)O")
        mol_rdkit_r = Chem.AddHs(mol_rdkit_r)
        AllChem.EmbedMolecule(mol_rdkit_r, randomSeed=42)
        conf_r = mol_rdkit_r.GetConformer()
        atoms_ala_r = Atoms(
            [a.GetSymbol() for a in mol_rdkit_r.GetAtoms()],
            positions=conf_r.GetPositions(),
        )

        mol_rdkit_s = Chem.MolFromSmiles("C[C@H](N)C(=O)O")
        mol_rdkit_s = Chem.AddHs(mol_rdkit_s)
        AllChem.EmbedMolecule(mol_rdkit_s, randomSeed=42)
        conf_s = mol_rdkit_s.GetConformer()
        atoms_ala_s = Atoms(
            [a.GetSymbol() for a in mol_rdkit_s.GetAtoms()],
            positions=conf_s.GetPositions(),
        )

        assert ParityLock.verify_invariance(atoms_ala_r, atoms_ala_r) is True
        assert ParityLock.verify_invariance(atoms_ala_r, atoms_ala_s) is False

    def test_parity_lock_3d_tetrahedral_volume_fallback(self) -> None:
        """Verify signed 3D tetrahedral scalar triple product volume fallback (v1 . (v2 x v3))."""
        pos_r = [
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.09],
            [1.03, 0.0, -0.36],
            [-0.51, 0.89, -0.36],
            [-0.51, -0.89, -0.36],
        ]
        mol_r = Atoms(["C", "H", "F", "Cl", "Br"], positions=pos_r)

        pos_s = [
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.09],
            [1.03, 0.0, -0.36],
            [-0.51, -0.89, -0.36],
            [-0.51, 0.89, -0.36],
        ]
        mol_s = Atoms(["C", "H", "F", "Cl", "Br"], positions=pos_s)

        vol_r: dict[int, str] = ParityLock._calculate_tetrahedral_volumes(mol_r)
        vol_s: dict[int, str] = ParityLock._calculate_tetrahedral_volumes(mol_s)

        assert 0 in vol_r
        assert 0 in vol_s
        assert vol_r[0] != vol_s[0]
        assert {vol_r[0], vol_s[0]} == {"R_vol", "S_vol"}

    def test_parity_lock_achiral_molecules(self) -> None:
        """Verify ParityLock returns True for achiral molecules without stereocenters."""
        water = Atoms("H2O", positions=[[0, 0, 0], [0, 0.76, 0.59], [0, -0.76, 0.59]])
        assert ParityLock.verify_invariance(water, water) is True


# ============================================================================
# 4. Good-Turing Completeness Estimator Tests
# ============================================================================

class TestGoodTuringEstimator:
    """Tests for Good-Turing dynamic minimum sample size and coverage tracking."""

    def test_good_turing_dynamic_min_sample_size(self) -> None:
        """Verify dynamic sample size N_min = clamp(15 * 2^min(max(n_rot, 0), 4), 15, 150)."""
        assert GoodTuringEstimator(n_rotatable_bonds=0).get_dynamic_min_sample_size() == 15
        assert GoodTuringEstimator(n_rotatable_bonds=1).get_dynamic_min_sample_size() == 30
        assert GoodTuringEstimator(n_rotatable_bonds=2).get_dynamic_min_sample_size() == 60
        assert GoodTuringEstimator(n_rotatable_bonds=3).get_dynamic_min_sample_size() == 120
        assert GoodTuringEstimator(n_rotatable_bonds=4).get_dynamic_min_sample_size() == 150
        assert GoodTuringEstimator(n_rotatable_bonds=10).get_dynamic_min_sample_size() == 150
        assert GoodTuringEstimator(n_rotatable_bonds=-5).get_dynamic_min_sample_size() == 15

    def test_good_turing_coverage_calculation(self) -> None:
        """Verify Good-Turing coverage formula C = 1 - (N_1 / N) with sample size gating."""
        estimator = GoodTuringEstimator(target_coverage=0.95, n_rotatable_bonds=0)
        # Below N_min=15, coverage returns 0.0
        estimator.update(["basin_1", "basin_2"])
        assert estimator.calculate_coverage() == 0.0

        # Reach N=15 with 15 singletons -> C = 1 - (15 / 15) = 0.0
        estimator.update([f"b_{i}" for i in range(13)])
        assert sum(estimator.basin_counts.values()) == 15
        assert estimator.calculate_coverage() == 0.0

        # Redundant distribution: N=20, N_1=0 -> C = 1.0
        estimator_red = GoodTuringEstimator(target_coverage=0.95, n_rotatable_bonds=0)
        estimator_red.update(["basin_A"] * 10 + ["basin_B"] * 10)
        assert estimator_red.calculate_coverage() == 1.0

    def test_good_turing_consecutive_converged_batches(self) -> None:
        """Verify 3 consecutive batches required for is_converged() and reset on drop."""
        estimator = GoodTuringEstimator(target_coverage=0.90, n_rotatable_bonds=0)
        assert estimator.is_converged() is False

        # Batch 1: C=1.0 -> count = 1
        estimator.update(["basin_A"] * 15)
        assert estimator.calculate_coverage() == 1.0
        assert estimator.consecutive_converged_batches == 1
        assert estimator.is_converged() is False

        # Batch 2: C=1.0 -> count = 2
        estimator.update(["basin_A"] * 5)
        assert estimator.calculate_coverage() == 1.0
        assert estimator.consecutive_converged_batches == 2
        assert estimator.is_converged() is False

        # Batch 3: C=1.0 -> count = 3 -> CONVERGED
        estimator.update(["basin_A"] * 5)
        assert estimator.calculate_coverage() == 1.0
        assert estimator.consecutive_converged_batches == 3
        assert estimator.is_converged() is True

        # Drop below threshold with singletons -> reset
        estimator.update([f"singleton_{i}" for i in range(15)])
        cov = estimator.calculate_coverage()
        assert cov < 0.90
        assert estimator.consecutive_converged_batches == 0
        assert estimator.is_converged() is False


# ============================================================================
# 5. Wigner-Guided Escape Engine Tests
# ============================================================================

class TestWignerGuidedEscape:
    """Tests for pseudo-Hessian calculation, normal mode analysis, and Wigner sampling."""

    def test_pseudo_hessian_calculation(self) -> None:
        """Verify finite-difference pseudo-Hessian calculation on real physical system."""
        atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
        atoms.calc = LennardJones(sigma=0.74, epsilon=1.0)

        wigner = WignerGuidedEscape()
        H = wigner.calculate_pseudo_hessian(atoms, delta=0.005)

        assert H.shape == (6, 6)
        # Symmetrized
        assert np.allclose(H, H.T, atol=1e-7)
        # Non-trivial non-zero elements
        assert np.max(np.abs(H)) > 1e-4

    def test_normal_mode_analysis_frequencies(self) -> None:
        """Verify mass-weighted normal mode diagonalization and frequency conversion."""
        atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
        atoms.calc = LennardJones(sigma=0.74, epsilon=1.0)

        wigner = WignerGuidedEscape(EscapeConfig(soft_mode_cutoff_cm1=5000.0))
        analysis = wigner.analyze_normal_modes(atoms)

        assert len(analysis.frequencies_cm1) == 6
        assert len(analysis.modes) == 6
        for mode in analysis.modes:
            assert isinstance(mode.frequency_cm1, float)
            assert len(mode.eigenvector) == 2
            assert len(mode.eigenvector[0]) == 3

    def test_wigner_phase_space_sampling_displacement(self) -> None:
        """Verify deterministic Wigner ground-state phase space displacement."""
        atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
        atoms.calc = LennardJones(sigma=0.74, epsilon=1.0)

        wigner = WignerGuidedEscape(EscapeConfig(seed=42))
        mode = WignerModeInfo(
            mode_index=0,
            frequency_cm1=80.0,  # Soft mode
            is_soft_mode=True,
            eigenvector=[[0.0, 0.0, 0.7071], [0.0, 0.0, -0.7071]],
        )

        perturbed = wigner.sample_wigner_displacement(atoms, mode, scale=1.0)
        assert perturbed is not None
        assert isinstance(perturbed, Atoms)
        assert len(perturbed) == 2
        # Displaced from original positions
        assert not np.allclose(atoms.get_positions(), perturbed.get_positions(), atol=1e-4)

    def test_wigner_missing_calculator_raises_error(self) -> None:
        """Verify calculate_pseudo_hessian raises ValueError if no calculator is attached."""
        atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
        atoms.calc = None

        wigner = WignerGuidedEscape()
        with pytest.raises(ValueError, match="Cannot compute pseudo-Hessian"):
            wigner.calculate_pseudo_hessian(atoms)


# ============================================================================
# 6. Progressive Langevin Thermal Auto-Tuning Tests
# ============================================================================

class TestProgressiveLangevinEscape:
    """Tests for progressive Langevin thermal schedule, SHAKE constraints, and explosion traps."""

    def test_shake_constraints_application(self) -> None:
        """Verify explicit SHAKE constraints for rigid water solvent O-H bonds."""
        langevin = ProgressiveLangevinEscape()

        # Water with O-H bonds < 1.1 Å
        water = Atoms(["O", "H", "H"], positions=[[0.0, 0.0, 0.0], [0.0, 0.76, 0.59], [0.0, -0.76, 0.59]])
        constraints = langevin._apply_shake_constraints(water)
        assert len(constraints) == 1
        assert isinstance(constraints[0], FixBondLengths)
        assert len(constraints[0].pairs) == 2

        # Molecule without O-H bonds (methane CH4)
        methane = Atoms(
            "CH4",
            positions=[
                [0.0, 0.0, 0.0],
                [0.63, 0.63, 0.63],
                [-0.63, -0.63, 0.63],
                [-0.63, 0.63, -0.63],
                [0.63, -0.63, -0.63],
            ],
        )
        no_constraints = langevin._apply_shake_constraints(methane)
        assert len(no_constraints) == 0

    def test_langevin_thermal_shock_300k_execution(self) -> None:
        """Verify deterministic Langevin MD thermal shock updates coordinates."""
        langevin = ProgressiveLangevinEscape(EscapeConfig(seed=42))
        atoms = Atoms("H2O", positions=[[0.0, 0.0, 0.0], [0.0, 0.76, 0.59], [0.0, -0.76, 0.59]])
        atoms.calc = LennardJones(sigma=1.0, epsilon=0.1)

        init_pos = atoms.get_positions().copy()
        result = langevin.execute_thermal_shock_stage(atoms, temperature_k=300.0, steps=20, dt_fs=1.0)

        assert result is not None
        assert isinstance(result, Atoms)
        assert not np.allclose(init_pos, result.get_positions(), atol=1e-4)

    def test_langevin_explosion_trap(self) -> None:
        """Verify explosion trap triggers when atoms violate minimum distance (< 0.4 Å)."""
        langevin = ProgressiveLangevinEscape()
        exploded_atoms = Atoms(["O", "H"], positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.2]])
        exploded_atoms.calc = LennardJones()

        result = langevin.execute_thermal_shock_stage(exploded_atoms, temperature_k=300.0, steps=10, dt_fs=1.0)
        assert result is None


# ============================================================================
# 7. Photochemical Shock / MECP Engine Tests
# ============================================================================

class TestPhotochemicalShockEngine:
    """Tests for honest engine routing and ORCA TD-DFT input formatting."""

    def test_orca_mecp_input_formatting(self) -> None:
        """Verify quantum chemistry input deck formatting for ORCA TD-DFT MECP."""
        atoms = Atoms(["H", "H"], positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
        orca_inp = PhotochemicalShockEngine.format_orca_mecp_input(atoms, excited_state=2)

        assert "! B3LYP def2-SVP" in orca_inp
        assert "%tddft" in orca_inp
        assert "iroot 2" in orca_inp
        assert "nroots 3" in orca_inp
        assert "mecp true" in orca_inp
        assert "H 0.00000 0.00000 0.00000" in orca_inp
        assert "H 0.00000 0.00000 0.74000" in orca_inp

    def test_photochemical_shock_honest_failure_without_binary(self) -> None:
        """Verify honest RuntimeError when neither PySCF nor ORCA binary is installed in PATH."""
        atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
        with pytest.raises(RuntimeError, match="Honest MECP optimization failed"):
            PhotochemicalShockEngine.execute_photochemical_shock(atoms, excited_state=1)


# ============================================================================
# 8. Cross-Platform IPC Telemetry Broadcaster Tests
# ============================================================================

class TestIPCTelemetryBroadcaster:
    """Tests for localhost TCP socket streaming and callback dispatch."""

    def test_ipc_broadcaster_lifecycle_and_callback(self) -> None:
        """Verify IPC server socket initialization, ephemeral port, and callback dispatch."""
        broadcaster = IPCTelemetryBroadcaster(port=0)
        assert broadcaster.is_running is True
        assert broadcaster.active_port > 0

        received_packets: list[EscapeTelemetryPacket] = []
        broadcaster.register_callback(lambda p: received_packets.append(p))

        packet = EscapeTelemetryPacket(
            step_index=1,
            mechanism="wigner",
            coords=[[0.0, 0.0, 0.0]],
            coordinate_delta_rmsd=0.05,
            geometry_hash="dummy_hash_for_test",
        )
        broadcaster.broadcast(packet)

        assert len(received_packets) == 1
        assert received_packets[0].step_index == 1
        assert received_packets[0].mechanism == "wigner"

        broadcaster.close()
        assert broadcaster.is_running is False

    def test_ipc_broadcaster_tcp_socket_client_streaming(self) -> None:
        """Verify real TCP client socket connects and receives streamed JSON packets."""
        with IPCTelemetryBroadcaster(port=0) as broadcaster:
            port = broadcaster.active_port

            # Connect client socket
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect(("127.0.0.1", port))
            time.sleep(0.05)  # Allow accept loop to process

            packet = EscapeTelemetryPacket(
                step_index=42,
                mechanism="langevin_500k",
                coords=[[1.0, 2.0, 3.0]],
                geometry_hash="test_tcp_stream_hash",
            )
            broadcaster.broadcast(packet)

            client.settimeout(2.0)
            data = client.recv(4096).decode("utf-8")
            client.close()

            assert len(data) > 0
            parsed = json.loads(data.strip().split("\n")[0])
            assert parsed["step_index"] == 42
            assert parsed["mechanism"] == "langevin_500k"


# ============================================================================
# 9. Topographic Escape Room Orchestrator Tests
# ============================================================================

class TestToposEscapeOrchestrator:
    """Tests for multi-tier escape workflow and FAIR HDF5 provenance integration."""

    def test_escape_orchestrator_wigner_and_langevin_workflow(self, tmp_path: Path) -> None:
        """Verify full Escape Room orchestrator workflow with real TorchMLFF calculator."""
        db_file = tmp_path / "test_escape_landscape.h5"
        config = EscapeConfig(
            soft_mode_cutoff_cm1=2000.0,
            wigner_samples_per_mode=2,
            thermal_schedule=[300.0, 500.0],
            langevin_steps_per_stage=20,
            basin_rmsd_threshold=0.02,
            basin_energy_threshold_ev=1e-5,
            save_to_hdf5=True,
            db_path=db_file,
            seed=42,
        )

        atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]])
        atoms.calc = TorchMLFFCalculator()

        orchestrator = ToposEscapeOrchestrator(config=config)
        result = orchestrator.run_escape_search(atoms, escape_id="test_escape_run_01")

        assert isinstance(result, EscapeResult)
        assert result.escape_id == "test_escape_run_01"
        assert result.initial_energy is not None
        assert result.quenched_energy is not None
        assert len(result.quenched_coords) == 2

        # Verify HDF5 database provenance persistence
        if result.breached:
            assert db_file.exists()
            db_mgr = ToposHDF5MemoryManager(db_path=db_file)
            saved_geom = db_mgr.read_geometry("test_escape_run_01")
            assert saved_geom is not None
            assert saved_geom.geom_id == "test_escape_run_01"
            assert "provenance" in saved_geom.metadata

    def test_escape_orchestrator_metallic_cluster_emt(self, tmp_path: Path) -> None:
        """Verify Escape Room on metallic cluster (Cu2) with real EMT calculator."""
        db_file = tmp_path / "test_emt_escape.h5"
        config = EscapeConfig(
            soft_mode_cutoff_cm1=1000.0,
            wigner_samples_per_mode=2,
            thermal_schedule=[300.0],
            langevin_steps_per_stage=15,
            basin_rmsd_threshold=0.01,
            basin_energy_threshold_ev=1e-5,
            save_to_hdf5=True,
            db_path=db_file,
            seed=99,
        )

        atoms = Atoms(["Cu", "Cu"], positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 2.22]])
        atoms.calc = EMT()

        orchestrator = ToposEscapeOrchestrator(config=config)
        result = orchestrator.run_escape_search(atoms, escape_id="cu2_escape")

        assert isinstance(result, EscapeResult)
        assert result.atomic_numbers == [29, 29]

    def test_legacy_escape_room_interface_wrapper(self) -> None:
        """Verify backward compatibility of EscapeRoom class wrapper."""
        room = EscapeRoom(temperature_k=300.0, seed=42)
        atoms = Atoms("H2O", positions=[[0.0, 0.0, 0.0], [0.0, 0.76, 0.59], [0.0, -0.76, 0.59]])
        atoms.calc = LennardJones(sigma=1.0, epsilon=0.1)

        shocked = room.execute_thermal_shock(atoms, steps=20, dt_fs=1.0)
        assert shocked is not None
        assert isinstance(shocked, Atoms)
        assert len(shocked) == 3
