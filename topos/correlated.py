"""Typed, native ORCA correlated calculations with explicit basis/core choices.

The orbital label ``*-F12`` never selects an F12 Hamiltonian. F12D, F12b,
canonical CCSD(T), and local DLPNO-CCSD(T1) remain distinct protocols. Input and
parser validation are conditional until an installed licensed engine executes.
"""
from __future__ import annotations

import hashlib
import math
import re
import shutil
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable, Literal

from pydantic import Field, model_validator

from .base_integration import BaseRuntime
from .chemistry import atomic_number
from .engines import (
    EngineParseError,
    EngineResult,
    _engine_version,
    _number,
    _orca_convergence,
    _orca_version_input,
    artifact_inventory,
    parse_orca_engrad,
    read_xyz,
)
from .models import Contract, Molecule, ResourceLimits
from .orca_basis_names import resolve_orca_orbital_basis, validate_basis_elements
from .runtime import available_cpu_count
from .storage import atomic_json, digest_json

MDCI_SOURCE = "https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/mdci.html"
AUTOCI_SOURCE = "https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/autoci.html"
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
ORBITAL_BASES = frozenset(
    [f"{prefix}cc-pV{zeta}Z" for prefix in ("", "aug-") for zeta in ("D", "T", "Q", "5")]
    + [f"jun-cc-pV{zeta}Z" for zeta in ("D", "T", "Q")]
    + [f"cc-pV{zeta}Z-F12" for zeta in ("D", "T", "Q")]
    + [f"cc-pwCV{zeta}Z" for zeta in ("D", "T", "Q", "5")]
    + ["def2-SVP", "def2-TZVP", "def2-TZVPP", "def2-QZVPP"]
)
AUXILIARY_BASES = frozenset([f"cc-pV{zeta}Z/C" for zeta in ("D", "T", "Q", "5")]
                          + [f"cc-pV{zeta}Z/JK" for zeta in ("T", "Q", "5")]
                          + ["def2/JK", "def2-SVP/C", "def2-TZVP/C", "def2-TZVPP/C", "def2-QZVPP/C"])
CABS_BASES = frozenset(f"cc-pV{zeta}Z-F12-CABS" for zeta in ("D", "T", "Q"))


