"""
Genesis OS — Phase 6 Window Model.

One coherent window representation that tracks runtime state
through observation, not assumption.

WindowIdentity captures what Genesis knows about a real OS window.
WindowResolver discovers, caches, and re-validates windows at runtime.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)


class WindowState(str, Enum):
    """Observable window states."""
    DISCOVERED = "discovered"
    VISIBLE = "visible"
    FOCUSED = "focused"
    MINIMIZED = "minimized"
    MAXIMIZED = "maximized"
    HIDDEN = "hidden"
    DESTROYED = "destroyed"
    UNKNOWN = "unknown"


@dataclass
class WindowIdentity:
    """
    One coherent window representation.

    Fields are populated from actual OS observation,
    never assumed from previous commands.
    """
    hwnd: int
    title: str = ""
    pid: Optional[int] = None
    class_name: Optional[str] = None
    application: Optional[str] = None

    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0

    is_visible: bool = True
    is_foreground: bool = False
    is_minimized: bool = False
    is_maximized: bool = False
    is_enabled: bool = True

    uia_available: bool = False

    state: WindowState = WindowState.DISCOVERED

    observed_at: float = field(default_factory=time.monotonic)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def is_alive(self) -> bool:
        return self.state not in (
            WindowState.DESTROYED,
            WindowState.UNKNOWN,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "pid": self.pid,
            "class_name": self.class_name,
            "application": self.application,
            "bounds": {
                "left": self.left,
                "top": self.top,
                "right": self.right,
                "bottom": self.bottom,
                "width": self.width,
                "height": self.height,
            },
            "is_visible": self.is_visible,
            "is_foreground": self.is_foreground,
            "is_minimized": self.is_minimized,
            "is_maximized": self.is_maximized,
            "is_enabled": self.is_enabled,
            "uia_available": self.uia_available,
            "state": self.state.value,
            "observed_at": self.observed_at,
            "metadata": dict(self.metadata),
        }


# Unsafe window title patterns — shared between WindowResolver
# and RuntimeFocusResolver. Console/REPL/shell patterns, never
# application-specific names.
UNSAFE_TITLE_PATTERNS = (
    re.compile(r"\bcmd\.exe\b", re.IGNORECASE),
    re.compile(r"\bcommand\s+prompt\b", re.IGNORECASE),
    re.compile(r"\bpowershell\b", re.IGNORECASE),
    re.compile(r"\bpwsh\b", re.IGNORECASE),
    re.compile(r"\bwindows\s+terminal\b", re.IGNORECASE),
    re.compile(r"\bpython\s+", re.IGNORECASE),
    re.compile(r"\bipython\b", re.IGNORECASE),
    re.compile(r"\bjupyter\b", re.IGNORECASE),
    re.compile(r"\bconhost\b", re.IGNORECASE),
    re.compile(r"\bgenesis\s*os\b", re.IGNORECASE),
    re.compile(r"\bconsole\b", re.IGNORECASE),
    re.compile(r"^>\s*>>\s*", re.IGNORECASE),  # python REPL prompt
)

# Backward compatibility alias
_UNSAFE_TITLE_PATTERNS = UNSAFE_TITLE_PATTERNS


class WindowResolver:
    """
    Discovers and resolves real OS windows.

    Uses ctypes user32 for window enumeration and inspection.
    No assumption-based state — every field is observed.
    """

    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._user32: Any = None
        try:
            if sys.platform == "win32":
                import ctypes
                self._user32 = ctypes.windll.user32
        except Exception as exc:
            _log.debug("WindowResolver: user32 import failed: %s", exc)
            self._user32 = None

    @property
    def available(self) -> bool:
        return self._user32 is not None

    def enumerate_windows(self) -> List[WindowIdentity]:
        """Enumerate all visible top-level windows."""
        if not self.available:
            return []

        import ctypes
        import ctypes.wintypes

        results: List[WindowIdentity] = []

        EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.wintypes.HWND,
            ctypes.wintypes.LPARAM,
        )

        def callback(hwnd, _lparam):
            try:
                if not self._user32.IsWindowVisible(hwnd):
                    return True

                length = self._user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return True

                buf = (ctypes.c_wchar * (length + 1))()
                self._user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
                title = buf.value or ""

                if not title.strip():
                    return True

                rect = ctypes.wintypes.RECT()
                self._user32.GetWindowRect(hwnd, ctypes.byref(rect))

                pid = None
                try:
                    pdw_pid = ctypes.wintypes.DWORD(0)
                    self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pdw_pid))
                    pid = int(pdw_pid.value) or None
                except Exception as exc:
                    _log.debug("WindowResolver: GetWindowThreadProcessId failed for hwnd=%s: %s", hwnd, exc)

                class_name = ""
                try:
                    cn_buf = (ctypes.c_wchar * 256)()
                    self._user32.GetClassNameW(hwnd, cn_buf, 256)
                    class_name = cn_buf.value or ""
                except Exception as exc:
                    _log.debug("WindowResolver: GetClassNameW failed for hwnd=%s: %s", hwnd, exc)

                foreground_hwnd = 0
                try:
                    foreground_hwnd = int(self._user32.GetForegroundWindow() or 0)
                except Exception as exc:
                    _log.debug("WindowResolver: GetForegroundWindow failed: %s", exc)

                is_minimized = bool(self._user32.IsIconic(hwnd))
                is_maximized = bool(self._user32.IsZoomed(hwnd))

                win = WindowIdentity(
                    hwnd=hwnd,
                    title=title,
                    pid=pid,
                    class_name=class_name,
                    left=rect.left,
                    top=rect.top,
                    right=rect.right,
                    bottom=rect.bottom,
                    is_visible=True,
                    is_foreground=(hwnd == foreground_hwnd),
                    is_minimized=is_minimized,
                    is_maximized=is_maximized,
                    state=WindowState.FOCUSED if hwnd == foreground_hwnd else WindowState.VISIBLE,
                )
                results.append(win)
            except Exception as exc:
                _log.debug("WindowResolver: callback exception for hwnd=%s: %s", hwnd, exc)
            return True

        self._user32.EnumWindows(EnumWindowsProc(callback), 0)
        return results

    def find_window(
        self,
        pattern: str,
        *,
        timeout: float = 0.0,
        poll_interval: float = 0.2,
    ) -> Optional[WindowIdentity]:
        """
        Find a window matching a title pattern (regex).
        Optionally polls until timeout.
        """
        timeout = min(max(0.0, timeout), 60.0)
        deadline = time.monotonic() + timeout
        while True:
            windows = self.enumerate_windows()
            for win in windows:
                try:
                    if re.search(pattern, win.title, re.IGNORECASE):
                        return win
                except re.error:
                    if pattern.lower() in win.title.lower():
                        return win

            if time.monotonic() >= deadline:
                return None
            time.sleep(poll_interval)

    def find_by_hwnd(self, hwnd: int) -> Optional[WindowIdentity]:
        """Find a specific window by its HWND."""
        if not self.available or not hwnd:
            return None

        windows = self.enumerate_windows()
        for win in windows:
            if win.hwnd == hwnd:
                return win
        return None

    def get_foreground(self) -> Optional[WindowIdentity]:
        """Get the current foreground window."""
        if not self.available:
            return None

        try:
            hwnd = int(self._user32.GetForegroundWindow() or 0)
        except Exception:
            return None

        if not hwnd:
            return None

        return self.find_by_hwnd(hwnd)

    def is_safe_target(self, hwnd: int, title: str) -> Tuple[bool, Optional[str]]:
        """Check if a window is safe to dispatch GUI actions into."""
        if not hwnd:
            return False, "no window handle"
        if not title:
            return False, "window has no title"
        stripped = title.strip()
        if not stripped:
            return False, "window title is empty"
        for pattern in _UNSAFE_TITLE_PATTERNS:
            if pattern.search(stripped):
                return False, f"unsafe window: {stripped!r}"
        return True, None

    def verify_focus_retained(
        self,
        expected_hwnd: int,
        *,
        settle_seconds: float = 0.05,
    ) -> bool:
        """Re-inspect foreground window after dispatch."""
        if not self.available or not expected_hwnd:
            return False
        if settle_seconds > 0:
            time.sleep(settle_seconds)
        try:
            current = int(self._user32.GetForegroundWindow() or 0)
        except Exception:
            return False
        return current == expected_hwnd
