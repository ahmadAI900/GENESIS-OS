"""Item 26E (L12): save_if_important silently dropped dict-format
memory files.

``save_if_important`` loaded the store and did
``if not isinstance(data, list): memories = []``. A dict-format file
-- the format ``get_relevent_memory`` and ``memory_exists`` both
understand (``{"memories": [...]}``) -- was therefore DISCARDED
wholesale: the next save replaced it with a bare list containing only
the new item. Every previously remembered fact in that file was
silently dropped, and the file format flipped under the readers.

The fix reads dict-format stores (honouring their ``memories`` list)
and persists them back in the SAME format, preserving the other keys.
List-format files are untouched behaviour.
"""
from __future__ import annotations

import json

from memory.memory import MemoryManager


def _manager(tmp_path) -> MemoryManager:
    manager = MemoryManager()
    manager.base_path = str(tmp_path)  # never write into the product tree
    return manager


DICT_STORE = {
    "version": 1,
    "memories": [
        {"message": "i live in paris", "category": "profile"},
    ],
}


def test_dict_format_item_is_saved_and_existing_data_survives(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(json.dumps(DICT_STORE), encoding="utf-8")
    manager = _manager(tmp_path)

    assert manager.save_if_important(
        "my favorite language is python"
    ) is True

    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), (
        f"dict-format store was flattened to {type(data).__name__}"
    )
    messages = [item.get("message", "") for item in data["memories"]]
    assert any("paris" in msg.lower() for msg in messages), (
        f"existing dict-format data was silently dropped: {data!r}"
    )
    assert any("python" in msg.lower() for msg in messages), (
        f"the new item was not persisted: {data!r}"
    )
    assert data.get("version") == 1, (
        f"other dict keys were dropped: {data!r}"
    )


def test_both_items_are_retrievable_afterwards(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(json.dumps(DICT_STORE), encoding="utf-8")
    manager = _manager(tmp_path)

    manager.save_if_important("my favorite language is python")

    paris = manager.get_relevent_memory("paris", limit=5)
    python = manager.get_relevent_memory("python", limit=5)
    assert any(
        "paris" in item.get("message", "").lower() for item in paris
    ), f"the old memory is unreachable: {paris!r}"
    assert any(
        "python" in item.get("message", "").lower() for item in python
    ), f"the new memory is unreachable: {python!r}"


def test_list_format_files_still_work(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps([{"message": "i live in rome", "category": "profile"}]),
        encoding="utf-8",
    )
    manager = _manager(tmp_path)

    assert manager.save_if_important(
        "my favorite language is python"
    ) is True

    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 2, data
