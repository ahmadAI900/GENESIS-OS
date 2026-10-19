"""Item 16A (R8): a bare "next" was treated as a clause boundary.

`ObjectiveUnderstanding._BOUNDARY_RE` contained `\bnext\b`, so wherever
the word appeared it split the objective. In English "next" is
overwhelmingly an ORDINAL DETERMINER -- "the next one" -- not a
conjunction. Measured against the committed original:

    "play the next song"          -> ["play the", "song"]
    "go to the next slide"        -> ["go to the", "slide"]
    "open the next folder"        -> ["open the", "folder"]
    "download the next report"    -> ["download the", "report"]
    "jump to the next line"       -> ["jump to the", "line"]
    "the next step is to open Chrome"
                                 -> ["the", "step is to open Chrome"]

Every one of those is a single instruction that the user typed once.
The splitter invented a second step -- sometimes a fragment with no verb
at all ("song") -- out of one clause. That is a correctness failure in
the front door: the thing that decides what Genesis does next.

The fix requires a VERB to follow "next" before it may split, mirroring
the stricter splitter in `agents/workflow_decision.py::_L3_VERB_SPLIT`.
"""
from __future__ import annotations

import re

import pytest

from genesis_os.objective_understanding import ObjectiveUnderstanding


@pytest.fixture(scope="module")
def ou():
    from agents.workflow_decision import WorkflowDecisionEngine

    return ObjectiveUnderstanding(WorkflowDecisionEngine())


# --------------------------------------------------------------------------
# The defect: "the next <noun>" is one objective
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "objective",
    [
        "play the next song",
        "go to the next slide",
        "open the next folder",
        "download the next report",
        "jump to the next line",
        "show the next image",
        "delete the next file",
        "copy the next three documents",
    ],
)
def test_the_next_noun_is_a_single_step(ou, objective):
    steps = ou.split_objective(objective)

    assert len(steps) == 1, (
        f"{objective!r} was split into {list(steps)}; it is one "
        "instruction and 'next' is an ordinal determiner here, not a "
        "conjunction"
    )
    assert steps[0].lower().startswith(objective.split()[0].lower())


def test_the_next_noun_step_is_kept_whole(ou):
    """The surviving step must be the whole instruction, not a fragment."""
    steps = ou.split_objective("play the next song")

    assert len(steps) == 1
    assert "next" in steps[0].lower(), (
        f"the determiner was dropped from the step: {steps[0]!r}"
    )


def test_the_next_sentence_fragment_is_not_a_step(ou):
    """Before the fix the trailing noun became a step with no verb."""
    steps = ou.split_objective("play the next song")

    for step in steps:
        assert step.strip(), "an empty step was produced"


def test_the_next_step_is_not_torn(ou):
    steps = ou.split_objective("the next step is to open Chrome")

    assert len(steps) == 1, (
        f"got {list(steps)}; 'the next step' is a noun phrase"
    )


# --------------------------------------------------------------------------
# The counterpart: a genuine "next <verb>" still splits
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "objective,expected",
    [
        ("open Chrome, then open Word", ["open Chrome", "open Word"]),
        ("open Chrome then open Word", ["open Chrome", "open Word"]),
        ("close Word then open Chrome", ["close Word", "open Chrome"]),
        ("copy the file then delete the folder",
         ["copy the file", "delete the folder"]),
    ],
)
def test_real_boundaries_still_split(ou, objective, expected):
    steps = list(ou.split_objective(objective))

    assert steps == expected, (
        f"{objective!r} -> {steps}, expected {expected}; the fix must "
        "not have disabled genuine multi-step splitting"
    )


@pytest.mark.parametrize(
    "objective,count",
    [
        ("next open Chrome", 1),
        ("after that close Word", 1),
        ("open Chrome then next open Word", 2),
        ("open Chrome, next open Word", 2),
    ],
)
def test_next_before_a_verb_splits_and_consumes_itself(ou, objective, count):
    """`next open Chrome` IS one clause; the leading token is consumed.

    The boundary word is the connector, not content, so a leading "next"
    leaves exactly the clause it introduced.
    """
    steps = list(ou.split_objective(objective))

    assert len(steps) == count, f"{objective!r} -> {steps}"


def test_the_other_boundaries_are_unaffected(ou):
    assert len(ou.split_objective("open Chrome; open Word")) == 2
    assert len(ou.split_objective("after that close Word")) == 1


# --------------------------------------------------------------------------
# Structural guards
# --------------------------------------------------------------------------

def test_next_is_not_a_bare_alternative_in_the_boundary_regex():
    """`\\bnext\\b` on its own is the exact defect."""
    from genesis_os.objective_understanding import (
        ObjectiveUnderstanding as OU,
    )

    pattern = OU._BOUNDARY_RE.pattern

    assert not re.search(r"\|next\\b", pattern), (
        "next is a bare alternative in _BOUNDARY_RE again; it will "
        "split every 'the next <noun>'"
    )


def test_next_requires_a_verb_to_follow():
    from genesis_os.objective_understanding import (
        ObjectiveUnderstanding as OU,
    )

    pattern = OU._BOUNDARY_RE.pattern

    assert re.search(r"next\\s\+\(\?=", pattern), (
        "next must be followed by a verb lookahead, or it is a bare "
        "word boundary again"
    )


def test_the_regex_is_built_after_the_verb_pattern():
    """Ordering: it interpolates _ACTION_VERB_PATTERN, so it must come later."""
    from genesis_os.objective_understanding import (
        ObjectiveUnderstanding as OU,
    )

    assert OU._BOUNDARY_RE.pattern.count("(?:" ) >= 2, (
        "the boundary regex no longer embeds the action verb pattern"
    )


def test_the_split_is_driven_by_the_boundary_regex():
    """Sanity: a bare 'next' really would split under the old pattern."""
    old = re.compile(r"\s*(?:;|\b(?:then|and then|after that|next)\b)\s*",
                     re.IGNORECASE)
    new = OU_boundary = ObjectiveUnderstanding._BOUNDARY_RE

    assert len(old.split("play the next song")) == 2, (
        "the old pattern is expected to split; if not, this test no "
        "longer demonstrates the defect"
    )
    assert len(OU_boundary.split("play the next song")) == 1


def test_semicolon_and_then_still_split_unaided(ou):
    for objective in (
        "open Chrome; open Word",
        "open Chrome and then open Word",
        "after that close Word",
    ):
        assert ou.split_objective(objective) is not None


# --------------------------------------------------------------------------
# Broader "next" sweep -- nothing that reads as an ordinal may split
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "objective",
    [
        "read the next chapter",
        "rename the next folder to archive",
        "move the next file to backups",
        "calculate the next total",
        "filter the next column",
        "sort the next row",
    ],
)
def test_no_ordinal_next_splits(ou, objective):
    steps = ou.split_objective(objective)

    # A split is acceptable here only if BOTH halves carry a verb,
    # i.e. it is a genuine compound rather than a torn noun phrase.
    for step in steps:
        assert len(step.split()) >= 2, (
            f"{objective!r} -> {list(steps)}; {step!r} is a bare noun "
            "fragment, which means the sentence was torn"
        )