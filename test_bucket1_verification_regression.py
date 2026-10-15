"""
Regression tests for Bucket 1 verification fixes.

Covers:
    - file_manager.FileManager.copy() now performs a real post-state
      filesystem verification (destination exists, size matches) instead
      of trusting shutil.copy2()'s "no exception" return.
    - file_manager.FileManager.move() verifies destination exists AND
      source was actually removed.
    - agents.orchestrator.AgentOrchestrator.execute() rejects None,
      empty string, and empty containers instead of unconditionally
      returning success=True.
"""

from pathlib import Path

from genesis_os.filesystem.file_manager import FileManager
from agents.orchestrator import AgentOrchestrator


class _FakeAgent:
    def __init__(self, name, response):
        self._name = name
        self._response = response

    def get_info(self):
        return {"name": self._name}

    def run(self, task):
        return self._response


def test_copy_success_is_verified(tmp_path):
    source = tmp_path / "src.txt"
    source.write_text("genesis copy payload", encoding="utf-8")
    dest = tmp_path / "dest.txt"

    result = FileManager().copy(source, dest)

    assert result["success"] is True
    assert result["verified"] is True
    assert dest.is_file()
    assert dest.read_text(encoding="utf-8") == "genesis copy payload"


def test_copy_reports_failure_when_destination_missing(tmp_path, monkeypatch):
    source = tmp_path / "src.txt"
    source.write_text("payload", encoding="utf-8")
    dest = tmp_path / "dest.txt"

    real_copy2_call_count = {"n": 0}

    import shutil

    real_copy2 = shutil.copy2

    def _spy_copy2(src, dst, *args, **kwargs):
        real_copy2_call_count["n"] += 1
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", _spy_copy2)

    original_is_file = Path.is_file

    def _is_file_patched(self):
        if str(self) == str(dest):
            return False
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", _is_file_patched)

    result = FileManager().copy(source, dest)

    assert real_copy2_call_count["n"] == 1
    assert result["success"] is False
    assert result["verified"] is False
    assert "destination was not verified" in result["message"]


def test_copy_reports_failure_when_sizes_mismatch(tmp_path, monkeypatch):
    source = tmp_path / "src.txt"
    source.write_text("full payload content", encoding="utf-8")
    dest = tmp_path / "dest.txt"
    dest_resolved = dest.resolve()

    class _StatProxy:
        def __init__(self, size):
            self.st_size = size
            self.st_mode = 0o100644

    original_stat = Path.stat

    def _stat_truncated(self, *args, **kwargs):
        if Path(self) == dest_resolved:
            return _StatProxy(5)
        return original_stat(self)

    monkeypatch.setattr(Path, "stat", _stat_truncated)

    result = FileManager().copy(source, dest)

    assert result["success"] is False
    assert result["verified"] is False


def test_move_success_is_verified(tmp_path):
    source = tmp_path / "movable.txt"
    source.write_text("move me", encoding="utf-8")
    dest = tmp_path / "moved.txt"

    result = FileManager().move(source, dest)

    assert result["success"] is True
    assert result["verified"] is True
    assert dest.is_file()
    assert not source.exists()
    assert dest.read_text(encoding="utf-8") == "move me"


def test_move_reports_failure_when_destination_missing(tmp_path, monkeypatch):
    source = tmp_path / "movable.txt"
    source.write_text("move me", encoding="utf-8")
    dest = tmp_path / "moved.txt"
    dest_resolved = dest.resolve()

    import shutil
    real_move = shutil.move

    def _spy_move(src, dst, *args, **kwargs):
        return real_move(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "move", _spy_move)

    original_is_file = Path.is_file

    def _is_file_patched(self):
        if Path(self) == dest_resolved:
            return False
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", _is_file_patched)

    result = FileManager().move(source, dest)

    assert result["success"] is False
    assert result["verified"] is False


def test_move_reports_failure_when_source_still_present(tmp_path, monkeypatch):
    source = tmp_path / "movable.txt"
    source.write_text("move me", encoding="utf-8")
    source_resolved = source.resolve()

    original_exists = Path.exists

    def _exists_patched(self):
        if Path(self) == source_resolved:
            return True
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", _exists_patched)

    result = FileManager().move(source, tmp_path / "moved.txt")

    assert result["success"] is False
    assert result["verified"] is False


def test_orchestrator_rejects_empty_string():
    orchestrator = AgentOrchestrator([_FakeAgent("Research Agent", "")])
    result = orchestrator.execute("research something")

    assert result["success"] is False
    assert "empty" in result["message"].lower()


def test_orchestrator_rejects_none():
    orchestrator = AgentOrchestrator([_FakeAgent("Research Agent", None)])
    result = orchestrator.execute("research something")

    assert result["success"] is False
    assert result["message"] == "Agent returned no result."


def test_orchestrator_rejects_empty_dict():
    orchestrator = AgentOrchestrator([_FakeAgent("Research Agent", {})])
    result = orchestrator.execute("research something")

    assert result["success"] is False
    assert "empty" in result["message"].lower()


def test_orchestrator_accepts_real_string_result():
    orchestrator = AgentOrchestrator(
        [_FakeAgent("Research Agent", "42")]
    )
    result = orchestrator.execute("research the answer to life")

    assert result["success"] is True
    assert result["response"] == "42"


def test_orchestrator_accepts_short_but_meaningful_result():
    orchestrator = AgentOrchestrator(
        [_FakeAgent("Research Agent", "ok")]
    )
    result = orchestrator.execute("research x")

    assert result["success"] is True
    assert result["response"] == "ok"