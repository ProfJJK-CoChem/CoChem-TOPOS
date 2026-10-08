"""Reference predeclaration and native evidence rejection; no invented chemistry."""
from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

import pytest

from topos.config import SystemConfig
from topos.models import Molecule, RunRecord, RunRequest
from topos.scientific_references import (
    B0_DEFINITION,
    ENERGY_DEFINITION,
    ROTOR_DEFINITION,
    ReferenceCampaign,
    ReferenceCase,
    _native_value,
    assess_campaign,
    freeze_plan,
    main,
    validate_plan,
    verify_report,
    write_report,
)
from topos.storage import IntegrityError, RunStore, digest_json, file_digest
from topos.workflow import Workflow

ROOT = Path(__file__).resolve().parents[2]


def _plan(folder, request, value, *, reference_kind='native-reproducibility-calibration', assessment_kind='reproducibility-calibration'):
    """A caller-supplied calibration value; never a fabricated literature datum."""
    case = ReferenceCase(case_id='water-energy', chemistry_domain='neutral closed-shell gas-phase water at fixed input geometry',
        request=request, observable='electronic_energy', definition=ENERGY_DEFINITION, units='hartree',
        geometry_role='supplied-input', engine_version='6.7.1', reference_file='reference-data.json',
        reference_protocol={'method':'GFN2-xTB 6.7.1', 'basis':'Native GFN2-xTB minimal valence basis',
            'core_treatment':'GFN2-xTB native effective core model', 'counterpoise':'Not applicable to this absolute electronic energy',
            'geometry_convention':'Exact supplied water geometry', 'energy_zero':'Native GFN2-xTB total electronic energy convention',
            'geometry_role':'supplied-input', 'geometry_sha256':digest_json(request.molecule.model_dump(mode='json',exclude={'name'})),
            'state_and_environment':'Neutral singlet gas phase', 'isotope_mass_convention':'Default isotope convention',
            'source_limitations':'Native repeatability only; no independently published physical accuracy'},
        comparison_rationale='Compare an independently executed preceding native result at the identical declared protocol for numerical repeatability only',
        reference_sha256='0'*64, datum_id='water-energy', citation={
            'title':'Independent prior native xTB reproducibility observation',
            'locator':'Caller-supplied independently retained native reference; not publication accuracy',
            'kind':reference_kind, 'extraction_notes':'Same geometry/native protocol; numerical repeatability only'},
        tolerance={'absolute':1e-8, 'relative':0., 'rationale':'Test caller predeclares numeric repeatability, not a physical accuracy threshold'})
    data = {'schema_version':'topos-reference-data/1', 'data': {'water-energy':{
        'name':'Actual preceding native electronic energy', 'context_sha256':digest_json(case.context()),
        'value':value, 'uncertainty':None, 'uncertainty_definition':'Not calibrated; never added to tolerance'}}}
    data_path=folder/'reference-data.json'
    data_path.write_text(json.dumps(data))
    case=case.model_copy(update={'reference_sha256':file_digest(data_path)})
    campaign=ReferenceCampaign(campaign_id='water-repeatability', assessment_kind=assessment_kind,
        predeclaration_rationale='Freeze before independently executing the measured job; retain calibration limits', cases=[case])
    path=folder/'plan.json'
    path.write_text(campaign.model_dump_json(indent=2))
    return path


