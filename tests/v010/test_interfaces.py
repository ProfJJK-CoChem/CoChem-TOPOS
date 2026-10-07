"""Interface routing and integrity tests; no test double is chemical evidence."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from topos.actions.dispatch import ActionDispatchClient
from topos.cli import main
from topos.models import Candidate, RunRecord, RunRequest
from topos.storage import RunStore
from topos.ui import parse_request_json, submit_request


def request_payload() -> dict:
    return {
        "molecule": {
            "symbols": ["N", "O"], "coordinates": [[0, 0, 0], [0, 0, 1.2]],
            "charge": 0, "multiplicity": 2, "isotopes": [15, 18],
            "atom_ids": ["nitrogen", "oxygen"],
            "bonds": [{"atom1": 0, "atom2": 1, "order": 2.0}],
        },
        "presentation_environment": "codespaces", "calculation_environment": "github-actions",
        "engine": "orca", "method": "HF-3c", "purpose": "optimize", "budget_seconds": 12.0,
        "n_candidates": 1, "seed": 13,
    }


def test_remote_compatibility_receipt_does_not_claim_submission_or_read_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "environment-credential-must-not-be-read")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("No discovery or local fallback is allowed"))
    client = ActionDispatchClient(repo_root=tmp_path, token="private-explicit-token", target_repo="alice/science")
    result = client.dispatch_workflow("actual.yml", request_payload(), ref="review-branch").to_dict()
    assert result["status"] == "unavailable"
    assert result["validation_status"] == "not-evaluated"
    assert result["remote_job_id"] is None
    assert result["target_repo"] == "alice/science"
    assert result["workflow_name"] == "actual.yml"
    assert result["inputs"] == request_payload()
    assert result["ref"] == "review-branch"
    assert not list(tmp_path.iterdir())
    assert "private-explicit-token" not in repr(vars(client))
    assert "environment-credential" not in json.dumps(result)


def test_remote_receipt_redacts_nested_secrets_and_has_no_default_repository():
    result = ActionDispatchClient().dispatch_workflow(inputs={"settings": {"token": "SECRET", "method": "GFN2-xTB"}})
    assert result.target_repo is None
    assert result.inputs["settings"] == {"token": "[REDACTED]", "method": "GFN2-xTB"}


@pytest.mark.parametrize("text", [
    '{"engine":"xtb","engine":"orca"}',
    '{"budget_seconds":NaN}',
    '{"budget_seconds":Infinity}',
    '[]',
])
def test_strict_json_rejects_ambiguous_requests(text):
    with pytest.raises(ValueError):
        parse_request_json(text)


def test_shared_request_preserves_state_and_independent_selections():
    request = parse_request_json(json.dumps(request_payload()))
    assert request.engine == "orca"
    assert request.method == "HF-3c"
    assert request.presentation_environment == "codespaces"
    assert request.calculation_environment == "github-actions"
    assert request.molecule.multiplicity == 2
    assert request.molecule.isotopes == [15, 18]
    assert request.molecule.atom_ids == ["nitrogen", "oxygen"]
    assert request.budget_seconds == 12.0


def test_ui_and_cli_return_same_remote_unavailability_without_local_attempt(tmp_path, capsys):
    payload = request_payload()
    ui_result = submit_request(payload, tmp_path / "ui")
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(payload), encoding="utf-8")
    exit_code = main(["run", "--request", str(request_file), "--output-root", str(tmp_path / "cli")])
    cli_result = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert cli_result["status"] in {"unsupported", "unavailable"}
    assert ui_result.status == cli_result["status"]
    assert ui_result.request.model_dump(mode="json") == cli_result["request"]
    assert not cli_result["attempts"]
    assert not cli_result["candidates"]
    assert not ui_result.attempts
    assert ui_result.metadata["run_dir"] != cli_result["metadata"]["run_dir"]
    assert Path(ui_result.metadata["run_dir"]).is_dir()


def test_cli_validation_errors_do_not_echo_input_secrets(tmp_path, capsys):
    payload = request_payload()
    payload["unrecognized"] = "do-not-echo-this-input"
    path = tmp_path / "request.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["run", "--request", str(path), "--output-root", str(tmp_path / "runs")]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "do-not-echo-this-input" not in captured.err
    assert json.loads(captured.err)["status"] == "invalid"
    assert not (tmp_path / "runs").exists()


def test_cli_missing_file_is_an_error(tmp_path, capsys):
    assert main(["run", "--request", str(tmp_path / "absent.json"), "--output-root", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "error"


def test_cli_inspect_and_review_keep_uncomputed_candidates_ineligible(tmp_path, capsys):
    request = RunRequest.model_validate(request_payload())
    record = RunRecord(request=request, status="unavailable")
    candidate = Candidate(molecule=request.molecule, sources=["input-seed"])
    record.candidates.append(candidate)
    run_dir = tmp_path / record.run_id
    RunStore(run_dir).commit(record)
    assert main(["inspect", str(run_dir)]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == record.run_id
    assert main(["review", str(run_dir), "--subject", candidate.candidate_id, "--action", "accept",
                 "--actor", "scientist", "--reason", "Accept structure for further calculation"]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["reason"] == "Accept structure for further calculation"
    assert main(["decisions", str(run_dir)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["decision_id"] == decision["decision_id"]
    assert main(["handoff", str(run_dir), "--member", candidate.candidate_id, "--actor", "scientist"]) == 2
    assert "no calculation attempt" in capsys.readouterr().err


def test_python_module_provides_real_cli_not_historical_pass_harness():
    completed = subprocess.run([sys.executable, "-m", "topos", "--help"], capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert "review" in completed.stdout and "resume" in completed.stdout
    assert "verification passed" not in completed.stdout.lower()


def test_frontend_and_base_share_exact_submission_function():
    from frontend import submit_request as base_submit
    from frontend.cochem_topos_preflight import validate_request
    from frontend.cochem_topos_ui import submit_request as frontend_submit
    assert base_submit is submit_request
    assert frontend_submit is submit_request
    assert validate_request(request_payload()) == RunRequest.model_validate(request_payload())


@pytest.mark.parametrize("example, algorithm, nci", [
    ("water-search.json", "jiggle-quench", False),
    ("water-crest-mquick.json", "crest", False),
    ("water-union.json", "union", False),
    ("water-dimer-crest-nci.json", "crest", True),
])
def test_open_engine_examples_parse_through_shared_interface(example, algorithm, nci):
    path = Path(__file__).resolve().parents[2] / "examples" / example
    request = parse_request_json(path.read_text(encoding="utf-8"))
    assert request.engine == "xtb" and request.method == "GFN2-xTB"
    assert request.calculation_environment == "local"
    assert request.search_algorithm == algorithm and request.sampler_nci is nci
    assert request.dedup_energy_threshold_kcal_mol == 0.05
    assert request.dedup_rotational_threshold_fraction == 0.01
    if algorithm != "jiggle-quench":
        assert request.sampler_profile == "crest-mquick-v1"
        assert not any(request.molecule.isotopes)
    if nci:
        assert len(request.molecule.fragments) == 2


@pytest.mark.parametrize("algorithm, sampler_profile", [
    ("jiggle-quench", "crest-imtdgc-v1"),
    ("crest", "crest-mquick-v1"),
    ("union", "crest-imtdgc-v1"),
])
def test_browser_renders_independent_controls_and_remote_unavailability(tmp_path, algorithm, sampler_profile):
    """Exercise Streamlit form submission without asserting any calculated quantity."""
    testing = pytest.importorskip("streamlit.testing.v1", reason="optional browser adapter dependency")
    app = testing.AppTest.from_file(str(Path(__file__).resolve().parents[2] / "cochem_topos_web.py")).run(timeout=20)
    assert not app.exception
    selectors = {widget.label: widget for widget in app.selectbox}
    assert {"Presentation environment", "Calculation environment", "Calculation engine", "Method", "Purpose", "Convergence profile", "Search algorithm"} <= selectors.keys()
    selectors["Presentation environment"].select("codespaces")
    selectors["Calculation environment"].select("github-actions")
    selectors["Search algorithm"].select(algorithm)
    app.run(timeout=20)
    if algorithm != "jiggle-quench":
        next(widget for widget in app.selectbox if widget.label == "CREST sampling protocol").select(sampler_profile)
    inputs = {widget.label: widget for widget in app.text_input}
    inputs["Output directory"].set_value(str(tmp_path / "browser-runs"))
    next(button for button in app.button if button.label == "Run requested calculation").click()
    app.run(timeout=20)
    assert not app.exception
    job = app.session_state["topos_job"]
    assert job.done.wait(15)
    assert job.error is None
    assert job.record.status == "unavailable"
    assert job.record.request.calculation_environment == "github-actions"
    assert job.record.request.presentation_environment == "codespaces"
    assert job.record.request.engine == "xtb"
    assert job.record.request.method == "GFN2-xTB"
    assert job.record.request.search_algorithm == algorithm
    assert job.record.request.sampler_profile == sampler_profile
    assert not job.record.attempts
    app.run(timeout=20)
    assert not app.exception
    assert any("unavailable" in widget.value for widget in app.markdown)


def test_browser_search_controls_apply_only_to_search_purpose():
    testing = pytest.importorskip("streamlit.testing.v1", reason="optional browser adapter dependency")
    app = testing.AppTest.from_file(str(Path(__file__).resolve().parents[2] / "cochem_topos_web.py")).run(timeout=20)
    next(widget for widget in app.selectbox if widget.label == "Purpose").select("energy")
    app.run(timeout=20)
    assert not app.exception
    assert "Search algorithm" not in {widget.label for widget in app.selectbox}
    assert "CREST sampling protocol" not in {widget.label for widget in app.selectbox}
    assert "Deduplication energy tolerance (kcal/mol)" not in {widget.label for widget in app.number_input}


def test_browser_preserves_explicit_search_and_deduplication_settings(tmp_path):
    testing = pytest.importorskip("streamlit.testing.v1", reason="optional browser adapter dependency")
    app = testing.AppTest.from_file(str(Path(__file__).resolve().parents[2] / "cochem_topos_web.py")).run(timeout=20)
    next(widget for widget in app.selectbox if widget.label == "Calculation environment").select("github-actions")
    next(widget for widget in app.selectbox if widget.label == "Search algorithm").select("union")
    app.run(timeout=20)
    next(widget for widget in app.selectbox if widget.label == "CREST sampling protocol").select("crest-nci-v1")
    next(widget for widget in app.slider if widget.label == "CREST fraction of remaining workflow budget").set_value(0.65)
    app.run(timeout=20)
    values = {
        "Candidate limit per search source": 7,
        "TOPOS perturbation seed": 91,
        "Jiggle displacement scale (angstrom)": 0.2,
        "Electronic-energy window (kcal/mol)": 4.5,
        "Deduplication RMSD threshold (angstrom)": 0.11,
        "Deduplication energy tolerance (kcal/mol)": 0.03,
        "Deduplication rotational-constant relative tolerance": 0.005,
    }
    for widget in app.number_input:
        if widget.label in values:
            widget.set_value(values[widget.label])
    dimer = json.loads((Path(__file__).resolve().parents[2] / "examples" / "water-dimer-crest-nci.json").read_text())["molecule"]
    next(widget for widget in app.text_area if widget.label.startswith("Molecule JSON")).set_value(json.dumps(dimer))
    next(widget for widget in app.text_input if widget.label == "Output directory").set_value(str(tmp_path / "search-controls"))
    next(button for button in app.button if button.label == "Run requested calculation").click()
    app.run(timeout=20)
    assert not app.exception
    job = app.session_state["topos_job"]
    assert job.done.wait(15) and job.error is None
    request = job.record.request
    assert request.n_candidates == 7 and request.seed == 91
    assert request.perturbation_angstrom == 0.2
    assert request.energy_window_kcal_mol == 4.5
    assert request.rmsd_threshold_angstrom == 0.11
    assert request.dedup_energy_threshold_kcal_mol == 0.03
    assert request.dedup_rotational_threshold_fraction == 0.005
    assert request.sampler_profile == "crest-nci-v1" and request.sampler_nci
    assert request.sampler_budget_fraction == 0.65
    assert job.record.status == "unavailable" and not job.record.attempts


def test_browser_honors_configured_output_root_outside_repository(tmp_path, monkeypatch):
    testing = pytest.importorskip("streamlit.testing.v1", reason="optional browser adapter dependency")
    monkeypatch.setenv("TOPOS_OUTPUT_ROOT", str(tmp_path / "configured-runs"))
    app = testing.AppTest.from_file(str(Path(__file__).resolve().parents[2] / "cochem_topos_web.py")).run(timeout=20)
    assert not app.exception
    value = next(widget for widget in app.text_input if widget.label == "Output directory").value
    assert Path(value) == tmp_path / "configured-runs"
    assert not Path(value).is_relative_to(Path(__file__).resolve().parents[2])


def test_browser_export_default_is_sibling_bundle_directory(tmp_path):
    testing = pytest.importorskip("streamlit.testing.v1", reason="optional browser adapter dependency")
    record = RunRecord(request=RunRequest.model_validate(request_payload()), status="unavailable")
    run_dir = tmp_path / record.run_id
    RunStore(run_dir).commit(record)
    app = testing.AppTest.from_file(str(Path(__file__).resolve().parents[2] / "cochem_topos_web.py")).run(timeout=20)
    next(widget for widget in app.text_input if widget.label == "Run directory").set_value(str(run_dir))
    app.run(timeout=20)
    assert not app.exception
    destination = next(widget for widget in app.text_input if widget.label == "Local bundle folder").value
    assert Path(destination) == run_dir.parent / f"{run_dir.name}-publication"
    assert not Path(destination).is_relative_to(run_dir)
    assert not destination.endswith(".zip")


def test_base_preflight_revalidates_mutated_nested_models():
    from frontend.cochem_topos_preflight import validate_molecule, validate_request
    request = RunRequest.model_validate(request_payload())
    request.molecule.coordinates[0][0] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        validate_molecule(request.molecule)
    with pytest.raises(ValueError, match="finite"):
        validate_request(request)


def test_ui_launcher_uses_packaged_app_and_explicit_loopback(monkeypatch):
    cli = pytest.importorskip("streamlit.web.cli", reason="optional browser adapter dependency")
    from topos.ui import ui_main
    observed = {}

    def capture(**kwargs):
        observed.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "main", capture)
    assert ui_main(["--port", "8765"]) == 0
    arguments = observed["args"]
    assert arguments[0] == "run"
    assert Path(arguments[1]).name == "streamlit_app.py"
    assert Path(arguments[1]).is_file()
    assert arguments[arguments.index("--server.address") + 1] == "127.0.0.1"
    assert arguments[arguments.index("--server.port") + 1] == "8765"
    assert observed["standalone_mode"] is False


def test_ui_launcher_serves_local_health_endpoint(tmp_path):
    """A server-start check, distinct from the actual form/workflow tests above."""
    import http.client
    import socket
    import time

    pytest.importorskip("streamlit", reason="optional browser adapter dependency")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    log_path = tmp_path / "ui-server.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", "from topos.ui import ui_main; raise SystemExit(ui_main())", "--port", str(port)],
            cwd=Path(__file__).resolve().parents[2], stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            healthy = False
            while time.monotonic() < deadline and process.poll() is None:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                try:
                    connection.request("GET", "/_stcore/health")
                    response = connection.getresponse()
                    healthy = response.status == 200 and response.read() == b"ok"
                    if healthy:
                        break
                except OSError:
                    pass
                finally:
                    connection.close()
                time.sleep(0.1)
            assert healthy, log_path.read_text(encoding="utf-8")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
