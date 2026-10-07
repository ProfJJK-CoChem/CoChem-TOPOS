"""Genuine BASE-mediated native Hessian, VPT2 and correlated ORCA acceptance.

Each selected case must execute. Missing engines, skipped cases and parser-only
fixtures cannot pass. Small water cases check implementation, not matrix accuracy.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from topos.anharmonic import run_orca_vpt2
from topos.base_integration import BaseRuntime
from topos.correlated import CorrelatedMethod, run_correlated
from topos.engines import EngineResult, run_engine
from topos.models import MethodSpec, Molecule, ResourceLimits, utc_now
from topos.native_diagnostics import native_failure_tails
from topos.native_hessian import run_orca_hessian
from topos.storage import atomic_json, file_digest
from topos.workflow import software_provenance

CASES = ("native-hessian", "native-vpt2", "MP2", "MP2-optimization", "CCSD(T)", "AUTOCI-CCSD(T)",
         "DLPNO-CCSD(T1)", "CCSD(T)-F12D/RI", "F12-MP2", "F12-RI-MP2", "DLPNO-counterpoise", "F12-composite",
         "R2-composite")



def correlated_cp_case(runtime: BaseRuntime, folder: Path, resources: ResourceLimits) -> dict:
    """Exercise exact native exports and ghost centers; no full-R2 completion claim."""
    from topos.config import SystemConfig
    from topos.correlated_counterpoise import (
        R2_ENERGY_RESOLUTION,
        CorrelatedCounterpoiseProtocol,
        run_r2_counterpoise,
    )
    from topos.models import RunRecord, RunRequest
    from topos.storage import RunStore
    from topos.workflow import Workflow

    molecule = Molecule(symbols=["O", "H", "H", "O", "H", "H"],
        coordinates=[[0, 0, 0], [.96, 0, 0], [-.24, .93, 0],
                     [3, 0, 0], [3.96, 0, 0], [2.76, .93, 0]],
        fragments=[[0, 1, 2], [3, 4, 5]], fragment_states=[
            {"atom_indices": [0, 1, 2], "charge": 0, "multiplicity": 1},
            {"atom_indices": [3, 4, 5], "charge": 0, "multiplicity": 1}])
    native = CorrelatedMethod(method="DLPNO-CCSD(T1)", operation="energy", orbital_basis="cc-pVDZ-F12",
        auxiliary_c="cc-pVTZ/C", auxiliary_jk="cc-pVTZ/JK", scf_integrals="RIJK", frozen_core=True,
        pno_profile="TightPNO", tcutpno=1e-7)
    protocol = CorrelatedCounterpoiseProtocol(native=native, source_resolution=R2_ENERGY_RESOLUTION)
    request = RunRequest(molecule=molecule, purpose="energy", engine="orca", method=native.method,
        basis=native.orbital_basis, auxiliary_basis=native.auxiliary_c,
        budget_seconds=resources.budget_seconds, threads=resources.threads, memory_mb=resources.memory_mb)
    record = RunRecord(request=request, status="running", metadata={"run_dir": str(folder / "run"),
        "scope": "native frozen counterpoise interaction contribution; no full R2, optimization or thermochemistry claim"})
    store = RunStore(folder / "run")
    store.commit(record)
    workflow = Workflow(folder / "runs", config=SystemConfig(execution_backend="base", base_registry_path=runtime.registry_path))
    workflow.base_runtime = runtime
    deadline = time.monotonic() + resources.budget_seconds
    result = run_r2_counterpoise(workflow, record, store, molecule, protocol, deadline)
    if result is None:
        raise RuntimeError(f"Native correlated counterpoise did not complete: {record.status}; {record.metadata.get('termination_reason')}")
    if (len(record.attempts) != 3 or result["full_R2_recipe_completed"] is not False
            or result["f12_hamiltonian"] is not False or result["basis_identity"] != "native-export-verified"
            or any(a.status != "completed" or a.metadata.get("execution_kind") != "real" for a in record.attempts)):
        raise RuntimeError("Native three-leg counterpoise evidence is incomplete or overstates its scope")
    count = len(record.attempts)
    replay = run_r2_counterpoise(workflow, record, store, molecule, protocol, deadline)
    if replay != result or len(record.attempts) != count:
        raise RuntimeError("Correlated counterpoise replay did not reuse all exact completed native legs")
    record.status, record.validation_status = "completed", "validated-for-protocol"
    record.metadata["correlated_cp_acceptance"] = result
    store.commit(record)
    snapshot = store.verify()
    atomic_json(folder / "native-result.json", result)
    return {"recovery_verified": True, "protocol": protocol.model_dump(mode="json"),
            "interaction_energy_hartree": result["cp_interaction_energy_hartree"],
            "native_leg_count": count, "native_basis_exports": sorted(protocol.basis_names().values()),
            "scope": "frozen interaction-energy contribution only; no full R2 or vibrational correction",
            "snapshot_id": snapshot["snapshot_id"], "result_sha256": file_digest(folder / "native-result.json")}


def run_acceptance(registry: Path, output: Path, *, cases=CASES, budget_seconds=7200,
                   threads=2, memory_mb=4096) -> tuple[dict, int]:
    output = output.resolve()
    if output.exists() or output.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError("Extended acceptance requires a fresh output directory outside source")
    if not cases or len(set(cases)) != len(cases) or set(cases) - set(CASES):
        raise ValueError("Choose distinct supported native cases")
    resources = ResourceLimits(budget_seconds=budget_seconds, threads=threads, memory_mb=memory_mb)
    output.mkdir(parents=True)
    report = {"schema_version": "topos-orca-extended-acceptance/0.1.0", "status": "running",
              "started_at": utc_now(), "requested_cases": list(cases), "cases": {},
              "accuracy_benchmark": False, "scope": "actual small-molecule native calculation and recovery",
              "source": software_provenance(), "script_sha256": file_digest(Path(__file__)),
              "github_repository": os.environ.get("GITHUB_REPOSITORY"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"), "github_sha": os.environ.get("GITHUB_SHA")}
    receipt = output / "acceptance.json"
    atomic_json(receipt, report)
    deadline = time.monotonic() + budget_seconds
    try:
        runtime = BaseRuntime(registry)
        runtime.validate_resources(resources)
        binary = runtime.resolve_executable("orca")
        binary_hash = file_digest(Path(binary))
        report.update(base=runtime.provenance(), orca_executable_sha256=binary_hash)
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        report.update(status="unavailable", reason=str(exc), finished_at=utc_now())
        atomic_json(receipt, report)
        return report, 3
    molecule = Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.96, 0, 0], [-.24, .93, 0]])

    def remaining(maximum: float = 1200):
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("Extended native acceptance budget exhausted")
        return resources.model_copy(update={"budget_seconds": min(seconds, maximum)})

    def retain(result: EngineResult, folder: Path, label: str):
        atomic_json(folder / (label + "-result.json"), result.model_dump(mode="json"))
        if (result.status != "completed" or not result.converged or result.engine_version != "6.1.1"
                or result.metadata.get("execution_kind") != "real" or not result.command
                or result.metadata.get("executable_sha256") != binary_hash or not result.artifacts):
            raise RuntimeError(f"{label} did not establish a genuine completed native result: {result.status}; {result.diagnostics}")
        for artifact in result.artifacts:
            path = Path(artifact.path)
            if not path.resolve().is_relative_to(folder) or path.is_symlink() or file_digest(path) != artifact.sha256:
                raise RuntimeError("Native result evidence changed or escaped the case directory")
        return result

    for case in cases:
        folder = output / case.replace("/", "_")
        folder.mkdir()
        report["cases"][case] = {"status": "running", "started_at": utc_now()}
        atomic_json(receipt, report)
        try:
            if case == "R2-composite":
                from orca_r2_acceptance_case import r2_composite_case

                details = r2_composite_case(runtime, folder, remaining(5400))
            elif case == "F12-composite":
                from orca_f12_acceptance_case import f12_composite_case

                details = f12_composite_case(runtime, folder, remaining(2400))
            elif case == "DLPNO-counterpoise":
                details = correlated_cp_case(runtime, folder, remaining())
            elif case in {"native-hessian", "native-vpt2"}:
                method = (MethodSpec(engine="orca", method="r2SCAN-3c", profile_id="orca-mapping-v4.1")
                          if case == "native-hessian" else MethodSpec(engine="orca", method="B3LYP", basis="def2-TZVPP",
                              auxiliary_basis="def2/J", dispersion="D4", profile_id="orca-vpt2-reference-v1"))
                optimized = retain(run_engine(molecule, method, remaining(), folder / "optimization", executable=binary,
                                               process_runner=runtime.run_process), folder, "optimization")
                dft_import = None
                if case == "native-hessian":
                    from orca_dft_import_acceptance import verify_optimized_dft_import

                    dft_import = verify_optimized_dft_import(optimized, molecule, folder / "dft-reference-import")
                native = run_orca_hessian if case == "native-hessian" else run_orca_vpt2
                options = {"semirigid_modes": True} if case == "native-vpt2" else {}
                result = retain(native(optimized.molecule, method, remaining(), folder / "native",
                    executable=binary, process_runner=runtime.run_process, **options), folder, "native")
                if case == "native-hessian":
                    if result.metadata["analysis"]["validity"] != "harmonic-minimum-within-thresholds":
                        raise RuntimeError("Actual native Hessian did not establish a minimum")
                elif len(result.metadata["vpt2"]["fundamental_transitions"]) != 3:
                    raise RuntimeError("Actual water VPT2 fundamental table is incomplete")
                replay = native(optimized.molecule, method, remaining(), folder / "native", executable=binary,
                                process_runner=runtime.run_process, **options)
                reuse = "reused_completed_hessian" if case == "native-hessian" else "reused_completed_vpt2"
                if not replay.metadata.get(reuse) or replay.command != result.command:
                    raise RuntimeError("Native completed-stage recovery did not reuse verified evidence")
                details = {"recovery_verified": True, "energy_hartree": result.energy_hartree,
                           "result_sha256": file_digest(folder / "native-result.json")}
                if dft_import is not None:
                    details["optimized_dft_reference_import"] = dft_import
            else:
                f12 = case in {"CCSD(T)-F12D/RI", "F12-MP2", "F12-RI-MP2"}
                local = case == "DLPNO-CCSD(T1)"
                protocol = CorrelatedMethod(method="MP2" if case == "MP2-optimization" else case,
                    operation="optimize" if case == "MP2-optimization" else "gradient" if case == "AUTOCI-CCSD(T)" else "energy",
                    orbital_basis="cc-pVDZ-F12" if f12 or local else "cc-pVDZ", frozen_core=True,
                    auxiliary_c="cc-pVTZ/C" if local or case in {"CCSD(T)-F12D/RI", "F12-RI-MP2"} else None,
                    cabs="cc-pVDZ-F12-CABS" if f12 else None,
                    pno_profile="TightPNO" if local else None, tcutpno=1e-7 if local else None)
                result = retain(run_correlated(molecule, protocol, remaining(), folder / "native", executable=binary,
                                                process_runner=runtime.run_process), folder, "native")
                if case == "AUTOCI-CCSD(T)" and result.gradient_hartree_per_bohr is None:
                    raise RuntimeError("Native AUTOCI gradient is missing")
                if case == "MP2-optimization":
                    if (result.gradient_hartree_per_bohr is None or result.molecule is None
                            or not (folder / "native" / "final-gradient" / "job.engrad").is_file()
                            or not result.diagnostics.get("independent_stationarity", {}).get("passed")):
                        raise RuntimeError("Native MP2 optimization lacks independently verified final gradient/stationarity")
                details = {"protocol": protocol.model_dump(mode="json"), "energy_hartree": result.energy_hartree,
                           "result_sha256": file_digest(folder / "native-result.json")}
            report["cases"][case].update(status="passed", **details)
        except (ValueError, RuntimeError, OSError, ImportError) as exc:
            report["cases"][case].update(status="failed", reason=str(exc), exception=type(exc).__name__)
            report["cases"][case]["native_failure_tails"] = native_failure_tails(folder)
        report["cases"][case]["finished_at"] = utc_now()
        atomic_json(receipt, report)
        print(json.dumps({"case": case, **report["cases"][case]}), flush=True)
    report["status"] = "passed" if all(item["status"] == "passed" for item in report["cases"].values()) else "failed"
    report["finished_at"] = utc_now()
    atomic_json(receipt, report)
    return report, 0 if report["status"] == "passed" else 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", choices=CASES)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--memory-mb", type=int, default=4096)
    parser.add_argument("--budget-seconds", type=float, default=7200)
    args = parser.parse_args()
    report, code = run_acceptance(args.registry, args.output, cases=args.case or CASES,
        threads=args.threads, memory_mb=args.memory_mb, budget_seconds=args.budget_seconds)
    print(f"{report['status']}: {args.output / 'acceptance.json'}")
    if report.get("reason"):
        print(json.dumps({"status": report["status"], "reason": report["reason"]}), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
