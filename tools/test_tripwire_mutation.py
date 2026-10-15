"""The tripwire must fail an unmarked offender. This proves it does.

The three offenders in `tools/fixtures/test_tripwire_offenders_scratch.py`
carry no marks and are absent from `docs/tests_tiering.json`. They are
run in a CHILD pytest process, because that is the only honest way to
test a fixture: in-process, this file's own tests would already be
watched, the modules would already be imported, and a one-shot import
cost paid by an earlier test would make the tripwire look broken or the
offender look clean depending on order.

Each offender is one event class the tripwire is required to catch:

    non-loopback network    203.0.113.1 is RFC 5737 TEST-NET-3: reserved
                            for documentation, guaranteed unroutable, so
                            the attempt touches DNS and the network stack
                            without contacting anything real
    non-allowlisted exe     hostname.exe is read-only and instant, and is
                            deliberately absent from HARMLESS_EXECUTABLES
    ctypes window station   user32.GetForegroundWindow, the exact call
                            genesis_os/window_models.py makes

If the tripwire ever stops catching one of these, this file fails. That
is the whole point: a gate that silently stops working looks exactly like
a gate that has nothing to report.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
# Deliberately NOT named test_*.py. A file that is meant to fail must not
# be collected by an ordinary run, or the suite is permanently red for a
# reason nobody can explain. pytest still collects it when it is passed
# by explicit path, which is how the child process runs it.
OFFENDERS = Path(__file__).resolve().parent / "fixtures" / \
    "tripwire_offenders_scratch.py"

pytestmark = pytest.mark.skipif(
    not OFFENDERS.is_file(),
    reason="offender fixture file is missing",
)

EXPECTED = {
    "test_scratch_non_loopback_network_is_caught": "non-loopback network",
    "test_scratch_non_allowlisted_executable_is_caught": "allowlist",
    "test_scratch_ctypes_window_station_is_caught": "window-station",
}


def _run_child():
    # No `-p tripwire_plugin`: backend/conftest.py declares it, so the
    # tripwire must be active in ANY pytest invocation under backend,
    # with no flag. Passing -p here would prove only that the flag works.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(OFFENDERS), "-q",
         "--no-header", "-p", "no:cacheprovider"],
        cwd=BACKEND, capture_output=True, text=True, timeout=600)
    return proc.stdout + proc.stderr


@pytest.fixture(scope="module")
def child_output():
    return _run_child()


@pytest.mark.parametrize("test_name,expected_reason", sorted(EXPECTED.items()))
def test_tripwire_fails_unmarked_offender_by_name(child_output, test_name,
                                                   expected_reason):
    # pytest reports the node id relative to rootdir, so accept either
    # the bare filename or the full repo-relative path.
    candidates = [
        f"FAILED {OFFENDERS.name}::{test_name}",
        f"FAILED {OFFENDERS.relative_to(BACKEND).as_posix()}::{test_name}",
    ]
    assert any(c in child_output for c in candidates), (
        f"the tripwire did not fail {test_name}.\n"
        f"expected one of {candidates}\n"
        f"--- child output ---\n{child_output[-4000:]}")


def test_tripwire_failure_names_the_offending_action(child_output):
    """The message must say WHAT was reached, not just that something was."""
    for needle in ("203.0.113.1", "hostname.exe",
                   "user32.GetForegroundWindow"):
        assert needle in child_output, (
            f"tripwire message does not name {needle!r}; an author cannot "
            f"act on a message that omits the cause")


def test_tripwire_message_explains_how_to_resolve_it(child_output):
    """An author must be told the two legitimate ways out."""
    assert "pytest.mark.live" in child_output, "no instruction to mark live"
    assert "HARMLESS_EXECUTABLES" in child_output, (
        "no instruction to allowlist a genuinely harmless executable")
    assert "tools/tiering_rules.py" in child_output, (
        "the allowlist file was not named")


def test_offenders_carry_no_marks_and_are_not_in_the_tiering_snapshot():
    """The premise. If this fails, the test above proves nothing."""
    import json

    source = OFFENDERS.read_text(encoding="utf-8")
    assert "pytest.mark.live" not in source, (
        "the offender fixture must stay unmarked, or the tripwire is "
        "skipping it for the wrong reason")
    tiering = json.loads(
        (BACKEND / "docs" / "tests_tiering.json").read_text(encoding="utf-8"))
    for name in EXPECTED:
        nodeid = f"{OFFENDERS.relative_to(BACKEND).as_posix()}::{name}"
        assert nodeid not in tiering, (
            f"{nodeid} has been added to tests_tiering.json; it must stay "
            f"absent so it exercises the unmarked path")


# ----------------------------------------------------------------------
# The exemption list. An exemption nobody audits is just a hole.
# ----------------------------------------------------------------------

def test_exemptions_are_explicit_and_enumerated():
    import tiering_rules

    assert tiering_rules.RECORDER_SELF_TESTS, (
        "no self-test exemption is declared; if the list is gone, the "
        "canaries will start failing and someone will 'fix' it by "
        "widening the exemption without noticing it changed")
    for prefix in tiering_rules.RECORDER_SELF_TESTS:
        assert isinstance(prefix, str) and prefix.startswith("tools/")
    assert set(tiering_rules.RECORDER_SELF_TEST_EXEMPT_KINDS) == {
        "process", "dll_load", "ctypes_call"}, (
        "the self-test exemption must not cover gui, browser, network or "
        "os_launch; those would let a real capability through")


def test_exemption_covers_only_the_two_recorder_files():
    """Nothing else is exempt. A test outside those files is judged."""
    import tiering_rules

    exempt = [n for n in tiering_rules.RECORDER_SELF_TESTS
              if n in ("tools/test_record_probe_canaries.py",
                       "tools/test_record_probe_transparency.py")]
    assert len(exempt) == len(tiering_rules.RECORDER_SELF_TESTS)
    # Spot-check the predicate against a file that must NOT be exempt.
    assert not tiering_rules.is_recorder_self_test("test_phase6_unit.py::x")
    assert not tiering_rules.is_recorder_self_test("tools/other.py::x")


def test_a_gui_event_is_never_exempt_even_for_self_tests():
    """The exemption is by event kind, and must not leak to gui/browser."""
    import tiering_rules

    gui = [{"kind": "gui", "api": "pyautogui.click", "count": 1}]
    browser = [{"kind": "browser", "api": "selenium.webdriver.Chrome",
                "count": 1}]
    net = [{"kind": "network", "api": "socket.connect", "host": "example.com",
            "loopback": False, "count": 1}]
    exempt = tiering_rules.RECORDER_SELF_TEST_EXEMPT_KINDS
    assert tiering_rules.event_reasons(gui, exempt_kinds=exempt)
    assert tiering_rules.event_reasons(browser, exempt_kinds=exempt)
    assert tiering_rules.event_reasons(net, exempt_kinds=exempt)
    # ...but a process event IS exempt for them, which is the whole point.
    proc = [{"kind": "process", "api": "Popen", "exe": "python.exe",
             "argv": ["python.exe"], "count": 1}]
    assert not tiering_rules.event_reasons(proc, exempt_kinds=exempt)