# External quantum-chemistry protocols and acceptance boundaries

This records the external-engine work after the 907-test completion receipt.
That earlier receipt does not validate these new files. The executable contract
is [`ExternalProtocol` / `run_external`](../topos/external_engines.py); matrix
registration remains the responsibility of the compiled recipe dispatcher.

## Implemented contracts

**CFOUR:** native RHF-based HF, MP2, CCSD, CCSD(T), and CCSDT electronic energies;
native analytic Cartesian derivatives; explicitly requested first-order
properties; and TOPOS L-BFGS-B optimization driven by successive native CFOUR
derivatives. The outer optimizer is explicitly identified as TOPOS/SciPy, not
the native CFOUR internal-coordinate optimizer. Every derivative evaluation has
its own immutable input, basis library, raw logs, and parsed result. Optimization
requires both declared maximum and RMS Cartesian gradient thresholds. It
establishes stationarity; positive vibrational curvature requires a separate
Hessian calculation. One wall-clock deadline bounds the entire campaign.

The input is Cartesian, with conventional integral handling, an explicit
core choice, RHF reference, charge, CPU memory allocation, SCF/CC thresholds,
and a named basis from the supplied native installation's GENBAS file. The
executable and GENBAS bytes are hashed. GENBAS must occupy a documented native
installation location and contain the exact requested basis for every element.
No arbitrary replacement basis is renamed to satisfy a matrix label.
Full triples explicitly use `CC_PROG=ECC,ABCDTYPE=STANDARD`; the AO algorithm
is only available through CCSD(T). Public CFOUR 2.1 full quadruples additionally
have an energy-only `CC_PROG=NCC,ABCDTYPE=STANDARD` contract. No analytic
CCSDTQ derivative is inferred from availability of its energy method.

Output acceptance requires the exact engine version, complete successful native
subprogram termination, actual SCF and correlated-method convergence, matching
charge/core/reference/basis controls, and the requested correlated total energy.
Analytic gradients require agreement between the native GRD and stdout gradient,
both at the requested geometry. Total dipoles are expressed at the requested
origin, including the charge-dependent translation term. Proper rotations and translations are allowed;
unestablished atom permutations and mirror matches are rejected. Atom IDs,
isotopes, fragment states, and declared bonds remain those of the typed input.
The adapter never treats an intermediate HF/MP2 energy as a CCSD(T) result.

The public T3C-30min/1h/3h/12h/1d recipes bind these inputs to their exact matrix
method/basis/core/operation. T3C-3d additionally orchestrates all five real
optimization components and applies the documented junChS formula in a complete
explicit independent internal-coordinate chart. It requires the Cartesian
optimizer resolution and the explicit same-basis core-valence resolution.
Component energies are retained individually; no composite electronic energy
is invented from a geometry formula. These CFOUR routes still require live
licensed-engine acceptance.

The parameterized `T3C-1w` [higher geometry composite](TOPOS_HIGHER_COMPOSITES.md)
adds all eight explicit CBS/CV/fT/fQ component geometries, checked numerical
energy derivatives for full quadruples, and durable displacement-level
recovery. Its bases, extrapolation exponent, and numerical derivative settings
must be selected explicitly. Separate conditional adapters implement the
[raw/CP geometry bracket](TOPOS_CFOUR_COUNTERPOISE_REVIEW.md) and
[scalar/DBOC month composite with observed native-mass rotors](TOPOS_MONTH_GEOMETRY_BRANCH.md).
These routes require their own native evidence; they cannot borrow an
uncorrected geometry. The month Product A default-isotopologue calculation is
distinct from arbitrary-isotope DBOC campaigns.

**Psi4:** the explicitly selected SAPT2+3 branch, with two balanced closed-shell
monomers, declared orbital/SCF-fitting/SAPT-fitting bases, core treatment,
unaltered geometry, and explicit native API calls. The four native SAPT terms
must sum to the returned interaction energy. SAPT interaction energy is retained
under `native_result.interaction_energy_hartree`; it is deliberately **not**
stored as the system's total electronic energy. SAPT(DFT), GRAC shifts,
ionization-potential determination, and automatic PES exploration are distinct
protocols and are not silently inferred from this branch.

**Molpro/MPQC:** requests remain explicitly unsupported. A named F12 orbital
basis is not an F12 Hamiltonian or proof that an analytic F12 gradient exists.
The MPQC wording in the ORCA-track matrix row must be resolved before choosing
an engine or accepting a method substitution.

