"""CFOUR workspace allocation within the unchanged total process memory limit."""
from __future__ import annotations

from .models import ResourceLimits


def cfour_memory_plan(resources: ResourceLimits) -> dict[str, int | str]:
    """Reserve native static data and BLAS scratch before assigning CFOUR core.

    The verified CFOUR 2.1 xvdint has 444,508,040 bytes of static BSS. Its
    bundled OpenBLAS requests a 128 MiB scratch buffer separately from CFOUR's
    MEMORY_SIZE. Reserving 768 MiB for one thread, plus 128 MiB per additional
    thread, includes libraries, stacks and allocator margin. BASE still enforces
    the original total address-space/RSS limit, thread count and deadline.
    """
    resources = ResourceLimits.model_validate(resources.model_dump())
    total = resources.memory_mb * 1024**2
    reserve = (768 + 128 * (resources.threads - 1)) * 1024**2
    native = min(total * 3 // 4, total - reserve)
    if native <= 0:
        raise ValueError("CFOUR memory limit cannot accommodate native static/BLAS headroom; increase memory or reduce threads")
    words = native // 8
    return {"profile": "cfour-static-blas-headroom-v1", "total_limit_bytes": total,
            "reserved_headroom_bytes": reserve, "native_workspace_bytes": words * 8,
            "native_integer_words": words, "allocated_threads": resources.threads}
