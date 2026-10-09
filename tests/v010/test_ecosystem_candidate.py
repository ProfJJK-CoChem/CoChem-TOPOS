"""Complete-kit tamper contracts; inert receipts never count as native acceptance."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import subprocess
import sys
import tarfile
import textwrap
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "topos_ecosystem_candidate_test", ROOT / "scripts/assemble_ecosystem_candidate.py",
)
kit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = kit
spec.loader.exec_module(kit)


def wheel(path, project, version, payload):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{project.replace('-', '_')}-{version}.dist-info/METADATA",
            f"Name: {project}\nVersion: {version}\n",
        )
        for name, data in payload.items():
            archive.writestr(name, data)
    return path


def source_archive(path, prefix, payload):
    with tarfile.open(path, "w:gz") as archive:
        for name, data in payload.items():
            info = tarfile.TarInfo(f"{prefix}/{name}")
            encoded = data.encode()
            info.size = len(encoded)
            archive.addfile(info, io.BytesIO(encoded))
    return path


def edit_json(path, change):
    value = kit.read_json(path)
    change(value)
    kit.write_json(path, value)


@pytest.fixture
def inputs(tmp_path):
    """Archive/receipt input validation only; none of these packages is installed."""
    candidate, wheelhouse, installation = [tmp_path / name for name in ("candidate", "wheels", "installed")]
    for path in (candidate / "ml-worker", wheelhouse / "sources", installation / "acceptance"):
        path.mkdir(parents=True)
    payload = {"topos/ml_worker.py": "# inert test source\n", "topos/module.py": "# another inert source\n"}
    source_hashes = {name: hashlib.sha256(value.encode()).hexdigest() for name, value in payload.items()}
    topos = wheel(candidate / "cochem_topos-0.1.0-py3-none-any.whl", "cochem-topos", "0.1.0", payload)
    (wheelhouse / topos.name).write_bytes(topos.read_bytes())
    source = source_archive(candidate / "cochem_topos-0.1.0.tar.gz", "cochem_topos-0.1.0", payload)
    repeated = {path.name: kit.digest(path) for path in (topos, source)}
    kit.write_json(candidate / "distribution-manifest.json", {
        "schema_version": "topos-distribution-candidate/0.1.0", "version": "0.1.0",
        "reproducible_archives": True, "repeated_build_sha256": [repeated, repeated],
        "source_sha256": source_hashes, "included_source_sha256": source_hashes,
        "artifacts": [{"name": path.name, "sha256": kit.digest(path), "bytes": path.stat().st_size}
                      for path in (topos, source)],
    })
    companions = {}
    for project, version in kit.PROJECTS.items():
        package = "cochem-" + project
        path = wheel(wheelhouse / f"cochem_{project}-{version}-py3-none-any.whl", package, version,
                     {f"{project}/__init__.py": "# inert metadata fixture\n"})
        source = source_archive(wheelhouse / "sources" / f"{project}.tar.gz", f"cochem_{project}-{version}",
                                {"pyproject.toml": f'[project]\nname="cochem-{project}"\nversion="{version}"\n'})
        companions[project] = {
            "source_commit": ("a" if project == "base" else "b") * 40,
            "wheel_name": path.name, "wheel_sha256": kit.digest(path),
            "source_archive": source.relative_to(wheelhouse).as_posix(),
            "source_archive_sha256": kit.digest(source),
            "repeated_wheel_sha256": [kit.digest(path)] * 2,
        }
    kit.write_json(wheelhouse / "companion-build-manifest.json", {
        "schema_version": "cochem-companion-build/0.1.0", "companions": companions,
    })
    kit.write_checksums(wheelhouse, list(wheelhouse.glob("*.whl")))
    worker = wheel(candidate / "ml-worker/cochem_topos_ml_worker-0.1.0-py3-none-any.whl",
                   "cochem-topos-ml-worker", "0.1.0", payload)
    kit.write_json(candidate / "ml-worker/worker-distribution-manifest.json", {
        "source_sha256": source_hashes, "reproducible_archives": True,
        "wheel": {"name": worker.name, "sha256": kit.digest(worker), "bytes": worker.stat().st_size},
    })
    kit.write_json(candidate / "release-gate.json", {
        "schema_version": "topos-release-gate/0.1.0", "source_sha256": source_hashes,
        "status": "blocked", "blockers": ["synthetic input fixture: no actual calculations were performed"],
    })
    receipt = installation / "acceptance/installed-acceptance.json"
    kit.write_json(receipt, {
        "status": "passed", "editable": False, "execution_backend": "base",
        "topos_wheel_sha256": kit.digest(topos), "torq_consumer_ready": True,
        "torq_handoff": {"status": "passed", "computation_performed": False},
        "native_run": {"status": "completed", "execution_kind": "real"},
        "scope": "synthetic input-validation fixture; not native scientific evidence",
    })
    kit.write_json(installation / "clean-install.json", {
        "schema_version": "topos-clean-install/0.1.0", "status": "passed",
        "acceptance_sha256": kit.digest(receipt), "distribution_ownership_clean": True,
        "wheels": {name: {"sha256": kit.digest(path)}
                   for name, path in kit.verified_release_wheels(wheelhouse).items()},
    })
    return candidate, wheelhouse, installation


def test_complete_kit_is_reproducible_and_retains_blocked_gate(inputs, tmp_path):
    results = [kit.assemble(*inputs, tmp_path / f"download-{number}") for number in (1, 2)]
    assert results[0]["sha256"] == results[1]["sha256"]
    assert results[0]["release_certified"] is False
    root = tmp_path / "download-1/cochem-topos-0.1.0-candidate"
    assert len(list((root / "wheels").glob("*.whl"))) == 3
    assert len(list((root / "sources").glob("*.tar.gz"))) == 3
    assert len(list((root / "ml-worker").glob("*.whl"))) == 1
    manifest = kit.read_json(root / "candidate-manifest.json")
    assert manifest["scientific_gate_status"] == "blocked"
    assert manifest["published"] is False
    for line in (root / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split()
        assert kit.digest(root / name) == expected
    assert "--wheelhouse wheels" in (root / "README.md").read_text()
    assert "mkdir source" in (root / "README.md").read_text()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/../b", "a//b", "./a", ".", "a\\b"])
def test_archive_paths_cannot_escape_or_alias(name):
    with pytest.raises(ValueError, match="Unconfined"):
        kit.confined_name(name)


@pytest.mark.parametrize("name,data", [("engine/orca", b"\x7fELFbinary"), ("engine.exe", b"MZbinary"),
                                         ("model.pt", b"checkpoint"), ("model.safetensors", b"checkpoint")])
def test_engine_binaries_and_model_weights_are_rejected(name, data):
    with pytest.raises(ValueError, match="installation kit"):
        kit.audit_payload(name, data)


def test_source_archive_symlinks_are_rejected_without_extracting(tmp_path):
    path = tmp_path / "links.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        link = tarfile.TarInfo("package/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)
    with pytest.raises(ValueError, match="links and special"):
        kit.audit_archive(path)


def test_tampered_installed_receipt_never_exposes_partial_kit(inputs, tmp_path):
    candidate, wheelhouse, installation = inputs
    edit_json(installation / "acceptance/installed-acceptance.json", lambda x: x.update(status="failed"))
    output = tmp_path / "download"
    with pytest.raises(ValueError, match="noneditable installation evidence"):
        kit.assemble(candidate, wheelhouse, installation, output)
    assert not output.exists()


def test_worker_payload_is_checked_even_if_its_archive_hash_is_replaced(inputs):
    candidate, wheelhouse, installation = inputs
    path = next((candidate / "ml-worker").glob("*.whl"))
    wheel(path, "cochem-topos-ml-worker", "0.1.0", {"topos/ml_worker.py": "# changed\n", "topos/module.py": "# changed\n"})
    edit_json(candidate / "ml-worker/worker-distribution-manifest.json",
              lambda x: x["wheel"].update(sha256=kit.digest(path), bytes=path.stat().st_size))
    with pytest.raises(ValueError, match="payload differs"):
        kit.verify_inputs(candidate, wheelhouse, installation)


def test_source_payload_is_checked_even_if_archive_digests_are_replaced(inputs):
    candidate, wheelhouse, installation = inputs
    path = next(candidate.glob("*.tar.gz"))
    source_archive(path, "cochem_topos-0.1.0", {"topos/ml_worker.py": "# changed\n", "topos/module.py": "# changed\n"})

    def change(manifest):
        for item in manifest["artifacts"]:
            if item["name"] == path.name:
                item.update(sha256=kit.digest(path), bytes=path.stat().st_size)
        for values in manifest["repeated_build_sha256"]:
            values[path.name] = kit.digest(path)
    edit_json(candidate / "distribution-manifest.json", change)
    with pytest.raises(ValueError, match="Source archive payload differs"):
        kit.verify_inputs(candidate, wheelhouse, installation)


@pytest.mark.parametrize("target", ["companion", "gate"])
def test_other_source_or_nonreproducible_companion_cannot_join_this_kit(inputs, target):
    candidate, wheelhouse, installation = inputs
    if target == "companion":
        edit_json(wheelhouse / "companion-build-manifest.json",
                  lambda x: x["companions"]["base"].update(repeated_wheel_sha256=["0" * 64] * 2))
    else:
        edit_json(candidate / "release-gate.json", lambda x: x.update(source_sha256={"other.py": "0" * 64}))
    with pytest.raises(ValueError, match="reproducibility|gate evidence"):
        kit.verify_inputs(candidate, wheelhouse, installation)



def test_controller_wheel_payload_cannot_disagree_with_declared_source(inputs):
    candidate, wheelhouse, installation = inputs
    path = next(candidate.glob("*.whl"))
    wheel(path, "cochem-topos", "0.1.0", {"topos/ml_worker.py": "# changed\n", "topos/module.py": "# changed\n"})
    (wheelhouse / path.name).write_bytes(path.read_bytes())
    kit.write_checksums(wheelhouse, list(wheelhouse.glob("*.whl")))

    def change(manifest):
        for item in manifest["artifacts"]:
            if item["name"] == path.name:
                item.update(sha256=kit.digest(path), bytes=path.stat().st_size)
        for values in manifest["repeated_build_sha256"]:
            values[path.name] = kit.digest(path)
    edit_json(candidate / "distribution-manifest.json", change)
    with pytest.raises(ValueError, match="Wheel payload differs"):
        kit.verify_inputs(candidate, wheelhouse, installation)


@pytest.mark.parametrize("prefix,version", [("unexpected-root", kit.PROJECTS["base"]),
                                         ("cochem_base-" + kit.PROJECTS["base"], "9.9.9")])
def test_companion_extraction_root_and_package_version_are_checked(inputs, prefix, version):
    candidate, wheelhouse, installation = inputs
    path = wheelhouse / "sources/base.tar.gz"
    source_archive(path, prefix, {"pyproject.toml": f'[project]\nname="cochem-base"\nversion="{version}"\n'})
    edit_json(wheelhouse / "companion-build-manifest.json",
              lambda x: x["companions"]["base"].update(source_archive_sha256=kit.digest(path)))
    with pytest.raises(ValueError, match="extraction root|mandatory release set"):
        kit.verify_inputs(candidate, wheelhouse, installation)


def test_companions_are_really_twice_built_from_pinned_git_trees(tmp_path):
    roots, pins = {}, {}
    for project, version in kit.PROJECTS.items():
        root = tmp_path / project
        root.mkdir()
        (root / "pyproject.toml").write_text(
            '[build-system]\nrequires=["setuptools>=77", "wheel"]\nbuild-backend="setuptools.build_meta"\n'
            f'[project]\nname="cochem-{project}"\nversion="{version}"\n'
            f'[tool.setuptools]\npy-modules=["fixture_{project}"]\n'
        )
        (root / f"fixture_{project}.py").write_text("VALUE = 'pinned-source'\n")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=Kit test", "-c", "user.email=kit@example.invalid",
                        "commit", "-qm", "inert build fixture"], check=True)
        pins[project] = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        roots[project] = root
        # Actual archive bytes must not inherit this Windows conversion policy.
        subprocess.run(["git", "-C", str(root), "config", "core.autocrlf", "true"], check=True)
        (root / f"fixture_{project}.py").write_text("VALUE = 'uncommitted-change'\n")
    output = tmp_path / "companions"
    manifest = kit.prepare_companions(roots, pins, output)
    for project, proof in manifest["companions"].items():
        assert proof["source_commit"] == pins[project]
        assert proof["repeated_wheel_sha256"] == [proof["wheel_sha256"]] * 2
        with zipfile.ZipFile(output / proof["wheel_name"]) as archive:
            assert archive.read(f"fixture_{project}.py") == b"VALUE = 'pinned-source'\n"
    assert len(list(output.glob("*-build-*.log"))) == 4


def test_workflow_retains_complete_three_source_download():
    workflow = (ROOT / ".github/workflows/topos_release.yml").read_text()
    assert "assemble_ecosystem_candidate.py companions" in workflow
    assert "assemble_ecosystem_candidate.py assemble" in workflow
    assert "${{ runner.temp }}/ecosystem-download/" in workflow
    assert "inputs.base_commit || vars.COCHEM_BASE_COMMIT" in workflow
    assert "base_commit:" in workflow and "ref: ${{ env.BASE_COMMIT }}" in workflow
    assert '--base-pin "$BASE_COMMIT"' in workflow
    torq_commit = "4f323800227dbde00ffb082bd6d9e44d851e1c7a"
    assert f"ref: {torq_commit}" in workflow
    assert f"--torq-pin {torq_commit}" in workflow
    assert "--output \"$RUNNER_TEMP/topos-candidate/release-gate.json\"" in workflow


@pytest.mark.parametrize("pin,expected", [("", 1), ("main", 1), ("A" * 40, 1),
                                           ("a" * 39, 1), ("a" * 40, 0)])
def test_workflow_requires_an_explicit_immutable_base_source_before_checkout(pin, expected):
    workflow = (ROOT / ".github/workflows/topos_release.yml").read_text()
    validation = workflow.split("- name: Validate the exact BASE source commit", 1)[1]
    validation = validation.split("- uses:", 1)[0].split("run: |", 1)[1]
    result = subprocess.run(["bash", "-c", textwrap.dedent(validation)],
                            env={**os.environ, "BASE_COMMIT": pin}, capture_output=True, text=True)
    assert result.returncode == expected, result.stderr
    if not pin:
        assert "base_commit" in result.stderr and "COCHEM_BASE_COMMIT" in result.stderr


@pytest.mark.parametrize("old_version", ["1.0.0", "1.0.1", "1.0.2", "1.1.1"])
def test_unreviewed_base_version_cannot_join_exact_1_1_0_release_set(inputs, old_version):
    """Inert wheel metadata; no package or engine is installed by this case."""
    candidate, wheelhouse, installation = inputs
    base = kit.read_json(wheelhouse / "companion-build-manifest.json")["companions"]["base"]
    wheel(wheelhouse / base["wheel_name"], "cochem-base", old_version, {"fixture_base.py": "inert"})
    kit.write_checksums(wheelhouse, list(wheelhouse.glob("*.whl")))
    with pytest.raises(ValueError, match="name/version differs from the mandatory release set"):
        kit.verify_inputs(candidate, wheelhouse, installation)


def test_exact_base_foundation_version_matches_dependency_and_download_paths():
    """The standalone kit pins a reviewed BASE within managed compatibility."""
    dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert "CoChem-BASE>=1.0.1,<2" in dependencies
    assert kit.PROJECTS["base"] == kit.PACKAGE_VERSIONS["cochem-base"] == "1.1.0"
    assert "BASE 1.1.0" in kit.INSTALL_README
    assert "--base-root source/cochem_base-1.1.0" in kit.INSTALL_README
    acceptance = (ROOT / "scripts/accept_installed_release.py").read_text()
    assert "m.version('CoChem-BASE')=='1.1.0'" in acceptance
