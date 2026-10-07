"""Import an already executed hosted DFT optimization; no additional calculation."""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np

from topos.engines import EngineResult
from topos.ml_training import DFTSourcePoint, import_dft_point
from topos.models import Artifact, Attempt, MethodSpec, Molecule, Quantity, RunRecord, RunRequest
from topos.storage import RunStore, atomic_json, confined_file, digest_json, file_digest


def verify_optimized_dft_import(result: EngineResult, initial: Molecule, folder: Path) -> dict:
    """Retain exact real raw bytes in a RunStore and exercise the production importer."""
    if (result.status != "completed" or result.converged is not True or result.engine != "orca"
            or result.engine_version != "6.1.1" or result.operation != "optimize"
            or result.metadata.get("execution_kind") != "real" or not result.command
            or result.molecule is None or result.energy_hartree is None
            or result.gradient_hartree_per_bohr is None or not result.artifacts):
        raise ValueError("DFT import acceptance requires an actual completed ORCA optimization and final gradient")
    folder = folder.resolve()
    if folder.exists() or folder.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError("DFT import acceptance requires a fresh directory outside source")
    original_root = Path(result.diagnostics["process"]["stdout_path"]).parent.resolve(strict=True)
    if original_root.is_relative_to(folder):
        raise ValueError("Source engine artifacts cannot be staged in the new import proof directory")
    resources = result.metadata["resources"]
    method = MethodSpec.model_validate(result.metadata["requested_method"])
    request = RunRequest(molecule=initial, engine="orca", method=result.method, purpose="optimize",
        engine_version="6.1.1", budget_seconds=resources["budget_seconds"], threads=resources["threads"],
        memory_mb=resources["memory_mb"], device=resources["device"], profile_id=method.profile_id,
        basis=method.basis, auxiliary_basis=method.auxiliary_basis, dispersion=method.dispersion,
        solvent=method.solvent, constraints=method.constraints)
    record = RunRecord(request=request, status="completed", validation_status="validated-for-protocol", metadata={
        "scope": "Retention/import of existing native optimization; no additional engine execution or training",
        "source_engine_result_sha256": digest_json(result.model_dump(mode="json")),
        "acceptance_helper_sha256": file_digest(Path(__file__))})
    attempt = Attempt(run_id=record.run_id, engine=result.engine, engine_version=result.engine_version,
        method=result.method, status="completed", converged=True, validation_status="validated-for-protocol",
        command=list(result.command), diagnostics=result.diagnostics,
        metadata={**result.metadata, "operation": "optimize", "role": "retained-existing-native-optimization",
                  "input_molecule": initial.model_dump(mode="json"),
                  "output_molecule": result.molecule.model_dump(mode="json")})
    store = RunStore(folder / "run")
    evidence_root = store.run_dir / "attempts" / attempt.attempt_id
    for artifact in result.artifacts:
        try:
            relative = Path(artifact.path).absolute().relative_to(original_root).as_posix()
        except ValueError as exc:
            raise ValueError("Native result artifact escapes its original attempt") from exc
        source = confined_file(original_root, relative)
        if source.stat().st_size != artifact.size_bytes or file_digest(source) != artifact.sha256:
            raise ValueError("Original native evidence changed before DFT import acceptance")
        target = evidence_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        attempt.artifacts.append(artifact.model_copy(update={"path": target.relative_to(store.run_dir).as_posix()}))
    for name, value, units in (("electronic_energy", result.energy_hartree, "hartree"),
                                ("cartesian_gradient", result.gradient_hartree_per_bohr, "hartree/bohr")):
        attempt.quantities.append(Quantity(name=name, value=value, units=units, attempt_id=attempt.attempt_id,
            method=result.method, validity="validated-for-protocol",
            definition="Unchanged quantity from the retained actual native optimization/final-gradient result"))
    record.attempts.append(attempt)
    original_result = store.run_dir / "original-engine-result.json"
    atomic_json(original_result, result.model_dump(mode="json"))
    record.artifacts.append(Artifact(path=original_result.name, sha256=file_digest(original_result),
        size_bytes=original_result.stat().st_size, role="retained-original-native-engine-result"))
    store.commit(record)
    snapshot = store.verify()
    source = DFTSourcePoint(run_dir=str(store.run_dir), record_sha256=snapshot["record_sha256"],
        attempt_id=attempt.attempt_id, group_id="hosted-native-optimization-import", partition="test")
    imported = import_dft_point(source, folder / "reference")
    if (imported.molecule.model_dump(mode="json") != result.molecule.model_dump(mode="json")
            or abs(imported.energy_hartree - result.energy_hartree) > 2e-7
            or not np.allclose(imported.gradient_hartree_per_bohr, result.gradient_hartree_per_bohr, rtol=0, atol=1e-12)
            or not (folder / "reference/final-gradient/job.engrad").is_file()):
        raise RuntimeError("Imported DFT reference differs from the actual optimized final-gradient observation")
    report = {"status": "passed", "additional_native_calculations": 0, "training_performed": False,
        "source_record_sha256": source.record_sha256, "snapshot_id": snapshot["snapshot_id"],
        "source_engine_result_sha256": record.metadata["source_engine_result_sha256"],
        "reference_sha256": file_digest(folder / "reference/reference.json"),
        "final_gradient_sha256": file_digest(folder / "reference/final-gradient/job.engrad"),
        "energy_hartree": imported.energy_hartree,
        "scope": "One genuine optimized DFT point with exact native final-stage binding; not a training dataset or model"}
    atomic_json(folder / "acceptance.json", report)
    return report
