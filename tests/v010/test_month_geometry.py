"""Conditional month contract tests; no licensed native execution is simulated."""
import time
from threading import Event

import pytest

from topos.cfour_corrections import ScalarRelativisticProtocol
from topos.cfour_dboc import DefaultMassDBOCProtocol
from topos.config import SystemConfig
from topos.higher_composite import HigherGeometryProtocol, NumericalGeometryOptions
from topos.matrix_workflow import MatrixInputs, execution_support_report
from topos.method_matrix import MATRIX_REVISION, resolve_row, resolved_recipe, reviewed_revision
from topos.models import Molecule, RunRecord, RunRequest
from topos.month_geometry import (
    SOURCE_RESOLUTION,
    MonthCorrectionProtocol,
    execute_month_geometry,
    validate_month_inputs,
)
from topos.storage import RunStore
from topos.workflow import Workflow


def inputs():
    shared = dict(engine='cfour', engine_version='2.1', orbital_basis='PVTZ',
                  genbas_path='/licensed/cfour/basis/GENBAS', genbas_sha256='a'*64)
    numerical = NumericalGeometryOptions(step_bohr=.001,
        maximum_step_disagreement_hartree_per_bohr=1e-7,
        gradient_max_hartree_per_bohr=1e-5, gradient_rms_hartree_per_bohr=3e-6)
    high = HigherGeometryProtocol(template={**shared, 'method':'CCSD(T)', 'operation':'optimize', 'frozen_core':True},
        low_basis='PVTZ', high_basis='PVQZ', geometry_inverse_power=3., core_valence_basis='PCVTZ',
        full_triples_basis='PVTZ', full_quadruples_basis='PVDZ',
        coordinates={'coordinates':[{'kind':'distance', 'atoms':[0,1]}]},
        numerical_quadruples=numerical, convention='explicit-geometry-CBS-CV-fT-fQ-v1')
    corrections = MonthCorrectionProtocol(
        scalar=ScalarRelativisticProtocol(**shared, relativistic='X2C1E'),
        dboc=DefaultMassDBOCProtocol(**shared, contraction='GENERAL', mass_convention='cfour-2.1-native-default-masses-v1'),
        scalar_numerical=numerical, dboc_numerical=numerical,
        convention='cfour-higher-HF-X2C-native-default-DBOC-geometry-v1',
        rotor_policy='withhold-unverified-native-default-mass-rotors')
    return MatrixInputs(higher_geometry=high, month_corrections=corrections,
        source_resolution=SOURCE_RESOLUTION, external_resolution='cfour-topos-cartesian-optimizer-v1')


def record(**molecule_options):
    molecule = Molecule(symbols=['H','H'], coordinates=[[0,0,0],[0,0,.74]], **molecule_options)
    return RunRecord(request=RunRequest(molecule=molecule, purpose='matrix', matrix_row_id='T3C-1mo',
        matrix_revision=MATRIX_REVISION, budget_seconds=30))


def test_all_native_library_and_mass_choices_preflight_before_cost():
    high, corrections = validate_month_inputs(record(), inputs())
    assert high.template.genbas_sha256 == corrections.scalar.genbas_sha256
    assert corrections.rotor_policy == 'withhold-unverified-native-default-mass-rotors'
    altered = inputs()
    altered.higher_geometry.template.genbas_sha256 = 'b'*64
    with pytest.raises(ValueError, match='one native version and GENBAS'):
        validate_month_inputs(record(), altered)


def test_explicit_isotopes_cannot_enter_native_default_month_branch():
    with pytest.raises(ValueError, match='rejects every explicit isotope'):
        validate_month_inputs(record(isotopes=[1,2]), inputs())


@pytest.mark.parametrize('change', [{'scalar':{'relativistic':'OFF'}}, {'dboc':{'dboc':False}}])
def test_requested_increment_cannot_be_disabled(change):
    raw = inputs().month_corrections.model_dump()
    for key, fields in change.items():
        raw[key].update(fields)
    with pytest.raises(ValueError, match='explicit X2C1E and DBOC'):
        MonthCorrectionProtocol.model_validate(raw)


def test_plan_and_release_report_preserve_partial_mass_scope():
    steps, required = resolved_recipe(resolve_row('T3C-1mo'), SOURCE_RESOLUTION)
    assert 'month_corrections' in required and 'native_default_mass_domain' in required
    assert steps[-1].options['full_matrix_row_completed'] is False
    assert steps[-1].options['rotor_constants_withheld'] is True
    report = execution_support_report()
    assert 'T3C-1mo' in report['implemented_partial_branches']
    assert 'T3C-1mo' not in report['compiled_complete_recipes']
    revision = reviewed_revision(SOURCE_RESOLUTION)
    assert 'isotope-mass substitution' in revision['user_decision']
    assert report['unresolved_track_gaps'] == []
    assert {item['row_id'] for item in report['unavailable_by_design']} == {'T3C-10s','T3C-1min'}