@pytest.fixture(scope='module')
def measured_campaign(tmp_path_factory):
    binary=shutil.which(os.environ.get('TOPOS_XTB_EXECUTABLE','xtb'))
    if not binary:
        pytest.skip('A genuine xTB executable is required for reference-campaign integration')
    folder=tmp_path_factory.mktemp('actual-reference-campaign')
    request=RunRequest(molecule=Molecule(symbols=['O','H','H'],coordinates=[[0,0,0],[.9584,0,0],[-.239,.927,0]]),
        purpose='energy',engine='xtb',method='GFN2-xTB',profile_id='xtb-tight-v1',budget_seconds=60,threads=1,memory_mb=2048)
    config=SystemConfig(execution_backend='development',executables={'xtb':binary})
    prior=Workflow(folder/'prior-native',config=config).run(request)
    assert prior.status=='completed'
    source=next(candidate for candidate in prior.candidates if candidate.status=='eligible')
    plan=_plan(folder,request,source.energy_hartree)
    frozen=freeze_plan(plan,folder/'frozen',folder/'measurements',source_root=ROOT)
    measured=Workflow(folder/'measurements',config=config).run(request)
    assert measured.status=='completed'
    run=folder/'measurements'/measured.run_id
    store=RunStore(run)
    bindings={'water-energy':{'run_dir':str(run),'record_sha256':store.verify()['record_sha256']}}
    return folder,plan,frozen,run,bindings


def _bad_run(source, measured_campaign, tmp_path, mutate):
    """Repackage genuine native bytes solely to require corrupt-record rejection."""
    _,_,frozen,_,_=measured_campaign
    data=RunStore(source).load()
    mutate(data)
    destination=(frozen.parent/json.loads(frozen.read_text())['measurement_root']).resolve()/tmp_path.name
    shutil.copytree(RunStore(source).snapshot_path()/'artifacts',destination)
    store=RunStore(destination)
    store.commit(RunRecord.model_validate(data))
    return {'water-energy':{'run_dir':str(destination),'record_sha256':store.verify()['record_sha256']}}


def test_actual_native_repeatability_stays_pending_for_scientific_release(measured_campaign,tmp_path):
    _,_,frozen,_,bindings=measured_campaign
    report=write_report(frozen,bindings,frozen.parent.parent/(tmp_path.name+'-assessment.json'),source_root=ROOT)
    assert report['status']=='pending' and report['comparison_status']=='passed'
    assert report['calibration_passed'] is True and report['release_eligible'] is False
    assert report['scientific_reference_campaign'] is False
    assert report['base_authority_verified'] is False
    assert report['cases'][0]['base_authority_verified'] is False
    assert report['cases'][0]['native']['engine_version']=='6.7.1'
    assert report['cases'][0]['verified_snapshot_history']
    assert verify_report(frozen.parent.parent/(tmp_path.name+'-assessment.json'),ROOT)==report


def test_borrowed_native_bytes_cannot_be_promoted_by_a_base_label_and_arbitrary_registry_hash(measured_campaign, tmp_path):
    _, _, frozen, run, _ = measured_campaign

    def relabel(record):
        record['metadata']['execution_provider'] = 'CoChem-BASE'
        record['metadata']['execution_authority'] = {
            'backend': 'cochem-base', 'registry_sha256': 'a'*64, 'registry_checksum': 'b'*64,
            'ecosystem': {'available': True, 'problems': [], 'components': {
                name: {'available': True} for name in ('CoChem-BASE', 'CoChem-TOPOS', 'CoChem-TORQ')}}}

    bindings = _bad_run(run, measured_campaign, tmp_path, relabel)
    # Deliberate negative control: a relabelled calibration is NOT independent
    # literature evidence. These edits imitate a forged claim only to reject it.
    payload = json.loads(frozen.read_text())
    payload['plan']['assessment_kind'] = 'scientific-reference'
    payload['plan']['cases'][0]['citation']['kind'] = 'official-documentation'
    payload['freeze_sha256'] = digest_json({key: value for key, value in payload.items() if key != 'freeze_sha256'})
    forged = frozen.parent/(tmp_path.name+'-forged.json')
    forged.write_text(json.dumps(payload))
    report = assess_campaign(forged, bindings, source_root=ROOT)
    assert report['comparison_status'] == 'passed'  # Unchanged genuine numeric result remains diagnostically usable.
    assert report['status'] == 'pending'
    assert report['release_eligible'] is False and report['base_authority_verified'] is False
    assert report['cases'][0]['base_authority'] is None
    assert 'retained Stage 0 registry' in report['cases'][0]['authority_release_blocker']


