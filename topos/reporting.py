"""Method-matrix A.1 reporting comparisons and explicit ensemble bookkeeping.

Reporting groups are an annotation over retained molecular identities. They
never authorize generation-stage deletion or invent unsampled degeneracy.
"""
from __future__ import annotations

import time
from copy import deepcopy
from threading import Event
from typing import Any

import numpy as np

from .chemistry import molecular_graph
from .models import Candidate, Molecule
from .science import (
    HARTREE_KCAL_MOL,
    _BoundedGraphMatcher,
    _check_comparison_budget,
    _chemical_neighborhood_labels,
    _ComparisonBudgetExhausted,
    _double_bond_cosine,
    _double_bond_groups,
    _label_fragments,
    _mapped_stereo,
    _normalized_tetrahedron,
    _opposite_orientation,
    _proper_rmsd,
    _state_signature,
    compare_molecules,
    energy_comparison_key,
    rotational_constants,
    validate_stereochemical_preservation,
)
from .symmetry import point_group_analysis, principal_axis_dipole


def _heavy_geometry(a: Molecule, b: Molecule, *, threshold: float,
                    max_permutations: int, max_search_nodes: int,
                    deadline: float | None, cancel_event: Event | None) -> dict[str, Any]:
    result: dict[str, Any] = {"equivalent": False, "atom_selection": "heavy (Z > 1)",
                              "weighting": "uniform", "proper_rotations_only": True,
                              "rmsd_threshold_angstrom": threshold, "rmsd_angstrom": None,
                              "atom_mapping": None, "permutations": 0}
    selection = [i for i, symbol in enumerate(a.symbols) if symbol != "H"]
    if not selection:
        return {**result, "status": "unresolved", "reason": "heavy-atom reporting RMSD is undefined for an all-hydrogen system"}
    if _state_signature(a, include_stereo=False) != _state_signature(b, include_stereo=False):
        return {**result, "status": "different-state", "reason": "molecular/isotope/fragment states differ"}
    if any(validate_stereochemical_preservation(mol, mol)["status"] != "preserved" for mol in (a, b)):
        return {**result, "status": "unresolved", "reason": "stereochemical declarations require review"}
    ga, gb = molecular_graph(a), molecular_graph(b)
    if any(edge["kind"] == "unknown" for graph in (ga, gb) for _, _, edge in graph.edges(data=True)):
        return {**result, "status": "unresolved", "reason": "unknown bond identities require review"}
    _label_fragments(ga, a)
    _label_fragments(gb, b)
    matcher = _BoundedGraphMatcher(
        ga, gb, max_search_nodes=max_search_nodes, deadline=deadline, cancel_event=cancel_event,
        node_match=lambda x, y: (x["symbol"], x["isotope"], x["fragment_state"]) == (y["symbol"], y["isotope"], y["fragment_state"]),
        edge_match=lambda x, y: x["order"] == y["order"] and
        ("covalent" if x["kind"] == "inferred" else x["kind"]) == ("covalent" if y["kind"] == "inferred" else y["kind"]),
    )
    labels = _chemical_neighborhood_labels(ga)
    tetras = [list(ga.neighbors(i)) for i in ga if ga.degree(i) == 4 and len({labels[j][-1] for j in ga.neighbors(i)}) == 4]
    doubles = _double_bond_groups(ga, labels)
    declared = _mapped_stereo(a, dict(enumerate(range(len(a.symbols)))))
    xyz_a, xyz_b = np.asarray(a.coordinates), np.asarray(b.coordinates)
    accepted = None
    try:
        for mapping in matcher.isomorphisms_iter():
            _check_comparison_budget(deadline, cancel_event)
            if result["permutations"] >= max_permutations:
                raise _ComparisonBudgetExhausted("atom permutation budget exhausted")
            result["permutations"] += 1
            if declared != _mapped_stereo(b, {right: left for left, right in mapping.items()}):
                continue
            order = [mapping[i] for i in range(len(a.symbols))]
            xyz = xyz_b[order]
            # Include all labelled atoms in stereo guards although the Stage B
            # RMSD is heavy-atom only. A planar heavy skeleton does not erase H/D
            # chirality, and near-planar double bonds cannot certify identity.
            if _opposite_orientation(xyz_a, xyz):
                continue
            if any(abs(first) <= 1e-3 or abs(second) <= 1e-3 or first * second < 0
                   for first, second in ((_normalized_tetrahedron(xyz_a[group]),
                                           _normalized_tetrahedron(xyz[group])) for group in tetras)):
                continue
            if any(abs(first) <= 1e-3 or abs(second) <= 1e-3 or first * second < 0
                   for first, second in ((_double_bond_cosine(xyz_a, group), _double_bond_cosine(xyz, group)) for group in doubles)):
                continue
            rmsd = _proper_rmsd(xyz_a[selection], xyz[selection])
            if result["rmsd_angstrom"] is None or rmsd < result["rmsd_angstrom"]:
                result.update(rmsd_angstrom=rmsd, atom_mapping=order)
            if rmsd <= threshold:
                accepted = {**result, "status": "equivalent", "equivalent": True,
                            "reason": "labelled connectivity, stereo guards and heavy-atom proper RMSD agree"}
                if rmsd <= 1e-12:
                    return {**accepted, "search_termination": "qualifying-mapping"}
    except _ComparisonBudgetExhausted as exc:
        return {**(accepted or result), "status": "equivalent" if accepted else "unresolved",
                "reason": accepted["reason"] if accepted else str(exc), "search_termination": "budget"}
    finally:
        matcher.reset_recursion_limit()
    return {**(accepted or result), "status": "equivalent" if accepted else "distinct",
            "reason": accepted["reason"] if accepted else "no stereo-preserving heavy-atom mapping meets tolerance",
            "search_termination": "exhaustive"}