class CorrelatedMethod(Contract):
    engine: Literal["orca"] = "orca"
    engine_version: Literal["6.1.1"] = "6.1.1"
    method: Literal["MP2", "AUTOCI-CCSD(T)", "CCSD(T)", "DLPNO-CCSD(T1)", "CCSD(T)-F12D/RI", "F12-MP2", "F12-RI-MP2"]
    operation: Literal["energy", "gradient", "optimize"] = "energy"
    orbital_basis: str
    frozen_core: bool
    auxiliary_c: str | None = None
    auxiliary_jk: str | None = None
    cabs: str | None = None
    scf_integrals: Literal["conventional", "RIJK"] = "conventional"
    scf_convergence: Literal["TightSCF", "VeryTightSCF"] = "VeryTightSCF"
    pno_profile: Literal["TightPNO"] | None = None
    tcutpno: Literal[1e-6, 1e-7] | None = None
    integral_handling: Literal["native", "KC_AOBLAS"] = "native"
    local_energy_decomposition: bool = False
    max_iterations: int = Field(default=200, ge=1, le=2000)

    @model_validator(mode="after")
    def exact_protocol(self):
        if self.orbital_basis not in ORBITAL_BASES:
            raise ValueError("Orbital basis is outside the explicit correlated adapter grammar")
        if self.auxiliary_c is not None and (self.auxiliary_c not in AUXILIARY_BASES or not self.auxiliary_c.endswith("/C")):
            raise ValueError("An explicit supported correlation fitting /C basis is required")
        if self.auxiliary_jk is not None and (self.auxiliary_jk not in AUXILIARY_BASES or not self.auxiliary_jk.endswith("/JK")):
            raise ValueError("An explicit supported Coulomb/exchange /JK basis is required")
        if (self.scf_integrals == "RIJK") != (self.auxiliary_jk is not None):
            raise ValueError("RIJK and its fitting basis must be explicitly selected together")
        f12 = self.method in {"CCSD(T)-F12D/RI", "F12-MP2", "F12-RI-MP2"}
        if f12:
            if self.cabs not in CABS_BASES:
                raise ValueError("F12 requires an explicit supported CABS; an F12 orbital label is insufficient")
            if self.operation != "energy":
                raise ValueError("ORCA 6.1 F12 gradients are unavailable; an energy cannot be promoted to an optimized geometry")
        elif self.cabs is not None:
            raise ValueError("A CABS does not turn a conventional correlated method into F12")
        needs_aux = self.method in {"DLPNO-CCSD(T1)", "CCSD(T)-F12D/RI", "F12-RI-MP2"}
        if needs_aux != (self.auxiliary_c is not None):
            raise ValueError("The correlation fitting basis must match the selected RI/local method")
        local = self.method == "DLPNO-CCSD(T1)"
        if local:
            if self.pno_profile != "TightPNO" or self.tcutpno is None or self.operation != "energy":
                raise ValueError("DLPNO requires explicit TightPNO, TCutPNO and an energy operation; no analytic DLPNO gradient is assumed")
        elif self.pno_profile is not None or self.tcutpno is not None or self.local_energy_decomposition:
            raise ValueError("PNO and LED options apply only to the local DLPNO method")
        if self.integral_handling == "KC_AOBLAS" and self.method != "CCSD(T)":
            raise ValueError("MDCI AO-direct controls cannot be silently applied to AUTOCI or F12")
        if self.method == "CCSD(T)" and self.operation != "energy":
            raise ValueError("Choose the explicit AUTOCI analytic-gradient backend for canonical CCSD(T) derivatives")
        return self


def correlated_basis_support(molecule: Molecule, protocol: CorrelatedMethod) -> dict[str, dict]:
    """Resolve exact orbital spelling and preflight every native basis role."""
    basis = resolve_orca_orbital_basis(molecule, protocol.orbital_basis)
    return {role: validate_basis_elements(name, role, molecule.symbols)
            for role, name in (("orbital", basis["native_basis"]), ("auxiliary_c", protocol.auxiliary_c),
                               ("auxiliary_jk", protocol.auxiliary_jk), ("cabs", protocol.cabs)) if name}


def correlated_resource_allocation(molecule: Molecule, protocol: CorrelatedMethod,
                                   resources: ResourceLimits) -> tuple[ResourceLimits, dict[str, Any]]:
    """Bound F12 MPI ranks by a demonstrable occupied-pair space.

    ORCA's MDCI distributes occupied pairs, including diagonal pairs. Frozen
    cores for heavier atoms are native method choices; do not guess them from
    atomic numbers. H/He have no core orbitals, while an explicit all-electron
    NoFrozenCore reference establishes zero frozen orbitals through Kr.
    """
    numbers = [atomic_number(symbol) for symbol in molecule.symbols]
    electrons = sum(numbers) - molecule.charge
    receipt = {"requested_threads": resources.threads, "effective_threads": resources.threads,
               "policy": "requested-allocation", "proven_occupied_pair_count": None,
               "requested_maxcore_mb": int(resources.memory_mb * .75 / resources.threads),
               "effective_maxcore_mb": int(resources.memory_mb * .75 / resources.threads),
               "maxcore_policy": "preserve requested per-rank bound when reducing MPI ranks",
               "source": MDCI_SOURCE}
    if protocol.method not in {"CCSD(T)-F12D/RI", "F12-MP2", "F12-RI-MP2"}:
        return resources, receipt
    zero_core_scope = ("H/He have no core orbitals" if all(number <= 2 for number in numbers)
                       else "explicit all-electron NoFrozenCore through Kr"
                       if not protocol.frozen_core and all(number <= 36 for number in numbers) else None)
    if zero_core_scope is None:
        receipt["policy"] = "requested-allocation; native frozen-core pair count not established"
        return resources, receipt
    if molecule.multiplicity != 1 or electrons <= 0 or electrons % 2:
        raise ValueError("F12 pair allocation requires occupied closed-shell physical electrons")
    occupied = electrons // 2
    pairs = occupied * (occupied + 1) // 2
    threads = min(resources.threads, pairs)
    receipt.update(policy="F12 occupied-pair MPI bound", effective_threads=threads,
                   physical_electrons=electrons, proven_frozen_core_orbitals=0,
                   core_count_evidence=zero_core_scope, occupied_orbitals=occupied,
                   proven_occupied_pair_count=pairs, pair_count_formula="nocc * (nocc + 1) // 2")
    return resources.model_copy(update={"threads": threads}), receipt


