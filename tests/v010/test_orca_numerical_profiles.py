"""Versioned rendering, genuine SCF evidence, and cache/calibration separation.

No engine executes and no completed native receipt is manufactured here.
"""
import hashlib
import json
import re
from pathlib import Path

import pytest

from topos.anharmonic import orca_vpt2_input
from topos.engines import _method_problem, _orca_input
from topos.method_matrix import CalibratedRuntimeEstimator, CalibrationKey, RuntimeSample
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.native_hessian import orca_frequency_input, run_orca_hessian
from topos.orca_numerical_profiles import (
    MAPPING_V42,
    SCF_BLOCK,
    bind_numerical_profile_calibration_problem,
    numerical_profile_receipt,
    observe_scf_numerical_profile,
    verify_numerical_profile_receipt,
)
from topos.storage import digest_json

FIXTURES = Path(__file__).parents[1] / "fixtures/orca61-scf-mode0-tole"


def actual_text(name):
    provenance = json.loads((FIXTURES / "provenance.json").read_text())["files"][name]
    raw = (FIXTURES / name).read_bytes()
    assert len(raw) == provenance["size_bytes"]
    assert hashlib.sha256(raw).hexdigest() == provenance["sha256"]
    return raw.decode()


def system(profile=MAPPING_V42):
    molecule = Molecule(symbols=["O", "H", "H"], coordinates=[[.12, -.10, .08], [1.15, .13, .20], [-.20, .95, -.12]],
                        isotopes=[16, 1, 1], charge=0, multiplicity=1)
    method = MethodSpec(engine="orca", method="wB97X-V", basis="def2-TZVPP", auxiliary_basis="def2/J",
                        engine_version="6.1.1", profile_id=profile)
    return molecule, method, ResourceLimits(budget_seconds=900, threads=2, memory_mb=2048)


@pytest.mark.parametrize("operation", ["optimize", "gradient"])
def test_legacy_render_is_exact_and_new_render_matches_approved_scientific_deck(operation):
    molecule, old, resources = system("orca-mapping-v4.1")
    legacy = _orca_input(molecule, old, resources, operation)
    assert legacy == actual_text("predeclared-original-" + operation + ".inp")
    new = old.model_copy(update={"profile_id": MAPPING_V42})
    rendered = _orca_input(molecule, new, resources, operation)
    assert rendered == actual_text("predeclared-intervention-" + operation + ".inp")
    assert rendered == legacy.replace("* xyz 0 1\n", SCF_BLOCK + "* xyz 0 1\n")
    assert _method_problem(new, resources, operation, check_cpu_affinity=False) is None
    assert digest_json(new.model_dump()) != digest_json(old.model_dump())


def test_same_pose_hessian_inherits_new_scf_and_strict_vpt2_is_preserved():
    molecule, method, resources = system()
    with pytest.raises(ValueError, match="VV10/NL second derivatives are unavailable"):
        orca_frequency_input(molecule, method, resources, check_cpu_affinity=False)
    # B3LYP exercises supported derivative rendering only; this is not native
    # B3LYP evidence or a substitution for the requested VV10 Hamiltonian.
    method = method.model_copy(update={"method": "B3LYP"})
    deck = orca_frequency_input(molecule, method, resources, check_cpu_affinity=False)
    assert SCF_BLOCK in deck and deck.splitlines()[0].endswith(" Freq")
    strict = method.model_copy(update={"profile_id": "orca-vpt2-reference-v1"})
    molecule = molecule.model_copy(update={"isotopes": [None] * 3})
    strict_deck = orca_vpt2_input(molecule, strict, resources, check_cpu_affinity=False)
    assert " ExtremeSCF DEFGRID3" in strict_deck
    assert "%method\n  Z_Tol 1e-14\nend" in strict_deck
    assert "%scf" not in strict_deck
    assert numerical_profile_receipt(strict.profile_id) is None
    with pytest.raises(ValueError, match="explicit ExtremeSCF"):
        orca_vpt2_input(molecule, method, resources, check_cpu_affinity=False)


