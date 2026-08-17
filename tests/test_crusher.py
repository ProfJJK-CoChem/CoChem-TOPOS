from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest import mock

import h5py
import numpy as np
from ase import Atoms
from ase.calculators.lj import LennardJones
from scipy.spatial.transform import Rotation

from core_engine.cochem_topos_crusher import ToposCrusher

logger = logging.getLogger(__name__)


def test_topos_crusher_distance_matrix_hash(tmp_path: Path) -> None:
    """Verify distance matrix hash calculation and invariant behavior."""
    atoms = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)])
    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_hash.h5"))
    hash_val = crusher.distance_matrix_hash(atoms)
    assert isinstance(hash_val, np.ndarray)
    assert len(hash_val) == 50
    assert np.sum(hash_val) > 0.0

    # Test single-atom / empty case returning zero histogram
    single_atom = Atoms("H", positions=[(0, 0, 0)])
    zero_hash = crusher.distance_matrix_hash(single_atom)
    assert isinstance(zero_hash, np.ndarray)
    assert np.all(zero_hash == 0.0)


def test_distance_matrix_hash_rigid_invariance(tmp_path: Path) -> None:
    """Verify distance matrix hash is invariant under rigid translation and rotation."""
    atoms1 = Atoms(
        "CH4",
        positions=[
            [0.0, 0.0, 0.0],
            [0.63, 0.63, 0.63],
            [-0.63, -0.63, 0.63],
            [-0.63, 0.63, -0.63],
            [0.63, -0.63, -0.63],
        ],
    )
    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_invariance.h5"))
    hash1 = crusher.distance_matrix_hash(atoms1)

    # Rigid translation
    atoms_translated = atoms1.copy()
    atoms_translated.positions += np.array([12.5, -7.3, 4.2])
    hash_trans = crusher.distance_matrix_hash(atoms_translated)
    np.testing.assert_allclose(hash1, hash_trans, atol=1e-6)

    # Rigid 3D rotation
    atoms_rotated = atoms1.copy()
    rot = Rotation.from_euler("xyz", [35, 45, 60], degrees=True)
    atoms_rotated.positions = rot.apply(atoms_rotated.positions)
    hash_rot = crusher.distance_matrix_hash(atoms_rotated)
    np.testing.assert_allclose(hash1, hash_rot, atol=1e-6)

    # Jiggle-quench RMSD between identical / rigidly transformed conformers is 0.0
    jq_self = crusher.jiggle_quench_rmsd(atoms1, atoms_translated)
    assert np.isclose(jq_self, 0.0, atol=1e-6)

    # JQ RMSD between different geometries is > 0
    atoms_perturbed = atoms1.copy()
    atoms_perturbed.positions[1] += np.array([0.5, 0.0, 0.0])
    jq_diff = crusher.jiggle_quench_rmsd(atoms1, atoms_perturbed)
    assert jq_diff > 0.0


@mock.patch(
    "core_engine.cochem_topos_crusher.get_honest_xtb_calculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
)
@mock.patch(
    "core_engine.cochem_topos_crusher.MACEOFF24mCalculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
    create=True,
)
def test_goat_conformer_generation(
    mock_mace: mock.MagicMock,
    mock_xtb: mock.MagicMock,
    tmp_path: Path,
) -> None:
    """Verify GOAT conformer generation returns expected count and geometry sizes."""
    atoms = Atoms(
        "H2O",
        positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)],
        cell=[10, 10, 10],
        pbc=True,
    )
    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_goat.h5"))
    conformers = crusher._execute_goat_conformer_generation(atoms, num_conformers=3)
    assert len(conformers) == 3
    for conf in conformers:
        assert len(conf) == 3


