"""Native-deck regression and evidence transport; no native calculation is simulated.

The retained failure is unchanged genuine CFOUR output. Artifact bookkeeping
fixtures are not energies, gradients, solver completion or provider authority.
"""
import json
from pathlib import Path

import pytest

from topos.cfour_artifacts import finalize_artifacts, native_text
from topos.cfour_corrections import ScalarRelativisticProtocol, scalar_input
from topos.cfour_counterpoise import cfour_counterpoise_input, counterpoise_legs
from topos.cfour_dboc import MASS_CONVENTION, DefaultMassDBOCProtocol, dboc_input
from topos.engines import EngineParseError, EngineResult, artifact_inventory
from topos.external_engines import ExternalProtocol, _native_completion, cfour_input
from topos.models import Molecule, ResourceLimits
from topos.storage import file_digest

FIXTURE = Path(__file__).parent/'fixtures/cfour_failed_first_order'
RESOURCES = ResourceLimits(threads=2, memory_mb=2048, budget_seconds=3600)


def protocol(**updates):
    return ExternalProtocol(**{'engine':'cfour', 'engine_version':'2.1', 'method':'CCSD(T)',
        'operation':'first-order-properties', 'orbital_basis':'PVTZ', 'frozen_core':False,
        'genbas_path':'/unexecuted-cfour/basis/GENBAS', 'genbas_sha256':'a'*64, **updates})


def water():
    rows = (FIXTURE/'native-ZMAT.inp').read_text().splitlines()[1:4]
    return Molecule(symbols=[row.split()[0] for row in rows],
                    coordinates=[[float(x) for x in row.split()[1:]] for row in rows])


def controls(deck):
    body = deck.split('*CFOUR(', 1)[1].split(')', 1)[0]
    assert ',' not in body and all('=' in line for line in body.splitlines())
    values = [line.split('=',1) for line in body.splitlines()]
    assert len({key for key, _ in values}) == len(values)
    return dict(values)


def test_actual_failed_fixture_and_unchanged_requested_physics():
    proof = json.loads((FIXTURE/'provenance.json').read_text())
    for name, entry in proof['files'].items():
        assert file_digest(FIXTURE/name) == entry['sha256']
    raw = (FIXTURE/'output.stdout').read_text()
    assert '@GTFLGS-F, Must supply value for keyword string' in raw
    assert '--executable xjoda finished with status   256' in raw
    with pytest.raises(EngineParseError):
        _native_completion(raw, protocol())
    # Only separator/terminal-blank-line bytes change; every physical option,
    # coordinate and resource value is retained from the actual failed input.
    original = (FIXTURE/'native-ZMAT.inp').read_text()
    repaired = cfour_input(water(), protocol(), RESOURCES)
    assert repaired == original.replace(',\n', '\n') + '\n'
    assert controls(repaired)['PROPS'] == 'FIRST_ORDER'


@pytest.mark.parametrize('method,program',[('CCSD(T)','VCC'),('CCSDT','ECC'),('CCSDTQ','NCC')])
def test_cp_single_solver_and_physical_core_selection_after_separator_change(method, program):
    molecule = Molecule(symbols=['Ne','Ne'], coordinates=[[0,0,0],[0,0,3.5]],
        fragments=[[0],[1]], fragment_states=[{'atom_indices':[i],'charge':0,'multiplicity':1} for i in range(2)])
    native = protocol(operation='energy', method=method, frozen_core=True)
    _, _, physical, leg = counterpoise_legs(molecule, native, [1,1])[2]
    deck = cfour_counterpoise_input(physical, leg, RESOURCES)
    values = controls(deck)
    assert values['CC_PROG'] == program and values['DROPMO'] == '1>1'
    assert values['FROZEN_CORE'] == 'OFF' and values['ABCDTYPE'] == 'STANDARD'
    assert values['BASIS'] == 'SPECIAL' and deck.count('NE:PVTZ') == 2
    assert sum(line.startswith('GH ') for line in deck.splitlines()) == 1


@pytest.mark.parametrize('enabled',[True,False])
def test_dboc_response_is_not_disabled_by_obsolete_comma_suffix(enabled):
    p = DefaultMassDBOCProtocol(orbital_basis='PCVTZ', contraction='GENERAL',
        mass_convention=MASS_CONVENTION, dboc=enabled)
    values = controls(dboc_input(water(), p, RESOURCES))
    assert values['DBOC'] == ('ON' if enabled else 'OFF')
    assert values['RELATIVISTIC'] == 'OFF' and values['CONTRACTION'] == 'GENERAL'
    assert ('DERIV_LEVEL' not in values) if enabled else values['DERIV_LEVEL'] == 'ZERO'


@pytest.mark.parametrize('relativistic',['OFF','X2C1E'])
def test_scalar_controls_preserve_exact_hamiltonian_and_basis(relativistic):
    p = ScalarRelativisticProtocol(orbital_basis='PCVTZ',relativistic=relativistic)
    values = controls(scalar_input(water(),p,RESOURCES))
    assert values['RELATIVISTIC'] == relativistic and values['CONTRACTION'] == 'UNCONTRACTED'
    assert values['DBOC'] == 'OFF' and values['DERIV_LEVEL'] == 'ZERO'


