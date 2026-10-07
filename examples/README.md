# Small xTB and CREST requests

These bounded examples exercise actual xTB 6.7.1 and CREST 3.0.2 calculations without an ORCA binary. xTB and CREST still have their own open-source licenses. Install the package and set `TOPOS_XTB_EXECUTABLE` and `TOPOS_CREST_EXECUTABLE` to the corresponding executable paths if they are not on `PATH`.

Run from the repository, using an output directory outside its source tree:

```bash
python -m topos run --request examples/water-search.json --output-root /tmp/topos-example-runs
python -m topos run --request examples/water-crest-mquick.json --output-root /tmp/topos-example-runs
python -m topos run --request examples/water-union.json --output-root /tmp/topos-example-runs
python -m topos run --request examples/water-dimer-crest-nci.json --output-root /tmp/topos-example-runs
```

| Request | What it exercises |
|---|---|
| `water-search.json` | Seeded jiggle–quench, common-level optimization, and duplicate classification. |
| `water-crest-mquick.json` | Reduced native CREST sampling, followed by xTB refinement and deduplication. |
| `water-union.json` | Both sampling sources, preserving source attribution through refinement and deduplication. |
| `water-dimer-crest-nci.json` | Reduced CREST sampling with NCI confinement and two explicit fragments, followed by refinement without that confinement. |

The CREST examples deliberately select `crest-mquick-v1`; this reduces sampling and disables genetic crossing. It does not establish conformational completeness. Native `crest-imtdgc-v1` and NCI `crest-nci-v1` protocols remain distinct options; they are never silently substituted for one another. The NCI profile requires `sampler_nci: true` and at least two declared fragments. NCI confinement biases sampling and is recorded as such.

`seed` controls TOPOS perturbations; the supported CREST build controls its own random initialization. `n_candidates` includes the input for jiggle–quench, but bounds native CREST frames separately from the input; union retains both sources. Retained candidates are refined with the same requested xTB protocol before comparisons. Deduplication tolerances and the electronic-energy window are explicit in each request. An energy window is not a free-energy population criterion.

Inspect each saved run's status, candidate ledger, commands, versions, and raw artifacts. A timeout or failed native calculation is retained as an unsuccessful result. These tiny fixtures demonstrate software integration; they do not validate the scientific accuracy of GFN2-xTB for a research system.
