"""Install a reviewed, licensed ORCA 6.1.1 tar archive without executing it.

The source is either a direct ORCA_611_ARCHIVE_URL or an explicitly selected
GitHub release asset in GITHUB_REPOSITORY, authenticated with GITHUB_TOKEN.
Its reviewed SHA256 must be supplied separately. A digest match proves archive
identity, not licensing, executable compatibility, or the installed version.
Archives containing links are deliberately unsupported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import BinaryIO

DOWNLOAD_LIMIT = 4 * 1024**3
EXPANDED_LIMIT = 12 * 1024**3
MEMBER_LIMIT = 100_000
DISK_RESERVE = 512 * 1024**2
CHUNK_BYTES = 1024**2
MANIFEST_NAME = "topos-orca-installation.json"
SCRATCH_PREFIX = ".topos-orca-download-"
USER_AGENT = "CoChem-TOPOS-ORCA-installer/0.1.0"


class InstallError(ValueError):
    """A deliberately redacted installer error suitable for workflow output."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise InstallError("ORCA archive redirects are prohibited; use a direct HTTPS URL")


class _InspectApiRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Returning None makes urllib raise HTTPError instead of following it.
        # The asset path handles only one 302 after validating its destination.
        return None


class _BoundedMetadata(tarfile.TarInfo):
    def _proc_member(self, package):
        # Check before stdlib reads extension bodies. Recent Python tarfile
        # versions bypass public frombuf() inside fromtarfile().
        extensions = {tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK}
        if self.type in extensions and self.size > 64 * 1024:
            raise InstallError("ORCA archive metadata extension exceeds its safety limit")
        if self.type == tarfile.GNUTYPE_SPARSE:
            raise InstallError("ORCA archive contains an unsupported sparse member")
        return super()._proc_member(package)

    def _proc_gnusparse_00(self, *args, **kwargs):
        raise InstallError("ORCA archive contains an unsupported sparse member")

    def _proc_gnusparse_01(self, *args, **kwargs):
        raise InstallError("ORCA archive contains an unsupported sparse member")

    def _proc_gnusparse_10(self, *args, **kwargs):
        raise InstallError("ORCA archive contains an unsupported sparse member")


def _deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise InstallError("ORCA installation exceeded its total time limit")


def _space(path: Path, needed: int, reserve: int) -> None:
    if shutil.disk_usage(path).free < needed + reserve:
        raise InstallError("Insufficient temporary disk space for ORCA plus the required reserve")


def _root_and_destination(destination: Path) -> tuple[Path, Path]:
    configured = os.environ.get("RUNNER_TEMP")
    if not configured:
        raise InstallError("RUNNER_TEMP is required for a confined installation")
    root = Path(configured).resolve(strict=True)
    if not root.is_dir():
        raise InstallError("RUNNER_TEMP must name an existing directory")
    target = destination.expanduser().absolute()
    if any(ord(char) < 32 or ord(char) == 127 for char in str(target)):
        raise InstallError("Installation paths cannot contain control characters")
    # Do not traverse pre-existing symlinks, even when their targets are inside
    # the runner directory. The final directory must be newly created here.
    for component in (target, *target.parents):
        if component.is_symlink():
            raise InstallError("Installation paths cannot traverse symlinks")
    target = target.resolve()
    if target == root or not target.is_relative_to(root):
        raise InstallError("Installation destination must be strictly inside RUNNER_TEMP")
    if target.exists():
        raise InstallError("ORCA installation requires a fresh destination directory")
    return root, target


