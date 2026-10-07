# Persistent molecular ML inside ORCA GOAT-EXPLORE

`topos.ml_extopt.run_goat_extopt` implements the method matrix section 10 external
file contract with a persistent, explicitly provisioned model committee. It does
not download models. Both the native ORCA driver and ML interpreter run through
CoChem-BASE authority. The matrix caller supplies a complete `ModelManifest` and
an `ExtOptAllocation` with separate CPU-thread/RAM budgets for the concurrent ML
server and ORCA process group; their sums must fit the original request. GPU index
and allocator memory are explicit and enforced by the BASE/worker GPU boundary.

The audited worker loads each committee member once. MACE requests preserve an
explicit checkpoint head; multi-head models without a selection and unknown heads
are rejected. AIMNet2 requests retain the model's native float32 precision and
reject unsupported spin or element domains using checkpoint metadata.

The server's directory is mode 0700 and its UNIX socket is mode 0600. The callback
protocol is local, finite (10,000 requests by default; explicitly configurable up to 1,000,000),
byte bounded and timeout bounded. Receipt storage has its own allocation (1 GiB
default, explicitly configurable from 4 MiB to 64 GiB), accounting for 4 KiB
allocation blocks before admitting further calls. A budget stop retains complete
prior evidence and cannot certify a completed native sampler.
Each call records the native external input text, raw XYZ text and hashes, preserved
molecular identity, and the actual member energies/gradients before the committee
mean. Requests cannot silently change atom mapping, charge, spin, embedding or model
identity. Model files and the installed worker/client are checked against their
bound hashes. The generated wrapper uses the audited interpreter in Python isolated
mode; models are never reloaded by individual callback processes.

ORCA supplies `basename_EXT.extinp.tmp` and coordinates in angstrom. The wrapper
writes `basename_EXT.engrad` with energy in hartree and Cartesian gradient in
hartree/bohr, with the required force-to-gradient sign and length conversion:

\[
 E_\mathrm{Eh}=E_\mathrm{eV}/27.211386245988,\qquad
 g_\mathrm{Eh/bohr}=-F_\mathrm{eV/angstrom}\,0.529177210903/27.211386245988.
\]

The external-file reader rejects point charges, mismatched electronic state,
changed elements/order, nonfinite coordinates and files outside the native attempt.
Output is replaced atomically after receiving a complete matching model result.

The native deck is `GOAT-EXPLORE ExtOpt TightOpt`, with explicit `%scf TolE 1e-5`,
matching geometry energy tolerance, fixed wrapper path, native screening window and
bounded global iterations. GOAT-EXPLORE can break bonds. Every returned frame remains
an enumeration observation requiring subsequent common-level refinement, chemistry
validation and the method matrix's Stage A deduplication. ML energies are never
relabeled as executed DFT or used to claim spectroscopic geometry quality. Committee
spread remains uncalibrated model disagreement.

Validation includes genuine supplied MACE-OFF23 CPU inference through the persistent
socket and the actual ORCA-format callback writer: multiple geometries, a central
energy-difference gradient check, raw per-call evidence, model-load count, socket
permissions and rejection of an altered atom mapping. This is model/socket/file-
interface evidence. A combined licensed ORCA 6.1.1 + BASE-audited ML-silo calculation,
AIMNet2 execution and GPU execution require their separately provisioned acceptance
runs; parser or transport tests do not establish those results.

References: [method matrix section 10](../wiki/Method_Matrix.md),
[ORCA 6.1 external optimization manual](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/optimizations.html),
[ORCA GOAT manual](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/goat.html), and
[FACCTs AIMNet2 precision/server guidance](https://github.com/faccts/orca-external-tools/blob/main/readmes/aimnet2.md).
The actual checkpoint manifest records its own method, source, license and domain.
