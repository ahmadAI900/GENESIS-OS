"""
Genesis OS — Modal Dialog Recovery Tests.

Proves that a real unexpected modal dialog appearing mid-operation
does NOT cause an unbounded hang.  Every operation must recover
within its stated timeout bounds.

This is the direct regression test for the finding that
verify_uia_readback.py hung for 5+ hours when a "Save As"
dialog appeared in Notepad.

Tests:
  A. read_focused_text recovers when a modal dialog is blocking
  B. RuntimeFocusResolver refuses to dispatch into a modal dialog
  C. type_text recovers when focus lands on a modal dialog
  D. Full workflow: modal dialog mid-operation → system recovers
"""

import subprocess
import time
import pytest

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: launches real Notepad and sends real keystrokes.
# --------------------------------------------------------------
pytestmark = pytest.mark.live


def _open_notepad():
    """Open Notepad and wait for it to appear."""
    subprocess.Popen(["notepad.exe"], shell=True)
    time.sleep(1.5)
    from genesis_os.window_models import WindowResolver
    resolver = WindowResolver()
    return resolver.find_window(r"Notepad", timeout=5.0)


def _close_notepad():
    """Force-kill Notepad (never WM_CLOSE — that's the bug under test)."""
    subprocess.run(["taskkill", "/IM", "notepad.exe", "/F"], capture_output=True)


def _force_save_dialog():
    """Force Notepad to show the 'Save?' modal dialog.

    Sends WM_CLOSE to every Notepad window.  Because we will have
    modified the buffer, this triggers the 'Do you want to save
    changes?' modal.  The modal is LEFT OPEN on purpose — it is
    the thing under test.
    """
    import ctypes
    user32 = ctypes.windll.user32

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LPARAM,
    )

    hwnds = []

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = (ctypes.c_wchar * (length + 1))()
        user32.GetWindowTextW(hwnd, ctypes.byref(buf), length + 1)
        title = buf.value or ""
        if "Notepad" in title:
            hwnds.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)

    for hwnd in hwnds:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE

    # Give Notepad time to show the dialog
    time.sleep(1.0)


# ============================================================
# A. read_focused_text must not hang when modal is present
# ============================================================

