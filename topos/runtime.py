"""Bounded local subprocess execution with owned process-group cancellation.

Only the POSIX local execution adapter is implemented. Engine output is streamed
unchanged to files. Memory is bounded by a per-process address-space hard limit
and a conservative aggregate RSS watchdog for the process group.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import ResourceLimits


@dataclass(frozen=True)
class ProcessResult:
    command: list[str]
    status: str
    returncode: int | None
    elapsed_seconds: float
    peak_rss_mb: float
    stdout_path: str
    stderr_path: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def available_cpu_count() -> int:
    return len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)


def _group_rss_bytes(pgid: int) -> int:
    """Linux /proc process-group RSS; shared pages may be counted more than once."""
    total = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            # Parentheses may contain whitespace: split after final closing paren.
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) != pgid:
                continue
            for line in (entry / "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1]) * 1024
                    break
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, IndexError):
            continue
    return total


def _terminate_group(process: subprocess.Popen[bytes], grace_seconds: float = 0.5) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    # Descendants may survive after their parent exits. Kill only this owned group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_process(
    command: list[str],
    workdir: str | Path,
    resources: ResourceLimits,
    *,
    cancel_event: Event | None = None,
    log_prefix: str = "engine",
    environment: dict[str, str] | None = None,
    output_limit_mb: int = 256,
    threads_per_process: int | None = None,
) -> ProcessResult:
    """Execute argv without a shell; no global process killing or output synthesis."""
    if os.name != "posix" or not Path("/proc").is_dir():
        raise ValueError("bounded local engine execution currently requires Linux/POSIX")
    if not command or any(not isinstance(arg, str) or "\x00" in arg for arg in command):
        raise ValueError("command must contain non-NUL string arguments")
    if resources.device != "cpu":
        raise ValueError("this local subprocess adapter supports CPU execution only")
    if resources.threads > available_cpu_count():
        raise ValueError("requested threads exceed available CPU affinity")
    native_threads = resources.threads if threads_per_process is None else threads_per_process
    if isinstance(native_threads, bool) or not isinstance(native_threads, int) or not 1 <= native_threads <= resources.threads:
        raise ValueError("per-process threads must fit within the total CPU allocation")
    if Path(log_prefix).name != log_prefix or not log_prefix:
        raise ValueError("log prefix must be a basename")
    folder = Path(workdir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    stdout_path = folder / f"{log_prefix}.stdout"
    stderr_path = folder / f"{log_prefix}.stderr"
    if stdout_path.exists() or stderr_path.exists():
        raise FileExistsError("raw logs already exist; use a new attempt directory")
    env = os.environ.copy()
    env.update(environment or {})
    env.update({
        "OMP_NUM_THREADS": str(native_threads),
        "OMP_THREAD_LIMIT": str(native_threads),
        "OMP_DYNAMIC": "FALSE",
        "OPENBLAS_NUM_THREADS": str(native_threads),
        "MKL_NUM_THREADS": str(native_threads),
        "NUMEXPR_NUM_THREADS": str(native_threads),
        "VECLIB_MAXIMUM_THREADS": str(native_threads),
        "OMP_STACKSIZE": "16M",
    })
    # A separate launcher sets rlimits safely (preexec_fn deadlocks with threads).
    launcher = [sys.executable, str(Path(__file__).resolve()), "--limit-exec",
                str(resources.memory_mb), str(output_limit_mb), *command]
    start = time.monotonic()
    status, reason, peak = "completed", None, 0
    returncode = None
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        if cancel_event is not None and cancel_event.is_set():
            return ProcessResult(command, "cancelled", None, 0.0, 0.0,
                                 str(stdout_path), str(stderr_path), "cancelled before launch")
        try:
            process = subprocess.Popen(launcher, cwd=folder, env=env,
                                       stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       start_new_session=True)
        except OSError as exc:
            return ProcessResult(command, "failed", None, time.monotonic() - start, 0.0,
                                 str(stdout_path), str(stderr_path), f"launch failed: {exc}")
        try:
            while process.poll() is None:
                peak = max(peak, _group_rss_bytes(process.pid))
                if cancel_event is not None and cancel_event.is_set():
                    status, reason = "cancelled", "cancellation requested"
                elif time.monotonic() - start >= resources.budget_seconds:
                    status, reason = "timed-out", "attempt wall-clock budget exhausted"
                elif peak > resources.memory_mb * 1024**2:
                    status, reason = "failed", "aggregate process-group memory limit exceeded"
                else:
                    time.sleep(0.02)
                    continue
                _terminate_group(process)
                break
            returncode = process.wait()
            if returncode != 0 and status == "completed":
                status, reason = "failed", f"engine process exited with code {returncode}"
        finally:
            _terminate_group(process)
    return ProcessResult(command, status, returncode, time.monotonic() - start,
                         peak / 1024**2, str(stdout_path), str(stderr_path), reason)


def _limit_exec() -> None:
    """Private child entry point. Never accepts shell source."""
    import resource

    memory = int(sys.argv[2]) * 1024**2
    file_size = int(sys.argv[3]) * 1024**2
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_size, file_size))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.execvpe(sys.argv[4], sys.argv[4:], os.environ)


if __name__ == "__main__":
    # Script execution needs no package import; see guarded import above.
    if len(sys.argv) < 5 or sys.argv[1] != "--limit-exec":
        raise SystemExit("private engine launcher: invalid arguments")
    _limit_exec()
