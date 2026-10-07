"""Chemistry validation and conservative graph hypotheses using versioned data."""
from __future__ import annotations

from functools import lru_cache
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

import networkx as nx
import numpy as np

if TYPE_CHECKING:
    from .models import Molecule


@lru_cache(maxsize=118)
def _element(symbol: str) -> Any:
    try:
        from mendeleev import element
    except ImportError as exc:
        raise RuntimeError("Mendeleev is required for chemistry validation; install project dependencies") from exc
    try:
        item = element(symbol)
    except (ValueError, KeyError) as exc:
        raise ValueError("unknown chemical element symbol") from exc
    if item.symbol != symbol:
        raise ValueError("use canonical case-sensitive element symbols")
    return item


def atomic_number(symbol: str) -> int:
    return int(_element(symbol).atomic_number)


def covalent_radius(symbol: str) -> float:
    """Pyykko single-bond covalent radius, converted from pm to angstrom."""
    radius = _element(symbol).covalent_radius_pyykko
    if radius is None or radius <= 0:
        raise ValueError(f"covalent radius unavailable for {symbol}; explicit connectivity required")
    return float(radius) / 100.0


@lru_cache(maxsize=1024)
def isotope_mass(symbol: str, mass_number: int) -> float:
    isotope = next((i for i in _element(symbol).isotopes if i.mass_number == mass_number), None)
    if isotope is None or isotope.mass is None:
        raise ValueError(f"isotope mass unavailable for {symbol}-{mass_number}")
    return float(isotope.mass)


def atomic_data_provenance() -> dict[str, str]:
    return {
        "provider": "mendeleev", "version": version("mendeleev"),
        "radii": "Pyykko covalent_radius_pyykko, pm / 100 -> angstrom",
        "mass_unit": "u", "isotope_selection": "explicit mass number or recorded most-abundant isotope",
    }