@mock.patch(
    "core_engine.cochem_topos_crusher.get_honest_xtb_calculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
)
@mock.patch(
    "core_engine.cochem_topos_crusher.MACEOFF24mCalculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
    create=True,
)
def test_topos01_inhess_xtb2_preconditioner(
    mock_mace: mock.MagicMock,
    mock_xtb: mock.MagicMock,
    tmp_path: Path,
) -> None:
    """Verify TOPOS-01: Prohibited Calc_Hess=True removed and replaced with InHess XTB2 preconditioner.

    Uses CH4 (n_atoms=5 > 3) to ensure tangential kicks are executed and tested.
    """
    atoms = Atoms(
        "CH4",
        positions=[
            [0.0, 0.0, 0.0],
            [0.63, 0.63, 0.63],
            [-0.63, -0.63, 0.63],
            [-0.63, 0.63, -0.63],
            [0.63, -0.63, -0.63],
        ],
        cell=[10, 10, 10],
        pbc=True,
    )
    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_topos01.h5"))
    worker_out = crusher._goat_single_worker(atoms, kick_magnitude=0.5)

    assert worker_out.info.get("InHess") == "XTB2"
    assert "Calc_Hess" not in worker_out.info or worker_out.info["Calc_Hess"] is not True
    # Validate tangential kick perturbed coordinates from initial
    assert not np.allclose(worker_out.positions, atoms.positions)


@mock.patch("shutil.which", return_value=None)
@mock.patch(
    "core_engine.cochem_topos_crusher.get_honest_xtb_calculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
)
@mock.patch(
    "core_engine.cochem_topos_crusher.MACEOFF24mCalculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
    create=True,
)
def test_topos02_two_stage_deduplication_protocol(
    mock_mace: mock.MagicMock,
    mock_xtb: mock.MagicMock,
    mock_which: mock.MagicMock,
    tmp_path: Path,
) -> None:
    """Verify TOPOS-02: Two-Stage Deduplication Protocol with CREST cross-check and CREGEN referee deduplication."""
    crusher = ToposCrusher(bthr=0.001, hdf5_path=str(tmp_path / "test_topos02.h5"))
    atoms1 = Atoms(
        "H2O",
        positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)],
        cell=[10, 10, 10],
        pbc=True,
    )
    res1 = crusher.process_conformer(atoms1, energy_kcal=-10.0)
    assert res1["status"] == "accepted"

    # Secondary CREST crosscheck fallback execution test
    crest_ensemble = crusher._execute_crest_secondary_crosscheck(atoms1, num_conformers=3)
    assert len(crest_ensemble) > 0

    # Near-identical conformer should trigger CREGEN referee deduplication (bthr < 0.001)
    atoms2 = atoms1.copy()
    atoms2.positions += 1e-5
    res2 = crusher.process_conformer(atoms2, energy_kcal=-10.0, bthr=0.001)
    assert res2["status"] == "duplicate"
    assert "merged_with" in res2


def test_crest_secondary_crosscheck_subprocess(tmp_path: Path) -> None:
    """Verify external CREST binary execution branch in _execute_crest_secondary_crosscheck."""
    from ase.io import write as ase_write

    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_crest_subp.h5"))
    atoms = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])

    def fake_subprocess_run(
        cmd: list[str],
        cwd: str,
        capture_output: bool,
        text: bool,
        timeout: int,
        check: bool,
    ) -> mock.MagicMock:
        # Simulate CREST output conformer ensemble file
        conf1 = atoms.copy()
        conf2 = atoms.copy()
        conf2.positions += 0.05
        out_xyz = Path(cwd) / "crest_conformers.xyz"
        ase_write(str(out_xyz), [conf1, conf2])
        return mock.MagicMock(returncode=0)

    with (
        mock.patch("shutil.which", return_value="/mock/bin/crest"),
        mock.patch("subprocess.run", side_effect=fake_subprocess_run) as mock_run,
    ):
        result = crusher._execute_crest_secondary_crosscheck(atoms, num_conformers=2)
        mock_run.assert_called_once()
        assert len(result) == 2


def test_shake_constraints_water(tmp_path: Path) -> None:
    """Verify RATTLE / SHAKE algorithm freezes O-H bond lengths (0.9572 A) and H-H distance (1.5136 A)."""
    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_shake.h5"))
    # Distorted water molecule with O at origin and stretched O-H bonds
    distorted_water = Atoms(
        symbols=["O", "H", "H"],
        positions=[
            (0.0, 0.0, 0.0),  # O
            (0.0, 1.10, 0.0),  # Distorted H1 (1.1 A vs 0.9572 A)
            (0.0, -0.40, 0.90),  # Distorted H2
        ],
    )
    constrained_water = crusher._apply_shake_constraints(distorted_water)
    pos = constrained_water.positions
    symbols = constrained_water.get_chemical_symbols()

    o_idx = symbols.index("O")
    h_indices = [i for i, s in enumerate(symbols) if s == "H"]

    d_oh1 = float(np.linalg.norm(pos[h_indices[0]] - pos[o_idx]))
    d_oh2 = float(np.linalg.norm(pos[h_indices[1]] - pos[o_idx]))
    d_hh = float(np.linalg.norm(pos[h_indices[0]] - pos[h_indices[1]]))

    assert np.isclose(d_oh1, 0.9572, atol=1e-3)
    assert np.isclose(d_oh2, 0.9572, atol=1e-3)
    assert np.isclose(d_hh, 1.5136, atol=1e-3)


