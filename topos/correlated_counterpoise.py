"""Native three-leg DLPNO counterpoise with separate physical/basis centers.

R2's cc-pVDZ-F12 is an orbital basis, not an F12 Hamiltonian. This energy
contribution does not implement a frozen-manifold vibrational correction.
"""
from __future__ import annotations

import math
import shutil
import time
from pathlib import Path
from threading import Event
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from .chemistry import atomic_number
from .correlated import CorrelatedMethod, correlated_input, parse_correlated_output
from .counterpoise import ORCA_BASIS_SOURCE, ORCA_GHOST_SOURCE, _validate_basis_export_receipts
from .engines import EngineResult, _engine_version, _orca_version_input, artifact_inventory
from .fragments import split_fragments
from .matrix_components import run_component
from .models import Artifact, Contract, MethodSpec, Molecule, ResourceLimits, new_id
from .science import geometry_digest
from .storage import IntegrityError, atomic_json, digest_json, file_digest

R2_ENERGY_RESOLUTION = "orca-r2-dlpno-orbital-f12-cp-v1"


class CorrelatedCounterpoiseProtocol(Contract):
    native: CorrelatedMethod
    source_resolution: Literal["orca-r2-dlpno-orbital-f12-cp-v1"]

    @model_validator(mode="after")
    def exact_r2_energy(self):
        native = self.native
        if (native.method, native.operation, native.orbital_basis, native.pno_profile, native.frozen_core) != (
                "DLPNO-CCSD(T1)", "energy", "cc-pVDZ-F12", "TightPNO", True):
            raise ValueError("The reviewed R2 energy is ordinary frozen-core DLPNO-CCSD(T1)/cc-pVDZ-F12 TightPNO")
        if native.cabs is not None or native.local_energy_decomposition:
            raise ValueError("R2 counterpoise is neither an F12 Hamiltonian nor LED")
        return self

    def basis_names(self) -> dict[str, str]:
        names = {"orbital": self.native.orbital_basis, "correlation": self.native.auxiliary_c}
        if self.native.auxiliary_jk:
            names["jk"] = self.native.auxiliary_jk
        return names


class CorrelatedGhostLeg(CorrelatedMethod):
    """Typed basis-center inventory; molecular argument remains the physical system."""
    basis_centers: Molecule
    physical_atom_indices: list[Annotated[int, Field(strict=True)]] = Field(min_length=1)
    basis_exports: dict[str, dict[str, Any]]

    @model_validator(mode="after")
    def bounded_ghost_scope(self):
        CorrelatedCounterpoiseProtocol(native=CorrelatedMethod.model_validate(
            self.model_dump(exclude={"basis_centers", "physical_atom_indices", "basis_exports"})),
            source_resolution=R2_ENERGY_RESOLUTION)
        indices = self.physical_atom_indices
        if len(indices) != len(set(indices)) or any(
                isinstance(i, bool) or i < 0 or i >= len(self.basis_centers.symbols) for i in indices):
            raise ValueError("Physical centers must be unique atom indices within the full basis inventory")
        if any(atomic_number(s) > 36 for s in self.basis_centers.symbols):
            raise ValueError("Correlated counterpoise requires all-electron H–Kr; no implicit ghost ECP")
        return self

    def native_protocol(self) -> CorrelatedMethod:
        return CorrelatedMethod.model_validate(self.model_dump(
            exclude={"basis_centers", "physical_atom_indices", "basis_exports"}))


def correlated_counterpoise_plan(molecule: Molecule, protocol: CorrelatedCounterpoiseProtocol):
    protocol = CorrelatedCounterpoiseProtocol.model_validate(protocol.model_dump())
    fragments = split_fragments(molecule)
    if len(fragments) != 2:
        raise ValueError("The reviewed three-leg counterpoise protocol requires exactly two fragments")
    if molecule.environment not in ({}, {"phase": "gas"}):
        raise ValueError("Correlated counterpoise is an explicit gas-phase protocol")
    if any(atomic_number(s) > 36 for s in molecule.symbols):
        raise ValueError("Correlated counterpoise requires all-electron H–Kr; no implicit ghost ECP")
    if any(m.multiplicity != 1 for m in [molecule, *fragments]):
        raise ValueError("The native correlated reference requires closed-shell physical complex and fragments")
    return [("complex-in-complex-basis", molecule, list(range(len(molecule.symbols)))),
            *[(f"fragment-{i}-in-complex-basis", fragment, list(group))
              for i, (fragment, group) in enumerate(zip(fragments, molecule.fragments, strict=True))]]


