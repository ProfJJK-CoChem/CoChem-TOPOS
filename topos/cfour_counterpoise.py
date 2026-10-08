"""Conditional native CFOUR relaxed-total counterpoise geometry bracket.

The two branches optimize eight component surfaces each. Every CP displacement
rebuilds all physical and ghost legs. This is neither an interaction-only
optimization nor a Hessian-certified minimum. Native CFOUR 2.1 correlated ghost
acceptance remains separate from this documented, fail-closed implementation.
"""
from __future__ import annotations

import math
import re
import shutil
import time
from importlib.metadata import version
from pathlib import Path
from threading import Event
from typing import Any, Literal

import numpy as np
from pydantic import Field, StrictInt, model_validator

from .base_integration import BaseRuntime
from .cfour_artifacts import finalize_artifacts, native_text
from .chemistry import atomic_number
from .engines import EngineParseError, EngineResult, _number
from .external_engines import (
    _FLOAT,
    ExternalProtocol,
    _native_completion,
    _native_genbas,
    _native_invocations,
    _ncc_total_energy,
    _physical_input,
    _proper_rotation,
    cfour_input,
)
from .fragments import split_fragments
from .higher_composite import (
    HigherGeometryProtocol,
    NumericalGeometryOptions,
    _ComponentStop,
    checked_energy_gradient,
    combine_higher_geometry,
)
from .matrix_components import run_component
from .models import Contract, Molecule, ResourceLimits
from .science import BOHR_ANGSTROM, rotational_constants, validate_stereochemical_preservation
from .storage import IntegrityError, atomic_json, digest_json, file_digest

SOURCES = [
    "https://github.com/MolSSI/QCElemental/blob/v0.51.2/qcelemental/molparse/to_string.py",
    "https://github.com/MolSSI/QCEngine/blob/v0.51.0/qcengine/programs/cfour/runner.py",
    "https://github.com/MolSSI/QCEngine/blob/v0.51.0/qcengine/programs/cfour/harvester.py",
    "https://github.com/RagnarB83/ash/blob/f43c421f3bca48e3740bab7a10acb5a2676246a0/ash/interfaces/interface_CFour.py",
]


class BasisCenter(Contract):
    """A basis site is not a physical atom or an electron-counting Molecule."""

    symbol: str
    atom_id: str = Field(min_length=1)
    coordinates: list[float]
    physical: bool

    @model_validator(mode="after")
    def valid(self):
        if not 1 <= atomic_number(self.symbol) <= 10:
            raise ValueError("The explicit conventional CFOUR CP profile is limited to H–Ne")
        if len(self.coordinates) != 3 or not all(math.isfinite(v) for v in self.coordinates):
            raise ValueError("A basis center requires three finite angstrom coordinates")
        return self


class CfourCounterpoiseLeg(ExternalProtocol):
    """Basis-center geometry and physical occupied-core choice enter cache identity."""

    basis_centers: list[BasisCenter] = Field(min_length=1)
    dropped_core_orbitals: int = Field(ge=0)

    @model_validator(mode="after")
    def exact_leg(self):
        if (self.engine, self.engine_version, self.operation) != ("cfour", "2.1", "energy"):
            raise ValueError("Counterpoise legs require scalar CFOUR 2.1 energies")
        if self.method not in {"CCSD(T)", "CCSDT", "CCSDTQ"}:
            raise ValueError("This high-composite leg supports CCSD(T), ECC CCSDT and NCC CCSDTQ")
        if not self.genbas_path or not self.genbas_sha256:
            raise ValueError("Every CP leg requires its pinned native GENBAS")
        if not self.frozen_core and self.dropped_core_orbitals:
            raise ValueError("All-electron legs cannot drop occupied orbitals")
        if len({c.atom_id for c in self.basis_centers}) != len(self.basis_centers):
            raise ValueError("Basis center atom identities must be unique")
        return self


