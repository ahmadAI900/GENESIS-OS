"""T24 -- tiering must demote module-level ``pytestmark = live``.

The hook used to remove ``live`` from ``item.own_markers``. A module-level
mark is owned by the module, not the item, so ``-m live`` still selected
the item and the claimed "moved live -> runtime" coverage stayed out of
the fast gate.

These tests drive a real ``pytest --collect-only`` process because the
defect is in pytest's marker resolution, not in a helper that a unit test
could exercise. They prove all three required properties:

* a ``runtime`` entry under a module-level ``live`` is not collected by
  ``-m live``;
* the same entry is collected by the fast gate's ``-m "not live"``;
* a function-level ``@pytest.mark.live`` on another ``runtime`` entry is
  still respected even though the evidence says ``runtime``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

BACKEND = Path(__file__).resolve().parent

MODULE_LIVE_NODEID = (
    "test_phase0_mixed_data_flow.py::"
    "test_production_mixed_objective_bridges_coding_output_to_os_action"
)
FUNCTION_LIVE_NODEID = (
    "test_unseen_task_semantic.py::TestEndToEndPipelineStillExecutes::"
    "test_anaphoric_move_plan_is_valid"
)


def _collect(mark_expression, target):
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "--collect-only", "-q",
            "-p", "no:cacheprovider",
            "-m", mark_expression,
            target,
        ],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def test_runtime_entry_under_module_live_is_not_collected_by_live():
    result = _collect("live", "test_phase0_mixed_data_flow.py")

    assert MODULE_LIVE_NODEID not in result.stdout, (
        "the tier snapshot calls this test runtime, but -m live still "
        f"collects it:\n{result.stdout}\n{result.stderr}"
    )
    assert result.returncode == 5, (
        "expected no tests collected, got exit code "
        f"{result.returncode}:\n{result.stdout}\n{result.stderr}"
    )


def test_the_same_entry_is_collected_by_the_fast_gate():
    result = _collect("not live", "test_phase0_mixed_data_flow.py")

    assert result.returncode == 0, (
        f"collection failed:\n{result.stdout}\n{result.stderr}"
    )
    assert MODULE_LIVE_NODEID in result.stdout, (
        "the demoted runtime test did not enter the fast gate:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_a_function_level_live_marker_is_still_respected():
    result = _collect("live", FUNCTION_LIVE_NODEID)

    assert result.returncode == 0, (
        f"collection failed:\n{result.stdout}\n{result.stderr}"
    )
    assert FUNCTION_LIVE_NODEID in result.stdout, (
        "the hook demoted an explicit function-level @pytest.mark.live "
        "because the evidence said runtime; that marker is a human "
        f"decision:\n{result.stdout}\n{result.stderr}"
    )
