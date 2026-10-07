"""Install the checksum-pinned official Linux x86_64 xTB 6.7.1 executable."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tarfile
import tempfile
import urllib.request
from pathlib import Path

URL = "https://github.com/grimme-lab/xtb/releases/download/v6.7.1/xtb-6.7.1-linux-x86_64.tar.xz"
ARCHIVE_SHA256 = "62a8d18778286e815292ee53d76ce447daf460a4dea3782c0f25cbac7019b5df"
BINARY_SHA256 = "debf27a9e0fa4bfb5ca75aafe4b90d8211f08ec2f4a482f375a4987212eaa12a"


def install(destination: Path) -> Path:
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ValueError("This pinned release is for Linux x86_64 only")
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    binary = destination / "xtb"
    if binary.exists():
        if hashlib.sha256(binary.read_bytes()).hexdigest() != BINARY_SHA256:
            raise FileExistsError(
                "Existing executable differs; choose a fresh installation directory"
            )
        return binary
    with tempfile.TemporaryDirectory(dir=destination) as staging:
        archive = Path(staging) / "xtb.tar.xz"
        with urllib.request.urlopen(URL, timeout=60) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
            raise ValueError("Official xTB archive checksum mismatch")
        with tarfile.open(archive, "r:xz") as package:
            member = package.getmember("xtb-dist/bin/xtb")
            if not member.isfile():
                raise ValueError("xTB executable must be a regular archive member")
            stream = package.extractfile(member)
            if stream is None:
                raise ValueError("xTB executable absent from archive")
            data = stream.read()
        if hashlib.sha256(data).hexdigest() != BINARY_SHA256:
            raise ValueError("xTB executable checksum mismatch")
        temporary = Path(staging) / "xtb"
        temporary.write_bytes(data)
        temporary.chmod(0o755)
        os.replace(temporary, binary)
        (destination / "installation.json").write_text(
            json.dumps(
                {
                    "url": URL,
                    "archive_sha256": ARCHIVE_SHA256,
                    "binary_sha256": BINARY_SHA256,
                    "version": "6.7.1",
                    "license": "LGPL-3.0-or-later",
                    "license_source": "https://github.com/grimme-lab/xtb/blob/v6.7.1/COPYING",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return binary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(install(args.destination))
