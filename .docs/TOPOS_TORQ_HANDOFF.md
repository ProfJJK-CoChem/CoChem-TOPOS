# TOPOS producer contract and reproducible research export

TOPOS exports reviewed ensembles; CoChem-TORQ is a separate mandatory CoChem
component under development. A handoff file is **not evidence that TORQ consumed
it or performed a calculation**. The legacy TORQ `fetch_topos_matrices` loader
reads unversioned HDF5 groups, supplies default values for some missing data, and
does not implement the contract below. TOPOS does not invoke that loader or
report its compatibility with this protocol.

## Producer interface

```python
from topos.review import export_torq_handoff, verify_torq_handoff
handoff = export_torq_handoff("path/to/run", "handoff.json")
verified = verify_torq_handoff("handoff.json")
```

The source run must have a verified committed snapshot, explicit accepted
candidate decisions, and a current reviewed ensemble. Export refuses stale
snapshots, superseded review, scientific incompleteness and mixed comparison
protocols. It creates an immutable external JSON file and retains the exact
transmitted content under `run/handoffs/<handoff_sha256>.json`.

`topos-torq-handoff/0.1.0` carries:

- Run ID, ensemble schema/digest, committed snapshot and record digests.
- The complete original request, including constraints, matrix/profile settings,
  calculation resources and seeds; the complete typed run record and attempt
  provenance; the exact ensemble and hash-linked review decisions.
- Every member's ID, geometry digest, full molecule and candidate payload,
  originating attempt ID, comparison protocol, uncertainty and unresolved items.
  Molecules preserve coordinates/units, symbols, isotopes, atom IDs, connectivity,
  stereochemistry, fragments and fragment charge/spin states.
- `scope: reviewed-geometry-ensemble` and
  `consumer_status: awaiting-external-consumption`.
- Explicitly retained limitations, including that TORQ may need further sampling.

This geometry transfer includes the raw-artifact **inventory**, not raw output
bytes or licensed executables. Use `topos.publication.export_bundle` to transfer
checksummed inputs and raw outputs. Wavefunction reuse requires that separate
artifact transfer and TORQ's own state/basis/geometry compatibility checks; this
handoff never supplies a fabricated `.gbw` path or missing energy sentinel.

Digests are SHA-256 over UTF-8 JSON with sorted keys, separators `(',', ':')`,
`ensure_ascii=False`, and `allow_nan=False`. The handoff digest excludes only
`handoff_sha256`; an ensemble digest excludes only `manifest_sha256`. Member
geometry digests cover the **entire molecule payload**, including atom maps,
isotopes, charge/spin and units. Digest validation establishes content integrity,
not sender authentication or scientific accuracy.

A consumer must verify the handoff, check its own schema and physics support,
import each exact member, and only then emit a receipt. Missing data remain
missing. Unsupported chemistry or incomplete transfer must fail explicitly.

## External consumption receipt

TOPOS accepts an externally generated JSON receipt with **exactly** these keys:

```json
{
  "schema_version": "topos-torq-consumption/0.1.0",
  "run_id": "SOURCE_RUN_ID",
  "ensemble_schema": "topos-ensemble/0.1.0",
  "ensemble_sha256": "EXACT_ENSEMBLE_DIGEST",
  "handoff_sha256": "EXACT_HANDOFF_DIGEST",
  "members": [
    {"member_id": "EXACT_MEMBER_ID", "geometry_sha256": "EXACT_GEOMETRY_DIGEST"}
  ],
  "consumer": {"name": "CoChem-TORQ", "version": "ACTUAL_CONSUMER_VERSION"},
  "consumed_at": "ISO_8601_TIMESTAMP_WITH_TIMEZONE",
  "status": "consumed",
  "receipt_sha256": "SHA256_OF_RECEIPT_WITHOUT_THIS_FIELD"
}
```

Member order must match the handoff. Import the external file with:

```python
from topos.review import accept_torq_receipt
receipt = accept_torq_receipt("path/to/run", "receipt-from-torq.json")
```

