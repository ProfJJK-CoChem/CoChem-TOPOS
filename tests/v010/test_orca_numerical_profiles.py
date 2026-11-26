"""Versioned rendering, genuine SCF evidence, and cache/calibration separation.

No engine executes and no completed native receipt is manufactured here.
"""
import hashlib
import json
import re
import sys
from pathlib import Path
from threading import Event

import pytest
from scipy.constants import physical_constants

from topos.anharmonic import orca_vpt2_input
from topos.engines import _method_problem, _orca_input, run_engine, write_xyz
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
from topos.runtime import ProcessResult
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


def test_trah_scf_converger_accepts_achieved_orbital_criteria_and_rejects_failures():
    """ORCA 6.1.1 Auto-TRAH/TRAH-SCF checks Energy, Orbital Gradient, and Orbital Rotation."""
    base = actual_text("positive-cold.stdout")
    trah_block = (
        "\n       ******************************************************************************\n"
        "       ***                               Auto-TRAH                                ***\n"
        "       ***               Leaving SCF to start the TRAH-SCF procedure              ***\n"
        "       ******************************************************************************\n"
        " --------------------------------------------------------------------------------------------\n"
        "   Iter.        energy            ||Error||_2        Shift      TRadius  Mac/Mic        Rej.\n"
        " --------------------------------------------------------------------------------------------\n"
        "    0       -200.000000000000     1.200000e-01                     0.400 (TRAH MAcro)   No\n"
        "    1       -201.015987893435     2.131203e-07                           (NR   MAcro)\n\n"
    )
    conv_idx = base.rfind("SCF CONVERGED AFTER")
    assert conv_idx != -1
    trah_raw = base[:conv_idx] + trah_block + base[conv_idx:]
    # Simulate stale pre-TRAH density-change and DIIS residuals in SCF CONVERGENCE summary
    trah_raw = re.sub(
        r"(Last MAX-Density change\s*\.\.\.\s*)\S+",
        r"\g<1>6.3142e-01",
        trah_raw,
    )
    trah_raw = re.sub(
        r"(Last RMS-Density change\s*\.\.\.\s*)\S+",
        r"\g<1>2.5480e-02",
        trah_raw,
    )
    trah_raw = re.sub(
        r"(Last DIIS Error\s*\.\.\.\s*)\S+",
        r"\g<1>2.1154e-03",
        trah_raw,
    )
    evidence = observe_scf_numerical_profile(trah_raw)
    assert evidence["passed"] is True, evidence["failures"]
    assert evidence["final_active_converger"] == "TRAH-SCF"
    assert evidence["DIIS_residual_mandatory"] is False
    assert evidence["inactive_DIIS_residual_retained"] is True
    assert evidence["density_residuals_mandatory"] is False
    assert evidence["inactive_density_residuals_retained"] is True
    assert evidence["trah_iter0_energy_change_uninitialized"] is False

    # Active TRAH-SCF criteria (Energy change, Orbital Gradient, Orbital Rotation) must still be strictly enforced.
    for label, bad_value in [
        ("Energy change", "5.0000e-09"),
        ("Orbital Gradient", "5.0000e-04"),
        ("Orbital Rotation", "5.0000e-04"),
    ]:
        failed_raw = re.sub(
            rf"(Last {re.escape(label)}\s*\.\.\.\s*)\S+",
            rf"\g<1>{bad_value}",
            trah_raw,
        )
        failed = observe_scf_numerical_profile(failed_raw)
        assert failed["passed"] is False
        assert failed["trah_iter0_energy_change_uninitialized"] is False
        assert f"active final criterion not achieved: {label}" in failed["failures"]

    # Multi-step TRAH with sentinel-like unachieved Energy change and zero rotation must still fail.
    multistep_bad_ec = re.sub(
        r"(Last Energy change\s*\.\.\.\s*)\S+",
        r"\g<1>-2.0102e+02",
        re.sub(r"(Last Orbital Rotation\s*\.\.\.\s*)\S+", r"\g<1>0.0000e+00", trah_raw),
    )
    multistep_bad_ev = observe_scf_numerical_profile(multistep_bad_ec)
    assert multistep_bad_ev["passed"] is False
    assert multistep_bad_ev["trah_iter0_energy_change_uninitialized"] is False
    assert "active final criterion not achieved: Energy change" in multistep_bad_ev["failures"]

    # Without TRAH-SCF (pure SOSCF), stale density residuals must still be rejected.
    bad_soscf = re.sub(r"(Last MAX-Density change\s*\.\.\.\s*)\S+", r"\g<1>6.3142e-01", base)
    bad_soscf_ev = observe_scf_numerical_profile(bad_soscf)
    assert bad_soscf_ev["passed"] is False
    assert bad_soscf_ev["final_active_converger"] == "S-O-S-C-F"
    assert bad_soscf_ev["trah_iter0_energy_change_uninitialized"] is False
    assert "active final criterion not achieved: MAX-Density change" in bad_soscf_ev["failures"]


