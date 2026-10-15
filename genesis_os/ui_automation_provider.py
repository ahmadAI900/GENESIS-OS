"""
Genesis OS — Phase 6 UI Automation Provider.

Semantic Windows UI Automation provider using comtypes.

This provider implements the GUIProvider interface using
Windows UI Automation (UIA) for semantic interaction with
UI elements. When UIA is available, it provides:

- Semantic click by automation ID / name / control type
- Semantic text input via ValuePattern
- UI tree enumeration for inspection
- Element state observation

When UIA is NOT available, operations fall back gracefully.

Provider priority:
    1. UIA semantic (this provider)
    2. Win32/COM native
    3. pyautogui fallback

Architecture:
    This provider is isolated behind the GUIProvider ABC.
    It does NOT spread comtypes imports through the codebase.
    It does NOT expose raw COM interfaces to capabilities.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Dict, List, Optional, Tuple

from genesis_os.gui_controller import GUIAction, GUIActionResult, GUIProvider
from genesis_os.ui_target_models import (
    UIControlType,
    UITarget,
    UITargetConfidence,
    UITargetResolution,
)

# Hard ceiling for any single UIA COM call.  Matches the browser
# stack's DEFAULT_DISPATCH_TIMEOUT pattern (browser_manager.py:190).
_UIA_READ_TIMEOUT = 5.0


def _import_comtypes():
    """Lazy import comtypes to avoid import-time failures."""
    try:
        import comtypes
        import comtypes.client
        return comtypes
    except ImportError:
        return None


def _get_uia_root():
    """Get the UIAutomation COM interface root."""
    comtypes = _import_comtypes()
    if comtypes is None:
        return None
    try:
        UIAutomation = comtypes.client.CreateObject(
            "{FF48DBA4-60EF-4201-AA87-54103EEF594E}",
            interface=comtypes.gen.UIAutomationClient.IUIAutomation,
        )
        return UIAutomation
    except Exception:
        return None


# Control type mapping from UIA integer constants to our enum.
# Types not in UIControlType are mapped to UNKNOWN.
_UIA_CONTROL_TYPE_MAP: Dict[int, UIControlType] = {
    50000: UIControlType.BUTTON,
    50001: UIControlType.UNKNOWN,  # CALENDAR
    50002: UIControlType.CHECKBOX,
    50003: UIControlType.COMBO_BOX,
    50004: UIControlType.EDIT,
    50005: UIControlType.HYPERLINK,
    50006: UIControlType.IMAGE,
    50007: UIControlType.UNKNOWN,  # ITEM
    50008: UIControlType.LIST,
    50009: UIControlType.LIST_ITEM,
    50010: UIControlType.MENU,
    50011: UIControlType.UNKNOWN,  # MENU_BAR
    50012: UIControlType.MENU_ITEM,
    50013: UIControlType.UNKNOWN,  # PROGRESS_BAR
    50014: UIControlType.RADIO_BUTTON,
    50015: UIControlType.UNKNOWN,  # SCROLL_BAR
    50016: UIControlType.SLIDER,
    50017: UIControlType.SPINNER,
    50018: UIControlType.STATUS_BAR,
    50019: UIControlType.TAB,
    50020: UIControlType.TAB_ITEM,
    50021: UIControlType.TEXT,
    50022: UIControlType.UNKNOWN,  # TOOL_BAR
    50023: UIControlType.TOOL_TIP,
    50024: UIControlType.TREE,
    50025: UIControlType.TREE_ITEM,
    50026: UIControlType.GROUP,
    50027: UIControlType.THUMB,
    50028: UIControlType.DATA_GRID,
    50029: UIControlType.UNKNOWN,  # DATA_ITEM
    50030: UIControlType.DOCUMENT,
    50031: UIControlType.UNKNOWN,  # SPLIT_BUTTON
    50032: UIControlType.WINDOW,
    50033: UIControlType.PANE,
    50034: UIControlType.UNKNOWN,  # HEADER
    50035: UIControlType.UNKNOWN,  # HEADER_ITEM
    50036: UIControlType.UNKNOWN,  # TABLE
    50037: UIControlType.TITLE_BAR,
    50038: UIControlType.UNKNOWN,  # SEPARATOR
    50039: UIControlType.UNKNOWN,  # SCRIPT
    50040: UIControlType.MENU_ITEM,  # placeholder
}


def _map_uia_control_type(uia_type: int) -> UIControlType:
    """Map a UIA control type integer to our enum."""
    return _UIA_CONTROL_TYPE_MAP.get(uia_type, UIControlType.UNKNOWN)


class UIAutomationProvider(GUIProvider):
    """
    Windows UI Automation provider for semantic GUI interaction.

    Uses comtypes to access the Windows UIAutomation COM interface.
    Provides semantic element interaction when the target application
    exposes UIA accessibility information.

    Fallback behavior:
        When UIA is unavailable or the target element cannot be
        resolved semantically, this provider returns honest failure
        so the caller can fall back to the coordinate-based provider.
    """

    VERSION = "6.0.0"

    def __init__(self) -> None:
        self._uia = None
        self._comtypes = None
        self._pyautogui: Any = None
        self._pyperclip: Any = None
        self._user32: Any = None

        self._comtypes = _import_comtypes()
        if self._comtypes is not None:
            try:
                self._uia = _get_uia_root()
            except Exception:
                self._uia = None

        try:
            import pyautogui as _pyautogui
            _pyautogui.FAILSAFE = True
            self._pyautogui = _pyautogui
        except ImportError:
            pass

        try:
            import pyperclip as _pyperclip
            self._pyperclip = _pyperclip
        except ImportError:
            pass

        try:
            import ctypes
            self._user32 = ctypes.windll.user32
        except Exception:
            pass

    def available(self) -> bool:
        return self._pyautogui is not None

    def provider_health(self) -> Dict[str, Any]:
        return {
            "available": self.available(),
            "uia_available": self._uia is not None,
            "comtypes_available": self._comtypes is not None,
            "pyautogui_available": self._pyautogui is not None,
            "pyperclip_available": self._pyperclip is not None,
            "user32_available": self._user32 is not None,
            "version": self.VERSION,
        }

    # --------------------------------------------------------
    # UIA TEXT READING
    # --------------------------------------------------------

    def read_focused_text(self) -> GUIActionResult:
        """Read the text content of the currently focused UI element.

        Uses UIA ValuePattern or TextPattern to obtain the actual
        text value of the focused control. This is the independent
        observation mechanism for content verification.

        All UIA COM calls are wrapped in a ThreadPoolExecutor with a
        hard timeout (_UIA_READ_TIMEOUT) so that a blocked COM
        apartment (e.g. caused by an unexpected modal dialog) never
        produces an unbounded hang.

        Returns:
            GUIActionResult with data containing:
            - text: the observed text content (or empty string)
            - readable: whether content was successfully read
            - method: which UIA pattern was used
            - hwnd: the focused window handle
            - element_name: the focused element name
        """
        action = "read_focused_text"

        if self._user32 is None:
            return GUIActionResult.fail(
                action,
                error="read_focused_text requires ctypes user32.",
            )

        import ctypes

        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return GUIActionResult.fail(
                action,
                error="No foreground window.",
            )

        # Read window title
        length = self._user32.GetWindowTextLengthW(hwnd)
        buf = (ctypes.c_wchar * (length + 1))()
        self._user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
        title = buf.value or ""

        if self._uia is None:
            return GUIActionResult.ok(
                action,
                message="UIA not available; content unreadable.",
                data={
                    "text": "",
                    "readable": False,
                    "method": "none",
                    "hwnd": hwnd,
                    "title": title,
                    "element_name": "",
                },
            )

        # ---------------------------------------------------------
        # UIA COM calls are bounded by _UIA_READ_TIMEOUT.
        #
        # A modal dialog (e.g. "Save As") can cause the UIA tree
        # to block on cross-apartment marshaling.  Without a
        # timeout this produces an unbounded hang.
        # ---------------------------------------------------------

        def _read_via_uia() -> Dict[str, Any]:
            element = self._uia.ElementFromHandle(hwnd)
            if element is None:
                return {"text": "", "readable": False, "method": "none",
                        "element_name": ""}

            focused = None
            try:
                focused = element.GetFocusedChild()
            except Exception:
                pass

            target_element = focused if focused is not None else element

            text_content = ""
            method = "none"

            try:
                patterns = target_element.GetSupportedPatterns()
                for p in patterns:
                    try:
                        pattern_obj = target_element.GetPatternAsObject(p)
                        if pattern_obj is not None:
                            try:
                                val = pattern_obj.CurrentValue
                                if val is not None:
                                    text_content = str(val)
                                    method = "value_pattern"
                                    break
                            except Exception:
                                try:
                                    text_content = str(pattern_obj.DocumentRange.GetText(-1))
                                    method = "text_pattern"
                                    break
                                except Exception:
                                    continue
                    except Exception:
                        continue
            except Exception:
                pass

            if not text_content and method == "none":
                try:
                    name = target_element.CurrentName
                    if name:
                        text_content = str(name)
                        method = "name_property"
                except Exception:
                    pass

            element_name = ""
            try:
                element_name = target_element.CurrentName or ""
            except Exception:
                pass

            return {"text": text_content, "readable": method in {"value_pattern", "text_pattern"},
                    "method": method, "element_name": element_name}

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_read_via_uia)
                uia_result = future.result(timeout=_UIA_READ_TIMEOUT)
        except FuturesTimeoutError:
            return GUIActionResult.fail(
                action,
                error=(
                    f"UIA text reading timed out after "
                    f"{_UIA_READ_TIMEOUT}s (possible blocked COM "
                    f"apartment from modal dialog)."
                ),
                data={
                    "text": "",
                    "readable": False,
                    "method": "timeout",
                    "hwnd": hwnd,
                    "title": title,
                    "element_name": "",
                },
            )
        except Exception as exc:
            return GUIActionResult.fail(
                action,
                error=f"UIA text reading failed: {exc}",
            )

        readable = bool(uia_result.get("method") != "none")
        return GUIActionResult.ok(
            action,
            message=(
                f"Read {len(uia_result.get('text', ''))} character(s) "
                f"via {uia_result.get('method')}."
                if readable
                else "Content not readable via UIA."
            ),
            data={
                "text": uia_result.get("text", ""),
                "readable": readable,
                "method": uia_result.get("method", "none"),
                "hwnd": hwnd,
                "title": title,
                "element_name": uia_result.get("element_name", ""),
            },
        )

    # --------------------------------------------------------
    # UIA ELEMENT DISCOVERY
    # --------------------------------------------------------

    def _find_uia_element(
        self,
        *,
        name: Optional[str] = None,
        automation_id: Optional[str] = None,
        control_type: Optional[str] = None,
        hwnd: Optional[int] = None,
    ) -> Optional[Any]:
        """Find a UIA element by semantic properties."""
        if self._uia is None:
            return None

        try:
            if hwnd:
                element = self._uia.ElementFromHandle(hwnd)
            else:
                element = self._uia.GetRootElement()

            if element is None:
                return None

            condition = None
            if self._comtypes is not None:
                try:
                    conditions = []
                    if name:
                        conditions.append(
                            self._uia.CreatePropertyCondition(30005, name)
                        )
                    if automation_id:
                        conditions.append(
                            self._uia.CreatePropertyCondition(30011, automation_id)
                        )
                    if control_type:
                        type_id = {
                            "button": 50000,
                            "text": 50021,
                            "edit": 50004,
                            "checkbox": 50002,
                            "combo_box": 50003,
                            "list": 50008,
                            "list_item": 50009,
                            "menu": 50010,
                            "menu_item": 50012,
                            "tab": 50019,
                            "tree": 50024,
                            "tree_item": 50025,
                            "toolbar": 50022,
                            "window": 50032,
                            "pane": 50033,
                            "document": 50030,
                        }.get(control_type.lower(), 0)
                        if type_id:
                            conditions.append(
                                self._uia.CreatePropertyCondition(30003, type_id)
                            )

                    if len(conditions) == 1:
                        condition = conditions[0]
                    elif len(conditions) > 1:
                        condition = self._uia.CreateAndCondition(
                            conditions[0], conditions[1]
                        )
                        for c in conditions[2:]:
                            condition = self._uia.CreateAndCondition(condition, c)
                except Exception:
                    pass

            if condition is not None:
                found = element.FindFirst(4, condition)
                return found

        except Exception:
            pass

        return None

    def _uia_element_to_target(self, element: Any) -> Optional[UITarget]:
        """Convert a UIA element to a UITarget."""
        try:
            name = ""
            try:
                name = element.CurrentName or ""
            except Exception:
                pass

            automation_id = ""
            try:
                automation_id = element.CurrentAutomationId or ""
            except Exception:
                pass

            control_type_int = 0
            try:
                control_type_int = element.CurrentControlType
            except Exception:
                pass
            control_type = _map_uia_control_type(control_type_int)

            class_name = ""
            try:
                class_name = element.CurrentClassName or ""
            except Exception:
                pass

            left, top, right, bottom = 0, 0, 0, 0
            try:
                rect = element.CurrentBoundingRectangle
                left = rect.left
                top = rect.top
                right = rect.right
                bottom = rect.bottom
            except Exception:
                pass

            is_enabled = True
            try:
                is_enabled = element.CurrentIsEnabled
            except Exception:
                pass

            is_visible = True
            try:
                is_visible = element.CurrentIsOffscreen == 0
            except Exception:
                pass

            value = ""
            try:
                patterns = element.GetSupportedPatterns()
                for p in patterns:
                    try:
                        val_pattern = element.GetPatternAsObject(p)
                        if val_pattern is not None:
                            try:
                                value = val_pattern.CurrentValue or ""
                            except Exception:
                                pass
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            return UITarget(
                name=name,
                automation_id=automation_id,
                control_type=control_type,
                class_name=class_name,
                value=value,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                is_enabled=is_enabled,
                is_visible=is_visible,
            )
        except Exception:
            return None

    def _click_uia_element(self, element: Any) -> GUIActionResult:
        """Click a UIA element using InvokePattern or coordinates."""
        action = GUIAction.click.value

        try:
            try:
                invoke_pattern = element.GetPatternAsObject(10000)
                if invoke_pattern is not None:
                    invoke_pattern.Invoke()
                    return GUIActionResult.ok(
                        action,
                        message="Clicked via InvokePattern.",
                        data={"method": "invoke_pattern"},
                    )
            except Exception:
                pass

            try:
                rect = element.CurrentBoundingRectangle
                cx = (rect.left + rect.right) // 2
                cy = (rect.top + rect.bottom) // 2
                if self._pyautogui is not None:
                    self._pyautogui.click(cx, cy)
                    return GUIActionResult.ok(
                        action,
                        target=f"({cx}, {cy})",
                        message=f"Clicked at ({cx}, {cy}) via coordinates.",
                        data={"x": cx, "y": cy, "method": "coordinate_fallback"},
                    )
            except Exception:
                pass

            return GUIActionResult.fail(
                action,
                error="Could not click UIA element: no invoke pattern or coordinates available.",
            )
        except Exception as exc:
            return GUIActionResult.fail(action, error=str(exc))

    def _type_to_uia_element(self, element: Any, text: str) -> GUIActionResult:
        """Type text into a UIA element using ValuePattern."""
        action = GUIAction.type_text.value

        try:
            try:
                val_pattern = element.GetPatternAsObject(10002)
                if val_pattern is not None:
                    val_pattern.SetValue(text)
                    return GUIActionResult.ok(
                        action,
                        message=f"Set value via ValuePattern ({len(text)} chars).",
                        data={"method": "value_pattern", "length": len(text)},
                    )
            except Exception:
                pass

            try:
                element.SetFocus()
                time.sleep(0.05)
            except Exception:
                pass

            if self._pyautogui is not None:
                self._pyautogui.typewrite(text, interval=0.02)
                return GUIActionResult.ok(
                    action,
                    message=f"Typed {len(text)} character(s) via fallback.",
                    data={"method": "pyautogui_fallback", "length": len(text)},
                )

            return GUIActionResult.fail(
                action,
                error="Could not type into UIA element.",
            )
        except Exception as exc:
            return GUIActionResult.fail(action, error=str(exc))

    # --------------------------------------------------------
    # GUIProvider INTERFACE
    # --------------------------------------------------------

    def focus_window(
        self,
        title_pattern: str,
        *,
        timeout: float = 10.0,
        poll_interval: float = 0.3,
    ) -> GUIActionResult:
        action = GUIAction.focus_window.value

        if self._user32 is None:
            return GUIActionResult.fail(
                action,
                error="Window focus requires ctypes user32.",
            )

        import ctypes
        import re
        import time

        deadline = time.time() + max(0.1, min(timeout, 30.0))
        last_error = ""

        while True:
            result_hwnd: list = []

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                ctypes.c_bool,
                ctypes.wintypes.HWND,
                ctypes.wintypes.LPARAM,
            )

            def callback(hwnd, _lparam):
                if not self._user32.IsWindowVisible(hwnd):
                    return True
                length = self._user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return True
                buf = (ctypes.c_wchar * (length + 1))()
                self._user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
                title = buf.value or ""
                try:
                    if re.search(title_pattern, title, re.IGNORECASE):
                        result_hwnd.append(hwnd)
                except re.error:
                    if title_pattern.lower() in title.lower():
                        result_hwnd.append(hwnd)
                return True

            self._user32.EnumWindows(EnumWindowsProc(callback), 0)

            if result_hwnd:
                hwnd = result_hwnd[0]
                try:
                    self._user32.SetForegroundWindow(hwnd)
                except Exception as exc:
                    last_error = str(exc)
                else:
                    length = self._user32.GetWindowTextLengthW(hwnd)
                    buf = (ctypes.c_wchar * (length + 1))()
                    self._user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
                    title = buf.value or ""
                    return GUIActionResult.ok(
                        action,
                        target=title_pattern,
                        message=f"Focused window '{title}'.",
                        data={"hwnd": hwnd, "title": title},
                    )

            if time.time() >= deadline:
                break
            time.sleep(poll_interval)

        return GUIActionResult.fail(
            action,
            target=title_pattern,
            error=last_error or f"No window matching '{title_pattern}'.",
        )

    def inspect_window(self, title_pattern: str) -> GUIActionResult:
        action = GUIAction.inspect_window.value

        if self._user32 is None:
            return GUIActionResult.fail(
                action,
                error="Window inspection requires ctypes user32.",
            )

        try:
            import ctypes
            import re

            result_hwnd: list = []

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                ctypes.c_bool,
                ctypes.wintypes.HWND,
                ctypes.wintypes.LPARAM,
            )

            def callback(hwnd, _lparam):
                if not self._user32.IsWindowVisible(hwnd):
                    return True
                length = self._user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return True
                buf = (ctypes.c_wchar * (length + 1))()
                self._user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
                title = buf.value or ""
                try:
                    if re.search(title_pattern, title, re.IGNORECASE):
                        result_hwnd.append(hwnd)
                except re.error:
                    if title_pattern.lower() in title.lower():
                        result_hwnd.append(hwnd)
                return True

            self._user32.EnumWindows(EnumWindowsProc(callback), 0)

            if not result_hwnd:
                return GUIActionResult.fail(
                    action,
                    target=title_pattern,
                    error=f"No window matching '{title_pattern}'.",
                )

            hwnd = result_hwnd[0]
            length = self._user32.GetWindowTextLengthW(hwnd)
            buf = (ctypes.c_wchar * (length + 1))()
            self._user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
            title = buf.value or ""

            rect = ctypes.wintypes.RECT()
            self._user32.GetWindowRect(hwnd, ctypes.byref(rect))

            uia_data = {}
            if self._uia is not None:
                try:
                    element = self._uia.ElementFromHandle(hwnd)
                    if element is not None:
                        uia_data["uia_available"] = True
                        try:
                            uia_data["name"] = element.CurrentName or ""
                        except Exception:
                            pass
                except Exception:
                    uia_data["uia_available"] = False

            return GUIActionResult.ok(
                action,
                target=title_pattern,
                message=f"Inspected window '{title}'.",
                data={
                    "hwnd": hwnd,
                    "title": title,
                    "rect": {
                        "left": rect.left,
                        "top": rect.top,
                        "right": rect.right,
                        "bottom": rect.bottom,
                    },
                    **uia_data,
                },
            )
        except Exception as exc:
            return GUIActionResult.fail(
                action,
                target=title_pattern,
                error=str(exc),
            )

    def click(self, x: int, y: int) -> GUIActionResult:
        action = GUIAction.click.value
        if self._pyautogui is None:
            return GUIActionResult.fail(action, error="Mouse control requires pyautogui.")
        try:
            self._pyautogui.click(x, y)
            return GUIActionResult.ok(
                action,
                target=f"({x}, {y})",
                message=f"Clicked at ({x}, {y}).",
                data={"x": x, "y": y},
            )
        except Exception as exc:
            return GUIActionResult.fail(action, target=f"({x}, {y})", error=str(exc))

    def double_click(self, x: int, y: int) -> GUIActionResult:
        action = GUIAction.double_click.value
        if self._pyautogui is None:
            return GUIActionResult.fail(action, error="Mouse control requires pyautogui.")
        try:
            self._pyautogui.doubleClick(x, y)
            verified = False
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                verified = hwnd != 0
            except Exception:
                pass
            return GUIActionResult.ok(
                action,
                target=f"({x}, {y})",
                message=f"Double-clicked at ({x}, {y}).",
                data={
                    "x": x,
                    "y": y,
                    "verified": False,
                    "verification_type": "dispatch_only",
                    "verification_reason": "Foreground retention does not prove a double-click postcondition.",
                },
            )
        except Exception as exc:
            return GUIActionResult.fail(action, target=f"({x}, {y})", error=str(exc))

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
            return GUIActionResult.fail(action, error="Typing requires pyautogui.")
        if not isinstance(text, str) or not text:
            return GUIActionResult.fail(action, error="No text provided.")

        if focus_title_pattern:
            focus_result = self.focus_window(
                focus_title_pattern,
                timeout=focus_timeout,
                poll_interval=focus_poll_interval,
            )
            if not focus_result.success:
                return GUIActionResult.fail(
                    action,
                    target=focus_title_pattern,
                    error=focus_result.error,
                )

        baseline = self.read_focused_text()
        previous_text = None
        baseline_available = False
        if baseline.success and baseline.data.get("readable"):
            if str(baseline.data.get("method", "none")) in {"value_pattern", "text_pattern"}:
                previous_text = str(baseline.data.get("text", ""))
                baseline_available = True

        try:
            self._pyautogui.typewrite(text, interval=0.02)
        except Exception as exc:
            return GUIActionResult.fail(action, error=str(exc))

        import time as _time
        _time.sleep(0.3)

        readback = self.read_focused_text()
        if readback.success and readback.data.get("readable"):
            observed = readback.data.get("text", "")
            verified = bool(
                baseline_available
                and text in observed
                and observed != previous_text
            )
            return GUIActionResult.ok(
                action,
                message=(
                    f"Typed {len(text)} character(s). "
                    f"Content verified via {readback.data.get('method')}."
                    if verified
                    else f"Typed {len(text)} character(s). "
                    f"Content mismatch via {readback.data.get('method')}."
                ),
                data={
                    "length": len(text),
                    "verified": verified,
                    "verification_note": (
                        "content_verified" if verified
                        else "dispatch_confirmed_content_mismatch"
                    ),
                    "observed_text": observed[:200],
                    "read_method": readback.data.get("method"),
                },
            )
        else:
            return GUIActionResult.ok(
                action,
                message=f"Typed {len(text)} character(s). Dispatch confirmed via provider.",
                data={
                    "length": len(text),
                    "verified": False,
                    "verification_note": "dispatch_confirmed_content_unverified",
                },
            )

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
            return GUIActionResult.fail(action, error="Clipboard paste requires pyperclip.")
        if not isinstance(text, str) or not text:
            return GUIActionResult.fail(action, error="No text provided.")
        baseline = self.read_focused_text()
        previous_text = None
        baseline_available = False
        if baseline.success and baseline.data.get("readable"):
            if str(baseline.data.get("method", "none")) in {"value_pattern", "text_pattern"}:
                previous_text = str(baseline.data.get("text", ""))
                baseline_available = True

        try:
            self._pyperclip.copy(text)
            if self._pyautogui is not None:
                self._pyautogui.hotkey("ctrl", "v")
            readback = self._pyperclip.paste()
            clipboard_verified = readback == text
            target_readback = self.read_focused_text()
            target_verified = bool(
                baseline_available
                and target_readback.success
                and target_readback.data.get("readable")
                and text in str(target_readback.data.get("text", ""))
                and str(target_readback.data.get("text", "")) != previous_text
            )
            return GUIActionResult.ok(
                action,
                message=f"Pasted {len(text)} character(s).",
                data={
                    "length": len(text),
                    "verified": target_verified,
                    "content_match": target_verified,
                    "clipboard_verified": clipboard_verified,
                    "observed_text": str(target_readback.data.get("text", ""))[:200],
                    "read_method": target_readback.data.get("method"),
                },
                metadata={"verification_type": "focused_content_readback"},
            )
        except Exception as exc:
            return GUIActionResult.fail(action, error=str(exc))

    def read_visible_text(self) -> GUIActionResult:
        action = GUIAction.read_visible_text.value
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf = (length + 1) * ctypes.c_wchar
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value or ""
            return GUIActionResult.ok(
                action,
                message=f"Read foreground window title: '{title}'.",
                data={"window_title": title, "hwnd": hwnd},
            )
        except Exception as exc:
            return GUIActionResult.fail(action, error=str(exc))

    def select_text(self, start: int, end: int) -> GUIActionResult:
        action = GUIAction.select_text.value
        if self._pyautogui is None:
            return GUIActionResult.fail(action, error="Text selection requires pyautogui.")
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
                data={"start": start, "end": end},
            )
        except Exception as exc:
            return GUIActionResult.fail(action, target=f"[{start}:{end}]", error=str(exc))

    def scroll(self, direction: str, amount: int) -> GUIActionResult:
        action = GUIAction.scroll.value
        if self._pyautogui is None:
            return GUIActionResult.fail(action, error="Scrolling requires pyautogui.")
        normalized = str(direction or "").strip().lower()
        if normalized not in ("up", "down"):
            return GUIActionResult.fail(action, error="Direction must be 'up' or 'down'.")
        amount = max(1, min(int(amount or 3), 50))
        try:
            clicks = amount if normalized == "up" else -amount
            self._pyautogui.scroll(clicks)
            return GUIActionResult.ok(
                action,
                target=normalized,
                message=f"Scrolled {normalized} {amount} notch(es).",
                data={"direction": normalized, "amount": amount},
            )
        except Exception as exc:
            return GUIActionResult.fail(action, target=normalized, error=str(exc))

    def keyboard_action(self, key: str) -> GUIActionResult:
        action = GUIAction.keyboard_action.value
        if self._pyautogui is None:
            return GUIActionResult.fail(action, error="Keyboard control requires pyautogui.")
        if not isinstance(key, str) or not key.strip():
            return GUIActionResult.fail(action, error="No key specified.")
        try:
            normalized = key.strip().lower()
            if "+" in normalized:
                parts = [p.strip() for p in normalized.split("+")]
                self._pyautogui.hotkey(*parts)
            else:
                self._pyautogui.press(normalized)
            return GUIActionResult.ok(
                action,
                target=key,
                message=f"Sent key '{key}'.",
                data={"key": key},
            )
        except Exception as exc:
            return GUIActionResult.fail(action, target=key, error=str(exc))

    def hotkey(self, keys: str) -> GUIActionResult:
        action = GUIAction.hotkey.value
        if self._pyautogui is None:
            return GUIActionResult.fail(action, error="Hotkey requires pyautogui.")
        if not isinstance(keys, str) or not keys.strip():
            return GUIActionResult.fail(action, error="No keys specified.")
        try:
            from genesis_os.ui_target_models import normalize_hotkey
            normalized = normalize_hotkey(keys)
            self._pyautogui.hotkey(*normalized)
            verified = False
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                verified = hwnd != 0
            except Exception:
                pass
            return GUIActionResult.ok(
                action,
                target=keys,
                message=f"Sent hotkey '{keys}'.",
                data={
                "keys": keys,
                "normalized": normalized,
                "verified": False,
                "verification_type": "dispatch_only",
                "verification_reason": "Foreground retention does not prove a hotkey postcondition.",
            },
            )
        except Exception as exc:
            return GUIActionResult.fail(action, target=keys, error=str(exc))

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
            return GUIActionResult.fail(action, error="Drag requires pyautogui.")
        try:
            duration = max(0.1, min(float(duration or 0.5), 5.0))
            self._pyautogui.moveTo(start_x, start_y)
            self._pyautogui.drag(
                end_x - start_x, end_y - start_y, duration=duration
            )
            verified = False
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                verified = hwnd != 0
            except Exception:
                pass
            return GUIActionResult.ok(
                action,
                target=f"({start_x},{start_y})->({end_x},{end_y})",
                message=f"Dragged from ({start_x},{start_y}) to ({end_x},{end_y}).",
                data={
                    "start_x": start_x, "start_y": start_y,
                    "end_x": end_x, "end_y": end_y,
                    "duration": duration,
                    "verified": False,
                    "verification_type": "dispatch_only",
                    "verification_reason": "Foreground retention does not prove a drag-and-drop postcondition.",
                },
            )
        except Exception as exc:
            return GUIActionResult.fail(
                action, target=f"({start_x},{start_y})->({end_x},{end_y})", error=str(exc)
            )

    def wait_for_state(
        self, condition: Callable[[], bool], timeout: float
    ) -> GUIActionResult:
        action = GUIAction.wait_for_state.value
        if not callable(condition):
            return GUIActionResult.fail(action, error="Condition must be callable.")
        timeout = max(0.0, min(float(timeout or 10.0), 120.0))
        deadline = time.monotonic() + timeout
        polls = 0
        try:
            while time.monotonic() < deadline:
                if condition():
                    return GUIActionResult.ok(
                        action,
                        message=f"Condition met after {polls} poll(s).",
                        data={"polls": polls, "elapsed": round(timeout - (deadline - time.monotonic()), 3)},
                    )
                time.sleep(0.2)
                polls += 1
            return GUIActionResult.fail(
                action,
                error=f"Timed out after {timeout}s ({polls} polls).",
                data={"polls": polls, "timeout": timeout},
            )
        except Exception as exc:
            return GUIActionResult.fail(action, error=str(exc))

    def wait_for_window(
        self,
        title_pattern: str,
        *,
        timeout: float = 3.0,
        poll_interval: float = 0.2,
    ) -> GUIActionResult:
        action = "wait_for_window"
        if self._user32 is None:
            return GUIActionResult.fail(action, error="Window polling requires ctypes user32.")

        import ctypes
        import re

        timeout = max(0.0, float(timeout or 0.0))
        poll_interval = max(0.05, float(poll_interval or 0.2))
        deadline = time.monotonic() + timeout
        polls = 0

        while True:
            polls += 1
            result_hwnd: list = []

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                ctypes.c_bool,
                ctypes.wintypes.HWND,
                ctypes.wintypes.LPARAM,
            )

            def callback(hwnd, _lparam):
                if not self._user32.IsWindowVisible(hwnd):
                    return True
                length = self._user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return True
                buf = (ctypes.c_wchar * (length + 1))()
                self._user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
                title = buf.value or ""
                try:
                    if re.search(title_pattern, title, re.IGNORECASE):
                        result_hwnd.append(hwnd)
                except re.error:
                    if title_pattern.lower() in title.lower():
                        result_hwnd.append(hwnd)
                return True

            self._user32.EnumWindows(EnumWindowsProc(callback), 0)

            if result_hwnd:
                hwnd = result_hwnd[0]
                length = self._user32.GetWindowTextLengthW(hwnd)
                buf = (ctypes.c_wchar * (length + 1))()
                self._user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
                title = buf.value or ""
                return GUIActionResult.ok(
                    action,
                    target=title_pattern,
                    message=f"Window matching '{title_pattern}' appeared after {polls} poll(s).",
                    data={"hwnd": hwnd, "title": title, "polls": polls, "timeout": timeout},
                )

            if time.monotonic() >= deadline:
                break
            time.sleep(poll_interval)

        return GUIActionResult.fail(
            action,
            target=title_pattern,
            error=f"No window matching '{title_pattern}' appeared within {timeout}s ({polls} poll(s)).",
            data={"polls": polls, "timeout": timeout},
        )

    def inspect_ui_tree(
        self, title_pattern: str
    ) -> GUIActionResult:
        """Inspect UI elements using UIA when available."""
        action = GUIAction.inspect_ui_tree.value

        if self._user32 is None:
            return GUIActionResult.fail(
                action,
                error="UI tree inspection requires ctypes user32.",
            )

        import ctypes
        import re

        result_hwnd: list = []

        EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.wintypes.HWND,
            ctypes.wintypes.LPARAM,
        )

        def callback(hwnd, _lparam):
            if not self._user32.IsWindowVisible(hwnd):
                return True
            length = self._user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = (ctypes.c_wchar * (length + 1))()
            self._user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
            title = buf.value or ""
            try:
                if re.search(title_pattern, title, re.IGNORECASE):
                    result_hwnd.append(hwnd)
            except re.error:
                if title_pattern.lower() in title.lower():
                    result_hwnd.append(hwnd)
            return True

        self._user32.EnumWindows(EnumWindowsProc(callback), 0)

        if not result_hwnd:
            return GUIActionResult.fail(
                action,
                target=title_pattern,
                error=f"No window matching '{title_pattern}'.",
            )

        hwnd = result_hwnd[0]
        length = self._user32.GetWindowTextLengthW(hwnd)
        buf = (ctypes.c_wchar * (length + 1))()
        self._user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
        title = buf.value or ""

        elements = []
        if self._uia is not None:
            try:
                element = self._uia.ElementFromHandle(hwnd)
                if element is not None:
                    children = element.GetChildren()
                    for i in range(min(children.Count, 50)):
                        try:
                            child = children.GetElement(i)
                            target = self._uia_element_to_target(child)
                            if target:
                                elements.append(target.to_dict())
                        except Exception:
                            continue
            except Exception:
                pass

        return GUIActionResult.ok(
            action,
            target=title_pattern,
            message=f"Inspected UI tree of '{title}'.",
            data={
                "hwnd": hwnd,
                "title": title,
                "elements": elements,
                "element_count": len(elements),
                "uia_available": self._uia is not None,
            },
        )
