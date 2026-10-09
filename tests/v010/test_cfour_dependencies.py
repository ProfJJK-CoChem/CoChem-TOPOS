"""Real parser availability and negative prelaunch checks; no native calculation."""
from __future__ import annotations

import importlib.util
import sys
import tomllib
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest
from packaging.requirements import Requirement

from topos import cfour_dependencies as dependencies
from topos.cfour_corrections import ScalarRelativisticProtocol, run_scalar_relativistic
from topos.cfour_counterpoise import (
    CfourCounterpoiseLeg,
    parse_cfour_counterpoise_output,
    run_cfour_counterpoise_leg,
)
from topos.cfour_dboc import MASS_CONVENTION, DefaultMassDBOCProtocol, run_default_mass_dboc
from topos.engines import EngineParseError
from topos.external_engines import ExternalProtocol, parse_cfour_output, run_external
from topos.models import Molecule, ResourceLimits

ROOT = Path(__file__).resolve().parents[2]


def test_actual_installed_pinned_parsers_are_importable_without_native_execution():
    from qcengine.programs.cfour.harvester import harvest_GRD, harvest_outfile_pass

    assert dependencies.require_cfour_parsers() == (harvest_GRD, harvest_outfile_pass)


@pytest.mark.parametrize("extra", ["", "ui", "dev"])
def test_standard_package_metadata_requires_pinned_parsers_for_every_installation(extra):
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    requirements = [Requirement(item) for item in metadata["dependencies"]]
    selected = {r.name: str(r.specifier) for r in requirements if not r.marker or r.marker.evaluate({"extra": extra})}
    assert selected["qcengine"] == "==0.51.0"
    assert selected["qcelemental"] == "==0.51.2"
    assert set(metadata["optional-dependencies"]["external"]) == {"qcengine==0.51.0", "qcelemental==0.51.2"}
    assert selected["CoChem-BASE"] == "<2,>=1.0.1"
    assert "CoChem-TORQ" not in selected
    assert metadata["optional-dependencies"]["standalone-ecosystem"] == ["CoChem-TORQ==0.1.0"]


def test_actual_source_setup_plan_needs_no_optional_external_selection(tmp_path):
    path = ROOT / "scripts/setup_ecosystem.py"
    spec = importlib.util.spec_from_file_location("cfour_dependency_setup_plan", path)
    setup = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = setup
    spec.loader.exec_module(setup)
    layout = setup.SetupLayout(tmp_path / "base", ROOT, tmp_path / "torq", tmp_path / "artifacts")
    commands = setup.setup_commands(layout)
    assert commands["install_modules"] == [str(layout.python), "-m", "pip", "install", "-e", str(ROOT) + "[dev,ui]",
                                           "-e", str(layout.torq_root)]
    assert "--all" in commands["mandatory_setup"]
    assert not (tmp_path / "artifacts").exists()  # Concrete argv plan; nothing installed.


def inputs(kind):
    molecule = Molecule(symbols=["H", "H"], coordinates=[[0, 0, 0], [0, 0, .74]], atom_ids=["h1", "h2"])
    common = {"orbital_basis": "PVTZ", "genbas_path": "/unexecuted/cfour/basis/GENBAS", "genbas_sha256": "a" * 64}
    if kind == "external":
        return run_external, molecule, ExternalProtocol(engine="cfour", engine_version="2.1", method="CCSD(T)",
                                                       operation="energy", frozen_core=False, **common)
    if kind == "counterpoise":
        centers = [{"symbol": "H", "atom_id": atom, "coordinates": xyz, "physical": True}
                   for atom, xyz in zip(molecule.atom_ids, molecule.coordinates, strict=True)]
        return run_cfour_counterpoise_leg, molecule, CfourCounterpoiseLeg(engine="cfour", engine_version="2.1", method="CCSD(T)",
            operation="energy", frozen_core=False, dropped_core_orbitals=0, basis_centers=centers, **common)
    if kind == "scalar":
        return run_scalar_relativistic, molecule, ScalarRelativisticProtocol(relativistic="X2C1E", **common)
    return run_default_mass_dboc, molecule, DefaultMassDBOCProtocol(contraction="GENERAL", mass_convention=MASS_CONVENTION, **common)


def inject_dependency_failure(monkeypatch, failure):
    actual_version = dependencies.version
    actual_import = dependencies.import_module
    if failure.startswith("missing-"):
        missing = failure.removeprefix("missing-")
        def version(name):
            if name == missing:
                raise PackageNotFoundError(name)
            return actual_version(name)
        monkeypatch.setattr(dependencies, "version", version)
    elif failure == "wrong-version":
        monkeypatch.setattr(dependencies, "version", lambda name: "0.50.0" if name == "qcengine" else actual_version(name))
    else:
        def broken_import(name):
            if name == "qcengine.programs.cfour.harvester":
                raise ImportError("Explicit negative parser dependency fixture")
            return actual_import(name)
        monkeypatch.setattr(dependencies, "import_module", broken_import)