def correlated_ghost_input(physical: Molecule, leg: CorrelatedGhostLeg, resources: ResourceLimits) -> str:
    """Build a native deck only after binding physical atom IDs to basis centers."""
    leg = CorrelatedGhostLeg.model_validate(leg.model_dump())
    indices, centers = leg.physical_atom_indices, leg.basis_centers
    for field in ("symbols", "coordinates", "atom_ids", "isotopes"):
        if getattr(physical, field) != [getattr(centers, field)[i] for i in indices]:
            raise ValueError("Physical fragment atom identities and coordinates differ from the basis centers")
    expected = correlated_counterpoise_plan(centers, CorrelatedCounterpoiseProtocol(
        native=leg.native_protocol(), source_resolution=R2_ENERGY_RESOLUTION))
    if not any(group == indices and candidate.model_dump() == physical.model_dump() for _, candidate, group in expected):
        raise ValueError("Physical charge/spin/fragment identity does not match the explicit complex partition")
    native = leg.native_protocol()
    deck = correlated_input(physical, native, resources)
    prefix = deck[:deck.index("* xyz ")].splitlines()
    tokens = prefix[0].split()
    omitted = {native.orbital_basis, native.auxiliary_c, native.auxiliary_jk}
    prefix[0] = " ".join(token for token in tokens if token not in omitted)
    prefix.append("%basis")
    names = CorrelatedCounterpoiseProtocol(native=native, source_resolution=R2_ENERGY_RESOLUTION).basis_names()
    if set(leg.basis_exports) != set(names):
        raise ValueError("Every exact orbital, correlation and selected JK basis requires a native export receipt")
    for kind, keyword in (("orbital", "GTOName"), ("correlation", "GTOAuxCName"), ("jk", "GTOAuxJKName")):
        if kind in names:
            prefix.append(f'  {keyword} "{kind}.bas"')
    if "jk" in names:
        # A file-backed AuxJK assignment does not populate ORCA's separate
        # AuxJ slot. Use the same explicitly selected, exported JK basis bytes
        # for Coulomb fitting; this introduces no second fitting protocol.
        prefix.append('  GTOAuxJName "jk.bas"')
    prefix.extend(["end", f"* xyz {physical.charge} {physical.multiplicity}"])
    selected = set(indices)
    for index, (symbol, xyz) in enumerate(zip(centers.symbols, centers.coordinates, strict=True)):
        prefix.append(f"{symbol}{'' if index in selected else ':'} " + " ".join(format(x, ".16g") for x in xyz))
    return "\n".join([*prefix, "*", ""])


def _basis_slot_bindings(leg: CorrelatedGhostLeg) -> dict[str, dict[str, str]]:
    """Retain every native basis-slot assignment and its exact exported bytes."""
    names = CorrelatedCounterpoiseProtocol(native=leg.native_protocol(), source_resolution=R2_ENERGY_RESOLUTION).basis_names()
    assignments = {"orbital": "orbital", "AuxC": "correlation"}
    if "jk" in names:
        assignments.update(AuxJK="jk", AuxJ="jk")
    return {slot: {"export_role": kind, "basis": names[kind], "file": f"{kind}.bas",
                   "sha256": leg.basis_exports[kind]["output_sha256"]}
            for slot, kind in assignments.items()}


