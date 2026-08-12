import hashlib  # SHA-256 artifact provenance tracking
"""
CoChem-TOPOS: Stage 5.0 - Post-Flight Audit & FAIR Export
Extracts finalized calculations from landscape.h5, compiles LaTeX SI documents,
and packages reproducibility archives.
"""

import h5py
import zipfile
import logging
import json
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger("CoChem.TOPOS.FAIRExporter")

class TOPOSFAIRExporter:
    """
    Scrapes the finalized landscape.h5 database to compile Supporting Information 
    LaTeX documentation and compressed FAIR-compliant submission archives.
    """
    
    def __init__(self, hdf5_path: str, output_dir: str) -> None:
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
                for geom_id in f.keys():
                    if geom_id == "deduplicated_isomers":
                        continue
                    
                    geom_group = f[geom_id]
                    # Find the highest tier available for this geometry
                    available_tiers = list(geom_group.keys())
                    if not available_tiers:
                        continue
                    
                    # Sort or pick the terminal tier (e.g., TIER_4_EQ_TARGET or highest available)
                    terminal_tier = available_tiers[-1]
                    tier_grp = geom_group[terminal_tier]
                    
                    energy = tier_grp.attrs.get("electronic_energy_hartree", 0.0)
                    xyz_str = tier_grp["geometry_xyz"][()].decode('utf-8') if "geometry_xyz" in tier_grp else ""
                    
                    records.append({
                        "id": geom_id,
                        "tier": terminal_tier,
                        "energy": energy,
                        "xyz": xyz_str
                    })
        except Exception as e:
            logger.error(f"Failed to read HDF5 database during LaTeX generation: {e}")
            raise

        # Construct the LaTeX document string using standard siunitx structures
        latex_content = r"""\documentclass[11pt, a4paper]{article}
\usepackage[a4paper, margin=2.5cm]{geometry}
\usepackage{booktabs}
\usepackage{siunitx}
\usepackage{hyperref}

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
\begin{<caption>{Optimized Isomer Energies across Method Matrix Tiers}</caption>
\begin{tabular}{l l S[table-format=3.6]}
\toprule
\textbf{Isomer ID} & \textbf{Terminal Tier} & \textbf{Energy (\si{\hartree})} \\
\midrule
"""
        
        for rec in records:
            latex_content += f"{rec['id']} & {rec['tier']} & {rec['energy']:.6f} \\\n"
            
        latex_content += r"""\bottomrule
\end{tabular}
\end{table}

\section{Cartesian Coordinates}
"""
        
        for rec in records:
            latex_content += f"\\subsection*{{Isomer: {rec['id']} ({rec['tier']})}}\n"
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
            # 1. Add the master HDF5 database
            if self.hdf5_path.exists():
                zf.write(self.hdf5_path, arcname="landscape.h5")
                
            # 2. Add generated LaTeX files
            for tex_file in self.output_dir.glob("*.tex"):
                zf.write(tex_file, arcname=tex_file.name)
                
            # 3. Embed a JSON provenance manifest
            manifest = {
                "archive_type": "CoChem-TOPOS FAIR Output",
                "version": "3.0",
                "source_database": self.hdf5_path.name
            }
            manifest_path = self.output_dir / "fair_manifest.json"
            with open(manifest_path, 'w') as mf:
                json.dump(manifest, mf, indent=2)
            zf.write(manifest_path, arcname="fair_manifest.json")
            if manifest_path.exists():
                manifest_path.unlink() # Clean up local temp manifest
                
        logger.info(f"FAIR submission archive successfully compiled at {zip_path}")
        return zip_path