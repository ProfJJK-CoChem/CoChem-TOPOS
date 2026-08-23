"""
CoChem-TOPOS: Mechanics Subsystem
Provides hardware brokering, HDF5 SWMR state management, universal fallback cascade,
precision downgrade protocol, and lightning PES quench relaxation.
"""

from .cochem_topos_memory import (
    CascadeState,
    DeviceType,
    EngineTier,
    FallbackCascadeStateMachine,
    FallbackReason,
    GeometryRecord,
    GPUDeviceInfo,
    HardwareResourceBroker,
    HardwareSnapshot,
    PrecisionDowngradeProtocol,
    PrecisionMode,
    TelemetryRecord,
    ToposHDF5MemoryManager,
    TrajectoryStep,
    UniversalFallbackCascade,
)

from .cochem_topos_quench import (
    CUDAGraphOptimizerWrapper,
    CalculatorFactory,
    ParallelASEQuenchRunner,
    QuenchAlgorithm,
    QuenchBatchResult,
    QuenchConfig,
    QuenchResult,
    QuenchStatus,
    SoftQuenchGovernor,
    SoftQuenchTelemetry,
    ToposQuenchOrchestrator,
    TorchMLFFCalculator,
)

__all__ = [
    # Memory and state management
    "ToposHDF5MemoryManager",
    "HardwareResourceBroker",
    "HardwareSnapshot",
    "GPUDeviceInfo",
    "UniversalFallbackCascade",
    "FallbackCascadeStateMachine",
    "EngineTier",
    "FallbackReason",
    "DeviceType",
    "PrecisionMode",
    "CascadeState",
    "PrecisionDowngradeProtocol",
    "GeometryRecord",
    "TrajectoryStep",
    "TelemetryRecord",
    # Quench and relaxation
    "CUDAGraphOptimizerWrapper",
    "CalculatorFactory",
    "ParallelASEQuenchRunner",
    "QuenchAlgorithm",
    "QuenchBatchResult",
    "QuenchConfig",
    "QuenchResult",
    "QuenchStatus",
    "SoftQuenchGovernor",
    "SoftQuenchTelemetry",
    "ToposQuenchOrchestrator",
    "TorchMLFFCalculator",
]