@pytest.mark.integration
def test_actual_base_calibration_retains_and_reverifies_portable_registry_authority(tmp_path):
    """Two real BASE xTB observations; never independent physical accuracy."""
    path = os.environ.get('COCHEM_CONFIG')
    if not path or not Path(path).is_file():
        if os.environ.get('TOPOS_REQUIRE_BASE') == '1':
            pytest.fail('Actual BASE reference acceptance requires the completed Stage 0 registry')
        pytest.skip('Actual BASE Stage 0 registry is unavailable')
    config = SystemConfig(execution_backend='base', base_registry_path=Path(path))
    request = RunRequest(molecule=Molecule(symbols=['O','H','H'], coordinates=[[0,0,0],[.9584,0,0],[-.239,.927,0]]),
                         purpose='energy', engine='xtb', method='GFN2-xTB', profile_id='xtb-tight-v1',
                         budget_seconds=30, threads=1, memory_mb=1024)
    prior = Workflow(tmp_path/'prior', config=config).run(request)
    assert prior.status == 'completed', prior.metadata.get('termination_reason')
    energy = next(candidate.energy_hartree for candidate in prior.candidates if candidate.status == 'eligible')
    plan = _plan(tmp_path, request, energy)
    frozen = freeze_plan(plan, tmp_path/'frozen', tmp_path/'measurements', source_root=ROOT)
    observed = Workflow(tmp_path/'measurements', config=config).run(request)
    assert observed.status == 'completed', observed.metadata.get('termination_reason')
    store = RunStore(observed.metadata['run_dir'])
    bindings = {'water-energy': {'run_dir': str(store.run_dir), 'record_sha256': store.verify()['record_sha256']}}
    retained = tmp_path/'actual-base-registry.json'
    retained.write_bytes(Path(path).read_bytes())
    summary = Path(path).parent/'setup_summary.json'
    if not summary.is_file() or summary.is_symlink():
        pytest.fail('Actual BASE reference acceptance requires its retained eleven-phase setup reports')
    (tmp_path/'setup_summary.json').write_bytes(summary.read_bytes())
    report_path = tmp_path/'base-reference-report.json'
    report = write_report(frozen, bindings, report_path, source_root=ROOT, base_registry_paths=[retained])
    assert report['comparison_status'] == 'passed' and report['base_authority_verified'] is True
    assert report['status'] == 'pending' and report['release_eligible'] is False
    assert report['cases'][0]['base_authority']['native_attempts'][0]['engine'] == 'xtb'
    assert report['base_registries'][0]['registry_sha256'] == observed.metadata['execution_authority']['registry_sha256']
    assert len(report['base_registries'][0]['verified_phase_reports']) == 11
    assert report['base_registries'][0]['setup_summary_sha256'] == file_digest(tmp_path/'setup_summary.json')
    relocated = tmp_path/'portable'
    relocated.mkdir()
    for name in ('frozen', 'measurements'):
        shutil.copytree(tmp_path/name, relocated/name)
    for name in (retained.name, report_path.name, 'setup_summary.json'):
        shutil.copyfile(tmp_path/name, relocated/name)
    assert verify_report(relocated/report_path.name, ROOT) == report
    # A changed checksum or stripped registry cannot preserve a claimed pass.
    changed = json.loads((relocated/retained.name).read_text())
    changed['hardware']['ram_gb'] += 1
    (relocated/retained.name).write_text(json.dumps(changed))
    with pytest.raises(IntegrityError, match='registry|Registry|checksum'):
        verify_report(relocated/report_path.name, ROOT)
    shutil.copyfile(retained, relocated/retained.name)
    changed_setup = json.loads((relocated/'setup_summary.json').read_text())
    changed_setup['phases_executed'][0]['report']['status'] = 'changed-setup-evidence'
    (relocated/'setup_summary.json').write_text(json.dumps(changed_setup))
    with pytest.raises(IntegrityError, match='setup reports'):
        verify_report(relocated/report_path.name, ROOT)


