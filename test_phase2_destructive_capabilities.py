"""
Genesis OS - Phase 2 destructive-capability regression tests.

Scope (per the user's session-B prompt):

    file.delete
    cleanup.empty_recycle_bin
    application.close  (only when the unsaved-changes
                        precondition is active)

For every capability in this scope the new tests pin two
properties:

    (a) Calling the tool WITHOUT prior confirmation does
        NOT reach ``ActionExecutor.execute`` at all - the
        adapter-level risk-tier pre-check returns a
        structured ``confirmation_required`` ActionResult
        and the executor is never asked to dispatch the
        plan.  This is proven by spying on
        ``ActionExecutor.execute`` and asserting it was
        never called for the unconfirmed case.

    (b) With confirmation granted (``confirmed=True``),
        the adapter DOES reach the real executor, and the
        executor reaches the real ``OSManager`` method
        and produces an honest verified / verification_reason
        result.  This is proven by giving the adapter a
        real executor wrapping a recording OSManager mock
        and asserting both ``executor.execute`` and the
        underlying ``os_manager.<method>`` were called.

The tests also pin the structural safety invariant: the
adapter never injects ``confirmed=True`` itself.  The plan
builder for every destructive capability must produce an
``ActionPlan`` whose ``parameters`` does NOT contain a
``confirmed`` key when the caller has not supplied one.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

# =========================================================
# Imports under test
# =========================================================

from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.action_result import ActionResult
from genesis_os.agent_framework_adapter import (
    ALWAYS_DESTRUCTIVE,
    CONDITIONALLY_DESTRUCTIVE,
    AgentFrameworkAdapter,
    _build_action_plan,
)
from genesis_os.capability_registry import CapabilityRegistry
from genesis_os.approval_store import ApprovalStore


# =========================================================
# MOCK OS MANAGER (destructive-capability surface)
# =========================================================


class _RecordingDestructiveOSM:
    """
    Mock OSManager that records every call ``ActionExecutor._dispatch``
    makes for the destructive capabilities in this scope.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def delete_file(self, path, **kwargs) -> dict:
        self.calls.append(
            {
                "method": "delete_file",
                "path": path,
                "kwargs": kwargs,
            }
        )
        return {
            "success": True,
            "operation": "file.delete",
            "path": path,
            "executed": True,
            "verified": True,
            "file_exists": False,
            "message": f"Deleted {path}.",
            "data": {"path": path},
            "metadata": {
                "verification_type": "file_gone",
                "verification_reason": "",
            },
        }

    def empty_recycle_bin(self) -> dict:
        self.calls.append({"method": "empty_recycle_bin"})
        return {
            "success": True,
            "operation": "cleanup.empty_recycle_bin",
            "executed": True,
            "verified": True,
            "item_count": 0,
            "message": "Recycle Bin emptied.",
            "metadata": {
                "verification_type": "bin_empty_after",
                "verification_reason": "",
            },
        }

    def close_application(self, application: str) -> dict:
        self.calls.append(
            {"method": "close_application", "application": application}
        )
        return {
            "success": True,
            "operation": "application.close",
            "application": application,
            "executed": True,
            "verified": True,
            "running": False,
            "message": f"{application} closed successfully.",
            "metadata": {
                "verification_type": "process_gone",
                "verification_reason": "",
            },
        }


# =========================================================
# FIXTURES
# =========================================================


_DESTRUCTIVE_CAPS = (
    "file.delete",
    "cleanup.empty_recycle_bin",
    "application.close",
)


@pytest.fixture
def destructive_osm() -> _RecordingDestructiveOSM:
    return _RecordingDestructiveOSM()


@pytest.fixture
def adapter(
    destructive_osm: _RecordingDestructiveOSM,
) -> AgentFrameworkAdapter:
    executor = ActionExecutor(destructive_osm)
    return AgentFrameworkAdapter(
        executor, capability_ids=_DESTRUCTIVE_CAPS
    )


def _approve_issued_token(token: str) -> None:
    ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])


