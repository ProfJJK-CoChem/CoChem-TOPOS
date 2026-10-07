"""Historical native bytes test parsing and recovery, never current physics.

The replay runner below executes no binary. It copies unchanged retained ORCA
text into a test attempt so the adapter's finite-stopping decision is exercised.
These replayed observations cannot satisfy scientific or release acceptance.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from topos.engines import EngineParseError
from topos.goat import parse_goat_ensemble, run_goat
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.runtime import ProcessResult
from topos.storage import file_digest

FIXTURE = Path(__file__).parent / "fixtures/goat_hosted_finalensemble"


@pytest.fixture
def reference():
    return Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.95, 0, 0], [-.24, .93, 0]])


def test_retained_native_fixture_bytes_and_original_stopping_scope():
    provenance = json.loads((FIXTURE / "provenance.json").read_text())
    for name, expected in provenance["fixture_sha256"].items():
        assert file_digest(FIXTURE / name) == expected
    assert provenance["observed_native_process"]["status"] == "completed"
    assert provenance["observed_native_process"]["returncode"] == 0
    assert provenance["observed_native_process"]["elapsed_seconds"] == 2417.19613003
    assert provenance["observed_native_resources"]["budget_seconds"] == 4800
    assert provenance["observed_global_search"]["finite_stopping_marker"] is False
    assert "MAXGLOBALITER 3" in (FIXTURE / "native-input.inp").read_text()
    raw = (FIXTURE / "native-search.stdout").read_text()
    assert "Reached the maximum number of global iterations (3)!" in raw
    assert "ORCA TERMINATED NORMALLY" in raw
    assert "Global minimum found!" not in raw


def test_actual_finalensemble_comment_attests_local_frame_only(reference):
    frames = parse_goat_ensemble(FIXTURE / "native-ensemble.txt", reference)
    assert len(frames) == 1
    frame = frames[0]
    assert frame.energy_hartree == -76.4189354908
    assert frame.molecule.coordinates[0] == [0.15232441883653966, -0.010306486322767722, 0.07179912314741471]
    assert frame.molecule.atom_ids == reference.atom_ids
    assert frame.metadata["raw_comment"] == "-76.4189354908 converged=true"
    assert frame.metadata["native_frame_converged"] is True
    assert "local native frame only" in frame.metadata["frame_convergence_scope"]
    assert frame.metadata["validation_status"] == "requires-common-level-refinement"
    assert frame.metadata["stationary_point_classification"] == "unclassified"


@pytest.mark.parametrize("comment,energy", [
    ("-1.0 converged=true", -1.0), ("-1.25D+01 converged=true", -12.5),
    ("Energy -1.0", -1.0), ("Energy -1.25D+01 Eh", -12.5), ("Energy -.5 hartree", -.5),
])
def test_complete_energy_conventions_preserve_finite_hartree_values(reference, tmp_path, comment, energy):
    path = tmp_path / "ensemble.xyz"
    path.write_text(f"3\n{comment}\nO 0 0 0\nH .95 0 0\nH -.24 .93 0\n")
    frame = parse_goat_ensemble(path, reference)[0]
    assert frame.energy_hartree == energy
    assert frame.metadata["native_frame_converged"] is (True if "converged=true" in comment else None)


@pytest.mark.parametrize("comment", [
    "-10", "-10 converged=false", "-10 converged=yes", "-10 converged=1",
    "-10 converged=true converged=false", "-10 -20 converged=true",
    "Energy -10 -20", "Energy -10 converged=true", "-10 kcal/mol converged=true",
    "NaN converged=true", "Inf converged=true", "1e999 converged=true",
])
def test_ambiguous_or_unconverged_native_comments_cannot_supply_an_energy(reference, tmp_path, comment):
    path = tmp_path / "ensemble.xyz"
    path.write_text(f"3\n{comment}\nO 0 0 0\nH .95 0 0\nH -.24 .93 0\n")
    with pytest.raises(EngineParseError):
        parse_goat_ensemble(path, reference)


def test_parser_recovery_does_not_promote_actual_iteration_limited_search(reference, tmp_path):
    # This nonexecuted marker identifies only a replay test. All scientific text
    # below is the unchanged historical output, not newly generated chemistry.
    executable = tmp_path / "never-executed-native-replay-marker"
    executable.write_text("historical output replay test; never execute")
    executable.chmod(0o700)
    calls = []

    def replay(command, folder, resources, *, log_prefix, **kwargs):
        calls.append(log_prefix)
        stdout = Path(folder) / f"{log_prefix}.stdout"
        stderr = Path(folder) / f"{log_prefix}.stderr"
        source = FIXTURE / ("native-version.stdout" if log_prefix == "version" else "native-search.stdout")
        stdout.write_bytes(source.read_bytes())
        stderr.write_bytes(b"")
        if log_prefix == "goat":
            (Path(folder) / "goat.finalensemble.xyz").write_bytes((FIXTURE / "native-ensemble.txt").read_bytes())
        return ProcessResult(command, "completed", 0, 0.0, 0.0, str(stdout), str(stderr))

    method = MethodSpec(engine="orca", method="r2SCAN-3c", engine_version="6.1.1", profile_id="orca-mapping-v4.1")
    result = run_goat(reference, method, ResourceLimits(budget_seconds=30), tmp_path / "historical-replay",
                      executable=executable, process_runner=replay, deterministic=True, max_global_iterations=3)
    assert calls == ["version", "goat"]
    assert result.status == "partial", result.diagnostics
    assert result.converged is False and len(result.ensemble) == 1
    assert result.ensemble[0].metadata["native_frame_converged"] is True
    assert result.metadata["native_progress"]["reported_global_iteration_indices"] == [1, 2, 3]
    assert result.metadata["native_progress"]["normal_termination_marker_present"] is True
    assert result.metadata["native_progress"]["finite_stopping_marker_present"] is False
    assert "convergence marker absent" in result.diagnostics["reason"]
    assert result.metadata["exhaustive"] is False
