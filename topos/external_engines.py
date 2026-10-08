"""Explicit external-engine protocols; unavailable engines never become results.

CFOUR Cartesian derivatives are evaluated natively. TOPOS may drive an
unconstrained L-BFGS optimization with those actual derivatives; it does not
pretend that a single point is a geometry optimization. Psi4 SAPT2+3 uses its
documented Python API. Molpro F12 and MPQC remain unresolved protocol choices.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from collections import Counter
from pathlib import Path
from threading import Event
from typing import Any, Callable, Literal

import numpy as np
from pydantic import Field, model_validator

from .base_integration import BaseRuntime
from .cfour_artifacts import finalize_artifacts, native_text
from .cfour_controls import native_control_value
from .cfour_dependencies import require_cfour_parsers
from .cfour_efg import parse_cfour_efg
from .cfour_properties import CfourEfgConventionDeclaration
from .engines import EngineParseError, EngineResult, _number, artifact_inventory
from .fragments import split_fragments
from .models import Contract, Molecule, ResourceLimits
from .science import BOHR_ANGSTROM
from .storage import atomic_json, digest_json, file_digest

PSI4_REVISION = "23be3de4b1f6cd70e337b98a2a200008cf350274"
SOURCES = [
    f"https://github.com/psi4/psi4/blob/{PSI4_REVISION}/doc/sphinxman/source/cfour.rst",
    f"https://github.com/psi4/psi4/blob/{PSI4_REVISION}/doc/sphinxman/source/sapt.rst",
    "https://github.com/MolSSI/QCEngine/tree/v0.51.0/qcengine/programs/cfour",
    "https://github.com/RagnarB83/ash-documentation/blob/1230964f43ebe62fa894527794d9b85b39ecbf96/docs/CFour-interface.rst#L120-L134",
]
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
_BASIS = re.compile(r"[A-Za-z0-9][A-Za-z0-9+*()._-]{0,79}\Z")
_CFOUR_METHODS = {"HF": "SCF", "MP2": "MP2", "CCSD": "CCSD", "CCSD(T)": "CCSD[T]", "CCSDT": "CCSDT", "CCSDTQ": "CCSDTQ"}


class ExternalProtocol(Contract):
    engine: Literal["cfour", "psi4", "molpro", "mpqc"]
    engine_version: str = Field(min_length=1, max_length=40)
    operation: Literal["energy", "gradient", "optimize", "first-order-properties", "sapt-decomposition"]
    method: str
    orbital_basis: str
    frozen_core: bool
    reference: Literal["RHF"] = "RHF"
    genbas_path: str | None = None
    genbas_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    auxiliary_scf_basis: str | None = None
    auxiliary_sapt_basis: str | None = None
    scf_convergence: int = Field(default=10, ge=8, le=14)
    cc_convergence: int = Field(default=10, ge=8, le=14)
    max_iterations: int = Field(default=200, ge=1, le=2000)
    gradient_max_hartree_per_bohr: float = Field(default=1e-5, gt=0, le=1e-4)
    gradient_rms_hartree_per_bohr: float = Field(default=3e-6, gt=0, le=1e-4)
    sapt_natural_orbitals: Literal[False] = False
    efg_convention: CfourEfgConventionDeclaration | None = None

    @model_validator(mode="after")
    def exact_choices(self):
        for label in (self.orbital_basis, self.auxiliary_scf_basis, self.auxiliary_sapt_basis):
            if label is not None and not _BASIS.fullmatch(label):
                raise ValueError("Basis must be a literal native basis name, without commands or paths")
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+", self.engine_version):
            raise ValueError("An exact native engine version is required")
        if (self.genbas_path is None) != (self.genbas_sha256 is None):
            raise ValueError("GENBAS location and checksum must be supplied together")
        if self.efg_convention is not None and (self.engine != "cfour"
                or self.operation != "first-order-properties" or self.method != "CCSD(T)"
                or self.engine_version != self.efg_convention.engine_version):
            raise ValueError("An EFG convention declaration requires the exact CFOUR 2.1 CCSD(T) FIRST_ORDER protocol")
        if self.engine == "cfour":
            if self.method not in _CFOUR_METHODS or self.operation == "sapt-decomposition":
                raise ValueError("Unsupported CFOUR method/operation; higher increments require their own verified adapter")
            if self.auxiliary_scf_basis or self.auxiliary_sapt_basis:
                raise ValueError("The CFOUR conventional-integral profile does not use fitting bases")
            if self.method == "CCSDTQ" and (self.operation != "energy" or self.engine_version != "2.1"):
                raise ValueError("Public CFOUR 2.1 NCC full quadruples are energy-only here; no analytic derivative is inferred")
        elif self.engine == "psi4":
            if self.method != "SAPT2+3" or self.operation != "sapt-decomposition":
                raise ValueError("This Psi4 adapter supports the explicit SAPT2+3 branch only")
            if not self.auxiliary_scf_basis or not self.auxiliary_sapt_basis:
                raise ValueError("SAPT2+3 requires explicit SCF and SAPT fitting bases")
            if self.genbas_path is not None:
                raise ValueError("GENBAS belongs only to CFOUR")
        elif self.genbas_path or self.auxiliary_scf_basis or self.auxiliary_sapt_basis:
            raise ValueError("Unresolved Molpro/MPQC protocols cannot borrow CFOUR/Psi4 options")
        return self


def _physical_input(molecule: Molecule, resources: ResourceLimits) -> None:
    Molecule.model_validate(molecule.model_dump())
    ResourceLimits.model_validate(resources.model_dump())
    if molecule.multiplicity != 1:
        raise ValueError("The external profiles require closed-shell singlets; no open-shell substitution")
    if molecule.environment not in ({}, {"phase": "gas"}):
        raise ValueError("These external profiles specify gas phase only")
    if resources.device != "cpu":
        raise ValueError("No GPU implementation is established for these explicit external profiles")


def cfour_input(molecule: Molecule, protocol: ExternalProtocol, resources: ResourceLimits) -> str:
    """Native Cartesian ZMAT for one evaluation; optimization is an outer driver."""
    _physical_input(molecule, resources)
    protocol = ExternalProtocol.model_validate(protocol.model_dump())
    if protocol.engine != "cfour":
        raise ValueError("CFOUR input requires a CFOUR protocol")
    gradient = protocol.operation in {"gradient", "optimize"}
    properties = protocol.operation == "first-order-properties"
    lines = ["CoChem TOPOS explicit native CFOUR evaluation"]
    lines.extend(symbol + " " + " ".join(format(x, ".16g") for x in xyz)
                 for symbol, xyz in zip(molecule.symbols, molecule.coordinates, strict=True))
    options = [f"CALC_LEVEL={_CFOUR_METHODS[protocol.method]}", f"BASIS={protocol.orbital_basis}",
               "REFERENCE=RHF", f"CHARGE={molecule.charge}", "MULTIPLICITY=1",
               "COORDINATES=CARTESIAN", "UNITS=ANGSTROM", "SYMMETRY=OFF", "SPHERICAL=ON",
               "ABCDTYPE=" + ("STANDARD" if protocol.method in {"CCSDT", "CCSDTQ"} else "AOBASIS"),
               f"FROZEN_CORE={'ON' if protocol.frozen_core else 'OFF'}",
               f"SCF_CONV={protocol.scf_convergence}", f"CC_CONV={protocol.cc_convergence}",
               f"LINEQ_CONV={protocol.cc_convergence}", "MEM_UNIT=INTEGERWORDS",
               f"MEMORY_SIZE={int(resources.memory_mb * 1024**2 * .75 / 8)}"]
    if protocol.method in {"CCSDT", "CCSDTQ"}:
        options.append("CC_PROG=" + ("NCC" if protocol.method == "CCSDTQ" else "ECC"))
    options.append("PROPS=FIRST_ORDER" if properties else f"DERIV_LEVEL={'FIRST' if gradient else 'ZERO'}")
    # Use the newline-only control grammar of native CFOUR/QCEngine; a comma
    # immediately before a newline can produce an empty keyword field.
    lines.extend(["", "*CFOUR(" + "\n".join(options) + ")", ""])
    return "\n".join(lines) + "\n"


def _proper_rotation(native: np.ndarray, requested: np.ndarray) -> np.ndarray:
    """Require the exact indexed geometry, allowing only translation/rotation."""
    native, requested = np.asarray(native), np.asarray(requested)
    if native.shape != requested.shape or native.ndim != 2 or native.shape[1] != 3:
        raise EngineParseError("Native atom inventory does not match the requested geometry")
    a, b = native - native.mean(axis=0), requested - requested.mean(axis=0)
    u, _, vt = np.linalg.svd(a.T @ b)
    correction = np.eye(3)
    correction[-1, -1] = np.linalg.det(u @ vt)
    rotation = u @ correction @ vt
    if np.max(np.linalg.norm(a @ rotation - b, axis=1)) > 2e-6:
        raise EngineParseError("CFOUR geometry changed, atom order changed, or only an improper reflection matches")
    return rotation


def _dipole_in_requested_frame(vector_atomic_units: list[float], native_angstrom: np.ndarray,
                               molecule: Molecule) -> list[float]:
    """A charged molecule's total dipole also changes with the coordinate origin."""
    requested = np.asarray(molecule.coordinates)
    rotation = _proper_rotation(native_angstrom, requested)
    shift_bohr = (requested.mean(axis=0) - native_angstrom.mean(axis=0) @ rotation) / BOHR_ANGSTROM
    return (np.asarray(vector_atomic_units) @ rotation + molecule.charge * shift_bohr).tolist()


