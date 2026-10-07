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
from topos.engines import EngineResult, artifact_inventory, run_engine
from topos.matrix_components import run_component
from topos.ml import BOHR_ANGSTROM, HARTREE_EV, ModelManifest, molecule_system_identity
from topos.ml_training import (
    DFTSourcePoint,
    MACETrainingOptions,
    ReferenceFrame,
    ReplayFile,
    TrainingDatasetSpec,
    _configuration_key,
    _evaluate_heldout,
    _trained_manifest,
    _validate_replay,
    _verified_fitted_checkpoint,
    compile_mace_training_command,
    heldout_errors,
    import_dft_point,
    numerical_error_metrics,
    prepare_training_dataset,
    reference_extxyz,
    run_mace_finetuning,
    validate_reference_partition,
    validate_training_target,
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


def test_identical_species_cloud_cannot_cross_holdout_by_equivalent_atom_exchange():
    frames = [frame(index) for index in range(100)]
    xyz = frames[0].molecule.coordinates
    frames[-1].molecule.coordinates = [xyz[0], xyz[2], xyz[1]]
    with pytest.raises(ValueError, match="Duplicate configurations"):
        validate_reference_partition(frames)


def test_leakage_fingerprint_ignores_atom_order_but_preserves_isotopes_and_state():
    molecule = water()
    permutation = [2, 0, 1]
    reordered = Molecule(symbols=[molecule.symbols[i] for i in permutation],
                         coordinates=[molecule.coordinates[i] for i in permutation])
    assert _configuration_key(molecule) == _configuration_key(reordered)
    isotope = molecule.model_copy(update={"isotopes": [None, 2, None]})
    charged = molecule.model_copy(update={"charge": 2})
    triplet = molecule.model_copy(update={"multiplicity": 3})
    assert len({_configuration_key(m) for m in [molecule, isotope, charged, triplet]}) == 4


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


def test_reordered_replay_configuration_cannot_leak_into_the_heldout_system(tmp_path):
    settings = options(tmp_path)
    reference = frame(95)
    order = [2, 0, 1]
    reference.molecule = Molecule(symbols=[reference.molecule.symbols[i] for i in order],
                                  coordinates=[reference.molecule.coordinates[i] for i in order])
    reference.gradient_hartree_per_bohr = [reference.gradient_hartree_per_bohr[i] for i in order]
    settings.replay_validation = replay(tmp_path / "reordered-overlap.extxyz", reference_extxyz([reference]))
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


def test_training_target_allows_distorted_reference_geometries_and_names():
    target = water().model_copy(update={"name": "requested water"})
    frames = [frame(index) for index in range(100)]
    # A distorted DFT point is not a different declared molecular graph.
    frames[0].molecule.coordinates[1] = [2.5, .2, -.1]
    frames[-1].molecule.name = "distorted reference"
    domain = validate_training_target(frames, target)
    assert domain["molecule_identity_sha256"] == molecule_system_identity(target)
    assert domain["bound_to_requested_target"] is True
    assert domain["transferability_outside_target_assessed"] is False
    assert "coordinates" not in domain["molecule_identity"]
    assert "name" not in domain["molecule_identity"]


@pytest.mark.parametrize("field,value", [
    ("symbols", ["S", "H", "H"]),
    ("atom_ids", ["oxygen", "h1", "h2"]),
    ("charge", 2), ("multiplicity", 3),
    ("isotopes", [18, None, None]),
    ("fragments", [[0, 1, 2]]),
    ("bonds", [{"atom1": 0, "atom2": 1, "order": 1, "kind": "covalent"}]),
    ("stereochemistry", {"declared_reference": "different"}),
    ("environment", {"solvent": "water"}),
])
def test_training_target_rejects_each_changed_identity_even_with_same_coordinates(field, value):
    data = water().model_dump(mode="json")
    data[field] = value
    target = Molecule.model_validate(data)
    with pytest.raises(ValueError, match="dataset identity differs"):
        validate_training_target([frame()], target)


def test_training_target_preserves_explicit_fragment_state_and_declared_bond_order():
    target_data = water().model_dump()
    target_data.update(fragments=[[0, 1, 2]],
        fragment_states=[{"atom_indices": [0, 1, 2], "charge": 0, "multiplicity": 1}])
    target = Molecule.model_validate(target_data)
    reference = frame().model_copy(update={"molecule": target.model_copy(deep=True)})
    reference.molecule.fragment_states[0].multiplicity = 3
    with pytest.raises(ValueError, match="dataset identity differs"):
        validate_training_target([reference], target)
    target_data = water().model_dump()
    target_data["bonds"] = [{"atom1": 0, "atom2": 1, "order": 1, "kind": "covalent"}]
    target = Molecule.model_validate(target_data)
    reference.molecule = target.model_copy(deep=True)
    reference.molecule.bonds[0].order = 2
    with pytest.raises(ValueError, match="dataset identity differs"):
        validate_training_target([reference], target)


def test_saved_system_model_contract_does_not_inherit_foundation_transferability(tmp_path):
    # Compile the manifest only; this fixture is never used as a native checkpoint.
    original = manifest(tmp_path)
    original.supported_elements = ["C", "H", "N", "O"]
    checkpoint = tmp_path / "manifest-only-contract.model"
    checkpoint.write_text("Manifest serialization fixture, not an executable model")
    domain = validate_training_target([frame()], water())
    prepared = {"reference_protocol": frame().method.model_dump(mode="json"),
                "specification_sha256": digest_json(specification().model_dump(mode="json"))}
    trained = _trained_manifest(original, checkpoint, {"contract_fixture_only": True}, prepared, domain, tmp_path)
    assert trained.head == "Default"
    assert trained.supported_elements == ["H", "O"]
    assert trained.system_identity_sha256 == molecule_system_identity(water())
    assert domain["molecule_identity_sha256"] in trained.domain_reference
    assert prepared["specification_sha256"] in trained.domain_reference
    assert "transferability outside this target is unassessed" in trained.domain_reference
    trained.validate_molecule(water(1.05))
    with pytest.raises(ValueError, match="system-specific"):
        trained.validate_molecule(Molecule(symbols=["O", "H", "H", "O", "H", "H"],
            coordinates=water().coordinates + [[3, 0, 0], [3.96, 0, 0], [2.76, .93, 0]]))


@pytest.mark.parametrize("mutation", ["no-inventory", "changed-bytes", "symlink", "duplicate", "not-native"])
def test_checkpoint_recovery_rejects_unverified_storage_before_training_or_inference(tmp_path, mutation):
    evidence = tmp_path / "original-evidence"
    evidence.mkdir()
    raw = evidence / "non-native.txt"
    raw.write_text("Storage integrity fixture only, no model or scientific execution")
    inventory = [item.model_dump(mode="json") for item in artifact_inventory(evidence)]
    previous = {"status": "partial", "artifacts": inventory}
    if mutation == "no-inventory":
        previous["artifacts"] = []
    elif mutation == "changed-bytes":
        raw.write_text("Changed bytes")
    elif mutation == "symlink":
        raw.rename(evidence / "target.txt")
        raw.symlink_to(evidence / "target.txt")
    elif mutation == "duplicate":
        previous["artifacts"] = inventory + inventory
    with pytest.raises(IntegrityError):
        _verified_fitted_checkpoint(previous, manifest(tmp_path), specification(), options(tmp_path), water(),
            deadline=time.monotonic() + 30, cancel_event=None)


def test_invalid_checkpoint_recovery_never_starts_another_fit(tmp_path):
    class MustNotTrain:
        def run_mace_training_process(self, *args, **kwargs):
            raise AssertionError("A recovery request must never launch fitting")
    result = run_mace_finetuning(manifest(tmp_path), specification(), options(tmp_path),
        ResourceLimits(device="gpu"), tmp_path / "retry", runtime=MustNotTrain(),
        expected_molecule=water(), resume_report={"status": "partial"})
    assert result["status"] == "unsupported"
    assert result["training_performed"] is False
    assert result["heldout_errors"] is None and result["checkpoint"] is None
    assert not (tmp_path / "retry" / "dataset").exists()
    assert not (tmp_path / "retry" / "native").exists()


@pytest.mark.parametrize("stop", ["cancelled", "budget"])
def test_heldout_stop_preserves_checkpoint_without_retraining_or_scientific_success(tmp_path, stop):
    # Control-flow test stops before model loading; no native model is simulated.
    marker = {"contract_fixture_only": "retained checkpoint identity"}
    report = {"checkpoint": marker, "training_performed": False, "resumed_checkpoint": True,
              "heldout_errors": None}
    event = Event()
    if stop == "cancelled":
        event.set()
    result = _evaluate_heldout({}, manifest(tmp_path), ResourceLimits(device="gpu"), options(tmp_path),
        tmp_path / "retry", None, report, cancel_event=event,
        deadline=time.monotonic() + (30 if stop == "cancelled" else -1))
    assert result["status"] == ("cancelled" if stop == "cancelled" else "partial")
    assert result["checkpoint"] == marker and result["heldout_errors"] is None
    assert result["training_performed"] is False
    assert not (tmp_path / "retry").exists()
