import os
import logging
from typing import Optional

import numpy as np
from ase import Atoms
from ase.md.langevin import Langevin
from ase import units
from ase.io import Trajectory
from ase.calculators.calculator import Calculator

logger = logging.getLogger(__name__)

class MACE_EscapeMechanism:
    """
    Provides enhanced sampling and high-temperature molecular dynamics 
    to escape deep local minima during conformer exploration.
    Works with any ASE-compatible calculator, ideally MACE-OFF24m or XTB.
    """
    def __init__(self, calculator: Calculator, temperature_K: float = 800.0, friction: float = 0.01, timestep_fs: float = 1.0):
        """
        Initialize the escape mechanism.

        Args:
            calculator (Calculator): ASE-compatible calculator (e.g., MACECalculator, XTB).
            temperature_K (float): Temperature in Kelvin for the MD run.
            friction (float): Friction coefficient for Langevin dynamics.
            timestep_fs (float): Time step in femtoseconds.
        """
        self.calculator = calculator
        self.temperature_K = temperature_K
        self.friction = friction
        self.timestep_fs = timestep_fs
        
    def run_escape_dynamics(self, atoms: Atoms, steps: int = 1000, trajectory_file: Optional[str] = None) -> Atoms:
        """
        Run high-temperature Langevin dynamics to overcome energy barriers.
        
        Args:
            atoms (Atoms): The starting structure.
            steps (int): Number of MD steps to run.
            trajectory_file (Optional[str]): If provided, saves the MD trajectory to this file.
            
        Returns:
            Atoms: The final structure after the MD run.
        """
        md_atoms = atoms.copy()
        md_atoms.calc = self.calculator
        
        # Set up Langevin dynamics
        dyn = Langevin(
            md_atoms,
            timestep=self.timestep_fs * units.fs,
            temperature_K=self.temperature_K,
            friction=self.friction
        )
        
        traj = None
        if trajectory_file:
            traj = Trajectory(trajectory_file, 'w', md_atoms)
            dyn.attach(traj.write, interval=max(1, steps // 100))
            
        logger.info(f"Starting escape dynamics at {self.temperature_K} K for {steps} steps.")
        dyn.run(steps)
        logger.info("Escape dynamics completed.")
        
        if traj:
            traj.close()
            
        return md_atoms

    def run_simulated_annealing(self, atoms: Atoms, steps_per_temp: int = 500, max_temp_K: float = 1000.0, cooling_rate: float = 0.9) -> Atoms:
        """
        Run a simulated annealing sequence to escape and then relax into a new minimum.
        
        Args:
            atoms (Atoms): The starting structure.
            steps_per_temp (int): Number of steps at each temperature stage.
            max_temp_K (float): Peak temperature to reach before cooling.
            cooling_rate (float): Multiplier for temperature at each cooling step.
            
        Returns:
            Atoms: The final cooled structure.
        """
        current_atoms = atoms.copy()
        current_temp = max_temp_K
        
        # Initial heating phase
        original_temp = self.temperature_K
        self.temperature_K = current_temp
        
        while current_temp > 300.0:
            logger.info(f"Annealing stage: {current_temp:.1f} K")
            self.temperature_K = current_temp
            current_atoms = self.run_escape_dynamics(current_atoms, steps=steps_per_temp)
            current_temp *= cooling_rate
            
        self.temperature_K = original_temp # Restore original temperature
        return current_atoms