def test_trah_scf_iter0_uninitialized_energy_change_accepts_strict_density_and_rejects_failures():
    """TRAH Iter-0 immediate convergence verifies pre-TRAH density rows even with stale summary rows."""
    base = actual_text("positive-cold.stdout")
    conv_idx = base.rfind("SCF CONVERGED AFTER")
    assert conv_idx != -1

    def make_trah_iter0(
        energy_str: str = "-76.434622047478",
        tag: str = "(TRAH MAcro)",
        energy_change: str = "-7.6435e+01",
        rotation: str = "0.0000e+00",
        strip_pre_trah_rows: bool = False,
        extra_pre_trah_rows: str = "",
        summary_max_dp: str | None = None,
        summary_rms_dp: str | None = None,
    ) -> str:
        prefix = base[:conv_idx]
        if strip_pre_trah_rows:
            lean_idx = prefix.rfind("ORCA LEAN-SCF")
            assert lean_idx != -1
            prefix = prefix[:lean_idx] + re.sub(
                r"(?m)^\s*\d+\s+[-+]\d+\.\d+.*$\n?",
                "",
                prefix[lean_idx:],
            )
        if extra_pre_trah_rows:
            prefix = prefix + extra_pre_trah_rows
        trah_block = (
            "\n       ******************************************************************************\n"
            "       ***                               Auto-TRAH                                ***\n"
            "       ***               Leaving SCF to start the TRAH-SCF procedure              ***\n"
            "       ******************************************************************************\n"
            " --------------------------------------------------------------------------------------------\n"
            "   Iter.        energy            ||Error||_2        Shift      TRadius  Mac/Mic        Rej.\n"
            " --------------------------------------------------------------------------------------------\n"
            f"    0       {energy_str}     2.390000e-07                           {tag}\n\n"
        )
        raw = prefix + trah_block + base[conv_idx:]
        raw = re.sub(r"(Last Energy change\s*\.\.\.\s*)\S+", rf"\g<1>{energy_change}", raw)
        raw = re.sub(r"(Last Orbital Rotation\s*\.\.\.\s*)\S+", rf"\g<1>{rotation}", raw)
        if summary_max_dp is not None:
            raw = re.sub(r"(Last MAX-Density change\s*\.\.\.\s*)\S+", rf"\g<1>{summary_max_dp}", raw)
        if summary_rms_dp is not None:
            raw = re.sub(r"(Last RMS-Density change\s*\.\.\.\s*)\S+", rf"\g<1>{summary_rms_dp}", raw)
        return raw

    # Authentic TRAH Iter-0 immediate convergence (both TRAH MAcro and NR MAcro, with or without pre-TRAH rows)
    for tag, strip_rows in [("(TRAH MAcro)", False), ("(NR   MAcro)", False), ("(TRAH MAcro)", True)]:
        ev = observe_scf_numerical_profile(make_trah_iter0(tag=tag, strip_pre_trah_rows=strip_rows))
        assert ev["passed"] is True, ev["failures"]
        assert ev["final_active_converger"] == "TRAH-SCF"
        assert ev["trah_iter0_energy_change_uninitialized"] is True
        assert ev["density_residuals_mandatory"] is False
        assert ev["inactive_density_residuals_retained"] is True
        assert ev["DIIS_residual_mandatory"] is False
        assert ev["inactive_DIIS_residual_retained"] is True

    # DEF-S2-03: Converged pre-TRAH Cycle 50 (RMS-DP <= 5e-9, MAX-DP <= 1e-7) with consecutive
    # unseparated pre-TRAH rows MUST PASS even when SCF CONVERGENCE summary retains stale density buffer rows.
    stale_summary_converged_pre_trah = make_trah_iter0(
        energy_str="-76.434622047990",
        energy_change="-7.6435e+01",
        extra_pre_trah_rows=(
            "   49    -76.4346220475000000     1.20e-09  5.40e-09  1.03e-07  4.20e-07     0.5\n"
            "   50    -76.4346220474030000    -9.70e-11  8.09e-10  1.84e-08  2.39e-07     0.5\n"
        ),
        summary_max_dp="1.0300e-07",
        summary_rms_dp="5.4000e-09",
    )
    stale_ev = observe_scf_numerical_profile(stale_summary_converged_pre_trah)
    assert stale_ev["passed"] is True, stale_ev["failures"]
    assert stale_ev["final_active_converger"] == "TRAH-SCF"
    assert stale_ev["trah_iter0_energy_change_uninitialized"] is True
    assert stale_ev["density_residuals_mandatory"] is False
    assert stale_ev["inactive_density_residuals_retained"] is True

    # DEF-S2-03 fail-closed: If last pre-TRAH row exceeds RMS-DP (> 5e-9) or MAX-DP (> 1e-7),
    # MUST FAIL CLOSED even when SCF CONVERGENCE summary rows look achieved.
    for bad_rms, bad_max in [("5.40e-09", "1.84e-08"), ("8.09e-10", "1.03e-07"), ("2.55e-02", "6.31e-01")]:
        bad_pre_trah = make_trah_iter0(
            energy_str="-76.434622047403",
            extra_pre_trah_rows=(
                "   49    -76.4346220474000000     1.00e-11  1.00e-10  1.00e-09  1.00e-09     0.5\n"
                f"   50    -76.4346220474030000    -3.00e-12  {bad_rms}  {bad_max}  2.39e-07     0.5\n"
            ),
            summary_max_dp="1.7468e-09",
            summary_rms_dp="1.7473e-10",
        )
        bad_pre_ev = observe_scf_numerical_profile(bad_pre_trah)
        assert bad_pre_ev["passed"] is False
        assert bad_pre_ev["trah_iter0_energy_change_uninitialized"] is False
        assert "active final criterion not achieved: Energy change" in bad_pre_ev["failures"]

    # Without pre-TRAH rows, unachieved summary MAX-Density or RMS-Density MUST FAIL CLOSED.
    for kwargs in [{"summary_max_dp": "6.3142e-01"}, {"summary_rms_dp": "2.5480e-02"}]:
        no_rows_bad = make_trah_iter0(strip_pre_trah_rows=True, **kwargs)
        no_rows_ev = observe_scf_numerical_profile(no_rows_bad)
        assert no_rows_ev["passed"] is False
        assert no_rows_ev["trah_iter0_energy_change_uninitialized"] is False
        assert "active final criterion not achieved: Energy change" in no_rows_ev["failures"]

    # Bad Orbital Gradient must still FAIL even when trah_iter0_uninit holds.
    valid_iter0 = make_trah_iter0()
    bad_grad_raw = re.sub(r"(Last Orbital Gradient\s*\.\.\.\s*)\S+", r"\g<1>5.0000e-04", valid_iter0)
    bad_grad_ev = observe_scf_numerical_profile(bad_grad_raw)
    assert bad_grad_ev["passed"] is False
    assert bad_grad_ev["trah_iter0_energy_change_uninitialized"] is True
    assert "active final criterion not achieved: Orbital Gradient" in bad_grad_ev["failures"]

    # Nonzero Orbital Rotation (even within 1e-5 tolerance) disqualifies Iter-0 uninitialized bypass
    nonzero_rot = make_trah_iter0(rotation="4.4137e-10")
    nonzero_rot_ev = observe_scf_numerical_profile(nonzero_rot)
    assert nonzero_rot_ev["passed"] is False
    assert nonzero_rot_ev["trah_iter0_energy_change_uninitialized"] is False
    assert "active final criterion not achieved: Energy change" in nonzero_rot_ev["failures"]

    # Real non-sentinel Energy change fails sentinel check and fails Energy change criterion
    real_ec = make_trah_iter0(energy_change="-5.0000e-09")
    real_ec_ev = observe_scf_numerical_profile(real_ec)
    assert real_ec_ev["passed"] is False
    assert real_ec_ev["trah_iter0_energy_change_uninitialized"] is False
    assert "active final criterion not achieved: Energy change" in real_ec_ev["failures"]

    # Large energy discontinuity |E_trah0 - E_last_pre_trah| > 1e-6 disqualifies Iter-0 bypass
    jumped = make_trah_iter0(energy_str="-76.430000000000", energy_change="-7.6430e+01")
    jumped_ev = observe_scf_numerical_profile(jumped)
    assert jumped_ev["passed"] is False
    assert jumped_ev["trah_iter0_energy_change_uninitialized"] is False
    assert "active final criterion not achieved: Energy change" in jumped_ev["failures"]


