"""Conditional HF DBOC under an explicit, unmodified native mass convention.

Only default masses selected internally by public CFOUR 2.1 are requested.
No ISOMASS syntax or nuclear masses are invented. Numeric atomic rotor masses
are accepted only when printed by every completed native ON evaluation and
strictly bound to atom order, geometry, version and immutable raw artifacts.
"""
from __future__ import annotations

import math
import re
import shutil
import time
from decimal import Decimal
from pathlib import Path
from threading import Event
from typing import Any, Callable, Literal

import numpy as np

from .base_integration import BaseRuntime
from .cfour_corrections import ScalarCampaignStopped, apply_scalar_geometry_increment
from .engines import EngineParseError, EngineResult, _number, artifact_inventory
from .external_engines import (
    ExternalProtocol,
    _native_completion,
    _native_genbas,
    _physical_input,
    cfour_input,
    parse_cfour_output,
)
from .higher_composite import HigherCoordinateSet, NumericalGeometryOptions, checked_energy_gradient
from .matrix_components import run_component
from .models import Molecule, ResourceLimits
from .science import BOHR_ANGSTROM, validate_stereochemical_preservation
from .storage import IntegrityError, atomic_json, digest_json, file_digest

MASS_CONVENTION = "cfour-2.1-native-default-masses-v1"
ALLOWED_ELEMENTS = frozenset({"H", "C", "N", "O", "F"})
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
SOURCES = [
    "https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/psi4/src/read_options.cc#L3891-L3895",
    "https://github.com/RagnarB83/ash/blob/f43c421f3bca48e3740bab7a10acb5a2676246a0/ash/interfaces/interface_CFour.py#L459-L484",
    "https://github.com/HPQC-LABS/AI_ENERGIES/blob/3098f558135589f5acf52474428ba020a561d58d/C/DBOC/aug-cc-pCVDZ-NR/CFOUR.txt",
]


class DefaultMassDBOCProtocol(ExternalProtocol):
    engine: Literal["cfour"] = "cfour"
    engine_version: Literal["2.1"] = "2.1"
    operation: Literal["energy"] = "energy"
    method: Literal["HF"] = "HF"
    frozen_core: Literal[False] = False
    relativistic: Literal["OFF"] = "OFF"
    dboc: bool = True
    contraction: Literal["GENERAL", "UNCONTRACTED"]
    mass_convention: Literal["cfour-2.1-native-default-masses-v1"]

    def electronic_protocol(self) -> ExternalProtocol:
        return ExternalProtocol.model_validate(self.model_dump(exclude={"relativistic", "dboc", "contraction", "mass_convention"}))


def mass_convention_record() -> dict[str, Any]:
    return {"name": MASS_CONVENTION, "explicit_isotopes_supported": False,
            "allowed_elements": sorted(ALLOWED_ELEMENTS), "native_numeric_masses_verified": False,
            "rotor_mass_attestation_available": False,
            "selection": "CFOUR native defaults; no custom isotope or mass input",
            "scope": "does not assert equality with TOPOS/Mendeleev masses or a historical CFOUR mass table"}


def validate_default_mass_domain(molecule: Molecule) -> None:
    Molecule.model_validate(molecule.model_dump())
    if any(value is not None for value in molecule.isotopes):
        raise ValueError("Native-default DBOC rejects every explicit isotope; no mass substitution is supported")
    if not set(molecule.symbols) <= ALLOWED_ELEMENTS:
        raise ValueError("Native-default DBOC is restricted to H, C, N, O and F")
    if molecule.multiplicity != 1 or molecule.environment not in ({}, {"phase": "gas"}):
        raise ValueError("Native-default HF DBOC requires an isolated closed-shell singlet")


def dboc_input(molecule: Molecule, protocol: DefaultMassDBOCProtocol, resources: ResourceLimits) -> str:
    protocol = DefaultMassDBOCProtocol.model_validate(protocol.model_dump())
    validate_default_mass_domain(molecule)
    raw = cfour_input(molecule, protocol.electronic_protocol(), resources)
    before, after = raw.rsplit(")", 1)
    if protocol.dboc:
        # Native DBOC requires internal response/second-derivative machinery;
        # historical successful input lets DBOC select it, rather than forcing
        # DERIV_LEVEL=ZERO and suppressing required native modules.
        before = before.removesuffix(",\nDERIV_LEVEL=ZERO")
    return before + f",\nDBOC={'ON' if protocol.dboc else 'OFF'},\nRELATIVISTIC=OFF,\nCONTRACTION={protocol.contraction})" + after


