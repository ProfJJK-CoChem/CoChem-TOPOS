"""Genuine reviewed R2 acceptance with a newly calculated CCSD(T) monomer.

The hydrogen-bonded water dimer is a bounded applicability test, not a benchmark.
A soft-mode, transferability or perturbative failure stays a failed acceptance;
no lower threshold, alternate functional or invented monomer can produce a pass.
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy import constants

from topos.base_integration import BaseRuntime
from topos.config import SystemConfig
from topos.constraints import PROFILES
from topos.correlated import CorrelatedMethod, correlated_input, run_correlated
from topos.correlated_counterpoise import R2_ENERGY_RESOLUTION, CorrelatedCounterpoiseProtocol
from topos.engines import EngineResult
from topos.matrix_r2 import R2_REVIEWED_RESOLUTION, R2MonomerProvenance, R2VPT2Options
from topos.matrix_workflow import MatrixInputs, execute_matrix
from topos.method_matrix import MATRIX_REVISION, reviewed_revision
from topos.models import Molecule, ResourceLimits, RunRecord, RunRequest, utc_now
from topos.science import geometry_digest
from topos.storage import RunStore, atomic_json, digest_json, file_digest
from topos.workflow import Workflow, software_provenance


def isolated_water_protocol() -> CorrelatedMethod:
    return CorrelatedMethod(method="AUTOCI-CCSD(T)", operation="optimize", orbital_basis="cc-pVTZ",
                            frozen_core=True, scf_integrals="conventional", scf_convergence="VeryTightSCF")


def water_dimer_from_monomer(monomer: Molecule) -> tuple[Molecule, list[Molecule], list[dict]]:
    """Rigidly place two exact native monomer shapes in a hydrogen-bond seed.

    This placement is only an initial geometry. Neither the separation nor the
    orientation is claimed to be an optimized or published water-dimer result.
    """
    monomer = Molecule.model_validate(monomer.model_dump())
    if (monomer.symbols != ["O", "H", "H"] or monomer.charge != 0 or monomer.multiplicity != 1
            or monomer.fragments or monomer.bonds or monomer.stereochemistry or any(monomer.isotopes)):
        raise ValueError("Acceptance monomer must be the unmapped closed-shell O,H,H native water profile")
    xyz = np.asarray(monomer.coordinates, float)
    centered = xyz - xyz[0]
    one = centered[1] / np.linalg.norm(centered[1])
    two = centered[2] / np.linalg.norm(centered[2])
    y = two - np.dot(two, one)*one
    if np.linalg.norm(y) < 1e-6:
        raise ValueError("A nonlinear native water geometry is required")
    y /= np.linalg.norm(y)
    donor_rotation = np.column_stack([one, y, np.cross(one, y)])
    bisector = one+two
    bisector /= np.linalg.norm(bisector)
    difference = one-two
    difference /= np.linalg.norm(difference)
    acceptor_rotation = np.column_stack([bisector, np.cross(difference, bisector), difference])
    references, transformations = [], []
    for role, rotation, origin in [("donor", donor_rotation, np.zeros(3)),
                                    ("acceptor", acceptor_rotation, np.array([2.9, 0., 0.]))]:
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-12) or np.linalg.det(rotation) < .999999999:
            raise ValueError("Water placement must be a proper rigid transformation")
        coordinates = centered @ rotation + origin
        reference = Molecule.model_validate({**monomer.model_dump(), "coordinates": coordinates.tolist(),
            "atom_ids": [f"{role}-{i}" for i in range(3)], "name": f"native-CCSD(T)-water-{role}"})
        old_distances = np.linalg.norm(xyz[:, None]-xyz[None, :], axis=2)
        new_distances = np.linalg.norm(coordinates[:, None]-coordinates[None, :], axis=2)
        if not np.allclose(old_distances, new_distances, atol=1e-12, rtol=0):
            raise ValueError("Rigid placement changed the actual high-level monomer shape")
        references.append(reference)
        transformations.append({"role": role, "rotation_row_coordinates": rotation.tolist(),
            "source_origin_angstrom": xyz[0].tolist(), "target_origin_angstrom": origin.tolist(),
            "atom_mapping": dict(zip(monomer.atom_ids, reference.atom_ids, strict=True)),
            "source_geometry_sha256": digest_json(monomer.model_dump(mode="json")),
            "placed_geometry_sha256": digest_json(reference.model_dump(mode="json")),
            "maximum_internal_distance_change_angstrom": float(np.max(np.abs(old_distances-new_distances)))})
    molecule = Molecule(symbols=[*references[0].symbols, *references[1].symbols],
        coordinates=[*references[0].coordinates, *references[1].coordinates],
        atom_ids=[*references[0].atom_ids, *references[1].atom_ids],
        fragments=[[0, 1, 2], [3, 4, 5]], fragment_states=[
            {"atom_indices": [0, 1, 2], "charge": 0, "multiplicity": 1},
            {"atom_indices": [3, 4, 5], "charge": 0, "multiplicity": 1}],
        name="R2 native acceptance hydrogen-bond water dimer")
    return molecule, references, transformations


def acceptance_request(resources: ResourceLimits, monomer: Molecule, native_source: str) -> tuple[RunRequest, list[dict]]:
    """Compile exact input choices; this function alone performs no calculation."""
    if not native_source.strip():
        raise ValueError("Actual high-level monomer evidence reference is required")
    molecule, references, transformations = water_dimer_from_monomer(monomer)
    cp = CorrelatedCounterpoiseProtocol(native=CorrelatedMethod(method="DLPNO-CCSD(T1)", operation="energy",
        orbital_basis="cc-pVDZ-F12", auxiliary_c="cc-pVTZ/C", auxiliary_jk="cc-pVTZ/JK", scf_integrals="RIJK",
        frozen_core=True, pno_profile="TightPNO", tcutpno=1e-7), source_resolution=R2_ENERGY_RESOLUTION)
    inputs = MatrixInputs(source_resolution=R2_REVIEWED_RESOLUTION, isolated_monomer_references=references,
        r2_monomer_provenance=[R2MonomerProvenance(geometry_sha256=digest_json(m.model_dump(mode="json")),
            method="fc-CCSD(T)/cc-pVTZ", source=native_source,
            evidence_kind="declared-calculation-reference") for m in references],
        r2_counterpoise=cp, r2_vpt2=R2VPT2Options(semirigid_modes=True, displacement=.05,
            transfer={"semirigid_same_basin": True}))
    return RunRequest(molecule=molecule, purpose="matrix", engine="orca", method="wB97M-V",
        basis="def2-QZVPP", auxiliary_basis="def2/J", engine_version="6.1.1", profile_id="orca-mapping-v4.1",
        matrix_row_id="T3O-3h", matrix_revision=MATRIX_REVISION, matrix_inputs=inputs.model_dump(mode="json"),
        budget_seconds=resources.budget_seconds, threads=resources.threads, memory_mb=resources.memory_mb,
        device=resources.device, n_candidates=1, include_queue_in_budget=True,
        metadata={"acceptance_scope": "actual separately relaxed B3LYP-D4 VPT2 transfer on hydrogen-bond water dimer; no accuracy benchmark",
            "high_level_monomer_source": native_source,
            "applicability_policy": "Same-basin and semirigid hypotheses are tested by unchanged production gates; failure is not bypassed"}), transformations


def _verify_native(result: EngineResult, folder: Path, binary_hash: str) -> None:
    if (result.status != "completed" or result.converged is not True or result.engine != "orca"
            or result.engine_version != "6.1.1" or result.metadata.get("execution_kind") != "real"
            or result.metadata.get("executable_sha256") != binary_hash or not result.command or not result.artifacts
            or result.molecule is None or result.gradient_hartree_per_bohr is None
            or not result.diagnostics.get("independent_stationarity", {}).get("passed")):
        raise RuntimeError(f"Actual high-level monomer optimization failed: {result.status}; {result.diagnostics}")
    for artifact in result.artifacts:
        path = Path(artifact.path)
        if (path.is_symlink() or not path.resolve().is_relative_to(folder) or not path.is_file()
                or file_digest(path) != artifact.sha256 or path.stat().st_size != artifact.size_bytes):
            raise RuntimeError("High-level monomer raw evidence changed or escaped its directory")
    if not (folder / "final-gradient" / "job.engrad").is_file():
        raise RuntimeError("High-level water geometry lacks its actual independent final correlated gradient")


def _verify_r2(record: RunRecord, binary_hash: str) -> dict:
    output = record.metadata.get("matrix_r2", {})
    if (record.status != "completed" or not record.metadata.get("matrix_execution", {}).get("full_row_completed")
            or output.get("source_resolution") != R2_REVIEWED_RESOLUTION
            or output.get("reviewed_method_revision") != reviewed_revision(R2_REVIEWED_RESOLUTION)
            or output.get("full_reviewed_R2_completed") is not True or output.get("approximate_composite") is not True
            or output.get("original_nonstationary_vpt2_performed") is not False
            or output.get("target_full_molecule_stationary") is not False
            or output.get("experimental_accuracy_claim") is not None or output.get("numerical_transfer_uncertainty") is not None):
        raise RuntimeError(f"Reviewed R2 did not complete its exact approximate scope: {record.status}; {record.metadata.get('termination_reason')}")
    target, reference = (Molecule.model_validate(output[key]) for key in ("target_molecule", "reference_molecule"))
    if (output["target_geometry_sha256"] != geometry_digest(target)
            or output["reference_geometry_sha256"] != geometry_digest(reference)
            or geometry_digest(target) == geometry_digest(reference)):
        raise RuntimeError("R2 must retain distinct actual frozen and independently relaxed geometries")
    identity = ["6.1.1", binary_hash]
    if any(output[key].get("engine_identity") != identity for key in ("geometry", "counterpoise")) or output["engine_identity"] != identity:
        raise RuntimeError("QZ geometry, CP, independent reference and VPT2 must share the actual native ORCA identity")
    method = output["reference_method"]
    if (method.get("method"), method.get("dispersion"), method.get("basis"), method.get("profile_id")) != (
            "B3LYP", "D4", "def2-TZVPP", "orca-vpt2-reference-v1") or method.get("constraints"):
        raise RuntimeError("The independent native reference is not the explicit unconstrained B3LYP-D4/TZVPP variant")
    diagnostic = output["geometry"]["constraint_diagnostics"]
    residual = np.asarray(diagnostic["frozen_gradient_hartree_per_bohr"], float)
    if (residual.shape != (6, 3) or not np.isfinite(residual).all()
            or abs(float(np.max(np.abs(residual)))-diagnostic["max_frozen_gradient_hartree_per_bohr"]) > 1e-12
            or not 0 <= diagnostic["max_trajectory_intrafragment_drift_angstrom"] <= PROFILES["mapping-2026"].rigidity_angstrom):
        raise RuntimeError("Frozen-monomer residual forces or whole-trajectory rigidity evidence are inconsistent")
    cp = output["counterpoise"]
    legs = cp["leg_energies_hartree"]
    if set(legs) != {"complex-in-complex-basis", "fragment-0-in-complex-basis", "fragment-1-in-complex-basis"}:
        raise RuntimeError("R2 requires all three actual native counterpoise legs")
    interaction = math.fsum([legs["complex-in-complex-basis"], -legs["fragment-0-in-complex-basis"], -legs["fragment-1-in-complex-basis"]])
    if (not math.isfinite(interaction) or abs(interaction-cp["cp_interaction_energy_hartree"]) > 1e-11
            or cp["geometry_sha256"] != geometry_digest(target) or cp.get("f12_hamiltonian") is not False):
        raise RuntimeError("R2 counterpoise arithmetic, frozen geometry or ordinary DLPNO identity differs")
    correction = output["correction_transfer"]
    if correction.get("native_execution_verified") is not True or correction.get("options", {}).get("semirigid_same_basin") is not True:
        raise RuntimeError("Rotational transfer lacks actual native evidence or declared applicability")
    masses = np.asarray(correction["mass_provenance"]["masses_amu"], float)
    xyz = np.asarray(target.coordinates, float)
    xyz -= np.average(xyz, axis=0, weights=masses)
    tensor = sum(m*(np.dot(r, r)*np.eye(3)-np.outer(r, r)) for m, r in zip(masses, xyz, strict=True))
    target_constants = constants.h/(8*np.pi**2*np.linalg.eigvalsh(tensor)*constants.atomic_mass*1e-20)/1e9
    native_delta = (np.asarray(correction["native_b0_cm1"])-correction["native_be_cm1"])*constants.c/1e7
    mapping = correction["axis_correspondence"]
    delta = [native_delta[mapping["native_axis_for_sorted_reference"][i]] for i in mapping["reference_axis_for_sorted_target"]]
    approximate = target_constants+delta
    if (not np.allclose(approximate, correction["constants_ghz"], atol=1e-10, rtol=0)
            or not np.allclose(approximate*1000, output["approximate_ground_state_rotational_constants_mhz"], atol=1e-7, rtol=0)
            or not np.allclose(target_constants*1000, output["mass_matched_target_rotational_constants_mhz"], atol=1e-7, rtol=0)):
        raise RuntimeError("Independent inertia/axis arithmetic does not reproduce the reported transferred constants")
    native = [a for a in record.attempts if a.command and a.command[0] != "topos-internal"]
    for attempt in native:
        if (attempt.engine != "orca" or attempt.status != "completed" or attempt.converged is not True
                or attempt.validation_status != "validated-for-protocol" or not attempt.artifacts
                or attempt.engine_version != "6.1.1" or attempt.metadata.get("execution_kind") != "real"
                or attempt.metadata.get("executable_sha256") != binary_hash):
            raise RuntimeError("R2 retained an incomplete or inconsistent actual native stage")
    keys = [a.metadata.get("component_key") for a in native]
    if (sum(str(key).startswith("r2-cp-") for key in keys) != 3
            or keys.count("r2-independent-dft-reference-optimize") != 1 or keys.count("r2-independent-dft-vpt2") != 1):
        raise RuntimeError("R2 acceptance must retain exactly three CP legs, one independent optimization and one VPT2 component")
    return output


def r2_composite_case(runtime: BaseRuntime, folder: Path, resources: ResourceLimits) -> dict:
    """Execute the public compiled recipe and re-enter it from verified persistence."""
    resources = ResourceLimits.model_validate(resources.model_dump())
    if not math.isfinite(resources.budget_seconds) or resources.budget_seconds > 5400:
        raise ValueError("R2 native acceptance needs one finite shared budget of at most 5400 seconds")
    started, deadline = time.monotonic(), time.monotonic()+resources.budget_seconds
    folder = folder.resolve()
    if folder.is_relative_to(Path(__file__).resolve().parents[1]) or folder.exists() and any(folder.iterdir()):
        raise ValueError("R2 acceptance needs an empty directory outside source")
    folder.mkdir(parents=True, exist_ok=True)
    progress = {"schema": "topos-r2-native-acceptance-progress/1", "status": "running", "started_at": utc_now(),
        "source": software_provenance(), "helper_sha256": file_digest(Path(__file__)), "stages": []}
    calls, utility_calls = [], []
    original_process, original_utility = BaseRuntime.run_process, BaseRuntime.run_orca_utility

    def remaining():
        seconds = deadline-time.monotonic()
        if seconds <= 0:
            raise TimeoutError("R2 acceptance aggregate deadline exhausted")
        return resources.model_copy(update={"budget_seconds": seconds})

    def counted_process(owner, command, workdir, limits, **kwargs):
        limits = limits.model_copy(update={"budget_seconds": min(limits.budget_seconds, remaining().budget_seconds)})
        process = original_process(owner, command, workdir, limits, **kwargs)
        calls.append({"command": list(command), "workdir": str(workdir), "resources": limits.model_dump(mode="json"),
                      "log_prefix": kwargs.get("log_prefix"), "result": process.to_dict()})
        return process

    def counted_utility(owner, command, workdir, limits, **kwargs):
        limits = limits.model_copy(update={"budget_seconds": min(limits.budget_seconds, remaining().budget_seconds)})
        result = original_utility(owner, command, workdir, limits, **kwargs)
        utility_calls.append({"command": list(command), "workdir": str(workdir), "result": result})
        return result

    def reject_replay_process(*args, **kwargs):
        raise RuntimeError("Verified completed R2 replay attempted a new native process or basis export")

    try:
        runtime.validate_resources(resources)
        binary = Path(runtime.resolve_executable("orca"))
        binary_hash = file_digest(binary)
        progress.update(orca_executable_sha256=binary_hash, base=runtime.provenance())
        atomic_json(folder / "progress.json", progress)
        monomer = Molecule(symbols=["O", "H", "H"], coordinates=[[0., 0., 0.], [.97, 0., 0.], [-.25, .94, 0.]])
        protocol = isolated_water_protocol()
        correlated_input(monomer, protocol, remaining())
        atomic_json(folder / "isolated-water-request.json", {"molecule": monomer.model_dump(mode="json"),
                    "protocol": protocol.model_dump(mode="json"), "scope": "actual canonical frozen-core CCSD(T)/cc-pVTZ monomer optimization via AUTOCI"})
        with patch.object(BaseRuntime, "run_process", counted_process), patch.object(BaseRuntime, "run_orca_utility", counted_utility):
            high_level = run_correlated(monomer, protocol, remaining(), folder / "isolated-water",
                                       executable=binary, process_runner=runtime.run_process)
            atomic_json(folder / "isolated-water-result.json", high_level.model_dump(mode="json"))
            _verify_native(high_level, folder / "isolated-water", binary_hash)
            source = ("Actual retained AUTOCI canonical fc-CCSD(T)/cc-pVTZ optimization: "
                + str(folder / "isolated-water-result.json") + " sha256=" + file_digest(folder / "isolated-water-result.json"))
            request, transformations = acceptance_request(remaining(), high_level.molecule, source)
            atomic_json(folder / "monomer-placement.json", {"transformations": transformations,
                "scope": "two exact native monomer shapes under proper rigid transformations and explicit atom-ID remapping"})
            progress["stages"].append({"stage": "native-high-level-monomer", "status": "completed",
                "result_sha256": file_digest(folder / "isolated-water-result.json")})
            atomic_json(folder / "progress.json", progress)
            workflow = Workflow(folder / "runs", config=SystemConfig(execution_backend="base", base_registry_path=runtime.registry_path))
            # Reduce the public request budget by any time spent serializing its
            # immutable inputs; no fresh budget is granted to the R2 campaign.
            request.budget_seconds = remaining().budget_seconds
            atomic_json(folder / "request.json", request.model_dump(mode="json"))
            record = workflow.run(request)
            store = RunStore(record.metadata["run_dir"])
            store.verify()
            output = _verify_r2(record, binary_hash)
        if not calls or any(call["result"]["status"] != "completed" for call in calls):
            raise RuntimeError("R2 acceptance lacks successful genuine native process execution")
        original_attempts = [a.model_dump(mode="json") for a in record.attempts]
        output_hash, call_count, utility_count = digest_json(output), len(calls), len(utility_calls)
        with patch.object(BaseRuntime, "run_process", reject_replay_process), patch.object(BaseRuntime, "run_orca_utility", reject_replay_process):
            resumed = workflow.resume(store.run_dir, invocation_budget_seconds=remaining().budget_seconds)
            if resumed.model_dump(mode="json") != record.model_dump(mode="json"):
                raise RuntimeError("Public completed-run recovery changed the persisted R2 record")
            # Re-enter the compiled recipe too, exercising actual child/CP/DFT/
            # VPT2 cache verification instead of only the completed-run shortcut.
            recovered = RunRecord.model_validate(store.load())
            execute_matrix(workflow, recovered, store, deadline, None)
            replay = _verify_r2(recovered, binary_hash)
        if (digest_json(replay) != output_hash or [a.model_dump(mode="json") for a in recovered.attempts] != original_attempts
                or len(calls) != call_count or len(utility_calls) != utility_count):
            raise RuntimeError("Persisted R2 replay changed native components or its result")
        remaining()
        snapshot = store.verify()
        atomic_json(folder / "native-result.json", replay)
        progress.update(status="passed", finished_at=utc_now(), run_id=record.run_id)
        return {"recovery_verified": True, "replay_process_call_count": 0,
            "native_process_call_count": call_count, "native_basis_utility_count": utility_count,
            "all_attempt_count": len(record.attempts),
            "native_attempt_count": sum(bool(a.command) and a.command[0] != "topos-internal" for a in record.attempts),
            "run_id": record.run_id,
            "snapshot_id": snapshot["snapshot_id"], "source_resolution": R2_REVIEWED_RESOLUTION,
            "reviewed_method_revision": reviewed_revision(R2_REVIEWED_RESOLUTION),
            "high_level_monomer_protocol": protocol.model_dump(mode="json"),
            "high_level_result_sha256": file_digest(folder / "isolated-water-result.json"),
            "monomer_placement_sha256": file_digest(folder / "monomer-placement.json"),
            "result_sha256": file_digest(folder / "native-result.json"), "helper_sha256": file_digest(Path(__file__)),
            "approximate_ground_state_rotational_constants_mhz": replay["approximate_ground_state_rotational_constants_mhz"],
            "cp_interaction_energy_hartree": replay["counterpoise"]["cp_interaction_energy_hartree"],
            "frozen_residual_gradient_hartree_per_bohr": replay["geometry"]["constraint_diagnostics"]["max_frozen_gradient_hartree_per_bohr"],
            "elapsed_seconds": time.monotonic()-started, "accuracy_benchmark": False,
            "scope": "Genuine high-level monomer, frozen QZ dimer, ordinary DLPNO CP, independent B3LYP-D4 VPT2 transfer and process-free durable replay; applicability gates unchanged"}
    except Exception as exc:
        progress.update(status="failed", reason=str(exc), exception=type(exc).__name__, finished_at=utc_now())
        raise
    finally:
        atomic_json(folder / "native-process-calls.json", {"native_processes": calls, "basis_utilities": utility_calls})
        atomic_json(folder / "progress.json", progress)
