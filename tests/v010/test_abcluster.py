"""Native ABC acceptance and typed-contract checks; no fabricated engine outputs."""
import json
import os
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from topos.abcluster import KJ_MOL_PER_HARTREE, parse_rigidmol, rigidmol_inputs, run_rigidmol
from topos.engines import EngineParseError
from topos.models import (
    FragmentState,
    Molecule,
    ResourceLimits,
    RigidmolAtomParameter,
    RigidmolOptions,
)
from topos.storage import IntegrityError


def neon():
    molecule = Molecule(symbols=["Ne", "Ne"], coordinates=[[0., 0., 0.], [4., 0., 0.]],
        fragments=[[0], [1]], fragment_states=[FragmentState(atom_indices=[i], charge=0, multiplicity=1) for i in range(2)])
    options = RigidmolOptions(atomic_parameters=[RigidmolAtomParameter(atom_id=i, charge_e=0.,
        epsilon_kj_mol=.1848, sigma_angstrom=2.9223) for i in molecule.atom_ids],
        parameter_source="ABCluster 3.4 misc/charmm36/ne.xyz: bms_dec03; https://zhjun-sci.com/abcluster.html",
        population=8, generations=8, max_saved_minima=10)
    return molecule, options


@pytest.fixture
def binary():
    value = os.environ.get("TOPOS_ABCLUSTER_EXECUTABLE")
    if not value:
        pytest.skip("native ABCluster 3.4 rigidmol executable not explicitly provisioned")
    assert Path(value).is_file()
    return value


def test_input_contains_explicit_native_units_and_no_electronic_method():
    molecule, options = neon()
    files = rigidmol_inputs(molecule, options)
    assert files["packing.cluster"] == "2\nfragment-0000.xyz 1\nfragment-0001.xyz 1\n* 4\n"
    assert "q(e) epsilon(kJ/mol) sigma(angstrom)" in files["fragment-0000.xyz"]
    assert "0 0.1848 2.9223" in files["fragment-0000.xyz"]
    assert "GFN" not in "".join(files.values())


def test_force_field_state_and_repulsion_are_explicit():
    molecule, options = neon()
    wrong = options.model_copy(deep=True)
    wrong.atomic_parameters[0].charge_e = 1.
    with pytest.raises(ValueError, match="fragment charge"):
        rigidmol_inputs(molecule, wrong)
    wrong = options.model_copy(deep=True)
    wrong.atomic_parameters[0].epsilon_kj_mol = 0.
    wrong.atomic_parameters[0].sigma_angstrom = 0.
    with pytest.raises(ValueError, match="repulsive"):
        rigidmol_inputs(molecule, wrong)
    wrong = options.model_copy(update={"atomic_parameters": options.atomic_parameters[:1]})
    with pytest.raises(ValueError, match="every input atom"):
        rigidmol_inputs(molecule, wrong)


def test_no_undeclared_fragment_or_environment_substitution():
    molecule, options = neon()
    for altered in [molecule.model_copy(update={"fragment_states": []}),
                    molecule.model_copy(update={"environment": {"solvent": "water"}})]:
        with pytest.raises(ValueError):
            rigidmol_inputs(altered, options)


def test_genuine_neon_dimer_analytic_lj_limit_resume_and_tamper(tmp_path, binary):
    molecule, options = neon()
    resources = ResourceLimits(budget_seconds=10., memory_mb=256)
    result = run_rigidmol(molecule, options, resources, tmp_path / "run", executable=binary)
    assert result.status == "completed", result.diagnostics
    assert result.engine == "abcluster" and result.engine_version == "3.4"
    best = result.ensemble[0]
    # Two identical neutral sites have an exact LJ minimum at 2^(1/6)*sigma,
    # with energy -epsilon. This checks genuine native geometry and energy units.
    distance = np.linalg.norm(np.diff(best.molecule.coordinates, axis=0))
    # Native local optimization stops at its own tolerance: its printed score
    # has eight decimals, not a 1e-7-Eh/bohr quantum stationarity guarantee.
    assert distance == pytest.approx(2 ** (1 / 6) * 2.9223, abs=5e-4)
    assert best.metadata["native_energy_kj_mol"] == pytest.approx(-.1848, abs=1e-8)
    assert best.energy_hartree == pytest.approx(-.1848 / KJ_MOL_PER_HARTREE, abs=1e-12)
    assert best.metadata["is_electronic_energy"] is False
    assert result.metadata["exhaustive"] is False
    cached = run_rigidmol(molecule, options, resources, tmp_path / "run", executable=binary)
    assert cached.metadata["reused_completed_search"] is True
    assert cached.command == result.command and cached.artifacts == result.artifacts
    assert len(list((tmp_path / "run").glob("native-*"))) == 1
    native = Path(result.metadata["native_directory"])
    raw = (native / "rigidmol.stdout").read_text()
    with pytest.raises(EngineParseError, match="terminate normally"):
        parse_rigidmol(raw.replace("Normal termination at", "Unexpected end at"), native, molecule, options)
    with pytest.raises(EngineParseError, match="generation evidence"):
        parse_rigidmol(raw.replace("    8      ", "    9      "), native, molecule, options)
    (native / "packing-LM/0.xyz").write_text((native / "packing-LM/0.xyz").read_text().replace("-0.18480000", "-9.18480000"))
    with pytest.raises(IntegrityError, match="raw artifact changed"):
        run_rigidmol(molecule, options, resources, tmp_path / "run", executable=binary)


