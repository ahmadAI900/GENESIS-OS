"""Item 16B (C16): close() certified closure it never checked.

`ApplicationManager.is_running()` returned a bare bool and turned every
exception into `return False`. A tasklist that could not be executed at
all therefore read as "not running", and `close()` branches on exactly
that value:

    if not self.is_running(executable):
        return {"success": True, "already_closed": True, "running": False,
                "verified": True,
                "verification_type": "process_table_inspection"}

Reproduced against the committed original, with tasklist raising
OSError: the application could be alive the entire time and Genesis
reported `verified: True` by an inspection that never ran. The
`verification_type` claims a process-table inspection, which is the
part that makes it a lie rather than a gap.

Three states now: running, not_running, unknown. UNKNOWN is never
certified.
"""
from __future__ import annotations

import io

import pytest

import genesis_os.applications.app_manager as app_mod
from genesis_os.applications.app_manager import ApplicationManager


NOTEPAD = "C:/Windows/System32/notepad.exe"


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _raises(*a, **k):
    raise OSError("tasklist is not available (WinError 2)")


def _exits_nonzero(*a, **k):
    return _Completed(1, "", "ERROR: The system cannot find the file.")


def _absent_cleanly(*a, **k):
    """Exit 0 and the image is not in the table: a real answer."""
    return _Completed(
        0, "INFO: No tasks are running which match the specified criteria."
    )


def _present(*a, **k):
    return _Completed(
        0,
        'notepad.exe                   4321 Console                    1    12,000 K',
    )


class _PosixOSView:
    """Presents os.name == "posix" to one module without touching real os.

    Same trap as the existing test_level3_9 suite: `app_mod.os` IS the
    global os module, so patching its `name` in place mutates it
    process-wide and corrupts unrelated teardown (pathlib reads
    os.name on every Path() call).
    """

    name = "posix"


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(app_mod.os, "name", "nt")
    m = ApplicationManager()
    monkeypatch.setattr(m, "resolve_application", lambda _t: NOTEPAD)
    return m


def _run(manager, monkeypatch, impl):
    monkeypatch.setattr(app_mod.subprocess, "run", impl)
    return manager


# --------------------------------------------------------------------------
# The defect: a failed query must not certify closure
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "label,impl",
    [
        ("tasklist raises", _raises),
        ("tasklist exits non-zero", _exits_nonzero),
    ],
)
def test_close_does_not_certify_closure_when_tasklist_fails(
    manager, monkeypatch, label, impl
):
    _run(manager, monkeypatch, impl)

    result = manager.close("notepad")

    assert result.get("verified") is not True, (
        f"{label}: close() certified closure it never checked: {result}"
    )
    assert result.get("success") is False, result
    assert result.get("process_state") == "unknown", result


def test_close_does_not_claim_already_closed_on_unknown(manager, monkeypatch):
    _run(manager, monkeypatch, _raises)

    result = manager.close("notepad")

    assert result.get("already_closed") is None, (
        "already_closed=False would be a claim; it must be None "
        f"(not determined): {result}"
    )
    assert not result.get("already_closed"), "already_closed must be falsy"


def test_close_does_not_claim_a_process_table_inspection_it_never_ran(
    manager, monkeypatch
):
    _run(manager, monkeypatch, _raises)

    result = manager.close("notepad")

    assert result.get("verification_type") != "process_table_inspection", (
        "claiming a tasklist inspection while tasklist failed is the "
        f"core of the defect: {result}"
    )
    assert result.get("verification_type") == "process_state_unknown"


def test_close_reports_the_reason(manager, monkeypatch):
    _run(manager, monkeypatch, _raises)

    result = manager.close("notepad")

    assert result.get("error"), "an unknown state was reported with no reason"
    assert "WinError" in result["error"], result["error"]


def test_the_message_says_the_app_may_still_be_open(manager, monkeypatch):
    _run(manager, monkeypatch, _raises)

    message = manager.close("notepad").get("message", "").lower()

    assert "may still be open" in message, (
        f"the user is not told the application might be untouched: {message!r}"
    )


# --------------------------------------------------------------------------
# The counterpart: a real answer is still honoured
# --------------------------------------------------------------------------

def test_close_still_certifies_a_confirmed_not_running(manager, monkeypatch):
    _run(manager, monkeypatch, _absent_cleanly)

    result = manager.close("notepad")

    assert result["success"] is True, result
    assert result["already_closed"] is True
    assert result["verified"] is True
    assert result["verification_type"] == "process_table_inspection"
    assert result["process_state"] == "not_running"


def test_close_attempts_a_real_close_when_running(manager, monkeypatch):
    """Unknown must not break the normal path.

    `close` kills the process with `taskkill` via subprocess.run, so the
    tasklist stub and the taskkill stub have to be told apart.
    """
    issued = []

    def _dispatch(args, **kwargs):
        if args and args[0] == "tasklist":
            return _present(*args, **kwargs)
        issued.append(args)
        return _Completed(0, "")

    monkeypatch.setattr(app_mod.subprocess, "run", _dispatch)
    monkeypatch.setattr(
        manager,
        "wait_until_stopped",
        lambda exe, attempts=10, delay_seconds=0.5: True,
    )

    result = manager.close("notepad")

    assert issued, "the close was never attempted"
    assert issued[0][0] == "taskkill", issued
    assert result.get("verified") is True, result


# --------------------------------------------------------------------------
# The tri-state itself
# --------------------------------------------------------------------------

