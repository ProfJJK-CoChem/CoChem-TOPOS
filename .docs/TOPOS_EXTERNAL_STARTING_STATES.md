# Independent starting states and continuation

TOPOS accepts independently prepared geometry and native GOAT/CREST ensemble
files through the same typed workflow used by BASE, the browser and the CLI.
This permits a specialized external search to supply the starting states for a
new TOPOS refinement, scan, thermal calculation or supported matrix recipe.

Install the mandatory BASE/TOPOS/TORQ ecosystem first and verify BASE's actual
runtime authority with `cochem-topos doctor --verify-runtime`. The TOPOS GUI is
started with `topos-ui`. Its external starting-state panel validates an upload,
shows its frames, retains the original bytes, and starts the selected real
calculation. It does not execute uploaded scripts or infer a successful engine
calculation from a filename, completion declaration or XYZ energy comment.

## Supported import stages

| Import entrypoint | Accepted requested route | Behavior |
| --- | --- | --- |
| `geometry` | Search, optimize, energy, gradient, frequency, thermochemistry, association, matrix | One selected geometry becomes the requested input. The complete requested calculation runs. |
| `refinement` | Search, optimize, energy, gradient | Every selected frame is calculated at the requested target level. This explicitly skips generating a new jiggle/CREST/GOAT search. Ordinary comparison/deduplication follows the actual target calculations. |
| `topology-seeds` | T1-10s, T1-1h, T1-1mo | Populate the typed topology seeds. Existing minimum-count and distinct-geometry checks apply. |
| `stage-b-ensemble` | T1-3d | Populate the typed ensemble for the next refinement stage. Imported search energies do not become validated target energies. |
| `leading-isomers` | T1-12h | Supply two or three distinct, explicitly selected geometries. |
| `entropy-seeds` | T1-1d | Supply identical seeds to the actual paired native entropy calculation. Imported source scores do not establish entropy convergence. |
| `ml-search-seeds` | T1-30min, T1-1w | Supply starting geometries while retaining all required explicit model/training/allocation inputs. |
| `isolated-monomers` | T3O-1min, T3O-3h | Supply one independent geometry per declared fragment, retaining stable atom IDs and charge/spin state. R2 additionally requires exact typed high-level method/source/geometry-hash provenance. |

The import stage never supplies missing matrix controls, fitting bases, trained
checkpoints, resource authority or native derivative evidence. Advanced controls
are entered in the GUI's explicit recipe JSON or the identical `RunRequest` JSON.
An incompatible route returns its concrete validation reason.

## Source conventions

Accepted primary formats are `xyz`, `crest-ensemble`, and `goat-ensemble`.
Coordinates must be explicitly declared in angstroms. Native CREST/GOAT ensemble
comments must be explicitly declared as hartree; their existing strict native
parsers check finite values and exact element order. For a single geometry XYZ,
the comment is retained but is never interpreted as an electronic energy.

The reference molecule declares total charge, multiplicity, isotopes, stable
atom IDs, environment, stereo information, fragment partition and fragment
electronic states. Its source `atom_order` must match those stable IDs exactly.
Checking the element sequence cannot prove the mapping of two identical atoms;
the producer is responsible for the explicit declaration. Changes in inferred
covalent topology, declared molecular state, mapped stereo, or physically suspect
geometry are rejected as incompatible starting states.

A single-geometry import rejects pre-existing starting-geometry lists and matrix
seed or native-ensemble inputs that could override the selection. Use a fresh
request and the corresponding named matrix entrypoint instead. Isolated monomer
references and property protocols remain attached to a new complex pose.

Every import supplies source engine, version, method, author and description.
These are caller declarations. An ORCA native `converged=true` frame comment
describes that local frame; it does not certify the external global search,
common-level refinement, a full-dimensional minimum or an exhaustive ensemble.

Primary uploads and optional accompanying `.inp`, `.out`, `.log`, `.stdout`,
`.stderr`, `.txt`, `.json` and `.xyz` text files are preserved byte for byte in
the canonical run's checksummed snapshots. Associated outputs are retained as
unvalidated source evidence. Binary files, archives, pickles and symlink files
are rejected. Combined uploads are limited to 64 MiB and ensembles to 10,000
frames. Generated destination names prevent duplicate basenames or path traversal
from changing canonical artifact membership.

## CLI example

Prepare `molecule.json` containing the declared molecular state and original
atom mapping. Prepare a normal `request.json` containing that molecule and the
target engine/method/purpose. For a GOAT ensemble, create `import-spec.json`:

```json
{
  "format": "goat-ensemble",
  "reference": {"symbols": ["O", "H", "H"], "coordinates": [[0, 0, 0], [0.95, 0, 0], [-0.24, 0.93, 0]], "charge": 0, "multiplicity": 1, "atom_ids": ["O1", "H1", "H2"]},
  "entrypoint": "refinement",
  "selected_frames": [1],
  "source": {
    "engine": "orca",
    "engine_version": "6.1.1",
    "method": "r2SCAN-3c",
    "created_by": "student identity",
    "description": "Independent GOAT search with explicitly documented custom controls",
    "coordinate_units": "angstrom",
    "energy_units": "hartree",
    "atom_order": ["O1", "H1", "H2"],
    "original_calculation_status": "unknown"
  }
}
```

This three-atom example demonstrates the import contract; it is not evidence for
the reviewed matrix campaign, whose selected complexes have 5–10 atoms and at
least two declared fragments. Use the actual source molecule and controls for
your calculation. Source energies and the target calculation level can differ;
their values are never combined into a common comparison protocol implicitly.

```bash
cochem-topos external-preview --input goat.finalensemble.xyz --spec import-spec.json
cochem-topos ingest --input goat.finalensemble.xyz --spec import-spec.json \
  --supporting-file goat.inp --supporting-file goat.out \
  --request request.json --output-root "$HOME/CoChem_Artifacts/TOPOS" --execute
```

Omit `--execute` to create only the verified queued starting-state record. In
Python, call `execute_external(run_dir)` to start that staged run. Use the normal
`cochem-topos resume --run-dir ...` command for a previously started compatible
calculation. Queued imports have no calculation attempts or validated candidate
energies; imported outputs cannot bypass scientific review/export gates.

For separate monomer uploads, repeat `--input` and `--spec` once per fragment in
matching argument order. Each monomer spec uses its own fragment reference and
`isolated-monomers` entrypoint. Files are ordered canonically by the complex's
declared partition, not by upload order. All required fragments must be supplied.
R2 references additionally require the matching `r2_monomer_provenance` objects
in the request, bound to the exact imported molecule's canonical JSON SHA-256.
No source method or scientific provenance is fabricated during import.

## Hosted calculations and existing completed work

`starting_geometries` and the full typed matrix inputs are serialized in the
normal Actions request. A hosted external import requires the configured private
student/lab controller, its source pins, BASE authority and the separately
provisioned requested engines. Original uploaded files stay in the caller's
verified run; the hosted worker receives the declared coordinates and provenance.
Its independently retained record binds the actual target calculations. Initial
dispatch is explicit and can occur only once; subsequent remote continuation
polls the owned job rather than silently dispatching a new calculation.

A verified existing TOPOS `RunStore` can be resumed through the existing recovery
path, which checks snapshot membership, request identity and committed result
integrity. Verified native ensembles from those stores remain available through
the existing `goat_ensemble`/`crest_ensemble` matrix input contracts. Arbitrary
foreign output files can be retained alongside a new starting geometry, but are
not converted into a forged TOPOS attempt, Hessian, population, property, or
publication eligibility. A source output needing a new scientific parser must
first receive a genuine engine-specific validation contract.