def _cfour_cc_converged(raw: str, method: str) -> bool:
    """Accept native VCC/ECC or the exact requested NCC iteration completion."""
    ncc = re.search(r"(?m)^\s*" + re.escape(method) + r" iterations converged in\s+\d+\s+cycles\b", raw)
    if method == "CCSDTQ":
        return ncc is not None
    return ncc is not None or re.search(r"Amplitude equations converged|CC iterations have converged", raw) is not None


def _ncc_total_energy(raw: str, method: str) -> float:
    """Exact native NCC total after converged iterations; never an MRCC label."""
    convergence = r"(?m)^\s*" + re.escape(method) + r" iterations converged in\s+\d+\s+cycles\b"
    matches = re.findall(r"(?m)^\s*Total " + re.escape(method) + r" energy:\s*(" + _FLOAT + r")\s*$", raw)
    if len(matches) != 1 or not re.search(convergence, raw):
        raise EngineParseError("The requested NCC method lacks one converged native total energy")
    return _number(matches[0])


def _native_invocations(raw: str) -> list[str]:
    """Read both actual CFOUR invocation layouts, retaining every event."""
    programs = []
    lines = raw.splitlines()
    for index, line in enumerate(lines):
        heading = re.fullmatch(r"[ \t]*--invoking executable(.*)", line)
        if heading is None:
            continue
        suffix = heading[1]
        if suffix.strip() == "--":
            token = lines[index + 1].strip() if index + 1 < len(lines) else ""
        else:
            inline = re.fullmatch(r"[ \t]+(\S+)[ \t]*", suffix)
            if inline is None:
                raise EngineParseError("Malformed native CFOUR executable invocation separator")
            token = inline[1]
        if not token or re.search(r"\s", token) or token == "--":
            raise EngineParseError("Malformed native CFOUR executable invocation")
        name = Path(token).name
        if re.fullmatch(r"x[A-Za-z0-9_]+", name) is None:
            raise EngineParseError("Unknown native CFOUR executable invocation")
        programs.append(name)
    return programs


