"""Versioned numerical profiles and explicit engine/resource admission checks."""

from __future__ import annotations

import os
import platform
import shutil
from typing import Any

import psutil

from .config import SystemConfig
from .models import RunRequest

PROFILE_REVISION = "topos-0.1.0-supported-profile-v1"
PROFILES = {
    "screening-v1": {"engine": "xtb", "convergence": "native normal", "purpose": "screening"},
    "xtb-tight-v1": {"engine": "xtb", "convergence": "native tight", "purpose": "screening"},
    "xtb-vtight-v1": {"engine": "xtb", "convergence": "native vtight", "purpose": "screening"},
    "xtb-extreme-v1": {"engine": "xtb", "convergence": "native extreme", "purpose": "stationary derivative reference"},
    "orca-mapping-v4.1": {
        "engine": "orca",
        "convergence": "mapping-v4.1 explicit thresholds",
        "purpose": "refinement",
        "source": ".docs/method_matrix.md",
    },
}


def capability_report() -> dict[str, Any]:
    """Report discovery, not engine validation or successful execution."""
    from . import __version__
    from .base_integration import inspect_ecosystem
    from .method_matrix import load_catalog

    catalog = load_catalog()

    return {
        "software": "CoChem-TOPOS",
        "version": __version__,
        "schema_version": "topos/0.1.0",
        "profile_revision": PROFILE_REVISION,
        "full_method_matrix": {
            "revision": catalog.revision, "source_sha256": catalog.source_sha256,
            "rows": len(catalog.rows),
            "owner_counts": {owner: sum(row.owner == owner for row in catalog.rows) for owner in ("TOPOS", "TORQ")},
            "execution": "Use matrix planning for exact prerequisites; catalog membership does not establish an executable route.",
        },
        "mandatory_ecosystem": inspect_ecosystem().to_dict(),
        "profiles": PROFILES,
        "engines": {
            name: {
                "executable_discovered": bool(
                    os.environ.get(f"TOPOS_{name.upper()}_EXECUTABLE") or shutil.which(name)
                ),
                "methods": methods,
                "device": "cpu",
                "validation": "verify per execution",
            }
            for name, methods in {
                "xtb": ["GFN2-xTB"],
                "orca": ["HF-3c", "r2SCAN-3c", "HF", "wB97X-V", "wB97M-V", "B3LYP-D4"],
            }.items()
        },
        "supported_operations": ["energy", "gradient", "optimize", "search", "frequency", "thermochemistry", "association", "matrix"],
        "search_algorithm": "seeded Cartesian or rigid-fragment jiggle–quench",
        "search_algorithms": ["jiggle-quench", "crest", "union"],
        "samplers": {
            "crest": {
                "version": "3.0.2",
                "potential": "external xTB 6.7.1 GFN2-xTB",
                "profiles": ["crest-imtdgc-v1", "crest-mquick-v1", "crest-nci-v1"],
                "nci": "explicit confinement for declared multifragment inputs; common-level unconfined refinement",
                "seed": "engine-controlled; no numeric seed support",
                "isotope_labelled_dynamics": "unsupported",
            },
            "goat": {
                "version": "ORCA 6.1.1",
                "interface": "explicit matrix recipes",
                "potential": "native r2SCAN-3c or externally audited xTB; explicit ExtOpt model manifest where selected",
                "refinement": "search ensembles require common-level refinement and TOPOS deduplication",
                "availability": "requires BASE-authorized ORCA and every selected potential backend",
            },
        },
        "conditional_adapters": {
            "ML": {"backends": ["mace", "aimnet2"], "devices": ["cpu", "gpu"],
                   "requirements": "explicit checkpoint hashes/domain/head, audited isolated BASE interpreter, actual device and VRAM",
                   "evidence_scope": "model inference; uncalibrated committee spread is not DFT accuracy"},
            "CFOUR": {"interface": "typed external_protocol in matrix requests",
                      "requirements": "licensed exact native version, GENBAS hash and BASE executable authority"},
            "Psi4": {"method": "SAPT2+3", "requirements": "explicit orbital/fitting bases, actual BASE-audited native installation"},
            "native_analytic_Hessian": {"engine": "ORCA 6.1.1", "requirements": "supported SCF method, physical .hess and separate stationarity gradient"},
            "native_VPT2": {"engine": "ORCA 6.1.1", "interface": "topos.anharmonic",
                            "requirements": "unconstrained nonlinear semirigid minimum; not a frozen-monomer R2 force field"},
        },
        "execution_environment": {
            "local": "Linux through the verified BASE registry and subprocess broker",
            "github-actions": "Private default-branch TOPOS worker provisioned by BASE; requires configured credentials and deployed workflow",
            "development": "Explicit numerical regression runtime, excluded from mandatory ecosystem acceptance",
        },
        "platform": {
            "system": platform.system(),
            "cpu_count": os.cpu_count(),
            "available_memory_mb": psutil.virtual_memory().available // (1024 * 1024),
        },
        "conditional_unverified": [
            "ORCA 6.1.1 integration without installed licensed executable",
            "TOPOS request-correlated GitHub Actions execution requires a separately recorded live acceptance run",
            "TORQ consumer readiness is distinct from mandatory package installation",
        ],
        "unavailable": [
            "native Windows/macOS engine execution",
            "HPC scheduler transport",
            "ABCluster native adapter",
            "Molpro F12 and MPQC native adapters",
            "frozen-monomer R2 VPT2 force field",
            "automatic kinetic grouping",
            "automatic journal or repository deposition",
        ],
        "separate_module_requirements": [
            "DVR and other TORQ-owned matrix algorithms require implemented TORQ consumers",
        ],
        "scientific_limits": [
            "Finite search does not establish completeness.",
            "Electronic-energy weights are not Gibbs populations.",
            "Numerical convergence does not establish method accuracy.",
            "Frozen monomer refinement validates only the allowed subspace.",
        ],
        "deduplication": {
            "profile": "topos-conservative-generation-v1",
            "source": "wiki/Method_Matrix.md Appendix A.1; SRS chapters 6–7",
            "criteria": "compatible protocol/state AND electronic energy AND equilibrium rotational constants AND proper-rotation graph-mapped RMSD",
            "energy_kcal_mol": 0.05,
            "rotational_fraction": 0.01,
            "rmsd_angstrom": 0.125,
            "limits": "fixed conservative rotational screen; not native CREGEN adaptive thresholds or spectroscopic identity",
        },
    }