def test_pending_token_cannot_be_consumed():
    store = ApprovalStore()
    record = store.request("file.delete", {"path": "A"})
    token = f"HUMAN-APPROVE:file.delete:{record['approval_id']}"

    with pytest.raises(ValueError, match="pending human approval"):
        store.consume_token(token, arguments={"path": "A"})

    assert store.status(record["approval_id"])["status"] == "pending"


def test_approved_token_cannot_be_replayed_for_another_target():
    store = ApprovalStore()
    record = store.request("file.delete", {"path": "A"})
    store.approve(record["approval_id"])
    token = f"HUMAN-APPROVE:file.delete:{record['approval_id']}"

    with pytest.raises(ValueError, match="arguments do not match"):
        store.consume_token(token, arguments={"path": "B"})

    assert store.status(record["approval_id"])["status"] == "approved"


def test_tool_call_path_rejects_cross_target_token_before_dispatch(
    adapter, destructive_osm
):
    from test_phase2_agent_framework_adapter_expansion import _invoke

    tool = next(
        tool
        for tool in adapter.build_tools()
        if tool.additional_properties.get("genesis_capability_id")
        == "file.delete"
    )
    token = ApprovalStore.issue_token(
        "file.delete", {"path": "C:/approved.txt"}
    )
    _approve_issued_token(token)

    rejected = _invoke(
        tool,
        {
            "path": "C:/different.txt",
            "approval_token": token,
        },
    )
    assert rejected["status"] == "confirmation_required"
    assert rejected["executed"] is False
    assert rejected["verified"] is False
    assert destructive_osm.calls == []

    accepted = _invoke(
        tool,
        {
            "path": "C:/approved.txt",
            "approval_token": token,
        },
    )
    assert accepted["status"] == "verified"
    assert accepted["verified"] is True
    assert len(destructive_osm.calls) == 1


# =========================================================
# (A) RISK-TIER CLASSIFICATION
# =========================================================


class TestRiskTierClassification:
    """The destructive-capability set is correctly partitioned."""

    def test_always_destructive_contains_file_delete(self):
        assert "file.delete" in ALWAYS_DESTRUCTIVE

    def test_always_destructive_contains_empty_recycle_bin(self):
        assert "cleanup.empty_recycle_bin" in ALWAYS_DESTRUCTIVE

    def test_conditionally_destructive_contains_application_close(self):
        assert "application.close" in CONDITIONALLY_DESTRUCTIVE

    def test_file_move_is_not_in_either_destructive_set(self):
        """
        ``file.move`` is the user's specific example of a
        capability that is NOT blanket-destructive - it
        should be in the high-tier-but-confirm-only-on-
        unresolved-target family, not in the always-
        destructive family.  This pins the boundary.
        """
        assert "file.move" not in ALWAYS_DESTRUCTIVE
        assert "file.move" not in CONDITIONALLY_DESTRUCTIVE

    def test_application_close_is_not_in_always_destructive(self):
        assert "application.close" not in ALWAYS_DESTRUCTIVE

    def test_every_destructive_capability_is_registered(self):
        """
        Every entry in the destructive sets must resolve in
        the capability registry; otherwise the executor's
        safety policy will reject the plan with
        ``safety_blocked`` and the test cannot exercise the
        end-to-end path.
        """
        for cap in (
            list(ALWAYS_DESTRUCTIVE) + list(CONDITIONALLY_DESTRUCTIVE)
        ):
            assert CapabilityRegistry.exists(cap), (
                f"destructive capability {cap!r} not in registry"
            )


# =========================================================
# (B) NO-CONFIRM BLOCKS THE EXECUTOR
# =========================================================


