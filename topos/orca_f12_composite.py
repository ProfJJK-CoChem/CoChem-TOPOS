"""Explicit ORCA F12D/RI + split MP2-F12 CBS + MP2 CV interaction energies.

This user-reviewed variant is not junChS-F12b and inherits no F12b benchmark.
HF+CABS and actual F12 correlation are extrapolated separately. All terms
come from native, hash-verified component calculations at frozen geometries.
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path
from threading import Event
from typing import Literal

from pydantic import Field, model_validator

from .correlated import CorrelatedMethod, run_correlated
from .engines import EngineParseError, EngineResult, _number
from .fragments import split_fragments
from .matrix_components import run_component
from .models import Contract
from .storage import IntegrityError, file_digest

SOURCE_RESOLUTION = "orca-f12d-composite-interaction-v1"
F12_SOURCE = "https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/mdci.html#explicitly-correlated-methods-f12-mp2-and-f12-ccsd-t"
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"


class OrcaF12CompositeProtocol(Contract):
    """Five exact energy protocols; no CABS, fitting set, or exponent inferred."""

    base: CorrelatedMethod
    mp2_low: CorrelatedMethod
    mp2_high: CorrelatedMethod
    cv_ae: CorrelatedMethod
    cv_fc: CorrelatedMethod
    hf_exponential_alpha: float = Field(gt=0, le=20)
    correlation_inverse_power: float = Field(gt=0, le=10)
    extrapolation_quantity: Literal["hf-plus-cabs-exponential-and-f12-correlation-power"]
    convention: Literal["orca-f12d-ri-mp2-cbs-cv-v1"]

    @model_validator(mode="after")
    def exact_components(self):
        protocols = self.protocols()
        if any(p.operation != "energy" for p in protocols.values()):
            raise ValueError("The ORCA F12 composite requires five frozen-geometry single-point energies")
        if (self.base.method, self.base.orbital_basis, self.base.frozen_core) != (
                "CCSD(T)-F12D/RI", "jun-cc-pVTZ", True):
            raise ValueError("The reviewed base is frozen-core CCSD(T)-F12D/RI/jun-cc-pVTZ; it is not F12b")
        if self.mp2_low.method not in {"F12-MP2", "F12-RI-MP2"} or self.mp2_high.method != self.mp2_low.method:
            raise ValueError("Both CBS components require the same explicitly selected F12-MP2 or F12-RI-MP2 variant")
        if (self.mp2_low.orbital_basis, self.mp2_high.orbital_basis) != ("jun-cc-pVTZ", "jun-cc-pVQZ"):
            raise ValueError("The reviewed MP2-F12 CBS pair is explicitly jun-cc-pVTZ/jun-cc-pVQZ")
        if not self.mp2_low.frozen_core or not self.mp2_high.frozen_core:
            raise ValueError("CBS MP2-F12 legs require the same frozen-core treatment as the CC base")
        if (self.cv_ae.method, self.cv_fc.method, self.cv_ae.frozen_core, self.cv_fc.frozen_core) != (
                "MP2", "MP2", False, True):
            raise ValueError("The CV increment is explicit same-basis conventional MP2(all-electron minus frozen-core)")
        if self.cv_ae.orbital_basis != "cc-pwCVTZ" or self.cv_fc.orbital_basis != "cc-pwCVTZ":
            raise ValueError("The reviewed same-basis CV increment uses cc-pwCVTZ on both sides")
        if self.cv_ae.model_dump(exclude={"frozen_core"}) != self.cv_fc.model_dump(exclude={"frozen_core"}):
            raise ValueError("All CV settings other than correlated core treatment must match exactly")
        if self.base.cabs != self.mp2_low.cabs:
            raise ValueError("The CC base and MP2 triple-zeta leg must share the explicit CABS")
        if self.base.auxiliary_jk != self.mp2_low.auxiliary_jk:
            raise ValueError("The matched triple-zeta HF calculations must share their fitting basis")
        if self.mp2_low.method == "F12-RI-MP2" and self.base.auxiliary_c != self.mp2_low.auxiliary_c:
            raise ValueError("The RI base and RI-MP2 triple-zeta F12 fitting bases must match")
        if len({(p.scf_integrals, p.scf_convergence) for p in protocols.values()}) != 1:
            raise ValueError("Every composite leg requires a common explicit SCF integral/convergence convention")
        if min(self.denominators()) < 1e-6:
            raise ValueError("CBS extrapolation is numerically ill-conditioned")
        return self

    def protocols(self) -> dict[str, CorrelatedMethod]:
        return {name: getattr(self, name) for name in ("base", "mp2_low", "mp2_high", "cv_ae", "cv_fc")}

    def denominators(self) -> tuple[float, float]:
        return -math.expm1(-self.hf_exponential_alpha), -math.expm1(self.correlation_inverse_power * math.log(3 / 4))


def parse_f12_mp2_partition(raw: str) -> dict[str, float]:
    """Parse the manual's native HF+CABS/correlation decomposition, not E(0) alone.

    This is a partition parser; the parent correlated adapter must separately
    establish version, method, convergence and complete normal termination.
    """
    # Native ORCA repeats this title for the setup banner and the final energy
    # table. Only the table immediately followed by its first physical term
    # constitutes a partition; two complete tables remain ambiguous.
    heading = re.findall(r"(?m)^[ \t]*(?:RI-)?MP2-F12 ENERGY[ \t]*\n[ \t]*-+[ \t]*\n\s*"
                         r"(?=EMP2 correlation Energy[ \t]*:)", raw)
    if len(heading) != 1:
        raise EngineParseError("Expected exactly one native MP2-F12 energy decomposition")
    labels = {
        "orbital_mp2_correlation_hartree": "EMP2 correlation Energy",
        "f12_correlation_correction_hartree": "F12 correction",
        "f12_correlation_hartree": "MP2 basis set limit estimate",
        "hf_hartree": "Hartree-Fock energy",
        "cabs_singles_hartree": "(2)_S CABS correction to EHF",
        "hf_plus_cabs_hartree": "HF basis set limit estimate",
        "mp2_before_f12_hartree": "MP2 total energy before F12",
        "total_f12_correction_hartree": "Total F12 correction",
        "total_hartree": "Final basis set limit MP2 estimate",
    }
    values = {}
    for key, label in labels.items():
        # Genuine ORCA 6.1.1 uses HF for conventional MP2-F12 and EHF for
        # RI-MP2-F12. Both denote the CABS singles correction, not correlation.
        label_pattern = (r"\(2\)_S CABS correction to (?:EHF|HF)" if key == "cabs_singles_hartree"
                         else re.escape(label))
        matches = re.findall(r"(?im)^\s*" + label_pattern + r"\s*:\s*(" + _FLOAT + r")\s*$", raw)
        if len(matches) != 1:
            raise EngineParseError("Native MP2-F12 partition is missing or duplicates " + label)
        values[key] = _number(matches[0])
    sums = [
        ("f12_correlation_hartree", "orbital_mp2_correlation_hartree", "f12_correlation_correction_hartree"),
        ("hf_plus_cabs_hartree", "hf_hartree", "cabs_singles_hartree"),
        ("mp2_before_f12_hartree", "hf_hartree", "orbital_mp2_correlation_hartree"),
        ("total_f12_correction_hartree", "f12_correlation_correction_hartree", "cabs_singles_hartree"),
        ("total_hartree", "hf_plus_cabs_hartree", "f12_correlation_hartree"),
        ("total_hartree", "mp2_before_f12_hartree", "total_f12_correction_hartree"),
    ]
    if any(abs(values[total] - math.fsum([values[a], values[b]])) > 2e-9 for total, a, b in sums):
        raise EngineParseError("Native MP2-F12 HF, CABS and correlation terms do not sum consistently")
    return values


def _native_partition(result: EngineResult) -> dict[str, float]:
    filename = result.diagnostics.get("process", {}).get("stdout_path")
    if not isinstance(filename, str):
        raise IntegrityError("MP2-F12 composite lacks its native stdout provenance")
    path = Path(filename)
    artifacts = [a for a in result.artifacts if a.path == str(path)]
    if (not path.is_absolute() or len(artifacts) != 1 or path.is_symlink() or not path.is_file()
            or path.stat().st_size != artifacts[0].size_bytes or file_digest(path) != artifacts[0].sha256):
        raise IntegrityError("Native MP2-F12 partition artifact differs from its immutable component")
    values = parse_f12_mp2_partition(path.read_text(errors="strict"))
    if result.energy_hartree is None or abs(values["total_hartree"] - result.energy_hartree) > 2e-7:
        raise IntegrityError("MP2-F12 partition and verified native final energy differ")
    return values


def combine_orca_f12_components(energies: dict[str, float], partitions: dict[str, dict[str, float]],
                                protocol: OrcaF12CompositeProtocol) -> dict:
    """Pure explicit arithmetic; the caller must verify native physical evidence."""
    protocol = OrcaF12CompositeProtocol.model_validate(protocol.model_dump())
    if (set(energies) != set(protocol.protocols()) or set(partitions) != {"mp2_low", "mp2_high"}
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in energies.values())):
        raise ValueError("The five finite electronic energies and both native MP2-F12 partitions are required")
    for role, values in partitions.items():
        required = {"hf_plus_cabs_hartree", "f12_correlation_hartree", "total_hartree"}
        if not required <= values.keys() or any(isinstance(values[k], bool) or not isinstance(values[k], (int, float))
                                               or not math.isfinite(values[k]) for k in required):
            raise ValueError("Finite native HF+CABS and F12-correlation components are required")
        if (abs(math.fsum([values["hf_plus_cabs_hartree"], values["f12_correlation_hartree"]]) - values["total_hartree"]) > 2e-9
                or abs(values["total_hartree"] - energies[role]) > 2e-7):
            raise ValueError("MP2-F12 partition does not match its exact native total energy")
    low, high = partitions["mp2_low"], partitions["mp2_high"]
    dhf, dcorr = protocol.denominators()
    hf_cabs_inf = low["hf_plus_cabs_hartree"] + (high["hf_plus_cabs_hartree"] - low["hf_plus_cabs_hartree"]) / dhf
    corr_inf = low["f12_correlation_hartree"] + (high["f12_correlation_hartree"] - low["f12_correlation_hartree"]) / dcorr
    mp2_cbs = math.fsum([hf_cabs_inf, corr_inf])
    cbs_increment = mp2_cbs - energies["mp2_low"]
    cv_increment = energies["cv_ae"] - energies["cv_fc"]
    total = math.fsum([energies["base"], cbs_increment, cv_increment])
    if not all(math.isfinite(v) for v in (hf_cabs_inf, corr_inf, mp2_cbs, cbs_increment, cv_increment, total)):
        raise ValueError("Composite arithmetic produced a nonfinite energy")
    return {"electronic_energy_hartree": total, "hf_plus_cabs_cbs_hartree": hf_cabs_inf,
            "f12_correlation_cbs_hartree": corr_inf, "mp2_f12_cbs_total_hartree": mp2_cbs,
            "cbs_increment_hartree": cbs_increment, "core_valence_increment_hartree": cv_increment,
            "components_hartree": dict(energies), "mp2_f12_partitions": partitions,
            "formula": "E_CCSD(T)-F12D/RI(junTZ) + HF_CABS_inf[exp(-alpha*X)] + Ecorr_MP2-F12_inf[X^-p] - E_MP2-F12(junTZ) + E_MP2(ae,pwCVTZ)-E_MP2(fc,pwCVTZ)",
            "hf_exponential_alpha": protocol.hf_exponential_alpha, "correlation_inverse_power": protocol.correlation_inverse_power,
            "extrapolation_absolute_coefficient_sums": {"hf_plus_cabs": 2/dhf-1, "f12_correlation": 2/dcorr-1},
            "accuracy_claim": None, "published_junchs_f12b_recipe": False}


def execute_orca_f12_composite(workflow, record, store, inputs, deadline: float, cancel_event: Event | None) -> bool:
    """Actual five-leg complex and frozen-fragment calculations, with durable reuse."""
    from .correlated import correlated_input
    from .correlated_workflow import _publish
    from .method_matrix import reviewed_revision

    if record.request.matrix_row_id != "T5-3h" or inputs.source_resolution != SOURCE_RESOLUTION:
        raise ValueError("The ORCA F12D/RI composite requires the explicit reviewed T5-3h source resolution")
    if inputs.orca_f12_composite is None:
        raise ValueError("T5-3h requires every explicit ORCA F12 composite protocol and extrapolation choice")
    protocol = OrcaF12CompositeProtocol.model_validate(inputs.orca_f12_composite.model_dump())
    fragments = split_fragments(record.request.molecule)
    if len(fragments) < 2:
        raise ValueError("Frozen interaction energy requires at least two complete state-resolved fragments")
    molecules = [record.request.molecule, *fragments]
    # Reject unsupported charge/spin/environment/resource combinations for all
    # components before any expensive native calculation is launched.
    for molecule in molecules:
        for native in protocol.protocols().values():
            correlated_input(molecule, native, record.request.resources)
    details, identities = {}, set()
    for index, molecule in enumerate(molecules):
        role = "complex" if index == 0 else f"fragment-{index-1}"
        geometry_deadline = deadline
        if record.request.per_geometry_budget_seconds is not None:
            geometry_deadline = min(deadline, time.monotonic() + record.request.per_geometry_budget_seconds)
        energies, references, partitions = {}, {}, {}
        for component, native in protocol.protocols().items():
            result = run_component(workflow, record, store, f"orca-F12D-composite-{role}-{component}", molecule,
                                   native, run_correlated, geometry_deadline, cancel_event)
            if result is None:
                return False
            energies[component] = result.energy_hartree
            references[component] = result.metadata.get("native_result", {}).get("reference_energy_hartree")
            identities.add((result.engine_version, result.metadata.get("executable_sha256")))
            if component in {"mp2_low", "mp2_high"}:
                partitions[component] = _native_partition(result)
                parsed_hf = partitions[component]["hf_hartree"]
                if references[component] is not None and abs(references[component] - parsed_hf) > 2e-8:
                    raise IntegrityError("Native SCF reference and the F12 partition refer to different HF solutions")
                references[component] = parsed_hf
        if any(isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float))
               or not math.isfinite(a) or not math.isfinite(b) or abs(a-b) > 2e-8
               for a, b in ((references["base"], references["mp2_low"]), (references["cv_ae"], references["cv_fc"]))):
            raise IntegrityError("Matched-basis composite legs do not establish the same actual HF reference solution")
        if cancel_event is not None and cancel_event.is_set() or time.monotonic() >= geometry_deadline:
            record.status = "cancelled" if cancel_event is not None and cancel_event.is_set() else "timed-out"
            record.metadata["termination_reason"] = "ORCA F12 composite geometry budget ended before derived-result publication"
            store.commit(record)
            return False
        details[role] = combine_orca_f12_components(energies, partitions, protocol)
    if len(identities) != 1 or not all(next(iter(identities))):
        raise IntegrityError("ORCA F12 composite mixed engine versions or executable identities")
    if cancel_event is not None and cancel_event.is_set() or time.monotonic() >= deadline:
        record.status = "cancelled" if cancel_event is not None and cancel_event.is_set() else "timed-out"
        record.metadata["termination_reason"] = "ORCA F12 composite stopped before derived-result publication"
        store.commit(record)
        return False
    interaction = details["complex"]["electronic_energy_hartree"] - math.fsum(
        value["electronic_energy_hartree"] for key, value in details.items() if key != "complex")
    _publish(record, store, "T5-3h", {"recipe": protocol.convention, "output_kind": "frozen-interaction-energy",
        "definition": "Same-protocol ORCA F12D/RI + split MP2-F12 CBS + MP2 CV energy of the complex minus the sum of frozen-inc fragment energies",
        "interaction_energy_hartree": interaction, "component_details": details,
        "protocols": [protocol.model_dump(mode="json")], "engine_identity": list(next(iter(identities))),
        "source_resolution": SOURCE_RESOLUTION, "reviewed_method_revision": reviewed_revision(SOURCE_RESOLUTION),
        "source_difference": "Explicit ORCA F12D/RI variant and split HF+CABS/correlation extrapolation, not the original F12b recipe",
        "counterpoise_applied": False, "geometry_state": "frozen-inc", "geometry_optimized": False,
        "binding_energy_hartree": None, "gibbs_energy_hartree": None, "accuracy_claim": None,
        "published_junchs_f12b_recipe": False, "sources": [F12_SOURCE],
        "scope": "Exact chosen ORCA composite approximation; native execution does not establish the source F12b A14 benchmark"})
    return True