def _rounding_bound(value: str) -> float:
    exponent = Decimal(value.replace("D", "E").replace("d", "e")).as_tuple().exponent
    return float(Decimal(5).scaleb(exponent - 1))


def parse_cfour_rotor_mass_table(raw: str, molecule: Molecule) -> dict[str, Any]:
    """Parse observed vibrational atomic masses, never assert native completion.

    CFOUR's Cartesian Z-matrix table fixes indexed atom order. The printed
    vibrational mass vector is tied to that same order; molecular identities
    and geometry must independently agree. No nuclear mass is inferred.
    """
    import hashlib

    from .chemistry import atomic_number, resolved_masses
    from .external_engines import _proper_rotation

    molecule = Molecule.model_validate(molecule.model_dump(mode='json'))
    if any(i is not None for i in molecule.isotopes):
        raise EngineParseError('Default-mass observation cannot validate an explicitly requested isotope')
    if re.search(r'SIGSEGV|segmentation fault|forrtl:\s*severe|fatal error', raw, re.I):
        raise EngineParseError('CFOUR mass observation contains native fatal error')
    lines = raw.splitlines()
    n = len(molecule.symbols)
    tables = []
    for index, line in enumerate(lines):
        if not re.fullmatch(r'\s*masses used \(in AMU\) in vibrational analysis:\s*', line):
            continue
        printed, last = [], index
        for position in range(index+1, len(lines)):
            text = lines[position].strip()
            if not text:
                if printed:
                    break
                continue
            fields = text.split()
            if not all(re.fullmatch(_FLOAT, field) for field in fields):
                break
            printed.extend(fields)
            last = position
        if len(printed) != n:
            raise EngineParseError('Native vibrational mass vector is incomplete or has extra atoms')
        values = [_number(value) for value in printed]
        bounds = [_rounding_bound(value) for value in printed]
        if min(values) <= 0 or max(bounds) > 5.01e-7:
            raise EngineParseError('Native atomic masses must be positive and printed to at least six decimals')
        tables.append({'masses_amu': values, 'rounding_half_width_amu': bounds,
                       'printed_values': printed, 'source_lines': [index+1, last+1]})
    if not tables:
        raise EngineParseError('Native vibrational atomic mass vector is absent')
    if any((table['masses_amu'], table['rounding_half_width_amu']) !=
           (tables[0]['masses_amu'], tables[0]['rounding_half_width_amu']) for table in tables[1:]):
        raise EngineParseError('Repeated native atomic mass vectors or precision differ')
    masses = tables[0]['masses_amu']
    # Identity-only rejection screen. These independent atomic data never
    # replace the native values or attest CFOUR's internal DBOC nuclear masses.
    expected, isotopes = resolved_masses(molecule)
    if not np.allclose(masses, expected, atol=1e-4, rtol=0):
        raise EngineParseError('Native mass vector does not follow the expected atomic isotope order')
    pattern = (r'Z-matrix\s+Atomic\s+Coordinates \(in bohr\)\s*\n'
               r'\s*Symbol\s+Number\s+X\s+Y\s+Z\s*\n\s*-+\s*\n(.*?)\n\s*-+')
    geometries = []
    for match in re.finditer(pattern, raw, re.S):
        rows = [row.split() for row in match[1].splitlines() if row.strip()]
        if (len(rows) != n or any(len(row) != 5 for row in rows)
                or [row[0].capitalize() for row in rows] != molecule.symbols
                or [row[1] for row in rows] != [str(atomic_number(s)) for s in molecule.symbols]):
            raise EngineParseError('Native Cartesian mass/geometry atom inventory differs')
        xyz = np.asarray([[_number(v) for v in row[2:]] for row in rows]) * BOHR_ANGSTROM
        rotation = _proper_rotation(xyz, np.asarray(molecule.coordinates))
        geometries.append({'coordinates_angstrom': xyz.tolist(), 'native_coordinate_units': 'bohr',
                           'source_lines': [raw.count('\n', 0, match.start())+1, raw.count('\n', 0, match.end())+1],
                           'proper_rotation_to_requested': rotation.tolist()})
    if not geometries and n == 1:
        # Authentic monatomic output omits its trivial Cartesian table. Bind
        # the observed Z-matrix entry and element/Z, without inventing positions.
        matches = list(re.finditer(r'(?m)^\s*1\s+([A-Z][a-z]?)\s+(\d+)\s+(' + _FLOAT + r')\s*$', raw))
        if len(matches) != 1 or matches[0][1] != molecule.symbols[0] or int(matches[0][2]) != atomic_number(molecule.symbols[0]):
            raise EngineParseError('Native monatomic Z-matrix inventory is absent or ambiguous')
        geometries.append({'coordinates_angstrom': None, 'native_coordinate_units': None,
                           'source_lines': [raw.count('\n', 0, matches[0].start())+1, raw.count('\n', 0, matches[0].end())+1],
                           'geometry_scope': 'single atom; no orientation or internal geometry'})
    if not geometries:
        raise EngineParseError('Native mass vector lacks its indexed Cartesian geometry')
    return {'schema': 'topos-cfour-observed-atomic-masses/1', 'atom_ids': molecule.atom_ids,
            'symbols': molecule.symbols, 'masses_amu': masses,
            'rounding_half_width_amu': tables[0]['rounding_half_width_amu'],
            'atoms': [{'atom_id': atom_id, 'native_index': i+1, 'symbol': symbol, 'mass_amu': masses[i],
                       'rounding_half_width_amu': tables[0]['rounding_half_width_amu'][i]}
                      for i, (atom_id, symbol) in enumerate(zip(molecule.atom_ids, molecule.symbols, strict=True))],
            'mass_table_observations': tables, 'native_geometries': geometries,
            'requested_molecule': molecule.model_dump(mode='json'),
            'requested_geometry_sha256': digest_json(molecule.model_dump(mode='json')),
            'source_text_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            'mass_role': 'atomic masses used in native vibrational analysis and selected for rigid-rotor inertia',
            'mass_source': 'masses used (in AMU) in vibrational analysis',
            'isotope_sanity_check': isotopes, 'mass_values_substituted': False,
            'internal_dboc_nuclear_masses_numerically_verified': False,
            'nuclear_mass_scope': 'native DBOC default convention; no nuclear vector printed here or inferred by electron subtraction',
            'native_execution_verified': False, 'arbitrary_isotopes_supported': False}


