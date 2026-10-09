"""Acceptance state-policy checks; no calculation or native output is mocked."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/accept_orca_topos.py"
spec = importlib.util.spec_from_file_location("topos_acceptance_validation", SCRIPT)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


@pytest.mark.parametrize("record_status", ["human-review", "validated-for-protocol"])
def test_native_protocol_validation_does_not_imply_operator_review(record_status):
    record = SimpleNamespace(validation_status=record_status, attempts=[
        SimpleNamespace(command=["native-engine"], validation_status="validated-for-protocol")])
    acceptance._require_calculation_validation(record)
    assert record.validation_status == record_status


@pytest.mark.parametrize("record_status,native_status", [
    ("rejected", "validated-for-protocol"),
    ("not-evaluated", "validated-for-protocol"),
    ("human-review", "human-review"),
    ("validated-for-protocol", "rejected"),
])
def test_unvalidated_native_observations_cannot_pass(record_status, native_status):
    record = SimpleNamespace(validation_status=record_status, attempts=[
        SimpleNamespace(command=["native-engine"], validation_status=native_status)])
    with pytest.raises(acceptance.AcceptanceFailure, match="protocol validation"):
        acceptance._require_calculation_validation(record)


def test_internal_bookkeeping_is_not_native_calculation_evidence():
    record = SimpleNamespace(validation_status="human-review", attempts=[
        SimpleNamespace(command=["topos-internal"], validation_status="validated-for-protocol")])
    with pytest.raises(acceptance.AcceptanceFailure, match="No real native"):
        acceptance._require_calculation_validation(record)


@pytest.mark.parametrize("case", ["native-vpt2", "native-hessian", "MP2"])
def test_extended_positive_vpt2_request_uses_c2v_seed_without_changing_other_cases(tmp_path, monkeypatch, case):
    """Intercept the actual selected request; no successful native result exists."""
    import numpy as np

    from topos.engines import _orca_input
    from topos.models import MethodSpec

    script = SCRIPT.with_name("accept_orca_extended.py")
    extended_spec = importlib.util.spec_from_file_location("topos_extended_seed_preflight", script)
    extended = importlib.util.module_from_spec(extended_spec)
    extended_spec.loader.exec_module(extended)
    binary = tmp_path / "not-a-native-executable"
    binary.write_text("Request interception only; never execute this file")

    class ContractRuntime:
        def __init__(self, registry):
            pass

        def validate_resources(self, resources):
            pass

        def resolve_executable(self, engine):
            assert engine == "orca"
            return str(binary)

        def provenance(self):
            return {"scope": "preflight contract only; no native authority"}

        def run_process(self, *args, **kwargs):
            raise AssertionError("Preflight must not launch native chemistry")

    captured = []

    def intercept(molecule, protocol, resources, folder, **options):
        captured.append((molecule, protocol, resources, folder, options))
        raise RuntimeError("Request intercepted before native execution; acceptance cannot pass")

    monkeypatch.setattr(extended, "BaseRuntime", ContractRuntime)
    monkeypatch.setattr(extended, "run_engine", intercept)
    monkeypatch.setattr(extended, "run_correlated", intercept)
    report, code = extended.run_acceptance(tmp_path / "unused-registry", tmp_path / "evidence",
        cases=[case], budget_seconds=77, threads=2, memory_mb=4096)
    assert code == 3 and report["status"] == report["cases"][case]["status"] == "failed"
    assert "intercepted before native execution" in report["cases"][case]["reason"]
    assert len(captured) == 1 and len(extended.CASES) == 13
    molecule, protocol, resources, folder, options = captured[0]
    assert molecule.symbols == ["O", "H", "H"] and molecule.charge == 0 and molecule.multiplicity == 1
    assert resources.threads == 2 and resources.memory_mb == 4096 and resources.device == "cpu"
    assert 0 < resources.budget_seconds <= 77 and options["executable"] == str(binary)
    assert options["process_runner"].__self__.__class__ is ContractRuntime
    if case == "native-vpt2":
        xyz = np.asarray(molecule.coordinates)
        assert xyz[0] == pytest.approx([0., 0., 0.])
        assert xyz[1] == pytest.approx(xyz[2] * [-1, 1, 1])
        assert np.all(xyz[:, 2] == 0) and xyz[1, 0] != 0 and xyz[1, 1] != 0
        masses = np.array([16., 1., 1.])
        centered = xyz - np.average(xyz, axis=0, weights=masses)
        inertia = sum(mass * (np.dot(row, row) * np.eye(3) - np.outer(row, row))
                      for mass, row in zip(masses, centered, strict=True))
        assert inertia - np.diag(np.diag(inertia)) == pytest.approx(np.zeros((3, 3)), abs=1e-15)
        assert protocol == MethodSpec(engine="orca", method="B3LYP", basis="def2-TZVPP",
            auxiliary_basis="def2/J", dispersion="D4", profile_id="orca-vpt2-reference-v1")
        deck = _orca_input(molecule, protocol, resources, "optimize")
        assert "B3LYP" in deck and "def2-TZVPP" in deck and "D4" in deck and " Opt" in deck
        assert "ExtremeSCF" in deck and "DEFGRID3" in deck and "RIJCOSX" in deck
        assert "TolRMSG 3e-8" in deck and "TolMaxG 1e-7" in deck and "TolE 1e-10" in deck
    else:
        assert molecule.coordinates == [[0, 0, 0], [.96, 0, 0], [-.24, .93, 0]]
        if case == "native-hessian":
            assert protocol == MethodSpec(engine="orca", method="r2SCAN-3c", profile_id="orca-mapping-v4.2")
        else:
            assert protocol.method == "MP2" and protocol.operation == "energy" and protocol.orbital_basis == "cc-pVDZ"
