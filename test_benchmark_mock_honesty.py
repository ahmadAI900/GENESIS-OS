"""Item 5B -- a mocked benchmark run must never claim real verification.

`benchmark/runner.py::_MockOSManager` returned `"verified": True` for
every capability. Nothing executed, so nothing could be verified: the
flag asserted a post-state check that never happened, and two of the
benchmark's twelve metrics ("observation" and "verification") inherited
that claim and reported a pass whose only evidence was the mock itself.

The project already states the contract this violated, in
`benchmark_real_os/__init__.py`:

    MOCKED  Execution layer is mocked (e.g. _MockOSManager).
            Used by the legacy 500-task benchmark for
            cross-host reproducibility.
    "This package never labels a mocked or simulated OS execution
     as REAL_OS."
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark.runner import BenchmarkRunner, _MockOSManager


# ----------------------------------------------------------------------
# The mock itself
# ----------------------------------------------------------------------
def test_the_mock_never_claims_verified_true():
    result = _MockOSManager().file_delete("C:/x.txt")
    assert result["verified"] is False, (
        "the mock claims a verification that never happened: "
        f"{result}"
    )


@pytest.mark.parametrize("capability", [
    "file_create", "folder_delete", "browser_click",
    "system_status", "anything_at_all",
])
def test_no_capability_is_ever_marked_verified(capability):
    result = getattr(_MockOSManager(), capability)("target")
    assert result["verified"] is False, result


def test_the_mock_marks_itself_as_mocked():
    """A consumer must be able to tell this apart from a real result."""
    result = _MockOSManager().file_move("a", "b")
    assert result.get("mocked") is True, result
    assert result.get("verification_type") == "mocked", result
    assert "mocked" in (result.get("verification_reason") or "").lower()


def test_the_mock_still_reports_structural_success():
    """Honesty must not break the pipeline the benchmark exercises.

    The mock exists so validation/safety/dispatch/normalization can run
    end-to-end. `success` stays True; only the verification claim goes.
    """
    result = _MockOSManager().file_read("C:/x.txt")
    assert result["success"] is True, result
    assert result["executed"] is True, result


# ----------------------------------------------------------------------
# The runner declares its execution layer
# ----------------------------------------------------------------------
def test_the_runner_declares_a_mocked_execution_layer():
    runner = BenchmarkRunner()
    declaration = runner.execution_layer_declaration()
    assert declaration["execution_layer"] == "MOCKED", declaration
    assert declaration["mocked"] is True, declaration
    assert declaration["real_os"] is False, (
        f"a mocked run must never declare itself REAL_OS: {declaration}"
    )


def test_the_declaration_names_the_alternative():
    """A reader must be told where real verification actually lives."""
    runner = BenchmarkRunner()
    note = runner.execution_layer_declaration()["note"]
    assert "benchmark_real_os" in note, note
    assert "mocked" in note.lower(), note


# ----------------------------------------------------------------------
# The metrics that used to cite the fabricated flag
# ----------------------------------------------------------------------
def _score_levels(source: str):
    """Map metric name -> pass flag, resolving simple local assignments.

    Each MetricScore call passes a local name (e.g. ``obs_passed``), so
    the walk resolves that name back to its assignment in the same body
    and records the literal value when it is a constant.
    """
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_score")

    # name -> literal value, for simple `x = True/False` assignments.
    consts = {}
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)):
            consts[node.targets[0].id] = node.value.value

    out = {}
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "MetricScore"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            passed = node.args[1] if len(node.args) > 1 else None
            if isinstance(passed, ast.Name):
                if passed.id in consts:
                    out[node.args[0].value] = consts[passed.id]
            elif isinstance(passed, ast.Constant):
                out[node.args[0].value] = passed.value
    return out


@pytest.mark.parametrize("metric", ["observation", "verification"])
def test_a_mocked_run_cannot_pass_a_physical_metric(metric):
    """These two must be a constant False, not a variable derived
    from a mocked result."""
    import benchmark.runner as runner_module

    scores = _score_levels(
        Path(runner_module.__file__).read_text(encoding="utf-8")
    )
    assert metric in scores, f"{metric} metric not found: {scores}"
    assert scores[metric] is False, (
        f"the {metric} metric is not pinned to False; it is "
        f"{scores[metric]!r} and can still be flipped to a pass by a "
        "mocked result"
    )


def test_no_scoring_detail_still_cites_the_fabricated_flag():
    """The old detail strings advertised the mock's fake verification."""
    import benchmark.runner as runner_module

    source = Path(runner_module.__file__).read_text(encoding="utf-8")
    assert "Mock OSManager reports verified=True" not in source, (
        "a scoring detail still cites the mock's fabricated verified=True"
    )
    assert "Mock result is verified=True" not in source, (
        "a scoring detail still cites the mock's fabricated verified=True"
    )


def test_the_mock_source_contains_no_hardcoded_verified_true():
    """Structural: the literal cannot come back unnoticed."""
    import benchmark.runner as runner_module

    source = Path(runner_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef)
               and n.name == "_MockOSManager")
    offenders = [
        node.lineno for node in ast.walk(cls)
        if isinstance(node, ast.Dict)
        for k, v in zip(node.keys, node.values)
        if isinstance(k, ast.Constant) and k.value == "verified"
        and isinstance(v, ast.Constant) and v.value is True
    ]
    assert not offenders, (
        f"_MockOSManager hardcodes verified=True at line(s) {offenders}"
    )