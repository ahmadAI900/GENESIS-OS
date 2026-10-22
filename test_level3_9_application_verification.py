"""
Genesis OS — Level 3.9
Application State Verification.

Real-world validation exposed two honesty bugs that must stay
fixed permanently:

    1. application.inspect determined the running state but
       never emitted verification evidence, so a truthful
       "chrome is running" answer was downgraded to
       verification_failed by the executor.

    2. application.close treated the FIRST process-table poll
       after taskkill as final evidence. A dying browser
       process tree briefly still lists its processes, so
       close was reported as unverified even when it had
       succeeded.

Close must WAIT for absence; inspect must carry evidence.
"""

import subprocess
from pathlib import Path, PosixPath

import pytest

from genesis_os.applications.app_manager import ApplicationManager


@pytest.fixture(scope="module")
def manager():
    return ApplicationManager()


def _tasklist_output(*images):
    header = "\nImage Name                     PID Session Name\n========== ==================== ==========\n"
    rows = "".join(f"{image}   {1234 + i} Console\n" for i, image in enumerate(images))
    return header + rows


# =========================================================
# INSPECT CARRIES VERIFICATION EVIDENCE
# =========================================================


def test_inspect_running_app_reports_verified_state(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda exe, attempts=1: True)

    result = manager.inspect("chrome")

    assert result["success"] is True
    assert result["running"] is True
    assert result["verified"] is True


def test_inspect_stopped_app_reports_verified_state(manager, monkeypatch):
    monkeypatch.setattr(manager, "is_running", lambda exe, attempts=1: False)

    result = manager.inspect("chrome")

    assert result["success"] is True
    assert result["running"] is False
    assert result["verified"] is True


# =========================================================
# CLOSE WAITS FOR REAL PROCESS-TREE ABSENCE
# =========================================================


class _FakeCompleted:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def test_close_verifies_success_when_process_tree_gone(manager, monkeypatch):
    monkeypatch.setattr(manager, "resolve_application", lambda name: "C:\\apps\\chrome.exe")
    monkeypatch.setattr(manager, "is_running", lambda exe, attempts=1: True)
    monkeypatch.setattr(manager, "wait_until_stopped", lambda exe, attempts=10, delay_seconds=0.5: True)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _FakeCompleted(stdout="SUCCESS: terminated."),
    )

    result = manager.close("chrome")

    assert result["success"] is True
    assert result["verified"] is True


def test_close_does_not_fake_success_when_process_survives(manager, monkeypatch):
    monkeypatch.setattr(manager, "resolve_application", lambda name: "C:\\apps\\chrome.exe")
    monkeypatch.setattr(manager, "is_running", lambda exe, attempts=1: True)
    monkeypatch.setattr(manager, "wait_until_stopped", lambda exe, attempts=10, delay_seconds=0.5: False)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _FakeCompleted(stdout="SUCCESS: terminated."),
    )

    result = manager.close("chrome")

    # The kill request was dispatched but Genesis could NOT
    # confirm termination: this must remain an honest failure.
    assert result["success"] is False
    assert result["verified"] is False


def test_wait_until_stopped_polls_past_dying_processes(manager, monkeypatch):
    """
    A dying browser may still appear in one or two polls; the
    verifier must keep waiting until genuine absence.
    """
    outputs = iter([
        _tasklist_output("chrome.exe"),
        _tasklist_output("chrome.exe"),
        _tasklist_output(),
    ])

    def fake_run(*args, **kwargs):
        return _FakeCompleted(stdout=next(outputs))

    monkeypatch.setattr(subprocess, "run", fake_run)
    sleeps = []
    monkeypatch.setattr(
        "genesis_os.applications.app_manager.time.sleep",
        lambda s: sleeps.append(s),
    )

    assert manager.wait_until_stopped("C:\\apps\\chrome.exe", attempts=10) is True


