"""Controlled-dependency transport only, never a scientific native success.

The genuine failed TOPOS receipt remains unchanged and cannot establish the new
controlled-dependency acceptance contract. Positive extension cases use explicitly
inert authority metadata and genuine failed stdout, never chemistry or live authority.
No licensed basis bytes or native executables exist in these fixtures.
"""

from __future__ import annotations

import copy
import hashlib
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import topos
from topos.engines import EngineParseError, artifact_inventory
from topos.external_engines import ExternalProtocol, _native_completion
from topos.matrix_components import run_component, verify_cfour_runtime_receipts
from topos.models import Molecule, RunRecord, RunRequest
from topos.storage import IntegrityError, RunStore, atomic_json, file_digest, read_json

FIXTURE = Path(__file__).parent / "fixtures/cfour_controlled_transport"
FAILED = Path(__file__).parent / "fixtures/cfour_failed_first_order"
if not FAILED.is_dir():
    FAILED = Path(topos.__file__).parent.parent / "tests/v010/fixtures/cfour_failed_first_order"


@pytest.fixture
def scientific_transport(tmp_path):
    proof = read_json(FIXTURE / "provenance.json")
    assert file_digest(FIXTURE / "engine-cfour-runtime.json") == proof["runtime_receipt_sha256"]
    assert (
        file_digest(FIXTURE / "registry-basis-excerpt.json")
        == proof["registry_basis_excerpt_sha256"]
    )
    receipt = read_json(FIXTURE / "engine-cfour-runtime.json")
    basis = read_json(FIXTURE / "registry-basis-excerpt.json")
    source = Path(receipt["workdir"]).parent
    root = tmp_path / "scientific-only"
    evaluation = root / "evaluation-00000"
    evaluation.mkdir(parents=True)
    for source_file, dest in [
        (FAILED / "native-ZMAT.inp", "ZMAT"),
        (FAILED / "output.stdout", "engine.stdout"),
        (FIXTURE / "engine-cfour-runtime.json", "engine-cfour-runtime.json"),
    ]:
        (evaluation / dest).write_bytes(source_file.read_bytes())
    (evaluation / "engine.stderr").write_text("")
    retained = {
        p.relative_to(root).as_posix(): {"sha256": file_digest(p), "size_bytes": p.stat().st_size}
        for p in evaluation.iterdir()
    }
    policy = {
        "schema": "topos-cfour-scientific-evidence/1",
        "source_directory": str(source),
        "retained_files": retained,
        "omitted_files": [
            {
                "path": "evaluation-00000/GENBAS",
                "classification": "licensed-basis",
                "sha256": basis["GENBAS"]["sha256"],
                "size_bytes": basis["GENBAS"]["bytes"],
            }
        ],
        "omitted_links": [],
        "controlled_basis_library": basis["GENBAS"],
        "controlled_runtime_dependencies": {},
        "native_rerun_self_contained": False,
        "licensed_assets_included": False,
    }
    return root, receipt["runtime_before"], basis, policy


@pytest.fixture
def current_receipt_bookkeeping(scientific_transport):
    """Unexecuted metadata extension, explicitly distinct from the genuine receipt."""
    root, _, basis, policy = scientific_transport
    policy = copy.deepcopy(policy)
    authority = {
        "runtime_seal_sha256": "a" * 64,
        "binary_sha256": "b" * 64,
        "executable": "/bookkeeping/not-a-native-executable",
        "identity_scope": "Unexecuted dependency-extension bookkeeping; not native authority",
    }
    policy["source_directory"] = str(root)
    dependencies = {
        k: {"path": v["path"], "sha256": v["sha256"], "size_bytes": v["bytes"]}
        for k, v in basis.items()
    }
    policy["controlled_runtime_dependencies"] = dependencies
    path = root / "evaluation-00000/engine-cfour-runtime.json"
    receipt = read_json(path)
    receipt.update(
        runtime_before=authority,
        runtime_after=authority,
        command=[authority["executable"]],
        workdir=str(path.parent),
        controlled_runtime_dependencies=copy.deepcopy(dependencies),
    )
    atomic_json(path, receipt)
    policy["retained_files"]["evaluation-00000/engine-cfour-runtime.json"] = {
        "sha256": file_digest(path),
        "size_bytes": path.stat().st_size,
    }
    return root, authority, basis, policy


