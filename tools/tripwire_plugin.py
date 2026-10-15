"""Fast-gate tripwire: fail a test that reaches for a real capability.

The problem this exists to solve
--------------------------------
`docs/tests_tiering.json` is a snapshot. A test written tomorrow is not
in it, keeps whatever marks it has -- which is none -- and therefore
lands in the fast gate by default. Continuation A4 proved the fast gate
was running 22 tests that touched a real window station, a real browser
and the real network, while reporting green.

Nothing in the marking scheme prevents that from recurring. This does.

How it works
------------
`pytest_runtest_setup` and `pytest_runtest_teardown` are hookwrappers
that open a capture frame BEFORE any fixture setup runs and close it
AFTER every finalizer has run, so a test is watched across its entire
lifecycle -- setup of every scope, the call phase, and teardown of every
scope. The autouse-fixture form this replaced could not do that: pytest
sets fixtures up highest-scope-first, so a module-scoped fixture was
already built before any function-scoped autouse frame existed, and
teardown runs lowest-scope-first, so a module-scoped finalizer ran after
the frame was gone. Both ends of the lifecycle were blind.

The frame's events are inspected at three points: after the call phase
(an ordinary FAILED), and after teardown (recorded, then surfaced as an
ordinary FAILED by `pytest_runtest_makereport`, never as an error).

The rules come from `tools/tiering_rules.py`, the same module that
produced the snapshot. One rule set, so a test the tiering called
`runtime` is exactly a test the tripwire permits.

Judgment never raises at the call site. That is deliberate and it is the
reason the A2 blocking probe was abandoned: a block raised inside an
async task surfaces as a playwright `TargetClosedError`, and the real
cause is swallowed. Recording first and judging afterwards cannot swallow
anything, because it never raises during the test.

    pytest -m "not live"                      # tripwire ON
    pytest -m "not live" --no-tripwire        # tripwire OFF
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND / "tools") not in sys.path:
    sys.path.insert(0, str(BACKEND / "tools"))

import tiering_rules as rules  # noqa: E402

TRIPWIRE_ENABLED = {"value": True}
# Per-test OVERHEAD accounting: frame setup + teardown only, never the
# test body. Timing the whole fixture span would report the suite's own
# runtime back as "tripwire cost", which is how an instrument ends up
# looking 90 seconds expensive when it costs 90 milliseconds.
STATS = {"tests": 0, "failures": 0, "overhead_seconds": 0.0}
# nodeid -> capture frame, live from BEFORE fixture setup until AFTER
# every finalizer has run.
FRAMES: dict = {}
# nodeid -> seconds spent attaching the frame.
SETUP_COST: dict = {}
# nodeid -> message for a violation raised during TEARDOWN. Held here
# rather than raised in the finalizer, so `pytest_runtest_makereport`
# can turn the resulting ERROR into an ordinary FAILED. See below.
LATE_VIOLATIONS: dict = {}


def _event_counts(frame) -> dict:
    return {record_probe.event_key(e): e.get("count", 1)
            for e in frame["events"]}


def _new_events(frame, seen) -> list:
    """Events that appeared, or grew, after `seen` was snapshotted."""
    current = {record_probe.event_key(e): e.get("count", 1)
               for e in frame["events"]}
    grown = {k for k, n in current.items() if n > seen.get(k, 0)}
    if not grown:
        return []
    return [e for e in frame["events"]
            if record_probe.event_key(e) in grown]


def pytest_addoption(parser):
    group = parser.getgroup("genesis-tripwire")
    group.addoption("--no-tripwire", action="store_true", default=False,
                    help="disable the fast-gate capability tripwire")


def pytest_configure(config):
    TRIPWIRE_ENABLED["value"] = not config.getoption("--no-tripwire",
                                                    default=False)


def _is_exempt(nodeid: str) -> bool:
    return rules.is_recorder_self_test(nodeid)


def _exempt_kinds(nodeid):
    return (rules.RECORDER_SELF_TEST_EXEMPT_KINDS
            if _is_exempt(nodeid) else ())


def _watch(item) -> bool:
    """Should this item be watched at all?

    Skipped for `live` tests: they are SUPPOSED to open windows and
    browsers. That is the whole meaning of the marker.
    """
    if not TRIPWIRE_ENABLED["value"]:
        return False
    return item.get_closest_marker("live") is None


def _attach(item):
    """Open a capture frame covering the WHOLE item lifecycle.

    Why this is a `pytest_runtest_setup` hookwrapper and not an autouse
    fixture
    ----------------------------------------------------------
    pytest sets fixtures up HIGHEST SCOPE FIRST. A module-scoped
    fixture is therefore set up BEFORE any function-scoped autouse
    fixture, so the autouse form attached its frame too late to see a
    module-scoped fixture's setup. That is not a hypothetical: a
    module-scoped fixture in this suite builds a real `GenesisOS`,
    whose browser probe is precisely the event class the tripwire
    exists to catch, and it was invisible.

    Symmetrically, teardown runs LOWEST SCOPE FIRST, so a module- or
    session-scoped finalizer runs after every function-scoped autouse
    finalizer -- the autouse form had already removed its frame, and
    teardown-phase violations were invisible too.

    Wrapping the two hooks puts the frame outside the entire fixture
    lifecycle at both ends, for every scope.
    """
    import time as _time

    if not _watch(item):
        return
    global record_probe
    import record_probe

    t0 = _time.perf_counter()
    nodeid = item.nodeid
    frame = record_probe.new_capture(nodeid)
    record_probe.ensure_installed()
    record_probe._CAPTURE_STACK.append(frame)
    FRAMES[nodeid] = frame
    SETUP_COST[nodeid] = _time.perf_counter() - t0


def _detach(item, t0):
    """Close the frame and judge anything raised while finalizers ran."""
    import time as _time

    nodeid = item.nodeid
    frame = FRAMES.pop(nodeid, None)
    STATS["overhead_seconds"] += SETUP_COST.pop(nodeid, 0.0)
    if frame is None:
        return
    if not _watch(item):
        STATS["overhead_seconds"] += _time.perf_counter() - t0
        return

    # Backstop: anything the call-phase check already judged is in
    # `_checked`; only genuinely new violations -- i.e. raised during
    # fixture teardown -- are reported here.
    seen = frame.get("_checked") or {}
    late = _new_events(frame, seen)
    if late:
        reasons = rules.event_reasons(late,
                                      exempt_kinds=_exempt_kinds(nodeid))
        if reasons:
            STATS["failures"] += 1
            LATE_VIOLATIONS[nodeid] = (
                _message(item, reasons, _is_exempt(nodeid)) +
                "\n\nNOTE: this capability was reached during TEARDOWN "
                "(fixture finalization), not during the test body.\n")
    if frame in record_probe._CAPTURE_STACK:
        record_probe._CAPTURE_STACK.remove(frame)
    STATS["overhead_seconds"] += _time.perf_counter() - t0


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    """Attach BEFORE fixture setup, so every scope's setup is watched."""
    _attach(item)
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Judge after every finalizer has run, for every scope."""
    import time as _time

    t0 = _time.perf_counter()
    if _watch(item):
        STATS["tests"] += 1
    try:
        yield
    finally:
        _detach(item, t0)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Report a teardown-phase violation as a FAILED, not an ERROR.

    Setting `report.outcome = "failed"` is NOT sufficient on its own.
    `_pytest.runner.pytest_report_teststatus` has a `tryfirst` impl that
    maps any FAILED setup or teardown report to ("error", "E", "ERROR"),
    so a violation found during fixture finalization is counted and
    displayed as an error no matter what the outcome says. The
    companion `pytest_report_teststatus` hook below overrides that
    classification for reports this plugin raised.

    Raising inside a finalizer is reported by pytest as an error, and a
    summary reading "3120 passed, 1 error" is a shape in which a test
    that quietly reached a browser is easy to miss. A finalizer-phase
    finding is a test failure and is reported as one, attributed to the
    test that caused it, by name.
    """
    outcome = yield
    report = outcome.get_result()
    if report.when != "teardown":
        return
    message = LATE_VIOLATIONS.pop(item.nodeid, None)
    if not message:
        return
    report.outcome = "failed"
    report.longrepr = message
    report._genesis_tripwire_teardown = True


