"""Item 21B (C33): the startup probe pool blocks construction and teardown.

BrowserManager.__init__ ran the two advanced-provider probes inside:

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="browser_probe") as pool:
        ...
        done, pending = wait([f_sel, f_pw], timeout=..._PROVIDER_PROBE_TIMEOUT)
        for future in pending:
            future.cancel()

future.cancel() cannot stop a STARTED probe, and the `with` exit then
runs shutdown(wait=True) -- so a probe that hangs holds the
constructor open for the probe's full runtime. MEASURED on the
committed original (_PROVIDER_PROBE_TIMEOUT=1.0, probe sleeps 6s):

    construction took 6.00s  <- the 1.0s bound never applied

and the existing test_a_slow_probe_yields_degraded_true_with_a_reason
(60s stubs) paid the full 60.40s.

WHY NOT ThreadPoolExecutor + shutdown(wait=False) (the literal first
reading of the fix): Python 3.9+ ThreadPoolExecutor workers are
NON-daemon by design (bpo-39812) and are joined at interpreter exit
via threading._register_atexit(_python_exit) -- _python_exit joins
EVERY executor thread ever registered, wait=False or not. MEASURED:
an 8s worker abandoned via shutdown(wait=False, cancel_futures=True)
still delayed interpreter exit by 8.19s. The probes are pure
diagnostics (their only side effect is a provider-list insert), so
they run as plain daemon threads with a bounded join: construction
returns at the bound, a still-running probe is ABANDONED, and a
daemon thread cannot block interpreter exit.

THE HONEST LIMIT: a probe that finishes after the window had its
answer DISCARDED (it "did not answer" -- that is what degraded
means), and degraded_reason still says timeout, never absence:
absent != failed.

Fail-before against the committed original: the construction tests
block for the full stub sleep, and the subprocess test reports
probes=0 (the `with` form waited for them) instead of probes=2.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import textwrap
import time

import pytest

from genesis_os.browser_manager import BrowserManager

MODULE = pathlib.Path("genesis_os") / "browser_manager.py"

# In-process construction bound: fail-before ~5.0s (the stub sleep),
# pass-after ~0.3s (the window). Both sides sit far from 1.5.
STUB_SLEEP_S = 5.0
WINDOW_S = 0.3
MUST_BUILD_BY = 1.5

# Subprocess: the probes hang for the whole 8s; before the fix the
# constructor waits them out (fail-before total ~8.5s), after it
# construction returns at the 0.5s window and the daemon probes are
# abandoned (pass-after total ~1.5s).
SUB_WINDOW_S = 0.5
SUB_STUB_SLEEP_S = 8.0
SUB_MUST_BUILD_BY = 1.5
SUB_MUST_EXIT_BY = 4.0


def _hang(self=None):
    time.sleep(STUB_SLEEP_S)


def _function_body(name):
    tree = ast.parse(MODULE.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {MODULE}")


# --------------------------------------------------------------------------
# Construction returns at the bound, degraded but usable
# --------------------------------------------------------------------------

def test_hanging_probes_do_not_block_construction(monkeypatch):
    monkeypatch.setattr(BrowserManager, "_PROVIDER_PROBE_TIMEOUT", WINDOW_S)
    monkeypatch.setattr(BrowserManager, "_try_register_selenium", _hang)
    monkeypatch.setattr(BrowserManager, "_try_register_playwright", _hang)

    started = time.monotonic()
    manager = BrowserManager()
    built = time.monotonic() - started

    assert built < MUST_BUILD_BY, (
        f"construction blocked {built:.3f}s against a {WINDOW_S}s "
        f"probe window and a {STUB_SLEEP_S}s hanging probe -- the "
        "`with` pool form waited for the probes instead of abandoning "
        "them at the bound"
    )
    # Honest degraded: timeout, not absence, and still usable.
    assert manager.degraded is True
    assert "timeout" in (manager.degraded_reason or "").lower(), (
        manager.degraded_reason
    )
    assert "webbrowser" in manager.provider_names


# --------------------------------------------------------------------------
# No non-daemon probe thread can block interpreter exit (subprocess)
# --------------------------------------------------------------------------

_SUBPROCESS_SCRIPT = textwrap.dedent("""\
    import sys, time, threading
    from genesis_os.browser_manager import BrowserManager

    BrowserManager._PROVIDER_PROBE_TIMEOUT = {window}
    BrowserManager._try_register_selenium = lambda self: time.sleep({sleep})
    BrowserManager._try_register_playwright = lambda self: time.sleep({sleep})

    t0 = time.monotonic()
    manager = BrowserManager()
    built = time.monotonic() - t0

    probes = [t for t in threading.enumerate()
              if t.name.startswith("browser_probe")]
    non_daemon = [t.name for t in probes if not t.daemon]
    print("RESULT built=%.2f probes=%d non_daemon=%d degraded=%d webbrowser=%d" % (
        built, len(probes), len(non_daemon),
        1 if manager.degraded else 0,
        1 if "webbrowser" in manager.provider_names else 0))
