# **CoChem-TOPOS: Topological Optimization & Deduplication Engine**

## **Overview**

**CoChem-TOPOS** (Topological Optimization of Potential and Orbital Surfaces) is the primary geometry engine for the CoChem ecosystem. It is responsible for taking a raw 2D graph or crude 3D geometry and rigorously mapping its conformational landscape.

Unlike traditional pipelines that blindly run heavy DFT optimizations on thousands of conformers, TOPOS utilizes a **"Jiggle-Quench"** protocol driven by Machine Learning Force Fields (MACE-OFF23). It rapidly generates ensembles, quenches them to local minima using GPU-accelerated ML potentials, and deduplicates them using strict NetworkX graph hashing.

## **Scientific & Technical Trade-offs**

* **Graph Hashing over RMSD:** Traditional RMSD deduplication fails on highly flexible molecules. TOPOS relies on NetworkX connectivity hashing (detecting if bonds were broken during the quench) combined with Coulomb Matrix Eigenspectrum variance. This mathematically guarantees we don't calculate the same physical basin twice, though it costs slightly more CPU time upfront.  
* **The Fallback Cascade:** Not all elements are supported by MACE-OFF23. If TOPOS detects an exotic transition metal or iodine, it automatically bypasses the PyTorch/MACE silo and "fails down" to g-xTB (semi-empirical). This trades absolute ML speed for guaranteed chemical stability without crashing the pipeline.

## **Installation & Setup**

CoChem-TOPOS requires the cochem\_system\_config.json registry to know if it can use your GPU.

git clone \[https://github.com/CoChem/CoChem-TOPOS.git\](https://github.com/CoChem/CoChem-TOPOS.git)  
cd CoChem-TOPOS

## **How to Run**

TOPOS operates in distinct phases. It is recommended to run these via the master Jupyter Notebook, but they can be executed via CLI:

1. **The Sieve (Initial Generation & Triage):**  
   python cochem\_crusher.py \--input my\_molecule.xyz \--mode sieve  
   *(Generates crude 3D geometries and identifies Weak vs. Strong complexes).*  
2. **The Jiggle-Quench (GPU Accelerated Optimization):**  
   python cochem\_jiggle\_quench.py  
   *(Uses MACE-OFF23 to optimize 10,000+ conformers in minutes, writing to landscape.h5).*  
3. **Ab Initio Escalation:**  
   python cochem\_escalator.py  
   *(Takes the unique minimums and routes them to ORCA 6.1.1 for high-accuracy DFT refinement).*

## **Output**

All data is serialized into landscape.h5, preventing thousands of loose .xyz and .out files from clogging your filesystem.