class CfourCounterpoiseGeometryProtocol(Contract):
    geometry: HigherGeometryProtocol
    numerical: NumericalGeometryOptions
    core_orbitals_by_atom: list[StrictInt] = Field(min_length=1)
    convention: Literal["relaxed-total-CP-geometry-CBS-CV-fT-fQ-v1"]

    @model_validator(mode="after")
    def nonnegative_core(self):
        if any(type(n) is not int or n < 0 for n in self.core_orbitals_by_atom):
            raise ValueError("Core selection requires explicit nonnegative integer occupied orbitals per physical atom")
        return self

    def validate_molecule(self, molecule: Molecule) -> list[Molecule]:
        molecule = Molecule.model_validate(molecule.model_dump())
        monomers = split_fragments(molecule)
        if molecule.multiplicity != 1 or any(m.multiplicity != 1 for m in monomers):
            raise ValueError("CFOUR CP requires explicit closed-shell singlet fragments and complex")
        if molecule.environment not in ({}, {"phase": "gas"}):
            raise ValueError("CFOUR CP describes gas-phase electronic potentials")
        if len(self.core_orbitals_by_atom) != len(molecule.symbols):
            raise ValueError("Core orbital choices must cover every physical complex atom once")
        for symbol, core in zip(molecule.symbols, self.core_orbitals_by_atom, strict=True):
            z = atomic_number(symbol)
            if not 1 <= z <= 10 or core != (0 if z <= 2 else 1):
                raise ValueError("This conventional H–Ne core profile requires H/He=0 and Li–Ne=1 occupied core orbital per physical nucleus; arbitrary atom-local selection is unsupported")
        for group, physical in [(list(range(len(molecule.symbols))), molecule), *zip(molecule.fragments, monomers, strict=True)]:
            electrons = sum(atomic_number(s) for s in physical.symbols) - physical.charge
            if 2 * sum(self.core_orbitals_by_atom[i] for i in group) >= electrons:
                raise ValueError("Each physical complex/fragment must retain correlated occupied electrons")
        combine_higher_geometry({role: molecule for role in self.geometry.protocols()}, self.geometry)
        return monomers


def _validate_leg(molecule: Molecule, protocol: CfourCounterpoiseLeg) -> None:
    physical = [c for c in protocol.basis_centers if c.physical]
    actual = [(c.symbol, c.atom_id, c.coordinates) for c in physical]
    expected = list(zip(molecule.symbols, molecule.atom_ids, molecule.coordinates, strict=True))
    if actual != expected:
        raise ValueError("Physical molecule must exactly match the indexed physical basis centers")
    electrons = sum(atomic_number(s) for s in molecule.symbols) - molecule.charge
    expected_core = sum(0 if atomic_number(s) <= 2 else 1 for s in molecule.symbols) if protocol.frozen_core else 0
    if protocol.dropped_core_orbitals != expected_core:
        raise ValueError("DROPMO must select the conventional H–Ne count of lowest occupied orbitals; arbitrary atom-local selection is unsupported")
    if molecule.multiplicity != 1 or protocol.dropped_core_orbitals * 2 >= electrons:
        raise ValueError("Dropped orbitals must belong to occupied physical electrons, leaving a correlated space")


def counterpoise_legs(molecule: Molecule, native: ExternalProtocol,
                       core_orbitals_by_atom: list[int]) -> list[tuple[str, float, Molecule, CfourCounterpoiseLeg]]:
    """E_AB + sum(E_i own − E_i ghost), with full movable basis inventory."""
    monomers = split_fragments(molecule)
    if any(type(n) is not int or n < 0 for n in core_orbitals_by_atom):
        raise ValueError("Physical core choices must be nonnegative integers")
    if len(core_orbitals_by_atom) != len(molecule.symbols):
        raise ValueError("Core choices do not match the complex atom inventory")
    if any(not 1 <= atomic_number(symbol) <= 10 or count != (0 if atomic_number(symbol) <= 2 else 1)
           for symbol, count in zip(molecule.symbols, core_orbitals_by_atom, strict=True)):
        raise ValueError("Conventional H–Ne core counts must be H/He=0 and Li–Ne=1; no atom-local orbital projection is inferred")
    result = []
    for name, coefficient, physical, group, ghost in [
        ("complex", 1., molecule, list(range(len(molecule.symbols))), False),
        *[(f"fragment-{i}-{kind}", sign, monomer, group, ghosts)
          for i, (group, monomer) in enumerate(zip(molecule.fragments, monomers, strict=True))
          for kind, sign, ghosts in (("own", 1., False), ("ghost", -1., True))],
    ]:
        included = list(range(len(molecule.symbols))) if ghost else group
        centers = [BasisCenter(symbol=molecule.symbols[i], atom_id=molecule.atom_ids[i],
                               coordinates=molecule.coordinates[i], physical=i in group) for i in included]
        if ghost and group != sorted(group):
            raise ValueError("CP fragment partitions must use ascending native atom indices; no silent bond remapping")
        leg = CfourCounterpoiseLeg.model_validate({**native.model_dump(), "operation": "energy",
              "basis_centers": [c.model_dump() for c in centers],
              "dropped_core_orbitals": sum(core_orbitals_by_atom[i] for i in group) if native.frozen_core else 0})
        _validate_leg(physical, leg)
        result.append((name, coefficient, physical, leg))
    return result


