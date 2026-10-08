"""Actual BASE 1.0.1 producer and TOPOS receiver; no native process execution."""
from __future__ import annotations

import hashlib
import json

import pytest
from cochem_base.interfaces.artifact_handoff import prepare_module_handoff

from topos.base_provider import request_from_handoff
from topos.models import Molecule, RunRequest


def handoff(tmp_path, labels, isotopes):
    molecule = Molecule(symbols=["O", "H", "H"], isotopes=isotopes,
                        coordinates=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], charge=0, multiplicity=1)
    request = RunRequest(molecule=molecule, purpose="energy", engine="xtb", budget_seconds=30).model_dump(mode="json")
    xyz = tmp_path / "source.xyz"
    xyz.write_text("3\nExplicit nuclear labels\n" + "\n".join(f"{label} {' '.join(map(str, xyz))}" for label, xyz in zip(labels, molecule.coordinates, strict=True)) + "\n")
    folder = tmp_path / "handoff"
    prepare_module_handoff("topos", xyz, folder, operation="energy", options={"topos_request": request})
    return folder / "handoff.json"


@pytest.mark.parametrize("labels,isotopes", [(["18O", "D", "H"], [18, 2, None]),
    (["O-18", "2H", "T"], [18, 2, 3]), (["O", "H", "H"], [18, 2, 3]),
    (["O", "H", "H"], [None, None, None])])
def test_raw_labels_and_explicit_request_agree_without_mutating_artifact(tmp_path, labels, isotopes):
    manifest = handoff(tmp_path, labels, isotopes)
    original = {path: path.read_bytes() for path in manifest.parent.iterdir() if path.is_file()}
    request, receipt = request_from_handoff(manifest)
    assert request.molecule.symbols == ["O", "H", "H"]
    assert request.molecule.isotopes == isotopes
    assert request.molecule.charge == 0 and request.molecule.multiplicity == 1
    assert all(path.read_bytes() == content for path, content in original.items())
    assert receipt["artifact_sha256"] == hashlib.sha256(original[manifest.parent / "artifact.xyz"]).hexdigest()
    assert receipt["producer_scientific_execution_performed"] is False


@pytest.mark.parametrize("isotopes", [[None, None, None], [18, 3, None], [16, 2, None]])
def test_explicit_raw_isotope_must_be_declared_identically(tmp_path, isotopes):
    manifest = handoff(tmp_path, ["18O", "D", "H"], isotopes)
    with pytest.raises(ValueError, match="isotope"):
        request_from_handoff(manifest)


@pytest.mark.parametrize("change", ["order", "coordinate", "state", "purpose", "extra-options", "missing-isotopes"])
def test_normalization_never_bypasses_original_request_authority(tmp_path, change):
    manifest = handoff(tmp_path, ["18O", "D", "H"], [18, 2, None])
    value = json.loads(manifest.read_text())
    request = value["options"]["topos_request"]
    if change == "order":
        request["molecule"]["symbols"] = ["H", "O", "H"]
        request["molecule"]["isotopes"] = [2, 18, None]
    elif change == "coordinate":
        request["molecule"]["coordinates"][1][0] = 2
    elif change == "state":
        del request["molecule"]["charge"]
    elif change == "purpose":
        value["operation"] = "gradient"
    elif change == "extra-options":
        value["options"]["ignore_labels"] = True
    else:
        del request["molecule"]["isotopes"]
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        request_from_handoff(manifest)


@pytest.mark.parametrize("label", ["999O", "3D", "Xx", "O:ghost", "[18O]"])
def test_unsupported_nuclear_labels_do_not_create_handoff(tmp_path, label):
    with pytest.raises(ValueError):
        handoff(tmp_path, [label, "H", "H"], [None, None, None])
    assert not (tmp_path / "handoff/handoff.json").exists()