def test_orca_input_cosx_tight_grid_preserves_frozen_default_and_emits_intaccx():
    """cosx_tight_grid=False stays byte-for-byte frozen; True emits IntAccX 6,6,7 only for RIJCOSX."""
    molecule, method, resources = system(MAPPING_V42)
    for operation in ("optimize", "gradient"):
        assert _orca_input(molecule, method, resources, operation) == actual_text(
            "predeclared-intervention-" + operation + ".inp"
        )
        assert _orca_input(molecule, method, resources, operation, cosx_tight_grid=False) == actual_text(
            "predeclared-intervention-" + operation + ".inp"
        )
        tight = _orca_input(molecule, method, resources, operation, cosx_tight_grid=True)
        assert "%method\n  IntAccX 6,6,7\nend\n" in tight
        assert SCF_BLOCK in tight
        assert "TightSCF DEFGRID3" in tight
        assert "RIJCOSX" in tight
        if operation == "optimize":
            assert "  EnforceStrictConvergence true\n" in tight

    # Merges into %method block when strict_vpt2 already emits Z_Tol 1e-14.
    strict_b3lyp = MethodSpec(
        engine="orca", method="B3LYP", basis="def2-TZVPP", dispersion="D4",
        engine_version="6.1.1", profile_id="orca-vpt2-reference-v1",
    )
    strict_tight = _orca_input(molecule, strict_b3lyp, resources, "optimize", cosx_tight_grid=True)
    assert "%method\n  Z_Tol 1e-14\n  IntAccX 6,6,7\nend\n" in strict_tight
    assert strict_tight.count("%method") == 1

    # Non-RIJCOSX methods never emit IntAccX 6,6,7.
    for non_cosx in (
        MethodSpec(engine="orca", method="HF", basis="def2-TZVPP", engine_version="6.1.1", profile_id=MAPPING_V42),
        MethodSpec(engine="orca", method="r2SCAN-3c", engine_version="6.1.1", profile_id=MAPPING_V42),
    ):
        deck = _orca_input(molecule, non_cosx, resources, "optimize", cosx_tight_grid=True)
        assert "RIJCOSX" not in deck
        assert "IntAccX" not in deck