def resolved_masses(molecule: Molecule, *, isotope_policy: str = "most_abundant") -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Resolve isotope masses, recording any explicit most-abundant assumption."""
    if isotope_policy not in {"most_abundant", "require_explicit"}:
        raise ValueError("unknown isotope policy")
    masses, records = [], []
    for symbol, number in zip(molecule.symbols, molecule.isotopes, strict=True):
        source = "explicit"
        if number is None:
            if isotope_policy == "require_explicit":
                raise ValueError("spectroscopy requires explicit isotope mass numbers under this policy")
            available = [i for i in _element(symbol).isotopes if i.abundance is not None and i.abundance > 0 and i.mass is not None]
            if not available:
                raise ValueError(f"no natural-abundance isotope for {symbol}; specify mass number")
            number = max(available, key=lambda i: i.abundance).mass_number
            source = "assumed-most-abundant"
        mass = isotope_mass(symbol, number)
        masses.append(mass)
        records.append({"symbol": symbol, "mass_number": number, "mass_u": mass, "selection": source})
    return np.asarray(masses, dtype=np.float64), records


def molecular_graph(molecule: Molecule, *, radius_scale: float = 1.2) -> nx.Graph:
    """Return explicit connectivity or a labelled, documented distance hypothesis."""
    if not np.isfinite(radius_scale) or radius_scale <= 0:
        raise ValueError("connectivity radius scale must be finite and positive")
    graph = nx.Graph()
    for i, (symbol, isotope) in enumerate(zip(molecule.symbols, molecule.isotopes, strict=True)):
        graph.add_node(i, symbol=symbol, isotope=isotope)
    if molecule.bonds:
        for bond in molecule.bonds:
            graph.add_edge(bond.atom1, bond.atom2, order=bond.order, kind=bond.kind)
        graph.graph["source"] = "explicit"
    else:
        coordinates = np.asarray(molecule.coordinates, dtype=np.float64)
        radii = np.asarray([covalent_radius(s) for s in molecule.symbols])
        for i in range(len(coordinates)):
            for j in range(i):
                distance = float(np.linalg.norm(coordinates[i] - coordinates[j]))
                if distance <= radius_scale * (radii[i] + radii[j]):
                    graph.add_edge(i, j, order=1.0, kind="inferred")
        graph.graph["source"] = f"distance-hypothesis/pyykko/scale-{radius_scale}"
    return graph


def validate_chemistry(molecule: Molecule) -> dict[str, Any]:
    """Reject coincident atoms, flag radius-relative clashes without chemical overclaim."""
    coordinates = np.asarray(molecule.coordinates, dtype=np.float64)
    issues = []
    for i in range(len(coordinates)):
        for j in range(i):
            distance = float(np.linalg.norm(coordinates[i] - coordinates[j]))
            if distance < 1e-8:
                raise ValueError(f"coincident atoms at indices {j} and {i}")
            try:
                contact_radius = covalent_radius(molecule.symbols[i]) + covalent_radius(molecule.symbols[j])
            except ValueError:
                issues.append(f"radius unavailable for contact {j}-{i}; manual geometry validation required")
                continue
            if distance < 0.35 * contact_radius:
                issues.append(f"unusually short contact {j}-{i} relative to covalent radii")
    return {
        "status": "physically-suspect" if issues else "valid", "issues": issues,
        "provenance": atomic_data_provenance(), "contact_policy": "coincidence-1e-8A/radius-warning-0.35-v1",
    }


def classify_fragments(molecule: Molecule) -> dict[str, Any]:
    graph = molecular_graph(molecule)
    fragments = [sorted(group) for group in nx.connected_components(graph)]
    issues = []
    coordination = any(b.kind == "coordination" for b in molecule.bonds)
    unknown = any(b.kind == "unknown" for b in molecule.bonds)
    transition_metal = any(_element(s).block in {"d", "f"} for s in molecule.symbols)
    if coordination:
        classification = "candidate-strong-complex"
    elif unknown or (transition_metal and len(molecule.symbols) > 1):
        classification = "unresolved"
        issues.append("coordination or metal connectivity needs a supported bonding rule or review")
    elif len(fragments) > 1:
        classification = "candidate-weak-complex"
    else:
        classification = "monomer"
    if molecule.fragments and sorted(map(sorted, molecule.fragments)) != sorted(fragments):
        issues.append("declared partition differs from connectivity; preserve input and review partition")
        classification = "unresolved"
    if classification == "candidate-weak-complex" and not molecule.fragment_states and molecule.charge != 0:
        issues.append("charged fragment states are unspecified; do not infer neutral monomers")
        classification = "unresolved"
    return {"classification": classification, "fragments": fragments, "graph_source": graph.graph["source"], "issues": issues}


def to_xyz(molecule: Molecule, comment: str = "TOPOS geometry; coordinates angstrom") -> str:
    if "\n" in comment or "\r" in comment:
        raise ValueError("XYZ comment must be a single line")
    lines = [str(len(molecule.symbols)), comment]
    lines.extend(f"{s} {p[0]:.14f} {p[1]:.14f} {p[2]:.14f}" for s, p in zip(molecule.symbols, molecule.coordinates, strict=True))
    return "\n".join(lines) + "\n"


def from_xyz(text: str, *, charge: int = 0, multiplicity: int = 1, template: Molecule | None = None) -> Molecule:
    """Parse exactly one XYZ frame; output files retain template state and atom order."""
    from .models import Molecule

    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError("XYZ requires count and comment lines")
    try:
        count = int(lines[0].strip())
    except ValueError as exc:
        raise ValueError("XYZ atom count is not an integer") from exc
    if count < 1 or len(lines) < count + 2 or any(line.strip() for line in lines[count + 2:]):
        raise ValueError("XYZ atom count does not match exactly one frame")
    symbols, coordinates = [], []
    for line in lines[2:count + 2]:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("XYZ rows must contain symbol and three coordinates")
        symbols.append(fields[0])
        try:
            coordinates.append([float(v) for v in fields[1:]])
        except ValueError as exc:
            raise ValueError("invalid XYZ coordinate") from exc
    if template is not None:
        if symbols != template.symbols:
            raise ValueError("engine output atom order/composition does not match input")
        return Molecule.model_validate({**template.model_dump(), "coordinates": coordinates})
    return Molecule(symbols=symbols, coordinates=coordinates, charge=charge, multiplicity=multiplicity)