def test_new_hessian_producer_authors_profile_identity_before_execution_without_changing_legacy(tmp_path):
    molecule, method, resources = system()
    method = method.model_copy(update={"method": "B3LYP"})
    resources = resources.model_copy(update={"threads": 1})
    missing = str(tmp_path / 'missing-orca-executable')
    new = run_orca_hessian(molecule, method, resources, tmp_path / 'new', executable=missing)
    assert new.status == 'unavailable' and new.metadata['execution_kind'] == 'not-executed'
    assert new.metadata['profile_id'] == MAPPING_V42
    assert new.metadata['requested_method']['profile_id'] == MAPPING_V42
    assert new.metadata['numerical_profile'] == numerical_profile_receipt(MAPPING_V42)
    assert 'process' not in new.diagnostics
    old = run_orca_hessian(molecule, method.model_copy(update={'profile_id':'orca-mapping-v4.1'}),
                           resources, tmp_path / 'old', executable=missing)
    assert old.status == 'unavailable' and 'profile_id' not in old.metadata and 'numerical_profile' not in old.metadata


@pytest.mark.parametrize("name", ["positive-optimization.stdout", "positive-cold.stdout"])
def test_actual_tighter_energy_native_rows_and_profile_provenance_reverify(name):
    raw = actual_text(name)
    evidence = observe_scf_numerical_profile(raw)
    assert evidence["passed"] is True
    assert evidence["final_printed_rows"]["Energy change"]["threshold"] == 1e-10
    assert evidence["final_printed_rows"]["RMS-Density change"]["achieved"] is True
    receipt = numerical_profile_receipt(MAPPING_V42)
    assert receipt["definition_sha256"] == digest_json(receipt["definition"])
    verify_numerical_profile_receipt(MAPPING_V42, {"numerical_profile": receipt},
                                     {"scf_numerical_profile": evidence}, raw)


@pytest.mark.parametrize("name", ["negative-old-mode0-cold.stdout", "negative-mode2-cold.stdout"])
def test_genuine_previous_native_failures_cannot_be_promoted_to_the_new_profile(name):
    raw = actual_text(name)
    evidence = observe_scf_numerical_profile(raw)
    assert evidence["passed"] is False
    assert "printed target differs: Energy change" in evidence["failures"]
    if name == "negative-old-mode0-cold.stdout":
        assert "active final criterion not achieved: RMS-Density change" in evidence["failures"]
    with pytest.raises(ValueError, match="achieved active raw SCF"):
        verify_numerical_profile_receipt(MAPPING_V42, {"numerical_profile": numerical_profile_receipt(MAPPING_V42)},
                                         {"scf_numerical_profile": evidence}, raw)


@pytest.mark.parametrize("corruption", ["missing_profile", "profile_definition", "profile_digest", "raw_evidence", "false_pass"])
def test_cache_metadata_cannot_replace_exact_native_numerical_profile_evidence(corruption):
    raw = actual_text("positive-cold.stdout")
    metadata = {"numerical_profile": numerical_profile_receipt(MAPPING_V42)}
    diagnostics = {"scf_numerical_profile": observe_scf_numerical_profile(raw)}
    if corruption == "missing_profile":
        metadata.clear()
    elif corruption == "profile_definition":
        metadata["numerical_profile"]["definition"]["scf_controls"]["TolE"] = 1e-8
    elif corruption == "profile_digest":
        metadata["numerical_profile"]["definition_sha256"] = "0" * 64
    elif corruption == "raw_evidence":
        diagnostics["scf_numerical_profile"]["raw_stdout_sha256"] = "0" * 64
    else:
        diagnostics["scf_numerical_profile"]["passed"] = False
    with pytest.raises(ValueError):
        verify_numerical_profile_receipt(MAPPING_V42, metadata, diagnostics, raw)


def calibration_key(profile="orca-mapping-v4.1", **problem_changes):
    problem = {"atom_count": 3, "charge": 0, "multiplicity": 1, "operation": "optimize", "constraints_sha256": "0" * 64}
    problem.update(problem_changes)
    return CalibrationKey(row_id="T3O-30min", engine="orca", engine_version="6.1.1", method="wB97X-V",
                          basis="def2-TZVPP", profile_id=profile, hardware_fingerprint="explicit-observed-host",
                          threads=2, memory_mb=2048, problem=problem)


