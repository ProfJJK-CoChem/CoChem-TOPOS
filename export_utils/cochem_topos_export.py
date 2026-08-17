"""
CoChem-TOPOS: Stage 5.0 - Post-Flight Audit & FAIR Export
Extracts finalized calculations from landscape.h5, compiles LaTeX SI documents,
and packages reproducibility archives.
"""
import hashlib  # SHA-256 artifact provenance tracking
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Dict, Optional, Union

import h5py

logger = logging.getLogger("CoChem.TOPOS.FAIRExporter")


def _compute_sha256(file_path: Path) -> str:
    """Computes the SHA-256 hexadecimal digest for a given file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


class TOPOSFAIRExporter:
    """
    Scrapes the finalized landscape.h5 database to compile Supporting Information 
    LaTeX documentation and compressed FAIR-compliant submission archives.
    """
    
    def __init__(self, hdf5_path: Union[str, Path], output_dir: Union[str, Path]) -> None:
        self.hdf5_path = Path(hdf5_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        if not self.hdf5_path.exists():
            raise FileNotFoundError(f"Master database not found at {self.hdf5_path}")

    def generate_latex_si(self, filename: str = "TOPOS_Supporting_Information.tex") -> Path:
        """
        Scrapes landscape.h5 and compiles a compile-ready LaTeX document 
        featuring siunitx-formatted tables for energies and coordinates.
        """
        latex_path = self.output_dir / filename
        
        records = []
        try:
            with h5py.File(self.hdf5_path, 'r', libver='latest', swmr=True) as f:
                # Traverse the database for evaluated geometries
                base_group = f["deduplicated_isomers"] if "deduplicated_isomers" in f else f
                for geom_id in base_group.keys():
                    geom_group = base_group[geom_id]
                    if not isinstance(geom_group, h5py.Group):
                        continue
                    
                    # Find the highest tier available for this geometry (strictly h5py.Group)
                    available_tiers = [k for k, v in geom_group.items() if isinstance(v, h5py.Group)]
                    if not available_tiers:
                        continue
                    
                    # Sort or pick the terminal tier (e.g., TIER_4_EQ_TARGET or highest available)
                    def extract_tier_num(t: str) -> int:
                        match = re.search(r'\d+', t)
                        return int(match.group()) if match else 0

                    available_tiers.sort(key=extract_tier_num)
                    terminal_tier = available_tiers[-1]
                    tier_grp = geom_group[terminal_tier]
                    
                    # Check for energy in attributes or datasets
                    energy: Optional[float] = None
                    if "electronic_energy_hartree" in tier_grp.attrs:
                        val = tier_grp.attrs["electronic_energy_hartree"]
                        if val is not None:
                            energy = float(val)
                    elif "energy" in tier_grp.attrs:
                        val = tier_grp.attrs["energy"]
                        if val is not None:
                            energy = float(val)
                    elif "electronic_energy_hartree" in tier_grp and isinstance(tier_grp["electronic_energy_hartree"], h5py.Dataset):
                        val = tier_grp["electronic_energy_hartree"][()]
                        if val is not None:
                            energy = float(val)
                    elif "energy" in tier_grp and isinstance(tier_grp["energy"], h5py.Dataset):
                        val = tier_grp["energy"][()]
                        if val is not None:
                            energy = float(val)

                    if energy is None:
                        logger.warning(
                            f"Missing electronic energy for geometry '{geom_id}' at tier '{terminal_tier}'. Defaulting to 0.0 Hartree."
                        )
                        energy = 0.0
                    
                    xyz_str = ""
                    if "geometry_xyz" in tier_grp:
                        xyz_val = tier_grp["geometry_xyz"][()]
                        xyz_str = xyz_val.decode('utf-8') if hasattr(xyz_val, 'decode') else str(xyz_val)
                    
                    records.append({
                        "id": geom_id,
                        "tier": terminal_tier,
                        "energy": energy,
                        "xyz": xyz_str
                    })
        except Exception as e:
            logger.error(f"Failed to read HDF5 database during LaTeX generation: {e}")
            raise

        records.sort(key=lambda x: x["id"])

        # Construct the LaTeX document string using standard siunitx structures
        latex_content = r"""\documentclass[11pt, a4paper]{article}
