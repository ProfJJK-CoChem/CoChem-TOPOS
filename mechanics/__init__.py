"""
CoChem-TOPOS: Mechanics Subsystem
Provides hardware brokering, HDF5 SWMR state management, universal fallback cascade,
and precision downgrade protocol.
"""

from .cochem_topos_memory import (
    ToposHDF5MemoryManager,
    HardwareResourceBroker,
    HardwareSnapshot,
    GPUDeviceInfo,
    UniversalFallbackCascade,
    FallbackCascadeStateMachine,
    EngineTier,
    FallbackReason,
    CascadeState,
    PrecisionDowngradeProtocol,
    GeometryRecord,
    TrajectoryStep,
    TelemetryRecord,
)

__all__ = [
    "ToposHDF5MemoryManager",
    "HardwareResourceBroker",
    "HardwareSnapshot",
    "GPUDeviceInfo",
    "UniversalFallbackCascade",
    "FallbackCascadeStateMachine",
    "EngineTier",
    "FallbackReason",
    "CascadeState",
    "PrecisionDowngradeProtocol",
    "GeometryRecord",
    "TrajectoryStep",
    "TelemetryRecord",
]
