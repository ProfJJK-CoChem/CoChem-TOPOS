"""Real subprocess ownership and descendant-quiescence regressions."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from threading import Event, Timer

import pytest

from topos.models import ResourceLimits
from topos.runtime import run_process

# This child explicitly ignores SIGTERM and stays runnable. Its parent prints
# readiness only after the child installed the handler, so both escalation and
# complete group cleanup are tested rather than incidental process startup.
CHILD = "import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print(os.getpid(),flush=True);\nwhile True: pass"
PARENT = (
    "import json,os,subprocess,sys,time; "
    f"p=subprocess.Popen([sys.executable,'-c',{CHILD!r}],stdout=subprocess.PIPE,text=True); "
    "pid=int(p.stdout.readline()); print(json.dumps({'parent':os.getpid(),'child':pid,'pgid':os.getpgrp()}),flush=True); "
)


def assert_quiescent(pid):
    path = Path(f"/proc/{pid}/stat")
    try:
        state = path.read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return
    assert state == "Z", f"owned process {pid} is still {state} after run_process returned"


@pytest.mark.parametrize("stop", ["timeout", "cancel", "parent-exit"])
def test_term_resistant_owned_descendant_stops_before_return(tmp_path, stop):
    event = Event()
    timer = Timer(.4, event.set) if stop == "cancel" else None
    code = PARENT + ("raise SystemExit(0)" if stop == "parent-exit" else "time.sleep(30)")
    if timer:
        timer.start()
    try:
        result = run_process([sys.executable, "-c", code], tmp_path,
                             ResourceLimits(budget_seconds=.4 if stop == "timeout" else 10, memory_mb=256),
                             cancel_event=event)
    finally:
        if timer:
            timer.cancel()
    identities = json.loads(Path(result.stdout_path).read_text())
    assert identities["parent"] == identities["pgid"]
    assert result.status == {"timeout": "timed-out", "cancel": "cancelled", "parent-exit": "completed"}[stop]
    assert result.elapsed_seconds < 3
    assert_quiescent(identities["parent"])
    assert_quiescent(identities["child"])


def test_owned_cleanup_preserves_unrelated_process_group(tmp_path):
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True)
    try:
        sentinel_group = os.getpgid(sentinel.pid)
        result = run_process([sys.executable, "-c", PARENT + "time.sleep(30)"], tmp_path,
                             ResourceLimits(budget_seconds=.4, memory_mb=256))
        identities = json.loads(Path(result.stdout_path).read_text())
        assert identities["pgid"] != sentinel_group
        assert result.status == "timed-out"
        assert_quiescent(identities["child"])
        assert sentinel.poll() is None
        assert os.getpgid(sentinel.pid) == sentinel_group
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=3)
