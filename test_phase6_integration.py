"""
Genesis OS — Phase 6 Integration Tests.

Tests for:
- GUI controller with new actions
- UI Automation provider
- Action executor with Phase 6 operations
- Capability registration
- Provider selection
"""

import pytest
from unittest.mock import MagicMock, patch
from genesis_os.gui_controller import (
    GUIAction, GUIController, GUIActionResult, GUIProvider,
)
from genesis_os.window_models import WindowResolver
from genesis_os.ui_target_models import normalize_hotkey
from genesis_os.action_result import ActionResult


# ============================================================
# GUI CONTROLLER INTEGRATION
# ============================================================

class TestGUIControllerExtended:
    def test_gui_action_enum_includes_hotkey(self):
        assert hasattr(GUIAction, "hotkey")
        assert GUIAction.hotkey.value == "hotkey"

    def test_gui_action_enum_includes_drag(self):
        assert hasattr(GUIAction, "drag")
        assert GUIAction.drag.value == "drag"

    def test_gui_action_enum_includes_wait_for_window(self):
        assert hasattr(GUIAction, "wait_for_window")
        assert GUIAction.wait_for_window.value == "wait_for_window"

    def test_gui_action_enum_includes_inspect_ui_tree(self):
        assert hasattr(GUIAction, "inspect_ui_tree")
        assert GUIAction.inspect_ui_tree.value == "inspect_ui_tree"

    def test_gui_controller_capabilities(self):
        controller = GUIController()
        caps = controller.capabilities()
        assert "hotkey" in caps
        assert "drag" in caps
        assert "wait_for_window" in caps
        assert "inspect_ui_tree" in caps
        assert "click" in caps
        assert "type_text" in caps

    def test_gui_controller_provider_health(self):
        controller = GUIController()
        health = controller.provider_health()
        assert "available" in health
        assert "provider" in health

    def test_gui_result_ok(self):
        result = GUIActionResult.ok(
            "test_action",
            message="Test message",
            data={"key": "value"},
        )
        assert result.success is True
        assert result.action == "test_action"
        assert result.data["key"] == "value"

    def test_gui_result_fail(self):
        result = GUIActionResult.fail(
            "test_action",
            error="Something failed",
        )
        assert result.success is False
        assert result.error == "Something failed"

    def test_gui_result_to_dict(self):
        result = GUIActionResult.ok("test", message="ok")
        d = result.to_dict()
        assert d["success"] is True
        assert d["action"] == "test"
        assert d["message"] == "ok"


# ============================================================
# MOCK PROVIDER TESTS
# ============================================================

class MockGUIProvider(GUIProvider):
    """Mock provider for testing the controller facade."""

    def __init__(self):
        self._available = True
        self.calls = []

    def available(self):
        return self._available

    def focus_window(self, title_pattern):
        self.calls.append(("focus_window", title_pattern))
        return GUIActionResult.ok("focus_window", message=f"Focused {title_pattern}")

    def inspect_window(self, title_pattern):
        self.calls.append(("inspect_window", title_pattern))
        return GUIActionResult.ok("inspect_window", data={"title": title_pattern})

    def click(self, x, y):
        self.calls.append(("click", x, y))
        return GUIActionResult.ok("click", data={"x": x, "y": y})

    def double_click(self, x, y):
        self.calls.append(("double_click", x, y))
        return GUIActionResult.ok("double_click", data={"x": x, "y": y})

    def type_text(self, text, **kwargs):
        self.calls.append(("type_text", text, kwargs))
        return GUIActionResult.ok("type_text", data={"length": len(text)})

    def paste_text(self, text):
        self.calls.append(("paste_text", text))
        return GUIActionResult.ok("paste_text", data={"length": len(text)})

    def read_visible_text(self):
        self.calls.append(("read_visible_text",))
        return GUIActionResult.ok("read_visible_text", data={"text": ""})

    def select_text(self, start, end):
        self.calls.append(("select_text", start, end))
        return GUIActionResult.ok("select_text")

    def scroll(self, direction, amount):
        self.calls.append(("scroll", direction, amount))
        return GUIActionResult.ok("scroll")

    def keyboard_action(self, key):
        self.calls.append(("keyboard_action", key))
        return GUIActionResult.ok("keyboard_action")

    def hotkey(self, keys):
        self.calls.append(("hotkey", keys))
        return GUIActionResult.ok("hotkey", data={"keys": keys})

    def drag(self, start_x, start_y, end_x, end_y, duration=0.5):
        self.calls.append(("drag", start_x, start_y, end_x, end_y, duration))
        return GUIActionResult.ok("drag")

    def wait_for_state(self, condition, timeout):
        self.calls.append(("wait_for_state", condition, timeout))
        return GUIActionResult.ok("wait_for_state")

    def wait_for_window(self, title_pattern, **kwargs):
        self.calls.append(("wait_for_window", title_pattern, kwargs))
        return GUIActionResult.ok("wait_for_window", data={"title": title_pattern})

    def inspect_ui_tree(self, title_pattern):
        self.calls.append(("inspect_ui_tree", title_pattern))
        return GUIActionResult.ok("inspect_ui_tree", data={"elements": []})

    def read_focused_text(self):
        self.calls.append(("read_focused_text",))
        return GUIActionResult.ok(
            "read_focused_text",
            data={"text": "", "readable": False, "method": "mock"},
        )


