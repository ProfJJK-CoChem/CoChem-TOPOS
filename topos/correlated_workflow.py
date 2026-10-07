"""Complete correlated energy and parameter-wise geometry recipe orchestration."""
from __future__ import annotations

import time
from threading import Event
from typing import Any

from .correlated import CorrelatedMethod, run_correlated
from .fragments import split_fragments
from .matrix_components import run_component
from .models import Artifact, Attempt, Quantity, RunRecord
from .storage import IntegrityError, RunStore, atomic_json, digest_json, file_digest


def _protocol_for_row(row_id: str, supplied: CorrelatedMethod | None) -> CorrelatedMethod:
    if row_id not in {"T5-12h", "T5-1d", "T5-3d", "T3O-3d", "T3O-1mo"}:
        raise ValueError("This row has no compiled correlated single-protocol recipe; variants cannot be substituted")
    if supplied is None:
        raise ValueError("This correlated row requires an explicit correlated_protocol including orbital/auxiliary bases and frozen-core treatment")
    expected = {
        "T5-12h": ("DLPNO-CCSD(T1)", "cc-pVDZ-F12", "energy"),
        "T5-3d": ("CCSD(T)-F12D/RI", "cc-pVTZ-F12", "energy"),
        "T3O-3d": ("AUTOCI-CCSD(T)", "cc-pVTZ-F12", "optimize"),
        "T3O-1mo": ("CCSD(T)-F12D/RI", "cc-pVTZ-F12", "energy"),
    }
    if row_id in expected and (supplied.method, supplied.orbital_basis, supplied.operation) != expected[row_id]:
        raise ValueError(f"{row_id} requires the exact method, orbital basis and operation {expected[row_id]}")
    if row_id in {"T5-3d", "T3O-1mo"} and supplied.cabs != "cc-pVTZ-F12-CABS":
        raise ValueError("T5-3d requires cc-pVTZ-F12-CABS, plus the explicitly supplied RI correlation fitting basis")
    if row_id == "T5-12h" and (supplied.tcutpno != 1e-7 or not supplied.local_energy_decomposition):
        raise ValueError("T5-12h requires TightPNO/TCutPNO=1e-7 and a complete native LED decomposition")
    if row_id == "T5-1d" and (supplied.method != "DLPNO-CCSD(T1)" or supplied.operation != "energy"
                               or supplied.local_energy_decomposition):
        raise ValueError("CPS(6/7) requires a complete DLPNO-CCSD(T1) energy protocol; LED is a separate recipe")
    return supplied


def _publish(record: RunRecord, store: RunStore, row_id: str, output: dict[str, Any]) -> None:
    output["row_id"] = row_id
    output["component_attempt_ids"] = [a.attempt_id for a in record.attempts
                                        if a.metadata.get("role") == "matrix-native-component" and a.status == "completed"]
    path = store.run_dir / "correlated-results" / (digest_json(output) + ".json")
    atomic_json(path, output)
    artifact = Artifact(path=path.relative_to(store.run_dir).as_posix(), sha256=file_digest(path),
                        size_bytes=path.stat().st_size, role="matrix-correlated-result")
    if not any(a.path == artifact.path for a in record.artifacts):
        record.artifacts.append(artifact)
    record.metadata["matrix_correlated"] = {**output, "result_path": artifact.path}
    identity = "attempt_correlated_derived_" + digest_json(output)[:24]
    if not any(a.attempt_id == identity for a in record.attempts):
        aggregate = Attempt(attempt_id=identity, run_id=record.run_id, engine="topos", method=output["recipe"],
                            status="completed", converged=True, validation_status="validated-for-protocol",
                            command=["topos-internal", "correlated-recipe-arithmetic"], artifacts=[artifact],
                            metadata={"execution_kind": "real", "result_kind": "derived-correlated-recipe",
                                      "component_attempt_ids": output["component_attempt_ids"],
                                      "scientific_definition": output["definition"],
                                      "basis_and_method_identity": output.get("protocols"),
                                      "output_kind": output["output_kind"]})
        for key, units in (("interaction_energy_hartree", "hartree"), ("equilibrium_rotational_constants_mhz", "MHz"),
                           ("stationary_geometry_rotational_constants_mhz", "MHz"),
                           ("electronic_energy_hartree", "hartree")):
            if output.get(key) is not None:
                aggregate.quantities.append(Quantity(name=key, value=output[key], units=units,
                                                     definition=output["definition"], attempt_id=identity,
                                                     method=output["recipe"], validity="validated-for-protocol"))
        record.attempts.append(aggregate)
    store.commit(record)