def _native_completion(raw: str, protocol: ExternalProtocol) -> str:
    native_versions = re.findall(r"(?im)^\s*version\s+([\w.+-]+)\s*$", raw)
    if not native_versions or set(native_versions) != {protocol.engine_version}:
        raise EngineParseError("CFOUR output does not establish the exact requested native version")
    if "SCF has converged." not in raw or re.search(r"(?:SCF|CC|AMPLITUDE).*?(?:NOT CONVERGED|FAILED TO CONVERGE)", raw, re.I):
        raise EngineParseError("CFOUR SCF/correlation convergence was not established")
    if protocol.method.startswith("CC") and not _cfour_cc_converged(raw, protocol.method):
        raise EngineParseError("The requested coupled-cluster amplitude equations did not converge")
    invoked = Counter(_native_invocations(raw))
    finished = re.findall(r"--executable\s+(\S+)\s+finished with status\s+(-?\d+)", raw)
    if not invoked or Counter(name for name, _ in finished) != invoked or any(int(status) for _, status in finished):
        raise EngineParseError("CFOUR native subprogram termination is incomplete or unsuccessful")
    return native_versions[-1]


def parse_cfour_output(raw: str, molecule: Molecule, protocol: ExternalProtocol,
                       *, grd: str | None = None, dipol: str | None = None,
                       efg: str | None = None) -> dict[str, Any]:
    """Interpret one actual Cartesian evaluation, never an earlier optimization step."""
    harvest_GRD, harvest_outfile_pass = require_cfour_parsers()

    observed_version = _native_completion(raw, protocol)
    def control(name: str) -> str:
        return native_control_value(raw, name)

    native_basis = control("BASIS")
    if native_basis.lower() != protocol.orbital_basis.lower():
        raise EngineParseError("The native basis setting differs from the explicit requested basis")
    if control("FROZEN_CORE") != ("ON" if protocol.frozen_core else "OFF") or control("REFERENCE") != "RHF":
        raise EngineParseError("The native core/reference treatment differs from the requested protocol")
    if control("SPHERICAL") != "ON":
        raise EngineParseError("The native spherical basis convention differs from the requested TOPOS protocol")
    if molecule.multiplicity != 1 or control("MULTIPLICI?TY") != "1":
        raise EngineParseError("The native spin multiplicity differs from the requested closed-shell protocol")
    if control("CHARGE") != str(molecule.charge):
        raise EngineParseError("The native electronic charge differs from the requested molecule")
    native_method = control("CALC_?LEVEL").upper()
    accepted_methods = {"HF": {"HF", "SCF"}, "MP2": {"MP2", "MBPT(2)"},
                        "CCSD": {"CCSD"}, "CCSD(T)": {"CCSD(T)", "CCSD[T]"}, "CCSDT": {"CCSDT"}, "CCSDTQ": {"CCSDTQ"}}
    if native_method not in accepted_methods[protocol.method]:
        raise EngineParseError("Native CALC_LEVEL differs from the requested method; an intermediate energy is not the requested job")
    if protocol.method in {"CCSDT", "CCSDTQ"}:
        program = "NCC" if protocol.method == "CCSDTQ" else "ECC"
        if control("CC_PROGRAM") != program or control("ABCDTYPE") != "STANDARD":
            raise EngineParseError("Higher coupled-cluster calculation lacks the requested native solver and STANDARD integrals")
        if protocol.method == "CCSDTQ" and "xncc" not in _native_invocations(raw):
            raise EngineParseError("Full quadruples require the built-in NCC solver; an external MRCC result cannot impersonate it")
    if len(re.findall(r"SCF has converged\.", raw)) != 1:
        raise EngineParseError("Expected one CFOUR Cartesian evaluation, not concatenated jobs/optimization cycles")
    qcvars, native, stdout_gradient, _, _, error = harvest_outfile_pass(raw)
    if error or native is None or list(native.symbols) != molecule.symbols:
        raise EngineParseError("CFOUR output lacks the exact indexed atom inventory")
    native_xyz = np.asarray(native.geometry) * BOHR_ANGSTROM
    rotation = _proper_rotation(native_xyz, np.asarray(molecule.coordinates))
    key = ("HF" if protocol.method == "HF" else protocol.method) + " TOTAL ENERGY"
    if key not in qcvars or "SCF TOTAL ENERGY" not in qcvars:
        raise EngineParseError("Requested correlated total energy absent; SCF/MP2 intermediate energies are insufficient")
    energy, reference = _number(str(qcvars[key])), _number(str(qcvars["SCF TOTAL ENERGY"]))
    if protocol.method == "CCSDTQ" and abs(energy - _ncc_total_energy(raw, protocol.method)) > 1e-10:
        raise EngineParseError("QCEngine's full-quadruples total differs from the exact native NCC total")
    gradient = None
    if protocol.operation in {"gradient", "optimize"}:
        if not grd:
            raise EngineParseError("CFOUR analytic derivative requires its native GRD artifact")
        try:
            grd_molecule, grd_gradient = harvest_GRD(grd.replace("D", "E").replace("d", "e"))
        except (ValueError, IndexError) as exc:
            raise EngineParseError("CFOUR GRD artifact is malformed") from exc
        if list(grd_molecule.symbols) != molecule.symbols:
            raise EngineParseError("CFOUR GRD atom order does not preserve explicit molecular identities")
        grd_rotation = _proper_rotation(np.asarray(grd_molecule.geometry) * BOHR_ANGSTROM,
                                        np.asarray(molecule.coordinates))
        gradient = np.asarray(grd_gradient) @ grd_rotation
        if gradient.shape != (len(molecule.symbols), 3) or not np.all(np.isfinite(gradient)):
            raise EngineParseError("Native gradient shape/values are invalid")
        if stdout_gradient is None or not np.allclose(np.asarray(stdout_gradient) @ rotation, gradient, atol=6e-8, rtol=0):
            raise EngineParseError("Native GRD and stdout gradients do not describe the same indexed result")
    observation = {"energy_hartree": energy, "reference_energy_hartree": reference,
                   "total_correlation_energy_hartree": energy - reference,
                   "gradient_hartree_per_bohr": gradient.tolist() if gradient is not None else None,
                   "engine_version": observed_version,
                   "frame_alignment": "indexed proper rotation only; no atom permutation or reflection",
                   "parser": {"qcengine": "0.51.0", "qcelemental": "0.51.2"}}
    if protocol.operation == "first-order-properties":
        if not dipol or control("PROPS") != "FIRST_ORDER":
            raise EngineParseError("First-order properties require native PROPS=FIRST_ORDER evidence and DIPOL")
        values = dipol.split()
        if len(values) != 3:
            raise EngineParseError("CFOUR DIPOL requires exactly three atomic-unit components")
        efg_observation = parse_cfour_efg(raw, efg, molecule, native_xyz,
            engine_version=observed_version, method=protocol.method, declaration=protocol.efg_convention)
        efg_observation["raw_artifacts_sha256"]["DIPOL"] = hashlib.sha256(dipol.encode("utf-8")).hexdigest()
        dipole_components = [_number(v) for v in values]
        if dipole_components != efg_observation["correlated_dipole_native_atomic_units"]:
            raise EngineParseError("Native DIPOL differs from the exact correlated-density xprops dipole")
        dipole_xyz = native_xyz
        if grd:
            # QCEngine documents DIPOL in GRD's orientation when GRD exists.
            try:
                grd_molecule, _ = harvest_GRD(grd.replace("D", "E").replace("d", "e"))
            except (ValueError, IndexError) as exc:
                raise EngineParseError("DIPOL's GRD coordinate frame is malformed") from exc
            if list(grd_molecule.symbols) != molecule.symbols:
                raise EngineParseError("DIPOL's GRD coordinate frame changes molecular identities")
            dipole_xyz = np.asarray(grd_molecule.geometry) * BOHR_ANGSTROM
        observation["dipole_atomic_units"] = _dipole_in_requested_frame(dipole_components, dipole_xyz, molecule)
        observation["dipole_origin"] = "requested Cartesian coordinate origin, including the charge-dependent translation term"
        observation["efg_observation"] = efg_observation
    return observation