Production calls use BASE's audited executable resolution and bounded process
broker. An engine without a valid BASE registration remains unavailable; TOPOS
does not manufacture registry entries or bypass that boundary. The current
BASE schema has CFOUR but does not yet provide Psi4, Molpro, or MPQC engine
registration. A companion patch now adds genuine Psi4 audit and preserves the
launcher, actual compiled core, and interpreter fingerprints through Stage 0
and execution authority. It is supplied separately for BASE integration;
production availability requires applying it and rerunning genuine Stage 0.
A development runner can test an installed engine independently, but that
evidence does not establish production BASE integration.

## Remaining matrix inventory at the start of this work

The following are the exact 27 previously unimplemented TOPOS recipes, grouped
by what their completion actually requires. This is an inventory of original
obligations, not a claim that concurrently developed adapters remain absent.
Use the current `cochem-topos matrix support` output for registration counts.

| Row(s) | Necessary scientific implementation / unresolved choice |
| --- | --- |
| T1-30min, T1-1w; T2-1min; T5-1min | Actual ML model inference, model/version/training/domain evidence and validated force/energy units; T1-1w additionally requires genuine fine-tuning and independent validation. An xTB fallback does not satisfy these rows. |
| T1-1d | Both requested entropy estimators and a stated sampling/convergence contract. A finite run cannot certify complete conformational coverage. |
| T1-1mo | The specified broad GOAT/CREST search, native-version compatibility, diversity and coupled-cluster reranking; each stage needs evidence. |
| T3O-3h | Common-geometry high-level energy, counterpoise, and actual VPT2 corrections with compatible reference/basis and verified derivatives. |
| T3O-12h | Explicit junChS optimized geometry assembled from the specified CCSD(T), MP2 CBS and core-valence contributions. |
| T3O-1d | Conflicting MPQC wording in an ORCA/DLPNO track; requires an explicit scientifically justified resolution rather than executing document text. |
| T3O-3d | Verified AUTOCI CCSD(T) derivatives and the specified conventional orbital basis. An F12 basis label alone does not make this an F12 calculation. |
| T3O-1w | Explicit CBS, core-valence, full-triples and full-quadruples increments, basis choices and geometry parameterization. |
| T3O-1mo | Molpro: exact F12 variant, orbital and auxiliary/CABS bases, core treatment, installed version and verified analytic or explicitly selected numerical gradient strategy. The original generic `DF-CCSD(T)-F12` is insufficient. |
| T3C-30min | Native frozen-core MP2/cc-pVDZ optimization; CFOUR contract above provides energy/gradient/outer-optimization machinery. |
| T3C-1h | Native CCSD(T)/cc-pVTZ single point with requested first-order properties. This is not an optimized geometry. |
| T3C-3h, T3C-12h | Frozen-core CCSD(T) optimization at cc-pVTZ and cc-pVQZ respectively, with actual derivatives and convergence. |
| T3C-1d | All-electron CCSD(T)/cc-pCVQZ optimization, explicitly different from frozen-core treatment. |
| T3C-3d | junChS geometry contributions at a common explicit coordinate parameterization: frozen-core CCSD(T)/jun-cc-pVTZ; frozen-core MP2 jun-TZ/jun-QZ CBS contribution; all-electron minus frozen-core MP2/cc-pwCVTZ core-valence increment. Optimizing each component separately and summing energies is not the requested composite geometry. |
| T3C-1w | CBS+CV+full-triples+full-quadruples geometry composite; increment bases and parameterization must be supplied explicitly. CCSDT alone does not establish a quadruples correction. |
| T3C-1mo | The preceding composite plus an explicit relativistic Hamiltonian (DPT2 or X2C1E as selected), basis and DBOC protocol. Neither correction can be assigned a default zero. |
| T5-30min | Source conflict between r2SCAN-3c's built-in gCP and an additional raw counterpoise instruction; avoid double-counting and require the documented resolution. |
| T5-3h | Actual junChS-F12 interaction-energy components and complete common fragment/reference definitions. |
| T5-12h | Actual DLPNO-CCSD(T1)/TightPNO energy and native LED decomposition, with the required orbital/auxiliary bases. LED interfragment terms are not automatically binding energies. |
| T5-1d | Separate, otherwise identical actual PNO calculations at the two prescribed thresholds and the explicitly requested extrapolation. |
| T5-3d | The exact canonical CCSD(T)-F12 variant, fitting bases and CABS, with complete frozen-fragment interaction-energy calculations. |
| T5-1w | CFOUR CBS+CV+full-triples interaction composite, with explicit increment bases and fragment state/core definitions. |
| T5-1mo | Explicitly chosen SAPT2+3 or SAPT(DFT) protocol and orbital/fitting bases; SAPT(DFT) additionally requires physically determined monomer asymptotic corrections. Automatic PES work is a separate requirement. |

The two source track gaps, T3C-10s and T3C-1min, remain source gaps rather than
invented cheap CFOUR recipes. TORQ-owned rows remain TORQ responsibilities.

## Evidence and limits

