"""Item 14A (C8): process.list `executed` must reflect reality.

`ProcessManager.list` runs `tasklist` and parses its CSV output. Before
this item the success path reported `executed: False` and two failure
paths reported `executed: True` -- exactly inverted, and inverted on
both sides at once.

`executed` is how a caller distinguishes "we actually did the thing"
from "we declined to". A caller that saw `executed: False` next to
`success: True` had no way to reconcile the pair, and a caller that saw
`executed: True` next to `success: False` could not tell a listing that
was attempted-and-failed from one that was never attempted.

The contract asserted here:

    success=True   -> executed=True   (tasklist ran, output became `rows`)
    success=False  -> executed=False  (no inventory was produced)

NUANCE, deliberately pinned by a test so it cannot drift silently: on
the returncode-nonzero path the `tasklist` subprocess *did* spawn. Under
a narrower reading of `executed` ("the command was launched") that path
would be True. It is False because `executed` means the LISTING was
carried out, and a non-zero tasklist produced no inventory.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from genesis_os.processes.process_manager import ProcessManager


TASKLIST_CSV = (
    '"System Idle Process","0","Services","0","24 K"\r\n'
    '"explorer.exe","4212","Console","1","98,204 K"\r\n'
    '"notepad.exe","7777","Console","1","12,000 K"\r\n'
)


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def nt_platform(monkeypatch):
    """Force the Windows branch regardless of the host actually running.

    Replaces the module's `os` reference rather than mutating the real
    `os` module -- `os.name` is the module's only use of `os`, and
    monkeypatching the genuine attribute corrupts unrelated teardown.
    """
    monkeypatch.setattr(
        "genesis_os.processes.process_manager.os",
        _FakeOS("nt"),
    )


class _FakeOS:
    """Minimal stand-in: process_manager only ever asks os.name."""

    def __init__(self, name):
        self.name = name


def _patch_run(monkeypatch, completed):
    monkeypatch.setattr(
        "genesis_os.processes.process_manager.subprocess.run",
        lambda *a, **k: completed,
    )


# --------------------------------------------------------------------------
# The success path: tasklist ran and produced rows.  It was executed.
# --------------------------------------------------------------------------

def test_a_successful_list_reports_executed_true(nt_platform, monkeypatch):
    _patch_run(monkeypatch, _Completed(0, TASKLIST_CSV))

    result = ProcessManager().list()

    assert result["success"] is True, result
    assert result["executed"] is True, (
        "a list that ran tasklist and parsed its output reports "
        f"executed={result['executed']!r}; it definitely was executed"
    )


def test_a_successful_list_still_verifies_and_returns_rows(nt_platform, monkeypatch):
    _patch_run(monkeypatch, _Completed(0, TASKLIST_CSV))

    result = ProcessManager().list()

    assert result["executed"] is True
    assert result["verified"] is True
    assert result["count"] == 3
    assert {p["name"] for p in result["processes"]} == {
        "System Idle Process",
        "explorer.exe",
        "notepad.exe",
    }
    assert result["operation"] == "process.list"


def test_success_and_executed_can_no_longer_disagree(nt_platform, monkeypatch):
    """The pair a consumer reads must never contradict itself."""
    _patch_run(monkeypatch, _Completed(0, TASKLIST_CSV))

    result = ProcessManager().list()

    assert result["success"] == result["executed"] is True


# --------------------------------------------------------------------------
# Failure paths: no inventory was produced, so nothing was executed.
# --------------------------------------------------------------------------

def test_nonzero_returncode_reports_executed_false(nt_platform, monkeypatch):
    _patch_run(monkeypatch, _Completed(1, "", "ERROR: Invalid argument"))

    result = ProcessManager().list()

    assert result["success"] is False, result
    assert result["executed"] is False, (
        "tasklist exited non-zero and produced no inventory; executed="
        f"{result['executed']!r} contradicts success={result['success']!r}"
    )
    assert result["verified"] is False


def test_unparsable_output_reports_executed_false(nt_platform, monkeypatch):
    # A non-str stdout makes StringIO raise, exercising the parse
    # handler. (stdout=None would NOT -- StringIO(None) is legal and
    # simply yields zero rows, taking the success path instead.)
    _patch_run(monkeypatch, _Completed(0, 12345))

    result = ProcessManager().list()

    assert result["success"] is False, result
    assert result["executed"] is False, (
        "the listing was never assembled, so it was not executed; "
        f"got executed={result['executed']!r}"
    )
    assert result["verified"] is False
    assert "Unable to parse process inventory" in result["error"]


def test_subprocess_raising_reports_executed_false(nt_platform, monkeypatch):
    def _boom(*a, **k):
        raise OSError("tasklist is not installed")

    monkeypatch.setattr(
        "genesis_os.processes.process_manager.subprocess.run", _boom
    )

    result = ProcessManager().list()

    assert result["success"] is False, result
    assert result["executed"] is False
    assert result["verified"] is False


def test_non_windows_reports_executed_false(monkeypatch):
    monkeypatch.setattr(
        "genesis_os.processes.process_manager.os", _FakeOS("posix")
    )

    def _never(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("tasklist must not run on a non-Windows host")

    monkeypatch.setattr(
        "genesis_os.processes.process_manager.subprocess.run", _never
    )

    result = ProcessManager().list()

    assert result["success"] is False, result
    assert result["executed"] is False
    assert result["verified"] is False


# --------------------------------------------------------------------------
# Structural guard: the inversion cannot come back.
# --------------------------------------------------------------------------

def test_no_return_dict_pairs_executed_true_with_success_false(monkeypatch):
    """AST sweep: a failure dict must never claim it executed.

    Guards both failure paths at once, so fixing one and forgetting the
    other fails here instead of hiding until a consumer notices.
    """
    import ast
    import pathlib

    path = pathlib.Path(
        sys.modules[ProcessManager.__module__].__file__
    )
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    offenders = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        literal: dict[str, object] = {}
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                try:
                    literal[key.value] = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    literal[key.value] = "<dynamic>"

        if literal.get("success") is False and literal.get("executed") is True:
            offenders.append(node.lineno)

    assert not offenders, (
        "result dicts at "
        f"{offenders} pair success=False with executed=True, which is "
        "the exact inversion this item removed"
    )