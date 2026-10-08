"""Installed MACE CLI wrapper enforcing the requested single-device VRAM cap."""
from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    payload = json.loads(args.request.read_text())
    if payload.get("schema_version") != "topos-mace-training-worker/1":
        raise ValueError("Unsupported training worker request")
    for filename, expected in payload["input_files"].items():
        path = Path(filename)
        if not path.is_absolute() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Training input changed after authority verification")
    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError("Training requires exactly one explicitly selected available CUDA device")
    memory = torch.cuda.get_device_properties(0).total_memory
    requested = payload["gpu_memory_mb"] * 1024**2
    if not 0 < requested <= memory:
        raise ValueError("Training VRAM limit exceeds the selected device")
    torch.cuda.set_per_process_memory_fraction(requested / memory, device=0)
    torch.set_num_threads(payload["threads"])
    command = payload["command"]
    if command[1:3] != ["-m", "mace.cli.run_train"]:
        raise ValueError("Only the official reviewed MACE training module is supported")
    sys.argv = ["mace.cli.run_train", *command[3:]]
    runpy.run_module("mace.cli.run_train", run_name="__main__")


if __name__ == "__main__":
    main()
