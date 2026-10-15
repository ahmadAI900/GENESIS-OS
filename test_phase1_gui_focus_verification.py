"""
Genesis OS — Phase 0 Blocker Fix Integration Tests.

The Phase 0 forensic test exposed a production-critical
correctness bug:

    "write hello world"
    → _handle_level3_request
    → _try_multi_step_workflow
    → UniversalDesktopWorkflowEngine
    → ActionExecutor
    → requires_runtime_resolution  (NO pyautogui.typewrite call)
    → workflow-engine carve-out
    → completed / verified=True

The workflow engine's carve-out at ``workflow_engine.py``
previously accepted ``requires_runtime_resolution`` for
``gui.type_text`` / ``gui.paste_text`` / ``gui.focus_window``
as a verified success, while the executor's
``action_executor.py`` short-circuit never actually called
``pyautogui.typewrite``. Net effect: Genesis reported
"Genesis completed the objective in 1 verified step(s)."
without ever sending a keystroke.

This module enforces the new contract end-to-end:

    A. Standalone "write hello world" — must actually
       dispatch (or honestly fail), never produce a
       verified=True success without dispatch.

    B. Compound "open notepad and write Hello from Genesis"
       — pre-focus must succeed, type_text must dispatch,
       verification must succeed.

    C. gui.type_text with no safely resolvable target —
       must return unresolved_target with verified=False;
       workflow must NOT report completed.

    D. gui.paste_text — same contract as gui.type_text.

    E. Successful GUI action must show actual dispatch
       (mock recorded) AND verified=True.

    F. Failed / unverified GUI action must NEVER become
       successful merely because the executor accepted the
       request.

These tests use a mocked ``OSManager`` so no real Notepad
or browser is opened. The mocks are designed to exercise
the real ``ActionExecutor.execute`` and
``UniversalDesktopWorkflowEngine.execute`` code paths.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import Mock

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.objective_understanding import ObjectiveUnderstanding
from genesis_os.os_manager import OSManager
from genesis_os.workflow_decomposer import WorkflowDecomposer
from genesis_os.workflow_engine import UniversalDesktopWorkflowEngine
from genesis_os.workflow_models import (
    WorkflowPlan,
    WorkflowStep,
)


# =========================================================
# MOCKS
# =========================================================


class _FakeGUIProvider:
    """Stand-in for a real GUIProvider.

    Returns ``GUIActionResult``-shaped dicts (with
    ``success``, ``executed``, ``verified``, ``error``,
    ``message``, ``data``, ``metadata``) that the
    ``OSManager.gui_action`` wrapper can map straight onto
    its return dict. Counts every call so tests can
    assert that dispatch actually happened.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.type_attempts = 0
        self.paste_attempts = 0
        self.focus_attempts = 0
        self._user32: Optional[Any] = None
        self._focused_title: str = ""
        self._focused_hwnd: int = 0
        self.dispatches_succeed: bool = True
        self._content: str = ""
        # When False, simulate focus shifting mid-dispatch so
        # the resolver's post-state observation fails.
        self.shift_focus_mid_dispatch: bool = False

    def available(self) -> bool:
        return True

    def focus_window(self, title_pattern, timeout=3.0, poll_interval=0.2):
        self.focus_attempts += 1
        self.calls.append({"op": "focus_window", "pattern": title_pattern})
        if self._user32 is None:
            return {
                "success": False,
                "operation": "focus_window",
                "error": "user32 not available in test",
                "verified": False,
            }
        hwnd = self._user32.find_window(title_pattern)
        if hwnd is None:
            return {
                "success": False,
                "operation": "focus_window",
                "error": f"No window matching '{title_pattern}'",
                "verified": False,
            }
        try:
            self._user32.SetForegroundWindow(hwnd)
        except Exception as exc:
            return {
                "success": False,
                "operation": "focus_window",
                "error": str(exc),
                "verified": False,
            }
        return {
            "success": True,
            "operation": "focus_window",
            "verified": True,
            "data": {"hwnd": hwnd, "title": self._user32.title_for(hwnd)},
        }

    def type_text(
        self,
        text,
        *,
        focus_title_pattern=None,
        focus_timeout=3.0,
        focus_poll_interval=0.2,
    ):
        self.type_attempts += 1
        self.calls.append(
            {"op": "type_text", "text": text, "pattern": focus_title_pattern}
        )
        if self.shift_focus_mid_dispatch and self._user32 is not None:
            # Simulate the foreground window changing during
            # the dispatch so the resolver's post-state
            # observation catches it.
            self._user32._focused_hwnd = 0
            self._user32._focused_title = ""
        if self.dispatches_succeed:
            self._content = text
            return {
                "success": True,
                "operation": "type_text",
            "executed": True,
            "verified": True,
            "running": True,
            "message": f"Typed {len(text)} character(s).",
                "data": {
                    "length": len(text),
                    "content_match": True,
                    "observed_text": text,
                    "read_method": "value_pattern",
                },
                "metadata": {
                    "focus_attempted": bool(focus_title_pattern),
                    "verification_type": "focused_content_readback",
                },
            }
        return {
            "success": False,
            "operation": "type_text",
            "executed": False,
            "verified": False,
            "error": "Simulated dispatch failure.",
        }

    def paste_text(self, text, **kwargs):
        self.paste_attempts += 1
        self.calls.append({"op": "paste_text", "text": text})
        if self.dispatches_succeed:
            self._content = text
            return {
                "success": True,
                "operation": "paste_text",
                "executed": True,
                "verified": True,
                "message": f"Pasted {len(text)} character(s).",
                "data": {
                    "length": len(text),
                    "verified": True,
                    "content_match": True,
                    "observed_text": text,
                    "read_method": "value_pattern",
                },
                "metadata": {
                    "verification_type": "focused_content_readback",
                    "clipboard_verified": True,
                },
            }
        return {
            "success": False,
            "operation": "paste_text",
            "executed": False,
            "verified": False,
            "error": "Simulated paste failure.",
        }

    def read_focused_text(self):
        return {
            "success": True,
            "operation": "read_focused_text",
            "data": {
                "text": self._content,
                "readable": True,
                "method": "value_pattern",
            },
        }


