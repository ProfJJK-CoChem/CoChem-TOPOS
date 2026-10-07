"""Durable Workflow integration for physical derivatives and balanced association."""
from __future__ import annotations

import time
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any

from .engines import EngineResult
from .fragments import monomer_first_association
from .models import Artifact, Attempt, Candidate, Molecule, Quantity, RunRecord, new_id, utc_now
from .storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest
from .thermochemistry import calculate_thermochemistry, derivative_coordinate_frame

if TYPE_CHECKING:
    from .workflow import Workflow


def _evidence(path: Path, store: RunStore, role: str) -> Artifact:
    return Artifact(path=path.resolve().relative_to(store.run_dir.resolve()).as_posix(),
                    sha256=file_digest(path), size_bytes=path.stat().st_size, role=role)


def _quantity(name: str, value: Any, units: str, definition: str,
              attempt: Attempt, candidate: Candidate | None = None) -> Quantity:
    return Quantity(name=name, value=value, units=units, definition=definition,
                    attempt_id=attempt.attempt_id, geometry_id=candidate.candidate_id if candidate else None,
                    method=attempt.method, parser="topos.advanced_workflow/0.1.0",
                    validity=attempt.validation_status)


def execute_advanced(workflow: Workflow, record: RunRecord, store: RunStore,
                      deadline: float, cancel_event: Event | None) -> None:
    """Run the requested derived workflow; leave final commit to Workflow._finish."""
    try:
        if record.request.purpose == "association":
            _association(workflow, record, store, deadline, cancel_event)
        else:
            _frequencies(workflow, record, store, deadline, cancel_event)
    except IntegrityError:
        raise
    except ValueError as exc:
        record.status, record.validation_status = "unsupported", "rejected"
        record.metadata["termination_reason"] = str(exc)