def _has_controls(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _remaining_timeout(timeout: float, deadline: float) -> float:
    _deadline(deadline)
    return min(timeout, max(0.001, deadline - time.monotonic()))


def _open_download_response(github_asset_id: str | None, *, timeout: float, deadline: float):
    # Both branches retain Python's certificate and hostname validation and
    # the runner's configured HTTPS proxy. They never silently switch sources.
    if github_asset_id is not None:
        return _open_github_asset(github_asset_id, timeout=timeout, deadline=deadline)
    url = os.environ.get("ORCA_611_ARCHIVE_URL", "")
    try:
        parsed = urllib.parse.urlsplit(url)
        valid = parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.fragment
    except (ValueError, TypeError):
        valid = False
    if not valid or _has_controls(url):
        raise InstallError("ORCA_611_ARCHIVE_URL must contain a direct HTTPS URL without userinfo or a fragment")
    return urllib.request.build_opener(_NoRedirect()).open(url, timeout=_remaining_timeout(timeout, deadline))


def _open_github_asset(asset_id: str, *, timeout: float, deadline: float):
    if os.environ.get("ORCA_611_ARCHIVE_URL"):
        raise InstallError("Choose one archive source; unset ORCA_611_ARCHIVE_URL when selecting a GitHub asset")
    if not isinstance(asset_id, str) or re.fullmatch(r"[1-9][0-9]*", asset_id) is None:
        raise InstallError("GitHub asset ID must be a positive decimal identifier")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    owner = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
    if re.fullmatch(owner + r"/[A-Za-z0-9_.-]{1,100}", repository) is None or repository.split("/")[-1] in {".", ".."}:
        raise InstallError("GITHUB_REPOSITORY must contain a valid owner/repository identifier")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token or any(ord(char) <= 32 or ord(char) > 126 for char in token):
        raise InstallError("GitHub asset mode requires a nonempty GITHUB_TOKEN without whitespace or control characters")
    endpoint = f"https://api.github.com/repos/{repository}/releases/assets/{asset_id}"
    request = urllib.request.Request(endpoint, headers={
        "Accept": "application/octet-stream",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    })
    try:
        response = urllib.request.build_opener(_InspectApiRedirect()).open(request, timeout=_remaining_timeout(timeout, deadline))
    except urllib.error.HTTPError as failure:
        # HTTPError is also a closable response. Its URL/message are private;
        # inspect the numeric status and headers without exposing the error.
        response = failure
    if response.status == 200:
        return response
    if response.status != 302:
        response.close()
        raise InstallError("GitHub release asset request was denied or returned an unsupported status") from None
    try:
        locations = response.headers.get_all("Location") if hasattr(response.headers, "get_all") else [response.headers.get("Location")]
        location = locations[0] if locations and len(locations) == 1 else None
    finally:
        response.close()
    try:
        redirected = urllib.parse.urlsplit(location) if isinstance(location, str) else None
        safe = (
            redirected is not None and redirected.scheme == "https"
            and redirected.hostname == "release-assets.githubusercontent.com"
            and redirected.port in {None, 443}
            and redirected.username is None and redirected.password is None
            and "#" not in location and not _has_controls(location)
        )
    except (ValueError, TypeError):
        safe = False
    if not safe:
        raise InstallError("GitHub asset redirect must target the permitted HTTPS release-assets host")
    # Construct a new request and opener, with no Authorization, Cookie, or
    # Referer headers. The authenticated API Request is never reused at the CDN.
    download = urllib.request.Request(location, headers={"Accept": "application/octet-stream", "User-Agent": USER_AGENT})
    return urllib.request.build_opener(_NoRedirect()).open(download, timeout=_remaining_timeout(timeout, deadline))


def _download(archive: Path, *, limit: int, timeout: float, deadline: float, reserve: int, github_asset_id: str | None = None) -> str:
    digest = hashlib.sha256()
    downloaded = 0
    try:
        _deadline(deadline)
        with _open_download_response(github_asset_id, timeout=timeout, deadline=deadline) as response, archive.open("xb") as output:
            if response.status != 200:
                raise InstallError("ORCA archive server did not return HTTP 200")
            header = response.headers.get("Content-Length")
            if header is not None:
                try:
                    advertised = int(header)
                except (TypeError, ValueError):
                    raise InstallError("ORCA archive Content-Length is invalid") from None
                if advertised < 0 or advertised > limit:
                    raise InstallError("ORCA archive exceeds the download byte limit")
                _space(archive.parent, advertised, reserve)
            while True:
                _deadline(deadline)
                # HTTPResponse.read(n) can wait for n bytes while a peer keeps
                # resetting its socket timeout with a drip feed. read1 issues
                # at most one underlying read, so the deadline is rechecked.
                transport = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                if transport is not None:
                    transport.settimeout(min(timeout, max(0.001, deadline - time.monotonic())))
                chunk = response.read1(min(CHUNK_BYTES, limit - downloaded + 1))
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > limit:
                    raise InstallError("ORCA archive exceeds the download byte limit")
                _space(archive.parent, len(chunk), reserve)
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
            if header is not None and downloaded != advertised:
                raise InstallError("ORCA archive response is incomplete or has inconsistent size")
    except InstallError:
        raise
    except Exception:
        # urllib/SSL/proxy exceptions can include the complete presigned URL.
        # Never chain, format, log, or return their original exception text.
        raise InstallError("ORCA archive download failed; check the selected source credentials and HTTPS access") from None
    return digest.hexdigest()


def _member_path(member: tarfile.TarInfo) -> PurePosixPath | None:
    name = member.name
    if not name or "\\" in name or ":" in name or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise InstallError("ORCA archive contains an unsafe member path")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise InstallError("ORCA archive contains an absolute or traversal member path")
    if not path.parts:
        if member.isdir():
            return None  # The conventional './' tar root entry.
        raise InstallError("ORCA archive has a non-directory root entry")
    if path == PurePosixPath(MANIFEST_NAME):
        raise InstallError("ORCA archive collides with the installation manifest")
    if path.parts[0].startswith(SCRATCH_PREFIX):
        raise InstallError("ORCA archive collides with reserved installation scratch paths")
    return path


def _catalogue(archive: Path, *, max_members: int, max_bytes: int, deadline: float) -> tuple[list[tuple[tarfile.TarInfo, PurePosixPath | None]], PurePosixPath, int]:
    entries: list[tuple[tarfile.TarInfo, PurePosixPath | None]] = []
    seen: set[PurePosixPath | None] = set()
    regular: set[PurePosixPath] = set()
    directories: set[PurePosixPath] = set()
    executables: list[PurePosixPath] = []
    expanded = 0
    with tarfile.open(archive, "r:*", tarinfo=_BoundedMetadata) as package:
        for member in package:
            _deadline(deadline)
            if len(entries) >= max_members:
                raise InstallError("ORCA archive exceeds the member count limit")
            path = _member_path(member)
            if path in seen:
                raise InstallError("ORCA archive contains duplicate normalized paths")
            seen.add(path)
            if member.issym() or member.islnk():
                raise InstallError("ORCA archive compatibility failure: symbolic and hard links are unsupported")
            if not (member.isfile() or member.isdir()) or member.issparse():
                raise InstallError("ORCA archive contains an unsupported special or sparse member")
            if member.size < 0 or (member.isdir() and member.size != 0):
                raise InstallError("ORCA archive contains an invalid member size")
            if member.isfile():
                expanded += member.size
                if expanded > max_bytes:
                    raise InstallError("ORCA archive exceeds the expanded byte limit")
                regular.add(path)
                if path.name == "orca" and member.mode & 0o111:
                    executables.append(path)
            elif path is not None:
                directories.add(path)
            entries.append((member, path))
    for path in regular | directories:
        if any(parent in regular for parent in path.parents):
            raise InstallError("ORCA archive file conflicts with a directory path")
    if len(executables) != 1:
        raise InstallError("ORCA archive must contain exactly one regular executable named orca")
    return entries, executables[0], expanded


def _copy_member(source: BinaryIO, target: Path, size: int, *, deadline: float, reserve: int) -> None:
    remaining = size
    with target.open("xb") as output:
        while remaining:
            _deadline(deadline)
            chunk = source.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                raise InstallError("ORCA archive member is truncated")
            _space(target.parent, len(chunk), reserve)
            output.write(chunk)
            remaining -= len(chunk)
        output.flush()
        os.fsync(output.fileno())


def install(
    destination: Path,
    sha256: str,
    *,
    github_asset_id: str | None = None,
    max_download_bytes: int = DOWNLOAD_LIMIT,
    max_expanded_bytes: int = EXPANDED_LIMIT,
    max_members: int = MEMBER_LIMIT,
    disk_reserve_bytes: int = DISK_RESERVE,
    socket_timeout_seconds: float = 30.0,
    total_timeout_seconds: float = 900.0,
) -> Path:
    """Stream, verify, and safely unpack into a fresh runner-local directory.

    Limits are keyword parameters for isolated infrastructure tests. No URL
    parameter is accepted. The archive's own programs are never executed.
    """
    if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-fA-F]{64}", sha256) is None:
        raise InstallError("Reviewed SHA256 must contain exactly 64 hexadecimal characters")
    if any(not isinstance(n, int) or n <= 0 for n in (max_download_bytes, max_expanded_bytes, max_members)):
        raise InstallError("Archive size and member limits must be positive integers")
    if not isinstance(disk_reserve_bytes, int) or disk_reserve_bytes < 0:
        raise InstallError("Disk reserve must be a nonnegative integer")
    if any(not isinstance(t, (float, int)) or not (0 < t < float("inf")) for t in (socket_timeout_seconds, total_timeout_seconds)):
        raise InstallError("Installation timeouts must be finite and positive")
    created: Path | None = None
    deadline = time.monotonic() + total_timeout_seconds
    try:
        root, target = _root_and_destination(Path(destination))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(exist_ok=False)
        created = target
        _space(root, 0, disk_reserve_bytes)
        # Keep every licensed byte under the installation root so the workflow
        # can clean interrupted downloads by removing its one owned directory.
        with tempfile.TemporaryDirectory(prefix=SCRATCH_PREFIX, dir=target) as scratch:
            archive = Path(scratch) / "archive.tar"
            actual = _download(archive, limit=max_download_bytes, timeout=min(socket_timeout_seconds, total_timeout_seconds), deadline=deadline, reserve=disk_reserve_bytes, github_asset_id=github_asset_id)
            if actual != sha256.lower():
                raise InstallError("ORCA archive checksum mismatch; nothing was extracted")
            entries, executable, expanded = _catalogue(archive, max_members=max_members, max_bytes=max_expanded_bytes, deadline=deadline)
            _space(root, expanded, disk_reserve_bytes)
            with tarfile.open(archive, "r:*", tarinfo=_BoundedMetadata) as package:
                for member, relative in entries:
                    _deadline(deadline)
                    if relative is None:
                        continue
                    path = target.joinpath(*relative.parts)
                    if member.isdir():
                        path.mkdir(parents=True, exist_ok=True)
                        path.chmod(0o755)
                        continue
                    path.parent.mkdir(parents=True, exist_ok=True)
                    stream = package.extractfile(member)
                    if stream is None:
                        raise InstallError("ORCA archive member cannot be read")
                    with stream:
                        _copy_member(stream, path, member.size, deadline=deadline, reserve=disk_reserve_bytes)
                    path.chmod(0o755 if member.mode & 0o111 else 0o644)
            binary = target.joinpath(*executable.parts).resolve(strict=True)
            if not binary.is_file() or binary.is_symlink() or not os.access(binary, os.X_OK):
                raise InstallError("Installed ORCA entry is not a regular executable")
            with (target / MANIFEST_NAME).open("x", encoding="utf-8") as manifest:
                json.dump({"archive_sha256": actual, "expected_version": "6.1.1"}, manifest, indent=2)
                manifest.write("\n")
            _deadline(deadline)
            return binary
    except Exception as exc:
        if created is not None:
            shutil.rmtree(created, ignore_errors=True)
        if isinstance(exc, InstallError):
            raise
        raise InstallError("ORCA installation failed while validating or extracting the archive") from None


def _write_github_env(path: Path, executable: Path) -> None:
    # Refuse final-path symlinks and use the runner-provided append-only format.
    if path.is_symlink():
        raise InstallError("GitHub environment file cannot be a symlink")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(f"TOPOS_ORCA_EXECUTABLE={executable}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--github-asset-id", help="Private release asset in GITHUB_REPOSITORY; requires GITHUB_TOKEN")
    args = parser.parse_args(argv)
    try:
        binary = install(args.destination, args.sha256, github_asset_id=args.github_asset_id)
        if args.github_env is not None:
            _write_github_env(args.github_env, binary)
    except Exception as exc:
        message = str(exc) if isinstance(exc, InstallError) else "ORCA installation or environment registration failed"
        print(message)
        return 1
    print(binary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
