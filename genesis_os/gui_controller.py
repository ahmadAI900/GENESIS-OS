"""
Genesis OS — Level 3.14
GUI Controller Abstraction.

Safe, extensible abstraction for application GUI interaction.
Platform-specific logic is isolated behind provider interfaces;
the controller facade delegates to the active provider.

Provider hierarchy:

    GUIProvider (ABC)
        └── WindowsGUIProvider

The controller auto-detects the best available provider at
instantiation time, or accepts an explicit provider override.

Safety:

    - No keylogging: type_text and paste_text do not retain
      text beyond the immediate operation.
    - Window focus and inspection use the official Windows
      user32 API — no synthetic alt-tab, no shell hacks.
    - All provider methods return a standardized GUIActionResult
      so callers never need to inspect raw exceptions.
"""

from __future__ import annotations

import difflib
import enum
import re
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ============================================================
# WINDOW-TITLE NORMALIZATION (fuzzy-match second pass)
# ============================================================

_VERSION_NUMBER_RE = re.compile(r"\d+(?:\.\d+)+")

# Trailing " - <app>" / " — <app>" / " | <app>" style suffix.
# Only the LAST such segment is stripped, so
# "report - draft - chrome" normalizes to "report - draft".
_APP_SUFFIX_RE = re.compile(r"\s+[—–\-:|]\s*\S[^—–\-:|]*$")


def _normalize_title(title: Any) -> str:
    """Normalize a window title for fuzzy matching.

    Steps: lowercase, strip ``*`` modified markers (``*doc``,
    ``doc *``), remove version numbers (``1.2.3``), strip the
    trailing app suffix (`` - notepad``, `` - chrome``,
    `` — excel``), then collapse punctuation/whitespace.

    Examples::

        "Untitled - Notepad"      -> "untitled"
        "Report - Google Chrome"  -> "report"
        "Budget — Excel 16.0"     -> "budget excel"
        "*Draft - Word"           -> "draft"
    """
    s = str(title or "").lower().strip()
    if not s:
        return ""
    # Strip "*" modified markers (leading and trailing).
    s = re.sub(r"^\*+\s*", "", s)
    s = re.sub(r"\s*\*+\s*$", "", s)
    # Remove version numbers such as 1.2.3 / 10.0.19045.
    s = _VERSION_NUMBER_RE.sub(" ", s)
    # Strip the trailing app suffix (" - notepad", " — excel").
    s = _APP_SUFFIX_RE.sub("", s).strip()
    # Collapse punctuation/whitespace to single spaces.
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ============================================================
# GUI ACTION ENUM
# ============================================================

class GUIAction(enum.Enum):
    """
    Canonical set of GUI interaction actions.
    """

    focus_window = "focus_window"
    inspect_window = "inspect_window"
    click = "click"
    double_click = "double_click"
    type_text = "type_text"
    paste_text = "paste_text"
    read_visible_text = "read_visible_text"
    select_text = "select"
    scroll = "scroll"
    keyboard_action = "keyboard_action"
    hotkey = "hotkey"
    drag = "drag"
    wait_for_state = "wait_for_state"
    wait = "wait"
    wait_for_window = "wait_for_window"
    inspect_ui_tree = "inspect_ui_tree"


# ============================================================
# GUI ACTION RESULT
# ============================================================

@dataclass(frozen=True)
class GUIActionResult:
    """
    Standardized result for every GUI action.

    Follows the Genesis OS result contract:

        success   — whether the action completed as requested
        action    — which GUIAction was attempted
        target    — optional human-readable target description
        message   — human-readable summary
        data      — arbitrary structured payload
        metadata  — additional context (provider, timing, etc.)
        error     — error description when success is False
    """

    success: bool

    action: str

    target: Optional[str] = None

    message: str = ""

    data: Dict[str, Any] = field(default_factory=dict)

    metadata: Dict[str, Any] = field(default_factory=dict)

    error: Optional[str] = None

    # --------------------------------------------------------
    # FACTORY: SUCCESS
    # --------------------------------------------------------

    @classmethod
    def ok(
        cls,
        action: str,
        *,
        target: Optional[str] = None,
        message: str = "",
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GUIActionResult:
        return cls(
            success=True,
            action=action,
            target=target,
            message=message,
            data=data or {},
            metadata=metadata or {},
        )

    # --------------------------------------------------------
    # FACTORY: FAILURE
    # --------------------------------------------------------

    @classmethod
    def fail(
        cls,
        action: str,
        *,
        target: Optional[str] = None,
        message: str = "",
        error: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GUIActionResult:
        return cls(
            success=False,
            action=action,
            target=target,
            message=message,
            data=data or {},
            metadata=metadata or {},
            error=error,
        )

    # --------------------------------------------------------
    # SERIALIZATION
    # --------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "action": self.action,
            "target": self.target,
            "message": self.message,
            "data": dict(self.data),
            "metadata": dict(self.metadata),
            "error": self.error,
        }


# ============================================================
# ABSTRACT PROVIDER
# ============================================================

class GUIProvider(ABC):
    """
    Abstract interface that every platform-specific GUI provider
    must implement.  The controller facade delegates every action
    to the active provider.

    Providers must never raise — every method must return a
    GUIActionResult, even on failure.
    """

    @abstractmethod
    def focus_window(self, title_pattern: str) -> GUIActionResult:
        ...

    @abstractmethod
    def inspect_window(self, title_pattern: str) -> GUIActionResult:
        ...

    @abstractmethod
    def click(self, x: int, y: int) -> GUIActionResult:
        ...

    @abstractmethod
    def double_click(self, x: int, y: int) -> GUIActionResult:
        ...

    @abstractmethod
    def type_text(
        self,
        text: str,
        *,
        focus_title_pattern: Optional[str] = None,
        focus_timeout: float = 3.0,
        focus_poll_interval: float = 0.2,
    ) -> GUIActionResult:
        ...

    @abstractmethod
    def paste_text(
        self,
        text: str,
        *,
        focus_title_pattern: Optional[str] = None,
        focus_timeout: float = 3.0,
        focus_poll_interval: float = 0.2,
    ) -> GUIActionResult:
        ...

    @abstractmethod
    def read_visible_text(self) -> GUIActionResult:
        ...

    @abstractmethod
    def read_focused_text(self) -> GUIActionResult:
        """Read the text content of the currently focused UI element.

        Uses UIA ValuePattern or similar mechanisms to obtain the
        actual text value of the focused control for content verification.
        """
        ...

    @abstractmethod
    def select_text(self, start: int, end: int) -> GUIActionResult:
        ...

    @abstractmethod
    def scroll(self, direction: str, amount: int) -> GUIActionResult:
        ...

    @abstractmethod
    def keyboard_action(self, key: str) -> GUIActionResult:
        ...

    @abstractmethod
    def hotkey(self, keys: str) -> GUIActionResult:
        ...

    @abstractmethod
    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
    ) -> GUIActionResult:
        ...

    @abstractmethod
    def wait_for_state(
        self, condition: Callable[[], bool], timeout: float
    ) -> GUIActionResult:
        ...

    @abstractmethod
    def available(self) -> bool:
        ...

    def provider_health(self) -> Dict[str, Any]:
        return {"available": self.available()}


# ============================================================
# WINDOWS GUI PROVIDER
# ============================================================

