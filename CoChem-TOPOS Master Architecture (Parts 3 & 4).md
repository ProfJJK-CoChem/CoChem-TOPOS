# **CoChem-TOPOS 3.0 Master Architecture**

## **Parts 3 & 4: Method Matrix Cascade, Persistence, and FAIR Export**

**Project Intent**

To securely escalate the deduplicated topographic basins through a mathematically rigorous, multi-tier execution ladder (The Method Matrix). This phase bridges fast Machine Learning potentials with high-fidelity Wavefunction theory (e.g., DLPNO-CCSD(T)), actively trapping correlation breakdowns and Basis Set Superposition Errors (BSSE). Finalized data must be serialized in a concurrent-safe format and automatically packaged into journal-ready supplementary documents.

### **PART 3: The Method Matrix Cascade & SWMR Persistence**

This phase replaces legacy linear optimizations with a dynamic, self-governing escalator. It relies on Inter-Process Communication (IPC) via the SubprocessBroker to enforce RAM/VRAM boundaries while writing heavily compressed tensor data to the master filesystem in real-time.

#### **Module Map (Stage 4\)**

* **Stage 4.0.1: Method Matrix Rules Engine (cochem\_topos\_cascade\_matrix.py)**  
  * **Responsibility:** The deterministic logic dictionary for execution parameters.  
  * **Mechanics:** \* *BSSE Trap:* Auto-detects if the input is an intermolecular complex (from Stage 3.5). Injects %geom Counterpoise blocks *unless* a self-correcting composite method (e.g., r2SCAN-3c or aug-cc-pVQZ) is active.  
    * *Multireference Trap:* Monitors ORCA T1 and D1 diagnostics. If ![][image1] or ![][image2], the assumption of a single-reference closed-shell ground state is invalid. The rules engine triggers an escalate\_to\_multireference flag, halting single-reference correlation to prevent unphysical energies.  
* **Stage 4.0.2: Cascade Orchestrator & IPC Handoff (cochem\_topos\_cascade\_orchestrator.py)**  
  * **Responsibility:** Maps each unique conformer through the execution tiers (e.g., TIER\_1\_SCREEN ![][image3] TIER\_2\_VDW ![][image3] TIER\_3\_BULK ![][image3] TIER\_4\_EQ\_TARGET).  
  * **Mechanics:** Packages execution payloads (method, basis, geometry) into dictionaries and dispatches them to CoChem-CORE's SubprocessBroker. Implements *Graceful Degradation*: if Tier 4 (DLPNO-CCSD(T)) OOM-crashes, it marks the state as REDUCED\_FIDELITY, preserves the Tier 3 geometry, and continues the pipeline rather than triggering a fatal system halt.  
* **Stage 4.0.3: HDF5 SWMR Persistence Layer (cochem\_cascade\_hdf5.py)**  
  * **Responsibility:** Manages high-performance, concurrent-safe data serialization.  
  * **Mechanics:** Initializes landscape.h5 with libver='latest' and swmr\_mode=True. Serializes massive analytical Hessians and Gradient matrices using lzf compression and chunking. Forces an immediate OS-level .flush() after every tensor commit, explicitly breaking POSIX file-locks so that downstream modules (like CoChem-DOCK visualizers or CoChem-TORQ) can read the data instantly.  
* **Stage 4.1: Pipeline Master Integrator (cochem\_topos\_master.py)**  
  * **Responsibility:** The overarching state machine. Glues the Crusher loop (Stage 2\) to the Cascade (Stage 4\) by doing a read-only sweep of the generated topological basins and pushing them into the Orchestrator queue.

#### **Data Flow (Part 3\)**

Crusher Deduplicated Isomers ![][image3] Read-Only HDF5 Sweep ![][image3] Method Matrix Parameter Negotiation ![][image3] Subprocess Broker Dispatch ![][image3] Multireference/BSSE Validation ![][image3] LZF Compressed Tensor Array ![][image3] SWMR HDF5 Flush (landscape.h5).

#### **Scientific and Technical Risks**

* **Risk:** Concurrent HDF5 writes/reads across networked drives (SMB/NFS) can bypass swmr protections, corrupting the 50GB master database.  
* **Mitigation:** The deployment architecture strictly air-gaps landscape.h5 into $HOME/CoChem\_Artifacts/, mandating a local NVMe or highly-compliant block storage volume.

