import logging
logger = logging.getLogger(__name__)
import pytest
import json
from cascade_engine.cochem_topos_cascade_orchestrator import CascadeOrchestrator, CascadeConfig, GradientPayload
from ase.calculators.lj import LennardJones
from unittest import mock

import shutil
def has_xtb():
    try:
        import xtb
        return True
    except ImportError:
        return False

@mock.patch('cascade_engine.cochem_topos_cascade_orchestrator.get_honest_xtb_calculator', return_value=LennardJones())
@mock.patch('cascade_engine.cochem_topos_cascade_orchestrator.MACEOFF24mCalculator', return_value=LennardJones(), create=True)
@mock.patch('cascade_engine.cochem_topos_cascade_orchestrator.SubprocessBroker.execute', return_value=0, create=True)
@mock.patch('cascade_engine.cochem_topos_cascade_orchestrator.CascadeOrchestrator._compute_true_hessian', return_value=[])
def test_topos04_v4_t1_search_escalation_routing(mock_hessian, mock_broker, mock_mace, mock_xtb, tmp_path) -> None:
    """Verify TOPOS-04: Tier routing for v4 T1 search escalation."""
    
    config = CascadeConfig(artifact_dir=tmp_path, complex_flag=True)
    orchestrator = CascadeOrchestrator(config=config)
    
    tier_seq = orchestrator._get_tier_sequence(complex_flag=True)
    assert len(tier_seq) == 5
    
    methods = [t.method for t in tier_seq]
    assert methods[0] == "Hand Topology"
    assert methods[1] == "GOAT XTB2"
    assert methods[2] == "GOAT-EXPLORE ExtOpt"
    assert methods[3] == "CREST NCI"
    assert methods[4] == "r2SCAN-3c"
    
    
    tier_names = [t.tier_name for t in tier_seq]
    assert tier_names == ["T1-10s", "T1-1min", "T1-30min", "T1-1h", "T1-3h"]
    
    # Process a simple geometry and assert functional success.
    # We use injected EMT and mocked SubprocessBroker to ensure execution tests the logic.
    xyz_data = "3\nWater\nO 0.0 0.0 0.0\nH 0.0 0.76 0.59\nH 0.0 -0.76 0.59\n"
    res = orchestrator.process_geometry("test_geom_01", xyz_data)
    assert res.geom_id == "test_geom_01"
    assert res.final_status == "SUCCESS"

def test_gradient_payload_validation():
    """Verify Pydantic validation rejects fake 0.0 gradients."""
    import pydantic
    
    # Valid payload
    GradientPayload(energy=-1.0, gradient=[[1.0, 2.0, 3.0]], hessian=[])
    
    # Fake 0.0 payload should fail
    with pytest.raises(pydantic.ValidationError, match="Fake 0.0 gradients are strictly prohibited"):
        GradientPayload(energy=-1.0, gradient=[[0.0, 0.0, 0.0]], hessian=[])
