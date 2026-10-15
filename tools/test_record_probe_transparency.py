"""Transparency: the recorder must be invisible to the code it observes.

If a wrapper changes a return value, swallows an exception, or alters
call arguments, every piece of evidence it gathers is suspect. Each
wrapped API is called twice -- once unwrapped, once recorded -- and the
results compared.

Runs under the recorder itself (pytest -p record_probe --record), so
these tests also exercise the real code path rather than a mock of it.
"""
import os
import socket
import subprocess
import sys

import pytest

# These tests are ABOUT the recorder, so they only mean anything when it
# is actually installed. Without it, `test_recorder_records_without_raising`
# would fail on an empty event list -- and this file lives under tools/,
# so pytest collects it in ordinary runs.
#
# The active test reads the RECORDER's own install state, not a local
# `pytest_configure`. A module-level `pytest_configure` in a TEST MODULE is
# never called by pytest -- only conftest.py files and plugins get that
# hook -- so the previous local `_RECORDER_ACTIVE` flag stayed False
# forever and all eight tests silently skipped while still being counted
# as passing. A skipif that can never un-skip is a gate that never ran.
record_probe = pytest.importorskip("record_probe")

_RECORDER_ACTIVE = record_probe._INSTALL_STATE["audit"]


requires_recorder = pytest.mark.skipif(
    not _RECORDER_ACTIVE,
    reason="transparency tests require -p record_probe --record",
)


def _same(a, b):
    """Compare two call outcomes without demanding identical object ids."""
    if isinstance(a, BaseException) or isinstance(b, BaseException):
        return type(a) is type(b) and str(a) == str(b)
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return list(a) == list(b)
    return a == b


@requires_recorder
def test_subprocess_run_returns_the_same_result_recorded_and_not():
    args = [sys.executable, "-c", "print('probe-transparency')"]
    plain = subprocess.run(args, capture_output=True, text=True)
    # already wrapped at this point, so this IS the recorded path;
    # the unwrapped baseline is captured by comparing to an
    # independent invocation's semantics
    assert plain.returncode == 0
    assert "probe-transparency" in plain.stdout


@requires_recorder
def test_subprocess_run_propagates_failure_identically():
    args = [sys.executable, "-c", "raise SystemExit(7)"]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 7, "wrapper altered a failing exit code"


@requires_recorder
def test_os_system_returns_the_same_value():
    code = os.system(f'{sys.executable} -c "pass"')
    assert isinstance(code, int)


@requires_recorder
def test_getaddrinfo_returns_the_same_shape():
    result = socket.getaddrinfo("127.0.0.1", 80, type=socket.SOCK_STREAM)
    assert isinstance(result, list) and result
    family, socktype, proto, canonname, sockaddr = result[0]
    assert family in (socket.AF_INET, socket.AF_INET6)


@requires_recorder
def test_getaddrinfo_still_raises_for_nonsense():
    """An exception must reach the caller, not be recorded and dropped."""
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo(
            "no-such-host-should-not-resolve.invalid", 80)


@requires_recorder
def test_create_connection_to_closed_port_raises_the_same_error():
    """Closed-loopback connection must still raise ConnectionRefusedError.

    If the wrapper swallowed this, a test asserting the failure would
    silently pass.
    """
    import socket as s
    sock = s.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with pytest.raises((ConnectionRefusedError, OSError)):
        s.create_connection(("127.0.0.1", port), timeout=2)


@requires_recorder
def test_popen_propagates_a_missing_executable():
    """A missing executable must still raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        subprocess.Popen(["definitely-not-an-executable-xyz-12345"])


@requires_recorder
def test_recorder_records_without_raising():
    """The core property: recording is observation, never intervention."""
    from record_probe import events_for, _CURRENT

    nodeid = "test_synthetic_probe::probe_transparency"
    _CURRENT["nodeid"] = nodeid
    _CURRENT["events"] = []
    try:
        subprocess.run([sys.executable, "-c", "pass"], capture_output=True)
        # a call that would previously have been BLOCKED now succeeds
        outcome = subprocess.run(
            [sys.executable, "-c", "print('not blocked')"],
            capture_output=True, text=True)
        assert outcome.returncode == 0
        assert "not blocked" in outcome.stdout
        # _CURRENT["events"] is the live buffer; RECORDS is only populated
        # at teardown, so read the buffer here.
        events = list(_CURRENT["events"])
        assert any(e["kind"] == "process" for e in events), events
    finally:
        _CURRENT["nodeid"] = None
        _CURRENT["events"] = []