class TestMockProviderIntegration:
    def test_hotkey_delegation(self):
        provider = MockGUIProvider()
        controller = GUIController(provider=provider)
        result = controller.hotkey("Ctrl+S")
        assert result.success is True
        assert len(provider.calls) == 1
        assert provider.calls[0] == ("hotkey", "Ctrl+S")

    def test_drag_delegation(self):
        provider = MockGUIProvider()
        controller = GUIController(provider=provider)
        result = controller.drag(100, 200, 300, 400, duration=0.5)
        assert result.success is True
        assert len(provider.calls) == 1
        assert provider.calls[0][0] == "drag"

    def test_wait_for_window_delegation(self):
        provider = MockGUIProvider()
        controller = GUIController(provider=provider)
        result = controller.wait_for_window("Notepad", timeout=5.0)
        assert result.success is True

    def test_inspect_ui_tree_delegation(self):
        provider = MockGUIProvider()
        controller = GUIController(provider=provider)
        result = controller.inspect_ui_tree("Notepad")
        assert result.success is True

    def test_unavailable_provider(self):
        provider = MockGUIProvider()
        provider._available = False
        controller = GUIController(provider=provider)
        result = controller.hotkey("Ctrl+S")
        assert result.success is False
        assert "not available" in result.error.lower()

    def test_no_provider(self):
        controller = GUIController.__new__(GUIController)
        controller._provider = None
        result = controller.hotkey("Ctrl+S")
        assert result.success is False
        assert "no gui provider" in result.error.lower()


# ============================================================
# ACTION RESULT INTEGRATION
# ============================================================

class TestActionResultPhase6:
    def test_trustworthy_success_verified(self):
        result = ActionResult.success_result(
            operation="gui.type_text",
            target="Notepad",
            application="notepad",
            message="Typed text",
            executed=True,
            verified=True,
            verification={"content_match": True},
        )
        assert result.trustworthy_success is True
        assert result.final_state == "verified"

    def test_trustworthy_success_unverified(self):
        result = ActionResult.success_result(
            operation="gui.type_text",
            target="Notepad",
            application="notepad",
            message="Typed text",
            executed=True,
            verified=False,
        )
        assert result.trustworthy_success is False
        assert result.final_state == "executed_unverified"

    def test_failure_result(self):
        result = ActionResult.failure_result(
            operation="gui.hotkey",
            target="Ctrl+S",
            application=None,
            message="Failed to send hotkey",
            status="provider_failure",
            error="pyautogui not available",
            executed=False,
            verified=False,
        )
        assert result.success is False
        assert result.verified is False
        assert result.final_state == "not_executed"

    def test_user_message_verified(self):
        result = ActionResult.success_result(
            operation="gui.click",
            target="Save",
            application="notepad",
            message="",
            executed=True,
            verified=True,
        )
        msg = result.user_message()
        assert "verified" in msg.lower() or "completed" in msg.lower()

    def test_user_message_unverified(self):
        result = ActionResult.success_result(
            operation="gui.type_text",
            target="editor",
            application=None,
            message="",
            executed=True,
            verified=False,
        )
        msg = result.user_message()
        assert "could not be verified" in msg.lower() or "not verified" in msg.lower() or "executed" in msg.lower()