def correlated_input(molecule: Molecule, protocol: CorrelatedMethod, resources: ResourceLimits) -> str:
    if molecule.multiplicity != 1:
        raise ValueError("This correlated profile requires closed-shell RHF; open-shell reference semantics must be specified separately")
    if molecule.environment not in ({}, {"phase": "gas"}):
        raise ValueError("The explicit correlated profile is gas phase")
    if resources.device != "cpu" or resources.threads > available_cpu_count():
        raise ValueError("Correlated ORCA requires a valid CPU allocation; no GPU substitution")
    if resources.memory_mb * .75 < 16 * resources.threads:
        raise ValueError("Insufficient memory for explicit per-rank MaxCore and driver reserve")
    maxcore_mb = int(resources.memory_mb * .75 / resources.threads)
    resources, _ = correlated_resource_allocation(molecule, protocol, resources)
    basis = resolve_orca_orbital_basis(molecule, protocol.orbital_basis)
    correlated_basis_support(molecule, protocol)
    keywords = ["RHF", protocol.method, basis["native_basis"], protocol.scf_convergence,
                "FrozenCore" if protocol.frozen_core else "NoFrozenCore"]
    keywords.extend(value for value in (protocol.auxiliary_c, protocol.auxiliary_jk, protocol.cabs, protocol.pno_profile) if value)
    keywords.extend(["RIJK", "NOCOSX"] if protocol.scf_integrals == "RIJK" else ["NOCOSX"])
    if protocol.local_energy_decomposition:
        keywords.append("LED")
    if protocol.operation == "optimize":
        # Opt and EnGrad select different native run types; verify the final
        # geometry using an independent gradient job under the same budget.
        keywords.append("Opt")
    elif protocol.operation == "gradient":
        keywords.append("Engrad")
    lines = ["! " + " ".join(keywords), f"%pal nprocs {resources.threads} end",
             f"%maxcore {maxcore_mb}"]
    if protocol.operation == "optimize":
        lines.extend(["%geom", f"  MaxIter {protocol.max_iterations}", "  TolE 1e-7", "  TolMaxG 1e-5",
                      "  TolRMSG 3e-6", "  TolRMSD 5e-5", "  TolMaxD 1e-4", "  InHess Lindh", "end"])
    if protocol.method == "DLPNO-CCSD(T1)":
        lines.extend(["%mdci", f"  TCutPNO {protocol.tcutpno:.12g}", "  StorageType Shared"])
        if protocol.local_energy_decomposition:
            if len(molecule.fragments) != 2 or len(molecule.fragment_states) != 2:
                raise ValueError("LED requires exactly two explicit physical fragments and their electronic states")
        lines.append("end")
    elif protocol.integral_handling == "KC_AOBLAS":
        lines.extend(["%mdci", "  KCOpt KC_AOBLAS", "end"])
    lines.append(f"* xyz {molecule.charge} {molecule.multiplicity}")
    for index, (symbol, xyz) in enumerate(zip(molecule.symbols, molecule.coordinates, strict=True)):
        fragment = next((i + 1 for i, group in enumerate(molecule.fragments) if index in group), None)
        label = f"{symbol}({fragment})" if protocol.local_energy_decomposition else symbol
        lines.append(label + " " + " ".join(format(value, ".16g") for value in xyz))
    lines.extend(["*", ""])
    return "\n".join(lines)


