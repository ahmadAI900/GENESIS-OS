"""Item 21C (C36): GenesisOS had no shutdown API.

The runtime starts resources it never stops -- the filesystem
watcher (os_manager.start_watching), open browser provider
sessions, the run loop -- and genesis.py exposed no shutdown(),
close() or stop() of any kind. Consequences, all in-tree:

  * benchmark/real_e2e.py could not exit at all; its own comment
    says "the runtime exposes no shutdown API, so a plain sys.exit
    would hang forever", and it hard-exits with os._exit instead,
    skipping every cleanup;
  * the conftest genesis_runtime fixture simply abandoned the
    module-scoped runtime at teardown;
  * main() returned into an interpreter exit whose promptness was
    luck (measured on this machine: bare construction happened to
    leave no non-daemon children -- the missing API is still the
    bug, and the harness comment documents the class of hang).

shutdown() now exists and is:
  * wired -- called from main() (finally), the real_e2e harness
    (before its hard exit), and the conftest fixture teardown;
  * honest -- stops what it can (run loop, watcher, browser
    providers), lists every remaining NON-DAEMON thread (a thread
    cannot be killed) and forces success=False when anything
    remains or a stop raised; never claims a clean stop it did not
    achieve;
  * idempotent -- a second call re-stops nothing.

Fail-before against the committed original: every test here fails
AttributeError / finds no shutdown call, except the guards that
assert the harness still hard-exits after shutting down.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import threading
import time

GENESIS = pathlib.Path("genesis.py")
CONFTEST = pathlib.Path("conftest.py")
HARNESS = pathlib.Path("benchmark") / "real_e2e.py"


def _function_body(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path}")


# --------------------------------------------------------------------------
# The API exists and stops what it owns
# --------------------------------------------------------------------------

def test_the_runtime_exposes_a_shutdown_method():
    from genesis import GenesisOS

    assert hasattr(GenesisOS, "shutdown"), (
        "GenesisOS has no shutdown(); the runtime starts a watcher "
        "and browser sessions it can never stop, and the e2e harness "
        "is forced to os._exit around the leak"
    )
    assert callable(GenesisOS.shutdown)


class _StubBrowser:
    def __init__(self, *, close_result=None, close_raises=None):
        self.close_calls = 0
        self.close_result = close_result or {
            "success": True, "errors": [],
        }
        self.close_raises = close_raises

    def close(self):
        self.close_calls += 1
        if self.close_raises is not None:
            raise self.close_raises
        return self.close_result


class _StubOSManager:
    def __init__(self, browser=None):
        self.browser = browser if browser is not None else _StubBrowser()
        self.stop_calls = 0

    def stop_watching(self):
        self.stop_calls += 1
        return {"success": True, "watching": False, "path": None}


def _runtime(os_manager=None):
    """A GenesisOS built without paying the real ~9s construction."""
    from genesis import GenesisOS

    g = GenesisOS.__new__(GenesisOS)
    g.running = True
    g.os_manager = _StubOSManager() if os_manager is None else os_manager
    return g


def test_shutdown_stops_the_loop_and_the_owned_resources():
    g = _runtime()

    report = g.shutdown()

    assert g.running is False, "shutdown() must stop the run() loop"
    assert g.os_manager.stop_calls == 1, (
        "the filesystem watcher was never stopped"
    )
    assert g.os_manager.browser.close_calls == 1, (
        "the browser providers were never closed -- their driver "
        "sessions and subprocesses outlive the runtime"
    )
    assert report["errors"] == [], report
    assert "run_loop" in report["stopped"], report
    assert "filesystem_watcher" in report["stopped"], report
    assert "browser_providers" in report["stopped"], report
    assert report["already_shutdown"] is False


def test_shutdown_is_idempotent():
    g = _runtime()

    first = g.shutdown()
    second = g.shutdown()

    assert second["already_shutdown"] is True, second
    assert g.os_manager.stop_calls == 1, (
        "a second shutdown re-stopped the watcher -- stop must be "
        "idempotent, not repeated"
    )
    assert g.os_manager.browser.close_calls == 1, (
        "a second shutdown re-closed the providers; a closed driver "
        "raises on a second close and would fabricate an error"
    )
    assert second["success"] == first["success"] or (
        second["unstoppable_threads"] and not first["unstoppable_threads"]
    ), (first, second)


# --------------------------------------------------------------------------
# The honest report: what could not be stopped is listed, not hidden
# --------------------------------------------------------------------------

def test_shutdown_reports_the_threads_it_cannot_stop():
    """A thread cannot be killed; say so instead of claiming success."""
    g = _runtime()

    release = threading.Event()

    def _stub_worker():
        release.wait(5.0)

    worker = threading.Thread(
        target=_stub_worker, name="c36_stub_thread", daemon=False,
    )
    worker.start()
    try:
        report = g.shutdown()
    finally:
        release.set()
        worker.join(5.0)

    names = [entry["name"] for entry in report["unstoppable_threads"]]
    assert "c36_stub_thread" in names, (
        f"a live non-daemon thread was not reported: {report}"
    )
    assert report["success"] is False, (
        "shutdown claimed success while a non-daemon thread was "
        "still running -- it must REPORT unstoppable threads, not "
        "paper over them"
    )


def test_a_stop_that_raises_is_reported_not_swallowed():
    g = _runtime(os_manager=_StubOSManager(
        browser=_StubBrowser(close_raises=RuntimeError("driver wedged")),
    ))

    report = g.shutdown()

    assert g.os_manager.stop_calls == 1, (
        "one resource failing must not skip the others"
    )
    assert report["success"] is False, (
        "a browser close that raised must not be reported as success"
    )
    assert any("browser" in e and "driver wedged" in e
               for e in report["errors"]), report


def test_a_clean_runtime_reports_success_in_a_clean_process():
    """Deterministic success pin: no stray session threads possible."""
    script = (
        "from genesis import GenesisOS\n"
        "g = GenesisOS.__new__(GenesisOS)\n"
        "g.running = True\n"
        "g.os_manager = None\n"
        "r = g.shutdown()\n"
        "print('RESULT success=%s stopped=%s unstoppable=%d' % (\n"
        "    r['success'], r['stopped'], len(r['unstoppable_threads'])))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(pathlib.Path(__file__).resolve().parent),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"shutdown failed in a clean process:\n{proc.stdout}\n{proc.stderr}"
    )
    line = [l for l in proc.stdout.splitlines()
            if l.startswith("RESULT ")][-1]
    assert "success=True" in line, line
    assert "unstoppable=0" in line, line


# --------------------------------------------------------------------------
# The wiring: main(), the harness, the conftest fixture
# --------------------------------------------------------------------------

def test_main_shuts_the_runtime_down():
    body = ast.unparse(_function_body(GENESIS, "main"))
    assert "shutdown" in body, (
        "main() never calls shutdown(); the run loop's resources "
        "outlive the session and the only teardown is interpreter exit"
    )


def test_the_conftest_fixture_shuts_the_runtime_down():
    body = ast.unparse(_function_body(CONFTEST, "genesis_runtime"))
    assert "shutdown" in body, (
        "the genesis_runtime fixture abandons the runtime it built; "
        "module-scoped runtimes must be stopped at teardown"
    )


def test_the_real_e2e_harness_shuts_down_then_still_hard_exits():
    src = HARNESS.read_text(encoding="utf-8-sig")
    assert "shutdown" in src, (
        "the real_e2e harness never stops the runtime it booted"
    )
    # The hard exit stays: abandoned daemon/abandoned workers may
    # still hold a plain exit open, and the exit status must not
    # depend on them (pinned also by test_real_e2e_harness.py).
    assert "os._exit" in src
