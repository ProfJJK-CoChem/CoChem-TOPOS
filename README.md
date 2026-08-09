# CoChem-TOPOS

**CoChem-TOPOS** is the Combinatorial Conformational Engine of the CoChem suite.

It is responsible for:
- Executing the stochastic Global Optimization Algorithm (GOAT) to generate massive monomer conformer populations.
- Interactive HTML 3D Triage for user-driven *Enantiomer* and *Duplicate* classification.
- Generating extreme combinatorial strong and weak complexes, utilizing `MACE-OFF24m` Active Learning to rapidly discard repulsive clashes in milliseconds.
- Enforcing spatial hashing cutoffs to protect GPU memory from the combinatorial explosion.
- Calculating NCI interaction energies to automatically append the `LAM_TRIGGER_REQUIRED` flag to the shared `cochem_state.h5` tensor, dictating downstream physics.

## Usage
Please refer to the authoritative [CoChem Master User Manual](../CoChem-BASE/CoChem_Master_User_Manual.md) for full execution instructions across the entire 5-module pipeline.