def parse_correlated_output(raw: str, protocol: CorrelatedMethod) -> dict[str, Any]:
    """Validate native termination and method-specific energy evidence, never HF alone."""
    if (_engine_version(raw, "orca") != "6.1.1" or "ORCA TERMINATED NORMALLY" not in raw
            or "SCF CONVERGED AFTER" not in raw or re.search(r"SCF NOT CONVERGED|SCF CONVERGENCE FAILURE", raw, re.I)):
        raise EngineParseError("Correlated output lacks versioned normal termination and SCF convergence")
    if re.search(r"(?:CCSD|MDCI|AUTOCI).*?(?:NOT CONVERGED|FAILED TO CONVERGE)|MDCI ERROR TERMINATION", raw, re.I):
        raise EngineParseError("Native correlated solver failed to converge")
    matches = re.findall(r"FINAL SINGLE POINT ENERGY\s+(" + _FLOAT + r")", raw)
    if not matches:
        raise EngineParseError("Final native correlated electronic energy absent")
    energy = _number(matches[-1])
    # Input echo alone is not method evidence: require an actual result block.
    patterns = {
        "MP2": [r"MP2 TOTAL ENERGY\s*[:=]\s*(" + _FLOAT + r")", r"Total Energy\s*:\s*(" + _FLOAT + r")\s*Eh\s*\n.*?MP2"],
        "CCSD(T)": [r"E\(CCSD\(T\)\)\s*(?:[:=]|\.\.\.)\s*(" + _FLOAT + r")"],
        "AUTOCI-CCSD(T)": [r"(?:E\(CCSD\(T\)\)|Total CCSD\(T\) energy)\s*(?:[:=]|\.\.\.)\s*(" + _FLOAT + r")"],
        "DLPNO-CCSD(T1)": [r"E\(CCSD\(T1?\)\)\s*(?:[:=]|\.\.\.)\s*(" + _FLOAT + r")"],
        "CCSD(T)-F12D/RI": [r"(?:E\(CCSD\(T\)-F12(?:D)?\)|Final (?:basis set limit )?CCSD\(T\)(?:-F12)? (?:energy|estimate))\s*(?:[:=]|\.\.\.)\s*(" + _FLOAT + r")",
                           # ORCA 6.1.1 prints the unscaled triples result with
                           # this prefix. The neighboring scaled-(T) estimate
                           # is a different quantity and must not match.
                           r"(?m)^\s*F12-E\(CCSD\(T\)\)\s*\.\.\.\s*(" + _FLOAT + r")\s*$"],
        "F12-MP2": [r"Final basis set limit MP2 estimate\s*:\s*(" + _FLOAT + r")"],
        "F12-RI-MP2": [r"Final basis set limit MP2 estimate\s*:\s*(" + _FLOAT + r")"],
    }
    observed = [_number(match) for pattern in patterns[protocol.method] for match in re.findall(pattern, raw, re.I)]
    if not observed or abs(observed[-1] - energy) > 2e-7:
        raise EngineParseError("Final total energy is not confirmed by the requested correlated method's native result block")
    reference_energy, reference_sources = _reference_energy(raw)
    observation = {"energy_hartree": energy, "method_result_energy_hartree": observed[-1],
            "method": protocol.method, "orbital_basis": protocol.orbital_basis,
            "frozen_core": protocol.frozen_core, "f12_hamiltonian": protocol.method in {"CCSD(T)-F12D/RI", "F12-MP2", "F12-RI-MP2"},
            "reference_energy_hartree": reference_energy,
            "reference_energy_sources": reference_sources,
            "total_correlation_energy_hartree": energy - reference_energy if reference_energy is not None else None,
            "total_correlation_energy_scope": (
                "total minus uncorrected orbital HF; includes the HF basis correction for F12, not the pure F12 correlation partition"
                if protocol.method in {"CCSD(T)-F12D/RI", "F12-MP2", "F12-RI-MP2"}
                else "total minus orbital HF reference"),
            "method_identity_scope": "explicit native input protocol plus native correlated result block; version-specific live acceptance remains separate"}
    if protocol.local_energy_decomposition:
        observation["local_energy_decomposition"] = parse_led(raw, energy)
    return observation


