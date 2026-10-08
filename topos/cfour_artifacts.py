"""Confined CFOUR scientific evidence with explicit controlled dependencies.

Basis libraries and native scratch are never snapshot payloads. Their identities
are retained without promising self-contained native re-execution. Links are
recorded as text and never traversed. Collection failures stay secondary.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .engines import EngineParseError, EngineResult
from .models import Artifact
from .storage import (
    IntegrityError,
    atomic_json,
    confined_file,
    file_digest,
    json_bytes,
    read_json,
    safe_relative,
)

POLICY_SCHEMA = 'topos-cfour-scientific-evidence/1'
POLICY_NAME = 'cfour-evidence-policy.json'
PORTABLE_NAMES = frozenset({'ZMAT', 'protocol.json', 'native-result.json',
    'engine.stdout', 'engine.stderr', 'engine-cfour-runtime.json', 'GRD', 'DIPOL', 'EFG', 'FCMFINAL'})
_SCIENTIFIC_FILES = PORTABLE_NAMES | {'GENBAS', POLICY_NAME}
_LICENSED_NAMES = frozenset({'GENBAS', 'ECPDATA'})


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
        # Preserve the exact native UTF-8 bytes in downstream hash bindings;
        # universal-newline text loading can silently normalize CRLF to LF.
        return confined_file(folder, name).read_bytes().decode('utf-8')
    except (IntegrityError, OSError, UnicodeError) as exc:
        raise EngineParseError('CFOUR native evidence is not a confined regular text file: ' + name) from exc


def _dependency_identity(value):
    if (not isinstance(value, dict) or not Path(str(value.get('path', ''))).is_absolute()
            or not re.fullmatch(r'[0-9a-f]{64}', str(value.get('sha256', '')))
            or type(value.get('size_bytes')) is not int or value['size_bytes'] < 1):
        raise IntegrityError('CFOUR controlled dependency lacks an exact path/hash/size identity')
    return {key: value[key] for key in ('path', 'sha256', 'size_bytes')}


def finalize_artifacts(result: EngineResult, folder: Path) -> None:
    """Retain permitted scientific files, never licensed basis or native scratch."""
    artifacts, links, errors, regular, controlled = [], [], [], {}, {}
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
                    if name in _SCIENTIFIC_FILES:
                        errors.append('Scientific CFOUR artifact cannot be a symlink: ' + relative)
                    continue
                if not path.is_file() or name == POLICY_NAME:
                    continue
                try:
                    safe = confined_file(folder, relative)
                    regular[relative] = {'sha256': file_digest(safe), 'size_bytes': safe.stat().st_size}
                    if name == 'engine-cfour-runtime.json':
                        receipt = read_json(safe)
                        if 'controlled_runtime_dependencies' in receipt:
                            declared = receipt['controlled_runtime_dependencies']
                            if not isinstance(declared, dict) or set(declared) != _LICENSED_NAMES:
                                raise IntegrityError('CFOUR runtime dependency inventory is incomplete')
                            observed = {key: _dependency_identity(value) for key, value in declared.items()}
                            if controlled and controlled != observed:
                                raise IntegrityError('CFOUR dependency identities changed between evaluations')
                            controlled = observed
                except (IntegrityError, OSError) as exc:
                    errors.append(relative + ': ' + str(exc))
        basis = result.metadata.get('basis_library', {})
        if not isinstance(basis, dict):
            raise IntegrityError('CFOUR basis library identity must be an object')
        licensed_hashes = {v['sha256'] for v in controlled.values()}
        if re.fullmatch(r'[0-9a-f]{64}', str(basis.get('sha256', ''))):
            licensed_hashes.add(basis['sha256'])
        licensed_hashes.update(value['sha256'] for name, value in regular.items() if Path(name).name.upper() in _LICENSED_NAMES)
        retained, omitted = {}, []
        for relative, identity in regular.items():
            name = Path(relative).name
            licensed = name.upper() in _LICENSED_NAMES or identity['sha256'] in licensed_hashes
            if licensed or name not in PORTABLE_NAMES:
                omitted.append({'path': relative, **identity,
                                'classification': 'licensed-basis' if licensed else 'native-scratch'})
            else:
                retained[relative] = identity
                artifacts.append(Artifact(path=str((folder/relative).absolute()), **identity,
                    role='engine-input' if name in {'ZMAT', 'protocol.json'} else 'raw-output'))
        policy = {'schema': POLICY_SCHEMA, 'source_directory': str(folder.absolute()),
            'retained_files': retained, 'omitted_files': omitted, 'omitted_links': links,
            'controlled_basis_library': basis, 'controlled_runtime_dependencies': controlled,
            'native_rerun_self_contained': False, 'licensed_assets_included': False,
            'scope': 'Scientific evidence only; native re-execution requires separately authorized unchanged CFOUR runtime and basis libraries'}
        path = folder/POLICY_NAME
        if path.is_symlink():
            raise IntegrityError('CFOUR evidence policy cannot overwrite a symlink')
        atomic_json(path, policy)
        digest = file_digest(path)
        result.metadata.update(cfour_evidence_policy=policy, cfour_evidence_policy_sha256=digest)
        artifacts.append(Artifact(path=str(path.absolute()), sha256=digest, size_bytes=path.stat().st_size,
                                  role='cfour-evidence-policy'))
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


def _artifact_identity(value: dict) -> dict:
    if (not isinstance(value, dict)
            or not re.fullmatch(r'[0-9a-f]{64}', str(value.get('sha256', '')))
            or type(value.get('size_bytes')) is not int or value['size_bytes'] < 0):
        raise IntegrityError('Scientific export artifact lacks an exact hash/size identity')
    return {key: value[key] for key in ('sha256', 'size_bytes')}


def validate_scientific_export_membership(record: dict, manifest: dict) -> dict:
    """Reject unqualified CFOUR payloads; storage validity is not native acceptance."""
    if not isinstance(record, dict) or not isinstance(manifest, dict):
        raise IntegrityError('Scientific export requires verified record and manifest objects')
    raw_members = manifest.get('artifacts')
    if not isinstance(raw_members, list):
        raise IntegrityError('Scientific export manifest lacks artifact membership')
    members = {}
    for item in raw_members:
        if not isinstance(item, dict):
            raise IntegrityError('Scientific export manifest contains an invalid artifact')
        name = safe_relative(item.get('path'))
        _artifact_identity(item)
        if name in members:
            raise IntegrityError('Duplicate scientific export artifact membership')
        # Apply this globally, including top-level artifacts and policyless runs.
        if Path(name).name.upper() in _LICENSED_NAMES:
            raise IntegrityError('Licensed CFOUR basis bytes cannot be included in scientific export')
        members[name] = item
    raw_attempts = record.get('attempts', [])
    if not isinstance(raw_attempts, list) or any(not isinstance(a, dict) for a in raw_attempts):
        raise IntegrityError('Scientific export record has invalid attempt membership')
    attempts = [a for a in raw_attempts if a.get('engine') == 'cfour' and a.get('artifacts')]
    if not attempts:
        return {'cfour_attempts': 0, 'scope': 'No CFOUR native artifacts declared'}
    licensed_hashes = set()
    for attempt in attempts:
        metadata = attempt.get('metadata', {})
        policy = metadata.get('cfour_evidence_policy') if isinstance(metadata, dict) else None
        if (not isinstance(policy, dict) or policy.get('schema') != POLICY_SCHEMA
                or policy.get('native_rerun_self_contained') is not False
                or policy.get('licensed_assets_included') is not False):
            raise IntegrityError('CFOUR export requires an explicit scientific-only controlled-dependency policy')
        encoded = json_bytes(policy) + b'\n'
        digest = hashlib.sha256(encoded).hexdigest()
        artifacts = attempt['artifacts']
        if not isinstance(artifacts, list) or any(not isinstance(a, dict) for a in artifacts):
            raise IntegrityError('CFOUR scientific export has invalid artifact membership')
        evidence = [a for a in artifacts if a.get('role') == 'cfour-evidence-policy']
        if (metadata.get('cfour_evidence_policy_sha256') != digest or len(evidence) != 1
                or evidence[0].get('sha256') != digest
                or Path(safe_relative(evidence[0].get('path'))).name != POLICY_NAME):
            raise IntegrityError('CFOUR scientific evidence policy is not bound to its exact artifact')
        prefix = Path(evidence[0]['path']).parent
        retained = policy.get('retained_files')
        if not isinstance(retained, dict):
            raise IntegrityError('CFOUR scientific export lacks exact retained membership')
        expected = {(prefix/POLICY_NAME).as_posix(): {'sha256': digest, 'size_bytes': len(encoded)}}
        for relative, identity in retained.items():
            safe_relative(relative)
            if Path(relative).name not in PORTABLE_NAMES:
                raise IntegrityError('CFOUR scientific export declares unsupported native scratch')
            expected[(prefix/relative).as_posix()] = _artifact_identity(identity)
        seen = set()
        for artifact in artifacts:
            name = safe_relative(artifact.get('path'))
            if name in seen:
                raise IntegrityError('Duplicate CFOUR scientific export attempt artifact')
            seen.add(name)
            identity = _artifact_identity(artifact)
            entry = members.get(name)
            if entry is None or _artifact_identity(entry) != identity:
                raise IntegrityError('CFOUR attempt disagrees with the verified snapshot manifest')
            if artifact.get('role') == 'matrix-native-component-result' and name == (prefix/'matrix-component-result.json').as_posix():
                continue
            if name not in expected or expected[name] != identity:
                raise IntegrityError('CFOUR scientific export includes undeclared native payload')
        if not set(expected) <= seen:
            raise IntegrityError('CFOUR scientific export is missing declared evidence')
        dependencies = policy.get('controlled_runtime_dependencies')
        if not isinstance(dependencies, dict) or (dependencies and set(dependencies) != _LICENSED_NAMES):
            raise IntegrityError('CFOUR scientific export has incomplete controlled dependencies')
        for entry in dependencies.values():
            licensed_hashes.add(_dependency_identity(entry)['sha256'])
        source = policy.get('source_directory')
        if (not isinstance(source, str) or not Path(source).is_absolute()
                or Path(source).as_posix() != source or '..' in Path(source).parts):
            raise IntegrityError('CFOUR scientific export lacks its original native directory')
        basis = policy.get('controlled_basis_library')
        if not isinstance(basis, dict):
            raise IntegrityError('CFOUR scientific export has invalid basis identity')
        if basis.get('sha256'):
            if not re.fullmatch(r'[0-9a-f]{64}', str(basis['sha256'])):
                raise IntegrityError('CFOUR scientific export has invalid basis digest')
            if not Path(str(basis.get('path', ''))).is_absolute():
                raise IntegrityError('CFOUR scientific export has invalid basis path')
            licensed_hashes.add(basis['sha256'])
        observed_basis = metadata.get('basis_library', {})
        requested = metadata.get('requested_protocol', {})
        if not isinstance(observed_basis, dict) or not isinstance(requested, dict):
            raise IntegrityError('CFOUR scientific export has invalid native basis metadata')
        if observed_basis and basis != observed_basis:
            raise IntegrityError('CFOUR scientific export basis differs from the observed native basis')
        requested_hash = requested.get('genbas_sha256')
        if requested_hash is not None:
            if not re.fullmatch(r'[0-9a-f]{64}', str(requested_hash)):
                raise IntegrityError('CFOUR scientific export has invalid requested GENBAS identity')
            # The native adapter resolves an input path alias before recording
            # the controlled library path. Offline export binds requested bytes;
            # it cannot resolve aliases on the originating machine.
            if basis and basis.get('sha256') != requested_hash:
                raise IntegrityError('CFOUR scientific export basis differs from the requested protocol')
            # A prelaunch failure can lack observed basis metadata; its declared
            # protocol digest still prohibits exporting a renamed library copy.
            licensed_hashes.add(requested_hash)
        if dependencies and (not basis or any(dependencies['GENBAS'][key] != basis.get(key)
                                              for key in ('path', 'sha256'))):
            raise IntegrityError('CFOUR scientific export basis differs from audited runtime dependencies')
        omitted = policy.get('omitted_files')
        if not isinstance(omitted, list):
            raise IntegrityError('CFOUR scientific export lacks controlled omission inventory')
        excluded = set(retained)
        for entry in omitted:
            _artifact_identity(entry)
            relative = safe_relative(entry.get('path'))
            if relative in excluded or (prefix/relative).as_posix() in members:
                raise IntegrityError('Duplicate or retained CFOUR scientific export omission')
            excluded.add(relative)
            if entry.get('classification') not in {'licensed-basis', 'native-scratch'}:
                raise IntegrityError('CFOUR scientific export has an invalid omission classification')
            if entry['classification'] == 'licensed-basis':
                licensed_hashes.add(entry['sha256'])
        links = policy.get('omitted_links')
        if not isinstance(links, list):
            raise IntegrityError('CFOUR scientific export lacks native link omission inventory')
        for entry in links:
            if (not isinstance(entry, dict) or not isinstance(entry.get('link_text'), str)
                    or entry.get('disposition') != 'not-followed-or-retained'):
                raise IntegrityError('CFOUR scientific export has invalid native link omission')
            relative = safe_relative(entry.get('path'))
            if relative in excluded or (prefix/relative).as_posix() in members:
                raise IntegrityError('Duplicate or retained CFOUR scientific export link omission')
            excluded.add(relative)
    if any(a['sha256'] in licensed_hashes for a in members.values()):
        raise IntegrityError('Licensed CFOUR basis bytes cannot be included in scientific export, including renamed copies')
    return {'cfour_attempts': len(attempts), 'native_rerun_self_contained': False,
            'scope': 'Verified scientific-only snapshot membership; native science and runtime authorization remain separate'}