def cfour_counterpoise_input(molecule: Molecule, protocol: CfourCounterpoiseLeg,
                             resources: ResourceLimits) -> str:
    _physical_input(molecule, resources)
    protocol = CfourCounterpoiseLeg.model_validate(protocol.model_dump())
    _validate_leg(molecule, protocol)
    plain = ExternalProtocol.model_validate({k: v for k, v in protocol.model_dump().items()
                                            if k in ExternalProtocol.model_fields})
    ordinary = cfour_input(molecule, plain, resources)
    controls = ordinary.split("*CFOUR(", 1)[1].rsplit(")", 1)[0]
    controls = re.sub(r"BASIS=[^,\n]+", "BASIS=SPECIAL", controls)
    controls = re.sub(r"FROZEN_CORE=(?:ON|OFF)", "FROZEN_CORE=OFF", controls)
    controls = re.sub(r"ABCDTYPE=[^,\n]+", "ABCDTYPE=STANDARD", controls)
    controls = re.sub(r"\nCC_PROG=[^,\n]+", "", controls)
    controls += "\nCC_PROG=" + {"CCSD(T)": "VCC", "CCSDT": "ECC", "CCSDTQ": "NCC"}[protocol.method]
    if protocol.dropped_core_orbitals:
        controls += f"\nDROPMO=1>{protocol.dropped_core_orbitals}"
    lines = ["CoChem TOPOS explicit relaxed-total counterpoise energy"]
    lines.extend((c.symbol if c.physical else "GH") + " " + " ".join(format(v, ".16g") for v in c.coordinates)
                 for c in protocol.basis_centers)
    lines.extend(["", "*CFOUR(" + controls + ")", ""])
    lines.extend(c.symbol.upper() + ":" + protocol.orbital_basis for c in protocol.basis_centers)
    return "\n".join(lines) + "\n\n"


_GEOMETRY = re.compile(r"(?m)^[ \t]*Symbol[ \t]+Number[ \t]+X[ \t]+Y[ \t]+Z[ \t]*\n"
    r"[ \t]*-+[ \t]*\n(?P<rows>(?:[ \t]*[A-Za-z]+[ \t]+(?:\d+|\*\*\*)[ \t]+" + _FLOAT +
    r"[ \t]+" + _FLOAT + r"[ \t]+" + _FLOAT + r"[ \t]*\n)+)[ \t]*-+[ \t]*")


def _native_basis_geometry(raw: str, protocol: CfourCounterpoiseLeg) -> tuple[np.ndarray, str]:
    """Parse original GH inventory directly; no invented atomic ghost species."""
    matches = list(_GEOMETRY.finditer(raw))
    if len(matches) != 1:
        raise EngineParseError("Exactly one native indexed basis-center coordinate table is required")
    table = matches[0]
    rows = [line.split() for line in table.group("rows").splitlines()]
    if len(rows) != len(protocol.basis_centers):
        raise EngineParseError("Native basis-center count differs from the requested inventory")
    for fields, center in zip(rows, protocol.basis_centers, strict=True):
        if center.physical:
            valid = fields[0].upper() == center.symbol.upper() and fields[1] == str(atomic_number(center.symbol))
        else:
            valid = fields[0].upper() == "GH" and fields[1] in {"110", "***"}
        if not valid:
            raise EngineParseError("Native physical/ghost indexed basis-center identity differs")
    xyz = np.array([[_number(v) for v in row[-3:]] for row in rows]) * BOHR_ANGSTROM
    _proper_rotation(xyz, np.array([c.coordinates for c in protocol.basis_centers]))
    # QCEngine's energy-only harvesting must not assign a fictitious element to
    # GH. Remove its independently validated geometry block, preserving every
    # energy/control byte and the untouched original output artifact.
    return xyz, raw[:table.start()] + raw[table.end():]


