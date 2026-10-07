# Reviewed ORCA F12D/RI interaction-energy variant

The user authorized explicitly named ORCA alternatives with their scientific differences documented. `T5-3h` therefore has an opt-in reviewed variant, `source_resolution="orca-f12d-composite-interaction-v1"`. It preserves the archived method-matrix identity and records the separate reviewed-overlay SHA in the derived result. It does **not** implement the archived F12b Hamiltonian or inherit its A14 errors or timing guarantees.

## Exact five-component definition

For each unchanged complex or fragment geometry, the caller supplies five complete [`CorrelatedMethod`](../topos/correlated.py) protocols through [`OrcaF12CompositeProtocol`](../topos/orca_f12_composite.py):

| Component | Explicit native calculation |
|---|---|
| `base` | Frozen-core ORCA `CCSD(T)-F12D/RI` / jun-cc-pVTZ |
| `mp2_low` | Frozen-core `F12-MP2` **or** `F12-RI-MP2` / jun-cc-pVTZ |
| `mp2_high` | The same MP2-F12 variant / jun-cc-pVQZ |
| `cv_ae` | Conventional MP2, all-electron, cc-pwCVTZ |
| `cv_fc` | Conventional MP2, frozen-core, cc-pwCVTZ |

The F12 calculations require explicit CABS and, for RI methods, explicit correlation-fitting bases. RIJK requires a separately declared JK-fitting basis. No fitting basis or CABS is inferred from the orbital-basis name. The CC base and triple-zeta MP2 leg must share their CABS, HF fitting convention, and (when both use RI) correlation-fitting basis. All five legs use the same SCF convergence and integral convention; the two CV protocols must otherwise match exactly. Actual matched-basis HF reference energies are checked, so a different SCF solution cannot silently enter the correction.

The [ORCA 6.1 manual, explicitly correlated methods](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/mdci.html#explicitly-correlated-methods-f12-mp2-and-f12-ccsd-t) reports MP2-F12 as separate orbital MP2 correlation, F12 correlation correction, HF, and CABS-singles terms. It identifies CABS singles as an estimate of the underlying SCF basis error, and notes that this estimate typically undershoots the limit. The adapter verifies every printed arithmetic identity before using these quantities. It does not classify the CABS-singles correction as correlation energy.

Let `H_X = E_HF,X + E_CABS-singles,X` and `C_X = E_MP2-correlation,X + E_F12-correlation-correction,X`, with `X=3,4`. The exact declared extrapolation is:

```text
H_inf = H_3 + (H_4 - H_3) / (1 - exp(-alpha))
C_inf = C_3 + (C_4 - C_3) / (1 - (3/4)^p)
Delta_CBS = H_inf + C_inf - E_MP2-F12,junTZ
Delta_CV  = E_MP2,ae,pwCVTZ - E_MP2,fc,pwCVTZ
E_variant = E_CCSD(T)-F12D/RI,junTZ + Delta_CBS + Delta_CV
```

The caller must explicitly supply positive `hf_exponential_alpha`, `correlation_inverse_power`, `extrapolation_quantity="hf-plus-cabs-exponential-and-f12-correlation-power"`, and `convention="orca-f12d-ri-mp2-cbs-cv-v1"`. Numerically ill-conditioned denominators are rejected; amplification coefficients are retained in the output. These exponents are declared model parameters, **not** a fitted or benchmark-validated choice. Neither the manual's finite-basis “basis set limit estimate” label nor this extrapolation establishes a true complete-basis result. This reviewed approximation requires its own convergence and benchmark study before an accuracy claim.

## Observable and execution evidence

The reported quantity is `E_variant(complex) - sum(E_variant(fragment_i))`. Every fragment retains its coordinates from the complex (`frozen-inc`), atom mapping, explicit charge and spin. The partition must be complete and may not cut a declared covalent or coordination bond. All components and fragments use one exact protocol and verified ORCA executable identity. This is an electronic interaction energy; no geometry relaxation, counterpoise correction, monomer deformation, thermal contribution, Gibbs energy, or binding-energy claim is added.

Native components use the durable matrix ledger: input/protocol identities, commands, engine identity and raw artifact hashes are retained. Interrupted runs reuse only verified completed components. The global deadline and one shared per-geometry cap bound all five legs together. Missing native decomposition, inconsistent sums, changed artifacts, mismatched HF references, mixed executable identities, cancellation or expired budgets prevent derived-result publication.

Tests check exact protocol rejection, a transcribed official-manual decomposition, provenance tampering, analytical convergence models, and unchanged output from [genuine hosted ORCA 6.1.1 calculations on 2026-10-07](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37638685260). The [retained fixture provenance](../tests/v010/fixtures/orca_611_correlated/provenance.json) binds each complete native stdout to its hash, requested protocol, executable hash, and source artifact. These native water single points establish the unscaled `F12-E(CCSD(T))` result grammar, precise orbital HF references, and separate conventional/RI MP2-F12 partitions. Native ORCA repeats the MP2-F12 title for its setup banner and result table; only the complete physical partition is accepted. Its conventional and RI variants spell the CABS correction `to HF` and `to EHF`, respectively. Neighboring scaled-(T) results and duplicate or arithmetically inconsistent partitions remain rejected.

Local replay tests do not execute ORCA. Complete licensed execution of all five exact jun-basis/CV legs on a complex and its fragments remains a distinct acceptance requirement; the smaller native component runs and parser/arithmetic tests do not establish the full composite recipe or a benchmark accuracy.

## Scientific differences from the archived row

- The coupled-cluster base uses ORCA F12D/RI rather than F12b. Different approximations are not interchangeable labels.
- The CBS increment explicitly extrapolates HF+CABS and F12 correlation separately, using caller-declared exponents. It is not an undocumented total-energy power fit.
- Native ORCA basis/CABS/fitting and core conventions are recorded explicitly; their suitability for a particular chemical system is not inferred from a method-family name.
- The original junChS-F12b A14 MUE, RMSD and maximum-error figures are not assigned to this variant. Native convergence alone cannot establish those errors.

Implementation and analytical/parser tests: [`orca_f12_composite.py`](../topos/orca_f12_composite.py), [`test_orca_f12_composite.py`](../tests/v010/test_orca_f12_composite.py). Method/background source: ORCA manual above; related MP2 basis extrapolation study cited by that manual, Liakos, Izsák, Valeev and Neese, *Molecular Physics* **111** (2013), 2653–2662, [doi:10.1080/00268976.2013.811812](https://doi.org/10.1080/00268976.2013.811812). This citation supplies scientific context and is not evidence that the present five-component recipe was calibrated in that study.
