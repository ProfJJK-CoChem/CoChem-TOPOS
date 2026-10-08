"""Native failure regressions: no licensed ORCA execution is simulated."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from topos.correlated import (
    CorrelatedMethod,
    correlated_input,
    correlated_resource_allocation,
    run_correlated,
)
from topos.correlated_counterpoise import (
    CorrelatedGhostLeg,
    _basis_slot_bindings,
    correlated_ghost_input,
)
from topos.models import Molecule, ResourceLimits
from topos.runtime import run_process

FIXTURES = Path(__file__).parent / "fixtures" / "orca_611_correlated_failures"


def native_failure(name):
    receipt = json.loads((FIXTURES / "provenance.json").read_text())["files"][name]
    evidence = {}
    for label, item in receipt["files"].items():
        raw = (FIXTURES / item["file"]).read_bytes()
        assert len(raw) == item["size_bytes"]
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        evidence[label] = raw.decode()
    assert receipt["native_result_status"] == "failed"
    return receipt, evidence


def hydrogen():
    return Molecule(symbols=["H", "H"], coordinates=[[0, 0, 6], [.74, 0, 6]])


def f12(**updates):
    data = dict(method="CCSD(T)-F12D/RI", orbital_basis="jun-cc-pVTZ", frozen_core=True,
                auxiliary_c="cc-pVQZ/C", cabs="cc-pVTZ-F12-CABS")
    return CorrelatedMethod(**{**data, **updates})


def test_native_hydrogen_f12_pair_failure_drives_exact_rank_correction_and_keeps_maxcore():
    receipt, raw = native_failure("f12-pair-cap")
    assert "NO frozen core" in raw["engine.stdout"]
    assert "Number of processes (2) in parallel calculation exceeds number of pairs (1)" in raw["engine.stdout"]
    assert "ORCA finished by error termination in MDCI" in raw["engine.stdout"]
    protocol = CorrelatedMethod.model_validate_json(raw["protocol.json"])
    requested = ResourceLimits.model_validate(receipt["resources"])
    effective, allocation = correlated_resource_allocation(hydrogen(), protocol, requested)
    assert requested.threads == 2 and effective.threads == 1
    assert effective.memory_mb == requested.memory_mb and effective.budget_seconds == requested.budget_seconds
    assert allocation["physical_electrons"] == 2
    assert allocation["proven_frozen_core_orbitals"] == 0
    assert allocation["proven_occupied_pair_count"] == 1
    assert allocation["requested_maxcore_mb"] == allocation["effective_maxcore_mb"] == 1536
    corrected = correlated_input(hydrogen(), protocol, requested)
    assert corrected == raw["job.inp"].replace("%pal nprocs 2", "%pal nprocs 1")


@pytest.mark.parametrize("method", ["CCSD(T)-F12D/RI", "F12-MP2", "F12-RI-MP2"])
@pytest.mark.parametrize("frozen_core", [True, False])
def test_hydrogen_has_one_pair_for_each_explicit_f12_protocol(method, frozen_core):
    protocol = f12(method=method, frozen_core=frozen_core,
                   auxiliary_c=None if method == "F12-MP2" else "cc-pVQZ/C")
    resources, allocation = correlated_resource_allocation(hydrogen(), protocol, ResourceLimits(threads=8))
    assert resources.threads == 1 and allocation["requested_threads"] == 8
    assert allocation["core_count_evidence"] == "H/He have no core orbitals"


@pytest.mark.parametrize("frozen_core,expected", [(True, 32), (False, 15)])
def test_heavy_atom_core_count_is_explicit_or_kept_unresolved(frozen_core, expected):
    water = Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.96, 0, 0], [-.24, .93, 0]])
    effective, allocation = correlated_resource_allocation(water, f12(frozen_core=frozen_core), ResourceLimits(threads=32))
    assert effective.threads == expected
    if frozen_core:
        assert allocation["proven_occupied_pair_count"] is None
        assert "not established" in allocation["policy"]
        assert "proven_frozen_core_orbitals" not in allocation
    else:
        assert allocation["occupied_orbitals"] == 5 and allocation["proven_occupied_pair_count"] == 15
        assert allocation["proven_frozen_core_orbitals"] == 0


def test_non_f12_protocol_does_not_inherit_unrequested_resource_policy():
    protocol = CorrelatedMethod(method="CCSD(T)", orbital_basis="cc-pVTZ", frozen_core=True)
    requested = ResourceLimits(threads=2)
    effective, allocation = correlated_resource_allocation(hydrogen(), protocol, requested)
    assert effective == requested and allocation["policy"] == "requested-allocation"


def test_unavailable_f12_run_retains_both_requested_and_effective_resources(tmp_path):
    requested = ResourceLimits(threads=2, memory_mb=4096)
    result = run_correlated(hydrogen(), f12(), requested, tmp_path / "absent",
                            executable="/missing/licensed/orca", process_runner=run_process)
    assert result.status == "unavailable" and result.energy_hartree is None
    assert result.metadata["resources"] == requested.model_dump(mode="json")
    assert result.metadata["effective_resources"]["threads"] == 1
    assert result.metadata["resource_allocation"]["requested_threads"] == 2
    assert result.metadata["execution_kind"] == "not-executed" and not result.artifacts


def test_native_rijk_ghost_missing_auxj_uses_identical_exported_jk_bytes():
    receipt, raw = native_failure("rijk-auxj-slot")
    assert "AUXILIARY/JK BASIS SET INFORMATION" in raw["engine.stdout"]
    assert "ERROR: no AuxJ basis set in ORCA_GTOInt!" in raw["engine.stdout"]
    leg = CorrelatedGhostLeg.model_validate_json(raw["protocol.json"])
    physical = Molecule.model_validate(receipt["physical_molecule"])
    corrected = correlated_ghost_input(physical, leg, ResourceLimits.model_validate(receipt["resources"]))
    assert corrected == raw["job.inp"].replace('  GTOAuxJKName "jk.bas"\n', '  GTOAuxJKName "jk.bas"\n  GTOAuxJName "jk.bas"\n')
    bindings = _basis_slot_bindings(leg)
    assert bindings["AuxJ"] == bindings["AuxJK"]
    assert bindings["AuxJ"]["basis"] == "cc-pVTZ/JK"
    assert bindings["AuxJ"]["sha256"] == leg.basis_exports["jk"]["output_sha256"]
    assert "AutoAux" not in corrected and "def2/J" not in corrected


def test_rijk_basis_slot_provenance_is_bound_to_exact_export_hash():
    _, raw = native_failure("rijk-auxj-slot")
    leg = CorrelatedGhostLeg.model_validate_json(raw["protocol.json"])
    original = _basis_slot_bindings(leg)
    changed = leg.model_copy(deep=True)
    changed.basis_exports["jk"]["output_sha256"] = "0" * 64
    assert _basis_slot_bindings(changed)["AuxJ"] != original["AuxJ"]
    assert _basis_slot_bindings(changed)["AuxC"] == original["AuxC"]
