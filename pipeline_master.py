#!/usr/bin/env python3
"""
CoChem-TOPOS: Pipeline Master Orchestrator
Manages state handoffs between geometry stages (01 to 05).
Queries the system registry for paths and logs completion matrices.
"""

import os
import sys
import json
import subprocess
import logging
from pathlib import Path

class Colors:
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

logging.basicConfig(
    filename='topos_pipeline_master.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class ToposOrchestrator:
    def __init__(self):
        self.config_path = Path("cochem_system_config.json")
        self.state_marker = Path("stage_n_complete.json")
        self.stages = [
            ("01_INGEST_GC.py", "Stage 1: Smart Ingestion & Graph Connectivity"),
            ("GOAT.py", "Stage 2.3: Global Optimization via Active Topology"),
            ("Crusher.py", "Stage 2.5: Jiggle-Quench Basin Deduplication")
        ]
        self.system_config = self.load_config()
        
    def load_config(self) -> dict:
        if not self.config_path.exists():
            logging.error("FATAL: cochem_system_config.json missing. Cannot orchestrate.")
            print(f"{Colors.FAIL}❌ FATAL: System registry not found. Run Stage 0 setup first.{Colors.ENDC}")
            sys.exit(1)
        with open(self.config_path, 'r') as f:
            return json.load(f)

    def load_state(self) -> dict:
        if self.state_marker.exists():
            try:
                with open(self.state_marker, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {"completed_stages": []}

    def save_state(self, state: dict):
        with open(self.state_marker, 'w') as f:
            json.dump(state, f, indent=4)

    def execute_stage(self, script_name: str, desc: str, state: dict) -> bool:
        if script_name in state["completed_stages"]:
            print(f"{Colors.OKCYAN}⏭️  Skipping {desc} (Already Completed).{Colors.ENDC}")
            return True
            
        if not Path(script_name).exists():
            # For the purpose of the audit, we warn if downstream files aren't coded yet
            print(f"{Colors.WARNING}⚠️ Warning: {script_name} not found in directory. Halting pipeline execution cleanly.{Colors.ENDC}")
            return False

        print(f"{Colors.BOLD}▶ Executing {desc}...{Colors.ENDC}")
        try:
            subprocess.run([sys.executable, script_name], check=True)
            state["completed_stages"].append(script_name)
            self.save_state(state)
            print(f"{Colors.OKGREEN}✅ {desc} Completed Successfully.{Colors.ENDC}")
            logging.info(f"Successfully completed: {script_name}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"{Colors.FAIL}❌ FATAL: {script_name} failed. Pipeline halted.{Colors.ENDC}")
            logging.error(f"Execution failed for {script_name}: {e}")
            return False

    def run(self):
        print(f"\n{Colors.HEADER}{Colors.BOLD}========================================={Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}   CoChem-TOPOS: Stage Orchestrator      {Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}========================================={Colors.ENDC}\n")
        
        state = self.load_state()
        
        for script, desc in self.stages:
            if not self.execute_stage(script, desc, state):
                break
                
        print(f"\n{Colors.OKCYAN}Orchestrator sequence concluded.{Colors.ENDC}\n")

if __name__ == "__main__":
    orchestrator = ToposOrchestrator()
    orchestrator.run()