class WindowsGUIProvider(GUIProvider):
    """
    Windows implementation of GUIProvider.

    Dependencies (all optional — provider degrades gracefully):

        pyautogui  — mouse and keyboard automation
        pyperclip  — clipboard read/write
        ctypes     — user32 window focus and enumeration

    Every public method wraps its work in a try/except and
    returns a GUIActionResult so the caller never sees raw
    exceptions.
    """

    VERSION = "3.14.0"

    def __init__(self) -> None:
        self._pyautogui: Any = None
        self._pyperclip: Any = None
        self._user32: Any = None
        # Rollback stack: foreground-hwnd snapshots pushed before
        # every destructive GUI op (type/paste/click) so a failed
        # op can restore the previous focus.  Bounded to 32
        # entries.  Accessed via getattr in helpers because some
        # tests construct the provider via __new__.
        self._rollback_stack: List[int] = []

        try:
            import pyautogui as _pyautogui  # noqa: F401
            _pyautogui.FAILSAFE = True
            self._pyautogui = _pyautogui
        except Exception:
            pass

        try:
            import pyperclip as _pyperclip  # noqa: F401
            self._pyperclip = _pyperclip
        except Exception:
            pass

        try:
            import ctypes as _ctypes
            self._user32 = _ctypes.windll.user32  # type: ignore[attr-defined]
        except Exception:
            pass

    def available(self) -> bool:
        return self._pyautogui is not None

    # --------------------------------------------------------
    # ROLLBACK STACK (foreground snapshots for destructive ops)
    # --------------------------------------------------------

    def _rollback_stack_for(self) -> List[int]:
        """Return the rollback stack, creating it if missing."""
        stack = getattr(self, "_rollback_stack", None)
        if stack is None:
            stack = []
            self._rollback_stack = stack
        return stack

    def _get_foreground_hwnd(self) -> Optional[int]:
        """Return the current foreground window handle, if obtainable."""
        try:
            if self._user32 is None:
                return None
            hwnd = self._user32.GetForegroundWindow()
            return int(hwnd) if hwnd else None
        except Exception:
            return None

    def _push_rollback_snapshot(self) -> Optional[int]:
        """Snapshot the foreground hwnd before a destructive GUI op."""
        hwnd = self._get_foreground_hwnd()
        if hwnd is not None:
            stack = self._rollback_stack_for()
            stack.append(hwnd)
            # Bound the stack so a long session cannot grow it
            # without limit.
            if len(stack) > 32:
                del stack[:-32]
        return hwnd

    def _discard_snapshot(self, snapshot: Optional[int]) -> None:
        """Drop a snapshot after its op succeeded (no rollback needed)."""
        try:
            stack = self._rollback_stack_for()
            if (
                snapshot is not None
                and stack
                and stack[-1] == snapshot
            ):
                stack.pop()
        except Exception:
            pass

    def _focus_hwnd(self, hwnd: int) -> bool:
        if not hwnd or self._user32 is None:
            return False
        try:
            if self._user32.IsIconic(hwnd):
                self._user32.ShowWindow(hwnd, 9)
        except Exception:
            pass
        try:
            if self._user32.SetForegroundWindow(hwnd):
                return True
        except Exception:
            pass
        try:
            foreground = int(self._user32.GetForegroundWindow() or 0)
            current_thread = int(self._user32.GetCurrentThreadId() or 0)
            target_thread = int(
                self._user32.GetWindowThreadProcessId(hwnd, None) or 0
            )
            foreground_thread = int(
                self._user32.GetWindowThreadProcessId(foreground, None) or 0
            ) if foreground else 0
            attached = []
            for thread_id in {target_thread, foreground_thread}:
                if thread_id and thread_id != current_thread:
                    self._user32.AttachThreadInput(
                        current_thread,
                        thread_id,
                        True,
                    )
                    attached.append(thread_id)
            try:
                self._user32.ShowWindow(hwnd, 9)
                self._user32.BringWindowToTop(hwnd)
                result = self._user32.SetForegroundWindow(hwnd)
                if not result:
                    self._user32.SetActiveWindow(hwnd)
                    self._user32.SetFocus(hwnd)
                    result = int(
                        self._user32.GetForegroundWindow() or 0
                    ) == hwnd
                return bool(result)
            finally:
                for thread_id in attached:
                    self._user32.AttachThreadInput(
                        current_thread,
                        thread_id,
                        False,
                    )
        except Exception:
            return False

    def _restore_foreground_hwnd(self, hwnd: Optional[int]) -> bool:
        """Restore a previously snapshotted foreground hwnd."""
        try:
            if hwnd and self._user32 is not None:
                self._user32.SetForegroundWindow(hwnd)
                return True
        except Exception:
            pass
        return False

    def _fail_with_rollback(
        self,
        action: str,
        snapshot: Optional[int],
        *,
        target: Optional[str] = None,
        message: str = "",
        error: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GUIActionResult:
        """Restore the snapshotted focus and return a failure result.

        Pops this op's snapshot, restores the previous foreground
        window, and reports ``rolled_back`` / ``rollback_hwnd`` in
        both data and metadata.
        """
        rolled_back = False
        if snapshot is not None:
            self._discard_snapshot(snapshot)
            rolled_back = self._restore_foreground_hwnd(snapshot)
        payload = dict(data or {})
        payload["rolled_back"] = rolled_back
        payload["rollback_hwnd"] = snapshot
        meta = dict(metadata or {})
        meta["rolled_back"] = rolled_back
        return GUIActionResult.fail(
            action,
            target=target,
            message=message,
            error=error,
            data=payload,
            metadata=meta,
        )

    # --------------------------------------------------------
    # POST-STATE VERIFICATION HELPERS (drag / hotkey)
    # --------------------------------------------------------

    def _get_cursor_pos(self) -> Optional[tuple]:
        """Return the current cursor position, if obtainable.

        Prefers Win32 GetCursorPos; falls back to
        ``pyautogui.position()``.  Returns ``None`` when neither
        source is available.
        """
        try:
            if self._user32 is not None:
                import ctypes
                import ctypes.wintypes

                pt = ctypes.wintypes.POINT()
                if self._user32.GetCursorPos(ctypes.byref(pt)):
                    return (int(pt.x), int(pt.y))
        except Exception:
            pass
        try:
            if self._pyautogui is not None:
                pos = self._pyautogui.position()
                return (int(pos[0]), int(pos[1]))
        except Exception:
            pass
        return None

    def _is_window_alive(self, hwnd: Optional[int]) -> Optional[bool]:
        """Return True if ``hwnd`` is a live window, False if dead.

        Returns ``None`` when liveness cannot be determined
        (Win32 unavailable).
        """
        if hwnd in (None, 0):
            return False
        try:
            if self._user32 is None:
                return None
            return bool(self._user32.IsWindow(int(hwnd)))
        except Exception:
            return None

    def _verify_foreground_retained(
        self, foreground_before: Optional[int]
    ) -> Dict[str, Any]:
        """Post-state check for hotkey/keyboard actions.

        Verifies the focused window is still alive and the
        foreground was retained.  When Win32 is unavailable the
        check is honestly reported as unverified
        (``verified=False``).
        """
        foreground_after = self._get_foreground_hwnd()
        alive: Optional[bool] = self._is_window_alive(
            foreground_after
        )
        retained = (
            foreground_before is not None
            and foreground_after is not None
            and foreground_before == foreground_after
        )
        if self._user32 is None or alive is None:
            verified = False
            note = "win32_unavailable"
        else:
            verified = bool(retained and alive)
            note = (
                "foreground_retained"
                if verified
                else "foreground_changed_or_dead"
            )
        return {
            "verified": verified,
            "foreground_before": foreground_before,
            "foreground_after": foreground_after,
            "foreground_retained": bool(retained),
            "window_alive": alive,
            "verification_note": note,
        }

    # --------------------------------------------------------
    # DEEP CONTENT VERIFICATION (UIA focused-text readback)
    # --------------------------------------------------------

    def _verify_content_via_focused_read(
        self,
        expected_text: str,
        previous_text: Optional[str] = None,
        baseline_available: bool = False,
    ) -> Dict[str, Any]:
        """Verify dispatched text by reading back the focused element.

        Uses ``read_focused_text()`` — the UIA ValuePattern /
        TextPattern observation when a UIA-backed provider is
        active — as the independent post-state check.  A substring
        match (``expected in actual``) counts as verified.

        When no readable content is available (pyautogui-only
        provider, blocked COM apartment, timeout) the dispatch is
        reported honestly as confirmed-but-unverified — never as
        verified.
        """
        expected_len = len(expected_text or "")

        try:
            time.sleep(0.3)
        except Exception:
            pass

        try:
            readback = self.read_focused_text()
        except Exception as exc:
            return {
                "verified": False,
                "content_match": False,
                "content_mismatch": False,
                "verification_note": (
                    "dispatch_confirmed_content_unverified"
                ),
                "expected_length": expected_len,
                "actual_length": 0,
                "truncated": False,
                "read_method": "none",
                "read_error": str(exc),
            }

        try:
            readable = bool(
                readback.success
                and readback.data.get("readable")
                and str(readback.data.get("method", "none")) in {
                    "value_pattern",
                    "text_pattern",
                }
            )
            method = str(
                readback.data.get("method", "none") or "none"
            )
        except Exception:
            readable = False
            method = "none"

        if not readable:
            return {
                "verified": False,
                "content_match": False,
                "content_mismatch": False,
                "verification_note": (
                    "dispatch_confirmed_content_unverified"
                ),
                "expected_length": expected_len,
                "actual_length": 0,
                "truncated": False,
                "read_method": method,
                "read_error": readback.error,
            }

        actual = ""
        try:
            actual = readback.data.get("text", "") or ""
        except Exception:
            actual = ""
        actual_len = len(actual)
        content_match = bool(
            expected_text
            and expected_text in actual
            and baseline_available
            and actual != previous_text
        )
        truncated = (
            actual_len < (expected_len * 0.9)
            if expected_len
            else False
        )

        if content_match:
            return {
                "verified": True,
                "content_match": True,
                "post_state_matches": True,
                "content_mismatch": False,
                "verification_note": "content_verified",
                "expected_length": expected_len,
                "actual_length": actual_len,
                "truncated": truncated,
                "read_method": method,
                # Sliced: never retain more than a preview.
                "observed_text": actual[:200],
            }

        return {
            "verified": False,
            "content_match": False,
            "content_mismatch": True,
            "verification_note": (
                "dispatch_confirmed_content_mismatch"
            ),
            "expected_length": expected_len,
            "actual_length": actual_len,
            "truncated": truncated,
            "read_method": method,
            # Sliced: never retain more than a preview.
            "observed_text": actual[:200],
        }

    # --------------------------------------------------------
    # WINDOW FOCUS
    # --------------------------------------------------------

    def focus_window(
        self,
        title_pattern: str,
        *,
        timeout: float = 3.0,
        poll_interval: float = 0.2,
    ) -> GUIActionResult:
        action = GUIAction.focus_window.value

        if self._user32 is None:
            return GUIActionResult.fail(
                action,
                error=(
                    "Window focus requires ctypes user32 "
                    "(Windows only)."
                ),
            )

        timeout = min(max(0.0, float(timeout or 0.0)), 30.0)
        poll_interval = max(0.05, float(poll_interval or 0.2))

        deadline = time.monotonic() + timeout
        hwnd: Optional[int] = None
        polls = 0
        last_title = ""
        fuzzy_match = False
        match_ratio = 0.0
        normalized_match = False

        while True:
            polls += 1
            try:
                hwnd = self._find_window(title_pattern)
                if hwnd is not None:
                    last_title = self._get_window_title(hwnd)
            except Exception as exc:
                return GUIActionResult.fail(
                    action,
                    target=title_pattern,
                    error=str(exc),
                )

            if hwnd is not None:
                live_title = self._get_window_title(hwnd)
                if live_title:
                    last_title = live_title
                break

            if time.monotonic() >= deadline:
                break

            time.sleep(poll_interval)

        if hwnd is None:
            return GUIActionResult.fail(
                action,
                target=title_pattern,
                error=(
                    f"No window matching '{title_pattern}' "
                    f"appeared within {timeout}s "
                    f"({polls} poll(s))."
                ),
                data={"polls": polls, "timeout": timeout},
            )

        previous_hwnd = self._get_foreground_hwnd()
        try:
            switched = self._focus_hwnd(hwnd)
        except Exception as exc:
            rolled_back = (
                self._restore_foreground_hwnd(previous_hwnd)
                if previous_hwnd not in (None, hwnd)
                else False
            )
            return GUIActionResult.fail(
                action,
                target=title_pattern,
                error=str(exc),
                data={
                    "hwnd": hwnd,
                    "polls": polls,
                    "title": last_title,
                    "previous_hwnd": previous_hwnd,
                    "rolled_back": rolled_back,
                },
                metadata={"rolled_back": rolled_back},
            )

        if not switched:
            rolled_back = (
                self._restore_foreground_hwnd(previous_hwnd)
                if previous_hwnd not in (None, hwnd)
                else False
            )
            return GUIActionResult.fail(
                action,
                target=title_pattern,
                error=(
                    f"SetForegroundWindow refused to focus "
                    f"hwnd={hwnd} ('{last_title}')."
                ),
                data={
                    "hwnd": hwnd,
                    "polls": polls,
                    "title": last_title,
                    "previous_hwnd": previous_hwnd,
                    "rolled_back": rolled_back,
                },
                metadata={"rolled_back": rolled_back},
            )

        print(
            f"[gui] focus_window: matched '{title_pattern}' "
            f"after {polls} poll(s); hwnd={hwnd} title='{last_title}'"
        )

        return GUIActionResult.ok(
            action,
            target=title_pattern,
            message=(
                f"Focused window matching '{title_pattern}'."
            ),
            data={
                "hwnd": hwnd,
                "title": last_title,
                "polls": polls,
                "timeout": timeout,
                "fuzzy_match": bool(fuzzy_match),
                "match_ratio": float(match_ratio),
                "normalized_match": bool(normalized_match),
            },
            metadata={
                "fuzzy_match": bool(fuzzy_match),
                "match_ratio": float(match_ratio),
                "normalized_match": bool(normalized_match),
            },
        )

    # --------------------------------------------------------
    # WINDOW INSPECTION
    # --------------------------------------------------------

    def inspect_window(self, title_pattern: str) -> GUIActionResult:
        action = GUIAction.inspect_window.value

        if self._user32 is None:
            return GUIActionResult.fail(
                action,
                error=(
                    "Window inspection requires ctypes user32 "
                    "(Windows only)."
                ),
            )

        try:
            hwnd = self._find_window(title_pattern)

            if hwnd is None:
                return GUIActionResult.fail(
                    action,
                    target=title_pattern,
                    error=f"No window matching '{title_pattern}'.",
                )

            length = self._user32.GetWindowTextLengthW(hwnd)
            buf = (length + 1) * __import__("ctypes").c_wchar
            self._user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value or ""

            rect = __import__("ctypes").c_long * 4
            r = rect()
            self._user32.GetWindowRect(hwnd, r)

            return GUIActionResult.ok(
                action,
                target=title_pattern,
                message=f"Inspected window '{title}'.",
                data={
                    "hwnd": hwnd,
                    "title": title,
                    "rect": {
                        "left": r[0],
                        "top": r[1],
                        "right": r[2],
                        "bottom": r[3],
                    },
                },
            )

        except Exception as exc:
            return GUIActionResult.fail(
                action,
                target=title_pattern,
                error=str(exc),
            )

    # --------------------------------------------------------
    # MOUSE: CLICK
    # --------------------------------------------------------

    def click(self, x: int, y: int) -> GUIActionResult:
        action = GUIAction.click.value

        if self._pyautogui is None:
            return GUIActionResult.fail(
                action,
                error="Mouse control requires pyautogui.",
            )

        snapshot = self._push_rollback_snapshot()
        try:
            self._pyautogui.click(x, y)
            self._discard_snapshot(snapshot)

            return GUIActionResult.ok(
                action,
                target=f"({x}, {y})",
                message=f"Clicked at ({x}, {y}).",
                data={
                    "x": x,
                    "y": y,
                    "verified": False,
                    "verification_type": "dispatch_only",
                    "verification_reason": "No UI state readback is available for coordinate clicks.",
                },
            )

        except Exception as exc:
            return self._fail_with_rollback(
                action,
                snapshot,
                target=f"({x}, {y})",
                error=str(exc),
            )

    # --------------------------------------------------------
    # MOUSE: DOUBLE CLICK
    # --------------------------------------------------------

    def double_click(self, x: int, y: int) -> GUIActionResult:
        action = GUIAction.double_click.value

        if self._pyautogui is None:
            return GUIActionResult.fail(
                action,
                error="Mouse control requires pyautogui.",
            )

        snapshot = self._push_rollback_snapshot()
        try:
            self._pyautogui.doubleClick(x, y)
            self._discard_snapshot(snapshot)

            return GUIActionResult.ok(
                action,
                target=f"({x}, {y})",
                message=f"Double-clicked at ({x}, {y}).",
                data={
                    "x": x,
                    "y": y,
                    "verified": False,
                    "verification_type": "dispatch_only",
                    "verification_reason": "No UI state readback is available for coordinate double-clicks.",
                },
            )

        except Exception as exc:
            return self._fail_with_rollback(
                action,
                snapshot,
                target=f"({x}, {y})",
                error=str(exc),
            )

    # --------------------------------------------------------
    # TEXT: TYPE
    # --------------------------------------------------------

    def type_text(
        self,
        text: str,
        *,
        focus_title_pattern: Optional[str] = None,
        focus_timeout: float = 3.0,
        focus_poll_interval: float = 0.2,
    ) -> GUIActionResult:
        action = GUIAction.type_text.value

        if self._pyautogui is None:
            return GUIActionResult.fail(
                action,
                error="Typing requires pyautogui.",
            )

        if not isinstance(text, str) or not text:
            return GUIActionResult.fail(
                action,
                error="No text provided.",
            )

        focus_metadata: Dict[str, Any] = {}

        if focus_title_pattern:
            focus_result = self.focus_window(
                focus_title_pattern,
                timeout=focus_timeout,
                poll_interval=focus_poll_interval,
            )
            focus_metadata = {
                "focus_title_pattern": focus_title_pattern,
                "focus_attempted": True,
                "focus_success": focus_result.success,
                "focus_hwnd": (
                    focus_result.data.get("hwnd")
                    if focus_result.success else None
                ),
                "focus_title": (
                    focus_result.data.get("title")
                    if focus_result.success else None
                ),
                "focus_polls": (
                    focus_result.data.get("polls")
                    if focus_result.success else None
                ),
                "focus_error": focus_result.error,
            }

            if not focus_result.success:
                return GUIActionResult.fail(
                    action,
                    target=focus_title_pattern,
                    message=(
                        f"Could not focus window matching "
                        f"'{focus_title_pattern}' before typing."
                    ),
                    error=focus_result.error,
                    data={"length": len(text)},
                    metadata=focus_metadata,
                )
        else:
            focus_metadata = {"focus_attempted": False}

        baseline = self.read_focused_text()
        previous_text = None
        baseline_available = False
        if baseline.success and baseline.data.get("readable"):
            method = str(baseline.data.get("method", "none"))
            if method in {"value_pattern", "text_pattern"}:
                previous_text = str(baseline.data.get("text", ""))
                baseline_available = True

        snapshot = self._push_rollback_snapshot()
        try:
            print(
                f"[gui] type_text: focused hwnd="
                f"{focus_metadata.get('focus_hwnd')} "
                f"title='{focus_metadata.get('focus_title')}' "
                f"-> typing {len(text)} char(s): <redacted>"
            )

            self._pyautogui.typewrite(text, interval=0.02)

        except Exception as exc:
            return self._fail_with_rollback(
                action,
                snapshot,
                error=str(exc),
                metadata=focus_metadata,
            )

        # Deep content verification: read back the focused
        # element via read_focused_text() (UIA ValuePattern when
        # a UIA-backed provider is active) and confirm the
        # dispatched text actually landed.  Without a readable
        # UIA signal the dispatch is reported honestly as
        # confirmed-but-unverified — never as verified.
        verification = self._verify_content_via_focused_read(
            text,
            previous_text=previous_text,
            baseline_available=baseline_available,
        )
        self._discard_snapshot(snapshot)

        verified = bool(verification.get("verified"))
        method = str(verification.get("read_method", "none"))
        metadata = dict(focus_metadata)
        metadata.update(
            {
                "verification_note": verification.get(
                    "verification_note"
                ),
                "verification_type": "focused_content_readback",
                "read_method": method,
                "truncated": bool(
                    verification.get("truncated", False)
                ),
            }
        )
        data: Dict[str, Any] = {
            "length": len(text),
            "verified": verified,
            "content_match": bool(
                verification.get("content_match", False)
            ),
            "content_mismatch": bool(
                verification.get("content_mismatch", False)
            ),
            "expected_length": verification.get(
                "expected_length", len(text)
            ),
            "actual_length": verification.get(
                "actual_length", 0
            ),
            "truncated": bool(
                verification.get("truncated", False)
            ),
        }
        if verification.get("observed_text") is not None:
            data["observed_text"] = verification["observed_text"]

        if verified:
            message = (
                f"Typed {len(text)} character(s); content "
                f"verified via {method}."
            )
        elif verification.get("content_mismatch"):
            message = (
                f"Typed {len(text)} character(s) but content "
                f"readback did not match "
                f"({data['actual_length']}/"
                f"{data['expected_length']} chars via {method})."
            )
        else:
            message = (
                f"Typed {len(text)} character(s); dispatch "
                f"confirmed, content unverified "
                f"(UIA readback unavailable)."
            )

        return GUIActionResult.ok(
            action,
            message=message,
            data=data,
            metadata=metadata,
        )

    # --------------------------------------------------------
    # TEXT: PASTE (clipboard)
    # --------------------------------------------------------

    def paste_text(
        self,
        text: str,
        *,
        focus_title_pattern: Optional[str] = None,
        focus_timeout: float = 3.0,
        focus_poll_interval: float = 0.2,
    ) -> GUIActionResult:
        action = GUIAction.paste_text.value

        if focus_title_pattern:
            focus_result = self.focus_window(focus_title_pattern)
            if not focus_result.success:
                return focus_result

        if self._pyperclip is None:
            return GUIActionResult.fail(
                action,
                error="Clipboard paste requires pyperclip.",
            )

        if not isinstance(text, str) or not text:
            return GUIActionResult.fail(
                action,
                error="No text provided.",
            )

        baseline = self.read_focused_text()
        previous_text = None
        baseline_available = False
        if baseline.success and baseline.data.get("readable"):
            method = str(baseline.data.get("method", "none"))
            if method in {"value_pattern", "text_pattern"}:
                previous_text = str(baseline.data.get("text", ""))
                baseline_available = True

        snapshot = self._push_rollback_snapshot()
        try:
            self._pyperclip.copy(text)

            if self._pyautogui is not None:
                self._pyautogui.hotkey("ctrl", "v")

            clipboard_readback = self._pyperclip.paste()
            clipboard_verified = clipboard_readback == text

        except Exception as exc:
            return self._fail_with_rollback(
                action,
                snapshot,
                error=str(exc),
            )

        # Deep content verification: read back the focused
        # element via read_focused_text() (UIA ValuePattern when
        # a UIA-backed provider is active) and confirm the pasted
        # text actually landed.  The clipboard readback above only
        # proves the clipboard round-tripped — without a readable
        # UIA signal the paste is reported honestly as
        # confirmed-but-unverified.  Observed text is sliced so
        # the provider never retains more than a preview.
        verification = self._verify_content_via_focused_read(
            text,
            previous_text=previous_text,
            baseline_available=baseline_available,
        )
        self._discard_snapshot(snapshot)

        verified = bool(verification.get("verified"))
        method = str(verification.get("read_method", "none"))
        data = {
            "length": len(text),
            "verified": verified,
            "content_match": bool(
                verification.get("content_match", False)
            ),
            "content_mismatch": bool(
                verification.get("content_mismatch", False)
            ),
            "expected_length": verification.get(
                "expected_length", len(text)
            ),
            "actual_length": verification.get(
                "actual_length", 0
            ),
            "truncated": bool(
                verification.get("truncated", False)
            ),
            "clipboard_verified": clipboard_verified,
        }
        if verification.get("observed_text") is not None:
            data["observed_text"] = verification["observed_text"]
        metadata = {
            "verification_note": verification.get(
                "verification_note"
            ),
            "verification_type": "focused_content_readback",
            "read_method": method,
            "truncated": bool(
                verification.get("truncated", False)
            ),
            "clipboard_verified": clipboard_verified,
        }

        if verified:
            message = (
                f"Pasted {len(text)} character(s); content "
                f"verified via {method}."
            )
        elif verification.get("content_mismatch"):
            message = (
                f"Pasted {len(text)} character(s) but content "
                f"readback did not match "
                f"({data['actual_length']}/"
                f"{data['expected_length']} chars via {method})."
            )
        else:
            message = (
                f"Pasted {len(text)} character(s); dispatch "
                f"confirmed, content unverified "
                f"(UIA readback unavailable)."
            )

        return GUIActionResult.ok(
            action,
            message=message,
            data=data,
            metadata=metadata,
        )

    # --------------------------------------------------------
    # TEXT: READ VISIBLE
    # --------------------------------------------------------

    def read_visible_text(self) -> GUIActionResult:
        action = GUIAction.read_visible_text.value

        try:
            import ctypes
            import ctypes.wintypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()

            length = user32.GetWindowTextLengthW(hwnd)
            buf = (length + 1) * ctypes.c_wchar
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value or ""

            return GUIActionResult.ok(
                action,
                message=f"Read foreground window title: '{title}'.",
                data={
                    "window_title": title,
                    "hwnd": hwnd,
                    "note": (
                        "Full OCR-based visible text extraction "
                        "is not yet implemented."
                    ),
                },
            )

        except Exception as exc:
            return GUIActionResult.fail(
                action,
                error=str(exc),
            )

    # --------------------------------------------------------
    # TEXT: READ FOCUSED ELEMENT
    # --------------------------------------------------------

    def read_focused_text(self) -> GUIActionResult:
        """Read the text content of the currently focused UI element.

        The WindowsGUIProvider (pyautogui-based) does not have direct
        access to UIA. It reads the foreground window title as the
        best available signal. For actual element content reading,
        use the UIAutomationProvider which has ValuePattern access.

        Win32 calls are wrapped in a ThreadPoolExecutor with a hard
        timeout so that a blocked window (e.g. caused by an
        unexpected modal dialog) never produces an unbounded hang.
        """
        action = "read_focused_text"

        def _read_title() -> Dict[str, Any]:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return {"hwnd": 0, "title": "", "error": "No foreground window."}

            length = user32.GetWindowTextLengthW(hwnd)
            buf = (ctypes.c_wchar * (length + 1))()
            user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
            title = buf.value or ""
            return {"hwnd": hwnd, "title": title, "error": ""}

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_read_title)
                result = future.result(timeout=5.0)
        except FuturesTimeoutError:
            return GUIActionResult.fail(
                action,
                error=(
                    "read_focused_text timed out after 5s "
                    "(possible blocked window from modal dialog)."
                ),
                data={
                    "text": "",
                    "readable": False,
                    "method": "timeout",
                    "hwnd": 0,
                    "title": "",
                    "element_name": "",
                },
            )
        except Exception as exc:
            return GUIActionResult.fail(action, error=str(exc))

        if result.get("error"):
            return GUIActionResult.fail(action, error=result["error"])

        return GUIActionResult.ok(
            action,
            message=(
                "WindowsGUIProvider cannot read element content; "
                "only window title available."
            ),
            data={
                "text": "",
                "readable": False,
                "method": "window_title_only",
                "hwnd": result["hwnd"],
                "title": result["title"],
                "element_name": "",
            },
        )

    # --------------------------------------------------------
    # TEXT: SELECT
    # --------------------------------------------------------

    def select_text(self, start: int, end: int) -> GUIActionResult:
        action = GUIAction.select_text.value

        if self._pyautogui is None:
            return GUIActionResult.fail(
                action,
                error="Text selection requires pyautogui.",
            )

        try:
            self._pyautogui.hotkey("ctrl", "home")

            for _ in range(start):
                self._pyautogui.press("right")

            self._pyautogui.keyDown("shift")
            for _ in range(end - start):
                self._pyautogui.press("right")
            self._pyautogui.keyUp("shift")

            return GUIActionResult.ok(
                action,
                target=f"[{start}:{end}]",
                message=f"Selected characters {start} to {end}.",
                data={
                    "start": start,
                    "end": end,
                    "verified": False,
                    "verification_type": "dispatch_only",
                    "verification_reason": "Selection state was not independently read back.",
                },
            )

        except Exception as exc:
            return GUIActionResult.fail(
                action,
                target=f"[{start}:{end}]",
                error=str(exc),
            )

    # --------------------------------------------------------
    # SCROLL
    # --------------------------------------------------------

    def scroll(self, direction: str, amount: int) -> GUIActionResult:
        action = GUIAction.scroll.value

        if self._pyautogui is None:
            return GUIActionResult.fail(
                action,
                error="Scrolling requires pyautogui.",
            )

        normalized = str(direction or "").strip().lower()

        if normalized not in ("up", "down"):
            return GUIActionResult.fail(
                action,
                error="Direction must be 'up' or 'down'.",
            )

        amount = max(1, min(int(amount or 3), 50))

        try:
            clicks = amount if normalized == "up" else -amount
            self._pyautogui.scroll(clicks)

            return GUIActionResult.ok(
                action,
                target=normalized,
                message=f"Scrolled {normalized} {amount} notch(es).",
                data={
                    "direction": normalized,
                    "amount": amount,
                    "verified": False,
                    "verification_type": "dispatch_only",
                    "verification_reason": "Scroll position was not independently read back.",
                },
            )

        except Exception as exc:
            return GUIActionResult.fail(
                action,
                target=normalized,
                error=str(exc),
            )

    # --------------------------------------------------------
    # KEYBOARD
    # --------------------------------------------------------

    def keyboard_action(self, key: str) -> GUIActionResult:
        action = GUIAction.keyboard_action.value

        if self._pyautogui is None:
            return GUIActionResult.fail(
                action,
                error="Keyboard control requires pyautogui.",
            )

        if not isinstance(key, str) or not key.strip():
            return GUIActionResult.fail(
                action,
                error="No key specified.",
            )

        try:
            normalized = key.strip().lower()

            foreground_before = self._get_foreground_hwnd()
            if "+" in normalized:
                parts = [p.strip() for p in normalized.split("+")]
                self._pyautogui.hotkey(*parts)
            else:
                self._pyautogui.press(normalized)

            post = self._verify_foreground_retained(
                foreground_before
            )
            verified = False

            return GUIActionResult.ok(
                action,
                target=key,
                message=f"Sent key '{key}'.",
                data={
                    "key": key,
                    "verified": verified,
                    "verification_type": "dispatch_only",
                    "verification_reason": "Foreground retention is not keyboard-state verification.",
                    "post_state": post,
                },
                metadata={"verified": verified},
            )

        except Exception as exc:
            return GUIActionResult.fail(
                action,
                target=key,
                error=str(exc),
            )

    # --------------------------------------------------------
    # HOTKEY
    # --------------------------------------------------------

    def hotkey(self, keys: str) -> GUIActionResult:
        action = GUIAction.hotkey.value

        if self._pyautogui is None:
            return GUIActionResult.fail(
                action,
                error="Hotkey requires pyautogui.",
            )

        if not isinstance(keys, str) or not keys.strip():
            return GUIActionResult.fail(
                action,
                error="No keys specified.",
            )

        try:
            from genesis_os.ui_target_models import normalize_hotkey
            normalized = normalize_hotkey(keys)
            foreground_before = self._get_foreground_hwnd()
            self._pyautogui.hotkey(*normalized)

            post = self._verify_foreground_retained(
                foreground_before
            )
            verified = False

            return GUIActionResult.ok(
                action,
                target=keys,
                message=f"Sent hotkey '{keys}'.",
                data={
                    "keys": keys,
                    "normalized": normalized,
                    "verified": verified,
                    "verification_type": "dispatch_only",
                    "verification_reason": "Foreground retention is not hotkey-state verification.",
                    "post_state": post,
                },
                metadata={"verified": verified},
            )

        except Exception as exc:
            return GUIActionResult.fail(
                action,
                target=keys,
                error=str(exc),
            )

    # --------------------------------------------------------
    # DRAG
    # --------------------------------------------------------

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
    ) -> GUIActionResult:
        action = GUIAction.drag.value

        if self._pyautogui is None:
            return GUIActionResult.fail(
                action,
                error="Drag requires pyautogui.",
            )

        try:
            duration = max(0.1, min(float(duration or 0.5), 5.0))
            cursor_before = self._get_cursor_pos()
            self._pyautogui.moveTo(start_x, start_y)
            self._pyautogui.drag(
                end_x - start_x,
                end_y - start_y,
                duration=duration,
            )

            cursor_after = self._get_cursor_pos()
            if cursor_before is None or cursor_after is None:
                moved = False
                verified = False
                note = "cursor_position_unavailable"
            else:
                moved = bool(cursor_before != cursor_after)
                verified = False
                note = (
                    "cursor_moved_without_drop_verification"
                    if moved
                    else "cursor_unmoved"
                )
            post_state = {
                "cursor_before": cursor_before,
                "cursor_after": cursor_after,
                "moved": bool(moved),
                "verification_note": note,
            }

            return GUIActionResult.ok(
                action,
                target=f"({start_x},{start_y})->({end_x},{end_y})",
                message=f"Dragged from ({start_x},{start_y}) to ({end_x},{end_y}).",
                data={
                    "start_x": start_x,
                    "start_y": start_y,
                    "end_x": end_x,
                    "end_y": end_y,
                    "duration": duration,
                    "verified": verified,
                    "verification_type": "dispatch_only",
                    "verification_reason": "Cursor movement does not prove a successful drop.",
                    "moved": bool(moved),
                    "post_state": post_state,
                },
                metadata={"verified": verified},
            )

        except Exception as exc:
            return GUIActionResult.fail(
                action,
                target=f"({start_x},{start_y})->({end_x},{end_y})",
                error=str(exc),
            )

    def wait(self, seconds: float = 1.0) -> GUIActionResult:
        duration = max(0.0, min(float(seconds or 0.0), 120.0))
        time.sleep(duration)
        return GUIActionResult.ok(
            GUIAction.wait.value,
            message=f"Waited {duration:.3f} seconds.",
            data={"seconds": duration, "verified": True, "post_state_matches": True},
        )

    # --------------------------------------------------------
    # WAIT FOR STATE
    # --------------------------------------------------------

    def wait_for_state(
        self, condition: Callable[[], bool], timeout: float
    ) -> GUIActionResult:
        action = GUIAction.wait_for_state.value

        if not callable(condition):
            return GUIActionResult.fail(
                action,
                error="Condition must be callable.",
            )

        timeout = max(0.0, min(float(timeout or 10.0), 120.0))
        deadline = time.monotonic() + timeout
        polls = 0

        try:
            while time.monotonic() < deadline:
                if condition():
                    return GUIActionResult.ok(
                        action,
                        message=(
                            f"Condition met after "
                            f"{polls} poll(s)."
                        ),
                        data={
                            "polls": polls,
                            "elapsed": round(
                                timeout
                                - (deadline - time.monotonic()),
                                3,
                            ),
                        },
                    )
                time.sleep(0.2)
                polls += 1

            return GUIActionResult.fail(
                action,
                error=(
                    f"Timed out after {timeout}s "
                    f"({polls} polls)."
                ),
                data={"polls": polls, "timeout": timeout},
            )

        except Exception as exc:
            return GUIActionResult.fail(
                action,
                error=str(exc),
            )

    # --------------------------------------------------------
    # INTERNAL: FIND WINDOW BY TITLE
    # --------------------------------------------------------

    def _enumerate_window_titles(self) -> List[tuple]:
        """Enumerate real visible top-level windows via EnumWindows.

        Returns a list of ``(hwnd, title)`` tuples.  Only real
        EnumWindows results are ever returned — handles are never
        invented.  Returns ``[]`` when user32 is unavailable.
        """
        if self._user32 is None:
            return []

        import ctypes
        import ctypes.wintypes

        collected: List[tuple] = []

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
                self._user32.GetWindowTextW(
                    hwnd, ctypes.byref(buf), length + 1
                )
                title = buf.value or ""
                if title:
                    collected.append((int(hwnd), title))
            except Exception:
                pass
            return True

        try:
            self._user32.EnumWindows(
                EnumWindowsProc(callback), 0
            )
        except Exception:
            return collected

        return collected

    def _find_window_with_meta(
        self, title_pattern: str
    ) -> tuple:
        """Locate a window, falling back to fuzzy title matching.

        Pass 1: exact/regex (``re.search`` case-insensitive) over
        real EnumWindows titles — first match wins.
        Pass 2: difflib.SequenceMatcher fallback scoring
        ``ratio(lower(pattern), lower(title))`` over the same real
        window list; the best candidate with ratio >= 0.6 wins.
        Pass 3: normalized difflib fallback scoring
        ``ratio(_normalize_title(pattern),
        _normalize_title(title))``; the best candidate with
        ratio >= 0.6 wins.

        Returns ``(hwnd_or_None, fuzzy_match_bool, match_ratio,
        matched_title)``.  Handles are only ever real EnumWindows
        results — never invented.  See
        ``_find_window_with_normalized_meta`` for the variant that
        additionally reports whether the normalized pass won.
        """
        hwnd, fuzzy, ratio, title, _normalized = (
            self._find_window_with_normalized_meta(title_pattern)
        )
        return (hwnd, fuzzy, ratio, title)

    @staticmethod
    def _normalize_title(title: Any) -> str:
        """Normalize a window title (see module ``_normalize_title``)."""
        return _normalize_title(title)

    def _find_window_with_normalized_meta(
        self, title_pattern: str
    ) -> tuple:
        """Locate a window with raw + normalized fuzzy fallbacks.

        Pass 1 (raw): exact/regex first, then difflib ratio on the
        raw titles.  Pass 2 (normalized): difflib ratio on
        ``_normalize_title`` applied to BOTH the pattern and each
        candidate title.  Both fuzzy passes use threshold 0.6.

        Returns ``(hwnd_or_None, fuzzy_match_bool, match_ratio,
        matched_title, normalized_match_bool)`` where
        ``normalized_match_bool`` is True only when the
        normalized second pass won.
        """
        windows = self._enumerate_window_titles()
        if not windows:
            return (None, False, 0.0, "", False)

        pattern = str(title_pattern or "")

        # Pass 1a: exact / regex match on raw titles.
        for hwnd, title in windows:
            try:
                if re.search(pattern, title, re.IGNORECASE):
                    return (hwnd, False, 1.0, title, False)
            except re.error:
                # Invalid regex → plain case-insensitive
                # substring fallback for pass 1.
                if pattern.lower() in title.lower():
                    return (hwnd, False, 1.0, title, False)
            except Exception:
                continue

        # Pass 1b: fuzzy fallback on raw titles via
        # difflib.SequenceMatcher.
        lowered_pattern = pattern.lower()
        best_hwnd: Optional[int] = None
        best_ratio = 0.0
        best_title = ""
        for hwnd, title in windows:
            try:
                ratio = difflib.SequenceMatcher(
                    None, lowered_pattern, title.lower()
                ).ratio()
            except Exception:
                continue
            if ratio > best_ratio:
                best_ratio = ratio
                best_hwnd = hwnd
                best_title = title

        if best_hwnd is not None and best_ratio >= 0.6:
            return (best_hwnd, True, round(float(best_ratio), 4), best_title, False)

        # Pass 2: fuzzy fallback on NORMALIZED titles (both sides).
        normalized_pattern = _normalize_title(pattern)
        if normalized_pattern:
            best_hwnd = None
            best_ratio = 0.0
            best_title = ""
            for hwnd, title in windows:
                try:
                    ratio = difflib.SequenceMatcher(
                        None,
                        normalized_pattern,
                        _normalize_title(title),
                    ).ratio()
                except Exception:
                    continue
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_hwnd = hwnd
                    best_title = title

            if best_hwnd is not None and best_ratio >= 0.6:
                return (
                    best_hwnd,
                    True,
                    round(float(best_ratio), 4),
                    best_title,
                    True,
                )

        return (None, False, 0.0, "", False)

    def _find_window(self, title_pattern: str) -> Optional[int]:
        """
        Locate a top-level window whose title matches the given
        pattern (substring or regex, with difflib fuzzy fallback).
        """

        hwnd, _fuzzy, _ratio, _title = self._find_window_with_meta(
            title_pattern
        )
        return hwnd

    def _get_window_title(self, hwnd: int) -> str:
        """Read the title of a known top-level window handle."""
        if self._user32 is None:
            return ""

        try:
            length = self._user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return ""

            import ctypes
            buf = (ctypes.c_wchar * (length + 1))()
            self._user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
            return buf.value or ""
        except Exception:
            return ""

    # --------------------------------------------------------
    # WAIT FOR WINDOW
    # --------------------------------------------------------

    def wait_for_window(
        self,
        title_pattern: str,
        *,
        timeout: float = 3.0,
        poll_interval: float = 0.2,
    ) -> GUIActionResult:
        """Poll for a window matching ``title_pattern`` to exist.

        Useful when a freshly-launched application's window may
        not yet have been created at the instant ``application.open``
        returns. Returns a successful ``GUIActionResult`` containing
        ``{hwnd, title}`` once a match is found; returns a failure
        result if the timeout elapses without a match.
        """
        action = "wait_for_window"

        if self._user32 is None:
            return GUIActionResult.fail(
                action,
                error=(
                    "Window polling requires ctypes user32 "
                    "(Windows only)."
                ),
            )

        timeout = max(0.0, float(timeout or 0.0))
        poll_interval = max(0.05, float(poll_interval or 0.2))

        deadline = time.monotonic() + timeout
        polls = 0
        hwnd: Optional[int] = None

        while True:
            polls += 1
            try:
                hwnd = self._find_window(title_pattern)
            except Exception as exc:
                return GUIActionResult.fail(
                    action,
                    target=title_pattern,
                    error=str(exc),
                )

            if hwnd is not None:
                break

            if time.monotonic() >= deadline:
                break

            time.sleep(poll_interval)

        if hwnd is None:
            return GUIActionResult.fail(
                action,
                target=title_pattern,
                error=(
                    f"No window matching '{title_pattern}' "
                    f"appeared within {timeout}s "
                    f"({polls} poll(s))."
                ),
                data={"polls": polls, "timeout": timeout},
            )

        title = self._get_window_title(hwnd)
        return GUIActionResult.ok(
            action,
            target=title_pattern,
            message=(
                f"Window matching '{title_pattern}' appeared "
                f"after {polls} poll(s)."
            ),
            data={
                "hwnd": hwnd,
                "title": title,
                "polls": polls,
                "timeout": timeout,
            },
        )

    # --------------------------------------------------------
    # INSPECT UI TREE
    # --------------------------------------------------------

    def inspect_ui_tree(
        self, title_pattern: str
    ) -> GUIActionResult:
        """Inspect UI elements of a window.

        This is a basic implementation using window enumeration.
        For full UIA tree inspection, use the UIAutomationProvider.
        """
        action = GUIAction.inspect_ui_tree.value

        if self._user32 is None:
            return GUIActionResult.fail(
                action,
                error="UI tree inspection requires ctypes user32.",
            )

        try:
            hwnd = self._find_window(title_pattern)
            if hwnd is None:
                return GUIActionResult.fail(
                    action,
                    target=title_pattern,
                    error=f"No window matching '{title_pattern}'.",
                )

            title = self._get_window_title(hwnd)

            rect = __import__("ctypes").c_long * 4
            r = rect()
            self._user32.GetWindowRect(hwnd, r)

            return GUIActionResult.ok(
                action,
                target=title_pattern,
                message=f"Basic inspection of '{title}' window.",
                data={
                    "hwnd": hwnd,
                    "title": title,
                    "rect": {
                        "left": r[0],
                        "top": r[1],
                        "right": r[2],
                        "bottom": r[3],
                    },
                    "note": (
                        "Full UIA tree inspection requires "
                        "UIAutomationProvider."
                    ),
                },
            )
        except Exception as exc:
            return GUIActionResult.fail(
                action,
                target=title_pattern,
                error=str(exc),
            )


