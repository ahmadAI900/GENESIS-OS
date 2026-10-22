"""Item 27C (L8): is_reasoning_request matched "if" inside other words.

brain/brain.py's is_reasoning_request tested each keyword with a raw
substring test (`keyword in text`). The keyword "if" therefore fired
inside "verify", "modify" and "beautiful" -- so "verify this file" was
treated as a reasoning request and was answered by the reasoning
engine instead of the normal AI path.

The fix matches on word boundaries (the same \\b-anchored, escaped,
cached pattern convention agents/workflow_decision.py already uses),
so a standalone "if" still matches while inside-of-a-word hits do not.

These tests pin:
  * verify / modify / beautiful are NOT reasoning requests,
  * a standalone "if" IS a reasoning request,
  * the other reasoning keywords still fire, including the multi-word
    phrases ("how many", "how much"),
  * the match site is no longer a raw substring test.
"""
from __future__ import annotations

from inspect import getsource

from brain.brain import Brain


def is_reasoning(text: str) -> bool:
    return Brain.is_reasoning_request(Brain.__new__(Brain), text)


FALSE_POSITIVES = [
    "verify this file",
    "modify the plan",
    "beautiful weather today",
    "verify and modify the beautiful layout",
]


def test_verify_is_not_a_reasoning_request():
    assert not is_reasoning("verify this file"), (
        "'verify' contains 'if' and was treated as a reasoning request"
    )


def test_modify_is_not_a_reasoning_request():
    assert not is_reasoning("modify the plan"), (
        "'modify' contains 'if' and was treated as a reasoning request"
    )


def test_beautiful_is_not_a_reasoning_request():
    assert not is_reasoning("beautiful weather today"), (
        "'beautiful' contains 'if' and was treated as a reasoning request"
    )


def test_none_of_the_substring_hits_are_reasoning_requests():
    for text in FALSE_POSITIVES:
        assert not is_reasoning(text), (
            f"{text!r} was treated as a reasoning request because a "
            "keyword matched inside a word"
        )


def test_a_standalone_if_is_still_a_reasoning_request():
    assert is_reasoning("if I add two numbers what do I get"), (
        "a standalone 'if' must still select the reasoning engine"
    )


def test_the_other_reasoning_keywords_still_fire():
    for text in [
        "solve this equation",
        "calculate the total",
        "how many apples are there",
        "how much does it cost",
        "why is the sky blue",
        "explain gravity",
        "compare python and rust",
        "this is a problem",
    ]:
        assert is_reasoning(text), (
            f"{text!r} stopped being a reasoning request"
        )


def test_the_match_site_is_not_a_raw_substring_test():
    source = getsource(Brain.is_reasoning_request)

    assert "keyword in text" not in source, (
        "is_reasoning_request still uses a raw substring test"
    )
