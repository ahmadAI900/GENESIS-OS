"""Item 4B -- workstation.lock must report what Windows actually said.

`LockWorkStation()` returns a BOOL. The product discarded it and
hardcoded `result = True`, so a refusal by Windows (typically because no
interactive session is available) was reported as
`success=True, executed=True, verified=True` -- a security control
claiming it had locked a workstation it never locked.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from genesis_os import workstation_control as WC


@pytest.fixture
def controller():
    return WC.WorkstationController()


def _with_lock_api(return_value):
    """Patch ctypes so LockWorkStation returns exactly `return_value`."""
    fake_user32 = mock.MagicMock()
    fake_user32.LockWorkStation.return_value = return_value
    patcher = mock.patch.object(WC, "ctypes")
    fake_ctypes = patcher.start()
    fake_ctypes.windll.user32 = fake_user32
    fake_ctypes.sizeof = lambda t: 8
    return patcher, fake_user32


def test_a_refused_lock_is_reported_as_a_failure(controller):
    """LockWorkStation() -> 0 must NOT produce success."""
    patcher, user32 = _with_lock_api(0)
    try:
        result = controller.lock()
    finally:
        patcher.stop()

    assert result["success"] is False, (
        "Windows refused the lock (LockWorkStation returned 0) but the "
        f"product reported success: {result}"
    )
    assert result["verified"] is False, result
    assert result["executed"] is False, (
        f"executed=True alongside success=False claims the request took "
        f"effect when Windows declined it: {result}"
    )
    assert "did not accept" in result.get("message", "").lower(), result


def test_an_accepted_lock_is_reported_as_success(controller):
    """The normal path must keep reporting success."""
    patcher, user32 = _with_lock_api(1)
    try:
        result = controller.lock()
    finally:
        patcher.stop()

    assert result["success"] is True, result
    assert result["verified"] is True, result
    assert result["executed"] is True, result
    assert user32.LockWorkStation.called


@pytest.mark.parametrize("truthy", [1, -1, True, 42])
def test_any_nonzero_return_counts_as_accepted(controller, truthy):
    """Windows uses nonzero-success; every nonzero value must pass."""
    patcher, _ = _with_lock_api(truthy)
    try:
        result = controller.lock()
    finally:
        patcher.stop()
    assert result["success"] is True, result


def test_an_exception_is_still_reported_as_failure(controller):
    """The pre-existing exception path must be preserved."""
    patcher, user32 = _with_lock_api(1)
    user32.LockWorkStation.side_effect = OSError("api unavailable")
    try:
        result = controller.lock()
    finally:
        patcher.stop()

    assert result["success"] is False, result
    assert result["executed"] is False, result
    assert result["verified"] is False, result
    assert "api unavailable" in result.get("error", ""), result


def test_the_api_return_value_is_not_hardcoded(controller):
    """Structural: the call must be assigned, not discarded."""
    import ast

    source = Path(WC.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "lock")

    hardcoded = []
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "result" for t in node.targets)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, bool)):
            hardcoded.append(node.lineno)

    assert not hardcoded, (
        f"lock() still hardcodes `result = True` at line(s) {hardcoded}; "
        "the LockWorkStation return value must be used"
    )