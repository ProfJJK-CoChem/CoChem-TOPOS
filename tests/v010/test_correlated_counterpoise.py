"""Ghost-state/basis authority contracts; inert receipts are never engine output."""
from copy import deepcopy
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from topos.base_integration import BaseIntegrationError, BaseRuntime
from topos.correlated import CorrelatedMethod
from topos.correlated_counterpoise import (
    R2_ENERGY_RESOLUTION,
    CorrelatedCounterpoiseProtocol,
    CorrelatedGhostLeg,
    _verify_exports,
    correlated_counterpoise_plan,
    correlated_ghost_input,
    run_correlated_ghost,
    run_r2_counterpoise,
)
from topos.models import FragmentState, Molecule, ResourceLimits
from topos.storage import IntegrityError, file_digest


def protocol(**updates):
    native = dict(method="DLPNO-CCSD(T1)", orbital_basis="cc-pVDZ-F12", frozen_core=True,
                  auxiliary_c="cc-pVTZ/C", pno_profile="TightPNO", tcutpno=1e-7)
    native.update(updates)
    return CorrelatedCounterpoiseProtocol(native=CorrelatedMethod(**native), source_resolution=R2_ENERGY_RESOLUTION)


def closed_ionic_pair():
    # Atom/state bookkeeping fixture, not a claim that this geometry is bound.
    return Molecule(symbols=["He", "H"], coordinates=[[0, 0, 0], [0, 0, 3]], atom_ids=["helium", "hydride"],
        charge=-1, fragments=[[0], [1]], fragment_states=[FragmentState(atom_indices=[0], charge=0, multiplicity=1),
                                                        FragmentState(atom_indices=[1], charge=-1, multiplicity=1)])


def export_contract_fixture(tmp_path):
    """Inert export receipt parser fixtures, not authenticated or scientific runs."""
    exporter = tmp_path / "orca_exportbasis"
    exporter.write_text("INERT RECEIPT HASH FIXTURE; NEVER EXECUTED\n")
    receipts = {}
    for kind, name in protocol().basis_names().items():
        path = tmp_path / f"{kind}.bas"
        path.write_text("INERT BASIS CONTRACT FIXTURE; NEVER USED FOR CHEMISTRY\n")
        stdout, stderr = tmp_path / f"{kind}.stdout", tmp_path / f"{kind}.stderr"
        stdout.write_text("receipt parser fixture only\n")
        stderr.write_text("")
        receipts[kind] = dict(schema_version="topos-orca-basis-export/0.1.0",
            authority_kind="verified-ORCA-distribution-utility", basis=name, elements=["H", "He"], format="GAMESS-US",
            command=[str(exporter), "-b", name, "-a", "H", "He", "-f", "GAMESS-US", "-o", path.name],
            output_path=str(path), output_sha256=file_digest(path), exporter_sha256=file_digest(exporter),
            orca_sha256="a"*64, orca_version="6.1.1", distribution_manifest_sha256="b"*64, archive_sha256="c"*64,
            process=dict(status="completed", stdout_path=str(stdout), stderr_path=str(stderr)), status="completed",
            evidence=[dict(path=str(p), sha256=file_digest(p), bytes=p.stat().st_size) for p in (stdout, stderr)])
    return receipts


def leg(receipts):
    return CorrelatedGhostLeg(**protocol().native.model_dump(), basis_centers=closed_ionic_pair(),
                               physical_atom_indices=[1], basis_exports=receipts)


def test_three_physical_states_use_one_unchanged_full_basis_geometry():
    jobs = correlated_counterpoise_plan(closed_ionic_pair(), protocol())
    assert len(jobs) == 3
    assert [job[1].charge for job in jobs] == [-1, 0, -1]
    assert [job[2] for job in jobs] == [[0, 1], [0], [1]]
    assert jobs[2][1].symbols == ["H"] and jobs[2][1].coordinates == [[0, 0, 3]]


def test_ghost_deck_uses_physical_charge_and_all_exported_orbital_and_fitting_centers(tmp_path):
    spec = leg(export_contract_fixture(tmp_path))
    physical = correlated_counterpoise_plan(closed_ionic_pair(), protocol())[2][1]
    deck = correlated_ghost_input(physical, spec, ResourceLimits())
    assert "* xyz -1 1\nHe: 0 0 0\nH 0 0 3\n*" in deck
    assert 'GTOName "orbital.bas"' in deck and 'GTOAuxCName "correlation.bas"' in deck
    assert "DLPNO-CCSD(T1)" in deck and "TightPNO" in deck and "TCutPNO 1e-07" in deck
    assert "cc-pVDZ-F12" not in deck and "cc-pVTZ/C" not in deck
    assert "CABS" not in deck and "MORead" not in deck and " Opt" not in deck


@pytest.mark.parametrize("updates", [dict(method="CCSD(T)-F12D/RI", cabs="cc-pVDZ-F12-CABS", pno_profile=None, tcutpno=None),
    dict(orbital_basis="cc-pVTZ"), dict(frozen_core=False), dict(operation="gradient"),
    dict(local_energy_decomposition=True), dict(pno_profile=None), dict(tcutpno=None)])