def test_shake_constraints_non_water(tmp_path: Path) -> None:
    """Verify SHAKE constraints safely preserve non-water structures."""
    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_shake_non_water.h5"))
    ch4 = Atoms(
        "CH4",
        positions=[
            [0.0, 0.0, 0.0],
            [0.63, 0.63, 0.63],
            [-0.63, -0.63, 0.63],
            [-0.63, 0.63, -0.63],
            [0.63, -0.63, -0.63],
        ],
    )
    result = crusher._apply_shake_constraints(ch4)
    np.testing.assert_allclose(result.positions, ch4.positions, atol=1e-6)


def test_apply_spectroscopic_override(tmp_path: Path) -> None:
    """Verify spectroscopic override rotational constants comparison within 1.5% tolerance."""
    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_override.h5"))
    atoms1 = Atoms(
        "CH4",
        positions=[
            [0.0, 0.0, 0.0],
            [0.63, 0.63, 0.63],
            [-0.63, -0.63, 0.63],
            [-0.63, 0.63, -0.63],
            [0.63, -0.63, -0.63],
        ],
    )

    # Identical / slightly rotated geometry -> moments match within 1.5% -> returns True
    rot = Rotation.from_euler("z", 10, degrees=True)
    atoms_rot = atoms1.copy()
    atoms_rot.positions = rot.apply(atoms_rot.positions)
    assert crusher._apply_spectroscopic_override(atoms1, atoms_rot) is True

    # Heavily distorted geometry -> moments differ > 1.5% -> returns False
    atoms_distorted = atoms1.copy()
    atoms_distorted.positions[1] = np.array([2.5, 2.5, 2.5])
    assert crusher._apply_spectroscopic_override(atoms1, atoms_distorted) is False


def test_dynamic_anneal_threshold(tmp_path: Path) -> None:
    """Verify dynamic annealing threshold adjustments across varying pool sizes and energy variances."""
    crusher = ToposCrusher(base_rmsd_threshold=0.20, hdf5_path=str(tmp_path / "test_anneal.h5"))

    # Pool size < 2 -> returns base_rmsd
    crusher.pool_size = 1
    assert crusher._dynamic_anneal_threshold() == 0.20

    # Pool size >= 2 with high variance (> 10.0) -> scaling 0.6
    crusher.pool_size = 3
    crusher.accepted_basins = [
        {"energy_kcal": -100.0},
        {"energy_kcal": -90.0},
        {"energy_kcal": -80.0},
    ]
    # Variance of [-100, -90, -80] is 66.67 > 10.0 -> threshold is max(0.05, 0.20 * 0.6) = 0.12
    assert np.isclose(crusher._dynamic_anneal_threshold(), 0.12)

    # Pool size >= 2 with moderate variance (2.0 < var <= 10.0) -> scaling 0.8
    crusher.accepted_basins = [
        {"energy_kcal": -10.0},
        {"energy_kcal": -8.0},
        {"energy_kcal": -6.0},
    ]
    # Variance of [-10, -8, -6] is 2.67 -> threshold is max(0.05, 0.20 * 0.8) = 0.16
    assert np.isclose(crusher._dynamic_anneal_threshold(), 0.16)

    # Pool size >= 2 with low variance (var <= 2.0) -> scaling 1.0
    crusher.accepted_basins = [
        {"energy_kcal": -10.0},
        {"energy_kcal": -10.5},
        {"energy_kcal": -9.8},
    ]
    assert np.isclose(crusher._dynamic_anneal_threshold(), 0.20)


