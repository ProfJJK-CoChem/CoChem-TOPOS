"""Manual-example parser and analytical formulas; no licensed run is simulated."""
import math
from types import SimpleNamespace

import pytest

from topos.correlated import CorrelatedMethod
from topos.engines import EngineParseError, EngineResult
from topos.models import Artifact, Molecule, ResourceLimits
from topos.orca_f12_composite import (
    SOURCE_RESOLUTION,
    OrcaF12CompositeProtocol,
    _native_partition,
    combine_orca_f12_components,
    execute_orca_f12_composite,
    parse_f12_mp2_partition,
)
from topos.storage import IntegrityError, file_digest

# Transcribed from the official ORCA 6.1 manual, MDCI/F12-MP2 subsection.
# This is a published example, not output from an engine executed by this test.
MANUAL_PARTITION = """-----------------
RI-MP2-F12 ENERGY
-----------------
EMP2 correlation Energy            :      -0.241038994909
F12 correction                     :      -0.054735459470
MP2 basis set limit estimate       :      -0.295774454379
Hartree-Fock energy                :     -76.057963800414
(2)_S CABS correction to EHF       :      -0.003475342535
HF basis set limit estimate        :     -76.061439142949
MP2 total energy before F12        :     -76.299002795323
Total F12 correction               :      -0.058210802005
Final basis set limit MP2 estimate :     -76.357213597328
"""


def specification(**updates):
    base = CorrelatedMethod(method="CCSD(T)-F12D/RI", orbital_basis="jun-cc-pVTZ", frozen_core=True,
                            cabs="cc-pVTZ-F12-CABS", auxiliary_c="cc-pVQZ/C")
    mp2 = CorrelatedMethod(method="F12-RI-MP2", orbital_basis="jun-cc-pVTZ", frozen_core=True,
                           cabs="cc-pVTZ-F12-CABS", auxiliary_c="cc-pVQZ/C")
    cv = CorrelatedMethod(method="MP2", orbital_basis="cc-pwCVTZ", frozen_core=True)
    data = dict(base=base, mp2_low=mp2,
                mp2_high=mp2.model_copy(update={"orbital_basis": "jun-cc-pVQZ", "cabs": "cc-pVQZ-F12-CABS"}),
                cv_ae=cv.model_copy(update={"frozen_core": False}), cv_fc=cv,
                hf_exponential_alpha=1.7, correlation_inverse_power=3.,
                extrapolation_quantity="hf-plus-cabs-exponential-and-f12-correlation-power",
                convention="orca-f12d-ri-mp2-cbs-cv-v1")
    data.update(updates)
    return OrcaF12CompositeProtocol(**data)


def mathematical_components():
    """Analytical convergence model, explicitly not engine output."""
    partitions = {}
    for role, x in (("mp2_low", 3), ("mp2_high", 4)):
        hf_cabs, correlation = -100 + .3*math.exp(-1.7*x), -.4 + .2/x**3
        partitions[role] = dict(hf_plus_cabs_hartree=hf_cabs, f12_correlation_hartree=correlation,
                                total_hartree=hf_cabs+correlation)
    return dict(base=-100.5, mp2_low=partitions["mp2_low"]["total_hartree"],
                mp2_high=partitions["mp2_high"]["total_hartree"], cv_ae=-100.45, cv_fc=-100.44), partitions


def test_split_extrapolation_recovers_its_declared_asymptotes_and_cv_sign():
    energies, partitions = mathematical_components()
    result = combine_orca_f12_components(energies, partitions, specification())
    assert result["hf_plus_cabs_cbs_hartree"] == pytest.approx(-100, abs=1e-12)
    assert result["f12_correlation_cbs_hartree"] == pytest.approx(-.4, abs=1e-12)
    assert result["electronic_energy_hartree"] == pytest.approx(-100.5 + (-100.4-energies["mp2_low"]) - .01, abs=1e-12)
    assert result["core_valence_increment_hartree"] == pytest.approx(-.01)
    assert result["accuracy_claim"] is None and result["published_junchs_f12b_recipe"] is False


def test_manual_native_partition_keeps_cabs_singles_out_of_correlation():
    parsed = parse_f12_mp2_partition(MANUAL_PARTITION)
    assert parsed["f12_correlation_hartree"] == -.295774454379
    assert parsed["hf_plus_cabs_hartree"] == -76.061439142949
    assert parsed["total_hartree"] - parsed["hf_hartree"] != pytest.approx(parsed["f12_correlation_hartree"])
    assert parse_f12_mp2_partition(MANUAL_PARTITION.replace("RI-MP2-F12", "MP2-F12")) == parsed


