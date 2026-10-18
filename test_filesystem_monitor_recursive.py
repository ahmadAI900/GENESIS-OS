"""Item 14C (C10): `recursive` must be honoured on the polling fallback.

`FilesystemMonitor.watch(path, cb, recursive=True)` had two paths. With
watchdog installed, `recursive` reached `observer.schedule`. Without it,
`_start_polling` was called WITHOUT the argument -- so a caller that
asked for subtree coverage got a watcher covering only the top level,
and nothing said so.

There was a second, less obvious instance of the same drop: if watchdog
is present but the watch fails *after* the caller asked for recursion
(the import or `observer.schedule` raises), `_start_watchdog` falls back
to polling -- and dropped `recursive` there too.

`recursive` is now threaded through to `_snapshot_path`, which walks the
subtree when asked.

The poll interval is 1.0s, so the end-to-end tests cost ~2s each.
"""
from __future__ import annotations

import sys
import time

import pytest

from genesis_os.filesystem_monitor import FilesystemMonitor


POLL_INTERVAL = 1.0
SETTLE = POLL_INTERVAL + 1.0  # one full poll plus slack


def _wait_for(predicate, timeout=6.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def tree(tmp_path):
    """A root with a nested subtree three levels deep."""
    root = tmp_path / "root"
    deep = root / "sub" / "deeper"
    deep.mkdir(parents=True)
    (root / "top.txt").write_text("top")
    (root / "sub" / "mid.txt").write_text("mid")
    (deep / "deep.txt").write_text("deep")
    return root


@pytest.fixture
def polling_monitor(monkeypatch):
    """A monitor forced onto the polling fallback."""
    monitor = FilesystemMonitor()
    monkeypatch.setattr(monitor, "_watchdog_available", False)
    assert monitor.watchdog_available is False
    return monitor


# --------------------------------------------------------------------------
# The unit: does the snapshot cover the subtree?
# --------------------------------------------------------------------------

def test_recursive_snapshot_includes_nested_files(polling_monitor, tree):
    shallow = polling_monitor._snapshot_path(str(tree), recursive=False)
    deep = polling_monitor._snapshot_path(str(tree), recursive=True)

    # The original scandir path snapshots every entry, directories
    # included, so the top level already holds `top.txt` AND `sub`.
    assert set(shallow) == {str(tree / "top.txt"), str(tree / "sub")}

    assert str(tree / "top.txt") in deep
    assert str(tree / "sub" / "mid.txt") in deep, (
        "recursive snapshot missed a file one level down"
    )
    assert str(tree / "sub" / "deeper" / "deep.txt") in deep, (
        "recursive snapshot missed a file two levels down"
    )


def test_recursive_snapshot_is_a_strict_superset_of_shallow(polling_monitor, tree):
    """`recursive=True` must extend the same rule, not change it."""
    shallow = polling_monitor._snapshot_path(str(tree), recursive=False)
    deep = polling_monitor._snapshot_path(str(tree), recursive=True)

    assert shallow.keys() <= deep.keys(), (
        "recursive watch lost coverage the non-recursive watch had: "
        f"{set(shallow) - set(deep)}"
    )
    assert len(deep) > len(shallow), "recursive added nothing at all"


def test_non_recursive_snapshot_is_unchanged(polling_monitor, tree):
    """Default behaviour must not have shifted."""
    snapshot = polling_monitor._snapshot_path(str(tree))

    assert set(snapshot) == {str(tree / "top.txt"), str(tree / "sub")}


def test_recursive_snapshot_of_a_file_is_that_file(polling_monitor, tree):
    target = tree / "sub" / "mid.txt"

    snapshot = polling_monitor._snapshot_path(str(target), recursive=True)

    assert set(snapshot) == {str(target)}


def test_snapshot_of_a_missing_path_is_empty(polling_monitor, tree):
    assert polling_monitor._snapshot_path(str(tree / "nope"), recursive=True) == {}


# --------------------------------------------------------------------------
# End to end: the caller's recursive watch must actually SEE the subtree
# --------------------------------------------------------------------------

def test_a_recursive_polling_watch_observes_a_subdirectory_change(
    polling_monitor, tree
):
    events = []
    polling_monitor.watch(str(tree), events.append, recursive=True)

    (tree / "sub" / "new_in_subdir.txt").write_text("hello")

    assert _wait_for(lambda: any(e.path.endswith("new_in_subdir.txt") for e in events)), (
        "a recursive watch on the polling fallback never reported a "
        f"change in a subdirectory; events={[(e.event_type, e.path) for e in events]}"
    )
    created = [e for e in events if e.event_type == "created"]
    assert created, events
    assert str(tree / "sub" / "new_in_subdir.txt") in created[0].path


def test_a_recursive_polling_watch_observes_a_deeply_nested_change(
    polling_monitor, tree
):
    events = []
    polling_monitor.watch(str(tree), events.append, recursive=True)

    deep_file = tree / "sub" / "deeper" / "added.txt"
    deep_file.write_text("hello")

    assert _wait_for(lambda: any(e.path.endswith("added.txt") for e in events)), (
        f"two levels down was never observed; events={[(e.event_type, e.path) for e in events]}"
    )


def test_a_recursive_polling_watch_observes_a_subdirectory_deletion(
    polling_monitor, tree
):
    events = []
    polling_monitor.watch(str(tree), events.append, recursive=True)

    victim = tree / "sub" / "mid.txt"
    victim.unlink()

    assert _wait_for(lambda: any(e.event_type == "deleted" for e in events)), (
        f"a deletion inside a subdirectory was never observed; events={[(e.event_type, e.path) for e in events]}"
    )
    deleted = [e for e in events if e.event_type == "deleted"]
    assert any(e.path.endswith("mid.txt") for e in deleted), deleted


def test_a_non_recursive_polling_watch_does_not_see_subdirectories(
    polling_monitor, tree
):
    """The counterpart: the flag must still mean something."""
    events = []
    polling_monitor.watch(str(tree), events.append, recursive=False)

    (tree / "sub" / "ignored.txt").write_text("hello")
    time.sleep(SETTLE)

    assert not any("ignored.txt" in e.path for e in events), (
        "a NON-recursive watch reported a subdirectory change, so the "
        "flag is not actually being honoured in either direction"
    )


# --------------------------------------------------------------------------
# The second drop: watchdog present but failing
# --------------------------------------------------------------------------

def test_recursive_survives_the_watchdog_to_polling_fallback(tree, monkeypatch):
    """If watchdog blows up mid-setup, the fallback must stay recursive."""
    monitor = FilesystemMonitor()
    monkeypatch.setattr(monitor, "_watchdog_available", True)

    # Setting a sys.modules entry to None makes `from watchdog... import`
    # raise ImportError, which _start_watchdog catches and turns into a
    # polling fallback -- after `recursive` was already supplied.
    for name in ("watchdog", "watchdog.observers", "watchdog.events"):
        monkeypatch.setitem(sys.modules, name, None)

    events = []
    monitor.watch(str(tree), events.append, recursive=True)

    (tree / "sub" / "fallback.txt").write_text("hello")

    assert _wait_for(lambda: any(e.path.endswith("fallback.txt") for e in events)), (
        "the watchdog->polling fallback dropped `recursive`; events="
        f"{[(e.event_type, e.path) for e in events]}"
    )


# --------------------------------------------------------------------------
# Structural guard
# --------------------------------------------------------------------------

def test_every_start_polling_call_forwards_recursive():
    """No call site may drop the argument again."""
    import ast
    import pathlib

    path = pathlib.Path(sys.modules[FilesystemMonitor.__module__].__file__)
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))

    calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_start_polling"
        ):
            calls.append(node)

    assert calls, "no _start_polling call sites found to check"

    # recursive is the 5th positional parameter, so a forwarded call
    # carries >=5 positional args.
    dropped = [
        node.lineno for node in calls if len(node.args) < 5
    ]

    assert not dropped, (
        f"_start_polling called without `recursive` at line(s) {dropped}; "
        "a recursive watch would silently degrade to top-level only"
    )