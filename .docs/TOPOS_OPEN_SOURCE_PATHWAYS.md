# TOPOS 0.1.0: xTB, CREST and deduplication

TOPOS implements local Linux CPU searches using genuine xTB 6.7.1 and CREST 3.0.2 executables. These routes do not require ORCA; xTB and CREST remain subject to their own open-source licenses. They share the validated request contract used by the CLI, browser and CoChem-BASE Python interface. ORCA provisioning and GitHub Actions calculations are being handled separately by CoChem-BASE and are outside this verification scope.

The [SRS](CoChem-TOPOS_SRS.md), [method matrix](../wiki/Method_Matrix.md), and [scientific reference register](TOPOS_0.1.0_REFERENCES.md) define the requirements and scientific context. This document identifies the implemented subset and its limits. It does not claim that the complete method matrix or SRS is implemented.

## Choose a search protocol

| Request setting | Executed behavior |
|---|---|
| `search_algorithm: "jiggle-quench"` | Retain the input, generate seeded Cartesian perturbations, and optimize each admissible proposal using the requested xTB protocol. Supported frozen-monomer requests use rigid-fragment perturbations instead. |
| `search_algorithm: "crest"`, `sampler_profile: "crest-imtdgc-v1"` | Run native CREST iMTD-GC through the supported legacy driver with GFN2-xTB. Preserve its ensemble, then refine selected frames with xTB. |
| `sampler_profile: "crest-mquick-v1"` | Explicitly select CREST's reduced `--mquick` protocol. It omits normal molecular dynamics and genetic crossing. It is a distinct requested protocol, not automatic recovery from a failed full search. |
| `sampler_profile: "crest-nci-v1"`, `sampler_nci: true` | Select the matrix's NCI search options: `--nci --nocross --noreftopo`, with explicit GFN2-xTB and energy-window settings. Genetic crossing and the initial topology check are disabled; TOPOS still checks chemistry after refinement. |
| `search_algorithm: "union"` | Combine the explicitly requested jiggle–quench and CREST branches, preserve their observations, and compare candidates after common-level refinement. |

NCI requires at least two explicitly declared molecular fragments. The `sampler_nci` flag can also add NCI confinement to another selected CREST profile, including `crest-mquick-v1`. Confinement changes the sampled potential and is recorded. Subsequent xTB refinement does not retain that confinement. `--noreftopo` disables CREST's initial topology check; it is not the `--notopo` option that disables CREGEN topology checks. See [S03](TOPOS_0.1.0_REFERENCES.md#s03).

CREST routes currently require unconstrained GFN2-xTB and the supported engine versions. Unsupported constraints, methods or isotope-labelled CREST dynamics produce explicit unsupported outcomes. CREST's GFN0-xTB auxiliary Wiberg-bond-order/flexibility stage is recorded separately from the requested GFN2-xTB sampling potential. It is not presented as a replacement refinement Hamiltonian.

