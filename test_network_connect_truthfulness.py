"""Item 4C -- Wi-Fi verification must come from real interface state.

`netsh wlan connect` returning 0 means the REQUEST was accepted, not
that the interface associated: the operation is asynchronous and returns
0 for networks that then fail to join. The product nevertheless set
`verified = connect.returncode == 0`, so a connection that never
happened was reported as verified.

Verification now reads `netsh wlan show interfaces` and requires the
State to be `connected` AND the SSID to match the requested network.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from genesis_os import network_manager as NM

SECRET = "hunter2-SUPER-SECRET-PSK"

DISCONNECTED = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel Wireless
    GUID                   : 1111
    Physical address       : aa:bb
    State                  : disconnected
    SSID                   :
"""

CONNECTED_CORRECT = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    State                  : connected
    SSID                   : CorpNet
    Signal                 : 99%
"""

CONNECTED_ELSEWHERE = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    State                  : connected
    SSID                   : SomeOtherNetwork
"""

UNPARSABLE = "netsh produced nothing useful"


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _connect(*, connect_rc=0, interfaces_stdout=CONNECTED_CORRECT,
             interfaces_rc=0, interfaces_stderr="", ssid="CorpNet",
             password=SECRET, interfaces_raises=False):
    """Drive connect_wifi with mocked netsh results. Returns (result, argv)."""
    argv = []

    def fake_run(cmd, **kwargs):
        argv.append(list(cmd))
        joined = cmd[:4]
        if joined == ["netsh", "wlan", "add", "profile"]:
            return _Proc(0, "Profile added")
        if joined[:4] == ["netsh", "wlan", "connect", f"name={ssid}"]:
            return _Proc(connect_rc, "Request completed successfully.")
        if joined == ["netsh", "wlan", "show", "interfaces"]:
            if interfaces_raises:
                raise OSError("netsh unavailable")
            return _Proc(interfaces_rc, interfaces_stdout, interfaces_stderr)
        raise AssertionError(f"unexpected netsh invocation: {cmd}")

    with mock.patch.object(NM.os, "name", "nt"), \
         mock.patch.object(NM.subprocess, "run", fake_run):
        return NM.NetworkManager().connect_wifi(ssid, password), argv


# ----------------------------------------------------------------------
# (b) verification comes from real state, not the exit code
# ----------------------------------------------------------------------
def test_exit_zero_with_a_disconnected_interface_is_not_verified():
    """The core regression: netsh returned 0 and nothing associated."""
    result, _ = _connect(connect_rc=0, interfaces_stdout=DISCONNECTED)

    assert result["executed"] is True, (
        "netsh accepted the request, so executed should be True"
    )
    assert result["verified"] is False, (
        "netsh returned 0 but the interface is disconnected; reporting "
        f"verified=True is a false success: {result}"
    )
    assert result["success"] is False, result


def test_a_genuinely_connected_interface_is_verified():
    result, argv = _connect(connect_rc=0, interfaces_stdout=CONNECTED_CORRECT)

    assert result["verified"] is True, result
    assert result["success"] is True, result
    assert any("interfaces" in " ".join(c) for c in argv), (
        "verification must consult the real interface state"
    )
    assert result["verification_type"] == "interface_state", result


def test_connected_to_a_different_network_is_not_verified():
    """Connected, but to some OTHER SSID, is not a connection to ours."""
    result, _ = _connect(interfaces_stdout=CONNECTED_ELSEWHERE)
    assert result["verified"] is False, (
        f"the interface is on another network: {result}"
    )
    assert result["connected_ssid"] == "SomeOtherNetwork", result


def test_unparsable_interface_output_fails_closed():
    result, _ = _connect(interfaces_stdout=UNPARSABLE)
    assert result["verified"] is False, (
        f"unreadable state must not be credited: {result}"
    )


def test_a_failing_interface_query_fails_closed():
    result, _ = _connect(interfaces_rc=1, interfaces_stderr="access denied")
    assert result["verified"] is False, result


def test_an_exception_querying_interfaces_fails_closed():
    result, _ = _connect(interfaces_raises=True)
    assert result["verified"] is False, result


def test_the_exit_code_alone_can_never_set_verified_true():
    """Exhaustive: every non-connected state yields verified=False."""
    for stdout in (DISCONNECTED, CONNECTED_ELSEWHERE, UNPARSABLE, ""):
        result, _ = _connect(connect_rc=0, interfaces_stdout=stdout)
        assert result["verified"] is False, (
            f"stdout={stdout!r} produced verified=True: {result}"
        )


# ----------------------------------------------------------------------
# (a) the PSK never persists or leaks
# ----------------------------------------------------------------------
def test_the_password_never_appears_in_the_result():
    result, _ = _connect()
    assert SECRET not in repr(result), (
        f"the PSK leaked into the returned dict: {result}"
    )


def test_the_password_never_appears_on_any_command_line():
    """A PSK in argv is visible to every process listing on the machine."""
    _, argv = _connect()
    for cmd in argv:
        assert SECRET not in " ".join(cmd), (
            f"the PSK was passed on a command line: {cmd}"
        )


def test_the_plaintext_profile_is_transient():
    """The profile file must be gone once connect_wifi returns."""
    seen = {}
    real_tempdir = NM.tempfile.TemporaryDirectory

    class TrackingTempDir(real_tempdir):
        def __enter__(self):
            self._entered = super().__enter__()
            seen["dir"] = self._entered
            return self._entered

    original_write = NM.ET.ElementTree.write

    def spy_write(self, file, **kwargs):
        path = Path(file)
        seen["path"] = path
        outcome = original_write(self, file, **kwargs)
        # Read AFTER the real write; beforehand the file is still empty.
        seen["content"] = path.read_text(encoding="utf-8")
        return outcome

    # `write` is looked up on the class at call time, so patching the
    # unbound function here is what intercepts it.
    with mock.patch.object(NM.tempfile, "TemporaryDirectory",
                           TrackingTempDir), \
         mock.patch.object(NM.ET.ElementTree, "write", spy_write):
        result, _ = _connect()

    assert seen.get("path") is not None, (
        "the profile write was never observed; the fixture is not "
        "exercising the code path under test"
    )
    assert SECRET in seen["content"], (
        "netsh needs the PSK in the profile; this asserts the fixture is "
        "actually writing it"
    )
    assert not seen["path"].exists(), (
        "the plaintext profile still exists after connect_wifi returned; "
        f"it must be removed by the TemporaryDirectory: {seen['path']}"
    )
    assert not Path(seen["dir"]).exists(), (
        f"the temp directory itself survived: {seen['dir']}"
    )
    assert result["success"] is True, result