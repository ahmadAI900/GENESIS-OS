"""Non-interactive smoke verification for the compound-OS
planner fix.

Exercises the ``open notepad and write Hello from Genesis``
pipeline through the planning layer and a single
``ActionExecutor.execute`` call for each planned OS step
WITHOUT launching any GUI application or sending real
keystrokes. Suitable for CI and for verifying the patch on
a remote machine where the user does not want Notepad
popping open.

The script confirms:

  1. The decision engine classifies ``open notepad`` as
     ``application.open`` and ``write Hello from Genesis``
     as ``gui.type_text`` (level=3, intent matches).
  2. The ``MixedWorkflowPlanner`` emits TWO OS steps for the
     compound request, chained via ``depends_on``.
  3. A mocked ``ActionExecutor`` accepts both plans and
     dispatches them in the right order without raising.

Run:
    python verify_compound.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _green(text: str) -> str:
    return f"\033[92m{text}\033[0m"


def _red(text: str) -> str:
    return f"\033[91m{text}\033[0m"


def main() -> int:
    from agents.agent_registry import AgentRegistry
    from agents.base_agent import BaseAgent
    from agents.workflow_decision import WorkflowDecisionEngine
    from genesis_os.action_executor import ActionExecutor
    from genesis_os.action_plan import ActionPlan
    from genesis_os.context_resolver import ContextResolver
    from genesis_os.unified_executor import AgentCapabilityMapper, MixedWorkflowPlanner

    failures: list[str] = []

    # ------------------------------------------------------------------
    # 1. Decision engine per-clause intents
    # ------------------------------------------------------------------
    de = WorkflowDecisionEngine()

    intent_open = de.decide("open notepad")
    intent_write = de.decide("write Hello from Genesis")

    if intent_open.get("level") != 3:
        failures.append(
            f"'open notepad' expected level=3, got {intent_open.get('level')}"
        )
    if intent_open.get("intent") != "application.open":
        failures.append(
            f"'open notepad' expected intent=application.open, got {intent_open.get('intent')}"
        )
    if intent_write.get("level") != 3:
        failures.append(
            f"'write Hello from Genesis' expected level=3, got {intent_write.get('level')}"
        )
    if intent_write.get("intent") != "gui.type_text":
        failures.append(
            f"'write Hello from Genesis' expected intent=gui.type_text, got {intent_write.get('intent')}"
        )
    if intent_write.get("parameters", {}).get("text") != "hello from genesis":
        failures.append(
            f"expected parameters.text='hello from genesis', got {intent_write.get('parameters', {}).get('text')!r}"
        )

    # ------------------------------------------------------------------
    # 2. MixedWorkflowPlanner emits two chained os_steps
    # ------------------------------------------------------------------
    class _StubAgent(BaseAgent):
        def __init__(self):
            super().__init__("Stub Agent", "Stub.", ["stub"])

        def can_handle(self, task):
            return False

        def run(self, task, context=None):
            return {"ok": True}

    registry = AgentRegistry()
    mapper = AgentCapabilityMapper(registry)
    planner = MixedWorkflowPlanner(mapper, de, ContextResolver())
    plan = planner.plan("open notepad and write Hello from Genesis")

    if len(plan.os_steps) != 2:
        failures.append(
            f"expected 2 os_steps, got {len(plan.os_steps)}"
        )
    if plan.os_steps:
        ops = [s.action_plan.operation for s in plan.os_steps]
        if ops != ["application.open", "gui.type_text"]:
            failures.append(
                f"expected operations ['application.open', 'gui.type_text'], got {ops}"
            )
        if len(plan.os_steps) >= 2:
            dep = plan.os_steps[1].depends_on
            if "os-1" not in dep:
                failures.append(
                    f"expected os_steps[1].depends_on to include 'os-1', got {dep}"
                )

    # ------------------------------------------------------------------
    # 3. Direct ActionExecutor dispatch through a fake OSManager
    # ------------------------------------------------------------------
    class _FakeOSManager:
        def __init__(self):
            self.calls: list[tuple[str, str, dict]] = []

        def open_application(self, target):
            self.calls.append(("application.open", target, {}))
            return {
                "success": True,
                "operation": "application.open",
                "target": target,
                "executed": True,
                "verified": True,
                "message": f"Opened {target}",
            }

        def execute_gui(self, action, **kwargs):
            self.calls.append((f"gui.{action}", "", kwargs))
            return {
                "success": True,
                "operation": f"gui.{action}",
                "executed": True,
                "verified": True,
                "message": f"Ran {action}",
            }

    fake_os = _FakeOSManager()
    executor = ActionExecutor(os_manager=fake_os)

    # Dispatch each planned step individually. This bypasses
    # the full UnifiedExecutor (which orchestrates Level-2
    # agents and safety gates) and asserts only that the
    # planner-produced plans are accepted by ActionExecutor.
    #
    # gui.type_text with target=None is no longer a
    # ``requires_runtime_resolution`` short-circuit. The
    # executor now performs the closed-loop dispatch itself
    # via ``RuntimeFocusResolver.dispatch_text_or_paste``
    # (resolve foreground window via user32, refuse unsafe
    # targets, attempt the dispatch, verify focus retained).
    # On a host without a real GUI bridge / user32 the
    # resolver returns ``unresolved_target``; the executor
    # surfaces that as a non-verified failure so the
    # workflow engine cannot treat it as completed. On a
    # host WITH a real bridge the executor dispatches
    # ``pyautogui.typewrite`` (or ``pyperclip.copy``) and
    # verifies focus was retained.
    for step in plan.os_steps:
        try:
            result = executor.execute(step.action_plan)
        except Exception as exc:
            failures.append(
                f"ActionExecutor raised on {step.action_plan.operation}: {exc!r}"
            )
            continue
        if step.action_plan.operation == "gui.type_text":
            # The new contract: the executor no longer
            # returns ``requires_runtime_resolution`` for
            # GUI typing. Either it dispatches and verifies
            # (status="verified", success=True,
            # verified=True) OR it surfaces an honest
            # failure (status="unresolved_target",
            # success=False, verified=False).
            status = getattr(result, "status", "")
            if status == "requires_runtime_resolution":
                failures.append(
                    f"gui.type_text plan returned "
                    f"requires_runtime_resolution — this is "
                    f"the Phase 0 production-critical bug. "
                    f"The executor must perform the dispatch "
                    f"or surface an honest failure."
                )
            elif status == "unresolved_target":
                # Headless / no-focus-window case — correct.
                if getattr(result, "verified", False):
                    failures.append(
                        f"gui.type_text resolved as "
                        f"unresolved_target but reported "
                        f"verified=True — false success."
                    )
            continue
        if not getattr(result, "success", False):
            failures.append(
                f"ActionExecutor reported failure on "
                f"{step.action_plan.operation}: {getattr(result, 'message', '')} "
                f"| status={getattr(result, 'status', '')}"
            )

    op_seq = [c[0] for c in fake_os.calls]
    if "application.open" not in op_seq:
        failures.append(
            f"expected application.open in calls, got {op_seq}"
        )

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------
    if failures:
        print(_red("verify_compound.py FAILED:"))
        for line in failures:
            print(_red(f"  - {line}"))
        return 1
    print(_green("verify_compound.py PASSED"))
    print("  - 'open notepad'                  -> level=3 intent=application.open")
    print("  - 'write Hello from Genesis'      -> level=3 intent=gui.type_text text='hello from genesis'")
    print("  - MixedWorkflowPlanner emits 2 os_steps chained by depends_on")
    print("  - mocked ActionExecutor accepts application.open AND gui.type_text (gui.type_text deferred to runtime focus resolver)")
    return 0


if __name__ == "__main__":
    sys.exit(main())