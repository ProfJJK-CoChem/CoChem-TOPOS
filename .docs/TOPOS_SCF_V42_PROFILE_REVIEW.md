# Explicit ordinary ORCA numerical profile v4.2

`orca-mapping-v4.2` retains the v4.1 Hamiltonian, basis/auxiliary basis, DEFGRID3 grids, density/orbital targets, five geometry thresholds, independent final-gradient guard, and original method/time budgets. It adds only this electronic convergence block to each ordinary energy, optimization, and gradient deck:

```text
%scf
  ConvCheckMode 0
  TolE 1e-10
end
```

The original geometry `%geom TolE 1e-7` remains unchanged. SCF `TolE` controls the electronic energy change between SCF cycles; geometry `TolE` controls geometry optimization. The explicit `orca-vpt2-reference-v1` profile retains ExtremeSCF, Z_Tol 1e-14, and its stricter geometry criteria; v4.2 cannot be substituted for that reference profile. Native analytic VV10/NL Hessians and VPT2 remain unsupported in ORCA 6.1; supported numerical derivative routes retain their separate interpretation.

## Native scientific evidence and limits

The genuine original diagnostic [BASE run 37708503109](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37708503109) retained a failing TightSCF mode-two optimization/cold-gradient pair. Its corrected energies differed by −7.423279981821906e-7 hartree, exceeding the unchanged 2e-7 guard. Mode zero alone repaired that physical pair, but its independently cold-started gradient had RMS density change 7.1272e-9 against the unchanged 5e-9 target. That failed result is preserved as a failure.

The ORCA 6.1 manual describes `ConvCheckMode 0` as requiring all convergence criteria, with an overachievement exception. A native “SCF converged” marker therefore does not itself establish every required density target. The same manual defines the `%scf TolE` keyword and lists the TightSCF default electronic tolerance of 1e-8. Tightening only this electronic tolerance was tested to seek additional electronic convergence without loosening any scientific guard.[1]

The single genuine follow-up [BASE run 37713499250](https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37713499250) passed its predeclared independent verifier. It used ORCA 6.1.1, wB97X-V/def2-TZVPP/def2/J, RIJCOSX and unchanged DEFGRID3. The primary and additional independently cold-started gradients each differed from the optimized energy by +5.583004281106696e-9 hartree, below 2e-7. Both cold gradients achieved SCF energy change −1.7195e-11 against 1e-10, MAX density 1.7468e-9 against 1e-7, and RMS density 1.7473e-10 against 5e-9. All five optimizer conditions, independent gradient limits, grids, exact native property poses, and active SCF criteria passed. The independent shared native wall span was 158.638017 seconds within 900 seconds, with 2 CPU workers and 2048 MiB unchanged.

These are historical-source water consistency measurements. They establish neither reference accuracy nor transferability to other species, bases, methods, Hessians, VPT2, R2, or the complete matrix. The prior control was retained rather than rerun on the same host, so the comparison is not a contemporaneous same-host experiment. No current-source native or release acceptance is implied.

The verifier receipt SHA256 is `7876cda4be0cc91dc91a3561d2f01398703cc46ac75ad08dafe2f04597d03b30`; original scientific ZIP SHA256 is `d430386c14d25b8da0757d84147e5e029e2298b08f24caf898553c7b9edd84c0`. Unedited positive and negative stdout fixtures retain their original run/archive provenance. No historical result is relabeled as a completed v4.2 production result.

## Rendering, provenance, recovery, and timing

The versioned definition and its canonical SHA256 are recorded in new-profile native result metadata. The new profile checks actual printed `All-Criteria`, all six exact SCF targets, and achieved active energy/density/orbital residuals. Under genuine SOSCF, the last DIIS residual may retain its earlier switching value; it is preserved separately instead of being misrepresented as a current SOSCF residual. When DIIS is the active final converger, its residual remains mandatory. Unknown or incomplete native tables fail closed.

Independent gradient and analytic-Hessian recovery reparse the bound native evidence and compare the exact profile receipt. Numerical-Hessian recovery, optimization/reference imports, ML label import, and counterpoise/reference validation retain the same new-profile checks. Existing method/protocol identities already include `profile_id`; new runtime calibration additionally requires the exact numerical definition SHA256. Old profiles, caches, and timing samples keep their old identity and cannot become new-profile results by changing a default or adding a pass flag.

The ordinary native generator supplies the same method to optimization and its fresh final gradient. Supported analytic Freq inherits that generator; finite-difference Hessian gradients inherit the same method/profile through their declared protocol. Strict VPT2 reference rendering remains separately gated and unchanged. The archived matrix source table is retained; current compiled routing activation is a separate reviewed numerical implementation change.

More SCF iterations may increase computation time. No timing scaling or universal cost claim is justified by the water experiment. Every attempt, workflow and derivative retains its original deadline; the new profile may yield partial or timed-out results under shorter tiers. New matched hardware/method/profile measurements are required for runtime estimates.

## Bounded native continuation on the workstation

An ordinary energy or analytic-gradient job that terminates normally but misses an active final SCF residual may continue once from its own freshly generated GBW. The input deck, numerical targets, method, original shared deadline and cancellation state remain unchanged. Optimization orbitals are never imported into an independent cold-gradient job. Missing or changed targets, unknown final convergers, failed native processes and optimization jobs do not qualify.

The controller retains the initial input, GBW, derivatives and both native streams under `initial-scf/`, records their exact hashes in `scf-continuation.json`, and requires native AutoStart evidence before accepting the continuation. The final native output must independently pass the existing numerical-profile parser. This changes solver execution only; it supplies no reference-accuracy or complete-matrix pass. Earlier failed native results remain retained.

## Sources

1. FACCTs, *ORCA 6.1 Manual*, “Convergence Tolerances,” including `%scf TolE`, TightSCF targets and `ConvCheckMode` semantics: <https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/scf.html#convergence-tolerances>. The exact retrieved document used for preparation is retained outside the repository as `scf-mode0-tole-investigation-20261008/official-orca61-scf-source.md`, SHA256 `6586b7ca35d5f95560618384f85332202271d7d9bfd4f1ca6373fb977df3f7c1`.
2. FACCTs, *ORCA 6.1 Manual*, VV10 nonlocal correction and derivative limitations: <https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/dispersioncorrections.html#non-local-dispersion-correction-vv10-dft-nl>.
