"""Genuine rigid packing followed by independently executed quantum refinement."""
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from topos.config import SystemConfig
from topos.models import Molecule, RigidmolAtomParameter, RigidmolOptions, RunRequest
from topos.publication import export_bundle, verify_bundle
from topos.review import append_decision, create_ensemble_manifest
from topos.storage import RunStore
from topos.workflow import Workflow


def neon():
    molecule = Molecule(symbols=['Ne', 'Ne'], coordinates=[[0, 0, 0], [4, 0, 0]], fragments=[[0], [1]],
        fragment_states=[{'atom_indices':[0], 'charge':0, 'multiplicity':1}, {'atom_indices':[1], 'charge':0, 'multiplicity':1}])
    options = RigidmolOptions(atomic_parameters=[RigidmolAtomParameter(atom_id=i, charge_e=0.,
        epsilon_kj_mol=.1848, sigma_angstrom=2.9223) for i in molecule.atom_ids],
        parameter_source='ABCluster 3.4 misc/charmm36/ne.xyz: bms_dec03; https://zhjun-sci.com/abcluster.html',
        population=8, generations=8, max_saved_minima=4)
    return molecule, options


def test_abcluster_schema_requires_explicit_parameter_source_and_atom_mapping():
    molecule, options = neon()
    request = RunRequest(molecule=molecule, search_algorithm='abcluster', abcluster_options=options)
    assert request.abcluster_options.atomic_parameters[0].atom_id == molecule.atom_ids[0]
    schema = RunRequest.model_json_schema()
    assert 'abcluster' in schema['properties']['search_algorithm']['enum']
    assert 'RigidmolOptions' in schema['$defs'] and 'epsilon_kj_mol' in schema['$defs']['RigidmolAtomParameter']['properties']
    with pytest.raises(ValidationError, match='explicit abcluster_options'):
        RunRequest(molecule=molecule, search_algorithm='abcluster')
    with pytest.raises(ValidationError, match='match every input atom'):
        RunRequest(molecule=molecule, search_algorithm='abcluster', abcluster_options=options.model_copy(update={'atomic_parameters':options.atomic_parameters[:1]}))
    with pytest.raises(ValidationError, match='explicit abcluster sampler'):
        RunRequest(molecule=molecule, abcluster_options=options)


@pytest.mark.parametrize('updates', [dict(population=4), dict(generations=True), dict(amplitude_angstrom=float('nan')),
    dict(parameter_source='  '), dict(max_saved_minima=0)])
def test_abcluster_controls_are_explicit_finite_and_bounded(updates):
    _, options = neon()
    with pytest.raises(ValidationError):
        RigidmolOptions.model_validate({**options.model_dump(), **updates})


def test_missing_abcluster_cannot_silently_switch_sampler(tmp_path):
    molecule, options = neon()
    config = SystemConfig(execution_backend='development', executables={'abcluster':'/missing/rigidmol'})
    request = RunRequest(molecule=molecule, search_algorithm='abcluster', abcluster_options=options, budget_seconds=30)
    result = Workflow(tmp_path, config=config).run(request)
    assert result.status == 'unavailable' and not result.candidates
    assert len(result.attempts) == 1 and result.attempts[0].engine == 'abcluster'
    assert result.attempts[0].metadata['execution_kind'] == 'not-executed'
    assert not result.attempts[0].quantities


