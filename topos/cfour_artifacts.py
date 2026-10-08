"""Confined CFOUR evidence collection, without following native scratch links.

Links are recorded as link text, never as the target's bytes or scientific
results. Required scientific input/output links fail closed. Collection errors
remain secondary diagnostics and cannot erase the original solver failure.
"""
from __future__ import annotations

import os
from pathlib import Path

from .engines import EngineParseError, EngineResult
from .models import Artifact
from .storage import IntegrityError, confined_file, file_digest

_SCIENTIFIC_FILES = frozenset({'ZMAT', 'GENBAS', 'protocol.json', 'native-result.json',
    'engine.stdout', 'engine.stderr', 'engine-cfour-runtime.json', 'GRD', 'DIPOL', 'EFG', 'FCMFINAL'})


def native_text(folder: Path, name: str, *, required: bool = False,
                process_path: str | None = None) -> str | None:
    """Read only the requested regular native file inside this evaluation."""
    if folder.is_symlink() or Path(name).name != name:
        raise EngineParseError('Native CFOUR evidence requires a confined nonsymlink directory and filename')
    path = folder / name
    if process_path is not None and Path(process_path).absolute() != path.absolute():
        raise EngineParseError('CFOUR process output path differs from the declared native evaluation')
    if path.is_symlink():
        raise EngineParseError('CFOUR native evidence is not a confined regular text file: ' + name)
    if not path.exists():
        if required:
            raise EngineParseError('Required CFOUR native evidence is missing: ' + name)
        return None
    try:
        return confined_file(folder, name).read_text(encoding='utf-8')
    except (IntegrityError, OSError, UnicodeError) as exc:
        raise EngineParseError('CFOUR native evidence is not a confined regular text file: ' + name) from exc


def finalize_artifacts(result: EngineResult, folder: Path) -> None:
    """Collect regular evidence and link metadata; never mask a primary error."""
    artifacts, links, errors = [], [], []
    def traversal_error(error):
        raise error
    try:
        if folder.is_symlink():
            raise IntegrityError('CFOUR evidence directory cannot be a symlink')
        for base, directories, names in os.walk(folder, followlinks=False, onerror=traversal_error):
            directories.sort()
            for name in sorted([*directories, *names]):
                path = Path(base) / name
                relative = path.relative_to(folder).as_posix()
                if path.is_symlink():
                    links.append({'path': relative, 'link_text': os.readlink(path),
                                  'disposition': 'not-followed-or-retained'})
                    if path.name in _SCIENTIFIC_FILES:
                        errors.append('Scientific CFOUR artifact cannot be a symlink: ' + relative)
                    continue
                if not path.is_file():
                    continue
                try:
                    safe = confined_file(folder, relative)
                    artifacts.append(Artifact(path=str(safe), sha256=file_digest(safe),
                        size_bytes=safe.stat().st_size,
                        role='engine-input' if name in {'ZMAT', 'GENBAS', 'protocol.json'} else 'raw-output'))
                except (IntegrityError, OSError) as exc:
                    errors.append(relative + ': ' + str(exc))
    except (IntegrityError, OSError) as exc:
        errors.append(str(exc))
    result.artifacts = sorted(artifacts, key=lambda item: item.path)
    if links:
        result.diagnostics['artifact_links'] = sorted(links, key=lambda item: item['path'])
    if errors:
        result.diagnostics['artifact_error'] = '; '.join(errors)
        if result.status in {'completed', 'partial'}:
            result.status = 'failed'
        result.converged, result.energy_hartree, result.gradient_hartree_per_bohr = False, None, None
        result.diagnostics.setdefault('reason', 'CFOUR evidence collection failed: ' + '; '.join(errors))
