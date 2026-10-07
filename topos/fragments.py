"""Explicit, balanced monomer-first association workflows.

Partitions and electronic states are supplied by the caller; distance cutoffs
never authorize bond cleavage. All comparisons use one declared engine recipe.
An electronic binding energy is not relabelled an association free energy.
"""
from __future__ import annotations

import os
import shutil
import time
from collections import Counter
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

import numpy as np

from .config import SystemConfig
from .engines import EngineResult, run_engine
from .models import Bond, Molecule, RunRecord, RunRequest
from .science import geometry_digest
from .storage import (
    IntegrityError,
    RunStore,
    atomic_json,
    confined_file,
    digest_json,
    file_digest,
    read_json,
)
from .thermochemistry import standard_state_correction


def split_fragments(molecule: Molecule) -> list[Molecule]:
    """Extract every explicitly partitioned monomer without changing atom IDs."""
    molecule = Molecule.model_validate(molecule.model_dump())
    if len(molecule.fragments) < 2 or len(molecule.fragment_states) != len(molecule.fragments):
        raise ValueError("association requires a complete explicit partition and fragment charge/spin states")
    member = {atom: number for number, group in enumerate(molecule.fragments) for atom in group}
    if any(member[bond.atom1] != member[bond.atom2] for bond in molecule.bonds):
        raise ValueError("fragment extraction may not cleave a specified covalent or coordination bond")
    if set(molecule.stereochemistry) - {"tetrahedral_centers"}:
        raise ValueError("unsupported stereochemistry cannot be silently discarded during fragment extraction")
    state_by_group = {frozenset(s.atom_indices): s for s in molecule.fragment_states}
    fragments = []
    for number, group in enumerate(molecule.fragments):
        state = state_by_group[frozenset(group)]
        mapping = {old: new for new, old in enumerate(group)}
        ids = {molecule.atom_ids[i] for i in group}
        centers = []
        for center in molecule.stereochemistry.get("tetrahedral_centers", []):
            if center["center_atom_id"] not in ids:
                continue
            if not set(center["ordered_neighbor_ids"]).issubset(ids):
                raise ValueError("fragment partition cuts an explicitly declared stereocenter")
            centers.append(center)
        fragments.append(Molecule(
            symbols=[molecule.symbols[i] for i in group],
            coordinates=[molecule.coordinates[i] for i in group],
            isotopes=[molecule.isotopes[i] for i in group],
            atom_ids=[molecule.atom_ids[i] for i in group],
            charge=state.charge, multiplicity=state.multiplicity,
            bonds=[Bond(atom1=mapping[b.atom1], atom2=mapping[b.atom2], order=b.order, kind=b.kind)
                   for b in molecule.bonds if b.atom1 in mapping and b.atom2 in mapping],
            stereochemistry={"tetrahedral_centers": centers} if centers else {},
            environment=molecule.environment, name=f"{molecule.name or 'complex'}-fragment-{number}",
        ))
    return fragments


def assemble_monomer_seed(complex_molecule: Molecule, monomers: list[Molecule]) -> Molecule:
    """Place relaxed monomers by atom-mapped proper least-squares alignment.

    Existing relative placement is retained as a search seed. This does not
    certify favorable packing, remove steric clashes, or add molecular symmetry.
    """
    references = split_fragments(complex_molecule)
    if len(monomers) != len(references):
        raise ValueError("one relaxed monomer is required per explicit fragment")
    xyz = np.array(complex_molecule.coordinates, dtype=float)
    for group, reference, relaxed in zip(complex_molecule.fragments, references, monomers, strict=True):
        _matching_fragment(reference, relaxed)
        origin = np.asarray(reference.coordinates)
        moving = np.asarray(relaxed.coordinates)
        ac = origin - origin.mean(axis=0)
        bc = moving - moving.mean(axis=0)
        u, _, vt = np.linalg.svd(bc.T @ ac)
        correction = np.eye(3)
        correction[-1, -1] = np.linalg.det(u @ vt)
        placed = bc @ (u @ correction @ vt) + origin.mean(axis=0)
        xyz[group] = placed
    return Molecule.model_validate({**complex_molecule.model_dump(), "coordinates": xyz.tolist()})


