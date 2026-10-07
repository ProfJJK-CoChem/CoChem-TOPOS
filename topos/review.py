"""Auditable human decisions and immutable, explicitly acknowledged ensembles."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .storage import IntegrityError, RunStore, atomic_json, digest_json, json_bytes, read_json

REVIEW_SCHEMA = "topos-review/0.1.0"
ENSEMBLE_SCHEMA = "topos-ensemble/0.1.0"
DECISIONS = {"accept", "reject", "annotate", "needs-review", "withdraw"}
HANDOFF_SCHEMA = "topos-torq-handoff/0.1.0"
CONSUMER_RECEIPT_SCHEMA = "topos-torq-consumption/0.1.0"


def _nonempty(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError(f"{field} must be a nonempty string")
    return value.strip()


def _decision_chain(store: RunStore) -> tuple[list[dict[str, Any]], str | None]:
    pointer = store.run_dir / "review" / "HEAD.json"
    if not pointer.exists():
        return [], None
    head = read_json(pointer)
    digest = head.get("sha256")
    original = digest
    decisions = []
    seen = set()
    while digest:
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise IntegrityError("Invalid review digest")
        if digest in seen:
            raise IntegrityError("Review ledger contains a cycle")
        seen.add(digest)
        entry = read_json(store.run_dir / "review" / "events" / f"{digest}.json")
        if digest_json(entry) != digest or entry.get("schema_version") != REVIEW_SCHEMA:
            raise IntegrityError("Review ledger checksum/schema mismatch")
        decisions.append(entry)
        digest = entry.get("previous_sha256")
    decisions.reverse()
    for number, entry in enumerate(decisions, 1):
        if entry.get("sequence") != number:
            raise IntegrityError("Review ledger sequence mismatch")
    return decisions, original


def list_decisions(run_dir: str | Path) -> list[dict[str, Any]]:
    store = RunStore(run_dir)
    store.verify()
    return _decision_chain(store)[0]


def append_decision(
    run_dir: str | Path, *, subject_id: str, action: str, actor: str,
    reason: str, supersedes: str | None = None, scope: str = "candidate",
    annotations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a hash-linked decision; actor is attribution, not authentication."""
    actor = _nonempty(actor, "actor")
    reason = _nonempty(reason, "reason")
    scope = _nonempty(scope, "scope")
    if annotations is not None and not isinstance(annotations, Mapping):
        raise IntegrityError("Review annotations must be a JSON mapping")
    annotation_data = dict(annotations or {})
    json_bytes(annotation_data)
    if action not in DECISIONS:
        raise IntegrityError(f"Unsupported review action: {action}")
    store = RunStore(run_dir)
    with store.lock:
        record = store.load()
        snapshot = store.verify()
        if subject_id not in {c["candidate_id"] for c in record["candidates"]}:
            raise IntegrityError("Review subject is not a candidate in this run")
        decisions, previous_hash = _decision_chain(store)
        previous = [d for d in decisions if d["subject_id"] == subject_id]
        if previous:
            if supersedes != previous[-1]["decision_id"]:
                raise IntegrityError("A new decision must explicitly supersede the latest subject decision")
        elif supersedes is not None:
            raise IntegrityError("Cannot supersede a nonexistent decision")
        entry = {
            "schema_version": REVIEW_SCHEMA, "run_id": record["run_id"],
            "decision_id": f"decision_{uuid4().hex}", "sequence": len(decisions) + 1,
            "subject_id": subject_id, "action": action, "actor": actor, "reason": reason,
            "supersedes": supersedes, "previous_sha256": previous_hash,
            "source_snapshot_sha256": snapshot["snapshot_id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scope": scope, "annotations": annotation_data,
        }
        digest = digest_json(entry)
        atomic_json(store.run_dir / "review" / "events" / f"{digest}.json", entry)
        atomic_json(store.run_dir / "review" / "HEAD.json", {"sha256": digest})
        return entry


def validate_scientific_candidate(
    record: Mapping[str, Any], candidate: Mapping[str, Any],
) -> dict[str, Any]:
    attempts = {a["attempt_id"]: a for a in record["attempts"]}
    if candidate.get("status") in {
        "rejected", "failed", "partial", "unavailable", "unsupported", "cancelled", "timed-out",
        "duplicate",
    }:
        raise IntegrityError("A scientifically rejected or incomplete candidate cannot be promoted")
    attempt = attempts.get(candidate.get("attempt_id"))
    if attempt is None:
        raise IntegrityError(f"Candidate {candidate['candidate_id']} has no calculation attempt")
    if attempt.get("status") != "completed" or attempt.get("converged") is not True:
        raise IntegrityError("Selected candidate lacks a completed converged calculation")
    if attempt.get("validation_status") != "validated-for-protocol":
        raise IntegrityError("Selected calculation is not validated for its protocol")
    if attempt.get("metadata", {}).get("execution_kind") != "real":
        raise IntegrityError("Demonstration or unspecified execution cannot enter scientific export")
    if not attempt.get("command") or not attempt.get("engine_version"):
        raise IntegrityError("Real calculation requires recorded command and engine version")
    if not any(a.get("role") in {"raw-output", "stdout", "engine-output"} for a in attempt["artifacts"]):
        raise IntegrityError("Real calculation requires verified raw output membership")
    if not candidate.get("comparison_protocol"):
        raise IntegrityError("Selected candidate lacks a comparison protocol")
    metadata = attempt.get("metadata", {})
    if metadata.get("output_molecule") != candidate.get("molecule"):
        raise IntegrityError("Candidate geometry differs from its recorded calculation output")
    if metadata.get("comparison_protocol") != candidate["comparison_protocol"]:
        raise IntegrityError("Candidate comparison protocol differs from its source attempt")
    for field, quantity_name in (("energy_hartree", "electronic_energy"), ("gibbs_hartree", "gibbs_energy")):
        value = candidate.get(field)
        if value is None:
            continue
        matches = [q for q in attempt.get("quantities", []) if q.get("name") == quantity_name]
        if len(matches) != 1:
            raise IntegrityError(f"Candidate {field} requires one matching source quantity")
        quantity = matches[0]
        if (quantity.get("value") != value or quantity.get("units") not in {"hartree", "Eh"}
                or quantity.get("attempt_id") != attempt["attempt_id"]
                or quantity.get("geometry_id") != candidate["candidate_id"]
                or quantity.get("method") != attempt["method"]
                or quantity.get("validity") != "validated-for-protocol"):
            raise IntegrityError(f"Candidate {field} differs from its validated source quantity")
    if metadata.get("result_kind") == "derived-optimization":
        accepted_id = metadata.get("accepted_derivative_attempt_id")
        accepted = attempts.get(accepted_id)
        derivative_ids = metadata.get("derivative_attempt_ids", [])
        if not accepted or accepted_id not in derivative_ids or any(i not in attempts for i in derivative_ids):
            raise IntegrityError("Derived optimizer has missing derivative attempt provenance")
        if (accepted.get("status") != "completed" or accepted.get("converged") is not True
                or accepted.get("validation_status") != "validated-for-protocol"
                or accepted.get("metadata", {}).get("execution_kind") != "real"
                or accepted.get("metadata", {}).get("result_kind") == "derived-optimization"
                or not accepted.get("command") or not accepted.get("engine_version")
                or not any(a.get("role") in {"raw-output", "stdout", "engine-output"}
                           for a in accepted.get("artifacts", []))
                or accepted.get("metadata", {}).get("output_molecule") != candidate["molecule"]
                or any(accepted.get(k) != attempt.get(k) for k in ("engine", "method", "engine_version"))):
            raise IntegrityError("Derived optimizer does not match an authentic accepted derivative evaluation")
        source_energy = [q for q in accepted.get("quantities", []) if q.get("name") == "electronic_energy"]
        if (len(source_energy) != 1 or source_energy[0].get("value") != candidate.get("energy_hartree")
                or source_energy[0].get("units") not in {"hartree", "Eh"}
                or source_energy[0].get("validity") != "validated-for-protocol"):
            raise IntegrityError("Derived optimizer energy differs from its accepted derivative evaluation")
    if metadata.get("result_kind") == "physical-hessian-thermochemistry":
        try:
            _validate_physical_hessian(record, candidate, attempt, attempts)
        except IntegrityError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityError("Incomplete or invalid physical-Hessian provenance") from exc
    if metadata.get("result_kind") == "native-analytic-hessian":
        try:
            _validate_native_hessian(record, candidate, attempt)
        except IntegrityError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityError("Incomplete or invalid native analytic-Hessian provenance") from exc
    if metadata.get("result_kind") == "derived-association":
        try:
            _validate_association(record, candidate, attempt, attempts)
        except IntegrityError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityError("Incomplete or invalid balanced-association provenance") from exc
    return dict(attempt)


def _validate_native_hessian(record, candidate, attempt) -> None:
    """Require a physical native Hessian and a separate real stationarity job."""
    import numpy as np

    from .models import Molecule
    from .science import harmonic_analysis, validate_derivatives
    from .thermochemistry import rrho_thermochemistry

    metadata = attempt["metadata"]
    reference = metadata["reference_gradient_result"]
    molecule = Molecule.model_validate(candidate["molecule"])
    if (metadata.get("derivative_kind") != "native-analytic-SCF-Hessian"
            or reference.get("status") != "completed" or reference.get("converged") is not True
            or reference.get("operation") != "gradient" or not reference.get("command")
            or reference.get("metadata", {}).get("execution_kind") != "real"
            or reference.get("molecule") != candidate["molecule"]
            or any(reference.get(key) != attempt.get(key) for key in ("engine", "method", "engine_version"))
            or reference.get("energy_hartree") != candidate.get("energy_hartree")):
        raise IntegrityError("Native Hessian lacks an authentic matching gradient/energy reference")
    inventory = {a["sha256"] for a in attempt["artifacts"]}
    if (not reference.get("artifacts") or any(a["sha256"] not in inventory for a in reference["artifacts"])
            or not any(Path(a["path"]).suffix == ".hess" for a in attempt["artifacts"])):
        raise IntegrityError("Native Hessian and reference raw artifacts must belong to the calculation")
    protocol = metadata["protocol"]
    if (protocol.get("molecule") != candidate["molecule"]
            or protocol.get("executable_sha256") != metadata.get("executable_sha256")
            or reference.get("metadata", {}).get("executable_sha256") != metadata.get("executable_sha256")):
        raise IntegrityError("Native Hessian and reference require the same geometry and executable")
    threshold = protocol.get("gradient_threshold")
    if not isinstance(threshold, (int, float)) or not 0 < threshold <= 1e-5:
        raise IntegrityError("Native minimum requires a declared strict stationarity threshold")
    hessian = metadata["hessian_hartree_per_bohr2"]
    gradient = reference["gradient_hartree_per_bohr"]
    validate_derivatives(gradient, hessian, natoms=len(molecule.symbols))
    reported = [q for q in attempt["quantities"] if q.get("name") == "cartesian_hessian"]
    if (len(reported) != 1 or reported[0].get("units") != "hartree/bohr^2"
            or reported[0].get("attempt_id") != attempt["attempt_id"]
            or reported[0].get("validity") != "validated-for-protocol"
            or not np.allclose(reported[0]["value"], hessian, rtol=1e-12, atol=1e-14)):
        raise IntegrityError("Native Hessian quantity differs from the recorded physical derivative")
    analysis = harmonic_analysis(molecule, hessian, gradient_hartree_per_bohr=gradient,
                                 gradient_threshold=threshold)
    stored = metadata["analysis"]
    if (analysis["validity"] != "harmonic-minimum-within-thresholds"
            or stored.get("validity") != analysis["validity"]
            or not np.allclose(stored.get("frequencies_cm1", []), analysis["frequencies_cm1"], rtol=1e-9, atol=1e-7)):
        raise IntegrityError("Native Hessian does not establish a reproducible harmonic minimum")
    if candidate.get("gibbs_hartree") is not None:
        thermal = metadata["thermochemistry"]
        options = record["request"]["thermochemistry_options"]
        recalculated = rrho_thermochemistry(
            molecule, reference["energy_hartree"], analysis, temperature_k=record["request"]["temperature_k"],
            pressure_pa=options["pressure_pa"], concentration_mol_l=options["concentration_mol_l"],
            symmetry_number=thermal["symmetry_number"], frequency_scale=options["frequency_scale"],
            low_frequency_policy=options["low_frequency_policy"], cutoff_cm1=options["cutoff_cm1"],
        )
        if not np.isclose(recalculated["gibbs_hartree"], candidate["gibbs_hartree"], rtol=0, atol=1e-12):
            raise IntegrityError("Gibbs energy does not reproduce from the native Hessian")
        for name in ("zpe_hartree", "thermal_enthalpy_correction_hartree", "entropy_hartree_per_k",
                     "standard_state_correction_hartree", "gibbs_hartree"):
            if not np.isclose(recalculated[name], thermal[name], rtol=0, atol=1e-12):
                raise IntegrityError("Native-Hessian thermal components do not reproduce")
        if candidate.get("metadata", {}).get("thermochemistry") != thermal:
            raise IntegrityError("Candidate thermal components differ from the native Hessian attempt")


def _validate_association(record, candidate, attempt, attempts) -> None:
    """Recompute interaction/binding from actual source-complex/monomer jobs."""
    from .fragments import _matching_fragment, association_energies, split_fragments
    from .models import Molecule
    from .science import geometry_digest

    metadata = attempt["metadata"]
    source = attempts.get(metadata.get("source_complex_attempt_id"))
    if (source is None or source["attempt_id"] == attempt["attempt_id"]
            or source.get("metadata", {}).get("result_kind") == "derived-association"):
        raise IntegrityError("Association requires its separate genuine complex source attempt")
    source_candidate = {**candidate, "attempt_id": source["attempt_id"],
                        "candidate_id": metadata["source_complex_candidate_id"]}
    validate_scientific_candidate(record, source_candidate)
    claimed = metadata["association"]
    protocol = claimed["comparison_protocol"]
    executable_sha = protocol.get("executable_sha256")
    if not isinstance(executable_sha, str) or len(executable_sha) != 64:
        raise IntegrityError("Association common method requires the actual executable fingerprint")
    native_source = source
    if source.get("metadata", {}).get("result_kind") == "derived-optimization":
        native_source = attempts[source["metadata"]["accepted_derivative_attempt_id"]]
    if native_source.get("metadata", {}).get("executable_sha256") != executable_sha:
        raise IntegrityError("Association complex executable differs from the common electronic protocol")
    molecule = Molecule.model_validate(candidate["molecule"])
    fragments = split_fragments(molecule)
    monomer_ids = metadata.get("monomer_reference_attempt_ids", [])
    frozen_ids = metadata.get("frozen_fragment_attempt_ids", [])
    identifiers = [*monomer_ids, *frozen_ids]
    if (len(monomer_ids) != len(fragments) or len(frozen_ids) != len(fragments)
            or len(set(identifiers)) != len(identifiers)
            or metadata.get("component_attempt_ids") != identifiers
            or any(identifier not in attempts for identifier in identifiers)):
        raise IntegrityError("Association lacks distinct, balanced monomer/frozen-fragment source jobs")
    energies = []
    for index, identifier in enumerate(identifiers):
        component = attempts[identifier]
        cm = component.get("metadata", {})
        if (component.get("status") != "completed" or component.get("converged") is not True
                or component.get("validation_status") != "validated-for-protocol"
                or cm.get("execution_kind") != "real" or not component.get("command")
                or any(component.get(key) != attempt.get(key) for key in ("engine", "method", "engine_version"))
                or not any(a.get("role") in {"raw-output", "stdout", "engine-output"} for a in component["artifacts"])):
            raise IntegrityError("Association source component is not a validated common-method real calculation")
        if cm.get("executable_sha256") != executable_sha:
            raise IntegrityError("Association component executable differs from the common electronic protocol")
        actual_method = cm.get("requested_method", {})
        requested_method = protocol.get("method", {})
        if any(actual_method.get(key) != requested_method.get(key)
               for key in ("engine", "method", "basis", "auxiliary_basis", "dispersion", "solvent")):
            raise IntegrityError("Association component Hamiltonian differs from the common electronic protocol")
        geometry = Molecule.model_validate(cm["output_molecule"])
        expected = fragments[index % len(fragments)]
        _matching_fragment(expected, geometry)
        if index >= len(fragments) and geometry_digest(geometry) != geometry_digest(expected):
            raise IntegrityError("Frozen-fragment source geometry does not match the selected complex")
        quantity = [q for q in component["quantities"] if q.get("name") == "electronic_energy"]
        if (len(quantity) != 1 or quantity[0].get("units") not in {"hartree", "Eh"}
                or quantity[0].get("validity") != "validated-for-protocol"
                or quantity[0].get("attempt_id") != identifier
                or quantity[0].get("method") != component["method"]):
            raise IntegrityError("Association component lacks one attributable electronic energy")
        energies.append(quantity[0]["value"])
    computed = association_energies(molecule, candidate["energy_hartree"], energies[len(fragments):],
                                    energies[:len(fragments)], comparison_protocol=claimed["comparison_protocol"],
                                    bsse_policy=claimed["bsse_policy"])
    if computed != claimed or candidate.get("metadata", {}).get("association") != computed:
        raise IntegrityError("Association quantities differ from their balanced real calculation sources")
    for name in ("electronic_interaction_hartree", "electronic_binding_hartree", "fragment_deformation_hartree"):
        matches = [q for q in attempt["quantities"] if q.get("name") == name.removesuffix("_hartree")]
        if (len(matches) != 1 or matches[0].get("value") != computed[name]
                or matches[0].get("units") not in {"hartree", "Eh"}
                or matches[0].get("attempt_id") != attempt["attempt_id"]
                or matches[0].get("geometry_id") != candidate["candidate_id"]
                or matches[0].get("validity") != "validated-for-protocol"):
            raise IntegrityError("Association source quantity lacks valid balanced attribution")
    if not any(a.get("role") == "derived-output" and a.get("sha256") == metadata.get("association_result_sha256")
               for a in attempt["artifacts"]):
        raise IntegrityError("Association requires its checksummed derivation artifact")


def _validate_physical_hessian(record, candidate, attempt, attempts) -> None:
    """Reconstruct the reported physical Hessian from authentic derivative attempts."""
    import numpy as np

    from .models import Molecule
    from .science import BOHR_ANGSTROM, harmonic_analysis, validate_derivatives
    from .thermochemistry import rrho_thermochemistry

    metadata = attempt["metadata"]
    molecule = Molecule.model_validate(candidate["molecule"])
    natoms = len(molecule.symbols)
    identifiers = metadata.get("derivative_attempt_ids", [])
    if (len(identifiers) != 1 + 6 * natoms or len(set(identifiers)) != len(identifiers)
            or metadata.get("accepted_derivative_attempt_id") != identifiers[0]
            or any(identifier not in attempts for identifier in identifiers)):
        raise IntegrityError("Physical Hessian requires the reference and all distinct paired derivative attempts")
    evidence = [a for a in attempt["artifacts"] if a.get("role") == "derived-output"
                and a.get("sha256") == metadata.get("derived_result_sha256")]
    if len(evidence) != 1:
        raise IntegrityError("Physical Hessian requires one checksummed derived-result artifact")
    gradients = []
    energies = []
    step = record["request"]["thermochemistry_options"]["step_bohr"]
    for index, identifier in enumerate(identifiers):
        source = attempts[identifier]
        source_metadata = source.get("metadata", {})
        if (source.get("status") != "completed" or source.get("converged") is not True
                or source.get("validation_status") != "validated-for-protocol"
                or source_metadata.get("execution_kind") != "real"
                or source_metadata.get("operation") != "gradient"
                or source_metadata.get("result_kind") in {"derived-optimization", "physical-hessian-thermochemistry"}
                or not source.get("command")
                or any(source.get(key) != attempt.get(key) for key in ("engine", "method", "engine_version"))
                or not any(a.get("role") in {"raw-output", "stdout", "engine-output"}
                           for a in source.get("artifacts", []))):
            raise IntegrityError("Physical Hessian contains an unauthentic or incompatible derivative evaluation")
        expected = molecule.model_dump(mode="json")
        if index:
            xyz = np.asarray(expected["coordinates"], dtype=float)
            xyz.flat[(index - 1) // 2] += (1 if index % 2 else -1) * step * BOHR_ANGSTROM
            expected["coordinates"] = xyz.tolist()
        if source_metadata.get("output_molecule") != expected:
            raise IntegrityError("Physical Hessian derivative geometry differs from its displacement")
        gradient = [q for q in source.get("quantities", []) if q.get("name") == "cartesian_gradient"]
        energy = [q for q in source.get("quantities", []) if q.get("name") == "electronic_energy"]
        if (len(gradient) != 1 or len(energy) != 1 or gradient[0].get("units") != "hartree/bohr"
                or energy[0].get("units") not in {"hartree", "Eh"}
                or any(q.get("attempt_id") != identifier or q.get("method") != source["method"]
                       or q.get("validity") != "validated-for-protocol" for q in [*gradient, *energy])):
            raise IntegrityError("Physical Hessian derivative lacks correctly attributed gradient/energy quantities")
        validate_derivatives(gradient=gradient[0]["value"], natoms=natoms)
        gradients.append(np.asarray(gradient[0]["value"], dtype=float))
        energies.append(energy[0]["value"])
    if energies[0] != candidate.get("energy_hartree"):
        raise IntegrityError("Physical Hessian reference energy differs from selected candidate")
    columns = [(gradients[1 + 2 * column].ravel() - gradients[2 + 2 * column].ravel()) / (2 * step)
               for column in range(3 * natoms)]
    hessian = np.asarray(columns).T
    hessian = (hessian + hessian.T) / 2
    reported = [q for q in attempt["quantities"] if q.get("name") == "cartesian_hessian"]
    if (len(reported) != 1 or reported[0].get("units") != "hartree/bohr^2"
            or not np.allclose(reported[0]["value"], hessian, rtol=1e-10, atol=1e-12)):
        raise IntegrityError("Reported physical Hessian does not reproduce from its derivative attempts")
    analysis = harmonic_analysis(molecule, hessian, gradient_hartree_per_bohr=gradients[0])
    stored = metadata.get("analysis", {})
    if (analysis["validity"] != "harmonic-minimum-within-thresholds"
            or stored.get("validity") != analysis["validity"]
            or not np.allclose(stored.get("frequencies_cm1", []), analysis["frequencies_cm1"], rtol=1e-9, atol=1e-7)):
        raise IntegrityError("Physical Hessian lacks a reproducible harmonic-minimum classification")
    thermal = metadata.get("thermochemistry")
    if candidate.get("gibbs_hartree") is not None:
        if not isinstance(thermal, Mapping):
            raise IntegrityError("Gibbs energy requires a declared thermal model")
        options = record["request"]["thermochemistry_options"]
        recalculated = rrho_thermochemistry(
            molecule, energies[0], analysis, temperature_k=record["request"]["temperature_k"],
            pressure_pa=options["pressure_pa"], concentration_mol_l=options["concentration_mol_l"],
            symmetry_number=thermal["symmetry_number"], frequency_scale=options["frequency_scale"],
            low_frequency_policy=options["low_frequency_policy"], cutoff_cm1=options["cutoff_cm1"],
        )
        if not np.isclose(recalculated["gibbs_hartree"], candidate["gibbs_hartree"], rtol=0, atol=1e-12):
            raise IntegrityError("Gibbs energy does not reproduce from the recorded Hessian and thermal model")
        for name in ("zpe_hartree", "thermal_enthalpy_correction_hartree", "entropy_hartree_per_k",
                     "standard_state_correction_hartree", "gibbs_hartree"):
            if not np.isclose(recalculated[name], thermal[name], rtol=0, atol=1e-12):
                raise IntegrityError("Thermal components do not reproduce from the recorded physical model")
        if candidate.get("metadata", {}).get("thermochemistry") != thermal:
            raise IntegrityError("Candidate thermal components differ from the derived attempt")


def create_ensemble_manifest(
    run_dir: str | Path, member_ids: Sequence[str], *, actor: str, reason: str = "",
    expected_snapshot_sha256: str | None = None,
) -> dict[str, Any]:
    actor = _nonempty(actor, "actor")
    if not member_ids or len(set(member_ids)) != len(member_ids):
        raise IntegrityError("Ensemble requires unique explicitly selected candidate IDs")
    store = RunStore(run_dir)
    with store.lock:
        record = store.load()
        snapshot = store.verify()
        snapshot_hash = snapshot["snapshot_id"]
        if expected_snapshot_sha256 is not None and expected_snapshot_sha256 != snapshot_hash:
            raise IntegrityError("Run changed since ensemble review")
        decisions, review_hash = _decision_chain(store)
        latest = {d["subject_id"]: d for d in decisions}
        candidates = {c["candidate_id"]: c for c in record["candidates"]}
        members = []
        for member_id in sorted(member_ids):
            if member_id not in candidates:
                raise IntegrityError(f"Unknown ensemble member: {member_id}")
            decision = latest.get(member_id)
            if not decision or decision["action"] != "accept":
                raise IntegrityError(f"Candidate needs explicit accepted review: {member_id}")
            if decision["source_snapshot_sha256"] != snapshot_hash:
                raise IntegrityError("Candidate decision belongs to a stale run snapshot")
            candidate = candidates[member_id]
            if candidate.get("metadata", {}).get("duplicate_of") in member_ids:
                raise IntegrityError("A duplicate observation cannot also be a separate ensemble member")
            validate_scientific_candidate(record, candidate)
            members.append(candidate)
        if len({c["comparison_protocol"] for c in members}) != 1:
            raise IntegrityError("Selected ensemble mixes incompatible comparison protocols")
        body = {
            "schema_version": ENSEMBLE_SCHEMA, "run_id": record["run_id"],
            "source_snapshot_sha256": snapshot_hash,
            "source_record_sha256": snapshot["record_sha256"],
            "review_head_sha256": review_hash, "actor": actor, "reason": reason,
            "members": members, "member_ids": sorted(member_ids),
            "comparison_protocol": members[0]["comparison_protocol"],
            "decisions": [latest[i]["decision_id"] for i in sorted(member_ids)],
            "limitations": record.get("metadata", {}).get("limitations", []),
        }
        digest = digest_json(body)
        manifest = {**body, "manifest_sha256": digest}
        path = store.run_dir / "ensembles" / f"{digest}.json"
        if path.exists() and read_json(path) != manifest:
            raise IntegrityError("Existing ensemble digest has different content")
        if not path.exists():
            atomic_json(path, manifest)
        atomic_json(store.run_dir / "ensembles" / "CURRENT.json", {"sha256": digest})
        return manifest


def get_ensemble_manifest(
    run_dir: str | Path, *, digest: str | None = None,
) -> dict[str, Any]:
    store = RunStore(run_dir)
    snapshot = store.verify()
    current = read_json(store.run_dir / "ensembles" / "CURRENT.json").get("sha256")
    selected = current if digest is None else digest
    if selected != current:
        raise IntegrityError("Ensemble version is stale")
    if not isinstance(selected, str) or len(selected) != 64 or any(c not in "0123456789abcdef" for c in selected):
        raise IntegrityError("Invalid ensemble digest")
    manifest = read_json(store.run_dir / "ensembles" / f"{selected}.json")
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if digest_json(body) != selected or manifest.get("manifest_sha256") != selected:
        raise IntegrityError("Ensemble checksum mismatch")
    if manifest.get("schema_version") != ENSEMBLE_SCHEMA:
        raise IntegrityError("Unsupported ensemble schema")
    if manifest.get("run_id") != snapshot["run_id"]:
        raise IntegrityError("Ensemble belongs to another run")
    if manifest.get("source_snapshot_sha256") != snapshot["snapshot_id"]:
        raise IntegrityError("Ensemble references a stale run snapshot")
    if manifest.get("review_head_sha256") != _decision_chain(store)[1]:
        raise IntegrityError("Ensemble references superseded review decisions")
    return manifest


def acknowledge_torq(
    run_dir: str | Path, manifest_sha256: str, *, actor: str,
    schema_version: str = ENSEMBLE_SCHEMA,
) -> dict[str, Any]:
    actor = _nonempty(actor, "actor")
    if schema_version != ENSEMBLE_SCHEMA:
        raise IntegrityError("TORQ cannot acknowledge an incompatible ensemble schema")
    store = RunStore(run_dir)
    with store.lock:
        manifest = get_ensemble_manifest(run_dir, digest=manifest_sha256)
        acknowledgment = {
            "schema_version": "topos-torq-ack/0.1.0", "run_id": manifest["run_id"],
            "ensemble_schema": schema_version, "manifest_sha256": manifest_sha256,
            "actor": actor, "status": "acknowledged", "scope": "manifest-receipt-only",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        path = store.run_dir / "acknowledgments" / f"{digest_json(acknowledgment)}.json"
        atomic_json(path, acknowledgment)
        return acknowledgment


def review_basket(run_dir: str | Path) -> dict[str, Any]:
    """Expose original observations beside decisions, without rewriting chemistry."""
    store = RunStore(run_dir)
    with store.lock:
        record = store.load()
        snapshot = store.verify()
        decisions, head = _decision_chain(store)
        latest = {decision["subject_id"]: decision for decision in decisions}
        items = []
        for candidate in record["candidates"]:
            try:
                validate_scientific_candidate(record, candidate)
                eligibility = {"eligible": True, "reason": None}
            except IntegrityError as exc:
                eligibility = {"eligible": False, "reason": str(exc)}
            items.append({"candidate": candidate, "eligibility": eligibility,
                          "decision": latest.get(candidate["candidate_id"]),
                          "unresolved": candidate.get("metadata", {}).get("unresolved", []),
                          "history": [d for d in decisions if d["subject_id"] == candidate["candidate_id"]]})
        return {"run_id": record["run_id"], "source_snapshot_sha256": snapshot["snapshot_id"],
                "review_head_sha256": head, "items": items,
                "limitations": record.get("metadata", {}).get("limitations", [])}


def _handoff_body(record: Mapping[str, Any], ensemble: Mapping[str, Any],
                  decisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    members = []
    for candidate in ensemble["members"]:
        attempt = validate_scientific_candidate(record, candidate)
        members.append({
            "member_id": candidate["candidate_id"],
            "geometry_sha256": digest_json(candidate["molecule"]),
            "molecule": candidate["molecule"], "candidate": candidate,
            "attempt_id": attempt["attempt_id"],
            "comparison_protocol": candidate["comparison_protocol"],
            "uncertainty": candidate.get("metadata", {}).get("uncertainty"),
            "unresolved": candidate.get("metadata", {}).get("unresolved", []),
        })
    return {
        "schema_version": HANDOFF_SCHEMA, "run_id": record["run_id"],
        "ensemble_schema": ENSEMBLE_SCHEMA,
        "ensemble_sha256": ensemble["manifest_sha256"],
        "source_snapshot_sha256": ensemble["source_snapshot_sha256"],
        "source_record_sha256": digest_json(record),
        "record": record, "ensemble": ensemble, "review": list(decisions),
        "members": members, "request": record["request"],
        "scope": "reviewed-geometry-ensemble",
        "raw_artifact_access": "Inventory in record; obtain the verified research bundle for raw files",
        "consumer_status": "awaiting-external-consumption",
        "limitations": [*ensemble.get("limitations", []),
                        "Search provenance does not establish exhaustive sampling; TORQ may require further sampling"],
    }


def export_torq_handoff(run_dir: str | Path, destination: str | Path, *,
                        ensemble_sha256: str | None = None) -> dict[str, Any]:
    """Publish a portable strict producer contract; this does not execute TORQ."""
    from filelock import FileLock

    store = RunStore(run_dir)
    target = Path(destination).absolute()
    if target.is_symlink() or target == store.run_dir or store.run_dir in target.parents:
        raise IntegrityError("Handoff must be an external regular file, outside the live run")
    target.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(target.parent / f".{target.name}.lock"), timeout=10), store.lock:
        if target.exists():
            raise FileExistsError(f"Immutable handoff already exists: {target}")
        record = store.load()
        ensemble = get_ensemble_manifest(run_dir, digest=ensemble_sha256)
        body = _handoff_body(record, ensemble, _decision_chain(store)[0])
        handoff = {**body, "handoff_sha256": digest_json(body)}
        # Keep exactly what was transmitted for a later externally produced receipt.
        atomic_json(store.run_dir / "handoffs" / f"{handoff['handoff_sha256']}.json", handoff)
        atomic_json(target, handoff)
        return handoff


def verify_torq_handoff(path: str | Path) -> dict[str, Any]:
    """Validate schema, member geometry, source record and review without TOPOS state.

    This verifies content integrity, not sender identity or the chemistry of an
    untrusted engine. A consumer must also enforce its own capability/physics checks.
    """
    from .storage import record_dict

    source = Path(path)
    if source.is_symlink():
        raise IntegrityError("Handoff cannot be a symlink")
    handoff = read_json(source)
    if handoff.get("schema_version") != HANDOFF_SCHEMA:
        raise IntegrityError("Incompatible TOPOS/TORQ handoff schema")
    body = {key: value for key, value in handoff.items() if key != "handoff_sha256"}
    if digest_json(body) != handoff.get("handoff_sha256"):
        raise IntegrityError("Handoff checksum mismatch")
    try:
        record = record_dict(handoff["record"])
        ensemble = handoff["ensemble"]
        ensemble_body = {key: value for key, value in ensemble.items() if key != "manifest_sha256"}
        if (ensemble.get("schema_version") != ENSEMBLE_SCHEMA
                or digest_json(ensemble_body) != ensemble.get("manifest_sha256")
                or ensemble.get("source_record_sha256") != digest_json(record)
                or ensemble.get("run_id") != record["run_id"]):
            raise IntegrityError("Handoff ensemble/record identity mismatch")
        candidates = {c["candidate_id"]: c for c in record["candidates"]}
        member_ids = ensemble["member_ids"]
        if not member_ids or len(set(member_ids)) != len(member_ids):
            raise IntegrityError("Handoff needs unique nonempty members")
        if ensemble["members"] != [candidates[i] for i in member_ids]:
            raise IntegrityError("Handoff members differ from the reviewed record")
        decisions = handoff["review"]
        previous = None
        latest: dict[str, Any] = {}
        for number, decision in enumerate(decisions, 1):
            if (decision.get("schema_version") != REVIEW_SCHEMA or decision.get("sequence") != number
                    or decision.get("previous_sha256") != previous
                    or decision.get("run_id") != record["run_id"]):
                raise IntegrityError("Handoff review chain mismatch")
            previous = digest_json(decision)
            latest[decision["subject_id"]] = decision
        if previous != ensemble["review_head_sha256"]:
            raise IntegrityError("Handoff review digest mismatch")
        if ensemble["decisions"] != [latest[i]["decision_id"] for i in member_ids]:
            raise IntegrityError("Handoff selected decisions mismatch")
        for member_id in member_ids:
            decision = latest[member_id]
            if (decision["action"] != "accept"
                    or decision["source_snapshot_sha256"] != ensemble["source_snapshot_sha256"]):
                raise IntegrityError("Handoff includes unaccepted or stale member")
        if len({c["comparison_protocol"] for c in ensemble["members"]}) != 1:
            raise IntegrityError("Handoff has incompatible comparison protocols")
        if ensemble["comparison_protocol"] != ensemble["members"][0]["comparison_protocol"]:
            raise IntegrityError("Handoff ensemble comparison protocol mismatch")
        if any(c.get("metadata", {}).get("duplicate_of") in member_ids for c in ensemble["members"]):
            raise IntegrityError("Handoff cannot promote duplicate observations as independent members")
        if _handoff_body(record, ensemble, decisions) != body:
            raise IntegrityError("Handoff geometry/protocol/source identity mismatch")
    except (KeyError, TypeError, IndexError) as exc:
        raise IntegrityError("Incomplete TOPOS/TORQ handoff") from exc
    return handoff


def accept_torq_receipt(run_dir: str | Path, receipt_path: str | Path) -> dict[str, Any]:
    """Record an external consumer's declaration bound to the exact current handoff.

    TOPOS never fabricates this receipt. A receipt establishes a declared import,
    not a successful TORQ calculation, consumer authentication or completed sampling.
    """
    receipt = read_json(Path(receipt_path))
    fields = {"schema_version", "run_id", "ensemble_schema", "ensemble_sha256", "handoff_sha256",
              "members", "consumer", "consumed_at", "status", "receipt_sha256"}
    if set(receipt) != fields or receipt.get("schema_version") != CONSUMER_RECEIPT_SCHEMA:
        raise IntegrityError("Incompatible or incomplete TORQ consumption receipt")
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if digest_json(body) != receipt.get("receipt_sha256"):
        raise IntegrityError("TORQ receipt checksum mismatch")
    if receipt.get("status") != "consumed" or receipt.get("ensemble_schema") != ENSEMBLE_SCHEMA:
        raise IntegrityError("TORQ must declare consumption of the compatible ensemble schema")
    consumer = receipt["consumer"]
    if not isinstance(consumer, dict) or set(consumer) != {"name", "version"}:
        raise IntegrityError("TORQ consumer must provide name and version")
    if consumer.get("name") != "CoChem-TORQ":
        raise IntegrityError("Receipt consumer must identify CoChem-TORQ")
    _nonempty(consumer.get("version"), "consumer version")
    try:
        timestamp = datetime.fromisoformat(receipt["consumed_at"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("timezone missing")
    except (AttributeError, TypeError, ValueError) as exc:
        raise IntegrityError("TORQ receipt needs an ISO 8601 timestamp with timezone") from exc
    digest = receipt["handoff_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise IntegrityError("Invalid handoff digest")
    store = RunStore(run_dir)
    with store.lock:
        ensemble = get_ensemble_manifest(run_dir, digest=receipt["ensemble_sha256"])
        handoff = verify_torq_handoff(store.run_dir / "handoffs" / f"{digest}.json")
        expected = [{"member_id": member["member_id"], "geometry_sha256": member["geometry_sha256"]}
                    for member in handoff["members"]]
        if (receipt["run_id"] != ensemble["run_id"] or receipt["members"] != expected
                or handoff["ensemble_sha256"] != ensemble["manifest_sha256"]):
            raise IntegrityError("TORQ receipt does not match the exact current ensemble and members")
        atomic_json(store.run_dir / "consumer-receipts" / f"{receipt['receipt_sha256']}.json", receipt)
    return receipt
