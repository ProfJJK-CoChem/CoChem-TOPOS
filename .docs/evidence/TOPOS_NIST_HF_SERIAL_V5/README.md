# NIST trans-formic-acid component comparison

The serial HF/def2-TZVPP native VPT2 calculation completed with the predeclared strict stationarity, derivative-association and main-isotopologue checks. It overpredicts all three experimental ground-state constants by about 3.3–3.4%. Numerical validity does not establish spectroscopic model accuracy. No accuracy threshold, formal SRS-029 clearance, calibration or 42-row noncovalent qualification is assigned.

| Constant | HF/VPT2 (MHz) | NIST B0 (MHz) | Signed error (MHz) | Signed relative error |
|---|---:|---:|---:|---:|
| A0 | 80140.519873 | 77512.2310 | +2628.288873 | +3.390805% |
| B0 | 12453.378705 | 12055.1045 | +398.274205 | +3.303781% |
| C0 | 10762.249450 | 10416.1145 | +346.134950 | +3.323072% |

Experimental values are trans-HCOOH microwave ground-state constants from [Willemot et al., JPCRD 9 (1980), Table 1](https://srd.nist.gov/jpcrdreprint/1.555618.pdf). Experimental standard uncertainties are 0.0063, 0.0008 and 0.0008 MHz, respectively; they are distinct from HF/VPT2 model error. Native printed resolution is 0.299792458 MHz.

The actual calculation finished at `2026-10-09T02:09:04.447523+00:00` after 1884.313 seconds. It used one thread, a 4096 MiB total allocation, predeclared native MaxCore 3072 MB and one shared 7200-second deadline. The reviewed plan SHA256 is `6a57d464af8172a50bc5e1671987d89ccbca808d4fc502f2806b9bf0bfe67294`.

Actual frozen source identities remain:

- BASE: `5ef80c9362ce5bd01f69fbe65b467f1bdb0e04ac`
- TOPOS: `4488faf5f4a236316b8cbd8f38d6be06e610c0b1`
- TORQ: `4f323800227dbde00ffb082bd6d9e44d851e1c7a`

The original-pose Cartesian gradient had maximum 3.368e-9 and RMS 1.624089242e-9 Eh/bohr; the native-pose check had maximum 1.0374e-8 and RMS 4.414903306e-9. Both passed the unchanged maximum 1e-7 and RMS 3e-8 gates. Native stdout and high-precision force-field masses identify 12C/16O/16O/1H/1H. Literal five-decimal Hessian masses exactly match those verified masses rounded to their native representation, with zero added floating tolerance.

The [original comparison JSON](comparison.json), [original human report](ORIGINAL_COMPARISON.md) and [independent literal Decimal arithmetic audit](literal-arithmetic-audit.json) are copied byte-for-byte. Their [portable record index](PORTABLE-INDEX.json) binds hashes and sizes. Native stdout rows were independently converted using exactly 29979.2458 MHz per inverse centimetre, and all reported errors agree.

These compact records retain original local artifact locators. They do not package, relabel or provide a portable retrieval promise for the full raw native evidence. The complete 165-file raw snapshot remains in the controlled Windows workstation copy; no native binary, model, raw displacement artifact or reference PDF is included here. The earlier B3LYP stationarity failure and MPI HF crash remain separate retained failures. The independent computed CCSD(T)/cc-pVTZ equilibrium comparison in JSON is a different method/observable, and its conditional coordinate-rounding interval is not model uncertainty.
