# Explicit molecular ML pathways

TOPOS executes molecular model predictions through a separately audited CoChem-BASE
Python silo. PyTorch and model packages are not loaded into the BASE UI process.
Each request supplies a `ModelManifest`: backend and exact package version, ordered
checkpoint paths and SHA-256 hashes, training-run identifiers, model family and
training method, declared element/charge/spin domain, numerical precision, source,
and license. A trained multihead MACE model additionally requires the explicit
target `head`; the replay head must not be silently selected.

The adapter independently checks actual checkpoint elements and supported spin
handling. MACE-OFF is restricted to neutral closed-shell molecules here. The
manifest's minimum-distance check is a collision guard, not a learned domain or
accuracy certificate. Periodicity, embedding and solvent are not inferred.

## Execution and quantities

- `topos.ml.MLRunner` loads one model committee per finite batch. BASE authorizes
  the actual interpreter, installed worker, package lock, CPU allocation and model
  hashes. GPU requests additionally identify one measured device and a VRAM limit;
  aggregate VRAM across several cards is not treated as a single-device allocation.
- `T2-1min` accepts an explicit rigid frozen-isolated-fragment grid with at least
  1000 points. It retains the exact Cartesian geometries, grid definition, model
  energies and gradients in an HDF5 surface shard. These are boundary-exploration
  observations, not quantitative well-depth validation.
- `T5-1min` subtracts frozen fragment energies separately for each committee member
  before calculating interaction-energy disagreement. This preserves covariance
  between a member's complex and fragment predictions. At least two distinct,
  independently trained members must be declared. One checkpoint produces no
  uncertainty value. The implemented no-culling policy retains every structure;
  it does not assert that the method-matrix G4 correlation audit has passed.
- `topos.ml_extopt` provides the persistent ORCA external-potential bridge. It
  records every callback geometry and member prediction, rejects point charges,
  and returns energy in hartree and gradients in hartree/bohr. The model stays
  loaded across callbacks. Generated structures still require the matrix's common
  electronic-structure refinement and deduplication before reporting.
- `topos.ml_training` requires authentic, immutable DFT energy/gradient evidence,
  explicit group-disjoint training/validation/test partitions and local replay
  data for multihead fine-tuning. A checkpoint and held-out errors are separate
  outputs. A dataset of 100–500 structures is a requested experiment size, not an
  accuracy guarantee. The complete T1-1w search recipe additionally requires every
  specified post-training sampler; training alone does not complete that row.

The force conversion is `gradient = -force_eV_per_angstrom × 0.529177210903 /
27.211386245988`. Committee standard deviations use `ddof=1`. They quantify model
disagreement, not calibrated prediction error, confidence intervals, or electronic
structure convergence. Model energies are never renamed as executed DFT results.

## Provisioning and licenses

