import logging
logger = logging.getLogger(__name__)
import pytest
import os
import json
from pathlib import Path
from core_engine.cochem_topos_master import TOPOSMasterIntegrator

def test_topos_master_init(tmp_path) -> None:
    config_file = tmp_path / "cochem_system_config.json"
    hdf5_file = tmp_path / "landscape.h5"
    
    config_file.write_text(json.dumps({"test": "ok"}))
    import h5py
    with h5py.File(hdf5_file, "w") as f:
        f.attrs["version"] = "1.0"

    master = TOPOSMasterIntegrator(
        config_path=str(config_file),
        hdf5_path=str(hdf5_file),
        zmq_port=5559
    )
    assert master is not None
    assert hasattr(master, "oet_client")

def test_topos05_oet_server_ipc_client_and_headers() -> None:
    """Verify TOPOS-05: IPC client helper for oet_server daemon, gradient sign-flip guard, TolE 1e-5 threshold, and header updates."""
    from core_engine.cochem_topos_master import OETServerIPCClient
    import numpy as np

    client = OETServerIPCClient(host="localhost", port=8888, scf_tole=1e-5)
    
    # 1. ORCA input format check
    orca_input = client.format_orca_extopt_input("input.xyz", pal=8)
    assert "! EXTOPT GOAT PAL8" in orca_input
    assert "oet_client" in orca_input
    assert "TolE 1e-05" in orca_input or "TolE 1e-5" in orca_input

    # 2. Gradient Sign-Flip Guard (nabla E = -F)
    forces = np.array([[0.5, -0.2, 0.1], [-0.5, 0.2, -0.1]], dtype=np.float32)
    gradients = client.apply_gradient_sign_flip_guard(forces)
    np.testing.assert_array_almost_equal(gradients, -forces)

    # 3. Daemon response handling
    resp = client.process_daemon_response({"energy": -76.4, "forces": forces})
    assert resp["status"] == "SUCCESS"
    assert resp["scf_threshold"] == 1e-5
    np.testing.assert_array_almost_equal(resp["gradients_hartree_bohr"], -forces)

    # 4. Header verification
    repo_root = Path(__file__).parent.parent
    ingest_file = repo_root / "core_engine" / "01_INGEST_GC.py"
    master_file = repo_root / "core_engine" / "cochem_topos_master.py"

    assert "v4 T1 Search Pipeline" in ingest_file.read_text(encoding="utf-8")
    assert "v4 T1 Master Orchestration" in master_file.read_text(encoding="utf-8")