def test_running_state_distinguishes_all_three(manager, monkeypatch):
    _run(manager, monkeypatch, _present)
    assert manager.running_state(NOTEPAD) == ApplicationManager.STATE_RUNNING

    _run(manager, monkeypatch, _absent_cleanly)
    assert manager.running_state(NOTEPAD) == ApplicationManager.STATE_NOT_RUNNING

    _run(manager, monkeypatch, _raises)
    assert manager.running_state(NOTEPAD) == ApplicationManager.STATE_UNKNOWN


def test_is_running_returns_none_for_unknown(manager, monkeypatch):
    _run(manager, monkeypatch, _raises)

    assert manager.is_running(NOTEPAD) is None, (
        "is_running must report UNKNOWN as None, not as False; False "
        "means the process table answered"
    )


def test_is_running_stays_truthy_only_when_observed(manager, monkeypatch):
    _run(manager, monkeypatch, _present)
    assert manager.is_running(NOTEPAD) is True

    _run(manager, monkeypatch, _absent_cleanly)
    assert manager.is_running(NOTEPAD) is False


def test_is_running_none_is_falsy_so_existing_callers_are_unaffected(manager, monkeypatch):
    """`if not m.is_running(x)` must behave as it always did."""
    _run(manager, monkeypatch, _raises)

    assert not manager.is_running(NOTEPAD)
    if manager.is_running(NOTEPAD):
        pytest.fail("an unknown state must not read as running")


def test_a_non_windows_host_is_unknown_not_not_running(manager, monkeypatch):
    monkeypatch.setattr(app_mod, "os", _PosixOSView())

    assert manager.running_state(NOTEPAD) == ApplicationManager.STATE_UNKNOWN, (
        "a platform with no process-table implementation cannot answer "
        "'not running'"
    )


def test_an_empty_executable_is_unknown(manager):
    assert manager.running_state("") == ApplicationManager.STATE_UNKNOWN


def test_the_last_query_error_is_recorded_for_unknown(manager, monkeypatch):
    _run(manager, monkeypatch, _raises)

    manager.running_state(NOTEPAD)

    assert manager._last_process_query_error, (
        "the reason for the unknown state was not recorded anywhere"
    )


# --------------------------------------------------------------------------
# open() must not leak None into `success`
# --------------------------------------------------------------------------

def test_open_never_reports_a_none_success(manager, monkeypatch):
    _run(manager, monkeypatch, _raises)
    monkeypatch.setattr(manager, "_launch", lambda *a, **k: None)

    result = manager.open("notepad")

    assert result["success"] is not None, (
        f"success=None is neither True nor False: {result}"
    )
    assert isinstance(result["success"], bool)
    assert result["success"] is False, result
    assert result["verified"] is False, result
    assert result.get("process_state") == "unknown", result


def test_open_verified_is_a_real_boolean(manager, monkeypatch):
    _run(manager, monkeypatch, _raises)
    monkeypatch.setattr(manager, "_launch", lambda *a, **k: None)

    result = manager.open("notepad")

    assert isinstance(result["verified"], bool), result["verified"]


# --------------------------------------------------------------------------
# Structural guards
# --------------------------------------------------------------------------

def test_close_checks_for_unknown_not_just_for_false():
    """`if not m.is_running(...)` is the exact shape that caused this.

    close() still calls is_running() -- several existing suites stub
    that method -- but it must compare against None, because None is
    the new third state and truthiness would fold it back into False.
    """
    import ast
    import inspect
    import pathlib

    source = inspect.getsource(ApplicationManager.close)
    assert "STATE_UNKNOWN" in source, (
        "close() has no branch for the unknown state"
    )

    tree = ast.parse(
        (pathlib.Path("genesis_os") / "applications" / "app_manager.py")
        .read_text(encoding="utf-8-sig")
    )
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "close"
    )

    # `observed is None` must appear: that is what stops truthiness
    # from folding unknown back into "not running".
    compares_to_none = any(
        isinstance(node, ast.Compare)
        and any(
            isinstance(c, ast.Constant) and c.value is None
            for c in node.comparators
        )
        for node in ast.walk(fn)
    )

    assert compares_to_none, (
        "close() never compares the process observation to None; a "
        "two-state truthiness check would treat UNKNOWN as not-running"
    )


def test_close_uses_the_tri_state_underneath():
    import inspect

    source = inspect.getsource(ApplicationManager.is_running)

    assert "running_state" in source, (
        "is_running must delegate to running_state so the error is "
        "never swallowed into a bare False"
    )


def test_running_state_never_returns_false_for_a_failed_query(manager, monkeypatch):
    _run(manager, monkeypatch, _raises)

    assert manager.running_state(NOTEPAD) != ApplicationManager.STATE_NOT_RUNNING


def test_a_non_zero_exit_is_not_evidence_of_absence(manager, monkeypatch):
    """The subtle half: tasklist ran, but failed."""
    _run(manager, monkeypatch, _exits_nonzero)

    assert manager.running_state(NOTEPAD) == ApplicationManager.STATE_UNKNOWN, (
        "a failed query was treated as a successful 'not running'"
    )


def test_a_clean_query_with_no_match_is_the_only_not_running(manager, monkeypatch):
    _run(manager, monkeypatch, _absent_cleanly)

    assert manager.running_state(NOTEPAD) == ApplicationManager.STATE_NOT_RUNNING


def test_unknown_is_never_verified_true_anywhere_in_close(manager, monkeypatch):
    """Belt and braces across the whole method."""
    _run(manager, monkeypatch, _raises)

    result = manager.close("notepad")

    assert result.get("verified") is False, result
    assert "already empty" not in str(result.get("message", "")).lower()
    assert io is not None  # keep the import meaningful