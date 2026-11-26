"""Hard CI AST, regex, M1 _scoped_attr, and artifact firewall gate.

Enforces:
- Zero mock/monkeypatch/fake/simulation patterns across the repository
- Empty .anti_spoof_amnesty.json if present
- Zero _scoped_attr / _scoped_attrs outside tests/ (topos/, src/, scripts/, cochem_topos_web.py)
- Frozen _scoped_attr call-site inventory cap in tests/m1_scoped_attr_inventory.json
- Zero leaked mockup PNG/PDF artifacts (cochem:mockup=true / NOT SCIENTIFIC DATA / MOCKUP — VISUAL LAYOUT ONLY)
"""

from __future__ import annotations

import ast
import json
import os
import re
import struct
import subprocess
import zlib
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SELF_PATH = Path(__file__).resolve()
SELF_REL_PATH = SELF_PATH.relative_to(REPO_ROOT).as_posix()
M1_INVENTORY_PATH = REPO_ROOT / "tests" / "m1_scoped_attr_inventory.json"

EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "build",
        "dist",
        "__pycache__",
        ".pytest_cache",
        ".conda",
        ".mypy_cache",
        ".ruff_cache",
        ".eggs",
        "node_modules",
    }
)

EXCLUDED_REL_PATHS = frozenset(
    {
        "ci_tools/anti_spoof_linter.py",
        "src/cochem_base/core_engine/anti_spoof_linter.py",
        SELF_REL_PATH,
    }
)

PROHIBITED_MODULES = frozenset(
    {
        "unittest.mock",
        "mock",
        "pytest_mock",
        "responses",
        "vcrpy",
        "vcr",
        "requests_mock",
        "requests-mock",
    }
)

PROHIBITED_SYMBOLS = frozenset(
    {
        "MagicMock",
        "Mock",
        "AsyncMock",
        "PropertyMock",
        "create_autospec",
        "NonCallableMock",
        "mock_open",
        "monkeypatch",
        "mocker",
        "requests_mock",
    }
)

PROHIBITED_PREFIXES = (
    "fake_",
    "FAKE_",
)

PROHIBITED_EXACT_NAMES = frozenset(
    {
        "generate_deterministic_solver_output",
        "poll_or_simulate_execution",
        "COLAB_WORKER_FAKE_GPU_NAME",
        "simulated_temp",
        "dummy_force",
    }
)

SCOPED_ATTR_NAMES = frozenset({"_scoped_attr", "_scoped_attrs"})
NON_TEST_EXPLICIT_TARGETS = ("topos", "src", "scripts", "cochem_topos_web.py")

SIMULATION_MODE_PATTERN = re.compile(r"""\bmode\s*=\s*(['"])simulation\1""")

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MOCKUP_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "cochem:mockup=true",
        re.compile(
            r"cochem:mockup\s*(?:=\s*['\"]?true['\"]?|\x00\s*true|>\s*true\s*<)",
            re.IGNORECASE,
        ),
    ),
    (
        "MOCKUP — VISUAL LAYOUT ONLY",
        re.compile(r"MOCKUP\s*(?:\u2014|--|-|\x97)\s*VISUAL\s+LAYOUT\s+ONLY", re.IGNORECASE),
    ),
    (
        "NOT SCIENTIFIC DATA",
        re.compile(r"NOT\s+SCIENTIFIC\s+DATA", re.IGNORECASE),
    ),
)


def _is_prohibited_module(module_name: str) -> bool:
    return any(
        module_name == banned or module_name.startswith(banned + ".")
        for banned in PROHIBITED_MODULES
    )


def _is_prohibited_identifier(name: str) -> bool:
    return name in PROHIBITED_EXACT_NAMES or name.startswith(PROHIBITED_PREFIXES)


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _iter_repo_python_files(repo_root: Path) -> list[Path]:
    discovered: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in EXCLUDED_DIRS and not d.endswith(".egg-info")
        )
        root_path = Path(dirpath)
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            candidate = root_path / filename
            if candidate.resolve() == SELF_PATH:
                continue
            rel = candidate.relative_to(repo_root).as_posix()
            if rel in EXCLUDED_REL_PATHS:
                continue
            discovered.append(candidate)
    return discovered


