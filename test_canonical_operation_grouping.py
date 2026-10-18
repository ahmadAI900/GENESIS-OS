"""Directive 12E (R7): the and/or grouping in _canonical_operation.

The suffix-match comprehension read, with no boolean parentheses:

    if "." in capability_id
    and capability_id.split(".", 1)[1] == proposed
    or capability_id.replace(".", "_") == proposed

Python binds `and` tighter than `or`, so this has always evaluated as

    ("." in capability_id and suffix == proposed) or (flattened == proposed)

The parentheses that ARE present belong to `.split(".", 1)` and
`.replace(".", "_")` -- method-call arguments -- so there is no visible
grouping anywhere in the condition. The competing reading, `"." in
capability_id and (suffix == proposed or flattened == proposed)`, is
plausible enough to be mistaken for the intended one.

BEFORE parenthesising, the two groupings were compared against the real
registry: all 143 registered operations contain a dot, and across all
399 distinct proposals reachable from it (every id, every dotted
suffix, every flattened form, plus junk) the groupings produced ZERO
disagreements. So the explicit parentheses below state existing
behaviour; they do not choose a new one.

These tests pin the truth table so a future edit cannot silently flip
the grouping to the other reading.
"""

from __future__ import annotations

import ast
import itertools
import pathlib

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

BACKEND = pathlib.Path(__file__).resolve().parent
SRC = BACKEND / "genesis_os" / "llm_intent_resolver.py"


@pytest.fixture(scope="module")
def registry():
    from genesis_os.capability_registry import CapabilityRegistry

    return CapabilityRegistry.operations()


def _matches_current(capability_id: str, proposed: str) -> bool:
    """The grouping as it has always evaluated."""
    return ("." in capability_id
            and capability_id.split(".", 1)[1] == proposed) or \
           capability_id.replace(".", "_") == proposed


def _matches_alternative(capability_id: str, proposed: str) -> bool:
    """The competing reading: dot required for BOTH branches."""
    return "." in capability_id and (
        capability_id.split(".", 1)[1] == proposed
        or capability_id.replace(".", "_") == proposed
    )


def _resolved(proposed: str):
    from genesis_os.llm_intent_resolver import LLMIntentResolver

    return LLMIntentResolver._canonical_operation(proposed)


# =====================================================================
# The truth table
# =====================================================================

@pytest.mark.parametrize(
    "proposed,expected",
    [
        ("display.brightness_set", "display.brightness_set"),  # exact
        ("brightness_set", "display.brightness_set"),          # suffix
        ("file_copy", "file.copy"),                            # flattened
        ("open_url", "browser.open_url"),                       # suffix
        ("totally_made_up", None),                              # no match
        ("", None),                                             # empty
    ],
)
def test_the_truth_table(proposed, expected):
    assert _resolved(proposed) == expected, (
        f"_canonical_operation({proposed!r}) returned {_resolved(proposed)!r}"
    )


def test_the_suffix_branch_requires_a_dot(registry):
    """Branch one: a DOTTED id matches on the text after its first dot."""
    dotted = [c for c in registry if "." in c]
    assert dotted, "registry has no dotted ids"

    sample = dotted[0]
    suffix = sample.split(".", 1)[1]
    assert sample in [
        c for c in registry if _matches_current(c, suffix)
    ], f"{suffix!r} should have matched {sample!r}"


def test_the_flattened_branch_matches_the_whole_id(registry):
    """Branch two: a DOTTED id also matches with its dot flattened."""
    sample = next(c for c in registry if "." in c)
    flattened = sample.replace(".", "_")
    assert _matches_current(sample, flattened) is True
    assert flattened != sample, "flattening should change the string"


def test_ambiguous_suffixes_are_discarded_not_guessed(registry):
    """The docstring promises this; a suffix shared by two ids resolves
    to None rather than picking one."""
    by_suffix = {}
    for capability_id in registry:
        if "." in capability_id:
            by_suffix.setdefault(
                capability_id.split(".", 1)[1], []
            ).append(capability_id)

    ambiguous = [
        suffix for suffix, ids in by_suffix.items() if len(ids) > 1
    ]
    assert ambiguous, (
        "no ambiguous suffixes in the registry; the never-guess "
        "guarantee cannot be tested"
    )
    for suffix in ambiguous[:3]:
        assert _resolved(suffix) is None, (
            f"{suffix!r} is ambiguous but resolved to "
            f"{_resolved(suffix)!r}; ambiguous proposals must be discarded"
        )