@pytest.mark.parametrize("text", ["", MANUAL_PARTITION*2,
    MANUAL_PARTITION.replace("(2)_S CABS correction to EHF", "not a physical partition"),
    MANUAL_PARTITION.replace("-0.003475342535", "-0.003000000000"),
    MANUAL_PARTITION.replace("-76.357213597328", "-76.300000000000"),
    MANUAL_PARTITION + "Hartree-Fock energy : -76.057963800414\n",
    MANUAL_PARTITION.replace("-76.357213597328", "-7.6357213597328D999")])
def test_incomplete_duplicate_or_inconsistent_partition_is_rejected(text):
    with pytest.raises(EngineParseError):
        parse_f12_mp2_partition(text)


@pytest.mark.parametrize("role,updates", [
    ("base", dict(method="CCSD(T)-F12b")), ("base", dict(orbital_basis="cc-pVTZ-F12")),
    ("base", dict(frozen_core=False)), ("mp2_high", dict(method="F12-MP2", auxiliary_c=None)),
    ("mp2_high", dict(orbital_basis="cc-pVQZ")), ("mp2_low", dict(frozen_core=False)),
    ("mp2_low", dict(cabs="cc-pVDZ-F12-CABS")), ("mp2_low", dict(auxiliary_c="cc-pVTZ/C")),
    ("cv_ae", dict(frozen_core=True)), ("cv_ae", dict(orbital_basis="cc-pVTZ")),
    ("cv_ae", dict(scf_convergence="TightSCF")), ("mp2_high", dict(scf_convergence="TightSCF")),
    ("cv_ae", dict(operation="gradient"))])
def test_exact_method_basis_core_and_reference_choices_cannot_drift(role, updates):
    data = specification().model_dump()
    data[role].update(updates)
    with pytest.raises(ValueError):
        OrcaF12CompositeProtocol.model_validate(data)


@pytest.mark.parametrize("updates", [dict(hf_exponential_alpha=0), dict(hf_exponential_alpha=1e-20),
    dict(correlation_inverse_power=1e-20), dict(correlation_inverse_power=float("nan")),
    dict(extrapolation_quantity="total-energy-power"), dict(convention="junChS-F12b-A14")])
def test_exponents_and_scientific_definition_are_not_silently_guessed(updates):
    with pytest.raises(ValueError):
        specification(**updates)


def test_conventional_f12_mp2_is_explicitly_distinct_from_ri_mp2():
    data = specification().model_dump()
    for name in ("mp2_low", "mp2_high"):
        data[name].update(method="F12-MP2", auxiliary_c=None)
    protocol = OrcaF12CompositeProtocol.model_validate(data)
    assert protocol.mp2_low.method == "F12-MP2" and protocol.mp2_low.auxiliary_c is None
    assert protocol.base.method == "CCSD(T)-F12D/RI"


@pytest.mark.parametrize("damage", ["missing-energy", "nonfinite", "missing-partition", "wrong-total", "wrong-sum"])
def test_composite_requires_every_consistent_finite_component(damage):
    energies, partitions = mathematical_components()
    if damage == "missing-energy":
        del energies["cv_ae"]
    elif damage == "nonfinite":
        energies["base"] = float("nan")
    elif damage == "missing-partition":
        del partitions["mp2_high"]
    elif damage == "wrong-total":
        energies["mp2_high"] += .001
    else:
        partitions["mp2_high"]["hf_plus_cabs_hartree"] += .001
    with pytest.raises(ValueError):
        combine_orca_f12_components(energies, partitions, specification())


def test_partition_requires_unchanged_native_artifact_identity(tmp_path):
    raw = tmp_path / "published-manual-example.txt"
    raw.write_text(MANUAL_PARTITION)
    # Parser-only result; never submitted to the calculation ledger as real evidence.
    result = EngineResult(status="failed", engine="orca", method="F12-RI-MP2", operation="energy",
        energy_hartree=-76.357213597328, diagnostics={"process": {"stdout_path": str(raw)}},
        artifacts=[Artifact(path=str(raw), sha256=file_digest(raw), size_bytes=raw.stat().st_size)])
    assert _native_partition(result)["cabs_singles_hartree"] == -.003475342535
    result.energy_hartree += .001
    with pytest.raises(IntegrityError, match="final energy"):
        _native_partition(result)
    result.energy_hartree -= .001
    raw.write_text(MANUAL_PARTITION.replace("-76.357", "-75.357"))
    with pytest.raises(IntegrityError, match="immutable component"):
        _native_partition(result)


def test_missing_fragment_partition_rejected_before_any_executor_call():
    request = SimpleNamespace(matrix_row_id="T5-3h", molecule=Molecule(symbols=["He"], coordinates=[[0, 0, 0]]),
                              resources=ResourceLimits())
    record = SimpleNamespace(request=request)
    inputs = SimpleNamespace(source_resolution=SOURCE_RESOLUTION, orca_f12_composite=specification())
    with pytest.raises(ValueError, match="complete explicit partition"):
        execute_orca_f12_composite(None, record, None, inputs, 0, None)
