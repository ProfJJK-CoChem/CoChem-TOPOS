"""Real failed RunStore export guards; no calculation or scientific success."""

from __future__ import annotations

import pytest

from topos.models import Artifact, Attempt, Molecule, RunRecord, RunRequest
from topos.publication import export_bundle
from topos.storage import IntegrityError, RunStore, file_digest


@pytest.mark.parametrize(
    "name,engine",
    [
        ("GENBAS", "cfour"),
        ("ECPDATA", "cfour"),
        ("GENBAS", "infrastructure"),
        ("engine.stdout", "cfour"),
    ],
)
def test_publication_rejects_unqualified_cfour_snapshot_before_any_copy(
    tmp_path, monkeypatch, name, engine
):
    source = tmp_path / "source"
    source.mkdir()
    path = source / name
    path.write_text("Inert legacy artifact marker; no licensed bytes or scientific result\n")
    record = RunRecord(
        request=RunRequest(molecule=Molecule(symbols=["He"], coordinates=[[0, 0, 0]])),
        status="failed",
    )
    artifact = Artifact(path=name, sha256=file_digest(path), size_bytes=path.stat().st_size)
    if engine == "cfour":
        record.attempts.append(
            Attempt(
                run_id=record.run_id,
                engine="cfour",
                method="HF",
                status="failed",
                artifacts=[artifact],
            )
        )
    else:
        record.artifacts.append(artifact)
    store = RunStore(source)
    original = store.commit(record)
    target = tmp_path / "publication"
    monkeypatch.setattr(
        "topos.publication.shutil.copytree",
        lambda *args, **kwargs: pytest.fail("Unqualified scientific bytes must never be copied"),
    )
    with pytest.raises(IntegrityError, match="Licensed CFOUR|explicit scientific-only"):
        export_bundle(source, target)
    assert store.verify() == original
    assert not target.exists() and not list(tmp_path.glob(".publication.pending-*"))
    assert not list(tmp_path.rglob("snapshot"))
