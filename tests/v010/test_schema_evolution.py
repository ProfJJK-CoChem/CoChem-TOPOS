"""Optional reader defaults must not corrupt prior immutable snapshots."""
import pytest

import topos.storage as storage
from topos.models import Molecule, RunRecord, RunRequest
from topos.storage import IntegrityError, RunStore, digest_json


def test_new_optional_request_defaults_preserve_old_document_identity(tmp_path, monkeypatch):
    record = RunRecord(request=RunRequest(molecule=Molecule(symbols=["He"], coordinates=[[0, 0, 0]])))
    record.metadata["request_sha256"] = digest_json({k: v for k, v in record.request.model_dump(mode="json").items()
                                                    if k != "dipole_method_error_debye"})
    canonical = storage.record_dict

    def older_writer(value):
        result = canonical(value)
        result["request"].pop("dipole_method_error_debye", None)
        return result

    store = RunStore(tmp_path / record.run_id)
    # Emulate the prior schema writer, not damaged data with mismatched hashes.
    with monkeypatch.context() as old:
        old.setattr(storage, "record_dict", older_writer)
        before = store.commit(record)
    document = store.load()
    assert "dipole_method_error_debye" not in document["request"]
    assert digest_json(document) == before["record_sha256"]
    assert store.verify() == before
    restored = RunRecord.model_validate(document)
    assert restored.request.dipole_method_error_debye is None
    restored.status = "unavailable"
    store.commit(restored)
    assert store.load()["request"] == document["request"]
    assert store.load()["metadata"]["request_sha256"] == digest_json(document["request"])
    restored.request.dipole_method_error_debye = 0.1
    with pytest.raises(IntegrityError, match="Immutable input/request"):
        store.commit(restored)
