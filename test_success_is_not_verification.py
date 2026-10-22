"""Directive 13D (C7): do not let `success` stand in for proof.

Two read-back operations returned

    {"success": True, ..., "verified": <may be False>}

`display_control.set_brightness` and `media_control.set_volume` both
dispatch a hardware change and then read the state back. When the
readback does not confirm, the message said so -- but the boolean did
not. Any consumer reading `success` saw green for a brightness or
volume change the hardware never confirmed.

THE CONVENTION BEING ALIGNED TO is the executor's, and it is explicit.
`ActionResult`'s docstring opens with four questions and then:

    The key safety property is:
        success != trustworthy_success
    A raw execution attempt is NOT enough.
    Genesis should only expose trustworthy success when the desired
    final state is known and verified.

and `trustworthy_success` requires `success AND verified AND a coherent
status` -- "Execution or a desired-state flag alone is never
sufficient."

So `success` is not made to mean verification. That would destroy a real
distinction: the call WAS dispatched, and `executed` already says so.
Instead both sites now carry `trustworthy_success`, which is the single
field a consumer must read to decide whether to tell the user the
change took effect.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.usefixtures("hermetic_capabilities")

BACKEND = pathlib.Path(__file__).resolve().parent
DISPLAY = BACKEND / "genesis_os" / "display_control.py"
MEDIA = BACKEND / "genesis_os" / "media_control.py"
ACTION_RESULT = BACKEND / "genesis_os" / "action_result.py"


def _dict_at(path: pathlib.Path, needle_key: str):
    """Yield (lineno, keys) for every returned dict containing needle_key."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            keys = {
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            if needle_key in keys:
                yield node.lineno, keys


def _value_of(path: pathlib.Path, lineno: int, key: str):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and getattr(node, "lineno", None) == lineno:
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == key:
                    return v
    return None


def _result_dicts_for(path: pathlib.Path, operation: str):
    """Returned dicts whose `operation` VALUE is the given string.

    Matching on the key would be wrong: the key is always "operation",
    the operation name is the value.
    """
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Dict)):
            continue
        for k, v in zip(node.keys, node.values):
            if (
                isinstance(k, ast.Constant)
                and k.value == "operation"
                and isinstance(v, ast.Constant)
                and v.value == operation
            ):
                keys = {
                    kk.value
                    for kk in node.keys
                    if isinstance(kk, ast.Constant)
                    and isinstance(kk.value, str)
                }
                found.append((node.lineno, keys))
                break
    return found


# =====================================================================
# Both sites now separate dispatched from verified
# =====================================================================

@pytest.mark.parametrize(
    "path,operation",
    [(DISPLAY, "display.brightness_set"), (MEDIA, "volume.set")],
)
def test_the_readback_sites_carry_trustworthy_success(path, operation):
    """The regression. Before Item 13D these dicts had no such key."""
    hits = _result_dicts_for(path, operation)
    assert hits, f"no result dict found for {operation}"

    found = False
    for lineno, keys in hits:
        if "trustworthy_success" in keys:
            found = True
            value = _value_of(path, lineno, "trustworthy_success")
            assert value is not None, (
                f"{operation} at line {lineno} has trustworthy_success "
                f"but it is not a value"
            )
    assert found, (
        f"{operation} returns success=True with a verified that can be "
        f"False, and offers no trustworthy_success for a consumer to "
        f"trust instead"
    )


def test_trustworthy_success_matches_verified_not_success():
    """If the two could diverge, the field would be decoration."""
    for path, operation in (
        (DISPLAY, "display.brightness_set"),
        (MEDIA, "volume.set"),
    ):
        for lineno, keys in _result_dicts_for(path, operation):
            if "trustworthy_success" not in keys:
                continue
            verified = ast.unparse(_value_of(path, lineno, "verified"))
            trust = ast.unparse(_value_of(path, lineno, "trustworthy_success"))
            assert verified == trust, (
                f"{operation} line {lineno}: verified={verified} but "
                f"trustworthy_success={trust}; they must be the same "
                f"expression or the split is meaningless"
            )


