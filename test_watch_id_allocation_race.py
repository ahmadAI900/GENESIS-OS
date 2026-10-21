"""Item 25B (C35): watcher id computed without a lock.

``FilesystemMonitor.watch()`` built its id as
``f"watch_{len(self._watchers)}_{hash(path):04x}"`` with NO lock held
around the read. Two concurrent watch() calls for the SAME path both
read the pre-insert length and the same hash, so both computed the
IDENTICAL id; the inserts themselves are locked (the dict write
succeeds twice), which means the second entry silently OVERWROTE the
first -- one live observer/polling thread became unreachable: unwatch()
could not find it, stop it, or count it. Identity derived from
``len(dict)`` is also recycled: unwatch() shrinks the dict, so a later
watch() can mint an id an earlier watcher already used.

Both defects are deterministic here, no timing luck:

- The race: watch()'s caller-side id computation happens BEFORE the
  _start_* call, so the test replaces _start_polling with a barrier
  synchroniser: every thread computes its id, THEN they all release
  together and insert. Pre-fix all ids are equal (len==0 for all,
  same hash) -> N threads, 1 id, dict of size 1: N-1 watchers lost.
- The recycling: watch -> unwatch -> watch on the same path re-reads
  len==0 pre-fix and returns the same id.

Post-fix ids come from a monotonic counter incremented under
``self._lock`` in watch(); the insert sites already take that lock.
"""
from __future__ import annotations

import threading

import pytest

from genesis_os.filesystem_monitor import FilesystemMonitor


def _sync_start_patched(monitor, barrier, errors):
    """Replacement for _start_polling: release every thread only once
    all of them have computed their id, then insert under the lock."""

    def _start(path, callback, event_types, watcher_id, recursive):
        try:
            barrier.wait(timeout=5)
        except threading.BrokenBarrierError:
            errors.append("barrier broke before all ids were computed")
            return
        with monitor._lock:
            monitor._watchers[watcher_id] = (
                threading.current_thread(),
                threading.Event(),
            )

    return _start


def test_concurrent_watch_calls_get_distinct_ids_and_keep_all_watchers(
    monkeypatch,
):
    monitor = FilesystemMonitor()
    # Route deterministically to the polling branch; the id is
    # allocated BEFORE either branch runs, so this does not hide it.
    monitor._watchdog_available = False

    thread_count = 8
    barrier = threading.Barrier(thread_count)
    errors: list = []
    results: list = []
    monkeypatch.setattr(
        monitor, "_start_polling", _sync_start_patched(monitor, barrier, errors)
    )

    def worker():
        try:
            results.append(
                monitor.watch("/probe/concurrent_watch", lambda ev: None)
            )
        except Exception as exc:  # captured, never expected
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads), "worker hung"
    assert not errors, errors

    ids = list(results)
    assert len(ids) == thread_count, f"only {len(ids)} watch() calls returned"
    assert len(set(ids)) == thread_count, (
        "concurrent watch() calls minted duplicate ids (id derived from "
        f"len(_watchers) without a lock): {ids}"
    )
    assert len(monitor._watchers) == thread_count, (
        "watchers were overwritten under a duplicate id -- "
        f"{len(monitor._watchers)} entries for {thread_count} calls: "
        f"{sorted(monitor._watchers)}"
    )
    assert set(monitor._watchers) == set(ids), (
        f"registered watchers {sorted(monitor._watchers)} do not match the "
        f"returned ids {sorted(ids)}"
    )


def test_ids_are_not_recycled_after_unwatch(monkeypatch):
    monitor = FilesystemMonitor()
    monitor._watchdog_available = False

    def _sync_start(path, callback, event_types, watcher_id, recursive):
        with monitor._lock:
            monitor._watchers[watcher_id] = (
                threading.current_thread(),
                threading.Event(),
            )

    monkeypatch.setattr(monitor, "_start_polling", _sync_start)

    first = monitor.watch("/probe/recycled_watch", lambda ev: None)
    assert monitor.unwatch(first) is True, "first unwatch must succeed"

    second = monitor.watch("/probe/recycled_watch", lambda ev: None)
    assert second != first, (
        "watch() after unwatch() returned a recycled id: identity was "
        f"derived from len(_watchers) ({first!r} reused)"
    )
    assert second in monitor._watchers
