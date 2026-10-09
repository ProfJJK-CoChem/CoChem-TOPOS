"""Real BASE broker/registry integration; generic commands are infrastructure tests.

The final xTB test is scientific execution evidence. Python subprocess fixtures
exercise containment and byte preservation and do not simulate a QM engine.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from threading import Event, Timer

import pytest

from topos.base_integration import (
    BaseIntegrationError,
    BaseRuntime,
    _orca_deck_allocation,
    inspect_ecosystem,
)
from topos.models import ResourceLimits


@pytest.fixture
def base_source(monkeypatch):
    root = Path(os.environ.get("COCHEM_BASE_ROOT", Path(__file__).resolve().parents[3] / "CoChem-BASE"))
    if not (root / "src/cochem_base/core_engine/execution_authority.py").is_file():
        if os.environ.get("TOPOS_REQUIRE_BASE") == "1":
            pytest.fail("Mandatory BASE acceptance requires the actual CoChem-BASE source installation")
        pytest.skip("Requires the mandatory CoChem-BASE installation with execution_authority")
    monkeypatch.setenv("COCHEM_BASE_ROOT", str(root))
    monkeypatch.syspath_prepend(str(root / "src"))
    return root


@pytest.fixture
def runtime(base_source, tmp_path):
    from cochem_base.cochem_core_registry_schema import CoChemSystemConfig
    from cochem_base.core.cochem_core_registry_manager import save_system_config

    binary = str(Path(sys.executable).absolute())
    config = CoChemSystemConfig.model_validate({
        "hardware": {"ram_gb": 4, "cpu_physical_cores": 1,
                     "allocatable_compute_cores": 1, "maxcore_mb": 2048},
        "engines": {"infrastructure-python": {
            "status": "found", "path": binary,
            "hash": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        }},
    })
    path = tmp_path / "registry.json"
    save_system_config(config, path)
    return BaseRuntime(path, require_torq=False)


def test_missing_torq_is_not_replaced_by_base_bundled_namespace(base_source, monkeypatch):
    monkeypatch.delenv("COCHEM_TORQ_ROOT", raising=False)
    import importlib.metadata

    original = importlib.metadata.distribution

    def distributions(name):
        if name.lower() == "cochem-torq":
            raise importlib.metadata.PackageNotFoundError(name)
        return original(name)

    monkeypatch.setattr(importlib.metadata, "distribution", distributions)
    status = inspect_ecosystem()
    assert not status.available
    assert not status.components["CoChem-TORQ"]["available"]


def test_explicit_torq_source_is_discovered_without_bootstrap(base_source, tmp_path, monkeypatch):
    root = tmp_path / "torq"
    (root / "src/cochem_torq").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname="CoChem-TORQ"\nversion="0.1.0"\n')
    (root / "src/cochem_torq/__init__.py").write_text('raise RuntimeError("bootstrap must not execute")\n')
    monkeypatch.setenv("COCHEM_TORQ_ROOT", str(root))
    assert inspect_ecosystem().available


def test_registry_checksum_and_executable_hash_enforced(runtime):
    assert runtime.resolve_executable("infrastructure-python") == str(Path(sys.executable).absolute())
    payload = json.loads(runtime.registry_path.read_text())
    payload["hardware"]["ram_gb"] = 1000
    runtime.registry_path.write_text(json.dumps(payload))
    with pytest.raises(BaseIntegrationError, match="checksum"):
        runtime.resolve_executable("infrastructure-python")


def test_no_unregistered_executable_fallback(runtime):
    with pytest.raises(BaseIntegrationError, match="not available"):
        runtime.resolve_executable("orca")


def test_native_bytes_and_sidecars_and_cwd_are_preserved(runtime, tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "must-not-reach-calculation")
    folder = tmp_path / "attempt"
    folder.mkdir()
    (folder / "input.dat").write_bytes(b"native-input\n")
    command = [str(Path(sys.executable).absolute()), "-c",
               "import os,pathlib; assert 'GH_TOKEN' not in os.environ; "
               "assert os.environ['OMP_NUM_THREADS']=='1'; "
               "pathlib.Path('sidecar.dat').write_bytes(pathlib.Path('input.dat').read_bytes()); "
               "os.write(1,b'\\xffnative\\x00output\\n'); os.write(2,b'warning\\n')"]
    result = runtime.run_process(command, folder, ResourceLimits(memory_mb=256, budget_seconds=10))
    assert result.status == "completed", result
    assert Path(result.stdout_path).read_bytes() == b"\xffnative\x00output\n"
    assert Path(result.stderr_path).read_bytes() == b"warning\n"
    assert (folder / "sidecar.dat").read_bytes() == b"native-input\n"
    assert result.command == command
    with pytest.raises(FileExistsError):
        runtime.run_process(command, folder, ResourceLimits())


def test_native_logs_exceeding_base_ring_buffer_are_not_truncated(runtime, tmp_path):
    result = runtime.run_process(
        [str(Path(sys.executable).absolute()), "-c", "import os; os.write(1,b'a'*(11*1024*1024))"],
        tmp_path / "large", ResourceLimits(memory_mb=256, budget_seconds=10), output_limit_mb=16,
    )
    assert result.status == "completed"
    assert Path(result.stdout_path).stat().st_size == 11 * 1024 * 1024


def test_budget_and_precancel(runtime, tmp_path):
    command = [str(Path(sys.executable).absolute()), "-c", "import time; print('started',flush=True); time.sleep(10)"]
    result = runtime.run_process(command, tmp_path / "timeout", ResourceLimits(budget_seconds=.2, memory_mb=256))
    assert result.status == "timed-out"
    assert b"started" in Path(result.stdout_path).read_bytes()
    cancelled = Event()
    cancelled.set()
    result = runtime.run_process(command, tmp_path / "cancel", ResourceLimits(), cancel_event=cancelled)
    assert result.status == "cancelled"
    assert result.returncode is None
    assert Path(result.stdout_path).read_bytes() == b""


def test_cancellation_reaps_owned_process_and_keeps_logs(runtime, tmp_path):
    import psutil

    folder = tmp_path / "cancel-running"
    event = Event()
    timer = Timer(.35, event.set)
    timer.start()
    try:
        result = runtime.run_process(
            [str(Path(sys.executable).absolute()), "-c",
             "import os,time,pathlib; pathlib.Path('pid').write_text(str(os.getpid())); "
             "print('started',flush=True); time.sleep(20)"], folder,
            ResourceLimits(memory_mb=256, budget_seconds=5), cancel_event=event,
        )
    finally:
        timer.cancel()
    assert result.status == "cancelled"
    assert b"started" in Path(result.stdout_path).read_bytes()
    assert not psutil.pid_exists(int((folder / "pid").read_text()))


def test_failure_is_not_retried_or_relabelled_success(runtime, tmp_path):
    result = runtime.run_process(
        [str(Path(sys.executable).absolute()), "-c",
         "import pathlib,sys; pathlib.Path('count').open('a').write('attempt\\n'); sys.exit(7)"],
        tmp_path / "failure", ResourceLimits(memory_mb=256, budget_seconds=5),
    )
    assert result.status == "failed" and result.returncode == 7
    assert (tmp_path / "failure/count").read_text() == "attempt\n"


def test_audited_resources_and_native_identity_are_mandatory(runtime, tmp_path):
    with pytest.raises(BaseIntegrationError, match="cores"):
        runtime.validate_resources(ResourceLimits(threads=2))
    with pytest.raises(BaseIntegrationError, match="RAM"):
        runtime.validate_resources(ResourceLimits(memory_mb=10000))
    with pytest.raises(BaseIntegrationError, match="audited BASE engine"):
        runtime.run_process(["python", "--version"], tmp_path / "wrong", ResourceLimits())


def test_total_cpu_allocation_is_distinct_from_per_process_threads(runtime, tmp_path):
    """A real Python launcher probes resources; it does not impersonate ORCA."""
    from cochem_base.cochem_core_registry_schema import CoChemSystemConfig
    from cochem_base.core.cochem_core_registry_manager import save_system_config

    cpus = sorted(os.sched_getaffinity(0))[:2]
    if len(cpus) != 2:
        pytest.fail("BASE acceptance requires two available CPU identifiers for allocation separation")
    config = CoChemSystemConfig.model_validate({
        "hardware": {"ram_gb": 4, "cpu_physical_cores": 2, "allocatable_compute_cores": 2,
                     "maxcore_mb": 2048, "audited_cpu_ids": cpus},
        "engines": runtime.registry.model_dump(mode="json")["engines"],
    })
    save_system_config(config, runtime.registry_path)
    runtime = BaseRuntime(runtime.registry_path, require_torq=False)
    result = runtime.run_process(
        [str(Path(sys.executable).absolute()), "-c",
         "import os,json; print(json.dumps({'cpu_ids':sorted(os.sched_getaffinity(0)),"
         "'omp':os.environ['OMP_NUM_THREADS'],'blas':os.environ['OPENBLAS_NUM_THREADS']}))"],
        tmp_path / "two-core-allocation", ResourceLimits(threads=2, memory_mb=256, budget_seconds=10),
        threads_per_process=1,
    )
    assert result.status == "completed"
    assert json.loads(Path(result.stdout_path).read_text()) == {"cpu_ids": cpus, "omp": "1", "blas": "1"}


def test_orca_allocation_uses_the_actual_serial_probe_maxcore(tmp_path):
    deck = tmp_path / "probe.inp"
    deck.write_text("! HF STO-3G SP\n%pal nprocs 1 end\n%maxcore 64\n* xyz 0 1\nHe 0 0 0\n*\n")
    assert _orca_deck_allocation(["/registered/orca", deck.name], tmp_path,
                                 ResourceLimits(threads=1, memory_mb=2048)) == 64


@pytest.mark.parametrize("deck,reason", [
    ("%pal nprocs 2 end\n%maxcore 64\n", "nprocs"),
    ("%pal nprocs 1 end\n%maxcore 4096\n", "memory"),
    ("%pal nprocs 1 end\n%maxcore 64\n%maxcore 65\n", "exactly one"),
    ("%pal nprocs 1 end\n%maxcore -1\n", "exactly one"),
    ("%pal nprocs 1 end\n# %maxcore 64\n", "exactly one"),
])
def test_orca_deck_must_match_audited_resource_request(tmp_path, deck, reason):
    (tmp_path / "input.inp").write_text(deck)
    with pytest.raises(BaseIntegrationError, match=reason):
        _orca_deck_allocation(["/registered/orca", "input.inp"], tmp_path, ResourceLimits())


def test_orca_deck_cannot_escape_attempt(tmp_path):
    (tmp_path / "outside.inp").write_text("%pal nprocs 1 end\n%maxcore 64\n")
    with pytest.raises(BaseIntegrationError, match="confined"):
        _orca_deck_allocation(["/registered/orca", "../outside.inp"], tmp_path / "attempt", ResourceLimits())


@pytest.fixture
def utility_distribution(runtime, base_source, tmp_path, monkeypatch):
    """File-integrity fixture only: never executes or simulates ORCA output."""
    from cochem_base.cochem_core_registry_schema import CoChemSystemConfig
    from cochem_base.core.cochem_core_registry_manager import save_system_config

    install = tmp_path / "distribution"
    install.mkdir()
    for name in ("orca", "orca_exportbasis"):
        (install / name).write_bytes(b"inert distribution identity fixture " + name.encode())
        (install / name).chmod(0o700)
    manifest_path = base_source / "scripts/orca-distribution.json"
    manifest = json.loads(manifest_path.read_text())
    provenance = {"schema_version": 1, "distribution": manifest,
                  "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                  "archive_sha256": manifest["sha256"], "orca_version": manifest["orca_version"],
                  "executable": str(install / "orca"),
                  "files": {path.name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
                            for path in install.iterdir()}}
    provenance_path = install / "cochem-orca-provenance.json"
    provenance_path.write_text(json.dumps(provenance))
    monkeypatch.setenv("COCHEM_ORCA_PROVENANCE", str(provenance_path))
    config = CoChemSystemConfig.model_validate({
        "hardware": runtime.registry.model_dump(mode="json")["hardware"],
        "engines": {"orca": {"status": "found", "path": str(install / "orca"),
                              "hash": hashlib.sha256((install / "orca").read_bytes()).hexdigest()}},
    })
    save_system_config(config, runtime.registry_path)
    return BaseRuntime(runtime.registry_path, require_torq=False), install, provenance_path


def test_export_utility_authority_binds_parent_helper_and_pinned_distribution(utility_distribution):
    runtime, install, _ = utility_distribution
    helper, _, receipt = runtime._orca_distribution_utility()
    assert helper == install / "orca_exportbasis"
    assert receipt["authority_kind"] == "verified-ORCA-distribution-utility"
    assert receipt["exporter_sha256"] == hashlib.sha256(helper.read_bytes()).hexdigest()
    helper.write_bytes(b"changed utility")
    with pytest.raises(BaseIntegrationError, match="inventory"):
        runtime._orca_distribution_utility()


@pytest.mark.parametrize("field", ["archive_sha256", "manifest_sha256", "orca_version", "executable"])
def test_export_utility_rejects_forged_distribution_identity(utility_distribution, field):
    runtime, _, provenance_path = utility_distribution
    payload = json.loads(provenance_path.read_text())
    payload[field] = "invalid"
    provenance_path.write_text(json.dumps(payload))
    with pytest.raises(BaseIntegrationError, match="pinned manifest"):
        runtime._orca_distribution_utility()


@pytest.mark.parametrize("arguments", [
    ["-b", "def2-TZVPP", "-a", "He", "-f", "GAMESS-US", "-o", "../escape.bas"],
    ["-b", "def2-TZVPP", "-a", "H,O", "-f", "GAMESS-US", "-o", "basis.bas"],
    ["-b", "def2-TZVPP", "-a", "U", "-f", "GAMESS-US", "-o", "basis.bas"],
    ["-b", "user.bas", "-a", "He", "-f", "GAMESS-US", "-o", "basis.bas"],
    ["-b", "def2-TZVPP", "-a", "He", "-f", "GAMESS-US", "-o", "basis.bas", "--arbitrary"],
])
def test_export_utility_rejects_noncanonical_arguments_before_execution(runtime, tmp_path, arguments):
    with pytest.raises(BaseIntegrationError):
        runtime.run_orca_utility(arguments, tmp_path / "export", ResourceLimits(memory_mb=256))
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("requested_mb,expected_mb,expected_maxcore", [(256, 256, 192), (4096, 2730, 2047)])
def test_serial_basis_utility_cannot_inherit_excessive_mpi_campaign_memory(
    utility_distribution, tmp_path, monkeypatch, requested_mb, expected_mb, expected_maxcore,
):
    """Real BASE authority, stopped before execution; no ORCA output is produced."""
    runtime, _, _ = utility_distribution

    class InspectedBeforeLaunch(RuntimeError):
        pass

    def inspect(command, folder, effective, authority, **kwargs):
        assert effective.memory_mb == expected_mb
        assert effective.threads == authority.cores == 1
        assert authority.maxcore_mb == expected_maxcore <= runtime.registry.hardware.maxcore_mb
        assert effective.budget_seconds == 123
        assert kwargs["threads_per_process"] == 1
        raise InspectedBeforeLaunch

    monkeypatch.setattr(runtime, "_execute_authorized", inspect)
    requested = ResourceLimits(threads=1, memory_mb=requested_mb, budget_seconds=123)
    with pytest.raises(InspectedBeforeLaunch):
        runtime.export_orca_basis("cc-pVDZ-F12", ["H", "O"], tmp_path / "utility", requested)
    assert requested.memory_mb == requested_mb
    assert not (tmp_path / "utility").exists()


@pytest.mark.parametrize("engine", [None, "orca", "xtb", "crest", "infrastructure-python"])
def test_gpu_allocation_never_bypasses_the_native_cpu_boundary(runtime, engine):
    with pytest.raises(BaseIntegrationError, match="audited ML"):
        runtime.validate_resources(ResourceLimits(device="gpu"), engine=engine, gpu_index=0, gpu_memory_mb=128)


def test_ml_gpu_requires_measured_authority_and_cpu_has_no_implicit_device(runtime):
    with pytest.raises(BaseIntegrationError, match="measured BASE GPU"):
        runtime.validate_resources(ResourceLimits(device="gpu"), engine="mace", gpu_index=0, gpu_memory_mb=128)
    with pytest.raises(BaseIntegrationError, match="implicit GPU"):
        runtime.validate_resources(ResourceLimits(), engine="mace", gpu_index=0)


def test_python_ml_worker_cannot_claim_an_unaudited_silo(runtime, tmp_path):
    # Hash-bound files exercise an authority rejection; no model is executed.
    request = tmp_path / "request.json"
    request.write_text('{}\n')
    model = tmp_path / "model.member"
    model.write_bytes(b'inert identity fixture, never an ML model')
    with pytest.raises(BaseIntegrationError, match="Stage 0 micro-silo"):
        runtime.run_ml_process([str(Path(sys.executable).absolute()), "-m", "topos.ml_worker", "--request", str(request)],
                               tmp_path, ResourceLimits(memory_mb=256), engine="mace",
                               request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(), worker_sha256="a" * 64,
                               model_files={str(model): hashlib.sha256(model.read_bytes()).hexdigest()})
    assert not (tmp_path / "ml.stdout").exists()


def test_ml_python_authority_does_not_allow_arbitrary_code(runtime, tmp_path):
    with pytest.raises(BaseIntegrationError, match="explicit TOPOS module"):
        runtime.run_ml_process([str(Path(sys.executable).absolute()), "-c", "raise RuntimeError('must not execute')"],
                               tmp_path, ResourceLimits(memory_mb=256), engine="mace", request_sha256="a" * 64,
                               worker_sha256="b" * 64, model_files={})


@pytest.mark.integration
def test_real_xtb_water_through_base_registry_and_broker(base_source, tmp_path):
    import re
    import shutil

    from cochem_base.cochem_core_registry_schema import CoChemSystemConfig
    from cochem_base.core.cochem_core_registry_manager import save_system_config

    candidate = os.environ.get("TOPOS_XTB_EXECUTABLE") or shutil.which("xtb")
    if not candidate:
        if os.environ.get("TOPOS_REQUIRE_BASE") == "1":
            pytest.fail("Mandatory BASE acceptance requires real xTB")
        pytest.skip("Real xTB is required for BASE scientific acceptance")
    binary = str(Path(candidate).resolve())
    config = CoChemSystemConfig.model_validate({
        "hardware": {"ram_gb": 4, "cpu_physical_cores": 1, "allocatable_compute_cores": 1,
                     "maxcore_mb": 2048},
        "engines": {"xtb": {"status": "found", "path": binary,
                             "hash": hashlib.sha256(Path(binary).read_bytes()).hexdigest()}},
    })
    path = tmp_path / "registry.json"
    save_system_config(config, path)
    runtime = BaseRuntime(path, require_torq=False)
    folder = tmp_path / "water"
    folder.mkdir()
    (folder / "input.xyz").write_text("3\nwater\nO 0 0 0\nH 0 -.757 .587\nH 0 .757 .587\n")
    result = runtime.run_process([binary, "input.xyz", "--gfn", "2", "--sp", "--chrg", "0", "--uhf", "0"],
                                 folder, ResourceLimits(memory_mb=1024, budget_seconds=30))
    output = Path(result.stdout_path).read_text()
    assert result.status == "completed", Path(result.stderr_path).read_text()
    energies = re.findall(r"TOTAL ENERGY\s+([-+0-9.]+)", output)
    assert energies and -6 < float(energies[-1]) < -4
    assert "xtb version" in output.lower()


@pytest.mark.integration
def test_actual_stage0_and_mandatory_ecosystem_workflow(tmp_path):
    """Use the real eleven-phase registry, not an infrastructure registry fixture."""
    from topos.config import SystemConfig
    from topos.models import Molecule, RunRequest
    from topos.storage import RunStore
    from topos.workflow import Workflow

    path = os.environ.get("COCHEM_CONFIG")
    if not path or not Path(path).is_file():
        if os.environ.get("TOPOS_REQUIRE_BASE") == "1":
            pytest.fail("Mandatory BASE acceptance requires a real completed Stage 0 registry")
        pytest.skip("Real BASE Stage 0 registry is required")
    runtime = BaseRuntime(path)
    assert runtime.ecosystem.available
    assert len(runtime.registry.stage0.phases) == 11
    assert Path(runtime.resolve_executable("xtb")).is_file()
    assert Path(runtime.resolve_executable("crest")).is_file()
    config = SystemConfig(execution_backend="base", base_registry_path=Path(path))
    request = RunRequest(molecule=Molecule(symbols=["O", "H", "H"],
                                           coordinates=[[0, 0, 0], [0, -.757, .587], [0, .757, .587]]),
                         purpose="energy", budget_seconds=30, memory_mb=1024)
    result = Workflow(tmp_path / "mandatory", config=config).run(request)
    assert result.status == "completed", result.metadata
    assert result.attempts and result.attempts[0].engine == "xtb"
    assert result.candidates and -6 < result.candidates[0].energy_hartree < -4
    assert RunStore(result.metadata["run_dir"]).load()["status"] == "completed"


def test_training_cannot_silently_fall_back_to_cpu(runtime, tmp_path):
    from topos.models import ResourceLimits

    with pytest.raises(BaseIntegrationError, match="fine-tuning requires.*CUDA"):
        runtime.run_mace_training_process(
            ["unused-python", "-m", "mace.cli.run_train"], tmp_path,
            ResourceLimits(device="cpu", threads=1, memory_mb=512, budget_seconds=1),
            package_version="0.3.16", input_files={}, gpu_index=0, gpu_memory_mb=128,
        )


def test_export_manifest_is_found_for_actual_base_namespace_package(utility_distribution, monkeypatch):
    runtime, install, _ = utility_distribution
    monkeypatch.delenv("COCHEM_BASE_ROOT", raising=False)
    assert runtime._orca_distribution_utility()[0] == install / "orca_exportbasis"


def test_orca_environment_adds_reauthorized_mpi_outside_controller_path(runtime, tmp_path, monkeypatch):
    """Real Python/true probe validates launch environment, not ORCA chemistry."""
    import shutil

    from cochem_base.cochem_core_registry_schema import CoChemSystemConfig
    from cochem_base.core.cochem_core_registry_manager import save_system_config

    mpi = tmp_path / "isolated-mpi" / "mpirun"
    mpi.parent.mkdir()
    shutil.copyfile("/usr/bin/true", mpi)
    mpi.chmod(0o700)
    config = runtime.registry.model_dump(mode="json")
    config["hardware"].update(cpu_physical_cores=2, allocatable_compute_cores=2)
    config["engines"]["mpirun"] = {"status": "found", "path": str(mpi),
                                     "hash": hashlib.sha256(mpi.read_bytes()).hexdigest()}
    save_system_config(CoChemSystemConfig.model_validate(config), runtime.registry_path)
    runtime = BaseRuntime(runtime.registry_path, require_torq=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("COCHEM_CPU_ALLOCATION_POLICY", "github_hosted_vcpus")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    monkeypatch.setenv("OMPI_unrelated_token", "must-not-leak")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/unrelated-engine/lib")
    monkeypatch.setenv("COCHEM_ORCA_LD_LIBRARY_PATH", "/reviewed-orca/lib")
    authority = runtime._authorize("infrastructure-python", registry_path=runtime.registry_path,
                                   cores=2, maxcore_mb=64)
    command = [str(Path(sys.executable).absolute()), "-c",
               "import shutil,os; print(shutil.which('mpirun')); print(os.environ['OMP_NUM_THREADS']); "
               "print(os.environ['OMPI_MCA_rmaps_base_mapping_policy']); "
               "assert 'LD_LIBRARY_PATH' in os.environ and os.environ['LD_LIBRARY_PATH']=='/reviewed-orca/lib'; "
               "assert 'OMPI_unrelated_token' not in os.environ"]
    resources = ResourceLimits(threads=2, memory_mb=256, budget_seconds=10)
    result = runtime._execute_authorized(command, tmp_path / "mpi-path-probe", resources,
                                         authority, engine="orca")
    assert result.status == "completed", result
    assert Path(result.stdout_path).read_text().splitlines() == [str(mpi), "1", "hwthread:NOOVERSUBSCRIBE"]
    mpi.write_bytes(b"altered infrastructure executable")
    with pytest.raises(BaseIntegrationError, match="MPI launcher"):
        runtime._execute_authorized(command, tmp_path / "changed-mpi", resources,
                                    authority, engine="orca")



@pytest.mark.parametrize("engine", ["mace", "aimnet2"])
def test_isolated_python_broker_excludes_host_engine_library_paths(runtime, tmp_path, monkeypatch, engine):
    """Actual Python broker child checks isolation, without claiming ML inference."""
    host_libraries = "/unrelated-orca/lib:/unrelated-openmpi/lib"
    monkeypatch.setenv("LD_LIBRARY_PATH", host_libraries)
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/unrelated-native/lib")
    authority = runtime._authorize("infrastructure-python", registry_path=runtime.registry_path,
                                   cores=1, maxcore_mb=64)
    code = """import json,os
