"""Conditional month-tier geometry corrections with unverified masses withheld.

This is an explicitly selected geometry-only branch. Native default CFOUR masses
do not establish isotope-consistent rotor constants or the full archived row.
"""
from __future__ import annotations

import time
from threading import Event
from typing import Literal

from pydantic import model_validator

from .cfour_corrections import (
    ScalarCampaignStopped,
    ScalarRelativisticProtocol,
    calculate_scalar_geometry_correction,
    scalar_input,
)
from .cfour_dboc import (
    DefaultMassDBOCProtocol,
    calculate_default_mass_dboc_geometry,
    dboc_input,
    validate_default_mass_domain,
)
from .higher_composite import (
    HigherGeometryProtocol,
    NumericalGeometryOptions,
    calculate_higher_geometry,
    combine_higher_geometry,
)
from .models import Artifact, Contract, Molecule
from .storage import IntegrityError, atomic_json, digest_json, file_digest

SOURCE_RESOLUTION = "cfour-native-default-mass-corrected-geometry-v1"


class MonthCorrectionProtocol(Contract):
    scalar: ScalarRelativisticProtocol
    dboc: DefaultMassDBOCProtocol
    scalar_numerical: NumericalGeometryOptions
    dboc_numerical: NumericalGeometryOptions
    convention: Literal["cfour-higher-HF-X2C-native-default-DBOC-geometry-v1"]
    rotor_policy: Literal["withhold-unverified-native-default-mass-rotors"]

    @model_validator(mode="after")
    def exact_pair(self):
        if self.scalar.relativistic != "X2C1E" or not self.dboc.dboc:
            raise ValueError("Month corrections require explicit X2C1E and DBOC=ON pairs")
        if (self.scalar.genbas_path, self.scalar.genbas_sha256) != (self.dboc.genbas_path, self.dboc.genbas_sha256):
            raise ValueError("Month correction pairs require one exact native GENBAS library")
        return self


def validate_month_inputs(record, inputs) -> tuple[HigherGeometryProtocol, MonthCorrectionProtocol]:
    if record.request.matrix_row_id != "T3C-1mo" or inputs.source_resolution != SOURCE_RESOLUTION:
        raise ValueError("The restricted month branch requires its explicit row and source resolution")
    if inputs.external_resolution != "cfour-topos-cartesian-optimizer-v1":
        raise ValueError("Month geometry requires the explicit CFOUR/TOPOS optimizer resolution")
    if inputs.higher_geometry is None or inputs.month_corrections is None:
        raise ValueError("Explicit higher_geometry and month_corrections protocols are required")
    high = HigherGeometryProtocol.model_validate(inputs.higher_geometry.model_dump())
    corrections = MonthCorrectionProtocol.model_validate(inputs.month_corrections.model_dump())
    signatures = {(p.engine_version, p.genbas_path, p.genbas_sha256)
                  for p in (high.template, corrections.scalar, corrections.dboc)}
    if len(signatures) != 1:
        raise ValueError("Higher, scalar and DBOC components require one native version and GENBAS identity")
    molecule = record.request.molecule
    validate_default_mass_domain(molecule)
    combine_higher_geometry({role: molecule for role in high.protocols()}, high)
    # Generate strict typed decks before any costly high-level component runs.
    scalar_input(molecule, corrections.scalar, record.request.resources)
    dboc_input(molecule, corrections.dboc, record.request.resources)
    return high, corrections


def _retain_stage(record, store, role: str, report: dict) -> None:
    path = store.run_dir / "month-components" / role / (digest_json(report) + ".json")
    atomic_json(path, report)
    artifact = Artifact(path=path.relative_to(store.run_dir).as_posix(), sha256=file_digest(path),
                        size_bytes=path.stat().st_size, role="matrix-month-geometry-component")
    if not any(item.path == artifact.path for item in record.artifacts):
        record.artifacts.append(artifact)
    record.metadata.setdefault("month_geometry_stages", {})[role] = artifact.model_dump(mode="json")
    store.commit(record)


