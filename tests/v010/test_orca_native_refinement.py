"""Actual hosted parsing plus bounded-dispatch tests; no simulated chemistry passes."""
from __future__ import annotations

import json
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

import topos.engines as engines
from topos.engines import EngineResult, _orca_convergence, parse_orca_engrad
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.native_hessian import parse_orca_hessian
from topos.science import harmonic_analysis
from topos.storage import file_digest

FIXTURES=Path(__file__).parent/'fixtures/orca_fifth_hosted'


def historical_partial():
    result=EngineResult.model_validate(json.loads((FIXTURES/'incomplete-r2scan-result.json').read_text()))
    raw=(FIXTURES/'incomplete-r2scan-optimization.stdout').read_text()
    result.diagnostics['native_optimizer_reported_converged']='THE OPTIMIZATION HAS CONVERGED' in raw
    return result


def test_actual_native_overachieved_stop_remains_scientifically_partial():
    raw=(FIXTURES/'incomplete-r2scan-optimization.stdout').read_text()
    assert 'The step convergence is overachieved' in raw
    assert 'THE OPTIMIZATION HAS CONVERGED' in raw and 'ORCA TERMINATED NORMALLY' in raw
    criteria=_orca_convergence(raw)
    assert criteria=={'energy_change':True,'rms_gradient':False,'max_gradient':True,'rms_step':True,'max_step':True}
    result=historical_partial()
    assert result.converged is False and result.status=='partial'
    assert engines._orca_refinement_needed(result)
    result.diagnostics['convergence']={key:False for key in criteria}
    assert engines._orca_refinement_needed(result)
    for status in ['failed','timed-out','cancelled','unsupported']:
        assert not engines._orca_refinement_needed(result.model_copy(update={'status':status}))
    # Missing native evidence is not an optimizer shortcut that may be retried.
    result.diagnostics['convergence'].pop('max_gradient')
    assert not engines._orca_refinement_needed(result)


def test_genuine_hosted_centered_hessian_reconstructs_stationary_native_water():
    provenance=json.loads((FIXTURES/'provenance.json').read_text())
    for source in provenance['sources']:
        assert file_digest(FIXTURES/source['file'])==source['sha256']
    molecule=Molecule.model_validate(json.loads((FIXTURES/'b3lyp-reference-molecule.json').read_text()))
    parsed=parse_orca_hessian(FIXTURES/'b3lyp-frequency.hess',molecule)
    energy,gradient=parse_orca_engrad(FIXTURES/'b3lyp-reference.engrad',molecule)
    assert energy<0
    frame=parsed['native_to_requested_frame']
    assert frame['max_atom_displacement_angstrom']<5e-9
    assert frame['target_center']==pytest.approx([.0409874497688,.0531651138874,0],abs=1e-11)
    analysis=harmonic_analysis(molecule,parsed['hessian_hartree_per_bohr2'],gradient_hartree_per_bohr=gradient,gradient_threshold=1e-7)
    assert analysis['validity']=='harmonic-minimum-within-thresholds'
    assert analysis['frequencies_cm1']==pytest.approx([1632.10768156445,3806.1180824900707,3908.2234163841454],rel=1e-10)
    # A separate rigid rotation of the requested coordinates changes tensor
    # components, while physical eigenfrequencies remain invariant.
    rotation=Rotation.from_rotvec([.3,-.7,.6]).as_matrix()
    transformed=molecule.model_copy(update={'coordinates':(np.asarray(molecule.coordinates)@rotation+[3,-2,1]).tolist()})
    moved=parse_orca_hessian(FIXTURES/'b3lyp-frequency.hess',transformed)
    moved_analysis=harmonic_analysis(transformed,moved['hessian_hartree_per_bohr2'],
                                    gradient_hartree_per_bohr=(np.asarray(gradient)@rotation).tolist(),gradient_threshold=1e-7)
    assert moved_analysis['frequencies_cm1']==pytest.approx(analysis['frequencies_cm1'],rel=1e-10)
    changed=molecule.model_copy(deep=True)
    changed.coordinates[1][0]+=.0001
    with pytest.raises(ValueError,match='geometry differs'):
        parse_orca_hessian(FIXTURES/'b3lyp-frequency.hess',changed)


