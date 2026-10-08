"""Strict CP contracts and explicit mathematical surfaces; no licensed CFOUR run.

The sole native fixture is unchanged historical 1.2 MP2 output. It establishes
GH coordinate grammar and is deliberately rejected by the 2.1 execution parser.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest

from topos.cfour_counterpoise import (
    BasisCenter,
    CfourCounterpoiseGeometryProtocol,
    CfourCounterpoiseLeg,
    _drop_selection,
    _native_basis_geometry,
    _optimize_surface,
    cfour_counterpoise_input,
    counterpoise_legs,
    execute_cfour_counterpoise_recipe,
    parse_cfour_counterpoise_output,
    run_cfour_counterpoise_leg,
)
from topos.engines import EngineParseError
from topos.external_engines import ExternalProtocol
from topos.higher_composite import HigherGeometryProtocol, NumericalGeometryOptions, _ComponentStop
from topos.models import Molecule, ResourceLimits, RunRecord, RunRequest
from topos.science import BOHR_ANGSTROM
from topos.storage import RunStore, digest_json, file_digest

FIXTURES = Path(__file__).parent / 'fixtures/cfour_counterpoise'


def numerical():
    return NumericalGeometryOptions(step_bohr=.001, maximum_step_disagreement_hartree_per_bohr=1e-7,
        gradient_max_hartree_per_bohr=1e-5, gradient_rms_hartree_per_bohr=3e-6, maximum_iterations=20)


def molecule():
    return Molecule(symbols=['He', 'He'], coordinates=[[0., 0., 0.], [0., 0., 3.]],
        fragments=[[0], [1]], fragment_states=[{'atom_indices': [0], 'charge': 0, 'multiplicity': 1},
                                             {'atom_indices': [1], 'charge': 0, 'multiplicity': 1}])


def specification(**updates):
    geometry = HigherGeometryProtocol(template=ExternalProtocol(engine='cfour', engine_version='2.1',
        method='CCSD(T)', operation='optimize', orbital_basis='PVTZ', frozen_core=True,
        genbas_path='/licensed/cfour/basis/GENBAS', genbas_sha256='a'*64), low_basis='PVTZ', high_basis='PVQZ',
        geometry_inverse_power=3., core_valence_basis='PCVTZ', full_triples_basis='PVTZ', full_quadruples_basis='PVDZ',
        coordinates={'coordinates': [{'kind': 'distance', 'atoms': [0, 1]}]},
        numerical_quadruples=numerical(), convention='explicit-geometry-CBS-CV-fT-fQ-v1')
    values = dict(geometry=geometry, numerical=numerical(), core_orbitals_by_atom=[0, 0],
                  convention='relaxed-total-CP-geometry-CBS-CV-fT-fQ-v1')
    return CfourCounterpoiseGeometryProtocol(**{**values, **updates})


def native(spec=None, role='cc_low'):
    value = (spec or specification()).geometry.protocols()[role].model_dump()
    return ExternalProtocol.model_validate({**value, 'operation': 'energy'})


def test_leg_inventory_balances_relaxed_total_and_keeps_ghosts_out_of_physical_molecule():
    legs = counterpoise_legs(molecule(), native(), [0, 0])
    assert [(name, weight) for name, weight, _, _ in legs] == [
        ('complex', 1.), ('fragment-0-own', 1.), ('fragment-0-ghost', -1.),
        ('fragment-1-own', 1.), ('fragment-1-ghost', -1.)]
    assert len(legs[2][2].symbols) == 1
    assert len(legs[2][3].basis_centers) == 2
    assert [c.physical for c in legs[2][3].basis_centers] == [True, False]
    assert [c.physical for c in legs[4][3].basis_centers] == [False, True]
    # Distinct physical charge cannot be inferred from the whole basis inventory.
    complex_value, own, ghost = -20., [-9., -9.], [-9.2, -9.2]
    relaxed = complex_value + sum(own) - sum(ghost)
    interaction = complex_value - sum(ghost)
    assert relaxed == pytest.approx(-19.6) and interaction == pytest.approx(-1.6)


def test_all_ghost_centers_follow_every_whole_complex_displacement_and_cache_identity():
    original = counterpoise_legs(molecule(), native(), [0, 0])[2][3]
    changed = molecule().model_copy(deep=True)
    changed.coordinates[1][2] += .03
    displaced = counterpoise_legs(changed, native(), [0, 0])[2][3]
    assert displaced.basis_centers[0] == original.basis_centers[0]
    assert displaced.basis_centers[1].coordinates[2] == 3.03
    assert digest_json(original.model_dump()) != digest_json(displaced.model_dump())


def test_only_physical_nuclei_contribute_core_orbitals():
    complex_molecule = Molecule(symbols=['Ne', 'Ne'], coordinates=[[0, 0, 0], [0, 0, 3.5]],
        fragments=[[0], [1]], fragment_states=[{'atom_indices': [i], 'charge': 0, 'multiplicity': 1} for i in range(2)])
    legs = counterpoise_legs(complex_molecule, native(), [1, 1])
    assert [p.dropped_core_orbitals for _, _, _, p in legs] == [2, 1, 1, 1, 1]
    _, _, physical, ghost = legs[2]
    text = cfour_counterpoise_input(physical, ghost, ResourceLimits())
    assert 'DROPMO=1>1' in text and 'FROZEN_CORE=OFF' in text
    assert text.count('Ne ') == 1 and text.count('GH ') == 1
    assert text.count('NE:PVTZ') == 2
    assert 'BASIS=SPECIAL' in text and 'ABCDTYPE=STANDARD' in text and 'CC_PROG=VCC' in text
    ae = counterpoise_legs(complex_molecule, native(role='cv_ae'), [1, 1])
    assert all(p.dropped_core_orbitals == 0 for _, _, _, p in ae)


@pytest.mark.parametrize('role,program', [('triples_full', 'ECC'), ('quadruples_full', 'NCC')])
def test_explicit_high_solver_and_scalar_energies(role, program):
    _, _, physical, leg = counterpoise_legs(molecule(), native(role=role), [0, 0])[2]
    text = cfour_counterpoise_input(physical, leg, ResourceLimits())
    assert 'CC_PROG=' + program in text and 'DERIV_LEVEL=ZERO' in text
    assert 'ABCDTYPE=STANDARD' in text and 'DROPMO=' not in text
    assert 'DERIV_LEVEL=FIRST' not in text and 'MRCC' not in text


@pytest.mark.parametrize('counts', [[True, 0], [-1, 0], [1.2, 0]])
def test_core_choices_cannot_be_coerced_or_guessed(counts):
    with pytest.raises(ValueError):
        specification(core_orbitals_by_atom=counts)


@pytest.mark.parametrize('counts', [[0], [1, 0], [10, 0]])
def test_core_counts_need_correlated_electrons_and_complete_physical_inventory(counts):
    with pytest.raises(ValueError):
        specification(core_orbitals_by_atom=counts).validate_molecule(molecule())


@pytest.mark.parametrize('changes', [{'convention': 'interaction-only'},
    {'core_orbitals_by_atom': []}])
def test_wrong_scientific_convention_or_missing_core_choices_rejected(changes):
    with pytest.raises(ValueError):
        specification(**changes)


def test_ghost_centers_are_separate_from_physical_atom_identity():
    _, _, physical, leg = counterpoise_legs(molecule(), native(), [0, 0])[2]
    wrong = physical.model_copy(update={'charge': 2})
    with pytest.raises(ValueError, match='correlated space'):
        cfour_counterpoise_input(wrong, leg, ResourceLimits())
    wrong = physical.model_copy(update={'atom_ids': ['different']})
    with pytest.raises(ValueError, match='indexed physical'):
        cfour_counterpoise_input(wrong, leg, ResourceLimits())
    with pytest.raises(ValueError, match='H–Ne'):
        BasisCenter(symbol='Ar', atom_id='a', coordinates=[0, 0, 0], physical=False)


def test_historical_fixture_hash_geometry_only_and_exact_version_rejection():
    provenance = json.loads((FIXTURES / 'provenance.json').read_text())
    path = FIXTURES / provenance['fixture']
    assert file_digest(path) == provenance['sha256']
    assert provenance['native_version'] == '1.2'
    raw = path.read_text()
    # Extract actual coordinates from its independently authored input echo.
    rows = re.findall(r'(?m)^\s*(H|O|GH)\s+([-+.0-9]+)\s+([-+.0-9]+)\s+([-+.0-9]+)\s*$', raw.split('*CFOUR(', 1)[0])
    assert len(rows) == 6
    symbols = ['H', 'O', 'H', 'H', 'O', 'H']
    centers = [BasisCenter(symbol=s, atom_id=str(i), coordinates=list(map(float, r[1:])), physical=i < 3)
               for i, (s, r) in enumerate(zip(symbols, rows, strict=True))]
    physical = Molecule(symbols=symbols[:3], coordinates=[c.coordinates for c in centers[:3]], atom_ids=['0', '1', '2'])
    leg = CfourCounterpoiseLeg.model_validate({**native().model_dump(), 'basis_centers': centers, 'dropped_core_orbitals': 1})
    xyz, energy_text = _native_basis_geometry(raw, leg)
    assert xyz.shape == (6, 3)
    assert 'Symbol    Number           X' not in energy_text
    assert 'E(SCF)' in energy_text
    with pytest.raises(EngineParseError, match='exact requested native version'):
        parse_cfour_counterpoise_output(raw, physical, leg)
    with pytest.raises(EngineParseError, match='identity differs'):
        _native_basis_geometry(raw.replace('GH      110', 'O         8'), leg)
    with pytest.raises(EngineParseError, match='Exactly one'):
        _native_basis_geometry(raw + raw, leg)
    altered = leg.model_copy(deep=True)
    altered.basis_centers[5].coordinates[2] += .1
    with pytest.raises(EngineParseError, match='geometry changed'):
        _native_basis_geometry(raw, altered)


@pytest.mark.parametrize('value,expected', [('NONE', set()), ('1>3', {1, 2, 3}), ('1,2,3', {1, 2, 3}), ('1', {1})])
def test_explicit_native_drop_selection_grammar(value, expected):
    assert _drop_selection(value) == expected


@pytest.mark.parametrize('value', ['3>1', 'AUTO', '1-3', 'ALL'])
def test_unknown_native_core_grammar_is_rejected(value):
    with pytest.raises(EngineParseError):
        _drop_selection(value)


def record_store(tmp_path):
    record = RunRecord(request=RunRequest(molecule=molecule(), purpose='matrix', matrix_row_id='T3O-1w'), status='running')
    store = RunStore(tmp_path / record.run_id)
    store.commit(record)
    return record, store


@pytest.mark.parametrize('branch,expected', [('raw', 3.), ('cp', 3. - .04*BOHR_ANGSTROM)])
def test_relaxed_surface_optimizer_includes_ghost_basis_motion(tmp_path, monkeypatch, branch, expected):
    """Analytic mathematical potential; not mocked native CFOUR output."""
    import topos.cfour_counterpoise as module

    record, store = record_store(tmp_path)
    samples = []

    def mathematical_component(workflow, record, store, key, physical, protocol, executor, deadline, cancel):
        centers = protocol.basis_centers
        xyz = np.array([c.coordinates for c in centers]) / BOHR_ANGSTROM
        if len(centers) == 1:
            value = -1.
        else:
            r = np.linalg.norm(xyz[1] - xyz[0])
            value = .5 * (r - 3./BOHR_ANGSTROM)**2 - 2. if all(c.physical for c in centers) else -1. - .02*r
        samples.append((key, [c.coordinates[:] for c in centers]))
        return SimpleNamespace(energy_hartree=value, engine_version='2.1',
            metadata={'executable_sha256': 'a'*64, 'basis_library': {'sha256': 'b'*64}})

    monkeypatch.setattr(module, 'run_component', mathematical_component)
    optimized, evidence, identities = _optimize_surface(None, record, store, native(), specification(),
        branch, 'cc_low', time.monotonic()+30, None)
    radius = np.linalg.norm(np.array(optimized.coordinates)[1] - optimized.coordinates[0])
    assert radius == pytest.approx(expected, abs=1e-7)
    assert not evidence['analytic_gradient'] and not evidence['minimum_hessian_verified']
    assert len(identities) == 1
    if branch == 'cp':
        assert any('fragment-0-ghost' in key for key, _ in samples)
        assert len({digest_json(xyz) for key, xyz in samples if 'fragment-0-ghost' in key}) > 10
    assert not record.attempts  # The mathematical fixture never becomes native evidence.


@pytest.mark.parametrize('kind', ['cancel', 'deadline'])
def test_campaign_boundary_stops_before_any_native_displacement(tmp_path, monkeypatch, kind):
    import topos.cfour_counterpoise as module

    record, store = record_store(tmp_path)
    cancel = Event()
    if kind == 'cancel':
        cancel.set()
    monkeypatch.setattr(module, 'run_component', lambda *args: pytest.fail('Must not launch any native calculation'))
    with pytest.raises(_ComponentStop):
        _optimize_surface(None, record, store, native(), specification(), 'cp', 'cc_low',
                          time.monotonic() + (30 if kind == 'cancel' else -1), cancel)
    assert record.status == ('cancelled' if kind == 'cancel' else 'timed-out')


def test_whole_recipe_runs_sixteen_component_optimizations_without_averaging(tmp_path, monkeypatch):
    """Driver arithmetic fixture bypasses native execution and publication."""
    import topos.cfour_counterpoise as module
    import topos.external_matrix_workflow as publisher

    record, store = record_store(tmp_path)
    calls, outputs = [], []

    def mathematical_optimize(workflow, record, store, native, specification, branch, role, deadline, cancel):
        calls.append((branch, role, native.operation))
        value = record.request.molecule.model_copy(deep=True)
        value.coordinates[1][2] += .005 if branch == 'cp' else 0.
        return value, {'test_only_mathematics': True}, {('2.1', 'a'*64, 'b'*64)}

    monkeypatch.setattr(module, '_optimize_surface', mathematical_optimize)
    monkeypatch.setattr(publisher, '_publish', lambda record, store, output: outputs.append(output))
    inputs = SimpleNamespace(cfour_counterpoise=specification(), external_resolution='cfour-relaxed-counterpoise-geometry-v1',
                             source_resolution='cfour-relaxed-counterpoise-geometry-v1')
    assert execute_cfour_counterpoise_recipe(None, record, store, inputs, time.monotonic()+30, None)
    assert len(calls) == 16 and all(operation == 'energy' for _, _, operation in calls)
    assert set(role for branch, role, _ in calls if branch == 'cp') == set(specification().geometry.protocols())
    output = outputs[0]
    assert set(output['branches']) == {'raw', 'cp'}
    assert output['branches']['raw']['molecule']['coordinates'] != output['branches']['cp']['molecule']['coordinates']
    assert output['counterpoise_bracket_computed'] and not output['minimum_hessian_verified']
    assert output['composite_electronic_energy_hartree'] is None and output['accuracy_claim'] is None
    assert not record.attempts and not record.artifacts  # No manufactured native receipt.


def test_native_leg_unavailable_cannot_produce_science(tmp_path):
    _, _, physical, leg = counterpoise_legs(molecule(), native(), [0, 0])[2]
    result = run_cfour_counterpoise_leg(physical, leg, ResourceLimits(), tmp_path/'native',
        executable='/certainly/absent/cfour', process_runner=lambda *args, **kw: pytest.fail('Engine absent'))
    assert result.status == 'unavailable' and result.energy_hartree is None and not result.converged
    assert result.metadata['execution_kind'] == 'not-executed'


def test_atom_local_core_assignment_cannot_impersonate_lowest_occupied_dropmo():
    co = Molecule(symbols=['C', 'O'], coordinates=[[0, 0, 0], [0, 0, 4]],
        fragments=[[0], [1]], fragment_states=[{'atom_indices': [i], 'charge': 0, 'multiplicity': 1} for i in range(2)])
    with pytest.raises(ValueError, match='H–Ne core'):
        specification(core_orbitals_by_atom=[0, 2]).validate_molecule(co)
    with pytest.raises(ValueError, match='Conventional H–Ne core'):
        counterpoise_legs(co, native(), [0, 2])


@pytest.mark.parametrize('changed', ['ZMAT', 'GENBAS', 'protocol.json', 'executable', 'source-library', 'linked-input'])
def test_real_process_boundary_rejects_input_or_executable_mutation(tmp_path, monkeypatch, changed):
    """/bin/true is a transport-only process; no electronic calculation is claimed."""
    import shutil

    import topos.cfour_counterpoise as module
    from topos.runtime import run_process

    installation = tmp_path / 'transport-fixture'
    (installation / 'bin').mkdir(parents=True)
    (installation / 'basis').mkdir()
    executable = installation / 'bin' / 'process-control'
    shutil.copyfile('/bin/true', executable)
    executable.chmod(0o700)
    library = installation / 'basis' / 'GENBAS'
    library.write_text('He:PVTZ\nTransport input identity test only; never passed to an electronic engine.\n')
    _, _, physical, original = counterpoise_legs(molecule(), native(), [0, 0])[2]
    leg = CfourCounterpoiseLeg.model_validate({**original.model_dump(), 'genbas_path': str(library),
                                             'genbas_sha256': file_digest(library)})

    def real_transport_with_injected_mutation(command, folder, resources, **kwargs):
        process = run_process(command, folder, resources, **kwargs)
        assert process.status == 'completed'
        target = executable if changed == 'executable' else library if changed == 'source-library' else folder / changed
        if changed == 'linked-input':
            target = folder / 'ZMAT'
            retained = folder / 'linked-target'
            retained.write_bytes(target.read_bytes())
            target.unlink()
            target.symlink_to(retained)
        else:
            with target.open('ab') as stream:
                stream.write(b'changed')
        return process

    monkeypatch.setattr(module, 'parse_cfour_counterpoise_output', lambda *args: pytest.fail('Mutated native input must never be accepted'))
    result = run_cfour_counterpoise_leg(physical, leg, ResourceLimits(), tmp_path/'attempt',
        executable=executable, process_runner=real_transport_with_injected_mutation)
    assert result.status == 'failed' and result.energy_hartree is None and not result.converged
    assert 'immutable executable/basis/input changed' in result.diagnostics['reason']


@pytest.mark.parametrize('source_resolution', [None, 'cfour-topos-cartesian-optimizer-v1'])
def test_reviewed_counterpoise_resolution_is_required_before_any_engine(tmp_path, monkeypatch, source_resolution):
    import topos.cfour_counterpoise as module

    record, store = record_store(tmp_path)
    monkeypatch.setattr(module, '_optimize_surface', lambda *args: pytest.fail('Wrong resolution cannot run'))
    inputs = SimpleNamespace(cfour_counterpoise=specification(), external_resolution='cfour-relaxed-counterpoise-geometry-v1',
                             source_resolution=source_resolution)
    assert not execute_cfour_counterpoise_recipe(None, record, store, inputs, time.monotonic()+30, None)
    assert record.status == 'unsupported' and not record.attempts