def execute_correlated_recipe(workflow: Any, record: RunRecord, store: RunStore, inputs: Any,
                              deadline: float, cancel_event: Event | None) -> bool:
    row_id = record.request.matrix_row_id
    try:
        if row_id == "T3O-12h":
            return _junchs_geometry(workflow, record, store, inputs, deadline, cancel_event)
        protocol = _protocol_for_row(row_id, inputs.correlated_protocol)
        if row_id == "T3O-1mo":
            if inputs.source_resolution != "orca-f12-reference-singlepoint-v1":
                raise ValueError("Reference-energy branch requires explicit orca-f12-reference-singlepoint-v1 resolution")
            result = run_component(workflow, record, store, "reference-F12-singlepoint", record.request.molecule,
                                   protocol, run_correlated, deadline, cancel_event)
            if result is None:
                return False
            _publish(record, store, row_id, {"recipe": "ORCA-F12-reference-singlepoint", "output_kind": "reference-electronic-energy",
                "definition": "Native CCSD(T)-F12D/RI electronic energy at the supplied, unoptimized geometry",
                "electronic_energy_hartree": result.energy_hartree, "molecule": result.molecule.model_dump(mode="json"),
                "protocols": [protocol.model_dump(mode="json")], "geometry_optimized": False,
                "equilibrium_geometry_claim": False, "equilibrium_rotational_constants_mhz": None,
                "full_geometry_row_completed": False, "accuracy_claim": None})
            return True
        if row_id == "T3O-3d":
            if inputs.correlated_resolution != "autoci-conventional-transformation-v1":
                raise ValueError("AUTOCI does not inherit MDCI AO-direct controls. Explicit correlated_resolution='autoci-conventional-transformation-v1' is required and the source's AO-direct requirement is not claimed")
            result = run_component(workflow, record, store, "canonical-geometry", record.request.molecule,
                                   protocol, run_correlated, deadline, cancel_event)
            if result is None:
                return False
            from .science import rotational_constants

            output = {"recipe": "canonical-AUTOCI-CCSD(T)-geometry", "output_kind": "equilibrium-geometry",
                      "definition": "equilibrium geometry from actual canonical CCSD(T) analytic gradients; an F12 orbital basis does not imply an F12 Hamiltonian",
                      "molecule": result.molecule.model_dump(mode="json"),
                      "equilibrium_rotational_constants_mhz": [value * 1000 if value is not None else None for value in rotational_constants(result.molecule)["constants_ghz"]],
                      "protocols": [protocol.model_dump(mode="json")], "resolution": inputs.correlated_resolution,
                      "source_difference": "native AUTOCI integral transformation; no unverified AO-direct guarantee",
                      "vibrational_correction_applied": False, "minimum_hessian_verified": False}
            _publish(record, store, row_id, output)
            return True
        fragments = split_fragments(record.request.molecule)
        if len(fragments) != 2:
            raise ValueError("These interaction-energy recipes require exactly two explicit frozen-in-complex fragments")
        molecules = [record.request.molecule, *fragments]
        roles = ["complex", "fragment-0", "fragment-1"]
        identities = set()
        values = {}
        details = {}
        for role, molecule in zip(roles, molecules, strict=True):
            geometry_deadline = deadline
            if record.request.per_geometry_budget_seconds is not None:
                geometry_deadline = min(deadline, time.monotonic()+record.request.per_geometry_budget_seconds)
            current = protocol.model_copy(update={"local_energy_decomposition": protocol.local_energy_decomposition and role == "complex"})
            if row_id == "T5-1d":
                native = []
                for exponent in (6, 7):
                    component = current.model_copy(update={"tcutpno": 10.0 ** -exponent})
                    result = run_component(workflow, record, store, f"{role}-pno-{exponent}", molecule,
                                           component, run_correlated, geometry_deadline, cancel_event)
                    if result is None:
                        return False
                    native.append(result)
                    identities.add((result.engine_version, result.metadata.get("executable_sha256")))
                observations = [result.metadata["native_result"] for result in native]
                refs = [observation["reference_energy_hartree"] for observation in observations]
                if any(value is None for value in refs) or abs(refs[0] - refs[1]) > 2e-8:
                    raise IntegrityError("CPS thresholds do not share the same validated HF reference energy")
                from .composites import cps67

                values[role] = cps67(refs[0], observations[0]["total_correlation_energy_hartree"],
                                     observations[1]["total_correlation_energy_hartree"])
                details[role] = {"common_hf_hartree": refs[0], "energies_6_7_hartree": [r.energy_hartree for r in native]}
            else:
                result = run_component(workflow, record, store, role, molecule, current, run_correlated, geometry_deadline, cancel_event)
                if result is None:
                    return False
                identities.add((result.engine_version, result.metadata.get("executable_sha256")))
                values[role] = result.energy_hartree
                details[role] = result.metadata["native_result"]
        if len(identities) != 1 or not all(next(iter(identities))):
            raise IntegrityError("Interaction-energy components mixed different ORCA binaries or versions")
        definition = "E_complex - E_fragment_0 - E_fragment_1; every fragment frozen at the same complex geometry"
        if row_id == "T5-1d":
            definition += "; each component uses E_HF + E_corr(6) + 1.5*[E_corr(7)-E_corr(6)], with the same validated HF reference"
        _publish(record, store, row_id, {
            "recipe": "CPS(6/7)" if row_id == "T5-1d" else protocol.method,
            "output_kind": "frozen-interaction-energy", "definition": definition,
            "interaction_energy_hartree": values["complex"] - values["fragment-0"] - values["fragment-1"],
            "component_energies_hartree": values, "component_details": details,
            "protocols": [protocol.model_dump(mode="json")], "engine_identity": list(next(iter(identities))),
            "binding_energy_hartree": None, "gibbs_energy_hartree": None,
            "counterpoise_applied": False,
            "bsse_policy": "F12 calculation without optional CP" if row_id == "T5-3d" else "raw interaction; no counterpoise calculation claimed",
            "method_scope": "Plain DLPNO-CCSD(T1) remains conventional even with an F12-labeled orbital basis" if row_id in {"T5-12h", "T5-1d"} else "explicit F12D approximation, never relabeled F12b",
            "accuracy_claim": None,
        })
        return True
    except IntegrityError:
        raise
    except (ValueError, OSError, RuntimeError) as exc:
        record.status, record.metadata["termination_reason"] = "unsupported" if not record.attempts else "partial", str(exc)
        return False


