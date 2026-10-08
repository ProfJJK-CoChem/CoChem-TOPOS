"""Release metadata, refusal gates and archive contracts; native install is separate."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
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


def test_native_provisioning_patch_is_distributed_and_binds_source_identity(tmp_path):
    module = script("build_release")
    patch = tmp_path / ".docs/patches/crest-3.0.2-generic-paths.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text("--- source.f90\n+++ source.f90\n@@\n-old\n+new\n")
    assert patch in module.release_files(tmp_path)
    before = source_inventory(tmp_path)
    assert before[str(patch.relative_to(tmp_path))] == hashlib.sha256(patch.read_bytes()).hexdigest()
    patch.write_text(patch.read_text().replace("+new", "+changed"))
    assert source_inventory(tmp_path) != before
    assert "recursive-include .docs *.md *.json *.patch *.xml" in (ROOT / "MANIFEST.in").read_text()


@pytest.mark.parametrize("filename", ["carbon12-dboc.out", "GRD", "ZMAT"])
def test_authentic_out_fixture_ships_and_mutation_invalidates_source_receipt(tmp_path, filename):
    module = script("build_release")
    fixture = tmp_path / "tests/v010/fixtures/cfour_corrections" / filename
    fixture.parent.mkdir(parents=True)
    fixture.write_text("inert parser fixture identity example\n")
    assert fixture in module.release_files(tmp_path)
    before = source_inventory(tmp_path)
    assert before[str(fixture.relative_to(tmp_path))] == hashlib.sha256(fixture.read_bytes()).hexdigest()
    fixture.write_text(fixture.read_text() + "altered native observation\n")
    assert source_inventory(tmp_path) != before
    assert "recursive-include tests *.py *.txt *.json *.stdout *.out" in (ROOT / "MANIFEST.in").read_text()


@pytest.mark.parametrize("form", ["files-list", "retained-path", "receipts", "all-retained", "files-dict"])
def test_scoped_evidence_text_formats_keep_origin_archives_outside_sources(tmp_path, form):
    """Storage/packaging contract text; no native calculation is represented."""
    module = script("build_release")
    evidence = tmp_path / ".docs/evidence"
    evidence.mkdir(parents=True)
    folder = evidence / "retained" if form == "files-dict" else evidence
    folder.mkdir(exist_ok=True)
    rows = []
    for name in ("original.txt", "deck.inp", "phase.log"):
        path = folder / name
        path.write_bytes(b"Unexecuted archive membership contract text.\n")
        rows.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "size_bytes": path.stat().st_size, "original_path": "/external/not-retained/artifact.zip"})
    if form == "files-dict":
        payload = {"directory": "retained", "files": {row["path"]: row for row in rows}}
    elif form == "retained-path":
        payload = {"files": [{**row, "retained_path": row["path"]} for row in rows]}
    else:
        key = {"files-list": "files", "receipts": "receipts", "all-retained": "all_retained_members"}[form]
        payload = {key: rows}
    payload["original_archives"] = [{"path": "/external/not-retained/artifact.zip", "sha256": "0" * 64}]
    index = evidence / "MEMBERS_INDEX.json"
    index.write_text(json.dumps(payload))
    for name in ("original.zip", "native-orca", "model.pt", "record.h5", "venv/ignored.py", "venv/ignored.log"):
        path = evidence / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"Excluded unexecuted packaging fixture")
    selected = set(module.release_files(tmp_path))
    assert selected == {index, *(folder / row["path"] for row in rows)}
    assert module.verify_evidence_indices(tmp_path, selected)[index.relative_to(tmp_path).as_posix()] == {
        (folder / row["path"]).relative_to(tmp_path).as_posix(): row["sha256"] for row in rows}


@pytest.mark.parametrize("damage", ["bytes", "size", "missing", "unsupported", "escape", "absolute", "alias", "docs-symlink", "parent-symlink", "leaf-symlink", "binary", "self"])
def test_indexed_source_evidence_cannot_be_omitted_rebound_or_corrupted(tmp_path, damage):
    module = script("build_release")
    evidence = tmp_path / ".docs/evidence"
    evidence.mkdir(parents=True)
    path = evidence / "original.txt"
    path.write_bytes(b"Unexecuted storage contract text.\n")
    row = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    if damage == "bytes":
        path.write_bytes(b"Changed contract bytes.\n")
    elif damage == "size":
        row["bytes"] += 1
    elif damage == "missing":
        path.unlink()
    elif damage == "unsupported":
        row["path"] = "original.zip"
        path.rename(evidence / row["path"])
    elif damage in {"escape", "absolute", "alias"}:
        row["path"] = {"escape": "../original.txt", "absolute": str(path), "alias": "./original.txt"}[damage]
    elif damage in {"parent-symlink", "leaf-symlink"}:
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        outside_file = outside / "original.txt"
        outside_file.write_bytes(path.read_bytes())
        if damage == "leaf-symlink":
            path.unlink()
            path.symlink_to(outside_file)
        else:
            (evidence / "alias").symlink_to(outside, target_is_directory=True)
            row["path"] = "alias/original.txt"
    elif damage == "binary":
        path.write_bytes(b"\x7fELF\0Unexecuted binary exclusion contract")
        row.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size)
    elif damage == "self":
        row["path"] = "MEMBERS_INDEX.json"
    (evidence / "MEMBERS_INDEX.json").write_text(json.dumps({"files": [row]}))
    if damage == "docs-symlink":
        (tmp_path / ".docs").rename(tmp_path / "external-docs")
        (tmp_path / ".docs").symlink_to(tmp_path / "external-docs", target_is_directory=True)
    with pytest.raises(ValueError, match="retained evidence|Retained evidence|Retained source evidence|Indexed retained|symlinks"):
        module.release_files(tmp_path)


@pytest.mark.parametrize("damage", ["missing", "changed", "duplicate"])
def test_built_source_archive_must_keep_each_indexed_member_once_and_unchanged(tmp_path, damage):
    """An inert archive mutation exercises the independent post-build verifier."""
    module = script("build_release")
    index_name = ".docs/evidence/MEMBERS_INDEX.json"
    name = ".docs/evidence/retained.txt"
    original = b"Unexecuted immutable archive contract.\n"
    digest = hashlib.sha256(original).hexdigest()
    index_data = json.dumps({"files": [{"path": "retained.txt", "sha256": digest}]}).encode()
    hashes = {index_name: hashlib.sha256(index_data).hexdigest(), name: digest}
    path = tmp_path / "inert.tar.gz"
    payloads = [(index_name, index_data)]
    if damage != "missing":
        payloads.append((name, b"Changed archive bytes" if damage == "changed" else original))
    if damage == "duplicate":
        payloads.append((name, original))
    with tarfile.open(path, "w:gz") as archive:
        for archived_name, data in payloads:
            member = tarfile.TarInfo("inert/" + archived_name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    with pytest.raises(ValueError, match="retained evidence"):
        module.verify_archived_evidence(path, {index_name: {name: digest}}, hashes)


def test_all_retained_indices_survive_actual_source_staging_and_manifest_rules(tmp_path):
    """Original historical bytes remain unchanged; no candidate or chemistry runs."""
    module = script("build_release")
    selected = module.release_files(ROOT)
    indices = module.verify_evidence_indices(ROOT, set(selected))
    assert indices
    stage = tmp_path / "source"
    stage.mkdir()
    for path in selected:
        name = path.relative_to(ROOT)
        if not (name.as_posix().startswith(".docs/") or name.as_posix() == "MANIFEST.in"):
            continue
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    (stage / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name='topos-retained-evidence-distribution-test', version='0.0.0', packages=[])\n")
    built = subprocess.run([sys.executable, "setup.py", "sdist", "--dist-dir", str(tmp_path / "dist")],
                           cwd=stage, capture_output=True, text=True, check=False)
    assert built.returncode == 0, built.stdout + built.stderr
    archive = next((tmp_path / "dist").glob("*.tar.gz"))
    hashes = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in selected}
    module.verify_archived_evidence(archive, indices, hashes)
    with tarfile.open(archive) as source:
        names = source.getnames()
        assert not any(name.endswith((".zip", ".h5", ".pt", ".whl")) for name in names)
        for guide in ("TOPOS_SCIENTIFIC_REFERENCE_CAMPAIGN.md", "TOPOS_REVIEWED_MATRIX_CAMPAIGN.md",
                      "TOPOS_VPT2_NATIVE_POSE_REFERENCE.md"):
            member = next(name for name in names if name.endswith("/.docs/" + guide))
            assert source.extractfile(member).read() == (ROOT / ".docs" / guide).read_bytes()


def test_tracked_native_fixtures_survive_candidate_staging_and_source_archive(tmp_path):
    """Native parser regressions remain runnable after extracting the source archive."""
    module = script("build_release")
    if (ROOT / ".git").exists():
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "tests/fixtures", "tests/v010/fixtures"],
            cwd=ROOT, capture_output=True, check=True,
        ).stdout
        fixtures = {ROOT / os.fsdecode(name) for name in tracked.split(b"\0") if name}
    else:
        # The extracted distribution has no Git index; exercise its retained fixtures.
        fixtures = {path for folder in ("tests/fixtures", "tests/v010/fixtures")
                    for path in (ROOT / folder).rglob("*")
                    if path.is_file() and "__pycache__" not in path.parts}
    # These unchanged historical derivative files are required by the native
    # raw revalidators, including the evidence of empty stderr. Source identity
    # and archives must retain them even before a new fixture reaches Git.
    derivative_folder = ROOT / "tests/v010/fixtures/orca_native_hessian_attribution"
    provenance = json.loads((derivative_folder / "provenance.json").read_text())
    required = {"frequency.stderr", "gradient-engine.stderr", "gradient-version.stderr",
                "gradient-version.inp", "gradient-version.stdout"}
    assert required <= set(provenance["files"])
    identity = source_inventory(ROOT)
    for name in required:
        path = derivative_folder / name
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        assert observed == provenance["files"][name]["sha256"]
        assert path.stat().st_size == provenance["files"][name]["size_bytes"]
        assert identity[path.relative_to(ROOT).as_posix()] == observed
    fixtures.update(derivative_folder / name for name in provenance["files"])
    # New provider fixtures must ship before Git staging, with original native
    # names retained only as provenance and accepted source-package suffixes.
    cfour_folder = ROOT / "tests/v010/fixtures/cfour_provider_2_1"
    cfour_proof = json.loads((cfour_folder / "provenance.json").read_text())
    assert {name: item["original_filename"] for name, item in cfour_proof["files"].items()} == {
        "output.stdout": "output.dat", "native-ZMAT.inp": "ZMAT"}
    for name, item in cfour_proof["files"].items():
        path = cfour_folder / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        assert path.stat().st_size == item["size_bytes"]
        assert identity[path.relative_to(ROOT).as_posix()] == item["sha256"]
    for name in {"provenance.json", *cfour_proof["files"]}:
        path = cfour_folder / name
        assert path.relative_to(ROOT).as_posix() in identity
        fixtures.add(path)
    assert fixtures
    stage = tmp_path / "source"
    stage.mkdir()
    # Exercise the production staging filter and actual MANIFEST.in rules together.
    for path in module.release_files(ROOT):
        if path not in fixtures | {ROOT / "MANIFEST.in"}:
            continue
        target = stage / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    (stage / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name='topos-fixture-distribution-test', version='0.0.0', packages=[])\n"
    )
    built = subprocess.run(
        [sys.executable, "setup.py", "sdist", "--dist-dir", str(tmp_path / "dist")],
        cwd=stage, capture_output=True, text=True, check=False,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    with tarfile.open(next((tmp_path / "dist").glob("*.tar.gz"))) as archive:
        payloads = {Path(member.name).relative_to(Path(member.name).parts[0]).as_posix():
                    hashlib.sha256(archive.extractfile(member).read()).hexdigest()
                    for member in archive.getmembers() if member.isfile()}
    for fixture in fixtures:
        name = fixture.relative_to(ROOT).as_posix()
        assert payloads.get(name) == hashlib.sha256(fixture.read_bytes()).hexdigest(), name


@pytest.mark.parametrize("suffix", [".hess", ".engrad", ".inp", ".stderr"])
def test_native_fixture_mutation_invalidates_source_receipt(tmp_path, suffix):
    fixture = tmp_path / "tests/v010/fixtures" / ("native" + suffix)
    fixture.parent.mkdir(parents=True)
    fixture.write_text("inert artifact identity example\n")
    before = source_inventory(tmp_path)
    assert before[str(fixture.relative_to(tmp_path))] == hashlib.sha256(fixture.read_bytes()).hexdigest()
    fixture.write_text("changed native artifact identity example\n")
    assert source_inventory(tmp_path) != before


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


def test_gate_refuses_missing_evidence_without_inventing_matrix_gaps():
    result = release_gate(ROOT)
    assert result["status"] == "blocked" and not result["release_certified"] and not result["published"]
    assert any("current evidence file is missing" in reason for reason in result["blockers"])
    assert "Scientific reference campaign: current evidence file is missing" in result["blockers"]
    assert "Reviewed matrix campaign: current evidence file is missing" in result["blockers"]
    # Every available TOPOS row now has a complete explicitly selected recipe;
    # scientific/native evidence remains a separate release requirement.
    assert not any(reason.startswith("Method matrix") for reason in result["blockers"])


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


def test_claimed_campaign_passes_require_reverified_plans_and_actual_runs(tmp_path):
    path = tmp_path / "claimed-campaign.json"
    path.write_text(json.dumps({"status": "passed", "source_sha256": source_inventory(ROOT),
                                "scientific_reference_campaign": True, "reviewed_matrix_campaign": True}))
    result = release_gate(ROOT, scientific_reference_campaign=path, reviewed_matrix_campaign=path)
    assert result["status"] == "blocked" and result["release_certified"] is False
    assert any(item.startswith("Scientific reference campaign:") for item in result["blockers"])
    assert any(item.startswith("Reviewed matrix campaign:") for item in result["blockers"])


def test_empty_objects_cannot_satisfy_any_mandatory_release_evidence(tmp_path):
    path = tmp_path / "empty-receipt.json"
    path.write_text("{}\n")
    result = release_gate(
        ROOT, validation=path, installation=path, hosted=path, hosted_extended=path,
        srs_acceptance=path, distribution_manifest=path,
        scientific_reference_campaign=path, reviewed_matrix_campaign=path,
    )
    assert result["status"] == "blocked" and result["release_certified"] is False
    for label in ("regression", "installed-wheel acceptance", "hosted ORCA acceptance", "extended hosted ORCA acceptance",
                  "SRS acceptance", "distribution", "Scientific reference campaign", "Reviewed matrix campaign"):
        assert any(reason.startswith(label + ": invalid receipt") and "empty object" in reason
                   for reason in result["blockers"]), result["blockers"]


@pytest.mark.parametrize("command", ["scientific-references", "matrix-campaign", "release"])
def test_installed_cli_exposes_acceptance_commands_without_starting_a_calculation(command):
    result = subprocess.run([sys.executable, "-m", "topos", command, "--help"],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def test_source_identity_is_content_based_and_ignores_local_caches(tmp_path):
    (tmp_path / "topos").mkdir()
    source = tmp_path / "topos/science.py"
    source.write_text("first")
    before = source_inventory(tmp_path)
    os.utime(source, (1, 1))
    assert source_inventory(tmp_path) == before
    source.write_text("second")
    assert source_inventory(tmp_path) != before


def test_worker_source_inventory_rejects_namespace_symlinks(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    module = script('build_ml_worker')
    (tmp_path / 'topos').mkdir()
    (tmp_path / 'topos/ml_worker.py').write_text('# exact worker\n')
    assert module.worker_sources(tmp_path) == {
        'topos/ml_worker.py': hashlib.sha256(b'# exact worker\n').hexdigest(),
    }
    (tmp_path / 'topos/escape.py').symlink_to(tmp_path / 'topos/ml_worker.py')
    with pytest.raises(ValueError, match='symlinks'):
        module.worker_sources(tmp_path)


def test_worker_installer_refuses_controller_ownership_before_pip(tmp_path, monkeypatch):
    module = script('install_ml_worker')
    monkeypatch.setattr(module.sys, 'prefix', str(tmp_path / 'venv'))
    monkeypatch.setattr(module.sys, 'base_prefix', str(tmp_path / 'system'))
    monkeypatch.setattr(module.importlib.metadata, 'distribution', lambda name: object())
    invoked = []
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: invoked.append(a))
    with pytest.raises(ValueError, match='controller namespace'):
        module.install(tmp_path / 'unread.whl', tmp_path / 'unread.json')
    assert invoked == []


def test_srs_refresh_uses_hashed_named_results_and_preserves_unrelated_native_skip(tmp_path):
    module = script('refresh_srs_acceptance')
    docs = tmp_path / '.docs'
    docs.mkdir()
    srs = docs / 'CoChem-TOPOS_SRS.md'
    srs.write_text('requirement fixture')
    source = tmp_path / 'source.py'
    source.write_text('# reviewed implementation\n')
    tests = tmp_path / 'test_contract.py'
    tests.write_text('def test_supported(): pass\ndef test_native(): pass\n')
    xml = tmp_path / 'results.xml'
    xml.write_text('<testsuites><testsuite tests="2" failures="0" errors="0" skipped="1">'
                   '<testcase classname="tests.test_contract" name="test_supported"/>'
                   '<testcase classname="tests.test_contract" name="test_native"><skipped message="licensed engine absent"/></testcase>'
                   '</testsuite></testsuites>')
    def identity(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    validation = tmp_path / 'validation.json'
    validation.write_text(json.dumps({'verification': {'sources_unchanged': True,
        'source_sha256': {'source.py': identity(source), 'test_contract.py': identity(tests)},
        'checks': [{'check': 'pytest', 'exit_code': 0, 'command': ['python', '-m', 'pytest', 'tests/v010'],
                    'junit': {'tests': 2, 'failures': 0, 'errors': 0, 'skipped': 1},
                    'junit_sha256': identity(xml)}]}}))
    def requirement(function, conditions):
        return {'implementation': [{'path': 'source.py'}],
                'acceptance_tests': [{'path': 'test_contract.py', 'test_functions': [function]}],
                'verification': {}, 'evidence': [], 'coding_gaps': [],
                'additional_acceptance_conditions': conditions}
    ledger_path = docs / 'ledger.json'
    ledger_path.write_text(json.dumps({'srs_sha256': identity(srs), 'requirements': {
        'supported': requirement('test_supported', []),
        'native': requirement('test_native', ['hosted_orca']),
        'missing': requirement('test_not_collected', []),
    }}))
    report = module.refresh(tmp_path, ledger_path, validation, reviewer='contract-test', junit_path=xml)
    assert report['requirements']['supported']['status'] == 'verified'
    assert report['requirements']['native']['status'] == 'verification-pending'
    assert report['requirements']['native']['additional_acceptance_conditions'] == ['hosted_orca']
    assert report['requirements']['missing']['status'] == 'verification-pending'
    assert report['requirements']['supported']['verification']['current_suite_skipped'] == 1
    xml.write_text(xml.read_text().replace('<skipped message="licensed engine absent"/>', ''))
    with pytest.raises(ValueError, match='JUnit artifact'):
        module.refresh(tmp_path, ledger_path, validation, reviewer='contract-test', junit_path=xml)


def test_release_gate_composes_only_exact_same_source_named_test_results(tmp_path):
    (tmp_path / 'topos').mkdir()
    source = tmp_path / 'topos/contract.py'
    source.write_text('# deliberately inert release-gate fixture\n')
    current = source_inventory(tmp_path)

    def receipt(name, case, skipped):
        xml = tmp_path / f'{name}.xml'
        xml.write_text('<testsuites><testsuite><testcase classname="tests.test_native" name="' + case + '">'
                       + ('<skipped message="native engine unavailable locally"/>' if skipped else '')
                       + '</testcase></testsuite></testsuites>')
        document = {'all_srs_acceptance_complete': True, 'all_matrix_recipes_implemented': True,
                    'verification': {'source_sha256': current, 'sources_unchanged': True, 'checks': [{
                        'check': 'pytest', 'exit_code': 0, 'junit_path': xml.name,
                        'junit_sha256': hashlib.sha256(xml.read_bytes()).hexdigest(),
                        'junit': {'tests': 1, 'failures': 0, 'errors': 0, 'skipped': int(skipped)},
                    }]}}
        path = tmp_path / f'{name}.json'
        path.write_text(json.dumps(document))
        return path

    local = receipt('local', 'test_exact_native', True)
    unrelated = receipt('unrelated', 'test_another_native_method', False)
    result = release_gate(tmp_path, validation=local, supplemental_validations=[unrelated])
    assert result['testcase_coverage']['uncovered'] == ['tests.test_native::test_exact_native']
    matching = receipt('matching', 'test_exact_native', False)
    result = release_gate(tmp_path, validation=local, supplemental_validations=[matching])
    assert result['testcase_coverage']['uncovered'] == []
    assert 'tests.test_native::test_exact_native' in result['testcase_coverage']['covered_by_supplements']
    assert not any(reason.startswith('Regression') for reason in result['blockers'])
    assert result['status'] == 'blocked'  # Missing native/SRS/distribution evidence remains mandatory.
    altered = json.loads(matching.read_text())
    altered['verification']['source_sha256']['topos/contract.py'] = '0' * 64
    matching.write_text(json.dumps(altered))
    result = release_gate(tmp_path, validation=local, supplemental_validations=[matching])
    assert any('source identity' in reason for reason in result['blockers'])


def test_hosted_receipts_require_same_selected_run_and_both_native_case_sets(tmp_path):
    """Receipt metadata fixtures test refusal logic, never native chemistry."""
    (tmp_path / 'topos').mkdir()
    (tmp_path / 'topos/science.py').write_text('# inert fixture\n')
    (tmp_path / 'scripts').mkdir()
    for name in ('accept_orca_topos.py', 'accept_orca_extended.py'):
        (tmp_path / 'scripts' / name).write_text('# inert receipt-producing script identity\n')
    inventory = source_inventory(tmp_path)
    identity = {'github_repository': 'ProfJJK-CoChem/CoChem-BASE', 'github_run_id': '1234',
                'github_run_attempt': '2', 'github_sha': 'a' * 40}
    baseline = {'schema_version': 'topos-orca-physical-acceptance/0.1.0', 'status': 'passed', **identity,
        'source': {'source_files': inventory}, 'acceptance_script_sha256': inventory['scripts/accept_orca_topos.py'],
        'cases': {name: {'status': 'passed'} for name in ('hf3c-energy-gradient',
            'r2scan3c-optimization-thermochemistry', 'wb97xv-optimization', 'counterpoise', 'goat-refinement')}}
    extended = {'schema_version': 'topos-orca-extended-acceptance/0.1.0', 'status': 'passed', **identity,
        'source': {'source_files': inventory}, 'script_sha256': inventory['scripts/accept_orca_extended.py'],
        'cases': {name: {'status': 'passed'} for name in ('native-hessian', 'native-vpt2', 'MP2', 'MP2-optimization', 'CCSD(T)', 'DLPNO-counterpoise',
            'AUTOCI-CCSD(T)', 'DLPNO-CCSD(T1)', 'CCSD(T)-F12D/RI', 'F12-MP2', 'F12-RI-MP2', 'F12-composite', 'R2-composite')}}
    first, second = tmp_path / 'baseline.json', tmp_path / 'extended.json'
    first.write_text(json.dumps(baseline))
    second.write_text(json.dumps(extended))
    def gate():
        return release_gate(tmp_path, hosted=first, hosted_extended=second,
                            hosted_repository=identity['github_repository'], hosted_run_id='1234', hosted_run_attempt='2')
    report = gate()
    assert not any(reason.startswith('Hosted ORCA') for reason in report['blockers'])
    assert report['status'] == 'blocked'  # Other release evidence is still absent.
    for missing in ('DLPNO-counterpoise', 'MP2-optimization', 'F12-composite', 'R2-composite'):
        del extended['cases'][missing]
        second.write_text(json.dumps(extended))
        assert any('every required native case' in reason for reason in gate()['blockers'])
        extended['cases'][missing] = {'status': 'passed'}
    extended['github_run_attempt'] = '1'
    second.write_text(json.dumps(extended))
    assert any('selected repository/run/attempt' in reason for reason in gate()['blockers'])
    extended['github_run_attempt'] = '2'
    extended['cases']['native-vpt2']['status'] = 'failed'
    second.write_text(json.dumps(extended))
    assert any('every required native case' in reason for reason in gate()['blockers'])
    extended['cases']['native-vpt2']['status'] = 'passed'
    extended['source']['source_files'] = dict(inventory, **{'topos/science.py': '0' * 64})
    second.write_text(json.dumps(extended))
    assert any('current package source' in reason for reason in gate()['blockers'])


def test_release_distinguishes_source_declared_unavailable_tiers_from_unresolved_gaps(tmp_path, monkeypatch):
    import topos.matrix_workflow as matrix

    source = tmp_path / 'wiki/Method_Matrix.md'
    source.parent.mkdir()
    source.write_text('CFOUR has no 10 s or 1 min entry\n')
    report = {'additional_adapter_recipes': [], 'topos_track_gaps': ['T3C-10s', 'T3C-1min'],
              'unresolved_track_gaps': [], 'unavailable_by_design': [
                  {'row_id': row, 'disposition': 'unavailable-by-design', 'source_path': 'wiki/Method_Matrix.md',
                   'source_lines': [1], 'source_excerpt': 'CFOUR has no 10 s or 1 min entry',
                   'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
                  for row in ['T3C-10s', 'T3C-1min']]}
    monkeypatch.setattr(matrix, 'execution_support_report', lambda: report)
    result = release_gate(tmp_path)
    assert not any(reason.startswith('Method matrix') for reason in result['blockers'])
    assert result['status'] == 'blocked'  # All scientific/runtime evidence remains mandatory.
    report['topos_track_gaps'].append('T3O-1w')
    report['unresolved_track_gaps'].append('T3O-1w')
    assert any('unresolved source track gaps T3O-1w' in reason for reason in release_gate(tmp_path)['blockers'])
    report['unresolved_track_gaps'].clear()
    assert any('lack an explicit' in reason for reason in release_gate(tmp_path)['blockers'])
    source.write_text('Changed source does not declare the unsupported tiers\n')
    assert any('matching source evidence' in reason for reason in release_gate(tmp_path)['blockers'])
