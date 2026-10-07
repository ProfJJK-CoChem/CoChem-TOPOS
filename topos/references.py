"""Execution-aware scientific credit; bibliographic presence is not validation."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

XTB_BIBLIOGRAPHY = "https://github.com/grimme-lab/xtb/blob/main/assets/references.bib"
GCP_BIBLIOGRAPHY = "https://github.com/grimme-lab/gcp/blob/master/README.md"
BASIS_BIBLIOGRAPHY = "https://github.com/MolSSI-BSE/basis_set_exchange/blob/master/basis_set_exchange/data/REFERENCES.json"

CORRELATED_MANUAL = "https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/mdci.html"
AIMNET_BIBLIOGRAPHY = "https://github.com/isayevlab/aimnetcentral/blob/main/README.md#citation"
MACE_BIBLIOGRAPHY = "https://github.com/ACEsuit/mace/blob/main/README.md#references"

METHOD_REFERENCES = {
    "DLPNO-CCSD(T1)": {
        "title": "Communication: An Improved Linear Scaling Perturbative Triples Correction for the Domain Based Local Pair-Natural Orbital Based Singles and Doubles Coupled Cluster Method [DLPNO-CCSD(T)]",
        "authors": ["Yang Guo", "Christoph Riplinger", "Ute Becker", "Dimitrios G. Liakos", "Yury Minenkov", "Luigi Cavallo", "Frank Neese"],
        "year": 2018, "doi": "10.1063/1.5011798", "source": CORRELATED_MANUAL,
    },
    "B3LYP": {
        "title": "Density-functional thermochemistry. III. The role of exact exchange",
        "authors": ["Axel D. Becke"], "year": 1993, "doi": "10.1063/1.464913",
        "source": "https://doi.org/10.1063/1.464913",
    },
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
    elif engine in {"aimnet2", "mace"}:
        references.append({"kind": "software", "title": "AIMNet2" if engine == "aimnet2" else "MACE",
                           "url": "https://github.com/isayevlab/aimnetcentral" if engine == "aimnet2" else "https://github.com/ACEsuit/mace",
                           "role": "executed model implementation; checkpoint identity and rights are separate"})
        if engine == "aimnet2":
            references.append({"kind": "peer-reviewed-method", "method": method,
                               "title": "AIMNet2: A Neural Network Potential to Meet Your Neutral, Charged, Organic, and Elemental-Organic Needs",
                               "authors": ["Dylan M. Anstine", "Roman Zubatyuk", "Olexandr Isayev"],
                               "year": 2025, "doi": "10.1039/D4SC08572H", "source": AIMNET_BIBLIOGRAPHY,
                               "role": "model architecture; supplied checkpoint family and training Hamiltonian remain explicit"})
        else:
            references.append({"kind": "peer-reviewed-conference-method", "method": method,
                               "title": "MACE: Higher Order Equivariant Message Passing Neural Networks for Fast and Accurate Force Fields",
                               "authors": ["Ilyes Batatia", "David Peter Kovacs", "Gregor N. C. Simm", "Christoph Ortner", "Gabor Csanyi"],
                               "year": 2022, "conference": "Advances in Neural Information Processing Systems",
                               "url": "https://openreview.net/forum?id=YPpSngE-ZU", "source": MACE_BIBLIOGRAPHY})
    elif engine == "cfour":
        references.append({"kind": "software", "title": "CFOUR", "url": "https://cfour.uni-mainz.de/",
                           "role": "executed native software; exact version and GENBAS identity retained in attempt"})
    elif engine == "psi4":
        references.extend([{"kind": "software", "title": "Psi4", "url": "https://github.com/psi4/psi4"},
                           {"kind": "peer-reviewed-software", "title": "Psi4 1.4: Open-source software for high-throughput quantum chemistry",
                            "doi": "10.1063/5.0006002", "year": 2020,
                            "source": "https://github.com/psi4/psi4/blob/master/README.md"}])
    if method == "B3LYP":
        references.append({
            "kind": "peer-reviewed-method", "method": method,
            "title": "Development of the Colle-Salvetti correlation-energy formula into a functional of the electron density",
            "authors": ["Chengteh Lee", "Weitao Yang", "Robert G. Parr"], "year": 1988,
            "doi": "10.1103/PhysRevB.37.785", "source": "https://doi.org/10.1103/PhysRevB.37.785",
        })
    reference = METHOD_REFERENCES.get(method.replace("²", "2"))
    if reference:
        references.append({"kind": "peer-reviewed-method", "method": method, **reference,
                           "verification": "bibliographic metadata in official software bibliography"})
    elif method in {"MP2", "AUTOCI-CCSD(T)", "CCSD(T)", "CCSD", "CCSDT", "CCSD(T)-F12D/RI", "F12-MP2", "F12-RI-MP2", "HF"}:
        references.append({"kind": "documentation", "method": method,
                           "title": f"Native {engine} implementation of {method}",
                           "url": CORRELATED_MANUAL if engine == "orca" else "https://psicode.org/psi4manual/master/cfour.html",
                           "role": "version-specific implementation reference; canonical/local/F12 approximations are distinct"})
    elif engine == "psi4" and method.upper() == "SAPT2+3":
        references.append({"kind": "documentation", "method": method,
                           "title": "Psi4 SAPT: Symmetry-Adapted Perturbation Theory",
                           "url": "https://psicode.org/psi4manual/master/sapt.html"})
    elif engine not in {"crest", "aimnet2", "mace"}:
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
    for attempt in record.get("attempts", []):
        metadata = attempt.get("metadata", {})
        if metadata.get("execution_kind") != "real" or not attempt.get("command"):
            continue
        additions = []
        manifest = metadata.get("manifest") or metadata.get("model_manifest")
        if manifest and manifest.get("backend") in {"aimnet2", "mace"}:
            additions.append({"kind": "model-artifact", "title": manifest["family"],
                              "method": attempt["method"], "backend": manifest["backend"],
                              "manifest_sha256": metadata.get("manifest_sha256"),
                              "members": [{key: member.get(key) for key in ("sha256", "training_run_id", "source")}
                                          for member in manifest.get("members", [])],
                              "training_hamiltonian": manifest.get("training_method"),
                              "license": manifest.get("license_name"), "license_url": manifest.get("license_url"),
                              "domain_reference": manifest.get("domain_reference"),
                              "role": "executed checkpoint provenance; author-supplied domain/license declarations are not independent validation"})
            family = manifest["family"].lower()
            if family == "aimnet2-2025":
                additions.append({"kind": "peer-reviewed-model", "title": "Critical benchmarking of machine-learned interatomic potentials for intermolecular and noncovalent interactions",
                                  "doi": "10.1088/2632-2153/aea39f", "year": 2026, "source": AIMNET_BIBLIOGRAPHY})
            elif family in {"mace-off23", "mace-off23-small", "mace-off23-medium", "mace-off23-large"}:
                additions.append({"kind": "preprint-model", "title": "MACE-OFF23: Transferable Machine Learning Force Fields for Organic Molecules",
                                  "url": "https://arxiv.org/abs/2312.15211", "source": MACE_BIBLIOGRAPHY,
                                  "role": "family-specific source; does not validate a renamed OFF24 checkpoint"})
        if metadata.get("requested_method", {}).get("dispersion") == "D4":
            additions.append({"kind": "peer-reviewed-method", "title": "A generally applicable atomic-charge dependent London dispersion correction",
                              "doi": "10.1063/1.5090222", "year": 2019, "source": "https://doi.org/10.1063/1.5090222"})
        if metadata.get("profile", "").startswith("goat-"):
            additions.append({"kind": "peer-reviewed-method", "title": "The Global Optimizer Algorithm (GOAT)",
                              "doi": "10.1002/anie.202500393", "year": 2025,
                              "source": "https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/goat.html"})
        if metadata.get("profile") == "crest-entropy-v1":
            additions.append({"kind": "peer-reviewed-method", "title": "Calculation of absolute molecular entropies and heat capacities made simple",
                              "authors": ["Philipp Pracht", "Stefan Grimme"], "doi": "10.1039/D1SC00621E", "year": 2021,
                              "source": "https://github.com/crest-lab/crest/blob/v3.0.2/README.md"})
            additions.append({"kind": "peer-reviewed-method", "title": "CREST entropy sampling implementation reference",
                              "authors": ["Jan Gorges", "Stefan Grimme", "Andreas Hansen", "Philipp Pracht"],
                              "journal": "Physical Chemistry Chemical Physics", "volume": 24, "pages": "12249–12259", "year": 2022,
                              "source": "https://github.com/crest-lab/crest/blob/v3.0.2/src/algos/search_entropy.f90"})
        if metadata.get("derivative_kind") == "native-VPT2-analytic-Hessian-differences":
            additions.append({"kind": "documentation", "title": "ORCA 6.1 VPT2/GVPT2 native force-field and spectroscopy protocol",
                              "url": "https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/vpt2.html"})
            additions.append({"kind": "peer-reviewed-method", "title": "Anharmonic vibrational properties of CH2F2: A comparison of theory and experiment",
                              "doi": "10.1063/1.461259", "year": 1991,
                              "source": "native ORCA VPT2 output cites Amos et al., equations 5 and 6"})
        for reference in additions:
            key = reference.get("doi", reference.get("url", reference["title"]))
            if reference["kind"] == "model-artifact":
                key += ":" + str(reference.get("manifest_sha256") or attempt["attempt_id"])
            entry = references.setdefault(key, reference)
            entry.setdefault("attempt_ids", []).append(attempt["attempt_id"])
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
        if (attempt.get("metadata", {}).get("execution_kind") != "real" or not attempt.get("command")
                or attempt.get("engine", "").lower() not in {"orca", "cfour", "psi4"}):
            continue
        metadata = attempt.get("metadata", {})
        recipe = metadata.get("requested_method") or metadata.get("requested_protocol", {})
        basis = recipe.get("basis") or recipe.get("orbital_basis")
        if not basis and attempt.get("engine", "").lower() == "orca":
            basis = request.get("basis")
        auxiliary = recipe.get("auxiliary_basis") or metadata.get("resolved_auxiliary_basis") or request.get("auxiliary_basis")
        if basis:
            basis_attempts.setdefault(basis, []).append(attempt["attempt_id"])
        if auxiliary:
            auxiliary_attempts.setdefault(auxiliary, []).append(attempt["attempt_id"])
        for key in ("auxiliary_scf_basis", "auxiliary_sapt_basis", "cabs_basis", "correlation_auxiliary_basis"):
            if recipe.get(key):
                auxiliary_attempts.setdefault(recipe[key], []).append(attempt["attempt_id"])
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