def scan_python_source(source: str, filename: str = "<memory>") -> list[str]:
    """Scan Python source with AST and regex rules for prohibited constructs."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [f"{filename}:{exc.lineno}: syntax error: {exc.msg}"]

    findings: list[str] = []
    importlib_aliases: set[str] = {"importlib"}
    import_module_aliases: set[str] = {"import_module", "__import__"}
    unittest_aliases: set[str] = {"unittest"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name
                if alias.name == "importlib":
                    importlib_aliases.add(local_name)
                elif alias.name == "unittest":
                    unittest_aliases.add(local_name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        import_module_aliases.add(alias.asname or alias.name)
            elif mod == "builtins":
                for alias in node.names:
                    if alias.name == "__import__":
                        import_module_aliases.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_prohibited_module(alias.name):
                    findings.append(
                        f"{filename}:{node.lineno}: prohibited import '{alias.name}'"
                    )
                if alias.asname and (
                    alias.asname in PROHIBITED_SYMBOLS
                    or _is_prohibited_identifier(alias.asname)
                ):
                    findings.append(
                        f"{filename}:{node.lineno}: prohibited alias '{alias.asname}'"
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if _is_prohibited_module(mod):
                findings.append(
                    f"{filename}:{node.lineno}: prohibited import-from '{mod}'"
                )
            elif mod == "unittest":
                for alias in node.names:
                    if alias.name == "mock":
                        as_clause = f" as {alias.asname}" if alias.asname else ""
                        findings.append(
                            f"{filename}:{node.lineno}: prohibited import 'from {mod} import {alias.name}{as_clause}'"
                        )
            for alias in node.names:
                if alias.name in PROHIBITED_SYMBOLS or _is_prohibited_identifier(alias.name):
                    findings.append(
                        f"{filename}:{node.lineno}: prohibited imported symbol '{alias.name}'"
                    )
                if alias.asname and (
                    alias.asname in PROHIBITED_SYMBOLS
                    or _is_prohibited_identifier(alias.asname)
                ):
                    findings.append(
                        f"{filename}:{node.lineno}: prohibited alias '{alias.asname}'"
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in PROHIBITED_SYMBOLS or _is_prohibited_identifier(node.name):
                findings.append(
                    f"{filename}:{node.lineno}: prohibited definition '{node.name}'"
                )
        elif isinstance(node, ast.arg):
            if node.arg in PROHIBITED_SYMBOLS or _is_prohibited_identifier(node.arg):
                findings.append(
                    f"{filename}:{node.lineno}: prohibited parameter '{node.arg}'"
                )
        elif isinstance(node, ast.Name):
            if node.id in PROHIBITED_SYMBOLS or _is_prohibited_identifier(node.id):
                findings.append(
                    f"{filename}:{node.lineno}: prohibited reference '{node.id}'"
                )
        elif isinstance(node, ast.Attribute):
            if node.attr in PROHIBITED_SYMBOLS or _is_prohibited_identifier(node.attr):
                findings.append(
                    f"{filename}:{node.lineno}: prohibited attribute '.{node.attr}'"
                )
            if node.attr == "mock" and _dotted_name(node.value) in unittest_aliases:
                findings.append(
                    f"{filename}:{node.lineno}: prohibited unittest.mock attribute access '{_dotted_name(node)}'"
                )
        elif isinstance(node, ast.keyword):
            if node.arg and (
                node.arg in PROHIBITED_SYMBOLS or _is_prohibited_identifier(node.arg)
            ):
                findings.append(
                    f"{filename}:{node.lineno}: prohibited keyword '{node.arg}'"
                )
            if (
                node.arg == "mode"
                and isinstance(node.value, ast.Constant)
                and node.value.value == "simulation"
            ):
                findings.append(
                    f"{filename}:{node.lineno}: prohibited simulation mode argument"
                )
        elif isinstance(node, ast.Call):
            callee = _dotted_name(node.func)
            is_dynamic_import = callee in import_module_aliases or any(
                callee == f"{alias}.import_module" for alias in importlib_aliases
            )
            if is_dynamic_import:
                target_arg: ast.AST | None = node.args[0] if node.args else None
                if target_arg is None:
                    for kw in node.keywords:
                        if kw.arg == "name":
                            target_arg = kw.value
                            break
                if (
                    isinstance(target_arg, ast.Constant)
                    and isinstance(target_arg.value, str)
                    and _is_prohibited_module(target_arg.value)
                ):
                    findings.append(
                        f"{filename}:{node.lineno}: prohibited dynamic import '{target_arg.value}'"
                    )

    for match in SIMULATION_MODE_PATTERN.finditer(source):
        lineno = source.count("\n", 0, match.start()) + 1
        findings.append(
            f"{filename}:{lineno}: prohibited simulation mode literal '{match.group(0)}'"
        )

    return findings


def _extract_scoped_attr_target(call: ast.Call) -> str:
    obj = ast.unparse(call.args[0]) if len(call.args) >= 1 else "<unknown>"
    if (
        len(call.args) >= 2
        and isinstance(call.args[1], ast.Constant)
        and isinstance(call.args[1].value, str)
    ):
        attr = call.args[1].value
    elif len(call.args) >= 2:
        attr = ast.unparse(call.args[1])
    else:
        attr = "<unknown>"
    return f"{obj}.{attr}"


def scan_scoped_attr_outside_tests(repo_root: Path) -> list[str]:
    """Fail if _scoped_attr or _scoped_attrs appears anywhere outside tests/."""
    findings: list[str] = []
    candidates: set[Path] = set()
    for py_file in _iter_repo_python_files(repo_root):
        rel = py_file.relative_to(repo_root).as_posix()
        if not rel.startswith("tests/"):
            candidates.add(py_file)
    for explicit in NON_TEST_EXPLICIT_TARGETS:
        target = repo_root / explicit
        if target.is_file() and target.suffix == ".py":
            candidates.add(target)
        elif target.is_dir():
            for py_file in sorted(target.rglob("*.py")):
                rel_parts = py_file.relative_to(repo_root).parts
                if any(part in EXCLUDED_DIRS for part in rel_parts):
                    continue
                candidates.add(py_file)

    for py_file in sorted(candidates):
        rel = py_file.relative_to(repo_root).as_posix()
        if rel in EXCLUDED_REL_PATHS:
            continue
        source = py_file.read_text(encoding="utf-8-sig", errors="replace")
        if "_scoped_attr" not in source:
            continue
        tree = ast.parse(source, filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in SCOPED_ATTR_NAMES:
                findings.append(f"{rel}:{node.lineno}: forbidden definition '{node.name}' outside tests/")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in SCOPED_ATTR_NAMES or alias.asname in SCOPED_ATTR_NAMES:
                        findings.append(f"{rel}:{node.lineno}: forbidden import '{alias.name}' outside tests/")
            elif isinstance(node, ast.Name) and node.id in SCOPED_ATTR_NAMES:
                findings.append(f"{rel}:{node.lineno}: forbidden reference '{node.id}' outside tests/")
            elif isinstance(node, ast.Attribute) and node.attr in SCOPED_ATTR_NAMES:
                findings.append(f"{rel}:{node.lineno}: forbidden attribute '.{node.attr}' outside tests/")
    return findings


def scan_test_scoped_attr_calls(repo_root: Path) -> list[dict[str, object]]:
    """Collect every _scoped_attr call site under tests/ via AST."""
    tests_root = repo_root / "tests"
    if not tests_root.is_dir():
        return []
    sites: list[dict[str, object]] = []
    for py_file in sorted(tests_root.rglob("*.py")):
        rel_parts = py_file.relative_to(repo_root).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue
        rel = py_file.relative_to(repo_root).as_posix()
        if rel == SELF_REL_PATH or py_file.resolve() == SELF_PATH:
            continue
        source = py_file.read_text(encoding="utf-8-sig", errors="replace")
        if "_scoped_attr" not in source:
            continue
        tree = ast.parse(source, filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                is_sa = (isinstance(fn, ast.Name) and fn.id == "_scoped_attr") or (
                    isinstance(fn, ast.Attribute) and fn.attr == "_scoped_attr"
                )
                if is_sa:
                    sites.append(
                        {
                            "file": rel,
                            "line": node.lineno,
                            "target": _extract_scoped_attr_target(node),
                        }
                    )
    sites.sort(key=lambda item: (str(item["file"]), int(item["line"]), str(item["target"])))
    return sites


def validate_scoped_attr_inventory(repo_root: Path, inventory_path: Path) -> list[str]:
    """Verify tests/ _scoped_attr calls never exceed or diverge from the frozen M1 inventory."""
    findings: list[str] = []
    if not inventory_path.is_file():
        return [f"Missing frozen M1 inventory file: {inventory_path}"]

    data = json.loads(inventory_path.read_text(encoding="utf-8"))
    call_sites = data.get("call_sites")
    if not isinstance(call_sites, list):
        return ["m1_scoped_attr_inventory.json: 'call_sites' must be a list"]

    frozen_total = data.get("total_call_count")
    if frozen_total != len(call_sites):
        findings.append(
            f"m1_scoped_attr_inventory.json: total_call_count ({frozen_total}) != len(call_sites) ({len(call_sites)})"
        )
    if data.get("outside_tests_count") != 0:
        findings.append(
            f"m1_scoped_attr_inventory.json: outside_tests_count must be 0, got {data.get('outside_tests_count')!r}"
        )
    if data.get("scientific_engine_callable_swaps") != 0:
        findings.append(
            "m1_scoped_attr_inventory.json: scientific_engine_callable_swaps must be 0"
        )
    note = str(data.get("blind_set_v_a6_exclusion_note", ""))
    if "Blind Set" not in note or "V-A6" not in note:
        findings.append(
            "m1_scoped_attr_inventory.json: missing Blind Set / V-A6 exclusion note"
        )

    allowed_files: set[str] = set()
    allowed_exact_sites: set[tuple[str, int, str]] = set()
    allowed_file_target_counts: Counter[tuple[str, str]] = Counter()
    for entry in call_sites:
        if entry.get("scientific_engine_swap") is not False:
            findings.append(
                f"m1_scoped_attr_inventory.json: entry {entry!r} must declare scientific_engine_swap=false"
            )
        f_rel = str(entry["file"])
        line = int(entry["line"])
        target = str(entry["target"])
        allowed_files.add(f_rel)
        allowed_exact_sites.add((f_rel, line, target))
        allowed_file_target_counts[(f_rel, target)] += 1

    observed = scan_test_scoped_attr_calls(repo_root)
    if isinstance(frozen_total, int) and len(observed) > frozen_total:
        findings.append(
            f"tests/ _scoped_attr call count ({len(observed)}) exceeds frozen M1 cap ({frozen_total})"
        )

    observed_file_target_counts: Counter[tuple[str, str]] = Counter()
    for site in observed:
        f_rel = str(site["file"])
        line = int(site["line"])
        target = str(site["target"])
        observed_file_target_counts[(f_rel, target)] += 1
        if f_rel not in allowed_files:
            findings.append(
                f"{f_rel}:{line}: new file using _scoped_attr not in frozen M1 inventory ({target})"
            )
        elif (f_rel, line, target) not in allowed_exact_sites:
            findings.append(
                f"{f_rel}:{line}: _scoped_attr site ({target}) not listed in frozen M1 inventory"
            )

    for (f_rel, target), obs_count in observed_file_target_counts.items():
        cap = allowed_file_target_counts[(f_rel, target)]
        if obs_count > cap:
            findings.append(
                f"{f_rel}: _scoped_attr target '{target}' count ({obs_count}) exceeds frozen cap ({cap})"
            )

    return findings


def validate_amnesty_files(repo_root: Path) -> list[str]:
    """Ensure every .anti_spoof_amnesty.json in the repository parses strictly to []."""
    findings: list[str] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in EXCLUDED_DIRS and not d.endswith(".egg-info")
        )
        if ".anti_spoof_amnesty.json" not in filenames:
            continue
        amnesty_path = Path(dirpath) / ".anti_spoof_amnesty.json"
        rel = amnesty_path.relative_to(repo_root).as_posix()
        try:
            parsed = json.loads(amnesty_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            findings.append(f"{rel}: invalid JSON ({exc})")
            continue
        if parsed != []:
            findings.append(f"{rel}: expected empty list [], got {parsed!r}")
    return findings


def _extract_png_text_payloads(raw: bytes) -> list[str]:
    """Extract tEXt, zTXt, and iTXt metadata payloads from a PNG byte stream."""
    payloads: list[str] = []
    if not raw.startswith(PNG_SIGNATURE):
        return payloads
    offset = len(PNG_SIGNATURE)
    total = len(raw)
    while offset + 12 <= total:
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        chunk_type = raw[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        if data_end + 4 > total:
            break
        chunk_data = raw[data_start:data_end]
        if chunk_type == b"tEXt":
            payloads.append(chunk_data.decode("latin-1", errors="replace"))
        elif chunk_type == b"zTXt":
            nul = chunk_data.find(b"\x00")
            if nul != -1 and nul + 2 <= len(chunk_data):
                keyword = chunk_data[:nul].decode("latin-1", errors="replace")
                try:
                    text = zlib.decompress(chunk_data[nul + 2 :]).decode("latin-1", errors="replace")
                except zlib.error:
                    text = ""
                payloads.append(f"{keyword}\x00{text}")
        elif chunk_type == b"iTXt":
            nul = chunk_data.find(b"\x00")
            if nul != -1 and nul + 3 <= len(chunk_data):
                keyword = chunk_data[:nul].decode("latin-1", errors="replace")
                comp_flag = chunk_data[nul + 1]
                rest = chunk_data[nul + 3 :]
                parts = rest.split(b"\x00", 2)
                if len(parts) == 3:
                    text_bytes = parts[2]
                    if comp_flag == 1:
                        try:
                            text_bytes = zlib.decompress(text_bytes)
                        except zlib.error:
                            text_bytes = b""
                    text = text_bytes.decode("utf-8", errors="replace")
                    payloads.append(f"{keyword}\x00{text}")
                else:
                    payloads.append(chunk_data.decode("utf-8", errors="replace"))
        offset = data_end + 4
        if chunk_type == b"IEND":
            break
    return payloads


def _extract_pdf_text_payloads(raw: bytes) -> list[str]:
    """Extract raw PDF/XMP text and best-effort decompressed FlateDecode streams."""
    payloads: list[str] = [
        raw.decode("utf-8", errors="replace"),
        raw.decode("latin-1", errors="replace"),
    ]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, flags=re.DOTALL):
        stream_bytes = match.group(1)
        try:
            inflated = zlib.decompress(stream_bytes)
        except zlib.error:
            continue
        payloads.append(inflated.decode("utf-8", errors="replace"))
        payloads.append(inflated.decode("latin-1", errors="replace"))
    return payloads


def scan_mockup_bytes(raw: bytes, filename: str) -> list[str]:
    """Inspect a PNG or PDF byte payload for prohibited mockup metadata or markers."""
    lower_name = filename.lower()
    if lower_name.endswith(".png"):
        surfaces = _extract_png_text_payloads(raw) + [
            raw.decode("utf-8", errors="replace"),
            raw.decode("latin-1", errors="replace"),
        ]
    elif lower_name.endswith(".pdf"):
        surfaces = _extract_pdf_text_payloads(raw)
    else:
        return []

    findings: list[str] = []
    seen_labels: set[str] = set()
    for surface in surfaces:
        for label, pattern in MOCKUP_TEXT_PATTERNS:
            if label not in seen_labels and pattern.search(surface):
                seen_labels.add(label)
                findings.append(f"{filename}: prohibited mockup marker '{label}'")
    return findings


def _iter_png_pdf_files(repo_root: Path, tracked_only: bool = True) -> list[Path]:
    """List PNG/PDF files under repo_root (strictly git-tracked when tracked_only=True)."""
    if tracked_only and (repo_root / ".git").exists():
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
        results: list[Path] = []
        for entry in proc.stdout.split(b"\x00"):
            if not entry:
                continue
            rel_str = entry.decode("utf-8", errors="surrogateescape")
            if not rel_str.lower().endswith((".png", ".pdf")):
                continue
            candidate = repo_root / rel_str
            if candidate.is_file():
                results.append(candidate)
        return sorted(results)

    discovered: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in EXCLUDED_DIRS and not d.endswith(".egg-info")
        )
        root_path = Path(dirpath)
        for filename in sorted(filenames):
            if filename.lower().endswith((".png", ".pdf")):
                discovered.append(root_path / filename)
    return discovered


def scan_mockup_artifacts(repo_root: Path, tracked_only: bool = True) -> list[str]:
    """Scan PNG/PDF artifacts in repo_root for leaked mockup metadata or watermarks."""
    findings: list[str] = []
    for artifact_path in _iter_png_pdf_files(repo_root, tracked_only=tracked_only):
        rel = artifact_path.relative_to(repo_root).as_posix()
        findings.extend(scan_mockup_bytes(artifact_path.read_bytes(), filename=rel))
    return findings


def _build_minimal_png(extra_chunks: list[tuple[bytes, bytes]]) -> bytes:
    """Build a minimal valid 1x1 PNG with custom ancillary chunks for firewall tests."""
    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00")
    parts = [PNG_SIGNATURE, _chunk(b"IHDR", ihdr)]
    for ctype, cdata in extra_chunks:
        parts.append(_chunk(ctype, cdata))
    parts.append(_chunk(b"IDAT", idat))
    parts.append(_chunk(b"IEND", b""))
    return b"".join(parts)


def test_zero_mock_and_no_sim_ast_gate() -> None:
    """Repository must contain zero mock/monkeypatch/fake/simulation patterns."""
    all_violations: list[str] = []
    py_files = _iter_repo_python_files(REPO_ROOT)
    assert py_files, "Expected at least one Python file to scan in repository"
    for py_file in py_files:
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        source = py_file.read_text(encoding="utf-8-sig", errors="replace")
        all_violations.extend(scan_python_source(source, filename=rel))
    assert not all_violations, (
        f"Zero-mock/zero-sim CI gate failed with {len(all_violations)} violation(s):\n"
        + "\n".join(all_violations)
    )


def test_anti_spoof_amnesty_empty_if_present(tmp_path: Path) -> None:
    """Every .anti_spoof_amnesty.json in the repository must parse strictly to []."""
    assert validate_amnesty_files(REPO_ROOT) == []

    bad = tmp_path / ".anti_spoof_amnesty.json"
    bad.write_text('["topos/example.py"]\n', encoding="utf-8")
    assert len(validate_amnesty_files(tmp_path)) == 1
    bad.write_text("[]\n", encoding="utf-8")
    assert validate_amnesty_files(tmp_path) == []


def test_no_scoped_attr_outside_tests() -> None:
    """M1 gate (a): _scoped_attr/_scoped_attrs must never appear in topos/, src/, scripts/, or cochem_topos_web.py."""
    findings = scan_scoped_attr_outside_tests(REPO_ROOT)
    assert not findings, (
        "M1 gate failed: _scoped_attr found outside tests/:\n" + "\n".join(findings)
    )


def test_scoped_attr_test_calls_match_frozen_inventory() -> None:
    """M1 gate (b): test _scoped_attr call sites must not exceed or introduce sites outside the frozen inventory."""
    findings = validate_scoped_attr_inventory(REPO_ROOT, M1_INVENTORY_PATH)
    assert not findings, (
        "M1 frozen _scoped_attr inventory gate failed:\n" + "\n".join(findings)
    )


def test_m1_scoped_attr_gate_catches_seeded_violations(tmp_path: Path) -> None:
    """Self-verify M1 gates catch both outside-tests usage and unauthorized test sites."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "bad_script.py").write_text(
        "def f():\n    return _scoped_attr(object, 'x', 1)\n", encoding="utf-8"
    )
    assert scan_scoped_attr_outside_tests(tmp_path), "Failed to detect _scoped_attr in scripts/"

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_new.py").write_text(
        "def test_x():\n    with _scoped_attr(obj, 'flag', True):\n        pass\n",
        encoding="utf-8",
    )
    inv = tmp_path / "tests" / "m1_scoped_attr_inventory.json"
    inv.write_text(
        json.dumps(
            {
                "outside_tests_count": 0,
                "scientific_engine_callable_swaps": 0,
                "total_call_count": 0,
                "blind_set_v_a6_exclusion_note": "Excluded from Blind Set / V-A6.",
                "call_sites": [],
            }
        ),
        encoding="utf-8",
    )
    assert validate_scoped_attr_inventory(tmp_path, inv), (
        "Failed to reject unauthorized test _scoped_attr call site"
    )


