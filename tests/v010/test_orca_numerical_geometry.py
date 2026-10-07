"""ORCA contracts and genuine xTB validation of the engine-independent driver.

Analytic functions are mathematical fixtures, never claimed native ORCA output.
"""
import os
import time
from threading import Event

import numpy as np
import pytest
from pydantic import ValidationError

from topos.config import SystemConfig
from topos.correlated import CorrelatedMethod
from topos.engines import run_engine
from topos.higher_composite import NumericalGeometryOptions
from topos.matrix_workflow import MatrixInputs
from topos.method_matrix import (
    BackendCapability,
    HardwareSpec,
    plan_route,
    resolve_row,
    reviewed_revision,
)
from topos.models import MethodSpec, Molecule, ResourceLimits, RunRecord, RunRequest
from topos.orca_numerical_geometry import (
    OrcaF12GeometryProtocol,
    execute_orca_numerical_geometry,
    optimize_energy_geometry,
)
from topos.runtime import run_process
from topos.science import BOHR_ANGSTROM
from topos.storage import RunStore
from topos.workflow import Workflow


def molecule(distance=.8):
    return Molecule(symbols=['H','H'],coordinates=[[0,0,0],[0,0,distance]])


def options(**updates):
    return NumericalGeometryOptions(**{**dict(step_bohr=.001,maximum_step_disagreement_hartree_per_bohr=5e-7,
        gradient_max_hartree_per_bohr=1e-5,gradient_rms_hartree_per_bohr=3e-6,maximum_iterations=30),**updates})


def protocol(zeta='D',**updates):
    values=dict(convention='orca-f12d-numerical-geometry-'+('dz' if zeta=='D' else 'tz')+'-v1',
        energy_protocol=CorrelatedMethod(method='CCSD(T)-F12D/RI',orbital_basis=f'cc-pV{zeta}Z-F12',
            cabs=f'cc-pV{zeta}Z-F12-CABS',auxiliary_c=f'cc-pV{zeta}Z/C',frozen_core=True),numerical=options())
    return OrcaF12GeometryProtocol(**{**values,**updates})


@pytest.mark.parametrize('zeta,row',[('D','T3O-1d'),('T','T3O-1mo')])
def test_reviewed_geometry_protocol_preserves_archived_source(zeta,row):
    spec=protocol(zeta)
    review=reviewed_revision(spec.convention)
    assert review['definition']['row_id']==row and len(review['sha256'])==64
    archived=resolve_row(row)
    assert ('MPQC' in archived.method_text) if zeta=='D' else ('Molpro' in archived.method_text)
    cap=BackendCapability(engine='orca',engine_version='6.1.1',operations=['numerical-energy-geometry'],
        methods=['CCSD(T)-F12D/RI'],bases=[spec.energy_protocol.orbital_basis],verified=True,
        evidence='conditional adapter; not native acceptance',supported_elements=['H'],supported_multiplicities=[1])
    plan=plan_route(row,hardware=HardwareSpec(cpu_threads=1,memory_mb=1024,fingerprint='test'),
        capabilities=[cap],symbols=['H'],available_inputs=['molecule','orca_numerical_geometry'],source_resolution=spec.convention)
    assert plan.runnable and plan.reviewed_revision==review
    assert plan.steps[0].options['native_analytic_gradient'] is False
    assert any('not MPQC' in warning or 'not Molpro' in warning for warning in plan.warnings)


@pytest.mark.parametrize('changed',[dict(frozen_core=False),dict(auxiliary_c='cc-pVQZ/C'),dict(cabs='cc-pVTZ-F12-CABS'),dict(scf_convergence='TightSCF')])
def test_no_basis_core_or_convergence_substitution(changed):
    native=CorrelatedMethod.model_validate({**protocol().energy_protocol.model_dump(),**changed})
    with pytest.raises(ValidationError,match='exact canonical'):
        protocol(energy_protocol=native)


def test_stationarity_includes_displacement_sensitivity_and_topology():
    initial=molecule(.75)
    def harmonic(x):
        return .3*(np.linalg.norm(x.reshape(-1,3)[1]-x.reshape(-1,3)[0])-.74/BOHR_ANGSTROM)**2
    accepted=[]
    result,report=optimize_energy_geometry(initial,harmonic,options(),check_deadline=lambda:None,checkpoint=lambda x:accepted.append(x.copy()))
    assert np.linalg.norm(np.diff(result.coordinates,axis=0))==pytest.approx(.74,abs=1e-7)
    assert report['max_gradient_hartree_per_bohr']<1e-5 and not report['minimum_hessian_verified']
    assert accepted and report['native_analytic_gradient'] is False
    resumed,receipt=optimize_energy_geometry(initial,harmonic,options(),check_deadline=lambda:None,start=result.coordinates)
    assert np.asarray(resumed.coordinates)==pytest.approx(np.asarray(result.coordinates))
    assert receipt['restarted_from_accepted_checkpoint'] and not receipt['optimizer_history_restored']
    def dissociated(x):
        return .3*(np.linalg.norm(x.reshape(-1,3)[1]-x.reshape(-1,3)[0])-5/BOHR_ANGSTROM)**2
    with pytest.raises(ValueError,match='topology'):
        optimize_energy_geometry(initial,dissociated,options(),check_deadline=lambda:None)