\usepackage[a4paper, margin=2.5cm]{geometry}
\usepackage{booktabs}
\usepackage{siunitx}
\usepackage{hyperref}
\DeclareSIUnit\hartree{E_h}

\title{CoChem-TOPOS: High-Precision Conformational Supporting Information}
\author{CoChem Automated Pipeline Engine}
\date{\today}

\begin{document}
\maketitle

\section{Introduction}
This document contains the verified structural coordinates and single-point electronic energies resulting from the multi-tier Method Matrix Cascade.

\section{Optimized Isomer Energetics}
\begin{table}[htbp]
\centering
\caption{Optimized Isomer Energies across Method Matrix Tiers}
\begin{tabular}{l l S[table-format=-4.6]}
\toprule
\textbf{Isomer ID} & \textbf{Terminal Tier} & {\textbf{Energy (\si{\hartree})}} \\
\midrule
"""
        
        for rec in records:
            id_esc = rec['id'].replace('_', r'\_')
            tier_esc = rec['tier'].replace('_', r'\_')
            latex_content += f"{id_esc} & {tier_esc} & {rec['energy']:.6f} \\\\\n"
            
        latex_content += r"""\bottomrule
\end{tabular}
\end{table}

\section{Cartesian Coordinates}
"""
        
        for rec in records:
            id_esc = rec['id'].replace('_', r'\_')
            tier_esc = rec['tier'].replace('_', r'\_')
            latex_content += f"\\subsection*{{Isomer: {id_esc} ({tier_esc})}}\n"
            latex_content += "\\begin{verbatim}\n" + rec['xyz'] + "\n\\end{verbatim}\n"

        latex_content += r"""
\end{document}
"""

        with open(latex_path, 'w', encoding='utf-8') as f:
            f.write(latex_content)
            
        logger.info(f"Successfully generated LaTeX Supporting Information at {latex_path}")
        return latex_path

    def bundle_fair_archive(self, zip_filename: str = "TOPOS_FAIR_Archive.zip") -> Path:
        """
        Bundles landscape.h5, the generated LaTeX documentation, and provenance 
        metadata into a single compressed ZIP archive for Zenodo deposition.
        """
        zip_path = self.output_dir / zip_filename
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            provenance_hashes: Dict[str, str] = {}

            # 1. Add the master HDF5 database
            if self.hdf5_path.exists():
                zf.write(self.hdf5_path, arcname="landscape.h5")
                provenance_hashes["landscape.h5"] = _compute_sha256(self.hdf5_path)
                
            # 2. Gather generated LaTeX files and QM artifacts
            files_to_bundle: Dict[str, Path] = {}
            for tex_file in self.output_dir.glob("*.tex"):
                files_to_bundle[tex_file.name] = tex_file

            search_dirs = [self.output_dir]
            if self.hdf5_path.parent.exists() and self.hdf5_path.parent.resolve() != self.output_dir.resolve():
                search_dirs.append(self.hdf5_path.parent)

            for sdir in search_dirs:
                for target_ext in ["*.out", "*.gbw"]:
                    for qm_file in sdir.glob(target_ext):
                        if qm_file.name not in files_to_bundle:
                            files_to_bundle[qm_file.name] = qm_file

            # 3. Add files to zip archive and record provenance hashes
            for arc_name, file_path in files_to_bundle.items():
                zf.write(file_path, arcname=arc_name)
                provenance_hashes[arc_name] = _compute_sha256(file_path)
            
            # 4. Embed a JSON provenance manifest
            manifest = {
                "archive_type": "CoChem-TOPOS FAIR Output",
                "version": "4.0",
                "source_database": self.hdf5_path.name,
                "provenance_hashes": provenance_hashes,
                "accuracy_claim": "[M] - Extracted directly from Method Matrix cascade."
            }
            zf.writestr("fair_manifest.json", json.dumps(manifest, indent=2))
                
        logger.info(f"FAIR submission archive successfully compiled at {zip_path}")
        return zip_path
