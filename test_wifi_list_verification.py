"""Item 23A (C25): network.list_wifi honesty — executed and verified.

`NetworkManager.list_wifi` runs `netsh wlan show networks mode=bssid`.
Before this item the result reported, in one line:

    "executed": True, "verified": result.returncode == 0

so `executed` was True even when the command failed, and `verified`
merely restated the exit code -- the definition of exit-code-only
"verification". The exception path and the non-Windows path returned
dicts with NEITHER key, so a consumer reading `result["executed"]` on
any failure hit a KeyError.

The contract asserted here:

    success=True   -> executed=True, verified = networks were PARSED
                      from the netsh output (not merely: exit code 0)
    success=False  -> executed=False, verified=False
    exception      -> executed=False, verified=False (both keys present)
    non-Windows    -> executed=False, verified=False (both keys present)

HONEST LIMIT, pinned by a test so it cannot drift: a successful scan
that reports zero networks (genuinely empty radio environment, or
output we cannot parse) is executed but NOT verified. Verification
requires the networks themselves to be read back. Failing closed here
is deliberate -- an empty result is indistinguishable from
unrecognisable output without a positive signal.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from genesis_os.network_manager import NetworkManager


# A realistic `netsh wlan show networks mode=bssid` capture: SSID
# headers AND their indented BSSID sub-entries. The BSSID lines are the
# trap -- they must not be parsed as networks.
NETSH_WITH_NETWORKS = (
    "There is 1 interface on the system.\r\n"
    "\r\n"
    "Interface name : Wi-Fi\r\n"
    "    SSID 1 : MyHomeWiFi\r\n"
    "        Network type            : Infrastructure\r\n"
    "        Authentication          : WPA2-Personal\r\n"
    "        Encryption              : CCMP\r\n"
    "        BSSID 1                 : 00:11:22:33:44:55\r\n"
    "             Signal             : 76%\r\n"
    "             Radio type         : 802.11n\r\n"
    "             Channel            : 6\r\n"
    "\r\n"
    "    SSID 2 : CoffeeShop-Guest\r\n"
    "        Network type            : Infrastructure\r\n"
    "        Authentication          : Open\r\n"
    "        Encryption              : None\r\n"
    "        BSSID 1                 : aa:bb:cc:dd:ee:ff\r\n"
    "             Signal             : 43%\r\n"
)

NETSH_NO_NETWORKS = (
    "There is 1 interface on the system.\r\n"
    "\r\n"
    "Interface name : Wi-Fi\r\n"
)

# Exit code 0 but no parseable network inventory at all: the "verified
# = returncode == 0" line claimed True for this output.
NETSH_UNPARSEABLE = "The Wireless AutoConfig Service is not running.\r\n"


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeOS:
    """Minimal stand-in: network_manager only ever asks os.name."""

    def __init__(self, name):
        self.name = name


@pytest.fixture
def nt_platform(monkeypatch):
    """Force the Windows branch regardless of the host actually running.

    Replaces the module's `os` reference rather than mutating the real
    `os` module (the Item 14A trap: patching the genuine global breaks
    unrelated teardown).
    """
    monkeypatch.setattr(
        "genesis_os.network_manager.os",
        _FakeOS("nt"),
    )


def _patch_run(monkeypatch, completed):
    monkeypatch.setattr(
        "genesis_os.network_manager.subprocess.run",
        lambda *a, **k: completed,
    )


# --------------------------------------------------------------------------
# The success path: netsh ran AND its output yielded networks.
# --------------------------------------------------------------------------

def test_a_successful_listing_parses_networks_from_output(nt_platform, monkeypatch):
    _patch_run(monkeypatch, _Completed(0, NETSH_WITH_NETWORKS))

    result = NetworkManager().list_wifi()

    assert result["success"] is True, result
    assert result["executed"] is True, (
        "netsh ran and produced an inventory; executed="
        f"{result['executed']!r} would deny the listing happened"
    )
    assert result["verified"] is True, (
        "the networks were parsed out of the real netsh output; "
        f"verified={result['verified']!r}"
    )
    assert result["networks"] == ["MyHomeWiFi", "CoffeeShop-Guest"], (
        f"parsed {result.get('networks')!r} from the capture"
    )


def test_bssid_entries_are_not_counted_as_networks(nt_platform, monkeypatch):
    """Each SSID block carries indented BSSID sub-entries.

    BSSID lines start with a letter, not with "SSID", so they must not
    inflate the parsed inventory. This guard exists because the parse
    is the verification -- counting BSSID rows as networks would verify
    a listing twice over.
    """
    _patch_run(monkeypatch, _Completed(0, NETSH_WITH_NETWORKS))

    result = NetworkManager().list_wifi()

    assert result["verified"] is True
    assert len(result["networks"]) == 2, (
        "BSSID sub-entries were parsed as networks: "
        f"{result['networks']!r}"
    )


def test_success_and_executed_agree_on_the_success_path(nt_platform, monkeypatch):
    _patch_run(monkeypatch, _Completed(0, NETSH_WITH_NETWORKS))

    result = NetworkManager().list_wifi()

    assert result["success"] == result["executed"] is True


# --------------------------------------------------------------------------
# Failure paths: the listing was not carried out, so nothing was
# executed -- and with no inventory there is nothing to verify.
# --------------------------------------------------------------------------

def test_a_failed_listing_reports_executed_false(nt_platform, monkeypatch):
    _patch_run(monkeypatch, _Completed(1, "", "The Wireless AutoConfig Service is not running."))

    result = NetworkManager().list_wifi()

    assert result["success"] is False, result
    assert "executed" in result, (
        "every list_wifi failure path must carry the executed key; "
        f"got keys {sorted(result)}"
    )
    assert result["executed"] is False, (
        "netsh exited non-zero and produced no inventory; executed="
        f"{result['executed']!r} contradicts success={result['success']!r}"
    )
    assert "verified" in result
    assert result["verified"] is False


def test_an_exception_reports_executed_and_verified_false(nt_platform, monkeypatch):
    def _boom(*a, **k):
        raise OSError("netsh is not installed")

    monkeypatch.setattr(
        "genesis_os.network_manager.subprocess.run", _boom
    )

    result = NetworkManager().list_wifi()

    assert result["success"] is False, result
    assert "executed" in result, (
        "the exception path returned no executed key; keys="
        f"{sorted(result)}"
    )
    assert result["executed"] is False
    assert "verified" in result
    assert result["verified"] is False


def test_non_windows_reports_executed_false(monkeypatch):
    monkeypatch.setattr(
        "genesis_os.network_manager.os", _FakeOS("posix")
    )

    def _never(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("netsh must not run on a non-Windows host")

    monkeypatch.setattr(
        "genesis_os.network_manager.subprocess.run", _never
    )

    result = NetworkManager().list_wifi()

    assert result["success"] is False, result
    assert "executed" in result, (
        "the non-Windows path returned no executed key; keys="
        f"{sorted(result)}"
    )
    assert result["executed"] is False
    assert "verified" in result
    assert result["verified"] is False


# --------------------------------------------------------------------------
# The exit-code-only defect itself: an exit of 0 is NOT a verification.
# --------------------------------------------------------------------------

def test_exit_zero_without_parseable_networks_is_not_verified(nt_platform, monkeypatch):
    """Exit 0 + nothing recognisable in the output -> verified must be False.

    Before this item `verified = result.returncode == 0` claimed True
    for exactly this: the command ran, and the output contained no
    networks we could read back.
    """
    _patch_run(monkeypatch, _Completed(0, NETSH_UNPARSEABLE))

    result = NetworkManager().list_wifi()

    assert result["success"] is True, result
    assert result["executed"] is True, (
        "the command ran to completion, so it was executed"
    )
    assert result["verified"] is False, (
        "verified=True was claimed from the exit code alone; no "
        "network was read back from the output"
    )
    assert result["networks"] == [], result


def test_a_successful_scan_of_an_empty_radio_environment_is_not_verified(
    nt_platform, monkeypatch,
):
    """HONEST LIMIT: genuinely zero networks is still verified=False.

    We cannot distinguish "no networks in range" from "output we failed
    to parse" without a positive signal, so verification fails closed.
    `executed` remains True -- the scan DID run -- and `success` remains
    True -- netsh completed.
    """
    _patch_run(monkeypatch, _Completed(0, NETSH_NO_NETWORKS))

    result = NetworkManager().list_wifi()

    assert result["success"] is True, result
    assert result["executed"] is True, result
    assert result["verified"] is False, (
        "no network was read back, so nothing corroborates a listing"
    )


# --------------------------------------------------------------------------
# Structural guards: the two defects cannot come back.
# --------------------------------------------------------------------------

def test_no_return_dict_pairs_executed_true_with_success_false(monkeypatch):
    """AST sweep: a failure dict must never claim it executed."""
    import ast

    path = pathlib.Path(
        sys.modules[NetworkManager.__module__].__file__
    )
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    offenders = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        literal: dict[str, object] = {}
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                try:
                    literal[key.value] = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    literal[key.value] = "<dynamic>"

        if literal.get("success") is False and literal.get("executed") is True:
            offenders.append(node.lineno)

    assert not offenders, (
        "result dicts at "
        f"{offenders} pair success=False with executed=True"
    )


def test_every_list_wifi_return_carry_executed_and_verified():
    """AST sweep: every list_wifi return dict must expose both keys.

    The pre-fix defect was not only wrong VALUES but missing KEYS on
    the exception and non-Windows paths. This guard pins presence on
    every literal dict the function can return, so a new failure path
    added later without the keys fails here first.
    """
    import ast

    path = pathlib.Path(
        sys.modules[NetworkManager.__module__].__file__
    )
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)

    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "list_wifi"
    )
    missing = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Return):
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            continue
        keys = {
            key.value
            for key in value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        if "operation" not in keys:
            continue
        string_values = {
            value_el.value
            for value_el in value.values
            if isinstance(value_el, ast.Constant)
            and isinstance(value_el.value, str)
        }
        if "network.list_wifi" not in string_values:
            continue
        absent = {"executed", "verified"} - keys
        if absent:
            missing.append((node.lineno, sorted(absent)))

    assert not missing, (
        "list_wifi return dicts at "
        f"{missing} are missing executed/verified keys"
    )
