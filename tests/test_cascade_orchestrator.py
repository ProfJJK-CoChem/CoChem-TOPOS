"""
CoChem-TOPOS: Unit and Verification Tests for Method Matrix Cascade Orchestrator.
Validates v4 T1 search escalation routing, SWMR HDF5 persistence, real Hessian calculation,
and strict anti-spoofing gradient validation according to CoChem directives.
"""

import logging
from pathlib import Path
from unittest import mock
import h5py
import numpy as np
import pydantic
import pytest
from ase.calculators.lj import LennardJones
from ase.io import read as ase_read
import io

from cascade_engine.cochem_topos_cascade_orchestrator import (
    CascadeConfig,
    CascadeOrchestrator,
    GradientPayload,
)

logger = logging.getLogger(__name__)


def _fake_broker_execute(cmd: str) -> int:
    """Simulates SubprocessBroker execution by generating physical ORCA output."""
    if ">" in cmd:
        out_path_str = cmd.split(">")[-1].strip()
        out_path = Path(out_path_str)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            "ORCA TERMINATED NORMALLY\n"
            "FINAL SINGLE POINT ENERGY      -76.4253102345\n"
        )
    return 0


@mock.patch("cascade_engine.cochem_topos_cascade_orchestrator.MACE_OFF24M_AVAILABLE", True)
@mock.patch("cascade_engine.cochem_topos_cascade_orchestrator.MACEOFF24mCalculator", side_effect=lambda *args, **kwargs: LennardJones(), create=True)
@mock.patch("cascade_engine.cochem_topos_cascade_orchestrator.get_honest_xtb_calculator", side_effect=lambda *args, **kwargs: LennardJones())
@mock.patch("cascade_engine.cochem_topos_cascade_orchestrator.SubprocessBroker.execute", side_effect=_fake_broker_execute, create=True)
def test_topos04_v4_t1_search_escalation_routing(
    mock_broker: mock.MagicMock,
    mock_xtb: mock.MagicMock,
    mock_mace: mock.MagicMock,
    tmp_path: Path,
) -> None:
    """
    Verify TOPOS-04: Tier routing for v4 T1 search escalation.
    Tests end-to-end geometry processing, method matrix tier sequence,
    physical Hessian evaluation with temporary directory lifecycle,
    and SWMR HDF5 dataset persistence.
    """
    config = CascadeConfig(artifact_dir=tmp_path, complex_flag=True)
    orchestrator = CascadeOrchestrator(config=config)

    tier_seq = orchestrator._get_tier_sequence(complex_flag=True)
    assert len(tier_seq) == 5

    methods = [t.method for t in tier_seq]
    assert methods == [
        "Hand Topology",
        "GOAT XTB2",
        "GOAT-EXPLORE ExtOpt",
        "CREST NCI",
        "r2SCAN-3c",
    ]

    tier_names = [t.tier_name for t in tier_seq]
    assert tier_names == ["T1-10s", "T1-1min", "T1-30min", "T1-1h", "T1-3h"]

    # Process a water geometry through the cascade
    xyz_data = "3\nWater\nO 0.0 0.0 0.0\nH 0.0 0.76 0.59\nH 0.0 -0.76 0.59\n"
    res = orchestrator.process_geometry("test_geom_01", xyz_data)

    # 1. Assertions on OrchestratorPayload output
    assert res.geom_id == "test_geom_01"
    assert res.final_status == "SUCCESS"
    assert res.highest_tier == 5
    assert res.final_geometry == xyz_data

    # 2. Mock call verifications
    assert mock_xtb.call_count >= 1, "get_honest_xtb_calculator must be invoked for XTB tiers."
    assert mock_mace.call_count >= 1, "MACEOFF24mCalculator must be invoked for T1-30min MLFF exploration."
    assert mock_broker.call_count >= 1, "SubprocessBroker must be invoked for T1-3h ORCA execution."

    # 3. HDF5 dataset and attribute persistence verification
    orchestrator.serializer.close()
    assert orchestrator.hdf5_path.exists(), "Cascade HDF5 persistence file must exist on disk."

    with h5py.File(orchestrator.hdf5_path, "r") as h5_file:
        assert "test_geom_01" in h5_file, "Root geometry ID group must exist in HDF5."
        geom_group = h5_file["test_geom_01"]

        for tier_id in ["1", "2", "3", "4", "5"]:
            assert tier_id in geom_group, f"Tier {tier_id} group missing from HDF5 datastore."
            tier_grp = geom_group[tier_id]

            # Verify electronic energy is physically present and non-zero
            energy = tier_grp.attrs.get("electronic_energy_hartree")
            assert energy is not None, f"Tier {tier_id} missing electronic_energy_hartree attribute."
            assert energy != 0.0, f"Tier {tier_id} energy must not be 0.0 (anti-spoofing directive)."

            # Verify serialized geometry byte string
            assert "geometry_xyz" in tier_grp, f"Tier {tier_id} missing geometry_xyz dataset."
            saved_geom = tier_grp["geometry_xyz"][()].decode("utf-8")
            assert "Water" in saved_geom or "O" in saved_geom

            # Tiers 1, 2, and 4 calculate forces and numerical Hessians via LennardJones
            if tier_id in ["1", "2", "4"]:
                assert "gradient_matrix" in tier_grp, f"Tier {tier_id} missing gradient_matrix dataset."
                grad = np.array(tier_grp["gradient_matrix"])
                assert grad.shape == (3, 3), f"Tier {tier_id} gradient must have shape (3, 3)."
                assert not np.all(grad == 0.0), f"Tier {tier_id} gradient must not be all zeros."

                assert "hessian_matrix" in tier_grp, f"Tier {tier_id} missing hessian_matrix dataset."
                hess = np.array(tier_grp["hessian_matrix"])
                assert hess.shape == (9, 9), f"Tier {tier_id} Hessian must have shape (9, 9)."
                assert not np.all(hess == 0.0), f"Tier {tier_id} Hessian must not be all zeros."

            # Tier 3 (MACE-OFF24m) provides forces
            elif tier_id == "3":
                assert "gradient_matrix" in tier_grp, "Tier 3 missing gradient_matrix dataset."
                grad = np.array(tier_grp["gradient_matrix"])
                assert grad.shape == (3, 3), "Tier 3 gradient must have shape (3, 3)."
                assert not np.all(grad == 0.0), "Tier 3 gradient must not be all zeros."

            # Tier 5 (r2SCAN-3c) parses single-point energy from physical ORCA output
            elif tier_id == "5":
                assert energy == pytest.approx(-76.4253102345), (
                    f"Tier 5 energy {energy} does not match expected ORCA single point energy."
                )