class TestDestructiveCapabilitiesRequireConfirmation:
    """
    Two-way test: calling each destructive capability
    WITHOUT ``confirmed=True`` MUST NOT reach the real
    ``ActionExecutor.execute``.  The adapter returns a
    structured ``confirmation_required`` ActionResult and
    the executor's spy shows zero calls.
    """

    def test_file_delete_without_confirm_does_not_reach_executor(
        self, adapter, destructive_osm, monkeypatch
    ):
        captured_executor_calls: List[Any] = []
        original_execute = adapter.executor.execute

        def spy_execute(plan):
            captured_executor_calls.append(plan)
            return original_execute(plan)

        monkeypatch.setattr(adapter.executor, "execute", spy_execute)

        result = adapter.execute_capability(
            "file.delete", {"path": "C:/some/file.txt"}
        )

        # The adapter's pre-check returned BEFORE
        # executor.execute was called.
        assert captured_executor_calls == [], (
            f"ActionExecutor.execute was called for "
            f"file.delete without confirmation: "
            f"{captured_executor_calls}"
        )

        # The OSManager never saw the delete call.
        assert destructive_osm.calls == [], (
            f"OSManager.delete_file was called for "
            f"file.delete without confirmation: "
            f"{destructive_osm.calls}"
        )

        # The result is clearly a confirmation request, not
        # a generic failure.
        assert result.status == "confirmation_required"
        assert result.executed is False
        assert result.verified is False
        assert result.success is False
        assert result.metadata.get("confirmation_required") is True
        assert "confirmation_message" in result.metadata
        assert result.metadata.get("adapter_risk_tier") == (
            "always_destructive"
        )
        assert "execute" not in result.metadata.get(
            "execution_stage", ""
        ).lower().replace("adapter_risk_tier_pre_check", "execute") or (
            result.metadata.get("execution_stage")
            == "adapter_risk_tier_pre_check"
        )

    def test_empty_recycle_bin_without_confirm_does_not_reach_executor(
        self, adapter, destructive_osm, monkeypatch
    ):
        captured_executor_calls: List[Any] = []

        def spy_execute(plan):
            captured_executor_calls.append(plan)
            return adapter.executor.execute(plan)

        monkeypatch.setattr(adapter.executor, "execute", spy_execute)

        result = adapter.execute_capability(
            "cleanup.empty_recycle_bin", {}
        )

        assert captured_executor_calls == []
        assert destructive_osm.calls == []
        assert result.status == "confirmation_required"
        assert result.metadata.get("adapter_risk_tier") == (
            "always_destructive"
        )
        assert result.metadata.get("confirmation_required") is True

    def test_application_close_without_confirm_does_not_reach_executor_when_unsaved(
        self, adapter, destructive_osm, monkeypatch
    ):
        """
        ``application.close`` is CONDITIONALLY destructive:
        the adapter only blocks when the unsaved-changes
        precondition is active.  We force the precondition
        to be active by monkeypatching the heuristic to
        return ``(True, 'forced test')`` and confirm the
        executor is never called.
        """

        def fake_precond(capability_id, arguments):
            return (True, "forced test - unsaved state detected")

        monkeypatch.setattr(
            adapter,
            "_check_unsaved_changes_precondition",
            fake_precond,
        )

        captured_executor_calls: List[Any] = []

        def spy_execute(plan):
            captured_executor_calls.append(plan)
            return adapter.executor.execute(plan)

        monkeypatch.setattr(adapter.executor, "execute", spy_execute)

        result = adapter.execute_capability(
            "application.close", {"application": "notepad"}
        )

        assert captured_executor_calls == []
        assert destructive_osm.calls == []
        assert result.status == "confirmation_required"
        assert result.metadata.get("adapter_risk_tier") == (
            "conditionally_destructive"
        )
        assert result.metadata.get("confirmation_required") is True
        # The precondition reason must be surfaced to the
        # model so it can present the proposal in plain
        # language.
        assert "forced test" in (
            result.metadata.get("confirmation_message") or ""
        )


# =========================================================
# (C) WITH CONFIRMATION, REACHES THE REAL EXECUTOR
# =========================================================