def _bind_rotor_mass_execution(observation, molecule, identity, stdout):
    """Attach actual native identity only after parse_dboc_output succeeds."""
    if identity[0] != '2.1' or any(not isinstance(v, str) or not v for v in identity):
        raise IntegrityError('Observed atomic masses require the exact native 2.1 identity')
    result = dict(observation)
    result.update(native_engine_identity=list(identity), native_execution_verified=True,
                  source_artifact={'path': str(Path(stdout).resolve()), 'sha256': file_digest(Path(stdout)),
                                   'size_bytes': Path(stdout).stat().st_size},
                  requested_geometry_sha256=digest_json(molecule.model_dump(mode='json')))
    return result


def _collect_rotor_mass_attestation(record, store, molecule, protocol, native_identity):
    """Reopen every matching completed ON component and reparse native evidence."""
    from .matrix_components import _verified_component

    expected_identity = molecule.model_dump(mode='json', exclude={'coordinates', 'name'})
    observations = []
    protocol_data = protocol.model_dump(mode='json')
    for attempt in record.attempts:
        if attempt.status != 'completed' or not str(attempt.metadata.get('component_key', '')).startswith('default-dboc-True-'):
            continue
        if attempt.metadata.get('requested_protocol') != protocol_data:
            raise IntegrityError('Completed DBOC ON components mixed protocols')
        current = Molecule.model_validate(attempt.metadata['input_molecule'])
        if current.model_dump(mode='json', exclude={'coordinates', 'name'}) != expected_identity:
            raise IntegrityError('Completed DBOC mass observations changed molecular identity')
        key = 'default-dboc-True-' + digest_json(current.coordinates)
        identity = digest_json({'component_key': key, 'molecule': current.model_dump(mode='json'), 'protocol': protocol_data})
        if key != attempt.metadata['component_key']:
            raise IntegrityError('DBOC mass observation is not bound to its exact evaluated geometry')
        native = _verified_component(attempt, store, current, protocol_data, identity)
        actual_identity = [native.engine_version, native.metadata.get('executable_sha256'), native.metadata.get('basis_library', {}).get('sha256')]
        if actual_identity != list(native_identity):
            raise IntegrityError('DBOC atomic mass observations mixed native engines or basis libraries')
        stdout = Path(native.diagnostics['process']['stdout_path'])
        if str(stdout.resolve()) not in {str(Path(a.path).resolve()) for a in native.artifacts}:
            raise IntegrityError('DBOC mass observation stdout is not inventoried')
        parsed = parse_dboc_output(stdout.read_text(), current, protocol)
        bound = _bind_rotor_mass_execution(parsed['rotor_mass_attestation'], current, actual_identity, stdout)
        if bound != native.metadata.get('native_result', {}).get('rotor_mass_attestation'):
            raise IntegrityError('Native atomic mass metadata differs from raw evidence')
        observations.append({'attempt_id': attempt.attempt_id, **bound})
    if not observations:
        raise IntegrityError('No completed native DBOC ON atomic mass observations exist')
    first = observations[0]
    for item in observations[1:]:
        if any(item[key] != first[key] for key in ('atom_ids', 'symbols', 'masses_amu', 'rounding_half_width_amu')):
            raise IntegrityError('Native DBOC campaign atomic mass vectors or precision differ')
    return {'schema': 'topos-cfour-campaign-atomic-masses/1',
            **{key: first[key] for key in ('atom_ids', 'symbols', 'masses_amu', 'rounding_half_width_amu', 'atoms',
                                         'mass_role', 'mass_source', 'native_engine_identity', 'nuclear_mass_scope')},
            'observation_count': len(observations), 'observations': observations,
            'native_execution_verified': True, 'every_completed_dboc_on_evaluation_checked': True,
            'mass_values_substituted': False, 'arbitrary_isotopes_supported': False,
            'internal_dboc_nuclear_masses_numerically_verified': False,
            'dboc_off_reference': 'electronic BO surface; no vibrational mass attestation required'}


