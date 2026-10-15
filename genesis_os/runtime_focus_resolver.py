"""
Genesis OS — Runtime Focus Resolver (generalized).

Purpose
-------

GUI capabilities whose target is implicit ("type hello world", "paste
clipboard into the focused window") cannot be safely dispatched until
the runtime has determined WHICH OS window is the focus target and
WHETHER that window is a safe recipient. Without this resolver, the
executor previously short-circuited to a `requires_runtime_resolution`
status that the workflow engine then converted to `verified=True`
without ever calling the underlying ``pyautogui.typewrite`` — producing
silent false-success messages.

This module provides the generalized runtime contract:

  * ``resolve_focused_window()`` — observes the current OS foreground
    window (hwnd, title, pid) via the Windows ``user32`` bridge.
  * ``is_safe_target(hwnd, title)`` — refuses to dispatch into a
    small set of never-type-into identifiers (the terminal that
    launched Genesis, the Python REPL, the bare OS shell). Patterns
    are kept GENERAL: they match on common console/repl substrings,
    never on application-specific names.
  * ``verify_focus_retained(expected_hwnd)`` — re-inspects the
    foreground window after a dispatch to confirm the same window
    is still in focus. This is the post-state observation the
    executor binds its ``verified`` flag to.
  * ``dispatch_text_or_paste`` — the integrated dispatch:
    resolve → safety check → call into the OSManager GUI bridge →
    verify focus retained → return a structured result the executor
    can map directly onto ``ActionResult``.

No application is special-cased. The patterns below match generic
console/REPL/shell identifiers. Notepad, Chrome, Word, Slack, etc. are
all accepted; ``cmd.exe``, ``powershell``, ``python``, ``ipython``,
``jupyter``, ``WindowsTerminal`` are not.

Platform limitations
-------------------

The Windows-specific ``user32`` calls only run on ``sys.platform ==
"win32"``. On any other host the resolver reports ``unsupported`` and
the executor surfaces an explicit unresolved_target failure so the
workflow engine can treat it as a real failure, not as silent success.
This is the correct, honest behavior; "type into the focused window"
is a Windows-desktop-only capability by definition.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from genesis_os.window_models import UNSAFE_TITLE_PATTERNS as _UNSAFE_TITLE_PATTERNS


# ---------------------------------------------------------------
# Modal-dialog title patterns.
#
# If the foreground window matches any of these, a real OS modal
# dialog is present.  Dispatching keystrokes into it is wrong:
# the typed text would land in the dialog (e.g. a filename
# edit in "Save As") instead of the intended application window.
#
# These patterns are intentionally GENERAL — they match the
# well-known Windows dialog title substrings, never app-specific
# names.
# ---------------------------------------------------------------
_MODAL_DIALOG_TITLE_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"\bSave\s+As\b", re.IGNORECASE),
    re.compile(r"\bDo\s+you\s+want\s+to\s+save\b", re.IGNORECASE),
    re.compile(r"\bSave\s+changes\b", re.IGNORECASE),
    re.compile(r"\bConfirm\s+Save\s+As\b", re.IGNORECASE),
    re.compile(r"\bDelete\s+File\b", re.IGNORECASE),
    re.compile(r"\bConfirm\s+Delete\b", re.IGNORECASE),
    re.compile(r"\bReplace\s+Existing\b", re.IGNORECASE),
    re.compile(r"\bMove\s+File\b", re.IGNORECASE),
    re.compile(r"\bCopy\s+File\b", re.IGNORECASE),
    re.compile(r"\bFolder\s+Already\s+Exists\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class FocusedWindow:
    """A foreground window observed at runtime."""

    hwnd: int
    title: str
    pid: Optional[int] = None


@dataclass
class RuntimeFocusResolution:
    """Structured outcome of the runtime focus resolver.

    The executor maps this directly onto ``ActionResult``. The
    contract is:

      * ``dispatched`` — the OSManager GUI bridge actually ran
      * ``verified``   — post-state observation confirms the
                        foreground window after dispatch is the
                        same window that received the dispatch
      * ``focused``    — the resolved window metadata
      * ``error``      — populated when the resolver or the
                        dispatch failed; the executor surfaces it
                        in the ``ActionResult.error`` field
    """

    dispatched: bool = False
    verified: bool = False
    focused: Optional[FocusedWindow] = None
    raw_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status: str = "unresolved_target"  # see module docstring for values
    safety_rejected: bool = False
    safety_reason: Optional[str] = None
    verification_reason: Optional[str] = None


class RuntimeFocusResolver:
    """Generalized runtime resolver for GUI dispatch targets.

    The resolver is stateless and safe to construct per-call. All
    platform interactions go through the existing Windows user32
    bridge that the GUI controller already uses, so we depend on
    no new libraries.

    The OS bridge is supplied by the caller as a small duck-typed
    callable (``os_manager.gui_action``) to avoid a hard import
    cycle between ``action_executor`` and ``os_manager``.
    """

    VERSION = "3.14.1"

    UNSAFE_TITLE_PATTERNS = _UNSAFE_TITLE_PATTERNS

    @staticmethod
    def is_safe_target(hwnd: Optional[int], title: Optional[str]) -> Tuple[bool, Optional[str]]:
        """Return ``(safe, reason)``.

        A window is unsafe if it has no title (likely an internal /
        background process window) or its title matches one of the
        generalized console/REPL patterns, or if it is a known modal
        dialog (Save As, Delete confirmation, etc.).  ``hwnd == 0`` is
        also considered unsafe (no foreground window).
        """
        if not hwnd:
            return False, "no foreground window"
        if title is None:
            return False, "foreground window has no title"
        stripped = title.strip()
        if not stripped:
            return False, "foreground window title is empty"
        for pattern in _UNSAFE_TITLE_PATTERNS:
            if pattern.search(stripped):
                return False, (
                    f"refusing to dispatch into console/REPL window "
                    f"(title={stripped!r})"
                )
        for pattern in _MODAL_DIALOG_TITLE_PATTERNS:
            if pattern.search(stripped):
                return False, (
                    f"foreground window is a modal dialog "
                    f"(title={stripped!r}); dispatch would land in "
                    f"the dialog, not the application"
                )
        return True, None

    @classmethod
    def resolve_focused_window(cls, user32: Any) -> Optional[FocusedWindow]:
        """Return the current OS foreground window, or ``None`` if
        the platform cannot answer (e.g. non-Windows host).

        ``user32`` is the ctypes ``windll.user32`` handle; the call
        is performed in a try/except so a missing/broken platform
        bridge never crashes the runtime.
        """
        if user32 is None:
            return None
        try:
            hwnd = int(user32.GetForegroundWindow() or 0)
        except Exception:
            return None
        if not hwnd:
            return None
        title = ""
        try:
            length = int(user32.GetWindowTextLengthW(hwnd) or 0)
            buf = (length + 1) * __import__("ctypes").c_wchar
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value or ""
        except Exception:
            title = ""
        pid: Optional[int] = None
        try:
            pdw_pid = __import__("ctypes").c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, __import__("ctypes").byref(pdw_pid))
            pid = int(pdw_pid.value or 0) or None
        except Exception:
            pid = None
        return FocusedWindow(hwnd=hwnd, title=title, pid=pid)

    @classmethod
    def verify_focus_retained(
        cls,
        user32: Any,
        expected_hwnd: int,
        *,
        settle_seconds: float = 0.05,
    ) -> bool:
        """Re-inspect the foreground window after dispatch.

        A small settle delay (50ms by default) absorbs the
        asynchronous focus shift that follows keystroke dispatch
        on Windows. The expected hwnd is the one we observed
        BEFORE dispatch; the post-dispatch foreground window
        must match it for the dispatch to be considered verified.
        """
        if user32 is None or not expected_hwnd:
            return False
        if settle_seconds > 0:
            time.sleep(settle_seconds)
        try:
            current = int(user32.GetForegroundWindow() or 0)
        except Exception:
            return False
        return current == expected_hwnd

    # --------------------------------------------------------------
    # Integrated dispatch for type_text / paste_text
    # --------------------------------------------------------------

    def dispatch_text_or_paste(
        self,
        *,
        os_manager: Any,
        action: str,
        text: str,
        focus_title_pattern: Optional[str] = None,
        focus_timeout: float = 3.0,
        focus_poll_interval: float = 0.2,
        text_parameter_key: str = "text",
        require_focus_retain: bool = True,
    ) -> RuntimeFocusResolution:
        """Generalized dispatch path for type_text / paste_text.

        Parameters
        ----------
        os_manager : object
            Must expose ``gui_action(action, **kwargs)`` returning a
            dict with at least ``success``, ``executed``, ``verified``,
            ``error``, ``data``. The existing ``OSManager.gui_action``
            already has this contract.
        action : str
            ``"type_text"`` or ``"paste_text"``.
        text : str
            The text payload to type / paste.
        focus_title_pattern : str, optional
            When supplied, the GUI provider performs its own
            focus-window polling before dispatch. We do NOT
            additionally probe the foreground window in this path
            because the user has explicitly named the target.
        require_focus_retain : bool
            When ``True``, re-inspect the foreground window after
            dispatch and only report verified=True if the same
            window is still focused. This is the closed-loop
            observation the new contract requires.
        """

        outcome = RuntimeFocusResolution()

        if os_manager is None or not hasattr(os_manager, "gui_action"):
            outcome.status = "unresolved_target"
            outcome.error = (
                "No OSManager GUI bridge is available; runtime "
                "focus resolution cannot dispatch the action."
            )
            return outcome

        # ------------------------------------------------------
        # 1. Determine the target window.
        #
        # When the user named a window, dispatch goes through the
        # GUI provider's own focus-window polling. When the user
        # did NOT name one, we MUST inspect the current foreground
        # window via user32 and decide whether it is safe before
        # dispatching — otherwise keystrokes could land in the
        # terminal that launched Genesis (the original bug).
        # ------------------------------------------------------

        user32 = None
        try:
            gui = getattr(os_manager, "gui", None)
            if gui is not None:
                user32 = getattr(gui, "_provider", None)
                if user32 is not None:
                    user32 = getattr(user32, "_user32", None)
        except Exception:
            user32 = None

        if not focus_title_pattern:
            # Implicit-target path: observe + safety-check.
            if sys.platform != "win32":
                outcome.status = "unresolved_target"
                outcome.error = (
                    "Runtime focus resolution is implemented for "
                    "Windows only; this host is "
                    f"{sys.platform!r}."
                )
                return outcome

            focused = self.resolve_focused_window(user32)
            if focused is None:
                outcome.status = "unresolved_target"
                outcome.error = (
                    "No foreground window is currently focused; "
                    "refusing to dispatch keystrokes into an "
                    "unknown target."
                )
                return outcome

            safe, reason = self.is_safe_target(focused.hwnd, focused.title)
            if not safe:
                outcome.status = "unresolved_target"
                outcome.safety_rejected = True
                outcome.safety_reason = reason
                outcome.error = reason
                outcome.focused = focused
                return outcome

            outcome.focused = focused

        # ------------------------------------------------------
        # 2. Dispatch through the OSManager GUI bridge.
        # ------------------------------------------------------

        try:
            kwargs: Dict[str, Any] = {
                text_parameter_key: text,
                "focus_title_pattern": focus_title_pattern,
                "focus_timeout": focus_timeout,
                "focus_poll_interval": focus_poll_interval,
            }
            raw = os_manager.gui_action(action, **kwargs)
        except Exception as exc:
            outcome.status = "unresolved_target"
            outcome.error = f"GUI dispatch raised an exception: {exc}"
            return outcome

        outcome.raw_result = raw
        if not isinstance(raw, dict):
            outcome.status = "unresolved_target"
            outcome.error = (
                "OSManager GUI bridge returned a non-dict payload."
            )
            return outcome

        dispatched = bool(raw.get("success")) and bool(raw.get("executed", True))
        if not dispatched:
            outcome.status = "execution_failed"
            outcome.error = raw.get("error") or raw.get("message") or (
                "GUI dispatch did not report success."
            )
            return outcome

        outcome.dispatched = True

        # ------------------------------------------------------
        # 3. Closed-loop observation: re-inspect foreground window
        #    after dispatch and confirm it is the same window we
        #    resolved to. This is the post-state evidence that
        #    binds ``verified`` to an actual observation.
        #
        #    When the user explicitly named a target window
        #    (``focus_title_pattern`` set), the GUI provider has
        #    already polled for the window to appear; we still
        #    confirm focus was retained.
        # ------------------------------------------------------

        if not require_focus_retain or user32 is None:
            # Best-effort: if we cannot observe, fall back to the
            # provider's own verified flag. This is the most
            # honest signal we have without user32.
            provider_verified = bool(raw.get("verified"))
            outcome.verified = provider_verified
            if provider_verified:
                outcome.status = "verified"
                outcome.verification_reason = (
                    "Provider-reported verification; "
                    "user32 observation unavailable."
                )
            else:
                outcome.status = "verification_failed"
                outcome.error = (
                    raw.get("error")
                    or raw.get("message")
                    or (
                        "GUI dispatch reported success but the "
                        "provider did not confirm verification."
                    )
                )
                outcome.verification_reason = (
                    "Provider did not confirm verification "
                    "and user32 observation unavailable."
                )
            return outcome

        expected_hwnd = (
            outcome.focused.hwnd
            if outcome.focused is not None
            else 0
        )
        retained = self.verify_focus_retained(user32, expected_hwnd)
        if retained:
            outcome.verified = True
            outcome.status = "verified"
            outcome.verification_reason = (
                f"Foreground HWND {expected_hwnd} retained "
                "after dispatch; focus verified."
            )
        else:
            outcome.verified = False
            outcome.status = "verification_failed"
            outcome.error = (
                f"Foreground window changed during {action}; the "
                "keystrokes may have landed in the wrong window."
            )
            outcome.verification_reason = (
                f"Foreground HWND changed from {expected_hwnd} "
                f"during {action}; focus not retained."
            )
        return outcome