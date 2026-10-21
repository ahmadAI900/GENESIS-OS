"""Item 23C (C28): clipboard.copy claimed success on an unconfirmed readback.

`ClipboardManager.copy` performs the write, reads the clipboard back,
computes `verified = readback == text` -- and then returned
`"success": True` unconditionally. The readback result drove only the
`verified` flag and the message. A caller that read `success` saw green
for a copy the clipboard never confirmed: the text was overwritten
before we read it, or the write silently did not land.

The contract asserted here:

    readback matches    -> success=True,  verified=True,
                           trustworthy_success=True,  executed=True
    readback mismatches -> success=False, verified=False,
                           trustworthy_success=False, executed=True

`executed` deliberately stays True on a mismatch: pyperclip.copy ran
without exception, so the WRITE was attempted and completed. What
failed is the confirmation of the final state -- which is why the
mismatch is `verification_failed` territory, not an execution error,
and why the result must NOT carry an `error` (an `error` makes the
executor collapse the status to `execution_failed`, erasing the
precise "attempted but final state unconfirmed" signal).

`trustworthy_success` is the Item 13D field (display_control.py): the
name consumers are told to read instead of `success`.
"""
from __future__ import annotations

import pathlib
import sys

from genesis_os.clipboard_manager import ClipboardManager


class _FakePyperclip:
    """In-memory clipboard; optionally sabotages the readback.

    `readback_override` simulates a clipboard that did not keep our
    text: another app stole it, or the write silently failed. When it
    is None, paste() returns whatever copy() stored (the honest match).
    """

    def __init__(self, readback_override=None):
        self._stored = None
        self._override = readback_override
        self.copy_calls = []

    def copy(self, text):
        self._stored = text
        self.copy_calls.append(text)

    def paste(self):
        if self._override is not None:
            return self._override
        return self._stored


def _manager(fake):
    manager = ClipboardManager()
    manager.available = True
    manager._pyperclip = fake
    return manager


# --------------------------------------------------------------------------
# The defect: the mismatch case was reported as a success.
# --------------------------------------------------------------------------

def test_a_readback_mismatch_is_not_a_success():
    manager = _manager(_FakePyperclip(readback_override="SOMETHING ELSE ENTIRELY"))

    result = manager.copy("Genesis secret payload")

    assert result["success"] is False, (
        "the readback did not confirm the copied text, yet success="
        f"{result['success']!r} told callers the copy worked"
    )
    assert result["verified"] is False, result
    assert result["executed"] is True, (
        "pyperclip.copy ran without exception; the write was "
        "attempted, so executed must stay True"
    )
    assert "did not confirm" in result["message"], (
        f"the honest message is gone: {result['message']!r}"
    )


def test_a_readback_mismatch_carries_trustworthy_success_false():
    manager = _manager(_FakePyperclip(readback_override="not what we wrote"))

    result = manager.copy("the text we asked for")

    assert "trustworthy_success" in result, (
        "the Item 13D field consumers must read is missing; keys="
        f"{sorted(result)}"
    )
    assert result["trustworthy_success"] is False, (
        "an unconfirmed readback must never be a trustworthy success"
    )


def test_a_readback_mismatch_is_not_labeled_an_execution_error():
    """Precision guard: mismatch -> verification_failed, not execution_failed.

    pyperclip.copy succeeded; only the confirmation failed. Adding an
    `error` here would make the executor report the status as
    `execution_failed`, telling the user the copy call itself broke
    when it did not.
    """
    manager = _manager(_FakePyperclip(readback_override="interference"))

    result = manager.copy("payload")

    assert result["success"] is False, result
    assert result.get("error") in (None, ""), (
        f"a readback mismatch is not an execution error: {result.get('error')!r}"
    )


def test_copy_never_hardcodes_success_true():
    """AST sweep: `success` may not be hardcoded while `verified` is dynamic.

    Guards the exact shape of the defect -- `"success": True` sitting
    next to a computed `"verified"` -- anywhere in this module. A dict
    that hardcodes BOTH success and verified (the early-rejection and
    paste paths) is honest and passes.
    """
    import ast

    path = pathlib.Path(
        sys.modules[ClipboardManager.__module__].__file__
    )
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    offenders = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        values: dict[str, object] = {}
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                try:
                    values[key.value] = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    values[key.value] = "<dynamic>"

        if values.get("success") is True and "verified" in values:
            if values.get("verified") is not True:
                offenders.append(node.lineno)

    assert not offenders, (
        "dicts at "
        f"{offenders} hardcode success=True while verified is dynamic "
        "-- success must be bound to the readback result"
    )


# --------------------------------------------------------------------------
# Guards: the honest paths must not move.
# --------------------------------------------------------------------------

def test_a_matching_readback_is_a_trustworthy_success():
    manager = _manager(_FakePyperclip())

    result = manager.copy("Genesis AIOS test payload")

    assert result["success"] is True, result
    assert result["verified"] is True, result
    assert result["executed"] is True, result
    assert "trustworthy_success" in result, (
        "the Item 13D field must exist on every copy result; keys="
        f"{sorted(result)}"
    )
    assert result["trustworthy_success"] is True, result
    assert result["content_match"] is True, result
    assert manager._pyperclip.copy_calls == ["Genesis AIOS test payload"]


def test_empty_text_still_rejects_before_any_clipboard_write():
    manager = _manager(_FakePyperclip())

    result = manager.copy("   ")

    assert result["success"] is False, result
    assert result["executed"] is False, (
        "no write was attempted, so executed must be False"
    )
    assert manager._pyperclip.copy_calls == [], (
        "the clipboard must not be touched for empty text"
    )
