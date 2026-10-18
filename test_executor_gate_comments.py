"""Item 14G (S10): the comments about the live gate must be true.

A comment block immediately above the executor's Tier 1 gate said:

    "BUILT, PROVEN, BUT NOT ENABLED" ...
    "UNTIL THIS GATE IS ENABLED, `confirmed: true` REMAINS THE LIVE
     EXECUTOR GATE ... Do not read this branch as protection."

The gate it described is live. It sits directly below a header reading
"BLAST-RADIUS AUTHORIZATION GATE (ENABLED)" and reads blast_radius
only -- never risk_level.

So a reader auditing the Tier 1 path was told the grant gate is inert
and that `confirmed: true` is what actually gates. The code was right
and the description was its opposite, which is the worst combination
there is: the file looked like it had been reviewed.

This item changed comments only. The tests therefore do two jobs:

  1. Assert the stale claims are gone and the accurate ones are
     present, scanning the real comments via tokenize.
  2. Assert the behaviour those comments now describe is actually
     true, so the corrected text cannot itself go stale.

A test that only greps for strings would pass against a file whose
code said the opposite. That is the failure this item is about.
"""
from __future__ import annotations

import io
import tokenize
from pathlib import Path

import pytest

from genesis_os.action_executor import _operation_requires_authorization


SOURCE = Path("genesis_os") / "action_executor.py"


def _comments() -> list[str]:
    """Every comment in the file, via tokenize (not a line regex)."""
    out = []
    with open(SOURCE, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type == tokenize.COMMENT:
                out.append(tok.string)
    return out


def _comment_text() -> str:
    return "\n".join(_comments())


# --------------------------------------------------------------------------
# 1. The stale claims are gone
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "phrase",
    [
        "BUILT, PROVEN, BUT NOT ENABLED",
        "REMAINS THE LIVE EXECUTOR GATE",
        "UNTIL THIS GATE IS ENABLED",
    ],
)
def test_the_stale_gate_claims_are_gone(phrase):
    assert phrase not in _comment_text(), (
        f"action_executor.py still claims {phrase!r} about a gate that "
        "is live"
    )


def test_no_comment_still_asserts_confirmed_true_is_a_gate():
    text = _comment_text()

    bad = [
        line for line in text.splitlines()
        if "confirmed" in line.lower()
        and ("live executor gate" in line.lower() or "remains the live" in line.lower())
    ]
    assert not bad, f"stale `confirmed` gate claims remain: {bad}"


def test_the_corrected_history_is_recorded():
    text = _comment_text()

    assert "BLAST-RADIUS GATE — HISTORY" in text, (
        "the block should now read as history, not as the live status"
    )
    assert "this gate IS enabled" in text.lower() or "IS enabled" in text


def test_the_comment_states_the_real_rule():
    text = _comment_text()

    assert "blast_radius ONLY" in text
    assert "never risk_level" in text
    assert "must not be" in text


# --------------------------------------------------------------------------
# 2. The behaviour those comments describe is true
# --------------------------------------------------------------------------

def test_the_gate_is_actually_live():
    """The comment says it is enabled. Prove it is."""
    assert _operation_requires_authorization(
        "file.delete", "file.delete", {"path": "C:/x"}
    ) is True, (
        "the corrected comment claims the blast-radius gate is live, "
        "but a Tier 1 operation is not being gated"
    )


def test_a_tier_2_capability_is_not_gated():
    assert _operation_requires_authorization(
        "application.list", "application_manager.list", {}
    ) is False


def test_the_bare_browser_verb_is_not_gated_when_the_capability_id_is_present():
    """The exact gap that once forced the gate back to inert."""
    assert _operation_requires_authorization(
        "click", "browser_manager.click", {}
    ) is False, (
        "the bare-verb gap is back: a legitimate Tier 2 browser click "
        "would be gated again"
    )


def test_a_missing_capability_id_cannot_make_a_plan_less_gated():
    """Fail-safe by construction: absent id can only gate more."""
    with_id = _operation_requires_authorization(
        "file.delete", "file.delete", {"path": "C:/x"}
    )
    without_id = _operation_requires_authorization(
        "file.delete", None, {"path": "C:/x"}
    )

    assert with_id is True
    assert without_id is True
    assert without_id is not False


def test_confirmed_true_alone_does_not_authorise():
    """The corrected comment says so; check it is not lying."""
    assert _operation_requires_authorization(
        "file.delete",
        "file.delete",
        {"path": "C:/x", "confirmed": True},
    ) is True, (
        "`confirmed: True` satisfied the gate on its own; the comment "
        "claim that it is not an executor gate is wrong"
    )


def test_the_resolver_does_not_read_risk_level():
    """blast_radius only. Directly asserted from the source."""
    import inspect

    from genesis_os.action_executor import (
        _operation_requires_authorization as f,
    )

    source = inspect.getsource(f)

    code_lines = [
        line for line in source.splitlines()
        if not line.strip().startswith("#")
        and not line.strip().startswith('"')
        and not line.strip().startswith("``")
    ]
    code = "\n".join(code_lines)

    assert "risk_level" not in code, (
        "the resolver's executable body references risk_level; the "
        "comment claims it never does"
    )


def test_the_deny_by_default_fallback_is_still_present():
    """An unclassifiable operation is Tier 1."""
    assert _operation_requires_authorization(
        "totally.unregistered.verb", None, {}
    ) is True, (
        "deny-by-default was weakened; an unclassifiable operation is "
        "no longer gated"
    )


# --------------------------------------------------------------------------
# 3. The file is syntactically sound and the gate is where it was
# --------------------------------------------------------------------------

def test_action_executor_still_parses():
    import ast

    ast.parse(SOURCE.read_text(encoding="utf-8-sig"))


def test_the_gate_branch_exists_in_the_executor_source():
    text = SOURCE.read_text(encoding="utf-8-sig")

    assert "if _operation_requires_authorization(" in text, (
        "the executor no longer calls the gate; the corrected comment "
        "describes a branch that is not there"
    )