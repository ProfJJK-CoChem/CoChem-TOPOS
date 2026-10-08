"""Operator policy and transport bookkeeping, never native acceptance.

Native stdout/EFG/DIPOL/ZMAT are unchanged genuine R4 fixtures. Constructed
receipt/authority objects exercise admission/rejection only; no engine is run,
no BASE Stage0 is claimed, and no current native matrix completion is evidence.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from topos.base_integration import BaseIntegrationError, BaseRuntime
from topos.cfour_efg import verify_cfour_property_recovery
from topos.cfour_operator import (
    CfourOperatorAuthority,
    apply_operator_authority,
    property_operator_authority,
)
from topos.cfour_properties import (
    CfourEfgConventionDeclaration,
    NuclearQuadrupoleMoment,
    first_order_quadrupole_output,
)
from topos.external_engines import ExternalProtocol, parse_cfour_output
from topos.models import Molecule
from topos.storage import IntegrityError, atomic_json, file_digest, read_json

FIXTURE = Path(__file__).parent / "fixtures/cfour_first_order_2_1"
XPROPS = "53d4040eedbc7616cf62732b49c2e2ef14aa157d1122b6d029a87afb1c7cf72b"
INVENTORY = "e9a59cfcaeed3df210d8276b7d3055aed68ba082b2dbc31e826b8eafebd4e286"


def molecule():
    rows = (FIXTURE / "native-ZMAT.inp").read_text().splitlines()[1:4]
    return Molecule(symbols=[row.split()[0] for row in rows], isotopes=[16, 2, 2],
                    coordinates=[[float(value) for value in row.split()[1:]] for row in rows])


def protocol(**changes):
    return ExternalProtocol(**(dict(engine="cfour", engine_version="2.1", operation="first-order-properties",
                                  method="CCSD(T)", orbital_basis="PVTZ", frozen_core=False) | changes))


def mathematical_nucleus():
    source = {"citation": "Mathematical nuclear-data declaration only; no measured Q or spin claim",
              "identifier": "urn:topos:mathematical-nuclear-contract-only", "locator": "symbolic example"}
    return NuclearQuadrupoleMoment(atom_id="atom-1", symbol="H", mass_number=2, nuclear_spin_twice=2,
        signed_q_millibarn=2.86, q_reported_uncertainty_millibarn=.02,
        q_reported_uncertainty_policy="Mathematical reported error; no statistical coverage inferred",
        uncertainty_convention="reported-source-uncertainty", spin_source=source, q_source=source,
        q_uncertainty_source=source)


@pytest.fixture
def bookkeeping(tmp_path):
    for name, target in (("output.stdout", "engine.stdout"), ("native-ZMAT.inp", "ZMAT"),
                         ("EFG.out", "EFG"), ("DIPOL.out", "DIPOL")):
        shutil.copyfile(FIXTURE / name, tmp_path / target)
    (tmp_path / "engine.stderr").write_text("")  # Unexecuted transport binding only.
    authority = {"runtime_seal_sha256": "a" * 64, "binary_sha256": "b" * 64,
                 "executable": "/unexecuted-bookkeeping/bin/xcfour", "identity_scope": "Unexecuted policy bookkeeping"}
    fingerprint = {"schema": "topos-cfour-property-runtime/1", "runtime_authority": authority,
                   "mode": "packaged", "native_version": "2.1", "runtime_inventory_sha256": INVENTORY,
                   "xprops": {"path": "/unexecuted-bookkeeping/bin/xprops", "sha256": XPROPS, "bytes": 113368}}
    binding = {"schema": "topos-cfour-runtime-integrity/1", "status": "verified", "reason": None,
               "runtime_before": authority, "runtime_after": authority, "command": [authority["executable"]],
               "workdir": str(tmp_path), "native_inputs_sha256": {"ZMAT": file_digest(tmp_path / "ZMAT"), "GENBAS": "c" * 64},
               "stdout_name": "engine.stdout", "stderr_name": "engine.stderr",
               "stdout_sha256": file_digest(tmp_path / "engine.stdout"), "stderr_sha256": file_digest(tmp_path / "engine.stderr"),
               "property_runtime_before": fingerprint, "property_runtime_after": fingerprint}
    atomic_json(tmp_path / "engine-cfour-runtime.json", binding)
    paths = list(tmp_path.iterdir())
    return tmp_path, paths, authority, fingerprint


def acquisition(folder):
    return parse_cfour_output((folder / "engine.stdout").read_text(), molecule(), protocol(),
                             dipol=(folder / "DIPOL").read_text(), efg=(folder / "EFG").read_text())


def test_bound_compiled_operator_has_reachable_computational_chi_path_without_accuracy_claim(bookkeeping):
    folder, paths, authority, fingerprint = bookkeeping
    context = property_operator_authority(folder, paths, authority, molecule(), protocol().model_dump(),
                                           current_property_runtime=fingerprint)
    raw = acquisition(folder)
    verified = apply_operator_authority(raw["efg_observation"], context)
    chi, missing = first_order_quadrupole_output(molecule(), verified, [mathematical_nucleus()], "rigid-inertial", context)
    assert missing == []  # Computational policy path only, not physical native acceptance.
    assert chi["native_unit_sign_independently_verified"] is True
    assert chi["validity"] == "human-review"
    assert chi["nuclear_data_independently_verified"] is False
    assert chi["native_execution_verified"] is False
    assert chi["full_uncertainty_available"] is False
    assert chi["couplings"][0]["q_only_component_standard_uncertainty_khz"] is None
    profile = chi["runtime_operator_evidence"]["compiled_profile"]
    assert "same-xprops" in profile["correlated_operator_scope"]
    assert profile["electronic_structure_accuracy_certified"] is False
    assert profile["native_execution_or_full_row_certified_by_profile"] is False
    raw["efg_observation"] = verified
    assert verify_cfour_property_recovery(folder, paths, molecule(), protocol().model_dump(), raw, authority) == raw


def test_a_json_flag_or_replayed_profile_dictionary_cannot_authorize_conversion(bookkeeping):
    folder, paths, authority, _ = bookkeeping
    context = property_operator_authority(folder, paths, authority, molecule(), protocol().model_dump())
    verified = apply_operator_authority(acquisition(folder)["efg_observation"], context)
    result, missing = first_order_quadrupole_output(molecule(), json.loads(json.dumps(verified)),
        [mathematical_nucleus()], "requested-cartesian")
    assert result is None
    assert missing
    with pytest.raises(IntegrityError, match="context"):
        apply_operator_authority(verified, context.metadata())
    with pytest.raises(IntegrityError, match="receipt context"):
        CfourOperatorAuthority(context.metadata(), _mint=object())
    with pytest.raises(AttributeError, match="immutable"):
        context._payload = "{}"


@pytest.mark.parametrize("change", ["pre-runtime", "post-runtime", "missing-post", "pre-xprops", "post-xprops",
    "stdout", "stderr", "zmat", "status", "command", "duplicate-receipt", "missing-raw", "changed-current"])
def test_changed_or_incomplete_raw_runtime_context_cannot_activate_profile(bookkeeping, change):
    folder, paths, authority, fingerprint = bookkeeping
    binding = read_json(folder / "engine-cfour-runtime.json")
    current = copy.deepcopy(fingerprint)
    if change == "pre-runtime":
        binding["runtime_before"]["runtime_seal_sha256"] = "d" * 64
    elif change == "post-runtime":
        binding["runtime_after"]["runtime_seal_sha256"] = "d" * 64
    elif change == "missing-post":
        binding.pop("property_runtime_after")
    elif change in {"pre-xprops", "post-xprops"}:
        key = "property_runtime_before" if change == "pre-xprops" else "property_runtime_after"
        binding[key]["xprops"]["sha256"] = "d" * 64
    elif change in {"stdout", "stderr", "zmat"}:
        key = {"stdout": "engine.stdout", "stderr": "engine.stderr", "zmat": "ZMAT"}[change]
        (folder / key).write_bytes((folder / key).read_bytes() + b"Changed bookkeeping bytes\n")
    elif change == "status":
        binding["status"] = "pending-native-completion"
    elif change == "command":
        binding["command"].append("unapproved")
    elif change == "duplicate-receipt":
        paths.append(folder / "engine-cfour-runtime.json")
    elif change == "missing-raw":
        paths.remove(folder / "engine.stderr")
    else:
        current["xprops"]["sha256"] = "d" * 64
    atomic_json(folder / "engine-cfour-runtime.json", binding)
    with pytest.raises(IntegrityError, match="CFOUR|property operator"):
        property_operator_authority(folder, paths, authority, molecule(), protocol().model_dump(),
                                    current_property_runtime=current)


@pytest.mark.parametrize("change", ["unrecognized-inventory", "unrecognized-xprops", "wrong-version", "wrong-mode", "wrong-size", "historical"])
def test_unadmitted_or_historical_complete_context_remains_partial(bookkeeping, change):
    folder, paths, authority, _ = bookkeeping
    binding = read_json(folder / "engine-cfour-runtime.json")
    for key in ("property_runtime_before", "property_runtime_after"):
        if change == "historical":
            binding.pop(key)
        elif change == "unrecognized-inventory":
            binding[key]["runtime_inventory_sha256"] = "d" * 64
        elif change == "unrecognized-xprops":
            binding[key]["xprops"]["sha256"] = "d" * 64
        elif change == "wrong-version":
            binding[key]["native_version"] = "2.2"
        elif change == "wrong-mode":
            binding[key]["mode"] = "local_unsealed"
        else:
            binding[key]["xprops"]["bytes"] += 1
    atomic_json(folder / "engine-cfour-runtime.json", binding)
    assert property_operator_authority(folder, paths, authority, molecule(), protocol().model_dump()) is None


@pytest.mark.parametrize("changes", [{"frozen_core": True}, {"orbital_basis": "PVQZ"}, {"method": "MP2"}])
def test_empirical_profile_is_scoped_to_its_declared_protocol(bookkeeping, changes):
    folder, paths, authority, _ = bookkeeping
    assert property_operator_authority(folder, paths, authority, molecule(), protocol(**changes).model_dump()) is None


@pytest.mark.parametrize("field,value", [("units", "wrong-unit"), ("unit_sign_authority", "fabricated verified authority"),
                                         ("native_unit_sign_independently_verified", False),
                                         ("scope", "fabricated scientific scope"), ("native_engine_version", "99.9")])
def test_scalar_display_assertions_cannot_override_context(bookkeeping, field, value):
    folder, paths, authority, _ = bookkeeping
    context = property_operator_authority(folder, paths, authority, molecule(), protocol().model_dump())
    verified = apply_operator_authority(acquisition(folder)["efg_observation"], context)
    verified[field] = value
    with pytest.raises(IntegrityError, match="freshly derived"):
        first_order_quadrupole_output(molecule(), verified, [mathematical_nucleus()], "requested-cartesian", context)


def test_raw_recovery_rejects_an_operator_profile_when_no_complete_runtime_context_is_supplied(bookkeeping):
    folder, paths, authority, _ = bookkeeping
    context = property_operator_authority(folder, paths, authority, molecule(), protocol().model_dump())
    raw = acquisition(folder)
    raw["efg_observation"] = apply_operator_authority(raw["efg_observation"], context)
    with pytest.raises(IntegrityError, match="fresh parse"):
        verify_cfour_property_recovery(folder, paths, molecule(), protocol().model_dump(), raw)


@pytest.mark.parametrize("change", ["tensor", "atom-order", "density-span", "source-token", "raw-efg-hash", "rotation", "rounding-bound"])
def test_context_binds_the_actual_tensor_atom_frame_density_and_print_evidence(bookkeeping, change):
    folder, paths, authority, _ = bookkeeping
    context = property_operator_authority(folder, paths, authority, molecule(), protocol().model_dump())
    verified = apply_operator_authority(acquisition(folder)["efg_observation"], context)
    if change == "tensor":
        verified["tensors_native_units"][0][0][0] *= -1
    elif change == "atom-order":
        verified["atom_ids"].reverse()
    elif change == "density-span":
        verified["density_provenance"]["density_program_sha256"] = "d" * 64
    elif change == "source-token":
        verified["source_tokens"][0]["xx"] = "1.0000000000"
    elif change == "raw-efg-hash":
        verified["raw_artifacts_sha256"]["EFG"] = "d" * 64
    elif change == "rotation":
        verified["proper_rotation_native_to_requested"][0][0] *= -1
    else:
        verified["component_rounding_bounds_native_units"][0][0][0] *= 1000
    with pytest.raises(IntegrityError, match="freshly parsed raw tensor"):
        first_order_quadrupole_output(molecule(), verified, [mathematical_nucleus()], "requested-cartesian", context)


def test_base_property_fingerprint_comes_from_actual_runtime_verification_not_registry_display(monkeypatch):
    # Pure authorization-transport control; no executable or native output.
    authority = {"runtime_seal_sha256": "a" * 64, "binary_sha256": "b" * 64,
                 "executable": "/unexecuted-bookkeeping/bin/xcfour"}
    authorization = SimpleNamespace(**authority)
    record = {"runtime_seal_sha256": authority["runtime_seal_sha256"], "hash": authority["binary_sha256"],
              "path": authority["executable"], "runtime_metadata": {"helpers": {"xprops": {"sha256": "d" * 64}}}}
    observed = {"runtime_seal_sha256": authority["runtime_seal_sha256"], "executable": authority["executable"],
                "executable_record": {"sha256": authority["binary_sha256"]}, "mode": "packaged", "version": "2.1",
                "runtime_inventory_sha256": INVENTORY, "helpers": {"xprops": {"path": "/unexecuted-bookkeeping/bin/xprops", "sha256": XPROPS, "bytes": 113368}}}
    calls = []
    module = SimpleNamespace(verify_cfour_runtime=lambda executable: calls.append(executable) or observed)
    monkeypatch.setitem(sys.modules, "cochem_base.core_engine.cfour_runtime", module)
    runtime = object.__new__(BaseRuntime)
    runtime.registry_path = Path("/unexecuted-bookkeeping/registry.json")
    runtime.registry = SimpleNamespace(model_dump=lambda **kwargs: {"engines": {"cfour": record}})
    runtime._authorize = lambda *args, **kwargs: authorization
    fingerprint = runtime.cfour_property_runtime_identity()
    assert calls == [authority["executable"]]
    assert fingerprint["xprops"]["sha256"] == XPROPS
    observed["runtime_seal_sha256"] = "d" * 64
    with pytest.raises(BaseIntegrationError, match="complete BASE authority"):
        runtime.cfour_property_runtime_identity()


def test_operator_context_cannot_be_transferred_to_changed_requested_isotopes_or_geometry(bookkeeping):
    folder, paths, authority, _ = bookkeeping
    context = property_operator_authority(folder, paths, authority, molecule(), protocol().model_dump())
    verified = apply_operator_authority(acquisition(folder)["efg_observation"], context)
    for changed in (molecule().model_copy(update={"isotopes": [18, 2, 2]}),
                    molecule().model_copy(update={"coordinates": [[0, 0, 0], [0, 0, 1], [0, 0, -1]]})):
        with pytest.raises(IntegrityError, match="different indexed molecule"):
            first_order_quadrupole_output(changed, verified, [mathematical_nucleus()], "requested-cartesian", context)


def test_unresolved_requested_rigid_axes_leave_computational_coverage_incomplete():
    # Pure mathematical conditional example, not native engine output.
    source = mathematical_nucleus().q_source
    declaration = CfourEfgConventionDeclaration(source=source, reviewed_by="mathematical-test",
        reviewed_at="2026-01-01T00:00:00Z", review_reason="Mathematical degeneracy policy only; no native convention authority")
    linear = Molecule(symbols=["H", "H"], isotopes=[2, 2], coordinates=[[0, 0, -1], [0, 0, 1]])
    efg = {"native_convention_declaration": declaration.model_dump(mode="json"),
           "units": "atomic-unit-electric-field-gradient", "tensors_native_units": [[[0, 0, 0]] * 3] * 2,
           "component_rounding_bounds_native_units": [[[0, 0, 0]] * 3] * 2}
    chi, reasons = first_order_quadrupole_output(linear, efg, [mathematical_nucleus()], "rigid-inertial")
    assert chi["inertial_frame"]["axes_resolved"] is False
    assert chi["inertial_frame"]["couplings"][0]["chi_aa_bb_cc_khz"] is None
    assert any("inertia axes are degenerate" in reason for reason in reasons)
