"""Actual fifteen-component ORCA F12 composite acceptance through BASE.

The exponents below are explicitly chosen numerical acceptance parameters, not
accuracy calibrations. Missing native calculations cannot pass this case.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

from topos.base_integration import BaseRuntime
from topos.config import SystemConfig
from topos.correlated import CorrelatedMethod, correlated_input
from topos.fragments import split_fragments
from topos.matrix_workflow import MatrixInputs
from topos.method_matrix import MATRIX_REVISION, reviewed_revision
from topos.models import Molecule, ResourceLimits, RunRecord, RunRequest
from topos.orca_f12_composite import (
    SOURCE_RESOLUTION,
    OrcaF12CompositeProtocol,
    execute_orca_f12_composite,
)
from topos.storage import RunStore, atomic_json, digest_json, file_digest
from topos.workflow import Workflow, software_provenance


def acceptance_request(resources: ResourceLimits) -> RunRequest:
    """Exact water + H2 system and five independently declared native protocols."""
    molecule = Molecule(symbols=["O", "H", "H", "H", "H"],
        coordinates=[[0., 0., 0.], [.96, 0., 0.], [-.24, .93, 0.],
                     [0., 0., 6.], [.74, 0., 6.]],
        fragments=[[0, 1, 2], [3, 4]], fragment_states=[
            {"atom_indices": [0, 1, 2], "charge": 0, "multiplicity": 1},
            {"atom_indices": [3, 4], "charge": 0, "multiplicity": 1}])
    common = dict(operation="energy", frozen_core=True, scf_integrals="conventional",
                  scf_convergence="VeryTightSCF")
    base = CorrelatedMethod(method="CCSD(T)-F12D/RI", orbital_basis="jun-cc-pVTZ",
                            auxiliary_c="cc-pVQZ/C", cabs="cc-pVTZ-F12-CABS", **common)
    low = CorrelatedMethod(method="F12-RI-MP2", orbital_basis="jun-cc-pVTZ",
                           auxiliary_c="cc-pVQZ/C", cabs="cc-pVTZ-F12-CABS", **common)
    high = CorrelatedMethod(method="F12-RI-MP2", orbital_basis="jun-cc-pVQZ",
                            auxiliary_c="cc-pVQZ/C", cabs="cc-pVQZ-F12-CABS", **common)
    cv_fc = CorrelatedMethod(method="MP2", orbital_basis="cc-pwCVTZ", **common)
    cv_ae = CorrelatedMethod.model_validate({**cv_fc.model_dump(), "frozen_core": False})
    protocol = OrcaF12CompositeProtocol(base=base, mp2_low=low, mp2_high=high,
        cv_ae=cv_ae, cv_fc=cv_fc, hf_exponential_alpha=1.7, correlation_inverse_power=3.,
        extrapolation_quantity="hf-plus-cabs-exponential-and-f12-correlation-power",
        convention="orca-f12d-ri-mp2-cbs-cv-v1")
    for physical in [molecule, *split_fragments(molecule)]:
        for native in protocol.protocols().values():
            correlated_input(physical, native, resources)
    inputs = MatrixInputs(source_resolution=SOURCE_RESOLUTION, orca_f12_composite=protocol)
    return RunRequest(molecule=molecule, purpose="matrix", engine="orca", method=base.method,
        engine_version="6.1.1", basis=base.orbital_basis, auxiliary_basis=base.auxiliary_c,
        matrix_row_id="T5-3h", matrix_revision=MATRIX_REVISION,
        matrix_inputs=inputs.model_dump(mode="json"), budget_seconds=resources.budget_seconds,
        threads=resources.threads, memory_mb=resources.memory_mb, device=resources.device,
        metadata={"acceptance_scope": "frozen water+H2 composite implementation; no accuracy benchmark",
                  "cbs_exponents_role": "explicit numerical acceptance parameters, not calibrated accuracy parameters"})


class _CountedRuntime:
    """Count calls while delegating unchanged to the actual BASE authority."""

    def __init__(self, runtime: BaseRuntime):
        self.runtime = runtime
        self.calls: list[dict] = []

    def resolve_executable(self, *args, **kwargs):
        return self.runtime.resolve_executable(*args, **kwargs)

    def run_process(self, command, workdir, resources, **kwargs):
        process = self.runtime.run_process(command, workdir, resources, **kwargs)
        self.calls.append({"command": list(command), "workdir": str(workdir),
            "resources": resources.model_dump(mode="json"), "log_prefix": kwargs.get("log_prefix"),
            "result": process.to_dict()})
        return process


def _verify_composite(record: RunRecord, protocol: OrcaF12CompositeProtocol, binary_hash: str) -> dict:
    """Check actual native component evidence and independently recompute the sum."""
    output = record.metadata.get("matrix_correlated", {})
    if (output.get("source_resolution") != SOURCE_RESOLUTION
            or output.get("reviewed_method_revision") != reviewed_revision(SOURCE_RESOLUTION)
            or output.get("geometry_state") != "frozen-inc"
            or output.get("counterpoise_applied") is not False
            or output.get("geometry_optimized") is not False
            or output.get("published_junchs_f12b_recipe") is not False
            or output.get("accuracy_claim") is not None
            or output.get("binding_energy_hartree") is not None
            or output.get("gibbs_energy_hartree") is not None):
        raise RuntimeError("F12 composite does not retain its exact reviewed scientific scope")
    physical = {"complex": record.request.molecule,
                **{f"fragment-{i}": m for i, m in enumerate(split_fragments(record.request.molecule))}}
    expected = {f"orca-F12D-composite-{role}-{component}": (molecule, native)
                for role, molecule in physical.items() for component, native in protocol.protocols().items()}
    attempts = [a for a in record.attempts if a.metadata.get("role") == "matrix-native-component"]
    if len(attempts) != 15 or {a.metadata.get("component_key") for a in attempts} != set(expected):
        raise RuntimeError("F12 composite must retain exactly fifteen unique native components")
    for attempt in attempts:
        molecule, native = expected[attempt.metadata["component_key"]]
        payload = attempt.metadata.get("native_result", {})
        metadata = payload.get("metadata", {})
        if (attempt.status != "completed" or attempt.converged is not True
                or attempt.validation_status != "validated-for-protocol"
                or attempt.metadata.get("execution_kind") != "real" or not attempt.command or not attempt.artifacts
                or attempt.engine != "orca" or attempt.engine_version != "6.1.1"
                or attempt.metadata.get("requested_protocol") != native.model_dump(mode="json")
                or payload.get("molecule") != molecule.model_dump(mode="json")
                or metadata.get("executable_sha256") != binary_hash
                or payload.get("status") != "completed" or payload.get("converged") is not True):
            raise RuntimeError("F12 composite component lacks exact genuine native identity and frozen geometry")
    details = output.get("component_details", {})
    if set(details) != set(physical):
        raise RuntimeError("F12 composite is missing a complex or physical-fragment result")
    for role, detail in details.items():
        energies = detail.get("components_hartree", {})
        partitions = detail.get("mp2_f12_partitions", {})
        if set(energies) != set(protocol.protocols()) or set(partitions) != {"mp2_low", "mp2_high"}:
            raise RuntimeError("F12 composite lacks complete CBS/CV decomposition")
        for name, partition in partitions.items():
            hf_cabs = math.fsum([partition["hf_hartree"], partition["cabs_singles_hartree"]])
            correlation = math.fsum([partition["orbital_mp2_correlation_hartree"],
                                     partition["f12_correlation_correction_hartree"]])
            if (abs(hf_cabs - partition["hf_plus_cabs_hartree"]) > 2e-9
                    or abs(correlation - partition["f12_correlation_hartree"]) > 2e-9
                    or abs(hf_cabs + correlation - energies[name]) > 2e-9):
                raise RuntimeError("Native HF+CABS and true F12 correlation partitions do not sum")
        low, high = partitions["mp2_low"], partitions["mp2_high"]
        h_inf = low["hf_plus_cabs_hartree"] + (high["hf_plus_cabs_hartree"] - low["hf_plus_cabs_hartree"]) / (1 - math.exp(-1.7))
        c_inf = low["f12_correlation_hartree"] + (high["f12_correlation_hartree"] - low["f12_correlation_hartree"]) / (1 - (3/4)**3)
        cv = energies["cv_ae"] - energies["cv_fc"]
        derived = math.fsum([energies["base"], h_inf, c_inf, -energies["mp2_low"], cv])
        if (not all(math.isfinite(v) for v in [derived, cv, *energies.values()])
                or abs(derived - detail["electronic_energy_hartree"]) > 2e-10
                or abs(cv - detail["core_valence_increment_hartree"]) > 2e-10):
            raise RuntimeError("Reported F12 composite differs from independent CBS/CV arithmetic")
        if role != "fragment-1" and abs(cv) <= 1e-10:
            raise RuntimeError("Oxygen-containing acceptance geometry did not exercise its nonzero core-valence increment")
        if role == "fragment-1" and abs(cv) > 2e-8:
            raise RuntimeError("Hydrogen-only fragment unexpectedly changes under core freezing")
    interaction = math.fsum([details["complex"]["electronic_energy_hartree"],
                            -details["fragment-0"]["electronic_energy_hartree"],
                            -details["fragment-1"]["electronic_energy_hartree"]])
    if not math.isfinite(interaction) or abs(interaction - output["interaction_energy_hartree"]) > 2e-10:
        raise RuntimeError("Composite interaction differs from the sum of its frozen physical fragments")
    return output


def f12_composite_case(runtime: BaseRuntime, folder: Path, resources: ResourceLimits) -> dict:
    """Execute all fifteen native jobs and verify replay calls no process again."""
    started = time.monotonic()
    deadline = started + resources.budget_seconds
    folder = folder.resolve()
    if folder.is_relative_to(Path(__file__).resolve().parents[1]) or folder.exists() and any(folder.iterdir()):
        raise ValueError("F12 composite acceptance needs an empty directory outside source")
    folder.mkdir(parents=True, exist_ok=True)
    runtime.validate_resources(resources)
    binary = Path(runtime.resolve_executable("orca"))
    binary_hash = file_digest(binary)
    request = acceptance_request(resources)
    inputs = MatrixInputs.model_validate(request.matrix_inputs)
    protocol = inputs.orca_f12_composite
    atomic_json(folder / "request.json", request.model_dump(mode="json"))
    record = RunRecord(request=request, status="running", metadata={
        "run_dir": str(folder / "run"), "software": software_provenance(),
        "script_sha256": file_digest(Path(__file__)), "base": runtime.provenance(),
        "scope": "Full explicit F12D/RI composite implementation acceptance; no F12b or accuracy benchmark"})
    store = RunStore(folder / "run")
    store.commit(record)
    workflow = Workflow(folder / "runs", config=SystemConfig(execution_backend="base", base_registry_path=runtime.registry_path))
    counted = _CountedRuntime(runtime)
    workflow.base_runtime = counted
    if not execute_orca_f12_composite(workflow, record, store, inputs, deadline, None):
        raise RuntimeError(f"Native F12 composite did not complete: {record.status}; {record.metadata.get('termination_reason')}")
    output = _verify_composite(record, protocol, binary_hash)
    native_calls = [item for item in counted.calls if item["log_prefix"] == "engine"]
    if len(native_calls) != 15 or any(item["result"]["status"] != "completed" for item in counted.calls):
        raise RuntimeError("F12 composite requires fifteen actual completed engine jobs")
    before = [a.model_dump(mode="json") for a in record.attempts]
    before_output = digest_json(output)
    call_count = len(counted.calls)
    store.verify()
    recovered = RunRecord.model_validate(store.load())
    if not execute_orca_f12_composite(workflow, recovered, store, inputs, deadline, None):
        raise RuntimeError("F12 composite completed-component recovery did not finish within the aggregate deadline")
    replay = _verify_composite(recovered, protocol, binary_hash)
    if (len(counted.calls) != call_count or [a.model_dump(mode="json") for a in recovered.attempts] != before
            or digest_json(replay) != before_output):
        raise RuntimeError("F12 composite replay reran a process, changed an attempt, or changed its result")
    if time.monotonic() >= deadline:
        raise RuntimeError("F12 composite acceptance exhausted its aggregate budget before publication")
    recovered.status, recovered.validation_status = "completed", "validated-for-protocol"
    store.commit(recovered)
    snapshot = store.verify()
    atomic_json(folder / "native-result.json", replay)
    atomic_json(folder / "native-process-calls.json", counted.calls)
    return {"recovery_verified": True, "native_component_count": 15,
        "native_process_call_count": call_count, "replay_process_call_count": 0,
        "all_attempt_count": len(recovered.attempts), "snapshot_id": snapshot["snapshot_id"],
        "interaction_energy_hartree": replay["interaction_energy_hartree"],
        "protocol": protocol.model_dump(mode="json"), "source_resolution": SOURCE_RESOLUTION,
        "reviewed_method_revision": reviewed_revision(SOURCE_RESOLUTION),
        "result_sha256": file_digest(folder / "native-result.json"),
        "native_calls_sha256": file_digest(folder / "native-process-calls.json"),
        "helper_sha256": file_digest(Path(__file__)), "elapsed_seconds": time.monotonic() - started,
        "accuracy_benchmark": False, "counterpoise_applied": False, "geometry_optimized": False,
        "scope": "Fifteen real energies, split HF+CABS/F12 correlation CBS, nonzero oxygen CV, frozen water+H2 interaction and process-free durable replay"}
