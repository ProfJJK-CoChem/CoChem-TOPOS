# TOPOS 0.1.0 native derivatives and entropy protocols

This document defines the implemented scientific contract. An implemented adapter,
a parser fixture and a completed licensed-engine calculation are different evidence.
Consult the run's actual attempts, raw artifacts, validation status and release gate
before describing a calculation as executed or a result as validated.

## Native ORCA harmonic frequencies

`topos.native_hessian.run_orca_hessian` executes an actual reference `Engrad` followed
by a separate `Freq` calculation at exactly the same geometry, electronic state and
Hamiltonian. It requires ORCA 6.1.1, checks the native electronic energies, parses the
complete Cartesian Hessian in hartree/bohr² and verifies the `.hess` atom ordering and
coordinates in bohr. It rejects missing, truncated, nonfinite, asymmetric and
misattributed Hessians. A normal process exit alone is insufficient.

The adapter follows the documented analytic HF/DFT domain. It does not substitute
numerical frequency calculations or route coupled-cluster/double-hybrid methods to
analytic Hessians. ORCA documents exclusions including RI-JK [1]. The matrix's
explicit numerical-derivative resolution remains a separately named alternative.

TOPOS independently projects rigid translations and rotations and mass weights the
electronic Cartesian Hessian with its declared isotope policy. Native `.hess` masses
are retained separately. The reference gradient establishes stationarity before a
harmonic minimum or thermal correction can be reported. Constrained stationary
points do not automatically receive full-dimensional RRHO thermochemistry.

Completed reference and Hessian stages can be reused after checking every raw
artifact checksum and the original geometry/method/binary/resource protocol.
Interrupted analytic Hessians restart in fresh scratch: ORCA explicitly states that
analytic frequency calculations themselves cannot resume partial Hessians [1].

## Matched native entropy sampling

`topos.entropy.run_matched_entropy` starts native `GOAT-ENTROPY` and CREST 3.0.2
`--entropy` from every identical supplied molecular geometry. Each pair has the
same GFN2-xTB potential, gas-phase state and explicit screening window. Native
random streams remain independent; identical starting geometries are not a claim
of identical pseudorandom sequences. The protocol currently requires 298.15 K:
CREST 3.0.2 evaluates its entropy stopping criterion at that temperature [3,4].

GOAT receives explicit `CONFTEMP`, `MINDELS` and `CONFDEGEN auto` settings. TOPOS
retains the native entropy/free-energy table and global-iteration trajectory [2].
CREST receives explicit entropy-growth and conformer-growth thresholds; both native
convergence flags are required. The conformer-count/entropy trajectory, extrapolation
status and separate `Sconf`, `delta Srrho`, `S(total)` and relative free energy are
preserved. A completed native process without the entropy observables or convergence
evidence cannot complete this protocol.

These reported entropies use different native rotamer/degeneracy definitions.
CREST's ensemble `delta Srrho` correction is not an absolute molecular RRHO entropy.
TOPOS does not pool these values, infer degeneracies from sampling hit counts, or
claim that a finite converged search is exhaustive. For an explicitly defined set
of electronic-energy states, `configurational_statistics` independently evaluates

\[
 p_i = g_i e^{-\Delta E_i/(k_B T)}/Z,\quad
 S_\mathrm{conf}=-R\sum_i p_i\ln(p_i/g_i),\quad
 F_\mathrm{conf}=-k_BT\ln Z.
\]

The caller supplies positive integer physical degeneracies and their definition.
Intrinsic conformer vibrational/rotational entropies are excluded from this formula.

Complete native searches survive recovery with verified artifacts. A previously
missing licensed ORCA executable can be provisioned without discarding a completed
independent CREST search. An already established executable identity cannot change
within the protocol. Incomplete native searches restart in fresh scratch. CREST's
internal scratch symlink to its own bias XYZ is archived as the exact target bytes
with the original link and checksum recorded; external/dangling symlinks are rejected.

## VPT2 spectroscopy and its domain

