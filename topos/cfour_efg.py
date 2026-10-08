"""Hash-bound native CFOUR 2.1 correlated EFG observations.

The positively supported grammar is the authentic CCSD(T) FIRST_ORDER output
from the retained private Actions diagnostic 37717679093. Native atom/frame
and correlated density are checked independently of nuclear moments.
Acquisition remains available independently of nuclear moments. Native units
and sign can be admitted by a separate compiled, protocol-scoped empirical
profile only with fresh exact-build BASE authority and bound process evidence.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import numpy as np

from .cfour_properties import CfourEfgConventionDeclaration, rotate_efg_tensors
from .chemistry import atomic_number
from .engines import EngineParseError
from .models import Molecule
from .science import BOHR_ANGSTROM
from .storage import IntegrityError, confined_file

_TOKEN = r"[-+]?\d+\.\d{10}"
_COMPONENTS = re.compile(
    r"[ \t]*XX =\s*(" + _TOKEN + r")\s+YY =\s*(" + _TOKEN + r")\s+ZZ =\s*(" + _TOKEN
    + r")[ \t]*\n[ \t]*XY =\s*(" + _TOKEN + r")\s+XZ =\s*(" + _TOKEN
    + r")\s+YZ =\s*(" + _TOKEN + r")[ \t]*(?:\n|$)"
)
_BUILTIN_CHI = re.compile(
    r"\s*In kHz, Mass number\s+[1-9]\d*\s*\n"
    + "".join(r"[ \t]*CHI" + item + r" =\s*[-+]?\d+\.\d{5}[ \t]*\n"
              for item in ("xx", "yy", "zz", "xy", "xz", "yz"))
    + r"\s*\Z"
)


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _one_program(raw: str, name: str) -> tuple[str, int, int]:
    starts = list(re.finditer(
        r"(?m)^[ \t]*--invoking executable(?:--[ \t]*\n[ \t]*|[ \t]+)"
        + r"(?:\S*/)?" + re.escape(name) + r"[ \t]*\n", raw))
    ends = list(re.finditer(
        r"(?m)^[ \t]*--executable[ \t]+" + re.escape(name)
        + r"[ \t]+finished with status[ \t]+(-?\d+)\b[^\n]*(?:\n|$)", raw))
    if len(starts) != 1 or len(ends) != 1 or starts[0].end() >= ends[0].start() or ends[0][1] != "0":
        raise EngineParseError("Native EFG requires one successfully completed " + name + " invocation")
    return raw[starts[0].end():ends[0].start()], starts[0].start(), ends[0].end()


def _correlated_properties(raw: str, molecule: Molecule) -> tuple[str, dict[str, Any]]:
    density, density_start, density_end = _one_program(raw, "xdens")
    if (density.count("CCSD(T) density and intermediates are calculated.") != 1
            or density.count("Density calculation successfully completed.") != 1):
        raise EngineParseError("EFG lacks the explicitly completed native CCSD(T) density")
    traces = re.findall(r"(?m)^\s*Trace of density matrix\s*:\s*(" + _TOKEN + r")\.\s*$", density)
    expected_electrons = sum(atomic_number(symbol) for symbol in molecule.symbols) - molecule.charge
    if len(traces) != 1 or abs(float(traces[0]) - expected_electrons) > 5e-11:
        raise EngineParseError("Native correlated density trace differs from the declared electronic state")
    props, props_start, props_end = _one_program(raw, "xprops")
    if density_end > props_start:
        raise EngineParseError("The completed CCSD(T) density must precede the native xprops invocation")
    response, response_start, response_end = _one_program(raw, "xlambda")
    if response.count("The lambda equations have converged.") != 1 or response_end > density_start:
        raise EngineParseError("Converged native CC lambda response must precede the CCSD(T) density")
    headers = list(re.finditer(
        r"(?m)^\s*@DRVPRP-I, Properties computed from the (SCF|correlated) density matrix follow\.\s*$", props))
    if len(headers) != 2 or [item[1] for item in headers] != ["SCF", "correlated"]:
        raise EngineParseError("EFG requires separately identified SCF and correlated xprops blocks")
    correlated = props[headers[1].end():]
    stops = list(re.finditer(r"(?m)^\s*Mulliken population analysis of SCF density\.\s*$", correlated))
    if len(stops) != 1:
        raise EngineParseError("Native correlated property block has no unique completion boundary")
    correlated = correlated[:stops[0].start()]
    return correlated, {"method": "CCSD(T)", "native_density_trace": traces[0],
                        "electrons": expected_electrons,
                        "completed_density_program": "xdens", "completed_property_program": "xprops",
                        "density_program_sha256": _sha(density),
                        "lambda_response_program_sha256": _sha(response),
                        "native_program_order": ["xlambda-completed", "xdens-completed", "xprops-invoked"],
                        "native_program_span_convention": "UTF-8 byte half-open intervals [invocation_start, completion_end)",
                        "native_program_spans_utf8_bytes": {
                            name: {"invocation_start": len(raw[:start].encode("utf-8")),
                                   "completion_end": len(raw[:end].encode("utf-8"))}
                            for name, start, end in (("xlambda", response_start, response_end),
                                                    ("xdens", density_start, density_end),
                                                    ("xprops", props_start, props_end))},
                        "correlated_property_block_sha256": _sha(correlated),
                        "scope": "Explicit completed CCSD(T) density, not an SCF tensor or energy-only attribution"}


def parse_cfour_efg(raw: str, efg: str | None, molecule: Molecule,
                    native_coordinates_angstrom: Any, *, engine_version: str, method: str,
                    declaration: CfourEfgConventionDeclaration | None = None) -> dict[str, Any]:
    """Acquire native tensors, requiring exact correlated table/file identity.

    Native execution/runtime/control/SCF/CC checks remain the outer adapter's
    authority. This helper neither executes an engine nor proves nuclear data.
    """
    if engine_version != "2.1" or method != "CCSD(T)":
        raise EngineParseError("The independently fixture-backed EFG grammar supports CFOUR 2.1 CCSD(T) only")
    if not efg:
        raise EngineParseError("FIRST_ORDER requires the authentic native EFG artifact")
    correlated, density = _correlated_properties(raw, molecule)
    dipoles = re.findall(r"(?m)^\s*Components of electric dipole moment[ \t]*\n"
                         r"[ \t]*X =\s*(" + _TOKEN + r")\s+Y =\s*(" + _TOKEN
                         + r")\s+Z =\s*(" + _TOKEN + r")[ \t]*$", correlated)
    if len(dipoles) != 1:
        raise EngineParseError("The native correlated property block requires one complete dipole")
    qcomp = list(re.finditer(r"(?m)^\s*Coordinates used in calculation \(QCOMP\)[ \t]*\n"
                            r"[ \t]*-+[ \t]*\n[ \t]*Z-matrix[ \t]+Atomic[ \t]+Coordinates \(in bohr\)[ \t]*\n"
                            r"[ \t]*Symbol[ \t]+Number[ \t]+X[ \t]+Y[ \t]+Z[ \t]*\n"
                            r"[ \t]*-+[ \t]*\n(?P<rows>.*?)^[ \t]*-+[ \t]*$", raw, re.S))
    if len(qcomp) != 1:
        raise EngineParseError("Native EFG requires one explicit QCOMP coordinate frame")
    qrows = [line.split() for line in qcomp[0]["rows"].splitlines() if line.strip()]
    if (len(qrows) != len(molecule.symbols) or any(len(row) != 5 for row in qrows)
            or [row[0] for row in qrows] != molecule.symbols
            or [row[1] for row in qrows] != [str(atomic_number(symbol)) for symbol in molecule.symbols]
            or any(re.fullmatch(r"[-+]?\d+\.\d{8}", token) is None for row in qrows for token in row[2:])):
        raise EngineParseError("Native EFG QCOMP inventory or observed coordinate grammar differs")
    qxyz = np.asarray([row[2:] for row in qrows], dtype=float) * BOHR_ANGSTROM
    supplied_xyz = np.asarray(native_coordinates_angstrom, dtype=float)
    if supplied_xyz.shape != qxyz.shape or not np.allclose(supplied_xyz, qxyz, atol=2e-12, rtol=0):
        raise EngineParseError("Native EFG coordinates must be the actual stdout QCOMP frame")
    headings = list(re.finditer(r"(?m)^\s*Electric field gradient at atomic centers\s*$", correlated))
    endings = list(re.finditer(r"(?m)^\s*Electrostatic potential at atomic centers\s*$", correlated))
    if len(headings) != 1 or len(endings) != 1 or headings[0].end() >= endings[0].start():
        raise EngineParseError("Native correlated EFG block is missing, duplicated or incomplete")
    table = correlated[headings[0].end():endings[0].start()]
    centers = list(re.finditer(r"(?m)^\s*Z-matrix center\s+(\d+):[ \t]*\n"
                              r"[ \t]*Atomic charge is[ \t]+(\d+)[ \t]*\n", table))
    if len(centers) != len(molecule.symbols) or table[:centers[0].start()].strip():
        raise EngineParseError("Native EFG must include exactly the requested indexed atomic centers")
    tensors, tokens, ignored = [], [], []
    for index, center in enumerate(centers):
        if int(center[1]) != index + 1 or int(center[2]) != atomic_number(molecule.symbols[index]):
            raise EngineParseError("Native EFG center index or atomic charge differs from the molecule")
        end = centers[index + 1].start() if index + 1 < len(centers) else len(table)
        body = table[center.end():end]
        components = _COMPONENTS.match(body)
        if components is None:
            raise EngineParseError("Native EFG requires the complete observed six-component 10-decimal grammar")
        rest = body[components.end():]
        if rest.strip():
            if _BUILTIN_CHI.fullmatch(rest) is None:
                raise EngineParseError("Native EFG contains an unknown, duplicated or malformed center record")
            ignored.append(index + 1)
        xx, yy, zz, xy, xz, yz = map(float, components.groups())
        tensors.append([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]])
        tokens.append(dict(zip(("xx", "yy", "zz", "xy", "xz", "yz"), components.groups(), strict=True)))
    rows = [line.split() for line in efg.splitlines() if line.strip()]
    if (len(rows) != 3 * len(molecule.symbols)
            or any(len(row) != 3 or any(re.fullmatch(_TOKEN, item) is None for item in row) for row in rows)):
        raise EngineParseError("Native EFG file requires exactly three observed Cartesian rows per atom")
    file_tensors = np.asarray(rows, dtype=float).reshape(len(molecule.symbols), 3, 3)
    if not np.array_equal(file_tensors, np.asarray(tensors)):
        raise EngineParseError("Native EFG file does not equal the requested correlated-density stdout tensor")
    try:
        rotated = rotate_efg_tensors(molecule, molecule.symbols, native_coordinates_angstrom,
                                    tensors, np.full_like(file_tensors, 5e-11))
    except ValueError as exc:
        raise EngineParseError(str(exc)) from exc
    declared = (CfourEfgConventionDeclaration.model_validate(declaration.model_dump())
                if declaration is not None else None)
    if declared is not None and declared.engine_version != engine_version:
        raise EngineParseError("Native EFG convention declaration is bound to a different engine version")
    for key in tuple(rotated):
        if key.endswith("_atomic_units"):
            rotated[key.removesuffix("_atomic_units") + "_native_units"] = rotated.pop(key)
    return {**rotated,
            "units": declared.native_units if declared else "native-unlabeled-EFG-components",
            "native_frame": "indexed CFOUR stdout QCOMP Cartesian coordinates; file equals correlated xprops table",
            "native_coordinate_printing": "eight decimal places in bohr",
            "coordinate_frame_uncertainty_propagated": False,
            "rotated_print_bound_scope": "EFG token rounding under the nominal inferred rotation; coordinate-printing, alignment and geometry error are excluded",
            "source_tokens": tokens, "density_provenance": density,
            "correlated_dipole_native_atomic_units": list(map(float, dipoles[0])),
            "raw_artifacts_sha256": {"engine.stdout": _sha(raw), "EFG": _sha(efg)},
            "native_execution_verified": False,
            "native_unit_sign_independently_verified": False,
            "native_convention_declaration": declared.model_dump(mode="json") if declared else None,
            "unit_sign_authority": "explicit caller-reviewed declaration; independently unverified" if declared else "unresolved",
            "builtin_nuclear_chi_ignored_atom_indices": ignored,
            "builtin_nuclear_chi_policy": "Native Mass number defaults are never user isotope or nuclear-Q input",
            "scope": "Correlated indexed EFG acquisition; unit/sign authority and nuclear conversion require separate review"}


def verify_cfour_property_recovery(folder: Path, artifact_paths: list[Path], molecule: Molecule,
                                   protocol_data: dict, observation: dict,
                                   runtime_authority: dict | None = None) -> dict:
    """Reparse raw property evidence; caller separately verifies hashes/runtime."""
    from .external_engines import ExternalProtocol, parse_cfour_output

    folder = folder.absolute()
    paths = [path.absolute() for path in artifact_paths]
    outputs = [path for path in paths if path.name == "engine.stdout"]
    if len(outputs) != 1:
        raise IntegrityError("A CFOUR property component requires exactly one raw Cartesian evaluation")
    parent = outputs[0].parent
    adjacent = {}
    for name in ("engine.stdout", "DIPOL", "EFG"):
        expected = parent / name
        if paths.count(expected) != 1:
            raise IntegrityError("CFOUR property recovery requires each adjacent hash-bound raw artifact")
        try:
            relative = expected.relative_to(folder).as_posix()
        except ValueError as exc:
            raise IntegrityError("CFOUR property evidence lies outside its assigned folder") from exc
        adjacent[name] = confined_file(folder, relative).read_bytes().decode("utf-8", errors="strict")
    grd = parent / "GRD"
    if paths.count(grd) > 1:
        raise IntegrityError("CFOUR property recovery has duplicate GRD evidence")
    observed = parse_cfour_output(adjacent["engine.stdout"], molecule,
        ExternalProtocol.model_validate(protocol_data), dipol=adjacent["DIPOL"], efg=adjacent["EFG"],
        grd=confined_file(folder, grd.relative_to(folder).as_posix()).read_bytes().decode("utf-8", errors="strict")
            if grd in paths else None)
    if runtime_authority is not None:
        from .cfour_operator import apply_operator_authority, property_operator_authority

        context = property_operator_authority(folder, paths, runtime_authority, molecule, protocol_data)
        observed["efg_observation"] = apply_operator_authority(observed["efg_observation"], context)
    if observation != observed:
        raise IntegrityError("CFOUR property result differs from a fresh parse of its exact native raw evidence")
    return observed
