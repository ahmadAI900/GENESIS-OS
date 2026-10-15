"""Fail a test, by name, that writes into the product tree.

The problem
-----------
A whole-tree diff after a full run once turned up a zero-byte file
named `file` in `backend/`. Something in the suite wrote a RELATIVE
path, so wherever the process was sitting at the time became the
target. Nothing failed. The diff found it hours later.

That is the worst possible shape: a test that damages the tree it is
testing, reports green, and leaves the damage behind for the next
session. This is the same argument the capability tripwire makes, turned
on the filesystem.

Why it is cheap
---------------
The expensive designs are both rejected:

  * hash every product file before and after every test. With ~620
    files and ~3100 tests that is about four million reads, and it buys
    nothing over noticing the write at the moment it happens.
  * walk the tree per test. Same order of cost.

So this records at the call site instead. The wrappers do a frozenset
membership test and a prefix test, and do real work only when a path
actually lands inside the product tree. Cost is paid by tests that
write there, which is the thing being complained about.

Scope
-----
Outside the workspace root and the cache directories, which is what
"the product tree" means for a test: `.genesis_workspace` is where
filesystem tests are supposed to write, `__pycache__` and
`.pytest_cache` are build residue, and the system temp directory holds
pytest's own `tmp_path`.

    pytest -m "not live"                        # check ON
    pytest -m "not live" --tree-writes=report   # enumerate, never fail
    pytest -m "not live" --tree-writes=off      # off
"""

from __future__ import annotations

import builtins
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND / "tools") not in sys.path:
    sys.path.insert(0, str(BACKEND / "tools"))

import record_probe  # noqa: E402

MODE = {"value": "fail"}
STATS = {"tests": 0, "failures": 0, "overhead_seconds": 0.0}
# nodeid -> list of (api, path) recorded while that test ran.
WRITES: dict = {}

EVENT_KIND = "product_tree_write"

# ----------------------------------------------------------------------
# What counts as "the product tree", and what does not.
# ----------------------------------------------------------------------

# Directories where writing is expected and meaningless as a signal.
ALLOWED_DIR_NAMES = frozenset({
    "__pycache__", ".pytest_cache", ".git", "backups", ".venv",
    ".genesis_workspace", "node_modules", ".mypy_cache", ".ruff_cache",
})

# The gate's own evidence files. These are written by `record_probe` when
# the run is explicitly asked to record, and by `apply_tiering`. They are
# tool OUTPUT, not a test damaging the tree, so they are named exactly
# rather than being given a broad exemption.
ALLOWED_EXACT = frozenset({
    (BACKEND / "docs" / "fast_gate_evidence.json").resolve(),
    (BACKEND / "docs" / "tests_tiering.json").resolve(),
})

# Known product-tree writers, each with the reason it is tolerated.
#
# This is a CLOSED SET, the same shape as HARMLESS_EXECUTABLES in
# tiering_rules.py: anything absent is treated as a violation. An entry
# here is a claim that a specific path is written on purpose, and
# `tools/test_tooling_guards.py` asserts the list is declared, so it
# cannot be widened silently.
_AUDIT_NOTE = (
    "The approval audit log. The PRODUCT opens it in append mode "
    "inside the source tree -- `approval_channel._audit_path()` returns "
    "`Path(__file__).parent / 'approval_audit.jsonl'` and line 118 "
    "calls `path.parent.mkdir(parents=True, exist_ok=True)` -- so every "
    "test that dispatches an approval-guarded action writes both the "
    "file and a `makedirs` on the `genesis_os/` directory itself. This "
    "is a real product-tree write and a real finding: a source tree "
    "that changes as a side effect of running tests cannot be verified "
    "byte-for-byte, and it is why `genesis_os/approval_audit.jsonl` "
    "shows as MODIFIED against the Oct 9 backup. Relocating it to a "
    "configurable path is tracked for C3; until then it is named here "
    "so the rest of the check can still hold."
)

ALLOWED_WRITES = {
    (BACKEND / "genesis_os" / "approval_audit.jsonl").resolve():
        _AUDIT_NOTE,
    (BACKEND / "genesis_os").resolve():
        _AUDIT_NOTE,
}


