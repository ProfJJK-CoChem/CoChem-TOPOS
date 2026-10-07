# ORCA 6.1.1 VPT2 execution policy

TOPOS retains the reviewed B3LYP-D4/def2-TZVPP VPT2 scientific reference, with
ExtremeSCF, DEFGRID3, `Z_Tol 1e-14`, `HessianCutoff 1e-12`, and dimensionless
`AnharmDisp 0.05`. The unconstrained reference must have a separately verified
gradient below the strict stationarity threshold and a positive harmonic
Hessian with all vibrational frequencies at least 50 cm⁻¹. An explicit
semirigid applicability declaration remains required. Serial execution does
not establish these conditions by itself.

The official [ORCA 6.1 VPT2 manual][manual] requires tightly converged geometry,
SCF, CP-SCF and DFT grids, and restricts native VPT2 to nonlinear systems with
available analytic Hessians. It documents `%output Pickettname "pickett.txt"`
as an interface template for SPCAT, while stating that this feature is still
being refined and extended. A generated template is not proof of a completed
anharmonic force field or a validated SPCAT simulation.

## Native failure evidence

The retained [BASE native run 37666938546][run] used two ORCA MPI workers for
both the reference derivatives and native VPT2. Its extended water case
completed the initial SCF, reached “writing data to file in Pickett format,”
and printed an explicit `PROPERTIES` error while launching
`mpirun -np 2 ... orca_prop_mpi`. The licensed pytest water case stopped at
the same Pickett writer message and reached its execution deadline; its
stdout does not contain the explicit MPI error. Neither output reaches the
anharmonic analysis/displacement sequence or normal termination.

These observations locate the failure before the force-field calculation;
they do not, by themselves, prove a general ORCA MPI defect or establish that
serial execution succeeds. Unchanged historical input, stdout and stderr
bytes with hashes are retained in
[`tests/v010/fixtures/orca_vpt2_mpi_property_failure`][fixtures].

## Explicit serial compatibility policy

The protocol `orca-6.1.1-vpt2-serial-preserve-maxcore-v1` makes native VPT2 a
single-worker calculation before execution. It retains the caller's requested
allocation for the separate reference Engrad/Freq stages, and records the
requested and effective allocations in the recovery protocol and result.
Native VPT2 retains the original requested per-worker `%maxcore`, the total
RAM hard ceiling, and the original shared wall-clock deadline. For example,
a request for two workers and 4096 MiB yields reference `nprocs 2` and VPT2
`nprocs 1`, with `%maxcore 1536` in both. BASE authorizes the actual input deck's
1536 MiB per-worker allocation; it does not authorize an inflated 3072 MiB
MaxCore for the serial stage.

The policy changes execution parallelism without substituting a functional,
basis, dispersion correction, numerical grid, convergence threshold, or
displacement. It can reduce throughput; TOPOS does not extend the scientific
time tier when a serial calculation exceeds the original deadline. A request
for GPU native VPT2 continues to fail explicitly under the CPU-only native
ORCA contract.

Recovery rejects changed requested/effective resources, input or policy.
The completed receipt inventories the recovery manifest. Rotational correction
transfer independently reconstructs the native/reference inputs and verifies
the declared effective process allocation, raw derivatives and spectroscopy
tables. Changing execution-policy metadata cannot turn a failed or altered
calculation into accepted evidence.

## Remaining native validation

This policy requires its own native ORCA 6.1.1 acceptance. The focused diagnostic
must compare serial and two-worker initial SCF property writing, each with and
without Pickett output, while retaining all original process outputs. That
diagnostic isolates the writer and is not a complete VPT2 calculation.

The subsequent production native test must complete all VPT2 displacements,
produce and validate the native force-field/Hessian/geometry/spectroscopy
artifacts and Pickett template, pass rotational correction transfer, and
replay the exact completed stages. Historical failed MPI outputs and the
public furan parser fixture cannot clear this requirement. Until those
physical checks pass on the current source, VPT2 release acceptance remains
pending.

[manual]: https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/vpt2.html
[run]: https://github.com/ProfJJK-CoChem/CoChem-BASE/actions/runs/37666938546
[fixtures]: ../tests/v010/fixtures/orca_vpt2_mpi_property_failure/provenance.json
