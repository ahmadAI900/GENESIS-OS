"""
Genesis OS — Level 3 GUI Text Input + Compound Pipeline Integration.

End-to-end tests for the canonical compound GUI-typing
example and its generalized variants.

Background
----------

A real runtime failure was reproduced for the user request
"open notepad and write Hello from Genesis":

  * The router detected 2 L3 clauses.
  * ``application.open / notepad`` was recognized.
  * The workflow then failed with:
      "Genesis understood this as a multi-step objective,
       but could not safely execute every step"

The root cause was that
``WorkflowDecomposer._intent_to_action_plan`` built an
``ActionPlan`` for ``gui.type_text`` with ``target=None``
(the user did not name a window — the executor types into
whichever window currently has focus) and then called
``ActionPlan.validate`` with the default
``require_target=True``. The validator rejected the step,
so the decomposition was non-executable and the runtime
returned the clarification message.

The fix generalized the ``gui.*`` capability contract so
``target=None`` is structurally valid for interactions that
resolve their target at runtime through the focused window
or a runtime-selected element. The workflow engine was
also updated so a ``requires_runtime_resolution`` result
from a ``gui.type_text`` / ``gui.paste_text`` /
``gui.focus_window`` step is treated as a completed step
when there is no preceding ``application.open`` step in
the same plan — in that case the plan is structurally
valid and the executor defers final UI verification to
the runtime focus resolver.

When a compound plan *does* chain ``application.open``
followed by a targetless ``gui.type_text`` /
``gui.paste_text`` / ``gui.click``, the workflow engine
now resolves the app name from the preceding open step
and calls ``focus_window`` through the OSManager GUI
bridge BEFORE dispatching the GUI step. ``focus_window``
polls for the window to exist (up to ~3s with 200ms
sleeps) so a freshly launched app's window has time to
appear; if the window never appears, the step fails
honestly instead of typing blindly into whatever
window already had OS focus. Step 2's status is then
``verified`` (the focus call returned success and
``type_text`` ran), not ``requires_runtime_resolution``.

These tests assert the runtime contract for the fixed
behavior end-to-end. They use a mocked ``OSManager`` /
``GUIController`` so no real Notepad or browser is opened.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import Mock

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.objective_understanding import ObjectiveUnderstanding
from genesis_os.os_manager import OSManager
from genesis_os.workflow_decomposer import WorkflowDecomposer
from genesis_os.workflow_engine import UniversalDesktopWorkflowEngine


# =========================================================
# HELPERS
# =========================================================


class _FakeOSManager:
    """Minimal OSManager stand-in that records every call.

    Real OSManager is not instantiable on a headless host,
    but the ActionExecutor only calls the methods the
    mocked capabilities invoke. ``gui_action`` records the
    typed text so tests can assert the payload arrived
    intact.

    Includes a permissive ``inspect_application`` so the
    observation loop can verify application.open steps
    without failing the workflow.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

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
        self.calls.append(
            {"op": "application.inspect", "target": target, "kwargs": kwargs}
        )
        return {
            "success": True,
            "operation": "application.inspect",
            "target": target,
            "application": target,
            "running": True,
            "executed": True,
            "verified": True,
        }

    def web_search(self, query, engine="google", **kwargs):
        self.calls.append(
            {
                "op": "browser.search",
                "query": query,
                "engine": engine,
                "kwargs": kwargs,
            }
        )
        search_url = f"https://www.google.com/search?q={query.replace(' ', '%20')}"
        return {
            "success": True,
            "operation": "browser.search",
            "query": query,
            "engine": engine,
            "executed": True,
            "verified": True,
            "url": search_url,
            "requested_url": search_url,
            "title": f"{query} - Search",
            "message": f"Searched {query} on {engine}",
        }

    def browser_get_url(self, session_id="default"):
        return {
            "success": True,
            "operation": "browser.get_url",
            "url": "https://www.google.com/search?q=python%20tutorials",
            "verified": True,
        }

    def browser_get_title(self, session_id="default"):
        return {
            "success": True,
            "operation": "browser.get_title",
            "title": "Python tutorials - Google",
            "verified": True,
        }
    def gui_action(self, action, **kwargs):
        self.calls.append(
            {"op": f"gui.{action}", "kwargs": kwargs}
        )
        return {
            "success": True,
            "operation": f"gui.{action}",
            "executed": True,
            "verified": True,
            "message": f"GUI {action} succeeded",
            "data": {
                "content_match": action in {"type_text", "paste_text"},
                "observed_text": str(kwargs.get("text", "")) if action in {"type_text", "paste_text"} else "",
                "read_method": "value_pattern" if action in {"type_text", "paste_text"} else "none",
            },
            "metadata": {
                "verification_type": "focused_content_readback",
            } if action in {"type_text", "paste_text"} else {},
        }


