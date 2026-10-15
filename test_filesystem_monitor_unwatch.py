"""Item 3C -- FilesystemMonitor.unwatch_all() must not self-deadlock.

`unwatch_all` acquired `self._lock` and then called `unwatch()`, which
acquired the same non-reentrant `threading.Lock` again. Any machine with
one or more registered watchers hung permanently the first time
`unwatch_all()` was called.

The test runs `unwatch_all` on a worker thread and JOINS WITH A TIMEOUT,
so a regression fails fast instead of hanging the whole gate. faulthandler
is armed as a backstop: if the thread is still stuck when the join
expires, the interpreter dumps every stack so the deadlock is visible
rather than silent.
"""
from __future__ import annotations

import faulthandler
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from genesis_os.filesystem_monitor import FilesystemMonitor

JOIN_TIMEOUT = 10.0


class _FakeWatcher:
    """Minimal stand-in for a watchdog Observer."""

    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True

    def join(self, timeout=None):
        return None


def _monitor_with(n_watchers: int) -> FilesystemMonitor:
    monitor = FilesystemMonitor()
    for i in range(n_watchers):
        monitor._watchers[f"w{i}"] = _FakeWatcher()
    return monitor


def test_unwatch_all_returns_instead_of_deadlocking():
    """The regression: one watcher is enough to hang it."""
    monitor = _monitor_with(3)
    result = {}

    def run():
        result["count"] = monitor.unwatch_all()

    faulthandler.dump_traceback_later(JOIN_TIMEOUT + 5, exit=True)
    try:
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(JOIN_TIMEOUT)
    finally:
        faulthandler.cancel_dump_traceback_later()

    assert not worker.is_alive(), (
        "unwatch_all() deadlocked: it held the monitor lock and re-acquired "
        "it in unwatch(). The worker thread never returned."
    )
    assert result.get("count") == 3, (
        f"expected 3 watchers stopped, got {result.get('count')!r}"
    )
    assert monitor._watchers == {}, (
        f"watchers were not removed: {list(monitor._watchers)}"
    )


def test_unwatch_all_with_no_watchers_is_a_no_op():
    monitor = FilesystemMonitor()
    result = {}

    def run():
        result["count"] = monitor.unwatch_all()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(JOIN_TIMEOUT)

    assert not worker.is_alive()
    assert result.get("count") == 0


def test_single_unwatch_still_works_and_is_idempotent():
    """The primitive unwatch_all depends on is unchanged."""
    monitor = _monitor_with(1)
    watcher = monitor._watchers["w0"]

    assert monitor.unwatch("w0") is True
    assert watcher.stopped is True
    assert monitor.unwatch("w0") is False, (
        "unwatch of an already-removed id must report False, not raise"
    )


def test_the_monitor_lock_is_reentrant():
    """Pins WHY the fix works, so it cannot silently regress.

    unwatch_all -> unwatch acquires the same lock, so the lock must
    permit re-entry by the owning thread. A plain Lock would BLOCK here
    forever (or raise RuntimeError), so the double-acquire is done on a
    worker thread joined WITH A TIMEOUT -- a regression fails fast
    instead of hanging the gate.
    """
    monitor = FilesystemMonitor()
    acquired = threading.Event()

    def double_acquire():
        monitor._lock.acquire()
        monitor._lock.acquire()   # second acquire: legal only on an RLock
        acquired.set()
        monitor._lock.release()
        monitor._lock.release()

    faulthandler.dump_traceback_later(JOIN_TIMEOUT + 5, exit=True)
    try:
        worker = threading.Thread(target=double_acquire, daemon=True)
        worker.start()
        worker.join(JOIN_TIMEOUT)
    finally:
        faulthandler.cancel_dump_traceback_later()

    assert acquired.is_set(), (
        "the monitor lock did not permit re-entrant acquisition; it is a "
        "plain Lock again, so unwatch_all -> unwatch will deadlock"
    )