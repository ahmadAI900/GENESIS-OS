"""SCRATCH: capability violations inside FIXTURE phases. These MUST fail
by name.

Removed after the measurement. Not a product file and not collected by
an ordinary run: it lives under `tools/fixtures/` and does not match
`test_*.py`, so pytest only sees it when it is passed by explicit path.

Why these three
---------------
The tripwire used to attach its capture frame from an autouse
FUNCTION-scoped fixture. That made two whole phases invisible:

  * pytest sets fixtures up highest-scope-first, so a module-scoped
    fixture was already built before any function-scoped frame existed;
  * teardown runs lowest-scope-first, so a module-scoped finalizer ran
    after the frame had been removed.

`test_scratch_non_loopback_network_is_caught` covers the call phase and
already passed before the change -- it is the control. The other three
are what the change was made for. If they ever pass silently, the
coverage has been lost again.
"""

import socket
import subprocess

import pytest

NETWORK_TARGET = ("203.0.113.1", 80)  # RFC 5737 TEST-NET-3


def _touch_network():
    sock = socket.socket()
    sock.settimeout(0.25)
    try:
        sock.connect(NETWORK_TARGET)
    except OSError:
        pass  # the ATTEMPT is the evidence, not the outcome
    finally:
        sock.close()


# ======================================================================
# 1. function-scoped fixture SETUP
# ======================================================================

@pytest.fixture
def func_setup_offender():
    _touch_network()
    yield "armed"


def test_scratch_function_fixture_setup_is_caught(func_setup_offender):
    assert func_setup_offender == "armed"


# ======================================================================
# 2. function-scoped fixture TEARDOWN
# ======================================================================

@pytest.fixture
def func_teardown_offender():
    yield "armed"
    _touch_network()


def test_scratch_function_fixture_teardown_is_caught(func_teardown_offender):
    assert func_teardown_offender == "armed"


# ======================================================================
# 3. module-scoped fixture SETUP, attributed to the first test that
#    requests it
# ======================================================================

@pytest.fixture(scope="module")
def module_setup_offender():
    _touch_network()
    return "armed"


def test_scratch_module_fixture_setup_is_caught(module_setup_offender):
    assert module_setup_offender == "armed"


# ======================================================================
# 4. module-scoped fixture TEARDOWN
#
# MEASURED ATTRIBUTION: a module-scoped finalizer runs when the LAST
# test in the module finishes, not when the test that requested the
# fixture finishes. So this violation is reported against
# `test_scratch_function_fixture_setup_executable_is_caught` -- the last
# test in this module -- and NOT against this test. The violation is
# caught and the run goes red; only the attribution differs from the
# module-SETUP case above, which is attributed to the first requesting
# test as required. Recorded here so the behaviour is not mistaken for a
# miss if this test is ever seen passing.
# ======================================================================

@pytest.fixture(scope="module")
def module_teardown_offender():
    yield "armed"
    _touch_network()


def test_scratch_module_fixture_teardown_is_caught(module_teardown_offender):
    assert module_teardown_offender == "armed"


# ======================================================================
# 5. CONTROL: the call phase, which the old design already covered.
#    If this stops failing, the instrument itself is broken and the four
#    above prove nothing.
# ======================================================================

def test_scratch_call_phase_control_is_caught():
    _touch_network()


# ======================================================================
# 6. A clean sibling in the same module, which must KEEP passing. A
#    tripwire that fails everything is not a tripwire.
# ======================================================================

def test_scratch_clean_sibling_still_passes():
    assert sum([1, 2, 3]) == 6


# ======================================================================
# 7. A non-allowlisted executable reached from a function-scoped
#    fixture's SETUP, so the check is not specific to sockets.
# ======================================================================

@pytest.fixture
def func_setup_executable_offender():
    subprocess.run(["hostname.exe"], capture_output=True)
    yield "armed"


def test_scratch_function_fixture_setup_executable_is_caught(
        func_setup_executable_offender):
    assert func_setup_executable_offender == "armed"
