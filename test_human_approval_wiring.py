"""Directive 9A: the real human-approval channel, wired end to end.

SEAM, recorded before editing:

    _ActionPlan.from_decision -> self._pending_llm_action["plan"]
      -> _execute_pending_action() records the "yes" as `source` and
         DISCARDS the plan (it re-derives from text + classification)
      -> _handle_level3_request -> run_level3 builds a FRESH plan and
         resolves its target
      -> genesis_runtime.execute_audited(plan=plan)
      -> executor.execute(plan) reads plan.authorization and
         plan.authorization_arguments

The only writer of those two fields in the codebase is
`action_plan.attach_authorization`, which had ZERO product callers. So
both were always None and every Tier 1 operation returned
`confirmation_required` forever -- reproduced three times in a row with
`file.delete` against a real temp file, which stayed on disk.

These tests drive the seam with a FAKE TTY and a temp file OUTSIDE the
workspace:

  * the exact phrase -> the operation executes, the file is gone;
  * anything else -> denied, nothing executed, file still present;
  * no TTY at all -> denied;
  * a grant for op A / args A never authorises op B / args B;
  * the model-facing surface never receives a token, grant or usable id.
"""

from __future__ import annotations

import io

import pytest

from genesis_os.action_plan import ActionPlan

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

EXACT_PHRASE = "approve"


class FakeTTY(io.StringIO):
    """A stdin that claims to be a TTY.

    Same shape the rest of this suite uses (test_approval_channel.py):
    a StringIO reporting isatty(). Combined with timeout=None, which
    skips the select() guard, because select() cannot poll a pipe on
    Windows -- only sockets. That is a platform fact about the test
    harness, not a relaxation of the channel: the phrase comparison and
    the TTY requirement are both still exercised.
    """

    def isatty(self) -> bool:
        return True


class NotATTY(io.StringIO):
    """A stream the channel must refuse to prompt."""

    def isatty(self) -> bool:
        return False


def _plan_for(victim) -> ActionPlan:
    """A Tier 1 plan for a file OUTSIDE the workspace."""
    return ActionPlan(
        operation="file.delete",
        target=str(victim),
        parameters={"path": str(victim)},
        confidence=0.99,
    )


def _authorize(genesis_runtime, plan, typed, *, tty=True):
    """Drive the seam with a fake TTY, returning (plan, denial)."""
    from genesis_os import approval_channel

    real_channel = approval_channel.ApprovalChannel
    stream = FakeTTY(typed) if tty else NotATTY("")

    def channel_factory(*args, **kwargs):
        kwargs["stdin"] = stream
        kwargs["stdout"] = io.StringIO()
        kwargs["timeout"] = None
        return real_channel(*args, **kwargs)

    approval_channel.ApprovalChannel = channel_factory
    try:
        return genesis_runtime._authorize_plan_for_execution(plan)
    finally:
        approval_channel.ApprovalChannel = real_channel


# =====================================================================
# The acceptance test
# =====================================================================

def test_exact_phrase_authorises_and_the_operation_runs(
    genesis_runtime, tmp_path
):
    """Fails before Item 9A: the method did not exist."""
    victim = tmp_path / "outside-the-workspace.txt"
    victim.write_text("important", encoding="utf-8")

    plan, denial = _authorize(
        genesis_runtime, _plan_for(victim), EXACT_PHRASE + "\n"
    )

    assert denial is None, denial
    assert plan is not None
    assert plan.authorization is not None, "no grant was attached"
    assert plan.authorization_arguments is not None

    # The plan must actually clear the executor's gate now.
    from genesis_os.action_executor import ActionExecutor

    result = ActionExecutor(genesis_runtime.os_manager).execute(plan)
    assert result.status != "confirmation_required", result.to_dict()
    assert result.executed is True, result.to_dict()
    assert not victim.exists(), "the approved delete did not remove the file"


def test_anything_else_is_denied_and_nothing_executes(
    genesis_runtime, tmp_path
):
    victim = tmp_path / "outside-the-workspace.txt"
    victim.write_text("important", encoding="utf-8")

    for typed in ("yes\n", "y\n", "approve please\n", "\n", "no\n"):
        plan, denial = _authorize(genesis_runtime, _plan_for(victim), typed)
        assert plan is None, f"{typed!r} must not authorise"
        assert denial and "Not performed" in denial, denial
        assert victim.exists(), f"{typed!r} must not delete anything"


