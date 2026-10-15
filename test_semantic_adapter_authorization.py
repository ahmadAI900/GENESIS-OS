"""Item 3B-2 -- the semantic surface has ONE authorization authority.

`SemanticCapabilityAdapter.invoke` used to check a CONTEXT-FREE
`assess_operation_risk` and then call `os_manager.delete_file` directly,
bypassing the executor's authorization gate entirely. A Tier 1 capability
could therefore reach the OS manager with no grant at all.

The class is dormant (constructed nowhere in the product), but the bypass
is real code, so it is closed here. The gate it now uses is the SAME
shared `_operation_requires_authorization` the executor uses, so there is
one authority rather than two.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from genesis_os.approval_store import ApprovalStore
from genesis_os.authorization_grant import issue_authorization_grant
from genesis_os.semantic_adapter import SemanticCapabilityAdapter


class _RecordingOSM:
    """Records manager calls so 'did it reach delete_file' is provable."""

    def __init__(self):
        self.calls = []

    def delete_file(self, path, **kwargs):
        self.calls.append(("delete_file", path))
        return {"success": True, "executed": True, "verified": True}

    def __getattr__(self, name):
        def call(*a, **k):
            self.calls.append((name, a))
            return {"success": True, "executed": True, "verified": True}
        return call


@pytest.fixture
def osm():
    return _RecordingOSM()


@pytest.fixture
def adapter(osm):
    return SemanticCapabilityAdapter(osm)


def _valid_grant(capability_id, arguments):
    token = ApprovalStore.issue_token(capability_id, dict(arguments))
    ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])
    return issue_authorization_grant(
        operation=capability_id, arguments=dict(arguments), token=token
    )


def test_file_delete_without_a_grant_never_reaches_the_manager(adapter, osm):
    """No grant -> refused, and delete_file is NEVER called."""
    result = adapter.invoke("file_delete", {"path": "C:/secret.txt"})

    assert result["success"] is False, result
    assert result.get("status") == "confirmation_required", result
    assert result.get("requires_confirmation") is True, result
    assert result["executed"] is False, result
    assert osm.calls == [], (
        f"an ungranted Tier 1 capability reached the OS manager: {osm.calls}"
    )


def test_file_delete_with_a_valid_grant_does_reach_the_manager(adapter, osm):
    """A real, human-approved grant still authorises exactly one call."""
    args = {"path": "C:/authorised.txt"}
    grant = _valid_grant("file.delete", args)

    result = adapter.invoke("file_delete", {**args, "authorization": grant})

    assert [c for c in osm.calls if c[0] == "delete_file"], (
        f"a valid grant did not reach the manager: {result}"
    )


def test_a_forged_grant_is_refused(adapter, osm):
    """`confirmed` is not an authority and a bogus grant is not either."""
    result = adapter.invoke(
        "file_delete", {"path": "C:/x.txt", "confirmed": True}
    )
    assert result.get("status") == "confirmation_required", result
    assert osm.calls == [], osm.calls

    forged = adapter.invoke(
        "file_delete",
        {"path": "C:/x.txt", "authorization": {"not": "a grant"}},
    )
    assert forged.get("status") == "confirmation_required", forged
    assert osm.calls == [], osm.calls


def test_a_grant_for_another_target_does_not_authorise(adapter, osm):
    """The grant is argument-bound: approving A must not authorise B."""
    grant = _valid_grant("file.delete", {"path": "C:/approved.txt"})
    result = adapter.invoke(
        "file_delete",
        {"path": "C:/somebody_elses.txt", "authorization": grant},
    )
    assert result.get("status") == "confirmation_required", result
    assert osm.calls == [], (
        f"a grant for one file authorised another: {osm.calls}"
    )


def test_a_benign_read_only_call_is_unaffected(adapter, osm):
    """A non-destructive function must still work with no grant."""
    result = adapter.invoke("file_read", {"path": "C:/notes.txt"})
    assert [c for c in osm.calls if c[0] == "read_file"], (
        f"the read path was gated: {result}"
    )