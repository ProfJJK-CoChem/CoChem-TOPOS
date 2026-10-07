"""Control-plane regressions; the supervisor double emits no chemistry."""
from pathlib import Path

import pytest

from topos import ml_extopt
from topos.models import ResourceLimits
from topos.runtime import ProcessResult


class CompletionCollection:
    """Represent the narrow interval after native exit but before collection."""

    def __init__(self, server, native_status='completed', *, first_wait_times_out=False):
        self.server = server
        self.native_status = native_status
        self.first_wait_times_out = first_wait_times_out
        self.cancellation_at_collection = []
        self.waits = []

    def done(self):
        return False

    def result(self, timeout):
        self.waits.append(timeout)
        cancelled = self.server._cancel.is_set()
        self.cancellation_at_collection.append(cancelled)
        if self.first_wait_times_out and len(self.waits) == 1:
            raise TimeoutError('supervisor has not finished within its bound')
        return ProcessResult([], 'cancelled' if cancelled else self.native_status,
            0 if self.native_status == 'completed' else 7, 0.0, 0.0, 'unused.stdout', 'unused.stderr')


def closing_server(tmp_path: Path, monkeypatch, **options):
    server = ml_extopt.PersistentMLServer(None, None, None, ResourceLimits(), tmp_path)
    server.ready = {'manifest_sha256': 'bound-model'}
    server.binding = {'manifest_sha256': 'bound-model'}
    future = CompletionCollection(server, **options)
    server._future = future

    def closed_socket(*args, **kwargs):
        raise ConnectionRefusedError('native worker reached its request limit')

    monkeypatch.setattr(ml_extopt, 'connect_server', closed_socket)
    return server, future


@pytest.mark.parametrize('native_status', ['completed', 'failed'])
def test_closed_stop_socket_preserves_collected_native_status(tmp_path, monkeypatch, native_status):
    server, future = closing_server(tmp_path, monkeypatch, native_status=native_status)
    result = server.close()
    assert result.status == native_status
    assert future.cancellation_at_collection == [False]
    assert future.waits == [10]
    assert server.close() is result


def test_explicit_cancellation_is_not_reclassified_as_clean_exit(tmp_path, monkeypatch):
    server, future = closing_server(tmp_path, monkeypatch)
    assert server.close(cancel=True).status == 'cancelled'
    assert future.cancellation_at_collection == [True]


def test_closed_socket_with_unresponsive_process_still_cancels_after_bounded_wait(tmp_path, monkeypatch):
    server, future = closing_server(tmp_path, monkeypatch, first_wait_times_out=True)
    assert server.close().status == 'cancelled'
    assert future.cancellation_at_collection == [False, True]
    assert future.waits == [10, 10]