def test_r2_energy_cannot_be_relabelled_as_f12_or_different_method(updates):
    with pytest.raises(ValueError):
        protocol(**updates)


@pytest.mark.parametrize("indices", [[True], [], [1, 1], [2], [-1]])
def test_physical_atom_inventory_requires_exact_indices(indices):
    with pytest.raises(ValueError):
        CorrelatedGhostLeg(**protocol().native.model_dump(), basis_centers=closed_ionic_pair(),
                           physical_atom_indices=indices, basis_exports={})


def test_ghost_state_cannot_replace_the_fragment_state(tmp_path):
    spec = leg(export_contract_fixture(tmp_path))
    wrong = Molecule(symbols=["H"], coordinates=[[0, 0, 3]], atom_ids=["hydride"], charge=1)
    with pytest.raises(ValueError, match="charge/spin/fragment identity"):
        correlated_ghost_input(wrong, spec, ResourceLimits())


def test_open_shell_fragments_are_not_silently_promoted_to_rhf():
    hydrogen = Molecule(symbols=["H", "H"], coordinates=[[0, 0, 0], [0, 0, 3]], fragments=[[0], [1]],
        fragment_states=[FragmentState(atom_indices=[i], charge=0, multiplicity=2) for i in range(2)])
    with pytest.raises(ValueError, match="closed-shell"):
        correlated_counterpoise_plan(hydrogen, protocol())


def test_native_exports_require_exact_basis_names_distributions_and_bytes(tmp_path):
    receipts = export_contract_fixture(tmp_path)
    _verify_exports(leg(receipts))  # Receipt grammar only; no engine result is supplied.
    altered = deepcopy(receipts)
    altered["correlation"]["archive_sha256"] = "d"*64
    with pytest.raises(IntegrityError, match="same authorized ORCA distribution"):
        _verify_exports(leg(altered))
    altered = deepcopy(receipts)
    altered["correlation"]["basis"] = "def2/J"
    with pytest.raises(IntegrityError, match="requested basis"):
        _verify_exports(leg(altered))
    Path(receipts["orbital"]["output_path"]).write_text("TAMPERED\n")
    with pytest.raises(IntegrityError, match="retained receipt"):
        _verify_exports(leg(receipts))


def test_missing_orca_cannot_produce_any_correlated_cp_energy(tmp_path):
    spec = leg(export_contract_fixture(tmp_path))
    physical = correlated_counterpoise_plan(closed_ionic_pair(), protocol())[2][1]
    result = run_correlated_ghost(physical, spec, ResourceLimits(), tmp_path / "job", executable=tmp_path / "missing",
        process_runner=lambda *a, **kw: pytest.fail("No native executable exists"))
    assert result.status == "unavailable" and result.energy_hartree is None
    assert result.metadata["execution_kind"] == "not-executed" and result.molecule is None


@pytest.mark.parametrize("cancelled", [True, False])
def test_prelaunch_cancellation_or_deadline_produces_no_cp_sum(cancelled):
    event = Event()
    if cancelled:
        event.set()
    record = SimpleNamespace(request=SimpleNamespace(per_geometry_budget_seconds=None, resources=ResourceLimits()),
                             metadata={}, status="running")
    store = SimpleNamespace(commit=lambda r: None)
    runtime = SimpleNamespace(export_orca_basis=lambda *a, **kw: pytest.fail("Stopped request cannot export or calculate"))
    result = run_r2_counterpoise(SimpleNamespace(base_runtime=runtime), record, store, closed_ionic_pair(), protocol(), 0, event)
    assert result is None and record.status == ("cancelled" if cancelled else "timed-out")


@pytest.mark.parametrize("basis", ["cc-pVDZ-F12", "cc-pVTZ/C", "cc-pVTZ/JK"])
def test_named_correlated_basis_export_still_requires_actual_distribution_authority(tmp_path, basis):
    runtime = object.__new__(BaseRuntime)
    runtime.validate_resources = lambda resources: None

    def no_authority():
        raise BaseIntegrationError("actual distribution authority required")

    runtime._orca_distribution_utility = no_authority
    with pytest.raises(BaseIntegrationError, match="actual distribution authority required"):
        runtime.run_orca_utility(["-b", basis, "-a", "He", "-f", "GAMESS-US", "-o", "basis.bas"],
                                 tmp_path / "export", ResourceLimits())
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("basis", ["cc-pVTZ/C\n!HF", "../cc-pVDZ-F12", "user.bas", "cc-pVTZ;uname"])
def test_correlated_export_extension_does_not_accept_freeform_basis_or_shell_text(tmp_path, basis):
    runtime = object.__new__(BaseRuntime)
    runtime.validate_resources = lambda resources: None
    runtime._orca_distribution_utility = lambda: pytest.fail("Invalid text must not reach native authority")
    with pytest.raises(BaseIntegrationError, match="fixed basis identity"):
        runtime.run_orca_utility(["-b", basis, "-a", "He", "-f", "GAMESS-US", "-o", "basis.bas"],
                                 tmp_path / "export", ResourceLimits())
