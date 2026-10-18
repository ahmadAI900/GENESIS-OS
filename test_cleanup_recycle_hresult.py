"""Item 14B (C9): the "already empty" HRESULT must be the right one.

`CleanupManager.empty_recycle_bin` decides whether a non-zero HRESULT
from `SHEmptyRecycleBinW` means "there was nothing to empty" (benign,
report success) or "emptying failed". It used to decide that with:

    already_empty = result == -2147024879 or result == 0x80070091 % (
        1 << 32
    ) - (1 << 32)

which resolves as `result == -2147024879 or result == ((0x80070091 %
(1 << 32)) - (1 << 32))`.

The contract asserted here:

    ERROR_DIR_NOT_EMPTY (0x80070091) -> already empty -> success
    anything else non-zero          -> failure        -> success=False

and, because `already_empty` also drives `verified`, getting this wrong
is not cosmetic: the wrong constant certified a failed operation as
verified.
"""
from __future__ import annotations

import pytest

from genesis_os.cleanup_manager import (
    ERROR_DIR_NOT_EMPTY_HRESULT,
    CleanupManager,
)


ERROR_NOT_SAME_DEVICE = 0x80070011 - (1 << 32)  # == -2147024879


def _run_with_hresult(monkeypatch, hresult, *, stats=None):
    """Drive empty_recycle_bin against a stubbed shell32 returning `hresult`.

    `recycle_bin_stats` is stateful: the first call (the BEFORE reading)
    reports whatever `stats` says, and every later call (the AFTER
    re-query) reports an empty bin. Without that, the success path could
    never verify -- it would re-read the same populated stats forever.
    """
    mgr = CleanupManager()
    stats = stats if stats is not None else {
        "success": True,
        "item_count": 4,
        "size_mb": 10.0,
    }
    empty = {"success": True, "item_count": 0, "size_mb": 0.0}
    calls = {"n": 0}

    def _stats():
        calls["n"] += 1
        return dict(stats) if calls["n"] == 1 else dict(empty)

    monkeypatch.setattr(mgr, "recycle_bin_stats", _stats)

    class _Shell32:
        @staticmethod
        def SHEmptyRecycleBinW(_root, _path, _flags):
            return hresult

    class _Windll:
        shell32 = _Shell32()

    class _WindllHolder:
        windll = _Windll()

    monkeypatch.setattr(
        "genesis_os.cleanup_manager.ctypes", _WindllHolder, raising=True
    )
    return mgr.empty_recycle_bin()


# --------------------------------------------------------------------------
# The constant itself
# --------------------------------------------------------------------------

def test_the_named_hresult_is_error_dir_not_empty():
    assert ERROR_DIR_NOT_EMPTY_HRESULT == 0x80070091 - (1 << 32)
    assert ERROR_DIR_NOT_EMPTY_HRESULT == -2147024751
    assert ERROR_DIR_NOT_EMPTY_HRESULT & 0xFFFFFFFF == 0x80070091


def test_the_named_hresult_is_not_error_not_same_device():
    """The whole point: the two codes are different numbers."""
    assert ERROR_DIR_NOT_EMPTY_HRESULT != ERROR_NOT_SAME_DEVICE


# --------------------------------------------------------------------------
# The empty-dir code is treated as benign
# --------------------------------------------------------------------------

def test_the_empty_dir_code_reports_already_empty(monkeypatch):
    result = _run_with_hresult(monkeypatch, ERROR_DIR_NOT_EMPTY_HRESULT)

    assert result["success"] is True, result
    assert result["verified"] is True, result
    assert result["executed"] is True
    assert result["after_item_count"] == 0
    assert result["item_count"] == 0
    assert "already empty" in result["message"]


def test_zero_still_reports_success_and_verifies(monkeypatch):
    result = _run_with_hresult(
        monkeypatch,
        0,
        stats={"success": True, "item_count": 4, "size_mb": 10.0},
    )

    assert result["success"] is True, result
    assert result["executed"] is True
    assert result["verified"] is True, (
        "a real empty (HRESULT 0) with an empty AFTER re-query must verify"
    )
    assert result["before_item_count"] == 4
    assert result["after_item_count"] == 0


# --------------------------------------------------------------------------
# Unrelated codes must NOT be treated as benign
# --------------------------------------------------------------------------

def test_error_not_same_device_is_no_longer_treated_as_already_empty(monkeypatch):
    """The regression: this code used to short-circuit to success."""
    result = _run_with_hresult(monkeypatch, ERROR_NOT_SAME_DEVICE)

    assert result["success"] is False, (
        "ERROR_NOT_SAME_DEVICE is a genuine failure and must not be "
        f"reported as success; got {result['success']!r}"
    )
    assert result["verified"] is False, (
        "a failed empty must never be certified verified"
    )
    assert result["executed"] is True
    assert result["item_count"] is None
    assert result["after_item_count"] is None


def test_an_arbitrary_nonzero_code_is_a_failure(monkeypatch):
    result = _run_with_hresult(monkeypatch, 0x80070005)  # ACCESS_DENIED

    assert result["success"] is False, result
    assert result["verified"] is False, result
    assert result["executed"] is True


def test_several_unrelated_codes_are_all_refused(monkeypatch):
    for code in (
        0x80070005,  # ACCESS_DENIED
        0x80070006,  # INVALID_HANDLE
        0x80070015,  # NOT_READY
        ERROR_NOT_SAME_DEVICE,
        1,
        -1,
    ):
        result = _run_with_hresult(monkeypatch, code)
        assert result["success"] is False, f"code {code!r} was accepted"
        assert result["verified"] is False, f"code {code!r} was verified"


# --------------------------------------------------------------------------
# Structural guard
# --------------------------------------------------------------------------

def test_no_bare_error_not_same_device_literal_remains():
    """The literal must not reappear in EXECUTABLE code.

    Checked against the AST rather than the raw text: comments are not
    in the AST at all, so the comment block explaining which literal
    was removed is allowed to name it. A text search would either flag
    that explanation or be defeated by reformatting.
    """
    import ast
    import pathlib
    import sys

    path = pathlib.Path(sys.modules[CleanupManager.__module__].__file__)
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))

    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
        and node.value == ERROR_NOT_SAME_DEVICE
    ]

    assert not offenders, (
        f"the ERROR_NOT_SAME_DEVICE literal ({ERROR_NOT_SAME_DEVICE}) is "
        f"back in executable code at line(s) {offenders}"
    )


def test_the_already_empty_test_uses_the_named_constant():
    """The comparison must reference the name, not a literal."""
    import ast
    import pathlib
    import sys

    path = pathlib.Path(sys.modules[CleanupManager.__module__].__file__)
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))

    names_used = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }
    assert "ERROR_DIR_NOT_EMPTY_HRESULT" in names_used, (
        "already_empty must be computed from the named constant"
    )


@pytest.mark.parametrize("code", [0, 0x80070091 - (1 << 32)])
def test_both_benign_outcomes_claim_zero_items(code, monkeypatch):
    result = _run_with_hresult(monkeypatch, code)

    assert result["success"] is True, result
    assert result["item_count"] == 0, result