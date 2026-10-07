"""Preflight only for the native hosted case; no successful ORCA run is mocked."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from topos.chemistry import atomic_number
from topos.correlated import correlated_input
from topos.fragments import split_fragments
from topos.matrix_workflow import MatrixInputs
from topos.method_matrix import MATRIX_REVISION
from topos.models import ResourceLimits
from topos.orca_f12_composite import SOURCE_RESOLUTION

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "orca_f12_acceptance_case.py"
SPEC = importlib.util.spec_from_file_location("orca_f12_acceptance_case_preflight", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_hosted_case_preserves_exact_15_component_chemical_and_method_inventory():
    resources = ResourceLimits(threads=1, memory_mb=4096, budget_seconds=2400)
    request = MODULE.acceptance_request(resources)
    inputs = MatrixInputs.model_validate(request.matrix_inputs)
    protocol = inputs.orca_f12_composite
    assert request.matrix_row_id == "T5-3h" and request.matrix_revision == MATRIX_REVISION
    assert inputs.source_resolution == SOURCE_RESOLUTION
    assert request.resources == resources
    assert sum(atomic_number(symbol) for symbol in request.molecule.symbols) == 12
    fragments = split_fragments(request.molecule)
    assert [m.symbols for m in fragments] == [["O", "H", "H"], ["H", "H"]]
    assert all(m.charge == 0 and m.multiplicity == 1 for m in [request.molecule, *fragments])
    assert [xyz for m in fragments for xyz in m.coordinates] == request.molecule.coordinates
    assert protocol.base.method == "CCSD(T)-F12D/RI"
    assert protocol.mp2_low.method == protocol.mp2_high.method == "F12-RI-MP2"
    assert protocol.base.orbital_basis == protocol.mp2_low.orbital_basis == "jun-cc-pVTZ"
    assert protocol.mp2_high.orbital_basis == "jun-cc-pVQZ"
    assert protocol.base.cabs == protocol.mp2_low.cabs == "cc-pVTZ-F12-CABS"
    assert protocol.mp2_high.cabs == "cc-pVQZ-F12-CABS"
    assert protocol.base.auxiliary_c == protocol.mp2_low.auxiliary_c == protocol.mp2_high.auxiliary_c == "cc-pVQZ/C"
    assert protocol.cv_ae.orbital_basis == protocol.cv_fc.orbital_basis == "cc-pwCVTZ"
    assert protocol.cv_ae.frozen_core is False and protocol.cv_fc.frozen_core is True
    assert protocol.cv_ae.model_dump(exclude={"frozen_core"}) == protocol.cv_fc.model_dump(exclude={"frozen_core"})
    assert (protocol.hf_exponential_alpha, protocol.correlation_inverse_power) == (1.7, 3.)
    assert "not calibrated" in request.metadata["cbs_exponents_role"]
    decks = [correlated_input(molecule, native, resources)
             for molecule in [request.molecule, *fragments] for native in protocol.protocols().values()]
    assert len(decks) == 15 and all("* xyz 0 1" in deck for deck in decks)
    assert sum("NoFrozenCore" in deck for deck in decks) == 3
    assert all(" Opt" not in deck and " Engrad" not in deck for deck in decks)


def test_hosted_case_rejects_gpu_allocation_before_native_execution():
    with pytest.raises(ValueError, match="CPU allocation"):
        MODULE.acceptance_request(ResourceLimits(device="gpu"))