def validate_rotor_mass_attestation(report, record, store, molecule, native_identity):
    """Reject an injected aggregate by reconstructing every native observation."""
    protocol = DefaultMassDBOCProtocol.model_validate(report['native_optimizations']['hf_plus_dboc']['protocol'])
    requested = record.request.matrix_inputs.get('month_corrections', {}).get('dboc')
    if requested is not None and DefaultMassDBOCProtocol.model_validate(requested) != protocol:
        raise IntegrityError('Mass report differs from the immutable requested DBOC protocol')
    rebuilt = _collect_rotor_mass_attestation(record, store, molecule, protocol, native_identity)
    if rebuilt != report.get('rotor_mass_attestation'):
        raise IntegrityError('Aggregate rotor mass attestation differs from native component evidence')
    return rebuilt


def parse_default_mass_dboc_section(raw: str) -> dict[str, Any]:
    """Read authentic section grammar only; caller must establish method/version.

    Historical default-mass output prints the total twice. Consistent repeated
    observations are retained; an early total before a subsequent mass failure
    is never accepted as completed evidence.
    """
    if re.search(r"SIGSEGV|segmentation fault|forrtl:\s*severe|fatal error", raw, re.I):
        raise EngineParseError("Native DBOC reports a fatal error after or before its correction")
    reads = re.findall(r"(?im)^\s*readis\s+is\s+([TF])\s*$", raw)
    if not reads or set(reads) != {"F"} or re.search(
            r"read masses from file ISOMASS|Evaluating DBOC using custom masses|Non-standard isotopic masses", raw, re.I):
        raise EngineParseError("DBOC does not establish the unmodified native-default mass path")
    totals = re.findall(r"(?m)^\s*The total diagonal Born-Oppenheimer correction \(DBOC\) is:\s*(" + _FLOAT + r")\s+a\.u\.\s*$", raw)
    if not totals:
        raise EngineParseError("Native default-mass DBOC total in Hartree is absent")
    values = [_number(text) for text in totals]
    rounding = max(_rounding_bound(text) for text in totals)
    if min(values) < 0 or max(values) - min(values) > 2 * rounding:
        raise EngineParseError("Native HF DBOC must be nonnegative and repeated totals must agree")
    return {"dboc_energy_hartree": values[-1], "printed_totals_hartree": values,
            "dboc_print_rounding_bound_hartree": rounding,
            "mass_convention": mass_convention_record()}


