"""Actual process probes distinguish total CPU allocation from per-rank threads."""
import json
import sys

import pytest

from topos.models import ResourceLimits
from topos.runtime import available_cpu_count, run_process


def test_mpi_style_allocation_preserves_single_threaded_child_environment(tmp_path):
    total = min(2, available_cpu_count())
    resource = ResourceLimits(threads=total, memory_mb=256, budget_seconds=10)
    command = [sys.executable, "-c", "import json,os; print(json.dumps({k:os.environ[k] for k in ('OMP_NUM_THREADS','OMP_THREAD_LIMIT','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS')}))"]
    result = run_process(command, tmp_path, resource, threads_per_process=1)
    assert result.status == "completed"
    assert resource.threads == total
    assert set(json.loads((tmp_path / "engine.stdout").read_text()).values()) == {"1"}


@pytest.mark.parametrize("per_process", [0, -1, 3, True, 1.5])
def test_invalid_per_process_thread_counts_reject_before_launch(tmp_path, per_process):
    with pytest.raises(ValueError, match="per-process"):
        run_process([sys.executable, "-c", "raise SystemExit('must not run')"], tmp_path,
                    ResourceLimits(threads=min(2, available_cpu_count())), threads_per_process=per_process)
    assert not (tmp_path / "engine.stdout").exists()
