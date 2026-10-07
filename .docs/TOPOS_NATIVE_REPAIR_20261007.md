# Native calculation and release repairs under validation

The retained [licensed run 37666938546](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37666938546) tested TOPOS `65af1e05ce505cac5911b1bfe8f985a26dd87864` through BASE `705b9d54370d5089da286a02b7a1c4afdcbafec1` and TORQ `79fbb111125e50627a1a2c129888a45496f368d4`. Its original GitHub artifact ZIP matches the API digest, all 11,393 extracted files match that ZIP, source inventories match the committed source, and all 30 retained RunStore snapshots verify. The [portable index](evidence/TOPOS_ORCA_RUN_37666938546_EVIDENCE_INDEX.json) preserves the original receipt bytes.

The actual results were two of five baseline cases, eight of thirteen extended cases, and 25 of 27 licensed tests passing. These historical component passes do not certify subsequent source changes. The [diagnosis](evidence/TOPOS_ORCA_RUN_37666938546_FAILURE_DIAGNOSIS.json) and [VPT2 progress analysis](evidence/TOPOS_ORCA_RUN_37666938546_VPT2_DIAGNOSIS.json) identify the native failures without converting them into successful calculations.

## Correlated input and execution allocation

The native RIJK ghost inputs populated AuxJK but omitted the AuxJ slot required by ORCA startup. The corrected counterpoise deck binds both slots to the identical already selected, exported JK basis file and checksum. It introduces no additional fitting basis or correlation approximation; every native leg retains and verifies both slot bindings.

The H2 F12 fragment was rejected because two MPI ranks exceeded its one occupied pair. TOPOS now caps F12 ranks only when the zero-core occupied space is established: H/He have no core orbitals, or the caller explicitly requests all-electron NoFrozenCore within the reviewed domain. It preserves the original per-rank MaxCore, total RAM ceiling and deadline and records requested/effective allocations. It does not guess a heavier atom's native frozen-core choice. The Hamiltonian, basis, core convention and frozen geometry remain the explicitly requested protocol.

The native pair rejection and memory declarations are preserved in authentic regression fixtures. The [ORCA MDCI manual](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/mdci.html) supplies the method context; the exact installed native output supplies the operational pair-limit evidence.

## VPT2 property writer

Both historical water VPT2 runs stopped at the initial Pickett property output before any displaced Hessian calculations. The extended case printed an MPI PROPERTIES error; the licensed pytest case stalled there until its deadline. The distinction remains in their unchanged outputs. This evidence does not establish that a longer budget would complete VPT2.

The pinned ORCA 6.1.1 VPT2 route now explicitly requests one native worker while keeping the original per-worker MaxCore and shared deadline. Its reference optimization/gradient/Hessian retain the caller's requested allocation. Requested and effective resources, the execution-policy identity and exact decks are bound into recovery and rotational-transfer verification. All method, basis, dispersion, convergence, grid and finite-displacement settings remain unchanged. The serial compatibility choice still requires completed native acceptance.

The [official VPT2 manual](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/vpt2.html) documents `%output Pickettname "pickett.txt"` and states that the feature is still being refined and extended. Its retrieved HTML has SHA-256 `f49ed59d47ba2e9368820407c78fa9aaa46a2d29ea192236205be30490e51eb2`. The [property diagnostic](../scripts/probe_orca_pickett.py) compares genuine serial/MPI SCF property jobs with and without this keyword. A property-only diagnostic cannot complete VPT2 acceptance.

## Recovery and installation

Remote recovery now binds the caller's immutable request separately from the worker's deliberate local request, retains owned dispatch/controller identities before submission, and polls/retrieves the same job after interruption. A lost submission response remains explicitly unconfirmed until an authenticated matching job is observed; recovery does not submit another job. Imported terminal scientific records, including failures, remain immutable.

The hosted preflight now expands only the reviewed `orca+crest` compound label into its supported native ORCA/CREST/xTB installations. It does not infer installers for arbitrary compound labels or ML/CFOUR profiles.

The [repository-owned complete-kit assembler](../scripts/assemble_ecosystem_candidate.py) now packages all three exact companion sources and wheels, the isolated TOPOS worker, checksums, installation evidence and a concrete installer. Companion wheels are independently built twice from the supplied committed archives. The release workflow retains the complete downloadable kit and its scientific gate result. Assembly never signs, publishes or certifies a release.

The [SRS acceptance ledger](TOPOS_SRS_ACCEPTANCE.json) and [release status](TOPOS_RELEASE_STATUS.md) retain external-engine, GPU, full matrix campaign and deployed queue/correlation conditions. These repairs require fresh source-matched regression, installed-package and physical evidence before any condition is cleared.