def test_compute_true_hessian_directory_lifecycle(tmp_path: Path) -> None:
    """
    Verify that _compute_true_hessian calculates the 3Nx3N Hessian matrix,
    creates the temporary calculation directory, and cleans it up after completion.
    """
    config = CascadeConfig(artifact_dir=tmp_path, complex_flag=False)
    orchestrator = CascadeOrchestrator(config=config)

    xyz_data = "2\nH2\nH 0.0 0.0 0.0\nH 0.0 0.0 0.74\n"
    atoms = ase_read(io.StringIO(xyz_data), format="xyz")
    calc = LennardJones()

    prefix = "test_lifecycle"
    expected_vib_dir = Path(f"vib_tmp_{prefix}")

    hessian = orchestrator._compute_true_hessian(atoms, calc, prefix)

    # 1. Validate computed Hessian matrix shape and non-zero values
    hessian_arr = np.array(hessian)
    assert hessian_arr.shape == (6, 6), f"Expected 6x6 Hessian for H2 molecule, got {hessian_arr.shape}."
    assert not np.all(hessian_arr == 0.0), "Computed Hessian must contain non-zero force constants."

    # 2. Validate temporary calculation directory was cleanly removed
    assert not expected_vib_dir.exists(), f"Temporary directory {expected_vib_dir} must be cleaned up."


@pytest.mark.parametrize(
    "spoofed_gradient",
    [
        [[0.0, 0.0, 0.0]],
        [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        [0.0, 0.0, 0.0],
        [0.0],
        [0.0, 0.0],
        [[0.0, 0.0], [0.0, 0.0]],
    ],
)
def test_gradient_payload_anti_spoofing_rejection(spoofed_gradient: list) -> None:
    """
    Verify Pydantic validation strictly rejects spoofed all-zero gradients across
    various tensor dimensions (1D, 2D, multi-atom arrays) per Anti-Spoofing Directive.
    """
    with pytest.raises(pydantic.ValidationError, match="Fake 0.0 gradients are strictly prohibited"):
        GradientPayload(energy=-1.0, gradient=spoofed_gradient, hessian=[])


@pytest.mark.parametrize(
    "valid_gradient",
    [
        [],
        [[1.0, 2.0, 3.0]],
        [[0.01, -0.02, 0.005], [0.0, 0.01, -0.005], [-0.01, 0.01, 0.0]],
        [[1e-12, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        [[0.0, 0.0, 1e-8]],
        [1e-15, 0.0, 0.0],
        [-0.5, 0.2, 0.1],
    ],
)
def test_gradient_payload_valid_cases(valid_gradient: list) -> None:
    """
    Verify GradientPayload accepts valid non-zero gradients, small floating-point
    gradients above numerical threshold, and legitimately empty gradient lists.
    """
    payload = GradientPayload(energy=-76.4, gradient=valid_gradient, hessian=[])
    assert payload.energy == -76.4
    assert payload.gradient == valid_gradient
    assert payload.scf_tole == 1e-7
