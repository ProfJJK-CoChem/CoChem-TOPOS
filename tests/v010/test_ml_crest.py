"""Pure compiler checks plus explicitly selected genuine CREST/MACE acceptance.

The optional live checks use the bounded development executor, not BASE proof.
No successful native engine is replaced by a test double.
"""
from __future__ import annotations

import os
import shutil
import tomllib
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from topos.engines import write_xyz
from topos.ml import ModelManifest
from topos.ml_crest import _receipt_evidence, crest_ml_command, crest_ml_input, run_crest_ml
from topos.ml_extopt import ExtOptAllocation, PersistentMLServer
from topos.models import Molecule, ResourceLimits
from topos.runtime import run_process
from topos.storage import file_digest, read_json


def water():
    return Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.9584, 0, 0], [-.24, .928, 0]])


def protocol_only_manifest():
    """Manifest metadata for validation tests; never passed to native inference."""
    return ModelManifest(backend="mace", family="protocol-only fixture", package_version="0.3.16",
        members=[{"path": "/nonexistent-protocol-only-checkpoint", "sha256": "0" * 64,
                  "training_run_id": "not-an-engine-result", "source": "protocol-only fixture"}],
        training_method="protocol-only", license_name="protocol-only", license_url="protocol-only",
        supported_elements=["H", "O"], supported_charges=[0], supported_multiplicities=[1],
        precision="float64", domain_reference="protocol-only fixture")


def test_native_generic_deck_preserves_state_and_initial_preoptimization(tmp_path):
    wrapper = tmp_path / "fixed-crest-client"
    deck = tomllib.loads(crest_ml_input(water(), wrapper, ResourceLimits(threads=2)))
    assert deck["input"] == "input.xyz" and deck["threads"] == 2
    assert "runtype" not in deck
    assert deck["calculation"]["level"] == [{"method": "generic", "binary": str(wrapper),
        "gradtype": "engrad", "gradfile": "genericinp.engrad", "chrg": 0, "uhf": 0}]
    ion = Molecule(symbols=["O", "H", "H"], coordinates=water().coordinates, charge=1, multiplicity=2)
    level = tomllib.loads(crest_ml_input(ion, wrapper, ResourceLimits()))["calculation"]["level"][0]
    assert level["chrg"] == 1 and level["uhf"] == 1


@pytest.mark.parametrize("path", ["relative-client", "/tmp/space client", "/tmp/client;pwd", "/tmp/client$(pwd)", "/tmp/client\n"])
def test_native_shell_interpolation_is_rejected(path):
    with pytest.raises(ValueError, match="shell-safe"):
        crest_ml_input(water(), path, ResourceLimits())


@pytest.mark.parametrize("profile", ["crest-imtdgc-v1", "crest-mquick-v1"])
def test_exact_native_command_has_no_potential_substitution(profile):
    command = crest_ml_command("/real/crest", water(), ResourceLimits(threads=2), profile=profile)
    assert command[:5] == ["/real/crest", "ml-crest.toml", "--newversion", "--v3", "-T"]
    assert command[-2:] == ["--ewin", "12"]
    assert ("--mquick" in command) == (profile == "crest-mquick-v1")
    assert not {"--legacy", "--gfn2", "--xnam", "--nopreopt", "--mdlen"}.intersection(command)


@pytest.mark.parametrize("window", [0, -1, True, float("nan"), float("inf")])
def test_invalid_native_window(window):
    with pytest.raises(ValueError, match="finite positive"):
        crest_ml_command("crest", water(), ResourceLimits(), energy_window_kcal_mol=window)


def test_no_base_authority_no_native_result(tmp_path):
    result = run_crest_ml(water(), protocol_only_manifest(), ResourceLimits(threads=2), tmp_path / "attempt",
        runtime=None, allocation=ExtOptAllocation(1, 512, 1, 512))
    assert result.status == "unavailable" and result.metadata["execution_kind"] == "not-executed"
    assert not result.ensemble and not result.artifacts and not result.command
    assert not (tmp_path / "attempt").exists()