@mock.patch(
    "core_engine.cochem_topos_crusher.get_honest_xtb_calculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
)
@mock.patch(
    "core_engine.cochem_topos_crusher.MACEOFF24mCalculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
    create=True,
)
def test_rotamer_merging_neb_barrier(
    mock_mace: mock.MagicMock,
    mock_xtb: mock.MagicMock,
    tmp_path: Path,
) -> None:
    """Verify NEB barrier evaluation and rotamer merging during conformer processing."""
    crusher = ToposCrusher(bthr=0.001, hdf5_path=str(tmp_path / "test_neb_merge.h5"))
    atoms1 = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])
    isomer_a = Atoms("O", positions=[(0, 0, 0)])
    isomer_b = Atoms("H2", positions=[(0, 0.76, 0.59), (0, -0.76, 0.59)])

    # First accept initial basin
    res1 = crusher.process_conformer(atoms1, energy_kcal=-10.0)
    assert res1["status"] == "accepted"

    # Create candidate duplicate
    atoms_dup = atoms1.copy()
    atoms_dup.positions += 1e-5

    # 1. Low barrier (< KB_T_298): should merge
    with mock.patch.object(crusher, "_execute_jax_neb", return_value=0.2):
        res_merge = crusher.process_conformer(
            candidate=atoms_dup,
            energy_kcal=-10.1,
            isomer_a=isomer_a,
            isomer_b=isomer_b,
        )
        assert res_merge["status"] == "merged"
        assert res_merge["merged_with"] == 0
        assert res_merge["energy_kcal"] == -10.1
        assert res_merge["barrier_kcal"] == 0.2

    # 2. High barrier (>= KB_T_298): should reject as standard duplicate
    with mock.patch.object(crusher, "_execute_jax_neb", return_value=2.5):
        res_dup = crusher.process_conformer(
            candidate=atoms_dup,
            energy_kcal=-10.1,
            isomer_a=isomer_a,
            isomer_b=isomer_b,
        )
        assert res_dup["status"] == "duplicate"
        assert res_dup["merged_with"] == 0


@mock.patch(
    "core_engine.cochem_topos_crusher.get_honest_xtb_calculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
)
@mock.patch(
    "core_engine.cochem_topos_crusher.MACEOFF24mCalculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
    create=True,
)
def test_topos_crusher_hdf5_persistence(
    mock_mace: mock.MagicMock,
    mock_xtb: mock.MagicMock,
    tmp_path: Path,
) -> None:
    """Verify HDF5 state isolation and persistence of atomic coordinates, numbers, and metadata."""
    hdf5_file = tmp_path / "custom_state.h5"
    crusher = ToposCrusher(hdf5_path=str(hdf5_file))
    atoms = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])

    res = crusher.process_conformer(
        atoms,
        energy_kcal=-15.5,
        complex_flag=True,
        lam_trigger_required=True,
    )
    assert res["status"] == "accepted"

    assert hdf5_file.exists()
    with h5py.File(hdf5_file, "r") as f:
        assert "combinatorial_matrix" in f
        grp = f["combinatorial_matrix"]
        assert "basin_00000" in grp
        subgrp = grp["basin_00000"]
        assert "coordinates" in subgrp
        assert "atomic_numbers" in subgrp
        assert "energy_kcal" in subgrp
        assert subgrp.attrs["energy_kcal"] == -15.5
        assert bool(subgrp.attrs["complex_flag"]) is True
        assert bool(subgrp.attrs["LAM_TRIGGER_REQUIRED"]) is True
        np.testing.assert_allclose(subgrp["coordinates"][:], atoms.positions)
        np.testing.assert_array_equal(subgrp["atomic_numbers"][:], atoms.get_atomic_numbers())


@mock.patch(
    "core_engine.cochem_topos_crusher.get_honest_xtb_calculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
)
@mock.patch(
    "core_engine.cochem_topos_crusher.MACEOFF24mCalculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
    create=True,
)
def test_process_conformer_crest_crosscheck_flag(
    mock_mace: mock.MagicMock,
    mock_xtb: mock.MagicMock,
    tmp_path: Path,
) -> None:
    """Verify process_conformer with run_crest_crosscheck=True executes union screening."""
    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_crosscheck.h5"))
    atoms = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])

    with mock.patch("shutil.which", return_value=None):
        res = crusher.process_conformer(atoms, energy_kcal=-10.0, run_crest_crosscheck=True)
        assert res["status"] == "accepted"
        assert crusher.pool_size >= 1


