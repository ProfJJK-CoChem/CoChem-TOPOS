"""Preflight and geometric placement checks only; no licensed native ORCA run."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from topos.correlated import correlated_input
from topos.fragments import split_fragments
from topos.matrix_r2 import R2_REVIEWED_RESOLUTION
from topos.matrix_workflow import MatrixInputs
from topos.models import Molecule, ResourceLimits
from topos.storage import digest_json

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'orca_r2_acceptance_case.py'
spec = importlib.util.spec_from_file_location('topos_test_r2_acceptance', SCRIPT)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


def mathematical_water():
    return Molecule(symbols=['O', 'H', 'H'], coordinates=[[.2, -.3, .1], [1.16, -.3, .1], [-.04, .63, .1]])


def test_high_level_monomer_protocol_is_actual_canonical_tz_optimization():
    protocol = acceptance.isolated_water_protocol()
    assert protocol.method == 'AUTOCI-CCSD(T)' and protocol.operation == 'optimize'
    assert protocol.orbital_basis == 'cc-pVTZ' and protocol.frozen_core
    deck = correlated_input(mathematical_water(), protocol, ResourceLimits())
    assert ' Opt' in deck and 'cc-pVTZ' in deck and 'AUTOCI-CCSD(T)' in deck
    assert ' Engrad' not in deck  # independent final gradient is a separate actual job.


def test_two_water_shapes_are_exact_rigid_copies_with_explicit_atom_mapping():
    original = mathematical_water()
    complex_molecule, references, transforms = acceptance.water_dimer_from_monomer(original)
    original_xyz = np.asarray(original.coordinates)
    distances = np.linalg.norm(original_xyz[:, None]-original_xyz[None, :], axis=2)
    assert len(complex_molecule.symbols) == 6 and len(set(complex_molecule.atom_ids)) == 6
    assert np.linalg.norm(np.asarray(complex_molecule.coordinates)[3]-complex_molecule.coordinates[0]) == pytest.approx(2.9)
    for reference, transform, fragment in zip(references, transforms, split_fragments(complex_molecule), strict=True):
        xyz = np.asarray(reference.coordinates)
        assert np.linalg.norm(xyz[:, None]-xyz[None, :], axis=2) == pytest.approx(distances, abs=1e-12)
        assert fragment.atom_ids == reference.atom_ids and fragment.coordinates == reference.coordinates
        rotation = np.asarray(transform['rotation_row_coordinates'])
        assert np.linalg.det(rotation) == pytest.approx(1., abs=1e-12)
        assert transform['placed_geometry_sha256'] == digest_json(reference.model_dump(mode='json'))
        assert set(transform['atom_mapping']) == set(original.atom_ids)
    # Donor O-H points toward acceptor oxygen, while acceptor H atoms point away.
    xyz = np.asarray(complex_molecule.coordinates)
    assert xyz[1, 0] > xyz[0, 0] and xyz[1, 0] < xyz[3, 0]
    assert xyz[4, 0] > xyz[3, 0] and xyz[5, 0] > xyz[3, 0]
    assert xyz[4, 2] * xyz[5, 2] < 0


def test_preflight_carries_explicit_reviewed_scope_and_unchanged_applicability_gates():
    request, transforms = acceptance.acceptance_request(ResourceLimits(budget_seconds=5400, threads=1, memory_mb=2048),
        mathematical_water(), 'TEST-ONLY planned evidence reference, no native calculation asserted')
    inputs = MatrixInputs.model_validate(request.matrix_inputs)
    assert inputs.source_resolution == R2_REVIEWED_RESOLUTION == 'r2-b3lyp-d4-vpt2-transfer-v1'
    assert request.matrix_row_id == 'T3O-3h' and request.purpose == 'matrix'
    assert request.include_queue_in_budget and request.budget_seconds == 5400
    assert inputs.r2_vpt2.semirigid_modes and inputs.r2_vpt2.transfer.semirigid_same_basin
    assert inputs.r2_vpt2.transfer.max_correction_fraction == .1
    assert inputs.r2_vpt2.transfer.min_axis_overlap == .95
    assert inputs.r2_counterpoise.native.method == 'DLPNO-CCSD(T1)'
    assert inputs.r2_counterpoise.native.cabs is None
    assert inputs.r2_counterpoise.native.auxiliary_c == 'cc-pVTZ/C'
    assert inputs.r2_counterpoise.native.auxiliary_jk == 'cc-pVTZ/JK'
    assert len(transforms) == 2
    for reference, provenance in zip(inputs.isolated_monomer_references, inputs.r2_monomer_provenance, strict=True):
        assert provenance.method == 'fc-CCSD(T)/cc-pVTZ'
        assert provenance.geometry_sha256 == digest_json(reference.model_dump(mode='json'))


def test_missing_evidence_or_nonwater_input_cannot_construct_acceptance():
    with pytest.raises(ValueError, match='evidence reference'):
        acceptance.acceptance_request(ResourceLimits(), mathematical_water(), ' ')
    with pytest.raises(ValueError, match='water profile'):
        acceptance.water_dimer_from_monomer(Molecule(symbols=['He'], coordinates=[[0, 0, 0]]))


def test_rejected_native_basis_authority_stops_before_high_level_geometry(tmp_path, monkeypatch):
    """Infrastructure rejection only; no successful native result is simulated."""
    observed = []

    class DeniedUtility:
        def validate_resources(self, resources):
            pass

        def resolve_executable(self, name):
            # A real file is used only for identity hashing; never executed.
            return sys.executable

        def provenance(self):
            return {'scope': 'test-only rejection before execution'}

        def export_orca_basis(self, basis, elements, folder, resources):
            observed.append((basis, elements, resources))
            raise RuntimeError('explicit native basis authority rejection')

    def forbidden_geometry(*args, **kwargs):
        pytest.fail('High-level geometry ran before basis availability was established')

    monkeypatch.setattr(acceptance, 'run_correlated', forbidden_geometry)
    with pytest.raises(RuntimeError, match='basis authority rejection'):
        acceptance.r2_composite_case(DeniedUtility(), tmp_path / 'acceptance',
                                      ResourceLimits(threads=2, memory_mb=4096, budget_seconds=60))
    assert len(observed) == 1 and observed[0][:2] == ('cc-pVDZ-F12', ['H', 'O'])
    assert observed[0][2].threads == 1 and 0 < observed[0][2].budget_seconds <= 60
    retained = json.loads((tmp_path / 'acceptance/native-process-calls.json').read_text())
    assert retained == {'native_processes': [], 'basis_utilities': []}