def compare_reporting_candidates(a: Candidate, b: Candidate, *, qm_refined: bool,
                                 rmsd_threshold: float = 0.125,
                                 energy_threshold_kcal_mol: float = 0.05,
                                 rotational_threshold_fraction: float = 0.001,
                                 max_permutations: int = 10000, max_search_nodes: int = 100000,
                                 deadline: float | None = None, cancel_event: Event | None = None,
                                 dipole_a_debye: list[float] | None = None,
                                 dipole_b_debye: list[float] | None = None,
                                 dipole_error_debye: float | None = None) -> dict[str, Any]:
    """Matrix Stage B: common QM refinement AND energy AND ABC AND heavy RMSD.

    ``qm_refined`` is an explicit caller assertion supported by its attempt
    provenance. A screening ensemble cannot silently opt into this stage.
    Missing dipoles are not zero; supplied dipoles are only an additional
    disagreement veto, never an independent merge criterion.
    """
    if not isinstance(qm_refined, bool):
        raise ValueError("QM refinement assertion must be a boolean")
    if any(not np.isfinite(value) or value <= 0 for value in (rmsd_threshold, energy_threshold_kcal_mol, rotational_threshold_fraction)):
        raise ValueError("reporting thresholds must be finite and positive")
    if any(not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 for limit in (max_permutations, max_search_nodes)):
        raise ValueError("comparison budgets must be positive integers")
    if deadline is not None and not np.isfinite(deadline):
        raise ValueError("comparison deadline must be finite")
    result: dict[str, Any] = {"equivalent": False, "status": "unresolved", "stage": "reporting",
                              "policy": "method-matrix-A.1-stage-B", "combination": "AND",
                              "comparison_protocol": a.comparison_protocol,
                              "energy_threshold_kcal_mol": energy_threshold_kcal_mol,
                              "rotational_threshold_fraction": rotational_threshold_fraction,
                              "rotational_policy": "abs(first-second)/max(abs(first),abs(second))",
                              "rmsd_threshold_angstrom": rmsd_threshold,
                              "criteria": {"qm_refinement": qm_refined, "comparable_energy": None,
                                           "energy": None, "rotation": None, "geometry": None},
                              "dipole_consistency": "not-supplied"}
    if not qm_refined:
        return {**result, "reason": "reporting comparison requires all survivors reoptimized at a common declared QM level"}
    if (deadline is not None and time.monotonic() >= deadline) or (cancel_event and cancel_event.is_set()):
        return {**result, "reason": "comparison cancelled or deadline exhausted"}
    key = energy_comparison_key(a)
    if key is None or key != energy_comparison_key(b):
        result["criteria"]["comparable_energy"] = False
        return {**result, "status": "incomparable", "reason": "valid energies at one complete protocol and molecular state are required"}
    result["criteria"]["comparable_energy"] = True
    difference = abs(a.energy_hartree - b.energy_hartree) * HARTREE_KCAL_MOL
    result["energy_difference_kcal_mol"] = difference
    result["criteria"]["energy"] = difference <= energy_threshold_kcal_mol
    first = rotational_constants(a.molecule)["constants_ghz"]
    second = rotational_constants(b.molecule)["constants_ghz"]
    fractions = [None if x is None or y is None else abs(x - y) / max(abs(x), abs(y)) for x, y in zip(first, second, strict=True)]
    rotation_ok = all((x is None and y is None) or (fraction is not None and fraction <= rotational_threshold_fraction)
                      for x, y, fraction in zip(first, second, fractions, strict=True))
    result["rotational_constants_ghz"] = [first, second]
    result["rotational_difference_fractions"] = fractions
    result["criteria"]["rotation"] = rotation_ok
    if not result["criteria"]["energy"] or not rotation_ok:
        return {**result, "status": "distinct", "reason": "energy or rotational reporting threshold exceeded"}
    geometry = _heavy_geometry(a.molecule, b.molecule, threshold=rmsd_threshold,
                              max_permutations=max_permutations, max_search_nodes=max_search_nodes,
                              deadline=deadline, cancel_event=cancel_event)
    result["geometry"] = geometry
    result["criteria"]["geometry"] = geometry["equivalent"]
    if not geometry["equivalent"]:
        return {**result, "status": geometry["status"], "reason": geometry["reason"]}
    if dipole_error_debye is not None and dipole_a_debye is None and dipole_b_debye is None:
        dipole_a_debye = a.metadata.get("dipole", {}).get("cartesian_debye")
        dipole_b_debye = b.metadata.get("dipole", {}).get("cartesian_debye")
    if dipole_a_debye is not None or dipole_b_debye is not None or dipole_error_debye is not None:
        if dipole_a_debye is None or dipole_b_debye is None or dipole_error_debye is None:
            return {**result, "dipole_consistency": "incomplete", "reason": "both actual dipoles and a method error are required for a dipole consistency check"}
        if not np.isfinite(dipole_error_debye) or dipole_error_debye <= 0:
            raise ValueError("dipole method error must be finite and positive")
        first_mu = principal_axis_dipole(a.molecule, dipole_a_debye, dipole_method=a.comparison_protocol)
        second_mu = principal_axis_dipole(b.molecule, dipole_b_debye, dipole_method=b.comparison_protocol)
        if first_mu["status"] != "resolved" or second_mu["status"] != "resolved":
            return {**result, "dipole_consistency": "axis-ambiguity", "reason": "degenerate principal axes require aligned dipole review"}
        # Axis signs are a frame convention. Component magnitudes provide a
        # sign-gauge invariant disagreement screen; stored annotations remain signed.
        delta = np.abs(np.abs(first_mu["signed_abc_debye"]) - np.abs(second_mu["signed_abc_debye"]))
        result.update(dipole_difference_debye=delta.tolist(), dipole_error_debye=dipole_error_debye)
        if np.any(delta > dipole_error_debye):
            return {**result, "dipole_consistency": "requires-review", "reason": "dipoles disagree beyond the declared method error"}
        result["dipole_consistency"] = "consistent-with-declared-error"
    elif any(item.metadata.get("dipole", {}).get("cartesian_debye") is not None for item in (a, b)):
        result["dipole_consistency"] = "not-evaluated-method-error-unavailable"
    return {**result, "equivalent": True, "status": "equivalent", "reason": "all reporting AND criteria agree"}


