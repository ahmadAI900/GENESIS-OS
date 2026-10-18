"""Genesis OS — Phase 7: Filesystem Event Monitoring.

Watchdog integration for real-time filesystem monitoring.
This module provides event subscriptions for file changes,
enabling workflow wait/wakeup and context updates.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:  # honest fallback: watchdog optional
    Observer = None  # type: ignore[assignment]
    FileSystemEventHandler = None  # type: ignore[assignment]
    HAS_WATCHDOG = False


class FilesystemEvent:
    """A single filesystem event."""
    def __init__(self, event_type: str, path: str, src_path: Optional[str] = None):
        self.event_type = event_type  # "created", "modified", "deleted", "moved"
        self.path = path
        self.src_path = src_path
        self.timestamp = __import__("time").time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "path": self.path,
            "src_path": self.src_path,
            "timestamp": self.timestamp,
        }


class FilesystemMonitor:
    """Phase 7: Real-time filesystem event monitoring.

    Uses watchdog when available, falls back to polling.
    Provides event subscriptions for workflow wait/wakeup.
    """

    def __init__(self):
        self._watchers: Dict[str, Any] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        # Item 3C: this was a plain threading.Lock. unwatch_all() holds
        # this lock and then calls unwatch(), which acquires it again --
        # a permanent self-deadlock whenever at least one watcher was
        # registered (proven 2026-10-15 with a faulthandler dump, the
        # blocked thread parked at the `with self._lock:` inside
        # unwatch()). An RLock makes that nesting legal and is
        # behaviour-identical everywhere the lock is taken only once.
        self._lock = threading.RLock()
        self._watchdog_available = HAS_WATCHDOG
        # Live single-observer state for start()/stop() API.
        self._observer: Any = None
        self._live_path: Optional[str] = None
        self._running = False
        # In-memory ring buffer of recent live events (thread-safe).
        self._event_log: deque = deque(maxlen=200)
        self._event_lock = threading.Lock()

    def _record_event(self, event_name: str, path: str) -> None:
        """Append one event to the ring buffer. Never raises."""
        try:
            entry: Dict[str, Any] = {
                "event": event_name,
                "path": path,
                "timestamp": time.time(),
            }
            with self._event_lock:
                self._event_log.append(entry)
        except Exception:
            pass

    def recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return up to *limit* most-recent events (oldest-first copy)."""
        try:
            limit = int(limit)
        except Exception:
            limit = 50
        if limit <= 0:
            return []
        try:
            with self._event_lock:
                items = list(self._event_log)
        except Exception:
            return []
        try:
            return [dict(e) for e in items[-limit:]]
        except Exception:
            return []

    def start(
        self,
        path: str,
        callback: Callable[[Dict[str, Any]], None],
        recursive: bool = False,
    ) -> Dict[str, Any]:
        """Start live monitoring of *path* via watchdog Observer.

        Events (created/modified/deleted) invoke ``callback`` with
        ``{"event": <name>, "path": <path>}``. No fake events are ever
        emitted. If watchdog is not installed, returns an honest
        failure dict and emits nothing.
        """
        if not HAS_WATCHDOG or Observer is None:
            return {
                "success": False,
                "error": "watchdog not installed",
                "fallback": "honest fallback: live monitoring unavailable, no events emitted",
                "watching": False,
            }
        if not path or not isinstance(path, str):
            return {"success": False, "error": "invalid path", "watching": False}
        if callback is None or not callable(callback):
            return {"success": False, "error": "callback must be callable", "watching": False}
        if not os.path.exists(path):
            return {"success": False, "error": f"path does not exist: {path}", "watching": False}

        with self._lock:
            if self._running and self._observer is not None:
                try:
                    self._observer.stop()
                except Exception:
                    pass
                try:
                    self._observer.join(timeout=2.0)
                except Exception:
                    pass
                self._observer = None
                self._running = False

        try:
            base_handler = FileSystemEventHandler
            _record = self._record_event

            class _LiveHandler(base_handler):  # type: ignore[valid-type,misc]
                def _emit(self, event_name: str, src: str) -> None:
                    # Record first so the ring buffer keeps the event even
                    # if the user callback raises. Neither step may ever
                    # propagate into the watchdog observer thread.
                    try:
                        _record(event_name, src)
                    except Exception:
                        pass
                    try:
                        callback({"event": event_name, "path": src, "timestamp": time.time()})
                    except Exception:
                        pass

                def on_created(self, event):  # noqa: N802
                    try:
                        if event is not None:
                            self._emit("created", event.src_path)
                    except Exception:
                        pass

                def on_modified(self, event):  # noqa: N802
                    try:
                        if event is not None:
                            self._emit("modified", event.src_path)
                    except Exception:
                        pass

                def on_deleted(self, event):  # noqa: N802
                    try:
                        if event is not None:
                            self._emit("deleted", event.src_path)
                    except Exception:
                        pass

                def on_moved(self, event):  # noqa: N802
                    try:
                        if event is not None:
                            dest = getattr(event, "dest_path", None) or getattr(event, "src_path", "")
                            self._emit("moved", dest)
                    except Exception:
                        pass

            handler = _LiveHandler()
            observer = Observer()
            observer.schedule(handler, path, recursive=recursive)
            observer.start()
            with self._lock:
                self._observer = observer
                self._live_path = path
                self._running = True
            return {"success": True, "path": path, "watching": True, "recursive": recursive}
        except Exception as exc:
            return {"success": False, "error": str(exc), "watching": False}

    def stop(self) -> Dict[str, Any]:
        """Stop live monitoring started by start(). Joins the observer."""
        with self._lock:
            observer = self._observer
            self._observer = None
            self._running = False
            live_path = self._live_path
            self._live_path = None
        if observer is None:
            return {"success": True, "watching": False, "path": live_path}
        try:
            observer.stop()
        except Exception:
            pass
        try:
            observer.join(timeout=5.0)
        except Exception:
            pass
        return {"success": True, "watching": False, "path": live_path}

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running and self._observer is not None

    @property
    def watchdog_available(self) -> bool:
        return self._watchdog_available

    def watch(
        self,
        path: str,
        callback: Callable[[FilesystemEvent], None],
        recursive: bool = False,
        event_types: Optional[List[str]] = None,
    ) -> str:
        """Start watching a path for filesystem events.

        Returns a watcher ID for later unwatch().
        """
        watcher_id = f"watch_{len(self._watchers)}_{hash(path) & 0xFFFF:04x}"

        if self._watchdog_available:
            self._start_watchdog(path, callback, recursive, event_types, watcher_id)
        else:
            # Item 14C (C10): recursive was dropped here.
            self._start_polling(path, callback, event_types, watcher_id, recursive)

        return watcher_id

    def unwatch(self, watcher_id: str) -> bool:
        """Stop watching a path."""
        with self._lock:
            watcher = self._watchers.pop(watcher_id, None)
            if watcher is None:
                return False
            if self._watchdog_available and hasattr(watcher, "stop"):
                watcher.stop()
                watcher.join(timeout=2.0)
            return True

    def unwatch_all(self) -> int:
        """Stop all watchers. Returns count stopped."""
        count = 0
        with self._lock:
            for watcher_id in list(self._watchers.keys()):
                if self.unwatch(watcher_id):
                    count += 1
        return count

    def _start_watchdog(
        self,
        path: str,
        callback: Callable[[FilesystemEvent], None],
        recursive: bool,
        event_types: Optional[List[str]],
        watcher_id: str,
    ) -> None:
        """Start a watchdog-based watcher."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            _record = self._record_event

            class _Handler(FileSystemEventHandler):
                def __init__(self, cb, types_filter):
                    self._cb = cb
                    self._types = types_filter

                def _should_handle(self, event_type):
                    return self._types is None or event_type in self._types

                def _safe_emit(self, fs_event: FilesystemEvent) -> None:
                    try:
                        _record(fs_event.event_type, fs_event.path)
                    except Exception:
                        pass
                    try:
                        self._cb(fs_event)
                    except Exception:
                        pass

                def on_created(self, event):
                    try:
                        if self._should_handle("created"):
                            self._safe_emit(FilesystemEvent("created", event.src_path))
                    except Exception:
                        pass

                def on_modified(self, event):
                    try:
                        if self._should_handle("modified"):
                            self._safe_emit(FilesystemEvent("modified", event.src_path))
                    except Exception:
                        pass

                def on_deleted(self, event):
                    try:
                        if self._should_handle("deleted"):
                            self._safe_emit(FilesystemEvent("deleted", event.src_path))
                    except Exception:
                        pass

                def on_moved(self, event):
                    try:
                        if self._should_handle("moved"):
                            self._safe_emit(FilesystemEvent("moved", event.dest_path, event.src_path))
                    except Exception:
                        pass

            handler = _Handler(callback, event_types)
            observer = Observer()
            observer.schedule(handler, path, recursive=recursive)
            observer.start()
            with self._lock:
                self._watchers[watcher_id] = observer
        except Exception:
            # Item 14C (C10): the watchdog path can fail AFTER the
            # caller asked for a recursive watch (e.g. the import or
            # observer.schedule raises). Falling back to polling must
            # not quietly drop `recursive` on the floor.
            self._start_polling(path, callback, event_types, watcher_id, recursive)

    def _start_polling(
        self,
        path: str,
        callback: Callable[[FilesystemEvent], None],
        event_types: Optional[List[str]],
        watcher_id: str,
        recursive: bool = False,
    ) -> None:
        """Start a polling-based watcher (fallback).

        Item 14C (C10): `recursive` is threaded through to the snapshot
        so the polling fallback covers the same tree the caller asked
        for. It defaults to False so any existing direct caller keeps
        the old single-level behaviour rather than changing shape.
        """
        stop_event = threading.Event()
        snapshot = self._snapshot_path(path, recursive)

        def _poll():
            while not stop_event.is_set():
                stop_event.wait(1.0)
                if stop_event.is_set():
                    break
                try:
                    current = self._snapshot_path(path, recursive)
                    self._detect_changes(snapshot, current, callback, event_types)
                    snapshot.clear()
                    snapshot.update(current)
                except Exception:
                    pass

        t = threading.Thread(target=_poll, daemon=True, name=f"fs_poll_{watcher_id}")
        t.start()
        with self._lock:
            self._watchers[watcher_id] = (t, stop_event)

    def _snapshot_path(
        self, path: str, recursive: bool = False
    ) -> Dict[str, float]:
        """Take a snapshot of file modification times.

        Item 14C (C10): `recursive` is honoured here. It used to be a
        parameter of `watch()` that silently did nothing whenever the
        polling fallback was in play -- `_start_polling` was called
        without it, so a recursive watch on a host without watchdog
        quietly watched only the top level and reported nothing about
        subdirectories. Failing silently was the worst option: the
        caller asked for subtree coverage and got none, with no
        indication either way.

        DELIBERATE CHOICE: the recursive walk snapshots the SAME KIND
        of entry the single-level `os.scandir` path always did --
        directories as well as files -- just at every level. The
        original code did not filter `os.scandir` results by type, so
        excluding directories under a walk would have made
        `recursive=True` behave by a different rule than
        `recursive=False` rather than being a strict superset of it.
        A recursive watch therefore still reports an ancestor
        directory's mtime bump when something beneath it changes, which
        is exactly what a single-level watch already did for top-level
        directories.
        """
        snapshot: Dict[str, float] = {}
        try:
            if os.path.isfile(path):
                snapshot[path] = os.path.getmtime(path)
            elif os.path.isdir(path):
                if recursive:
                    for dirpath, dirnames, filenames in os.walk(path):
                        for name in dirnames + filenames:
                            full = os.path.join(dirpath, name)
                            try:
                                snapshot[full] = os.stat(full).st_mtime
                            except (OSError, PermissionError):
                                pass
                else:
                    for entry in os.scandir(path):
                        try:
                            snapshot[entry.path] = entry.stat().st_mtime
                        except (OSError, PermissionError):
                            pass
        except (OSError, PermissionError):
            pass
        return snapshot

    def _detect_changes(
        self,
        old: Dict[str, float],
        new: Dict[str, float],
        callback: Callable[[FilesystemEvent], None],
        event_types: Optional[List[str]],
    ) -> None:
        """Detect changes between two snapshots."""
        types_filter = event_types

        def _safe_cb(fs_event: FilesystemEvent) -> None:
            try:
                self._record_event(fs_event.event_type, fs_event.path)
            except Exception:
                pass
            try:
                callback(fs_event)
            except Exception:
                pass

        for path in new:
            if path not in old:
                if types_filter is None or "created" in types_filter:
                    _safe_cb(FilesystemEvent("created", path))
            elif new[path] != old[path]:
                if types_filter is None or "modified" in types_filter:
                    _safe_cb(FilesystemEvent("modified", path))

        for path in old:
            if path not in new:
                if types_filter is None or "deleted" in types_filter:
                    _safe_cb(FilesystemEvent("deleted", path))