def _frequencies(workflow: Workflow, record: RunRecord, store: RunStore,
                 deadline: float, cancel_event: Event | None) -> None:
    request = record.request
    options = request.thermochemistry_options.model_dump()
    molecule = request.molecule
    if request.constraints:
        record.status = "unsupported"
        record.metadata["termination_reason"] = "Frozen/constrained geometries require a dedicated constrained thermal model; full-dimensional RRHO is not applied"
        return
    if "advanced_geometry" in record.metadata:
        molecule = Molecule.model_validate(record.metadata["advanced_geometry"])
    else:
        if request.engine == "xtb":
            molecule, transformation = derivative_coordinate_frame(molecule)
            record.metadata["derivative_coordinate_frame"] = transformation
        if options["optimize_first"]:
            optimization_method = request.method_spec
            if request.engine == "xtb":
                optimization_method = optimization_method.model_copy(update={"profile_id": "xtb-extreme-v1"})
                record.metadata["frequency_optimization_policy"] = {
                    "profile_id": "xtb-extreme-v1", "native_level": "extreme",
                    "reason": "stationary-point gradient criterion is stricter than screening optimization",
                    "hamiltonian_changed": False,
                }
            attempt, optimized = workflow._engine_attempt(record, store, molecule, 0, None,
                                                          deadline, cancel_event, "optimize",
                                                          method_override=optimization_method)
            attempt.metadata["advanced_role"] = "frequency-reference-optimization"
            if optimized.status != "completed" or not optimized.converged or optimized.molecule is None:
                record.status = optimized.status
                record.metadata["termination_reason"] = "Frequency reference optimization did not complete"
                return
            molecule = optimized.molecule
        record.metadata["advanced_geometry"] = molecule.model_dump(mode="json")
        store.commit(record)
    if cancel_event is not None and cancel_event.is_set():
        record.status = "cancelled"
        return
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        record.status = "timed-out"
        return
    parent = None

    def evaluate(geometry, scratch, limits):
        nonlocal parent
        attempt, result = workflow._engine_attempt(record, store, geometry, len(record.attempts), parent,
                                                   deadline, cancel_event, "gradient", strip_constraints=True)
        attempt.metadata["advanced_role"] = "physical-hessian-derivative"
        parent = attempt.attempt_id
        result.metadata["attempt_id"] = attempt.attempt_id
        store.commit(record)
        return result

    symmetry = options.pop("symmetry_number")
    symmetry_evidence = None
    if symmetry is None:
        from .symmetry import point_group_analysis

        symmetry_evidence = point_group_analysis(molecule, tolerance_angstrom=request.symmetry_tolerance_angstrom)
        symmetry = symmetry_evidence.get("rotational_symmetry_number")
        if symmetry is None or symmetry_evidence.get("status") != "stable":
            if request.purpose == "thermochemistry":
                record.status = "unsupported"
                record.metadata["termination_reason"] = "Rotational symmetry is unresolved or tolerance-sensitive; supply an explicitly justified symmetry_number"
                record.metadata["symmetry_evidence"] = symmetry_evidence
                return
            symmetry = 1  # Unused: a frequency-only request does not calculate RRHO.
    step = options.pop("step_bohr")
    options.pop("optimize_first")
    result = calculate_thermochemistry(
        molecule, request.method_spec, request.resources.model_copy(update={"budget_seconds": remaining}),
        store.run_dir / "advanced" / "hessian", evaluator=evaluate,
        executable=workflow.config.executables.get(request.engine), step_bohr=step,
        temperature_k=request.temperature_k, symmetry_number=symmetry,
        thermal=request.purpose == "thermochemistry", artifact_root=store.run_dir,
        cancel_event=cancel_event, **options,
    )
    result["symmetry_evidence"] = symmetry_evidence
    record.status = result["status"]
    record.metadata["advanced_status"] = result["status"]
    if result.get("reason"):
        record.metadata["termination_reason"] = result["reason"]
    evaluations = result["hessian"]["evaluations"]
    if not evaluations:
        return
    derivative_ids = [e["result"]["metadata"].get("attempt_id") for e in evaluations]
    attempts = {a.attempt_id: a for a in record.attempts}
    if any(identifier not in attempts for identifier in derivative_ids):
        record.status = "failed"
        record.metadata["termination_reason"] = "Physical Hessian lacks persisted derivative attempt identities"
        return
    reference = attempts[derivative_ids[0]]
    aggregate = Attempt(run_id=record.run_id, engine=request.engine, method=request.method,
                        status=result["status"], engine_version=reference.engine_version,
                        parent_attempt_id=reference.attempt_id,
                        command=["topos-internal", "physical-finite-difference-hessian"],
                        started_at=reference.started_at, finished_at=utc_now(),
                        converged=result["status"] == "completed",
                        validation_status="validated-for-protocol" if result["status"] == "completed" else "rejected",
                        metadata={"execution_kind": reference.metadata.get("execution_kind", "not-executed"), "result_kind": "physical-hessian-thermochemistry",
                                  "derivative_attempt_ids": derivative_ids,
                                  "accepted_derivative_attempt_id": reference.attempt_id,
                                  "analysis": result["analysis"], "thermochemistry": result["thermochemistry"],
                                  "executable_sha256": reference.metadata.get("executable_sha256"),
                                  "input_molecule": molecule.model_dump(mode="json"),
                                  "output_molecule": molecule.model_dump(mode="json")})
    evidence = store.run_dir / "attempts" / aggregate.attempt_id / "derived-result.json"
    atomic_json(evidence, result)
    aggregate.artifacts = [artifact.model_copy(deep=True) for artifact in reference.artifacts]
    aggregate.artifacts.append(_evidence(evidence, store, "derived-output"))
    aggregate.metadata["derived_result_sha256"] = file_digest(evidence)
    if result["hessian"]["energy_hartree"] is not None:
        aggregate.quantities.append(_quantity("electronic_energy", result["hessian"]["energy_hartree"], "hartree",
                                             "reference electronic energy from actual engine gradient evaluation", aggregate))
    native_result = EngineResult(status=result["status"], engine=request.engine, method=request.method,
                                 operation=request.purpose, molecule=molecule,
                                 energy_hartree=result["hessian"]["energy_hartree"],
                                 engine_version=reference.engine_version, converged=result["status"] == "completed",
                                 metadata={"executable_sha256": reference.metadata.get("executable_sha256")})
    candidate = workflow._candidate(record, molecule, aggregate, native_result, 0, request.purpose)
    if result["analysis"] is not None:
        classification = result["analysis"]["validity"]
        candidate.metadata["stationary_point_classification"] = classification
        record.metadata["stationary_point_classification"] = classification
        candidate.metadata["frequency_analysis"] = result["analysis"]
        if classification != "harmonic-minimum-within-thresholds":
            candidate.status = "human-review"
            aggregate.validation_status = "human-review"
    for name, value, units, definition in (
        ("cartesian_hessian", result["hessian"]["hessian_hartree_per_bohr2"], "hartree/bohr^2", "symmetric central finite differences of actual Cartesian gradients"),
        ("harmonic_frequencies", (result["analysis"] or {}).get("frequencies_cm1"), "cm^-1", "mass-weighted Hessian eigenfrequencies after rigid translation/rotation projection"),
    ):
        if value is not None:
            aggregate.quantities.append(_quantity(name, value, units, definition, aggregate, candidate))
    thermal = result["thermochemistry"]
    if thermal is not None:
        candidate.gibbs_hartree = thermal["gibbs_hartree"]
        candidate.metadata["thermochemistry"] = thermal
        for name, key, units in (("zero_point_energy", "zpe_hartree", "hartree"),
                                 ("thermal_enthalpy_correction", "thermal_enthalpy_correction_hartree", "hartree"),
                                 ("entropy", "entropy_hartree_per_k", "hartree/K"),
                                 ("standard_state_correction", "standard_state_correction_hartree", "hartree"),
                                 ("gibbs_energy", "gibbs_hartree", "hartree")):
            aggregate.quantities.append(_quantity(name, thermal[key], units, f"{thermal['model']}; explicit reference state and symmetry", aggregate, candidate))
        candidate.comparison_protocol = digest_json({
            "electronic_protocol": candidate.comparison_protocol,
            "thermal_model": thermal["model"], "temperature_k": thermal["temperature_k"],
            "standard_state": thermal["standard_state"],
            "rotational_symmetry_convention": "proper-nuclear-rotations; one factor per member",
            "frequency_scale": thermal["frequency_scale"], "low_frequency_policy": thermal["low_frequency_policy"],
            "cutoff_cm1": thermal["cutoff_cm1"],
        })
        aggregate.metadata["comparison_protocol"] = candidate.comparison_protocol
    for quantity in aggregate.quantities:
        quantity.validity = aggregate.validation_status
    record.attempts.append(aggregate)
    # A resumed successful calculation adds a new candidate; partial historical
    # candidates remain in the append-only ledger and cannot enter export.
    record.candidates.append(candidate)
    record.validation_status = aggregate.validation_status
    record.metadata["advanced_result"] = evidence.relative_to(store.run_dir).as_posix()


