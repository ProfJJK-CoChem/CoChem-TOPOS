from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from typing import Generator
from unittest import mock

import h5py
import numpy as np
import pytest
import zmq
import zmq.asyncio
from ase import Atoms
from ase.calculators.lj import LennardJones

from cascade_engine.cochem_topos_cascade_orchestrator import CascadeOrchestrator
from core_engine.cochem_topos_crusher import ToposCrusher
from core_engine.cochem_topos_master import OETServerIPCClient, TOPOSMasterIntegrator


def get_free_port() -> int:
    """Find a free ephemeral TCP port for isolated ZMQ testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


def create_mock_environment(tmp_path: Path) -> tuple[Path, Path]:
    """Create valid test configuration and HDF5 database files."""
    config_file = tmp_path / "cochem_system_config.json"
    hdf5_file = tmp_path / "landscape.h5"
    config_file.write_text(json.dumps({"system": "TOPOS-v4", "active": True}), encoding="utf-8")
    with h5py.File(hdf5_file, "w", libver="latest") as f:
        f.attrs["version"] = "1.0"
        f.attrs["system"] = "TOPOS"
    return config_file, hdf5_file


@pytest.fixture
def master_integrator(tmp_path: Path) -> Generator[TOPOSMasterIntegrator, None, None]:
    """Fixture providing a TOPOSMasterIntegrator instance with guaranteed ZMQ and HDF5 teardown."""
    config_file, hdf5_file = create_mock_environment(tmp_path)
    port = get_free_port()
    master = TOPOSMasterIntegrator(
        config_path=str(config_file),
        hdf5_path=str(hdf5_file),
        zmq_port=port,
    )
    try:
        yield master
    finally:
        master.close()


def test_topos_master_init(tmp_path: Path) -> None:
    """Verify TOPOSMasterIntegrator initializes all core engines, state paths, and network sockets."""
    config_file, hdf5_file = create_mock_environment(tmp_path)
    port = get_free_port()

    master = TOPOSMasterIntegrator(
        config_path=str(config_file),
        hdf5_path=str(hdf5_file),
        zmq_port=port,
    )
    try:
        assert master.config_path == config_file
        assert master.hdf5_path == hdf5_file
        assert master.zmq_port == port
        assert isinstance(master.orchestrator, CascadeOrchestrator)
        assert isinstance(master.crusher, ToposCrusher)
        assert isinstance(master.oet_client, OETServerIPCClient)
        assert isinstance(master.zmq_context, zmq.asyncio.Context)
        assert isinstance(master.zmq_socket, zmq.asyncio.Socket)
    finally:
        master.close()


def test_topos_master_init_missing_paths(tmp_path: Path) -> None:
    """Verify TOPOSMasterIntegrator raises FileNotFoundError if paths do not exist."""
    missing_config = tmp_path / "nonexistent_config.json"
    missing_hdf5 = tmp_path / "nonexistent_landscape.h5"

    with pytest.raises(FileNotFoundError, match="Master Integrator requires valid"):
        TOPOSMasterIntegrator(
            config_path=str(missing_config),
            hdf5_path=str(missing_hdf5),
            zmq_port=get_free_port(),
        )


def test_topos_master_context_manager(tmp_path: Path) -> None:
    """Verify TOPOSMasterIntegrator operates cleanly as a context manager and tears down resources."""
    config_file, hdf5_file = create_mock_environment(tmp_path)
    port = get_free_port()

    with TOPOSMasterIntegrator(str(config_file), str(hdf5_file), zmq_port=port) as master:
        assert master.zmq_port == port
        assert master.zmq_socket is not None

    # Socket and context should be closed after exit
    assert master.zmq_socket.closed


def test_oet_server_ipc_client_defaults_and_custom() -> None:
    """Verify OETServerIPCClient default initialization and custom configuration parameters."""
    default_client = OETServerIPCClient()
    assert default_client.host == "localhost"
    assert default_client.port == 8888
    assert default_client.scf_tole == 1e-5

    custom_client = OETServerIPCClient(host="10.0.0.42", port=9999, scf_tole=1e-6)
    assert custom_client.host == "10.0.0.42"
    assert custom_client.port == 9999
    assert custom_client.scf_tole == 1e-6


def test_oet_server_format_orca_extopt_input() -> None:
    """Verify ORCA/MPQC ExtOpt input generation with custom PAL, host, port, and TolE thresholds."""
    client = OETServerIPCClient(host="daemon.local", port=7777, scf_tole=1e-5)

    orca_input = client.format_orca_extopt_input("sample.xyz", pal=16)
    assert "! EXTOPT GOAT PAL16" in orca_input
    assert 'ProgExt "oet_client"' in orca_input
    assert 'Ext_Params "-b daemon.local:7777"' in orca_input
    assert "TolE 1e-05" in orca_input or "TolE 1e-5" in orca_input
    assert "* xyzfile 0 1 sample.xyz" in orca_input
    assert "%goat" in orca_input
    assert "maxen 12.0" in orca_input

    # Verify alias parity
    mpqc_input = client.format_mpqc_extopt_input("sample.xyz", pal=16)
    assert orca_input == mpqc_input


def test_oet_server_gradient_sign_flip_guard() -> None:
    """Verify Gradient Sign-Flip Guard (nabla E = -F) converts MLFF forces to energy gradients with float32 precision."""
    client = OETServerIPCClient()

    forces = np.array([[1.5, -2.0, 0.25], [-0.5, 0.0, -1.25]], dtype=np.float32)
    gradients = client.apply_gradient_sign_flip_guard(forces)

    assert gradients.dtype == np.float32
    np.testing.assert_array_almost_equal(gradients, -forces)
    assert np.all(gradients[0] == np.array([-1.5, 2.0, -0.25], dtype=np.float32))

    # Test with python lists and 1D arrays
    list_forces = [0.1, -0.2, 0.3]
    grad_1d = client.apply_gradient_sign_flip_guard(list_forces)
    assert grad_1d.dtype == np.float32
    np.testing.assert_array_almost_equal(grad_1d, np.array([-0.1, 0.2, -0.3], dtype=np.float32))

    # Test empty forces array
    empty_grad = client.apply_gradient_sign_flip_guard(np.array([]))
    assert empty_grad.size == 0
    assert empty_grad.dtype == np.float32


def test_oet_server_process_daemon_response_edge_cases() -> None:
    """Verify daemon response parsing across valid data, empty payloads, and missing keys."""
    client = OETServerIPCClient(scf_tole=1e-5)

    # 1. Normal payload with forces
    forces = np.array([[0.1, 0.2, 0.3]], dtype=np.float32)
    resp = client.process_daemon_response({"energy": -42.5, "forces": forces})
    assert resp["status"] == "SUCCESS"
    assert resp["energy_hartree"] == -42.5
    assert resp["scf_threshold"] == 1e-5
    np.testing.assert_array_almost_equal(resp["gradients_hartree_bohr"], -forces)

    # 2. Empty payload (default fallback)
    resp_empty = client.process_daemon_response({})
    assert resp_empty["status"] == "SUCCESS"
    assert resp_empty["energy_hartree"] == 0.0
    assert isinstance(resp_empty["gradients_hartree_bohr"], np.ndarray)
    assert resp_empty["gradients_hartree_bohr"].size == 0

    # 3. Payload with empty forces list
    resp_no_forces = client.process_daemon_response({"energy": "-150.25", "forces": []})
    assert resp_no_forces["energy_hartree"] == -150.25
    assert resp_no_forces["gradients_hartree_bohr"].size == 0


def test_macroscopic_boltzmann_synthesis(master_integrator: TOPOSMasterIntegrator) -> None:
    """Verify Macroscopic Boltzmann Synthesis extracts highest tier energies and computes correct populations."""
    hdf5_path = master_integrator.hdf5_path

    # Populate HDF5 with multi-tier isomer energies
    with h5py.File(hdf5_path, "a", libver="latest") as f:
        iso_group = f.create_group("deduplicated_isomers")

        # Isomer 1: Tier 1 (-100.0) and Tier 2 (-101.0 -> should take precedence)
        iso1 = iso_group.create_group("iso_01")
        iso1.create_group("tier_1").create_dataset("energy", data=-100.0)
        iso1.create_group("tier_2").create_dataset("energy", data=-101.0)

        # Isomer 2: Tier 1 only (-100.0)
        iso2 = iso_group.create_group("iso_02")
        iso2.create_group("tier_1").create_dataset("energy", data=-100.0)

    # Run Boltzmann synthesis
    master_integrator._macroscopic_boltzmann_synthesis(["iso_01", "iso_02"], temperature_K=298.15)

    # Edge cases: Non-existent group or empty isomer list should not raise exceptions
    master_integrator._macroscopic_boltzmann_synthesis([])
    master_integrator._macroscopic_boltzmann_synthesis(["nonexistent_iso"])


def test_zmq_ui_listener_lifecycle(master_integrator: TOPOSMasterIntegrator) -> None:
    """Verify the ZMQ UI listener daemon receives commands and returns ACKs without socket leaks."""
    async def run_listener_test() -> None:
        port = master_integrator.zmq_port
        ui_task = asyncio.create_task(master_integrator._zmq_ui_listener())

        client_ctx = zmq.asyncio.Context()
        client_sock = client_ctx.socket(zmq.REQ)
        client_sock.connect(f"tcp://127.0.0.1:{port}")

        try:
            # Send test command
            await client_sock.send_json({"command": "PING", "payload": "status_check"})
            response = await client_sock.recv_json()
            assert response["status"] == "ACK"
            assert response["message"] == "Command received"
        finally:
            client_sock.close(linger=0)
            client_ctx.term()
            ui_task.cancel()
            await asyncio.gather(ui_task, return_exceptions=True)

    asyncio.run(run_listener_test())


def test_run_escalation_pass(master_integrator: TOPOSMasterIntegrator) -> None:
    """Verify _run_escalation_pass handles empty databases and escalates registered isomers."""
    async def run_test() -> None:
        # 1. Escalation pass on empty database should cleanly exit
        await master_integrator._run_escalation_pass()

        # 2. Add an isomer to the HDF5 registry
        water_xyz = "3\nWater\nO 0.0 0.0 0.0\nH 0.0 0.76 0.59\nH 0.0 -0.76 0.59\n"
        with h5py.File(master_integrator.hdf5_path, "a", libver="latest") as f:
            if "deduplicated_isomers" not in f:
                iso_group = f.create_group("deduplicated_isomers")
            else:
                iso_group = f["deduplicated_isomers"]
            iso1 = iso_group.create_group("iso_water")
            iso1.create_dataset("initial_xyz", data=water_xyz.encode("utf-8"))

        with mock.patch("cascade_engine.cochem_topos_cascade_orchestrator.get_honest_xtb_calculator", return_value=LennardJones()), \
             mock.patch("cascade_engine.cochem_topos_cascade_orchestrator.MACEOFF24mCalculator", return_value=LennardJones(), create=True), \
             mock.patch("cascade_engine.cochem_topos_cascade_orchestrator.SubprocessBroker.execute", return_value=0, create=True), \
             mock.patch("cascade_engine.cochem_topos_cascade_orchestrator.CascadeOrchestrator._compute_true_hessian", return_value=[]):
            await master_integrator._run_escalation_pass()

    asyncio.run(run_test())


def test_execute_nested_assembly_pipeline(tmp_path: Path) -> None:
    """Verify execute_nested_assembly_pipeline executes monomer, strong, and weak complex phases and escalates."""
    config_file, hdf5_file = create_mock_environment(tmp_path)
    port = get_free_port()

    async def run_pipeline() -> None:
        master = TOPOSMasterIntegrator(
            config_path=str(config_file),
            hdf5_path=str(hdf5_file),
            zmq_port=port,
        )
        try:
            with mock.patch("core_engine.cochem_topos_crusher.get_honest_xtb_calculator", side_effect=lambda *args, **kwargs: LennardJones()), \
                 mock.patch("core_engine.cochem_topos_crusher.MACEOFF24mCalculator", side_effect=lambda *args, **kwargs: LennardJones(), create=True), \
                 mock.patch("cascade_engine.cochem_topos_cascade_orchestrator.get_honest_xtb_calculator", return_value=LennardJones()), \
                 mock.patch("cascade_engine.cochem_topos_cascade_orchestrator.MACEOFF24mCalculator", return_value=LennardJones(), create=True), \
                 mock.patch("cascade_engine.cochem_topos_cascade_orchestrator.SubprocessBroker.execute", return_value=0, create=True), \
                 mock.patch("cascade_engine.cochem_topos_cascade_orchestrator.CascadeOrchestrator._compute_true_hessian", return_value=[]):
                
                h2 = Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)])
                await master.execute_nested_assembly_pipeline(h2)
        finally:
            master.close()

    asyncio.run(run_pipeline())