class TestReadFocusedTextModalRecovery:
    """read_focused_text must return within timeout even when a
    modal dialog is blocking the foreground window."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        self.win = _open_notepad()
        yield
        _close_notepad()

    def test_read_focused_text_returns_within_timeout_with_modal(self):
        """Force a 'Save?' modal, then call read_focused_text.
        Must return within 10 seconds (the UIA timeout is 5s)."""
        if self.win is None:
            pytest.skip("Notepad did not open")

        from genesis_os.gui_controller import GUIController
        controller = GUIController()

        # Modify Notepad content so WM_CLOSE triggers the dialog
        import pyautogui
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.press("delete")
        time.sleep(0.2)
        pyautogui.typewrite("test", interval=0.02)
        time.sleep(0.3)

        # Force the modal dialog to appear
        _force_save_dialog()

        # Now call read_focused_text — this must NOT hang.
        start = time.monotonic()
        result = controller.read_focused_text()
        elapsed = time.monotonic() - start

        assert elapsed < 10.0, (
            f"read_focused_text took {elapsed:.1f}s — should be < 10s"
        )
        assert result.success is True  # the Win32 path always succeeds

    def test_uia_read_focused_text_returns_within_timeout_with_modal(self):
        """Force a 'Save?' modal, then call UIAutomationProvider
        read_focused_text.  Must return within 10 seconds."""
        if self.win is None:
            pytest.skip("Notepad did not open")

        from genesis_os.ui_automation_provider import UIAutomationProvider
        provider = UIAutomationProvider()

        # Modify Notepad content
        import pyautogui
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.press("delete")
        time.sleep(0.2)
        pyautogui.typewrite("test", interval=0.02)
        time.sleep(0.3)

        # Force the modal dialog
        _force_save_dialog()

        # UIA read must NOT hang
        start = time.monotonic()
        result = provider.read_focused_text()
        elapsed = time.monotonic() - start

        assert elapsed < 10.0, (
            f"UIA read_focused_text took {elapsed:.1f}s — should be < 10s"
        )
        # Should either succeed or fail with timeout — never hang
        assert result.success in (True, False)


# ============================================================
# B. RuntimeFocusResolver refuses to dispatch into a modal
# ============================================================

class TestFocusResolverModalDetection:
    """RuntimeFocusResolver.is_safe_target must reject modal
    dialog windows."""

    def test_save_as_dialog_is_unsafe(self):
        from genesis_os.runtime_focus_resolver import RuntimeFocusResolver
        safe, reason = RuntimeFocusResolver.is_safe_target(
            12345, "Save As"
        )
        assert safe is False
        assert "modal dialog" in reason.lower()

    def test_do_you_want_to_save_is_unsafe(self):
        from genesis_os.runtime_focus_resolver import RuntimeFocusResolver
        safe, reason = RuntimeFocusResolver.is_safe_target(
            12345, "Notepad - Do you want to save changes?"
        )
        assert safe is False
        assert "modal dialog" in reason.lower()

    def test_confirm_save_as_is_unsafe(self):
        from genesis_os.runtime_focus_resolver import RuntimeFocusResolver
        safe, reason = RuntimeFocusResolver.is_safe_target(
            12345, "Confirm Save As"
        )
        assert safe is False

    def test_normal_notepad_is_safe(self):
        from genesis_os.runtime_focus_resolver import RuntimeFocusResolver
        safe, reason = RuntimeFocusResolver.is_safe_target(
            12345, "Untitled - Notepad"
        )
        assert safe is True

    def test_notepad_with_content_is_safe(self):
        from genesis_os.runtime_focus_resolver import RuntimeFocusResolver
        safe, reason = RuntimeFocusResolver.is_safe_target(
            12345, "Hello Genesis - Notepad"
        )
        assert safe is True


# ============================================================
# C. type_text recovers when focus lands on a modal dialog
# ============================================================

class TestTypeTextModalRecovery:
    """type_text must not hang when a modal dialog steals focus."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        self.win = _open_notepad()
        yield
        _close_notepad()

    def test_type_text_recovers_with_modal_present(self):
        """Force a 'Save?' modal, then call type_text.
        Must return within 10 seconds."""
        if self.win is None:
            pytest.skip("Notepad did not open")

        from genesis_os.gui_controller import GUIController
        controller = GUIController()

        # Modify content to trigger dialog on close
        import pyautogui
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.press("delete")
        time.sleep(0.2)
        pyautogui.typewrite("test", interval=0.02)
        time.sleep(0.3)

        # Force modal dialog
        _force_save_dialog()

        # type_text must NOT hang
        start = time.monotonic()
        result = controller.type_text(
            "should not hang",
            focus_title_pattern="Notepad",
        )
        elapsed = time.monotonic() - start

        assert elapsed < 10.0, (
            f"type_text took {elapsed:.1f}s — should be < 10s"
        )
        # Result may be success or failure — the important thing
        # is that it returns, not that it succeeds.
        assert result.success in (True, False)


# ============================================================
# D. Full workflow: modal dialog mid-operation → recovery
# ============================================================

class TestFullWorkflowModalRecovery:
    """Simulate the exact scenario that caused the 5+ hour hang:
    type into Notepad, then a modal appears, then subsequent
    operations must still recover."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        self.win = _open_notepad()
        yield
        _close_notepad()

    def test_workflow_recovers_after_modal(self):
        """Type text, force modal, then do more operations.
        Everything must complete within timeout."""
        if self.win is None:
            pytest.skip("Notepad did not open")

        from genesis_os.gui_controller import GUIController
        from genesis_os.ui_automation_provider import UIAutomationProvider
        import pyautogui

        controller = GUIController()
        provider = UIAutomationProvider()

        # Step 1: type text (should work)
        focus = controller.focus_window("Notepad")
        assert focus.success, f"Focus failed: {focus.error}"

        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.press("delete")
        time.sleep(0.2)

        type_result = controller.type_text("Hello", focus_title_pattern="Notepad")
        assert type_result.success, f"Type failed: {type_result.error}"
        time.sleep(0.3)

        # Step 2: force modal dialog
        _force_save_dialog()

        # Step 3: subsequent operations must all complete within timeout
        start = time.monotonic()

        r1 = controller.read_focused_text()
        r2 = provider.read_focused_text()
        r3 = controller.type_text("should not hang", focus_title_pattern="Notepad")

        total_elapsed = time.monotonic() - start

        # Total of all three operations must be < 30s
        # (each has a 5s timeout, but we allow margin)
        assert total_elapsed < 30.0, (
            f"Three post-modal operations took {total_elapsed:.1f}s "
            f"— should be < 30s total"
        )

        # None of these should have hung
        assert r1.success in (True, False)
        assert r2.success in (True, False)
        assert r3.success in (True, False)