def parse_dboc_output(raw: str, molecule: Molecule, protocol: DefaultMassDBOCProtocol) -> dict[str, Any]:
    protocol = DefaultMassDBOCProtocol.model_validate(protocol.model_dump())
    validate_default_mass_domain(molecule)
    _native_completion(raw, protocol.electronic_protocol())
    for label, wanted in (("DBOC", "ON" if protocol.dboc else "OFF"), ("RELATIVIST(?:IC)?", "OFF"), ("CONTRACTION", protocol.contraction)):
        values = re.findall(r"(?m)^\s*" + label + r"\s+\w+\s+(\S+)", raw)
        if values != [wanted]:
            raise EngineParseError(f"DBOC native {label} setting differs from the exact requested protocol")
    native = parse_cfour_output(raw, molecule, protocol.electronic_protocol())
    correction = parse_default_mass_dboc_section(raw) if protocol.dboc else {
        "dboc_energy_hartree": 0., "dboc_print_rounding_bound_hartree": 0.,
        "mass_convention": mass_convention_record(), "dboc_not_requested": True}
    scf = re.findall(r"E\(SCF\)\s*=\s*(" + _FLOAT + r")", raw)
    if not scf:
        raise EngineParseError("Native HF electronic energy precision is not established")
    electronic_rounding = max(_rounding_bound(text) for text in scf)
    potential = math.fsum([native["energy_hartree"], correction["dboc_energy_hartree"]])
    if not math.isfinite(potential):
        raise EngineParseError("HF plus DBOC potential arithmetic is nonfinite")
    if protocol.dboc:
        correction['rotor_mass_attestation'] = parse_cfour_rotor_mass_table(raw, molecule)
    native.update(correction, dboc_requested=protocol.dboc, potential_energy_hartree=potential,
        potential_definition="E_HF + native-default-mass DBOC" if protocol.dboc else "E_HF, DBOC explicitly OFF",
        potential_rounding_bound_hartree=electronic_rounding + correction["dboc_print_rounding_bound_hartree"] + abs(float(np.spacing(potential))),
        energy_definition="HF electronic energy alone; DBOC and corrected potential are separately identified",
        analytic_dboc_gradient=False)
    return native


def quantized_gradient_error_bound(options: NumericalGeometryOptions, energy_rounding_hartree: float,
                                   step_disagreement_hartree_per_bohr: float) -> dict[str, float]:
    """Bound endpoint print rounding and add the observed step sensitivity.

    Only the print-quantization term is a bound. The combined acceptance margin
    is not a rigorous total error bound or a bound on electronic SCF error.
    """
    options = NumericalGeometryOptions.model_validate(options.model_dump())
    if any(not math.isfinite(value) or value < 0 for value in (energy_rounding_hartree, step_disagreement_hartree_per_bohr)):
        raise ValueError("Finite nonnegative native rounding and step-sensitivity bounds are required")
    floor = 2 * energy_rounding_hartree / options.step_bohr
    uncertainty = floor + step_disagreement_hartree_per_bohr
    if uncertainty > min(options.gradient_max_hartree_per_bohr, options.gradient_rms_hartree_per_bohr) / 4:
        raise ValueError("DBOC output quantization plus step sensitivity cannot resolve the requested gradient convergence")
    return {"print_quantization_gradient_bound_hartree_per_bohr": floor,
            "acceptance_margin_hartree_per_bohr": uncertainty}