### **PART 4: Post-Flight Audit & FAIR Export**

This phase guarantees that all computational effort translates directly into human-readable, cryptographically verifiable, publication-ready output.

#### **Module Map (Stage 5\)**

* **Stage 5.0: Post-Flight Audit & FAIR Export (cochem\_topos\_export.py)**  
  * **Responsibility:** Safely extracts the finalized datasets and translates them into Academic Standard formats without invoking heavy dependencies like pandas.  
  * **Mechanics:**  
    * *LaTeX Compilation:* Uses Python string injection to generate a siunitx-formatted TOPOS\_Supporting\_Information.tex. Extracts the highest successfully completed Tier's energy and maps the final Cartesian .xyz block into verbatim environments.  
    * *FAIR Archiving:* Embeds a fair\_manifest.json containing the metadata (archive type, pipeline version, database source) and bundles it alongside the .h5 and .tex files into a singular TOPOS\_FAIR\_Archive.zip using zipfile.ZIP\_DEFLATED compression.

#### **Data Flow (Part 4\)**

Finalized landscape.h5 ![][image3] SWMR Read Extraction ![][image3] LaTeX String Assembly ![][image3] JSON Manifest Generation ![][image3] zipfile Deflation ![][image3] Zenodo-Compliant .zip Archive.

#### **Validation Plan**

* **Read-Lock Integrity Check:** While the Cascade is actively flushing a long-running DLPNO-CCSD(T) optimization to landscape.h5, run the cochem\_topos\_export.py script. It must successfully extract the Tier 3 geometry without throwing an OS-level file lock error, proving SWMR efficacy.  
* **Siunitx Precision Test:** Compile the generated .tex file using pdflatex. Verify that the ![][image4] column alignment perfectly aligns the decimals of the extracted Hartree energies regardless of their leading integer counts.

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAFkAAAAaCAYAAADcx/BtAAADe0lEQVR4Xu2Xz0tUURTHJzIo+k3JpM54Z4ahoUW1mH4gtJIWbVrVIiha1KL+goRyG7QW2kQQEiFECC2EghZDmyAXrSSwBA0jEEoSDCy0vl89V8+c3nvzRiWF7gcOM/d7zr33vDN37rs3kwkEAoHApsI5V4T9Tmu2P+ns7HwOX5vV/zFbkEO3yvU9NRsURblc3oP4PtW3z8YQE/MR0lYbEwmCB2AXjLY4UEdHR07JLdB++EahUOiXuHn53NAiSx5zvl0sFk8xLx0TRWtr6y7G4Xmeeg3tB2i/1XFov87lcmUVM81+1Wp1m46LBIGT+GhREovJonHi7Upn7Bf1/TpW8EX+EBtd5FKptFdyGNA6tfb29rzWLHjGS4ibg3V5Dc9VYl8dh/ZCRq1cxPRIjc6psEhaEPxCC/l8/qQkzEE1LP4zo3HyNolPXWTMcUISPG19q8HJ3xjPct7os1E5a+D/CqtxRRud453h90qlstvWhAtQtDH8a7IrPQ1wVmxxmJR0HtI6Bt0HrVtrhP0lPnWRPZj/GPtyNVlfM2CMSdgsilI1+gRsRmsWmb8/Soc9VO3PsDsqhO8AxnCO5p4dHX7BFpDwWeuLghPIZM1NpHBLL1/uqb18CVl/IyTnuCIn7cuLW2NCkWtW98DXJX1vWl8j/H48ZPfjONw6FNkjb/leGa9o/XFIfNNFVi+9uCJPWN0D3zzmG7V6Q7gHcfC0q5iwuJLQmouswXjXOC5eaoetzyLzN13kbDa7k/6EItesTqA/ho1ZPRVO9uO0q5iwuOxjH3At4Ki0A2NOwQatLwq39PKKK/LysTOKBkV+YnXMcQv20uqpwaDjHNzqSax3kWV1fcd4j6wvDsSPsJg8GRl9xqljZxSqmHUXF9Hvak30eebo28jzHg8FOiYRGXjc6km4dSoyxrjPQsF6ra8ReMgbkvtlrYtWd3vDuf6AbrulH2gY+e/3mt9GYEdM7Ddz+fDHWn3PiMetXK9vW18S/jKy2iKj7yBsiluE9TWBP0598AKLSU0Xxb9zYCNe4y1O8u9RcVecuj2KNip964w/sI6LxHYyVvdLapgUY/D5yZu0l5NNgEV5A3uXSXv/bwAe9hDGewWb5h7LXPBZMGGc9ycvQ1pEzlepw4ZhNX7PqLxwazwo9fjLcNY/robaPGD1HLVaIBAIBAKBQCAQ+H/4A/zBTP3fWvdlAAAAAElFTkSuQmCC>

