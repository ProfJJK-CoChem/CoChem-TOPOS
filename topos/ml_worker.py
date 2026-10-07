"""Isolated finite ML inference worker; models never auto-download.

MACE serialized models must be trusted, separately provisioned artifacts. The
parent binds their exact SHA-256 and BASE binds the isolated interpreter.
"""
from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path

from .ml import ML_SCHEMA, ModelManifest, reduce_committee
from .models import Molecule, ResourceLimits
from .storage import atomic_json, digest_json, file_digest, json_bytes, read_json


class ModelSession:
    """Load a hash-bound committee once; evaluate subsequent geometries in memory."""

    def __init__(self, request: dict):
        import torch
        from ase import Atoms

        if set(request) != {"schema_version", "manifest", "molecules", "resources", "gpu_memory_mb"} or request["schema_version"] != ML_SCHEMA:
            raise ValueError("Unknown ML worker request contract")
        self.manifest = ModelManifest.model_validate(request["manifest"])
        resources = ResourceLimits.model_validate(request["resources"])
        molecules = [Molecule.model_validate(m) for m in request["molecules"]]
        if not 1 <= len(molecules) <= 10000:
            raise ValueError("Invalid frame count")
        for molecule in molecules:
            self.manifest.validate_molecule(molecule)
        for member in self.manifest.members:
            member.verify()
        package = "aimnet" if self.manifest.backend == "aimnet2" else "mace-torch"
        self.versions = {name: importlib.metadata.version(name) for name in (package, "torch", "numpy", "ase")}
        if self.versions[package] != self.manifest.package_version:
            raise ValueError("ML package version differs from manifest")
        torch.set_num_threads(resources.threads)
        torch.use_deterministic_algorithms(True)
        self.device = "cpu"
        if resources.device == "gpu":
            if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
                raise ValueError("GPU request requires one explicitly selected CUDA device")
            limit = request["gpu_memory_mb"]
            total = torch.cuda.get_device_properties(0).total_memory / 1024**2
            if type(limit) is not int or not 0 < limit <= total:
                raise ValueError("Invalid per-device GPU allocator limit")
            torch.cuda.set_per_process_memory_fraction(limit / total, device=0)
            torch.backends.cuda.matmul.allow_tf32 = False
            self.device = "cuda:0"
        elif resources.device != "cpu" or request["gpu_memory_mb"] is not None:
            raise ValueError("Requested ML device is unsupported or inconsistent")
        self.calculators, self.allowed_species = [], []
        for member in self.manifest.members:
            if self.manifest.backend == "mace":
                from mace.calculators import MACECalculator

                calculator = MACECalculator(model_paths=member.path, device=self.device,
                                            default_dtype=self.manifest.precision, head=self.manifest.head)
                heads = list(getattr(calculator.models[0], "heads", ["Default"]))
                if self.manifest.head is not None and self.manifest.head not in heads:
                    raise ValueError("Declared MACE head is absent from the actual checkpoint")
                if len(heads) > 1 and self.manifest.head is None:
                    raise ValueError("Multi-head MACE checkpoint requires an explicit model head")
                allowed = set(int(z) for z in calculator.models[0].atomic_numbers.tolist())
            else:
                from aimnet.calculators import AIMNet2Calculator

                calculator = AIMNet2Calculator(member.path, device=self.device, compile_model=False)
                if any(m.multiplicity != 1 for m in molecules) and not calculator.is_nse:
                    raise ValueError("AIMNet checkpoint ignores spin multiplicity; refusing open-shell inference")
                allowed = set((calculator.metadata or {}).get("implemented_species", []))
                if not allowed:
                    raise ValueError("AIMNet checkpoint must advertise its supported atomic numbers")
            if any(not set(Atoms(m.symbols).numbers) <= allowed for m in molecules):
                raise ValueError("Requested elements are outside actual checkpoint metadata")
            self.calculators.append(calculator)
            self.allowed_species.append(allowed)
        self.manifest_sha256 = digest_json(request["manifest"])

    def evaluate(self, molecules: list[Molecule]) -> list[dict]:
        import numpy as np
        from ase import Atoms

        if not 1 <= len(molecules) <= 10000:
            raise ValueError("Invalid frame count")
        frames = []
        for molecule in molecules:
            self.manifest.validate_molecule(molecule)
            energies, forces = [], []
            atoms = Atoms(molecule.symbols, positions=molecule.coordinates)
            for calculator, allowed in zip(self.calculators, self.allowed_species, strict=True):
                if not set(atoms.numbers) <= allowed:
                    raise ValueError("Requested elements are outside actual checkpoint metadata")
                if self.manifest.backend == "mace":
                    atoms.calc = calculator
                    energies.append(float(atoms.get_potential_energy()))
                    forces.append(np.asarray(atoms.get_forces(), dtype=float).tolist())
                else:
                    if molecule.multiplicity != 1 and not calculator.is_nse:
                        raise ValueError("AIMNet checkpoint ignores requested spin multiplicity")
                    output = calculator({"coord": np.asarray(molecule.coordinates), "numbers": atoms.numbers,
                                         "charge": float(molecule.charge), "mult": float(molecule.multiplicity)}, forces=True)
                    energies.append(float(output["energy"].detach().cpu().item()))
                    forces.append(output["forces"].detach().cpu().numpy().tolist())
            frames.append(reduce_committee(energies, forces, len(molecule.symbols)))
        return frames

    def verify_models(self):
        for member in self.manifest.members:
            member.verify()


