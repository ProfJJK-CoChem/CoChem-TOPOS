import pytest
import json
from pathlib import Path
from cascade_engine.cochem_topos_cascade_orchestrator import CascadeOrchestrator

def test_topos04_v4_t1_search_escalation_routing(tmp_path):
    """Verify TOPOS-04: Tier routing for v4 T1 search escalation (Hand topology -> GOAT XTB2 -> GOAT-EXPLORE ExtOpt -> CREST NCI -> r2SCAN-3c)."""
    config_file = tmp_path / "cochem_system_config.json"
    hdf5_file = tmp_path / "landscape.h5"
    
    config_file.write_text(json.dumps({"test": "ok"}))
    
    orchestrator = CascadeOrchestrator(
        config_path=str(config_file),
        hdf5_path=str(hdf5_file)
    )
    
    tier_seq = orchestrator._get_tier_sequence(complex_flag=True)
    assert len(tier_seq) == 5
    
    methods = [t["method"] for t in tier_seq]
    assert methods[0] == "Hand Topology"
    assert methods[1] == "GOAT XTB2"
    assert methods[2] == "GOAT-EXPLORE ExtOpt"
    assert methods[3] == "CREST NCI"
    assert methods[4] == "r2SCAN-3c"
    
    tier_names = [t.get("tier_name") for t in tier_seq]
    assert tier_names == ["T1-10s", "T1-1min", "T1-30min", "T1-1h", "T1-3h"]
    
    # Process a simple geometry through the v4 T1 search escalation
    xyz_data = "3\nWater\nO 0.0 0.0 0.0\nH 0.0 0.76 0.59\nH 0.0 -0.76 0.59\n"
    res = orchestrator.process_geometry("test_geom_01", xyz_data, complex_flag=True)
    assert res["geom_id"] == "test_geom_01"
    assert res["highest_tier"] == 5
    assert res["final_status"] == "SUCCESS"
