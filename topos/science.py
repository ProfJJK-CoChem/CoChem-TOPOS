"""Unit-aware numerical science and conservative molecular comparison.

Utilities never invent an electronic energy, frequency, or thermochemical
correction. Geometry-derived rotational constants are labelled equilibrium
rigid-rotor predictions, not measured ground-state constants.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from threading import Event
from typing import Any, Iterable

import networkx as nx
import numpy as np
import scipy
from scipy import constants
from scipy.special import logsumexp

from .chemistry import atomic_data_provenance, molecular_graph, resolved_masses
from .models import Candidate, Molecule

BOHR_ANGSTROM = constants.physical_constants["Bohr radius"][0] / constants.angstrom
HARTREE_EV = constants.physical_constants["Hartree energy in eV"][0]
HARTREE_J = constants.physical_constants["Hartree energy"][0]
HARTREE_KCAL_MOL = HARTREE_J * constants.Avogadro / (1000.0 * constants.calorie)
KB_HARTREE_K = constants.Boltzmann / HARTREE_J


def constants_provenance() -> dict[str, str]:
    # SciPy's own data is the source of truth; archive the resolved numerical
    # constants rather than inferring an edition from a moving upstream branch.
    from scipy.constants import _codata

    return {"provider": "scipy.constants", "version": scipy.__version__,
            "codata_edition": str(getattr(_codata, "_current_codata", "not-exposed-by-provider")),
            "bohr_angstrom": repr(BOHR_ANGSTROM), "hartree_ev": repr(HARTREE_EV),
            "hartree_j": repr(HARTREE_J)}


def geometry_digest(molecule: Molecule) -> str:
    """Exact geometry/state identity; deliberately not a conformer equivalence proof."""
    data = molecule.model_dump(mode="json")
    data.pop("name", None)
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def convert_ase_quantities(
    energy_ev: float | None = None,
    forces_ev_angstrom: Any = None,
    hessian_ev_angstrom2: Any = None,
    *, natoms: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"energy_hartree": None, "gradient_hartree_per_bohr": None,
                             "hessian_hartree_per_bohr2": None, "constants": constants_provenance()}
    if energy_ev is not None:
        if not np.isfinite(energy_ev):
            raise ValueError("nonfinite electronic energy")
        result["energy_hartree"] = float(energy_ev) / HARTREE_EV
    if forces_ev_angstrom is not None:
        forces = np.asarray(forces_ev_angstrom, dtype=np.float64)
        if forces.ndim != 2 or forces.shape[1] != 3 or (natoms is not None and len(forces) != natoms) or not np.isfinite(forces).all():
            raise ValueError("forces must be a finite N by 3 array")
        result["gradient_hartree_per_bohr"] = (-forces * BOHR_ANGSTROM / HARTREE_EV).tolist()
    if hessian_ev_angstrom2 is not None:
        hessian = np.asarray(hessian_ev_angstrom2, dtype=np.float64)
        if hessian.ndim != 2 or hessian.shape[0] != hessian.shape[1] or hessian.shape[0] % 3 or (natoms is not None and hessian.shape != (3 * natoms, 3 * natoms)):
            raise ValueError("Cartesian Hessian must have shape 3N by 3N")
        if not np.isfinite(hessian).all() or not np.allclose(hessian, hessian.T, rtol=1e-8, atol=1e-10):
            raise ValueError("Hessian must be finite and symmetric within declared tolerance")
        result["hessian_hartree_per_bohr2"] = (hessian * BOHR_ANGSTROM ** 2 / HARTREE_EV).tolist()
    return result


def validate_derivatives(gradient: Any = None, hessian: Any = None, *, natoms: int) -> None:
    if gradient is not None:
        values = np.asarray(gradient, dtype=np.float64)
        if values.shape != (natoms, 3) or not np.isfinite(values).all():
            raise ValueError("gradient must be finite N by 3, including physical zero values")
    if hessian is not None:
        values = np.asarray(hessian, dtype=np.float64)
        if values.shape != (3 * natoms, 3 * natoms) or not np.isfinite(values).all():
            raise ValueError("Hessian must be finite 3N by 3N")
        if not np.allclose(values, values.T, rtol=1e-8, atol=1e-10):
            raise ValueError("Cartesian Hessian is not symmetric")


def _state_signature(molecule: Molecule, *, include_stereo: bool = True) -> tuple[Any, ...]:
    atoms = tuple(sorted(Counter(zip(molecule.symbols, molecule.isotopes, strict=True)).items(), key=repr))
    fragment_states = {frozenset(state.atom_indices): (state.charge, state.multiplicity)
                       for state in molecule.fragment_states}
    fragments = []
    for group in molecule.fragments:
        composition = tuple(sorted(Counter((molecule.symbols[i], molecule.isotopes[i])
                                           for i in group).items(), key=repr))
        fragments.append((composition, fragment_states.get(frozenset(group))))
    return (atoms, molecule.charge, molecule.multiplicity,
            json.dumps(molecule.environment, sort_keys=True),
            tuple(sorted(fragments, key=repr)),
            json.dumps(molecule.stereochemistry, sort_keys=True) if include_stereo else None)


def energy_comparison_key(candidate: Candidate) -> str | None:
    """Partition comparable electronic energies, without asserting geometry identity.

    Stereoisomers may share a thermodynamic comparison scale. Isotopes,
    fragment states, environment, total state and the complete protocol must
    still agree. Unknown protocols and missing energies never form a group.
    """
    if (not candidate.comparison_protocol or not candidate.comparison_protocol.strip()
            or candidate.energy_hartree is None or not np.isfinite(candidate.energy_hartree)):
        return None
    data = (candidate.comparison_protocol, _state_signature(candidate.molecule, include_stereo=False))
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _proper_rmsd(a: np.ndarray, b: np.ndarray) -> float:
    ac, bc = a - a.mean(axis=0), b - b.mean(axis=0)
    u, _, vt = np.linalg.svd(bc.T @ ac)
    correction = np.eye(3)
    correction[-1, -1] = np.linalg.det(u @ vt)
    rotation = u @ correction @ vt
    return float(np.sqrt(np.mean(np.sum((bc @ rotation - ac) ** 2, axis=1))))


def _opposite_orientation(a: np.ndarray, b: np.ndarray) -> bool:
    """Retain reflection-related structures even when an RMSD cutoff is loose.

    A deterministic, well-spread tetrahedron preserves orientation under proper
    rotation. Ambiguous nearly planar cases do not supply a chirality assertion;
    explicit input stereochemistry and proper RMSD remain additional gates.
    """
    if len(a) < 4:
        return False
    i = int(np.argmax(np.linalg.norm(a - a.mean(axis=0), axis=1)))
    j = int(np.argmax(np.linalg.norm(a - a[i], axis=1)))
    cross = np.cross(a[j] - a[i], a - a[i])
    k = int(np.argmax(np.linalg.norm(cross, axis=1)))
    normal = np.cross(a[j] - a[i], a[k] - a[i])
    fourth = int(np.argmax(np.abs((a - a[i]) @ normal)))
    selected = [i, j, k, fourth]
    determinants = []
    for coords in (a, b):
        xyz = coords[selected]
        vectors = xyz[1:] - xyz[0]
        scale = float(np.prod(np.linalg.norm(vectors, axis=1)))
        determinants.append(float(np.linalg.det(vectors)) / scale if scale else 0.0)
    return abs(determinants[0]) > 1e-3 and abs(determinants[1]) > 1e-3 and determinants[0] * determinants[1] < 0


def _normalized_tetrahedron(points: np.ndarray) -> float:
    vectors = points[:3] - points[3]
    scale = float(np.prod(np.linalg.norm(vectors, axis=1)))
    return float(np.linalg.det(vectors)) / scale if scale else 0.0


def _chemical_neighborhood_labels(graph: nx.Graph) -> dict[int, list[str]]:
    for index in graph:
        node = graph.nodes[index]
        node["chemical_label"] = f"{node['symbol']}:{node['isotope']}"
    return nx.weisfeiler_lehman_subgraph_hashes(
        graph, node_attr="chemical_label", edge_attr="order", iterations=max(3, min(len(graph), 10)),
    )


class _ComparisonBudgetExhausted(Exception):
    pass


def _check_comparison_budget(deadline: float | None, cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise _ComparisonBudgetExhausted("comparison cancelled; retain both")
    if deadline is not None and time.monotonic() >= deadline:
        raise _ComparisonBudgetExhausted("comparison deadline exhausted; retain both")


class _BoundedGraphMatcher(nx.algorithms.isomorphism.GraphMatcher):
    """Bound VF2 partial search states as well as completed isomorphisms."""

    def __init__(self, *args: Any, max_search_nodes: int, deadline: float | None,
                 cancel_event: Event | None, **kwargs: Any) -> None:
        self.search_nodes = 0
        self.max_search_nodes = max_search_nodes
        self.deadline = deadline
        self.cancel_event = cancel_event
        super().__init__(*args, **kwargs)

    def syntactic_feasibility(self, first: int, second: int) -> bool:
        _check_comparison_budget(self.deadline, self.cancel_event)
        if self.search_nodes >= self.max_search_nodes:
            raise _ComparisonBudgetExhausted("graph search node budget exhausted; retain both")
        self.search_nodes += 1
        return super().syntactic_feasibility(first, second)

    def semantic_feasibility(self, first: int, second: int) -> bool:
        if not super().semantic_feasibility(first, second):
            return False
        # Whole identical fragments may permute. Atoms from one declared
        # fragment must never be split across several candidate fragments.
        return all((self.G1.nodes[first]["fragment"] == self.G1.nodes[left]["fragment"]) ==
                   (self.G2.nodes[second]["fragment"] == self.G2.nodes[right]["fragment"])
                   for left, right in self.core_1.items())


def _label_fragments(graph: nx.Graph, molecule: Molecule) -> None:
    states = {frozenset(s.atom_indices): (s.charge, s.multiplicity) for s in molecule.fragment_states}
    for node in graph:
        graph.nodes[node].update(fragment=None, fragment_state=None)
    for number, group in enumerate(molecule.fragments):
        for node in group:
            graph.nodes[node].update(fragment=number, fragment_state=states.get(frozenset(group)))


def _mapped_stereo(molecule: Molecule, mapping: dict[int, int]) -> set[tuple[Any, ...]]:
    """Canonical signed declarations under a particular chemical atom mapping.

    Declarations have already been validated by the coordinate-based stereo
    validator. Atom ID spelling and neighbor-list order are not chemistry.
    """
    ids = {atom_id: mapping[i] for i, atom_id in enumerate(molecule.atom_ids)}
    result = set()
    for center in molecule.stereochemistry.get("tetrahedral_centers", []):
        neighbors = [ids[atom_id] for atom_id in center["ordered_neighbor_ids"]]
        inversions = sum(left > right for i, left in enumerate(neighbors) for right in neighbors[i + 1:])
        sign = center["orientation"] * (-1 if inversions % 2 else 1)
        result.add((ids[center["center_atom_id"]], tuple(sorted(neighbors)), sign))
    return result


def _double_bond_groups(graph: nx.Graph, labels: dict[int, list[str]]) -> list[list[int]]:
    """Explicit alkenelike double bonds with two distinguishable groups per end.

    This is a coordinate same-side/opposite-side guard, not a CIP assignment.
    Inferred distance graphs do not contain bond orders and cannot certify it.
    """
    groups = []
    for first, second, edge in graph.edges(data=True):
        if edge["order"] != 2 or edge["kind"] != "covalent":
            continue
        left = sorted(set(graph.neighbors(first)) - {second})
        right = sorted(set(graph.neighbors(second)) - {first})
        if (len(left) == len(right) == 2 and labels[left[0]][-1] != labels[left[1]][-1]
                and labels[right[0]][-1] != labels[right[1]][-1]):
            groups.append([first, second, left[0], right[0]])
    return groups


def _double_bond_cosine(coordinates: np.ndarray, group: list[int]) -> float:
    first, second, left, right = coordinates[group]
    axis = second - first
    length = float(np.linalg.norm(axis))
    if length <= 1e-12:
        return 0.0
    axis = axis / length
    first_group, second_group = left - first, right - second
    first_group -= np.dot(first_group, axis) * axis
    second_group -= np.dot(second_group, axis) * axis
    scale = float(np.linalg.norm(first_group) * np.linalg.norm(second_group))
    return float(np.dot(first_group, second_group)) / scale if scale > 1e-12 else 0.0


def compare_molecules(a: Molecule, b: Molecule, *, rmsd_threshold: float = 0.125,
                      max_permutations: int = 10000, max_search_nodes: int = 100000,
                      deadline: float | None = None, cancel_event: Event | None = None) -> dict[str, Any]:
    """Conservative graph/permutation/proper-rotation identity comparison.

    A qualifying mapping proves equivalence under the stated tolerance, not
    that the coordinates represent the same potential-energy minimum. If a
    completed-mapping or partial-search budget prevents finding such a mapping,
    retain both as unresolved. ``deadline`` is an absolute monotonic-clock time.
    RMSD covers all atoms equally and never includes a reflection. Graph hashes
    only identify distinguishable substituents, never molecular identity.
    """
    if (not np.isfinite(rmsd_threshold) or rmsd_threshold <= 0
            or any(not isinstance(limit, int) or isinstance(limit, bool) or limit < 1
                   for limit in (max_permutations, max_search_nodes))
            or (deadline is not None and not np.isfinite(deadline))):
        raise ValueError("comparison limits must be positive")
    base = {"equivalent": False, "rmsd_angstrom": None, "atom_mapping": None,
            "atom_selection": "all", "weighting": "uniform", "proper_rotations_only": True,
            "rmsd_threshold_angstrom": rmsd_threshold, "max_permutations": max_permutations,
            "max_search_nodes": max_search_nodes,
            "stereochemistry_scope": "signed-tetrahedral/explicit-double-bond-relative-orientation/proper-rotation",
            "permutations": 0, "search_nodes": 0, "permutation_search_complete": False}
    try:
        _check_comparison_budget(deadline, cancel_event)
    except _ComparisonBudgetExhausted as exc:
        return {**base, "status": "unresolved", "reason": str(exc)}
    if _state_signature(a, include_stereo=False) != _state_signature(b, include_stereo=False):
        return {**base, "status": "different-state", "reason": "composition, isotopes, total or fragment state, partition or environment differ"}
    for molecule in (a, b):
        stereo = validate_stereochemical_preservation(molecule, molecule)
        if stereo["status"] != "preserved":
            return {**base, "status": "unresolved", "reason": "ambiguous, invalid or unsupported stereochemistry; retain both",
                    "stereochemistry_validation": stereo}
    ga, gb = molecular_graph(a), molecular_graph(b)
    if any(edge["kind"] == "unknown" for graph in (ga, gb) for _, _, edge in graph.edges(data=True)):
        return {**base, "status": "unresolved", "reason": "unknown bond identity requires review; retain both"}
    _label_fragments(ga, a)
    _label_fragments(gb, b)
    base["connectivity_sources"] = [ga.graph["source"], gb.graph["source"]]
    labels = _chemical_neighborhood_labels(ga)
    tetrahedral_neighbors = [list(ga.neighbors(i)) for i in ga if ga.degree(i) == 4 and
                             len({labels[j][-1] for j in ga.neighbors(i)}) == 4]
    double_bond_groups = _double_bond_groups(ga, labels)
    matcher = _BoundedGraphMatcher(
        ga, gb, max_search_nodes=max_search_nodes, deadline=deadline, cancel_event=cancel_event,
        node_match=lambda x, y: (x["symbol"], x["isotope"], x["fragment_state"]) ==
                               (y["symbol"], y["isotope"], y["fragment_state"]),
        edge_match=lambda x, y: x["order"] == y["order"] and
        ("covalent" if x["kind"] == "inferred" else x["kind"]) ==
        ("covalent" if y["kind"] == "inferred" else y["kind"]),
    )
    xyz_a, xyz_b = np.asarray(a.coordinates), np.asarray(b.coordinates)
    best, best_mapping, count, orientation_conflict = float("inf"), None, 0, False
    ambiguous_double_bond = False
    accepted: dict[str, Any] | None = None
    stereo_a = _mapped_stereo(a, dict(enumerate(range(len(a.symbols)))))
    try:
        for mapping in matcher.isomorphisms_iter():
            _check_comparison_budget(deadline, cancel_event)
            if count >= max_permutations:
                raise _ComparisonBudgetExhausted("atom permutation budget exhausted; retain both")
            count += 1
            if stereo_a != _mapped_stereo(b, {right: left for left, right in mapping.items()}):
                continue
            order = [mapping[i] for i in range(len(a.symbols))]
            xyz = xyz_b[order]
            rmsd = _proper_rmsd(xyz_a, xyz)
            if rmsd < best:
                best, best_mapping = rmsd, order
            local_inversion = any(
                abs(first) > 1e-3 and abs(second) > 1e-3 and first * second < 0
                for first, second in ((_normalized_tetrahedron(xyz_a[neighbors]),
                                      _normalized_tetrahedron(xyz[neighbors]))
                                     for neighbors in tetrahedral_neighbors)
            )
            double_bond_values = [(_double_bond_cosine(xyz_a, group), _double_bond_cosine(xyz, group))
                                  for group in double_bond_groups]
            ambiguous = any(abs(first) <= 1e-3 or abs(second) <= 1e-3 for first, second in double_bond_values)
            changed_double_bond = any(abs(first) > 1e-3 and abs(second) > 1e-3 and first * second < 0
                                      for first, second in double_bond_values)
            ambiguous_double_bond |= ambiguous and rmsd <= rmsd_threshold
            reflected = _opposite_orientation(xyz_a, xyz) or local_inversion or changed_double_bond
            orientation_conflict |= reflected
            if rmsd <= rmsd_threshold and not reflected and not ambiguous and (accepted is None or rmsd < accepted["rmsd_angstrom"]):
                accepted = {**base, "equivalent": True, "rmsd_angstrom": rmsd, "atom_mapping": order,
                            "status": "equivalent", "reason": "labelled graph and proper-rotation all-atom RMSD agree",
                            "permutations": count, "search_nodes": matcher.search_nodes,
                            "search_termination": "qualifying-mapping", "rmsd_is_global_minimum": False}
                if rmsd <= 1e-12:
                    return accepted
    except _ComparisonBudgetExhausted as exc:
        if accepted is not None:
            return {**accepted, "permutations": count, "search_nodes": matcher.search_nodes,
                    "search_termination": "budget-after-qualifying-mapping"}
        return {**base, "status": "unresolved", "reason": str(exc),
                "rmsd_angstrom": best if np.isfinite(best) else None, "permutations": count,
                "search_nodes": matcher.search_nodes}
    finally:
        matcher.reset_recursion_limit()
    if accepted is not None:
        return {**accepted, "permutations": count, "search_nodes": matcher.search_nodes,
                "search_termination": "exhaustive", "permutation_search_complete": True,
                "rmsd_is_global_minimum": True}
    if ambiguous_double_bond:
        return {**base, "status": "unresolved", "reason": "double-bond orientation is ambiguous; retain both",
                "rmsd_angstrom": best if np.isfinite(best) else None, "atom_mapping": best_mapping,
                "permutations": count, "search_nodes": matcher.search_nodes,
                "permutation_search_complete": True}
    return {**base, "rmsd_angstrom": best if np.isfinite(best) else None, "atom_mapping": best_mapping,
            "status": "distinct", "reason": "orientation differs" if orientation_conflict else "no qualifying graph/RMSD mapping",
            "permutations": count, "search_nodes": matcher.search_nodes,
            "permutation_search_complete": True, "rmsd_is_global_minimum": True}


def validate_stereochemical_preservation(reference: Molecule, candidate: Molecule, *,
                                       normalized_volume_tolerance: float = 1e-3) -> dict[str, Any]:
    """Check mapped tetrahedral orientations independently of copied labels.

    Supported declaration::

        {"tetrahedral_centers": [{"center_atom_id": "atom-0",
          "ordered_neighbor_ids": ["atom-1", "atom-2", "atom-3", "atom-4"],
          "orientation": 1}]}

    ``orientation`` means the signed determinant of neighbor 1/2/3 relative to
    neighbor 4. It is NOT CIP R/S. Opaque labels and unsupported stereo types
    require review. Undeclared tetrahedral centers are screened only when four
    rooted chemical neighborhood labels are distinguishable; this utility does
    not certify double-bond, axial, helical or metal-complex stereochemistry.
    """
    result: dict[str, Any] = {
        "status": "preserved", "centers": [], "issues": [],
        "scope": "atom-mapped-distinguishable-tetrahedral-orientation-v1",
        "not_certified": ["CIP-R/S", "E/Z", "axial", "helical", "coordination stereochemistry"],
        "normalized_volume_tolerance": normalized_volume_tolerance,
    }
    if not np.isfinite(normalized_volume_tolerance) or normalized_volume_tolerance <= 0:
        raise ValueError("orientation tolerance must be finite and positive")
    if set(reference.atom_ids) != set(candidate.atom_ids):
        return {**result, "status": "unsupported", "issues": ["atom mapping changed or is missing"]}
    ids_ref = {value: i for i, value in enumerate(reference.atom_ids)}
    ids_out = {value: i for i, value in enumerate(candidate.atom_ids)}
    for atom_id in ids_ref:
        i, j = ids_ref[atom_id], ids_out[atom_id]
        if (reference.symbols[i], reference.isotopes[i]) != (candidate.symbols[j], candidate.isotopes[j]):
            return {**result, "status": "unsupported", "issues": ["mapped atom chemistry changed"]}
    declarations = reference.stereochemistry
    if set(declarations) - {"tetrahedral_centers"} or candidate.stereochemistry != declarations:
        return {**result, "status": "unsupported", "issues": ["opaque or changed stereo labels require a validated interpreter; only signed tetrahedral declarations are supported"]}
    declared = declarations.get("tetrahedral_centers", [])
    if not isinstance(declared, list):
        return {**result, "status": "invalid-input", "issues": ["tetrahedral_centers must be a list"]}
    graph = molecular_graph(reference)
    labels = _chemical_neighborhood_labels(graph)
    centers: dict[str, tuple[list[str], int | None]] = {}
    for spec in declared:
        if not isinstance(spec, dict) or set(spec) != {"center_atom_id", "ordered_neighbor_ids", "orientation"}:
            return {**result, "status": "invalid-input", "issues": ["invalid signed tetrahedral declaration fields"]}
        center, neighbors, orientation = spec["center_atom_id"], spec["ordered_neighbor_ids"], spec["orientation"]
        if not isinstance(center, str) or center not in ids_ref or not isinstance(neighbors, list) or len(neighbors) != 4 or any(not isinstance(x, str) or x not in ids_ref for x in neighbors) or len(set(neighbors)) != 4 or not isinstance(orientation, int) or isinstance(orientation, bool) or orientation not in {-1, 1}:
            return {**result, "status": "invalid-input", "issues": ["signed tetrahedral declarations require a mapped center, four distinct mapped neighbors and orientation +/-1"]}
        if center in centers:
            return {**result, "status": "invalid-input", "issues": ["duplicate tetrahedral center declaration"]}
        index = ids_ref[center]
        if set(ids_ref[x] for x in neighbors) != set(graph.neighbors(index)):
            return {**result, "status": "invalid-input", "issues": ["declared neighbors do not match center connectivity"]}
        if len({labels[ids_ref[x]][-1] for x in neighbors}) != 4:
            return {**result, "status": "unsupported", "issues": ["center substituents are not distinguishable by the supported graph rule"]}
        centers[center] = (neighbors, orientation)
    for index in graph:
        neighbors = list(graph.neighbors(index))
        if len(neighbors) == 4 and len({labels[i][-1] for i in neighbors}) == 4:
            center = reference.atom_ids[index]
            centers.setdefault(center, (sorted(reference.atom_ids[i] for i in neighbors), None))

    def volume(molecule: Molecule, lookup: dict[str, int], neighbors: list[str]) -> float:
        points = np.asarray([molecule.coordinates[lookup[x]] for x in neighbors])
        return _normalized_tetrahedron(points)

    priorities = {"preserved": 0, "ambiguous": 1, "inverted": 2, "invalid-input": 3}
    for center, (neighbors, expected) in centers.items():
        initial, final = volume(reference, ids_ref, neighbors), volume(candidate, ids_out, neighbors)
        state = "preserved"
        if abs(initial) > normalized_volume_tolerance and expected is not None and int(np.sign(initial)) != expected:
            state = "invalid-input"
        elif abs(initial) <= normalized_volume_tolerance or abs(final) <= normalized_volume_tolerance:
            state = "ambiguous"
        elif initial * final < 0:
            state = "inverted"
        result["centers"].append({"center_atom_id": center, "ordered_neighbor_ids": neighbors,
                                  "initial_volume": initial, "final_volume": final, "status": state})
        if priorities[state] > priorities[result["status"]]:
            result["status"] = state
    if result["status"] != "preserved":
        result["issues"].append("tetrahedral orientation requires rejection or human review; copied labels are not evidence")
    return result


def rotational_constants(molecule: Molecule, *, isotope_policy: str = "most_abundant") -> dict[str, Any]:
    masses, isotope_records = resolved_masses(molecule, isotope_policy=isotope_policy)
    xyz = np.asarray(molecule.coordinates, dtype=np.float64)
    xyz -= np.average(xyz, axis=0, weights=masses)
    tensor = sum(m * (np.dot(r, r) * np.eye(3) - np.outer(r, r)) for m, r in zip(masses, xyz, strict=True))
    moments = np.linalg.eigvalsh(tensor)
    scale = max(float(np.max(np.abs(moments))), 1.0)
    if float(moments.min()) < -1e-12 * scale:
        raise ValueError("inertia tensor has an unphysical negative eigenvalue")
    moments = np.maximum(moments, 0.0)
    values = []
    for moment in moments:
        values.append(None if moment <= 1e-12 * scale else float(constants.h / (8 * np.pi ** 2 * moment * constants.atomic_mass * constants.angstrom ** 2) / 1e9))
    return {"moments_amu_angstrom2": moments.tolist(), "constants_ghz": values,
            "observable": "equilibrium-rigid-rotor", "not_measured_B0": True,
            "geometry_class": "monatomic" if len(masses) == 1 else ("linear" if values[0] is None else "nonlinear"),
            "isotope_provenance": isotope_records, "atomic_data": atomic_data_provenance(),
            "constants": constants_provenance()}


def compare_candidates(a: Candidate, b: Candidate, *, rmsd_threshold: float = 0.125,
                       energy_threshold_kcal_mol: float = 0.05,
                       rotational_threshold_fraction: float = 0.01,
                       max_permutations: int = 10000, max_search_nodes: int = 100000,
                       deadline: float | None = None, cancel_event: Event | None = None) -> dict[str, Any]:
    """Generation-level AND screen: common energy, inertia and chemical geometry.

    This TOPOS screen uses a fixed, explicitly recorded rotational tolerance.
    It does not emulate CREGEN's anisotropy-dependent 1–2.5% adjustment, nor
    claim reporting-level spectroscopic equivalence. Rotations are proper,
    all atoms contribute uniformly to RMSD, and enantiomers remain separate.
    """
    if any(not np.isfinite(value) or value <= 0 for value in
           (rmsd_threshold, energy_threshold_kcal_mol, rotational_threshold_fraction)):
        raise ValueError("deduplication thresholds must be finite and positive")
    if deadline is not None and not np.isfinite(deadline):
        raise ValueError("comparison deadline must be finite")
    if any(not isinstance(limit, int) or isinstance(limit, bool) or limit < 1
           for limit in (max_permutations, max_search_nodes)):
        raise ValueError("comparison search budgets must be positive integers")
    result: dict[str, Any] = {
        "equivalent": False, "status": "unresolved", "reason": "comparison not completed",
        "policy": "topos-generation-and-screen-v1", "stage": "generation-level",
        "combination": "AND", "comparison_protocol": a.comparison_protocol,
        "energy_threshold_kcal_mol": energy_threshold_kcal_mol,
        "rotational_threshold_fraction": rotational_threshold_fraction,
        "rotational_policy": "fixed-symmetric-fraction-abs(A-B)/max(A,B)",
        "rmsd_threshold_angstrom": rmsd_threshold,
        "atom_selection": "all", "weighting": "uniform", "proper_rotations_only": True,
        "criteria": {"comparable_energy": None, "energy": None, "rotation": None, "geometry": None},
    }
    try:
        _check_comparison_budget(deadline, cancel_event)
        first_key, second_key = energy_comparison_key(a), energy_comparison_key(b)
        if first_key is None or second_key is None or first_key != second_key:
            result["criteria"]["comparable_energy"] = False
            return {**result, "status": "incomparable", "reason": "valid energies on one explicit protocol and molecular/fragment state are required"}
        result["criteria"]["comparable_energy"] = True
        energy_difference = abs(a.energy_hartree - b.energy_hartree) * HARTREE_KCAL_MOL
        result["energy_difference_kcal_mol"] = energy_difference
        result["criteria"]["energy"] = energy_difference <= energy_threshold_kcal_mol
        if not result["criteria"]["energy"]:
            return {**result, "status": "distinct", "reason": "electronic energy difference exceeds generation-level tolerance"}
        first_rotation, second_rotation = rotational_constants(a.molecule), rotational_constants(b.molecule)
        result["rotational_constants"] = [first_rotation, second_rotation]
        _check_comparison_budget(deadline, cancel_event)
        if first_rotation["geometry_class"] != second_rotation["geometry_class"]:
            result["criteria"]["rotation"] = False
            return {**result, "status": "distinct", "reason": "linear/nonlinear/monatomic inertia classification differs"}
        differences: list[float | None] = []
        for first, second in zip(first_rotation["constants_ghz"], second_rotation["constants_ghz"], strict=True):
            if first is None and second is None:
                differences.append(None)
            elif first is None or second is None:
                result["criteria"]["rotation"] = False
                return {**result, "status": "distinct", "reason": "defined rotational axes differ"}
            else:
                differences.append(abs(first - second) / max(first, second))
        result["rotational_fractional_differences"] = differences
        result["undefined_rotation_policy"] = "skip matching zero-inertia axes; all axes skipped for one atom"
        result["criteria"]["rotation"] = all(value is None or value <= rotational_threshold_fraction for value in differences)
        if not result["criteria"]["rotation"]:
            return {**result, "status": "distinct", "reason": "rotational-constant difference exceeds generation-level tolerance"}
        geometry = compare_molecules(a.molecule, b.molecule, rmsd_threshold=rmsd_threshold,
                                     max_permutations=max_permutations, max_search_nodes=max_search_nodes,
                                     deadline=deadline, cancel_event=cancel_event)
        result["geometry_comparison"] = geometry
        result["criteria"]["geometry"] = geometry["equivalent"]
        result["rmsd_angstrom"] = geometry["rmsd_angstrom"]
        result["atom_mapping"] = geometry["atom_mapping"]
        return {**result, "equivalent": geometry["equivalent"], "status": geometry["status"],
                "reason": "common-level energy AND rotational constants AND proper-rotation geometry agree"
                if geometry["equivalent"] else geometry["reason"]}
    except _ComparisonBudgetExhausted as exc:
        return {**result, "reason": str(exc)}
    except ValueError as exc:
        return {**result, "reason": f"scientific comparison unavailable; retain both: {exc}"}


def ensemble_populations(candidates: Iterable[Candidate], *, temperature_k: float = 298.15,
                         quantity: str = "electronic") -> dict[str, Any]:
    candidates = list(candidates)
    if not candidates or not np.isfinite(temperature_k) or temperature_k <= 0:
        raise ValueError("a nonempty ensemble and finite positive temperature are required")
    if quantity not in {"electronic", "gibbs"}:
        raise ValueError("quantity must be electronic or gibbs")
    if len({c.candidate_id for c in candidates}) != len(candidates):
        raise ValueError("duplicate candidate identity must not multiply ensemble weights")
    protocols = {c.comparison_protocol for c in candidates}
    if len(protocols) != 1 or None in protocols or "" in protocols:
        raise ValueError("ensemble requires one explicit common comparison protocol")
    signatures = {_state_signature(c.molecule, include_stereo=False) for c in candidates}
    if len(signatures) != 1:
        raise ValueError("incompatible composition, charge, spin or environment in ensemble")
    field = "energy_hartree" if quantity == "electronic" else "gibbs_hartree"
    energies = [getattr(c, field) for c in candidates]
    if any(e is None or not np.isfinite(e) for e in energies):
        raise ValueError(f"all ensemble members require valid {field}")
    energy = np.asarray(energies, dtype=np.float64)
    degeneracy = np.asarray([c.degeneracy for c in candidates])
    if not np.isfinite(degeneracy).all() or (degeneracy <= 0).any():
        raise ValueError("degeneracies must be finite and positive")
    thermal_energy = KB_HARTREE_K * temperature_k
    minimum = float(energy.min())
    log_weights = np.log(degeneracy) - (energy - minimum) / thermal_energy
    partition = float(logsumexp(log_weights))
    populations = np.exp(log_weights - partition)
    return {"populations": {c.candidate_id: float(p) for c, p in zip(candidates, populations, strict=True)},
            "ensemble_energy_hartree": minimum - thermal_energy * partition,
            "weight_kind": "electronic-energy-weights-not-Gibbs-populations" if quantity == "electronic" else "Gibbs-populations",
            "comparison_protocol": next(iter(protocols)), "temperature_k": temperature_k,
            "degeneracy_convention": "explicit-not-already-in-member-energy",
            "completeness": "not-certified", "constants": constants_provenance()}


def counterpoise_interaction(energy_ab_ab: float, energy_a_ab: float, energy_b_ab: float,
                            energy_a_a: float, energy_b_b: float) -> dict[str, float]:
    values = [energy_ab_ab, energy_a_ab, energy_b_ab, energy_a_a, energy_b_b]
    if not np.isfinite(values).all():
        raise ValueError("counterpoise inputs must be finite energies from compatible fragment states")
    raw = energy_ab_ab - energy_a_a - energy_b_b
    corrected = energy_ab_ab - energy_a_ab - energy_b_ab
    return {"raw_interaction_hartree": raw, "cp_interaction_hartree": corrected,
            "additive_cp_correction_hartree": corrected - raw}


def harmonic_analysis(molecule: Molecule, hessian_hartree_per_bohr2: Any, *,
                      gradient_hartree_per_bohr: Any = None,
                      gradient_threshold: float = 1e-5,
                      imaginary_tolerance_cm1: float = 10.0,
                      constraints: dict[str, Any] | None = None) -> dict[str, Any]:
    """Project rigid translation/rotation and analyze a supplied physical Hessian.

    This utility cannot turn an optimization/preconditioning Hessian into a
    physical derivative. The caller must retain the actual Hessian provenance.
    General internal constraints require a separately derived projection and
    are deliberately rejected here rather than ignored.
    """
    from scipy.linalg import null_space

    if constraints:
        raise ValueError("general constrained thermochemistry is unsupported; supply a validated dedicated thermal model")
    if not np.isfinite([gradient_threshold, imaginary_tolerance_cm1]).all() or gradient_threshold <= 0 or imaginary_tolerance_cm1 < 0:
        raise ValueError("frequency/gradient thresholds must be nonnegative, gradient strictly positive")
    n = len(molecule.symbols)
    validate_derivatives(gradient_hartree_per_bohr, hessian_hartree_per_bohr2, natoms=n)
    masses, isotope_records = resolved_masses(molecule)
    xyz = np.asarray(molecule.coordinates, dtype=np.float64)
    xyz -= np.average(xyz, axis=0, weights=masses)
    root_mass = np.sqrt(masses)
    rigid_columns = []
    for axis in np.eye(3):
        rigid_columns.append((root_mass[:, None] * axis).ravel())
        rotation = (root_mass[:, None] * np.cross(axis, xyz)).ravel()
        if np.linalg.norm(rotation) > 1e-12:
            rigid_columns.append(rotation)
    # Orthonormalizing each column before rank detection removes arbitrary
    # relative length scales between translations and rotations.
    rigid = np.column_stack([v / np.linalg.norm(v) for v in rigid_columns])
    basis = null_space(rigid.T, rcond=1e-10)
    hessian = np.asarray(hessian_hartree_per_bohr2, dtype=np.float64)
    atomic_mass_kg = masses * constants.atomic_mass
    mass_vector = np.repeat(atomic_mass_kg, 3)
    weighted = hessian * HARTREE_J / (BOHR_ANGSTROM * constants.angstrom) ** 2
    weighted /= np.sqrt(np.outer(mass_vector, mass_vector))
    eigenvalues = np.linalg.eigvalsh(basis.T @ weighted @ basis)
    signed_cm1 = np.sign(eigenvalues) * np.sqrt(np.abs(eigenvalues)) / (2 * np.pi * constants.c * 100)
    unstable = bool(np.any(signed_cm1 < -imaginary_tolerance_cm1))
    stationary = None if gradient_hartree_per_bohr is None else bool(np.max(np.abs(gradient_hartree_per_bohr)) <= gradient_threshold)
    if stationary is False:
        validity = "nonstationary"
    elif unstable:
        validity = "unstable-modes"
    elif stationary is None:
        validity = "stationarity-not-evaluated"
    else:
        validity = "harmonic-minimum-within-thresholds"
    zpe = None if unstable or stationary is not True else float(
        0.5 * constants.h * constants.c * 100 * np.maximum(signed_cm1, 0).sum() / HARTREE_J
    )
    return {"frequencies_cm1": signed_cm1.tolist(), "zpe_hartree": zpe,
            "vibrational_modes": basis.shape[1], "removed_rigid_modes": 3 * n - basis.shape[1],
            "validity": validity, "stationary": stationary,
            "imaginary_tolerance_cm1": imaginary_tolerance_cm1,
            "small_imaginary_modes": int(np.sum((signed_cm1 < 0) & (signed_cm1 >= -imaginary_tolerance_cm1))),
            "isotope_provenance": isotope_records, "constants": constants_provenance()}