The function refuses unknown fields, incompatible schema, absent consumer
identity/version, invalid timestamp, mismatched geometry/member membership, and
stale run/review/ensemble versions. Valid receipts are retained under
`run/consumer-receipts/` by their digest, with idempotent duplicate import.
TOPOS does not create a consumer receipt. The declared consumer identity is not
cryptographically authenticated; a receipt records a declared import and does
not establish a successful downstream calculation. Existing `acknowledge_torq`
remains an explicitly scoped **manifest-receipt-only** operator action and is
never substituted for an external consumption receipt.

## Review and scientific export

`review_basket(run_dir)` returns original candidate structures/metrics/provenance,
scientific eligibility and its reason, unresolved items, and complete decision
history. `append_decision` accepts optional `scope` and JSON `annotations`, so
manual symmetry/group assignments remain annotations. Revisions must explicitly
supersede the previous decision; raw observations are unchanged.

Research bundles now include `regenerate.py`, `selected.csv`, and
`relative-energy.svg`. Run:

```bash
python /path/to/bundle/regenerate.py /new/output/directory
```

The script requires Python 3.10 or newer and only its standard library, checks
its source inputs against the bundle inventory, and regenerates both outputs.
The plot shows relative **electronic** energies in hartree within the reviewed
common protocol. It counts omitted missing energies; it does not substitute
Gibbs energies, infer populations, assert accuracy, or replace absent energies
with zero. Zero in a valid plot means the minimum reported selected energy.

Citations are attached to actually invoked engines and retain attempt IDs,
versions, methods and execution status, including retained failed attempts.
Author-supplied additions retain that attribution. Verified catalog entries
separate peer-reviewed papers, software, documentation and the GFN0-xTB preprint.
Unknown methods/models/bases remain unresolved; bibliographic presence does not
establish scientific validity or complete credit.

For actual ORCA invocations, exports include the ORCA 6 required software citation
[Neese, 2025, DOI 10.1002/wcms.70019](https://doi.org/10.1002/wcms.70019), a DATA
notice, and the June 2025 EULA section 7 disclaimer. A proposed bundle license
never overrides the ORCA EULA. Conflicting blanket rights remain unresolved for
author review. Local export accepts the supported SPDX identifiers or documented
`LicenseRef-...` identifiers; custom license text and artifact-specific rights
still need author review. This does not grant software/data rights.

Export, external draft deposit, and public release are separate actions. This
API performs a local export only: `publication_ready=false`,
`publication_status=not-published`, `version_doi=null`, and `concept_doi=null`.
It does not reserve a DOI, publish, or submit to a journal. Publication remains
an explicit author action after rights/access and scientific review. A future
deposition connector must distinguish a reserved DOI from a published exact
version and a concept/all-versions DOI.

## Validation scope

`tests/v010/test_completion_io.py` exercises portable handoff round trips,
corruption/semantic mismatches, external-receipt contract fixtures, stale versions,
review annotation preservation, standalone table/figure reproduction, missing
data, execution-aware references and license metadata. Receipt fixtures are
clearly labelled; they are **not real TORQ integration evidence**.

The ENOSPC tests redirect one isolated staging write to Linux `/dev/full` so the
actual kernel returns `ENOSPC`; they verify that the committed snapshot survives
and an incomplete export is not promoted. They do not fill shared disk space or
claim physical filesystem exhaustion, filesystem-specific power-loss guarantees,
or storage-device failure testing. Existing quota, corruption, concurrent-run,
interruption and restart tests remain in `test_storage_publication.py`.

Bibliographic metadata was checked against the official
[xTB bibliography](https://github.com/grimme-lab/xtb/blob/main/assets/references.bib),
[CREST documentation](https://github.com/crest-lab/crest/blob/master/README.md),
and [gCP method bibliography](https://github.com/grimme-lab/gcp/blob/master/README.md).
The ORCA citation and notice derive from the user-supplied June 2025 EULA.