assert 'LD_LIBRARY_PATH' not in os.environ and 'DYLD_LIBRARY_PATH' not in os.environ
assert os.environ['PYTHONSAFEPATH'] == os.environ['PYTHONNOUSERSITE'] == '1'
assert os.environ['OMP_NUM_THREADS'] == os.environ['OPENBLAS_NUM_THREADS'] == '1'
print(json.dumps({'isolated': True}))
"""
    result = runtime._execute_authorized([authority.executable, "-I", "-c", code],
        tmp_path / engine, ResourceLimits(memory_mb=256, budget_seconds=10), authority,
        engine=engine, isolated_python=True,
        environment={"LD_LIBRARY_PATH": "/another-engine/lib", "DYLD_LIBRARY_PATH": "/another-native/lib"})
    assert result.status == "completed", result
    assert json.loads(Path(result.stdout_path).read_text()) == {"isolated": True}
    assert os.environ["LD_LIBRARY_PATH"] == host_libraries
    assert os.environ["DYLD_LIBRARY_PATH"] == "/unrelated-native/lib"


def test_training_engine_guard_uses_actual_base_dictionary_schema(runtime, tmp_path, monkeypatch):
    # Resource authorization is an infrastructure double here; this test must
    # reject a missing package record before any worker or science can launch.
    monkeypatch.setattr(runtime, "validate_resources", lambda *args, **kwargs: None)
    with pytest.raises(BaseIntegrationError, match="actually audited"):
        runtime.run_mace_training_process([], tmp_path, ResourceLimits(device="gpu"),
                                         package_version="0.3.16", input_files={},
                                         gpu_index=0, gpu_memory_mb=128)
    assert not (tmp_path / "training-worker-request.json").exists()


def test_actual_legacy_base_authority_cannot_launch_cfour(runtime, tmp_path):
    """An actual old-BASE infrastructure authorization cannot certify CFOUR."""
    from topos.base_integration import _cfour_authorization_identity

    authority = runtime._authorize('infrastructure-python', registry_path=runtime.registry_path, cores=1, maxcore_mb=1)
    if getattr(authority, 'runtime_seal_sha256', None) is not None:
        pytest.fail('Infrastructure Python must not carry a CFOUR runtime seal')
    record = {'path': authority.executable, 'hash': authority.binary_sha256, 'runtime_seal_sha256': 'a' * 64}
    with pytest.raises(BaseIntegrationError, match='sealed-runtime authorization'):
        _cfour_authorization_identity(authority, record)


@pytest.mark.parametrize('change', ['missing-seal', 'seal', 'executable', 'binary'])
def test_cfour_authorization_contract_rejects_changed_bookkeeping(change):
    """Typed authority bookkeeping only; no executable or native output exists."""
    from types import SimpleNamespace

    from topos.base_integration import _cfour_authorization_identity

    record = {'path': '/bookkeeping/not-an-engine', 'hash': 'b' * 64, 'runtime_seal_sha256': 'a' * 64}
    authority = SimpleNamespace(executable=record['path'], binary_sha256=record['hash'], runtime_seal_sha256='a' * 64)
    if change == 'missing-seal':
        del authority.runtime_seal_sha256
    elif change == 'seal':
        authority.runtime_seal_sha256 = 'c' * 64
    elif change == 'executable':
        authority.executable += '-different'
    else:
        authority.binary_sha256 = 'c' * 64
    with pytest.raises(BaseIntegrationError, match='sealed-runtime authorization'):
        _cfour_authorization_identity(authority, record)


@pytest.mark.parametrize('post_change', ['seal', 'input', 'none'])
def test_cfour_broker_failed_infrastructure_transport_keeps_postrun_checks(runtime, tmp_path, monkeypatch, post_change):
    """An exit-4 shell is transport evidence only, under explicit bookkeeping authority.

    This does not simulate successful CFOUR output or certify a runtime seal.
    """
    from types import SimpleNamespace

    from cochem_base.core_engine import engine_environment

    script = tmp_path / 'failed-infrastructure'
    script.write_text('#!/bin/sh\nprintf "%s %s %s\\n" "$OMP_NUM_THREADS" "$OPENBLAS_NUM_THREADS" "$BLIS_NUM_THREADS"\n'
                      + ('printf "changed\\n" >> ZMAT\n' if post_change == 'input' else '') + 'exit 4\n')
    script.chmod(0o700)
    authority = SimpleNamespace(executable=str(script), binary_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
                                runtime_seal_sha256='a' * 64, cores=2, maxcore_mb=64, cpu_affinity=())
    marker = b'Bookkeeping input; never a scientific calculation\n'
    dependencies = {name: {'path': str(tmp_path / 'controlled' / name),
                          'sha256': hashlib.sha256(marker).hexdigest(), 'bytes': len(marker)}
                    for name in ('GENBAS', 'ECPDATA')}
    record = {'path': authority.executable, 'hash': authority.binary_sha256, 'runtime_seal_sha256': 'a' * 64,
              'runtime_metadata': {'basis': dependencies}}
    monkeypatch.setattr(runtime, 'registry', SimpleNamespace(model_dump=lambda **kwargs: {'engines': {'cfour': record}}))
    calls = []
    original_environment = engine_environment.engine_runtime_environment

    def recorded_environment(engine, environment, **kwargs):
        calls.append(engine)
        return original_environment(engine, environment, **kwargs)

    monkeypatch.setattr(engine_environment, 'engine_runtime_environment', recorded_environment)

    def post_authority(engine, **kwargs):
        assert engine == 'cfour' and kwargs['command'] == [str(script)]
        return SimpleNamespace(**{**vars(authority), 'runtime_seal_sha256': 'c' * 64 if post_change == 'seal' else 'a' * 64})

    monkeypatch.setattr(runtime, '_authorize', post_authority)
    folder = tmp_path / 'failed-transport'
    folder.mkdir()
    for name in ('ZMAT', 'GENBAS'):
        (folder / name).write_text('Bookkeeping input; never a scientific calculation\n')
    result = runtime._execute_authorized([str(script)], folder, ResourceLimits(threads=2, memory_mb=256, budget_seconds=10),
                                         authority, engine='cfour')
    assert result.status == 'failed' and result.returncode == 4
    assert calls == ['cfour']
    assert Path(result.stdout_path).read_text() == '2 1 1\n'
    receipt = json.loads((folder / 'engine-cfour-runtime.json').read_text())
    assert receipt['status'] == ('verified' if post_change == 'none' else 'failed')
    assert receipt['command'] == [str(script)] and receipt['workdir'] == str(folder)
    assert receipt['controlled_runtime_dependencies'] == {name: {
        'path': entry['path'], 'sha256': entry['sha256'], 'size_bytes': entry['bytes']}
        for name, entry in dependencies.items()}
    assert receipt['stdout_sha256'] == hashlib.sha256(Path(result.stdout_path).read_bytes()).hexdigest()
    if post_change == 'seal':
        assert 'sealed-runtime authorization' in result.reason
    elif post_change == 'input':
        assert 'native input changed' in result.reason
    else:
        assert 'exit code 4' in result.reason


def test_cfour_cannot_override_environment_after_base_authorization(runtime, tmp_path):
    authority = runtime._authorize('infrastructure-python', registry_path=runtime.registry_path, cores=1, maxcore_mb=1)
    with pytest.raises(BaseIntegrationError, match='environment overrides'):
        runtime._execute_authorized([authority.executable], tmp_path / 'forbidden-environment',
                                     ResourceLimits(), authority, engine='cfour',
                                     environment={'COCHEM_CFOUR_LD_LIBRARY_PATH': '/unaudited/library'})
    assert (tmp_path / 'forbidden-environment/engine.stdout').read_bytes() == b''


def test_actual_native_cpu_memory_failure_preserves_address_space_limit(runtime, tmp_path, monkeypatch):
    """A real allocation fails under the existing CPU AS ceiling."""
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    command = [str(Path(sys.executable).absolute()), "-I", "-c",
               "import resource; print(resource.getrlimit(resource.RLIMIT_AS)[0],flush=True); "
               "value=bytearray(256*1024*1024)"]
    result = runtime.run_process(command, tmp_path / "cpu-memory", ResourceLimits(memory_mb=128, budget_seconds=15))
    assert result.status == "failed" and result.returncode != 0
    assert str(128 * 1024**2).encode() in Path(result.stdout_path).read_bytes()
    assert b"MemoryError" in Path(result.stderr_path).read_bytes()


def test_gpu_launcher_rejects_an_allocation_without_actual_engine_authority(runtime, tmp_path):
    authorization = runtime._authorize("infrastructure-python", registry_path=runtime.registry_path, cores=1, maxcore_mb=64)
    with pytest.raises(BaseIntegrationError, match="audited GPU allocation"):
        runtime._execute_authorized([authorization.executable, "-c", "print(42)"], tmp_path / "unaudited-gpu",
                                    ResourceLimits(memory_mb=128, device="gpu"), authorization,
                                    engine="mace", cuda_visible_devices="0", gpu_memory_mb=64)
    assert not (tmp_path / "unaudited-gpu").exists()


@pytest.mark.integration
def test_actual_audited_cuda_tensor_preserves_rss_and_gpu_allocator_limits(tmp_path):
    """Real CUDA infrastructure check; no model or scientific acceptance fixture."""
    interpreter = os.environ.get("TOPOS_MACE_PYTHON")
    registry = os.environ.get("COCHEM_CONFIG")
    if not interpreter or not registry:
        pytest.skip("Explicit CUDA silo and actual GPU Stage 0 authority required")
    runtime = BaseRuntime(registry, require_torq=False)
    if not (runtime.registry.engines.get("mace") and runtime.registry.engines["mace"].gpu_support):
        pytest.skip("Current audited MACE silo has no GPU support")
    resources = ResourceLimits(threads=2, memory_mb=4096, budget_seconds=60, device="gpu")
    authorization = runtime._authorize("mace", registry_path=runtime.registry_path,
                                       executable=interpreter, cores=2, maxcore_mb=1536)
    code = """import json,os,pathlib,torch