class _FakeUser32:
    """Minimal stand-in for ctypes windll.user32.

    Reports a single safe foreground window whose title
    matches ``focused_title``. Tests can also pollute the
    set of valid windows for focus_window lookups.

    The ``GetWindowTextW`` and ``GetWindowTextLengthW``
    implementations use real ctypes ``c_wchar`` arrays so
    that the buffer ``.value`` property the resolver
    introspects returns a plain Python string.
    """

    def __init__(self, focused_title: str = "Notepad", focused_hwnd: int = 12345) -> None:
        import ctypes
        self._ctypes = ctypes
        self._focused_title = focused_title
        self._focused_hwnd = focused_hwnd
        self._windows: Dict[int, str] = {focused_hwnd: focused_title}

    def GetForegroundWindow(self):
        return self._focused_hwnd

    def GetWindowTextLengthW(self, hwnd):
        if hwnd not in self._windows:
            return 0
        return len(self._windows[hwnd])

    def GetWindowTextW(self, hwnd, buf, max_count):
        """Write up to ``max_count`` wide chars into ``buf``.

        ``buf`` is a ctypes ``c_wchar * (max_count)`` array.
        Setting ``buf.value`` populates the entire array
        from a Python string and null-terminates.
        """
        if hwnd not in self._windows:
            return 0
        title = self._windows[hwnd]
        if len(title) < max_count:
            buf.value = title
        else:
            buf.value = title[: max_count - 1]
        return min(max_count - 1, len(title))

    def SetForegroundWindow(self, hwnd):
        if hwnd not in self._windows:
            raise OSError(f"Cannot focus unknown hwnd {hwnd}")
        self._focused_hwnd = hwnd
        return True

    def find_window(self, pattern):
        import re
        for hwnd, title in self._windows.items():
            if re.search(pattern, title, re.IGNORECASE):
                return hwnd
        return None

    def title_for(self, hwnd):
        return self._windows.get(hwnd, "")

    def IsWindowVisible(self, hwnd):
        return True

    def EnumWindows(self, callback, lparam):
        for hwnd in list(self._windows.keys()):
            callback(hwnd, lparam)
        return True

    def GetWindowThreadProcessId(self, hwnd, pid_ref):
        pid_ref.value = 9999
        return 1

    def GetWindowRect(self, hwnd, rect):
        rect[0] = 0
        rect[1] = 0
        rect[2] = 800
        rect[3] = 600
        return True


