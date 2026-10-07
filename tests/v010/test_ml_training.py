"""Fine-tuning data/math/compiler contracts; no DFT or trained model is invented.

Constructed frame values below exercise numerical algorithms only. Native data
tests reject real xTB as a DFT source. Actual MACE parser tests compile arguments
without running or claiming a GPU training calculation.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from topos.config import SystemConfig
from topos.engines import EngineResult, run_engine
from topos.matrix_components import run_component
from topos.ml import BOHR_ANGSTROM, HARTREE_EV, ModelManifest
from topos.ml_training import (
    DFTSourcePoint,
    MACETrainingOptions,
    ReferenceFrame,
    ReplayFile,
    TrainingDatasetSpec,
    _validate_replay,
    compile_mace_training_command,
    heldout_errors,
    import_dft_point,
    numerical_error_metrics,
    prepare_training_dataset,
    reference_extxyz,
    run_mace_finetuning,
    validate_reference_partition,
)
from topos.models import MethodSpec, Molecule, ResourceLimits, RunRecord, RunRequest
from topos.storage import IntegrityError, RunStore, digest_json, file_digest
from topos.workflow import Workflow


def water(length=.96):
    return Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [length, 0, 0], [-.24, .93, 0]])


def source(index, partition=None):
    return DFTSourcePoint(run_dir=f"/mathematical-contract-fixture/run-{index}",
        record_sha256=digest_json({"mathematical_fixture": index}), attempt_id=f"attempt-{index}",
        group_id=f"group-{index}", partition=partition or ("train" if index < 80 else "validation" if index < 90 else "test"))


def frame(index=0, partition=None):
    return ReferenceFrame(source=source(index, partition), molecule=water(.90 + .001 * index),
        method=MethodSpec(engine="orca", method="wB97X-V", basis="def2-TZVPP", purpose="gradient", engine_version="6.1.1"),
        energy_hartree=-75 + index * .001,
        gradient_hartree_per_bohr=[[.001, -.002, .003], [-.001, .002, -.003], [0, 0, 0]])


def specification():
    return TrainingDatasetSpec(points=[source(index) for index in range(100)],
                               partition_rationale="Mathematical fixture of explicit separated configuration groups")


def replay(path, text, reference_method="declared replay reference"):
    path.write_text(text)
    return ReplayFile(path=str(path), sha256=file_digest(path), source="compiler/numerical fixture only",
                      reference_method=reference_method, license_name="test fixture")


def options(tmp_path):
    return MACETrainingOptions(seed=17, max_epochs=40, atomic_energy_baseline="foundation",
        replay_train=replay(tmp_path / "replay-train.extxyz", reference_extxyz([frame(150)])),
        replay_validation=replay(tmp_path / "replay-validation.extxyz", reference_extxyz([frame(160)])),
        gpu_index=0, gpu_memory_mb=4096)


def manifest(tmp_path):
    # A hash-binding compiler fixture only; never passed to torch or a native model evaluator.
    path = tmp_path / "not-a-native-checkpoint.model"
    path.write_text("This is not a trained model; unavailable-runtime tests must never execute it.")
    return ModelManifest(backend="mace", family="compiler-fixture", package_version="0.3.16",
        members=[{"path": str(path), "sha256": file_digest(path), "training_run_id": "compiler-fixture", "source": "unit test"}],
        training_method="fixture", license_name="test fixture", license_url="https://example.invalid/license",
        supported_elements=["H", "O"], supported_charges=[0], supported_multiplicities=[1],
        precision="float64", domain_reference="fixture, no inference authorized")


def test_explicit_three_way_group_partition_and_cardinality():
    report = validate_reference_partition([frame(index) for index in range(100)])
    assert report["counts"] == {"train": 80, "validation": 10, "test": 10}
    assert len(report["configuration_keys"]) == 100
    assert report["native_provenance_verified"] is False
    for count in (99, 501):
        with pytest.raises(ValueError):
            TrainingDatasetSpec(points=[source(index) for index in range(count)], partition_rationale="fixture")


def test_same_trajectory_group_cannot_cross_partitions_and_holdout_cannot_be_omitted():
    data = specification().model_dump()
    data["points"][80]["group_id"] = data["points"][0]["group_id"]
    with pytest.raises(ValueError, match="groups must not cross"):
        TrainingDatasetSpec.model_validate(data)
    data = specification().model_dump()
    for point in data["points"]:
        if point["partition"] == "test":
            point["partition"] = "validation"
    with pytest.raises(ValueError, match="held-out test"):
        TrainingDatasetSpec.model_validate(data)


def test_same_immutable_dft_attempt_cannot_be_duplicated():
    data = specification().model_dump()
    data["points"][1] = data["points"][0]
    with pytest.raises(ValueError, match="cannot occur more than once"):
        TrainingDatasetSpec.model_validate(data)


def test_rotated_translated_duplicates_cannot_leak_into_holdout():
    frames = [frame(index) for index in range(100)]
    rotation = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]])
    frames[-1].molecule.coordinates = (np.asarray(frames[0].molecule.coordinates) @ rotation + [2, 3, 4]).tolist()
    with pytest.raises(ValueError, match="Duplicate configurations"):
        validate_reference_partition(frames)


@pytest.mark.parametrize("mutation", ["method", "basis", "state", "atom-mapping"])
def test_reference_labels_must_share_exact_system_and_hamiltonian(mutation):
    frames = [frame(index) for index in range(100)]
    if mutation == "method":
        frames[-1].method.method = "B3LYP"
    elif mutation == "basis":
        frames[-1].method.basis = "def2-SVP"
    elif mutation == "state":
        frames[-1].molecule.charge = 2
    else:
        frames[-1].molecule.atom_ids = ["different", "atom-1", "atom-2"]
    with pytest.raises(ValueError, match="same explicit DFT Hamiltonian|share atom mapping"):
        validate_reference_partition(frames)


@pytest.mark.parametrize("gradient", [[[0, 0, 0]], [[0, 0], [0, 0], [0, 0]], [[float("nan"), 0, 0]] * 3])
def test_incomplete_or_nonfinite_gradients_cannot_be_reference_labels(gradient):
    data = frame().model_dump()
    data["gradient_hartree_per_bohr"] = gradient
    with pytest.raises(ValueError):
        ReferenceFrame.model_validate(data)


def test_ase_reads_exact_energy_and_opposite_signed_force_unit_conversion():
    from ase.io import read

    reference = frame()
    atoms = read(io.StringIO(reference_extxyz([reference])), format="extxyz")
    assert atoms.info["REF_energy"] == pytest.approx(reference.energy_hartree * HARTREE_EV)
    np.testing.assert_allclose(atoms.arrays["REF_forces"],
        -np.asarray(reference.gradient_hartree_per_bohr) * HARTREE_EV / BOHR_ANGSTROM, atol=1e-14)
    np.testing.assert_allclose(atoms.positions, reference.molecule.coordinates, atol=1e-15)
    assert not atoms.pbc.any()


def test_heldout_error_metrics_use_absolute_offsets_per_atom_and_all_force_components():
    result = numerical_error_metrics([0., 0.], [1 / HARTREE_EV, -3 / HARTREE_EV],
        [[[0, 0, 0]], [[0, 0, 0], [0, 0, 0]]],
        [[[BOHR_ANGSTROM / HARTREE_EV, 0, 0]], [[0, 0, 0], [0, 0, 0]]])
    assert result["energy_mae_ev"] == pytest.approx(2)
    assert result["energy_rmse_ev"] == pytest.approx(np.sqrt(5))
    assert result["energy_per_atom_mae_ev"] == pytest.approx(1.25)
    assert result["energy_per_atom_rmse_ev"] == pytest.approx(np.sqrt((1 + 2.25) / 2))
    assert result["force_component_mae_ev_per_angstrom"] == pytest.approx(1 / 9)
    assert result["force_component_rmse_ev_per_angstrom"] == pytest.approx(1 / 3)


@pytest.mark.parametrize("energies,predicted,gradients,predicted_gradients", [
    ([], [], [], []), ([1], [1, 2], [[[0, 0, 0]]], [[[0, 0, 0]]]),
    ([1], [float("nan")], [[[0, 0, 0]]], [[[0, 0, 0]]]),
    ([1], [1], [[[0, 0, 0]]], [[[0, 0]]]),
    ([1], [1], [[[0, 0, 0]]], [[[float("inf"), 0, 0]]]),
])
def test_error_metrics_reject_missing_or_nonfinite_observations(energies, predicted, gradients, predicted_gradients):
    with pytest.raises(ValueError):
        numerical_error_metrics(energies, predicted, gradients, predicted_gradients)


def test_unexecuted_predictions_and_training_frames_cannot_be_reported_as_holdout():
    prediction = EngineResult(status="unavailable", engine="mace", method="missing", operation="gradient")
    with pytest.raises(ValueError, match="genuine matching MACE"):
        heldout_errors([frame(99)], [prediction], manifest_sha256="a" * 64)
    with pytest.raises(ValueError, match="explicitly selected test"):
        heldout_errors([frame(0)], [prediction], manifest_sha256="a" * 64)


def test_official_cli_pins_multihead_gpu_local_replay_and_excludes_test_set(tmp_path):
    settings = options(tmp_path)
    command = compile_mace_training_command("/audited/mace/python", tmp_path / "foundation.model",
        tmp_path / "train.extxyz", tmp_path / "validation.extxyz", tmp_path / "replay-train.extxyz",
        tmp_path / "replay-validation.extxyz", tmp_path / "native", settings, foundation_head="Default")
    assert command[:3] == ["/audited/mace/python", "-m", "mace.cli.run_train"]
    assert "--multiheads_finetuning=True" in command and "--device=cuda" in command
    assert "--default_dtype=float64" in command and "--E0s=foundation" in command
    assert "--pt_train_file=" + str(tmp_path / "replay-train.extxyz") in command
    assert "--pt_valid_file=" + str(tmp_path / "replay-validation.extxyz") in command
    assert "--foundation_head=Default" in command
    assert not any(argument.startswith(("--test_file", "--restart", "--dry_run")) for argument in command)
    assert "--save_cpu" in command and "--keep_checkpoints" in command


@pytest.mark.integration
def test_actual_installed_mace_0316_argument_parser_accepts_compiled_protocol(tmp_path):
    interpreter = Path(os.environ.get("TOPOS_MACE_PYTHON", "/workspace/.venvs/topos-ml/bin/python"))
    if not interpreter.is_file():
        pytest.skip("The actual pinned MACE parser is not installed")
    settings = options(tmp_path)
    command = compile_mace_training_command(str(interpreter), tmp_path / "foundation.model",
        tmp_path / "train.extxyz", tmp_path / "validation.extxyz", tmp_path / "replay-train.extxyz",
        tmp_path / "replay-validation.extxyz", tmp_path / "native", settings)
    script = (
        "import json, sys, importlib.metadata; "
        "from mace.tools.arg_parser import build_default_arg_parser; "
        "assert importlib.metadata.version('mace-torch') == '0.3.16'; "
        "args=build_default_arg_parser().parse_args(json.loads(sys.argv[1])); "
        "assert args.multiheads_finetuning and args.device == 'cuda' and args.test_file is None; "
        "print('official-parser-accepted')"
    )
    process = subprocess.run([str(interpreter), "-c", script, json.dumps(command[3:])],
                             capture_output=True, text=True, timeout=60, check=False)
    assert process.returncode == 0, process.stderr
    assert "official-parser-accepted" in process.stdout


def test_explicit_replay_does_not_overlap_system_specific_data(tmp_path):
    settings = options(tmp_path)
    _validate_replay(settings, [frame(index) for index in range(100)])
    path = tmp_path / "overlap.extxyz"
    overlap = replay(path, reference_extxyz([frame(95)]))
    settings.replay_validation = overlap
    with pytest.raises(ValueError, match="exclude all system-specific"):
        _validate_replay(settings, [frame(index) for index in range(100)])


def test_replay_partition_or_hash_changes_cannot_be_ignored(tmp_path):
    settings = options(tmp_path)
    data = settings.model_dump()
    data["replay_validation"] = data["replay_train"]
    with pytest.raises(ValueError, match="distinct"):
        MACETrainingOptions.model_validate(data)
    Path(settings.replay_train.path).write_text("altered")
    with pytest.raises(IntegrityError, match="differ from their hash"):
        settings.replay_train.verify()


@pytest.mark.parametrize("device,status,reason", [
    ("cpu", "unsupported", "no CPU substitution"),
    ("gpu", "unavailable", "audited GPU training boundary"),
])
def test_missing_training_authority_never_uses_generic_runner_or_creates_checkpoint(tmp_path, device, status, reason):
    result = run_mace_finetuning(manifest(tmp_path), specification(), options(tmp_path),
        ResourceLimits(device=device), tmp_path / "training", runtime=None)
    assert result["status"] == status and reason in result["reason"]
    assert result["execution_kind"] == "not-executed"
    assert result["checkpoint"] is None and result["heldout_errors"] is None
    assert result["matrix_row_complete"] is False and result["search_reexecuted"] is False
    stored = json.loads((tmp_path / "training" / "training-report.json").read_text())
    assert stored["status"] == status
    assert result["artifacts"] and not list((tmp_path / "training").rglob("*.model"))


@pytest.mark.integration
def test_real_xtb_gradient_cannot_be_imported_as_dft_training_data(tmp_path):
    choices = [os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"), "/workspace/.tools/xtb-dist/bin/xtb"]
    binary = next((shutil.which(choice) for choice in choices if shutil.which(choice)), None)
    if binary is None:
        pytest.skip("A genuine xTB executable is required for the negative provenance test")
    workflow = Workflow(tmp_path / "runs", config=SystemConfig(execution_backend="development", executables={"xtb": binary}))
    record = RunRecord(request=RunRequest(molecule=water(), purpose="optimize"))
    store = RunStore(workflow.output_root / record.run_id)
    method = MethodSpec(engine="xtb", method="GFN2-xTB", purpose="gradient", engine_version="6.7.1")
    def execute(molecule, protocol, resources, folder, **kwargs):
        return run_engine(molecule, protocol, resources, folder, operation="gradient", **kwargs)
    result = run_component(workflow, record, store, "actual-xtb-gradient", water(), method, execute, time.monotonic() + 30, None)
    assert result is not None and result.status == "completed"
    actual_source = DFTSourcePoint(run_dir=str(store.run_dir), record_sha256=digest_json(store.load()),
        attempt_id=record.attempts[0].attempt_id, group_id="actual-xtb", partition="train")
    with pytest.raises(ValueError, match="real completed ORCA 6.1.1 DFT"):
        import_dft_point(actual_source, tmp_path / "imported")
    assert not (tmp_path / "imported").exists()
    actual_source.record_sha256 = "0" * 64
    with pytest.raises(IntegrityError, match="selected immutable record"):
        import_dft_point(actual_source, tmp_path / "altered-record")


@pytest.mark.parametrize("path", ["https://example.invalid/source", "relative/run"])
def test_reference_source_must_be_explicit_local_absolute_snapshot(tmp_path, path):
    point = source(0).model_copy(update={"run_dir": path})
    with pytest.raises(ValueError, match="absolute nonsymlink local"):
        import_dft_point(point, tmp_path / "data")


def test_dataset_preparation_refuses_existing_output_before_native_import(tmp_path):
    (tmp_path / "existing").write_text("user data")
    with pytest.raises(ValueError, match="fresh directory"):
        prepare_training_dataset(specification(), tmp_path)
    assert (tmp_path / "existing").read_text() == "user data"


@pytest.mark.parametrize("stop", ["cancelled", "timed-out"])
def test_reference_verification_honors_preexisting_stop_before_import(tmp_path, stop):
    event = Event()
    if stop == "cancelled":
        event.set()
    with pytest.raises(InterruptedError if stop == "cancelled" else TimeoutError):
        prepare_training_dataset(specification(), tmp_path / "dataset", cancel_event=event,
                                 deadline=time.monotonic() - 1)
    assert not (tmp_path / "dataset" / "sources").exists()


def test_training_cancellation_precedes_unavailable_runtime_and_preserves_reason(tmp_path):
    event = Event()
    event.set()
    result = run_mace_finetuning(manifest(tmp_path), specification(), options(tmp_path),
        ResourceLimits(device="gpu"), tmp_path / "training", runtime=None, cancel_event=event)
    assert result["status"] == "cancelled" and result["execution_kind"] == "not-executed"
    assert result["checkpoint"] is None and not (tmp_path / "training" / "dataset").exists()