@pytest.mark.parametrize("case", ["allocation", "isotopes", "profile", "requests", "receipts", "device"])
def test_unsupported_inputs_cannot_start_inference(tmp_path, case):
    molecule, resources = water(), ResourceLimits(threads=2)
    options = {"allocation": ExtOptAllocation(1, 512, 1, 512)}
    if case == "allocation":
        options["allocation"] = ExtOptAllocation(2, 512, 1, 512)
    elif case == "isotopes":
        molecule = molecule.model_copy(update={"isotopes": [18, None, None]})
    elif case == "profile":
        options["profile"] = "crest-entropy-v1"
    elif case == "requests":
        options["max_requests"] = 1_000_001
    elif case == "receipts":
        options["max_receipt_mb"] = 3
    else:
        resources = resources.model_copy(update={"device": "unspecified-accelerator"})
    result = run_crest_ml(molecule, protocol_only_manifest(), resources, tmp_path / "attempt", runtime=None, **options)
    assert result.status == "unsupported" and not result.ensemble and not result.artifacts
    assert not (tmp_path / "attempt").exists()


def test_cancel_before_authority_validation(tmp_path):
    cancel = Event()
    cancel.set()
    result = run_crest_ml(water(), protocol_only_manifest(), ResourceLimits(threads=2), tmp_path / "attempt",
        runtime=None, allocation=ExtOptAllocation(1, 512, 1, 512), cancel_event=cancel)
    assert result.status == "cancelled" and result.converged is None and not result.ensemble


class DevelopmentNativeMLRuntime:
    """Actual bounded native processes; explicitly provides no BASE attestation."""

    def __init__(self, crest, python):
        self.crest, self.python = crest, python

    def resolve_executable(self, engine):
        return self.crest if engine == "crest" else self.python

    def run_process(self, command, workdir, resources, **kwargs):
        return run_process(command, workdir, resources, **kwargs)

    def run_ml_process(self, command, workdir, resources, *, engine, request_sha256, worker_sha256,
                       model_files, gpu_index=None, gpu_memory_mb=None, **kwargs):
        from topos import ml_worker

        assert engine == "mace" and gpu_index is None and gpu_memory_mb is None
        assert file_digest(Path(command[-1])) == request_sha256
        assert file_digest(Path(ml_worker.__file__)) == worker_sha256
        assert all(file_digest(Path(path)) == sha for path, sha in model_files.items())
        return run_process(command, workdir, resources, **kwargs)


@pytest.fixture
def genuine_runtime():
    python, request_path, crest = (os.environ.get(name) for name in
                                   ("TOPOS_ML_TEST_PYTHON", "TOPOS_ML_TEST_REQUEST", "TOPOS_CREST_EXECUTABLE"))
    if not python or not request_path or not crest:
        pytest.skip("explicit genuine CREST/MACE interpreter and checkpoint request required")
    original = read_json(Path(request_path))
    manifest = ModelManifest.model_validate(original["manifest"])
    assert manifest.backend == "mace"
    return DevelopmentNativeMLRuntime(crest, python), manifest, Molecule.model_validate(original["molecules"][0])


def test_actual_native_crest_reads_actual_mace_energy_and_gradient(tmp_path, genuine_runtime):
    """A real single-point generic bridge, not a full search or BASE acceptance."""
    runtime, manifest, molecule = genuine_runtime
    native = tmp_path / "native"
    native.mkdir()
    resources = ResourceLimits(threads=1, memory_mb=8192, budget_seconds=90)
    server = PersistentMLServer(runtime, manifest, molecule, resources, tmp_path / "model-server",
                                max_requests=100, max_receipt_mb=8)
    try:
        server.start()
        wrapper = server.make_client(native, native / "fixed-client", mode="crest")
        write_xyz(molecule, native / "input.xyz")
        # Single-point is explicitly selected for this bridge test only.
        (native / "ml-crest.toml").write_text('runtype = "singlepoint"\n' +
            crest_ml_input(molecule, wrapper, ResourceLimits(threads=1)))
        process = runtime.run_process([runtime.crest, "ml-crest.toml", "--newversion", "--keepdir"], native,
                                      ResourceLimits(threads=1, memory_mb=512, budget_seconds=30))
        assert process.status == "completed", Path(process.stderr_path).read_text()
        output = Path(process.stdout_path).read_text()
        assert "Generic script execution" in output and str(wrapper) in output
        assert "CREST terminated normally." in output
        server.close()
        evidence = _receipt_evidence(server)
        assert evidence["requests"] == evidence["model_load_count"] == 1
        receipt = read_json(server.folder / "calls" / "0000001.json")
        native_values = [float(line) for line in (native / "crest.engrad").read_text().splitlines()
                         if line.strip() and not line.startswith("#")]
        assert native_values[0] == len(molecule.symbols)
        frame = receipt["response"]["frame"]
        assert native_values[1] == pytest.approx(frame["energy_hartree"], abs=1e-14)
        np.testing.assert_allclose(np.array(native_values[2:]).reshape(-1, 3),
                                   frame["gradient_hartree_per_bohr"], atol=1e-14, rtol=0)
        # The immutable callback evidence checker detects real receipt tampering.
        (server.folder / "calls" / "0000001.json").unlink()
        with pytest.raises(ValueError, match="receipt count"):
            _receipt_evidence(server)
    finally:
        server.close(cancel=True)


