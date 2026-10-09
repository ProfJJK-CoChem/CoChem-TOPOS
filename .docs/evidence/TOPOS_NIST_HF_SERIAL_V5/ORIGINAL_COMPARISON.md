# NIST rigid-rotor comparison: trans-formic acid

This is a descriptive main-isotopologue HF/def2-TZVPP native VPT2 component comparison. No accuracy threshold, calibration, formal scientific-reference pass or noncovalent 42-row qualification is assigned.

Outcome: **completed-component-comparison**. Elapsed calculation time: 1884.31 seconds.

The calculation used unchanged `orca-vpt2-reference-v1` gates, no dispersion or RIJCOSX, one CPU thread, a 4096 MiB total ceiling and one shared 7200-second deadline. Native MaxCore was predeclared as 3072 MB. Actual source commits were:

- BASE: `5ef80c9362ce5bd01f69fbe65b467f1bdb0e04ac`
- TOPOS: `4488faf5f4a236316b8cbd8f38d6be06e610c0b1`
- TORQ: `4f323800227dbde00ffb082bd6d9e44d851e1c7a`

Reviewed plan SHA256: `6a57d464af8172a50bc5e1671987d89ccbca808d4fc502f2806b9bf0bfe67294`.
Comparison SHA256: `498991c89d258d2666c432315b6c7cce9075f7c2ccdd25702c93eaabfa91c0c2`.

The experimental microwave reference is trans-HCOOH in its vibrational ground state, [Willemot et al., JPCRD 9 (1980), Table 1](https://srd.nist.gov/jpcrdreprint/1.555618.pdf). Its reported uncertainties are one estimated standard deviation. Equilibrium Be and vibrationally averaged B0 are reported separately.

| Constant | HF/VPT2 (MHz) | NIST B0 (MHz) | Signed error (MHz) | Absolute error (MHz) | Relative error (%) | NIST standard uncertainty (MHz) |
|---|---:|---:|---:|---:|---:|---:|
| A0 | 80140.519873 | 77512.2310 | +2628.288873 | 2628.288873 | +3.390805 | 0.0063 |
| B0 | 12453.378705 | 12055.1045 | +398.274205 | 398.274205 | +3.303781 | 0.0008 |
| C0 | 10762.249450 | 10416.1145 | +346.134950 | 346.134950 | +3.323072 | 0.0008 |

Native printed B0 resolution is 0.299792458 MHz. HF and perturbation-theory model error is distinct from the experimental measurement uncertainty; their ratio is not a probabilistic accuracy test.

Both independently calculated original-pose and actual native-pose Cartesian gradients passed the unchanged maximum 1e-7 and RMS 3e-8 Eh/bohr gates:
- native_frame_reference_hessian_result: max 1.0374e-08, RMS 4.4149033e-09 Eh/bohr.
- reference_hessian_result: max 3.368e-09, RMS 1.6240892e-09 Eh/bohr.

Actual native stdout and high-precision `.vpt2` masses identify 12C/16O/16O/1H/1H within the predeclared 5e-7 u gate. Literal five-decimal Hessian masses exactly equal those verified force-field masses rounded to the native representation; no native artifact or isotope was edited.

| Equilibrium constant | HF/VPT2 Be (MHz) | Independent NIST computed CCSD(T)/cc-pVTZ Be (MHz) | Signed difference (MHz) |
|---|---:|---:|---:|
| Ae | 80494.574765 | 77790.266199 | +2704.308567 |
| Be | 12531.024952 | 12022.477950 | +508.547002 |
| Ce | 10843.193413 | 10413.129773 | +430.063640 |

The equilibrium comparison uses a different electronic-structure model. Its conditional coordinate-rounding interval is retained in JSON and is not model uncertainty or an acceptance threshold. The newer [NIST-authored 2023 ground-state data](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=936857) are also compared in the retained JSON.

The preceding B3LYP v2 attempt remains unavailable due to strict Cartesian stationarity; HF MPI v3 remains unavailable after its native gradient-kernel crash. The unused v4 helpers and initial v5 namespace preflight failure are preserved. This v5 used independent frozen native Git clones and an explicit no-site-hook dependency bootstrap.

Full byte-identical Windows evidence: [comparison.json](<C:/Users/ansac/Documents/Codex/2026-10-08/codex-threads-01a113a5-0dfb-7736-b0e1-2/work/engines/nist-formic-frozen-hf-serial-v5/comparison.json>), [plan.json](<C:/Users/ansac/Documents/Codex/2026-10-08/codex-threads-01a113a5-0dfb-7736-b0e1-2/work/engines/nist-formic-frozen-hf-serial-v5/plan.json>), [controlled-copy index](<C:/Users/ansac/Documents/Codex/2026-10-08/codex-threads-01a113a5-0dfb-7736-b0e1-2/work/engines/nist-formic-frozen-hf-serial-v5/CONTROLLED-COPY-INDEX.json>).
