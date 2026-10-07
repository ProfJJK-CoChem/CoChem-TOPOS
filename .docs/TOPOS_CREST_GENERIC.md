# CREST generic ML potential and native path correction

`topos.ml_crest.run_crest_ml` binds native CREST to the same persistent,
manifest-bound ML worker used by ORCA ExtOpt. It retains each accepted native
XYZ request and exact model energy/gradient response. Coordinates are Angstrom;
the generic `engrad` file contains atom count, Hartree energy, and `3N`
Hartree/Bohr gradient components. The caller must allocate the concurrent model
and CREST processes explicitly under BASE authority.

This is an enumeration potential. Final observations require common-level QM
refinement and do not establish exhaustive sampling or frequency-verified
minima. CREST additionally computes internal GFN0 WBOs for its flexibility-based
MD-length estimate; these ancillary calculations do not replace the search
potential. Isotope MD masses remain unsupported and isotope input is rejected.

## Stock 3.0.2 defect

Exact upstream source: `af7eb9927e2b36e24b14055f9eba3bea5be0014e` (`v3.0.2`).

* [`parallel.f90`](https://github.com/crest-lab/crest/blob/v3.0.2/src/algos/parallel.f90#L559)
  copies already initialized calculation objects and assigns a new `calcspace`
  to each worker.
* [`generic_sc.f90`](https://github.com/crest-lab/crest/blob/v3.0.2/src/calculator/generic_sc.f90#L151)
  reuses its cached `calcfile` and `systemcall`. Its gradient reader nevertheless
  constructs a path from the new `calcspace`.

Observed with both genuine external xTB gradients and genuine MACE gradients:
single-point and trial MD calls work, but the production MD calls use the old
directory; CREST cannot read their gradients from the new worker directories.
The resulting empty trajectory is a native failure, not sampling completion.

The [source patch](patches/crest-3.0.2-generic-paths.patch) invalidates those two
cached fields inside the generic setup routine before reconstructing them from
the current calculation directory. It leaves the potential, gradients, MD
settings, optimization, screening, and ensemble algorithms unchanged. It also
prints `TOPOS patch: crest-3.0.2-generic-paths-v1` in the native banner and version
probe. Its SHA-256 is
`9f22e2d9e0cd9b6aa8a6d41a0c32b6271d659c62498f888f0d5d889cc09aa8b9`.

The ML sampler rejects stock 3.0.2 before launching a model search. Results
record the actual executable hash, upstream version/commit, patch identity,
native command, model manifest, and callback receipts. The original stock
installation is retained separately.

## Build contract

Clone the exact upstream commit and initialize its pinned git submodules;
apply only the patch above. GNU Fortran 14.2.0, GNU C 14.2.0, CMake 3.31.10,
Ninja 1.13.0 and BLAS/LAPACK were used for the development build. Configure
`CMAKE_BUILD_TYPE=Release`, `WITH_TBLITE=OFF`, `WITH_TESTS=OFF`,
`WITH_XHCFF=OFF`. Keep OpenMP, TOML-F, GFN0, GFN-FF and lwONIOM enabled.
The absent tblite backend is explicit: this build runs the supplied generic
potential; TOPOS's existing legacy xTB route uses its external xTB executable.

Keep `installation.json` beside the new executable with the exact source and
submodule commits, patch hash, executable hash, feature switches, compiler/build
commands, shared-library hashes and license files. BASE must audit that actual
installation; a development executor result does not constitute BASE authority.
Do not replace a stock executable silently or represent the patched build as an
unmodified upstream release.

## Validation scope

The explicit live tests in `tests/v010/test_ml_crest.py` use
`TOPOS_CREST_EXECUTABLE` for stock CREST,
`TOPOS_CREST_ML_EXECUTABLE` for the identified patched build,
`TOPOS_ML_TEST_PYTHON` for an interpreter with actual MACE and installed TOPOS,
and `TOPOS_ML_TEST_REQUEST` for a real checkpoint request.

The single-point bridge compares actual CREST output with the actual retained
MACE energy and gradient. The bounded-search test verifies truthful termination
when its explicit callback budget is reached. Neither test alone establishes a
completed default iMTD search, GPU fine-tuning, or the compound T1-1w recipe.

A separate complete native `crest-mquick-v1` acceptance succeeded with the
reviewed patched binary and actual MACE-OFF23-small (MACE 0.3.16, Torch 2.8.0
CPU): two CREST workers completed all six production MTDs and native ensemble
optimization, preserving 3,851 successful model callbacks and one final water
conformer in 206.337 seconds. No MD-length override was used. The immutable
binary SHA-256 is
`a2834f036e793ae674c823d1cb673a2625b1644db5239cfed8eaa9f6fcc65adc`.
`native-validation.json` accompanies that installation and binds the raw result
and all retained artifact hashes. This demonstrates the explicit reduced
profile and generic parallel interface under the bounded development executor;
BASE execution, GPU training and the full compound recipe remain separate
acceptance requirements.

Call `validate_crest_ml_distribution(binary)` before expensive fitting to
verify the explicit source/patch/binary distribution. Its capability version is
`3.0.2+topos-generic-paths-v1`, distinct from stock `3.0.2`. The sampler also
checks the actual native version marker and requires BASE execution authority.
