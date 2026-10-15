"""Item 3B-3a -- overwriting an existing file is Tier 1 at the gate.

Before this, `overwrite_destination_escalation` was registered only for
`file.move` / `file.rename` / `folder.move` / `folder.rename`, and it
read only destination-shaped keys. Two real gaps followed:

1. `file.rename` / `folder.rename` pass a BARE `new_name`, which was
   never among those keys, so the evaluator read no destination and
   always returned `None` -- the rename escalations were unreachable.
2. `file.copy`, `file.create` and `document.create_docx` had no
   evaluator at all, so overwriting an existing file through them was
   ungated on the live executor path (which hardcodes `confirmed=True`).

These tests drive the real authority -- `_operation_requires_authorization`
-- so they fail on the pre-fix module and pass after.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from genesis_os.action_executor import (
    ActionExecutor,
    _operation_requires_authorization,
)
from genesis_os.action_plan import ActionPlan
from genesis_os.os_manager import OSManager


def _gated(capability_id, arguments):
    return _operation_requires_authorization(
        capability_id, capability_id, dict(arguments)
    )


@pytest.fixture
def tree(workspace_root):
    """A source, an existing target (with content), and a free target.

    Deliberately built INSIDE the `workspace_root` fixture rather than
    tmp_path. The workspace boundary escalates any write OUTSIDE the root
    to Tier 1, so a tmp_path-based fixture made these Tier-2 cases fail
    whenever an earlier test had armed the boundary -- an order-dependent
    test, not a product fault.
    """
    existing = workspace_root / "existing.txt"
    existing.write_text("irreplaceable data", encoding="utf-8")
    free = workspace_root / "free.txt"
    src = workspace_root / "source.txt"
    src.write_text("source", encoding="utf-8")
    srcdir = workspace_root / "srcdir"
    srcdir.mkdir()
    return {
        "existing": existing, "free": free,
        "src": src, "srcdir": srcdir,
        "root": workspace_root,
    }


# ----------------------------------------------------------------------
# Tier decisions at the authority
# ----------------------------------------------------------------------
@pytest.mark.parametrize("capability_id,args_key,value_key", [
    ("file.copy", "source", "destination"),
    ("file.move", "source", "destination"),
])
def test_copy_and_move_onto_existing_are_tier1(tree, capability_id,
                                               args_key, value_key):
    args = {args_key: str(tree["src"]), value_key: str(tree["existing"])}
    assert _gated(capability_id, args) is True


def test_copy_onto_a_free_target_stays_tier2(tree):
    args = {"source": str(tree["src"]), "destination": str(tree["free"])}
    assert _gated("file.copy", args) is False


def test_file_create_overwrite_existing_is_tier1(tree):
    assert _gated(
        "file.create",
        {"path": str(tree["existing"]), "overwrite": True},
    ) is True


def test_file_create_without_overwrite_stays_tier2(tree):
    """Without overwrite=True the manager refuses, so nothing is destroyed."""
    assert _gated("file.create", {"path": str(tree["existing"])}) is False


def test_file_rename_onto_existing_is_tier1(tree):
    """The evaluator must resolve a BARE new_name beside the source.

    This is the case that was registered but dead: new_name was never a
    destination-shaped key.
    """
    assert _gated(
        "file.rename",
        {"source": str(tree["src"]), "new_name": "existing.txt"},
    ) is True


def test_file_rename_onto_free_stays_tier2(tree):
    # Only `destination` is passed. A bare `new_name` cannot appear in a
    # Tier-2 assertion here because `arguments_escape_workspace` resolves
    # argument values it does not recognise as paths against the process
    # CWD: a bare `new_name` becomes backend/brand_new.txt, which is
    # outside the workspace root and escalates the call for a reason
    # unrelated to overwriting. That is a pre-existing quirk of the
    # boundary check, not of the overwrite evaluator, and pinning it here
    # would only pin the quirk. The bare-`new_name` escalation IS pinned,
    # by test_file_rename_onto_existing_is_tier1.
    assert _gated(
        "file.rename",
        {
            "source": str(tree["src"]),
            "destination": str(tree["root"] / "brand_new.txt"),
        },
    ) is False


def test_folder_rename_onto_existing_is_tier1(tree):
    target_name = tree["existing"].name
    assert _gated(
        "folder.rename",
        {"source": str(tree["srcdir"]), "new_name": target_name},
    ) is True


def test_folder_move_onto_existing_is_tier1(tree):
    assert _gated(
        "folder.move",
        {"source": str(tree["srcdir"]),
         "destination": str(tree["existing"])},
    ) is True


def test_document_create_docx_onto_existing_is_tier1(tree):
    assert _gated(
        "document.create_docx", {"path": str(tree["existing"])}
    ) is True


def test_document_create_docx_onto_free_stays_tier2(tree):
    assert _gated(
        "document.create_docx", {"path": str(tree["free"])}
    ) is False


def test_a_benign_read_stays_tier2(tree):
    assert _gated("file.read", {"path": str(tree["existing"])}) is False


# ----------------------------------------------------------------------
# End-to-end through the executor: blocked, and ZERO dispatches
# ----------------------------------------------------------------------
class _CountingOSM:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*a, **k):
            self.calls.append(name)
            return {"success": True, "executed": True, "verified": True}
        return call

    def inspect_file(self, path, **k):
        self.calls.append("inspect_file")
        return {"exists": True}

    def inspect_folder(self, path, **k):
        self.calls.append("inspect_folder")
        return {"exists": True}


def test_overwriting_copy_is_blocked_with_zero_dispatches(tree):
    osm = _CountingOSM()
    executor = ActionExecutor(osm)
    plan = ActionPlan(
        operation="file.copy",
        target=str(tree["src"]),
        parameters={
            "source": str(tree["src"]),
            "destination": str(tree["existing"]),
        },
    )
    result = executor.execute(plan)
    assert result.status == "confirmation_required", (
        f"an overwriting copy was allowed: status={result.status!r}"
    )
    assert "copy_file" not in osm.calls, (
        f"the overwriting copy dispatched anyway: {osm.calls}"
    )


def test_a_free_destination_copy_is_not_gated(tree):
    osm = _CountingOSM()
    executor = ActionExecutor(osm)
    plan = ActionPlan(
        operation="file.copy",
        target=str(tree["src"]),
        parameters={
            "source": str(tree["src"]),
            "destination": str(tree["free"]),
        },
    )
    result = executor.execute(plan)
    assert result.status != "confirmation_required", (
        "a copy to a FREE target must not be escalated"
    )
    assert "copy_file" in osm.calls, (
        f"a copy to a free target did not dispatch: {osm.calls}"
    )
