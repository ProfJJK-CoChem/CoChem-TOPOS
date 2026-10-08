"""Release-policy contracts only; no generated value represents native chemistry.

These declarations have no measured runs. Existing reference integration tests
independently exercise actual xTB evidence and immutable report recomputation.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from topos.models import Molecule, RunRequest
from topos.release import _reference_acceptance_test_coverage, release_gate, source_inventory
from topos.scientific_references import (
    B0_DEFINITION,
    CP_DEFINITION,
    FREQUENCY_DEFINITION,
    NUMERICAL_REFERENCE_OBLIGATIONS,
    REFERENCE_REQUIREMENTS,
    ROTOR_DEFINITION,
    ReferenceCampaign,
    ReferenceCase,
    ReferenceCaseCoverage,
    ReferenceCoverageReview,
    ReferenceRequirementCoverage,
    _assess_requirement_coverage,
    _validate_coverage_ledger,
    assess_campaign,
    freeze_plan,
    reference_ledger_scope,
    validate_plan,
    verify_release_coverage,
)
from topos.storage import IntegrityError, digest_json, file_digest

ROOT = Path(__file__).resolve().parents[2]


def case(observable='cp_interaction_energy', *, suffix='', domain='Declared water test domain'):
    molecule = Molecule(symbols=['O', 'H', 'H'], coordinates=[[0, 0, 0], [.96, 0, 0], [-.24, .93, 0]])
    role = {'cp_interaction_energy': 'frozen-complex-geometry', 'equilibrium_rotational_constants': 'optimized-stationary-geometry',
            'ground_state_rotational_constants': 'ground-state-average', 'harmonic_frequencies': 'harmonic-minimum',
            'gibbs_energy': 'harmonic-minimum'}[observable]
    definition = {'cp_interaction_energy': CP_DEFINITION, 'equilibrium_rotational_constants': ROTOR_DEFINITION,
                  'ground_state_rotational_constants': B0_DEFINITION, 'harmonic_frequencies': FREQUENCY_DEFINITION,
                  'gibbs_energy': 'Declared RRHO Gibbs observable with explicit reference state'}[observable]
    request = RunRequest(molecule=molecule, engine='orca', method='r2SCAN-3c', purpose='optimize' if
                         role == 'optimized-stationary-geometry' else 'energy')
    return ReferenceCase(case_id=observable + suffix, chemistry_domain=domain, request=request, observable=observable,
        definition=definition, units='cm^-1' if observable == 'harmonic_frequencies' else
        'GHz' if 'rotational_constants' in observable else 'hartree', geometry_role=role, engine_version='6.1.1',
        reference_file='unmeasured-contract-data.json', reference_sha256='a'*64, datum_id=observable + suffix,
        citation={'kind': 'official-documentation', 'title': 'Unexecuted schema fixture', 'locator': 'contract-only',
                  'extraction_notes': 'No measured or literature chemistry value is supplied by this contract fixture'},
        tolerance={'absolute': .1, 'relative': 0., 'rationale': 'Unexecuted schema fixture, not an accuracy acceptance limit'},
        reference_protocol={'method': 'Explicit contract method', 'basis': 'Explicit contract basis', 'core_treatment': 'Declared',
            'counterpoise': 'Declared', 'geometry_convention': 'Explicit contract geometry role', 'geometry_role': role,
            'geometry_sha256': digest_json(molecule.model_dump(mode='json', exclude={'name'})) if role == 'frozen-complex-geometry' else None,
            'energy_zero': 'Declared', 'state_and_environment': 'Gas-phase singlet', 'isotope_mass_convention': 'Declared',
            'source_limitations': 'No physical value or measurement is being attested'},
        comparison_rationale='Control-plane schema test only; cannot pass native evidence verification')


@pytest.fixture
def ledger(tmp_path):
    value = json.loads((ROOT / '.docs/TOPOS_SRS_ACCEPTANCE.json').read_text())
    # This is a schema fixture, not new evidence or a modified checked-in ledger.
    value['srs_sha256'] = file_digest(ROOT / '.docs/CoChem-TOPOS_SRS.md')
    current = source_inventory(ROOT)
    for entry in value['requirements'].values():
        for item in entry['implementation'] + entry['acceptance_tests']:
            item['sha256'] = current.get(item['path'])
    path = tmp_path / 'reviewed-ledger.json'
    path.write_text(json.dumps(value))
    return value, path


def disposition(ledger, requirement, cases=()):
    entry = ledger['requirements'][requirement]
    target = next(item for item in entry['acceptance_tests'] if item.get('test_functions'))
    claims = [ReferenceCaseCoverage(case_id=item.case_id, chemistry_domain=item.chemistry_domain,
        observable=item.observable, context_sha256=digest_json(item.context()),
        scientific_scope='Only this explicitly declared observable and domain', rationale='Explicit fixture applicability')
        for item in cases]
    return ReferenceRequirementCoverage(requirement_id=requirement,
        requirement_source_sha256=digest_json(entry['requirement_source']),
        applicability='numerical-reference' if requirement in NUMERICAL_REFERENCE_OBLIGATIONS else 'non-numerical-contract',
        requirement_scope='The reference-comparison aspect only; all other SRS behaviors remain separately tested',
        rationale='Native numerical agreement and algorithmic correctness require different evidence',
        exclusions='No global chemical accuracy, exhaustive search, deduplication correctness or unavailable engine certification',
        acceptance_test_references=[target['path']+'::'+target['test_functions'][0]],
        required_chemistry_domains=sorted({item.chemistry_domain for item in cases}), case_claims=claims)


def campaign(ledger, path, rows, cases):
    review = ReferenceCoverageReview(srs_sha256=ledger['srs_sha256'], acceptance_ledger_file=str(path),
        acceptance_ledger_sha256=file_digest(path), acceptance_ledger_scope_sha256=digest_json(reference_ledger_scope(ledger)),
        reviewer='Schema test reviewer, not a physical review', reviewed_at='2026-01-01T00:00:00+00:00',
        review_rationale='Explicitly unexecuted coverage declaration for contract validation', requirements=rows)
    return ReferenceCampaign(campaign_id='unmeasured-contract', assessment_kind='scientific-reference',
        predeclaration_rationale='Unexecuted schema test', cases=cases, requirement_coverage=review)


def test_one_cp_case_cannot_complete_the_twenty_reference_obligations(ledger):
    value, path = ledger
    cp = case()
    declared = campaign(value, path, [disposition(value, 'TOPOS-010-033', [cp])], [cp])
    # Categorical comparison outcome only; no RunStore or native value exists.
    coverage = _assess_requirement_coverage(declared, [{'case_id': cp.case_id, 'status': 'passed'}])
    assert coverage['complete_for_reference_condition'] is False
    assert len(coverage['missing_requirements']) == 19
    assert coverage['requirements']['TOPOS-010-033']['full_requirement_verified'] is False
    with pytest.raises(ValueError, match='Complete reviewed'):
        verify_release_coverage({'assessment_kind': 'scientific-reference', 'requirement_coverage': coverage}, value)


@pytest.mark.parametrize('requirement', ['TOPOS-010-029', 'TOPOS-010-031', 'TOPOS-010-034'])
def test_cp_energy_cannot_substitute_for_spectroscopy_derivatives_or_thermal_observables(ledger, requirement):
    value, _ = ledger
    with pytest.raises(ValueError, match='relevant cases'):
        disposition(value, requirement, [case()])


@pytest.mark.parametrize('requirement', ['TOPOS-010-019', 'TOPOS-010-026', 'TOPOS-010-028', 'TOPOS-010-035', 'TOPOS-010-036'])
def test_numerical_agreement_cannot_certify_algorithmic_requirements(ledger, requirement):
    value, _ = ledger
    with pytest.raises(ValueError, match='Non-numerical contracts'):
        disposition(value, requirement, [case()])


def test_each_predeclared_domain_needs_all_observable_roles(ledger):
    value, _ = ledger
    be = case('equilibrium_rotational_constants', domain='Domain A')
    b0 = case('ground_state_rotational_constants', domain='Domain B')
    with pytest.raises(ValueError, match='Each reviewed chemistry domain'):
        disposition(value, 'TOPOS-010-029', [be, b0])
    with pytest.raises(ValueError, match='Each reviewed chemistry domain'):
        disposition(value, 'TOPOS-010-034', [case('harmonic_frequencies')])


@pytest.mark.parametrize('damage', ['case-id', 'context', 'domain', 'observable', 'calibration'])
def test_coverage_claims_cannot_change_case_identity_or_promote_calibration(ledger, damage):
    value, path = ledger
    cp = case()
    document = campaign(value, path, [disposition(value, 'TOPOS-010-033', [cp])], [cp]).model_dump(mode='json')
    claim = document['requirement_coverage']['requirements'][0]['case_claims'][0]
    if damage == 'case-id':
        claim['case_id'] = 'absent'
    elif damage == 'context':
        claim['context_sha256'] = 'b'*64
    elif damage == 'domain':
        claim['chemistry_domain'] = 'Different chemical domain'
    elif damage == 'observable':
        claim['observable'] = 'gibbs_energy'
    else:
        document['assessment_kind'] = 'reproducibility-calibration'
    with pytest.raises(ValueError):
        ReferenceCampaign.model_validate(document)


@pytest.mark.parametrize('damage', ['ledger-bytes', 'clause', 'wrong-clause-under-valid-id', 'unlisted-test', 'stale-test', 'srs'])
def test_review_binds_exact_ledger_clause_test_and_srs(ledger, damage):
    value, path = ledger
    declared = campaign(value, path, [disposition(value, 'TOPOS-010-019')], [case()])
    if damage == 'ledger-bytes':
        path.write_text(path.read_text()+'\n')
    elif damage == 'clause':
        declared.requirement_coverage.requirements[0].requirement_source_sha256 = 'b'*64
    elif damage == 'wrong-clause-under-valid-id':
        replacement = value['requirements']['TOPOS-010-033']['requirement_source']
        value['requirements']['TOPOS-010-019']['requirement_source'] = replacement
        declared.requirement_coverage.requirements[0].requirement_source_sha256 = digest_json(replacement)
        path.write_text(json.dumps(value))
        declared.requirement_coverage.acceptance_ledger_sha256 = file_digest(path)
        declared.requirement_coverage.acceptance_ledger_scope_sha256 = digest_json(reference_ledger_scope(value))
    elif damage == 'unlisted-test':
        declared.requirement_coverage.requirements[0].acceptance_test_references = ['tests/other.py::test_invented']
    elif damage == 'stale-test':
        item = value['requirements']['TOPOS-010-019']['acceptance_tests'][0]
        item['sha256'] = 'b'*64
        path.write_text(json.dumps(value))
        declared.requirement_coverage.acceptance_ledger_sha256 = file_digest(path)
        declared.requirement_coverage.acceptance_ledger_scope_sha256 = digest_json(reference_ledger_scope(value))
    else:
        declared.requirement_coverage.srs_sha256 = 'b'*64
    with pytest.raises(IntegrityError):
        _validate_coverage_ledger(declared, path, source_root=ROOT)


def test_scope_binding_allows_receipt_updates_but_not_changed_scientific_claims(ledger):
    value, _ = ledger
    before = digest_json(reference_ledger_scope(value))
    value['requirements']['TOPOS-010-033']['status'] = 'verified'
    value['requirements']['TOPOS-010-033']['additional_acceptance_conditions'] = []
    value['requirements']['TOPOS-010-033']['evidence'] = [{'scope': 'Bookkeeping update only'}]
    assert digest_json(reference_ledger_scope(value)) == before
    value['requirements']['TOPOS-010-033']['assessment'] += ' Changed scientific coverage.'
    assert digest_json(reference_ledger_scope(value)) != before


def test_named_acceptance_tests_require_actual_passing_parameterizations():
    coverage = {'requirements': {'TOPOS-010-026': {
        'acceptance_test_references': ['tests/v010/test_science.py::test_identity']}}}
    real_names = {'tests.v010.test_science::test_identity[proper]': 'passed',
                  'tests.v010.test_science::test_identity[reflection]': 'passed'}
    assert len(_reference_acceptance_test_coverage(coverage, real_names)['TOPOS-010-026']) == 2
    for actual in ({}, {**real_names, 'tests.v010.test_science::test_identity[reflection]': 'skipped'},
                   {'other.test_science::test_identity': 'passed'}):
        with pytest.raises(ValueError, match='executed passing'):
            _reference_acceptance_test_coverage(coverage, actual)


def test_legacy_campaign_pass_flag_cannot_clear_release_condition(tmp_path, monkeypatch):
    import topos.scientific_references as references

    path = tmp_path/'unscoped-report.json'
    claim = {'status': 'passed', 'source_sha256': source_inventory(ROOT), 'release_eligible': True,
             'assessment_kind': 'scientific-reference'}
    path.write_text(json.dumps(claim))
    # Negative release-boundary control: even a legacy verifier's broad pass
    # cannot replace the new independently required coverage inventory.
    monkeypatch.setattr(references, 'verify_report', lambda *args: claim)
    result = release_gate(ROOT, scientific_reference_campaign=path)
    assert result['release_certified'] is False
    assert any('Complete reviewed per-requirement' in reason for reason in result['blockers'])


def test_frozen_unmeasured_review_is_portable_and_cannot_be_edited(ledger, tmp_path):
    value, ledger_path = ledger
    cp = case()
    datum = {'schema_version': 'topos-reference-data/1', 'data': {cp.datum_id: {
        'name': 'Unmeasured schema fixture, not a literature or native result', 'context_sha256': digest_json(cp.context()),
        'value': 1., 'uncertainty': None, 'uncertainty_definition': 'No physical uncertainty claim'}}}
    reference = tmp_path/cp.reference_file
    reference.write_text(json.dumps(datum))
    cp.reference_sha256 = file_digest(reference)
    declared = campaign(value, ledger_path, [disposition(value, 'TOPOS-010-033', [cp])], [cp])
    plan = tmp_path/'plan.json'
    plan.write_text(declared.model_dump_json())
    assert validate_plan(plan) == declared
    frozen = freeze_plan(plan, tmp_path/'frozen', tmp_path/'measurements', source_root=ROOT)
    report = assess_campaign(frozen, {}, source_root=ROOT)
    assert report['status'] == 'pending' and report['release_eligible'] is False
    assert report['requirement_coverage']['requirements']['TOPOS-010-033']['status'] == 'pending-or-failed-reference'
    retained = frozen.parent/'reviewed-acceptance-ledger.json'
    assert file_digest(retained) == declared.requirement_coverage.acceptance_ledger_sha256
    payload = json.loads(frozen.read_text())
    payload['plan']['requirement_coverage']['requirements'][0]['rationale'] = 'Changed after freeze'
    frozen.write_text(json.dumps(payload))
    with pytest.raises(IntegrityError, match='identity changed'):
        assess_campaign(frozen, {}, source_root=ROOT)


def test_complete_inventory_still_requires_all_declared_measurements(ledger):
    value, path = ledger
    cases = [case(observable) for observable in ('equilibrium_rotational_constants', 'ground_state_rotational_constants',
             'harmonic_frequencies', 'gibbs_energy', 'cp_interaction_energy')]
    rows = []
    for requirement in REFERENCE_REQUIREMENTS:
        allowed = set().union(*NUMERICAL_REFERENCE_OBLIGATIONS.get(requirement, (set(),)))
        rows.append(disposition(value, requirement, [item for item in cases if item.observable in allowed]))
    declared = campaign(value, path, rows, cases)
    _validate_coverage_ledger(declared, path, source_root=ROOT)
    missing = [{'case_id': item.case_id, 'status': 'pending'} for item in cases]
    coverage = _assess_requirement_coverage(declared, missing)
    assert not coverage['missing_requirements']
    assert coverage['complete_for_reference_condition'] is False
    changed = copy.deepcopy(value)
    changed['requirements'].pop('TOPOS-010-049')
    with pytest.raises(ValueError, match='complete 50-requirement'):
        reference_ledger_scope(changed)