def _matching_fragment(reference: Molecule, other: Molecule) -> None:
    for field in ("symbols", "isotopes", "atom_ids", "charge", "multiplicity", "environment", "stereochemistry"):
        if getattr(reference, field) != getattr(other, field):
            raise ValueError(f"fragment reference and result differ in {field}")
    def bonds(molecule: Molecule) -> list[tuple[int, int, float, str]]:
        return sorted((min(b.atom1, b.atom2), max(b.atom1, b.atom2), b.order, b.kind)
                      for b in molecule.bonds)
    if bonds(reference) != bonds(other):
        raise ValueError("fragment reference and result differ in declared bond connectivity/order/kind")


def _execution_identity(record: Any, attempt: Any) -> tuple[str | None, str | None]:
    source = attempt
    if attempt.metadata.get("result_kind") == "derived-optimization":
        identifier = attempt.metadata.get("accepted_derivative_attempt_id")
        sources = [item for item in record.attempts if item.attempt_id == identifier]
        if (len(sources) != 1 or sources[0].status != "completed"
                or sources[0].metadata.get("execution_kind") != "real"
                or (sources[0].engine, sources[0].method, sources[0].engine_version)
                != (attempt.engine, attempt.method, attempt.engine_version)):
            raise ValueError("constrained association energy lacks its actual accepted derivative source")
        source = sources[0]
    return source.engine_version, source.metadata.get("executable_sha256")