def evaluate(request: dict) -> dict:
    session = ModelSession(request)
    frames = session.evaluate([Molecule.model_validate(m) for m in request["molecules"]])
    session.verify_models()
    return {"schema_version": ML_SCHEMA, "manifest_sha256": session.manifest_sha256,
            "versions": session.versions, "device": session.device, "frames": frames}


def serve(request: dict, request_path: Path) -> dict:
    """Serve a finite private local callback session; every call has raw evidence."""
    import os
    import socket
    import stat
    import struct
    import time

    from .ml_extopt import MAX_MESSAGE_BYTES, SOCKET_SCHEMA, receive_json, send_json

    if set(request) != {"schema_version", "manifest", "molecules", "resources", "gpu_memory_mb", "mode", "server"} or request["mode"] != "server":
        raise ValueError("Unknown persistent ML server request contract")
    spec = request["server"]
    required = {"socket_name", "max_requests", "client_module_sha256", "request_timeout_seconds"}
    if not required <= set(spec) or set(spec) - required - {"max_receipt_mb"}:
        raise ValueError("Unknown persistent ML socket configuration")
    if spec["socket_name"] != "s" or type(spec["max_requests"]) is not int or not 1 <= spec["max_requests"] <= 1_000_000:
        raise ValueError("Invalid socket name or request bound")
    if not isinstance(spec["request_timeout_seconds"], (int, float)) or not 0 < spec["request_timeout_seconds"] <= 600:
        raise ValueError("Invalid callback timeout")
    max_receipt_mb = spec.get("max_receipt_mb", 1024)
    if type(max_receipt_mb) is not int or not 4 <= max_receipt_mb <= 65536:
        raise ValueError("Persistent receipt allocation must be 4..65536 MiB")
    receipt_limit = max_receipt_mb * 1024**2
    receipt_bytes = 0
    folder = request_path.parent.resolve()
    if folder != Path.cwd().resolve() or stat.S_IMODE(folder.stat().st_mode) != 0o700:
        raise ValueError("Persistent server requires its private 0700 attempt directory as cwd")
    client_module = Path(__file__).with_name("ml_extopt.py")
    if file_digest(client_module) != spec["client_module_sha256"]:
        raise ValueError("Installed ExtOpt client module differs from reviewed source")
    reference = Molecule.model_validate(request["molecules"][0])
    if len(request["molecules"]) != 1:
        raise ValueError("Persistent server requires one reference chemical identity")
    identity = reference.model_dump(exclude={"coordinates"})
    session = ModelSession({k: v for k, v in request.items() if k not in {"mode", "server"}})
    deadline = time.monotonic() + ResourceLimits.model_validate(request["resources"]).budget_seconds
    count, successful, stopped = 0, 0, False
    socket_path = folder / "s"
    if socket_path.exists() or socket_path.is_symlink():
        raise ValueError("Persistent server refuses a pre-existing socket path")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind("s")
        os.chmod(socket_path, 0o600)
        listener.listen(16)
        listener.settimeout(.2)
        atomic_json(folder / "ready.json", {"schema_version": SOCKET_SCHEMA, "manifest_sha256": session.manifest_sha256,
                                            "versions": session.versions, "device": session.device,
                                            "model_load_count": len(session.calculators), "socket_name": "s"})
        while time.monotonic() < deadline and receipt_bytes + 2 * MAX_MESSAGE_BYTES + 4096 <= receipt_limit:
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            with connection:
                connection.settimeout(min(spec["request_timeout_seconds"], max(.001, deadline - time.monotonic())))
                if hasattr(socket, "SO_PEERCRED"):
                    _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if uid != os.getuid():
                        continue
                message = receive_json(connection)
                if message == {"schema_version": SOCKET_SCHEMA, "action": "stop", "manifest_sha256": session.manifest_sha256}:
                    send_json(connection, {"status": "stopped", "requests": count})
                    stopped = True
                    break
                count += 1
                receipt = {"schema_version": SOCKET_SCHEMA, "sequence": count, "request": message}
                try:
                    if count > spec["max_requests"]:
                        raise ValueError("Persistent ML request bound exceeded")
                    if set(message) != {"schema_version", "action", "manifest_sha256", "molecule", "external_input"} or message.get("schema_version") != SOCKET_SCHEMA or message.get("action") != "evaluate":
                        raise ValueError("Unknown persistent inference message")
                    if message["manifest_sha256"] != session.manifest_sha256:
                        raise ValueError("Callback requests a different model manifest")
                    molecule = Molecule.model_validate(message["molecule"])
                    if molecule.model_dump(exclude={"coordinates"}) != identity:
                        raise ValueError("Callback altered the reference chemical identity")
                    frame = session.evaluate([molecule])[0]
                    response = {"status": "completed", "sequence": count, "manifest_sha256": session.manifest_sha256, "frame": frame}
                    successful += 1
                except Exception as exc:
                    response = {"status": "failed", "sequence": count, "reason": str(exc)}
                receipt["response"] = response
                encoded_size = len(json_bytes(receipt)) + 1
                allocated = ((encoded_size + 4095) // 4096) * 4096
                if receipt_bytes + allocated > receipt_limit:
                    raise ValueError("Persistent receipt allocation exhausted")
                atomic_json(folder / "calls" / f"{count:07d}.json", receipt)
                receipt_bytes += allocated
                send_json(connection, response)
                if count >= spec["max_requests"]:
                    break
        session.verify_models()
        if file_digest(client_module) != spec["client_module_sha256"]:
            raise ValueError("Client module changed during persistent inference")
        return {"schema_version": ML_SCHEMA, "mode": "server", "manifest_sha256": session.manifest_sha256,
                "versions": session.versions, "device": session.device, "requests": count, "successful_requests": successful,
                "model_load_count": len(session.calculators), "receipt_allocated_bytes": receipt_bytes,
                "max_receipt_mb": max_receipt_mb,
                "termination": "requested-stop" if stopped else "request-time-or-receipt-bound"}
    finally:
        listener.close()
        socket_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    path = args.request
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError("ML request must be a bounded absolute regular file")
    digest = file_digest(path)
    request = read_json(path)
    result = serve(request, path) if request.get("mode") == "server" else evaluate(request)
    if file_digest(path) != digest:
        raise ValueError("ML request changed during inference")
    result["request_sha256"] = digest
    output = path.parent / "ml-result.json"
    if output.exists() or output.is_symlink():
        raise ValueError("Refusing to overwrite an existing ML result")
    atomic_json(output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