def _allowed(path: str) -> bool:
    if Path(path) in ALLOWED_EXACT:
        return True
    for allowed in ALLOWED_WRITES:
        if path == str(allowed):
            return True
    parts = Path(path).parts
    if any(part in ALLOWED_DIR_NAMES for part in parts):
        return True
    temp = os.path.normcase(os.environ.get("TEMP")
                            or os.environ.get("TMP") or "")
    if temp and os.path.normcase(path).startswith(temp):
        return True
    return False


def _in_product_tree(path: str) -> bool:
    root = os.path.normcase(str(BACKEND))
    norm = os.path.normcase(path)
    return norm == root or norm.startswith(root + os.sep)


def _note_write(target, api: str) -> None:
    """Record a write that lands in the product tree."""
    if MODE["value"] == "off":
        return
    try:
        path = os.path.abspath(os.fspath(target))
    except TypeError:
        return
    if not _in_product_tree(path):
        return
    if _allowed(path):
        return
    record_probe._record(EVENT_KIND, {"api": api, "path": path,
                                     "source": "tree"})


# ----------------------------------------------------------------------
# The write-call wrappers
# ----------------------------------------------------------------------
# Only installed once. Each is a thin shim: decide, record, delegate.

_real_open = builtins.open
_real_os_open = os.open
_installed = {"value": False}


def _wrap_writes():
    if _installed["value"]:
        return
    _installed["value"] = True

    def tree_open(file, mode="r", *args, **kwargs):
        if (record_probe._ACTIVE and record_probe._any_frame_active()
                and isinstance(mode, str)
                and any(ch in mode for ch in "wax+")):
            _note_write(file, f"open({mode})")
        return _real_open(file, mode, *args, **kwargs)

    def tree_os_open(path, flags, *args, **kwargs):
        # O_WRONLY 1, O_RDWR 2, O_CREAT 64, O_APPEND 1024, O_TRUNC 512
        if (record_probe._ACTIVE and record_probe._any_frame_active()
                and flags & (1 | 2 | 64 | 512 | 1024)):
            _note_write(path, "os.open")
        return _real_os_open(path, flags, *args, **kwargs)

    def _wrap_os(name, api):
        real = getattr(os, name)

        def wrapper(path, *args, **kwargs):
            if record_probe._ACTIVE and record_probe._any_frame_active():
                _note_write(path, api)
            return real(path, *args, **kwargs)
        wrapper.__name__ = name
        setattr(os, name, wrapper)

    def _wrap_shutil(name, api):
        real = getattr(shutil, name)

        def wrapper(src, *args, **kwargs):
            if record_probe._ACTIVE and record_probe._any_frame_active():
                _note_write(src, api)
            return real(src, *args, **kwargs)
        wrapper.__name__ = name
        setattr(shutil, name, wrapper)

    builtins.open = tree_open
    os.open = tree_os_open
    for name, api in (("mkdir", "os.mkdir"), ("makedirs", "os.makedirs"),
                      ("remove", "os.remove"), ("unlink", "os.unlink"),
                      ("rmdir", "os.rmdir"), ("rename", "os.rename"),
                      ("replace", "os.replace")):
        _wrap_os(name, api)
    for name, api in (("copyfile", "shutil.copyfile"),
                      ("copy2", "shutil.copy2"),
                      ("copytree", "shutil.copytree"),
                      ("rmtree", "shutil.rmtree"),
                      ("move", "shutil.move")):
        _wrap_shutil(name, api)


# ----------------------------------------------------------------------
# Hooks
# ----------------------------------------------------------------------

def pytest_addoption(parser):
    group = parser.getgroup("genesis-tree-writes")
    group.addoption("--tree-writes", action="store", default="fail",
                    choices=("fail", "report", "off"),
                    help="product-tree write policy for the fast gate")


def pytest_configure(config):
    MODE["value"] = config.getoption("--tree-writes", default="fail")
    if MODE["value"] != "off":
        _wrap_writes()
    if MODE["value"] == "report":
        sys.stdout.write(
            "\n[tree-writes] REPORT mode: product-tree writes will be "
            "enumerated, not failed.\n")


def _unique_paths(events):
    seen, out = set(), []
    for event in events:
        if event.get("kind") != EVENT_KIND:
            continue
        key = event.get("path")
        if key in seen:
            continue
        seen.add(key)
        out.append(event)
    return out


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    t0 = time.perf_counter()
    if MODE["value"] != "off" and _watch(item):
        nodeid = item.nodeid
        frame = record_probe.new_capture(nodeid)
        record_probe._CAPTURE_STACK.append(frame)
        WRITES[nodeid] = frame
        STATS["overhead_seconds"] += time.perf_counter() - t0
    yield