def test_actual_native_sampler_callback_bound_never_claims_completion(tmp_path, genuine_runtime):
    """Real CREST/MACE reaches its explicit bound; never a synthetic success."""
    runtime, manifest, molecule = genuine_runtime
    patched = os.environ.get("TOPOS_CREST_ML_EXECUTABLE")
    if not patched:
        pytest.skip("explicit patched generic-paths-v1 native CREST build required")
    runtime.crest = patched
    result = run_crest_ml(molecule, manifest, ResourceLimits(threads=2, memory_mb=8704, budget_seconds=90),
        tmp_path / "search", runtime=runtime, allocation=ExtOptAllocation(1, 8192, 1, 512),
        profile="crest-mquick-v1", max_requests=2, max_receipt_mb=8)
    assert result.metadata["execution_kind"] == "real", result.diagnostics
    assert result.status in {"failed", "timed-out"} and result.converged is False
    assert result.metadata["potential_fallback"] is False
    assert result.metadata["ml_server_summary"]["successful_requests"] == 2
    assert len(list((tmp_path / "search" / "model-server" / "calls").glob("*.json"))) == 2
    assert result.artifacts and result.engine_version == "3.0.2"
    assert all(frame.metadata["partial_native_attempt"] for frame in result.ensemble)


def test_stock_native_crest_is_rejected_before_model_search(tmp_path, genuine_runtime):
    runtime, manifest, molecule = genuine_runtime
    result = run_crest_ml(molecule, manifest, ResourceLimits(threads=2), tmp_path / "search", runtime=runtime,
                          allocation=ExtOptAllocation(1, 512, 1, 512))
    assert result.status == "unsupported" and "caches stale" in result.diagnostics["reason"]
    assert result.metadata["execution_kind"] == "not-executed" and not result.ensemble
    assert not (tmp_path / "search" / "model-server").exists()


@pytest.mark.parametrize("damage", ["missing-manifest", "patch-bytes", "binary-binding"])
def test_actual_patched_binary_requires_matching_source_provenance(tmp_path, genuine_runtime, damage):
    runtime, manifest, molecule = genuine_runtime
    patched = os.environ.get("TOPOS_CREST_ML_EXECUTABLE")
    if not patched:
        pytest.skip("explicit patched generic-paths-v1 native CREST build required")
    source = Path(patched).parent
    copied = tmp_path / "real-native-installation"
    copied.mkdir()
    for name in ("crest", "installation.json", "source.patch"):
        shutil.copy2(source / name, copied / name)
    # Keep the actual native loader dependencies beside the copied executable.
    if (source / "lib").is_dir():
        shutil.copytree(source / "lib", copied / "lib")
    if damage == "missing-manifest":
        (copied / "installation.json").unlink()
    elif damage == "patch-bytes":
        with (copied / "source.patch").open("ab") as stream:
            stream.write(b"\nchanged patch evidence\n")
    else:
        from topos.storage import atomic_json

        data = read_json(copied / "installation.json")
        data["binary_sha256"] = "0" * 64
        atomic_json(copied / "installation.json", data)
    runtime.crest = str(copied / "crest")
    result = run_crest_ml(molecule, manifest, ResourceLimits(threads=2), tmp_path / "search", runtime=runtime,
                          allocation=ExtOptAllocation(1, 512, 1, 512))
    assert result.status == "failed" and "provenance" in result.diagnostics["reason"]
    assert result.metadata["execution_kind"] == "not-executed" and not result.ensemble
    assert not (tmp_path / "search" / "model-server").exists()
