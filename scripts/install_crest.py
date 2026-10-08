"""Install checksum-pinned official Linux x86_64 CREST 3.0.2 (GNU build)."""
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

URL = "https://github.com/crest-lab/crest/releases/download/v3.0.2/crest-gnu-12-ubuntu-latest.tar.xz"
ARCHIVE_SHA256 = "8e5bd18b06f99741ebd7bb71b3a996295f391b2f076aaeab739740f709e9554d"
BINARY_SHA256 = "201db7940796c4af3652245ba7c8e1a4234767f4e19223772fbd83098d5f2142"


def install(destination: Path) -> Path:
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ValueError("This pinned release is for Linux x86_64 only")
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    binary = destination / "crest"
    if binary.exists():
        if hashlib.sha256(binary.read_bytes()).hexdigest() != BINARY_SHA256:
            raise FileExistsError("Existing executable differs; choose a fresh installation directory")
        return binary
    with tempfile.TemporaryDirectory(dir=destination) as staging:
        archive = Path(staging) / "crest.tar.xz"
        with urllib.request.urlopen(URL, timeout=60) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
            raise ValueError("Official CREST archive checksum mismatch")
        with tarfile.open(archive, "r:xz") as package:
            # Extract only named, regular members; never trust archive paths/symlinks.
            for name in ["crest", "LICENSE", "LICENSE.LESSER"]:
                member = package.getmember(f"crest/{name}")
                if not member.isfile():
                    raise ValueError("CREST payload must contain regular archive members")
                stream = package.extractfile(member)
                if stream is None:
                    raise ValueError("CREST payload missing")
                data = stream.read()
                if name == "crest" and hashlib.sha256(data).hexdigest() != BINARY_SHA256:
                    raise ValueError("CREST executable checksum mismatch")
                temporary = Path(staging) / name
                temporary.write_bytes(data)
                temporary.chmod(0o755 if name == "crest" else 0o644)
                os.replace(temporary, destination / name)
        (destination / "installation.json").write_text(json.dumps({
            "url": URL,
            "archive_sha256": ARCHIVE_SHA256,
            "binary_sha256": BINARY_SHA256,
            "version": "3.0.2",
            "build": "GNU 12; static Linux x86_64",
            "license": "LGPL-3.0-or-later",
            "license_source": "https://github.com/crest-lab/crest/tree/v3.0.2",
            "backend_requirement": "TOPOS external-backend profile requires xTB 6.7.1 separately",
        }, indent=2) + "\n", encoding="utf-8")
    return binary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(install(args.destination))