def _drop_selection(value: str) -> set[int]:
    value = value.strip()
    if value == "NONE":
        return set()
    if re.fullmatch(r"\d+>\d+", value):
        first, last = map(int, value.split(">"))
        if first > last:
            raise EngineParseError("Reversed native DROPMO range")
        return set(range(first, last + 1))
    if re.fullmatch(r"\d+(?:[ \t,-]+\d+)*", value):
        if "-" in value:
            raise EngineParseError("Undocumented native DROPMO range grammar")
        return {int(v) for v in re.split(r"[ \t,]+", value)}
    raise EngineParseError("Unsupported native DROPMO output; cannot establish physical core space")


def _native_zmat_echo(raw: str) -> str:
    """Read the genuine dashed and asterisk-bordered ZMAT echo layouts only."""
    lines = raw.splitlines()
    titles = [i for i, line in enumerate(lines) if "Input from ZMAT file" in line]
    controls = [i for i, line in enumerate(lines) if "CFOUR Control Parameters" in line]
    if len(titles) != 1 or len(controls) != 1:
        raise EngineParseError("Native ZMAT echo and control section must each occur exactly once")
    start, control = titles[0], controls[0]
    title = lines[start].strip()
    if title == "Input from ZMAT file":
        marker = "-"
    elif re.fullmatch(r"\*[ \t]+Input from ZMAT file[ \t]+\*", title):
        marker = "*"
    else:
        raise EngineParseError("Unsupported native ZMAT echo title framing")
    if (start < 1 or control <= start + 3 or control + 1 >= len(lines)
            or not re.fullmatch(re.escape(marker) + r"{10,}", lines[start - 1].strip())
            or lines[start - 1].strip() != lines[start + 1].strip()
            or lines[control].strip() != "CFOUR Control Parameters"
            or not re.fullmatch(r"-{10,}", lines[control - 1].strip())
            or lines[control - 1].strip() != lines[control + 1].strip()):
        raise EngineParseError("Native ZMAT/control section delimiters are incomplete or inconsistent")
    end = control - 1
    if marker == "*":
        end -= 1
        while end > start + 1 and not lines[end].strip():
            end -= 1
        if lines[end].strip() != lines[start - 1].strip():
            raise EngineParseError("Native asterisk-bordered ZMAT echo lacks its closing delimiter")
    body = "\n".join(lines[start + 2:end])
    if len(re.findall(r"(?m)^[ \t]*\*(?:CFOUR|ACES2)\(", body)) != 1:
        raise EngineParseError("Native ZMAT echo requires exactly one input control block")
    return body


def _native_counterpoise_control(raw: str, name: str) -> str:
    """Require one actual native control row; input keywords are not proof."""
    found = re.findall(r"(?m)^[ \t]*" + name + r"[ \t]+\w+[ \t]+([^\n]+)", raw)
    if len(found) != 1:
        raise EngineParseError("Missing/ambiguous native control " + name)
    return re.split(r"[ \t]+\[|[ \t]+\*\*\*", found[0])[0].strip()


