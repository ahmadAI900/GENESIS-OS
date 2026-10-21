"""Item 26D (L11): non-atomic memory write -- interruption corrupts
the file.

``MemoryManager.save_memory`` opened the target with mode "w" (which
TRUNCATES the file immediately) and then streamed ``json.dump`` into
it. An interruption mid-dump -- crash, Ctrl+C, disk full -- left a
truncated/corrupt file with the original content ALREADY GONE: memory
did not survive the crash.

The fix writes the JSON to a temp file in the SAME directory (so the
final rename is atomic on one filesystem), flushes and fsyncs it,
then swaps it in with ``os.replace``. A failure at any point before
the replace leaves the original file byte-for-byte intact, and the
temp file is cleaned up on the error path.
"""
from __future__ import annotations

import json

import pytest

from memory.memory import MemoryManager


def _manager(tmp_path) -> MemoryManager:
    manager = MemoryManager()
    manager.base_path = str(tmp_path)  # never write into the product tree
    return manager


ORIGINAL = '{"memories": [{"message": "i live in paris"}]}'


def test_interrupted_write_leaves_original_intact(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    path.write_text(ORIGINAL, encoding="utf-8")

    def _interrupted_dump(obj, fp, **kwargs):
        fp.write('{"truncated": ')
        raise RuntimeError("simulated interruption mid-write")

    monkeypatch.setattr(json, "dump", _interrupted_dump)

    with pytest.raises(RuntimeError):
        _manager(tmp_path).save_memory(
            "memory.json", {"memories": [], "new": True}
        )

    assert path.read_text(encoding="utf-8") == ORIGINAL, (
        "an interrupted write corrupted the original memory file"
    )
    leftovers = sorted(p.name for p in tmp_path.iterdir())
    assert leftovers == ["memory.json"], (
        f"temp files left behind: {leftovers}"
    )


def test_successful_write_replaces_content(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(ORIGINAL, encoding="utf-8")

    _manager(tmp_path).save_memory("memory.json", {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}
    leftovers = sorted(p.name for p in tmp_path.iterdir())
    assert leftovers == ["memory.json"], leftovers