def run_default_mass_dboc(molecule: Molecule, protocol: DefaultMassDBOCProtocol,
                          resources: ResourceLimits, workdir: str | Path, *,
                          executable: str | Path | None = None,
                          process_runner: Callable[..., Any] | None = None,
                          cancel_event: Event | None = None) -> EngineResult:
    started, folder = time.monotonic(), Path(workdir)
    result = EngineResult(status="unsupported", engine="cfour", method="HF", operation="energy",
        metadata={"execution_kind": "not-executed", "adapter_validation": "conditional-not-live-validated",
                  "requested_protocol": protocol.model_dump(mode="json"), "sources": SOURCES,
                  "mass_convention": mass_convention_record()})
    try:
        protocol = DefaultMassDBOCProtocol.model_validate(protocol.model_dump())
        _physical_input(molecule, resources)
        validate_default_mass_domain(molecule)
        if folder.is_symlink():
            raise IntegrityError("DBOC work directory cannot be a symlink")
        folder = folder.resolve()
        if folder.exists() and any(folder.iterdir()):
            raise ValueError("DBOC requires a fresh directory without inherited mass or native state files")
        if cancel_event is not None and cancel_event.is_set():
            result.status = "cancelled"
            return result
        if process_runner is None:
            runtime = BaseRuntime()
            runtime.validate_resources(resources)
            executable = runtime.resolve_executable("cfour", executable)
            process_runner = runtime.run_process
        found = shutil.which(str(executable or "xcfour"))
        if found is None:
            result.status, result.diagnostics["reason"] = "unavailable", "Audited CFOUR 2.1 executable is unavailable"
            return result
        binary = Path(found).resolve()
        genbas = _native_genbas(binary, protocol.electronic_protocol(), molecule)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "ZMAT").write_text(dboc_input(molecule, protocol, resources))
        shutil.copyfile(genbas, folder / "GENBAS")
        if file_digest(folder / "GENBAS") != protocol.genbas_sha256:
            raise IntegrityError("GENBAS changed during staging")
        atomic_json(folder / "protocol.json", protocol.model_dump(mode="json"))
        immutable = {str(path): file_digest(path) for path in (folder / "ZMAT", folder / "GENBAS", folder / "protocol.json", binary, genbas)}
        result.metadata.update(executable=str(binary), executable_sha256=file_digest(binary),
            protocol_sha256=digest_json(protocol.model_dump(mode="json")),
            basis_library={"path": str(genbas), "sha256": protocol.genbas_sha256, "contraction": protocol.contraction})
        remaining = resources.budget_seconds - (time.monotonic() - started)
        if remaining <= 0:
            result.status = "timed-out"
            return result
        result.command = [str(binary)]
        process = process_runner(result.command, folder, resources.model_copy(update={"budget_seconds": remaining}),
                                 cancel_event=cancel_event, log_prefix="engine")
        result.status, result.diagnostics["process"] = process.status, process.to_dict()
        result.metadata["execution_kind"] = "real"
        if process.status != "completed" or process.returncode != 0:
            if process.status == "completed":
                result.status = "failed"
            return result
        if (folder / "ISOMASS").exists() or any(Path(path).is_symlink() or file_digest(Path(path)) != sha for path, sha in immutable.items()):
            raise IntegrityError("Native-default DBOC input changed or custom ISOMASS appeared")
        native = parse_dboc_output(Path(process.stdout_path).read_text(errors="replace"), molecule, protocol)
        if protocol.dboc:
            native['rotor_mass_attestation'] = _bind_rotor_mass_execution(native['rotor_mass_attestation'], molecule,
                [native['engine_version'], result.metadata['executable_sha256'], protocol.genbas_sha256], process.stdout_path)
            native['mass_convention'].update(native_numeric_masses_verified=True, rotor_mass_attestation_available=True,
                numeric_mass_scope='observed atomic rotor masses only; internal DBOC nuclear vector not numerically attested')
        atomic_json(folder / "native-result.json", native)
        result.metadata.update(native_result=native, mass_convention=native["mass_convention"],
                               adapter_validation="native-output-validated-for-this-execution")
        result.energy_hartree, result.engine_version = native["energy_hartree"], native["engine_version"]
        result.molecule, result.converged = molecule, True
        return result
    except (ValueError, RuntimeError, OSError) as exc:
        result.status = "failed" if result.metadata["execution_kind"] == "real" else "unsupported" if isinstance(exc, ValueError) else "unavailable"
        result.converged, result.diagnostics["reason"] = False, str(exc)
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - started
        if folder.is_dir() and not folder.is_symlink():
            result.artifacts = artifact_inventory(folder)