def parse_cfour_counterpoise_output(raw: str, molecule: Molecule,
                                     protocol: CfourCounterpoiseLeg) -> dict[str, Any]:
    _validate_leg(molecule, protocol)
    observed = _native_completion(raw, protocol)
    if len(re.findall(r"SCF has converged\.", raw)) != 1:
        raise EngineParseError("Counterpoise leg requires one SCF evaluation")

    def control(name: str) -> str:
        return _native_counterpoise_control(raw, name)

    expected = {"BASIS": "SPECIAL", "FROZEN_CORE": "OFF", "REFERENCE": "RHF", "CHARGE": str(molecule.charge),
        "MULTIPLICTY": "1", "ABCDTYPE": "STANDARD", "SYMMETRY": "OFF", "SPHERICAL": "ON",
        "CC_PROGRAM": {"CCSD(T)": "VCC", "CCSDT": "ECC", "CCSDTQ": "NCC"}[protocol.method]}
    for key, value in expected.items():
        if control(key) != value:
            raise EngineParseError("Native counterpoise control differs: " + key)
    if control("CALC_?LEVEL") not in {protocol.method, protocol.method.replace("(T)", "[T]")}:
        raise EngineParseError("Native correlated method differs from requested CP leg")
    if control("DERIV_LEV(?:EL)?") != "ZERO":
        raise EngineParseError("A CP numerical leg must be a scalar energy calculation")
    if _drop_selection(control("DROPMO")) != set(range(1, protocol.dropped_core_orbitals + 1)):
        raise EngineParseError("Native occupied-core DROPMO space differs from the physical fragment choice")
    solver = {"CCSD(T)": "xvcc", "CCSDT": "xecc", "CCSDTQ": "xncc"}[protocol.method]
    if solver not in _native_invocations(raw):
        raise EngineParseError("Requested native CC solver was not actually invoked")
    echoed = _native_zmat_echo(raw)
    basis = re.findall(r"(?m)^[ \t]*([A-Za-z]+):([^\s]+)[ \t]*$", echoed)
    wanted = [(c.symbol.upper(), protocol.orbital_basis.upper()) for c in protocol.basis_centers]
    if [(s.upper(), b.upper()) for s, b in basis] != wanted:
        raise EngineParseError("Native per-center SPECIAL basis map differs from original element/basis inventory")
    _, energy_text = _native_basis_geometry(raw, protocol)
    if version("qcengine") != "0.51.0" or version("qcelemental") != "0.51.2":
        raise EngineParseError("CFOUR CP energy harvesting requires pinned QCEngine 0.51.0/QCElemental 0.51.2")
    from qcengine.programs.cfour.harvester import harvest_outfile_pass

    qcvars, _, _, _, _, error = harvest_outfile_pass(energy_text)
    electrons = sum(atomic_number(s) for s in molecule.symbols) - molecule.charge
    if error or any(int(qcvars.get(key, -1)) != electrons // 2 for key in ("N ALPHA ELECTRONS", "N BETA ELECTRONS")):
        raise EngineParseError("Native alpha/beta populations do not establish the physical fragment electron count")
    xyz = np.asarray(molecule.coordinates) / BOHR_ANGSTROM
    charges = [atomic_number(symbol) for symbol in molecule.symbols]
    repulsion = math.fsum(charges[i] * charges[j] / float(np.linalg.norm(xyz[i] - xyz[j]))
                         for i in range(len(charges)) for j in range(i))
    if abs(_number(str(qcvars.get("NUCLEAR REPULSION ENERGY", "nan"))) - repulsion) > 3e-7:
        raise EngineParseError("Native nuclear repulsion does not match physical nuclei; ghosts carry no charge")
    if int(qcvars.get("N BASIS FUNCTIONS", 0)) < electrons // 2:
        raise EngineParseError("Native AO basis-function count is absent or inconsistent")
    key = protocol.method + " TOTAL ENERGY"
    if key not in qcvars or "SCF TOTAL ENERGY" not in qcvars:
        raise EngineParseError("Requested correlated CP total energy is absent")
    total, reference = _number(str(qcvars[key])), _number(str(qcvars["SCF TOTAL ENERGY"]))
    if protocol.method == "CCSDTQ" and abs(total - _ncc_total_energy(raw, protocol.method)) > 1e-10:
        raise EngineParseError("NCC/QCEngine full-quadruples totals disagree")
    return {"engine_version": observed, "energy_hartree": total, "reference_energy_hartree": reference,
        "physical_electrons": electrons, "dropped_occupied_orbitals": sorted(range(1, protocol.dropped_core_orbitals + 1)),
        "basis_centers": [c.model_dump(mode="json") for c in protocol.basis_centers],
        "basis_functions": int(qcvars["N BASIS FUNCTIONS"]), "ghost_geometry_validated": True,
        "gradient_hartree_per_bohr": None, "parser": {"qcengine": "0.51.0", "qcelemental": "0.51.2"},
        "energy_harvest_geometry_excluded": True}


def run_cfour_counterpoise_leg(molecule: Molecule, protocol: CfourCounterpoiseLeg, resources: ResourceLimits,
                               workdir: str | Path, *, executable=None, process_runner=None,
                               cancel_event: Event | None = None) -> EngineResult:
    started, folder = time.monotonic(), Path(workdir).resolve()
    result = EngineResult(status="unsupported", engine="cfour", method=protocol.method, operation="energy",
        metadata={"execution_kind": "not-executed", "adapter_validation": "conditional-not-live-validated",
                  "requested_protocol": protocol.model_dump(mode="json"), "sources": SOURCES})
    try:
        protocol = CfourCounterpoiseLeg.model_validate(protocol.model_dump())
        text = cfour_counterpoise_input(molecule, protocol, resources)
        if cancel_event is not None and cancel_event.is_set():
            result.status = "cancelled"
            return result
        if folder.exists() and any(folder.iterdir()):
            raise ValueError("CFOUR CP requires a fresh native attempt directory")
        if process_runner is None:
            runtime = BaseRuntime()
            runtime.validate_resources(resources)
            executable, process_runner = runtime.resolve_executable("cfour", executable), runtime.run_process
        resolved = shutil.which(str(executable or "xcfour"))
        if resolved is None:
            result.status, result.diagnostics["reason"] = "unavailable", "Audited CFOUR executable is unavailable"
            return result
        binary = Path(resolved).resolve()
        # Every ghost element must also exist in this exact native GENBAS. A
        # separate physical Molecule avoids changing fragment charge or spin.
        plain = ExternalProtocol.model_validate({k: v for k, v in protocol.model_dump().items() if k in ExternalProtocol.model_fields})
        library = _native_genbas(binary, plain, molecule)
        library_text = library.read_text()
        for center in protocol.basis_centers:
            if not re.search(r"(?mi)^" + re.escape(center.symbol) + ":" + re.escape(protocol.orbital_basis) + r"\s*$", library_text):
                raise ValueError("Native GENBAS lacks a requested real/ghost element basis")
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(library, folder / "GENBAS")
        if file_digest(folder / "GENBAS") != protocol.genbas_sha256:
            raise IntegrityError("GENBAS changed during CP staging")
        (folder / "ZMAT").write_text(text)
        atomic_json(folder / "protocol.json", protocol.model_dump(mode="json"))
        immutable = {path: file_digest(path) for path in (binary, library, folder / "ZMAT", folder / "GENBAS", folder / "protocol.json")}
        result.metadata.update(executable_sha256=immutable[binary],
            basis_library={"sha256": immutable[library], "path": str(library)},
            native_input_sha256={path.name: immutable[path] for path in (folder / "ZMAT", folder / "GENBAS", folder / "protocol.json")},
            core_convention="Lowest occupied spatial orbitals, count=sum(H/He:0; Li–Ne:1) over physical nuclei only; no atom-local orbital projection")
        remaining = resources.budget_seconds - (time.monotonic() - started)
        if remaining <= 0:
            result.status = "timed-out"
            return result
        result.command = [str(binary)]
        process = process_runner(result.command, folder, resources.model_copy(update={"budget_seconds": remaining}),
                                 cancel_event=cancel_event, log_prefix="engine")
        result.metadata["execution_kind"], result.diagnostics["process"] = "real", process.to_dict()
        result.status = process.status
        for path, expected_sha256 in immutable.items():
            if path.is_symlink() or not path.is_file() or file_digest(path) != expected_sha256:
                raise IntegrityError("Native CP immutable executable/basis/input changed during execution: " + path.name)
        if process.status != "completed":
            result.diagnostics["reason"] = process.reason
            return result
        native = parse_cfour_counterpoise_output(native_text(folder, "engine.stdout", required=True, process_path=process.stdout_path), molecule, protocol)
        atomic_json(folder / "native-result.json", native)
        result.energy_hartree, result.molecule, result.engine_version = native["energy_hartree"], molecule, native["engine_version"]
        result.metadata.update(native_result=native, adapter_validation="native-output-validated-for-this-execution")
        if cancel_event is not None and cancel_event.is_set():
            result.status = "cancelled"
        elif time.monotonic() - started > resources.budget_seconds:
            result.status = "timed-out"
        else:
            result.status, result.converged = "completed", True
        return result
    except (ValueError, RuntimeError, OSError, ImportError, KeyError) as exc:
        result.status = "failed" if result.metadata["execution_kind"] == "real" else "unsupported"
        result.diagnostics["reason"] = str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - started
        if folder.is_dir():
            finalize_artifacts(result, folder)


def _optimize_surface(workflow, record, store, native: ExternalProtocol, specification: CfourCounterpoiseGeometryProtocol,
                      branch: Literal["raw", "cp"], role: str, deadline: float, cancel_event: Event | None):
    from scipy.optimize import minimize

    from .workflow import _topology_preserved

    initial, options = record.request.molecule, specification.numerical
    evaluated, derivatives, identities = {}, {}, set()

    def check():
        if cancel_event is not None and cancel_event.is_set() or time.monotonic() >= deadline:
            record.status = "cancelled" if cancel_event is not None and cancel_event.is_set() else "timed-out"
            record.metadata["termination_reason"] = "Counterpoise geometry shared campaign boundary reached"
            store.commit(record)
            raise _ComponentStop()

    def energy(x):
        check()
        current = Molecule.model_validate({**initial.model_dump(), "coordinates": (x.reshape(-1, 3) * BOHR_ANGSTROM).tolist()})
        key = digest_json(current.coordinates)
        if key not in evaluated:
            terms = []
            legs = counterpoise_legs(current, native, specification.core_orbitals_by_atom)
            for name, weight, physical, leg in (legs if branch == "cp" else legs[:1]):
                # Full typed physical/basis-center geometry is already in the
                # ledger identity. Stable role keys also reuse own-fragment
                # energies when only a partner/ghost center moved.
                result = run_component(workflow, record, store, f"cfour-cp-{role}-{name}", physical,
                    leg, run_cfour_counterpoise_leg, deadline, cancel_event)
                if result is None:
                    raise _ComponentStop()
                if result.energy_hartree is None:
                    raise IntegrityError("CP numerical displacement lacks a native total electronic energy")
                identities.add((result.engine_version, result.metadata.get("executable_sha256"),
                                result.metadata.get("basis_library", {}).get("sha256")))
                terms.append(weight * result.energy_hartree)
            evaluated[key] = math.fsum(terms)
        return evaluated[key]

    def evaluate(x):
        check()
        key = digest_json(x.tolist())
        if key not in derivatives:
            derivatives[key] = checked_energy_gradient(energy, x, options)
        value, gradient, _ = derivatives[key]
        return value, gradient

    optimized = minimize(evaluate, np.asarray(initial.coordinates).ravel() / BOHR_ANGSTROM,
        jac=True, method="L-BFGS-B", options={"maxiter": options.maximum_iterations, "maxls": 30,
            "ftol": 1e-15, "gtol": min(options.gradient_max_hartree_per_bohr, options.gradient_rms_hartree_per_bohr) / 2})
    value, gradient = evaluate(optimized.x)
    sensitivity = derivatives[digest_json(optimized.x.tolist())][2]
    margin = sensitivity["maximum_step_disagreement_hartree_per_bohr"]
    maximum, rms = float(np.max(np.abs(gradient))), float(np.sqrt(np.mean(gradient**2)))
    if maximum + margin > options.gradient_max_hartree_per_bohr or rms + margin > options.gradient_rms_hartree_per_bohr:
        record.status, record.metadata["termination_reason"] = "partial", "Counterpoise component failed gradient convergence including step sensitivity"
        store.commit(record)
        raise _ComponentStop()
    molecule = Molecule.model_validate({**initial.model_dump(), "coordinates": (optimized.x.reshape(-1, 3) * BOHR_ANGSTROM).tolist()})
    if not _topology_preserved(initial, molecule) or validate_stereochemical_preservation(initial, molecule)["status"] != "preserved":
        raise ValueError("Counterpoise component changed topology or stereochemistry")
    check()
    return molecule, {"branch": branch, "potential_hartree": value, "potential_definition": "E_AB + sum(E_i own - E_i ghost)" if branch == "cp" else "E_AB",
        "gradient_hartree_per_bohr": gradient.reshape(-1, 3).tolist(), "maximum_gradient_hartree_per_bohr": maximum,
        "rms_gradient_hartree_per_bohr": rms, "derivative_sensitivity": sensitivity,
        "energy_geometries": len(evaluated), "iterations": int(optimized.nit), "message": str(optimized.message),
        "analytic_gradient": False, "minimum_hessian_verified": False}, identities


def execute_cfour_counterpoise_recipe(workflow, record, store, inputs, deadline: float,
                                       cancel_event: Event | None) -> bool:
    from .external_matrix_workflow import _publish
    from .method_matrix import reviewed_revision

    try:
        resolution = "cfour-relaxed-counterpoise-geometry-v1"
        if (record.request.matrix_row_id != "T3O-1w" or inputs.external_resolution != resolution
                or getattr(inputs, "source_resolution", None) != resolution):
            raise ValueError("T3O-1w requires its explicit cfour-relaxed-counterpoise-geometry-v1 source resolution")
        if inputs.cfour_counterpoise is None:
            raise ValueError("Explicit cfour_counterpoise bases, chart, occupied-core choices and numerical thresholds are required")
        specification = CfourCounterpoiseGeometryProtocol.model_validate(inputs.cfour_counterpoise.model_dump())
        specification.validate_molecule(record.request.molecule)
        if record.request.per_geometry_budget_seconds is not None:
            deadline = min(deadline, time.monotonic() + record.request.per_geometry_budget_seconds)
        geometries, diagnostics, identities = {"raw": {}, "cp": {}}, {"raw": {}, "cp": {}}, set()
        protocols = {role: ExternalProtocol.model_validate({**native.model_dump(), "operation": "energy"})
                     for role, native in specification.geometry.protocols().items()}
        for branch in ("raw", "cp"):
            for role, native in protocols.items():
                molecule, diagnostic, observed = _optimize_surface(workflow, record, store, native, specification,
                                                                    branch, role, deadline, cancel_event)
                geometries[branch][role], diagnostics[branch][role] = molecule, diagnostic
                identities.update(observed)
        if len(identities) != 1 or not all(next(iter(identities))):
            raise IntegrityError("Counterpoise bracket mixed native version, executable or basis-library bytes")
        combined = {branch: combine_higher_geometry(values, specification.geometry) for branch, values in geometries.items()}
        identity = next(iter(identities))
        output = {"row_id": "T3O-1w", "output_kind": "counterpoise-bracketed-composite-geometries",
            "source_resolution": inputs.external_resolution, "reviewed_method_revision": reviewed_revision(resolution),
            "protocol": specification.model_dump(mode="json"),
            "component_attempt_ids": [a.attempt_id for a in record.attempts if a.status == "completed"
                and str(a.metadata.get("component_key", "")).startswith("cfour-cp-")],
            "engine_version": identity[0], "executable_sha256": identity[1], "genbas_sha256": identity[2],
            "branches": {branch: {"geometry_composite": value, "molecule": value["molecule"],
                "equilibrium_rotational_constants_mhz": [v * 1000 if v is not None else None for v in rotational_constants(
                    Molecule.model_validate(value["molecule"]))["constants_ghz"]]} for branch, value in combined.items()},
            "component_optimization_evidence": diagnostics, "counterpoise_bracket_computed": True,
            "bracket_interpretation": "Raw/CP sensitivity bracket; no statistical uncertainty or averaged geometry",
            "minimum_hessian_verified": False, "composite_stationarity_verified": False,
            "composite_electronic_energy_hartree": None, "native_cfour_optimizer": False,
            "vibrational_correction_applied": False, "accuracy_claim": None,
            "restart_scope": "Verified native displacement energies; optimizer restarts from common input, never restored CC amplitudes"}
        if cancel_event is not None and cancel_event.is_set() or time.monotonic() >= deadline:
            record.status = "cancelled" if cancel_event is not None and cancel_event.is_set() else "timed-out"
            record.metadata["termination_reason"] = "Counterpoise campaign boundary reached before publication"
            store.commit(record)
            return False
        _publish(record, store, output)
        return True
    except IntegrityError:
        raise
    except _ComponentStop:
        return False
    except (ValueError, RuntimeError, OSError) as exc:
        record.status, record.metadata["termination_reason"] = "unsupported" if not record.attempts else "partial", str(exc)
        store.commit(record)
        return False