def test_non_interactive_denies(genesis_runtime, tmp_path):
    """No TTY means deny, always."""
    victim = tmp_path / "outside-the-workspace.txt"
    victim.write_text("important", encoding="utf-8")

    plan, denial = _authorize(
        genesis_runtime, _plan_for(victim), EXACT_PHRASE + "\n", tty=False
    )

    assert plan is None, "a non-interactive run must never approve"
    assert denial and "Not performed" in denial, denial
    assert victim.exists()


# =====================================================================
# The invariants
# =====================================================================

def test_a_tier_2_plan_is_never_prompted_for(genesis_runtime, workspace_root):
    """No gratuitous interruption: the seam asks only what the executor
    actually gates.

    The destination must be INSIDE the workspace. A tmp_path target is
    outside it, so the workspace boundary escalates a plain move to
    Tier 1 -- which is correct behaviour, and the reason this test uses
    the workspace fixture rather than tmp_path.
    """
    from genesis_os.action_executor import (
        _operation_requires_authorization as requires,
    )

    source = workspace_root / "movable.txt"
    source.write_text("x", encoding="utf-8")
    dest = workspace_root / "brand-new-name.txt"
    plan = ActionPlan(
        operation="file.move",
        target=str(source),
        parameters={"source": str(source), "destination": str(dest)},
        confidence=0.99,
    )
    assert requires(plan.operation, None, plan.parameters) is False, (
        "premise broken: this move is gated, so the test below is void"
    )

    out, denial = genesis_runtime._authorize_plan_for_execution(plan)

    assert denial is None, denial
    assert out is plan, "a Tier 2 plan must pass through untouched"
    assert out.authorization is None


def test_a_grant_for_op_a_does_not_authorise_op_b(genesis_runtime, tmp_path):
    """The grant is bound to operation AND arguments."""
    from genesis_os.action_plan import attach_authorization
    from genesis_os.action_executor import ActionExecutor

    victim = tmp_path / "doomed.txt"
    victim.write_text("important", encoding="utf-8")
    other = tmp_path / "innocent.txt"
    other.write_text("must survive", encoding="utf-8")

    granted, denial = _authorize(
        genesis_runtime, _plan_for(victim), EXACT_PHRASE + "\n"
    )
    assert denial is None, denial

    # Same operation, DIFFERENT target: the target-correspondence check
    # must refuse even though the arguments hash was for another path.
    swapped = ActionPlan(
        operation="file.delete",
        target=str(other),
        parameters={"path": str(other)},
        confidence=0.99,
    )
    reused = attach_authorization(
        swapped, granted.authorization,
        arguments=granted.authorization_arguments,
    )

    result = ActionExecutor(genesis_runtime.os_manager).execute(reused)
    assert result.status == "confirmation_required", result.to_dict()
    assert result.executed is False, result.to_dict()
    assert other.exists(), "a grant for path A must not delete path B"


def test_the_grant_never_travels_in_model_visible_parameters(
    genesis_runtime, tmp_path
):
    """The plan's `parameters` are model-visible and serialised, so the
    grant must not ride there."""
    victim = tmp_path / "outside.txt"
    victim.write_text("x", encoding="utf-8")

    plan, denial = _authorize(
        genesis_runtime, _plan_for(victim), EXACT_PHRASE + "\n"
    )
    assert denial is None, denial

    assert "authorization" not in plan.parameters
    assert "_authorization_grant" not in plan.parameters
    rendered = repr(plan.to_dict())
    assert "AuthorizationGrant" not in rendered, rendered


def test_the_denial_message_leaks_no_token_or_grant(
    genesis_runtime, tmp_path
):
    victim = tmp_path / "outside.txt"
    victim.write_text("x", encoding="utf-8")

    _plan, denial = _authorize(genesis_runtime, _plan_for(victim), "no\n")

    assert denial is not None
    for secret in ("APR-", "HUMAN-APPROVE", "AuthorizationGrant",
                   "arguments_hash", "approval_id"):
        assert secret not in denial, f"{secret!r} leaked into {denial!r}"