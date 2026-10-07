"""Unit-labelled dipole parsing, plus an authentic xTB execution check.

ORCA text below is explicitly an analytical parser fixture, not engine evidence.
"""
import hashlib
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from topos.engines import (
    EngineParseError,
    _method_problem,
    _orca_input,
    parse_cartesian_dipole,
    run_engine,
)
from topos.models import MethodSpec, Molecule, ResourceLimits
from topos.science import geometry_digest
from topos.symmetry import principal_axis_dipole

XTB_BLOCK = """molecular dipole:
                 x           y           z       tot (Debye)
 q only:        0.372       0.480      -0.000
   full:        0.534       0.690       0.000       2.217
molecular quadrupole (traceless):
"""
ORCA_FIXTURE = """DIPOLE MOMENT
-------------------------
                                X             Y             Z
Electronic contribution:      1.000000     -2.000000       2.000000
Nuclear contribution:         0.000000      0.000000       0.000000
Total Dipole Moment    :       1.000000     -2.000000       2.000000
Magnitude (a.u.)       :       3.000000
Magnitude (Debye)      :       7.625239
"""


def test_xtb_camm_components_are_atomic_units_but_norm_is_debye():
    result = parse_cartesian_dipole(XTB_BLOCK, "xtb")
    assert result["cartesian_atomic_units"] == [.534, .690, 0]
    assert result["cartesian_debye"] == pytest.approx([1.357292616, 1.753805065, 0])
    assert result["printed_magnitude_debye"] == 2.217
    assert "CAMM" in result["definition"]
    assert result["printed_component_rounding_bound_debye"] == pytest.approx(.001270873)


def test_orca_signed_atomic_components_and_explicit_magnitude_crosscheck():
    result = parse_cartesian_dipole(ORCA_FIXTURE, "orca")
    assert result["cartesian_atomic_units"] == [1, -2, 2]
    assert result["cartesian_debye"] == pytest.approx([2.541746472, -5.083492943, 5.083492943])
    assert result["cartesian_debye"][1] < 0


@pytest.mark.parametrize("engine", ["xtb", "orca"])
def test_absent_dipole_is_not_a_zero_vector(engine):
    assert parse_cartesian_dipole("energy only", engine) is None


def test_physical_zero_vector_survives_parser():
    text = XTB_BLOCK.replace("0.534       0.690       0.000       2.217", "0.000       0.000       0.000       0.000")
    assert parse_cartesian_dipole(text, "xtb")["cartesian_debye"] == [0, 0, 0]


@pytest.mark.parametrize("text, engine", [
    (XTB_BLOCK.replace("2.217", "9.999"), "xtb"),
    (XTB_BLOCK.replace("tot (Debye)", "tot unknown"), "xtb"),
    (XTB_BLOCK.replace("0.534", "NaN"), "xtb"),
    (XTB_BLOCK + "molecular dipole:\n incomplete", "xtb"),
    (ORCA_FIXTURE.replace("7.625239", "2.999999"), "orca"),
    (ORCA_FIXTURE.replace("Magnitude (a.u.)", "Magnitude (unknown)"), "orca"),
    (ORCA_FIXTURE + "DIPOLE MOMENT\n incomplete", "orca"),
])
def test_missing_truncated_or_inconsistent_dipoles_are_not_accepted(text, engine):
    with pytest.raises(EngineParseError):
        parse_cartesian_dipole(text, engine)


@pytest.mark.parametrize("method", ["wB97X-V", "wB97M-V"])
@pytest.mark.parametrize("auxiliary", [None, "def2/J"])
def test_hybrid_matrix_recipe_renders_its_actual_rijcosx_auxiliary_basis(method, auxiliary):
    molecule = Molecule(symbols=["He"], coordinates=[[0, 0, 0]])
    spec = MethodSpec(engine="orca", method=method, basis="def2-TZVPP", auxiliary_basis=auxiliary,
                      profile_id="orca-mapping-v4.1")
    assert _method_problem(spec, ResourceLimits(), "optimize") is None
    text = _orca_input(molecule, spec, ResourceLimits(), "optimize")
    assert f"! {method} TightSCF DEFGRID3 def2-TZVPP RIJCOSX def2/J Opt Engrad" in text


@pytest.mark.parametrize("method, basis, auxiliary", [("HF-3c", None, "def2/J"),
                                                       ("r2SCAN-3c", None, "def2/J"),
                                                       ("HF", "def2-SVP", "def2/J"),
                                                       ("wB97X-V", "def2-TZVPP", "def2/JK")])
def test_auxiliary_override_does_not_leak_into_incompatible_methods(method, basis, auxiliary):
    spec = MethodSpec(engine="orca", method=method, basis=basis, auxiliary_basis=auxiliary,
                      profile_id="orca-mapping-v4.1")
    assert "auxiliary" in _method_problem(spec, ResourceLimits(), "optimize")


@pytest.mark.integration
def test_genuine_xtb_dipole_is_bound_to_geometry_and_raw_artifact(tmp_path):
    binary = shutil.which(os.environ.get("TOPOS_XTB_EXECUTABLE", "xtb"))
    if binary is None:
        pytest.skip("authentic xTB is required; no synthetic engine substitute")
    molecule = Molecule(symbols=["O", "H", "H"], coordinates=[[0, 0, 0], [.9584, 0, 0], [-.239, .927, 0]])
    result = run_engine(molecule, MethodSpec(engine="xtb", method="GFN2-xTB", profile_id="xtb-vtight-v1"),
                        ResourceLimits(budget_seconds=60), tmp_path / "actual-dipole", executable=binary)
    assert result.status == "completed", result.diagnostics
    vector = result.metadata["dipole_cartesian_debye"]
    provenance = result.metadata["dipole_provenance"]
    assert provenance["geometry_digest"] == geometry_digest(result.molecule)
    assert provenance["raw_output_sha256"] == hashlib.sha256((tmp_path / "actual-dipole" / "engine.stdout").read_bytes()).hexdigest()
    assert result.metadata["execution_kind"] == "real"
    annotation = principal_axis_dipole(result.molecule, vector, dipole_method="GFN2-xTB CAMM")
    assert annotation["status"] == "resolved"
    assert np.linalg.norm(annotation["signed_abc_debye"]) == pytest.approx(np.linalg.norm(vector))
    assert "raw-output" in {artifact.role for artifact in result.artifacts}
    assert Path(provenance["raw_output"]).name == "engine.stdout"
