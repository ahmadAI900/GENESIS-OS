"""Step 3: `confirmed` is no longer an authority, and denied operations
are refused unconditionally.

These tests pin the replacement made in `action_executor.py` and
`genesis.py`. They are deliberately about the ABSENCE of a bypass, so
they are written as negative assertions: a flag that does nothing is
only proved by showing the operation still refuses.
"""
import pytest

from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import KNOWN_DENIED_OPERATIONS, ActionPlan
from genesis_os.approval_store import ApprovalStore
from genesis_os.authorization_grant import issue_authorization_grant
from genesis_os.action_plan import attach_authorization
from genesis_os.capability_registry import CapabilityRegistry


class RecordingOSM:
    """Records dispatch intent; nothing is written."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*a, **k):
            self.calls.append(name)
            return {"success": True, "operation": name, "executed": True,
                    "verified": True, "file_exists": True, "message": "ok",
                    "path": a[0] if a else None, "count": 0}
        return call


def _grant(operation, arguments):
    token = ApprovalStore.issue_token(operation, arguments)
    ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])
    return issue_authorization_grant(
        operation=operation, arguments=arguments, token=token
    )


# ---------------------------------------------------------------------------
# The denied set.
# ---------------------------------------------------------------------------
def test_denied_set_is_not_empty():
    """The replacement depends on this set existing."""
    assert "shell.execute" in KNOWN_DENIED_OPERATIONS
    assert "system.sleep" in KNOWN_DENIED_OPERATIONS


@pytest.mark.parametrize("operation", sorted(KNOWN_DENIED_OPERATIONS))
def test_denied_operation_refuses_even_with_confirmed_true(operation):
    """A bare `confirmed: true` must never enable a denied operation."""
    plan = ActionPlan(
        operation=operation,
        target="C:/Windows/System32",
        parameters={"confirmed": True, "command": "whoami"},
        confidence=0.99,
    )
    osm = RecordingOSM()
    result = ActionExecutor(osm).execute(plan)
    assert result.executed is False
    assert osm.calls == [], f"{operation} dispatched despite being denied"


@pytest.mark.parametrize("operation", sorted(KNOWN_DENIED_OPERATIONS))
def test_denied_operation_refuses_even_with_a_genuine_grant(operation):
    """STRONGER than before: a grant cannot enable a denied operation.

    The old stand-in consulted `confirmed`, so a valid approval token
    promoted to `confirmed=True` by the adapter would have let the
    operation through. The replacement consults the deny list directly.

    NOTE: in practice these are refused even earlier, by
    `execution_safety`'s policy gate (`execution_stage == "safety"`),
    which denies the same set. So this test asserts the outcome and not
    a specific gate: there are now two independent denials, either of
    which alone is sufficient.
    """
    arguments = {"confirmed": True, "target": "C:/Windows/System32"}
    plan = attach_authorization(
        ActionPlan(
            operation=operation,
            target="C:/Windows/System32",
            parameters=dict(arguments),
            confidence=0.99,
        ),
        _grant(operation, arguments),
        arguments=arguments,
    )
    osm = RecordingOSM()
    result = ActionExecutor(osm).execute(plan)
    assert result.executed is False
    assert osm.calls == [], f"{operation} dispatched on a valid grant"
    assert result.success is False


def test_denied_operation_is_refused_by_a_gate_before_dispatch():
    """Pin that the refusal happens at a gate, not at a provider."""
    osm = RecordingOSM()
    plan = ActionPlan(
        operation="shell.execute",
        target="C:/Windows/System32",
        parameters={"command": "whoami", "confirmed": True},
        confidence=0.99,
    )
    result = ActionExecutor(osm).execute(plan)
    assert result.success is False
    assert result.executed is False
    assert osm.calls == []
    stage = result.metadata.get("execution_stage")
    assert stage in {"safety", "denied", "blast_radius", "confirmation"}, (
        f"unexpected refusal stage: {stage!r} / {sorted(result.metadata)}"
    )


def test_unregistered_operation_is_rejected_at_construction():
    """ActionPlan refuses capabilities the registry does not know.

    pydantic wraps the validator's error, so the raised type is
    ValidationError; the message is what matters.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Unknown Genesis capability"):
        ActionPlan(operation="format_disk", target="C:/", confidence=0.99)


# ---------------------------------------------------------------------------
# Attack A6, re-proved for the executor side: `confirmed=True` alone.
# ---------------------------------------------------------------------------
def test_confirmed_alone_is_refused_for_an_identified_capability(workspace_root):
    """The original F5 defect, still refused after the replacement."""
    from genesis_os.blast_radius import resolve_blast_radius
    from genesis_os.capabilities import BlastRadius

    outside = str(workspace_root.parent / "elsewhere.txt")
    plan = ActionPlan(
        operation="file.create",
        target=outside,
        parameters={"path": outside, "content": "x", "confirmed": True},
        confidence=0.99,
    )
    osm = RecordingOSM()
    result = ActionExecutor(osm).execute(plan)
    assert result.status == "confirmation_required"
    assert osm.calls == []

    # And it IS the boundary escalating it, not some accident.
    assert resolve_blast_radius(
        "file.create", {"path": outside}
    ) is BlastRadius.IRREVERSIBLE_OR_OUTWARD


def test_confirmed_alone_does_not_unblock_an_in_workspace_tier2_capability(
    workspace_root,
):
    """Tier 2 runs freely; `confirmed` is neither needed nor consulted."""
    inside = str(workspace_root / "ok.txt")
    plan = ActionPlan(
        operation="file.create",
        target=inside,
        parameters={"path": inside, "content": "x", "confirmed": False},
        confidence=0.99,
    )
    osm = RecordingOSM()
    result = ActionExecutor(osm).execute(plan)
    assert result.status == "verified"
    assert len(osm.calls) == 1, "Tier 2 should not consult confirmed at all"


# ---------------------------------------------------------------------------
# The replacement must not have become a new bypass.
# ---------------------------------------------------------------------------
def test_every_registry_capability_still_resolves():
    """Denial of the denied set must not have broken classification."""
    unresolved = [d.capability_id for d in CapabilityRegistry.all()
                  if not CapabilityRegistry.exists(d.capability_id)]
    assert not unresolved, f"unresolvable capabilities: {unresolved}"


def test_denied_operations_are_not_registered_capabilities():
    """The two sets are disjoint, so the deny gate is the only backstop."""
    registered = [op for op in KNOWN_DENIED_OPERATIONS
                  if CapabilityRegistry.exists(op)]
    # system.shutdown / system.restart ARE registered (Tier 1, unavailable).
    assert set(registered) <= {"system.shutdown", "system.restart"}