def _junchs_geometry(workflow: Any, record: RunRecord, store: RunStore, inputs: Any,
                     deadline: float, cancel_event: Event | None) -> bool:
    from .composites import CompositeCoordinateSet, combine_junchs_geometry
    from .science import rotational_constants

    if inputs.correlated_resolution != "junchs-same-basis-core-valence-v1":
        raise ValueError("junChS requires explicit same-basis core-valence resolution; the matrix contains conflicting CV subtraction definitions")
    coordinates = CompositeCoordinateSet.model_validate(inputs.composite_coordinates)
    if coordinates.cv_basis != "cc-pwCVTZ":
        raise ValueError("The matrix junChS CV increment uses cc-pwCVTZ for both ae and fc optimizations")
    specs = {
        "base": CorrelatedMethod(method="AUTOCI-CCSD(T)", orbital_basis="jun-cc-pVTZ", operation="optimize", frozen_core=True),
        "mp2_tz": CorrelatedMethod(method="MP2", orbital_basis="jun-cc-pVTZ", operation="optimize", frozen_core=True),
        "mp2_qz": CorrelatedMethod(method="MP2", orbital_basis="jun-cc-pVQZ", operation="optimize", frozen_core=True),
        "cv_ae": CorrelatedMethod(method="MP2", orbital_basis="cc-pwCVTZ", operation="optimize", frozen_core=False),
        "cv_fc": CorrelatedMethod(method="MP2", orbital_basis="cc-pwCVTZ", operation="optimize", frozen_core=True),
    }
    geometries, energies, identities = {}, {}, set()
    for role, protocol in specs.items():
        result = run_component(workflow, record, store, "junchs-" + role, record.request.molecule,
                               protocol, run_correlated, deadline, cancel_event)
        if result is None:
            return False
        geometries[role] = result.molecule
        energies[role] = result.energy_hartree
        identities.add((result.engine_version, result.metadata.get("executable_sha256")))
    if len(identities) != 1:
        raise IntegrityError("junChS geometry components used different ORCA binaries")
    combined = combine_junchs_geometry(**geometries, coordinates=coordinates)
    from .models import Molecule

    molecule = Molecule.model_validate(combined["molecule"])
    _publish(record, store, record.request.matrix_row_id, {
        "recipe": "junChS-equilibrium-geometry", "output_kind": "composite-equilibrium-geometry",
        "definition": "parameter-wise R[fc-CCSD(T)/junTZ] + 64/37*(R[fc-MP2/junQZ]-R[fc-MP2/junTZ]) + R[ae-MP2/pwCVTZ]-R[fc-MP2/pwCVTZ]",
        "geometry_composite": combined, "molecule": molecule.model_dump(mode="json"),
        "equilibrium_rotational_constants_mhz": [value * 1000 if value is not None else None for value in rotational_constants(molecule)["constants_ghz"]],
        "component_energies_hartree": energies, "composite_electronic_energy_hartree": None,
        "protocols": {name: value.model_dump(mode="json") for name, value in specs.items()},
        "vibrational_correction_applied": False, "minimum_hessian_verified": False,
        "resolution": inputs.correlated_resolution, "accuracy_claim": None,
    })
    return True