def _optimize_dboc_surface(workflow, record, store, protocol, options, deadline, cancel_event):
    from scipy.optimize import minimize

    from .workflow import _topology_preserved

    initial = record.request.molecule
    values, derivatives, identities = {}, {}, set()

    def check():
        stop = cancel_event is not None and cancel_event.is_set()
        if stop or time.monotonic() >= deadline:
            record.status = "cancelled" if stop else "timed-out"
            record.metadata["termination_reason"] = "Default-mass DBOC campaign stopped; native energy components retained"
            store.commit(record)
            raise ScalarCampaignStopped(record.metadata["termination_reason"])

    def energy(x):
        check()
        current = Molecule.model_validate({**initial.model_dump(), "coordinates": (x.reshape(-1, 3) * BOHR_ANGSTROM).tolist()})
        key = digest_json(current.coordinates)
        if key not in values:
            result = run_component(workflow, record, store, "default-dboc-" + str(protocol.dboc) + "-" + key,
                current, protocol, run_default_mass_dboc, deadline, cancel_event)
            if result is None:
                raise ScalarCampaignStopped("Native default-mass DBOC component did not complete")
            native = result.metadata.get("native_result", {})
            potential, rounding = native.get("potential_energy_hartree"), native.get("potential_rounding_bound_hartree")
            if not isinstance(potential, (int, float)) or not isinstance(rounding, (int, float)) or not math.isfinite(potential) or not 0 <= rounding < 1:
                raise IntegrityError("DBOC derivative lacks a validated corrected potential and its output precision")
            values[key] = (potential, rounding)
            identities.add((result.engine_version, result.metadata.get("executable_sha256"), result.metadata.get("basis_library", {}).get("sha256")))
        return values[key][0]

    def evaluate(x):
        check()
        key = digest_json(x.tolist())
        if key not in derivatives:
            value, gradient, sensitivity = checked_energy_gradient(energy, x, options)
            # At the finer h/2 derivative, the denominator is h. Each endpoint
            # contributes its worst-case printed-energy rounding bound.
            sensitivity.update(quantized_gradient_error_bound(options, max(item[1] for item in values.values()),
                sensitivity["maximum_step_disagreement_hartree_per_bohr"]))
            derivatives[key] = (value, gradient, sensitivity)
        return derivatives[key][:2]

    optimized = minimize(evaluate, np.asarray(initial.coordinates).ravel() / BOHR_ANGSTROM, jac=True,
        method="L-BFGS-B", options={"maxiter": options.maximum_iterations, "maxls": 30, "ftol": 1e-15,
        "gtol": min(options.gradient_max_hartree_per_bohr, options.gradient_rms_hartree_per_bohr) / 2})
    value, gradient = evaluate(optimized.x)
    sensitivity = derivatives[digest_json(optimized.x.tolist())][2]
    maximum, rms = float(np.max(np.abs(gradient))), float(np.sqrt(np.mean(gradient**2)))
    error = sensitivity["acceptance_margin_hartree_per_bohr"]
    if maximum + error > options.gradient_max_hartree_per_bohr or rms + error > options.gradient_rms_hartree_per_bohr:
        record.status, record.metadata["termination_reason"] = "partial", "DBOC geometry failed gradient convergence including numerical precision"
        store.commit(record)
        raise ScalarCampaignStopped(record.metadata["termination_reason"])
    molecule = Molecule.model_validate({**initial.model_dump(), "coordinates": (optimized.x.reshape(-1, 3) * BOHR_ANGSTROM).tolist()})
    if not _topology_preserved(initial, molecule) or validate_stereochemical_preservation(initial, molecule)["status"] != "preserved":
        raise ValueError("DBOC optimization changed topology or stereochemistry")
    check()
    return molecule, {"protocol": protocol.model_dump(mode="json"), "options": options.model_dump(mode="json"),
        "potential_energy_hartree": value, "gradient_hartree_per_bohr": gradient.reshape(-1, 3).tolist(),
        "gradient_definition": "numerical derivative of E_HF+DBOC" if protocol.dboc else "numerical derivative of E_HF",
        "derivative_sensitivity": sensitivity, "iterations": int(optimized.nit), "energy_geometries": len(values),
        "native_analytic_dboc_gradient": False, "minimum_hessian_verified": False}, identities


