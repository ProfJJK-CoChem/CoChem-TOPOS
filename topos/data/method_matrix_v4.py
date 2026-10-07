"""Lossless table extraction from wiki/Method_Matrix.md; never executable engine input.

Generated from the repository source. References and numerical claims remain source
claims; runtime routing separately validates scientific and adapter applicability.
"""

SOURCE_PATH = 'wiki/Method_Matrix.md'
SOURCE_SHA256 = 'd4b382c88d9734eef844e6dcaafdca06e5901c482fa0f4c17ca1efeb4f5c989d'
SOURCE_REVISION = "method-matrix-v4-2026-08-09"
ROWS = [{'row_id': 'T1-10s',
  'source_line': 2934,
  'tier': '10 s',
  'method_text': 'Hand-enumerated binding topologies, then `! XTB2 TightOpt` per seed — ORCA/xtb',
  'delivers': 'an ensemble of 3–9 seeds; **no accuracy claim**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'no search at all; a topology missed by hand is invisible to every later row',
  'expansion': {'source_line': 2949,
                'core_hours_text': '0.022',
                'workflow': '`! XTB2 TightOpt`; or `xtb --opt vtight --strict`',
                'state_in': 'seed `.xyz`; `.CHRG`/`.UHF`',
                'state_out': '`xtbopt.xyz`, `.xtbw` — **R**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '<0.5 GB / negligible',
                'license': 'free',
                'teaching_setup': 'Yes',
                'benchmark_error': 'GFN2-xTB S22 COM max 32 pm',
                'notes': '`--strict` mandatory in a chain; hand enumeration is the only completeness '
                         'argument'}},
 {'row_id': 'T1-1min',
  'source_line': 2935,
  'tier': '1 min',
  'method_text': '`! GOAT XTB2 PAL8`, GFN-FF uphill — ORCA',
  'delivers': 'full GOAT ensemble at N ≤ 10 (~100 × N_at optimisations `[M]`)',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': "semi-empirical ranking only; GFN2-xTB's S22 centre-of-mass maximum error is 32 pm `[M]`, "
                 '≈14 % in B',
  'expansion': {'source_line': 2950,
                'core_hours_text': '0.13',
                'workflow': '`%goat maxen 12.0 confdegen auto gfnuphill gfnff end`',
                'state_in': 'seed `.xyz`',
                'state_out': 'ensemble `.xyz`, energy on the comment line — **D** (decompose by seed)',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '1 GB / 1 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'Yes',
                'benchmark_error': 'as above',
                'notes': 'set `MAXEN` explicitly — the manual gives 6.0 in the table and 12.0 in the '
                         'text'}},
 {'row_id': 'T1-30min',
  'source_line': 2936,
  'tier': '30 min',
  'method_text': '`! GOAT-EXPLORE ExtOpt` + `oet_server aimnet2 -d cuda` — ORCA + AIMNet2',
  'delivers': 'free-topology enumeration, many seeds in parallel; **Stage A dedup runs here**',
  'concurrency_text': '**G**',
  'product_text': 'A',
  'limitations': 'float32 noise (~4 × 10⁻⁶ Eh) and interaction-energy errors of **3.5–7.3 kcal/mol on S30L '
                 '`[M]`** — an enumerator, not a judge',
  'expansion': {'source_line': 2951,
                'core_hours_text': '4',
                'workflow': '`! GOAT-EXPLORE ExtOpt TightOpt PAL8` + `%scf TolE 1e-5 end` + `%method '
                            'ProgExt … end`',
                'state_in': 'seeds `.xyz`; MLFF checkpoint',
                'state_out': '`.finalensemble.xyz`, `.globalminimum.xyz`, `*.confrot.xyz` — **D**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '2 GB host / 1–2 GB VRAM',
                'license': 'free model, ORCA academic',
                'teaching_setup': 'Yes (CPU model only)',
                'benchmark_error': 'S30L 7.31 kcal/mol; PLA15 29.9 `[M]`',
                'notes': '`! TightOpt` + `TolE 1e-5`; server mode; two venvs (AIMNet2 and UMA conflict); '
                         '**never report these energies**'}},
 {'row_id': 'T1-1h',
  'source_line': 2937,
  'tier': '1 h',
  'method_text': '`crest --nci --gfn2 --ewin 12 --nocross --noreftopo`, one run per seed — CREST',
  'delivers': 'an independent second ensemble',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'the RMSD bias can still dissociate the complex; hydrogen bonds disrupted after **4.2 ps '
                 '`[M]`**; a different seed found a conformer **50 kJ/mol lower**',
  'expansion': {'source_line': 2952,
                'core_hours_text': '8',
                'workflow': '`crest seed.xyz --nci --gfn2 --ewin 12 --nocross --noreftopo --T 8`',
                'state_in': 'seed `.xyz`',
                'state_out': '`crest_conformers.xyz`, `crest_rotamers_*.xyz` — **D** (no general restart)',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '2 GB / 2 GB',
                'license': 'free, LGPL-3.0',
                'teaching_setup': 'Yes',
                'benchmark_error': '50 kJ/mol seed sensitivity `[M]`',
                'notes': '≥3 chemically distinct seeds; `--wscal 0.9` or reduced `kpush` if it still '
                         'dissociates'}},
 {'row_id': 'T1-3h',
  'source_line': 2938,
  'tier': '3 h',
  'method_text': 'union merge → `crest --screen` → r²SCAN-3c re-optimisation → `crest --cregen` — CREST + '
                 'ORCA',
  'delivers': 'the production ensemble; **Stage B dedup**; ensemble energies ±1–3 kcal/mol `[E]`',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'a union is not a proof; report per-engine and overlap counts',
  'expansion': {'source_line': 2953,
                'core_hours_text': '24',
                'workflow': '`cat *.finalensemble.xyz crest_conformers.xyz > union.xyz`; `crest --screen`; '
                            '`! r2SCAN-3c TightOpt Freq` ; `crest --cregen … --bthr 0.001`',
                'state_in': 'both ensembles',
                'state_out': 'one deduplicated QM ensemble — **R** for the optimisations, **D** for the '
                             'searches',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '2 GB per rank / 3 GB',
                'license': 'mixed',
                'teaching_setup': 'Yes (at risk)',
                'benchmark_error': 'r²SCAN-3c ROT34 AMAX 1.5 % `[M]`',
                'notes': 're-optimise the union at one common level *before* CREGEN; report GOAT-only, '
                         'CREST-only, both, union'}},
 {'row_id': 'T1-12h',
  'source_line': 2939,
  'tier': '12 h',
  'method_text': '`! GOAT r2SCAN-3c`, `%PAL NPROCS 16`, on the 2–3 leading isomers — ORCA',
  'delivers': 'QM-level search around the assigned minima',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': '**at risk on 16 threads**: ORCA advises 32 cores and warns of "a few days" for an '
                 'r²SCAN-3c GOAT',
  'expansion': {'source_line': 2954,
                'core_hours_text': '96',
                'workflow': '`! GOAT r2SCAN-3c` + `%PAL NPROCS 16`',
                'state_in': 'leading isomers `.xyz`',
                'state_out': 'refined ensemble + `.gbw` per conformer — **D**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '3 GB per rank / 6 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'No (>6 h)',
                'benchmark_error': '—',
                'notes': 'if the budget will not stretch, run `GOAT-COARSE` with rigid fragments instead'}},
 {'row_id': 'T1-1d',
  'source_line': 2940,
  'tier': '1 d',
  'method_text': '`! GOAT-ENTROPY XTB2` + `crest --entropy` on the same seeds — ORCA + CREST',
  'delivers': '**convergence evidence**: ΔS_conf < 0.1 cal mol⁻¹ K⁻¹ against a converged CREST ensemble '
              'entropy',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'the two S_conf values are not comparable unless `CONFDEGEN auto` is set — GOAT defaults '
                 'to g_i = 1',
  'expansion': {'source_line': 2955,
                'core_hours_text': '192',
                'workflow': '`! GOAT-ENTROPY XTB2`; `crest --entropy`',
                'state_in': 'same seeds',
                'state_out': 'S_conf trajectories — **D**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '2 GB / 2 GB',
                'license': 'mixed',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': 'set `CONFDEGEN auto`; this row produces *evidence of convergence*, not new '
                         'structures'}},
 {'row_id': 'T1-3d',
  'source_line': 2941,
  'tier': '3 d',
  'method_text': 'ωB97X-V/def2-TZVPP re-optimisation of Stage-B survivors; **no new searching** — ORCA',
  'delivers': 'geometries good enough to feed a 0.1 % constant; ΔE ±0.3–1.0 kcal/mol `[E]`',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'the search is no longer the bottleneck; this row buys ranking, not coverage',
  'expansion': {'source_line': 2956,
                'core_hours_text': '576',
                'workflow': '`! wB97X-V def2-TZVPP def2/J RIJCOSX TightOpt` + §4.4 `%geom` + `InHess XTB2`',
                'state_in': 'Stage-B ensemble `.xyz`, `.gbw`',
                'state_out': 'per-isomer `.xyz`, `.gbw`, `.opt` — **R**',
                'frozen_monomer': 'frozen-iso available (recipe R1/R2)',
                'memory_scratch': '2 GB per rank / 4 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': 'ωB97X-D rare-gas RMSD 36.34 pm `[M]`',
                'notes': 'seed each optimisation with an MLFF `.carthess` (§8A.3) for ~2–2.5× fewer cycles '
                         '`[E]`'}},
 {'row_id': 'T1-1w',
  'source_line': 2942,
  'tier': '1 w',
  'method_text': 'fine-tune MACE or AIMNet2 on 100–500 system-specific DFT points, re-run GOAT + CREST — '
                 'MACE + ORCA',
  'delivers': 'insurance against a missed basin; a reusable checkpoint',
  'concurrency_text': '**G**, then S',
  'product_text': 'A',
  'limitations': 'fine-tuning is **documented as experimental** and states no required dataset size — '
                 '**`n.a.`**; buys no improvement in any reported constant',
  'expansion': {'source_line': 2957,
                'core_hours_text': '1,344',
                'workflow': '`mace_run_train --foundation_model=small --multiheads_finetuning=True`',
                'state_in': '100–500 DFT points; ensemble',
                'state_out': 'fine-tuned checkpoint — **R**; **archive it, it is reusable state for every '
                             'later campaign**',
                'frozen_monomer': '—',
                'memory_scratch': '8 GB host / 8 GB VRAM',
                'license': 'free',
                'teaching_setup': 'No',
                'benchmark_error': 'required dataset size **`n.a.`**',
                'notes': 'multihead replay "prevents catastrophic forgetting" and is the recommended mode; '
                         'mark the row experimental'}},
 {'row_id': 'T1-1mo',
  'source_line': 2943,
  'tier': '1 mo',
  'method_text': 'exhaustive union: all seeds × both engines × `--v4` / `GOAT-DIVERSITY`, then '
                 'coupled-cluster re-ranking',
  'delivers': 'the maximum coverage claim available',
  'concurrency_text': '**G**, then **S**',
  'product_text': 'A',
  'limitations': '**partly obsolete**: running two GOATs concurrently on two devices from the same start '
                 'delivers much of this diversity for zero extra wall time (§8A.2). Retain only as '
                 'completeness insurance',
  'expansion': {'source_line': 2958,
                'core_hours_text': '5,760 @ 8 cores; 21,504 @ 128',
                'workflow': 'all seeds × both engines × `--v4` / `GOAT-DIVERSITY`; DLPNO re-ranking',
                'state_in': 'everything above',
                'state_out': 'maximal ensemble — **D**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '8 GB / 20 GB',
                'license': 'mixed',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': '**dominated for every reported observable**; the concurrent two-device union '
                         '(§8A.2) delivers most of it free'}},
 {'row_id': 'T2-10s',
  'source_line': 2970,
  'tier': '10 s',
  'method_text': 'semi-empirical relaxed 1-D scan, 20–40 points — xtb/ORCA',
  'delivers': 'well topology only; **no energy claim**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'a tight-binding intermolecular curve is qualitative',
  'expansion': {'source_line': 2985,
                'core_hours_text': '0.022',
                'workflow': '`xtb --opt vtight` along R',
                'state_in': 'seed `.xyz`',
                'state_out': 'scan `.xyz` — **D**',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': '<0.5 GB',
                'license': 'free',
                'teaching_setup': 'Yes',
                'benchmark_error': '—',
                'notes': 'nothing to parallelise at this size'}},
 {'row_id': 'T2-1min',
  'source_line': 2971,
  'tier': '1 min',
  'method_text': 'dense MLFF scan, 10³ points, to bound the well — MACE/AIMNet2',
  'delivers': 'the boundaries of the well, not its depth',
  'concurrency_text': '**G**',
  'product_text': 'A',
  'limitations': '**the one row where FP32 is legitimate**; use the boundaries, not the energies',
  'expansion': {'source_line': 2986,
                'core_hours_text': '0.13',
                'workflow': 'ASE + MLFF, 10³ points, batched on the GPU',
                'state_in': 'seed `.xyz`; model key',
                'state_out': 'dense grid → HDF5 shard — **D**',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': '1 GB VRAM',
                'license': 'free',
                'teaching_setup': 'Yes (CPU)',
                'benchmark_error': 'S30L 7.31 kcal/mol',
                'notes': "the 3090's 35.6 TFLOPS FP32 is the right number **only for this row**"}},
 {'row_id': 'T2-30min',
  'source_line': 2972,
  'tier': '30 min',
  'method_text': 'composite meta-GGA scan, ~200 points — ORCA r²SCAN-3c',
  'delivers': 'relative energies ±1.5–3 kcal/mol `[E]`',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'no diffuse functions; the long-range tail is unreliable',
  'expansion': {'source_line': 2987,
                'core_hours_text': '4',
                'workflow': '**`parallel -j 16` single-rank, not `PAL16`**',
                'state_in': "previous point's `.gbw` (`! MORead`)",
                'state_out': 'per-point `.gbw` + HDF5 shard — **D**',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': '1 GB per job / 1 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'Yes',
                'benchmark_error': 'r²SCAN-3c ROT34 AMAX 1.5 %',
                'notes': 'v3 omitted the concurrency instruction on this row; it is now explicit'}},
 {'row_id': 'T2-1h',
  'source_line': 2973,
  'tier': '1 h',
  'method_text': '2-D relaxed (R, θ) grid, 960 points, ωB97X-V/def2-TZVPP — ORCA',
  'delivers': 'a 2-D surface, ±1–2 kcal/mol `[E]`',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'relaxed scans hide hysteresis; run both scan directions and compare',
  'expansion': {'source_line': 2988,
                'core_hours_text': '8',
                'workflow': '`seq 0 959 \\| parallel -j 16 --joblog pes.log --eta ./pes_run.sh {}`; '
                            'recover with `--resume-failed`',
                'state_in': 'scan `.xyz` / `.gbw`',
                'state_out': 'HDF5 `points/<method>/…` — **D**',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': '2 GB per job / 3 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'Yes (one 6 h job)',
                'benchmark_error': '—',
                'notes': 'neighbour `.gbw` reuse is free: each displaced point is a small perturbation of '
                         'a converged one'}},
 {'row_id': 'T2-3h',
  'source_line': 2974,
  'tier': '3 h',
  'method_text': '1-D sinc-DVR on 30–40 points — SciPy',
  'delivers': 'band origins ±20–50 cm⁻¹ `[E]`',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': '**a 40 × 40 DVR on a GPU is ~70× *slower* than the CPU `[M]`**',
  'expansion': {'source_line': 2989,
                'core_hours_text': '24',
                'workflow': 'SciPy sinc-DVR; **if JAX is used, `JAX_ENABLE_X64=True` on line 1**',
                'state_in': 'fitted 1-D potential',
                'state_out': 'eigenvalues — **R** (cheap to redo)',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': '1 GB',
                'license': 'free',
                'teaching_setup': 'Yes',
                'benchmark_error': '—',
                'notes': 'JAX "by default enforces single-precision numbers" and the flag "only works on '
                         'startup"; FP32 noise is ~10⁻¹–10⁰ cm⁻¹ `[D]`'}},
 {'row_id': 'T2-12h',
  'source_line': 2975,
  'tier': '12 h',
  'method_text': '**Δ-learning + active learning**: DFT/PIP base + CCSD(T)-F12 correction — ORCA + MOLPIPx',
  'delivers': 'fitted surface, **RMS 3–10 cm⁻¹ `[E]`**, from 2,000 DFT + 300–800 CC points',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': "the fitted surface's error where the acquisition function never looked is **not** "
                 'bounded by the AL residual',
  'expansion': {'source_line': 2990,
                'core_hours_text': '96',
                'workflow': '2,000 DFT points (`parallel -j 16`) + 300–800 CC points; fit with MOLPIPx for '
                            'a differentiable GPU surface',
                'state_in': 'HDF5 `delta_pairs(low, high)`',
                'state_out': 'fitted Δ-surface + held-out residual — **R**',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': '3 GB per job / 8 GB',
                'license': 'free / ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': 'fit residual must be reported in cm⁻¹',
                'notes': "**was v3's 1 w row.** Cite the 200-CCSD(T)-point demonstration and the 208-PIP "
                         'ethanol correction'}},
 {'row_id': 'T2-1d',
  'source_line': 2976,
  'tier': '1 d',
  'method_text': 'committee-uncertainty active learning with an explicit acquisition function — ORCA + NN '
                 'committee',
  'delivers': '300–800 actively selected points from a 2,000-point pool; surface RMS 5–20 cm⁻¹ `[E]`',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': '**variance-maximisation alone plateaus an order of magnitude worse `[M]`**; a held-out '
                 'validation grid is mandatory',
  'expansion': {'source_line': 2991,
                'core_hours_text': '192',
                'workflow': 'committee of two neural surfaces; escalate on the weighted square energy '
                            'difference',
                'state_in': '2,000-point DFT pool; committee checkpoint',
                'state_out': 'escalated points; updated committee — **D**',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': '3 GB per job / 8 GB',
                'license': 'free',
                'teaching_setup': 'No',
                'benchmark_error': 'H₂O–He: 472 points → 0.3253 cm⁻¹ `[M]`',
                'notes': '**budget the held-out grid separately**; a 500-point surface with a 100-point '
                         'held-out set is not a spectroscopic surface'}},
 {'row_id': 'T2-3d',
  'source_line': 2977,
  'tier': '3 d',
  'method_text': '3-D rigid-monomer DVR, matrix-free Lanczos, on 500 actively selected points',
  'delivers': 'band origins ±5–20 cm⁻¹ `[E]`',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'basis 40 × 24 × 24 = 23,040; **the GPU gives ~1–2× here, i.e. nothing `[M]`**',
  'expansion': {'source_line': 2992,
                'core_hours_text': '576 @ 8 cores',
                'workflow': '500 DLPNO points at 15 min each = 125 core-h ⇒ **10.4 h wall at `-j 16` '
                            '`[D]`**, or 29 min on 1,024 HPC cores',
                'state_in': 'HDF5 geometry list; neighbour `.gbw`',
                'state_out': '500 CC energies in HDF5; DVR eigenvalues — **D**',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': '3 GB per job / 5–20 GB per point',
                'license': 'ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': 'Inductiva RTX 3090 Lanczos: 0.67× at dim 10⁴, 4.2× at 10⁵ `[M]`',
                'notes': 'v3\'s "125 h on one rank" read as the row\'s cost; it is the *serial* number. '
                         '**Correct optimisations are CUDA-graph capture of the fixed-shape matvec and '
                         'block Lanczos, not a faster card**'}},
 {'row_id': 'T2-1w',
  'source_line': 2978,
  'tier': '1 w',
  'method_text': '6-D rigid-monomer variational treatment on a Δ-learned surface',
  'delivers': 'band origins ±1–5 cm⁻¹ `[E]`',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'dense 3-D at 40³ needs 32.8 GB and does not fit 24 GB; matrix-free is mandatory',
  'expansion': {'source_line': 2993,
                'core_hours_text': '1,344 @ 8 cores',
                'workflow': 'matrix-free Lanczos / block Davidson on the Δ-learned 6-D surface',
                'state_in': 'Δ-surface',
                'state_out': 'VRT manifold — **R**',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': '8 GB / 20 GB',
                'license': 'free',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': 'one matvec is ~14 µs of FP64 arithmetic against a 5–15 µs launch overhead `[D]` '
                         '— this is why the GPU underdelivers here'}},
 {'row_id': 'T2-1mo',
  'source_line': 2979,
  'tier': '1 mo',
  'method_text': 'full-dimensional flexible-monomer surface — autoPES/flex-autoPES or PIP',
  'delivers': '**9.1 cm⁻¹ (site–site, 4,758–11,311 points) `[M]`**, or 0.4–6.3 cm⁻¹ (PIP, 3–5 × 10⁴ '
              'points) `[M]`',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': '**not a workstation tier**: 5 × 10⁴ CC points is 26–43 days here against 12–20 h on '
                 '1,024 HPC cores `[D]`',
  'expansion': {'source_line': 2994,
                'core_hours_text': '5,760 @ 8 cores; 92,160 @ 128',
                'workflow': 'autoPES/flex-autoPES (needs **ORCA 3.0.1, Dalton 2.0, SAPT2016**), or PIP via '
                            'MSA-2.0',
                'state_in': 'HDF5 full point set',
                'state_out': 'analytic surface file, 500 MB – 5 GB',
                'frozen_monomer': 'relaxed (full-dimensional)',
                'memory_scratch': '16 GB / 200 GB',
                'license': 'autoPES licence **`n.a.`**',
                'teaching_setup': 'No',
                'benchmark_error': 'flex-autoPES (H₂O)₂ 9.1 cm⁻¹; stationary-point RMSE 7.6 cm⁻¹ vs '
                                   'CCSD(T) 1.8 `[M]`',
                'notes': "**HPC only.** autoPES's grid is `NFP × 6 × 100/(100 − TEST PCT)`, proportional "
                         'to the number of fit parameters, not to atom count; out of the box it is serial '
                         '(`MAX SIM PT` default 1)'}},
 {'row_id': 'T3O-10s',
  'source_line': 3004,
  'tier': '10 s',
  'method_text': 'GFN2-xTB equilibrium structure — xtb/ORCA',
  'delivers': '**B_e ±3–15 % `[M]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'intermonomer separations from tight binding are systematically off by 14 pm MAD on S22',
  'expansion': {'source_line': 3019,
                'core_hours_text': '0.022',
                'workflow': '`! XTB2 TightOpt`; or `xtb --opt vtight --strict`',
                'state_in': 'seed `.xyz`',
                'state_out': '`xtbopt.xyz`, `.xtbw` — **R**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '<0.5 GB',
                'license': 'free',
                'teaching_setup': 'Yes',
                'benchmark_error': 'pyrrole–Ne: B3LYP/6-311++G(d,p) 46.34 %; MP2/aVTZ 25.66 % `[M]`',
                'notes': 'escalate before quoting anything; use for search seeding and isotopologue '
                         'bookkeeping'}},
 {'row_id': 'T3O-1min',
  'source_line': 3005,
  'tier': '1 min',
  'method_text': '**recipe R1**: frozen high-level or experimental monomers + r²SCAN-3c intermolecular '
                 'optimisation — ORCA',
  'delivers': '**B_e ±1–3 %; A to <0.2 % `[D]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'no diffuse functions, so the intermolecular distance is the dominant error',
  'expansion': {'source_line': 3020,
                'core_hours_text': '0.13',
                'workflow': '`! r2SCAN-3c TightSCF DefGrid3` + §4.4 `%geom` + `%geom Constraints {…} end`. '
                            '**No `D4`, no `gCP`** — both are inside the composite',
                'state_in': '`xtbopt.xyz`; `InHess XTB2`',
                'state_out': '`.xyz`, `.gbw`, `.opt` — **R**',
                'frozen_monomer': '**frozen-iso**',
                'memory_scratch': '1 GB per rank / 1 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'Yes',
                'benchmark_error': 'r²SCAN-3c ROT34 AMAX 1.5 % `[M]`',
                'notes': '**strictly dominates the unconstrained r²SCAN-3c row: same cost, same B, A '
                         'improved by ~1.5 pp.** Pareto: frontier'}},
 {'row_id': 'T3O-30min',
  'source_line': 3006,
  'tier': '30 min',
  'method_text': 'ωB97X-V/def2-TZVPP full optimisation — ORCA',
  'delivers': '**B_e ±0.5–3 % `[E]`**',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': '**BSSE contracts the complex: +4.1 pm ≈ 2.8 % in B at plain cc-pVTZ `[M]`**',
  'expansion': {'source_line': 3021,
                'core_hours_text': '4',
                'workflow': '`! wB97X-V def2-TZVPP def2/J RIJCOSX TightSCF DefGrid3` + §4.4 `%geom` + '
                            '`InHess XTB2`',
                'state_in': '`s(1min).xyz` + `.gbw` (`! MORead`) + `.opt`',
                'state_out': '`.xyz`, `.gbw`, `.opt`; exported `.bas` for the CP triplet — **R**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '2 GB per rank / 3 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'Yes',
                'benchmark_error': 'ωB97X-D rare-gas RMSD 36.34 pm `[M]`',
                'notes': 'do not counterpoise below triple zeta; at triple zeta and above use '
                         '`BSSEOptimization.cmp` and report both structures'}},
 {'row_id': 'T3O-1h',
  'source_line': 3007,
  'tier': '1 h',
  'method_text': 'ωB97X-V/jun-cc-pVTZ, diffuse functions in the basis — ORCA',
  'delivers': '**B_e ±0.5–2 % `[E]`**',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'diffuse sets on hydrogen cause near-linear dependence; the failure is loud, not silent',
  'expansion': {'source_line': 3022,
                'core_hours_text': '8',
                'workflow': '`! wB97X-V jun-cc-pVTZ def2/J RIJCOSX TightSCF DefGrid3`; raise `%scf '
                            'SThresh` if the overlap spectrum is ill-conditioned',
                'state_in': 'TZ `.gbw` cascade',
                'state_out': '`.xyz`, `.gbw`, `.opt` — **R**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '2 GB per rank / 4 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'Yes',
                'benchmark_error': 'as above',
                'notes': 'use calendar sets (jun-, may-) rather than aug-; jun-TZ carries ~27 % fewer '
                         "functions. **Removed from v3's dominated list**: cc-pVTZ → cc-pVDZ-F12 (paired "
                         'with CABS) cuts the CP discrepancy from 4.1 to 1.1 pm'}},
 {'row_id': 'T3O-3h',
  'source_line': 3008,
  'tier': '3 h',
  'method_text': '**recipe R2**: frozen CCSD(T)-class monomers + ωB97M-V/def2-QZVPP intermolecular + 3-leg '
                 'counterpoise + VPT2 — ORCA',
  'delivers': '**B_e ±0.4–1.5 %; ±0.3–0.5 % semi-rigid; A to <0.2 % `[E]`**, plus ΔB_vib',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'quadruple zeta is the DFT complete-basis limit for non-covalent interactions — this is '
                 'the end of the DFT road',
  'expansion': {'source_line': 3023,
                'core_hours_text': '24',
                'workflow': '`! wB97M-V def2-QZVPP def2/J RIJCOSX TightSCF DefGrid3` + §4.4 `%geom` + '
                            'constraints; then 3 × `! DLPNO-CCSD(T1) TightPNO cc-pVDZ-F12 (paired with '
                            'CABS)`; then `! wB97X-V def2-TZVPP Freq VPT2 VeryTightSCF`',
                'state_in': '`s(30min).xyz` + `.gbw` (TZ→QZ projection)',
                'state_out': '`.xyz`, `.gbw`, `.opt`, `.hess` — the geometry that feeds Tables 4 and 5 — '
                             '**R**',
                'frozen_monomer': '**frozen-iso**',
                'memory_scratch': '3 GB per rank / 6 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'Yes (at risk)',
                'benchmark_error': 'ωB97X-V A21 RMSD 0.58 pm; rare gases 7.91 pm `[M]`',
                'notes': '**the best de novo accuracy-per-core-hour row in the document.** Report the '
                         'residual gradient on the frozen coordinates'}},
 {'row_id': 'T3O-12h',
  'source_line': 3009,
  'tier': '12 h',
  'method_text': '**recipe R4: junChS (jun-cc-pVnZ CBS+CV composite)** — ORCA compound scripts',
  'delivers': '**B_e, MAE 0.13 % for ≤16 atoms `[M]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'delivers **B_e only**; ChS is not BSSE-free; parameter-wise addition assumes '
                 'near-transferable intramolecular coordinates',
  'expansion': {'source_line': 3024,
                'core_hours_text': '96',
                'workflow': 'R[fc-CCSD(T)/jun-cc-pVTZ] + ΔR[MP2/CBS(T→Q), n⁻³] + ΔR[MP2/CV, cc-pwCVTZ], '
                            'parameter-wise',
                'state_in': '`s(3h).xyz` + `.gbw`',
                'state_out': 'composite geometry; component energies — **D** (no MDCI restart)',
                'frozen_monomer': 'frozen-iso or relaxed',
                'memory_scratch': '3 GB per rank / 8 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': 'ChS MAE 0.13 % in B_e, ≤16 atoms `[M]`',
                'notes': 'anchored on pyridine–H₂O at 7 h 47 min (cc-pVTZ) / 16 h 12 min (jun-cc-pVTZ) on '
                         "64 CPUs `[M]`. **Replaces v3's double-hybrid geometry row**, which had no vdW "
                         'benchmark'}},
 {'row_id': 'T3O-1d',
  'source_line': 3010,
  'tier': '1 d',
  'method_text': 'MPQC CCSD(T)-F12 numerical-gradient optimisation — ORCA',
  'delivers': '**B_e ±0.3–0.8 % floppy, ±0.15–0.5 % semi-rigid `[D]`**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**no analytic DLPNO gradient**: each gradient is 6N = 60 single points, 25 cycles ≈ '
                 '1,500 points ≈ 375 core-h. **Dominated by T3O-12h**',
  'expansion': {'source_line': 3025,
                'core_hours_text': '192',
                'workflow': '`! MPQC CCSD(T)-F12 TightPNO cc-pVDZ-F12 (paired with CABS) NumGrad Opt '
                            'TightSCF` + §4.4 `%geom`',
                'state_in': '`s(3h).xyz` + `.gbw`; per-displacement neighbour `.gbw`',
                'state_out': '`.xyz`; 60 displacement single points per cycle — **D**, run them as '
                             'independent jobs',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '3 GB per rank / 5–20 GB per point',
                'license': 'ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': 'geometry maximum **`n.a.`**',
                'notes': '**Dominated by T3O-12h**: 375 core-h for a floppy geometry no better than '
                         'T3O-3h, against a 0.13 %-MAE composite at 6–20 h'}},
 {'row_id': 'T3O-3d',
  'source_line': 3011,
  'tier': '3 d',
  'method_text': 'canonical CCSD(T)/cc-pVTZ-F12 (paired with CABS: OptRI [Yousaf & Peterson, J. Chem. '
                 'Phys. 129, 184108 (2008)], JKFIT, MP2FIT), AUTOCI analytic gradients — ORCA (Setup 3)',
  'delivers': '**B_e ±0.3–1 % `[M]`, with a warning**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**fc-CCSD(T)/cc-pVQZ gave −6.56 % in A_e for a C₅H₂ isomer `[M]`**; frozen core is a '
                 '−0.81 % bias in B_e',
  'expansion': {'source_line': 3026,
                'core_hours_text': '576 @ 8 cores; 9,216 @ 128',
                'workflow': '`! AUTOCI-CCSD(T) cc-pVTZ-F12 (paired with CABS: OptRI [Yousaf & Peterson, J. '
                            'Chem. Phys. 129, 184108 (2008)], JKFIT, MP2FIT) Opt TightSCF`; AO-direct '
                            'mandatory',
                'state_in': '`s(3h).xyz` + `.gbw`',
                'state_out': '`.xyz`, `.gbw` — **D** in ORCA, **R** in CFOUR',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '8 GB per rank / **99 GB four-external + 25 GB three-external if '
                                  'integral-conventional**',
                'license': 'ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': '−6.56 % in A_e `[M]`',
                'notes': "~596 basis functions sits at ORCA's 500–600 practical ceiling. **`fc` vs `ae` is "
                         'not a detail: the core-correlation effect on A_e was 1.0 pp with inconsistent '
                         'sign.** Prefer CFOUR (T3C-3d) or junChS-F12 (Molpro)'}},
 {'row_id': 'T3O-1w',
  'source_line': 3012,
  'tier': '1 w',
  'method_text': 'composite CCSD(T)/CBS + Δcore + ΔT + ΔQ (the ChS/HEAT family) — ORCA compound scripts or '
                 'CFOUR',
  'delivers': '**B_e ±0.04 % semi-rigid closed-shell `[M]`; 1–2 % floppy `[D]`**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'the 0.04 % figure is a semi-rigid closed-shell number and does not transfer to a floppy '
                 'complex',
  'expansion': {'source_line': 3027,
                'core_hours_text': '1,344 @ 8; 21,504 @ 128',
                'workflow': 'CCSD(T)/cc-pV∞Z + Δcore + ΔT + ΔQ, counterpoise-bracketed',
                'state_in': 'CFOUR `JOBARC`; component energies',
                'state_out': 'composite geometry; `FCMFINAL` — **R** in CFOUR',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '16 GB / 200 GB',
                'license': 'CFOUR academic registration',
                'teaching_setup': 'No',
                'benchmark_error': 'composite MAE 0.04 %, SD 0.07 % — **semi-rigid closed-shell** `[M]`',
                'notes': '**this row is the ChS/HEAT-class composite; the family names are given so a '
                         'reader can find the literature.** For a floppy complex quote 1–2 % and route to '
                         'Product B'}},
 {'row_id': 'T3O-1mo',
  'source_line': 3013,
  'tier': '1 mo',
  'method_text': 'explicitly correlated reference single points; F12 geometry **requires Molpro**',
  'delivers': '**B_e — no better than T3O-1w for the reported constants**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '"F12 gradients are not available" is true in ORCA 6.1 and false in general. **Dominated '
                 'by T3O-1w**; retained for method benchmarking',
  'expansion': {'source_line': 3028,
                'core_hours_text': '5,760 @ 8; 92,160 @ 128',
                'workflow': 'Molpro DF-CCSD(T)-F12 optimisation, or `! CCSD(T)-F12D/RI cc-pVTZ-F12` single '
                            'points in ORCA',
                'state_in': 'Molpro or ORCA geometry',
                'state_out': 'reference geometry — **D**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '32 GB / 500 GB',
                'license': '**Molpro commercial**; ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': 'as T3O-1w',
                'notes': '**junChS-F12 (recipe R3) dominates this row**: "one order of magnitude faster '
                         'than the CBS+CV counterparts" with SE100 MUE(r) 0.0011 Å `[M]`'}},
 {'row_id': 'T3C-10s',
  'source_line': 3034,
  'tier': '10 s',
  'method_text': '—',
  'delivers': '—',
  'concurrency_text': '—',
  'product_text': '—',
  'limitations': '**This track cannot fill this tier.** CFOUR has no semi-empirical or force-field engine '
                 'and no DFT on its public feature list. Use `T3O-10s`',
  'expansion': {'source_line': 3049,
                'core_hours_text': '—',
                'workflow': '—',
                'state_in': '—',
                'state_out': '—',
                'frozen_monomer': '—',
                'memory_scratch': '—',
                'license': '—',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': '**track gap, stated rather than hidden.** Escalate to the ORCA track'}},
 {'row_id': 'T3C-1min',
  'source_line': 3035,
  'tier': '1 min',
  'method_text': '—',
  'delivers': '—',
  'concurrency_text': '—',
  'product_text': '—',
  'limitations': '**Cannot fill.** No global optimiser; the cheapest meaningful CFOUR job is an SCF or MP2 '
                 'single point. Use `T3O-1min`',
  'expansion': {'source_line': 3049,
                'core_hours_text': '—',
                'workflow': '—',
                'state_in': '—',
                'state_out': '—',
                'frozen_monomer': '—',
                'memory_scratch': '—',
                'license': '—',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': '**track gap, stated rather than hidden.** Escalate to the ORCA track'}},
 {'row_id': 'T3C-30min',
  'source_line': 3036,
  'tier': '30 min',
  'method_text': 'MP2/cc-pVDZ optimisation, `COORDINATES=INTERNAL` with `*` on the variables',
  'delivers': 'a structural sanity check; **no B_e claim**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': '**MP2 is not worth running in parallel in CFOUR**',
  'expansion': {'source_line': 3050,
                'core_hours_text': '4',
                'workflow': '`*CFOUR(CALC=MP2,BASIS=PVDZ,COORDINATES=INTERNAL, '
                            'MEMORY_SIZE=32,MEM_UNIT=GB)` with `*` after the variables',
                'state_in': '`ZMAT` + `GENBAS`',
                'state_out': '`JOBARC`, `JAINDX`, `OPTARC` — **R**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': 'global 32 GB / 20 GB',
                'license': 'CFOUR academic (wet signature)',
                'teaching_setup': '**No** — licence does not scale to a class',
                'benchmark_error': '—',
                'notes': '`MEMORY_SIZE` is a **global** allocation defaulting to ≈762 MB; raise it or the '
                         'job thrashes'}},
 {'row_id': 'T3C-1h',
  'source_line': 3037,
  'tier': '1 h',
  'method_text': 'CCSD(T)/cc-pVTZ single point with `PROPS=FIRST_ORDER`',
  'delivers': 'dipole components, EFG → χ; no geometry',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'requires the EFG → nuclear-quadrupole-coupling conversion by hand',
  'expansion': {'source_line': 3051,
                'core_hours_text': '8',
                'workflow': 'add `PROPS=FIRST_ORDER`',
                'state_in': '`JOBARC`',
                'state_out': 'first-order properties — **R**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '32 GB / 30 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': 'χ conversion factor 234.96474 documented',
                'notes': 'ORCA cannot do this at CCSD(T): "an unrelaxed density for CCSD(T) is NOT '
                         'available"'}},
 {'row_id': 'T3C-3h',
  'source_line': 3038,
  'tier': '3 h',
  'method_text': 'CCSD(T)/cc-pVTZ geometry optimisation, analytic gradients',
  'delivers': '**B_e, MAE 0.90 % `[M]`** at this basis',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'optimisation only in internal or XYZ2INT coordinates — **Cartesian input silently '
                 'disables it**',
  'expansion': {'source_line': 3052,
                'core_hours_text': '24',
                'workflow': '`*` after the variables; `GEO_CONV=5`, RMS gradient 1e-5 E_h/bohr, '
                            '`GEO_MAXCYC=50`',
                'state_in': '`ZMAT`, `JOBARC`',
                'state_out': 'optimised `ZMAT`, `JOBARC` — **R**',
                'frozen_monomer': 'relaxed or frozen-inc',
                'memory_scratch': '32 GB / 40 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': 'fc-CCSD(T)/VTZ MAE 0.90 % in B_e `[M]`',
                'notes': '**three-character variable names, single-space fields, no 0°/180° angles — dummy '
                         'atoms for linear fragments**'}},
 {'row_id': 'T3C-12h',
  'source_line': 3039,
  'tier': '12 h',
  'method_text': 'CCSD(T)/cc-pVQZ optimisation',
  'delivers': '**B_e, MAE 0.43 % `[M]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'frozen core at quadruple zeta is a **−0.81 % bias `[M]`**; add a core correction',
  'expansion': {'source_line': 3053,
                'core_hours_text': '96',
                'workflow': '`BASIS=PVQZ`',
                'state_in': '`JOBARC`',
                'state_out': '`JOBARC` — **R**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '32 GB / 80 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': 'fc-CCSD(T)/VQZ MAE 0.812 %, max 2.701 % `[M]`',
                'notes': '`ABCDTYPE=AOBASIS` + `CC_PROG=ECC` required for parallel execution'}},
 {'row_id': 'T3C-1d',
  'source_line': 3040,
  'tier': '1 d',
  'method_text': 'all-electron CCSD(T)/cc-pCVQZ optimisation',
  'delivers': '**B_e, mean −0.037 %, MAE 0.164 % `[M]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'core-valence quadruple zeta is expensive; the cheap alternative is fc/CBS(Q,5) + '
                 'core/cc-pCVTZ at 0.107 % `[M]`',
  'expansion': {'source_line': 3054,
                'core_hours_text': '192',
                'workflow': '`BASIS=PCVQZ`, `FROZEN_CORE=OFF`',
                'state_in': '`JOBARC`',
                'state_out': '`JOBARC` — **R**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '32 GB / 150 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': 'ae-CCSD(T)/cc-pCVQZ MAE 0.164 %, max 0.874 % `[M]`',
                'notes': 'the cheap alternative is fc/CBS(Q,5) + core/cc-pCVTZ — CBS extrapolation makes a '
                         'small core-valence basis suffice'}},
 {'row_id': 'T3C-3d',
  'source_line': 3041,
  'tier': '3 d',
  'method_text': 'ChS composite in CFOUR: fc-CCSD(T)/TZ + ΔMP2/CBS + ΔMP2/CV',
  'delivers': '**B_e, MAE 0.13 % `[M]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'plain ChS has no diffuse functions — **use jun-cc-pVnZ for a weak complex**',
  'expansion': {'source_line': 3055,
                'core_hours_text': '576 @ 8; 9,216 @ 128',
                'workflow': 'three legs, added parameter-wise',
                'state_in': '`JOBARC` per leg',
                'state_out': 'composite geometry — **R**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '32 GB / 200 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': 'ChS MAE 0.13 % `[M]`',
                'notes': '**report the extrapolation formula: n⁻³ vs n⁻⁵ is worth 3–5 mÅ, i.e. 0.20–0.34 % '
                         'in B `[D]`**'}},
 {'row_id': 'T3C-1w',
  'source_line': 3042,
  'tier': '1 w',
  'method_text': 'CBS+CV+fT+fQ composite',
  'delivers': '**B_e, MAE 0.04 % semi-rigid closed-shell `[M]`**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'a semi-rigid figure; a floppy complex is 1–2 %. The ΔQ step is the cost driver',
  'expansion': {'source_line': 3056,
                'core_hours_text': '1,344 @ 8; 21,504 @ 128',
                'workflow': 'add ΔT and ΔQ increments',
                'state_in': '`JOBARC`, `MOINTS`, `MOABCD`',
                'state_out': 'composite geometry — **R** (CFOUR restarts CC)',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '64 GB / 400 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': '0.04 % semi-rigid closed-shell `[M]`',
                'notes': "**this is the tier CFOUR's CC restart makes reachable under a 48 h queue and "
                         'ORCA does not**'}},
 {'row_id': 'T3C-1mo',
  'source_line': 3043,
  'tier': '1 mo',
  'method_text': 'the above plus relativistic (`RELATIVISTIC=DPT2` or `X2C1E`) and the diagonal '
                 'Born–Oppenheimer correction (`DBOC=ON`)',
  'delivers': '**B_e with small-correction closure**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'DBOC is limited to HF/MP1/MP2/CCSD for RHF/UHF; **`ANHARM=FULLQUARTIC` is not in the '
                 'public release**',
  'expansion': {'source_line': 3057,
                'core_hours_text': '5,760 @ 8; 92,160 @ 128',
                'workflow': 'stacked `RELATIVISTIC=`, `DBOC=ON`',
                'state_in': '`JOBARC`',
                'state_out': 'full small-correction set — **R**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '64 GB / 500 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': "public CFOUR is **v2.1, July 2019** and lags the developers' version; GUINEA, "
                         'FULLQUARTIC, CASSCF, Raman and MRCC-driven runs are unavailable'}},
 {'row_id': 'T4O-10s',
  'source_line': 3071,
  'tier': '10 s',
  'method_text': 'inertial defect and planar moments from any geometry',
  'delivers': 'Δ = I_c − I_a − I_b, P_aa/P_bb/P_cc; **sign must be right**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'qualitative; three subtractions on A, B, C',
  'expansion': {'source_line': 3086,
                'core_hours_text': '0.022',
                'workflow': 'three subtractions',
                'state_in': 'any `.xyz`',
                'state_out': 'Δ, P_aa/P_bb/P_cc — **R**',
                'frozen_monomer': '—',
                'memory_scratch': 'negligible',
                'license': 'free',
                'teaching_setup': 'Yes',
                'benchmark_error': '—',
                'notes': '**the sign of Δ must be right, always**; it probes the out-of-plane force field '
                         'directly'}},
 {'row_id': 'T4O-1min',
  'source_line': 3072,
  'tier': '1 min',
  'method_text': '**recipe R6: semi-experimental anchoring** — scale the geometry to the measured parent, '
                 'substitute masses — Kisiel suite',
  'delivers': '**B₀ ±0.03–0.1 % `[M]`**',
  'concurrency_text': 'C',
  'product_text': '**B**',
  'limitations': '**requires a measured parent or close analogue.** Not available for Product A',
  'expansion': {'source_line': 3087,
                'core_hours_text': '0.13',
                'workflow': 'scale to the measured A, B, C, then substitute masses; **use r_e^SE, not r₀**',
                'state_in': 'experimental parent constants + any `.xyz`',
                'state_out': 'scaled geometry — **R**',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': 'negligible',
                'license': 'free',
                'teaching_setup': 'Yes',
                'benchmark_error': '0.03–0.06 % `[M]`',
                'notes': '**the best cell in the document.** Add recipe R5 (per-bond regression) as a '
                         'named sub-recipe, and **never apply the template to a B3LYP geometry — it nearly '
                         'doubles the deviation**'}},
 {'row_id': 'T4O-30min',
  'source_line': 3073,
  'tier': '30 min',
  'method_text': 'analytic DFT Hessian on the T3O-3h geometry; harmonic α_r',
  'delivers': '**ΔB_vib, ±0.1 % of B₀ at 20 % force-constant error `[D]`**; quartic distortion free',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**analytic frequencies are not restartable** — must fit one wall-clock window',
  'expansion': {'source_line': 3088,
                'core_hours_text': '4',
                'workflow': '`! wB97M-V def2-QZVPP … Freq TightSCF DefGrid3 MORead` at the **identical '
                            'level and geometry**',
                'state_in': '`s(3h).xyz` + `.gbw`',
                'state_out': '`.hess` (→ all isotopologues), quartic constants — **D**',
                'frozen_monomer': 'inherits',
                'memory_scratch': '3 GB per rank / 6 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'Yes (at risk)',
                'benchmark_error': '—',
                'notes': 'if it will not fit one window, switch to `NumFreq`, which **is** restartable via '
                         '`%freq Restart true`'}},
 {'row_id': 'T4O-1h',
  'source_line': 3074,
  'tier': '1 h',
  'method_text': 'DFT VPT2 anharmonic force field, 49 analytic Hessians at N = 10',
  'delivers': '**B₀ = B_e + ΔB_vib, ±0.3–0.5 % semi-rigid `[D]`**; α_r, quartic distortion, Watson '
              'parameters',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**`!VPT2` accepts only analytic-Hessian methods — no double hybrids, no RI-JK, and no '
                 'linear molecules**',
  'expansion': {'source_line': 3089,
                'core_hours_text': '8',
                'workflow': '`! B3LYP D4 def2-TZVPP VPT2` + `%pal nprocs 16 nprocs_group 2 end` + `%method '
                            'Z_Tol 1e-14 end` + `%output Pickettname "x.txt" end`',
                'state_in': 'same `.xyz` + `.gbw`; 49 analytic Hessians',
                'state_out': '`.hess` per displacement; α_r; a Pickett template — **D**',
                'frozen_monomer': 'frozen-iso permitted',
                'memory_scratch': '3 GB per rank / 10 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': '49 = 6N − 11 at N = 10. **Skip for linear complexes.** Substituted hybrid force '
                         'fields are permitted on the semi-rigid manifold only, and **any mode below ~100 '
                         'cm⁻¹ is excluded from the hybrid treatment**'}},
 {'row_id': 'T4O-3h',
  'source_line': 3075,
  'tier': '3 h',
  'method_text': 'VPT2 on three conformers; Boltzmann-averaged constants + Pickett export',
  'delivers': 'B₀ per conformer plus vibrational satellites B_v',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'Boltzmann weights inherit the energy error; report the weights and their sensitivity',
  'expansion': {'source_line': 3090,
                'core_hours_text': '24',
                'workflow': 'three conformer `.xyz` + `.gbw`',
                'state_in': 'Table 3 geometries',
                'state_out': 'three `.hess`; B_v satellites — **D**',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': '3 GB per rank / 12 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': 'satellites are the second-strongest features in a jet spectrum of a complex'}},
 {'row_id': 'T4O-12h',
  'source_line': 3076,
  'tier': '12 h',
  'method_text': '**isotopologue campaign from one force field** — `orca_vib` re-analysis',
  'delivers': 'B₀ for 6–15 isotopologues at **zero additional electronic-structure cost — a 6–15× saving '
              '`[D]`**',
  'concurrency_text': 'C',
  'product_text': '**C**',
  'limitations': 'the force field must be the *same*; re-analysis cannot fix a wrong geometry',
  'expansion': {'source_line': 3091,
                'core_hours_text': '96',
                'workflow': '`for iso in …; do cp s5.hess iso_$iso.hess; orca_vib iso_$iso.hess; done`; or '
                            'CFOUR `ISOMASS` + `xjoda`',
                'state_in': 'one `.hess` or `JOBARC`',
                'state_out': 'B₀ per isotopologue — **R**',
                'frozen_monomer': 'inherits',
                'memory_scratch': '1 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'Yes',
                'benchmark_error': 'isotopologue shifts to 0.02–0.1 % `[M]`',
                'notes': "**the second-highest-value reuse in the document.** Note that CFOUR's "
                         '`ANHARM=VIBROT` cubic constants are **not** sufficient for isotopologues of '
                         'lower symmetry — use `ANHARM=VPT2`'}},
 {'row_id': 'T4O-1d',
  'source_line': 3077,
  'tier': '1 d',
  'method_text': 'rigid-monomer path-integral MD at 50 K on an MLFF surface, ORCA `%md`',
  'delivers': '**ΔB_vib with a factor-2 uncertainty**; basin count',
  'concurrency_text': '**G** with a CPU driver',
  'product_text': 'A',
  'limitations': 'P > 18 beads at 50 K for ω_max = 600 cm⁻¹ (use 40 with the 2.2 safety factor); '
                 '**full-dimensional PIMD at jet temperature is deleted** — P > 863 at 5 K',
  'expansion': {'source_line': 3092,
                'core_hours_text': '192',
                'workflow': '`%md Restart IfExists end`; MLFF forces on the GPU, ORCA driver on one P-core',
                'state_in': 'MLFF checkpoint; `.xyz`; `mdrestart`',
                'state_out': '`.mdrestart` every step; trajectory — **R** (chain 6 h jobs)',
                'frozen_monomer': 'frozen-iso (rigid monomers)',
                'memory_scratch': '4 GB host / 2 GB VRAM',
                'license': 'free',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': '**classical MD is a diagnostic only**: emit basin count, a bounded ΔB_vib, and a '
                         '"zero-point energy not included" flag'}},
 {'row_id': 'T4O-3d',
  'source_line': 3078,
  'tier': '3 d',
  'method_text': '⟨μ_αα⟩ from the Table 2 3-D surface — vibrational averaging of the inverse inertia '
                 'tensor',
  'delivers': '**B₀ ±5–20 cm⁻¹-equivalent for the intermolecular modes `[E]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'averages the **inverse** inertia tensor, not the constants — averaging B directly is '
                 'wrong',
  'expansion': {'source_line': 3093,
                'core_hours_text': '576',
                'workflow': 'Lanczos on the registered grid; average μ_αα, then invert',
                'state_in': 'Table 2 3 d surface (HDF5 `dvr_grid`)',
                'state_out': '⟨μ_αα⟩, B₀ — **R**',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': '8 GB',
                'license': 'free',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': 'average the **inverse** inertia tensor; the DVR is cheap to redo'}},
 {'row_id': 'T4O-1w',
  'source_line': 3079,
  'tier': '1 w',
  'method_text': 'diffusion Monte Carlo on the Δ-learned surface',
  'delivers': '⟨μ_αα⟩, B₀ for the true ground state',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': "walker ensembles are embarrassingly parallel and checkpointable; the surface's error is "
                 'inherited',
  'expansion': {'source_line': 3094,
                'core_hours_text': '1,344',
                'workflow': 'walker ensemble with periodic checkpoints',
                'state_in': 'Table 2 12 h Δ-surface',
                'state_out': 'walker checkpoint; ⟨μ_αα⟩ — **R**',
                'frozen_monomer': 'frozen-iso',
                'memory_scratch': '8 GB',
                'license': 'free',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': 'embarrassingly parallel; the natural Setup-3 row'}},
 {'row_id': 'T4O-1mo',
  'source_line': 3080,
  'tier': '1 mo',
  'method_text': 'full VRT manifold and tunnelling splittings from the 6-D surface',
  'delivers': 'band origins; **tunnelling splittings as estimates only**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'splittings span 6 MHz to 279,650 MHz within one molecule — **factor of 3 at best**',
  'expansion': {'source_line': 3095,
                'core_hours_text': '5,760 @ 8; 92,160 @ 128',
                'workflow': 'variational solution on the 6-D surface',
                'state_in': 'Table 2 1 mo surface',
                'state_out': 'VRT manifold, splittings — **D**',
                'frozen_monomer': 'relaxed',
                'memory_scratch': '32 GB / 200 GB',
                'license': 'free',
                'teaching_setup': 'No',
                'benchmark_error': 'splittings span 6 MHz – 279,650 MHz `[M]`',
                'notes': 'report the barrier, the reduced mass and the path, and flag the splitting as an '
                         'estimate'}},
 {'row_id': 'T4C-10s',
  'source_line': 3101,
  'tier': '10 s',
  'method_text': '—',
  'delivers': '—',
  'concurrency_text': '—',
  'product_text': '—',
  'limitations': '**Cannot fill.** No cheap engine. Use `T4O-10s`',
  'expansion': {'source_line': 3116,
                'core_hours_text': '—',
                'workflow': '—',
                'state_in': '—',
                'state_out': '—',
                'frozen_monomer': '—',
                'memory_scratch': '—',
                'license': '—',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': '**track gap, stated.** Use the ORCA track'}},
 {'row_id': 'T4C-1min',
  'source_line': 3102,
  'tier': '1 min',
  'method_text': '—',
  'delivers': '—',
  'concurrency_text': '—',
  'product_text': '—',
  'limitations': '**Cannot fill.** No template or scaling machinery is documented. Use `T4O-1min`',
  'expansion': {'source_line': 3116,
                'core_hours_text': '—',
                'workflow': '—',
                'state_in': '—',
                'state_out': '—',
                'frozen_monomer': '—',
                'memory_scratch': '—',
                'license': '—',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': '**track gap, stated.** Use the ORCA track'}},
 {'row_id': 'T4C-30min',
  'source_line': 3103,
  'tier': '30 min',
  'method_text': 'SCF or MP2 harmonic frequencies, `VIB=EXACT`',
  'delivers': 'ω at a low level; a sanity check',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'MP2 is not parallelised in CFOUR',
  'expansion': {'source_line': 3117,
                'core_hours_text': '4',
                'workflow': '`VIB=EXACT`, `CALC=MP2`',
                'state_in': '`ZMAT` + `JOBARC`',
                'state_out': '`FCMFINAL` — **R** (finite-difference restart needs only `JOBARC` + '
                             '`JAINDX`)',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': 'global 32 GB / 20 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': '`VIB=ANALYTIC` is "in the current release not available"; the manual warns '
                         '"Please do not use VIB=2!"'}},
 {'row_id': 'T4C-1h',
  'source_line': 3104,
  'tier': '1 h',
  'method_text': 'CCSD(T) **analytic harmonic Hessian**, `VIB=EXACT` + `ABCDTYPE=AOBASIS`, `CC_PROG=ECC`',
  'delivers': 'ω, IR intensities; produces `FCM`, `FCMINT`, `DIPDER`',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'no analytic second derivatives for ROHF-based coupled cluster',
  'expansion': {'source_line': 3118,
                'core_hours_text': '8',
                'workflow': '`VIB=EXACT` + `ABCDTYPE=AOBASIS` + `CC_PROG=ECC`',
                'state_in': 'converged `ZMAT`, `JOBARC`',
                'state_out': '`FCM`, `FCMINT`, `DIPDER`, `FCMFINAL` — **R**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '32 GB / 60 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': '**ORCA cannot do this at any tier**: analytic Hessians for SCF only'}},
 {'row_id': 'T4C-3h',
  'source_line': 3105,
  'tier': '3 h',
  'method_text': '`ANHARM=VIBROT` — vibration–rotation interaction constants only',
  'delivers': '**α constants → B₀ from B_e**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'only φ_nij with n totally symmetric; **no saving in C₁, which is the usual symmetry of a '
                 'floppy complex**, and insufficient for lower-symmetry isotopologues',
  'expansion': {'source_line': 3119,
                'core_hours_text': '24',
                'workflow': '`VIB=EXACT, ANHARM=VIBROT`',
                'state_in': '`JOBARC`, `FCMFINAL`',
                'state_out': 'α_r → B₀ — **R**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '32 GB / 80 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': 'oxirane rotational constants ~0.1 % `[M]`',
                'notes': '**do not budget a symmetry discount for a C₁ complex**'}},
 {'row_id': 'T4C-12h',
  'source_line': 3106,
  'tier': '12 h',
  'method_text': 'full `ANHARM=VPT2`, cc-pVTZ, 49 analytic Hessians at N = 10',
  'delivers': 'anharmonic ν, α, **quartic and sextic** distortion; oxirane agreement ~0.1 % rotational, '
              '2–3 % quartic, 3–4 % sextic `[M]`',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': '**GUINEA (deperturbed VPT2, anharmonic intensities) is not in the public release**',
  'expansion': {'source_line': 3120,
                'core_hours_text': '96',
                'workflow': '`VIB=EXACT, ANHARM=VPT2, ANH_STEPSIZ=50000, FD_PROJECT=ON`',
                'state_in': '`JOBARC`',
                'state_out': 'full cubic + semidiagonal quartic field — **R**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '32 GB / 150 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': 'quartic 2–3 %, sextic 3–4 % `[M]`',
                'notes': '49 analytic Hessians against **176,400 ORCA/DLPNO single points** for the same '
                         'object — a ratio of 36N² `[D]`'}},
 {'row_id': 'T4C-1d',
  'source_line': 3107,
  'tier': '1 d',
  'method_text': 'the above with `PROPS=FIRST_ORDER` and vibrationally averaged properties',
  'delivers': '⟨A⟩ = A_e + Σ_r (∂A/∂Q_r)⟨Q_r⟩ + …; χ tensors',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': "vibrational averaging of properties inherits the force field's error",
  'expansion': {'source_line': 3121,
                'core_hours_text': '192',
                'workflow': 'add `PROPS=FIRST_ORDER`',
                'state_in': '`JOBARC`',
                'state_out': '⟨A⟩, χ, dipole components — **R**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '32 GB / 150 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': 'conversion χ(kHz) = EFG(a.u.) × Q(mbarn) × 234.96474'}},
 {'row_id': 'T4C-3d',
  'source_line': 3108,
  'tier': '3 d',
  'method_text': '`ANHARM=VPT2` at cc-pCVTZ or ANO1 with core correlation, queue-split',
  'delivers': 'a semi-experimental-quality force field',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'job splitting is script-driven, not built in; `FD_PROJECT=OFF` in the parallel recipe',
  'expansion': {'source_line': 3122,
                'core_hours_text': '576 @ 8; 9,216 @ 128',
                'workflow': 'add `FREQ_ALGORITHM=PARALLEL, ANH_ALGORITHM=PARALLEL, FD_PROJECT=OFF`; '
                            'process with `xjoda`, `xsymcor`, `xja2fja`, `xcubic`',
                'state_in': '`JOBARC`',
                'state_out': 'queue-split force field — **R**; `FD_IRREP` is the decomposition axis',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '32 GB / 250 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': '**`FD_IRREP` gives no decomposition in C₁** — decompose by displacement '
                         'instead'}},
 {'row_id': 'T4C-1w',
  'source_line': 3109,
  'tier': '1 w',
  'method_text': 'isotopologue force fields from the same field via `%isotopes`',
  'delivers': 'B₀ for 6–15 isotopologues at CCSD(T) quality',
  'concurrency_text': 'C',
  'product_text': '**C**',
  'limitations': '`ANHARM=VIBROT` is insufficient here — the full `ANHARM=VPT2` field is required',
  'expansion': {'source_line': 3123,
                'core_hours_text': '1,344 @ 8; 21,504 @ 128',
                'workflow': '`%isotopes` per isotopologue, re-running `xjoda` against a saved `JOBARC`',
                'state_in': 'one `JOBARC` + one force field',
                'state_out': 'B₀ per isotopologue — **R**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '32 GB / 250 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': 'isotopologue shifts 0.02–0.1 % `[M]`',
                'notes': '**one force field, many isotopologues, no new electronic structure**'}},
 {'row_id': 'T4C-1mo',
  'source_line': 3110,
  'tier': '1 mo',
  'method_text': 'the above plus `SPINROT=ON`, `DBOC=ON`, `RELATIVISTIC=DPT2`',
  'delivers': 'the full composite spectroscopic-constant set for an isotopic campaign',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'DBOC limited to HF/MP1/MP2/CCSD for RHF/UHF; `ANHARM=FULLQUARTIC` unavailable publicly',
  'expansion': {'source_line': 3124,
                'core_hours_text': '5,760 @ 8; 92,160 @ 128',
                'workflow': 'stacked `SPINROT=ON`, `DBOC=ON`, `RELATIVISTIC=`',
                'state_in': '`JOBARC`',
                'state_out': 'the full constant set — **R**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '64 GB / 500 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': 'spin–rotation ~3 % for D₂O `[M]`',
                'notes': '**CFOUR has no documented SPCAT export — the constants must be transcribed by '
                         'hand or by a script (`n.a.`)**'}},
 {'row_id': 'T5-10s',
  'source_line': 3132,
  'tier': '10 s',
  'method_text': 'GFN2-xTB interaction energy',
  'delivers': '**ΔE ±2–5 kcal/mol `[E]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'screening only',
  'expansion': {'source_line': 3147,
                'core_hours_text': '0.022',
                'workflow': '`! XTB2` on dimer and two monomers',
                'state_in': 'ensemble `.xyz`',
                'state_out': 'energies → HDF5 — **D**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '<0.5 GB',
                'license': 'free',
                'teaching_setup': 'Yes',
                'benchmark_error': '—',
                'notes': 'the three legs share one geometry'}},
 {'row_id': 'T5-1min',
  'source_line': 3133,
  'tier': '1 min',
  'method_text': 'MLFF interaction energy — MACE/AIMNet2',
  'delivers': '**ΔE, but errors of 3.5–7.3 kcal/mol on S30L `[M]`**',
  'concurrency_text': '**G**',
  'product_text': 'A',
  'limitations': '**larger than typical isomer separations — a filter with a wide window, never a '
                 'ranking** (guard G4)',
  'expansion': {'source_line': 3148,
                'core_hours_text': '0.13',
                'workflow': 'MLFF single points',
                'state_in': 'ensemble `.xyz`; model key',
                'state_out': 'energies + committee σ — **D**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '1 GB VRAM',
                'license': 'free',
                'teaching_setup': 'Yes (CPU)',
                'benchmark_error': 'S30L 7.31, PLA15 29.9 kcal/mol `[M]`',
                'notes': '**guard G4 applies: audit ρ on 20 structures before culling**'}},
 {'row_id': 'T5-30min',
  'source_line': 3134,
  'tier': '30 min',
  'method_text': 'r²SCAN-3c with the built-in D4 + gCP',
  'delivers': '**ΔE ±1–2 kcal/mol `[E]`**',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': '**never add D4 or gCP — both are inside the composite**',
  'expansion': {'source_line': 3149,
                'core_hours_text': '4',
                'workflow': '`! r2SCAN-3c TightSCF DefGrid3`, three legs',
                'state_in': '`.xyz` + previous conformer `.gbw`',
                'state_out': 'raw/CP/half-CP — **D**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '1 GB per rank / 1 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'Yes',
                'benchmark_error': 'ROT34 AMAX 1.5 % `[M]`',
                'notes': 'one dispersion model per composite'}},
 {'row_id': 'T5-1h',
  'source_line': 3135,
  'tier': '1 h',
  'method_text': 'ωB97M-V/def2-TZVPP, three-leg Boys–Bernardi counterpoise',
  'delivers': '**ΔE ±0.5–1 kcal/mol `[E]`**; raw, CP and half-CP all reported',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': '**never add D4 to a VV10 functional**',
  'expansion': {'source_line': 3150,
                'core_hours_text': '8',
                'workflow': 'ghost atoms with `:`; one exported `.bas` shared by all three legs',
                'state_in': 'one dimer `.xyz`; **no cross-leg `.gbw` reuse dimer → monomer**',
                'state_out': 'raw/CP/half-CP — **D**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '2 GB per rank / 3 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'Yes',
                'benchmark_error': 'S66 CP reduces MAE from ~0.7 to ~0.2 kcal/mol at aVDZ `[M]`',
                'notes': 'full CP at double zeta, half-CP at triple zeta and above, CP-free with F12'}},
 {'row_id': 'T5-3h',
  'source_line': 3136,
  'tier': '3 h',
  'method_text': '**junChS-F12 composite energy** — ORCA F12 single points',
  'delivers': '**A14 MAX 0.11, MUE 0.06, RMSD 0.07 kJ/mol `[M]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'requires F12 auxiliary and CABS bases; **no F12 gradient in ORCA**',
  'expansion': {'source_line': 3151,
                'core_hours_text': '24',
                'workflow': 'CCSD(T)-F12b/jun-cc-pVTZ + MP2-F12 CBS + MP2 CV, added',
                'state_in': '`s(3h).xyz` + `.gbw`',
                'state_out': 'composite energy — **D**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '3 GB per rank / 20 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': 'junChS-F12 A14 MAX 0.11 kJ/mol `[M]`',
                'notes': '**replaces v3\'s 3 d F12 row.** Costs "no more than twice the underlying '
                         'coupled-cluster step"'}},
 {'row_id': 'T5-12h',
  'source_line': 3137,
  'tier': '12 h',
  'method_text': 'DLPNO-CCSD(T1)/TightPNO/cc-pVDZ-F12 (paired with CABS) with local energy decomposition',
  'delivers': '**ΔE ±0.2–0.5 kcal/mol `[E]`**, plus a physical decomposition',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**no MDCI restart** — the job must fit one window',
  'expansion': {'source_line': 3152,
                'core_hours_text': '96',
                'workflow': '`! DLPNO-CCSD(T1) TightPNO cc-pVDZ-F12 (paired with CABS) cc-pVDZ-F12 (paired '
                            'with CABS)/C def2/JK TightSCF` + `%mdci TCutPNO 1e-7 DoLED true StorageType '
                            'Shared end`',
                'state_in': '`.xyz` + `.gbw` from T3O-3h',
                'state_out': 'energies, LED terms — **D**, no MDCI restart',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '3 GB per rank / 5–20 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': 'TightPNO S66 outliers <0.3 kcal/mol `[M]`',
                'notes': '`StorageType Shared` works only when all ranks are on one node — which is Setup '
                         "2's situation"}},
 {'row_id': 'T5-1d',
  'source_line': 3138,
  'tier': '1 d',
  'method_text': 'PNO-space extrapolation CPS(6/7)',
  'delivers': '**ΔE ±0.1–0.2 kcal/mol `[M]`** (S66: TightPNO 0.20 → CPS(6/7) 0.11)',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'CPS is calibrated against tighter PNO calculations, **not against canonical CCSD(T)** — '
                 'a convergence measure, not an accuracy measure',
  'expansion': {'source_line': 3153,
                'core_hours_text': '192',
                'workflow': 'two MDCI energies at consecutive `TCutPNO` exponents; E = E^X + 1.5(E^Y − '
                            'E^X)',
                'state_in': 'per-threshold `.gbw`',
                'state_out': 'extrapolated energy — **D**',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '3 GB per rank / 20 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': 'S66 CPS(6/7) 0.11 kcal/mol `[M]`',
                'notes': '**the exponents must be consecutive** — v3\'s "1e-5 → 1e-7" ladder was invalid; '
                         'F = 1.5 "should NOT be changed"'}},
 {'row_id': 'T5-3d',
  'source_line': 3139,
  'tier': '3 d',
  'method_text': 'canonical CCSD(T)-F12D/RI single point',
  'delivers': '**ΔE ±0.1–0.2 kcal/mol `[E]`**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**dominated by T5-3h** on cost: junChS-F12 delivers 0.06 kJ/mol MUE at a fraction of '
                 'this',
  'expansion': {'source_line': 3154,
                'core_hours_text': '576 @ 8; 9,216 @ 128',
                'workflow': '`! CCSD(T)-F12D/RI cc-pVTZ-F12 cc-pVTZ-F12-CABS`',
                'state_in': '`.xyz` + `.gbw`',
                'state_out': 'reference energy — **D** in ORCA, **R** in CFOUR',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '8 GB / 100 GB',
                'license': 'ORCA academic',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': '**dominated by T5-3h**'}},
 {'row_id': 'T5-1w',
  'source_line': 3140,
  'tier': '1 w',
  'method_text': 'CCSD(T)/CBS + Δcore + ΔT increments',
  'delivers': '**ΔE ±0.05–0.1 kcal/mol `[E]`**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'thermochemical-composite territory; **HEAT, Wn, Gn and ccCA take a geometry as input and '
                 'produce no rotational constant** — footnote only',
  'expansion': {'source_line': 3155,
                'core_hours_text': '1,344 @ 8; 21,504 @ 128',
                'workflow': 'composite increments',
                'state_in': '`JOBARC`/`MOINTS`/`MOABCD` where CFOUR is used',
                'state_out': 'reference energy + increments — **R** in CFOUR',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '16 GB / 200 GB',
                'license': 'CFOUR academic',
                'teaching_setup': 'No',
                'benchmark_error': 'W4 MAD 0.066 kcal/mol vs ATcT `[M]`',
                'notes': 'for a *trimer*, state that D3/D4 is pairwise-additive and three-body terms carry '
                         '15–20 % `[M]`'}},
 {'row_id': 'T5-1mo',
  'source_line': 3141,
  'tier': '1 mo',
  'method_text': 'SAPT(DFT) or SAPT2+3 decomposition — Psi4 or autoPES',
  'delivers': 'the physical decomposition: electrostatics, exchange, induction, dispersion',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'a decomposition is an interpretation, not an accuracy improvement',
  'expansion': {'source_line': 3156,
                'core_hours_text': '5,760 @ 8; 92,160 @ 128',
                'workflow': "Psi4 SAPT, or autoPES's SAPT(DFT) route",
                'state_in': '`.xyz`',
                'state_out': 'decomposition table',
                'frozen_monomer': 'frozen-inc',
                'memory_scratch': '32 GB / 200 GB',
                'license': 'Psi4 free / autoPES **`n.a.`**',
                'teaching_setup': 'No',
                'benchmark_error': '—',
                'notes': "SAPT(DFT) scales N⁵ against CCSD(T)'s N⁷, which is why it can afford a "
                         'full-dimensional grid'}},
 {'row_id': 'T6O-10s',
  'source_line': 3170,
  'tier': '10 s',
  'method_text': 'inertial defect, planar moments, dipolar coupling D ∝ r⁻³ from any geometry',
  'delivers': 'Δ sign; P_aa > P_bb > P_cc ordering; D',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'qualitative, but **free and independently constraining**',
  'expansion': {'source_line': 3181,
                'notes': '**Expansion block — Table 6-O.** Core-h follow the standard ladder (0.022, 0.13, '
                         '4, 8, 24, 96, 192, 576, 1,344, 5,760 at 8 cores). **State-in** for every row '
                         'from 30 min upward is the T3O-3h geometry plus its `.gbw` (`! MORead`); '
                         '**State-out** is the property block of the `.out` plus, from T6O-3d, '
                         '`pickett.txt` — **D** for every analytic-property row, since analytic '
                         'frequencies and MDCI are not restartable. **Frozen-mono**: inherits the geometry '
                         "row's flag. **Mem/scratch** 2–3 GB per rank / 3–20 GB. **Licence** ORCA academic "
                         'throughout. **Setup 1** yes to 3 h, no beyond. **Max benchmark error**: '
                         'camphor-class dipole studies show an 0.08 D component deciding whether a branch '
                         'exists `[M]`; χ at 5 % from MP2/6-311++G(2d,2p) `[M]`; χ(D) basis shift TZ→6Z is '
                         '9.9 kHz = 6.3 % `[M]`. **Mitigation**: report signed components in the principal '
                         'axis system, never magnitudes; for χ, state the basis and whether a vibrational '
                         'correction was applied.'}},
 {'row_id': 'T6O-1min',
  'source_line': 3171,
  'tier': '1 min',
  'method_text': 'GFN2-xTB dipole in the principal axis system',
  'delivers': 'μ_a, μ_b, μ_c **signed**, ±0.5 D `[E]`',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'semi-empirical dipoles decide which branch types exist and are unreliable at this level',
  'expansion': {'source_line': 3181,
                'notes': '**Expansion block — Table 6-O.** Core-h follow the standard ladder (0.022, 0.13, '
                         '4, 8, 24, 96, 192, 576, 1,344, 5,760 at 8 cores). **State-in** for every row '
                         'from 30 min upward is the T3O-3h geometry plus its `.gbw` (`! MORead`); '
                         '**State-out** is the property block of the `.out` plus, from T6O-3d, '
                         '`pickett.txt` — **D** for every analytic-property row, since analytic '
                         'frequencies and MDCI are not restartable. **Frozen-mono**: inherits the geometry '
                         "row's flag. **Mem/scratch** 2–3 GB per rank / 3–20 GB. **Licence** ORCA academic "
                         'throughout. **Setup 1** yes to 3 h, no beyond. **Max benchmark error**: '
                         'camphor-class dipole studies show an 0.08 D component deciding whether a branch '
                         'exists `[M]`; χ at 5 % from MP2/6-311++G(2d,2p) `[M]`; χ(D) basis shift TZ→6Z is '
                         '9.9 kHz = 6.3 % `[M]`. **Mitigation**: report signed components in the principal '
                         'axis system, never magnitudes; for χ, state the basis and whether a vibrational '
                         'correction was applied.'}},
 {'row_id': 'T6O-30min',
  'source_line': 3172,
  'tier': '30 min',
  'method_text': 'ωB97X-V/def2-TZVPP dipole and electric field gradient',
  'delivers': '**μ ±0.1–0.3 D `[E]`**; χ_aa, χ_bb − χ_cc ~10 % `[E]`',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'hybrid DFT does **not** currently meet the ±0.1 D per-component requirement for flexible '
                 'or weakly bound species',
  'expansion': {'source_line': 3181,
                'notes': '**Expansion block — Table 6-O.** Core-h follow the standard ladder (0.022, 0.13, '
                         '4, 8, 24, 96, 192, 576, 1,344, 5,760 at 8 cores). **State-in** for every row '
                         'from 30 min upward is the T3O-3h geometry plus its `.gbw` (`! MORead`); '
                         '**State-out** is the property block of the `.out` plus, from T6O-3d, '
                         '`pickett.txt` — **D** for every analytic-property row, since analytic '
                         'frequencies and MDCI are not restartable. **Frozen-mono**: inherits the geometry '
                         "row's flag. **Mem/scratch** 2–3 GB per rank / 3–20 GB. **Licence** ORCA academic "
                         'throughout. **Setup 1** yes to 3 h, no beyond. **Max benchmark error**: '
                         'camphor-class dipole studies show an 0.08 D component deciding whether a branch '
                         'exists `[M]`; χ at 5 % from MP2/6-311++G(2d,2p) `[M]`; χ(D) basis shift TZ→6Z is '
                         '9.9 kHz = 6.3 % `[M]`. **Mitigation**: report signed components in the principal '
                         'axis system, never magnitudes; for χ, state the basis and whether a vibrational '
                         'correction was applied.'}},
 {'row_id': 'T6O-1h',
  'source_line': 3173,
  'tier': '1 h',
  'method_text': 'MP2/6-311++G(2d,2p) electric field gradients',
  'delivers': '**χ to ~5 % `[M]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': "the field-gradient basis requirement is tighter than the energy's",
  'expansion': {'source_line': 3181,
                'notes': '**Expansion block — Table 6-O.** Core-h follow the standard ladder (0.022, 0.13, '
                         '4, 8, 24, 96, 192, 576, 1,344, 5,760 at 8 cores). **State-in** for every row '
                         'from 30 min upward is the T3O-3h geometry plus its `.gbw` (`! MORead`); '
                         '**State-out** is the property block of the `.out` plus, from T6O-3d, '
                         '`pickett.txt` — **D** for every analytic-property row, since analytic '
                         'frequencies and MDCI are not restartable. **Frozen-mono**: inherits the geometry '
                         "row's flag. **Mem/scratch** 2–3 GB per rank / 3–20 GB. **Licence** ORCA academic "
                         'throughout. **Setup 1** yes to 3 h, no beyond. **Max benchmark error**: '
                         'camphor-class dipole studies show an 0.08 D component deciding whether a branch '
                         'exists `[M]`; χ at 5 % from MP2/6-311++G(2d,2p) `[M]`; χ(D) basis shift TZ→6Z is '
                         '9.9 kHz = 6.3 % `[M]`. **Mitigation**: report signed components in the principal '
                         'axis system, never magnitudes; for χ, state the basis and whether a vibrational '
                         'correction was applied.'}},
 {'row_id': 'T6O-3h',
  'source_line': 3174,
  'tier': '3 h',
  'method_text': 'quartic centrifugal distortion from the T4O-30min harmonic force field',
  'delivers': '**quartic constants to a factor of 2 `[M]`**, free',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'free only if the Hessian already exists; otherwise it is a Hessian job',
  'expansion': {'source_line': 3181,
                'notes': '**Expansion block — Table 6-O.** Core-h follow the standard ladder (0.022, 0.13, '
                         '4, 8, 24, 96, 192, 576, 1,344, 5,760 at 8 cores). **State-in** for every row '
                         'from 30 min upward is the T3O-3h geometry plus its `.gbw` (`! MORead`); '
                         '**State-out** is the property block of the `.out` plus, from T6O-3d, '
                         '`pickett.txt` — **D** for every analytic-property row, since analytic '
                         'frequencies and MDCI are not restartable. **Frozen-mono**: inherits the geometry '
                         "row's flag. **Mem/scratch** 2–3 GB per rank / 3–20 GB. **Licence** ORCA academic "
                         'throughout. **Setup 1** yes to 3 h, no beyond. **Max benchmark error**: '
                         'camphor-class dipole studies show an 0.08 D component deciding whether a branch '
                         'exists `[M]`; χ at 5 % from MP2/6-311++G(2d,2p) `[M]`; χ(D) basis shift TZ→6Z is '
                         '9.9 kHz = 6.3 % `[M]`. **Mitigation**: report signed components in the principal '
                         'axis system, never magnitudes; for χ, state the basis and whether a vibrational '
                         'correction was applied.'}},
 {'row_id': 'T6O-12h',
  'source_line': 3175,
  'tier': '12 h',
  'method_text': 'DLPNO-CCSD unrelaxed-density multipoles and field gradients',
  'delivers': 'μ and χ at coupled-cluster quality for closed shells',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**"an unrelaxed density for CCSD(T) is NOT available"** — CCSD only',
  'expansion': {'source_line': 3181,
                'notes': '**Expansion block — Table 6-O.** Core-h follow the standard ladder (0.022, 0.13, '
                         '4, 8, 24, 96, 192, 576, 1,344, 5,760 at 8 cores). **State-in** for every row '
                         'from 30 min upward is the T3O-3h geometry plus its `.gbw` (`! MORead`); '
                         '**State-out** is the property block of the `.out` plus, from T6O-3d, '
                         '`pickett.txt` — **D** for every analytic-property row, since analytic '
                         'frequencies and MDCI are not restartable. **Frozen-mono**: inherits the geometry '
                         "row's flag. **Mem/scratch** 2–3 GB per rank / 3–20 GB. **Licence** ORCA academic "
                         'throughout. **Setup 1** yes to 3 h, no beyond. **Max benchmark error**: '
                         'camphor-class dipole studies show an 0.08 D component deciding whether a branch '
                         'exists `[M]`; χ at 5 % from MP2/6-311++G(2d,2p) `[M]`; χ(D) basis shift TZ→6Z is '
                         '9.9 kHz = 6.3 % `[M]`. **Mitigation**: report signed components in the principal '
                         'axis system, never magnitudes; for χ, state the basis and whether a vibrational '
                         'correction was applied.'}},
 {'row_id': 'T6O-1d',
  'source_line': 3176,
  'tier': '1 d',
  'method_text': 'vibrational corrections to μ and χ from the VPT2 force field',
  'delivers': '⟨μ⟩, ⟨χ⟩; **χ(D) vibrational correction is 1.7 % `[M]`**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': "a vibrational correction inherits the force field's error",
  'expansion': {'source_line': 3181,
                'notes': '**Expansion block — Table 6-O.** Core-h follow the standard ladder (0.022, 0.13, '
                         '4, 8, 24, 96, 192, 576, 1,344, 5,760 at 8 cores). **State-in** for every row '
                         'from 30 min upward is the T3O-3h geometry plus its `.gbw` (`! MORead`); '
                         '**State-out** is the property block of the `.out` plus, from T6O-3d, '
                         '`pickett.txt` — **D** for every analytic-property row, since analytic '
                         'frequencies and MDCI are not restartable. **Frozen-mono**: inherits the geometry '
                         "row's flag. **Mem/scratch** 2–3 GB per rank / 3–20 GB. **Licence** ORCA academic "
                         'throughout. **Setup 1** yes to 3 h, no beyond. **Max benchmark error**: '
                         'camphor-class dipole studies show an 0.08 D component deciding whether a branch '
                         'exists `[M]`; χ at 5 % from MP2/6-311++G(2d,2p) `[M]`; χ(D) basis shift TZ→6Z is '
                         '9.9 kHz = 6.3 % `[M]`. **Mitigation**: report signed components in the principal '
                         'axis system, never magnitudes; for χ, state the basis and whether a vibrational '
                         'correction was applied.'}},
 {'row_id': 'T6O-3d',
  'source_line': 3177,
  'tier': '3 d',
  'method_text': 'Boltzmann-averaged constants across the conformer ensemble + Pickett/SPCAT export',
  'delivers': 'an assignment-ready `.var` template',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'the Pickett export is "still being refined and extended"',
  'expansion': {'source_line': 3181,
                'notes': '**Expansion block — Table 6-O.** Core-h follow the standard ladder (0.022, 0.13, '
                         '4, 8, 24, 96, 192, 576, 1,344, 5,760 at 8 cores). **State-in** for every row '
                         'from 30 min upward is the T3O-3h geometry plus its `.gbw` (`! MORead`); '
                         '**State-out** is the property block of the `.out` plus, from T6O-3d, '
                         '`pickett.txt` — **D** for every analytic-property row, since analytic '
                         'frequencies and MDCI are not restartable. **Frozen-mono**: inherits the geometry '
                         "row's flag. **Mem/scratch** 2–3 GB per rank / 3–20 GB. **Licence** ORCA academic "
                         'throughout. **Setup 1** yes to 3 h, no beyond. **Max benchmark error**: '
                         'camphor-class dipole studies show an 0.08 D component deciding whether a branch '
                         'exists `[M]`; χ at 5 % from MP2/6-311++G(2d,2p) `[M]`; χ(D) basis shift TZ→6Z is '
                         '9.9 kHz = 6.3 % `[M]`. **Mitigation**: report signed components in the principal '
                         'axis system, never magnitudes; for χ, state the basis and whether a vibrational '
                         'correction was applied.'}},
 {'row_id': 'T6O-1w',
  'source_line': 3178,
  'tier': '1 w',
  'method_text': 'vibrational satellites B_v for the three lowest modes',
  'delivers': 'B_v; order of magnitude for intermolecular modes, 0.1 % for intramolecular',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'intermolecular satellites are exactly where VPT2 is least trustworthy',
  'expansion': {'source_line': 3181,
                'notes': '**Expansion block — Table 6-O.** Core-h follow the standard ladder (0.022, 0.13, '
                         '4, 8, 24, 96, 192, 576, 1,344, 5,760 at 8 cores). **State-in** for every row '
                         'from 30 min upward is the T3O-3h geometry plus its `.gbw` (`! MORead`); '
                         '**State-out** is the property block of the `.out` plus, from T6O-3d, '
                         '`pickett.txt` — **D** for every analytic-property row, since analytic '
                         'frequencies and MDCI are not restartable. **Frozen-mono**: inherits the geometry '
                         "row's flag. **Mem/scratch** 2–3 GB per rank / 3–20 GB. **Licence** ORCA academic "
                         'throughout. **Setup 1** yes to 3 h, no beyond. **Max benchmark error**: '
                         'camphor-class dipole studies show an 0.08 D component deciding whether a branch '
                         'exists `[M]`; χ at 5 % from MP2/6-311++G(2d,2p) `[M]`; χ(D) basis shift TZ→6Z is '
                         '9.9 kHz = 6.3 % `[M]`. **Mitigation**: report signed components in the principal '
                         'axis system, never magnitudes; for χ, state the basis and whether a vibrational '
                         'correction was applied.'}},
 {'row_id': 'T6O-1mo',
  'source_line': 3179,
  'tier': '1 mo',
  'method_text': '**— sextic distortion, spin–rotation and DBOC cannot be produced by this track**',
  'delivers': '—',
  'concurrency_text': '—',
  'product_text': '—',
  'limitations': '**Track gap.** None is documented in ORCA. **Escalate to `T6C-1mo`**',
  'expansion': {'source_line': 3181,
                'notes': '**Expansion block — Table 6-O.** Core-h follow the standard ladder (0.022, 0.13, '
                         '4, 8, 24, 96, 192, 576, 1,344, 5,760 at 8 cores). **State-in** for every row '
                         'from 30 min upward is the T3O-3h geometry plus its `.gbw` (`! MORead`); '
                         '**State-out** is the property block of the `.out` plus, from T6O-3d, '
                         '`pickett.txt` — **D** for every analytic-property row, since analytic '
                         'frequencies and MDCI are not restartable. **Frozen-mono**: inherits the geometry '
                         "row's flag. **Mem/scratch** 2–3 GB per rank / 3–20 GB. **Licence** ORCA academic "
                         'throughout. **Setup 1** yes to 3 h, no beyond. **Max benchmark error**: '
                         'camphor-class dipole studies show an 0.08 D component deciding whether a branch '
                         'exists `[M]`; χ at 5 % from MP2/6-311++G(2d,2p) `[M]`; χ(D) basis shift TZ→6Z is '
                         '9.9 kHz = 6.3 % `[M]`. **Mitigation**: report signed components in the principal '
                         'axis system, never magnitudes; for χ, state the basis and whether a vibrational '
                         'correction was applied.'}},
 {'row_id': 'T6C-10s',
  'source_line': 3187,
  'tier': '10 s',
  'method_text': '—',
  'delivers': '—',
  'concurrency_text': '—',
  'product_text': '—',
  'limitations': '**Cannot fill.** No cheap engine. Use `T6O-10s`',
  'expansion': {'source_line': 3198,
                'notes': '**Expansion block — Table 6-C.** Core-h as the standard ladder; Setup-3 rows '
                         'also quote the 128-core figure (T6C-3d 9,216; T6C-1w 21,504; T6C-1mo 92,160). '
                         '**State-in** is `JOBARC` (+ `JAINDX`, and `MOINTS`/`MOABCD` for coupled-cluster '
                         'restarts); **State-out** is `JOBARC` plus the printed property block — **R** '
                         'throughout, because CFOUR restarts both coupled cluster and finite-difference '
                         'frequencies, which is the reason these rows are reachable under a 48 h queue and '
                         'their ORCA counterparts are not. **Frozen-mono** `frozen-inc`. **Mem** is a '
                         '*global* `MEMORY_SIZE=32, MEM_UNIT=GB`, not per rank — the default is ≈762 MB '
                         'and must be raised. **Licence** CFOUR academic, wet signature, two-year renewing '
                         'term. **Setup 1: no, at every tier** — the licence does not scale to a class.'}},
 {'row_id': 'T6C-1min',
  'source_line': 3188,
  'tier': '1 min',
  'method_text': '—',
  'delivers': '—',
  'concurrency_text': '—',
  'product_text': '—',
  'limitations': '**Cannot fill.** Use `T6O-1min`',
  'expansion': {'source_line': 3198,
                'notes': '**Expansion block — Table 6-C.** Core-h as the standard ladder; Setup-3 rows '
                         'also quote the 128-core figure (T6C-3d 9,216; T6C-1w 21,504; T6C-1mo 92,160). '
                         '**State-in** is `JOBARC` (+ `JAINDX`, and `MOINTS`/`MOABCD` for coupled-cluster '
                         'restarts); **State-out** is `JOBARC` plus the printed property block — **R** '
                         'throughout, because CFOUR restarts both coupled cluster and finite-difference '
                         'frequencies, which is the reason these rows are reachable under a 48 h queue and '
                         'their ORCA counterparts are not. **Frozen-mono** `frozen-inc`. **Mem** is a '
                         '*global* `MEMORY_SIZE=32, MEM_UNIT=GB`, not per rank — the default is ≈762 MB '
                         'and must be raised. **Licence** CFOUR academic, wet signature, two-year renewing '
                         'term. **Setup 1: no, at every tier** — the licence does not scale to a class.'}},
 {'row_id': 'T6C-30min',
  'source_line': 3189,
  'tier': '30 min',
  'method_text': 'SCF/MP2 `PROPS=FIRST_ORDER`',
  'delivers': 'dipole, quadrupole, octopole; electric field gradients',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'MP2 is not parallelised in CFOUR',
  'expansion': {'source_line': 3198,
                'notes': '**Expansion block — Table 6-C.** Core-h as the standard ladder; Setup-3 rows '
                         'also quote the 128-core figure (T6C-3d 9,216; T6C-1w 21,504; T6C-1mo 92,160). '
                         '**State-in** is `JOBARC` (+ `JAINDX`, and `MOINTS`/`MOABCD` for coupled-cluster '
                         'restarts); **State-out** is `JOBARC` plus the printed property block — **R** '
                         'throughout, because CFOUR restarts both coupled cluster and finite-difference '
                         'frequencies, which is the reason these rows are reachable under a 48 h queue and '
                         'their ORCA counterparts are not. **Frozen-mono** `frozen-inc`. **Mem** is a '
                         '*global* `MEMORY_SIZE=32, MEM_UNIT=GB`, not per rank — the default is ≈762 MB '
                         'and must be raised. **Licence** CFOUR academic, wet signature, two-year renewing '
                         'term. **Setup 1: no, at every tier** — the licence does not scale to a class.'}},
 {'row_id': 'T6C-1h',
  'source_line': 3190,
  'tier': '1 h',
  'method_text': 'CCSD(T)/cc-pVTZ `PROPS=FIRST_ORDER`',
  'delivers': '**CCSD(T)-quality μ and EFG → χ**, converted by χ(kHz) = EFG × Q(mbarn) × 234.96474',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'the conversion is manual; no SPCAT export',
  'expansion': {'source_line': 3198,
                'notes': '**Expansion block — Table 6-C.** Core-h as the standard ladder; Setup-3 rows '
                         'also quote the 128-core figure (T6C-3d 9,216; T6C-1w 21,504; T6C-1mo 92,160). '
                         '**State-in** is `JOBARC` (+ `JAINDX`, and `MOINTS`/`MOABCD` for coupled-cluster '
                         'restarts); **State-out** is `JOBARC` plus the printed property block — **R** '
                         'throughout, because CFOUR restarts both coupled cluster and finite-difference '
                         'frequencies, which is the reason these rows are reachable under a 48 h queue and '
                         'their ORCA counterparts are not. **Frozen-mono** `frozen-inc`. **Mem** is a '
                         '*global* `MEMORY_SIZE=32, MEM_UNIT=GB`, not per rank — the default is ≈762 MB '
                         'and must be raised. **Licence** CFOUR academic, wet signature, two-year renewing '
                         'term. **Setup 1: no, at every tier** — the licence does not scale to a class.'}},
 {'row_id': 'T6C-3h',
  'source_line': 3191,
  'tier': '3 h',
  'method_text': 'quartic distortion from the `T4C-1h` analytic Hessian',
  'delivers': 'quartic constants; ~2–3 % on oxirane `[M]`',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'requires the analytic CCSD(T) Hessian first',
  'expansion': {'source_line': 3198,
                'notes': '**Expansion block — Table 6-C.** Core-h as the standard ladder; Setup-3 rows '
                         'also quote the 128-core figure (T6C-3d 9,216; T6C-1w 21,504; T6C-1mo 92,160). '
                         '**State-in** is `JOBARC` (+ `JAINDX`, and `MOINTS`/`MOABCD` for coupled-cluster '
                         'restarts); **State-out** is `JOBARC` plus the printed property block — **R** '
                         'throughout, because CFOUR restarts both coupled cluster and finite-difference '
                         'frequencies, which is the reason these rows are reachable under a 48 h queue and '
                         'their ORCA counterparts are not. **Frozen-mono** `frozen-inc`. **Mem** is a '
                         '*global* `MEMORY_SIZE=32, MEM_UNIT=GB`, not per rank — the default is ≈762 MB '
                         'and must be raised. **Licence** CFOUR academic, wet signature, two-year renewing '
                         'term. **Setup 1: no, at every tier** — the licence does not scale to a class.'}},
 {'row_id': 'T6C-12h',
  'source_line': 3192,
  'tier': '12 h',
  'method_text': '**sextic centrifugal distortion** from `ANHARM=VPT2`',
  'delivers': '**sextic constants, 3–4 % on oxirane `[M]` — CFOUR only**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'needs the full VPT2 field; **not available in ORCA at any tier**',
  'expansion': {'source_line': 3198,
                'notes': '**Expansion block — Table 6-C.** Core-h as the standard ladder; Setup-3 rows '
                         'also quote the 128-core figure (T6C-3d 9,216; T6C-1w 21,504; T6C-1mo 92,160). '
                         '**State-in** is `JOBARC` (+ `JAINDX`, and `MOINTS`/`MOABCD` for coupled-cluster '
                         'restarts); **State-out** is `JOBARC` plus the printed property block — **R** '
                         'throughout, because CFOUR restarts both coupled cluster and finite-difference '
                         'frequencies, which is the reason these rows are reachable under a 48 h queue and '
                         'their ORCA counterparts are not. **Frozen-mono** `frozen-inc`. **Mem** is a '
                         '*global* `MEMORY_SIZE=32, MEM_UNIT=GB`, not per rank — the default is ≈762 MB '
                         'and must be raised. **Licence** CFOUR academic, wet signature, two-year renewing '
                         'term. **Setup 1: no, at every tier** — the licence does not scale to a class.'}},
 {'row_id': 'T6C-1d',
  'source_line': 3193,
  'tier': '1 d',
  'method_text': 'nuclear spin–rotation, `SPINROT=ON`',
  'delivers': 'C_aa, C_bb, C_cc; **~3 % demonstrated for D₂O `[M]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'NMR-type input; one of the few places computation sits at experimental accuracy',
  'expansion': {'source_line': 3198,
                'notes': '**Expansion block — Table 6-C.** Core-h as the standard ladder; Setup-3 rows '
                         'also quote the 128-core figure (T6C-3d 9,216; T6C-1w 21,504; T6C-1mo 92,160). '
                         '**State-in** is `JOBARC` (+ `JAINDX`, and `MOINTS`/`MOABCD` for coupled-cluster '
                         'restarts); **State-out** is `JOBARC` plus the printed property block — **R** '
                         'throughout, because CFOUR restarts both coupled cluster and finite-difference '
                         'frequencies, which is the reason these rows are reachable under a 48 h queue and '
                         'their ORCA counterparts are not. **Frozen-mono** `frozen-inc`. **Mem** is a '
                         '*global* `MEMORY_SIZE=32, MEM_UNIT=GB`, not per rank — the default is ≈762 MB '
                         'and must be raised. **Licence** CFOUR academic, wet signature, two-year renewing '
                         'term. **Setup 1: no, at every tier** — the licence does not scale to a class.'}},
 {'row_id': 'T6C-3d',
  'source_line': 3194,
  'tier': '3 d',
  'method_text': 'vibrationally averaged properties, ⟨A⟩ = A_e + Σ_r (∂A/∂Q_r)⟨Q_r⟩ + …',
  'delivers': '⟨μ⟩, ⟨χ⟩, ⟨A⟩ at coupled-cluster quality',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': "inherits the anharmonic field's error",
  'expansion': {'source_line': 3198,
                'notes': '**Expansion block — Table 6-C.** Core-h as the standard ladder; Setup-3 rows '
                         'also quote the 128-core figure (T6C-3d 9,216; T6C-1w 21,504; T6C-1mo 92,160). '
                         '**State-in** is `JOBARC` (+ `JAINDX`, and `MOINTS`/`MOABCD` for coupled-cluster '
                         'restarts); **State-out** is `JOBARC` plus the printed property block — **R** '
                         'throughout, because CFOUR restarts both coupled cluster and finite-difference '
                         'frequencies, which is the reason these rows are reachable under a 48 h queue and '
                         'their ORCA counterparts are not. **Frozen-mono** `frozen-inc`. **Mem** is a '
                         '*global* `MEMORY_SIZE=32, MEM_UNIT=GB`, not per rank — the default is ≈762 MB '
                         'and must be raised. **Licence** CFOUR academic, wet signature, two-year renewing '
                         'term. **Setup 1: no, at every tier** — the licence does not scale to a class.'}},
 {'row_id': 'T6C-1w',
  'source_line': 3195,
  'tier': '1 w',
  'method_text': 'diagonal Born–Oppenheimer correction, `DBOC=ON`',
  'delivers': 'the DBOC contribution to the constants',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'limited to HF, MP1, MP2 and CCSD for RHF/UHF',
  'expansion': {'source_line': 3198,
                'notes': '**Expansion block — Table 6-C.** Core-h as the standard ladder; Setup-3 rows '
                         'also quote the 128-core figure (T6C-3d 9,216; T6C-1w 21,504; T6C-1mo 92,160). '
                         '**State-in** is `JOBARC` (+ `JAINDX`, and `MOINTS`/`MOABCD` for coupled-cluster '
                         'restarts); **State-out** is `JOBARC` plus the printed property block — **R** '
                         'throughout, because CFOUR restarts both coupled cluster and finite-difference '
                         'frequencies, which is the reason these rows are reachable under a 48 h queue and '
                         'their ORCA counterparts are not. **Frozen-mono** `frozen-inc`. **Mem** is a '
                         '*global* `MEMORY_SIZE=32, MEM_UNIT=GB`, not per rank — the default is ≈762 MB '
                         'and must be raised. **Licence** CFOUR academic, wet signature, two-year renewing '
                         'term. **Setup 1: no, at every tier** — the licence does not scale to a class.'}},
 {'row_id': 'T6C-1mo',
  'source_line': 3196,
  'tier': '1 mo',
  'method_text': 'relativistic corrections, `RELATIVISTIC=DPT2` or `X2C1E`, stacked with the above',
  'delivers': 'the closed small-correction set for a heavy-atom complex',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**no SPCAT export — transcribe the constants by hand (`n.a.`)**',
  'expansion': {'source_line': 3198,
                'notes': '**Expansion block — Table 6-C.** Core-h as the standard ladder; Setup-3 rows '
                         'also quote the 128-core figure (T6C-3d 9,216; T6C-1w 21,504; T6C-1mo 92,160). '
                         '**State-in** is `JOBARC` (+ `JAINDX`, and `MOINTS`/`MOABCD` for coupled-cluster '
                         'restarts); **State-out** is `JOBARC` plus the printed property block — **R** '
                         'throughout, because CFOUR restarts both coupled cluster and finite-difference '
                         'frequencies, which is the reason these rows are reachable under a 48 h queue and '
                         'their ORCA counterparts are not. **Frozen-mono** `frozen-inc`. **Mem** is a '
                         '*global* `MEMORY_SIZE=32, MEM_UNIT=GB`, not per rank — the default is ≈762 MB '
                         'and must be raised. **Licence** CFOUR academic, wet signature, two-year renewing '
                         'term. **Setup 1: no, at every tier** — the licence does not scale to a class.'}},
 {'row_id': 'T7-10s',
  'source_line': 3208,
  'tier': '10 s',
  'method_text': 'GFN2-xTB relaxed torsional scan',
  'delivers': 'the existence and rough height of a barrier; **no V₃ claim**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'tight binding misplaces torsional barriers routinely',
  'expansion': {'source_line': 3219,
                'notes': '**Expansion block — Table 7.** Core-h as the standard ladder. **State-in**: the '
                         "T3O-3h or T3O-12h geometry plus `.gbw`; scan rows consume the previous point's "
                         '`.gbw` by `! MORead` (free, and each point is a small perturbation). '
                         '**State-out**: `.xyz` + `.gbw` per scan step, the fitted path, and the effective '
                         'one-dimensional potential — **D**, because a relaxed scan is a set of '
                         'independent optimisations and is decomposed rather than checkpointed. '
                         '**Frozen-mono**: `frozen-iso` for the intermolecular torsion; `relaxed` if the '
                         'barrier involves an internal rotor of one monomer. **Mem/scratch** 1–3 GB per '
                         'rank / 1–20 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error: ±14 %, ammonia–formic acid, computed span 168.3–212.8 cm⁻¹ '
                         'against 195.18(7) `[M]` — the same figure for every row, and the accuracy cells '
                         'are capped at it accordingly.** **Mitigation**: report the barrier with the '
                         'reduced mass and the path; run the relaxed scan in both directions and report '
                         'the hysteresis; state whether the path is one- or two-dimensional.'}},
 {'row_id': 'T7-1min',
  'source_line': 3209,
  'tier': '1 min',
  'method_text': 'MLFF torsional scan, dense',
  'delivers': 'the shape of the one-dimensional path',
  'concurrency_text': '**G**',
  'product_text': 'A',
  'limitations': 'use the shape, not the height',
  'expansion': {'source_line': 3219,
                'notes': '**Expansion block — Table 7.** Core-h as the standard ladder. **State-in**: the '
                         "T3O-3h or T3O-12h geometry plus `.gbw`; scan rows consume the previous point's "
                         '`.gbw` by `! MORead` (free, and each point is a small perturbation). '
                         '**State-out**: `.xyz` + `.gbw` per scan step, the fitted path, and the effective '
                         'one-dimensional potential — **D**, because a relaxed scan is a set of '
                         'independent optimisations and is decomposed rather than checkpointed. '
                         '**Frozen-mono**: `frozen-iso` for the intermolecular torsion; `relaxed` if the '
                         'barrier involves an internal rotor of one monomer. **Mem/scratch** 1–3 GB per '
                         'rank / 1–20 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error: ±14 %, ammonia–formic acid, computed span 168.3–212.8 cm⁻¹ '
                         'against 195.18(7) `[M]` — the same figure for every row, and the accuracy cells '
                         'are capped at it accordingly.** **Mitigation**: report the barrier with the '
                         'reduced mass and the path; run the relaxed scan in both directions and report '
                         'the hysteresis; state whether the path is one- or two-dimensional.'}},
 {'row_id': 'T7-30min',
  'source_line': 3210,
  'tier': '30 min',
  'method_text': 'r²SCAN-3c relaxed 1-D scan, ~36 points',
  'delivers': '**V₃ ±14 % `[M]`**, one-dimensional',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'a one-dimensional path through a multi-dimensional barrier is a lower bound on the true '
                 'barrier',
  'expansion': {'source_line': 3219,
                'notes': '**Expansion block — Table 7.** Core-h as the standard ladder. **State-in**: the '
                         "T3O-3h or T3O-12h geometry plus `.gbw`; scan rows consume the previous point's "
                         '`.gbw` by `! MORead` (free, and each point is a small perturbation). '
                         '**State-out**: `.xyz` + `.gbw` per scan step, the fitted path, and the effective '
                         'one-dimensional potential — **D**, because a relaxed scan is a set of '
                         'independent optimisations and is decomposed rather than checkpointed. '
                         '**Frozen-mono**: `frozen-iso` for the intermolecular torsion; `relaxed` if the '
                         'barrier involves an internal rotor of one monomer. **Mem/scratch** 1–3 GB per '
                         'rank / 1–20 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error: ±14 %, ammonia–formic acid, computed span 168.3–212.8 cm⁻¹ '
                         'against 195.18(7) `[M]` — the same figure for every row, and the accuracy cells '
                         'are capped at it accordingly.** **Mitigation**: report the barrier with the '
                         'reduced mass and the path; run the relaxed scan in both directions and report '
                         'the hysteresis; state whether the path is one- or two-dimensional.'}},
 {'row_id': 'T7-1h',
  'source_line': 3211,
  'tier': '1 h',
  'method_text': 'ωB97X-V/def2-TZVPP relaxed 1-D scan',
  'delivers': '**V₃ ±14 % `[M]`**, one-dimensional, better electronic structure',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'same coverage limitation; the improvement is in the energy, not the path',
  'expansion': {'source_line': 3219,
                'notes': '**Expansion block — Table 7.** Core-h as the standard ladder. **State-in**: the '
                         "T3O-3h or T3O-12h geometry plus `.gbw`; scan rows consume the previous point's "
                         '`.gbw` by `! MORead` (free, and each point is a small perturbation). '
                         '**State-out**: `.xyz` + `.gbw` per scan step, the fitted path, and the effective '
                         'one-dimensional potential — **D**, because a relaxed scan is a set of '
                         'independent optimisations and is decomposed rather than checkpointed. '
                         '**Frozen-mono**: `frozen-iso` for the intermolecular torsion; `relaxed` if the '
                         'barrier involves an internal rotor of one monomer. **Mem/scratch** 1–3 GB per '
                         'rank / 1–20 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error: ±14 %, ammonia–formic acid, computed span 168.3–212.8 cm⁻¹ '
                         'against 195.18(7) `[M]` — the same figure for every row, and the accuracy cells '
                         'are capped at it accordingly.** **Mitigation**: report the barrier with the '
                         'reduced mass and the path; run the relaxed scan in both directions and report '
                         'the hysteresis; state whether the path is one- or two-dimensional.'}},
 {'row_id': 'T7-3h',
  'source_line': 3212,
  'tier': '3 h',
  'method_text': '2-D (τ, R) relaxed scan',
  'delivers': '**V₃ ±14 % `[M]`**, two-dimensional coupling captured',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'the coupling to the intermolecular stretch is often what the one-dimensional path misses',
  'expansion': {'source_line': 3219,
                'notes': '**Expansion block — Table 7.** Core-h as the standard ladder. **State-in**: the '
                         "T3O-3h or T3O-12h geometry plus `.gbw`; scan rows consume the previous point's "
                         '`.gbw` by `! MORead` (free, and each point is a small perturbation). '
                         '**State-out**: `.xyz` + `.gbw` per scan step, the fitted path, and the effective '
                         'one-dimensional potential — **D**, because a relaxed scan is a set of '
                         'independent optimisations and is decomposed rather than checkpointed. '
                         '**Frozen-mono**: `frozen-iso` for the intermolecular torsion; `relaxed` if the '
                         'barrier involves an internal rotor of one monomer. **Mem/scratch** 1–3 GB per '
                         'rank / 1–20 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error: ±14 %, ammonia–formic acid, computed span 168.3–212.8 cm⁻¹ '
                         'against 195.18(7) `[M]` — the same figure for every row, and the accuracy cells '
                         'are capped at it accordingly.** **Mitigation**: report the barrier with the '
                         'reduced mass and the path; run the relaxed scan in both directions and report '
                         'the hysteresis; state whether the path is one- or two-dimensional.'}},
 {'row_id': 'T7-12h',
  'source_line': 3213,
  'tier': '12 h',
  'method_text': '2-D scan + one-dimensional torsional Schrödinger solution → A/E splittings',
  'delivers': 'A/E splittings and the reduced barrier s; **±14 % on V₃ propagates steeply into the '
              'splitting**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'the splitting depends exponentially on V₃, so a 14 % barrier error is not a 14 % '
                 'splitting error',
  'expansion': {'source_line': 3219,
                'notes': '**Expansion block — Table 7.** Core-h as the standard ladder. **State-in**: the '
                         "T3O-3h or T3O-12h geometry plus `.gbw`; scan rows consume the previous point's "
                         '`.gbw` by `! MORead` (free, and each point is a small perturbation). '
                         '**State-out**: `.xyz` + `.gbw` per scan step, the fitted path, and the effective '
                         'one-dimensional potential — **D**, because a relaxed scan is a set of '
                         'independent optimisations and is decomposed rather than checkpointed. '
                         '**Frozen-mono**: `frozen-iso` for the intermolecular torsion; `relaxed` if the '
                         'barrier involves an internal rotor of one monomer. **Mem/scratch** 1–3 GB per '
                         'rank / 1–20 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error: ±14 %, ammonia–formic acid, computed span 168.3–212.8 cm⁻¹ '
                         'against 195.18(7) `[M]` — the same figure for every row, and the accuracy cells '
                         'are capped at it accordingly.** **Mitigation**: report the barrier with the '
                         'reduced mass and the path; run the relaxed scan in both directions and report '
                         'the hysteresis; state whether the path is one- or two-dimensional.'}},
 {'row_id': 'T7-1d',
  'source_line': 3214,
  'tier': '1 d',
  'method_text': 'conformer-resolved barriers across the Table 1 ensemble',
  'delivers': '**V₃ ±14 % `[M]`** per conformer',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': "ranking conformers by barrier inherits the energy ranking's error",
  'expansion': {'source_line': 3219,
                'notes': '**Expansion block — Table 7.** Core-h as the standard ladder. **State-in**: the '
                         "T3O-3h or T3O-12h geometry plus `.gbw`; scan rows consume the previous point's "
                         '`.gbw` by `! MORead` (free, and each point is a small perturbation). '
                         '**State-out**: `.xyz` + `.gbw` per scan step, the fitted path, and the effective '
                         'one-dimensional potential — **D**, because a relaxed scan is a set of '
                         'independent optimisations and is decomposed rather than checkpointed. '
                         '**Frozen-mono**: `frozen-iso` for the intermolecular torsion; `relaxed` if the '
                         'barrier involves an internal rotor of one monomer. **Mem/scratch** 1–3 GB per '
                         'rank / 1–20 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error: ±14 %, ammonia–formic acid, computed span 168.3–212.8 cm⁻¹ '
                         'against 195.18(7) `[M]` — the same figure for every row, and the accuracy cells '
                         'are capped at it accordingly.** **Mitigation**: report the barrier with the '
                         'reduced mass and the path; run the relaxed scan in both directions and report '
                         'the hysteresis; state whether the path is one- or two-dimensional.'}},
 {'row_id': 'T7-3d',
  'source_line': 3215,
  'tier': '3 d',
  'method_text': 'MPQC CCSD(T)-F12 single points along the converged path',
  'delivers': 'the barrier at coupled-cluster quality, still **±14 %** against experiment',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**the cap is set by the benchmark spread, not by the electronic structure**',
  'expansion': {'source_line': 3219,
                'notes': '**Expansion block — Table 7.** Core-h as the standard ladder. **State-in**: the '
                         "T3O-3h or T3O-12h geometry plus `.gbw`; scan rows consume the previous point's "
                         '`.gbw` by `! MORead` (free, and each point is a small perturbation). '
                         '**State-out**: `.xyz` + `.gbw` per scan step, the fitted path, and the effective '
                         'one-dimensional potential — **D**, because a relaxed scan is a set of '
                         'independent optimisations and is decomposed rather than checkpointed. '
                         '**Frozen-mono**: `frozen-iso` for the intermolecular torsion; `relaxed` if the '
                         'barrier involves an internal rotor of one monomer. **Mem/scratch** 1–3 GB per '
                         'rank / 1–20 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error: ±14 %, ammonia–formic acid, computed span 168.3–212.8 cm⁻¹ '
                         'against 195.18(7) `[M]` — the same figure for every row, and the accuracy cells '
                         'are capped at it accordingly.** **Mitigation**: report the barrier with the '
                         'reduced mass and the path; run the relaxed scan in both directions and report '
                         'the hysteresis; state whether the path is one- or two-dimensional.'}},
 {'row_id': 'T7-1w',
  'source_line': 3216,
  'tier': '1 w',
  'method_text': 'tunnelling splitting from an instanton or WKB treatment on the fitted path',
  'delivers': '**an estimate only — factor of 3 at best**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'splittings span 6 MHz to 279,650 MHz within one molecule `[M]`',
  'expansion': {'source_line': 3219,
                'notes': '**Expansion block — Table 7.** Core-h as the standard ladder. **State-in**: the '
                         "T3O-3h or T3O-12h geometry plus `.gbw`; scan rows consume the previous point's "
                         '`.gbw` by `! MORead` (free, and each point is a small perturbation). '
                         '**State-out**: `.xyz` + `.gbw` per scan step, the fitted path, and the effective '
                         'one-dimensional potential — **D**, because a relaxed scan is a set of '
                         'independent optimisations and is decomposed rather than checkpointed. '
                         '**Frozen-mono**: `frozen-iso` for the intermolecular torsion; `relaxed` if the '
                         'barrier involves an internal rotor of one monomer. **Mem/scratch** 1–3 GB per '
                         'rank / 1–20 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error: ±14 %, ammonia–formic acid, computed span 168.3–212.8 cm⁻¹ '
                         'against 195.18(7) `[M]` — the same figure for every row, and the accuracy cells '
                         'are capped at it accordingly.** **Mitigation**: report the barrier with the '
                         'reduced mass and the path; run the relaxed scan in both directions and report '
                         'the hysteresis; state whether the path is one- or two-dimensional.'}},
 {'row_id': 'T7-1mo',
  'source_line': 3217,
  'tier': '1 mo',
  'method_text': 'full VRT treatment on the Table 2 6-D surface',
  'delivers': 'band origins and splittings for the coupled manifold',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': '**no tier in this document reliably delivers a tunnelling splitting**; report the '
                 'barrier, the reduced mass and the path',
  'expansion': {'source_line': 3219,
                'notes': '**Expansion block — Table 7.** Core-h as the standard ladder. **State-in**: the '
                         "T3O-3h or T3O-12h geometry plus `.gbw`; scan rows consume the previous point's "
                         '`.gbw` by `! MORead` (free, and each point is a small perturbation). '
                         '**State-out**: `.xyz` + `.gbw` per scan step, the fitted path, and the effective '
                         'one-dimensional potential — **D**, because a relaxed scan is a set of '
                         'independent optimisations and is decomposed rather than checkpointed. '
                         '**Frozen-mono**: `frozen-iso` for the intermolecular torsion; `relaxed` if the '
                         'barrier involves an internal rotor of one monomer. **Mem/scratch** 1–3 GB per '
                         'rank / 1–20 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error: ±14 %, ammonia–formic acid, computed span 168.3–212.8 cm⁻¹ '
                         'against 195.18(7) `[M]` — the same figure for every row, and the accuracy cells '
                         'are capped at it accordingly.** **Mitigation**: report the barrier with the '
                         'reduced mass and the path; run the relaxed scan in both directions and report '
                         'the hysteresis; state whether the path is one- or two-dimensional.'}},
 {'row_id': 'T8O-10s',
  'source_line': 3229,
  'tier': '10 s',
  'method_text': 'GFN2-xTB harmonic frequencies',
  'delivers': 'mode ordering only',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'semi-empirical frequencies are qualitative',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8O-1min',
  'source_line': 3230,
  'tier': '1 min',
  'method_text': 'MLFF harmonic frequencies',
  'delivers': 'mode ordering, fast, on the GPU',
  'concurrency_text': '**G**',
  'product_text': 'A',
  'limitations': 'float32 noise sits near the soft-mode frequencies',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8O-30min',
  'source_line': 3231,
  'tier': '30 min',
  'method_text': 'r²SCAN-3c analytic harmonic Hessian',
  'delivers': '**ω ±25–40 cm⁻¹ `[M]`** (aRMSD 35 cm⁻¹)',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'harmonic; intermolecular modes are the least harmonic thing in the system',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8O-1h',
  'source_line': 3232,
  'tier': '1 h',
  'method_text': 'ωB97X-V/def2-TZVPP analytic harmonic Hessian + IR intensities',
  'delivers': '**ω ±20–35 cm⁻¹ `[E]`**, intensities',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'analytic Hessians are **not restartable**',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8O-3h',
  'source_line': 3233,
  'tier': '3 h',
  'method_text': 'DFT VPT2 fundamentals',
  'delivers': '**ν ±15–25 cm⁻¹ `[E]`**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**no linear molecules**; VPT2 is sensitive to numerical noise',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8O-12h',
  'source_line': 3234,
  'tier': '12 h',
  'method_text': 'VPT2 with a substituted hybrid force field: high-level harmonic + low-level anharmonic',
  'delivers': '**ν ±10–20 cm⁻¹ `[E]`** at no extra anharmonic cost',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**hybrid fields degrade for low-symmetry systems and fail catastrophically under '
                 'large-amplitude motion** — exclude every mode below ~100 cm⁻¹',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8O-1d',
  'source_line': 3235,
  'tier': '1 d',
  'method_text': 'MLFF molecular dynamics with a dipole surface → IR from the dipole autocorrelation',
  'delivers': 'a full spectrum including anharmonic couplings',
  'concurrency_text': '**G**',
  'product_text': 'A',
  'limitations': '**the Fourier resolution bound is Δν̃ = 1/(cT): 2 ps → 17 cm⁻¹, 4 ps → 8 cm⁻¹ `[D]`** — '
                 'and band positions are limited by *sampling* long before they are limited by that bound',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8O-3d',
  'source_line': 3236,
  'tier': '3 d',
  'method_text': 'band origins from the Table 2 3-D DVR',
  'delivers': '**±5–20 cm⁻¹ `[E]`** for the intermolecular manifold',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'only the modes the surface spans',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8O-1w',
  'source_line': 3237,
  'tier': '1 w',
  'method_text': '6-D variational band origins on the Δ-learned surface',
  'delivers': '**±1–5 cm⁻¹ `[E]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'the fit residual is the floor: report it in cm⁻¹',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8O-1mo',
  'source_line': 3238,
  'tier': '1 mo',
  'method_text': '**— a CCSD(T)-quality anharmonic force field is not reachable in this track**',
  'delivers': '—',
  'concurrency_text': '—',
  'product_text': '—',
  'limitations': '**Track gap.** `!VPT2` accepts only analytic-Hessian methods, and the DLPNO alternative '
                 'needs 176,400 single points at N = 10. **Escalate to `T8C-1mo`**',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8C-10s',
  'source_line': 3244,
  'tier': '10 s',
  'method_text': '—',
  'delivers': '—',
  'concurrency_text': '—',
  'product_text': '—',
  'limitations': '**Cannot fill** — CFOUR has no semi-empirical or force-field engine. Use `T8O-10s`',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8C-1min',
  'source_line': 3245,
  'tier': '1 min',
  'method_text': '—',
  'delivers': '—',
  'concurrency_text': '—',
  'product_text': '—',
  'limitations': '**Cannot fill** — no machine-learned or force-field path. Use `T8O-1min`',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8C-30min',
  'source_line': 3246,
  'tier': '30 min',
  'method_text': 'SCF/MP2 harmonic frequencies, `VIB=EXACT`',
  'delivers': 'ω at a low level',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'MP2 not parallelised',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8C-1h',
  'source_line': 3247,
  'tier': '1 h',
  'method_text': 'CCSD(T) analytic harmonic Hessian',
  'delivers': '**ω, IR intensities at coupled-cluster quality**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'no ROHF-based analytic second derivatives',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8C-3h',
  'source_line': 3248,
  'tier': '3 h',
  'method_text': '`ANHARM=VIBROT`',
  'delivers': 'α constants only, not fundamentals',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'insufficient for a full spectrum',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8C-12h',
  'source_line': 3249,
  'tier': '12 h',
  'method_text': '`ANHARM=VPT2`, cc-pVTZ',
  'delivers': '**fundamentals; cyclopentadiene CCSD(T)/ANO within ~0–19 cm⁻¹, ethylene ~10 cm⁻¹ `[M]`**',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'GUINEA (deperturbed VPT2, anharmonic intensities) is not public',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8C-1d',
  'source_line': 3250,
  'tier': '1 d',
  'method_text': 'the above plus resonance analysis and two-quantum transition intensities',
  'delivers': 'overtones and combination bands',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'resonance treatment is where VPT2 is most delicate',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8C-3d',
  'source_line': 3251,
  'tier': '3 d',
  'method_text': '`ANHARM=VPT2` at cc-pCVTZ/ANO1 with core correlation, queue-split',
  'delivers': '**ν within ~5–10 cm⁻¹ `[E]`**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'script-driven job splitting; `FD_PROJECT=OFF` in the parallel recipe',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8C-1w',
  'source_line': 3252,
  'tier': '1 w',
  'method_text': 'isotopologue spectra from the same force field',
  'delivers': 'full spectra for 6–15 isotopologues',
  'concurrency_text': 'C',
  'product_text': '**C**',
  'limitations': '`ANHARM=VPT2`, not `VIBROT`, is required',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T8C-1mo',
  'source_line': 3253,
  'tier': '1 mo',
  'method_text': 'the above plus relativistic and DBOC corrections',
  'delivers': 'the closed set for a heavy-atom complex',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '`ANHARM=FULLQUARTIC` unavailable publicly',
  'expansion': {'source_line': 3255,
                'notes': '**Expansion block — Tables 8-O and 8-C.** Core-h follow the standard ladder, '
                         'with 128-core figures for the 3 d, 1 w and 1 mo rows (9,216 / 21,504 / 92,160). '
                         '**State-in**: the geometry and `.gbw` (ORCA) or `JOBARC` (CFOUR) from the '
                         'corresponding Table 3 row. **State-out**: `.hess` / `FCMFINAL`, which feeds '
                         'Tables 4 and 6 and every isotopologue — ORCA analytic-frequency rows are **D** '
                         '(not restartable) while every CFOUR row is **R**. **Frozen-mono** inherits. '
                         '**Mem** 3 GB per rank (ORCA) or a 32 GB global allocation (CFOUR); scratch 6–250 '
                         'GB. **Licence** ORCA academic / CFOUR academic wet-signature. **Setup 1** yes to '
                         '3 h on the ORCA track, never on the CFOUR track. **Max benchmark error**: '
                         'r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`; small-basis C–H stretches too high "by 10–20 cm⁻¹ '
                         'or more" `[M]`; water VPT2+K overtones within 1.4 cm⁻¹ `[M]`. **Mitigation**: '
                         'state which modes were treated harmonically and which anharmonically, and '
                         'exclude every mode below ~100 cm⁻¹ from a hybrid force field.'}},
 {'row_id': 'T9-10s',
  'source_line': 3263,
  'tier': '10 s',
  'method_text': 'GFN2-xTB polarizability',
  'delivers': 'qualitative activity only',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'semi-empirical polarizabilities are indicative',
  'expansion': {'source_line': 3274,
                'notes': '**Expansion block — Table 9.** Core-h as the standard ladder. **State-in**: '
                         'geometry plus `.gbw`; the polarizability derivative rows additionally consume '
                         'the `.hess`. **State-out**: `.hess` with Raman activities; the MD rows emit '
                         'trajectories and a polarizability time series — **D** for analytic rows, **R** '
                         'for MD (`%md Restart IfExists`). **Frozen-mono** inherits. **Mem** 2–4 GB per '
                         'rank / 3–40 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error** r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`, and **the same figure may not '
                         'certify five different bands** — the tiers here are differentiated by coverage '
                         'and by whether anharmonicity is included, per Rule 3. **Mitigation**: report '
                         'activities as ratios, not absolutes, and state the polarizability basis.'}},
 {'row_id': 'T9-1min',
  'source_line': 3264,
  'tier': '1 min',
  'method_text': 'MLFF polarizability surface, where available',
  'delivers': 'activity pattern',
  'concurrency_text': '**G**',
  'product_text': 'A',
  'limitations': 'polarizability models are less mature than energy models',
  'expansion': {'source_line': 3274,
                'notes': '**Expansion block — Table 9.** Core-h as the standard ladder. **State-in**: '
                         'geometry plus `.gbw`; the polarizability derivative rows additionally consume '
                         'the `.hess`. **State-out**: `.hess` with Raman activities; the MD rows emit '
                         'trajectories and a polarizability time series — **D** for analytic rows, **R** '
                         'for MD (`%md Restart IfExists`). **Frozen-mono** inherits. **Mem** 2–4 GB per '
                         'rank / 3–40 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error** r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`, and **the same figure may not '
                         'certify five different bands** — the tiers here are differentiated by coverage '
                         'and by whether anharmonicity is included, per Rule 3. **Mitigation**: report '
                         'activities as ratios, not absolutes, and state the polarizability basis.'}},
 {'row_id': 'T9-30min',
  'source_line': 3265,
  'tier': '30 min',
  'method_text': 'r²SCAN-3c numerical Raman intensities',
  'delivers': '**ω ±25–40 cm⁻¹ `[M]`**, activities to a factor of ~2 `[E]`',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'Raman intensities need polarizability derivatives, hence extra displacements',
  'expansion': {'source_line': 3274,
                'notes': '**Expansion block — Table 9.** Core-h as the standard ladder. **State-in**: '
                         'geometry plus `.gbw`; the polarizability derivative rows additionally consume '
                         'the `.hess`. **State-out**: `.hess` with Raman activities; the MD rows emit '
                         'trajectories and a polarizability time series — **D** for analytic rows, **R** '
                         'for MD (`%md Restart IfExists`). **Frozen-mono** inherits. **Mem** 2–4 GB per '
                         'rank / 3–40 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error** r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`, and **the same figure may not '
                         'certify five different bands** — the tiers here are differentiated by coverage '
                         'and by whether anharmonicity is included, per Rule 3. **Mitigation**: report '
                         'activities as ratios, not absolutes, and state the polarizability basis.'}},
 {'row_id': 'T9-1h',
  'source_line': 3266,
  'tier': '1 h',
  'method_text': 'ωB97X-V/def2-TZVPP Raman',
  'delivers': '**ω ±20–35 cm⁻¹ `[E]`**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'diffuse functions matter more for polarizabilities than for energies',
  'expansion': {'source_line': 3274,
                'notes': '**Expansion block — Table 9.** Core-h as the standard ladder. **State-in**: '
                         'geometry plus `.gbw`; the polarizability derivative rows additionally consume '
                         'the `.hess`. **State-out**: `.hess` with Raman activities; the MD rows emit '
                         'trajectories and a polarizability time series — **D** for analytic rows, **R** '
                         'for MD (`%md Restart IfExists`). **Frozen-mono** inherits. **Mem** 2–4 GB per '
                         'rank / 3–40 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error** r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`, and **the same figure may not '
                         'certify five different bands** — the tiers here are differentiated by coverage '
                         'and by whether anharmonicity is included, per Rule 3. **Mitigation**: report '
                         'activities as ratios, not absolutes, and state the polarizability basis.'}},
 {'row_id': 'T9-3h',
  'source_line': 3267,
  'tier': '3 h',
  'method_text': 'Raman with an augmented basis',
  'delivers': 'intensities with converged polarizabilities',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'near-linear dependence risk from diffuse sets',
  'expansion': {'source_line': 3274,
                'notes': '**Expansion block — Table 9.** Core-h as the standard ladder. **State-in**: '
                         'geometry plus `.gbw`; the polarizability derivative rows additionally consume '
                         'the `.hess`. **State-out**: `.hess` with Raman activities; the MD rows emit '
                         'trajectories and a polarizability time series — **D** for analytic rows, **R** '
                         'for MD (`%md Restart IfExists`). **Frozen-mono** inherits. **Mem** 2–4 GB per '
                         'rank / 3–40 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error** r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`, and **the same figure may not '
                         'certify five different bands** — the tiers here are differentiated by coverage '
                         'and by whether anharmonicity is included, per Rule 3. **Mitigation**: report '
                         'activities as ratios, not absolutes, and state the polarizability basis.'}},
 {'row_id': 'T9-12h',
  'source_line': 3268,
  'tier': '12 h',
  'method_text': 'VPT2 anharmonic Raman',
  'delivers': '**ν ±15–25 cm⁻¹ `[E]`**',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': 'anharmonic intensities are the least reliable output of VPT2',
  'expansion': {'source_line': 3274,
                'notes': '**Expansion block — Table 9.** Core-h as the standard ladder. **State-in**: '
                         'geometry plus `.gbw`; the polarizability derivative rows additionally consume '
                         'the `.hess`. **State-out**: `.hess` with Raman activities; the MD rows emit '
                         'trajectories and a polarizability time series — **D** for analytic rows, **R** '
                         'for MD (`%md Restart IfExists`). **Frozen-mono** inherits. **Mem** 2–4 GB per '
                         'rank / 3–40 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error** r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`, and **the same figure may not '
                         'certify five different bands** — the tiers here are differentiated by coverage '
                         'and by whether anharmonicity is included, per Rule 3. **Mitigation**: report '
                         'activities as ratios, not absolutes, and state the polarizability basis.'}},
 {'row_id': 'T9-1d',
  'source_line': 3269,
  'tier': '1 d',
  'method_text': 'MLFF MD with a polarizability surface → Raman from the polarizability autocorrelation',
  'delivers': 'a full spectrum',
  'concurrency_text': '**G**',
  'product_text': 'A',
  'limitations': '**the polarizability-surface fitting error is not benchmarked for this class — `n.a.`; '
                 'planning value a factor of 2 in intensity `[E]`**',
  'expansion': {'source_line': 3274,
                'notes': '**Expansion block — Table 9.** Core-h as the standard ladder. **State-in**: '
                         'geometry plus `.gbw`; the polarizability derivative rows additionally consume '
                         'the `.hess`. **State-out**: `.hess` with Raman activities; the MD rows emit '
                         'trajectories and a polarizability time series — **D** for analytic rows, **R** '
                         'for MD (`%md Restart IfExists`). **Frozen-mono** inherits. **Mem** 2–4 GB per '
                         'rank / 3–40 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error** r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`, and **the same figure may not '
                         'certify five different bands** — the tiers here are differentiated by coverage '
                         'and by whether anharmonicity is included, per Rule 3. **Mitigation**: report '
                         'activities as ratios, not absolutes, and state the polarizability basis.'}},
 {'row_id': 'T9-3d',
  'source_line': 3270,
  'tier': '3 d',
  'method_text': 'Placzek-approximation decomposition into isotropic and anisotropic parts',
  'delivers': 'depolarisation ratios',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': "**the decomposition's validity for a floppy complex is not established — `n.a.`; treat "
                 'as qualitative `[E]`**',
  'expansion': {'source_line': 3274,
                'notes': '**Expansion block — Table 9.** Core-h as the standard ladder. **State-in**: '
                         'geometry plus `.gbw`; the polarizability derivative rows additionally consume '
                         'the `.hess`. **State-out**: `.hess` with Raman activities; the MD rows emit '
                         'trajectories and a polarizability time series — **D** for analytic rows, **R** '
                         'for MD (`%md Restart IfExists`). **Frozen-mono** inherits. **Mem** 2–4 GB per '
                         'rank / 3–40 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error** r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`, and **the same figure may not '
                         'certify five different bands** — the tiers here are differentiated by coverage '
                         'and by whether anharmonicity is included, per Rule 3. **Mitigation**: report '
                         'activities as ratios, not absolutes, and state the polarizability basis.'}},
 {'row_id': 'T9-1w',
  'source_line': 3271,
  'tier': '1 w',
  'method_text': 'Raman band origins from the Table 2 surface',
  'delivers': 'intermolecular Raman activity',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'only the modes the surface spans',
  'expansion': {'source_line': 3274,
                'notes': '**Expansion block — Table 9.** Core-h as the standard ladder. **State-in**: '
                         'geometry plus `.gbw`; the polarizability derivative rows additionally consume '
                         'the `.hess`. **State-out**: `.hess` with Raman activities; the MD rows emit '
                         'trajectories and a polarizability time series — **D** for analytic rows, **R** '
                         'for MD (`%md Restart IfExists`). **Frozen-mono** inherits. **Mem** 2–4 GB per '
                         'rank / 3–40 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error** r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`, and **the same figure may not '
                         'certify five different bands** — the tiers here are differentiated by coverage '
                         'and by whether anharmonicity is included, per Rule 3. **Mitigation**: report '
                         'activities as ratios, not absolutes, and state the polarizability basis.'}},
 {'row_id': 'T9-1mo',
  'source_line': 3272,
  'tier': '1 mo',
  'method_text': 'resonance Raman or a full polarizability surface',
  'delivers': 'the complete activity map',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**dominated for every microwave observable**; retain only if Raman is itself the '
                 'deliverable',
  'expansion': {'source_line': 3274,
                'notes': '**Expansion block — Table 9.** Core-h as the standard ladder. **State-in**: '
                         'geometry plus `.gbw`; the polarizability derivative rows additionally consume '
                         'the `.hess`. **State-out**: `.hess` with Raman activities; the MD rows emit '
                         'trajectories and a polarizability time series — **D** for analytic rows, **R** '
                         'for MD (`%md Restart IfExists`). **Frozen-mono** inherits. **Mem** 2–4 GB per '
                         'rank / 3–40 GB. **Licence** ORCA academic. **Setup 1** yes to 3 h. **Max '
                         'benchmark error** r²SCAN-3c aRMSD 35 cm⁻¹ `[M]`, and **the same figure may not '
                         'certify five different bands** — the tiers here are differentiated by coverage '
                         'and by whether anharmonicity is included, per Rule 3. **Mitigation**: report '
                         'activities as ratios, not absolutes, and state the polarizability basis.'}},
 {'row_id': 'T10-10s',
  'source_line': 3284,
  'tier': '10 s',
  'method_text': 'GFN2-xTB electronic gap',
  'delivers': 'a qualitative excitation estimate',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'not a spectroscopic prediction',
  'expansion': {'source_line': 3295,
                'notes': '**Expansion block — Table 10.** Core-h: standard ladder to 3 d; **T10-1w is '
                         '21,504 core-h at 128 cores `[D]`, not 1,344** — the arithmetic is 2,500 '
                         'trajectories × ~1,000 steps × 5–15 s ÷ 3,600, and the row does not fit Setup 2 '
                         'at all. **State-in**: geometry plus `.gbw`; QCxMS consumes a geometry and a '
                         'charge/multiplicity sidecar. **State-out**: `.cis` eigenvectors (TD-DFT, '
                         'consumed by `orca_plot` and STEOM), shielding tensors, trajectory files — **D** '
                         'throughout; QCxMS trajectories are independent and are the decomposition unit. '
                         '**Frozen-mono** `relaxed`. **Mem** 2–8 GB per rank / 3–100 GB. **Licence** ORCA '
                         'academic; QCxMS free. **Setup 1** yes to 1 h; the 1 d and 3 d rows fit only as '
                         'ensembles of independent short jobs, which is exactly what they are. **Max '
                         'benchmark error**: not benchmarked in domain for weakly bound complexes — '
                         '**`n.a.`; planning values as stated, all `[E]`.** **Mitigation**: for NMR, '
                         'average over the Boltzmann ensemble before comparing to experiment; for QCxMS, '
                         'report the trajectory count and the seed.'}},
 {'row_id': 'T10-1min',
  'source_line': 3285,
  'tier': '1 min',
  'method_text': 'sTDA/sTDDFT on the DFT density',
  'delivers': 'absorption band positions to ~0.3–0.5 eV `[E]`',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'simplified TDDFT is a screening tool',
  'expansion': {'source_line': 3295,
                'notes': '**Expansion block — Table 10.** Core-h: standard ladder to 3 d; **T10-1w is '
                         '21,504 core-h at 128 cores `[D]`, not 1,344** — the arithmetic is 2,500 '
                         'trajectories × ~1,000 steps × 5–15 s ÷ 3,600, and the row does not fit Setup 2 '
                         'at all. **State-in**: geometry plus `.gbw`; QCxMS consumes a geometry and a '
                         'charge/multiplicity sidecar. **State-out**: `.cis` eigenvectors (TD-DFT, '
                         'consumed by `orca_plot` and STEOM), shielding tensors, trajectory files — **D** '
                         'throughout; QCxMS trajectories are independent and are the decomposition unit. '
                         '**Frozen-mono** `relaxed`. **Mem** 2–8 GB per rank / 3–100 GB. **Licence** ORCA '
                         'academic; QCxMS free. **Setup 1** yes to 1 h; the 1 d and 3 d rows fit only as '
                         'ensembles of independent short jobs, which is exactly what they are. **Max '
                         'benchmark error**: not benchmarked in domain for weakly bound complexes — '
                         '**`n.a.`; planning values as stated, all `[E]`.** **Mitigation**: for NMR, '
                         'average over the Boltzmann ensemble before comparing to experiment; for QCxMS, '
                         'report the trajectory count and the seed.'}},
 {'row_id': 'T10-30min',
  'source_line': 3286,
  'tier': '30 min',
  'method_text': 'TD-DFT (ωB97X-D4/def2-TZVP), 10 roots',
  'delivers': 'vertical excitations ±0.2–0.3 eV `[E]`',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'charge-transfer states in a complex need a range-separated functional and still drift',
  'expansion': {'source_line': 3295,
                'notes': '**Expansion block — Table 10.** Core-h: standard ladder to 3 d; **T10-1w is '
                         '21,504 core-h at 128 cores `[D]`, not 1,344** — the arithmetic is 2,500 '
                         'trajectories × ~1,000 steps × 5–15 s ÷ 3,600, and the row does not fit Setup 2 '
                         'at all. **State-in**: geometry plus `.gbw`; QCxMS consumes a geometry and a '
                         'charge/multiplicity sidecar. **State-out**: `.cis` eigenvectors (TD-DFT, '
                         'consumed by `orca_plot` and STEOM), shielding tensors, trajectory files — **D** '
                         'throughout; QCxMS trajectories are independent and are the decomposition unit. '
                         '**Frozen-mono** `relaxed`. **Mem** 2–8 GB per rank / 3–100 GB. **Licence** ORCA '
                         'academic; QCxMS free. **Setup 1** yes to 1 h; the 1 d and 3 d rows fit only as '
                         'ensembles of independent short jobs, which is exactly what they are. **Max '
                         'benchmark error**: not benchmarked in domain for weakly bound complexes — '
                         '**`n.a.`; planning values as stated, all `[E]`.** **Mitigation**: for NMR, '
                         'average over the Boltzmann ensemble before comparing to experiment; for QCxMS, '
                         'report the trajectory count and the seed.'}},
 {'row_id': 'T10-1h',
  'source_line': 3287,
  'tier': '1 h',
  'method_text': 'GIAO NMR shieldings at DFT',
  'delivers': '¹H and ¹³C shifts, referenced',
  'concurrency_text': '**P**',
  'product_text': 'A',
  'limitations': 'shifts in a weakly bound complex are dominated by conformational averaging, not by the '
                 'shielding calculation',
  'expansion': {'source_line': 3295,
                'notes': '**Expansion block — Table 10.** Core-h: standard ladder to 3 d; **T10-1w is '
                         '21,504 core-h at 128 cores `[D]`, not 1,344** — the arithmetic is 2,500 '
                         'trajectories × ~1,000 steps × 5–15 s ÷ 3,600, and the row does not fit Setup 2 '
                         'at all. **State-in**: geometry plus `.gbw`; QCxMS consumes a geometry and a '
                         'charge/multiplicity sidecar. **State-out**: `.cis` eigenvectors (TD-DFT, '
                         'consumed by `orca_plot` and STEOM), shielding tensors, trajectory files — **D** '
                         'throughout; QCxMS trajectories are independent and are the decomposition unit. '
                         '**Frozen-mono** `relaxed`. **Mem** 2–8 GB per rank / 3–100 GB. **Licence** ORCA '
                         'academic; QCxMS free. **Setup 1** yes to 1 h; the 1 d and 3 d rows fit only as '
                         'ensembles of independent short jobs, which is exactly what they are. **Max '
                         'benchmark error**: not benchmarked in domain for weakly bound complexes — '
                         '**`n.a.`; planning values as stated, all `[E]`.** **Mitigation**: for NMR, '
                         'average over the Boltzmann ensemble before comparing to experiment; for QCxMS, '
                         'report the trajectory count and the seed.'}},
 {'row_id': 'T10-3h',
  'source_line': 3288,
  'tier': '3 h',
  'method_text': 'NMR with vibrational corrections from the existing force field',
  'delivers': 'corrected shifts',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': "inherits the force field's error",
  'expansion': {'source_line': 3295,
                'notes': '**Expansion block — Table 10.** Core-h: standard ladder to 3 d; **T10-1w is '
                         '21,504 core-h at 128 cores `[D]`, not 1,344** — the arithmetic is 2,500 '
                         'trajectories × ~1,000 steps × 5–15 s ÷ 3,600, and the row does not fit Setup 2 '
                         'at all. **State-in**: geometry plus `.gbw`; QCxMS consumes a geometry and a '
                         'charge/multiplicity sidecar. **State-out**: `.cis` eigenvectors (TD-DFT, '
                         'consumed by `orca_plot` and STEOM), shielding tensors, trajectory files — **D** '
                         'throughout; QCxMS trajectories are independent and are the decomposition unit. '
                         '**Frozen-mono** `relaxed`. **Mem** 2–8 GB per rank / 3–100 GB. **Licence** ORCA '
                         'academic; QCxMS free. **Setup 1** yes to 1 h; the 1 d and 3 d rows fit only as '
                         'ensembles of independent short jobs, which is exactly what they are. **Max '
                         'benchmark error**: not benchmarked in domain for weakly bound complexes — '
                         '**`n.a.`; planning values as stated, all `[E]`.** **Mitigation**: for NMR, '
                         'average over the Boltzmann ensemble before comparing to experiment; for QCxMS, '
                         'report the trajectory count and the seed.'}},
 {'row_id': 'T10-12h',
  'source_line': 3289,
  'tier': '12 h',
  'method_text': 'STEOM-DLPNO-CCSD excitations',
  'delivers': 'excitations ±0.1–0.2 eV `[E]`',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**no MDCI restart** — must fit one window',
  'expansion': {'source_line': 3295,
                'notes': '**Expansion block — Table 10.** Core-h: standard ladder to 3 d; **T10-1w is '
                         '21,504 core-h at 128 cores `[D]`, not 1,344** — the arithmetic is 2,500 '
                         'trajectories × ~1,000 steps × 5–15 s ÷ 3,600, and the row does not fit Setup 2 '
                         'at all. **State-in**: geometry plus `.gbw`; QCxMS consumes a geometry and a '
                         'charge/multiplicity sidecar. **State-out**: `.cis` eigenvectors (TD-DFT, '
                         'consumed by `orca_plot` and STEOM), shielding tensors, trajectory files — **D** '
                         'throughout; QCxMS trajectories are independent and are the decomposition unit. '
                         '**Frozen-mono** `relaxed`. **Mem** 2–8 GB per rank / 3–100 GB. **Licence** ORCA '
                         'academic; QCxMS free. **Setup 1** yes to 1 h; the 1 d and 3 d rows fit only as '
                         'ensembles of independent short jobs, which is exactly what they are. **Max '
                         'benchmark error**: not benchmarked in domain for weakly bound complexes — '
                         '**`n.a.`; planning values as stated, all `[E]`.** **Mitigation**: for NMR, '
                         'average over the Boltzmann ensemble before comparing to experiment; for QCxMS, '
                         'report the trajectory count and the seed.'}},
 {'row_id': 'T10-1d',
  'source_line': 3290,
  'tier': '1 d',
  'method_text': 'QCxMS trajectory ensemble, ~500 trajectories',
  'delivers': 'a fragmentation pattern, qualitative',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': '**single-core trajectories: run as 16 concurrent single-rank jobs, and drop to 15 when a '
                 'GPU feeder is running**',
  'expansion': {'source_line': 3295,
                'notes': '**Expansion block — Table 10.** Core-h: standard ladder to 3 d; **T10-1w is '
                         '21,504 core-h at 128 cores `[D]`, not 1,344** — the arithmetic is 2,500 '
                         'trajectories × ~1,000 steps × 5–15 s ÷ 3,600, and the row does not fit Setup 2 '
                         'at all. **State-in**: geometry plus `.gbw`; QCxMS consumes a geometry and a '
                         'charge/multiplicity sidecar. **State-out**: `.cis` eigenvectors (TD-DFT, '
                         'consumed by `orca_plot` and STEOM), shielding tensors, trajectory files — **D** '
                         'throughout; QCxMS trajectories are independent and are the decomposition unit. '
                         '**Frozen-mono** `relaxed`. **Mem** 2–8 GB per rank / 3–100 GB. **Licence** ORCA '
                         'academic; QCxMS free. **Setup 1** yes to 1 h; the 1 d and 3 d rows fit only as '
                         'ensembles of independent short jobs, which is exactly what they are. **Max '
                         'benchmark error**: not benchmarked in domain for weakly bound complexes — '
                         '**`n.a.`; planning values as stated, all `[E]`.** **Mitigation**: for NMR, '
                         'average over the Boltzmann ensemble before comparing to experiment; for QCxMS, '
                         'report the trajectory count and the seed.'}},
 {'row_id': 'T10-3d',
  'source_line': 3291,
  'tier': '3 d',
  'method_text': 'QCxMS with ~2,000 trajectories',
  'delivers': 'a converged fragmentation pattern',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': 'statistical convergence is the binding constraint, not the electronic structure',
  'expansion': {'source_line': 3295,
                'notes': '**Expansion block — Table 10.** Core-h: standard ladder to 3 d; **T10-1w is '
                         '21,504 core-h at 128 cores `[D]`, not 1,344** — the arithmetic is 2,500 '
                         'trajectories × ~1,000 steps × 5–15 s ÷ 3,600, and the row does not fit Setup 2 '
                         'at all. **State-in**: geometry plus `.gbw`; QCxMS consumes a geometry and a '
                         'charge/multiplicity sidecar. **State-out**: `.cis` eigenvectors (TD-DFT, '
                         'consumed by `orca_plot` and STEOM), shielding tensors, trajectory files — **D** '
                         'throughout; QCxMS trajectories are independent and are the decomposition unit. '
                         '**Frozen-mono** `relaxed`. **Mem** 2–8 GB per rank / 3–100 GB. **Licence** ORCA '
                         'academic; QCxMS free. **Setup 1** yes to 1 h; the 1 d and 3 d rows fit only as '
                         'ensembles of independent short jobs, which is exactly what they are. **Max '
                         'benchmark error**: not benchmarked in domain for weakly bound complexes — '
                         '**`n.a.`; planning values as stated, all `[E]`.** **Mitigation**: for NMR, '
                         'average over the Boltzmann ensemble before comparing to experiment; for QCxMS, '
                         'report the trajectory count and the seed.'}},
 {'row_id': 'T10-1w',
  'source_line': 3292,
  'tier': '1 w',
  'method_text': 'QCxMS at a higher level, **~2,500 trajectories (re-costed, was ~50,000)**',
  'delivers': 'branching ratios',
  'concurrency_text': 'C',
  'product_text': 'A',
  'limitations': "**v3's specification was infeasible by 10–30×; this row is Setup-3-only and its "
                 'core-hours are quoted at 128 cores**',
  'expansion': {'source_line': 3295,
                'notes': '**Expansion block — Table 10.** Core-h: standard ladder to 3 d; **T10-1w is '
                         '21,504 core-h at 128 cores `[D]`, not 1,344** — the arithmetic is 2,500 '
                         'trajectories × ~1,000 steps × 5–15 s ÷ 3,600, and the row does not fit Setup 2 '
                         'at all. **State-in**: geometry plus `.gbw`; QCxMS consumes a geometry and a '
                         'charge/multiplicity sidecar. **State-out**: `.cis` eigenvectors (TD-DFT, '
                         'consumed by `orca_plot` and STEOM), shielding tensors, trajectory files — **D** '
                         'throughout; QCxMS trajectories are independent and are the decomposition unit. '
                         '**Frozen-mono** `relaxed`. **Mem** 2–8 GB per rank / 3–100 GB. **Licence** ORCA '
                         'academic; QCxMS free. **Setup 1** yes to 1 h; the 1 d and 3 d rows fit only as '
                         'ensembles of independent short jobs, which is exactly what they are. **Max '
                         'benchmark error**: not benchmarked in domain for weakly bound complexes — '
                         '**`n.a.`; planning values as stated, all `[E]`.** **Mitigation**: for NMR, '
                         'average over the Boltzmann ensemble before comparing to experiment; for QCxMS, '
                         'report the trajectory count and the seed.'}},
 {'row_id': 'T10-1mo',
  'source_line': 3293,
  'tier': '1 mo',
  'method_text': 'full multi-reference or high-level excited-state treatment',
  'delivers': 'reference excitation energies',
  'concurrency_text': '**S**',
  'product_text': 'A',
  'limitations': '**dominated for every microwave observable**',
  'expansion': {'source_line': 3295,
                'notes': '**Expansion block — Table 10.** Core-h: standard ladder to 3 d; **T10-1w is '
                         '21,504 core-h at 128 cores `[D]`, not 1,344** — the arithmetic is 2,500 '
                         'trajectories × ~1,000 steps × 5–15 s ÷ 3,600, and the row does not fit Setup 2 '
                         'at all. **State-in**: geometry plus `.gbw`; QCxMS consumes a geometry and a '
                         'charge/multiplicity sidecar. **State-out**: `.cis` eigenvectors (TD-DFT, '
                         'consumed by `orca_plot` and STEOM), shielding tensors, trajectory files — **D** '
                         'throughout; QCxMS trajectories are independent and are the decomposition unit. '
                         '**Frozen-mono** `relaxed`. **Mem** 2–8 GB per rank / 3–100 GB. **Licence** ORCA '
                         'academic; QCxMS free. **Setup 1** yes to 1 h; the 1 d and 3 d rows fit only as '
                         'ensembles of independent short jobs, which is exactly what they are. **Max '
                         'benchmark error**: not benchmarked in domain for weakly bound complexes — '
                         '**`n.a.`; planning values as stated, all `[E]`.** **Mitigation**: for NMR, '
                         'average over the Boltzmann ensemble before comparing to experiment; for QCxMS, '
                         'report the trajectory count and the seed.'}}]
