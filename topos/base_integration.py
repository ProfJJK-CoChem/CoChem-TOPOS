"""TOPOS execution through the mandatory CoChem-BASE installation.

BASE owns Stage 0 authority, executable identity, and subprocess containment.
TOPOS owns molecular inputs, scientific validation, resource ceilings, and its
immutable run records. No installation or licensed binary is duplicated here.
"""
from __future__ import annotations

import atexit
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import math
import os
import re
import sys
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event, Thread
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import ResourceLimits
    from .runtime import ProcessResult


class BaseIntegrationError(RuntimeError):
    """Mandatory installation, registry authority, or broker is unavailable."""


def _source_root(variable: str, project: str, package: str) -> Path | None:
    value = os.environ.get(variable)
    if not value:
        return None
    root = Path(value).expanduser().resolve()
    manifest = root / "pyproject.toml"
    if not manifest.is_file():
        raise BaseIntegrationError(f"{variable} must identify the {project} repository root")
    import tomllib

    declared = tomllib.loads(manifest.read_text(encoding="utf-8")).get("project", {}).get("name", "")
    if declared.lower().replace("_", "-") != project.lower():
        raise BaseIntegrationError(f"{variable} does not identify {project}")
    source = root / "src" if (root / "src" / package).is_dir() else root
    if not (source / package).is_dir():
        raise BaseIntegrationError(f"{variable} lacks the expected Python package")
    return source


@dataclass(frozen=True)
class EcosystemStatus:
    available: bool
    components: dict[str, dict[str, Any]]
    problems: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "problems": list(self.problems)}


def inspect_ecosystem(*, require_torq: bool = True) -> EcosystemStatus:
    """Discover installations without importing TORQ's side-effectful bootstrap.

    An explicitly configured source checkout is supported during development.
    BASE's bundled ``cochem_torq`` namespace alone does not establish installation
    of the mandatory standalone CoChem-TORQ distribution.
    """
    components: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for project, package, variable in (
        ("CoChem-BASE", "cochem_base", "COCHEM_BASE_ROOT"),
        ("CoChem-TOPOS", "topos", "COCHEM_TOPOS_ROOT"),
        ("CoChem-TORQ", "cochem_torq", "COCHEM_TORQ_ROOT"),
    ):
        if project == "CoChem-TORQ" and not require_torq:
            continue
        try:
            source = _source_root(variable, project, package)
            if source is not None:
                # Only BASE is imported by this adapter. TORQ discovery must not
                # replace BASE's shared cochem namespace or execute its bootstrap.
                if project == "CoChem-BASE" and str(source) not in sys.path:
                    sys.path.insert(0, str(source))
                    importlib.invalidate_caches()
                components[project] = {"available": True, "kind": "explicit-source", "path": str(source)}
                if project == "CoChem-TORQ":
                    spec = importlib.util.find_spec(package)
                    origin = Path(spec.origin).resolve() if spec and spec.origin else None
                    shadowed = origin is not None and not origin.is_relative_to(source / package)
                    components[project].update(installed=True, import_path=str(origin) if origin else None,
                                               import_shadowed=shadowed, consumer_ready=False)
                continue
            try:
                distribution = importlib.metadata.distribution(project)
            except importlib.metadata.PackageNotFoundError:
                distribution = None
            spec = importlib.util.find_spec(package)
            if spec is None or (project == "CoChem-TORQ" and distribution is None):
                raise BaseIntegrationError(f"{project} is not installed; provision the mandatory CoChem package")
            components[project] = {
                "available": True, "kind": "installed" if distribution else "importable-source",
                "version": distribution.version if distribution else None,
                "path": spec.origin or next(iter(spec.submodule_search_locations or ()), None),
            }
            if project == "CoChem-TORQ":
                direct = distribution.read_text("direct_url.json") if distribution else None
                source_path = None
                if direct:
                    url = urllib.parse.urlsplit(json.loads(direct).get("url", ""))
                    if url.scheme == "file":
                        source_path = Path(urllib.parse.unquote(url.path)).resolve()
                import_path = Path(spec.origin).resolve() if spec.origin else None
                # BASE also ships a cochem_torq namespace. A separate installed
                # TORQ distribution is mandatory but its consumer remains an
                # independent capability, especially when BASE shadows it.
                shadowed = source_path is not None and import_path is not None and not import_path.is_relative_to(source_path)
                components[project].update(installed=True, distribution_path=str(source_path) if source_path else None,
                                           import_path=str(import_path) if import_path else None,
                                           import_shadowed=shadowed, consumer_ready=False)
        except (ImportError, ValueError, OSError, BaseIntegrationError) as exc:
            components[project] = {"available": False}
            problems.append(str(exc))
    return EcosystemStatus(not problems, components, tuple(problems))


def _engine_environment(environment: dict[str, str], threads: int) -> dict[str, str]:
    """Keep runtime configuration while excluding host and Actions credentials."""
    allowed = {
        "PATH", "HOME", "USER", "TMPDIR", "TMP", "TEMP", "SYSTEMROOT", "WINDIR",
        "COMSPEC", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
        "XTBPATH", "XTBHOME", "FORTRAN_UNBUFFERED_ALL",
    }
    result = {key: value for key, value in environment.items()
              if key in allowed or re.fullmatch(r"(?:OMP|MKL|OPENBLAS|NUMEXPR|OMPI|PMI|UCX|XTB|CREST)_[A-Z0-9_]+", key)}
    result = {key: value for key, value in result.items()
              if not re.search(r"TOKEN|PASSWORD|SECRET|CREDENTIAL|AUTHORIZATION", key)}
    result.update({key: str(threads) for key in (
        "OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
    )})
    result.update(OMP_DYNAMIC="FALSE", OMP_STACKSIZE="16M", CUDA_VISIBLE_DEVICES="")
    return result


