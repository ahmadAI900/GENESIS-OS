"""
Live verification for Phase 1 ActionPlan Pydantic contract.

Demonstrates that the new Pydantic-based ActionPlan now
rejects malformed/unsafe states at construction time
BEFORE they reach the executor.

Cases verified:
  1. SUCCESS: gui.type_text with target=None is ACCEPTED
     (Phase 0 bug fixed in Phase 1 blocker-fix; guarded
     here to prove the Pydantic model did not regress it.)
  2. SUCCESS: gui.type_text with target=None via
     from_decision() also works.
  3. MALFORMED REJECTED: empty operation string -> rejected.
  4. MALFORMED REJECTED: non-string operation -> rejected.
  5. MALFORMED REJECTED: operation=None -> rejected.
  6. MALFORMED REJECTED: non-targetless operation with
     target=None -> rejected.
  7. MALFORMED REJECTED: nonsense unknown operation ->
     construction succeeds (validate() is the
     registry-membership boundary), but plan.validate()
     rejects it as expected.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from genesis_os.action_plan import (
    ActionPlan,
    ActionPlanValidationError,
)
from pydantic import ValidationError as PydanticValidationError


GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"


def _green(text):
    return f"{GREEN}{text}{RESET}"


def _red(text):
    return f"{RED}{text}{RESET}"


def main() -> int:
    failures = []

    # --------------------------------------------------------------
    # 1. SUCCESS: gui.type_text with target=None
    # --------------------------------------------------------------
    try:
        plan = ActionPlan(
            operation="gui.type_text",
            target=None,
            parameters={"text": "hello ahmad"},
        )
        assert plan.operation == "gui.type_text"
        assert plan.target is None
        assert plan.parameters["text"] == "hello ahmad"
        print(_green(
            "[OK] ActionPlan(gui.type_text, target=None, "
            "parameters={text:'hello ahmad'}) constructed"
        ))
    except Exception as exc:
        failures.append(
            f"gui.type_text with target=None was rejected: "
            f"{type(exc).__name__}: {exc}"
        )

    # --------------------------------------------------------------
    # 2. SUCCESS: from_decision() for gui.type_text with target=None
    # --------------------------------------------------------------
    try:
        decision = {
            "level": 3,
            "mode": "os",
            "operation": "gui.type_text",
            "target": None,
            "parameters": {"text": "hello ahmad"},
            "confidence": 0.95,
        }
        plan = ActionPlan.from_decision(decision)
        assert plan.operation == "gui.type_text"
        assert plan.target is None
        print(_green(
            "[OK] ActionPlan.from_decision(gui.type_text, "
            "target=None) constructed"
        ))
    except Exception as exc:
        failures.append(
            f"from_decision(gui.type_text, target=None) was "
            f"rejected: {type(exc).__name__}: {exc}"
        )

    # --------------------------------------------------------------
    # 3. MALFORMED: empty operation string
    # --------------------------------------------------------------
    try:
        ActionPlan(operation="", target="x")
        failures.append(
            "empty operation string was ACCEPTED — should "
            "have been rejected at construction"
        )
    except (ActionPlanValidationError, PydanticValidationError) as exc:
        print(_green(
            f"[OK] ActionPlan(operation='', target='x') rejected: "
            f"{type(exc).__name__}: {str(exc)[:80]}"
        ))

    # --------------------------------------------------------------
    # 4. MALFORMED: non-string operation
    # --------------------------------------------------------------
    try:
        ActionPlan(operation=42, target="x")
        failures.append(
            "non-string operation (42) was ACCEPTED — should "
            "have been rejected at construction"
        )
    except (ActionPlanValidationError, PydanticValidationError) as exc:
        print(_green(
            f"[OK] ActionPlan(operation=42, target='x') rejected: "
            f"{type(exc).__name__}: {str(exc)[:80]}"
        ))

    # --------------------------------------------------------------
    # 5. MALFORMED: None operation
    # --------------------------------------------------------------
    try:
        ActionPlan(operation=None, target="x")
        failures.append(
            "None operation was ACCEPTED — should have been "
            "rejected at construction"
        )
    except (ActionPlanValidationError, PydanticValidationError) as exc:
        print(_green(
            f"[OK] ActionPlan(operation=None, target='x') rejected: "
            f"{type(exc).__name__}: {str(exc)[:80]}"
        ))

    # --------------------------------------------------------------
    # 6. MALFORMED: non-targetless op with target=None
    # --------------------------------------------------------------
    try:
        ActionPlan(operation="application.open", target=None)
        failures.append(
            "application.open with target=None was ACCEPTED — "
            "should have been rejected at construction"
        )
    except (ActionPlanValidationError, PydanticValidationError) as exc:
        msg = str(exc)
        if "target" not in msg.lower():
            failures.append(
                f"application.open/target=None rejected but "
                f"message lacks 'target': {msg}"
            )
        else:
            print(_green(
                f"[OK] ActionPlan(application.open, target=None) "
                f"rejected: {type(exc).__name__}: {msg[:80]}"
            ))

    # --------------------------------------------------------------
    # 7. UNKNOWN op: construction succeeds, validate() rejects
    # --------------------------------------------------------------
    try:
        plan = ActionPlan(operation="bogus.unknown", target="x")
        print(_green(
            f"[OK] ActionPlan(operation='bogus.unknown', "
            f"target='x') constructed (registry check "
            f"happens in validate())"
        ))
        try:
            plan.validate()
            failures.append(
                "plan.validate() did NOT reject unknown op "
                "'bogus.unknown'"
            )
        except ActionPlanValidationError as exc:
            if "bogus.unknown" not in str(exc):
                failures.append(
                    f"validate() rejected but message lacks "
                    f"op name: {exc}"
                )
            else:
                print(_green(
                    f"[OK] plan.validate() rejected unknown op: "
                    f"{str(exc)[:80]}"
                ))
    except (ActionPlanValidationError, PydanticValidationError) as exc:
        failures.append(
            f"unknown op construction unexpectedly rejected: "
            f"{type(exc).__name__}: {exc}"
        )

    # --------------------------------------------------------------
    # Result
    # --------------------------------------------------------------
    print()
    if failures:
        print(_red("verify_actionplan_pydantic FAILED:"))
        for line in failures:
            print(_red(f"  - {line}"))
        return 1
    print(_green("verify_actionplan_pydantic PASSED"))
    print("  - gui.type_text with target=None is ACCEPTED (Phase 0 fix preserved)")
    print("  - empty / non-string / None operation is REJECTED at construction")
    print("  - non-targetless operation with target=None is REJECTED at construction")
    print("  - unknown op construction succeeds; plan.validate() rejects (safety boundary preserved)")
    return 0


if __name__ == "__main__":
    sys.exit(main())