def enantiomer_relation(a: Molecule, b: Molecule, *, rmsd_threshold: float = 1e-3,
                        max_permutations: int = 10000, max_search_nodes: int = 100000,
                        deadline: float | None = None, cancel_event: Event | None = None) -> dict[str, Any]:
    """Discover sampled mirror-related geometries; reflection is never identity.

    An unresolved proper comparison is not proof of chirality. Point-group
    verification and both proper and improper comparisons are recorded.
    """
    kwargs = dict(rmsd_threshold=rmsd_threshold, max_permutations=max_permutations,
                  max_search_nodes=max_search_nodes, deadline=deadline, cancel_event=cancel_event)
    proper = compare_molecules(a, b, **kwargs)
    base = {"relation": "unresolved", "proper_comparison": proper, "reflection_axis": "Cartesian x",
            "rmsd_threshold_angstrom": rmsd_threshold, "degeneracy_assigned": False}
    if proper["equivalent"]:
        return {**base, "relation": "same-handed-geometry"}
    if proper["status"] in {"unresolved", "different-state"}:
        return {**base, "reason": "proper comparison did not establish distinct comparable geometries"}
    mirror = b.model_copy(deep=True)
    mirror.coordinates = [[-x, y, z] for x, y, z in b.coordinates]
    declarations = deepcopy(mirror.stereochemistry)
    for center in declarations.get("tetrahedral_centers", []):
        center["orientation"] *= -1
    mirror.stereochemistry = declarations
    improper = compare_molecules(a, mirror, **kwargs)
    if not improper["equivalent"]:
        return {**base, "relation": "distinct" if improper["status"] == "distinct" else "unresolved", "improper_comparison": improper}
    symmetry_a, symmetry_b = point_group_analysis(a), point_group_analysis(b)
    chiral = symmetry_a["is_chiral_geometry"] is True and symmetry_b["is_chiral_geometry"] is True
    return {**base, "relation": "enantiomeric-geometries" if chiral else "unresolved",
            "improper_comparison": improper, "point_groups": [symmetry_a, symmetry_b],
            "reason": "proper rotations fail; reflected mapping succeeds; both geometries have verified chiral point groups" if chiral else "tolerance-sensitive or achiral point-group result requires review"}