class TestDestructiveCapabilitiesExecuteAfterConfirmation:
    """
    Two-way test: when ``confirmed=True`` is supplied (or
    the unsaved-changes precondition is inactive for
    ``application.close``), the adapter reaches the real
    executor and the real ``OSManager`` method, and
    ``verified`` is bound to the honest post-state signal
    from the executor's normalization layer.
    """

    def test_file_delete_token_is_bound_to_original_target(
        self, adapter, destructive_osm
    ):
        token = ApprovalStore.issue_token(
            "file.delete", {"path": "C:/target-a.txt"}
        )
        _approve_issued_token(token)

        replay = adapter.execute_capability(
            "file.delete",
            {
                "path": "C:/target-b.txt",
                "confirmed": True,
                "approval_token": token,
            },
        )

        assert replay.status == "confirmation_required"
        assert destructive_osm.calls == []

        approved = adapter.execute_capability(
            "file.delete",
            {
                "path": "C:/target-a.txt",
                "confirmed": True,
                "approval_token": token,
            },
        )
        assert approved.success is True
        assert destructive_osm.calls[0]["path"] == "C:/target-a.txt"

    def test_file_delete_with_confirm_reaches_executor(
        self, adapter, destructive_osm
    ):
        token = ApprovalStore.issue_token(
            "file.delete", {"path": "C:/some/file.txt"}
        )
        _approve_issued_token(token)
        result = adapter.execute_capability(
            "file.delete",
            {
                "path": "C:/some/file.txt",
                "confirmed": True,
                "approval_token": token,
            },
        )

        # The real OSManager method was called.
        assert any(
            c.get("method") == "delete_file"
            for c in destructive_osm.calls
        ), destructive_osm.calls

        # The real executor's normalization layer stamped
        # the result envelope.
        assert (
            result.metadata.get("executor_version") == "3.6.0"
        ), result.metadata

        # ``verified`` is a genuine bool from the executor.
        assert isinstance(result.verified, bool)
        assert result.verified is True
        assert result.status == "verified"
        assert result.success is True

    def test_empty_recycle_bin_with_confirm_reaches_executor(
        self, adapter, destructive_osm
    ):
        token = ApprovalStore.issue_token("cleanup.empty_recycle_bin")
        _approve_issued_token(token)
        result = adapter.execute_capability(
            "cleanup.empty_recycle_bin",
            {"confirmed": True, "approval_token": token},
        )

        assert any(
            c.get("method") == "empty_recycle_bin"
            for c in destructive_osm.calls
        ), destructive_osm.calls
        assert (
            result.metadata.get("executor_version") == "3.6.0"
        ), result.metadata
        assert result.verified is True
        assert result.status == "verified"

    def test_application_close_with_confirm_reaches_executor(
        self, adapter, destructive_osm
    ):
        """
        When ``confirmed=True`` is explicitly supplied the
        adapter short-circuits the precondition check
        entirely - the model has already declared the
        intent, and the executor is allowed to run.
        """
        result = adapter.execute_capability(
            "application.close",
            {"application": "notepad", "confirmed": True},
        )

        assert any(
            c.get("method") == "close_application"
            for c in destructive_osm.calls
        ), destructive_osm.calls
        assert (
            result.metadata.get("executor_version") == "3.6.0"
        ), result.metadata
        assert result.verified is True

    def test_application_close_with_inactive_precondition_reaches_executor(
        self, adapter, destructive_osm, monkeypatch
    ):
        """
        When the unsaved-changes precondition is INACTIVE
        (no top-level window with an unsaved-changes
        title), the adapter lets the call through to the
        executor without requiring ``confirmed=True``.
        This is the user's specific requirement: only risky
        closes are gated, not every close.
        """

        def fake_precond(capability_id, arguments):
            return (False, "no unsaved-changes window title detected")

        monkeypatch.setattr(
            adapter,
            "_check_unsaved_changes_precondition",
            fake_precond,
        )

        result = adapter.execute_capability(
            "application.close", {"application": "calculator"}
        )

        assert any(
            c.get("method") == "close_application"
            for c in destructive_osm.calls
        ), destructive_osm.calls
        assert result.status == "verified"
        assert result.verified is True
        # The result did NOT go through the pre-check.
        assert (
            result.metadata.get("execution_stage")
            != "adapter_risk_tier_pre_check"
        )


