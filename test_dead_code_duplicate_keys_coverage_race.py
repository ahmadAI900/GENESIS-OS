"""Item 24C (C31): dead code, a silently-winning duplicate key, and
the coverage-gap check-then-act race.

Three defects, one batch:

1. safe_file_manager.py defined ``_confirmation`` (a static helper
   returning a confirmation-required dict) that NO call site ever
   referenced -- dead code that reads like a live safety path.

2. document_intelligence.py assigned ``source_stat = os.stat(abs_path)``
   in transform() and never read it -- a dead local that also performed
   a pointless syscall (and could raise on a file that vanished between
   validation and hashing, for no benefit).

3. app_manager.py's URI dict declared ``"xbox"`` TWICE (once inside the
   labeled XBOX block, again at the end of the trailing underscore-alias
   block). Python silently keeps the LAST duplicate, so an edit to the
   first entry would look applied and do nothing. Both values were
   "xbox:", so resolution behaviour is unchanged by keeping exactly one.

4. blast_radius.record_coverage_gap did ``for existing in
   _coverage_gaps: ... return`` followed by ``_coverage_gaps.append`` --
   a textbook check-then-act with no lock. Two threads recording the
   same unregistered operation both observe "not present" and both
   append, duplicating the coverage-gap log (the log whose whole point
   is telling you what the system could not classify).

The race test makes the window deterministic instead of hoping for a
collision: a list subclass that blocks every dedupe iteration at
StopIteration until all worker threads have finished their CHECK. The
append happens after the loop, so without a lock every thread checks
against a list no one has appended to yet and all N append.

All five tests fail before this item.
"""
from __future__ import annotations

import ast
import pathlib
import threading

BACKEND = pathlib.Path(__file__).resolve().parent
SAFE_FILE = BACKEND / "genesis_os" / "safe_file_manager.py"
DOC_INTEL = BACKEND / "genesis_os" / "document_intelligence.py"
APP_MANAGER = BACKEND / "genesis_os" / "applications" / "app_manager.py"


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8-sig"))


# --------------------------------------------------------------------------
# Dead code.
# --------------------------------------------------------------------------


def test_confirmation_helper_is_really_gone():
    tree = _parse(SAFE_FILE)
    defs = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_confirmation"
    ]
    refs = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "_confirmation"
    ]
    assert not defs, (
        f"_confirmation is defined at line(s) {defs} although nothing "
        "calls it -- dead code that reads like a live safety path"
    )
    assert not refs, f"_confirmation still referenced at {refs}"
    # The sibling that IS part of the file's contract stays.
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "_failure"
        for node in ast.walk(tree)
    ), "_failure must remain"


def test_dead_source_stat_local_is_gone():
    tree = _parse(DOC_INTEL)
    refs = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "source_stat"
    ]
    assert not refs, (
        f"source_stat is assigned/read at {refs} but never used -- a "
        "dead local whose os.stat could even raise for no benefit"
    )
    # What transform() actually consumes must still be computed.
    src = DOC_INTEL.read_text(encoding="utf-8-sig")
    assert "source_digest" in src
    assert "source_hash" in src


# --------------------------------------------------------------------------
# The duplicate dict key.
# --------------------------------------------------------------------------


def test_app_manager_has_no_duplicate_string_dict_keys():
    tree = _parse(APP_MANAGER)
    duplicates = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            seen = {}
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(
                    key.value, str
                ):
                    if key.value in seen:
                        duplicates.append(
                            (key.lineno, key.value, seen[key.value])
                        )
                    else:
                        seen[key.value] = key.lineno
    assert not duplicates, (
        "duplicate dict keys -- Python silently keeps the LAST one, so "
        f"an edit to the earlier line looks applied and does nothing: "
        f"{duplicates}"
    )


def test_xbox_entry_survives_exactly_once_with_its_value():
    tree = _parse(APP_MANAGER)
    entries = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "xbox"
                ):
                    entries.append(
                        (key.lineno, getattr(value, "value", None))
                    )
    assert len(entries) == 1, (
        f"expected exactly one xbox entry after de-duplication, "
        f"found {entries}"
    )
    assert entries[0][1] == "xbox:", entries


# --------------------------------------------------------------------------
# The coverage-gap race.
# --------------------------------------------------------------------------


class _DedupeSyncList(list):
    """List that makes record_coverage_gap's check-then-act window
    deterministic under threads.

    The product's dedupe loop is ``for existing in _coverage_gaps:`` --
    a Python-level iteration, which this subclass intercepts. Every
    thread that finishes its CHECK blocks at StopIteration until all
    N threads have finished theirs. The append happens AFTER the loop,
    so no thread can append before every thread has checked: without a
    lock, all N observe "not present" and all N append. With a lock,
    threads reach StopIteration one at a time -- the first waits on the
    barrier (the others are queued behind the lock), times out, appends,
    and the rest find the entry and return before their iteration ends.
    """

    def __init__(self, barrier):
        super().__init__()
        self._barrier = barrier

    def __iter__(self):
        base = list.__iter__(self)
        barrier = self._barrier
        state = {"waited": False}

        class _Guarded:
            def __next__(self):
                try:
                    return next(base)
                except StopIteration:
                    if not state["waited"]:
                        state["waited"] = True
                        try:
                            barrier.wait(timeout=1.0)
                        except threading.BrokenBarrierError:
                            pass
                    raise

        return _Guarded()


def test_concurrent_same_operation_records_are_deduplicated(monkeypatch):
    from genesis_os import blast_radius as BR

    thread_count = 8
    barrier = threading.Barrier(thread_count)
    gaps = _DedupeSyncList(barrier)
    monkeypatch.setattr(BR, "_coverage_gaps", gaps)

    errors = []

    def worker():
        try:
            BR.record_coverage_gap(
                {"operation": "unregistered.concurrent.op"}
            )
        except Exception as exc:  # captured, never expected
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads), (
        "a record_coverage_gap worker hung"
    )
    assert not errors, errors

    entries = [
        gap
        for gap in BR.coverage_gaps()
        if gap["operation"] == "unregistered.concurrent.op"
    ]
    assert len(entries) == 1, (
        f"check-then-act race logged the same operation "
        f"{len(entries)} times"
    )