def execute_month_geometry(workflow, record, store, inputs, deadline: float, cancel_event: Event | None) -> bool:
    """Compute supported corrections; never promote them to the full mass-bound row."""
    from .external_matrix_workflow import _publish
    from .method_matrix import reviewed_revision

    def check():
        cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled or time.monotonic() >= deadline:
            record.status = "cancelled" if cancelled else "timed-out"
            record.metadata["termination_reason"] = "Month geometry shared budget/cancellation reached"
            store.commit(record)
            raise ScalarCampaignStopped(record.metadata["termination_reason"])

    try:
        check()
        high, corrections = validate_month_inputs(record, inputs)
        if record.request.per_geometry_budget_seconds is not None:
            deadline = min(deadline, time.monotonic() + record.request.per_geometry_budget_seconds)
        check()
        base = calculate_higher_geometry(workflow, record, store, inputs, deadline, cancel_event,
                                         include_rotor_constants=False)
        if base is None:
            return False
        check()
        _retain_stage(record, store, "higher", base)
        scalar = calculate_scalar_geometry_correction(workflow, record, store,
            Molecule.model_validate(base["molecule"]), corrections.scalar, high.coordinates,
            corrections.scalar_numerical, deadline, cancel_event)
        check()
        _retain_stage(record, store, "scalar", scalar)
        dboc = calculate_default_mass_dboc_geometry(workflow, record, store,
            Molecule.model_validate(scalar["molecule"]), corrections.dboc, high.coordinates,
            corrections.dboc_numerical, deadline, cancel_event)
        check()
        _retain_stage(record, store, "dboc", dboc)
        identity = [base["engine_version"], base["executable_sha256"], base["genbas_sha256"]]
        if not all(identity) or any(report.get("native_engine_identity") != identity for report in (scalar, dboc)):
            raise IntegrityError("Higher/scalar/DBOC results mixed native executable or GENBAS identities")
        if any(report.get("claims", {}).get("native_execution_verified") is not True for report in (scalar, dboc)):
            raise IntegrityError("Month corrections lack completed native component evidence")
        output = {
            "row_id": "T3C-1mo", "output_kind": "conditional-corrected-geometry",
            "definition": "R_higher + (R_HF_X2C1E - R_HF_NR) + (R_HF_plus_native_default_DBOC - R_HF); common independent internal-coordinate chart",
            "protocol": corrections.model_dump(mode="json"), "higher_protocol": high.model_dump(mode="json"),
            "molecule": dboc["molecule"], "source_resolution": SOURCE_RESOLUTION,
            "reviewed_method_revision": reviewed_revision(SOURCE_RESOLUTION),
            "engine_version": identity[0], "executable_sha256": identity[1], "genbas_sha256": identity[2],
            "component_attempt_ids": [a.attempt_id for a in record.attempts if a.status == "completed"
                and str(a.metadata.get("component_key", "")).startswith(("higher-", "scalar-", "default-dboc-"))],
            "component_reports": record.metadata["month_geometry_stages"],
            "mass_convention": dboc["mass_convention"], "full_matrix_row_completed": False,
            "equilibrium_rotational_constants_mhz": None, "rotor_constants_publishable": False,
            "electronic_energy_hartree": None, "minimum_hessian_verified": False,
            "vibrational_correction_applied": False, "accuracy_claim": None,
            "limitations": ["Restricted native-default mass H/C/N/O/F geometry branch; every explicit isotope is rejected",
                "Numeric native masses remain unattested; all rotor constants are withheld",
                "HF scalar/adiabatic increments are not correlated small corrections or a common-potential stationary point",
                "Native CFOUR acceptance is required for every actual component; historical parser tests do not establish installation support",
                "Same torsional-basin membership remains an unverified assumption"],
        }
        check()
        _publish(record, store, output)
        return True
    except IntegrityError:
        raise
    except ScalarCampaignStopped:
        return False
    except (ValueError, RuntimeError, OSError) as exc:
        record.status = "partial" if record.attempts else "unsupported"
        record.metadata["termination_reason"] = str(exc)
        store.commit(record)
        return False
