"""CoChem-TOPOS: Topological Discovery, Conformational Search, and Deduplication Engine."""

__version__ = "0.1.0"
__author__ = "CoChem Swarm / Dr. Joshua John Klaassen"

from topos.calculation.xtb_runner import XTBCalculationResult, execute_gfn2_xtb
from topos.actions.dispatch import ActionDispatchClient, DispatchResult

__all__ = [
    "XTBCalculationResult",
    "execute_gfn2_xtb",
    "ActionDispatchClient",
    "DispatchResult",
]
