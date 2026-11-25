# CoChem-TOPOS User Guide

**CoChem-TOPOS** (Topological Optimization & Potential Surface Explorer) is the conformational search, non-covalent intermolecular (NCI) complex assembly, and reviewed ensemble handoff subsystem of the [CoChem](https://github.com/ProfJJK-CoChem) ecosystem.

For installation prerequisites, mandatory `CoChem-BASE` integration, and release-gate status, start with [README.md](../README.md).

## Documentation Map

| Guide | Purpose |
| --- | --- |
| [README.md](../README.md) | Repository front door, mandatory ecosystem install, CLI overview, and validation commands. |
| [Method Matrix](../wiki/Method_Matrix.md) | Authoritative 140-row method catalog (44 TOPOS rows, 96 TORQ rows) with source SHA-256 and capability rules. |
| [SRS](../.docs/CoChem-TOPOS_SRS.md) | Canonical requirements and scientific invariants. |
| [xTB & CREST Pathways](../.docs/TOPOS_OPEN_SOURCE_PATHWAYS.md) | Native GFN2-xTB and CREST 3.0.2 sampling protocols, seeds, and known limits. |
| [Counterpoise Contract](../.docs/TOPOS_COUNTERPOISE.md) | Five-leg ORCA counterpoise protocol, ghost-basis exports, and raw/CP/half-CP energetics. |
| [Matrix Recipes](../.docs/TOPOS_MATRIX_RECIPES.md) | Compiled complete recipes, partial branches, and reviewed ORCA/CFOUR alternatives. |
| [TORQ Handoff Specification](../.docs/TOPOS_TORQ_HANDOFF.md) | Producer handoff schema, consumer receipt verification, and local research bundle export. |

## 1. Conformer Search Pathways

- **GFN2-xTB (`xTB 6.7.1`)**: Executes genuine energies, analytical gradients, geometry optimization, and seeded jiggle-quench conformer discovery on Linux CPU.
- **CREST 3.0.2 + xTB 6.7.1**: Runs native full, reduced (`crest-mquick-v1`), and NCI conformational sampling, followed by common-level refinement and union with jiggle-quench ensembles while retaining original frames, exclusions, and source provenance.
- **Molecular ML Pathways**: Supports hash-bound AIMNet2/MACE predictions, committee interaction energies, and source-pinned CREST generic-calculator sampling under audited runtimes.
- **Symmetry & Deduplication**: Performs isotope-aware point-group verification, tolerance sensitivity checks, and enantiomer-grouping diagnostics while preserving unresolved chemistry.

## 2. Non-Covalent Intermolecular (NCI) Complex Assembly

- **Monomer-First Association**: Optimizes isolated monomers separately, constructs dimer/trimer/cluster complexes, and evaluates balanced common-method interaction, binding, and deformation energies.
- **Rigid-Fragment Constrained Optimization**: Preserves intramolecular monomer geometry with explicit convergence gates, trajectory intrafragment drift bounds, and residual frozen-force diagnostics.
- **Explicit Counterpoise (BSSE)**: Runs all five ORCA energy legs with explicit physical-fragment vs. ghost-basis separation and BASE-authorized native basis exports, reporting raw, CP-corrected, and half-CP interaction energies.
- **ABCluster 3.4**: Generates classical rigid-packing seeds with cited force-field parameters prior to independent quantum refinement.

## 3. `cochem-topos` CLI & `topos-ui` Quick Reference

### Environment & Diagnostics

```bash
cochem-topos doctor
cochem-topos doctor --verify-runtime --registry /path/to/Registry/cochem_system_config.json
cochem-topos capabilities
```

### Method Matrix Discovery & Planning (`wiki/Method_Matrix.md`)

```bash
cochem-topos matrix support
cochem-topos matrix list --owner TOPOS
cochem-topos matrix show T3O-30min
cochem-topos matrix plan T3O-30min --hardware hardware.json
```

### Execute, Inspect & Resume Calculations

```bash
cochem-topos request-schema
cochem-topos run --request examples/water-search.json --output-root /tmp/topos-runs
cochem-topos inspect /tmp/topos-runs/RUN_ID
cochem-topos resume --run-dir /tmp/topos-runs/RUN_ID
cochem-topos receive-base /path/to/module_handoff.json --output-root /tmp/topos-runs
```

Launch the interactive browser interface with `topos-ui`, or submit from a notebook via:

```python
from topos.ui import submit_request

result = submit_request(payload, output_root)
```

Exit codes: `0` completed action, `2` invalid input/action, `3` incomplete or unavailable execution.

## 4. Review & Downstream `CoChem-TORQ` / `CoChem-SPYFY` Handoffs

`CoChem-TOPOS` sits at the front of the rotational spectroscopy pipeline (**CoChem-TOPOS -> CoChem-TORQ -> CoChem-SPYFY / CoChem-GEOM**):

1. **Inspect & Review Candidates**:
   ```bash
   cochem-topos basket /tmp/topos-runs/RUN_ID
   cochem-topos review /tmp/topos-runs/RUN_ID --actor OPERATOR --reason "Verified low-energy conformer" ...
   ```
2. **Freeze & Export Producer Handoff for `CoChem-TORQ`**:
   ```bash
   cochem-topos handoff /tmp/topos-runs/RUN_ID ...
   cochem-topos export-handoff /tmp/topos-runs/RUN_ID --destination /tmp/topos-handoff/HANDOFF.json
   ```
   `CoChem-TORQ` ingests the versioned producer handoff in its isolated environment (`imported-awaiting-calculation`), executes high-level refinement, torsional scans, and ORCA/CFOUR VPT2 calculations, and emits a consumption receipt validated back in TOPOS via:
   ```bash
   cochem-topos receive-torq /tmp/topos-runs/RUN_ID --receipt RECEIPT.json
   ```
3. **Downstream `CoChem-SPYFY` Spectroscopy Integration**:
   Once `CoChem-TORQ` completes rotational/VPT2 refinement on the reviewed TOPOS conformers, TORQ exports versioned Pickett `.var`/`.int` seed packets and canonical `spyfy_manifest.json` / `.tar.zst` bundles for **CoChem-SPYFY** broadband microwave spectral assignment (SPCAT / Wang diagonalizer) and **CoChem-GEOM** semi-experimental $r_e^{\text{SE}}$ structure determination.
4. **Reproducible Local Research Bundles**:
   ```bash
   cochem-topos export /tmp/topos-runs/RUN_ID --destination /tmp/topos-bundle
   cochem-topos verify-export /tmp/topos-bundle
   python /tmp/topos-bundle/regenerate.py /tmp/topos-reproduced
   ```