The initial executable search found no CFOUR, Psi4, Molpro, or MPQC binary.
**Psi4 1.10.2 was subsequently installed and actually executed.** A real
SAPT2+3 calculation on the documented water-dimer geometry, with aug-cc-pVDZ,
aug-cc-pVDZ-jkfit, aug-cc-pVDZ-ri, and frozen cores, returned approximately
`-0.00718002478733 hartree` interaction energy. The four native SAPT terms sum
to that value. The public `RunRequest` matrix pathway and completed-component
resume both passed; resume retains the same attempt ID without recomputation.
The result is an interaction energy at one geometry, not a binding free energy
or a general accuracy benchmark. Native output, input, compiled-core hash, and
the ledger are retained in the execution workspace. CFOUR/Molpro/MPQC remain
absent, and no live calculation by those engines is claimed. Python parser
dependencies `qcengine==0.51.0` and `qcelemental==0.51.2` are installed; these are
parsers/contracts, not replacements for quantum-chemistry engines. The verified
optional dependency set belongs to the packaging/release configuration.

The focused adapter/workflow suite has **56 passing tests**, zero skips when
the actual Psi4 executable is configured, and a clean
Ruff check. It covers authentic historical MP2 and CCSD(T) output, native
geometry/gradient frame handling, wrong-method/core/basis/version rejection,
missing/truncated output, safe deck generation, explicit SAPT arithmetic,
unavailable engines, and one shared deadline/cancellation across an analytical
optimizer test fixture, exact matrix routing, genuine native SAPT execution and
verified ledger reuse. The analytical fixture is not quantum-chemistry
evidence. The separate BASE companion passed four focused native audit and
authority tests plus 48 existing authority regression tests. The complete
integrated release suite remains a distinct acceptance step.

The retained CFOUR native output excerpts are from the public Psi4 regression
suite, pinned to commit `23be3de4b1f6cd70e337b98a2a200008cf350274`, with complete
source/excerpt checksums in [fixture provenance](../tests/v010/fixtures/cfour/provenance.json).
They exercise the actual historical CFOUR 1.2 format, not a claim that a current
CFOUR installation ran here. Unknown modern output formats must fail closed
until their native artifacts have been tested.

## Reproducing the native Psi4 environment

[TOPOS_PSI4_ENVIRONMENT.lock](TOPOS_PSI4_ENVIRONMENT.lock) contains 98 immutable
conda-forge package URLs and SHA-256 hashes for Linux x86-64. Its explicit
installation plan was checked with micromamba 2.9.0. The actual installation
and genuine calculation used these package versions. In particular,
`libxc-c=7.0.0` is required by the tested build: the initially selected 7.1.2
allowed `psi4 --version` but caused the real compiled-core import to fail with
`XC_GGA_XC_TH_FL not found`. A version-only probe is consequently not sufficient
engine acceptance.

With a verified micromamba installation:

```sh
micromamba create -y -p /absolute/path/to/topos-psi4 -f .docs/TOPOS_PSI4_ENVIRONMENT.lock
TOPOS_PSI4_EXECUTABLE=/absolute/path/to/topos-psi4/bin/psi4 \
  python -m pytest -q tests/v010/test_external_engines.py tests/v010/test_external_matrix_workflow.py
```

The TOPOS interpreter also needs the project's `external` optional dependency
set. For production after the BASE companion is integrated, point
`COCHEM_PSI4_BIN` at that executable and run the actual eleven-phase Stage 0
setup; do not edit a locked registry to manufacture availability. The native
audit runs a real small He/HF calculation and binds subsequent execution to the
observed launcher, interpreter, and compiled-core hashes. This establishes
engine loading and execution authority; TOPOS independently validates every
requested SAPT calculation.

## Sources

1. [Psi4 CFOUR interface documentation, pinned source](https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/doc/sphinxman/source/cfour.rst): Cartesian derivative interfaces, optimizer ownership, standard orientation and atom-order handling.
2. [Psi4 SAPT documentation, pinned source](https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/doc/sphinxman/source/sapt.rst): SAPT2+3, closed-shell restrictions, decomposition, fitting bases, and distinct SAPT(DFT) asymptotic corrections.
3. [QCEngine CFOUR implementation, version 0.51.0](https://github.com/MolSSI/QCEngine/tree/v0.51.0/qcengine/programs/cfour): native Cartesian inputs, GENBAS layout, requested-method harvesting, GRD and dipole conventions.
4. [Actual upstream MP2 native output](https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/tests/cfour/opt-rhf-mp2/output.ref) and [CCSD(T) native output](https://github.com/psi4/psi4/blob/23be3de4b1f6cd70e337b98a2a200008cf350274/tests/cfour/opt-rhf-ccsd_t_/output.ref).
