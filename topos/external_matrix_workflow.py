"""Whole native CFOUR/Psi4 recipes with explicit source resolutions and evidence."""
from __future__ import annotations

from threading import Event
from typing import Any

from .external_engines import ExternalProtocol, run_external
from .matrix_components import run_component
from .models import Artifact, RunRecord
from .science import rotational_constants
from .storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest

EXTERNAL_ROWS = frozenset({"T3C-30min", "T3C-1h", "T3C-3h", "T3C-12h", "T3C-1d", "T3C-3d", "T5-1mo"})
NATIVE_BASIS_ALIASES = {"cc-pVDZ": {"cc-pVDZ", "PVDZ"}, "cc-pVTZ": {"cc-pVTZ", "PVTZ"},
                        "cc-pVQZ": {"cc-pVQZ", "PVQZ"}, "cc-pCVQZ": {"cc-pCVQZ", "PCVQZ"},
                        "jun-cc-pVTZ": {"jun-cc-pVTZ"}}


def protocol_for_row(row: str, supplied: ExternalProtocol | None) -> ExternalProtocol:
    if row not in EXTERNAL_ROWS:
        raise ValueError("This row has no complete external-engine recipe; unsupported composites cannot reuse a simpler calculation")
    if supplied is None:
        raise ValueError("An explicit external_protocol is required, including native version, basis and core treatment")
    supplied = ExternalProtocol.model_validate(supplied.model_dump())
    if row == "T5-1mo":
        if (supplied.engine, supplied.method, supplied.operation) != ("psi4", "SAPT2+3", "sapt-decomposition"):
            raise ValueError("T5-1mo currently requires its explicit Psi4 SAPT2+3 branch; SAPT(DFT) is a different protocol")
        return supplied
    method, basis, operation, core = {
        "T3C-30min": ("MP2", "cc-pVDZ", "optimize", True),
        "T3C-1h": ("CCSD(T)", "cc-pVTZ", "first-order-properties", None),
        "T3C-3h": ("CCSD(T)", "cc-pVTZ", "optimize", True),
        "T3C-12h": ("CCSD(T)", "cc-pVQZ", "optimize", True),
        "T3C-1d": ("CCSD(T)", "cc-pCVQZ", "optimize", False),
        "T3C-3d": ("CCSD(T)", "jun-cc-pVTZ", "optimize", True),
    }[row]
    if (supplied.engine, supplied.method, supplied.operation) != ("cfour", method, operation):
        raise ValueError(f"{row} requires native CFOUR {method} {operation}; no method/operation substitution")
    if supplied.orbital_basis not in NATIVE_BASIS_ALIASES[basis]:
        raise ValueError(f"{row} requires the explicit {basis} basis or its documented native CFOUR alias")
    if core is not None and supplied.frozen_core is not core:
        raise ValueError(f"{row} requires frozen_core={core}; core-valence treatments are not interchangeable")
    if not supplied.genbas_path or not supplied.genbas_sha256:
        raise ValueError("CFOUR matrix execution requires the unchanged native GENBAS path and SHA-256")
    return supplied


def _publish(record: RunRecord, store: RunStore, output: dict[str, Any]) -> None:
    if not output["component_attempt_ids"] or not output["executable_sha256"]:
        raise IntegrityError("External recipe lacks native attempt/executable provenance")
    path = store.run_dir / "external-results" / (digest_json(output) + ".json")
    atomic_json(path, output)
    artifact = Artifact(path=path.relative_to(store.run_dir).as_posix(), sha256=file_digest(path),
                        size_bytes=path.stat().st_size, role="matrix-external-result")
    if not any(a.path == artifact.path for a in record.artifacts):
        record.artifacts.append(artifact)
    record.metadata["matrix_external"] = {**output, "result_path": artifact.path}
    store.commit(record)


