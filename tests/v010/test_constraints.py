"""Mathematical rigid-manifold tests, not electronic-structure evidence.

Analytical harmonic functions deliberately isolate optimizer/projection errors.
The separately marked integration test executes the installed xTB binary.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import asdict
from threading import Event

import numpy as np
import pytest
from scipy.spatial.distance import pdist
from scipy.spatial.transform import Rotation

from topos.constraints import (
    BOHR_ANGSTROM,
    ConstraintError,
    EnergyGradientError,
    constrained_optimize,
    constraint_rank,
    intrafragment_drift,
    resolve_profile,
    rigid_perturb,
)
from topos.models import Molecule


def water_pair() -> Molecule:
    water = np.array([[0, 0, 0], [0.9572, 0, 0], [-0.23999, 0.9273, 0]])
    other = Rotation.from_rotvec([0.3, 0.2, 0.1]).apply(water) + [3, 0.4, 0.2]
    return Molecule(
        symbols=["O", "H", "H"] * 2,
        coordinates=np.vstack([water, other]).tolist(),
        fragments=[[0, 1, 2], [3, 4, 5]],
    )


def test_rigid_ranks_account_for_atomic_linear_and_nonlinear_fragments():
    assert constraint_rank(water_pair())["free_rank"] == 6
    pair = Molecule(symbols=["He", "He"], coordinates=[[0, 0, 0], [4, 0, 0]], fragments=[[0], [1]])
    assert constraint_rank(pair) == {
        "fragment_rotation_ranks": [0, 0], "rigid_cartesian_rank": 6,
        "global_frame_rank": 5, "free_rank": 1, "frozen_internal_rank": 0,
    }
    mixed = Molecule(symbols=["H", "H", "He"], coordinates=[[-0.37, 0, 0], [0.37, 0, 0], [0, 3, 0]], fragments=[[0, 1], [2]])
    rank = constraint_rank(mixed)
    assert rank["fragment_rotation_ranks"] == [2, 0]
    assert rank["free_rank"] == 2
    water = water_pair()
    water.fragments = [list(range(6))]
    assert constraint_rank(water)["free_rank"] == 0


def test_rigid_perturb_preserves_every_internal_distance_and_moves_both_bodies():
    original = water_pair()
    perturbed = rigid_perturb(original, np.random.default_rng(31), 0.3, 0.7)
    before, after = np.asarray(original.coordinates), np.asarray(perturbed.coordinates)
    for fragment in original.fragments:
        np.testing.assert_allclose(pdist(before[fragment]), pdist(after[fragment]), atol=2e-14)
        assert np.linalg.norm(after[fragment] - before[fragment]) > 1e-3
    np.testing.assert_allclose(before.mean(axis=0), after.mean(axis=0), atol=1e-14)
    assert perturbed.atom_ids == original.atom_ids
    assert perturbed.isotopes == original.isotopes


def test_rigid_motions_preserve_chirality():
    molecule = Molecule(
        symbols=["C", "H", "F", "Cl", "Br", "He"],
        coordinates=[[0, 0, 0], [1, 1, 1], [-1, -1, 1], [-1, 1, -1], [1, -1, -1], [4, 3, 2]],
        fragments=[[0, 1, 2, 3, 4], [5]],
    )
    original = np.asarray(molecule.coordinates)
    perturbed = np.asarray(rigid_perturb(molecule, np.random.default_rng(13), 2.0, 4.0).coordinates)
    def volume(x):
        return np.linalg.det(x[1:4] - x[0])
    assert volume(original) * volume(perturbed) > 0


def test_analytical_radial_harmonic_minimum_is_converged_in_atomic_units():
    molecule = Molecule(symbols=["He", "He"], coordinates=[[0, 0, 0], [5, 0, 0]], fragments=[[0], [1]])
    target = 3.0 / BOHR_ANGSTROM

    def analytical_radial(mol):
        x = np.asarray(mol.coordinates) / BOHR_ANGSTROM
        delta = x[1] - x[0]
        radius = np.linalg.norm(delta)
        radial_gradient = 0.02 * (radius - target) * delta / radius
        return 0.01 * (radius - target) ** 2, np.vstack([-radial_gradient, radial_gradient])

    result = constrained_optimize(molecule, analytical_radial, tolerances="mapping-2026")
    assert result.converged, result.diagnostics
    assert result.status == "completed"
    distance = np.linalg.norm(np.diff(np.asarray(result.molecule.coordinates), axis=0))
    assert distance == pytest.approx(3.0, abs=1e-6)
    assert result.energy_hartree < 1e-12
    assert all(result.diagnostics["convergence_criteria"].values())
    assert result.diagnostics["profile"]["profile_id"] == "mapping-2026"
    assert result.diagnostics["rms_displacement_bohr"] < 5e-5
    assert result.evaluations[-1]["accepted"]


def test_nonlinear_fragments_optimize_translation_and_orientation_without_deformation():
    molecule = water_pair()
    original = np.asarray(molecule.coordinates)
    target = original.copy()
    center = target[3:].mean(axis=0)
    target[3:] = Rotation.from_rotvec([0.08, -0.1, 0.07]).apply(target[3:] - center) + center + [-0.3, 0.1, -0.15]
    target /= BOHR_ANGSTROM
    distances = {(i, j): np.linalg.norm(target[i] - target[j]) for i in range(3) for j in range(3, 6)}

    def analytical_cross_distances(mol):
        x = np.asarray(mol.coordinates) / BOHR_ANGSTROM
        gradient = np.zeros_like(x)
        energy = 0.0
        for (i, j), equilibrium in distances.items():
            delta = x[i] - x[j]
            radius = np.linalg.norm(delta)
            residual = radius - equilibrium
            energy += 0.005 * residual**2
            derivative = 0.01 * residual * delta / radius
            gradient[i] += derivative
            gradient[j] -= derivative
        return energy, gradient

    initial_energy, _ = analytical_cross_distances(molecule)
    result = constrained_optimize(molecule, analytical_cross_distances, tolerances="mapping-2026")
    assert result.converged, result.diagnostics
    assert result.energy_hartree < initial_energy * 1e-4
    assert result.diagnostics["free_rank"] == 6
    assert result.diagnostics["max_trajectory_intrafragment_drift_angstrom"] < 1e-12
    assert intrafragment_drift(original, result.molecule.coordinates, molecule.fragments) < 1e-12


def test_frozen_internal_forces_are_retained_without_blocking_free_convergence():
    molecule = Molecule(symbols=["H", "H", "He"], coordinates=[[-0.37, 0, 0], [0.37, 0, 0], [0, 4, 0]], fragments=[[0, 1], [2]])

    def analytical_bond_strain_and_com_distance(mol):
        x = np.asarray(mol.coordinates) / BOHR_ANGSTROM
        gradient = np.zeros_like(x)
        bond = x[1] - x[0]
        bond_length = np.linalg.norm(bond)
        bond_residual = bond_length - 1.0 / BOHR_ANGSTROM
        bond_gradient = 0.1 * bond_residual * bond / bond_length
        gradient[0] -= bond_gradient
        gradient[1] += bond_gradient
        delta = x[2] - x[:2].mean(axis=0)
        radius = np.linalg.norm(delta)
        residual = radius - 2.5 / BOHR_ANGSTROM
        radial_gradient = 0.01 * residual * delta / radius
        gradient[2] += radial_gradient
        gradient[:2] -= radial_gradient / 2
        return 0.05 * bond_residual**2 + 0.005 * residual**2, gradient

    result = constrained_optimize(molecule, analytical_bond_strain_and_com_distance, tolerances="chunk3-2026")
    assert result.converged, result.diagnostics
    assert result.diagnostics["max_free_gradient_hartree_per_bohr"] < 1e-5
    assert result.diagnostics["max_frozen_gradient_hartree_per_bohr"] > 1e-2
    assert result.diagnostics["geometric_strain_warning"] is True
    assert "full-dimensional stability not established" in result.diagnostics["classification"]
    assert result.diagnostics["profile"]["rigidity_angstrom"] == 1e-8


def test_conflicting_profiles_are_never_silently_resolved():
    with pytest.raises(ConstraintError, match="explicit"):
        resolve_profile(None)
    with pytest.raises(ConstraintError, match="disagree"):
        constrained_optimize(water_pair(), lambda mol: None, {"profile_id": "chunk3-2026"}, "mapping-2026")
    with pytest.raises(ConstraintError, match="unsupported"):
        constrained_optimize(water_pair(), lambda mol: None, {"profile_id": "mapping-2026", "fixed_atoms": [0, 1, 2]})
    with pytest.raises(ConstraintError, match="partition"):
        constrained_optimize(Molecule(symbols=["He"], coordinates=[[0, 0, 0]]), lambda mol: None, tolerances="mapping-2026")
    altered = asdict(resolve_profile("mapping-2026"))
    altered["energy_hartree"] = 1e-3
    with pytest.raises(ConstraintError, match="immutable"):
        resolve_profile(altered)


def test_exact_zero_gradient_is_valid_but_absent_gradient_is_not():
    molecule = water_pair()
    result = constrained_optimize(molecule, lambda mol: (0.0, np.zeros((6, 3))), tolerances="mapping-2026")
    assert result.converged
    assert result.energy_hartree == 0.0
    assert len(result.evaluations) == 2
    with pytest.raises(EnergyGradientError, match="missing is not zero"):
        constrained_optimize(molecule, lambda mol: (0.0, None), tolerances="mapping-2026")


def test_evaluation_budget_and_cancellation_retain_honest_partial_state():
    molecule = water_pair()
    result = constrained_optimize(molecule, lambda mol: (-1.0, np.zeros((6, 3))), tolerances="mapping-2026", max_evaluations=1)
    assert result.status == "evaluation-limit"
    assert not result.converged
    assert result.energy_hartree == -1.0
    assert len(result.evaluations) == 1
    cancel = Event()
    cancel.set()
    result = constrained_optimize(molecule, lambda mol: None, tolerances="mapping-2026", cancel_event=cancel)
    assert result.status == "cancelled"
    assert result.energy_hartree is None
    assert not result.evaluations


def test_rejected_line_search_trial_never_replaces_the_accepted_geometry():
    molecule = Molecule(symbols=["He", "He"], coordinates=[[0, 0, 0], [5, 0, 0]], fragments=[[0], [1]])

    def steep_analytical_well(mol):
        x = np.asarray(mol.coordinates) / BOHR_ANGSTROM
        delta = x[1] - x[0]
        radius = np.linalg.norm(delta)
        residual = radius - 5.05 / BOHR_ANGSTROM
        derivative = residual * delta / radius
        return 0.5 * residual**2, np.vstack([-derivative, derivative])

    result = constrained_optimize(molecule, steep_analytical_well, tolerances="mapping-2026", max_evaluations=2)
    assert result.status == "evaluation-limit"
    assert [entry["accepted"] for entry in result.evaluations] == [True, False]
    assert result.energy_hartree == result.evaluations[0]["energy_hartree"]
    np.testing.assert_allclose(result.molecule.coordinates, molecule.coordinates)
    assert result.evaluations[-1]["energy_hartree"] > result.energy_hartree


@pytest.mark.integration
def test_authentic_xtb_frozen_water_dimer_converges_without_internal_drift(tmp_path):
    """Real binary/protocol evidence, without claiming reference monomer accuracy."""
    executable = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if executable is None:
        pytest.skip("authentic xTB executable is not installed")
    from topos.engines import run_engine
    from topos.models import MethodSpec, ResourceLimits

    molecule = Molecule(
        symbols=["O", "H", "H"] * 2,
        coordinates=[[0, 0, 0], [.9572, 0, 0], [-.23999, .9273, 0],
                     [2.9, .1, .2], [3.3, .9, .5], [3.4, -.6, -.2]],
        fragments=[[0, 1, 2], [3, 4, 5]],
    )
    evaluations = []

    def authentic_gradient(mol):
        result = run_engine(
            mol, MethodSpec(engine="xtb", method="GFN2-xTB", purpose="gradient"),
            ResourceLimits(budget_seconds=15, threads=1), tmp_path / f"gradient-{len(evaluations):03d}",
            operation="gradient", executable=executable,
        )
        evaluations.append(result)
        return result

    result = constrained_optimize(molecule, authentic_gradient, tolerances="mapping-2026", max_evaluations=200, budget_seconds=60)
    assert result.converged, result.diagnostics
    assert all(result.diagnostics["convergence_criteria"].values())
    assert result.energy_hartree is not None
    assert result.gradient_hartree_per_bohr is not None
    assert result.diagnostics["max_trajectory_intrafragment_drift_angstrom"] < 1e-12
    assert evaluations and all(entry.status == "completed" for entry in evaluations)
    assert all(entry.artifacts for entry in evaluations)
