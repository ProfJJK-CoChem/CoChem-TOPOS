## **4\. ADVANCED PHYSICS: THE MULTIREFERENCE TRAP**

### **4.1 The Single-Reference Assumption**

The vast majority of automated quantum chemistry tools (including Standard DFT and standard Coupled Cluster) assume that your molecule's ground state can be reasonably described by a single dominant electron configuration (the Hartree-Fock determinant).

For many systems—like stable organic molecules—this is a perfectly valid assumption. However, for transition states, stretched bonds, diradicals, or highly conjugated polyaromatics, this assumption breaks down. This is known as **Static Correlation** or **Multireference Character**.

### **4.2 Why it Matters**

If you blindly apply a single-reference method like DLPNO-CCSD(T) to a multireference system, the computer will not crash. It will successfully finish the calculation and give you an energy. **However, that energy will be completely wrong.**

### **4.3 The T1 and D1 Diagnostics**

To prevent this "silent failure," the CoChem-Cascade Orchestrator actively intercepts the log files and parses two critical metrics:

* **The T1 Diagnostic:** Measures the norm of the single-excitation amplitudes in Coupled Cluster.  
* **The D1 Diagnostic:** A more sensitive measure of the variance in the density matrix.

**CoChem's Hard Constraints:**

If the Orchestrator detects ![][image1] or ![][image2] (for closed-shell systems), it triggers the **Multireference Trap**.

* The script actively blocks further single-reference escalation.  
* The isomer is tagged CRITICAL: Multireference Character Detected.  
* You must manually inspect this geometry and utilize an active-space method (like CASSCF or NEVPT2) outside the standard automated pipeline.

## **5\. DOWNSTREAM EXTRACTION & TROUBLESHOOTING**

### **5.1 SWMR HDF5 Data Access**

The entirety of the CoChem pipeline writes to a Single-Writer/Multiple-Reader (SWMR) database located at $HOME/CoChem\_Artifacts/landscape.h5.

Because it uses SWMR, you can safely read this database using your own custom Jupyter notebooks *while* CoChem is actively optimizing other molecules in the background.

**Example Python Extraction Script:**

import h5py

\# MUST include libver='latest' and swmr=True to prevent file-lock collisions  
with h5py.File('/home/user/CoChem\_Artifacts/landscape.h5', 'r', libver='latest', swmr=True) as f:  
    isomer\_group \= f\["deduplicated\_isomers/isomer\_001/TIER\_4\_EQ\_TARGET"\]  
      
    \# Read scalars via attributes (fast)  
    final\_energy \= isomer\_group.attrs\["electronic\_energy\_hartree"\]  
      
    \# Read compressed tensor matrices (requires numpy)  
    hessian\_matrix \= isomer\_group\["hessian\_matrix"\]\[:\]  
    print(f"Final CCSD(T) Energy: {final\_energy}")

### **5.2 Advanced Troubleshooting**

#### **5.2.1 Issue: "HDF5-DIAG: Unable to lock file"**

* **Symptom:** Your custom script or the CoChem-DOCK UI crashes immediately upon trying to read landscape.h5.  
* **Cause:** You opened the file without the swmr=True flag, or you are running the pipeline on a network-attached drive (like a Windows SMB share) that does not fully support POSIX file-locking.  
* **Resolution:** Ensure landscape.h5 is located on a local NVMe/SSD drive. Always pass swmr=True in your reader scripts.

#### **5.2.2 Issue: "Reduced Fidelity" tag on all TIER 4 jobs**

* **Symptom:** Your geometries successfully process through wB97X-D4, but none of them complete the DLPNO-CCSD(T) step.  
* **Cause:** The SubprocessBroker is OOM-killing the ORCA engine. Coupled Cluster methods require immense amounts of RAM (often \> 4GB per core).  
* **Resolution:** Open $HOME/CoChem\_Artifacts/cochem\_system\_config.json and decrease \\"max\_parallel\_workers\\". Dedicate more RAM to fewer simultaneous jobs.

#### **5.2.3 Issue: The "Jiggle-Quench" erased my transition state**

