"""Item 14F (S9): positional construction bypassed the grant guard.

`ActionPlan.__init__` supports positional arguments for backward
compatibility with the historical `@dataclass` signature
(`ActionPlan("application.open", "notepad")`). Its AuthorizationGrant
guard, however, lived INSIDE `if not args:`.

So supplying a single positional argument skipped the check entirely,
and `authorization` -- documented as "the trusted adapter->executor
channel" that "cannot be populated from model input" -- accepted
anything at all:

    ActionPlan("file.delete", "C:/x", authorization={"forged": True})

`authorization` is not one of the positional field names, so the
overlap check let it through as a keyword alongside positional args, and
the merged mapping went straight to `super().__init__()` unvalidated.

The guard now runs once, after positional binding, over the merged
mapping -- so both paths agree.

This is the only item in the batch that is a genuine security hole
rather than a correctness or honesty defect, and the tests are written
to be readable by someone auditing the channel rather than only by
someone running them.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from genesis_os.action_plan import ActionPlan


OP = "application.open"
TIER1 = "file.delete"


def _forgeries():
    """Values that must never populate the authorization field."""
    return [
        ("dict", {"forged": True}),
        ("dict_role", {"role": "admin", "approved": True}),
        ("empty_dict", {}),
        ("str", "totally-a-grant"),
        ("bool_true", True),
        ("bool_false", False),
        ("list", ["grant"]),
        ("int", 1),
        ("object", object()),
        ("bytes", b"grant"),
    ]


# --------------------------------------------------------------------------
# The core defect: both construction paths must agree
# --------------------------------------------------------------------------

@pytest.mark.parametrize("label,value", _forgeries(), ids=lambda v: v if isinstance(v, str) else None)
def test_keyword_path_refuses_forged_authorization(label, value):
    """The path that already worked. Pinned so the two cannot diverge."""
    with pytest.raises(TypeError, match="AuthorizationGrant"):
        ActionPlan(
            operation=TIER1,
            target="C:/secret.txt",
            authorization=value,
        )


@pytest.mark.parametrize("label,value", _forgeries(), ids=lambda v: v if isinstance(v, str) else None)
def test_positional_path_refuses_forged_authorization(label, value):
    """The path that did NOT. This is the regression."""
    with pytest.raises(TypeError, match="AuthorizationGrant"):
        ActionPlan(TIER1, "C:/secret.txt", authorization=value)


def test_a_bare_pair_of_positionals_is_still_accepted():
    """The backward-compat behaviour this override exists for."""
    plan = ActionPlan(OP, "notepad")

    assert plan.operation == OP
    assert plan.target == "notepad"
    assert plan.authorization is None


def test_positional_binding_still_maps_the_declared_order():
    plan = ActionPlan(OP, "notepad", "notepad.exe", "focus the window", 0.9)

    assert plan.operation == OP
    assert plan.target == "notepad"
    assert plan.application == "notepad.exe"
    assert plan.task == "focus the window"
    assert plan.confidence == 0.9


def test_positional_and_keyword_overlap_is_still_refused():
    with pytest.raises(TypeError, match="both positional and keyword"):
        ActionPlan(OP, operation="application.close")


def test_too_many_positional_arguments_is_still_refused():
    with pytest.raises(TypeError, match="at most"):
        ActionPlan(*range(12))


# --------------------------------------------------------------------------
# A real grant must still work on both paths
# --------------------------------------------------------------------------

def _valid_grant(capability_id, arguments):
    from genesis_os.approval_store import ApprovalStore
    from genesis_os.authorization_grant import issue_authorization_grant

    token = ApprovalStore.issue_token(capability_id, dict(arguments))
    ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])
    return issue_authorization_grant(
        operation=capability_id, arguments=dict(arguments), token=token
    )


def test_a_real_grant_is_still_accepted_on_the_keyword_path():
    grant = _valid_grant(TIER1, {"path": "C:/authorised.txt"})

    plan = ActionPlan(
        operation=TIER1,
        target="C:/authorised.txt",
        authorization=grant,
    )

    assert plan.authorization is grant


def test_a_real_grant_is_still_accepted_on_the_positional_path():
    """The fix must not have over-corrected into refusing everything."""
    grant = _valid_grant(TIER1, {"path": "C:/authorised.txt"})

    plan = ActionPlan(TIER1, "C:/authorised.txt", authorization=grant)

    assert plan.authorization is grant, (
        "a genuine, human-approved grant was refused on the positional "
        "path; the guard is now too strict"
    )


def test_no_authorization_at_all_is_fine_on_both_paths():
    assert ActionPlan(OP, "notepad").authorization is None
    assert ActionPlan(operation=OP, target="notepad").authorization is None


# --------------------------------------------------------------------------
# Structural guard: the guard cannot drift back inside one branch
# --------------------------------------------------------------------------

def test_the_guard_is_not_nested_inside_a_positional_check():
    """`if not args: <guard>` is the exact shape that caused this.

    Reads the source rather than behaviour, because the failure mode is
    a refactor moving the check back under a branch -- which every
    behavioural test here would still pass.
    """
    import ast

    path = Path(ActionPlan.__module__.replace(".", "\\") + ".py") \
        if False else Path("genesis_os") / "action_plan.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))

    init = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "__init__"
        and getattr(n, "lineno", 0) > 500
    )

    # Direct expression: no `if` inside __init__ that branches on the
    # positional `args` may also contain the guard. `if not args:` was
    # the exact shape that caused the bypass.
    def _branches_on_args(node):
        return any(
            isinstance(n, ast.Name) and n.id == "args"
            for n in ast.walk(node.test)
        )

    offenders = []
    for node in ast.walk(init):
        if isinstance(node, ast.If) and _branches_on_args(node):
            for stmt in node.body:
                for n in ast.walk(stmt):
                    if (
                        isinstance(n, ast.Call)
                        and getattr(n.func, "id", None)
                        == "_is_authorization_grant"
                    ):
                        offenders.append(node.lineno)

    assert not offenders, (
        f"a branch on `args` at line(s) {offenders} also contains the "
        "AuthorizationGrant guard; that nesting is what let the "
        "positional path skip it"
    )


def test_both_paths_share_one_guard_call_site():
    """Simpler structural backstop: exactly one guard, at top level."""
    import ast

    path = Path("genesis_os") / "action_plan.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))

    init = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "__init__"
        and getattr(n, "lineno", 0) > 500
    )

    # At the top level of __init__ (not nested), how many statements
    # call _is_authorization_grant?
    top_level_calls = sum(
        1
        for stmt in init.body
        for n in ast.walk(stmt)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", None) == "_is_authorization_grant"
    )

    assert top_level_calls == 1, (
        f"expected exactly one _is_authorization_grant call reachable "
        f"from the top level of __init__, found {top_level_calls}"
    )


# --------------------------------------------------------------------------
# End to end: the forged value must not authorise anything
# --------------------------------------------------------------------------

def test_a_forged_authorization_cannot_reach_the_os_manager():
    """Even if construction were bypassed, the manager is never called."""
    from unittest.mock import MagicMock

    from genesis_os.semantic_adapter import SemanticCapabilityAdapter

    class _RecordingOSM:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            def call(*a, **k):
                self.calls.append(name)
                return {"success": True, "executed": True, "verified": True}

            return call

    osm = _RecordingOSM()
    adapter = SemanticCapabilityAdapter(osm)

    result = adapter.invoke(
        "file_delete",
        {"path": "C:/secret.txt", "authorization": {"forged": True}},
    )

    assert osm.calls == [], (
        f"a forged grant reached the OS manager: {osm.calls}"
    )
    assert result.get("status") == "confirmation_required", result