class _FakeOSManagerWithGUI:
    """OSManager stand-in that mirrors the real
    ``os_manager.gui._provider._user32`` attribute chain
    the ``RuntimeFocusResolver`` introspects.

    The fake GUI object's ``_provider`` is a
    ``_FakeGUIProvider`` and the provider's ``_user32`` is a
    ``_FakeUser32``.

    ``gui_action`` mirrors ``OSManager.gui_action``: it
    accepts a string action name, looks the method up on
    the provider by string name, and returns a dict shaped
    like the real ``OSManager.gui_action`` return value.
    """

    def __init__(
        self,
        user32: Optional[_FakeUser32] = None,
        provider: Optional[_FakeGUIProvider] = None,
    ) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.provider = provider or _FakeGUIProvider()
        if user32 is not None:
            self.provider._user32 = user32

        outer = self

        class _FakeGUIController:
            _provider = outer.provider

            def execute(self, action, **kwargs):
                if hasattr(action, "value"):
                    name = action.value
                else:
                    name = str(action)
                method = getattr(outer.provider, name, None)
                if method is None:
                    return {
                        "success": False,
                        "action": name,
                        "error": f"Provider does not implement '{name}'",
                    }
                return method(**kwargs)

            def read_focused_text(self):
                return outer.provider.read_focused_text()

        self.gui = _FakeGUIController()

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
            "message": f"Opened {target}",
        }

    def inspect_application(self, target, **kwargs):
        return {
            "success": True,
            "operation": "application.inspect",
            "target": target,
            "application": target,
            "running": True,
            "executed": True,
            "verified": True,
        }

    def gui_action(self, action, **kwargs):
        """Mirror the real ``OSManager.gui_action`` contract.

        Returns a dict with the canonical keys the executor
        and the runtime focus resolver rely on.
        """
        method = getattr(self.provider, action, None)
        if method is None:
            return {
                "success": False,
                "operation": f"gui.{action}",
                "error": f"Unknown GUI action: {action}",
                "verified": False,
            }
        result = method(**kwargs)
        payload = {
            "success": result.get("success", False),
            "operation": f"gui.{action}",
            "executed": result.get("executed", False),
            "verified": result.get("verified", False),
            "message": result.get("message", ""),
            "data": result.get("data", {}),
            "metadata": result.get("metadata", {}),
            "error": result.get("error"),
        }
        return payload


# =========================================================
# A. Standalone "write hello world"
# =========================================================


def test_a_standalone_write_hello_world_dispatches_or_fails_honestly():
    """Scenario A.

    Standalone ``"write hello world"`` is the canonical
    Phase 0 probe. With the carve-out removed, the executor
    MUST attempt to dispatch through the runtime focus
    resolver. When a safe focused window exists (the fake
    user32 reports a Notepad window), the dispatch must
    actually call into the provider's ``type_text`` and
    return verified=True. Without a safe focused window,
    the executor must return ``unresolved_target`` with
    ``verified=False`` and the workflow engine must NOT
    report ``completed``.

    On this test host there is no real user32 / GUI bridge,
    so the resolver MUST return ``unresolved_target`` and
    the workflow engine MUST NOT report verified=True.
    The test does not assert the positive case end-to-end
    here (it is asserted in test_e_successful_gui_action).
    """
    os_manager = Mock(spec=OSManager)
    os_manager.gui = None  # runtime focus resolver will fail
    executor = ActionExecutor(os_manager=os_manager)

    de = WorkflowDecisionEngine()
    decision = de.decide("write hello world")
    plan = ActionPlan.from_decision(decision)

    result = executor.execute(plan)

    # No fake-success: this is the Phase 0 carve-out's job.
    assert result.success is False, (
        f"Phase 0 carve-out returned verified=True for "
        f"a request that never reached pyautogui.typewrite. "
        f"Result: success={result.success} "
        f"verified={result.verified} status={result.status!r}"
    )
    assert result.verified is False
    # Status must be one of the legitimate failure states.
    assert result.status in {"unresolved_target", "verification_failed",
                              "execution_failed", "execution_exception"}
    # ``requires_runtime_resolution`` is no longer a valid
    # outcome for GUI text input — that was the carve-out.
    assert result.status != "requires_runtime_resolution", (
        "executor returned requires_runtime_resolution for "
        "gui.type_text — this is the Phase 0 production-"
        "critical bug. The executor must perform the "
        "closed-loop dispatch or surface an honest failure."
    )