def psi4_input(molecule: Molecule, protocol: ExternalProtocol, resources: ResourceLimits) -> str:
    """Generate a fixed API driver; caller text is data, never executable Python."""
    _physical_input(molecule, resources)
    protocol = ExternalProtocol.model_validate(protocol.model_dump())
    if protocol.engine != "psi4":
        raise ValueError("Psi4 input requires a Psi4 protocol")
    monomers = split_fragments(molecule)
    if len(monomers) != 2 or any(m.multiplicity != 1 for m in monomers):
        raise ValueError("Higher-order SAPT requires exactly two explicit closed-shell monomers")
    lines = []
    for number, monomer in enumerate(monomers):
        if number:
            lines.append("--")
        lines.append(f"{monomer.charge} 1")
        lines.extend(symbol + " " + " ".join(format(x, ".16g") for x in xyz)
                     for symbol, xyz in zip(monomer.symbols, monomer.coordinates, strict=True))
    lines.extend(["units angstrom", "no_reorient", "no_com", "symmetry c1"])
    options = {"basis": protocol.orbital_basis, "df_basis_scf": protocol.auxiliary_scf_basis,
               "df_basis_sapt": protocol.auxiliary_sapt_basis, "reference": "rhf", "scf_type": "df",
               "freeze_core": protocol.frozen_core, "e_convergence": 10**-protocol.scf_convergence,
               "d_convergence": 10**-protocol.scf_convergence, "sapt__nat_orbs_t2": False}
    geometry = "\n".join(lines)
    return ("import hashlib\nimport json\nimport psi4\nfrom pathlib import Path\n"
            f"assert psi4.__version__ == {protocol.engine_version!r}, 'Exact Psi4 version mismatch'\n"
            f"psi4.set_memory({int(resources.memory_mb * 1024**2 * .75)})\n"
            f"psi4.set_num_threads({resources.threads})\n"
            "psi4.core.set_output_file('psi4.native.out', False)\n"
            f"molecule = psi4.geometry({geometry!r})\n"
            f"psi4.set_options({options!r})\n"
            "energy = psi4.energy('sapt2+3', molecule=molecule)\n"
            "keys = ['SAPT ELST ENERGY', 'SAPT EXCH ENERGY', 'SAPT IND ENERGY', 'SAPT DISP ENERGY', 'SAPT TOTAL ENERGY']\n"
            "values = {key: float(psi4.variable(key)) for key in keys}\n"
            "result = {'engine_version': psi4.__version__, 'method': 'SAPT2+3', 'returned_interaction_hartree': float(energy), 'quantities_hartree': values}\n"
            "with Path(psi4.core.__file__).open('rb') as native_library:\n"
            "    result['native_core_sha256'] = hashlib.file_digest(native_library, 'sha256').hexdigest()\n"
            "Path('native-result.json').write_text(json.dumps(result, allow_nan=False))\n")


