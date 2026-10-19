"""Data-only, installed-wheel boundary for existing structural operations.

BASE owns process deadlines and resource limits. This provider never executes a
quantum engine and never assigns energies, populations or minimum qualification.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata as metadata
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

SCHEMA = "cochem.topos-structural/1"
MAX_REQUEST_BYTES = 1_048_576
MAX_ATOMS = 256
SOURCE_NAMES = (
    "__init__.py", "__main__.py", "boundary.py", "exceptions.py", "graph.py",
    "resonance.py", "rings.py", "tautomer.py",
)


class Refused(ValueError):
    """An unsupported, unsafe or ambiguous structural request."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ResonanceInput(StrictModel):
    smiles: str = Field(min_length=1, max_length=4096)
    max_structures: StrictInt = Field(default=50, ge=1, le=10000)
    temperature_k: None = None


class TopologyData(StrictModel):
    molecule_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    elements: list[str] = Field(min_length=1, max_length=MAX_ATOMS)
    atomic_numbers: list[Annotated[StrictInt, Field(ge=1, le=118)]] = Field(
        min_length=1, max_length=MAX_ATOMS
    )
    bonds: list[tuple[StrictInt, StrictInt, StrictFloat]] = Field(min_length=1, max_length=4096)
    formal_charges: list[StrictInt] | None = Field(default=None, max_length=MAX_ATOMS)

    @model_validator(mode="after")
    def coherent_arrays(self):
        n = len(self.elements)
        if len(self.atomic_numbers) != n or (
            self.formal_charges is not None and len(self.formal_charges) != n
        ):
            raise ValueError("Atom identity and charge array lengths must agree")
        seen = set()
        for left, right, order in self.bonds:
            pair = tuple(sorted((left, right)))
            if not 0 <= left < n or not 0 <= right < n or left == right or pair in seen:
                raise ValueError("Bonds require unique, distinct, existing atom indices")
            if order not in {1.0, 1.5, 2.0, 3.0, 4.0}:
                raise ValueError("Unsupported exact chemical bond order")
            seen.add(pair)
        return self


class ResonanceRequest(StrictModel):
    schema: Literal[SCHEMA]
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    operation: Literal["resonance_enumeration"]
    input: ResonanceInput


class TopologyRequest(StrictModel):
    schema: Literal[SCHEMA]
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    operation: Literal["topology_to_rdkit"]
    input: TopologyData


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Refused("Duplicate JSON object keys are forbidden")
        result[key] = value
    return result


def _parse(raw: bytes):
    def constant(_):
        raise Refused("Nonfinite JSON numbers are forbidden")

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise Refused("A single request object is required")
    kind = value.get("operation")
    model = {"resonance_enumeration": ResonanceRequest, "topology_to_rdkit": TopologyRequest}.get(kind)
    if model is None:
        raise Refused("Unsupported structural operation")
    # Validate the original JSON representation: strict tuple fields are JSON arrays.
    return model.model_validate_json(_json_bytes(value))


def _regular_path(path: Path) -> Path:
    path = path.absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise Refused("Symlinked paths are forbidden")
    if not stat.S_ISREG(path.stat().st_mode):
        raise Refused("The request must be a regular file")
    return path


def _read(path: Path) -> bytes:
    path = _regular_path(path)
    if path.stat().st_size > MAX_REQUEST_BYTES:
        raise Refused("Request exceeds the byte limit")
    with path.open("rb") as stream:
        raw = stream.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise Refused("Request exceeds the byte limit")
    return raw


def _installed_source() -> dict:
    dist = metadata.distribution("cochem-topos")
    direct = json.loads(dist.read_text("direct_url.json") or "{}")
    if direct.get("dir_info", {}).get("editable"):
        raise Refused("Structural execution requires an installed noneditable wheel")
    files = {str(member): member for member in dist.files or ()}
    sources = {}
    for name in SOURCE_NAMES:
        key = f"topos/structural/{name}"
        member = files.get(key)
        if member is None or member.hash is None or member.hash.mode != "sha256":
            raise Refused("The installed wheel does not record every structural source")
        path = _regular_path(Path(dist.locate_file(member)))
        if path != Path(__file__).parent / name:
            raise Refused("Imported structural source differs from the installed distribution")
        raw = path.read_bytes()
        encoded = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
        if encoded != member.hash.value or len(raw) != member.size:
            raise Refused("Installed structural source failed wheel RECORD verification")
        sources[key] = _digest(raw)
    record = dist.read_text("RECORD")
    if record is None:
        raise Refused("The installed wheel RECORD is missing")
    archive_hashes = direct.get("archive_info", {}).get("hashes", {})
    return {
        "distribution": "cochem-topos", "version": dist.version,
        "source_sha256": sources, "record_sha256": _digest(record.encode()),
        "wheel_archive_sha256": archive_hashes.get("sha256"),
        "integrity_scope": "wheel RECORD byte integrity; the caller must verify the approved source revision and wheel seal",
        "dependencies": {name: metadata.version(name) for name in (
            "CoChem-BASE", "rdkit", "mendeleev", "numpy", "networkx", "pydantic",
        )},
    }


