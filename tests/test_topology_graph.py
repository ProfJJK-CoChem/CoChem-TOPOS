"""
Unit tests for CoChem-TOPOS Graph Cleavage and Routing Engine (cochem_topos_graph.py).
Validates covalent connectivity graph construction, resonance protection trap scaling,
and physical coordinate severing into monomer seeds for counterpoise assembly.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from topology.cochem_topos_graph import (
    TopologyAnalysisResult,
    TopologyGraphEngine,
    analyze_molecular_graph,
    generate_chemical_formula,
    get_covalent_radius,
    parse_xyz_file,
    parse_xyz_string,
)


class TestCovalentRadiiAndFormulas:
    """Verifies empirical covalent radii lookup and chemical formula formatting."""

    def test_covalent_radii_lookup_by_symbol_and_atomic_number(self) -> None:
        """Confirms covalent radii match Cordero / Pyykko standards for common elements."""
        assert get_covalent_radius("H") == 0.31
        assert get_covalent_radius(1) == 0.31
        assert get_covalent_radius("C") == 0.76
        assert get_covalent_radius(6) == 0.76
        assert get_covalent_radius("N") == 0.71
        assert get_covalent_radius(7) == 0.71
        assert get_covalent_radius("O") == 0.66
        assert get_covalent_radius(8) == 0.66
        assert get_covalent_radius("F") == 0.57
        assert get_covalent_radius(9) == 0.57
        assert get_covalent_radius("Ar") == 1.06
        assert get_covalent_radius(18) == 1.06

    def test_covalent_radii_fallback(self) -> None:
        """Confirms unlisted or synthetic elements fall back to a reasonable default radius."""
        fallback_radius = get_covalent_radius(999)
        assert fallback_radius == 1.50

    def test_generate_chemical_formula(self) -> None:
        """Validates Hill notation chemical formula generation."""
        assert generate_chemical_formula(["O", "H", "H"]) == "H2O"
        assert generate_chemical_formula(["C", "H", "H", "H", "H"]) == "CH4"
        assert generate_chemical_formula(["C", "C", "C", "C", "C", "C", "H", "H", "H", "H", "H", "H"]) == "C6H6"
        assert generate_chemical_formula(["C", "O", "O"]) == "CO2"
        assert generate_chemical_formula(["Ar"]) == "Ar"
        assert generate_chemical_formula(["H", "F"]) == "FH" or generate_chemical_formula(["H", "F"]) == "HF"


class TestMonomerIdentification:
    """Verifies that single covalent molecules are routed directly to MONOMER_GOAT."""

    def test_water_monomer(self) -> None:
        """Evaluates single water molecule connectivity and routing target."""
        symbols = ["O", "H", "H"]
        coordinates = np.array([
            [0.0000,  0.0000,  0.1173],
            [0.0000,  0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ])

        engine = TopologyGraphEngine()
        result = engine.analyze_topology(symbols, coordinates)

        assert isinstance(result, TopologyAnalysisResult)
        assert result.num_atoms == 3
        assert result.num_fragments == 1
        assert result.is_weak_complex is False
        assert result.classification == "Monomer"
        assert result.routing_target == "MONOMER_GOAT"
        assert result.counterpoise_flag is False
        assert len(result.monomers) == 1

        monomer = result.monomers[0]
        assert monomer.fragment_index == 0
        assert monomer.num_atoms == 3
        assert monomer.symbols == ["O", "H", "H"]
        assert monomer.atomic_numbers == [8, 1, 1]
        assert monomer.atom_indices == [0, 1, 2]
        assert monomer.formula == "H2O"
        np.testing.assert_allclose(monomer.get_numpy_coordinates(), coordinates, atol=1e-5)

    def test_methane_monomer(self) -> None:
        """Evaluates methane molecule connectivity and single component topology."""
        symbols = ["C", "H", "H", "H", "H"]
        coordinates = np.array([
            [0.0000,  0.0000,  0.0000],
            [0.6276,  0.6276,  0.6276],
            [0.6276, -0.6276, -0.6276],
            [-0.6276,  0.6276, -0.6276],
            [-0.6276, -0.6276,  0.6276],
        ])

        result = analyze_molecular_graph(symbols, coordinates)

        assert result.num_atoms == 5
        assert result.num_fragments == 1
        assert result.is_weak_complex is False
        assert result.classification == "Monomer"
        assert result.routing_target == "MONOMER_GOAT"
        assert result.counterpoise_flag is False
        assert result.monomers[0].formula == "CH4"

    def test_benzene_monomer(self) -> None:
        """Evaluates aromatic benzene ring connectivity under 1.15x covalent threshold."""
        symbols = [
            "C", "C", "C", "C", "C", "C",
            "H", "H", "H", "H", "H", "H"
        ]
        coordinates = np.array([
            [ 0.0000,  1.3970,  0.0000],
            [ 1.2098,  0.6985,  0.0000],
            [ 1.2098, -0.6985,  0.0000],
            [ 0.0000, -1.3970,  0.0000],
            [-1.2098, -0.6985,  0.0000],
            [-1.2098,  0.6985,  0.0000],
            [ 0.0000,  2.4790,  0.0000],
            [ 2.1469,  1.2395,  0.0000],
            [ 2.1469, -1.2395,  0.0000],
            [ 0.0000, -2.4790,  0.0000],
            [-2.1469, -1.2395,  0.0000],
            [-2.1469,  1.2395,  0.0000],
        ])

        result = analyze_molecular_graph(symbols, coordinates)

        assert result.num_atoms == 12
        assert result.num_fragments == 1
        assert result.is_weak_complex is False
        assert result.classification == "Monomer"
        assert result.routing_target == "MONOMER_GOAT"
        assert result.counterpoise_flag is False
        assert result.monomers[0].formula == "C6H6"


class TestResonanceProtectionTrap:
    """Verifies that the 1.15x scaling factor preserves elongated transition state bonds."""

    def test_elongated_carbon_bond_scaling_protection(self) -> None:
        """
        Tests an elongated C-C bond at 1.65 Angstroms (e.g. transition state).
        Standard covalent sum = 0.76 + 0.76 = 1.52 A.
        Unscaled threshold (1.00x) = 1.52 A < 1.65 A -> False fragmentation.
        Scaled threshold (1.15x) = 1.15 * 1.52 = 1.748 A >= 1.65 A -> Protected single molecule!
        """
        symbols = ["C", "C", "H", "H", "H", "H", "H", "H"]
        # Stretched ethane with C-C distance = 1.65 A and C-H distances = 1.018 A (< 1.07 A)
        coordinates = np.array([
            [-0.8250,  0.0000,  0.0000],
            [ 0.8250,  0.0000,  0.0000],
            [-1.1650,  0.9600,  0.0000],
            [-1.1650, -0.4800,  0.8314],
            [-1.1650, -0.4800, -0.8314],
            [ 1.1650,  0.9600,  0.0000],
            [ 1.1650, -0.4800,  0.8314],
            [ 1.1650, -0.4800, -0.8314],
        ])

        engine_scaled = TopologyGraphEngine(resonance_scale=1.15)
        result_scaled = engine_scaled.analyze_topology(symbols, coordinates)
        assert result_scaled.num_fragments == 1
        assert result_scaled.is_weak_complex is False
        assert result_scaled.classification == "Monomer"
        assert result_scaled.routing_target == "MONOMER_GOAT"

        engine_unscaled = TopologyGraphEngine(resonance_scale=1.00)
        result_unscaled = engine_unscaled.analyze_topology(symbols, coordinates)
        assert result_unscaled.num_fragments == 2
        assert result_unscaled.is_weak_complex is True
        assert result_unscaled.classification == "Weak Complex"
        assert result_unscaled.routing_target == "COUNTERPOISE_ASSEMBLY"


class TestWeakComplexDetectionAndCleavage:
    """Verifies that non-covalent complexes are severed into isolated monomer seeds."""

    def test_water_dimer_cleavage(self) -> None:
        """
        Tests water dimer (H2O...H2O) with hydrogen bond distance ~1.95 A (O...H) and ~2.9 A (O...O).
        Both exceed covalent cutoffs and result in 2 severed water monomer seeds.
        """
        symbols = ["O", "H", "H", "O", "H", "H"]
        coordinates = np.array([
            # Monomer A (indices 0, 1, 2)
            [-1.464, -0.019,  0.021],
            [-1.765,  0.888,  0.002],
            [-0.499, -0.008, -0.063],
            # Monomer B (indices 3, 4, 5)
            [ 1.442,  0.001, -0.004],
            [ 1.761, -0.457,  0.778],
            [ 1.745, -0.479, -0.771],
        ])

        engine = TopologyGraphEngine(resonance_scale=1.15)
        result = engine.analyze_topology(symbols, coordinates)

        assert result.num_atoms == 6
        assert result.num_fragments == 2
        assert result.is_weak_complex is True
        assert result.classification == "Weak Complex"
        assert result.routing_target == "COUNTERPOISE_ASSEMBLY"
        assert result.counterpoise_flag is True
        assert len(result.monomers) == 2

        # Verify monomer A
        monomer_a = result.monomers[0]
        assert monomer_a.num_atoms == 3
        assert monomer_a.symbols == ["O", "H", "H"]
        assert monomer_a.atom_indices == [0, 1, 2]
        assert monomer_a.formula == "H2O"
        np.testing.assert_allclose(monomer_a.get_numpy_coordinates(), coordinates[0:3], atol=1e-5)

        # Verify monomer B
        monomer_b = result.monomers[1]
        assert monomer_b.num_atoms == 3
        assert monomer_b.symbols == ["O", "H", "H"]
        assert monomer_b.atom_indices == [3, 4, 5]
        assert monomer_b.formula == "H2O"
        np.testing.assert_allclose(monomer_b.get_numpy_coordinates(), coordinates[3:6], atol=1e-5)

    def test_formic_acid_dimer_cleavage(self) -> None:
        """Tests hydrogen-bonded formic acid dimer ((HCOOH)2) cleavage into 2 HCOOH monomers."""
        symbols = [
            "C", "O", "O", "H", "H",
            "C", "O", "O", "H", "H"
        ]
        coordinates = np.array([
            # Monomer 1 (HCOOH)
            [-1.3400,  0.1300,  0.0000],
            [-1.2500,  1.3200,  0.0000],
            [-2.3900, -0.6600,  0.0000],
            [-0.3800, -0.4200,  0.0000],
            [-2.2300, -1.6100,  0.0000],
            # Monomer 2 (HCOOH)
            [ 1.3400, -0.1300,  0.0000],
            [ 1.2500, -1.3200,  0.0000],
            [ 2.3900,  0.6600,  0.0000],
            [ 0.3800,  0.4200,  0.0000],
            [ 2.2300,  1.6100,  0.0000],
        ])

        result = analyze_molecular_graph(symbols, coordinates)

        assert result.num_atoms == 10
        assert result.num_fragments == 2
        assert result.is_weak_complex is True
        assert result.classification == "Weak Complex"
        assert result.routing_target == "COUNTERPOISE_ASSEMBLY"
        assert result.counterpoise_flag is True

        assert len(result.monomers) == 2
        assert result.monomers[0].num_atoms == 5
        assert result.monomers[0].formula == "CH2O2"
        assert result.monomers[1].num_atoms == 5
        assert result.monomers[1].formula == "CH2O2"

    def test_carbon_dioxide_water_complex(self) -> None:
        """Tests hetero-dimer CO2...H2O cleavage into CO2 and H2O monomers."""
        symbols = ["C", "O", "O", "O", "H", "H"]
        coordinates = np.array([
            # CO2
            [ 0.000,  0.000, -1.500],
            [ 0.000,  0.000, -0.340],
            [ 0.000,  0.000, -2.660],
            # H2O
            [ 0.000,  0.000,  1.500],
            [ 0.000,  0.757,  2.087],
            [ 0.000, -0.757,  2.087],
        ])

        result = analyze_molecular_graph(symbols, coordinates)

        assert result.num_atoms == 6
        assert result.num_fragments == 2
        assert result.is_weak_complex is True
        assert result.classification == "Weak Complex"
        assert result.routing_target == "COUNTERPOISE_ASSEMBLY"
        assert result.counterpoise_flag is True

        formulas = sorted([m.formula for m in result.monomers])
        assert formulas == ["CO2", "H2O"]

    def test_argon_hydrogen_fluoride_complex(self) -> None:
        """Tests noble-gas van der Waals complex Ar...HF."""
        symbols = ["Ar", "H", "F"]
        coordinates = np.array([
            [0.0000, 0.0000, -2.0000],  # Ar
            [0.0000, 0.0000,  1.0000],  # H
            [0.0000, 0.0000,  1.9200],  # F
        ])

        result = analyze_molecular_graph(symbols, coordinates)

        assert result.num_atoms == 3
        assert result.num_fragments == 2
        assert result.is_weak_complex is True
        assert result.classification == "Weak Complex"
        assert result.routing_target == "COUNTERPOISE_ASSEMBLY"
        assert result.counterpoise_flag is True

        atom_counts = sorted([m.num_atoms for m in result.monomers])
        assert atom_counts == [1, 2]

    def test_water_trimer_multi_fragment_cleavage(self) -> None:
        """Tests three-body cluster (H2O)3 cleavage into 3 distinct monomer seeds."""
        symbols = ["O", "H", "H", "O", "H", "H", "O", "H", "H"]
        coordinates = np.array([
            # Monomer 1
            [ 1.500,  0.000, 0.000],
            [ 2.000,  0.757, 0.000],
            [ 2.000, -0.757, 0.000],
            # Monomer 2
            [-1.500,  1.500, 0.000],
            [-1.000,  2.257, 0.000],
            [-1.000,  0.743, 0.000],
            # Monomer 3
            [-1.500, -1.500, 0.000],
            [-1.000, -0.743, 0.000],
            [-1.000, -2.257, 0.000],
        ])

        result = analyze_molecular_graph(symbols, coordinates)

        assert result.num_atoms == 9
        assert result.num_fragments == 3
        assert result.is_weak_complex is True
        assert result.classification == "Weak Complex"
        assert result.routing_target == "COUNTERPOISE_ASSEMBLY"
        assert result.counterpoise_flag is True
        assert len(result.monomers) == 3
        for monomer in result.monomers:
            assert monomer.num_atoms == 3
            assert monomer.formula == "H2O"


class TestCoordinateSlicingAndXYZExport:
    """Verifies XYZ parsing, string output, file export, and coordinate integrity."""

    def test_monomer_seed_xyz_string_and_export(self, tmp_path: Path) -> None:
        """Confirms monomer seeds can be written to XYZ strings and files."""
        symbols = ["O", "H", "H", "O", "H", "H"]
        coordinates = np.array([
            [-1.5, 0.0, 0.0],
            [-1.8, 0.7, 0.0],
            [-0.6, 0.0, 0.0],
            [ 1.5, 0.0, 0.0],
            [ 1.8, 0.7, 0.0],
            [ 1.8,-0.7, 0.0],
        ])

        engine = TopologyGraphEngine()
        result = engine.analyze_topology(symbols, coordinates)

        # Verify monomer XYZ string format
        monomer_a_xyz = result.monomers[0].to_xyz_string(comment="Monomer 0")
        lines = monomer_a_xyz.strip().split("\n")
        assert lines[0] == "3"
        assert lines[1] == "Monomer 0"
        assert len(lines) == 5

        # Export all monomers to tmp_path
        exported_paths = result.save_monomers_xyz(tmp_path, base_prefix="isolated_seed")
        assert len(exported_paths) == 2
        for path in exported_paths:
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert content.startswith("3\n")

    def test_parse_xyz_string_and_file(self, tmp_path: Path) -> None:
        """Validates XYZ parser on both raw strings and disk files."""
        raw_xyz = """3
