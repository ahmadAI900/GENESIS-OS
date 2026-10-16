"""Item 5C -- APPLICATION_OPERATIONS must have exactly one definition.

`ActionPlan` declared `APPLICATION_OPERATIONS` as a hand-authored
frozenset of 121 operation strings and then, on the very next line,
assigned `APPLICATION_OPERATIONS = CAPABILITIES`. The literal was
therefore dead on arrival: nothing could ever observe it.

INTENT, determined from usage (so the literal was the wrong half):

  * workflow_planner.py:12 `_full_supported_operations()` exists
    precisely to bypass this constant and reach the executor's full set.
  * agents/compound_task_router.py:289 says it "deliberately do[es] NOT
    call action_plan.validate() here with the strict
    APPLICATION_OPERATIONS default".
  * validate()'s own docstring says "the planner and the executor pass
    the full SUPPORTED_OPERATIONS set".

So the full capability set is the contract. The literal was stale,
missing 20 registered capabilities, and restoring it would have made
the four `validate()` call sites that pass no allow-list reject them.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import genesis_os.action_plan as ap
from genesis_os.action_plan import ActionPlan, CAPABILITIES


def _class_level_definitions() -> list:
    """Every class-level definition of APPLICATION_OPERATIONS."""
    tree = ast.parse(Path(ap.__file__).read_text(encoding="utf-8"))
    found = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for stmt in cls.body:
            targets = []
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
                value = stmt.value
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]
                value = stmt.value
            else:
                continue
            if any(getattr(t, "id", None) == "APPLICATION_OPERATIONS"
                   for t in targets):
                found.append(ast.unparse(value))
    return found


def test_there_is_exactly_one_definition():
    """The literal and the alias must not both exist.

    Two definitions is the original bug: whichever comes last wins and
    the other is unreachable.
    """
    definitions = _class_level_definitions()
    assert len(definitions) == 1, (
        f"APPLICATION_OPERATIONS is defined {len(definitions)} times: "
        f"{definitions}"
    )


def test_the_definition_is_the_full_capability_set():
    assert ActionPlan.APPLICATION_OPERATIONS == CAPABILITIES, (
        "validate() defaults to this, and four call sites pass no "
        "allow-list; it must therefore cover every registered "
        "capability or those calls reject valid ones"
    )


def test_no_dead_frozenset_literal_remains():
    """The stale 121-entry literal must be gone, not merely shadowed."""
    source = Path(ap.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    dead = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for stmt in cls.body:
            if (isinstance(stmt, (ast.Assign, ast.AnnAssign))
                    and any(getattr(getattr(stmt, "target", None)
                                    or getattr(stmt, "targets", [None])[0],
                                    "id", None) == "APPLICATION_OPERATIONS"
                           for _ in [0])):
                value = stmt.value
                if isinstance(value, ast.Call) and getattr(
                        value.func, "id", None) == "frozenset":
                    dead.append(stmt.lineno)
    assert not dead, (
        f"APPLICATION_OPERATIONS is still built by an inline frozenset at "
        f"line(s) {dead}; it must be the single CAPABILITIES reference"
    )


@pytest.mark.parametrize("operation", [
    # Capabilities that existed ONLY because the alias overrode the
    # literal. If the literal is ever restored, these break.
    "document.create_txt",
    "document.read_intel",
    "document.search_intel",
    "document.inspect",
    "document.create_pdf",
    "browser.get_page_state",
    "browser.find_text",
    "browser.capabilities",
    "application.window_list",
])
def test_capabilities_outside_the_old_literal_still_validate(operation):
    """The 20 that the stale literal omitted must still be accepted."""
    plan = ActionPlan(operation=operation, target="C:/x.txt")
    plan.validate()  # must not raise ActionPlanValidationError


def test_a_genuinely_unknown_operation_is_still_rejected():
    """Honesty in both directions: the set must not have become lax."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Unknown Genesis capability"):
        ActionPlan(operation="totally.made_up", target="C:/")


def test_validate_rejects_an_operation_outside_an_explicit_allowlist():
    """The supported_operations parameter must still narrow the set."""
    from genesis_os.action_plan import ActionPlanValidationError

    plan = ActionPlan(operation="file.read", target="C:/x.txt")
    with pytest.raises(ActionPlanValidationError):
        plan.validate(supported_operations={"file.delete"})


def test_the_workaround_in_workflow_planner_is_still_correct():
    """It asserts the full executor set; that must still hold."""
    from genesis_os.workflow_planner import _full_supported_operations
    from genesis_os.action_executor import ActionExecutor

    full = _full_supported_operations()
    assert full == frozenset(ActionExecutor.SUPPORTED_OPERATIONS)
    assert full == frozenset(CAPABILITIES)