def apply_dboc_geometry_increment(base: Molecule, corrected: Molecule, born_oppenheimer: Molecule,
                                  chart: HigherCoordinateSet) -> dict[str, Any]:
    """Pure additive coordinate arithmetic, without a native-execution claim."""
    for molecule in (base, corrected, born_oppenheimer):
        validate_default_mass_domain(molecule)
    report = apply_scalar_geometry_increment(base, corrected, born_oppenheimer, chart)
    renames = {"base": "base", "relativistic": "hf_plus_dboc", "nonrelativistic": "hf_born_oppenheimer"}
    for key in ("component_parameters", "component_geometry_sha256"):
        report[key] = {renames[name]: value for name, value in report[key].items()}
    report.update(schema_version="topos-default-mass-dboc-geometry/1",
        formula="R_corrected=R_base+(R_min[E_HF+DBOC_native_default]-R_min[E_HF]), same basis and contraction; parameter-wise",
        mass_convention=mass_convention_record(),
        claims={"native_execution_verified": False, "dboc_geometry_computed": False,
                "matrix_row_complete": False, "rotor_constants_publishable": False,
                "stationary_point_verified": False, "minimum_verified": False, "accuracy_claim": None},
        assumptions=["Additive HF adiabatic correction, not a correlated DBOC or a fully composite potential minimum",
                     "Native numeric masses are unverified; no arbitrary isotope or rotor-mass equivalence claim",
                     "Common topology/stereochemistry does not establish the same torsional basin"])
    return report


def calculate_default_mass_dboc_geometry(workflow, record, store, base: Molecule,
                                         protocol: DefaultMassDBOCProtocol, chart: HigherCoordinateSet,
                                         options: NumericalGeometryOptions, deadline: float,
                                         cancel_event: Event | None = None) -> dict[str, Any]:
    protocol = DefaultMassDBOCProtocol.model_validate(protocol.model_dump())
    options = NumericalGeometryOptions.model_validate(options.model_dump())
    if not protocol.dboc:
        raise ValueError("The paired default-mass correction requires explicit DBOC=ON")
    validate_default_mass_domain(base)
    validate_default_mass_domain(record.request.molecule)
    geometries, evaluations, identities = {}, {}, set()
    for role, enabled in (("hf_born_oppenheimer", False), ("hf_plus_dboc", True)):
        leg = DefaultMassDBOCProtocol.model_validate({**protocol.model_dump(), "dboc": enabled})
        geometries[role], evaluations[role], observed = _optimize_dboc_surface(workflow, record, store, leg, options, deadline, cancel_event)
        identities.update(observed)
    if len(identities) != 1 or any(value is None for value in next(iter(identities))):
        raise IntegrityError("Paired DBOC geometries mixed native versions, executables or basis libraries")
    report = apply_dboc_geometry_increment(base, geometries["hf_plus_dboc"], geometries["hf_born_oppenheimer"], chart)
    report.update(native_optimizations=evaluations, native_engine_identity=list(next(iter(identities))),
                  recovery="restart outer optimizer; reuse verified native components at matching geometries")
    report['rotor_mass_attestation'] = _collect_rotor_mass_attestation(record, store, base, protocol,
                                                                    report['native_engine_identity'])
    report['mass_convention'].update(native_numeric_masses_verified=True, rotor_mass_attestation_available=True,
        numeric_mass_scope='observed atomic rotor masses only; internal DBOC nuclear vector not numerically attested')
    report['assumptions'] = [item for item in report['assumptions'] if not item.startswith('Native numeric masses')]
    report['assumptions'].append('Native atomic rotor masses observed per atom; internal DBOC nuclear masses not numerically attested; no arbitrary isotopes')
    report["claims"].update(native_execution_verified=True, dboc_geometry_computed=True,
                           rotor_constants_publishable=True)
    return report