def _verify_exports(leg: CorrelatedGhostLeg, engine_identity=None):
    names = CorrelatedCounterpoiseProtocol(native=leg.native_protocol(), source_resolution=R2_ENERGY_RESOLUTION).basis_names()
    if set(leg.basis_exports) != set(names):
        raise IntegrityError("Correlated ghost calculation requires every native basis export")
    distributions = set()
    for kind, basis in names.items():
        receipt = leg.basis_exports[kind]
        path = Path(receipt.get("output_path", ""))
        inventory = {"orbital": {"sha256": receipt.get("output_sha256")}}
        _validate_basis_export_receipts({"orbital": receipt}, inventory, {"orbital": path}, leg.basis_centers,
                                       MethodSpec(engine="orca", method="HF", basis=basis), engine_identity)
        distributions.add(tuple(receipt[key] for key in ("orca_sha256", "archive_sha256", "distribution_manifest_sha256")))
    if len(distributions) != 1:
        raise IntegrityError("All shared basis exports must originate in the same authorized ORCA distribution")


def run_correlated_ghost(physical: Molecule, leg: CorrelatedGhostLeg, resources: ResourceLimits,
                         workdir: str | Path, *, executable=None, process_runner=None,
                         cancel_event: Event | None = None) -> EngineResult:
    """Run actual native ORCA with the physical state and full complex basis."""
    result = EngineResult(status="unsupported", engine="orca", method=leg.method, operation="energy",
        metadata={"execution_kind": "not-executed", "requested_protocol": leg.model_dump(mode="json"),
                  "resources": resources.model_dump(mode="json"), "physical_molecule": physical.model_dump(mode="json"),
                  "basis_center_molecule": leg.basis_centers.model_dump(mode="json"),
                  "physical_atom_indices": leg.physical_atom_indices, "f12_hamiltonian": False,
                  "sources": [ORCA_GHOST_SOURCE, ORCA_BASIS_SOURCE]})
    started, folder = time.monotonic(), Path(workdir).resolve()
    try:
        deck = correlated_ghost_input(physical, leg, resources)
        _verify_exports(leg)
        result.metadata["native_basis_slot_bindings"] = _basis_slot_bindings(leg)
        if process_runner is None:
            from .base_integration import BaseRuntime

            runtime = BaseRuntime()
            runtime.validate_resources(resources)
            executable = runtime.resolve_executable("orca", executable)
            process_runner = runtime.run_process
        binary = shutil.which(str(executable or "orca"))
        if binary is None:
            result.status, result.diagnostics["reason"] = "unavailable", "Licensed ORCA executable is unavailable"
            return result
        binary = str(Path(binary).resolve())
        identity = (leg.engine_version, file_digest(Path(binary)))
        _verify_exports(leg, identity)
        if folder.exists() and any(folder.iterdir()):
            raise ValueError("A native ghost component requires fresh scratch; use the immutable ledger to resume")
        folder.mkdir(parents=True, exist_ok=True)
        result.metadata["executable_sha256"] = identity[1]
        atomic_json(folder / "protocol.json", leg.model_dump(mode="json"))
        for kind, receipt in leg.basis_exports.items():
            destination = folder / f"{kind}.bas"
            shutil.copyfile(receipt["output_path"], destination)
            if file_digest(destination) != receipt["output_sha256"]:
                raise IntegrityError("Native shared basis bytes changed during staging")
            atomic_json(folder / f"{kind}-export-receipt.json", receipt)
            for index, evidence in enumerate(receipt["evidence"]):
                retained = folder / f"{kind}-export-{index}.log"
                shutil.copyfile(evidence["path"], retained)
                if file_digest(retained) != evidence["sha256"]:
                    raise IntegrityError("Native basis export evidence changed during staging")

        def remaining(diagnostic=False):
            seconds = resources.budget_seconds - (time.monotonic() - started)
            if seconds <= 0:
                raise TimeoutError("Correlated counterpoise component deadline reached")
            return resources.model_copy(update={"budget_seconds": min(10., seconds) if diagnostic else seconds,
                                                 "threads": 1 if diagnostic else resources.threads})

        (folder / "version.inp").write_text(_orca_version_input(resources))
        probe = process_runner([binary, "version.inp"], folder, remaining(True), log_prefix="version",
                               cancel_event=cancel_event, threads_per_process=1)
        result.diagnostics["version_probe"] = probe.to_dict()
        raw = Path(probe.stdout_path).read_text(errors="replace")
        if probe.status != "completed":
            result.status, result.diagnostics["reason"] = probe.status, probe.reason
            return result
        if (_engine_version(raw, "orca") != leg.engine_version or "ORCA TERMINATED NORMALLY" not in raw
                or "SCF CONVERGED AFTER" not in raw or "FINAL SINGLE POINT ENERGY" not in raw):
            raise ValueError("Native serial version/loader probe did not establish ORCA 6.1.1")
        result.engine_version = leg.engine_version
        (folder / "job.inp").write_text(deck)
        result.command, result.metadata["execution_kind"] = [binary, "job.inp"], "real"
        process = process_runner(result.command, folder, remaining(), log_prefix="engine",
                                 cancel_event=cancel_event, threads_per_process=1)
        result.diagnostics["process"], result.status = process.to_dict(), process.status
        if process.status != "completed":
            result.diagnostics["reason"] = process.reason
            return result
        observation = parse_correlated_output(Path(process.stdout_path).read_text(errors="replace"), leg.native_protocol())
        _verify_exports(leg, identity)
        result.metadata["native_result"] = observation
        result.energy_hartree, result.molecule, result.converged = observation["energy_hartree"], physical, True
        return result
    except TimeoutError as exc:
        result.status, result.diagnostics["reason"] = "timed-out", str(exc)
        return result
    except (ValueError, RuntimeError, OSError) as exc:
        result.status, result.diagnostics["reason"] = "failed" if result.metadata["execution_kind"] == "real" else "unsupported", str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - started
        if folder.is_dir():
            result.artifacts = artifact_inventory(folder)


