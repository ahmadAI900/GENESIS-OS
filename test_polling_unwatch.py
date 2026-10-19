"""Item 17C (C19): unwatch() never stopped a polling watcher.

`_start_polling` stores watchers as `(thread, stop_event)` tuples, but
`unwatch()` only knew about watchdog Observers:

    if self._watchdog_available and hasattr(watcher, "stop"):
        watcher.stop()
        watcher.join(timeout=2.0)
    return True

A tuple has no `.stop`, so nothing happened: the stop_event was never
set, the polling thread never exited -- and unwatch() still returned
True. It popped the id and reported the watch as stopped while the
thread kept polling the filesystem forever. Reproduced against the
committed original via watch()/unwatch() on a watchdog-less monitor:

    unwatch() ->  : True
    stop_event set: False
    thread alive   : True (1.5s after unwatch)

The same hole covers the watchdog->polling FALLBACK: _start_watchdog
can raise after the caller asked for a watch (missing/failed import,
schedule error), in which case _start_polling stores a tuple while
_watchdog_available stays True -- the hasattr() check, not the flag,
was always the only gate.

The fix dispatches on SHAPE (isinstance tuple vs .stop object), pops
under the lock, and joins OUTSIDE it (the pattern stop() already
uses), so a watcher callback re-entering the monitor cannot stall
behind a join. Return value is honest: True only if the watcher was
found AND stopped; False for an unknown id or a thread that outlived
the join window.
"""
from __future__ import annotations

import ast
import pathlib
import threading
import time

import pytest

from genesis_os.filesystem_monitor import FilesystemMonitor

MODULE = pathlib.Path("genesis_os") / "filesystem_monitor.py"


@pytest.fixture
def polling_monitor(monkeypatch, tmp_path):
    """A monitor forced onto the polling fallback, as on a machine
    without watchdog."""
    monitor = FilesystemMonitor()
    monkeypatch.setattr(monitor, "_watchdog_available", False)
    return monitor


def _unwatch_node() -> ast.FunctionDef:
    tree = ast.parse(MODULE.read_text(encoding="utf-8-sig"))
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "FilesystemMonitor":
            for node in cls.body:
                if isinstance(node, ast.FunctionDef) and node.name == "unwatch":
                    return node
    raise AssertionError("FilesystemMonitor.unwatch not found")


# --------------------------------------------------------------------------
# The regression: unwatch must actually stop the polling thread
# --------------------------------------------------------------------------

def test_unwatch_stops_the_polling_thread(polling_monitor, tmp_path):
    wid = polling_monitor.watch(str(tmp_path), lambda ev: None)

    watcher = polling_monitor._watchers.get(wid)
    assert isinstance(watcher, tuple), (
        f"expected a (thread, stop_event) polling watcher, got "
        f"{watcher!r}"
    )
    thread, stop_event = watcher

    assert polling_monitor.unwatch(wid) is True, (
        "unwatch() of a live polling watcher must report True only "
        "because it actually stopped it"
    )
    assert stop_event.is_set(), (
        "unwatch() returned without setting the polling stop_event -- "
        "the thread has no reason to exit and will poll forever"
    )
    thread.join(timeout=3.0)
    assert not thread.is_alive(), (
        "the polling thread is still alive after unwatch(); the watch "
        "was deregistered but never stopped"
    )
    assert wid not in polling_monitor._watchers


def test_unwatch_stops_a_polling_watcher_even_when_watchdog_is_available(
    monkeypatch, tmp_path
):
    """The watchdog->polling FALLBACK case: _start_watchdog raised,
    _start_polling stored a tuple, and _watchdog_available is still
    True. The old hasattr() gate skipped it exactly the same way.
    """
    monitor = FilesystemMonitor()  # _watchdog_available stays True
    assert monitor._watchdog_available is True
    events = []
    # Exactly what _start_watchdog's except branch does on failure.
    monitor._start_polling(str(tmp_path), events.append, None, "fallback_0")

    thread, stop_event = monitor._watchers["fallback_0"]

    assert monitor.unwatch("fallback_0") is True
    assert stop_event.is_set(), (
        "a polling watcher created by the watchdog fallback was not "
        "stopped -- _watchdog_available being True made no difference "
        "to the tuple"
    )
    thread.join(timeout=3.0)
    assert not thread.is_alive()


