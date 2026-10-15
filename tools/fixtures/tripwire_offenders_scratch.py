"""SCRATCH: unmarked capability offenders. These MUST fail by name.

No pytestmark. Not in docs/tests_tiering.json. Deliberately absent from
the tiering snapshot so they land in the fast gate by default, which is
exactly the situation a new test written tomorrow is in.

Existence proves the tripwire catches an unmarked offender rather than
merely marking the ones someone remembered to classify.
"""

import socket
import subprocess
import sys

import pytest


def test_scratch_non_loopback_network_is_caught():
    """Connects to a real, non-loopback address. Timeout keeps it fast.

    203.0.113.0/24 is TEST-NET-3 (RFC 5737): reserved for documentation,
    guaranteed not routable, so this touches the network stack and the
    DNS path without contacting anything real.
    """
    sock = socket.socket()
    sock.settimeout(0.25)
    try:
        sock.connect(("203.0.113.1", 80))
    except OSError:
        pass  # the ATTEMPT is the evidence, not the outcome
    finally:
        sock.close()


def test_scratch_non_allowlisted_executable_is_caught():
    """Starts an executable that is NOT on the harmless allowlist.

    `hostname.exe` prints the machine name and exits: read-only, instant,
    opens nothing. It is still absent from HARMLESS_EXECUTABLES, which
    is the point -- the allowlist is a closed set, so an executable
    nobody has classified yet is treated as not harmless.

    Deliberately NOT `cmd.exe`: that one IS allowlisted, because the
    product uses it for read-only registry and app queries.
    """
    result = subprocess.run(["hostname.exe"], capture_output=True)
    assert result.returncode == 0


def test_scratch_ctypes_window_station_is_caught():
    """Calls the real window station through ctypes, as the product does."""
    import ctypes
    handle = ctypes.windll.user32.GetForegroundWindow()
    assert isinstance(handle, int)