# =========================================================
# (D) STRUCTURAL: ADAPTER NEVER INJECTS confirmed
# =========================================================


class TestAdapterNeverInjectsConfirmedToken:
    """
    The plan builder for every destructive capability must
    produce an ActionPlan whose ``parameters`` does NOT
    contain a ``confirmed`` key when the caller has not
    supplied one.  This is the structural safety invariant
    for the new capabilities (the same one the PoC and
    expansion test files already pin for the other caps).
    """

    def test_file_delete_plan_has_no_confirmed_when_caller_omits_it(self):
        plan = _build_action_plan(
            "file.delete", {"path": "C:/x.txt"}
        )
        assert "confirmed" not in plan.parameters, plan.parameters

    def test_application_close_plan_has_no_confirmed_when_caller_omits_it(self):
        plan = _build_action_plan(
            "application.close", {"application": "notepad"}
        )
        assert "confirmed" not in plan.parameters, plan.parameters

    def test_empty_recycle_bin_plan_has_no_confirmed_when_caller_omits_it(self):
        plan = _build_action_plan("cleanup.empty_recycle_bin", {})
        assert "confirmed" not in plan.parameters, plan.parameters

    def test_confirmed_token_passes_through_when_caller_supplies_it(self):
        """
        RETARGETED 2026-10-15 (Item 3B-1).

        This test previously asserted that a caller-supplied
        ``confirmed=True`` was forwarded into ``plan.parameters``. That
        was the defect: ``arguments`` is model-controlled tool-call JSON,
        so ``confirmed`` was a second, model-reachable authority channel.
        A model could set ``confirmed: true`` and be believed.

        Approval authority now comes ONLY from a validated
        ``approval_token`` and the AuthorizationGrant it mints, so a
        caller-supplied ``confirmed`` must NOT reach the plan.
        """
        plan = _build_action_plan(
            "file.delete",
            {"path": "C:/x.txt", "confirmed": True},
        )
        assert "confirmed" not in plan.parameters, (
            "a caller-supplied confirmed leaked into plan.parameters; "
            f"parameters={plan.parameters}"
        )

    def test_browser_click_plan_has_no_confirmed_when_caller_omits_it(self):
        """
        ``browser.click`` is non-destructive and is NOT in
        any destructive set; the safety invariant still
        holds (the adapter never injects ``confirmed``) but
        the call must be allowed through without
        confirmation.
        """
        plan = _build_action_plan(
            "browser.click", {"selector": "h1", "session_id": "default"}
        )
        assert "confirmed" not in plan.parameters, plan.parameters


# =========================================================
# (E) NON-DESTRUCTIVE: browser.click
# =========================================================


