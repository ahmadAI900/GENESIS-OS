"""
Genesis OS — Phase 6 Unit Tests.

Tests for:
- GUI error taxonomy
- Window models
- UI target models
- GUI observer/verifier
- Key normalization
- UI target resolution
"""

import pytest
from genesis_os.gui_errors import GUIErrorCode, GUIError, gui_error
from genesis_os.window_models import (
    WindowIdentity, WindowResolver, WindowState,
)
from genesis_os.ui_target_models import (
    UIControlType, UITarget, UITargetConfidence, UITargetResolution,
    normalize_key_name, normalize_hotkey,
)
from genesis_os.gui_observer import (
    GUIObserver, GUIVerifier, Observation, VerificationResult,
)


# ============================================================
# GUI ERROR TAXONOMY
# ============================================================

class TestGUIErrorTaxonomy:
    def test_error_code_values(self):
        assert GUIErrorCode.PROVIDER_UNAVAILABLE.value == "provider_unavailable"
        assert GUIErrorCode.TARGET_NOT_FOUND.value == "target_not_found"
        assert GUIErrorCode.TARGET_AMBIGUOUS.value == "target_ambiguous"
        assert GUIErrorCode.TIMEOUT.value == "timeout"
        assert GUIErrorCode.ACCESS_DENIED.value == "access_denied"

    def test_gui_error_creation(self):
        err = gui_error(
            GUIErrorCode.TARGET_NOT_FOUND,
            "Button 'Save' not found",
            detail="UIA tree has no matching element",
            provider="UIAutomationProvider",
        )
        assert err.code == GUIErrorCode.TARGET_NOT_FOUND
        assert err.message == "Button 'Save' not found"
        assert err.detail == "UIA tree has no matching element"
        assert err.provider == "UIAutomationProvider"
        assert err.retryable is False

    def test_gui_error_to_dict(self):
        err = gui_error(
            GUIErrorCode.TIMEOUT,
            "Operation timed out",
            retryable=True,
        )
        d = err.to_dict()
        assert d["code"] == "timeout"
        assert d["message"] == "Operation timed out"
        assert d["retryable"] is True
        assert "detail" not in d
        assert "provider" not in d

    def test_all_error_codes_are_strings(self):
        for code in GUIErrorCode:
            assert isinstance(code.value, str)
            assert len(code.value) > 0


# ============================================================
# WINDOW MODELS
# ============================================================

class TestWindowIdentity:
    def test_creation(self):
        win = WindowIdentity(hwnd=12345, title="Notepad")
        assert win.hwnd == 12345
        assert win.title == "Notepad"
        assert win.state == WindowState.DISCOVERED
        assert win.is_alive is True

    def test_dimensions(self):
        win = WindowIdentity(hwnd=1, left=0, top=0, right=800, bottom=600)
        assert win.width == 800
        assert win.height == 600

    def test_is_alive_destroyed(self):
        win = WindowIdentity(hwnd=1, state=WindowState.DESTROYED)
        assert win.is_alive is False

    def test_to_dict(self):
        win = WindowIdentity(hwnd=100, title="Test", pid=1234)
        d = win.to_dict()
        assert d["hwnd"] == 100
        assert d["title"] == "Test"
        assert d["pid"] == 1234
        assert "bounds" in d
        assert "state" in d

    def test_window_states(self):
        states = list(WindowState)
        assert WindowState.FOCUSED in states
        assert WindowState.VISIBLE in states
        assert WindowState.MINIMIZED in states
        assert WindowState.DESTROYED in states


class TestWindowResolver:
    def test_availability(self):
        resolver = WindowResolver()
        import sys
        if sys.platform == "win32":
            assert resolver.available is True
        else:
            assert resolver.available is False

    def test_enumerate_returns_list(self):
        resolver = WindowResolver()
        if resolver.available:
            windows = resolver.enumerate_windows()
            assert isinstance(windows, list)

    def test_get_foreground(self):
        resolver = WindowResolver()
        if resolver.available:
            fg = resolver.get_foreground()
            if fg is not None:
                assert isinstance(fg, WindowIdentity)
                assert fg.hwnd > 0

    def test_is_safe_target_console(self):
        resolver = WindowResolver()
        safe, reason = resolver.is_safe_target(123, "cmd.exe")
        assert safe is False
        assert "unsafe" in reason.lower()

    def test_is_safe_target_normal(self):
        resolver = WindowResolver()
        safe, reason = resolver.is_safe_target(123, "Notepad")
        assert safe is True
        assert reason is None

    def test_is_safe_target_no_hwnd(self):
        resolver = WindowResolver()
        safe, reason = resolver.is_safe_target(0, "Notepad")
        assert safe is False

    def test_is_safe_target_empty_title(self):
        resolver = WindowResolver()
        safe, reason = resolver.is_safe_target(123, "")
        assert safe is False


# ============================================================
# UI TARGET MODELS
# ============================================================

