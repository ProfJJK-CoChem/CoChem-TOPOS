"""Installer infrastructure fixtures; no fixture is an ORCA calculation.

Tiny inert executable payloads test filesystem membership/permissions only.
Network responses are deliberately controlled; no licensed archive is present.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import tarfile
import urllib.error
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

# BASE owns the installed ``scripts`` package. Load the TOPOS source helper
# explicitly so this acceptance suite exercises the intended installer.
_installer_path = Path(__file__).resolve().parents[2] / "scripts" / "install_orca.py"
_installer_spec = importlib.util.spec_from_file_location("topos_orca_installer", _installer_path)
assert _installer_spec is not None and _installer_spec.loader is not None
installer = importlib.util.module_from_spec(_installer_spec)
_installer_spec.loader.exec_module(installer)

PRIVATE_URL = "https://licensed-archive.example/archive.tar.xz?signature=PRIVATE-URL-TOKEN"
PAYLOAD = b"inert installer fixture; never execute\n"
GITHUB_TOKEN_FIXTURE = "ghs_PRIVATE_INFRASTRUCTURE_TEST_TOKEN"
GITHUB_REPOSITORY_FIXTURE = "Controlled-Owner/student-tests"
ASSET_ENDPOINT = f"https://api.github.com/repos/{GITHUB_REPOSITORY_FIXTURE}/releases/assets/12345"
CDN_URL = "https://release-assets.githubusercontent.com/github-production-release-asset/test?signature=PRIVATE-CDN-SIGNATURE"


def archive_bytes(entries=None, compression="gz"):
    if entries is None:
        entries = [("./", "dir", b""), ("orca-6.1.1/orca", "file", PAYLOAD),
                   ("orca-6.1.1/helper", "file", b"inert helper"),
                   ("orca-6.1.1/data/reference.txt", "data", b"archive data")]
    stream = io.BytesIO()
    mode = f"w:{compression}" if compression else "w:"
    with tarfile.open(fileobj=stream, mode=mode) as archive:
        for name, kind, data in entries:
            member = tarfile.TarInfo(name)
            member.mode = 0o755 if kind in {"file", "dir"} else 0o644
            if kind == "dir":
                member.type = tarfile.DIRTYPE
            elif kind in {"symlink", "hardlink"}:
                member.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
                member.linkname = data.decode()
            elif kind == "fifo":
                member.type = tarfile.FIFOTYPE
            else:
                member.size = len(data)
            archive.addfile(member, io.BytesIO(data) if member.isfile() else None)
    return stream.getvalue()


class Response(io.BytesIO):
    status = 200

    def __init__(self, payload, *, length=True):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))} if length else {}


@pytest.fixture
def network_fixture(tmp_path, monkeypatch):
    root = tmp_path / "runner-temp"
    root.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(root))
    monkeypatch.setenv("ORCA_611_ARCHIVE_URL", PRIVATE_URL)

    def provide(payload, *, length=True, failure=None):
        def open_response(url, timeout):
            assert url == PRIVATE_URL
            assert 0 < timeout < float("inf")
            if failure is not None:
                raise failure
            return Response(payload, length=length)

        monkeypatch.setattr(installer.urllib.request, "build_opener", lambda *handlers: SimpleNamespace(open=open_response))
        return hashlib.sha256(payload).hexdigest()

    return root, provide


@pytest.mark.parametrize("compression", ["", "gz", "xz", "bz2"])
def test_full_archive_installs_without_executing_payloads(network_fixture, compression):
    root, provide = network_fixture
    digest = provide(archive_bytes(compression=compression))
    binary = installer.install(root / "installed", digest.upper(), disk_reserve_bytes=0)
    assert binary == (root / "installed/orca-6.1.1/orca").resolve()
    assert binary.read_bytes() == PAYLOAD
    assert os.access(binary, os.X_OK)
    assert (binary.parent / "helper").read_bytes() == b"inert helper"
    assert os.access(binary.parent / "helper", os.X_OK)
    assert (binary.parent / "data/reference.txt").read_text() == "archive data"
    assert not os.access(binary.parent / "data/reference.txt", os.X_OK)
    manifest = json.loads((root / "installed" / installer.MANIFEST_NAME).read_text())
    assert manifest == {"archive_sha256": digest, "expected_version": "6.1.1"}
    assert PRIVATE_URL not in json.dumps(manifest)
    assert sorted(p.name for p in root.iterdir()) == ["installed"]


def test_checksum_mismatch_precedes_any_extraction(network_fixture, monkeypatch):
    root, provide = network_fixture
    provide(archive_bytes())
    monkeypatch.setattr(installer, "_catalogue", lambda *a, **k: pytest.fail("must not inspect/extract an unverified archive"))
    with pytest.raises(installer.InstallError, match="checksum mismatch"):
        installer.install(root / "installed", "0" * 64, disk_reserve_bytes=0)
    assert not list(root.iterdir())


@pytest.mark.parametrize("extra", [
    ("../escape", "data", b"bad"),
    ("/absolute", "data", b"bad"),
    ("C:/windows", "data", b"bad"),
    ("directory\\windows", "data", b"bad"),
    ("line\nbreak", "data", b"bad"),
    ("orca-6.1.1/./orca", "file", b"duplicate"),
    ("link", "symlink", b"../../escape"),
    ("link", "hardlink", b"orca-6.1.1/orca"),
    ("fifo", "fifo", b""),
    ("orca-6.1.1/orca/child", "data", b"file-parent conflict"),
    (installer.MANIFEST_NAME, "data", b"manifest conflict"),
    (installer.SCRATCH_PREFIX + "forged/archive.tar", "data", b"scratch conflict"),
    ("other/orca", "file", b"ambiguous executable"),
])
def test_malicious_or_ambiguous_archive_is_rejected_before_extraction(network_fixture, extra):
    root, provide = network_fixture
    digest = provide(archive_bytes([("orca-6.1.1/orca", "file", PAYLOAD), extra]))
    with pytest.raises(installer.InstallError):
        installer.install(root / "installed", digest, disk_reserve_bytes=0)
    assert not list(root.iterdir())
    assert not (root.parent / "escape").exists()


def test_missing_or_nonexecutable_entry_cannot_be_promoted(network_fixture):
    root, provide = network_fixture
    digest = provide(archive_bytes([("package/orca", "data", PAYLOAD)]))
    with pytest.raises(installer.InstallError, match="exactly one regular executable"):
        installer.install(root / "installed", digest, disk_reserve_bytes=0)


@pytest.mark.parametrize("limit", ["download-header", "download-stream", "expanded", "members"])
def test_download_expansion_and_member_limits_are_enforced(network_fixture, limit):
    root, provide = network_fixture
    payload = archive_bytes()
    digest = provide(payload, length=limit != "download-stream")
    options = {"disk_reserve_bytes": 0}
    if limit.startswith("download"):
        options["max_download_bytes"] = len(payload) - 1
    elif limit == "expanded":
        options["max_expanded_bytes"] = len(PAYLOAD) - 1
    else:
        options["max_members"] = 1
    with pytest.raises(installer.InstallError, match="limit"):
        installer.install(root / "installed", digest, **options)
    assert not list(root.iterdir())


def test_disk_reserve_is_preserved(network_fixture, monkeypatch):
    root, provide = network_fixture
    digest = provide(archive_bytes())
    monkeypatch.setattr(installer.shutil, "disk_usage", lambda path: SimpleNamespace(free=4))
    with pytest.raises(installer.InstallError, match="disk space"):
        installer.install(root / "installed", digest, disk_reserve_bytes=5)
    assert not list(root.iterdir())


@pytest.mark.parametrize("digest", ["", "a" * 63, "a" * 65, "g" * 64, "a" * 63 + "\n"])
def test_reviewed_checksum_has_exact_format(network_fixture, digest):
    root, _ = network_fixture
    with pytest.raises(installer.InstallError, match="64 hexadecimal"):
        installer.install(root / "installed", digest)
    assert not list(root.iterdir())


def test_destination_is_fresh_confined_and_has_no_symlink_ancestors(network_fixture):
    root, provide = network_fixture
    digest = provide(archive_bytes())
    occupied = root / "existing"
    occupied.mkdir()
    sentinel = occupied / "keep.txt"
    sentinel.write_text("keep")
    for destination in (root, root.parent / "outside", occupied):
        with pytest.raises(installer.InstallError):
            installer.install(destination, digest, disk_reserve_bytes=0)
    link = root / "linked"
    link.symlink_to(occupied, target_is_directory=True)
    with pytest.raises(installer.InstallError, match="symlinks"):
        installer.install(link / "installed", digest, disk_reserve_bytes=0)
    assert sentinel.read_text() == "keep"


def test_network_exception_and_cli_output_never_reveal_presigned_url(network_fixture, capsys):
    root, provide = network_fixture
    failure = urllib.error.HTTPError(PRIVATE_URL, 403, f"denied {PRIVATE_URL}", {}, None)
    digest = provide(archive_bytes(), failure=failure)
    with pytest.raises(installer.InstallError) as caught:
        installer.install(root / "installed", digest, disk_reserve_bytes=0)
    assert PRIVATE_URL not in str(caught.value)
    assert "PRIVATE-URL-TOKEN" not in str(caught.value)
    assert caught.value.__suppress_context__ is True
    assert installer.main([str(root / "cli"), "--sha256", digest]) == 1
    assert "PRIVATE-URL-TOKEN" not in capsys.readouterr().out
    assert not list(root.iterdir())


def test_redirect_handler_refuses_redirects_without_disclosing_target():
    with pytest.raises(installer.InstallError, match="redirects") as caught:
        installer._NoRedirect().redirect_request(None, None, 302, "Found", {}, PRIVATE_URL)
    assert PRIVATE_URL not in str(caught.value)


@pytest.mark.parametrize("url", ["", "http://example/archive", "https://secret:password@example/archive", "https://example/archive#secret", "https://example/archive\nsecret"])
def test_url_must_be_https_and_only_read_from_environment(network_fixture, monkeypatch, url):
    root, provide = network_fixture
    digest = provide(archive_bytes())
    monkeypatch.setenv("ORCA_611_ARCHIVE_URL", url)
    with pytest.raises(installer.InstallError, match="HTTPS") as caught:
        installer.install(root / "installed", digest, disk_reserve_bytes=0)
    assert "password" not in str(caught.value)


def test_cli_emits_only_absolute_executable_and_appends_github_environment(network_fixture, capsys):
    root, provide = network_fixture
    digest = provide(archive_bytes())
    environment = root / "github-env"
    environment.write_text("EXISTING=value\n")
    assert installer.main([str(root / "installed"), "--sha256", digest, "--github-env", str(environment)]) == 0
    binary = (root / "installed/orca-6.1.1/orca").resolve()
    assert capsys.readouterr().out == f"{binary}\n"
    assert environment.read_text() == f"EXISTING=value\nTOPOS_ORCA_EXECUTABLE={binary}\n"


def test_corrupt_archive_error_is_redacted_and_cleaned(network_fixture):
    root, provide = network_fixture
    digest = provide(PRIVATE_URL.encode())
    with pytest.raises(installer.InstallError) as caught:
        installer.install(root / "installed", digest, disk_reserve_bytes=0)
    assert "PRIVATE-URL-TOKEN" not in str(caught.value)
    assert not list(root.iterdir())


def test_excessive_pax_metadata_is_bounded(network_fixture):
    root, provide = network_fixture
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        member = tarfile.TarInfo("orca")
        member.mode = 0o755
        member.pax_headers = {"comment": "x" * (65 * 1024)}
        member.size = len(PAYLOAD)
        archive.addfile(member, io.BytesIO(PAYLOAD))
    digest = provide(content.getvalue())
    with pytest.raises(installer.InstallError, match="metadata extension"):
        installer.install(root / "installed", digest, disk_reserve_bytes=0)
    assert not list(root.iterdir())


@pytest.mark.parametrize("pax_headers", [
    {"GNU.sparse.size": "999999999999"},
    {"GNU.sparse.map": "0,100", "GNU.sparse.size": "999999999999"},
    {"GNU.sparse.major": "1", "GNU.sparse.minor": "0", "GNU.sparse.realsize": "999999999999"},
])
def test_sparse_pax_variants_are_rejected_before_processing_maps(network_fixture, pax_headers):
    root, provide = network_fixture
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        member = tarfile.TarInfo("orca")
        member.mode = 0o755
        member.pax_headers = pax_headers
        member.size = len(PAYLOAD)
        archive.addfile(member, io.BytesIO(PAYLOAD))
    digest = provide(content.getvalue())
    with pytest.raises(installer.InstallError, match="unsupported sparse"):
        installer.install(root / "installed", digest, disk_reserve_bytes=0)
    assert not list(root.iterdir())


def test_total_deadline_and_invalid_timeout_are_enforced(network_fixture, monkeypatch):
    root, provide = network_fixture
    digest = provide(archive_bytes())
    with pytest.raises(installer.InstallError, match="finite"):
        installer.install(root / "installed", digest, total_timeout_seconds=float("inf"))
    moments = iter([0.0, 2.0])
    monkeypatch.setattr(installer.time, "monotonic", lambda: next(moments))
    with pytest.raises(installer.InstallError, match="time limit"):
        installer.install(root / "installed", digest, total_timeout_seconds=1, disk_reserve_bytes=0)
    assert not list(root.iterdir())


@pytest.fixture
def github_network_fixture(tmp_path, monkeypatch):
    root = tmp_path / "runner-temp"
    root.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(root))
    monkeypatch.setenv("GITHUB_REPOSITORY", GITHUB_REPOSITORY_FIXTURE)
    monkeypatch.setenv("GITHUB_TOKEN", GITHUB_TOKEN_FIXTURE)
    monkeypatch.delenv("ORCA_611_ARCHIVE_URL", raising=False)
    calls = []
    payload = archive_bytes()

    def provide(responses):
        pending = iter(responses)

        def opener(*handlers):
            def open_response(request, timeout):
                assert isinstance(request, installer.urllib.request.Request)
                assert 0 < timeout < float("inf")
                calls.append({"url": request.full_url, "headers": {k.lower(): v for k, v in request.header_items()},
                              "handlers": handlers, "method": request.get_method()})
                response = next(pending)
                if isinstance(response, Exception):
                    raise response
                return response

            return SimpleNamespace(open=open_response)

        monkeypatch.setattr(installer.urllib.request, "build_opener", opener)

    return root, payload, hashlib.sha256(payload).hexdigest(), calls, provide


def api_redirect(location=CDN_URL, *, status=302):
    headers = Message()
    if location is not None:
        headers["Location"] = location
    headers["Set-Cookie"] = "private-api-cookie=must-not-forward"
    return urllib.error.HTTPError(ASSET_ENDPOINT, status, "redirect", headers, io.BytesIO())


def test_private_asset_direct_api_download_has_scoped_auth_and_same_manifest(github_network_fixture):
    root, payload, digest, calls, provide = github_network_fixture
    provide([Response(payload)])
    binary = installer.install(root / "installed", digest, github_asset_id="12345", disk_reserve_bytes=0)
    assert binary.read_bytes() == PAYLOAD
    assert len(calls) == 1
    request = calls[0]
    assert request["url"] == ASSET_ENDPOINT
    assert request["method"] == "GET"
    assert request["headers"] == {
        "authorization": f"Bearer {GITHUB_TOKEN_FIXTURE}",
        "accept": "application/octet-stream",
        "x-github-api-version": "2022-11-28",
        "user-agent": installer.USER_AGENT,
    }
    assert isinstance(request["handlers"][0], installer._InspectApiRedirect)
    manifest = json.loads((root / "installed" / installer.MANIFEST_NAME).read_text())
    assert manifest == {"archive_sha256": digest, "expected_version": "6.1.1"}


@pytest.mark.parametrize("location", [CDN_URL, CDN_URL.replace(".com/", ".com:443/")])
def test_private_asset_cdn_request_never_inherits_token_or_cookies(github_network_fixture, location):
    root, payload, digest, calls, provide = github_network_fixture
    redirect = api_redirect(location)
    provide([redirect, Response(payload)])
    binary = installer.install(root / "installed", digest, github_asset_id="12345", disk_reserve_bytes=0)
    assert binary.read_bytes() == PAYLOAD
    assert redirect.closed
    assert len(calls) == 2
    assert calls[0]["headers"]["authorization"] == f"Bearer {GITHUB_TOKEN_FIXTURE}"
    assert calls[1]["url"] == location
    assert calls[1]["headers"] == {"accept": "application/octet-stream", "user-agent": installer.USER_AGENT}
    assert isinstance(calls[1]["handlers"][0], installer._NoRedirect)
    assert GITHUB_TOKEN_FIXTURE not in json.dumps({k: v for k, v in calls[1].items() if k != "handlers"})


@pytest.mark.parametrize("location", [
    None, "/relative/path", "http://release-assets.githubusercontent.com/asset",
    "https://objects.githubusercontent.com/asset", "https://api.github.com/asset",
    "https://release-assets.githubusercontent.com.evil.example/asset",
    "https://evil.release-assets.githubusercontent.com/asset",
    "https://release-assets.githubusercontent.com./asset",
    "https://release-assets.githubusercontent.com:444/asset",
    "https://release-assets.githubusercontent.com:bad/asset",
    "https://user@release-assets.githubusercontent.com/asset",
    "https://user:secret@release-assets.githubusercontent.com/asset",
    CDN_URL + "#secret", CDN_URL + "#", CDN_URL + "\nsecret",
])
def test_private_asset_rejects_redirects_outside_the_exact_cdn_policy(github_network_fixture, location):
    root, _, digest, calls, provide = github_network_fixture
    provide([api_redirect(location)])
    with pytest.raises(installer.InstallError, match="permitted HTTPS") as caught:
        installer.install(root / "installed", digest, github_asset_id="12345", disk_reserve_bytes=0)
    assert len(calls) == 1
    assert "PRIVATE-CDN-SIGNATURE" not in str(caught.value)
    assert GITHUB_TOKEN_FIXTURE not in str(caught.value)
    assert not list(root.iterdir())


@pytest.mark.parametrize("status", [301, 303, 307, 308, 403, 404])
def test_private_asset_api_error_has_no_fallback_or_private_error_text(github_network_fixture, status, capsys):
    root, _, digest, calls, provide = github_network_fixture
    private_error = urllib.error.HTTPError(ASSET_ENDPOINT, status, f"failure {GITHUB_TOKEN_FIXTURE} {PRIVATE_URL}", {}, io.BytesIO())
    provide([private_error])
    assert installer.main([str(root / "installed"), "--sha256", digest, "--github-asset-id", "12345"]) == 1
    output = capsys.readouterr()
    assert GITHUB_TOKEN_FIXTURE not in output.out + output.err
    assert PRIVATE_URL not in output.out + output.err
    assert ASSET_ENDPOINT not in output.out + output.err
    assert len(calls) == 1
    assert private_error.closed
    assert not list(root.iterdir())


def test_private_asset_rejects_duplicate_redirect_locations(github_network_fixture):
    root, _, digest, calls, provide = github_network_fixture
    redirect = api_redirect()
    redirect.headers["Location"] = "https://untrusted.example/second"
    provide([redirect])
    with pytest.raises(installer.InstallError, match="permitted HTTPS"):
        installer.install(root / "installed", digest, github_asset_id="12345", disk_reserve_bytes=0)
    assert len(calls) == 1


def test_private_asset_cdn_cannot_redirect_again(github_network_fixture):
    root, _, digest, calls, provide = github_network_fixture
    provide([api_redirect(), urllib.error.HTTPError(CDN_URL, 302, PRIVATE_URL, {"Location": PRIVATE_URL}, None)])
    with pytest.raises(installer.InstallError) as caught:
        installer.install(root / "installed", digest, github_asset_id="12345", disk_reserve_bytes=0)
    assert len(calls) == 2
    assert isinstance(calls[1]["handlers"][0], installer._NoRedirect)
    assert PRIVATE_URL not in str(caught.value)
    assert "PRIVATE-CDN-SIGNATURE" not in str(caught.value)
    assert not list(root.iterdir())


@pytest.mark.parametrize("asset_id", ["", "0", "-1", "+1", "01", "1.0", "123/other", "123\n", "１２３"])
def test_private_asset_identifier_is_canonical_positive_decimal(github_network_fixture, asset_id):
    root, _, digest, calls, provide = github_network_fixture
    provide([])
    with pytest.raises(installer.InstallError, match="positive decimal"):
        installer.install(root / "installed", digest, github_asset_id=asset_id, disk_reserve_bytes=0)
    assert calls == []


@pytest.mark.parametrize("repository", ["", "owner", "owner/repo/extra", "../repo", "owner/..", "owner/.", "-owner/repo", "owner-/repo", "owner/rep o", "owner/repo\n", "own%65r/repo", "https://github.com/owner/repo"])
def test_private_asset_repository_cannot_change_fixed_api_origin_or_path(github_network_fixture, monkeypatch, repository):
    root, _, digest, calls, provide = github_network_fixture
    provide([])
    monkeypatch.setenv("GITHUB_REPOSITORY", repository)
    with pytest.raises(installer.InstallError, match="owner/repository"):
        installer.install(root / "installed", digest, github_asset_id="12345", disk_reserve_bytes=0)
    assert calls == []


@pytest.mark.parametrize("token", ["", " token", "token ", "token\nAuthorization: different", "token\r", "token\t", "token\x7f", "é"])
def test_private_asset_token_rejects_header_injection_before_request(github_network_fixture, monkeypatch, token):
    root, _, digest, calls, provide = github_network_fixture
    provide([])
    monkeypatch.setenv("GITHUB_TOKEN", token)
    with pytest.raises(installer.InstallError, match="GITHUB_TOKEN"):
        installer.install(root / "installed", digest, github_asset_id="12345", disk_reserve_bytes=0)
    assert calls == []


def test_private_asset_and_presigned_url_sources_are_mutually_exclusive(github_network_fixture, monkeypatch):
    root, _, digest, calls, provide = github_network_fixture
    provide([])
    monkeypatch.setenv("ORCA_611_ARCHIVE_URL", PRIVATE_URL)
    with pytest.raises(installer.InstallError, match="Choose one archive source"):
        installer.install(root / "installed", digest, github_asset_id="12345", disk_reserve_bytes=0)
    assert calls == []


def test_presigned_url_mode_does_not_use_github_token(network_fixture, monkeypatch):
    root, provide = network_fixture
    digest = provide(archive_bytes())
    monkeypatch.setenv("GITHUB_TOKEN", "\ninvalid-token-would-fail-if-read")
    binary = installer.install(root / "installed", digest, disk_reserve_bytes=0)
    assert binary.read_bytes() == PAYLOAD


@pytest.mark.parametrize("redirected", [False, True])
def test_private_asset_download_retains_stream_byte_limit(github_network_fixture, redirected):
    root, payload, digest, calls, provide = github_network_fixture
    provide(([api_redirect()] if redirected else []) + [Response(payload, length=False)])
    with pytest.raises(installer.InstallError, match="download byte limit"):
        installer.install(root / "installed", digest, github_asset_id="12345", max_download_bytes=len(payload) - 1, disk_reserve_bytes=0)
    assert len(calls) == (2 if redirected else 1)
    assert not list(root.iterdir())


def test_private_asset_checksum_mismatch_blocks_extraction(github_network_fixture, monkeypatch):
    root, payload, _, _, provide = github_network_fixture
    provide([api_redirect(), Response(payload)])
    monkeypatch.setattr(installer, "_catalogue", lambda *a, **k: pytest.fail("must not unpack mismatched private asset"))
    with pytest.raises(installer.InstallError, match="checksum mismatch"):
        installer.install(root / "installed", "0" * 64, github_asset_id="12345", disk_reserve_bytes=0)
    assert not list(root.iterdir())


def test_private_asset_cli_registers_only_the_installed_binary(github_network_fixture, capsys):
    root, payload, digest, _, provide = github_network_fixture
    provide([api_redirect(), Response(payload)])
    environment = root / "github-env"
    assert installer.main([str(root / "installed"), "--sha256", digest, "--github-asset-id", "12345", "--github-env", str(environment)]) == 0
    binary = (root / "installed/orca-6.1.1/orca").resolve()
    assert capsys.readouterr().out == f"{binary}\n"
    assert environment.read_text() == f"TOPOS_ORCA_EXECUTABLE={binary}\n"
