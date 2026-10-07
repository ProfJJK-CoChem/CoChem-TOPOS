# TOPOS 0.1.0 — Scientific and technical reference register

**Review date:** 2026-10-06, America/Chicago. **Applies to:** the [TOPOS 0.1.0 SRS](CoChem-TOPOS_SRS.md). This register distinguishes retrieved documentation/source text from bibliographic verification of scientific publications.

The review retrieved official author/project repositories and documentation source files over HTTPS. DOI metadata was checked against those maintained bibliographies; the associated journal articles were **not** retrieved or reviewed in full. Direct requests to `doi.org`, the CREST documentation site, and the FACCTs ORCA manual host were denied by the review environment's proxy. Links to those destinations remain useful citations, but do not imply successful access. Official documentation source was available through GitHub. Scientific conclusions below are limited accordingly; unresolved engine-specific syntax or numerical acceptance limits still require verification against the deployed engine's documentation and benchmarks.

The `main`/`master` links below are **living upstream branch snapshots**, retrieved on the review date, not immutable revisions and not a pin of the final engine/model used by TOPOS. A scientific run must record its tested software, model artifact, parameterization, configuration and method-matrix revision separately. Upstream documentation and a citation do not establish that a TOPOS feature is implemented or scientifically validated. Project council resolutions document local decisions and historical receipts; they are not substitutes for primary scientific references or new execution evidence.

<a id="s01"></a>
## S01 — GFN2-xTB, GFN-FF and implicit solvation

**Bibliographic metadata verified in the official xTB bibliography:**