class TestBrowserClick:
    """
    ``browser.click`` is non-destructive (the underlying
    provider does not mutate user-saveable state) and is
    NOT in either destructive set.  The adapter forwards
    the call to the executor on every invocation; the
    executor's honest-fallback verification returns
    ``verified=False`` with a real verification_reason
    sourced from ``verification_helpers.verify_browser_click``.
    """

    def test_browser_click_is_not_in_any_destructive_set(self):
        assert "browser.click" not in ALWAYS_DESTRUCTIVE
        assert "browser.click" not in CONDITIONALLY_DESTRUCTIVE

    def test_browser_click_reaches_executor_without_confirmation(
        self, destructive_osm
    ):
        """
        Construct a dedicated adapter with browser.click in
        its capability set and a mock OSManager that mirrors
        the production ``os_manager.browser_click`` surface
        (which already wraps the result in
        ``verify_browser_click`` - see os_manager.py:311-317).
        """
        import asyncio

        from genesis_os.agent_framework_adapter import (
            AgentFrameworkAdapter,
        )
        from test_phase2_agent_framework_adapter_expansion import (
            _RecordingOSManagerGuiPaste as _GuiPasteMock,
            _invoke,
        )

        class _BrowserClickOSM(_GuiPasteMock):
            def browser_click(self, selector, session_id="default"):
                self.calls.append(
                    {
                        "method": "browser_click",
                        "selector": selector,
                        "session_id": session_id,
                    }
                )
                # Production ``os_manager.browser_click``
                # (``os_manager.py:311-317``) writes the
                # helper's result to the top level of the
                # return dict, not inside ``metadata``.
                # Mirror that shape so the executor's
                # ``_extract_verification_evidence`` reads
                # the fields correctly.
                return {
                    "success": True,
                    "operation": "browser.click",
                    "executed": True,
                    "verified": False,
                    "verification_reason": (
                        "no element_found signal in provider "
                        "result; honest fallback"
                    ),
                    "verification_type": "click_dispatched",
                    "message": "click dispatched",
                }

        osm = _BrowserClickOSM()
        executor = ActionExecutor(osm)
        adapter = AgentFrameworkAdapter(
            executor, capability_ids=("browser.click",)
        )
        tools = adapter.build_tools()
        tool = next(
            t for t in tools
            if t.additional_properties.get("genesis_capability_id")
            == "browser.click"
        )
        parsed = _invoke(
            tool,
            {"selector": "button#submit", "session_id": "default"},
        )
        assert (
            parsed.get("metadata", {}).get("executor_version")
            == "3.6.0"
        ), parsed
        assert any(
            c.get("method") == "browser_click"
            for c in osm.calls
        ), osm.calls
        # Honest-fallback: verified=False with a real
        # verification_type sourced from
        # ``verify_browser_click`` and surfaced via the
        # executor's normalization layer (the ``verification``
        # field, not the ``metadata`` field).  Not a
        # fabricated True.
        #
        # NOTE: the executor's ``_extract_verification_evidence``
        # does not currently pick up ``verification_reason``
        # (it is set on the raw result by the production
        # ``os_manager.browser_click`` wrapper but not
        # extracted into the normalized ``verification``
        # field).  That is a real production gap and is
        # flagged in the Session B report as a known
        # follow-up; the test pins the *currently delivered*
        # contract (``verified`` + ``verification_type``) so
        # future changes to the extraction logic are caught
        # by the assertion.
        assert parsed.get("verified") is False
        verification = parsed.get("verification") or {}
        assert verification.get("verified") is False, verification
        assert (
            verification.get("verification_type")
            == "click_dispatched"
        ), verification


# ----------------------------------------------------------------------
# A consumed approval must not leak across requests (H-06).
#
# `_consume_approval_token` used to stash the consumed record on a
# MODULE GLOBAL (`_LAST_CONSUMED_APPROVAL`), which the plan builder read
# later. Nothing tied that record to the request that produced it, so a
# later request presenting no token of its own could reach it. The record
# is now threaded explicitly from the consumption to the plan.
# ----------------------------------------------------------------------
def test_the_consumed_approval_global_no_longer_exists():
    """Structural: the shared module global is gone."""
    from genesis_os import agent_framework_adapter as adapter_mod

    assert not hasattr(adapter_mod, "_LAST_CONSUMED_APPROVAL"), (
        "the process-global consumed-approval slot is back; it lets one "
        "request's approval authorise another"
    )


def test_request_b_without_a_token_is_refused_after_request_a_consumed(
    adapter, destructive_osm
):
    """A consumes a valid token; B presents NO token and must be refused.

    Before the fix, A's consumed record was still on the module when B's
    decision was built, so B could reach A's authority.
    """
    token = ApprovalStore.issue_token(
        "file.delete", {"path": "C:/approved_by_a.txt"}
    )
    _approve_issued_token(token)

    # Request A: a real, human-approved token for its own target.
    result_a = adapter.execute_capability(
        "file.delete",
        {"path": "C:/approved_by_a.txt", "approval_token": token},
    )
    assert result_a.executed is True, result_a

    # Request B: same adapter, DIFFERENT target, and NO token at all.
    result_b = adapter.execute_capability(
        "file.delete",
        {"path": "C:/request_b_target.txt"},
    )
    assert result_b.status == "confirmation_required", (
        "request B presented no approval token yet was authorised: "
        f"{result_b}"
)
    assert result_b.executed is False, result_b
    assert len(destructive_osm.calls) == 1, (
        "only request A may dispatch; B must be blocked before dispatch"
    )