def test_reference_plan_frozen_without_any_measurement_reports_pending(measured_campaign):
    _,_,frozen,_,_=measured_campaign
    report=assess_campaign(frozen,{},source_root=ROOT)
    assert report['status']=='pending' and report['cases'][0]['status']=='pending'


@pytest.mark.parametrize('field,value', [('observable','gibbs_energy'),('units','GHz'),
    ('geometry_role','ground-state-average'),('engine_version','6.6.6')])
def test_reference_context_prevents_quantity_unit_geometry_or_version_substitution(measured_campaign,tmp_path,field,value):
    _,plan,_,_,_=measured_campaign
    document=json.loads(plan.read_text())
    document['cases'][0][field]=value
    path=tmp_path/'plan.json'
    document['cases'][0]['reference_file']=str(plan.parent/'reference-data.json')
    path.write_text(json.dumps(document))
    with pytest.raises((ValueError,IntegrityError)):
        validate_plan(path)


def test_native_calibration_cannot_be_relabelled_as_independent_reference(measured_campaign,tmp_path):
    _,plan,_,_,_=measured_campaign
    data=json.loads(plan.read_text())
    data['assessment_kind']='scientific-reference'
    with pytest.raises(ValueError,match='reproducibility'):
        ReferenceCampaign.model_validate(data)


def test_freeze_rejects_preexisting_measurement_directory_and_overwrite(measured_campaign,tmp_path):
    _,plan,_,run,_=measured_campaign
    with pytest.raises(ValueError,match='fresh'):
        freeze_plan(plan,tmp_path/'frozen',run,source_root=ROOT)


def test_reference_data_checksum_and_context_cannot_change(measured_campaign,tmp_path):
    _,plan,_,_,_=measured_campaign
    data=json.loads(plan.read_text())
    original=plan.parent/'reference-data.json'
    copied=tmp_path/'changed-data.json'
    copied.write_bytes(original.read_bytes()+b' ')
    data['cases'][0]['reference_file']=str(copied)
    path=tmp_path/'plan.json'
    path.write_text(json.dumps(data))
    with pytest.raises(IntegrityError,match='checksum'):
        validate_plan(path)
    changed=json.loads(original.read_text())
    changed['data']['water-energy']['context_sha256']='0'*64
    copied.write_text(json.dumps(changed))
    data['cases'][0]['reference_sha256']=file_digest(copied)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='conditions differ'):
        validate_plan(path)


def test_post_hoc_frozen_tolerance_change_is_rejected(measured_campaign,tmp_path):
    _,_,frozen,_,bindings=measured_campaign
    document=json.loads(frozen.read_text())
    document['plan']['cases'][0]['tolerance']['absolute']=999.
    changed=tmp_path/'frozen.json'
    changed.write_text(json.dumps(document))
    with pytest.raises(IntegrityError,match='identity changed'):
        assess_campaign(changed,bindings,source_root=ROOT)


def test_current_source_and_frozen_source_must_match(measured_campaign,tmp_path):
    _,_,frozen,_,bindings=measured_campaign
    document=json.loads(frozen.read_text())
    document['source_sha256']['topos/scientific_references.py']='0'*64
    document['freeze_sha256']=digest_json({key:value for key,value in document.items() if key!='freeze_sha256'})
    changed=tmp_path/'frozen.json'
    changed.write_text(json.dumps(document))
    with pytest.raises(IntegrityError,match='source differs'):
        assess_campaign(changed,bindings,source_root=ROOT)