def _verify_native_leg(result: EngineResult, physical: Molecule, leg: CorrelatedGhostLeg):
    if (result.status != "completed" or result.converged is not True or result.metadata.get("execution_kind") != "real"
            or result.energy_hartree is None or not result.command or not result.artifacts or result.molecule != physical):
        raise IntegrityError("Correlated CP requires actual converged physical native component evidence")
    inventory = {a.path: a for a in result.artifacts}
    for artifact in result.artifacts:
        path = Path(artifact.path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size != artifact.size_bytes or file_digest(path) != artifact.sha256:
            raise IntegrityError("Correlated CP native artifact changed")
    stdout = Path(result.diagnostics.get("process", {}).get("stdout_path", ""))
    deck = stdout.parent / "job.inp"
    if str(stdout) not in inventory or str(deck) not in inventory:
        raise IntegrityError("Correlated CP lacks its retained native deck and output")
    if deck.read_text() != correlated_ghost_input(physical, leg, ResourceLimits.model_validate(result.metadata["resources"])):
        raise IntegrityError("Native ghost deck differs from its physical state, basis inventory or method")
    if result.metadata.get("native_basis_slot_bindings") != _basis_slot_bindings(leg):
        raise IntegrityError("Native ghost basis-slot provenance differs from the exact shared exports")
    observation = parse_correlated_output(stdout.read_text(errors="replace"), leg.native_protocol())
    if abs(observation["energy_hartree"] - result.energy_hartree) > 1e-10:
        raise IntegrityError("Native correlated energy differs from its retained result")
    identity = (result.engine_version, result.metadata.get("executable_sha256"))
    if file_digest(Path(result.command[0])) != identity[1]:
        raise IntegrityError("The correlated native executable identity changed")
    _verify_exports(leg, identity)
    for kind, receipt in leg.basis_exports.items():
        path = stdout.parent / f"{kind}.bas"
        if str(path) not in inventory or file_digest(path) != receipt["output_sha256"]:
            raise IntegrityError("Correlated ghost leg did not retain the exact shared native basis bytes")
    return identity


def run_r2_counterpoise(workflow, record, store, molecule: Molecule, protocol: CorrelatedCounterpoiseProtocol,
                       deadline: float, cancel_event: Event | None = None) -> dict | None:
    """Three durable native energies; a contribution, never a full R2 completion."""
    plan = correlated_counterpoise_plan(molecule, protocol)
    for _, physical, _ in plan:
        correlated_input(physical, protocol.native, record.request.resources)
    if record.request.per_geometry_budget_seconds is not None:
        deadline = min(deadline, time.monotonic() + record.request.per_geometry_budget_seconds)
    runtime = workflow.base_runtime
    if runtime is None:
        record.status, record.metadata["termination_reason"] = "unavailable", "Correlated CP requires BASE-authorized native basis exports"
        store.commit(record)
        return None
    identity = digest_json({"molecule": molecule.model_dump(mode="json"), "protocol": protocol.model_dump(mode="json")})
    exports = record.metadata.setdefault("r2_counterpoise_basis_exports", {}).setdefault(identity, {})

    def stopped():
        cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled or time.monotonic() >= deadline:
            record.status = "cancelled" if cancelled else "timed-out"
            record.metadata["termination_reason"] = "Correlated CP shared geometry budget stopped before completion"
            store.commit(record)
            return True
        return False

    for kind, basis in protocol.basis_names().items():
        if stopped():
            return None
        if kind in exports:
            continue
        folder = store.run_dir / "r2-basis-exports" / new_id(kind)
        receipt = runtime.export_orca_basis(basis, sorted(set(molecule.symbols)), folder,
            record.request.resources.model_copy(update={"threads": 1, "budget_seconds": deadline-time.monotonic()}),
            cancel_event=cancel_event)
        for path in folder.rglob("*"):
            if path.is_file() and not path.is_symlink():
                record.artifacts.append(Artifact(path=path.relative_to(store.run_dir).as_posix(), sha256=file_digest(path),
                                                 size_bytes=path.stat().st_size, role="native-ORCA-basis-export"))
        if receipt["status"] != "completed":
            record.status, record.metadata["termination_reason"] = receipt["status"], "Native correlated CP basis export failed"
            store.commit(record)
            return None
        exports[kind] = receipt
        store.commit(record)
    values, identities = {}, set()
    for role, physical, indices in plan:
        if stopped():
            return None
        leg = CorrelatedGhostLeg(**protocol.native.model_dump(), basis_centers=molecule,
                                  physical_atom_indices=indices, basis_exports=exports)
        _verify_exports(leg)
        result = run_component(workflow, record, store, "r2-cp-"+role, physical, leg,
                               run_correlated_ghost, deadline, cancel_event)
        if result is None:
            return None
        identities.add(_verify_native_leg(result, physical, leg))
        values[role] = result.energy_hartree
    if stopped():
        return None
    if len(identities) != 1:
        raise IntegrityError("Counterpoise legs used different ORCA executable identities")
    energy = values["complex-in-complex-basis"] - math.fsum(values[f"fragment-{i}-in-complex-basis"] for i in range(2))
    return {"source_resolution": R2_ENERGY_RESOLUTION, "quantity_kind": "frozen-counterpoise-interaction-energy",
            "cp_interaction_energy_hartree": energy, "leg_energies_hartree": values,
            "definition": "E_AB(AB basis) - E_A(AB basis) - E_B(AB basis), all at the unchanged complex geometry",
            "geometry_sha256": geometry_digest(molecule), "geometry_state": "frozen-inc",
            "protocol": protocol.model_dump(mode="json"), "engine_identity": list(next(iter(identities))),
            "basis_identity": "native-export-verified", "basis_exports_sha256": digest_json(exports),
            "f12_hamiltonian": False, "binding_energy_hartree": None, "raw_interaction_energy_hartree": None,
            "bsse_correction_hartree": None, "vibrational_correction": None, "full_R2_recipe_completed": False,
            "accuracy_claim": None, "sources": [ORCA_GHOST_SOURCE, ORCA_BASIS_SOURCE]}
