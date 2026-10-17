"""Directive 10B (S11): the false safety claim must not come back.

Three comments claimed that a false negative from the unsaved-changes
detector is "caught by the executor's safety policy further down":

    genesis_os/blast_radius.py         (~line 658)
    genesis_os/agent_framework_adapter.py (~line 4874)
    test_blast_radius.py               (~line 347)

That was FALSE. `ExecutionSafety.check()` is a deny-list plus a
capability lookup -- it evaluates an operation NAME. It never inspects
windows, documents, or unsaved state, so there is no downstream safety
net and a false negative there is a false negative full stop.

The claim mattered because it was load-bearing. It was the stated
justification for letting a missing or broken detector pass silently.
If a future reader had believed it, they would have had no reason to
question the behaviour 7B changed.

These tests pin the corrected picture. COMMENT-ONLY in the product: no
behaviour changed in Item 10B.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

BACKEND = pathlib.Path(__file__).resolve().parent

# The false claim, as it was worded in each of the three places.
FALSE_CLAIM_FRAGMENTS = (
    "caught by the executor's safety policy",
)

UNSAVED_WORDS = ("unsaved", "draft", "dirty", "modified_window")


def _sources():
    for rel in (
        "genesis_os/blast_radius.py",
        "genesis_os/agent_framework_adapter.py",
        "test_blast_radius.py",
    ):
        path = BACKEND / rel
        assert path.is_file(), rel
        yield rel, path.read_text(encoding="utf-8-sig")


# =====================================================================
# The corrected comments
# =====================================================================

@pytest.mark.parametrize(
    "rel", ["genesis_os/blast_radius.py", "genesis_os/agent_framework_adapter.py"]
)
def test_the_false_claim_is_gone(rel):
    for name, text in _sources():
        if name != rel:
            continue
        for fragment in FALSE_CLAIM_FRAGMENTS:
            assert fragment not in text, (
                f"{rel} still claims {fragment!r}. That claim is false: "
                f"ExecutionSafety.check() never inspects unsaved state."
            )


def test_the_false_claim_is_gone_from_the_test_docstring():
    for name, text in _sources():
        if name != "test_blast_radius.py":
            continue
        for fragment in FALSE_CLAIM_FRAGMENTS:
            assert fragment not in text, (
                f"test_blast_radius.py still claims {fragment!r}"
            )


def test_the_correction_is_recorded_where_it_was_claimed():
    """A deletion leaves no trace. The correction must be discoverable
    by the next reader who wonders why the behaviour is what it is."""
    for name, text in _sources():
        assert "10B" in text or "S11" in text, (
            f"{name} should record the Item 10B correction so a future "
            f"reader can see the claim was checked, not overlooked"
        )


# =====================================================================
# The corrected claim is itself true
# =====================================================================

def test_execution_safety_really_has_no_unsaved_work_check():
    """Verified before correcting the comments, and pinned so it cannot
    quietly acquire one while still being described as a deny-list."""
    source = BACKEND / "genesis_os" / "execution_safety.py"
    text = source.read_text(encoding="utf-8-sig").lower()

    for word in UNSAVED_WORDS:
        assert word not in text, (
            f"execution_safety.py now mentions {word!r}; if a real "
            f"unsaved-work check was added there, the Item 10B comments "
            f"should be revisited rather than left claiming otherwise"
        )


def test_execution_safety_is_a_denylist_over_operation_names():
    """The shape the corrected comments describe."""
    tree = ast.parse(
        (BACKEND / "genesis_os" / "execution_safety.py").read_text(
            encoding="utf-8-sig"
        )
    )
    check = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "check"
        ):
            check = node
            break
    assert check is not None, "ExecutionSafety.check disappeared"
    # It takes an operation NAME, not a filesystem/UI state. It is a
    # classmethod, so `cls` may lead.
    args = [a.arg for a in check.args.args]
    assert "operation" in args, args


# =====================================================================
# The behaviour 7B established is unchanged by this item
# =====================================================================

def test_the_missing_versus_raising_distinction_still_holds():
    """10B corrected a comment; it must not have moved any behaviour."""
    from genesis_os import blast_radius as BR
    from genesis_os.blast_radius import (
        BlastRadius,
        resolve_blast_radius,
    )

    reversible = BlastRadius.REVERSIBLE_LOCAL
    irreversible = BlastRadius.IRREVERSIBLE_OR_OUTWARD

    # Missing detector -> quiet.
    saved = BR._unsaved_changes_detectors.pop("application.close", None)
    try:
        assert resolve_blast_radius(
            "application.close", {}, static_default=reversible
        ) is reversible
    finally:
        if saved is not None:
            BR._unsaved_changes_detectors["application.close"] = saved

    # Registered detector that raises -> escalates (7B).
    def boom(args):
        raise RuntimeError("boom")

    BR.register_unsaved_changes_detector("application.close", boom)
    assert resolve_blast_radius(
        "application.close", {}, static_default=reversible
    ) is irreversible