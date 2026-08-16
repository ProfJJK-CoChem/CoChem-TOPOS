import logging
logger = logging.getLogger(__name__)
import pytest
import json
from pathlib import Path
from cascade_engine.cochem_topos_cascade_orchestrator import CascadeOrchestrator, CascadeConfig, GradientPayload

def test_topos04_v4_t1_search_escalation_routing(tmp_path) -> None:
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
    
    # Process a simple geometry. Since xtb is not honestly present in CI, it should fail rigorously.
    xyz_data = "3\nWater\nO 0.0 0.0 0.0\nH 0.0 0.76 0.59\nH 0.0 -0.76 0.59\n"
    res = orchestrator.process_geometry("test_geom_01", xyz_data)
    assert res.geom_id == "test_geom_01"
    assert "Failed at" in res.final_status

def test_gradient_payload_validation():
    """Verify Pydantic validation rejects fake 0.0 gradients."""
    import pydantic
    
    # Valid payload
    GradientPayload(energy=-1.0, gradient=[[1.0, 2.0, 3.0]], hessian=[])
    
    # Fake 0.0 payload should fail
    with pytest.raises(pydantic.ValidationError, match="Fake 0.0 gradients are strictly prohibited"):
        GradientPayload(energy=-1.0, gradient=[[0.0, 0.0, 0.0]], hessian=[])