def _association(workflow: Workflow, record: RunRecord, store: RunStore,
                 deadline: float, cancel_event: Event | None) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        record.status = "timed-out"
        return
    # The protocol/checkpoint namespace persists across invocations. Completed
    # children are reused only through verified immutable RunStore snapshots;
    # interrupted native fragment jobs always receive fresh scratch.
    folder = store.run_dir / "advanced" / "association"
    result = monomer_first_association(record.request.molecule,
                                       record.request.model_copy(update={"budget_seconds": remaining}),
                                       folder, config=workflow.config, cancel_event=cancel_event)
    record.status = result["status"]
    record.metadata["association"] = result.get("energies")
    if result.get("reason"):
        record.metadata["termination_reason"] = result["reason"]
    records = [*result["monomer_runs"]]
    if result["complex_run"]:
        records.append(result["complex_run"])
    known_ids = {a.attempt_id for a in record.attempts}
    for child in records:
        child_folder = Path(child["metadata"]["run_dir"])
        manifest = RunStore(child_folder).verify()
        child_snapshot = child_folder / "snapshots" / manifest["snapshot_id"] / "artifacts"
        for data in child["attempts"]:
            if data["attempt_id"] in known_ids:
                continue
            attempt = Attempt.model_validate(data)
            attempt.run_id = record.run_id
            attempt.metadata["source_child_run_id"] = child["run_id"]
            attempt.metadata["source_child_snapshot_id"] = manifest["snapshot_id"]
            attempt.artifacts = [a.model_copy(update={"path": (child_snapshot / a.path).resolve().relative_to(store.run_dir).as_posix()}) for a in attempt.artifacts]
            record.attempts.append(attempt)
            known_ids.add(attempt.attempt_id)
    frozen_ids = []
    for index, data in enumerate(result["fragment_evaluations"]):
        native = EngineResult.model_validate(data)
        existing = next((a for a in record.attempts if a.metadata.get("association_evaluation_id")
                         == native.metadata.get("association_evaluation_id")), None)
        if existing is not None:
            frozen_ids.append(existing.attempt_id)
            continue
        attempt = Attempt(run_id=record.run_id, engine=native.engine, method=native.method,
                          status=native.status, engine_version=native.engine_version,
                          command=native.command, converged=native.converged,
                          validation_status="validated-for-protocol" if native.status == "completed" else "rejected",
                          finished_at=utc_now(), metadata={**native.metadata, "advanced_role": "frozen-fragment-energy", "fragment_index": index,
                                                          "output_molecule": native.molecule.model_dump(mode="json") if native.molecule else None},
                          diagnostics=native.diagnostics)
        attempt.artifacts = [a.model_copy(update={"path": Path(a.path).resolve().relative_to(store.run_dir).as_posix()}) for a in native.artifacts]
        if native.energy_hartree is not None:
            attempt.quantities = [_quantity("electronic_energy", native.energy_hartree, "hartree", "isolated fragment electronic energy at its geometry in the complex", attempt)]
        record.attempts.append(attempt)
        frozen_ids.append(attempt.attempt_id)
    # Mutable recovery state never becomes a published artifact. Each parent
    # invocation archives a content-addressed, immutable result document.
    evidence = folder / "results" / f"{digest_json(result)}.json"
    atomic_json(evidence, result)
    record.artifacts.append(_evidence(evidence, store, "derived-output"))
    record.metadata["advanced_result"] = evidence.relative_to(store.run_dir).as_posix()
    if result["status"] != "completed":
        return
    child = result["complex_run"]
    candidate = Candidate.model_validate(min((c for c in child["candidates"] if c["status"] == "eligible"), key=lambda c: c["energy_hartree"]))
    candidate.sources.append("monomer-first-association")
    candidate.metadata["association"] = result["energies"]
    candidate.metadata["monomer_run_ids"] = [r["run_id"] for r in result["monomer_runs"]]
    source = next(a for a in record.attempts if a.attempt_id == candidate.attempt_id)
    monomer_ids = [min((c for c in child_record["candidates"] if c["status"] == "eligible"),
                       key=lambda c: c["energy_hartree"])["attempt_id"] for child_record in result["monomer_runs"]]
    aggregate = source.model_copy(deep=True, update={"attempt_id": new_id("attempt"),
                                                    "parent_attempt_id": source.attempt_id})
    aggregate.metadata.update(result_kind="derived-association", source_complex_attempt_id=source.attempt_id,
                               source_complex_candidate_id=candidate.candidate_id,
                               component_attempt_ids=[*monomer_ids, *frozen_ids],
                               monomer_reference_attempt_ids=monomer_ids,
                               frozen_fragment_attempt_ids=frozen_ids,
                               association_result=evidence.relative_to(store.run_dir).as_posix(),
                               association_result_sha256=file_digest(evidence),
                               association=result["energies"])
    aggregate.artifacts.append(_evidence(evidence, store, "derived-output"))
    candidate = candidate.model_copy(deep=True, update={"candidate_id": new_id("candidate"),
                                                       "attempt_id": aggregate.attempt_id})
    for quantity in aggregate.quantities:
        quantity.attempt_id = aggregate.attempt_id
        quantity.geometry_id = candidate.candidate_id
    for name in ("electronic_interaction_hartree", "electronic_binding_hartree", "fragment_deformation_hartree"):
        aggregate.quantities.append(_quantity(name.removesuffix("_hartree"), result["energies"][name], "hartree",
                                             "balanced common-method association; negative interaction/binding favors association", aggregate, candidate))
    record.attempts.append(aggregate)
    record.candidates.append(candidate)
    record.validation_status = "validated-for-protocol"
