"""Run genuine TOPOS ORCA acceptance through a completed mandatory BASE setup.

This is calculation/integration acceptance, not a benchmark of chemical accuracy
or a declaration that every SRS requirement is complete. Missing licensed ORCA,
missing authority, incomplete calculations, and failed checks produce exit 3.
No synthetic output or skipped calculation can produce a passing receipt.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from topos.base_integration import BaseRuntime
from topos.config import SystemConfig
from topos.models import (
    Artifact,
    Attempt,
    MethodSpec,
    Molecule,
    Quantity,
    ResourceLimits,
    RunRecord,
    RunRequest,
    utc_now,
)
from topos.science import BOHR_ANGSTROM
from topos.storage import RunStore, atomic_json, file_digest
from topos.workflow import Workflow, software_provenance

SOURCE_ROOT = Path(__file__).resolve().parents[1]


class AcceptanceFailure(RuntimeError):
    """A requested physical acceptance condition was not established."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def water() -> Molecule:
    """Distorted, non-axis-aligned geometry avoids a trivial zero-gradient check."""
    return Molecule(symbols=["O", "H", "H"],
                    coordinates=[[.12, -.10, .08], [1.15, .13, .20], [-.20, .95, -.12]],
                    isotopes=[16, 1, 1], charge=0, multiplicity=1,
                    name="TOPOS ORCA physical acceptance water")


def _quantity(record: RunRecord, name: str) -> Any:
    values = [quantity.value for attempt in record.attempts for quantity in attempt.quantities
              if quantity.name == name and quantity.validity == "validated-for-protocol"]
    require(len(values) == 1, f"Expected one validated {name} observation")
    return values[0]


def _verify_run(record: RunRecord, expected_binary_hash: str) -> dict[str, Any]:
    store = RunStore(record.metadata["run_dir"])
    manifest = store.verify()
    require(store.load() == record.model_dump(mode="json"), "Verified snapshot differs from the returned record")
    require(record.status == "completed", f"Requested calculation did not complete: {record.metadata.get('termination_reason', record.status)}")
    require(record.validation_status == "validated-for-protocol", "Calculation lacks protocol validation")
    native = [attempt for attempt in record.attempts if attempt.command and attempt.command[0] != "topos-internal"]
    require(bool(native), "No real native calculation attempt was recorded")
    for attempt in native:
        require(attempt.status == "completed" and attempt.converged is True, "Native ORCA attempt is incomplete")
        require(attempt.engine == "orca" and attempt.engine_version == "6.1.1", "Wrong native engine/version")
        require(attempt.metadata.get("execution_kind") == "real", "Native attempt is not genuine execution evidence")
        require(attempt.metadata.get("executable_sha256") == expected_binary_hash, "Native executable identity changed")
        require(bool(attempt.artifacts), "Native calculation artifacts are missing")
    return {"run_id": record.run_id, "run_directory": str(store.run_dir),
            "snapshot_id": manifest["snapshot_id"], "record_sha256": manifest["record_sha256"],
            "native_attempt_count": len(native), "status": record.status,
            "request": record.request.model_dump(mode="json")}


def _archive_native(folder: Path, molecule: Molecule, method: MethodSpec,
                    payload: dict[str, Any], jobs: list[dict[str, Any]]) -> RunRecord:
    """Seal direct GOAT/CP observations without declaring reviewable minima."""
    request = RunRequest(molecule=molecule, engine="orca", method=method.method, purpose="energy",
                         basis=method.basis, auxiliary_basis=method.auxiliary_basis,
                         profile_id="orca-mapping-v4.1", engine_version="6.1.1", n_candidates=1)
    record = RunRecord(request=request, status=payload["status"],
                       validation_status=payload.get("validation_status", "validated-for-protocol" if payload["status"] == "completed" else "rejected"),
                       metadata={"run_dir": str(folder), "scope": "native acceptance observations; no conformer review inferred"})
    for job in jobs:
        result = job["result"]
        attempt = Attempt(run_id=record.run_id, engine=result["engine"], method=result["method"],
                          status=result["status"], engine_version=result.get("engine_version"),
                          command=result.get("command", []), converged=result.get("converged"),
                          validation_status="validated-for-protocol" if result["status"] == "completed" else "rejected",
                          metadata={**result.get("metadata", {}), "acceptance_role": job["role"]},
                          diagnostics=result.get("diagnostics", {}))
        for reference in result.get("artifacts", []):
            artifact = Artifact.model_validate(reference)
            path = Path(artifact.path).resolve()
            attempt.artifacts.append(artifact.model_copy(update={"path": path.relative_to(folder).as_posix()}))
        if result.get("energy_hartree") is not None:
            attempt.quantities.append(Quantity(name="electronic_energy", value=result["energy_hartree"],
                                               units="hartree", definition="native single-point electronic energy",
                                               attempt_id=attempt.attempt_id, method=method.method,
                                               parser="topos.engines/0.1.0", validity=attempt.validation_status))
        record.attempts.append(attempt)
    path = folder / "acceptance-native-result.json"
    atomic_json(path, payload)
    record.artifacts.append(Artifact(path=path.name, sha256=file_digest(path), size_bytes=path.stat().st_size,
                                     role="native-acceptance-result"))
    RunStore(folder).commit(record)
    RunStore(folder).verify()
    return record