def request(fixture, policy=None):
    root, authority, basis, original = fixture
    policy = copy.deepcopy(original if policy is None else policy)
    atomic_json(root / "cfour-evidence-policy.json", policy)
    artifacts = artifact_inventory(root)
    for a in artifacts:
        if Path(a.path).name == "cfour-evidence-policy.json":
            a.role = "cfour-evidence-policy"
    originals = [
        {
            **a.model_dump(mode="json"),
            "path": str(Path(policy["source_directory"]) / Path(a.path).relative_to(root)),
        }
        for a in artifacts
    ]
    kwargs = {
        "original_artifacts": originals,
        "evidence_policy": policy,
        "evidence_policy_sha256": file_digest(root / "cfour-evidence-policy.json"),
        "controlled_basis": basis["GENBAS"],
        "protocol_basis_sha256": basis["GENBAS"]["sha256"],
        "controlled_dependencies": {
            k: {"path": v["path"], "sha256": v["sha256"], "size_bytes": v["bytes"]}
            for k, v in basis.items()
        },
    }
    return artifacts, root, authority, kwargs


def test_real_failed_receipt_cannot_be_relabelled_current_acceptance(scientific_transport):
    args = request(scientific_transport)
    with pytest.raises(IntegrityError, match="controlled runtime dependency inventory"):
        verify_cfour_runtime_receipts(*args[:3], **args[3])
    assert (args[1] / "evaluation-00000/engine-cfour-runtime.json").read_bytes() == (
        FIXTURE / "engine-cfour-runtime.json"
    ).read_bytes()
    assert not list(args[1].rglob("GENBAS")) and not list(args[1].rglob("ECPDATA"))
    with pytest.raises(EngineParseError):
        _native_completion(
            (args[1] / "evaluation-00000/engine.stdout").read_text(),
            ExternalProtocol(
                engine="cfour",
                engine_version="2.1",
                method="CCSD(T)",
                operation="first-order-properties",
                orbital_basis="PVTZ",
                frozen_core=False,
            ),
        )


@pytest.mark.parametrize(
    "field",
    [
        "basis",
        "protocol",
        "audited-path",
        "policy-digest",
        "embedded",
        "missing-policy",
        "role",
        "source",
    ],
)
def test_policy_and_independent_basis_binding_reject_tamper(current_receipt_bookkeeping, field):
    artifacts, root, authority, kwargs = request(current_receipt_bookkeeping)
    if field == "basis":
        kwargs["controlled_basis"] = {**kwargs["controlled_basis"], "sha256": "0" * 64}
    elif field == "protocol":
        kwargs["protocol_basis_sha256"] = "0" * 64
    elif field == "audited-path":
        kwargs["controlled_basis"] = {**kwargs["controlled_basis"], "path": "/different/GENBAS"}
    elif field == "policy-digest":
        kwargs["evidence_policy_sha256"] = "0" * 64
    elif field == "embedded":
        kwargs["evidence_policy"]["licensed_assets_included"] = True
    elif field == "missing-policy":
        kwargs["evidence_policy"] = None
    elif field == "role":
        next(a for a in artifacts if a.role == "cfour-evidence-policy").role = "raw-output"
    elif field == "source":
        kwargs["evidence_policy"]["source_directory"] = "/another/attempt"
    with pytest.raises(IntegrityError, match="CFOUR"):
        verify_cfour_runtime_receipts(artifacts, root, authority, **kwargs)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "digest",
        "size",
        "directory",
        "classification",
        "duplicate",
        "traversal",
        "retained",
        "extra-file",
        "science-link",
    ],
)
def test_omitted_and_retained_membership_are_exact(current_receipt_bookkeeping, change):
    root, authority, basis, policy = current_receipt_bookkeeping
    policy = copy.deepcopy(policy)
    omitted = policy["omitted_files"][0]
    if change == "missing":
        policy["omitted_files"] = []
    elif change == "digest":
        omitted["sha256"] = "0" * 64
    elif change == "size":
        omitted["size_bytes"] += 1
        policy["controlled_runtime_dependencies"] = {
            k: {"path": v["path"], "sha256": v["sha256"], "size_bytes": v["bytes"]}
            for k, v in basis.items()
        }
    elif change == "directory":
        omitted["path"] = "other/GENBAS"
    elif change == "classification":
        omitted["classification"] = "native-scratch"
    elif change == "duplicate":
        policy["omitted_files"].append(copy.deepcopy(omitted))
    elif change == "traversal":
        omitted["path"] = "../GENBAS"
    elif change == "retained":
        policy["retained_files"]["evaluation-00000/engine.stdout"]["sha256"] = "0" * 64
    elif change == "extra-file":
        (root / "unapproved-scratch").write_text("Inert bookkeeping")
    elif change == "science-link":
        policy["omitted_links"] = [
            {
                "path": "evaluation-00000/EFG",
                "link_text": "/outside/EFG",
                "disposition": "not-followed-or-retained",
            }
        ]
    artifacts, root, authority, kwargs = request(current_receipt_bookkeeping, policy)
    with pytest.raises(IntegrityError):
        verify_cfour_runtime_receipts(artifacts, root, authority, **kwargs)


