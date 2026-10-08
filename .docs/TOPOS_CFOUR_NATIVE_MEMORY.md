# CFOUR native workspace and density reload

The total TOPOS memory allocation remains an upper bound enforced by BASE.
Native CFOUR `MEMORY_SIZE` covers its working array; it does not include static
program data, shared libraries, thread stacks or BLAS scratch buffers.

The verified CFOUR 2.1 xvdint executable has 444,508,040 bytes of static BSS.
Its bundled OpenBLAS allocates a separate 134,221,824-byte scratch buffer. At a
2048 MiB process limit, assigning the old 1536 MiB native workspace can make
BLAS repeatedly attempt an allocation that cannot fit the address-space bound.
A native child under that bound reproduced the spin inside
`blas_memory_alloc → dgemm → xgemm → dsofso → getdens → onedrv`. The same child
without the bound completed; the installed licensed runtime was unchanged.

The `cfour-static-blas-headroom-v1` allocation reserves 768 MiB for one thread,
plus 128 MiB per additional allocated thread. Native workspace is the smaller
of 75% of the total limit and the bytes remaining after the reservation. The
input states integer words, and the execution metadata records native,
reserved and total bytes. Nonpositive workspace is rejected before launch.
The thread allocation, address-space/RSS bounds, cancellation and deadline
remain enforced by BASE. For 2048 MiB and two threads, native workspace is
1152 MiB, with 896 MiB reserved inside that same total limit.

A native memory-only sweep completed identical water MP2/PVDZ gradients with
256, 512, 768, 1024 and 1280 MiB native workspace and byte-identical GRD output;
1536 MiB reached its original 30-second diagnostic deadline. The reservation
also completed native gradients at 1024 MiB/one thread and 2048 MiB/two and
four threads. It completed the original six-atom water-dimer gradient at
2048 MiB/two threads.

CFOUR 2.1 MP2, CCSD and CCSD(T) analytic gradients can contain a second native
`SCF has converged.` event. This is the zero-iteration density reload after
`xprepfc2f`, using OLDMOS/MOREAD, followed by `xvtran`, `xintprc` and `xfillfc`.
TOPOS accepts this only when every module has its own successful completion,
both markers belong to exactly two xvscf invocations, the first SCF has its
requested active convergence control, and the second has zero maximum and
observed iterations with the exact same printed SCF energy. Other versions,
methods, operations and repeated, unrelated or truncated SCF events cannot
borrow this rule. Native method/core/basis controls, correlated-energy
completion and indexed geometry checks remain required.

Pinned QCEngine 0.51.0 does not recognize this runtime's direct indexed
`O #1 x y z` stdout gradient layout. A supplemental parser requires exactly
one complete table inside one successfully completed xvdint module, with
sequential atom indices, matching element identities, three finite components
and the terminating gradient norm. The independently read stdout gradient
must agree with the separately parsed native GRD at the existing 6e-8
Hartree/bohr tolerance. Missing or malformed native gradients remain errors.

The regression fixtures in
`tests/v010/fixtures/cfour_2_1_mp2_density_reload` contain unmodified owned
scientific output for water and the six-atom dimer at MP2, CCSD and CCSD(T).
Their provenance records input/output hashes, exact runtime identity and
resource allocations. They contain no licensed source, executables, GENBAS,
ECPDATA or native scratch. These one-evaluation regressions support the
transport and parser changes; they do not establish a completed matrix row,
independent accuracy, final optimization or release acceptance.