def run_acceptance(registry: Path, output: Path, *, threads: int = 2, memory_mb: int = 2048,
                   budget_seconds: float = 3600, include_goat: bool = False,
                   include_counterpoise: bool = False) -> tuple[dict[str, Any], int]:
    output = output.expanduser().resolve()
    require(not output.exists(), "Acceptance output must be a fresh directory")
    require(not output.is_relative_to(SOURCE_ROOT), "Acceptance evidence must remain outside TOPOS source")
    require(math.isfinite(budget_seconds) and budget_seconds > 0, "Acceptance budget must be finite and positive")
    output.mkdir(parents=True)
    started = time.monotonic()
    deadline = started + budget_seconds
    report: dict[str, Any] = {
        "schema_version": "topos-orca-physical-acceptance/0.1.0", "status": "running", "started_at": utc_now(),
        "scope": "real TOPOS ORCA execution, derivatives, thermochemistry and artifact consistency",
        "scientific_accuracy_certified": False, "exhaustive_search_certified": False,
        "resources": {"threads": threads, "memory_mb": memory_mb, "budget_seconds": budget_seconds},
        "requested_cases": ["hf3c-energy-gradient", "r2scan3c-optimization-thermochemistry", "wb97xv-optimization"]
                           + (["counterpoise"] if include_counterpoise else []) + (["goat-refinement"] if include_goat else []),
        "cases": {}, "runs": [], "github_repository": os.environ.get("GITHUB_REPOSITORY"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_sha": os.environ.get("GITHUB_SHA"), "registry_path": str(registry.resolve()),
        "acceptance_script_sha256": file_digest(Path(__file__)),
    }
    receipt_path = output / "acceptance.json"
    atomic_json(receipt_path, report)
    try:
        runtime = BaseRuntime(registry)
        require(runtime.registry.stage0 is not None and len(runtime.registry.stage0.phases) == 11,
                "Complete mandatory-package Stage 0 authority is required")
        resources = ResourceLimits(threads=threads, memory_mb=memory_mb, budget_seconds=budget_seconds)
        runtime.validate_resources(resources)
        binary = runtime.resolve_executable("orca")
        identity = file_digest(Path(binary))
        report.update(base=runtime.provenance(), orca_executable=binary, orca_sha256=identity,
                      source=software_provenance(), registry_sha256=file_digest(registry))
        native_provenance = os.environ.get("COCHEM_ORCA_PROVENANCE")
        if native_provenance:
            source = Path(native_provenance)
            require(source.is_file() and not source.is_symlink(), "BASE ORCA distribution provenance is missing")
            shutil.copyfile(source, output / "orca-distribution-provenance.json")
        config = SystemConfig(execution_backend="base", base_registry_path=registry,
                              max_threads=threads, max_memory_mb=memory_mb)
        workflow = Workflow(output / "runs", config=config)

        def remaining(maximum: float) -> float:
            value = min(maximum, deadline - time.monotonic())
            require(value > 0, "Total acceptance wall-clock budget exhausted")
            return value

        def calculate(label: str, molecule: Molecule, method: str, purpose: str, *,
                      maximum: float = 300, **settings: Any) -> RunRecord:
            request = RunRequest(molecule=molecule, engine="orca", engine_version="6.1.1", method=method,
                                 purpose=purpose, profile_id="orca-mapping-v4.1", n_candidates=1,
                                 budget_seconds=remaining(maximum), threads=threads, memory_mb=memory_mb,
                                 metadata={"acceptance_case": label}, **settings)
            record = workflow.run(request)
            entry = {"label": label, "run_id": record.run_id, "run_directory": record.metadata["run_dir"],
                     "status": record.status}
            report["runs"].append(entry)
            atomic_json(receipt_path, report)
            entry.update(_verify_run(record, identity))
            return record

        def hf3c() -> dict[str, Any]:
            molecule = water()
            energy = calculate("hf3c-energy", molecule, "HF-3c", "energy")
            derivative = calculate("hf3c-gradient", molecule, "HF-3c", "gradient")
            gradient = np.asarray(_quantity(derivative, "cartesian_gradient"), dtype=float)
            require(gradient.shape == (3, 3) and np.isfinite(gradient).all(), "Native Cartesian gradient is invalid")
            reference_energy = float(_quantity(energy, "electronic_energy"))
            gradient_energy = float(_quantity(derivative, "electronic_energy"))
            require(abs(reference_energy - gradient_energy) < 1e-8, "Energy and gradient jobs disagree at the identical geometry")
            step = .002
            differences = np.empty((3, 3))
            for index in range(9):
                atom, axis = divmod(index, 3)
                energies = []
                for sign in (-1, 1):
                    coordinates = np.asarray(molecule.coordinates).copy()
                    coordinates[atom, axis] += sign * step * BOHR_ANGSTROM
                    displaced = Molecule.model_validate({**molecule.model_dump(), "coordinates": coordinates.tolist()})
                    sample = calculate(f"hf3c-difference-{index}-{sign:+d}", displaced, "HF-3c", "energy")
                    energies.append(float(_quantity(sample, "electronic_energy")))
                differences[atom, axis] = (energies[1] - energies[0]) / (2 * step)
            error = float(np.max(np.abs(differences - gradient)))
            require(error <= 2e-5, f"Analytic/finite-difference gradient discrepancy {error} Eh/bohr exceeds 2e-5")
            # A second step at the largest component tests displacement sensitivity.
            atom, axis = np.unravel_index(np.argmax(np.abs(gradient)), gradient.shape)
            half_step_energies = []
            for sign in (-1, 1):
                coordinates = np.asarray(molecule.coordinates).copy()
                coordinates[atom, axis] += sign * step / 2 * BOHR_ANGSTROM
                sample = calculate(f"hf3c-half-step-{sign:+d}", Molecule.model_validate({**molecule.model_dump(), "coordinates": coordinates.tolist()}), "HF-3c", "energy")
                half_step_energies.append(float(_quantity(sample, "electronic_energy")))
            half_derivative = (half_step_energies[1] - half_step_energies[0]) / step
            sensitivity = abs(half_derivative - differences[atom, axis])
            require(sensitivity <= 1e-5, "Finite-difference gradient is sensitive to halving the displacement")
            return {"energy_hartree": reference_energy, "gradient_hartree_per_bohr": gradient.tolist(),
                    "finite_difference_hartree_per_bohr": differences.tolist(), "step_bohr": step,
                    "max_absolute_error_hartree_per_bohr": error,
                    "half_step_difference_hartree_per_bohr": sensitivity,
                    "scope": "all nine Cartesian energy derivatives; internal numerical consistency, not chemical accuracy"}

        def thermochemistry() -> dict[str, Any]:
            record = calculate("r2scan3c-optimization-and-hessian", water(), "r2SCAN-3c", "thermochemistry", maximum=1800,
                               thermochemistry_options={"optimize_first": True, "symmetry_number": 2,
                                                        "step_bohr": .005, "frequency_scale": 1.0,
                                                        "low_frequency_policy": "reject"})
            aggregates = [attempt for attempt in record.attempts if attempt.metadata.get("result_kind") == "physical-hessian-thermochemistry"]
            require(len(aggregates) == 1, "Missing unique physical Hessian aggregation")
            aggregate = aggregates[0]
            require(len(aggregate.metadata.get("derivative_attempt_ids", [])) == 19,
                    "Water Hessian requires reference plus eighteen displaced gradients")
            analysis = aggregate.metadata["analysis"]
            thermal = aggregate.metadata["thermochemistry"]
            modes = analysis["frequencies_cm1"]
            require(analysis["stationary"] is True and analysis["validity"] == "harmonic-minimum-within-thresholds",
                    "Optimized water has not established a harmonic minimum")
            require(len(modes) == 3 and all(500 < value < 5000 for value in modes), "Unexpected water vibrational mode count or physical scale")
            require(thermal["status"] == "completed" and thermal["symmetry_number"] == 2,
                    "RRHO calculation or its explicit water symmetry convention is incomplete")
            require(0 < thermal["zpe_hartree"] < .05 and math.isfinite(thermal["gibbs_hartree"]), "Invalid physical thermal quantities")
            require(thermal["gibbs_hartree"] != float(next(q.value for q in aggregate.quantities if q.name == "electronic_energy")),
                    "Gibbs energy was replaced by electronic energy")
            return {"run_id": record.run_id, "derivative_attempt_count": 19,
                    "frequencies_cm1": modes, "analysis": analysis, "thermochemistry": thermal,
                    "accuracy_scope": "harmonic ideal-gas integration; no experimental accuracy claim"}

        def hybrid() -> dict[str, Any]:
            record = calculate("wb97xv-def2tzvpp-optimization", water(), "wB97X-V", "optimize", maximum=900,
                               basis="def2-TZVPP", auxiliary_basis="def2/J")
            require(len(record.candidates) == 1 and record.candidates[0].status == "eligible",
                    "Hybrid optimization did not yield an eligible geometry")
            attempt = record.attempts[0]
            require(attempt.metadata.get("resolved_auxiliary_basis") == "def2/J", "Hybrid fitting basis identity is missing")
            return {"run_id": record.run_id, "energy_hartree": record.candidates[0].energy_hartree,
                    "geometry": record.candidates[0].molecule.model_dump(mode="json"),
                    "stationary_point_scope": "native geometry convergence; no hybrid Hessian classification"}

        def cp() -> dict[str, Any]:
            from topos.counterpoise import execute_counterpoise

            export_resources = ResourceLimits(threads=1, memory_mb=min(memory_mb, 512), budget_seconds=remaining(120))
            exports = {}
            for role, basis in (("orbital", "def2-TZVPP"), ("auxiliary", "def2/J")):
                exports[role] = runtime.export_orca_basis(basis, ["He"], output / "basis-exports" / role,
                                                         export_resources.model_copy(update={"budget_seconds": remaining(120)}))
                require(exports[role]["status"] == "completed", f"Native {role} basis export failed")
            molecule = Molecule(symbols=["He", "He"], coordinates=[[0, 0, 0], [0, 0, 3]], fragments=[[0], [1]],
                                fragment_states=[{"atom_indices": [0], "charge": 0, "multiplicity": 1},
                                                 {"atom_indices": [1], "charge": 0, "multiplicity": 1}])
            method = MethodSpec(engine="orca", method="wB97M-V", basis="def2-TZVPP", auxiliary_basis="def2/J",
                                profile_id="orca-mapping-v4.1", engine_version="6.1.1")
            folder = output / "counterpoise-native"
            result = execute_counterpoise(molecule, method, resources.model_copy(update={"budget_seconds": remaining(900)}),
                                          folder, orbital_basis_file=exports["orbital"]["output_path"],
                                          auxiliary_basis_file=exports["auxiliary"]["output_path"],
                                          basis_export_receipts=exports, executable=binary, process_runner=runtime.run_process)
            sealed = _archive_native(folder, molecule, method, result, result["jobs"])
            report["runs"].append(_verify_run(sealed, identity))
            require(len(result["jobs"]) == 5, "Counterpoise did not execute all five physical legs")
            energies = result["energies"]
            legs = energies["leg_energies_hartree"]
            expected = legs["complex-in-complex-basis"] - legs["fragment-0-in-complex-basis"] - legs["fragment-1-in-complex-basis"]
            require(abs(expected - energies["cp_interaction_hartree"]) < 1e-12, "Counterpoise balance is inconsistent")
            return {"run_id": sealed.run_id, "energies": energies, "basis": result["basis"],
                    "basis_scope": "native ORCA distribution export authority and exact shared bytes verified in every leg"}

        def goat() -> dict[str, Any]:
            from topos.goat import run_goat

            # Native sampling currently uses natural isotope conventions.
            molecule = Molecule.model_validate({**water().model_dump(), "isotopes": [None, None, None]})
            method = MethodSpec(engine="orca", method="r2SCAN-3c", profile_id="orca-mapping-v4.1", engine_version="6.1.1")
            folder = output / "goat-native"
            result = run_goat(molecule, method, resources.model_copy(update={"budget_seconds": remaining(1200)}), folder,
                              executable=binary, process_runner=runtime.run_process, deterministic=True, max_global_iterations=3)
            payload = result.model_dump(mode="json")
            sealed = _archive_native(folder, molecule, method, payload, [{"role": "native-goat-search", "result": payload}])
            report["runs"].append(_verify_run(sealed, identity))
            require(result.converged is True and bool(result.ensemble), "Native GOAT did not complete its finite stopping criterion")
            refined = [calculate(f"goat-refinement-{index}", frame.molecule, "r2SCAN-3c", "optimize", maximum=300)
                       for index, frame in enumerate(result.ensemble)]
            return {"native_run_id": sealed.run_id, "native_frame_count": len(result.ensemble),
                    "refinement_run_ids": [record.run_id for record in refined],
                    "scope": "finite GOAT stopping criterion and all returned frames refined; no global/exhaustive claim"}

        cases: list[tuple[str, Callable[[], dict[str, Any]]]] = [
            ("hf3c-energy-gradient", hf3c), ("r2scan3c-optimization-thermochemistry", thermochemistry),
            ("wb97xv-optimization", hybrid),
        ]
        if include_counterpoise:
            cases.append(("counterpoise", cp))
        if include_goat:
            cases.append(("goat-refinement", goat))
        for name, evaluate in cases:
            case_start = time.monotonic()
            print(f"TOPOS ORCA acceptance: {name}", flush=True)
            try:
                details = evaluate()
                report["cases"][name] = {"status": "passed", "details": details}
            except Exception as exc:
                from topos.native_diagnostics import native_failure_tails

                report["cases"][name] = {"status": "failed", "reason": str(exc), "exception_type": type(exc).__name__}
                report["cases"][name]["native_failure_tails"] = native_failure_tails(output)
            report["cases"][name]["elapsed_seconds"] = time.monotonic() - case_start
            atomic_json(receipt_path, report)
            print(json.dumps({"case": name, **report["cases"][name]}), flush=True)
        require(file_digest(Path(binary)) == identity, "ORCA executable changed during acceptance")
        require(file_digest(registry) == report["registry_sha256"], "BASE registry changed during acceptance")
        require(software_provenance()["source_files"] == report["source"]["source_files"], "TOPOS source changed during acceptance")
        require(file_digest(Path(__file__)) == report["acceptance_script_sha256"], "Acceptance source changed during execution")
        require(set(report["cases"]) == set(report["requested_cases"]), "Some requested acceptance cases did not execute")
        require(all(case["status"] == "passed" for case in report["cases"].values()), "One or more requested physical acceptance cases failed")
        report["status"] = "passed"
    except Exception as exc:
        report.update(status="failed", failure=str(exc), exception_type=type(exc).__name__)
    finally:
        report["finished_at"] = utc_now()
        report["elapsed_seconds"] = time.monotonic() - started
        atomic_json(receipt_path, report)
    return report, 0 if report["status"] == "passed" else 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--memory-mb", type=int, default=2048)
    parser.add_argument("--budget-seconds", type=float, default=3600)
    parser.add_argument("--include-goat", action="store_true")
    parser.add_argument("--include-counterpoise", action="store_true")
    args = parser.parse_args()
    try:
        report, code = run_acceptance(args.registry, args.output, threads=args.threads, memory_mb=args.memory_mb,
                                     budget_seconds=args.budget_seconds, include_goat=args.include_goat,
                                     include_counterpoise=args.include_counterpoise)
    except (OSError, ValueError, AcceptanceFailure) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        return 3
    print(json.dumps({"status": report["status"], "receipt": str(args.output / "acceptance.json")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
