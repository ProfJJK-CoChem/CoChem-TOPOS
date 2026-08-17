import streamlit as st
import subprocess
import os
import sys
import time
import json
import psutil
import logging
from pathlib import Path
from typing import Optional, Any, Tuple
import h5py
import zmq
import socket
import uuid
import threading

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CoChem.TOPOS.WebUI")

st.set_page_config(page_title="CoChem-TOPOS - Native Pipeline UI", layout="wide")

def cleanup_child_processes(proc: Optional[subprocess.Popen] = None) -> None:
    """Terminates specifically the child process tree for a given run."""
    if proc is None or not proc.pid:
        return
        
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        target_procs = children + [parent]
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return

    for p in target_procs:
        try:
            p.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    _, alive = psutil.wait_procs(target_procs, timeout=2)
    for p in alive:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

def stream_reader(pipe, buffer):
    """Reads from a pipe line by line and appends to a buffer to prevent deadlock."""
    try:
        for line in iter(pipe.readline, ''):
            if not line:
                break
            buffer.append(line)
    except Exception as e:
        logger.error(f"Stream reader error: {e}")
    finally:
        try:
            pipe.close()
        except Exception:
            pass

def run_pipeline_sync(
    cmd: list[str],
    env: dict,
    cwd: str,
    zmq_port: int,
    timeout: float = 3600.0,
    status_placeholder: Optional[Any] = None,
    log_placeholder: Optional[Any] = None,
) -> Tuple[int, str]:
    """
    Executes the pipeline synchronously inside the Streamlit thread, avoiding async context
    issues. Prevents pipe deadlock via background reader threads. Uses DEALER socket.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=cwd,
        env=env,
        bufsize=1,
        universal_newlines=True
    )
    
    stdout_buffer = []
    reader_thread = threading.Thread(target=stream_reader, args=(proc.stdout, stdout_buffer))
    reader_thread.daemon = True
    reader_thread.start()

    ctx = zmq.Context()
    sock = ctx.socket(zmq.DEALER) # DEALER avoids REQ/REP state locks
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(f"tcp://127.0.0.1:{zmq_port}")
    
    start_time = time.time()
    telemetry_pings = 0

    try:
        while proc.poll() is None:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)
                
            # Periodic UI updates for logs
            if log_placeholder and len(stdout_buffer) > 0:
                log_placeholder.code("".join(stdout_buffer[-20:]), language="text")
                
            # Telemetry ping
            try:
                sock.send_json({
                    "command": "poll_telemetry",
                    "elapsed_seconds": round(elapsed, 1),
                    "timestamp": time.time(),
                }, flags=zmq.NOBLOCK)
                
                # Wait for reply with 500ms timeout
                if sock.poll(500):
                    response = sock.recv_json()
                    telemetry_pings += 1
                    if status_placeholder:
                        status_placeholder.info(
                            f"📡 Telemetry [Port {zmq_port}] | Pings: {telemetry_pings} | "
                            f"Status: {response.get('status', 'ACK')} | Elapsed: {round(elapsed, 1)}s"
                        )
                else:
                    if status_placeholder:
                        status_placeholder.info(
                            f"⏳ Executing... [Elapsed: {round(elapsed, 1)}s | Awaiting telemetry]"
                        )
            except zmq.ZMQError:
                pass
                
        reader_thread.join(timeout=2.0)
        return proc.returncode, "".join(stdout_buffer)
    finally:
        cleanup_child_processes(proc)
        try:
            sock.close(linger=0)
            ctx.term()
        except Exception:
            pass

st.title("🔬 CoChem-TOPOS Control Panel")
st.markdown("This UI executes raw, heavy mathematical payloads natively.")

with st.sidebar:
    st.header("Pipeline Configuration")
    target_smiles = st.text_input("Target SMILES", "CCO")
    run_mode = st.selectbox("Execution Mode", ["Fast", "Accurate"])

def execute_cochem():
    # Setup unique session ID to prevent cross-contamination
    run_uuid = uuid.uuid4().hex
    
    st.info("Initiating Physical Math Execution Pipeline...")

    module_dir = Path(__file__).resolve().parent

    artifact_dir = Path(os.environ.get("COCHEM_ARTIFACT_DIR", Path.home() / ".cochem_artifacts"))
    artifact_dir.mkdir(parents=True, exist_ok=True)

    hdf5_path = artifact_dir / f"landscape_{run_uuid}.h5"
    config_path = artifact_dir / f"cochem_system_config_{run_uuid}.json"
    xyz_path = artifact_dir / f"target_{run_uuid}.xyz"

    # Find free dynamic port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        zmq_port = s.getsockname()[1]

    config_payload = {
        "target_smiles": target_smiles,
        "run_mode": run_mode,
        "artifact_dir": str(artifact_dir),
        "landscape_h5": str(hdf5_path),
        "zmq_port": zmq_port,
        "timestamp": time.time(),
        "version": "4.0",
        "run_uuid": run_uuid
    }
    with open(config_path, "w", encoding="utf-8") as cfg_file:
        json.dump(config_payload, cfg_file, indent=2)

    if not hdf5_path.exists():
        with h5py.File(str(hdf5_path), "w", libver="latest") as f:
            f.attrs["version"] = "1.0"
            f.attrs["description"] = "CoChem-TOPOS Landscape Datastore"
            f.attrs["run_mode"] = run_mode
            f.attrs["target_smiles"] = target_smiles
            if "deduplicated_isomers" not in f:
                f.create_group("deduplicated_isomers")

    env = os.environ.copy()
    env["COCHEM_TARGET_H5"] = str(hdf5_path)
    env["COCHEM_ARTIFACT_DIR"] = str(artifact_dir)
    env["COCHEM_RUN_MODE"] = run_mode
    env["COCHEM_CONFIG_PATH"] = str(config_path) 

    telemetry_status = st.empty()
    log_status = st.empty()

    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem

        mol = Chem.MolFromSmiles(target_smiles)
        if mol is None:
            st.error(f"Invalid SMILES string: {target_smiles}")
            return # Use return instead of st.stop() to avoid hijacking control flow

        mol = Chem.AddHs(mol)
        embed_code = AllChem.EmbedMolecule(mol, randomSeed=42)

        if embed_code != 0:
            logger.warning("Initial 3D embedding failed. Attempting fallback with random coordinates...")
            embed_code = AllChem.EmbedMolecule(mol, useRandomCoords=True, randomSeed=42)

        if embed_code == 0:
            if AllChem.MMFFOptimizeMolecule(mol) != 0:
                AllChem.UFFOptimizeMolecule(mol)
        else:
            logger.warning("Random coords embedding failed. Attempting multi-conformer generation...")
            conf_ids = AllChem.EmbedMultipleConfs(mol, numConfs=5, maxAttempts=100, randomSeed=42, useRandomCoords=True)
            if conf_ids and len(conf_ids) > 0:
                best_conf = conf_ids[0]
                if AllChem.MMFFOptimizeMolecule(mol, confId=best_conf) != 0:
                    AllChem.UFFOptimizeMolecule(mol, confId=best_conf)
            else:
                st.error(f"Failed to generate valid 3D conformer coordinates for '{target_smiles}'.")
                return

        if mol.GetNumConformers() == 0:
            st.error(f"No valid 3D conformers found for '{target_smiles}'.")
            return

        Chem.rdmolfiles.MolToXYZFile(mol, str(xyz_path))

        cmd = [sys.executable, "-m", "core_engine.cochem_topos_master", str(xyz_path)]

        returncode, stdout = run_pipeline_sync(
            cmd=cmd,
            env=env,
            cwd=str(module_dir),
            zmq_port=zmq_port,
            timeout=3600,
            status_placeholder=telemetry_status,
            log_placeholder=log_status,
        )

        if returncode != 0:
            st.warning(f"Execution finished with non-zero exit code: {returncode}")
            if stdout:
                st.code(stdout[-3000:], language="text")
        else:
            if stdout:
                st.code(stdout[-3000:], language="text")
            st.success(f"✅ Execution Completed Natively in [{run_mode}] mode.")

            output_path = artifact_dir / f"physical_output_{run_uuid}.out"
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(stdout)

            # Enhanced UI Result Visualization
            st.subheader("📊 Execution Results")
            st.write(f"**Target SMILES:** `{target_smiles}`")
            st.write(f"**Run UUID:** `{run_uuid}`")
            
            try:
                with h5py.File(str(hdf5_path), "r") as f:
                    if "deduplicated_isomers" in f:
                        isomers = list(f["deduplicated_isomers"].keys())
                        col1, col2 = st.columns(2)
                        col1.metric("Generated Isomers", len(isomers))
                        col2.metric("Target Mode", f.attrs.get("run_mode", "Unknown"))
                        if isomers:
                            st.write("Sample Isomers Found:")
                            st.json(isomers[:10])
            except Exception as e:
                st.warning(f"Could not parse HDF5 output database for visualizations: {e}")

    except subprocess.TimeoutExpired:
        st.error("Execution timed out.")
    except Exception as e:
        st.error(f"Pipeline crashed during physical execution: {str(e)}")


if st.button("🚀 Execute Default Pipeline"):
    with st.spinner(f"Triggering quantum physics executor for {target_smiles}..."):
        execute_cochem()