def validate_route(request: RunRequest, config: SystemConfig) -> tuple[str, str] | None:
    """Return an explicit unsupported/unavailable outcome before spawning an engine."""
    if request.calculation_environment != "local":
        return (
            "unavailable",
            "This installation supports local execution; remote correlation, retrieval and cancellation are not validated.",
        )
    if platform.system() != "Linux":
        return (
            "unsupported",
            "Bounded local engine execution requires Linux; portable data tools remain available.",
        )
    ml_gpu_request = (request.device == "gpu" and request.purpose == "matrix"
                      and request.matrix_row_id in {"T1-30min", "T1-1w", "T2-1min", "T5-1min"}
                      and isinstance(request.matrix_inputs.get("ml_model"), dict))
    if request.device != "cpu" and not ml_gpu_request:
        return (
            "unsupported",
            "These engine adapters support CPU execution; GPU presence does not enable a different Hamiltonian.",
        )
    from .method_matrix import MATRIX_REVISION, resolve_row, validate_request_matrix

    if request.matrix_revision not in {PROFILE_REVISION, MATRIX_REVISION}:
        return (
            "unsupported",
            "Unknown matrix revision; import and validate its route definitions before use.",
        )
    if request.purpose == "matrix":
        if not request.matrix_row_id:
            return "unsupported", "A matrix campaign requires an explicit matrix_row_id."
        try:
            resolve_row(request.matrix_row_id, product=request.matrix_product)
        except ValueError as exc:
            return "unsupported", str(exc)
    else:
        problem = validate_request_matrix(request)
        if problem:
            return problem
    profile = PROFILES.get(request.profile_id)
    if request.purpose != "matrix" and (profile is None or profile["engine"] != request.engine):
        return "unsupported", "Select an explicit numerical profile matching the requested engine."
    if request.purpose not in {"energy", "gradient", "optimize", "search", "frequency", "thermochemistry", "association", "matrix"}:
        return "unsupported", "Requested scientific purpose has no validated adapter."
    if request.purpose not in {"search", "association", "matrix"} and request.search_algorithm != "jiggle-quench":
        return "unsupported", "A sampler selection applies only to the search purpose."
    if request.search_algorithm in {"crest", "union"} and (
        request.engine != "xtb" or request.method != "GFN2-xTB" or request.constraints
    ):
        return (
            "unsupported",
            "CREST routes require explicit unconstrained GFN2-xTB; no potential/constraint substitution is permitted.",
        )
    if request.engine not in {"xtb", "orca"}:
        return "unsupported", "Requested engine has no validated adapter."
    if request.threads > min(config.max_threads, os.cpu_count() or 1):
        return "unavailable", "Requested threads exceed the configured or detected CPU allocation."
    available_mb = psutil.virtual_memory().available // (1024 * 1024)
    memory_limit = min(available_mb, config.max_memory_mb or available_mb)
    if request.memory_mb > memory_limit:
        return "unavailable", "Requested engine memory exceeds available or configured memory."
    if request.molecule.environment:
        if any(
            key not in {"phase", "solvent", "chirality"} for key in request.molecule.environment
        ):
            return "unsupported", "Environment contains unsupported physical conditions."
        if request.molecule.environment.get("phase", "gas") != "gas":
            return (
                "unsupported",
                "Only isolated gas-phase geometry execution is validated by this profile.",
            )
        if request.molecule.environment.get("solvent"):
            return (
                "unsupported",
                "Solvated profiles require an explicit validated engine-specific model.",
            )
    if request.solvent:
        return (
            "unsupported",
            "Solvated profiles are unavailable until engine-specific solvent configuration is validated.",
        )
    return None
