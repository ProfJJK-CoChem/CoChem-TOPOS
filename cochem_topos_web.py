import streamlit as st
import subprocess
import os
import sys
import psutil
import atexit
import hashlib
import logging
from pathlib import Path

st.set_page_config(page_title="CoChem-TOPOS - Native Pipeline UI", layout="wide")

def kill_zombie_processes() -> None:
    target_procs = ['orca', 'xtb', 'mpi', 'crest']
    for proc in psutil.process_iter(['name']):
        try:
            name = proc.info.get('name')
            if name is not None:
                name = name.lower()
                if any(target in name for target in target_procs):
                    proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            logging.warning(f"Could not terminate process: {e}")

atexit.register(kill_zombie_processes)

st.title("🔬 CoChem-TOPOS Control Panel")
st.markdown("This UI executes raw, heavy mathematical payloads natively.")

with st.sidebar:
    st.header("Pipeline Configuration")
    target_smiles = st.text_input("Target SMILES", "CCO")
    run_mode = st.selectbox("Execution Mode", ["Fast", "Accurate"])

if st.button("🚀 Execute Default Pipeline"):
    with st.spinner(f"Triggering quantum physics executor for {target_smiles}..."):
        st.info("Initiating Physical Math Execution Pipeline...")
        
        module_dir = Path(__file__).resolve().parent
        
        # Enforce configurable artifact directory per Core Directive 1
        artifact_dir = Path(os.environ.get("COCHEM_ARTIFACT_DIR", Path.home() / "cochem_artifacts"))
        artifact_dir.mkdir(parents=True, exist_ok=True)
        
        env = os.environ.copy()
        env["COCHEM_TARGET_H5"] = str(artifact_dir / "landscape.h5")
        env["COCHEM_ARTIFACT_DIR"] = str(artifact_dir)
        
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem
            
            mol = Chem.MolFromSmiles(target_smiles)
            if mol is None:
                st.error(f"Invalid SMILES string: {target_smiles}")
            else:
                mol = Chem.AddHs(mol)
                AllChem.EmbedMolecule(mol)
                xyz_path = artifact_dir / "target.xyz"
                Chem.rdmolfiles.MolToXYZFile(mol, str(xyz_path))

                cmd = [sys.executable, "-m", "core_engine.cochem_topos_master", str(xyz_path)]
                result = subprocess.run(
                    cmd, 
                    capture_output=True, 
                    text=True, 
                    check=True, 
                    timeout=3600, 
                    cwd=str(module_dir),
                    env=env
                )
                
                st.code(result.stdout[-3000:], language="text")
                st.success("✅ Execution Completed Natively. CPU load generated.")
                
                output_path = artifact_dir / "physical_output.out"
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(result.stdout)
                
        except subprocess.TimeoutExpired:
            st.error("Execution timed out. Purging zombies.")
            kill_zombie_processes()
        except subprocess.CalledProcessError as e:
            st.warning(f"Execution finished with non-zero exit code: {e.returncode}")
            if e.stderr:
                st.code(e.stderr[-3000:], language="text")
            kill_zombie_processes()
        except Exception as e:
            st.error(f"Pipeline crashed during physical execution: {str(e)}")
            kill_zombie_processes()
