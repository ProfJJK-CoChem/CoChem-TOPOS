"""Real-filesystem portable identities and scientific-review consumer contracts."""
from __future__ import annotations

import json
from pathlib import PurePosixPath
from types import SimpleNamespace

import pytest

from topos.release import source_inventory
from topos.scientific_references import (
    ReferenceCoverageReview,
    _validate_coverage_ledger,
    reference_ledger_scope,
)
from topos.storage import IntegrityError, digest_json, file_digest


@pytest.mark.parametrize("relative", [
    "topos/scientific.py",
    "tests/v010/fixtures/native/GRD",
    ".github/workflows/acceptance.yml",
    ".docs/patches/native.patch",
])
def test_real_source_inventory_has_portable_relative_keys_and_actual_byte_hashes(tmp_path, relative):
    root = tmp_path / "source with spaces"
    source = root / PurePosixPath(relative)
    source.parent.mkdir(parents=True)
    source.write_bytes(b"actual retained source\r\n")

    inventory = source_inventory(root)

    assert inventory == {relative: file_digest(source)}
    assert all("\\" not in key and not PurePosixPath(key).is_absolute() for key in inventory)
    assert all((root / PurePosixPath(key)).is_file() for key in inventory)


def test_real_reference_consumer_accepts_portable_source_identity_and_rejects_changed_test(tmp_path):
    # Fifty real clause strings and one inert test source exercise source lookup.
    # No native values, quantities, measurements or acceptance pass are supplied.
    root = tmp_path / "reference source"
    test_name = "tests/v010/test_contract.py"
    test_source = root / test_name
    test_source.parent.mkdir(parents=True)
    test_source.write_text("def test_contract():\n    assert True\n", encoding="utf-8")
    clauses = {f"TOPOS-010-{number:03d}": f"**TOPOS-010-{number:03d}.** Inert path-binding contract."
               for number in range(1, 51)}
    srs = root / ".docs/CoChem-TOPOS_SRS.md"
    srs.parent.mkdir(parents=True)
    srs.write_text("\n".join(clauses.values()) + "\n", encoding="utf-8")
    ledger = {"srs_sha256": file_digest(srs), "requirements": {
        name: {"requirement_source": clause, "assessment": "Schema-only contract", "coding_gaps": [],
               "implementation": [], "acceptance_tests": []}
        for name, clause in clauses.items()}}
    ledger["requirements"]["TOPOS-010-019"]["acceptance_tests"] = [
        {"path": test_name, "sha256": file_digest(test_source), "test_functions": ["test_contract"]}]
    retained = tmp_path / "reviewed-ledger.json"
    retained.write_text(json.dumps(ledger), encoding="utf-8")
    review = ReferenceCoverageReview(
        srs_sha256=ledger["srs_sha256"], acceptance_ledger_file=retained.name,
        acceptance_ledger_sha256=file_digest(retained),
        acceptance_ledger_scope_sha256=digest_json(reference_ledger_scope(ledger)),
        reviewer="Path-binding schema test; no chemistry review",
        reviewed_at="2026-01-01T00:00:00+00:00",
        review_rationale="Actual native filesystem source lookup, not a scientific acceptance claim",
        requirements=[{
            "requirement_id": "TOPOS-010-019",
            "requirement_source_sha256": digest_json(clauses["TOPOS-010-019"]),
            "applicability": "non-numerical-contract",
            "requirement_scope": "Portable retained-source identity only",
            "rationale": "POSIX ledger keys must address actual files on every supported host",
            "exclusions": "No numerical chemistry, native execution or release qualification",
            "acceptance_test_references": [test_name + "::test_contract"],
        }],
    )
    declared = SimpleNamespace(requirement_coverage=review)

    assert _validate_coverage_ledger(declared, retained, source_root=root) == ledger

    test_source.write_text("def test_contract():\n    assert False\n", encoding="utf-8")
    with pytest.raises(IntegrityError, match="matching current source identity"):
        _validate_coverage_ledger(declared, retained, source_root=root)