""").format(window=SUB_WINDOW_S, sleep=SUB_STUB_SLEEP_S)


def test_no_non_daemon_probe_thread_blocks_exit():
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_SCRIPT],
        cwd=str(pathlib.Path(__file__).resolve().parent),
        capture_output=True,
        text=True,
        timeout=60,
    )
    wall = time.monotonic() - started

    assert proc.returncode == 0, (
        f"probe script failed:\n{proc.stdout}\n{proc.stderr}"
    )
    result_line = [l for l in proc.stdout.splitlines()
                   if l.startswith("RESULT ")]
    assert result_line, f"no result line in: {proc.stdout!r}"
    fields = dict(
        pair.split("=") for pair in result_line[0].split()[1:]
    )
    built = float(fields["built"])

    assert built < SUB_MUST_BUILD_BY, (
        f"construction took {built:.2f}s against a {SUB_WINDOW_S}s "
        "window -- the `with` pool form waited for the hung probes"
    )
    assert int(fields["probes"]) == 2, (
        "expected both probes still running after construction "
        f"(they must be abandoned, not waited for): {result_line[0]}"
    )
    assert int(fields["non_daemon"]) == 0, (
        "a non-daemon probe thread survived construction -- it would "
        "block interpreter exit (ThreadPoolExecutor workers are "
        "non-daemon and _python_exit joins them; measured 8.19s for "
        f"an 8s worker): {result_line[0]}"
    )
    assert int(fields["degraded"]) == 1, "hanging probes must degrade"
    assert int(fields["webbrowser"]) == 1, "degraded must stay usable"
    assert wall < SUB_MUST_EXIT_BY, (
        f"the probe process took {wall:.2f}s to construct AND exit "
        f"with {SUB_STUB_SLEEP_S}s probes still sleeping -- nothing "
        "stopped them from holding the process open"
    )


# --------------------------------------------------------------------------
# The answer window: timely answers register, late answers are discarded
# --------------------------------------------------------------------------

class _SlowSelenium:
    """Answers the probe, but not within the window."""

    name = "selenium"

    def __init__(self):
        time.sleep(2.5)
        self.available = True


class _FastSelenium:
    """Answers immediately."""

    name = "selenium"

    def __init__(self):
        self.available = True


def test_a_late_probe_answer_is_discarded(monkeypatch):
    """Absent != failed, and late != present.

    The probe finishes AFTER the window closed: construction must
    already have returned degraded, and when the answer finally
    arrives it must NOT be applied -- otherwise the manager would
    report "advanced provider missing because its probe timed out"
    while quietly carrying the provider.
    """
    monkeypatch.setattr(BrowserManager, "_PROVIDER_PROBE_TIMEOUT", WINDOW_S)
    monkeypatch.setattr(
        BrowserManager, "_try_register_playwright", lambda self: None
    )
    monkeypatch.setattr(
        "genesis_os.browser_selenium.SeleniumBrowserProvider", _SlowSelenium
    )

    started = time.monotonic()
    manager = BrowserManager()
    built = time.monotonic() - started

    assert built < MUST_BUILD_BY, (
        f"construction blocked {built:.3f}s waiting for the slow "
        "provider probe instead of abandoning it at the bound"
    )
    assert manager.degraded is True

    # The late answer lands at ~2.5s; give it time to try.
    time.sleep(3.0)
    assert "selenium" not in manager.provider_names, (
        "a probe that answered after the window was applied anyway; "
        "the degraded flag says the provider is missing because its "
        "probe timed out, so a late answer must be discarded"
    )
    assert manager.degraded is True


def test_a_timely_answer_still_registers(monkeypatch):
    """The gate must not discard an answer that arrived in time."""
    monkeypatch.setattr(BrowserManager, "_PROVIDER_PROBE_TIMEOUT", 5.0)
    monkeypatch.setattr(
        BrowserManager, "_try_register_playwright", lambda self: None
    )
    monkeypatch.setattr(
        "genesis_os.browser_selenium.SeleniumBrowserProvider", _FastSelenium
    )

    manager = BrowserManager()

    assert "selenium" in manager.provider_names, (
        "an in-window provider was discarded -- registration is broken"
    )
    assert manager.degraded is False
    assert manager.degraded_reason is None


# --------------------------------------------------------------------------
# Structural: the blocking `with` pool is gone, probes are daemon
# --------------------------------------------------------------------------

def test_the_blocking_with_pool_form_is_gone():
    node = _function_body("__init__")

    with_blocks = [n for n in ast.walk(node) if isinstance(n, ast.With)]
    offenders = []
    for block in with_blocks:
        for item in block.items:
            src = ast.unparse(item.context_expr)
            if "ThreadPoolExecutor" in src:
                offenders.append(src)

    assert not offenders, (
        f"`with ThreadPoolExecutor(...)` is back in __init__: "
        f"{offenders}. The __exit__ runs shutdown(wait=True) and "
        "blocks behind the hung probe, so the bound cannot apply"
    )


def test_probes_are_started_as_daemon_threads():
    body = ast.unparse(_function_body("__init__"))
    assert "daemon=True" in body, (
        "probes must be daemon threads: ThreadPoolExecutor workers "
        "are non-daemon (bpo-39812) and _python_exit joins them at "
        "interpreter exit even after shutdown(wait=False) -- measured "
        "8.19s of exit delay for an 8s abandoned worker"
    )
    assert ".join(timeout=" in body, (
        "the probe wait must be bounded by a deadline"
    )