@pytest.mark.parametrize('mutation', ['early-created','early-attempt','fake-execution','wrong-method','wrong-profile','failed-process','altered-value','wrong-geometry'])
def test_repackaged_native_records_cannot_pass_reference_assessment(measured_campaign,tmp_path,mutation):
    _,_,frozen,run,_=measured_campaign
    def mutate(record):
        attempt=next(row for row in record['attempts'] if row['status']=='completed')
        if mutation=='early-created':
            record['created_at']='2000-01-01T00:00:00+00:00'
        elif mutation=='early-attempt':
            attempt['started_at']='2000-01-01T00:00:00+00:00'
        elif mutation=='fake-execution':
            attempt['metadata']['execution_kind']='test-double'
        elif mutation=='wrong-method':
            attempt['method']='GFN-FF'
        elif mutation=='wrong-profile':
            attempt['metadata']['requested_method']['profile_id']='other-profile'
        elif mutation=='failed-process':
            attempt['diagnostics']['process']['returncode']=1
        elif mutation=='altered-value':
            next(quantity for quantity in attempt['quantities'] if quantity['name']=='electronic_energy')['value']+=1.
        else:
            record['candidates'][0]['molecule']['coordinates'][0][0]+=.1
    bindings=_bad_run(run,measured_campaign,tmp_path,mutate)
    with pytest.raises((ValueError,IntegrityError)):
        assess_campaign(frozen,bindings,source_root=ROOT)


def test_selected_snapshot_and_assessment_payload_are_recomputed(measured_campaign,tmp_path):
    _,_,frozen,_,bindings=measured_campaign
    invalid=copy.deepcopy(bindings)
    invalid['water-energy']['record_sha256']='0'*64
    with pytest.raises(IntegrityError,match='snapshot changed'):
        assess_campaign(frozen,invalid,source_root=ROOT)
    path=frozen.parent.parent/(tmp_path.name+'-report.json')
    report=write_report(frozen,bindings,path,source_root=ROOT)
    report['release_eligible']=True
    report['scientific_reference_campaign']=True
    report['status']='passed'
    path.write_text(json.dumps(report))
    with pytest.raises(IntegrityError,match='recomputed'):
        verify_report(path,ROOT)


def test_cli_schema_validation_and_genuine_calibration_assessment(measured_campaign,tmp_path,capsys):
    _,plan,frozen,_,bindings=measured_campaign
    assert main(['schema'])==0
    capsys.readouterr()
    assert main(['validate',str(plan)])==0
    binding_path=tmp_path/'bindings.json'
    binding_path.write_text(json.dumps(bindings))
    assert main(['assess',str(frozen),'--bindings',str(binding_path),'--output',str(frozen.parent.parent/(tmp_path.name+'-assessment.json'))])==3
    assert '"status": "pending"' in capsys.readouterr().out


def test_portable_bundle_relocation_recomputes_identical_native_comparison(measured_campaign,tmp_path):
    folder,_,frozen,_,bindings=measured_campaign
    original=folder/(tmp_path.name+'-portable.json')
    report=write_report(frozen,bindings,original,source_root=ROOT)
    moved=tmp_path/'relocated-campaign'
    moved.mkdir()
    shutil.copytree(folder/'frozen',moved/'frozen')
    shutil.copytree(folder/'measurements',moved/'measurements')
    shutil.copyfile(original,moved/original.name)
    assert verify_report(moved/original.name,ROOT)==report
    assert not Path(report['frozen_plan']).is_absolute()
    assert all(not Path(binding['run_dir']).is_absolute() for binding in report['measured_runs'].values())


def test_accuracy_reference_protocol_is_separate_from_tested_hamiltonian(measured_campaign,tmp_path):
    _,plan,_,_,_=measured_campaign
    document=json.loads(plan.read_text())
    case=document['cases'][0]
    case['reference_file']=str(plan.parent/'reference-data.json')
    case['reference_protocol']['method']='Different explicitly named independent reference method'
    path=tmp_path/'plan.json'
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError,match='Hamiltonian'):
        validate_plan(path)
    # The schema permits different reference and measured methods, but a
    # previously extracted datum cannot silently acquire a different protocol.
    declared=ReferenceCampaign.model_validate(document)
    assert declared.cases[0].request.method=='GFN2-xTB'
    assert declared.cases[0].reference_protocol.method!=declared.cases[0].request.method


