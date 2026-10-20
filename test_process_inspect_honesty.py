"""Item 22C (C24): inspect() was dishonest twice.

Two defects in genesis_os/processes/process_manager.py, both
REPRODUCED against the committed original with tasklist stubbed to
a fixed CSV (the same stubbing pattern test_process_executed_flag.py
established for list()):

1. EXACT-NAME FILTERING (list(), the tasklist CSV filter): the row
   filter compared image.casefold() != wanted, an exact match. Real
   tasklist output carries the ".exe" suffix ("chrome.exe"), so
   inspect("chrome") / list("chrome") matched NOTHING and reported
   running=False for a process that was plainly running. Windows
   treats name == name.exe; the filter now compares executable
   stems, case-insensitively, in both directions.

2. executed=False ON THE SUCCESS PATH (inspect(), line 143): a
   successful inspection -- tasklist ran, output was parsed, an
   answer was produced -- returned executed=False, the exact
   inversion list()'s success path already corrected under Item
   14A (C8). "not running" is still an executed inspection: the
   listing happened, the answer is just negative. inspect now
   reports executed=True whenever its underlying list() succeeded,
   and still propagates executed=False when the listing failed.

HONEST LIMIT pinned by test: stem matching is intentionally narrow
-- "chrome" matches "chrome.exe"/"Chrome.EXE" but NOT
"chrome_proxy.exe" (different stem), and non-.exe names such as
"System Idle Process" still match by full name.
"""
from __future__ import annotations

import ast
import pathlib
import sys

import pytest

from genesis_os.processes.process_manager import ProcessManager

TASKLIST_CSV = (
    '"System Idle Process","0","Services","0","24 K"\r\n'
    '"chrome.exe","1234","Console","1","500,000 K"\r\n'
    '"chrome_proxy.exe","1235","Console","1","50,000 K"\r\n'
    '"notepad.exe","7777","Console","1","12,000 K"\r\n'
)

NO_NOTEPAD_CSV = (
    '"System Idle Process","0","Services","0","24 K"\r\n'
    '"chrome.exe","1234","Console","1","500,000 K"\r\n'
)


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeOS:
    def __init__(self, name):
        self.name = name


@pytest.fixture
def nt_platform(monkeypatch):
    monkeypatch.setattr(
        "genesis_os.processes.process_manager.os",
        _FakeOS("nt"),
    )


def _patch_run(monkeypatch, completed):
    monkeypatch.setattr(
        "genesis_os.processes.process_manager.subprocess.run",
        lambda *a, **k: completed,
    )


# --------------------------------------------------------------------------
# Defect 1: inspect("chrome") must find chrome.exe
# --------------------------------------------------------------------------

def test_inspect_finds_a_running_process_by_bare_name(
    nt_platform, monkeypatch,
):
    _patch_run(monkeypatch, _Completed(0, TASKLIST_CSV))

    result = ProcessManager().inspect("chrome")

    assert result["success"] is True, result
    assert result["running"] is True, (
        "inspect('chrome') reported not-running while chrome.exe "
        "is in the tasklist output: the filter demanded an exact "
        "name match, and tasklist carries the '.exe' suffix. "
        "Windows treats name == name.exe"
    )
    assert result["pids"] == [1234]


def test_inspect_still_finds_it_by_full_exe_name(
    nt_platform, monkeypatch,
):
    _patch_run(monkeypatch, _Completed(0, TASKLIST_CSV))

    result = ProcessManager().inspect("chrome.exe")

    assert result["success"] is True, result
    assert result["running"] is True
    assert result["pids"] == [1234]


def test_list_matches_a_bare_name_case_insensitively(
    nt_platform, monkeypatch,
):
    _patch_run(monkeypatch, _Completed(0, TASKLIST_CSV))

    result = ProcessManager().list("CHROME")

    assert result["success"] is True, result
    assert result["count"] == 1, (
        f"list('CHROME') returned {result['count']} rows; the "
        "case-insensitive stem match must find chrome.exe"
    )
    assert result["processes"][0]["name"] == "chrome.exe"


# --------------------------------------------------------------------------
# Defect 2: a successful inspect must report executed=True
# --------------------------------------------------------------------------

def test_a_successful_inspect_reports_executed_true(
    nt_platform, monkeypatch,
):
    _patch_run(monkeypatch, _Completed(0, TASKLIST_CSV))

    result = ProcessManager().inspect("chrome.exe")

    assert result["success"] is True, result
    assert result["executed"] is True, (
        "a successful inspection (tasklist ran, output parsed, "
        "an answer produced) reports executed=False: the exact "
        "inversion list()'s success path already corrected under "
        f"Item 14A; got {result['executed']!r}"
    )
    assert result["verified"] is True


def test_a_successful_inspect_of_a_not_running_process_also_reports_executed_true(
    nt_platform, monkeypatch,
):
    """'Not running' is an executed inspection with a negative answer."""
    _patch_run(monkeypatch, _Completed(0, NO_NOTEPAD_CSV))

    result = ProcessManager().inspect("notepad.exe")

    assert result["success"] is True, result
    assert result["running"] is False
    assert result["executed"] is True, (
        "the listing ran and correctly answered 'not running'; "
        "executed=False would claim the inspection never happened"
    )


# --------------------------------------------------------------------------
# Honest limits and guards
# --------------------------------------------------------------------------

def test_a_different_stem_does_not_match(nt_platform, monkeypatch):
    """'chrome' must not pull in 'chrome_proxy.exe'."""
    _patch_run(monkeypatch, _Completed(0, TASKLIST_CSV))

    result = ProcessManager().inspect("chrome")

    assert result["success"] is True, result
    assert result["pids"] == [1234], (
        "stem matching overreached: a bare 'chrome' must match "
        "only chrome.exe, not chrome_proxy.exe"
    )


def test_non_exe_names_still_match_by_full_name(
    nt_platform, monkeypatch,
):
    _patch_run(monkeypatch, _Completed(0, TASKLIST_CSV))

    result = ProcessManager().inspect("system idle process")

    assert result["success"] is True, result
    assert result["running"] is True
    assert result["pids"] == [0]


def test_a_failed_inspect_still_reports_executed_false(monkeypatch):
    monkeypatch.setattr(
        "genesis_os.processes.process_manager.os", _FakeOS("posix")
    )

    def _never(*a, **k):  # pragma: no cover
        raise AssertionError("tasklist must not run off Windows")

    monkeypatch.setattr(
        "genesis_os.processes.process_manager.subprocess.run", _never
    )

    result = ProcessManager().inspect("chrome")

    assert result["success"] is False, result
    assert result["executed"] is False


# --------------------------------------------------------------------------
# Structural guard: the success dict in inspect() cannot re-invert
# --------------------------------------------------------------------------

def test_inspect_success_dict_never_claims_it_did_not_execute():
    path = pathlib.Path(
        sys.modules[ProcessManager.__module__].__file__
    )
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    inspect_fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "inspect"
    )

    offenders = []
    for node in ast.walk(inspect_fn):
        if not isinstance(node, ast.Dict):
            continue
        literal: dict[str, object] = {}
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                try:
                    literal[key.value] = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    literal[key.value] = "<dynamic>"
        if (
            literal.get("success") is True
            and literal.get("executed") is False
        ):
            offenders.append(node.lineno)

    assert not offenders, (
        f"inspect() dicts at {offenders} pair success=True with "
        "executed=False: a successful inspection was executed"
    )