Use BASE's reviewed ML silo provisioner and the exact lock accompanying the
installation. TOPOS never downloads weights during a calculation. Place the
reviewed checkpoint outside the application source tree and pass its absolute
path and independently recorded digest in the request manifest. The separately packaged `cochem-topos-ml-worker` wheel must be installed in the
audited silo with source bytes matching the controller. It must never share an
environment with the full TOPOS controller distribution. Use the [worker installation
procedure](TOPOS_INSTALLATION.md#isolated-ml-inference-worker); an injected
`PYTHONPATH` does not establish production authority.

The actual CPU verification used `mace-torch==0.3.16` and `torch==2.8.0+cpu`.
The previously supplied BASE pin `mace-torch==0.3.17` was unavailable on the package
index and is corrected in the companion BASE change. A CPU Torch installation
does not establish GPU or training readiness.

MACE code is MIT licensed. MACE-OFF checkpoint weights have a separate Academic
Software License; they are not bundled into TOPOS's Apache-2.0 wheel. Academic
deployment and redistribution must follow that model license, including any
fine-tuned derivatives. AIMNet model-family terms and citations must be retained
with the selected artifact rather than inferred from a different family's name.

One actual backend validation used the official MACE-OFF23 small checkpoint at
repository commit `91a78c5a9c300d1104700d9352c8bfe449227737`, SHA-256
`165cce4cfec5a34b9c64d4ebf95de15d71106bb584b7291c8470f0749977c46f`.
For water, 21 genuine inference frames checked the analytical forces against
central energy differences and rigid translations/rotations. Maximum derivative
disagreement was `3.56e-9 hartree/bohr`; the energy change under the tested rigid
transformations was zero at recorded precision. This is CPU model/units evidence,
not BASE silo, AIMNet, GPU, committee, training, or combined ORCA acceptance.

A separate genuine AIMNet2 verification used `aimnet==0.2.0`, `torch==2.8.0+cpu`,
`numpy==2.5.3` and `ase==3.29.0`, with four distinct official `wb97m-d3` checkpoints
whose recorded hashes matched the pinned AIMNet registry. The manifest explicitly
identifies the training Hamiltonian as `wB97M-D3(BJ)/def2-TZVPP`; the reported
energies are model predictions, not executed DFT results. No checkpoint weights
are included in the TOPOS distribution.

For water, 75 actual committee inference frames tested fourth-order energy
finite-difference gradients at three step pairs and rigid transformations.
Maximum gradient discrepancies were `1.65e-6`, `2.00e-6` and `6.55e-6 Eh/bohr`;
the report retains the float32 energy-roundoff bound and each actual step size.
The tested rotation changed energy by `3.52e-8 Eh` and the transformed gradient
by `1.69e-8 Eh/bohr`. The tested translation changed energy by `2.55e-8 Eh` and
gradient by `2.58e-7 Eh/bohr`. The four-member energy standard deviation was
`1.16e-4 Eh` (`ddof=1`), which is uncalibrated model disagreement.

The [unaltered verification receipt](evidence/TOPOS_AIMNET_CPU_VERIFICATION_20261007.json)
and [hash-matched raw predictions](evidence/TOPOS_AIMNET_CPU_RAW_20261007.json)
retain all model identities, numerical checks, versions, worker hash and scope.
This verifies CPU model inference and derivative/unit consistency for the tested
molecule. It does not establish BASE authorization, GPU execution, broader-domain
accuracy, a DFT benchmark or the accuracy of uncertainty estimates. The BASE
production path and its separately audited interpreter have independent evidence.

The subsequent BASE-managed
[worker08 refresh](evidence/TOPOS_WORKER08_REFRESH.json) records actual execution
of 21 MACE CPU frames, 75 four-member AIMNet CPU frames and three persistent MACE
callbacks. Its [distribution manifest](evidence/TOPOS_WORKER08_DISTRIBUTION.json)
binds all 84 worker source files to candidate12 source commit
`053c827638b3481c5c3d645856b69d50c47b387f` and worker wheel SHA-256
`7c5471d12c37d8912403bccfb7cafeea03d03a797ad27cc8d20aad07ad990b71`.
The [MACE](evidence/TOPOS_WORKER08_MACE_CPU.json),
[AIMNet](evidence/TOPOS_WORKER08_AIMNET_CPU.json) and
[persistent callback](evidence/TOPOS_WORKER08_MACE_PERSISTENT_CPU.json)
receipts retain the individual checks. This refresh verifies the recorded CPU
execution paths; no physical GPU execution was verified.

## Sources

1. [Official MACE-OFF repository, model license and citation](https://github.com/ACEsuit/mace-off/tree/91a78c5a9c300d1104700d9352c8bfe449227737).
2. Kovács et al., [MACE-OFF23: Transferable Machine Learning Force Fields for Organic Molecules](https://arxiv.org/abs/2312.15211).
3. [Official MACE source and fine-tuning implementation](https://github.com/ACEsuit/mace/tree/v0.3.16).
4. [Official AIMNet source and hash-pinned model registry](https://github.com/isayevlab/aimnetcentral/tree/718ffd62babf92d91b3b14cb909b01308e4c5b1d).
5. [ORCA 6.1 external-method workflow](https://www.faccts.de/docs/orca/6.1/tutorials/workflows/extopt.html).
6. [Supplied method matrix, Sections 10 and 13](../wiki/Method_Matrix.md).

7. Anstine, Zubatyuk and Isayev, [AIMNet2: A Neural Network Potential to Meet Your Neutral, Charged, Organic, and Elemental-Organic Needs](https://doi.org/10.1039/D4SC08572H), *Chemical Science* **16**, 10228–10244 (2025); citation verified in the official AIMNet project README.
