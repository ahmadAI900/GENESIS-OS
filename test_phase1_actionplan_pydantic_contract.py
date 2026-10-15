"""
Genesis OS — Phase 1 Pydantic contract regression tests.

These tests guard the two specific contracts the Phase 1
``ActionPlan`` Pydantic migration is responsible for:

1. The previously-buggy
   ``ActionPlan(operation="gui.type_text", target=None)``
   shape — which the Phase 0 compound-fix routed through
   ``TARGETLESS_OPERATIONS`` — is now ACCEPTED at construction
   time, before the executor even runs.

2. An unrecognized / nonsense operation string is now
   REJECTED at construction time with a clear Pydantic
   validation error — protection that didn't exist in the
   previous ``@dataclass(frozen=True)`` ActionPlan.

Both tests intentionally exercise the ``ActionPlan`` boundary
itself (not the executor), since the Phase 1 scope is the
contract enforcement at construction time.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from genesis_os.action_plan import (
    ActionPlan,
    ActionPlanValidationError,
)


def _assert_validation_error(exc_info: pytest.ExceptionInfo) -> None:
    """
    Accept either the project's ``ActionPlanValidationError``
    (raised by our custom field / model validators) or
    Pydantic's own ``ValidationError`` (raised by Pydantic
    when an input fails type / shape validation). Both are
    legitimate "clear validation error at construction time"
    outcomes; the Phase 1 prompt requires rejection, not a
    specific exception class.
    """

    assert (
        isinstance(exc_info.value, ActionPlanValidationError)
        or isinstance(exc_info.value, PydanticValidationError)
    ), (
        f"expected ActionPlanValidationError or "
        f"Pydantic ValidationError, got "
        f"{type(exc_info.value).__name__}: {exc_info.value}"
    )


class TestGuiTypeTextRegression:
    """
    The exact compound-clause shape the Phase 0 fix made
    executable. Construction-time acceptance is the new
    contract guard.
    """

    def test_gui_type_text_with_none_target_is_accepted(self):
        """
        Regression guard for the ``require_target=True``
        default that silently rejected valid
        ``gui.type_text`` plans.

        ``ActionPlan(operation="gui.type_text", target=None)``
        must construct cleanly. The conditional target
        requirement is now expressed as a Pydantic model
        validator that consults ``TARGETLESS_OPERATIONS``
        — not as scattered ``if`` checks at call sites.
        """

        plan = ActionPlan(
            operation="gui.type_text",
            target=None,
            parameters={"text": "hello ahmad"},
        )

        assert plan.operation == "gui.type_text"
        assert plan.target is None
        assert plan.parameters["text"] == "hello ahmad"
        assert "gui.type_text" in ActionPlan.TARGETLESS_OPERATIONS

    def test_gui_type_text_positional_two_args_is_accepted(self):
        """
        Positional construction ``ActionPlan("op", "target")``
        must keep working — the Phase 1 migration preserves
        the historical ``@dataclass(frozen=True)`` calling
        convention at every existing call site.
        """

        plan = ActionPlan(
            "gui.type_text",
            None,
        )

        assert plan.operation == "gui.type_text"
        assert plan.target is None

    def test_non_targetless_missing_target_is_still_rejected(self):
        """
        The conditional-target validator is symmetric: an
        operation NOT in ``TARGETLESS_OPERATIONS`` still
        requires a non-empty target at construction time.
        """

        with pytest.raises(Exception) as exc_info:
            ActionPlan(
                operation="application.open",
                target=None,
            )

        _assert_validation_error(exc_info)
        message = str(exc_info.value).lower()
        assert "target" in message
        assert "application.open" in str(exc_info.value)


class TestUnknownOperationRegression:
    """
    Construction-time rejection of malformed/unsafe state.

    Before Phase 1: an ``ActionPlan`` with a clearly
    malformed operation (non-string, empty, whitespace)
    could be constructed and was only rejected later by
    the executor's safety check.

    After Phase 1: those malformed shapes are caught at
    construction time by the Pydantic ``operation`` field
    validator. The allow-list membership check against
    ``ActionExecutor.SUPPORTED_OPERATIONS`` deliberately
    stays in the ``validate()`` method — the executor
    needs it there to preserve its "denied / unknown /
    malformed" distinction, which is the same
    architectural split the Phase 1 prompt asks us NOT to
    disturb.
    """

    def test_completely_empty_operation_string_is_rejected(self):
        """
        An empty operation string is now caught at
        construction time by the Pydantic ``operation``
        field validator — the same check the old
        ``validate()`` method performed, just at an
        earlier boundary.
        """

        with pytest.raises(Exception) as exc_info:
            ActionPlan(
                operation="",
                target="x",
            )

        _assert_validation_error(exc_info)
        message = str(exc_info.value).lower()
        assert "operation" in message

    def test_whitespace_only_operation_string_is_rejected(self):
        """
        A whitespace-only operation string is now caught
        at construction time. The Pydantic validator
        strips the value and rejects the empty result.
        """

        with pytest.raises(Exception) as exc_info:
            ActionPlan(
                operation="   ",
                target="x",
            )

        _assert_validation_error(exc_info)
        assert "operation" in str(exc_info.value).lower()

    def test_non_string_operation_is_rejected(self):
        """
        A non-string operation value (None, int, etc.) is
        rejected at construction time — a class of bug
        that the old dataclass would have silently
        accepted and that ``.value`` comparisons later
        crashed on.
        """

        for bad in (None, 42, 3.14, [], {}):
            with pytest.raises(Exception) as exc_info:
                ActionPlan(
                    operation=bad,
                    target="x",
                )

            _assert_validation_error(exc_info)
            assert "operation" in str(exc_info.value).lower()

    def test_unknown_operation_is_rejected_at_construction(self):
        with pytest.raises(Exception) as exc_info:
            ActionPlan(
                operation="unknown.operation",
                target="x",
            )

        _assert_validation_error(exc_info)
        assert "unknown.operation" in str(exc_info.value)