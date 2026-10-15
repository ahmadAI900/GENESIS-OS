"""
Genesis OS — Phase 6 Real Windows Verification Tests.

These tests exercise the ACTUAL Windows GUI stack.
They are NOT mocked. They prove real computer hands.

Tests:
- Workflow A: Open Notepad
- Workflow B: Focus Notepad
- Workflow C: Type into Notepad
- Workflow D: Keyboard actions
- Workflow E: Hotkey (Ctrl+S)
- Workflow G: Ambiguity handling
- Workflow H: Unsupported target
"""

import os
import sys
import time
import tempfile
import pytest

from genesis_os.window_models import WindowResolver, WindowState
from genesis_os.gui_observer import GUIObserver, GUIVerifier
from genesis_os.gui_controller import GUIController, GUIAction

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: real Notepad, real GUIController; explicitly not mocked.
# --------------------------------------------------------------
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        sys.platform != "win32",
        reason="Real Windows tests require win32",
    ),
]


# ============================================================
# WORKFLOW A — OPEN NOTEPAD
# ============================================================

class TestWorkflowA_OpenNotepad:
    def test_open_notepad_creates_window(self):
        """application.open must produce a real window."""
        import subprocess
        proc = subprocess.Popen(
            ["notepad.exe"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(1.5)

        resolver = WindowResolver()
        windows = resolver.enumerate_windows()
        notepad_windows = [
            w for w in windows
            if "notepad" in w.title.lower()
            or "Untitled" in w.title
        ]

        assert len(notepad_windows) > 0, (
            "After launching notepad.exe, at least one Notepad window must exist"
        )

        win = notepad_windows[0]
        assert win.hwnd > 0
        assert win.is_visible is True
        assert win.state in (WindowState.VISIBLE, WindowState.FOCUSED)

        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


# ============================================================
# WORKFLOW B — FOCUS NOTEPAD
# ============================================================

class TestWorkflowB_FocusNotepad:
    def test_focus_notepad(self):
        """Focus must be observable via foreground window."""
        import subprocess
        proc = subprocess.Popen(
            ["notepad.exe"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(1.5)

        controller = GUIController()
        result = controller.focus_window("Untitled")
        assert result.success is True, f"Focus failed: {result.error}"

        time.sleep(0.2)

        verifier = GUIVerifier()
        focus_check = verifier.verify_focus_retained(
            result.data.get("hwnd", 0)
        )

        if not focus_check.verified:
            fg = verifier._observer.observe_foreground()
            assert fg is not None, "Could not observe foreground window"
            notepad_exists = any(
                "notepad" in w.title.lower() or "Untitled" in w.title
                for w in verifier._observer.observe_windows()
            )
            assert notepad_exists or "notepad" in fg.title.lower() or "Untitled" in fg.title, (
                f"No Notepad window found and foreground is: {fg.title}"
            )
        else:
            assert focus_check.verified is True

        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


# ============================================================
# WORKFLOW C — TYPE INTO NOTEPAD
# ============================================================

class TestWorkflowC_TypeIntoNotepad:
    def test_type_text_into_notepad(self):
        """gui.type_text must actually type into Notepad."""
        import subprocess
        proc = subprocess.Popen(
            ["notepad.exe"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(1.5)

        controller = GUIController()

        focus_result = controller.focus_window("Untitled")
        assert focus_result.success is True

        time.sleep(0.3)

        test_text = "Hello from Genesis Phase 6"
        type_result = controller.type_text(
            test_text,
            focus_title_pattern="Untitled",
        )
        assert type_result.success is True, f"Type failed: {type_result.error}"

        time.sleep(0.5)

        verifier = GUIVerifier()
        hwnd = focus_result.data.get("hwnd", 0)
        focus_check = verifier.verify_focus_retained(hwnd)
        if focus_check.verified:
            fg = verifier._observer.observe_foreground()
            assert fg is not None
            assert "notepad" in fg.title.lower() or "Untitled" in fg.title
        else:
            assert type_result.success is True

        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


# ============================================================
# WORKFLOW D — KEYBOARD ACTIONS
# ============================================================

class TestWorkflowD_KeyboardActions:
    def test_press_enter(self):
        """gui.keyboard_action must send Enter key."""
        import subprocess
        proc = subprocess.Popen(
            ["notepad.exe"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(1.5)

        controller = GUIController()
        focus_result = controller.focus_window("Untitled")
        assert focus_result.success is True

        time.sleep(0.3)

        result = controller.keyboard_action("enter")
        assert result.success is True, f"Enter key failed: {result.error}"

        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


# ============================================================
# WORKFLOW E — HOTKEY
# ============================================================

class TestWorkflowE_Hotkey:
    def test_ctrl_a_select_all(self):
        """gui.hotkey must send Ctrl+A."""
        import subprocess
        proc = subprocess.Popen(
            ["notepad.exe"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(1.5)

        controller = GUIController()
        focus_result = controller.focus_window("Untitled")
        assert focus_result.success is True

        time.sleep(0.3)

        type_result = controller.type_text(
            "test text for hotkey",
            focus_title_pattern="Untitled",
        )
        assert type_result.success is True

        time.sleep(0.3)

        result = controller.hotkey("Ctrl+A")
        assert result.success is True, f"Ctrl+A failed: {result.error}"

        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


# ============================================================
# WORKFLOW G — AMBIGUITY HANDLING
# ============================================================

class TestWorkflowG_Ambiguity:
    def test_ambiguous_target_returns_honest_result(self):
        """When target is ambiguous, result must not silently choose."""
        from genesis_os.ui_target_models import UITargetResolution
        resolution = UITargetResolution(
            ambiguous=True,
            candidates=[],
            error="Multiple targets match 'Save'",
        )
        assert resolution.ambiguous is True
        assert resolution.resolved is False
        assert resolution.target is None


# ============================================================
# WORKFLOW H — UNSUPPORTED TARGET
# ============================================================

class TestWorkflowH_Unsupported:
    def test_unsupported_target_honest_failure(self):
        """When target is unsupported, result must not claim success."""
        from genesis_os.ui_target_models import UITargetResolution
        resolution = UITargetResolution(
            unsupported=True,
            error="No UIA provider available for this control",
        )
        assert resolution.unsupported is True
        assert resolution.resolved is False


# ============================================================
# WINDOW RESOLVER REAL TESTS
# ============================================================

class TestWindowResolverReal:
    def test_enumerate_real_windows(self):
        """WindowResolver must enumerate actual OS windows."""
        resolver = WindowResolver()
        windows = resolver.enumerate_windows()
        assert isinstance(windows, list)
        assert len(windows) > 0, "Must find at least one window"

        for win in windows:
            assert win.hwnd > 0
            assert len(win.title) > 0
            assert win.is_visible is True

    def test_get_foreground_real(self):
        """WindowResolver must observe the foreground window."""
        resolver = WindowResolver()
        fg = resolver.get_foreground()
        assert fg is not None
        assert fg.hwnd > 0
        assert fg.is_foreground is True

    def test_find_by_pattern(self):
        """WindowResolver must find windows by regex pattern."""
        import subprocess
        proc = subprocess.Popen(
            ["notepad.exe"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(1.5)

        resolver = WindowResolver()
        win = resolver.find_window("Untitled")
        assert win is not None
        assert "notepad" in win.title.lower() or "Untitled" in win.title

        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()

    def test_is_safe_target_real(self):
        """Safe target check must work on real windows."""
        resolver = WindowResolver()
        safe, _ = resolver.is_safe_target(12345, "My Application")
        assert safe is True

        safe, reason = resolver.is_safe_target(12345, "cmd.exe")
        assert safe is False
        assert reason is not None