@mock.patch(
    "core_engine.cochem_topos_crusher.get_honest_xtb_calculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
)
@mock.patch(
    "core_engine.cochem_topos_crusher.MACEOFF24mCalculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
    create=True,
)
def test_async_process_monomer_phase(
    mock_mace: mock.MagicMock,
    mock_xtb: mock.MagicMock,
    tmp_path: Path,
) -> None:
    """Verify asynchronous monomer search phase returns accepted monomer conformers."""
    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_monomer_phase.h5"))
    atoms = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])

    result = asyncio.run(crusher.process_monomer_phase(atoms))
    assert "monomers" in result
    assert len(result["monomers"]) >= 1
    assert result["monomers"][0]["status"] == "accepted"

    # Empty geometry returns empty list
    empty_result = asyncio.run(crusher.process_monomer_phase(None))
    assert empty_result == {"monomers": []}


@mock.patch(
    "core_engine.cochem_topos_crusher.get_honest_xtb_calculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
)
@mock.patch(
    "core_engine.cochem_topos_crusher.MACEOFF24mCalculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
    create=True,
)
def test_async_process_strong_complex_phase(
    mock_mace: mock.MagicMock,
    mock_xtb: mock.MagicMock,
    tmp_path: Path,
) -> None:
    """Verify asynchronous strong complex assembly phase combining monomer pairs with clearance."""
    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_strong_phase.h5"))

    # Empty monomers
    empty_res = asyncio.run(crusher.process_strong_complex_phase([]))
    assert empty_res == {"strong_complexes": []}

    # Monomer list
    m1 = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])
    m2 = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)])
    monomers = [{"atoms": m1, "status": "accepted"}, {"atoms": m2, "status": "accepted"}]

    result = asyncio.run(crusher.process_strong_complex_phase(monomers))
    assert "strong_complexes" in result
    assert len(result["strong_complexes"]) >= 1
    assert all(c["status"] == "accepted" for c in result["strong_complexes"])


@mock.patch(
    "core_engine.cochem_topos_crusher.get_honest_xtb_calculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
)
@mock.patch(
    "core_engine.cochem_topos_crusher.MACEOFF24mCalculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
    create=True,
)
def test_async_process_weak_complex_phase(
    mock_mace: mock.MagicMock,
    mock_xtb: mock.MagicMock,
    tmp_path: Path,
) -> None:
    """Verify asynchronous weak complex assembly phase with clearance and LAM_TRIGGER_REQUIRED handling."""
    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_weak_phase.h5"))

    # Pool size < 2
    insufficient_res = asyncio.run(crusher.process_weak_complex_phase([], []))
    assert insufficient_res == {"weak_complexes": []}

    m1 = Atoms("H2O", positions=[(0, 0, 0), (0, 0.76, 0.59), (0, -0.76, 0.59)])
    s1 = Atoms(
        "CH4",
        positions=[
            [0.0, 0.0, 0.0],
            [0.63, 0.63, 0.63],
            [-0.63, -0.63, 0.63],
            [-0.63, 0.63, -0.63],
            [0.63, -0.63, -0.63],
        ],
    )
    monomers = [{"atoms": m1, "status": "accepted"}]
    strong_complexes = [{"atoms": s1, "status": "accepted"}]

    result = asyncio.run(crusher.process_weak_complex_phase(monomers, strong_complexes))
    assert "weak_complexes" in result
    assert len(result["weak_complexes"]) >= 1


@mock.patch(
    "core_engine.cochem_topos_crusher.get_honest_xtb_calculator",
    side_effect=lambda *args, **kwargs: LennardJones(),
)
def test_execute_jax_neb_fallback(
    mock_xtb: mock.MagicMock,
    tmp_path: Path,
) -> None:
    """Verify ASE physical NEB barrier estimation computation."""
    crusher = ToposCrusher(hdf5_path=str(tmp_path / "test_neb.h5"))
    atoms1 = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)])
    atoms2 = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.90)])

    barrier = crusher._execute_jax_neb(atoms1, atoms2)
    assert isinstance(barrier, float)
    assert barrier >= 0.1
