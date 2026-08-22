"""Physical Unit Tests for CoChem-TOPOS Preflight Module (test_cochem_topos_preflight.py).

Enforces Zero-Tolerance Anti-Mocking:
- Real elemental monoisotopic mass resolutions via `mendeleev`.
- Real physical molecules (H2O, CH4, C6H6, OH, CH3, NO, O2, NH4+, OH-, etc.).
- Real Cartesian coordinate matrices and inertia tensor calculations.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from numpy import linalg as la

from frontend.cochem_topos_preflight import (
    PreflightStatus,
    align_to_principal_axes,
    assess_valency_and_radicals,
    build_connectivity_matrix,
    center_coordinates,
    compute_center_of_mass,
    compute_geometric_center,
    compute_mass_weighted_coordinates,
    compute_moment_of_inertia_tensor,
    compute_total_molecular_mass,
    detect_nuclear_clashes,
    find_connected_fragments,
    get_element_info,
    get_monoisotopic_mass,
    get_monoisotopic_masses,
    normalize_element_symbol,
    sanitize_and_validate_seed,
    validate_spin_parity,
)

# ===========================================================================
# 1. Mono-Isotopic Mass Anchoring & Mendeleev Resolution Tests
# ===========================================================================


class TestMonoisotopicMassAnchoring:
    """Test exact IUPAC/NIST monoisotopic mass resolutions with real elements."""

    def test_carbon_12_exact_mass(self) -> None:
        """Carbon-12 must be exactly 12.000000000 Da by IUPAC definition."""
        c_mass = get_monoisotopic_mass("C")
        assert math.isclose(c_mass, 12.0, rel_tol=1e-12, abs_tol=1e-12)

        info_c = get_element_info("C")
        assert info_c.symbol == "C"
        assert info_c.atomic_number == 6
        assert info_c.most_abundant_mass_number == 12
        assert math.isclose(info_c.monoisotopic_mass, 12.0, abs_tol=1e-12)

    def test_common_element_monoisotopic_masses(self) -> None:
        """Verify exact monoisotopic masses for standard organic/inorganic elements."""
        # Hydrogen (1H = ~1.007825 Da)
        h_mass = get_monoisotopic_mass("H")
        assert 1.0078 < h_mass < 1.0079

        # Nitrogen (14N = ~14.003074 Da)
        n_mass = get_monoisotopic_mass("N")
        assert 14.0030 < n_mass < 14.0032

        # Oxygen (16O = ~15.994915 Da)
        o_mass = get_monoisotopic_mass("O")
        assert 15.9948 < o_mass < 15.9950

        # Fluorine (19F = ~18.998403 Da)
        f_mass = get_monoisotopic_mass("F")
        assert 18.9983 < f_mass < 18.9985

        # Chlorine (35Cl = ~34.968853 Da)
        cl_mass = get_monoisotopic_mass("Cl")
        assert 34.968 < cl_mass < 34.970

        # Bromine (79Br = ~78.918338 Da)
        br_mass = get_monoisotopic_mass("Br")
        assert 78.918 < br_mass < 78.920

        # Iodine (127I = ~126.904473 Da)
        i_mass = get_monoisotopic_mass("I")
        assert 126.90 < i_mass < 126.91

    def test_hydrogen_isotopic_aliases(self) -> None:
        """Deuterium (D/2H) and Tritium (T/3H) must resolve exact isotopic masses."""
        d_mass = get_monoisotopic_mass("D")
        h2_mass = get_monoisotopic_mass("2H")
        assert math.isclose(d_mass, h2_mass, rel_tol=1e-6)
        assert 2.014 < d_mass < 2.015

        t_mass = get_monoisotopic_mass("T")
        h3_mass = get_monoisotopic_mass("3H")
        assert math.isclose(t_mass, h3_mass, rel_tol=1e-6)
        assert 3.015 < t_mass < 3.017

    def test_symbol_normalization_and_atomic_numbers(self) -> None:
        """Test symbol normalization (case insensitivity, atomic numbers)."""
        assert normalize_element_symbol("c") == "C"
        assert normalize_element_symbol("FE") == "Fe"
        assert normalize_element_symbol("cl") == "Cl"
        assert normalize_element_symbol(6) == "C"
        assert normalize_element_symbol("6") == "C"
        assert normalize_element_symbol(1) == "H"
        assert normalize_element_symbol(8) == "O"

        with pytest.raises(ValueError, match="Atomic number Z=0 is out of physical range"):
            normalize_element_symbol(0)

        with pytest.raises(ValueError, match="Atomic number Z=150 is out of physical range"):
            normalize_element_symbol(150)

        with pytest.raises(ValueError, match="Empty element symbol"):
            normalize_element_symbol("   ")

    def test_molecular_mass_vector_and_total(self) -> None:
        """Test monoisotopic mass array and total molecular mass computation."""
        # Water H2O
        water_symbols = ["O", "H", "H"]
        masses = get_monoisotopic_masses(water_symbols)
        assert len(masses) == 3
        total_h2o = compute_total_molecular_mass(water_symbols)
        expected_h2o = get_monoisotopic_mass("O") + 2 * get_monoisotopic_mass("H")
        assert math.isclose(total_h2o, expected_h2o, rel_tol=1e-9)
        assert 18.010 < total_h2o < 18.011

        # Chloroform CHCl3
        chcl3_symbols = ["C", "H", "Cl", "Cl", "Cl"]
        total_chcl3 = compute_total_molecular_mass(chcl3_symbols)
        expected_chcl3 = 12.0 + get_monoisotopic_mass("H") + 3 * get_monoisotopic_mass("Cl")
        assert math.isclose(total_chcl3, expected_chcl3, rel_tol=1e-9)


# ===========================================================================
# 2. Spin Parity Gatekeeping Tests
# ===========================================================================


class TestSpinParityGatekeeping:
    """Test strict quantum mechanical electron and spin parity enforcement."""

    def test_neutral_closed_shell_singlets_pass(self) -> None:
        """Even electron count systems with Singlet multiplicity must pass."""
        # Water H2O: Z = 8 + 1 + 1 = 10 e-
        z_tot, ne = validate_spin_parity(["O", "H", "H"], charge=0, multiplicity=1)
        assert z_tot == 10
        assert ne == 10

        # Methane CH4: Z = 6 + 4*1 = 10 e-
        z_tot, ne = validate_spin_parity(["C", "H", "H", "H", "H"], charge=0, multiplicity=1)
        assert z_tot == 10
        assert ne == 10

        # Nitrogen N2: Z = 7 + 7 = 14 e-
        z_tot, ne = validate_spin_parity(["N", "N"], charge=0, multiplicity=1)
        assert z_tot == 14
        assert ne == 14

        # Benzene C6H6: Z = 6*6 + 6*1 = 42 e-
        z_tot, ne = validate_spin_parity(["C"] * 6 + ["H"] * 6, charge=0, multiplicity=1)
        assert z_tot == 42
        assert ne == 42

    def test_neutral_open_shell_triplet_passes(self) -> None:
        """Triplet ground-state oxygen O2 (16 e-, mult=3) must pass."""
        z_tot, ne = validate_spin_parity(["O", "O"], charge=0, multiplicity=3)
        assert z_tot == 16
        assert ne == 16

    def test_odd_electron_singlet_raises_value_error(self) -> None:
        """Odd electron count with Singlet multiplicity (mult=1) MUST raise ValueError."""
        # Neutral methyl radical CH3: Z = 6 + 3 = 9 e-
        with pytest.raises(
            ValueError, match=r"Spin parity violation.*9 electrons.*cannot form a Singlet"
        ):
            validate_spin_parity(["C", "H", "H", "H"], charge=0, multiplicity=1)

        # Hydroxyl radical OH: Z = 8 + 1 = 9 e-
        with pytest.raises(
            ValueError, match=r"Spin parity violation.*9 electrons.*cannot form a Singlet"
        ):
            validate_spin_parity(["O", "H"], charge=0, multiplicity=1)

        # Nitric oxide NO: Z = 7 + 8 = 15 e-
        with pytest.raises(
            ValueError, match=r"Spin parity violation.*15 electrons.*cannot form a Singlet"
        ):
            validate_spin_parity(["N", "O"], charge=0, multiplicity=1)

        # Methoxy radical CH3O: Z = 6 + 3 + 8 = 17 e-
        with pytest.raises(
            ValueError, match=r"Spin parity violation.*17 electrons.*cannot form a Singlet"
        ):
            validate_spin_parity(["C", "H", "H", "H", "O"], charge=0, multiplicity=1)

    def test_odd_electron_radicals_with_doublet_pass(self) -> None:
        """Odd electron radicals with Doublet multiplicity (mult=2) must pass."""
        # Methyl radical CH3: 9 e-, mult=2 (Doublet)
        z_tot, ne = validate_spin_parity(["C", "H", "H", "H"], charge=0, multiplicity=2)
        assert z_tot == 9
        assert ne == 9

        # Hydroxyl radical OH: 9 e-, mult=2
        z_tot, ne = validate_spin_parity(["O", "H"], charge=0, multiplicity=2)
        assert z_tot == 9
        assert ne == 9

        # Nitric oxide NO: 15 e-, mult=2
        z_tot, ne = validate_spin_parity(["N", "O"], charge=0, multiplicity=2)
        assert z_tot == 15
        assert ne == 15

    def test_even_electron_system_with_doublet_raises_value_error(self) -> None:
        """Even electron count with even multiplicity (e.g. Doublet mult=2) MUST raise ValueError."""
        # Water H2O (10 e-) with mult=2
        with pytest.raises(
            ValueError,
            match=r"Spin parity violation.*10 electrons.*cannot form an even multiplicity 2",
        ):
            validate_spin_parity(["O", "H", "H"], charge=0, multiplicity=2)

    def test_charged_ions_spin_parity(self) -> None:
        """Test ionic species (cations, anions) with formal charges."""
        # Hydroxide anion OH-: Z = 9, Charge = -1 => Ne = 10 (Singlet passes)
        z_tot, ne = validate_spin_parity(["O", "H"], charge=-1, multiplicity=1)
        assert z_tot == 9
        assert ne == 10

        # Ammonium cation NH4+: Z = 11, Charge = +1 => Ne = 10 (Singlet passes)
        z_tot, ne = validate_spin_parity(["N", "H", "H", "H", "H"], charge=1, multiplicity=1)
        assert z_tot == 11
        assert ne == 10

        # Methyl cation CH3+: Z = 9, Charge = +1 => Ne = 8 (Singlet passes)
        z_tot, ne = validate_spin_parity(["C", "H", "H", "H"], charge=1, multiplicity=1)
        assert z_tot == 9
        assert ne == 8

        # Methyl anion CH3-: Z = 9, Charge = -1 => Ne = 10 (Singlet passes)
        z_tot, ne = validate_spin_parity(["C", "H", "H", "H"], charge=-1, multiplicity=1)
        assert z_tot == 9
        assert ne == 10

    def test_impossible_electron_and_multiplicity_bounds(self) -> None:
        """Test edge cases: negative electrons, multiplicity < 1, or 2S > Ne."""
        # 0 or negative electrons (e.g. H+ with charge +2)
        with pytest.raises(ValueError, match=r"Physical impossibility.*yield Ne=-1"):
            validate_spin_parity(["H"], charge=2, multiplicity=1)

        # Multiplicity < 1
        with pytest.raises(ValueError, match=r"Invalid spin multiplicity 0"):
            validate_spin_parity(["H", "H"], charge=0, multiplicity=0)

        # Unpaired electrons exceed total electrons (e.g. H2 with 2 e-, mult=5 requires 4 unpaired e-)
        with pytest.raises(
            ValueError,
            match=r"Physical impossibility.*requires 4 unpaired electrons.*exceeds total electron count Ne=2",
        ):
            validate_spin_parity(["H", "H"], charge=0, multiplicity=5)


# ===========================================================================
# 3. Coordinate Centering, Center of Mass & Inertia Alignment Tests
# ===========================================================================


class TestCoordinatesAndEckartGeometry:
    """Test Center of Mass, Centroid, and Inertia alignment transformations."""

    @pytest.fixture
    def water_geometry(self) -> tuple[list[str], np.ndarray]:
        """Return real C2v water geometry in Angstroms."""
        symbols = ["O", "H", "H"]
        coords = np.array(
            [
                [0.000000, 0.000000, 0.117300],
                [0.000000, 0.757200, -0.469200],
                [0.000000, -0.757200, -0.469200],
            ],
            dtype=np.float64,
        )
        return symbols, coords

    def test_center_of_mass_calculation(self, water_geometry: tuple[list[str], np.ndarray]) -> None:
        """Center of mass for C2v water must be heavily shifted towards the oxygen atom."""
        symbols, coords = water_geometry
        com = compute_center_of_mass(symbols, coords)
        assert com.shape == (3,)
        # In x and y it must be 0 by symmetry
        assert math.isclose(com[0], 0.0, abs_tol=1e-6)
        assert math.isclose(com[1], 0.0, abs_tol=1e-6)
        # In z it is close to oxygen z (0.1173)
        assert 0.04 < com[2] < 0.06

    def test_geometric_centroid(self, water_geometry: tuple[list[str], np.ndarray]) -> None:
        """Geometric centroid is unweighted arithmetic mean."""
        symbols, coords = water_geometry
        centroid = compute_geometric_center(coords)
        expected = np.mean(coords, axis=0)
        np.testing.assert_allclose(centroid, expected, atol=1e-9)

    def test_center_coordinates(self, water_geometry: tuple[list[str], np.ndarray]) -> None:
        """Centering coordinates sets new COM to (0,0,0)."""
        symbols, coords = water_geometry
        masses = get_monoisotopic_masses(symbols)
        centered = center_coordinates(coords, masses=masses)
        new_com = compute_center_of_mass(symbols, centered)
        np.testing.assert_allclose(new_com, np.zeros(3), atol=1e-9)

    def test_mass_weighted_coordinates(self, water_geometry: tuple[list[str], np.ndarray]) -> None:
        """Mass weighted coordinates scale as sqrt(m_i)."""
        symbols, coords = water_geometry
        masses = get_monoisotopic_masses(symbols)
        mw_coords = compute_mass_weighted_coordinates(symbols, coords, center=True)
        assert mw_coords.shape == (3, 3)
        # Check that norm of oxygen mass-weighted row is scaled by sqrt(15.9949)
        centered = center_coordinates(coords, masses=masses)
        np.testing.assert_allclose(mw_coords[0], centered[0] * math.sqrt(masses[0]), atol=1e-9)
        np.testing.assert_allclose(mw_coords[1], centered[1] * math.sqrt(masses[1]), atol=1e-9)

    def test_inertia_tensor_and_principal_alignment(
        self, water_geometry: tuple[list[str], np.ndarray]
    ) -> None:
        """Principal axis alignment must diagonalize the inertia tensor and maintain det(R) = +1."""
        symbols, coords = water_geometry
        aligned_coords, moments, rot_matrix = align_to_principal_axes(symbols, coords)

        # Check proper rotation
        det = float(la.det(rot_matrix))  # type: ignore[attr-defined]
        assert math.isclose(det, 1.0, rel_tol=1e-7, abs_tol=1e-7)

        # Check that principal moments are strictly positive and ascending
        assert len(moments) == 3
        assert moments[0] > 0
        assert moments[1] >= moments[0]
        assert moments[2] >= moments[1]

        # Recomputed inertia tensor of aligned coords must be diagonal
        aligned_tensor = compute_moment_of_inertia_tensor(symbols, aligned_coords)
        off_diagonals = aligned_tensor - np.diag(np.diag(aligned_tensor))
        np.testing.assert_allclose(off_diagonals, np.zeros((3, 3)), atol=1e-6)


# ===========================================================================
# 4. Nuclear Clash & Coordinate Validation Tests
# ===========================================================================


class TestNuclearClashesAndCoordinateSanity:
    """Test detection of unphysical overlaps and invalid array shapes / values."""

    def test_clean_molecule_has_no_clashes(self) -> None:
        """Equilibrium methane must have zero nuclear clashes."""
        symbols = ["C", "H", "H", "H", "H"]
        # Tetrahedral methane
        d = 1.089 / math.sqrt(3)
        coords = np.array(
            [
                [0.0, 0.0, 0.0],
                [d, d, d],
                [d, -d, -d],
                [-d, d, -d],
                [-d, -d, d],
            ]
        )
        clashes = detect_nuclear_clashes(coords, symbols_or_zs=symbols, min_distance_angstrom=0.5)
        assert len(clashes) == 0

    def test_overlapping_atoms_trigger_clash_detection(self) -> None:
        """Two atoms placed 0.2 A apart must trigger nuclear clash detection."""
        symbols = ["C", "C"]
        coords = np.array(
            [
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.2],  # Extreme clash (0.2 A vs typical C-C 1.54 A)
            ]
        )
        clashes = detect_nuclear_clashes(coords, symbols_or_zs=symbols, min_distance_angstrom=0.5)
        assert len(clashes) == 1
        clash = clashes[0]
        assert clash.atom_index_1 == 0
        assert clash.atom_index_2 == 1
        assert math.isclose(clash.distance_angstrom, 0.2, abs_tol=1e-6)

    def test_strict_mode_raises_on_clash(self) -> None:
        """sanitize_and_validate_seed in strict mode must raise ValueError on clashes."""
        symbols = ["O", "H", "H"]
        clashing_coords = np.array(
            [
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.1],  # Overlap
                [0.0, 0.8, 0.0],
            ]
        )
        with pytest.raises(ValueError, match="Physical impossibility: Nuclear clashes detected"):
            sanitize_and_validate_seed(symbols, clashing_coords, strict=True)

    def test_non_strict_mode_records_clash_in_report(self) -> None:
        """sanitize_and_validate_seed in non-strict mode records clash without crashing."""
        symbols = ["O", "H", "H"]
        clashing_coords = np.array(
            [
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.1],
                [0.0, 0.8, 0.0],
            ]
        )
        report = sanitize_and_validate_seed(symbols, clashing_coords, strict=False)
        assert report.status == PreflightStatus.FAIL
        assert not report.is_valid
        assert len(report.nuclear_clashes) >= 1
        assert any("Nuclear clashes detected" in err for err in report.errors)

    def test_nan_and_inf_coordinates_raise(self) -> None:
        """Coordinates containing NaN or Inf must raise ValueError."""
        symbols = ["H", "H"]
        nan_coords = np.array([[0.0, 0.0, 0.0], [0.0, np.nan, 0.74]])
        with pytest.raises(ValueError, match="Coordinates array contains NaN"):
            sanitize_and_validate_seed(symbols, nan_coords, strict=True)

        inf_coords = np.array([[0.0, 0.0, 0.0], [0.0, np.inf, 0.74]])
        with pytest.raises(ValueError, match="Coordinates array contains NaN"):
            sanitize_and_validate_seed(symbols, inf_coords, strict=True)

    def test_dimension_mismatch_raises(self) -> None:
        """Mismatch between symbol count and coordinate rows must raise ValueError."""
        symbols = ["C", "H", "H"]
        coords_4 = np.zeros((4, 3))
        with pytest.raises(
            ValueError, match="Mismatch: 3 symbols provided but coordinate array has 4 rows"
        ):
            sanitize_and_validate_seed(symbols, coords_4, strict=True)


# ===========================================================================
# 5. Connectivity Graph & Fragment Identification Tests
# ===========================================================================


class TestConnectivityAndFragments:
    """Test molecular adjacency matrix and disconnected fragment partitioning."""

    def test_single_molecule_connectivity(self) -> None:
        """Water molecule forms a single connected component."""
        symbols = ["O", "H", "H"]
        coords = np.array(
            [
                [0.000000, 0.000000, 0.117300],
                [0.000000, 0.757200, -0.469200],
                [0.000000, -0.757200, -0.469200],
            ]
        )
        adj = build_connectivity_matrix(symbols, coords)
        # O (index 0) connected to H1 (index 1) and H2 (index 2)
        assert adj[0, 1] and adj[1, 0]
        assert adj[0, 2] and adj[2, 0]
        assert not adj[1, 2]  # H-H distance is ~1.51 A > cutoff

        fragments = find_connected_fragments(adj)
        assert len(fragments) == 1
        assert fragments[0] == [0, 1, 2]

    def test_separated_bimolecular_dimer_identifies_two_fragments(self) -> None:
        """Two water molecules separated by 10 A must be detected as 2 separate fragments."""
        symbols = ["O", "H", "H", "O", "H", "H"]
        coords = np.array(
            [
                # Water 1
                [0.0, 0.0, 0.117],
                [0.0, 0.757, -0.469],
                [0.0, -0.757, -0.469],
                # Water 2 (translated by 10 A in x)
                [10.0, 0.0, 0.117],
                [10.0, 0.757, -0.469],
                [10.0, -0.757, -0.469],
            ]
        )
        adj = build_connectivity_matrix(symbols, coords)
        fragments = find_connected_fragments(adj)
        assert len(fragments) == 2
        assert fragments[0] == [0, 1, 2]
        assert fragments[1] == [3, 4, 5]

        report = sanitize_and_validate_seed(symbols, coords, strict=False)
        assert report.num_fragments == 2
        assert report.status == PreflightStatus.WARNING
        assert any("2 disconnected fragments" in w for w in report.warnings)


# ===========================================================================
# 6. Valency Assessment & Diagnostic Warnings Tests
# ===========================================================================


class TestValencyAndDiagnostics:
    """Test per-atom valency bounds and uncharged radical diagnostic flags."""

    def test_hypervalent_hydrogen_warning(self) -> None:
        """Hydrogen atom placed symmetrically between two carbon atoms (bridging) triggers hypervalent warning."""
        symbols = ["C", "H", "C"]
        coords = np.array(
            [
                [-1.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],  # H bonded to both C atoms at 1.0 A
                [1.0, 0.0, 0.0],
            ]
        )
        diagnostics = assess_valency_and_radicals(symbols, coords)
        h_diag = diagnostics[1]
        assert h_diag.symbol == "H"
        assert h_diag.coordination_number == 2
        assert h_diag.valency_anomaly
        assert any("Hypervalent hydrogen" in w for w in h_diag.warnings)

    def test_hypervalent_carbon_warning(self) -> None:
        """Carbon atom bonded to 5 hydrogens triggers hypervalent carbon warning."""
        symbols = ["C", "H", "H", "H", "H", "H"]
        coords = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.09, 0.0, 0.0],
                [-1.09, 0.0, 0.0],
                [0.0, 1.09, 0.0],
                [0.0, -1.09, 0.0],
                [0.0, 0.0, 1.09],
            ]
        )
        diagnostics = assess_valency_and_radicals(symbols, coords)
        c_diag = diagnostics[0]
        assert c_diag.symbol == "C"
        assert c_diag.coordination_number == 5
        assert c_diag.valency_anomaly
        assert any("Hypervalent carbon" in w for w in c_diag.warnings)


# ===========================================================================
# 7. Master Preflight Entrypoint & Reporting Tests
# ===========================================================================


class TestMasterSanitizeAndValidateSeed:
    """Test full preflight pipeline and report serialization."""

    def test_water_full_preflight_pass(self) -> None:
        """Standard water seed must pass preflight with PASS status."""
        symbols = ["O", "H", "H"]
        coords = np.array(
            [
                [0.000000, 0.000000, 0.117300],
                [0.000000, 0.757200, -0.469200],
                [0.000000, -0.757200, -0.469200],
            ]
        )
        report = sanitize_and_validate_seed(
            symbols,
            coords,
            charge=0,
            multiplicity=1,
            strict=True,
            center_on_com=True,
            align_principal_axes_flag=True,
        )
        assert report.is_valid
        assert report.status == PreflightStatus.PASS
        assert report.total_atoms == 3
        assert report.total_nuclear_charge == 10
        assert report.total_electrons == 10
        assert report.formal_charge == 0
        assert report.spin_multiplicity == 1
        assert report.num_fragments == 1
        assert len(report.nuclear_clashes) == 0

        # Coordinates retrieved as numpy
        coords_np = report.get_coordinates_numpy()
        assert coords_np.shape == (3, 3)

        # Summary string check
        summary = report.summary()
        assert "CoChem-TOPOS Preflight Report" in summary
        assert "Status: PASS" in summary

        # JSON Serialization check
        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["status"] == "PASS"
        assert data["total_atoms"] == 3
        assert data["total_electrons"] == 10

    def test_empty_system_handling(self) -> None:
        """Empty input system in non-strict mode returns clean FAIL report."""
        report = sanitize_and_validate_seed([], [], strict=False)
        assert not report.is_valid
        assert report.status == PreflightStatus.FAIL
        assert report.total_atoms == 0
        assert any("Empty system" in e for e in report.errors)

    def test_open_shell_radical_methyl_preflight(self) -> None:
        """Doublet methyl radical CH3 passes preflight."""
        symbols = ["C", "H", "H", "H"]
        # Planar D3h methyl radical
        r = 1.08
        coords = [
            [0.0, 0.0, 0.0],
            [r, 0.0, 0.0],
            [-0.5 * r, math.sqrt(3) / 2 * r, 0.0],
            [-0.5 * r, -math.sqrt(3) / 2 * r, 0.0],
        ]
        # Multiplicity 2 (Doublet) -> Passes!
        report = sanitize_and_validate_seed(
            symbols, coords, charge=0, multiplicity=2, strict=True, center_on_com=True
        )
        assert report.is_valid
        assert report.total_electrons == 9
        assert report.spin_multiplicity == 2
        assert report.num_unpaired_electrons == 1
        assert math.isclose(report.spin_quantum_number_s, 0.5, abs_tol=1e-6)

        # Multiplicity 1 (Singlet) in strict mode -> Raises ValueError
        with pytest.raises(ValueError, match="Spin parity violation"):
            sanitize_and_validate_seed(symbols, coords, charge=0, multiplicity=1, strict=True)

    def test_ammonium_and_hydroxide_ions_preflight(self) -> None:
        """Cations and anions validate correctly with non-zero formal charge."""
        # NH4+ cation
        nh4_symbols = ["N", "H", "H", "H", "H"]
        d = 1.02 / math.sqrt(3)
        nh4_coords = [
            [0.0, 0.0, 0.0],
            [d, d, d],
            [d, -d, -d],
            [-d, d, -d],
            [-d, -d, d],
        ]
        report_nh4 = sanitize_and_validate_seed(
            nh4_symbols, nh4_coords, charge=1, multiplicity=1, strict=True
        )
        assert report_nh4.is_valid
        assert report_nh4.formal_charge == 1
        assert report_nh4.total_electrons == 10

        # OH- anion
        oh_symbols = ["O", "H"]
        oh_coords = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.96]]
        report_oh = sanitize_and_validate_seed(
            oh_symbols, oh_coords, charge=-1, multiplicity=1, strict=True
        )
        assert report_oh.is_valid
        assert report_oh.formal_charge == -1
        assert report_oh.total_electrons == 10

    def test_heavy_and_isotopic_water(self) -> None:
        """Deuterated water D2O and mixed HOD resolve proper isotopic masses and COM."""
        # D2O
        d2o_symbols = ["O", "D", "D"]
        d2o_coords = [
            [0.0, 0.0, 0.117],
            [0.0, 0.757, -0.469],
            [0.0, -0.757, -0.469],
        ]
        report_d2o = sanitize_and_validate_seed(d2o_symbols, d2o_coords, strict=True)
        assert report_d2o.is_valid
        # Mass of D2O is ~ 15.9949 + 2*2.0141 = ~ 20.0231 Da
        assert 20.02 < report_d2o.total_monoisotopic_mass < 20.03

        # HOD
        hod_symbols = ["O", "H", "D"]
        report_hod = sanitize_and_validate_seed(hod_symbols, d2o_coords, strict=True)
        assert report_hod.is_valid
        assert 19.01 < report_hod.total_monoisotopic_mass < 19.03

    def test_report_numpy_accessors(self) -> None:
        """Verify all numpy accessor methods on PreflightReport."""
        symbols = ["O", "H", "H"]
        coords = np.array(
            [
                [0.000000, 0.000000, 0.117300],
                [0.000000, 0.757200, -0.469200],
                [0.000000, -0.757200, -0.469200],
            ]
        )
        report = sanitize_and_validate_seed(symbols, coords, strict=True)

        geom_center = report.get_geometric_center_numpy()
        assert geom_center.shape == (3,)

        com = report.get_center_of_mass_numpy()
        assert com.shape == (3,)

        mw_coords = report.get_mass_weighted_coordinates_numpy()
        assert mw_coords.shape == (3, 3)

        moments = report.get_principal_moments_numpy()
        assert moments.shape == (3,)

    def test_single_atom_principal_axes(self) -> None:
        """Single atom inertia alignment returns zero moments and identity matrix."""
        symbols = ["He"]
        coords = np.array([[1.0, 2.0, 3.0]])
        aligned, moments, rot_matrix = align_to_principal_axes(symbols, coords)
        np.testing.assert_allclose(aligned, np.zeros((1, 3)), atol=1e-9)
        np.testing.assert_allclose(moments, np.zeros(3), atol=1e-9)
        np.testing.assert_allclose(rot_matrix, np.eye(3), atol=1e-9)

    def test_radioactive_and_synthetic_elements(self) -> None:
        """Verify isotopic mass resolution for synthetic/radioactive elements (Tc, U, Pu)."""
        tc_info = get_element_info("Tc")
        assert tc_info.atomic_number == 43
        assert tc_info.monoisotopic_mass > 90.0

        u_info = get_element_info("U")
        assert u_info.atomic_number == 92
        assert u_info.monoisotopic_mass > 230.0

    def test_spin_parity_type_and_argument_validation(self) -> None:
        """Test type errors and empty input validation in validate_spin_parity."""
        with pytest.raises(TypeError, match="Charge must be an integer"):
            validate_spin_parity(["H"], charge="0")  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="Multiplicity must be an integer"):
            validate_spin_parity(["H"], charge=0, multiplicity=1.5)  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="Cannot validate spin parity for an empty system"):
            validate_spin_parity([], charge=0, multiplicity=1)

        # Odd electron with odd multiplicity > 1 (e.g. 9 electrons with Triplet mult=3)
        with pytest.raises(
            ValueError,
            match=r"Spin parity violation: System has 9 electrons \(odd count\), but requested multiplicity is 3 \(odd\)",
        ):
            validate_spin_parity(["C", "H", "H", "H"], charge=0, multiplicity=3)

    def test_uncharged_radical_center_warnings(self) -> None:
        """Trivalent carbon and monovalent oxygen in singlet neutral state trigger uncharged radical warnings."""
        # Trivalent neutral carbon (e.g. planar methyl in singlet)
        symbols_ch3 = ["C", "H", "H", "H"]
        coords_ch3 = [[0.0, 0.0, 0.0], [1.08, 0.0, 0.0], [-0.54, 0.93, 0.0], [-0.54, -0.93, 0.0]]
        diag_ch3 = assess_valency_and_radicals(symbols_ch3, coords_ch3, charge=0, multiplicity=1)
        assert any("uncharged radical center" in w for w in diag_ch3[0].warnings)

        # Monovalent neutral oxygen (e.g. OH radical in singlet)
        symbols_oh = ["O", "H"]
        coords_oh = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.96]]
        diag_oh = assess_valency_and_radicals(symbols_oh, coords_oh, charge=0, multiplicity=1)
        assert any("oxy radical" in w for w in diag_oh[0].warnings)

    def test_non_strict_error_aggregation_and_summary(self) -> None:
        """Non-strict mode aggregates invalid symbols, invalid coords, NaN, and formats summary."""
        report = sanitize_and_validate_seed(
            ["InvalidElementX"],
            [[np.nan, 0.0, 0.0]],
            strict=False,
        )
        assert not report.is_valid
        assert report.status == PreflightStatus.FAIL
        assert len(report.errors) > 0
        summary_text = report.summary()
        assert "Errors (" in summary_text
        assert "[ERROR]" in summary_text