def test_gate_scanner_detects_prohibited_constructs() -> None:
    """Self-verify widened banned mock detection catches dynamic imports and HTTP mock libs."""
    snippets = [
        "import unittest.mock\n",
        "from unittest import mock\n",
        "from unittest import mock as hidden_m\n",
        "import pytest_mock\n",
        "import responses\n",
        "import vcrpy\n",
        "import vcr\n",
        "import requests_mock\n",
        "import importlib\nmod = importlib.import_module('unittest.mock')\n",
        "import importlib\nmod = importlib.import_module('mock')\n",
        "import importlib\nmod = importlib.import_module('pytest_mock')\n",
        "import importlib\nmod = importlib.import_module('requests-mock')\n",
        "obj = MagicMock()\n",
        "obj = Mock()\n",
        "obj = AsyncMock()\n",
        "obj = PropertyMock()\n",
        "obj = create_autospec(int)\n",
        "obj = NonCallableMock()\n",
        "h = mock_open()\n",
        "def f(monkeypatch):\n    return monkeypatch\n",
        "def f(mocker):\n    return mocker\n",
        "def f(requests_mock):\n    return requests_mock\n",
        "def fake_solver():\n    return 0\n",
        "FAKE_ENERGY = -76.0\n",
        "def generate_deterministic_solver_output():\n    return ''\n",
        "def poll_or_simulate_execution():\n    return None\n",
        "COLAB_WORKER_FAKE_GPU_NAME = 'A100'\n",
        "simulated_temp = 298.15\n",
        "dummy_force = 0.0\n",
        'run_calc(mode="simulation")\n',
        "run_calc(mode='simulation')\n",
    ]
    for idx, snippet in enumerate(snippets):
        detected = scan_python_source(snippet, filename=f"check_{idx}.py")
        assert detected, f"Gate missed prohibited snippet #{idx}: {snippet!r}"

    clean_snippet = (
        "from pathlib import Path\n"
        "def compute_distance(a: float, b: float) -> float:\n"
        "    return abs(a - b)\n"
    )
    assert scan_python_source(clean_snippet, filename="clean.py") == []


