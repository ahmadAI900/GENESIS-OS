"""Item 26B (L3): build_preference_context raised UnboundLocalError
(or rendered stale data) for str-typed preference items.

The loop only bound ``preference``/``liked`` inside
``if isinstance(item, dict)`` but then tested ``if preference:`` for
EVERY item. A str item therefore either raised UnboundLocalError
(first iteration) or -- if a dict had come first -- reused the
PREVIOUS item's value: the str item vanished and a duplicate of the
previous line could be emitted.

The fix branches on the item type first; both dict items (with liked
flag) and plain strings build context without error and appear.
"""
from __future__ import annotations

from memory.memory import MemoryManager


def _manager() -> MemoryManager:
    return MemoryManager()


def test_str_items_do_not_raise_and_appear():
    context = _manager().build_preference_context(["rust", "dark mode"])
    assert "- User prefers rust." in context
    assert "- User prefers dark mode." in context


def test_dict_items_still_render_with_liked_flag():
    context = _manager().build_preference_context(
        [
            {"preference": "python", "liked": True},
            {"preference": "javascript", "liked": False},
        ]
    )
    assert "- User prefers python." in context
    assert "- User does not like javascript." in context


def test_mixed_str_and_dict_items_all_appear_exactly_once():
    context = _manager().build_preference_context(
        [
            {"preference": "python", "liked": True},
            "rust",
            {"preference": "vim", "liked": False},
        ]
    )
    assert context.count("- User prefers python.") == 1
    assert "- User prefers rust." in context
    assert context.count("- User prefers rust.") == 1
    assert "- User does not like vim." in context