@pytest.mark.integration
def test_actual_abcluster_scores_are_never_quantum_candidate_energies(tmp_path):
    binary = os.environ.get('TOPOS_ABCLUSTER_EXECUTABLE')
    xtb = os.environ.get('TOPOS_XTB_EXECUTABLE')
    if not binary or not xtb:
        pytest.skip('Actual ABCluster 3.4 and xTB 6.7.1 required')
    assert Path(binary).is_file() and Path(xtb).is_file()
    molecule, options = neon()
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development', executables={'abcluster':binary,'xtb':xtb}))
    request = RunRequest(molecule=molecule, search_algorithm='abcluster', abcluster_options=options,
                         profile_id='xtb-vtight-v1', n_candidates=2, budget_seconds=60)
    result = workflow.run(request)
    assert result.status == 'completed', result.metadata.get('termination_reason')
    sampling = [a for a in result.attempts if a.metadata.get('role') == 'sampler']
    assert len(sampling) == 1 and sampling[0].engine == 'abcluster' and sampling[0].engine_version == '3.4'
    assert sampling[0].metadata['execution_kind'] == 'real' and not sampling[0].quantities
    assert sampling[0].metadata['raw_ensemble'] and sampling[0].artifacts
    native_score = sampling[0].metadata['raw_ensemble'][0]['energy_hartree']
    assert abs(native_score) < .001
    assert result.candidates
    for candidate in result.candidates:
        if candidate.status == 'eligible':
            attempt = next(a for a in result.attempts if a.attempt_id == candidate.attempt_id)
            assert attempt.engine == 'xtb' and attempt.metadata['execution_kind'] == 'real'
            assert candidate.energy_hartree < -1 and candidate.energy_hartree != native_score
    assert any('ABCLUSTER' in candidate.sources for candidate in result.candidates)
    assert any(citation['title'] == 'ABCluster rigidmol' for citation in result.metadata['citations'])
    assert not any(citation.get('title') == 'CREST' for citation in result.metadata['citations'])
    assert RunStore(tmp_path/result.run_id).verify()
    eligible = next(candidate for candidate in result.candidates if candidate.status == 'eligible')
    run_dir = tmp_path / result.run_id
    append_decision(run_dir, subject_id=eligible.candidate_id, action='accept', actor='integration-test',
                    reason='Test-only review of genuine independently refined quantum geometry')
    create_ensemble_manifest(run_dir, [eligible.candidate_id], actor='integration-test',
                             reason='Test-only scientific handoff from real ABCluster and xTB')
    bundle = tmp_path / 'export'
    exported = export_bundle(run_dir, bundle)
    assert verify_bundle(bundle) == exported
    assert exported['publication_status'] == 'not-published'
    assert native_score != json.loads((bundle / 'candidate-ledger.json').read_text())[0]['candidate']['energy_hartree']
    resumed = workflow.resume(tmp_path/result.run_id, invocation_budget_seconds=30)
    assert resumed.status == 'completed'
    assert len([a for a in resumed.attempts if a.metadata.get('role') == 'sampler']) == 1


@pytest.mark.integration
def test_actual_abcluster_association_keeps_explicit_quantum_monomer_stages(tmp_path):
    binary = os.environ.get('TOPOS_ABCLUSTER_EXECUTABLE')
    xtb = os.environ.get('TOPOS_XTB_EXECUTABLE')
    if not binary or not xtb:
        pytest.skip('Actual ABCluster and xTB required')
    from test_abcluster import methanol_dimer

    molecule, options = methanol_dimer()
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development', executables={'abcluster':binary,'xtb':xtb}))
    result = workflow.run(RunRequest(molecule=molecule, purpose='association', search_algorithm='abcluster',
        abcluster_options=options, profile_id='xtb-vtight-v1', n_candidates=1, budget_seconds=60))
    assert result.status == 'completed', result.metadata.get('termination_reason')
    advanced = result.metadata['advanced_result']
    path = tmp_path / result.run_id / advanced['result_path'] if isinstance(advanced, dict) else tmp_path / result.run_id / advanced
    native = json.loads(path.read_text())
    assert native['association_sampling_policy']['isolated_monomers'] == 'independent common-QM jiggle-quench'
    assert all(item['request']['search_algorithm'] == 'jiggle-quench' for item in native['monomer_runs'])
    assert native['complex_run']['request']['search_algorithm'] == 'abcluster'
    assert native['energies'] and native['small_fragment_bypass'] is False
