"""
Genesis OS — Level 3.9 Application State Machine.

Formal state machine for application lifecycle management.

States:
    NOT_INSTALLED  → Application not found on system
    INSTALLED      → Application exists but not running
    STARTING       → Launch initiated, not yet verified
    RUNNING        → Process detected in process table
    READY          → Application responsive and usable
    FOCUSED        → Application has keyboard/window focus
    UNRESPONSIVE   → Application detected but not responding
    STOPPING       → Close initiated, not yet verified
    STOPPED        → Application confirmed not running
    UNKNOWN        → State cannot be determined

Transitions:
    NOT_INSTALLED → INSTALLED   (discovery confirms installation)
    INSTALLED → STARTING        (launch initiated)
    STARTING → RUNNING          (process detected)
    STARTING → NOT_INSTALLED    (launch failed, not installed)
    RUNNING → READY             (application responsive)
    RUNNING → UNRESPONSIVE      (timeout/no response)
    READY → FOCUSED             (window focus acquired)
    FOCUSED → READY             (focus lost)
    READY → STOPPING            (close initiated)
    RUNNING → STOPPING          (close initiated)
    STOPPING → STOPPED          (process terminated)
    STOPPING → RUNNING          (close failed, still running)
    STOPPED → INSTALLED         (reset)
    UNRESPONSIVE → RUNNING      (recovered)
    UNRESPONSIVE → STOPPING     (force close)

Every transition produces evidence (process table, window inspection).
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


class AppState(Enum):
    """Application lifecycle states."""
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"
    STARTING = "starting"
    RUNNING = "running"
    READY = "ready"
    FOCUSED = "focused"
    UNRESPONSIVE = "unresponsive"
    STOPPING = "stopping"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


# Valid state transitions
_VALID_TRANSITIONS: Dict[AppState, set[AppState]] = {
    AppState.NOT_INSTALLED: {AppState.INSTALLED, AppState.UNKNOWN},
    AppState.INSTALLED: {AppState.STARTING, AppState.NOT_INSTALLED, AppState.UNKNOWN},
    AppState.STARTING: {AppState.RUNNING, AppState.NOT_INSTALLED, AppState.UNKNOWN},
    AppState.RUNNING: {AppState.READY, AppState.UNRESPONSIVE, AppState.STOPPING, AppState.UNKNOWN},
    AppState.READY: {AppState.FOCUSED, AppState.STOPPING, AppState.RUNNING, AppState.UNKNOWN},
    AppState.FOCUSED: {AppState.READY, AppState.STOPPING, AppState.UNKNOWN},
    AppState.UNRESPONSIVE: {AppState.RUNNING, AppState.STOPPING, AppState.UNKNOWN},
    AppState.STOPPING: {AppState.STOPPED, AppState.RUNNING, AppState.UNKNOWN},
    AppState.STOPPED: {AppState.INSTALLED, AppState.UNKNOWN},
    AppState.UNKNOWN: {
        AppState.NOT_INSTALLED, AppState.INSTALLED, AppState.STARTING,
        AppState.RUNNING, AppState.READY, AppState.FOCUSED,
        AppState.UNRESPONSIVE, AppState.STOPPING, AppState.STOPPED,
    },
}


@dataclass
class StateTransition:
    """Record of a single state transition."""
    from_state: AppState
    to_state: AppState
    timestamp: datetime
    evidence: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from": self.from_state.value,
            "to": self.to_state.value,
            "timestamp": self.timestamp.isoformat(),
            "evidence": self.evidence,
            "metadata": dict(self.metadata),
        }


class ApplicationStateMachine:
    """
    Formal state machine for application lifecycle.

    Every transition is evidence-based and recorded.
    Invalid transitions are rejected.
    """

    VERSION = "3.9.0"

    def __init__(self, application_name: str):
        self.application_name = application_name
        self._state = AppState.UNKNOWN
        self._history: List[StateTransition] = []
        self._last_updated = datetime.now()

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def history(self) -> List[StateTransition]:
        return list(self._history)

    def transition(
        self,
        new_state: AppState,
        evidence: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Attempt a state transition.

        Returns True if the transition was valid and applied.
        Returns False if the transition is invalid.
        """
        if new_state == self._state:
            return True

        valid = _VALID_TRANSITIONS.get(self._state, set())
        if new_state not in valid:
            return False

        record = StateTransition(
            from_state=self._state,
            to_state=new_state,
            timestamp=datetime.now(),
            evidence=evidence,
            metadata=metadata or {},
        )

        self._history.append(record)
        self._state = new_state
        self._last_updated = datetime.now()
        return True

    def force_state(
        self,
        new_state: AppState,
        evidence: str,
    ) -> None:
        """Force a state transition, bypassing validation. Use only for initialization."""
        record = StateTransition(
            from_state=self._state,
            to_state=new_state,
            timestamp=datetime.now(),
            evidence=evidence,
            metadata={"forced": True},
        )
        self._history.append(record)
        self._state = new_state
        self._last_updated = datetime.now()

    def can_transition(self, new_state: AppState) -> bool:
        """Check if a transition is valid without applying it."""
        valid = _VALID_TRANSITIONS.get(self._state, set())
        return new_state in valid

    def to_dict(self) -> Dict[str, Any]:
        return {
            "application": self.application_name,
            "state": self._state.value,
            "last_updated": self._last_updated.isoformat(),
            "transition_count": len(self._history),
            "history": [t.to_dict() for t in self._history[-10:]],
            "version": self.VERSION,
        }

    def reset(self) -> None:
        """Reset to UNKNOWN state."""
        self.force_state(AppState.UNKNOWN, "manual_reset")