def test_seeded_canary_mock_aliases_fail_scanner(tmp_path: Path) -> None:
    """Seeded-canary test proving aliased and dynamically imported mocks fail the scanner."""
    canaries = {
        "canary_from_unittest_alias.py": (
            "from unittest import mock as _m\n"
            "def run():\n"
            "    return _m.patch('os.system')\n"
        ),
        "canary_import_unittest_mock_alias.py": (
            "import unittest.mock as um\n"
            "def run():\n"
            "    return um.patch('os.system')\n"
        ),
        "canary_unittest_attr_alias.py": (
            "import unittest as ut\n"
            "def run():\n"
            "    return ut.mock.patch('os.system')\n"
        ),
        "canary_importlib_alias.py": (
            "import importlib as il\n"
            "m = il.import_module('unittest.mock')\n"
        ),
        "canary_import_module_alias.py": (
            "from importlib import import_module as load_mod\n"
            "m = load_mod(name='pytest_mock')\n"
        ),
        "canary_mocker_fixture.py": (
            "def test_stub(mocker):\n"
            "    mocker.patch('os.getcwd')\n"
        ),
        "canary_http_mock_libs.py": (
            "import responses as resp_stub\n"
            "import vcrpy as vcr_stub\n"
            "import requests_mock as req_stub\n"
        ),
    }
    for name, content in canaries.items():
        canary_file = tmp_path / name
        canary_file.write_text(content, encoding="utf-8")
        findings = scan_python_source(
            canary_file.read_text(encoding="utf-8"),
            filename=name,
        )
        assert findings, f"Seeded canary '{name}' evaded zero-mock scanner"