def parse_psi4_result(raw: str, protocol: ExternalProtocol) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise EngineParseError("Psi4 native result is not an object")
    if data.get("engine_version") != protocol.engine_version or data.get("method") != "SAPT2+3":
        raise EngineParseError("Psi4 version/method differs from the explicit SAPT protocol")
    if not re.fullmatch(r"[0-9a-f]{64}", str(data.get("native_core_sha256", ""))):
        raise EngineParseError("Psi4 native compiled-core fingerprint is missing")
    values = data.get("quantities_hartree", {})
    keys = ["SAPT ELST ENERGY", "SAPT EXCH ENERGY", "SAPT IND ENERGY", "SAPT DISP ENERGY"]
    if not isinstance(values, dict) or set(values) != set(keys + ["SAPT TOTAL ENERGY"]):
        raise EngineParseError("SAPT native result lacks the complete four-term decomposition")
    terms = {key: _number(str(value)) for key, value in values.items()}
    total = _number(str(data["returned_interaction_hartree"]))
    if abs(sum(terms[key] for key in keys) - total) > 2e-8 or abs(terms["SAPT TOTAL ENERGY"] - total) > 2e-10:
        raise EngineParseError("SAPT terms do not sum to the native interaction energy")
    return {"interaction_energy_hartree": total, "sapt_components_hartree": terms,
            "native_core_sha256": data["native_core_sha256"],
            "quantity_kind": "frozen-geometry SAPT interaction energy; not total electronic or association free energy"}


