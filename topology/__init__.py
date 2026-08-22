"""
CoChem-TOPOS Topology Package.
Provides graph-based molecular connectivity, resonance protection scaling,
non-covalent complex cleavage, and conformer deduplication funnel.
"""

from topology.cochem_topos_crusher import (
    ConformerCandidate,
    CRESTConformerEngine,
    DeduplicationRecord,
    DeduplicationVerdict,
    DipoleMoment,
    EnsembleDeduplicationReport,
    GOATConformerEngine,
    KDTreeCoordinateFilter,
    MassWeightedEckartRMSD,
    RotationalConstants,
    RotationalSieve,
    TopologyCrusher,
    ToposCrusher,
    align_to_eckart_frame,
    compute_dipole_moment,
    compute_mass_weighted_eckart_rmsd,
    compute_rotational_constants,
    is_enantiomer_pair,
)
from topology.cochem_topos_graph import (
    COVALENT_RADII,
    RESONANCE_PROTECTION_SCALE,
    MonomerSeed,
    TopologyAnalysisResult,
    TopologyGraphEngine,
    analyze_molecular_graph,
    generate_chemical_formula,
    get_covalent_radius,
    parse_xyz_file,
    parse_xyz_string,
)

__all__ = [
    # Graph Engine exports
    "TopologyGraphEngine",
    "TopologyAnalysisResult",
    "MonomerSeed",
    "analyze_molecular_graph",
    "parse_xyz_string",
    "parse_xyz_file",
    "generate_chemical_formula",
    "get_covalent_radius",
    "COVALENT_RADII",
    "RESONANCE_PROTECTION_SCALE",
    # Deduplication Crusher exports
    "TopologyCrusher",
    "ToposCrusher",
    "RotationalSieve",
    "KDTreeCoordinateFilter",
    "MassWeightedEckartRMSD",
    "GOATConformerEngine",
    "CRESTConformerEngine",
    "ConformerCandidate",
    "RotationalConstants",
    "DipoleMoment",
    "DeduplicationVerdict",
    "DeduplicationRecord",
    "EnsembleDeduplicationReport",
    "compute_rotational_constants",
    "compute_dipole_moment",
    "align_to_eckart_frame",
    "compute_mass_weighted_eckart_rmsd",
    "is_enantiomer_pair",
]