def _orca_deck_allocation(command: list[str], workdir: str | Path, resources: ResourceLimits) -> int:
    """Authorize the actual confined TOPOS deck, including cheap serial probes."""
    if len(command) != 2:
        raise BaseIntegrationError("ORCA execution requires one explicit input deck and no extra arguments")
    folder = Path(workdir).resolve()
    deck = Path(command[1])
    deck = (folder / deck).resolve() if not deck.is_absolute() else deck.resolve()
    if not deck.is_relative_to(folder) or not deck.is_file() or deck.stat().st_size > 4 * 1024**2:
        raise BaseIntegrationError("ORCA input deck must be a bounded regular file confined to its work directory")
    text = deck.read_text(encoding="utf-8")
    # Only canonical TOPOS blocks are accepted. Remove comments before counting
    # declarations so a comment cannot supply or conceal a resource allocation.
    text = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    maxcores = re.findall(r"(?im)^\s*%maxcore\s+([1-9][0-9]*)\s*$", text)
    pals = re.findall(r"(?im)^\s*%pal\s+nprocs\s+([1-9][0-9]*)\s+end\s*$", text)
    if (len(maxcores) != 1 or len(pals) != 1 or len(re.findall(r"(?i)%maxcore\b", text)) != 1
            or len(re.findall(r"(?i)%pal\b", text)) != 1):
        raise BaseIntegrationError("ORCA deck requires exactly one canonical %maxcore and %pal allocation")
    maxcore, cores = int(maxcores[0]), int(pals[0])
    if cores != resources.threads:
        raise BaseIntegrationError("ORCA deck nprocs does not match the total audited CPU request")
    if maxcore * cores > resources.memory_mb:
        raise BaseIntegrationError("ORCA deck MaxCore exceeds the total memory ceiling")
    return maxcore