def association_energies(
    complex_molecule: Molecule,
    complex_energy_hartree: float,
    fragment_energies_at_complex_hartree: list[float],
    relaxed_monomer_energies_hartree: list[float],
    *,
    comparison_protocol: dict[str, Any],
    bsse_policy: str,
    ghost_fragment_energies_hartree: list[float] | None = None,
    ghost_calculation_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Binding = interaction + deformation; all values refer to electronic E.

    The optional CP path requires externally supplied *actual* ghost-fragment
    evidence. Composite gCP and counterpoise cannot be combined implicitly.
    """
    fragments = split_fragments(complex_molecule)
    n = len(fragments)
    if (len(fragment_energies_at_complex_hartree) != n or len(relaxed_monomer_energies_hartree) != n
            or not comparison_protocol):
        raise ValueError("balanced fragment energies and a complete common comparison protocol are required")
    if bsse_policy not in {"not-corrected", "engine-composite-gCP", "not-applicable-no-atom-centered-basis", "counterpoise"}:
        raise ValueError("BSSE policy must distinguish raw, composite gCP, basis-free, or actual counterpoise")
    values = [complex_energy_hartree, *fragment_energies_at_complex_hartree, *relaxed_monomer_energies_hartree]
    if not np.isfinite(values).all():
        raise ValueError("association energies must be finite")
    frozen_sum = sum(fragment_energies_at_complex_hartree)
    relaxed_sum = sum(relaxed_monomer_energies_hartree)
    interaction = complex_energy_hartree - frozen_sum
    binding = complex_energy_hartree - relaxed_sum
    deformation = frozen_sum - relaxed_sum
    result: dict[str, Any] = {
        "electronic_interaction_hartree": interaction,
        "electronic_binding_hartree": binding,
        "fragment_deformation_hartree": deformation,
        "fragment_deformations_hartree": [f - r for f, r in zip(fragment_energies_at_complex_hartree, relaxed_monomer_energies_hartree, strict=True)],
        "sign_convention": "negative interaction/binding favors association",
        "definitions": {"interaction": "E_complex - sum(E_fragment at complex geometry)",
                        "binding": "E_complex - sum(E_relaxed isolated monomer)",
                        "deformation": "sum(E_fragment at complex geometry - E_relaxed isolated monomer)"},
        "comparison_protocol": comparison_protocol,
        "comparison_protocol_sha256": digest_json(comparison_protocol),
        "fragment_count": n, "delta_n": 1 - n, "bsse_policy": bsse_policy,
        "balanced_composition": dict(Counter(complex_molecule.symbols)),
        "fragment_states": [s.model_dump(mode="json") for s in complex_molecule.fragment_states],
        "electronic_components": {"complex_hartree": complex_energy_hartree,
                                  "fragments_at_complex_hartree": fragment_energies_at_complex_hartree,
                                  "relaxed_monomers_hartree": relaxed_monomer_energies_hartree},
        "gibbs_association_hartree": None,
        "thermodynamic_scope": "electronic association only; no thermal, solvation or reservoir contributions",
        "negative_deformation_requires_review": bool(any(f < r - 1e-8 for f, r in zip(fragment_energies_at_complex_hartree, relaxed_monomer_energies_hartree, strict=True))),
    }
    if ghost_fragment_energies_hartree is not None or bsse_policy == "counterpoise":
        if (bsse_policy != "counterpoise" or ghost_fragment_energies_hartree is None
                or len(ghost_fragment_energies_hartree) != n
                or not np.isfinite(ghost_fragment_energies_hartree).all()
                or not ghost_calculation_evidence or len(ghost_calculation_evidence) != n):
            raise ValueError("counterpoise requires one real ghost-basis fragment energy/evidence per fragment")
        for fragment, evidence in zip(fragments, ghost_calculation_evidence, strict=True):
            if (evidence.get("status") != "completed" or evidence.get("execution_kind") != "real"
                    or evidence.get("charge") != fragment.charge
                    or evidence.get("multiplicity") != fragment.multiplicity
                    or evidence.get("basis_center_atom_ids") != complex_molecule.atom_ids
                    or not evidence.get("artifacts")
                    or evidence.get("comparison_protocol_sha256") != digest_json(comparison_protocol)):
                raise ValueError("ghost-basis evidence does not establish compatible states, centers and common protocol")
        corrected = complex_energy_hartree - sum(ghost_fragment_energies_hartree)
        result.update(cp_interaction_hartree=corrected,
                      additive_cp_correction_hartree=corrected - interaction,
                      cp_binding_hartree=corrected + deformation,
                      ghost_fragment_energies_hartree=ghost_fragment_energies_hartree,
                      ghost_calculation_evidence=ghost_calculation_evidence)
    return result


def association_gibbs(complex_molecule: Molecule, complex_thermal: dict[str, Any],
                      monomer_thermal: list[dict[str, Any]], *,
                      concentration_mol_l: float | None = None) -> dict[str, Any]:
    """Balanced gas-phase association with a single explicit state conversion."""
    fragments = split_fragments(complex_molecule)
    if len(monomer_thermal) != len(fragments):
        raise ValueError("one thermal record is required per monomer")
    records = [complex_thermal, *monomer_thermal]
    keys = ("temperature_k", "model", "frequency_scale", "low_frequency_policy", "cutoff_cm1", "comparison_protocol")
    if any(r.get("status") != "completed" for r in records):
        raise ValueError("association Gibbs requires completed thermal records")
    if not complex_thermal.get("comparison_protocol"):
        raise ValueError("association Gibbs requires an explicit common electronic method protocol")
    if any(any(r.get(k) != complex_thermal.get(k) for k in keys) for r in monomer_thermal):
        raise ValueError("association thermal protocols must agree")
    states = [r["standard_state"] for r in records]
    if any(s.get("kind") != "ideal-gas" or s != states[0] for s in states):
        raise ValueError("supply matching gas-state records; concentration conversion is applied once here")
    if complex_thermal.get("geometry_sha256") != geometry_digest(complex_molecule):
        raise ValueError("complex thermal record belongs to a different geometry/state")
    for monomer, record in zip(fragments, monomer_thermal, strict=True):
        # Relaxed monomers need a composition/state identity, as their geometry
        # necessarily differs from the fragment cut out of the complex.
        identity = record.get("molecular_state")
        if identity != {"symbols": monomer.symbols, "isotopes": monomer.isotopes,
                         "charge": monomer.charge, "multiplicity": monomer.multiplicity,
                         "atom_ids": monomer.atom_ids, "environment": monomer.environment}:
            raise ValueError("thermal monomer composition/state or atom identity is unbalanced")
    correction = None
    delta_g = complex_thermal["gibbs_hartree"] - sum(r["gibbs_hartree"] for r in monomer_thermal)
    if concentration_mol_l is not None:
        correction = standard_state_correction(temperature_k=complex_thermal["temperature_k"],
                                               pressure_pa=states[0]["pressure_pa"],
                                               concentration_mol_l=concentration_mol_l,
                                               delta_n=1 - len(fragments))
        delta_g += correction["correction_hartree"]
    return {"gibbs_association_hartree": delta_g, "standard_state_conversion": correction,
            "delta_n": 1 - len(fragments), "thermal_records": records,
            "solvation_included": False, "configuration_scope": "one chosen conformer per species"}


def monomer_first_association(
    complex_molecule: Molecule, request: RunRequest, workdir: str | Path, *,
    config: SystemConfig | None = None, cancel_event: Event | None = None,
) -> dict[str, Any]:
    """Search monomers, seed/search complex, then calculate frozen-fragment energies.

    Every child search remains a normal durable TOPOS run. References are the
    lowest eligible common-method structures actually found, not a claim of
    global minima. The complete input and mappings remain in the result.
    Verified completed stages and frozen energies survive cancellation/restart;
    incomplete child searches resume under the new invocation's remaining cap.
    """
    started = time.monotonic()
    from .config import load_config
    from .workflow import Workflow

    if request.molecule.model_dump() != complex_molecule.model_dump():
        raise ValueError("association request and complex input must identify the same geometry/state")
    fragments = split_fragments(complex_molecule)
    folder = Path(workdir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    actual_config = config if config is not None else load_config()
    workflow = Workflow(folder / "child-runs", config=actual_config)
    if actual_config.execution_backend == "base":
        from .base_integration import BaseRuntime

        workflow.base_runtime = BaseRuntime(registry_path=actual_config.base_registry_path)
        workflow.base_runtime.validate_resources(request.resources)
        actual_config.executables[request.engine] = workflow.base_runtime.resolve_executable(
            request.engine, actual_config.executables.get(request.engine))
    total_limit = min(request.budget_seconds, getattr(request, "per_ensemble_budget_seconds", None) or request.budget_seconds)
    deadline = started + total_limit
    requested_binary = actual_config.executables.get(request.engine) or os.environ.get(
        f"TOPOS_{request.engine.upper()}_EXECUTABLE", request.engine)
    binary = shutil.which(requested_binary)
    normalized_request = request.model_dump(mode="json")
    normalized_request.pop("budget_seconds")
    protocol = {"schema": "topos-association-recovery/0.1.0", "request": normalized_request,
                "execution_backend": actual_config.execution_backend,
                "executable_sha256": file_digest(Path(binary)) if binary else None}
    protocol_path = folder / "association-protocol.json"
    if protocol_path.exists():
        if read_json(protocol_path) != protocol:
            raise IntegrityError("Association restart geometry, state, method or executable protocol differs")
    else:
        atomic_json(protocol_path, protocol)
    protocol_sha = digest_json(protocol)
    checkpoint_path = folder / "association-checkpoint.json"
    checkpoint = (read_json(checkpoint_path) if checkpoint_path.exists()
                  else {"protocol_sha256": protocol_sha, "stages": {}, "fragment_jobs": {}})
    if (checkpoint.get("protocol_sha256") != protocol_sha
            or not isinstance(checkpoint.get("stages"), dict)
            or not isinstance(checkpoint.get("fragment_jobs"), dict)):
        raise IntegrityError("Association recovery checkpoint belongs to a different protocol")
    atomic_json(checkpoint_path, checkpoint)
    result: dict[str, Any] = {"status": "running", "input_molecule": complex_molecule.model_dump(mode="json"),
                              "monomer_runs": [], "complex_run": None, "fragment_evaluations": [],
                              "energies": None, "complex_molecule": None,
                              "monomer_first": True, "small_fragment_bypass": False,
                              "sampling_completeness": "not-certified", "reused_stages": [],
                              "reused_fragment_indices": [], "protocol_sha256": protocol_sha}

    def finish(status: str, reason: str | None = None) -> dict[str, Any]:
        result["status"] = status
        if reason:
            result["reason"] = reason
        atomic_json(folder / "association-result.json", result)
        return result

    def run_stage(label: str, child_request: RunRequest) -> RunRecord:
        child_request = child_request.model_copy(deep=True)
        child_request.metadata.update(association_stage=label, association_protocol_sha256=protocol_sha)

        def signature(data: dict[str, Any]) -> str:
            return digest_json({k: v for k, v in data.items() if k != "budget_seconds"})

        expected = signature(child_request.model_dump(mode="json"))
        saved = checkpoint["stages"].get(label)
        if saved:
            run_id = saved["run_id"]
            directory = workflow.output_root / run_id
            if Path(run_id).name != run_id or directory.resolve().parent != workflow.output_root:
                raise IntegrityError("Association checkpoint child run escapes its workspace")
        else:
            # A crash can occur after Workflow.run committed its initial input
            # but before the parent recorded its return. Discover only the
            # uniquely tagged, verified run for this exact stage/request.
            found = []
            for directory in sorted(workflow.output_root.iterdir()):
                if not directory.is_dir() or directory.is_symlink() or not (directory / "CURRENT.json").exists():
                    continue
                stored = RunStore(directory).load()
                metadata = stored["request"].get("metadata", {})
                if metadata.get("association_stage") == label and metadata.get("association_protocol_sha256") == protocol_sha:
                    if signature(stored["request"]) != expected:
                        raise IntegrityError("Association stage found a conflicting immutable request")
                    found.append(directory)
            if len(found) > 1:
                raise IntegrityError("Multiple child runs claim the same association stage")
            directory = found[0] if found else None
        if directory is not None:
            stage_store = RunStore(directory)
            stored = stage_store.load()
            manifest = stage_store.verify()
            if signature(stored["request"]) != expected:
                raise IntegrityError("Association child request differs from its stage protocol")
            if saved and saved.get("status") == "completed" and manifest["snapshot_id"] != saved["snapshot_id"]:
                raise IntegrityError("Completed association child snapshot changed")
            child = RunRecord.model_validate(stored)
            if child.status == "completed":
                result["reused_stages"].append(label)
            else:
                checkpoint["stages"][label] = {"run_id": child.run_id, "status": child.status,
                                               "snapshot_id": manifest["snapshot_id"]}
                atomic_json(checkpoint_path, checkpoint)
                child = workflow.resume(directory, cancel_event=cancel_event,
                                        invocation_budget_seconds=child_request.budget_seconds)
        else:
            child = workflow.run(child_request, cancel_event=cancel_event)
        manifest = RunStore(workflow.output_root / child.run_id).verify()
        checkpoint["stages"][label] = {"run_id": child.run_id, "status": child.status,
                                       "snapshot_id": manifest["snapshot_id"]}
        atomic_json(checkpoint_path, checkpoint)
        return child

    relaxed, relaxed_energies, identities = [], [], []
    for index, fragment in enumerate(fragments):
        if cancel_event is not None and cancel_event.is_set():
            return finish("cancelled", "monomer-first association cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return finish("timed-out", "monomer-first association budget exhausted")
        child_data = request.model_dump()
        child_data.update(molecule=fragment.model_dump(), purpose="search", constraints={}, sampler_nci=False,
                          budget_seconds=remaining / (len(fragments) - index + 2), seed=request.seed + index)
        if child_data["sampler_profile"] == "crest-nci-v1":
            child_data["sampler_profile"] = "crest-imtdgc-v1"
        child = run_stage(f"monomer-{index}", RunRequest.model_validate(child_data))
        result["monomer_runs"].append(child.model_dump(mode="json"))
        if child.status != "completed":
            return finish(child.status, f"monomer {index} search did not complete")
        eligible = [c for c in child.candidates if c.status == "eligible" and c.energy_hartree is not None]
        if not eligible:
            return finish("failed", f"monomer {index} has no valid common-method candidate")
        chosen = min(eligible, key=lambda c: c.energy_hartree)
        relaxed.append(chosen.molecule)
        relaxed_energies.append(chosen.energy_hartree)
        attempt = next(a for a in child.attempts if a.attempt_id == chosen.attempt_id)
        identities.append(_execution_identity(child, attempt))
    # Explicit frozen monomer references can be experimental or higher-level
    # geometries. Do not silently replace those internal structures with the
    # search Hamiltonian's relaxed isolated minimum. The latter is retained as
    # the binding/deformation reference, with its distinct geometry provenance.
    seed = (complex_molecule.model_copy(deep=True) if request.constraints
            else assemble_monomer_seed(complex_molecule, relaxed))
    result["complex_seed"] = seed.model_dump(mode="json")
    result["complex_seed_policy"] = ("preserve-explicit-frozen-reference-geometries" if request.constraints
                                     else "proper-alignment-of-relaxed-monomer-search-references")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return finish("timed-out", "association budget exhausted before complex search")
    child_data = request.model_dump()
    child_data.update(molecule=seed.model_dump(), purpose="search", budget_seconds=remaining * 0.75)
    complex_run = run_stage("complex", RunRequest.model_validate(child_data))
    result["complex_run"] = complex_run.model_dump(mode="json")
    if complex_run.status != "completed":
        return finish(complex_run.status, "complex search did not complete")
    eligible = [c for c in complex_run.candidates if c.status == "eligible" and c.energy_hartree is not None]
    if not eligible:
        return finish("failed", "complex has no valid common-method candidate")
    complex_candidate = min(eligible, key=lambda c: c.energy_hartree)
    result["complex_molecule"] = complex_candidate.molecule.model_dump(mode="json")
    complex_attempt = next(a for a in complex_run.attempts if a.attempt_id == complex_candidate.attempt_id)
    identities.append(_execution_identity(complex_run, complex_attempt))
    frozen_energies = []
    for index, fragment in enumerate(split_fragments(complex_candidate.molecule)):
        if cancel_event is not None and cancel_event.is_set():
            return finish("cancelled", "association cancelled before frozen-fragment energy")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return finish("timed-out", "association budget exhausted before frozen-fragment evaluation")
        geometry_sha = geometry_digest(fragment)
        saved_job = checkpoint["fragment_jobs"].get(str(index))
        evaluation = None
        if saved_job and saved_job.get("status") == "completed":
            receipt_path = confined_file(folder, saved_job["receipt"])
            if file_digest(receipt_path) != saved_job["receipt_sha256"] or saved_job["geometry_sha256"] != geometry_sha:
                raise IntegrityError("Frozen-fragment recovery evidence or geometry changed")
            evaluation = EngineResult.model_validate(read_json(receipt_path))
            if (evaluation.status != "completed" or evaluation.molecule is None
                    or geometry_digest(evaluation.molecule) != geometry_sha):
                raise IntegrityError("Frozen-fragment receipt does not establish the requested completed geometry")
            for artifact in evaluation.artifacts:
                try:
                    relative = Path(artifact.path).resolve().relative_to(folder).as_posix()
                except ValueError as exc:
                    raise IntegrityError("Frozen-fragment evidence escapes association workspace") from exc
                path = confined_file(folder, relative)
                if path.stat().st_size != artifact.size_bytes or file_digest(path) != artifact.sha256:
                    raise IntegrityError("Frozen-fragment raw artifact changed")
            result["reused_fragment_indices"].append(index)
        if evaluation is None:
            runner = workflow.base_runtime.run_process if workflow.base_runtime else None
            evaluation_id = uuid4().hex
            job_folder = folder / "fragment-jobs" / evaluation_id
            checkpoint["fragment_jobs"][str(index)] = {"status": "running", "geometry_sha256": geometry_sha,
                                                       "evaluation_id": evaluation_id}
            atomic_json(checkpoint_path, checkpoint)
            evaluation = run_engine(fragment, request.method_spec.model_copy(update={"constraints": {}}),
                                    request.resources.model_copy(update={"budget_seconds": min(remaining, getattr(request, "per_geometry_budget_seconds", None) or remaining)}),
                                    job_folder, operation="energy", cancel_event=cancel_event,
                                    executable=actual_config.executables.get(request.engine),
                                    **({"process_runner": runner} if runner else {}))
            evaluation.metadata["association_evaluation_id"] = evaluation_id
            receipt_path = folder / "fragment-receipts" / f"{evaluation_id}.json"
            atomic_json(receipt_path, evaluation.model_dump(mode="json"))
            checkpoint["fragment_jobs"][str(index)] = {
                "status": evaluation.status, "geometry_sha256": geometry_sha,
                "evaluation_id": evaluation_id, "receipt": receipt_path.relative_to(folder).as_posix(),
                "receipt_sha256": file_digest(receipt_path),
            }
            atomic_json(checkpoint_path, checkpoint)
        result["fragment_evaluations"].append(evaluation.model_dump(mode="json"))
        if evaluation.status != "completed" or evaluation.energy_hartree is None:
            return finish(evaluation.status, "frozen-fragment energy unavailable")
        frozen_energies.append(evaluation.energy_hartree)
        identities.append((evaluation.engine_version, evaluation.metadata.get("executable_sha256")))
    if len(set(identities)) != 1 or identities[0][0] is None or identities[0][1] is None:
        return finish("failed", "all association energies must use the same verified executable/version")
    policy = ("not-applicable-no-atom-centered-basis" if request.engine == "xtb" else
              "engine-composite-gCP" if request.method in {"HF-3c", "r2SCAN-3c", "r²SCAN-3c"} else "not-corrected")
    result["energies"] = association_energies(complex_candidate.molecule, complex_candidate.energy_hartree,
                                             frozen_energies, relaxed_energies,
                                             comparison_protocol={"method": request.method_spec.model_dump(mode="json"),
                                                                  "engine_version": identities[0][0],
                                                                  "executable_sha256": identities[0][1]},
                                             bsse_policy=policy)
    return finish("completed")