def _native_genbas(binary: Path, protocol: ExternalProtocol, molecule: Molecule) -> Path:
    if protocol.genbas_path is None:
        raise ValueError("The audited CFOUR installation's GENBAS file and SHA-256 are required")
    source = Path(protocol.genbas_path).resolve()
    # QCEngine documents ../basis/GENBAS; older vendor layouts colocate it in bin.
    native_locations = {(binary.parent.parent / "basis" / "GENBAS").resolve(), (binary.parent / "GENBAS").resolve()}
    if source not in native_locations or not source.is_file() or file_digest(source) != protocol.genbas_sha256:
        raise ValueError("GENBAS must be the unchanged basis library belonging to the audited CFOUR executable")
    text = source.read_text(errors="strict")
    for symbol in set(molecule.symbols):
        if not re.search(r"(?mi)^" + re.escape(symbol) + ":" + re.escape(protocol.orbital_basis) + r"\s*$", text):
            raise ValueError(f"Native GENBAS lacks {symbol}:{protocol.orbital_basis}; no basis-name substitution")
    return source


def run_external(molecule: Molecule, protocol: ExternalProtocol, resources: ResourceLimits,
                 workdir: str | Path, *, executable: str | Path | None = None,
                 process_runner: Callable[..., Any] | None = None,
                 cancel_event: Event | None = None) -> EngineResult:
    """Run exact native jobs through BASE; no unavailable-engine numerical fallback."""
    started, folder = time.monotonic(), Path(workdir).resolve()
    result = EngineResult(status="unsupported", engine=protocol.engine, method=protocol.method,
                          operation=protocol.operation,
                          metadata={"execution_kind": "not-executed", "adapter_validation": "conditional-not-live-validated",
                                    "requested_protocol": protocol.model_dump(mode="json"),
                                    "protocol_sha256": digest_json(protocol.model_dump(mode="json")), "sources": SOURCES,
                                    "execution_broker": "BASE" if process_runner is None or isinstance(getattr(process_runner, "__self__", None), BaseRuntime)
                                    else "explicit caller-supplied development/test runner"})
    try:
        protocol = ExternalProtocol.model_validate(protocol.model_dump())
        _physical_input(molecule, resources)
        if protocol.engine == "cfour":
            require_cfour_parsers()
        if protocol.engine == "cfour" and protocol.operation == "first-order-properties" and (
                protocol.engine_version != "2.1" or protocol.method != "CCSD(T)"):
            raise ValueError("The positively supported FIRST_ORDER property parser requires exact CFOUR 2.1 CCSD(T)")
        if protocol.engine in {"molpro", "mpqc"}:
            raise ValueError("Molpro F12 requires a verified explicit F12 variant/gradient protocol; the MPQC source row conflicts with its ORCA track. Neither is an executable recipe yet")
        if folder.exists() and any(folder.iterdir()):
            raise ValueError("External attempts require a fresh directory; reuse belongs to the verified workflow ledger")
        if process_runner is None:
            runtime = BaseRuntime()
            runtime.validate_resources(resources)
            try:
                executable = runtime.resolve_executable(protocol.engine, executable)
            except (ValueError, RuntimeError, OSError) as exc:
                result.status, result.diagnostics["reason"] = "unavailable", str(exc)
                return result
            process_runner = runtime.run_process
        resolved = shutil.which(str(executable or {"cfour": "xcfour", "psi4": "psi4"}[protocol.engine]))
        if resolved is None:
            result.status, result.diagnostics["reason"] = "unavailable", "Exact external engine executable is unavailable"
            return result
        binary = Path(resolved).resolve()
        genbas = _native_genbas(binary, protocol, molecule) if protocol.engine == "cfour" else None
        folder.mkdir(parents=True, exist_ok=True)
        atomic_json(folder / "protocol.json", protocol.model_dump(mode="json"))
        result.metadata.update(executable=str(binary), executable_sha256=file_digest(binary))
        if genbas:
            result.metadata["basis_library"] = {"path": str(genbas), "sha256": file_digest(genbas),
                                               "identity": "named basis from audited engine installation; retained native library"}
        deadline = started + resources.budget_seconds

        def limits() -> ResourceLimits:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("External campaign cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("External campaign deadline reached")
            return resources.model_copy(update={"budget_seconds": remaining})

        if protocol.engine == "psi4":
            (folder / "job.py").write_text(psi4_input(molecule, protocol, resources))
            result.command = [str(binary), "job.py", "driver.out"]
            process = process_runner(result.command, folder, limits(), cancel_event=cancel_event, log_prefix="engine")
            result.metadata["execution_kind"] = "real"
            result.diagnostics["process"] = process.to_dict()
            result.status = process.status
            if result.status != "completed":
                result.diagnostics["reason"] = process.reason
                return result
            native = parse_psi4_result((folder / "native-result.json").read_text(), protocol)
            if not (folder / "psi4.native.out").is_file():
                raise EngineParseError("Psi4 raw native output is missing")
            result.metadata["native_result"] = native
            # SAPT is an interaction energy. Do not put it in electronic_energy.
            result.metadata["quantity_kind"] = "interaction-energy"
            result.metadata["adapter_validation"] = "native-output-validated-for-this-execution"
            result.engine_version, result.molecule, result.converged = protocol.engine_version, molecule, True
            limits()
            return result

        evaluated: dict[str, tuple[Molecule, dict[str, Any]]] = {}

        def evaluate(x: np.ndarray) -> tuple[float, np.ndarray]:
            limits()
            current = (Molecule.model_validate({**molecule.model_dump(), "coordinates": (x.reshape(-1, 3) * BOHR_ANGSTROM).tolist()})
                       if protocol.operation == "optimize" else molecule)
            key = digest_json(current.coordinates)
            if key not in evaluated:
                require_cfour_parsers()
                evaluation = folder / f"evaluation-{len(evaluated):05d}"
                evaluation.mkdir()
                shutil.copyfile(genbas, evaluation / "GENBAS")
                if file_digest(evaluation / "GENBAS") != protocol.genbas_sha256:
                    raise EngineParseError("GENBAS changed during staging; the native input basis is not the pinned library")
                (evaluation / "ZMAT").write_text(cfour_input(current, protocol, resources))
                immutable = {path: file_digest(path) for path in
                             (binary, genbas, folder / "protocol.json", evaluation / "ZMAT", evaluation / "GENBAS")}
                result.command = [str(binary)]
                process = process_runner(result.command, evaluation, limits(), cancel_event=cancel_event,
                                         log_prefix="engine")
                result.metadata["execution_kind"] = "real"
                result.diagnostics["last_process"] = process.to_dict()
                if any(path.is_symlink() or not path.is_file() or file_digest(path) != expected
                       for path, expected in immutable.items()):
                    raise EngineParseError("Immutable CFOUR executable/basis/input changed during execution")
                if process.status != "completed":
                    result.status, result.diagnostics["reason"] = process.status, process.reason
                    raise _NativeFailure()
                observation = parse_cfour_output(native_text(evaluation, "engine.stdout", required=True, process_path=process.stdout_path), current, protocol,
                                                 grd=native_text(evaluation, "GRD"), dipol=native_text(evaluation, "DIPOL"),
                                                 efg=native_text(evaluation, "EFG"))
                if protocol.operation == "first-order-properties" and isinstance(
                        getattr(process_runner, "__self__", None), BaseRuntime):
                    from .cfour_operator import (
                        apply_operator_authority,
                        property_operator_authority,
                    )

                    actual_runtime = process_runner.__self__.cfour_property_runtime_identity()
                    context = property_operator_authority(folder, [path for path in evaluation.iterdir() if path.is_file()],
                        actual_runtime["runtime_authority"], current, protocol.model_dump(mode="json"),
                        current_property_runtime=actual_runtime)
                    observation["efg_observation"] = apply_operator_authority(observation["efg_observation"], context)
                atomic_json(evaluation / "native-result.json", observation)
                evaluated[key] = (current, observation)
            current, observation = evaluated[key]
            result.molecule, result.energy_hartree = current, observation["energy_hartree"]
            result.gradient_hartree_per_bohr = observation["gradient_hartree_per_bohr"]
            result.engine_version, result.metadata["native_result"] = observation["engine_version"], observation
            return result.energy_hartree, (np.asarray(result.gradient_hartree_per_bohr).ravel()
                                           if result.gradient_hartree_per_bohr is not None else np.empty(0))

        x = np.asarray(molecule.coordinates).ravel() / BOHR_ANGSTROM
        if protocol.operation == "optimize":
            from scipy.optimize import minimize

            optimized = minimize(evaluate, x, jac=True, method="L-BFGS-B",
                                 options={"maxiter": protocol.max_iterations, "maxls": 30, "ftol": 1e-15,
                                          "gtol": min(protocol.gradient_max_hartree_per_bohr,
                                                      protocol.gradient_rms_hartree_per_bohr)})
            # Re-read the actual evaluated final point, never synthesize a gradient.
            _, gradient = evaluate(optimized.x)
            max_g, rms_g = float(np.max(np.abs(gradient))), float(np.sqrt(np.mean(gradient**2)))
            result.converged = (max_g <= protocol.gradient_max_hartree_per_bohr
                                and rms_g <= protocol.gradient_rms_hartree_per_bohr)
            result.diagnostics["optimization"] = {"driver": "TOPOS/scipy-L-BFGS-B with actual CFOUR analytic gradients",
                                                  "native_cfour_optimizer": False, "iterations": int(optimized.nit),
                                                  "gradient_evaluations": len(evaluated), "max_gradient_hartree_per_bohr": max_g,
                                                  "rms_gradient_hartree_per_bohr": rms_g, "message": str(optimized.message),
                                                  "stationary_point_not_hessian_certified": True}
            result.status = "completed" if result.converged else "partial"
        else:
            evaluate(x)
            result.status, result.converged = "completed", True
        result.metadata["evaluations"] = len(evaluated)
        limits()
        return result
    except _NativeFailure:
        return result
    except InterruptedError as exc:
        result.status, result.diagnostics["reason"] = "cancelled", str(exc)
        return result
    except TimeoutError as exc:
        result.status, result.diagnostics["reason"] = "timed-out", str(exc)
        return result
    except (ValueError, RuntimeError, OSError, ImportError, KeyError) as exc:
        result.status = "failed" if result.metadata["execution_kind"] == "real" else "unsupported"
        result.diagnostics["reason"] = str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - started
        if folder.is_dir():
            if protocol.engine == "cfour":
                finalize_artifacts(result, folder)
            else:
                result.artifacts = artifact_inventory(folder)


class _NativeFailure(Exception):
    """The native subprocess already supplied its precise unsuccessful status."""
