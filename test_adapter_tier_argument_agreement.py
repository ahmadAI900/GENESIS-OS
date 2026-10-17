"""Directive 9B: the adapter must resolve the tier with REAL arguments.

`agent_framework_adapter.requires_approval_token` resolved the blast
radius with an EMPTY argument dict:

    resolve_blast_radius(capability_id, {})

while the executor resolves with the real ones:

    action_executor._operation_requires_authorization(
        plan.operation, capability_id, plan.parameters, ...
    )

Whenever escalation is argument-dependent the two therefore disagreed,
and they disagree in the worst direction: the adapter under-estimated
the tier, forwarded the call, and the executor refused it -- with a
refusal that carries no route to a grant. A legitimate call was blocked
forever, which is the same permanent-unreachability class as Item 9A.

Reproduced before the fix:

    resolve_blast_radius('file.move', {})   -> reversible_local
    resolve_blast_radius('file.move', real) -> irreversible_or_outward
    adapter requires_approval_token(...)    -> False
    executor _operation_requires_auth(...)  -> True

These tests pin the two resolvers together.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")


def _inside(root) -> str:
    return str(root / "a.txt")


def _outside() -> str:
    return "C:/Users/Public/definitely-outside-the-workspace.txt"


# =====================================================================
# The disagreement
# =====================================================================

def test_adapter_and_executor_agree_on_an_out_of_workspace_move(
    workspace_root,
):
    """The reproduction. Fails before Item 9B."""
    from genesis_os.action_executor import (
        _operation_requires_authorization as executor_requires,
    )
    from genesis_os.agent_framework_adapter import (
        requires_approval_token as adapter_requires,
    )

    arguments = {
        "source": _inside(workspace_root),
        "destination": _outside(),
    }

    adapter = adapter_requires("file.move", arguments)
    executor = executor_requires("file.move", None, arguments)

    assert adapter == executor, (
        "the adapter and the executor disagree on the same call: "
        f"adapter={adapter} executor={executor}. The adapter would "
        f"forward a call the executor always refuses."
    )
    assert adapter is True, (
        "a move to a destination outside the workspace is escalated to "
        "Tier 1 by the workspace boundary and must require approval"
    )


@pytest.mark.parametrize(
    "operation,arguments_factory",
    [
        ("file.move", lambda r: {
            "source": str(r / "a.txt"),
            "destination": _outside(),
        }),
        ("file.copy", lambda r: {
            "source": str(r / "a.txt"),
            "destination": _outside(),
        }),
        ("document.read", lambda r: {
            "path": _outside(),
        }),
    ],
)
def test_no_operation_where_the_resolvers_disagree(
    workspace_root, operation, arguments_factory
):
    """A broad sweep: for every shape tried, the two must agree."""
    from genesis_os.action_executor import (
        _operation_requires_authorization as executor_requires,
    )
    from genesis_os.agent_framework_adapter import (
        requires_approval_token as adapter_requires,
    )

    arguments = arguments_factory(workspace_root)

    assert (
        adapter_requires(operation, arguments)
        == executor_requires(operation, None, arguments)
    ), f"{operation} disagrees between the two resolvers"


def test_an_in_workspace_move_is_not_escalated_by_the_boundary(
    workspace_root,
):
    """The fix must not over-correct into demanding approval for
    everything. A move to a free name inside the workspace stays Tier 2.
    """
    from genesis_os.agent_framework_adapter import (
        requires_approval_token as adapter_requires,
    )

    arguments = {
        "source": str(workspace_root / "a.txt"),
        "destination": str(workspace_root / "b.txt"),
    }

    assert adapter_requires("file.move", arguments) is False


# =====================================================================
# Backwards compatibility
# =====================================================================

def test_omitting_arguments_keeps_the_previous_behaviour():
    """Existing callers that pass only a capability_id must be
    unaffected -- the parameter is optional."""
    from genesis_os.agent_framework_adapter import (
        requires_approval_token as adapter_requires,
    )

    # Tier 1 by declaration: unchanged.
    assert adapter_requires("file.delete") is True
    # Tier 2 with no arguments: unchanged.
    assert adapter_requires("network.list_wifi") is False


def test_the_pre_check_gates_on_argument_dependent_escalation(
    workspace_root,
):
    """End to end through the adapter's own pre-check: an
    argument-escalated call must produce confirmation_required rather
    than being forwarded."""
    from genesis_os.agent_framework_adapter import (
        AgentFrameworkAdapter,
    )

    adapter = AgentFrameworkAdapter.__new__(AgentFrameworkAdapter)

    result = adapter._risk_tier_pre_check(
        "file.move",
        {
            "source": str(workspace_root / "a.txt"),
            "destination": _outside(),
        },
    )

    assert result is not None, (
        "the adapter forwarded an argument-escalated call that the "
        "executor will always refuse"
    )
    assert result.status == "confirmation_required", result.to_dict()
    assert result.executed is False, result.to_dict()


def test_the_pre_check_still_forwards_a_tier_2_call(workspace_root):
    """The mirror case, so the fix is not simply 'gate everything'."""
    from genesis_os.agent_framework_adapter import (
        AgentFrameworkAdapter,
    )

    adapter = AgentFrameworkAdapter.__new__(AgentFrameworkAdapter)

    assert adapter._risk_tier_pre_check(
        "network.list_wifi", {}
    ) is None


# =====================================================================
# Option (b): preserve what the old /tmp spreadsheet cases covered
# =====================================================================
#
# Before Item 9B, the adapter resolved the tier with `{}`, so a
# spreadsheet capability whose arguments named a path OUTSIDE the
# workspace was under-resolved and forwarded ungated. Nine cases in
# test_phase2_agent_framework_adapter_expansion.py depended on that:
# they used hardcoded /tmp/data.csv and asserted the call reached the
# real OSManager. They have been retargeted into the workspace, per
# that file's own _retarget_into_workspace convention.
#
# That would have silently dropped the only coverage of the
# out-of-workspace case, so it is stated explicitly here: such a call
# is now REFUSED, and that is the intended behaviour.


def test_an_out_of_workspace_spreadsheet_read_is_refused(workspace_root):
    """Fails before Item 9B: the adapter forwarded this ungated."""
    from genesis_os.agent_framework_adapter import (
        AgentFrameworkAdapter,
    )

    adapter = AgentFrameworkAdapter.__new__(AgentFrameworkAdapter)

    result = adapter._risk_tier_pre_check(
        "spreadsheet.read",
        {"path": _outside(), "sheet_name": "Sheet1"},
    )

    assert result is not None, (
        "an out-of-workspace spreadsheet read was forwarded ungated; "
        "it must be gated like any other boundary escape"
    )
    assert result.status == "confirmation_required", result.to_dict()
    assert result.executed is False, result.to_dict()


def test_the_same_spreadsheet_read_inside_the_workspace_is_forwarded(
    workspace_root,
):
    """The boundary, not a blanket spreadsheet ban, is what gates it."""
    from genesis_os.agent_framework_adapter import (
        AgentFrameworkAdapter,
    )

    adapter = AgentFrameworkAdapter.__new__(AgentFrameworkAdapter)

    assert adapter._risk_tier_pre_check(
        "spreadsheet.read",
        {
            "path": str(workspace_root / "data.csv"),
            "sheet_name": "Sheet1",
        },
    ) is None


@pytest.mark.parametrize(
    "operation",
    ["spreadsheet.read", "spreadsheet.calculate", "spreadsheet.aggregate"],
)
def test_out_of_workspace_spreadsheet_ops_all_refuse(
    workspace_root, operation
):
    """Not a one-capability quirk."""
    from genesis_os.agent_framework_adapter import (
        AgentFrameworkAdapter,
    )

    adapter = AgentFrameworkAdapter.__new__(AgentFrameworkAdapter)

    result = adapter._risk_tier_pre_check(
        operation, {"path": _outside()}
    )

    assert result is not None, operation
    assert result.status == "confirmation_required", operation