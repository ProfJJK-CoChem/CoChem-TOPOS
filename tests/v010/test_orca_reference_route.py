"""Ordinary strict-reference admission preserves native settings and boundaries."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from topos import capabilities
from topos.anharmonic import orca_vpt2_input
from topos.config import SystemConfig
from topos.engines import _orca_input
from topos.models import Molecule, RunRequest


@pytest.fixture
def allocation(monkeypatch):
    monkeypatch.setattr(capabilities.platform, "system", lambda: "Linux")
    monkeypatch.setattr(capabilities.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(capabilities.psutil, "virtual_memory", lambda: SimpleNamespace(available=8 * 1024**3))
    return SystemConfig(max_threads=2, max_memory_mb=4096)


def reference_request(method, purpose):
    water = Molecule(symbols=["O", "H", "H"],
        coordinates=[[0.0, 0.0, 0.0], [.758, .586, 0.0], [-.758, .586, 0.0]],
        charge=0, multiplicity=1, environment={"phase": "gas"})
    return RunRequest(molecule=water, engine="orca", engine_version="6.1.1", method=method,
        purpose=purpose, basis="def2-TZVPP", profile_id="orca-vpt2-reference-v1",
        auxiliary_basis="def2/J" if method == "B3LYP" else None,
        dispersion="D4" if method == "B3LYP" else None,
        threads=2, memory_mb=4096, budget_seconds=7200, n_candidates=1)


@pytest.mark.parametrize(("method", "purpose"), [("HF", "optimize"), ("HF", "thermochemistry"), ("B3LYP", "optimize")])
def test_existing_native_strict_profile_reaches_ordinary_workflow_unchanged(allocation, method, purpose):
    request = reference_request(method, purpose)
    before = request.model_dump(mode="json")
    expected_deck = _orca_input(request.molecule, request.method_spec, request.resources, "optimize")
    assert capabilities.validate_route(request, allocation) is None
    assert request.model_dump(mode="json") == before
    assert _orca_input(request.molecule, request.method_spec, request.resources, "optimize") == expected_deck
    assert "ExtremeSCF DEFGRID3" in expected_deck
    for keyword, value in {"TolE": "1e-10", "TolMaxG": "1e-7", "TolRMSG": "3e-8", "TolRMSD": "5e-7", "TolMaxD": "1e-6"}.items():
        assert f"  {keyword} {value}\n" in expected_deck
    assert "  EnforceStrictConvergence true\n" in expected_deck
    if method == "B3LYP":
        vpt2 = orca_vpt2_input(request.molecule, request.method_spec, request.resources, displacement=.05)
        assert " VPT2\n" in vpt2 and " D4 " in vpt2
        assert "%pal nprocs 1 end\n" in vpt2 and "%maxcore 1536\n" in vpt2


@pytest.mark.parametrize(("change", "status"), [
    ({"engine": "xtb", "method": "GFN2-xTB", "basis": None}, "unsupported"),
    ({"profile_id": "unreviewed-reference-profile"}, "unsupported"),
    ({"threads": 3}, "unavailable"),
    ({"memory_mb": 8192}, "unavailable"),
    ({"solvent": "water"}, "unsupported"),
    ({"calculation_environment": "remote"}, "unavailable"),
])
def test_reference_admission_cannot_override_engine_resource_or_environment_boundaries(allocation, change, status):
    request = reference_request("HF", "thermochemistry").model_copy(update=change)
    before = request.model_dump(mode="json")
    problem = capabilities.validate_route(request, allocation)
    assert problem is not None and problem[0] == status
    assert request.model_dump(mode="json") == before


def test_admitting_reference_profile_does_not_admit_native_isotope_vpt2(allocation):
    request = reference_request("B3LYP", "optimize")
    assert capabilities.validate_route(request, allocation) is None
    molecule = request.molecule.model_copy(update={"isotopes": [16, 1, 2]})
    with pytest.raises(ValueError, match="isotope-specific"):
        orca_vpt2_input(molecule, request.method_spec, request.resources, displacement=.05)
