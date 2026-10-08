"""R2 phase wiring and input provenance; no ORCA result is fabricated."""
import time
from threading import Event
from types import SimpleNamespace

import pytest

from topos.fragments import split_fragments
from topos.matrix_r2 import (
    R2_REVIEWED_RESOLUTION,
    R2AnharmonicProtocol,
    R2MonomerProvenance,
    R2VPT2Options,
    execute_r2_geometry,
    execute_reviewed_r2,
    r2_reference_method,
)
from topos.matrix_workflow import MatrixInputs, _child_request
from topos.models import Molecule, RunRecord, RunRequest
from topos.storage import RunStore, digest_json


def inputs_and_record():
    molecule=Molecule(symbols=['O','H','H']*2,
        coordinates=[[0,0,0],[.9584,0,0],[-.239,.927,0],[3,0,0],[3.9584,0,0],[2.761,.927,0]],
        fragments=[[0,1,2],[3,4,5]],fragment_states=[{'atom_indices':[0,1,2],'charge':0,'multiplicity':1},
                                                {'atom_indices':[3,4,5],'charge':0,'multiplicity':1}])
    references=split_fragments(molecule)
    inputs=MatrixInputs(isolated_monomer_references=references,r2_monomer_provenance=[R2MonomerProvenance(
        geometry_sha256=digest_json(ref.model_dump(mode='json')),method='fc-CCSD(T)/cc-pVTZ',
        source='Test-only declared geometry input; no native calculation claim',evidence_kind='declared-calculation-reference')
        for ref in references])
    return inputs,RunRecord(request=RunRequest(molecule=molecule,purpose='matrix',matrix_row_id='T3O-3h'))


def test_r2_geometry_uses_exact_frozen_qz_method_and_auxiliary_without_completing_row(tmp_path):
    inputs,record=inputs_and_record()
    store=RunStore(tmp_path/record.run_id)
    requested=[]
    def unavailable(task,molecule,**kwargs):
        requested.append(kwargs)
        native=_child_request(record.request,molecule,purpose='optimize',remaining=30,**kwargs)
        assert native.method=='wB97M-V' and native.basis=='def2-QZVPP' and native.auxiliary_basis=='def2/J'
        assert native.dispersion is None and native.constraints['kind']=='frozen-monomers'
        return None
    assert execute_r2_geometry(SimpleNamespace(),record,store,inputs,unavailable,time.monotonic()+30,None) is None
    assert len(requested)==1 and not record.attempts and not record.metadata.get('matrix_r2_geometry')


def test_r2_monomer_provenance_binds_exact_supplied_geometry_before_engine_launch(tmp_path):
    inputs,record=inputs_and_record()
    inputs.isolated_monomer_references[0].coordinates[1][0]+=.01
    with pytest.raises(ValueError,match='bind the exact'):
        execute_r2_geometry(None,record,RunStore(tmp_path/record.run_id),inputs,None,time.monotonic()+30,None)
    assert not record.attempts


def test_named_reference_change_is_explicit_and_strictly_unconstrained():
    from topos.anharmonic import orca_vpt2_input
    from topos.engines import _orca_input
    from topos.models import ResourceLimits

    inputs, record = inputs_and_record()
    method = r2_reference_method()
    assert method.method == 'B3LYP' and method.dispersion == 'D4'
    assert method.basis == 'def2-TZVPP' and method.auxiliary_basis == 'def2/J'
    assert not method.constraints
    deck = _orca_input(record.request.molecule, method, ResourceLimits(), 'optimize')
    assert 'ExtremeSCF' in deck and 'TolMaxG 1e-7' in deck and ' D4 ' in deck
    assert 'wB97X' not in deck and 'Constraints' not in deck
    native = R2AnharmonicProtocol(**r2_reference_method(purpose='anharmonic').model_dump(),
                                  displacement=.05, semirigid_modes=True)
    deck = orca_vpt2_input(record.request.molecule, native.native_method(), ResourceLimits())
    assert ' VPT2' in deck and 'B3LYP' in deck and ' D4 ' in deck
    assert native.operation == 'anharmonic'