def methanol_dimer():
    # Numerical parameter facts from the official 3.4 distribution, not a test
    # potential disguised as engine output. All36_cgenff CH3OH has no virtual site.
    symbols = ["O", "H", "C", "H", "H", "H"]
    xyz = [[.046873, -.757692, 0.], [-.876185, -1.051609, 0.], [.046873, .660946, 0.],
           [1.094151, .975102, 0.], [-.437096, 1.086186, .893153], [-.437096, 1.086186, -.893153]]
    params = [[-.650, .8037, 3.1449], [.420, .1674, .4], [-.040, .3264, 3.6527],
              [.090, .1004, 2.3876], [.090, .1004, 2.3876], [.090, .1004, 2.3876]]
    # Interleaved atoms test recovery of original identities after native fragment grouping.
    positions = [position for coord in xyz for position in (coord, [coord[0] + 5., *coord[1:]])]
    groups = [list(range(0, 12, 2)), list(range(1, 12, 2))]
    molecule = Molecule(symbols=[s for symbol in symbols for s in [symbol, symbol]], coordinates=positions,
        fragments=groups, fragment_states=[FragmentState(atom_indices=g, charge=0, multiplicity=1) for g in groups])
    options = RigidmolOptions(atomic_parameters=[RigidmolAtomParameter(atom_id=molecule.atom_ids[i],
        charge_e=params[i // 2][0], epsilon_kj_mol=params[i // 2][1], sigma_angstrom=params[i // 2][2]) for i in range(12)],
        parameter_source="ABCluster 3.4 misc/charmm36/ch3oh.xyz, all36_cgenff; https://zhjun-sci.com/abcluster.html",
        population=8, generations=5, max_saved_minima=10)
    return molecule, options


def test_genuine_methanol_dimer_preserves_monomers_and_interleaved_atom_ids(tmp_path, binary):
    molecule, options = methanol_dimer()
    result = run_rigidmol(molecule, options, ResourceLimits(budget_seconds=20., memory_mb=256),
                          tmp_path / "run", executable=binary)
    assert result.status == "completed", result.diagnostics
    assert result.ensemble and result.ensemble[0].metadata["native_energy_kj_mol"] < 0
    for frame in result.ensemble:
        assert frame.molecule.atom_ids == molecule.atom_ids
        assert frame.molecule.symbols == molecule.symbols
        assert frame.molecule.fragment_states == molecule.fragment_states
        for group in molecule.fragments:
            before, after = np.asarray(molecule.coordinates)[group], np.asarray(frame.molecule.coordinates)[group]
            assert np.linalg.norm(before[:, None] - before[None, :], axis=2) == pytest.approx(
                np.linalg.norm(after[:, None] - after[None, :], axis=2), abs=5e-7)
    native = Path(result.metadata["native_directory"])
    path = native / "packing-LM/0.xyz"
    rows = path.read_text().splitlines()
    fields = rows[2].split()
    fields[1] = str(float(fields[1]) + .01)
    rows[2] = " ".join(fields)
    path.write_text("\n".join(rows) + "\n")
    with pytest.raises(EngineParseError, match="deformed"):
        parse_rigidmol((native / "rigidmol.stdout").read_text(), native, molecule, options)


def test_cancelled_search_retains_raw_evidence_then_can_retry(tmp_path, binary):
    molecule, options = neon()
    cancelled = Event()
    cancelled.set()
    result = run_rigidmol(molecule, options, ResourceLimits(budget_seconds=10., memory_mb=256),
                          tmp_path / "run", executable=binary, cancel_event=cancelled)
    assert result.status == "cancelled" and not result.ensemble
    assert result.artifacts and not (tmp_path / "run/completed.json").exists()
    resumed = run_rigidmol(molecule, options, ResourceLimits(budget_seconds=10., memory_mb=256),
                          tmp_path / "run", executable=binary)
    assert resumed.status == "completed", resumed.diagnostics
    assert len(list((tmp_path / "run").glob("native-*"))) == 2
    receipt = json.loads((tmp_path / "run/completed.json").read_text())
    assert receipt["metadata"]["recovery_policy"].endswith("starts fresh")