def _molecule_result(molecule, masses=None):
    from rdkit import Chem

    return {
        "isomeric_smiles": Chem.MolToSmiles(molecule, isomericSmiles=True),
        "atoms": [{
            "index": atom.GetIdx(), "symbol": atom.GetSymbol(),
            "atomic_number": atom.GetAtomicNum(), "isotope": atom.GetIsotope(),
            "formal_charge": atom.GetFormalCharge(),
            **({"mass_u": masses[atom.GetIdx()]} if masses is not None else {}),
        } for atom in molecule.GetAtoms()],
        "bonds": [{"left": bond.GetBeginAtomIdx(), "right": bond.GetEndAtomIdx(),
                   "order": bond.GetBondTypeAsDouble()} for bond in molecule.GetBonds()],
    }


def _resonance(data: ResonanceInput):
    from rdkit import Chem

    from topos.structural.graph import TopologyGraph
    from topos.structural.resonance import ResonanceEnumerator

    molecule = Chem.MolFromSmiles(data.smiles)
    if molecule is None or not 1 <= molecule.GetNumAtoms() <= MAX_ATOMS:
        raise Refused("SMILES must define a valid molecule within the atom limit")
    graph = TopologyGraph()
    for atom in molecule.GetAtoms():
        isotope = atom.GetIsotope()
        symbol = f"{isotope}{atom.GetSymbol()}" if isotope else atom.GetSymbol()
        graph.add_chemical_node(
            atom.GetIdx(), symbol, formal_charge=atom.GetFormalCharge(),
            hybridization=str(atom.GetHybridization()).lower(), in_ring=atom.IsInRing(),
            isotope=isotope, radical_electrons=atom.GetNumRadicalElectrons(),
        )
    for bond in molecule.GetBonds():
        graph.add_chemical_edge(
            bond.GetBeginAtomIdx(), bond.GetEndAtomIdx(),
            bond_order=bond.GetBondTypeAsDouble(), aromatic=bond.GetIsAromatic(),
            in_ring=bond.IsInRing(),
        )
    result = ResonanceEnumerator.enumerate(graph, data.max_structures, data.temperature_k)
    return {
        "source_nuclei": _molecule_result(molecule),
        "ensemble_size": result.ensemble_size,
        "enumeration_truncated": result.enumeration_truncated,
        "excluded_ghost_nodes": result.excluded_ghost_nodes,
        "population_scope": result.population_scope,
        "weights": result.weights, "temperature_k": result.temperature_k,
        "structures": [{
            "bond_orders": [{"left": u, "right": v, "order": order}
                            for (u, v), order in sorted(form.bond_orders.items())],
            "formal_charges": [{"index": node, "charge": charge}
                               for node, charge in sorted(form.formal_charges.items())],
            "relative_energy_kcal": form.relative_energy_kcal,
            "boltzmann_weight": form.boltzmann_weight,
        } for form in result.structures],
    }


def _topology(data: TopologyData):
    from cochem_base.physics.nuclide_resolver import get_element, parse_nuclide

    from topos.structural.tautomer import TopologyInput, _build_rdkit_mol_from_topology

    for symbol, number in zip(data.elements, data.atomic_numbers, strict=True):
        parsed = parse_nuclide(symbol)
        if int(get_element(parsed.symbol).atomic_number) != number:
            raise Refused("Element and atomic number identities disagree")
    values = data.model_dump(exclude_none=True)
    top = TopologyInput(**values)
    molecule = _build_rdkit_mol_from_topology(top)
    return {"molecule_id": data.molecule_id, **_molecule_result(molecule, top.masses),
            "mass_convention": "BASE get_isotope_mass; unspecified isotope uses its recorded resolver policy"}


def execute(raw: bytes) -> dict:
    if len(raw) > MAX_REQUEST_BYTES:
        raise Refused("Request exceeds the byte limit")
    before = _installed_source()
    request = _parse(raw)
    result = _resonance(request.input) if isinstance(request, ResonanceRequest) else _topology(request.input)
    if before != _installed_source():
        raise Refused("Installed structural source changed during execution")
    return {
        "schema": SCHEMA, "request_id": request.request_id, "operation": request.operation,
        "status": "completed", "request_sha256": _digest(raw),
        "canonical_request_sha256": _digest(_json_bytes(request.model_dump())),
        "acceptance_scope": "structural_enumeration_only",
        "scientific_execution_performed": False, "provider": before, "result": result,
        "limits": {"max_request_bytes": MAX_REQUEST_BYTES, "max_atoms": MAX_ATOMS,
                   "max_structures": 10000, "wall_time_authority": "calling BASE process broker"},
    }


def _publish(path: Path, value: dict):
    path = path.absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise Refused("Symlinked output paths are forbidden")
    if not path.parent.is_dir():
        raise Refused("The output parent must already exist")
    fd, temporary = tempfile.mkstemp(prefix=".topos-structural-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Exclusive publication; never replace student evidence.
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise Refused("The output already exists")
        raw = _read(args.request)
        receipt = execute(raw)
        if raw != _read(args.request):
            raise Refused("Request changed during execution")
        _publish(args.output, receipt)
    except Exception as error:
        # Deliberately omit raw untrusted fields and private filesystem paths.
        reason = str(error) if isinstance(error, Refused) else "The structural request could not be validated or executed"
        print(json.dumps({"schema": SCHEMA, "status": "refused", "error_type": type(error).__name__, "reason": reason}), file=sys.stderr)
        return 2
    return 0