def reporting_ensemble(candidates: list[Candidate], *, qm_refined: bool,
                       collapse_enantiomers: bool = False,
                       environment_is_achiral: bool | None = None,
                       dipole_error_debye: float | None = None,
                       deadline: float | None = None, cancel_event: Event | None = None) -> dict[str, Any]:
    """Create reviewable reporting groups without changing stored identities.

    Duplicate hits never increase g. Only two separately observed, geometrically
    verified enantiomers of unit weight may form a weight-2 reporting group in
    an explicitly achiral environment. An existing g > 1 is not counted again.
    Equivalent rotamer weights must come from declared external enumeration;
    sampled occurrences and point-group order are never multiplicities.
    """
    if len({item.candidate_id for item in candidates}) != len(candidates):
        raise ValueError("candidate identities must be unique")
    if collapse_enantiomers and environment_is_achiral is not True:
        raise ValueError("enantiomer collapse requires an explicitly achiral environment")
    representatives: list[Candidate] = []
    groups: list[list[str]] = []
    member_candidates: list[list[Candidate]] = []
    decisions: list[dict[str, Any]] = []
    for original in candidates:
        candidate = original.model_copy(deep=True)
        merged = False
        for index, representative in enumerate(representatives):
            comparison = compare_reporting_candidates(representative, candidate, qm_refined=qm_refined,
                                                      deadline=deadline, cancel_event=cancel_event,
                                                      dipole_error_debye=dipole_error_debye)
            matching_member = None
            for member in member_candidates[index]:
                member_comparison = compare_reporting_candidates(member, candidate, qm_refined=qm_refined,
                                                                 deadline=deadline, cancel_event=cancel_event,
                                                                 dipole_error_debye=dipole_error_debye)
                if member_comparison["equivalent"] and member.degeneracy == candidate.degeneracy:
                    matching_member = member
                    comparison = member_comparison
                    break
            decision = {"candidate_ids": [representative.candidate_id, candidate.candidate_id],
                        "comparison": comparison, "merged": False}
            if matching_member is not None:
                decision.update(merged=True, relation="same-handed-reporting-equivalent", degeneracy_action="unchanged; repeated samples are not additional states")
                merged = True
            elif (collapse_enantiomers and qm_refined and representative.degeneracy == candidate.degeneracy == 1
                  and comparison["criteria"]["energy"] and comparison["criteria"]["rotation"]):
                relation = enantiomer_relation(representative.molecule, candidate.molecule,
                                                deadline=deadline, cancel_event=cancel_event)
                decision["enantiomer_comparison"] = relation
                dipole_pair_ok = True
                if relation["relation"] == "enantiomeric-geometries" and dipole_error_debye is not None:
                    mirrored = candidate.model_copy(deep=True)
                    mirrored.molecule.coordinates = [[-x, y, z] for x, y, z in candidate.molecule.coordinates]
                    for center in mirrored.molecule.stereochemistry.get("tetrahedral_centers", []):
                        center["orientation"] *= -1
                    vector = mirrored.metadata.get("dipole", {}).get("cartesian_debye")
                    if vector is not None:
                        mirrored.metadata["dipole"]["cartesian_debye"] = [-vector[0], vector[1], vector[2]]
                    dipole_check = compare_reporting_candidates(representative, mirrored, qm_refined=True,
                                                                dipole_error_debye=dipole_error_debye,
                                                                deadline=deadline, cancel_event=cancel_event)
                    decision["enantiomer_dipole_check"] = dipole_check
                    dipole_pair_ok = dipole_check["equivalent"]
                if relation["relation"] == "enantiomeric-geometries" and dipole_pair_ok:
                    representative.degeneracy = 2
                    decision.update(merged=True, relation="sampled-enantiomer-pair", degeneracy_action="two verified unit-weight sampled members; g=2")
                    merged = True
            if not merged and comparison["equivalent"] and representative.degeneracy != candidate.degeneracy:
                decision["degeneracy_review"] = "pre-existing unequal weights cannot be combined without their partition-function convention"
            decisions.append(decision)
            if merged:
                groups[index].append(candidate.candidate_id)
                if decision.get("relation") == "sampled-enantiomer-pair":
                    # Keep one fixed anchor per hand, not every nearby hit;
                    # otherwise chained RMSD matches can span the tolerance.
                    member_candidates[index].append(original.model_copy(deep=True))
                representative.sources = sorted(set(representative.sources + candidate.sources))
                break
        if not merged:
            representatives.append(candidate)
            groups.append([candidate.candidate_id])
            member_candidates.append([original.model_copy(deep=True)])
    for representative, members in zip(representatives, groups, strict=True):
        representative.metadata["reporting_group"] = {"member_ids": members,
                                                       "identity_records_retained": True,
                                                       "degeneracy_convention": "distinct explicit states; duplicate samples add no weight"}
    return {"representatives": representatives, "groups": groups, "decisions": decisions,
            "identity_records_retained": True, "all_input_candidate_ids": [item.candidate_id for item in candidates],
            "qm_refined": qm_refined, "environment_is_achiral": environment_is_achiral,
            "partition_function_convention": "g multiplies each reporting representative once; never include both representative and member identities in the same sum",
            "spin_statistics": "not inferred from point groups; user-supplied molecular symmetry model required"}