* **Symptom:** You manually ingested a known transition state, but The Crusher deleted it.  
* **Cause:** The standard xTB or MACE optimizers default to finding local minima. A transition state is a saddle point (forces are zero, but one vibrational mode is imaginary). When the Jiggle-Quench perturbed the geometry, the optimizer simply pushed it downhill into the nearest standard basin.  
* **Resolution:** Transition states must be routed through the CoChem-KINETIC module, not the standard CoChem-TOPOS discovery engine.

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAFkAAAAaCAYAAADcx/BtAAADe0lEQVR4Xu2Xz0tUURTHJzIo+k3JpM54Z4ahoUW1mH4gtJIWbVrVIiha1KL+goRyG7QW2kQQEiFECC2EghZDmyAXrSSwBA0jEEoSDCy0vl89V8+c3nvzRiWF7gcOM/d7zr33vDN37rs3kwkEAoHApsI5V4T9Tmu2P+ns7HwOX5vV/zFbkEO3yvU9NRsURblc3oP4PtW3z8YQE/MR0lYbEwmCB2AXjLY4UEdHR07JLdB++EahUOiXuHn53NAiSx5zvl0sFk8xLx0TRWtr6y7G4Xmeeg3tB2i/1XFov87lcmUVM81+1Wp1m46LBIGT+GhREovJonHi7Upn7Bf1/TpW8EX+EBtd5FKptFdyGNA6tfb29rzWLHjGS4ibg3V5Dc9VYl8dh/ZCRq1cxPRIjc6psEhaEPxCC/l8/qQkzEE1LP4zo3HyNolPXWTMcUISPG19q8HJ3xjPct7os1E5a+D/CqtxRRud453h90qlstvWhAtQtDH8a7IrPQ1wVmxxmJR0HtI6Bt0HrVtrhP0lPnWRPZj/GPtyNVlfM2CMSdgsilI1+gRsRmsWmb8/Soc9VO3PsDsqhO8AxnCO5p4dHX7BFpDwWeuLghPIZM1NpHBLL1/uqb18CVl/IyTnuCIn7cuLW2NCkWtW98DXJX1vWl8j/H48ZPfjONw6FNkjb/leGa9o/XFIfNNFVi+9uCJPWN0D3zzmG7V6Q7gHcfC0q5iwuJLQmouswXjXOC5eaoetzyLzN13kbDa7k/6EItesTqA/ho1ZPRVO9uO0q5iwuOxjH3At4Ki0A2NOwQatLwq39PKKK/LysTOKBkV+YnXMcQv20uqpwaDjHNzqSax3kWV1fcd4j6wvDsSPsJg8GRl9xqljZxSqmHUXF9Hvak30eebo28jzHg8FOiYRGXjc6km4dSoyxrjPQsF6ra8ReMgbkvtlrYtWd3vDuf6AbrulH2gY+e/3mt9GYEdM7Ddz+fDHWn3PiMetXK9vW18S/jKy2iKj7yBsiluE9TWBP0598AKLSU0Xxb9zYCNe4y1O8u9RcVecuj2KNip964w/sI6LxHYyVvdLapgUY/D5yZu0l5NNgEV5A3uXSXv/bwAe9hDGewWb5h7LXPBZMGGc9ycvQ1pEzlepw4ZhNX7PqLxwazwo9fjLcNY/robaPGD1HLVaIBAIBAKBQCAQ+H/4A/zBTP3fWvdlAAAAAElFTkSuQmCC>

[image2]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAFwAAAAaCAYAAAA67jspAAADsElEQVR4Xu1YPWgUQRS+wwjBv8bEM5e7TO5yGNTC4hARtBEshKggCBZiYSNYKGghiI2IhWAVCIgExMJCsRUkWBwEjMRWSaEWEaIgiARMQEKI33f35vLy2N3c7YkRmQ8ee/u9N2/efDszO3uZTEBAQEDAf4FyubzHOfcJtkIbGBj4rM3zuVxuq23rgbh9iKlZfgOQRR0zvmbYMRsQh0qlsgPxy9Jumfc2BvwS7C6sr1QqOYz7AX6/StImFpLsu+UJJmUh+Nnlud7e3m1SnLfaaou/j2KxeIpC4XrUc7j/AVHO67goDA4OTnAM1Wp1M+955X1/f/9OHWfGu4J209rfFiTJW8sThUKhIv7DnkNn3bDbGGAe/ILbYMHR/xvWmFGTwjVm4wcVFgkZ2y/DfcXDumE4xnmbArVJ+1sGlkdOkpyxPg/xTw4PD2+P8LUluMygediY9aWFF0JzEKwqXPMhWMC/V9rWNI/J9BjckuZs/tRA8ktMFiWmhxS1wEFE+NoS3EOEn+WSxm3W+lsFln7B16d53PeRx4Q6oHkN+G8yhgJrnrPbCmzzpwYSvbfJDbpkQLMchHWyEJdCcIVN3A9l4Ketcz1AnCNSX6Tg8J/UvAb8z6XfSMH5rlKxHOdH13inzfG3btMypNhJy3v4pQkbtz5CCqlZPg0wG4fZF/q8an1xoKBSX5zga/ZiDdbNmDjBmUPFMn9zJbrGiWiGK8xz6yKfz/dI4qT9+wVjuNdbH8FCWLjlOwEHCluGEPeszwJxJ2QMcYInzfD6CSxOcD3DLdRDiTxsRALB19goYf/m2ZZJ31mHBwcKm7V8J0C+Mdhi1HnYwq2++CIFx0nqoOY14B9lTJzgmdUZzW3vXFSM7TcRTvYwy3sg6X76cT1ufR7s0P1BwdHXI+Sbb/WDQq3SRc3zZSm1lzWv4Q8MsCeax/241gW/r/N+aGhol+fSCh77weM/AGD3rU+DHboOBcfADyHHFGzGf4C0A6nTnirqW43mgKzeJtTDWrMtuMZW09SFK4BxWnAnqwPCv/RcIpCkWzobtT5wtyTZiPVZIG7RpRScpxL2Q8EzHRwNkeMO80DAoueQcxr2zMRxgjGuR3FfyJk4bkXNr1bm5cozMXzHTCTt83Wg8RYROs5+IvlZ285Cxfr/Xer/RSS9pDwQd1Hal6wvLTD43cyJ61Ncv8Fe2xhwl2Fzhs6i5gtSz0MZwxUTwy1kRHz1/5jsw/xnwS2jlZdhQEBAQEBAQEBAQEBAWvwGps1l2zcX2E8AAAAASUVORK5CYII=>