# =====================================================================
# The two groupings agree on the real registry -- and must keep agreeing
# =====================================================================

def test_the_two_groupings_agree_on_every_reachable_proposal(registry):
    """This is why the fix changed nothing, and why it can stay safe."""
    proposals = set()
    for capability_id in registry:
        proposals.add(capability_id)
        if "." in capability_id:
            proposals.add(capability_id.split(".", 1)[1])
            proposals.add(capability_id.replace(".", "_"))
    proposals.update(["made_up_capability", "", "a b c"])

    disagreements = [
        proposed
        for proposed in sorted(proposals)
        if [c for c in registry if _matches_current(c, proposed)]
        != [c for c in registry if _matches_alternative(c, proposed)]
    ]
    assert not disagreements, (
        "the two groupings now disagree; the explicit parentheses are "
        f"asserting the wrong one: {disagreements[:5]}"
    )


def test_the_registry_has_no_undotted_operations(registry):
    """Why they agree: the branch without a dot-check is unreachable."""
    undotted = [c for c in registry if "." not in c]
    assert not undotted, (
        f"{len(undotted)} registered operations contain no dot, so the "
        f"two groupings can now diverge. Re-check which grouping is "
        f"intended before trusting the parentheses."
    )


# =====================================================================
# Structural: the grouping is now visible in the source
# =====================================================================

def _canonical_operation_source() -> str:
    source = SRC.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_canonical_operation"
        ):
            return ast.get_source_segment(source, node) or ""
    raise AssertionError("_canonical_operation not found")


def _code_only(segment: str) -> str:
    """Drop `#` comments so a comment sitting between `(` and `and`
    cannot disguise an opening paren."""
    return "\n".join(
        line.split("#", 1)[0] for line in segment.splitlines()
    )


def _paren_depth(text: str) -> int:
    """Net '(' depth, ignoring anything inside quotes."""
    depth = 0
    quote = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    return depth


def _is_grouped(segment: str, risky: str) -> bool:
    """True when `risky` sits inside a parenthesis, i.e. its grouping is
    visible in the source rather than left to precedence."""
    code = _code_only(segment)
    idx = code.find(risky)
    if idx == -1:
        return True  # nothing to group
    return _paren_depth(code[:idx]) >= 1


def test_the_source_shows_an_explicit_grouping():
    """`and` must be parenthesised so a reader can SEE the grouping.

    This has to be a source check, not an AST check: parentheses do not
    change the parse tree. `A and B or C` and `(A and B) or C` are the
    SAME ast.BoolOp, which is precisely why the original was ambiguous
    to a reader and invisible to tooling.
    """
    body = _code_only(_canonical_operation_source())

    condition = body[body.find("suffix_matches"):]
    assert condition, "could not locate the suffix_matches comprehension"
    assert " and " in condition, condition

    assert _is_grouped(condition, " and "), (
        "the `and` branch is not inside a parenthesis, so its grouping is "
        "still decided by precedence alone. Source:\n" + condition[:300]
    )


def test_no_mixed_and_or_remains_ungrouped_in_this_module():
    """Module-wide, so the shape cannot reappear elsewhere.

    Source-level for the same reason as above: the AST cannot tell the
    two groupings apart, so each precedence-sensitive expression is
    checked for a parenthesis immediately before its inner operator.
    """
    source = SRC.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp):
            continue
        outer = type(node.op).__name__
        has_other = any(
            isinstance(v, ast.BoolOp) and type(v.op).__name__ != outer
            for v in node.values
        )
        if not has_other:
            continue
        segment = ast.get_source_segment(source, node) or ""
        # For an outer Or the risky operator is `and`, and vice versa.
        risky = " and " if outer == "Or" else " or "
        if not _is_grouped(segment, risky):
            offenders.append(
                (node.lineno, node.end_lineno,
                 _code_only(segment).replace("\n", " ")[:110])
            )

    assert not offenders, (
        "an ungrouped mixed and/or reappeared (source not parenthesised "
        "around the inner operator): "
        + "; ".join(f"line {lo}-{hi}: {s}" for lo, hi, s in offenders)
    )