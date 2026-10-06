# Task 1.2.5 Dispatch Specification: Structured L3 Breakdown

**Parent Task:** Level 1: Task 1: Implement Ingestion Plane & Physical Invariant Foundation (VR-01) - Dynamic Mendeleev mass queries, Eckart frame translation/rotation zeroing, and two-stage conformer deduplication with automorphism invariance.  
**Level 2 Task:** Engage `cochem-sdp-manager` to generate PMBOK/SWEBOK compliant Work Breakdown Structure  
**Specific Task to Execute:** `1.2.5 - Structured L3 breakdown across Pre-Flight, Scope Decomposition, Risk & Governance, Artifact Assembly, and Adversarial Audit`  
**Exact Execution Agent:** `cochem-sdp-manager`  
**Canonical Dispatch File:** [`task1_2_5_dispatch_prompt.md`](file:///C:/Users/ansac/.gemini/antigravity-cli/scratch/task1_2_5_dispatch_prompt.md)  
**Target Persistence File:** [`task1_level2_wbs_breakdown.md`](file:///C:/Users/ansac/.gemini/antigravity-cli/scratch/task1_level2_wbs_breakdown.md)  

---

## 1. Execution Agent Selection

**Designated Execution Agent:** `cochem-sdp-manager`

### Authoritative Justification:
1. **Taxonomy Alignment:** In the CoChem Multi-Agent taxonomy, `cochem-sdp-manager` (Software Development Plan Manager) is designated as the sole authoritative agent responsible for formal PMBOK 7th Edition and SWEBOK v3 Work Breakdown Structure (WBS) formulation, scope reconciliation (PMBOK 100% Rule), and MECE work package atomization.
2. **Historical Ledger Parity:** All preceding ratified WBS specifications in the project—including Task 2 ([`task2_level2_wbs_breakdown.md`](file:///C:/Users/ansac/.gemini/antigravity-cli/scratch/task2_level2_wbs_breakdown.md)), Task 3 ([`task3_level2_wbs_breakdown.md`](file:///C:/Users/ansac/.gemini/antigravity-cli/scratch/task3_level2_wbs_breakdown.md)), and Task 5 ([`task5_level2_wbs_breakdown.md`](file:///C:/Users/ansac/.gemini/antigravity-cli/scratch/task5_level2_wbs_breakdown.md))—were authored by `cochem-sdp-manager`. Assigning Task 1.2.5 to `cochem-sdp-manager` maintains role segregation, ensures single-agent accountability, and preserves architectural integrity.

---

## 2. Authoritative Dispatch Prompt for `cochem-sdp-manager`

```markdown
You are cochem-sdp-manager, the Software Development Project Manager for the CoChem agent swarm. You apply PMBOK 7th Edition and SWEBOK v3 principles to structure engineering goals into formal, actionable, and zero-mock Work Breakdown Structures (WBS).

================================================================================
PROJECT HIERARCHY & TASK ASSIGNMENT
================================================================================
- Level 1: Task 1: Implement Ingestion Plane & Physical Invariant Foundation (VR-01) - Dynamic Mendeleev mass queries, Eckart frame translation/rotation zeroing, and two-stage conformer deduplication with automorphism invariance.
- Level 2: Engage cochem-sdp-manager to generate PMBOK/SWEBOK compliant Work Breakdown Structure.
- Specific Task to Execute:
  1.2.5 - Structured L3 breakdown across Pre-Flight, Scope Decomposition, Risk & Governance, Artifact Assembly, and Adversarial Audit.

================================================================================
MANDATORY OPERATIONAL RULE 1: INGEST EXISTING FILES FOR CONTEXT
================================================================================
Before synthesizing any content, you MUST use your tools (view_file, grep_search, list_dir, find_by_name) to inspect the local filesystem and establish complete context:
1. Examine existing WBS breakdown artifacts for structural standards and formatting conventions:
   - C:/Users/ansac/.gemini/antigravity-cli/scratch/task2_level2_wbs_breakdown.md
   - C:/Users/ansac/.gemini/antigravity-cli/scratch/task3_level2_wbs_breakdown.md
   - C:/Users/ansac/.gemini/antigravity-cli/scratch/task5_level2_wbs_breakdown.md
2. Inspect the current swarm ledger to verify completed tasks and pending dependencies:
   - C:/Users/ansac/.gemini/antigravity-cli/scratch/swarm_state.json
3. Read relevant background guidance and index sources if accessible:
   - D:/Gdrive/__agentic/.sources/Global_Agent_Index.md

Do NOT guess the file schema, frontmatter, or matrix format. Gain full empirical context from these files first.

================================================================================
TECHNICAL SCOPE & PHYSICAL INVARIANTS (VR-01 & METHOD MATRIX v4)
================================================================================
Your L3 breakdown for Task 1 must be grounded in physical chemistry, rigorous numerical computing, and the CoChem Method Matrix v4:
1. Dynamic Mendeleev Mass Resolution:
   - All atomic and isotopic masses MUST be dynamically queried via `from mendeleev import element`.
   - Hardcoding atomic/isotopic masses or static CODATA floats is STRICTLY FORBIDDEN.
2. Eckart Frame Translation Zeroing:
   - Center-of-mass translation momentum drift must be zeroed to machine precision:
     $$\left\|\sum_{i=1}^{N} m_i \mathbf{r}_i\right\| < 10^{-12}\text{ a.u.}$$
3. Eckart Frame Rotation Zeroing:
   - Rigid-body orientation alignment strictly enforced within the special orthogonal group $\mathrm{SO}(3)$, with proper rotation matrix determinant:
     $$\det(\mathbf{U}) = +1.0$$
   - Inversion reflections ($\det(\mathbf{U}) = -1.0$) must be detected and rejected.
4. Two-Stage Conformer Deduplication:
   - Stage 1 (Topological Invariant): Weisfeiler-Lehman (WL) graph automorphism hashing to establish isomorphism equivalence classes without coordinate dependence.
   - Stage 2 (Geometric & Spectroscopic Filter): Kabsch algorithm coordinate superposition ($\mathrm{RMSD} < 0.08\text{ \AA}$) combined with principal rotational constant matching ($|\Delta B_i / B_i| \le 0.05\%$).
5. Numerical Precision & Model Hessians:
   - Mandatory line-1 initialization of 64-bit precision: `jax.config.update("jax_enable_x64", True)`.
   - Model Hessians (`InHess XTB2` or `Lindh`) mandated; `Calc_Hess true` is strictly prohibited.

================================================================================
STRUCTURED L3 BREAKDOWN SPECIFICATION (THE 5 PHASES)
================================================================================
You must structure the L3 Work Breakdown Structure across the five canonical project lifecycle phases, ensuring 100% MECE (Mutually Exclusive, Collectively Exhaustive) coverage:

1. Phase 1: Pre-Flight (Ingestion & Environment Verification)
   - 1.1 Specification Ingestion & Boundary Audit: Verification of VR-01 requirements, input formats (.xyz, .mol, .sdf, .pdb), and interface contracts.
   - 1.2 Environment & Toolchain Readiness Check: Verification of Python 3.11+, `mendeleev`, JAX x64, Open Babel / RDKit bindings, and OS compiler toolchains.

2. Phase 2: Scope Decomposition (MECE Technical Microtask Atomization)
   - 1.3 Dynamic Mendeleev Mass Module Specification (VR-01.1).
   - 1.4 Center-of-Mass & Eckart Translation Zeroing Engine Specification (VR-01.2).
   - 1.5 Proper Rotation Locking in SO(3) & Orientation Engine Specification (VR-01.3).
   - 1.6 Two-Stage Conformer Deduplication Pipeline (WL Graph Invariant + Kabsch/Rotational Filter) Specification (VR-01.4).
   - 1.7 Scientific Constraint & Method Matrix Mapping: Explicit alignment with spend priorities (§3.3), frozen-monomer alignments, and dispersion corrections.

3. Phase 3: Risk & Governance
   - 1.8 Single-Accountable RACI & Swarm Resource Allocation: Mapping every single microtask to exactly ONE execution agent (e.g., cochem-coder, cochem-tester, researcher, cochem-audit, adversary). Dual/shared ownership is prohibited.
   - 1.9 Multi-Environment Risk Register: Formal 6-tier runtime environment risk matrix (Windows Win32 Job Objects / path separators, Linux POSIX, macOS ARM64, Codespaces, GitHub Actions CI, HPC SLURM/Lustre) with concrete mitigations (Avoid, Escalate, Transfer, Mitigate, Accept).

4. Phase 4: Artifact Assembly (Documentation & Verification Architecture)
   - 1.10 Headless Pytest & Physics Verification Test Harness Specification: Designing real molecular fixtures (water dimer, benzene, alanine dipeptide) and forbidding synthetic mocks.
   - 1.11 Technical Markdown WBS Artifact Assembly: Authoring GFM-compliant document with YAML frontmatter, execution Mermaid flowchart, granular L3 task tables, and provenance tags (`[M]`, `[D]`, `[GOV]`, `[PROC]`, `[DOC]`).

5. Phase 5: Adversarial Audit & Persistence
   - 1.12 Static Anti-Spoofing & Authenticity Audit Sweep: Static verification ensuring zero stub logic, no `NotImplementedError`, no empty `pass` blocks, and no synthetic arrays (`np.zeros`, `np.ones`).
   - 1.13 Atomic Filesystem Persistence & Cryptographic Hashing: Persisting files atomically to disk and computing SHA-256 digests.
   - 1.14 Asymmetric Adversarial Audit & Swarm Ledger Synchronization: Submitting the deliverable for independent verification by `cochem-audit` / `adversary` and recording state in `swarm_state.json`.

================================================================================
MANDATORY OPERATIONAL RULE 2: WRITE FINAL CODE/RESULTS TO DISK
================================================================================
You MUST use your file authoring tool (`write_to_file`) to persist your complete, unabridged, professional WBS document directly to disk at:
- Primary Target: `C:/Users/ansac/.gemini/antigravity-cli/scratch/task1_level2_wbs_breakdown.md`
- Mirror Target (if artifact directory is active): `task1_level2_wbs_breakdown.md` in the active artifact directory.

Do NOT simply output the WBS text in chat conversation without writing it to disk. The document must physically reside on the filesystem.

================================================================================
MANDATORY OPERATIONAL RULE 3: RETURN TEXT REPORT WITH MODIFIED PATHS
================================================================================
After completing tool execution and disk persistence, you MUST return a final structured text report in chat.
Your response MUST begin with the tag `[SDPM REPORT]` and MUST conclude with a dedicated `[VERIFICATION & HANDOFF SUMMARY]` section that details:
1. Exact Absolute and Relative File Paths created or modified on disk.
2. SHA-256 cryptographic checksum of each modified file.
3. Total number of L3 work packages decomposed.
4. Summary table of single-agent RACI assignments across the 5 phases.
5. Asymmetric Verification Gate: Explicit call to hand off the generated file to `cochem-audit` or `adversary` for independent red-team verification.

================================================================================
ANTI-SPOOFING & ZERO-MOCK INVARIANTS (ANTI-SPOOFING PROTOCOL v4)
================================================================================
- Strictly eradicate mocks, stubs, dummy loops, and fake data structures.
- Do NOT use `NotImplementedError` or empty `pass` blocks.
- Do NOT use synthetic array generators (`np.zeros`, `np.ones`, `np.eye`) to fake state tensors or coordinate matrices.
- Do NOT take shortcuts such as appending `[AUDITOR FIX REQUIRED]` tags; write complete, production-grade architectural specifications.
```