@pytest.hookimpl(tryfirst=True)
def pytest_report_teststatus(report):
    """Keep a teardown-phase tripwire finding counted as a failure.

    `tryfirst` so it runs ahead of the built-in mapping described above.
    Returns None for everything else, which is the documented way to
    defer to the next implementation.
    """
    if getattr(report, "_genesis_tripwire_teardown", False):
        return "failed", "F", "FAILED"
    return None



@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Judge the test body, and report a genuine FAILED rather than a
    teardown ERROR.

    Raising inside a fixture finalizer is reported by pytest as
    "N passed, M errors" -- the offending test still counts as passed.
    In a gate that is the wrong shape: a summary can read green while a
    test quietly reached a browser. Judging here, immediately after the
    body and before finalizers, produces an ordinary failure.
    """
    outcome = yield
    if not _watch(item):
        return
    frame = FRAMES.get(item.nodeid)
    if frame is None:
        return

    reasons = rules.event_reasons(frame["events"],
                                  exempt_kinds=_exempt_kinds(item.nodeid))
    frame["_checked"] = _event_counts(frame)
    if not reasons:
        return
    STATS["failures"] += 1
    outcome.force_exception(
        pytest.fail.Exception(_message(item, reasons, _is_exempt(item.nodeid)),
                              pytrace=False))


def _message(item, reasons, exempt) -> str:
    lines = [
        f"capability tripwire: {item.nodeid} reached a real capability "
        f"that the fast gate must not depend on",
        "",
        "recorded during this test:",
    ]
    for reason in reasons[:12]:
        lines.append(f"  - {reason}")
    if len(reasons) > 12:
        lines.append(f"  ... and {len(reasons) - 12} more")
    lines.append("")
    if exempt:
        lines.append(
            "This file is exempt from the process and ctypes rules because "
            "it tests the recorder itself. That exemption is enumerated in "
            "RECORDER_SELF_TEST_EXEMPT_KINDS in tools/tiering_rules.py and "
            "does NOT cover a new event class."
        )
        return "\n".join(lines)

    lines.append("This test is unmarked, so it runs in the fast gate.")
    lines.append("Do one of these:")
    lines.append("")
    lines.append(
        "  1. If the behaviour is genuinely required, mark the test "
        "`live`:")
    lines.append("")
    lines.append("       pytestmark = pytest.mark.live")
    lines.append("")
    lines.append(
        "     or add the marker in docs/tests_tiering.json and re-run "
        "tools/apply_tiering.py. A `live` test is skipped by the fast "
        "gate and must be able to touch the desktop, a browser and the "
        "network.")
    lines.append("")
    lines.append(
        "  2. If the executable really is harmless and read-only, add it "
        "to HARMLESS_EXECUTABLES in tools/tiering_rules.py WITH a reason "
        "for why it is harmless. The allowlist is a closed set: "
        "anything absent from it is treated as not harmless.")
    lines.append("")
    lines.append(
        "  3. If this is a false positive, do not silence it with "
        "--no-tripwire in CI. Narrow the rule in tools/tiering_rules.py "
        "so the specific event is excluded and the rest stays watched.")
    return "\n".join(lines)


def pytest_terminal_summary(terminalreporter, exitstatus=None, config=None):
    if not STATS["tests"]:
        return
    if not TRIPWIRE_ENABLED["value"]:
        terminalreporter.write_sep("-", "capability tripwire disabled")
        return
    terminalreporter.write_sep("-", "capability tripwire")
    watched = STATS["tests"]
    overhead = STATS["overhead_seconds"]
    per_test = (overhead / watched * 1000) if watched else 0.0
    terminalreporter.write_line(
        f"watched {watched} fast-gate test(s); "
        f"{STATS['failures']} reached a real capability."
    )
    terminalreporter.write_line(
        f"tripwire overhead: {overhead:.2f}s total, "
        f"{per_test:.2f} ms per test (fixture setup + teardown only)."
    )