def _reference_energy(raw: str) -> tuple[float | None, dict[str, float]]:
    """Read only native orbital HF labels, excluding CABS-corrected estimates.

    MP2 does not print E(0). Its TOTAL SCF ENERGY section supplies the same
    reference, at higher precision. For optimization output use each label's
    final evaluation, and reject disagreement between available labels.
    """
    patterns = {
        "total_scf_energy": (r"(?m)^\s*TOTAL SCF ENERGY\s*\n[ \t]*-+[ \t]*\n\s*"
                             r"Total Energy[ \t]*:[ \t]*(" + _FLOAT + r")[ \t]+Eh\b"),
        "e_zero": r"(?m)^\s*E\(0\)\s*(?:[:=]|\.\.\.)\s*(" + _FLOAT + r")",
        "f12_hartree_fock": r"(?m)^\s*Hartree-Fock energy\s*:\s*(" + _FLOAT + r")\s*$",
    }
    values = {}
    for label, pattern in patterns.items():
        matches = re.findall(pattern, raw)
        if matches:
            values[label] = _number(matches[-1])
    if not values:
        return None, {}
    reference = next(iter(values.values()))
    if any(abs(value - reference) > 2e-8 for value in values.values()):
        raise EngineParseError("Native orbital HF reference labels disagree")
    return reference, values


def parse_led(raw: str, total_energy: float) -> dict[str, Any]:
    """Parse the complete LED sum, keeping interaction and interfragment terms distinct."""
    heading = "INTER- vs INTRA-FRAGMENT TOTAL ENERGIES (Eh)"
    if heading not in raw:
        raise EngineParseError("The complete LED energy decomposition is absent")
    block = raw.rsplit(heading, 1)[1]
    terms = {}
    for key, label in (("intra_fragment_total_hartree", "Sum of INTRA-fragment total energies"),
                       ("inter_fragment_total_hartree", "Sum of INTER-fragment total energies"),
                       ("total_hartree", "Total energy")):
        found = re.search(re.escape(label) + r"\s*[:=]\s*(" + _FLOAT + r")", block, re.I)
        if found is None:
            raise EngineParseError("LED decomposition is missing a total-energy component")
        terms[key] = _number(found.group(1))
    if (abs(terms["total_hartree"] - total_energy) > 2e-7 or
            abs(terms["intra_fragment_total_hartree"] + terms["inter_fragment_total_hartree"] - total_energy) > 2e-7):
        raise EngineParseError("Native LED components do not sum to the correlated electronic energy")
    terms["interpretation"] = "native intra/interfragment decomposition; interfragment LED term is not a binding energy or frozen-monomer interaction energy"
    terms["source"] = "https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/led.html#example"
    return terms