def test_native_scratch_links_are_recorded_without_reading_targets(tmp_path, monkeypatch):
    folder=tmp_path/'attempt'
    folder.mkdir()
    (folder/'engine.stdout').write_bytes((FIXTURE/'output.stdout').read_bytes())
    (folder/'engine.stderr').write_text('')
    external=tmp_path/'private-library'
    external.write_text('Never read this bookkeeping target')
    (folder/'ECPDATA').symlink_to(external)
    external_directory=tmp_path/'outside'
    external_directory.mkdir()
    (external_directory/'secret').write_text('Do not traverse')
    (folder/'native-scratch-directory').symlink_to(external_directory,target_is_directory=True)
    (folder/'broken-scratch').symlink_to(tmp_path/'absent')
    original=Path.open
    def reject_target(self,*args,**kwargs):
        assert self not in {external,external_directory/'secret'}, 'Symlink target was opened'
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'open',reject_target)
    result=EngineResult(status='failed',engine='cfour',method='CCSD(T)',operation='first-order-properties',
        diagnostics={'reason':'genuine native xjoda status 256; keyword value missing'})
    finalize_artifacts(result,folder)
    assert result.status == 'failed' and result.diagnostics['reason'].startswith('genuine native xjoda')
    assert {Path(a.path).name for a in result.artifacts} == {'engine.stdout','engine.stderr'}
    assert len(result.diagnostics['artifact_links']) == 3 and 'artifact_error' not in result.diagnostics
    assert all(item['disposition']=='not-followed-or-retained' for item in result.diagnostics['artifact_links'])
    with pytest.raises(EngineParseError,match='symlinks'):
        artifact_inventory(folder)  # The generic policy for other engines is unchanged.


@pytest.mark.parametrize('name',['ZMAT','GENBAS','engine.stdout','GRD','DIPOL','EFG','FCMFINAL'])
def test_scientific_symlinks_fail_without_masking_primary_failure(tmp_path,name):
    folder=tmp_path/'attempt'
    folder.mkdir()
    target=tmp_path/'untrusted'
    target.write_text('Not native evidence')
    (folder/name).symlink_to(target)
    result=EngineResult(status='timed-out',engine='cfour',method='HF',operation='energy',
        diagnostics={'reason':'primary allocated budget exhausted'})
    finalize_artifacts(result,folder)
    assert result.status=='timed-out' and result.diagnostics['reason']=='primary allocated budget exhausted'
    assert 'cannot be a symlink' in result.diagnostics['artifact_error'] and not result.artifacts
    with pytest.raises(EngineParseError,match='confined regular text'):
        native_text(folder,name,required=True)


def test_native_reader_rejects_wrong_directory_and_missing_required_file(tmp_path):
    (tmp_path/'engine.stdout').write_bytes((FIXTURE/'output.stdout').read_bytes())
    assert '@GTFLGS-F' in native_text(tmp_path,'engine.stdout',required=True,process_path=str(tmp_path/'engine.stdout'))
    with pytest.raises(EngineParseError,match='path differs'):
        native_text(tmp_path,'engine.stdout',process_path='/different/engine.stdout')
    with pytest.raises(EngineParseError,match='missing'):
        native_text(tmp_path,'GRD',required=True)
    assert native_text(tmp_path,'DIPOL') is None



def test_collection_io_error_is_secondary_and_keeps_other_regular_evidence(tmp_path, monkeypatch):
    (tmp_path/'engine.stdout').write_bytes((FIXTURE/'output.stdout').read_bytes())
    (tmp_path/'protocol.json').write_text('{}')
    original = Path.open
    def denied(self, *args, **kwargs):
        if self == tmp_path/'engine.stdout':
            raise PermissionError('injected read failure')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', denied)
    result = EngineResult(status='failed', engine='cfour', method='HF', operation='energy',
                          diagnostics={'reason':'original solver failure'})
    finalize_artifacts(result, tmp_path)
    assert result.status == 'failed' and result.diagnostics['reason'] == 'original solver failure'
    assert 'injected read failure' in result.diagnostics['artifact_error']
    assert [Path(a.path).name for a in result.artifacts] == ['protocol.json']


def test_symlinked_work_directory_is_never_walked(tmp_path):
    real = tmp_path/'real'
    real.mkdir()
    (real/'engine.stdout').write_text('Inert evidence bookkeeping only')
    linked = tmp_path/'linked'
    linked.symlink_to(real, target_is_directory=True)
    result = EngineResult(status='failed', engine='cfour', method='HF', operation='energy',
                          diagnostics={'reason':'original failure'})
    finalize_artifacts(result, linked)
    assert not result.artifacts and result.diagnostics['reason'] == 'original failure'
    assert 'directory cannot be a symlink' in result.diagnostics['artifact_error']


def test_invalid_scientific_artifact_clears_successful_bookkeeping_state(tmp_path):
    # A state-transition unit test only, with no native output or solver claim.
    (tmp_path/'GRD').symlink_to(tmp_path/'absent')
    result = EngineResult(status='completed', engine='cfour', method='HF', operation='energy', converged=True)
    finalize_artifacts(result, tmp_path)
    assert result.status == 'failed' and not result.converged and result.energy_hartree is None