def _write_engrad(path: Path, molecule: Molecule, energy: float, gradient: list[list[float]]) -> None:
    bohr_angstrom = physical_constants["Bohr radius"][0] * 1e10
    atomic_numbers = {"H": 1, "O": 8}
    lines = ["# Number of atoms", str(len(molecule.symbols)), "# Energy", f"{energy:.12f}", "# Gradient"]
    for row in gradient:
        for val in row:
            lines.append(f"{val:.12f}")
    lines.append("# Coordinates (Bohr)")
    for sym, xyz in zip(molecule.symbols, molecule.coordinates, strict=True):
        bohr = [v / bohr_angstrom for v in xyz]
        lines.append(f"{atomic_numbers[sym]} {bohr[0]:.12f} {bohr[1]:.12f} {bohr[2]:.12f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_run_engine_cosx_grid_retry_recovers_with_intermediate_geometry_and_propagates_to_final_gradient(tmp_path):
    """DEF-S2-01: RIJCOSX SCF failure triggers one IntAccX 6,6,7 retry from job.xyz and propagates to final-gradient."""
    molecule, base_method, base_resources = system(MAPPING_V42)
    method = base_method.model_copy(update={"method": "wB97M-V"})
    resources = base_resources.model_copy(update={"threads": 1})

    intermediate = molecule.model_copy(
        update={"coordinates": [[0.14, -0.04, 0.075], [1.11, 0.12, 0.197], [-0.19, 0.90, -0.11]]}
    )
    converged_mol = molecule.model_copy(
        update={
            "coordinates": [
                [0.15465705908082, -0.00643520581313, 0.07158475859768],
                [1.09861316185156, 0.1127729129331, 0.19484782584268],
                [-0.18327022093238, 0.87366229288002, -0.10643258444036],
            ]
        }
    )
    opt_stdout = actual_text("positive-optimization.stdout")
    grad_stdout = actual_text("positive-cold.stdout")
    grad_values = [
        [-0.000000128, -0.000000112, 0.000000108],
        [-0.000000076, -0.000000115, 0.000000065],
        [0.000000204, 0.000000228, -0.000000173],
    ]
    recorded_jobs: list[tuple[str, str]] = []

    def contract_runner(command, folder, res, *, log_prefix="engine", **kwargs):
        work = Path(folder)
        stdout = work / f"{log_prefix}.stdout"
        stderr = work / f"{log_prefix}.stderr"
        stderr.write_text("", encoding="utf-8")
        if command[-1] == "version.inp":
            stdout.write_text(
                "Program Version 6.1.1  -  RELEASE   -\n"
                "SCF CONVERGED AFTER 1 CYCLES\n"
                "FINAL SINGLE POINT ENERGY -2.807783957535\n"
                "ORCA TERMINATED NORMALLY\n",
                encoding="utf-8",
            )
            return ProcessResult(command, "completed", 0, 0.01, 1.0, str(stdout), str(stderr), None)

        deck = (work / "job.inp").read_text(encoding="utf-8")
        recorded_jobs.append((work.name, deck))
        if work.name == "attempt":
            write_xyz(intermediate, work / "job.xyz")
            stdout.write_text(
                "Program Version 6.1.1  -  RELEASE   -\n"
                "This wavefunction IS NOT CONVERGED!\n"
                "SCF NOT CONVERGED AFTER 124 CYCLES\n",
                encoding="utf-8",
            )
            return ProcessResult(command, "failed", 64, 0.02, 1.0, str(stdout), str(stderr), "engine process exited with code 64")
        if work.name == "cosx-grid-retry":
            write_xyz(converged_mol, work / "job.xyz")
            stdout.write_text(opt_stdout, encoding="utf-8")
            return ProcessResult(command, "completed", 0, 0.02, 1.0, str(stdout), str(stderr), None)
        if work.name == "final-gradient":
            _write_engrad(work / "job.engrad", converged_mol, -76.434622970034, grad_values)
            stdout.write_text(grad_stdout, encoding="utf-8")
            return ProcessResult(command, "completed", 0, 0.02, 1.0, str(stdout), str(stderr), None)
        raise AssertionError(f"Unexpected stage directory: {work}")

    result = run_engine(
        molecule, method, resources, tmp_path / "attempt", operation="optimize",
        executable=sys.executable, process_runner=contract_runner,
    )
    assert result.status == "completed", result.diagnostics
    assert result.converged is True
    assert [stage for stage, _ in recorded_jobs] == ["attempt", "cosx-grid-retry", "final-gradient"]

    initial_deck, retry_deck, grad_deck = (deck for _, deck in recorded_jobs)
    assert "IntAccX 6,6,7" not in initial_deck
    for deck in (retry_deck, grad_deck):
        assert "%method\n  IntAccX 6,6,7\nend\n" in deck
        assert SCF_BLOCK in deck
        assert "TightSCF DEFGRID3" in deck
        assert "RIJCOSX" in deck
    assert "  EnforceStrictConvergence true\n" in retry_deck
    # Retry started from intermediate job.xyz, not initial unoptimized coordinates.
    assert "O 0.14 -0.04 0.075\n" in retry_deck
    assert "O 0.12 -0.1 0.08\n" not in retry_deck

    assert result.metadata["cosx_grid_recovery"] == {
        "triggered": True,
        "intaccx": "6,6,7",
        "reason": "SCF NOT CONVERGED under default RIJCOSX grid",
    }
    assert result.metadata["final_gradient_verification"]["directory"] == "cosx-grid-retry/final-gradient"
    assert result.metadata["dipole_provenance"]["raw_output"] == "cosx-grid-retry/final-gradient/engine.stdout"
    verify_numerical_profile_receipt(
        MAPPING_V42,
        result.metadata,
        result.diagnostics,
        Path(result.diagnostics["process"]["stdout_path"]).read_text(encoding="utf-8"),
    )
    artifact_rel = {Path(a.path).relative_to(tmp_path / "attempt").as_posix() for a in result.artifacts}
    assert {"job.inp", "engine.stdout", "cosx-grid-retry/job.inp", "cosx-grid-retry/final-gradient/job.inp"}.issubset(artifact_rel)


def test_run_engine_cosx_grid_retry_falls_back_on_bad_xyz_bounds_retries_and_skips_ineligible_failures(tmp_path):
    """COSX retry falls back to input geometry on corrupt job.xyz, tries at most once, and skips non-RIJCOSX/non-SCF failures."""
    molecule, base_method, base_resources = system(MAPPING_V42)
    wb97m = base_method.model_copy(update={"method": "wB97M-V"})
    resources = base_resources.model_copy(update={"threads": 1})

    # 1. Corrupt job.xyz falls back to original molecule, and second SCF failure fails closed (no infinite loop).
    retry_decks: list[tuple[str, str]] = []

    def persistent_scf_failure(command, folder, res, *, log_prefix="engine", **kwargs):
        work = Path(folder)
        stdout = work / f"{log_prefix}.stdout"
        stderr = work / f"{log_prefix}.stderr"
        stderr.write_text("", encoding="utf-8")
        if command[-1] == "version.inp":
            stdout.write_text(
                "Program Version 6.1.1\nSCF CONVERGED AFTER 1 CYCLES\n"
                "FINAL SINGLE POINT ENERGY -2.8\nORCA TERMINATED NORMALLY\n",
                encoding="utf-8",
            )
            return ProcessResult(command, "completed", 0, 0.01, 1.0, str(stdout), str(stderr), None)
        retry_decks.append((work.name, (work / "job.inp").read_text(encoding="utf-8")))
        if work.name == "twice":
            (work / "job.xyz").write_text("3\ncorrupt\nC 0 0 0\nH 1 0 0\nH 0 1 0\n", encoding="utf-8")
        stdout.write_text("Program Version 6.1.1\nSCF CONVERGENCE FAILURE\n", encoding="utf-8")
        return ProcessResult(command, "failed", 64, 0.01, 1.0, str(stdout), str(stderr), "scf failed")

    failed_twice = run_engine(
        molecule, wb97m, resources, tmp_path / "twice", operation="optimize",
        executable=sys.executable, process_runner=persistent_scf_failure,
    )
    assert failed_twice.status == "failed" and failed_twice.converged is not True
    assert [name for name, _ in retry_decks] == ["twice", "cosx-grid-retry"]
    assert "O 0.12 -0.1 0.08\n" in retry_decks[1][1]
    assert "%method\n  IntAccX 6,6,7\nend\n" in retry_decks[1][1]
    assert failed_twice.metadata["cosx_grid_recovery"]["triggered"] is True
    assert not (tmp_path / "twice" / "cosx-grid-retry" / "cosx-grid-retry").exists()

    # 2. Non-SCF failure on wB97M-V does NOT trigger cosx-grid-retry.
    non_scf_calls: list[str] = []

    def non_scf_failure(command, folder, res, *, log_prefix="engine", **kwargs):
        work = Path(folder)
        stdout = work / f"{log_prefix}.stdout"
        stderr = work / f"{log_prefix}.stderr"
        stderr.write_text("", encoding="utf-8")
        if command[-1] == "version.inp":
            stdout.write_text(
                "Program Version 6.1.1\nSCF CONVERGED AFTER 1 CYCLES\n"
                "FINAL SINGLE POINT ENERGY -2.8\nORCA TERMINATED NORMALLY\n",
                encoding="utf-8",
            )
            return ProcessResult(command, "completed", 0, 0.01, 1.0, str(stdout), str(stderr), None)
        non_scf_calls.append(work.name)
        stdout.write_text("Program Version 6.1.1\nABORTING THE RUN: basis set error\n", encoding="utf-8")
        return ProcessResult(command, "failed", 2, 0.01, 1.0, str(stdout), str(stderr), "basis error")

    non_scf_res = run_engine(
        molecule, wb97m, resources, tmp_path / "nonscf", operation="energy",
        executable=sys.executable, process_runner=non_scf_failure,
    )
    assert non_scf_res.status == "failed"
    assert non_scf_calls == ["nonscf"]
    assert "cosx_grid_recovery" not in non_scf_res.metadata

    # 3. Exit-0 ORCA output with SCF NOT CONVERGED also triggers cosx-grid-retry and recovers cleanly on energy.
    energy_stdout = actual_text("positive-cold.stdout")
    exit0_calls: list[str] = []

    def exit0_scf_recovery(command, folder, res, *, log_prefix="engine", **kwargs):
        work = Path(folder)
        stdout = work / f"{log_prefix}.stdout"
        stderr = work / f"{log_prefix}.stderr"
        stderr.write_text("", encoding="utf-8")
        if command[-1] == "version.inp":
            stdout.write_text(
                "Program Version 6.1.1\nSCF CONVERGED AFTER 1 CYCLES\n"
                "FINAL SINGLE POINT ENERGY -2.8\nORCA TERMINATED NORMALLY\n",
                encoding="utf-8",
            )
            return ProcessResult(command, "completed", 0, 0.01, 1.0, str(stdout), str(stderr), None)
        exit0_calls.append(work.name)
        if work.name == "exit0":
            stdout.write_text(
                "Program Version 6.1.1\nSCF NOT CONVERGED AFTER 124 CYCLES\nORCA TERMINATED NORMALLY\n",
                encoding="utf-8",
            )
            return ProcessResult(command, "completed", 0, 0.01, 1.0, str(stdout), str(stderr), None)
        stdout.write_text(energy_stdout, encoding="utf-8")
        return ProcessResult(command, "completed", 0, 0.01, 1.0, str(stdout), str(stderr), None)

    exit0_res = run_engine(
        molecule, wb97m, resources, tmp_path / "exit0", operation="energy",
        executable=sys.executable, process_runner=exit0_scf_recovery,
    )
    assert exit0_res.status == "completed" and exit0_res.converged is True
    assert exit0_calls == ["exit0", "cosx-grid-retry"]
    assert exit0_res.metadata["cosx_grid_recovery"]["triggered"] is True
    assert exit0_res.metadata["dipole_provenance"]["raw_output"] == "cosx-grid-retry/engine.stdout"

    # 4. Non-RIJCOSX method (r2SCAN-3c) does NOT trigger cosx-grid-retry on SCF failure.
    non_cosx_calls: list[str] = []

    def non_cosx_scf_failure(command, folder, res, *, log_prefix="engine", **kwargs):
        work = Path(folder)
        stdout = work / f"{log_prefix}.stdout"
        stderr = work / f"{log_prefix}.stderr"
        stderr.write_text("", encoding="utf-8")
        if command[-1] == "version.inp":
            stdout.write_text(
                "Program Version 6.1.1\nSCF CONVERGED AFTER 1 CYCLES\n"
                "FINAL SINGLE POINT ENERGY -2.8\nORCA TERMINATED NORMALLY\n",
                encoding="utf-8",
            )
            return ProcessResult(command, "completed", 0, 0.01, 1.0, str(stdout), str(stderr), None)
        non_cosx_calls.append(work.name)
        stdout.write_text("Program Version 6.1.1\nSCF NOT CONVERGED AFTER 124 CYCLES\n", encoding="utf-8")
        return ProcessResult(command, "failed", 64, 0.01, 1.0, str(stdout), str(stderr), "scf failed")

    r2scan = MethodSpec(engine="orca", method="r2SCAN-3c", engine_version="6.1.1", profile_id=MAPPING_V42)
    non_cosx_res = run_engine(
        molecule, r2scan, resources, tmp_path / "r2scan", operation="optimize",
        executable=sys.executable, process_runner=non_cosx_scf_failure,
    )
    assert non_cosx_res.status == "failed"
    assert non_cosx_calls == ["r2scan"]
    assert "cosx_grid_recovery" not in non_cosx_res.metadata

    # 3. Cancelled after initial SCF failure does NOT launch cosx-grid-retry.
    cancel = Event()
    cancel_calls: list[str] = []

    def cancel_after_initial(command, folder, res, *, log_prefix="engine", **kwargs):
        work = Path(folder)
        stdout = work / f"{log_prefix}.stdout"
        stderr = work / f"{log_prefix}.stderr"
        stderr.write_text("", encoding="utf-8")
        if command[-1] == "version.inp":
            stdout.write_text(
                "Program Version 6.1.1\nSCF CONVERGED AFTER 1 CYCLES\n"
                "FINAL SINGLE POINT ENERGY -2.8\nORCA TERMINATED NORMALLY\n",
                encoding="utf-8",
            )
            return ProcessResult(command, "completed", 0, 0.01, 1.0, str(stdout), str(stderr), None)
        cancel_calls.append(work.name)
        cancel.set()
        stdout.write_text("Program Version 6.1.1\nSCF NOT CONVERGED AFTER 124 CYCLES\n", encoding="utf-8")
        return ProcessResult(command, "failed", 64, 0.01, 1.0, str(stdout), str(stderr), "scf failed")

    cancelled_res = run_engine(
        molecule, wb97m, resources, tmp_path / "cancelled", operation="energy",
        cancel_event=cancel, executable=sys.executable, process_runner=cancel_after_initial,
    )
    assert cancelled_res.status == "failed"
    assert cancel_calls == ["cancelled"]
    assert "cosx_grid_recovery" not in cancelled_res.metadata
