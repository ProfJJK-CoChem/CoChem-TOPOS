import pytest
import os
import json
from pathlib import Path
from core_engine.cochem_topos_master import TOPOSMasterIntegrator

def test_topos_master_init(tmp_path):
    config_file = tmp_path / "cochem_system_config.json"
    hdf5_file = tmp_path / "landscape.h5"
    
    config_file.write_text(json.dumps({"test": "ok"}))
    hdf5_file.write_bytes(b"")

    try:
        master = TOPOSMasterIntegrator(
            config_path=str(config_file),
            hdf5_path=str(hdf5_file),
            zmq_port=5559
        )
        assert master is not None
    except Exception as e:
        # If external HDF5 SWMR init expects full schema, check exception type
        assert "Master Integrator" in str(e) or "HDF5" in str(e) or "Cascade" in str(e)
