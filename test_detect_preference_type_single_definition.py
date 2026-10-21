"""Item 26C (L10): duplicate detect_preference_type -- the second
definition silently shadows the first.

MemoryManager defined ``detect_preference_type`` TWICE (class body):
the first version lowercases WITHOUT stripping and knows 10
languages; the second strips whitespace, knows 12 (adds swift and
kotlin) and, being defined later, silently wins. The first is dead
code that still reads like the live contract -- an edit to it would
appear applied and do nothing.

The fix keeps ONE definition: the SECOND (more complete) one --
strips surrounding whitespace (labels arrive from users) and
recognizes the two extra mobile languages -- and deletes the first.

Tests: AST finds exactly one definition; the kept definition returns
the expected type for known inputs (including the behaviors only the
kept version has: strip and swift).
"""
from __future__ import annotations

import ast
import pathlib

from memory.memory import MemoryManager
import memory.memory as memory_module

MODULE = pathlib.Path(memory_module.__file__)


def test_exactly_one_detect_preference_type_definition():
    tree = ast.parse(MODULE.read_text(encoding="utf-8-sig"))
    defs = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "detect_preference_type"
    ]
    assert len(defs) == 1, (
        "duplicate detect_preference_type definitions (lines "
        f"{defs}): the second silently shadows the first, so an edit "
        "to the earlier one looks applied and does nothing"
    )


def test_detection_returns_expected_types():
    detector = MemoryManager().detect_preference_type
    assert detector("Python") == "programming_language"
    assert detector("  Python  ") == "programming_language", (
        "the kept definition must strip whitespace from user labels"
    )
    assert detector("swift") == "programming_language", (
        "the kept definition must know every language the shadowed "
        "one forgot (swift/kotlin)"
    )
    assert detector("kotlin") == "programming_language"
    assert detector("tea") == "general"
