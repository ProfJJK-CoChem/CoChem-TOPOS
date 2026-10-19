"""Real installed-provider subprocess checks; no synthetic chemistry outputs."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import venv
from pathlib import Path

import pytest

SCHEMA = "cochem.topos-structural/1"
PROVIDER_PYTHON = sys.executable


@pytest.fixture(scope="module", autouse=True)
def installed_runtime(tmp_path_factory):
    """Editable collection still exercises a real isolated noneditable wheel.

    Installed-wheel acceptance uses its already verified interpreter. The normal
    source suite builds the same source into a temporary wheel and adds only its
    existing dependency paths to a fresh runtime. No test is skipped or replaced.
    """
    global PROVIDER_PYTHON
    source_root = Path(__file__).resolve().parents[2]
    probe = subprocess.run(
        [sys.executable, "-I", "-c", "import json; from topos.structural.boundary import _installed_source; print(json.dumps(_installed_source()))"],
        capture_output=True, text=True, timeout=40, check=False,
    )
    if probe.returncode == 0:
        identity = json.loads(probe.stdout)
        expected = {
            f"topos/structural/{name}": hashlib.sha256((source_root / "topos/structural" / name).read_bytes()).hexdigest()
            for name in ("__init__.py", "__main__.py", "boundary.py", "exceptions.py", "graph.py", "resonance.py", "rings.py", "tautomer.py")
        }
        if identity["source_sha256"] == expected:
            yield
            return
    root = tmp_path_factory.mktemp("structural-wheel-runtime")
    dist = root / "dist"
    subprocess.run(
        [sys.executable, "-I", "-m", "build", "--wheel", "--no-isolation", "--outdir", str(dist), str(source_root)],
        capture_output=True, text=True, timeout=180, check=True,
    )
    runtime = root / "env"
    venv.EnvBuilder(with_pip=False).create(runtime)
    provider = runtime / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    purelib = Path(subprocess.check_output(
        [str(provider), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True,
    ).strip())
    dependency_paths = [str(Path(item).resolve()) for item in sys.path if item and Path(item).is_dir()]
    (purelib / "structural_test_dependencies.pth").write_text("\n".join(dependency_paths) + "\n")
    subprocess.run(
        [sys.executable, "-I", "-m", "pip", "install", "--no-deps", "--no-compile", "--target", str(purelib), str(next(dist.glob("*.whl")))],
        capture_output=True, text=True, timeout=180, check=True,
    )
    PROVIDER_PYTHON = str(provider)
    try:
        yield
    finally:
        PROVIDER_PYTHON = sys.executable


def invoke(tmp_path, payload=None, raw=None):
    source = tmp_path / "request.json"
    output = tmp_path / "result.json"
    source.write_bytes(raw if raw is not None else json.dumps(payload).encode())
    command = [PROVIDER_PYTHON, "-I", "-B", "-m", "topos.structural", "--request", str(source), "--output", str(output)]
    process = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=40, check=False)
    return process, source, output


def resonance(**kwargs):
    return {"schema": SCHEMA, "request_id": "native-benzene", "operation": "resonance_enumeration", "input": {"smiles": "c1ccccc1", **kwargs}}


def test_installed_resonance_is_actual_unweighted_and_source_bound(tmp_path):
    process, source, output = invoke(tmp_path, resonance())
    assert process.returncode == 0, process.stderr
    receipt = json.loads(output.read_text())
    assert receipt["status"] == "completed"
    assert receipt["request_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert receipt["scientific_execution_performed"] is False
    result = receipt["result"]
    assert result["ensemble_size"] == 2 and result["weights"] is None and result["temperature_k"] is None
    assert result["structures"][0]["bond_orders"] != result["structures"][1]["bond_orders"]
    assert all(form["relative_energy_kcal"] is None and form["boltzmann_weight"] is None for form in result["structures"])
    assert len(receipt["provider"]["source_sha256"]) == 8
    assert len(receipt["provider"]["record_sha256"]) == 64
    # Some installers omit PEP 610 archive hashes. The external approved-wheel
    # seal remains the authority; this provider never invents a missing digest.
    archive = receipt["provider"]["wheel_archive_sha256"]
    assert archive is None or len(archive) == 64


def test_installed_truncation_remains_explicit(tmp_path):
    process, _, output = invoke(tmp_path, resonance(max_structures=1))
    assert process.returncode == 0, process.stderr
    result = json.loads(output.read_text())["result"]
    assert result["ensemble_size"] == 1 and result["enumeration_truncated"] is True


def test_installed_explicit_isotope_uses_actual_dynamic_mass(tmp_path):
    payload = {"schema": SCHEMA, "request_id": "isotope-formaldehyde", "operation": "topology_to_rdkit", "input": {"molecule_id": "isotope-formaldehyde", "elements": ["13C", "O"], "atomic_numbers": [6, 8], "bonds": [[0, 1, 2.0]]}}
    process, _, output = invoke(tmp_path, payload)
    assert process.returncode == 0, process.stderr
    atoms = json.loads(output.read_text())["result"]["atoms"]
    assert atoms[0]["isotope"] == 13 and atoms[0]["mass_u"] > 13.0
    assert atoms[1]["isotope"] == 0


@pytest.mark.parametrize("extra", [{"temperature_k": 298.15}, {"boltzmann_weight": .5}, {"relative_energy_kcal": 1.0}, {"max_structures": True}, {"max_structures": 10001}])
def test_installed_rejects_forged_thermodynamics_and_invalid_limits(tmp_path, extra):
    process, _, output = invoke(tmp_path, resonance(**extra))
    assert process.returncode == 2 and not output.exists()
    assert json.loads(process.stderr.splitlines()[-1])["status"] == "refused"


@pytest.mark.parametrize("raw", [b'{"operation":"resonance_enumeration","operation":"topology_to_rdkit"}', b'{"operation":"resonance_enumeration","input":{"temperature_k":NaN}}', b'[]', b'{' + b' ' * 1048576 + b'}'], ids=["duplicate", "nonfinite", "nonobject", "oversize"])
def test_installed_rejects_duplicate_nonfinite_nonobject_oversize_json(tmp_path, raw):
    process, _, output = invoke(tmp_path, raw=raw)
    assert process.returncode == 2 and not output.exists()


def test_installed_never_replaces_existing_student_evidence(tmp_path):
    output = tmp_path / "result.json"
    output.write_bytes(b"retained-student-data")
    process, _, _ = invoke(tmp_path, resonance())
    assert process.returncode == 2 and output.read_bytes() == b"retained-student-data"


def test_installed_rejects_symlinked_request(tmp_path):
    original = tmp_path / "original.json"
    original.write_text(json.dumps(resonance()))
    link = tmp_path / "request.json"
    link.symlink_to(original)
    output = tmp_path / "result.json"
    process = subprocess.run([PROVIDER_PYTHON, "-I", "-B", "-m", "topos.structural", "--request", str(link), "--output", str(output)], cwd=tmp_path, capture_output=True, text=True, timeout=40, check=False)
    assert process.returncode == 2 and not output.exists()


@pytest.mark.parametrize("changes", [
    {"atomic_numbers": [8, 8]},
    {"atomic_numbers": [True, 8]},
    {"bonds": [[0, 1, 2.1]]},
    {"bonds": [[0, 0, 1.0]]},
    {"bonds": [[0, 1, 2.0], [1, 0, 2.0]]},
    {"smiles": "C=O"},
    {"masses": [13.0, 16.0]},
])
def test_installed_rejects_ambiguous_or_inconsistent_topology(tmp_path, changes):
    payload = {"schema": SCHEMA, "request_id": "invalid-topology", "operation": "topology_to_rdkit", "input": {"molecule_id": "isotope-formaldehyde", "elements": ["13C", "O"], "atomic_numbers": [6, 8], "bonds": [[0, 1, 2.0]], **changes}}
    process, _, output = invoke(tmp_path, payload)
    assert process.returncode == 2 and not output.exists()


def test_installed_source_tampering_is_refused_without_result(tmp_path):
    source = Path(subprocess.check_output(
        [PROVIDER_PYTHON, "-I", "-c", "from importlib.metadata import distribution; print(distribution('cochem-topos').locate_file('topos/structural/rings.py'))"], text=True,
    ).strip())
    original = source.read_bytes()
    try:
        source.write_bytes(original + b"\n# genuine byte-integrity negative test\n")
        process, _, output = invoke(tmp_path, resonance())
        assert process.returncode == 2 and not output.exists()
        refusal = json.loads(process.stderr.splitlines()[-1])
        assert refusal["error_type"] == "Refused"
        assert "RECORD verification" in refusal["reason"]
    finally:
        source.write_bytes(original)
