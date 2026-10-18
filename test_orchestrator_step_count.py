"""Directive 12C (R5): the step count logged must be the step count.

`AgentOrchestrator.create_intelligent_plan` logged `len(plan)`.

`IntelligentTaskSelector.create_plan` returns a DICT:

    {'task': task, 'steps': steps, 'agent_count': len(steps)}

so `len(plan)` is 3 -- the number of KEYS -- for every plan, whatever
the real step count. Reproduced before the fix:

    task: rename a file
      REAL step count: 1     len(plan) says: 3
    task: search the web, summarise it, then write a report
      REAL step count: 1     len(plan) says: 3

The orchestrator's other method, `create_plan`, already counted
correctly via `len(plan['steps'])` at line 39, which is what made the
omission visible: two adjacent methods reporting step counts, one of
them structurally incapable of being right.
"""

from __future__ import annotations

import ast
import io
import contextlib
import pathlib

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

BACKEND = pathlib.Path(__file__).resolve().parent
SRC = BACKEND / "agents" / "agent_orchestrator.py"


def _orchestrator():
    from agents.agent_orchestrator import AgentOrchestrator

    return AgentOrchestrator(registry=None, context=None)


def _captured(task: str) -> tuple[dict, str]:
    orch = _orchestrator()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        plan = orch.create_intelligent_plan(task)
    return plan, buf.getvalue()


def _logged_count(output: str) -> int:
    """Pull N out of 'created N step(s).'"""
    import re

    match = re.search(r"created (\d+) step\(s\)", output)
    assert match, f"no step count in output:\n{output}"
    return int(match.group(1))


# =====================================================================
# The reported number is the real number
# =====================================================================

def test_the_logged_count_matches_the_real_step_count():
    """The regression. Fails before Item 12C: logged 3 for a 1-step plan."""
    plan, output = _captured("rename a file")

    logged = _logged_count(output)
    actual = len(plan["steps"])

    assert logged == actual, (
        f"logged {logged} step(s) but the plan holds {actual}; "
        f"len(plan) counts the dict's KEYS, not its steps"
    )


def test_it_is_not_just_the_number_of_keys():
    """Pins the specific confusion rather than one example."""
    plan, output = _captured("search the web and write a report")

    assert _logged_count(output) != len(plan), (
        "the reported count equals len(plan); the dict's key count and "
        "the step count are being confused"
    )
    assert _logged_count(output) == len(plan["steps"])


def test_a_multi_step_plan_is_not_reported_as_three():
    """A plan whose real length differs from 3 must prove it."""
    plan, output = _captured("plan")

    # Whatever the selector produced, the log must agree with it.
    assert _logged_count(output) == len(plan["steps"]), (
        f"plan has {len(plan['steps'])} steps, log says "
        f"{_logged_count(output)}"
    )


def test_a_plan_with_exactly_three_steps_is_unambiguous():
    """Guard against a fix that only works when len(plan) != 3.

    Stubs a selector returning three steps, so the correct answer is
    also 3 -- a wrong implementation could pass by luck on every
    other fixture in this file.
    """
    orch = _orchestrator()

    class ThreeStepSelector:
        def create_plan(self, task):
            return {
                "task": task,
                "steps": [{"a": 1}, {"b": 2}, {"c": 3}],
                "agent_count": 3,
            }

    orch.selector = ThreeStepSelector()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        plan = orch.create_intelligent_plan("anything")

    assert len(plan["steps"]) == 3
    assert _logged_count(buf.getvalue()) == 3


# =====================================================================
# Structural: no bare len(plan)
# =====================================================================

def test_no_bare_len_of_plan_survives():
    """`len(plan)` on a dict is the bug shape, whatever the variable is
    called -- so scan for any of them."""
    tree = ast.parse(SRC.read_text(encoding="utf-8-sig"))
    offenders = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "len"
            and len(node.args) == 1
        ):
            arg = ast.unparse(node.args[0])
            if arg == "plan" or arg.startswith("plan") and "[" not in arg:
                offenders.append((node.lineno, arg))
    assert not offenders, (
        f"len({offenders}) counts a dict's keys, not its steps: "
        f"use len(plan['steps'])"
    )


def test_both_plan_methods_count_steps_the_same_way():
    """create_plan and create_intelligent_plan must agree."""
    source = SRC.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "len"
        ):
            calls.append(ast.unparse(node.args[0]) if node.args else "")

    subscripted = [c for c in calls if "['steps']" in c or '["steps"]' in c]
    assert len(subscripted) >= 2, (
        f"both create_plan and create_intelligent_plan should count "
        f"plan['steps']; found {subscripted}"
    )


def test_the_returned_plan_is_untouched():
    """Only the log line changed."""
    plan, _ = _captured("rename a file")
    assert isinstance(plan, dict)
    assert "steps" in plan
    assert "task" in plan
    assert isinstance(plan["steps"], list)