# ============================================================
# GUI CONTROLLER (FACADE)
# ============================================================

# Maps GUIAction values to provider method names.
_ACTION_METHOD_MAP: Dict[str, str] = {
    GUIAction.focus_window.value: "focus_window",
    GUIAction.inspect_window.value: "inspect_window",
    GUIAction.click.value: "click",
    GUIAction.double_click.value: "double_click",
    GUIAction.type_text.value: "type_text",
    GUIAction.paste_text.value: "paste_text",
    GUIAction.read_visible_text.value: "read_visible_text",
    GUIAction.select_text.value: "select_text",
    GUIAction.scroll.value: "scroll",
    GUIAction.keyboard_action.value: "keyboard_action",
    GUIAction.hotkey.value: "hotkey",
    GUIAction.drag.value: "drag",
    GUIAction.wait_for_state.value: "wait_for_state",
    GUIAction.wait.value: "wait",
    GUIAction.wait_for_window.value: "wait_for_window",
    GUIAction.inspect_ui_tree.value: "inspect_ui_tree",
}


class GUIController:
    """
    Main facade for GUI interaction.

    Usage::

        controller = GUIController()
        result = controller.click(100, 200)
        if result.success:
            ...

    The controller auto-detects the best provider based on the
    current platform.  Pass an explicit provider to override::

        controller = GUIController(provider=MyCustomProvider())
    """

    VERSION = "3.14.0"

    def __init__(
        self, provider: Optional[GUIProvider] = None
    ) -> None:
        if provider is not None:
            self._provider: Optional[GUIProvider] = provider
        else:
            self._provider = self._auto_detect_provider()

    # --------------------------------------------------------
    # AUTO-DETECT
    # --------------------------------------------------------

    @staticmethod
    def _auto_detect_provider() -> Optional[GUIProvider]:
        import sys

        if sys.platform == "win32":
            try:
                from .ui_automation_provider import UIAutomationProvider
                semantic = UIAutomationProvider()
                if semantic.available() and semantic.provider_health().get("uia_available"):
                    return semantic
            except Exception:
                pass
            candidate = WindowsGUIProvider()
            if candidate.available():
                return candidate

        return None

    # --------------------------------------------------------
    # AVAILABILITY
    # --------------------------------------------------------

    def available(self) -> bool:
        return (
            self._provider is not None
            and self._provider.available()
        )

    # --------------------------------------------------------
    # CAPABILITIES
    # --------------------------------------------------------

    def capabilities(self) -> List[str]:
        if not self.available():
            return []

        return [action.value for action in GUIAction]

    def provider_health(self) -> Dict[str, Any]:
        """Return provider health information."""
        if self._provider is None:
            return {"available": False, "provider": None}
        return {
            "available": self._provider.available(),
            "provider": type(self._provider).__name__,
            "version": getattr(self._provider, "VERSION", "unknown"),
            **self._provider.provider_health(),
        }

    # --------------------------------------------------------
    # DELEGATED ACTIONS
    # --------------------------------------------------------

    def focus_window(self, title_pattern: str) -> GUIActionResult:
        return self._delegate("focus_window", title_pattern)

    def inspect_window(self, title_pattern: str) -> GUIActionResult:
        return self._delegate("inspect_window", title_pattern)

    def click(self, x: int, y: int) -> GUIActionResult:
        return self._delegate("click", x, y)

    def double_click(self, x: int, y: int) -> GUIActionResult:
        return self._delegate("double_click", x, y)

    def type_text(
        self,
        text: str,
        *,
        focus_title_pattern: Optional[str] = None,
        focus_timeout: float = 3.0,
        focus_poll_interval: float = 0.2,
    ) -> GUIActionResult:
        return self._delegate(
            "type_text",
            text,
            focus_title_pattern=focus_title_pattern,
            focus_timeout=focus_timeout,
            focus_poll_interval=focus_poll_interval,
        )

    def paste_text(
        self,
        text: str,
        *,
        focus_title_pattern: Optional[str] = None,
        focus_timeout: float = 3.0,
        focus_poll_interval: float = 0.2,
    ) -> GUIActionResult:
        return self._delegate(
            "paste_text",
            text,
            focus_title_pattern=focus_title_pattern,
            focus_timeout=focus_timeout,
            focus_poll_interval=focus_poll_interval,
        )

    def read_visible_text(self) -> GUIActionResult:
        return self._delegate("read_visible_text")

    def read_focused_text(self) -> GUIActionResult:
        return self._delegate("read_focused_text")

    def select_text(self, start: int, end: int) -> GUIActionResult:
        return self._delegate("select_text", start, end)

    def scroll(self, direction: str, amount: int) -> GUIActionResult:
        return self._delegate("scroll", direction, amount)

    def keyboard_action(self, key: str) -> GUIActionResult:
        return self._delegate("keyboard_action", key)

    def hotkey(self, keys: str) -> GUIActionResult:
        return self._delegate("hotkey", keys)

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
    ) -> GUIActionResult:
        return self._delegate(
            "drag", start_x, start_y, end_x, end_y, duration=duration
        )

    def wait_for_state(
        self, condition: Callable[[], bool], timeout: float
    ) -> GUIActionResult:
        return self._delegate("wait_for_state", condition, timeout)

    def wait_for_window(
        self,
        title_pattern: str,
        *,
        timeout: float = 3.0,
        poll_interval: float = 0.2,
    ) -> GUIActionResult:
        return self._delegate(
            "wait_for_window",
            title_pattern,
            timeout=timeout,
            poll_interval=poll_interval,
        )

    def inspect_ui_tree(
        self, title_pattern: str
    ) -> GUIActionResult:
        return self._delegate("inspect_ui_tree", title_pattern)

    # --------------------------------------------------------
    # GENERIC DISPATCH
    # --------------------------------------------------------

    def execute(
        self, action: GUIAction, **kwargs: Any
    ) -> GUIActionResult:
        """
        Dispatch an action by its enum value.

        Example::

            controller.execute(GUIAction.click, x=100, y=200)
        """
        if action == GUIAction.wait:
            return self.wait(kwargs.get("seconds", kwargs.get("timeout", 1.0)))

        method_name = _ACTION_METHOD_MAP.get(action.value)

        if method_name is None:
            return GUIActionResult.fail(
                action.value,
                error=f"Unknown action: {action.value}",
            )

        return self._delegate(method_name, **kwargs)

    # --------------------------------------------------------
    # INTERNAL DELEGATION
    # --------------------------------------------------------

    def _delegate(
        self, method_name: str, *args: Any, **kwargs: Any
    ) -> GUIActionResult:
        if self._provider is None:
            return GUIActionResult.fail(
                method_name,
                error=(
                    "No GUI provider available on this platform."
                ),
            )

        if not self._provider.available():
            return GUIActionResult.fail(
                method_name,
                error="GUI provider is not available.",
            )

        method = getattr(self._provider, method_name, None)

        if method is None or not callable(method):
            return GUIActionResult.fail(
                method_name,
                error=(
                    f"Provider does not implement "
                    f"'{method_name}'."
                ),
            )

        try:
            return method(*args, **kwargs)
        except Exception as exc:
            return GUIActionResult.fail(
                method_name,
                error=str(exc),
            )
