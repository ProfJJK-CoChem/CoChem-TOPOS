# Native ABCluster 3.4 rigid-monomer packing

`topos.abcluster.run_rigidmol` executes the genuine artificial-bee-colony
`rigidmol` program. It accepts explicit, balanced fragment states and an
atom-ID-indexed parameter set: partial charge in elementary charges, Lennard-
Jones epsilon in kJ/mol and sigma in Å. A nonempty parameter source is required.
It does not invent atom types, charges, virtual sites or transferable parameters.

The current contract supports gas-phase closed-shell fragments and CPU execution.
Every fragment must have a nonzero repulsive Lennard-Jones site, partial charges
must sum to the declared fragment charge, and declared bonds cannot cross the
partition. The input preserves all monomer coordinates; ABCluster chooses random
relative placements. Each native frame is mapped back to the original atom IDs,
and intramolecular distances and proper rotations are checked. Rigid packing
does not search monomer conformations or permit deformation.

The supplied amplitude is a native packing/search scale. It is not reported as a
physical confinement potential. Native Lennard-Jones repulsion and native local
optimization handle clashes. The native random stream is engine-controlled:
TOPOS does not claim that its separate jiggle seed seeds ABCluster.

The result contains **classical intermolecular scores**, including their native
kJ/mol values and explicit unit conversion. These exclude monomer internal
electronic energies. Sampled conformers require independent common-level quantum
optimization and TOPOS chemistry/deduplication checks before publication as
electronic results. Native local-minimum labels alone do not establish a quantum
stationary minimum, exhaustiveness or a global-minimum proof.

Native input, executable hash, version, requested population/generations/scout
limit/amplitude, raw logs, full saved ensemble and parameter source are retained.
Completion requires the pinned `rigidmol 3.4` banner, all requested generation
rows, normal termination, native best-score agreement and the complete reported
local-minimum inventory. A successful process exit alone is insufficient.
Completed searches are reused only after raw checksums and re-parsed frames
agree. Interrupted campaigns restart in fresh scratch, retaining previous raw
evidence; this is not a claim to resume the native random state.

## Acquisition and observed acceptance

The official [download page](https://zhjun-sci.com/abcluster.html) identifies
ABCluster 3.4, released 2026-01-07, and offers a direct Linux binary archive.
The separate source download requires registration. The manual describes the
program as free; this does not establish unrestricted redistribution rights.
No license file was found in the binary archive. The distribution was installed
locally for authorized testing and is not committed to this repository or wheel.

Observed archive SHA-256:
`00079b73409942fe694378124ce995ee027601e82d31f8c03c678f75fd2cafdd`.
Observed Linux `rigidmol` SHA-256:
`d535d2c3c1cef2e7ca33e0f11c16b102fc1405bcc8336840edb87b7fab777307`.
These are observed provenance checksums, not a vendor signature or universal
checksum for all platforms. Normal HTTPS verification was retained.

The focused native tests use the official distribution's neon and methanol
parameter facts. Neon dimer checks the analytic Lennard-Jones minimum energy
`−epsilon` and separation `2^(1/6)*sigma`; methanol dimer checks the preserved
internal geometry and recovery of interleaved input atom IDs. Additional tests
exercise cancellation, completed-search reuse, raw-output tamper rejection and
chemical-state mismatch rejection. `TOPOS_ABCLUSTER_EXECUTABLE` enables genuine
native acceptance; absence is a reported skip, never a simulated success.

BASE's executable identity is `abcluster`, mapped to the native `rigidmol` binary.
The companion registration patch adds the schema field and a component-specific
version probe. Bare invocation prints the version then returns status 1 for
missing input; that is a metadata probe only. Scientific acceptance requires
the real calculation above. Full production authority additionally requires
applying the BASE patch and rerunning its Stage 0 audit.

## Scientific and native references

- [Official rigidmol water-cluster input/output example](https://zhjun-sci.com/abcluster/doc/eg-h2o6.html).
- [Official CHARMM potential and parameter units](https://zhjun-sci.com/abcluster/doc/charmmff.html).
- [Official discussion of force-field applicability, hierarchical refinement and putative minima](https://zhjun-sci.com/abcluster/doc/theory.html).
- Zhang and Dolg, *Phys. Chem. Chem. Phys.* **17**, 24173–24181 (2015), [doi:10.1039/C5CP04060D](https://doi.org/10.1039/C5CP04060D).
- Zhang and Dolg, *Phys. Chem. Chem. Phys.* **18**, 3003–3010 (2016), [doi:10.1039/C5CP06313B](https://doi.org/10.1039/C5CP06313B).
