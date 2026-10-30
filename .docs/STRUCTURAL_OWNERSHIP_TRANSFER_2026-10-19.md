# Canonical structural ownership transfer

This bounded change moves the existing graph, ring, Lewis-contributor and
tautomer modules from BASE to `topos.structural`. It does not certify full SRS
conformance, thermodynamic ranking, exhaustive sampling or student deployment.

The immutable source is BASE
[`b05f7b048eff39bedf63019c8f371bdde5b5579a`](https://github.com/ProfJJK-CoChem/CoChem-BASE/tree/b05f7b048eff39bedf63019c8f371bdde5b5579a).
The [transfer manifest](evidence/structural-ownership-transfer-20261019.json)
records every original and migrated file SHA-256. Module ASTs are identical after
removing import nodes and normalizing whitespace-only blank lines in docstrings.
Changes are namespace imports, import sorting, removal of one unused typing
import, two lint comments that preserve the original `zip` behavior, and the
three documented whitespace sites. No algorithm, model, dynamic mass resolver,
numeric constant or scientific threshold changes. Compared with locally
committed producer `550717ed54c10387557099fe095bf1d336bc8614`, only excess EOF
blank lines in `exceptions.py` and blank-line spaces inside the `graph.py` and
`rings.py` docstrings were removed.

The four complete scientific test functions and their SMILES graph helper are
byte-identical to the original BASE functions. They test two actual benzene
Kekule contributors without isomer populations, explicit refusal of temperature
and guessed numerical weights/energies, truthful enumeration truncation, and
preservation of an explicit 13C label using the real dynamic mass resolver.
RDKit is a direct dependency because these modules actually call RDKit chemistry
operations; BASE's transitive installation is not its ownership contract.

The separate file/process boundary is
`python -I -m topos.structural --request REQUEST.json --output RESULT.json`.
BASE supplies the approved interpreter, verified module/wheel seal, wall deadline,
resource policy and cancellation. BASE does not need to import TOPOS science.
The interface accepts one UTF-8 JSON object with `schema`, `request_id`,
`operation`, and `input`. Its schema is `cochem.topos-structural/1`.

| Operation | Input and supported scope |
| --- | --- |
| `resonance_enumeration` | SMILES, optional `max_structures` (1–10000), optional null `temperature_k`; runs the existing structural enumeration. |
| `topology_to_rdkit` | `molecule_id`, explicit `elements` including isotope labels, matching `atomic_numbers`, exact indexed `bonds`, optional `formal_charges`; constructs and sanitizes the existing explicit non-ghost topology. |

The boundary rejects unknown fields, duplicate/nonfinite JSON, boolean integer
selectors, inconsistent identities, duplicate/self/dangling bonds, unsupported
exact bond orders, SMILES/explicit identity mixtures, supplied masses and forged
thermodynamic quantities. Requests are limited to 1 MiB, SMILES to 4096 characters,
and molecules to 256 explicit atoms. These are operational admission bounds,
not changed chemistry thresholds. The caller still enforces process resources.
Unsupported routes produce a nonzero refusal with no success result.

Each completed receipt contains the raw and canonical request hashes, dependency
versions, all eight structural source-member hashes and wheel RECORD digest.
Every structural member is checked against its installed noneditable-wheel
RECORD before and after execution. This proves byte consistency; the caller must
also verify the approved revision and external wheel seal. The installer used in
this local validation, uv, omitted PEP 610 archive hashes: the receipt honestly
retains null, and the [validation receipt](evidence/structural-ownership-20261019/receipt.json)
records the separately calculated actual wheel SHA-256.

Results contain explicit atom order/isotope identity and indexed bond lists.
Contributor bond dictionaries with tuple keys are never ambiguously serialized
as JSON object keys. Missing energies, weights and temperature remain null;
`scientific_execution_performed` remains false and the acceptance scope is
`structural_enumeration_only`. Output publication is exclusive and atomic;
symlinked paths, changed requests and existing student output are refused.

After that whitespace cleanup, a fresh installed noneditable wheel was validated
outside the checkout: **127 cases passed with zero failures, errors or skips**,
including all **26 required structural and real boundary cases** plus existing
science, schema-evolution and release regressions. Full repository Ruff and
dependency consistency checks passed. All three actual structural output proofs
were regenerated and their complete eight-member source hash maps were checked
against the post-whitespace source.

The [historical producer archive](evidence/structural-ownership-20261019/pre-whitespace-550717e/README.md)
retains the exact original native outputs, wheel identity, JUnit, dependency
freeze, initial failures, source-suite and stale-wheel proof from producer
`550717e`. Its byte-equivalence inventory was checked against that commit. Those
receipts remain historical evidence; they do not validate the later producer
bytes. The current test harness still compares all eight installed source hashes
with the current checkout before reusing its interpreter; mismatches rebuild a
current disposable wheel. No test body changed for the whitespace cleanup.

The receipt retains exact counts, durations, JUnit files and actual native
[benzene](evidence/structural-ownership-20261019/benzene-result.json),
[truncated benzene](evidence/structural-ownership-20261019/benzene-truncated-result.json),
and [13C formaldehyde](evidence/structural-ownership-20261019/13c-formaldehyde-result.json)
outputs and their input/artifact hashes. Initial failed setup/harness attempts
remain recorded separately; they are not scientific passes.

The new dedicated installed-wheel Actions lane preserves the existing full
source/editable lane. It uses the public pinned BASE source with GitHub's normal
checkout authorization, installs a genuine noneditable TOPOS wheel, runs all
four preserved cases plus the real boundary checks, and retains the wheel,
digest, dependency freeze, JUnit and native JSON evidence. This local receipt
does not assert that the new GitHub Actions lane has run.

BASE legacy sources and its five empirical-quench cases remain untouched here.
Only after independent review, TOPOS publication, a reviewed BASE catalog pin and
genuine managed boundary verification may BASE apply the staged test split and
retire duplicate distributions. The four scientific assertions must remain
upstream with this immutable provenance. The existing duplicate-alias byte test
is an ownership check, not a physical threshold; built-wheel and sdist ownership
tests replace that check at the BASE boundary.

## Frozen repository profile

The complete source profile at
`eecff25b13343305a3f05310800503014667e80a` finished on October 19, 2026:
**2850 passed, 43 skipped, zero failures or errors**, in 620.83 seconds.
The [producer evidence and independent review](evidence/frozen-structural-profile-eecff25b/review.json)
retain the original JUnit, log, command/environment, before/after inventories,
owned-process cleanup and [artifact digests](evidence/frozen-structural-profile-eecff25b/SHA256.json).
All 1093 inventoried files were unchanged during execution and still matched
their recorded hashes when reviewed after resuming the workspace. The aggregate
source hash is `e443be04b29cada1673c8d19f48abb519c5a9247e08d7e269562f27705d37af8`.
The owned process boundary finished clean, with no remaining descendants.

The 43 skipped cases remain unrun: five require ABCluster, three require licensed
ORCA, one requires Psi4, and 34 require explicitly provisioned ML interpreters,
models or the pinned MACE parser. Every exact case and reason is retained in the
review. This profile uses the development execution backend with real xTB/CREST
available; it is not full Method Matrix acceptance, a production authority test,
student deployment, or complete SRS conformance. The separate installed-wheel
structural proof and its limits above remain applicable.

This follow-up adds evidence and documentation only; the tested source revision
is the commit named above. Remote publication and the subsequent BASE managed
installation still require verification. GitHub credentials were unavailable
when this workspace resumed, so the review does not assert a successful fetch
or push from the resumed environment.