def test_repository_no_mockup_png_or_pdf_leaks() -> None:
    """Mockup-leak firewall: reject any tracked PNG/PDF carrying mockup metadata or markers."""
    findings = scan_mockup_artifacts(REPO_ROOT, tracked_only=True)
    assert not findings, (
        "Mockup-leak firewall failed on tracked PNG/PDF artifacts:\n"
        + "\n".join(findings)
    )


def test_mockup_leak_firewall_rejects_seeded_png_and_pdf(tmp_path: Path) -> None:
    """Self-verify PNG tEXt/iTXt and PDF/XMP mockup markers are caught while clean artifacts pass."""
    clean_png = tmp_path / "clean_figure.png"
    clean_png.write_bytes(_build_minimal_png([(b"tEXt", b"Software\x00CoChem-Verified")]))

    clean_pdf = tmp_path / "clean_figure.pdf"
    clean_pdf.write_bytes(b"%PDF-1.4\n1 0 obj<< /Producer (CoChem Verified) >>endobj\n%%EOF\n")

    assert scan_mockup_artifacts(tmp_path, tracked_only=False) == []

    seeded_cases = {
        "leak_text_kv.png": _build_minimal_png([(b"tEXt", b"cochem:mockup\x00true")]),
        "leak_itxt_tag.png": _build_minimal_png(
            [(b"iTXt", b"Comment\x00\x00\x00\x00\x00cochem:mockup=true")]
        ),
        "leak_banner.png": _build_minimal_png(
            [(b"iTXt", "Description\x00\x00\x00\x00\x00MOCKUP \u2014 VISUAL LAYOUT ONLY".encode("utf-8"))]
        ),
        "leak_xmp.pdf": (
            b"%PDF-1.4\n<x:xmpmeta><rdf:Description cochem:mockup=\"true\"/></x:xmpmeta>\n%%EOF\n"
        ),
        "leak_raw_tag.pdf": (
            b"%PDF-1.4\n% cochem:mockup=true\n%%EOF\n"
        ),
        "leak_not_sci.pdf": (
            b"%PDF-1.4\n1 0 obj<< /Subject (NOT SCIENTIFIC DATA) >>endobj\n%%EOF\n"
        ),
        "leak_banner.pdf": (
            "%PDF-1.4\n1 0 obj<< /Title (MOCKUP \u2014 VISUAL LAYOUT ONLY) >>endobj\n%%EOF\n".encode("utf-8")
        ),
    }

    for filename, payload in seeded_cases.items():
        detected = scan_mockup_bytes(payload, filename=filename)
        assert detected, f"Mockup-leak firewall missed seeded artifact '{filename}'"
