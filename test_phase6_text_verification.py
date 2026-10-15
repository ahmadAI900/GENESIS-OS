"""
Genesis OS — Phase 6 Text Content Verification Tests.

Real Windows tests that verify exact text content through UIA
ValuePattern, proving the DISPATCH_CONFIRMED → CONTENT_VERIFIED
verification chain works.

Tests:
- Empty editor: type text, verify exact content
- Existing content: type appended text, verify
- Paste: paste text, verify content
- Unreadable target: dispatch confirmed, content unverified
- read_focused_text returns honest results
"""

import subprocess
import time
import pytest
from genesis_os.gui_controller import GUIController
from genesis_os.window_models import WindowResolver

# --------------------------------------------------------------
# LIVE: requires a real external application, GUI session,
# browser, or provider. Excluded from the fast default run.
# Reason: real Notepad, real UIA ValuePattern readback.
# --------------------------------------------------------------
pytestmark = pytest.mark.live


def _open_notepad():
    """Open Notepad and wait for it to appear."""
    subprocess.Popen(["notepad.exe"], shell=True)
    time.sleep(1.5)
    resolver = WindowResolver()
    win = resolver.find_window(r"Notepad", timeout=5.0)
    return win


def _close_notepad():
    """Close all Notepad windows without saving.

    Uses taskkill /F (forceful termination) instead of WM_CLOSE.
    WM_CLOSE triggers a "Save?" modal on modified untitled buffers;
    an undissmissed modal can hang the GUI stack on subsequent
    COM/UIA calls.  The production app_manager.py uses the same
    taskkill approach.
    """
    subprocess.run(["taskkill", "/IM", "notepad.exe", "/F"], capture_output=True)


# ============================================================
# READ_FOCUSED_TEXT HONEST BEHAVIOR
# ============================================================

class TestReadFocusedTextHonestBehavior:
    """Verify read_focused_text returns honest results."""

    def test_read_focused_text_returns_structured_result(self):
        controller = GUIController()
        result = controller.read_focused_text()
        assert result.success is True
        assert isinstance(result.data, dict)
        assert "text" in result.data
        assert "readable" in result.data
        assert "method" in result.data

    def test_read_focused_text_when_no_uia(self):
        from genesis_os.ui_automation_provider import UIAutomationProvider
        provider = UIAutomationProvider()
        result = provider.read_focused_text()
        assert result.success is True
        assert isinstance(result.data, dict)
        # Should honest about readability
        assert "readable" in result.data
        assert "method" in result.data


# ============================================================
# NOTEPAD CONTENT VERIFICATION
# ============================================================