def _build_workflow(objective_text: str):
    """Build the canonical WorkflowPlan through the
    public compound pipeline.

    Mirrors what ``GenesisOS._try_multi_step_workflow``
    does for a real L3 request:

      ObjectiveUnderstanding.understand
      → WorkflowDecomposer.decompose
      → WorkflowPlan
    """
    ou = ObjectiveUnderstanding(WorkflowDecisionEngine())
    understanding = ou.understand(objective_text)
    decomposition = WorkflowDecomposer().decompose(understanding)
    return understanding, decomposition


# =========================================================
# TEST 1 — canonical compound GUI-typing example
# =========================================================


def test_open_notepad_and_write_hello_from_genesis_executes_both_steps():
    """The canonical example from the directive.

    ``open notepad and write Hello from Genesis`` must
    produce a two-step WorkflowPlan
    ``[(application.open, notepad), (gui.type_text, None)]``
    and dispatch BOTH steps through the ActionExecutor
    without rejecting the second step for "missing
    target".
    """
    understanding, decomposition = _build_workflow(
        "open notepad and write Hello from Genesis"
    )

    # Understanding correctly splits at "and".
    assert len(understanding.steps) == 2
    assert understanding.fully_level3 is True
    assert understanding.executable is True

    # Decomposition produces two executable steps.
    assert decomposition.executable is True
    assert decomposition.workflow is not None
    assert len(decomposition.workflow.steps) == 2
    assert decomposition.rejected_steps == ()

    # Step 1: open notepad.
    first = decomposition.workflow.steps[0].plan
    assert first.operation == "application.open"
    assert first.target == "notepad"

    # Step 2: gui.type_text — target is None because the
    # user did not name a window. The capability contract
    # must accept target=None for this operation so the
    # focused window can be resolved at runtime.
    second = decomposition.workflow.steps[1].plan
    assert second.operation == "gui.type_text"
    assert second.target is None
    assert second.parameters.get("text") == "hello from genesis"

    # Sequential dependency: step 2 depends on step 1.
    assert decomposition.workflow.steps[0].depends_on == ()
    assert decomposition.workflow.steps[1].depends_on == ("step-1",)

    # Dispatch both steps through the real engine. Step 1
    # opens the app; the workflow engine detects that step 2
    # (gui.type_text with target=None) follows an
    # application.open, so it focuses the app's window before
    # dispatching the type_text call. Both steps end up
    # verified through real OSManager calls (no fake
    # "requires_runtime_resolution" placeholder).
    fake_os = _FakeOSManager()
    executor = ActionExecutor(os_manager=fake_os)
    engine = UniversalDesktopWorkflowEngine(
        executor,
        os_manager=fake_os,
    )

    result = engine.execute(decomposition.workflow)

    assert result.success is True
    assert result.final_verified is True
    assert result.status == "completed"
    assert len(result.steps) == 2

    ops = [c["op"] for c in fake_os.calls]
    assert "application.open" in ops
    # Step 2's pre-focus + dispatch both happen through
    # os_manager.gui_action: the workflow engine injects
    # a focus_window call before the type_text call. Both
    # must have been invoked and both must have completed
    # successfully for the workflow to be considered
    # verified.
    assert "gui.focus_window" in ops
    assert "gui.type_text" in ops
    assert result.steps[1]["operation"] == "gui.type_text"
    # The pre-focus metadata is recorded on the step
    # record so a human can confirm which window was
    # focused before the keystrokes were dispatched.
    assert result.steps[1].get("pre_focus_app") == "notepad"