def run_dispatch_replay(monkeypatch,tmp_path,*,event=None,mode='exhaust'):
    # Infrastructure-only dispatch replay of an already rejected genuine job.
    # It never asserts that ORCA ran here or that any chemistry converged.
    historical=historical_partial()
    calls=[]
    def stage(molecule,method,resources,folder,**kwargs):
        Path(folder).mkdir(parents=True)
        calls.append((molecule.model_dump(),resources.budget_seconds,str(folder)))
        result=historical.model_copy(deep=True)
        result.metadata['resources']=resources.model_dump()
        if mode=='cancel':
            event.set()
        elif mode=='changed-binary' and len(calls)==2:
            result.metadata['executable_sha256']='0'*64
        elif mode=='deadline':
            clock[0]+=11
        return result
    clock=[100.]
    monkeypatch.setattr(engines,'_run_engine_once',stage)
    if mode=='deadline':
        monkeypatch.setattr(engines.time,'monotonic',lambda:clock[0])
    molecule=historical.molecule
    result=engines.run_engine(molecule,MethodSpec.model_validate(historical.metadata['requested_method']),
                              ResourceLimits(budget_seconds=10),tmp_path/'native',cancel_event=event)
    return result,calls


def test_native_continuations_exhaust_finite_limit_preserve_partial_and_receipts(monkeypatch,tmp_path):
    result,calls=run_dispatch_replay(monkeypatch,tmp_path)
    assert result.status=='partial' and result.converged is False
    assert len(calls)==4
    assert all(0<new[1]<=old[1] for old,new in zip(calls[:-1],calls[1:],strict=True))
    history=result.metadata['optimization_refinement']
    assert history['maximum_restarts']==3 and history['accepted_stage_directory'] is None
    assert [s['stage_directory'] for s in history['stages']]==['.','optimization-refinement-1','optimization-refinement-2','optimization-refinement-3']
    assert all(s['status']=='partial' for s in history['stages'])
    for i,stage in enumerate(history['stages']):
        receipt=tmp_path/'native'/stage['receipt']['path']
        assert file_digest(receipt)==stage['receipt']['sha256']
        saved=EngineResult.model_validate(json.loads(receipt.read_text()))
        assert saved.molecule.model_dump()==calls[min(i+1,3)][0]
        assert saved.converged is False
        assert any(Path(a.path)==receipt for a in result.artifacts)
    receipt.write_text('{}')
    assert file_digest(receipt)!=history['stages'][-1]['receipt']['sha256']


@pytest.mark.parametrize('mode,expected',[('cancel','cancelled'),('deadline','timed-out'),('changed-binary','failed')])
def test_refinement_never_restarts_after_cancel_deadline_or_identity_change(monkeypatch,tmp_path,mode,expected):
    result,calls=run_dispatch_replay(monkeypatch,tmp_path,event=Event(),mode=mode)
    assert result.status==expected and result.converged is False
    assert len(calls)==(2 if mode=='changed-binary' else 1)
    assert result.metadata['optimization_refinement']['accepted_stage_directory'] is None


def test_refinement_receipt_failure_cannot_start_an_unrecorded_stage(monkeypatch,tmp_path):
    def blocked_receipt(*args,**kwargs):
        raise OSError('receipt storage unavailable')
    monkeypatch.setattr('topos.storage.atomic_json',blocked_receipt)
    result,calls=run_dispatch_replay(monkeypatch,tmp_path)
    assert result.status=='failed' and result.converged is False
    assert len(calls)==1
    assert 'receipt could not be retained' in result.diagnostics['reason']
    assert result.metadata['optimization_refinement']['accepted_stage_directory'] is None


def test_refinement_rejects_unverifiable_artifact_inventory(monkeypatch,tmp_path):
    def bad_inventory(*args,**kwargs):
        raise engines.EngineParseError('engine artifact symlinks are not accepted')
    monkeypatch.setattr(engines,'artifact_inventory',bad_inventory)
    result,_=run_dispatch_replay(monkeypatch,tmp_path)
    assert result.status=='failed' and result.converged is False
    assert 'symlinks' in result.diagnostics['artifact_error']
    assert result.metadata['optimization_refinement']['accepted_stage_directory'] is None