def test_wait_until_stopped_times_out_honestly(manager, monkeypatch):
    def fake_run(*args, **kwargs):
        return _FakeCompleted(stdout=_tasklist_output("chrome.exe"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        "genesis_os.applications.app_manager.time.sleep",
        lambda s: None,
    )

    assert manager.wait_until_stopped("C:\\apps\\chrome.exe", attempts=3) is False


# =========================================================
# EXECUTOR INTEGRATION — STATUS QUESTIONS ARE TRUSTWORTHY
# =========================================================


def test_is_chrome_running_produces_verified_action_result(manager, monkeypatch):
    from genesis_os.action_executor import ActionExecutor
    from genesis_os.action_plan import ActionPlan

    monkeypatch.setattr(manager, "is_running", lambda exe, attempts=1: True)

    class StubOS:
        def inspect_application(self, app):
            return manager.inspect(app)

    plan = ActionPlan(operation="application.inspect", target="chrome", confidence=0.95)
    result = ActionExecutor(StubOS()).execute(plan)

    assert result.success is True
    assert result.status == "verified"


# =========================================================
# DIRECTIVE: HONEST OBSERVATION FOR MISSING APPS & NON-WINDOWS
# =========================================================


def test_open_missing_application_reports_unavailable_not_verified(
    manager, monkeypatch
):
    """When the resolution engine cannot find the executable,
    ``open`` must report ``success=False`` AND ``verified=False``.
    The executor must NOT upgrade this to ``verified=True``
    through any downstream default.
    """
    # Force resolve_application to return None for every query
    monkeypatch.setattr(
        manager, "resolve_application", lambda name: None
    )

    result = manager.open("definitely_not_an_app_zzz_123")

    assert result["success"] is False
    # The result must explicitly carry verified=False so the
    # executor's _derive_verified default never silently
    # upgrades the failure.
    assert result.get("verified") is False, (
        f"Missing-app open must report verified=False; "
        f"got {result}"
    )
    assert result.get("available") is False, (
        f"Missing-app open must report available=False; "
        f"got {result}"
    )


def test_open_missing_application_executor_does_not_pretend_verified(
    monkeypatch,
):
    """Integration: the ActionExecutor must NOT mark a
    missing-app open as ``trustworthy_success`` (verified).
    """
    from genesis_os.action_executor import ActionExecutor
    from genesis_os.action_plan import ActionPlan
    from genesis_os.applications.app_manager import ApplicationManager

    real_manager = ApplicationManager()

    class StubOS:
        def open_application(self, name):
            return real_manager.open(name)

    plan = ActionPlan(
        operation="application.open",
        target="definitely_not_an_app_zzz_123",
        application="definitely_not_an_app_zzz_123",
        confidence=0.95,
    )
    result = ActionExecutor(StubOS()).execute(plan)

    assert result.success is False
    assert result.verified is False, (
        f"Executor reported verified=True for a missing app; "
        f"status={result.status} verified={result.verified}"
    )


def test_uri_open_reports_dispatched_not_verified(manager, monkeypatch):
    """Windows URI applications dispatch through explorer.exe
    asynchronously. We must NOT report verified=True because
    the UI was never independently inspected.
    """
    # Pretend we are on Windows so the URI path is exercised.
    import genesis_os.applications.app_manager as app_mod
    monkeypatch.setattr(app_mod.os, "name", "nt")

    # The manager's URI alias table maps "settings" -> ms-settings:.
    result = manager.open("settings")

    # The dispatch should be successful but verified=False
    # because the UI was not independently inspected.
    assert result["success"] is True
    assert result.get("dispatched") is True, (
        f"URI open must record dispatched=True; "
        f"got {result}"
    )
    assert result.get("verified") is False, (
        f"URI open must report verified=False (UI not "
        f"independently inspected); got {result}"
    )


class _PosixOSView:
    """Presents ``os.name == "posix"`` to one module, without touching
    the real :mod:`os`.

    REWRITTEN 2026-10-08. This test previously did
    ``monkeypatch.setattr(app_mod.os, "name", "posix")``. Because
    ``app_mod.os`` IS the global ``os`` module, that mutated
    ``os.name`` process-wide -- and ``pathlib.Path`` is a *live*
    factory that reads ``os.name`` on every call, while the concrete
    classes are fixed at import. So every ``Path(...)`` built inside
    the patch window became a ``PosixPath`` instance, and any later
    use of it (``.glob``, ``.iterdir`` -> ``with_segments`` ->
    ``type(self)(...)``) raised::

        NotImplementedError: cannot instantiate 'PosixPath' on your system

    That guard is evaluated at import, so it fires regardless of
    ``os.name``; there is no way to make a ``PosixPath`` usable on
    Windows. The failure surfaced only under the alternate ordering
    because a sibling test's import state changed which code path ran.

    Patching this view instead keeps ``os.name`` real, so ``Path``
    keeps producing ``WindowsPath``, while ``app_manager`` still sees
    a non-Windows platform and takes the branch under test.
    """

    def __init__(self, real_os):
        self._real = real_os

    @property
    def name(self):
        return "posix"

    def __getattr__(self, attribute):
        return getattr(self._real, attribute)


def test_inspect_on_non_windows_reports_unsupported_not_verified(
    manager, monkeypatch
):
    """On a non-Windows host, the process-table query cannot
    be issued. ``inspect`` must NOT claim ``verified=True``
    because we did not actually inspect anything.
    """
    import os as real_os

    import genesis_os.applications.app_manager as app_mod
    monkeypatch.setattr(app_mod, "os", _PosixOSView(real_os))
    monkeypatch.setattr(
        manager, "resolve_application", lambda name: "/usr/bin/ch"
    )

    try:
        result = manager.inspect("chrome")

        assert result["success"] == "dispatched"
        assert result.get("platform_unsupported") is True, (
            f"Non-Windows inspect must mark "
            f"platform_unsupported=True; got {result}"
        )
        # The whole point of the hardening: verified must be
        # False because we cannot actually inspect the process
        # table on this platform.
        assert result.get("verified") is False, (
            f"Non-Windows inspect must NOT claim verified=True; "
            f"got {result}"
        )
    finally:
        # The global must be exactly as we found it, and Path must
        # still produce the host's concrete class.
        assert real_os.name == "nt", f"os.name leaked: {real_os.name!r}"
        assert type(Path(".")) is type(Path(".")), "sanity"
        assert not isinstance(Path("."), PosixPath), (
            "Path() is producing PosixPath on a Windows host"
        )
    # running should be None (unknown), not a False lie.
    assert result.get("running") is None, (
        f"Non-Windows inspect must report running=None "
        f"(unknown), not a False default; got {result}"
    )


def test_inspect_unresolvable_application_reports_not_available(
    manager, monkeypatch
):
    """When the resolver returns None, inspect must report
    available=False and NOT pretend the app is installed.
    """
    monkeypatch.setattr(
        manager, "resolve_application", lambda name: None
    )

    result = manager.inspect("chrome")

    assert result["success"] is False
    assert result.get("available") is False, (
        f"Unresolvable inspect must report available=False; "
        f"got {result}"
    )
    assert result.get("running") is False