def test_transfer_requires_explicit_semirigid_and_same_basin_declaration():
    with pytest.raises(ValueError):
        R2VPT2Options(transfer={})
    with pytest.raises(ValueError):
        R2VPT2Options(semirigid_modes=True, transfer={'semirigid_same_basin':False})
    assert R2VPT2Options(semirigid_modes=True, transfer={'semirigid_same_basin':True}).semirigid_modes


def test_reviewed_plan_preserves_unavailable_vv10_and_names_supported_alternative():
    from topos.method_matrix import (
        HardwareSpec,
        plan_route,
        resolve_row,
        resolved_recipe,
        reviewed_revision,
    )

    steps, required = resolved_recipe(resolve_row('T3O-3h'), R2_REVIEWED_RESOLUTION)
    assert 'r2_vpt2' in required and 'r2_counterpoise' in required and 'r2_monomer_provenance' in required
    assert steps[1].options['f12_hamiltonian'] is False and steps[1].options['cabs'] is None
    assert steps[2].method == steps[3].method == 'B3LYP'
    assert steps[2].options['dispersion'] == steps[3].options['dispersion'] == 'D4'
    assert steps[2].dispersion == steps[3].dispersion == 'D4'
    assert steps[2].profile_id == steps[3].profile_id == 'orca-vpt2-reference-v1'
    assert steps[2].auxiliary_basis == steps[3].auxiliary_basis == 'def2/J'
    assert steps[3].options['constraints'] is False
    assert steps[-1].options['approximate_composite'] is True
    revision = reviewed_revision(R2_REVIEWED_RESOLUTION)
    assert 'B3LYP-D4' in revision['definition']['title']
    blocked = plan_route('T3O-3h', source_resolution='r2-separate-dft-vpt2-transfer-v1',
        hardware=HardwareSpec(cpu_threads=1,memory_mb=1024,fingerprint='unit-contract'), capabilities=[])
    assert not blocked.runnable and any('VV10' in item for item in blocked.blockers)


def test_reviewed_r2_cancel_preserves_no_execution(tmp_path):
    inputs, record = inputs_and_record()
    event = Event()
    event.set()
    assert not execute_reviewed_r2(None, record, RunStore(tmp_path/record.run_id), inputs,
                                   None, time.monotonic()+30, event)
    assert record.status == 'cancelled' and not record.attempts


def test_reviewed_r2_missing_transfer_protocol_rejected_before_geometry(tmp_path):
    inputs, record = inputs_and_record()
    inputs.source_resolution = R2_REVIEWED_RESOLUTION
    assert not execute_reviewed_r2(None, record, RunStore(tmp_path/record.run_id), inputs,
                                   None, time.monotonic()+30, None)
    assert record.status == 'unsupported' and 'r2_vpt2' in record.metadata['termination_reason']
    assert not record.attempts


def test_public_reviewed_r2_checks_base_export_authority_before_expensive_geometry(tmp_path):
    from topos.config import SystemConfig
    from topos.correlated import CorrelatedMethod
    from topos.correlated_counterpoise import CorrelatedCounterpoiseProtocol
    from topos.method_matrix import MATRIX_REVISION
    from topos.workflow import Workflow

    inputs, record = inputs_and_record()
    inputs.source_resolution = R2_REVIEWED_RESOLUTION
    inputs.r2_vpt2 = R2VPT2Options(semirigid_modes=True, transfer={'semirigid_same_basin':True})
    inputs.r2_counterpoise = CorrelatedCounterpoiseProtocol(
        native=CorrelatedMethod(method='DLPNO-CCSD(T1)', operation='energy', orbital_basis='cc-pVDZ-F12',
            auxiliary_c='cc-pVDZ/C', frozen_core=True, pno_profile='TightPNO', tcutpno=1e-7),
        source_resolution='orca-r2-dlpno-orbital-f12-cp-v1')
    record.request.matrix_revision = MATRIX_REVISION
    record.request.matrix_inputs = inputs.model_dump(mode='json')
    result = Workflow(tmp_path, config=SystemConfig(execution_backend='development')).run(record.request)
    assert result.status == 'unsupported'
    assert 'BASE native orbital/fitting-basis export authority' in result.metadata['termination_reason']
    assert not result.attempts and result.metadata['matrix_execution']['full_row_completed'] is False
    assert result.metadata['matrix_plan']['runnable'] is True