def test_unwatch_all_stops_and_counts_polling_watchers(polling_monitor, tmp_path):
    ids = []
    threads = []
    for name in ("a", "b"):
        sub = tmp_path / name
        sub.mkdir()
        wid = polling_monitor.watch(str(sub), lambda ev: None)
        ids.append(wid)
        thread, stop_event = polling_monitor._watchers[wid]
        threads.append((thread, stop_event))

    count = polling_monitor.unwatch_all()

    assert count == 2, (
        f"expected 2 watchers stopped, got {count} -- watchers that "
        "were not actually stopped must not be counted as stopped"
    )
    for i, (thread, stop_event) in enumerate(threads):
        assert stop_event.is_set(), (
            f"watcher #{i} was counted as stopped but its stop_event "
            "was never set"
        )
        thread.join(timeout=3.0)
        assert not thread.is_alive(), (
            f"watcher #{i} thread survived unwatch_all()"
        )
    assert polling_monitor._watchers == {}


def test_unwatch_from_inside_the_polling_callback_does_not_raise(
    polling_monitor, tmp_path
):
    """unwatch() called BY the polling thread (from a callback): it
    must deliver the stop signal without trying to join itself --
    Thread.join on the current thread raises RuntimeError.
    """
    stop_event = threading.Event()
    polling_monitor._watchers["self_w"] = (threading.current_thread(), stop_event)

    assert polling_monitor.unwatch("self_w") is True
    assert stop_event.is_set(), (
        "the self-unwatch path returned without delivering the stop "
        "signal; the loop would never see it"
    )


def test_unwatch_reports_false_when_the_thread_outlives_the_join_window(
    polling_monitor,
):
    """Honesty: a thread that ignores the signal must NOT be reported
    as stopped. The stop signal is still delivered (the loop exits
    after its current work), but this call did not observe the stop.
    """
    stubborn = threading.Thread(
        target=lambda: time.sleep(5.0), daemon=True, name="stubborn_poll"
    )
    stubborn.start()
    polling_monitor._watchers["stuck"] = (stubborn, threading.Event())

    result = polling_monitor.unwatch("stuck")

    assert result is False, (
        "a polling thread that outlived the join window was reported "
        "as stopped; the return value must reflect what was observed, "
        "not what was hoped for"
    )
    assert "stuck" not in polling_monitor._watchers, (
        "the entry must be deregistered even when the thread could not "
        "be confirmed stopped"
    )


def test_unwatch_of_an_unknown_id_still_returns_false(polling_monitor):
    """The pre-existing contract unwatch_all() depends on."""
    assert polling_monitor.unwatch("never_existed") is False


# --------------------------------------------------------------------------
# Structural: shape-based dispatch, stop/join outside the lock
# --------------------------------------------------------------------------

def test_the_source_dispatches_on_shape_and_documents_the_item():
    node = _unwatch_node()
    body = ast.unparse(node)
    assert "isinstance(watcher, tuple)" in body, (
        "unwatch() does not dispatch on the tuple shape; a polling "
        "watcher will fall through un-stopped again"
    )
    assert "stop_event.set()" in body, (
        "the polling branch does not set the stop_event"
    )
    doc = ast.get_docstring(node) or ""
    assert "Item 17C (C19)" in doc, (
        "the unwatch docstring does not record why the shape-based "
        "dispatch exists"
    )
    assert "_watchdog_available" in doc and "SHAPE decides" in doc, (
        "the docstring no longer records that SHAPE -- not the global "
        "watchdog flag -- decides how a watcher is stopped"
    )


def test_the_stop_and_join_happen_outside_the_lock():
    """Pop under the lock, then stop/join with it released -- the
    pattern stop() already uses. Holding the lock across a join stalls
    any watcher callback that re-enters the monitor.
    """
    node = _unwatch_node()
    locked = [
        n for n in ast.walk(node)
        if isinstance(n, ast.With)
        and any(
            "self._lock" in ast.unparse(i.context_expr) for i in n.items
        )
    ]
    assert locked, "unwatch() no longer pops under the registry lock"
    for block in locked:
        src = ast.unparse(block)
        assert "join(" not in src and "stop()" not in src, (
            "the bounded stop/join runs while the registry lock is "
            "held; a callback re-entering the monitor stalls behind it"
        )