def test_a_workflow_engine_does_not_promote_unresolved_to_completed():
    """Scenario A follow-up: even when an ``unresolved_target``
    outcome reaches the workflow engine, the engine must
    NOT mark the workflow as completed. This is the
    workflow-engine carve-out the Phase 0 audit flagged.
    """
    user32 = _FakeUser32(focused_title="", focused_hwnd=0)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    executor = ActionExecutor(os_manager=fake_os)

    # Build a single-step workflow manually so we have
    # full control over the plan.
    plan = ActionPlan(
        operation="gui.type_text",
        target=None,
        parameters={"text": "hello world", "confirmed": True},
    )
    workflow = WorkflowPlan(
        objective="write hello world",
        steps=(
            WorkflowStep(
                step_id="step-1",
                plan=plan,
                depends_on=(),
            ),
        ),
    )

    engine = UniversalDesktopWorkflowEngine(executor, os_manager=fake_os)
    result = engine.execute(workflow)

    # CRITICAL: the workflow must NOT report completed.
    assert result.status != "completed", (
        "Workflow engine returned status='completed' for a "
        "request whose target could not be resolved. This "
        "is the Phase 0 production-critical bug."
    )
    assert result.final_verified is False
    assert result.success is False


@pytest.mark.live
def test_a_probe_text_write_hello_world_does_not_pyautogui_typewrite():
    """Regression guard for the Phase 0 forensic test.

    The exact text ``"write hello world"`` from the
    Phase 0 probe must NOT call ``pyautogui.typewrite``
    on a host with no real focused window — the runtime
    focus resolver must reject the unsafe target and
    the workflow engine must NOT report completed.

    This is the direct behavioural test for the bug the
    prompt requires to be fixed.

    LIVE: the only test in this file that touches the real
    desktop session. It builds a real ``GenesisOS`` and wraps
    the REAL ``pyautogui.typewrite`` in a pass-through spy, so
    it resolves focus against the actual foreground window and
    would type into whatever is focused. Every other test here
    uses ``_FakeGUIProvider`` / ``_FakeUser32`` and stays in the
    fast default run.
    """
    from genesis import GenesisOS

    g = GenesisOS()
    text = "write hello world"
    classification = g.classify(g._resolve_session_reference(text))
    assert classification.get("intent") == "gui.type_text", (
        f"classification changed: {classification!r}"
    )

    # Inject a counter into pyautogui.typewrite so we
    # can prove whether the keystroke was dispatched.
    import pyautogui
    real_typewrite = pyautogui.typewrite
    typewrite_calls: List[Any] = []

    def _spy(*args, **kwargs):
        typewrite_calls.append((args, kwargs))
        return real_typewrite(*args, **kwargs)

    pyautogui.typewrite = _spy
    try:
        response = g._handle_level3_request(text, classification)
    finally:
        pyautogui.typewrite = real_typewrite

    # The honest outcome is the failure message, not a
    # fake "1 verified step(s)" success.
    assert "1 verified step" not in str(response), (
        f"Phase 0 carve-out is back: response is {response!r}"
    )
    # And the keystroke was NOT sent on a host with no
    # safely-resolvable focused window. The runtime focus
    # resolver refused before dispatch.
    assert len(typewrite_calls) == 0, (
        f"pyautogui.typewrite was called "
        f"{len(typewrite_calls)} time(s) but should be 0 "
        f"on a host with no real focused window."
    )


# =========================================================
# B. Compound "open notepad and write Hello from Genesis"
# =========================================================


