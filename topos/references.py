"""Execution-aware scientific credit; bibliographic presence is not validation."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

XTB_BIBLIOGRAPHY = "https://github.com/grimme-lab/xtb/blob/main/assets/references.bib"
GCP_BIBLIOGRAPHY = "https://github.com/grimme-lab/gcp/blob/master/README.md"
BASIS_BIBLIOGRAPHY = "https://github.com/MolSSI-BSE/basis_set_exchange/blob/master/basis_set_exchange/data/REFERENCES.json"

METHOD_REFERENCES = {
    "GFN0-xTB": {
        "title": "A Robust Non-Self-Consistent Tight-Binding Quantum Chemistry Method for large Molecules",
        "authors": ["Philipp Pracht", "Eike Caldeweyher", "Sebastian Ehlert", "Stefan Grimme"],
        "year": 2019, "doi": "10.26434/chemrxiv.8326202.v1", "kind": "preprint-method",
        "source": XTB_BIBLIOGRAPHY,
    },
    "GFN1-xTB": {
        "title": "A robust and accurate tight-binding quantum chemical method for structures, vibrational frequencies, and noncovalent interactions of large molecular systems parametrized for all spd-block elements (Z=1–86)",
        "authors": ["Stefan Grimme", "Christoph Bannwarth", "Philip Shushkov"],
        "year": 2017, "doi": "10.1021/acs.jctc.7b00118", "source": XTB_BIBLIOGRAPHY,
    },
    "GFN2-xTB": {
        "title": "GFN2-xTB—An Accurate and Broadly Parametrized Self-Consistent Tight-Binding Quantum Chemical Method with Multipole Electrostatics and Density-Dependent Dispersion Contributions",
        "authors": ["Christoph Bannwarth", "Sebastian Ehlert", "Stefan Grimme"],
        "year": 2019, "doi": "10.1021/acs.jctc.8b01176", "source": XTB_BIBLIOGRAPHY,
    },
    "GFN-FF": {
        "title": "Robust Atomistic Modeling of Materials, Organometallic, and Biochemical Systems",
        "authors": ["Sebastian Spicher", "Stefan Grimme"], "year": 2020,
        "doi": "10.1002/anie.202004239", "source": XTB_BIBLIOGRAPHY,
    },
    "HF-3c": {
        "title": "Corrected small basis set Hartree-Fock method for large systems",
        "authors": ["Rebecca Sure", "Stefan Grimme"], "year": 2013,
        "doi": "10.1002/jcc.23317", "source": GCP_BIBLIOGRAPHY,
    },
    "r2SCAN-3c": {
        "title": "r²SCAN-3c: A 'Swiss army knife' composite electronic-structure method",
        "authors": ["Stefan Grimme", "Andreas Hansen", "Sebastian Ehlert", "Jan-Michael Mewes"],
        "year": 2021, "doi": "10.1063/5.0040021", "source": GCP_BIBLIOGRAPHY,
    },
    "wB97X-V": {
        "title": "ωB97X-V: A 10-parameter, range-separated hybrid, generalized gradient approximation density functional with nonlocal correlation, designed by a survival-of-the-fittest strategy",
        "authors": ["Narbe Mardirossian", "Martin Head-Gordon"], "year": 2014,
        "doi": "10.1039/C3CP54374A", "journal": "Physical Chemistry Chemical Physics",
        "volume": 16, "pages": "9904–9924",
        "source": "https://github.com/psi4/psi4/blob/master/psi4/driver/procrouting/dft/hyb_functionals.py",
    },
    "wB97M-V": {
        "title": "ωB97M-V: A combinatorially optimized, range-separated hybrid, meta-GGA density functional with VV10 nonlocal correlation",
        "authors": ["Narbe Mardirossian", "Martin Head-Gordon"], "year": 2016,
        "doi": "10.1063/1.4952647", "journal": "Journal of Chemical Physics",
        "volume": 144, "article": "214110",
        "source": "https://github.com/psi4/psi4/blob/master/psi4/driver/procrouting/dft/hyb_functionals.py",
    },
}


def method_references(engine: str, method: str) -> list[dict[str, Any]]:
    """Cite the selected engine/method without claiming it has been executed."""
    references: list[dict[str, Any]] = [{
        "kind": "software", "title": "CoChem-TOPOS", "version": "0.1.0",
        "url": "https://github.com/ProfJJK-CoChem/CoChem-TOPOS", "license": "Apache-2.0",
    }, {
        "kind": "data-software", "title": "Mendeleev",
        "url": "https://mendeleev.readthedocs.io/",
        "role": "versioned element/isotope data; installed version in software provenance",
    }, {
        "kind": "documentation", "title": "SciPy physical constants",
        "url": "https://docs.scipy.org/doc/scipy/reference/constants.html",
        "role": "units/constants; edition and installed version in derived-quantity provenance",
    }]
    engine = engine.lower()
    if engine == "xtb":
        references.extend([{
            "kind": "software", "title": "xTB", "url": "https://github.com/grimme-lab/xtb",
            "license": "LGPL-3.0-or-later", "role": "external executable, not redistributed",
        }, {
            "kind": "peer-reviewed-software", "title": "Extended tight-binding quantum chemistry methods",
            "doi": "10.1002/wcms.1493", "year": 2020, "source": XTB_BIBLIOGRAPHY,
        }])
    elif engine == "orca":
        references.extend([{
            "kind": "software", "title": "ORCA", "url": "https://www.faccts.de/orca/",
            "license": "LicenseRef-ORCA-EULA", "role": "external licensed executable, not redistributed",
        }, {
            "kind": "peer-reviewed-software", "title": "Software Update: The ORCA Program System—Version 6.0",
            "authors": ["Frank Neese"], "journal": "WIREs Computational Molecular Science",
            "volume": 15, "article": "e70019",
            "doi": "10.1002/wcms.70019", "year": 2025,
            "source": "ORCA EULA, June 2025, section 5 (user-supplied license)",
            "role": "ORCA 6 required software citation; exact executed patch version recorded separately",
        }])
    elif engine == "crest":
        references.extend([{
            "kind": "software", "title": "CREST", "url": "https://github.com/crest-lab/crest",
            "role": "external conformer search executable, not redistributed",
        }, {
            "kind": "peer-reviewed-software",
            "title": "CREST—A Program for the Exploration of Low-Energy Molecular Chemical Space",
            "doi": "10.1063/5.0197592", "year": 2024,
            "source": "https://github.com/crest-lab/crest/blob/master/README.md",
        }, {
            "kind": "peer-reviewed-method",
            "title": "Automated Exploration of the Low-Energy Chemical Space with Fast Quantum Chemical Methods",
            "doi": "10.1039/C9CP06869D", "year": 2020,
            "source": "https://github.com/crest-lab/crest/blob/master/README.md",
        }])
    reference = METHOD_REFERENCES.get(method.replace("²", "2"))
    if reference:
        references.append({"kind": "peer-reviewed-method", "method": method, **reference,
                           "verification": "bibliographic metadata in official software bibliography"})
    elif engine != "crest":
        references.append({"kind": "unresolved-reference", "title": method, "method": method,
                           "role": "exact method/basis reference requires author verification"})
    return references


def executed_references(record: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Credit every actually invoked engine, including unsuccessful retained attempts.

    Failed calculations remain labelled with their status. Planned but never
    invoked engines do not acquire an execution claim through request metadata.
    """
    references: dict[str, dict[str, Any]] = {}
    unresolved: set[str] = set()
    for attempt in record.get("attempts", []):
        if attempt.get("metadata", {}).get("execution_kind") != "real" or not attempt.get("command"):
            continue
        engine, method = attempt["engine"], attempt["method"]
        for reference in method_references(engine, method):
            reference = dict(reference)
            key = reference.get("doi", reference.get("url", reference.get("title", "")))
            entry = references.setdefault(key, reference)
            entry.setdefault("executions", []).append({
                "attempt_id": attempt["attempt_id"], "engine": engine,
                "engine_version": attempt.get("engine_version"), "method": method,
                "status": attempt["status"],
            })
            if reference["kind"] == "unresolved-reference":
                unresolved.add(f"Verified scientific method citation not supplied: {method}")
    request = record.get("request", {})
    if request.get("solvent"):
        # The request alone does not identify an engine's actual solvent model.
        unresolved.add("Verify the executed solvent model and its parameterization citation from engine input/output")
    actual_orca = [a["attempt_id"] for a in record.get("attempts", [])
                   if a.get("engine", "").lower() == "orca" and a.get("command")
                   and a.get("metadata", {}).get("execution_kind") == "real"]
    basis_attempts: dict[str, list[str]] = {}
    auxiliary_attempts: dict[str, list[str]] = {}
    for attempt in record.get("attempts", []):
        if attempt.get("attempt_id") not in actual_orca:
            continue
        metadata = attempt.get("metadata", {})
        recipe = metadata.get("requested_method", {})
        basis = recipe.get("basis") or request.get("basis")
        auxiliary = recipe.get("auxiliary_basis") or metadata.get("resolved_auxiliary_basis") or request.get("auxiliary_basis")
        if basis:
            basis_attempts.setdefault(basis, []).append(attempt["attempt_id"])
        if auxiliary:
            auxiliary_attempts.setdefault(auxiliary, []).append(attempt["attempt_id"])
    for basis, attempt_ids in basis_attempts.items():
        if basis in {"def2-SVP", "def2-SV(P)", "def2-TZVP", "def2-TZVPP", "def2-QZVP", "def2-QZVPP"}:
            entry = references.setdefault("10.1039/b508541a", {
                "kind": "peer-reviewed-basis", "bases": [], "attempt_ids": [],
                "title": "Balanced basis sets of split valence, triple zeta valence and quadruple zeta valence quality for H to Rn: Design and assessment of accuracy",
                "authors": ["Florian Weigend", "Reinhart Ahlrichs"], "year": 2005,
                "doi": "10.1039/b508541a", "source": BASIS_BIBLIOGRAPHY,
            })
            entry["bases"].append(basis)
            entry["attempt_ids"].extend(attempt_ids)
        elif basis in {"jun-cc-pVDZ", "jun-cc-pVTZ", "jun-cc-pVQZ", "jul-cc-pVDZ", "jul-cc-pVTZ", "jul-cc-pVQZ"}:
            entry = references.setdefault("10.1021/ct1005533", {
                "kind": "peer-reviewed-basis", "bases": [], "attempt_ids": [],
                "title": "Convergent Partially Augmented Basis Sets for Post-Hartree-Fock Calculations of Molecular Properties and Reaction Barrier Heights",
                "authors": ["Ewa Papajak", "Donald G. Truhlar"], "year": 2011,
                "doi": "10.1021/ct1005533", "source": BASIS_BIBLIOGRAPHY,
            })
            entry["bases"].append(basis)
            entry["attempt_ids"].extend(attempt_ids)
            unresolved.add("Verify underlying correlation-consistent basis references for the actual elements")
        else:
            unresolved.add(f"Verify explicit orbital basis citation from executed input: {basis}")
    for auxiliary, attempt_ids in auxiliary_attempts.items():
        if auxiliary in {"def2/J", "def2-J"}:
            references["10.1039/b515623h"] = {
                "kind": "peer-reviewed-auxiliary-basis", "basis": "def2/J",
                "title": "Accurate Coulomb-fitting basis sets for H to Rn",
                "authors": ["Florian Weigend"], "year": 2006,
                "doi": "10.1039/b515623h", "source": BASIS_BIBLIOGRAPHY,
                "attempt_ids": attempt_ids,
            }
        else:
            unresolved.add(f"Verify auxiliary basis-set citation from executed input: {auxiliary}")
    counterpoise = record.get("metadata", {}).get("matrix_counterpoise", {})
    if (actual_orca and counterpoise.get("status") == "completed"
            and counterpoise.get("validation_status") == "validated-for-protocol"):
        references["ORCA-Boys-Bernardi"] = {
            "kind": "documentation", "title": "ORCA 6.1 manual: Boys–Bernardi Counterpoise Correction",
            "url": "https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/counterpoise.html",
            "role": "Implemented balanced native energy legs and ghost-basis convention; not a complete-basis guarantee",
        }
    symmetry = [c for c in record.get("candidates", [])
                if "MolSym" in c.get("metadata", {}).get("point_group", {}).get("algorithm", "")]
    if symmetry:
        references["MolSym"] = {
            "kind": "software", "title": "MolSym", "license": "MIT",
            "url": "https://github.com/NASymmetry/MolSym",
            "versions": sorted({c["metadata"]["point_group"].get("algorithm_version", "unrecorded") for c in symmetry}),
            "candidate_ids": [c["candidate_id"] for c in symmetry],
        }
        references["10.1063/5.0216738"] = {
            "kind": "peer-reviewed-software", "title": "MolSym software citation",
            "doi": "10.1063/5.0216738",
            "source": "https://github.com/NASymmetry/MolSym/blob/main/README.md",
        }
        references["10.1002/jcc.23493"] = {
            "kind": "peer-reviewed-method", "title": "Algorithms for computer detection of symmetry elements in molecular systems",
            "authors": ["Otávio Beruski", "Luciano N. Vidal"],
            "doi": "10.1002/jcc.23493", "source": "https://github.com/NASymmetry/MolSym/blob/main/molsym/pgdetect/flowchart.py",
        }
    return list(references.values()), sorted(unresolved)
