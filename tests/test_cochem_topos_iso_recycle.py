"""
Unit tests for CoChem-TOPOS Isotopologue Hessian Recycling (Stage 4.1: cochem_topos_iso_recycle.py).

Validates First-Order Isotopic Mass Perturbation, Born-Oppenheimer PES invariance,
exact mono-isotopic mass injection via Mendeleev, mass-weighted Hessian diagonalization,
ZPE / vibrational thermochemistry calculations, KIE predictions, and HDF5 SWMR persistence.

Strictly complies with the Tripartite Air-Gap Policy and Zero-Mock Mandate.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import h5py
import numpy as np
import pytest

from escalation.cochem_topos_iso_recycle import (
    HESSIAN_UNIT_FACTORS,
    HessianUnit,
    IsotopeSubstitution,
    IsotopologueDefinition,
    IsotopologueRecycleResult,
    NormalMode,
    ThermochemicalCorrections,
    ToposIsotopologueRecycler,
    VibrationalAnalysis,
    calculate_harmonic_kie,
    get_exact_isotopic_mass,
    get_isotopic_masses,
    mass_weight_hessian,
    project_translations_rotations,
    recycle_hessian_frequencies,
)
from mechanics.cochem_topos_memory import GeometryRecord, ToposHDF5MemoryManager


# ============================================================================
# 1. Tests for Mass Retrieval & Mendeleev Resolution
# ============================================================================


class TestIsotopicMassResolution:
    """Verifies exact mono-isotopic mass querying and error handling."""

    def test_standard_element_monoisotopic_masses(self) -> None:
        """Confirms ground state monoisotopic masses for common organic elements."""
        assert pytest.approx(get_exact_isotopic_mass("H"), rel=1e-6) == 1.007825032
        assert pytest.approx(get_exact_isotopic_mass("C"), rel=1e-6) == 12.000000000
        assert pytest.approx(get_exact_isotopic_mass("N"), rel=1e-6) == 14.003074004
        assert pytest.approx(get_exact_isotopic_mass("O"), rel=1e-6) == 15.994914620
        assert pytest.approx(get_exact_isotopic_mass("S"), rel=1e-6) == 31.972071000

    def test_heavy_isotope_masses(self) -> None:
        """Confirms exact masses for heavy isotopic variants."""
        assert pytest.approx(get_exact_isotopic_mass("D"), rel=1e-6) == 2.014101778
        assert pytest.approx(get_exact_isotopic_mass("H", mass_number=2), rel=1e-6) == 2.014101778
        assert pytest.approx(get_exact_isotopic_mass("T"), rel=1e-6) == 3.016049281
        assert pytest.approx(get_exact_isotopic_mass("C", mass_number=13), rel=1e-6) == 13.003354835
        assert pytest.approx(get_exact_isotopic_mass("13C"), rel=1e-6) == 13.003354835
        assert pytest.approx(get_exact_isotopic_mass("O", mass_number=18), rel=1e-6) == 17.999159613
        assert pytest.approx(get_exact_isotopic_mass("18O"), rel=1e-6) == 17.999159613
        assert pytest.approx(get_exact_isotopic_mass("N", mass_number=15), rel=1e-6) == 15.000108899
        assert pytest.approx(get_exact_isotopic_mass("Cl", mass_number=37), rel=1e-6) == 36.96590260

    def test_get_isotopic_masses_sequence(self) -> None:
        """Tests mass array generation for molecular symbol lists."""
        symbols = ["O", "H", "H"]
        masses = get_isotopic_masses(symbols)
        assert len(masses) == 3
        assert pytest.approx(masses[0], rel=1e-5) == 15.994915
        assert pytest.approx(masses[1], rel=1e-5) == 1.007825
        assert pytest.approx(masses[2], rel=1e-5) == 1.007825

    def test_get_isotopic_masses_with_substitutions(self) -> None:
        """Tests mass array generation with explicit index substitutions."""
        symbols = ["O", "H", "H"]
        substitutions = {1: "D", 2: 2}
        masses = get_isotopic_masses(symbols, substitutions=substitutions)
        assert pytest.approx(masses[0], rel=1e-5) == 15.994915
        assert pytest.approx(masses[1], rel=1e-5) == 2.014102
        assert pytest.approx(masses[2], rel=1e-5) == 2.014102

    def test_numpy_integer_substitutions(self) -> None:
        """Confirms NumPy integer mass numbers resolve to exact monoisotopic masses."""
        symbols = ["H"]
        masses_py_int = get_isotopic_masses(symbols, substitutions={0: 2})
        masses_np_int = get_isotopic_masses(symbols, substitutions={0: np.int64(2)})
        assert pytest.approx(masses_py_int[0], rel=1e-6) == 2.014101778
        assert pytest.approx(masses_np_int[0], rel=1e-6) == 2.014101778
        assert pytest.approx(masses_py_int[0]) == masses_np_int[0]

    def test_invalid_symbol_or_isotope_raises(self) -> None:
        """Confirms invalid chemical symbols or unphysical mass numbers raise ValueError."""
        with pytest.raises(ValueError, match="not recognized"):
            get_exact_isotopic_mass("Unobtanium")

        with pytest.raises(ValueError, match="No isotope with mass number"):
            get_exact_isotopic_mass("H", mass_number=999)


# ============================================================================
# 2. Tests for Mass-Weighted Hessian & Eigendecomposition
# ============================================================================


class TestMassWeightedHessianAndFrequencies:
    """Verifies mass weighting, diagonalization, and frequency extraction."""

    @pytest.fixture
    def harmonic_diatomic_co(self) -> tuple[np.ndarray, np.ndarray, list[str]]:
        """Fixture providing an analytical 1D-like harmonic oscillator for CO."""
        coords = np.array([
            [0.0, 0.0, 0.0],       # C (index 0)
            [0.0, 0.0, 1.1283],    # O (index 1)
        ], dtype=np.float64)
        symbols = ["C", "O"]

        k = 11.58
        H = np.zeros((6, 6), dtype=np.float64)
        H[2, 2] = k
        H[5, 5] = k
        H[2, 5] = -k
        H[5, 2] = -k
        return H, coords, symbols

    def test_mass_weighted_hessian_scaling(self, harmonic_diatomic_co) -> None:
        """Confirms mass-weighting scaling formula."""
        H, coords, symbols = harmonic_diatomic_co
        m_C = get_exact_isotopic_mass("C")
        m_O = get_exact_isotopic_mass("O")
        masses = np.array([m_C, m_O])

        F = mass_weight_hessian(H, masses)
        assert F.shape == (6, 6)
        assert pytest.approx(F[2, 2]) == H[2, 2] / m_C
        assert pytest.approx(F[5, 5]) == H[5, 5] / m_O
        assert pytest.approx(F[2, 5]) == H[2, 5] / np.sqrt(m_C * m_O)
        assert pytest.approx(F[5, 2]) == H[5, 2] / np.sqrt(m_C * m_O)
        np.testing.assert_allclose(F, F.T, atol=1e-12)

    def test_diatomic_frequency_and_isotopic_shift(self, harmonic_diatomic_co) -> None:
        """Confirms exact isotopic frequency ratio follows reduced mass ratio."""
        H, coords, symbols = harmonic_diatomic_co
        res_12c16o = recycle_hessian_frequencies(
            hessian=H,
            symbols=symbols,
            coordinates=coords,
            unit=HessianUnit.EV_PER_ANGSTROM2,
        )
        res_13c16o = recycle_hessian_frequencies(
            hessian=H,
            symbols=symbols,
            coordinates=coords,
            substitutions={0: 13},
            unit=HessianUnit.EV_PER_ANGSTROM2,
        )

        m_C12 = get_exact_isotopic_mass("12C")
        m_C13 = get_exact_isotopic_mass("13C")
        m_O16 = get_exact_isotopic_mass("16O")

        mu_12 = (m_C12 * m_O16) / (m_C12 + m_O16)
        mu_13 = (m_C13 * m_O16) / (m_C13 + m_O16)
        theoretical_ratio = np.sqrt(mu_12 / mu_13)

        vib_12 = max(res_12c16o.frequencies_cm1)
        vib_13 = max(res_13c16o.frequencies_cm1)
        actual_ratio = vib_13 / vib_12

        assert pytest.approx(actual_ratio, rel=1e-4) == theoretical_ratio
        assert vib_12 > vib_13

    def test_all_hessian_units_consistency(self) -> None:
        """Confirms identical physical frequency across all supported input Hessian units."""
        # 1D harmonic oscillator with k = 1000 N/m (J/m^2)
        # 1000 N/m = 1000 J/m^2 = 62.4150907446 eV/Angstrom^2
        # 1000 N/m = 0.642283088 Hartree/Bohr^2 (1 Hartree = 4.3597447e-18 J, 1 Bohr = 0.5291772e-10 m)
        k_si = 1000.0  # J/m^2
        k_ev_ang2 = k_si * (1.0e-20 / 1.602176634e-19)
        k_ha_bohr2 = k_si * ((0.529177210903e-10)**2 / 4.3597447222071e-18)
        k_ha_ang2 = k_si * (1.0e-20 / 4.3597447222071e-18)

        symbols = ["C", "O"]
        coords = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.13]])

        def _make_h(k_val: float) -> np.ndarray:
            h = np.zeros((6, 6), dtype=np.float64)
            h[2, 2] = k_val
            h[5, 5] = k_val
            h[2, 5] = -k_val
            h[5, 2] = -k_val
            return h

        res_si = recycle_hessian_frequencies(_make_h(k_si), symbols, coords, unit=HessianUnit.J_PER_M2)
        res_ev = recycle_hessian_frequencies(_make_h(k_ev_ang2), symbols, coords, unit=HessianUnit.EV_PER_ANGSTROM2)
        res_ha_bohr = recycle_hessian_frequencies(_make_h(k_ha_bohr2), symbols, coords, unit=HessianUnit.HARTREE_PER_BOHR2)
        res_ha_ang = recycle_hessian_frequencies(_make_h(k_ha_ang2), symbols, coords, unit=HessianUnit.HARTREE_PER_ANGSTROM2)

        freq_si = max(res_si.frequencies_cm1)
        freq_ev = max(res_ev.frequencies_cm1)
        freq_ha_bohr = max(res_ha_bohr.frequencies_cm1)
        freq_ha_ang = max(res_ha_ang.frequencies_cm1)

        assert pytest.approx(freq_si, rel=1e-4) == 1573.34
        assert pytest.approx(freq_ev, rel=1e-4) == freq_si
        assert pytest.approx(freq_ha_bohr, rel=1e-4) == freq_si
        assert pytest.approx(freq_ha_ang, rel=1e-4) == freq_si

    def test_water_triatomic_isotopologue_series(self) -> None:
        """Tests water vibrational recycling across H2O, HDO, D2O, and H2_18O."""
        symbols = ["O", "H", "H"]
        coords = np.array([
            [0.0000, 0.0000, 0.1173],
            [0.0000, 0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ], dtype=np.float64)

        N = 3
        H = np.zeros((3 * N, 3 * N), dtype=np.float64)
        k_str = 35.0
        k_bend = 5.0

        d1 = coords[1] - coords[0]
        u1 = d1 / np.linalg.norm(d1)
        H_str1 = k_str * np.outer(u1, u1)

        d2 = coords[2] - coords[0]
        u2 = d2 / np.linalg.norm(d2)
        H_str2 = k_str * np.outer(u2, u2)

        H[0:3, 0:3] += H_str1 + H_str2
        H[3:6, 3:6] += H_str1
        H[0:3, 3:6] -= H_str1
        H[3:6, 0:3] -= H_str1

        H[6:9, 6:9] += H_str2
        H[0:3, 6:9] -= H_str2
        H[6:9, 0:3] -= H_str2

        H[3:6, 6:9] += k_bend * np.eye(3)
        H[6:9, 3:6] += k_bend * np.eye(3)
        H[3:6, 3:6] += k_bend * np.eye(3)
        H[6:9, 6:9] += k_bend * np.eye(3)

        res_h2o = recycle_hessian_frequencies(H, symbols, coords, unit=HessianUnit.EV_PER_ANGSTROM2)
        res_hdo = recycle_hessian_frequencies(H, symbols, coords, substitutions={1: "D"}, unit=HessianUnit.EV_PER_ANGSTROM2)
        res_d2o = recycle_hessian_frequencies(H, symbols, coords, substitutions={1: "D", 2: "D"}, unit=HessianUnit.EV_PER_ANGSTROM2)
        res_h2_18o = recycle_hessian_frequencies(H, symbols, coords, substitutions={0: 18}, unit=HessianUnit.EV_PER_ANGSTROM2)

        assert res_h2o.zpe_kcal_mol > res_h2_18o.zpe_kcal_mol
        assert res_h2_18o.zpe_kcal_mol > res_hdo.zpe_kcal_mol
        assert res_hdo.zpe_kcal_mol > res_d2o.zpe_kcal_mol

        h2o_vib_max = max(res_h2o.frequencies_cm1)
        d2o_vib_max = max(res_d2o.frequencies_cm1)
        assert pytest.approx(d2o_vib_max / h2o_vib_max, rel=0.1) == 1.0 / np.sqrt(2.0)


# ============================================================================
# 3. Tests for Thermochemistry, ZPE, and KIE
# ============================================================================


class TestThermochemistryAndKIE:
    """Verifies harmonic partition functions, thermodynamic corrections, and KIE."""

    def test_zpe_unit_conversions(self) -> None:
        """Confirms mathematical consistency of ZPE across Ha, kcal/mol, kJ/mol, and eV."""
        freqs = [3657.05, 1594.75, 3755.93]
        eigenvals = [1.0, 2.0, 3.0]
        vib = VibrationalAnalysis.from_frequencies(frequencies_cm1=freqs, eigenvalues=eigenvals)

        assert pytest.approx(vib.zpe_hartree, rel=1e-4) == 0.0205211
        assert pytest.approx(vib.zpe_kcal_mol, rel=1e-4) == vib.zpe_hartree * 627.509474
        assert pytest.approx(vib.zpe_kj_mol, rel=1e-4) == vib.zpe_hartree * 2625.49964
        assert pytest.approx(vib.zpe_ev, rel=1e-4) == vib.zpe_hartree * 27.211386

    def test_thermochemical_corrections_temperature(self) -> None:
        """Confirms thermal energy and entropy increase monotonically with temperature."""
        freqs = [500.0, 1000.0, 1500.0, 3000.0]
        vib = VibrationalAnalysis.from_frequencies(frequencies_cm1=freqs, eigenvalues=[1, 2, 3, 4])

        thermo_298 = vib.compute_thermochemistry(temperature_k=298.15)
        thermo_500 = vib.compute_thermochemistry(temperature_k=500.0)

        assert thermo_500.thermal_energy_hartree > thermo_298.thermal_energy_hartree
        assert thermo_500.entropy_cal_mol_k > thermo_298.entropy_cal_mol_k
        assert thermo_500.heat_capacity_cal_mol_k > thermo_298.heat_capacity_cal_mol_k

    def test_harmonic_kie_calculation(self) -> None:
        """Confirms semi-classical primary KIE (k_H / k_D > 1.0) due to ZPE difference."""
        freqs_react_H = [3000.0, 1000.0, 500.0]
        freqs_ts_H = [1500.0, 1000.0, 500.0]

        freqs_react_D = [3000.0 / np.sqrt(2.0), 1000.0, 500.0]
        freqs_ts_D = [1500.0 / np.sqrt(2.0), 1000.0, 500.0]

        vib_react_H = VibrationalAnalysis.from_frequencies(freqs_react_H, [1, 1, 1])
        vib_ts_H = VibrationalAnalysis.from_frequencies(freqs_ts_H, [1, 1, 1])
        vib_react_D = VibrationalAnalysis.from_frequencies(freqs_react_D, [1, 1, 1])
        vib_ts_D = VibrationalAnalysis.from_frequencies(freqs_ts_D, [1, 1, 1])

        kie_298 = calculate_harmonic_kie(
            reactant_light=vib_react_H,
            ts_light=vib_ts_H,
            reactant_heavy=vib_react_D,
            ts_heavy=vib_ts_D,
            temperature_k=298.15,
        )

        assert kie_298.kie_ratio > 1.0
        assert kie_298.delta_zpe_diff_kcal_mol > 0.0

    def test_harmonic_kie_with_wigner_tunneling(self) -> None:
        """Confirms Wigner tunneling calculation when transition states have imaginary modes."""
        freqs_react_H = [3000.0, 1000.0, 500.0]
        freqs_ts_H = [-1200.0, 1000.0, 500.0]

        freqs_react_D = [3000.0 / np.sqrt(2.0), 1000.0, 500.0]
        freqs_ts_D = [-1200.0 / np.sqrt(2.0), 1000.0, 500.0]

        vib_react_H = VibrationalAnalysis.from_frequencies(freqs_react_H, [1, 1, 1])
        vib_ts_H = VibrationalAnalysis.from_frequencies(freqs_ts_H, [-1, 1, 1])
        vib_react_D = VibrationalAnalysis.from_frequencies(freqs_react_D, [1, 1, 1])
        vib_ts_D = VibrationalAnalysis.from_frequencies(freqs_ts_D, [-1, 1, 1])

        kie = calculate_harmonic_kie(
            reactant_light=vib_react_H,
            ts_light=vib_ts_H,
            reactant_heavy=vib_react_D,
            ts_heavy=vib_ts_D,
            temperature_k=298.15,
        )

        assert kie.wigner_tunneling_correction_light > kie.wigner_tunneling_correction_heavy
        assert kie.wigner_tunneling_correction_heavy > 1.0
        assert kie.kie_ratio > 1.0


# ============================================================================
# 4. Tests for ToposIsotopologueRecycler & HDF5 SWMR Persistence
# ============================================================================


class TestToposIsotopologueRecyclerHDF5:
    """Verifies database extraction, batch calculation, and SWMR persistence."""

    @pytest.fixture
    def sample_h5_database(self, tmp_path: Path) -> tuple[Path, str]:
        """Creates an authentic HDF5 database with a converged water geometry & Hessian."""
        db_path = tmp_path / "landscape.h5"
        geom_id = "geom_water_cochem_opt"

        symbols = ["O", "H", "H"]
        atomic_numbers = [8, 1, 1]
        coords = [
            [0.0000, 0.0000, 0.1173],
            [0.0000, 0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ]
        hessian = (np.eye(9) * 15.0).tolist()
        energy = -76.4321

        mem = ToposHDF5MemoryManager(db_path=db_path)
        record = GeometryRecord(
            geom_id=geom_id,
            atomic_numbers=atomic_numbers,
            coords=coords,
            energy=energy,
            hessian=hessian,
            metadata={"level_of_theory": "wB97M-V/def2-TZVPP"},
        )
        mem.write_geometry(record)
        return db_path, geom_id

    def test_recycler_extract_and_recycle_from_hdf5(self, sample_h5_database) -> None:
        """Confirms extraction of baseline Hessian from HDF5 and calculation of isotopologues."""
        db_path, geom_id = sample_h5_database
        recycler = ToposIsotopologueRecycler(db_path=db_path)

        definitions = [
            IsotopologueDefinition(isotopologue_id="D2O", substitutions={1: "D", 2: "D"}),
            IsotopologueDefinition(isotopologue_id="H2_18O", substitutions={0: 18}),
            IsotopologueDefinition(isotopologue_id="HDO", substitutions={1: "D"}),
        ]

        report = recycler.recycle_batch(geom_id=geom_id, definitions=definitions, save_to_hdf5=True)

        assert report.total_calculated == 3
        assert len(report.results) == 3

        d2o_res = next(r for r in report.results if r.isotopologue_id == "D2O")
        assert d2o_res.isotopologue_zpe_kcal_mol < d2o_res.baseline_zpe_kcal_mol
        assert d2o_res.delta_zpe_kcal_mol < 0.0

        with h5py.File(db_path, "r") as f:
            assert "isotopologues" in f
            assert geom_id in f["isotopologues"]
            iso_grp = f["isotopologues"][geom_id]
            assert "D2O" in iso_grp
            assert "H2_18O" in iso_grp
            assert "HDO" in iso_grp

            d2o_grp = iso_grp["D2O"]
            assert "frequencies_cm1" in d2o_grp
            assert "baseline_frequencies_cm1" in d2o_grp
            assert "substituted_masses" in d2o_grp
            assert d2o_grp.attrs["zpe_kcal_mol"] == d2o_res.isotopologue_zpe_kcal_mol

    def test_recycler_read_persisted_isotopologue(self, sample_h5_database) -> None:
        """Confirms reading saved isotopologue data from HDF5 preserving distinct baseline and isotopologue freqs."""
        db_path, geom_id = sample_h5_database
        recycler = ToposIsotopologueRecycler(db_path=db_path)

        iso_def = IsotopologueDefinition(isotopologue_id="PerDeuterated", substitutions={"H": "D"})
        res_write = recycler.recycle_single(geom_id=geom_id, definition=iso_def, save_to_hdf5=True)

        res_read = recycler.read_isotopologue_from_hdf5(geom_id=geom_id, isotopologue_id="PerDeuterated")
        assert res_read is not None
        assert res_read.isotopologue_id == "PerDeuterated"
        assert pytest.approx(res_read.isotopologue_zpe_kcal_mol, rel=1e-5) == res_write.isotopologue_zpe_kcal_mol
        assert res_read.isotopologue_frequencies_cm1 == res_write.isotopologue_frequencies_cm1
        assert res_read.baseline_frequencies_cm1 == res_write.baseline_frequencies_cm1
        # For deuterated water, baseline (H2O) frequencies and isotopologue (D2O) frequencies must differ
        assert res_read.baseline_frequencies_cm1 != res_read.isotopologue_frequencies_cm1

    def test_generate_standard_isotopologue_ensemble(self, sample_h5_database) -> None:
        """Verifies automatic generation of standard isotopologue suites."""
        db_path, geom_id = sample_h5_database
        recycler = ToposIsotopologueRecycler(db_path=db_path)

        defs = recycler.generate_standard_isotopologues(geom_id=geom_id)
        assert len(defs) >= 4
        iso_ids = [d.isotopologue_id for d in defs]
        assert any("D2O" in i or "PerD" in i for i in iso_ids)
        assert any("18O" in i for i in iso_ids)


# ============================================================================
# 5. Tests for Edge Cases & Mathematical Robustness
# ============================================================================


class TestRecyclerEdgeCases:
    """Validates edge cases: dimension mismatch, non-symmetric Hessians, imaginary modes."""

    def test_dimension_mismatch_raises(self) -> None:
        """Confirms 3N x 3N dimension mismatch with N atoms raises ValueError."""
        H = np.eye(6)
        symbols = ["O", "H", "H"]
        coords = np.zeros((3, 3))

        with pytest.raises(ValueError, match="Dimension mismatch"):
            recycle_hessian_frequencies(H, symbols, coords)

    def test_imaginary_frequencies_handling(self) -> None:
        """Confirms negative eigenvalues (transition state) are flagged as imaginary."""
        H = np.diag([-5.0, 10.0, 10.0, 10.0, 10.0, 10.0])
        symbols = ["C", "H"]
        coords = np.zeros((2, 3))

        res = recycle_hessian_frequencies(H, symbols, coords, unit=HessianUnit.EV_PER_ANGSTROM2)
        assert res.num_imaginary == 1
        assert res.has_imaginary_modes is True
        assert any(f < 0 for f in res.frequencies_cm1)

    def test_translation_rotation_projection_nonlinear(self) -> None:
        """Confirms TR projector zeros out 6 external degrees of freedom for non-linear molecules."""
        coords = np.array([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ], dtype=np.float64)
        masses = np.array([12.0, 1.0, 1.0])
        A = np.random.RandomState(42).randn(9, 9)
        H = A.T @ A

        P = project_translations_rotations(coords, masses)
        assert P.shape == (9, 9)
        assert pytest.approx(np.trace(P)) == 3.0  # 3N - 6 = 9 - 6 = 3
        np.testing.assert_allclose(P @ P, P, atol=1e-10)

    def test_translation_rotation_projection_linear_diatomic(self) -> None:
        """Confirms TR projector preserves 1 vibrational mode for linear diatomics (3N - 5 = 1)."""
        coords = np.array([
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.1283],
        ], dtype=np.float64)
        masses = np.array([12.0, 16.0])
        symbols = ["C", "O"]

        P = project_translations_rotations(coords, masses)
        assert P.shape == (6, 6)
        assert pytest.approx(np.trace(P)) == 1.0  # 3N - 5 = 6 - 5 = 1
        np.testing.assert_allclose(P @ P, P, atol=1e-10)

        # Confirm stretching vibration is preserved under projection
        k = 11.58
        H = np.zeros((6, 6), dtype=np.float64)
        H[2, 2] = k
        H[5, 5] = k
        H[2, 5] = -k
        H[5, 2] = -k

        res = recycle_hessian_frequencies(H, symbols, coords, project_tr=True, unit=HessianUnit.EV_PER_ANGSTROM2)
        non_zero_freqs = [f for f in res.frequencies_cm1 if abs(f) > 10.0]
        assert len(non_zero_freqs) == 1
        assert pytest.approx(non_zero_freqs[0], rel=1e-4) == 677.7076
