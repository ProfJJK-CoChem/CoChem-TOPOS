"""Exact-build empirical CFOUR EFG operator authority, separate from accuracy.

No user protocol can select this profile. A compiled inventory/program identity
must agree with BASE's complete pre/post process authority and retained raw
bytes. The directly calibrated density is RHF; applying the same operator to
the separately attributed CCSD(T) density is an explicitly labeled inference.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import Molecule
from .storage import IntegrityError, confined_file, digest_json, file_digest, read_json

_INVENTORY = "e9a59cfcaeed3df210d8276b7d3055aed68ba082b2dbc31e826b8eafebd4e286"
_XPROPS = "53d4040eedbc7616cf62732b49c2e2ef14aa157d1122b6d029a87afb1c7cf72b"
_PROFILE = {
    "schema": "topos-cfour-efg-empirical-operator/1",
    "profile_id": "cfour-2.1-xprops-53d4040e-traceless-au-empirical-v1",
    "native_version": "2.1", "mode": "packaged",
    "runtime_inventory_sha256": _INVENTORY, "xprops_sha256": _XPROPS, "xprops_size_bytes": 113368,
    "native_units": "atomic-unit-electric-field-gradient",
    "tensor_convention": "traceless-electrostatic-potential-Hessian",
    "contribution_scope": "total-electronic-and-other-nuclear",
    "protocol_scope": "CFOUR 2.1 CCSD(T) FIRST_ORDER, all electrons correlated, spherical cc-pVTZ, neutral closed-shell vacuum; exact native grammar and density attribution required",
    "direct_evidence": "Independent RHF/cc-pVTZ water calculation; all 27 native SCF EFG components agree below the prospective 1e-7 au threshold",
    "correlated_operator_scope": "Inferred same-xprops operator convention for its separately identified CCSD(T) density; not an independent CCSD(T) accuracy benchmark",
    "original_artifact_zip_sha256": "8bc69a26f4be4e132fcdd2ac28fba09dd4217d7e210df5e3cd1efe64bae913eb",
    "empirical_producer_receipt_sha256": "761ec90e63a2a3ee125ff238d97823872e8a7ef8f16eee87dc16c5116e45536d",
    "independent_empirical_review_sha256": "b56d554d4054eb35e5401e719b060735fd1d913f6c47e4e69f698f423993eda6",
    "independent_native_runtime_review_sha256": "ac822f283e040d370065f4a1083571175e6bdd5aa8e89c68544c575f32b35969",
    "public_operator_source": "https://github.com/pyscf/properties/blob/4eee5a430fb47eca5962f36fdcaf75c2b87e7ede/pyscf/prop/efg/rhf.py",
    "public_operator_source_sha256": "cb79741703b4174dcdaa1b661953c38eb51dde6eeb82da0d5203b9647180ffd5",
    "electronic_structure_accuracy_certified": False,
    "nuclear_data_certified": False, "native_execution_or_full_row_certified_by_profile": False,
}
_MINT = object()


class CfourOperatorAuthority:
    """Internal verified receipt context; a JSON assertion cannot construct it."""

    __slots__ = ("_payload", "_source_efg")

    def __init__(self, payload: dict, *, _mint: object, _source_efg: dict | None = None):
        if _mint is not _MINT:
            raise IntegrityError("CFOUR operator authority requires verified raw process receipt context")
        object.__setattr__(self, "_payload", json.dumps(payload, sort_keys=True, separators=(",", ":")))
        object.__setattr__(self, "_source_efg", json.dumps(_source_efg, sort_keys=True, separators=(",", ":")))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Verified CFOUR operator context is immutable")

    def metadata(self) -> dict:
        return json.loads(self._payload)

    def source_observation(self) -> dict:
        return json.loads(self._source_efg)


def _runtime_fingerprint(value: Any, authority: dict) -> dict:
    if (not isinstance(value, dict)
            or set(value) != {"schema", "runtime_authority", "mode", "native_version", "runtime_inventory_sha256", "xprops"}
            or value["schema"] != "topos-cfour-property-runtime/1"
            or value["runtime_authority"] != authority
            or not isinstance(value["xprops"], dict)
            or set(value["xprops"]) != {"path", "sha256", "bytes"}
            or not Path(str(value["xprops"]["path"])).is_absolute()
            or Path(value["xprops"]["path"]) != Path(authority["executable"]).parent / "xprops"
            or not re.fullmatch(r"[a-f0-9]{64}", str(value["xprops"]["sha256"]))
            or type(value["xprops"]["bytes"]) is not int or value["xprops"]["bytes"] < 1):
        raise IntegrityError("CFOUR property fingerprint contradicts complete runtime authority")
    return value


def _compiled_profile_matches(fingerprint: dict) -> bool:
    return (fingerprint["mode"] == _PROFILE["mode"]
            and fingerprint["native_version"] == _PROFILE["native_version"]
            and fingerprint["runtime_inventory_sha256"] == _INVENTORY
            and fingerprint["xprops"]["sha256"] == _XPROPS
            and fingerprint["xprops"]["bytes"] == _PROFILE["xprops_size_bytes"])


def property_operator_authority(folder: Path, artifact_paths: list[Path], authority: dict,
                                molecule: Molecule, protocol_data: dict,
                                *, current_property_runtime: dict | None = None) -> CfourOperatorAuthority | None:
    """Recheck the raw property receipt after complete runtime/evidence validation.

    Historical receipts lacking property fingerprints remain conditional.
    The caller additionally verifies the complete artifact inventory, original
    launch binding and controlled GENBAS omission policy. This helper does not
    claim that unsigned metadata alone establishes native execution.
    """
    folder = folder.absolute()
    paths = [path.absolute() for path in artifact_paths]
    receipts = [path for path in paths if path.name == "engine-cfour-runtime.json"]
    if not receipts:
        return None
    outputs = [path for path in paths if path.name == "engine.stdout"]
    if len(receipts) != 1 or len(outputs) != 1 or receipts[0].parent != outputs[0].parent:
        raise IntegrityError("A property operator requires one exact adjacent native process receipt")
    adjacent = {}
    for name in ("engine-cfour-runtime.json", "engine.stdout", "engine.stderr", "ZMAT"):
        expected = outputs[0].parent / name
        if paths.count(expected) != 1:
            raise IntegrityError("CFOUR property operator context lacks unique hash-bound raw evidence")
        try:
            adjacent[name] = confined_file(folder, expected.relative_to(folder).as_posix())
        except ValueError as exc:
            raise IntegrityError("CFOUR operator context escapes its component") from exc
    binding = read_json(adjacent["engine-cfour-runtime.json"])
    before, after = binding.get("property_runtime_before"), binding.get("property_runtime_after")
    if before is None and after is None:
        return None
    if (not isinstance(authority, dict)
            or not re.fullmatch(r"[a-f0-9]{64}", str(authority.get("runtime_seal_sha256", "")))
            or not re.fullmatch(r"[a-f0-9]{64}", str(authority.get("binary_sha256", "")))
            or not Path(str(authority.get("executable", ""))).is_absolute()
            or binding.get("schema") != "topos-cfour-runtime-integrity/1"
            or binding.get("status") != "verified" or binding.get("reason") is not None
            or binding.get("runtime_before") != authority or binding.get("runtime_after") != authority
            or binding.get("command") != [authority["executable"]]
            or binding.get("stdout_name") != "engine.stdout" or binding.get("stderr_name") != "engine.stderr"
            or binding.get("stdout_sha256") != file_digest(adjacent["engine.stdout"])
            or binding.get("stderr_sha256") != file_digest(adjacent["engine.stderr"])
            or binding.get("native_inputs_sha256", {}).get("ZMAT") != file_digest(adjacent["ZMAT"])
            or not re.search(r"\bPROPS\s*=\s*FIRST_ORDER\b", adjacent["ZMAT"].read_text(encoding="utf-8"), re.I)):
        raise IntegrityError("CFOUR operator receipt differs from complete authority or exact raw property input/output")
    fingerprint = _runtime_fingerprint(before, authority)
    if after != fingerprint:
        raise IntegrityError("CFOUR property program changed between pre/post complete authorization")
    if current_property_runtime is not None and current_property_runtime != fingerprint:
        raise IntegrityError("Retained property operator differs from fresh complete BASE authorization")
    if not _compiled_profile_matches(fingerprint):
        return None
    if (protocol_data.get("engine") != "cfour" or protocol_data.get("engine_version") != "2.1"
            or protocol_data.get("operation") != "first-order-properties" or protocol_data.get("method") != "CCSD(T)"
            or protocol_data.get("orbital_basis") not in {"cc-pVTZ", "PVTZ"}
            or protocol_data.get("frozen_core") is not False
            or molecule.charge != 0 or molecule.multiplicity != 1
            or molecule.environment not in ({}, {"phase": "gas"})):
        return None
    from .external_engines import ExternalProtocol, parse_cfour_output

    for name in ("DIPOL", "EFG"):
        expected = outputs[0].parent / name
        if paths.count(expected) != 1:
            raise IntegrityError("Admitted CFOUR operator requires each complete correlated raw property artifact")
        adjacent[name] = confined_file(folder, expected.relative_to(folder).as_posix())
    parsed = parse_cfour_output(adjacent["engine.stdout"].read_bytes().decode("utf-8"), molecule,
        ExternalProtocol.model_validate(protocol_data), dipol=adjacent["DIPOL"].read_bytes().decode("utf-8"),
        efg=adjacent["EFG"].read_bytes().decode("utf-8"))
    payload = {"compiled_profile": _PROFILE, "runtime_fingerprint": fingerprint,
               "input_molecule_sha256": digest_json(molecule.model_dump(mode="json")),
               "raw_stdout_sha256": binding["stdout_sha256"],
               "raw_parsed_efg_sha256": digest_json(parsed["efg_observation"]),
               "raw_process_receipt_sha256": file_digest(adjacent["engine-cfour-runtime.json"]),
               "profile_scope": "Empirical direct RHF operator conformance; correlated same-build operator inference only"}
    return CfourOperatorAuthority(payload, _mint=_MINT, _source_efg=parsed["efg_observation"])


def apply_operator_authority(efg: dict, context: CfourOperatorAuthority | None) -> dict:
    """Annotate authentic acquisition; never accept a public dictionary flag."""
    if context is None:
        return efg
    if not isinstance(context, CfourOperatorAuthority):
        raise IntegrityError("CFOUR operator context is not a verified internal raw receipt context")
    evidence = context.metadata()
    if efg.get("raw_artifacts_sha256", {}).get("engine.stdout") != evidence["raw_stdout_sha256"]:
        raise IntegrityError("CFOUR operator context is bound to different raw stdout")
    if efg.get("density_provenance", {}).get("method") != "CCSD(T)":
        raise IntegrityError("CFOUR operator profile differs from the parsed engine/density grammar")
    source = context.source_observation()
    candidate = dict(efg)
    for key in ("runtime_operator_evidence", "native_engine_version"):
        candidate.pop(key, None)
    for key in ("units", "native_unit_sign_independently_verified", "unit_sign_authority", "scope"):
        candidate[key] = source[key]
    if digest_json(candidate) != evidence["raw_parsed_efg_sha256"]:
        raise IntegrityError("CFOUR operator observation changed its freshly parsed raw tensor, indexed frame or density evidence")
    result = dict(efg)
    result.update(units=_PROFILE["native_units"], native_unit_sign_independently_verified=True,
                  native_engine_version="2.1",
                  runtime_operator_evidence=evidence,
                  unit_sign_authority="Compiled exact-build empirical RHF conformance; correlated same-xprops operator inference",
                  scope="Correlated indexed EFG; exact-build operator convention inferred from independently checked RHF conformance; no correlated accuracy certification")
    return result


def validate_operator_observation(efg: dict, context: CfourOperatorAuthority | None, molecule: Molecule) -> bool:
    """Only freshly derived receipt context can authorize nuclear conversion."""
    if context is None:
        return False
    if not isinstance(context, CfourOperatorAuthority):
        raise IntegrityError("CFOUR operator context is not a verified internal raw receipt context")
    if context.metadata()["input_molecule_sha256"] != digest_json(molecule.model_dump(mode="json")):
        raise IntegrityError("CFOUR operator context is bound to different indexed molecule, isotopes or geometry")
    verified = apply_operator_authority(efg, context)
    if any(efg.get(key) != verified.get(key) for key in (
            "units", "native_unit_sign_independently_verified", "runtime_operator_evidence", "unit_sign_authority",
            "scope", "native_engine_version")):
        raise IntegrityError("CFOUR operator observation differs from its freshly derived receipt authority")
    return True