# =========================================================
# TEST 2 — generalized GUI text input
# =========================================================


@pytest.mark.parametrize(
    "text,expected_intent,expected_text,expected_target_is_none",
    [
        # user did NOT name a window — target stays None and
        # the executor types into whichever window is focused.
        ("write Hello from Genesis", "gui.type_text", "hello from genesis", True),
        ('type "Hello World"', "gui.type_text", "hello world", True),
        ("enter text foo bar", "gui.type_text", "foo bar", True),
        ("fill in the form", "gui.type_text", "the form", True),
        # user DID name a window — the planner keeps the
        # window as target so the executor can focus_window
        # before typing.
        ("input baz in notepad", "gui.type_text", "baz", False),
        # "paste" routes to gui.paste_text, not gui.type_text.
        ("paste Hello", "gui.paste_text", "hello", True),
    ],
)
def test_gui_type_text_routes_for_generalized_user_phrasing(
    text, expected_intent, expected_text, expected_target_is_none
):
    """Verify generalized routing, not Notepad-specific logic.

    The decision engine must route ANY user phrasing that
    means "type this text into the focused window" to the
    Level-3 ``gui.type_text`` (or ``gui.paste_text``)
    capability, regardless of which application is
    involved.
    """
    de = WorkflowDecisionEngine()
    decision = de.decide(text)

    assert decision.get("level") == 3
    assert decision.get("mode") == "os"
    assert decision.get("intent") == expected_intent
    assert decision.get("parameters", {}).get("text") == expected_text

    # The decision must produce a structurally valid
    # ActionPlan regardless of whether the user named a
    # window. The planner layer must NOT reject either
    # shape (named target OR focused-window fallback).
    understanding = ObjectiveUnderstanding(de).understand(text)
    assert understanding.executable is True
    decomposition = WorkflowDecomposer().decompose(understanding)
    assert decomposition.executable is True
    assert decomposition.workflow is not None
    assert decomposition.workflow.steps[0].plan.operation == expected_intent
    if expected_target_is_none:
        assert decomposition.workflow.steps[0].plan.target is None
    else:
        assert decomposition.workflow.steps[0].plan.target == "notepad"


# =========================================================
# TEST 3 — Chrome + search compound browser workflow
# =========================================================


def test_open_chrome_and_search_python_tutorials_still_works():
    """Compound browser workflow must continue to work.

    This is the pre-existing canonical compound L3
    example. The fix for gui.type_text must NOT
    regress this path.
    """
    fake_os = _FakeOSManager()
    executor = ActionExecutor(os_manager=fake_os)
    engine = UniversalDesktopWorkflowEngine(
        executor,
        os_manager=fake_os,
    )

    understanding, decomposition = _build_workflow(
        "Open Chrome and search for Python tutorials"
    )

    assert understanding.fully_level3 is True
    assert decomposition.executable is True
    assert len(decomposition.workflow.steps) == 2

    operations = [
        s.plan.operation for s in decomposition.workflow.steps
    ]
    assert operations == ["application.open", "browser.search"]

    targets = [s.plan.target for s in decomposition.workflow.steps]
    assert targets[0] == "chrome"
    assert "python tutorials" in (targets[1] or "").lower()

    result = engine.execute(decomposition.workflow)

    assert result.success is True
    assert result.final_verified is True
    assert {c["op"] for c in fake_os.calls} >= {
        "application.open",
        "browser.search",
    }


# =========================================================
# TEST 4 — old failure path no longer rejects valid compound
# =========================================================