def test_b_compound_open_notepad_and_write_hello_from_genesis():
    """Scenario B.

    Compound L3 request must:
      1. Open Notepad (application.open step).
      2. Resolve the open app's window via the workflow
         engine's pre-focus branch.
      3. Call ``gui.type_text`` into the resolved window.
      4. Verify focus was retained.
      5. Report final_verified=True ONLY when ALL of the
         above actually happened.
    """
    user32 = _FakeUser32(focused_title="Untitled - Notepad", focused_hwnd=12345)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    executor = ActionExecutor(os_manager=fake_os)
    engine = UniversalDesktopWorkflowEngine(executor, os_manager=fake_os)

    de = WorkflowDecisionEngine()
    understanding = ObjectiveUnderstanding(de).understand(
        "open notepad and write Hello from Genesis"
    )
    decomposition = WorkflowDecomposer().decompose(understanding)

    assert decomposition.executable is True
    assert len(decomposition.workflow.steps) == 2
    ops = [s.plan.operation for s in decomposition.workflow.steps]
    assert ops == ["application.open", "gui.type_text"]

    result = engine.execute(decomposition.workflow)

    # Step 1 succeeded.
    assert fake_os.calls[0]["op"] == "application.open"
    # The workflow engine invoked the pre-focus path before
    # the type_text call. This is the explicit "compound"
    # resolution.
    type_text_calls = [
        c for c in fake_os.provider.calls if c["op"] == "type_text"
    ]
    assert len(type_text_calls) == 1
    # The compound path used the resolved focus pattern.
    assert type_text_calls[0]["pattern"] == "notepad"
    # Verified.
    assert result.success is True
    assert result.final_verified is True
    assert result.status == "completed"


# =========================================================
# C. gui.type_text with no safely resolvable target
# =========================================================


def test_c_type_text_no_safe_target_returns_unresolved():
    """Scenario C.

    No safe focused window → the runtime focus resolver
    refuses to dispatch → executor returns
    ``unresolved_target`` with verified=False → workflow
    engine reports the step as a real failure.
    """
    user32 = _FakeUser32(focused_title="", focused_hwnd=0)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    executor = ActionExecutor(os_manager=fake_os)

    plan = ActionPlan(
        operation="gui.type_text",
        target=None,
        parameters={"text": "hello", "confirmed": True},
    )

    result = executor.execute(plan)

    # The resolver refused: no safe target, no dispatch.
    assert result.success is False
    assert result.verified is False
    assert result.status == "unresolved_target"
    # The provider was NOT called for type_text because the
    # resolver short-circuited before dispatch.
    assert fake_os.provider.type_attempts == 0


def test_c_workflow_no_safe_target_does_not_complete():
    """Workflow-level integration of scenario C: when the
    GUI text-input action cannot resolve a safe target,
    the workflow engine must NOT report completed.
    """
    user32 = _FakeUser32(focused_title="", focused_hwnd=0)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    executor = ActionExecutor(os_manager=fake_os)
    engine = UniversalDesktopWorkflowEngine(executor, os_manager=fake_os)

    plan = ActionPlan(
        operation="gui.type_text",
        target=None,
        parameters={"text": "hello", "confirmed": True},
    )
    workflow = WorkflowPlan(
        objective="write hello",
        steps=(
            WorkflowStep(step_id="step-1", plan=plan, depends_on=()),
        ),
    )

    result = engine.execute(workflow)

    # The workflow engine must report a non-completed,
    # non-verified outcome. The exact status string is
    # either "unresolved_target" (when the step never
    # dispatched) or "verification_failed" (when dispatch
    # ran but the post-state observation failed). Both are
    # legitimate — what matters is that the workflow
    # engine does NOT promote the step to completed.
    assert result.success is False
    assert result.final_verified is False
    assert result.status != "completed"
    assert result.status in {"unresolved_target", "verification_failed"}
    # No keystroke was sent.
    assert fake_os.provider.type_attempts == 0


# =========================================================
# D. gui.paste_text equivalent
# =========================================================


