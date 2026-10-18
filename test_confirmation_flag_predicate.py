"""Directive 12D (R6): one consistent predicate for the confirmation flags.

`ObjectiveUnderstanding._extract_constraints` read:

    if parameters.get("requires_confirmation") or parameters.get("confirmed") is False:

TRUTHINESS for the first, IDENTITY for the second, on the same concept.
Measured before the fix:

    value      requires_confirmation   confirmed
    True       TRIGGERS                 -
    False      -                        TRIGGERS
    1          TRIGGERS                 -
    "yes"      TRIGGERS                 -
    "false"    TRIGGERS                 -      <-- the irony
    [1]        TRIGGERS                 -
    0          -                        -

The string "false" demanded a human confirmation while the boolean
False did not, and 0 and False -- the same idea -- behaved differently
between the two flags.

STRICT IDENTITY is correct here because every product producer already
assigns a real boolean: 40 literal assignments plus 10 that forward a
typed attribute (one an explicit `bool(...)`). Nothing relied on the
truthiness readings, so this narrows the accepted values without
changing any real code path.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

BACKEND = pathlib.Path(__file__).resolve().parent
SRC = BACKEND / "genesis_os" / "objective_understanding.py"


def _extract(flag: str, value):
    from genesis_os.objective_understanding import ObjectiveUnderstanding

    resolver = ObjectiveUnderstanding.__new__(ObjectiveUnderstanding)
    return resolver._extract_constraints(
        "do a thing",
        {"operation": "x", "parameters": {flag: value}},
    )


def _triggers(flag: str, value) -> bool:
    return "requires_confirmation" in _extract(flag, value)


# The truth table both flags must obey after the fix.
BOOL_VALUES = [True, False, 1, 0, "yes", "no", "", None, [], [1], 2.5, "false"]


# =====================================================================
# The regression
# =====================================================================

def test_requires_confirmation_accepts_only_true():
    """Fails before Item 12D: 1, "yes", "false" and [1] all triggered."""
    assert _triggers("requires_confirmation", True) is True
    for value in (1, "yes", "no", "", 2.5, [1], [0]):
        assert _triggers("requires_confirmation", value) is False, (
            f"requires_confirmation={value!r} must not demand a "
            f"confirmation; only the boolean True should"
        )


def test_confirmed_accepts_only_false():
    """Fails before Item 12D: truthiness on the other half."""
    assert _triggers("confirmed", False) is True
    for value in (True, 0, "no", "", None, 2.5, [1], [0]):
        assert _triggers("confirmed", value) is False, (
            f"confirmed={value!r} must not demand a confirmation; only "
            f"the boolean False should"
        )


@pytest.mark.parametrize("value", BOOL_VALUES)
def test_both_flags_agree_that_non_booleans_do_not_count(value):
    """The consistency that was missing: the SAME value must be
    treated the same way by both flags.

    Booleans are excluded on purpose -- for a real bool the two flags
    are SUPPOSED to disagree, because `requires_confirmation=True` and
    `confirmed=False` both say "a human must approve" via different
    keys. For everything else they must agree, and they must agree on
    "neither counts"."""
    if value is True or value is False:
        pytest.skip("a real boolean legitimately means opposite things "
                    "on the two flags; covered by the tests above")

    assert _triggers("requires_confirmation", value) is False, (
        f"requires_confirmation={value!r} must not count"
    )
    assert _triggers("confirmed", value) is False, (
        f"confirmed={value!r} must not count"
    )


def test_the_whole_truth_table_is_what_we_intend():
    """One explicit table, so the intent is readable in one place.

    A list of tuples, not a dict: `[]` and `[1]` are unhashable and
    cannot be dict keys.
    """
    expected = [
        # value          requires_confirmation   confirmed
        (True,           True,  False),
        (False,          False, True),
        (1,              False, False),
        (0,              False, False),
        ("yes",          False, False),
        ("no",           False, False),
        ("",             False, False),
        (None,           False, False),
        ([],             False, False),
        ([1],            False, False),
        (2.5,            False, False),
        ("false",        False, False),
    ]
    for value, want_req, want_conf in expected:
        assert _triggers("requires_confirmation", value) is want_req, (
            f"requires_confirmation={value!r}: expected {want_req}"
        )
        assert _triggers("confirmed", value) is want_conf, (
            f"confirmed={value!r}: expected {want_conf}"
        )


def test_the_string_false_does_not_demand_confirmation():
    """The single clearest symptom."""
    assert _triggers("requires_confirmation", "false") is False
    assert _triggers("confirmed", "false") is False


def test_zero_and_false_are_handled_as_they_read():
    """0 and False mean the same thing to a reader."""
    assert _triggers("requires_confirmation", 0) is False
    assert _triggers("requires_confirmation", False) is False
    assert _triggers("confirmed", 0) is False
    assert _triggers("confirmed", False) is True, (
        "confirmed=False is the real, documented signal and must survive"
    )


# =====================================================================
# The real, documented cases are untouched
# =====================================================================

def test_the_real_producer_pairs_still_trigger():
    """The exact shape workflow_decision.py emits."""
    from genesis_os.objective_understanding import ObjectiveUnderstanding

    resolver = ObjectiveUnderstanding.__new__(ObjectiveUnderstanding)
    out = resolver._extract_constraints(
        "install something",
        {
            "operation": "package.install",
            "parameters": {"confirmed": False, "requires_confirmation": True},
        },
    )
    assert "requires_confirmation" in out, out


def test_either_flag_alone_is_enough():
    assert _triggers("requires_confirmation", True) is True
    assert _triggers("confirmed", False) is True


def test_neither_flag_means_no_constraint():
    from genesis_os.objective_understanding import ObjectiveUnderstanding

    resolver = ObjectiveUnderstanding.__new__(ObjectiveUnderstanding)
    out = resolver._extract_constraints(
        "rename a file",
        {"operation": "file.rename", "parameters": {}},
    )
    assert "requires_confirmation" not in out, out


def test_absent_parameters_do_not_blow_up():
    from genesis_os.objective_understanding import ObjectiveUnderstanding

    resolver = ObjectiveUnderstanding.__new__(ObjectiveUnderstanding)
    out = resolver._extract_constraints(
        "do a thing", {"operation": "x"}
    )
    assert isinstance(out, tuple)


def test_the_destructive_constraint_is_unaffected():
    """Only the confirmation predicate changed, not the neighbours."""
    from genesis_os.objective_understanding import ObjectiveUnderstanding

    resolver = ObjectiveUnderstanding.__new__(ObjectiveUnderstanding)
    out = resolver._extract_constraints(
        "delete it",
        {"operation": "file.delete", "parameters": {"confirmed": "yes"}},
    )
    assert "destructive_operation" in out, out


# =====================================================================
# Structural
# =====================================================================

def test_the_predicate_uses_identity_for_both_flags():
    """No truthiness may creep back in."""
    source = SRC.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_extract_constraints"
        ):
            identity = []
            for n in ast.walk(node):
                if isinstance(n, ast.Compare) and any(
                    isinstance(op, (ast.Is, ast.IsNot)) for op in n.ops
                ):
                    identity.append(ast.unparse(n))
            assert identity, (
                "_extract_constraints no longer uses identity checks for "
                "the confirmation flags"
            )
            compared = " | ".join(identity)
            assert "requires_confirmation" in compared, compared
            assert "'confirmed'" in compared, compared
            break
    else:
        raise AssertionError("_extract_constraints not found")