def test_new_profile_requires_exact_calibration_identity_and_rejects_legacy_timing_transfer():
    old = calibration_key()
    with pytest.raises(ValueError, match="exact versioned ORCA numerical profile"):
        calibration_key(MAPPING_V42)
    with pytest.raises(ValueError, match="exact versioned ORCA numerical profile"):
        calibration_key(MAPPING_V42, numerical_profile_sha256="0" * 64)
    new = calibration_key(MAPPING_V42, numerical_profile_sha256=numerical_profile_receipt(MAPPING_V42)["definition_sha256"])
    assert old.digest() != new.digest()
    estimator = CalibratedRuntimeEstimator([RuntimeSample(key=old, wall_seconds=100 + i, measurement_id="historical-" + str(i),
                                                          evidence_sha256="1" * 64) for i in range(3)])
    assert estimator.estimate(old).matching_samples == 3
    assert estimator.estimate(new).matching_samples == 0
    assert estimator.estimate(new).fits_budget(900) is None


def test_calibration_binding_requires_authored_profile_and_actual_raw_criteria():
    raw = actual_text("positive-cold.stdout")
    metadata = {"profile_id": MAPPING_V42, "requested_method": {"profile_id": MAPPING_V42},
                "numerical_profile": numerical_profile_receipt(MAPPING_V42)}
    diagnostics = {"scf_numerical_profile": observe_scf_numerical_profile(raw)}
    context = {"atom_count": 3}
    bound = bind_numerical_profile_calibration_problem(MAPPING_V42, metadata, diagnostics, raw, context)
    assert context == {"atom_count": 3}
    assert bound["numerical_profile_sha256"] == numerical_profile_receipt(MAPPING_V42)["definition_sha256"]
    with pytest.raises(ValueError, match="originally authored"):
        bind_numerical_profile_calibration_problem(MAPPING_V42, {**metadata, "profile_id": "orca-mapping-v4.1"}, diagnostics, raw, context)
    with pytest.raises(ValueError, match="different numerical profile"):
        bind_numerical_profile_calibration_problem(MAPPING_V42, metadata, diagnostics, raw, {"numerical_profile_sha256": "0" * 64})
    previous_raw = actual_text("negative-old-mode0-cold.stdout")
    with pytest.raises(ValueError, match="achieved active raw SCF"):
        bind_numerical_profile_calibration_problem(MAPPING_V42, metadata, diagnostics, previous_raw, context)
    assert bind_numerical_profile_calibration_problem("orca-mapping-v4.1", {}, {}, "", context) == context


@pytest.mark.parametrize("missing", ["final_solver_headers", "final_density_row", "final_mode", "final_settings"])
def test_multiblock_native_negative_tamper_cannot_borrow_prior_scf_evidence(missing):
    raw = actual_text("positive-optimization.stdout")
    assert raw.count('ORCA LEAN-SCF') == 2
    assert observe_scf_numerical_profile(raw)['passed'] is True
    if missing == 'final_solver_headers':
        start = raw.rfind('ORCA LEAN-SCF')
        altered = raw[:start] + re.sub(r'(?m)^-+(?:D-I-I-S|S-O-S-C-F)-+\s*$', '', raw[start:])
    elif missing == 'final_density_row':
        start = raw.rfind('SCF CONVERGENCE')
        altered = raw[:start] + re.sub(r'(?m)^\s*Last RMS-Density change.*$', '', raw[start:])
    elif missing == 'final_mode':
        start = raw.rfind('SCF SETTINGS')
        altered = raw[:start] + re.sub(r'(?m)^\s*Convergence Check Mode\s+ConvCheckMode.*$', '', raw[start:])
    else:
        start = raw.rfind('SCF SETTINGS')
        end = raw.index('ORCA LEAN-SCF', start)
        altered = raw[:start] + raw[end:]
    assert altered != raw
    evidence = observe_scf_numerical_profile(altered)
    assert evidence['passed'] is False
    if missing == 'final_solver_headers':
        assert evidence['final_active_converger'] is None
        assert 'final active native converger is not established' in evidence['failures']
    elif missing == 'final_density_row':
        assert 'missing final SCF row: RMS-Density change' in evidence['failures']
    else:
        assert 'native ConvCheckMode is not the declared All-Criteria mode' in evidence['failures']
    # This is an explicit negative parser control; the retained genuine bytes
    # are never changed, executed, or accepted as a native result.
    assert actual_text('positive-optimization.stdout') == raw