def test_independent_ecpdata_registry_binding(current_receipt_bookkeeping):
    root, authority, basis, policy = current_receipt_bookkeeping
    policy = copy.deepcopy(policy)
    policy["controlled_runtime_dependencies"] = {
        k: {"path": v["path"], "sha256": v["sha256"], "size_bytes": v["bytes"]}
        for k, v in basis.items()
    }
    artifacts, root, authority, kwargs = request(current_receipt_bookkeeping, policy)
    # Constructed extension bookkeeping binds independently retained real registry
    # identities; the scientific stdout still contains the genuine native failure.
    assert (
        verify_cfour_runtime_receipts(artifacts, root, authority, **kwargs)["native_evaluations"]
        == 1
    )
    kwargs["controlled_dependencies"]["ECPDATA"]["sha256"] = "0" * 64
    with pytest.raises(IntegrityError, match="retained audited registry"):
        verify_cfour_runtime_receipts(artifacts, root, authority, **kwargs)


def test_renamed_basis_digest_is_omitted_as_licensed(current_receipt_bookkeeping):
    policy = copy.deepcopy(current_receipt_bookkeeping[3])
    policy["omitted_files"].append(
        {**policy["omitted_files"][0], "path": "scratch/copy-of-controlled-library"}
    )
    args = request(current_receipt_bookkeeping, policy)
    assert verify_cfour_runtime_receipts(*args[:3], **args[3])["native_evaluations"] == 1


def test_cannot_launder_unlisted_file_as_matrix_receipt(current_receipt_bookkeeping):
    root = current_receipt_bookkeeping[0]
    (root / "unapproved-scratch").write_text("Bookkeeping only")
    artifacts, root, authority, kwargs = request(current_receipt_bookkeeping)
    next(
        a for a in artifacts if Path(a.path).name == "unapproved-scratch"
    ).role = "matrix-native-component-result"
    with pytest.raises(IntegrityError, match="absent from its policy"):
        verify_cfour_runtime_receipts(artifacts, root, authority, **kwargs)


@pytest.mark.parametrize(
    "tamper", [False, "digest", "empty", "missing-receipt-field", "missing-both"]
)
def test_constructed_dependency_extension_is_bound_to_policy(current_receipt_bookkeeping, tamper):
    """Explicitly inert authority bookkeeping; no claim of a native receipt.

    The raw science remains genuine failed output. Every constructed authority
    label identifies this as unexecuted transport, with no executable or energy.
    """
    root, _, basis, policy = current_receipt_bookkeeping
    policy = copy.deepcopy(policy)
    authority = {
        "runtime_seal_sha256": "a" * 64,
        "binary_sha256": "b" * 64,
        "executable": "/bookkeeping/not-a-native-executable",
        "identity_scope": "Unexecuted dependency-extension bookkeeping; not native authority",
    }
    policy["source_directory"] = str(root)
    dependencies = {
        k: {"path": v["path"], "sha256": v["sha256"], "size_bytes": v["bytes"]}
        for k, v in basis.items()
    }
    policy["controlled_runtime_dependencies"] = dependencies
    receipt_path = root / "evaluation-00000/engine-cfour-runtime.json"
    receipt = read_json(receipt_path)
    receipt.update(
        runtime_before=authority,
        runtime_after=authority,
        command=[authority["executable"]],
        workdir=str(receipt_path.parent),
        controlled_runtime_dependencies=copy.deepcopy(dependencies),
    )
    if tamper == "digest":
        receipt["controlled_runtime_dependencies"]["ECPDATA"]["sha256"] = "0" * 64
    elif tamper == "empty":
        receipt["controlled_runtime_dependencies"] = {}
        policy["controlled_runtime_dependencies"] = {}
    if tamper in {"missing-receipt-field", "missing-both"}:
        del receipt["controlled_runtime_dependencies"]
        if tamper == "missing-both":
            policy["controlled_runtime_dependencies"] = {}
    atomic_json(receipt_path, receipt)
    policy["retained_files"]["evaluation-00000/engine-cfour-runtime.json"] = {
        "sha256": file_digest(receipt_path),
        "size_bytes": receipt_path.stat().st_size,
    }
    args = request((root, authority, basis, policy))
    if tamper:
        with pytest.raises(IntegrityError, match="CFOUR.*dependenc"):
            verify_cfour_runtime_receipts(*args[:3], **args[3])
    else:
        proof = verify_cfour_runtime_receipts(*args[:3], **args[3])
        assert proof["native_evaluations"] == 1 and not Path(authority["executable"]).exists()


