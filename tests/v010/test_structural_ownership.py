"""Transferred actual Lewis-graph and isotope invariants; no energetic claims.

Original BASE source, tests and hashes are retained in the transfer manifest.
The four scientific test bodies are unchanged.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError
from rdkit import Chem

from topos.structural.graph import TopologyGraph
from topos.structural.resonance import (
    ResonanceEnumerator,
    ResonanceStructure,
    ResonanceThermodynamicsUnavailableError,
)
from topos.structural.tautomer import TopologyInput, _build_rdkit_mol_from_topology


def graph_from_smiles(smiles):
    molecule = Chem.MolFromSmiles(smiles)
    assert molecule is not None
    result = TopologyGraph()
    for atom in molecule.GetAtoms():
        result.add_chemical_node(atom.GetIdx(), atom.GetSymbol(), formal_charge=atom.GetFormalCharge(),
            hybridization=str(atom.GetHybridization()).lower(), in_ring=atom.IsInRing(), isotope=atom.GetIsotope())
    for bond in molecule.GetBonds():
        result.add_chemical_edge(bond.GetBeginAtomIdx(), bond.GetEndAtomIdx(), bond_order=bond.GetBondTypeAsDouble(), aromatic=bond.GetIsAromatic(), in_ring=bond.IsInRing())
    return result

def test_general_resonance_retains_real_kekule_forms_without_isomer_populations():
    result = ResonanceEnumerator.enumerate(graph_from_smiles("c1ccccc1"))
    assert result.ensemble_size == 2
    assert result.acceptance_scope == "structural_enumeration_only" and result.scientific_execution_performed is False
    assert result.weights is None and result.temperature_k is None
    assert all(form.relative_energy_kcal is None and form.boltzmann_weight is None for form in result.structures)
    assert result.structures[0].bond_orders != result.structures[1].bond_orders

def test_resonance_temperature_and_guessed_numeric_weights_are_explicitly_refused():
    graph = graph_from_smiles("c1ccccc1")
    with pytest.raises(ResonanceThermodynamicsUnavailableError, match="not thermally occupied isomers"):
        ResonanceEnumerator.enumerate(graph, temperature_k=298.15)
    actual = ResonanceEnumerator.enumerate(graph).structures[0].model_dump()
    with pytest.raises(ValidationError):
        ResonanceStructure(**{**actual, "boltzmann_weight": .5})
    with pytest.raises(ValidationError):
        ResonanceStructure(**{**actual, "relative_energy_kcal": 1.0})

def test_structural_truncation_is_declared_instead_of_claiming_complete_coverage():
    result = ResonanceEnumerator.enumerate(graph_from_smiles("c1ccccc1"), max_structures=1)
    assert result.ensemble_size == 1 and result.enumeration_truncated is True

def test_tautomer_topology_preserves_exact_explicit_nuclear_label():
    source = TopologyInput(molecule_id="isotope-formaldehyde", elements=["13C", "O"], atomic_numbers=[6, 8], bonds=[(0, 1, 2.0)])
    assert source.masses[0] > 13.0
    molecule = _build_rdkit_mol_from_topology(source)
    assert molecule.GetAtomWithIdx(0).GetIsotope() == 13
    assert molecule.GetAtomWithIdx(1).GetIsotope() == 0