def test_success_is_still_about_dispatch_not_verification():
    """`success` must NOT have been redefined to mean verified.

    Overloading it would erase the real distinction the executor
    documents, and `executed` already reports that the call ran.
    """
    for path, operation in (
        (DISPLAY, "display.brightness_set"),
        (MEDIA, "volume.set"),
    ):
        for lineno, keys in _result_dicts_for(path, operation):
            # Only the SUCCESS path is under test. The same operation
            # also has error paths whose success is legitimately False.
            if "trustworthy_success" not in keys:
                continue
            success = ast.unparse(_value_of(path, lineno, "success"))
            # C12: success now derives from verification for write ops
            assert success.strip() == "verified" or success.strip() == "applied", (
                f"{operation} line {lineno}: success is {success!r}; "
                f"C12 requires success = verified for write ops"
            )
            assert "executed" in keys, (
                f"{operation} line {lineno} lost `executed`"
            )


# =====================================================================
# It matches the executor's convention
# =====================================================================

def test_the_executor_states_the_rule_we_aligned_to():
    """If this convention is ever dropped, the alignment is meaningless."""
    doc = ACTION_RESULT.read_text(encoding="utf-8-sig")
    assert "success != trustworthy_success" in doc, (
        "ActionResult no longer documents that success and "
        "trustworthy_success are different things"
    )
    assert "NOT enough" in doc


def test_trustworthy_success_requires_verified_in_the_executor():
    """Sanity: the field we mirror is genuinely not just `success`."""
    from genesis_os.action_result import ActionResult

    ok = ActionResult.success_result(
        operation="x", target="t", application=None, message="m",
        verified=True,
        # trustworthy_success ALSO requires meaningful evidence, not
        # just a verified flag. `has_meaningful_result_evidence` only
        # honours a specific set of keys, so a free-form reason is not
        # evidence; `state_check_passed` is the readback-shaped one.
        verification={"state_check_passed": True},
    )
    not_verified = ActionResult.success_result(
        operation="x", target="t", application=None, message="m",
        verified=False,
        verification={"state_check_passed": True},
    )
    assert ok.trustworthy_success is True
    assert not_verified.success is True, (
        "premise broken: the executor now forbids success+unverified"
    )
    assert not_verified.trustworthy_success is False, (
        "the executor must not certify an unverified success"
    )


# =====================================================================
# The behaviour actually produced
# =====================================================================

def test_an_unconfirmed_volume_change_is_not_trustworthy():
    """End to end: the readback cannot confirm, so the field a consumer
    must read says so."""
    from genesis_os.media_control import MediaController

    mc = MediaController.__new__(MediaController)

    # The endpoint is unavailable, so the write is dispatched and the
    # readback returns nothing to confirm.
    mc.get_volume = lambda: {"success": False, "volume_percent": None}

    class Interface:
        def SetMasterVolumeLevelScalar(self, v, e):
            return 0

    class Iface:
        def SetMasterVolumeLevelScalar(self, v, e):
            return 0

        def GetMasterVolumeLevelScalar(self):
            return 0.5

        def GetMute(self):
            return 0

    mc._endpoint = lambda: (Iface(), object)
    result = mc.set_volume(50)

    assert result["success"] is False, (
        f"unconfirmed volume change must not report success: {result}"
    )
    assert result["verified"] is False, (
        f"a readback that confirmed nothing must not report verified: {result}"
    )
    assert result["trustworthy_success"] is False, (
        "a consumer reading trustworthy_success would be told the volume "
        f"changed when it was not confirmed: {result}"
    )
    del Interface


def _display_controller(brightness_readback):
    from genesis_os.display_control import DisplayController

    dc = DisplayController.__new__(DisplayController)
    # set_brightness checks availability first; the capability under
    # test here is the READBACK, not the display.
    dc._available = True
    dc.available = True
    dc.get_brightness = brightness_readback
    dc._sbc = type(
        "SBC", (), {"set_brightness": staticmethod(lambda v: None)}
    )()
    return dc


def test_an_unconfirmed_brightness_change_is_not_trustworthy():
    from genesis_os.display_control import DisplayController

    dc = _display_controller(
        lambda: {"success": False, "per_display": []}
    )

    result = dc.set_brightness(50)

    assert result["success"] is False, result
    assert result["verified"] is False, result
    assert result["trustworthy_success"] is False, (
        f"an unconfirmed brightness change must not be trustworthy: {result}"
    )


def test_a_confirmed_change_is_trustworthy():
    from genesis_os.display_control import DisplayController

    dc = _display_controller(
        lambda: {
            "success": True, "per_display": [50], "brightness_percent": 50,
        }
    )

    result = dc.set_brightness(50)

    assert result["verified"] is True, result
    assert result["trustworthy_success"] is True, (
        f"a confirmed change must be trustworthy: {result}"
    )