@pytest.mark.parametrize("kind", ["external", "counterpoise", "scalar", "dboc"])
@pytest.mark.parametrize("failure", ["missing-qcengine", "missing-qcelemental", "wrong-version", "broken-import"])
def test_missing_or_broken_parser_stops_every_runner_before_resolution_or_native_launch(tmp_path, monkeypatch, kind, failure):
    function, molecule, protocol = inputs(kind)
    inject_dependency_failure(monkeypatch, failure)
    module = sys.modules[function.__module__]
    def forbidden(*args, **kwargs):
        pytest.fail("No native executable resolution or process launch is permitted before parser preflight")
    monkeypatch.setattr(module.shutil, "which", forbidden)
    workdir = tmp_path / "unexecuted-attempt"
    result = function(molecule, protocol, ResourceLimits(), workdir, executable="/unexecuted/xcfour", process_runner=forbidden)
    assert result.status == "unsupported"
    assert result.metadata["execution_kind"] == "not-executed"
    assert "CFOUR parser dependency" in result.diagnostics["reason"]
    assert result.command == [] and result.energy_hartree is None
    assert not result.artifacts and not workdir.exists()


@pytest.mark.parametrize("kind", ["external", "counterpoise"])
def test_direct_parser_requires_dependencies_before_interpreting_any_text(monkeypatch, kind):
    _, molecule, protocol = inputs(kind)
    inject_dependency_failure(monkeypatch, "missing-qcengine")
    parser = parse_cfour_output if kind == "external" else parse_cfour_counterpoise_output
    with pytest.raises(EngineParseError, match="dependency qcengine==0.51.0 is missing"):
        parser("Not native output; preflight must reject before interpreting text", molecule, protocol)


@pytest.mark.parametrize("problem", ["imported-version", "noncallable-harvester", "missing-harvester"])
def test_distribution_metadata_cannot_hide_broken_imported_parser(monkeypatch, problem):
    actual_import = dependencies.import_module
    def changed(name):
        if problem == "imported-version" and name == "qcelemental":
            return SimpleNamespace(__version__="0.50.0")
        if problem != "imported-version" and name == "qcengine.programs.cfour.harvester":
            return SimpleNamespace(harvest_GRD=None, harvest_outfile_pass=None) if problem == "noncallable-harvester" else SimpleNamespace()
        return actual_import(name)
    monkeypatch.setattr(dependencies, "import_module", changed)
    with pytest.raises(EngineParseError):
        dependencies.require_cfour_parsers()


def test_successful_preflight_is_not_cached_across_dependency_failure(monkeypatch):
    dependencies.require_cfour_parsers()
    inject_dependency_failure(monkeypatch, "missing-qcelemental")
    with pytest.raises(EngineParseError, match="qcelemental==0.51.2 is missing"):
        dependencies.require_cfour_parsers()


def test_each_uncached_native_evaluation_rechecks_parser_before_staging(tmp_path, monkeypatch):
    from topos import external_engines as adapter
    from topos.storage import file_digest

    # Nonexecuted pathname/hash controls, not a scientific engine or basis.
    binary = tmp_path / "controlled/bin/xcfour"
    binary.parent.mkdir(parents=True)
    binary.write_text("Unexecuted transport marker; this is not an engine\n")
    binary.chmod(0o755)
    basis = tmp_path / "controlled/basis/GENBAS"
    basis.parent.mkdir()
    basis.write_text("H:PVTZ\nUnexecuted transport marker; no basis coefficients\n")
    _, molecule, selected = inputs("external")
    selected = selected.model_copy(update={"genbas_path": str(basis), "genbas_sha256": file_digest(basis)})
    calls = []
    def preflight():
        calls.append("check")
        if len(calls) > 1:
            raise EngineParseError("CFOUR parser dependency changed before evaluation")
        return dependencies.require_cfour_parsers()
    def forbidden(*args, **kwargs):
        pytest.fail("The dependency failed before any native process may launch")
    monkeypatch.setattr(adapter, "require_cfour_parsers", preflight)
    folder = tmp_path / "attempt"
    result = adapter.run_external(molecule, selected, ResourceLimits(), folder, executable=binary, process_runner=forbidden)
    assert len(calls) == 2
    assert result.status == "unsupported" and result.metadata["execution_kind"] == "not-executed"
    assert result.energy_hartree is None and result.command == []
    assert "dependency changed before evaluation" in result.diagnostics["reason"]
    assert not (folder / "evaluation-00000").exists()
