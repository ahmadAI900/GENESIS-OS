"""Directive 12B (R4): each resolution is counted once.

`ContextHintResolver.resolve` ran the SAME chain of five resolvers
twice:

    for resolver in (_settings_resolution, _browser_resolution, ...):
        ...
    self._resolutions_attempted += 1
    for resolver in (_settings_resolution, _browser_resolution, ...):   # identical
        ...

The two loops were AST-identical, and each was preceded by its own
`_resolutions_attempted += 1`. Since the first loop returns on a match,
the duplication is invisible on the happy path -- it only shows when
NOTHING matches, where the counters fall through both iterations.

Reproduced before the fix, for one logical resolution of an
unmatchable fragment under a settings_app context:

    expected: attempted=1, succeeded=0
    actual  : attempted=2, succeeded=0

So every failure was counted twice while every success was counted
once, and any success rate derived from `stats` was capped below 100%
no matter how good the resolver was. The duplicated second loop could
never do anything the first had not already tried.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

BACKEND = pathlib.Path(__file__).resolve().parent
SRC = BACKEND / "genesis_os" / "context_hint_resolver.py"

SETTINGS_FIRST_CLAUSE = {
    "level": 3,
    "mode": "os",
    "intent": "system.open_settings",
    "target": "settings",
    "application": "settings",
}

# A fragment that yields a settings_app hint but matches nothing.
UNMATCHABLE = "make me a sandwich"
MATCHING = "turn on bluetooth"


def _resolve_node():
    tree = ast.parse(SRC.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "resolve":
            return node
    raise AssertionError("resolve() not found")


def _fresh():
    from genesis_os.context_hint_resolver import ContextHintResolver

    return ContextHintResolver()


# =====================================================================
# The counters
# =====================================================================

def test_one_non_matching_resolution_counts_as_one_attempt():
    """The regression. Fails before Item 12B: reported 2."""
    resolver = _fresh()
    resolver.resolve(SETTINGS_FIRST_CLAUSE, UNMATCHABLE)

    stats = dict(resolver.stats)
    assert stats["resolutions_attempted"] == 1, (
        f"one logical resolution was counted as "
        f"{stats['resolutions_attempted']} attempts; the resolver chain "
        f"is iterated twice"
    )
    assert stats["resolutions_succeeded"] == 0, stats


def test_one_matching_resolution_counts_as_one_of_each():
    resolver = _fresh()
    resolver.resolve(SETTINGS_FIRST_CLAUSE, MATCHING)

    stats = dict(resolver.stats)
    assert stats["resolutions_attempted"] == 1, stats
    assert stats["resolutions_succeeded"] == 1, stats


def test_attempts_and_successes_stay_in_step():
    """A batch of mixed resolutions must never over-count attempts."""
    resolver = _fresh()
    for fragment in (MATCHING, UNMATCHABLE, MATCHING, UNMATCHABLE):
        resolver.resolve(SETTINGS_FIRST_CLAUSE, fragment)

    stats = dict(resolver.stats)
    assert stats["resolutions_attempted"] == 4, stats
    assert stats["resolutions_succeeded"] == 2, stats
    assert stats["resolutions_attempted"] >= stats["resolutions_succeeded"], (
        "attempts must be at least successes"
    )


def test_a_purely_failing_batch_can_reach_a_honest_zero_rate():
    """Before the fix this was structurally impossible.

    With every resolution failing, attempts used to exceed successes
    strictly, so a success rate could never be 0/0-with-zero-failures;
    it always looked as though some attempts had been wasted.
    """
    resolver = _fresh()
    for _ in range(5):
        resolver.resolve(SETTINGS_FIRST_CLAUSE, UNMATCHABLE)

    stats = dict(resolver.stats)
    assert stats == {
        "resolutions_attempted": 5,
        "resolutions_succeeded": 0,
    }, stats


def test_the_standalone_shortcut_is_still_counted_once():
    """The early-return path above the loop was always correct; guard it."""
    resolver = _fresh()
    resolver.resolve({}, "open bluetooth settings")

    stats = dict(resolver.stats)
    assert stats["resolutions_attempted"] == 1, stats
    assert stats["resolutions_succeeded"] == 1, stats


# =====================================================================
# Structural: one loop, one bump
# =====================================================================

def test_resolve_iterates_the_chain_exactly_once():
    """The duplication, asserted at the source level."""
    node = _resolve_node()
    loops = [n for n in node.body if isinstance(n, ast.For)]
    assert len(loops) == 1, (
        f"resolve() contains {len(loops)} resolver loops at lines "
        f"{[n.lineno for n in loops]}; a second identical chain can only "
        f"re-run work the first already did"
    )


def test_the_chain_is_still_all_five_resolvers():
    """Deleting the duplicate must not have shortened the real chain."""
    node = _resolve_node()
    (loop,) = [n for n in node.body if isinstance(n, ast.For)]
    names = [ast.unparse(e) for e in loop.iter.elts]
    assert names == [
        "_settings_resolution",
        "_browser_resolution",
        "_browser_action_resolution",
        "_file_manager_resolution",
        "_app_create_document_resolution",
    ], names


def test_attempted_is_bumped_once_per_logical_resolution():
    """Two sites remain: the standalone shortcut and the chain entry."""
    node = _resolve_node()
    bumps = [
        n.lineno
        for n in ast.walk(node)
        if isinstance(n, ast.AugAssign)
        and ast.unparse(n.target) == "self._resolutions_attempted"
    ]
    assert len(bumps) == 2, (
        f"_resolutions_attempted is bumped at {bumps}; expected exactly "
        f"two sites (standalone shortcut, chain entry)"
    )


def test_resolution_behaviour_is_unchanged_by_the_dedup():
    """Collapsing the loop must not change what resolve() returns."""
    resolver = _fresh()
    ok = resolver.resolve(SETTINGS_FIRST_CLAUSE, MATCHING)
    assert ok.resolved is True
    assert ok.decision["intent"] == "system.open_settings", ok.decision

    resolver2 = _fresh()
    miss = resolver2.resolve(SETTINGS_FIRST_CLAUSE, UNMATCHABLE)
    assert miss.resolved is False
    assert miss.family == "no_match", miss.family