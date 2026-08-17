"""
Unit tests for TOPOSFAIRExporter (export_utils/cochem_topos_export.py).
Validates LaTeX Supporting Information generation, HDF5 parsing resilience,
tier number regex extraction, fallback energy handling, and FAIR packaging.
"""

import json
import logging
import zipfile
from pathlib import Path
import h5py
import pytest

from export_utils.cochem_topos_export import TOPOSFAIRExporter, _compute_sha256


def test_compute_sha256(tmp_path: Path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello CoChem", encoding="utf-8")
    digest = _compute_sha256(test_file)
    assert isinstance(digest, str)
    assert len(digest) == 64


def test_topos_fair_exporter_init(tmp_path: Path):
    h5_path = tmp_path / "landscape.h5"
    out_dir = tmp_path / "fair_export"
    
    with pytest.raises(FileNotFoundError):
        TOPOSFAIRExporter(h5_path, out_dir)
        
    with h5py.File(h5_path, "w") as f:
        f.attrs["test"] = 1
        
    exporter = TOPOSFAIRExporter(h5_path, out_dir)
    assert exporter.hdf5_path == h5_path
    assert exporter.output_dir.exists()


def test_latex_si_generation_and_siunitx_header(tmp_path: Path):
    h5_path = tmp_path / "landscape.h5"
    out_dir = tmp_path / "fair_export"
    
    with h5py.File(h5_path, "w") as f:
        iso_grp = f.create_group("deduplicated_isomers")
        geom_a = iso_grp.create_group("isomer_001")
        
        # Add non-group dataset inside geom to test issue #2
        geom_a.create_dataset("some_metadata_dataset", data=[1, 2, 3])
        
        # Add hyphenated tier group to test issue #3
        t1_grp = geom_a.create_group("T1-30min")
        t1_grp.attrs["electronic_energy_hartree"] = -154.234567
        t1_grp.create_dataset("geometry_xyz", data=b"3\nWater\nO 0 0 0\nH 0 1 0\nH 0 0 1")
        
        # Add higher tier
        t2_grp = geom_a.create_group("T2-3h")
        t2_grp.attrs["electronic_energy_hartree"] = -154.300123
        t2_grp.create_dataset("geometry_xyz", data=b"3\nWater opt\nO 0 0 0\nH 0 1 0\nH 0 0 1")

    exporter = TOPOSFAIRExporter(h5_path, out_dir)
    tex_path = exporter.generate_latex_si("test_SI.tex")
    
    assert tex_path.exists()
    content = tex_path.read_text(encoding="utf-8")
    
    # 1. Verify siunitx braces fix (Issue #1)
    assert r"{\textbf{Energy (\si{\hartree})}}" in content
    
    # 2. Verify highest tier was chosen (T2-3h over T1-30min) (Issue #3)
    assert r"isomer\_001" in content
    assert r"T2-3h" in content
    assert "-154.300123" in content
    assert "Water opt" in content


def test_energy_dataset_and_fallback_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    h5_path = tmp_path / "landscape.h5"
    out_dir = tmp_path / "fair_export"
    
    with h5py.File(h5_path, "w") as f:
        # Test direct root isomers (when deduplicated_isomers group is absent)
        geom_b = f.create_group("isomer_dataset_energy")
        t1 = geom_b.create_group("TIER_1_SCREEN")
        # Store energy as dataset rather than attribute (Issue #5)
        t1.create_dataset("electronic_energy_hartree", data=-76.123456)
        
        geom_c = f.create_group("isomer_missing_energy")
        geom_c.create_group("TIER_1_SCREEN")  # No energy attribute or dataset

    exporter = TOPOSFAIRExporter(h5_path, out_dir)
    with caplog.at_level(logging.WARNING):
        tex_path = exporter.generate_latex_si()
        
    content = tex_path.read_text(encoding="utf-8")
    assert "-76.123456" in content
    assert "0.000000" in content
    
    # Verify warning was logged for isomer_missing_energy
    assert any("Missing electronic energy for geometry 'isomer_missing_energy'" in record.message for record in caplog.records)


def test_bundle_fair_archive_with_qm_artifacts(tmp_path: Path):
    h5_dir = tmp_path / "calculations"
    h5_dir.mkdir()
    h5_path = h5_dir / "landscape.h5"
    out_dir = tmp_path / "export_output"
    out_dir.mkdir()

    # Create dummy landscape.h5
    with h5py.File(h5_path, "w") as f:
        g = f.create_group("iso_1")
        t = g.create_group("T1")
        t.attrs["electronic_energy_hartree"] = -100.0

    # Create QM artifacts in h5_path.parent
    orca_out = h5_dir / "calc_01.out"
    orca_out.write_text("ORCA TERMINATED NORMALLY", encoding="utf-8")
    orca_gbw = h5_dir / "calc_01.gbw"
    orca_gbw.write_bytes(b"\x00\x01\x02\x03")

    exporter = TOPOSFAIRExporter(h5_path, out_dir)
    exporter.generate_latex_si()

    zip_path = exporter.bundle_fair_archive("archive.zip")
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "landscape.h5" in namelist
        assert "TOPOS_Supporting_Information.tex" in namelist
        assert "calc_01.out" in namelist
        assert "calc_01.gbw" in namelist
        assert "fair_manifest.json" in namelist

        manifest_data = json.loads(zf.read("fair_manifest.json").decode("utf-8"))
        assert manifest_data["archive_type"] == "CoChem-TOPOS FAIR Output"
        hashes = manifest_data["provenance_hashes"]
        assert "landscape.h5" in hashes
        assert "calc_01.out" in hashes
        assert "calc_01.gbw" in hashes
        assert "TOPOS_Supporting_Information.tex" in hashes
        assert hashes["calc_01.out"] == _compute_sha256(orca_out)