@pytest.mark.parametrize('field,value',[('absolute',float('nan')),('relative',float('inf')),('absolute',-1.),('relative',True)])
def test_predeclared_tolerances_reject_nonfinite_negative_and_boolean_limits(measured_campaign,field,value):
    _,plan,_,_,_=measured_campaign
    document=json.loads(plan.read_text())
    document['cases'][0]['tolerance'][field]=value
    with pytest.raises(ValueError):
        ReferenceCampaign.model_validate(document)


def test_arbitrary_report_paths_cannot_escape_portable_bundle(measured_campaign,tmp_path):
    folder,_,frozen,_,bindings=measured_campaign
    with pytest.raises(ValueError,match='bundle root'):
        write_report(frozen,bindings,tmp_path/'outside.json',source_root=ROOT)
    report_path=folder/(tmp_path.name+'-escape.json')
    report=write_report(frozen,bindings,report_path,source_root=ROOT)
    report['measured_runs']['water-energy']['run_dir']='../external-untrusted-run'
    report_path.write_text(json.dumps(report))
    with pytest.raises(IntegrityError,match='escapes'):
        verify_report(report_path,ROOT)


def test_actual_equilibrium_rotors_cannot_be_imported_as_native_ground_state_constants(measured_campaign):
    _,plan,_,run,_=measured_campaign
    case=validate_plan(plan).cases[0].model_copy(update={
        'observable':'ground_state_rotational_constants','geometry_role':'ground-state-average',
        'definition':B0_DEFINITION,'units':'GHz'})
    store=RunStore(run)
    record=RunRecord.model_validate(store.load())
    assert record.candidates[0].metadata['rotational_constants']['not_measured_B0'] is True
    with pytest.raises(IntegrityError,match='Be cannot substitute'):
        _native_value(case,record,store)


def test_arbitrary_fixed_geometry_cannot_be_predeclared_as_equilibrium_rotor_reference(measured_campaign):
    _,plan,_,_,_=measured_campaign
    document=json.loads(plan.read_text())
    document['cases'][0].update(observable='equilibrium_rotational_constants',definition=ROTOR_DEFINITION,units='GHz')
    with pytest.raises(ValueError,match='unconstrained stationary'):
        ReferenceCampaign.model_validate(document)


def test_constrained_geometry_cannot_be_predeclared_as_full_dimensional_equilibrium(measured_campaign):
    _,plan,_,_,_=measured_campaign
    document=json.loads(plan.read_text())
    case=document['cases'][0]
    case.update(observable='equilibrium_rotational_constants',definition=ROTOR_DEFINITION,units='GHz',
                geometry_role='optimized-stationary-geometry')
    case['request'].update(purpose='optimize',constraints={'kind':'frozen-monomers','profile_id':'mapping-2026'})
    with pytest.raises(ValueError,match='unconstrained stationary'):
        ReferenceCampaign.model_validate(document)


@pytest.mark.parametrize('mutation',['reference-role','fixed-coordinate-hash'])
def test_source_fixed_geometry_cannot_be_attached_to_a_different_physical_context(measured_campaign,mutation):
    _,plan,_,_,_=measured_campaign
    document=json.loads(plan.read_text())
    protocol=document['cases'][0]['reference_protocol']
    if mutation=='reference-role':
        protocol['geometry_role']='optimized-stationary-geometry'
    else:
        protocol['geometry_sha256']='0'*64
    with pytest.raises(ValueError,match='geometry'):
        ReferenceCampaign.model_validate(document)
