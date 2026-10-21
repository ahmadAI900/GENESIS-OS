"""Item 26A (L2): update_preference always fell into the for/else
append, so updating an EXISTING preference stored a duplicate key.

The method found the existing key (case/space-insensitive), replaced
it in place -- and then ran a "remove duplicates" for-loop whose ELSE
clause ALWAYS executed, because the loop contains no ``break``. The
else appended ``preferences[preference] = liked`` under the caller's
spelling. When the stored key differed in case or spacing from the
input ("Python" vs "python"), the file grew a SECOND entry for the
same preference: memory duplicated instead of updated.

The fix restructures the flow honestly: replace on match, append only
when absent, dedupe other variants, save and return True once.
"""
from __future__ import annotations

from memory.memory import MemoryManager


def _manager(tmp_path) -> MemoryManager:
    manager = MemoryManager()
    manager.base_path = str(tmp_path)  # never write into the product tree
    return manager


def test_updating_existing_preference_leaves_exactly_one_entry(tmp_path):
    manager = _manager(tmp_path)

    assert manager.update_preference("Python", liked=True) is True
    assert manager.update_preference("python", liked=False) is True

    stored = manager.load_preferences()
    matching = [
        key
        for key in stored
        if str(key).strip().lower() == "python"
    ]
    assert len(matching) == 1, (
        "updating an existing preference appended a duplicate instead "
        f"of replacing it: {stored!r}"
    )
    assert stored[matching[0]] is False, stored
    assert len(stored) == 1, (
        f"unexpected extra preferences appeared: {stored!r}"
    )


def test_absent_preference_is_still_appended(tmp_path):
    manager = _manager(tmp_path)

    assert manager.update_preference("vim", liked=True) is True
    assert manager.load_preferences() == {"vim": True}


def test_stored_update_persists_to_disk(tmp_path):
    import json

    manager = _manager(tmp_path)
    manager.update_preference("Python", liked=True)
    manager.update_preference("python", liked=False)

    on_disk = json.loads(
        (tmp_path / "preferences.json").read_text(encoding="utf-8")
    )
    assert list(on_disk.values()) == [False], on_disk