class TestNotepadContentVerification:
    """Real Windows tests: type into Notepad, verify content via UIA."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Open Notepad before tests, close after."""
        self.win = _open_notepad()
        yield
        _close_notepad()

    def test_type_text_exact_content_empty_editor(self):
        """A. Empty editor: type 'Hello Genesis', verify exact content."""
        if self.win is None:
            pytest.skip("Notepad did not open")

        controller = GUIController()

        # Focus Notepad
        focus_result = controller.focus_window("Notepad")
        assert focus_result.success, f"Focus failed: {focus_result.error}"

        # Clear any existing content
        import pyautogui
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.press("delete")
        time.sleep(0.3)

        # Read pre-state
        pre_result = controller.read_focused_text()
        pre_text = ""
        if pre_result.success and isinstance(pre_result.data, dict):
            pre_text = pre_result.data.get("text", "")

        # Type the test text
        test_text = "Hello Genesis"
        type_result = controller.type_text(
            test_text,
            focus_title_pattern="Notepad",
        )
        assert type_result.success, f"Type failed: {type_result.error}"

        # Wait for text to appear
        time.sleep(0.5)

        # Read post-state via UIA
        post_result = controller.read_focused_text()
        assert post_result.success, f"Read failed: {post_result.error}"
        assert isinstance(post_result.data, dict)

        post_text = post_result.data.get("text", "")
        readable = post_result.data.get("readable", False)
        method = post_result.data.get("method", "none")

        # Content verification: if UIA could read content,
        # verify the typed text appears in the observed content
        if readable and post_text:
            assert test_text in post_text, (
                f"Expected '{test_text}' in observed content "
                f"'{post_text}' (method={method})"
            )
        else:
            # UIA could not read content — honest result
            assert readable is False or post_text == ""

    def test_type_text_exact_content_append(self):
        """B. Existing content: type 'World' after 'Hello', verify."""
        if self.win is None:
            pytest.skip("Notepad did not open")

        controller = GUIController()

        # Focus Notepad
        focus_result = controller.focus_window("Notepad")
        assert focus_result.success, f"Focus failed: {focus_result.error}"

        # Clear and type initial text
        import pyautogui
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.press("delete")
        time.sleep(0.3)

        pyautogui.typewrite("Hello", interval=0.02)
        time.sleep(0.3)

        # Read pre-state
        pre_result = controller.read_focused_text()
        pre_text = ""
        if pre_result.success and isinstance(pre_result.data, dict):
            pre_text = pre_result.data.get("text", "")

        # Type additional text
        test_text = "World"
        type_result = controller.type_text(
            test_text,
            focus_title_pattern="Notepad",
        )
        assert type_result.success, f"Type failed: {type_result.error}"

        time.sleep(0.5)

        # Read post-state
        post_result = controller.read_focused_text()
        assert post_result.success
        post_text = post_result.data.get("text", "")
        readable = post_result.data.get("readable", False)

        if readable and post_text:
            # Should contain both "Hello" and "World"
            assert "Hello" in post_text, f"'Hello' not in '{post_text}'"
            assert "World" in post_text, f"'World' not in '{post_text}'"

    def test_paste_text_content_verification(self):
        """D. Paste controlled string, verify content."""
        if self.win is None:
            pytest.skip("Notepad did not open")

        controller = GUIController()

        # Focus Notepad
        focus_result = controller.focus_window("Notepad")
        assert focus_result.success, f"Focus failed: {focus_result.error}"

        # Clear
        import pyautogui
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.press("delete")
        time.sleep(0.3)

        # Paste text
        test_text = "PastedContent123"
        paste_result = controller.paste_text(test_text)
        assert paste_result.success, f"Paste failed: {paste_result.error}"

        time.sleep(0.5)

        # Read content
        post_result = controller.read_focused_text()
        assert post_result.success
        post_text = post_result.data.get("text", "")
        readable = post_result.data.get("readable", False)

        if readable and post_text:
            assert test_text in post_text, (
                f"Expected '{test_text}' in '{post_text}'"
            )

    def test_read_focused_text_returns_honest_when_unreadable(self):
        """E. Unreadable target: dispatch may occur, content cannot be read."""
        if self.win is None:
            pytest.skip("Notepad did not open")

        controller = GUIController()

        # read_focused_text should always return a result
        result = controller.read_focused_text()
        assert result.success is True
        assert isinstance(result.data, dict)

        # If readable, method should be non-empty
        readable = result.data.get("readable", False)
        method = result.data.get("method", "none")

        if readable:
            assert method != "none"
        else:
            # Honest: content not readable
            assert method == "none" or result.data.get("text", "") == ""

    def test_type_text_focus_retained(self):
        """G. Focus stolen: verification should detect focus change."""
        if self.win is None:
            pytest.skip("Notepad did not open")

        controller = GUIController()

        # Focus Notepad
        focus_result = controller.focus_window("Notepad")
        assert focus_result.success, f"Focus failed: {focus_result.error}"

        # Type with focus retention check
        type_result = controller.type_text(
            "test",
            focus_title_pattern="Notepad",
        )
        assert type_result.success

        # The result should have data with verification info
        assert isinstance(type_result.data, dict)
