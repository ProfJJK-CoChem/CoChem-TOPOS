"""Recompute frozen-geometry Boys–Bernardi interaction from immutable native legs.

This offline importer requires no licensed executable. It verifies the retained
bytes and BASE export receipts, not the authorship of arbitrary untrusted data.
It supplies no literature value, accuracy tolerance, or scientific release pass.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .counterpoise import CP_SCHEMA, counterpoise_plan
from .engines import EngineResult, _engine_version, _orca_input
from .method_matrix import MATRIX_REVISION, resolve_row, resolved_recipe
from .models import MethodSpec, Molecule, ResourceLimits, RunRecord
from .science import counterpoise_interaction, geometry_digest
from .storage import IntegrityError, RunStore, artifact_inventory, confined_file, digest_json

CP_DEFINITION = ("counterpoise-corrected electronic interaction energy at the predeclared frozen "
                 "complex geometry; no relaxation, ZPE or thermal corrections")
ROLES = ("complex-in-complex-basis", "fragment-0-in-own-basis",
         "fragment-0-in-complex-basis", "fragment-1-in-own-basis", "fragment-1-in-complex-basis")


def _require(condition, message):
    if not condition:
        raise IntegrityError(message)


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _member(original, inventory, snapshot):
    """Bind a native locator to one immutable member without rewriting metadata."""
    matches = [a for a in inventory if Path(a["path"]).parts[-2:] == Path(original["path"]).parts[-2:]
               and (a["sha256"], a["size_bytes"], a["role"])
               == (original["sha256"], original["size_bytes"], original["role"])]
    _require(len(matches) == 1, "Native CP artifact lacks a unique immutable attempt member")
    member = matches[0]
    return member, confined_file(snapshot, "artifacts/" + member["path"])


def _method(case, actual):
    if case.request.purpose == "matrix":
        _require(case.request.matrix_row_id == "T5-1h" and case.request.matrix_revision == MATRIX_REVISION,
                 "Ordinary CP references require the exact reviewed T5-1h matrix route")
        steps, _ = resolved_recipe(resolve_row("T5-1h"))
        _require(len(steps) == 1 and steps[0].operation == "counterpoise",
                 "The current reviewed row no longer defines ordinary counterpoise")
        expected = MethodSpec(engine=steps[0].engine, method=steps[0].method, basis=steps[0].basis,
                              auxiliary_basis="def2/J", purpose="energy", engine_version="6.1.1",
                              profile_id="orca-mapping-v4.1")
    else:
        _require(case.request.purpose == "energy", "A standalone CP reference requires a fixed-energy declaration")
        expected = case.request.method_spec
    # The executed operation and exact raw SP deck establish energy-only use;
    # a retained method label's advisory purpose cannot substitute an optimization.
    _require(actual.model_dump(exclude={"purpose"}) == expected.model_dump(exclude={"purpose"}),
             "Native CP Hamiltonian differs from the predeclared tested protocol")


def _basis_receipts(payload, molecule, method, executable_sha256, inventory, snapshot):
    basis, receipts = payload["basis"], payload.get("basis_export_receipts")
    _require(isinstance(receipts, dict) and set(receipts) == set(basis), "CP lacks exact native basis export coverage")
    identity = payload.get("basis_identity", {})
    _require(identity.get("status") == "native-export-verified"
             and identity.get("receipt_sha256") == digest_json(receipts), "CP native basis identity receipt changed")
    distribution, proof = set(), {}
    for kind, receipt in receipts.items():
        name = method.basis if kind == "orbital" else method.auxiliary_basis or "def2/J"
        elements = sorted(set(molecule.symbols))
        command = receipt["command"]
        _require(isinstance(command, list) and command and Path(command[0]).name == "orca_exportbasis",
                 "CP basis authority must be the verified native exporter")
        _require(receipt["schema_version"] == "topos-orca-basis-export/0.1.0"
                 and receipt["authority_kind"] == "verified-ORCA-distribution-utility"
                 and receipt["basis"] == name and receipt["elements"] == elements
                 and receipt["format"] == "GAMESS-US" and receipt["status"] == "completed"
                 and receipt["process"]["status"] == "completed" and receipt["process"]["returncode"] == 0
                 and receipt["process"]["command"] == command
                 and receipt["orca_version"] == "6.1.1" and receipt["orca_sha256"] == executable_sha256
                 and receipt["output_sha256"] == basis[kind]["sha256"]
                 and command == [command[0], "-b", name, "-a", *elements, "-f", "GAMESS-US", "-o",
                                 Path(receipt["output_path"]).name], "CP basis export disagrees with native method or executable")
        hashes = tuple(receipt.get(k) for k in ("archive_sha256", "distribution_manifest_sha256",
                                               "exporter_sha256", "orca_sha256"))
        _require(all(_hash(h) for h in hashes), "CP basis export lacks retained distribution identities")
        distribution.add(hashes)
        folder = "basis-export-evidence-" + digest_json(receipts)
        originals = {a["path"]: a for a in payload["artifacts"]}
        candidates = [a for a in originals.values() if Path(a["path"]).parts[-2:]
                      == (folder, kind + "-receipt.json") and a["role"] == "basis-export-receipt"]
        _require(len(candidates) == 1, "CP basis export receipt is absent from native retained artifacts")
        member, path = _member(candidates[0], inventory, snapshot)
        _require(json.loads(path.read_text()) == receipt, "Retained native basis receipt differs from CP metadata")
        evidence = receipt["evidence"]
        streams = {receipt["process"]["stdout_path"], receipt["process"]["stderr_path"]}
        _require(len(evidence) == 2 and len(streams) == 2 and {a["path"] for a in evidence} == streams,
                 "CP exporter must retain both distinct actual output streams")
        retained = {member["path"]: member["sha256"]}
        for index, stream in enumerate(evidence):
            _require(set(stream) == {"path", "sha256", "bytes"}, "CP exporter stream receipt is malformed")
            candidates = [a for a in originals.values() if Path(a["path"]).parts[-2:]
                          == (folder, f"{kind}-{index}.log") and a["role"] == "basis-export-output"
                          and (a["sha256"], a["size_bytes"]) == (stream["sha256"], stream["bytes"])]
            _require(len(candidates) == 1, "CP exporter output stream is absent or differs from its receipt")
            member, _ = _member(candidates[0], inventory, snapshot)
            retained[member["path"]] = member["sha256"]
        proof[kind] = {"basis_sha256": basis[kind]["sha256"], "receipt_sha256": digest_json(receipt),
                       "retained_artifacts_sha256": retained}
    _require(len(distribution) == 1, "CP orbital and auxiliary exports originate from different distributions")
    return proof


def extract_reference_value(case, record, store: RunStore) -> tuple[float, dict]:
    """Import only full CP electronic interaction at the declared frozen complex."""
    try:
        return _extract(case, record, store)
    except (KeyError, TypeError, IndexError, OSError, ValueError) as exc:
        if isinstance(exc, IntegrityError):
            raise
        raise IntegrityError("Incomplete or invalid native CP reference evidence: " + str(exc)) from exc


def _extract(case, record, store):
    manifest = store.verify()
    supplied = record.model_dump(mode="json") if isinstance(record, RunRecord) else record
    _require(supplied == store.load(), "CP import must use the exact immutable current RunStore record")
    record = RunRecord.model_validate(supplied)
    _require(case.observable == "cp_interaction_energy" and case.units == "hartree"
             and case.definition == CP_DEFINITION and case.geometry_role == "frozen-complex-geometry",
             "CP reference must declare the exact frozen electronic observable, never binding or thermal energy")
    _require(record.request == case.request and record.status == "completed"
             and record.validation_status == "validated-for-protocol", "CP reference lacks the exact completed declared request")
    metadata = record.metadata.get("matrix_counterpoise")
    _require(isinstance(metadata, dict) and metadata.get("status") == "completed"
             and metadata.get("validation_status") == "validated-for-protocol", "Ordinary native five-leg counterpoise is absent")
    snapshot = store.snapshot_path()
    inventory = artifact_inventory(supplied)
    summary = [a for a in inventory if a["path"] == metadata["result_path"] and a["role"] == "counterpoise-result"]
    _require(len(summary) == 1, "CP result must be a retained immutable scientific artifact")
    payload = json.loads(confined_file(snapshot, "artifacts/" + summary[0]["path"]).read_text())
    _require(Path(summary[0]["path"]).stem == digest_json(payload), "CP result filename does not bind its semantic receipt")
    _require(payload["schema_version"] == CP_SCHEMA and payload["status"] == "completed"
             and payload["validation_status"] == "validated-for-protocol"
             and all(metadata[k] == payload[k] for k in ("status", "validation_status", "basis_identity", "energies")),
             "CP metadata differs from its immutable native result")
    method = MethodSpec.model_validate(payload["method"])
    _method(case, method)
    molecule = case.request.molecule
    plan = counterpoise_plan(molecule, method)
    _require(payload["plan"] == plan and len(plan) == 5
             and payload["geometry_sha256"] == geometry_digest(molecule), "CP basis centers, frozen geometry or fragment states changed")
    basis = payload["basis"]
    _require(set(basis) == {"orbital", "auxiliary"} and basis["orbital"]["declared_name"] == method.basis
             and basis["auxiliary"]["declared_name"] == (method.auxiliary_basis or "def2/J"), "CP basis inventory differs from its named Hamiltonian")
    entries = [j for j in payload["jobs"] if j["result"].get("status") == "completed"]
    _require(len(entries) == 5 and {j["role"] for j in entries} == set(ROLES), "CP requires five distinct completed native energy legs")
    values, legs, identities = {}, {}, set()
    for job in plan:
        entry = next(j for j in entries if j["role"] == job["role"])
        native = entry["result"]
        _require(entry["result_sha256"] == digest_json(native), "CP native leg result digest changed")
        result = EngineResult.model_validate(native)
        attempts = [a for a in record.attempts if a.attempt_id == "attempt_cp_" + entry["result_sha256"][:24]]
        _require(len(attempts) == 1, "CP leg does not identify one immutable native attempt")
        attempt = attempts[0]
        _require(result.status == attempt.status == "completed" and result.converged is attempt.converged is True
                 and attempt.validation_status == "validated-for-protocol"
                 and result.engine == attempt.engine == "orca" and result.operation == "energy"
                 and result.method == attempt.method == method.method and result.engine_version == attempt.engine_version == case.engine_version == "6.1.1"
                 and result.metadata.get("execution_kind") == attempt.metadata.get("execution_kind") == "real"
                 and attempt.command == result.command and len(result.command) == 2 and result.command[1] == "job.inp"
                 and Path(result.command[0]).is_absolute() and result.diagnostics == attempt.diagnostics
                 and attempt.metadata == {**result.metadata, "counterpoise_role": job["role"]}
                 and result.energy_hartree is not None and math.isfinite(result.energy_hartree), "CP leg lacks exact genuine native attempt identity")
        physical = Molecule.model_validate(job.get("physical_molecule", job["molecule"]))
        _require(result.molecule is not None and geometry_digest(result.molecule) == geometry_digest(physical),
                 "CP fragment physical geometry differs from the declared frozen complex")
        local_inventory = [a.model_dump(mode="json") for a in attempt.artifacts]
        originals = {a.path: a.model_dump(mode="json") for a in result.artifacts}
        _require(len(originals) == len(result.artifacts) and originals, "CP leg native artifact membership is ambiguous")
        process = result.diagnostics["process"]
        _require(process["status"] == "completed" and process["returncode"] == 0 and process["command"] == result.command,
                 "CP leg native process did not complete successfully")
        stdout_original = process["stdout_path"]
        directory = Path(stdout_original).parent
        # Scientific proof requires the full converged output, both process
        # streams, exact SP deck and every shared basis. Auxiliary wavefunction
        # binaries need not be copied into a reference comparison fixture.
        needed = {stdout_original, process["stderr_path"], str(directory / "job.inp"),
                  *(str(directory / (kind + ".bas")) for kind in basis)}
        _require(needed.issubset(originals), "CP leg lacks its retained raw scientific evidence")
        mapped = {original: _member(originals[original], local_inventory, snapshot) for original in sorted(needed)}
        stdout_member, stdout = mapped[stdout_original]
        raw = stdout.read_text(errors="replace")
        match = re.findall(r"FINAL SINGLE POINT ENERGY\s+([-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?)", raw)
        _require(_engine_version(raw, "orca") == "6.1.1" and "ORCA TERMINATED NORMALLY" in raw
                 and "SCF CONVERGED AFTER" in raw and not re.search(r"SCF NOT CONVERGED|SCF CONVERGENCE FAILURE", raw, re.I)
                 and match, "CP leg raw output does not establish native electronic convergence")
        energy = float(match[-1].replace("D", "E").replace("d", "e"))
        _require(math.isfinite(energy) and abs(energy-result.energy_hartree) <= 1e-10,
                 "CP leg structured energy differs from its actual native output")
        deck_original = str(Path(stdout_original).parent / "job.inp")
        expected = _orca_input(Molecule.model_validate(job["molecule"]), method,
                               ResourceLimits.model_validate(result.metadata["resources"]), "energy",
                               ghost_atom_indices=job["ghost_atom_indices"],
                               ghost_electronic_state=tuple(job["ghost_electronic_state"]) if job["ghost_electronic_state"] else None,
                               basis_files={kind: f"{kind}.bas" for kind in basis})
        _require(mapped[deck_original][1].read_text() == expected, "CP raw deck changed method, geometry, ghost centers or electronic state")
        _require(result.metadata.get("requested_method") == method.model_dump(mode="json"),
                 "CP native leg requested method differs from its comparison protocol")
        for kind, description in basis.items():
            original = str(Path(stdout_original).parent / (kind + ".bas"))
            member, _ = mapped[original]
            _require((member["sha256"], member["size_bytes"]) == (description["sha256"], description["size_bytes"])
                     and result.metadata["external_basis"][kind]["sha256"] == description["sha256"]
                     and result.metadata["external_basis"][kind]["declared_basis"] == description["declared_name"],
                     "CP leg did not use the shared exact named basis bytes")
        executable_sha256 = result.metadata.get("executable_sha256")
        _require(_hash(executable_sha256), "CP leg lacks its actual native executable digest")
        identities.add(executable_sha256)
        quantities = [q for q in attempt.quantities if q.name == "electronic_energy"]
        _require(len(quantities) == 1 and quantities[0].units == "hartree" and quantities[0].validity == "validated-for-protocol"
                 and quantities[0].value == result.energy_hartree, "CP leg quantity differs from its native receipt")
        values[job["role"]] = energy
        legs[job["role"]] = {"attempt_id": attempt.attempt_id, "native_result_sha256": entry["result_sha256"],
                             "stdout_path": stdout_member["path"], "stdout_sha256": stdout_member["sha256"],
                             "energy_hartree": energy,
                             "native_artifacts_sha256": {member["path"]: member["sha256"] for member, _ in mapped.values()}}
    _require(len(identities) == 1, "CP legs were executed with different native binaries")
    executable_sha256 = identities.pop()
    basis_proof = _basis_receipts(payload, molecule, method, executable_sha256, inventory, snapshot)
    protocol = {"method": method.model_dump(mode="json"), "basis_sha256": {k: b["sha256"] for k, b in basis.items()},
                "complex_state": {"charge": molecule.charge, "multiplicity": molecule.multiplicity,
                                  "fragment_states": [s.model_dump(mode="json") for s in molecule.fragment_states]},
                "complex_geometry_sha256": geometry_digest(molecule),
                "engine_identity": {"version": "6.1.1", "executable_sha256": executable_sha256}}
    _require(payload["comparison_protocol_definition"] == protocol and payload["comparison_protocol"] == digest_json(protocol),
             "CP comparison protocol changed native method, state, basis, geometry or executable")
    energies = counterpoise_interaction(values[ROLES[0]], values[ROLES[2]], values[ROLES[4]], values[ROLES[1]], values[ROLES[3]])
    energies["half_cp_interaction_hartree"] = (energies["raw_interaction_hartree"] + energies["cp_interaction_hartree"]) / 2
    _require(payload["energies"] == {**energies, "leg_energies_hartree": values},
             "CP interaction receipt differs from independently recomputed five native energies")
    return energies["cp_interaction_hartree"], {"parser": "immutable-five-leg-native-Boys-Bernardi-v1",
            "snapshot_id": manifest["snapshot_id"], "result_path": summary[0]["path"],
            "result_sha256": summary[0]["sha256"], "engine_version": "6.1.1", "executable_sha256": executable_sha256,
            "geometry_sha256": geometry_digest(molecule), "comparison_protocol": payload["comparison_protocol"],
            "definition": CP_DEFINITION, "basis_exports": basis_proof, "native_legs": legs,
            "recomputed_energies_hartree": energies,
            "provenance_limit": "Immutable bytes and BASE receipt consistency; no independent authentication of arbitrary receipt authors"}