- Bannwarth, C.; Ehlert, S.; Grimme, S. “GFN2-xTB—An Accurate and Broadly Parametrized Self-Consistent Tight-Binding Quantum Chemical Method with Multipole Electrostatics and Density-Dependent Dispersion Contributions.” *Journal of Chemical Theory and Computation* **2019**, 15, 1652–1671. DOI: [10.1021/acs.jctc.8b01176](https://doi.org/10.1021/acs.jctc.8b01176).
- Spicher, S.; Grimme, S. “Robust Atomistic Modeling of Materials, Organometallic, and Biochemical Systems.” *Angewandte Chemie International Edition* **2020**, 59, 15665–15673. DOI: [10.1002/anie.202004239](https://doi.org/10.1002/anie.202004239). This is the GFN-FF reference.
- Ehlert, S.; Stahn, M.; Spicher, S.; Grimme, S. “Robust and Efficient Implicit Solvation Model for Fast Semiempirical Methods.” *Journal of Chemical Theory and Computation* **2021**, 17, 4250–4261. DOI: [10.1021/acs.jctc.1c00471](https://doi.org/10.1021/acs.jctc.1c00471).

**Retrieved sources:** [xTB reference list](https://raw.githubusercontent.com/grimme-lab/xtb/main/assets/references.bib) and [xTB README](https://raw.githubusercontent.com/grimme-lab/xtb/main/README.md). These files were read; the cited journal full texts were not.

**Supports and limits:** distinguish the semiempirical GFN2-xTB Hamiltonian, GFN-FF force field and chosen solvent model in configuration/provenance. They are different models, not interchangeable names for “fast quantum chemistry.” Record the actual engine and method; an empirical Lennard-Jones calculation is not a GFN2-xTB result. Broad parameterization does not establish quantitative accuracy for every element, charge, spin or weak-binding problem. The presence of native dispersion does not independently validate helium-dimer binding or make ALPB identical to an ORCA solvent model. Cite solvation references only when the corresponding model is used.

<a id="s02"></a>
## S02 — CREST method and program papers

**Bibliographic metadata verified in the official CREST README:**

- Pracht, P.; Bohle, F.; Grimme, S. “Automated Exploration of the Low-Energy Chemical Space with Fast Quantum Chemical Methods.” *Physical Chemistry Chemical Physics* **2020**, 22, 7169–7192. DOI: [10.1039/C9CP06869D](https://doi.org/10.1039/C9CP06869D).
- Pracht, P.; et al. “CREST—A Program for the Exploration of Low-Energy Molecular Chemical Space.” *Journal of Chemical Physics* **2024**, 160, 114110. DOI: [10.1063/5.0197592](https://doi.org/10.1063/5.0197592). This is the current program reference listed by the inspected project documentation.
- Grimme, S. “Exploration of Chemical Compound, Conformer, and Reaction Space with Meta-Dynamics Simulations Based on Tight-Binding Quantum Chemical Calculations.” *Journal of Chemical Theory and Computation* **2019**, 15, 2847–2862. DOI: [10.1021/acs.jctc.9b00143](https://doi.org/10.1021/acs.jctc.9b00143). The volume is taken from the README's BibTeX entry; its prose citation contains a typographical `155`.

**Retrieved source:** [CREST README, overview and bibliography](https://raw.githubusercontent.com/crest-lab/crest/master/README.md). Journal full texts were not retrieved.

**Supports and limits:** CREST explores and analyzes structural ensembles and schedules underlying efficient potential evaluations. Cite the applicable sampling/program paper and the potential actually used. Independent search seeds and additional sampling methods provide evidence of discovery robustness, not a proof of exhaustive conformational coverage or an independent validation of the shared Hamiltonian. A time budget is not a statistical convergence criterion.

<a id="s03"></a>
## S03 — CREST keyword and workflow documentation

**Retrieved sources:** official [keyword data](https://raw.githubusercontent.com/crest-lab/crest-docs/main/_data/keywords.yml), [workflow descriptions](https://raw.githubusercontent.com/crest-lab/crest-docs/main/page/overview/workflows.md) and [keyword documentation source](https://raw.githubusercontent.com/crest-lab/crest-docs/main/page/documentation/keywords.md). These documentation source files were read in full as files; they are not journal articles. Scientific paper metadata is in [S02](#s02) and [S06](#s06).

**Verified option meanings relevant to the SRS:**

- `--ewin` and `--ethr` use kcal/mol; `--rthr` uses ångströms.
- `--bthr` specifies a lower bound for the rotational-constant threshold; the inspected documentation describes dynamic adjustment. It must not be advertised as a fixed spectroscopic-identity tolerance solely from its numerical argument.
- `--noreftopo` disables the initial topology check; `--notopo` disables topology checks in CREGEN. These switches are not equivalent.
- `--nocross` disables genetic z-matrix crossing. `--nci` introduces confinement and modifies metadynamics settings; retain those settings in provenance.
- Entropy workflows have explicit ensemble/entropy growth controls. Wall-clock termination does not imply those controls were satisfied.

**Limits:** current upstream option definitions do not guarantee support or identical defaults in an older installed CREST release. Validate the actual adapter/version, preserve the executed argument array and resolved defaults, and perform TOPOS chemistry checks after optimization even when sampler checks are disabled. No search flag provides a universal completeness guarantee.

<a id="s04"></a>
## S04 — r²SCAN-3c, gCP, D4 and explicit counterpoise

**Bibliographic metadata verified in official gCP/xTB reference lists:**

- Grimme, S.; Hansen, A.; Ehlert, S.; Mewes, J.-M. *Journal of Chemical Physics* **2021**, 154, 064103. DOI: [10.1063/5.0040021](https://doi.org/10.1063/5.0040021). The r²SCAN-3c composite-method reference.
- Kruse, H.; Grimme, S. *Journal of Chemical Physics* **2012**, 136, 154101. DOI: [10.1063/1.3700154](https://doi.org/10.1063/1.3700154). The geometrical counterpoise reference.
- Caldeweyher, E.; et al. *Journal of Chemical Physics* **2019**, 150, 154122. DOI: [10.1063/1.5090222](https://doi.org/10.1063/1.5090222). The charge-dependent D4 dispersion reference.

**Retrieved sources:** [gCP README, supported composite levels and references](https://raw.githubusercontent.com/grimme-lab/gcp/master/README.md), [D4 README](https://raw.githubusercontent.com/dftd4/dftd4/main/README.md), [D4 parameter table](https://raw.githubusercontent.com/dftd4/dftd4/main/assets/parameters.toml), [xTB bibliography](https://raw.githubusercontent.com/grimme-lab/xtb/main/assets/references.bib), [Psi4 composite/gCP documentation](https://raw.githubusercontent.com/psi4/psi4/master/doc/sphinxman/source/gcp.rst), [Psi4 meta-GGA/composite definitions](https://raw.githubusercontent.com/psi4/psi4/master/psi4/driver/procrouting/dft/mgga_functionals.py), and [Psi4 explicit CP/noCP documentation](https://raw.githubusercontent.com/psi4/psi4/master/doc/sphinxman/source/nbody.rst). Documentation/source files were inspected; journal full texts were not retrieved.

**Supports and limits:** r²SCAN-3c is a defined composite with dedicated correction parameters; generic r²SCAN, generic D4 and arbitrary basis substitutions do not recreate it. The inspected Psi4 documentation pairs HF-3c with MINIX and r²SCAN-3c with def2-mTZVPP, with no separate user-selected basis for these composite calls. Do not double-correct an intact composite and retain its unmodified method name. Large finite orbital bases are not automatically BSSE-free, and auxiliary fitting bases are not orbital bases. Explicit fragment counterpoise requires consistent fragment charge/spin, geometry and ghost-basis treatment; Psi4 documentation demonstrates the calculation structure without prescribing a change of TOPOS engine.

For a fixed dimer geometry, define the signed raw and CP interaction energies before reporting a correction. With `ΔEraw = EAB(AB basis) − EA(A basis) − EB(B basis)` and `ΔECP = EAB(AB basis) − EA(AB basis) − EB(AB basis)`, define `δCP = ΔECP − ΔEraw`. The commonly positive correction under variational basis enlargement has the opposite sign from `EA(AB basis) − EA(A basis) + EB(AB basis) − EB(B basis)`. Universal positivity across approximate/nonvariational methods is not asserted. These identities are algebraic definitions; they do not validate a particular calculation.

<a id="s05"></a>
## S05 — Symmetry-aware RMSD and graph hashing

**Bibliographic metadata:** Meli, R.; Biggin, P. C., spyrmsd method paper, DOI [10.1186/s13321-020-00455-2](https://doi.org/10.1186/s13321-020-00455-2), verified in the project's source metadata. NetworkX cites Shervashidze et al., “Weisfeiler–Lehman Graph Kernels,” *Journal of Machine Learning Research* **2011**; its linked paper PDF was not retrieved and no DOI is asserted here.

**Retrieved sources:** [spyrmsd README](https://raw.githubusercontent.com/RMeli/spyrmsd/master/README.md), [spyrmsd citation metadata](https://raw.githubusercontent.com/RMeli/spyrmsd/master/spyrmsd/__init__.py) and [NetworkX graph-hashing implementation/documentation](https://raw.githubusercontent.com/networkx/networkx/main/networkx/algorithms/graph_hashing.py). Documentation/source was inspected; journal full texts were not retrieved.

**Supports and limits:** atom properties, graph correspondence and symmetry-aware permutations matter for coordinate comparison. A graph hash is a candidate lookup aid, not proof of graph or conformer equivalence. A distance histogram discards pair correspondence and is not an RMSD. Rotational constants and ordinary pair distances are reflection-invariant; they alone cannot distinguish enantiomers. Record atom mapping, isotope policy, compared atoms, units, thresholds and allowed transforms. Proper rotation and explicit stereo checks are TOPOS design requirements, not a claim that any default library call automatically meets them.

<a id="s06"></a>
## S06 — GoodVibes, low-frequency treatment and conformational entropy

**Bibliographic metadata verified in maintained project documentation:**

- Luchini, G.; Alegre-Requena, J. V.; Funes-Ardoiz, I.; Paton, R. S. “GoodVibes: Automated Thermochemistry for Heterogeneous Computational Chemistry Data.” *F1000Research* **2020**, 9, 291. DOI: [10.12688/f1000research.22758.1](https://doi.org/10.12688/f1000research.22758.1).
- Grimme's quasi-RRHO reference: DOI [10.1002/chem.201200497](https://doi.org/10.1002/chem.201200497). The alternative Truhlar-group low-frequency treatment cited by GoodVibes has DOI [10.1021/jp205508z](https://doi.org/10.1021/jp205508z). Cite the treatment actually selected.
- Pracht, P.; Grimme, S. “Calculation of Absolute Molecular Entropies and Heat Capacities Made Simple.” *Chemical Science* **2021**, 12, 6551–6568. DOI: [10.1039/D1SC00621E](https://doi.org/10.1039/D1SC00621E).

**Retrieved sources:** [GoodVibes README and references](https://raw.githubusercontent.com/patonlab/GoodVibes/master/README.md), [GoodVibes thermochemistry implementation](https://raw.githubusercontent.com/patonlab/GoodVibes/master/goodvibes/thermo.py), [CREST bibliography](https://raw.githubusercontent.com/crest-lab/crest/master/README.md) and [CREST entropy workflows](https://raw.githubusercontent.com/crest-lab/crest-docs/main/page/overview/workflows.md). Documentation and relevant implementation text were inspected; journal full texts were not retrieved.

**Supports and limits:** low-frequency entropy treatment, frequency scaling, temperature, standard state, solvent and conformer treatment must be explicit. Quasi-RRHO is an approximation, not a structural duplicate detector or a guarantee of accurate weak-complex free energies. A Hessian/stationary-point assessment is still needed for the chosen thermal protocol. Comparable electronic energies yield electronic-energy weights, not automatically Gibbs populations.

For a consistently defined ensemble, `pi ∝ gi exp[−(Gi−Gref)/(RT)]` and `Gensemble = Gref − RT ln Σi gi exp[−(Gi−Gref)/(RT)]`. Degeneracy already represented in `Gi` must not be counted again. Discovery counts are not thermodynamic degeneracies. These are statistical-mechanical definitions supporting the SRS consistency checks; this register does not claim TOPOS has validated their implementation or completed conformational sampling.

**Additional retrieved constrained-frequency sources:** official ASE [thermochemistry implementation](https://gitlab.com/ase/ase/-/blob/master/ase/thermochemistry.py) and [vibrational-data implementation](https://gitlab.com/ase/ase/-/blob/master/ase/vibrations/data.py). The relevant `IdealGasThermo` and `VibrationsData` definitions were inspected. They distinguish whole-molecule ideal-gas assumptions and constraint-consistent Hessians; automatic constraint inference in the inspected vibrational class recognizes limited constraint types, not arbitrary frozen-monomer internal constraints. This supports requiring an explicit allowed subspace and constrained thermal model, not claiming a validated general FMP thermochemistry implementation.

<a id="s07"></a>
## S07 — MACE and AIMNet2 model identity, scope and artifacts

**Bibliographic metadata verified in the authors' repositories:**

- Kovács, D. P.; et al. “MACE-OFF23: Transferable Machine Learning Force Fields for Organic Molecules.” Preprint identifier [arXiv:2312.15211](https://arxiv.org/abs/2312.15211). The author repository establishes this identifier/title; no journal DOI is asserted in this register.
- Anstine, D. M.; Zubatyuk, R.; Isayev, O. “AIMNet2: A Neural Network Potential to Meet Your Neutral, Charged, Organic, and Elemental-Organic Needs.” *Chemical Science* **2025**, 16, 10228–10244. DOI: [10.1039/D4SC08572H](https://doi.org/10.1039/D4SC08572H).

**Retrieved sources:** [MACE-OFF README](https://raw.githubusercontent.com/ACEsuit/mace-off/main/README.md), [MACE README/model table](https://raw.githubusercontent.com/ACEsuit/mace/main/README.md), [MACE foundation-model loader](https://raw.githubusercontent.com/ACEsuit/mace/main/mace/calculators/foundations_models.py), [AIMNet2 legacy repository README](https://raw.githubusercontent.com/isayevlab/AIMNet2/main/README.md), [AIMNet Central README](https://raw.githubusercontent.com/isayevlab/aimnetcentral/main/README.md) and [AIMNet model guide](https://raw.githubusercontent.com/isayevlab/aimnetcentral/main/docs/models/guide.md). These source/documentation files were retrieved; the preprint/journal full texts were not.

**Supports and limits:** the inspected public MACE sources document `MACE-OFF23` and `mace_off`, not sufficient verification of a repository-specific `MACE-OFF24m` artifact/API. This does not establish that a privately supplied model cannot exist. The inspected MACE table associates OFF23 weights with an Academic Software License; code and weights can have different terms. AIMNet has distinct model families with different element/charge/spin/reactivity/solvent scope. A base-model paper does not validate every later checkpoint.

Require artifact URI/hash/version, model family, training/reference method, supported chemistry, units, device/dtype and license for the actual selected artifact. GPU availability is not chemical applicability. Model disagreement is an empirical warning, not a calibrated uncertainty interval without independent calibration. Current loaders or model tables do not prove compatibility with TOPOS's installed versions.

<a id="s08"></a>
## S08 — HDF5/h5py SWMR and MPI persistence

**Retrieved sources:** official h5py [Single Writer Multiple Reader documentation](https://raw.githubusercontent.com/h5py/h5py/master/docs/swmr.rst) and [Parallel HDF5 documentation](https://raw.githubusercontent.com/h5py/h5py/master/docs/mpi.rst). Complete documentation source files were retrieved and the relevant constraints reviewed. These are software documentation citations; no journal DOI is asserted.

**Supports and limits:** SWMR requires one writer, compatible HDF5/file format, precreated groups/datasets, writer flush and reader refresh, and suitable filesystem I/O semantics. New groups/datasets cannot be created after entering SWMR mode. `libver='latest'` and an external lock do not by themselves activate SWMR or establish a correct reader protocol. MPI parallel HDF5 is a separate capability requiring MPI-enabled HDF5/h5py and collective-operation discipline; it is not ordinary multiple processes opening a file for writes.

A readable HDF5 file after writer failure is not proof that every TOPOS result or a multi-file workflow transaction completed durably. Define completion markers, artifact checksums, ownership and recovery tests independently. An implementation's “SWMR” docstring is not runtime evidence, and copying a backup into a memmap has workload-dependent recovery time.

<a id="s09"></a>
## S09 — RO-Crate and CodeMeta

**Retrieved RO-Crate 1.1 specification source:** [overview](https://raw.githubusercontent.com/ResearchObject/ro-crate/master/docs/_specification/1.1/index.md), [metadata](https://raw.githubusercontent.com/ResearchObject/ro-crate/master/docs/_specification/1.1/metadata.md), [root data entity](https://raw.githubusercontent.com/ResearchObject/ro-crate/master/docs/_specification/1.1/root-data-entity.md) and [contextual entities](https://raw.githubusercontent.com/ResearchObject/ro-crate/master/docs/_specification/1.1/contextual-entities.md). Canonical specification URI recorded in the retrieved text: [RO-Crate 1.1](https://w3id.org/ro/crate/1.1). These are specification source documents, not reviewed journal full texts. Version 1.1 is a potential interoperability target, not a claim that it is the latest release.

**Retrieved CodeMeta source:** [official README, schema versions and citation metadata](https://raw.githubusercontent.com/codemeta/codemeta/master/README.md). Its bibliographic record includes Jones, M. B.; et al., *CodeMeta: an exchange schema for software metadata*, version 2.0 (**2017**), DOI [10.5063/schema/codemeta-2.0](https://doi.org/10.5063/schema/codemeta-2.0), and version 3.0 (**2023**) with persistent URI [https://w3id.org/codemeta/3.0](https://w3id.org/codemeta/3.0). The README also lists newer schema versions; select a tested target explicitly rather than assuming these are latest. DOI metadata is verified from the repository, not a retrieved journal article.

**Supports and limits:** RO-Crate organizes linked dataset/software/person/file metadata; a valid base RO-Crate is explicitly not necessarily an exhaustive inventory of every payload. TOPOS must require its own complete file/hash manifest if completeness is needed. CodeMeta describes software metadata and does not replace per-calculation chemical provenance. Optional metadata formats should derive from one authoritative run/release record to avoid drift. Neither format provides scientific validation or a generic “FAIR certification.”

<a id="s10"></a>
## S10 — Citation File Format

**Retrieved sources:** official [Citation File Format README](https://raw.githubusercontent.com/citation-file-format/citation-file-format/main/README.md) and [schema guide version 1.2.0](https://raw.githubusercontent.com/citation-file-format/citation-file-format/main/schema-guide.md). Complete source files were retrieved; relevant citation/version fields were reviewed. The README identifies the CFF project through DOI [10.5281/zenodo.1003149](https://doi.org/10.5281/zenodo.1003149); this is repository/software citation metadata, not a reviewed journal paper.

**Supports and limits:** `CITATION.cff` carries authors, title, version/date/commit and identifiers. An optional `preferred-citation` can identify an associated paper while root metadata still describes the software. Examples distinguish an exact archived version from the collection of all versions. Cite the actual software/data version supporting a reported result, and do not fill missing release dates, authorship or DOIs with invented values. Schema-valid citation metadata does not establish that a software release or its scientific results were validated.

<a id="s11"></a>
## S11 — Zenodo draft, publication and version identity

**Retrieved sources:** official developer documentation for [deposition representation](https://raw.githubusercontent.com/zenodo/developers.zenodo.org/master/source/includes/resources/deposit/_representation.md) and [new-version action](https://raw.githubusercontent.com/zenodo/developers.zenodo.org/master/source/includes/resources/deposit-actions/_newversion.md). Complete documentation source files were retrieved and relevant lifecycle fields reviewed. No journal publication or additional DOI is asserted for these API documentation pages.

**Supports and limits:** reserving a DOI does not register/publish the deposition; the documentation states registration occurs on publication. A new version begins as an unpublished snapshot with modifiable files. The new-version action uses the latest version's identifier rather than the global identifier representing all versions. In combination with [CFF's versioned-citation examples](#s10), this supports storing exact-version and all-version identifiers in distinct fields and citing the exact archived release for reproducibility.

Local bundle validation, optional remote draft creation and final public publication must have separate states and evidence. A network request or reserved identifier is not proof of publication. Validate the API contract actually used by an implemented adapter: these documented deposition endpoints do not guarantee every later API behaves identically. This documentation task performs no deposit, reservation or publication.

<a id="s12"></a>
## S12 — Transition-state theory and kinetic interpretation

**Retrieved source:** the official RMG-Py [reaction implementation](https://raw.githubusercontent.com/ReactionMechanismGenerator/RMG-Py/main/rmgpy/reaction.py), especially `Reaction.calculate_tst_rate_coefficient`. The source file was retrieved and the relevant method/docstring reviewed. It specifies a temperature-dependent TST prefactor, transition-state/reactant partition functions, activation energy and tunneling factor. The original Eyring paper was neither retrieved nor bibliographically verified for this review, so no historical-paper DOI is asserted.

**Supports and limits:** in a simple unimolecular free-energy formulation, `k(T) = κ(T) kBT/h exp[−ΔG‡/(RT)]`; observable averaging depends on a declared timescale, for example through `k τobs`. These are model-dependent quantities. An electronic NEB maximum is not automatically an activation free energy or a validated first-order saddle. A barrier comparison with `kBT` alone does not establish kinetic or structural equivalence. Keep distinct structures and optional kinetic edges separate; a rate model requires its own chemical assumptions and validation.

<a id="s13"></a>
## S13 — Physical constants, isotopes and numerical precision

**Retrieved sources:** official SciPy [`constants` documentation source](https://raw.githubusercontent.com/scipy/scipy/main/scipy/constants/__init__.py) and [CODATA implementation/data](https://raw.githubusercontent.com/scipy/scipy/main/scipy/constants/_codata.py); official Mendeleev [model definitions](https://raw.githubusercontent.com/lmmentel/mendeleev/master/mendeleev/models.py), [data documentation](https://raw.githubusercontent.com/lmmentel/mendeleev/master/docs/source/data.rst) and [README](https://raw.githubusercontent.com/lmmentel/mendeleev/master/README.md). These complete source files were retrieved and relevant fields/documentation inspected. The SciPy text identifies the **2022 CODATA recommended values** and links [NIST's constants resource](https://physics.nist.gov/cuu/Constants/); this review does not claim to have retrieved that NIST page or a CODATA journal article. No unverified publication DOI is supplied.

**Verified distinctions:** SciPy's `physical_constants` stores `(value, unit, uncertainty)`; a value defined exactly in the underlying standard can still incur floating-point representation error. The inspected SciPy branch uses CODATA 2022, but the installed SciPy release must be recorded rather than assumed to share that dataset. Mendeleev's `Element.mass` is an alias of `atomic_weight`; isotope records separately store `mass`, `mass_number` and `mass_uncertainty`. Its `Element.isotope(mass_number)` searches records by mass number, while `isotopes` is a relationship collection rather than an integer-mass-number keyed table.

**Supports and limits:** standard atomic weight is not an exact isotope-specific mass. Resolve the intended isotopologue explicitly for inertia, rotational constants, isotope shifts and nuclear-motion calculations; record data source/version and units. Validate the lookup API of the installed Mendeleev release, with a field-based lookup if required. Do not index a list by mass number or label a natural-abundance standard atomic weight as the exact mass of a particular isotope. This register does not verify any numerical helium benchmark from local historical council text.

**Additional retrieved precision source:** official [JAX configuration implementation](https://raw.githubusercontent.com/jax-ml/jax/main/jax/_src/config.py) defines `jax_enable_x64` with default `False` and includes it in tracing/JIT state. This supports configuring and checking precision before relevant arrays/compilation, not a requirement that configuration occupy literal source line 1 or a claim that all float32 calculations fail.

## Explicit reference gaps

The original SRS names ORCA GOAT, ABCluster, MolSym, a Fraser force-constant benchmark, and spectroscopic accuracy/product targets without sufficient primary bibliographic or benchmark detail for this review to verify every claim. Exact GOAT/ABCluster papers and the system-specific Fraser/spectroscopy references remain unverified here; no guessed DOI or universal accuracy claim is supplied. Engine syntax and the complete v4.1/v4.2 purpose/time/hardware matrix require their actual versioned sources. These gaps do not license substitutions or invented evidence.