@pytest.mark.parametrize('cancelled', [True, False])
def test_cancel_or_expired_budget_never_launches_native_calculations(tmp_path, cancelled):
    run = record()
    store = RunStore(tmp_path/run.run_id)
    event = Event()
    if cancelled:
        event.set()
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development'))
    assert not execute_month_geometry(workflow, run, store, inputs(), time.monotonic()-1, event)
    assert run.status == ('cancelled' if cancelled else 'timed-out')
    assert not run.attempts and 'matrix_external' not in run.metadata


def test_unsupported_mass_rejected_before_high_level_component(tmp_path):
    run = record(isotopes=[1,2])
    store = RunStore(tmp_path/run.run_id)
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development'))
    assert not execute_month_geometry(workflow, run, store, inputs(), time.monotonic()+30, None)
    assert run.status == 'unsupported' and not run.attempts
    assert 'explicit isotope' in run.metadata['termination_reason']


def test_per_geometry_budget_bounds_whole_compound_and_suppresses_rotors(tmp_path, monkeypatch):
    import topos.month_geometry as module

    run = record()
    run.request.per_geometry_budget_seconds = .25
    store = RunStore(tmp_path/run.run_id)
    observed = {}

    def interrupted_component(workflow, current, current_store, supplied, deadline, event, *, include_rotor_constants):
        # Control-flow interruption fixture, never a fabricated engine result.
        observed.update(deadline=deadline, rotors=include_rotor_constants)
        current.status = 'partial'
        return None

    monkeypatch.setattr(module, 'calculate_higher_geometry', interrupted_component)
    before = time.monotonic()
    assert not execute_month_geometry(None, run, store, inputs(), before+100, None)
    assert before < observed['deadline'] <= time.monotonic()+.25
    assert observed['rotors'] is False
    assert not run.attempts and 'matrix_external' not in run.metadata


def test_matrix_request_rejects_mass_domain_before_engine_discovery(tmp_path):
    run = record(isotopes=[1,2])
    run.request.matrix_inputs = inputs().model_dump(mode='json')
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development'))
    result = workflow.run(run.request)
    assert result.status == 'unsupported'
    assert 'explicit isotope' in result.metadata['termination_reason']
    assert not result.attempts


def test_public_unavailable_tier_is_not_misreported_as_missing_adapter(tmp_path):
    run = record()
    run.request.matrix_row_id = 'T3C-10s'
    workflow = Workflow(tmp_path, config=SystemConfig(execution_backend='development'))
    result = workflow.run(run.request)
    assert result.status == 'unsupported'
    assert 'unavailable by design' in result.metadata['termination_reason']
    assert 'additional' not in result.metadata['termination_reason']
    assert not result.attempts


def test_cfour_counterpoise_plan_names_native_energy_derivatives_and_separate_branches():
    steps, required = resolved_recipe(resolve_row('T3O-1w'), 'cfour-relaxed-counterpoise-geometry-v1')
    assert {'fragments', 'fragment_states', 'cfour_counterpoise'} <= set(required)
    for step in steps[:4]:
        assert step.engine == 'cfour' and step.engine_version == '2.1'
        assert step.options['native_analytic_gradient'] is False
        assert step.options['cp_potential'] == 'E_AB+sum(E_i_own-E_i_ghost)'
        assert step.options['branches'] == ['raw', 'relaxed-total-counterpoise']
    assert steps[-1].options['midpoint_geometry'] is False
    assert steps[-1].options['composite_stationarity_verified'] is False
    assert 'T3O-1w' in execution_support_report()['compiled_complete_recipes']


def test_cfour_cp_row_requires_the_explicit_protocol_before_launch(tmp_path):
    run = record()
    run.request.matrix_row_id = 'T3O-1w'
    run.request.matrix_inputs = {'source_resolution':'cfour-relaxed-counterpoise-geometry-v1',
                                'external_resolution':'cfour-relaxed-counterpoise-geometry-v1'}
    result = Workflow(tmp_path, config=SystemConfig(execution_backend='development')).run(run.request)
    assert result.status == 'unsupported'
    assert 'cfour_counterpoise' in result.metadata['termination_reason']
    assert not result.attempts


@pytest.mark.parametrize('row', ['T3O-1w','T3C-1mo'])
def test_archival_recipe_cannot_fall_through_to_one_primitive_step(tmp_path, row):
    run = record()
    run.request.matrix_row_id = row
    result = Workflow(tmp_path, config=SystemConfig(execution_backend='development')).run(run.request)
    assert result.status == 'unsupported'
    assert 'explicit compiled scientific source_resolution' in result.metadata['termination_reason']
    assert not result.attempts