Water monomer test coordinate
O  0.0000  0.0000  0.1173
H  0.0000  0.7572 -0.4692
H  0.0000 -0.7572 -0.4692
"""
        parsed_symbols, parsed_coords, title = parse_xyz_string(raw_xyz)
        assert parsed_symbols == ["O", "H", "H"]
        assert parsed_coords.shape == (3, 3)
        assert title == "Water monomer test coordinate"

        file_path = tmp_path / "water.xyz"
        file_path.write_text(raw_xyz, encoding="utf-8")

        file_symbols, file_coords, file_title = parse_xyz_file(file_path)
        assert file_symbols == parsed_symbols
        np.testing.assert_allclose(file_coords, parsed_coords)

        # Analyze directly via engine method
        engine = TopologyGraphEngine()
        res_from_file = engine.analyze_xyz_file(file_path)
        assert res_from_file.classification == "Monomer"
        assert res_from_file.routing_target == "MONOMER_GOAT"

    def test_ase_atoms_ingestion(self) -> None:
        """Validates ingestion from an ASE Atoms object."""
        atoms = Atoms(symbols=["O", "H", "H"], positions=[
            [0.0000,  0.0000,  0.1173],
            [0.0000,  0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ])

        engine = TopologyGraphEngine()
        result = engine.analyze_atoms(atoms)
        assert result.classification == "Monomer"
        assert result.routing_target == "MONOMER_GOAT"
        assert result.num_atoms == 3


class TestSerializationAndValidation:
    """Verifies Pydantic model serialization, validation, and error traps."""

    def test_pydantic_serialization(self) -> None:
        """Verifies JSON round-trip serialization of TopologyAnalysisResult."""
        symbols = ["O", "H", "H"]
        coordinates = np.array([
            [0.0000,  0.0000,  0.1173],
            [0.0000,  0.7572, -0.4692],
            [0.0000, -0.7572, -0.4692],
        ])

        engine = TopologyGraphEngine()
        result = engine.analyze_topology(symbols, coordinates)

        json_str = result.to_json()
        data = json.loads(json_str)

        assert data["num_atoms"] == 3
        assert data["classification"] == "Monomer"
        assert data["routing_target"] == "MONOMER_GOAT"
        assert len(data["monomers"]) == 1

        reconstructed = TopologyAnalysisResult.model_validate(data)
        assert reconstructed.num_atoms == result.num_atoms
        assert reconstructed.routing_target == result.routing_target

    def test_single_atom_validation(self) -> None:
        """Confirms monoatomic system is treated as a monomer."""
        symbols = ["He"]
        coordinates = np.array([[0.0, 0.0, 0.0]])

        result = analyze_molecular_graph(symbols, coordinates)
        assert result.num_atoms == 1
        assert result.num_fragments == 1
        assert result.classification == "Monomer"
        assert result.routing_target == "MONOMER_GOAT"
        assert result.counterpoise_flag is False

    def test_empty_coordinates_error(self) -> None:
        """Confirms empty inputs raise ValueError."""
        engine = TopologyGraphEngine()
        with pytest.raises(ValueError, match="At least one atom"):
            engine.analyze_topology([], np.empty((0, 3)))

    def test_dimension_mismatch_error(self) -> None:
        """Confirms symbol count and coordinate count mismatch raises ValueError."""
        symbols = ["O", "H"]
        coordinates = np.array([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
        ])
        engine = TopologyGraphEngine()
        with pytest.raises(ValueError, match="Mismatch"):
            engine.analyze_topology(symbols, coordinates)

    def test_invalid_coordinate_shape_error(self) -> None:
        """Confirms 2D or 1D coordinate array raises ValueError."""
        symbols = ["O", "H"]
        coordinates = np.array([[0.0, 0.0], [1.0, 0.0]])
        engine = TopologyGraphEngine()
        with pytest.raises(ValueError, match="Cartesian coordinates must have shape"):
            engine.analyze_topology(symbols, coordinates)