def test_old_failure_path_no_longer_rejects_compound_gui_typing():
    """The old failure path was the runtime error
    ``Genesis understood this as a multi-step objective,
    but could not safely execute every step: …``.

    It fired whenever the second clause of a compound
    L3 objective produced a gui.type_text intent with
    ``target=None``. After the fix the planner accepts
    the second clause as a structurally valid
    ``gui.type_text`` ActionPlan and the workflow engine
    treats it as a completed step.
    """
    understanding, decomposition = _build_workflow(
        "open notepad and write Hello from Genesis"
    )

    # The exact precondition for the old failure was
    # "decomposition.executable is False because at
    # least one intent could not be converted into a
    # valid ActionPlan". After the fix the decomposition
    # is executable end-to-end.
    assert decomposition.executable is True
    assert decomposition.requires_clarification is False
    assert decomposition.rejected_steps == ()

    # Both intents are executable Level-3 OS intents;
    # the gui.type_text step has executable_intent=True
    # because the capability exists and the operation
    # is resolved.
    step_intents = list(understanding.steps)
    assert all(s.is_level3 for s in step_intents)
    assert all(s.executable_intent for s in step_intents)
    assert any(
        s.operation == "gui.type_text" for s in step_intents
    )


# =========================================================
# TEST 5 — unsupported GUI targets fail honestly
# =========================================================


def test_unsupported_gui_target_fails_honestly_not_verified():
    """When the executor dispatches a gui.* plan to the
    GUIController and the controller cannot actually
    execute it (e.g. no focused window exists, or pyautogui
    is unavailable), the runtime must report a non-verified
    failure — not a fake success.

    A non-None ``target`` is used here so the executor
    actually reaches the dispatch step instead of taking
    the runtime-resolution shortcut for anaphoric
    targets. The ActionPlan also carries
    ``parameters.confirmed=True`` so the confirmation
    gate accepts it and the executor reaches dispatch.
    """
    os_manager = Mock(spec=OSManager)
    os_manager.gui_action.return_value = {
        "success": False,
        "operation": "gui.type_text",
        "executed": False,
        "verified": False,
        "message": (
            "GUI controller is unavailable: pyautogui is "
            "not installed on this host."
        ),
        "error": "GUI controller is unavailable.",
    }

    plan = ActionPlan(
        operation="gui.type_text",
        target="notepad",
        parameters={"text": "hello", "confirmed": True},
    )

    executor = ActionExecutor(os_manager=os_manager)
    result = executor.execute(plan)

    # The executor must NOT silently upgrade the failure
    # to verified=True. Honest reporting is required.
    assert result.success is False
    assert result.verified is False
    assert result.status != "verified"
    combined = (
        (result.error or "")
        + " "
        + (result.message or "")
    ).lower()
    assert "unavailable" in combined, (
        f"executor swallowed the GUI-controller failure: "
        f"error={result.error!r} message={result.message!r}"
    )


def test_unsupported_gui_target_via_workflow_fails_workflow():
    """Same honest reporting requirement at the workflow
    engine level: a workflow that depends on a gui.type_text
    step that the runtime cannot dispatch must NOT report
    final_verified=True.

    A non-None target is used on the gui.type_text step so
    the executor actually reaches the dispatch step. The
    GUIController reports failure; the workflow engine
    must NOT pretend the second step was verified.
    """
    os_manager = Mock(spec=OSManager)
    os_manager.open_application.return_value = {
        "success": True,
        "operation": "application.open",
        "target": "notepad",
        "executed": True,
        "verified": True,
    }
    os_manager.gui_action.return_value = {
        "success": False,
        "operation": "gui.type_text",
        "executed": False,
        "verified": False,
        "message": "GUI controller unavailable.",
        "error": "GUI controller unavailable.",
    }

    # Build a workflow manually so the second step has a
    # concrete target (the user said "in notepad") and the
    # executor reaches the dispatch stage instead of taking
    # the runtime-resolution shortcut.
    plans = [
        ActionPlan(operation="application.open", target="notepad"),
        ActionPlan(
            operation="gui.type_text",
            target="notepad",
            parameters={"text": "hello from genesis"},
        ),
    ]
    from genesis_os.workflow_models import (
        WorkflowPlan,
        WorkflowStep,
    )
    workflow = WorkflowPlan(
        objective="open notepad and write hello from genesis",
        steps=tuple(
            WorkflowStep(
                step_id=f"step-{i}",
                plan=p,
                depends_on=("step-1",) if i > 1 else (),
            )
            for i, p in enumerate(plans, start=1)
        ),
    )

    engine = UniversalDesktopWorkflowEngine(ActionExecutor(os_manager))
    result = engine.execute(workflow)

    # Step 1 succeeds and is verified. Step 2 fails
    # honestly. The workflow engine must NOT pretend
    # the second step was verified.
    assert result.success is False
    assert result.final_verified is False
    assert result.status != "completed"


