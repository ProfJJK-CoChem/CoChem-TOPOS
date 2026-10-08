"""Prospective routing defaults; rendering tests supply no native acceptance."""
import json
from types import SimpleNamespace

import pytest

from topos.actions.hosted_worker import WorkerError, validate_smoke_request
from topos.matrix_workflow import _child_request
from topos.method_matrix import (
    MAPPING_REVISION,
    MATRIX_REVISION,
    PRIMITIVE_BINDINGS,
    resolve_row,
    resolved_recipe,
    validate_request_matrix,
)
from topos.models import Molecule, RunRequest


def test_ordinary_compiled_matrix_steps_explicitly_select_new_profile_and_vpt2_remains_separate():
    assert MAPPING_REVISION.endswith('/1.0.1')
    for row_id in ('T3O-30min', 'T3O-1h', 'T5-1h', 'T8O-1h'):
        steps, _ = resolved_recipe(resolve_row(row_id))
        ordinary = [step for step in steps if step.engine == 'orca']
        assert ordinary and all(step.profile_id == 'orca-mapping-v4.2' for step in ordinary)
    steps, _ = resolved_recipe(resolve_row('T3O-3h'), source_resolution='r2-b3lyp-d4-vpt2-transfer-v1')
    references = [step for step in steps if step.profile_id == 'orca-vpt2-reference-v1']
    assert references


def test_legacy_primitive_profile_is_rejected_for_new_current_route_without_relabeling():
    engine, method, purpose, basis, profile = PRIMITIVE_BINDINGS['T3O-30min']
    assert profile == 'orca-mapping-v4.2'
    request = SimpleNamespace(matrix_row_id='T3O-30min', matrix_revision=MATRIX_REVISION,
        engine=engine, method=method, purpose=purpose, basis=basis, profile_id=profile,
        dispersion=None, solvent=None, auxiliary_basis='def2/J', constraints={}, metadata={})
    assert validate_request_matrix(request) is None
    request.profile_id = 'orca-mapping-v4.1'
    assert validate_request_matrix(request)[0] == 'unsupported'
    assert request.profile_id == 'orca-mapping-v4.1'


def test_current_child_refinement_selects_new_profile_with_original_remaining_budget():
    molecule = Molecule(symbols=['O','H','H'], coordinates=[[0,0,0],[.96,0,0],[-.24,.93,0]])
    parent = RunRequest(molecule=molecule)
    child = _child_request(parent, molecule, engine='orca', method='wB97X-V', basis='def2-TZVPP',
                           purpose='optimize', remaining=91.25)
    assert child.profile_id == 'orca-mapping-v4.2'
    assert child.budget_seconds == 91.25
    assert (child.method, child.basis, child.auxiliary_basis) == ('wB97X-V','def2-TZVPP','def2/J')


def test_current_reviewed_smoke_request_is_explicit_and_legacy_is_not_silently_upgraded():
    from pathlib import Path

    payload = json.loads((Path(__file__).parents[2] / 'examples/orca-water-energy.json').read_text())
    assert validate_smoke_request(json.dumps(payload).encode()).profile_id == 'orca-mapping-v4.2'
    payload['profile_id'] = 'orca-mapping-v4.1'
    with pytest.raises(WorkerError, match='explicit mapping profile'):
        validate_smoke_request(json.dumps(payload).encode())
    assert payload['profile_id'] == 'orca-mapping-v4.1'
