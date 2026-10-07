"""Release metadata, refusal gates and archive contracts; native install is separate."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from topos.release import release_gate, source_inventory

ROOT = Path(__file__).resolve().parents[2]


def script(name):
    spec = importlib.util.spec_from_file_location(f"topos_release_test_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_wheel(folder, project, payload=None):
    """Inert metadata fixture, never installed or used as chemistry evidence."""
    path = folder / f"{project.replace('-', '_')}-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{project.replace('-', '_')}-0.1.0.dist-info/METADATA", f"Name: {project}\nVersion: 0.1.0\n")
        for name, value in (payload or {}).items():
            archive.writestr(name, value)
    return path


def checksums(folder):
    (folder / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                                               for path in sorted(folder.glob("*.whl"))))


def test_candidate_sources_exclude_binaries_caches_and_base_frontend(tmp_path):
    module = script("build_release")
    for path in ("topos/real.py", "topos/__pycache__/compiled.pyc", "frontend/__init__.py", "engine/orca", ".docs/guide.md"):
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("fixture")
    names = {str(path.relative_to(tmp_path)) for path in module.release_files(tmp_path)}
    assert names == {"topos/real.py", ".docs/guide.md"}


def test_candidate_rejects_symlinked_source_before_build(tmp_path):
    module = script("build_release")
    (tmp_path / "topos").mkdir()
    (tmp_path / "elsewhere.py").write_text("fixture")
    (tmp_path / "topos/source.py").symlink_to(tmp_path / "elsewhere.py")
    with pytest.raises(ValueError, match="symlinks"):
        module.release_files(tmp_path)


def test_wheel_normalization_changes_metadata_not_payload_or_record(tmp_path):
    module = script("build_release")
    wheel = write_wheel(tmp_path, "cochem-topos", {"topos/__init__.py": "PAYLOAD\n", "topos-0.1.dist-info/RECORD": "RECORD BYTES\n"})
    with zipfile.ZipFile(wheel) as original:
        expected = {name: original.read(name) for name in original.namelist()}
    module.normalize_archive(wheel, module.DEFAULT_EPOCH)
    first = wheel.read_bytes()
    module.normalize_archive(wheel, module.DEFAULT_EPOCH)
    assert wheel.read_bytes() == first
    with zipfile.ZipFile(wheel) as normalized:
        assert expected == {name: normalized.read(name) for name in normalized.namelist()}
        assert all(item.date_time == (2026, 1, 1, 0, 0, 0) for item in normalized.infolist())


def test_source_archive_normalization_is_repeatable_and_preserves_bytes(tmp_path):
    module = script("build_release")
    target = tmp_path / "source.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        info = tarfile.TarInfo("package/source.py")
        value = b"scientific source\n"
        info.size, info.mtime, info.uid = len(value), 1234567, 5678
        archive.addfile(info, io.BytesIO(value))
    module.normalize_archive(target, module.DEFAULT_EPOCH)
    before = target.read_bytes()
    module.normalize_archive(target, module.DEFAULT_EPOCH)
    assert target.read_bytes() == before
    with tarfile.open(target) as archive:
        assert archive.extractfile("package/source.py").read() == value
        assert archive.getmember("package/source.py").uid == 0


def test_release_installation_verifies_all_local_wheels_and_ownership(tmp_path):
    setup = script("setup_ecosystem")
    for project, payload in (("CoChem-BASE", {"frontend/__init__.py": "base"}),
                              ("cochem-topos", {"topos/__init__.py": "topos"}),
                              ("CoChem-TORQ", {"Libraries/__init__.py": "torq"})):
        write_wheel(tmp_path, project, payload)
    checksums(tmp_path)
    assert set(setup.verified_release_wheels(tmp_path)) == {"cochem-base", "cochem-topos", "cochem-torq"}
    write_wheel(tmp_path, "cochem-topos", {"frontend/__init__.py": "clobbered"})
    checksums(tmp_path)
    with pytest.raises(ValueError, match="overlap"):
        setup.verified_release_wheels(tmp_path)


def test_release_installer_rejects_checksum_tampering_before_pip(tmp_path):
    setup = script("setup_ecosystem")
    wheel = write_wheel(tmp_path, "cochem-topos")
    checksums(tmp_path)
    wheel.write_bytes(wheel.read_bytes() + b"altered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        setup.verified_release_wheels(tmp_path)


def test_clean_install_inventory_detects_identical_shared_files_too(tmp_path):
    acceptance = script("accept_installed_release")
    write_wheel(tmp_path, "CoChem-BASE", {"Libraries/shared.py": "same"})
    write_wheel(tmp_path, "CoChem-TORQ", {"Libraries/shared.py": "same"})
    write_wheel(tmp_path, "cochem-topos", {"topos/module.py": "private"})
    wheels, conflicts = acceptance.wheel_inventory(tmp_path)
    assert len(wheels) == 3 and len(conflicts) == 1
    assert conflicts[0]["same_bytes"]  # pip uninstall ownership is unsafe even with identical bytes


def test_gate_refuses_missing_evidence_and_current_unimplemented_matrix():
    result = release_gate(ROOT)
    assert result["status"] == "blocked" and not result["release_certified"] and not result["published"]
    assert any("current evidence file is missing" in reason for reason in result["blockers"])
    assert any("Method matrix" in reason for reason in result["blockers"])


def test_forged_top_level_pass_flags_cannot_replace_source_and_native_evidence(tmp_path):
    path = tmp_path / "claimed.json"
    path.write_text(json.dumps({"status": "passed", "all_srs_acceptance_complete": True, "all_matrix_recipes_implemented": True,
                                "pytest": {"tests": 100000, "failures": 0, "errors": 0, "skipped": 0},
                                "verification": {"sources_unchanged": True}}))
    result = release_gate(ROOT, validation=path, installation=path, hosted=path, srs_acceptance=path, distribution_manifest=path)
    assert result["status"] == "blocked"
    assert any("current source files" in item for item in result["blockers"])
    assert any("Installed wheel" in item for item in result["blockers"])
    assert any("Hosted ORCA" in item for item in result["blockers"])


def test_source_identity_is_content_based_and_ignores_local_caches(tmp_path):
    (tmp_path / "topos").mkdir()
    source = tmp_path / "topos/science.py"
    source.write_text("first")
    before = source_inventory(tmp_path)
    os.utime(source, (1, 1))
    assert source_inventory(tmp_path) == before
    source.write_text("second")
    assert source_inventory(tmp_path) != before