def test_gui_type_text_with_no_focused_window_returns_unresolved_target():
    """When the user types a gui.type_text clause WITHOUT
    naming a window, the planner keeps target=None and the
    executor MUST still perform the runtime focus resolution
    (resolve the foreground window via user32, refuse unsafe
    targets, attempt the dispatch, verify focus was retained).

    With the Phase 0 carve-out removed, the executor no longer
    returns ``requires_runtime_resolution`` for GUI typing —
    that status was the false-success shortcut the workflow
    engine was promoting to ``verified=True`` without ever
    calling ``pyautogui.typewrite``.

    On a mocked OSManager with no GUI bridge and no user32,
    the resolver returns ``unresolved_target`` with
    ``verified=False``: the executor surfaces that as a
    real failure so the workflow engine cannot pretend the
    step was completed.
    """
    plan = ActionPlan(
        operation="gui.type_text",
        target=None,
        parameters={"text": "hello"},
    )

    os_manager = Mock(spec=OSManager)
    # The Mock's gui_action returns a MagicMock dict by
    # default. Treat it like an unresolved_target outcome
    # so the runtime focus resolver short-circuits to the
    # unresolved_target branch.
    os_manager.gui = None
    executor = ActionExecutor(os_manager=os_manager)
    result = executor.execute(plan)

    # The runtime focus resolver returned an unresolved
    # target — there is no real focused window to type into
    # on this host. The executor MUST surface that as a
    # non-verified failure, not a fake success.
    assert result.success is False
    assert result.verified is False
    assert result.status == "unresolved_target", (
        f"executor returned status={result.status!r}; the "
        f"Phase 0 carve-out removed the old "
        f"requires_runtime_resolution short-circuit. The "
        f"executor must now surface a real failure when "
        f"there is no safely-resolvable target."
    )
    # The OSManager GUI bridge was NOT consulted for
    # verification purposes — the resolver refused to
    # dispatch at all.
    os_manager.gui_action.assert_not_called()


# =========================================================
# TEST 6 — creative writing NOT misrouted to gui.type_text
# =========================================================


@pytest.mark.parametrize(
    "text",
    [
        "write a poem",
        "write a story about a cat",
        "write an essay",
        "write a paragraph about AI",
        "write a sentence about Chrome",
    ],
)
def test_creative_writing_is_not_routed_to_gui_type_text(text):
    """The gui.type_text capability is for typing literal
    text into a focused window. Creative-writing requests
    ("write a poem", "write an essay") are L1/L2
    intelligence tasks and must NOT be misrouted as
    gui.type_text — otherwise the runtime would silently
    type the literal phrase "a poem" into Notepad.
    """
    de = WorkflowDecisionEngine()
    decision = de.decide(text)
    intent = decision.get("intent")
    operation = decision.get("operation")
    if intent is None and operation is None:
        return  # already L1 conversation
    assert intent != "gui.type_text", (
        f"creative-writing phrase {text!r} was misrouted to "
        f"gui.type_text — runtime would have typed the "
        f"payload into the focused window instead of "
        f"producing creative content."
    )
    assert operation != "gui.type_text"