`seed` determines TOPOS jiggle perturbations. CREST controls its own random initialization in this adapter; a TOPOS seed does not make repeated CREST ensembles identical. The configured `sampler_budget_fraction` allocates part of the remaining workflow execution budget to CREST, reserving the remainder for refinement and comparison. Neither a time allocation nor native termination certifies exhaustive exploration. [S02](TOPOS_0.1.0_REFERENCES.md#s02)

## Count proposals and preserve their origins

`n_candidates` is a refinement limit with explicit source semantics:

- Jiggle–quench plans up to `n_candidates` proposals, including the unchanged input.
- CREST retains the input and selects up to `n_candidates` native frames, ordered by native search energy and frame index, for common-level refinement.
- Union retains the jiggle–quench plan and the selected CREST frames: at most `2 × n_candidates` planned proposals, including the input once.

The native ensemble can contain more frames than the refinement cap. All parsed native frames and reasons for exclusions from refinement are retained. A native search energy is an observation used for selecting frames, not a final common-level conformer energy. Retrying failed attempts can create more historical candidate observations than planned proposals; `processed_samples`, `completed_samples` and `candidate_observations` have different meanings.

Source labels include `INITIAL_SEED`, `JIGGLE_QUENCH` and `CREST`. CREST proposals retain the sampler attempt, native frame and search-energy origin; candidate and refinement-attempt `sampling_origin` metadata connects them to this evidence. Deduplication keeps a representative and links duplicate observations rather than deleting their records. Discovery overlap does not create a thermodynamic degeneracy.

## Refine at one level and apply an explicit window

The supplied examples select `profile_id: "xtb-vtight-v1"` and GFN2-xTB for all final optimizations. The profile maps to native xTB `vtight` convergence; the executed commands, engine version, executable hash and convergence evidence remain in each attempt. Selecting a CREST profile does not change the final xTB refinement profile.

TOPOS checks refined geometry, inferred connectivity and supported atom-mapped tetrahedral stereochemistry before making a candidate eligible. A copied input bond list or stereochemical label is not accepted as evidence that optimization preserved the chemistry. Invalid or ambiguous observations remain in the ledger with reasons. Tetrahedral checks do not assign CIP R/S labels.

`energy_window_kcal_mol` is explicit and defaults to **6.0 kcal/mol**. The adapter passes it as `--ewin` after profile switches, so a reduced CREST profile cannot silently replace it with a narrower native default; the reported native setting is checked. After refinement, the same declared window is applied relative to the lowest eligible energy within each compatible protocol/state group. Incompatible methods, executable/protocol identities, molecular states or fragment states are not combined on an assumed common energy scale.

An excluded-window candidate remains evidence. Exclusion does not establish physical absence or negligible experimental population. These are electronic energies, without automatic zero-point or thermal corrections. Electronic-energy weights are not Gibbs populations; TOPOS withholds them when identity comparisons are interrupted or unresolved, so uncertain duplicate counts do not become statistical weights. [S01](TOPOS_0.1.0_REFERENCES.md#s01), [S06](TOPOS_0.1.0_REFERENCES.md#s06)

## Conservative generation-level deduplication

Two candidates are merged only when they have compatible state and energy provenance and **all three** generation-level criteria agree:

| Request field | Default | Applied comparison |
|---|---|---|
| `dedup_energy_threshold_kcal_mol` | 0.05 kcal/mol | Absolute electronic-energy difference. |
| `dedup_rotational_threshold_fraction` | 0.01, or 1% | For each defined corresponding rotational constant, `abs(A − B) / max(A, B)`; matching zero-inertia axes receive explicit treatment. |
| `rmsd_threshold_angstrom` | 0.125 Å | Uniformly weighted **all-atom** RMSD after chemically compatible atom permutations and proper rotations. |

The graph/mapping comparison respects composition, isotopes, connectivity, whole-fragment partitions, fragment states and supported stereochemistry. Reflections are not allowed, and enantiomers remain distinct. An explicit alkenelike double bond also receives a relative cis/trans orientation check; ambiguous orientation retains both candidates. This requires explicit bond orders and does not assign CIP labels or certify axial, helical or coordination stereochemistry. Energy or rotational-constant agreement alone cannot establish a duplicate. Comparison records retain thresholds, values, mappings and the reason for each decision. A bounded or ambiguous identity search retains both observations as unresolved; it does not manufacture an equivalence decision. See [S05](TOPOS_0.1.0_REFERENCES.md#s05).

The defaults follow the numerical generation-level values in [matrix Appendix A.1](../wiki/Method_Matrix.md#a1-conformer-search-global-optimisation-and-the-two-stage-deduplication-protocol). That appendix gives **0.05 kcal/mol**, whereas [§13.1](../wiki/Method_Matrix.md#131-table-1--conformer-and-isomer-search) states **0.100 kcal/mol**. TOPOS records the chosen 0.05 value explicitly instead of treating those conflicting statements as equivalent.

The TOPOS rotational tolerance is fixed and conservative. It does **not** reproduce CREGEN's anisotropy-dependent adjustment from 1% toward 2.5%, and this implementation is not labelled exact CREGEN. Native CREST filtering and the subsequent TOPOS screen are separate operations with separate evidence. The matrix's proposed reporting-level refinement, 0.1% spectroscopic criterion, heavy-atom RMSD, enantiomer/rotamer degeneracy collapse and dipole-based spectroscopic annotation are not delivered by this generation-level screen. A rigid-rotor equilibrium constant is not an experimentally measured or vibrationally averaged constant.

## Install, run, inspect and resume

Install the package and supported engines, using destinations outside the source checkout:

```bash
python -m pip install -e '.[dev,ui]'
python scripts/install_xtb.py /tmp/topos-tools
python scripts/install_crest.py /tmp/topos-crest
export TOPOS_XTB_EXECUTABLE=/tmp/topos-tools/xtb
export TOPOS_CREST_EXECUTABLE=/tmp/topos-crest/crest
```

Both installers verify pinned upstream checksums. The following small requests exercise the public workflow:

```bash
python -m topos run --request examples/water-search.json --output-root /tmp/topos-runs
python -m topos run --request examples/water-crest-mquick.json --output-root /tmp/topos-runs
python -m topos run --request examples/water-union.json --output-root /tmp/topos-runs
python -m topos run --request examples/water-dimer-crest-nci.json --output-root /tmp/topos-runs
python -m topos inspect /tmp/topos-runs/RUN_ID
python -m topos resume --run-dir /tmp/topos-runs/RUN_ID
```

Replace `RUN_ID` with the returned identifier. Run scratch and scientific records must remain outside the checkout. The browser uses the configured output root, with the same source-tree restriction as the CLI. See the [example guide](../examples/README.md) for each fixture's purpose. The water-dimer example explicitly selects **mquick plus NCI**, not `crest-nci-v1`; select the latter profile deliberately when requesting its different native search schedule.

`inspect` verifies the saved evidence. `resume` verifies the immutable request and committed snapshot before continuing; completed observations keep their identities and failed retries receive new linked attempts. Each explicit continuation receives a fresh recorded invocation budget. A completed run returns without recalculation.

If CREST is unavailable during an explicitly requested union, TOPOS can still complete the separately requested jiggle–quench branch. The overall result remains **partial**, with `sampler_pending` and the failed sampler attempt recorded. After the executable becomes available, resume retries CREST and appends its proposals while preserving completed jiggle–quench work and stable indices. This is completion of the original two-branch request, not a change of search algorithm.

A timeout, cancellation, failed native search or failed refinement is an outcome to inspect. Full native iMTD-GC can fail during genetic crossing for a single-conformer water case in CREST 3.0.2; TOPOS preserves that failure rather than silently choosing mquick or disabling genetic crossing. CLI exit status 0 means the requested finite protocol completed, 3 means incomplete/unavailable execution, and 2 means invalid input or an action error.

## Evidence and scientific limits

The machine-readable [open-source validation receipt](TOPOS_OPEN_SOURCE_VALIDATION.json) records **330 passing regression tests, zero failures/errors/skips**, Python and workflow linting, dependency checks, and a successful wheel/source build. A supplementary eight-test run and an intentional missing-engine failure verify the final CI collection guard. Source hashes distinguish this working tree from the earlier validation baselines.

All four documented CLI examples completed with genuine engines and verified snapshots:

| Example | Refined observations | Retained candidates | Duplicates |
| --- | ---: | ---: | ---: |
| Water jiggle–quench | 3 | 1 | 2 |
| Water CREST mquick | 2 | 1 | 1 |
| Water union | 3 | 1 | 2 |
| Water-dimer CREST mquick + NCI | 3 | 2 | 1 |

The water-dimer native sampler returned 48 frames in that run; the explicit two-frame refinement cap plus input produced the three refined observations above. These are measured outcomes of small integration fixtures, not required future counts or exhaustive chemical inventories.

A separate full native iMTD-GC ethanol experiment completed in 87.83 seconds within its declared 240-second budget and returned five native frames. All five were subsequently refined in separate real xTB `vtight` Workflow runs. Ten pair comparisons completed without unresolved identity searches, retaining five candidates. The receipt explicitly identifies this as a two-stage experiment, rather than a single CREST Workflow invocation. An earlier independent 90-second ethanol search timed out and retained three partial frames; its unsuccessful receipt remains recorded. Native frames, refined candidates and frequency-verified minima are distinct claims.

CI installs genuine pinned engines and sets `TOPOS_REQUIRE_REAL_ENGINES=1`, making missing required executables a verification failure. Standalone tests without that requirement can explicitly skip engine-dependent cases. Numerical fixtures, parser tests and interface tests provide different kinds of evidence; only real-engine invocations support claims about executed calculations. An Actions workflow file or a successful local test is not evidence that a GitHub-hosted run completed.

These pathways do not establish global minima, frequency-verified minima, exhaustive sampling, accurate thermochemistry, spectroscopic reporting, or transferable accuracy for arbitrary chemistry. They do not validate ORCA or GPU calculations. Using two search algorithms with the same GFN2-xTB potential adds discovery evidence without independently validating that potential.

Relevant primary citations already verified bibliographically in the reference register are Bannwarth, Ehlert and Grimme, GFN2-xTB ([10.1021/acs.jctc.8b01176](https://doi.org/10.1021/acs.jctc.8b01176)); Pracht, Bohle and Grimme, automated low-energy exploration ([10.1039/C9CP06869D](https://doi.org/10.1039/C9CP06869D)); and Pracht et al., the CREST program ([10.1063/5.0197592](https://doi.org/10.1063/5.0197592)). Their full texts were not newly reviewed for this implementation update. Version-specific option meanings are documented in [S03](TOPOS_0.1.0_REFERENCES.md#s03); execution provenance remains necessary alongside the citations.