class TestUITarget:
    def test_creation(self):
        target = UITarget(
            name="Save",
            control_type=UIControlType.BUTTON,
            automation_id="btnSave",
        )
        assert target.name == "Save"
        assert target.control_type == UIControlType.BUTTON
        assert target.automation_id == "btnSave"

    def test_center_calculations(self):
        target = UITarget(left=100, top=200, right=300, bottom=400)
        assert target.center_x == 200
        assert target.center_y == 300
        assert target.width == 200
        assert target.height == 200

    def test_to_dict(self):
        target = UITarget(
            name="OK",
            control_type=UIControlType.BUTTON,
            confidence=UITargetConfidence.HIGH,
        )
        d = target.to_dict()
        assert d["name"] == "OK"
        assert d["control_type"] == "button"
        assert d["confidence"] == "high"
        assert "bounds" in d

    def test_control_types(self):
        assert UIControlType.BUTTON.value == "button"
        assert UIControlType.EDIT.value == "edit"
        assert UIControlType.TEXT.value == "text"
        assert UIControlType.LIST.value == "list"
        assert UIControlType.UNKNOWN.value == "unknown"


class TestKeyNormalization:
    def test_normalize_enter(self):
        assert normalize_key_name("enter") == "enter"
        assert normalize_key_name("return") == "enter"
        assert normalize_key_name("Enter") == "enter"

    def test_normalize_escape(self):
        assert normalize_key_name("escape") == "escape"
        assert normalize_key_name("esc") == "escape"

    def test_normalize_ctrl(self):
        assert normalize_key_name("ctrl") == "ctrl"
        assert normalize_key_name("control") == "ctrl"
        assert normalize_key_name("Ctrl") == "ctrl"

    def test_normalize_unknown_key(self):
        assert normalize_key_name("a") == "a"
        assert normalize_key_name("z") == "z"

    def test_normalize_hotkey(self):
        result = normalize_hotkey("Ctrl+S")
        assert result == ["ctrl", "s"]

    def test_normalize_hotkey_shift(self):
        result = normalize_hotkey("Ctrl+Shift+S")
        assert result == ["ctrl", "shift", "s"]

    def test_normalize_hotkey_alt_tab(self):
        result = normalize_hotkey("Alt+Tab")
        assert result == ["alt", "tab"]

    def test_normalize_hotkey_ordering(self):
        result = normalize_hotkey("Shift+Ctrl+A")
        assert result == ["ctrl", "shift", "a"]


class TestUITargetResolution:
    def test_resolved(self):
        target = UITarget(name="Save", control_type=UIControlType.BUTTON)
        resolution = UITargetResolution(
            target=target,
            resolved=True,
            resolution_method="uia_exact_match",
        )
        assert resolution.resolved is True
        assert resolution.target is not None
        assert resolution.target.name == "Save"

    def test_ambiguous(self):
        resolution = UITargetResolution(
            ambiguous=True,
            candidates=[
                UITarget(name="Save"),
                UITarget(name="Save As"),
            ],
        )
        assert resolution.ambiguous is True
        assert len(resolution.candidates) == 2

    def test_unsupported(self):
        resolution = UITargetResolution(
            unsupported=True,
            error="No UIA provider available",
        )
        assert resolution.unsupported is True
        assert resolution.error == "No UIA provider available"


# ============================================================
# GUI OBSERVER / VERIFIER
# ============================================================

class TestGUIObserver:
    def test_availability(self):
        observer = GUIObserver()
        import sys
        if sys.platform == "win32":
            assert observer.available is True
        else:
            assert observer.available is False

    def test_take_snapshot(self):
        observer = GUIObserver()
        if observer.available:
            snapshot = observer.take_snapshot()
            assert isinstance(snapshot, Observation)
            assert snapshot.timestamp > 0
            assert isinstance(snapshot.all_windows, list)

    def test_observe_windows(self):
        observer = GUIObserver()
        if observer.available:
            windows = observer.observe_windows()
            assert isinstance(windows, list)


class TestGUIVerifier:
    def test_verify_window_exists_notepad(self):
        verifier = GUIVerifier()
        if verifier.available:
            result = verifier.verify_window_exists("NonExistentWindow12345")
            assert result.verified is False

    def test_verify_window_not_exists(self):
        verifier = GUIVerifier()
        if verifier.available:
            result = verifier.verify_window_not_exists("NonExistentWindow12345")
            assert result.verified is True

    def test_verify_condition_timeout(self):
        verifier = GUIVerifier()
        result = verifier.verify_condition(
            lambda: False,
            timeout=0.1,
            description="false_condition",
        )
        assert result.verified is False
        assert "not met" in result.reason

    def test_verify_condition_immediate(self):
        verifier = GUIVerifier()
        result = verifier.verify_condition(
            lambda: True,
            timeout=0.1,
            description="true_condition",
        )
        assert result.verified is True
        assert "met" in result.reason