class ApplicationWindowTracker:
    """
    Multi-window tracking with focus rollback.

    Applications frequently own more than one top-level window
    (main window, dialogs, floating toolbars).  This tracker keeps
    ``app name -> list of known hwnds`` and validates the cache
    against the live top-level window table so
    :meth:`list_windows` only ever returns real, still-existing
    handles.

    :meth:`focus_window` snapshots the current foreground window
    before switching; on failure it restores the previous
    foreground handle (rollback) and reports ``rolled_back=True``.
    """

    VERSION = "3.9.1"

    def __init__(self) -> None:
        self._windows: Dict[str, List[int]] = {}
        # Cross-app rollback stack: snapshots of
        # {app, hwnd, foreground} pushed before focus_window/close
        # so a failed switch can restore the previous foreground.
        # Bounded to 32 entries.
        self._snapshot_stack: List[Dict[str, Any]] = []

    # --------------------------------------------------------
    # REGISTRATION
    # --------------------------------------------------------

    def register_window(self, app: str, hwnd: int) -> None:
        """Record that ``hwnd`` belongs to ``app``."""
        try:
            handle = int(hwnd)
        except (TypeError, ValueError):
            return
        if handle <= 0:
            return
        known = self._windows.setdefault(str(app), [])
        if handle not in known:
            known.append(handle)

    def unregister_window(self, app: str, hwnd: int) -> None:
        """Forget a previously registered window handle."""
        known = self._windows.get(str(app))
        if not known:
            return
        try:
            known.remove(int(hwnd))
        except (TypeError, ValueError):
            pass
        if not known:
            self._windows.pop(str(app), None)

    def tracked_apps(self) -> List[str]:
        """Return the names of all apps with registered windows."""
        return sorted(self._windows.keys())

    # --------------------------------------------------------
    # LIVE ENUMERATION
    # --------------------------------------------------------

    def _enumerate_live_windows(self) -> List[Dict[str, Any]]:
        """Enumerate visible top-level windows via user32.

        Returns ``[{hwnd, title}]``.  Returns ``[]`` when the
        Win32 API is unavailable (non-Windows host) — callers
        fall back to the registration cache.
        """
        try:
            import ctypes
            import ctypes.wintypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        except Exception:
            return []

        windows: List[Dict[str, Any]] = []

        try:
            EnumWindowsProc = ctypes.WINFUNCTYPE(
                ctypes.c_bool,
                ctypes.wintypes.HWND,
                ctypes.wintypes.LPARAM,
            )

            def callback(hwnd, _lparam):
                try:
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length == 0:
                        return True
                    buf = (ctypes.c_wchar * (length + 1))()
                    user32.GetWindowTextW(
                        hwnd, ctypes.byref(buf), length + 1
                    )
                    windows.append(
                        {"hwnd": int(hwnd), "title": buf.value or ""}
                    )
                except Exception:
                    pass
                return True

            user32.EnumWindows(EnumWindowsProc(callback), 0)
        except Exception:
            return []

        return windows

    def list_windows(self, app: str) -> List[int]:
        """Return live top-level handles belonging to ``app``.

        Cached handles are validated against the live window
        table so stale (closed) handles are dropped, and live
        windows whose title contains the app name are discovered
        and merged into the cache.  When the Win32 API is
        unavailable the registration cache is returned as-is.
        """
        key = str(app)
        known = list(self._windows.get(key, []))
        live = self._enumerate_live_windows()

        if not live:
            return known

        live_hwnds = {w["hwnd"] for w in live}
        result = [h for h in known if h in live_hwnds]

        lowered = key.lower()
        for window in live:
            if window["hwnd"] not in result and lowered in (
                window["title"] or ""
            ).lower():
                result.append(window["hwnd"])

        self._windows[key] = list(result)
        return list(result)

    # --------------------------------------------------------
    # FOCUS WITH ROLLBACK
    # --------------------------------------------------------

    def get_foreground_hwnd(self) -> Optional[int]:
        """Return the current foreground window handle, if known."""
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetForegroundWindow()  # type: ignore[attr-defined]
            return int(hwnd) if hwnd else None
        except Exception:
            return None

    @staticmethod
    def _restore_foreground(
        previous_hwnd: Optional[int], target_hwnd: int
    ) -> bool:
        """Restore a snapshotted foreground handle (rollback)."""
        if previous_hwnd in (None, 0, target_hwnd):
            return False
        try:
            import ctypes

            return bool(
                ctypes.windll.user32.SetForegroundWindow(  # type: ignore[attr-defined]
                    previous_hwnd
                )
            )
        except Exception:
            return False

    # --------------------------------------------------------
    # CROSS-APP ROLLBACK STACK
    # --------------------------------------------------------

    def _push_snapshot(
        self,
        app: Optional[str],
        hwnd: int,
        foreground: Optional[int],
    ) -> Dict[str, Any]:
        """Push a {app, hwnd, foreground} snapshot before focus/close."""
        snapshot: Dict[str, Any] = {
            "app": app,
            "hwnd": int(hwnd) if hwnd is not None else None,
            "foreground": foreground,
        }
        self._snapshot_stack.append(snapshot)
        if len(self._snapshot_stack) > 32:
            del self._snapshot_stack[:-32]
        return snapshot

    def rollback_last(self) -> Dict[str, Any]:
        """Restore the most recent snapshot's foreground window.

        Pops the latest ``{app, hwnd, foreground}`` snapshot and
        restores its ``foreground`` handle via
        ``SetForegroundWindow`` (guarded try/except).  Returns
        ``{rolled_back: bool, ...}`` — ``rolled_back`` is True only
        when the OS confirms the restore.
        """
        if not self._snapshot_stack:
            return {
                "rolled_back": False,
                "restored_hwnd": None,
                "snapshot": None,
                "error": "Empty snapshot stack.",
            }
        snapshot = self._snapshot_stack.pop()
        foreground = snapshot.get("foreground")
        target = snapshot.get("hwnd")
        if foreground in (None, 0, target):
            return {
                "rolled_back": False,
                "restored_hwnd": None,
                "snapshot": snapshot,
                "error": None,
            }
        try:
            import ctypes

            restored = bool(
                ctypes.windll.user32.SetForegroundWindow(  # type: ignore[attr-defined]
                    foreground
                )
            )
            return {
                "rolled_back": restored,
                "restored_hwnd": foreground if restored else None,
                "snapshot": snapshot,
                "error": None,
            }
        except Exception as exc:
            return {
                "rolled_back": False,
                "restored_hwnd": None,
                "snapshot": snapshot,
                "error": str(exc),
            }

    def close_window(
        self, app: str, hwnd: int
    ) -> Dict[str, Any]:
        """Close ``hwnd`` belonging to ``app`` with rollback snapshot.

        Pushes a ``{app, hwnd, foreground}`` snapshot before
        attempting ``WM_CLOSE`` via user32.  The snapshot stays on
        the stack so the caller can :meth:`rollback_last` if the
        close needs to be undone (focus restored); on success the
        handle is unregistered from tracking.
        """
        try:
            target = int(hwnd)
        except (TypeError, ValueError):
            return {
                "success": False,
                "app": app,
                "hwnd": hwnd,
                "previous_hwnd": None,
                "rolled_back": False,
                "error": f"Invalid window handle: {hwnd!r}.",
            }
        previous = self.get_foreground_hwnd()
        self._push_snapshot(app, target, previous)
        try:
            import ctypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        except Exception:
            return {
                "success": False,
                "app": app,
                "hwnd": target,
                "previous_hwnd": previous,
                "rolled_back": False,
                "error": (
                    "Window close requires ctypes user32 "
                    "(Windows only)."
                ),
            }
        try:
            # WM_CLOSE = 0x0010 — polite close request.
            posted = bool(user32.PostMessageW(target, 0x0010, 0, 0))
        except Exception as exc:
            rollback = self.rollback_last()
            return {
                "success": False,
                "app": app,
                "hwnd": target,
                "previous_hwnd": previous,
                "rolled_back": bool(rollback.get("rolled_back")),
                "error": str(exc),
            }
        if not posted:
            rollback = self.rollback_last()
            return {
                "success": False,
                "app": app,
                "hwnd": target,
                "previous_hwnd": previous,
                "rolled_back": bool(rollback.get("rolled_back")),
                "error": f"Failed to post WM_CLOSE to hwnd={target}.",
            }
        self.unregister_window(app, target)
        return {
            "success": True,
            "app": app,
            "hwnd": target,
            "previous_hwnd": previous,
            "rolled_back": False,
            "error": None,
        }

    def focus_window(
        self, hwnd: int, app: Optional[str] = None
    ) -> Dict[str, Any]:
        """Focus ``hwnd``, restoring prior focus on failure.

        The current foreground handle is snapshotted before
        ``SetForegroundWindow`` runs.  If the switch raises or the
        OS refuses it (falsy return), the previous foreground
        window is restored and the result reports
        ``rolled_back=True``.  On success the handle is registered
        under ``app`` when an app name is given.
        """
        try:
            target = int(hwnd)
        except (TypeError, ValueError):
            return {
                "success": False,
                "hwnd": hwnd,
                "previous_hwnd": None,
                "rolled_back": False,
                "error": f"Invalid window handle: {hwnd!r}.",
            }
        if target <= 0:
            return {
                "success": False,
                "hwnd": hwnd,
                "previous_hwnd": None,
                "rolled_back": False,
                "error": f"Invalid window handle: {hwnd!r}.",
            }

        try:
            import ctypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        except Exception:
            return {
                "success": False,
                "hwnd": target,
                "previous_hwnd": None,
                "rolled_back": False,
                "error": (
                    "Window focus requires ctypes user32 "
                    "(Windows only)."
                ),
            }

        previous = self.get_foreground_hwnd()
        self._push_snapshot(app, target, previous)
        try:
            switched = user32.SetForegroundWindow(target)
        except Exception as exc:
            # Auto-rollback: restore previous foreground from the
            # snapshot stack.
            rollback = self.rollback_last()
            rolled_back = bool(rollback.get("rolled_back"))
            return {
                "success": False,
                "hwnd": target,
                "previous_hwnd": previous,
                "rolled_back": rolled_back,
                "error": str(exc),
            }

        if not switched:
            # Auto-rollback: OS refused the switch — restore the
            # snapshotted foreground.
            rollback = self.rollback_last()
            rolled_back = bool(rollback.get("rolled_back"))
            return {
                "success": False,
                "hwnd": target,
                "previous_hwnd": previous,
                "rolled_back": rolled_back,
                "error": (
                    f"SetForegroundWindow refused to focus "
                    f"hwnd={target}."
                ),
            }

        if app is not None:
            self.register_window(app, target)
        return {
            "success": True,
            "hwnd": target,
            "previous_hwnd": previous,
            "rolled_back": False,
            "error": None,
        }


@dataclass
class ApplicationLifecycle:
    """
    Complete application lifecycle tracking.

    Combines the state machine with process intelligence
    for evidence-based state determination.
    """
    name: str
    state_machine: ApplicationStateMachine
    executable: Optional[str] = None
    process_id: Optional[int] = None
    window_title: Optional[str] = None
    window_handle: Optional[int] = None
    is_responsive: bool = True
    last_launch_attempt: Optional[datetime] = None
    last_close_attempt: Optional[datetime] = None
    launch_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def state(self) -> AppState:
        return self.state_machine.state

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "executable": self.executable,
            "state": self.state.value,
            "process_id": self.process_id,
            "window_title": self.window_title,
            "is_responsive": self.is_responsive,
            "launch_count": self.launch_count,
            "machine": self.state_machine.to_dict(),
            "metadata": dict(self.metadata),
        }