`topos.anharmonic.run_orca_vpt2` implements documented native ORCA VPT2 for a supplied,
unconstrained, nonlinear stationary minimum with explicit semirigid applicability
[5]. It requires the `orca-vpt2-reference-v1` profile: `ExtremeSCF`, `DEFGRID3`,
`Z_Tol 1e-14`, and optimization tolerances including `TolMaxG 1e-7` and `TolRMSG 3e-8`.
The native VPT2 job declares `AnharmDisp 0.05`, `HessianCutoff 1e-12` and retains the
complete `.vpt2` force field and raw native evidence. Displacement is configurable
within the adapter's declared range and is part of the recovery protocol.

The physical reference gradient must satisfy 1e-7 hartree/bohr and the independently
analyzed Hessian must identify a harmonic minimum. This conservative protocol rejects
modes below 50 cm⁻¹, explicit isotopic substitutions whose native reanalysis has not
been validated, linear molecules, and constrained geometries. The low-mode cutoff
is a stated applicability screen, not proof that perturbation theory is accurate.
ORCA itself excludes linear molecules and methods without analytic Hessians [5].

Parsed native observables are the vibrational-rotational alpha tensor, equilibrium
and ground-state rotational constants (`Be` and `B0`), harmonic/fundamental transition
pairs, and harmonic, anharmonic and rovibrational zero-point contributions. Checks
include `Be-B0 = 1/2 sum(alpha)`, the printed frequency differences and the separate
zero-point sum, with tolerances derived from native printed precision. Native
principal-axis ordering and native masses remain explicit. Anharmonic fundamentals
are not inserted into harmonic partition functions to invent anharmonic Gibbs values.

A public ORCA 6.1.0 output supplies the factual parser-format excerpt and source
checksum [6]. It is not evidence that this TOPOS adapter has run licensed ORCA 6.1.1.
Tests for genuine 6.1.1 water frequency/VPT2 calculations and completed-stage recovery
execute only when the licensed executable is explicitly provisioned.

The matrix's frozen-monomer R2 geometry is generally not a full-dimensional stationary
point. This implementation does not apply full-molecule VPT2 to that constrained
geometry. A separately specified, physically validated semirigid/projected anharmonic
protocol is needed for that case. Coupled-cluster energies do not establish a
coupled-cluster VPT2 calculation. Native partial VPT2 sub-Hessian recovery is not yet
validated; completed stages are reused, while interrupted VPT2 jobs restart in fresh
scratch with earlier raw attempts preserved.

## Sources

1. [ORCA 6.1 manual, Vibrational Frequencies](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/frequencies.html).
2. [ORCA 6.1 manual, GOAT](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/goat.html); [GOAT method paper](https://doi.org/10.1002/anie.202500393).
3. [CREST 3.0.2 native entropy implementation](https://github.com/crest-lab/crest/blob/v3.0.2/src/entropy/entropy.f90).
4. [CREST 3.0.2 entropy convergence implementation](https://github.com/crest-lab/crest/blob/v3.0.2/src/legacy_algos/confscript2_misc.f90); Pracht and Grimme, *Chemical Science* **12**, 6551–6568 (2021), [doi:10.1039/D1SC00621E](https://doi.org/10.1039/D1SC00621E).
5. [ORCA 6.1 manual, VPT2/GVPT2](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/vpt2.html); Amos et al., *J. Chem. Phys.* **95**, 8323–8336 (1991), [doi:10.1063/1.461259](https://doi.org/10.1063/1.461259).
6. [Public ORCA 6.1.0 furan VPT2 output](https://github.com/physicien/parser_vpt2/blob/main/data/VPT2_furan_vpt2.out). The repository's parser fixture contains numerical table excerpts and the full source SHA-256.
7. For the explicit B3LYP-D4 recipe: [Becke exchange](https://doi.org/10.1063/1.464913), [LYP correlation](https://doi.org/10.1103/PhysRevB.37.785), [D4 dispersion](https://doi.org/10.1063/1.5090222), and [def2 orbital bases](https://doi.org/10.1039/b508541a). Publication citations are added only for actual recorded executions.
