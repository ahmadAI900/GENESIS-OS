"""Item 23B (C27): window dispatch exceptions reported executed=True.

`WindowManager._dispatch` has three return paths. The unavailable
bridge and the success path agree with reality. The exception path --
the shell could not be created, or the Shell method itself raised --
returned:

    {"success": False, ..., "executed": True, "verified": False}

so a COM failure was reported as "we did the thing". Under the Item
14A reading of `executed` (the operation was carried out), an
exception means the minimize/restore/show-desktop never happened.

The contract asserted here:

    success=True   -> executed=True   (the Shell method returned)
    success=False  -> executed=False  (unavailable / exception)

NUANCE, deliberately pinned: when the Shell method raises, the COM
call was *attempted* -- but an attempted-and-failed operation is not a
completed one, and `success: False` beside `executed: True` gave a
consumer no way to tell the two apart.
"""
from __future__ import annotations

import pathlib
import sys

from genesis_os.window_manager import WindowManager


class _CompletedShell:
    """A Shell whose method returns normally (no real COM dispatch)."""

    def MinimizeAll(self):
        pass

    def UndoMinimizeALL(self):
        pass

    def ToggleDesktop(self):
        pass


class _RaisingShell:
    """A Shell whose method itself raises -- _shell() worked, the call did not."""

    def MinimizeAll(self):
        raise RuntimeError("the Shell application object rejected the call")

    def UndoMinimizeALL(self):
        raise RuntimeError("the Shell application object rejected the call")

    def ToggleDesktop(self):
        raise RuntimeError("the Shell application object rejected the call")


def _manager(monkeypatch, shell_factory=None):
    """A manager forced onto the dispatch path regardless of host pywin32.

    `available` is set explicitly: the constructor's probe would leave
    it False on a host without pywin32, skipping the code under test.
    `_shell` is replaced so no real COM dispatch ever happens (the
    success path must not actually minimize the machine's windows).
    """
    manager = WindowManager()
    manager.available = True
    if shell_factory is None:
        monkeypatch.setattr(manager, "_shell", lambda: _CompletedShell())
    else:
        monkeypatch.setattr(manager, "_shell", shell_factory)
    return manager


# --------------------------------------------------------------------------
# The defect: both exception sites claimed executed=True.
# --------------------------------------------------------------------------

def test_a_shell_creation_exception_reports_not_executed(monkeypatch):
    def _boom():
        raise OSError("win32com bridge died")

    manager = _manager(monkeypatch, _boom)

    result = manager.minimize_all()

    assert result["success"] is False, result
    assert result["executed"] is False, (
        "the Shell object could never be created, so MinimizeAll "
        f"never ran; executed={result['executed']!r} claims otherwise"
    )
    assert result["verified"] is False
    assert "win32com bridge died" in result["error"]


def test_a_method_exception_reports_not_executed(monkeypatch):
    manager = _manager(monkeypatch, lambda: _RaisingShell())

    result = manager.minimize_all()

    assert result["success"] is False, result
    assert result["executed"] is False, (
        "the Shell method raised, so the operation was never carried "
        f"out; executed={result['executed']!r} contradicts "
        f"success={result['success']!r}"
    )
    assert result["verified"] is False
    assert "rejected the call" in result["error"]


def test_a_failure_result_never_pairs_success_false_with_executed_true(monkeypatch):
    """AST sweep: guards BOTH exception sites (and any added later)."""
    import ast

    path = pathlib.Path(
        sys.modules[WindowManager.__module__].__file__
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


# --------------------------------------------------------------------------
# Guards: the two honest paths must not move.
# --------------------------------------------------------------------------

def test_a_successful_dispatch_still_reports_executed_true(monkeypatch):
    dispatched = []

    class FakeShell:
        def MinimizeAll(self):
            dispatched.append("MinimizeAll")

    manager = WindowManager()
    manager.available = True
    monkeypatch.setattr(manager, "_shell", lambda: FakeShell())

    result = manager.minimize_all()

    assert result["success"] == "dispatched", result
    assert result["executed"] is True, (
        "the Shell method returned normally; executed=False would "
        "deny a dispatch that really happened"
    )
    assert result["verified"] is False, (
        "desktop state is not independently observed, so verified "
        "stays False (success is not verification)"
    )
    assert dispatched == ["MinimizeAll"]


def test_an_unavailable_bridge_reports_not_executed(monkeypatch):
    manager = WindowManager()
    manager.available = False

    def _never():  # pragma: no cover - must not be reached
        raise AssertionError("the Shell must not be created when unavailable")

    monkeypatch.setattr(manager, "_shell", _never)

    result = manager.restore_all()

    assert result["success"] is False, result
    assert result["executed"] is False, result
    assert result["verified"] is False
