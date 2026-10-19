"""Resonance Structure Enumeration Subsystem.

Provides bounded structural Lewis contributor enumeration. Resonance contributors
are representations of one electronic state; they are not thermally occupied
isomers. This module neither assigns guessed energies nor Boltzmann populations.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from rdkit import Chem

from topos.structural.exceptions import TopologyError
from topos.structural.graph import TopologyGraph
from topos.structural.rings import perceive_aromaticity, perceive_cycle_basis

logger = logging.getLogger("cochem.topos.resonance")

class ResonanceEnumerationError(TopologyError):
    """A bounded chemical-structure enumeration or validation failure."""


class ResonanceThermodynamicsUnavailableError(ResonanceEnumerationError):
    """Lewis contributors cannot be assigned equilibrium-isomer populations."""


class ResonanceStructure(BaseModel):
    """Represents a discrete canonical resonance contributor."""

    bond_orders: dict[tuple[int, int], float] = Field(
        description="Dictionary mapping sorted node pairs (u, v) with u < v to bond orders."
    )
    formal_charges: dict[int, int] = Field(
        description="Formal charge assigned to each participating topological node."
    )
    model_config = ConfigDict(extra="forbid")
    relative_energy_kcal: None = Field(default=None, description="Unavailable: no resonance-contributor energy was calculated")
    boltzmann_weight: None = Field(default=None, description="Not applicable to Lewis resonance contributors")
    is_major: None = Field(default=None, description="No wavefunction-derived contributor ranking is available")


class ResonanceEnsembleResult(BaseModel):
    """Container storing an ensemble of resonance structures for a conjugated molecular graph."""

    ensemble_size: int = Field(ge=1, description="Total number of distinct resonance contributors.")
    kekule_structures: list[list[tuple[int, int, int]]] = Field(
        default_factory=list, description="List of bonds (u, v, order) per resonance contributor."
    )
    formal_charges: list[dict[int, int]] = Field(
        default_factory=list, description="Per-atom formal charge mapping for each resonance contributor."
    )
    weights: None = Field(default=None, description="No thermodynamic populations apply to resonance contributors")
    structures: list[ResonanceStructure] = Field(
        default_factory=list,
        description="Structurally valid contributors, without an energetic or population ranking.",
    )
    pi_system_nodes: list[int] = Field(
        default_factory=list,
        description="Topological node indices participating in conjugated pi-system.",
    )
    temperature_k: None = None
    acceptance_scope: Literal["structural_enumeration_only"] = "structural_enumeration_only"
    scientific_execution_performed: Literal[False] = False
    enumeration_truncated: bool = False
    excluded_ghost_nodes: list[int] = Field(default_factory=list)
    population_scope: Literal["not_applicable_to_resonance_contributors"] = "not_applicable_to_resonance_contributors"


class ResonanceEnumerator:
    """Enumerates canonical resonance contributors across conjugated pi-systems."""

    @classmethod
    def enumerate(
        cls,
        graph: TopologyGraph,
        max_structures: int = 50,
        temperature_k: float | None = None,
    ) -> ResonanceEnsembleResult:
        """Enumerate Lewis forms without pretending they are separate isomers.

        The historical temperature argument explicitly refuses thermal ranking.
        Quantitative resonance weights require an authentic wavefunction analysis.
        """
        if temperature_k is not None:
            raise ResonanceThermodynamicsUnavailableError(
                "Resonance contributors are not thermally occupied isomers; Boltzmann populations and temperature-dependent rankings are not defined by this structural enumeration"
            )
        if type(max_structures) is not int or not 1 <= max_structures <= 10000:
            raise ResonanceEnumerationError("Use a positive bounded structural enumeration limit")
        graph = graph.copy()
        ghosts = [node for node, data in graph.nodes(data=True) if data.get("is_ghost") or data.get("atomic_number") == 0]
        graph.remove_nodes_from(ghosts)
        if graph.number_of_nodes() == 0:
            raise ResonanceEnumerationError("Cannot enumerate resonance structures for an empty graph.")

        perceive_cycle_basis(graph)
        perceive_aromaticity(graph)

        pi_nodes = cls._detect_pi_system_nodes(graph)
        if not pi_nodes:
            # Saturated molecule: single canonical structure
            base_orders = {
                tuple(sorted((u, v))): float(d.get("bond_order", 1.0))
                for u, v, d in graph.edges(data=True)
            }
            base_charges = {n: int(graph.nodes[n].get("formal_charge", 0)) for n in graph.nodes()}
            single_struct = ResonanceStructure(
                bond_orders=base_orders,
                formal_charges=base_charges,
            )
            cls._validate_structure(graph, single_struct)
            kekule = [[(u, v, int(round(bo))) for (u, v), bo in base_orders.items()]]
            return ResonanceEnsembleResult(
                ensemble_size=1,
                kekule_structures=kekule,
                formal_charges=[base_charges],
                structures=[single_struct],
                pi_system_nodes=[],
                excluded_ghost_nodes=ghosts,
            )

        # Specialized recognition for heteroaromatic 5-rings and conjugated nitroarenes
        structures: list[ResonanceStructure] = []

        # Check for 5-membered heteroaromatic ring (e.g. Pyrrole)
        pyrrole_match = cls._match_pyrrole_like_ring(graph)
        if pyrrole_match is not None:
            structures = cls._generate_pyrrole_contributors(graph, pyrrole_match, temperature_k)

        # Check for nitroarene (e.g. Nitrobenzene)
        elif cls._is_nitroarene(graph):
            structures = cls._generate_nitrobenzene_contributors(graph, temperature_k)

        else:
            structures = cls._generate_general_contributors(graph, pi_nodes, temperature_k, max_structures)

        for structure in structures:
            cls._validate_structure(graph, structure)
        truncated = len(structures) > max_structures
        structures = structures[:max_structures]
        kekule_structures = [
            [(u, v, int(round(bo))) for (u, v), bo in s.bond_orders.items()]
            for s in structures
        ]
        formal_charges = [s.formal_charges for s in structures]

        return ResonanceEnsembleResult(
            ensemble_size=len(structures),
            kekule_structures=kekule_structures,
            formal_charges=formal_charges,
            structures=structures,
            pi_system_nodes=sorted(pi_nodes),
            enumeration_truncated=truncated,
            excluded_ghost_nodes=ghosts,
        )

    @classmethod
    def _detect_pi_system_nodes(cls, graph: TopologyGraph) -> set[int]:
        """Identifies all nodes possessing unhybridized p-orbitals participating in conjugation."""
        pi_nodes = set()
        for u in graph.nodes():
            n_data = graph.nodes[u]
            symbol = str(n_data.get("symbol", "")).upper()
            hyb = str(n_data.get("hybridization", "sp3"))
            is_aromatic = bool(n_data.get("is_aromatic", False))

            if is_aromatic or hyb in ("sp", "sp2"):
                pi_nodes.add(u)
            elif symbol in ("N", "O", "S"):
                # Heteroatom with lone pair adjacent to an sp2/sp/aromatic node
                nbr_hybs = [str(graph.nodes[v].get("hybridization", "sp3")) for v in graph.neighbors(u)]
                nbr_arom = [bool(graph.nodes[v].get("is_aromatic", False)) for v in graph.neighbors(u)]
                if any(h in ("sp", "sp2") for h in nbr_hybs) or any(nbr_arom):
                    pi_nodes.add(u)
        return pi_nodes

    @classmethod
    def _match_pyrrole_like_ring(cls, graph: TopologyGraph) -> Optional[dict[str, Any]]:
        """Identifies 5-membered heteroaromatic rings with a divalent/trivalent heteroatom."""
        cycles = perceive_cycle_basis(graph)
        for cycle in cycles:
            if len(cycle) == 5:
                hetero_nodes = [n for n in cycle if str(graph.nodes[n].get("symbol", "")).upper() in ("N", "O", "S")]
                carbon_nodes = [n for n in cycle if str(graph.nodes[n].get("symbol", "")).upper() == "C"]
                if len(hetero_nodes) == 1 and len(carbon_nodes) == 4:
                    h_node = hetero_nodes[0]
                    # Order ring starting from heteroatom
                    h_idx = cycle.index(h_node)
                    ordered = cycle[h_idx:] + cycle[:h_idx]
                    return {
                        "hetero": h_node,
                        "c1": ordered[1],
                        "c2": ordered[2],
                        "c3": ordered[3],
                        "c4": ordered[4],
                        "cycle": ordered,
                    }
        return None

    @classmethod
    def _generate_pyrrole_contributors(
        cls,
        graph: TopologyGraph,
        match: dict[str, Any],
        temperature_k: float,
    ) -> list[ResonanceStructure]:
        """Generates the 5 classic non-bipartite resonance contributors for a 5-membered heteroaromatic ring."""
        h = match["hetero"]
        c1, c2, c3, c4 = match["c1"], match["c2"], match["c3"], match["c4"]

        base_bonds = {
            tuple(sorted((u, v))): float(d.get("bond_order", 1.0))
            for u, v, d in graph.edges(data=True)
        }
        base_charges = {n: int(graph.nodes[n].get("formal_charge", 0)) for n in graph.nodes()}

        def make_structure(
            ring_bonds: dict[tuple[int, int], float],
            charge_shifts: dict[int, int],
        ) -> ResonanceStructure:
            bonds = dict(base_bonds)
            for (u, v), bo in ring_bonds.items():
                bonds[tuple(sorted((u, v)))] = float(bo)
            charges = dict(base_charges)
            for node, q in charge_shifts.items():
                charges[node] = q
            return ResonanceStructure(bond_orders=bonds, formal_charges=charges)

        specs = [
            # 1. Neutral Lewis contributor
            (
                {(h, c1): 1.0, (c1, c2): 2.0, (c2, c3): 1.0, (c3, c4): 2.0, (c4, h): 1.0},
                {h: 0, c1: 0, c2: 0, c3: 0, c4: 0},
            ),
            # 2. Charge-separated: N=C1 double bond, negative charge at C2
            (
                {(h, c1): 2.0, (c1, c2): 1.0, (c2, c3): 1.0, (c3, c4): 2.0, (c4, h): 1.0},
                {h: 1, c1: 0, c2: -1, c3: 0, c4: 0},
            ),
            # 3. Charge-separated: N=C1, C2=C3, negative charge at C4
            (
                {(h, c1): 2.0, (c1, c2): 1.0, (c2, c3): 2.0, (c3, c4): 1.0, (c4, h): 1.0},
                {h: 1, c1: 0, c2: 0, c3: 0, c4: -1},
            ),
            # 4. Charge-separated: N=C4 double bond, negative charge at C3
            (
                {(h, c1): 1.0, (c1, c2): 2.0, (c2, c3): 1.0, (c3, c4): 1.0, (c4, h): 2.0},
                {h: 1, c1: 0, c2: 0, c3: -1, c4: 0},
            ),
            # 5. Charge-separated: N=C4, C3=C2, negative charge at C1
            (
                {(h, c1): 1.0, (c1, c2): 1.0, (c2, c3): 2.0, (c3, c4): 1.0, (c4, h): 2.0},
                {h: 1, c1: -1, c2: 0, c3: 0, c4: 0},
            ),
        ]

        return [make_structure(bonds, charges) for bonds, charges in specs]

    @classmethod
    def _is_nitroarene(cls, graph: TopologyGraph) -> bool:
        """Determines if the topology contains an aromatic ring conjugated with a nitro group."""
        nitro_n = [
            n for n in graph.nodes()
            if str(graph.nodes[n].get("symbol", "")).upper() == "N"
            and sum(1 for v in graph.neighbors(n) if str(graph.nodes[v].get("symbol", "")).upper() == "O") == 2
        ]
        if not nitro_n:
            return False
        n_node = nitro_n[0]
        # Check if bonded to an aromatic carbon
        for v in graph.neighbors(n_node):
            if bool(graph.nodes[v].get("in_ring", False)):
                return True
        return False

    @classmethod
    def _generate_nitrobenzene_contributors(
        cls,
        graph: TopologyGraph,
        temperature_k: float,
    ) -> list[ResonanceStructure]:
        """Generates canonical forms and ortho/para charge-separated quinoid contributors for nitrobenzene."""
        nitro_n = [
            n for n in graph.nodes()
            if str(graph.nodes[n].get("symbol", "")).upper() == "N"
            and sum(1 for v in graph.neighbors(n) if str(graph.nodes[v].get("symbol", "")).upper() == "O") == 2
        ][0]
        o_nodes = [v for v in graph.neighbors(nitro_n) if str(graph.nodes[v].get("symbol", "")).upper() == "O"]
        o1, o2 = o_nodes[0], o_nodes[1]
        c0 = [v for v in graph.neighbors(nitro_n) if v not in o_nodes][0]

        # Find 6-ring containing c0
        cycles = perceive_cycle_basis(graph)
        ring_6 = [c for c in cycles if len(c) == 6 and c0 in c][0]
        # Orient ring starting from c0
        c0_idx = ring_6.index(c0)
        ordered_ring = ring_6[c0_idx:] + ring_6[:c0_idx]
        c0, c1, c2, c3, c4, c5 = ordered_ring

        base_bonds = {
            tuple(sorted((u, v))): float(d.get("bond_order", 1.0))
            for u, v, d in graph.edges(data=True)
        }
        base_charges = {n: int(graph.nodes[n].get("formal_charge", 0)) for n in graph.nodes()}

        def make_structure(
            ring_bonds: dict[tuple[int, int], float],
            charge_shifts: dict[int, int],
        ) -> ResonanceStructure:
            bonds = dict(base_bonds)
            for (u, v), bo in ring_bonds.items():
                bonds[tuple(sorted((u, v)))] = float(bo)
            charges = dict(base_charges)
            for node, q in charge_shifts.items():
                charges[node] = q
            return ResonanceStructure(bond_orders=bonds, formal_charges=charges)

        specs = [
            # Kekule form 1
            (
                {
                    (c0, nitro_n): 1.0, (nitro_n, o1): 2.0, (nitro_n, o2): 1.0,
                    (c0, c1): 2.0, (c1, c2): 1.0, (c2, c3): 2.0, (c3, c4): 1.0, (c4, c5): 2.0, (c5, c0): 1.0
                },
                {nitro_n: 1, o1: 0, o2: -1, c0: 0, c1: 0, c2: 0, c3: 0, c4: 0, c5: 0},
            ),
            # Kekule form 2
            (
                {
                    (c0, nitro_n): 1.0, (nitro_n, o1): 2.0, (nitro_n, o2): 1.0,
                    (c0, c1): 1.0, (c1, c2): 2.0, (c2, c3): 1.0, (c3, c4): 2.0, (c4, c5): 1.0, (c5, c0): 2.0
                },
                {nitro_n: 1, o1: 0, o2: -1, c0: 0, c1: 0, c2: 0, c3: 0, c4: 0, c5: 0},
            ),
            # Quinoid 1: positive charge at ortho-carbon c1
            (
                {
                    (c0, nitro_n): 2.0, (nitro_n, o1): 1.0, (nitro_n, o2): 1.0,
                    (c0, c1): 1.0, (c1, c2): 1.0, (c2, c3): 2.0, (c3, c4): 1.0, (c4, c5): 2.0, (c5, c0): 1.0
                },
                {nitro_n: 1, o1: -1, o2: -1, c0: 0, c1: 1, c2: 0, c3: 0, c4: 0, c5: 0},
            ),
            # Quinoid 2: positive charge at para-carbon c3
            (
                {
                    (c0, nitro_n): 2.0, (nitro_n, o1): 1.0, (nitro_n, o2): 1.0,
                    (c0, c1): 1.0, (c1, c2): 2.0, (c2, c3): 1.0, (c3, c4): 1.0, (c4, c5): 2.0, (c5, c0): 1.0
                },
                {nitro_n: 1, o1: -1, o2: -1, c0: 0, c1: 0, c2: 0, c3: 1, c4: 0, c5: 0},
            ),
            # Quinoid 3: positive charge at ortho-carbon c5
            (
                {
                    (c0, nitro_n): 2.0, (nitro_n, o1): 1.0, (nitro_n, o2): 1.0,
                    (c0, c1): 1.0, (c1, c2): 2.0, (c2, c3): 1.0, (c3, c4): 2.0, (c4, c5): 1.0, (c5, c0): 1.0
                },
                {nitro_n: 1, o1: -1, o2: -1, c0: 0, c1: 0, c2: 0, c3: 0, c4: 0, c5: 1},
            ),
        ]

        return [make_structure(bonds, charges) for bonds, charges in specs]

    @classmethod
    def _generate_general_contributors(
        cls,
        graph: TopologyGraph,
        pi_nodes: set[int],
        temperature_k: float,
        max_structures: int = 50,
    ) -> list[ResonanceStructure]:
        """Use RDKit's actual bounded bond/charge resonance enumeration."""
        original = cls._rdkit_structure(graph, {
            tuple(sorted((u, v))): float(data.get("bond_order", 1.0)) for u, v, data in graph.edges(data=True)
        }, {node: int(graph.nodes[node].get("formal_charge", 0)) for node in graph.nodes()})
        # Validate every returned atom/H assignment against the original below;
        # contributor generation moves electrons, not hydrogen nuclei.
        supplier = Chem.ResonanceMolSupplier(original, Chem.ResonanceFlags.KEKULE_ALL | Chem.ResonanceFlags.ALLOW_CHARGE_SEPARATION, max_structures + 1)
        nodes = list(graph.nodes())
        result = []
        for molecule in supplier:
            charges = {nodes[atom.GetIdx()]: atom.GetFormalCharge() for atom in molecule.GetAtoms()}
            bonds = {tuple(sorted((nodes[bond.GetBeginAtomIdx()], nodes[bond.GetEndAtomIdx()]))): float(bond.GetBondTypeAsDouble()) for bond in molecule.GetBonds()}
            result.append(ResonanceStructure(bond_orders=bonds, formal_charges=charges))
        if not result:
            raise ResonanceEnumerationError("RDKit did not produce any valid structural contributor")
        return result

    @staticmethod
    def _rdkit_structure(graph: TopologyGraph, bonds: dict, charges: dict):
        nodes = list(graph.nodes())
        if any(type(node) is not int for node in nodes):
            raise ResonanceEnumerationError("Chemical contributor nodes require explicit integer identities")
        molecule = Chem.RWMol()
        for node in nodes:
            data = graph.nodes[node]
            number = data.get("atomic_number")
            if type(number) is not int or not 1 <= number <= 118:
                raise ResonanceEnumerationError("Structural contributors require actual non-ghost atomic numbers")
            atom = Chem.Atom(number)
            atom.SetFormalCharge(charges[node])
            atom.SetNumRadicalElectrons(int(data.get("radical_electrons", 0)))
            isotope = data.get("isotope", data.get("mass_number"))
            if isotope is not None:
                atom.SetIsotope(int(isotope))
            molecule.AddAtom(atom)
        indices = {node: index for index, node in enumerate(nodes)}
        types = {1.0: Chem.BondType.SINGLE, 1.5: Chem.BondType.AROMATIC, 2.0: Chem.BondType.DOUBLE, 3.0: Chem.BondType.TRIPLE, 4.0: Chem.BondType.QUADRUPLE}
        for (left, right), order in bonds.items():
            if order not in types:
                raise ResonanceEnumerationError("Unsupported chemical bond order in structural contributor")
            molecule.AddBond(indices[left], indices[right], types[order])
            if order == 1.5:
                molecule.GetAtomWithIdx(indices[left]).SetIsAromatic(True)
                molecule.GetAtomWithIdx(indices[right]).SetIsAromatic(True)
        result = molecule.GetMol()
        try:
            Chem.SanitizeMol(result)
        except Exception as error:
            raise ResonanceEnumerationError("RDKit rejected the contributor's chemical valence") from error
        return result

    @classmethod
    def _validate_structure(cls, graph: TopologyGraph, structure: ResonanceStructure) -> None:
        if sum(structure.formal_charges.values()) != sum(int(graph.nodes[node].get("formal_charge", 0)) for node in graph.nodes()):
            raise ResonanceEnumerationError("A contributor changes the source molecular charge")
        if set(structure.bond_orders) != {tuple(sorted(edge)) for edge in graph.edges()}:
            raise ResonanceEnumerationError("A contributor changes the source nuclear connectivity")
        original = cls._rdkit_structure(graph, {tuple(sorted((u, v))): float(data.get("bond_order", 1.0)) for u, v, data in graph.edges(data=True)}, {node: int(graph.nodes[node].get("formal_charge", 0)) for node in graph.nodes()})
        observed = cls._rdkit_structure(graph, structure.bond_orders, structure.formal_charges)
        if any(a.GetAtomicNum() != b.GetAtomicNum() or a.GetIsotope() != b.GetIsotope() or a.GetTotalNumHs(includeNeighbors=True) != b.GetTotalNumHs(includeNeighbors=True) for a, b in zip(original.GetAtoms(), observed.GetAtoms(), strict=True)):
            raise ResonanceEnumerationError("A contributor changes the original nuclear or attached-hydrogen identity")
