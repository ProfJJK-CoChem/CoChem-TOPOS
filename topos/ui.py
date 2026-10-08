"""Shared BASE/UI submission contract and an optional Streamlit interface.

Importing this module does not launch a server, read credentials, submit jobs,
create files, or execute chemistry. Every adapter uses the same RunRequest and
Workflow, including exact selections for environment, engine, method and budget.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from topos.models import RunRecord, RunRequest


def _error_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
    return str(exc)


def _parse_json(text: str) -> Any:
    """Parse strict JSON without silent duplicate-key or nonfinite-value coercion."""
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate request key: {key}")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError(f"Nonfinite JSON value is invalid: {value}")

    return json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)


def parse_request_json(text: str) -> RunRequest:
    """Parse the identical typed request used by every public interface."""
    value = _parse_json(text)
    if not isinstance(value, dict):
        raise ValueError("A run request must be a JSON object")
    return RunRequest.model_validate(value)


def submit_request(
    request: RunRequest | dict[str, Any],
    output_root: Path | str,
    *,
    cancel_event: threading.Event | None = None,
) -> RunRecord:
    """Submit an explicit request from BASE, the CLI, a notebook, or the browser."""
    from topos.workflow import Workflow

    values = request.model_dump(mode="json") if isinstance(request, RunRequest) else request
    validated = RunRequest.model_validate(values)
    return Workflow(Path(output_root)).run(validated, cancel_event=cancel_event)


@dataclass
class _UIJob:
    """Only runtime state; persisted scientific records remain in RunStore."""

    cancel_event: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    record: Any = None
    error: str | None = None


def _execute_ui_job(job: _UIJob, request: RunRequest, output_root: Path) -> None:
    try:
        job.record = submit_request(request, output_root, cancel_event=job.cancel_event)
    except Exception as exc:
        job.error = f"{type(exc).__name__}: {_error_message(exc)}"
    finally:
        job.done.set()


def _show_record(st: Any, record: dict[str, Any]) -> None:
    st.write(f"Execution: **{record['status']}** · Validation: **{record['validation_status']}**")
    st.caption(f"Run: {record['run_id']}")
    st.json(record.get("metadata", {}), expanded=False)
    st.subheader("Candidate basket")
    for candidate in record.get("candidates", []):
        with st.expander(f"{candidate['candidate_id']} — {candidate.get('status', 'unreviewed')}"):
            st.json(candidate)
    if not record.get("candidates"):
        st.info("This run has no candidate structures.")
    with st.expander("Execution attempts and requested protocol"):
        st.json({"request": record["request"], "attempts": record.get("attempts", [])})


def _review_panel(st: Any) -> None:
    from topos.publication import export_bundle
    from topos.review import (
        accept_torq_receipt,
        append_decision,
        create_ensemble_manifest,
        export_torq_handoff,
        list_decisions,
        review_basket,
    )
    from topos.storage import RunStore

    st.subheader("Review a saved run")
    run_text = st.text_input("Run directory", key="review_run_dir")
    if not run_text:
        return
    run_dir = Path(run_text).expanduser()
    try:
        store = RunStore(run_dir)
        snapshot = store.verify()
        record = store.load()
        _show_record(st, record)
        decisions = list_decisions(run_dir)
        with st.expander("Review history"):
            st.json(decisions)
        with st.expander("Scientific eligibility and unresolved chemistry"):
            st.json(review_basket(run_dir))
        with st.form("review_decision"):
            subject = st.text_input("Candidate ID")
            action = st.selectbox("Decision", ["accept", "reject", "annotate", "needs-review", "withdraw"])
            actor = st.text_input("Reviewer identity")
            reason = st.text_area("Reason and scope")
            supersedes = st.text_input("Superseded decision ID (optional)")
            scope = st.text_input("Decision scope", value="candidate")
            annotation_text = st.text_area("Annotations (JSON object)", value="{}")
            if st.form_submit_button("Record decision"):
                st.json(append_decision(run_dir, subject_id=subject, action=action, actor=actor,
                                        reason=reason, supersedes=supersedes or None, scope=scope,
                                        annotations=_parse_json(annotation_text)))
        with st.form("freeze_ensemble"):
            selected = st.multiselect("Ensemble members (each needs an accept decision)",
                                     [c["candidate_id"] for c in record.get("candidates", [])])
            actor = st.text_input("Ensemble author")
            reason = st.text_input("Selection rationale")
            if st.form_submit_button("Freeze reviewed ensemble"):
                st.json(create_ensemble_manifest(run_dir, selected, actor=actor, reason=reason,
                                                 expected_snapshot_sha256=snapshot["snapshot_id"]))
        with st.form("torq_handoff"):
            destination = st.text_input("TORQ handoff file", value=str(run_dir.parent / f"{run_dir.name}-torq.json"))
            if st.form_submit_button("Export reviewed ensemble for TORQ"):
                st.json(export_torq_handoff(run_dir, destination))
                st.info("Handoff exported. TORQ consumption requires a receipt from the consumer.")
        with st.form("torq_receipt"):
            receipt_path = st.text_input("Receipt file produced by TORQ")
            if st.form_submit_button("Verify TORQ consumption receipt"):
                st.json(accept_torq_receipt(run_dir, receipt_path))
        with st.form("publication_export"):
            destination = st.text_input("Local bundle folder", value=str(run_dir.parent / f"{run_dir.name}-publication"))
            license_id = st.text_input("Proposed artifact license (SPDX or LicenseRef identifier)")
            if st.form_submit_button("Create local publication archive"):
                st.json(export_bundle(run_dir, Path(destination), license_identifier=license_id or None))
                st.caption("Local archive only. Run its regenerate.py script to reproduce the table and figure; publication requires author review.")
    except (OSError, ValueError, RuntimeError) as exc:
        st.error(_error_message(exc))


def _matrix_panel(st: Any) -> None:
    """Inspect source-bound routes without treating PATH discovery as validation."""
    import psutil

    from topos.method_matrix import BackendCapability, HardwareSpec, load_catalog, plan_route
    from topos.runtime import available_cpu_count

    catalog = load_catalog()
    st.subheader("Purpose, time tier and hardware routes")
    st.caption(f"Matrix revision: {catalog.revision}. A time tier is a planning category, not a predicted runtime.")
    with st.expander("Executable recipes and remaining adapters"):
        from topos.matrix_workflow import execution_support_report
        st.json(execution_support_report())
    owner = st.selectbox("Matrix owner", ["TOPOS", "TORQ", "All"])
    rows = [row for row in catalog.rows if owner == "All" or row.owner == owner]
    row_id = st.selectbox("Matrix row", [row.row_id for row in rows])
    row = catalog.get(row_id)
    st.json(row.model_dump(mode="json"), expanded=False)
    if row.owner == "TORQ":
        st.info("This route belongs to TORQ. TOPOS can export the reviewed ensemble for that component.")
    with st.form("matrix_plan"):
        cpu = st.number_input("Allocated CPU threads", min_value=1, value=available_cpu_count())
        ram = st.number_input("Allocated memory (MB)", min_value=64,
                              value=max(64, int(psutil.virtual_memory().available // 1048576)))
        device = st.selectbox("Planning device", ["cpu", "auto", "gpu"])
        gpu = st.text_input("GPU model (required for GPU allocation)")
        gpu_memory = st.number_input("Available GPU memory (MB)", min_value=1, value=1024)
        fingerprint = st.text_input("Hardware fingerprint", value="interactive-local-observation")
        product = st.selectbox("Matrix product", ["A", "B", "C"])
        from .data.reviewed_matrix_v010 import RECIPES

        source_resolution = st.selectbox("Explicit source-conflict resolution", ["None",
            "native-composite-rawinteraction-v1", "orca-f12-reference-singlepoint-v1", *RECIPES],
            help="Choose only when the selected row documents this resolution. Reference single points do not complete an optimized-geometry row.")
        capabilities = st.text_area("Verified backend capabilities (JSON array)", value="[]",
                                    help="Use actual versioned adapter evidence. With no declarations, the plan reports missing capabilities.")
        inputs = st.text_input("Available scientific input names (comma separated)")
        if st.form_submit_button("Inspect execution plan"):
            try:
                values = _parse_json(capabilities)
                if not isinstance(values, list):
                    raise ValueError("Verified backend capabilities must be a JSON array")
                hardware = HardwareSpec(cpu_threads=cpu, memory_mb=ram,
                                        memory_per_worker_mb=min(1024, ram),
                                        device=device, gpu_model=gpu or None,
                                        gpu_memory_mb=gpu_memory if gpu else None,
                                        fingerprint=fingerprint)
                plan = plan_route(row_id, hardware=hardware, product=product,
                                  capabilities=[BackendCapability.model_validate(value) for value in values],
                                  available_inputs=[name.strip() for name in inputs.split(",") if name.strip()],
                                  source_resolution=None if source_resolution == "None" else source_resolution)
                st.json(plan.model_dump(mode="json"))
                st.caption("Plan inspection does not submit calculations or establish that all required adapters are implemented.")
            except (ValueError, OSError, RuntimeError) as exc:
                st.error(_error_message(exc))


def render_streamlit() -> None:
    """Render the genuine workflow; requires the optional ``ui`` installation extra."""
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError("Install the UI extra with: pip install 'cochem-topos[ui]'") from exc
    from topos.capabilities import capability_report
    from topos.config import load_config
    st.set_page_config(page_title="CoChem-TOPOS 0.1.0", layout="wide")
    st.title("CoChem-TOPOS 0.1.0")
    st.caption("Molecular search, scientific evidence, reviewed ensembles, and local publication archives")
    with st.expander("Available capabilities and limitations"):
        st.json(capability_report())
    with st.expander("CoChem installation"):
        from topos.base_integration import inspect_ecosystem
        ecosystem = inspect_ecosystem()
        st.json(ecosystem.to_dict())
        if not ecosystem.available:
            st.info("Provision the mandatory CoChem-BASE, TOPOS and TORQ package before calculation.")
    run_tab, review_tab, matrix_tab = st.tabs(["Calculate", "Review and export", "Method matrix"])
    with run_tab:
        job = st.session_state.get("topos_job")
        active = job is not None and not job.done.is_set()
        with st.container():
            first, second = st.columns(2)
            with first:
                presentation = st.selectbox("Presentation environment", ["local", "codespaces", "base", "jupyter"])
                purpose = st.selectbox("Purpose", ["search", "optimize", "energy", "gradient", "frequency", "thermochemistry", "association", "matrix"])
                engine = st.selectbox("Calculation engine", ["xtb", "orca"], disabled=purpose == "matrix")
                budget = st.number_input("Workflow budget (seconds)", min_value=1.0, value=300.0)
            with second:
                environment = st.selectbox("Calculation environment", ["local", "github-actions", "hpc"])
                method = st.selectbox("Method", capability_report()["engines"][engine]["methods"], disabled=purpose == "matrix")
                device = st.selectbox("Calculation device", ["cpu", "cuda"])
                basis = st.text_input("Basis (empty for native composite or not applicable)")
            profile_options = [name for name, values in capability_report()["profiles"].items()
                               if values["engine"] == engine]
            profile = st.selectbox("Convergence profile", profile_options)
            matrix_row = st.text_input("Method matrix row (optional)",
                                       help="Use an exact row such as T3O-30min. The selected engine, method and purpose must satisfy its validated binding.")
            matrix_settings = {}
            if matrix_row.strip():
                matrix_settings["matrix_product"] = st.selectbox("Requested matrix product", ["A", "B", "C"])
                matrix_input_text = st.text_area("Matrix scientific inputs (JSON object)", value="{}",
                    help="Use topology_seeds, stage_b_ensemble, isolated_monomer_references and isolated_monomer_sources as required by the selected recipe.")
            else:
                matrix_input_text = "{}"
            if purpose == "matrix":
                st.caption("The chosen matrix row specifies the calculation methods and required scientific inputs. Only compiled complete recipes can execute.")
            search_settings = {}
            abcluster_input_text = None
            if purpose == "search":
                algorithm = st.selectbox("Search algorithm", ["jiggle-quench", "crest", "union", "abcluster"],
                                         format_func=lambda value: {"jiggle-quench": "Jiggle–quench", "crest": "CREST", "union": "Jiggle–quench + CREST union", "abcluster": "ABCluster rigid packing"}[value])
                search_settings["search_algorithm"] = algorithm
                count, randomization = st.columns(2)
                with count:
                    search_settings["n_candidates"] = st.number_input(
                        "Candidate limit per search source", min_value=1, max_value=10000, value=4,
                        help="Jiggle–quench includes the input in this limit. CREST supplies up to this many native frames, plus the input. Union retains both sources.",
                    )
                with randomization:
                    search_settings["seed"] = st.number_input("TOPOS perturbation seed", min_value=0, value=0)
                if algorithm in {"jiggle-quench", "union"}:
                    search_settings["perturbation_angstrom"] = st.number_input(
                        "Jiggle displacement scale (angstrom)", min_value=0.0, value=0.15, step=0.01,
                        help="Controls TOPOS perturbations before local optimization; it does not establish exhaustive sampling.",
                    )
                if algorithm == "abcluster":
                    abcluster_input_text = st.text_area("ABCluster force-field parameters and sampling options (JSON object)", value="{}",
                        help="Supply atomic_parameters with atom_id, charge_e, epsilon_kj_mol and sigma_angstrom for every real atom, plus a cited parameter_source. Optional controls: population (at least 5), generations, scout_limit, amplitude_angstrom and max_saved_minima.")
                    search_settings["sampler_budget_fraction"] = st.slider("ABCluster fraction of remaining workflow budget",
                        min_value=.05, max_value=.95, value=.5, step=.05)
                    st.caption("Declare rigid fragments and their charge/spin states. ABCluster generates packing seeds using your classical force field; TOPOS independently refines them with the selected quantum method. Classical scores are retained as sampling evidence. Native randomness is engine-controlled.")
                if algorithm in {"crest", "union"}:
                    sampler_profile = st.selectbox("CREST sampling protocol", ["crest-imtdgc-v1", "crest-mquick-v1", "crest-nci-v1"])
                    fraction = st.slider("CREST fraction of remaining workflow budget", min_value=0.05,
                                         max_value=0.95, value=0.5, step=0.05)
                    nci = sampler_profile == "crest-nci-v1"
                    if not nci:
                        nci = st.checkbox("Noncovalent complex confinement (NCI)")
                    search_settings.update(sampler_profile=sampler_profile, sampler_budget_fraction=fraction,
                                           sampler_nci=nci)
                    st.caption("CREST routes require unconstrained GFN2-xTB. The TOPOS seed controls jiggle perturbations; CREST controls its own random initialization. Isotope-labelled molecular dynamics is unsupported.")
                    if nci:
                        st.caption("NCI requires at least two explicitly declared fragments. Its confinement potential biases sampling; final xTB refinement uses the requested physical potential without this confinement.")
                    if sampler_profile == "crest-mquick-v1":
                        st.caption("mquick uses a reduced sampling protocol with normal molecular dynamics and genetic crossing disabled. It does not establish conformational completeness.")
                with st.expander("Energy window and deduplication"):
                    search_settings["deduplication_stage"] = st.selectbox("Deduplication stage", ["generation", "reporting"])
                    if search_settings["deduplication_stage"] == "reporting":
                        st.caption("Reporting requires validated refined geometry and energy. Ineligible candidates remain unresolved.")
                    search_settings["collapse_enantiomers"] = st.checkbox("Group validated sampled mirror partners", value=False)
                    if search_settings["collapse_enantiomers"]:
                        environment_symmetry = st.selectbox("Chiral environment declaration", ["unspecified", "achiral", "chiral"])
                        search_settings["environment_is_achiral"] = {"unspecified": None, "achiral": True, "chiral": False}[environment_symmetry]
                        st.caption("Grouping needs explicit achiral conditions and a verified sampled mirror partner; no missing partner is invented.")
                    search_settings["symmetry_tolerance_angstrom"] = st.number_input(
                        "Point-group tolerance (angstrom)", min_value=0.000001, max_value=0.1, value=0.001, format="%.6f")
                    search_settings["energy_window_kcal_mol"] = st.number_input(
                        "Electronic-energy window (kcal/mol)", min_value=0.001, value=6.0,
                        help="Applied to refined candidates and passed to CREST's native ensemble window. This is not a free-energy or population criterion.",
                    )
                    search_settings["rmsd_threshold_angstrom"] = st.number_input(
                        "Deduplication RMSD threshold (angstrom)", min_value=0.0001, value=0.125, format="%.4f",
                    )
                    search_settings["dedup_energy_threshold_kcal_mol"] = st.number_input(
                        "Deduplication energy tolerance (kcal/mol)", min_value=0.0001, value=0.05, format="%.4f",
                    )
                    search_settings["dedup_rotational_threshold_fraction"] = st.number_input(
                        "Deduplication rotational-constant relative tolerance", min_value=0.0001, max_value=0.9999, value=0.01, format="%.4f",
                        help="A fractional tolerance: 0.01 means 1%. Rotational constants alone do not establish identity.",
                    )
            if purpose in {"frequency", "thermochemistry"}:
                with st.expander("Frequency and thermochemistry protocol", expanded=True):
                    search_settings["temperature_k"] = st.number_input("Temperature (K)", min_value=0.001, value=298.15)
                    thermal = {
                        "optimize_first": st.checkbox("Optimize before evaluating frequencies", value=True),
                        "step_bohr": st.number_input("Hessian displacement (bohr)", min_value=0.00001, max_value=0.1, value=0.005, format="%.5f"),
                        "pressure_pa": st.number_input("Gas standard pressure (Pa)", min_value=0.001, value=101325.0),
                        "frequency_scale": st.number_input("Frequency scale factor", min_value=0.001, value=1.0),
                        "low_frequency_policy": st.selectbox("Low-frequency treatment", ["reject", "frequency-floor"]),
                        "cutoff_cm1": st.number_input("Low-frequency cutoff (cm⁻¹)", min_value=0.001, value=10.0),
                    }
                    if st.checkbox("Use a solution concentration standard state"):
                        thermal["concentration_mol_l"] = st.number_input("Standard concentration (mol/L)", min_value=0.00001, value=1.0)
                    if st.checkbox("Specify rotational symmetry number"):
                        thermal["symmetry_number"] = st.number_input("Rotational symmetry number", min_value=1, value=1)
                    search_settings["thermochemistry_options"] = thermal
                    st.caption("Imaginary modes and nonstationary geometries require review. A frequency floor is an explicit approximation, not an anharmonic calculation.")
            if purpose == "association":
                st.info("Declare fragments and each fragment's charge and multiplicity in the molecule. Association runs retain separate monomer and complex evidence at a common method.")
            molecule_text = st.text_area(
                "Molecule JSON (explicit atoms, coordinates in angstrom, charge, multiplicity and optional state)",
                value=json.dumps({"symbols": ["O", "H", "H"], "coordinates": [[0, 0, 0], [0.7586, 0, 0.5043],
                                                                                           [-0.7586, 0, 0.5043]],
                                  "charge": 0, "multiplicity": 1}, indent=2), height=220,
            )
            advanced_text = st.text_area(
                "Search, resource and protocol settings (JSON)",
                value=json.dumps({"threads": 1, "memory_mb": 1024}, indent=2),
            )
            output_root = st.text_input("Output directory", value=str(load_config().output_root.expanduser().resolve()))
            submitted = st.button("Run requested calculation", disabled=active)
        if submitted:
            try:
                fields = _parse_json(advanced_text)
                if not isinstance(fields, dict):
                    raise ValueError("Search and resource settings must be a JSON object")
                selections = {"molecule": _parse_json(molecule_text), "engine": engine, "method": method,
                              "purpose": purpose, "presentation_environment": presentation,
                              "calculation_environment": environment, "budget_seconds": budget,
                              "device": device, "basis": basis or None, "profile_id": profile,
                              **search_settings, **matrix_settings}
                if abcluster_input_text is not None:
                    parameters = _parse_json(abcluster_input_text)
                    if not isinstance(parameters, dict):
                        raise ValueError("ABCluster options must be a JSON object")
                    selections["abcluster_options"] = parameters
                if matrix_row.strip():
                    from topos.method_matrix import MATRIX_REVISION
                    matrix_inputs = _parse_json(matrix_input_text)
                    if not isinstance(matrix_inputs, dict):
                        raise ValueError("Matrix scientific inputs must be a JSON object")
                    selections.update(matrix_row_id=matrix_row.strip(), matrix_revision=MATRIX_REVISION,
                                      matrix_inputs=matrix_inputs)
                if fields.keys() & selections.keys():
                    raise ValueError("Advanced settings must not override the explicit selectors")
                request = parse_request_json(json.dumps({**fields, **selections}, allow_nan=False))
                job = _UIJob()
                st.session_state["topos_job"] = job
                threading.Thread(target=_execute_ui_job, args=(job, request, Path(output_root).expanduser()),
                                 daemon=True, name="topos-ui-workflow").start()
            except (OSError, ValueError) as exc:
                st.error(_error_message(exc))
        if st.session_state.get("topos_job") is not None:
            @st.fragment(run_every=1.0)
            def progress() -> None:
                current = st.session_state["topos_job"]
                if not current.done.is_set():
                    st.info("Calculation is running; completed evidence will be preserved if cancelled.")
                    if st.button("Cancel this calculation"):
                        current.cancel_event.set()
                        st.info("Cancellation requested.")
                elif current.error is not None:
                    st.error(current.error)
                else:
                    _show_record(st, current.record.model_dump(mode="json"))
            progress()
    with review_tab:
        _review_panel(st)
    with matrix_tab:
        _matrix_panel(st)


def main() -> int:
    """``python -m topos.ui`` accepts the same CLI commands as ``python -m topos``."""
    from topos.cli import main as cli_main
    return cli_main()


def ui_main(argv: list[str] | None = None) -> int:
    """Launch the installed browser application on a local loopback port."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="topos-ui", description="Launch the CoChem-TOPOS browser interface")
    parser.add_argument("--port", type=int, default=8501, help="Local HTTP port (default: 8501)")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        from streamlit.web import cli as streamlit_cli
    except ImportError:
        print("Install browser support with: pip install 'cochem-topos[ui]'", file=sys.stderr)
        return 2
    script = Path(__file__).with_name("streamlit_app.py")
    result = streamlit_cli.main(
        args=["run", str(script), "--server.address", "127.0.0.1", "--server.port", str(args.port),
              "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        prog_name="topos-ui", standalone_mode=False,
    )
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
