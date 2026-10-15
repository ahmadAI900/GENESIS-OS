"""
Regression tests for the gui.type_text / gui.paste_text window-focus fix.

These tests pin down the exact contract for the compound
"open <app> and type <text>" workflow after the
``genesis_fix_window_focus.md`` fix:

  1. Compound plans whose immediately preceding completed
     step was ``application.open`` MUST focus the just-opened
     app's window before dispatching ``gui.type_text`` /
     ``gui.paste_text``. The focus call must complete successfully
     before the type call is dispatched.

  2. Standalone ``gui.type_text`` / ``gui.paste_text`` with no
     preceding ``application.open`` MUST NOT attempt to focus
     any window — the legacy behavior of typing into the
     currently focused window is preserved.

  3. When the focus call times out (the window never appears
     within the polling window) the step MUST fail honestly
     with a clear error message rather than proceeding to
     type blindly.

  4. The Windows provider's ``focus_window`` itself polls
     ``_find_window`` until the window exists or a timeout
     elapses, so a freshly-launched application's window has
     time to appear before the polling gives up.

  5. ``WindowsGUIProvider.type_text`` logs the focused
     hwnd / window title and confirms the ``pyautogui.typewrite``
     call before reporting success.

All tests use mocked ``pyautogui`` and ``user32`` so they run
on any host without touching real applications.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock, patch

import pytest

from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.gui_controller import (
    GUIActionResult,
    GUIController,
    WindowsGUIProvider,
)
from genesis_os.os_manager import OSManager
from genesis_os.workflow_engine import UniversalDesktopWorkflowEngine
from genesis_os.workflow_models import (
    WorkflowPlan,
    WorkflowStep,
)


# =========================================================
# TEST 1 — compound plan focuses before typing
# =========================================================


class _RecordingOSManager:
    """OSManager stand-in that records every GUI call.

    The action executor dispatches ``gui.type_text`` through
    ``os_manager.gui_action("type_text", ...)``. The workflow
    engine's pre-focus helper calls
    ``os_manager.gui_action("focus_window", ...)`` first. Both
    calls hit this fake and are recorded so tests can assert
    ordering and arguments.
    """

    def __init__(
        self,
        *,
        focus_success: bool = True,
        type_success: bool = True,
        focus_message: str = "Focused notepad",
        type_message: str = "Typed text",
    ) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._focus_success = focus_success
        self._type_success = type_success
        self._focus_message = focus_message
        self._type_message = type_message

    def open_application(self, target, **kwargs):
        self.calls.append(
            {"op": "application.open", "target": target, "kwargs": kwargs}
        )
        return {
            "success": True,
            "operation": "application.open",
            "target": target,
            "executed": True,
            "verified": True,
            "running": True,
        }

    def inspect_application(self, target, **kwargs):
        self.calls.append(
            {
                "op": "application.inspect",
                "target": target,
                "kwargs": kwargs,
            }
        )
        return {
            "success": True,
            "operation": "application.inspect",
            "target": target,
            "application": target,
            "running": True,
            "executed": True,
            "verified": True,
            "running": True,
        }

    def gui_action(self, action, **kwargs):
        self.calls.append(
            {"op": f"gui.{action}", "kwargs": dict(kwargs)}
        )
        if action == "focus_window":
            return {
                "success": self._focus_success,
                "operation": f"gui.{action}",
                "executed": self._focus_success,
                "verified": self._focus_success,
                "post_state_matches": self._focus_success,
                "message": self._focus_message,
                "data": (
                    {"hwnd": 0xABCD, "title": "notepad", "polls": 1}
                    if self._focus_success
                    else {}
                ),
                "error": None if self._focus_success else "No window",
                "metadata": {},
            }
        return {
            "success": self._type_success,
            "operation": f"gui.{action}",
            "executed": self._type_success,
            "verified": self._type_success,
            "message": self._type_message,
            "data": {
                "length": len(str(kwargs.get("text", ""))),
                "content_match": self._type_success,
                "observed_text": str(kwargs.get("text", "")) if self._type_success else "",
                "read_method": "value_pattern" if self._type_success else "none",
            },
            "error": None if self._type_success else "Typing failed",
            "metadata": {},
        }


def _build_compound_workflow():
    """A two-step compound workflow: open notepad, then type."""

    plans = [
        ActionPlan(operation="application.open", target="notepad"),
        ActionPlan(
            operation="gui.type_text",
            target=None,
            parameters={"text": "Hello from Genesis"},
        ),
    ]
    return WorkflowPlan(
        objective="open notepad and write Hello from Genesis",
        steps=tuple(
            WorkflowStep(
                step_id=f"step-{i}",
                plan=p,
                depends_on=("step-1",) if i > 1 else (),
            )
            for i, p in enumerate(plans, start=1)
        ),
    )


def test_compound_plan_focus_window_called_before_typewrite():
    """Compound "open notepad and write X" must call
    ``focus_window`` with the resolved app name BEFORE the
    typewrite call is dispatched, and must mark the step
    verified only after BOTH calls succeed."""

    os_manager = _RecordingOSManager()
    executor = ActionExecutor(os_manager=os_manager)
    engine = UniversalDesktopWorkflowEngine(
        executor,
        os_manager=os_manager,
    )
    workflow = _build_compound_workflow()

    result = engine.execute(workflow)

    # The workflow succeeded end-to-end and was verified.
    assert result.success is True
    assert result.final_verified is True
    assert result.status == "completed"

    # Both GUI calls happened through OSManager.gui_action,
    # and focus_window came first.
    gui_calls = [c for c in os_manager.calls if c["op"].startswith("gui.")]
    gui_ops = [c["op"] for c in gui_calls]
    assert "gui.focus_window" in gui_ops
    assert "gui.type_text" in gui_ops
    focus_idx = gui_ops.index("gui.focus_window")
    type_idx = gui_ops.index("gui.type_text")
    assert focus_idx < type_idx, (
        f"focus_window must be called BEFORE type_text; "
        f"got call order {gui_ops}"
    )

    # focus_window was called with the right title pattern.
    focus_call = next(
        c for c in gui_calls if c["op"] == "gui.focus_window"
    )
    assert focus_call["kwargs"].get("title_pattern") == "notepad"

    # type_text was called with the text payload (and the
    # focus_title_pattern forwarded so the provider knows
    # which window to focus idempotently).
    type_call = next(c for c in gui_calls if c["op"] == "gui.type_text")
    assert type_call["kwargs"].get("text") == "Hello from Genesis"
    assert type_call["kwargs"].get("focus_title_pattern") == "notepad"

    # The step record carries pre_focus_app so a human can
    # confirm in the console log which window received the
    # keystrokes.
    type_step = next(
        s for s in result.steps if s["operation"] == "gui.type_text"
    )
    assert type_step.get("pre_focus_app") == "notepad"
    assert type_step.get("pre_focus", {}).get("success") is True


# =========================================================
# TEST 2 — standalone typing does NOT attempt focus
# =========================================================


def test_standalone_gui_type_text_does_not_call_focus_window():
    """A standalone ``gui.type_text`` workflow with no
    preceding ``application.open`` step must NOT attempt to
    focus any window — preserves the legacy behavior of
    typing into whichever window currently has focus."""

    os_manager = _RecordingOSManager()
    executor = ActionExecutor(os_manager=os_manager)
    engine = UniversalDesktopWorkflowEngine(
        executor,
        os_manager=os_manager,
    )

    # Single-step workflow with no preceding application.open.
    plan = ActionPlan(
        operation="gui.type_text",
        target=None,
        parameters={"text": "hello"},
    )
    workflow = WorkflowPlan(
        objective="type hello",
        steps=(WorkflowStep(step_id="step-1", plan=plan),),
    )

    engine.execute(workflow)

    gui_calls = [c for c in os_manager.calls if c["op"].startswith("gui.")]
    gui_ops = [c["op"] for c in gui_calls]

    # The workflow engine did NOT inject a focus_window call
    # because there was no preceding application.open.
    assert "gui.focus_window" not in gui_ops, (
        f"workflow engine incorrectly injected a focus_window "
        f"call into a standalone typing workflow: {gui_ops}"
    )


def test_standalone_gui_type_text_with_named_target_does_not_call_focus_window():
    """A gui.type_text with a concrete target window name
    (e.g. user said "type X in notepad") keeps target=notepad
    and must NOT trigger the pre-focus path because the
    executor already routes through ``gui_action`` with that
    title."""

    os_manager = _RecordingOSManager()
    executor = ActionExecutor(os_manager=os_manager)
    engine = UniversalDesktopWorkflowEngine(
        executor,
        os_manager=os_manager,
    )

    plan = ActionPlan(
        operation="gui.type_text",
        target="notepad",
        parameters={"text": "hello"},
    )
    workflow = WorkflowPlan(
        objective="type hello in notepad",
        steps=(WorkflowStep(step_id="step-1", plan=plan),),
    )

    engine.execute(workflow)

    # focus_window was NOT injected by the workflow engine.
    focus_calls = [
        c for c in os_manager.calls if c["op"] == "gui.focus_window"
    ]
    assert focus_calls == []


# =========================================================
# TEST 3 — window-not-found-within-timeout fails honestly
# =========================================================


def test_window_not_found_within_timeout_fails_step_honestly():
    """If the focus call times out (window never appears
    within ~3s polling window) the step MUST fail honestly
    with a clear error message rather than proceeding to
    type blindly."""

    os_manager = _RecordingOSManager(
        focus_success=False,
        type_success=True,  # would succeed if dispatched
    )
    executor = ActionExecutor(os_manager=os_manager)
    engine = UniversalDesktopWorkflowEngine(
        executor,
        os_manager=os_manager,
    )
    workflow = _build_compound_workflow()

    result = engine.execute(workflow)

    # The workflow did NOT succeed: the focus call failed so
    # the workflow engine failed the step honestly instead
    # of dispatching a blind type_text call.
    assert result.success is False
    assert result.final_verified is False

    # The focus call happened; the type_text call did NOT.
    focus_calls = [
        c for c in os_manager.calls if c["op"] == "gui.focus_window"
    ]
    type_calls = [
        c for c in os_manager.calls if c["op"] == "gui.type_text"
    ]
    assert len(focus_calls) == 1
    assert len(type_calls) == 0, (
        "type_text MUST NOT be dispatched when the pre-focus "
        "failed; the runtime must not type into whatever "
        "window already had focus."
    )

    # The failed step has the pre_focus metadata attached
    # so a human can see exactly why the workflow stopped.
    type_step = next(
        s for s in result.steps
        if s["operation"] == "gui.type_text"
    )
    assert type_step.get("pre_focus", {}).get("success") is False
    assert type_step["status"] == "execution_failed"


# =========================================================
# TEST 4 — Windows provider polls for the window
# =========================================================


def _make_provider_with_mocks(
    *,
    user32_available: bool = True,
    find_window_results: List[Any] = None,
):
    """Construct a WindowsGUIProvider with mocked user32,
    pyautogui, and pyperclip so tests can simulate the
    window-existence polling without a real desktop.

    ``find_window_results`` is the list of values returned by
    ``_find_window`` on successive calls — e.g. ``[None, None, 0x1234]``
    means the window appears on the third poll.
    """
    find_window_results = list(find_window_results or [])

    user32 = MagicMock() if user32_available else None
    pyautogui = MagicMock()
    pyperclip = MagicMock()

    provider = WindowsGUIProvider.__new__(WindowsGUIProvider)
    provider._pyautogui = pyautogui
    provider._pyperclip = pyperclip
    provider._user32 = user32

    poll_iter = iter(find_window_results)

    def fake_find(title):
        try:
            return next(poll_iter)
        except StopIteration:
            return None

    provider._find_window = fake_find
    return provider


def test_windows_provider_focus_window_polls_until_window_appears():
    """focus_window must poll _find_window until the window
    exists or the timeout elapses."""

    provider = _make_provider_with_mocks(
        find_window_results=[None, None, None, 0xCAFE],
    )

    real_sleep = time.sleep
    sleeps: List[float] = []
    with patch.object(time, "sleep", side_effect=lambda s: sleeps.append(s)):
        result = provider.focus_window(
            "notepad", timeout=3.0, poll_interval=0.2,
        )

    assert result.success is True
    assert result.data["hwnd"] == 0xCAFE
    # Three polls missed the window before the fourth hit.
    assert result.data["polls"] == 4
    # Polls slept the configured interval between attempts.
    assert len(sleeps) == 3
    assert all(s == 0.2 for s in sleeps)
    # SetForegroundWindow was called with the matched hwnd.
    provider._user32.SetForegroundWindow.assert_called_with(0xCAFE)
    # Sanity: time.sleep patched out, not the real thing.
    del real_sleep


def test_windows_provider_focus_window_fails_after_timeout():
    """focus_window must return a failure result with a
    clear error when the window does not appear within the
    polling timeout."""

    provider = _make_provider_with_mocks(
        find_window_results=[None] * 50,
    )

    with patch.object(time, "sleep", lambda s: None):
        result = provider.focus_window(
            "notepad", timeout=0.6, poll_interval=0.2,
        )

    assert result.success is False
    assert "notepad" in (result.error or "")
    assert "0.6" in (result.error or "")  # timeout mentioned
    assert result.data["polls"] >= 1
    provider._user32.SetForegroundWindow.assert_not_called()


# =========================================================
# TEST 5 — type_text logs hwnd + payload and forwards focus
# =========================================================


def test_windows_provider_type_text_logs_hwnd_and_calls_typewrite():
    """type_text must log the focused hwnd/window title and
    confirm pyautogui.typewrite was actually called with the
    given text."""

    hwnd = 0xBEEF
    provider = _make_provider_with_mocks(
        find_window_results=[hwnd],
    )
    provider._get_window_title = lambda h: "Untitled - Notepad"

    print_calls: List[str] = []
    with patch("builtins.print", side_effect=lambda *a, **k: print_calls.append(" ".join(str(x) for x in a))):
        result = provider.type_text(
            "Hello from Genesis",
            focus_title_pattern="notepad",
            focus_timeout=0.5,
            focus_poll_interval=0.2,
        )

    assert result.success is True
    # pyautogui.typewrite was called with the exact text.
    provider._pyautogui.typewrite.assert_called_with(
        "Hello from Genesis", interval=0.02,
    )
    # The pre-focus log line identifies the focused window.
    assert any("focus_window" in line for line in print_calls), (
        f"focus_window should log a pre-focus line; "
        f"got {print_calls}"
    )
    # The type_text log line identifies the typed text and
    # the hwnd it was dispatched to. The hwnd is printed as
    # a decimal integer; check both the literal hwnd value
    # and the hex form to be safe.
    hwnd_str = str(hwnd)
    hwnd_hex = hex(hwnd)
    assert any(
        "type_text" in line
        and "<redacted>" in line
        and (hwnd_str in line or hwnd_hex in line)
        for line in print_calls
    ), (
        f"type_text should log a redacted payload and the focused hwnd; got {print_calls}"
    )
    # The result metadata records the focus context so
    # callers can verify the keystroke target.
    md = result.metadata
    assert md["focus_success"] is True
    assert md["focus_hwnd"] == hwnd
    assert md["focus_title"] == "Untitled - Notepad"


def test_windows_provider_type_text_fails_when_focus_times_out():
    """If focus_window times out, type_text must NOT call
    pyautogui.typewrite; it must return a failure result with
    a clear error and the focus error embedded in metadata."""

    provider = _make_provider_with_mocks(
        find_window_results=[None] * 50,
    )

    with patch.object(time, "sleep", lambda s: None):
        result = provider.type_text(
            "Hello from Genesis",
            focus_title_pattern="missing_app",
            focus_timeout=0.4,
            focus_poll_interval=0.2,
        )

    assert result.success is False
    provider._pyautogui.typewrite.assert_not_called()
    assert "missing_app" in (result.error or "")
    assert result.metadata["focus_success"] is False
    assert result.metadata["focus_error"]


def test_windows_provider_type_text_without_focus_still_types():
    """Standalone typing with no focus_title_pattern must
    type immediately into whatever window currently has
    focus — no focus polling."""

    provider = _make_provider_with_mocks(find_window_results=[])

    result = provider.type_text("hello")

    assert result.success is True
    provider._pyautogui.typewrite.assert_called_with(
        "hello", interval=0.02,
    )
    assert result.metadata["focus_attempted"] is False