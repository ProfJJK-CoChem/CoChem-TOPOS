"""CREST 3.0.2 native iMTD with a persistent, explicit molecular ML potential.

The native generic calculator reads Hartree energies and Hartree/Bohr gradients.
Its mandatory ancillary GFN0 WBO calculation estimates MD length only. Search
energies belong to the supplied checkpoint and require common-level refinement.
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path
from threading import Event

from .engines import EngineParseError, artifact_inventory, write_xyz
from .ml import ModelManifest
from .ml_extopt import ExtOptAllocation, PersistentMLServer
from .models import Molecule, ResourceLimits
from .runtime import available_cpu_count
from .sampling import SamplingResult, parse_crest_ensemble
from .storage import atomic_json, digest_json, file_digest, read_json

CREST_GENERIC_SOURCES = [
    "https://github.com/crest-lab/crest/blob/v3.0.2/src/calculator/generic_sc.f90",
    "https://github.com/crest-lab/crest/blob/v3.0.2/src/calculator/gradreader.f90",
    "https://github.com/crest-lab/crest/blob/v3.0.2/src/parsing/parse_calcdata.f90",
    "https://github.com/crest-lab/crest/blob/v3.0.2/src/algos/search_conformers.f90",
    "https://github.com/crest-lab/crest/blob/v3.0.2/src/choose_settings.f90",
]
ML_CREST_PROFILES = {"crest-imtdgc-v1": (), "crest-mquick-v1": ("--mquick",)}
CREST_GENERIC_BUILD_ID = "crest-3.0.2-generic-paths-v1"
CREST_GENERIC_CAPABILITY_VERSION = "3.0.2+topos-generic-paths-v1"
CREST_GENERIC_PATCH_SHA256 = "9f22e2d9e0cd9b6aa8a6d41a0c32b6271d659c62498f888f0d5d889cc09aa8b9"


def validate_crest_ml_distribution(binary: str | Path) -> dict:
    """Read-only provenance preflight before expensive training or inference.

    This verifies distribution files; BASE must independently authorize the
    actual executable. The sampler also checks its real native version banner.
    """
    binary = Path(binary)
    if not binary.is_absolute() or binary.is_symlink() or not binary.is_file():
        raise ValueError("Patched CREST executable must be an absolute regular file")
    build_file, patch_file = binary.parent / "installation.json", binary.parent / "source.patch"
    if (build_file.is_symlink() or patch_file.is_symlink() or not build_file.is_file()
            or not patch_file.is_file() or build_file.stat().st_size > 2_000_000
            or patch_file.stat().st_size > 100_000):
        raise ValueError("Patched CREST requires its bounded regular installation.json and source.patch provenance")
    provenance = read_json(build_file)
    expected = {"build_id": CREST_GENERIC_BUILD_ID, "upstream_version": "3.0.2",
                "upstream_commit": "af7eb9927e2b36e24b14055f9eba3bea5be0014e",
                "binary_sha256": file_digest(binary), "source_patch_sha256": CREST_GENERIC_PATCH_SHA256}
    if (any(provenance.get(key) != value for key, value in expected.items())
            or file_digest(patch_file) != CREST_GENERIC_PATCH_SHA256
            or any(provenance.get("build_features", {}).get(key) is not True
                   for key in ("OpenMP", "TOMLF", "GFN0", "GFNFF"))):
        raise ValueError("Patched CREST source/build provenance differs from the required native contract")
    return {**provenance, "capability_version": CREST_GENERIC_CAPABILITY_VERSION,
            "executable": str(binary), "provenance_file_sha256": file_digest(build_file)}


def crest_ml_input(molecule: Molecule, wrapper: str | Path, resources: ResourceLimits) -> str:
    """Compile the documented generic calculator, retaining native preoptimization.

    ``runtype=imtd-gc`` turns preoptimization off in CREST 3.0.2's TOML reader.
    Select iMTD explicitly with CLI ``--v3`` instead. CREST constructs an
    unquoted shell invocation for the fixed callback, requiring a safe path.
    """
    path = str(wrapper)
    if not Path(path).is_absolute() or re.fullmatch(r"[/A-Za-z0-9_.+-]+", path) is None:
        raise ValueError("CREST generic callback requires an absolute shell-safe fixed wrapper path")
    if resources.device != "cpu":
        raise ValueError("CREST native allocation must be CPU; only its model server can use GPU")
    return "\n".join([
        'input = "input.xyz"', f"threads = {resources.threads}",
        "[[calculation.level]]", 'method = "generic"', f'binary = "{path}"',
        'gradtype = "engrad"', 'gradfile = "genericinp.engrad"',
        f"chrg = {molecule.charge}", f"uhf = {molecule.multiplicity - 1}", "",
    ])


def crest_ml_command(binary: str | Path, molecule: Molecule, resources: ResourceLimits, *,
                     profile: str = "crest-imtdgc-v1", energy_window_kcal_mol: float = 12) -> list[str]:
    if profile not in ML_CREST_PROFILES:
        raise ValueError("Unsupported CREST ML profile")
    if (isinstance(energy_window_kcal_mol, bool) or not isinstance(energy_window_kcal_mol, (int, float))
            or not math.isfinite(energy_window_kcal_mol) or energy_window_kcal_mol <= 0):
        raise ValueError("Native ML screening window must be finite positive kcal/mol")
    if resources.device != "cpu":
        raise ValueError("CREST native allocation must be CPU")
    # --mquick resets EWIN: put the explicitly requested window last.
    return [str(binary), "ml-crest.toml", "--newversion", "--v3", "-T", str(resources.threads),
            "--chrg", str(molecule.charge), "--uhf", str(molecule.multiplicity - 1),
            "--keepdir", "--origin", *ML_CREST_PROFILES[profile],
            "--ewin", format(energy_window_kcal_mol, ".12g")]


def _receipt_evidence(server: PersistentMLServer) -> dict:
    """Cross-check retained calls against the completed immutable worker receipt."""
    summary, expected = server.summary, server.binding["manifest_sha256"]
    count = summary.get("requests")
    if (type(count) is not int or count <= 0 or summary.get("successful_requests") != count
            or summary.get("manifest_sha256") != expected
            or server.process is None or server.process.status != "completed"
            or summary.get("termination") != "requested-stop"):
        raise EngineParseError("Persistent ML inference did not finish with successful, bound callbacks")
    paths = sorted((server.folder / "calls").glob("*.json"))
    if len(paths) != count:
        raise EngineParseError("ML callback receipt count differs from retained native evidence")
    for index, path in enumerate(paths, 1):
        receipt = read_json(path)
        request, response = receipt.get("request", {}), receipt.get("response", {})
        if (path.name != f"{index:07d}.json" or receipt.get("sequence") != index
                or request.get("manifest_sha256") != expected
                or response.get("manifest_sha256") != expected
                or response.get("status") != "completed" or response.get("sequence") != index):
            raise EngineParseError("ML callback provenance differs from the bound checkpoint/sequence")
        native = request.get("external_input", {})
        if native.get("format") != "CREST3.0.2 generic XYZ/engrad":
            raise EngineParseError("Model callback lacks the CREST generic input provenance")
    return {"requests": count, "successful_requests": count, "manifest_sha256": expected,
            "receipt_directory": str(server.folder / "calls"),
            "model_load_count": summary.get("model_load_count")}


def run_crest_ml(molecule: Molecule, manifest: ModelManifest, resources: ResourceLimits,
                 workdir: str | Path, *, runtime, allocation: ExtOptAllocation,
                 gpu_index: int | None = None, gpu_memory_mb: int | None = None,
                 energy_window_kcal_mol: float = 12, profile: str = "crest-imtdgc-v1",
                 max_requests: int = 10000, max_receipt_mb: int = 1024,
                 cancel_event: Event | None = None) -> SamplingResult:
    """Execute CREST and the immutable model concurrently under BASE authority.

    ``allocation.orca_*`` fields allocate the CREST CPU driver here; the shared
    allocation type predates this adapter. RAM and CPU allocations sum within
    the caller's total. Search duration and callback/receipt bounds never select
    a smaller search profile or a different potential after failure.
    """
    started = time.monotonic()
    result = SamplingResult(status="unsupported", engine="crest", method=manifest.family,
        algorithm="CREST-mquick" if profile == "crest-mquick-v1" else "iMTD-GC",
        potential_engine=manifest.backend, potential_engine_version=manifest.package_version,
        metadata={"execution_kind": "not-executed", "profile": profile,
                  "manifest": manifest.model_dump(mode="json"),
                  "manifest_sha256": digest_json(manifest.model_dump(mode="json")),
                  "resources": resources.model_dump(mode="json"), "exhaustive": False,
                  "effective_seed": None, "randomness": "native CREST controlled initialization",
                  "energy_definition": "supplied ML checkpoint electronic energy",
                  "validation_status": "requires-common-level-refinement",
                  "stationary_point_classification": "unclassified",
                  "native_energy_window_kcal_mol": energy_window_kcal_mol,
                  "ancillary_methods": ["internal GFN0-xTB WBO/flexibility estimate for MD length"],
                  "potential_fallback": False, "native_source_contracts": CREST_GENERIC_SOURCES,
                  "reduced_search": profile == "crest-mquick-v1",
                  "disabled_native_stages": ["normal MD", "genetic crossing"] if profile == "crest-mquick-v1" else [],
                  "max_requests": max_requests, "max_receipt_mb": max_receipt_mb})
    folder = Path(workdir).absolute()
    server = None
    owns_folder = False

    def remaining() -> float:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("CREST ML search cancelled")
        value = resources.budget_seconds - (time.monotonic() - started)
        if value <= 0:
            raise TimeoutError("CREST ML search wall budget exhausted")
        return value

    try:
        remaining()
        allocation.validate(resources)
        if resources.threads > available_cpu_count() or resources.device not in {"cpu", "gpu"}:
            raise ValueError("Unsupported total CPU/device allocation")
        if (type(max_requests) is not int or not 1 <= max_requests <= 1_000_000
                or type(max_receipt_mb) is not int or not 4 <= max_receipt_mb <= 65536):
            raise ValueError("Explicit callback count/receipt bound is outside the supported range")
        manifest.validate_molecule(molecule)
        if any(value is not None for value in molecule.isotopes):
            raise ValueError("CREST isotope MD masses are unverified; isotope labels cannot be ignored")
        if len(molecule.symbols) < 3:
            raise ValueError("Native CREST sampling requires at least three atoms")
        native_resources = resources.model_copy(update={"device": "cpu", "threads": allocation.orca_threads,
                                                       "memory_mb": allocation.orca_memory_mb})
        crest_ml_command("crest", molecule, native_resources, profile=profile,
                         energy_window_kcal_mol=energy_window_kcal_mol)
        if runtime is None or any(not callable(getattr(runtime, name, None)) for name in
                                  ("run_ml_process", "run_process", "resolve_executable")):
            result.status = "unavailable"
            result.diagnostics["reason"] = "CREST ML search requires mandatory BASE native and ML execution authority"
            return result
        binary = Path(runtime.resolve_executable("crest"))
        if not binary.is_absolute() or not binary.is_file():
            result.status = "unavailable"
            result.diagnostics["reason"] = "BASE did not resolve an installed absolute CREST executable"
            return result
        binary = binary.resolve()
        if any(part.is_symlink() for part in [folder, *folder.parents]):
            raise ValueError("CREST ML attempt path may not traverse symlinks")
        if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
            raise ValueError("Fresh CREST ML attempt directory required")
        native = folder / "native"
        wrapper = native / "ml-crest-client"
        deck = crest_ml_input(molecule, wrapper, native_resources)
        folder.mkdir(parents=True, exist_ok=True)
        owns_folder = True
        native.mkdir()
        result.metadata.update({"crest_executable": str(binary), "crest_sha256": file_digest(binary),
                                "allocation": {"ml_threads": allocation.ml_threads,
                                    "ml_memory_mb": allocation.ml_memory_mb,
                                    "crest_threads": allocation.orca_threads,
                                    "crest_memory_mb": allocation.orca_memory_mb}})
        probe = runtime.run_process([str(binary), "--version"], folder,
            native_resources.model_copy(update={"threads": 1, "budget_seconds": min(10, remaining())}),
            cancel_event=cancel_event, log_prefix="crest-version")
        result.diagnostics["version_process"] = probe.to_dict()
        if probe.status != "completed":
            result.status = probe.status
            result.diagnostics["reason"] = probe.reason
            return result
        version_text = Path(probe.stdout_path).read_text() + Path(probe.stderr_path).read_text()
        match = re.search(r"(?im)^\s*crest\s+(\d+\.\d+\.\d+)\s*$", version_text)
        if match is None or match.group(1) != "3.0.2":
            raise ValueError("Generic ML sampling is verified only for CREST 3.0.2")
        result.engine_version = match.group(1)
        if f"TOPOS patch: {CREST_GENERIC_BUILD_ID}" not in version_text:
            result.status = "unsupported"
            result.diagnostics["reason"] = (
                "Stock CREST 3.0.2 caches stale generic calculator paths across parallel jobs; "
                "native ML sampling requires the explicitly identified generic-paths-v1 build"
            )
            return result
        build_provenance = validate_crest_ml_distribution(binary)
        result.metadata.update({"native_build_id": CREST_GENERIC_BUILD_ID,
                                "native_source_patch_sha256": CREST_GENERIC_PATCH_SHA256,
                                "native_source_commit": "af7eb9927e2b36e24b14055f9eba3bea5be0014e",
                                "native_build_provenance": build_provenance})
        atomic_json(folder / "native-build.json", build_provenance)
        (folder / "native-source.patch").write_bytes((binary.parent / "source.patch").read_bytes())
        write_xyz(molecule, native / "input.xyz")
        (native / "ml-crest.toml").write_text(deck, encoding="utf-8")
        atomic_json(folder / "model-manifest.json", manifest.model_dump(mode="json"))
        ml_resources = resources.model_copy(update={"threads": allocation.ml_threads,
            "memory_mb": allocation.ml_memory_mb, "budget_seconds": remaining()})
        server = PersistentMLServer(runtime, manifest, molecule, ml_resources, folder / "model-server",
            gpu_index=gpu_index, gpu_memory_mb=gpu_memory_mb, max_requests=max_requests,
            max_receipt_mb=max_receipt_mb, cancel_event=cancel_event)
        server.start()
        server.make_client(native, wrapper, mode="crest", maximum_external_cores=allocation.orca_threads)
        result.metadata["ml_server_binding"] = server.binding
        result.metadata["ml_server_ready"] = server.ready
        result.command = crest_ml_command(binary, molecule, native_resources, profile=profile,
                                         energy_window_kcal_mol=energy_window_kcal_mol)
        atomic_json(folder / "sampling-request.json", {"molecule": molecule.model_dump(mode="json"),
            "manifest_sha256": result.metadata["manifest_sha256"], "command": result.command,
            "native_input_sha256": file_digest(native / "ml-crest.toml"),
            "wrapper_sha256": file_digest(wrapper), "resources": resources.model_dump(mode="json"),
            "allocation": result.metadata["allocation"], "max_requests": max_requests,
            "max_receipt_mb": max_receipt_mb})
        result.metadata["execution_kind"] = "real"
        process = runtime.run_process(result.command, native,
            native_resources.model_copy(update={"budget_seconds": remaining()}),
            cancel_event=cancel_event, log_prefix="crest")
        result.status = process.status
        result.diagnostics["process"] = process.to_dict()
        # A healthy server can preserve its final summary after native failure.
        server.close(cancel=process.status in {"cancelled", "timed-out"})
        raw = Path(process.stdout_path).read_text(errors="replace")
        ensemble_path = native / "crest_conformers.xyz"
        if ensemble_path.is_file():
            result.ensemble = parse_crest_ensemble(ensemble_path, molecule)
            for frame in result.ensemble:
                frame.source = "CREST-ML"
                frame.metadata.update({"manifest_sha256": result.metadata["manifest_sha256"],
                    "potential_engine": manifest.backend, "energy_definition": "supplied ML checkpoint electronic energy"})
        if process.status != "completed":
            result.diagnostics["reason"] = process.reason
            return result
        if ("CREST terminated normally." not in raw or not result.ensemble
                or not re.search(r"--?v3\s*:\s*iMTD-GC", raw)
                or '* method = "generic"' not in raw or f'* binary = "{wrapper}"' not in raw):
            raise EngineParseError("Native log lacks the requested generic iMTD method, termination or final ensemble")
        windows = re.findall(r"sorting energy window \(EWIN\)\s*:\s*([0-9.]+)", raw, re.I)
        if not windows or not math.isclose(float(windows[-1]), energy_window_kcal_mol, abs_tol=5.1e-5):
            raise EngineParseError("Final native screening window differs from the requested kcal/mol window")
        if file_digest(binary) != result.metadata["crest_sha256"]:
            raise EngineParseError("CREST executable changed during sampling")
        result.metadata["ml_callback_evidence"] = _receipt_evidence(server)
        result.metadata["returned_frame_count"] = len(result.ensemble)
        result.metadata["convergence_scope"] = "native search completion only; no exhaustive search or minimum classification"
        result.converged = True
    except InterruptedError as exc:
        result.status, result.diagnostics["reason"] = "cancelled", str(exc)
    except TimeoutError as exc:
        result.status, result.diagnostics["reason"] = "timed-out", str(exc)
    except (ValueError, OSError, RuntimeError) as exc:
        result.status = "failed" if folder.is_dir() and any(folder.iterdir()) else "unsupported"
        result.diagnostics["reason"] = str(exc)
    finally:
        if server is not None:
            try:
                server.close(cancel=result.status != "completed")
                result.metadata["ml_server_summary"] = server.summary
                if server.process is not None:
                    result.diagnostics["ml_server_process"] = server.process.to_dict()
            except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
                result.status = "failed"
                result.diagnostics["ml_server_shutdown_error"] = str(exc)
        result.elapsed_seconds = time.monotonic() - started
        if result.status != "completed":
            result.converged = False if result.metadata["execution_kind"] == "real" else None
        if owns_folder:
            try:
                result.artifacts = artifact_inventory(folder)
            except (OSError, EngineParseError) as exc:
                result.status, result.converged = "failed", False
                result.diagnostics["artifact_error"] = str(exc)
        for frame in result.ensemble:
            frame.metadata.update({"adapter_attempt_status": result.status,
                                   "partial_native_attempt": result.status != "completed"})
    return result