def _watch(item) -> bool:
    return item.get_closest_marker("live") is None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        frame = WRITES.pop(item.nodeid, None)
        if frame is None:
            return
        if frame in record_probe._CAPTURE_STACK:
            record_probe._CAPTURE_STACK.remove(frame)
        STATS["overhead_seconds"] += time.perf_counter() - t0
        STATS["tests"] += 1
        offenders = _unique_paths(frame["events"])
        if not offenders:
            return
        STATS["failures"] += 1
        relative = []
        for event in offenders:
            try:
                relative.append(str(Path(event["path"]).relative_to(BACKEND)))
            except ValueError:
                relative.append(event["path"])
        sys.stdout.write(
            f"\n[tree-writes] {item.nodeid} wrote into the product tree: "
            f"{relative}\n")
        if MODE["value"] == "fail":
            _PENDING[item.nodeid] = _message(item, offenders)
    return


def _message(item, offenders) -> str:
    lines = [f"product-tree write: {item.nodeid} created or modified a "
             f"file in the product tree", "", "written during this test:"]
    for event in offenders:
        lines.append(f"  - {event.get('api')}  {event.get('path')}")
    lines += [
        "",
        "Tests must not write into the product tree. Writing a RELATIVE "
        "path is how the zero-byte file `backend/file` appeared: the "
        "target silently became whatever directory the process happened "
        "to be sitting in.",
        "",
        "Do one of these:",
        "",
        "  1. Write under the `workspace_root` fixture or under "
        "`tmp_path`. Both are outside the product tree and both are "
        "cleaned up.",
        "",
        "  2. If the write is a real product behaviour, name it in "
        "ALLOWED_WRITES in tools/tree_write_plugin.py WITH the reason it "
        "is allowed, so the exemption is auditable rather than implied.",
    ]
    return "\n".join(lines)


# nodeid -> message, for a write that must be reported as a FAILED.
_PENDING: dict = {}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Report a product-tree write as an ordinary FAILED, not an ERROR.

    Raising inside a finalizer is reported by pytest as an error, and
    "3120 passed, 1 error" is a shape in which a test that quietly
    damaged the tree is easy to miss. The teardown report is rewritten
    instead, so the finding is attributed to the test that caused it, by
    name, in the ordinary FAILED line of the summary.

    A teardown that ALREADY failed keeps its own error; the write is
    then appended to it rather than replacing it, because replacing a
    real error with this message would hide the real error.
    """
    outcome = yield
    report = outcome.get_result()
    if report.when != "teardown":
        return
    message = _PENDING.pop(item.nodeid, None)
    if not message:
        return
    if report.outcome == "passed":
        report.outcome = "failed"
        report.longrepr = message
        report._genesis_tree_write = True
    else:
        report.longrepr = f"{report.longrepr}\n\n{message}"


@pytest.hookimpl(tryfirst=True)
def pytest_report_teststatus(report):
    """Keep a product-tree write counted as a failure, not an error.

    `_pytest.runner.pytest_report_teststatus` has a `tryfirst` impl that
    maps any FAILED setup or teardown report to ("error", "E", "ERROR"),
    so a write found during fixture finalization would be displayed as
    an error no matter what `report.outcome` says. Returning None
    defers to the next implementation for everything else.
    """
    if getattr(report, "_genesis_tree_write", False):
        return "failed", "F", "FAILED"
    return None


def pytest_terminal_summary(terminalreporter, exitstatus=None, config=None):
    if not STATS["tests"] or MODE["value"] == "off":
        return
    watched = STATS["tests"]
    overhead = STATS["overhead_seconds"]
    per_test = (overhead / watched * 1000) if watched else 0.0
    terminalreporter.write_sep("-", "product-tree writes")
    if MODE["value"] == "report":
        terminalreporter.write_line(
            f"REPORT mode: {STATS['failures']} test(s) wrote into the "
            f"product tree; none were failed.")
    else:
        terminalreporter.write_line(
            f"{STATS['failures']} of {watched} fast-gate test(s) wrote "
            f"into the product tree and were failed.")
    terminalreporter.write_line(
        f"check overhead: {overhead:.2f}s total, {per_test:.3f} ms per "
        f"test (record-at-the-call-site, not a tree walk).")
