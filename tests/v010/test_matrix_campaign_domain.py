"""Pure frozen applicability controls; no engine or scientific acceptance fixture."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from topos.matrix_campaign import CampaignPlan, create_plan
from topos.method_matrix import MATRIX_REVISION, resolve_row
from topos.models import Molecule, RunRequest
from topos.storage import digest_json

ROOT = Path(__file__).resolve().parents[2]


def water_request():
    return RunRequest(molecule=Molecule(symbols=['O', 'H', 'H'],
        coordinates=[[0, 0, 0], [.9572, 0, 0], [-.23999, .9273, 0]]),
        purpose='matrix', matrix_revision=MATRIX_REVISION, matrix_row_id='T3O-10s',
        budget_seconds=10, threads=1, memory_mb=256, n_candidates=1)


def complex_request():
    # An analytical typed request exercises declaration validation only.
    # These coordinates are not a native minimum or a measured reference.
    molecule = Molecule(symbols=['O', 'H', 'H', 'O', 'H', 'H'],
        coordinates=[[0, 0, 0], [.9572, 0, 0], [-.23999, .9273, 0],
                     [2.9, 0, 0], [3.8572, 0, 0], [2.66001, .9273, 0]],
        fragments=[[0, 1, 2], [3, 4, 5]],
        environment={'phase': 'gas'})
    request = water_request().model_dump(mode='json')
    request['molecule'] = molecule.model_dump(mode='json')
    return RunRequest.model_validate(request)


def release_definition(request=None):
    request = request or complex_request()
    row = resolve_row(request.matrix_row_id)
    return {'request': request.model_dump(mode='json'),
        'coverage_scope': 'source-domain-release',
        'domain_declaration': {
            'chemistry_domain': row.chemical_domain,
            'physical_environment': 'isolated-gas-phase',
            'system_class': 'noncovalent-complex',
            'fragment_partition': request.molecule.fragments,
            'molecule_sha256': digest_json(request.molecule.model_dump(mode='json')),
            'request_environment_sha256': digest_json(request.molecule.environment),
            'source_row_limits': row.limitations,
            'reviewed_variant_differences': [],
            'reviewer': 'pure contract control; no scientific acceptance',
            'reviewed_at': '2026-10-07T00:00:00+00:00',
            'applicability_rationale': 'Exercises the explicit source-target declaration only; chemical truth remains a scientific review obligation.'}}


def test_legacy_bare_monomer_request_is_explicitly_diagnostic_only():
    plan = create_plan(ROOT, [water_request().model_dump(mode='json')])
    case = plan['cases'][0]
    assert case['coverage_scope'] == 'diagnostic-control'
    assert case['domain_declaration'] is None
    assert case['domain_declaration_sha256'] is None
    assert plan['schema_version'] == 'topos-reviewed-matrix-campaign-plan/0.2.0'


def test_explicit_target_declaration_is_frozen_without_any_native_execution(monkeypatch):
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError('Pure declaration validation must not execute a process')

    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    definition = release_definition()
    plan = create_plan(ROOT, [definition])
    case = plan['cases'][0]
    assert case['coverage_scope'] == 'source-domain-release'
    assert case['domain_declaration'] == definition['domain_declaration']
    assert case['domain_declaration_sha256'] == digest_json(definition['domain_declaration'])
    assert case['recipe']['row']['chemical_domain'] == definition['domain_declaration']['chemistry_domain']
    assert CampaignPlan.model_validate(plan).model_dump(mode='json') == plan


def test_monomer_cannot_be_relabelled_as_source_domain_release():
    request = water_request().model_dump(mode='json')
    request['molecule']['fragments'] = [[0], [1, 2]]
    request['molecule']['environment'] = {'phase': 'gas'}
    with pytest.raises(ValueError, match='5–10'):
        create_plan(ROOT, [release_definition(RunRequest.model_validate(request))])


def test_release_scope_cannot_omit_its_domain_review():
    definition = release_definition()
    del definition['domain_declaration']
    with pytest.raises(ValueError, match='predeclared source-domain review'):
        create_plan(ROOT, [definition])


def test_diagnostic_control_cannot_attach_release_claims():
    definition = release_definition()
    definition['coverage_scope'] = 'diagnostic-control'
    with pytest.raises(ValueError, match='Diagnostic controls'):
        create_plan(ROOT, [definition])


@pytest.mark.parametrize('atoms', [4, 11])
def test_target_atom_limits_come_from_the_existing_source_domain(atoms):
    molecule = Molecule(symbols=['He'] * atoms, coordinates=[[i * 3, 0, 0] for i in range(atoms)],
        fragments=[list(range(atoms // 2)), list(range(atoms // 2, atoms))],
        environment={'phase': 'gas'})
    request = water_request().model_dump(mode='json')
    request['molecule'] = molecule.model_dump(mode='json')
    with pytest.raises(ValueError, match='5–10'):
        create_plan(ROOT, [release_definition(RunRequest.model_validate(request))])


@pytest.mark.parametrize('field,value,error', [
    ('chemistry_domain', 'An unreviewed domain', 'exact reviewed source-domain descriptor'),
    ('fragment_partition', [[0, 1], [2, 3, 4, 5]], 'exact indexed noncovalent fragment'),
    ('molecule_sha256', '0' * 64, 'typed molecular/environment identity'),
    ('request_environment_sha256', '0' * 64, 'typed molecular/environment identity'),
    ('source_row_limits', 'omitted restrictions', 'source-specific limits'),
    ('reviewed_variant_differences', ['invented equivalence'], 'scientific differences'),
    ('reviewed_at', '2100-01-01T00:00:00+00:00', 'precede'),
    ('reviewed_at', '2026-10-07T00:00:00', 'identify UTC'),
    ('physical_environment', 'liquid', 'isolated-gas-phase'),
    ('system_class', 'covalent molecule', 'noncovalent-complex'),
    ('reviewer', '', 'at least 1 character'),
    ('reviewer', '  ', 'nonblank'),
    ('applicability_rationale', '', 'at least 1 character'),
    ('applicability_rationale', '\t\n ', 'nonblank'),
])
def test_wrong_or_postdeclared_domain_claims_are_rejected(field, value, error):
    definition = release_definition()
    definition['domain_declaration'][field] = value
    with pytest.raises(ValueError, match=error):
        create_plan(ROOT, [definition])


@pytest.mark.parametrize('environment', [{}, {'phase': 'liquid', 'boundary': 'isolated'},
                                        {'phase': 'gas', 'boundary': 'periodic'}])
def test_source_release_environment_is_explicit_and_matches_the_typed_request(environment):
    request = complex_request().model_dump(mode='json')
    request['molecule']['environment'] = environment
    with pytest.raises(ValueError, match='typed environment'):
        create_plan(ROOT, [release_definition(RunRequest.model_validate(request))])


def test_fragment_partition_cannot_be_inferred_from_coordinates():
    request = complex_request().model_dump(mode='json')
    request['molecule']['fragments'] = []
    with pytest.raises(ValueError, match='at least 2 items|exact indexed noncovalent fragment'):
        create_plan(ROOT, [release_definition(RunRequest.model_validate(request))])


def test_typed_interfragment_bond_cannot_be_silently_relabelled_noncovalent():
    request = complex_request().model_dump(mode='json')
    request['molecule']['bonds'] = [{'atom1': 0, 'atom2': 3, 'order': 1, 'kind': 'covalent'}]
    with pytest.raises(ValueError, match='interfragment bond'):
        create_plan(ROOT, [release_definition(RunRequest.model_validate(request))])


def test_rechecksummed_changed_review_still_must_match_request_and_source():
    plan = create_plan(ROOT, [release_definition()])
    corrupt = copy.deepcopy(plan)
    case = corrupt['cases'][0]
    case['domain_declaration']['fragment_partition'] = [[0, 1], [2, 3, 4, 5]]
    case['domain_declaration_sha256'] = digest_json(case['domain_declaration'])
    with pytest.raises(ValueError, match='exact indexed noncovalent fragment'):
        CampaignPlan.model_validate(corrupt)


def test_old_plan_contract_cannot_acquire_new_release_scope_by_default():
    plan = create_plan(ROOT, [water_request().model_dump(mode='json')])
    plan['schema_version'] = 'topos-reviewed-matrix-campaign-plan/0.1.0'
    with pytest.raises(ValueError, match='Unknown matrix campaign plan contract'):
        CampaignPlan.model_validate(plan)