def run_correlated(molecule: Molecule, protocol: CorrelatedMethod, resources: ResourceLimits,
                   workdir: str | Path, *, executable: str | Path | None = None,
                   process_runner: Callable[..., Any] | None = None,
                   cancel_event: Event | None = None) -> EngineResult:
    result = EngineResult(status="unsupported", engine="orca", method=protocol.method, operation=protocol.operation,
                          metadata={"execution_kind": "not-executed", "adapter_validation": "conditional-not-live-validated",
                                    "requested_protocol": protocol.model_dump(mode="json"),
                                    "protocol_sha256": digest_json(protocol.model_dump(mode="json")),
                                    "resources": resources.model_dump(mode="json"), "sources": [MDCI_SOURCE, AUTOCI_SOURCE]})
    started = time.monotonic()
    folder = Path(workdir).resolve()
    try:
        deck = correlated_input(molecule, protocol, resources)
        effective_resources, allocation = correlated_resource_allocation(molecule, protocol, resources)
        result.metadata["effective_resources"] = effective_resources.model_dump(mode="json")
        result.metadata["resource_allocation"] = allocation
        result.metadata["orbital_basis_resolution"] = resolve_orca_orbital_basis(molecule, protocol.orbital_basis)
        result.metadata["basis_support_receipts"] = correlated_basis_support(molecule, protocol)
        runtime = None
        if process_runner is None:
            runtime = BaseRuntime()
            runtime.validate_resources(resources)
            executable = runtime.resolve_executable("orca", executable)
            process_runner = runtime.run_process
        binary = shutil.which(str(executable or "orca"))
        if binary is None:
            result.status, result.diagnostics["reason"] = "unavailable", "The requested licensed ORCA executable is unavailable"
            return result
        binary = str(Path(binary).resolve())
        if folder.exists() and any(folder.iterdir()):
            raise ValueError("A correlated engine attempt requires a fresh directory; completed results are reused by the workflow ledger")
        folder.mkdir(parents=True, exist_ok=True)
        result.metadata.update(executable=binary, executable_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest())
        atomic_json(folder / "protocol.json", protocol.model_dump(mode="json"))
        (folder / "version.inp").write_text(_orca_version_input(resources))

        def limits(*, diagnostic=False):
            remaining = resources.budget_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("Correlated attempt deadline reached")
            return effective_resources.model_copy(update={"budget_seconds": min(10.0, remaining) if diagnostic else remaining,
                                                          "threads": 1 if diagnostic else effective_resources.threads})

        probe = process_runner([binary, "version.inp"], folder, limits(diagnostic=True),
                               log_prefix="version", cancel_event=cancel_event, threads_per_process=1)
        result.diagnostics["version_probe"] = probe.to_dict()
        raw_probe = Path(probe.stdout_path).read_text(errors="replace")
        if probe.status != "completed":
            result.status, result.diagnostics["reason"] = probe.status, probe.reason
            return result
        if (_engine_version(raw_probe, "orca") != protocol.engine_version or "ORCA TERMINATED NORMALLY" not in raw_probe
                or "SCF CONVERGED AFTER" not in raw_probe or "FINAL SINGLE POINT ENERGY" not in raw_probe):
            result.status, result.diagnostics["reason"] = "unavailable", "Native serial version/loader probe failed"
            return result
        result.engine_version = protocol.engine_version
        (folder / "job.inp").write_text(deck)
        result.command = [binary, "job.inp"]
        result.metadata["execution_kind"] = "real"
        process = process_runner(result.command, folder, limits(), cancel_event=cancel_event,
                                 log_prefix="engine", threads_per_process=1)
        result.diagnostics["process"] = process.to_dict()
        result.status = process.status
        if process.status != "completed":
            result.diagnostics["reason"] = process.reason
            return result
        raw = Path(process.stdout_path).read_text(errors="replace")
        observation = parse_correlated_output(raw, protocol)
        result.metadata["native_result"] = observation
        result.energy_hartree = observation["energy_hartree"]
        result.molecule = read_xyz(folder / "job.xyz", molecule) if protocol.operation == "optimize" else molecule
        if protocol.operation == "gradient":
            energy, gradient = parse_orca_engrad(folder / "job.engrad", result.molecule)
            if abs(energy - result.energy_hartree) > 2e-7:
                raise EngineParseError("Correlated derivative and native energy refer to different results")
            result.gradient_hartree_per_bohr = gradient
        result.converged = True
        if protocol.operation == "optimize":
            criteria = _orca_convergence(raw)
            result.diagnostics["convergence"] = criteria
            result.converged = len(criteria) == 5 and all(criteria.values()) and "THE OPTIMIZATION HAS CONVERGED" in raw
            if not result.converged:
                result.status = "partial"
            else:
                if cancel_event is not None and cancel_event.is_set():
                    result.status, result.converged = "cancelled", False
                    result.diagnostics["reason"] = "Cancelled before independent final correlated gradient"
                    return result
                gradient_protocol = protocol.model_copy(update={"operation": "gradient"})
                final = run_correlated(result.molecule, gradient_protocol, limits(), folder / "final-gradient",
                                       executable=binary, process_runner=process_runner, cancel_event=cancel_event)
                result.diagnostics["final_gradient"] = {"status": final.status, "diagnostics": final.diagnostics,
                    "command": final.command, "elapsed_seconds": final.elapsed_seconds}
                if (final.status != "completed" or final.converged is not True
                        or final.gradient_hartree_per_bohr is None or final.energy_hartree is None):
                    result.status = final.status if final.status != "completed" else "failed"
                    result.converged = False
                    result.diagnostics["reason"] = "Independent final correlated gradient did not complete"
                    return result
                if (final.engine_version != result.engine_version
                        or final.metadata.get("executable_sha256") != result.metadata["executable_sha256"]
                        or abs(final.energy_hartree - result.energy_hartree) > 2e-7):
                    raise EngineParseError("Correlated optimization and final gradient disagree in executable, version or energy")
                result.gradient_hartree_per_bohr = final.gradient_hartree_per_bohr
                stationarity = _stationarity(final.gradient_hartree_per_bohr)
                result.diagnostics["independent_stationarity"] = stationarity
                result.metadata["final_gradient_verification"] = {
                    "execution_kind": "real", "protocol": gradient_protocol.model_dump(mode="json"),
                    "directory": "final-gradient", "energy_hartree": final.energy_hartree,
                    "energy_difference_hartree": final.energy_hartree - result.energy_hartree,
                    "budget_scope": "remaining original attempt wall budget"}
                result.converged = stationarity["passed"]
                if not result.converged:
                    result.status = "partial"
                    result.diagnostics["reason"] = "Independent final correlated gradient is not stationary"
                if cancel_event is not None and cancel_event.is_set() or time.monotonic() - started >= resources.budget_seconds:
                    result.status = "cancelled" if cancel_event is not None and cancel_event.is_set() else "timed-out"
                    result.converged = False
                    result.diagnostics["reason"] = "Correlated attempt stopped before final-gradient publication"
        result.metadata["stationary_point_classification"] = "unclassified; no frequency Hessian"
        return result
    except TimeoutError as exc:
        result.status, result.diagnostics["reason"] = "timed-out", str(exc)
        result.converged = False
        return result
    except (ValueError, RuntimeError, OSError) as exc:
        result.status, result.diagnostics["reason"] = "failed" if result.metadata["execution_kind"] == "real" else "unsupported", str(exc)
        result.converged = False
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - started
        if folder.is_dir():
            result.artifacts = artifact_inventory(folder)


def _stationarity(gradient: list[list[float]]) -> dict[str, Any]:
    """Independent Cartesian gradient check; this does not classify a minimum."""
    if not gradient or any(len(row) != 3 for row in gradient):
        raise EngineParseError("Final correlated gradient requires three components per atom")
    values = [component for row in gradient for component in row]
    if any(not math.isfinite(value) for value in values):
        raise EngineParseError("Final correlated gradient is not finite")
    maximum = max(abs(value) for value in values)
    rms = math.sqrt(math.fsum(value * value for value in values) / len(values))
    return {"max_gradient_hartree_per_bohr": maximum, "rms_gradient_hartree_per_bohr": rms,
            "max_gradient_threshold": 1e-5, "rms_gradient_threshold": 3e-6,
            "passed": maximum <= 1e-5 and rms <= 3e-6,
            "scope": "independent final EnGrad; no Hessian classification"}