def junchs_protocols(protocol: ExternalProtocol) -> dict[str, ExternalProtocol]:
    """The exact five component methods/bases; never independently inferred core defaults."""
    base = protocol_for_row("T3C-3d", protocol)
    options = {"base": {"method": "CCSD(T)", "orbital_basis": "jun-cc-pVTZ", "frozen_core": True},
               "mp2_tz": {"method": "MP2", "orbital_basis": "jun-cc-pVTZ", "frozen_core": True},
               "mp2_qz": {"method": "MP2", "orbital_basis": "jun-cc-pVQZ", "frozen_core": True},
               "cv_ae": {"method": "MP2", "orbital_basis": "cc-pwCVTZ", "frozen_core": False},
               "cv_fc": {"method": "MP2", "orbital_basis": "cc-pwCVTZ", "frozen_core": True}}
    return {role: ExternalProtocol.model_validate({**base.model_dump(), **change}) for role, change in options.items()}


def _junchs_geometry(workflow: Any, record: RunRecord, store: RunStore, inputs: Any,
                    protocol: ExternalProtocol, deadline: float, cancel_event: Event | None) -> bool:
    from .composites import CompositeCoordinateSet, combine_junchs_geometry
    from .models import Molecule

    if inputs.correlated_resolution != "junchs-same-basis-core-valence-v1":
        raise ValueError("CFOUR junChS requires explicit correlated_resolution='junchs-same-basis-core-valence-v1'; ae and fc CV optimizations use the same cc-pwCVTZ basis")
    coordinates = CompositeCoordinateSet.model_validate(inputs.composite_coordinates)
    protocols = junchs_protocols(protocol)
    # Validate the user's chart before costly native optimizations. This is
    # geometry validation only, never an electronic-structure result.
    combine_junchs_geometry(**{role: record.request.molecule for role in protocols}, coordinates=coordinates)
    geometries, energies, identities = {}, {}, set()
    for role, component in protocols.items():
        result = run_component(workflow, record, store, "external-T3C-3d-" + role, record.request.molecule,
                               component, run_external, deadline, cancel_event)
        if result is None:
            return False
        if result.molecule is None or result.gradient_hartree_per_bohr is None:
            raise IntegrityError("A CFOUR junChS component lacks its actual optimized geometry or analytic gradient")
        geometries[role], energies[role] = result.molecule, result.energy_hartree
        identities.add((result.engine_version, result.metadata.get("executable_sha256"),
                        result.metadata.get("basis_library", {}).get("sha256")))
    if len(identities) != 1 or not all(next(iter(identities))):
        raise IntegrityError("CFOUR junChS components mixed engine versions, executables or GENBAS libraries")
    combined = combine_junchs_geometry(**geometries, coordinates=coordinates)
    molecule = Molecule.model_validate(combined["molecule"])
    identity = next(iter(identities))
    output = {"row_id": "T3C-3d", "output_kind": "composite-equilibrium-geometry",
              "definition": "Parameter-wise R[fc-CCSD(T)/junTZ] + (64/37)*(R[fc-MP2/junQZ]-R[fc-MP2/junTZ]) + R[ae-MP2/pwCVTZ]-R[fc-MP2/pwCVTZ]",
              "protocols": {role: value.model_dump(mode="json") for role, value in protocols.items()},
              "component_attempt_ids": [a.attempt_id for a in record.attempts if a.status == "completed"
                                         and str(a.metadata.get("component_key", "")).startswith("external-T3C-3d-")],
              "engine_version": identity[0], "executable_sha256": identity[1], "genbas_sha256": identity[2],
              "source_resolution": inputs.external_resolution, "cv_resolution": inputs.correlated_resolution,
              "geometry_composite": combined, "molecule": molecule.model_dump(mode="json"),
              "equilibrium_rotational_constants_mhz": [value * 1000 if value is not None else None
                  for value in rotational_constants(molecule)["constants_ghz"]],
              "component_energies_hartree": energies, "composite_electronic_energy_hartree": None,
              "native_cfour_optimizer": False, "minimum_hessian_verified": False,
              "vibrational_correction_applied": False, "accuracy_claim": None}
    _publish(record, store, output)
    return True