[image2]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAFwAAAAaCAYAAAA67jspAAADsElEQVR4Xu1YPWgUQRS+wwjBv8bEM5e7TO5yGNTC4hARtBEshKggCBZiYSNYKGghiI2IhWAVCIgExMJCsRUkWBwEjMRWSaEWEaIgiARMQEKI33f35vLy2N3c7YkRmQ8ee/u9N2/efDszO3uZTEBAQEDAf4FyubzHOfcJtkIbGBj4rM3zuVxuq23rgbh9iKlZfgOQRR0zvmbYMRsQh0qlsgPxy9Jumfc2BvwS7C6sr1QqOYz7AX6/StImFpLsu+UJJmUh+Nnlud7e3m1SnLfaaou/j2KxeIpC4XrUc7j/AVHO67goDA4OTnAM1Wp1M+955X1/f/9OHWfGu4J209rfFiTJW8sThUKhIv7DnkNn3bDbGGAe/ILbYMHR/xvWmFGTwjVm4wcVFgkZ2y/DfcXDumE4xnmbArVJ+1sGlkdOkpyxPg/xTw4PD2+P8LUluMygediY9aWFF0JzEKwqXPMhWMC/V9rWNI/J9BjckuZs/tRA8ktMFiWmhxS1wEFE+NoS3EOEn+WSxm3W+lsFln7B16d53PeRx4Q6oHkN+G8yhgJrnrPbCmzzpwYSvbfJDbpkQLMchHWyEJdCcIVN3A9l4Ketcz1AnCNSX6Tg8J/UvAb8z6XfSMH5rlKxHOdH13inzfG3btMypNhJy3v4pQkbtz5CCqlZPg0wG4fZF/q8an1xoKBSX5zga/ZiDdbNmDjBmUPFMn9zJbrGiWiGK8xz6yKfz/dI4qT9+wVjuNdbH8FCWLjlOwEHCluGEPeszwJxJ2QMcYInzfD6CSxOcD3DLdRDiTxsRALB19goYf/m2ZZJ31mHBwcKm7V8J0C+Mdhi1HnYwq2++CIFx0nqoOY14B9lTJzgmdUZzW3vXFSM7TcRTvYwy3sg6X76cT1ufR7s0P1BwdHXI+Sbb/WDQq3SRc3zZSm1lzWv4Q8MsCeax/241gW/r/N+aGhol+fSCh77weM/AGD3rU+DHboOBcfADyHHFGzGf4C0A6nTnirqW43mgKzeJtTDWrMtuMZW09SFK4BxWnAnqwPCv/RcIpCkWzobtT5wtyTZiPVZIG7RpRScpxL2Q8EzHRwNkeMO80DAoueQcxr2zMRxgjGuR3FfyJk4bkXNr1bm5cozMXzHTCTt83Wg8RYROs5+IvlZ285Cxfr/Xer/RSS9pDwQd1Hal6wvLTD43cyJ61Ncv8Fe2xhwl2Fzhs6i5gtSz0MZwxUTwy1kRHz1/5jsw/xnwS2jlZdhQEBAQEBAQEBAQEBAWvwGps1l2zcX2E8AAAAASUVORK5CYII=>

[image3]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABUAAAAYCAYAAAAVibZIAAAAg0lEQVR4XmNgGAWjYOCBvLz8AVFRUR50cYoA0NATcnJyE9DFKQIyMjKcQIM3q6ioiKLLUQyArr2lqKiohy4OBkBbLwLxfwrwanQzyQZAl+YDDVyHLk42UFBQyAAaGIwuTjYAGjYHaOgpdHGKANDQB8AUII0uTglgBBqqiS44CkYBDQEAkyklZx3WO6cAAAAASUVORK5CYII=>

[image4]: <data:image/png;base64,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>