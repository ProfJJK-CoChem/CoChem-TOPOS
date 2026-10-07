"""Real, fail-closed local xTB and ORCA adapters for TOPOS 0.1.0.

These adapters never change the requested Hamiltonian. Raw inputs, version
probes, stdout/stderr, geometries and derivatives remain in the attempt folder.
Only xTB 6.7.1 has live execution evidence in the initial release profile;
ORCA 6.1.1 is a conditional adapter requiring a licensed installation.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable, Literal

import numpy as np
from pydantic import Field

from .models import Artifact, Contract, ExecutionStatus, MethodSpec, Molecule, ResourceLimits
from .runtime import available_cpu_count, run_process
from .storage import digest_json

_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
XTB_PROFILES = {
    "screening-v1": "normal", "xtb-normal-v1": "normal",
    "xtb-tight-v1": "tight", "xtb-vtight-v1": "vtight",
    "xtb-extreme-v1": "extreme",
}
ORCA_METHODS = {"B3LYP": "B3LYP", "HF-3c": "HF-3c", "r2SCAN-3c": "r2SCAN-3c",
                "r²SCAN-3c": "r2SCAN-3c", "HF": "HF",
                "wB97X-V": "wB97X-V", "wB97M-V": "wB97M-V"}
ORCA_BASES = {"def2-SVP", "def2-TZVP", "def2-TZVPP", "def2-QZVPP", "jun-cc-pVTZ"}
ORCA_VERSION = "6.1.1"


class EngineResult(Contract):
    status: ExecutionStatus
    engine: str
    method: str
    operation: str
    engine_version: str | None = None
    energy_hartree: float | None = None
    gradient_hartree_per_bohr: list[list[float]] | None = None
    molecule: Molecule | None = None
    converged: bool | None = None
    command: list[str] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    elapsed_seconds: float = 0.0
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class EngineParseError(ValueError):
    """Engine artifacts do not establish the requested quantity/state."""


def _number(value: str) -> float:
    result = float(value.replace("D", "E").replace("d", "e"))
    if not math.isfinite(result):
        raise EngineParseError("nonfinite engine quantity")
    return result



def parse_cartesian_dipole(text: str, engine: str) -> dict[str, Any] | None:
    """Parse signed final Cartesian components, with explicit source units.

    xTB 6.7.1 prints CAMM components in atomic units but their norm in Debye.
    This is NOT its distinct AO-density dipole in xtbout.json. ORCA likewise
    prints Total Dipole Moment components in atomic units. The printed norm
    cross-check includes the known component rounding. An absent property is
    unavailable; a malformed advertised property is a parse error.
    """
    from scipy import constants

    atomic_unit_debye = (constants.physical_constants["atomic unit of electric dipole mom."][0]
                         * constants.c * 1e21)
    printed_atomic_unit_debye = atomic_unit_debye
    if engine == "xtb":
        marker = "molecular dipole:"
        if marker not in text:
            return None
        block = text.rsplit(marker, 1)[1].split("molecular quadrupole", 1)[0]
        if not re.search(r"x\s+y\s+z\s+tot \(Debye\)", block):
            raise EngineParseError("xTB molecular dipole units/header are not recognized")
        row = re.search(r"(?m)^\s*full:\s*(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s*$", block)
        if row is None:
            raise EngineParseError("xTB full molecular dipole vector is incomplete")
        vector = [_number(row.group(i)) for i in range(1, 4)]
        magnitude_debye = _number(row.group(4))
        component_rounding = 0.0005  # Fortran 3f12.3, verified in the source below.
        magnitude_rounding = 0.0005
        definition = "GFN2-xTB cumulative atomic multipole molecular dipole (CAMM full)"
        source = "https://github.com/grimme-lab/xtb/blob/26b28010e805f7d1aeeef39813feb473e69cc4be/src/aespot.f90#L701"
    elif engine == "orca":
        markers = list(re.finditer(r"(?m)^\s*DIPOLE MOMENT\s*$", text))
        if not markers:
            return None
        block = text[markers[-1].end():]
        row = re.search(r"(?m)^\s*Total Dipole Moment\s*:\s*(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s*$", block)
        norm_au = re.search(r"Magnitude\s*\(a\.u\.\)\s*:\s*(" + _FLOAT + r")", block)
        norm_debye = re.search(r"Magnitude\s*\(Debye\)\s*:\s*(" + _FLOAT + r")", block)
        if row is None or norm_au is None or norm_debye is None:
            raise EngineParseError("ORCA molecular dipole vector and explicit a.u./Debye magnitudes are required")
        vector = [_number(row.group(i)) for i in range(1, 4)]
        magnitude_debye = _number(norm_debye.group(1))
        def rounding(value: str) -> float:
            mantissa, _, exponent = value.lower().replace("d", "e").partition("e")
            decimals = len(mantissa.partition(".")[2])
            return .5 * 10.0 ** (int(exponent or "0") - decimals)

        component_errors = np.asarray([rounding(row.group(i)) for i in range(1, 4)])
        component_rounding = float(np.max(component_errors))
        magnitude_rounding = rounding(norm_debye.group(1))
        norm_atomic_units = _number(norm_au.group(1))
        norm_rounding = rounding(norm_au.group(1))
        if (norm_atomic_units < 0 or abs(float(np.linalg.norm(vector)) - norm_atomic_units)
                > float(np.linalg.norm(component_errors)) + norm_rounding):
            raise EngineParseError("ORCA Cartesian dipole components and atomic-unit magnitude disagree")
        # ORCA 6.1.1's retained native output uses its 2.541798 Debye/e a0
        # convention, not current CODATA. Validate the engine's printed units
        # separately; scientific Cartesian outputs below use current CODATA.
        printed_atomic_unit_debye = 2.541798
        if (abs(norm_atomic_units * printed_atomic_unit_debye - magnitude_debye)
                > norm_rounding * printed_atomic_unit_debye + magnitude_rounding):
            raise EngineParseError("ORCA dipole magnitudes disagree between atomic units and Debye")
        definition = "ORCA total electronic plus nuclear Cartesian dipole"
        source = "ORCA final DIPOLE MOMENT block; explicit Magnitude (a.u.) and Magnitude (Debye) cross-check"
    else:
        raise ValueError("dipole parser supports xtb or orca only")
    vector_debye = np.asarray(vector) * atomic_unit_debye
    tolerance = np.sqrt(3) * component_rounding * printed_atomic_unit_debye + magnitude_rounding
    native_vector_debye = np.asarray(vector) * printed_atomic_unit_debye
    if magnitude_debye < 0 or abs(float(np.linalg.norm(native_vector_debye)) - magnitude_debye) > tolerance:
        raise EngineParseError(f"{engine} Cartesian dipole components and printed magnitude disagree")
    return {"cartesian_debye": vector_debye.tolist(), "cartesian_atomic_units": vector,
            "printed_magnitude_debye": magnitude_debye, "units": "debye",
            "definition": definition, "parser": f"topos.engines/{engine}-dipole-v1",
            "source": source, "atomic_unit_debye": atomic_unit_debye,
            "cartesian_conversion_convention": "current scipy CODATA atomic unit of electric dipole",
            "printed_atomic_unit_debye": printed_atomic_unit_debye,
            "printed_conversion_convention": "ORCA 6.1.1 native 2.541798 Debye/e a0" if engine == "orca" else "current CODATA",
            "engine_native_cartesian_debye": native_vector_debye.tolist(),
            "printed_component_rounding_bound_debye": component_rounding * atomic_unit_debye,
            "selection": "last advertised molecular dipole block, without fallback to earlier incomplete results",
            "origin": "engine input/output Cartesian origin; charged-molecule origin dependence retained"}


def write_xyz(molecule: Molecule, path: str | Path) -> None:
    lines = [str(len(molecule.symbols)), "TOPOS input; angstrom; atom order preserved"]
    lines.extend(f"{s} {r[0]:.16g} {r[1]:.16g} {r[2]:.16g}"
                 for s, r in zip(molecule.symbols, molecule.coordinates, strict=True))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_xyz(path: str | Path, reference: Molecule) -> Molecule:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    n = len(reference.symbols)
    if len(lines) < 2 or lines[0].strip() != str(n):
        raise EngineParseError("output geometry has incompatible atom count")
    rows = [line.split() for line in lines[2:] if line.strip()]
    if len(rows) != n or any(len(row) != 4 for row in rows):
        raise EngineParseError("output geometry is incomplete or contains trailing structures")
    if [row[0] for row in rows] != reference.symbols:
        raise EngineParseError("output geometry changed element identity or atom order")
    data = reference.model_dump()
    data["coordinates"] = [[_number(v) for v in row[1:]] for row in rows]
    return Molecule.model_validate(data)


def parse_xtb_gradient(path: str | Path, molecule: Molecule) -> tuple[float, list[list[float]]]:
    """Read last Turbomole $grad cycle (Eh, Eh/bohr; coordinates in bohr)."""
    from scipy.constants import physical_constants

    text = Path(path).read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^\s*cycle\s*=", text)
    if len(blocks) < 2 or "$grad" not in blocks[0] or "$end" not in text:
        raise EngineParseError("missing complete xTB gradient cycle")
    lines = blocks[-1].splitlines()
    energy_match = re.search(r"SCF energy\s*=\s*(" + _FLOAT + ")", lines[0])
    if not energy_match:
        raise EngineParseError("missing gradient energy")
    n = len(molecule.symbols)
    rows = [line.split() for line in lines[1:] if line.strip() and not line.lstrip().startswith("$")]
    if len(rows) != 2 * n:
        raise EngineParseError("incomplete xTB gradient/coordinate array")
    if any(len(row) != 4 for row in rows[:n]) or any(len(row) != 3 for row in rows[n:]):
        raise EngineParseError("invalid xTB gradient record shape")
    if [row[3] for row in rows[:n]] != molecule.symbols:
        raise EngineParseError("gradient element mapping mismatch")
    bohr_angstrom = physical_constants["Bohr radius"][0] * 1e10
    coords = np.array([[_number(v) for v in row[:3]] for row in rows[:n]]) * bohr_angstrom
    if not np.allclose(coords, molecule.coordinates, atol=2e-7, rtol=0):
        raise EngineParseError("gradient belongs to a different geometry")
    return _number(energy_match.group(1)), [[_number(v) for v in row] for row in rows[n:]]


def parse_orca_engrad(path: str | Path, molecule: Molecule) -> tuple[float, list[list[float]]]:
    """Read ORCA .engrad including geometry/state array validation."""
    from scipy.constants import physical_constants

    from .chemistry import atomic_number

    rows = [line.split() for line in Path(path).read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    n = len(molecule.symbols)
    if not rows or rows[0] != [str(n)] or len(rows) != 2 + 4 * n:
        raise EngineParseError("incomplete ORCA engrad")
    energy = _number(rows[1][0])
    values = [_number(row[0]) for row in rows[2:2 + 3 * n] if len(row) == 1]
    if len(values) != 3 * n:
        raise EngineParseError("invalid ORCA gradient shape")
    coords = rows[2 + 3 * n:]
    if any(len(row) != 4 for row in coords):
        raise EngineParseError("invalid ORCA coordinate shape")
    if [int(row[0]) for row in coords] != [atomic_number(s) for s in molecule.symbols]:
        raise EngineParseError("ORCA gradient element mapping mismatch")
    bohr_angstrom = physical_constants["Bohr radius"][0] * 1e10
    xyz = np.array([[_number(v) for v in row[1:]] for row in coords]) * bohr_angstrom
    if not np.allclose(xyz, molecule.coordinates, atol=2e-6, rtol=0):
        raise EngineParseError("ORCA derivative belongs to a different geometry")
    return energy, np.array(values).reshape(n, 3).tolist()


def artifact_inventory(folder: Path) -> list[Artifact]:
    result = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise EngineParseError("engine artifact symlinks are not accepted")
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        result.append(Artifact(path=str(path.resolve()), sha256=digest.hexdigest(),
                               size_bytes=path.stat().st_size,
                               role="engine-input" if path.name in {"input.xyz", "job.inp", "version.inp"} else "raw-output"))
    return result


def _method_problem(method: MethodSpec, resources: ResourceLimits, operation: str) -> str | None:
    if operation not in {"energy", "gradient", "optimize"}:
        return f"operation {operation!r} has no validated adapter"
    if resources.device != "cpu":
        return "native xTB/ORCA adapter supports CPU; requested GPU cannot be silently substituted"
    if resources.threads > available_cpu_count():
        return "requested total worker count exceeds available CPU affinity"
    if method.constraints:
        return "native constraints not supported; use explicit TOPOS constrained-gradient protocol"
    if method.dispersion and not (method.engine == "orca" and method.method == "B3LYP" and method.dispersion == "D4"):
        return "custom dispersion has not been validated for this adapter"
    if method.auxiliary_basis is not None and not (
            method.engine == "orca" and method.method in {"B3LYP", "wB97X-V", "wB97M-V"}
            and method.auxiliary_basis == "def2/J"):
        return "explicit auxiliary basis is supported only as def2/J for the ORCA hybrid RIJCOSX recipes"
    if method.solvent:
        return "solvation requires a version-specific model/solvent profile; no implicit model chosen"
    if method.engine == "xtb":
        if method.method != "GFN2-xTB":
            return "this adapter currently validates GFN2-xTB only; no potential substitution"
        if method.basis is not None:
            return "GFN2-xTB has no selectable orbital basis"
        if method.profile_id not in XTB_PROFILES:
            return "unresolved xTB convergence profile"
    elif method.engine == "orca":
        if resources.memory_mb * 0.75 < 16 * resources.threads:
            return "ORCA memory budget cannot supply the minimum per-worker MaxCore plus driver reserve"
        if method.method not in ORCA_METHODS:
            return "ORCA method is outside the validated input grammar"
        if method.method in {"HF-3c", "r2SCAN-3c", "r²SCAN-3c"}:
            if method.basis is not None:
                return "3c composite uses its native basis; separate basis override is invalid"
        elif method.basis not in ORCA_BASES:
            return "explicit supported orbital basis required for noncomposite ORCA method"
        if method.profile_id not in {"orca-mapping-v4.1", "orca-vpt2-reference-v1"}:
            return "ORCA requires an explicit supported convergence profile; conflicting profiles not guessed"
    else:
        return f"engine {method.engine!r} has no validated local adapter"
    return None


def _orca_input(molecule: Molecule, method: MethodSpec, resources: ResourceLimits, operation: str,
                *, ghost_atom_indices: list[int] | None = None,
                ghost_electronic_state: tuple[int, int] | None = None,
                basis_files: dict[str, str] | None = None) -> str:
    strict_vpt2 = method.profile_id == "orca-vpt2-reference-v1"
    keywords = [ORCA_METHODS[method.method], "ExtremeSCF" if strict_vpt2 else "TightSCF", "DEFGRID3"]
    if method.dispersion == "D4":
        keywords.append("D4")
    if method.basis and not basis_files:
        keywords.append(method.basis)
    if method.method in {"B3LYP", "wB97X-V", "wB97M-V"}:
        keywords.append("RIJCOSX")
        if not basis_files or "auxiliary" not in basis_files:
            keywords.append("def2/J")
    if operation == "optimize":
        # Run-type keywords are mutually exclusive: Engrad after Opt selects
        # a single gradient in ORCA 6.1.1 and does not optimize the geometry.
        keywords.append("Opt")
    elif operation == "gradient":
        keywords.append("Engrad")
    # ORCA MaxCore is per worker; reserve 25% for unaccounted structures/driver.
    lines = ["! " + " ".join(keywords), f"%pal nprocs {resources.threads} end",
             f"%maxcore {max(16, int(resources.memory_mb * 0.75 / resources.threads))}"]
    if strict_vpt2:
        lines.extend(["%method", "  Z_Tol 1e-14", "end"])
    if operation == "optimize":
        lines.extend(["%geom", "  MaxIter 200", "  TolE 1e-10" if strict_vpt2 else "  TolE 1e-7",
                      "  TolMaxG 1e-7" if strict_vpt2 else "  TolMaxG 1e-5",
                      "  TolRMSG 3e-8" if strict_vpt2 else "  TolRMSG 3e-6",
                      "  TolRMSD 5e-7" if strict_vpt2 else "  TolRMSD 5e-5",
                      "  TolMaxD 1e-6" if strict_vpt2 else "  TolMaxD 1e-4",
                      "  InHess Lindh", "end"])
    if basis_files:
        lines.append("%basis")
        for kind, keyword in (("orbital", "GTOName"), ("auxiliary", "GTOAuxJName")):
            if kind in basis_files:
                if basis_files[kind] not in {"orbital.bas", "auxiliary.bas"}:
                    raise ValueError("External ORCA basis filenames must be the fixed staged names")
                lines.append(f'  {keyword} "{basis_files[kind]}"')
        lines.append("end")
    charge, multiplicity = ghost_electronic_state or (molecule.charge, molecule.multiplicity)
    lines.append(f"* xyz {charge} {multiplicity}")
    ghosts = set(ghost_atom_indices or [])
    lines.extend(f"{s}{':' if i in ghosts else ''} {r[0]:.16g} {r[1]:.16g} {r[2]:.16g}"
                 for i, (s, r) in enumerate(zip(molecule.symbols, molecule.coordinates, strict=True)))
    lines.extend(["*", ""])
    return "\n".join(lines)


def _orca_version_input(resources: ResourceLimits) -> str:
    """A separate genuine serial calculation establishes ORCA loader/version health.

    ORCA is invoked with an input file, not an assumed ``--version`` option.
    This He/HF/STO-3G diagnostic is never returned as the requested method's
    molecular result and does not test parallel MPI or the production protocol.
    """
    maxcore = max(16, min(64, resources.memory_mb // 2))
    return ("! HF STO-3G SP\n%pal nprocs 1 end\n"
            f"%maxcore {maxcore}\n* xyz 0 1\nHe 0.0 0.0 0.0\n*\n")


def _engine_version(text: str, engine: str) -> str | None:
    pattern = (r"xtb version\s+(\d+\.\d+\.\d+)" if engine == "xtb"
               else r"(?:Program Version|ORCA VERSION)\s+(\S+)")
    match = re.search(pattern, text, re.I)
    return match.group(1) if match else None


def _orca_convergence(text: str) -> dict[str, bool]:
    fields = {"energy_change": "Energy change", "rms_gradient": "RMS gradient",
              "max_gradient": "MAX gradient", "rms_step": "RMS step", "max_step": "MAX step"}
    result = {}
    for key, label in fields.items():
        matches = re.findall(re.escape(label) + r"\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(YES|NO)", text, re.I)
        if matches:
            value, threshold, yes = matches[-1]
            result[key] = yes.upper() == "YES" and abs(_number(value)) <= _number(threshold)
    return result


def run_engine(
    molecule: Molecule,
    method: MethodSpec,
    resources: ResourceLimits,
    workdir: str | Path,
    operation: Literal["energy", "gradient", "optimize"] = "optimize",
    cancel_event: Event | None = None,
    executable: str | Path | None = None,
    *,
    process_runner: Callable[..., Any] | None = None,
    ghost_atom_indices: list[int] | None = None,
    ghost_electronic_state: tuple[int, int] | None = None,
    orbital_basis_file: str | Path | None = None,
    auxiliary_basis_file: str | Path | None = None,
) -> EngineResult:
    """Run an isolated real attempt; failures keep artifacts and optional quantities null."""
    start = time.monotonic()
    execute_process = process_runner or run_process
    result = EngineResult(status="unsupported", engine=method.engine, method=method.method,
                          operation=operation, metadata={"execution_kind": "not-executed",
                          "profile_id": method.profile_id, "requested_method": method.model_dump(),
                          "resources": resources.model_dump(), "precision": "float64"})
    problem = _method_problem(method, resources, operation)
    if problem:
        result.diagnostics["reason"] = problem
        return result
    physical_molecule = molecule
    ghosts = list(ghost_atom_indices or [])
    if ghosts or ghost_electronic_state is not None:
        if method.engine != "orca" or operation != "energy" or not ghosts or ghost_electronic_state is None:
            result.diagnostics["reason"] = "Ghost basis centers require explicit ORCA energy-only fragment state"
            return result
        if (len(set(ghosts)) != len(ghosts) or len(ghosts) >= len(molecule.symbols)
                or any(not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= len(molecule.symbols) for i in ghosts)):
            result.diagnostics["reason"] = "Ghost indices must be distinct valid atom indices leaving a physical fragment"
            return result
        real = [i for i in range(len(molecule.symbols)) if i not in ghosts]
        try:
            charge, multiplicity = ghost_electronic_state
            if any(not isinstance(value, int) or isinstance(value, bool) for value in (charge, multiplicity)):
                raise ValueError("Fragment charge and multiplicity must be integers")
            physical_molecule = Molecule(
                symbols=[molecule.symbols[i] for i in real], coordinates=[molecule.coordinates[i] for i in real],
                atom_ids=[molecule.atom_ids[i] for i in real], isotopes=[molecule.isotopes[i] for i in real],
                charge=charge, multiplicity=multiplicity, environment=molecule.environment,
            )
            if any(set(group) == set(real) for group in molecule.fragments):
                from .fragments import split_fragments

                matching = [fragment for fragment in split_fragments(molecule)
                            if set(fragment.atom_ids) == set(physical_molecule.atom_ids)]
                if len(matching) != 1 or (matching[0].charge, matching[0].multiplicity) != (charge, multiplicity):
                    raise ValueError("Ghost electronic state must match the explicit physical fragment")
                physical_molecule = matching[0]
        except (TypeError, ValueError) as exc:
            result.diagnostics["reason"] = f"Invalid physical ghost-fragment state: {exc}"
            return result
        result.metadata.update(ghost_atom_indices=ghosts, basis_center_molecule=molecule.model_dump(mode="json"),
                               physical_molecule=physical_molecule.model_dump(mode="json"),
                               ghost_electronic_state={"charge": charge, "multiplicity": multiplicity})
        from .science import geometry_digest
        result.metadata.update(basis_center_geometry_sha256=geometry_digest(molecule),
                               physical_geometry_sha256=geometry_digest(physical_molecule))
    external_basis = {kind: Path(value) for kind, value in (("orbital", orbital_basis_file), ("auxiliary", auxiliary_basis_file)) if value is not None}
    if external_basis:
        if (method.engine != "orca" or operation != "energy" or "orbital" not in external_basis
                or method.method in {"HF-3c", "r2SCAN-3c", "r²SCAN-3c"}):
            result.diagnostics["reason"] = "Shared external basis files apply only to noncomposite ORCA energy calculations"
            return result
        for path in external_basis.values():
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 16 * 1024 * 1024:
                result.diagnostics["reason"] = "External basis must be a nonempty regular file at most 16 MiB"
                return result
    if molecule.environment:
        if molecule.environment != {"phase": "gas"}:
            result.diagnostics["reason"] = "explicit environment is unsupported by gas-phase adapter"
            return result
    from .chemistry import atomic_number
    if method.engine == "xtb" and any(atomic_number(s) > 86 for s in molecule.symbols):
        result.diagnostics["reason"] = "GFN2-xTB parameterization does not cover elements beyond radon"
        return result
    requested = str(executable) if executable is not None else os.environ.get(
        f"TOPOS_{method.engine.upper()}_EXECUTABLE", method.engine)
    binary = shutil.which(requested)
    if binary is None:
        result.status = "unavailable"
        result.diagnostics["reason"] = f"requested {method.engine} executable not found: {requested}"
        return result
    folder = Path(workdir).resolve()
    if folder.exists() and any(folder.iterdir()):
        result.status = "failed"
        result.diagnostics["reason"] = "attempt directory is not empty; stale outputs cannot be reused"
        return result
    folder.mkdir(parents=True, exist_ok=True)
    result.metadata["executable"] = str(Path(binary).resolve())
    result.metadata["executable_sha256"] = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
    try:
        basis_files = {}
        for kind, source in external_basis.items():
            name = f"{kind}.bas"
            data = source.read_bytes()
            if b"\x00" in data:
                raise EngineParseError("External basis file contains a NUL byte")
            (folder / name).write_bytes(data)
            basis_files[kind] = name
            result.metadata.setdefault("external_basis", {})[kind] = {
                "filename": name, "sha256": hashlib.sha256(data).hexdigest(),
                "declared_basis": method.basis if kind == "orbital" else method.auxiliary_basis or "def2/J",
                "format": "GAMESS-US", "source": "explicit supplied ORCA-exported basis; raw bytes retained",
            }
        if basis_files:
            result.metadata["basis_identity_status"] = "user-supplied-unverified"
            result.metadata["basis_comparison_protocol"] = digest_json({
                "method": method.model_dump(mode="json"),
                "basis_sha256": {kind: entry["sha256"] for kind, entry in result.metadata["external_basis"].items()},
            })
        probe_resources = resources.model_copy(update={"budget_seconds": min(resources.budget_seconds, 10.0)})
        if method.engine == "orca":
            (folder / "version.inp").write_text(_orca_version_input(resources), encoding="utf-8")
            probe_command = [str(Path(binary).resolve()), "version.inp"]
            probe_resources = probe_resources.model_copy(update={"threads": 1})
            result.metadata["version_probe"] = {
                "execution_kind": "real-diagnostic", "method": "HF", "basis": "STO-3G",
                "system": "He atom; charge 0; multiplicity 1", "purpose": "loader/version diagnostic",
                "scientific_result_eligibility": False, "parallel_mpi_validated": False,
            }
        else:
            probe_command = [binary, "--version"]
        probe = execute_process(probe_command, folder, probe_resources,
                            cancel_event=cancel_event, log_prefix="version")
        result.diagnostics["version_probe_process"] = probe.to_dict()
        probe_text = Path(probe.stdout_path).read_text(errors="replace") + Path(probe.stderr_path).read_text(errors="replace")
        version = _engine_version(probe_text, method.engine)
        result.diagnostics["observed_probe_version"] = version
        if probe.status in {"cancelled", "timed-out"}:
            result.status = probe.status
            result.diagnostics["reason"] = probe.reason
            return result
        if version is None or probe.status != "completed":
            result.status = "unavailable"
            result.diagnostics["reason"] = "successful engine version/loader probe did not establish executable identity/version"
            return result
        result.engine_version = version
        if method.engine == "orca" and ("ORCA TERMINATED NORMALLY" not in probe_text or
                                         "FINAL SINGLE POINT ENERGY" not in probe_text or
                                         "SCF CONVERGED AFTER" not in probe_text or
                                         "SCF NOT CONVERGED" in probe_text):
            result.status = "unavailable"
            result.diagnostics["reason"] = "ORCA serial version/loader diagnostic did not terminate normally with an energy"
            return result
        if method.engine == "orca":
            probe_energies = re.findall(r"FINAL SINGLE POINT ENERGY\s+(" + _FLOAT + ")", probe_text)
            if not probe_energies:
                result.status = "unavailable"
                result.diagnostics["reason"] = "ORCA version/loader diagnostic has no finite electronic energy"
                return result
            _number(probe_energies[-1])
        expected = method.engine_version
        if expected is not None and expected != result.engine_version:
            result.diagnostics["reason"] = f"requested engine version {expected}; found {result.engine_version}"
            return result
        if (method.engine == "xtb" and result.engine_version != "6.7.1") or (method.engine == "orca" and result.engine_version != ORCA_VERSION):
            result.diagnostics["reason"] = "engine version lies outside the adapter capability profile"
            return result
        remaining = resources.budget_seconds - (time.monotonic() - start)
        if remaining <= 0:
            result.status = "timed-out"
            result.diagnostics["reason"] = "attempt budget exhausted during preflight"
            return result
        write_xyz(molecule, folder / "input.xyz")
        if method.engine == "xtb":
            command = [binary, "input.xyz", "--gfn", "2", "--chrg", str(molecule.charge),
                       "--uhf", str(molecule.multiplicity - 1), "--json"]
            if operation == "optimize":
                command.extend(["--opt", XTB_PROFILES[method.profile_id]])
            # xTB processes run-type flags in order: optimization must precede --grad.
            command.append("--grad")
            runtime_resources = resources.model_copy(update={"budget_seconds": remaining})
        else:
            (folder / "job.inp").write_text(_orca_input(molecule, method, resources, operation,
                ghost_atom_indices=ghosts, ghost_electronic_state=ghost_electronic_state, basis_files=basis_files))
            command = [str(Path(binary).resolve()), "job.inp"]
            # %pal accounts for total workers; prevent nested OpenMP oversubscription.
            runtime_resources = resources.model_copy(update={"budget_seconds": remaining})
        result.command = command
        result.metadata["execution_kind"] = "real"
        if method.engine == "orca" and method.method in {"B3LYP", "wB97X-V", "wB97M-V"}:
            result.metadata["resolved_auxiliary_basis"] = "def2/J"
            result.metadata["exchange_approximation"] = "RIJCOSX"
        result.metadata["adapter_validation"] = "live-tested" if method.engine == "xtb" else "conditional-not-live-validated"
        process_options = {"threads_per_process": 1} if method.engine == "orca" else {}
        process = execute_process(command, folder, runtime_resources, cancel_event=cancel_event,
                                  **process_options)
        result.diagnostics["process"] = process.to_dict()
        result.status = process.status
        if process.status != "completed":
            result.diagnostics["reason"] = process.reason
            return result
        raw = Path(process.stdout_path).read_text(errors="replace")
        stderr = Path(process.stderr_path).read_text(errors="replace")
        if method.engine == "xtb":
            if "normal termination of xtb" not in raw + stderr or "convergence criteria satisfied" not in raw:
                raise EngineParseError("xTB normal termination and electronic convergence not established")
            matches = re.findall(r"TOTAL ENERGY\s+(" + _FLOAT + r")\s+Eh", raw)
            if not matches:
                raise EngineParseError("xTB total energy absent")
            energy = _number(matches[-1])
            output_molecule = read_xyz(folder / "xtbopt.xyz", molecule) if operation == "optimize" else molecule
            gradient_energy, gradient = parse_xtb_gradient(folder / "gradient", output_molecule)
            if abs(energy - gradient_energy) > 2e-9:
                raise EngineParseError("xTB energy and gradient artifacts disagree")
            if operation == "optimize":
                converged = "GEOMETRY OPTIMIZATION CONVERGED" in raw
                limits = re.findall(r"grad\. convergence\s+(" + _FLOAT + ")", raw)
                thresholds = re.findall(r"energy convergence\s+(" + _FLOAT + ")", raw)
                if not limits or not thresholds:
                    raise EngineParseError("native optimization thresholds absent")
                threshold = _number(limits[-1])
                norm = float(np.linalg.norm(gradient))
                result.diagnostics["convergence"] = {"profile": method.profile_id,
                    "native_level": XTB_PROFILES[method.profile_id], "native_reported": converged,
                    "gradient_norm_hartree_per_bohr": norm, "gradient_norm_threshold": threshold,
                    "energy_change_threshold_hartree": _number(thresholds[-1]),
                    "criteria_source": "xTB native optimizer; no claim of ORCA mapping tolerances"}
                result.converged = converged and norm <= threshold * (1 + 1e-6)
            else:
                result.converged = True  # electronic convergence only, not geometry classification
        else:
            actual_version = _engine_version(raw, "orca")
            if actual_version != result.engine_version:
                raise EngineParseError("ORCA production header does not match the verified engine version")
            if "ORCA TERMINATED NORMALLY" not in raw:
                raise EngineParseError("ORCA normal termination absent")
            if "SCF CONVERGED AFTER" not in raw:
                raise EngineParseError("ORCA electronic convergence marker absent")
            if re.search(r"SCF NOT CONVERGED|SCF CONVERGENCE FAILURE", raw, re.I):
                raise EngineParseError("ORCA SCF failed to converge")
            matches = re.findall(r"FINAL SINGLE POINT ENERGY\s+(" + _FLOAT + ")", raw)
            if not matches:
                raise EngineParseError("ORCA total energy absent")
            energy = _number(matches[-1])
            output_molecule = read_xyz(folder / "job.xyz", molecule) if operation == "optimize" else physical_molecule
            gradient = None
            if operation == "gradient":
                derivative_energy, gradient = parse_orca_engrad(folder / "job.engrad", output_molecule)
                if abs(energy - derivative_energy) > 2e-7:
                    raise EngineParseError("ORCA energy and derivative artifacts disagree")
            if operation == "optimize":
                criteria = _orca_convergence(raw)
                result.diagnostics["convergence"] = criteria
                result.converged = ("THE OPTIMIZATION HAS CONVERGED" in raw and
                                    len(criteria) == 5 and all(criteria.values()))
                if result.converged:
                    # Opt and EnGrad are distinct native run types. Verify the
                    # returned geometry with a fresh gradient instead of making
                    # assumptions about optimizer scratch-file retention.
                    remaining = resources.budget_seconds - (time.monotonic() - start)
                    if remaining <= 0 or (cancel_event is not None and cancel_event.is_set()):
                        result.status = "cancelled" if cancel_event is not None and cancel_event.is_set() else "timed-out"
                        result.converged = False
                        result.diagnostics["reason"] = "Final optimization gradient was not executed within the active attempt"
                        return result
                    final = run_engine(output_molecule, method, resources.model_copy(update={"budget_seconds": remaining}),
                                       folder / "final-gradient", operation="gradient", cancel_event=cancel_event,
                                       executable=binary, process_runner=execute_process)
                    result.diagnostics["final_gradient"] = {"status": final.status, "diagnostics": final.diagnostics,
                        "command": final.command, "elapsed_seconds": final.elapsed_seconds}
                    if (final.status != "completed" or final.converged is not True
                            or final.gradient_hartree_per_bohr is None or final.energy_hartree is None):
                        result.status = final.status if final.status != "completed" else "failed"
                        result.converged = False
                        result.diagnostics["reason"] = "Independent final optimization gradient did not complete"
                        return result
                    if (final.engine_version != result.engine_version
                            or final.metadata.get("executable_sha256") != result.metadata["executable_sha256"]
                            or abs(energy - final.energy_hartree) > 2e-7):
                        raise EngineParseError("Optimization and final gradient disagree in executable, version or energy")
                    gradient = final.gradient_hartree_per_bohr
                    strict = method.profile_id == "orca-vpt2-reference-v1"
                    max_threshold, rms_threshold = (1e-7, 3e-8) if strict else (1e-5, 3e-6)
                    values = np.asarray(gradient, dtype=float)
                    maximum = float(np.max(np.abs(values)))
                    rms = float(np.sqrt(np.mean(values ** 2)))
                    stationary = maximum <= max_threshold and rms <= rms_threshold
                    result.diagnostics["independent_stationarity"] = {
                        "max_gradient_hartree_per_bohr": maximum, "rms_gradient_hartree_per_bohr": rms,
                        "max_gradient_threshold": max_threshold, "rms_gradient_threshold": rms_threshold,
                        "passed": stationary, "scope": "independent final EnGrad; no Hessian classification"}
                    result.converged = result.converged and stationary
                    result.metadata["final_gradient_verification"] = {
                        "execution_kind": "real", "method": method.model_dump(mode="json"),
                        "directory": "final-gradient", "energy_hartree": final.energy_hartree,
                        "energy_difference_hartree": final.energy_hartree - energy,
                        "engine": final.engine, "engine_version": final.engine_version,
                        "executable_sha256": final.metadata["executable_sha256"],
                        "command": final.command, "resources": final.metadata["resources"],
                        "input_molecule_sha256": digest_json(output_molecule.model_dump(mode="json")),
                        "native_files_sha256": {
                            name: hashlib.sha256((folder / "final-gradient" / name).read_bytes()).hexdigest()
                            for name in ("job.inp", "engine.stdout", "job.engrad")},
                        "budget_scope": "remaining original attempt wall budget"}
            else:
                result.converged = True
        dipole_output = (folder / "final-gradient" / "engine.stdout"
                         if result.metadata.get("final_gradient_verification") else Path(process.stdout_path))
        dipole = parse_cartesian_dipole(dipole_output.read_text(errors="replace"), method.engine)
        if dipole is not None:
            from .science import geometry_digest

            result.metadata["dipole_cartesian_debye"] = dipole["cartesian_debye"]
            result.metadata["dipole_provenance"] = {
                **dipole, "geometry_digest": geometry_digest(output_molecule),
                "method": method.method, "engine": method.engine, "engine_version": result.engine_version,
                "raw_output": dipole_output.relative_to(folder).as_posix(),
                "raw_output_sha256": hashlib.sha256(dipole_output.read_bytes()).hexdigest(),
            }
        if (result.metadata.get("final_gradient_verification")
                and ((cancel_event is not None and cancel_event.is_set())
                     or time.monotonic() - start >= resources.budget_seconds)):
            result.status = "cancelled" if cancel_event is not None and cancel_event.is_set() else "timed-out"
            result.converged = False
            result.diagnostics["reason"] = "Optimization attempt stopped before final-gradient publication"
            return result
        result.energy_hartree = energy
        result.gradient_hartree_per_bohr = gradient if operation != "energy" else None
        result.molecule = output_molecule
        if not result.converged:
            result.status = "partial"
            result.diagnostics["reason"] = "requested optimization convergence was not established"
        result.metadata["gradient_units"] = "hartree/bohr" if gradient is not None else None
        result.metadata["energy_definition"] = "electronic potential energy; no thermochemical correction"
        result.metadata["convergence_scope"] = "geometry and electronic" if operation == "optimize" else "electronic only"
        result.metadata["stationary_point_classification"] = "unclassified; no frequency Hessian"
        return result
    except (EngineParseError, OSError, ValueError) as exc:
        result.status = "failed"
        result.converged = False
        result.diagnostics["reason"] = str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - start
        try:
            result.artifacts = artifact_inventory(folder)
        except (OSError, EngineParseError) as exc:
            result.status = "failed"
            result.converged = False
            result.diagnostics["artifact_error"] = str(exc)