def execute_external_recipe(workflow: Any, record: RunRecord, store: RunStore, inputs: Any,
                            deadline: float, cancel_event: Event | None) -> bool:
    """Complete one explicit external recipe; the native component ledger resumes it."""
    row = record.request.matrix_row_id
    try:
        protocol = protocol_for_row(row, inputs.external_protocol)
        if protocol.operation == "optimize" and inputs.external_resolution != "cfour-topos-cartesian-optimizer-v1":
            raise ValueError("The source uses CFOUR internal-coordinate optimization. Explicit external_resolution='cfour-topos-cartesian-optimizer-v1' is required for TOPOS Cartesian optimization using native analytic derivatives")
        if row == "T3C-3d":
            return _junchs_geometry(workflow, record, store, inputs, protocol, deadline, cancel_event)
        result = run_component(workflow, record, store, "external-" + row, record.request.molecule,
                               protocol, run_external, deadline, cancel_event)
        if result is None:
            return False
        if result.molecule is None:
            raise IntegrityError("Completed external calculation lacks its verified molecular geometry")
        native = result.metadata.get("native_result", {})
        output: dict[str, Any] = {
            "row_id": row, "protocol": protocol.model_dump(mode="json"),
            "protocol_sha256": digest_json(protocol.model_dump(mode="json")),
            "engine_version": result.engine_version, "executable_sha256": result.metadata.get("executable_sha256"),
            "component_attempt_ids": [a.attempt_id for a in record.attempts
                                      if a.metadata.get("component_key") == "external-" + row and a.status == "completed"],
            "molecule": result.molecule.model_dump(mode="json"), "accuracy_claim": None,
        }
        if protocol.operation == "sapt-decomposition":
            if result.energy_hartree is not None or result.metadata.get("quantity_kind") != "interaction-energy":
                raise IntegrityError("SAPT interaction energy must not be relabeled total electronic energy")
            if "interaction_energy_hartree" not in native or "sapt_components_hartree" not in native:
                raise IntegrityError("Native SAPT energy/decomposition is incomplete")
            output.update(output_kind="sapt-interaction-decomposition",
                          definition="Native SAPT2+3 frozen-geometry interaction energy and its electrostatic, exchange, induction and dispersion terms",
                          interaction_energy_hartree=native["interaction_energy_hartree"],
                          sapt_components_hartree=native["sapt_components_hartree"],
                          binding_energy_hartree=None, gibbs_energy_hartree=None,
                          geometry_optimized=False, automatic_pes_performed=False,
                          selected_source_branch="SAPT2+3; no SAPT(DFT) or automatic PES claim")
        elif protocol.operation == "first-order-properties":
            if "dipole_atomic_units" not in native:
                raise IntegrityError("First-order-property row lacks the actual native correlated dipole")
            output.update(output_kind="fixed-geometry-first-order-properties",
                          definition="Native CCSD(T) electronic energy and first-order electric dipole at the supplied geometry",
                          electronic_energy_hartree=result.energy_hartree,
                          dipole_atomic_units=native["dipole_atomic_units"], geometry_optimized=False,
                          equilibrium_rotational_constants_mhz=None)
        else:
            output.update(output_kind="stationary-geometry",
                          definition="TOPOS Cartesian L-BFGS-B optimization with actual native CFOUR analytic gradients",
                          electronic_energy_hartree=result.energy_hartree,
                          equilibrium_rotational_constants_mhz=[value * 1000 if value is not None else None
                              for value in rotational_constants(result.molecule)["constants_ghz"]],
                          source_resolution=inputs.external_resolution,
                          native_cfour_optimizer=False, gradient_convergence=result.diagnostics.get("optimization"),
                          minimum_hessian_verified=False, vibrational_correction_applied=False)
        _publish(record, store, output)
        return True
    except IntegrityError:
        raise
    except (ValueError, RuntimeError, OSError) as exc:
        record.status, record.metadata["termination_reason"] = "unsupported" if not record.attempts else "partial", str(exc)
        return False