def test_d_paste_text_dispatches_or_fails_honestly():
    """Scenario D.

    Same contract as gui.type_text. The standalone request
    ``"paste Hello"`` is the gui.paste_text equivalent of
    "write hello world". Without a safe focused window
    the executor must return unresolved_target with
    verified=False.
    """
    user32 = _FakeUser32(focused_title="", focused_hwnd=0)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    executor = ActionExecutor(os_manager=fake_os)

    de = WorkflowDecisionEngine()
    decision = de.decide("paste Hello")
    assert decision.get("intent") == "gui.paste_text"

    plan = ActionPlan.from_decision(decision)
    result = executor.execute(plan)

    assert result.success is False
    assert result.verified is False
    assert result.status == "unresolved_target"
    assert result.status != "requires_runtime_resolution"
    assert fake_os.provider.paste_attempts == 0


def test_d_paste_text_with_safe_target_dispatches_and_verifies():
    """Scenario D positive path: with a safe focused
    window the executor dispatches paste_text, the
    provider's verified flag flows through, and the
    workflow engine reports completed.
    """
    user32 = _FakeUser32(focused_title="Untitled - Notepad", focused_hwnd=12345)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    executor = ActionExecutor(os_manager=fake_os)
    engine = UniversalDesktopWorkflowEngine(executor, os_manager=fake_os)

    plan = ActionPlan(
        operation="gui.paste_text",
        target=None,
        parameters={"text": "Hello from Genesis", "confirmed": True},
    )
    workflow = WorkflowPlan(
        objective="paste Hello from Genesis",
        steps=(
            WorkflowStep(step_id="step-1", plan=plan, depends_on=()),
        ),
    )

    result = engine.execute(workflow)

    assert result.success is True
    assert result.final_verified is True
    assert result.status == "completed"
    assert fake_os.provider.paste_attempts == 1


# =========================================================
# E. Successful GUI action must show actual dispatch AND verification
# =========================================================


def test_e_successful_gui_action_dispatch_and_verified():
    """Scenario E.

    When the runtime focus resolver finds a safe focused
    window, dispatches through the GUI bridge, and the
    post-state observation confirms focus was retained,
    the executor MUST return success=True, verified=True,
    and the workflow MUST report completed.
    """
    user32 = _FakeUser32(focused_title="Untitled - Notepad", focused_hwnd=12345)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    executor = ActionExecutor(os_manager=fake_os)

    plan = ActionPlan(
        operation="gui.type_text",
        target=None,
        parameters={"text": "Hello World", "confirmed": True},
    )

    result = executor.execute(plan)

    assert result.success is True, (
        f"executor returned success=False for a request that "
        f"found a safe focused window and dispatched. "
        f"status={result.status!r} error={result.error!r}"
    )
    assert result.verified is True
    # Actual dispatch happened.
    assert fake_os.provider.type_attempts == 1


def test_e_workflow_successful_gui_action_completes():
    """Workflow integration of scenario E."""
    user32 = _FakeUser32(focused_title="Untitled - Notepad", focused_hwnd=12345)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    executor = ActionExecutor(os_manager=fake_os)
    engine = UniversalDesktopWorkflowEngine(executor, os_manager=fake_os)

    plan = ActionPlan(
        operation="gui.type_text",
        target=None,
        parameters={"text": "Hello", "confirmed": True},
    )
    workflow = WorkflowPlan(
        objective="type Hello",
        steps=(
            WorkflowStep(step_id="step-1", plan=plan, depends_on=()),
        ),
    )

    result = engine.execute(workflow)

    assert result.success is True
    assert result.final_verified is True
    assert result.status == "completed"
    assert fake_os.provider.type_attempts == 1


# =========================================================
# F. Failed / unverified GUI action must never become successful
# =========================================================