@pytest.mark.parametrize(
    "state", ["prelaunch-absolute", "prelaunch-relative", "observed-canonical"]
)
def test_failed_ledger_recovery_does_not_reinventory_basis_bytes(tmp_path, state):
    """Failure bookkeeping only: executor raises, never constructs native success."""
    marker = b"Inert controlled-byte marker; not a chemistry basis library\n"
    authority = {
        "runtime_seal_sha256": "a" * 64,
        "binary_sha256": "b" * 64,
        "executable": "/bookkeeping/not-a-native-executable",
        "identity_scope": "Unexecuted failed-ledger recovery; not native authority",
    }
    molecule = Molecule(symbols=["He"], coordinates=[[0, 0, 0]])
    protocol = ExternalProtocol(
        engine="cfour",
        engine_version="2.1",
        method="HF",
        operation="energy",
        orbital_basis="PVTZ",
        frozen_core=False,
        genbas_path="/unexecuted/GENBAS" if state == "prelaunch-absolute" else "relative/GENBAS",
        genbas_sha256=hashlib.sha256(marker).hexdigest(),
    )
    record = RunRecord(request=RunRequest(molecule=molecule), status="running")
    store = RunStore(tmp_path / "ledger")
    workflow = SimpleNamespace(
        base_runtime=SimpleNamespace(
            cfour_runtime_identity=lambda: authority,
            resolve_executable=lambda *args: authority["executable"],
            run_process=None,
        ),
        config=SimpleNamespace(executables={}, execution_backend="development"),
    )

    def failing_executor(molecule, protocol, resources, folder, **kwargs):
        folder.mkdir(parents=True)
        (folder / "GENBAS").write_bytes(marker)
        (folder / "engine.stdout").write_bytes((FAILED / "output.stdout").read_bytes())
        if state == "observed-canonical":
            # Inert metadata only: represents a resolved library identity without
            # constructing native completion, an energy, or any authorization.
            record.attempts[-1].metadata["basis_library"] = {
                "path": "/controlled/GENBAS",
                "sha256": hashlib.sha256(marker).hexdigest(),
            }
        raise RuntimeError("Deliberate bookkeeping interruption before any native launch")

    with pytest.raises(RuntimeError, match="Deliberate bookkeeping interruption"):
        run_component(
            workflow,
            record,
            store,
            "unexecuted-recovery",
            molecule,
            protocol,
            failing_executor,
            time.monotonic() + 30,
            None,
        )
    retained = store.load()
    attempt = retained["attempts"][0]
    assert retained["status"] == "failed" and attempt["status"] == "failed"
    assert (
        attempt["diagnostics"]["reason"]
        == "Deliberate bookkeeping interruption before any native launch"
    )
    assert all(Path(a["path"]).name != "GENBAS" for a in attempt["artifacts"])
    policy = attempt["metadata"]["cfour_evidence_policy"]
    assert policy["omitted_files"] == [
        {
            "path": "GENBAS",
            "sha256": hashlib.sha256(marker).hexdigest(),
            "size_bytes": len(marker),
            "classification": "licensed-basis",
        }
    ]
    assert any(a["role"] == "cfour-evidence-policy" for a in attempt["artifacts"])
    assert not list((store.run_dir / "snapshots").rglob("GENBAS"))

    from topos.cfour_artifacts import validate_scientific_export_membership

    expected_basis = (
        {"path": "/controlled/GENBAS", "sha256": hashlib.sha256(marker).hexdigest()}
        if state == "observed-canonical"
        else {}
    )
    assert policy["controlled_basis_library"] == expected_basis
    assert validate_scientific_export_membership(retained, store.verify())["cfour_attempts"] == 1