def test_a_request_presenting_its_own_token_is_still_authorised(
    adapter, destructive_osm
):
    """The legitimate path keeps working: own token -> executed once."""
    token = ApprovalStore.issue_token(
        "file.delete", {"path": "C:/own_token.txt"}
    )
    _approve_issued_token(token)

    result = adapter.execute_capability(
        "file.delete",
        {"path": "C:/own_token.txt", "approval_token": token},
    )
    assert result.executed is True, result
    assert len(destructive_osm.calls) == 1


def test_two_authorised_requests_each_use_their_own_token(
    adapter, destructive_osm
):
    """Two approvals, two dispatches, each bound to its own arguments."""
    token_a = ApprovalStore.issue_token(
        "file.delete", {"path": "C:/a.txt"}
    )
    token_b = ApprovalStore.issue_token(
        "file.delete", {"path": "C:/b.txt"}
    )
    _approve_issued_token(token_a)
    _approve_issued_token(token_b)

    first = adapter.execute_capability(
        "file.delete", {"path": "C:/a.txt", "approval_token": token_a}
    )
    second = adapter.execute_capability(
        "file.delete", {"path": "C:/b.txt", "approval_token": token_b}
    )
    assert first.executed is True, first
    assert second.executed is True, second
    assert len(destructive_osm.calls) == 2


# ----------------------------------------------------------------------
# A caller-supplied `confirmed` is NOT approval (Item 3B-1).
#
# `arguments` is model-controlled tool-call JSON. Before this fix a model
# could set `confirmed: true` and unlock a destructive operation with no
# human involved: `_risk_tier_pre_check` returned early (allow) on
# `arguments.get("confirmed")`, and `_runtime_tokens` copied the same
# value into `plan.parameters`.
# ----------------------------------------------------------------------
def test_a_model_tool_call_with_confirmed_only_is_refused(
    adapter, destructive_osm
):
    """confirmed=True and no token must NOT authorise a destructive cap."""
    from unittest.mock import patch

    from genesis_os.agent_framework_adapter import AgentFrameworkAdapter

    # Activate the precondition so the conditionally destructive branch
    # is the one under test.
    with patch.object(
        AgentFrameworkAdapter,
        "_check_unsaved_changes_precondition",
        return_value=(True, "document has unsaved changes"),
    ):
        result = adapter.execute_capability(
            "folder.rename",
            {
                "source": "C:/docs",
                "new_name": "renamed",
                "confirmed": True,
            },
        )

    assert result.status == "confirmation_required", (
        "a caller-supplied confirmed=True executed a destructive "
        f"capability with no human approval: {result}"
    )
    assert result.executed is False, result
    assert destructive_osm.calls == [], (
        f"the unapproved rename dispatched: {destructive_osm.calls}"
    )


def test_a_real_approval_token_still_executes_exactly_once(
    adapter, destructive_osm
):
    """The authorised path is untouched: own token -> one dispatch."""
    token = ApprovalStore.issue_token(
        "file.delete", {"path": "C:/token_authorised.txt"}
    )
    _approve_issued_token(token)

    result = adapter.execute_capability(
        "file.delete",
        {"path": "C:/token_authorised.txt", "approval_token": token},
    )
    assert result.executed is True, result
    assert len(destructive_osm.calls) == 1, (
        f"expected exactly one dispatch, got {destructive_osm.calls}"
    )


def test_confirmed_is_never_copied_into_plan_parameters():
    """Structural: _build_action_plan ignores a supplied confirmed."""
    plan = _build_action_plan(
        "file.delete", {"path": "C:/x.txt", "confirmed": True}
    )
    assert "confirmed" not in plan.parameters, plan.parameters