def test_f_unverified_dispatch_does_not_become_successful():
    """Scenario F.

    When the provider's dispatch returns success=True but
    the runtime focus resolver's post-state observation
    determines focus was NOT retained (or the provider
    reports verified=False), the executor MUST return
    verified=False and the workflow engine MUST NOT
    report completed.

    This is the carve-out that previously converted
    unverified / unsafe-target cases into fake-success.
    """
    user32 = _FakeUser32(focused_title="Untitled - Notepad", focused_hwnd=12345)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    # Make the provider report failure / unverified.
    fake_os.provider.dispatches_succeed = False
    executor = ActionExecutor(os_manager=fake_os)
    engine = UniversalDesktopWorkflowEngine(executor, os_manager=fake_os)

    plan = ActionPlan(
        operation="gui.type_text",
        target=None,
        parameters={"text": "Hello", "confirmed": True},
    )
    workflow = WorkflowPlan(
        objective="type Hello",
        steps=(
            WorkflowStep(step_id="step-1", plan=plan, depends_on=()),
        ),
    )

    result = engine.execute(workflow)

    # The dispatch was attempted but the provider reported
    # failure. Verified must remain False.
    assert result.success is False
    assert result.final_verified is False
    assert result.status != "completed"
    assert fake_os.provider.type_attempts == 1  # the attempt happened


def test_f_unsafe_console_target_rejected():
    """The runtime focus resolver MUST refuse to type into
    a console / REPL / no-title window. This is the
    general safety guard; not application-specific.
    """
    # A focused window with a console-like title.
    user32 = _FakeUser32(focused_title="Windows PowerShell", focused_hwnd=99)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    executor = ActionExecutor(os_manager=fake_os)

    plan = ActionPlan(
        operation="gui.type_text",
        target=None,
        parameters={"text": "hello", "confirmed": True},
    )

    result = executor.execute(plan)

    # The resolver refused.
    assert result.success is False
    assert result.verified is False
    assert result.status == "unresolved_target"
    # The provider was NOT called.
    assert fake_os.provider.type_attempts == 0


def test_f_empty_title_focused_window_rejected():
    """A foreground window with an empty / missing title is
    also refused. This is a common Windows case (background
    processes with no title).
    """
    user32 = _FakeUser32(focused_title="", focused_hwnd=42)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    executor = ActionExecutor(os_manager=fake_os)

    plan = ActionPlan(
        operation="gui.type_text",
        target=None,
        parameters={"text": "hello", "confirmed": True},
    )

    result = executor.execute(plan)

    assert result.success is False
    assert result.verified is False
    assert result.status == "unresolved_target"
    assert fake_os.provider.type_attempts == 0


def test_f_focus_retained_post_dispatch_required():
    """The runtime focus resolver re-inspects the foreground
    window AFTER dispatch. When the foreground window
    changes during dispatch (simulated by having the user32
    point at a different hwnd post-dispatch) the executor
    MUST report verification_failed with verified=False.

    This guards against the case where the dispatch
    succeeds but the keystrokes may have landed in the
    wrong window because focus shifted mid-call.
    """
    user32 = _FakeUser32(focused_title="Untitled - Notepad", focused_hwnd=12345)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    # Configure the provider to shift focus during dispatch
    # so the post-state observation fails.
    fake_os.provider.shift_focus_mid_dispatch = True
    executor = ActionExecutor(os_manager=fake_os)

    plan = ActionPlan(
        operation="gui.type_text",
        target=None,
        parameters={"text": "Hello", "confirmed": True},
    )

    result = executor.execute(plan)

    # The dispatch ran but verification caught the focus shift.
    assert result.executed is True
    assert result.verified is False
    assert result.status == "verification_failed"


def test_content_readback_is_required_when_focus_is_retained():
    user32 = _FakeUser32(focused_title="Untitled - Notepad", focused_hwnd=12345)
    fake_os = _FakeOSManagerWithGUI(user32=user32)
    fake_os.provider.type_text = lambda *args, **kwargs: {
        "success": True,
        "operation": "type_text",
        "executed": True,
        "verified": False,
        "data": {"content_match": False, "observed_text": ""},
    }
    fake_os.provider.read_focused_text = lambda: {
        "success": True,
        "data": {"text": "", "readable": False, "method": "none"},
    }
    result = ActionExecutor(os_manager=fake_os).execute(
        ActionPlan(
            operation="gui.type_text",
            target=None,
            parameters={"text": "Hello", "confirmed": True},
        )
    )

    assert result.success is True
    assert result.executed is True
    assert result.verified is False
    assert result.status in {"verification_failed", "verification_unavailable"}