class BaseRuntime:
    """Bind native engine attempts to BASE's audited registry and broker APIs."""

    def __init__(self, registry_path: str | Path | None = None, *, require_torq: bool = True):
        self.ecosystem = inspect_ecosystem(require_torq=require_torq)
        if not self.ecosystem.available:
            raise BaseIntegrationError("; ".join(self.ecosystem.problems))
        try:
            authority = importlib.import_module("cochem_base.core_engine.execution_authority")
            registry = importlib.import_module("cochem_base.core.cochem_core_registry_manager")
            config = importlib.import_module("cochem_base.config_loader")
            broker = importlib.import_module("cochem.concurrency.subprocess_broker")
            self.registry_path = Path(config.resolve_config_path(registry_path)).resolve()
            if registry_path is not None and self.registry_path != Path(registry_path).expanduser().resolve():
                raise BaseIntegrationError("BASE resolved a different registry than explicitly requested")
            self.registry = registry.load_system_config(self.registry_path, verify_integrity=True)
            if not self.registry.verify_checksum():
                raise BaseIntegrationError("BASE registry lacks a valid Stage 0 checksum")
            self._authorize = authority.authorize_engine_execution
            self._broker_type = broker.SubprocessBroker
        except Exception as exc:
            raise BaseIntegrationError(f"CoChem-BASE execution setup failed: {exc}") from exc

    def provenance(self) -> dict[str, Any]:
        return {"backend": "cochem-base", "ecosystem": self.ecosystem.to_dict(),
                "registry_path": str(self.registry_path),
                "registry_sha256": hashlib.sha256(self.registry_path.read_bytes()).hexdigest(),
                "registry_checksum": self.registry.registry_checksum}

    def resolve_executable(self, engine: str, executable: str | Path | None = None) -> str:
        try:
            return self._authorize(engine, registry_path=self.registry_path,
                                   executable=executable, cores=1, maxcore_mb=1).executable
        except Exception as exc:
            raise BaseIntegrationError(str(exc)) from exc

    def validate_resources(self, resources: ResourceLimits, *, engine: str | None = None,
                           gpu_index: int | None = None, gpu_memory_mb: int | None = None) -> None:
        from .runtime import available_cpu_count

        if resources.device != "cpu":
            if resources.device != "gpu" or engine not in {"mace", "aimnet2"}:
                raise BaseIntegrationError("Only an explicitly audited ML engine may request GPU execution")
            metrics = self.registry.hardware.gpu_compute_metrics
            if (type(gpu_index) is not int or not 0 <= gpu_index < metrics.device_count
                    or type(gpu_memory_mb) is not int or not 1 <= gpu_memory_mb <= metrics.vram_gb * 1024):
                raise BaseIntegrationError("GPU index and positive VRAM request must fit measured BASE GPU authority")
            inherited = os.environ.get("CUDA_VISIBLE_DEVICES")
            if inherited is not None and str(gpu_index) not in inherited.split(","):
                raise BaseIntegrationError("Requested GPU is excluded by the inherited device visibility boundary")
        elif gpu_index is not None or gpu_memory_mb is not None:
            raise BaseIntegrationError("CPU execution cannot carry an implicit GPU allocation")
        if resources.threads > min(self.registry.hardware.allocatable_compute_cores, available_cpu_count()):
            raise BaseIntegrationError("Requested cores exceed the audited/current CPU allocation")
        if resources.memory_mb > self.registry.hardware.ram_gb * 1024:
            raise BaseIntegrationError("Requested memory exceeds the BASE audited RAM allocation")
        if not math.isfinite(resources.budget_seconds) or resources.budget_seconds <= 0:
            raise BaseIntegrationError("A finite positive execution budget is required")

    def run_ml_process(
        self, command: list[str], workdir: str | Path, resources: ResourceLimits, *, engine: str,
        request_sha256: str, worker_sha256: str, model_files: dict[str, str],
        gpu_index: int | None = None, gpu_memory_mb: int | None = None,
        cancel_event: Event | None = None, log_prefix: str = "ml", output_limit_mb: int = 256,
    ) -> ProcessResult:
        return self._run_ml_module(command, workdir, resources, engine=engine,
                                   request_sha256=request_sha256, worker_sha256=worker_sha256,
                                   model_files=model_files, gpu_index=gpu_index, gpu_memory_mb=gpu_memory_mb,
                                   cancel_event=cancel_event, log_prefix=log_prefix, output_limit_mb=output_limit_mb,
                                   worker_module="topos.ml_worker")

    def run_mace_training_process(
        self, command: list[str], workdir: str | Path, resources: ResourceLimits, *,
        package_version: str, input_files: dict[str, str], gpu_index: int, gpu_memory_mb: int,
        cancel_event: Event | None = None,
    ) -> ProcessResult:
        """Authorize a bounded official MACE fine-tuning CLI via an installed wrapper."""
        from .storage import atomic_json, file_digest

        if resources.device != "gpu":
            raise BaseIntegrationError("MACE fine-tuning requires an explicitly audited CUDA allocation")
        self.validate_resources(resources, engine="mace", gpu_index=gpu_index, gpu_memory_mb=gpu_memory_mb)
        if package_version != "0.3.16" or self.registry.engines.mace is None or self.registry.engines.mace.version != package_version:
            raise BaseIntegrationError("MACE fine-tuning requires the reviewed, actually audited 0.3.16 package")
        folder = Path(workdir).resolve()
        if folder.exists() and any(folder.iterdir()):
            raise BaseIntegrationError("MACE fine-tuning requires a fresh native work directory")
        if (len(command) < 4 or command[1:3] != ["-m", "mace.cli.run_train"]
                or any(not isinstance(value, str) or "\x00" in value for value in command)):
            raise BaseIntegrationError("Only the explicit official MACE training CLI is supported")
        flags = {}
        for argument in command[3:]:
            if not argument.startswith("--"):
                raise BaseIntegrationError("MACE training options require explicit named flags")
            key, _, value = argument[2:].partition("=")
            if key in flags:
                raise BaseIntegrationError("Duplicate MACE training option")
            flags[key] = value
        fixed = {"device": "cuda", "default_dtype": "float64", "multiheads_finetuning": "True",
                 "E0s": "foundation", "energy_key": "REF_energy", "forces_key": "REF_forces",
                 "num_workers": "0", "plot": "False", "error_table": "PerAtomRMSE", "launcher": "none",
                 "save_cpu": "", "keep_checkpoints": ""}
        files = {"foundation_model", "train_file", "valid_file", "pt_train_file", "pt_valid_file"}
        numeric = {"seed", "max_num_epochs", "batch_size", "valid_batch_size", "energy_weight", "forces_weight"}
        directories = {"work_dir": folder, "model_dir": folder / "models", "checkpoints_dir": folder / "checkpoints",
                       "results_dir": folder / "results", "log_dir": folder / "logs", "downloads_dir": folder / "downloads"}
        required = set(fixed) | files | numeric | set(directories) | {"name"}
        if set(flags) not in (required, required | {"foundation_head"}) or any(flags.get(k) != v for k, v in fixed.items()):
            raise BaseIntegrationError("MACE training option set differs from the reviewed fine-tuning protocol")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", flags["name"]):
            raise BaseIntegrationError("Invalid confined MACE model name")
        if "foundation_head" in flags and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", flags["foundation_head"]):
            raise BaseIntegrationError("Invalid foundation head")
        for key in numeric:
            try:
                value = float(flags[key])
            except ValueError as exc:
                raise BaseIntegrationError("Invalid MACE numeric option") from exc
            if not math.isfinite(value) or value < 0 or (key != "seed" and value == 0):
                raise BaseIntegrationError("MACE numeric options must be finite and within the reviewed bounds")
            if key in {"seed", "max_num_epochs", "batch_size", "valid_batch_size"} and (not value.is_integer() or value > 2**31 - 1):
                raise BaseIntegrationError("MACE integer options are invalid")
        if any(flags[key] not in input_files or not Path(flags[key]).is_absolute() for key in files):
            raise BaseIntegrationError("Every native MACE input must have an explicit immutable file hash")
        if any(Path(flags[key]).resolve() != expected for key, expected in directories.items()):
            raise BaseIntegrationError("MACE outputs must remain in the fresh native attempt directory")
        folder.mkdir(parents=True, exist_ok=True)
        request = folder / "training-worker-request.json"
        payload = {"schema_version": "topos-mace-training-worker/1", "command": command,
                   "input_files": input_files, "gpu_memory_mb": gpu_memory_mb, "threads": resources.threads}
        atomic_json(request, payload)
        worker = Path(__file__).with_name("ml_training_worker.py")
        wrapper = [command[0], "-m", "topos.ml_training_worker", "--request", str(request)]
        return self._run_ml_module(wrapper, folder, resources, engine="mace", request_sha256=file_digest(request),
                                   worker_sha256=file_digest(worker), model_files=input_files, gpu_index=gpu_index,
                                   gpu_memory_mb=gpu_memory_mb, cancel_event=cancel_event, log_prefix="training",
                                   output_limit_mb=1024, worker_module="topos.ml_training_worker")

    def _run_ml_module(
        self, command: list[str], workdir: str | Path, resources: ResourceLimits, *, engine: str,
        request_sha256: str, worker_sha256: str, model_files: dict[str, str],
        gpu_index: int | None = None, gpu_memory_mb: int | None = None,
        cancel_event: Event | None = None, log_prefix: str = "ml", output_limit_mb: int = 256,
        worker_module: str,
    ) -> ProcessResult:
        """Run a hash-bound Python ML worker through actual BASE silo authority.

        Models/packages are never enrolled here. Missing Stage 0 micro-silo
        evidence or a worker absent from that interpreter prevents execution.
        The worker must independently enforce its requested GPU allocator limit.
        """
        from .storage import atomic_json, file_digest

        started = time.monotonic()
        self.validate_resources(resources, engine=engine, gpu_index=gpu_index, gpu_memory_mb=gpu_memory_mb)
        if engine not in {"mace", "aimnet2"} or os.name != "posix":
            raise BaseIntegrationError("This BASE ML worker boundary requires a supported POSIX ML silo")
        if worker_module not in {"topos.ml_worker", "topos.ml_training_worker"}:
            raise BaseIntegrationError("Unsupported installed ML worker")
        if (len(command) != 5 or command[1:4] != ["-m", worker_module, "--request"]
                or any(not isinstance(value, str) or "\x00" in value for value in command)):
            raise BaseIntegrationError("ML authority accepts only the explicit TOPOS module worker and request file")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", log_prefix) or output_limit_mb < 1:
            raise ValueError("Invalid ML worker log configuration")
        folder = Path(workdir).resolve()
        request_path = Path(command[4])
        if (not request_path.is_absolute() or request_path.is_symlink() or not request_path.is_file()
                or not request_path.resolve().is_relative_to(folder) or request_path.stat().st_size > 2_000_000):
            raise BaseIntegrationError("The ML request must be a bounded regular file confined to its attempt")
        if file_digest(request_path) != request_sha256 or not re.fullmatch(r"[a-f0-9]{64}", worker_sha256):
            raise BaseIntegrationError("The ML request or worker digest is invalid")
        if not isinstance(model_files, dict) or not model_files:
            raise BaseIntegrationError("ML execution requires every model member's explicit path and SHA-256")
        for filename, expected in model_files.items():
            path = Path(filename)
            if (not path.is_absolute() or path.is_symlink() or not path.is_file()
                    or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected)
                    or file_digest(path) != expected):
                raise BaseIntegrationError("An ML model member differs from its declared immutable identity")
        raw = self.registry.model_dump(mode="json")
        native = raw["engines"].get(engine)
        silos = (raw.get("stage0") or {}).get("micro_silos", {})
        silo = silos.get(native.get("track")) if isinstance(native, dict) else None
        if (not isinstance(silo, dict) or silo.get("python_executable") != command[0]
                or not silo.get("packages") or not silo.get("python_version")):
            raise BaseIntegrationError("Actual BASE Stage 0 micro-silo and package-lock evidence is required for ML")
        package = "mace-torch" if engine == "mace" else "aimnet"
        if package not in silo["packages"]:
            raise BaseIntegrationError("The requested ML engine is absent from the audited micro-silo package lock")
        try:
            authority = self._authorize(engine, registry_path=self.registry_path, command=command,
                                        cores=resources.threads,
                                        maxcore_mb=max(1, int(resources.memory_mb * .75 / resources.threads)))
        except Exception as exc:
            raise BaseIntegrationError(f"BASE ML execution authority failed: {exc}") from exc

        def remaining():
            seconds = resources.budget_seconds - (time.monotonic() - started)
            if seconds <= 0:
                raise BaseIntegrationError("ML budget exhausted during immutable-input and silo validation")
            return resources.model_copy(update={"budget_seconds": seconds})

        probe_code = """import hashlib, importlib.metadata, importlib.util, json, pathlib, site, sys
expected = json.loads(sys.argv[1])
assert pathlib.Path(sys.prefix).resolve() == pathlib.Path(expected['root']).resolve(), 'wrong interpreter silo'
assert sys.prefix != sys.base_prefix and not site.ENABLE_USER_SITE, 'unisolated interpreter'
assert 'include-system-site-packages = false' in (pathlib.Path(sys.prefix)/'pyvenv.cfg').read_text().lower(), 'global package leakage'
version = '.'.join(map(str, sys.version_info[:3]))
assert version == expected['python_version'] or version.startswith(expected['python_version']+'.'), 'Python version drift'
versions = {name: importlib.metadata.version(name) for name in expected['packages']}
assert versions == expected['packages'], 'audited package version drift'
spec = importlib.util.find_spec(expected['worker_module'])
assert spec and spec.origin, 'TOPOS worker is not installed in the audited silo'
path = pathlib.Path(spec.origin)
assert not path.is_symlink() and path.resolve().is_relative_to(pathlib.Path(sys.prefix).resolve()), 'worker is outside the isolated installed package'
digest = hashlib.sha256(path.read_bytes()).hexdigest()
assert digest == expected['worker_sha256'], 'installed worker identity differs from reviewed source'
distribution = importlib.metadata.distribution('cochem-topos-ml-worker')
try:
 importlib.metadata.distribution('cochem-topos')
 raise AssertionError('controller and worker namespace ownership overlap')
except importlib.metadata.PackageNotFoundError:
 pass
manifest_path = pathlib.Path(distribution.locate_file('topos/data/ml_worker_distribution.json')).resolve()
assert manifest_path.is_relative_to(pathlib.Path(sys.prefix).resolve()), 'worker distribution manifest outside silo'
manifest = json.loads(manifest_path.read_text())
assert manifest['schema_version'] == 'topos-ml-worker-distribution/0.1.0', 'unknown worker distribution'
assert manifest['version'] == distribution.version == expected['topos_version'], 'worker distribution version drift'
assert manifest['source_sha256'] == expected['source_sha256'], 'worker dependency source differs from controller revision'
for name, expected_sha in expected['source_sha256'].items():
 installed = pathlib.Path(distribution.locate_file(name)).resolve()
 assert installed.is_relative_to(pathlib.Path(sys.prefix).resolve()), 'worker source outside silo'
 assert hashlib.sha256(installed.read_bytes()).hexdigest() == expected_sha, 'installed worker dependency source changed'
for name, package_version in manifest['dependencies'].items():
 assert importlib.metadata.version(name) == package_version, 'worker dependency version drift'
result = {'worker_path':str(path),'worker_sha256':digest,'packages':versions,'python_version':version,'gpu':None,
 'worker_distribution':distribution.version,'source_sha256':expected['source_sha256'],
 'distribution_manifest_path':str(manifest_path),'distribution_manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest()}

if expected['gpu_memory_mb'] is not None:
 import torch
 assert torch.cuda.is_available() and torch.cuda.device_count() == 1, 'selected GPU is unavailable'
 properties = torch.cuda.get_device_properties(0)
 memory_mb = properties.total_memory / 1024**2
 assert expected['gpu_memory_mb'] <= memory_mb, 'request exceeds selected-device VRAM'
 result['gpu'] = {'visible_device_count':1,'name':properties.name,'memory_mb':memory_mb}
print(json.dumps(result,sort_keys=True))
"""
        from . import __version__
        source_root = Path(__file__).resolve().parent.parent
        source_files = {path.relative_to(source_root).as_posix(): file_digest(path)
                        for path in sorted((source_root / "topos").rglob("*"))
                        if path.is_file() and path.suffix in {".py", ".json"} and "__pycache__" not in path.parts
                        and path.name != "ml_worker_distribution.json"}
        contract = {**silo, "worker_sha256": worker_sha256, "worker_module": worker_module, "gpu_memory_mb": gpu_memory_mb,
                    "source_sha256": source_files, "topos_version": __version__}
        probe_command = [command[0], "-I", "-c", probe_code, json.dumps(contract, sort_keys=True)]
        probe = self._execute_authorized(probe_command, folder, remaining(), authority, engine=engine,
                                         cancel_event=cancel_event, log_prefix=log_prefix + "-authority",
                                         output_limit_mb=4, cuda_visible_devices=str(gpu_index) if gpu_index is not None else None)
        if probe.status != "completed":
            if probe.status in {"cancelled", "timed-out"}:
                return probe
            raise BaseIntegrationError("The actual isolated ML interpreter/package/worker/GPU probe failed; inspect its retained streams")
        observed = json.loads(Path(probe.stdout_path).read_text(encoding="utf-8"))
        binding = {"schema_version": "topos-base-ml-authority/0.1.0", "authority_kind": "audited-ML-micro-silo",
                   "engine": engine, "interpreter": command[0], "interpreter_sha256": authority.binary_sha256,
                   "request_sha256": request_sha256, "worker_sha256": worker_sha256, "worker_module": worker_module,
                   "model_files": model_files, "resources": resources.model_dump(mode="json"),
                   "gpu_index": gpu_index, "gpu_memory_mb": gpu_memory_mb, "observed": observed,
                   "registry_sha256": file_digest(self.registry_path), "probe": probe.to_dict()}
        atomic_json(folder / (log_prefix + "-authority.json"), binding)
        result = self._execute_authorized(command, folder, remaining(), authority, engine=engine,
                                          cancel_event=cancel_event, log_prefix=log_prefix, output_limit_mb=output_limit_mb,
                                          cuda_visible_devices=str(gpu_index) if gpu_index is not None else None,
                                          isolated_python=True)
        if file_digest(request_path) != request_sha256 or any(file_digest(Path(p)) != h for p, h in model_files.items()):
            raise BaseIntegrationError("The immutable ML request or model members changed during execution")
        if file_digest(Path(observed["worker_path"])) != worker_sha256 or file_digest(self.registry_path) != binding["registry_sha256"]:
            raise BaseIntegrationError("ML worker or BASE authority changed during execution")
        if file_digest(Path(observed["distribution_manifest_path"])) != observed["distribution_manifest_sha256"]:
            raise BaseIntegrationError("The installed worker source manifest changed during execution")
        installed_root = Path(observed["distribution_manifest_path"]).parents[2]
        if any(file_digest(installed_root / name) != expected for name, expected in source_files.items()):
            raise BaseIntegrationError("An installed worker dependency changed during execution")
        return result

    def _orca_distribution_utility(self) -> tuple[Path, Any, dict[str, Any]]:
        """Resolve only the official basis exporter from the audited distribution.

        This is distribution utility authority, not a claim that Stage 0
        individually registered this helper as a calculation engine.
        """
        try:
            parent = self._authorize("orca", registry_path=self.registry_path, cores=1, maxcore_mb=1)
            binary = Path(parent.executable).resolve(strict=True)
            configured = os.environ.get("COCHEM_ORCA_PROVENANCE")
            candidates = ([Path(configured)] if configured else
                          [directory / "cochem-orca-provenance.json" for directory in list(binary.parents)[:3]])
            provenance_path = next((path.resolve() for path in candidates if path.is_file()), None)
            if provenance_path is None:
                raise BaseIntegrationError("The complete installed ORCA distribution provenance is required for basis export")
            source = _source_root("COCHEM_BASE_ROOT", "CoChem-BASE", "cochem_base")
            if source is None:
                spec = importlib.util.find_spec("cochem_base")
                # BASE is a PEP 420 namespace package: origin is intentionally
                # None for a genuine editable installation. Resolve its actual
                # package search location before looking for the installer pin.
                locations = list(spec.submodule_search_locations or ()) if spec else []
                package_path = (Path(spec.origin).resolve().parent if spec and spec.origin else
                                Path(locations[0]).resolve() if locations else None)
                source = package_path.parent if package_path is not None else None
            manifests = [] if source is None else [source / "scripts/orca-distribution.json",
                                                   source.parent / "scripts/orca-distribution.json"]
            manifest_path = next((path for path in manifests if path.is_file()), None)
            if manifest_path is None:
                raise BaseIntegrationError("The installed BASE source distribution manifest is unavailable")
            manifest_bytes = manifest_path.read_bytes()
            manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
            manifest = json.loads(manifest_bytes)
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            if (provenance.get("schema_version") != 1 or provenance.get("distribution") != manifest
                    or provenance.get("manifest_sha256") != manifest_hash
                    or provenance.get("archive_sha256") != manifest.get("sha256")
                    or provenance.get("orca_version") != manifest.get("orca_version")
                    or Path(provenance.get("executable", "")).resolve() != binary):
                raise BaseIntegrationError("ORCA installed distribution provenance does not match BASE's pinned manifest")
            install_root = provenance_path.parent
            helper = binary.parent / "orca_exportbasis"
            files = provenance.get("files", {})
            hashes = {}
            for name, path in (("orca", binary), ("exporter", helper)):
                if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK) or not path.is_relative_to(install_root):
                    raise BaseIntegrationError(f"The {name} executable is not a regular member of the installed ORCA distribution")
                entry = files.get(path.relative_to(install_root).as_posix(), {})
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if entry.get("sha256") != digest or entry.get("bytes") != path.stat().st_size:
                    raise BaseIntegrationError(f"The {name} executable differs from the audited ORCA distribution inventory")
                hashes[name] = digest
            if hashes["orca"] != parent.binary_sha256:
                raise BaseIntegrationError("ORCA parent executable differs from BASE Stage 0 authority")
            authority = {
                "authority_kind": "verified-ORCA-distribution-utility",
                "exporter_path": str(helper), "exporter_sha256": hashes["exporter"],
                "orca_path": str(binary), "orca_sha256": hashes["orca"],
                "orca_version": manifest["orca_version"], "archive_sha256": manifest["sha256"],
                "distribution_manifest_sha256": manifest_hash, "distribution": manifest,
                "distribution_provenance_path": str(provenance_path),
                "distribution_provenance_sha256": hashlib.sha256(provenance_path.read_bytes()).hexdigest(),
                "registry_sha256": hashlib.sha256(self.registry_path.read_bytes()).hexdigest(),
            }
            return helper, parent, authority
        except BaseIntegrationError:
            raise
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise BaseIntegrationError(f"ORCA distribution utility authorization failed: {exc}") from exc
        except Exception as exc:
            raise BaseIntegrationError(f"BASE ORCA parent authority failed: {exc}") from exc

    def run_orca_utility(
        self, arguments: list[str], workdir: str | Path, resources: ResourceLimits, *,
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        """Execute only ``orca_exportbasis`` with an exact, confined argument set."""
        from .storage import atomic_json, file_digest

        self.validate_resources(resources)
        if os.name != "posix" or resources.threads != 1:
            raise BaseIntegrationError("ORCA basis export requires a POSIX serial resource allocation")
        if (len(arguments) < 8 or any(not isinstance(item, str) or "\x00" in item for item in arguments)
                or arguments[:1] != ["-b"] or arguments[2:3] != ["-a"]
                or arguments[-4:-1] != ["-f", "GAMESS-US", "-o"]):
            raise BaseIntegrationError("Only explicit -b BASIS -a ELEMENTS -f GAMESS-US -o BASENAME basis export is supported")
        basis, elements, output_name = arguments[1], arguments[3:-4], arguments[-1]
        if not re.fullmatch(r"def2-(?:SVP|SVPD|TZVP|TZVPD|TZVPP|TZVPPD|QZVP|QZVPD|QZVPP|QZVPPD)|def2/J|def2/JK", basis):
            raise BaseIntegrationError("Basis export requires an explicitly supported def2 basis identity")
        supported = set("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr".split())
        if not elements or elements != sorted(set(elements)) or not set(elements) <= supported:
            raise BaseIntegrationError("Basis export elements must be sorted, unique H–Kr symbols in separate arguments")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*\.bas", output_name):
            raise BaseIntegrationError("Basis export output must be a confined .bas basename")
        folder = Path(workdir).resolve()
        if folder.exists() and any(folder.iterdir()):
            raise BaseIntegrationError("Basis export requires a fresh empty work directory")
        helper, parent, authority = self._orca_distribution_utility()
        try:
            parent = self._authorize("orca", registry_path=self.registry_path, cores=1,
                                     maxcore_mb=max(1, int(resources.memory_mb * .75)))
        except Exception as exc:
            raise BaseIntegrationError(f"BASE basis-export resource authority failed: {exc}") from exc
        command = [str(helper), *arguments]
        result = self._execute_authorized(command, folder, resources, parent, engine="orca", cancel_event=cancel_event,
                                          log_prefix="basis-export", threads_per_process=1, output_limit_mb=32)
        # Native code and its authority must remain stable throughout execution.
        _, _, after = self._orca_distribution_utility()
        if authority != after:
            raise BaseIntegrationError("ORCA basis exporter authority changed during execution")
        output = folder / output_name
        valid_output = output.is_file() and not output.is_symlink() and output.stat().st_size > 0
        status = result.status
        if result.status == "completed" and not valid_output:
            status = "failed"
        receipt = {
            "schema_version": "topos-orca-basis-export/0.1.0", **authority,
            "status": status, "basis": basis, "elements": elements, "format": "GAMESS-US",
            "command": command, "process": result.to_dict(), "output_path": str(output),
            "resources": resources.model_dump(mode="json"),
            "parent_stage0": {"engine": "orca", "cores": parent.cores, "maxcore_mb": parent.maxcore_mb,
                              "cpu_affinity": list(parent.cpu_affinity)},
            "output_sha256": file_digest(output) if valid_output else None,
            "evidence": [{"path": str(path), "sha256": file_digest(path), "bytes": path.stat().st_size}
                         for path in (Path(result.stdout_path), Path(result.stderr_path))],
        }
        atomic_json(folder / "basis-export-receipt.json", receipt)
        return receipt

    def export_orca_basis(
        self, basis: str, elements: list[str], workdir: str | Path, resources: ResourceLimits, *,
        output_name: str = "basis.bas", cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        """Export canonical shared basis bytes with native distribution evidence."""
        return self.run_orca_utility(["-b", basis, "-a", *sorted(set(elements)), "-f", "GAMESS-US", "-o", output_name],
                                     workdir, resources, cancel_event=cancel_event)

    def run_process(
        self, command: list[str], workdir: str | Path, resources: ResourceLimits, *,
        cancel_event: Event | None = None, log_prefix: str = "engine",
        environment: dict[str, str] | None = None, output_limit_mb: int = 256,
        threads_per_process: int | None = None,
    ) -> ProcessResult:
        """Run one native attempt; retain full bytes, enforce bounds, never retry.

        A tiny exec launcher redirects streams before replacing itself with the
        authorized executable. This avoids BASE's captured-output ring buffer
        truncating the native logs used by TOPOS scientific parsers.
        """
        self.validate_resources(resources)
        if threads_per_process is not None and (
            isinstance(threads_per_process, bool) or not isinstance(threads_per_process, int)
            or not 1 <= threads_per_process <= resources.threads
        ):
            raise ValueError("Per-process threads must be within the total audited allocation")
        if os.name != "posix":
            raise BaseIntegrationError("TOPOS native resource launcher currently requires POSIX (use WSL on Windows)")
        if not command or any(not isinstance(arg, str) or "\x00" in arg for arg in command):
            raise ValueError("command must be an explicit non-NUL argument vector")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", log_prefix) or output_limit_mb < 1:
            raise ValueError("Invalid native log configuration")
        matches = [name for name, record in self.registry.model_dump(mode="json")["engines"].items()
                   if isinstance(record, dict) and record.get("path") == command[0]]
        if len(matches) != 1:
            raise BaseIntegrationError("Native command must identify exactly one audited BASE engine")
        # Authorize the actual ORCA deck allocation (including small diagnostic
        # probes), with a separate total hard limit in the launcher/RSS monitor.
        maxcore = (_orca_deck_allocation(command, workdir, resources) if matches[0] == "orca"
                   else max(1, int(resources.memory_mb * .75 / resources.threads)))
        try:
            authorization = self._authorize(matches[0], registry_path=self.registry_path,
                                            command=command, cores=resources.threads, maxcore_mb=maxcore)
        except Exception as exc:
            raise BaseIntegrationError(str(exc)) from exc
        return self._execute_authorized(command, workdir, resources, authorization, engine=matches[0],
                                        cancel_event=cancel_event, log_prefix=log_prefix, environment=environment,
                                        output_limit_mb=output_limit_mb, threads_per_process=threads_per_process)

    def _execute_authorized(
        self, command: list[str], workdir: str | Path, resources: ResourceLimits, authorization: Any, *,
        engine: str, cancel_event: Event | None = None, log_prefix: str = "engine",
        environment: dict[str, str] | None = None, output_limit_mb: int = 256,
        threads_per_process: int | None = None,
        cuda_visible_devices: str | None = None, isolated_python: bool = False,
    ) -> ProcessResult:
        """Private common broker path after engine or distribution authority succeeds."""
        from .runtime import ProcessResult

        folder = Path(workdir).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        stdout, stderr = folder / f"{log_prefix}.stdout", folder / f"{log_prefix}.stderr"
        # Exclusive creation also catches symlink targets and stale output.
        with stdout.open("xb"), stderr.open("xb"):
            pass
        if cancel_event is not None and cancel_event.is_set():
            return ProcessResult(command, "cancelled", None, 0, 0, str(stdout), str(stderr), "cancelled before launch")
        # PAL ranks consume the full audited allocation; each ORCA MPI rank
        # uses one BLAS/OpenMP thread. Do not reduce the authorized CPU affinity
        # to one core merely to prevent nested thread oversubscription.
        native_threads = threads_per_process if threads_per_process is not None else (
            1 if engine == "orca" else resources.threads
        )
        supplied = _engine_environment({**os.environ, **(environment or {})}, native_threads)
        if cuda_visible_devices is not None:
            supplied["CUDA_VISIBLE_DEVICES"] = cuda_visible_devices
        if isolated_python:
            supplied.update(PYTHONSAFEPATH="1", PYTHONNOUSERSITE="1")
        if engine == "orca":
            # The BASE installer deliberately does not alter the controller
            # PATH. ORCA launches mpirun by name, so resolve and re-authorize
            # its actual registered executable before exposing that directory.
            paths = [str(Path(authorization.executable).resolve().parent)]
            if resources.threads > 1:
                try:
                    mpi = self._authorize("mpirun", registry_path=self.registry_path,
                                          cores=resources.threads, maxcore_mb=1)
                except Exception as exc:
                    raise BaseIntegrationError(f"Audited ORCA MPI launcher is unavailable: {exc}") from exc
                paths.append(str(Path(mpi.executable).resolve().parent))
            supplied["PATH"] = os.pathsep.join([*paths, supplied.get("PATH", os.defpath)])
            runtime_libraries = os.environ.get("COCHEM_ORCA_LD_LIBRARY_PATH")
            if runtime_libraries:
                supplied["LD_LIBRARY_PATH"] = runtime_libraries
        owner = self
        process_ready = Event()
        done = Event()
        state: dict[str, Any] = {"process": None, "peak": 0.0, "status": None, "reason": None}

        class ToposBroker(owner._broker_type):
            def assign_to_job(self, process):
                super().assign_to_job(process)
                state["process"] = process
                if authorization.cpu_affinity:
                    import psutil
                    psutil.Process(process.pid).cpu_affinity(list(authorization.cpu_affinity))
                process_ready.set()

            def _prepare_worker_environment(self, worker_index=0, retries=0, extra_env=None):
                # BASE's default topology environment copies all host variables.
                # A complete explicit engine environment keeps tokens out of QM.
                return supplied.copy()

        broker = ToposBroker(cwd=folder, env=supplied, base_scratch_dir=folder / ".base-scratch",
                             timeout_seconds=resources.budget_seconds, max_retries=1)
        # BASE may copy selected files into a global store. Keep its auxiliary
        # copies in this attempt; TOPOS alone publishes its validated RunStore.
        broker.store_dir = folder / ".base-evidence"
        started = time.monotonic()

        def monitor() -> None:
            import psutil
            while not done.wait(.02):
                if not process_ready.is_set():
                    continue
                process = state["process"]
                if process.poll() is not None:
                    return
                try:
                    parent = psutil.Process(process.pid)
                    rss = sum(item.memory_info().rss for item in [parent, *parent.children(recursive=True)] if item.is_running()) / 1024**2
                    state["peak"] = max(state["peak"], rss)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                if cancel_event is not None and cancel_event.is_set():
                    state.update(status="cancelled", reason="cancellation requested")
                elif time.monotonic() - started >= resources.budget_seconds:
                    state.update(status="timed-out", reason="attempt wall-clock budget exhausted")
                elif state["peak"] > resources.memory_mb:
                    state.update(status="failed", reason="aggregate process-tree memory limit exceeded")
                else:
                    continue
                broker.terminate_process_tree(process, grace_timeout=.5)
                return

        watcher = Thread(target=monitor, name="topos-base-budget", daemon=True)
        watcher.start()
        launcher = [sys.executable, str(Path(__file__).resolve()), "--native-exec",
                    str(resources.memory_mb), str(output_limit_mb), str(stdout), str(stderr), *command]
        try:
            result = broker.execute(launcher, cwd=folder, timeout_seconds=resources.budget_seconds)
            status = state["status"] or ("timed-out" if result.returncode == -124 else
                                         "completed" if result.success and result.returncode == 0 else "failed")
            reason = state["reason"] or (None if status == "completed" else f"BASE broker exit code {result.returncode}")
            return ProcessResult(command, status, result.returncode, time.monotonic() - started,
                                 state["peak"], str(stdout), str(stderr), reason)
        finally:
            done.set()
            watcher.join(timeout=5)
            broker.cleanup()
            atexit.unregister(broker.cleanup)


def _native_exec() -> None:
    import resource

    memory, limit = int(sys.argv[2]) * 1024**2, int(sys.argv[3]) * 1024**2
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    for descriptor, path in ((1, sys.argv[4]), (2, sys.argv[5])):
        handle = os.open(path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
        os.dup2(handle, descriptor)
        os.close(handle)
    with open(os.devnull, "rb") as handle:
        os.dup2(handle.fileno(), 0)
    os.execvpe(sys.argv[6], sys.argv[6:], os.environ)


if __name__ == "__main__":
    if len(sys.argv) < 7 or sys.argv[1] != "--native-exec":
        raise SystemExit("Private TOPOS native launcher: invalid arguments")
    _native_exec()