torch.set_num_threads(2)
torch.use_deterministic_algorithms(True)
assert torch.cuda.is_available() and torch.cuda.device_count()==1
torch.cuda.set_per_process_memory_fraction(8192/(torch.cuda.get_device_properties(0).total_memory/1024**2),device=0)
x=torch.tensor([[1.,2.],[3.,4.]],device='cuda:0',dtype=torch.float64,requires_grad=True)
y=(x@x).sum();y.backward();torch.cuda.synchronize()
status=pathlib.Path('/proc/self/status').read_text()
print(json.dumps({'device':str(x.device),'gradient':x.grad.cpu().tolist(),
 'result':y.item(),'workspace':os.environ.get('CUBLAS_WORKSPACE_CONFIG'),
 'vms_kib':int(next(line.split()[1] for line in status.splitlines() if line.startswith('VmSize:')))}))
"""
    result = runtime._execute_authorized([interpreter, "-I", "-c", code], tmp_path / "cuda-memory",
                                        resources, authorization, engine="mace",
                                        cuda_visible_devices="0", gpu_memory_mb=8192)
    assert result.status == "completed", result
    observed = json.loads(Path(result.stdout_path).read_text())
    assert observed["device"] == "cuda:0" and observed["gradient"] == [[7, 11], [9, 13]]
    assert observed["result"] == 54 and observed["workspace"] == ":4096:8"
    assert observed["vms_kib"] > resources.memory_mb * 1024
    assert result.peak_rss_mb <= resources.memory_mb


@pytest.mark.integration
def test_actual_gpu_mode_rss_ceiling_kills_and_reaps_large_cpu_allocation(tmp_path):
    """AS relaxation must retain actual process-tree resident-memory containment."""
    interpreter, registry = os.environ.get("TOPOS_MACE_PYTHON"), os.environ.get("COCHEM_CONFIG")
    if not interpreter or not registry:
        pytest.skip("Explicit CUDA silo and actual GPU Stage 0 authority required")
    runtime = BaseRuntime(registry, require_torq=False)
    if not (runtime.registry.engines.get("mace") and runtime.registry.engines["mace"].gpu_support):
        pytest.skip("Current audited MACE silo has no GPU support")
    resources = ResourceLimits(threads=1, memory_mb=128, budget_seconds=30, device="gpu")
    authorization = runtime._authorize("mace", registry_path=runtime.registry_path,
                                       executable=interpreter, cores=1, maxcore_mb=96)
    code = "import os,time; print(os.getpid(),flush=True); value=bytearray(256*1024*1024); time.sleep(10)"
    result = runtime._execute_authorized([interpreter, "-I", "-c", code], tmp_path / "gpu-mode-rss",
                                        resources, authorization, engine="mace",
                                        cuda_visible_devices="0", gpu_memory_mb=8192)
    assert result.status == "failed" and result.reason == "aggregate process-tree memory limit exceeded"
    assert result.peak_rss_mb > resources.memory_mb
    import psutil

    assert not psutil.pid_exists(int(Path(result.stdout_path).read_text().strip()))