def test_geometry_cancel_and_missing_licensed_engine_never_produce_quantities(tmp_path):
    request=RunRequest(molecule=molecule(),purpose='matrix',matrix_row_id='T3O-1d')
    workflow=Workflow(tmp_path,config=SystemConfig(execution_backend='development',executables={'orca':'/not-provisioned/orca'}))
    inputs=MatrixInputs(source_resolution=protocol().convention,orca_numerical_geometry=protocol())
    record=RunRecord(request=request)
    store=RunStore(tmp_path/record.run_id)
    event=Event()
    event.set()
    assert not execute_orca_numerical_geometry(workflow,record,store,inputs,time.monotonic()+30,event)
    assert record.status=='cancelled' and not record.attempts
    assert not execute_orca_numerical_geometry(workflow,record,store,inputs,time.monotonic()+30,None)
    assert record.status=='unavailable' and len(record.attempts)==1
    assert not record.attempts[0].quantities and not record.metadata.get('matrix_correlated')


def test_public_revised_route_retains_binding_and_rejects_changed_revision_on_resume(tmp_path,monkeypatch):
    import topos.method_matrix as matrix

    native=protocol()
    request=RunRequest(molecule=molecule(),purpose='matrix',matrix_row_id='T3O-1d',matrix_revision=matrix.MATRIX_REVISION,
        matrix_inputs={'source_resolution':native.convention,'orca_numerical_geometry':native.model_dump(mode='json')})
    workflow=Workflow(tmp_path,config=SystemConfig(execution_backend='development',executables={'orca':'/not-provisioned/orca'}))
    result=workflow.run(request)
    assert result.status=='unavailable' and not result.candidates
    assert result.metadata['matrix_plan']['reviewed_revision']['variant']==native.convention
    original=dict(matrix.REVIEWED_RECIPES[native.convention])
    monkeypatch.setitem(matrix.REVIEWED_RECIPES,native.convention,{**original,'title':'changed scientific protocol'})
    from topos.storage import IntegrityError

    with pytest.raises(IntegrityError,match='Reviewed matrix revision changed'):
        workflow.resume(tmp_path/result.run_id,invocation_budget_seconds=30)


@pytest.mark.integration
def test_generic_energy_difference_optimizer_matches_genuine_xtb_gradient(tmp_path):
    binary=os.environ.get('TOPOS_XTB_EXECUTABLE')
    if not binary:
        pytest.skip('Actual xTB required to test generic numerical driver')
    initial,calls=molecule(),[]
    deadline=time.monotonic()+90
    def check():
        assert time.monotonic()<deadline
    def energy(x):
        current=initial.model_copy(update={'coordinates':(x.reshape(-1,3)*BOHR_ANGSTROM).tolist()})
        result=run_engine(current,MethodSpec(engine='xtb',method='GFN2-xTB',purpose='energy',profile_id='xtb-extreme-v1'),
            ResourceLimits(budget_seconds=max(.01,deadline-time.monotonic())),tmp_path/f'energy-{len(calls):04d}',
            executable=binary,process_runner=run_process)
        assert result.status=='completed' and result.metadata['execution_kind']=='real'
        calls.append(result)
        return result.energy_hartree
    optimized,report=optimize_energy_geometry(initial,energy,options(),check_deadline=check)
    reference=run_engine(optimized,MethodSpec(engine='xtb',method='GFN2-xTB',purpose='gradient',profile_id='xtb-extreme-v1'),
        ResourceLimits(budget_seconds=10),tmp_path/'independent-gradient',executable=binary,process_runner=run_process)
    assert reference.status=='completed' and reference.gradient_hartree_per_bohr is not None
    assert np.asarray(reference.gradient_hartree_per_bohr)==pytest.approx(np.asarray(report['gradient_hartree_per_bohr']),abs=3e-7)
    assert report['electronic_energy_hartree']==pytest.approx(reference.energy_hartree,abs=1e-9)
    assert len(calls)>=25 and all(result.artifacts for result in calls)
